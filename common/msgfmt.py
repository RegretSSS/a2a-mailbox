import re

HUB_FROM = "hub"

HEADER_RE = re.compile(r"^\[A2A\] from=(?P<from>\S+) id=(?P<msg_id>\S+)(?: ack=(?P<ack_id>\S+))?$")
ACTION_MARKERS = (
    "读", "写", "跑", "发", "回", "确认", "继续", "执行", "报告", "查", "修",
    "启动", "停止", "安装", "部署", "测试", "验证", "列出", "创建", "分析",
    "通知", "完成", "处理",
)
ACTION_VERBS_RE = re.compile(
    r"\b(go|run|read|write|send|reply|check|fix|start|report|list|create|install)\b",
    re.IGNORECASE,
)
REVIVAL_MARKERS = ("继续", "续传", "断点", "接续", "恢复", "revival", "resume", "续跑")
REPLY_RECEIPT_MARKERS = (
    "OK", "ok", "完成", "回函", "收到", "结果", "done", "Done", "success",
)
RECEIPT_BODY_MAX_CHARS = 32
REPLY_TAG = "[需回函]"
LEGACY_ACK_ACTION_PREFIX = "收到即调 mail_ack"
LEGACY_REPLY_HINT = "完成后用 mail_send 回函（in_reply_to 填本消息 id）"
HOP_WARNING_THRESHOLD = 32
INJECTION_SAFE_MAX = 400


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def capped_body(body: str, msg_id: str, overhead: int) -> str:
    budget = max(INJECTION_SAFE_MAX - overhead, 40)
    note = f"…\n(超长截断: 全文 mail_read {msg_id})"
    if utf16_length(body) <= budget:
        return body
    cut = 0
    total = 0
    for index, char in enumerate(body):
        width = 2 if ord(char) > 0xFFFF else 1
        if total + width > budget - utf16_length(note):
            break
        total += width
        cut = index + 1
    return f"{body[:cut]}…{note.split('…', 1)[1]}"


def has_actionable_directive(body: str) -> bool:
    if any(marker in body for marker in ACTION_MARKERS):
        return True
    return bool(ACTION_VERBS_RE.search(body))


def is_revival_request(body: str) -> bool:
    return any(marker in body for marker in REVIVAL_MARKERS)


def has_rebuild_clue(body: str) -> bool:
    return any("/" in token for token in body.split())


def is_reply_receipt(body: str) -> bool:
    if len(body) > RECEIPT_BODY_MAX_CHARS:
        return False
    return any(marker in body for marker in REPLY_RECEIPT_MARKERS)


def compose_wake(agent_id: str, msg_id: str, body: str, expect_reply: bool = False, cap_injection: bool = True) -> str:
    overhead = utf16_length(f"[A2A] from={agent_id} id={msg_id}\n") + (utf16_length(REPLY_TAG) + 1 if expect_reply else 0)
    injected = capped_body(body, msg_id, overhead) if cap_injection else body
    head = f"[A2A] from={agent_id} id={msg_id}\n{injected}"
    if expect_reply:
        return f"{head}\n{REPLY_TAG}"
    return head


def parse_wake(text: str):
    parts = text.strip().split("\n", 1)
    matched = HEADER_RE.match(parts[0])
    if not matched or len(parts) < 2:
        return None
    rest = parts[1]
    if rest.startswith(LEGACY_ACK_ACTION_PREFIX):
        rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    if rest.endswith(REPLY_TAG):
        rest = rest[: -len(REPLY_TAG)].rstrip("\n")
    elif rest.endswith(LEGACY_REPLY_HINT):
        rest = rest[: -len(LEGACY_REPLY_HINT)].rstrip("\n")
    body = rest.strip()
    if not body:
        return None
    ack_id = matched.group("ack_id") or f"ack-{matched.group('msg_id')}"
    return matched.group("from"), matched.group("msg_id"), ack_id, body
