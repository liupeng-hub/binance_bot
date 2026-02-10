import ccxt
import os
from dotenv import load_dotenv

def get_account_balance(api_key, secret_key, testnet=False):
    """
    Fetches the account balance (USDT) from Binance.
    """
    if not api_key or not secret_key:
        return 0.0

    exchange_config = {
        'apiKey': api_key,
        'secret': secret_key,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future'
        }
    }
    
    # 尝试配置本地代理
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    
    if http_proxy or https_proxy:
        exchange_config['proxies'] = {}
        if http_proxy:
            exchange_config['proxies']['http'] = http_proxy
        if https_proxy:
            exchange_config['proxies']['https'] = https_proxy

    try:
        exchange = ccxt.binanceusdm(exchange_config)
        if testnet:
            exchange.set_sandbox_mode(True)
        
        balance = exchange.fetch_balance()
        # 对于 USDT 本位合约，通常关注 USDT 的 free 或 total
        usdt_balance = balance.get('USDT', {})
        return usdt_balance.get('free', 0.0) # 或者 'total'
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return 0.0
