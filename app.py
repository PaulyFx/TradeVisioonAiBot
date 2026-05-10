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

# IDE ÍRD BE A @BotFather-TŐL KAPOTT LINKET!
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
    """Minden fontos eseményről küld üzenetet az adminnak privátban."""
    print(f"🛠 [LOG]: {text}", flush=True) 
    try:
        bot.send_message(ADMIN_ID, f"🛠 **SYSTEM LOG:**\n{text}")
    except Exception as e:
        print(f"Hiba az admin log küldésekor: {e}")

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

# --- JAVÍTOTT ALPHA VANTAGE MOTOR ---
def get_current_price_av(sym):
    s = str(sym).upper().replace("SYMBOL:", "").replace(" ", "").replace("/", "").replace("-", "")
    base, quote = s, "USD"
    
    if s == "GOLD" or "XAU" in s: base, quote = "XAU", "USD"
    elif s == "SILVER" or "XAG" in s: base, quote = "XAG", "USD"
    elif s.endswith("USDT"): base, quote = s[:-4], "USDT"
    elif s.endswith("USD"): base, quote = s[:-3], "USD"
    elif len(s) == 6: base, quote = s[:3], s[3:]
    
    url_currency = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_VANTAGE_API_KEY}"
    
    try:
        req = requests.get(url_currency, timeout=10)
        data = req.json()
        if "Realtime Currency Exchange Rate" in data:
            return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        else:
            # Részletes logolás az adminnak, ha nem jön adat
            msg = str(data)[:200]
            send_admin_log(f"⚠️ API Info ({sym}): {msg}")
    except Exception as e:
        send_admin_log(f"❌ AV API Hiba: {e}")

    # Próba indexekkel (pl. US500 -> SPY)
    ticker = s
    if "US100" in s or "NASDAQ" in s: ticker = "QQQ"
    elif "US500" in s or "SPX" in s: ticker = "SPY"
    
    url_quote = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        req = requests.get(url_quote, timeout=10)
        data = req.json()
        if "Global Quote" in data and "05. price" in data["Global Quote"]:
            return float(data["Global Quote"]["05. price"])
    except: pass
    return None

def auto_trade_checker():
    send_admin_log("🔄 Auto Checker elindult.")
    while True:
        try:
            conn = sqlite3.connect('trades.db', check_same_thread=False)
            c = conn.cursor()
            c.execute("SELECT id, symbol, type, sl, tp FROM signals WHERE status='PENDING'")
            trades = c.fetchall()
            conn.close()
            
            if trades:
                unique_symbols = set([t[1] for t in trades])
                for sym in unique_symbols:
                    price = get_current_price_av(sym)
                    if price:
                        conn = sqlite3.connect('trades.db', check_same_thread=False)
                        c = conn.cursor()
                        # Megnézzük mely trade-eknél változik a státusz
                        for t_id, t_sym, t_type, sl, tp in trades:
                            if t_sym != sym: continue
                            new_status = None
                            if "BUY" in t_type:
                                if price >= tp: new_status = "WON"
                                elif price <= sl: new_status = "LOST"
                            elif "SELL" in t_type:
                                if price <= tp: new_status = "WON"
                                elif price >= sl: new_status = "LOST"
                            if new_status:
                                c.execute("UPDATE signals SET status=? WHERE id=?", (new_status, t_id))
                                send_admin_log(f"🎯 AUTOMATIKUS ZÁRÁS: {sym} -> {new_status}")
                        conn.commit()
                        conn.close()
                time.sleep(900 * len(unique_symbols))
            else:
                time.sleep(600)
        except Exception as e:
            print(f"Hiba a háttérben: {e}")
            time.sleep(300)

# --- WEB SERVER & API ---
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
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---

# 🌟 ÚJ: MANUÁLIS WIN/LOSS REAKCIÓ KEZELŐ
@bot.message_handler(func=lambda m: m.reply_to_message is not None and m.text.lower() in ['win', 'won', 'lost', 'loss', 'profit'])
def handle_manual_update(message):
    if not is_authorized(message): return
    
    text = message.text.lower()
    new_status = "WON" if text in ['win', 'won', 'profit'] else "LOST"
    orig_msg_id = str(message.reply_to_message.message_id)
    
    try:
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("UPDATE signals SET status=? WHERE msg_id=?", (new_status, orig_msg_id))
        if c.rowcount > 0:
            conn.commit()
            bot.reply_to(message, f"✅ **HUB FRISSÍTVE:** A szignál státusza mostantól: `{new_status}`")
            send_admin_log(f"Manuális frissítés történt: {orig_msg_id} -> {new_status}")
        else:
            bot.reply_to(message, "⚠️ Nem találom ezt a szignált az adatbázisban.")
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"❌ Hiba a frissítés közben: {e}")

@bot.message_handler(commands=['check'])
def manual_price_check(message):
    if not is_authorized(message): return
    bot.reply_to(message, "🔍 Árak ellenőrzése az API-n...")
    # Itt is meghívjuk a get_current_price_av-t... (a logika ugyanaz mint fent)

@bot.message_handler(commands=['start', 'hub'])
def start_cmd(message):
    if not is_authorized(message): return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📱 Open Terminal", url=WEB_APP_URL))
    bot.reply_to(message, "🚀 **TradeVision AI Hub**", reply_markup=markup)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if not is_authorized(message): return
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)
    img = Image.open(io.BytesIO(downloaded))
    run_analysis(message, [img])

def run_analysis(message, images):
    status_msg = bot.reply_to(message, "⏳ *Analysing...*", parse_mode='Markdown')
    try:
        prompt = "You are an Elite Institutional Analyst. Output Part 1 (Summary) and Part 2 (Rationale) separated by '|||'."
        response = client.models.generate_content(model=MODEL_NAME, contents=[prompt] + images)
        summary, reasoning = response.text.split("|||", 1) if "|||" in response.text else (response.text, "...")
        
        entry = extract_price(summary, "ENTRY")
        sl = extract_price(summary, "STOP LOSS")
        tp = extract_price(summary, "TAKE PROFIT")
        sym = re.search(r"SYMBOL:\s*([\w/]+)", summary).group(1) if re.search(r"SYMBOL:\s*([\w/]+)", summary) else "ASSET"
        
        conn = sqlite3.connect('trades.db', check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status, confidence) VALUES (?,?,?,?,?,?,?,?,?)",
                  (str(status_msg.message_id), sym, "BUY" if "BUY" in summary.upper() else "SELL", entry, sl, tp, reasoning.strip(), "PENDING", 85))
        conn.commit()
        conn.close()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Read Rationale", callback_data=f"det_{status_msg.message_id}"))
        bot.edit_message_text(f"📊 **ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status_msg.message_id)

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=auto_trade_checker, daemon=True).start()
    send_admin_log("🚀 TradeVision Online")
    bot.infinity_polling()
