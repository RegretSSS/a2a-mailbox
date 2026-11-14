import base64
import json
import subprocess
import sys
from xml.sax.saxutils import escape

EVENT_LABELS = {
    "delivered": "投递成功",
    "ack-timeout": "回执超时",
    "agent-online": "agent 上线",
    "agent-offline": "agent 离线",
    "tool-silent": "工具面静默",
}
POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
TOAST_HEAD = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
    "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument;"
    "$xml.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('"
)
TOAST_TAIL = (
    "')));"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('A2A Mailbox').Show("
    "[Windows.UI.Notifications.ToastNotification]::new($xml))"
)
XML_TEMPLATE = (
    "<toast scenario='reminder'><visual><binding template='ToastGeneric'>"
    "<text>{title}</text><text>{body}</text></binding></visual></toast>"
)


def toast_xml(event: str, payload: dict) -> str:
    label = EVENT_LABELS.get(event, event)
    agent = str(payload.get("agent_id") or "")
    detail = payload.get("msg_id") or ""
    body = " ".join(part for part in (agent, str(detail)) if part)
    return XML_TEMPLATE.format(title=escape(f"A2A {label}"), body=escape(body or event))


def run_toast(xml: str) -> int:
    encoded = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    try:
        finished = subprocess.run(
            [POWERSHELL, "-NoProfile", "-Command", TOAST_HEAD + encoded + TOAST_TAIL],
            capture_output=True,
            timeout=15,
        )
    except Exception:
        return 1
    return finished.returncode


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        return 1
    event = str(payload.get("event") or "")
    if not event:
        return 1
    return run_toast(toast_xml(event, payload))


if __name__ == "__main__":
    sys.exit(main())
