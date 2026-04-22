import os
import telebot
from telebot import apihelper
from google import genai
from PIL import Image
import io
import time
import threading
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- KONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Brutális timeout és kényszerített szálkezelés
apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

# Alternatív megoldás: ha a fő szerver blokkolt, megpróbáljuk ezt
# apihelper.API_URL = "https://api.telegram.org/bot{0}/{1}"

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- WEB SZERVER (A Hugging Face-nek) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI Status: RUNNING")
    def log_message(self, format, *args): return # Kikapcsoljuk a GET logokat, hogy lássuk a botot

def run_health_server():
    httpd = HTTPServer(('0.0.0.0', 7860), HealthCheckHandler)
    httpd.serve_forever()

# --- BOT LOGIKA ---
@bot.message_handler(commands=['start'])
def welcome(message):
    print(f">>> Üzenet érkezett: {message.text}", flush=True)
    bot.reply_to(message, "✅ TradeVision AI ONLINE!\nKüldj egy chart fotót.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép érkezett!", flush=True)
    msg = bot.reply_to(message, "⏳ Elemzés folyamatban...")
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=["Analyze this trading chart. Signal (BUY/SELL), Trend, Levels. English.", img]
        )
        bot.edit_message_text(f"📊 **Analysis:**\n\n{response.text}", message.chat.id, msg.message_id, parse_mode='Markdown')
    except Exception as e:
        print(f"!!! Elemzési hiba: {e}", flush=True)
        bot.edit_message_text(f"❌ Hiba: {str(e)}", message.chat.id, msg.message_id)

# --- INDÍTÁS ---
if __name__ == "__main__":
    # Web szerver indítása háttérben
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print(">>> TradeVision AI INDÍTÁSA...", flush=True)
    
    # Próbáljuk meg kideríteni, látjuk-e a Telegramot
    while True:
        try:
            print(">>> Kapcsolódási kísérlet a Telegramhoz...", flush=True)
            bot.remove_webhook()
            me = bot.get_me()
            print(f">>> SIKER! Bot név: @{me.username}", flush=True)
            
            print(">>> Polling indítása...", flush=True)
            bot.infinity_polling(timeout=90, long_polling_timeout=40)
        except Exception as e:
            print(f">>> HIBA: {e}", flush=True)
            print(">>> Újrapróbálkozás 15 másodperc múlva...", flush=True)
            time.sleep(15)