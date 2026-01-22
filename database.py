import asyncio
import os
import asyncpg
from datetime import datetime

# Отримуємо URL з Environment Variables на Koyeb
DATABASE_URL = os.environ.get("DATABASE_URL")

async def get_connection():
    """Створює підключення до бази даних Neon (PostgreSQL)"""
    return await asyncpg.connect(DATABASE_URL)

async def cancel_event_in_db(event_id):
    conn = await get_connection()
    try:
        # Оновлюємо статус івенту
        await conn.execute("UPDATE events SET status = 'closed' WHERE event_id = $1", event_id)
        
        # Отримуємо список гравців, які були записані, щоб знати кому писати
        rows = await conn.fetch("SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'", event_id)
        return [r['user_id'] for r in rows]
    finally:
        await conn.close()

async def get_total_players_count():
    conn = await get_connection()
    try:
        # Рахуємо всіх зареєстрованих користувачів
        count = await conn.fetchval("SELECT COUNT(*) FROM users")
        return count if count else 0
    finally:
        await conn.close()

async def init_db():
    """Створює таблиці, якщо вони не існують"""
    conn = await get_connection()
    
    # Таблиця користувачів
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        display_name TEXT,
        role TEXT NOT NULL CHECK(role IN ('admin','player')),
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Таблиця подій (ігор)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        event_date TEXT NOT NULL,
        event_time TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active','closed')),
        created_by BIGINT NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Таблиця реєстрацій
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS registrations (
        registration_id SERIAL PRIMARY KEY,
        event_id INTEGER NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(user_id),
        comment TEXT,
        status TEXT NOT NULL CHECK(status IN ('active','cancelled')),
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    await conn.close()
    print("Database initialized successfully!")

# Якщо потрібно запустити створення таблиць вручну
if __name__ == "__main__":
    asyncio.run(init_db())



