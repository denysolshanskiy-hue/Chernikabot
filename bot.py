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
PORT = int(os.getenv("PORT", 10000))

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
    nickname = State()

class CommentState(StatesGroup):
    comment = State()

# ================== CALLBACK DATA ==================

class InviteCallback(CallbackData, prefix="invite"):
    action: str   # join | ignore | cancel | players
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
                    text="👥 Гравці",
                    callback_data=InviteCallback(action="players", event_id=event_id).pack()
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

# ================== START ==================

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
            await message.answer("👋 Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(NicknameState.nickname)
            return

        if not user["display_name"]:
            await message.answer("Введіть ваш **нік**:", parse_mode="Markdown")
            await state.set_state(NicknameState.nickname)
            return

        keyboard = admin_menu_keyboard() if user["role"] == "admin" else player_menu_keyboard()
        await message.answer(
            f"З поверненням, **{user['display_name']}** 👋",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    finally:
        await conn.close()

@dp.message(NicknameState.nickname)
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

# ================== ACTIVE EVENTS ==================

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
            await message.answer("ℹ️ Немає активних івентів")
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

# ================== JOIN EVENT ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def join_event(callback: types.CallbackQuery, callback_data: InviteCallback, state: FSMContext):
    conn = await get_connection()
    try:
        exists = await conn.fetchval(
            """
            SELECT 1 FROM registrations
            WHERE event_id = $1 AND user_id = $2 AND status = 'active'
            """,
            callback_data.event_id,
            callback.from_user.id
        )

        if exists:
            await callback.answer("Ви вже записані", show_alert=True)
            return

        await conn.execute(
            """
            INSERT INTO registrations (event_id, user_id, status)
            VALUES ($1, $2, 'active')
            """,
            callback_data.event_id,
            callback.from_user.id
        )

        await callback.answer("✅ Ви записались!")
        await state.set_state(CommentState.comment)
        await state.update_data(event_id=callback_data.event_id)
        await callback.message.answer(
            "💬 Напишіть коментар (+1, не весь вечір) або `-` щоб пропустити"
        )
    finally:
        await conn.close()

@dp.message(CommentState.comment)
async def save_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    event_id = data["event_id"]
    comment = None if message.text.strip() == "-" else message.text.strip()

    conn = await get_connection()
    try:
        await conn.execute(
            """
            UPDATE registrations
            SET comment = $1
            WHERE event_id = $2 AND user_id = $3 AND status = 'active'
            """,
            comment,
            event_id,
            message.from_user.id
        )
        await state.clear()
        await message.answer("✅ Коментар збережено", reply_markup=cancel_keyboard(event_id))
    finally:
        await conn.close()

# ================== PLAYERS LIST ==================

@dp.callback_query(InviteCallback.filter(F.action == "players"))
async def show_players(callback: types.CallbackQuery, callback_data: InviteCallback):
    conn = await get_connection()
    try:
        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1 AND r.status = 'active'
            ORDER BY r.created_at
            """,
            callback_data.event_id
        )

        if not players:
            await callback.answer("Поки нікого немає", show_alert=True)
            return

        text = "👥 **Гравці:**\n\n"
        for i, p in enumerate(players, 1):
            suffix = f" ({p['comment']})" if p["comment"] else ""
            text += f"{i}. {p['display_name']}{suffix}\n"

        await callback.message.answer(text, parse_mode="Markdown")
        await callback.answer()
    finally:
        await conn.close()

# ================== PAYMENTS ==================

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
            "Після оплати натисніть кнопку 👇"
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
