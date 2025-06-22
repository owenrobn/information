import logging
import asyncio
import os
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Config
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [6685099030]

# Validate required environment variables
if not all([SUPABASE_URL, SUPABASE_KEY, BOT_TOKEN]):
    print("❌ Missing environment variables")
    exit(1)

# Initialize Supabase
try:
    from supabase import create_client, Client
    if not SUPABASE_URL.startswith(('http://', 'https://')):
        SUPABASE_URL = 'https://' + SUPABASE_URL
    supabase: Client = create_client(SUPABASE_URL.rstrip('/'), SUPABASE_KEY)
    print("✅ Supabase connected")
except Exception as e:
    print(f"❌ Supabase failed: {e}")
    supabase = None

# In-memory storage fallback
user_data = {'alerts': {}, 'watchlists': {}, 'portfolios': {}, 'sessions': {}}

# Crypto symbol mapping for API
SYMBOL_MAP = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin', 'SOL': 'solana',
    'ADA': 'cardano', 'DOT': 'polkadot', 'LINK': 'chainlink', 'MATIC': 'matic-network',
    'UNI': 'uniswap', 'LTC': 'litecoin', 'AVAX': 'avalanche-2', 'ATOM': 'cosmos',
    'XRP': 'ripple', 'DOGE': 'dogecoin', 'SHIB': 'shiba-inu'
}

# API Functions
async def get_crypto_prices(symbols):
    try:
        coin_ids = [SYMBOL_MAP.get(s.upper(), s.lower()) for s in symbols]
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(coin_ids)}&vs_currencies=usd&include_24hr_change=true"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {symbols[i].upper(): {'price': data[coin_ids[i]]['usd'], 'change_24h': data[coin_ids[i]].get('usd_24h_change', 0)} 
                           for i, coin_id in enumerate(coin_ids) if coin_id in data}
        return {}
    except:
        return {}

async def get_market_overview():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.coingecko.com/api/v3/global") as response:
                if response.status == 200:
                    data = (await response.json())['data']
                    return {
                        'total_market_cap': data['total_market_cap']['usd'],
                        'total_volume': data['total_volume']['usd'],
                        'market_cap_change_24h': data['market_cap_change_percentage_24h_usd'],
                        'btc_dominance': data['market_cap_percentage']['btc']
                    }
    except:
        return None

# Database operations with fallback
def safe_db_op(db_op, fallback_op):
    try:
        return db_op() if supabase else fallback_op()
    except:
        return fallback_op()

def log_user_activity(user_id, username=None, first_name=None):
    def db_op():
        supabase.table("user_sessions").upsert({"user_id": user_id, "username": username, "first_name": first_name, "last_active": datetime.now().isoformat()}).execute()
        return True
    def fallback_op():
        user_data['sessions'][user_id] = {'username': username, 'first_name': first_name, 'last_active': datetime.now()}
        return True
    return safe_db_op(db_op, fallback_op)

def get_user_alerts(user_id):
    def db_op():
        return supabase.table("user_alerts").select("*").eq("user_id", user_id).eq("is_active", True).execute().data
    return safe_db_op(db_op, lambda: user_data['alerts'].get(user_id, [])) or []

def add_user_alert(user_id, symbol, price=None, min_price=None, max_price=None):
    def db_op():
        alert_data = {"user_id": user_id, "symbol": symbol.upper(), "alert_type": "price_range" if min_price and max_price else "single_price"}
        if price: alert_data["price"] = float(price)
        if min_price: alert_data["min_price"] = float(min_price)
        if max_price: alert_data["max_price"] = float(max_price)
        supabase.table("user_alerts").insert(alert_data).execute()
        return True
    def fallback_op():
        if user_id not in user_data['alerts']: user_data['alerts'][user_id] = []
        alert = {'symbol': symbol.upper(), 'type': 'range' if min_price and max_price else 'single'}
        if price: alert['price'] = float(price)
        if min_price: alert['min_price'] = float(min_price)
        if max_price: alert['max_price'] = float(max_price)
        user_data['alerts'][user_id].append(alert)
        return True
    return safe_db_op(db_op, fallback_op)

def remove_user_alerts(user_id, symbol):
    def db_op():
        supabase.table("user_alerts").update({"is_active": False}).eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        return True
    def fallback_op():
        if user_id in user_data['alerts']:
            user_data['alerts'][user_id] = [a for a in user_data['alerts'][user_id] if a['symbol'] != symbol.upper()]
        return True
    return safe_db_op(db_op, fallback_op)

def get_user_watchlist(user_id):
    def db_op():
        return [item["symbol"] for item in supabase.table("user_watchlist").select("symbol").eq("user_id", user_id).execute().data]
    return safe_db_op(db_op, lambda: user_data['watchlists'].get(user_id, [])) or []

def add_to_watchlist(user_id, symbols):
    def db_op():
        for symbol in symbols:
            supabase.table("user_watchlist").upsert({"user_id": user_id, "symbol": symbol.upper()}).execute()
        return True
    def fallback_op():
        if user_id not in user_data['watchlists']: user_data['watchlists'][user_id] = []
        for symbol in symbols:
            if symbol.upper() not in user_data['watchlists'][user_id]:
                user_data['watchlists'][user_id].append(symbol.upper())
        return True
    return safe_db_op(db_op, fallback_op)

def remove_from_watchlist(user_id, symbol):
    def db_op():
        supabase.table("user_watchlist").delete().eq("user_id", user_id).eq("symbol", symbol.upper()).execute()
        return True
    def fallback_op():
        if user_id in user_data['watchlists']:
            try: user_data['watchlists'][user_id].remove(symbol.upper())
            except ValueError: pass
        return True
    return safe_db_op(db_op, fallback_op)

def get_user_portfolio(user_id):
    def db_op():
        data = supabase.table("user_portfolio").select("*").eq("user_id", user_id).execute().data
        return {item["symbol"]: {"amount": item["amount"], "avg_price": item["avg_price"]} for item in data}
    return safe_db_op(db_op, lambda: user_data['portfolios'].get(user_id, {})) or {}

def add_to_portfolio(user_id, symbol, amount, price):
    def db_op():
        existing = supabase.table("user_portfolio").select("*").eq("user_id", user_id).eq("symbol", symbol).execute()
        if existing.data:
            old_amount, old_avg_price = existing.data[0]["amount"], existing.data[0]["avg_price"]
            new_amount = old_amount + amount
            new_avg_price = ((old_amount * old_avg_price) + (amount * price)) / new_amount
            supabase.table("user_portfolio").update({"amount": new_amount, "avg_price": new_avg_price}).eq("user_id", user_id).eq("symbol", symbol).execute()
        else:
            supabase.table("user_portfolio").insert({"user_id": user_id, "symbol": symbol, "amount": amount, "avg_price": price}).execute()
        return True
    def fallback_op():
        if user_id not in user_data['portfolios']: user_data['portfolios'][user_id] = {}
        if symbol in user_data['portfolios'][user_id]:
            old_amount = user_data['portfolios'][user_id][symbol]['amount']
            old_avg_price = user_data['portfolios'][user_id][symbol]['avg_price']
            new_amount = old_amount + amount
            new_avg_price = ((old_amount * old_avg_price) + (amount * price)) / new_amount
            user_data['portfolios'][user_id][symbol] = {'amount': new_amount, 'avg_price': new_avg_price}
        else:
            user_data['portfolios'][user_id][symbol] = {'amount': amount, 'avg_price': price}
        return True
    return safe_db_op(db_op, fallback_op)

# Bot setup
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_user_activity(user.id, user.username, user.first_name)
    
    keyboard = [
        [InlineKeyboardButton("📊 Prices", callback_data="price_help"), InlineKeyboardButton("🔔 Alerts", callback_data="alert_help")],
        [InlineKeyboardButton("📋 Watchlist", callback_data="watch_help"), InlineKeyboardButton("💼 Portfolio", callback_data="portfolio_help")],
        [InlineKeyboardButton("🛠 Admin", callback_data="admin_panel") if user.id in ADMIN_IDS else InlineKeyboardButton("❓ Help", callback_data="general_help")]
    ]
    
    await update.message.reply_text(f"🤖 Welcome {user.first_name}!\n\nYour Crypto Trading Assistant is ready.\nChoose an option below:", reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """🤖 **Crypto Bot Commands:**

**Prices:** `/price BTC ETH` • `/market` • `/top10`
**Alerts:** `/alert BTC 45000` • `/alerts` • `/removealert BTC`
**Watchlist:** `/watchlist` • `/addwatch BTC ETH` • `/removewatch BTC`
**Portfolio:** `/portfolio` • `/addholding BTC 0.5 45000` • `/pnl`
**Info:** `/status` • `/start`"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/price BTC ETH SOL`", parse_mode='Markdown')
        return
    
    symbols = [arg.upper() for arg in context.args[:10]]
    await update.message.reply_text("🔄 Fetching prices...")
    prices = await get_crypto_prices(symbols)
    
    if not prices:
        await update.message.reply_text("❌ Unable to fetch prices.")
        return
    
    price_text = "📊 **Current Prices:**\n\n"
    for symbol in symbols:
        if symbol in prices:
            price_data = prices[symbol]
            change_emoji = "🟢" if price_data['change_24h'] >= 0 else "🔴"
            price_text += f"{change_emoji} **{symbol}**: ${price_data['price']:,.2f} ({price_data['change_24h']:+.2f}%)\n"
        else:
            price_text += f"❌ **{symbol}**: Price not found\n"
    
    await update.message.reply_text(price_text, parse_mode='Markdown')

async def market_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Fetching market data...")
    market_data = await get_market_overview()
    
    if not market_data:
        await update.message.reply_text("❌ Unable to fetch market data.")
        return
    
    market_text = f"""📈 **Market Overview:**
💰 **Total Market Cap**: ${market_data['total_market_cap']:,.0f}
📊 **24h Volume**: ${market_data['total_volume']:,.0f}
📉 **Market Cap Change**: {market_data['market_cap_change_24h']:+.2f}%
₿ **BTC Dominance**: {market_data['btc_dominance']:.1f}%"""
    
    await update.message.reply_text(market_text, parse_mode='Markdown')

async def top10_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_coins = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOT', 'LINK', 'MATIC']
    await update.message.reply_text("🔄 Fetching top 10...")
    prices = await get_crypto_prices(top_coins)
    
    if not prices:
        await update.message.reply_text("❌ Unable to fetch data.")
        return
    
    top_text = "🏆 **Top 10 Cryptocurrencies:**\n\n"
    for i, symbol in enumerate(top_coins, 1):
        if symbol in prices:
            price_data = prices[symbol]
            change_emoji = "🟢" if price_data['change_24h'] >= 0 else "🔴"
            top_text += f"{i}. {change_emoji} **{symbol}**: ${price_data['price']:,.2f} ({price_data['change_24h']:+.2f}%)\n"
    
    await update.message.reply_text(top_text, parse_mode='Markdown')

async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    portfolio = get_user_portfolio(user_id)
    
    if not portfolio:
        await update.message.reply_text("💼 Portfolio empty. Use `/addholding BTC 0.5 45000`!", parse_mode='Markdown')
        return
    
    symbols = list(portfolio.keys())
    current_prices = await get_crypto_prices(symbols)
    
    portfolio_text = "💼 **Your Portfolio:**\n\n"
    total_value = total_cost = 0
    
    for symbol, holding in portfolio.items():
        amount, avg_price = holding['amount'], holding['avg_price']
        cost_basis = amount * avg_price
        
        if symbol in current_prices:
            current_price = current_prices[symbol]['price']
            current_value = amount * current_price
            pnl = current_value - cost_basis
            pnl_percent = (pnl / cost_basis) * 100
            
            total_value += current_value
            total_cost += cost_basis
            
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            portfolio_text += f"{pnl_emoji} **{symbol}**: {amount:.6f} | ${current_value:,.2f} | P&L: ${pnl:+,.2f} ({pnl_percent:+.2f}%)\n"
    
    if total_cost > 0:
        total_pnl = total_value - total_cost
        total_pnl_percent = (total_pnl / total_cost) * 100
        total_emoji = "🟢" if total_pnl >= 0 else "🔴"
        portfolio_text += f"\n📊 **Total:** {total_emoji} ${total_value:,.2f} | P&L: ${total_pnl:+,.2f} ({total_pnl_percent:+.2f}%)"
    
    await update.message.reply_text(portfolio_text, parse_mode='Markdown')

async def addholding_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        await update.message.reply_text("Usage: `/addholding BTC 0.5 45000`", parse_mode='Markdown')
        return
    
    try:
        symbol, amount, price = context.args[0].upper(), float(context.args[1]), float(context.args[2])
        if amount <= 0 or price <= 0:
            await update.message.reply_text("❌ Amount and price must be positive")
            return
        
        if add_to_portfolio(update.effective_user.id, symbol, amount, price):
            await update.message.reply_text(f"✅ Added {amount} {symbol} at ${price:,.2f}")
        else:
            await update.message.reply_text("❌ Error adding to portfolio")
    except ValueError:
        await update.message.reply_text("❌ Invalid number format")

async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    portfolio = get_user_portfolio(update.effective_user.id)
    if not portfolio:
        await update.message.reply_text("💼 No portfolio data")
        return
    
    current_prices = await get_crypto_prices(list(portfolio.keys()))
    winners, losers = [], []
    
    for symbol, holding in portfolio.items():
        if symbol in current_prices:
            amount, avg_price = holding['amount'], holding['avg_price']
            current_price = current_prices[symbol]['price']
            pnl = (amount * current_price) - (amount * avg_price)
            pnl_percent = (pnl / (amount * avg_price)) * 100
            
            (winners if pnl >= 0 else losers).append((symbol, pnl, pnl_percent))
    
    pnl_text = "📊 **P&L Analysis:**\n\n"
    if winners:
        pnl_text += "🟢 **Winners:**\n" + "\n".join([f"• {s}: +${p:,.2f} (+{pp:.2f}%)" for s, p, pp in sorted(winners, key=lambda x: x[1], reverse=True)]) + "\n\n"
    if losers:
        pnl_text += "🔴 **Losers:**\n" + "\n".join([f"• {s}: ${p:,.2f} ({pp:.2f}%)" for s, p, pp in sorted(losers, key=lambda x: x[1])]) + "\n\n"
    
    total_pnl = sum([p for _, p, _ in winners + losers])
    pnl_text += f"{'🟢' if total_pnl >= 0 else '🔴'} **Total P&L**: ${total_pnl:+,.2f}"
    
    await update.message.reply_text(pnl_text, parse_mode='Markdown')

async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/alert BTC 45000` or `/alert BTC 45000 50000`", parse_mode='Markdown')
        return
    
    user_id, symbol = update.effective_user.id, context.args[0].upper()
    
    try:
        if len(context.args) == 2:
            price = float(context.args[1])
            if add_user_alert(user_id, symbol, price=price):
                await update.message.reply_text(f"✅ Alert set: {symbol} at ${price:,.2f}")
        elif len(context.args) == 3:
            min_price, max_price = float(context.args[1]), float(context.args[2])
            if min_price >= max_price:
                await update.message.reply_text("❌ Min price must be lower than max")
                return
            if add_user_alert(user_id, symbol, min_price=min_price, max_price=max_price):
                await update.message.reply_text(f"✅ Range alert: {symbol} ${min_price:,.2f} - ${max_price:,.2f}")
    except ValueError:
        await update.message.reply_text("❌ Invalid price format")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts = get_user_alerts(update.effective_user.id)
    if not alerts:
        await update.message.reply_text("🔔 No alerts. Use `/alert BTC 45000`!", parse_mode='Markdown')
        return
    
    alert_text = "🔔 **Your Alerts:**\n\n"
    for alert in alerts:
        symbol = alert.get('symbol')
        if alert.get('type') == 'single' or alert.get('alert_type') == 'single_price':
            alert_text += f"• {symbol}: ${alert.get('price'):,.2f}\n"
        else:
            alert_text += f"• {symbol}: ${alert.get('min_price'):,.2f} - ${alert.get('max_price'):,.2f}\n"
    
    await update.message.reply_text(alert_text, parse_mode='Markdown')

async def removealert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/removealert BTC`", parse_mode='Markdown')
        return
    
    symbol = context.args[0].upper()
    if remove_user_alerts(update.effective_user.id, symbol):
        await update.message.reply_text(f"✅ Alerts removed for {symbol}")

async def watchlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    watchlist = get_user_watchlist(update.effective_user.id)
    if not watchlist:
        await update.message.reply_text("📋 Watchlist empty. Use `/addwatch BTC ETH`!", parse_mode='Markdown')
        return
    
    # Get prices for watchlist
    prices = await get_crypto_prices(watchlist)
    text = "📋 **Your Watchlist:**\n\n"
    
    for symbol in watchlist:
        if symbol in prices:
            price_data = prices[symbol]
            change_emoji = "🟢" if price_data['change_24h'] >= 0 else "🔴"
            text += f"{change_emoji} **{symbol}**: ${price_data['price']:,.2f} ({price_data['change_24h']:+.2f}%)\n"
        else:
            text += f"• {symbol}: Price unavailable\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def addwatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/addwatch BTC ETH SOL`", parse_mode='Markdown')
        return
    
    symbols = [arg.upper() for arg in context.args]
    if add_to_watchlist(update.effective_user.id, symbols):
        await update.message.reply_text(f"✅ Added {', '.join(symbols)} to watchlist!")

async def removewatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/removewatch BTC`", parse_mode='Markdown')
        return
    
    symbol = context.args[0].upper()
    if remove_from_watchlist(update.effective_user.id, symbol):
        await update.message.reply_text(f"✅ Removed {symbol} from watchlist")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_status = "✅ Connected" if supabase else "❌ Memory storage"
    status_text = f"""🤖 **Bot Status:**
Database: {db_status}
Users: {len(user_data['sessions'])}
Alerts: {sum(len(alerts) for alerts in user_data['alerts'].values())}
Watchlists: {sum(len(wl) for wl in user_data['watchlists'].values())}"""
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    help_texts = {
        "price_help": "📊 **Price Commands:**\n• `/price BTC ETH` - Get current prices\n• `/market` - Market overview\n• `/top10` - Top 10 cryptocurrencies",
        "alert_help": "🔔 **Alert Commands:**\n• `/alert BTC 45000` - Single price alert\n• `/alert BTC 45000 50000` - Range alert\n• `/alerts` - View all alerts\n• `/removealert BTC` - Remove alerts",
        "watch_help": "📋 **Watchlist Commands:**\n• `/watchlist` - View watchlist with prices\n• `/addwatch BTC ETH` - Add coins to watchlist\n• `/removewatch BTC` - Remove coin from watchlist",
        "portfolio_help": "💼 **Portfolio Commands:**\n• `/portfolio` - View portfolio with P&L\n• `/addholding BTC 0.5 45000` - Add holding\n• `/pnl` - Detailed P&L analysis",
        "general_help": "❓ **Help:**\nUse `/help` for all commands\nUse `/status` for bot status\nUse `/start` for main menu",
        "admin_panel": "🛠 **Admin Panel:**\nDatabase status checked.\nUse `/status` for details." if update.effective_user.id in ADMIN_IDS else "❌ Access denied"
    }
    
    await query.message.reply_text(help_texts.get(query.data, "Unknown option"), parse_mode='Markdown')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.getLogger(__name__).error(f"Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again.")

def main():
    logging.getLogger(__name__).info("🚀 Starting Crypto Bot...")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Add all handlers
    handlers = [
        CommandHandler("start", start), CommandHandler("help", help_command),
        CommandHandler("price", price_command), CommandHandler("market", market_command), 
        CommandHandler("top10", top10_command), CommandHandler("portfolio", portfolio_command),
        CommandHandler("addholding", addholding_command), CommandHandler("pnl", pnl_command),
        CommandHandler("alert", alert_command), CommandHandler("alerts", alerts_command),
        CommandHandler("removealert", removealert_command), CommandHandler("watchlist", watchlist_command),
        CommandHandler("addwatch", addwatch_command), CommandHandler("removewatch", removewatch_command),
        CommandHandler("status", status_command), CallbackQueryHandler(callback_handler)
    ]
    
    for handler in handlers:
        app.add_handler(handler)
    
    app.add_error_handler(error_handler)
    
    print("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
