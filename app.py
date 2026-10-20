import os
import asyncio
from threading import Thread
from flask import Flask
import bot as my_bot  # Импортируем ваш bot.py

app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "Bot is running", 200

def run_flask():
    # Flask работает в фоновом потоке
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # 1. Запускаем Flask в фоне (чтобы Render видел открытый порт)
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True # Чтобы поток завершился вместе с основным
    flask_thread.start()
    
    # 2. Запускаем бота в ГЛАВНОМ потоке (это исправит ошибку set_wakeup_fd)
    asyncio.run(my_bot.main())