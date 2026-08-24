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

# تنظیمات سیستم رفرال (دعوت دوستان)
REFERRAL_REQUIRED_COUNT = int(os.getenv("REFERRAL_REQUIRED_COUNT", "3"))   # تعداد خرید موفق لازم
REFERRAL_REWARD_VOLUME = int(os.getenv("REFERRAL_REWARD_VOLUME", "50"))   # حجم هدیه گیمینگ (گیگ)

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
