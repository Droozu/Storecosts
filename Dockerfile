# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Чтобы логи сразу выводились (без буферизации)
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала копируем зависимости (для кеша слоёв)
COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

# Потом код
COPY app ./app

# По умолчанию запускаем скрипт
CMD ["python", "-m", "app.main"]