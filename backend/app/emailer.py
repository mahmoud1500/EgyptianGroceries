"""Email sending.

Uses the Resend HTTP API when RESEND_API_KEY is set; otherwise logs the
email to the console (dev fallback, clearly marked) so order flows never
break for lack of a mail provider.

Env:
  RESEND_API_KEY  — if set, emails are really sent via https://api.resend.com/emails
  EMAIL_FROM      — sender, e.g. "Osiris Marketplace <orders@example.com>"
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request
from zoneinfo import ZoneInfo

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Osiris Marketplace <noreply@example.com>")
_MARKET_TZ = ZoneInfo("America/Los_Angeles")


def _pickup_time_text(value) -> str:
    """Format stored UTC pickup datetimes in the marketplace timezone."""
    if value is None:
        return "Not specified"
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    local = value.astimezone(_MARKET_TZ)
    return local.strftime("%a %b %d, %Y %I:%M %p %Z")


def _frontend_base() -> str:
    """Public URL of the customer site, used to build links users can click.

    Same source as routers/stripe.py: FRONTEND_URL, defaulting to local dev.
    """
    return os.environ.get("FRONTEND_URL", "http://localhost:8000").rstrip("/")


def send_email(to: str, subject: str, body_text: str) -> bool:
    """Send a plain-text email.

    Returns True if the email was really sent via Resend, False if it was
    only logged to the console (dev fallback). Never raises — a mail failure
    must not break order flows; the failure is printed instead.
    """
    if not to:
        print("[emailer] no recipient — email skipped")
        return False
    if RESEND_API_KEY:
        try:
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=json.dumps(
                    {"from": EMAIL_FROM, "to": [to], "subject": subject, "text": body_text}
                ).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
            print(f"[emailer] sent via Resend → {to} | {subject}")
            return True
        except Exception as exc:  # noqa: BLE001 — mail must never crash the request
            print(f"[emailer] Resend failed ({exc}) — falling back to console log")
    # Dev fallback: clearly marked console log.
    print(
        "[emailer:console-fallback — NOT really sent]\n"
        f"To: {to}\nFrom: {EMAIL_FROM}\nSubject: {subject}\n\n{body_text}\n"
        "[end email]"
    )
    return False


def _parse_name_list(raw) -> list[str]:
    """Parse a JSON name-list column (removed/added ingredients) for display."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    return [str(n) for n in raw] if isinstance(raw, list) else []


def _removed_ingredient_lines(items) -> list[str]:
    """Per-item '⚠️ NO: ...' lines — kitchen-critical, must stand out."""
    lines = []
    for item in items or []:
        names = _parse_name_list(getattr(item, "removed_ingredients", None))
        if names:
            lines.append(f"  ⚠️ NO: {', '.join(names)}  ({item.dish_name})")
    return lines


def send_order_confirmation(order, to_email: str | None = None, to_name: str | None = None) -> bool:
    """Order-placed confirmation to the customer.

    to_email/to_name override the account holder — used for guest checkout
    (guest orders have no customer account).
    """
    customer = order.customer
    to = to_email if to_email is not None else (customer.email if customer else "")
    customer_name = to_name if to_name is not None else (customer.name if customer else "there")
    vendor_name = order.vendor.name if order.vendor else "your vendor"
    lines = [
        f"Hi {customer_name},",
        "",
        f"Thanks for your order #{order.id} from {vendor_name} — we've got it!",
        "",
    ]
    for item in order.items or []:
        mod = f" ({item.modifier_label})" if getattr(item, "modifier_label", None) else ""
        lines.append(f"  • {item.quantity}× {item.dish_name}{mod} — ${float(item.unit_price):.2f}")
    no_lines = _removed_ingredient_lines(order.items)
    if no_lines:
        lines += ["", *no_lines]
    lines += [
        "",
        f"Subtotal: ${float(order.subtotal):.2f}",
    ]
    if float(getattr(order, "discount_amount", 0) or 0) > 0:
        lines.append(
            f"Promo {getattr(order, 'promo_code', '') or ''}: -${float(order.discount_amount):.2f}"
        )
    if float(getattr(order, "points_discount", 0) or 0) > 0:
        lines.append(f"Points redeemed: -${float(order.points_discount):.2f}")
    if float(order.delivery_fee or 0) > 0:
        lines.append(f"Delivery fee: ${float(order.delivery_fee):.2f}")
    lines.append(f"Tax: ${float(order.tax or 0):.2f}")
    lines.append(f"Total: ${float(order.total):.2f}")
    lines.append(f"Payment: {order.payment_method} (recorded)")
    # For Zelle/Venmo the customer pays the vendor directly — spell out where
    # the money should go. Cash/card orders keep the plain recorded line above.
    vendor = order.vendor
    pm = (order.payment_method or "").lower()
    if pm == "zelle" and vendor and vendor.zelle_handle:
        lines.append(f"Send ${float(order.total):.2f} to: {vendor.zelle_handle}")
    elif pm == "venmo" and vendor and vendor.venmo_handle:
        lines.append(f"Send ${float(order.total):.2f} to: {vendor.venmo_handle}")
    if order.fulfillment == "pickup":
        lines.append(f"Pickup: {_pickup_time_text(order.pickup_at)}")
    else:
        lines.append(f"Delivery to: {order.delivery_address or ''}")
    if order.notes:
        lines.append(f"Your instructions: {order.notes}")
    lines += ["", "We'll email you every time your order status changes.", "", "Shukran! 🇪🇬", f"— {vendor_name}"]
    return send_email(to, f"Order #{order.id} confirmed — {vendor_name} ✅", "\n".join(lines))


def send_vendor_new_order_email(order) -> bool:
    """New-order notification to the vendor owner.

    Sent when a checkout completes so the kitchen knows what to prepare.
    Skips silently when the vendor has no owner or the owner has no email.
    Never raises — send_email() already swallows failures.
    """
    vendor = order.vendor
    owner = vendor.owner if vendor else None
    to = owner.email if owner and owner.email else ""
    if not to:
        print(f"[emailer] vendor #{vendor.id if vendor else '?'} has no owner email — new-order email skipped")
        return False
    vendor_name = vendor.name if vendor else "your shop"
    owner_name = owner.name if owner and owner.name else "there"
    customer = order.customer
    customer_name = (
        customer.name if customer
        else (getattr(order, "guest_name", None) or "a guest")
    )
    customer_phone = (
        (customer.phone if customer and customer.phone else "")
        or (getattr(order, "guest_phone", None) or "")
    )
    lines = [
        f"Hi {owner_name},",
        "",
        f"New order #{order.id} for {vendor_name} — please get cooking! 👨‍🍳",
        "",
        f"Customer: {customer_name}" + (f" ({customer_phone})" if customer_phone else ""),
    ]
    for item in order.items or []:
        mod = f" ({item.modifier_label})" if getattr(item, "modifier_label", None) else ""
        lines.append(f"  • {item.quantity}× {item.dish_name}{mod} — ${float(item.unit_price):.2f} each")
    no_lines = _removed_ingredient_lines(order.items)
    if no_lines:
        lines += ["", *no_lines]
    lines += [
        "",
        f"Subtotal: ${float(order.subtotal):.2f}",
    ]
    if float(order.delivery_fee or 0) > 0:
        lines.append(f"Delivery fee: ${float(order.delivery_fee):.2f}")
    lines.append(f"Tax: ${float(order.tax or 0):.2f}")
    lines.append(f"Total: ${float(order.total):.2f}")
    if order.fulfillment == "pickup":
        lines.append(f"Fulfillment: pickup — scheduled for {_pickup_time_text(order.pickup_at)}")
    elif order.fulfillment == "drop":
        # === Community drops (Oct 2026): don't fall through to the delivery line. ===
        lines.append(f"Fulfillment: community drop — {order.drop_label or ''}")
    else:
        lines.append(f"Fulfillment: delivery to {order.delivery_address or ''}")
    if order.notes:
        lines.append(f"Customer instructions: {order.notes}")
    lines += ["", "View it in the vendor portal → Orders.", "", "— Osiris Marketplace"]
    return send_email(
        to,
        f"🧾 New order #{order.id} — {customer_name} — {vendor_name}",
        "\n".join(lines),
    )


def send_verification_email(user, token: str) -> bool:
    """Welcome email carrying the account-verification link.

    Verifying is OPTIONAL: login and checkout work while unverified, because
    Resend may not be configured yet (console-fallback just logs the link).
    """
    to = user.email if user else ""
    name = user.name if user and user.name else "there"
    link = f"{_frontend_base()}/#/verify-email?token={token}"
    body = "\n".join(
        [
            f"Hi {name},",
            "",
            "Welcome to Osiris Marketplace! 🎉",
            "Please verify your email address by clicking this link:",
            "",
            f"    {link}",
            "",
            "Verifying is optional — you can order right away either way.",
            "It just keeps your account safer and lets us reach you about orders.",
            "",
            "— Osiris Marketplace",
        ]
    )
    return send_email(to, "Verify your email — Osiris Marketplace", body)


def send_order_status_update(order, old_status: str, new_status: str) -> bool:
    """Status-change notification to the customer."""
    customer = order.customer
    to = customer.email if customer else ""
    vendor_name = order.vendor.name if order.vendor else "your vendor"
    customer_name = customer.name if customer else "there"
    pretty = {"new": "confirmed ✅", "preparing": "being prepared 👨‍🍳",
              "ready": "ready 🎉", "on_the_way": "on its way to you 🛵",
              "completed": "completed — bil hana wil shifa! 😋",
              "cancelled": "cancelled"}.get(new_status, new_status)
    lines = [
        f"Hi {customer_name},",
        "",
        f"Your order #{order.id} from {vendor_name}: {pretty}.",
        "",
        f"Order total: ${float(order.total):.2f}",
    ]
    # === FEATURE 9: pickup-point card appended to the reminder ===
    if (order.fulfillment or "") == "pickup":
        lines += _pickup_card_lines(order.vendor)
    # === END FEATURE 9 ===
    lines += [
        "",
        "Shukran! 🇪🇬",
        f"— {vendor_name}",
    ]
    body = "\n".join(lines)
    return send_email(to, f"Order #{order.id}: {pretty}", body)


# === FEATURE 9: pickup-point card ===
def _pickup_card_lines(vendor) -> list[str]:
    """Vendor pickup-point card for emails: address, map link, instructions.

    Returns [] when the vendor set none of the fields — an empty card is
    never shown.
    """
    if vendor is None:
        return []
    addr = (getattr(vendor, "pickup_address", None) or "").strip()
    instr = (getattr(vendor, "pickup_instructions", None) or "").strip()
    map_url = (getattr(vendor, "pickup_map_url", None) or "").strip()
    if not (addr or instr or map_url):
        return []
    lines = ["", "📍 Pickup point:"]
    if addr:
        lines.append(f"  {addr}")
    if map_url:
        lines.append(f"  Map: {map_url}")
    if instr:
        lines.append(f"  {instr}")
    return lines
# === END FEATURE 9 ===


def send_password_reset(user, token: str) -> bool:
    """Password-reset email carrying the reset token.

    The customer frontend has in-memory JS routing (no deep links), so the
    email carries the token for the user to paste into the reset form.
    """
    to = user.email if user else ""
    name = user.name if user and user.name else "there"
    body = "\n".join(
        [
            f"Hi {name},",
            "",
            "We got a request to reset your marketplace password.",
            "Enter this code on the password-reset page (it expires in 1 hour):",
            "",
            f"    {token}",
            "",
            "If you didn't ask for this, just ignore this email.",
            "",
            "— Osiris Marketplace",
        ]
    )
    return send_email(to, "Reset your marketplace password", body)


def send_complaint_notification(to: str, reporter, complaint) -> bool:
    """Tell an admin a new support ticket was filed."""
    name = reporter.name if reporter and reporter.name else "Someone"
    body = "\n".join(
        [
            "A new support ticket needs your attention:",
            "",
            f"Ticket #{complaint.id} — {complaint.subject}",
            f"From: {name} ({reporter.email if reporter else '?'}, {reporter.role if reporter else '?'})",
            f"Category: {complaint.category}",
            *( [f"Order: #{complaint.order_id}"] if complaint.order_id else [] ),
            *( [f"Vendor ID: {complaint.vendor_id}"] if complaint.vendor_id else [] ),
            "",
            (complaint.message or "")[:1000],
            "",
            "Reply from the vendor portal → Support inbox.",
            "",
            "— Osiris Marketplace",
        ]
    )
    return send_email(to, f"[Support #{complaint.id}] {complaint.subject}", body)


def send_complaint_reply(to: str, reporter, complaint) -> bool:
    """Tell the reporter the admin answered their ticket."""
    name = reporter.name if reporter and reporter.name else "there"
    body = "\n".join(
        [
            f"Hi {name},",
            "",
            f"Update on your support ticket #{complaint.id} ({complaint.subject}):",
            "",
            (complaint.admin_reply or "")[:2000],
            "",
            f"Status: {complaint.status}",
            "",
            "If you need anything else, just send us another message from the Help page.",
            "",
            "— Osiris Marketplace",
        ]
    )
    return send_email(to, f"[Support #{complaint.id}] Update on your ticket", body)


def send_catering_notification(to: str, req) -> bool:
    """Tell an admin a new catering inquiry was submitted."""
    body = "\n".join(
        [
            "A new catering inquiry needs your attention:",
            "",
            f"Inquiry #{req.id} — {req.event_type} on {req.event_date}",
            f"Contact: {req.contact_name} ({req.phone}" + (f", {req.email}" if req.email else "") + ")",
            f"Location: {req.location}",
            f"Food wanted: {req.food_type}",
            *( [f"Guests: {req.guest_count}"] if req.guest_count else [] ),
            "",
            (req.notes or "")[:1000],
            "",
            "Work it from the vendor portal → Admin → Catering.",
            "",
            "— Osiris Marketplace",
        ]
    )
    return send_email(to, f"[Catering #{req.id}] {req.event_type} — {req.event_date}", body)
