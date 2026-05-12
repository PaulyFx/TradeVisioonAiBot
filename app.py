import os, telebot, threading, psycopg2, re, time, io, json, requests
from telebot import apihelper, types
from google import genai
from PIL import Image
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- CONFIG ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'DEMO') 
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_ID = 1578448812 

ALLOWED_CHATS = [-1002786610592] 

# IDE ÍRD BE A SAJÁT @BotFather LINKEDET!
WEB_APP_URL = "https://t.me/Tradevisionfxai_bot/Terminal" 

MODEL_NAME = 'models/gemini-3.1-flash-lite-preview'
client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_TOKEN)
analysis_storage = {}
media_groups = {}

# --- DATABASE SETUP (SUPABASE / POSTGRES) ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS signals 
                     (id SERIAL PRIMARY KEY, 
                      msg_id TEXT, symbol TEXT, type TEXT, entry REAL, sl REAL, tp REAL, 
                      reasoning TEXT, status TEXT, confidence INTEGER)''')
        conn.commit()
        c.close()
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
    # Okos árolvasó, ami átugorja a dollárjeleket és szövegeket
    match = re.search(rf"{label}[^\n\d]*([\d.,]+)", text, re.IGNORECASE)
    if match:
        try: return float(match.group(1).replace(',', ''))
        except: return None
    return None

# --- JAVÍTOTT ALPHA VANTAGE MOTOR (DOCS ALAPJÁN) ---
def get_current_price_av(sym):
    s = str(sym).upper().replace("SYMBOL:", "").replace(" ", "").replace("/", "").replace("-", "")
    base, quote = s, "USD"
    
    if s == "GOLD" or "XAU" in s: base, quote = "XAU", "USD"
    elif s == "SILVER" or "XAG" in s: base, quote = "XAG", "USD"
    elif s.endswith("USDT"): base, quote = s[:-4], "USDT"
    elif s.endswith("USD"): base, quote = s[:-3], "USD"
    elif s.endswith("EUR"): base, quote = s[:-3], "EUR"
    elif s.endswith("JPY"): base, quote = s[:-3], "JPY"
    elif len(s) == 6: base, quote = s[:3], s[3:]
    
    url_currency = f"https://www.alphavantage.co/query?function=CURRENCY_EXCHANGE_RATE&from_currency={base}&to_currency={quote}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        req = requests.get(url_currency, timeout=10)
        data = req.json()
        if "Realtime Currency Exchange Rate" in data:
            return float(data["Realtime Currency Exchange Rate"]["5. Exchange Rate"])
        elif "Information" in data or "Note" in data or "Error Message" in data:
            print(f"AV API MESSAGE (Currency): {data}") 
    except Exception as e:
        print(f"AV Request Error: {e}")

    ticker = s
    if "US100" in s or "NASDAQ" in s: ticker = "QQQ"
    elif "US500" in s or "SPX" in s: ticker = "SPY"
    elif "US30" in s or "DOW" in s: ticker = "DIA"
    
    url_quote = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={ALPHA_VANTAGE_API_KEY}"
    try:
        req = requests.get(url_quote, timeout=10)
        data = req.json()
        if "Global Quote" in data and "05. price" in data["Global Quote"]:
            price_str = data["Global Quote"]["05. price"]
            if price_str: return float(price_str)
        elif "Information" in data or "Note" in data or "Error Message" in data:
            print(f"AV API MESSAGE (Stock): {data}")
    except Exception as e:
        pass
    return None

def auto_trade_checker():
    send_admin_log("🔄 AV Auto Checker (Smart Limit) Started...")
    while True:
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT id, symbol, type, sl, tp FROM signals WHERE status='PENDING'")
            trades = c.fetchall()
            c.close()
            conn.close()
            
            if not trades:
                time.sleep(900)
                continue 
            
            unique_symbols = set([t[1] for t in trades])
            num_symbols = len(unique_symbols)
            
            current_prices = {}
            for sym in unique_symbols:
                price = get_current_price_av(sym)
                if price:
                    current_prices[sym] = price
                time.sleep(15) 

            if current_prices:
                conn = get_db_connection()
                c = conn.cursor()
                for t_id, sym, t_type, sl, tp in trades:
                    if sym not in current_prices or not sl or not tp: continue 
                    
                    price = current_prices[sym]
                    new_status = None
                    
                    if "BUY" in t_type:
                        if price >= tp: new_status = "WON"
                        elif price <= sl: new_status = "LOST"
                    elif "SELL" in t_type:
                        if price <= tp: new_status = "WON"
                        elif price >= sl: new_status = "LOST"
                        
                    if new_status:
                        c.execute("UPDATE signals SET status=%s WHERE id=%s", (new_status, t_id))
                        send_admin_log(f"🎯 [AUTO-CLOSE]: {sym} ({t_type}) -> {new_status} (Price: {price})")
                
                conn.commit()
                c.close()
                conn.close()

            sleep_minutes = 60 * num_symbols
            time.sleep(sleep_minutes * 60)
            
        except Exception as e:
            print(f"Auto Checker Error: {e}")
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
                conn = get_db_connection()
                c = conn.cursor()
                c.execute("SELECT symbol, type, entry, sl, tp, reasoning, confidence, status FROM signals ORDER BY id DESC LIMIT 20")
                rows = c.fetchall()
                c.close()
                conn.close()
                
                signals = []
                for row in rows:
                    signals.append({
                        "asset": str(row[0]).upper(),
                        "type": str(row[1]).upper(),
                        "entry": row[2] if row[2] else 0,
                        "sl": row[3] if row[3] else 0,
                        "tp": row[4] if row[4] else 0,
                        "conf": row[6] if row[6] else 85,
                        "status": str(row[7]).upper(), 
                        "reasoning": row[5] if row[5] else "No details provided."
                    })
                self.wfile.write(json.dumps(signals).encode())
            except Exception as e:
                print(f"API Error: {e}")
                self.wfile.write(json.dumps([]).encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"TradeVision API ACTIVE")
    def log_message(self, format, *args): return

# --- BOT HANDLERS ---
@bot.message_handler(func=lambda m: not is_authorized(m))
def unauthorized_access(message):
    if message.chat.type == 'private':
        bot.reply_to(message, "🛑 **Access Denied. You are not authorized to use this terminal.**")

# 1. MANUÁLIS WIN/LOSS REAKCIÓ (JAVÍTVA SUPABASE-RE)
@bot.message_handler(func=lambda m: m.reply_to_message is not None)
def handle_manual_update(message):
    if not is_authorized(message): return
    text = message.text.lower()
    new_status = None
    
    if any(word in text for word in ['win', 'won', 'profit', 'hit tp', 'tp']):
        new_status = "WON"
    elif any(word in text for word in ['lost', 'loss', 'sl', 'hit sl']):
        new_status = "LOST"
        
    if new_status:
        orig_msg_id = str(message.reply_to_message.message_id)
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("UPDATE signals SET status=%s WHERE msg_id=%s", (new_status, orig_msg_id))
            if c.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"✅ **HUB UPDATED!** The trade is now marked as `{new_status}` 📈")
            else:
                bot.reply_to(message, "⚠️ Hmm, I can't find this signal in the database. Are you replying to the correct analysis message? 🤔")
            c.close()
            conn.close()
        except Exception as e:
            bot.reply_to(message, f"❌ Oops, database error: {e}")
    else:
        # Ha a reply nem win/loss volt, menjen át a chatbe
        handle_trading_chat(message)

# 2. START / HUB PARANCSOK
@bot.message_handler(commands=['start'])
def welcome(message):
    if not is_authorized(message): return
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="📱 Open TradeVision Hub", url=WEB_APP_URL))
    bot.reply_to(message, "🚀 **Welcome to TradeVision AI v4.2b Pro!** Let's conquer the markets together. 👇", reply_markup=markup)

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
    except Exception as e:
        send_admin_log(f"Couldn't pin the message. Error: {e}")

# 3. CHECK PARANCS (JAVÍTVA SUPABASE-RE)
@bot.message_handler(commands=['check'])
def manual_price_check(message):
    if not is_authorized(message): return
    bot.reply_to(message, "🔄 **Initiating Manual Price Check...**\nFetching active trades from the Alpha Vantage API... ⏳")
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, symbol, type, sl, tp FROM signals WHERE status='PENDING'")
        trades = c.fetchall()
        
        if not trades:
            bot.send_message(message.chat.id, "🤷‍♂️ No open (PENDING) trades found right now.")
            c.close()
            conn.close()
            return
            
        updated_count = 0
        for t_id, sym, t_type, sl, tp in trades:
            if not sl or not tp: continue
            price = get_current_price_av(sym)
            
            if not price:
                bot.send_message(message.chat.id, f"⚠️ Couldn't fetch a price for `{sym}` from the API. Check the Render logs! 🕵️‍♂️")
                continue
            
            new_status = None
            if "BUY" in t_type:
                if price >= tp: new_status = "WON"
                elif price <= sl: new_status = "LOST"
            elif "SELL" in t_type:
                if price <= tp: new_status = "WON"
                elif price >= sl: new_status = "LOST"
                
            if new_status:
                c.execute("UPDATE signals SET status=%s WHERE id=%s", (new_status, t_id))
                bot.send_message(message.chat.id, f"🔔 **TRADE UPDATE!** {sym} hit its target and is now `{new_status}`! 🚀\n💵 Current API Price: {price}")
                updated_count += 1
            else:
                bot.send_message(message.chat.id, f"📊 `{sym}` is still holding strong. 💎👐\n💵 Current API Price: {price}\n(🛑 SL: {sl} | 🎯 TP: {tp})")
                
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Oops, ran into an issue during the check: {e} 🔧")

# 4. KÉPKEZELÉS ÉS AI ANALÍZIS (JAVÍTVA SUPABASE-RE)
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

def run_analysis(message, images):
    status_msg = bot.reply_to(message, "⏳ *Scanning the markets and analyzing your chart... Give me a sec!* 🧠📈", parse_mode='Markdown')
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

        try:
            match_type = re.search(r"SIGNAL:\s*([^\n]+)", summary, re.IGNORECASE)
            sig_type = match_type.group(1).strip().upper() if match_type else ("SELL" if "SELL" in summary.upper() else "BUY")

            conf_match = re.search(r'CONFIDENCE[:\s]*(\d+)', summary, re.IGNORECASE)
            conf_val = int(conf_match.group(1)) if conf_match else 85

            entry_p = extract_price(summary, "ENTRY")
            sl_p = extract_price(summary, "STOP LOSS")
            tp_p = extract_price(summary, "TAKE PROFIT")
            sym = "ASSET"
            match_sym = re.search(r"SYMBOL:\s*([\w/]+)", summary)
            if match_sym: sym = match_sym.group(1)
            
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("INSERT INTO signals (msg_id, symbol, type, entry, sl, tp, reasoning, status, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (str(status_msg.message_id), sym, sig_type, entry_p, sl_p, tp_p, reasoning.strip(), "PENDING", conf_val))
            conn.commit()
            c.close()
            conn.close()
        except Exception as db_e:
            send_admin_log(f"⚠️ DB Saving Error: {db_e}")

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(text="📖 Read Confluence", callback_data=f"det_{status_msg.message_id}"))
        bot.edit_message_text(f"📊 **MARKET ANALYSIS**\n\n{summary.strip()}", message.chat.id, status_msg.message_id, reply_markup=markup)
    except Exception as e:
        bot.edit_message_text(f"❌ *Whoops! My circuits got tangled analyzing that. Error:* {e}", message.chat.id, status_msg.message_id, parse_mode='Markdown')

# 5. DETAILED DESCRIPTION GOMB (JAVÍTVA SUPABASE-RE)
@bot.callback_query_handler(func=lambda call: call.data.startswith("det_"))
def callback_inline(call):
    if not is_authorized(call.message): return
    msg_id = call.data.split("_")[1]
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT reasoning FROM signals WHERE msg_id = %s", (msg_id,))
        row = c.fetchone()
        c.close()
        conn.close()
        if row: bot.send_message(call.message.chat.id, f"🔍 **AI RATIONALE:**\n\n{row[0]}\n\n*Trade safe!* 🛡️")
        else: bot.answer_callback_query(call.id, "Data not found in the vault. 🤷‍♂️")
    except: bot.answer_callback_query(call.id, "Error loading the data.")

# 6. EREDETI ÁLTALÁNOS CSEVEGŐ (TRADING ASSZISZTENS)
@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_trading_chat(message):
    if not is_authorized(message): return
    
    if message.reply_to_message and any(w in message.text.lower() for w in ['win', 'won', 'lost', 'loss', 'profit', 'tp', 'sl']):
        return 

    status_msg = bot.reply_to(message, "🤔 *Thinking about the markets...*", parse_mode='Markdown')
    try:
        prompt = (
            "You are TradeVision AI, an elite, friendly, and highly intelligent trading assistant. "
            "The user is asking you a trading, crypto, forex, or finance related question. "
            "Answer in English, use emojis to make it engaging and human-like. "
            "If applicable, cite real-world knowledge or suggest internet sources/links to back up your claims. "
            "Keep it concise but highly valuable. If the user asks something completely unrelated to trading/finance, "
            "politely steer the conversation back to the markets.\n\n"
            f"User's message: {message.text}"
        )
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        bot.edit_message_text(response.text, message.chat.id, status_msg.message_id, disable_web_page_preview=True)
    except Exception as e:
        bot.edit_message_text(f"❌ *Sorry, my AI brain had a hiccup:* {e}", message.chat.id, status_msg.message_id, parse_mode='Markdown')

if __name__ == "__main__":
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthCheckHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=auto_trade_checker, daemon=True).start()
    send_admin_log("🚀 TradeVision Gatekeeper started (All Features + Chat Linked)!")
    bot.infinity_polling()
