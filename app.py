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

# --- DATABASE SETUP ---
def init_db():
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        # Tábla létrehozása (id, msg_id, symbol, type, entry, sl, tp, reasoning, status)
        c.execute('''CREATE TABLE IF NOT EXISTS signals 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                      reasoning TEXT, status TEXT)''')
        conn.commit()
        conn.close()
        print(">>> Database initialized successfully.", flush=True)
    except Exception as e:
        print(f">>> DB Error: {e}", flush=True)

def send_admin_log(text):
    full_log = f"🛠 [LOG]: {text}"
    print(full_log, flush=True) 
    try:
        bot.send_message(ADMIN_ID, full_log)
    except: pass

def extract_price(text, label):
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"TradeVision v3.7 ACTIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI v3.7 Elite**\nDatabase fix applied. Send a chart to begin.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"📸 Új elemzés tőle: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Analyzing market structure...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "Analyze this chart. You MUST use '|||' to separate Part 1 and Part 2.\n"
            "PART 1: SYMBOL, SIGNAL, ENTRY, SL, TP, CONFIDENCE, PATTERNS.\n"
            "|||\n"
            "PART 2: DETAILED CONFLUENCE (SMC, ICT, Price Action breakdown)."
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary, reasoning = res_text, "Rationale analyzed."

        # JAVÍTOTT ADATBÁZIS MENTÉS (Pontosan 8 binding a 8 oszlophoz)
        try:
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "SL")
            tp_p = extract_price(summary, "TP")
            sym = "ASSET"
            match_sym = re.search(r"SYMBOL:\s*([\w/]+)", summary)
            if match_sym: sym = match_sym.group(1)

            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            # Itt volt a hiba: 8 kérdőjel kell a 8 oszlopnak
            c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status) VALUES (?,?,?,?,?,?,?,?)",
                      (str(status_msg.message_id), sym, "SELL" if "SELL" in summary.upper() else "BUY", entry_p, sl_p, tp_p, reasoning.strip(), "PENDING"))
            conn.commit()
            conn.close()
            send_admin_log(f"✅ Trade mentve az adatbázisba. (ID: {status_msg.message_id})")
        except Exception as db_e:
            send_admin_log(f"⚠️ DB Mentési hiba: {db_e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Confluence", callback_data=f"det_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **TRADING SIGNAL**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)

    except Exception as e:
        send_admin_log(f"❌ HIBA: {e}")
        bot.edit_message_text("⚠️ AI overloaded. Please retry.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    msg_id = call.data.split("_")[1]
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
        row = c.fetchone()
        conn.close()
        
        if row and row[0]:
            bot.send_message(call.message.chat.id, f"🔍 **TECHNICAL CONFLUENCE:**\n\n{row[0]}")
        else:
            bot.answer_callback_query(call.id, "Details not found. Try resending the chart.")
    except Exception as e:
        bot.answer_callback_query(call.id, "Error loading data.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    send_admin_log("🚀 TradeVision v3.7 indítása...")
    bot.infinity_polling()
