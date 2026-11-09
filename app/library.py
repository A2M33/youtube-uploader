"""Video library: the videos folder, per-video metadata sidecars, upload state."""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
STATE_FILE = DATA_DIR / "state.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
THUMB_EXTS = (".jpg", ".jpeg", ".png")

DEFAULT_SETTINGS = {
    "videos_dir": "",  # empty = videos/ next to the app
    "channel_tz": "America/New_York",
    "slot_times": ["15:00"],
    "category_id": "1",  # Film & Animation
    "made_for_kids": False,
    "default_tags": [],
    "description_template": "{hook}\n\n{summary}\n\n#shorts",
    "notify_subscribers": True,
}

_lock = threading.RLock()


def _resolve_videos_dir() -> Path:
    """YT_UPLOADER_VIDEOS env var, then settings.videos_dir, then ./videos."""
    raw = os.environ.get("YT_UPLOADER_VIDEOS")
    if not raw:
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("videos_dir")
        except (FileNotFoundError, json.JSONDecodeError):
            raw = None
    p = Path(raw).expanduser() if raw else BASE / "videos"
    return p if p.is_absolute() else (BASE / p).resolve()


VIDEOS_DIR = _resolve_videos_dir()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------- settings ----------

def get_settings() -> dict:
    with _lock:
        return {**DEFAULT_SETTINGS, **_read_json(SETTINGS_FILE, {})}


def save_settings(new: dict) -> dict:
    with _lock:
        merged = {**get_settings(), **{k: v for k, v in new.items() if k in DEFAULT_SETTINGS}}
        _write_json(SETTINGS_FILE, merged)
        return merged


# ---------- state (upload status per video) ----------

def get_state() -> dict:
    with _lock:
        return _read_json(STATE_FILE, {})


def update_state(name: str, **fields) -> dict:
    with _lock:
        state = get_state()
        entry = {**state.get(name, {}), **fields}
        state[name] = entry
        _write_json(STATE_FILE, state)
        return entry


# ---------- metadata ----------

def video_path(name: str) -> Path:
    p = (VIDEOS_DIR / name).resolve()
    if p.parent != VIDEOS_DIR.resolve() or p.suffix.lower() not in VIDEO_EXTS:
        raise ValueError(f"bad video name: {name}")
    return p


def meta_path(name: str) -> Path:
    return video_path(name).with_suffix(".json")


def thumbnail_for(name: str) -> Path | None:
    stem = video_path(name).with_suffix("")
    for ext in THUMB_EXTS:
        p = stem.with_name(stem.name + ".thumb" + ext)
        if p.exists():
            return p
    return None


def blank_meta(name: str) -> dict:
    s = get_settings()
    return {
        "title": Path(name).stem,
        "description": "",
        "tags": list(s["default_tags"]),
        "category_id": s["category_id"],
        "made_for_kids": s["made_for_kids"],
        "synthetic_media": False,
        "privacy": "public",
        "publish_at": None,
        "notify_subscribers": s["notify_subscribers"],
    }


def parse_legacy_txt(txt: Path) -> dict:
    """Legacy .txt format: TITLE/TAGS/PUBLISH_AT header lines, then DESCRIPTION:."""
    text = txt.read_text(encoding="utf-8")
    meta = {}
    head, sep, desc = text.partition("DESCRIPTION:")
    if not sep:
        head, desc = "", text
    # The old generator appended a giant keyword list; drop it, it is spam by YouTube's rules.
    desc = desc.split("RELATED SEARCHES")[0]
    meta["description"] = desc.strip("\n").rstrip()
    for line in head.splitlines():
        key, _, val = line.partition(":")
        val = val.strip()
        if key == "TITLE" and val:
            meta["title"] = val
        elif key == "TAGS":
            meta["tags"] = [t.strip() for t in val.split(",") if t.strip()]
        elif key == "PUBLISH_AT" and val:
            try:
                dt = datetime.strptime(val, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                meta["publish_at"] = iso(dt)
            except ValueError:
                pass
    return meta


def get_meta(name: str) -> dict:
    with _lock:
        mp = meta_path(name)
        if mp.exists():
            return {**blank_meta(name), **_read_json(mp, {})}
        meta = blank_meta(name)
        legacy = mp.with_suffix(".txt")
        if legacy.exists():
            meta.update(parse_legacy_txt(legacy))
        return meta


def save_meta(name: str, meta: dict) -> dict:
    with _lock:
        allowed = blank_meta(name).keys()
        clean = {k: meta[k] for k in allowed if k in meta}
        merged = {**get_meta(name), **clean}
        _write_json(meta_path(name), merged)
        return merged


def list_videos() -> list[dict]:
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    state = get_state()
    out = []
    for p in sorted(VIDEOS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        st = state.get(p.name, {})
        out.append({
            "name": p.name,
            "size": p.stat().st_size,
            "added": iso(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)),
            "meta": get_meta(p.name),
            "has_thumbnail": thumbnail_for(p.name) is not None,
            "status": st.get("status", "draft"),
            "state": st,
        })
    return out
