import ccxt
import os

def test_connection():
    print("Testing Binance Futures Testnet Connection...")
    
    # Simulate the configuration we use in app_lite.py
    exchange_class = ccxt.binanceusdm
    exchange = exchange_class({
        'apiKey': 'test', # Dummy
        'secret': 'test', # Dummy
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    # Manual Override
    print("Applying URL override...")
    exchange.urls['api'] = {
        'fapiPublic': 'https://testnet.binancefuture.com/fapi/v1',
        'fapiPrivate': 'https://testnet.binancefuture.com/fapi/v1',
        'public': 'https://testnet.binancefuture.com/fapi/v1',
        'private': 'https://testnet.binancefuture.com/fapi/v1',
        # Adding SAPI to satisfy checks
        'sapi': 'https://testnet.binance.vision/api',
        'sapiPublic': 'https://testnet.binance.vision/api',
        'sapiPrivate': 'https://testnet.binance.vision/api',
        
        'dapiPublic': 'https://testnet.binancefuture.com/dapi/v1',
        'dapiPrivate': 'https://testnet.binancefuture.com/dapi/v1',
    }
    
    print("Exchange URLs configured:")
    print(exchange.urls['api'])
    
    try:
        # Try to access a public endpoint to verify URL structure works (no auth needed)
        print("Fetching ticker for BTC/USDT...")
        ticker = exchange.fetch_ticker('BTC/USDT')
        print(f"Success! BTC Price: {ticker['last']}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_connection()
