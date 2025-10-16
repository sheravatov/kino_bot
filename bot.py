import os
import logging
from datetime import datetime, timedelta
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import sqlite3
from contextlib import contextmanager

# .env fayldan o'qish (local uchun)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ===== KONFIGURATSIYA =====
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://localhost:5000")
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

# Token tekshirish
if not TOKEN:
    raise ValueError("BOT_TOKEN o'rnatilmagan! .env faylda yoki environment variable sifatida o'rnating.")

# ===== LOGGING =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== DATABASE =====
DB_NAME = "kinobot.db"

@contextmanager
def get_db():
    """Ma'lumotlar bazasi bilan ishlash uchun kontekst manager"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Ma'lumotlar bazasini yaratish"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Foydalanuvchilar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_active DATE
            )
        """)
        
        # Kinolar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kino (
                id INTEGER PRIMARY KEY,
                file_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT
            )
        """)
        
        # Xabarlar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Adminlar jadvali
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        logger.info("Ma'lumotlar bazasi muvaffaqiyatli yaratildi")

def update_user(user_id: int, username: str, first_name: str):
    """Foydalanuvchini bazaga qo'shish yoki yangilash"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_active)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, first_name, datetime.now().date()))
        conn.commit()

def save_message(user_id: int, text: str):
    """Xabarni bazaga saqlash"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO messages (user_id, text)
            VALUES (?, ?)
        """, (user_id, text))
        conn.commit()

def get_admin_ids():
    """Barcha adminlar ro'yxatini olish"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT admin_id FROM admins")
        db_admins = [row[0] for row in cursor.fetchall()]
    
    # Env dan va bazadan adminlarni birlashtirish
    all_admins = list(set(ADMIN_IDS + db_admins))
    return all_admins if all_admins else ADMIN_IDS

def is_admin(user_id: int) -> bool:
    """Foydalanuvchi admin ekanligini tekshirish"""
    return user_id in get_admin_ids()

# ===== CONVERSATION STATES =====
WAITING_FOR_NUMBER, WAITING_FOR_TITLE, WAITING_FOR_DESCRIPTION = range(3)

# ===== HANDLERS =====

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyrug'ini qayta ishlash"""
    user = update.effective_user
    update_user(user.id, user.username, user.first_name)
    
    welcome_text = f"👋 Salom, {user.first_name}!\n\n"
    
    if is_admin(user.id):
        welcome_text += "🎬 Siz adminsiz. Quyidagi imkoniyatlar mavjud:\n\n"
        welcome_text += "📹 Video yuklash: Video yuboring\n"
        welcome_text += "📊 Statistika: /stats\n"
        welcome_text += "👥 Admin qo'shish: /addadmin [ID]\n"
        welcome_text += "🗑 Admin o'chirish: /removeadmin [ID]\n"
        welcome_text += "📋 Adminlar ro'yxati: /admins\n"
        welcome_text += "💬 Javob berish: reply [ID] [xabar]\n\n"
    
    welcome_text += "🎥 Kino ko'rish uchun raqamini yuboring.\n"
    welcome_text += "✉️ Savollaringiz bo'lsa, xabar yozing!"
    
    await update.message.reply_text(welcome_text)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Statistikani ko'rsatish (faqat adminlar uchun)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Bu buyruq faqat adminlar uchun.")
        return
    
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Umumiy foydalanuvchilar
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Bugun faol foydalanuvchilar
        today = datetime.now().date()
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_active = ?", (today,))
        today_active = cursor.fetchone()[0]
        
        # Oy davomida faol foydalanuvchilar
        month_ago = datetime.now().date() - timedelta(days=30)
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (month_ago,))
        month_active = cursor.fetchone()[0]
        
        # Kinolar soni
        cursor.execute("SELECT COUNT(*) FROM kino")
        total_kino = cursor.fetchone()[0]
        
        # Bugun yuborilgan xabarlar
        cursor.execute("""
            SELECT COUNT(*) FROM messages 
            WHERE DATE(timestamp) = ?
        """, (today,))
        today_messages = cursor.fetchone()[0]
    
    stats_text = f"""📊 <b>Statistika</b>

👥 Umumiy foydalanuvchilar: {total_users}
✅ Bugun faol: {today_active}
📅 Oy davomida faol: {month_active}
🎬 Bazadagi kinolar: {total_kino}
💬 Bugun yuborilgan xabarlar: {today_messages}"""
    
    await update.message.reply_text(stats_text, parse_mode="HTML")

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin qo'shish"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Bu buyruq faqat adminlar uchun.")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Noto'g'ri format. Ishlatish: /addadmin [ID]")
        return
    
    new_admin_id = int(context.args[0])
    
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO admins (admin_id, added_by)
                VALUES (?, ?)
            """, (new_admin_id, update.effective_user.id))
            conn.commit()
            await update.message.reply_text(f"✅ Admin qo'shildi: {new_admin_id}")
        except sqlite3.IntegrityError:
            await update.message.reply_text("⚠️ Bu foydalanuvchi allaqachon admin.")

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin o'chirish"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Bu buyruq faqat adminlar uchun.")
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❌ Noto'g'ri format. Ishlatish: /removeadmin [ID]")
        return
    
    admin_id = int(context.args[0])
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE admin_id = ?", (admin_id,))
        conn.commit()
        
        if cursor.rowcount > 0:
            await update.message.reply_text(f"✅ Admin o'chirildi: {admin_id}")
        else:
            await update.message.reply_text("⚠️ Bu foydalanuvchi admin emas.")

async def list_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminlar ro'yxatini ko'rsatish"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Bu buyruq faqat adminlar uchun.")
        return
    
    admins = get_admin_ids()
    
    if not admins:
        await update.message.reply_text("📋 Adminlar ro'yxati bo'sh.")
        return
    
    admin_text = "👥 <b>Adminlar ro'yxati:</b>\n\n"
    for admin_id in admins:
        admin_text += f"🔹 ID: <code>{admin_id}</code>\n"
    
    await update.message.reply_text(admin_text, parse_mode="HTML")

async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin video yuklash jarayonini boshlash"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Siz video yuklay olmaysiz.")
        return ConversationHandler.END
    
    video = update.message.video
    context.user_data["file_id"] = video.file_id
    
    await update.message.reply_text("🎬 Kino raqamini kiriting (masalan: 1):")
    return WAITING_FOR_NUMBER

async def get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kino raqamini qabul qilish"""
    text = update.message.text.strip()
    
    if not text.isdigit():
        await update.message.reply_text("❌ Iltimos, faqat raqam kiriting:")
        return WAITING_FOR_NUMBER
    
    context.user_data["kino_id"] = int(text)
    await update.message.reply_text("📝 Kino nomini kiriting:")
    return WAITING_FOR_TITLE

async def get_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kino nomini qabul qilish"""
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text("📄 Kino tavsifini kiriting:")
    return WAITING_FOR_DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kino tavsifini qabul qilish va bazaga saqlash"""
    description = update.message.text.strip()
    
    kino_id = context.user_data["kino_id"]
    file_id = context.user_data["file_id"]
    title = context.user_data["title"]
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO kino (id, file_id, title, description)
            VALUES (?, ?, ?, ?)
        """, (kino_id, file_id, title, description))
        conn.commit()
    
    await update.message.reply_text(f"✅ Kino #{kino_id} muvaffaqiyatli saqlandi!")
    
    # User data tozalash
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Jarayonni bekor qilish"""
    context.user_data.clear()
    await update.message.reply_text("❌ Jarayon bekor qilindi.")
    return ConversationHandler.END

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oddiy xabarlarni qayta ishlash"""
    user = update.effective_user
    text = update.message.text.strip()
    
    update_user(user.id, user.username, user.first_name)
    
    # Admin javob berish funktsiyasi
    if is_admin(user.id) and text.startswith("reply "):
        parts = text.split(None, 2)
        if len(parts) >= 3 and parts[1].isdigit():
            target_user_id = int(parts[1])
            reply_text = parts[2]
            
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"💬 <b>Admin javob berdi:</b>\n\n{reply_text}",
                    parse_mode="HTML"
                )
                await update.message.reply_text(f"✅ Javob yuborildi: {target_user_id}")
            except Exception as e:
                await update.message.reply_text(f"❌ Xato: {e}")
        else:
            await update.message.reply_text("❌ Noto'g'ri format. Ishlatish: reply [ID] [xabar]")
        return
    
    # Kino raqamini tekshirish
    if text.isdigit():
        kino_id = int(text)
        
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT file_id, title, description FROM kino WHERE id = ?", (kino_id,))
            result = cursor.fetchone()
        
        if result:
            file_id, title, description = result
            caption = f"🎬 <b>{title}</b>\n\n{description}"
            
            await update.message.reply_video(
                video=file_id,
                caption=caption,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(f"❌ {kino_id}-raqamli kino topilmadi.")
        return
    
    # Foydalanuvchi xabarini adminga yuborish
    save_message(user.id, text)
    
    message_to_admins = f"""✉️ <b>Yangi xabar</b>

👤 Ism: {user.first_name}
🆔 ID: <code>{user.id}</code>
🧷 Username: @{user.username if user.username else 'mavjud emas'}
💬 Xabar: {text}"""
    
    for admin_id in get_admin_ids():
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message_to_admins,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Adminga xabar yuborishda xato {admin_id}: {e}")
    
    await update.message.reply_text("📨 Xabaringiz adminga yuborildi!")

# ===== FLASK APPLICATION =====
app = Flask(__name__)

@app.route("/")
def index():
    return "Kinobot ishlayapti! ✅"

@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    """Telegram webhook qabul qilish"""
    json_data = request.get_json()
    update = Update.de_json(json_data, application.bot)
    await application.process_update(update)
    return "OK"

# ===== BOT APPLICATION =====
application = Application.builder().token(TOKEN).build()

# Conversation handler - video yuklash
conv_handler = ConversationHandler(
    entry_points=[MessageHandler(filters.VIDEO, video_handler)],
    states={
        WAITING_FOR_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_number)],
        WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
        WAITING_FOR_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# Handlers
application.add_handler(CommandHandler("start", start_command))
application.add_handler(CommandHandler("stats", stats_command))
application.add_handler(CommandHandler("addadmin", add_admin_command))
application.add_handler(CommandHandler("removeadmin", remove_admin_command))
application.add_handler(CommandHandler("admins", list_admins_command))
application.add_handler(conv_handler)
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

# ===== MAIN =====
if __name__ == "__main__":
    # Ma'lumotlar bazasini yaratish
    init_db()
    
    # Webhook o'rnatish
    import asyncio
    
    async def setup_webhook():
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
        logger.info(f"Webhook o'rnatildi: {WEBHOOK_URL}/{TOKEN}")
    
    asyncio.run(setup_webhook())
    
    # Flask serverni ishga tushirish
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)