import asyncio
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

from config import BOT_TOKEN
from database import get_connection, init_db


# ================== INIT ==================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ================== STATES ==================

class CreateEventStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_date = State()
    waiting_for_time = State()


class NicknameState(StatesGroup):
    waiting_for_nickname = State()


class CommentState(StatesGroup):
    waiting_for_comment = State()


# ================== CALLBACK DATA ==================

class InviteCallback(CallbackData, prefix="invite"):
    action: str   # join | ignore | cancel
    event_id: int


# ================== KEYBOARDS ==================

def invite_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Записатись",
                    callback_data=InviteCallback(action="join", event_id=event_id).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Ігнорувати",
                    callback_data=InviteCallback(action="ignore", event_id=event_id).pack(),
                ),
            ]
        ]
    )


def cancel_keyboard(event_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Скасувати",
                    callback_data=InviteCallback(action="cancel", event_id=event_id).pack(),
                )
            ]
        ]
    )


def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📅 Активні події")]],
        resize_keyboard=True,
    )


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент")],
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
            [KeyboardButton(text="❌ Скасувати івент")],
        ],
        resize_keyboard=True,
    )


# ================== START / NICKNAME ==================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT display_name, role FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()

    if not row:
        cursor.execute(
            """
            INSERT INTO users (user_id, username, display_name, role, created_at)
            VALUES (?, ?, NULL, 'player', datetime('now'))
            """,
            (user_id, username),
        )
        conn.commit()
        conn.close()

        await message.answer(
            "👋 Вітаю!\n\nВведіть, будь ласка, **нік**",
            parse_mode="Markdown",
        )
        await state.set_state(NicknameState.waiting_for_nickname)
        return

    display_name, role = row
    conn.close()

    if not display_name:
        await message.answer(
            "👋 Вітаю!\n\nВведіть, будь ласка, **нік**",
            parse_mode="Markdown",
        )
        await state.set_state(NicknameState.waiting_for_nickname)
        return

    keyboard = admin_menu_keyboard() if role == "admin" else player_menu_keyboard()

    await message.answer(
        f"З поверненням, **{display_name}** 👋",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@dp.message(NicknameState.waiting_for_nickname)
async def save_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()

    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("❌ Нік має бути від 2 до 20 символів.")
        return

    user_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET display_name = ? WHERE user_id = ?",
        (nickname, user_id),
    )
    conn.commit()
    conn.close()

    await state.clear()

    await message.answer(
        f"✅ Готово! Ваш нік: **{nickname}**",
        parse_mode="Markdown",
        reply_markup=player_menu_keyboard(),
    )


# ================== ACTIVE EVENTS ==================

@dp.message(F.text == "📅 Активні події")
async def show_active_events(message: types.Message):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT event_id, title, event_date, event_time
        FROM events
        WHERE status = 'active'
        ORDER BY created_at DESC
        """
    )
    events = cursor.fetchall()
    conn.close()

    if not events:
        await message.answer("ℹ️ Наразі немає активних івентів")
        return

    for event_id, title, event_date, event_time in events:
        await message.answer(
            f"🎭 *{title}*\n📅 {event_date}\n⏰ {event_time}",
            parse_mode="Markdown",
            reply_markup=invite_keyboard(event_id),
        )


# ================== CREATE EVENT (ADMIN) ==================

@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM users WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] != "admin":
        await message.answer("❌ У вас немає прав")
        return

    await message.answer("📝 Введіть назву івенту:")
    await state.set_state(CreateEventStates.waiting_for_title)


@dp.message(CreateEventStates.waiting_for_title)
async def create_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Введіть дату (DD-MM-YYYY):")
    await state.set_state(CreateEventStates.waiting_for_date)


@dp.message(CreateEventStates.waiting_for_date)
async def create_event_date(message: types.Message, state: FSMContext):
    await state.update_data(event_date=message.text)
    await message.answer("⏰ Введіть час (HH:MM):")
    await state.set_state(CreateEventStates.waiting_for_time)


@dp.message(CreateEventStates.waiting_for_time)
async def create_event_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data["title"]
    event_date = data["event_date"]
    event_time = message.text
    admin_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO events (title, event_date, event_time, status, created_by, created_at)
        VALUES (?, ?, ?, 'active', ?, datetime('now'))
        """,
        (title, event_date, event_time, admin_id),
    )
    conn.commit()
    event_id = cursor.lastrowid

    cursor.execute(
        "SELECT user_id FROM users WHERE role = 'player' AND is_active = 1"
    )
    players = cursor.fetchall()
    conn.close()

    for (player_id,) in players:
        try:
            await bot.send_message(
                player_id,
                f"🎭 *{title}*\n📅 {event_date}\n⏰ {event_time}",
                parse_mode="Markdown",
                reply_markup=invite_keyboard(event_id),
            )
        except Exception:
            pass

    await state.clear()
    await message.answer("✅ Івент створено")


# ================== JOIN / COMMENT / CANCEL ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def invite_join(
    callback: types.CallbackQuery,
    callback_data: InviteCallback,
    state: FSMContext,
):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1 FROM registrations
        WHERE event_id = ? AND user_id = ? AND status = 'active'
        """,
        (event_id, user_id),
    )
    if cursor.fetchone():
        conn.close()
        await callback.answer("Ви вже записані")
        return

    cursor.execute(
        """
        INSERT INTO registrations (event_id, user_id, status, created_at, updated_at)
        VALUES (?, ?, 'active', datetime('now'), datetime('now'))
        """,
        (event_id, user_id),
    )
    conn.commit()
    conn.close()

    await callback.message.edit_reply_markup()
    await callback.answer("Записано")

    await state.set_state(CommentState.waiting_for_comment)
    await state.update_data(event_id=event_id)

    await bot.send_message(
        user_id,
        "💬 Залиште коментар або напишіть `-`",
        parse_mode="Markdown",
    )


@dp.message(CommentState.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    comment = message.text.strip()
    if comment == "-":
        comment = None

    data = await state.get_data()
    event_id = data["event_id"]
    user_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE registrations
        SET comment = ?, updated_at = datetime('now')
        WHERE event_id = ? AND user_id = ? AND status = 'active'
        """,
        (comment, event_id, user_id),
    )
    conn.commit()

    cursor.execute(
        """
        SELECT e.title, e.event_date, e.event_time, u.display_name, e.created_by
        FROM events e
        JOIN users u ON u.user_id = ?
        WHERE e.event_id = ?
        """,
        (user_id, event_id),
    )
    event = cursor.fetchone()
    conn.close()

    await state.clear()
    await message.answer("✅ Ви записані!", reply_markup=cancel_keyboard(event_id))

    if event:
        title, date, time, name, admin_id = event
        await bot.send_message(
            admin_id,
            f"🆕 Нова реєстрація\n🎭 {title}\n👤 {name}\n💬 {comment or '—'}",
        )

@dp.callback_query(InviteCallback.filter(F.action == "ignore"))
async def invite_ignore(callback: types.CallbackQuery):
    # 1️⃣ Обовʼязково відповідаємо Telegram
    await callback.answer("Запрошення проігноровано ❌")

    # 2️⃣ Прибираємо кнопки під повідомленням
    await callback.message.edit_reply_markup(reply_markup=None)

@dp.callback_query(InviteCallback.filter(F.action == "cancel"))
async def invite_cancel(callback: types.CallbackQuery, callback_data: InviteCallback):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE registrations
        SET status = 'cancelled', updated_at = datetime('now')
        WHERE event_id = ? AND user_id = ? AND status = 'active'
        """,
        (event_id, user_id),
    )
    conn.commit()

    cursor.execute(
        """
        SELECT title, event_date, event_time
        FROM events
        WHERE event_id = ?
        """,
        (event_id,),
    )
    event = cursor.fetchone()
    conn.close()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Запис скасовано ❌")

    await bot.send_message(user_id, "❌ Ваш запис скасовано")

    if event:
        title, date, time = event
        # за бажанням — можна повідомити адміна


# ================== ADMIN ACTIONS ==================

@dp.message(F.text == "👥 Список гравців")
async def show_players(message: types.Message):
    user_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM users WHERE user_id = ? AND is_active = 1",
        (user_id,),
    )
    if cursor.fetchone()[0] != "admin":
        conn.close()
        return

    cursor.execute(
        """
        SELECT event_id, title, event_date, event_time
        FROM events
        WHERE status = 'active'
        ORDER BY created_at DESC LIMIT 1
        """
    )
    event = cursor.fetchone()

    if not event:
        conn.close()
        await message.answer("ℹ️ Немає активного івенту")
        return

    event_id, title, date, time = event

    cursor.execute(
        """
        SELECT u.display_name, r.status, r.comment
        FROM registrations r
        JOIN users u ON u.user_id = r.user_id
        WHERE r.event_id = ?
        """,
        (event_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    text = f"🎭 *{title}*\n📅 {date}\n⏰ {time}\n\n"

    text += "✅ Записані:\n"
    for name, status, comment in rows:
        if status == "active":
            text += f"- {name}"
            if comment:
                text += f" ({comment})"
            text += "\n"

    await message.answer(text, parse_mode="Markdown")


@dp.message(F.text == "❌ Скасувати івент")
async def cancel_event(message: types.Message):
    user_id = message.from_user.id

    conn = get_connection()
    cursor = conn.cursor()

    # 1️⃣ перевірка адміна
    cursor.execute(
        "SELECT role FROM users WHERE user_id = ? AND is_active = 1",
        (user_id,)
    )
    row = cursor.fetchone()
    if not row or row[0] != "admin":
        conn.close()
        return

    # 2️⃣ беремо активний івент
    cursor.execute(
        """
        SELECT event_id, title, event_date, event_time
        FROM events
        WHERE status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    event = cursor.fetchone()

    if not event:
        conn.close()
        await message.answer("ℹ️ Немає активного івенту")
        return

    event_id, title, date, time = event

    # 3️⃣ ВАЖЛИВО: спочатку беремо гравців
    cursor.execute(
        """
        SELECT user_id
        FROM registrations
        WHERE event_id = ? AND status = 'active'
        """,
        (event_id,)
    )
    players = cursor.fetchall()

    # 4️⃣ тепер скасовуємо івент
    cursor.execute(
        "UPDATE events SET status = 'closed' WHERE event_id = ?",
        (event_id,)
    )

    cursor.execute(
        """
        UPDATE registrations
        SET status = 'cancelled', updated_at = datetime('now')
        WHERE event_id = ? AND status = 'active'
        """,
        (event_id,)
    )

    conn.commit()
    conn.close()

    # 5️⃣ РОЗСИЛКА ГРАВЦЯМ
    for (player_id,) in players:
        try:
            await bot.send_message(
                player_id,
                "😔 *Ігровий вечір скасовано*\n\n"
                f"🎭 {title}\n"
                f"📅 {date}\n"
                f"⏰ {time}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    # 6️⃣ підтвердження адміну
    await message.answer(
        f"❌ Івент скасовано\n\n"
        f"📣 Повідомлено гравців: {len(players)}"
    )


# ================== RUN ==================

async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
