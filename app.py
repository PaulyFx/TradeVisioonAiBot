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

# A modell neve (Ezt fogjuk átírni a log alapján, ha nem működik)
MODEL_NAME = 'gemini-1.5-flash' 

# Hálózati türelem
apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

# Kliensek inicializálása
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- MINI WEB SZERVER (A Render életben tartásához) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI Status: RUNNING")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f">>> Health server elindult a {port} porton.", flush=True)
    server.serve_forever()

# --- BOT FUNKCIÓK ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI ONLINE!**\n\nKüldj egy képet elemzésre!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép érkezett elemzésre!", flush=True)
    msg = bot.reply_to(message, "⏳ *Elemzés folyamatban...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = "Analyze this trading chart. Signal (BUY/SELL), Trend, Support/Resistance. English."
        
        # Itt használjuk a beállított modell nevet
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=[prompt, img]
        )
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"📊 **Elemzés:**\n\n{response.text}",
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"!!! Elemzési hiba: {e}", flush=True)
        bot.edit_message_text(f"❌ Hiba: `{str(e)[:100]}`", message.chat.id, msg.message_id, parse_mode='Markdown')

# --- INDÍTÁS ÉS MODELL LISTÁZÁS ---
if __name__ == "__main__":
    # 1. Health szerver indítása
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print("--- NYOMOZÁS INDUL: ELÉRHETŐ MODELLEK ---", flush=True)
    try:
        # KILISTÁZZUK AZ ÖSSZES MODELLT
        available_models = client.models.list()
        for m in available_models:
            # Csak azokat írjuk ki, amik tudnak tartalmat generálni
            if 'generateContent' in m.supported_generation_methods:
                print(f"SZABAD MODELL NÉV: {m.name}", flush=True)
    except Exception as e:
        print(f"!!! Nem sikerült listázni a modelleket: {e}", flush=True)
    print("------------------------------------------", flush=True)

    print(">>> TradeVision AI Bot indítása...", flush=True)
    
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            me = bot.get_me()
            print(f">>> SIKER! Bot: @{me.username}", flush=True)
            bot.infinity_polling(timeout=90, long_polling_timeout=40)
        except Exception as e:
            if "Conflict" in str(e):
                print(">>> Konfliktus, várjunk...", flush=True)
                time.sleep(15)
            else:
                time.sleep(5)
