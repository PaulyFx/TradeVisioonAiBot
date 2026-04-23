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

# IDE ÍRD BE A CSOPORTOD ID-JÁT (pl: -100123456789)
# Addig is az Admin (Te) privátban tudod használni.
ALLOWED_CHATS = [-1002786610592] 

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
    except: pass

# --- SECURITY CHECK ---
def is_authorized(message):
    # Admin mindig hozzáfér
    if message.from_user.id == ADMIN_ID:
        return True
    # Csoport ellenőrzés
    if message.chat.id in ALLOWED_CHATS:
        return True
    return False

def extract_price(text, label):
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if not match:
        match = re.search(rf"[\u2600-\u27BF].*?[:\s]*([\d,.]+)", text)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"TradeVision v3.9 ACTIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---

# Illetéktelenek kezelése
@bot.message_handler(func=lambda m: not is_authorized(m))
def unauthorized_access(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "🛑 **Access Denied.** This is a private AI terminal.")
    # Segít megtudni a csoport ID-t a logban
    send_admin_log(f"⚠️ Unauthorized access! Chat ID: {message.chat.id} | User: {message.from_user.first_name}")

@bot.message_handler(commands=['start'])
def welcome(message):
    if not is_authorized(message): return
    bot.reply_to(message, "🚀 **TradeVision AI v3.9b Pro** 🚀\nSecurity active.\nVision Brain active.\nClosed Beta.\nSignals are not 100%!\nDo Your Own Research!\nSend a chart to begin.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not is_authorized(message): return
    
    send_admin_log(f"📸 Új elemzés tőle: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Analysing the picture...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        # PONTOSAN A v3.8 PROMPTJA
        prompt = (
            "You are an Elite Institutional Analyst. Use emojis for clarity. "
            "You MUST separate Part 1 and Part 2 with '|||'.\n\n"
            "PART 1 (Output exactly in this style):\n"
            "🏷️ SYMBOL: [Asset]\n"
            "🚦 SIGNAL: [BUY/SELL/NEUTRAL]\n"
            "🎯 ENTRY: [Price]\n"
            "🛑 STOP LOSS: [Price]\n"
            "💰 TAKE PROFIT: [Price]\n"
            "⚡ CONFIDENCE: [X%]\n"
            "🧩 PATTERNS: [Specific patterns found]\n"
            "|||\n"
            "PART 2:\n"
            "[Detailed technical analysation using Mutliple Strategy.]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary, reasoning = res_text, "Check details."

        # DB Mentés
        try:
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "STOP LOSS")
            tp_p = extract_price(summary, "TAKE PROFIT")
            sym = "ASSET"
            match_sym = re.search(r"SYMBOL:\s*([\w/]+)", summary)
            if match_sym: sym = match_sym.group(1)

            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status) VALUES (?,?,?,?,?,?,?,?)",
                      (str(status_msg.message_id), sym, "SELL" if "SELL" in summary.upper() else "BUY", entry_p, sl_p, tp_p, reasoning.strip(), "PENDING"))
            conn.commit()
            conn.close()
        except Exception as db_e:
            send_admin_log(f"⚠️ DB Saving Error: {db_e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Read Detailed Confluence", callback_data=f"det_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **MARKET ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)

    except Exception as e:
        send_admin_log(f"❌ HIBA: {e}")
        bot.edit_message_text("⚠️ System is overloaded. Please retry but don't spam me.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    if not is_authorized(call.message): return
    
    msg_id = call.data.split("_")[1]
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
        row = c.fetchone()
        conn.close()
        if row:
            bot.send_message(call.message.chat.id, f"🔍 **TECHNICAL RATIONALE:**\n\n{row[0]}")
        else:
            bot.answer_callback_query(call.id, "Data not found.")
    except:
        bot.answer_callback_query(call.id, "Error loading data.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    send_admin_log("🚀 TradeVision v3.9 Gatekeeper started!")
    bot.infinity_polling()
