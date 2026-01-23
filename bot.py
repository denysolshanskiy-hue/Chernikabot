import asyncio
import os
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.callback_data import CallbackData
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database import get_connection, init_db

# ================== INIT ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 10000))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL is not set")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================== STATES ==================

class CreateEventStates(StatesGroup):
    title = State()
    date = State()
    time = State()
    location = State()

class NicknameState(StatesGroup):
    waiting_for_nickname = State()

class CommentState(StatesGroup):
    waiting_for_comment = State()

# ================== CALLBACK DATA ==================

class InviteCallback(CallbackData, prefix="invite"):
    action: str
    event_id: int

# ================== KEYBOARDS ==================

def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент"), KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців"), KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="✅ Підтвердити подію"), KeyboardButton(text="💳 Оплатити ігри")],
            [KeyboardButton(text="🏁 Завершити вечір"), KeyboardButton(text="❌ Скасувати івент")],
        ],
        resize_keyboard=True
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
            [KeyboardButton(text="💳 Оплатити ігри")],
        ],
        resize_keyboard=True
    )

def invite_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Записатись",
                    callback_data=InviteCallback(action="join", event_id=event_id).pack()
                ),
                InlineKeyboardButton(
                    text="❌ Ігнорувати",
                    callback_data=InviteCallback(action="ignore", event_id=event_id).pack()
                ),
            ]
        ]
    )

def cancel_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=InviteCallback(action="cancel", event_id=event_id).pack()
                )
            ]
        ]
    )

# ================== START / NICKNAME ==================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT display_name, role FROM users WHERE user_id = $1",
            user_id
        )

        if not user:
            await conn.execute(
                "INSERT INTO users (user_id, username, role) VALUES ($1, $2, 'player')",
                user_id, username
            )
            await message.answer("👋 Вітаю! Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        if not user["display_name"]:
            await message.answer("Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        keyboard = admin_menu_keyboard() if user["role"] == "admin" else player_menu_keyboard()
        await message.answer(
            f"З поверненням, **{user['display_name']}** 👋",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    finally:
        await conn.close()

@dp.message(NicknameState.waiting_for_nickname)
async def save_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if not 2 <= len(nickname) <= 20:
        await message.answer("❌ Нік має бути від 2 до 20 символів.")
        return

    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET display_name = $1 WHERE user_id = $2",
            nickname, message.from_user.id
        )
        await state.clear()
        await message.answer(
            f"✅ Ваш нік: **{nickname}**",
            parse_mode="Markdown",
            reply_markup=player_menu_keyboard()
        )
    finally:
        await conn.close()

# ================== CREATE EVENT (ADMIN) ==================

@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            return
    finally:
        await conn.close()

    await message.answer("📝 Введіть назву івенту:")
    await state.set_state(CreateEventStates.title)

@dp.message(CreateEventStates.title)
async def event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Введіть дату:")
    await state.set_state(CreateEventStates.date)

@dp.message(CreateEventStates.date)
async def event_date(message: types.Message, state: FSMContext):
    await state.update_data(date=message.text)
    await message.answer("⏰ Введіть час:")
    await state.set_state(CreateEventStates.time)

@dp.message(CreateEventStates.time)
async def event_time(message: types.Message, state: FSMContext):
    await state.update_data(time=message.text)
    await message.answer("📍 Вкажіть місце проведення:")
    await state.set_state(CreateEventStates.location)

@dp.message(CreateEventStates.location)
async def event_location(message: types.Message, state: FSMContext):
    data = await state.get_data()

    conn = await get_connection()
    try:
        event_id = await conn.fetchval(
            """
            INSERT INTO events (title, event_date, event_time, location, status, created_by)
            VALUES ($1, $2, $3, $4, 'active', $5)
            RETURNING event_id
            """,
            data["title"], data["date"], data["time"], message.text, message.from_user.id
        )

        players = await conn.fetch("SELECT user_id FROM users WHERE is_active = 1")

        for p in players:
            try:
                await bot.send_message(
                    p["user_id"],
                    f"🎭 *{data['title']}*\n📅 {data['date']}\n⏰ {data['time']}\n📍 *{message.text}*",
                    parse_mode="Markdown",
                    reply_markup=invite_keyboard(event_id)
                )
            except Exception:
                continue

        await message.answer("✅ Івент створено та розіслано")
        await state.clear()
    finally:
        await conn.close()

# ================== PUBLIC PLAYER LIST ==================

@dp.message(F.text == "👥 Список гравців")
async def show_players_public(message: types.Message):
    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            """
            SELECT e.event_id, e.title
            FROM registrations r
            JOIN events e ON e.event_id = r.event_id
            WHERE r.user_id = $1
              AND r.status = 'active'
              AND e.status = 'active'
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            message.from_user.id
        )

        if not event:
            await message.answer("ℹ️ Ви не записані на жоден активний івент")
            return

        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1 AND r.status = 'active'
            ORDER BY r.created_at
            """,
            event["event_id"]
        )

        text = f"👥 *Гравці на івенті:* _{event['title']}_\n\n"
        for i, p in enumerate(players, 1):
            suffix = f" ({p['comment']})" if p["comment"] else ""
            text += f"{i}. {p['display_name']}{suffix}\n"

        await message.answer(text, parse_mode="Markdown")
    finally:
        await conn.close()
        
# ================== ACTIVE EVENTS (PUBLIC) ==================

@dp.message(F.text == "📅 Активні події")
async def show_active_events(message: types.Message):
    conn = await get_connection()
    try:
        events = await conn.fetch(
            """
            SELECT event_id, title, event_date, event_time, location
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        )

        if not events:
            await message.answer("ℹ️ Наразі немає активних івентів")
            return

        for ev in events:
            await message.answer(
                (
                    f"🎭 *{ev['title']}*\n"
                    f"📅 {ev['event_date']}\n"
                    f"⏰ {ev['event_time']}\n"
                    f"📍 *{ev['location']}*"
                ),
                parse_mode="Markdown",
                reply_markup=invite_keyboard(ev["event_id"])
            )

    finally:
        await conn.close()

# ================== WEBHOOK RUN ==================

async def start_all():
    await init_db()

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

    app = web.Application()

    SimpleRequestHandler(dp, bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("🚀 Webhook bot started")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_all())

