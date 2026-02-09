import unittest
from unittest.mock import patch, MagicMock
from src.utils.notification import FeishuNotifier, TelegramNotifier, NotificationManager

class TestNotification(unittest.TestCase):
    
    @patch('requests.post')
    def test_feishu_notifier(self, mock_post):
        notifier = FeishuNotifier("https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
        
        # Mock successful response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        notifier.send("Test Title", "Test Message", "INFO")
        
        # Verify call
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['card']['header']['title']['content'], "Test Title")
        self.assertEqual(kwargs['json']['card']['elements'][0]['text']['content'], "Test Message")

    @patch('requests.post')
    def test_telegram_notifier(self, mock_post):
        notifier = TelegramNotifier("123:token", "999")
        
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response
        
        notifier.send("Alert", "Something happened", "ERROR")
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("❌ Alert", kwargs['json']['text'])
        self.assertEqual(kwargs['json']['chat_id'], "999")

    def test_notification_manager(self):
        manager = NotificationManager()
        mock_n1 = MagicMock()
        mock_n2 = MagicMock()
        
        manager.add_notifier(mock_n1)
        manager.add_notifier(mock_n2)
        
        manager.send("Title", "Msg")
        
        mock_n1.send.assert_called_with("Title", "Msg", "INFO")
        mock_n2.send.assert_called_with("Title", "Msg", "INFO")

if __name__ == '__main__':
    unittest.main()
