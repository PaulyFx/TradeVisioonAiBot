import os
import telebot
from telebot import apihelper, types
from google import genai
from PIL import Image
import io
import time
import threading
import sqlite3
import re
import yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIGURATION ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = "15781578448812" 
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
analysis_storage = {}

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, status TEXT)''')
    conn.commit()
    conn.close()

# --- ADMIN LOG SYSTEM ---
def send_admin_log(text):
    try:
        bot.send_message(ADMIN_ID, f"🛠 **SYSTEM LOG:**\n{text}")
    except Exception as e:
        print(f"Log error: {e}")

# --- HELPER: PRICE EXTRACTION ---
def extract_price(text, label):
    # Keresi a számokat rugalmasabban (pl: TP:4700 vagy TP 4700.5)
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- PRICE TRACKER THREAD ---
def track_prices():
    while True:
        try:
            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT * FROM signals WHERE status = 'PENDING'")
            trades = c.fetchall()
            
            for t in trades:
                # Arany ticker a Yahoo-n
                ticker_sym = "GC=F" if "XAU" in t[1].upper() else t[1]
                ticker = yf.Ticker(ticker_sym)
                current_price = ticker.fast_info['last_price']
                
                if t[2] == "SELL":
                    if current_price <= t[5]: # TP
                        send_admin_log(f"✅ **TP HIT!**\nAsset: {t[1]}\nTarget: {t[5]}\nCurrent: {current_price}")
                        c.execute("UPDATE signals SET status = 'TP_HIT' WHERE id = ?", (t[0],))
                    elif current_price >= t[4]: # SL
                        send_admin_log(f"❌ **SL HIT!**\nAsset: {t[1]}\nStop: {t[4]}\nCurrent: {current_price}")
                        c.execute("UPDATE signals SET status = 'SL_HIT' WHERE id = ?", (t[0],))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Tracker err: {e}")
        time.sleep(300)

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"TradeVision v3.1 ACTIVE")
    def log_message(self, format, *args): return

def run_health_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler)
    server.serve_forever()

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    send_admin_log(f"User started: {message.from_user.first_name}")
    bot.reply_to(message, "🚀 **TradeVision AI v3.1 Pro**\nSend a chart to begin.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"📸 New image from: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Initializing AI Analysis...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Analyze chart (SMC/ICT). SYMBOL, SIGNAL, ENTRY, SL, TP, CONFIDENCE. "
            "Separate with '|||'. PART 2: Rationale."
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary, reasoning = res_text, "Rationale stored."

        # Database saving
        try:
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "SL")
            tp_p = extract_price(summary, "TP")
            
            if entry_p and sl_p and tp_p:
                conn = sqlite3.connect('trades.db', check_same_thread=False)
                c = conn.cursor()
                c.execute("INSERT INTO signals (symbol, type, entry, sl, tp, status) VALUES ('XAUUSD', ?, ?, ?, ?, 'PENDING')",
                          ("SELL" if "SELL" in summary.upper() else "BUY", entry_p, sl_p, tp_p))
                conn.commit()
                conn.close()
                send_admin_log(f"💾 Trade saved to DB: {entry_p} / {tp_p}")
        except Exception as db_e:
            send_admin_log(f"⚠️ DB Error: {db_e}")

        storage_key = f"{message.chat.id}_{status_msg.message_id}"
        analysis_storage[storage_key] = reasoning.strip()

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data=f"details_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode='Markdown')
        send_admin_log("✅ Analysis complete.")

    except Exception as e:
        error_str = str(e)
        if "503" in error_str or "overloaded" in error_str.lower():
            send_admin_log("⚠️ AI Overloaded (503). User notified.")
            bot.edit_message_text("⚠️ **AI is currently overloaded.** Please try again in a few moments.", message.chat.id, status_msg.message_id, parse_mode='Markdown')
        else:
            send_admin_log(f"❌ Critical Error: {e}")
            bot.edit_message_text(f"❌ Analysis Error. System Log updated.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("details_"))
def callback_inline(call):
    key = f"{call.message.chat.id}_{call.data.split('_')[1]}"
    if key in analysis_storage:
        bot.send_message(call.message.chat.id, f"🔍 **RATIONALE:**\n\n{analysis_storage[key]}", parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "Session expired.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=track_prices, daemon=True).start()
    send_admin_log("🚀 TradeVision v3.1 successfully started!")
    bot.infinity_polling()
