import logging
import asyncio
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv


print("Current working directory:", os.getcwd())
print("Files in directory:", os.listdir('.'))

# Try to load .env file
result = load_dotenv()
print("load_dotenv() result:", result)

# ================== CONFIG ===================
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [6685099030]

# Validate required environment variables
if not all([SUPABASE_URL, SUPABASE_KEY, BOT_TOKEN]):
    print("❌ Missing required environment variables:")
    if not SUPABASE_URL: print("  - SUPABASE_URL")
    if not SUPABASE_KEY: print("  - SUPABASE_KEY")
    if not BOT_TOKEN: print("  - BOT_TOKEN")
    exit(1)

print("🚀 Starting Crypto Bot...")
print(f"📡 Connecting to Supabase: {SUPABASE_URL[:50]}...")

# ================== SUPABASE INIT ===================
try:
    from supabase import create_client, Client
    
    # Clean and validate URL
    if not SUPABASE_URL.startswith(('http://', 'https://')):
        SUPABASE_URL = 'https://' + SUPABASE_URL
    
    # Remove any trailing slashes or extra characters
    SUPABASE_URL = SUPABASE_URL.rstrip('/')
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase client created successfully")
    
except Exception as e:
    print(f"❌ Supabase initialization failed: {e}")
    print("🔄 Running without database - using in-memory storage")
    supabase = None

# ================== IN-MEMORY STORAGE (FALLBACK) ===================
user_data = {
    'alerts': {},      # user_id: [{'symbol': 'BTC', 'price': 45000, 'type': 'single'}]
    'watchlists': {},  # user_id: ['BTC', 'ETH']
    'api_keys': {},    # user_id: {'binance': {'key': 'xxx', 'secret': 'yyy'}}
    'sessions': {}     # user_id: {'username': 'xxx', 'last_active': datetime}
}

# ================== DATABASE FUNCTIONS ===================
def test_connection():
    """Test database connection"""
    if not supabase:
        return False
    try:
        supabase.table("user_alerts").select("*").limit(1).execute()
        return True
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        return False

def safe_db_operation(operation, fallback_operation=None):
    """Safely execute database operation with fallback"""
    try:
        if supabase:
            return operation()
        elif fallback_operation:
            return fallback_operation()
        return False
    except Exception as e:
        print(f"Database error: {e}")
        if fallback_operation:
            return fallback_operation()
        return False

def log_user_activity(user_id, username=None, first_name=None):
    """Log user activity"""
    def db_op():
        supabase.table("user_sessions").upsert({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_active": datetime.now().isoformat()
        }).execute()
        return True
    
    def fallback_op():
        user_data['sessions'][user_id] = {
            'username': username,
            'first_name': first_name,
            'last_active': datetime.now()
        }
        return True
    
    return safe_db_operation(db_op, fallback_op)

def get_user_alerts(user_id):
    """Get user alerts"""
    def db_op():
        response = supabase.table("user_alerts").select("*").eq("user_id", user_id).eq("is_active", True).execute()
        return response.data
    
    def fallback_op():
        return user_data['alerts'].get(user_id, [])
    
    return safe_db_operation(db_op, fallback_op) or []

def add_user_alert(user_id, symbol, price=None, min_price=None, max_price=None):
    """Add user alert"""
    def db_op():
        alert_data = {
            "user_id": user_id,
            "symbol": symbol.upper(),
            "alert_type": "price_range" if min_price and max_price else "single_price"
        }
        if price: alert_data["price"] = float(price)
        if min_price: alert_data["min_price"] = float(min_price)
        if max_price: alert_data["max_price"] = float(max_price)
        
        supabase.table("user_alerts").insert(alert_data).execute()
        return True
    
    def fallback_op():
        if user_id not in user_data['alerts']:
            user_data['alerts'][user_id] = []
        
        alert = {'symbol': symbol.upper(), 'type': 'range' if min_price and max_price else 'single'}
        if price: alert['price'] = float(price)
        if min_price: alert['min_price'] = float(min_price)
        if max_price: alert['max_price'] = float(max_price)
        
        user_data['alerts'][user_id].append(alert)
        return True
    
    return safe_db_operation(db_op, fallback_op)

def remove_user_alerts(user_id, symbol):
    """Remove user alerts for symbol"""
    def db_op():
        supabase.table("user_alerts").update({"is_active": False}).eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        return True
    
    def fallback_op():
        if user_id in user_data['alerts']:
            user_data['alerts'][user_id] = [
                alert for alert in user_data['alerts'][user_id] 
                if alert['symbol'] != symbol.upper()
            ]
        return True
    
    return safe_db_operation(db_op, fallback_op)

def get_user_watchlist(user_id):
    """Get user watchlist"""
    def db_op():
        response = supabase.table("user_watchlist").select("symbol").eq("user_id", user_id).execute()
        return [item["symbol"] for item in response.data]
    
    def fallback_op():
        return user_data['watchlists'].get(user_id, [])
    
    return safe_db_operation(db_op, fallback_op) or []

def add_to_watchlist(user_id, symbols):
    """Add symbols to watchlist"""
    def db_op():
        for symbol in symbols:
            supabase.table("user_watchlist").upsert({
                "user_id": user_id,
                "symbol": symbol.upper()
            }).execute()
        return True
    
    def fallback_op():
        if user_id not in user_data['watchlists']:
            user_data['watchlists'][user_id] = []
        
        for symbol in symbols:
            symbol = symbol.upper()
            if symbol not in user_data['watchlists'][user_id]:
                user_data['watchlists'][user_id].append(symbol)
        return True
    
    return safe_db_operation(db_op, fallback_op)

def remove_from_watchlist(user_id, symbol):
    """Remove symbol from watchlist"""
    def db_op():
        supabase.table("user_watchlist").delete().eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        return True
    
    def fallback_op():
        if user_id in user_data['watchlists']:
            try:
                user_data['watchlists'][user_id].remove(symbol.upper())
            except ValueError:
                pass
        return True
    
    return safe_db_operation(db_op, fallback_op)

# ================== BOT SETUP ===================
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================== BOT COMMANDS ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    log_user_activity(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("📊 Prices", callback_data="price_help"),
         InlineKeyboardButton("🔔 Alerts", callback_data="alert_help")],
        [InlineKeyboardButton("📋 Watchlist", callback_data="watch_help"),
         InlineKeyboardButton("💼 Portfolio", callback_data="portfolio_help")],
        [InlineKeyboardButton("🛠 Admin", callback_data="admin_panel") if user.id in ADMIN_IDS else InlineKeyboardButton("❓ Help", callback_data="general_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🤖 Welcome {user.first_name}!\n\nYour Crypto Trading Assistant is ready.\nChoose an option below:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """🤖 **Crypto Bot Commands:**

**Alerts:**
• `/alert BTC 45000` - Single price alert
• `/alert BTC 45000 50000` - Range alert
• `/alerts` - View alerts
• `/removealert BTC` - Remove alerts

**Watchlist:**
• `/watchlist` - View watchlist
• `/addwatch BTC ETH` - Add coins
• `/removewatch BTC` - Remove coin

**Info:**
• `/status` - Bot status
• `/start` - Main menu"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set price alert"""
    if not context.args:
        await update.message.reply_text("Usage: `/alert BTC 45000` or `/alert BTC 45000 50000`", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide symbol and price(s)")
        return
    
    user_id = update.effective_user.id
    symbol = context.args[0].upper()
    
    try:
        if len(context.args) == 2:
            price = float(context.args[1])
            if add_user_alert(user_id, symbol, price=price):
                await update.message.reply_text(f"✅ Alert set: {symbol} at ${price:,.2f}")
            else:
                await update.message.reply_text("❌ Error setting alert")
        
        elif len(context.args) == 3:
            min_price, max_price = float(context.args[1]), float(context.args[2])
            if min_price >= max_price:
                await update.message.reply_text("❌ Min price must be lower than max price")
                return
                
            if add_user_alert(user_id, symbol, min_price=min_price, max_price=max_price):
                await update.message.reply_text(f"✅ Range alert set: {symbol} ${min_price:,.2f} - ${max_price:,.2f}")
            else:
                await update.message.reply_text("❌ Error setting alert")
                
    except ValueError:
        await update.message.reply_text("❌ Invalid price format")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View alerts"""
    user_id = update.effective_user.id
    alerts = get_user_alerts(user_id)
    
    if not alerts:
        await update.message.reply_text("🔔 No active alerts. Use `/alert BTC 45000` to set one!", parse_mode='Markdown')
        return
    
    alert_text = "🔔 **Your Alerts:**\n\n"
    for alert in alerts:
        symbol = alert.get('symbol', alert.get('symbol'))
        if alert.get('type') == 'single' or alert.get('alert_type') == 'single_price':
            price = alert.get('price')
            alert_text += f"• {symbol}: ${price:,.2f}\n"
        else:
            min_p = alert.get('min_price')
            max_p = alert.get('max_price')
            alert_text += f"• {symbol}: ${min_p:,.2f} - ${max_p:,.2f}\n"
    
    await update.message.reply_text(alert_text, parse_mode='Markdown')

async def removealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove alerts"""
    if not context.args:
        await update.message.reply_text("Usage: `/removealert BTC`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbol = context.args[0].upper()
    
    if remove_user_alerts(user_id, symbol):
        await update.message.reply_text(f"✅ Alerts removed for {symbol}")
    else:
        await update.message.reply_text("❌ Error removing alerts")

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View watchlist"""
    user_id = update.effective_user.id
    watchlist = get_user_watchlist(user_id)
    
    if not watchlist:
        await update.message.reply_text("📋 Watchlist empty. Use `/addwatch BTC ETH`!", parse_mode='Markdown')
        return
    
    text = "📋 **Your Watchlist:**\n\n" + "\n".join([f"• {symbol}" for symbol in watchlist])
    await update.message.reply_text(text, parse_mode='Markdown')

async def addwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add to watchlist"""
    if not context.args:
        await update.message.reply_text("Usage: `/addwatch BTC ETH SOL`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbols = [arg.upper() for arg in context.args]
    
    if add_to_watchlist(user_id, symbols):
        await update.message.reply_text(f"✅ Added {', '.join(symbols)} to watchlist!")
    else:
        await update.message.reply_text("❌ Error adding to watchlist")

async def removewatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove from watchlist"""
    if not context.args:
        await update.message.reply_text("Usage: `/removewatch BTC`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbol = context.args[0].upper()
    
    if remove_from_watchlist(user_id, symbol):
        await update.message.reply_text(f"✅ Removed {symbol} from watchlist")
    else:
        await update.message.reply_text("❌ Error removing from watchlist")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot status"""
    db_status = "✅ Connected" if supabase and test_connection() else "❌ Using memory storage"
    
    status_text = f"""🤖 **Bot Status:**

Database: {db_status}
Storage: {'Supabase' if supabase else 'In-Memory'}
Status: 🟢 Online

Users tracked: {len(user_data['sessions'])}
Total alerts: {sum(len(alerts) for alerts in user_data['alerts'].values())}
Total watchlists: {sum(len(wl) for wl in user_data['watchlists'].values())}"""
    
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ================== CALLBACK HANDLERS ===================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks"""
    query = update.callback_query
    await query.answer()
    
    help_texts = {
        "price_help": "📊 **Price Commands:**\n\n• `/price BTC ETH` - Get prices\n• Coming soon: Live price tracking",
        "alert_help": "🔔 **Alert Commands:**\n\n• `/alert BTC 45000` - Single alert\n• `/alert BTC 45000 50000` - Range alert\n• `/alerts` - View alerts\n• `/removealert BTC` - Remove alerts",
        "watch_help": "📋 **Watchlist Commands:**\n\n• `/watchlist` - View list\n• `/addwatch BTC ETH` - Add coins\n• `/removewatch BTC` - Remove coin",
        "portfolio_help": "💼 **Portfolio:**\n\nComing soon:\n• Portfolio tracking\n• P&L analysis\n• Exchange integration",
        "general_help": "❓ **Help:**\n\nUse `/help` for all commands\nUse `/status` for bot status\nUse `/start` for main menu",
        "admin_panel": "🛠 **Admin Panel:**\n\nDatabase status checked.\nUse `/status` for details." if update.effective_user.id in ADMIN_IDS else "❌ Access denied"
    }
    
    text = help_texts.get(query.data, "Unknown option")
    await query.message.reply_text(text, parse_mode='Markdown')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again.")

# ================== MAIN ===================
def main():
    """Start the bot"""
    print("🔧 Initializing bot...")
    
    # Test database if available
    if supabase:
        if test_connection():
            print("✅ Database connection verified")
        else:
            print("⚠️ Database test failed - using memory storage")
    else:
        print("⚠️ Running with in-memory storage only")
    
    # Create bot application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("alert", alert_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("removealert", removealert_command))
    app.add_handler(CommandHandler("watchlist", watchlist_command))
    app.add_handler(CommandHandler("addwatch", addwatch_command))
    app.add_handler(CommandHandler("removewatch", removewatch_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(error_handler)
    
    print("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
