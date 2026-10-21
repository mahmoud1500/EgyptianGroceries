"""Smart bilingual search (F4, Oct 2026).

Public GET /api/search?q= used by the website and mobile search boxes.
Typo-tolerant matching over dish name + description in English, Arabic
(normalized: diacritics/tatweel stripped, alef/hamza forms unified), and
common transliterations (a small built-in alias dictionary for common dish
terms). Dependency-free: normalized substring + token-prefix + a difflib
fuzzy fallback.

Every query that returns ZERO results is logged in the SearchQuery table;
the vendor portal's "What customers searched for" panel aggregates the top
zero-result queries from the last 7 days (global, no per-vendor attribution
in v1).
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db
from ..ratelimit import check_rate_limit
from .dishes import _attach_ingredient_options, _attach_options, _attach_ratings

router = APIRouter(prefix="/api/search", tags=["search"])

# --- Arabic normalization ------------------------------------------------
# Strip tashkeel (harakat) U+064B–U+0652, tatweel U+0640, unify alef forms
# (أ إ آ → ا), hamza-on-seat forms (ؤ → و, ئ → ي), alef maqsura (ى → ي),
# taa marbuta (ة → ه — the common search convention, e.g. مقلوبة↔مقلوبه).
_ALEF_RE = re.compile(r"[أإآا]")
_HAMZA_WAW_RE = re.compile(r"ؤ")
_HAMZA_YA_RE = re.compile(r"ئ")
_TASHKEEL_RE = re.compile(r"[\u064b-\u0652\u0640]")
_PUNCT_RE = re.compile(r"[^\w\s\u0600-\u06ff]", re.UNICODE)


def _normalize_arabic(text: str) -> str:
    t = text or ""
    t = _ALEF_RE.sub("ا", t)
    t = _HAMZA_WAW_RE.sub("و", t)
    t = _HAMZA_YA_RE.sub("ي", t)
    t = t.replace("ة", "ه").replace("ى", "ي")
    t = _TASHKEEL_RE.sub("", t)
    return t


def normalize(text: str) -> str:
    """Lowercase, Arabic-normalize, strip punctuation, collapse whitespace."""
    t = (text or "").strip().lower()
    t = _normalize_arabic(t)
    # NFKD strip of combining marks left over on latin text.
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = _PUNCT_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


# --- Transliteration alias dictionary -------------------------------------
# Each group lists equivalent ways to name one dish: common latin
# transliterations, the Arabic spelling, and the English menu wording.
# Matching is symmetric: searching for ANY term in a group also searches
# for every other term in that group.
TRANSLITERATION_GROUPS: list[list[str]] = [
    ["koshary", "koshari", "كشري"],
    ["mahshi", "محشي", "stuffed vegetables", "stuffed peppers"],
    ["warak enab", "warak eneb", "ورق عنب", "grape leaves", "stuffed grape leaves"],
    ["kibbeh", "kibbe", "كبه", "كبة"],
    ["sfiha", "sfeeha", "صفيحه", "صفيحة", "meat pie"],
    ["maqlouba", "maqluba", "maklouba", "مقلوبه", "مقلوبة", "upside down rice"],
    ["musakhan", "msakhan", "مسخن"],
    ["mansaf", "منسف"],
    ["freekeh", "frikeh", "فريكه", "فريكة"],
    ["ouzi", "oozi", "awzi", "اوزي", "أوزي"],
    ["yalanji", "yalangi", "يلنجي"],
    ["hawawshi", "hawawshi", "حواوشي"],
    ["molokhia", "mulukhiyah", "ملوخيه", "ملوخية", "jute mallow"],
    ["foul", "fool", "فول", "fava beans"],
    ["feteer", "fateer", "فطير"],
    ["tameya", "taameya", "tamia", "طعميه", "طعمية", "falafel"],
    ["bamya", "bamia", "باميه", "بامية", "okra"],
    ["mahshy", "محشي"],
    ["om ali", "umm ali", "ام علي", "أم علي", "bread pudding"],
]

# Pre-normalized term sets for fast expansion.
_NORM_GROUPS = [[normalize(term) for term in group] for group in TRANSLITERATION_GROUPS]


def _expand_query(qn: str) -> list[str]:
    """All search needles: the normalized query plus every alias-group term
    from groups where ANY term appears in the query."""
    needles = {qn} if qn else set()
    for group in _NORM_GROUPS:
        if any(term and (term in qn or qn in term and len(qn) >= 3) for term in group):
            needles.update(t for t in group if t)
    return sorted(needles, key=len, reverse=True)


_FUZZY_THRESHOLD = 0.62


def _match_score(qn: str, needles: list[str], haystack: str, name: str) -> int:
    """3 = normalized/alias substring, 2 = token-prefix, 1 = fuzzy, 0 = miss."""
    if qn and qn in haystack:
        return 3
    for needle in needles:
        if len(needle) >= 2 and needle in haystack:
            return 3
    hay_tokens = haystack.split()
    for needle in needles:
        for tok in needle.split():
            if len(tok) < 3:
                continue
            for ht in hay_tokens:
                if len(ht) >= 3 and (ht.startswith(tok) or tok.startswith(ht)):
                    return 2
    # Light fuzzy fallback on the dish NAME only (names are short and
    # distinctive; running it on long descriptions is noisy).
    if qn and len(qn) >= 4:
        if difflib.SequenceMatcher(None, qn, name).ratio() >= _FUZZY_THRESHOLD:
            return 1
    return 0


@router.get("", response_model=schemas.SearchOut)
def smart_search(
    request: Request,
    q: str = Query(default="", max_length=120),
    category: str | None = Query(default=None),
    vegetarian: bool | None = Query(default=None),
    vegan: bool | None = Query(default=None),
    available_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    caller: models.User | None = Depends(auth.get_optional_user),
):
    """Typo-tolerant bilingual dish search. Public; rate-limited."""
    check_rate_limit(request, "search", limit=60, window_seconds=60)
    raw = (q or "").strip()
    qn = normalize(raw)
    if not qn:
        return schemas.SearchOut(query=raw, hits=[])
    needles = _expand_query(qn)

    stmt = select(models.Dish)
    show_hidden = False
    if caller is not None:
        if caller.role == "admin":
            show_hidden = True
    if not show_hidden:
        stmt = stmt.where(models.Dish.is_hidden == False)  # noqa: E712
    if category:
        stmt = stmt.where(models.Dish.category == category)
    if vegetarian is not None:
        stmt = stmt.where(models.Dish.is_vegetarian == vegetarian)
    if vegan is not None:
        stmt = stmt.where(models.Dish.is_vegan == vegan)
    if available_only:
        stmt = stmt.where(models.Dish.available == True)  # noqa: E712
    dishes = list(db.scalars(stmt).all())

    scored: list[tuple[int, models.Dish]] = []
    for d in dishes:
        haystack = normalize(f"{d.name} {d.description or ''}")
        name = normalize(d.name)
        score = _match_score(qn, needles, haystack, name)
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: (-x[0], (x[1].name or "").lower()))

    matched = [d for _, d in scored]
    _attach_ratings(db, matched)
    _attach_options(db, matched)
    _attach_ingredient_options(db, matched)
    hits = [
        schemas.SearchHitOut(dish=schemas.DishOut.model_validate(d), score=s)
        for s, d in scored
    ]
    if not hits:
        # Zero results → log it so vendors can see what customers looked for.
        db.add(models.SearchQuery(query=raw[:120]))
        db.commit()
    return schemas.SearchOut(query=raw, hits=hits)


@router.get("/zero-results", response_model=list[schemas.ZeroResultQueryOut])
def zero_result_queries(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Top zero-result queries of the last 7 days (global aggregate, v1).
    Vendors use it for the "What customers searched for" panel; admins too."""
    if user.role not in ("vendor", "admin"):
        raise HTTPException(status_code=403, detail="Vendors and admins only")
    since = dt.datetime.utcnow() - dt.timedelta(days=7)
    rows = (
        db.execute(
            select(models.SearchQuery.query, func.count(models.SearchQuery.id).label("n"))
            .where(models.SearchQuery.created_at >= since)
            .group_by(models.SearchQuery.query)
            .order_by(func.count(models.SearchQuery.id).desc(), models.SearchQuery.query)
            .limit(30)
        ).all()
    )
    return [schemas.ZeroResultQueryOut(query=r[0], count=int(r[1])) for r in rows]
