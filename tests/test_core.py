from datetime import datetime, timedelta, timezone

from app import policy
from app.library import parse_legacy_txt
from app.schedule import next_slots

FUTURE = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")


def meta(**kw):
    base = {"title": "The Great Emu War", "description": "Australia lost a war to birds in 1932. #shorts #history",
            "tags": ["emu war", "history"], "made_for_kids": False, "publish_at": None}
    return {**base, **kw}


def levels(m, field=None):
    return {c["level"] for c in policy.check(m) if field is None or c["field"] == field}


def test_clean_meta_has_no_errors():
    assert "error" not in levels(meta())


def test_hard_limits():
    assert "error" in levels(meta(title=""), "title")
    assert "error" in levels(meta(title="x" * 101), "title")
    assert "error" in levels(meta(description="a <b> tag"), "description")
    assert "error" in levels(meta(tags=["word"] * 120), "tags")


def test_keyword_list_is_flagged():
    stuffed = "Real sentence here.\n\n" + "\n".join(f"funny meme {i}" for i in range(20))
    assert "error" in levels(meta(description=stuffed), "description")


def test_too_many_hashtags():
    many = " ".join(f"#tag{i}" for i in range(61))
    assert "error" in levels(meta(description=many), "description")
    some = " ".join(f"#tag{i}" for i in range(20))
    assert "warn" in levels(meta(description=some), "description")


def test_past_schedule_is_error():
    assert "error" in levels(meta(publish_at="2020-01-01T00:00:00Z"), "publish_at")
    assert "error" not in levels(meta(publish_at=FUTURE), "publish_at")


def test_tag_char_count_matches_youtube_rule():
    assert policy.tags_char_count(["ab", "c d"]) == 2 + 5 + 1


def test_slots_skip_taken_and_keep_local_hour():
    start = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)  # 07:00 New York
    first = next_slots(2, "America/New_York", ["15:00"], start=start)
    assert first == ["2026-11-09T20:00:00Z", "2026-11-10T20:00:00Z"]
    again = next_slots(1, "America/New_York", ["15:00"], taken=[first[0]], start=start)
    assert again == ["2026-11-10T20:00:00Z"]


def test_slots_follow_dst():
    start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    assert next_slots(1, "America/New_York", ["15:00"], start=start) == ["2026-07-01T19:00:00Z"]


def test_legacy_txt_drops_keyword_list(tmp_path):
    p = tmp_path / "v.txt"
    p.write_text("TITLE: Hi\nTAGS: a, b\nPUBLISH_AT: 2026-07-21 20:00\nDESCRIPTION:\nHello there.\n\n"
                 "RELATED SEARCHES\nmeme\nfunny\n", encoding="utf-8")
    m = parse_legacy_txt(p)
    assert m["title"] == "Hi" and m["tags"] == ["a", "b"]
    assert m["publish_at"] == "2026-07-21T20:00:00Z"
    assert "RELATED" not in m["description"] and m["description"] == "Hello there."
