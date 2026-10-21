"""Shared image-upload plumbing: dish photos and review photos.

Uploaded files live under the frontend's /img tree so they are served by the
existing static mount (and get the /img/* cache headers).
photo_uploads.py -> app -> backend -> project root (3 parents).
Overridable via the UPLOAD_DIR env var (main.py warns when local disk is
used — it gets wiped on redeploy on ephemeral hosts).
"""
import io
import os
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

_DEFAULT_UPLOAD_DIR = (
    Path(__file__).resolve().parent.parent.parent / "frontend" / "img" / "uploads"
)
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", _DEFAULT_UPLOAD_DIR)).expanduser()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_PHOTO_SIDE = 1200  # downscale larger images
ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")

# v29 (Oct 2026): vendor intro + dish videos. User content — lives OUTSIDE
# the zips (documented in UPGRADE.md), so in-place upgrades never wipe it.
VIDEO_UPLOAD_DIR = UPLOAD_DIR / "videos"
VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_VIDEO_BYTES = 25 * 1024 * 1024  # 25 MB
_VIDEO_READ_CHUNK = 1024 * 1024  # 1 MB — cap enforced while reading
# ext -> (allowed content-types, magic-byte check)
_VIDEO_SPECS = {
    "mp4": (("video/mp4",), lambda b: len(b) >= 12 and b[4:8] == b"ftyp"),
    "webm": (("video/webm",), lambda b: b[:4] == b"\x1a\x45\xdf\xa3"),  # EBML header
}


def save_uploaded_video(file: UploadFile) -> str:
    """Validate an uploaded dish/intro video and store it; returns its
    /img/uploads/videos/* URL.

    mp4/webm ONLY: the extension, the content-type, AND the magic bytes
    ('ftyp' box for mp4, EBML header for webm) must all agree. The 25 MB cap
    is enforced while reading so a huge body never buffers unbounded.
    Raises HTTPException(400) on any validation failure.
    """
    filename = (file.filename or "").strip()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    spec = _VIDEO_SPECS.get(ext)
    if spec is None:
        raise HTTPException(status_code=400, detail="Only MP4 or WebM videos are allowed")
    allowed_ctypes, magic_ok = spec
    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype not in allowed_ctypes:
        raise HTTPException(
            status_code=400,
            detail=f"Content type {ctype or 'missing'} does not match a .{ext} video",
        )
    data = bytearray()
    while True:
        chunk = file.file.read(_VIDEO_READ_CHUNK)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_VIDEO_BYTES:
            raise HTTPException(status_code=400, detail="Video must be 25 MB or smaller")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if not magic_ok(bytes(data)):
        raise HTTPException(status_code=400, detail=f"File is not a valid .{ext} video")
    name = f"{uuid.uuid4().hex}.{ext}"
    (VIDEO_UPLOAD_DIR / name).write_bytes(bytes(data))
    return f"/img/uploads/videos/{name}"


def save_uploaded_photo(file: UploadFile) -> str:
    """Validate an uploaded image and store it; returns its /img/uploads/* URL.

    Raises HTTPException(400) on any validation failure. Shared by the dish
    photo endpoint and the review photo endpoint.
    """
    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or GIF images are allowed")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Image must be 5 MB or smaller")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))  # verify() closes the handle
        fmt = (img.format or "").upper()
        ext = ALLOWED_FORMATS.get(fmt)
        if not ext:
            raise ValueError("unsupported format")
    except Exception:
        raise HTTPException(status_code=400, detail="File is not a valid image")
    # Downscale very large photos so pages stay fast.
    if max(img.size) > MAX_PHOTO_SIDE:
        img.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE), Image.LANCZOS)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        data, ext = buf.getvalue(), "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    return f"/img/uploads/{name}"


def delete_uploaded_file(photo_url: str | None) -> None:
    """Remove an old /img/uploads/* file when a photo/video is replaced or
    removed. Video URLs (/img/uploads/videos/*) resolve into the videos
    subdir; everything else resolves into the upload root."""
    if not photo_url or not photo_url.startswith("/img/uploads/"):
        return
    root = (
        VIDEO_UPLOAD_DIR
        if photo_url.startswith("/img/uploads/videos/")
        else UPLOAD_DIR
    )
    target = (root / Path(photo_url).name).resolve()
    if target.parent == root.resolve():
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass


# Uploaded files are UUID-named (32 hex chars); only those are ever swept.
_ORPHAN_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp|gif)$")
_ORPHAN_VIDEO_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(mp4|webm)$")


def _sweep_dir(dir_path, root, referenced, name_re):
    """Sweep one upload dir: delete UUID-named files nothing references.

    Returns (deleted, kept). Every deletion is traversal-checked.
    """
    deleted = kept = 0
    for path in dir_path.iterdir():
        if not path.is_file() or not name_re.match(path.name):
            kept += 1
            continue
        if path.name in referenced:
            kept += 1
            continue
        try:
            if path.resolve().parent == root:
                path.unlink()
                deleted += 1
            else:
                kept += 1
        except OSError:
            kept += 1
    return deleted, kept


def sweep_orphan_uploads(db: Session) -> dict:
    """Delete /img/uploads/* files that no dish, review, or video field references.

    Covers the uploads root (images: dish/review photo_urls) and the videos
    subdir (dish.video_url + vendor.intro_video_url). Only UUID-named files
    are candidates — anything else (e.g. a .gitkeep) is left alone. Every
    deletion is traversal-checked. Returns {"deleted": n, "kept": m}.
    P1-3 (2026-10-15 audit); review-photo references added Oct 2026;
    video sweep added Oct 2026 (P2).
    """
    import json as _json

    from . import models as _m

    referenced = {
        Path(url).name
        for url in db.scalars(select(_m.Dish.photo_url)).all()
        if url and url.startswith("/img/uploads/")
    }
    for raw in db.scalars(select(_m.Review.photo_urls)).all():
        if not raw:
            continue
        try:
            urls = _json.loads(raw)
        except (ValueError, TypeError):
            continue
        for url in urls or []:
            if isinstance(url, str) and url.startswith("/img/uploads/"):
                referenced.add(Path(url).name)
    video_referenced = {
        Path(url).name
        for url in db.scalars(select(_m.Dish.video_url)).all()
        if url and url.startswith("/img/uploads/videos/")
    }
    for url in db.scalars(select(_m.Vendor.intro_video_url)).all():
        if url and url.startswith("/img/uploads/videos/"):
            video_referenced.add(Path(url).name)
    root = UPLOAD_DIR.resolve()
    deleted, kept = _sweep_dir(UPLOAD_DIR, root, referenced, _ORPHAN_NAME_RE)
    video_root = VIDEO_UPLOAD_DIR.resolve()
    if VIDEO_UPLOAD_DIR.is_dir():
        vd, vk = _sweep_dir(VIDEO_UPLOAD_DIR, video_root, video_referenced, _ORPHAN_VIDEO_NAME_RE)
        deleted += vd
        kept += vk
    return {"deleted": deleted, "kept": kept}
