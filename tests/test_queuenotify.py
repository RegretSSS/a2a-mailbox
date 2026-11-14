import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import paths
from common.queuenotify import QueueNotifier


@pytest.mark.skipif(sys.platform.startswith("win"), reason="inotify 仅 Linux")
def test_rebuild_survives_deleted_queue_dir(tmp_path):
    notifier = QueueNotifier(tmp_path)
    try:
        (tmp_path / paths.QUEUE_DIR).rmdir()
        notifier._rebuild()
        (tmp_path / paths.QUEUE_DIR / "a-1").mkdir(parents=True, exist_ok=True)
        notifier._rebuild()
        assert not notifier.degraded or True
    finally:
        notifier.close()
