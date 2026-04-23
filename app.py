import os, telebot, threading, sqlite3, re, time, io
from telebot import apihelper, types
from google import genai
from PIL import Image
import yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = "15781578448812" 
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    # Kibővítjük a táblát a részletes elemzés tárolásához is
    c.execute('''CREATE TABLE IF NOT EXISTS signals 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                  reasoning TEXT, status TEXT)''')
    conn.commit()
    conn.close()

def send_admin_log(text):
    try: bot.send_message(ADMIN_ID, f"🛠 **LOG:** {text}")
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
        self.send_response(200); self.end_headers(); self.wfile.write(b"ACTIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🚀 **TradeVision AI v3.2 Pro** is online.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"📸 Kép érkezett: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *AI Analysis in progress...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        prompt = (
            "You are a Master SMC/ICT Trader. Analyze this chart. "
            "You MUST provide exactly two parts separated by '|||'.\n"
            "PART 1 (BRIEF):\nSYMBOL: [Asset]\nSIGNAL: [BUY/SELL]\nENTRY: [Price]\nSL: [Price]\nTP: [Price]\n"
            "|||\n"
            "PART 2 (DETAILED):\n[Provide deep SMC/ICT reasoning here]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        # Bontás és mentés
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary = res_text
            reasoning = "Check market structure manually. No details provided by AI."

        # Adatbázis mentés (hogy a gomb mindig működjön)
        try:
            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "SL")
            tp_p = extract_price(summary, "TP")
            sym = "ASSET"
            match_sym = re.search(r"SYMBOL:\s*(\w+)", summary)
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
        markup.add(types.InlineKeyboardButton(text="📖 Show Detailed Analysis", callback_data=f"det_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
        send_admin_log("✅ Elemzés kész.")

    except Exception as e:
        send_admin_log(f"❌ Error: {e}")
        bot.edit_message_text("⚠️ High demand. Try again in 1 minute.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    msg_id = call.data.split("_")[1]
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        bot.send_message(call.message.chat.id, f"🔍 **DETAILED RATIONALE:**\n\n{row[0]}")
    else:
        bot.answer_callback_query(call.id, "Data expired or not found. Please resend chart.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    bot.infinity_polling()
