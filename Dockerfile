# Базовый образ с Python и минимальными утилитами
FROM python:3.10-slim

# Устанавливаем Tesseract OCR и русскую локаль
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-rus && \
    rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Копируем весь проект
COPY . /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Точка входа
CMD ["python", "main.py"]

