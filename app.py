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

# A logod alapján ez a pontos, 500-as kvótájú modell azonosító:
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview' 

# Hálózati stabilitás beállítások
apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

# Kliensek inicializálása
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- WEB SZERVER (A Render.com számára) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI: ONLINE")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f">>> Port figyelése: {port}", flush=True)
    server.serve_forever()

# --- BOT FUNKCIÓK ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI Aktív!**\n\nKüldj egy chartot, és elemzem a Gemini 3.1 Flash Lite segítségével!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép érkezett elemzésre...", flush=True)
    msg = bot.reply_to(message, "⏳ *Elemzés folyamatban...*", parse_mode='Markdown')
    
    try:
        # Kép letöltése és feldolgozása
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = "Analyze this trading chart. Identify Trend, Support/Resistance, and give a Signal (BUY/SELL/NEUTRAL). Professional English analysis."
        
        # AI Hívás a pontos modellel
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=[prompt, img]
        )
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"📊 **Elemzés eredménye:**\n\n{response.text}",
            parse_mode='Markdown'
        )
        print(">>> Elemzés sikeresen elküldve.", flush=True)

    except Exception as e:
        print(f"!!! Elemzési hiba: {e}", flush=True)
        bot.edit_message_text(f"❌ Hiba: `{str(e)[:150]}`", message.chat.id, msg.message_id, parse_mode='Markdown')

# --- INDÍTÁS ÉS HIBAKEZELÉS ---
if __name__ == "__main__":
    # Életjel szerver indítása
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print(f">>> Modell beállítva: {MODEL_NAME}", flush=True)
    print(">>> TradeVision AI Bot indítása...", flush=True)
    
    while True:
        try:
            # Konfliktusok elkerülése érdekében töröljük a beragadt webhookokat
            bot.remove_webhook()
            time.sleep(1)
            
            me = bot.get_me()
            print(f">>> SIKER! Kapcsolódva: @{me.username}", flush=True)
            
            # Folyamatos figyelés
            bot.infinity_polling(timeout=90, long_polling_timeout=40)
            
        except Exception as e:
            if "Conflict" in str(e):
                print(">>> 409 Konfliktus: Várunk a régi példány leállására (15mp)...", flush=True)
                time.sleep(15)
            else:
                print(f">>> Hiba: {e}. Újraindítás 5mp múlva...", flush=True)
                time.sleep(5)
