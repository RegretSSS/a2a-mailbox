import ctypes
import gc
import threading
import time

TRIM_INTERVAL_SECONDS = 300.0

_lock = threading.Lock()
_last_trim_at = 0.0
_libc = None
_libc_resolved = False


def _resolve_libc():
    global _libc, _libc_resolved
    if _libc_resolved:
        return
    _libc_resolved = True
    try:
        candidate = ctypes.CDLL("libc.so.6", use_errno=True)
        if hasattr(candidate, "malloc_trim"):
            _libc = candidate
    except OSError:
        _libc = None


def trim_now() -> bool:
    global _last_trim_at
    with _lock:
        _resolve_libc()
        gc.collect()
        trimmed = False
        if _libc is not None:
            try:
                trimmed = bool(_libc.malloc_trim(0))
            except Exception:
                trimmed = False
        _last_trim_at = time.monotonic()
        return trimmed


def maybe_trim(now: float | None = None) -> None:
    moment = now if now is not None else time.monotonic()
    if moment - _last_trim_at < TRIM_INTERVAL_SECONDS:
        return
    trim_now()


def rss_mb() -> float:
    try:
        with open("/proc/self/statm") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * 4096 / 1024 / 1024
    except (OSError, ValueError, IndexError):
        return 0.0
