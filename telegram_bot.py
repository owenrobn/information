import os
import logging
from datetime import datetime, time
import pytz
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Your other imports
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from supabase import create_client, Client
from gotrue.errors import AuthApiError
import ccxt

# Configure logging to show INFO messages and above
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
PORT = int(os.environ.get('PORT', '10000')) # Use 10000 as default for Render

# --- Supabase Client ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Webhook Setup ---
WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}{WEBHOOK_PATH}" if RENDER_EXTERNAL_HOSTNAME else None

# --- Global Thread Pool Executor for potentially long-running tasks ---
executor = ThreadPoolExecutor(max_workers=5)

# --- Bot's State Management ---
# This is a simple dictionary for demonstration. In a real app, use a database.
user_states = {} # Stores current menu/action for each user

# --- Menu Keyboards ---
main_menu_keyboard = [
    [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard_menu")],
    [InlineKeyboardButton("💹 Trade", callback_data="trade_menu")],
    [InlineKeyboardButton("💰 Wallet", callback_data="wallet_menu")],
    [InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")],
    [InlineKeyboardButton("❓ Help", callback_data="help_menu")]
]

dashboard_menu_keyboard = [
    [InlineKeyboardButton("📈 Market Overview", callback_data="market_overview")],
    [InlineKeyboardButton("📜 My Positions", callback_data="my_positions")],
    [InlineKeyboardButton("↩️ Back to Main", callback_data="main_menu")]
]

trade_menu_keyboard = [
    [InlineKeyboardButton("🔄 Spot Trading", callback_data="spot_trading")],
    [InlineKeyboardButton("📈 Futures Trading", callback_data="futures_trading")],
    [InlineKeyboardButton("↩️ Back to Main", callback_data="main_menu")]
]

wallet_menu_keyboard = [
    [InlineKeyboardButton("💳 Deposit", callback_data="deposit")],
    [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw")],
    [InlineKeyboardButton("📊 Balance", callback_data="balance")],
    [InlineKeyboardButton("↩️ Back to Main", callback_data="main_menu")]
]

settings_menu_keyboard = [
    [InlineKeyboardButton("🔑 API Keys", callback_data="api_keys")],
    [InlineKeyboardButton("🔔 Notifications", callback_data="notifications")],
    [InlineKeyboardButton("↩️ Back to Main", callback_data="main_menu")]
]

# --- Helper Functions ---
async def fetch_market_data():
    exchange_id = 'binance'
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'enableRateLimit': True,
    })
    ticker = await exchange.fetch_ticker('BTC/USDT')
    return ticker

async def get_or_create_user(telegram_id: int, username: str):
    try:
        response = supabase.from_('users').select('*').eq('telegram_id', telegram_id).execute()
        user = response.data

        if not user:
            logger.info(f"Creating new user: {username} ({telegram_id})")
            response = supabase.from_('users').insert({
                'telegram_id': telegram_id,
                'username': username,
                'joined_at': datetime.now().isoformat()
            }).execute()
            user = response.data
        return user[0] if user else None
    except Exception as e:
        logger.error(f"Error getting or creating user: {e}")
        return None

# --- Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message on /start and initializes the user."""
    logger.info("Received /start command.")
    user = update.effective_user
    if user:
        db_user = await get_or_create_user(user.id, user.username)
        if db_user:
            update.message.reply_html(
                f"Hi {user.mention_html()}! I'm your trading bot. How can I assist you today?",
                reply_markup=InlineKeyboardMarkup(main_menu_keyboard)
            )
            user_states[user.id] = "main_menu"
        else:
            await update.message.reply_text("There was an error initializing your account. Please try again.")
    else:
        await update.message.reply_text("Could not identify user. Please try again from a Telegram account.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /help is issued."""
    logger.info("Received /help command.")
    await update.message.reply_text(
        "I'm a powerful trading bot that helps you manage your trades. "
        "Use the menu buttons to navigate features like dashboard, trading, wallet, and settings. "
        "If you need specific assistance, please contact support."
    )

# --- Callback Query Handlers ---
async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callbacks from inline keyboard buttons."""
    query = update.callback_query
    await query.answer() # Acknowledge the callback query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"Received callback query: {data} from user {user_id}")

    if data == "main_menu":
        await query.edit_message_text("Welcome back to the main menu!", reply_markup=InlineKeyboardMarkup(main_menu_keyboard))
        user_states[user_id] = "main_menu"
    elif data == "dashboard_menu":
        await query.edit_message_text("Welcome to your dashboard!", reply_markup=InlineKeyboardMarkup(dashboard_menu_keyboard))
        user_states[user_id] = "dashboard_menu"
    elif data == "trade_menu":
        await query.edit_message_text("Select a trading option:", reply_markup=InlineKeyboardMarkup(trade_menu_keyboard))
        user_states[user_id] = "trade_menu"
    elif data == "wallet_menu":
        await query.edit_message_text("Manage your wallet:", reply_markup=InlineKeyboardMarkup(wallet_menu_keyboard))
        user_states[user_id] = "wallet_menu"
    elif data == "settings_menu":
        await query.edit_message_text("Bot settings:", reply_markup=InlineKeyboardMarkup(settings_menu_keyboard))
        user_states[user_id] = "settings_menu"
    elif data == "help_menu":
        await query.edit_message_text(
            "I'm a powerful trading bot that helps you manage your trades. "
            "Use the menu buttons to navigate features like dashboard, trading, wallet, and settings. "
            "If you need specific assistance, please contact support.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back to Main", callback_data="main_menu")]])
        )
        user_states[user_id] = "help_menu"
    elif data == "market_overview":
        try:
            ticker = await fetch_market_data()
            message_text = (
                f"📊 Market Overview (BTC/USDT):\n"
                f"Last Price: ${ticker['last']:.2f}\n"
                f"High 24h: ${ticker['high']:.2f}\n"
                f"Low 24h: ${ticker['low']:.2f}\n"
                f"Volume 24h (BTC): {ticker['baseVolume']:.2f}\n"
                f"Volume 24h (USDT): {ticker['quoteVolume']:.2f}\n"
                f"Last Updated: {datetime.fromtimestamp(ticker['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')} UTC"
            )
            await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(dashboard_menu_keyboard))
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            await query.edit_message_text("Could not fetch market data at this time. Please try again later.", reply_markup=InlineKeyboardMarkup(dashboard_menu_keyboard))
        user_states[user_id] = "dashboard_menu"
    # Add handlers for other specific buttons (spot_trading, futures_trading, deposit, withdraw, balance, api_keys, notifications)
    else:
        logger.warning(f"Unhandled callback data: {data}")
        await query.edit_message_text("Functionality not yet implemented. Please choose from the menu.", reply_markup=InlineKeyboardMarkup(main_menu_keyboard))


# --- General Message Handler (Fallback for unhandled text) ---
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles general text input from the user."""
    user_id = update.effective_user.id
    text = update.message.text
    logger.info(f"Received text input: '{text}' from user {user_id}. Current state: {user_states.get(user_id)}")

    # Example: If a user types something in the main menu context
    if user_states.get(user_id) == "main_menu":
        await update.message.reply_text("Please use the menu buttons to navigate.", reply_markup=InlineKeyboardMarkup(main_menu_keyboard))
    else:
        await update.message.reply_text("I'm not sure how to respond to that. Please use the menu buttons or try a command like /start.", reply_markup=InlineKeyboardMarkup(main_menu_keyboard))


# --- Error Handler ---
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a message to the user."""
    logger.error(f"Update {update} caused error {context.error}")
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                "An error occurred while processing your request. Please try again later or use the /start command."
            )
        except Exception as e:
            logger.error(f"Error sending error message to user: {e}")

# --- Async Functions for on_startup and on_shutdown ---
async def on_startup(application: Application):
    if WEBHOOK_URL:
        logger.info(f"Attempting to set webhook to: {WEBHOOK_URL}")
        try:
            # Set webhook with allowed_updates for efficiency
            await application.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=["message", "callback_query"])
            info = await application.bot.get_webhook_info()
            logger.info(f"Webhook set successfully. Current info: {info.to_dict()}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            # If webhook fails, you might want to switch to polling or raise an error
            # For deployment, it's critical the webhook sets correctly.
            pass
    logger.info("Bot started successfully (on_startup).")

async def on_shutdown(application: Application):
    if WEBHOOK_URL:
        logger.info("Attempting to delete webhook on shutdown.")
        try:
            await application.bot.delete_webhook()
            logger.info("Webhook deleted successfully.")
        except Exception as e:
            logger.error(f"Failed to delete webhook: {e}")
    logger.info("Bot shutting down (on_shutdown).")


# --- Main Function ---
def main() -> None:
    """Start the bot."""
    if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Missing environment variables. Please set TELEGRAM_BOT_TOKEN, SUPABASE_URL, and SUPABASE_KEY.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Register handlers
    # This handler logs ALL incoming updates and should be one of the first to run
    application.add_handler(MessageHandler(filters.ALL, log_all_updates), group=-1)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_menu_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    # Register the error handler
    application.add_error_handler(error_handler)

    # Start the bot
    if RENDER_EXTERNAL_HOSTNAME:
        logger.info(f"Configuring bot for webhook mode. Render Host: {RENDER_EXTERNAL_HOSTNAME}, Port: {PORT}")
        logger.info(f"Listening on 0.0.0.0:{PORT} with URL path: {WEBHOOK_PATH}")
        logger.info(f"Telegram Webhook URL: {WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=WEBHOOK_URL,
            on_startup=on_startup,
            on_shutdown=on_shutdown
        )
    else:
        logger.warning("RENDER_EXTERNAL_HOSTNAME not set. Falling back to polling mode. This is not recommended for Render deployment.")
        # If running locally without webhook, you might want to use polling:
        # application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()