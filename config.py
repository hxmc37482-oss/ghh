import os
from dotenv import load_dotenv

load_dotenv()

# Конфигурация
BOT_TOKEN = os.getenv('BOT_TOKEN', '8490698154:AAFJbSYEulyLJMegQb4ij3KVih1cThXJv3A')
CRYPTOBOT_TOKEN = os.getenv('CRYPTOBOT_TOKEN', '505975:AAWB2WYvz4wJuseOm4nrs875jo4ORUJl7ww')
ADMIN_ID = int(os.getenv('ADMIN_ID', 7037764178))
API_ID = int(os.getenv('API_ID', 30147101))
API_HASH = os.getenv('API_HASH', '72c394e899371cf4f9f9253233cbf18f')

# Пути
DATABASE_NAME = 'mart_snoser.db'
BANNER_PATH = 'banner.jpg'  # Положите ваш баннер в эту папку

# Настройки подписок
SUBSCRIPTION_PLANS = {
    '3_days': {'days': 3, 'price': 1.0, 'currency': 'USD'},
    '7_days': {'days': 7, 'price': 5.0, 'currency': 'USD'}
}