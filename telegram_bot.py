# telegram_bot.py

import os
import sys
import asyncio
import logging
import traceback
import aiohttp
import time
import pymysql
import sqlite3
from datetime import datetime, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
from binance.client import Client as BinanceClient
from pycoingecko import CoinGeckoAPI

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Constants === #
ADMIN_ID = 6685099030
  # Replace with your Telegram user ID
BOT_TOKEN = os.getenv("7631419865:AAFSJK9A7FNbQL5BRwujVm89C_RVg0wTYI4")

# === Database Connection === #
def connect_mysql():
    try:
        conn = pymysql.connect(
            host="localhost",
            user="root",
            password="Chidera12345.",
            database="tradingbot",
            autocommit=True
        )
        return conn
    except Exception as e:
        logger.error(f"MySQL connection error: {e}")
        with open("db_errors.log", "a") as f:
            f.write(f"{datetime.now()} - {e}\n")
        return None

        import pymysql

def ensure_database_exists():
    connection = pymysql.connect(host='localhost', user='root', password='Chidera12345')
    with connection.cursor() as cursor:
        cursor.execute("CREATE DATABASE IF NOT EXISTS tradingbot")
    connection.close()

ensure_database_exists()



def init_sqlite_fallback():
    conn = sqlite3.connect("fallback_bot.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_watchlist (user_id INTEGER, symbol TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_alerts (user_id INTEGER, alert_type TEXT)''')
    conn.commit()
    return conn

db_conn = connect_mysql() or init_sqlite_fallback()

# === Signal Dispatcher + Watchlist === #
async def check_new_listings():
    try:
        cg = CoinGeckoAPI()
        coins = cg.get_coins_list()
        new_listings = [coin for coin in coins if datetime.strptime(coin['id'], '%Y-%m-%d') > datetime.now() - timedelta(days=1)]
        for coin in new_listings:
            await broadcast_signal(f"🆕 New Coin Listing: {coin['name'].capitalize()} ({coin['symbol'].upper()})")
    except Exception as e:
        logger.error(f"New listing check failed: {e}")

async def detect_whale_activity():
    try:
        # Simulated whale activity (custom logic or whale API can be added)
        whales = ["BTC", "ETH"]  # example result
        for asset in whales:
            await broadcast_signal(f"🐋 Whale Alert: Massive volume spike in {asset}")
    except Exception as e:
        logger.error(f"Whale alert failed: {e}")

async def detect_pump_dump():
    try:
        cg = CoinGeckoAPI()
        market = cg.get_coins_markets(vs_currency='usd')
        for coin in market:
            if coin['price_change_percentage_1h_in_currency'] and abs(coin['price_change_percentage_1h_in_currency']) > 5:
                move = "📈 Pump" if coin['price_change_percentage_1h_in_currency'] > 0 else "📉 Dump"
                await broadcast_signal(f"{move} detected in {coin['symbol'].upper()} ({coin['price_change_percentage_1h_in_currency']:.2f}%)")
    except Exception as e:
        logger.error(f"Pump/dump detection failed: {e}")

async def broadcast_signal(message):
    if not db_conn:
        return
    try:
        cursor = db_conn.cursor()
        cursor.execute("SELECT DISTINCT user_id FROM user_alerts")
        users = cursor.fetchall()
        for user in users:
            try:
                await app.bot.send_message(chat_id=user[0], text=message)
            except Exception as err:
                logger.error(f"Message send error: {err}")
    except Exception as e:
        logger.error(f"Broadcast error: {e}")

async def signal_scheduler():
    while True:
        await check_new_listings()
        await detect_whale_activity()
        await detect_pump_dump()
        await asyncio.sleep(3600)  # every hour

# === User Watchlist Handlers === #
async def add_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args:
        symbol = context.args[0].upper()
        cursor = db_conn.cursor()
        cursor.execute("INSERT INTO user_watchlist (user_id, symbol) VALUES (%s, %s)", (user_id, symbol))
        await update.message.reply_text(f"✅ {symbol} added to your watchlist.")

async def subscribe_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.args:
        alert_type = context.args[0].upper()
        cursor = db_conn.cursor()
        cursor.execute("INSERT INTO user_alerts (user_id, alert_type) VALUES (%s, %s)", (user_id, alert_type))
        await update.message.reply_text(f"🔔 Subscribed to {alert_type} signals.")

# === Bot Handlers === #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to the Crypto Futures Bot! Use /addwatch BTC or /subscribe PUMP")

# === Main Async Application === #
async def main():
    global app
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addwatch", add_watchlist))
    app.add_handler(CommandHandler("subscribe", subscribe_signals))

    asyncio.create_task(signal_scheduler())

    logger.info("✅ Bot is running...")
    await app.run_polling()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "event loop is running" in str(e):
            loop = asyncio.get_event_loop()
            loop.create_task(main())
            loop.run_forever()
        else:
            logger.error(f"RuntimeError during bot execution: {e}")
            with open("runtime_errors.log", "a") as f:
                f.write(f"{datetime.now()} - {traceback.format_exc()}\n")
