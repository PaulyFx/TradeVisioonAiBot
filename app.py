import os, telebot, threading, psycopg2, re, time, io, json, requests
from telebot import apihelper, types
from google import genai
from PIL import Image
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'DEMO')
DATABASE_URL = os.getenv('DATABASE_URL') # A Supabase link a Renderről
ADMIN_ID = 1578448812 

ALLOWED_CHATS = [-1002786610592] 

# IDE ÍRD BE A SAJÁT @BotFather LINKEDET!
WEB_APP_URL = "https://t.me/Tradevisionfxai_bot/Terminal" 

MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
media_groups = {}

# --- DATABASE SETUP (POSTGRESQL / SUPABASE) ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Postgres-specifikus tábla létrehozás
        c.execute('''CREATE TABLE IF NOT EXISTS signals 
                     (id SERIAL PRIMARY KEY, 
                      msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                      reasoning TEXT, status TEXT, confidence INTEGER)''')
        conn.commit()
        c.close()
        conn.close()
        print(">>> Supabase Database Initialized.")
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
    match = re.search(rf"{label}[^\n\d]*([\d.,]+)", text, re.IGNORECASE)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- ALPHA VANTAGE MOTOR ---
def get_current_price_av(sym):
    s = str(sym).upper().replace("SYMBOL:", "").replace(" ", "").replace("/", "").replace("-", "")
    base, quote = s, "USD"
    if s == "GOLD" or "XAU" in s: base, quote = "XAU", "USD"
    elif s == "SILVER" or "XAG" in s: base, quote = "XAG", "USD"
    elif s.endswith("USDT"): base, quote = s[:-4], "USDT"
    elif s.endswith("USD"): base, quote = s[:-3], "USD"
    elif len(s) == 6: base, quote = s[:3], s[3:]
    
    url = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        req = requests.get(url, timeout=10)
        data = req.json()
        if "Realtime Currency Exchange Rate" in data:
            return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
    except: pass
    return None

def auto_trade_checker():
    while True:
        try:
            conn = get_db_connection()
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
                        elif "SELL" in t_type:
                            if price <= tp: new_status = "WON"
                            elif price >= sl: new_status = "LOST"
                        if new_status:
                            c.execute("UPDATE signals SET status=%s WHERE id=%s", (new_status, t_id))
                            send_admin_log(f"🎯 [AUTO-CLOSE]: {sym} -> {new_status}")
                conn.commit()
            c.close()
            conn.close()
        except: pass
        time.sleep(900)

# --- WEB SERVER & API ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/signals':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*') 
            self.end_headers()
            try:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT symbol, type, entry, sl, tp, reasoning, confidence, status FROM signals ORDER BY id DESC LIMIT 20")
                rows = c.fetchall()
                c.close()
                conn.close()
                signals = [{"asset": r[0], "type": r[1], "entry": r[2], "sl": r[3], "tp": r[4], "conf": r[6], "status": r[7]} for r in rows]
                self.wfile.write(json.dumps(signals).encode())
            except: self.wfile.write(b"[]")
        else:
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---

@bot.message_handler(func=lambda m: not is_authorized(m))
def unauthorized_access(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "🛑 **Access Denied. You are not authorized.**")

# 1. JAVÍTOTT MANUÁLIS WIN/LOSS REAKCIÓ (REPLY)
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_manual_reply(message):
    if not is_authorized(message): return
    text = message.text.lower()
    new_status = None
    if any(word in text for word in ['win', 'won', 'profit', 'tp']): new_status = "WON"
    elif any(word in text for word in ['lost', 'loss', 'sl']): new_status = "LOST"
        
    if new_status:
        orig_msg_id = str(message.reply_to_message.message_id)
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE signals SET status=%s WHERE msg_id=%s", (new_status, orig_msg_id))
            if c.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"✅ **Hub Updated!** Signal status: `{new_status}` 🚀")
            else:
                bot.reply_to(message, "⚠️ Signal not found in Supabase database.")
            c.close()
            conn.close()
        except Exception as e:
            bot.reply_to(message, f"❌ DB Error: {e}")
    else:
        handle_trading_chat(message)

# 2. COMMANDS
@bot.message_handler(commands=['start'])
def welcome(message):
    if not is_authorized(message): return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📱 Open TradeVision Hub", url=WEB_APP_URL))
    bot.reply_to(message, "🚀 **Welcome to TradeVision AI v3.9b Pro!** Let's conquer the markets together. 👇", reply_markup=markup)

@bot.message_handler(commands=['hub'])
def send_pinned_hub(message):
    if not is_authorized(message): return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📱 Launch AI Terminal", url=WEB_APP_URL))
    text = (
        "🌐 **TradeVision AI Hub**\n\n"
        "Access the Elite Trading Terminal, live market data, and AI confluence scanner here. "
        "Upload your charts inside the Hub for instant analysis.\n\n"
        "👇 *Click the button below to open.*"
    )
    msg = bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')
    try:
        bot.pin_chat_message(message.chat.id, msg.message_id)
    except: pass

@bot.message_handler(commands=['check'])
def manual_check(message):
    if not is_authorized(message): return
    bot.reply_to(message, "🔄 **Initiating Manual Price Check...**")

# 3. KÉPKEZELÉS (MTF)
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

# 4. ANALÍZIS ÉS MENTÉS
def run_analysis(message, images):
    status_msg = bot.reply_to(message, "⏳ *Scanning the markets...*", parse_mode='Markdown')
    try:
        mtf_context = f"I have provided {len(images)} charts. Perform MTF analysis. " if len(images) > 1 else ""
        prompt = (
            f"You are an Elite Institutional Analyst. {mtf_context}Use emojis for clarity. "
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
            "PART 2:\n[Detailed technical analysation]"
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt] + images)
        res_text = response.text
        if "|||" in res_text: summary, reasoning = res_text.split("|||", 1)
        else: summary, reasoning = res_text, "Check details."

        entry = extract_price(summary, "ENTRY")
        sl = extract_price(summary, "STOP LOSS")
        tp = extract_price(summary, "TAKE PROFIT")
        sym = re.search(r"SYMBOL:\s*([\w/]+)", summary).group(1) if re.search(r"SYMBOL:\s*([\w/]+)", summary) else "ASSET"
        conf_match = re.search(r'CONFIDENCE[:\s]*(\d+)', summary)
        conf_val = int(conf_match.group(1)) if conf_match else 85
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                  (str(status_msg.message_id), sym, "BUY" if "BUY" in summary.upper() else "SELL", entry, sl, tp, reasoning.strip(), "PENDING", conf_val))
        conn.commit()
        c.close()
        conn.close()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Read Confluence", callback_data=f"det_{status_msg.message_id}"))
        bot.edit_message_text(f"📊 **MARKET ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

# 5. AI CHAT ASSISZTENS
def handle_trading_chat(message):
    try:
        prompt = f"You are TradeVision AI, professional assistant. English with emojis: {message.text}"
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        bot.reply_to(message, response.text)
    except: pass

# 6. CALLBACK (GOMB)
@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    if not is_authorized(call.message): return
    msg_id = call.data.split("_")[1]
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT reasoning FROM signals WHERE msg_id = %s", (msg_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    if row: bot.send_message(call.message.chat.id, f"🔍 **AI RATIONALE:**\n\n{row[0]}")

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=auto_trade_checker, daemon=True).start()
    bot.infinity_polling()
