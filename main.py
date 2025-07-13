import os
import json
import re
import time
import asyncio
import aiohttp
import uuid
from collections import deque
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    CallbackQueryHandler, ContextTypes
)
import yt_dlp
from urllib.parse import quote

# ======= إعدادات =======
TOKEN = "7654416760:AAFEAJBDSSA27CNUDeJQ3EO7aMZM-4iXsA8"
VT_API_KEY = "06ae9a8042a744b19d373b364b19d373b364a951040564addb48dff7a2fc30f9b18a4b333b0"
ADMINS_IDS = {774954050}
SETTINGS_FILE = "settings.json"
USER_STATS_FILE = "user_stats.json"

chat_messages = {}
user_stats = {}
whispers_data = {}
waiting_for_whisper = {}

def load_settings():
    default_settings = {
        "welcome_text_bot": "أهلًا بك في بوت حماية المجموعات. أرسل /start",
        "welcome_text_group": "أهلًا بالمجموعة! اضغط ✅ لتفعيل الحماية.",
        "banned_words": [],
        "welcome_photo": "welcome_photo.jpg",
        "active_groups": []
    }
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        return {**default_settings, **saved}
    return default_settings

def save_settings():
    SETTINGS["active_groups"] = list(ACTIVE_GROUPS)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(SETTINGS, f, ensure_ascii=False, indent=2)

def load_user_stats():
    global user_stats
    if os.path.exists(USER_STATS_FILE):
        with open(USER_STATS_FILE, "r", encoding="utf-8") as f:
            user_stats = json.load(f)
    else:
        user_stats = {}

def save_user_stats():
    with open(USER_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(user_stats, f, ensure_ascii=False, indent=2)

def increment_stat(user_id, key):
    user_id = str(user_id)
    if user_id not in user_stats:
        user_stats[user_id] = {"messages_count":0, "edits_count":0, "photos_count":0}
    user_stats[user_id][key] = user_stats[user_id].get(key, 0) + 1
    save_user_stats()

def get_stats(user_id):
    user_id = str(user_id)
    if user_id not in user_stats:
        return {"messages_count":0, "edits_count":0, "photos_count":0}
    return user_stats[user_id]

SETTINGS = load_settings()
ACTIVE_GROUPS = set(SETTINGS.get("active_groups", []))
load_user_stats()

# ========== أوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    bot_username = (await context.bot.get_me()).username
    args = context.args

    if chat.type == "private":
        if args and len(args) == 1 and args[0].startswith("whisper_"):
            try:
                _, target_id_str, group_id_str = args[0].split("_")
                target_id = int(target_id_str)
                group_id = int(group_id_str)
                waiting_for_whisper[user.id] = {"target_id": target_id, "group_id": group_id}
                await update.message.reply_text(f"✅ يمكنك الآن إرسال الهمسة للمستخدم (ID: {target_id}). أرسل نص الهمسة هنا.")
                return
            except: pass

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 قناة البوت", url="https://t.me/your_channel")],
            [InlineKeyboardButton("🛠️ قناة السورس", url="https://t.me/your_source")],
            [InlineKeyboardButton("➕ أدخلني في مجموعتك", url=f"https://t.me/{bot_username}?startgroup=true")]
        ])
        await update.message.reply_text(SETTINGS["welcome_text_bot"], reply_markup=kb)

    else:
        chat_id = chat.id
        enabled = chat_id in ACTIVE_GROUPS
        btns = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تفعيل" if not enabled else "🔒 مفعّل", callback_data="enable_group" if not enabled else "noop"),
                InlineKeyboardButton("❌ تعطيل" if enabled else "✖️ معطل", callback_data="disable_group" if enabled else "noop")
            ],
            [InlineKeyboardButton("🔗 قناة البوت", url="https://t.me/your_channel")]
        ])
        await update.message.reply_text(SETTINGS["welcome_text_group"], reply_markup=btns)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    chat_id = q.message.chat.id

    if data == "enable_group":
        ACTIVE_GROUPS.add(chat_id)
        save_settings()
        await q.edit_message_reply_markup(
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔒 مفعّل", callback_data="noop"),
                 InlineKeyboardButton("❌ تعطيل", callback_data="disable_group")],
                [InlineKeyboardButton("🔗 قناة البوت", url="https://t.me/your_channel")]
            ])
        )
        msg = await context.bot.send_message(chat_id, "✅ تم تفعيل الحماية")
        await asyncio.sleep(5)
        await msg.delete()

    elif data == "disable_group":
        ACTIVE_GROUPS.discard(chat_id)
        save_settings()
        await q.edit_message_reply_markup(
            InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تفعيل", callback_data="enable_group"),
                 InlineKeyboardButton("✖️ معطل", callback_data="noop")],
                [InlineKeyboardButton("🔗 قناة البوت", url="https://t.me/your_channel")]
            ])
        )
        msg = await context.bot.send_message(chat_id, "❌ تم تعطيل الحماية")
        await asyncio.sleep(5)
        await msg.delete()

async def whisper_receive_in_private(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in waiting_for_whisper:
        await update.message.reply_text("❌ لم تطلب إرسال همسة لأي شخص.")
        return

    data = waiting_for_whisper[user_id]
    target_id = data["target_id"]
    group_id = data["group_id"]
    text = update.message.text

    if not text or len(text) > 4096:
        await update.message.reply_text("❌ نص الهمسة غير صالح أو طويل جداً.")
        return

    whisper_id = str(uuid.uuid4())
    whispers_data[whisper_id] = {
        "sender_id": user_id,
        "target_id": target_id,
        "group_id": group_id,
        "text": text
    }

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 عرض الهمسة", callback_data=f"show_whisper:{whisper_id}")]])
    try:
        await context.bot.send_message(
            chat_id=group_id,
            text=f"📩 همسة خاصة بين شخصين",
            reply_markup=kb,
            disable_notification=True
        )
    except Exception as e:
        print(f"خطأ في إرسال الهمسة: {e}")

    await update.message.reply_text("✅ تم إرسال الهمسة بنجاح.")
    del waiting_for_whisper[user_id]

async def whisper_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if not data.startswith("show_whisper:"):
        await query.answer()
        return

    whisper_id = data.split(":", 1)[1]
    if whisper_id not in whispers_data:
        await query.answer("❌ الهمسة غير موجودة.", show_alert=True)
        return

    whisper = whispers_data[whisper_id]
    if user_id != whisper["sender_id"] and user_id != whisper["target_id"]:
        await query.answer("❌ هذه الهمسة ليست لك.", show_alert=True)
        return

    await query.answer(text=f"💬 الهمسة:\n{whisper['text']}", show_alert=True)

# ======= البحث باليوتيوب =======
async def search_youtube(query):
    search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url) as resp:
            html = await resp.text()
    video_ids = re.findall(r"watch\?v=(.{11})", html)
    return f"https://www.youtube.com/watch?v={video_ids[0]}" if video_ids else None

async def download_audio(url):
    filename = str(uuid.uuid4())
    output_path = f"/tmp/{filename}.mp3"
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return output_path
    except Exception as e:
        print(f"❌ خطأ تحميل: {e}")
        return None

# ========== الرسائل في المجموعات ==========
async def message_collector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_id = update.message.message_id

    if chat_id not in ACTIVE_GROUPS:
        return

    if chat_id not in chat_messages:
        chat_messages[chat_id] = deque(maxlen=200)
    chat_messages[chat_id].append(message_id)

    user = update.effective_user
    increment_stat(user.id, "messages_count")

    text = update.message.text or ""

    if text.lower().startswith("حذف اخر"):
        match = re.search(r"حذف اخر\s+(\d+)", text.lower())
        if match:
            count = int(match.group(1))
            member_status = (await context.bot.get_chat_member(chat_id, user.id)).status
            if member_status in ["administrator", "creator"]:
                messages_to_delete = list(chat_messages[chat_id])[-count:]
                chat_messages[chat_id] = deque(list(chat_messages[chat_id])[:-count], maxlen=200)
                deleted_count = 0
                for mid in messages_to_delete:
                    try:
                        await context.bot.delete_message(chat_id, mid)
                        deleted_count += 1
                    except: pass
                try:
                    await update.message.delete()
                except: pass
                msg = await context.bot.send_message(chat_id, f"✅ تم حذف {deleted_count} رسالة.")
                await asyncio.sleep(5)
                await msg.delete()
            else:
                await update.message.reply_text("❌ هذا الأمر للمشرفين فقط.")
        return

    if text.strip() == "همسة" and update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
        bot_username = (await context.bot.get_me()).username
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📩 إرسال همسة", url=f"https://t.me/{bot_username}?start=whisper_{target_id}_{chat_id}")]])
        await update.message.reply_text("اضغط الزر لإرسال همسة سرية.", reply_markup=kb)
        try: await update.message.delete()
        except: pass
        return

    if text.lower().startswith("يوت "):
        query = text[4:].strip()
        if not query:
            await update.message.reply_text("❌ الرجاء كتابة اسم الأغنية بعد 'يوت'")
            return
        await update.message.reply_text("🔍 جارٍ البحث عن الصوت...")
        try:
            url = await search_youtube(query)
            if not url:
                await update.message.reply_text("❌ لم يتم العثور على نتيجة.")
                return
            file_path = await download_audio(url)
            if not file_path or not os.path.exists(file_path):
                await update.message.reply_text("❌ فشل تحميل الصوت.")
                return
            await context.bot.send_audio(chat_id=chat_id, audio=open(file_path, 'rb'), title=query, caption=f"🎵 {query}")
            os.remove(file_path)
        except Exception as e:
            print(f"❌ خطأ الإرسال: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء إرسال الصوت.")
        return

# ========== تشغيل البوت ==========
async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(enable_group|disable_group|noop)$"))
    app.add_handler(CallbackQueryHandler(whisper_callback_handler, pattern="^show_whisper:"))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, whisper_receive_in_private))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, message_collector))
    print("Bot started...")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.run(main())
