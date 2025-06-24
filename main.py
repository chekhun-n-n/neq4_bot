import os
import logging
import io
import re
import json

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

from oauth2client.service_account import ServiceAccountCredentials
import gspread
from PIL import Image
import pytesseract

# ----------------------
# 1. Настройка логирования
# ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------
# 2. Чтение переменных окружения
# ----------------------
# Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    logger.error("ERROR: TELEGRAM_TOKEN не задана")
    exit(1)

# Google Sheets ID
GOOGLE_SHEET_ID = os.getenv('GOOGLE_SHEET_ID')
if not GOOGLE_SHEET_ID:
    logger.error("ERROR: GOOGLE_SHEET_ID не задана")
    exit(1)

# JSON ключ (либо из переменной, либо файл)
env_json = os.getenv('GOOGLE_SERVICE_JSON')
if env_json:
    # Восстановить файл ключа из переменной окружения
    with open('service_account.json', 'w', encoding='utf-8') as f:
        f.write(env_json)
    GOOGLE_JSON_PATH = 'service_account.json'
else:
    # fallback на файл в репозитории
    GOOGLE_JSON_PATH = os.getenv(
        'GOOGLE_JSON_PATH',
        'sheets-bot-463919-5cf9c9fa0648.json'
    )

# ----------------------
# 3. Инициализация бота и диспетчера
# ----------------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# ----------------------
# 4. Подключение к Google Sheets
# ----------------------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    GOOGLE_JSON_PATH, scope
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1

# ----------------------
# 5. Обработчики команд и сообщений
# ----------------------
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    text = (
        "Привет! Я – ваш ассистент-бот.\n\n"
        "• Перешлите мне фото/скриншот – я распознаю номер задания и километраж.\n"
        "• Используйте /template <ключ> – я подберу нужный шаблон из Google Sheets.\n"
    )
    await message.reply(text)

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    # 1) Скачиваем фото
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    bio = io.BytesIO()
    await bot.download_file(file.file_path, destination=bio)
    bio.seek(0)

    # 2) OCR распознавание
    try:
        img = Image.open(bio)
        text = pytesseract.image_to_string(img, lang='rus').strip()
    except Exception as e:
        await message.reply(f"Ошибка распознавания: {e}")
        return

    # 3) Парсинг номера задания и километража
    num = re.search(r'[Зз]адани[ея][: ]+(\w+)', text)
    km  = re.search(r'(\d+)[\s-]*км', text)
    job = num.group(1) if num else 'не найден'
    kmv = km.group(1)  if km  else 'не найден'

    # 4) Ответ пользователю
    resp = (
        f"📋 *Распознано:*\n"
        f"– Задание: `{job}`\n"
        f"– Километраж: `{kmv} км`\n\n"
        f"🗒 Распознанный текст:\n{text}"
    )
    await message.reply(resp, parse_mode='Markdown')

@dp.message_handler(commands=['template'])
async def handle_template(message: types.Message):
    key = message.get_args().lower().strip()
    if not key:
        return await message.reply("Укажите ключ: `/template оплата`", parse_mode='Markdown')

    rows = sheet.get_all_records()
    matches = [r for r in rows if key in r.get('Ключевые слова', '').lower()]
    if not matches:
        return await message.reply("Шаблон не найден.")

    for row in matches:
        cat = row.get('Категория', '')
        txt = row.get('Шаблон (текст сообщения)', '').strip()
        link= row.get('Ссылка на видео/файл', '').strip()
        out = f"📄 *{cat}*\n{txt}"
        if link:
            out += f"\n🔗 {link}"
        await message.reply(out, parse_mode='Markdown')

# ----------------------
# 6. Запуск бота
# ----------------------
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)

