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
# A Render a "Secret Files" vagy "Environment Variables" közül olvassa ki ezeket
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Extra türelem a hálózati ingadozásokhoz
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
        self.wfile.write(b"TradeVision AI Status: RUNNING and HEALTHY")
    
    def log_message(self, format, *args):
        return # Kikapcsoljuk a naplózást, hogy ne zavarja a bot logjait

def run_health_server():
    # A Render automatikusan ad egy portot a környezeti változókban (PORT)
    # Ha nincs megadva, alapértelmezetten a 7860-at használja
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f">>> Health check szerver elindult a {port} porton.", flush=True)
    server.serve_forever()

# --- BOT FUNKCIÓK ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    print(f">>> Üzenet érkezett: {message.text}", flush=True)
    bot.reply_to(message, "🚀 **TradeVision AI ONLINE!**\n\nKüldj egy tőzsdei grafikont (fotót), és azonnal elemzem neked!")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Kép érkezett elemzésre!", flush=True)
    msg = bot.reply_to(message, "⏳ *Elemzés folyamatban (Gemini 2.0 Flash)...*", parse_mode='Markdown')
    
    try:
        # 1. Kép letöltése a Telegramról
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        # 2. AI Elemzés kérése
        prompt = "Analyze this trading chart. Provide: Signal (BUY/SELL), Trend, Support/Resistance levels. Keep it professional. English language."
        
        response = client.models.generate_content(
    model='gemini-2.0-flash',  # 2.0 helyett próbáld meg az 1.5-öt
    contents=[prompt, img]
)
        
        # 3. Válasz küldése a felhasználónak
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=msg.message_id,
            text=f"📊 **TradeVision AI Elemzés:**\n\n{response.text}",
            parse_mode='Markdown'
        )
        print(">>> Sikeres elemzés elküldve.", flush=True)

    except Exception as e:
        error_txt = f"❌ Hiba történt: {str(e)}"
        print(f"!!! {error_txt}", flush=True)
        bot.edit_message_text(error_txt, message.chat.id, msg.message_id)

# --- FŐ PROGRAM INDÍTÁSA ---
if __name__ == "__main__":
    # 1. Elindítjuk a web szervert egy külön szálon
    threading.Thread(target=run_health_server, daemon=True).start()
    
    print(">>> TradeVision AI Bot indítása...", flush=True)
    
    # 2. Bot futtatása végtelen ciklusban, hogy hiba esetén újrainduljon
    while True:
        try:
            # Megpróbáljuk leszedni a webhookot a tiszta pollinghoz
            bot.remove_webhook()
            
            # Ellenőrizzük a kapcsolatot
            me = bot.get_me()
            print(f">>> SIKER! Kapcsolódva mint: @{me.username}", flush=True)
            
            # Polling indítása
            bot.infinity_polling(timeout=90, long_polling_timeout=40)
        except Exception as e:
            print(f">>> Hálózati hiba, újrapróbálkozás 10 másodperc múlva... (Hiba: {e})", flush=True)
            time.sleep(10)
