import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import msgfmt


def test_compose_parse_roundtrip():
    wake = msgfmt.compose_wake("claude-h-1", "m1", "去哪读: memory/MEMORY.md\n怎么续: 启动批B")
    parsed = msgfmt.parse_wake(wake)
    assert parsed == ("claude-h-1", "m1", "ack-m1", "去哪读: memory/MEMORY.md\n怎么续: 启动批B")


def test_wake_expect_reply_false_has_no_tail():
    wake = msgfmt.compose_wake("claude-h-1", "m1", "部署完成纯通知")
    assert wake == "[A2A] from=claude-h-1 id=m1\n部署完成纯通知"


def test_wake_expect_reply_true_adds_short_tag():
    wake = msgfmt.compose_wake("claude-h-1", "m1", "回函一句确认", expect_reply=True)
    assert wake == "[A2A] from=claude-h-1 id=m1\n回函一句确认\n[需回函]"
    parsed = msgfmt.parse_wake(wake)
    assert parsed == ("claude-h-1", "m1", "ack-m1", "回函一句确认")


def test_parse_strips_legacy_reply_hint_tail():
    legacy = (
        "[A2A] from=claude-h-1 id=m1 ack=ack-m1\n"
        "任务指令内容\n完成后用 mail_send 回函（in_reply_to 填本消息 id）"
    )
    assert msgfmt.parse_wake(legacy) == ("claude-h-1", "m1", "ack-m1", "任务指令内容")


def test_parse_rejects_header_without_body():
    assert msgfmt.parse_wake("[A2A] from=a id=b ack=c") is None


def test_parse_strips_legacy_ack_action_line():
    legacy = (
        "[A2A] from=claude-h-1 id=m1 ack=ack-m1\n"
        "收到即调 mail_ack(ack_id=ack-m1) 确认——本指令自包含, 无需读写任何文件\n"
        "去哪读: memory/MEMORY.md"
    )
    assert msgfmt.parse_wake(legacy) == ("claude-h-1", "m1", "ack-m1", "去哪读: memory/MEMORY.md")


def test_is_reply_receipt_short_confirmation_passes():
    assert msgfmt.is_reply_receipt("E2E-V2 pi 腿回函OK")


def test_is_reply_receipt_long_body_rejected():
    assert not msgfmt.is_reply_receipt("去哪读: memory/MEMORY.md 怎么续: 启动批B 这段足够长不应按回执豁免线索校验了")


def test_is_reply_receipt_no_receipt_marker_rejected():
    assert not msgfmt.is_reply_receipt("继续刚才的任务")


def test_parse_rejects_plain_text():
    assert msgfmt.parse_wake("hello\nworld") is None


def test_parse_v3_header_derives_ack_id():
    assert msgfmt.parse_wake("[A2A] from=a id=b\nbody") == ("a", "b", "ack-b", "body")


def test_clue_accepts_path_token():
    assert msgfmt.has_rebuild_clue("读 plans/next.md 后继续")


def test_clue_rejects_marker_without_path():
    assert not msgfmt.has_rebuild_clue("看 TaskList 逐项继续")
    assert not msgfmt.has_rebuild_clue("去哪读: DESIGN.md『实现骨架约定』节")


def test_clue_rejects_vague_body():
    assert not msgfmt.has_rebuild_clue("继续刚才的任务")


def test_actionable_directive_verbs_pass():
    assert msgfmt.has_actionable_directive("回函一句确认")
    assert msgfmt.has_actionable_directive("读一下状态报告")
    assert msgfmt.has_actionable_directive("install the package")


def test_actionable_directive_mood_words_rejected():
    assert not msgfmt.has_actionable_directive("嗯嗯")
    assert not msgfmt.has_actionable_directive("good morning everyone")


def test_revival_request_detection():
    assert msgfmt.is_revival_request("继续刚才的任务")
    assert msgfmt.is_revival_request("从断点恢复执行")
    assert not msgfmt.is_revival_request("回函一句确认")


def test_compose_wake_caps_long_body_with_read_hint():
    wake = msgfmt.compose_wake("claude-a-b-c", "6b5248d36385", "长" * 600, expect_reply=True)

    assert len(wake) <= msgfmt.INJECTION_SAFE_MAX
    assert "超长截断" in wake
    assert "mail_read 6b5248d36385" in wake
    assert wake.endswith("[需回函]")


def test_compose_wake_short_body_untouched():
    wake = msgfmt.compose_wake("claude-a", "6b5248d36385", "短消息", expect_reply=True)

    assert wake == "[A2A] from=claude-a id=6b5248d36385\n短消息\n[需回函]"
    assert "超长截断" not in wake


def test_compose_wake_uncapped_passes_full_body():
    body = "长" * 600
    wake = msgfmt.compose_wake("pi-a", "6b5248d36385", body, cap_injection=False)

    assert body in wake
    assert "超长截断" not in wake
