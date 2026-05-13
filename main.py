import asyncio
import json
import os
import tempfile
from pathlib import Path

from pyrogram import Client as PyrogramClient
from pytgcalls import PyTgCalls
from pytgcalls.exceptions import NoActiveGroupCall
from pytgcalls.types import MediaStream

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===================== CONFIGURATION =====================

API_ID = 32801472
API_HASH = "80947f2a32a377b50e2e55a83ae0cd9e"
BOT_TOKEN = "8428112586:AAGCde8vBr7VjL13rpZoGo1P01Us2yzx-nw"
OWNER_ID = 8091971292

SETTINGS_FILE = "settings.json"

# ===================== SETTINGS STORAGE =====================

def load_settings() -> dict:
    if Path(SETTINGS_FILE).exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"group_id": None}


def save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


settings = load_settings()

# ===================== PYROGRAM + PYTGCALLS =====================

pyro = PyrogramClient(
    "voice_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

calls = PyTgCalls(pyro)
_calls_started = False
current_media: dict = {}

# ===================== HELPERS =====================

def get_group_id():
    return settings.get("group_id")


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


async def ensure_calls_started():
    global _calls_started
    if not _calls_started:
        await calls.start()
        _calls_started = True


def get_media_from_message(message):
    if message.audio:
        return message.audio.file_id, message.audio.file_name or "audio.mp3"
    if message.video:
        return message.video.file_id, message.video.file_name or "video.mp4"
    if message.voice:
        return message.voice.file_id, "voice.ogg"
    if message.video_note:
        return message.video_note.file_id, "videonote.mp4"
    if message.document:
        name = message.document.file_name or ""
        ext = name.lower().split(".")[-1] if "." in name else ""
        if ext in ("mp3", "ogg", "wav", "flac", "aac", "m4a", "mp4", "mkv", "avi", "mov", "webm"):
            return message.document.file_id, name
    return None


async def _play(group_id: int, file_path: str) -> None:
    await ensure_calls_started()
    stream = MediaStream(file_path)
    try:
        await calls.play(group_id, stream)
    except NoActiveGroupCall:
        raise Exception("لا يوجد استيج نشط في المجموعة. يرجى فتح الاستيج اولاً")
    except Exception as e:
        raise Exception(f"خطأ في التشغيل: {e}")

# ===================== COMMAND HANDLERS =====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = get_group_id()
    group_status = f"المجموعة الحالية: {group_id}" if group_id else "لا توجد مجموعة محددة بعد"

    me = await context.bot.get_me()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("تعيين مجموعة", callback_data="set_group_prompt")],
        [InlineKeyboardButton("اضافة البوت للمجموعة", url=f"https://t.me/{me.username}?startgroup=true")],
    ])

    await update.message.reply_text(
        f"مرحباً بك في بوت القصائد الحسينية والقرآن الكريم\n\n"
        f"{group_status}\n\n"
        f"لتشغيل مقطع صوتي او مرئي: قم بالرد على الرسالة بكلمة (تشغيل)",
        reply_markup=keyboard,
    )


async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("هذا الامر متاح للمالك فقط")
        return
    if not context.args:
        await update.message.reply_text("الاستخدام: /setgroup <group_id>")
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("يرجى ادخال رقم صحيح للمجموعة")
        return
    settings["group_id"] = gid
    save_settings(settings)
    await update.message.reply_text(f"تم تعيين المجموعة: {gid}")

# ===================== CALLBACK QUERIES =====================

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "set_group_prompt":
        if not is_owner(query.from_user.id):
            await query.answer("هذا الخيار متاح للمالك فقط", show_alert=True)
            return
        await query.answer()
        await query.message.reply_text(
            "ارسل رقم المجموعة باستخدام الامر التالي:\n/setgroup <group_id>\n\nمثال:\n/setgroup -1001234567890"
        )

    elif data == "stop":
        group_id = get_group_id()
        if not group_id:
            await query.answer("لم يتم تعيين مجموعة", show_alert=True)
            return
        try:
            await calls.leave_call(group_id)
        except Exception:
            pass
        current_media.clear()
        await query.answer()
        await query.message.edit_text("تم ايقاف التشغيل")

    elif data == "replay":
        group_id = get_group_id()
        if not group_id:
            await query.answer("لم يتم تعيين مجموعة", show_alert=True)
            return
        if not current_media.get("file_path"):
            await query.answer("لا يوجد مقطع للاعادة", show_alert=True)
            return
        try:
            await _play(group_id, current_media["file_path"])
            await query.answer("تمت اعادة التشغيل")
        except Exception as e:
            await query.answer(f"خطأ: {e}", show_alert=True)

# ===================== PLAY TRIGGER =====================

async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.reply_to_message:
        return

    if not message.text or message.text.strip() != "تشغيل":
        return

    group_id = get_group_id()
    if not group_id:
        await message.reply_text("لم يتم تعيين مجموعة بعد. تواصل مع المالك لتعيين المجموعة")
        return

    media = get_media_from_message(message.reply_to_message)
    if not media:
        await message.reply_text("الرسالة لا تحتوي على ملف صوتي او مرئي مدعوم (mp3, mp4)")
        return

    file_id, file_name = media
    status_msg = await message.reply_text("جاري تحميل الملف...")

    tmp_dir = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, file_name)

    try:
        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(file_path)
    except Exception as e:
        await status_msg.edit_text(f"فشل تحميل الملف: {e}")
        return

    await status_msg.edit_text("جاري الصعود للاستيج...")

    try:
        await _play(group_id, file_path)
    except Exception as e:
        await status_msg.edit_text(f"فشل تشغيل الملف: {e}")
        return

    current_media["file_path"] = file_path

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ايقاف", callback_data="stop"),
            InlineKeyboardButton("اعادة التشغيل", callback_data="replay"),
        ]
    ])

    await status_msg.edit_text(
        "يتم التشغيل الآن في الاستيج",
        reply_markup=keyboard,
    )

# ===================== ENTRYPOINT =====================

async def main():
    await pyro.start()
    print("Pyrogram client started for voice chats")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(
        MessageHandler(filters.REPLY & filters.Regex(r"^تشغيل$"), cmd_play)
    )

    async with app:
        await app.start()
        me = await app.bot.get_me()
        print(f"البوت يعمل الآن... @{me.username}")
        await app.updater.start_polling(drop_pending_updates=True)
        while True:
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
