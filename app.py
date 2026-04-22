import os
import telebot
from telebot import apihelper
from google import genai
from PIL import Image
import io
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- KONFIGURÁCIÓ ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Alapértelmezett modell (ezt fogjuk cserélni a log alapján)
MODEL_NAME = 'gemini-1.5-flash' 

apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- WEB SZERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- BOT ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "TradeVision Online! Küldj képet!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    msg = bot.reply_to(message, "⏳ *Elemzés...*", parse_mode='Markdown')
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=["Analyze this chart. Signal, Trend, Support/Resistance.", img]
        )
        bot.edit_message_text(f"📊 {response.text}", message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Hiba: `{str(e)[:100]}`", message.chat.id, msg.message_id, parse_mode='Markdown')

# --- INDÍTÁS ÉS LISTÁZÁS ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print("--- MODELLEK LISTÁZÁSA ---", flush=True)
    try:
        # Itt a javítás: csak a neveket írjuk ki, mindenféle extra szűrés nélkül
        for m in client.models.list():
            print(f"ELÉRHETŐ: {m.name}", flush=True)
    except Exception as e:
        print(f"Még mindig hiba a listázásnál: {e}", flush=True)
    print("--------------------------", flush=True)

    while True:
        try:
            bot.remove_webhook()
            bot.infinity_polling(timeout=90)
        except Exception as e:
            time.sleep(10)
