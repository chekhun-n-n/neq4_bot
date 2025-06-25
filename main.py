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
import jwt  # pip install pyjwt[crypto]
from dotenv import load_dotenv

# ————————————————————————————
# 1. ИНИЦИАЛИЗАЦИЯ
# ————————————————————————————
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.getenv('TELEGRAM_TOKEN')
YANDEX_FOLDER_ID  = os.getenv('YANDEX_FOLDER_ID')
YANDEX_KEY_JSON   = os.getenv('YANDEX_KEY_JSON')  # теперь весь JSON-контент

assert TELEGRAM_TOKEN,   "🔴 TELEGRAM_TOKEN не задан!"
assert YANDEX_FOLDER_ID, "🔴 YANDEX_FOLDER_ID не задан!"
assert YANDEX_KEY_JSON,  "🔴 YANDEX_KEY_JSON не задан!"

# парсим JSON сервисного аккаунта
try:
    yandex_key = json.loads(YANDEX_KEY_JSON)
except json.JSONDecodeError:
    raise SystemExit("🔴 Не удалось распарсить YANDEX_KEY_JSON как JSON")

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot)


# ————————————————————————————
# 2. ПОЛУЧЕНИЕ IAM-Токена
# ————————————————————————————
_IAM_TOKEN   = None
_IAM_EXPIRES = 0

def get_iam_token():
    global _IAM_TOKEN, _IAM_EXPIRES
    # возвращаем кешированный, если ещё не истечёт через 5 минут
    if _IAM_TOKEN and _IAM_EXPIRES > time.time() + 300:
        return _IAM_TOKEN

    now = int(time.time())
    payload = {
        "aud": "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        "iss": yandex_key["service_account_id"],
        "iat": now,
        "exp": now + 360,
    }
    encoded_jwt = jwt.encode(
        payload,
        yandex_key["private_key"],
        algorithm="PS256",
        headers={"kid": yandex_key["id"]}
    )

    resp = requests.post(
        "https://iam.api.cloud.yandex.net/iam/v1/tokens",
        json={"jwt": encoded_jwt},
        timeout=10
    )
    if resp.status_code != 200:
        logger.error("IAM error %s: %s", resp.status_code, resp.text)
        raise RuntimeError("Не удалось получить Yandex IAM токен")

    data = resp.json()
    _IAM_TOKEN   = data["iamToken"]
    _IAM_EXPIRES = time.time() + 3600 * 11
    return _IAM_TOKEN


# ————————————————————————————
# 3. OCR через Yandex Vision
# ————————————————————————————
def yandex_ocr(img_bytes: bytes) -> str:
    token = get_iam_token()
    url = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    body = {
        "folderId": YANDEX_FOLDER_ID,
        "analyze_specs": [{
            "content": img_b64,
            "features": [{"type": "TEXT_DETECTION",
                          "text_detection_config": {"language_codes": ["ru"]}}]
        }]
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    try:
        pages = resp.json()["results"][0]["results"][0]["textDetection"]["pages"]
        lines = []
        for block in pages[0]["blocks"]:
            for line in block.get("lines", []):
                lines.append(" ".join(w["text"] for w in line["words"]))
        return "\n".join(lines).strip()
    except Exception as e:
        logger.error("OCR error: %s — %s", e, resp.text)
        return ""


# ————————————————————————————
# 4. Хендлеры Telegram
# ————————————————————————————
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    await msg.reply(
        "Привет! Пришли мне фото — я распознаю текст, задание и километраж "
        "с помощью Yandex Vision."
    )

@dp.message_handler(content_types=["photo"])
async def handle_photo(msg: types.Message):
    file = await bot.get_file(msg.photo[-1].file_id)
    bio  = io.BytesIO()
    await bot.download_file(file.file_path, destination=bio)
    text = yandex_ocr(bio.getvalue())
    if not text:
        return await msg.reply("Не удалось распознать текст — попробуй ещё раз.")

    job = re.search(r"[Зз]адани[ея][: ]+([^\n,;]+)", text)
    km  = re.search(r"(\d+)[\s-]*км", text)
    job = job.group(1).strip() if job else "не найдено"
    km  = km.group(1) if km else "не найдено"

    await msg.reply(
        f"📋 *Распознано:*\n– Задание: `{job}`\n– Километраж: `{km} км`\n\n"
        f"🗒 Распознанный текст:\n{text}",
        parse_mode="Markdown"
    )


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)

