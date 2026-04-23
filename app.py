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
# Beillesztve az ID-d:
ADMIN_ID = "15781578448812" 
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'

apihelper.READ_TIMEOUT = 120
apihelper.CONNECT_TIMEOUT = 90

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
    """Küld egy üzenetet az adminnak a bot belső állapotáról"""
    try:
        bot.send_message(ADMIN_ID, f"🛠 **SYSTEM LOG:**\n{text}")
    except Exception as e:
        print(f"Admin log hiba: {e}")

# --- HELPER: SZÁMOK KINYERÉSE ---
def extract_price(text, label):
    """Kikeresi a számokat az AI válaszából (pl. SL: 4720.5 -> 4720.5)"""
    match = re.search(f"{label}:?\\s*([\\d,.]+)", text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- PRICE TRACKER (Háttérben futó figyelő) ---
def track_prices():
    while True:
        try:
            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT * FROM signals WHERE status = 'PENDING'")
            trades = c.fetchall()
            
            for t in trades:
                # Arany ticker a Yahoo Finance-en: GC=F
                ticker_sym = "GC=F" if "XAU" in t[1].upper() else t[1]
                ticker = yf.Ticker(ticker_sym)
                current_price = ticker.fast_info['last_price']
                
                # Egyszerűsített ellenőrzés (SELL esetén)
                if t[2] == "SELL":
                    if current_price <= t[5]: # TP elérése
                        send_admin_log(f"✅ **TP HIT!**\nSymbol: {t[1]}\nTarget: {t[5]}\nCurrent: {current_price}")
                        c.execute("UPDATE signals SET status = 'TP_HIT' WHERE id = ?", (t[0],))
                    elif current_price >= t[4]: # SL elérése
                        send_admin_log(f"❌ **SL HIT!**\nSymbol: {t[1]}\nStop: {t[4]}\nCurrent: {current_price}")
                        c.execute("UPDATE signals SET status = 'SL_HIT' WHERE id = ?", (t[0],))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Tracker hiba: {e}")
        time.sleep(300) # 5 percenként ellenőriz

# --- WEB SERVER (Életben tartáshoz) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"TradeVision AI v3.0: ONLINE")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    send_admin_log(f"Új interakció: {message.from_user.first_name} (@{message.from_user.username})")
    bot.reply_to(message, "🚀 **TradeVision AI v3.0 Professional**\nMonitoring active. Send a chart to begin.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"🖼 Kép érkezett tőle: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Initializing Neural Scanning...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Act as a Master Institutional Trader (SMC/ICT). Analyze this chart.\n"
            "MANDATORY FORMAT (Part 1):\n"
            "SYMBOL: [Asset name]\nSIGNAL: [BUY/SELL/NEUTRAL]\nENTRY: [Price]\nSL: [Price]\nTP: [Price]\nCONFIDENCE: [X%]\n"
            "|||\n"
            "PART 2: DETAILED RATIONALE (Order Blocks, FVG, Liquidity sweeps)."
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary, reasoning = res_text, "Detailed rationale stored."

        # Mentés az adatbázisba követéshez
        try:
            sym = "XAUUSD" # Alapértelmezett, ha nem találja
            sig = "SELL" if "SELL" in summary.upper() else "BUY"
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "SL")
            tp_p = extract_price(summary, "TP")
            
            if entry_p and sl_p and tp_p:
                conn = sqlite3.connect('trades.db', check_same_thread=False)
                c = conn.cursor()
                c.execute("INSERT INTO signals (symbol, type, entry, sl, tp, status) VALUES (?,?,?,?,?,'PENDING')",
                          (sym, sig, entry_p, sl_p, tp_p))
                conn.commit()
                conn.close()
                send_admin_log(f"📝 Trade mentve: {sym} {sig} | TP: {tp_p}")
        except Exception as db_e:
            send_admin_log(f"⚠️ Adatbázis mentési hiba: {db_e}")

        storage_key = f"{message.chat.id}_{status_msg.message_id}"
        analysis_storage[storage_key] = reasoning.strip()

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data=f"details_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **SIGNAL**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup, parse_mode='Markdown')

    except Exception as e:
        send_admin_log(f"❌ HIBA: {e}")
        bot.edit_message_text(f"❌ Analysis Error. Check System Log.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("details_"))
def callback_inline(call):
    key = f"{call.message.chat.id}_{call.data.split('_')[1]}"
    if key in analysis_storage:
        bot.send_message(call.message.chat.id, f"🔍 **TECHNICAL RATIONALE:**\n\n{analysis_storage[key]}", parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "Session expired.")

# --- STARTUP ---
if __name__ == "__main__":
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=track_prices, daemon=True).start()
    
    print(">>> TradeVision AI v3.0 is running...", flush=True)
    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(timeout=90)
        except Exception as e:
            time.sleep(5)
