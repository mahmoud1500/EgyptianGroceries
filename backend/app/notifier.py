"""SMS + push notifications.

Same pattern as emailer.py: real send when the provider is configured,
otherwise a clearly-marked console log (dev fallback). NEVER raises —
a notification failure must not break order flows. Every function returns
True only when the message was really delivered.

Env (two spellings supported; the TWILIO_ACCOUNT_SID family takes
precedence — use those for new setups):
  TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER  (preferred)
  TWILIO_SID / TWILIO_TOKEN / TWILIO_FROM                     (legacy)
  — if all three are set, SMS goes through the Twilio Messages API
  (https://api.twilio.com). Credential values are NEVER logged or stored —
  logs only ever show a masked phone number (last 4 digits).
Push (Oct 2026): the mobile app registers Expo push tokens via
POST /api/push/register (stored in the push_tokens table). send_push_* below
delivers through the free Expo Push API (https://exp.host/--/api/v2/push/send)
— no credentials needed on our side.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

# New spelling takes precedence; legacy spelling is the fallback.
TWILIO_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip() or os.environ.get("TWILIO_SID", "").strip()
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip() or os.environ.get("TWILIO_TOKEN", "").strip()
TWILIO_FROM = os.environ.get("TWILIO_FROM_NUMBER", "").strip() or os.environ.get("TWILIO_FROM", "").strip()

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _mask_phone(to: str) -> str:
    """Mask a phone number for logs: only the last 4 digits are shown.

    '+1 (206) 555-0199' -> '+•••••••0199'. The full number NEVER appears
    in a log line.
    """
    s = str(to or "")
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return "•••"
    prefix = "+" if s.strip().startswith("+") else ""
    return prefix + "•" * max(len(digits) - 4, 0) + digits[-4:]


def _scrub(text: str) -> str:
    """Redact Twilio credential values from a string (e.g. an error that
    echoes the request URL, which embeds the account SID)."""
    out = str(text or "")
    for secret in (TWILIO_SID, TWILIO_TOKEN):
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


def send_sms(to: str, msg: str) -> bool:
    """Send an SMS via Twilio, or log it when Twilio isn't configured.

    Returns True only if Twilio accepted the message. Never raises.
    Logs show a MASKED phone number only — never the full number, and
    never any credential value.
    """
    if not to or not msg:
        print("[notifier] no recipient/message — SMS skipped")
        return False
    if TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM:
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
            data = urllib.parse.urlencode(
                {"From": TWILIO_FROM, "To": to, "Body": msg}
            ).encode("utf-8")
            creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Authorization": f"Basic {creds}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            print(f"[notifier] SMS sent via Twilio → {_mask_phone(to)}")
            return True
        except Exception as exc:  # noqa: BLE001 — SMS must never crash the request
            # The exception may echo the request URL (which embeds the SID);
            # scrub credentials before logging.
            print(f"[notifier] Twilio failed ({_scrub(exc)}) — falling back to console log")
    # Dev fallback: clearly marked console log.
    print(
        "[notifier:console-fallback — NOT really sent]\n"
        f"To (SMS): {_mask_phone(to)}\n{msg}\n"
        "[end sms]"
    )
    return False


def send_push_to_tokens(db, token_rows, title: str, body: str, data: dict | None = None) -> bool:
    """Deliver a push via the free Expo Push API to the given token rows.

    token_rows: iterable of objects with an .expo_token attribute (PushToken).
    data: extra payload delivered to the app (e.g. {"orderId": 123}) so it can
    deep-link on tap. Tickets that come back as DeviceNotRegistered have their
    row deleted (stale token cleanup). Never raises. Returns True when at
    least one ticket was accepted.
    """
    try:
        rows = list(token_rows)
        tokens = [r.expo_token for r in rows if getattr(r, "expo_token", None)]
        if not tokens or not title or not body:
            print("[notifier] no push tokens/message — push skipped")
            return False
        accepted = False
        # Expo accepts up to 100 messages per request.
        for chunk in (tokens[i : i + 100] for i in range(0, len(tokens), 100)):
            messages = [
                {
                    "to": tok,
                    "title": title,
                    "body": body,
                    "data": data or {},
                    "sound": "default",
                }
                for tok in chunk
            ]
            req = urllib.request.Request(
                EXPO_PUSH_URL,
                data=json.dumps(messages).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    payload = json.loads(resp.read().decode("utf-8") or "{}")
            except Exception as exc:  # noqa: BLE001 — push must never crash the request
                print(f"[notifier] Expo push failed ({exc}) — skipping chunk")
                continue
            tickets = payload.get("data") or []
            for tok, ticket in zip(chunk, tickets):
                if not isinstance(ticket, dict):
                    continue
                if ticket.get("status") == "ok":
                    accepted = True
                    continue
                details = ticket.get("details") or {}
                if details.get("error") == "DeviceNotRegistered":
                    # Token is dead (app uninstalled / token rotated) — prune it.
                    from . import models as _m

                    try:
                        db.query(_m.PushToken).filter_by(expo_token=tok).delete(
                            synchronize_session=False
                        )
                        db.commit()
                        print(f"[notifier] pruned dead push token {tok[:24]}…")
                    except Exception as exc:  # noqa: BLE001
                        db.rollback()
                        print(f"[notifier] token prune failed ({exc})")
                else:
                    print(f"[notifier] Expo ticket error for {tok[:24]}…: {ticket}")
        return accepted
    except Exception as exc:  # noqa: BLE001 — belt and suspenders
        print(f"[notifier] send_push_to_tokens failed ({exc})")
        return False


# === v40: admin alerts (new order / application / ticket) ===
_ALERT_TOGGLE = {
    "order": "alert_orders",
    "application": "alert_applications",
    "ticket": "alert_tickets",
}


def _setting_value(db, key: str, default: str = "") -> str:
    """Read a raw Setting value (string). Never raises."""
    try:
        from . import models as _m

        row = db.query(_m.Setting).filter(_m.Setting.key == key).first()
        if row is not None and row.value is not None:
            return str(row.value)
    except Exception:
        pass
    return default


def alert_admins(db, kind: str, title: str, body: str) -> bool:
    """Notify the admin the moment something needs attention.

    kind: "order" | "application" | "ticket". Each has an on/off toggle
    in admin settings (alert_orders / alert_applications / alert_tickets,
    default on). Delivery: Expo push to every admin-role user's tokens +
    one SMS to the alert_phone setting (Twilio when configured, otherwise
    the notifier's clearly-marked console log). Best effort — never raises,
    never breaks the calling flow. Returns True if anything was delivered.
    """
    try:
        toggle_key = _ALERT_TOGGLE.get(kind)
        if toggle_key and _setting_value(db, toggle_key, "1") not in ("1", "true", "yes"):
            return False
        from . import models as _m

        delivered = False
        admin_ids = [
            u.id
            for u in db.query(_m.User).filter(_m.User.role == "admin").all()
        ]
        if admin_ids and title and body:
            rows = (
                db.query(_m.PushToken)
                .filter(_m.PushToken.user_id.in_(admin_ids))
                .all()
            )
            if send_push_to_tokens(db, rows, title, body, data={"alertKind": kind}):
                delivered = True
        phone = _setting_value(db, "alert_phone", "").strip()
        if phone and body:
            if send_sms(phone, f"{title}\n{body}"):
                delivered = True
        return delivered
    except Exception as exc:  # noqa: BLE001 — alerts must never break the flow
        print(f"[notifier] alert_admins failed ({exc})")
        return False
# === END v40 ===
_PUSH_STATUS_PRETTY = {
    "new": ("confirmed ✅", "تم تأكيد طلبك ✅"),
    "preparing": ("being prepared 👨‍🍳", "بيتجهز دلوقتي 👨‍🍳"),
    "ready": ("ready 🎉", "جاهز للاستلام 🎉"),
    "on_the_way": ("on its way to you 🛵", "في الطريق ليك 🛵"),
    "completed": ("completed — bil hana wil shifa! 😋", "اتسلّم — بالهنا والشفا 😋"),
    "cancelled": ("cancelled", "اتلغى"),
}


def send_order_status_push(db, order, new_status: str) -> bool:
    """Push the customer about an order status change. Best effort — never raises.

    Guest orders (no customer_id) are skipped: push tokens are tied to app
    accounts. Called from the existing status-change notification spot in
    routers/orders.py.
    """
    try:
        customer_id = getattr(order, "customer_id", None)
        if not customer_id:
            return False
        from . import models as _m

        rows = (
            db.query(_m.PushToken).filter(_m.PushToken.user_id == customer_id).all()
        )
        if not rows:
            return False
        en_pretty, ar_pretty = _PUSH_STATUS_PRETTY.get(
            new_status, (new_status, new_status)
        )
        title = f"Osiris — order #{order.id}"
        body = f"Your order is {en_pretty}\nطلبك #{order.id} {ar_pretty}"
        # === FEATURE 9: pickup-point card appended to the push reminder ===
        vendor = getattr(order, "vendor", None)
        if (getattr(order, "fulfillment", "") or "") == "pickup" and vendor is not None:
            addr = (getattr(vendor, "pickup_address", None) or "").strip()
            if addr:
                body += f"\n📍 {addr}"
        # === END FEATURE 9 ===
        return send_push_to_tokens(
            db, rows, title, body, data={"orderId": order.id}
        )
    except Exception as exc:  # noqa: BLE001 — a push failure must never break the order flow
        print(f"[notifier] send_order_status_push failed ({exc})")
        return False


def send_order_status_sms(db, order, new_status: str) -> bool:
    """SMS the customer about an order status change. Best effort — never raises.

    Works for BOTH account orders (uses the customer's saved phone) and
    guest orders (uses order.guest_phone). Silently skips when there is no
    phone number at all. The body is bilingual (EN + AR), reusing the
    _PUSH_STATUS_PRETTY status labels. Logs show a MASKED phone only.
    Called from the vendor + admin status-change endpoints.
    """
    try:
        customer = getattr(order, "customer", None)
        phone = (getattr(customer, "phone", None) if customer else None) or getattr(
            order, "guest_phone", None
        )
        if not phone:
            return False  # silent skip — nothing to send to
        vendor = getattr(order, "vendor", None)
        vendor_name = (getattr(vendor, "name", None) or "").strip()
        en_pretty, ar_pretty = _PUSH_STATUS_PRETTY.get(
            new_status, (new_status, new_status)
        )
        body = (
            f"Osiris: order #{order.id} from {vendor_name} is now {en_pretty}\n"
            f"Osiris: الأوردر رقم #{order.id} من {vendor_name} بقى {ar_pretty}"
        )
        return send_sms(phone, body)
    except Exception as exc:  # noqa: BLE001 — an SMS failure must never break the order flow
        print(f"[notifier] send_order_status_sms failed ({exc})")
        return False
