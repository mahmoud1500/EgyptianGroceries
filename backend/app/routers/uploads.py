"""Video uploads for vendors (v29, Oct 2026).

POST /api/uploads/video (vendor auth): dish videos and vendor intro
videos — mp4/webm ONLY (extension + content-type + magic bytes must agree),
25 MB cap enforced while reading, UUID filenames under
frontend/img/uploads/videos/ (user content — excluded from the zips, see
UPGRADE.md). Returns {"url": "/img/uploads/videos/<uuid>.mp4"}.

Chef photos reuse the existing image endpoint
(POST /api/dishes/photo-upload) — no new endpoint needed.
"""
from fastapi import APIRouter, Depends, File, Request, UploadFile

from .. import auth, models
from ..photo_uploads import save_uploaded_video
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("/video")
def upload_video(
    request: Request,
    file: UploadFile = File(...),
    user: models.User = Depends(auth.require_vendor),
):
    """Upload a dish/intro video; returns the URL to store as video_url /
    intro_video_url. Same 20/hour-per-IP cap as dish photo uploads so a
    vendor can't fill the disk with unbounded 25 MB files."""
    check_rate_limit(request, "video_upload", limit=20, window_seconds=3600)
    return {"url": save_uploaded_video(file)}
