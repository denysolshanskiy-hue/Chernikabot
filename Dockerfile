FROM python:3.11-slim

# Встановлюємо робочу директорію
WORKDIR /app

# Копіюємо всі файли проекту
COPY . .

# Оновлюємо сертифікати та встановлюємо залежності
RUN apt-get update && apt-get install -y ca-certificates && update-ca-certificates
RUN pip install --no-cache-dir -r requirements.txt

# Запуск бота
CMD ["python", "bot.py"]