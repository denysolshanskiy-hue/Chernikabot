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
from aiogram.client.session.aiohttp import AiohttpSession

# Імпортуємо функції з вашого нового database.py
from database import get_connection, init_db

# ================== INIT ==================
# Отримуємо токен з Environment Variables Koyeb
BOT_TOKEN = os.getenv("BOT_TOKEN")
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
def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Створити івент")],
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
            [KeyboardButton(text="🛠 Адмін: список + скасовані")],
            [KeyboardButton(text="✅ Підтвердити вечір")],
            [KeyboardButton(text="❌ Скасувати івент")],
        ],
        resize_keyboard=True
    )

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
                    text="❌ Скасувати запис",
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

def player_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Активні події")],
            [KeyboardButton(text="👥 Список гравців")],
        ],
        resize_keyboard=True
    )


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            # Перший ряд: Основні дії з івентом
            [
                KeyboardButton(text="➕ Створити івент"),
                KeyboardButton(text="📅 Активні події")
            ],
            # Другий ряд: Робота з гравцями та списками
            [
                KeyboardButton(text="👥 Список гравців"),
                KeyboardButton(text="🛠 Адмін: список + скасовані")
            ],
            # Третій ряд: Управління поточним вечором
            [
                KeyboardButton(text="✅ Підтвердити вечір"),
                KeyboardButton(text="🏁 Завершити вечір")
            ],
            # Четвертий ряд: "Небезпечна" кнопка (окремо, щоб не натиснути випадково)
            [
                KeyboardButton(text="❌ Скасувати івент")
            ]
        ],
        resize_keyboard=True
    )



# ================== START / NICKNAME ==================

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username

    conn = await get_connection()
    try:
        # PostgreSQL використовує $1 замість ?
        row = await conn.fetchrow(
            "SELECT display_name, role FROM users WHERE user_id = $1",
            user_id,
        )

        if not row:
            await conn.execute(
                """
                INSERT INTO users (user_id, username, display_name, role)
                VALUES ($1, $2, NULL, 'player')
                """,
                user_id, username,
            )
            await message.answer(
                "👋 Вітаю!\n\nВведіть, будь ласка, ваш **нік** для ігор:",
                parse_mode="Markdown",
            )
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        display_name, role = row['display_name'], row['role']
        
        if not display_name:
            await message.answer("Введіть, будь ласка, ваш **нік**:")
            await state.set_state(NicknameState.waiting_for_nickname)
            return

        keyboard = admin_menu_keyboard() if role == "admin" else player_menu_keyboard()
        await message.answer(
            f"З поверненням, **{display_name}** 👋",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    finally:
        await conn.close()

@dp.message(NicknameState.waiting_for_nickname)
async def save_nickname(message: types.Message, state: FSMContext):
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("❌ Нік має бути від 2 до 20 символів.")
        return

    user_id = message.from_user.id
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET display_name = $1 WHERE user_id = $2",
            nickname, user_id,
        )
        await state.clear()
        await message.answer(
            f"✅ Готово! Ваш нік: **{nickname}**",
            parse_mode="Markdown",
            reply_markup=player_menu_keyboard(),
        )
    finally:
        await conn.close()

# ================== Colse Event ==================

@dp.message(F.text == "🏁 Завершити вечір")
async def archive_event(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        # Перевірка на адміна
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin":
            return

        # Знаходимо останній активний івент
        event = await conn.fetchrow(
            "SELECT event_id, title FROM events WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів для завершення.")
            return

        # Змінюємо статус на 'closed'
        await conn.execute(
            "UPDATE events SET status = 'closed' WHERE event_id = $1", 
            event['event_id']
        )

        await message.answer(f"✅ Івент **{event['title']}** успішно завершено та перенесено в архів.", parse_mode="Markdown")

    finally:
        await conn.close()


# ================== ACTIVE EVENTS ==================

@dp.message(F.text == "📅 Активні події")
async def show_active_events(message: types.Message):
    conn = await get_connection()
    try:
        events = await conn.fetch(
            """
            SELECT event_id, title, event_date, event_time
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
                f"🎭 *{ev['title']}*\n📅 {ev['event_date']}\n⏰ {ev['event_time']}",
                parse_mode="Markdown",
                reply_markup=invite_keyboard(ev['event_id']),
            )
    finally:
        await conn.close()

# ================== CREATE EVENT (ADMIN) ==================

@dp.message(F.text == "➕ Створити івент")
async def create_event_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin":
            await message.answer("❌ У вас немає прав адміністратора")
            return

        await message.answer("📝 Введіть назву івенту (наприклад: Мафія Класика):")
        await state.set_state(CreateEventStates.waiting_for_title)
    finally:
        await conn.close()

@dp.message(CreateEventStates.waiting_for_title)
async def create_event_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("📅 Введіть дату (наприклад: 20.01):")
    await state.set_state(CreateEventStates.waiting_for_date)

@dp.message(CreateEventStates.waiting_for_date)
async def create_event_date(message: types.Message, state: FSMContext):
    await state.update_data(event_date=message.text)
    await message.answer("⏰ Введіть час (наприклад: 19:00):")
    await state.set_state(CreateEventStates.waiting_for_time)

@dp.message(CreateEventStates.waiting_for_time)
async def create_event_time(message: types.Message, state: FSMContext):
    data = await state.get_data()
    title = data["title"]
    event_date = data["event_date"]
    event_time = message.text
    admin_id = message.from_user.id

    conn = await get_connection()
    try:
        # 1. Зберігаємо івент у базу
        event_id = await conn.fetchval(
            """
            INSERT INTO events (title, event_date, event_time, status, created_by)
            VALUES ($1, $2, $3, 'active', $4)
            RETURNING event_id
            """,
            title, event_date, event_time, admin_id,
        )

        # 2. Отримуємо список усіх активних гравців
        players = await conn.fetch("SELECT user_id FROM users WHERE is_active = 1")
        
        # 3. Розсилаємо повідомлення
        sent_count = 0
        for p in players:
            try:
                await bot.send_message(
                    p['user_id'],
                    f"🔔 *Новий івент!*\n\n🎭 *{title}*\n📅 {event_date}\n⏰ {event_time}",
                    parse_mode="Markdown",
                    reply_markup=invite_keyboard(event_id),
                )
                sent_count += 1
            except Exception:
                # Пропускаємо, якщо бот заблокований користувачем
                continue

        # 4. Очищуємо стан та видаємо звіт як на скріншоті
        await state.clear()
        await message.answer(
            f"✅ Івент створено!\n"
            f"📢 Запрошення розіслано гравцям: **{sent_count}**",
            parse_mode="Markdown"
        )
        
    finally:
        await conn.close()
#=================== COMMIT EVENT ====================
@dp.message(F.text == "✅ Підтвердити вечір")
async def confirm_event_start(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        # Перевірка на адміна
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin":
            return

        # Шукаємо останній активний івент
        event = await conn.fetchrow(
            "SELECT event_id, title, event_date FROM events WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів для підтвердження.")
            return

        # Кнопка для остаточного підтвердження
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🚀 ВІДПРАВИТИ ПІДТВЕРДЖЕННЯ", 
                callback_data=f"send_confirm_{event['event_id']}"
            )]
        ])

        await message.answer(
            f"❓ Надіслати гравцям підтвердження, що вечір відбудеться?\n🎭 *{event['title']}* ({event['event_date']})",
            parse_mode="Markdown",
            reply_markup=kb
        )
    finally:
        await conn.close()

@dp.callback_query(F.data.startswith("send_confirm_"))
async def process_send_confirmation(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    
    conn = await get_connection()
    try:
        # 1. Отримуємо список усіх активних гравців на цей івент
        players = await conn.fetch(
            "SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'", 
            event_id
        )

        if not players:
            await callback.answer("На цей івент ще ніхто не записався", show_alert=True)
            return

        # 2. Розсилаємо повідомлення
        success_count = 0
        for p in players:
            try:
                await bot.send_message(
                    p['user_id'], 
                    "✅ Ігровий вечір в силі! Чекаємо на тебе🫶"
                )
                success_count += 1
            except Exception:
                continue

        # 3. Змінюємо повідомлення у адміна
        await callback.message.edit_text(
            f"✅ Підтвердження надіслано!\n👥 Гравців сповіщено: **{success_count}**",
            parse_mode="Markdown"
        )
        await callback.answer("Розсилку завершено")

    finally:
        await conn.close()

# ================== JOIN / COMMENT / CANCEL ==================

@dp.callback_query(InviteCallback.filter(F.action == "join"))
async def invite_join(callback: types.CallbackQuery, callback_data: InviteCallback, state: FSMContext):
    user_id = callback.from_user.id
    event_id = callback_data.event_id

    conn = await get_connection()
    try:
        existing = await conn.fetchval(
            "SELECT 1 FROM registrations WHERE event_id = $1 AND user_id = $2 AND status = 'active'",
            event_id, user_id
        )
        if existing:
            await callback.answer("Ви вже записані на цей івент")
            return

        await conn.execute(
            """
            INSERT INTO registrations (event_id, user_id, status)
            VALUES ($1, $2, 'active')
            """,
            event_id, user_id
        )
        
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Ви записані!")

        await state.set_state(CommentState.waiting_for_comment)
        await state.update_data(event_id=event_id)
        await bot.send_message(user_id, "💬 Напишіть коментар (наприклад: +1) або надішліть `-` щоб пропустити")
    finally:
        await conn.close()

@dp.message(CommentState.waiting_for_comment)
async def save_comment(message: types.Message, state: FSMContext):
    comment = None if message.text.strip() == "-" else message.text.strip()
    data = await state.get_data()
    event_id = data.get("event_id")
    user_id = message.from_user.id

    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE registrations SET comment = $1 WHERE event_id = $2 AND user_id = $3 AND status = 'active'",
            comment, event_id, user_id
        )
        
        event_info = await conn.fetchrow(
            "SELECT e.title, u.display_name, e.created_by FROM events e JOIN users u ON u.user_id = $1 WHERE e.event_id = $2",
            user_id, event_id
        )
        
        await state.clear()
        await message.answer("✅ Запис підтверджено!", reply_markup=cancel_keyboard(event_id))

        if event_info:
            await bot.send_message(
                event_info['created_by'],
                f"🆕 *Реєстрація*\n🎭 {event_info['title']}\n👤 {event_info['display_name']}\n💬 {comment or '—'}",
                parse_mode="Markdown"
            )
    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "cancel"))
async def invite_cancel(callback: types.CallbackQuery, callback_data: InviteCallback):
    user_id = callback.from_user.id
    event_id = callback_data.event_id
    MY_ADMIN_ID = 444726017  

    conn = await get_connection()
    try:
        # 1. Отримуємо дані одним запитом: назву івенту та нікнейм користувача
        event_title = await conn.fetchval("SELECT title FROM events WHERE event_id = $1", int(event_id))
        user_nick = await conn.fetchval("SELECT display_name FROM users WHERE user_id = $1", int(user_id))
        
        # Якщо нік раптом не знайдено (хоча він має бути), використовуємо повне ім'я з телеграму
        display_name = user_nick or callback.from_user.full_name

        # 2. Оновлюємо статус у базі
        await conn.execute(
            "UPDATE registrations SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE event_id = $1 AND user_id = $2",
            int(event_id), int(user_id)
        )
        
        # 3. Прибираємо кнопки та підтверджуємо гравцю
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Запис скасовано")
        await bot.send_message(user_id, "❌ Ви скасували свій запис на івент")

        # 4. СПОВІЩЕННЯ АДМІНА (тепер з ніком)
        # Додаємо умову, щоб не спамити вам, коли ви самі скасовуєте (якщо хочете бачити завжди — просто видаліть if)
        if user_id != MY_ADMIN_ID:
            await bot.send_message(
                chat_id=MY_ADMIN_ID,
                text=(
                    f"⚠️ **Скасування реєстрації!**\n\n"
                    f"🎭 Івент: **{event_title or 'Невідомий'}**\n"
                    f"👤 Гравець: **{display_name}**\n"
                    f"🆔 ID: `{user_id}`"
                ),
                parse_mode="Markdown"
            )

    except Exception as e:
        print(f"ПОМИЛКА ОБРОБКИ SQL: {e}")
    finally:
        await conn.close()

@dp.callback_query(InviteCallback.filter(F.action == "ignore"))
async def invite_ignore(callback: types.CallbackQuery):
    await callback.answer("Проігноровано")
    await callback.message.delete()

# ================== ADMIN ACTIONS ==================

@dp.message(F.text == "👥 Список гравців")
async def show_players_public(message: types.Message):
    conn = await get_connection()

    try:
        event = await conn.fetchrow(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних ігрових вечорів")
            return

        players = await conn.fetch(
            """
            SELECT u.display_name, r.comment
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
            ORDER BY r.created_at
            """,
            event["event_id"]
        )

        text = f"👥 *Гравці на івенті:* _{event['title']}_\n\n"

        if not players:
            text += "— Поки ніхто не записався"
        else:
            for i, p in enumerate(players, 1):
                comment = f" ({p['comment']})" if p["comment"] else ""
                text += f"{i}. {p['display_name']}{comment}\n"

        await message.answer(text, parse_mode="Markdown")

    finally:
        await conn.close()

@dp.message(F.text == "🛠 Адмін: список + скасовані")
async def show_players_admin(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()

    try:
        role = await conn.fetchval(
            "SELECT role FROM users WHERE user_id = $1 AND is_active = 1",
            user_id
        )
        if role != "admin":
            await message.answer("❌ Команда доступна лише адміну")
            return

        event = await conn.fetchrow(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів")
            return

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

        active_players = []
        cancelled_players = []

        for r in rows:
            if r["status"] == "active":
                line = r["display_name"]
                if r["comment"]:
                    line += f" ({r['comment']})"
                active_players.append(line)
            elif r["status"] == "cancelled":
                cancelled_players.append(r["display_name"])

        # Формуємо заголовок звіту
        text = f"🛠 *Адмін-звіт по івенту:* _{event['title']}_\n\n"

        # Списки активних гравців
        text += "✅ **Активні:**\n"
        if not active_players:
            text += "— Поки ніхто не записався\n"
        else:
            # ТУТ БУЛА ПОМИЛКА: додаємо 4 пробіли перед text +=
            for i, player in enumerate(active_players, start=1):
                text += f"{i}. {player}\n"

        # Список тих, хто скасував
        text += "\n❌ **Скасували:**\n"
        if not cancelled_players:
            text += "—"
        else:
            # Нумеруємо також і список скасування для зручності
            for i, p in enumerate(cancelled_players, start=1):
                text += f"{i}. {p}\n"

        await message.answer(text, parse_mode="Markdown")

    finally:
        await conn.close()
# ================== CANCEL EVENT ADMIN ==================
@dp.message(F.text == "❌ Скасувати івент")
async def request_cancel_event(message: types.Message):
    user_id = message.from_user.id
    conn = await get_connection()
    try:
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", user_id)
        if not row or row['role'] != "admin":
            await message.answer("❌ У вас немає прав адміністратора")
            return

        # Шукаємо останній активний івент
        event = await conn.fetchrow(
            "SELECT event_id, title, event_date FROM events WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        )

        if not event:
            await message.answer("ℹ️ Немає активних івентів для скасування.")
            return

        # Створюємо інлайн-кнопку для підтвердження
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔥 ПІДТВЕРДИТИ СКАСУВАННЯ", 
                callback_data=f"confirm_cancel_{event['event_id']}"
            )]
        ])

        await message.answer(
            f"❓ Ви впевнені, що хочете скасувати івент:\n🎭 *{event['title']}* ({event['event_date']})?",
            parse_mode="Markdown",
            reply_markup=kb
        )
    finally:
        await conn.close()
        
@dp.callback_query(F.data.startswith("confirm_cancel_"))
async def admin_confirm_cancel(callback: types.CallbackQuery):
    event_id = int(callback.data.split("_")[2])
    
    conn = await get_connection()
    try:
        # Перевірка на адміна
        row = await conn.fetchrow("SELECT role FROM users WHERE user_id = $1", callback.from_user.id)
        if not row or row['role'] != "admin":
            await callback.answer("❌ Немає прав", show_alert=True)
            return

        # Отримуємо список гравців для сповіщення
        players_to_notify = await conn.fetch(
            "SELECT user_id FROM registrations WHERE event_id = $1 AND status = 'active'", 
            event_id
        )

        # Скасовуємо в базі
        await conn.execute("UPDATE events SET status = 'closed' WHERE event_id = $1", event_id)

        # Розсилаємо сповіщення
        for p in players_to_notify:
            try:
                await bot.send_message(
                    p['user_id'], 
                    "😔 На жаль, ігровий вечір скасовано. Слідкуйте за новими анонсами!"
                )
            except:
                continue

        await callback.message.edit_text(f"✅ Івент #{event_id} скасовано. Гравці ({len(players_to_notify)}) отримали повідомлення.")
        await callback.answer("Івент закрито")
    finally:
        await conn.close()
# ================== RUNNER & WEB SERVER ==================

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_all():
    # 1. Ініціалізація БД
    await init_db()

    # 2. Веб-сервер
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8000)))
    await site.start()

    # 3. Бот
    print("Starting bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(start_all())
    except (KeyboardInterrupt, SystemExit):
        pass

















