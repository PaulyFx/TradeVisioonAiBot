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
# Using the high-quota model we identified
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview' 

apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Dictionary to store detailed analysis temporarily
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
        "Send me a trading chart, and I will perform a deep technical analysis using:\n"
        "• Smart Money Concepts (SMC) & ICT\n"
        "• Advanced Chart & Candle Patterns\n"
        "• Trendline & Breakout Analysis\n"
        "• Dynamic Support/Resistance"
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
        
        # Enhanced Professional Prompt
        prompt = (
            "Act as a Master Institutional Trader. Analyze this chart using SMC, ICT, and Price Action. "
            "Look for Order Blocks, Fair Value Gaps (FVG), Liquidity sweeps, and advanced Candle/Chart patterns. "
            "STRICTLY follow this format for your output:\n\n"
            "SIGNAL: [BUY / SELL / NEUTRAL]\n"
            "ENTRY: [Price level]\n"
            "SL: [Price level]\n"
            "TP: [Price level]\n"
            "CONFIDENCE: [0-100%]\n"
            "---REASONING--- \n"
            "[Detailed technical explanation of patterns, SMC/ICT context, and why this signal was generated]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        full_analysis = response.text
        
        # Split summary and reasoning
        if "---REASONING---" in full_analysis:
            summary, reasoning = full_analysis.split("---REASONING---", 1)
        else:
            summary, reasoning = full_analysis, "Detailed technical data analyzed."

        # Store reasoning for the "Read More" button
        chat_id = message.chat.id
        analysis_storage[chat_id] = reasoning.strip()

        # Create "Read More" button
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📖 Show Detailed Analysis", callback_query_data="show_details"))

        bot.edit_message_text(
            chat_id=chat_id,
            message_id=status_msg.message_id,
            text=f"📊 **TRADING SIGNAL**\n\n{summary.strip()}",
            reply_markup=markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        print(f"!!! Analysis Error: {e}", flush=True)
        bot.edit_message_text(f"❌ Error during analysis: `{str(e)[:100]}`", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "show_details")
def callback_inline(call):
    chat_id = call.message.chat.id
    if chat_id in analysis_storage:
        details = analysis_storage[chat_id]
        bot.send_message(chat_id, f"🔍 **DETAILED RATIONALE:**\n\n{details}", parse_mode='Markdown')
        # Remove from storage after showing
        del analysis_storage[chat_id]
    else:
        bot.answer_callback_query(call.id, "Analysis expired. Please send a new chart.")

# --- STARTUP ---
if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    print(">>> TradeVision AI v2.0 Professional Starting...", flush=True)
    
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(timeout=90)
        except Exception as e:
            time.sleep(5)
