from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import UsernameInvalidError, UsernameNotOccupiedError
from datetime import datetime
import pytz
import asyncio
from config import API_ID, API_HASH, SESSION_NAME

class TelegramChecker:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.moscow_tz = pytz.timezone('Europe/Moscow')
    
    async def start(self):
        await self.client.start()
        print("✅ Telethon клиент запущен")
    
    async def get_account_info(self, username):
        """Реальная проверка аккаунта через Telethon"""
        try:
            username = username.replace('@', '').strip()
            
            # Получаем информацию об аккаунте
            user = await self.client.get_entity(username)
            
            if not user:
                return None
            
            # Получаем полную информацию
            full_user = await self.client(GetFullUserRequest(user))
            
            # Определяем примерную дату создания по ID
            user_id = user.id
            if user_id > 0:
                timestamp = (user_id >> 32) + 1288834974657
                created_date = datetime.fromtimestamp(timestamp/1000, self.moscow_tz)
            else:
                created_date = datetime.now(self.moscow_tz)
            
            # Определяем дата-центр
            dc_id = 1  # По умолчанию
            if hasattr(user, 'photo') and user.photo:
                dc_id = user.photo.dc_id
            
            dc_map = {
                1: "Сан-Франциско, США",
                2: "Амстердам, Нидерланды",
                3: "Майами, США",
                4: "Сингапур",
                5: "Дубай, ОАЭ"
            }
            dc_location = dc_map.get(dc_id, "Неизвестно")
            
            # Формируем результат
            account_info = {
                'username': user.username or 'Нет юзернейма',
                'id': user.id,
                'first_name': user.first_name or '',
                'last_name': user.last_name or '',
                'phone': user.phone or 'Скрыт',
                'is_bot': user.bot,
                'is_verified': user.verified or False,
                'is_scam': user.scam or False,
                'is_fake': user.fake or False,
                'created': created_date.strftime('%Y-%m-%d'),
                'dc': dc_location,
                'bio': full_user.full_user.about or 'Нет описания',
                'common_chats': full_user.full_user.common_chats_count,
                'photos_count': len(full_user.profile_photos) if full_user.profile_photos else 0,
                'restricted': user.restricted or False
            }
            
            return account_info
            
        except (UsernameInvalidError, UsernameNotOccupiedError):
            return None
        except Exception as e:
            print(f"Ошибка проверки: {e}")
            return None

# Глобальный экземпляр
checker = TelegramChecker()

# Синхронные функции
def get_account_info_sync(username):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(checker.get_account_info(username))
    finally:
        loop.close()

async def get_account_info_async(username):
    return await checker.get_account_info(username)