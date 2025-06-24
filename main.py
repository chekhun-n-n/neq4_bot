import logging
from aiogram import Bot, Dispatcher, types, executor
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pytesseract
from PIL import Image
import io
import re
import os

logging.basicConfig(level=logging.INFO)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_SHEET_ID = os.environ.get('GOOGLE_SHEET_ID')
GOOGLE_JSON_PATH = 'sheets-bot-463919-5cf9c9fa0648.json'  # путь к вашему json-ключу

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_JSON_PATH, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1

@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    file_path = file.file_path
    file_bytes = await bot.download_file(file_path)
    image = Image.open(io.BytesIO(file_bytes.read()))
    text = pytesseract.image_to_string(image, lang='rus')
    # Парсим примерные поля
    match_num = re.search(r'[Зз]адани[ея][: ]+(\w+)', text)
    match_km = re.search(r'(\d+)[\s-]*км', text)
    job_num = match_num.group(1) if match_num else 'Не найдено'
    km = match_km.group(1) if match_km else 'Не найдено'
    await message.answer(f"Задание: {job_num}\nКилометраж: {km}\n\nРаспознанный текст:\n{text}")

@dp.message_handler(commands=['template'])
async def handle_template(message: types.Message):
    args = message.get_args()
    rows = sheet.get_all_records()
    found = [row for row in rows if args.lower() in row['Ключевые слова']]
    if found:
        for row in found:
            await message.answer(row['Шаблон (текст сообщения)'])
    else:
        await message.answer("Шаблон не найден.")

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я ассистент-бот. Пришлите фото/сообщение или используйте команду /template [ключевое слово].")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
