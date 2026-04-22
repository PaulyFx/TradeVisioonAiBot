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

# --- KONFIGURÁCIÓ ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Hálózati türelem beállítása
apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

# Kliensek inicializálása
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- MINI WEB SZERVER (A Render.com életben tartásához) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI Status: RUNNING")
    
    def log_message(self, format, *args):
        return # Tiszta logok érdekében nem naplózzuk a pingelést

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f">>> Health server elindult a {port} porton.", flush=True)
    server.serve_forever()

# --- BOT FUNKCIÓK ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    print(f">>> Üzenet érkezett: {message.text}", flush=True)
    bot.reply_to(message, "🚀 **TradeVision AI ONLINE!**\n\nKüldj egy tőzsdei grafikont, és elemzem a Gemini 3.1 Flash Lite segítségével!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép érkezett elemzésre!", flush=True)
    msg = bot.reply_to(message, "⏳ *Elemzés folyamatban...*", parse_mode='Markdown')
    
    try:
        # Kép letöltése
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        # AI Elemzés - A táblázatod szerinti 500/nap kvótás modell
        prompt = "Analyze this trading chart. Give Signal (BUY/SELL), Trend, and Support/Resistance levels. English please."
        
        response = client.models.generate_content(
            model='gemini-3-flash', 
            contents=[prompt, img]
        )
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"📊 **Elemzés eredménye:**\n\n{response.text}",
            parse_mode='Markdown'
        )
        print(">>> Sikeres elemzés.", flush=True)

    except Exception as e:
        error_msg = str(e)
        print(f"!!! Elemzési hiba: {error_msg}", flush=True)
        bot.edit_message_text(f"❌ Hiba történt az elemzés során.\n`{error_msg[:100]}`", message.chat.id, msg.message_id, parse_mode='Markdown')

# --- INDÍTÁS ÉS KONFLIKTUS KEZELÉS ---
if __name__ == "__main__":
    # Web szerver indítása külön szálon
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print(">>> TradeVision AI Bot indítása...", flush=True)
    
    while True:
        try:
            # Tisztítjuk a korábbi esetleges beragadt kapcsolatokat
            bot.remove_webhook()
            time.sleep(1)
            
            me = bot.get_me()
            print(f">>> SIKER! Kapcsolódva mint: @{me.username}", flush=True)
            
            # Polling indítása
            bot.infinity_polling(timeout=90, long_polling_timeout=40)
            
        except Exception as e:
            # Ha 409 Conflict hiba van, várjunk, hogy a régi példány leálljon
            if "Conflict" in str(e):
                print(">>> KONFLIKTUS: Egy másik példány még fut. Várakozás 15 másodpercig...", flush=True)
                time.sleep(15)
            else:
                print(f">>> Hálózati hiba: {e}. Újrapróbálkozás 5 mp múlva...", flush=True)
                time.sleep(5)
