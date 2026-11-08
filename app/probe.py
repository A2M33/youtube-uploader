"""Read duration and frame size with ffprobe, if it is installed."""
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=512)
def _probe(path: str, mtime: float) -> dict | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=20, check=True).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        return {
            "duration": float(data.get("format", {}).get("duration") or 0) or None,
            "width": stream.get("width"),
            "height": stream.get("height"),
        }
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def probe(path: Path) -> dict | None:
    return _probe(str(path), path.stat().st_mtime)
