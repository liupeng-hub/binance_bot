import ccxt
import os
from dotenv import load_dotenv

def get_account_balance(api_key, secret_key, testnet=False):
    """
    Fetches the account balance (USDT) from Binance.
    """
    if not api_key or not secret_key:
        return 0.0

    # Sanitize keys
    api_key = api_key.strip()
    secret_key = secret_key.strip()

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
            # Manual Override for Testnet
            exchange.urls['api'] = {
                'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                'public': 'https://testnet.binancefuture.com/fapi/v1',
                'private': 'https://testnet.binancefuture.com/fapi/v1',
                'sapi': 'https://testnet.binancefuture.com/fapi/v1',
            }
            exchange.has['fetchCurrencies'] = False
        
        balance = exchange.fetch_balance()
        # Debug: Print keys to see what we got
        # print(f"Balance keys: {balance.keys()}")
        
        # 优先读取 total (权益), 其次 free (可用)
        # 兼容不同交易所的返回结构
        usdt = balance.get('USDT', {})
        if 'total' in usdt:
            return usdt['total']
        elif 'free' in usdt:
            return usdt['free']
        else:
            # 尝试从 info 原始数据中读取 (Binance 特有)
            # Binance Future response structure usually has 'totalWalletBalance' or 'totalMarginBalance' in info
            if 'info' in balance:
                info = balance['info']
                # info 可以是 list (assets) 或 dict
                if isinstance(info, dict):
                    return float(info.get('totalMarginBalance', 0.0))
                elif isinstance(info, list):
                    # 遍历查找 USDT
                    for asset in info:
                        if asset.get('asset') == 'USDT':
                            return float(asset.get('marginBalance', 0.0))
            
            return 0.0
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return 0.0

def get_exchange_connection(api_key, secret_key, testnet=False, exchange_id='binance'):
    """Helper to get ccxt exchange instance"""
    exchange_config = {
        'apiKey': api_key,
        'secret': secret_key,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    }
    
    # Proxy
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    if http_proxy or https_proxy:
        exchange_config['proxies'] = {'http': http_proxy, 'https': https_proxy}

    try:
        exchange_class = getattr(ccxt, f"{exchange_id}usdm") if exchange_id == 'binance' else getattr(ccxt, exchange_id)
        exchange = exchange_class(exchange_config)
        if testnet:
            if exchange_id == 'binance' or exchange_id == 'binanceusdm':
                exchange.urls['api'] = {
                    'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
                    'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
                    'public': 'https://testnet.binancefuture.com/fapi/v1',
                    'private': 'https://testnet.binancefuture.com/fapi/v1',
                    'sapi': 'https://testnet.binancefuture.com/fapi/v1',
                }
                exchange.has['fetchCurrencies'] = False
            else:
                exchange.set_sandbox_mode(True)
        return exchange
    except Exception as e:
        print(f"Error creating exchange connection: {e}")
        return None
