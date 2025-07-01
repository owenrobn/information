import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
from supabase import create_client, Client
import ccxt
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
import io
import asyncio
from datetime import datetime, timedelta

# --- Configure logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Load environment variables ---
load_dotenv()

# --- Debugging .env file and token ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

logger.debug(f"TELEGRAM_BOT_TOKEN (raw from os.getenv): '{TELEGRAM_BOT_TOKEN}'")
logger.debug(f"Is TELEGRAM_BOT_TOKEN None? {TELEGRAM_BOT_TOKEN is None}")
if TELEGRAM_BOT_TOKEN:
    logger.debug(f"TELEGRAM_BOT_TOKEN length: {len(TELEGRAM_BOT_TOKEN)}")
    logger.debug(f"First 5 chars of token: {TELEGRAM_BOT_TOKEN[:5]}...")
    logger.debug(f"Token starts with space? {TELEGRAM_BOT_TOKEN.startswith(' ')}")
    logger.debug(f"Token ends with space? {TELEGRAM_BOT_TOKEN.endswith(' ')}")
    logger.debug(f"Token matches Telegram format (N:XXXX)? {':' in TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN.split(':')) == 2}")
else:
    logger.error("TELEGRAM_BOT_TOKEN is not set!")

logger.debug(f"Current working directory: {os.getcwd()}")
logger.debug(f".env file exists in CWD: {os.path.exists('.env')}")

# --- Initialize Supabase client ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Conversation States ---
AWAITING_TRADE_INPUT = 'awaiting_trade_input'
AWAITING_CHART_INPUT = 'awaiting_chart_input'
GET_API_KEY = 'get_api_key'
GET_API_SECRET = 'get_api_secret'


# --- Helper Functions ---
async def get_or_create_user(telegram_user_id: int):
    """Fetches user from DB or creates a new one if not found."""
    response = await supabase.from_('users').select('*').eq('telegram_user_id', telegram_user_id).execute()
    user_data = response.data

    if not user_data:
        # Create new user
        new_user_data = {
            'telegram_user_id': telegram_user_id,
            'is_demo_mode': True,
            'demo_balance_usd': 10000.00
        }
        insert_response = await supabase.from_('users').insert(new_user_data).execute()
        if insert_response.data:
            return insert_response.data[0]
        else:
            logger.error(f"Failed to create new user: {insert_response.get('error')}")
            return None
    return user_data[0]

async def update_user_demo_balance(user_id: int, new_balance: float):
    """Updates the demo balance for a user."""
    response = await supabase.from_('users').update({'demo_balance_usd': new_balance}).eq('id', user_id).execute()
    return response.data

# --- Bot Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message and main menu."""
    user_tg_id = update.effective_user.id
    user_db_data = await get_or_create_user(user_tg_id)

    if not user_db_data:
        await update.message.reply_text("Oops! Something went wrong while setting up your account. Please try again.")
        return

    # Ensure to clear any previous conversation state when starting fresh
    context.user_data.clear() # Clear all user_data to reset state

    keyboard = [
        [InlineKeyboardButton("Trade", callback_data="menu_trade")],
        [InlineKeyboardButton("View Portfolio", callback_data="menu_portfolio")],
        [InlineKeyboardButton("Get Chart", callback_data="menu_chart")],
        [InlineKeyboardButton("Toggle Demo Mode", callback_data="menu_toggle_demo")],
        [InlineKeyboardButton("🔑 Manage API Keys", callback_data="menu_manage_api_keys")],
        [InlineKeyboardButton("Help", callback_data="menu_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    mode = "Demo" if user_db_data['is_demo_mode'] else "Live"
    balance = user_db_data['demo_balance_usd'] if user_db_data['is_demo_mode'] else "Connect exchange to see live balance"

    await update.message.reply_html(
        f"👋 Hi {update.effective_user.mention_html()}! Welcome to your Trading Bot.\n\n"
        f"Current Mode: <b>{mode}</b>\n"
        f"Demo Balance: <b>${balance:,.2f}</b>\n\n"
        "What would you like to do?",
        reply_markup=reply_markup
    )

async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callback queries from the main menu and platform choices."""
    query = update.callback_query
    await query.answer() # Acknowledge the button press

    user_tg_id = query.from_user.id
    user_db_data = await get_or_create_user(user_tg_id)

    if not user_db_data:
        await query.edit_message_text("Oops! Could not retrieve your account data.")
        return

    # Clear previous state as we're navigating through menus
    context.user_data['state'] = None
    context.user_data.pop('selected_exchange', None) # Clear selected exchange if exists

    if query.data == "menu_trade":
        await query.edit_message_text("Which platform would you like to trade on?",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("Bybit", callback_data="trade_bybit")],
                                          [InlineKeyboardButton("MEXC (Coming Soon)", callback_data="coming_soon")],
                                          [InlineKeyboardButton("Bitget (Coming Soon)", callback_data="coming_soon")],
                                          [InlineKeyboardButton("Gate.io (Coming Soon)", callback_data="coming_soon")],
                                          [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                                      ]))
    elif query.data == "trade_bybit":
        context.user_data['selected_exchange'] = 'bybit'
        if user_db_data['is_demo_mode']:
            await query.edit_message_text(
                "You are in **Demo Mode** for Bybit.\n"
                "Please enter the trading pair (e.g., `BTC/USDT`) to place a **Market Buy** order. "
                "You can also specify quantity (e.g., `BTC/USDT 0.001`).\n\n"
                "Example: `BTC/USDT 0.001` or `ETH/USDT` (for default quantity)",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                ])
            )
            context.user_data['state'] = AWAITING_TRADE_INPUT
        else:
            await query.edit_message_text(
                "You are in **Live Mode** for Bybit. "
                "**Warning: Live trading is not fully implemented in Phase 1.**\n"
                "Please connect your Bybit API keys in settings (coming soon) to proceed.\n"
                "For now, only demo trading is functional.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                ])
            )
            context.user_data['state'] = None

    elif query.data == "coming_soon":
        await query.edit_message_text("This feature is coming soon! Please try Bybit demo for now.",
                                      reply_markup=InlineKeyboardMarkup([
                                          [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                                      ]))
    elif query.data == "menu_portfolio":
        mode = "Demo" if user_db_data['is_demo_mode'] else "Live"
        balance = user_db_data['demo_balance_usd'] if user_db_data['is_demo_mode'] else "Connect exchange to see live balance"

        demo_trades_response = await supabase.from_('demo_trades').select('*').eq('user_id', user_db_data['id']).order('timestamp', desc=True).limit(5).execute()
        demo_trades = demo_trades_response.data

        trades_summary = ""
        if demo_trades:
            trades_summary = "\n**Recent Demo Trades:**\n"
            for trade in demo_trades:
                trades_summary += (
                    f"- {trade['pair']} ({trade['type'].upper()}): "
                    f"@{trade['entry_price']:.4f} Qty:{trade['quantity']:.4f} "
                    f"[{trade['status']}]\n"
                )
        else:
            trades_summary = "\nNo recent demo trades yet."

        await query.edit_message_text(
            f"💰 Your Portfolio Summary:\n\n"
            f"Current Mode: **{mode}**\n"
            f"Demo Balance: **${balance:,.2f}**\n"
            f"{trades_summary}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
    elif query.data == "menu_toggle_demo":
        new_demo_mode = not user_db_data['is_demo_mode']
        response = await supabase.from_('users').update({'is_demo_mode': new_demo_mode}).eq('telegram_user_id', user_tg_id).execute()
        if response.data:
            user_db_data = response.data[0]
            mode_status = "enabled" if new_demo_mode else "disabled"
            balance_info = f"Demo Balance: **${user_db_data['demo_balance_usd']:,.2f}**" if new_demo_mode else "Connect exchange to see live balance"
            await query.edit_message_text(
                f"**Demo Mode is now {mode_status}!**\n"
                f"{balance_info}\n\n"
                "What would you like to do next?",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Trade", callback_data="menu_trade")],
                    [InlineKeyboardButton("View Portfolio", callback_data="menu_portfolio")],
                    [InlineKeyboardButton("Get Chart", callback_data="menu_chart")],
                    [InlineKeyboardButton("Toggle Demo Mode", callback_data="menu_toggle_demo")],
                    [InlineKeyboardButton("🔑 Manage API Keys", callback_data="menu_manage_api_keys")],
                    [InlineKeyboardButton("Help", callback_data="menu_help")]
                ])
            )
        else:
            await query.edit_message_text("Failed to toggle demo mode. Please try again.")

    elif query.data == "menu_chart":
        await query.edit_message_text(
            "Please enter the trading pair and timeframe for the chart (e.g., `BTC/USDT 1h` or `ETH/USDT 4h`).\n"
            "Supported timeframes: `1m, 5m, 15m, 30m, 1h, 4h, 1d`.\n\n"
            "Example: `BTC/USDT 1h`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
        context.user_data['state'] = AWAITING_CHART_INPUT

    elif query.data == "menu_manage_api_keys":
        await query.edit_message_text(
            "Please select which API keys you'd like to manage:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Bybit Testnet API Keys", callback_data="manage_bybit_testnet_api")],
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
    elif query.data == "manage_bybit_testnet_api":
        user_db_data = await get_or_create_user(user_tg_id)
        text_message = "Alright, let's set up your Bybit Testnet API keys.\n\n" \
                       "Please send me your **Bybit Testnet API Key**.\n\n" \
                       "You can get this from your Bybit Testnet account settings (API Management section)."
        
        current_key = user_db_data.get('bybit_testnet_api_key')
        if current_key:
            text_message += "\n\n**Current API Key detected. Entering a new one will overwrite it.**"
            
        await query.edit_message_text(
            text_message,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_api_input_conv")]
            ])
        )
        context.user_data['state'] = GET_API_KEY
        return GET_API_KEY

    elif query.data == "menu_help":
        await query.edit_message_text(
            "This bot helps you with crypto trading.\n\n"
            "Available commands:\n"
            "/start - Show main menu\n"
            "/trade - Initiate a trade (demo or live)\n"
            "/portfolio - View your balance and open positions\n"
            "/chart - Get a price chart for a pair\n"
            "/demo - Toggle demo trading mode\n\n"
            "More features coming soon!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
    elif query.data == "back_to_main_menu":
        await start(update, context)

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles text input based on the current user state."""
    user_state = context.user_data.get('state')

    if user_state == AWAITING_TRADE_INPUT:
        await process_trade_input(update, context)
    elif user_state == AWAITING_CHART_INPUT:
        await process_chart_input(update, context)
    elif user_state == GET_API_KEY:
        await receive_api_key(update, context)
    elif user_state == GET_API_SECRET:
        await receive_api_secret(update, context)
    else:
        await update.message.reply_text("I'm not sure what to do with that. Please use the menu buttons or /start.")

async def process_trade_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes the trade input from the user."""
    user_tg_id = update.effective_user.id
    user_db_data = await get_or_create_user(user_tg_id)
    if not user_db_data:
        await update.message.reply_text("Could not retrieve your account data for trading.")
        context.user_data['state'] = None
        return

    is_demo_mode = user_db_data['is_demo_mode']
    selected_exchange = context.user_data.get('selected_exchange')

    if not selected_exchange:
        await update.message.reply_text("Please select an exchange from the menu first.")
        context.user_data['state'] = None
        return

    text_input = update.message.text.strip().upper()
    parts = text_input.split()

    if len(parts) == 1:
        pair = parts[0]
        quantity = None
    elif len(parts) == 2:
        pair = parts[0]
        try:
            quantity = float(parts[1])
            if quantity <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Invalid quantity. Please enter a positive number (e.g., `BTC/USDT 0.001`).")
            return
    else:
        await update.message.reply_text("Invalid trade format. Please use `PAIR/QUOTE QUANTITY` (e.g., `BTC/USDT 0.001`) or just `PAIR/QUOTE` (e.g., `BTC/USDT`).")
        return

    if '/' not in pair or len(pair.split('/')) != 2:
        await update.message.reply_text("Invalid trading pair format. Please use `BASE/QUOTE` (e.g., `BTC/USDT`).")
        return

    try:
        exchange_class = getattr(ccxt, selected_exchange)
        exchange = exchange_class({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        
        await exchange.load_markets()
        if pair not in exchange.markets:
            await update.message.reply_text(f"Trading pair {pair} not found on {selected_exchange}. Please check the symbol.")
            return

        market = exchange.market(pair)
        base = market['base']
        quote = market['quote']

        ticker = await exchange.fetch_ticker(pair)
        current_price = ticker['last']

        if quantity is None:
            default_quote_amount = 50.00
            quantity = default_quote_amount / current_price
            await update.message.reply_text(f"No quantity specified. Defaulting to ${default_quote_amount:.2f} worth of {base} (approx. {quantity:.4f} {base}).")

        trade_cost = quantity * current_price

        if is_demo_mode:
            current_balance = user_db_data['demo_balance_usd']
            if current_balance < trade_cost:
                await update.message.reply_text(
                    f"Insufficient demo balance! You need ${trade_cost:,.2f} but only have ${current_balance:,.2f}."
                )
                context.user_data['state'] = None
                return

            new_balance = current_balance - trade_cost
            update_response = await update_user_demo_balance(user_db_data['id'], new_balance)

            if update_response:
                await supabase.from_('demo_trades').insert({
                    'user_id': user_db_data['id'],
                    'pair': pair,
                    'type': 'buy',
                    'quantity': quantity,
                    'entry_price': current_price,
                    'cost_usd': trade_cost,
                    'status': 'filled'
                }).execute()

                await update.message.reply_text(
                    f"✅ Demo Market BUY order placed for {quantity:.4f} {base} @ {current_price:,.4f} {quote} on {selected_exchange}.\n"
                    f"Cost: ${trade_cost:,.2f}\n"
                    f"Remaining Demo Balance: ${new_balance:,.2f}\n\n"
                    "What would you like to do next?",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                    ])
                )
            else:
                await update.message.reply_text("Failed to process demo trade. Please try again.")

        else:
            await update.message.reply_text(
                "You are in **Live Mode**. Live trading is not yet fully implemented for real exchanges.\n"
                "Please connect your Bybit API keys to use testnet trading or toggle to Demo Mode for simulated trades.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                ])
            )
        context.user_data['state'] = None
    except ccxt.ExchangeError as e:
        logger.error(f"CCXT Exchange Error: {e}")
        await update.message.reply_text(f"Exchange error: {e}. Please check the pair or try again later.")
        context.user_data['state'] = None
    except Exception as e:
        logger.error(f"Error processing trade: {e}")
        await update.message.reply_text(f"An unexpected error occurred: {e}. Please try again.")
        context.user_data['state'] = None

async def process_chart_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes the chart input from the user."""
    text_input = update.message.text.strip().upper()
    parts = text_input.split()

    if len(parts) != 2:
        await update.message.reply_text("Invalid chart format. Please use `PAIR/QUOTE TIMEFRAME` (e.g., `BTC/USDT 1h`).")
        return

    pair = parts[0]
    timeframe = parts[1].lower()

    supported_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
    if timeframe not in supported_timeframes:
        await update.message.reply_text(f"Unsupported timeframe: `{timeframe}`. Please use one of: {', '.join(supported_timeframes)}.")
        return

    if '/' not in pair or len(pair.split('/')) != 2:
        await update.message.reply_text("Invalid trading pair format. Please use `BASE/QUOTE` (e.g., `BTC/USDT`).")
        return

    try:
        exchange = ccxt.bybit({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        
        await update.message.reply_text(f"Fetching {pair} {timeframe} chart, please wait...")

        ohlcv = await exchange.fetch_ohlcv(pair, timeframe)

        if not ohlcv:
            await update.message.reply_text(f"Could not fetch OHLCV data for {pair} {timeframe}. It might be an invalid pair or timeframe for the exchange.")
            context.user_data['state'] = None
            return

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        fig, axlist = mpf.plot(df, type='candle', style='yahoo', title=f"{pair} {timeframe} Chart",
                               volume=True, mav=(20,50),
                               figscale=1.5,
                               returnfig=True)

        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        buf.seek(0)

        await update.message.reply_photo(
            photo=buf,
            caption=f"Here is the {pair} {timeframe} chart.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
        plt.close(fig)
        buf.close()

        context.user_data['state'] = None

    except ccxt.ExchangeError as e:
        logger.error(f"CCXT Exchange Error: {e}")
        await update.message.reply_text(f"Exchange error: {e}. Please check the pair or try again later.")
        context.user_data['state'] = None
    except Exception as e:
        logger.error(f"Error generating chart: {e}")
        await update.message.reply_text(f"An unexpected error occurred: {e}. Please try again.")
        context.user_data['state'] = None

# --- API Key Conversation Handlers ---
async def receive_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the API Key and asks for the Secret."""
    user_api_key = update.message.text.strip()
    context.user_data['temp_api_key'] = user_api_key

    await update.message.reply_text(
        "Now, please send me your **Bybit Testnet API Secret**.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_api_input_conv")]
        ])
    )
    context.user_data['state'] = GET_API_SECRET
    return GET_API_SECRET

async def receive_api_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the API Secret, saves both to Supabase, and ends the conversation."""
    user_api_secret = update.message.text.strip()
    user_api_key = context.user_data.pop('temp_api_key', None)

    if not user_api_key:
        await update.message.reply_text(
            "It looks like the API Key was not properly saved. Please start over.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )
        context.user_data.clear()
        return ConversationHandler.END

    user_tg_id = update.effective_user.id
    user_db_data = await get_or_create_user(user_tg_id)

    if not user_db_data:
        await update.message.reply_text("Could not retrieve your account data to save API keys.")
        context.user_data.clear()
        return ConversationHandler.END

    try:
        response = await supabase.from_('users').update({
            'bybit_testnet_api_key': user_api_key,
            'bybit_testnet_api_secret': user_api_secret
        }).eq('telegram_user_id', user_tg_id).execute()

        if response.data:
            await update.message.reply_text(
                "✅ Your Bybit Testnet API keys have been saved successfully!\n"
                "You can now use Bybit Testnet for demo trading.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                ])
            )
        else:
            await update.message.reply_text(
                "Failed to save API keys. Please try again or contact support if the issue persists.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
                ])
            )
    except Exception as e:
        logger.error(f"Error saving API keys to Supabase: {e}")
        await update.message.reply_text(
            f"An unexpected error occurred while saving keys: {e}. Please try again.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
            ])
        )

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_api_input_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the API key input conversation."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "API key setup cancelled. Returning to main menu.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu")]
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END

# --- Main function to run the bot ---
def main() -> None:
    """Starts the bot."""
    if not TELEGRAM_BOT_TOKEN or not SUPABASE_URL or not SUPABASE_KEY:
        logger.critical("Missing one or more environment variables. Please check your .env file.")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # --- NEW: Webhook configuration for Render ---
    # Render provides the PORT environment variable for Web Services
    port = int(os.environ.get("PORT", 8000)) # Default to 8000 if not set locally
    
    # Render provides the RENDER_EXTERNAL_HOSTNAME for Web Services
    # This is the public URL of your deployed service
    render_external_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

    if render_external_hostname:
        # A secret path for Telegram to send updates to
        WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}" # Using token for unique, hard-to-guess path
        WEBHOOK_URL = f"https://{render_external_hostname}{WEBHOOK_PATH}"
        
        logger.info(f"Configuring bot for webhook mode.")
        logger.info(f"Listening on 0.0.0.0:{port} with URL path: {WEBHOOK_PATH}")
        logger.info(f"Telegram Webhook URL: {WEBHOOK_URL}")

        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=WEBHOOK_PATH,
            webhook_url=WEBHOOK_URL
        )
    else:
        # Fallback to polling for local development if RENDER_EXTERNAL_HOSTNAME is not set
        logger.info("RENDER_EXTERNAL_HOSTNAME not found. Running bot in polling mode for local development.")
        application.run_polling() # This will block until stopped

    logger.info("Application started")

    # --- Command Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", handle_menu_callback))

    # --- Conversation Handler for API Key Input ---
    api_key_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_menu_callback, pattern='^manage_bybit_testnet_api$')
        ],
        states={
            GET_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key)],
            GET_API_SECRET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_secret)],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_api_input_conv, pattern='^cancel_api_input_conv$'),
            CommandHandler("cancel", cancel_api_input_conv)
        ],
        allow_reentry=True
    )
    application.add_handler(api_key_conv_handler)

    # --- Callback Query Handler (for all other inline keyboard buttons) ---
    application.add_handler(CallbackQueryHandler(handle_menu_callback))

    # --- Message Handler (for text input) ---
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))


if __name__ == '__main__':
    main()