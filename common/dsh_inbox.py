import http.client
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import paths

RPC_TIMEOUT_SECONDS = 8.0
COOKIE_MAX_AGE_SECONDS = 29 * 24 * 3600.0
COOKIE_REFRESH_MARGIN_SECONDS = 48 * 3600.0


class InboxOutcome:
    __slots__ = ("ok", "session_id", "mode", "reason")

    def __init__(self, ok, session_id="", mode="", reason=""):
        self.ok = ok
        self.session_id = session_id
        self.mode = mode
        self.reason = reason


def hosts_dir(root: Path | None = None) -> Path:
    return (root or paths.mailbox_root()) / "dsh-hosts"


def token_path(agent_id: str, root: Path | None = None) -> Path:
    return hosts_dir(root) / f"{agent_id}.token"


def cookie_path(agent_id: str, root: Path | None = None) -> Path:
    return hosts_dir(root) / f"{agent_id}.cookie"


def call_rpc(url: str, cookie: str, endpoint: str, args: dict, rpc_id: str):
    envelope = {
        "type": "client-request",
        "rpcId": rpc_id,
        "method": endpoint,
        "payload": {"args": args},
    }
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=RPC_TIMEOUT_SECONDS)
    try:
        conn.request(
            "POST",
            f"/api/{endpoint}",
            body=json.dumps(envelope),
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        resp = conn.getresponse()
        status = resp.status
        payload = json.loads(resp.read())
    finally:
        conn.close()
    if status != 200:
        raise RuntimeError(f"{endpoint} 期望 200, 实得 {status}")
    result = payload.get("result") or {}
    if result.get("ok") is False:
        error = result.get("error") or {}
        raise RuntimeError(str(error.get("message") or endpoint))
    return result.get("value")


def exchange_cookie(url: str, token: str) -> str:
    parts = urlsplit(url)
    conn = http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=RPC_TIMEOUT_SECONDS)
    try:
        conn.request("GET", f"/connect?token={quote(token)}&interactions=none")
        resp = conn.getresponse()
        status = resp.status
        raw = resp.headers.get("Set-Cookie", "")
        resp.read()
    finally:
        conn.close()
    if status != 302:
        raise RuntimeError(f"connect 期望 302, 实得 {status}")
    pair, _, _ = raw.partition(";")
    name, sep, value = pair.partition("=")
    if not sep or not value:
        raise RuntimeError("connect 未下发 dsh-auth cookie")
    return f"{name}={value}"


def ensure_cookie(url: str, agent_id: str, now: float, root: Path | None = None) -> str:
    store = cookie_path(agent_id, root)
    try:
        age = now - store.stat().st_mtime
        if age < COOKIE_MAX_AGE_SECONDS - COOKIE_REFRESH_MARGIN_SECONDS:
            cached = store.read_text().strip()
            if cached:
                return cached
    except OSError:
        pass
    token = ""
    try:
        token = token_path(agent_id, root).read_text().strip()
    except OSError:
        pass
    if not token:
        raise RuntimeError(
            f"缺 launch token({token_path(agent_id, root)}), dsh host 启动脚本未写或已丢失"
        )
    cookie = exchange_cookie(url, token)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(cookie)
    return cookie


def win_shaped_cwd(value: str) -> bool:
    if value.startswith("\\\\wsl.localhost\\") or value.startswith("\\\\wsl$\\"):
        return True
    return len(value) >= 2 and value[1] == ":" and value[0].isascii() and value[0].isalpha()


def cwd_to_posix(value: str) -> str:
    slashed = value.replace("\\", "/").rstrip("/")
    lowered = slashed.lower()
    for prefix in ("//wsl.localhost/", "//wsl$/"):
        if lowered.startswith(prefix):
            parts = slashed.split("/", 4)
            return "/" + parts[4] if len(parts) == 5 else lowered
    if win_shaped_cwd(value):
        return "/mnt/" + slashed[0].lower() + slashed[2:]
    return slashed


def cwd_matches(session_cwd: str, record_cwd: str) -> bool:
    left = cwd_to_posix(session_cwd)
    right = cwd_to_posix(record_cwd)
    if left == right:
        return True
    if win_shaped_cwd(session_cwd) or win_shaped_cwd(record_cwd):
        return left.lower() == right.lower()
    return False


def pick_session(items, cwd: str):
    best = None
    best_updated = -1
    for item in items:
        if item.get("blank"):
            continue
        if cwd and not cwd_matches(str(item.get("cwd") or ""), cwd):
            continue
        updated = int(item.get("updatedAt") or 0)
        if updated > best_updated:
            best = item
            best_updated = updated
    return best


def enqueue(record: dict, msg_id: str, wake_text: str, now: float, root: Path | None = None) -> InboxOutcome:
    url = str(record.get("rpc_inbox_url") or "").rstrip("/")
    agent_id = str(record.get("agent_id") or "")
    if not url or not agent_id:
        return InboxOutcome(False, reason="档案缺 rpc_inbox_url")
    try:
        cookie = ensure_cookie(url, agent_id, now, root)
        value = call_rpc(url, cookie, "session/list", {"_request": {}}, "a2a-list")
        items = ((value or {}).get("items")) or []
        session = pick_session(items, str(record.get("cwd") or ""))
        if session is None:
            return InboxOutcome(False, reason="无 cwd 匹配的非空白会话")
        session_id = str(session.get("sessionId") or "")
        mode = "steer" if session.get("running") else "queue"
        request = {
            "requestId": f"a2a-{msg_id}",
            "sessionId": session_id,
            "mode": mode,
            "content": [{"type": "text", "text": str(wake_text or "")}],
        }
        call_rpc(url, cookie, "session/prompt", {"request": request}, "a2a-prompt")
        return InboxOutcome(True, session_id=session_id, mode=mode)
    except Exception as exc:
        return InboxOutcome(False, reason=str(exc))
