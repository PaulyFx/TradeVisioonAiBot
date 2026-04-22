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

# Dictionary to store detailed analysis indexed by message_id
analysis_storage = {}

# --- WEB SERVER ---
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

# --- BOT LOGIC ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    welcome_text = (
        "🚀 **TradeVision AI v2.5 Pro**\n\n"
        "Send me a chart. I will provide a quick Signal (BUY/SELL/NO TRADE) "
        "and you can click for deep SMC/ICT reasoning."
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Institutional analysis triggered...", flush=True)
    status_msg = bot.reply_to(message, "⏳ *Analyzing Chart Patterns...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Act as a Master Institutional Trader (SMC/ICT Specialist). "
            "Analyze this chart and provide two distinct parts separated by '|||' keyword.\n\n"
            "PART 1 (BRIEF SUMMARY):\n"
            "SIGNAL: [BUY, SELL, NEUTRAL, or NO TRADE]\n"
            "ENTRY: [Level or Range]\n"
            "SL: [Level]\n"
            "TP: [Level]\n"
            "CONFIDENCE: [X%]\n"
            "NOTE: [If NO TRADE, explain why in 1 sentence, otherwise leave empty]\n\n"
            "|||\n\n"
            "PART 2 (DETAILED REASONING):\n"
            "[Provide a full SMC/ICT breakdown: Market Structure, Liquidity, Order Blocks, and FVG]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        full_text = response.text
        
        # Splitting the content
        if "|||" in full_text:
            summary, reasoning = full_text.split("|||", 1)
        else:
            summary = full_text
            reasoning = "Detailed analysis unavailable for this specific image."

        # Use the message_id as key to ensure multiple users don't mix up analyses
        storage_key = f"{message.chat.id}_{status_msg.message_id}"
        analysis_storage[storage_key] = reasoning.strip()

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data=f"details_{status_msg.message_id}"))

        final_summary = f"📊 **MARKET SIGNAL**\n\n{summary.strip()}"
        
        try:
            bot.edit_message_text(final_summary, message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.edit_message_text(final_summary, message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode=None)

    except Exception as e:
        print(f"!!! Error: {e}", flush=True)
        bot.edit_message_text(f"❌ Analysis failed: `{str(e)[:100]}`", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("details_"))
def callback_inline(call):
    chat_id = call.message.chat.id
    msg_id = call.data.split("_")[1]
    storage_key = f"{chat_id}_{msg_id}"
    
    if storage_key in analysis_storage:
        detail_text = f"🔍 **TECHNICAL RATIONALE (SMC/ICT)**\n\n{analysis_storage[storage_key]}"
        try:
            bot.send_message(chat_id, detail_text, parse_mode='Markdown')
        except:
            bot.send_message(chat_id, detail_text, parse_mode=None)
        
        # Optional: Delete from memory after use to save RAM
        # del analysis_storage[storage_key]
    else:
        bot.answer_callback_query(call.id, "Details expired. Please resend the chart.")

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
