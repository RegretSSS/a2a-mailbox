import os

if os.name == "nt":
    import msvcrt

    def lock_exclusive(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def lock_exclusive_blocking(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def lock_exclusive(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def lock_exclusive_blocking(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_EX)

    def unlock(handle) -> None:
        fcntl.flock(handle, fcntl.LOCK_UN)
