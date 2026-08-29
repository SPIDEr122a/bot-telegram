import asyncio
import logging
from time import monotonic

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

import config
import database as db

logging.basicConfig(level=logging.INFO)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

BOT_USERNAME = ""  # در main() پر میشه


# ---------- عضویت اجباری ----------
# وضعیت‌هایی که «عضو» حساب می‌شن
_MEMBER_OK = {"member", "administrator", "creator", "restricted"}


def _normalize_channel(ch: str):
    """آیدی عددی رو int و یوزرنیم رو با @ برمی‌گردونه."""
    s = (ch or "").strip()
    if not s:
        return s
    if s.lstrip("-").isdigit():
        return int(s)
    return s if s.startswith("@") else f"@{s}"


def _member_status_str(member) -> str:
    st = getattr(member, "status", None)
    if st is None:
        return ""
    return str(getattr(st, "value", st)).lower()


async def is_user_member(user_id: int) -> bool:
    """
    اگر REQUIRED_CHANNELS خالی باشه یا کاربر ادمین ربات باشه → True.
    وگرنه باید در همه کانال‌ها عضو (member/admin/creator/restricted) باشه.
    """
    if not config.REQUIRED_CHANNELS:
        return True
    # ادمین‌های ربات از چک عضویت معاف‌اند
    if user_id in config.ADMIN_IDS:
        return True

    for raw in config.REQUIRED_CHANNELS:
        chat_id = _normalize_channel(raw)
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            status = _member_status_str(member)
            logging.info(f"Membership: user={user_id} chat={chat_id} status={status}")
            if status not in _MEMBER_OK:
                return False
        except Exception as e:
            # رایج‌ترین علت: ربات ادمین کانال نیست / آیدی کانال اشتباه است
            logging.error(f"Membership check FAILED for chat={chat_id} user={user_id}: {e}")
            return False
    return True


async def build_join_kb() -> InlineKeyboardMarkup:
    """دکمه‌های جوین به کانال‌ها + دکمه بررسی عضویت."""
    rows = []
    for raw in config.REQUIRED_CHANNELS:
        chat_id = _normalize_channel(raw)
        url = None
        label = str(raw).lstrip("@")
        try:
            chat = await bot.get_chat(chat_id)
            title = getattr(chat, "title", None) or label
            if getattr(chat, "username", None):
                url = f"https://t.me/{chat.username}"
            else:
                # کانال خصوصی: سعی می‌کنیم لینک دعوت بگیریم (ربات باید ادمین با حق دعوت باشه)
                try:
                    inv = await bot.create_chat_invite_link(chat_id, name="bot-join")
                    url = inv.invite_link
                except Exception:
                    url = getattr(chat, "invite_link", None)
            label = title
        except Exception as e:
            logging.warning(f"Could not resolve channel {chat_id}: {e}")
            if isinstance(chat_id, str) and chat_id.startswith("@"):
                url = f"https://t.me/{chat_id.lstrip('@')}"
        if url:
            rows.append([InlineKeyboardButton(text=f"📢 عضویت در {label}", url=url)])
        else:
            rows.append(
                [InlineKeyboardButton(text=f"📢 عضویت در {label}", callback_data="join_info")]
            )
    rows.append([InlineKeyboardButton(text="✅ بررسی عضویت", callback_data="check_membership")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


JOIN_REQUIRED_TEXT = (
    "🔒 <b>عضویت اجباری</b>\n\n"
    "برای استفاده از ربات، ابتدا در کانال‌/گروه‌های زیر عضو شوید، "
    "سپس روی دکمه «✅ بررسی عضویت» بزنید.\n\n"
    "اگر عضو نشده باشید، امکان استفاده از ربات وجود ندارد."
)


# ---------- Rate limit / آنتی‌اسپم ----------
class ThrottlingMiddleware(BaseMiddleware):
    """جلوگیری از اسپم کردن دکمه‌ها یا ثبت پشت‌سرهم سفارش توسط یه کاربر."""

    def __init__(self, rate_limit: float = 0.6):
        self.rate_limit = rate_limit
        self.last_call: dict[int, float] = {}

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user is not None:
            now = monotonic()
            last = self.last_call.get(user.id)
            if last is not None and (now - last) < self.rate_limit:
                if isinstance(event, CallbackQuery):
                    await event.answer("⏳ لطفاً کمی آروم‌تر بزنید!", show_alert=False)
                return  # این درخواست به‌خاطر اسپم بودن نادیده گرفته میشه
            self.last_call[user.id] = now
        return await handler(event, data)


dp.message.outer_middleware(ThrottlingMiddleware(rate_limit=0.7))
dp.callback_query.outer_middleware(ThrottlingMiddleware(rate_limit=0.4))


# ---------- States ----------
class BuyStates(StatesGroup):
    waiting_for_receipt = State()
    entering_coupon_code = State()


class WalletStates(StatesGroup):
    entering_topup_amount = State()
    waiting_for_topup_receipt = State()


class AdminStates(StatesGroup):
    waiting_for_panel_info = State()
    waiting_for_reject_reason = State()
    waiting_for_freetest_info = State()
    editing_gaming_price = State()
    editing_multi_price = State()
    adding_gaming_volume = State()
    adding_gaming_price = State()
    adding_multi_label = State()
    adding_multi_price = State()
    editing_welcome_message = State()
    editing_referral_percent = State()
    editing_rules_text = State()
    adding_coupon_code = State()
    adding_coupon_percent = State()
    adding_coupon_maxuses = State()
    editing_wallet_bonus_threshold = State()
    editing_wallet_bonus_percent = State()


# ---------- Keyboards ----------
def main_menu_kb(user_id: int | None = None) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="🛍 خرید سرویس"), KeyboardButton(text="🖥 سرویس‌های من")],
        [KeyboardButton(text="🎁 تست رایگان"), KeyboardButton(text="💰 کیف پول")],
        [KeyboardButton(text="💬 پشتیبانی"), KeyboardButton(text="🤝 دعوت دوستان")],
        [KeyboardButton(text="📜 قوانین")],
    ]
    if user_id is not None and user_id in config.ADMIN_IDS:
        keyboard.append([KeyboardButton(text="🛠 مدیریت ربات")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")]]
    )


def services_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎮 سرویس گیمینگ", callback_data="svc:gaming")],
        [InlineKeyboardButton(text="🌍 سرویس مولتی لوکیشن (وبگردی)", callback_data="svc:multi")],
        [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def gaming_plans_kb(plans) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for p in plans:
        row.append(
            InlineKeyboardButton(text=f"{p['volume_gb']} گیگ - {p['price']:,} تومان", callback_data=f"gplan:{p['id']}")
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="back:services")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def multi_plans_kb(plans) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{p['label']} - {p['price']:,} تومان", callback_data=f"mplan:{p['id']}")]
        for p in plans
    ]
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="back:services")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_order_summary_kb(order) -> InlineKeyboardMarkup:
    """کیبورد صفحه خلاصه سفارش: ارسال رسید، کد تخفیف، پرداخت با کیف پول (در صورت کافی بودن موجودی) یا بازگشت."""
    kind = "gaming" if str(order["plan_name"]).startswith("🎮") else "multi"
    rows = [[InlineKeyboardButton(text="📤 ارسال رسید", callback_data=f"reqreceipt:{order['id']}")]]

    if order["coupon_code"]:
        rows.append(
            [
                InlineKeyboardButton(text="🔄 تغییر کد تخفیف", callback_data=f"applycoupon:{order['id']}"),
                InlineKeyboardButton(text="🗑 حذف تخفیف", callback_data=f"removecoupon:{order['id']}"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="🎟 اعمال کد تخفیف", callback_data=f"applycoupon:{order['id']}")])

    if order["price"] and order["price"] > 0:
        balance = await db.get_wallet_balance(order["user_id"])
        if balance >= order["price"]:
            rows.append(
                [InlineKeyboardButton(text=f"💰 پرداخت با کیف پول ({balance:,} تومان)", callback_data=f"walletpay:{order['id']}")]
            )

    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"cancelorder:{order['id']}:{kind}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def waiting_receipt_kb(order_id: int) -> InlineKeyboardMarkup:
    """کیبورد صفحه‌ی در انتظار دریافت رسید: فقط بازگشت به خلاصه سفارش."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"backsummary:{order_id}")]]
    )


def order_summary_text(order) -> str:
    price_block = f"💰 قیمت: {order['price']:,} تومان"
    if order["coupon_code"]:
        price_block = (
            f"💵 قیمت اصلی: {order['original_price']:,} تومان\n"
            f"🎟 کد تخفیف: {order['coupon_code']}\n"
            f"💰 قیمت نهایی: {order['price']:,} تومان"
        )
    return (
        f"🧾 <b>خلاصه سفارش شما</b>\n"
        f"—————————————\n"
        f"📦 {order['plan_name']}\n"
        f"{price_block}\n"
        f"—————————————\n\n"
        f"💳 شماره کارت: <code>{config.CARD_NUMBER}</code>\n"
        f"👤 به نام: {config.CARD_HOLDER}\n\n"
        f"ℹ️ پس از واریز وجه، روی دکمه «📤 ارسال رسید» بزنید و سپس عکس یا فایل رسید رو ارسال کنید."
    )


def admin_decision_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید", callback_data=f"approve:{order_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{order_id}"),
            ]
        ]
    )


# ---------- User handlers ----------
@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    # پردازش لینک دعوت (رفرال) در صورت وجود
    args = command.args
    if args and args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
        except ValueError:
            referrer_id = None

        if referrer_id and referrer_id != message.from_user.id:
            existing = await db.get_referral_by_referred(message.from_user.id)
            if not existing:
                added = await db.add_referral(referrer_id, message.from_user.id, message.from_user.username or "")
                if added:
                    try:
                        await bot.send_message(referrer_id, "🎉 یک نفر با لینک دعوت شما وارد ربات شد!")
                    except Exception as e:
                        logging.warning(f"Could not notify referrer {referrer_id}: {e}")

    # عضویت اجباری: اگر عضو نباشه فقط صفحه جوین نشون داده میشه
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(
            JOIN_REQUIRED_TEXT,
            parse_mode="HTML",
            reply_markup=await build_join_kb(),
        )
        return

    custom_welcome = await db.get_welcome_message()
    if custom_welcome:
        text = custom_welcome
    else:
        text = (
            f"✨ <b>{config.BRAND_NAME}</b> ✨\n\n"
            f"👋 به پلتفرم فروش سرویس {config.BRAND_NAME} خوش اومدید\n\n"
            f"🎁 <b>چی دریافت می‌کنید؟</b>\n"
            f"🎮 سرویس گیمینگ با حجم دلخواه\n"
            f"🌍 سرویس مولتی لوکیشن (وبگردی) با پلن نامحدود\n\n"
            f"🟢 سرویس فعال دارید؟ از دکمه «🖥 سرویس‌های من» وارد شوید"
        )
    await message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb(message.from_user.id))


@dp.callback_query(F.data == "check_membership")
async def check_membership_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not config.REQUIRED_CHANNELS:
        await callback.answer("عضویت اجباری فعال نیست.", show_alert=True)
        return

    # ادمین همیشه عبور می‌کنه
    if callback.from_user.id in config.ADMIN_IDS or await is_user_member(callback.from_user.id):
        try:
            await callback.message.edit_text("✅ عضویت شما تأیید شد! می‌تونید از ربات استفاده کنید.")
        except Exception:
            pass
        custom_welcome = await db.get_welcome_message()
        if custom_welcome:
            text = custom_welcome
        else:
            text = (
                f"✨ <b>{config.BRAND_NAME}</b> ✨\n\n"
                f"👋 به پلتفرم فروش سرویس {config.BRAND_NAME} خوش اومدید"
            )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=main_menu_kb(callback.from_user.id))
        await callback.answer("عضویت تأیید شد ✅")
        return

    # لاگ فنی فقط در سرور؛ به کاربر پیام ساده نشون می‌دیم
    for raw in config.REQUIRED_CHANNELS:
        chat_id = _normalize_channel(raw)
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
            status = _member_status_str(member)
            if status not in _MEMBER_OK:
                logging.info(f"User {callback.from_user.id} not member of {chat_id}: {status}")
        except Exception as e:
            logging.error(f"check_membership error chat={chat_id}: {e}")

    await callback.answer("❌ عضویت تأیید نشد. لطفاً اول عضو شوید.", show_alert=True)


@dp.callback_query(F.data == "join_info")
async def join_info_handler(callback: CallbackQuery):
    await callback.answer(
        "لینک عمومی این کانال در دسترس نیست. از طریق جست‌وجو در تلگرام عضو شوید یا با پشتیبانی در ارتباط باشید.",
        show_alert=True,
    )


@dp.message(F.text == "🛍 خرید سرویس")
async def show_services(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    await message.answer("🛍 لطفاً نوع سرویس مورد نظر رو انتخاب کنید:", reply_markup=services_kb())


@dp.callback_query(F.data == "back:menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "↩️ به منوی اصلی برگشتید.\nبرای شروع دوباره از دکمه «🛍 خرید سرویس» در پایین صفحه استفاده کنید."
    )
    await callback.answer()


@dp.callback_query(F.data == "back:services")
async def back_to_services(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🛍 لطفاً نوع سرویس مورد نظر رو انتخاب کنید:", reply_markup=services_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith("cancelorder:"))
async def cancel_order_and_go_back(callback: CallbackQuery, state: FSMContext):
    """کاربر از صفحه خلاصه سفارش «بازگشت» رو زده -> سفارش لغو میشه و به لیست تعرفه‌های همون سرویس برمی‌گرده."""
    _, order_id_str, kind = callback.data.split(":")
    order_id = int(order_id_str)
    order = await db.get_order(order_id)
    if order and order["user_id"] == callback.from_user.id and order["status"] in ("awaiting_receipt", "pending"):
        await db.set_order_status(order_id, "cancelled")
    await state.clear()

    if kind == "gaming":
        plans = await db.get_gaming_plans()
        if not plans:
            await callback.answer("در حال حاضر تعرفه‌ای برای این سرویس ثبت نشده.", show_alert=True)
            return
        await callback.message.edit_text(
            "🎮 <b>سرویس گیمینگ</b>\nحجم مورد نظر رو انتخاب کنید:", parse_mode="HTML", reply_markup=gaming_plans_kb(plans)
        )
    else:
        plans = await db.get_multi_plans()
        if not plans:
            await callback.answer("در حال حاضر تعرفه‌ای برای این سرویس ثبت نشده.", show_alert=True)
            return
        await callback.message.edit_text(
            "🌍 <b>سرویس مولتی لوکیشن (وبگردی)</b>\nتعرفه مورد نظر رو انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=multi_plans_kb(plans),
        )
    await callback.answer()


@dp.callback_query(F.data == "svc:gaming")
async def choose_gaming_service(callback: CallbackQuery, state: FSMContext):
    plans = await db.get_gaming_plans()
    if not plans:
        await callback.answer("در حال حاضر تعرفه‌ای برای این سرویس ثبت نشده.", show_alert=True)
        return
    await callback.message.edit_text(
        "🎮 <b>سرویس گیمینگ</b>\nحجم مورد نظر رو انتخاب کنید:", parse_mode="HTML", reply_markup=gaming_plans_kb(plans)
    )
    await callback.answer()


@dp.callback_query(F.data == "svc:multi")
async def choose_multi_service(callback: CallbackQuery, state: FSMContext):
    plans = await db.get_multi_plans()
    if not plans:
        await callback.answer("در حال حاضر تعرفه‌ای برای این سرویس ثبت نشده.", show_alert=True)
        return
    await callback.message.edit_text(
        "🌍 <b>سرویس مولتی لوکیشن (وبگردی)</b>\nتعرفه مورد نظر رو انتخاب کنید:",
        parse_mode="HTML",
        reply_markup=multi_plans_kb(plans),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("gplan:"))
async def choose_gaming_plan(callback: CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split(":")[1])
    plan = await db.get_gaming_plan(plan_id)
    if not plan or not plan["active"]:
        await callback.answer("این تعرفه دیگر موجود نیست.", show_alert=True)
        return

    plan_name = f"🎮 سرویس گیمینگ - {plan['volume_gb']} گیگ"

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "",
        full_name=callback.from_user.full_name,
        plan_id=plan_id,
        plan_name=plan_name,
        price=plan["price"],
    )

    await state.clear()
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        order_summary_text(order), parse_mode="HTML", reply_markup=await build_order_summary_kb(order)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("mplan:"))
async def choose_multi_plan(callback: CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split(":")[1])
    plan = await db.get_multi_plan(plan_id)
    if not plan or not plan["active"]:
        await callback.answer("این تعرفه دیگر موجود نیست.", show_alert=True)
        return

    plan_name = f"🌍 سرویس مولتی لوکیشن - {plan['label']}"

    order_id = await db.create_order(
        user_id=callback.from_user.id,
        username=callback.from_user.username or "",
        full_name=callback.from_user.full_name,
        plan_id=plan_id,
        plan_name=plan_name,
        price=plan["price"],
    )

    await state.clear()
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        order_summary_text(order), parse_mode="HTML", reply_markup=await build_order_summary_kb(order)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("reqreceipt:"))
async def request_receipt(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return
    if order["status"] not in ("awaiting_receipt", "pending"):
        await callback.answer("این سفارش دیگه در وضعیت ارسال رسید نیست.", show_alert=True)
        return

    await state.update_data(order_id=order_id)
    await state.set_state(BuyStates.waiting_for_receipt)

    await callback.message.edit_text(
        "📸 لطفاً عکس یا فایل رسید پرداخت رو همینجا ارسال کنید.",
        reply_markup=waiting_receipt_kb(order_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("backsummary:"))
async def back_to_order_summary(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        order_summary_text(order), parse_mode="HTML", reply_markup=await build_order_summary_kb(order)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("applycoupon:"))
async def start_apply_coupon(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return
    if order["status"] not in ("awaiting_receipt", "pending"):
        await callback.answer("این سفارش دیگه قابل ویرایش نیست.", show_alert=True)
        return

    await state.update_data(order_id=order_id)
    await state.set_state(BuyStates.entering_coupon_code)
    await callback.message.edit_text(
        "🎟 کد تخفیف رو وارد کنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"backsummary:{order_id}")]]
        ),
    )
    await callback.answer()


@dp.message(BuyStates.entering_coupon_code)
async def apply_coupon_code(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    order = await db.get_order(order_id) if order_id else None
    if not order:
        await message.answer("مشکلی پیش اومد، لطفاً دوباره از منو پلن رو انتخاب کنید.")
        await state.clear()
        return

    code = (message.text or "").strip().upper()
    coupon = await db.get_coupon(code)

    if not coupon or not coupon["active"]:
        await message.answer("❌ این کد تخفیف معتبر نیست. یه کد دیگه امتحان کنید یا از دکمه بازگشت استفاده کنید.")
        return
    if coupon["max_uses"] is not None and coupon["used_count"] >= coupon["max_uses"]:
        await message.answer("❌ ظرفیت استفاده از این کد تخفیف تموم شده. یه کد دیگه امتحان کنید.")
        return

    new_price = int(order["original_price"] * (100 - coupon["percent"]) / 100)
    await db.apply_coupon_to_order(order_id, code, new_price)
    await db.increment_coupon_usage(code)
    await state.clear()

    order = await db.get_order(order_id)
    await message.answer(
        f"✅ کد تخفیف {code} ({coupon['percent']}٪) با موفقیت اعمال شد!",
    )
    await message.answer(
        order_summary_text(order), parse_mode="HTML", reply_markup=await build_order_summary_kb(order)
    )


@dp.callback_query(F.data.startswith("removecoupon:"))
async def remove_coupon(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return

    await db.remove_coupon_from_order(order_id)
    await state.clear()
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        order_summary_text(order), parse_mode="HTML", reply_markup=await build_order_summary_kb(order)
    )
    await callback.answer("کد تخفیف حذف شد.")


@dp.callback_query(F.data.startswith("walletpay:"))
async def pay_with_wallet(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return
    if order["status"] not in ("awaiting_receipt", "pending"):
        await callback.answer("این سفارش دیگه قابل پرداخت نیست.", show_alert=True)
        return

    ok = await db.deduct_wallet_balance(order["user_id"], order["price"])
    if not ok:
        await callback.answer("موجودی کیف پول شما کافی نیست.", show_alert=True)
        return

    await db.mark_order_paid_by_wallet(order_id)
    await state.clear()

    await callback.message.edit_text(
        "✅ پرداخت با موفقیت از کیف پول انجام شد.\nسفارش شما برای بررسی و تحویل به ادمین ارسال شد.",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()

    caption = (
        f"🆕 سفارش جدید #{order_id} (💰 پرداخت با کیف پول)\n"
        f"👤 کاربر: {order['full_name']} (@{order['username'] or '-'})\n"
        f"🆔 آیدی عددی: {order['user_id']}\n"
        f"📦 پلن: {order['plan_name']}\n"
        f"💰 مبلغ: {order['price']:,} تومان"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, caption, reply_markup=admin_decision_kb(order_id))
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id}: {e}")


@dp.message(BuyStates.waiting_for_receipt, F.photo | F.document)
async def receive_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await message.answer("مشکلی پیش اومد، لطفاً دوباره از منو پلن رو انتخاب کنید.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    await db.attach_receipt(order_id, file_id)
    order = await db.get_order(order_id)

    await message.answer(
        "🕐 رسید شما دریافت شد و برای بررسی به ادمین ارسال شد. "
        "به محض تأیید، اطلاعات سرویس ارسال میشه.",
        reply_markup=main_menu_kb(message.from_user.id),
    )
    await state.clear()

    caption = (
        f"🆕 سفارش جدید #{order_id}\n"
        f"👤 کاربر: {order['full_name']} (@{order['username'] or '-'})\n"
        f"🆔 آیدی عددی: {order['user_id']}\n"
        f"📦 پلن: {order['plan_name']}\n"
        f"💰 مبلغ: {order['price']:,} تومان"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            if message.photo:
                await bot.send_photo(
                    admin_id, photo=file_id, caption=caption,
                    reply_markup=admin_decision_kb(order_id),
                )
            else:
                await bot.send_document(
                    admin_id, document=file_id, caption=caption,
                    reply_markup=admin_decision_kb(order_id),
                )
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id}: {e}")


@dp.message(BuyStates.waiting_for_receipt)
async def waiting_receipt_wrong_input(message: Message):
    await message.answer("لطفاً عکس یا فایل رسید پرداخت رو ارسال کنید 📸")


ORDER_STATUS_MAP = {
    "awaiting_receipt": "⏳ در انتظار ارسال رسید",
    "pending": "🕐 در حال بررسی",
    "approved": "✅ تأیید شده",
    "rejected": "❌ رد شده",
    "delivered": "📦 تحویل داده شده",
    "cancelled": "🚫 لغو شده",
}

ORDER_STATUS_ICON = {
    "awaiting_receipt": "⏳",
    "pending": "🕐",
    "approved": "✅",
    "rejected": "❌",
    "delivered": "📦",
    "cancelled": "🚫",
}


def my_orders_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for o in orders:
        icon = ORDER_STATUS_ICON.get(o["status"], "•")
        rows.append(
            [InlineKeyboardButton(text=f"{icon} #{o['id']} - {o['plan_name']}", callback_data=f"vieworder:{o['id']}")]
        )
    rows.append([InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_detail_text(order) -> str:
    text = (
        f"🆔 <b>سفارش #{order['id']}</b>\n"
        f"—————————————\n"
        f"📦 پلن: {order['plan_name']}\n"
        f"💰 مبلغ: {order['price']:,} تومان\n"
        f"📌 وضعیت: {ORDER_STATUS_MAP.get(order['status'], order['status'])}"
    )
    if order["status"] == "delivered" and order["panel_info"]:
        text += f"\n\n🔑 اطلاعات و کانفیگ سرویس:\n{order['panel_info']}"
    return text


@dp.message(F.text == "🖥 سرویس‌های من")
async def my_orders(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    orders = await db.get_user_orders(message.from_user.id)
    if not orders:
        await message.answer("شما هنوز هیچ سفارشی ثبت نکردید.", reply_markup=back_menu_kb())
        return

    await message.answer(
        "🖥 <b>سرویس‌های من</b>\nبرای مشاهده اطلاعات و کانفیگ هر سفارش، روی اون کلیک کنید:",
        parse_mode="HTML",
        reply_markup=my_orders_kb(orders),
    )


@dp.callback_query(F.data.startswith("vieworder:"))
async def view_order_detail(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("این سفارش پیدا نشد.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به لیست سرویس‌ها", callback_data="myorders:list")]]
    )
    await callback.message.edit_text(order_detail_text(order), parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "myorders:list")
async def back_to_my_orders_list(callback: CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id)
    if not orders:
        await callback.message.edit_text("شما هنوز هیچ سفارشی ثبت نکردید.")
        await callback.answer()
        return
    await callback.message.edit_text(
        "🖥 <b>سرویس‌های من</b>\nبرای مشاهده اطلاعات و کانفیگ هر سفارش، روی اون کلیک کنید:",
        parse_mode="HTML",
        reply_markup=my_orders_kb(orders),
    )
    await callback.answer()


def topup_summary_text(topup) -> str:
    return (
        f"🧾 <b>شارژ کیف پول</b>\n"
        f"—————————————\n"
        f"💰 مبلغ: {topup['amount']:,} تومان\n"
        f"—————————————\n\n"
        f"💳 شماره کارت: <code>{config.CARD_NUMBER}</code>\n"
        f"👤 به نام: {config.CARD_HOLDER}\n\n"
        f"ℹ️ پس از واریز وجه، روی دکمه «📤 ارسال رسید» بزنید و سپس عکس یا فایل رسید رو ارسال کنید."
    )


def topup_summary_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 ارسال رسید", callback_data=f"topupreq:{topup_id}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"topupcancel:{topup_id}")],
        ]
    )


def topup_waiting_receipt_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"topupback:{topup_id}")]]
    )


def topup_decision_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید و شارژ", callback_data=f"wapprove:{topup_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"wreject:{topup_id}"),
            ]
        ]
    )


def free_test_admin_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تحویل تست", callback_data=f"ftapprove:{user_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"ftreject:{user_id}"),
            ]
        ]
    )


@dp.message(F.text == "🎁 تست رایگان")
async def free_test_handler(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return

    user_id = message.from_user.id
    if await db.has_claimed_free_test(user_id):
        existing = await db.get_free_test(user_id)
        status = existing["status"] if existing else "?"
        if status == "pending":
            await message.answer(
                "⏳ درخواست تست رایگان شما قبلاً ثبت شده و در صف بررسی ادمینه.\n"
                "لطفاً صبور باشید.",
                reply_markup=main_menu_kb(user_id),
            )
        else:
            await message.answer(
                "❌ شما قبلاً از تست رایگان استفاده کردید.\n"
                "هر آیدی فقط یک‌بار می‌تونه تست رایگان بگیره.",
                reply_markup=main_menu_kb(user_id),
            )
        return

    ok = await db.create_free_test_request(
        user_id,
        message.from_user.username or "",
        message.from_user.full_name,
    )
    if not ok:
        await message.answer(
            "❌ شما قبلاً از تست رایگان استفاده کردید.",
            reply_markup=main_menu_kb(user_id),
        )
        return

    await message.answer(
        "✅ درخواست تست رایگان شما ثبت شد.\n"
        "به‌محض بررسی توسط ادمین، اطلاعات تست براتون ارسال می‌شه.",
        reply_markup=main_menu_kb(user_id),
    )

    caption = (
        f"🎁 درخواست تست رایگان\n"
        f"👤 کاربر: {message.from_user.full_name} (@{message.from_user.username or '-'})\n"
        f"🆔 آیدی عددی: <code>{user_id}</code>"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                caption,
                parse_mode="HTML",
                reply_markup=free_test_admin_kb(user_id),
            )
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id} about free test: {e}")


@dp.callback_query(F.data.startswith("ftapprove:"))
async def admin_approve_free_test(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    ft = await db.get_free_test(user_id)
    if not ft:
        await callback.answer("درخواست پیدا نشد.", show_alert=True)
        return
    if ft["status"] == "delivered":
        await callback.answer("این تست قبلاً تحویل داده شده.", show_alert=True)
        return

    await state.update_data(freetest_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_freetest_info)
    await callback.message.answer(
        f"✅ درخواست تست کاربر <code>{user_id}</code> تأیید شد.\n"
        f"حالا اطلاعات/کانفیگ تست رایگان رو برای ارسال به کاربر بفرستید:",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_freetest_info)
async def admin_send_free_test_info(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("freetest_user_id")
    if not user_id:
        await message.answer("مشکلی پیش اومد.")
        await state.clear()
        return

    panel_info = message.text or message.caption or ""
    await db.deliver_free_test(user_id, panel_info)
    await state.clear()

    try:
        await bot.send_message(
            user_id,
            f"🎉 تست رایگان شما آماده شد!\n\n"
            f"🔑 اطلاعات تست:\n{panel_info}",
        )
        await message.answer(f"✅ اطلاعات تست با موفقیت برای کاربر {user_id} ارسال شد.")
    except Exception as e:
        await message.answer(f"⚠️ ارسال به کاربر ناموفق بود: {e}")


@dp.callback_query(F.data.startswith("ftreject:"))
async def admin_reject_free_test(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    ft = await db.get_free_test(user_id)
    if not ft:
        await callback.answer("درخواست پیدا نشد.", show_alert=True)
        return

    await db.set_free_test_status(user_id, "rejected")
    try:
        await bot.send_message(
            user_id,
            "❌ متأسفانه درخواست تست رایگان شما رد شد.\n"
            "در صورت سؤال با پشتیبانی در ارتباط باشید.",
        )
    except Exception as e:
        logging.warning(f"Could not notify user about free test reject: {e}")

    await callback.message.answer(f"❌ تست رایگان کاربر {user_id} رد شد.")
    await callback.answer()


@dp.message(F.text == "💰 کیف پول")
async def wallet_handler(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    balance = await db.get_wallet_balance(message.from_user.id)
    threshold = await db.get_wallet_bonus_threshold()
    bonus_percent = await db.get_wallet_bonus_percent()
    text = (
        f"💰 <b>کیف پول شما</b>\n\n"
        f"موجودی فعلی: <b>{balance:,} تومان</b>\n\n"
        f"می‌تونید کیف پولتون رو شارژ کنید و در خریدهای بعدی بدون نیاز به ارسال رسید، از همون پرداخت کنید.\n\n"
        f"🎁 شارژهای <b>{threshold:,} تومان</b> به بالا، <b>{bonus_percent}٪ هدیه اضافه</b> می‌گیرن!"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ شارژ کیف پول", callback_data="topupwallet")],
            [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")],
        ]
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "topupwallet")
async def start_topup(callback: CallbackQuery, state: FSMContext):
    threshold = await db.get_wallet_bonus_threshold()
    bonus_percent = await db.get_wallet_bonus_percent()
    await state.set_state(WalletStates.entering_topup_amount)
    await callback.message.edit_text(
        f"💳 مبلغ مورد نظر برای شارژ کیف پول رو به تومان وارد کنید (فقط عدد، مثال: 200000):\n\n"
        f"🎁 نکته: شارژ {threshold:,} تومان به بالا، {bonus_percent}٪ هدیه اضافه می‌گیره!",
        reply_markup=back_menu_kb(),
    )
    await callback.answer()


@dp.message(WalletStates.entering_topup_amount)
async def receive_topup_amount(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("لطفاً فقط عدد بزرگ‌تر از صفر بفرستید (مثال: 200000)")
        return

    amount = int(text)
    topup_id = await db.create_wallet_topup(
        message.from_user.id, message.from_user.username or "", message.from_user.full_name, amount
    )
    await state.clear()
    topup = await db.get_wallet_topup(topup_id)
    await message.answer(topup_summary_text(topup), parse_mode="HTML", reply_markup=topup_summary_kb(topup_id))


@dp.callback_query(F.data.startswith("topupcancel:"))
async def cancel_topup(callback: CallbackQuery, state: FSMContext):
    topup_id = int(callback.data.split(":")[1])
    topup = await db.get_wallet_topup(topup_id)
    if topup and topup["user_id"] == callback.from_user.id and topup["status"] in ("awaiting_receipt", "pending"):
        await db.set_topup_status(topup_id, "cancelled")
    await state.clear()
    await callback.message.edit_text("🚫 درخواست شارژ کیف پول لغو شد.", reply_markup=back_menu_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith("topupreq:"))
async def request_topup_receipt(callback: CallbackQuery, state: FSMContext):
    topup_id = int(callback.data.split(":")[1])
    topup = await db.get_wallet_topup(topup_id)
    if not topup or topup["user_id"] != callback.from_user.id:
        await callback.answer("این درخواست پیدا نشد.", show_alert=True)
        return
    if topup["status"] not in ("awaiting_receipt", "pending"):
        await callback.answer("این درخواست دیگه در وضعیت ارسال رسید نیست.", show_alert=True)
        return

    await state.update_data(topup_id=topup_id)
    await state.set_state(WalletStates.waiting_for_topup_receipt)
    await callback.message.edit_text(
        "📸 لطفاً عکس یا فایل رسید واریزی رو همینجا ارسال کنید.",
        reply_markup=topup_waiting_receipt_kb(topup_id),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("topupback:"))
async def back_to_topup_summary(callback: CallbackQuery, state: FSMContext):
    topup_id = int(callback.data.split(":")[1])
    topup = await db.get_wallet_topup(topup_id)
    if not topup or topup["user_id"] != callback.from_user.id:
        await callback.answer("این درخواست پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        topup_summary_text(topup), parse_mode="HTML", reply_markup=topup_summary_kb(topup_id)
    )
    await callback.answer()


@dp.message(WalletStates.waiting_for_topup_receipt, F.photo | F.document)
async def receive_topup_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    topup_id = data.get("topup_id")
    if not topup_id:
        await message.answer("مشکلی پیش اومد، لطفاً دوباره از «💰 کیف پول» شروع کنید.")
        await state.clear()
        return

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    await db.attach_topup_receipt(topup_id, file_id)
    topup = await db.get_wallet_topup(topup_id)

    await message.answer(
        "🕐 رسید شما دریافت شد و برای بررسی به ادمین ارسال شد. "
        "به محض تأیید، کیف پولتون شارژ میشه.",
        reply_markup=main_menu_kb(message.from_user.id),
    )
    await state.clear()

    caption = (
        f"💰 درخواست شارژ کیف پول #{topup_id}\n"
        f"👤 کاربر: {topup['full_name']} (@{topup['username'] or '-'})\n"
        f"🆔 آیدی عددی: {topup['user_id']}\n"
        f"💵 مبلغ: {topup['amount']:,} تومان"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            if message.photo:
                await bot.send_photo(
                    admin_id, photo=file_id, caption=caption, reply_markup=topup_decision_kb(topup_id)
                )
            else:
                await bot.send_document(
                    admin_id, document=file_id, caption=caption, reply_markup=topup_decision_kb(topup_id)
                )
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id}: {e}")


@dp.message(WalletStates.waiting_for_topup_receipt)
async def waiting_topup_receipt_wrong_input(message: Message):
    await message.answer("لطفاً عکس یا فایل رسید واریزی رو ارسال کنید 📸")


@dp.callback_query(F.data.startswith("wapprove:"))
async def admin_approve_topup(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return

    topup_id = int(callback.data.split(":")[1])
    topup = await db.get_wallet_topup(topup_id)
    if not topup:
        await callback.answer("این درخواست پیدا نشد.", show_alert=True)
        return
    if topup["status"] == "approved":
        await callback.answer("این درخواست قبلاً تأیید شده.", show_alert=True)
        return

    await db.set_topup_status(topup_id, "approved")

    threshold = await db.get_wallet_bonus_threshold()
    bonus_percent = await db.get_wallet_bonus_percent()
    bonus = 0
    if threshold > 0 and bonus_percent > 0 and topup["amount"] >= threshold:
        bonus = int(topup["amount"] * bonus_percent / 100)

    credit_amount = topup["amount"] + bonus
    await db.add_wallet_balance(topup["user_id"], credit_amount)
    new_balance = await db.get_wallet_balance(topup["user_id"])

    bonus_note = f"\n🎁 چون شارژتون {threshold:,} تومان یا بیشتر بود، {bonus:,} تومان هدیه هم گرفتید!" if bonus > 0 else ""

    try:
        await bot.send_message(
            topup["user_id"],
            f"✅ کیف پول شما به مبلغ {topup['amount']:,} تومان شارژ شد.{bonus_note}\n"
            f"💰 موجودی جدید: {new_balance:,} تومان",
        )
    except Exception as e:
        logging.warning(f"Could not notify user about wallet charge: {e}")

    await callback.message.answer(
        f"✅ شارژ کیف پول #{topup_id} تأیید شد و کیف پول کاربر شارژ شد."
        + (f" (شامل {bonus:,} تومان هدیه پلکانی)" if bonus > 0 else "")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("wreject:"))
async def admin_reject_topup(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return

    topup_id = int(callback.data.split(":")[1])
    topup = await db.get_wallet_topup(topup_id)
    if not topup:
        await callback.answer("این درخواست پیدا نشد.", show_alert=True)
        return

    await db.set_topup_status(topup_id, "rejected")

    try:
        await bot.send_message(
            topup["user_id"],
            f"❌ متأسفانه درخواست شارژ کیف پول شما رد شد.\n"
            f"در صورت وجود اشتباه در واریزی، لطفاً با پشتیبانی در ارتباط باشید.",
        )
    except Exception as e:
        logging.warning(f"Could not notify user: {e}")

    await callback.message.answer(f"❌ شارژ کیف پول #{topup_id} رد شد و به کاربر اطلاع داده شد.")
    await callback.answer()


@dp.message(F.text == "💬 پشتیبانی")
async def support_handler(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📞 ارتباط با پشتیبانی", url=f"https://t.me/{config.SUPPORT_USERNAME}")],
            [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")],
        ]
    )
    await message.answer("💬 برای ارتباط با پشتیبانی روی دکمه زیر بزنید:", reply_markup=kb)


DEFAULT_RULES_TEXT = (
    "📜 <b>قوانین و مقررات استفاده از ربات</b>\n\n"
    "۱️⃣ خرید سرویس از این ربات به معنی پذیرش کامل این قوانینه.\n"
    "۲️⃣ اطلاعات سرویس (کانفیگ/یوزرنیم/پسورد) فقط برای استفاده شخصی شماست؛ اشتراک‌گذاری یا فروش مجدد اون بدون هماهنگی با پشتیبانی مجاز نیست.\n"
    "۳️⃣ بعد از ارسال رسید یا پرداخت با کیف پول، سفارش شما در سریع‌ترین زمان ممکن توسط ادمین بررسی و تحویل داده میشه.\n"
    "۴️⃣ در صورت واریز اشتباه یا مغایرت مبلغ، سفارش ممکنه رد بشه؛ لطفاً از طریق پشتیبانی پیگیری کنید.\n"
    "۵️⃣ وجه واریزی برای سرویس‌های تحویل‌داده‌شده قابل استرداد نیست، مگر در صورت وجود مشکل فنی از سمت ما.\n"
    "۶️⃣ موجودی کیف پول فقط داخل همین ربات و برای خرید سرویس قابل استفاده است و قابل برداشت نقدی نیست.\n"
    "۷️⃣ استفاده از سرویس‌ها برای فعالیت‌های غیرقانونی یا مخرب (هک، اسپم، آزار دیگران و ...) ممنوعه و در صورت مشاهده، سرویس بدون اطلاع قبلی مسدود میشه.\n"
    "۸️⃣ قیمت‌ها و تعرفه‌ها ممکنه بدون اطلاع قبلی تغییر کنن؛ قیمت لحظه ثبت سفارش ملاک نهایی است.\n"
    "۹️⃣ برای هرگونه سؤال یا مشکل، از بخش «💬 پشتیبانی» با ما در ارتباط باشید.\n\n"
    "با تشکر از اعتماد شما 🙏"
)


@dp.message(F.text == "📜 قوانین")
async def rules_handler(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    custom_rules = await db.get_rules_text()
    text = custom_rules if custom_rules else DEFAULT_RULES_TEXT
    await message.answer(text, parse_mode="HTML", reply_markup=back_menu_kb())


@dp.message(F.text == "🤝 دعوت دوستان")
async def invite_handler(message: Message, state: FSMContext):
    await state.clear()
    if config.REQUIRED_CHANNELS and not await is_user_member(message.from_user.id):
        await message.answer(JOIN_REQUIRED_TEXT, parse_mode="HTML", reply_markup=await build_join_kb())
        return
    referrer_id = message.from_user.id
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{referrer_id}"
    total = await db.count_referrals(referrer_id)
    converted = await db.count_converted_referrals(referrer_id)
    commission_percent = await db.get_referral_commission_percent()
    total_earned = await db.get_total_referral_earnings(referrer_id)

    text = (
        f"🤝 <b>دعوت دوستان</b>\n\n"
        f"لینک اختصاصی شما:\n<code>{link}</code>\n\n"
        f"👥 تعداد افراد دعوت‌شده: {total}\n"
        f"✅ تعداد خریدهای موفق زیرمجموعه: {converted}\n"
        f"💰 مجموع پورسانتی دریافتی تا الان: <b>{total_earned:,} تومان</b>\n\n"
        f"🎁 به‌ازای <b>هر</b> خرید موفق دوستانی که با لینک شما وارد بشن، <b>{commission_percent}٪</b> از "
        f"مبلغ خریدشون بلافاصله و به‌صورت نقدی به کیف پول شما اضافه میشه — برای همیشه و بدون محدودیت تعداد دفعات! 💸"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=back_menu_kb())


# ---------- Admin: management panel ----------
def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 تعرفه‌های گیمینگ", callback_data="admintariff:gaming")],
            [InlineKeyboardButton(text="🌍 تعرفه‌های مولتی لوکیشن", callback_data="admintariff:multi")],
            [InlineKeyboardButton(text="✉️ پیام خوش‌آمدگویی", callback_data="adminwelcome")],
            [InlineKeyboardButton(text="📜 ویرایش قوانین", callback_data="adminrules")],
            [InlineKeyboardButton(text="🎟 کدهای تخفیف", callback_data="admincoupons")],
            [InlineKeyboardButton(text="🤝 تنظیمات رفرال", callback_data="adminreferral")],
            [InlineKeyboardButton(text="💳 تخفیف شارژ کیف پول", callback_data="adminwalletbonus")],
            [InlineKeyboardButton(text="🔙 بازگشت به منو", callback_data="back:menu")],
        ]
    )


async def gaming_admin_list_kb() -> InlineKeyboardMarkup:
    plans = await db.get_gaming_plans(active_only=False)
    rows = []
    for p in plans:
        status = "✅" if p["active"] else "🚫"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {p['volume_gb']} گیگ - {p['price']:,} تومان",
                    callback_data=f"gpriceedit:{p['id']}",
                ),
                InlineKeyboardButton(
                    text="غیرفعال" if p["active"] else "فعال",
                    callback_data=f"gtoggle:{p['id']}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ افزودن تعرفه جدید", callback_data="gadd")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def multi_admin_list_kb() -> InlineKeyboardMarkup:
    plans = await db.get_multi_plans(active_only=False)
    rows = []
    for p in plans:
        status = "✅" if p["active"] else "🚫"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {p['label']} - {p['price']:,} تومان",
                    callback_data=f"mpriceedit:{p['id']}",
                ),
                InlineKeyboardButton(
                    text="غیرفعال" if p["active"] else "فعال",
                    callback_data=f"mtoggle:{p['id']}",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ افزودن تعرفه جدید", callback_data="madd")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


ADMIN_ROOT_TEXT = "⚙️ <b>مدیریت ربات</b>\nچی رو می‌خواید تنظیم کنید؟"


@dp.message(Command("admin"))
@dp.message(F.text == "🛠 مدیریت ربات")
async def admin_panel_entry(message: Message, state: FSMContext):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    await state.clear()
    await message.answer(ADMIN_ROOT_TEXT, parse_mode="HTML", reply_markup=admin_menu_kb())


@dp.callback_query(F.data == "admintariff:root")
async def admintariff_root(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(ADMIN_ROOT_TEXT, parse_mode="HTML", reply_markup=admin_menu_kb())
    await callback.answer()


back_to_admin_root_kb = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")]]
)


@dp.callback_query(F.data == "adminwelcome")
async def admin_edit_welcome(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    current = await db.get_welcome_message()
    current_display = current if current else (
        f"(پیش‌فرض) ✨ {config.BRAND_NAME} ✨\n👋 به پلتفرم فروش سرویس {config.BRAND_NAME} خوش اومدید ..."
    )
    await state.set_state(AdminStates.editing_welcome_message)
    await callback.message.edit_text(
        f"✉️ <b>پیام خوش‌آمدگویی فعلی:</b>\n\n{current_display}\n\n"
        f"—————————————\n"
        f"متن جدید رو بفرستید (تگ‌های ساده HTML مثل &lt;b&gt; پشتیبانی میشه):",
        parse_mode="HTML",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.editing_welcome_message)
async def save_welcome_message(message: Message, state: FSMContext):
    text = message.text or message.caption
    if not text:
        await message.answer("لطفاً یه پیام متنی معتبر بفرستید.")
        return
    await db.set_welcome_message(text)
    await state.clear()
    await message.answer("✅ پیام خوش‌آمدگویی با موفقیت بروزرسانی شد.", reply_markup=admin_menu_kb())


@dp.callback_query(F.data == "adminrules")
async def admin_edit_rules(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    current = await db.get_rules_text()
    current_display = current if current else f"(پیش‌فرض)\n\n{DEFAULT_RULES_TEXT}"
    await state.set_state(AdminStates.editing_rules_text)
    await callback.message.edit_text(
        f"📜 <b>قوانین فعلی:</b>\n\n{current_display}\n\n"
        f"—————————————\n"
        f"متن جدید قوانین رو بفرستید (تگ‌های ساده HTML مثل &lt;b&gt; پشتیبانی میشه):",
        parse_mode="HTML",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.editing_rules_text)
async def save_rules_text(message: Message, state: FSMContext):
    text = message.text or message.caption
    if not text:
        await message.answer("لطفاً یه پیام متنی معتبر بفرستید.")
        return
    await db.set_rules_text(text)
    await state.clear()
    await message.answer("✅ قوانین با موفقیت بروزرسانی شد.", reply_markup=admin_menu_kb())


def referral_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ تغییر درصد پورسانتی", callback_data="editrefpercent")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")],
        ]
    )


@dp.callback_query(F.data == "adminreferral")
async def admin_referral_settings(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.clear()
    percent = await db.get_referral_commission_percent()
    await callback.message.edit_text(
        f"🤝 <b>تنظیمات رفرال (پورسانتی دائمی)</b>\n\n"
        f"💸 درصد پورسانتی فعلی: <b>{percent}٪</b>\n\n"
        f"به‌ازای هر خرید موفق (تحویل‌شده) هر کاربری که با لینک یه نفر وارد ربات شده، همین درصد از مبلغ خرید بلافاصله و به‌صورت نقدی به کیف پول دعوت‌کننده اضافه میشه — برای همیشه و بدون محدودیت تعداد دفعات.",
        parse_mode="HTML",
        reply_markup=referral_settings_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data == "editrefpercent")
async def start_edit_referral_percent(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.editing_referral_percent)
    await callback.message.edit_text(
        "درصد پورسانتی رفرال رو وارد کنید (عدد بین ۱ تا ۱۰۰، مثال: 10):",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.editing_referral_percent)
async def save_referral_percent(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("لطفاً یه عدد صحیح بین ۱ تا ۱۰۰ بفرستید (مثال: 10)")
        return
    await db.set_setting("referral_commission_percent", int(text))
    await state.clear()
    await message.answer("✅ درصد پورسانتی رفرال با موفقیت بروزرسانی شد.", reply_markup=referral_settings_kb())


# ---------- Admin: کد تخفیف ----------
async def coupons_admin_kb() -> InlineKeyboardMarkup:
    coupons = await db.list_coupons()
    rows = []
    for c in coupons:
        status = "✅" if c["active"] else "🚫"
        usage = f"{c['used_count']}/{c['max_uses']}" if c["max_uses"] is not None else f"{c['used_count']}/∞"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{status} {c['code']} - {c['percent']}٪ ({usage})",
                    callback_data=f"coupontoggle:{c['code']}",
                ),
                InlineKeyboardButton(text="🗑", callback_data=f"coupondelete:{c['code']}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="➕ ساخت کد تخفیف جدید", callback_data="coupadd")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@dp.callback_query(F.data == "admincoupons")
async def admin_coupons_root(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "🎟 <b>کدهای تخفیف</b>\nروی هر کد بزنید تا فعال/غیرفعال بشه، یا با 🗑 حذفش کنید.",
        parse_mode="HTML",
        reply_markup=await coupons_admin_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("coupontoggle:"))
async def toggle_coupon(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    code = callback.data.split(":", 1)[1]
    await db.toggle_coupon_active(code)
    await callback.message.edit_text(
        "🎟 <b>کدهای تخفیف</b>\nروی هر کد بزنید تا فعال/غیرفعال بشه، یا با 🗑 حذفش کنید.",
        parse_mode="HTML",
        reply_markup=await coupons_admin_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("coupondelete:"))
async def delete_coupon_handler(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    code = callback.data.split(":", 1)[1]
    await db.delete_coupon(code)
    await callback.message.edit_text(
        "🎟 <b>کدهای تخفیف</b>\nروی هر کد بزنید تا فعال/غیرفعال بشه، یا با 🗑 حذفش کنید.",
        parse_mode="HTML",
        reply_markup=await coupons_admin_kb(),
    )
    await callback.answer("کد تخفیف حذف شد.")


@dp.callback_query(F.data == "coupadd")
async def start_add_coupon(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.adding_coupon_code)
    await callback.message.edit_text(
        "کد تخفیف رو وارد کنید (فقط حروف انگلیسی و عدد، بدون فاصله - مثال: SUMMER20):",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.adding_coupon_code)
async def add_coupon_step_code(message: Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code.isalnum():
        await message.answer("کد باید فقط شامل حروف انگلیسی و عدد باشه، بدون فاصله یا کاراکتر خاص. دوباره امتحان کنید:")
        return
    existing = await db.get_coupon(code)
    if existing:
        await message.answer("این کد قبلاً ثبت شده. یه کد دیگه انتخاب کنید:")
        return
    await state.update_data(coupon_code=code)
    await state.set_state(AdminStates.adding_coupon_percent)
    await message.answer("چند درصد تخفیف بده؟ (عدد بین ۱ تا ۱۰۰):")


@dp.message(AdminStates.adding_coupon_percent)
async def add_coupon_step_percent(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("لطفاً یه عدد صحیح بین ۱ تا ۱۰۰ بفرستید:")
        return
    await state.update_data(coupon_percent=int(text))
    await state.set_state(AdminStates.adding_coupon_maxuses)
    await message.answer("حداکثر تعداد استفاده از این کد چقدر باشه؟ (برای نامحدود، عدد 0 رو بفرستید):")


@dp.message(AdminStates.adding_coupon_maxuses)
async def add_coupon_step_maxuses(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (برای نامحدود، 0 رو بفرستید):")
        return
    max_uses = int(text) if int(text) > 0 else None

    data = await state.get_data()
    code = data.get("coupon_code")
    percent = data.get("coupon_percent")
    await db.create_coupon(code, percent, max_uses)
    await state.clear()

    usage_text = f"{max_uses} بار" if max_uses else "نامحدود"
    await message.answer(
        f"✅ کد تخفیف <b>{code}</b> با {percent}٪ تخفیف و ظرفیت {usage_text} ساخته شد.",
        parse_mode="HTML",
        reply_markup=await coupons_admin_kb(),
    )


# ---------- Admin: تخفیف پلکانی شارژ کیف پول ----------
def wallet_bonus_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ تغییر آستانه مبلغ", callback_data="editwalletthreshold")],
            [InlineKeyboardButton(text="✏️ تغییر درصد هدیه", callback_data="editwalletbonuspercent")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admintariff:root")],
        ]
    )


@dp.callback_query(F.data == "adminwalletbonus")
async def admin_wallet_bonus_settings(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.clear()
    threshold = await db.get_wallet_bonus_threshold()
    percent = await db.get_wallet_bonus_percent()
    await callback.message.edit_text(
        f"💳 <b>تخفیف پلکانی شارژ کیف پول</b>\n\n"
        f"📊 آستانه فعلی: <b>{threshold:,} تومان</b>\n"
        f"🎁 درصد هدیه: <b>{percent}٪</b>\n\n"
        f"یعنی وقتی کاربری {threshold:,} تومان یا بیشتر شارژ کنه، {percent}٪ هدیه اضافه هم به کیف پولش اضافه میشه.",
        parse_mode="HTML",
        reply_markup=wallet_bonus_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data == "editwalletthreshold")
async def start_edit_wallet_threshold(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.editing_wallet_bonus_threshold)
    await callback.message.edit_text(
        "حداقل مبلغ شارژ برای دریافت هدیه رو به تومان وارد کنید (مثال: 500000):",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.editing_wallet_bonus_threshold)
async def save_wallet_threshold(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("لطفاً یه عدد صحیح و بزرگ‌تر از صفر بفرستید (مثال: 500000)")
        return
    await db.set_setting("wallet_bonus_threshold", int(text))
    await state.clear()
    await message.answer("✅ آستانه مبلغ با موفقیت بروزرسانی شد.", reply_markup=wallet_bonus_kb())


@dp.callback_query(F.data == "editwalletbonuspercent")
async def start_edit_wallet_bonus_percent(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.editing_wallet_bonus_percent)
    await callback.message.edit_text(
        "درصد هدیه رو وارد کنید (عدد بین ۱ تا ۱۰۰، مثال: 5):",
        reply_markup=back_to_admin_root_kb,
    )
    await callback.answer()


@dp.message(AdminStates.editing_wallet_bonus_percent)
async def save_wallet_bonus_percent(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit() or not (1 <= int(text) <= 100):
        await message.answer("لطفاً یه عدد صحیح بین ۱ تا ۱۰۰ بفرستید (مثال: 5)")
        return
    await db.set_setting("wallet_bonus_percent", int(text))
    await state.clear()
    await message.answer("✅ درصد هدیه با موفقیت بروزرسانی شد.", reply_markup=wallet_bonus_kb())


@dp.callback_query(F.data == "admintariff:gaming")
async def admintariff_gaming(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await callback.message.edit_text(
        "🎮 <b>تعرفه‌های سرویس گیمینگ</b>\nروی هر تعرفه بزنید تا قیمتش رو تغییر بدید، یا فعال/غیرفعالش کنید:",
        parse_mode="HTML",
        reply_markup=await gaming_admin_list_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data == "admintariff:multi")
async def admintariff_multi(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await callback.message.edit_text(
        "🌍 <b>تعرفه‌های سرویس مولتی لوکیشن</b>\nروی هر تعرفه بزنید تا قیمتش رو تغییر بدید، یا فعال/غیرفعالش کنید:",
        parse_mode="HTML",
        reply_markup=await multi_admin_list_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("gtoggle:"))
async def toggle_gaming(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    await db.toggle_gaming_active(plan_id)
    await callback.message.edit_reply_markup(reply_markup=await gaming_admin_list_kb())
    await callback.answer("وضعیت تعرفه تغییر کرد.")


@dp.callback_query(F.data.startswith("mtoggle:"))
async def toggle_multi(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    await db.toggle_multi_active(plan_id)
    await callback.message.edit_reply_markup(reply_markup=await multi_admin_list_kb())
    await callback.answer("وضعیت تعرفه تغییر کرد.")


@dp.callback_query(F.data.startswith("gpriceedit:"))
async def start_edit_gaming_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    plan = await db.get_gaming_plan(plan_id)
    if not plan:
        await callback.answer("این تعرفه پیدا نشد.", show_alert=True)
        return
    await state.update_data(plan_id=plan_id)
    await state.set_state(AdminStates.editing_gaming_price)
    await callback.message.answer(
        f"قیمت جدید برای «{plan['volume_gb']} گیگ» رو به تومان بفرستید (فقط عدد):"
    )
    await callback.answer()


@dp.message(AdminStates.editing_gaming_price)
async def save_gaming_price(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (مثال: 80000)")
        return
    data = await state.get_data()
    plan_id = data.get("plan_id")
    await db.update_gaming_price(plan_id, int(text))
    await state.clear()
    await message.answer("✅ قیمت با موفقیت بروزرسانی شد.", reply_markup=await gaming_admin_list_kb())


@dp.callback_query(F.data.startswith("mpriceedit:"))
async def start_edit_multi_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    plan_id = int(callback.data.split(":")[1])
    plan = await db.get_multi_plan(plan_id)
    if not plan:
        await callback.answer("این تعرفه پیدا نشد.", show_alert=True)
        return
    await state.update_data(plan_id=plan_id)
    await state.set_state(AdminStates.editing_multi_price)
    await callback.message.answer(
        f"قیمت جدید برای «{plan['label']}» رو به تومان بفرستید (فقط عدد):"
    )
    await callback.answer()


@dp.message(AdminStates.editing_multi_price)
async def save_multi_price(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (مثال: 180000)")
        return
    data = await state.get_data()
    plan_id = data.get("plan_id")
    await db.update_multi_price(plan_id, int(text))
    await state.clear()
    await message.answer("✅ قیمت با موفقیت بروزرسانی شد.", reply_markup=await multi_admin_list_kb())


@dp.callback_query(F.data == "gadd")
async def start_add_gaming(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.adding_gaming_volume)
    await callback.message.answer("حجم تعرفه جدید رو به گیگابایت بفرستید (فقط عدد، مثال: 60):")
    await callback.answer()


@dp.message(AdminStates.adding_gaming_volume)
async def add_gaming_volume(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (مثال: 60)")
        return
    await state.update_data(volume=int(text))
    await state.set_state(AdminStates.adding_gaming_price)
    await message.answer("حالا قیمت این تعرفه رو به تومان بفرستید:")


@dp.message(AdminStates.adding_gaming_price)
async def add_gaming_price(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (مثال: 400000)")
        return
    data = await state.get_data()
    volume = data.get("volume")
    await db.add_gaming_plan(volume, int(text))
    await state.clear()
    await message.answer("✅ تعرفه جدید اضافه شد.", reply_markup=await gaming_admin_list_kb())


@dp.callback_query(F.data == "madd")
async def start_add_multi(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return
    await state.set_state(AdminStates.adding_multi_label)
    await callback.message.answer("عنوان تعرفه جدید رو بفرستید (مثال: سه کاربره نامحدود یک‌ماهه):")
    await callback.answer()


@dp.message(AdminStates.adding_multi_label)
async def add_multi_label(message: Message, state: FSMContext):
    label = (message.text or "").strip()
    if not label:
        await message.answer("لطفاً یه عنوان معتبر بفرستید.")
        return
    await state.update_data(label=label)
    await state.set_state(AdminStates.adding_multi_price)
    await message.answer("حالا قیمت این تعرفه رو به تومان بفرستید:")


@dp.message(AdminStates.adding_multi_price)
async def add_multi_price(message: Message, state: FSMContext):
    text = (message.text or "").replace(",", "").strip()
    if not text.isdigit():
        await message.answer("لطفاً فقط عدد بفرستید (مثال: 300000)")
        return
    data = await state.get_data()
    label = data.get("label")
    await db.add_multi_plan(label, int(text))
    await state.clear()
    await message.answer("✅ تعرفه جدید اضافه شد.", reply_markup=await multi_admin_list_kb())


# ---------- Admin handlers ----------
@dp.callback_query(F.data.startswith("approve:"))
async def admin_approve(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("سفارش پیدا نشد.", show_alert=True)
        return

    await db.set_order_status(order_id, "approved")
    await state.update_data(order_id=order_id)
    await state.set_state(AdminStates.waiting_for_panel_info)

    await callback.message.answer(
        f"✅ سفارش #{order_id} تأیید شد.\n"
        f"حالا لطفاً اطلاعات سرویس (کانفیگ/یوزر/پس/لینک و ...) رو برای ارسال به مشتری بفرستید:"
    )
    await callback.answer()


@dp.message(AdminStates.waiting_for_panel_info)
async def admin_send_panel_info(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    order = await db.get_order(order_id)
    if not order:
        await message.answer("سفارش پیدا نشد.")
        await state.clear()
        return

    panel_info = message.text or message.caption or ""
    await db.deliver_order(order_id, panel_info)
    await state.clear()

    try:
        await bot.send_message(
            order["user_id"],
            f"🎉 سفارش شما (#{order_id}) تأیید و تحویل داده شد!\n\n"
            f"🔑 اطلاعات سرویس شما:\n{panel_info}",
        )
        await message.answer(f"✅ اطلاعات سرویس با موفقیت برای مشتری سفارش #{order_id} ارسال شد.")
    except Exception as e:
        await message.answer(f"⚠️ ارسال به کاربر ناموفق بود: {e}")

    # رفرال دائمی پورسانتی: به‌ازای هر خرید موفق (تحویل‌شده) کاربری که با لینک یه نفر دیگه وارد شده،
    # درصدی از مبلغ خرید به‌صورت نقدی به کیف پول دعوت‌کننده اضافه میشه - این کار به تعداد نامحدود تکرار میشه
    referral = await db.get_referral_by_referred(order["user_id"])
    if referral:
        if not referral["converted"]:
            await db.mark_referral_converted(order["user_id"])
        referrer_id = referral["referrer_id"]
        if order["price"] and order["price"] > 0:
            commission_percent = await db.get_referral_commission_percent()
            commission_amount = int(order["price"] * commission_percent / 100)
            if commission_amount > 0:
                await db.add_wallet_balance(referrer_id, commission_amount)
                await db.add_referral_commission(referrer_id, order["user_id"], order_id, commission_amount)
                try:
                    await bot.send_message(
                        referrer_id,
                        f"💸 یکی از دوستانی که دعوت کردید خرید کرد!\n"
                        f"مبلغ {commission_amount:,} تومان ({commission_percent}٪ از خریدش) به کیف پول شما اضافه شد. 🎉",
                    )
                except Exception as e:
                    logging.warning(f"Could not notify referrer {referrer_id} about commission: {e}")


@dp.callback_query(F.data.startswith("reject:"))
async def admin_reject(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("شما دسترسی ادمین ندارید.", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("سفارش پیدا نشد.", show_alert=True)
        return

    await db.set_order_status(order_id, "rejected")

    refund_note = ""
    if order["payment_method"] == "wallet" and order["price"] > 0:
        await db.add_wallet_balance(order["user_id"], order["price"])
        refund_note = f"\n💰 مبلغ {order['price']:,} تومان به کیف پول شما برگردونده شد."

    try:
        await bot.send_message(
            order["user_id"],
            f"❌ متأسفانه سفارش شما (#{order_id}) رد شد.{refund_note}\n"
            f"در صورت وجود اشتباه در واریزی، لطفاً با پشتیبانی در ارتباط باشید.",
        )
    except Exception as e:
        logging.warning(f"Could not notify user: {e}")

    await callback.message.answer(f"❌ سفارش #{order_id} رد شد و به کاربر اطلاع داده شد.")
    await callback.answer()


@dp.message(Command("orders_admin"))
async def admin_all_pending(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        return
    # نمایش سریع راهنما - برای گزارش کامل می‌تونید دیتابیس bot.db رو با ابزار SQLite باز کنید
    await message.answer(
        "برای مشاهده کامل سفارش‌ها فایل دیتابیس bot.db رو بررسی کنید، "
        "یا از دستورات تأیید/رد که زیر هر سفارش جدید ارسال میشه استفاده کنید."
    )


# ---------- Startup ----------
async def main():
    global BOT_USERNAME
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده! متغیر محیطی BOT_TOKEN رو ست کنید.")
    if not config.ADMIN_IDS:
        logging.warning("ADMIN_IDS تنظیم نشده! هیچ ادمینی سفارش‌ها رو دریافت نمی‌کنه.")

    await db.init_db()
    await bot.delete_webhook(drop_pending_updates=True)

    me = await bot.get_me()
    BOT_USERNAME = me.username
    logging.info(f"Bot started as @{BOT_USERNAME}")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
