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
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview' 

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
        self.wfile.write(b"ONLINE")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- BOT FUNKCIÓK ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI Aktív!**\n\nKüldj egy chartot!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép elemzése...", flush=True)
    msg = bot.reply_to(message, "⏳ *Elemzés folyamatban...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = "Analyze this trading chart. Signal (BUY/SELL), Trend, Support/Resistance. English."
        
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=[prompt, img]
        )
        
        full_text = f"📊 **Elemzés:**\n\n{response.text}"
        
        try:
            # Megpróbáljuk szépen formázva elküldeni
            bot.edit_message_text(full_text, message.chat.id, msg.message_id, parse_mode='Markdown')
        except:
            # Ha a Markdown elrontja, elküldjük sima szövegként (biztonsági mentés)
            bot.edit_message_text(full_text, message.chat.id, msg.message_id, parse_mode=None)
            
        print(">>> Sikeres válasz.", flush=True)

    except Exception as e:
        print(f"!!! Hiba: {e}", flush=True)
        bot.edit_message_text(f"❌ Hiba: {str(e)[:100]}", message.chat.id, msg.message_id)

# --- INDÍTÁS ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            print(">>> Bot indul...", flush=True)
            bot.infinity_polling(timeout=90)
        except Exception as e:
            time.sleep(5)
