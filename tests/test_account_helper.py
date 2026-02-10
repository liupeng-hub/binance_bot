import pytest
from unittest.mock import MagicMock
from src.utils.account_helper import get_account_balance
import ccxt

def test_get_account_balance_success(mocker):
    # Mock ccxt.binanceusdm
    mock_exchange = MagicMock()
    mock_exchange.fetch_balance.return_value = {
        'USDT': {'free': 1000.0, 'total': 1500.0}
    }
    mocker.patch('ccxt.binanceusdm', return_value=mock_exchange)
    
    balance = get_account_balance('api_key', 'secret_key', testnet=True)
    
    assert balance == 1000.0
    mock_exchange.set_sandbox_mode.assert_called_with(True)
    mock_exchange.fetch_balance.assert_called_once()

def test_get_account_balance_no_keys():
    balance = get_account_balance(None, None)
    assert balance == 0.0

def test_get_account_balance_error(mocker):
    # Mock exception
    mock_exchange = MagicMock()
    mock_exchange.fetch_balance.side_effect = Exception("Network Error")
    mocker.patch('ccxt.binanceusdm', return_value=mock_exchange)
    
    balance = get_account_balance('api', 'secret')
    assert balance == 0.0
