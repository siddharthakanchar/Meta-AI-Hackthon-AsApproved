"""Locating and driving ffmpeg.

ffmpeg is a hard dependency for video masters, for the 24 kHz PCM conversion
Voice Transcribe needs, and for trimming the demo recording. It is also the
dependency most likely to be "installed but not on PATH" — winget updates the
user PATH but every already-open shell keeps the old one.

So: resolve it rather than assume it, and look in the places a Windows install
actually puts it before giving up.
"""

from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

__all__ = ["ffmpeg_path", "ffprobe_path", "run_ffmpeg", "FFmpegMissing"]


class FFmpegMissing(RuntimeError):
    pass


def _winget_candidates(name: str) -> list[Path]:
    import os

    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    roots = [
        Path(local) / "Microsoft" / "WinGet" / "Links",
        Path(local) / "Microsoft" / "WinGet" / "Packages",
    ]
    found: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        direct = root / f"{name}.exe"
        if direct.exists():
            found.append(direct)
        # Gyan's build unpacks to ffmpeg-<version>-full_build/bin/
        found.extend(root.glob(f"**/bin/{name}.exe"))
    return found


@lru_cache(maxsize=4)
def _resolve(name: str) -> str | None:
    on_path = shutil.which(name)
    if on_path:
        return on_path
    for candidate in _winget_candidates(name):
        if candidate.exists():
            return str(candidate)
    return None


def ffmpeg_path(required: bool = True) -> str | None:
    path = _resolve("ffmpeg")
    if path is None and required:
        raise FFmpegMissing(
            "ffmpeg not found. Install it (`winget install Gyan.FFmpeg`) and open a new "
            "terminal so PATH refreshes, or put it on PATH manually."
        )
    return path


def ffprobe_path(required: bool = True) -> str | None:
    path = _resolve("ffprobe")
    if path is None and required:
        raise FFmpegMissing("ffprobe not found alongside ffmpeg.")
    return path


def run_ffmpeg(args: list[str], *, quiet: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg with the given arguments, raising with its stderr on failure."""
    cmd = [ffmpeg_path()]
    if quiet:
        cmd += ["-hide_banner", "-loglevel", "error"]
    cmd += ["-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{proc.stderr.strip()}")
    return proc
