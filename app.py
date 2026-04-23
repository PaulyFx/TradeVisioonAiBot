import os
import telebot
from telebot import apihelper, types
from google import genai
from PIL import Image
import io
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview' 

apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
analysis_storage = {}

# --- IMPROVED WEB SERVER FOR RENDER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Ez a rész válaszol 200 OK-val mindenre, így a Cron-job is örülni fog
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI: ACTIVE AND AWAKE")
    
    def log_message(self, format, *args): return

def run_health_server():
    # Render alapértelmezett portja a 10000, ha nincs más megadva
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    print(f">>> Health Server started on port {port}", flush=True)
    server.serve_forever()

# --- BOT LOGIC ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI v2.5 Pro** is active! Send a chart for analysis.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status_msg = bot.reply_to(message, "⏳ *Analyzing Market Data...*", parse_mode='Markdown')
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Act as a Master Institutional Trader (SMC/ICT). Analyze this chart and separate with '|||'.\n"
            "PART 1: SIGNAL, ENTRY, SL, TP, CONFIDENCE, NOTE.\n|||\n"
            "PART 2: DETAILED REASONING (Order Blocks, FVG, Liquidity)."
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        if "|||" in response.text:
            summary, reasoning = response.text.split("|||", 1)
        else:
            summary, reasoning = response.text, "Technical rationale analyzed."

        storage_key = f"{message.chat.id}_{status_msg.message_id}"
        analysis_storage[storage_key] = reasoning.strip()

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data=f"details_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **SIGNAL**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        bot.edit_message_text(f"❌ Error: `{str(e)[:100]}`", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("details_"))
def callback_inline(call):
    storage_key = f"{call.message.chat.id}_{call.data.split('_')[1]}"
    if storage_key in analysis_storage:
        bot.send_message(call.message.chat.id, f"🔍 **DETAILED RATIONALE:**\n\n{analysis_storage[storage_key]}", parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "Session expired.")

# --- STARTUP ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(timeout=90)
        except Exception as e:
            time.sleep(5)
