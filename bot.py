import asyncio
import sqlite3
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User as TelethonUser
import aiohttp
import pytz

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = '8469336460:AAEcuC0jiEwQjEMO6098qF-uYSPAFNXyCW0'
CRYPTOBOT_TOKEN = '505975:AAWB2WYvz4wJuseOm4nrs875jo4ORUJl7ww'
ADMIN_ID = 7037764178
API_ID = 30147101
API_HASH = '72c394e899371cf4f9f9253233cbf18f'
DATABASE_NAME = 'mart_snoser.db'

# Инициализация
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Telethon клиент с обработкой сессии
try:
    client = TelegramClient('user_session', API_ID, API_HASH)
    client.start()
    logger.info("Telethon клиент запущен успешно")
except Exception as e:
    logger.error(f"Ошибка запуска Telethon: {e}")

# Состояния FSM
class UserStates(StatesGroup):
    waiting_for_username = State()
    confirm_request = State()
    waiting_admin_user_id = State()
    waiting_admin_days = State()
    waiting_payment_check = State()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        subscription_end DATETIME,
        requests_today INTEGER DEFAULT 0,
        daily_reset_date DATE DEFAULT CURRENT_DATE,
        last_request_time DATETIME,
        total_requests INTEGER DEFAULT 0,
        joined_date DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Таблица платежей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        invoice_id TEXT UNIQUE,
        amount REAL,
        currency TEXT DEFAULT 'USDT',
        days INTEGER,
        status TEXT DEFAULT 'pending',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        paid_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Таблица запросов на снос
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS snos_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target_username TEXT,
        target_id INTEGER,
        target_info TEXT,
        status TEXT DEFAULT 'processing',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Таблица админ действий
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        action TEXT,
        target_user_id INTEGER,
        details TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Индексы для быстрого поиска
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_requests_user ON snos_requests(user_id)')
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def get_db_connection():
    return sqlite3.connect(DATABASE_NAME, check_same_thread=False)

def add_user(user_id: int, username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR IGNORE INTO users (user_id, username, joined_date)
    VALUES (?, ?, ?)
    ''', (user_id, username, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def get_user(user_id: int) -> Optional[tuple]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user_requests(user_id: int):
    """Обновляем счетчик запросов и время последнего запроса"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    UPDATE users 
    SET requests_today = requests_today + 1,
        last_request_time = ?,
        total_requests = total_requests + 1
    WHERE user_id = ?
    ''', (now, user_id))
    
    conn.commit()
    conn.close()

def reset_daily_limits():
    """Сбрасываем дневные лимиты для всех пользователей"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today = datetime.now().date().strftime('%Y-%m-%d')
    cursor.execute('''
    UPDATE users 
    SET requests_today = 0,
        daily_reset_date = ?
    WHERE daily_reset_date < ?
    ''', (today, today))
    
    conn.commit()
    conn.close()

def check_daily_reset(user_id: int):
    """Проверяем и сбрасываем дневной лимит если нужно"""
    user = get_user(user_id)
    if not user:
        return
    
    today = datetime.now().date().strftime('%Y-%m-%d')
    reset_date = datetime.strptime(user[4], '%Y-%m-%d').date() if user[4] else None
    
    if reset_date and reset_date < datetime.now().date():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE users 
        SET requests_today = 0,
            daily_reset_date = ?
        WHERE user_id = ?
        ''', (today, user_id))
        conn.commit()
        conn.close()

def check_cooldown(user_id: int) -> bool:
    """Проверяем кд между запросами (10 минут)"""
    user = get_user(user_id)
    if not user or not user[5]:  # last_request_time
        return True
    
    last_request = datetime.strptime(user[5], '%Y-%m-%d %H:%M:%S')
    cooldown_end = last_request + timedelta(minutes=10)
    
    return datetime.now() > cooldown_end

def get_cooldown_remaining(user_id: int) -> int:
    """Возвращает оставшееся время кд в секундах"""
    user = get_user(user_id)
    if not user or not user[5]:
        return 0
    
    last_request = datetime.strptime(user[5], '%Y-%m-%d %H:%M:%S')
    cooldown_end = last_request + timedelta(minutes=10)
    
    remaining = (cooldown_end - datetime.now()).total_seconds()
    return max(0, int(remaining))

def update_subscription(user_id: int, days: int):
    """Обновляем подписку пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    user = get_user(user_id)
    if user and user[2]:  # Если есть активная подписка
        current_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
        new_end = current_end + timedelta(days=days)
    else:
        new_end = datetime.now() + timedelta(days=days)
    
    cursor.execute('''
    UPDATE users SET subscription_end = ? WHERE user_id = ?
    ''', (new_end.strftime('%Y-%m-%d %H:%M:%S'), user_id))
    
    conn.commit()
    conn.close()
    
    return new_end

def check_subscription(user_id: int) -> bool:
    """Проверяем активна ли подписка"""
    user = get_user(user_id)
    if not user or not user[2]:
        return False
    
    subscription_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
    return datetime.now() < subscription_end

def get_subscription_info(user_id: int) -> Dict[str, Any]:
    """Получаем информацию о подписке"""
    user = get_user(user_id)
    if not user:
        return {"active": False, "days_left": 0, "end_date": None}
    
    if not user[2]:
        return {"active": False, "days_left": 0, "end_date": None}
    
    subscription_end = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
    now = datetime.now()
    
    if now >= subscription_end:
        return {"active": False, "days_left": 0, "end_date": subscription_end}
    
    days_left = (subscription_end - now).days
    return {
        "active": True,
        "days_left": days_left,
        "end_date": subscription_end,
        "requests_today": user[3],
        "requests_limit": 50,
        "cooldown": get_cooldown_remaining(user_id)
    }

def create_payment_record(user_id: int, invoice_id: str, amount: float, days: int):
    """Создаем запись о платеже"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT INTO payments (user_id, invoice_id, amount, days, status, created_at)
    VALUES (?, ?, ?, ?, 'pending', ?)
    ''', (user_id, invoice_id, amount, days, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    conn.commit()
    conn.close()

def update_payment_status(invoice_id: str, status: str):
    """Обновляем статус платежа"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    paid_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if status == 'paid' else None
    
    cursor.execute('''
    UPDATE payments 
    SET status = ?, paid_at = ?
    WHERE invoice_id = ?
    ''', (status, paid_at, invoice_id))
    
    conn.commit()
    
    # Если оплата подтверждена, активируем подписку
    if status == 'paid':
        cursor.execute('SELECT user_id, days FROM payments WHERE invoice_id = ?', (invoice_id,))
        payment = cursor.fetchone()
        if payment:
            user_id, days = payment
            update_subscription(user_id, days)
    
    conn.close()

def get_payment_by_invoice(invoice_id: str) -> Optional[tuple]:
    """Получаем информацию о платеже по invoice_id"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM payments WHERE invoice_id = ?', (invoice_id,))
    payment = cursor.fetchone()
    conn.close()
    return payment

def add_snos_request(user_id: int, target_username: str, target_info: dict):
    """Добавляем запрос на снос"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    target_info_json = json.dumps(target_info, ensure_ascii=False)
    
    cursor.execute('''
    INSERT INTO snos_requests (user_id, target_username, target_id, target_info, created_at)
    VALUES (?, ?, ?, ?, ?)
    ''', (user_id, target_username, target_info.get('id'), target_info_json, 
          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    
    request_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    return request_id

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """Получаем статистику пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Общие запросы
    cursor.execute('SELECT COUNT(*) FROM snos_requests WHERE user_id = ?', (user_id,))
    total_requests = cursor.fetchone()[0]
    
    # Успешные запросы
    cursor.execute('SELECT COUNT(*) FROM snos_requests WHERE user_id = ? AND status = "completed"', (user_id,))
    completed_requests = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_requests": total_requests,
        "completed_requests": completed_requests,
        "success_rate": (completed_requests / total_requests * 100) if total_requests > 0 else 0
    }

def get_bot_stats() -> Dict[str, Any]:
    """Получаем статистику бота"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    # Активные подписки
    cursor.execute('SELECT COUNT(*) FROM users WHERE subscription_end > datetime("now")')
    active_subs = cursor.fetchone()[0]
    
    # Запросы
    cursor.execute('SELECT COUNT(*) FROM snos_requests')
    total_requests = cursor.fetchone()[0]
    
    # Платежи
    cursor.execute('SELECT SUM(amount) FROM payments WHERE status = "paid"')
    total_revenue = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        "total_users": total_users,
        "active_subs": active_subs,
        "total_requests": total_requests,
        "total_revenue": total_revenue
    }

# ========== CRYPTOBOT API ==========
async def create_cryptobot_invoice(amount: float, description: str = "") -> Optional[Dict]:
    """Создаем инвойс через CryptoBot API"""
    url = f"https://pay.crypt.bot/api/createInvoice"
    
    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN,
        "Content-Type": "application/json"
    }
    
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "hidden_message": "Оплата подписки MartSnoser",
        "paid_btn_name": "callback",
        "paid_btn_url": f"https://t.me/MartSnoserBot",
        "allow_comments": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        return data.get("result")
                logger.error(f"CryptoBot API error: {await response.text()}")
                return None
    except Exception as e:
        logger.error(f"Error creating invoice: {e}")
        return None

async def check_cryptobot_invoice(invoice_id: str) -> Optional[Dict]:
    """Проверяем статус инвойса"""
    url = f"https://pay.crypt.bot/api/getInvoices"
    
    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
    }
    
    params = {
        "invoice_ids": invoice_id
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok") and data.get("result", {}).get("items"):
                        return data["result"]["items"][0]
                return None
    except Exception as e:
        logger.error(f"Error checking invoice: {e}")
        return None

# ========== TELEGRAM ACCOUNT INFO ==========
async def get_telegram_account_info(username: str) -> Optional[Dict[str, Any]]:
    """Получаем реальную информацию об аккаунте Telegram через Telethon"""
    try:
        async with client:
            # Убираем @ если есть
            username_clean = username.replace('@', '')
            
            try:
                # Получаем полную информацию об аккаунте
                entity = await client.get_entity(username_clean)
                
                if isinstance(entity, TelethonUser):
                    # Получаем подробную информацию
                    full_user = await client(GetFullUserRequest(entity))
                    
                    # Определяем дату создания (примерно)
                    # Telethon не предоставляет точную дату создания, но можно оценить по ID
                    # ID < 1000000000 обычно старые аккаунты
                    created_approx = "Старый аккаунт" if entity.id < 1000000000 else "Новый аккаунт"
                    
                    # Определяем дата-центр
                    if hasattr(entity, 'photo') and entity.photo:
                        dc_id = entity.photo.dc_id
                    else:
                        dc_id = "Неизвестно"
                    
                    # Статус
                    status = "Онлайн" if hasattr(entity, 'status') and entity.status else "Оффлайн"
                    
                    # Бот или нет
                    is_bot = entity.bot if hasattr(entity, 'bot') else False
                    
                    # Информация о премиуме
                    is_premium = entity.premium if hasattr(entity, 'premium') else False
                    
                    account_info = {
                        "id": entity.id,
                        "username": entity.username,
                        "first_name": entity.first_name or "",
                        "last_name": entity.last_name or "",
                        "phone": entity.phone or "Скрыт",
                        "is_bot": is_bot,
                        "is_premium": is_premium,
                        "status": status,
                        "dc_id": dc_id,
                        "created_approx": created_approx,
                        "has_profile_photo": bool(entity.photo),
                        "restricted": entity.restricted if hasattr(entity, 'restricted') else False,
                        "verified": entity.verified if hasattr(entity, 'verified') else False,
                        "scam": entity.scam if hasattr(entity, 'scam') else False,
                        "fake": entity.fake if hasattr(entity, 'fake') else False,
                        "bio": full_user.full_user.about if hasattr(full_user.full_user, 'about') else "Нет"
                    }
                    
                    return account_info
                else:
                    return None
                    
            except ValueError as e:
                logger.error(f"User not found: {e}")
                return None
            except Exception as e:
                logger.error(f"Error getting user info: {e}")
                return None
                
    except Exception as e:
        logger.error(f"Telethon client error: {e}")
        return None

async def simulate_snos_process(target_username: str, target_info: Dict) -> bool:
    """Имитируем процесс сноса аккаунта"""
    # В реальном боте здесь была бы интеграция с сервисом сноса
    # Сейчас это имитация
    
    await asyncio.sleep(2)  # Имитация обработки
    
    # Вероятность успешного сноса (в реальности зависит от многих факторов)
    import random
    success_chance = 0.7  # 70% шанс успеха
    
    return random.random() < success_chance

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="💰 Прайсич", callback_data="pricing")],
        [InlineKeyboardButton(text="📤 Отправка запросов", callback_data="send_request")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_pricing_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="3 дня - 1$", callback_data="subscribe_3")],
        [InlineKeyboardButton(text="7 дней - 5$", callback_data="subscribe_7")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="user_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_back_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_confirm_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="✅ Да, сносить!", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Нет, отмена", callback_data="confirm_no")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton(text="📊 Статистика бота", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_give_sub")],
        [InlineKeyboardButton(text="👥 Поиск пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_payment_keyboard(invoice_id: str, days: int):
    keyboard = [
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=f"https://t.me/CryptoBot?start={invoice_id}")],
        [InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data=f"check_payment_{invoice_id}_{days}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="pricing")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== ОСНОВНЫЕ ХЭНДЛЕРЫ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or f"user_{user_id}"
    
    # Добавляем пользователя в БД
    add_user(user_id, username)
    
    # Проверяем сброс дневных лимитов
    check_daily_reset(user_id)
    
    # Приветственное сообщение
    welcome_text = (
        "❝ Добро пожаловать в MartSnoser. Выбери действие: ❞"
    )
    
    # Отправляем баннер (заглушка - пользователь добавит своё фото)
    try:
        # Сначала отправляем баннер
        await message.answer_photo(
            photo="https://via.placeholder.com/600x200/1a1a2e/ffffff?text=MartSnoser+Banner",
            caption=welcome_text,
            reply_markup=get_main_keyboard()
        )
    except:
        # Если фото не загружено, отправляем только текст
        await message.answer(
            text=welcome_text,
            reply_markup=get_main_keyboard()
        )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    welcome_text = "❝ Добро пожаловать в MartSnoser. Выбери действие: ❞"
    
    try:
        await callback.message.edit_caption(
            caption=welcome_text,
            reply_markup=get_main_keyboard()
        )
    except:
        await callback.message.edit_text(
            text=welcome_text,
            reply_markup=get_main_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user:
        username = user[1] or "Не указан"
        sub_info = get_subscription_info(user_id)
        stats = get_user_stats(user_id)
        
        if sub_info["active"]:
            sub_status = f"✅ Активна ({sub_info['days_left']} дней)"
            requests_info = f"{sub_info['requests_today']}/{sub_info['requests_limit']}"
            
            if sub_info['cooldown'] > 0:
                cooldown_min = sub_info['cooldown'] // 60
                cooldown_sec = sub_info['cooldown'] % 60
                cooldown_text = f"\n⏳ КД: {cooldown_min}:{cooldown_sec:02d}"
            else:
                cooldown_text = "\n✅ Можно отправлять запрос"
        else:
            sub_status = "❌ Нет подписки"
            requests_info = "0/50"
            cooldown_text = ""
        
        profile_text = (
            f"👤 <b>Ваш профиль</b>\n\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Имя: @{username}\n"
            f"├ Подписка: {sub_status}\n"
            f"├ Запросы сегодня: {requests_info}{cooldown_text}\n"
            f"├ Всего запросов: {stats['total_requests']}\n"
            f"└ Успешных: {stats['completed_requests']} ({stats['success_rate']:.1f}%)\n\n"
            f"💎 <i>Подписка дает доступ ко всем функциям!</i>"
        )
    else:
        profile_text = "❌ Профиль не найден"
    
    try:
        await callback.message.edit_caption(
            caption=profile_text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
    except:
        await callback.message.edit_text(
            text=profile_text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "pricing")
async def show_pricing(callback: CallbackQuery):
    pricing_text = (
        "💰 <b>Прайсич подписок</b>\n\n"
        "┌ <b>3 дня - 1$</b>\n"
        "│ ├ 50 запросов в день\n"
        "│ ├ КД 10 минут\n"
        "│ ├ Инлайн режим\n"
        "│ └ Полная информация об аккаунтах\n\n"
        "└ <b>7 дней - 5$</b>\n"
        "  ├ Все возможности 3-дневной\n"
        "  ├ Приоритетная обработка\n"
        "  ├ Высокий приоритет сноса\n"
        "  └ Поддержка 24/7\n\n"
        "💎 Выбери подписку:"
    )
    
    try:
        await callback.message.edit_caption(
            caption=pricing_text,
            reply_markup=get_pricing_keyboard(),
            parse_mode="HTML"
        )
    except:
        await callback.message.edit_text(
            text=pricing_text,
            reply_markup=get_pricing_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "user_stats")
async def show_user_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    
    stats_text = (
        f"📊 <b>Ваша статистика</b>\n\n"
        f"├ Всего запросов: {stats['total_requests']}\n"
        f"├ Успешных: {stats['completed_requests']}\n"
        f"└ Успешность: {stats['success_rate']:.1f}%\n\n"
        f"<i>Статистика обновляется в реальном времени</i>"
    )
    
    try:
        await callback.message.edit_caption(
            caption=stats_text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
    except:
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("subscribe_"))
async def process_subscribe(callback: CallbackQuery):
    user_id = callback.from_user.id
    days = int(callback.data.split("_")[1])
    
    # Определяем цену
    prices = {3: 1.0, 7: 5.0}
    amount = prices.get(days, 1.0)
    
    # Создаем инвойс через CryptoBot
    description = f"Подписка MartSnoser на {days} дней"
    invoice = await create_cryptobot_invoice(amount, description)
    
    if invoice:
        invoice_id = invoice.get("invoice_id")
        pay_url = invoice.get("pay_url")
        
        # Сохраняем платеж в БД
        create_payment_record(user_id, invoice_id, amount, days)
        
        payment_text = (
            f"📋 <b>Оплата подписки на {days} дней</b>\n\n"
            f"├ Сумма: <b>{amount}$ USDT</b>\n"
            f"├ Срок: <b>{days} дней</b>\n"
            f"├ ID: <code>{invoice_id}</code>\n"
            f"└ Статус: ⏳ Ожидает оплаты\n\n"
            f"💳 <b>Инструкция:</b>\n"
            f"1. Нажмите кнопку ниже для оплаты\n"
            f"2. Оплатите через @CryptoBot\n"
            f"3. После оплаты нажмите '✅ Я оплатил(а)'"
        )
        
        await callback.message.edit_caption(
            caption=payment_text,
            reply_markup=get_payment_keyboard(invoice_id, days),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_caption(
            caption="❌ Ошибка при создании инвойса. Попробуйте позже.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data.startswith("check_payment_"))
async def check_payment_handler(callback: CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    invoice_id = data_parts[2]
    days = int(data_parts[3])
    user_id = callback.from_user.id
    
    # Проверяем статус платежа
    invoice_info = await check_cryptobot_invoice(invoice_id)
    
    if invoice_info:
        status = invoice_info.get("status")
        
        if status == "paid":
            # Обновляем статус платежа в БД
            update_payment_status(invoice_id, "paid")
            
            success_text = (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Подписка на {days} дней активирована.\n"
                f"Теперь у вас есть доступ ко всем функциям!\n\n"
                f"🎉 <i>Можете начинать использовать бота!</i>"
            )
            
            await callback.message.edit_caption(
                caption=success_text,
                reply_markup=get_back_keyboard(),
                parse_mode="HTML"
            )
            
        elif status == "active":
            await callback.message.edit_caption(
                caption="⏳ Оплата еще не поступила. Попробуйте через минуту.",
                reply_markup=get_payment_keyboard(invoice_id, days)
            )
        else:
            await callback.message.edit_caption(
                caption="❌ Платеж не найден или отменен.",
                reply_markup=get_back_keyboard()
            )
    else:
        await callback.message.edit_caption(
            caption="⚠️ Не удалось проверить платеж. Попробуйте позже.",
            reply_markup=get_back_keyboard()
        )
    
    await callback.answer()

@dp.callback_query(F.data == "send_request")
async def send_request_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Проверяем подписку
    if not check_subscription(user_id):
        await callback.message.edit_caption(
            caption="❌ <b>У вас нет активной подписки!</b>\n\n"
                   "Для доступа к функциям нужно купить подписку.\n"
                   "Перейдите в раздел '💰 Прайсич'",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    # Проверяем дневной лимит (50 запросов)
    check_daily_reset(user_id)
    user = get_user(user_id)
    
    if user and user[3] >= 50:  # 50 запросов в день
        await callback.message.edit_caption(
            caption="❌ <b>Вы исчерпали лимит запросов на сегодня!</b>\n\n"
                   "Лимит: 50 запросов в день\n"
                   "Обновится через: 00:00 по МСК",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    # Проверяем кд (10 минут)
    if not check_cooldown(user_id):
        cooldown_remaining = get_cooldown_remaining(user_id)
        minutes = cooldown_remaining // 60
        seconds = cooldown_remaining % 60
        
        await callback.message.edit_caption(
            caption=f"⏳ <b>Подождите перед следующим запросом</b>\n\n"
                   f"КД между запросами: 10 минут\n"
                   f"Осталось: {minutes}:{seconds:02d}",
            reply_markup=get_back_keyboard(),
            parse_mode="HTML"
        )
        await callback.answer()
        return
    
    await state.set_state(UserStates.waiting_for_username)
    
    await callback.message.edit_caption(
        caption="📝 <b>Отправка запроса на снос</b>\n\n"
               "Введите юзернейм цели (например: username или @username):\n\n"
               "<i>❗ Без @ в начале, только имя пользователя</i>",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(UserStates.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip().replace('@', '')
    
    if not username or len(username) < 3:
        await message.answer(
            "❌ Неверный юзернейм!\n"
            "Введите корректное имя пользователя:",
            reply_markup=get_back_keyboard()
        )
        return
    
    # Сохраняем в состояние
    await state.update_data(target_username=username)
    await state.set_state(UserStates.confirm_request)
    
    # Показываем загрузку
    loading_msg = await message.answer("🔍 <b>Сканируем аккаунт...</b>", parse_mode="HTML")
    
    # Получаем реальную информацию об аккаунте через Telethon
    account_info = await get_telegram_account_info(username)
    
    if account_info:
        # Форматируем информацию
        status_emoji = "🟢" if account_info["status"] == "Онлайн" else "🔴"
        premium_emoji = "⭐" if account_info["is_premium"] else ""
        bot_emoji = "🤖" if account_info["is_bot"] else "👤"
        verified_emoji = "☑️" if account_info["verified"] else ""
        
        info_text = (
            f"📊 <b>Найдена информация об аккаунте</b>\n\n"
            f"├ {bot_emoji} <b>Имя:</b> {account_info['first_name']} {account_info['last_name']}\n"
            f"├ 👤 <b>Юзернейм:</b> @{account_info['username']}\n"
            f"├ 🆔 <b>ID:</b> <code>{account_info['id']}</code>\n"
            f"├ {status_emoji} <b>Статус:</b> {account_info['status']}\n"
            f"├ 📅 <b>Создан:</b> {account_info['created_approx']}\n"
            f"├ 🌐 <b>Дата-центр:</b> DC{account_info['dc_id']}\n"
            f"├ {premium_emoji} <b>Премиум:</b> {'Да' if account_info['is_premium'] else 'Нет'}\n"
            f"├ {verified_emoji} <b>Вериф:</b> {'Да' if account_info['verified'] else 'Нет'}\n"
            f"├ 📸 <b>Фото:</b> {'Есть' if account_info['has_profile_photo'] else 'Нет'}\n"
            f"├ ⚠️ <b>Ограничен:</b> {'Да' if account_info['restricted'] else 'Нет'}\n"
            f"├ 🚫 <b>Скам:</b> {'ДА ⚠️' if account_info['scam'] else 'Нет'}\n"
            f"└ 📝 <b>Био:</b> {account_info['bio'][:50]}...\n\n"
            f"<b>Вы точно хотите отправить запрос на снос этого аккаунта?</b>"
        )
        
        await state.update_data(target_info=account_info)
    else:
        info_text = (
            f"⚠️ <b>Аккаунт не найден или недоступен</b>\n\n"
            f"Цель: @{username}\n"
            f"Статус: Не удалось получить информацию\n\n"
            f"<i>Вы все равно хотите отправить запрос на снос?</i>"
        )
    
    # Удаляем сообщение о загрузке
    await loading_msg.delete()
    
    await message.answer(
        text=info_text,
        reply_markup=get_confirm_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "confirm_yes", UserStates.confirm_request)
async def confirm_request(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    target_username = user_data.get('target_username')
    target_info = user_data.get('target_info', {})
    user_id = callback.from_user.id
    
    # Проверяем кд еще раз
    if not check_cooldown(user_id):
        await callback.answer("⏳ Подождите перед следующим запросом!", show_alert=True)
        return
    
    # Обновляем счетчик запросов
    update_user_requests(user_id)
    
    # Сохраняем запрос в БД
    request_id = add_snos_request(user_id, target_username, target_info)
    
    # Отправляем прогресс бар
    progress_msg = await callback.message.edit_caption(
        caption="🚀 <b>Начинаем процесс сноса...</b>\n\n"
               "[░░░░░░░░░░] 0%",
        parse_mode="HTML"
    )
    
    # Имитация прогресс бара с реальными этапами
    stages = [
        ("🔍 Сканируем аккаунт...", 10),
        ("📡 Устанавливаем соединение...", 20),
        ("🔧 Подготавливаем систему...", 30),
        ("⚡ Запускаем процедуру...", 50),
        ("🎯 Цель заблокирована...", 70),
        ("🚀 Запускаем финальную стадию...", 85),
        ("✅ Процесс завершен!", 100)
    ]
    
    for stage_text, stage_percent in stages:
        await asyncio.sleep(1.5)
        progress = "█" * (stage_percent // 10) + "░" * (10 - stage_percent // 10)
        
        try:
            await progress_msg.edit_caption(
                caption=f"🚀 <b>Процесс сноса</b>\n\n"
                       f"{stage_text}\n"
                       f"[{progress}] {stage_percent}%",
                parse_mode="HTML"
            )
        except:
            pass
    
    # Имитируем результат
    success = await simulate_snos_process(target_username, target_info)
    
    if success:
        result_text = (
            f"✅ <b>Запрос успешно обработан!</b>\n\n"
            f"Цель: @{target_username}\n"
            f"ID запроса: <code>{request_id}</code>\n"
            f"Статус: Успешно отправлен в систему\n\n"
            f"<i>Обычно снос занимает 24-72 часа.\n"
            f"Вы получите уведомление о результате.</i>"
        )
        
        # Обновляем статус запроса в БД
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE snos_requests SET status = 'completed', completed_at = ?
        WHERE id = ?
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), request_id))
        conn.commit()
        conn.close()
    else:
        result_text = (
            f"⚠️ <b>Запрос отправлен, но нужна дополнительная проверка</b>\n\n"
            f"Цель: @{target_username}\n"
            f"ID запроса: <code>{request_id}</code>\n"
            f"Статус: Требует ручной проверки\n\n"
            f"<i>Наши операторы проверят аккаунт\n"
            f"и уведомят вас о результате.</i>"
        )
    
    # Отправляем результат
    await progress_msg.edit_caption(
        caption=result_text,
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "confirm_no", UserStates.confirm_request)
async def cancel_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(
        caption="❌ Запрос отменен пользователем.",
        reply_markup=get_back_keyboard()
    )
    await state.clear()
    await callback.answer()

# ========== АДМИН ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен!")
        return
    
    admin_text = (
        "🛠️ <b>Админ панель MartSnoser</b>\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=admin_text,
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    stats = get_bot_stats()
    
    # Получаем последние платежи
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT u.username, p.amount, p.days, p.created_at 
    FROM payments p
    JOIN users u ON p.user_id = u.user_id
    WHERE p.status = 'paid'
    ORDER BY p.paid_at DESC
    LIMIT 5
    ''')
    recent_payments = cursor.fetchall()
    conn.close()
    
    stats_text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"┌ <b>Пользователи:</b>\n"
        f"├ Всего: {stats['total_users']}\n"
        f"├ С подпиской: {stats['active_subs']}\n"
        f"└ Активность: {stats['active_subs']/stats['total_users']*100:.1f}%\n\n"
        f"┌ <b>Запросы:</b>\n"
        f"└ Всего: {stats['total_requests']}\n\n"
        f"┌ <b>Финансы:</b>\n"
        f"└ Общая выручка: ${stats['total_revenue']:.2f}\n\n"
        f"<b>Последние платежи:</b>\n"
    )
    
    for payment in recent_payments:
        username, amount, days, created_at = payment
        stats_text += f"├ @{username}: ${amount} ({days} д.)\n"
    
    if recent_payments:
        stats_text += "└ ...\n"
    
    try:
        await callback.message.edit_caption(
            caption=stats_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except:
        await callback.message.edit_text(
            text=stats_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "admin_give_sub")
async def admin_give_sub(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserStates.waiting_admin_user_id)
    
    await callback.message.edit_caption(
        caption="👤 <b>Выдача подписки</b>\n\n"
               "Введите ID пользователя или @юзернейм:",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(UserStates.waiting_admin_user_id)
async def process_admin_user_id(message: Message, state: FSMContext):
    user_input = message.text.strip()
    
    try:
        # Пробуем получить user_id разными способами
        if user_input.isdigit():
            user_id = int(user_input)
            user = get_user(user_id)
        elif user_input.startswith('@'):
            # Поиск по юзернейму
            username = user_input[1:]
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users WHERE username = ?', (username,))
            result = cursor.fetchone()
            conn.close()
            
            if result:
                user_id = result[0]
                user = get_user(user_id)
            else:
                await message.answer("❌ Пользователь не найден!")
                return
        else:
            await message.answer("❌ Неверный формат! Введите ID или @юзернейм")
            return
        
        if not user:
            await message.answer("❌ Пользователь не найден в базе данных!")
            return
        
        await state.update_data(admin_user_id=user_id)
        await state.set_state(UserStates.waiting_admin_days)
        
        await message.answer(
            f"👤 Найден пользователь: @{user[1]}\n"
            f"ID: {user_id}\n\n"
            "⏳ Введите количество дней для подписки:",
            parse_mode="HTML"
        )
        
    except ValueError:
        await message.answer("❌ Неверный ID! Введите число.")

@dp.message(UserStates.waiting_admin_days)
async def process_admin_days(message: Message, state: FSMContext):
    try:
        days = int(message.text)
        if days <= 0 or days > 365:
            await message.answer("❌ Неверное количество дней! (1-365)")
            return
        
        user_data = await state.get_data()
        user_id = user_data.get('admin_user_id')
        
        if user_id:
            # Выдаем подписку
            end_date = update_subscription(user_id, days)
            
            # Сохраняем действие админа
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO admin_actions (admin_id, action, target_user_id, details)
            VALUES (?, ?, ?, ?)
            ''', (ADMIN_ID, 'give_subscription', user_id, 
                  f'{days} дней, до {end_date.strftime("%Y-%m-%d")}'))
            conn.commit()
            conn.close()
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=f"🎁 <b>Вам выдана подписка!</b>\n\n"
                         f"Администратор выдал вам подписку на {days} дней.\n"
                         f"Доступ открыт до: {end_date.strftime('%d.%m.%Y')}\n\n"
                         f"Теперь вы можете использовать все функции бота!",
                    parse_mode="HTML"
                )
            except:
                pass
            
            await message.answer(
                f"✅ Подписка на {days} дней выдана пользователю {user_id}!\n"
                f"Подписка активна до: {end_date.strftime('%d.%m.%Y')}",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer("❌ Ошибка! Пользователь не найден.")
            
    except ValueError:
        await message.answer("❌ Неверное количество дней! Введите число.")
    
    await state.clear()

@dp.callback_query(F.data == "admin_find_user")
async def admin_find_user(callback: CallbackQuery):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Получаем последних пользователей
    cursor.execute('''
    SELECT user_id, username, subscription_end, requests_today, total_requests
    FROM users
    ORDER BY joined_date DESC
    LIMIT 10
    ''')
    recent_users = cursor.fetchall()
    conn.close()
    
    users_text = "👥 <b>Последние пользователи</b>\n\n"
    
    for user in recent_users:
        user_id, username, sub_end, req_today, total_req = user
        
        if sub_end:
            sub_end_date = datetime.strptime(sub_end, '%Y-%m-%d %H:%M:%S')
            if datetime.now() < sub_end_date:
                sub_status = f"✅ ({sub_end_date.strftime('%d.%m')})"
            else:
                sub_status = "❌"
        else:
            sub_status = "❌"
        
        users_text += (
            f"├ @{username}\n"
            f"│ ├ ID: {user_id}\n"
            f"│ ├ Подписка: {sub_status}\n"
            f"│ └ Запросы: {req_today}/50 | Всего: {total_req}\n"
        )
    
    users_text += "└ ..."
    
    try:
        await callback.message.edit_caption(
            caption=users_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    except:
        await callback.message.edit_text(
            text=users_text,
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
    
    await callback.answer()

# ========== ИНЛАЙН РЕЖИМ ==========
@dp.inline_query()
async def inline_handler(inline_query: types.InlineQuery):
    user_id = inline_query.from_user.id
    
    # Проверяем подписку
    if not check_subscription(user_id):
        # Показываем только кнопку для покупки подписки
        result = types.InlineQueryResultArticle(
            id='1',
            title="🚫 Нет доступа",
            description="Купите подписку для использования инлайн режима",
            input_message_content=types.InputTextMessageContent(
                message_text="🚫 Для использования инлайн режима нужна подписка!\n\n"
                           "Купите подписку в @MartSnoserBot"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Купить подписку", url=f"https://t.me/MartSnoserBot")]
            ])
        )
        await inline_query.answer([result], cache_time=300)
        return
    
    query = inline_query.query.strip().replace('@', '')
    
    if not query or len(query) < 3:
        # Показываем инструкцию
        result = types.InlineQueryResultArticle(
            id='1',
            title="📝 Инлайн режим MartSnoser",
            description="Введите юзернейм для сноса (например: username)",
            input_message_content=types.InputTextMessageContent(
                message_text="🔍 <b>Инлайн режим MartSnoser</b>\n\n"
                           "Для сноса аккаунта введите:\n"
                           "<code>@MartSnoserBot username</code>\n\n"
                           "<i>Пример: @MartSnoserBot evil_user</i>",
                parse_mode="HTML"
            )
        )
        await inline_query.answer([result], cache_time=300)
        return
    
    # Проверяем кд
    if not check_cooldown(user_id):
        cooldown_remaining = get_cooldown_remaining(user_id)
        minutes = cooldown_remaining // 60
        seconds = cooldown_remaining % 60
        
        result = types.InlineQueryResultArticle(
            id='1',
            title="⏳ Подождите",
            description=f"КД: {minutes}:{seconds:02d}",
            input_message_content=types.InputTextMessageContent(
                message_text=f"⏳ <b>Подождите перед запросом</b>\n\n"
                           f"КД между запросами: 10 минут\n"
                           f"Осталось: {minutes}:{seconds:02d}\n\n"
                           f"<i>Запрос: @{query}</i>",
                parse_mode="HTML"
            )
        )
        await inline_query.answer([result], cache_time=60)
        return
    
    # Проверяем дневной лимит
    check_daily_reset(user_id)
    user = get_user(user_id)
    
    if user and user[3] >= 50:
        result = types.InlineQueryResultArticle(
            id='1',
            title="🚫 Лимит исчерпан",
            description="50 запросов в день",
            input_message_content=types.InputTextMessageContent(
                message_text=f"🚫 <b>Лимит исчерпан!</b>\n\n"
                           f"Вы использовали 50/50 запросов на сегодня.\n"
                           f"Лимит обновится в 00:00 по МСК.\n\n"
                           f"<i>Запрос: @{query}</i>",
                parse_mode="HTML"
            )
        )
        await inline_query.answer([result], cache_time=300)
        return
    
    # Создаем инлайн результат
    result = types.InlineQueryResultArticle(
        id='1',
        title=f"Снос аккаунта: @{query}",
        description="Отправить запрос на снос",
        input_message_content=types.InputTextMessageContent(
            message_text=f"🚨 <b>Запрос на снос аккаунта</b>\n\n"
                        f"Цель: @{query}\n"
                        f"От: Пользователь\n"
                        f"Статус: ⏳ Обработка...\n\n"
                        f"<i>Отправлено через @MartSnoserBot</i>",
            parse_mode="HTML"
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить снос", callback_data=f"inline_confirm_{query}")],
            [InlineKeyboardButton(text="🚫 Отменить", callback_data="inline_cancel")]
        ])
    )
    
    await inline_query.answer([result], cache_time=1, is_personal=True)

@dp.callback_query(F.data.startswith("inline_confirm_"))
async def inline_confirm(callback: CallbackQuery):
    user_id = callback.from_user.id
    target_username = callback.data.replace("inline_confirm_", "")
    
    # Проверяем подписку
    if not check_subscription(user_id):
        await callback.answer("🚫 Нет подписки!", show_alert=True)
        return
    
    # Проверяем кд
    if not check_cooldown(user_id):
        await callback.answer("⏳ Подождите перед запросом!", show_alert=True)
        return
    
    # Проверяем лимит
    check_daily_reset(user_id)
    user = get_user(user_id)
    if user and user[3] >= 50:
        await callback.answer("🚫 Лимит исчерпан!", show_alert=True)
        return
    
    # Получаем информацию об аккаунте
    account_info = await get_telegram_account_info(target_username)
    
    if account_info:
        # Обновляем счетчик
        update_user_requests(user_id)
        
        # Сохраняем запрос
        request_id = add_snos_request(user_id, target_username, account_info)
        
        # Имитируем процесс
        success = await simulate_snos_process(target_username, account_info)
        
        if success:
            result_text = (
                f"✅ <b>Запрос через инлайн принят!</b>\n\n"
                f"Цель: @{target_username}\n"
                f"ID: <code>{request_id}</code>\n"
                f"Статус: Успешно отправлен\n\n"
                f"<i>Снос в процессе...</i>"
            )
            
            # Обновляем статус
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
            UPDATE snos_requests SET status = 'completed', completed_at = ?
            WHERE id = ?
            ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), request_id))
            conn.commit()
            conn.close()
        else:
            result_text = (
                f"⚠️ <b>Запрос принят с пометкой</b>\n\n"
                f"Цель: @{target_username}\n"
                f"ID: <code>{request_id}</code>\n"
                f"Статус: Требует проверки\n\n"
                f"<i>Наши операторы проверят аккаунт</i>"
            )
    else:
        result_text = (
            f"⚠️ <b>Аккаунт не найден</b>\n\n"
            f"Цель: @{target_username}\n"
            f"Статус: Не удалось получить информацию\n\n"
            f"<i>Запрос все равно отправлен на проверку</i>"
        )
        
        # Все равно сохраняем
        update_user_requests(user_id)
        add_snos_request(user_id, target_username, {"error": "not_found"})
    
    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            text=result_text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Открыть бота", url=f"https://t.me/MartSnoserBot")]
            ])
        )
    except:
        pass
    
    await callback.answer()

@dp.callback_query(F.data == "inline_cancel")
async def inline_cancel(callback: CallbackQuery):
    await callback.message.edit_text(
        text="❌ Запрос отменен пользователем.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Открыть бота", url=f"https://t.me/MartSnoserBot")]
        ])
    )
    await callback.answer()

# ========== ЕЖЕДНЕВНЫЙ СБРОС ЛИМИТОВ ==========
async def daily_reset_task():
    """Задача для сброса дневных лимитов"""
    while True:
        try:
            now = datetime.now()
            # Сбрасываем в 00:00 по МСК
            moscow_tz = pytz.timezone('Europe/Moscow')
            moscow_time = now.astimezone(moscow_tz)
            
            if moscow_time.hour == 0 and moscow_time.minute == 0:
                reset_daily_limits()
                logger.info("Дневные лимиты сброшены")
            
            # Ждем 1 минуту перед следующей проверкой
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"Ошибка в daily_reset_task: {e}")
            await asyncio.sleep(60)

# ========== ЗАПУСК БОТА ==========
async def main():
    # Инициализация БД
    init_db()
    
    # Запускаем задачу сброса лимитов
    asyncio.create_task(daily_reset_task())
    
    logger.info("🤖 MartSnoser бот запущен!")
    
    # Удаляем вебхук (если был)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запускаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())