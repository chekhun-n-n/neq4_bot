import os
import logging
import io
import re
import json

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.utils.markdown import escape_md

from google.oauth2.service_account import Credentials
import gspread
from PIL import Image
import pytesseract

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = os.getenv('TELEGRAM_TOKEN')
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
if not TELEGRAM_TOKEN or not GOOGLE_SHEET_ID:
    logger.error("🔴 TELEGRAM_TOKEN и GOOGLE_SHEET_ID должны быть заданы!")
    exit(1)

svc_json = os.getenv('GOOGLE_SERVICE_JSON')
if not svc_json:
    logger.error("🔴 Переменная GOOGLE_SERVICE_JSON не найдена!")
    exit(1)

info = json.loads(svc_json)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(info, scopes=scopes)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def cmd_start(msg: types.Message):
    await msg.reply(
        "Привет! Я — ассистент-бот.\n\n"
        "• Перешлите фото, я распознаю задание и км.\n"
        "• /template <ключ> — найду шаблон в Google Sheets."
    )

@dp.message_handler(content_types=['photo'])
async def on_photo(msg: types.Message):
    f    = await bot.get_file(msg.photo[-1].file_id)
    bio  = io.BytesIO()
    await bot.download_file(f.file_path, destination=bio)
    bio.seek(0)

    try:
        img  = Image.open(bio)
        text = pytesseract.image_to_string(img, lang='rus').strip()
    except Exception as e:
        return await msg.reply(f"Ошибка OCR: {e}")

    job = re.search(r'[Зз]адани[ея][: ]+(\w+)', text)
    km  = re.search(r'(\d+)[\s-]*км',        text)
    job = job.group(1) if job else 'не найден'
    km  = km.group(1)  if km  else 'не найден'

    # Экранируем для Markdown
    job_esc = escape_md(job)
    km_esc  = escape_md(km)
    text_esc = escape_md(text)

    await msg.reply(
        f"📋 *Распознано:*\n"
        f"– Задание: `{job_esc}`\n"
        f"– Километраж: `{km_esc} км`\n\n"
        f"🗒 Распознанный текст:\n{text_esc}",
        parse_mode='Markdown'
    )

@dp.message_handler(commands=['template'])
async def on_template(msg: types.Message):
    key = msg.get_args().lower().strip()
    if not key:
        return await msg.reply("Укажите ключ: `/template оплата`", parse_mode='Markdown')

    recs = sheet.get_all_records()
    hits = [r for r in recs if key in r.get('Ключевые слова','').lower()]
    if not hits:
        return await msg.reply("Шаблон не найден.")

    for r in hits:
        out = f"📄 *{escape_md(r.get('Категория',''))}*\n{escape_md(r.get('Шаблон (текст сообщения)',''))}"
        link = r.get('Ссылка на видео/файл','').strip()
        if link:
            out += f"\n🔗 {escape_md(link)}"
        await msg.reply(out, parse_mode='Markdown')

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)


