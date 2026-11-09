"""YouTube API: OAuth, channel info, upload worker, analytics insights."""
import queue
import socket
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import library as lib
from .policy import check, has_errors

CRED_DIR = lib.BASE / "credentials"
CLIENT_SECRET = CRED_DIR / "client_secret.json"
TOKEN_FILE = CRED_DIR / "token.json"
QUOTA_FILE = lib.DATA_DIR / "quota.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
DAILY_QUOTA = 10_000
COST = {"insert": 1600, "thumbnail": 50, "read": 1}
RETRIABLE_STATUS = {500, 502, 503, 504}
PACIFIC = ZoneInfo("America/Los_Angeles")  # YouTube quota resets at midnight Pacific

_auth = {"state": "idle", "error": None, "url": None}
_client_cache = {}


# ---------- quota bookkeeping (local estimate) ----------

def _quota_day() -> str:
    return datetime.now(PACIFIC).strftime("%Y-%m-%d")


def quota_used() -> int:
    return lib._read_json(QUOTA_FILE, {}).get(_quota_day(), 0)


def _spend(kind: str, n: int = 1) -> None:
    with lib._lock:
        data = lib._read_json(QUOTA_FILE, {})
        day = _quota_day()
        data = {day: data.get(day, 0) + COST[kind] * n}
        lib._write_json(QUOTA_FILE, data)


# ---------- auth ----------

def _load_creds():
    import google.oauth2.credentials
    from google.auth.transport.requests import Request
    if not TOKEN_FILE.exists():
        return None
    creds = google.oauth2.credentials.Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not set(SCOPES) <= set(creds.scopes or []):
        return None  # token from an older scope set (e.g. the legacy upload-only script)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                return None  # Testing-mode refresh tokens die after 7 days
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        else:
            return None
    return creds


def services():
    from googleapiclient.discovery import build
    creds = _load_creds()
    if not creds:
        raise RuntimeError("Not connected to YouTube.")
    key = creds.token
    if _client_cache.get("key") != key:
        _client_cache.update(
            key=key,
            yt=build("youtube", "v3", credentials=creds, cache_discovery=False),
            ya=build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False),
        )
    return _client_cache["yt"], _client_cache["ya"]


def auth_status() -> dict:
    if not CLIENT_SECRET.exists():
        return {"state": "no_client_secret", "error": None}
    if _auth["state"] == "connecting":
        return dict(_auth)
    return {"state": "connected" if _load_creds() else "disconnected", "error": _auth["error"]}


def sign_in(on_url=None) -> None:
    """Run the Google consent flow and save the token. Blocks until the user
    finishes in the browser (5 minute timeout). Raises on failure."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    class Flow(InstalledAppFlow):
        def authorization_url(self, **kw):
            url, state = super().authorization_url(**kw)
            _auth["url"] = url  # shown in the UI in case the browser didn't open
            if on_url:
                on_url(url)
            return url, state

    flow = Flow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, browser=_browser(),
                                  timeout_seconds=300, prompt="consent", access_type="offline")
    CRED_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    _client_cache.clear()
    _channel_cache.clear()


def connect() -> None:
    """Start sign_in() in a background thread (used by the web UI)."""
    if _auth["state"] == "connecting":
        return

    def run():
        try:
            sign_in()
            _auth.update(state="idle", error=None)
        except Exception as e:  # user closed the tab, timeout, denied, ...
            _auth.update(state="idle", error=str(e) or type(e).__name__)

    _auth.update(state="connecting", error=None, url=None)
    threading.Thread(target=run, daemon=True).start()


def _browser() -> str | None:
    """Prefer Chrome for the Google sign-in page (it holds the channel's Google session)."""
    import os
    import webbrowser
    for path in (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                 r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                 r"%LocalAppData%\Google\Chrome\Application\chrome.exe"):
        exe = os.path.expandvars(path)
        if os.path.exists(exe):
            webbrowser.register("chrome-local", None, webbrowser.BackgroundBrowser(exe))
            return "chrome-local"
    return None  # default browser


def disconnect() -> None:
    TOKEN_FILE.unlink(missing_ok=True)
    _client_cache.clear()
    _channel_cache.clear()


# ---------- channel ----------

_channel_cache = {}


def channel() -> dict | None:
    if _channel_cache.get("data"):
        return _channel_cache["data"]
    yt, _ = services()
    resp = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()
    _spend("read")
    items = resp.get("items") or []
    if not items:
        return None
    c = items[0]
    data = {
        "id": c["id"],
        "title": c["snippet"]["title"],
        "handle": c["snippet"].get("customUrl"),
        "avatar": c["snippet"]["thumbnails"]["default"]["url"],
        "subscribers": c["statistics"].get("subscriberCount"),
        "videos": c["statistics"].get("videoCount"),
        "uploads_playlist": c["contentDetails"]["relatedPlaylists"]["uploads"],
    }
    _channel_cache["data"] = data
    return data


def recent_uploads(limit: int = 50) -> list[dict]:
    """Latest channel videos with status and stats (scheduled ones included)."""
    yt, _ = services()
    ch = channel()
    if not ch:
        return []
    ids, token = [], None
    while len(ids) < limit:
        resp = yt.playlistItems().list(part="contentDetails", playlistId=ch["uploads_playlist"],
                                       maxResults=50, pageToken=token).execute()
        _spend("read")
        ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        token = resp.get("nextPageToken")
        if not token:
            break
    out = []
    for i in range(0, len(ids[:limit]), 50):
        resp = yt.videos().list(part="snippet,status,statistics,contentDetails",
                                id=",".join(ids[i:i + 50])).execute()
        _spend("read")
        for v in resp.get("items", []):
            out.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "published_at": v["snippet"]["publishedAt"],
                "privacy": v["status"]["privacyStatus"],
                "publish_at": v["status"].get("publishAt"),
                "views": int(v.get("statistics", {}).get("viewCount", 0)),
                "thumbnail": v["snippet"]["thumbnails"].get("medium", {}).get("url"),
            })
    return out


# ---------- insights: when to publish ----------

def insights(tz_name: str) -> dict:
    yt, ya = services()
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    result = {"tz": tz_name, "weekdays": [], "hours": [], "countries": [], "notes": []}

    rep = ya.reports().query(ids="channel==MINE", startDate=str(today - timedelta(days=90)),
                             endDate=str(today), metrics="views", dimensions="day").execute()
    by_wd = defaultdict(list)
    for day, views in rep.get("rows") or []:
        by_wd[datetime.strptime(day, "%Y-%m-%d").weekday()].append(views)
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    result["weekdays"] = [{"day": names[d], "avg_views": round(sum(v) / len(v), 1) if v else 0}
                          for d, v in ((d, by_wd.get(d, [])) for d in range(7))]

    rep = ya.reports().query(ids="channel==MINE", startDate=str(today - timedelta(days=90)),
                             endDate=str(today), metrics="views", dimensions="country",
                             sort="-views", maxResults=5).execute()
    result["countries"] = [{"country": c, "views": v} for c, v in rep.get("rows") or []]

    # Publish-hour performance: views in each video's first 7 days, grouped by
    # the local hour it went live. The API has no "when viewers are online" data.
    vids = [v for v in recent_uploads(40) if v["privacy"] == "public"]
    by_hour = defaultdict(list)
    for v in vids:
        pub = lib.parse_iso(v["published_at"])
        if not pub or pub.date() > today - timedelta(days=8):
            continue
        rep = ya.reports().query(ids="channel==MINE", startDate=str(pub.date()),
                                 endDate=str(pub.date() + timedelta(days=7)), metrics="views",
                                 filters=f"video=={v['id']}").execute()
        rows = rep.get("rows") or [[0]]
        by_hour[pub.astimezone(tz).hour].append(rows[0][0])
    result["hours"] = [{"hour": h, "videos": len(v), "avg_views_7d": round(sum(v) / len(v))}
                       for h, v in sorted(by_hour.items())]
    sample = sum(len(v) for v in by_hour.values())
    if sample < 8:
        result["notes"].append(
            f"Only {sample} videos old enough to compare. Keep the default slot until there are ~8+.")
    else:
        best = max(result["hours"], key=lambda r: r["avg_views_7d"] if r["videos"] >= 2 else -1)
        result["suggested_slot"] = f"{best['hour']:02d}:00"
    return result


# ---------- upload worker ----------

class Uploader:
    def __init__(self):
        self.q: "queue.Queue[str]" = queue.Queue()
        self.paused = False
        self.current = None
        threading.Thread(target=self._loop, daemon=True).start()

    def enqueue(self, names: list[str]) -> None:
        for n in names:
            st = lib.get_state().get(n, {})
            if st.get("status") in ("queued", "uploading", "done"):
                continue
            lib.update_state(n, status="queued", error=None, progress=0)
            self.q.put(n)

    def requeue_pending(self) -> None:
        """After a restart, put back anything that was queued or mid-upload."""
        for name, st in lib.get_state().items():
            if st.get("status") in ("queued", "uploading"):
                lib.update_state(name, status="draft")
                self.enqueue([name])

    def cancel(self, name: str) -> None:
        if lib.get_state().get(name, {}).get("status") == "queued":
            lib.update_state(name, status="draft")

    def _loop(self):
        while True:
            name = self.q.get()
            if lib.get_state().get(name, {}).get("status") != "queued":
                continue
            while self.paused:
                time.sleep(1)
            self.current = name
            try:
                upload_video(name)
            except QuotaExhausted as e:
                lib.update_state(name, status="failed", error=str(e))
                self.paused = True
            except Exception as e:
                lib.update_state(name, status="failed", error=_err_text(e))
            finally:
                self.current = None


def upload_video(name: str, on_progress=None) -> dict:
    """Upload one video from the library synchronously and return its final state entry."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    meta = lib.get_meta(name)
    problems = check(meta)
    if has_errors(problems):
        raise RuntimeError("Fix the errors first: " + "; ".join(
            p["msg"] for p in problems if p["level"] == "error"))
    if quota_used() + COST["insert"] > DAILY_QUOTA:
        raise QuotaExhausted("Daily API quota is used up; it resets at midnight Pacific time.")

    yt, _ = services()
    status = {
        "selfDeclaredMadeForKids": bool(meta["made_for_kids"]),
        "containsSyntheticMedia": bool(meta["synthetic_media"]),
    }
    if meta.get("publish_at"):
        status.update(privacyStatus="private", publishAt=meta["publish_at"])
    else:
        status["privacyStatus"] = meta.get("privacy") or "public"
    body = {
        "snippet": {
            "title": meta["title"].strip(),
            "description": meta["description"],
            "tags": [t for t in meta["tags"] if t.strip()],
            "categoryId": str(meta["category_id"]),
        },
        "status": status,
    }
    media = MediaFileUpload(str(lib.video_path(name)), chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media,
                             notifySubscribers=bool(meta.get("notify_subscribers", True)))
    lib.update_state(name, status="uploading", progress=0, started_at=lib.iso(lib.now_utc()))

    response, retry = None, 0
    while response is None:
        try:
            prog, response = req.next_chunk()
            if prog:
                pct = round(prog.progress() * 100, 1)
                lib.update_state(name, progress=pct)
                if on_progress:
                    on_progress(pct)
            retry = 0
        except HttpError as e:
            reason = _reason(e)
            if reason in ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded"):
                raise QuotaExhausted(f"YouTube refused the upload: {reason}.")
            if e.resp.status not in RETRIABLE_STATUS:
                raise
            retry = _backoff(name, retry, e)
        except (socket.error, ConnectionError, TimeoutError) as e:
            retry = _backoff(name, retry, e)
    _spend("insert")

    vid = response["id"]
    warnings = []
    got = response.get("status", {})
    wanted_public = meta.get("publish_at") or status["privacyStatus"] != "private"
    if wanted_public and got.get("privacyStatus") == "private" and not got.get("publishAt"):
        warnings.append("YouTube locked this video to Private. The API project needs to pass "
                        "the YouTube API audit before uploads can be public or scheduled.")

    thumb = lib.thumbnail_for(name)
    if thumb:
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
            _spend("thumbnail")
        except HttpError as e:
            warnings.append("Thumbnail not set: " + _err_text(e) +
                            " (custom thumbnails need a phone-verified channel).")

    return lib.update_state(name, status="done", progress=100, youtube_id=vid,
                            uploaded_at=lib.iso(lib.now_utc()),
                            result_privacy=got.get("privacyStatus"),
                            result_publish_at=got.get("publishAt"),
                            warnings=warnings, error=None)


class QuotaExhausted(Exception):
    pass


def _backoff(name: str, retry: int, err) -> int:
    retry += 1
    if retry > 8:
        raise err
    wait = min(2 ** retry, 60)
    lib.update_state(name, error=f"Network hiccup, retrying in {wait}s ({retry}/8)")
    time.sleep(wait)
    return retry


def _reason(e) -> str:
    try:
        return e.error_details[0].get("reason", "")
    except Exception:
        return ""


def _err_text(e) -> str:
    try:
        from googleapiclient.errors import HttpError
        if isinstance(e, HttpError):
            return f"{e.resp.status} {e._get_reason()}"
    except Exception:
        pass
    return str(e) or type(e).__name__
