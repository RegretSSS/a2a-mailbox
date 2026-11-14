import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SPEC = importlib.util.spec_from_file_location(
    "win_toast", Path(__file__).resolve().parent.parent / "scripts" / "win-toast.py"
)
win_toast = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(win_toast)


def test_toast_xml_maps_event_labels():
    xml = win_toast.toast_xml("delivered", {"agent_id": "codex-h-2-ws", "msg_id": "m1"})
    assert "A2A 投递成功" in xml
    assert "codex-h-2-ws m1" in xml


def test_toast_xml_unknown_event_falls_back():
    xml = win_toast.toast_xml("mystery", {"agent_id": "a"})
    assert "A2A mystery" in xml


def test_run_toast_embeds_base64_utf8(monkeypatch):
    seen = {}

    class Finished:
        returncode = 0

    def fake_run(command, **kwargs):
        seen["command"] = command
        return Finished()

    monkeypatch.setattr(win_toast.subprocess, "run", fake_run)
    assert win_toast.run_toast("<toast><text>中文</text></toast>") == 0
    script = seen["command"][3]
    assert script.startswith(win_toast.TOAST_HEAD)
    assert script.endswith(win_toast.TOAST_TAIL)
    embedded = script[len(win_toast.TOAST_HEAD):-len(win_toast.TOAST_TAIL)]
    assert embedded.isascii()
    import base64

    assert base64.b64decode(embedded).decode("utf-8") == "<toast><text>中文</text></toast>"


def test_main_requires_event_on_stdin(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"read": lambda self: '{"event":""}'})())
    assert win_toast.main() == 1


def test_toast_xml_escapes_agent_controlled_text():
    hostile = {"agent_id": "a<b>&'\"", "msg_id": "<script>alert(1)</script>"}
    xml = win_toast.toast_xml("delivered", hostile)
    assert "<script>" not in xml and "</script>" not in xml
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in xml
    assert "&lt;b&gt;&amp;" in xml
