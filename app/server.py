"""Local web server for the uploader UI. Run: python -m app"""
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import library as lib
from . import youtube as yt
from .policy import check
from .probe import probe
from .schedule import next_slots

WEB_DIR = lib.BASE / "web"

app = FastAPI(title="YouTube Uploader")
uploader = yt.Uploader()
uploader.requeue_pending()


def _checks(name: str, meta: dict) -> list[dict]:
    info = probe(lib.video_path(name)) or {}
    w, h = info.get("width"), info.get("height")
    return check(meta, duration=info.get("duration"), vertical=(h >= w) if w and h else None)


def _video_or_404(name: str) -> Path:
    try:
        p = lib.video_path(name)
    except ValueError:
        raise HTTPException(400, "Bad file name")
    if not p.exists():
        raise HTTPException(404, "No such video")
    return p


def _safe(fn):
    """Turn Google/API errors into a readable 502 instead of a stack trace."""
    try:
        return fn()
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(502, yt._err_text(e))


# ---------- account ----------

@app.get("/api/status")
def status():
    auth = yt.auth_status()
    ch = None
    if auth["state"] == "connected":
        try:
            ch = yt.channel()
        except Exception as e:
            auth["error"] = yt._err_text(e)
    return {"auth": auth, "channel": ch, "quota_used": yt.quota_used(), "quota_limit": yt.DAILY_QUOTA,
            "paused": uploader.paused, "current": uploader.current, "videos_dir": str(lib.VIDEOS_DIR)}


@app.post("/api/auth/connect")
def auth_connect():
    if not yt.CLIENT_SECRET.exists():
        raise HTTPException(400, "credentials/client_secret.json is missing")
    yt.connect()
    return {"ok": True}


@app.post("/api/auth/disconnect")
def auth_disconnect():
    yt.disconnect()
    return {"ok": True}


# ---------- library ----------

@app.get("/api/videos")
def videos():
    items = lib.list_videos()
    for v in items:
        v["checks"] = _checks(v["name"], v["meta"])
        v["probe"] = probe(lib.video_path(v["name"]))
    return items


@app.post("/api/videos")
async def add_video(file: UploadFile):
    name = Path(file.filename or "").name
    try:
        dest = lib.video_path(name)
    except ValueError:
        raise HTTPException(400, "Only .mp4 / .mov / .webm / .mkv files")
    if dest.exists():
        raise HTTPException(409, f"{name} already exists")
    lib.VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"name": name}


@app.get("/api/videos/{name}/file")
def video_file(name: str):
    return FileResponse(_video_or_404(name))


@app.get("/api/videos/{name}/thumbnail")
def video_thumb(name: str):
    _video_or_404(name)
    t = lib.thumbnail_for(name)
    if not t:
        raise HTTPException(404)
    return FileResponse(t)


@app.post("/api/videos/{name}/thumbnail")
async def set_thumb(name: str, file: UploadFile):
    p = _video_or_404(name)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in lib.THUMB_EXTS:
        raise HTTPException(400, "Thumbnail must be JPG or PNG")
    old = lib.thumbnail_for(name)
    if old:
        old.unlink()
    dest = p.with_name(p.stem + ".thumb" + ext)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    if dest.stat().st_size > 2 * 1024 * 1024:
        dest.unlink()
        raise HTTPException(400, "Thumbnail must be under 2 MB")
    return {"ok": True}


class Meta(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    category_id: str | None = None
    made_for_kids: bool | None = None
    synthetic_media: bool | None = None
    privacy: str | None = None
    publish_at: str | None = None
    notify_subscribers: bool | None = None


@app.put("/api/videos/{name}/meta")
def put_meta(name: str, meta: Meta):
    _video_or_404(name)
    if lib.get_state().get(name, {}).get("status") in ("uploading", "done"):
        raise HTTPException(409, "Already uploaded; edit it in YouTube Studio")
    data = meta.model_dump(exclude_unset=True)
    saved = lib.save_meta(name, data)
    return {"meta": saved, "checks": _checks(name, saved)}


@app.post("/api/videos/{name}/check")
def dry_check(name: str, meta: Meta):
    _video_or_404(name)
    merged = {**lib.get_meta(name), **meta.model_dump(exclude_unset=True)}
    return _checks(name, merged)


# ---------- queue ----------

class Names(BaseModel):
    names: list[str]


@app.post("/api/queue")
def queue_add(body: Names):
    for n in body.names:
        _video_or_404(n)
    uploader.enqueue(body.names)
    return {"ok": True}


@app.post("/api/queue/cancel")
def queue_cancel(body: Names):
    for n in body.names:
        uploader.cancel(n)
    return {"ok": True}


@app.post("/api/queue/retry")
def queue_retry(body: Names):
    for n in body.names:
        if lib.get_state().get(n, {}).get("status") == "failed":
            lib.update_state(n, status="draft", error=None)
    uploader.enqueue(body.names)
    return {"ok": True}


@app.post("/api/queue/resume")
def queue_resume():
    uploader.paused = False
    return {"ok": True}


# ---------- scheduling & insights ----------

@app.post("/api/schedule/auto")
def schedule_auto(body: Names):
    s = lib.get_settings()
    taken = [v["meta"]["publish_at"] for v in lib.list_videos()
             if v["meta"].get("publish_at") and v["name"] not in body.names]
    if yt.auth_status()["state"] == "connected":
        try:
            taken += [v["publish_at"] for v in yt.recent_uploads(50) if v.get("publish_at")]
        except Exception:
            pass  # offline planning still works from local data
    slots = next_slots(len(body.names), s["channel_tz"], s["slot_times"], taken)
    for name, slot in zip(body.names, slots):
        lib.save_meta(name, {"publish_at": slot})
    return dict(zip(body.names, slots))


@app.get("/api/schedule/next")
def schedule_next(count: int = 7):
    s = lib.get_settings()
    taken = [v["meta"]["publish_at"] for v in lib.list_videos() if v["meta"].get("publish_at")]
    return next_slots(count, s["channel_tz"], s["slot_times"], taken)


@app.get("/api/uploads")
def uploads():
    return _safe(lambda: yt.recent_uploads(30))


@app.get("/api/insights")
def insights():
    return _safe(lambda: yt.insights(lib.get_settings()["channel_tz"]))


@app.get("/api/settings")
def get_settings():
    return lib.get_settings()


@app.put("/api/settings")
def put_settings(body: dict):
    from zoneinfo import ZoneInfo
    if "channel_tz" in body:
        try:
            ZoneInfo(body["channel_tz"])
        except Exception:
            raise HTTPException(400, "Unknown time zone")
    if "slot_times" in body:
        try:
            next_slots(1, body.get("channel_tz", lib.get_settings()["channel_tz"]), body["slot_times"])
        except Exception:
            raise HTTPException(400, "Slot times must look like 15:00")
    return lib.save_settings(body)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
