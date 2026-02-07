import asyncio
import logging
import os
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError, PhoneCodeExpiredError, PhoneCodeInvalidError

# --- الإعدادات الأساسية ---
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Missing API_ID, API_HASH, or BOT_TOKEN env vars")

API_ID = int(API_ID)

# تخزين البيانات في الذاكرة
users_db = {}
user_state = {}

logging.basicConfig(level=logging.INFO)

if not os.path.exists('sessions'):
    os.makedirs('sessions')

async def poster_task(user_id):
    """مهمة النشر التلقائي لكل حساب"""
    while True:
        u_data = users_db.get(user_id)
        if not u_data or not u_data.get("running"):
            await asyncio.sleep(5)
            continue
        
        if u_data.get("groups"):
            client = u_data["client"]
            for group in u_data["groups"]:
                if not u_data.get("running"): break
                try:
                    await client.send_message(group, u_data["text"])
                    logging.info(f"User {user_id} posted to {group}")
                except Exception as e:
                    logging.error(f"Post error for {user_id}: {e}")
                await asyncio.sleep(2) # فاصل بين المجموعات لتجنب السبام
            
            await asyncio.sleep(u_data["delay"])
        else:
            await asyncio.sleep(5)

def get_main_keyboard(user_id):
    u_data = users_db.get(user_id)
    if not u_data:
        return [[Button.inline("➕ إضافة حساب جديد", b"add_account")]]
    
    status = "🟢 يعمل" if u_data["running"] else "🔴 متوقف"
    return [
        [Button.inline(f"الحالة: {status}", b"toggle_status")],
        [Button.inline("📝 نص المنشور", b"edit_text"), Button.inline("⏱ الثواني", b"edit_delay")],
        [Button.inline("👥 المجموعات", b"manage_groups")],
        [Button.inline("❌ تسجيل الخروج", b"delete_account")]
    ]

async def start_app():
    # استخدام loop واحد ثابت لجميع العمليات
    bot = TelegramClient('bot_manager', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)

    @bot.on(events.NewMessage(pattern='/start'))
    async def start(event):
        user_id = event.sender_id
        await event.respond(
            "🚀 **مرحباً بك في بوت النشر التلقائي الاحترافي**\n\n"
            "هذا البوت يتيح لك ربط حسابك الشخصي كجلسة (Session) للنشر التلقائي.",
            buttons=get_main_keyboard(user_id)
        )

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        data = event.data
        user_id = event.sender_id

        if data == b"add_account":
            user_state[user_id] = {"step": "phone"}
            await event.respond("📱 أرسل رقم هاتفك الآن مع المفتاح الدولي\nمثال: `+9647700000000`")

        elif data == b"toggle_status" and user_id in users_db:
            users_db[user_id]["running"] = not users_db[user_id]["running"]
            await event.edit(buttons=get_main_keyboard(user_id))

        elif data == b"edit_text" and user_id in users_db:
            user_state[user_id] = {"step": "text"}
            await event.respond("📝 أرسل النص الجديد للمنشور:")

        elif data == b"edit_delay" and user_id in users_db:
            user_state[user_id] = {"step": "delay"}
            await event.respond("⏱ أرسل وقت الانتظار بالثواني (مثلاً 10):")

        elif data == b"manage_groups" and user_id in users_db:
            user_state[user_id] = {"step": "groups"}
            await event.respond("👥 أرسل يوزرات المجموعات مفصولة بمسافة (مثال: @group1 @group2):")

        elif data == b"delete_account" and user_id in users_db:
            try:
                await users_db[user_id]["client"].disconnect()
            except: pass
            del users_db[user_id]
            await event.edit("✅ تم تسجيل الخروج وحذف الجلسة.", buttons=get_main_keyboard(user_id))

    @bot.on(events.NewMessage)
    async def input_handler(event):
        user_id = event.sender_id
        if user_id not in user_state or user_state[user_id] is None: return
        
        state = user_state[user_id]
        text = event.text.strip()

        if state["step"] == "phone":
            phone = text.replace(" ", "")
            # إنشاء عميل جديد لكل مستخدم لضمان استقلالية الجلسة
            client = TelegramClient(f'sessions/{user_id}', API_ID, API_HASH)
            await client.connect()
            try:
                # طلب الكود
                result = await client.send_code_request(phone)
                user_state[user_id] = {
                    "step": "code", 
                    "phone": phone, 
                    "client": client, 
                    "hash": result.phone_code_hash
                }
                await event.respond("📩 وصلك كود من تليجرام، أرسله الآن:")
            except Exception as e:
                await event.respond(f"❌ خطأ في طلب الكود: {e}")

        elif state["step"] == "code":
            client = state["client"]
            try:
                await client.sign_in(state["phone"], text, phone_code_hash=state["hash"])
                # نجاح تسجيل الدخول
                users_db[user_id] = {
                    "client": client, 
                    "text": "منشور تلقائي", 
                    "groups": [], 
                    "delay": 10, 
                    "running": False
                }
                asyncio.create_task(poster_task(user_id))
                user_state[user_id] = None
                await event.respond("✅ تم ربط الحساب بنجاح!", buttons=get_main_keyboard(user_id))
            except SessionPasswordNeededError:
                user_state[user_id]["step"] = "password"
                await event.respond("🔐 الحساب محمي بالتحقق بخطوتين، أرسل كلمة السر:")
            except PhoneCodeExpiredError:
                await event.respond("❌ انتهت صلاحية الكود. يرجى البدء من جديد بالضغط على إضافة حساب.")
                user_state[user_id] = None
            except Exception as e:
                await event.respond(f"❌ خطأ: {e}")

        elif state["step"] == "password":
            client = state["client"]
            try:
                await client.sign_in(password=text)
                users_db[user_id] = {"client": client, "text": "منشور تلقائي", "groups": [], "delay": 10, "running": False}
                asyncio.create_task(poster_task(user_id))
                user_state[user_id] = None
                await event.respond("✅ تم الدخول بنجاح!", buttons=get_main_keyboard(user_id))
            except Exception as e:
                await event.respond(f"❌ كلمة سر خاطئة: {e}")

        elif state["step"] == "text":
            users_db[user_id]["text"] = text
            user_state[user_id] = None
            await event.respond("✅ تم حفظ النص.", buttons=get_main_keyboard(user_id))

        elif state["step"] == "delay":
            if text.isdigit():
                users_db[user_id]["delay"] = int(text)
                user_state[user_id] = None
                await event.respond(f"✅ تم ضبط الوقت على {text} ثانية.", buttons=get_main_keyboard(user_id))

        elif state["step"] == "groups":
            groups = [g.strip() for g in text.split() if g.startswith('@')]
            users_db[user_id]["groups"] = groups
            user_state[user_id] = None
            await event.respond(f"✅ تم حفظ {len(groups)} مجموعة.", buttons=get_main_keyboard(user_id))

    print("🚀 البوت المدير يعمل... اذهب إلى تليجرام وجربه")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    # ضمان استخدام الـ loop المناسب للأندرويد
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start_app())
    except KeyboardInterrupt:
        pass
