import json
import os
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_json_atomic(path: Path, payload) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2))
