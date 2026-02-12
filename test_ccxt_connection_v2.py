import ccxt
import os

def test_connection():
    print("Testing Binance Futures Testnet Connection...")
    
    exchange_class = ccxt.binanceusdm
    exchange = exchange_class({
        'apiKey': 'test',
        'secret': 'test',
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    # Override URLs
    exchange.urls['api'] = {
        'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
        'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
        'public': 'https://testnet.binancefuture.com/fapi/v1',
        'private': 'https://testnet.binancefuture.com/fapi/v1',
        # Point sapi to fapi to avoid "missing URL" error, but we expect 404 if called
        'sapi': 'https://testnet.binancefuture.com/fapi/v1', 
        'sapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
        'sapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
    }
    
    # DISABLE fetchCurrencies to prevent calling Spot endpoints
    exchange.has['fetchCurrencies'] = False
    
    try:
        print("Fetching ticker...")
        ticker = exchange.fetch_ticker('BTC/USDT')
        print(f"Success! BTC Price: {ticker['last']}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_connection()
