import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pytgcalls import PyTgCalls
from pytgcalls.exceptions import NoActiveGroupCall
from pytgcalls.types import AudioPiped, MediaStream, VideoParameters

# ===================== CONFIGURATION =====================

API_ID = 32801472
API_HASH = "80947f2a32a377b50e2e55a83ae0cd9e"
BOT_TOKEN = "8428112586:AAEVk_MNuZchp2eHGFB_7mYST5ohVc0bp68"
OWNER_ID = 6668195885

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

# ===================== CLIENTS =====================

app = Client(
    "bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

calls = PyTgCalls(app)

# ===================== STATE =====================

current_media: dict = {}


# ===================== HELPERS =====================

def get_group_id() -> int | None:
    return settings.get("group_id")


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def get_media_from_message(message: Message):
    """
    Return (file_id, file_name, is_video) from a message that contains
    audio or video, or None if the message has no supported media.
    """
    if message.audio:
        return message.audio.file_id, message.audio.file_name or "audio.mp3", False
    if message.video:
        return message.video.file_id, message.video.file_name or "video.mp4", True
    if message.voice:
        return message.voice.file_id, "voice.ogg", False
    if message.video_note:
        return message.video_note.file_id, "videonote.mp4", True
    if message.document:
        name = message.document.file_name or ""
        if name.lower().endswith((".mp3", ".ogg", ".wav", ".flac", ".aac", ".m4a")):
            return message.document.file_id, name, False
        if name.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm")):
            return message.document.file_id, name, True
    return None


# ===================== COMMANDS =====================

@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, message: Message):
    group_id = get_group_id()
    group_status = f"المجموعة الحالية: {group_id}" if group_id else "لا توجد مجموعة محددة بعد"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("تعيين مجموعة", callback_data="set_group_prompt")],
        [InlineKeyboardButton("اضافة البوت للمجموعة", url=f"https://t.me/{(await client.get_me()).username}?startgroup=true")],
    ])

    await message.reply_text(
        f"مرحباً بك في بوت القصائد الحسينية والقرآن الكريم\n\n"
        f"{group_status}\n\n"
        f"لتشغيل مقطع صوتي او مرئي: قم بالرد على الرسالة بكلمة (تشغيل)",
        reply_markup=keyboard,
    )


@app.on_message(filters.command("setgroup") & filters.private)
async def cmd_setgroup(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply_text("هذا الامر متاح للمالك فقط")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("الاستخدام: /setgroup <group_id>")
        return
    try:
        gid = int(parts[1])
    except ValueError:
        await message.reply_text("يرجى ادخال رقم صحيح للمجموعة")
        return
    settings["group_id"] = gid
    save_settings(settings)
    await message.reply_text(f"تم تعيين المجموعة: {gid}")


# ===================== CALLBACK QUERIES =====================

@app.on_callback_query(filters.regex("^set_group_prompt$"))
async def cb_set_group_prompt(client: Client, callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("هذا الخيار متاح للمالك فقط", show_alert=True)
        return
    await callback.message.reply_text(
        "ارسل رقم المجموعة باستخدام الامر التالي:\n/setgroup <group_id>\n\nمثال:\n/setgroup -1001234567890"
    )
    await callback.answer()


@app.on_callback_query(filters.regex("^stop$"))
async def cb_stop(client: Client, callback: CallbackQuery):
    group_id = get_group_id()
    if not group_id:
        await callback.answer("لم يتم تعيين مجموعة", show_alert=True)
        return
    try:
        await calls.leave_call(group_id)
    except NoActiveGroupCall:
        pass
    except Exception:
        pass
    current_media.clear()
    await callback.message.edit_text("تم ايقاف التشغيل")
    await callback.answer()


@app.on_callback_query(filters.regex("^replay$"))
async def cb_replay(client: Client, callback: CallbackQuery):
    group_id = get_group_id()
    if not group_id:
        await callback.answer("لم يتم تعيين مجموعة", show_alert=True)
        return
    if not current_media.get("file_path"):
        await callback.answer("لا يوجد مقطع للاعادة", show_alert=True)
        return
    try:
        await _play(group_id, current_media["file_path"], current_media.get("is_video", False))
        await callback.answer("تمت اعادة التشغيل")
    except Exception as e:
        await callback.answer(f"خطأ: {e}", show_alert=True)


# ===================== PLAY TRIGGER =====================

@app.on_message(filters.reply & filters.regex(r"^تشغيل$"))
async def cmd_play(client: Client, message: Message):
    group_id = get_group_id()
    if not group_id:
        await message.reply_text("لم يتم تعيين مجموعة بعد. تواصل مع المالك لتعيين المجموعة")
        return

    replied = message.reply_to_message
    if not replied:
        await message.reply_text("يرجى الرد على رسالة تحتوي على صوت او فيديو")
        return

    media = get_media_from_message(replied)
    if not media:
        await message.reply_text("الرسالة لا تحتوي على ملف صوتي او مرئي مدعوم (mp3, mp4)")
        return

    file_id, file_name, is_video = media

    status_msg = await message.reply_text("جاري تحميل الملف...")

    tmp_dir = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, file_name)

    try:
        await client.download_media(file_id, file_name=file_path)
    except Exception as e:
        await status_msg.edit_text(f"فشل تحميل الملف: {e}")
        return

    await status_msg.edit_text("جاري الصعود للاستيج...")

    try:
        await _play(group_id, file_path, is_video)
    except Exception as e:
        await status_msg.edit_text(f"فشل تشغيل الملف: {e}")
        return

    current_media["file_path"] = file_path
    current_media["is_video"] = is_video

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ايقاف", callback_data="stop"),
            InlineKeyboardButton("اعادة التشغيل", callback_data="replay"),
        ]
    ])

    media_type = "المرئي" if is_video else "الصوتي"
    await status_msg.edit_text(
        f"يتم تشغيل المقطع {media_type} في الاستيج",
        reply_markup=keyboard,
    )


# ===================== PLAY FUNCTION =====================

async def _play(group_id: int, file_path: str, is_video: bool) -> None:
    if is_video:
        stream = MediaStream(
            file_path,
            video_parameters=VideoParameters(
                width=1280,
                height=720,
                frame_rate=30,
            ),
        )
    else:
        stream = MediaStream(file_path)

    try:
        await calls.play(group_id, stream)
    except NoActiveGroupCall:
        raise Exception("لا يوجد استيج نشط في المجموعة. يرجى فتح الاستيج اولاً")


# ===================== ENTRYPOINT =====================

async def main():
    await app.start()
    await calls.start()
    print("البوت يعمل الآن...")
    await asyncio.get_event_loop().create_future()


if __name__ == "__main__":
    asyncio.run(main())
