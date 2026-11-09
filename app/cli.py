"""Command-line interface for scripts and AI agents.

Every command prints one JSON document to stdout. Progress and hints go to
stderr. Exit codes: 0 ok, 1 failed or blocked by checks, 2 setup or sign-in
needed, 3 YouTube quota used up.

    python -m app status
    python -m app upload path/to/video.mp4 --title "..." --description-file d.txt --publish-at auto
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import library as lib
from .policy import check, has_errors
from .probe import probe
from .schedule import next_slots

EXIT_OK, EXIT_FAIL, EXIT_SETUP, EXIT_QUOTA = 0, 1, 2, 3


def _blocked(st: dict) -> bool:
    """True if a video is uploaded or an upload is really in progress. An "uploading" entry with no
    youtube_id that started over 20 minutes ago is a dead run (process killed / network loss): allow a retry."""
    if st.get("status") == "done" or st.get("youtube_id"):
        return True
    if st.get("status") != "uploading":
        return False
    try:
        t0 = datetime.fromisoformat(str(st.get("started_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - t0).total_seconds() < 20 * 60


class CliError(Exception):
    def __init__(self, msg: str, code: int = EXIT_FAIL, **extra):
        super().__init__(msg)
        self.code = code
        self.extra = extra


def out(data) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------- helpers ----------

def _yt():
    """Import the YouTube module lazily so offline commands work without Google libs."""
    try:
        from . import youtube
    except ImportError as e:
        raise CliError(f"Google libraries missing ({e}). Run Install.bat or "
                       "pip install -r requirements.txt.", EXIT_SETUP)
    return youtube


def _require_connected(yt) -> None:
    st = yt.auth_status()["state"]
    if st == "no_client_secret":
        raise CliError(f"Missing {yt.CLIENT_SECRET}. A human must add a Google OAuth client "
                       "(Desktop type) there first.", EXIT_SETUP)
    if st != "connected":
        raise CliError("Not signed in to YouTube. Run: python -m app connect "
                       "(a human has to finish the Google sign-in in the browser).", EXIT_SETUP)


def _resolve(target: str, import_file: bool) -> str:
    """Turn a library name or a file path into a library name.
    Files outside the videos folder are copied in, along with a same-name .json
    sidecar and .thumb.jpg/.png if they sit next to the file."""
    p = Path(target).expanduser()
    if p.parent == Path(".") and not p.exists() and (lib.VIDEOS_DIR / p.name).exists():
        return p.name
    p = p.resolve()
    if not p.exists():
        if (lib.VIDEOS_DIR / Path(target).name).exists():
            return Path(target).name
        raise CliError(f"No such video: {target}")
    if p.suffix.lower() not in lib.VIDEO_EXTS:
        raise CliError(f"Not a video file ({', '.join(sorted(lib.VIDEO_EXTS))}): {target}")
    if p.parent == lib.VIDEOS_DIR.resolve():
        return p.name
    if not import_file:
        raise CliError(f"{target} is outside the videos folder ({lib.VIDEOS_DIR}).")
    dest = lib.VIDEOS_DIR / p.name
    if dest.exists():
        if dest.stat().st_size != p.stat().st_size:
            raise CliError(f"A different {p.name} already exists in {lib.VIDEOS_DIR}. Rename the file.")
        return p.name
    lib.VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    note(f"Copying {p.name} into {lib.VIDEOS_DIR}")
    shutil.copy2(p, dest)
    side = p.with_suffix(".json")
    if side.exists() and not dest.with_suffix(".json").exists():
        shutil.copy2(side, dest.with_suffix(".json"))
    for ext in lib.THUMB_EXTS:
        thumb = p.with_name(p.stem + ".thumb" + ext)
        if thumb.exists():
            shutil.copy2(thumb, dest.with_name(dest.stem + ".thumb" + ext))
            break
    return p.name


def _parse_when(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CliError(f"Bad --publish-at '{value}'. Use ISO 8601 with a zone, "
                       "e.g. 2026-11-20T20:00:00Z, or 'auto'.")
    if dt.tzinfo is None:
        raise CliError("--publish-at needs a time zone (Z or +hh:mm) so the time is unambiguous.")
    return lib.iso(dt)


def _auto_slot(names: list[str], online: bool) -> list[str]:
    s = lib.get_settings()
    taken = [v["meta"]["publish_at"] for v in lib.list_videos()
             if v["meta"].get("publish_at") and v["name"] not in names]
    if online:
        yt = _yt()
        if yt.auth_status()["state"] == "connected":
            try:
                taken += [v["publish_at"] for v in yt.recent_uploads(50) if v.get("publish_at")]
            except Exception as e:
                note(f"Could not read scheduled videos from YouTube ({e}); using local data only.")
    return next_slots(len(names), s["channel_tz"], s["slot_times"], taken)


def _meta_changes(a) -> dict:
    """Collect metadata flags into a dict of changes."""
    m = {}
    if a.meta_json:
        m.update(json.loads(Path(a.meta_json).read_text(encoding="utf-8")))
    if a.title is not None:
        m["title"] = a.title
    if a.description_file:
        m["description"] = Path(a.description_file).read_text(encoding="utf-8").strip()
    if a.description is not None:
        m["description"] = a.description
    if a.tags is not None:
        m["tags"] = [t.strip() for t in a.tags.split(",") if t.strip()]
    if a.category is not None:
        m["category_id"] = str(a.category)
    if a.kids is not None:
        m["made_for_kids"] = a.kids
    if a.ai_content is not None:
        m["synthetic_media"] = a.ai_content
    if a.notify is not None:
        m["notify_subscribers"] = a.notify
    if a.privacy:
        m["privacy"] = a.privacy
        m["publish_at"] = None
    if a.publish_at and a.publish_at != "auto":
        m["publish_at"] = _parse_when(a.publish_at)
        m["privacy"] = "private"
    return m


def _checks(name: str, meta: dict) -> list[dict]:
    info = probe(lib.video_path(name)) or {}
    w, h = info.get("width"), info.get("height")
    return check(meta, duration=info.get("duration"), vertical=(h >= w) if w and h else None)


def _apply(name: str, a, online: bool) -> dict:
    st = lib.get_state().get(name, {})
    if _blocked(st):
        raise CliError(f"{name} is already uploaded; edit it in YouTube Studio.",
                       youtube_id=st.get("youtube_id"))
    changes = _meta_changes(a)
    if a.publish_at == "auto":
        changes["publish_at"] = _auto_slot([name], online)[0]
        changes["privacy"] = "private"
    meta = lib.save_meta(name, changes) if changes else lib.get_meta(name)
    if a.thumbnail:
        src = Path(a.thumbnail)
        if src.suffix.lower() not in lib.THUMB_EXTS or src.stat().st_size > 2 * 1024 * 1024:
            raise CliError("Thumbnail must be a JPG or PNG under 2 MB.")
        old = lib.thumbnail_for(name)
        if old:
            old.unlink()
        dest = lib.video_path(name)
        shutil.copy2(src, dest.with_name(dest.stem + ".thumb" + src.suffix.lower()))
    return meta


def _video_info(v: dict) -> dict:
    st = v["state"]
    return {
        "name": v["name"],
        "status": v["status"],
        "title": v["meta"]["title"],
        "publish_at": v["meta"].get("publish_at"),
        "privacy": v["meta"].get("privacy"),
        "youtube_id": st.get("youtube_id"),
        "error": st.get("error"),
        "checks": _checks(v["name"], v["meta"]),
    }


# ---------- commands ----------

def cmd_status(a):
    s = lib.get_settings()
    info = {"videos_dir": str(lib.VIDEOS_DIR), "channel_tz": s["channel_tz"],
            "slot_times": s["slot_times"]}
    try:
        yt = _yt()
    except CliError as e:
        return {**info, "auth": "libraries_missing", "error": str(e)}
    auth = yt.auth_status()
    info.update(auth=auth["state"], quota_used=yt.quota_used(), quota_limit=yt.DAILY_QUOTA,
                uploads_left_today=(yt.DAILY_QUOTA - yt.quota_used()) // yt.COST["insert"])
    if auth["state"] == "connected":
        try:
            info["channel"] = yt.channel()
        except Exception as e:
            info["error"] = yt._err_text(e)
    return info


def cmd_connect(a):
    yt = _yt()
    if yt.auth_status()["state"] == "no_client_secret":
        _require_connected(yt)
    note("Opening Google sign-in in the browser. A human has to pick the channel and allow access "
         "(5 minute timeout).")
    try:
        yt.sign_in(on_url=lambda u: note(f"If no browser opened, visit:\n{u}"))
    except Exception as e:
        raise CliError(f"Sign-in failed: {e}", EXIT_SETUP)
    return {"ok": True, "channel": yt.channel()}


def cmd_list(a):
    vids = lib.list_videos()
    if not a.all:
        vids = [v for v in vids if v["status"] != "done"]
    return [_video_info(v) for v in vids]


def cmd_meta(a):
    name = _resolve(a.video, import_file=True)
    meta = _apply(name, a, online=False)
    return {"name": name, "meta": meta, "checks": _checks(name, meta)}


def cmd_check(a):
    name = _resolve(a.video, import_file=False)
    meta = {**lib.get_meta(name), **_meta_changes(a)}
    checks = _checks(name, meta)
    if has_errors(checks):
        raise CliError("Checks found errors.", name=name, checks=checks)
    return {"name": name, "ok": True, "checks": checks}


def cmd_schedule(a):
    names = [_resolve(v, import_file=True) for v in a.videos]
    for n in names:
        if _blocked(lib.get_state().get(n, {})):
            raise CliError(f"{n} is already uploaded.")
    slots = _auto_slot(names, online=True)
    for n, slot in zip(names, slots):
        lib.save_meta(n, {"publish_at": slot, "privacy": "private"})
    return [{"name": n, "publish_at": s} for n, s in zip(names, slots)]


def cmd_upload(a):
    yt = _yt()
    name = _resolve(a.video, import_file=True)
    if not a.dry_run:
        _require_connected(yt)
    meta = _apply(name, a, online=not a.dry_run)
    checks = _checks(name, meta)
    if has_errors(checks):
        raise CliError("Checks found errors; nothing was uploaded.", name=name, meta=meta, checks=checks)
    if a.dry_run:
        return {"name": name, "dry_run": True, "meta": meta, "checks": checks}

    lib.update_state(name, status="queued", error=None, progress=0)
    last = [-10.0]

    def progress(pct):
        if pct - last[0] >= 10 or pct >= 100:
            note(f"Uploading {name}: {pct:.0f}%")
            last[0] = pct

    try:
        st = yt.upload_video(name, on_progress=progress)
    except yt.QuotaExhausted as e:
        lib.update_state(name, status="failed", error=str(e))
        raise CliError(str(e), EXIT_QUOTA, name=name)
    except Exception as e:
        lib.update_state(name, status="failed", error=yt._err_text(e))
        raise CliError(f"Upload failed: {yt._err_text(e)}", name=name)
    vid = st["youtube_id"]
    return {
        "name": name,
        "youtube_id": vid,
        "url": f"https://youtu.be/{vid}",
        "studio_url": f"https://studio.youtube.com/video/{vid}/edit",
        "privacy": st.get("result_privacy"),
        "publish_at": st.get("result_publish_at"),
        "warnings": st.get("warnings", []),
    }


def cmd_uploads(a):
    yt = _yt()
    _require_connected(yt)
    return yt.recent_uploads(a.limit)


def cmd_slots(a):
    s = lib.get_settings()
    taken = [v["meta"]["publish_at"] for v in lib.list_videos() if v["meta"].get("publish_at")]
    return {"tz": s["channel_tz"], "slots": next_slots(a.count, s["channel_tz"], s["slot_times"], taken)}


# ---------- parser ----------

def _bool_pair(p, name, dest, help_on, help_off):
    g = p.add_mutually_exclusive_group()
    g.add_argument(f"--{name}", dest=dest, action="store_true", default=None, help=help_on)
    g.add_argument(f"--no-{name}", dest=dest, action="store_false", help=help_off)
    p.set_defaults(**{dest: None})


def _meta_flags(p, schedule=True):
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--description-file", help="read the description from a UTF-8 text file")
    p.add_argument("--tags", help="comma separated")
    p.add_argument("--category", help="YouTube category id, e.g. 1 Film & Animation, 23 Comedy, 27 Education")
    _bool_pair(p, "kids", "kids", "made for kids", "not made for kids")
    _bool_pair(p, "ai-content", "ai_content", "realistic AI-altered content (disclosure)",
               "no realistic AI-altered content")
    _bool_pair(p, "notify", "notify", "notify subscribers", "do not notify subscribers")
    p.add_argument("--privacy", choices=["public", "unlisted", "private"],
                   help="publish right away with this visibility (clears any schedule)")
    if schedule:
        p.add_argument("--publish-at", help="ISO 8601 time with zone, or 'auto' for the next free slot")
    else:
        p.set_defaults(publish_at=None)
    p.add_argument("--thumbnail", help="JPG/PNG under 2 MB")
    p.add_argument("--meta-json", help="JSON file with any of: title, description, tags, category_id, "
                                       "made_for_kids, synthetic_media, privacy, publish_at, notify_subscribers")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m app", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="start the web UI (default with no command)")
    sub.add_parser("status", help="sign-in state, channel, quota, videos folder").set_defaults(fn=cmd_status)
    sub.add_parser("connect", help="Google sign-in (needs a human in the browser)").set_defaults(fn=cmd_connect)

    p = sub.add_parser("list", help="videos in the library that are not uploaded yet")
    p.add_argument("--all", action="store_true", help="include uploaded videos")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("meta", help="show or set a video's metadata without uploading")
    p.add_argument("video", help="file path or name in the videos folder")
    _meta_flags(p)
    p.set_defaults(fn=cmd_meta)

    p = sub.add_parser("check", help="run the policy checks; flags are applied without saving")
    p.add_argument("video")
    _meta_flags(p, schedule=False)
    p.set_defaults(fn=cmd_check, thumbnail=None)

    p = sub.add_parser("upload", help="set metadata, check, upload and wait for the result")
    p.add_argument("video", help="file path or name in the videos folder")
    _meta_flags(p)
    p.add_argument("--dry-run", action="store_true", help="save metadata and run checks, do not upload")
    p.set_defaults(fn=cmd_upload)

    p = sub.add_parser("schedule", help="give videos the next free publish slots")
    p.add_argument("videos", nargs="+")
    p.set_defaults(fn=cmd_schedule)

    p = sub.add_parser("slots", help="next free publish slots")
    p.add_argument("--count", type=int, default=7)
    p.set_defaults(fn=cmd_slots)

    p = sub.add_parser("uploads", help="latest videos on the channel")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_uploads)
    return ap


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    a = build_parser().parse_args(argv)
    try:
        out(a.fn(a))
        return EXIT_OK
    except CliError as e:
        out({"ok": False, "error": str(e), **e.extra})
        return e.code
    except (OSError, ValueError, json.JSONDecodeError) as e:
        out({"ok": False, "error": f"{type(e).__name__}: {e}"})
        return EXIT_FAIL
