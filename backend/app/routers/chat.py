"""SoukBot chat endpoint: Gemini-powered answers with rule-based fallback.

POST /api/chat {message, language} -> {reply, source}
- source="ai": Gemini answered (GEMINI_API_KEY is set and the call succeeded).
- source="rule": the frontend should use its local rule-based engine
  (key unset, or the Gemini call failed/timed out).

The API key is read ONLY from the GEMINI_API_KEY environment variable.
It is never accepted from the client, never logged, never stored anywhere.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit

router = APIRouter(tags=["chat"])

GEMINI_MODEL = "gemini-3.8-flash"  # 2.5-flash 404s for new API keys; Google points to 3.8-flash
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
MAX_MESSAGE_LEN = 1000
GEMINI_TIMEOUT_S = 15
_AR_RE = re.compile(r"[\u0600-\u06FF]")


def _menu_snapshot(db: Session) -> str:
    """Real vendor/dish data for grounding — the model may only use this."""
    vendors = db.scalars(select(models.Vendor).order_by(models.Vendor.id)).all()
    dishes = db.scalars(
        select(models.Dish)
        .where(models.Dish.available.is_(True))
        .order_by(models.Dish.vendor_id, models.Dish.name)
    ).all()
    vmap = {v.id: v.name for v in vendors}
    lines = ["VENDORS:"]
    for v in vendors:
        fee = float(v.delivery_fee or 0)
        line = f"- {v.name} ({v.area or 'local'}): fulfillment={v.fulfillment}, delivery fee ${fee:.2f}"
        if v.phone:
            line += f", phone {v.phone}"
        lines.append(line)
    lines.append("DISHES (name — price USD — vendor — category):")
    for d in dishes:
        lines.append(
            f"- {d.name} — ${float(d.price):.2f} — {vmap.get(d.vendor_id, '?')} — {d.category}"
        )
    return "\n".join(lines)


def _system_prompt(lang: str, menu: str) -> str:
    if lang == "ar":
        return (
            "أنت SoukBot، المساعد الودود لموقع Osiris، سوق للأكل البيتي المصري. "
            "الزباين بيسألوك عن المنيو وطريقة الطلب والاستلام والتوصيل والدفع.\n\n"
            "قواعد صارمة:\n"
            "- جاوب بس عن السوق. استخدم بس بيانات المنيو اللي تحت — ممنوع تخترع أطباق أو أسعار أو بائعين.\n"
            "- لو الإجابة مش في البيانات، قول إنك مش متأكد واقترح تصفح المنيو.\n"
            "- طريقة الطلب: ١) ضيف الأطباق للسلة ٢) عند إتمام الطلب اختار الاستلام (حدد معاد) أو التوصيل (اكتب عنوانك) وطريقة الدفع ٣) أكّد الطلب وتابعه من طلباتي.\n"
            "- الدفع: بطاقة عبر Stripe أو Zelle أو Venmo أو كاش. معظم البائعين استلام فقط.\n"
            "- إجابات قصيرة (٢-٤ جمل)، ودية، بالعربي المصري البسيط. الأسعار بالدولار.\n\n"
            f"بيانات المنيو:\n{menu}"
        )
    return (
        "You are SoukBot, the friendly assistant for Osiris, an Egyptian home-food marketplace. "
        "Customers ask you about the menu, ordering, pickup/delivery, and payments.\n\n"
        "STRICT RULES:\n"
        "- Answer ONLY about the marketplace. Use ONLY the menu data below — "
        "never invent dishes, prices, vendors, or offers.\n"
        "- If the answer isn't in the data, say you don't know and suggest browsing the menu.\n"
        "- Ordering: 1) add dishes to the cart, 2) at checkout choose pickup (pick a time) "
        "or delivery (enter your address) plus a payment method, 3) place the order and track it under My Orders.\n"
        "- Payments: credit card via Stripe, Zelle, Venmo, or cash. Most vendors are pickup-only.\n"
        "- Keep answers short (2-4 sentences), warm, conversational. Prices in USD.\n\n"
        f"MENU DATA:\n{menu}"
    )


def _ask_gemini(key: str, system: str, message: str) -> str | None:
    """Call Gemini; return the reply text, or None on any failure. The key is
    sent only in the x-goog-api-key header — never in the URL, never logged.
    One retry on 503 (transient capacity); everything else fails fast so the
    frontend can fall back to the rule-based engine."""
    import time
    import urllib.error

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": message}]}],
        "generationConfig": {"maxOutputTokens": 400, "temperature": 0.7},
    }
    for attempt in (1, 2):
        req = urllib.request.Request(
            GEMINI_URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt == 1:
                time.sleep(2)
                continue
            return None
        except Exception:
            return None
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip() or None
        except (KeyError, IndexError, TypeError, AttributeError):
            return None
    return None


@router.post("/api/chat", response_model=schemas.ChatOut)
def chat(payload: schemas.ChatIn, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request, "chat", limit=30, window_seconds=60)
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")
    if len(message) > MAX_MESSAGE_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Message is too long (max {MAX_MESSAGE_LEN} characters).",
        )
    lang = payload.language if payload.language in ("en", "ar") else None
    if lang is None:
        lang = "ar" if _AR_RE.search(message) else "en"
    # Key comes ONLY from the environment — never from the client.
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return schemas.ChatOut(reply=None, source="rule")
    reply = _ask_gemini(key, _system_prompt(lang, _menu_snapshot(db)), message)
    if not reply:
        return schemas.ChatOut(reply=None, source="rule")
    return schemas.ChatOut(reply=reply, source="ai")
