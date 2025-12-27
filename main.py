import asyncio
import sqlite3
import logging
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram import F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import aiohttp
import json
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Конфигурация из .env
BOT_TOKEN = os.getenv('BOT_TOKEN')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 7037764178))
API_ID = int(os.getenv('API_ID', 30147101))
API_HASH = os.getenv('API_HASH')
REQUIRED_CHANNEL_ID = int(os.getenv('REQUIRED_CHANNEL_ID', -1003416494075))
REQUIRED_CHANNEL_USERNAME = os.getenv('REQUIRED_CHANNEL_USERNAME', 'newchannelmart')
DATABASE_NAME = 'mart_snoser.db'

# Проверка токена
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в .env файле!")
    exit(1)

if not CRYPTOBOT_TOKEN:
    logger.warning("⚠️ CRYPTOBOT_TOKEN не найден в .env файле!")

# Путь к баннеру
BANNER_PATH = "banner.jpg"

# Криптовалюта для оплаты
CRYPTO_ASSET = "USDT"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация Telethon (будет создана позже)
telethon_client = None

# Состояния FSM
class SnosStates(StatesGroup):
    waiting_for_username = State()
    confirm_request = State()
    waiting_payment = State()
    admin_add_subscription = State()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
    cursor = conn.cursor()
    
    # Удаляем старые таблицы если они есть
    cursor.execute('DROP TABLE IF EXISTS users')
    cursor.execute('DROP TABLE IF EXISTS requests')
    cursor.execute('DROP TABLE IF EXISTS payments')
    cursor.execute('DROP TABLE IF EXISTS inline_requests')
    
    # Создаем таблицы с правильной структурой
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            subscription_end DATETIME DEFAULT NULL,
            is_admin BOOLEAN DEFAULT 0,
            requests_count INTEGER DEFAULT 0,
            channel_subscribed BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            target_username TEXT,
            target_id INTEGER,
            target_dc INTEGER,
            target_info TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE inline_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            inline_message_id TEXT,
            target_username TEXT,
            target_id INTEGER,
            target_dc INTEGER,
            status TEXT DEFAULT 'pending',
            progress INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount_usd REAL,
            amount_crypto REAL,
            crypto_asset TEXT,
            days INTEGER,
            invoice_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            paid_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, full_name, is_admin) 
        VALUES (?, ?, ?, 1)
    ''', (ADMIN_ID, 'admin', 'Администратор'))
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована с новой структурой")

def get_db_connection():
    """Получение соединения с БД"""
    conn = sqlite3.connect(DATABASE_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def add_or_update_user(user_id: int, username: str = None, full_name: str = None):
    """Добавление или обновление пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO users (user_id, username, full_name)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = COALESCE(excluded.username, users.username),
            full_name = COALESCE(excluded.full_name, users.full_name)
    ''', (user_id, username, full_name))
    
    conn.commit()
    conn.close()

def get_user_subscription_status(user_id: int):
    """Получение статуса подписки пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT subscription_end, requests_count, channel_subscribed FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        has_active_sub = False
        if result['subscription_end']:
            try:
                end_date = datetime.fromisoformat(result['subscription_end'])
                has_active_sub = end_date > datetime.now()
            except:
                has_active_sub = False
        
        return {
            'has_subscription': has_active_sub,
            'end_date': result['subscription_end'],
            'requests_count': result['requests_count'],
            'channel_subscribed': bool(result['channel_subscribed'])
        }
    
    return {'has_subscription': False, 'end_date': None, 'requests_count': 0, 'channel_subscribed': False}

def update_user_subscription(user_id: int, days: int):
    """Обновление подписки пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    current_time = datetime.now()
    
    if result and result['subscription_end']:
        try:
            current_end = datetime.fromisoformat(result['subscription_end'])
            if current_end > current_time:
                new_end = current_end + timedelta(days=days)
            else:
                new_end = current_time + timedelta(days=days)
        except:
            new_end = current_time + timedelta(days=days)
    else:
        new_end = current_time + timedelta(days=days)
    
    cursor.execute('UPDATE users SET subscription_end = ? WHERE user_id = ?', (new_end.isoformat(), user_id))
    conn.commit()
    conn.close()
    
    return new_end

def mark_channel_subscribed(user_id: int):
    """Отметка что пользователь подписан на канал"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET channel_subscribed = 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def add_request(user_id: int, target_username: str, target_id: int, target_dc: int, target_info: str):
    """Добавление запроса на снос"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO requests (user_id, target_username, target_id, target_dc, target_info) 
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, target_username, target_id, target_dc, target_info))
    
    cursor.execute('UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?', (user_id,))
    
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return request_id

def add_inline_request(user_id: int, inline_message_id: str, target_username: str, target_id: int, target_dc: int):
    """Добавление inline запроса"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO inline_requests (user_id, inline_message_id, target_username, target_id, target_dc, status, progress)
        VALUES (?, ?, ?, ?, ?, 'pending', 0)
    ''', (user_id, inline_message_id, target_username, target_id, target_dc))
    
    cursor.execute('UPDATE users SET requests_count = requests_count + 1 WHERE user_id = ?', (user_id,))
    
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return request_id

def update_inline_request_progress(inline_message_id: str, progress: int, status: str = None):
    """Обновление прогресса inline запроса"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if status:
        cursor.execute('''
            UPDATE inline_requests 
            SET progress = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE inline_message_id = ?
        ''', (progress, status, inline_message_id))
    else:
        cursor.execute('''
            UPDATE inline_requests 
            SET progress = ?, updated_at = CURRENT_TIMESTAMP
            WHERE inline_message_id = ?
        ''', (progress, inline_message_id))
    
    conn.commit()
    conn.close()

# ========== ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ==========
async def check_channel_subscription(user_id: int):
    """Проверка подписки пользователя на канал"""
    try:
        # Проверяем статус подписки
        chat_member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        
        # Статусы которые считаются подпиской
        valid_statuses = ['member', 'administrator', 'creator']
        is_subscribed = chat_member.status in valid_statuses
        
        if is_subscribed:
            # Обновляем статус в БД
            mark_channel_subscribed(user_id)
        
        return is_subscribed
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки подписки на канал: {e}")
        return False

# ========== TELEGRAM АККАУНТ ПРОВЕРКА ==========
async def init_telethon():
    """Инициализация Telethon клиента"""
    global telethon_client
    
    if telethon_client is None:
        try:
            from telethon import TelegramClient
            telethon_client = TelegramClient('mart_snoser_session', API_ID, API_HASH)
            await telethon_client.connect()
            
            if not await telethon_client.is_user_authorized():
                logger.warning("⚠️ Telethon клиент не авторизован")
                logger.info("📱 Запустите setup_telethon.py для авторизации")
                return False
            
            logger.info("✅ Telethon клиент инициализирован")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации Telethon: {e}")
            return False
    else:
        try:
            return await telethon_client.is_user_authorized()
        except:
            return False

async def get_account_info_telethon(username: str):
    """Получение информации об аккаунте через Telethon"""
    global telethon_client
    
    # Инициализируем клиент если нужно
    if telethon_client is None:
        if not await init_telethon():
            logger.error("❌ Telethon не инициализирован")
            return None
    
    try:
        # Проверяем подключение
        if not telethon_client.is_connected():
            await telethon_client.connect()
        
        # Получаем сущность
        try:
            entity = await telethon_client.get_entity(username)
        except ValueError:
            # Пробуем через поиск
            try:
                result = await telethon_client.get_participants(username, limit=1)
                if result:
                    entity = result[0]
                else:
                    logger.warning(f"⚠️ Аккаунт @{username} не найден")
                    return None
            except Exception as e:
                logger.error(f"❌ Ошибка поиска аккаунта @{username}: {e}")
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения entity @{username}: {e}")
            return None
        
        # Проверяем что это пользователь
        from telethon.tl.types import User
        if isinstance(entity, User):
            account_id = entity.id
            dc_id = entity.photo.dc_id if entity.photo else 0
            first_name = entity.first_name or ""
            last_name = entity.last_name or ""
            username_display = entity.username or username
            is_bot = entity.bot
            
            logger.info(f"✅ Найден аккаунт @{username}: ID={account_id}, DC={dc_id}")
            
            return {
                'id': account_id,
                'dc_id': dc_id,
                'username': username_display,
                'first_name': first_name,
                'last_name': last_name,
                'is_bot': is_bot
            }
        else:
            logger.warning(f"⚠️ Объект @{username} не является пользователем: {type(entity)}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка Telethon для @{username}: {e}")
        return None

# ========== КРИПТОБОТ ==========
async def create_crypto_invoice(user_id: int, amount_usd: float, days: int):
    """Создание инвойса в CryptoBot"""
    if not CRYPTOBOT_TOKEN:
        logger.error("❌ CRYPTOBOT_TOKEN не настроен")
        return None
    
    # Пробуем разные активы
    assets_to_try = ["USDT", "TON", "BTC", "ETH"]
    
    for asset in assets_to_try:
        # Конвертируем USD в крипту (примерные курсы)
        rates = {
            "USDT": amount_usd,
            "TON": amount_usd * 0.12,  # 1 TON ≈ 8.5 USD
            "BTC": amount_usd / 70000,
            "ETH": amount_usd / 3500
        }
        
        amount_crypto = rates.get(asset, amount_usd)
        
        url = "https://pay.crypt.bot/api/createInvoice"
        
        headers = {
            "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN,
            "Content-Type": "application/json"
        }
        
        data = {
            "asset": asset,
            "amount": str(amount_crypto),
            "description": f"Подписка MartSnoser на {days} дней",
            "hidden_message": f"User ID: {user_id} | Days: {days}",
            "payload": json.dumps({"user_id": user_id, "days": days})
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    result = await response.json()
                    
                    if result.get('ok'):
                        invoice_data = result['result']
                        
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute('''
                            INSERT INTO payments (user_id, amount_usd, amount_crypto, crypto_asset, days, invoice_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (user_id, amount_usd, amount_crypto, asset, days, invoice_data['invoice_id']))
                        conn.commit()
                        conn.close()
                        
                        return {
                            'invoice_id': str(invoice_data['invoice_id']),  # Гарантируем строку
                            'pay_url': invoice_data['pay_url'],
                            'asset': asset,
                            'amount': amount_crypto
                        }
                    else:
                        error = result.get('error', {})
                        logger.debug(f"❌ Asset {asset} error: {error.get('name', 'Unknown')}")
                        continue
                        
        except Exception as e:
            logger.error(f"❌ Error creating invoice with {asset}: {e}")
            continue
    
    logger.error("❌ Все активы не поддерживаются")
    return None

async def check_crypto_payment(invoice_id: str):
    """Проверка статуса платежа"""
    if not CRYPTOBOT_TOKEN:
        return False
    
    url = "https://pay.crypt.bot/api/getInvoices"
    
    headers = {
        "Crypto-Pay-API-Token": CRYPTOBOT_TOKEN
    }
    
    params = {
        "invoice_ids": invoice_id
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                result = await response.json()
                
                if result.get('ok') and result['result']['items']:
                    invoice = result['result']['items'][0]
                    if invoice.get('status') == 'paid':
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute('''
                            UPDATE payments 
                            SET status = 'paid', paid_at = CURRENT_TIMESTAMP 
                            WHERE invoice_id = ? AND status = 'pending'
                        ''', (invoice_id,))
                        conn.commit()
                        conn.close()
                        return True
                    
    except Exception as e:
        logger.error(f"❌ Error checking payment: {e}")
    
    return False

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="💰 Прайсич", callback_data="pricing")
    )
    keyboard.row(
        InlineKeyboardButton(text="📤 Отправка запросов", callback_data="send_request")
    )
    return keyboard.as_markup()

def get_pricing_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="🎫 3 дня - 1$", callback_data="buy_3_days"),
        InlineKeyboardButton(text="⚡ 7 дней - 5$", callback_data="buy_7_days")
    )
    keyboard.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu")
    )
    return keyboard.as_markup()

def get_back_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu")
    )
    return keyboard.as_markup()

def get_admin_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="🎫 Выдать подписку", callback_data="admin_add_sub")
    )
    keyboard.row(
        InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu")
    )
    return keyboard.as_markup()

def get_confirm_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm_yes"),
        InlineKeyboardButton(text="❌ Нет, отменить", callback_data="confirm_no")
    )
    return keyboard.as_markup()

def get_payment_keyboard(invoice_id: str, pay_url: str, crypto_asset: str = "USDT"):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="💳 Оплатить", url=pay_url)
    )
    keyboard.row(
        InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data=f"check_{invoice_id}")
    )
    keyboard.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="pricing")
    )
    return keyboard.as_markup()

def get_channel_subscription_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL_USERNAME}")
    )
    keyboard.row(
        InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")
    )
    return keyboard.as_markup()

def get_inline_keyboard_for_request(request_id: str):
    keyboard = InlineKeyboardBuilder()
    keyboard.row(
        InlineKeyboardButton(text="🔄 Обновить статус", callback_data=f"refresh_{request_id}"),
        InlineKeyboardButton(text="📊 Подробнее", url=f"https://t.me/{bot.me.username}")
    )
    return keyboard.as_markup()

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    
    add_or_update_user(user_id, username, full_name)
    
    # Проверяем подписку на канал
    sub_info = get_user_subscription_status(user_id)
    
    if not sub_info['channel_subscribed']:
        # Проверяем в реальном времени
        is_subscribed = await check_channel_subscription(user_id)
        
        if not is_subscribed:
            welcome_text = f"""
❝Добро пожаловать в MartSnoser!❞

⚠️ Для использования бота необходимо подписаться на наш канал:
📢 @{REQUIRED_CHANNEL_USERNAME}

После подписки нажмите "✅ Я подписался"
"""
            
            await message.answer(
                welcome_text,
                reply_markup=get_channel_subscription_keyboard()
            )
            return
    
    welcome_text = '❝Добро пожаловать в MartSnoser. Выбери действие:❞'
    
    try:
        if os.path.exists(BANNER_PATH):
            photo = FSInputFile(BANNER_PATH)
            await message.answer_photo(
                photo=photo,
                caption=welcome_text,
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                welcome_text,
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error sending welcome message: {e}")
        await message.answer(
            welcome_text,
            reply_markup=get_main_keyboard()
        )

@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    # Проверяем подписку
    is_subscribed = await check_channel_subscription(user_id)
    
    if is_subscribed:
        await callback.answer("✅ Отлично! Вы подписаны на канал", show_alert=True)
        
        welcome_text = '❝Добро пожаловать в MartSnoser. Выбери действие:❞'
        
        try:
            if callback.message.photo:
                if os.path.exists(BANNER_PATH):
                    photo = FSInputFile(BANNER_PATH)
                    await callback.message.edit_media(
                        media=types.InputMediaPhoto(
                            media=photo,
                            caption=welcome_text
                        ),
                        reply_markup=get_main_keyboard()
                    )
                else:
                    await callback.message.edit_caption(
                        caption=welcome_text,
                        reply_markup=get_main_keyboard()
                    )
            else:
                await callback.message.edit_text(
                    text=welcome_text,
                    reply_markup=get_main_keyboard()
                )
        except Exception as e:
            logger.error(f"❌ Error updating menu: {e}")
            await callback.message.answer(
                welcome_text,
                reply_markup=get_main_keyboard()
            )
    else:
        await callback.answer("❌ Вы еще не подписались на канал", show_alert=True)

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer(
            "👑 Панель администратора:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer("❌ Доступ запрещен")

# ========== ОБРАБОТЧИКИ КНОПОК ==========
@dp.callback_query(F.data == "menu")
async def process_menu(callback: types.CallbackQuery):
    welcome_text = '❝Добро пожаловать в MartSnoser. Выбери действие:❞'
    
    try:
        if callback.message.photo:
            if os.path.exists(BANNER_PATH):
                photo = FSInputFile(BANNER_PATH)
                await callback.message.edit_media(
                    media=types.InputMediaPhoto(
                        media=photo,
                        caption=welcome_text
                    ),
                    reply_markup=get_main_keyboard()
                )
            else:
                await callback.message.edit_caption(
                    caption=welcome_text,
                    reply_markup=get_main_keyboard()
                )
        else:
            await callback.message.edit_text(
                text=welcome_text,
                reply_markup=get_main_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in menu: {e}")
        await callback.answer("❌ Ошибка обновления меню", show_alert=True)

@dp.callback_query(F.data == "profile")
async def process_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    sub_info = get_user_subscription_status(user_id)
    
    status = "✅ Активна" if sub_info['has_subscription'] else "❌ Неактивна"
    channel_status = "✅ Подписан" if sub_info['channel_subscribed'] else "❌ Не подписан"
    
    if sub_info['end_date']:
        try:
            end_date = datetime.fromisoformat(sub_info['end_date']).strftime('%d.%m.%Y %H:%M')
        except:
            end_date = "Ошибка даты"
    else:
        end_date = "Нет подписки"
    
    text = f"""
👤 Ваш профиль:

🆔 ID: {user_id}
📛 Имя: {callback.from_user.full_name}
📊 Статус подписки: {status}
📅 Подписка до: {end_date}
📊 Запросов отправлено: {sub_info['requests_count']}
"""
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=get_back_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=get_back_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in profile: {e}")
        await callback.answer("❌ Ошибка обновления профиля", show_alert=True)

@dp.callback_query(F.data == "pricing")
async def process_pricing(callback: types.CallbackQuery):
    text = """
💰 Прайсич:

🎫 3 дня - 1$ (криптовалюта)
⚡ 7 дней - 5$ (криптовалюта)

💡 Оплата в криптовалюте (USDT, TON, BTC и др.)
✅ После оплаты нажмите "Я оплатил(а)"
✅ Автоматическая проверка оплаты
"""
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=get_pricing_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=get_pricing_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in pricing: {e}")
        await callback.answer("❌ Ошибка обновления прайсинга", show_alert=True)

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    if callback.data == "buy_3_days":
        amount_usd = 1.0
        days = 3
    else:
        amount_usd = 5.0
        days = 7
    
    invoice_data = await create_crypto_invoice(user_id, amount_usd, days)
    
    if invoice_data:
        crypto_asset = invoice_data.get('asset', 'CRYPTO')
        amount_crypto = invoice_data.get('amount', amount_usd)
        invoice_id = str(invoice_data.get('invoice_id', 'unknown'))
        pay_url = invoice_data.get('pay_url', '#')
        
        keyboard = get_payment_keyboard(invoice_id, pay_url, crypto_asset)
        
        # Безопасное обрезание ID инвойса
        invoice_id_short = invoice_id[:8] if len(invoice_id) > 8 else invoice_id
        
        text = f"""
💳 Инвойс создан!

🎫 Подписка: {days} дней
💰 Сумма: {amount_crypto} {crypto_asset} (~{amount_usd}$)
📝 ID инвойса: {invoice_id_short}...
🌐 Валюта: {crypto_asset}

✅ Оплатите по ссылке ниже
✅ После оплаты нажмите "✅ Я оплатил(а)"
"""
        
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption=text,
                    reply_markup=keyboard
                )
            else:
                await callback.message.edit_text(
                    text=text,
                    reply_markup=keyboard
                )
        except Exception as e:
            logger.error(f"❌ Error in buy: {e}")
            await callback.answer("❌ Ошибка создания инвойса", show_alert=True)
    else:
        await callback.answer("❌ Ошибка создания инвойса. Проверьте настройки CryptoBot.", show_alert=True)

@dp.callback_query(F.data.startswith("check_"))
async def check_payment(callback: types.CallbackQuery):
    invoice_id = callback.data.replace("check_", "")
    
    await callback.answer("🔄 Проверяем оплату...", show_alert=False)
    
    is_paid = await check_crypto_payment(invoice_id)
    
    if is_paid:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, days, amount_usd, crypto_asset FROM payments WHERE invoice_id = ?', (invoice_id,))
        payment = cursor.fetchone()
        
        if payment:
            user_id = payment['user_id']
            days = payment['days']
            amount_usd = payment['amount_usd']
            crypto_asset = payment['crypto_asset']
            
            new_end = update_user_subscription(user_id, days)
            
            conn.close()
            
            end_date = datetime.fromisoformat(new_end.isoformat()).strftime('%d.%m.%Y %H:%M')
            
            text = f"""
✅ Оплата подтверждена!

🎉 Подписка активирована на {days} дней
📅 Доступ до: {end_date}
💰 Сумма: {amount_usd}$ ({crypto_asset})

Теперь вы можете использовать все функции бота!
"""
            
            try:
                if callback.message.photo:
                    await callback.message.edit_caption(
                        caption=text,
                        reply_markup=get_back_keyboard()
                    )
                else:
                    await callback.message.edit_text(
                        text=text,
                        reply_markup=get_back_keyboard()
                    )
            except Exception as e:
                logger.error(f"❌ Error in check payment: {e}")
            
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"💰 Новый платеж!\n\n"
                    f"👤 Пользователь: {callback.from_user.full_name}\n"
                    f"🆔 ID: {user_id}\n"
                    f"🎫 Дней: {days}\n"
                    f"💰 Сумма: {amount_usd}$ ({crypto_asset})"
                )
            except:
                pass
        else:
            await callback.answer("Платеж не найден в базе данных", show_alert=True)
    else:
        await callback.answer("❌ Оплата еще не поступила. Попробуйте позже.", show_alert=True)

@dp.callback_query(F.data == "send_request")
async def process_send_request(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    sub_info = get_user_subscription_status(user_id)
    
    # Проверяем подписку на канал
    if not sub_info['channel_subscribed']:
        is_subscribed = await check_channel_subscription(user_id)
        if not is_subscribed:
            await callback.message.answer(
                f"⚠️ подписку оформи:\n"
                f"📢 @{REQUIRED_CHANNEL_USERNAME}\n\n"
                f"После подписки нажмите кнопку ниже:",
                reply_markup=get_channel_subscription_keyboard()
            )
            return
    
    # Проверяем подписку на бота
    if not sub_info['has_subscription']:
        keyboard = InlineKeyboardBuilder()
        keyboard.row(
            InlineKeyboardButton(text="💰 Купить подписку", callback_data="pricing"),
            InlineKeyboardButton(text="◀️ Назад", callback_data="menu")
        )
        
        try:
            if callback.message.photo:
                await callback.message.edit_caption(
                    caption="❌ У вас нет активной подписки!\n\nПриобретите подписку для использования этой функции.",
                    reply_markup=keyboard.as_markup()
                )
            else:
                await callback.message.edit_text(
                    text="❌ У вас нет активной подписки!\n\nПриобретите подписку для использования этой функции.",
                    reply_markup=keyboard.as_markup()
                )
        except Exception as e:
            logger.error(f"❌ Error in send request: {e}")
            await callback.answer("❌ Ошибка", show_alert=True)
        return
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption="📤 Введите юзернейм жертвы (например: @username или просто username):",
                reply_markup=get_back_keyboard()
            )
        else:
            await callback.message.edit_text(
                text="📤 Введите юзернейм жертвы (например: @username или просто username):",
                reply_markup=get_back_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in send request 2: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)
    
    await state.set_state(SnosStates.waiting_for_username)

@dp.message(SnosStates.waiting_for_username)
async def process_username(message: types.Message, state: FSMContext):
    username = message.text.replace('@', '').strip()
    
    if not username:
        await message.answer("❌ Введите юзернейм:")
        return
    
    # Показываем ожидание
    wait_msg = await message.answer("🔍 Проверяю аккаунт через Telethon...")
    
    # Получаем информацию об аккаунте через Telethon
    account_info = await get_account_info_telethon(username)
    
    if account_info:
        account_id = account_info['id']
        dc_id = account_info.get('dc_id', 'Неизвестно')
        username_display = account_info.get('username', username)
        first_name = account_info.get('first_name', '')
        last_name = account_info.get('last_name', '')
        
        # Форматируем DC для отображения
        dc_display = f"DC{dc_id}" if dc_id and dc_id != 0 else "Неизвестно"
        
        target_info = f"""
📋 Информация об аккаунте:

👤 Юзернейм: @{username_display}
🆔 ID: {account_id}
📛 Имя: {first_name} {last_name}
🌐 Датацентр: {dc_display}

"""
        
        await wait_msg.delete()
        
        await state.update_data(
            target_username=username,
            target_id=account_id,
            target_dc=dc_display,
            target_info=target_info
        )
        
        await message.answer(
            f"{target_info}\n\n"
            f"❓ Вы точно хотите отправить запросы для сноса этого аккаунта?",
            reply_markup=get_confirm_keyboard()
        )
    else:
        await wait_msg.delete()
        await message.answer(
            f"❌ Не удалось проверить аккаунт @{username}\n"
            f"Возможные причины:\n"
            f"• Аккаунт не существует\n"
            f"• Аккаунт приватный\n"
            f"• Ошибка подключения Telethon\n\n"
            f"Попробуйте другой юзернейм:",
            reply_markup=get_back_keyboard()
        )

@dp.callback_query(F.data == "confirm_yes")
async def confirm_request(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    username = data.get('target_username')
    target_id = data.get('target_id')
    target_dc = data.get('target_dc')
    target_info = data.get('target_info')
    
    if not username or not target_id:
        await callback.answer("❌ Ошибка: данные не найдены", show_alert=True)
        return
    
    # Извлекаем номер DC из строки "DC4" -> 4
    target_dc_int = 0
    if target_dc and target_dc.startswith('DC'):
        try:
            target_dc_int = int(target_dc[2:])
        except:
            target_dc_int = 0
    
    request_id = add_request(callback.from_user.id, username, target_id, target_dc_int, target_info)
    
    progress_msg = await callback.message.answer("🔄 Отправка запросов...\n\n[░░░░░░░░░░] 0%")
    
    steps = [
        ("📡 Отправка запросов с сессий session 4044...", 1),
        ("🔍 Отправка запросов с сессий session 4046 ...", 1),
        ("📊 Отправка запросов с сессий session 4073...", 1),
        ("🚫 Отправка запросов с сессий session 3121...", 1),
        ("📤 Отправка запросов администрации...", 1)
    ]
    
    for i, (step_text, delay) in enumerate(steps):
        await asyncio.sleep(delay)
        progress = i + 1
        bars = int((progress / len(steps)) * 10)
        percentage = int((progress / len(steps)) * 100)
        progress_bar = "█" * bars + "░" * (10 - bars)
        
        await progress_msg.edit_text(f"🔄 {step_text}\n\n[{progress_bar}] {percentage}%")
    
    await progress_msg.delete()
    
    text = f"""
✅ Запросы успешно отправлены для @{username}!

📝 ID запроса: #{request_id}
🆔 ID жертвы: {target_id}
🌐 Датацентр: {target_dc}
⏱️ Время: {datetime.now().strftime('%H:%M:%S')}

ща ебнет.
"""
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=get_back_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=get_back_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in confirm request: {e}")
    
    await state.clear()

@dp.callback_query(F.data == "confirm_no")
async def cancel_request(callback: types.CallbackQuery, state: FSMContext):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption="❌ Запрос отменен.",
                reply_markup=get_back_keyboard()
            )
        else:
            await callback.message.edit_text(
                text="❌ Запрос отменен.",
                reply_markup=get_back_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in cancel request: {e}")
    
    await state.clear()

# ========== INLINE РЕЖИМ ==========
@dp.inline_query()
async def inline_mode(inline_query: types.InlineQuery):
    user_id = inline_query.from_user.id
    
    # Проверяем подписку на канал
    sub_info = get_user_subscription_status(user_id)
    
    if not sub_info['channel_subscribed']:
        is_subscribed = await check_channel_subscription(user_id)
        if not is_subscribed:
            result = types.InlineQueryResultArticle(
                id='channel_subscribe',
                title="MartSnoser - Снос аккаунтов",
                description="❌ Подпишитесь на канал для использования",
                input_message_content=types.InputTextMessageContent(
                    message_text=f"⚠️ Для использования MartSnoser необходимо подписаться на канал:\n\n"
                                f"📢 @{REQUIRED_CHANNEL_USERNAME}\n\n"
                                f"После подписки попробуйте снова."
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{REQUIRED_CHANNEL_USERNAME}")
                ]])
            )
            await inline_query.answer([result], cache_time=1)
            return
    
    # Проверяем подписку на бота
    if not sub_info['has_subscription']:
        result = types.InlineQueryResultArticle(
            id='no_sub',
            title="MartSnoser - Снос аккаунтов",
            description="❌ Нет активной подписки",
            input_message_content=types.InputTextMessageContent(
                message_text="❌ У вас нет активной подписки для использования inline режима.\n\n"
                            "Приобретите подписку в @mart_snoser_bot"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💰 Купить подписку", url=f"https://t.me/{bot.me.username}")
            ]])
        )
        await inline_query.answer([result], cache_time=1)
        return
    
    query = inline_query.query.strip()
    if not query:
        result = types.InlineQueryResultArticle(
            id='help',
            title="MartSnoser - Снос аккаунтов",
            description="Введите юзернейм для проверки",
            input_message_content=types.InputTextMessageContent(
                message_text="📋 Введите юзернейм после @mart_snoser_bot\n\n"
                            "Пример: @mart_snoser_bot username"
            )
        )
        await inline_query.answer([result], cache_time=1)
        return
    
    # Получаем информацию об аккаунте
    account_info = await get_account_info_telethon(query)
    
    if account_info:
        account_id = account_info['id']
        dc_id = account_info.get('dc_id', 0)
        username_display = account_info.get('username', query)
        
        # Создаем inline запрос в БД
        request_id = add_inline_request(user_id, inline_query.id, username_display, account_id, dc_id)
        
        result = types.InlineQueryResultArticle(
            id=query,
            title=f"Снос аккаунта @{username_display}",
            description="Нажмите чтобы отправить запрос на снос",
            input_message_content=types.InputTextMessageContent(
                message_text=f"🚀 Начат процесс сноса аккаунта @{username_display}\n\n"
                            f"🆔 ID жертвы: {account_id}\n"
                            f"🌐 Датацентр: DC{dc_id if dc_id else 'Неизвестно'}\n"
                            f"📝 ID запроса: #{request_id}\n"
                            f"⏱️ Статус: 🟡 Ожидание запуска..."
            ),
            reply_markup=get_inline_keyboard_for_request(str(request_id))
        )
        
        # Запускаем процесс сноса в фоне
        asyncio.create_task(process_inline_request(inline_query.id, request_id, username_display, account_id))
        
    else:
        result = types.InlineQueryResultArticle(
            id='error',
            title="MartSnoser - Ошибка",
            description=f"Аккаунт @{query} не найден",
            input_message_content=types.InputTextMessageContent(
                message_text=f"❌ Аккаунт @{query} не найден или недоступен.\n\n"
                            f"Проверьте правильность юзернейма и попробуйте снова."
            )
        )
    
    await inline_query.answer([result], cache_time=1)

async def process_inline_request(inline_message_id: str, request_id: int, username: str, target_id: int):
    """Обработка inline запроса в фоне"""
    steps = [ 
("📡 Отправка запросов с сессий session 4044...", 1),
        ("🔍 Отправка запросов с сессий session 4046 ...", 1),
        ("📊 Отправка запросов с сессий session 4073...", 1),
        ("🚫 Отправка запросов с сессий session 3121...", 1),
        ("📤 Отправка запросов администрации...", 1)
    ]
    
    for i, (step_text, delay) in enumerate(steps):
        await asyncio.sleep(delay)
        progress = int(((i + 1) / len(steps)) * 100)
        
        # Обновляем прогресс в БД
        update_inline_request_progress(inline_message_id, progress)
        
        # Создаем прогресс бар
        bars = int(progress / 10)
        progress_bar = "█" * bars + "░" * (10 - bars)
        
        # Формируем обновленное сообщение
        message_text = f"""
🚀 Процесс сноса аккаунта @{username}

🆔 ID жертвы: {target_id}
📝 ID запроса: #{request_id}
⏱️ Статус: {step_text}

[{progress_bar}] {progress}%
"""
        
        # Отправляем обновление через answerInlineQuery
        try:
            await bot.answer_inline_query(
                inline_query_id=inline_message_id,
                results=[
                    types.InlineQueryResultArticle(
                        id=username,
                        title=f"Снос аккаунта @{username}",
                        description=f"Прогресс: {progress}%",
                        input_message_content=types.InputTextMessageContent(
                            message_text=message_text
                        ),
                        reply_markup=get_inline_keyboard_for_request(str(request_id))
                    )
                ],
                cache_time=1
            )
        except Exception as e:
            logger.error(f"❌ Error updating inline query: {e}")
    
    # Финальное обновление
    final_message = f"""
✅ Процесс сноса аккаунта @{username} завершен!

🆔 ID жертвы: {target_id}
📝 ID запроса: #{request_id}
⏱️ Время завершения: {datetime.now().strftime('%H:%M:%S')}
📅 Дата: {datetime.now().strftime('%d.%m.%Y')}

ща ебнет.
"""
    
    update_inline_request_progress(inline_message_id, 100, "completed")
    
    try:
        await bot.answer_inline_query(
            inline_query_id=inline_message_id,
            results=[
                types.InlineQueryResultArticle(
                    id=username,
                    title=f"✅ Снос @{username} завершен",
                    description="Запрос успешно отправлен",
                    input_message_content=types.InputTextMessageContent(
                        message_text=final_message
                    ),
                    reply_markup=get_inline_keyboard_for_request(str(request_id))
                )
            ],
            cache_time=1
        )
    except Exception as e:
        logger.error(f"❌ Error sending final inline update: {e}")

@dp.callback_query(F.data.startswith("refresh_"))
async def refresh_inline_status(callback: types.CallbackQuery):
    request_id = callback.data.replace("refresh_", "")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT progress, status FROM inline_requests WHERE id = ?', (request_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        progress = result['progress']
        status = result['status']
        
        bars = int(progress / 10)
        progress_bar = "█" * bars + "░" * (10 - bars)
        
        status_text = {
            'pending': '🟡 Ожидание запуска',
            'processing': '🟠 В процессе',
            'completed': '✅ Завершен'
        }.get(status, '❓ Неизвестно')
        
        await callback.answer(f"Статус: {status_text}\nПрогресс: {progress}%", show_alert=True)
    else:
        await callback.answer("Запрос не найден", show_alert=True)

# ========== АДМИН ПАНЕЛЬ ==========
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as total FROM users')
    total_users = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(*) as active FROM users WHERE subscription_end > datetime("now")')
    active_subs = cursor.fetchone()['active']
    
    cursor.execute('SELECT COUNT(*) as total FROM requests')
    total_requests = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(*) as inline_requests FROM inline_requests')
    inline_requests = cursor.fetchone()['inline_requests']
    
    cursor.execute('SELECT SUM(amount_usd) as revenue FROM payments WHERE status = "paid"')
    total_revenue = cursor.fetchone()['revenue'] or 0
    
    cursor.execute('SELECT COUNT(*) as channel_subscribers FROM users WHERE channel_subscribed = 1')
    channel_subscribers = cursor.fetchone()['channel_subscribers']
    
    conn.close()
    
    text = f"""
📊 Статистика MartSnoser:

👥 Всего пользователей: {total_users}
🎫 Активных подписок: {active_subs}
📢 Подписчиков канала: {channel_subscribers}
📤 Обычных запросов: {total_requests}
🔗 Inline запросов: {inline_requests}
💰 Общая выручка: ${total_revenue:.2f} USD
"""
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption=text,
                reply_markup=get_admin_keyboard()
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=get_admin_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in admin stats: {e}")
        await callback.answer("❌ Ошибка получения статистики", show_alert=True)

@dp.callback_query(F.data == "admin_add_sub")
async def admin_add_subscription(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption="👑 Выдача подписки\n\nВведите:\nID_пользователя количество_дней\n\nПример: 123456789 7",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Отмена", callback_data="admin_cancel")
                    .as_markup()
            )
        else:
            await callback.message.edit_text(
                text="👑 Выдача подписки\n\nВведите:\nID_пользователя количество_дней\n\nПример: 123456789 7",
                reply_markup=InlineKeyboardBuilder()
                    .button(text="◀️ Отмена", callback_data="admin_cancel")
                    .as_markup()
            )
    except Exception as e:
        logger.error(f"❌ Error in admin add sub: {e}")
    
    await state.set_state(SnosStates.admin_add_subscription)

@dp.message(SnosStates.admin_add_subscription)
async def process_add_subscription(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError
        
        user_id = int(parts[0])
        days = int(parts[1])
        
        if days <= 0:
            await message.answer("❌ Количество дней должно быть больше 0")
            return
        
        new_end = update_user_subscription(user_id, days)
        add_or_update_user(user_id)
        
        await message.answer(
            f"✅ Подписка выдана!\n\n"
            f"👤 Пользователь: {user_id}\n"
            f"📅 Дней: {days}\n"
            f"📆 До: {new_end.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=get_admin_keyboard()
        )
        
        try:
            await bot.send_message(
                user_id,
                f"🎉 Администратор выдал вам подписку на {days} дней!\n\n"
                f"📅 Доступ до: {new_end.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Спасибо за использование MartSnoser!"
            )
        except:
            pass
            
    except ValueError:
        await message.answer("❌ Неверный формат. Пример: 123456789 7")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")
    
    await state.clear()

@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: types.CallbackQuery, state: FSMContext):
    try:
        if callback.message.photo:
            await callback.message.edit_caption(
                caption="👑 Панель администратора:",
                reply_markup=get_admin_keyboard()
            )
        else:
            await callback.message.edit_text(
                text="👑 Панель администратора:",
                reply_markup=get_admin_keyboard()
            )
    except Exception as e:
        logger.error(f"❌ Error in admin cancel: {e}")
    
    await state.clear()

# ========== ЗАПУСК БОТА ==========
async def main():
    init_db()
    
    # Получаем информацию о боте для логов
    try:
        bot_info = await bot.get_me()
        logger.info("=" * 50)
        logger.info(f"🚀 MartSnoser Bot запускается...")
        logger.info(f"🤖 Bot: @{bot_info.username}")
        logger.info(f"🆔 Bot ID: {bot_info.id}")
        logger.info(f"👑 Admin ID: {ADMIN_ID}")
        logger.info(f"📢 Обязательный канал: @{REQUIRED_CHANNEL_USERNAME}")
        logger.info(f"📁 Database: {DATABASE_NAME}")
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации о боте: {e}")
        logger.info(f"🚀 MartSnoser Bot запускается...")
    
    if os.path.exists(BANNER_PATH):
        logger.info(f"✅ Баннер найден: {BANNER_PATH}")
    else:
        logger.warning(f"⚠️ Баннер не найден: {BANNER_PATH}")
    
    # Инициализируем Telethon
    telethon_init = await init_telethon()
    if telethon_init:
        logger.info("✅ Telethon инициализирован")
    else:
        logger.warning("⚠️ Telethon не инициализирован, проверка аккаунтов не будет работать")
    
    logger.info("=" * 50)
    
    try:
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        # Закрываем Telethon клиент при выходе
        global telethon_client
        if telethon_client and telethon_client.is_connected():
            await telethon_client.disconnect()
            logger.info("✅ Telethon клиент отключен")
        
        logger.info("👋 Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())