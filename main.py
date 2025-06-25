import os
import io
import time
import json
import logging
import base64
import re

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from PIL import Image
import requests
from dotenv import load_dotenv

# 1. ИНИЦИАЛИЗАЦИЯ
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')
YANDEX_KEY_FILE  = os.getenv('YANDEX_KEY_FILE', 'yandex_key.json')

assert TELEGRAM_TOKEN,   "TELEGRAM_TOKEN is not set!"
assert YANDEX_FOLDER_ID, "YANDEX_FOLDER_ID is not set!"
assert os.path.exists(YANDEX_KEY_FILE), "YANDEX_KEY_FILE is missing!"

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot)

# 2. ЯНДЕКС IAM TOKEN (автоматическое получение и кэширование)
_IAM_TOKEN = None
_IAM_EXPIRES = 0

def get_iam_token():
    """
    Получение IAM токена для сервисного аккаунта.
    Используется JWT-подпись приватным ключом.
    """
    global _IAM_TOKEN, _IAM_EXPIRES
    if _IAM_TOKEN and _IAM_EXPIRES > time.time() + 300:
        return _IAM_TOKEN
    with open(YANDEX_KEY_FILE, "r") as f:
        key = json.load(f)

    try:
        import jwt  # pyjwt
    except ImportError:
        raise ImportError("Установите библиотеку pyjwt: pip install pyjwt[crypto]")

    now = int(time.time())
    payload = {
        "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        "iss": key["service_account_id"],
        "iat": now,
        "exp": now + 360,
    }
    # Приватный ключ должен быть в PEM-формате в поле "private_key"
    encoded_jwt = jwt.encode(
        payload,
        key["private_key"],
        algorithm="PS256",
        headers={"kid": key["id"]}
    )

    url = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
    resp = requests.post(url, json={"jwt": encoded_jwt})
    if resp.status_code != 200:
        logger.error(f"IAM token error: {resp.status_code}, {resp.text}")
        raise RuntimeError("Failed to obtain Yandex IAM token")
    result = resp.json()
    _IAM_TOKEN = result["iamToken"]
    _IAM_EXPIRES = int(time.time()) + 3600 * 11  # 11 часов
    return _IAM_TOKEN

# 3. ЯНДЕКС OCR (VISION)
def yandex_ocr(img_bytes):
    iam_token = get_iam_token()
    url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json"
    }
    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
    data = {
        "folderId": YANDEX_FOLDER_ID,
        "analyze_specs": [
            {
                "content": img_b64,
                "features": [{"type": "TEXT_DETECTION", "text_detection_config": {"language_codes": ["ru"]}}]
            }
        ]
    }
    resp = requests.post(url, headers=headers, json=data, timeout=30)
    try:
        result = resp.json()
    except Exception:
        logger.error(f"Ответ не JSON: {resp.text}")
        return ""
    try:
        blocks = result["results"][0]["results"][0]["textDetection"]["pages"][0]["blocks"]
        full_text = []
        for block in blocks:
            for line in block.get("lines", []):
                full_text.append(' '.join([w["text"] for w in line["words"]]))
        return '\n'.join(full_text).strip()
    except Exception as e:
        logger.error(f"OCR error: {e}, raw={result}")
        return ""

# 4. TELEGRAM BOT
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    await msg.reply("Привет! Отправь фото (скриншот или снимок экрана), и я распознаю текст, задание и километраж с помощью Yandex Vision OCR.")

@dp.message_handler(content_types=["photo"])
async def handle_photo(msg: types.Message):
    file_info = await bot.get_file(msg.photo[-1].file_id)
    file = await bot.download_file(file_info.file_path)
    img_bytes = file.read()
    text = yandex_ocr(img_bytes)
    if not text:
        await msg.reply("Ошибка распознавания текста или не удалось получить ответ от Yandex Vision.")
        return

    job = re.search(r'[Зз]адани[ея][: ]+([^\n,;]+)', text)
    km  = re.search(r'(\d+)[\s-]*км', text)
    job = job.group(1).strip() if job else 'не найдено'
    km  = km.group(1) if km else 'не найдено'

    await msg.reply(
        f"📋 *Распознано:*\n"
        f"– Задание: `{job}`\n"
        f"– Километраж: `{km} км`\n\n"
        f"🗒 Распознанный текст:\n{text}",
        parse_mode='Markdown'
    )

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
