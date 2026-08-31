import os
from dotenv import load_dotenv

load_dotenv()

# توکن ربات - از @BotFather بگیرید
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آیدی عددی ادمین‌ها (با کاما جدا کنید اگر چند نفر هستند) مثال: 123456789,987654321
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# اطلاعات کارت برای پرداخت
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000-0000-0000-0000")
CARD_HOLDER = os.getenv("CARD_HOLDER", "نام صاحب حساب")

# مسیر دیتابیس - روی Railway پیشنهاد میشه از Volume استفاده کنید تا دیتا پاک نشه
DB_PATH = os.getenv("DB_PATH", "bot.db")

# نام برند/ربات که در پیام خوش‌آمدگویی نمایش داده میشه
BRAND_NAME = os.getenv("BRAND_NAME", "X4G")

# آیدی پشتیبانی (بدون @) - در دکمه «ارتباط با پشتیبانی» استفاده میشه
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "SuppX4G")

# کانال‌/گروه‌های عضویت اجباری — با کاما جدا کنید
# می‌تونه آیدی عددی (مثل -1001234567890) یا یوزرنیم با/بدون @ باشه (مثل @mychannel یا mychannel)
# مثال Railway: REQUIRED_CHANNELS=-1001234567890,@X4GChannel
# اگه خالی باشه، عضویت اجباری غیرفعاله
REQUIRED_CHANNELS = [x.strip() for x in os.getenv("REQUIRED_CHANNELS", "").split(",") if x.strip()]

# تنظیمات سیستم رفرال (دعوت دوستان)
REFERRAL_REQUIRED_COUNT = int(os.getenv("REFERRAL_REQUIRED_COUNT", "3"))   # تعداد خرید موفق لازم
REFERRAL_REWARD_VOLUME = int(os.getenv("REFERRAL_REWARD_VOLUME", "50"))   # حجم هدیه گیمینگ (گیگ)
# پاداش ورود با لینک دعوت — به هر دو طرف (دعوت‌کننده + دعوت‌شونده)
REFERRAL_JOIN_BONUS = int(os.getenv("REFERRAL_JOIN_BONUS", "30000"))

# تعرفه‌های پیش‌فرض سرویس گیمینگ - فقط در اولین اجرا (وقتی دیتابیس خالیه) استفاده میشه
# بعد از اون، قیمت‌ها از دیتابیس خونده میشن و از طریق دستور ادمین توی خود ربات قابل تغییرن
DEFAULT_GAMING_PLANS = [
    (10, 70000),
    (20, 140000),
    (30, 210000),
    (40, 280000),
    (50, 350000),
]

# تعرفه‌های پیش‌فرض سرویس مولتی لوکیشن (وبگردی) - فقط در اولین اجرا استفاده میشه
DEFAULT_MULTI_PLANS = [
    ("تک کاربره نامحدود یک‌ماهه", 150000),
    ("دو کاربره نامحدود یک‌ماهه", 250000),
    ("تک کاربره نامحدود دو‌ماهه", 250000),
    ("دو کاربره نامحدود دو‌ماهه", 450000),
]

# ---------- پنل پاسارگارد (تست خودکار) ----------
# اگر PASARGUARD_BASE_URL خالی باشه، تست رایگان دستی (توسط ادمین) می‌مونه
PASARGUARD_BASE_URL = os.getenv("PASARGUARD_BASE_URL", "").rstrip("/")
PASARGUARD_USERNAME = os.getenv("PASARGUARD_USERNAME", "")
PASARGUARD_PASSWORD = os.getenv("PASARGUARD_PASSWORD", "")
PASARGUARD_API_KEY = os.getenv("PASARGUARD_API_KEY", "")  # اختیاری؛ اگر باشه به‌جای یوزر/پسورد

# قالب تست (اختیاری). اگر ست بشه، کاربر از روی قالب ساخته می‌شه
PASARGUARD_TEST_TEMPLATE_ID = os.getenv("PASARGUARD_TEST_TEMPLATE_ID", "").strip() or None
if PASARGUARD_TEST_TEMPLATE_ID is not None:
    try:
        PASARGUARD_TEST_TEMPLATE_ID = int(PASARGUARD_TEST_TEMPLATE_ID)
    except ValueError:
        PASARGUARD_TEST_TEMPLATE_ID = None

# اگر قالب نباشد، از این مقادیر برای ساخت کاربر استفاده می‌شود
PASARGUARD_TEST_DATA_LIMIT_GB = float(os.getenv("PASARGUARD_TEST_DATA_LIMIT_GB", "0.3"))  # گیگ
PASARGUARD_TEST_EXPIRE_HOURS = int(os.getenv("PASARGUARD_TEST_EXPIRE_HOURS", "48"))

# گروه‌های تست — می‌تونی اسم گروه یا آیدی عددی بنویسی (با کاما جدا کن)
# مثال با اسم: PASARGUARD_TEST_GROUPS=gaming,multi
# مثال با آیدی: PASARGUARD_TEST_GROUPS=1,3
# (نام متغیر قدیمی PASARGUARD_TEST_GROUP_IDS هم هنوز کار می‌کنه)
_raw_groups = os.getenv("PASARGUARD_TEST_GROUPS") or os.getenv("PASARGUARD_TEST_GROUP_IDS") or ""
PASARGUARD_TEST_GROUPS = [x.strip() for x in _raw_groups.split(",") if x.strip()]

# پیشوند نام کاربری تست (مثلاً test_)
PASARGUARD_TEST_USERNAME_PREFIX = os.getenv("PASARGUARD_TEST_USERNAME_PREFIX", "test_")

# متن‌های نمایشی در پیام تحویل (قابل تغییر از Variables)
PASARGUARD_TEST_LOCATION_NAME = os.getenv("PASARGUARD_TEST_LOCATION_NAME", "مولتی لوکیشن")
PASARGUARD_TEST_SERVICE_NAME = os.getenv("PASARGUARD_TEST_SERVICE_NAME", "تست")

# قالب پیام تحویل — از این placeholderها استفاده کنید:
# {username} {location} {duration} {volume} {subscription_url} {service_name}
PASARGUARD_TEST_MESSAGE = os.getenv(
    "PASARGUARD_TEST_MESSAGE",
    (
        "✅ تست با موفقیت آماده شد\n\n"
        "👤 نام کاربری تست : {username}\n"
        "🌐 لوکیشن : {location}\n"
        "⌛ مدت زمان : {duration}\n"
        "📊 حجم تست : {volume}\n\n"
        "لینک اتصال 📎 :\n"
        "{subscription_url}\n\n"
        "🧑‍🦯 شما میتوانید شیوه اتصال را با فشردن دکمه زیر و انتخاب سیستم عامل خود را دریافت کنید"
    ),
)


def is_panel_auto_enabled() -> bool:
    """آیا ساخت خودکار روی پنل فعال است؟ (تست و خرید سرویس)"""
    if not PASARGUARD_BASE_URL:
        return False
    if PASARGUARD_API_KEY:
        return True
    return bool(PASARGUARD_USERNAME and PASARGUARD_PASSWORD)


# ---------- سرویس خریداری‌شده (بعد از تأیید رسید) ----------
# گروه‌های سرویس پولی — اگر خالی باشد از PASARGUARD_TEST_GROUPS استفاده می‌شود
_raw_svc_groups = os.getenv("PASARGUARD_SERVICE_GROUPS", "").strip()
PASARGUARD_SERVICE_GROUPS = (
    [x.strip() for x in _raw_svc_groups.split(",") if x.strip()]
    if _raw_svc_groups
    else list(PASARGUARD_TEST_GROUPS)
)

PASARGUARD_SERVICE_USERNAME_PREFIX = os.getenv("PASARGUARD_SERVICE_USERNAME_PREFIX", "svc_")
PASARGUARD_SERVICE_LOCATION_NAME = os.getenv(
    "PASARGUARD_SERVICE_LOCATION_NAME",
    os.getenv("PASARGUARD_TEST_LOCATION_NAME", "مولتی لوکیشن نیم بها"),
)

# مدت پیش‌فرض گیمینگ (روز) — پلن گیمینگ فقط حجم دارد
PASARGUARD_GAMING_EXPIRE_DAYS = int(os.getenv("PASARGUARD_GAMING_EXPIRE_DAYS", "30"))
# اگر از لیبل مولتی مدت استخراج نشد
PASARGUARD_MULTI_EXPIRE_DAYS = int(os.getenv("PASARGUARD_MULTI_EXPIRE_DAYS", "30"))

# قالب پیام تحویل سرویس خریداری‌شده
# {username} {service_name} {location} {duration} {volume} {subscription_url}
PASARGUARD_SERVICE_MESSAGE = os.getenv(
    "PASARGUARD_SERVICE_MESSAGE",
    (
        "✅ سرویس با موفقیت ایجاد شد\n\n"
        "👤 نام کاربری سرویس : {username}\n"
        "🚀 نام سرویس: {service_name}\n"
        "🌐 لوکیشن: {location}\n"
        "⏳ مدت زمان: {duration}\n"
        "📊 حجم سرویس: {volume}\n\n"
        "لینک اتصال:\n"
        "{subscription_url}\n\n"
        "🧑‍🦯 شما میتوانید شیوه اتصال را با فشردن دکمه زیر و انتخاب سیستم عامل خود را دریافت کنید"
    ),
)


# ---------- گردونه شانس ----------
# تعداد شانس روزانه هر کاربر
WHEEL_MAX_SPINS_PER_DAY = int(os.getenv("WHEEL_MAX_SPINS_PER_DAY", "3"))

# جوایز — با ; از هم جدا شوند. فرمت هر جایزه:
#   wallet|مبلغ_تومان|وزن
#   config|حجم_گیگ|روز|وزن     (مثال 0.5 = ۵۰۰ مگ)
#   empty|وزن
# مثال پیش‌فرض:
# WHEEL_PRIZES=wallet|10000|22;wallet|20000|14;config|0.5|30|16;empty|24;empty|24
_DEFAULT_WHEEL = "wallet|10000|22;wallet|20000|14;config|0.5|30|16;empty|24;empty|24"


def _parse_wheel_prizes(raw: str) -> list[dict]:
    prizes: list[dict] = []
    for i, part in enumerate((raw or "").split(";")):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split("|")]
        kind = (bits[0] or "").lower()
        try:
            if kind == "wallet" and len(bits) >= 3:
                amount = int(bits[1])
                weight = int(bits[2])
                prizes.append(
                    {
                        "key": f"wallet_{amount}_{i}",
                        "label": f"{amount:,} تومان کیف پول".replace(",", "٬"),
                        "weight": weight,
                        "type": "wallet",
                        "amount": amount,
                    }
                )
            elif kind == "config" and len(bits) >= 4:
                gb = float(bits[1])
                days = int(bits[2])
                weight = int(bits[3])
                if gb < 1:
                    mb = int(round(gb * 1024))
                    if abs(gb * 1024 - 512) < 2:
                        mb = 500
                    vol = f"{mb} مگ"
                else:
                    vol = f"{int(gb) if gb == int(gb) else gb} گیگ"
                prizes.append(
                    {
                        "key": f"config_{gb}_{days}_{i}",
                        "label": f"کانفیگ {vol} ({days} روزه)",
                        "weight": weight,
                        "type": "config",
                        "gb": gb,
                        "days": days,
                    }
                )
            elif kind == "empty" and len(bits) >= 2:
                weight = int(bits[1])
                prizes.append(
                    {
                        "key": f"empty_{i}",
                        "label": "پوچ 😅",
                        "weight": weight,
                        "type": "empty",
                    }
                )
        except (ValueError, IndexError):
            continue
    return prizes


WHEEL_PRIZES = _parse_wheel_prizes(os.getenv("WHEEL_PRIZES", _DEFAULT_WHEEL))
if not WHEEL_PRIZES:
    WHEEL_PRIZES = _parse_wheel_prizes(_DEFAULT_WHEEL)
