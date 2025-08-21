import os
import asyncio
import sqlite3
from datetime import datetime, timezone, date
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
)

# === Ortam değişkenleri ===
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@igro_store_tm")  # Çekiliş için kanal
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(x.strip()) for x in ADMIN_IDS_ENV.split(",") if x.strip().isdigit()]

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable'ı eksik!")

DB_PATH = os.getenv("DB_PATH", "bot.db")

# === DB yardımcıları ===
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def db_init():
    conn = db_connect()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined_at TEXT,
        last_seen TEXT
    );
    """)
    # çekilişe katılanlar için tablo
    conn.execute("""
    CREATE TABLE IF NOT EXISTS giveaway (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        username TEXT,
        joined_at TEXT
    );
    """)
    conn.commit()
    conn.close()

def upsert_user(user):
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    conn.execute("""
        INSERT INTO users (user_id, username, first_name, last_name, joined_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            last_seen=excluded.last_seen
    """, (
        user.id,
        user.username,
        user.first_name,
        user.last_name,
        now,
        now
    ))
    conn.commit()
    conn.close()

def count_total_users() -> int:
    conn = db_connect()
    cur = conn.execute("SELECT COUNT(*) FROM users;")
    total = cur.fetchone()[0]
    conn.close()
    return total

def add_to_giveaway(user):
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    conn.execute("""
        INSERT OR IGNORE INTO giveaway (user_id, username, joined_at)
        VALUES (?, ?, ?)
    """, (user.id, user.username, now))
    conn.commit()
    conn.close()

# === Yetki kontrolü ===
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# === Komutlar ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upsert_user, user)

    loop = asyncio.get_running_loop()
    total_users = await loop.run_in_executor(None, count_total_users)

    keyboard = [
        [
            InlineKeyboardButton("🛒 Store Gir", web_app=WebAppInfo(url="https://igrostore.pythonanywhere.com")),
            InlineKeyboardButton("🎁 Çekilişe Katıl", callback_data="join_giveaway")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"🤖 IGRO Store Bot\n📊 {total_users} users\n\n🛍️ Satlyk akkauntlary görmek üçin aşakdaky knopgalary ulanyň 👇"
    await update.effective_message.reply_text(text, reply_markup=reply_markup)


# === Callback işlemleri ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "join_giveaway":
        user = query.from_user
        try:
            member = await context.bot.get_chat_member(CHANNEL_USERNAME, user.id)
            if member.status in ("member", "administrator", "creator"):
                # kullanıcı kanalda
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, add_to_giveaway, user)
                await query.edit_message_text("🎉 Tebrikler! Çekilişe başarıyla katıldınız.")
            else:
                await query.edit_message_text(f"⚠️ Katılmak için önce kanala abone olmalısın: {CHANNEL_USERNAME}")
        except Exception:
            await query.edit_message_text(f"⚠️ Katılmak için önce kanala abone olmalısın: {CHANNEL_USERNAME}")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await context.application.run_in_executor(None, upsert_user, user)

    txt = [
        "🆘 *Yardım*",
        "• /start – Menü butonlarını gönderir",
        "• /stats – (admin) günlük & toplam kullanıcı",
        "• /sendall <mesaj> – (admin) tüm kullanıcılara duyuru",
    ]
    await update.effective_message.reply_text("\n".join(txt), parse_mode=ParseMode.MARKDOWN)


async def echo_touch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await context.application.run_in_executor(None, upsert_user, user)

# === Uygulama ===
def main():
    db_init()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL, echo_touch))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
