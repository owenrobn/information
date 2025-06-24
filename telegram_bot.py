import logging
import asyncio
import os
import aiohttp
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [6685099030]

if not all([SUPABASE_URL, SUPABASE_KEY, BOT_TOKEN]):
    print("❌ Missing environment variables")
    exit(1)

try:
    from supabase import create_client, Client
    if not SUPABASE_URL.startswith(('http://', 'https://')):
        SUPABASE_URL = 'https://' + SUPABASE_URL
    supabase: Client = create_client(SUPABASE_URL.rstrip('/'), SUPABASE_KEY)
    print("✅ Supabase connected")
except Exception as e:
    print(f"❌ Supabase failed: {e}")
    supabase = None

user_data = {'alerts': {}, 'watchlists': {}, 'portfolios': {}, 'sessions': {}, 'demo_accounts': {}}

SYMBOL_MAP = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'BNB': 'binancecoin', 'SOL': 'solana',
    'ADA': 'cardano', 'DOT': 'polkadot', 'LINK': 'chainlink', 'MATIC': 'matic-network',
    'UNI': 'uniswap', 'LTC': 'litecoin', 'AVAX': 'avalanche-2', 'ATOM': 'cosmos',
    'XRP': 'ripple', 'DOGE': 'dogecoin', 'SHIB': 'shiba-inu'
}

import json

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

# Demo Account Management Functions
def create_demo_account(user_id, starting_balance=10000.0):
    """Create a new demo account with starting balance"""
    def db_op():
        # Check if account exists
        existing = supabase.table("demo_accounts").select("*").eq("user_id", user_id).execute()
        if not existing.data:
            supabase.table("demo_accounts").insert({
                "user_id": user_id,
                "balance": starting_balance,
                "total_invested": 0.0,
                "total_profit_loss": 0.0,
                "created_at": datetime.now().isoformat()
            }).execute()
        return True
    
    def fallback_op():
        if user_id not in user_data['demo_accounts']:
            user_data['demo_accounts'][user_id] = {
                'balance': starting_balance,
                'total_invested': 0.0,
                'total_profit_loss': 0.0,
                'transactions': [],
                'created_at': datetime.now()
            }
        return True
    
    return safe_db_op(db_op, fallback_op)

def get_demo_account(user_id):
    """Get demo account info"""
    def db_op():
        result = supabase.table("demo_accounts").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None
    
    def fallback_op():
        return user_data['demo_accounts'].get(user_id)
    
    account = safe_db_op(db_op, fallback_op)
    if not account:
        create_demo_account(user_id)
        return get_demo_account(user_id)
    return account

def update_demo_balance(user_id, new_balance, total_invested=None):
    """Update demo account balance"""
    def db_op():
        update_data = {"balance": new_balance}
        if total_invested is not None:
            update_data["total_invested"] = total_invested
        supabase.table("demo_accounts").update(update_data).eq("user_id", user_id).execute()
        return True
    
    def fallback_op():
        if user_id in user_data['demo_accounts']:
            user_data['demo_accounts'][user_id]['balance'] = new_balance
            if total_invested is not None:
                user_data['demo_accounts'][user_id]['total_invested'] = total_invested
        return True
    
    return safe_db_op(db_op, fallback_op)

def add_transaction(user_id, transaction_type, symbol, amount, price, total_cost):
    """Add transaction to history"""
    def db_op():
        supabase.table("demo_transactions").insert({
            "user_id": user_id,
            "transaction_type": transaction_type,  # 'buy' or 'sell'
            "symbol": symbol,
            "amount": amount,
            "price": price,
            "total_cost": total_cost,
            "timestamp": datetime.now().isoformat()
        }).execute()
        return True
    
    def fallback_op():
        if user_id not in user_data['demo_accounts']:
            create_demo_account(user_id)
        if 'transactions' not in user_data['demo_accounts'][user_id]:
            user_data['demo_accounts'][user_id]['transactions'] = []
        
        user_data['demo_accounts'][user_id]['transactions'].append({
            'type': transaction_type,
            'symbol': symbol,
            'amount': amount,
            'price': price,
            'total_cost': total_cost,
            'timestamp': datetime.now()
        })
        return True
    
    return safe_db_op(db_op, fallback_op)

def get_transaction_history(user_id, limit=10):
    """Get recent transaction history"""
    def db_op():
        result = supabase.table("demo_transactions").select("*").eq("user_id", user_id).order("timestamp", desc=True).limit(limit).execute()
        return result.data
    
    def fallback_op():
        account = user_data['demo_accounts'].get(user_id, {})
        transactions = account.get('transactions', [])
        return sorted(transactions, key=lambda x: x['timestamp'], reverse=True)[:limit]
    
    return safe_db_op(db_op, fallback_op) or []

def reset_demo_account(user_id, starting_balance=10000.0):
    """Reset demo account to starting balance"""
    def db_op():
        # Reset account
        supabase.table("demo_accounts").update({
            "balance": starting_balance,
            "total_invested": 0.0,
            "total_profit_loss": 0.0
        }).eq("user_id", user_id).execute()
        
        # Clear portfolio
        supabase.table("user_portfolio").delete().eq("user_id", user_id).execute()
        
        # Archive old transactions (mark as inactive instead of deleting)
        supabase.table("demo_transactions").update({"is_active": False}).eq("user_id", user_id).execute()
        return True
    
    def fallback_op():
        user_data['demo_accounts'][user_id] = {
            'balance': starting_balance,
            'total_invested': 0.0,
            'total_profit_loss': 0.0,
            'transactions': [],
            'created_at': datetime.now()
        }
        if user_id in user_data['portfolios']:
            user_data['portfolios'][user_id] = {}
        return True
    
    return safe_db_op(db_op, fallback_op)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_user_activity(user.id, user.username, user.first_name)
    keyboard = [
        [InlineKeyboardButton("📊 Prices", callback_data="price_help"), InlineKeyboardButton("🔔 Alerts", callback_data="alert_help")],
        [InlineKeyboardButton("📋 Watchlist", callback_data="watch_help"), InlineKeyboardButton("💼 Portfolio", callback_data="portfolio_help")],
        [InlineKeyboardButton("🛠 Admin", callback_data="admin_panel") if user.id in ADMIN_IDS else InlineKeyboardButton("❓ Help", callback_data="general_help")]
    ]
    await update.message.reply_text(
        f"🤖 Welcome {user.first_name}!\nYour Crypto Trading Assistant is ready.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def topgainers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                top = sorted(data, key=lambda x: x['price_change_percentage_24h'], reverse=True)[:5]
                msg = "🚀 Top Gainers (24h):\n"
                for coin in top:
                    msg += f"{coin['symbol'].upper()}: ${coin['current_price']} ({coin['price_change_percentage_24h']:.2f}%)\n"
                await update.message.reply_text(msg)
    except:
        await update.message.reply_text("Failed to fetch top gainers.")

async def toplosers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                worst = sorted(data, key=lambda x: x['price_change_percentage_24h'])[:5]
                msg = "📉 Top Losers (24h):\n"
                for coin in worst:
                    msg += f"{coin['symbol'].upper()}: ${coin['current_price']} ({coin['price_change_percentage_24h']:.2f}%)\n"
                await update.message.reply_text(msg)
    except:
        await update.message.reply_text("Failed to fetch top losers.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /price BTC ETH to check prices. Use /portfolio to track holdings. Use /alert to set price alerts.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /help.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "price_help":
        await query.edit_message_text("Use /price BTC ETH to check prices.")
    elif data == "alert_help":
        await query.edit_message_text("Use /alert BTC 50000 or /alert BTC 45000 55000 to set alerts.")
    elif data == "watch_help":
        await query.edit_message_text("Use /watchlist to see coins. /addwatch BTC to add.")
    elif data == "portfolio_help":
        await query.edit_message_text(
            "*Demo Trading Commands:*\n"
            "/balance - View account summary\n"
            "/buy BTC 0.1 30000 - Buy crypto\n"
            "/sell BTC 0.1 32000 - Sell crypto\n"
            "/portfolio - View holdings\n"
            "/pnl - Profit/Loss analysis\n"
            "/history - Transaction history\n"
            "/resetdemo - Reset demo account"
        )
    elif data == "admin_panel":
        await query.edit_message_text("Admin Panel: coming soon.")
    elif data == "general_help":
        await query.edit_message_text(
            "*Available Commands:*\n"
            "/help - Show this help\n"
            "/price BTC ETH - Check prices\n"
            "/balance - Demo account status\n"
            "/buy - Buy crypto (demo)\n"
            "/sell - Sell crypto (demo)\n"
            "/topgainers - Top gaining coins\n"
            "/toplosers - Top losing coins\n"
            "/chart BTC - Simple price chart"
        )
    elif data.startswith("reset_confirm_"):
        user_id = int(data.split("_")[2])
        if user_id == query.from_user.id:  # Security check
            reset_demo_account(user_id)
            await query.edit_message_text(
                "✅ *DEMO ACCOUNT RESET SUCCESSFUL*\n\n"
                "💰 Balance: $10,000.00\n"
                "📊 Portfolio: Empty\n"
                "📋 Transactions: Archived\n\n"
                "🚀 Ready to start trading! Use /buy to make your first trade."
            )
        else:
            await query.edit_message_text("❌ Unauthorized reset attempt.")
    elif data == "reset_cancel":
        await query.edit_message_text("❌ Demo account reset cancelled.")

async def background_alert_scanner(app):
    import time
    await asyncio.sleep(5)
    while True:
        try:
            url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        for coin in data:
                            change = coin.get("price_change_percentage_24h", 0)
                            symbol = coin['symbol'].upper()
                            if change >= 10:
                                msg = f"🚀 Pump Alert: {symbol} is up {change:.2f}% in 24h!"
                            elif change <= -10:
                                msg = f"💥 Dump Alert: {symbol} is down {change:.2f}% in 24h!"
                            else:
                                continue
                            for user_id in user_data['sessions']:
                                try:
                                    await app.bot.send_message(chat_id=user_id, text=msg)
                                except:
                                    pass
            await asyncio.sleep(600)
        except Exception as e:
            print("Alert scanner error:", e)
            await asyncio.sleep(600)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.getLogger(_name_).error(f"Error: {context.error}")
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠ An error occurred.")

async def chart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /chart BTC")
        return
    symbol = context.args[0].upper()
    chart_url = f"https://quickchart.io/chart?c={{type:'line',data:{{labels:['1h','2h','3h','4h','5h','6h'],datasets:[{{label:'{symbol}',data:[100,102,104,103,105,107]}}]}}}}"
    await update.message.reply_photo(photo=chart_url, caption=f"Mini Chart for {symbol}")

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /buy BTC 0.1 30000")
        return
    
    try:
        user_id = update.effective_user.id
        symbol = context.args[0].upper()
        amount = float(context.args[1])
        price = float(context.args[2])
        total_cost = amount * price
        
        # Get demo account
        account = get_demo_account(user_id)
        current_balance = account['balance'] if account else 0
        
        # Check if user has enough balance
        if current_balance < total_cost:
            await update.message.reply_text(
                f"❌ Insufficient balance!\n"
                f"💰 Current balance: ${current_balance:,.2f}\n"
                f"💸 Required: ${total_cost:,.2f}\n"
                f"📊 Use /balance to check your demo account"
            )
            return
        
        # Execute the trade
        add_to_portfolio(user_id, symbol, amount, price)
        new_balance = current_balance - total_cost
        total_invested = account.get('total_invested', 0) + total_cost
        update_demo_balance(user_id, new_balance, total_invested)
        add_transaction(user_id, 'buy', symbol, amount, price, total_cost)
        
        await update.message.reply_text(
            f"✅ *DEMO BUY ORDER EXECUTED*\n"
            f"🪙 Bought: {amount} {symbol}\n"
            f"💰 Price: ${price:,.2f}\n"
            f"💸 Total Cost: ${total_cost:,.2f}\n"
            f"💵 Remaining Balance: ${new_balance:,.2f}\n"
            f"📊 Use /portfolio to view holdings"
        )
        
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /buy BTC 0.1 30000")
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing buy order: {str(e)}")

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /sell BTC 0.1 32000")
        return
    
    try:
        user_id = update.effective_user.id
        symbol = context.args[0].upper()
        amount = float(context.args[1])
        sell_price = float(context.args[2])
        
        portfolio = get_user_portfolio(user_id)
        
        if symbol not in portfolio or portfolio[symbol]['amount'] < amount:
            available = portfolio.get(symbol, {}).get('amount', 0)
            await update.message.reply_text(
                f"❌ Insufficient holdings!\n"
                f"🪙 Available {symbol}: {available}\n"
                f"📊 Use /portfolio to view holdings"
            )
            return
        
        # Calculate profit/loss
        buy_price = portfolio[symbol]['avg_price']
        total_sale = amount * sell_price
        cost_basis = amount * buy_price
        profit_loss = total_sale - cost_basis
        
        # Update portfolio
        old_amount = portfolio[symbol]['amount']
        new_amount = old_amount - amount
        
        if new_amount == 0:
            # Remove from portfolio if sold all
            if supabase:
                supabase.table("user_portfolio").delete().eq("user_id", user_id).eq("symbol", symbol).execute()
            if user_id in user_data['portfolios'] and symbol in user_data['portfolios'][user_id]:
                del user_data['portfolios'][user_id][symbol]
        else:
            # Update remaining amount
            if supabase:
                supabase.table("user_portfolio").update({"amount": new_amount}).eq("user_id", user_id).eq("symbol", symbol).execute()
            if user_id in user_data['portfolios']:
                user_data['portfolios'][user_id][symbol]['amount'] = new_amount
        
        # Update demo account balance
        account = get_demo_account(user_id)
        new_balance = account['balance'] + total_sale
        update_demo_balance(user_id, new_balance)
        add_transaction(user_id, 'sell', symbol, amount, sell_price, -total_sale)
        
        profit_emoji = "📈" if profit_loss >= 0 else "📉"
        profit_text = f"+${profit_loss:.2f}" if profit_loss >= 0 else f"-${abs(profit_loss):.2f}"
        
        await update.message.reply_text(
            f"✅ *DEMO SELL ORDER EXECUTED*\n"
            f"🪙 Sold: {amount} {symbol}\n"
            f"💰 Sale Price: ${sell_price:,.2f}\n"
            f"💸 Total Received: ${total_sale:,.2f}\n"
            f"{profit_emoji} P&L: {profit_text}\n"
            f"💵 New Balance: ${new_balance:,.2f}\n"
            f"📊 Use /portfolio to view remaining holdings"
        )
        
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /sell BTC 0.1 32000")
    except Exception as e:
        await update.message.reply_text(f"❌ Error processing sell order: {str(e)}")

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    account = get_demo_account(user_id)
    portfolio = get_user_portfolio(user_id)
    
    if not portfolio:
        portfolio_value = 0
        portfolio_text = "No holdings"
    else:
        # Get current prices for portfolio valuation
        prices = await get_crypto_prices(list(portfolio.keys()))
        portfolio_value = 0
        portfolio_items = []
        
        for symbol, data in portfolio.items():
            current_price = prices.get(symbol, {}).get('price', 0)
            holding_value = data['amount'] * current_price
            portfolio_value += holding_value
            portfolio_items.append(f"  • {symbol}: {data['amount']} @ ${current_price:,.2f} = ${holding_value:,.2f}")
        
        portfolio_text = "\n".join(portfolio_items) if portfolio_items else "No holdings"
    
    total_account_value = account['balance'] + portfolio_value
    total_invested = account.get('total_invested', 0)
    overall_pnl = total_account_value - 10000  # Assuming $10k starting balance
    
    await update.message.reply_text(
        f"💰 *DEMO ACCOUNT SUMMARY*\n\n"
        f"💵 Cash Balance: ${account['balance']:,.2f}\n"
        f"📊 Portfolio Value: ${portfolio_value:,.2f}\n"
        f"💎 Total Account Value: ${total_account_value:,.2f}\n\n"
        f"📈 Overall P&L: ${overall_pnl:+,.2f}\n"
        f"💸 Total Invested: ${total_invested:,.2f}\n\n"
        f"🪙 *Current Holdings:*\n{portfolio_text}\n\n"
        f"ℹ This is a demo account with virtual money"
    )

async def reset_demo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Create confirmation keyboard
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Reset Account", callback_data=f"reset_confirm_{user_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="reset_cancel")]
    ]
    
    await update.message.reply_text(
        "⚠ *RESET DEMO ACCOUNT*\n\n"
        "This will:\n"
        "• Reset your balance to $10,000\n"
        "• Clear all holdings\n"
        "• Archive transaction history\n\n"
        "Are you sure you want to continue?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def transaction_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    transactions = get_transaction_history(user_id, 15)
    
    if not transactions:
        await update.message.reply_text("📋 No transaction history found.")
        return
    
    msg = "📋 *RECENT TRANSACTIONS* (Last 15)\n\n"
    
    for i, tx in enumerate(transactions, 1):
        tx_type = tx.get('transaction_type', tx.get('type', 'unknown'))
        symbol = tx['symbol']
        amount = tx['amount']
        price = tx['price']
        total = abs(tx.get('total_cost', amount * price))
        
        # Handle timestamp
        timestamp = tx.get('timestamp')
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                timestamp = datetime.now()
        elif not timestamp:
            timestamp = datetime.now()
        
        time_str = timestamp.strftime("%m/%d %H:%M")
        
        if tx_type.lower() == 'buy':
            msg += f"{i}. 🟢 BUY {amount} {symbol} @ ${price:,.2f} = ${total:,.2f} [{time_str}]\n"
        else:
            msg += f"{i}. 🔴 SELL {amount} {symbol} @ ${price:,.2f} = ${total:,.2f} [{time_str}]\n"
    
    msg += "\n💡 Use /balance to see current account status"
    await update.message.reply_text(msg)

from telegram.ext import CommandHandler

async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    portfolio = get_user_portfolio(user_id)
    account = get_demo_account(user_id)
    
    if not portfolio:
        await update.message.reply_text("Your demo portfolio is empty. Use /buy to start trading!")
        return
    
    prices = await get_crypto_prices(list(portfolio.keys()))
    msg = "📊 *PORTFOLIO P&L ANALYSIS*\n\n"
    total_pnl = 0
    total_value = 0
    
    for sym, data in portfolio.items():
        current_price = prices.get(sym, {}).get('price', 0)
        avg_price = data['avg_price']
        amount = data['amount']
        
        current_value = current_price * amount
        cost_basis = avg_price * amount
        pnl = current_value - cost_basis
        pnl_percent = (pnl / cost_basis * 100) if cost_basis > 0 else 0
        
        total_pnl += pnl
        total_value += current_value
        
        pnl_emoji = "📈" if pnl >= 0 else "📉"
        pnl_text = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        percent_text = f"+{pnl_percent:.1f}%" if pnl_percent >= 0 else f"{pnl_percent:.1f}%"
        
        msg += f"🪙 *{sym}*\n"
        msg += f"  Amount: {amount}\n"
        msg += f"  Avg Buy: ${avg_price:.2f} → Current: ${current_price:.2f}\n"
        msg += f"  Value: ${current_value:.2f} | P&L: {pnl_text} ({percent_text})\n\n"
    
    overall_pnl_emoji = "📈" if total_pnl >= 0 else "📉"
    total_pnl_text = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
    
    msg += f"💰 *TOTALS*\n"
    msg += f"Portfolio Value: ${total_value:.2f}\n"
    msg += f"Cash Balance: ${account['balance']:.2f}\n"
    msg += f"{overall_pnl_emoji} Total P&L: {total_pnl_text}\n\n"
    msg += f"💡 Use /balance for complete account overview"
    
    await update.message.reply_text(msg)

async def post_init(app):
    """Initialize background tasks after the app starts"""
    app.create_task(background_alert_scanner(app))

def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    handlers = [
        CommandHandler("start", start),
        CommandHandler("help", help_command),
        CommandHandler("balance", balance_command),
        CommandHandler("buy", buy_command),
        CommandHandler("sell", sell_command),
        CommandHandler("portfolio", pnl_command),  # Using pnl_command for portfolio
        CommandHandler("pnl", pnl_command),
        CommandHandler("history", transaction_history_command),
        CommandHandler("resetdemo", reset_demo_command),
        CommandHandler("topgainers", topgainers_command),
        CommandHandler("toplosers", toplosers_command),
        CommandHandler("chart", chart_command),
        CallbackQueryHandler(callback_handler),
        MessageHandler(filters.COMMAND, unknown)
    ]

    for handler in handlers:
        app.add_handler(handler)

    app.add_error_handler(error_handler)
    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "_main_":
    main()
