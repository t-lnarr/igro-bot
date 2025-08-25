import os
import asyncio
import sqlite3
from datetime import datetime, timezone, date
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler,
    CallbackQueryHandler, filters
)

# === Ortam değişkenleri ===
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@igro_store_tm")
STORE_URL = os.getenv("STORE_URL", "https://igrostore.pythonanywhere.com")
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: List[int] = [int(x.strip()) for x in ADMIN_IDS_ENV.split(",") if x.strip().isdigit()]

DB_PATH = os.getenv("DB_PATH", "bot.db")
DATABASE_URL = os.getenv("DATABASE_URL")  # PostgreSQL için, örn: postgres://user:pass@host:5432/dbname

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable'ı eksik!")

# === Sabit klavye (her zaman görünen) ===
MAIN_KB = ReplyKeyboardMarkup(
    [[KeyboardButton("🛒 Store gir", web_app=WebAppInfo(url=STORE_URL)), KeyboardButton("📣 Kanala gir")]],
    resize_keyboard=True,
    is_persistent=True
)

# === DB yardımcıları ===
def db_connect():
    """Veritabanı bağlantısını kurar. PostgreSQL varsa onu kullanır."""
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def db_init():
    """Veritabanı tablolarını oluşturur."""
    conn = db_connect()
    cur = conn.cursor()
    if DATABASE_URL:
        # PostgreSQL
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_at TEXT,
            last_seen TEXT
        );
        """)
    else:
        # SQLite
        cur.execute("""
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
    conn.commit()
    conn.close()

def upsert_user(user):
    now = datetime.now(timezone.utc).isoformat()
    conn = db_connect()
    cur = conn.cursor()

    if DATABASE_URL:
        # PostgreSQL
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, last_name, joined_at, last_seen)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                last_name=EXCLUDED.last_name,
                last_seen=EXCLUDED.last_seen
        """, (
            user.id,
            user.username,
            user.first_name,
            user.last_name,
            now,
            now
        ))
    else:
        # SQLite
        cur.execute("""
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
    cur.close()
    conn.close()


def count_total_users() -> int:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    conn.close()
    return total

def count_active_today() -> int:
    today = date.today().isoformat()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM users WHERE substr(last_seen, 1, 10)=?" if not DATABASE_URL
        else "SELECT COUNT(*) FROM users WHERE left(last_seen, 10)=%s",
        (today,)
    )
    active = cur.fetchone()[0]
    conn.close()
    return active

def get_all_user_ids():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

# === Yetki kontrolü ===
def is_admin(user_id: int) -> bool:
    """Kullanıcının yönetici olup olmadığını kontrol eder."""
    return user_id in ADMIN_IDS

# === Komutlar ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upsert_user, user)

    text = (
        "🤖 IGRO Store Bot\n\n"
        "🛍️ Satlyk akkauntlary görmek üçin aşakdaky düwmeleri ulanyň.\n"
        "• 🛒 *Store gir*: Web Store açar\n"
        "• 📣 *Kanala gir*: Resmi kanala geçiş"
    )
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KB)

async def channel_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ReplyKeyboard'daki 'Kanala gir' düğmesine basılınca çalışır."""
    user = update.effective_user
    if user:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upsert_user, user)

    url_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📣 Kanala geç", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")]])
    await update.effective_message.reply_text("Resmi kanal :", reply_markup=url_btn)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upsert_user, user)

    txt = [
        "🆘 *Kömek*",
        "• /start – Menü knopgalar görkeziler",
        "• /stats – (admin) günlik & jemi ulanyjylar",
        "• /sendall <mesaj> – (admin) hemme ulanyjylara bildiriş",
        "• Kanala gir dügmesi bilen kanal linkini alarsyňyz"
    ]
    await update.effective_message.reply_text("\n".join(txt), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KB)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    loop = asyncio.get_running_loop()
    total = await loop.run_in_executor(None, count_total_users)
    active = await loop.run_in_executor(None, count_active_today)

    await update.effective_message.reply_text(f"📈 Statistikalar\nJemi ulanyjy: {total}\nBugün aktiw: {active}", reply_markup=MAIN_KB)

async def sendall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    message_text = " ".join(context.args) if context.args else None
    if not message_text:
        await update.effective_message.reply_text("⚠️ Ulanylyşy: /sendall <mesaj>")
        return

    loop = asyncio.get_running_loop()
    user_ids = await loop.run_in_executor(None, get_all_user_ids)
    if not user_ids:
        await update.effective_message.reply_text("⚠️ Ulanyjy ýok.")
        return

    ok = 0
    fail = 0
    preview_msg = await update.effective_message.reply_text(
        f"📣 Ugradylýar…\nHedef: {len(user_ids)} kullanıcı"
    )

    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    await preview_msg.edit_text(f"✅ Ugradyldy: {ok}\n❌ Ýalňyş: {fail}\n🎯 Jemi: {len(user_ids)}")

async def echo_touch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, upsert_user, user)

# === Uygulama ===
def main():
    db_init()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("sendall", sendall_cmd))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("Kanala gir|📣 Kanala gir"), channel_entry))
    app.add_handler(MessageHandler(filters.ALL, echo_touch))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
