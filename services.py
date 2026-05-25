# Tên file: services.py
import requests

def send_discord_notification(webhook_url, message):
    """
    Gửi thông báo tới Discord qua Webhook.
    """
    if not webhook_url or "discord" not in webhook_url:
        return
    try: 
        requests.post(webhook_url, json={"content": message}, timeout=2)
    except Exception as e: 
        print(f"Lỗi khi gửi Discord: {e}")
        pass
