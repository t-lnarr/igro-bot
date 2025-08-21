import os
import asyncio
import sqlite3
from datetime import datetime, timezone, date
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters
)

# === Ortam değişkenleri ===
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS_ENV = os.getenv("ADMIN_IDS", "")  # Virgülle ayrılmış: "123456,987654"
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
    conn.commit()
    conn.close()

def upsert_user(user):
    # UTC ISO time
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
        now,  # joined_at (ilk kezse kaydolur)
        now   # last_seen
    ))
    conn.commit()
    conn.close()

def count_total_users() -> int:
    conn = db_connect()
    cur = conn.execute("SELECT COUNT(*) FROM users;")
    total = cur.fetchone()[0]
    conn.close()
    return total

def count_active_today() -> int:
    # UTC gün başlangıcı
    today_utc = date.today()
    start_of_day = datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=timezone.utc).isoformat()
    conn = db_connect()
    cur = conn.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?;", (start_of_day,))
    active = cur.fetchone()[0]
    conn.close()
    return active

# === Yetki kontrolü ===
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# === Komutlar ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        # Kullanıcıyı DB'ye yaz
        await context.application.run_in_executor(None, upsert_user, user)

    keyboard = [
        [InlineKeyboardButton("🛒 Store Gir", web_app=WebAppInfo(url="https://igrostore.pythonanywhere.com"))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "IGRO Store’a hoş geldiň! 👋\n\n🛍️ Satılık hesaplara göz atmak için butona tıkla."
    await update.effective_message.reply_text(text, reply_markup=reply_markup)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await context.application.run_in_executor(None, upsert_user, user)

    txt = [
        "🆘 *Yardım*",
        "• /start – Store butonunu gönderir",
        "• /stats – (admin) günlük & toplam kullanıcı",
        "• /sendall <mesaj> – (admin) tüm kullanıcılara duyuru",
        "",
        "İpucu: ADMIN_IDS ortam değişkeni ile admin ID’lerini ayarlayın (örn: 123,456)."
    ]
    await update.effective_message.reply_text("\n".join(txt), parse_mode=ParseMode.MARKDOWN)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    total = await context.application.run_in_executor(None, count_total_users)
    active = await context.application.run_in_executor(None, count_active_today)

    txt = (
        "📊 *İstatistikler (UTC)*\n"
        f"• Bugün aktif: *{active}*\n"
        f"• Toplam kayıtlı: *{total}*"
    )
    await update.effective_message.reply_text(txt, parse_mode=ParseMode.MARKDOWN)

async def sendall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    # Mesaj metnini al
    if context.args:
        message_text = " ".join(context.args).strip()
    else:
        await update.effective_message.reply_text("Kullanım: /sendall <mesaj>")
        return

    # Kullanıcı listesini çek
    def get_all_user_ids():
        conn = db_connect()
        cur = conn.execute("SELECT user_id FROM users;")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]

    user_ids = await context.application.run_in_executor(None, get_all_user_ids)
    if not user_ids:
        await update.effective_message.reply_text("Kayıtlı kullanıcı yok.")
        return

    ok = 0
    fail = 0
    preview_msg = await update.effective_message.reply_text(
        f"📣 Gönderiliyor…\nHedef: {len(user_ids)} kullanıcı"
    )

    # Kullanıcıları sırayla bilgilendir (rate-limit'e dikkat)
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=message_text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # nazik hız

    await preview_msg.edit_text(f"✅ Gönderildi: {ok}\n❌ Hata: {fail}\n🎯 Toplam: {len(user_ids)}")

async def echo_touch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Her mesaj/komutta kullanıcıyı aktif kabul edip last_seen’i güncelleriz."""
    user = update.effective_user
    if user:
        await context.application.run_in_executor(None, upsert_user, user)

# === Uygulama ===
def main():
    db_init()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("sendall", sendall_cmd))

    # Kullanıcı aktifliğini daha iyi yakalamak için her mesajı dokundur
    app.add_handler(MessageHandler(filters.ALL, echo_touch))

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
