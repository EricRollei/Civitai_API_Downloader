"""
Resumable, verified large-file transfer engine.

Why this exists
---------------
Civitai and Hugging Face both redirect model downloads to time-limited, signed
CDN URLs. A naive downloader (Chrome, a bare ``requests.get``) fails when the
connection hiccups, and then can't resume because the signed URL has expired.
This module wraps that whole dance:

    resolve()  -> follow the redirect ourselves (with auth) and get a bare
                  signed URL plus exact Content-Length
    download   -> aria2c (multi-connection, ``-c`` resume into a ``.part`` file)
                  or a pure-Python Range-request fallback
    on failure -> re-resolve a fresh signed URL and resume from where we were
    verify     -> size and SHA-256 when the source publishes them
    finish     -> atomic rename ``.part`` -> final name

Nothing ever lands at the final filename unless it is complete and verified,
so ``target.exists()`` can once again be trusted as "we have this file".
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import requests

LogFunc = Callable[[str], None]

PART_SUFFIX = ".part"
ARIA2_CONTROL_SUFFIX = ".aria2"

# Official aria2 Windows build. Pinned so the auto-fetch is deterministic.
ARIA2_VERSION = "1.37.0"
ARIA2_WIN64_URL = (
    f"https://github.com/aria2/aria2/releases/download/release-{ARIA2_VERSION}/"
    f"aria2-{ARIA2_VERSION}-win-64bit-build1.zip"
)

# Where a bundled aria2c.exe lives: <tool root>/bin/aria2c.exe
TOOL_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_BIN_DIR = TOOL_ROOT / "bin"

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_ARIA2_PROGRESS = re.compile(r"\[#\w+\s+(?P<done>[\d.]+\w*i?B?)/(?P<total>[\d.]+\w*i?B?)\((?P<pct>\d+)%\).*?DL:(?P<rate>[\d.]+\w*i?B?)(?:.*?ETA:(?P<eta>\S+))?")


class TransferError(RuntimeError):
    pass


class TransferCancelled(TransferError):
    pass


@dataclass
class TransferSettings:
    """User-tunable knobs. Mirrors the Settings tab."""

    use_aria2: bool = True
    aria2_path: str = ""          # explicit path to aria2c(.exe); empty = auto-detect
    connections: int = 8          # -x / -s for aria2
    auto_fetch_aria2: bool = True # download aria2 into bin/ if missing (Windows)
    max_rounds: int = 60          # outer resume loop cap
    stall_rounds: int = 8         # give up after this many consecutive rounds with zero progress
    retry_wait: float = 10.0      # seconds between rounds (backs off)


@dataclass
class ResolvedSource:
    """A concrete, ready-to-fetch URL plus what we know about the payload."""

    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    size: Optional[int] = None
    sha256: Optional[str] = None


# resolve_fn() must return a *fresh* ResolvedSource every time it is called.
ResolveFunc = Callable[[], ResolvedSource]


@dataclass
class TransferSpec:
    target: Path
    resolve: ResolveFunc
    display_name: str = ""
    expected_size: Optional[int] = None    # from the API (may be approximate, see size_tolerance)
    expected_sha256: Optional[str] = None
    size_tolerance: int = 0                # bytes of slack when expected_size is approximate (Civitai sizeKB)


@dataclass
class TransferResult:
    status: str        # "downloaded" | "skipped" | "failed"
    path: Path
    bytes: int = 0
    engine: str = ""
    message: str = ""


# --------------------------------------------------------------------------- #
# Redirect resolution
# --------------------------------------------------------------------------- #

def resolve_redirect(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
    max_hops: int = 6,
) -> ResolvedSource:
    """
    Follow redirects manually so the auth header only goes to the origin,
    never to the CDN (S3/R2-style signed URLs reject an extra Authorization
    header outright). Returns the final URL and, when the final hop answers
    with a Content-Length / ETag, the exact size and a sha256 if the ETag is one.

    The final request is a streamed GET (not HEAD) because some CDNs answer
    HEAD without Content-Length; the body is never read.
    """
    sess = session or requests.Session()
    current = url
    current_headers = dict(headers or {})
    hops = 0
    # Hugging Face puts the LFS sha256/size on the *redirect* response
    # (X-Linked-Etag / X-Linked-Size), so remember them across hops.
    linked_sha: Optional[str] = None
    linked_size: Optional[int] = None
    while True:
        try:
            response = sess.get(current, headers=current_headers, allow_redirects=False, stream=True, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            raise TransferError(f"Could not reach {current}: {exc}") from exc
        try:
            etag_linked = (response.headers.get("X-Linked-Etag") or "").strip().strip('"')
            if _HEX64.match(etag_linked):
                linked_sha = etag_linked.lower()
            size_linked = response.headers.get("X-Linked-Size")
            if size_linked and size_linked.isdigit():
                linked_size = int(size_linked)
            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise TransferError(f"Redirect from {current} without Location header")
                location = requests.compat.urljoin(current, location)
                hops += 1
                if hops > max_hops:
                    raise TransferError(f"Too many redirects resolving {url}")
                # Strip auth once we leave the origin host.
                if requests.compat.urlparse(location).netloc != requests.compat.urlparse(current).netloc:
                    current_headers.pop("Authorization", None)
                current = location
                continue
            if response.status_code in (401, 403):
                raise TransferError(
                    f"HTTP {response.status_code} for {url} - the file needs a login/API token "
                    "(early access, gated repo, or a missing/invalid key)."
                )
            if response.status_code == 404:
                raise TransferError(f"HTTP 404 for {url} - file not found")
            if response.status_code >= 400:
                raise TransferError(f"HTTP {response.status_code} for {url}")

            size: Optional[int] = linked_size
            length = response.headers.get("Content-Length")
            if length and length.isdigit():
                size = int(length)
            sha256: Optional[str] = linked_sha
            if sha256 is None:
                etag = (response.headers.get("ETag") or "").strip().strip('"')
                if _HEX64.match(etag):
                    sha256 = etag.lower()
            return ResolvedSource(url=current, headers=current_headers, size=size, sha256=sha256)
        finally:
            response.close()


# --------------------------------------------------------------------------- #
# aria2 discovery / bootstrap
# --------------------------------------------------------------------------- #

def _exe_name() -> str:
    return "aria2c.exe" if os.name == "nt" else "aria2c"


def find_aria2(explicit_path: str = "") -> Optional[str]:
    """Explicit setting > bundled bin/ > PATH."""
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if candidate.is_dir():
            candidate = candidate / _exe_name()
        if candidate.is_file():
            return str(candidate)
    bundled = BUNDLED_BIN_DIR / _exe_name()
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("aria2c")
    return found


def fetch_aria2_windows(log: LogFunc, *, session: Optional[requests.Session] = None) -> Optional[str]:
    """Download the official aria2 zip into bin/ and extract aria2c.exe. Windows only."""
    if os.name != "nt":
        return None
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        log("aria2 auto-fetch only supports 64-bit Windows; install aria2 manually.")
        return None
    BUNDLED_BIN_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = BUNDLED_BIN_DIR / f"aria2-{ARIA2_VERSION}.zip"
    sess = session or requests.Session()
    log(f"aria2 not found - fetching {ARIA2_WIN64_URL} …")
    try:
        with sess.get(ARIA2_WIN64_URL, stream=True, timeout=60) as response:
            response.raise_for_status()
            with open(zip_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if chunk:
                        handle.write(chunk)
        with zipfile.ZipFile(zip_path) as archive:
            member = next((m for m in archive.namelist() if m.lower().endswith("/aria2c.exe") or m.lower() == "aria2c.exe"), None)
            if member is None:
                raise TransferError("aria2c.exe not present in downloaded archive")
            with archive.open(member) as src, open(BUNDLED_BIN_DIR / "aria2c.exe", "wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception as exc:  # noqa: BLE001 - report and fall back to python engine
        log(f"aria2 auto-fetch failed ({exc}); using built-in downloader instead.")
        return None
    finally:
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
    exe = BUNDLED_BIN_DIR / "aria2c.exe"
    if exe.is_file():
        log(f"aria2 {ARIA2_VERSION} installed to {exe}")
        return str(exe)
    return None


def ensure_aria2(settings: TransferSettings, log: LogFunc) -> Optional[str]:
    if not settings.use_aria2:
        return None
    found = find_aria2(settings.aria2_path)
    if found:
        return found
    if settings.auto_fetch_aria2:
        return fetch_aria2_windows(log)
    return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def sha256_of(path: Path, *, cancel: Optional[threading.Event] = None, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise TransferCancelled("cancelled during hash")
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _size_matches(actual: int, expected: Optional[int], tolerance: int) -> bool:
    if expected is None:
        return True
    return abs(actual - expected) <= tolerance


def _part_path(target: Path) -> Path:
    return target.with_name(target.name + PART_SUFFIX)


def _cleanup_partial(part: Path) -> None:
    for candidate in (part, part.with_name(part.name + ARIA2_CONTROL_SUFFIX)):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Engines
# --------------------------------------------------------------------------- #

def _run_aria2_once(
    aria2: str,
    source: ResolvedSource,
    part: Path,
    *,
    connections: int,
    sha256: Optional[str],
    log: LogFunc,
    cancel: Optional[threading.Event],
    label: str,
) -> int:
    cmd = [
        aria2,
        "--continue=true",
        f"--max-connection-per-server={connections}",
        f"--split={connections}",
        "--min-split-size=10M",
        "--piece-length=1M",
        "--max-tries=5",
        "--retry-wait=10",
        "--timeout=60",
        "--connect-timeout=30",
        "--lowest-speed-limit=1K",
        "--file-allocation=none",
        "--auto-file-renaming=false",
        "--remote-time=true",
        "--console-log-level=warn",
        "--summary-interval=10",
        "--download-result=hide",
        "--show-console-readout=false",
        "--human-readable=true",
        "--check-certificate=true",
        f"--dir={part.parent}",
        f"--out={part.name}",
    ]
    if sha256:
        cmd.append(f"--checksum=sha-256={sha256}")
    for key, value in source.headers.items():
        cmd.append(f"--header={key}: {value}")
    cmd.append(source.url)

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=creationflags,
    )
    last_progress_log = 0.0
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                raise TransferCancelled("cancelled")
            text = line.strip()
            if not text:
                continue
            match = _ARIA2_PROGRESS.search(text)
            if match:
                now = time.monotonic()
                if now - last_progress_log >= 10:
                    last_progress_log = now
                    eta = f" ETA {match.group('eta')}" if match.group("eta") else ""
                    log(f"  {label}: {match.group('done')}/{match.group('total')} ({match.group('pct')}%) @ {match.group('rate')}/s{eta}")
                continue
            lowered = text.lower()
            if "error" in lowered or "warn" in lowered or "checksum" in lowered or "exception" in lowered:
                log(f"  aria2: {text[:300]}")
    finally:
        proc.wait()
    return proc.returncode


def _download_python_once(
    source: ResolvedSource,
    part: Path,
    *,
    log: LogFunc,
    cancel: Optional[threading.Event],
    label: str,
    session: requests.Session,
) -> bool:
    """Single sequential Range-resume attempt. Returns True if the stream ended normally."""
    existing = part.stat().st_size if part.exists() else 0
    headers = dict(source.headers)
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
    with session.get(source.url, headers=headers, stream=True, timeout=(30, 60)) as response:
        if existing > 0 and response.status_code == 416:
            # Range not satisfiable -> we already have everything (or more).
            return True
        if existing > 0 and response.status_code == 200:
            log(f"  {label}: server ignored resume request; restarting from 0")
            existing = 0
            mode = "wb"
        elif response.status_code == 206:
            mode = "ab"
        elif response.status_code == 200:
            mode = "wb"
        else:
            raise TransferError(f"HTTP {response.status_code} while downloading {label}")

        total: Optional[int] = None
        length = response.headers.get("Content-Length")
        if length and length.isdigit():
            total = int(length) + existing if mode == "ab" else int(length)

        done = existing
        last_log = time.monotonic()
        last_bytes = done
        with open(part, mode) as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                if cancel is not None and cancel.is_set():
                    raise TransferCancelled("cancelled")
                if not chunk:
                    continue
                handle.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last_log >= 10:
                    rate = (done - last_bytes) / (now - last_log)
                    pct = f" ({done * 100 // total}%)" if total else ""
                    log(f"  {label}: {_human(done)}/{_human(total) if total else '?'}{pct} @ {_human(rate)}/s")
                    last_log, last_bytes = now, done
        return True


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def download_file(
    spec: TransferSpec,
    settings: TransferSettings,
    log: LogFunc,
    *,
    cancel: Optional[threading.Event] = None,
    session: Optional[requests.Session] = None,
) -> TransferResult:
    """
    Download ``spec`` to ``spec.target`` with resume, retry and verification.

    Existing-file policy (cheap; no hashing of files already on disk):
      * final exists and size matches           -> skipped
      * final exists, size short                 -> treated as a sequential partial, resumed
      * final exists, size wrong the other way   -> deleted, re-downloaded
      * ``.part`` exists                         -> resumed
    """
    target = spec.target
    part = _part_path(target)
    label = spec.display_name or target.name
    sess = session or requests.Session()

    # First resolve: gives us the exact size when the CDN reports one.
    try:
        source = spec.resolve()
    except TransferError as exc:
        return TransferResult("failed", target, message=str(exc))

    expected_size = source.size if source.size is not None else spec.expected_size
    tolerance = 0 if source.size is not None else spec.size_tolerance
    expected_sha = (spec.expected_sha256 or source.sha256 or "").lower() or None

    if target.exists():
        actual = target.stat().st_size
        if _size_matches(actual, expected_size, tolerance):
            return TransferResult("skipped", target, bytes=actual, message="already present, size matches")
        if expected_size is not None and actual < expected_size and not part.exists():
            log(f"{label}: existing file is short ({_human(actual)} of {_human(expected_size)}) - resuming it")
            target.replace(part)
        else:
            log(f"{label}: existing file has wrong size ({_human(actual)} vs {_human(expected_size or 0)}) - re-downloading")
            target.unlink()
            _cleanup_partial(part)

    target.parent.mkdir(parents=True, exist_ok=True)

    aria2 = ensure_aria2(settings, log)
    engine = "aria2" if aria2 else "python"
    if part.exists():
        log(f"{label}: resuming from {_human(part.stat().st_size)} [{engine}]")
    else:
        size_note = f" ({_human(expected_size)})" if expected_size else ""
        log(f"{label}: starting download{size_note} [{engine}, {settings.connections if aria2 else 1} conn]")

    stalled = 0
    wait = settings.retry_wait
    last_size = part.stat().st_size if part.exists() else 0
    for round_no in range(1, settings.max_rounds + 1):
        if cancel is not None and cancel.is_set():
            return TransferResult("failed", target, engine=engine, message="cancelled")
        if round_no > 1:
            # Signed URL may have expired while we were down: always re-resolve.
            try:
                source = spec.resolve()
            except TransferError as exc:
                log(f"{label}: re-resolve failed ({exc}); waiting {wait:.0f}s")
                time.sleep(wait)
                wait = min(wait * 1.5, 120)
                continue
        try:
            if aria2:
                code = _run_aria2_once(
                    aria2, source, part,
                    connections=max(1, settings.connections),
                    sha256=expected_sha, log=log, cancel=cancel, label=label,
                )
                finished = code == 0
                if not finished:
                    log(f"{label}: aria2 exited with code {code} (round {round_no})")
            else:
                finished = _download_python_once(source, part, log=log, cancel=cancel, label=label, session=sess)
        except TransferCancelled:
            return TransferResult("failed", target, engine=engine, message="cancelled")
        except (TransferError, requests.exceptions.RequestException, OSError) as exc:
            finished = False
            log(f"{label}: {exc} (round {round_no})")

        current = part.stat().st_size if part.exists() else 0
        if finished:
            if expected_size is not None and not _size_matches(current, expected_size, tolerance):
                log(f"{label}: size mismatch after download ({current} vs {expected_size}); retrying")
                if current > expected_size:
                    _cleanup_partial(part)
                finished = False
            elif expected_sha and not aria2:
                # aria2 already verified via --checksum; python engine verifies here.
                log(f"{label}: verifying SHA-256 …")
                try:
                    actual_sha = sha256_of(part, cancel=cancel)
                except TransferCancelled:
                    return TransferResult("failed", target, engine=engine, message="cancelled")
                if actual_sha != expected_sha:
                    log(f"{label}: SHA-256 mismatch ({actual_sha[:12]}… vs {expected_sha[:12]}…); re-downloading")
                    _cleanup_partial(part)
                    finished = False
        if finished:
            os.replace(part, target)
            try:
                part.with_name(part.name + ARIA2_CONTROL_SUFFIX).unlink(missing_ok=True)
            except OSError:
                pass
            return TransferResult("downloaded", target, bytes=current, engine=engine)

        # Progress bookkeeping for stall detection.
        if current > last_size:
            stalled = 0
            wait = settings.retry_wait
        else:
            stalled += 1
            if stalled >= settings.stall_rounds:
                return TransferResult(
                    "failed", target, bytes=current, engine=engine,
                    message=f"no progress in {stalled} consecutive attempts; partial kept at {part.name}",
                )
        last_size = current
        log(f"{label}: retrying in {wait:.0f}s …")
        for _ in range(int(wait)):
            if cancel is not None and cancel.is_set():
                return TransferResult("failed", target, engine=engine, message="cancelled")
            time.sleep(1)
        wait = min(wait * 1.5, 120)

    return TransferResult("failed", target, bytes=last_size, engine=engine, message=f"gave up after {settings.max_rounds} rounds; partial kept at {part.name}")


def download_small(
    url: str,
    target: Path,
    *,
    headers: Optional[Dict[str, str]] = None,
    session: Optional[requests.Session] = None,
    attempts: int = 3,
    timeout: Tuple[int, int] = (20, 60),
) -> None:
    """
    For previews/images: plain streamed GET into ``.part`` then atomic rename,
    with a few retries. Keeps truncated images from ever sitting at the final name.
    """
    sess = session or requests.Session()
    part = _part_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            with sess.get(url, headers=headers or {}, stream=True, timeout=timeout) as response:
                if response.status_code >= 400:
                    raise TransferError(f"HTTP {response.status_code}")
                expected = response.headers.get("Content-Length")
                with open(part, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        if chunk:
                            handle.write(chunk)
            if expected and expected.isdigit() and part.stat().st_size != int(expected):
                raise TransferError(f"truncated ({part.stat().st_size}/{expected} bytes)")
            os.replace(part, target)
            return
        except (TransferError, requests.exceptions.RequestException, OSError) as exc:
            last_exc = exc
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 8))
    raise TransferError(f"Failed download {url}: {last_exc}")
