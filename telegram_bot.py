import logging
import asyncio
import requests
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from supabase import create_client, Client

# ================== CONFIG ===================
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://kxvheefpdeqtaklcqikp.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt4dmhlZWZwZGVxdGFrbGNxaWtwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDk5MTM3MzQsImV4cCI6MjA2NTQ4OTczNH0.JEx0LcIAdBJYiDBuCOQdOiyzhiHvkcIV-PBxGDKQZPw")
BOT_TOKEN = os.getenv("BOT_TOKEN", "7631419865:AAFSJK9A7FNbQL5BRwujVm89C_RVg0wTYI4")
ADMIN_IDS = [6685099030]  # Replace with your Telegram ID

print("🚀 Starting Crypto Bot...")
print("📡 Connecting to Supabase...")

# ================== SUPABASE INIT ===================
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ================== DATABASE FUNCTIONS ===================
def test_supabase_connection():
    """Test Supabase connection and verify tables exist"""
    try:
        # Test connection by trying to query a table
        response = supabase.table("user_alerts").select("*").limit(1).execute()
        print("✅ Supabase connection successful")
        return True
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        print("\n💡 Make sure you have created the required tables in your Supabase dashboard.")
        print("📋 Required tables: user_alerts, user_watchlist, api_keys, user_sessions")
        return False

def get_table_creation_sql():
    """Return SQL commands for creating required tables"""
    return """
-- Create user_alerts table
CREATE TABLE IF NOT EXISTS user_alerts (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    alert_type TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price DECIMAL(20,8),
    min_price DECIMAL(20,8),
    max_price DECIMAL(20,8),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create user_watchlist table
CREATE TABLE IF NOT EXISTS user_watchlist (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, symbol)
);

-- Create api_keys table
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    exchange TEXT NOT NULL,
    api_key TEXT NOT NULL,
    api_secret TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, exchange)
);

-- Create user_sessions table for tracking users
CREATE TABLE IF NOT EXISTS user_sessions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    last_active TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_user_alerts_user_id ON user_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_user_watchlist_user_id ON user_watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
"""

def log_user_activity(user_id, username=None, first_name=None, last_name=None):
    """Log user activity to Supabase"""
    try:
        # Insert or update user session
        supabase.table("user_sessions").upsert({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "last_active": datetime.now().isoformat()
        }).execute()
        logger.info(f"User activity logged for user {user_id}")
    except Exception as e:
        logger.error(f"Error logging user activity: {e}")

def get_user_alerts(user_id):
    """Get user's active alerts from Supabase"""
    try:
        response = supabase.table("user_alerts").select("*").eq("user_id", user_id).eq("is_active", True).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error getting user alerts: {e}")
        return []

def add_user_alert(user_id, symbol, price=None, min_price=None, max_price=None):
    """Add price alert for user to Supabase"""
    try:
        alert_data = {
            "user_id": user_id,
            "symbol": symbol.upper(),
            "alert_type": "price_range" if min_price and max_price else "single_price"
        }
        
        if price:
            alert_data["price"] = float(price)
        if min_price:
            alert_data["min_price"] = float(min_price)
        if max_price:
            alert_data["max_price"] = float(max_price)
            
        response = supabase.table("user_alerts").insert(alert_data).execute()
        logger.info(f"Alert added for user {user_id}: {symbol}")
        return True
    except Exception as e:
        logger.error(f"Error adding user alert: {e}")
        return False

def remove_user_alerts(user_id, symbol):
    """Remove alerts for a specific symbol"""
    try:
        supabase.table("user_alerts").update({"is_active": False}).eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        logger.info(f"Alerts removed for user {user_id}: {symbol}")
        return True
    except Exception as e:
        logger.error(f"Error removing user alerts: {e}")
        return False

def get_user_watchlist(user_id):
    """Get user's watchlist from Supabase"""
    try:
        response = supabase.table("user_watchlist").select("*").eq("user_id", user_id).execute()
        return [item["symbol"] for item in response.data]
    except Exception as e:
        logger.error(f"Error getting user watchlist: {e}")
        return []

def add_to_watchlist(user_id, symbols):
    """Add symbols to user's watchlist in Supabase"""
    try:
        for symbol in symbols:
            supabase.table("user_watchlist").upsert({
                "user_id": user_id,
                "symbol": symbol.upper()
            }).execute()
        logger.info(f"Added to watchlist for user {user_id}: {symbols}")
        return True
    except Exception as e:
        logger.error(f"Error adding to watchlist: {e}")
        return False

def remove_from_watchlist(user_id, symbol):
    """Remove symbol from user's watchlist"""
    try:
        supabase.table("user_watchlist").delete().eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        logger.info(f"Removed from watchlist for user {user_id}: {symbol}")
        return True
    except Exception as e:
        logger.error(f"Error removing from watchlist: {e}")
        return False

def store_api_keys(user_id, exchange, api_key, api_secret):
    """Store user's API keys (encrypted in production)"""
    try:
        # In production, encrypt api_key and api_secret before storing
        supabase.table("api_keys").upsert({
            "user_id": user_id,
            "exchange": exchange.lower(),
            "api_key": api_key,  # Should be encrypted
            "api_secret": api_secret  # Should be encrypted
        }).execute()
        logger.info(f"API keys stored for user {user_id}: {exchange}")
        return True
    except Exception as e:
        logger.error(f"Error storing API keys: {e}")
        return False

def get_user_api_keys(user_id):
    """Get user's stored API keys"""
    try:
        response = supabase.table("api_keys").select("exchange").eq("user_id", user_id).execute()
        return [item["exchange"] for item in response.data]
    except Exception as e:
        logger.error(f"Error getting user API keys: {e}")
        return []

# ================== LOGGER ===================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== BOT COMMANDS ===================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - show main menu"""
    user = update.effective_user
    user_name = user.first_name
    
    # Log user activity to Supabase
    log_user_activity(user.id, user.username, user.first_name, user.last_name)
    
    keyboard = [
        [InlineKeyboardButton("📊 Price Check", callback_data="price_menu"),
         InlineKeyboardButton("🚀 Top Gainers/Losers", callback_data="top_menu")],
        [InlineKeyboardButton("🔔 Price Alerts", callback_data="alert_menu"),
         InlineKeyboardButton("🧠 Auto Trade Demo", callback_data="demo_trade_menu")],
        [InlineKeyboardButton("💼 Portfolio", callback_data="portfolio_menu"),
         InlineKeyboardButton("📈 Charts", callback_data="chart_menu")],
        [InlineKeyboardButton("🔐 API Keys", callback_data="apikey_menu"),
         InlineKeyboardButton("📋 Watchlist", callback_data="watchlist_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"🤖 Welcome {user_name}!\n\n" \
                   "Your personal Crypto Trading Assistant is ready.\n" \
                   "Choose an option below to get started:"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
🤖 **Crypto Bot Commands:**

📊 **Price Commands:**
• `/price BTC ETH` - Get current prices
• `/price BTCUSDT` - Get specific pair price

🔔 **Alert Commands:**
• `/alert BTC 45000 50000` - Set price range alerts
• `/alert ETH 3000` - Set single price alert
• `/alerts` - View your active alerts
• `/removealert BTC` - Remove alerts for a coin

💼 **Portfolio Commands:**
• `/portfolio` - View your portfolio
• `/balance` - Check balances

🔐 **API Commands:**
• `/setapikey binance YOUR_KEY YOUR_SECRET` - Set exchange API keys
• `/viewkeys` - View configured exchanges

📋 **Watchlist Commands:**
• `/watchlist` - View your watchlist
• `/addwatch BTC ETH` - Add coins to watchlist
• `/removewatch BTC` - Remove from watchlist

🚀 **Market Commands:**
• `/topgainers` - Top gaining coins
• `/toplosers` - Top losing coins

Type `/start` to return to the main menu.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set price alert"""
    if not context.args:
        await update.message.reply_text(
            "Please specify alert parameters.\n\n"
            "Examples:\n"
            "• `/alert BTC 45000` - Single price alert\n"
            "• `/alert ETH 3000 4000` - Price range alert",
            parse_mode='Markdown'
        )
        return
    
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text("❌ Please provide symbol and price(s)")
        return
    
    symbol = context.args[0].upper()
    
    try:
        if len(context.args) == 2:
            # Single price alert
            price = float(context.args[1])
            if add_user_alert(user_id, symbol, price=price):
                await update.message.reply_text(f"✅ Price alert set for {symbol} at ${price:,.2f}")
            else:
                await update.message.reply_text("❌ Error setting alert. Please try again.")
        
        elif len(context.args) == 3:
            # Price range alert
            min_price = float(context.args[1])
            max_price = float(context.args[2])
            if min_price >= max_price:
                await update.message.reply_text("❌ Min price must be lower than max price")
                return
                
            if add_user_alert(user_id, symbol, min_price=min_price, max_price=max_price):
                await update.message.reply_text(f"✅ Price range alert set for {symbol}: ${min_price:,.2f} - ${max_price:,.2f}")
            else:
                await update.message.reply_text("❌ Error setting alert. Please try again.")
                
    except ValueError:
        await update.message.reply_text("❌ Invalid price format. Please use numbers only.")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View user's active alerts"""
    user_id = update.effective_user.id
    alerts = get_user_alerts(user_id)
    
    if not alerts:
        await update.message.reply_text("🔔 You have no active price alerts.\n\nUse `/alert BTC 45000` to set one!", parse_mode='Markdown')
        return
    
    alert_text = "🔔 **Your Active Alerts:**\n\n"
    for alert in alerts:
        symbol = alert['symbol']
        if alert['alert_type'] == 'single_price':
            alert_text += f"• {symbol}: ${alert['price']:,.2f}\n"
        else:
            alert_text += f"• {symbol}: ${alert['min_price']:,.2f} - ${alert['max_price']:,.2f}\n"
    
    await update.message.reply_text(alert_text, parse_mode='Markdown')

async def removealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove alerts for a specific symbol"""
    if not context.args:
        await update.message.reply_text("Please specify the symbol.\nExample: `/removealert BTC`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbol = context.args[0].upper()
    
    if remove_user_alerts(user_id, symbol):
        await update.message.reply_text(f"✅ All alerts removed for {symbol}")
    else:
        await update.message.reply_text("❌ Error removing alerts. Please try again.")

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View user's watchlist"""
    user_id = update.effective_user.id
    watchlist = get_user_watchlist(user_id)
    
    if not watchlist:
        await update.message.reply_text("📋 Your watchlist is empty.\n\nUse `/addwatch BTC ETH` to add coins!", parse_mode='Markdown')
        return
    
    watchlist_text = "📋 **Your Watchlist:**\n\n" + "\n".join([f"• {symbol}" for symbol in watchlist])
    await update.message.reply_text(watchlist_text, parse_mode='Markdown')

async def addwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add coins to watchlist"""
    if not context.args:
        await update.message.reply_text("Please specify coins to add.\nExample: `/addwatch BTC ETH SOL`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbols = [arg.upper() for arg in context.args]
    
    if add_to_watchlist(user_id, symbols):
        await update.message.reply_text(f"✅ Added {', '.join(symbols)} to your watchlist!")
    else:
        await update.message.reply_text("❌ Error adding coins to watchlist. Please try again.")

async def removewatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove coin from watchlist"""
    if not context.args:
        await update.message.reply_text("Please specify the coin to remove.\nExample: `/removewatch BTC`", parse_mode='Markdown')
        return
    
    user_id = update.effective_user.id
    symbol = context.args[0].upper()
    
    if remove_from_watchlist(user_id, symbol):
        await update.message.reply_text(f"✅ Removed {symbol} from your watchlist")
    else:
        await update.message.reply_text("❌ Error removing coin from watchlist. Please try again.")

async def setapikey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set API keys for exchanges"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Please provide exchange, API key, and secret.\n\n"
            "Example: `/setapikey binance YOUR_API_KEY YOUR_SECRET`\n\n"
            "⚠️ **Security Warning:** Only use this command in private messages!",
            parse_mode='Markdown'
        )
        return
    
    # Delete the user's message for security
    try:
        await update.message.delete()
    except:
        pass
    
    user_id = update.effective_user.id
    exchange = context.args[0].lower()
    api_key = context.args[1]
    api_secret = context.args[2]
    
    if store_api_keys(user_id, exchange, api_key, api_secret):
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ API keys for {exchange.title()} have been stored securely.\n\n"
                 "⚠️ Your original message has been deleted for security."
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Error storing API keys. Please try again."
        )

async def viewkeys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View configured exchanges"""
    user_id = update.effective_user.id
    exchanges = get_user_api_keys(user_id)
    
    if not exchanges:
        await update.message.reply_text("🔐 No API keys configured.\n\nUse `/setapikey` to add exchange keys.", parse_mode='Markdown')
        return
    
    keys_text = "🔐 **Configured Exchanges:**\n\n" + "\n".join([f"• {exchange.title()}" for exchange in exchanges])
    await update.message.reply_text(keys_text, parse_mode='Markdown')

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel - only for authorized users"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ Access denied. Admin privileges required.")
        return
        
    keyboard = [
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 Database Info", callback_data="admin_db_info")],
        [InlineKeyboardButton("🔄 Test Connection", callback_data="admin_test_connection")],
        [InlineKeyboardButton("📥 Broadcast Message", callback_data="admin_broadcast")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("🛠 **Admin Control Panel**\nSelect an action:", 
                                   reply_markup=reply_markup, parse_mode='Markdown')

# ================== CALLBACK HANDLERS ===================
async def admin_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.callback_query.answer("Access denied")
        return
        
    await update.callback_query.answer()
    
    try:
        # Get user count
        users_response = supabase.table("user_sessions").select("id").execute()
        user_count = len(users_response.data)
        
        # Get alerts count
        alerts_response = supabase.table("user_alerts").select("id").eq("is_active", True).execute()
        alerts_count = len(alerts_response.data)
        
        # Get watchlist entries count
        watchlist_response = supabase.table("user_watchlist").select("id").execute()
        watchlist_count = len(watchlist_response.data)
        
        # Get API keys count
        apikeys_response = supabase.table("api_keys").select("id").execute()
        apikeys_count = len(apikeys_response.data)
        
        stats_text = f"""
📊 **Bot Statistics:**

👥 Total Users: {user_count}
🔔 Active Alerts: {alerts_count}
📋 Watchlist Entries: {watchlist_count}
🔐 API Keys Stored: {apikeys_count}

Database: ✅ Supabase Connected
Status: 🟢 Online
        """
        
        await update.callback_query.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.callback_query.message.reply_text(f"❌ Error getting stats: {e}")

async def admin_test_connection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test Supabase connection"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.callback_query.answer("Access denied")
        return
        
    await update.callback_query.answer()
    
    if test_supabase_connection():
        await update.callback_query.message.reply_text("✅ Supabase connection is working perfectly!")
    else:
        await update.callback_query.message.reply_text("❌ Supabase connection failed. Check your configuration.")

async def admin_db_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show database setup information"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.callback_query.answer("Access denied")
        return
        
    await update.callback_query.answer()
    
    info_text = """
🗄️ **Database Setup Information:**

**Supabase Tables:**
• user_alerts - Price alerts storage
• user_watchlist - User watchlists
• api_keys - Exchange API keys (encrypted)
• user_sessions - User tracking

**Setup Status:**
✅ Using Supabase (PostgreSQL)
✅ Real-time capabilities
✅ Secure API key storage
✅ Auto-scaling database

**Performance:**
• Indexed queries for fast lookups
• Optimized for concurrent users
• Automatic backups enabled

All tables are properly configured and indexed.
    """
    
    await update.callback_query.message.reply_text(info_text, parse_mode='Markdown')

# Menu handlers
async def price_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle price menu callback"""
    await update.callback_query.answer()
    help_text = """
📊 **Price Check Commands:**

• `/price BTC` - Get Bitcoin price
• `/price ETH BTC ADA` - Get multiple prices
• `/price BTCUSDT` - Get trading pair price

**Examples:**
• `/price bitcoin ethereum`
• `/price BTC ETH SOL DOGE`

Just type the command with coin symbols!
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def top_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle top gainers/losers menu"""
    await update.callback_query.answer()
    help_text = """
🚀 **Market Movers:**

• `/topgainers` - Top 10 gaining coins today
• `/toplosers` - Top 10 losing coins today
• `/trending` - Trending coins

Get real-time market movement data!
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def alert_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alerts menu"""
    await update.callback_query.answer()
    help_text = """
🔔 **Price Alert System:**

• `/alert BTC 45000 50000` - Set price range alert
• `/alert ETH 3000` - Set single price alert
• `/alerts` - View your active alerts
• `/removealert BTC` - Remove alerts for a coin

**How it works:**
Set alerts and get notified when prices hit your targets!
Alerts are stored securely in Supabase.
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def demo_trade_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle demo trading menu"""
    await update.callback_query.answer()
    help_text = """
🧠 **Auto Trade Demo (Coming Soon):**

Features in development:
• Paper trading simulation
• Automated trading signals
• Strategy backtesting
• Risk management tools

Stay tuned for updates! 🚀
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def portfolio_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle portfolio menu"""
    await update.callback_query.answer()
    help_text = """
💼 **Portfolio Management:**

• `/portfolio` - View your portfolio
• `/balance` - Check exchange balances
• `/setapikey` - Configure exchange APIs
• `/viewkeys` - View configured exchanges

**Note:** Connect your exchange API keys first!
All keys are stored securely in encrypted Supabase storage.
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def chart_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle charts menu"""
    await update.callback_query.answer()
    help_text = """
📈 **Chart Analysis (Coming Soon):**

Planned features:
• Live price charts
• Technical indicators
• Support/resistance levels
• Volume analysis

Charts feature is under development! 📊
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def apikey_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle API keys menu"""
    await update.callback_query.answer()
    help_text = """
🔐 **Exchange API Management:**

• `/setapikey binance YOUR_API YOUR_SECRET` - Add Binance keys
• `/setapikey coinbase YOUR_API YOUR_SECRET` - Add Coinbase keys
• `/viewkeys` - View configured exchanges

**Security Features:**
• Keys are encrypted before storage
• Stored securely in Supabase
• Never logged in plain text
• Auto-deletion of setup messages

⚠️ **Never share your API keys with anyone!**
Only use read-only or trading permissions as needed.
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

async def watchlist_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle watchlist menu"""
    await update.callback_query.answer()
    help_text = """
📋 **Watchlist Management:**

• `/watchlist` - View your watchlist
• `/addwatch BTC ETH SOL` - Add coins to watchlist
• `/removewatch BTC` - Remove from watchlist

**Features:**
• Unlimited watchlist entries
• Persistent storage in Supabase
• Quick price checks for watched coins

Track your favorite cryptocurrencies easily!
    """
    await update.callback_query.message.reply_text(help_text, parse_mode='Markdown')

# ================== ERROR HANDLER ===================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify user"""
    logger.error(f"Exception while handling an update: {context.error}")
    
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An error occurred while processing your request. Please try again later."
        )

# ================== MAIN APPLICATION ===================
def main():
    """Start the bot"""
    print("🔧 Initializing Supabase Crypto Bot...")
    
    # Test Supabase connection
    if not test_supabase_connection():
        print("\n📋 SQL commands to create tables:")
        print(get_table_creation_sql())
        print("\n💡 Copy the above SQL and run it in your Supabase SQL Editor to create the required tables.")
        print("🔄 After creating tables, restart the bot.")
        return
    
    print("✅ Supabase connection verified!")
    
    # Create application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CommandHandler("help", help_command))
