"""
اتصال به پنل PasarGuard برای ساخت خودکار اکانت تست.
همه تنظیمات از config (متغیرهای محیطی) خوانده می‌شود.
"""
from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

import httpx

import config

logger = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def _base() -> str:
    return (config.PASARGUARD_BASE_URL or "").rstrip("/")


async def _get_token(client: httpx.AsyncClient) -> str:
    """توکن ادمین یا API Key پنل را برمی‌گرداند."""
    # اولویت با API Key — بدون نیاز به لاگین یوزر/پسورد
    if config.PASARGUARD_API_KEY:
        return config.PASARGUARD_API_KEY.strip()

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    # PasarGuard: OAuth2 password form
    url = f"{_base()}/api/admin/token"
    data = {
        "username": config.PASARGUARD_USERNAME,
        "password": config.PASARGUARD_PASSWORD,
        "grant_type": "password",
    }
    r = await client.post(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code >= 400:
        r2 = await client.post(
            f"{_base()}/api/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r2.status_code >= 400:
            raise RuntimeError(
                f"Login failed: {r.status_code} {r.text[:300]} | alt: {r2.status_code} {r2.text[:200]}"
            )
        r = r2

    payload = r.json()
    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise RuntimeError(f"No access_token in login response: {payload}")

    expires_in = int(payload.get("expires_in") or 3600)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


def _auth_headers(token: str) -> dict[str, str]:
    """هدر احراز هویت — برای API Key هم Bearer و هم X-Api-Key ارسال می‌شود."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if config.PASARGUARD_API_KEY and token == config.PASARGUARD_API_KEY.strip():
        headers["X-Api-Key"] = token
    return headers


async def _fetch_groups_list(client: httpx.AsyncClient, token: str) -> list[dict]:
    """لیست گروه‌ها را از چند مسیر رایج API می‌گیرد."""
    headers = _auth_headers(token)
    base = _base()
    attempts = [
        ("GET", f"{base}/api/groups/simple", {"all": "true", "limit": "500"}),
        ("GET", f"{base}/api/groups/simple", {"limit": "500"}),
        ("GET", f"{base}/api/groups", {"limit": "500", "offset": "0"}),
        ("GET", f"{base}/api/group", {"limit": "500"}),
    ]
    errors: list[str] = []
    for method, url, params in attempts:
        try:
            r = await client.request(method, url, headers=headers, params=params)
        except Exception as e:
            errors.append(f"{url}: {e}")
            continue
        if r.status_code >= 400:
            errors.append(f"{url} -> {r.status_code} {r.text[:120]}")
            continue
        try:
            payload = r.json()
        except Exception:
            errors.append(f"{url}: invalid json")
            continue

        if isinstance(payload, list):
            groups_list = payload
        elif isinstance(payload, dict):
            groups_list = (
                payload.get("groups")
                or payload.get("items")
                or payload.get("data")
                or []
            )
        else:
            groups_list = []

        if isinstance(groups_list, list) and groups_list:
            logger.info("Fetched %s groups from %s", len(groups_list), url)
            return [g for g in groups_list if isinstance(g, dict)]

        errors.append(f"{url}: empty groups in response keys={list(payload) if isinstance(payload, dict) else type(payload)}")

    raise RuntimeError(
        "Could not fetch groups from panel. "
        "Check PASARGUARD_API_KEY permissions (need groups read). Details: "
        + " | ".join(errors[:4])
    )


async def _resolve_group_ids(
    client: httpx.AsyncClient,
    token: str,
    group_specs: list[str] | None = None,
) -> list[int]:
    """
    لیست اسم/آیدی گروه را به آیدی عددی تبدیل می‌کند.
    پشتیبانی: اسم گروه، آیدی عددی، یا * برای همه گروه‌ها.
    """
    specs = [s.strip() for s in (group_specs if group_specs is not None else (getattr(config, "PASARGUARD_TEST_GROUPS", None) or [])) if s.strip()]
    if not specs:
        return []

    groups_list = await _fetch_groups_list(client, token)
    by_name: dict[str, int] = {}
    by_id: dict[str, int] = {}
    for g in groups_list:
        gid = g.get("id")
        name = (g.get("name") or g.get("group_name") or "").strip()
        if gid is None:
            continue
        try:
            gid_int = int(gid)
        except (TypeError, ValueError):
            continue
        by_id[str(gid_int)] = gid_int
        if name:
            by_name[name.lower()] = gid_int

    # * یا all یعنی همه گروه‌های پنل
    if len(specs) == 1 and specs[0].lower() in ("*", "all_groups", "__all__"):
        ids = list(by_id.values())
        if not ids:
            raise RuntimeError("Panel returned no groups.")
        logger.info("Using ALL panel groups -> ids %s", ids)
        return ids

    resolved: list[int] = []
    missing: list[str] = []
    for key in specs:
        kl = key.lower()
        if kl in by_name:
            resolved.append(by_name[kl])
        elif key in by_id:
            resolved.append(by_id[key])
        else:
            missing.append(key)

    if missing:
        available = ", ".join(f"{n}(id={i})" for n, i in sorted(by_name.items())[:40]) or "(none)"
        raise RuntimeError(
            f"Group not found: {', '.join(missing)}. "
            f"Available on panel: [{available}]. "
            f"Tip: set PASARGUARD_TEST_GROUPS to exact name (e.g. 222) or use * for all groups."
        )
    if not resolved:
        raise RuntimeError("No group IDs resolved.")

    logger.info("Resolved test groups %s -> ids %s", specs, resolved)
    return list(dict.fromkeys(resolved))


def _format_volume(gb: float) -> str:
    if gb >= 1:
        # عدد صحیح اگر ممکن باشد
        if abs(gb - int(gb)) < 1e-9:
            return f"{int(gb)} گیگابایت"
        return f"{gb:g} گیگابایت"
    mb = int(round(gb * 1024))
    return f"{mb} مگابایت"


def _format_duration(hours: int) -> str:
    if hours >= 24 and hours % 24 == 0:
        days = hours // 24
        return f"{days} روز" if days != 1 else "۱ روز"
    return f"{hours} ساعت"


def build_test_message(username: str, subscription_url: str) -> str:
    """متن تحویل را از قالب Variables می‌سازد."""
    hours = config.PASARGUARD_TEST_EXPIRE_HOURS
    gb = config.PASARGUARD_TEST_DATA_LIMIT_GB
    tpl = config.PASARGUARD_TEST_MESSAGE or ""
    return tpl.format(
        username=username,
        location=config.PASARGUARD_TEST_LOCATION_NAME,
        duration=_format_duration(hours),
        volume=_format_volume(gb),
        subscription_url=subscription_url,
        service_name=config.PASARGUARD_TEST_SERVICE_NAME,
    )


def make_qr_png(data: str) -> bytes:
    """QR کد PNG از متن/لینک (مثلاً subscription_url) می‌سازد."""
    import io

    try:
        import qrcode
    except ImportError as e:
        raise RuntimeError("qrcode package is not installed") from e

    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def create_test_account(telegram_user_id: int) -> dict[str, str]:
    """
    یک اکانت تست روی پنل می‌سازد.
    خروجی: {"username", "subscription_url", "message"}
    """
    if not config.is_panel_auto_enabled():
        raise RuntimeError("Panel auto mode is not configured")

    base = _base()
    prefix = config.PASARGUARD_TEST_USERNAME_PREFIX or "test_"
    # نام یکتا: prefix + بخشی از آیدی تلگرام + رندوم کوتاه
    username = f"{prefix}{telegram_user_id}_{uuid4().hex[:6]}"
    # محدودیت طول یوزرنیم پنل معمولاً تا ۱۲۸ است
    username = username[:64]

    async with httpx.AsyncClient(timeout=30.0, verify=True, follow_redirects=True) as client:
        token = await _get_token(client)
        headers = _auth_headers(token)

        user_data: dict[str, Any] | None = None

        # مسیر ۱: ساخت از قالب
        if config.PASARGUARD_TEST_TEMPLATE_ID is not None:
            body = {
                "user_template_id": config.PASARGUARD_TEST_TEMPLATE_ID,
                "username": username,
                "note": f"telegram free test uid={telegram_user_id}",
            }
            r = await client.post(f"{base}/api/user/from_template", json=body, headers=headers)
            if r.status_code >= 400:
                logger.error("from_template failed: %s %s", r.status_code, r.text[:400])
                raise RuntimeError(f"Create from template failed: {r.status_code} {r.text[:300]}")
            user_data = r.json()
        else:
            # مسیر ۲: ساخت مستقیم
            data_limit_bytes = int(config.PASARGUARD_TEST_DATA_LIMIT_GB * (1024**3))
            expire_ts = int(time.time()) + config.PASARGUARD_TEST_EXPIRE_HOURS * 3600
            body = {
                "username": username,
                "status": "active",
                "data_limit": data_limit_bytes,
                "expire": expire_ts,
                "note": f"telegram free test uid={telegram_user_id}",
            }
            group_ids = await _resolve_group_ids(client, token)
            if group_ids:
                body["group_ids"] = group_ids
            else:
                raise RuntimeError(
                    "No test groups configured. Set PASARGUARD_TEST_GROUPS to your panel group names "
                    "(e.g. gaming,multi) or numeric IDs."
                )

            r = await client.post(f"{base}/api/user", json=body, headers=headers)
            if r.status_code >= 400:
                logger.error("create user failed: %s %s", r.status_code, r.text[:400])
                raise RuntimeError(f"Create user failed: {r.status_code} {r.text[:300]}")
            user_data = r.json()

        final_username = (user_data or {}).get("username") or username

        # بعد از ساخت، یک‌بار جزئیات کاربر را می‌گیریم تا subscription_url قطعی باشد
        try:
            r2 = await client.get(f"{base}/api/user/{final_username}", headers=headers)
            if r2.status_code < 400:
                fresh = r2.json()
                if isinstance(fresh, dict):
                    user_data = {**(user_data or {}), **fresh}
        except Exception as e:
            logger.warning("Could not refresh user after create: %s", e)

        sub = _extract_subscription_url(user_data or {}, base)
        if not sub:
            # مسیرهای جایگزین دریافت ساب
            for path in (
                f"{base}/api/user/{final_username}/subscription",
                f"{base}/api/user/{final_username}/sub",
            ):
                try:
                    r3 = await client.get(path, headers=headers)
                    if r3.status_code < 400:
                        try:
                            j = r3.json()
                            sub = _extract_subscription_url(j if isinstance(j, dict) else {}, base)
                        except Exception:
                            text = (r3.text or "").strip()
                            if text.startswith("http"):
                                sub = text.split()[0]
                        if sub:
                            break
                except Exception:
                    pass

        if not sub:
            logger.error("No subscription_url in user payload keys=%s", list((user_data or {}).keys()))
            sub = ""

    message = build_test_message(final_username, sub)
    # اگر قالب Variables جای‌نگهدار نداشت، خودمان نام و لینک را اضافه می‌کنیم
    if final_username and final_username not in message:
        message = message.rstrip() + f"\n\n👤 نام کاربری تست : {final_username}"
    if sub:
        if sub not in message:
            message = message.rstrip() + f"\n\nلینک اتصال 📎 :\n{sub}"
    else:
        message = message.rstrip() + "\n\n⚠️ لینک اشتراک از پنل دریافت نشد. با پشتیبانی تماس بگیرید."

    return {
        "username": final_username,
        "subscription_url": sub or "",
        "message": message,
    }


def _extract_subscription_url(data: dict, base: str) -> str:
    """از پاسخ پنل لینک ساب را بیرون می‌کشد."""
    if not data:
        return ""
    candidates = [
        data.get("subscription_url"),
        data.get("subscription"),
        data.get("sub_url"),
        data.get("subLink"),
        data.get("subscribe_url"),
    ]
    # بعضی پاسخ‌ها لینک‌ها را داخل لیست links می‌گذارند
    links = data.get("links") or data.get("subscription_links")
    if isinstance(links, list) and links:
        candidates.append(links[0] if isinstance(links[0], str) else None)
    if isinstance(links, dict):
        candidates.extend(links.values())

    for c in candidates:
        if isinstance(c, str) and c.strip():
            sub = c.strip()
            if sub.startswith("/"):
                sub = f"{base}{sub}"
            return sub

    token_sub = data.get("subscription_token") or data.get("token") or data.get("sub_token")
    if isinstance(token_sub, str) and token_sub.strip():
        t = token_sub.strip()
        if t.startswith("http"):
            return t
        return f"{base}/sub/{t}"
    return ""


def _format_days(days: int) -> str:
    if days <= 0:
        return "نامحدود"
    if days == 1:
        return "1 روزه"
    return f"{days} روزه"


def build_service_message(
    username: str,
    subscription_url: str,
    *,
    service_name: str,
    duration: str,
    volume: str,
) -> str:
    tpl = config.PASARGUARD_SERVICE_MESSAGE or ""
    return tpl.format(
        username=username,
        service_name=service_name,
        location=config.PASARGUARD_SERVICE_LOCATION_NAME,
        duration=duration,
        volume=volume,
        subscription_url=subscription_url,
    )


async def _create_user_on_panel(
    client: httpx.AsyncClient,
    token: str,
    *,
    username: str,
    data_limit_gb: float,
    expire_days: int,
    note: str,
    group_specs: list[str] | None,
    hwid_limit: int | None = None,
) -> dict[str, Any]:
    """ساخت کاربر روی پنل و برگرداندن payload کامل (با subscription_url)."""
    base = _base()
    headers = _auth_headers(token)

    if data_limit_gb and data_limit_gb > 0:
        data_limit_bytes = int(data_limit_gb * (1024**3))
    else:
        data_limit_bytes = 0  # نامحدود

    if expire_days and expire_days > 0:
        expire_ts = int(time.time()) + int(expire_days) * 86400
    else:
        expire_ts = 0

    body: dict[str, Any] = {
        "username": username,
        "status": "active",
        "data_limit": data_limit_bytes,
        "expire": expire_ts,
        "note": note,
    }
    if hwid_limit is not None and hwid_limit > 0:
        body["hwid_limit"] = hwid_limit

    group_ids = await _resolve_group_ids(client, token, group_specs=group_specs)
    if group_ids:
        body["group_ids"] = group_ids
    else:
        raise RuntimeError(
            "No service groups configured. Set PASARGUARD_SERVICE_GROUPS or PASARGUARD_TEST_GROUPS."
        )

    r = await client.post(f"{base}/api/user", json=body, headers=headers)
    if r.status_code >= 400:
        logger.error("create service user failed: %s %s", r.status_code, r.text[:400])
        raise RuntimeError(f"Create user failed: {r.status_code} {r.text[:300]}")
    user_data = r.json() if r.content else {}
    final_username = (user_data or {}).get("username") or username

    try:
        r2 = await client.get(f"{base}/api/user/{final_username}", headers=headers)
        if r2.status_code < 400:
            fresh = r2.json()
            if isinstance(fresh, dict):
                user_data = {**(user_data or {}), **fresh}
    except Exception as e:
        logger.warning("Could not refresh user after create: %s", e)

    sub = _extract_subscription_url(user_data or {}, base)
    if not sub:
        for path in (
            f"{base}/api/user/{final_username}/subscription",
            f"{base}/api/user/{final_username}/sub",
        ):
            try:
                r3 = await client.get(path, headers=headers)
                if r3.status_code < 400:
                    try:
                        j = r3.json()
                        sub = _extract_subscription_url(j if isinstance(j, dict) else {}, base)
                    except Exception:
                        text = (r3.text or "").strip()
                        if text.startswith("http"):
                            sub = text.split()[0]
                    if sub:
                        break
            except Exception:
                pass

    return {
        "username": final_username,
        "subscription_url": sub or "",
        "raw": user_data or {},
    }


async def create_service_account(
    *,
    telegram_user_id: int,
    order_id: int,
    data_limit_gb: float,
    expire_days: int,
    service_name: str,
    volume_label: str,
    duration_label: str | None = None,
    hwid_limit: int | None = None,
) -> dict[str, str]:
    """
    ساخت اکانت سرویس خریداری‌شده روی پنل.
    خروجی: username, subscription_url, message
    """
    if not config.is_panel_auto_enabled():
        raise RuntimeError("Panel auto mode is not configured")

    prefix = config.PASARGUARD_SERVICE_USERNAME_PREFIX or "svc_"
    username = f"{prefix}{telegram_user_id}_{order_id}_{uuid4().hex[:5]}"
    username = username[:64]
    duration = duration_label or _format_days(expire_days)

    async with httpx.AsyncClient(timeout=30.0, verify=True, follow_redirects=True) as client:
        token = await _get_token(client)
        created = await _create_user_on_panel(
            client,
            token,
            username=username,
            data_limit_gb=data_limit_gb,
            expire_days=expire_days,
            note=f"order#{order_id} telegram={telegram_user_id}",
            group_specs=list(getattr(config, "PASARGUARD_SERVICE_GROUPS", None) or []),
            hwid_limit=hwid_limit,
        )

    final_username = created["username"]
    sub = created["subscription_url"]
    message = build_service_message(
        final_username,
        sub or "—",
        service_name=service_name,
        duration=duration,
        volume=volume_label,
    )
    if final_username and final_username not in message:
        message = message.rstrip() + f"\n\n👤 نام کاربری سرویس : {final_username}"
    if sub and sub not in message:
        message = message.rstrip() + f"\n\n📎 لینک اتصال:\n{sub}"
    elif not sub:
        message = message.rstrip() + "\n\n⚠️ لینک اشتراک از پنل دریافت نشد."

    return {
        "username": final_username,
        "subscription_url": sub or "",
        "message": message,
    }
