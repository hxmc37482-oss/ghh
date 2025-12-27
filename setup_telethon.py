#!/usr/bin/env python3
"""
Скрипт для настройки Telethon с исправленной обработкой 2FA
"""

import asyncio
from telethon import TelegramClient

# Получаем данные из .env
API_ID = 30147101  # Ваш API_ID из .env
API_HASH = '72c394e899371cf4f9f9253233cbf18f'  # Ваш API_HASH из .env

async def main():
    print("🔧 Настройка Telethon...")
    print(f"API ID: {API_ID}")
    print("=" * 50)
    
    client = TelegramClient('mart_snoser_session', API_ID, API_HASH)
    
    try:
        await client.connect()
        print("✅ Подключено к Telegram")
        
        if not await client.is_user_authorized():
            print("\n📱 Шаг 1: Введите номер телефона (с кодом страны)")
            print("Пример: +79123456789 или +27631765362")
            print("\nВведите номер:")
            phone = input().strip()
            
            print(f"\n📲 Отправляю код на {phone}...")
            await client.send_code_request(phone)
            
            print("\n📋 Введите код из Telegram (5 цифр):")
            code = input().strip()
            
            try:
                # Пробуем войти с кодом
                print("\n🔄 Пробую войти с кодом...")
                await client.sign_in(phone, code)
                print("✅ Авторизация успешна!")
                
            except Exception as e:
                if "password" in str(e) or "Two-steps" in str(e):
                    print("\n🔐 Требуется двухфакторная аутентификация")
                    print("Введите пароль от 2FA:")
                    password = input().strip()
                    
                    try:
                        await client.sign_in(password=password)
                        print("✅ Авторизация с паролем успешна!")
                    except Exception as e2:
                        print(f"❌ Ошибка при вводе пароля: {e2}")
                        return
                else:
                    print(f"❌ Ошибка авторизации: {e}")
                    return
        else:
            print("✅ Уже авторизован!")
        
        # Проверяем подключение
        print("\n🔍 Проверяю подключение...")
        try:
            me = await client.get_me()
            if me:
                name = me.first_name or ""
                last_name = me.last_name or ""
                username = f"@{me.username}" if me.username else "нет"
                print(f"✅ Вы авторизованы как: {name} {last_name}")
                print(f"📧 Username: {username}")
                print(f"🆔 ID: {me.id}")
            else:
                print("⚠️ Не удалось получить информацию о пользователе")
        except Exception as e:
            print(f"⚠️ Ошибка при получении информации: {e}")
        
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        print("\nВозможные решения:")
        print("1. Проверьте интернет-подключение")
        print("2. Проверьте правильность API_ID и API_HASH")
        print("3. Убедитесь что номер телефона правильный")
        
    finally:
        await client.disconnect()
        print("\n" + "=" * 50)
        print("👋 Настройка Telethon завершена!")
        print("Теперь можно запускать бота: python main.py")

if __name__ == "__main__":
    asyncio.run(main())