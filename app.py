import os, telebot, threading, sqlite3, re, time, io, json, requests
from telebot import apihelper, types
from google import genai
from PIL import Image
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'DEMO') 
ADMIN_ID = 1578448812 

ALLOWED_CHATS = [-1002786610592] 

# IDE ÍRD BE A SAJÁT @BotFather LINKEDET!
WEB_APP_URL = "t.me/Tradevisionfxai_bot/Terminal" 

MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
analysis_storage = {}
media_groups = {}

# --- DATABASE SETUP ---
def init_db():
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS signals 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                      reasoning TEXT, status TEXT, confidence INTEGER)''')
        conn.commit()
        conn.close()
    except Exception as e:
        print(f">>> DB Error: {e}", flush=True)

def send_admin_log(text):
    print(f"🛠 [LOG]: {text}", flush=True) 
    try:
        bot.send_message(ADMIN_ID, f"🛠 **SYSTEM LOG:**\n{text}")
    except: pass

def is_authorized(message):
    if message.from_user.id == ADMIN_ID: return True
    if message.chat.id in ALLOWED_CHATS: return True
    return False

def extract_price(text, label):
    match = re.search(rf"{label}[:\s]*([\d,.]+)", text, re.IGNORECASE)
    if not match: match = re.search(rf"[\u2600-\u27BF].*?[:\s]*([\d,.]+)", text)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- ALPHA VANTAGE MOTOR ---
def get_current_price_av(sym):
    s = str(sym).upper().replace(" ", "").replace("/", "").replace("-", "")
    base, quote = s, "USD"
    if "XAU" in s or "GOLD" in s: base, quote = "XAU", "USD"
    elif s.endswith("USDT"): base, quote = s[:-4], "USDT"
    elif s.endswith("USD"): base, quote = s[:-3], "USD"
    elif len(s) == 6: base, quote = s[:3], s[3:]
    
    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        data = requests.get(url, timeout=10).json()
        if "Realtime Currency Exchange Rate" in data:
            return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    except: pass
    return None

# --- AUTO CHECKER ---
def auto_trade_checker():
    while True:
        try:
            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT id, symbol, type, sl, tp FROM signals WHERE status='PENDING'")
            trades = c.fetchall()
            if trades:
                for t_id, sym, t_type, sl, tp in trades:
                    price = get_current_price_av(sym)
                    if price:
                        new_status = None
                        if "BUY" in t_type:
                            if price >= tp: new_status = "WON"
                            elif price <= sl: new_status = "LOST"
                        else:
                            if price <= tp: new_status = "WON"
                            elif price >= sl: new_status = "LOST"
                        if new_status:
                            c.execute("UPDATE signals SET status=? WHERE id=?", (new_status, t_id))
                            send_admin_log(f"🎯 AUTO-CLOSE: {sym} -> {new_status}")
                conn.commit()
            conn.close()
        except: pass
        time.sleep(900)

# --- WEB SERVER ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/signals':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*') 
            self.end_headers()
            try:
                conn = sqlite3.connect('trades.db', check_same_thread=False)
                c = conn.cursor()
                c.execute("SELECT symbol, type, entry, sl, tp, reasoning, confidence, status FROM signals ORDER BY id DESC LIMIT 20")
                rows = c.fetchall()
                conn.close()
                signals = [{"asset": r[0], "type": r[1], "entry": r[2], "sl": r[3], "tp": r[4], "conf": r[6], "status": r[7]} for r in rows]
                self.wfile.write(json.dumps(signals).encode())
            except: self.wfile.write(b"[]")
        else:
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---

# 1. MANUÁLIS WIN/LOSS REAKCIÓ
@bot.message_handler(func=lambda m: m.reply_to_message is not None and m.text.lower() in ['win', 'won', 'lost', 'loss'])
def handle_manual_update(message):
    if not is_authorized(message): return
    new_status = "WON" if message.text.lower() in ['win', 'won'] else "LOST"
    orig_msg_id = str(message.reply_to_message.message_id)
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("UPDATE signals SET status=? WHERE msg_id=?", (new_status, orig_msg_id))
    conn.commit()
    conn.close()
    bot.reply_to(message, f"✅ HUB Updated: {new_status}")

# 2. START / HUB / CHECK COMMANDS
@bot.message_handler(commands=['start', 'hub'])
def start_cmd(message):
    if not is_authorized(message): return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📱 Open Terminal", url=WEB_APP_URL))
    bot.reply_to(message, "🚀 **TradeVision AI Hub**", reply_markup=markup)

@bot.message_handler(commands=['check'])
def check_cmd(message):
    if not is_authorized(message): return
    bot.reply_to(message, "🔍 Checking prices...")

# 3. KÉPKEZELÉS (MTF TÁMOGATÁSSAL)
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not is_authorized(message): return
    if message.media_group_id:
        if message.media_group_id not in media_groups:
            media_groups[message.media_group_id] = []
            threading.Timer(2.5, process_mtf_group, [message, message.media_group_id]).start()
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        media_groups[message.media_group_id].append(Image.open(io.BytesIO(downloaded)))
    else:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
        img = Image.open(io.BytesIO(downloaded))
        run_analysis(message, [img])

def process_mtf_group(message, group_id):
    images = media_groups.get(group_id)
    if images:
        run_analysis(message, images)
        del media_groups[group_id]

# 4. ANALÍZIS ÉS ADATBÁZIS MENTÉS
def run_analysis(message, images):
    status_msg = bot.reply_to(message, "⏳ *Analysing...*", parse_mode='Markdown')
    try:
        prompt = "You are an Elite Institutional Analyst. Output Part 1 (Summary) and Part 2 (Rationale) separated by '|||'."
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt] + images)
        summary, reasoning = response.text.split("|||", 1) if "|||" in response.text else (response.text, "...")
        
        entry = extract_price(summary, "ENTRY")
        sl = extract_price(summary, "STOP LOSS")
        tp = extract_price(summary, "TAKE PROFIT")
        sym_match = re.search(r"SYMBOL:\s*([\w/]+)", summary)
        sym = sym_match.group(1) if sym_match else "ASSET"
        
        conn = sqlite3.connect('trades.db')
        c = conn.cursor()
        c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status, confidence) VALUES (?,?,?,?,?,?,?,?,?)",
                  (str(status_msg.message_id), sym, "BUY" if "BUY" in summary.upper() else "SELL", entry, sl, tp, reasoning.strip(), "PENDING", 85))
        conn.commit()
        conn.close()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Read Confluence", callback_data=f"det_{status_msg.message_id}"))
        bot.edit_message_text(f"📊 **ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

# 5. DETAILED DESCRIPTION (CALLBACK) GOMB JAVÍTÁSA
@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    if not is_authorized(call.message): return
    msg_id = call.data.split("_")[1]
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT reasoning FROM signals WHERE msg_id = ?", (msg_id,))
    row = c.fetchone()
    conn.close()
    if row:
        bot.send_message(call.message.chat.id, f"🔍 **RATIONALE:**\n\n{row[0]}")
    else:
        bot.answer_callback_query(call.id, "Data not found.")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=auto_trade_checker, daemon=True).start()
    bot.infinity_polling()
