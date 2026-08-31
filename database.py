import aiosqlite
from datetime import datetime
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                plan_id INTEGER,
                plan_name TEXT,
                price INTEGER,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'pending',
                panel_info TEXT,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                referred_username TEXT,
                converted INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reward_claims (
                referrer_id INTEGER PRIMARY KEY,
                claimed_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS gaming_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                volume_gb INTEGER NOT NULL,
                price INTEGER NOT NULL,
                active INTEGER DEFAULT 1
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS multi_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                price INTEGER NOT NULL,
                active INTEGER DEFAULT 1
            )
            """
        )
        # دسته‌های تعرفه سفارشی (مثل «اختلالات شدید»)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
            """
        )
        # پلن‌های داخل هر دسته سفارشی
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tariff_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                price INTEGER NOT NULL,
                active INTEGER DEFAULT 1,
                FOREIGN KEY (category_id) REFERENCES tariff_categories(id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallets (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS wallet_topups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                amount INTEGER NOT NULL,
                receipt_file_id TEXT,
                status TEXT DEFAULT 'awaiting_receipt',
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT,
                last_seen TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                role TEXT NOT NULL,
                added_by INTEGER,
                added_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                percent INTEGER NOT NULL,
                max_uses INTEGER,
                used_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS referral_commissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS free_tests (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                status TEXT DEFAULT 'pending',
                panel_info TEXT,
                created_at TEXT,
                delivered_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS wheel_spins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                prize_key TEXT NOT NULL,
                prize_label TEXT,
                created_at TEXT NOT NULL,
                spin_date TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_wheel_spins_user_date ON wheel_spins(user_id, spin_date)"
        )
        await db.commit()

        # مهاجرت: ستون payment_method به جدول orders (برای دیتابیس‌های قدیمی‌تر که این ستون رو ندارن)
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT DEFAULT 'receipt'")
            await db.commit()
        except Exception:
            pass  # ستون از قبل وجود داره

        # مهاجرت: ستون‌های کد تخفیف روی orders
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN coupon_code TEXT")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN original_price INTEGER")
            await db.commit()
        except Exception:
            pass
        # برای سفارش‌های قدیمی که original_price نداشتن، برابر با price در نظر گرفته میشه
        await db.execute("UPDATE orders SET original_price = price WHERE original_price IS NULL")
        await db.commit()

        # اولین اجرا: اگه جدول‌های تعرفه خالی بودن، از مقادیر پیش‌فرض config.py پر می‌شن
        import config

        cursor = await db.execute("SELECT COUNT(*) FROM gaming_plans")
        row = await cursor.fetchone()
        if row[0] == 0:
            for volume, price in config.DEFAULT_GAMING_PLANS:
                await db.execute(
                    "INSERT INTO gaming_plans (volume_gb, price, active) VALUES (?, ?, 1)", (volume, price)
                )
            await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM multi_plans")
        row = await cursor.fetchone()
        if row[0] == 0:
            for label, price in config.DEFAULT_MULTI_PLANS:
                await db.execute(
                    "INSERT INTO multi_plans (label, price, active) VALUES (?, ?, 1)", (label, price)
                )
            await db.commit()


async def create_order(user_id, username, full_name, plan_id, plan_name, price, payment_method="receipt"):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO orders (user_id, username, full_name, plan_id, plan_name, price, original_price, status, payment_method, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_receipt', ?, ?)""",
            (user_id, username, full_name, plan_id, plan_name, price, price, payment_method, datetime.now().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def apply_coupon_to_order(order_id: int, code: str, new_price: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET price = ?, coupon_code = ? WHERE id = ?", (new_price, code, order_id)
        )
        await db.commit()


async def remove_coupon_from_order(order_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET price = original_price, coupon_code = NULL WHERE id = ?", (order_id,)
        )
        await db.commit()


async def mark_order_paid_by_wallet(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET payment_method = 'wallet', status = 'pending' WHERE id = ?", (order_id,)
        )
        await db.commit()


async def attach_receipt(order_id, file_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET receipt_file_id = ?, status = 'pending' WHERE id = ?",
            (file_id, order_id),
        )
        await db.commit()


async def get_order(order_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
        return await cursor.fetchone()


async def set_order_status(order_id, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        await db.commit()


async def deliver_order(order_id, panel_info):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE orders SET status = 'delivered', panel_info = ? WHERE id = ?",
            (panel_info, order_id),
        )
        await db.commit()


async def get_user_orders(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,)
        )
        return await cursor.fetchall()


async def get_last_pending_order_without_receipt(user_id, plan_id):
    """آخرین سفارش کاربر برای یک پلن خاص که هنوز رسیدش ثبت نشده"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT * FROM orders WHERE user_id = ? AND plan_id = ? AND status = 'awaiting_receipt'
               ORDER BY id DESC LIMIT 1""",
            (user_id, plan_id),
        )
        return await cursor.fetchone()


# ---------- Referral system ----------
async def add_referral(referrer_id: int, referred_id: int, referred_username: str) -> bool:
    """ثبت یک رفرال جدید. اگر کاربر قبلاً رفرال شده باشه، False برمی‌گردونه."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM referrals WHERE referred_id = ?", (referred_id,))
        if await cursor.fetchone():
            return False
        await db.execute(
            """INSERT INTO referrals (referrer_id, referred_id, referred_username, converted, created_at)
               VALUES (?, ?, ?, 0, ?)""",
            (referrer_id, referred_id, referred_username, datetime.now().isoformat()),
        )
        await db.commit()
        return True


async def get_referral_by_referred(referred_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM referrals WHERE referred_id = ?", (referred_id,))
        return await cursor.fetchone()


async def mark_referral_converted(referred_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE referrals SET converted = 1 WHERE referred_id = ? AND converted = 0", (referred_id,)
        )
        await db.commit()


async def count_referrals(referrer_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (referrer_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def count_converted_referrals(referrer_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND converted = 1", (referrer_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def has_claimed_reward(referrer_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT 1 FROM reward_claims WHERE referrer_id = ?", (referrer_id,))
        return await cursor.fetchone() is not None


async def set_reward_claimed(referrer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO reward_claims (referrer_id, claimed_at) VALUES (?, ?)",
            (referrer_id, datetime.now().isoformat()),
        )
        await db.commit()


# ---------- Gaming plans (تعرفه سرویس گیمینگ) ----------
async def get_gaming_plans(active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM gaming_plans"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY volume_gb ASC"
        cursor = await db.execute(query)
        return await cursor.fetchall()


async def get_gaming_plan(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM gaming_plans WHERE id = ?", (plan_id,))
        return await cursor.fetchone()


async def get_gaming_plan_by_volume(volume_gb: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM gaming_plans WHERE volume_gb = ? ORDER BY id LIMIT 1", (volume_gb,)
        )
        return await cursor.fetchone()


async def update_gaming_price(plan_id: int, new_price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gaming_plans SET price = ? WHERE id = ?", (new_price, plan_id))
        await db.commit()


async def toggle_gaming_active(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE gaming_plans SET active = 1 - active WHERE id = ?", (plan_id,))
        await db.commit()


async def add_gaming_plan(volume_gb: int, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO gaming_plans (volume_gb, price, active) VALUES (?, ?, 1)", (volume_gb, price)
        )
        await db.commit()


async def delete_gaming_plan(plan_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM gaming_plans WHERE id = ?", (plan_id,))
        await db.commit()


# ---------- Multi-location plans (تعرفه سرویس مولتی لوکیشن) ----------
async def get_multi_plans(active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM multi_plans"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY id ASC"
        cursor = await db.execute(query)
        return await cursor.fetchall()


async def get_multi_plan(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM multi_plans WHERE id = ?", (plan_id,))
        return await cursor.fetchone()


async def update_multi_price(plan_id: int, new_price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE multi_plans SET price = ? WHERE id = ?", (new_price, plan_id))
        await db.commit()


async def toggle_multi_active(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE multi_plans SET active = 1 - active WHERE id = ?", (plan_id,))
        await db.commit()


async def add_multi_plan(label: str, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO multi_plans (label, price, active) VALUES (?, ?, 1)", (label, price))
        await db.commit()


async def delete_multi_plan(plan_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM multi_plans WHERE id = ?", (plan_id,))
        await db.commit()


# ---------- Custom tariff categories (دسته‌های تعرفه سفارشی) ----------
async def get_tariff_categories(active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM tariff_categories"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY id ASC"
        cursor = await db.execute(query)
        return await cursor.fetchall()


async def get_tariff_category(category_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tariff_categories WHERE id = ?", (category_id,))
        return await cursor.fetchone()


async def add_tariff_category(name: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO tariff_categories (name, active, created_at) VALUES (?, 1, ?)",
            (name, datetime.now().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def toggle_tariff_category(category_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tariff_categories SET active = 1 - active WHERE id = ?", (category_id,)
        )
        await db.commit()


async def delete_tariff_category(category_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tariff_plans WHERE category_id = ?", (category_id,))
        await db.execute("DELETE FROM tariff_categories WHERE id = ?", (category_id,))
        await db.commit()


async def rename_tariff_category(category_id: int, name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tariff_categories SET name = ? WHERE id = ?", (name, category_id))
        await db.commit()


async def get_tariff_plans(category_id: int, active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM tariff_plans WHERE category_id = ?"
        params: list = [category_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY id ASC"
        cursor = await db.execute(query, params)
        return await cursor.fetchall()


async def get_tariff_plan(plan_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tariff_plans WHERE id = ?", (plan_id,))
        return await cursor.fetchone()


async def add_tariff_plan(category_id: int, label: str, price: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO tariff_plans (category_id, label, price, active) VALUES (?, ?, ?, 1)",
            (category_id, label, price),
        )
        await db.commit()
        return cur.lastrowid


async def update_tariff_plan_price(plan_id: int, price: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tariff_plans SET price = ? WHERE id = ?", (price, plan_id))
        await db.commit()


async def toggle_tariff_plan(plan_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tariff_plans SET active = 1 - active WHERE id = ?", (plan_id,))
        await db.commit()


async def delete_tariff_plan(plan_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tariff_plans WHERE id = ?", (plan_id,))
        await db.commit()


# ---------- Settings (تنظیمات پویا - قابل تغییر توسط ادمین از داخل ربات) ----------
async def get_setting(key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, str(value)),
        )
        await db.commit()


async def get_welcome_message():
    """پیام خوش‌آمدگویی سفارشی؛ اگه ادمین تنظیم نکرده باشه None برمی‌گردونه (یعنی از متن پیش‌فرض استفاده بشه)."""
    return await get_setting("welcome_message")


async def set_welcome_message(text: str) -> None:
    await set_setting("welcome_message", text)


async def get_referral_required_count() -> int:
    import config
    val = await get_setting("referral_required_count")
    return int(val) if val is not None else config.REFERRAL_REQUIRED_COUNT


async def get_referral_reward_volume() -> int:
    import config
    val = await get_setting("referral_reward_volume")
    return int(val) if val is not None else config.REFERRAL_REWARD_VOLUME


async def get_rules_text():
    """متن قوانین سفارشی؛ اگه ادمین تنظیم نکرده باشه None برمی‌گردونه (یعنی از متن پیش‌فرض استفاده بشه)."""
    return await get_setting("rules_text")


async def set_rules_text(text: str) -> None:
    await set_setting("rules_text", text)


# ---------- Wallet (کیف پول) ----------
async def get_wallet_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def add_wallet_balance(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO wallets (user_id, balance) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET balance = balance + excluded.balance""",
            (user_id, amount),
        )
        await db.commit()


async def deduct_wallet_balance(user_id: int, amount: int) -> bool:
    """در صورت کافی بودن موجودی، مبلغ رو کم می‌کنه و True برمی‌گردونه؛ وگرنه False."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        balance = row[0] if row else 0
        if balance < amount:
            return False
        await db.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        await db.commit()
        return True


async def create_wallet_topup(user_id: int, username: str, full_name: str, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO wallet_topups (user_id, username, full_name, amount, status, created_at)
               VALUES (?, ?, ?, ?, 'awaiting_receipt', ?)""",
            (user_id, username, full_name, amount, datetime.now().isoformat()),
        )
        await db.commit()
        return cursor.lastrowid


async def get_wallet_topup(topup_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM wallet_topups WHERE id = ?", (topup_id,))
        return await cursor.fetchone()


async def attach_topup_receipt(topup_id: int, file_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE wallet_topups SET receipt_file_id = ?, status = 'pending' WHERE id = ?",
            (file_id, topup_id),
        )
        await db.commit()


async def set_topup_status(topup_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE wallet_topups SET status = ? WHERE id = ?", (status, topup_id))
        await db.commit()


async def set_wallet_balance(user_id: int, amount: int) -> None:
    """موجودی کیف پول رو مستقیماً روی یه عدد مشخص تنظیم می‌کنه (برای اصلاح دستی توسط ادمین)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO wallets (user_id, balance) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET balance = excluded.balance""",
            (user_id, amount),
        )
        await db.commit()


# ---------- Users (لیست کاربران و جست‌وجو) ----------
async def touch_user(user_id: int, username: str, full_name: str) -> None:
    """هر بار کاربر با ربات تعامل داشت، رکورد کاربر رو ثبت/بروزرسانی می‌کنه."""
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (user_id, username, full_name, joined_at, last_seen)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   full_name = excluded.full_name,
                   last_seen = excluded.last_seen""",
            (user_id, username, full_name, now, now),
        )
        await db.commit()


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def search_users(query: str, limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query.lstrip("-").isdigit():
            cursor = await db.execute(
                "SELECT * FROM users WHERE user_id = ? LIMIT ?", (int(query), limit)
            )
        else:
            clean = query.lstrip("@")
            cursor = await db.execute(
                "SELECT * FROM users WHERE username LIKE ? ORDER BY last_seen DESC LIMIT ?",
                (f"%{clean}%", limit),
            )
        return await cursor.fetchall()


async def list_users(limit: int = 15, offset: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY last_seen DESC LIMIT ? OFFSET ?", (limit, offset)
        )
        return await cursor.fetchall()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_recent_orders(limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))
        return await cursor.fetchall()


# ---------- Admins (سطوح دسترسی ادمین‌ها) ----------
async def add_admin(user_id: int, role: str, added_by: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO admins (user_id, role, added_by, added_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET role = excluded.role, added_by = excluded.added_by""",
            (user_id, role, added_by, datetime.now().isoformat()),
        )
        await db.commit()


async def remove_admin(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_admin_role(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT role FROM admins WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else None


async def list_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM admins ORDER BY added_at DESC")
        return await cursor.fetchall()


# ---------- Coupons (کد تخفیف) ----------
async def create_coupon(code: str, percent: int, max_uses: int | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT code FROM coupons WHERE code = ?", (code,))
        if await cursor.fetchone():
            return False
        await db.execute(
            """INSERT INTO coupons (code, percent, max_uses, used_count, active, created_at)
               VALUES (?, ?, ?, 0, 1, ?)""",
            (code, percent, max_uses, datetime.now().isoformat()),
        )
        await db.commit()
        return True


async def get_coupon(code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM coupons WHERE code = ?", (code,))
        return await cursor.fetchone()


async def list_coupons():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM coupons ORDER BY created_at DESC")
        return await cursor.fetchall()


async def increment_coupon_usage(code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE coupons SET used_count = used_count + 1 WHERE code = ?", (code,))
        await db.commit()


async def toggle_coupon_active(code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE coupons SET active = 1 - active WHERE code = ?", (code,))
        await db.commit()


async def delete_coupon(code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM coupons WHERE code = ?", (code,))
        await db.commit()


# ---------- رفرال دائمی پورسانتی (کش‌بک نقدی به کیف پول) ----------
async def get_referral_commission_percent() -> int:
    val = await get_setting("referral_commission_percent")
    return int(val) if val is not None else 10


async def add_referral_commission(referrer_id: int, referred_id: int, order_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO referral_commissions (referrer_id, referred_id, order_id, amount, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (referrer_id, referred_id, order_id, amount, datetime.now().isoformat()),
        )
        await db.commit()


async def get_total_referral_earnings(referrer_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM referral_commissions WHERE referrer_id = ?", (referrer_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


# ---------- تخفیف پلکانی شارژ کیف پول ----------
async def get_wallet_bonus_threshold() -> int:
    val = await get_setting("wallet_bonus_threshold")
    return int(val) if val is not None else 500000


async def get_wallet_bonus_percent() -> int:
    val = await get_setting("wallet_bonus_percent")
    return int(val) if val is not None else 5


# ---------- تست رایگان (یک‌بار برای هر user_id) ----------
async def has_claimed_free_test(user_id: int) -> bool:
    """آیا این کاربر قبلاً تست رایگان گرفته (pending/delivered)؟"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM free_tests WHERE user_id = ? AND status IN ('pending', 'delivered')",
            (user_id,),
        )
        return await cursor.fetchone() is not None


async def create_free_test_request(user_id: int, username: str, full_name: str) -> bool:
    """ثبت درخواست تست رایگان. اگر قبلاً گرفته باشه False برمی‌گردونه."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status FROM free_tests WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row and row[0] in ("pending", "delivered"):
            return False
        # اگه rejected بوده یا اصلاً نبوده، upsert می‌کنیم
        await db.execute(
            """INSERT INTO free_tests (user_id, username, full_name, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username = excluded.username,
                   full_name = excluded.full_name,
                   status = 'pending',
                   panel_info = NULL,
                   created_at = excluded.created_at,
                   delivered_at = NULL""",
            (user_id, username, full_name, datetime.now().isoformat()),
        )
        await db.commit()
        return True


async def get_free_test(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM free_tests WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def set_free_test_status(user_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE free_tests SET status = ? WHERE user_id = ?", (status, user_id)
        )
        await db.commit()


async def deliver_free_test(user_id: int, panel_info: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE free_tests SET status = 'delivered', panel_info = ?, delivered_at = ?
               WHERE user_id = ?""",
            (panel_info, datetime.now().isoformat(), user_id),
        )
        await db.commit()


# ---------- گردونه شانس ----------
def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


async def count_wheel_spins_today(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM wheel_spins WHERE user_id = ? AND spin_date = ?",
            (user_id, _today_str()),
        )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def record_wheel_spin(user_id: int, prize_key: str, prize_label: str) -> None:
    now = datetime.now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO wheel_spins (user_id, prize_key, prize_label, created_at, spin_date)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, prize_key, prize_label, now.isoformat(), now.strftime("%Y-%m-%d")),
        )
        await db.commit()
