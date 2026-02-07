
import requests
import json
import os

class WeChatNotifier:
    def __init__(self, webhook_url=None):
        # 优先从环境变量读取，如果没有则使用传入的参数
        self.webhook_url = webhook_url or os.getenv("WECHAT_WEBHOOK_URL")
        
    def send_text(self, content):
        """发送纯文本消息"""
        if not self.webhook_url:
            print("未配置企业微信 Webhook，跳过发送。")
            return

        headers = {'Content-Type': 'application/json'}
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        
        try:
            resp = requests.post(self.webhook_url, headers=headers, json=data)
            if resp.json().get('errcode') == 0:
                print("企业微信消息发送成功")
            else:
                print(f"企业微信发送失败: {resp.text}")
        except Exception as e:
            print(f"发送异常: {e}")

    def send_markdown(self, content):
        """发送 Markdown 消息"""
        if not self.webhook_url:
            return

        headers = {'Content-Type': 'application/json'}
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        try:
            requests.post(self.webhook_url, headers=headers, json=data)
        except Exception:
            pass

# 单例模式使用示例
# notifier = WeChatNotifier("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY")
# notifier.send_text("测试消息")
