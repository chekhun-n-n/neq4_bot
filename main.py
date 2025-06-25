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
import jwt   # теперь есть в requirements
from dotenv import load_dotenv

# --- 1. Загрузка ENV ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

# Вы можете хранить JSON-сервисного ключа прямо в переменной:
YANDEX_KEY_JSON = os.getenv('YANDEX_KEY_JSON')
if not YANDEX_KEY_JSON:
    # либо на диске (но тогда надо положить yandex_key.json рядом с main.py)
    YANDEX_KEY_FILE = os.getenv('YANDEX_KEY_FILE', 'yandex_key.json')
    assert os.path.exists(YANDEX_KEY_FILE), "YANDEX_KEY_FILE not found!"
    with open(YANDEX_KEY_FILE, 'r') as f:
        key = json.load(f)
else:
    key = json.loads(YANDEX_KEY_JSON)

assert TELEGRAM_TOKEN,   "TELEGRAM_TOKEN is not set!"
assert YANDEX_FOLDER_ID, "YANDEX_FOLDER_ID is not set!"

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot)

# --- 2. Кэширование IAM-токена ---
_IAM_TOKEN = None
_IAM_EXPIRES = 0

def get_iam_token():
    global _IAM_TOKEN, _IAM_EXPIRES
    if _IAM_TOKEN and _IAM_EXPIRES > time.time() + 300:
        return _IAM_TOKEN

    # Формируем JWT
    now = int(time.time())
    payload = {
        "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        "iss": key["service_account_id"],
        "iat": now,
        "exp": now + 360,
    }
    signed = jwt.encode(
        payload,
        key["private_key"],
        algorithm="PS256",
        headers={"kid": key["id"]},
    )
    # Запрашиваем IAM token
    resp = requests.post(
        "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        json={"jwt": signed},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    _IAM_TOKEN = data["iamToken"]
    _IAM_EXPIRES = now + 3600 * 11
    return _IAM_TOKEN

# --- 3. OCR через Yandex Vision ---
def yandex_ocr(img_bytes: bytes) -> str:
    token = get_iam_token()
    img_b64 = base64.b64encode(img_bytes).decode('utf-8')
    payload = {
        "folderId": YANDEX_FOLDER_ID,
        "analyze_specs": [{
            "content": img_b64,
            "features": [{
                "type": "TEXT_DETECTION",
                "text_detection_config": {"language_codes": ["ru"]}
            }]
        }]
    }
    r = requests.post(
        "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=20
    )
    r.raise_for_status()
    res = r.json()
    try:
        blocks = res["results"][0]["results"][0]["textDetection"]["pages"][0]["blocks"]
        lines = []
        for b in blocks:
            for ln in b.get("lines", []):
                lines.append(" ".join(w["text"] for w in ln["words"]))
        return "\n".join(lines).strip()
    except Exception as e:
        logger.error("OCR parsing error: %s\nRaw response: %s", e, res)
        return ""

# --- 4. Telegram Handlers ---
@dp.message_handler(commands=['start'])
async def cmd_start(msg: types.Message):
    await msg.reply(
        "Привет! Отправь мне фото — я вытяну задание и километраж через Яндекс Vision OCR."
    )

@dp.message_handler(content_types=['photo'])
async def handle_photo(msg: types.Message):
    f_info = await bot.get_file(msg.photo[-1].file_id)
    bio = io.BytesIO()
    await bot.download_file(f_info.file_path, destination=bio)
    bio.seek(0)
    text = yandex_ocr(bio.read())
    if not text:
        return await msg.reply("Не удалось распознать текст.")
    job = re.search(r'[Зз]адани[ея][: ]+([^\n,;]+)', text)
    km  = re.search(r'(\d+)\s*км', text)
    job = job.group(1).strip() if job else 'не найдено'
    km  = km.group(1)         if km  else 'не найдено'
    await msg.reply(
        f"📋 *Распознано:*\n"
        f"– Задание: `{job}`\n"
        f"– Километраж: `{km} км`\n\n"
        f"🗒 Текст:\n```\n{text}\n```",
        parse_mode='Markdown'
    )

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

