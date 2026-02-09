import requests
import json
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

class NotificationBase(ABC):
    @abstractmethod
    def send(self, title, message, level='INFO'):
        pass

class FeishuNotifier(NotificationBase):
    """
    Feishu (Lark) Webhook Notifier
    """
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def send(self, title, message, level='INFO'):
        if not self.webhook_url:
            return

        headers = {'Content-Type': 'application/json'}
        
        # Color mapping for different levels
        color_map = {
            'INFO': 'blue',
            'WARNING': 'orange',
            'ERROR': 'red',
            'SUCCESS': 'green'
        }
        color = color_map.get(level, 'blue')

        data = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": color 
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": message
                        }
                    }
                ]
            }
        }

        try:
            response = requests.post(self.webhook_url, headers=headers, json=data, timeout=5)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Feishu notification: {e}")

class TelegramNotifier(NotificationBase):
    """
    Telegram Bot Notifier
    """
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send(self, title, message, level='INFO'):
        if not self.token or not self.chat_id:
            return

        # Simple text formatting
        emoji_map = {
            'INFO': 'ℹ️',
            'WARNING': '⚠️',
            'ERROR': '❌',
            'SUCCESS': '✅'
        }
        emoji = emoji_map.get(level, 'ℹ️')
        
        full_text = f"*{emoji} {title}*\n\n{message}"

        data = {
            "chat_id": self.chat_id,
            "text": full_text,
            "parse_mode": "Markdown"
        }

        try:
            response = requests.post(self.api_url, json=data, timeout=5)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")

class NotificationManager:
    """
    Central Manager for Notifications
    """
    def __init__(self):
        self.notifiers = []

    def add_notifier(self, notifier):
        self.notifiers.append(notifier)

    def send(self, title, message, level='INFO'):
        for notifier in self.notifiers:
            notifier.send(title, message, level)

# Global Instance
notification_manager = NotificationManager()
