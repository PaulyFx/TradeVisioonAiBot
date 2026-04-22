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

# Dictionary to store detailed analysis
analysis_storage = {}

# --- HEALTH CHECK SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI: ACTIVE")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 7860))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- BOT LOGIC ---
@bot.message_handler(commands=['start', 'help'])
def welcome(message):
    welcome_text = (
        "🚀 **TradeVision AI v2.0 Professional**\n\n"
        "Send me a trading chart for a deep institutional analysis:\n"
        "• SMC (Order Blocks, Breakers, Mitigations)\n"
        "• ICT (FVG, Liquidity Pools, Killzones)\n"
        "• Advanced Price Action & Patterns"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(">>> Analyzing new chart...", flush=True)
    status_msg = bot.reply_to(message, "⏳ *Processing market data...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Act as a Master Institutional Trader. Analyze this chart using SMC and ICT concepts. "
            "Identify Liquidity, Order Blocks, FVGs, and Trend. "
            "Output format:\n\n"
            "SIGNAL: [BUY / SELL / NEUTRAL]\n"
            "ENTRY: [Price]\n"
            "SL: [Price]\n"
            "TP: [Price]\n"
            "CONFIDENCE: [X%]\n"
            "---REASONING--- \n"
            "[Detailed SMC/ICT breakdown]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        full_analysis = response.text
        
        if "---REASONING---" in full_analysis:
            summary, reasoning = full_analysis.split("---REASONING---", 1)
        else:
            summary, reasoning = full_analysis, "Detailed technical data analyzed."

        chat_id = message.chat.id
        analysis_storage[chat_id] = reasoning.strip()

        # CORRECTED BUTTON KEYWORD: callback_data
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data="show_details"))

        text_to_send = f"📊 **TRADING SIGNAL**\n\n{summary.strip()}"
        
        try:
            bot.edit_message_text(text_to_send, chat_id, status_msg.message_id, reply_markup=markup, parse_mode='Markdown')
        except:
            bot.edit_message_text(text_to_send, chat_id, status_msg.message_id, reply_markup=markup, parse_mode=None)

    except Exception as e:
        print(f"!!! Error: {e}", flush=True)
        bot.edit_message_text(f"❌ Error: `{str(e)[:100]}`", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "show_details")
def callback_inline(call):
    chat_id = call.message.chat.id
    if chat_id in analysis_storage:
        details = f"🔍 **DETAILED RATIONALE:**\n\n{analysis_storage[chat_id]}"
        try:
            bot.send_message(chat_id, details, parse_mode='Markdown')
        except:
            bot.send_message(chat_id, details, parse_mode=None)
    else:
        bot.answer_callback_query(call.id, "Session expired. Send chart again.")

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
