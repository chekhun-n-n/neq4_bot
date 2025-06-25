import os
import io
import time
import json
import logging
import base64
import re

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import requests
import jwt   # PyJWT[crypto]
from dotenv import load_dotenv

# --- 1. Загрузка ENV и логгирование ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')

# Сервисный ключ можно хранить прямо в ENV
YANDEX_KEY_JSON = os.getenv('YANDEX_KEY_JSON')
if YANDEX_KEY_JSON:
    key = json.loads(YANDEX_KEY_JSON)
else:
    YANDEX_KEY_FILE = os.getenv('YANDEX_KEY_FILE', 'yandex_key.json')
    assert os.path.exists(YANDEX_KEY_FILE), "YANDEX_KEY_FILE not found!"
    with open(YANDEX_KEY_FILE, 'r') as f:
        key = json.load(f)

assert TELEGRAM_TOKEN,   "TELEGRAM_TOKEN is not set!"
assert YANDEX_FOLDER_ID, "YANDEX_FOLDER_ID is not set!"

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot)

# --- 2. Кэширование IAM-токена ---
_IAM_TOKEN = None
_IAM_EXPIRES = 0

def get_iam_token() -> str:
    global _IAM_TOKEN, _IAM_EXPIRES
    if _IAM_TOKEN and _IAM_EXPIRES > time.time() + 300:
        return _IAM_TOKEN

    now = int(time.time())
    payload = {
        "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        "iss": key["service_account_id"],
        "iat": now,
        "exp": now + 360,
    }
    signed_jwt = jwt.encode(
        payload,
        key["private_key"],
        algorithm="PS256",
        headers={"kid": key["id"]},
    )

    resp = requests.post(
        "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        json={"jwt": signed_jwt},
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

    resp = requests.post(
        "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=20
    )
    resp.raise_for_status()
    res = resp.json()

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

# --- 4. Телеграм-хендлеры ---
@dp.message_handler(commands=['start'])
async def cmd_start(msg: types.Message):
    await msg.reply(
        "Привет! Отправь фото — я распознаю *Task ID*, *Задание* и *Километраж* через Яндекс Vision OCR.",
        parse_mode='Markdown'
    )

@dp.message_handler(content_types=['photo'])
async def handle_photo(msg: types.Message):
    # Скачиваем изображение
    f_info = await bot.get_file(msg.photo[-1].file_id)
    bio = io.BytesIO()
    await bot.download_file(f_info.file_path, destination=bio)
    img_bytes = bio.getvalue()

    # OCR
    text = yandex_ocr(img_bytes)
    if not text:
        return await msg.reply("❌ Не удалось распознать текст.")

    # 1) Task ID: цифры внутри [..]
    tid_m = re.search(r'\[([^\]]+)\]', text)
    task_id = tid_m.group(1) if tid_m else '—'

    # 2) Raw slug (первую строку) — то, что нужно вставить в задание
    first_line = text.splitlines()[0].strip()

    # 3) Название после «Задание:»
    jt_m = re.search(r'[Зз]адани[ея][: ]+([^\n,;]+)', text)
    job_part = jt_m.group(1).strip() if jt_m else ''

    # Собираем полное задание: первая строка + доп. название
    if job_part:
        job_full = f"{first_line} — {job_part}"
    else:
        job_full = first_line

    # 4) Километраж: сначала в скобках "(NN км)", иначе просто "NN км"
    km_m = re.search(r'\(\s*(\d+(?:[.,]\d+)?)\s*км\s*\)', text)
    if not km_m:
        km_m = re.search(r'(\d+(?:[.,]\d+)?)\s*км', text)
    km = km_m.group(1).replace(',', '.') if km_m else 'не найдено'

    # Ответ пользователю
    await msg.reply(
        f"📋 *Распознано:*\n"
        f"– Task ID: `{task_id}`\n"
        f"– Задание: `{job_full}`\n"
        f"– Километраж: `{km} км`\n\n"
        f"🗒 *Текст:*\n```{text}```",
        parse_mode='Markdown'
    )

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
