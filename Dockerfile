FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-rus && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# Устанавливаем зависимости сразу из requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
