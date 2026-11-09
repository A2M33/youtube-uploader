import json

import pytest

from app import cli
from app import library as lib


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(lib, "VIDEOS_DIR", videos)
    monkeypatch.setattr(lib, "DATA_DIR", data)
    monkeypatch.setattr(lib, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(lib, "SETTINGS_FILE", data / "settings.json")
    return tmp_path


def run(capsys, *args):
    code = cli.main(list(args))
    return code, json.loads(capsys.readouterr().out)


def test_meta_imports_outside_file_with_sidecar(sandbox, capsys):
    src = sandbox / "elsewhere"
    src.mkdir()
    (src / "clip.mp4").write_bytes(b"x" * 10)
    (src / "clip.json").write_text(json.dumps({"title": "From sidecar"}), encoding="utf-8")
    code, res = run(capsys, "meta", str(src / "clip.mp4"), "--tags", "a, b")
    assert code == 0
    assert (lib.VIDEOS_DIR / "clip.mp4").exists()
    assert res["meta"]["title"] == "From sidecar" and res["meta"]["tags"] == ["a", "b"]


def test_check_reports_errors_with_exit_1(sandbox, capsys):
    (lib.VIDEOS_DIR / "v.mp4").write_bytes(b"x")
    code, res = run(capsys, "check", "v.mp4", "--title", "x" * 101)
    assert code == 1 and res["ok"] is False
    assert any(c["field"] == "title" and c["level"] == "error" for c in res["checks"])


def test_dry_run_with_auto_slot(sandbox, capsys):
    (lib.VIDEOS_DIR / "v.mp4").write_bytes(b"x")
    code, res = run(capsys, "upload", "v.mp4", "--title", "Real title",
                    "--description", "A real sentence about the video. #shorts",
                    "--publish-at", "auto", "--dry-run")
    assert code == 0 and res["dry_run"] is True
    assert res["meta"]["publish_at"].endswith("Z") and res["meta"]["privacy"] == "private"


def test_publish_at_needs_zone(sandbox, capsys):
    (lib.VIDEOS_DIR / "v.mp4").write_bytes(b"x")
    code, res = run(capsys, "meta", "v.mp4", "--publish-at", "2030-01-01T10:00")
    assert code == 1 and "time zone" in res["error"]
    code, res = run(capsys, "meta", "v.mp4", "--publish-at", "2030-01-01T10:00+03:30")
    assert code == 0 and res["meta"]["publish_at"] == "2030-01-01T06:30:00Z"


def test_uploaded_video_is_not_uploaded_twice(sandbox, capsys):
    (lib.VIDEOS_DIR / "v.mp4").write_bytes(b"x")
    lib.update_state("v.mp4", status="done", youtube_id="abc")
    code, res = run(capsys, "upload", "v.mp4", "--dry-run")
    assert code == 1 and res["youtube_id"] == "abc"
