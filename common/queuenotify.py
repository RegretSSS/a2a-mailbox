import ctypes
import os
import select
import struct
from pathlib import Path

from common import paths

IN_CLOSE_WRITE = 0x08
IN_MOVED_TO = 0x80
IN_CREATE = 0x100
IN_IGNORED = 0x8000
IN_ISDIR = 0x40000000
WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_CREATE
ARRIVAL_MASK = IN_CLOSE_WRITE | IN_MOVED_TO
EVENT_STRUCT = struct.Struct("iIII")
EVENT_SIZE = EVENT_STRUCT.size
READ_CHUNK = 65536


class QueueNotifier:
    def __init__(self, root: Path):
        self.root = root
        self.queue_root = root / paths.QUEUE_DIR
        self.queue_root.mkdir(parents=True, exist_ok=True)
        self.watches: dict[int, str] = {}
        self.degraded = False
        if os.name == "nt":
            raise OSError("inotify 仅 Linux——Windows 节点走 SCAN_INTERVAL 轮询降级")
        libc = ctypes.CDLL(None, use_errno=True)
        self._init = libc.inotify_init1
        self._init.restype = ctypes.c_int
        self._init.argtypes = [ctypes.c_int]
        self._add = libc.inotify_add_watch
        self._add.restype = ctypes.c_int
        self._add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        fd = self._init(os.O_NONBLOCK | os.O_CLOEXEC)
        if fd < 0:
            raise OSError("inotify_init1 failed")
        self.fd = fd
        self._rebuild()

    def _watch(self, directory: Path) -> None:
        wd = self._add(self.fd, os.fsencode(directory), WATCH_MASK)
        if wd >= 0:
            self.watches[wd] = str(directory)

    def _rebuild(self) -> None:
        self.watches.clear()
        self._watch(self.root)
        self._watch_tree(self.queue_root)
        self.degraded = False

    def _watch_tree(self, directory: Path) -> None:
        self._watch(directory)
        for child in sorted(directory.iterdir()):
            if child.is_dir():
                self._watch_tree(child)

    def _drain(self) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        while True:
            try:
                data = os.read(self.fd, READ_CHUNK)
            except BlockingIOError:
                break
            if not data:
                break
            offset = 0
            while offset + EVENT_SIZE <= len(data):
                wd, mask, _cookie, name_len = EVENT_STRUCT.unpack_from(data, offset)
                offset += EVENT_SIZE
                raw_name = data[offset:offset + name_len]
                offset += name_len
                if mask & IN_IGNORED:
                    self.watches.pop(wd, None)
                    self.degraded = True
                    continue
                directory = self.watches.get(wd)
                if directory is None:
                    continue
                name = raw_name.split(b"\x00", 1)[0].decode("utf-8", "replace")
                if mask & IN_ISDIR and mask & IN_CREATE and name:
                    self._watch(Path(directory) / name)
                if mask & ARRIVAL_MASK and not (mask & IN_ISDIR):
                    events.append((directory, name))
        return events

    def wait(self, timeout: float) -> list[tuple[str, str]]:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        return self._drain()

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            return
