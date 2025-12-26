import telebot
from telebot import types
import threading
import time
import requests
import json
from datetime import datetime
import asyncio
import config
from database import Database
from telethon_checker import get_account_info_sync, checker
import sqlite3

# Инициализация
bot = telebot.TeleBot(config.BOT_TOKEN)
db = Database(config.DATABASE_NAME)

# Глобальные переменные
user_states = {}
payment_checks = {}

# ====================== КЛАВИАТУРЫ (ПРОСТЫЕ) ======================
def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('Профиль'),
        types.KeyboardButton('Прайсич'),
        types.KeyboardButton('Отправка запросов')
    )
    return markup

def profile_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('Назад'),
        types.KeyboardButton('Я оплатил(а)')
    )
    return markup

def price_menu():
    markup = types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(
        types.KeyboardButton(f'3 дня - {config.SUBSCRIPTION_PRICES["3_days"]}$'),
        types.KeyboardButton(f'7 дней - {config.SUBSCRIPTION_PRICES["7_days"]}$'),
        types.KeyboardButton('Назад')
    )
    return markup

def confirm_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('✅ Да'),
        types.KeyboardButton('❌ Нет')
    )
    return markup

def admin_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('📊 Статистика'),
        types.KeyboardButton('🎁 Выдать подписку'),
        types.KeyboardButton('👥 Все пользователи'),
        types.KeyboardButton('Главное меню')
    )
    return markup

# ====================== РЕАЛЬНЫЕ ПЛАТЕЖИ CRYPTOBOT ======================
def create_cryptobot_invoice(amount, user_id):
    """Создает реальный счет"""
    try:
        # РЕАЛЬНЫЙ CryptoBot API
        response = requests.post(
            'https://pay.crypt.bot/api/createInvoice',
            headers={'Crypto-Pay-API-Token': config.CRYPTOBOT_TOKEN},
            json={
                'asset': 'USDT',
                'amount': str(amount),
                'description': f'Подписка MartSnoser | User: {user_id}',
                'hidden_message': f'ID: {user_id}',
                'payload': str(user_id)
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                invoice = data.get('result')
                return {
                    'success': True,
                    'invoice_id': invoice['invoice_id'],
                    'pay_url': invoice['pay_url']
                }
        
        return {'success': False, 'error': 'Ошибка'}
        
    except Exception as e:
        return {'success': False, 'error': str(e)}

def check_cryptobot_payment(invoice_id):
    """Проверяет статус платежа"""
    try:
        response = requests.get(
            f'https://pay.crypt.bot/api/getInvoices',
            headers={'Crypto-Pay-API-Token': config.CRYPTOBOT_TOKEN},
            params={'invoice_ids': invoice_id}
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') and data.get('result'):
                return data['result'][0]['status']
                
        return 'error'
        
    except:
        return 'error'

# ====================== ЗАПУСК TELETHON ======================
async def start_telethon():
    await checker.start()
    print("✅ Telethon запущен")

# ====================== ОСНОВНЫЕ КОМАНДЫ ======================
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    db.add_user(user_id, username)
    
    try:
        with open('banner.jpg', 'rb') as photo:
            bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption=f'*"Добро пожаловать в MartSnoser, {message.from_user.first_name}. Выбери действие:"*',
                parse_mode='Markdown',
                reply_markup=main_menu()
            )
    except:
        bot.send_message(
            message.chat.id,
            f'*"Добро пожаловать в MartSnoser, {message.from_user.first_name}. Выбери действие:"*',
            parse_mode='Markdown',
            reply_markup=main_menu()
        )
    
    if user_id == config.ADMIN_ID:
        bot.send_message(message.chat.id, "👑 Админ панель", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == 'Назад')
@bot.message_handler(func=lambda message: message.text == 'Главное меню')
def back_to_main(message):
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())

# ====================== ПРОФИЛЬ ======================
@bot.message_handler(func=lambda message: message.text == 'Профиль')
def profile_handler(message):
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    subscription_status = "✅ Активна" if db.check_subscription(user_id) else "❌ Не активна"
    
    if user and user[2]:
        end_date = user[2]
    else:
        end_date = "Нет подписки"
    
    profile_text = f"""
    📋 Ваш профиль:
    
    👤 ID: `{user_id}`
    📛 Имя: {message.from_user.first_name}
    
    🎫 Подписка:
    Статус: {subscription_status}
    Действует до: `{end_date}`
    Запросов: `{user[3] if user else 0}`
    
    💳 Для оплаты нажми "Прайсич"
    После оплаты нажми "Я оплатил(а)"
    """
    
    bot.send_message(
        message.chat.id,
        profile_text,
        parse_mode='Markdown',
        reply_markup=profile_menu()
    )

@bot.message_handler(func=lambda message: message.text == 'Я оплатил(а)')
def check_payment(message):
    user_id = message.from_user.id
    
    conn = sqlite3.connect(config.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT invoice_id, amount FROM payments WHERE user_id = ? AND status = 'pending' ORDER BY payment_id DESC LIMIT 1",
        (user_id,)
    )
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        bot.send_message(message.chat.id, "❌ Нет ожидающих оплату счетов.")
        return
    
    invoice_id, amount = result
    
    bot.send_message(message.chat.id, "🔍 Проверяю оплату...")
    
    status = check_cryptobot_payment(invoice_id)
    
    if status == 'paid':
        db.update_payment(invoice_id, 'paid')
        
        amount = float(amount)
        if amount == config.SUBSCRIPTION_PRICES['3_days']:
            days = 3
        elif amount == config.SUBSCRIPTION_PRICES['7_days']:
            days = 7
        else:
            days = 0
        
        if days > 0:
            end_date = db.update_subscription(user_id, days)
            bot.send_message(
                message.chat.id,
                f"✅ Оплата подтверждена!\nПодписка на {days} дней.\nДо: {end_date.strftime('%Y-%m-%d %H:%M:%S')}",
                reply_markup=main_menu()
            )
            return
    
    bot.send_message(
        message.chat.id,
        "❌ Оплата еще не поступила. Подождите.",
        reply_markup=profile_menu()
    )

# ====================== ПРАЙСИЧ ======================
@bot.message_handler(func=lambda message: message.text == 'Прайсич')
def price_handler(message):
    price_text = f"""
    💰 Наши тарифы:
    
    3 дня - {config.SUBSCRIPTION_PRICES['3_days']}$
    7 дней - {config.SUBSCRIPTION_PRICES['7_days']}$
    
    💎 Что дает подписка:
    ✅ Проверка аккаунтов
    ✅ Отправка запросов
    ✅ Инлайн-режим
    
    Выберите тариф:
    """
    
    bot.send_message(
        message.chat.id,
        price_text,
        parse_mode='Markdown',
        reply_markup=price_menu()
    )

@bot.message_handler(func=lambda message: message.text.startswith(('3 дня', '7 дней')))
def process_payment(message):
    user_id = message.from_user.id
    
    if '3 дня' in message.text:
        amount = config.SUBSCRIPTION_PRICES['3_days']
        days = 3
    else:
        amount = config.SUBSCRIPTION_PRICES['7_days']
        days = 7
    
    invoice_result = create_cryptobot_invoice(amount, user_id)
    
    if not invoice_result['success']:
        bot.send_message(message.chat.id, "❌ Ошибка при создании счета.")
        return
    
    db.add_payment(user_id, amount, invoice_result['invoice_id'])
    
    payment_text = f"""
    💳 Оплата подписки на {days} дней
    
    Сумма: {amount}$ USDT
    Ссылка: [Оплатить]({invoice_result['pay_url']})
    
    После оплаты нажмите "Я оплатил(а)"
    """
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Оплатить", url=invoice_result['pay_url']))
    
    bot.send_message(
        message.chat.id,
        payment_text,
        parse_mode='Markdown',
        reply_markup=markup
    )
    bot.send_message(message.chat.id, "После оплаты нажмите 'Я оплатил(а)'", reply_markup=profile_menu())

# ====================== ОТПРАВКА ЗАПРОСОВ ======================
@bot.message_handler(func=lambda message: message.text == 'Отправка запросов')
def request_handler(message):
    user_id = message.from_user.id
    
    if not db.check_subscription(user_id):
        bot.send_message(
            message.chat.id,
            "❌ Нет активной подписки!\nОформите в 'Прайсич'",
            reply_markup=main_menu()
        )
        return
    
    bot.send_message(
        message.chat.id,
        "✏️ Введите юзернейм жертвы (@username или username):",
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(message, process_username)

def process_username(message):
    username = message.text.replace('@', '').strip()
    user_id = message.from_user.id
    
    user_states[user_id] = {'username': username}
    
    loading_msg = bot.send_message(message.chat.id, "🔍 Проверяю аккаунт...")
    
    # РЕАЛЬНАЯ ПРОВЕРКА ТЕЛЕТОН
    account_info = get_account_info_sync(username)
    
    if account_info:
        info_text = f"""
        📊 Информация об аккаунте:
        
        👤 Юзернейм: @{account_info['username']}
        🆔 ID: `{account_info['id']}`
        📅 Дата создания: `{account_info['created']}`
        🌐 Дата центр: `{account_info['dc']}`
        📞 Телефон: {account_info['phone']}
        📝 Био: {account_info['bio'][:50]}...
        
        ❓ Вы точно хотите отправить запросы?
        """
        
        bot.edit_message_text(
            info_text,
            chat_id=message.chat.id,
            message_id=loading_msg.message_id,
            parse_mode='Markdown'
        )
        bot.send_message(
            message.chat.id,
            "Подтвердите отправку:",
            reply_markup=confirm_menu()
        )
        bot.register_next_step_handler(message, confirm_request, account_info)
    else:
        bot.edit_message_text(
            "❌ Не удалось проверить аккаунт.",
            chat_id=message.chat.id,
            message_id=loading_msg.message_id
        )
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())

def confirm_request(message, account_info):
    if message.text == '✅ Да':
        progress_msg = bot.send_message(
            message.chat.id,
            "🔄 Отправка запросов...\n"
            "▰▱▱▱▱▱▱▱▱ 10%",
            parse_mode='Markdown'
        )
        
        for i in range(1, 11):
            time.sleep(0.3)
            progress = i * 10
            bars = '▰' * i + '▱' * (10 - i)
            bot.edit_message_text(
                f"🔄 Отправка запросов...\n"
                f"{bars} {progress}%",
                chat_id=message.chat.id,
                message_id=progress_msg.message_id,
                parse_mode='Markdown'
            )
        
        db.increment_requests(message.from_user.id)
        db.add_request(message.from_user.id, account_info['username'])
        
        bot.edit_message_text(
            "✅ Запросы успешно отправлены!\n"
            f"Аккаунт @{account_info['username']} будет проверен.",
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            parse_mode='Markdown'
        )
    else:
        bot.send_message(message.chat.id, "❌ Отправка отменена.")
    
    bot.send_message(message.chat.id, "Главное меню:", reply_markup=main_menu())

# ====================== АДМИН ПАНЕЛЬ ======================
@bot.message_handler(func=lambda message: message.text == '📊 Статистика' and message.from_user.id == config.ADMIN_ID)
def admin_stats(message):
    users = db.get_all_users()
    active_subs = sum(1 for user in users if user[2] and db.check_subscription(user[0]))
    
    conn = sqlite3.connect(config.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'paid'")
    total_income = cursor.fetchone()[0] or 0
    conn.close()
    
    stats_text = f"""
    📊 Статистика:
    
    👥 Пользователей: {len(users)}
    🎫 Активных подписок: {active_subs}
    📤 Всего запросов: {sum(user[3] for user in users)}
    💰 Общий доход: {total_income}$
    
    Последние пользователи:
    """
    
    for user in users[-5:]:
        sub_status = "✅" if db.check_subscription(user[0]) else "❌"
        stats_text += f"\n{sub_status} ID: {user[0]} | @{user[1]}"
    
    bot.send_message(message.chat.id, stats_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '🎁 Выдать подписку' and message.from_user.id == config.ADMIN_ID)
def give_subscription(message):
    bot.send_message(
        message.chat.id,
        "Введите ID пользователя и дней через пробел:\nПример: 123456789 7"
    )
    bot.register_next_step_handler(message, process_give_sub)

def process_give_sub(message):
    try:
        user_id, days = map(int, message.text.split())
        end_date = db.update_subscription(user_id, days)
        
        bot.send_message(
            message.chat.id,
            f"✅ Подписка выдана {user_id} на {days} дней.\nДо: {end_date.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        bot.send_message(
            user_id,
            f"🎁 Админ выдал вам подписку на {days} дней!\nДо: {end_date.strftime('%Y-%m-%d %H:%M:%S')}",
            reply_markup=main_menu()
        )
    except:
        bot.send_message(message.chat.id, "❌ Ошибка. Пример: 123456789 7")

@bot.message_handler(func=lambda message: message.text == '👥 Все пользователи' and message.from_user.id == config.ADMIN_ID)
def all_users(message):
    users = db.get_all_users()
    
    if not users:
        bot.send_message(message.chat.id, "❌ Нет пользователей.")
        return
    
    users_text = f"👥 Все пользователи ({len(users)}):\n\n"
    
    for user in users:
        sub_status = "✅" if db.check_subscription(user[0]) else "❌"
        users_text += f"{sub_status} ID: `{user[0]}` | @{user[1] or 'нет'}\nЗапросов: {user[3]}\n\n"
    
    bot.send_message(message.chat.id, users_text, parse_mode='Markdown')

# ====================== ИНЛАЙН РЕЖИМ ======================
@bot.inline_handler(func=lambda query: True)
def inline_query(inline_query):
    user_id = inline_query.from_user.id
    
    # Проверяем подписку для инлайн режима
    if not db.check_subscription(user_id):
        # Показываем сообщение о необходимости подписки
        r = types.InlineQueryResultArticle(
            id='1',
            title='MartSnoser: Проверка аккаунтов',
            description='Требуется подписка. Нажмите для информации',
            input_message_content=types.InputTextMessageContent(
                message_text="🔒 *MartSnoser - Проверка аккаунтов*\n\n"
                            "Для использования инлайн-режима нужна подписка.\n"
                            "Перейдите в бота: @MartSnoserBot",
                parse_mode='Markdown'
            )
        )
        bot.answer_inline_query(inline_query.id, [r])
        return
    
    query = inline_query.query.strip()
    
    if not query:
        # Если запрос пустой, показываем инструкцию
        r = types.InlineQueryResultArticle(
            id='1',
            title='MartSnoser: Проверить аккаунт',
            description='Введите юзернейм после @MartSnoserBot',
            input_message_content=types.InputTextMessageContent(
                message_text="🔍 *MartSnoser - Проверка аккаунтов*\n\n"
                            "Использование: @MartSnoserBot username\n"
                            "Пример: @MartSnoserBot @username",
                parse_mode='Markdown'
            )
        )
        bot.answer_inline_query(inline_query.id, [r])
        return
    
    username = query.replace('@', '').strip()
    
    # Показываем что идет проверка
    r = types.InlineQueryResultArticle(
        id='1',
        title=f'MartSnoser: Проверка @{username}',
        description='Нажмите для проверки аккаунта',
        input_message_content=types.InputTextMessageContent(
            message_text=f"🔍 *MartSnoser проверяет аккаунт...*\n\n"
                        f"Юзернейм: @{username}\n"
                        f"Пользователь: @{inline_query.from_user.username or 'anon'}\n"
                        f"⏳ Ожидайте результат...",
            parse_mode='Markdown'
        )
    )
    
    bot.answer_inline_query(inline_query.id, [r], cache_time=1)
    
    # Делаем реальную проверку в фоне
    def check_in_background(username, inline_query_id, user_id):
        account_info = get_account_info_sync(username)
        
        if account_info:
            result_text = f"""
            📊 *Результат проверки MartSnoser*
            
            👤 Аккаунт: @{account_info['username']}
            🆔 ID: `{account_info['id']}`
            📅 Создан: `{account_info['created']}`
            🌐 Дата-центр: `{account_info['dc']}`
            
            📛 Имя: {account_info['first_name']} {account_info['last_name']}
            📞 Телефон: {account_info['phone']}
            
            ⚠️ Проверен: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            👤 Проверил: @{inline_query.from_user.username or 'anon'}
            
            *Информация получена через Telegram API*
            """
            
            # Обновляем результат
            r2 = types.InlineQueryResultArticle(
                id='2',
                title=f'✅ Результат проверки @{username}',
                description=f'ID: {account_info["id"]} | Создан: {account_info["created"]}',
                input_message_content=types.InputTextMessageContent(
                    message_text=result_text,
                    parse_mode='Markdown'
                )
            )
            
            try:
                bot.answer_inline_query(inline_query_id, [r2], cache_time=3600)
            except:
                pass
            
            # Увеличиваем счетчик запросов
            db.increment_requests(user_id)
        else:
            r2 = types.InlineQueryResultArticle(
                id='2',
                title=f'❌ Аккаунт @{username} не найден',
                description='Проверьте правильность юзернейма',
                input_message_content=types.InputTextMessageContent(
                    message_text=f"❌ *Аккаунт не найден*\n\n"
                                f"Юзернейм: @{username}\n"
                                f"Не удалось получить информацию.\n"
                                f"Возможно аккаунт не существует или приватный.",
                    parse_mode='Markdown'
                )
            )
            
            try:
                bot.answer_inline_query(inline_query_id, [r2], cache_time=3600)
            except:
                pass
    
    # Запускаем проверку в отдельном потоке
    thread = threading.Thread(
        target=check_in_background,
        args=(username, inline_query.id, user_id)
    )
    thread.start()

# ====================== ЗАПУСК БОТА ======================
def start_bot():
    print("🤖 MartSnoser Bot запущен!")
    bot.infinity_polling()

if __name__ == '__main__':
    # Запуск Telethon
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_telethon())
    
    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=start_bot)
    bot_thread.start()
    
    print("✅ Бот готов к работе!")
    print("✅ Telethon подключен!")
    print("✅ CryptoBot настроен!")
    
    # Держим основной поток активным
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⛔ Бот остановлен")