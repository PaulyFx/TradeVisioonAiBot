import os, telebot, threading, sqlite3, re, time, io
from telebot import apihelper, types
from google import genai
from PIL import Image
import yfinance as yf
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ADMIN_ID = 15781578448812 # Számként adtam meg, ez biztosabb
MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                  reasoning TEXT, status TEXT)''')
    conn.commit()
    conn.close()
    print(">>> Database initialized.", flush=True)

def send_admin_log(text):
    """Admin log küldése és kiírása a konzolra is hibakereséshez"""
    print(f"LOG: {text}", flush=True)
    try:
        bot.send_message(ADMIN_ID, f"🛠 **SYSTEM LOG:**\n{text}")
    except Exception as e:
        print(f"!!! Nem sikerült log üzenetet küldeni Telegramon: {e}", flush=True)

def extract_price(text, label):
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"TradeVision v3.3 LIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    if message.from_user.id == ADMIN_ID:
        send_admin_log("Admin bejelentkezett a botba.")
    bot.reply_to(message, "🚀 **TradeVision AI v3.3 Elite**\n\nAdvanced Multi-Strategy & Fundamental Analysis active.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    send_admin_log(f"📸 Kép érkezett tőle: {message.from_user.first_name}")
    status_msg = bot.reply_to(message, "⏳ *Advanced Market Scan (SMC/ICT + Macro)...*", parse_mode='Markdown')
    
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        
        # BRUTÁL PROMPT: SMC, ICT, Wyckoff, Elliott + Fundamentumok
        prompt = (
            "You are an Elite Hedge Fund Strategist. Analyze this chart using a HYBRID approach.\n\n"
            "1. PRIMARY: SMC/ICT (Order Blocks, FVG, Liquidity Sweeps, Market Structure).\n"
            "2. SECONDARY: Wyckoff (Accumulation/Distribution) and Elliott Wave context.\n"
            "3. FUNDAMENTALS: Mention current high-impact news context (CPI, FOMC, NFP) and sentiment affecting this asset.\n\n"
            "MANDATORY FORMAT (Follow strictly):\n"
            "SYMBOL: [Asset]\nSIGNAL: [BUY/SELL/NO TRADE]\nENTRY: [Price]\nSL: [Price]\nTP: [Price]\nCONFIDENCE: [X%]\n"
            "FUNDAMENTAL NOTE: [Current news impact]\n"
            "|||\n"
            "DETAILED CONFLUENCE:\n[Deep breakdown of SMC, ICT and Wyckoff findings]"
        )
        
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt, img])
        res_text = response.text
        
        if "|||" in res_text:
            summary, reasoning = res_text.split("|||", 1)
        else:
            summary = res_text
            reasoning = "Check details manually. Formatting error in AI response."

        # DB MENTÉS
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
            send_admin_log(f"💾 Adatbázisba mentve: {sym}")
        except Exception as e:
            send_admin_log(f"⚠️ DB hiba: {e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Detailed Confluence", callback_data=f"det_{status_msg.message_id}"))

        bot.edit_message_text(f"📊 **HYBRID ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
        send_admin_log("✅ Elemzés sikeresen kiküldve.")

    except Exception as e:
        send_admin_log(f"❌ HIBA: {e}")
        bot.edit_message_text("⚠️ Market data unavailable. Please retry in 1 minute.", message.chat.id, status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    msg_id = call.data.split("_")[1]
    conn = sqlite3.connect('trades.db', check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        bot.send_message(call.message.chat.id, f"🔍 **TECHNICAL RATIONALE:**\n\n{row[0]}")
    else:
        bot.answer_callback_query(call.id, "Details expired. Resend chart.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    send_admin_log("🚀 TradeVision v3.3 ELITE indítása...")
    bot.infinity_polling()
