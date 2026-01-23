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
WEBHOOK_PATH = "/webhook"

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
            [KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="✅ Підтвердити подію"), KeyboardButton(text="💳 Оплатити ігри")],
            [KeyboardButton(text="🏁 Завершити вечір"), KeyboardButton(text="❌ Скасувати івент")],
        ],
        resize_keyboard=True
    )

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
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

# ================= CREATE EVENT ===================
@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            await message.answer("❌ Створення івентів доступне лише адміну")
            return
    finally:
        await conn.close()

    await state.clear()
    await message.answer("📝 Введіть назву івенту:")
    await state.set_state(CreateEventStates.title)
    
@dp.message(CreateEventStates.title)
async def create_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📅 Введіть дату івенту (наприклад: 20.01):")
    await state.set_state(CreateEventStates.date)

@dp.message(CreateEventStates.date)
async def create_event_date(message: types.Message, state: FSMContext):
    await state.update_data(event_date=message.text.strip())
    await message.answer("⏰ Введіть час івенту (наприклад: 19:00):")
    await state.set_state(CreateEventStates.time)

@dp.message(CreateEventStates.time)
async def create_event_time(message: types.Message, state: FSMContext):
    await state.update_data(event_time=message.text.strip())
    await message.answer("📍 Вкажіть місце проведення:")
    await state.set_state(CreateEventStates.location)

@dp.message(CreateEventStates.location)
async def create_event_location(message: types.Message, state: FSMContext):
    data = await state.get_data()

    title = data["title"]
    event_date = data["event_date"]
    event_time = data["event_time"]
    location = message.text.strip()
    admin_id = message.from_user.id

    conn = await get_connection()
    try:
        event_id = await conn.fetchval(
            """
            INSERT INTO events (title, event_date, event_time, location, status, created_by)
            VALUES ($1, $2, $3, $4, 'active', $5)
            RETURNING event_id
            """,
            title, event_date, event_time, location, admin_id
        )

        players = await conn.fetch(
            "SELECT user_id FROM users WHERE is_active = 1"
        )

        sent_count = 0

        for p in players:
            try:
                await message.bot.send_message(
                    p["user_id"],
                    (
                        f"🎭 *{title}*\n"
                        f"📅 {event_date}\n"
                        f"⏰ {event_time}\n"
                        f"📍 *{location}*"
                    ),
                    parse_mode="Markdown",
                    reply_markup=invite_keyboard(event_id)
                )
                sent_count += 1   # ✅ Правильний відступ
            except Exception:
                continue

        await message.answer(
            f"✅ Івент створено та розіслано гравцям (**{sent_count}**)",
            parse_mode="Markdown"
        )
        
    finally:
        # Важливо закривати з'єднання, якщо ти не використовуєш context manager
        await conn.close()

    await state.clear()

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

# ================== CANCEL EVENT ==================

@dp.message(F.text == "❌ Скасувати івент")
async def request_cancel_event(message: types.Message):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            await message.answer("❌ Команда доступна лише адміну")
            return

        event = await conn.fetchrow(
            """
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів для скасування")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔥 ПІДТВЕРДИТИ СКАСУВАННЯ",
                        callback_data=f"confirm_cancel_{event['event_id']}"
                    )
                ]
            ]
        )

        await message.answer(
            f"❗ Ви впевнені, що хочете скасувати івент?\n\n"
            f"🎭 *{event['title']}*\n"
            f"📅 {event['event_date']}",
            parse_mode="Markdown",
            reply_markup=kb
        )

    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("confirm_cancel_"))
async def confirm_cancel_event(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])

    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            callback.from_user.id
        )
        if role != "admin":
            await callback.answer("❌ Немає прав", show_alert=True)
            return

        players = await conn.fetch(
            """
            SELECT user_id
            FROM registrations
            WHERE event_id = $1 AND status = 'active'
            """,
            event_id
        )

        await conn.execute(
            "UPDATE events SET status = 'closed' WHERE event_id = $1",
            event_id
        )

        for p in players:
            try:
                await callback.bot.send_message(
                    p["user_id"],
                    "😔 На жаль, ігрову подію скасовано. Слідкуйте за новими анонсами."
                )
            except Exception:
                continue

        await callback.message.edit_text(
            f"✅ Івент скасовано.\n"
            f"👥 Гравців сповіщено: **{len(players)}**",
            parse_mode="Markdown"
        )
        await callback.answer("Івент скасовано")

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

# ================= CLOSE EVENT ======================
@dp.message(F.text == "🏁 Завершити вечір")
async def finish_evening_start(message: types.Message):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            await message.answer("❌ Доступно лише адміну")
            return

        events = await conn.fetch(
            """
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        )

        if not events:
            await message.answer("ℹ️ Немає активних івентів")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"🏁 {e['title']} ({e['event_date']})",
                        callback_data=f"finish_event_{e['event_id']}"
                    )
                ]
                for e in events
            ]
        )

        await message.answer("Оберіть івент для завершення:", reply_markup=kb)

    finally:
        await conn.close()
        
@dp.callback_query(F.data.startswith("finish_event_"))
async def finish_event(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[-1])

    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            "SELECT title FROM events WHERE event_id = $1 AND status = 'active'",
            event_id
        )
        if not event:
            await callback.answer("Івент вже завершено", show_alert=True)
            return

        players = await conn.fetch(
            "SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'",
            event_id
        )

        await conn.execute(
            "UPDATE events SET status = 'closed' WHERE event_id = $1",
            event_id
        )

        for p in players:
            try:
                await callback.bot.send_message(
                    p["user_id"],
                    "🏁 Ігровий вечір завершено. Дякуємо за участь ❤️"
                )
            except Exception:
                continue

        await callback.message.edit_text(
            f"🏁 Івент **{event['title']}** завершено.\n"
            f"👥 Сповіщено гравців: **{len(players)}**",
            parse_mode="Markdown"
        )
        await callback.answer("Івент завершено")

    finally:
        await conn.close()
# ===================== COMMIT EVENT ======================================
@dp.message(F.text == "✅ Підтвердити подію")
async def confirm_event_start(message: types.Message):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            return

        event = await conn.fetchrow(
            """
            SELECT event_id, title, event_date
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів для підтвердження.")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚀 ВІДПРАВИТИ ПІДТВЕРДЖЕННЯ",
                        callback_data=f"send_confirm_{event['event_id']}"
                    )
                ]
            ]
        )

        await message.answer(
            f"❓ Надіслати підтвердження гравцям?\n\n"
            f"🎭 *{event['title']}*\n📅 {event['event_date']}",
            parse_mode="Markdown",
            reply_markup=kb
        )

    finally:
        await conn.close()
@dp.callback_query(F.data.startswith("send_confirm_"))
async def send_event_confirmation(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[-1])

    conn = await get_connection()
    try:
        players = await conn.fetch(
            """
            SELECT user_id
            FROM registrations
            WHERE event_id = $1 AND status = 'active'
            """,
            event_id
        )

        if not players:
            await callback.answer("Ніхто не записаний", show_alert=True)
            return

        sent = 0
        for p in players:
            try:
                await callback.bot.send_message(
                    p["user_id"],
                    "✅ Ігрова подія підтверджена! Чекаємо на тебе 🫶"
                )
                sent += 1
            except Exception:
                continue

        await callback.message.edit_text(
            f"✅ Підтвердження надіслано\n👥 Гравців: **{sent}**",
            parse_mode="Markdown"
        )
        await callback.answer("Готово")

    finally:
        await conn.close()

# ================== PLAYER LIST\CANCEL =====================
@dp.message(F.text == "🛠 Адмін: список + скасовані")
async def admin_players_with_cancelled(message: types.Message):
    conn = await get_connection()
    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1",
            message.from_user.id
        )
        if role != "admin":
            await message.answer("❌ Доступ лише для адміністратора")
            return

        events = await conn.fetch(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        )

        if not events:
            await message.answer("ℹ️ Немає активних івентів")
            return

        for event in events:
            rows = await conn.fetch(
                """
                SELECT u.display_name, r.status, r.comment
                FROM registrations r
                JOIN users u ON u.user_id = r.user_id
                WHERE r.event_id = $1
                ORDER BY r.created_at
                """,
                event["event_id"]
            )

            active = []
            cancelled = []

            for r in rows:
                name = r["display_name"]
                if r["comment"]:
                    name += f" ({r['comment']})"

                if r["status"] == "active":
                    active.append(name)
                elif r["status"] == "cancelled":
                    cancelled.append(r["display_name"])

            text = f"🛠 *{event['title']}*\n\n"

            text += "✅ **Активні:**\n"
            text += "\n".join(f"{i+1}. {p}" for i, p in enumerate(active)) or "—"
            text += "\n\n❌ **Скасували:**\n"
            text += "\n".join(f"{i+1}. {p}" for i, p in enumerate(cancelled)) or "—"

            await message.answer(text, parse_mode="Markdown")

    finally:
        await conn.close()

# ================== WEBHOOK ==================

async def start_all():
    await init_db()

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")

    app = web.Application()

    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot
    ).register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
    )
    await site.start()

    print("🚀 Webhook bot started")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(start_all())














