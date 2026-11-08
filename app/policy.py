"""Pre-upload checks against YouTube's API limits and spam/metadata policies.

Each check returns {"level": "error"|"warn"|"info", "field": ..., "msg": ...}.
Errors block upload; warnings are things YouTube may penalise.
"""
import re
from collections import Counter
from datetime import timedelta

from .library import now_utc, parse_iso

HASHTAG_RE = re.compile(r"(?<!\w)#[\w؀-ۿ]+", re.UNICODE)
WORD_RE = re.compile(r"[a-zA-Z؀-ۿ']+")
STOPWORDS = set("""a an the and or but of to in on at for with is are was were be this that it its
i you he she we they my your our their me him her them so if as by from not no do does did just
have has had what when who why how all can will would one more most very really""".split())


def tags_char_count(tags: list[str]) -> int:
    # YouTube counts commas between tags and wraps multi-word tags in quotes.
    total = sum(len(t) + (2 if " " in t else 0) for t in tags)
    return total + max(len(tags) - 1, 0)


def _keyword_list_run(desc: str) -> int:
    """Longest run of consecutive short, punctuation-free lines (a pasted keyword list)."""
    best = run = 0
    for line in desc.splitlines():
        s = line.strip()
        if s and len(s.split()) <= 4 and not re.search(r"[.!?,:;…]", s) and not s.startswith("#"):
            run += 1
            best = max(best, run)
        elif s:
            run = 0
    return best


def check(meta: dict, duration: float | None = None, vertical: bool | None = None) -> list[dict]:
    out = []

    def add(level, field, msg):
        out.append({"level": level, "field": field, "msg": msg})

    title = (meta.get("title") or "").strip()
    desc = meta.get("description") or ""
    tags = [t for t in (meta.get("tags") or []) if t.strip()]

    # --- hard API limits ---
    if not title:
        add("error", "title", "Title is empty.")
    if len(title) > 100:
        add("error", "title", f"Title is {len(title)} characters; the limit is 100.")
    if len(desc) > 5000:
        add("error", "description", f"Description is {len(desc)} characters; the limit is 5000.")
    for field, text in (("title", title), ("description", desc)):
        if "<" in text or ">" in text:
            add("error", field, "YouTube rejects < and > in titles and descriptions.")
    tc = tags_char_count(tags)
    if tc > 500:
        add("error", "tags", f"Tags use {tc} of 500 characters.")
    if any(len(t) > 100 for t in tags):
        add("error", "tags", "A single tag is longer than 100 characters.")

    # --- spam & deceptive practices ---
    hashtags = HASHTAG_RE.findall(title + "\n" + desc)
    if len(hashtags) > 60:
        add("error", "description", f"{len(hashtags)} hashtags: over 60, YouTube ignores all of them.")
    elif len(hashtags) > 15:
        add("warn", "description", f"{len(hashtags)} hashtags. Over-tagging counts as spam; 3-5 is plenty.")
    elif not hashtags:
        add("info", "description", "No hashtags. Add 2-3 relevant ones (e.g. #shorts).")

    run = _keyword_list_run(desc)
    if run >= 8:
        add("error", "description",
            f"Looks like a pasted keyword list ({run} short lines in a row). "
            "YouTube's spam policy bans keyword stuffing in descriptions.")

    words = [w.lower() for w in WORD_RE.findall(title + " " + desc)]
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]
    if len(content) >= 40:
        word, n = Counter(content).most_common(1)[0]
        if n >= 8 and n / len(content) > 0.06:
            add("warn", "description", f'"{word}" repeats {n} times. Heavy repetition reads as keyword stuffing.')

    if len(tags) > 15:
        add("warn", "tags", f"{len(tags)} tags. Use a few accurate ones; tags matter little for ranking.")
    lowered = [t.lower() for t in tags]
    if len(set(lowered)) != len(lowered):
        add("warn", "tags", "Duplicate tags.")

    letters = [c for c in title if c.isalpha()]
    if len(letters) > 10 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        add("warn", "title", "Title is mostly CAPS. Reads as clickbait.")
    if re.search(r"[!?]{3,}", title):
        add("warn", "title", "Repeated !!! or ??? in the title reads as clickbait.")

    if desc and len(desc.strip()) < 30:
        add("info", "description", "Very short description. One or two real sentences help search.")
    if not desc.strip():
        add("warn", "description", "Description is empty.")

    # --- audience & disclosure ---
    if meta.get("made_for_kids"):
        add("info", "made_for_kids", "Made for kids: comments, notifications and the miniplayer get turned off.")

    # --- scheduling ---
    pub = parse_iso(meta.get("publish_at"))
    if meta.get("publish_at") and not pub:
        add("error", "publish_at", "Schedule time is not a valid date.")
    elif pub:
        if pub <= now_utc():
            add("error", "publish_at", "Schedule time is in the past.")
        elif pub <= now_utc() + timedelta(minutes=15):
            add("warn", "publish_at", "Schedule time is less than 15 minutes away; YouTube may reject it.")

    # --- Shorts format ---
    is_short = "#shorts" in (title + desc).lower()
    if duration is not None and is_short and duration > 180:
        add("warn", "file", f"Video is {duration:.0f}s; Shorts must be 3 minutes or less.")
    if vertical is False and is_short:
        add("warn", "file", "Video is not vertical or square, so it will not appear as a Short.")

    return out


def has_errors(results: list[dict]) -> bool:
    return any(r["level"] == "error" for r in results)
