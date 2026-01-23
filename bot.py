import asyncio
import os
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters.callback_data import CallbackData
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from database import get_connection, init_db

# ================== INIT ==================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", 10000))

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ================== STATES ==================

class CreateEvent(StatesGroup):
    title = State()
    date = State()
    time = State()
    location = State()

class Nickname(StatesGroup):
    value = State()

# ================== CALLBACK ==================

class EventCallback(CallbackData, prefix="event"):
    action: str   # join | players
    event_id: int

# ================== KEYBOARDS ==================

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент"), KeyboardButton(text="📅 Активні події")],
        ],
        resize_keyboard=True
    )

def player_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
        ],
        resize_keyboard=True
    )

def event_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Записатись",
                    callback_data=EventCallback(action="join", event_id=event_id).pack()
                ),
                InlineKeyboardButton(
                    text="👥 Гравці",
                    callback_data=EventCallback(action="players", event_id=event_id).pack()
                )
            ]
        ]
    )

# ================== START ==================

@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT display_name, role FROM users WHERE user_id=$1",
            message.from_user.id
        )

        if not user:
            await conn.execute(
                "INSERT INTO users (user_id, username, role) VALUES ($1,$2,'player')",
                message.from_user.id,
                message.from_user.username
            )
            await message.answer("👋 Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(Nickname.value)
            return

        if not user["display_name"]:
            await message.answer("Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(Nickname.value)
            return

        menu = admin_menu() if user["role"] == "admin" else player_menu()
        await message.answer(f"З поверненням, **{user['display_name']}** 👋", reply_markup=menu, parse_mode="Markdown")

    finally:
        await conn.close()

@dp.message(Nickname.value)
async def save_nick(message: types.Message, state: FSMContext):
    await get_connection().execute(
        "UPDATE users SET display_name=$1 WHERE user_id=$2",
        message.text.strip(),
        message.from_user.id
    )
    await state.clear()
    await message.answer("✅ Готово!", reply_markup=player_menu())

# ================== ACTIVE EVENTS ==================

@dp.message(F.text == "📅 Активні події")
async def active_events(message: types.Message):
    conn = await get_connection()
    try:
        events = await conn.fetch(
            "SELECT event_id,title,event_date,event_time,location FROM events WHERE status='active'"
        )

        if not events:
            await message.answer("ℹ️ Немає активних івентів")
            return

        for e in events:
            await message.answer(
                f"🎭 *{e['title']}*\n📅 {e['event_date']}\n⏰ {e['event_time']}\n📍 *{e['location']}*",
                parse_mode="Markdown",
                reply_markup=event_keyboard(e["event_id"])
            )
    finally:
        await conn.close()

# ================== JOIN EVENT ==================

@dp.callback_query(EventCallback.filter(F.action == "join"))
async def join_event(cb: types.CallbackQuery, callback_data: EventCallback):
    conn = await get_connection()
    try:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM registrations
            WHERE event_id=$1 AND user_id=$2 AND status='active'
            """,
            callback_data.event_id,
            cb.from_user.id
        )

        if exists:
            await cb.answer("Ви вже записані", show_alert=True)
            return

        await conn.execute(
            "INSERT INTO registrations (event_id,user_id,status) VALUES ($1,$2,'active')",
            callback_data.event_id,
            cb.from_user.id
        )

        await cb.answer("✅ Ви записались!")
    finally:
        await conn.close()

# ================== PLAYERS LIST ==================

@dp.callback_query(EventCallback.filter(F.action == "players"))
async def show_players(cb: types.CallbackQuery, callback_data: EventCallback):
    conn = await get_connection()
    try:
        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
            ORDER BY r.created_at
            """,
            callback_data.event_id
        )

        if not players:
            await cb.answer("Поки нікого немає", show_alert=True)
            return

        text = "👥 **Гравці:**\n\n"
        for i, p in enumerate(players, 1):
            comment = f" ({p['comment']})" if p["comment"] else ""
            text += f"{i}. {p['display_name']}{comment}\n"

        await cb.message.answer(text, parse_mode="Markdown")
        await cb.answer()

    finally:
        await conn.close()
#========================= ОПЛАТИ =====================================
@dp.message(F.text == "💳 Оплатити ігри")
async def pay_games(message: types.Message):
    await message.answer(
        (
            "💳 **Оплата ігрових вечорів**\n\n"
            "**М А Ф І Я**\n\n"
            "🎭 Ігровий вечір — **350 грн**\n"
            "🎲 Одна гра — **150 грн**\n\n"
            "🔗 **Посилання на банку:**\n"
            "https://send.monobank.ua/jar/7eyHDYKjeX\n\n"
            "💳 **Номер картки банки:**\n"
            "`4874 1000 2416 5600`\n\n"
            "Після оплати натисніть кнопку нижче 👇"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 Я оплатив", callback_data="payment_done")]
            ]
        )
    )
    
@dp.callback_query(F.data == "payment_done")
async def payment_done(callback: types.CallbackQuery):
    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT display_name FROM users WHERE user_id = $1",
            callback.from_user.id
        )
        name = user["display_name"] if user else callback.from_user.full_name

        admins = await conn.fetch(
            "SELECT user_id FROM users WHERE role = 'admin' AND is_active = 1"
        )
    finally:
        await conn.close()

    await callback.answer("Дякуємо за оплату 💚")
    await callback.message.edit_reply_markup(None)
    await callback.message.reply("✅ Оплату зафіксовано. Дякуємо 🙏")

    for admin in admins:
        if admin["user_id"] != callback.from_user.id:
            await callback.bot.send_message(
                admin["user_id"],
                f"💳 **Оплата**\n👤 {name}\n🆔 `{callback.from_user.id}`",
                parse_mode="Markdown"
            )


# ================== WEBHOOK ==================

async def main():
    await init_db()

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

    app = web.Application()
    SimpleRequestHandler(dp, bot).register(app, "/webhook")
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    print("🚀 Bot started")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())


