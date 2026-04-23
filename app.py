import os, telebot, threading, sqlite3, re, time, io
from telebot import apihelper, types
from google import genai
from PIL import Image
import yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = 1578448812 
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
analysis_storage = {}

# --- DATABASE SETUP ---
def init_db():
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS signals 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                      reasoning TEXT, status TEXT)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f">>> DB Error: {e}", flush=True)

def send_admin_log(text):
    full_log = f"🛠 [LOG]: {text}"
    print(full_log, flush=True) 
    try:
        bot.send_message(ADMIN_ID, full_log)
    except Exception as e:
        print(f"!!! Telegram Log Error: {e}", flush=True)

def extract_price(text, label):
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"TradeVision v3.5 Full Spectrum ACTIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    send_admin_log(f"User Start: {message.from_user.first_name}")
    bot.reply_to(message, "🚀 **TradeVision AI v3.5 Full Spectrum**\nSMC/ICT + Price Action + Patterns active.\n\nSend a chart to begin.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"📸 Image analysis triggered by: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Deep Scanning Structure, Patterns & Candles...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Act as a Master Quantitative Analyst & Price Action Expert. Analyze this chart for an elite trading setup.\n\n"
            "1. MARKET STRUCTURE: Identify BOS (Break of Structure), CHoCH (Change of Character), and current trend (Bullish/Bearish/Sideways).\n"
            "2. CHART PATTERNS: Look for Head & Shoulders, Double Tops/Bottoms, Triangles, Wedges, or Flags.\n"
            "3. CANDLESTICK PATTERNS: Identify key candles like Pin Bars, Engulfing patterns, Morning/Evening Stars, or Dojis at key levels.\n"
            "4. INSTITUTIONAL CONTEXT: Confirm with SMC/ICT (Order Blocks, FVG, Liquidity).\n"
            "5. MACRO/FUNDAMENTALS: Incorporate current market sentiment.\n\n"
            "STRICT FORMAT (Part 1):\n"
            "SYMBOL: [Asset Name]\nSIGNAL: [BUY/SELL/NO TRADE]\nENTRY: [Price]\nSL: [Price]\nTP: [Price]\nCONFIDENCE: [X%]\n"
            "PATTERNS FOUND: [List specific chart/candle patterns detected]\n"
            "|||\n"
            "PART 2 (DETAILED CONFLUENCE):\n[Full breakdown of Market Structure, SMC logic, and how the patterns confirm the signal]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary = res_text
            reasoning = "Check confluence manually."

        # DB Mentés
        try:
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "SL")
            tp_p = extract_price(summary, "TP")
            sym = "ASSET"
            match_sym = re.search(r"SYMBOL:\s*([\w/]+)", summary)
            if match_sym: sym = match_sym.group(1)

            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status) VALUES (?,?,?,?,?,?,?,'PENDING')",
                      (str(status_msg.message_id), sym, "SELL" if "SELL" in summary.upper() else "BUY", entry_p, sl_p, tp_p, reasoning.strip()))
            conn.commit()
            conn.close()
        except Exception as e:
            send_admin_log(f"⚠️ DB Error: {e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Confluence", callback_data=f"det_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **FULL SPECTRUM ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
        send_admin_log("✅ Analysis complete.")

    except Exception as e:
        error_str = str(e)
        if "503" in error_str or "overloaded" in error_str.lower():
            bot.edit_message_text("⚠️ **AI is currently overloaded.** Please try again in 1 minute.", message.chat.id, status_msg.message_id)
        else:
            send_admin_log(f"❌ Error: {e}")
            bot.edit_message_text("❌ Technical error. Please retry.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    msg_id = call.data.split("_")[1]
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        bot.send_message(call.message.chat.id, f"🔍 **TECHNICAL CONFLUENCE:**\n\n{row[0]}")
    else:
        bot.answer_callback_query(call.id, "Data expired.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    send_admin_log("🚀 TradeVision v3.5 Full Spectrum started!")
    bot.infinity_polling()
