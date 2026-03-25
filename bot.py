"""
بوت تيليجرام لتحميل الميديا + نظام إعلانات إجباري
"""

import logging
import os
import re
import asyncio
import tempfile
import time
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import yt_dlp

BOT_TOKEN        = "8243416431:AAG5eZHOLB3vSgC_V2lLlQMdjkF-4oE7M_s"
MONETAG_URL      = "https://www.profitablecpmratenetwork.com/u8gmpfy20?key=8c14ee6a74908a6a9a9a8d4358ab80bf"
AD_FORCE_WAIT    = 30       # ثواني انتظار إجباري بعد الضغط على الإعلان
AD_COOLDOWN      = 60 * 60  # ساعة وصول مجاني بعد مشاهدة الإعلان
MAX_FILE_SIZE_MB = 50
DOWNLOAD_DIR     = "downloads"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# نظام التحقق الإجباري
# ad_watched  = user_id → وقت منح الوصول (بعد انتهاء الانتظار)
# ad_clicked  = user_id → وقت ضغط زر الإعلان
# ─────────────────────────────────────────────
ad_watched: dict = {}
ad_clicked: dict = {}

def user_has_access(user_id: int) -> bool:
    last = ad_watched.get(user_id, 0)
    return (time.time() - last) < AD_COOLDOWN

def record_ad_click(user_id: int):
    """تسجيل لحظة ضغط زر الإعلان"""
    ad_clicked[user_id] = time.time()

def user_waited_enough(user_id: int) -> bool:
    """هل انتظر المستخدم الوقت الكافي؟"""
    clicked = ad_clicked.get(user_id, 0)
    return clicked > 0 and (time.time() - clicked) >= AD_FORCE_WAIT

def seconds_remaining(user_id: int) -> int:
    clicked = ad_clicked.get(user_id, 0)
    if clicked == 0:
        return AD_FORCE_WAIT
    remaining = AD_FORCE_WAIT - (time.time() - clicked)
    return max(0, int(remaining))

def grant_access(user_id: int):
    ad_watched[user_id] = time.time()
    ad_clicked.pop(user_id, None)

def time_left(user_id: int) -> str:
    last = ad_watched.get(user_id, 0)
    remaining = AD_COOLDOWN - (time.time() - last)
    mins = int(remaining // 60)
    return f"{mins} دقيقة"

# ─────────────────────────────────────────────
# المنصات
# ─────────────────────────────────────────────
def detect_platform(url: str) -> str:
    url = url.lower()
    if any(x in url for x in ["youtube.com", "youtu.be"]): return "youtube"
    elif any(x in url for x in ["twitter.com", "x.com"]):  return "twitter"
    elif "tiktok.com" in url:                               return "tiktok"
    elif "instagram.com" in url:                            return "instagram"
    elif "snapchat.com" in url:                             return "snapchat"
    elif "reddit.com" in url:                               return "reddit"
    elif "facebook.com" in url or "fb.watch" in url:        return "facebook"
    return "unknown"

def is_valid_url(text: str) -> bool:
    return bool(re.search(r'https?://[^\s]+', text))

def extract_url(text: str) -> str:
    m = re.search(r'https?://[^\s]+', text)
    return m.group(0) if m else ""

PLATFORM_EMOJI = {
    "youtube": "▶️ يوتيوب", "twitter": "🐦 تويتر/X",
    "tiktok": "🎵 تيك توك", "instagram": "📸 انستجرام",
    "snapchat": "👻 سناب شات", "reddit": "🤖 ريديت",
    "facebook": "📘 فيسبوك", "unknown": "🔗 رابط",
}

# ─────────────────────────────────────────────
# التحميل
# ─────────────────────────────────────────────
def get_ydl_opts(platform: str, quality: str, output_path: str) -> dict:
    base = {"outtmpl": output_path, "quiet": True, "no_warnings": True,
            "noplaylist": True, "socket_timeout": 30}
    if quality == "audio":
        return {**base, "format": "bestaudio/best",
                "postprocessors": [{"key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3", "preferredquality": "192"}]}
    fmt = {
        "high":   "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "medium": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "low":    "bestvideo[height<=480]+bestaudio/best[height<=480]",
    }.get(quality, "bestvideo[height<=720]+bestaudio/best[height<=720]")
    if platform == "tiktok":
        return {**base, "format": fmt, "http_headers": {"User-Agent": "Mozilla/5.0"}}
    elif platform == "youtube":
        return {**base, "format": fmt, "merge_output_format": "mp4"}
    return {**base, "format": fmt}

async def download_media(url: str, platform: str, quality: str) -> dict:
    try:
        with tempfile.TemporaryDirectory(dir=DOWNLOAD_DIR) as tmp_dir:
            opts = get_ydl_opts(platform, quality, os.path.join(tmp_dir, "%(title).50s.%(ext)s"))
            with yt_dlp.YoutubeDL({**opts, "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "ميديا")
                media_type = "photo" if info.get("ext") in ["jpg","png","webp"] else "video"
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            files = list(Path(tmp_dir).glob("*"))
            if not files: return {"success": False, "error": "لم يحمل اي ملف"}
            downloaded = files[0]
            size_mb = downloaded.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                return {"success": False, "error": f"الملف كبير جدا ({size_mb:.1f}MB)"}
            final_path = os.path.join(DOWNLOAD_DIR, downloaded.name)
            downloaded.rename(final_path)
            return {"success": True, "path": final_path, "title": title,
                    "type": media_type, "size_mb": round(size_mb, 1)}
    except yt_dlp.utils.DownloadError as e:
        err = str(e)
        if "private" in err.lower(): return {"success": False, "error": "المنشور خاص"}
        return {"success": False, "error": f"فشل التحميل: {err[:100]}"}
    except Exception as e:
        return {"success": False, "error": "حدث خطا، حاول مرة اخرى"}

def quality_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 عالية 1080p", callback_data="quality_high"),
         InlineKeyboardButton("📱 متوسطة 720p", callback_data="quality_medium")],
        [InlineKeyboardButton("💾 منخفضة 480p", callback_data="quality_low"),
         InlineKeyboardButton("🎵 صوت MP3", callback_data="quality_audio")],
    ])

# ─────────────────────────────────────────────
# الأوامر
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "اهلا! انا بوت تحميل الميديا\n\n"
        "ارسل اي رابط من:\n"
        "يوتيوب | تيك توك | تويتر | انستجرام | سناب | فيسبوك\n\n"
        "كل تحميل يتطلب مشاهدة اعلان قصير\n"
        "بعدها وصول مجاني لمدة ساعة كاملة!"
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if not is_valid_url(text):
        await update.message.reply_text("ارسل رابطا صحيحا")
        return

    url = extract_url(text)
    platform = detect_platform(url)

    if platform == "unknown":
        await update.message.reply_text("المنصة غير مدعومة")
        return

    context.user_data["url"] = url
    context.user_data["platform"] = platform
    platform_name = PLATFORM_EMOJI.get(platform, "رابط")

    # عنده وصول؟ مباشرة للجودة
    if user_has_access(user_id):
        await update.message.reply_text(
            f"رابط {platform_name} جاهز!\n"
            f"وصولك المجاني: {time_left(user_id)} متبقية\n\n"
            "اختر الجودة:",
            reply_markup=quality_keyboard()
        )
    else:
        # يلزمه إعلان - زر واحد فقط الآن
        keyboard = [[InlineKeyboardButton(
            f"👉 اضغط هنا لمشاهدة الاعلان ({AD_FORCE_WAIT} ثانية)",
            callback_data="ad_open"
        )]]
        await update.message.reply_text(
            f"رابط {platform_name} جاهز!\n\n"
            f"لتحميل المقطع، اضغط الزر وانتظر {AD_FORCE_WAIT} ثانية\n"
            "ثم سيظهر لك زر التحميل تلقائيا",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ─────────────────────────────────────────────
# الخطوة 1: ضغط زر الإعلان → فتح الرابط + تسجيل الوقت
# ─────────────────────────────────────────────
async def handle_ad_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # تسجيل وقت الضغط
    record_ad_click(user_id)

    # تعديل الرسالة - زر الإعلان + زر التأكيد معطل
    keyboard = [
        [InlineKeyboardButton("🌐 افتح الاعلان", url=MONETAG_URL)],
        [InlineKeyboardButton(f"⏳ انتظر {AD_FORCE_WAIT} ثانية...", callback_data="ad_too_early")],
    ]
    await query.edit_message_text(
        f"افتح الاعلان واتركه يشتغل {AD_FORCE_WAIT} ثانية\n\n"
        f"بعد {AD_FORCE_WAIT} ثانية سيتفعل زر التحميل تلقائيا",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # انتظر AD_FORCE_WAIT ثانية ثم حدّث الرسالة تلقائياً
    await asyncio.sleep(AD_FORCE_WAIT)

    # تحقق أن المستخدم لم يحصل على وصول بعد
    if not user_has_access(user_id) and ad_clicked.get(user_id, 0) > 0:
        keyboard_done = [[InlineKeyboardButton(
            "✅ تم! اضغط هنا للتحميل", callback_data="ad_done"
        )]]
        try:
            await query.edit_message_text(
                "انتهى وقت الاعلان!\n\nاضغط الزر للتحميل:",
                reply_markup=InlineKeyboardMarkup(keyboard_done)
            )
        except Exception:
            pass

# ─────────────────────────────────────────────
# الخطوة 2: ضغط زر التأكيد → التحقق من الوقت
# ─────────────────────────────────────────────
async def handle_ad_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "ad_too_early":
        secs = seconds_remaining(user_id)
        if secs > 0:
            # لم ينتظر بعد
            await query.answer(
                f"انتظر {secs} ثانية اخرى!",
                show_alert=True
            )
        return

    if query.data == "ad_done":
        if not user_waited_enough(user_id):
            secs = seconds_remaining(user_id)
            await query.answer(
                f"لم تنتظر بعد! باقي {secs} ثانية",
                show_alert=True
            )
            return

        # منح الوصول
        grant_access(user_id)
        await query.edit_message_text(
            "تم فتح التحميل لمدة ساعة كاملة!\n\nاختر الجودة:",
            reply_markup=quality_keyboard()
        )

# ─────────────────────────────────────────────
# التحميل بعد اختيار الجودة
# ─────────────────────────────────────────────
async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    quality = query.data.replace("quality_", "")
    url = context.user_data.get("url")
    platform = context.user_data.get("platform")

    if not url:
        await query.edit_message_text("انتهت الجلسة، ارسل الرابط مجددا")
        return

    if not user_has_access(user_id):
        await query.edit_message_text("انتهى وصولك!\n\nارسل الرابط مجددا")
        return

    labels = {"high": "1080p", "medium": "720p", "low": "480p", "audio": "MP3"}
    await query.edit_message_text(
        f"جاري التحميل بجودة {labels.get(quality, '')}...\n"
        f"{PLATFORM_EMOJI.get(platform, '')}\n\nانتظر لحظة..."
    )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: asyncio.run(download_media(url, platform, quality))
    )

    if not result["success"]:
        await query.edit_message_text(f"فشل التحميل\n\n{result['error']}")
        return

    await query.edit_message_text("جاري الارسال...")
    file_path = result["path"]
    caption = f"{result.get('title','')}\n{result.get('size_mb',0)}MB | {PLATFORM_EMOJI.get(platform,'')}"

    try:
        with open(file_path, "rb") as f:
            if quality == "audio":
                await query.message.reply_audio(audio=f, title=result.get("title",""), caption=caption)
            elif result["type"] == "photo":
                await query.message.reply_photo(photo=f, caption=caption)
            else:
                await query.message.reply_video(video=f, caption=caption, supports_streaming=True)
        await query.edit_message_text(
            f"تم التحميل!\nوصولك المجاني: {time_left(user_id)} متبقية"
        )
    except Exception as e:
        logger.error(f"خطا ارسال: {e}")
        await query.edit_message_text("فشل الارسال، الملف قد يكون كبيرا جدا")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "كيفية الاستخدام:\n\n"
        "1 - ارسل رابط الفيديو\n"
        "2 - شاهد اعلانا لمدة 30 ثانية (مرة كل ساعة)\n"
        "3 - اختر الجودة\n"
        "4 - استلم الملف"
    )

# ─────────────────────────────────────────────
# التشغيل
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(handle_ad_open,     pattern="^ad_open$"))
    app.add_handler(CallbackQueryHandler(handle_ad_callback, pattern="^ad_(done|too_early)$"))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern="^quality_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    print("البوت يعمل مع نظام الاعلانات الاجباري...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
