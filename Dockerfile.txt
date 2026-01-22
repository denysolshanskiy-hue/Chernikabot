FROM python:3.11-slim

WORKDIR /app

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей з папки mafia_bot
COPY mafia_bot/requirements.txt .

# Встановлюємо залежності (тепер asyncpg точно встановиться)
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо все інше
COPY . .

# Запуск
CMD ["python", "mafia_bot/bot.py"]
