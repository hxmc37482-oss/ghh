# cryptobot.py
import requests

class Api:
    def __init__(self, token):
        self.token = token
        self.base_url = 'https://pay.crypt.bot/api/'
    
    def _request(self, method, endpoint, **kwargs):
        headers = {
            'Crypto-Pay-API-Token': self.token
        }
        url = self.base_url + endpoint
        response = requests.request(method, url, headers=headers, **kwargs)
        return response.json()
    
    def createInvoice(self, asset, amount, description=''):
        return self._request('POST', 'createInvoice', json={
            'asset': asset,
            'amount': str(amount),
            'description': description
        })
    
    def getInvoices(self, invoice_ids=None):
        params = {}
        if invoice_ids:
            params['invoice_ids'] = invoice_ids
        return self._request('GET', 'getInvoices', params=params)