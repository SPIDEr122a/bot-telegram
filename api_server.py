"""API + مینی‌اپ تلگرام."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import config
import database as db

logger = logging.getLogger(__name__)

app = FastAPI(title="MiniApp", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MINIAPP_DIR = Path(__file__).resolve().parent / "miniapp"


def _validate_init_data(init_data: str, max_age_sec: int = 86400) -> dict:
    if not init_data or not config.BOT_TOKEN:
        raise HTTPException(status_code=401, detail="Missing initData")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="No hash")

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        raise HTTPException(status_code=401, detail="Invalid hash")

    auth_date = int(parsed.get("auth_date") or 0)
    if auth_date and time.time() - auth_date > max_age_sec:
        raise HTTPException(status_code=401, detail="initData expired")

    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="No user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        user = json.loads(unquote(user_raw))
    return user


async def current_user(
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
):
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Send X-Telegram-Init-Data header")
    user = _validate_init_data(x_telegram_init_data)
    uid = int(user["id"])
    return {
        "id": uid,
        "username": user.get("username") or "",
        "full_name": (
            " ".join(
                x for x in [user.get("first_name") or "", user.get("last_name") or ""] if x
            ).strip()
            or "User"
        ),
        "is_admin": uid in config.ADMIN_IDS,
    }


@app.on_event("startup")
async def _startup():
    try:
        await db.init_db()
        logger.info("DB ready")
    except Exception:
        logger.exception("init_db failed")


@app.get("/api/health")
@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "service": "miniapp"})


@app.get("/api/me")
async def api_me(user=Depends(current_user)):
    balance = await db.get_wallet_balance(user["id"])
    return {
        **user,
        "balance": balance,
        "brand": config.BRAND_NAME,
        "support": config.SUPPORT_USERNAME,
        "join_bonus": int(getattr(config, "REFERRAL_JOIN_BONUS", 30000) or 0),
    }


@app.get("/api/services")
async def api_services(user=Depends(current_user)):
    out = []
    gaming = await db.get_gaming_plans(active_only=True)
    if gaming:
        out.append(
            {
                "id": "gaming",
                "title": "🎮 سرویس گیمینگ",
                "plans": [
                    {"id": f"g:{p['id']}", "label": f"{p['volume_gb']} گیگ", "price": p["price"]}
                    for p in gaming
                ],
            }
        )
    multi = await db.get_multi_plans(active_only=True)
    if multi:
        out.append(
            {
                "id": "multi",
                "title": "🌍 مولتی لوکیشن",
                "plans": [
                    {"id": f"m:{p['id']}", "label": p["label"], "price": p["price"]} for p in multi
                ],
            }
        )
    try:
        cats = await db.get_tariff_categories(active_only=True)
        for c in cats:
            plans = await db.get_tariff_plans(c["id"], active_only=True)
            if not plans:
                continue
            out.append(
                {
                    "id": f"cat:{c['id']}",
                    "title": f"📦 {c['name']}",
                    "plans": [
                        {"id": f"c:{p['id']}", "label": p["label"], "price": p["price"]}
                        for p in plans
                    ],
                }
            )
    except Exception:
        logger.exception("custom categories")
    return {"categories": out}


@app.get("/api/referral")
async def api_referral(user=Depends(current_user)):
    bot_user = (os.getenv("BOT_USERNAME") or "").lstrip("@")
    link = f"https://t.me/{bot_user}?start=ref_{user['id']}" if bot_user else ""
    total = await db.count_referrals(user["id"])
    converted = await db.count_converted_referrals(user["id"])
    earned = await db.get_total_referral_earnings(user["id"])
    bonus = int(getattr(config, "REFERRAL_JOIN_BONUS", 30000) or 0)
    return {
        "link": link,
        "total": total,
        "converted": converted,
        "earned": earned,
        "join_bonus": bonus,
        "message": (
            f"با لینک دعوت، هم تو و هم دوستت هر کدام {bonus:,} تومان می‌گیرید.\n"
            "قضیه برد مساوی برد هست 💚"
        ),
    }


@app.get("/api/orders/mine")
async def api_my_orders(user=Depends(current_user)):
    orders = await db.get_user_orders(user["id"])
    return {
        "orders": [
            {
                "id": o["id"],
                "plan_name": o["plan_name"],
                "price": o["price"],
                "status": o["status"],
                "created_at": o["created_at"],
            }
            for o in (orders or [])[:30]
        ]
    }


@app.get("/api/admin/report")
async def api_admin_report(user=Depends(current_user)):
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    rep = await db.get_orders_report()
    return {
        "total": rep["total"],
        "delivered": rep["delivered"],
        "pending": rep["pending"],
        "rejected": rep["rejected"],
        "revenue": rep["revenue"],
        "revenue_today": rep["revenue_today"],
        "delivered_today": rep["delivered_today"],
        "recent": [
            {
                "id": o["id"],
                "plan_name": o["plan_name"],
                "price": o["price"],
                "status": o["status"],
                "user_id": o["user_id"],
                "full_name": o["full_name"],
            }
            for o in rep["recent"]
        ],
    }


@app.get("/")
async def index():
    index_path = MINIAPP_DIR / "index.html"
    if not index_path.is_file():
        return HTMLResponse(
            "<h1>miniapp/index.html missing</h1>",
            status_code=404,
        )
    return FileResponse(index_path, media_type="text/html; charset=utf-8")
