import aiohttp
import json

async def create_invoice(token: str, amount: float, currency: str = "USD", 
                         description: str = "", user_id: int = None) -> dict:
    """
    Создает инвойс в CryptoBot
    """
    url = f"https://pay.crypt.bot/api/createInvoice"
    
    headers = {
        "Crypto-Pay-API-Token": token,
        "Content-Type": "application/json"
    }
    
    data = {
        "asset": currency,
        "amount": str(amount),
        "description": description
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=data) as response:
            return await response.json()

async def get_invoice(token: str, invoice_id: str) -> dict:
    """
    Получает информацию об инвойсе
    """
    url = f"https://pay.crypt.bot/api/getInvoices"
    
    headers = {
        "Crypto-Pay-API-Token": token,
        "Content-Type": "application/json"
    }
    
    params = {
        "invoice_ids": invoice_id
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            return await response.json()

async def get_exchange_rates(token: str) -> dict:
    """
    Получает курсы валют
    """
    url = f"https://pay.crypt.bot/api/getExchangeRates"
    
    headers = {
        "Crypto-Pay-API-Token": token
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return await response.json()