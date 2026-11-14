import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import agents as cli_agents
from common import codexq
from common import detect as cli_detect
from common import dsh_inbox
from common import federation, lockfile, msgfmt, nativebox, paths, peers as peers_store, queuenotify, registry, sshio, storage, tmuxio

SCAN_INTERVAL_SECONDS = 2.0
SLOW_INTERVAL_SECONDS = 5.0
SETTLE_SECONDS = 0.5
PANE_BOOT_SETTLE_SECONDS = 15.0
ACK_TIMEOUT_SECONDS = 120.0
FAILED_MORGUE_SECONDS = 7 * 86400.0
WIN_REANCHOR_WINDOW_SECONDS = 1800.0
QUEUE_DISPATCH_TIMEOUT_SECONDS = 20.0
SPAWN_ACK_TIMEOUT_SECONDS = 300.0
SPAWN_TIMEOUT_SECONDS = 600.0
NOTIFY_TIMEOUT_SECONDS = 8.0

STATE_SETTLING = "SETTLING"
STATE_INJECTING = "INJECTING"
STATE_WAIT_SPAWN_EXIT = "WAIT_SPAWN_EXIT"
STATE_WAIT_NATIVE = "WAIT_NATIVE"
STATE_WAIT_CONFIRM = "WAIT_CONFIRM"
STATE_WAIT_ACK = "WAIT_ACK"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"
STATE_QUEUE_RETRY = "QUEUE_RETRY"
QUEUE_RETRY_DELAY_SECONDS = 60.0
QUEUE_MAX_ATTEMPTS = 3
DELIVERY_ERROR_STRIKES = 3
DELIVERY_ERROR_RETRY_SECONDS = 60.0
RELAY_RETRY_SECONDS = 60.0
RELAY_GIVEUP_SECONDS = 1800.0
ACTIVE_TICK_SECONDS = 1.0
CONFIRM_PATIENCE_SECONDS = 1800.0
REMOTE_LIVENESS_SECONDS = 60.0
REINJECT_GUARD_SECONDS = 60.0
INJECTING_PATIENCE_SECONDS = 90.0
BUSY_TAIL_LINES = 6
INPUT_ZONE_LINES = 10
TOOL_SILENT_SECONDS = 900.0
REGISTRY_PRUNE_TTL = 1800.0
REGISTRY_PRUNE_REMOTE_TTL = REGISTRY_PRUNE_TTL * 4
PANELESS_ACTIVE_SECONDS = 600.0
FED_PULL_INTERVAL_SECONDS = 60.0
FED_PULL_NOW_FILENAME = "fed-pull-now"


class HubLog:
    def __init__(self, root: Path):
        self.root = root

    def write(self, line: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with (self.root / paths.LOG_FILE).open("a") as handle:
            handle.write(f"[{stamp}] {line}\n")


NOTIFY_CONFIG_WARNED = False


def load_notify_cmd(log=None) -> list[str]:
    global NOTIFY_CONFIG_WARNED
    try:
        config = json.loads((paths.mailbox_root() / "notify.json").read_text())
    except Exception as exc:
        if log is not None and not NOTIFY_CONFIG_WARNED:
            NOTIFY_CONFIG_WARNED = True
            log.write(f"notify.json 不可读({exc!r})——通知静默降级为关闭")
        return []
    cmd = config.get("cmd")
    if isinstance(cmd, list) and cmd and all(isinstance(item, str) for item in cmd):
        return cmd
    if log is not None and not NOTIFY_CONFIG_WARNED:
        NOTIFY_CONFIG_WARNED = True
        log.write("notify.json 缺合法 cmd 数组——通知静默降级为关闭")
    return []


HUB_LOCK_RETRY_SECONDS = 5.0
HUB_LOCK_RETRY_INTERVAL = 0.2


def acquire_hub_lock(root: Path):
    handle = open(root / paths.HUB_LOCK_FILE, "w")
    deadline = time.time() + HUB_LOCK_RETRY_SECONDS
    while True:
        try:
            lockfile.lock_exclusive(handle)
            return handle
        except OSError:
            if time.time() >= deadline:
                handle.close()
                return None
            time.sleep(HUB_LOCK_RETRY_INTERVAL)


IDLE_REAP_ENV = "A2A_HUB_IDLE_REAP"
IDLE_REAP_SECONDS = 3600.0


def idle_reap_due(root: Path, reg: dict, deliveries: dict, now: float, hub_started_at: float) -> bool:
    if os.environ.get(IDLE_REAP_ENV, "") != "1":
        return False
    if now - hub_started_at < IDLE_REAP_SECONDS:
        return False
    if deliveries:
        return False
    for record in reg["agents"].values():
        last_seen = storage.to_epoch(record.get("last_seen") or record.get("started_at"))
        if now - last_seen < IDLE_REAP_SECONDS:
            return False
    if any((root / paths.QUEUE_DIR).glob("*/*.msg")):
        return False
    try:
        heartbeat_age = now - (root / paths.MCP_HEARTBEAT_FILE).stat().st_mtime
    except OSError:
        return False
    return heartbeat_age >= IDLE_REAP_SECONDS


def notify(log, event: str, **fields) -> None:
    cmd = load_notify_cmd(log)
    if not cmd:
        return
    payload = json.dumps({"event": event, **fields}, ensure_ascii=False)
    NOTIFY_POOL.spawn(cmd, payload, event, log)


class NotifyPool:
    __slots__ = ("pending",)

    def __init__(self):
        self.pending = []

    def spawn(self, cmd, payload, event, log):
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as exc:
            log.write(f"notify {event} error: {exc}")
            return
        try:
            proc.stdin.write(payload.encode())
            proc.stdin.close()
        except Exception as exc:
            log.write(f"notify {event} stdin error: {exc}")
        self.pending.append((proc, event, time.time()))

    def reap(self, log, now):
        keep = 0
        total = len(self.pending)
        for slot in range(total):
            proc, event, started = self.pending[slot]
            code = proc.poll()
            if code is None:
                if now - started >= NOTIFY_TIMEOUT_SECONDS:
                    proc.terminate()
                    log.write(f"notify {event} terminated after {NOTIFY_TIMEOUT_SECONDS:g}s")
                self.pending[keep] = self.pending[slot]
                keep += 1
            elif code != 0:
                log.write(f"notify {event} exit={code}")
        del self.pending[keep:]


NOTIFY_POOL = NotifyPool()

HUB_FROM = msgfmt.HUB_FROM


def bounce_envelope(original: dict, reason: str, cap_injection: bool = True) -> dict:
    msg_id, ack_id = storage.new_ids()
    body = f"投递失败: {reason}——{original.get('msg_id')} → {original.get('to')} 未送达"
    wake_text = msgfmt.compose_wake(HUB_FROM, msg_id, body, cap_injection=cap_injection)
    return {
        "msg_id": msg_id,
        "ack_id": ack_id,
        "from": HUB_FROM,
        "to": str(original.get("from") or ""),
        "body": body,
        "context": f"delivery-failed reason={reason}",
        "in_reply_to": str(original.get("msg_id") or ""),
        "hop": 1,
        "created_at": time.time(),
        "wake_text": wake_text,
        "bounce": True,
    }


def enqueue_bounce(root: Path, log, original: dict, reason: str) -> None:
    sender = str(original.get("from") or "")
    if original.get("bounce") or not sender or sender == HUB_FROM:
        return
    sender_record = registry.get(root, sender) or {}
    storage.enqueue(
        root,
        bounce_envelope(
            original,
            reason,
            cap_injection=bool(cli_agents.spec_for(str(sender_record.get("cli") or "")).get("wake_cap")),
        ),
    )
    log.write(f"bounce {original.get('msg_id')} to={sender} reason={reason}")


DEREGISTERED_REASON = "recipient deregistered"


def relay_to_home(root: Path, log, agent_id: str, msg_id: str, record: dict, envelope: dict, now: float) -> None:
    alias = str(record.get("ssh_alias") or "")
    first = float(envelope.get("home_relay_first_at") or 0)
    if first > 0 and now - first >= RELAY_GIVEUP_SECONDS:
        storage.mark_failed(root, agent_id, msg_id)
        log.write(f"relay-giveup {msg_id} to={agent_id} home hub({alias}) 直投重试超 {RELAY_GIVEUP_SECONDS:g}s——回弹")
        notify(log, "delivery-failed", agent_id=agent_id, msg_id=msg_id, reason=f"home hub unreachable: {alias}")
        enqueue_bounce(root, log, envelope, f"home hub unreachable: {alias}")
        return
    if first <= 0 or now - float(envelope.get("home_relay_last_try") or 0) >= RELAY_RETRY_SECONDS:
        storage.stamp_home_relay(root, agent_id, msg_id, now)
        envelope["home_relay_first_at"] = first or now
        envelope["home_relay_last_try"] = now
    else:
        return
    status = sshio.write_remote_envelope(alias, envelope)
    if status == sshio.REMOTE_OK:
        storage.archive_msg(root, agent_id, msg_id)
        log.write(f"relayed {msg_id} to={agent_id} home hub({alias}) 直投入队成功, 本机副本归档")
        return
    log.write(f"relay-retry {msg_id} to={agent_id} home hub({alias}) 直投失败({status}), {RELAY_RETRY_SECONDS:g}s 后重试")


def home_peer_of(agent_id: str, known_peers: list[str]) -> str:
    parts = agent_id.split("-")
    if len(parts) < 2:
        return ""
    for peer in known_peers:
        if parts[1] == peer:
            return peer
    return ""


def settle_agent_mail(
    root: Path,
    log,
    agent_id: str,
    reason: str,
    deliveries: dict | None = None,
    record: dict | None = None,
) -> int:
    settled = 0
    home_hub = bool(record) and str(record.get("ssh_alias") or "")
    orphan_peer = "" if record else home_peer_of(agent_id, peers_store.load_peers(root))
    for envelope in storage.list_queue(root, agent_id):
        msg_id = envelope.get("msg_id")
        if not msg_id:
            continue
        if nativebox.rcpt_exists(root, agent_id, str(msg_id)):
            storage.archive_msg(root, agent_id, str(msg_id))
            log.write(
                f"receipt-held {msg_id} to={agent_id} 原生通道回执在案, 注销按已送达归档不回弹"
            )
            settled += 1
            continue
        if home_hub:
            log.write(f"relay-deferred {msg_id} to={agent_id} 锚齐收件人归 home hub 管辖, 移交直投链不回弹")
            relay_to_home(root, log, agent_id, str(msg_id), record, envelope, time.time())
            settled += 1
            continue
        if orphan_peer:
            log.write(f"relay-deferred {msg_id} to={agent_id} 孤儿信按 host 段归 home hub({orphan_peer}) 管辖, 移交直投链不回弹")
            relay_to_home(root, log, agent_id, str(msg_id), {"ssh_alias": orphan_peer}, envelope, time.time())
            settled += 1
            continue
        storage.mark_failed(root, agent_id, msg_id)
        notify(log, "delivery-failed", agent_id=agent_id, msg_id=msg_id, reason=reason)
        enqueue_bounce(root, log, envelope, reason)
        settled += 1
    if deliveries:
        for key in [key for key in deliveries if key.startswith(f"{agent_id}/")]:
            delivery = deliveries.pop(key)
            if delivery.spawn_proc is not None and delivery.spawn_proc.poll() is None:
                delivery.spawn_proc.terminate()
    return settled


class Delivery:
    __slots__ = (
        "envelope",
        "pane_id",
        "pane_created",
        "ssh_host",
        "spawn_cmd",
        "native",
        "queue_daemon",
        "rpc_inbox",
        "wake_cap",
        "state",
        "state_since",
        "injected_at",
        "ack_probe_lost_at",
        "busy_probe_at",
        "busy_probe_frame",
        "deferred",
        "echo_marker_text",
        "wake_head_text",
        "enter_stage",
        "enter_deadline",
        "enter_tail",
        "spawn_proc",
        "queue_proc",
        "queue_out_path",
        "wake_text_cache",
        "error_strikes",
        "next_tick_at",
    )

    def __init__(self, envelope: dict, now: float, pane_id: str = "", ssh_host: str = "", spawn_cmd=None, pane_created: float = 0.0, native: bool = False, queue_daemon: bool = False, rpc_inbox: bool = False, wake_cap: bool = False):
        self.envelope = envelope
        self.pane_id = pane_id
        self.pane_created = pane_created
        self.ssh_host = ssh_host
        self.spawn_cmd = spawn_cmd
        self.native = native
        self.queue_daemon = queue_daemon
        self.rpc_inbox = rpc_inbox
        self.wake_cap = wake_cap
        self.state = STATE_SETTLING
        self.state_since = now
        self.injected_at = 0.0
        self.ack_probe_lost_at = 0.0
        self.busy_probe_at = 0.0
        self.busy_probe_frame = ""
        self.deferred = 0
        self.echo_marker_text = ""
        self.wake_head_text = ""
        self.enter_stage = 0
        self.enter_deadline = 0.0
        self.enter_tail = ""
        self.spawn_proc = None
        self.queue_proc = None
        self.queue_out_path = ""
        self.wake_text_cache = ""
        self.error_strikes = 0
        self.next_tick_at = 0.0

    def finished(self) -> bool:
        return self.state in (STATE_DONE, STATE_FAILED, STATE_QUEUE_RETRY)

    def resume_after_injection(self, injected_at: float) -> None:
        self.state = STATE_WAIT_CONFIRM
        self.state_since = injected_at
        self.injected_at = injected_at

    def dispatch_native(self, root: Path, log, now: float) -> None:
        self.state = STATE_WAIT_CONFIRM
        self.state_since = now
        self.injected_at = now
        storage.stamp_injected(root, self.envelope["to"], self.envelope["msg_id"], now)
        log.write(f"injected {self.envelope['msg_id']} via=pi-native (扩展队列入队即送达, 等阅读回执)")

    def dispatch_rpc_inbox(self, root: Path, log, now: float, record: dict) -> bool:
        outcome = dsh_inbox.enqueue(
            record,
            str(self.envelope.get("msg_id") or ""),
            self.wake_text_resolved(),
            now,
            root,
        )
        if not outcome.ok:
            self.retry_or_giveup(root, log, now, f"rpc-inbox: {outcome.reason}")
            return False
        self.state = STATE_WAIT_CONFIRM
        self.state_since = now
        self.injected_at = now
        storage.stamp_injected(root, self.envelope["to"], self.envelope["msg_id"], now)
        log.write(
            f"injected {self.envelope['msg_id']} via=dsh-rpc"
            f" (session={outcome.session_id[:20]} mode={outcome.mode}, 入队即送达, 等阅读回执)"
        )
        return True

    def dispatch_queue_daemon(self, root: Path, log, now: float, record: dict) -> bool:
        thread_id = str(record.get("codex_thread") or "")
        fresh = codexq.locate_win(str(record.get("cwd") or ""))
        fresh_thread = str((fresh or {}).get("codex_thread") or "")
        if fresh and (
            fresh_thread != thread_id
            or str(fresh.get("codex_bin") or "") != str(record.get("codex_bin") or "")
            or str(fresh.get("codex_home") or "") != str(record.get("codex_home") or "")
        ):
            if fresh_thread:
                thread_id = fresh_thread
            record.update(fresh)
            updated = dict(record)
            registry.upsert(root, str(record.get("agent_id") or self.envelope["to"]), updated)
            log.write(
                f"queue-thread-reanchored {self.envelope['to']} -> {thread_id[:13]}"
                "(会话/安装已切换, 重锚最新 rollout 与 bin)"
            )
        proc, out_path = codexq.enqueue_async(
            str((fresh or {}).get("codex_bin") or record.get("codex_bin") or ""),
            Path(str((fresh or {}).get("codex_home") or record.get("codex_home") or "")),
            thread_id,
            self.wake_text_resolved(),
        )
        if proc is None:
            self.retry_or_giveup(root, log, now, "queue 命令拉起失败")
            return False
        self.queue_proc = proc
        self.queue_out_path = out_path
        self.state = STATE_WAIT_NATIVE
        self.state_since = now
        self.injected_at = now
        storage.stamp_injected(root, self.envelope["to"], self.envelope["msg_id"], now)
        log.write(f"injected {self.envelope['msg_id']} via=codex-queue (daemon 队列接管, 等回执)")
        return True

    def retry_or_giveup(self, root: Path, log, now: float, reason: str) -> None:
        self.cleanup_queue_proc()
        attempts = int(self.envelope.get("queue_attempts") or 0) + 1
        if attempts >= QUEUE_MAX_ATTEMPTS:
            self.native = False
            self.state = STATE_FAILED
            storage.mark_failed(root, self.envelope["to"], self.envelope["msg_id"])
            log.write(
                f"FAILED {self.envelope['msg_id']} to={self.envelope['to']} queue 通道 {attempts} 次尝试未成——回弹"
            )
            notify(
                log,
                "delivery-failed",
                agent_id=self.envelope["to"],
                msg_id=self.envelope["msg_id"],
                reason=f"queue retries exhausted: {reason}",
            )
            enqueue_bounce(root, log, self.envelope, f"queue retries exhausted: {reason}")
            return
        storage.stamp_queue_attempt(
            root,
            self.envelope["to"],
            self.envelope["msg_id"],
            now,
            QUEUE_RETRY_DELAY_SECONDS,
            attempts,
        )
        self.native = False
        self.state = STATE_QUEUE_RETRY
        log.write(
            f"queue-retry {self.envelope['msg_id']} to={self.envelope['to']} {reason}"
            f"——attempt {attempts}/{QUEUE_MAX_ATTEMPTS}, 滞留重试不降级 tmux"
        )

    def abort_error_loop(self, root: Path, log, exc: BaseException) -> None:
        to_id = str(self.envelope.get("to") or "")
        msg_id = str(self.envelope.get("msg_id") or "")
        self.state = STATE_FAILED
        if not (to_id and msg_id):
            return
        storage.mark_failed(root, to_id, msg_id)
        log.write(
            f"FAILED {msg_id} to={to_id} 连续 {DELIVERY_ERROR_STRIKES} 轮投递异常——回弹"
        )
        notify(
            log,
            "delivery-failed",
            agent_id=to_id,
            msg_id=msg_id,
            reason=f"delivery error loop: {exc!r}",
        )
        enqueue_bounce(root, log, self.envelope, f"delivery error loop: {exc!r}")

    def await_receipt(self, root: Path, log, now: float, reason: str) -> None:
        nativebox.write_rcpt(root, self.envelope["to"], self.envelope["msg_id"], now)
        log.write(
            f"receipt-assumed {self.envelope['msg_id']} to={self.envelope['to']} {reason}"
        )
        self.state = STATE_WAIT_CONFIRM
        self.state_since = now

    def collect_queue_daemon(self, root: Path, log, now: float) -> None:
        code = self.queue_proc.poll()
        if code is None:
            if now - self.injected_at >= QUEUE_DISPATCH_TIMEOUT_SECONDS:
                try:
                    self.queue_proc.terminate()
                except OSError:
                    pass
                self.retry_or_giveup(root, log, now, "queue 命令超时")
            return
        output = codexq.read_output(self.queue_out_path)
        self.cleanup_queue_proc()
        if code != 0:
            self.retry_or_giveup(root, log, now, f"queue 命令退出码 {code}")
            return
        queued_id = codexq.parse_queued_message(output)
        if not queued_id:
            self.await_receipt(root, log, now, "退出码 0 但回执不可读, 按 daemon 受理推定等确认")
            return
        nativebox.write_rcpt(
            root,
            self.envelope["to"],
            self.envelope["msg_id"],
            now,
        )
        log.write(
            f"receipt {self.envelope['msg_id']} to={self.envelope['to']} "
            f"echo={now - self.injected_at:.1f}s via=codex-queue queued={queued_id}"
        )
        self.state = STATE_WAIT_CONFIRM
        self.state_since = now

    def cleanup_queue_proc(self) -> None:
        if self.queue_proc is not None:
            try:
                self.queue_proc.wait(timeout=0)
            except Exception:
                pass
            self.queue_proc = None
        if self.queue_out_path:
            try:
                os.unlink(self.queue_out_path)
            except OSError:
                pass
            self.queue_out_path = ""

    def resume_queue_receipted(self, injected_at: float) -> None:
        self.state = STATE_WAIT_CONFIRM
        self.state_since = injected_at
        self.injected_at = injected_at

    def ack_arrived(self, root: Path) -> bool:
        if self.ssh_host:
            state = sshio.remote_ack_state(self.ssh_host, self.envelope["ack_id"])
            if state == sshio.REMOTE_ACK_UNREACHABLE:
                self.ack_probe_lost_at = time.monotonic()
                return False
            self.ack_probe_lost_at = 0.0
            return state == sshio.REMOTE_ACK_PRESENT
        return storage.ack_exists(root, self.envelope["ack_id"])

    def confirm_delivered(self, root: Path, log) -> None:
        storage.archive_msg(root, self.envelope["to"], self.envelope["msg_id"])
        self.state = STATE_DONE
        log.write(f"delivered {self.envelope['msg_id']} to={self.envelope['to']}")
        notify(log, "delivered", agent_id=self.envelope["to"], msg_id=self.envelope["msg_id"])

    def close_unconfirmed(self, root: Path, log) -> None:
        if self.envelope.get("expect_reply"):
            storage.mark_failed(root, self.envelope["to"], self.envelope["msg_id"])
            self.state = STATE_DONE
            log.write(
                f"reply-missing {self.envelope['msg_id']} to={self.envelope['to']} "
                "已回显未回函(expect_reply 超时), 留痕 .failed 供发送方查证"
            )
            notify(
                log,
                "reply-missing",
                agent_id=self.envelope["to"],
                msg_id=self.envelope["msg_id"],
                reason="expect_reply timeout",
            )
            return
        storage.archive_msg(root, self.envelope["to"], self.envelope["msg_id"])
        self.state = STATE_DONE
        log.write(
            f"unconfirmed {self.envelope['msg_id']} to={self.envelope['to']} "
            "receipt-only（管道已回显，未见回函/确认——通知类为正常终态）"
        )

    def echo_marker(self) -> str:
        if not self.echo_marker_text:
            self.echo_marker_text = str(self.envelope["msg_id"])
        return self.echo_marker_text

    def echo_frame(self, frames: dict | None) -> str:
        if frames is None:
            return tmuxio.capture_joined_bottom(self.pane_id, ssh_host=self.ssh_host or None)
        per_host = frames.get(self.ssh_host)
        if per_host is None:
            per_host = {}
            frames[self.ssh_host] = per_host
        frame = per_host.get(self.pane_id)
        if frame is None:
            frame = tmuxio.capture_joined_bottom(self.pane_id, ssh_host=self.ssh_host or None)
            per_host[self.pane_id] = frame
        return frame

    def tail_zone(self, frames: dict | None = None) -> str:
        lines = self.echo_frame(frames).rstrip("\n").split("\n")
        return "\n".join(lines[-INPUT_ZONE_LINES:]) if lines else ""

    def wake_head(self) -> str:
        if not self.wake_head_text:
            self.wake_head_text = self.wake_text_resolved().split("\n")[0][:24]
        return self.wake_head_text

    def wake_text_resolved(self) -> str:
        if not self.wake_text_cache:
            stored = str(self.envelope.get("wake_text") or "")
            if stored:
                self.wake_text_cache = stored
            else:
                self.wake_text_cache = msgfmt.compose_wake(
                    str(self.envelope.get("from") or ""),
                    str(self.envelope.get("msg_id") or ""),
                    str(self.envelope.get("body") or ""),
                    cap_injection=self.wake_cap,
                )
        return self.wake_text_cache

    def marker_in_tail(self, frames: dict | None = None) -> bool:
        tail = self.tail_zone(frames)
        if self.echo_marker() in tail:
            return True
        return bool(self.wake_head()) and self.wake_head() in tail

    def settle_injection(self, root: Path, log, now: float, frames: dict | None) -> None:
        held = self.marker_in_tail(frames)
        log.write(
            f"receipt {self.envelope['msg_id']} to={self.envelope['to']} "
            + (
                "via=tail-echo 注入文本驻留输入区(收件方忙碌排队)"
                if held
                else "via=enter-ladder pane 滚动未歇按铃未尽"
            )
            + ", 转耐心等待 ack/收尾"
        )
        self.state = STATE_WAIT_CONFIRM
        self.state_since = now

    def frame_tail(self, frames: dict | None) -> str:
        return "\n".join(self.echo_frame(frames).rstrip("\n").split("\n")[-BUSY_TAIL_LINES:])

    def fail(self, root: Path, log, reason: str, dump: str) -> None:
        if self.spawn_proc is not None and self.spawn_proc.poll() is None:
            self.spawn_proc.terminate()
        storage.mark_failed(root, self.envelope["to"], self.envelope["msg_id"])
        self.state = STATE_FAILED
        log.write(
            f"FAILED {self.envelope['msg_id']} to={self.envelope['to']} reason={reason}"
        )
        notify(log, "delivery-failed", agent_id=self.envelope["to"], msg_id=self.envelope["msg_id"], reason=reason)
        enqueue_bounce(root, log, self.envelope, reason)
        for line in dump.splitlines():
            log.write(f"  | {line[:120]}")

    def pane_occupied(self, now: float) -> bool:
        if not self.pane_id or self.spawn_cmd:
            return False
        ssh = self.ssh_host or None
        mark = tmuxio.quiet_mark(self.pane_id, ssh)
        if mark == "1":
            return True
        if mark == "0":
            return False
        if self.busy_probe_at == 0.0:
            self.busy_probe_frame = tmuxio.busy_probe_frame(self.pane_id, ssh)
            self.busy_probe_at = now
            return True
        first = self.busy_probe_frame
        self.busy_probe_frame = ""
        self.busy_probe_at = 0.0
        return tmuxio.frame_grew_since(first, self.pane_id, ssh)

    def defer_occupied(self, log, now: float) -> None:
        self.state = STATE_SETTLING
        self.state_since = now
        self.deferred += 1
        if self.deferred == 1:
            log.write(
                f"deferred {self.envelope['msg_id']} to={self.envelope['to']} "
                f"pane {self.pane_id} 底部字符增长/占用, 退让等空闲"
            )

    def inject_round(self, root: Path, log, now: float) -> None:
        if self.ack_arrived(root):
            self.confirm_delivered(root, log)
            return
        if self.ack_probe_lost_at:
            return
        if self.pane_occupied(now):
            self.defer_occupied(log, now)
            return
        if self.spawn_cmd:
            if not self.start_spawn(log):
                self.fail(root, log, "spawn command failed", "")
                return
            self.injected_at = now
            log.write(f"injected {self.envelope['msg_id']} via=spawn")
            return
        tmuxio.prime_injection(self.pane_id, self.wake_text_resolved(), self.ssh_host or None)
        self.state = STATE_INJECTING
        self.enter_stage = 0
        self.enter_deadline = now + tmuxio.ENTER_QUIET_LADDER[0]
        self.enter_tail = ""
        storage.stamp_injected(root, self.envelope["to"], self.envelope["msg_id"], now)
        self.injected_at = now
        log.write(
            f"injected {self.envelope['msg_id']} via=pane {self.pane_id} "
            "(文本入输入区, Enter 阶梯按铃尽力一次)"
        )

    def start_spawn(self, log) -> bool:
        command = [*self.spawn_cmd, self.wake_text_resolved()]
        try:
            self.spawn_proc = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as exc:
            log.write(f"spawn error {self.envelope['msg_id']}: {exc}")
            return False
        self.state = STATE_WAIT_SPAWN_EXIT
        return True

    def collect_spawn(self, root: Path, log, now: float) -> None:
        code = self.spawn_proc.poll()
        if code is None:
            if now - self.injected_at >= SPAWN_TIMEOUT_SECONDS:
                self.spawn_proc.terminate()
                self.fail(root, log, "spawn timeout", "")
            return
        log.write(f"spawn exit={code} {self.envelope['msg_id']}")
        if code == 0:
            self.state = STATE_WAIT_ACK
            self.state_since = now
        else:
            self.fail(root, log, "spawn command failed", "")

    def ack_timeout(self) -> float:
        if self.spawn_cmd:
            return SPAWN_ACK_TIMEOUT_SECONDS
        return ACK_TIMEOUT_SECONDS

    def dump_bottom(self) -> str:
        if not self.pane_id:
            return ""
        return tmuxio.capture_bottom(self.pane_id, ssh_host=self.ssh_host or None)

    def booting(self, now: float) -> bool:
        return self.pane_created > 0.0 and now - self.pane_created < PANE_BOOT_SETTLE_SECONDS

    def tick(self, root: Path, log, now: float, target_online: bool, frames: dict | None = None) -> None:
        if self.finished() or not target_online:
            return
        if self.state == STATE_SETTLING:
            if now - self.state_since < SETTLE_SECONDS:
                return
            if self.booting(now):
                return
            self.inject_round(root, log, now)
            return
        if self.state == STATE_WAIT_NATIVE:
            if self.ack_arrived(root):
                self.confirm_delivered(root, log)
                return
            if self.queue_proc is not None:
                self.collect_queue_daemon(root, log, now)
            return
        if self.state == STATE_WAIT_SPAWN_EXIT:
            if self.ack_arrived(root):
                self.confirm_delivered(root, log)
                return
            self.collect_spawn(root, log, now)
            return
        if self.state == STATE_INJECTING:
            if self.ack_arrived(root):
                self.confirm_delivered(root, log)
                return
            tail = self.frame_tail(frames)
            if self.enter_tail and tmuxio.frames_show_growth(self.enter_tail, tail):
                self.enter_tail = tail
                self.enter_deadline = now + tmuxio.ENTER_QUIET_LADDER[self.enter_stage]
                return
            self.enter_tail = tail
            if now - self.injected_at >= INJECTING_PATIENCE_SECONDS:
                self.settle_injection(root, log, now, frames)
                return
            if now < self.enter_deadline:
                return
            tmuxio.send_enter(self.pane_id, self.ssh_host or None)
            self.enter_stage += 1
            if self.enter_stage >= len(tmuxio.ENTER_QUIET_LADDER):
                log.write(
                    f"receipt {self.envelope['msg_id']} to={self.envelope['to']} "
                    f"via=pane {self.pane_id} (Enter 阶梯完成, 文本已提交, 等阅读回执)"
                )
                self.state = STATE_WAIT_CONFIRM
                self.state_since = now
            else:
                self.enter_deadline = now + tmuxio.ENTER_QUIET_LADDER[self.enter_stage]
            return
        if self.state == STATE_WAIT_CONFIRM:
            if self.ack_arrived(root):
                self.confirm_delivered(root, log)
                return
            if self.ack_probe_lost_at:
                self.state_since = now
                return
            if now - self.state_since < CONFIRM_PATIENCE_SECONDS:
                return
            self.close_unconfirmed(root, log)
            return
        if self.state == STATE_WAIT_ACK:
            if self.ack_arrived(root):
                self.confirm_delivered(root, log)
                return
            if self.ack_probe_lost_at:
                self.injected_at = now
                return
            if now - self.injected_at < self.ack_timeout():
                return
            self.fail(root, log, "ack timeout after retries", self.dump_bottom())


def build_delivery(envelope: dict, record: dict, now: float, root: Path | None = None):
    record = dict(record)
    inst_key = str(envelope.get("to_instance") or "")
    if inst_key:
        entry = dict(record.get("instances") or {}).get(inst_key) or {}
        if entry:
            record["pane_id"] = entry.get("pane_id") or record.get("pane_id") or ""
            record["pane_pid"] = entry.get("pane_pid") or record.get("pane_pid") or ""
            record["slot"] = entry.get("slot") or record.get("slot") or ""
    pane_id = record.get("pane_id") or ""
    ssh_host = str(record.get("ssh_alias") or "")
    spawn_cmd = record.get("spawn_cmd")
    cli = str(record.get("cli") or "")
    kind = cli_agents.delivery_kind(cli)
    native = (
        root is not None
        and pane_id
        and not ssh_host
        and not spawn_cmd
        and kind == "native-inbox"
    )
    queue_bin = str(record.get("codex_bin") or "")
    queue_daemon = (
        root is not None
        and not ssh_host
        and not spawn_cmd
        and bool(queue_bin)
        and bool(record.get("codex_home"))
        and bool(record.get("codex_thread"))
        and (codexq.is_windows_bin(queue_bin) or codexq.daemon_alive(Path(str(record.get("codex_home")))))
    )
    rpc_inbox = (
        root is not None
        and not ssh_host
        and kind == "rpc-inbox"
        and bool(str(record.get("rpc_inbox_url") or ""))
    )
    if pane_id or queue_daemon or rpc_inbox:
        created = tmuxio.pane_created(pane_id, ssh_host or None) if pane_id else 0.0
        return Delivery(
            envelope,
            now,
            pane_id=pane_id,
            ssh_host=ssh_host,
            pane_created=created,
            native=native or queue_daemon,
            queue_daemon=queue_daemon,
            rpc_inbox=rpc_inbox,
            wake_cap=bool(cli_agents.spec_for(cli).get("wake_cap")),
        )
    if isinstance(spawn_cmd, list) and spawn_cmd and not ssh_host:
        return Delivery(envelope, now, spawn_cmd=spawn_cmd)
    return None


def collect_snapshots(reg: dict) -> dict:
    hosts = {""}
    for record in reg["agents"].values():
        alias = str(record.get("ssh_alias") or "")
        if alias:
            hosts.add(alias)
    snapshots = {}
    for host in hosts:
        panes = tmuxio.snapshot_all_panes(host or None)
        if not panes:
            continue
        slots = {}
        for pane_id, rec in panes.items():
            slots[rec["slot"]] = pane_id
        snapshots[host] = {"panes": panes, "slots": slots}
    return snapshots


def reanchor_codex_threads(reg: dict, root: Path, log) -> None:
    updates: dict = {}
    for agent_id, record in reg["agents"].items():
        if str(record.get("cli") or "") != "codex" or not record.get("codex_bin"):
            continue
        pane_pid = str(record.get("pane_pid") or "")
        if not pane_pid or not str(record.get("pane_id") or ""):
            continue
        thread = codexq.thread_of_pid(int(pane_pid) if pane_pid.isdigit() else 0)
        if thread and thread != str(record.get("codex_thread") or ""):
            updated = dict(record)
            updated["codex_thread"] = thread
            updates[agent_id] = updated
    if updates:
        registry.apply_batch(root, updates)
        reg["agents"].update(updates)
        for agent_id, updated in updates.items():
            log.write(f"codex-thread-reanchored {agent_id} -> {updated['codex_thread']}")


def reanchor_cwd_panes(reg: dict, root: Path, log, snapshots: dict) -> None:
    updates = {}
    for agent_id, record in reg["agents"].items():
        cwd = str(record.get("cwd") or "")
        pane_id = str(record.get("pane_id") or "")
        if record.get("spawn_cmd") or not cwd:
            continue
        if codexq.anchors_complete(record):
            continue
        snap = snapshots.get(str(record.get("ssh_alias") or ""))
        if snap is None:
            continue
        if pane_id and pane_id in snap["panes"]:
            continue
        hits = [hit_id for hit_id, pane_rec in snap["panes"].items() if pane_rec.get("cwd") == cwd]
        if len(hits) != 1:
            continue
        pane_rec = snap["panes"][hits[0]]
        expected_commands = cli_agents.pane_commands_for(str(record.get("cli") or ""))
        if pane_rec.get("command") not in expected_commands:
            continue
        updated = dict(record)
        updated["pane_id"] = hits[0]
        updated["pane_pid"] = pane_rec["pane_pid"]
        updated["slot"] = pane_rec["slot"]
        updated["display_name"] = pane_rec["slot"].split(":", 1)[-1] if ":" in pane_rec["slot"] else ""
        updates[agent_id] = updated
        reason = f"死锚重锚, 原pane {pane_id} 已消亡" if pane_id else "cwd 匹配回锚"
        log.write(f"re-anchored {agent_id} -> pane {hits[0]} slot {pane_rec['slot']}（{reason}: {cwd}）")
    if updates:
        registry.apply_batch(root, updates)
        reg["agents"].update(updates)


def refresh_display_names(reg: dict, root: Path, log, snapshots: dict | None = None) -> None:
    snaps = snapshots or {}
    updates = {}
    for agent_id, record in list(reg["agents"].items()):
        pane_id = record.get("pane_id") or ""
        if not pane_id:
            continue
        host_key = str(record.get("ssh_alias") or "")
        snap = snaps.get(host_key)
        if snap is not None:
            pane_rec = snap["panes"].get(pane_id)
            slot = pane_rec["slot"] if pane_rec else ""
        else:
            slot = tmuxio.pane_slot(pane_id, host_key or None)
        window_name = slot.split(":", 1)[1] if ":" in slot else ""
        if not slot or (slot == record.get("slot") and window_name == record.get("display_name")):
            continue
        updated = dict(record)
        updated["slot"] = slot
        updated["display_name"] = window_name
        updates[agent_id] = updated
        log.write(f"slot {agent_id} -> {slot}（agent_id/fingerprint 不变）")
    if updates:
        registry.apply_batch(root, updates)
        reg["agents"].update(updates)


def paneless_online(record: dict) -> bool:
    if codexq.anchors_complete(record) or bool(record.get("spawn_cmd")):
        return True
    cli = str(record.get("cli") or "")
    if cli not in cli_agents.pull_only_clis() and cli not in cli_agents.rpc_inbox_clis():
        return False
    last_seen = float(record.get("last_seen") or 0)
    return last_seen > 0 and time.time() - last_seen < PANELESS_ACTIVE_SECONDS


def sweep_liveness(
    reg: dict,
    root: Path,
    log,
    prev_online: dict,
    remote_cache: dict,
    now: float,
    snapshots: dict | None = None,
) -> dict:
    snaps = snapshots or {}
    online = {}
    updates = {}
    for agent_id, record in reg["agents"].items():
        instances = record.get("instances")
        if isinstance(instances, dict) and instances:
            host_key = str(record.get("ssh_alias") or "") or None
            inst_snap = snaps.get(host_key or "")
            live = {}
            for inst_key, entry in instances.items():
                inst_pane = str(entry.get("pane_id") or "")
                if inst_pane and inst_snap is not None and inst_pane in inst_snap["panes"]:
                    live[inst_key] = entry
                elif inst_pane and inst_snap is None and tmuxio.pane_pid_matches(inst_pane, str(entry.get("pane_pid") or ""), host_key):
                    live[inst_key] = entry
                elif not inst_pane:
                    live[inst_key] = entry
            if len(live) != len(instances):
                dropped = sorted(set(instances) - set(live))
                updated = updates.get(agent_id) or dict(record)
                updated["instances"] = live
                updates[agent_id] = updated
                log.write(f"instance-pruned {agent_id} 剔除失活分身 {dropped}")
        slot = record.get("slot") or ""
        pane_id = record.get("pane_id") or ""
        ssh_host = str(record.get("ssh_alias") or "") or None
        snap = snaps.get(ssh_host or "")
        if slot:
            if snap is not None:
                resolved = snap["slots"].get(slot, "")
            else:
                resolved = tmuxio.slot_pane_id(slot, ssh_host)
            alive = bool(resolved)
            if alive and resolved != pane_id:
                anchor = snap["panes"].get(resolved, {}) if snap is not None else {}
                command = str(anchor.get("command") or tmuxio.pane_current_command(resolved, ssh_host) or "")
                expected = cli_agents.pane_commands_for(str(record.get("cli") or ""))
                if command and command not in expected:
                    log.write(
                        f"identity-mismatch {agent_id} slot {slot} 新 pane {resolved} 前台={command} "
                        f"非 {record.get('cli')}——同名窗被占, 不重锚判 offline"
                    )
                    notify(log, "agent-offline", agent_id=agent_id)
                    online[agent_id] = False
                    continue
                updated = dict(record)
                updated["pane_id"] = resolved
                updated["pane_pid"] = anchor.get("pane_pid") or tmuxio.pane_pid(resolved, ssh_host)
                updates[agent_id] = updated
        elif pane_id:
            if ssh_host:
                checked_at, was_alive = remote_cache.get(agent_id, (0.0, False))
                if was_alive and now - checked_at < REMOTE_LIVENESS_SECONDS:
                    online[agent_id] = True
                    continue
                alive = snapshot_pane_pid(snap, pane_id, record, ssh_host)
                remote_cache[agent_id] = (now, alive)
            else:
                alive = snapshot_pane_pid(snap, pane_id, record, ssh_host)
        else:
            online[agent_id] = paneless_online(record)
            continue
        online[agent_id] = alive
        was = prev_online.get(agent_id)
        if was is not None and was != alive:
            log.write(f"agent {agent_id} {'online' if alive else 'offline'}")
            notify(log, "agent-online" if alive else "agent-offline", agent_id=agent_id)
    if updates:
        registry.apply_batch(root, updates)
        reg["agents"].update(updates)
    return online


def snapshot_pane_pid(snap: dict | None, pane_id: str, record: dict, ssh_host) -> bool:
    expected = str(record.get("pane_pid", ""))
    if snap is not None:
        pane_rec = snap["panes"].get(pane_id)
        return bool(pane_rec) and pane_rec["pane_pid"] == expected
    return tmuxio.pane_pid_matches(pane_id, expected, ssh_host)


def sweep_tool_silence(reg: dict, log, prev_silent: set, now: float, online: dict) -> set:
    silent = set()
    for agent_id, record in reg["agents"].items():
        if not online.get(agent_id):
            continue
        last_seen = storage.to_epoch(record.get("last_seen") or record.get("started_at") or 0)
        if now - last_seen > TOOL_SILENT_SECONDS:
            silent.add(agent_id)
    for agent_id in sorted(silent - prev_silent):
        log.write(
            f"tool-silent {agent_id} last_seen 老化超过 {TOOL_SILENT_SECONDS:g}s——"
            "参考信息(判活以 pane_pid 为准, last_seen 仅在收件方调用 mail 工具时刷新): "
            "若该端工具面确实已死(工具列表为空), 处方=respawn 该端窗口"
        )
    return silent


def ensure_online(record: dict, online: dict, remote_cache: dict, now: float) -> bool:
    agent_id = record.get("agent_id") or ""
    if agent_id in online:
        return online[agent_id]
    pane_id = record.get("pane_id") or ""
    ssh_host = str(record.get("ssh_alias") or "") or None
    if not pane_id:
        online[agent_id] = paneless_online(record)
        return online[agent_id]
    alive = tmuxio.pane_pid_matches(pane_id, str(record.get("pane_pid", "")), ssh_host)
    if ssh_host:
        remote_cache[agent_id] = (now, alive)
    online[agent_id] = alive
    return alive


def respawn_offline_spawners(reg: dict, root: Path, log, online: dict) -> None:
    for agent_id, record in list(reg["agents"].items()):
        if online.get(agent_id):
            continue
        spawn_cmd = record.get("spawn_cmd")
        if not (isinstance(spawn_cmd, list) and spawn_cmd):
            continue
        if not storage.list_queue(root, agent_id):
            continue
        if not record.get("pane_id"):
            online[agent_id] = True
            continue
        unanchored = dict(record)
        unanchored["pane_id"] = ""
        unanchored["pane_pid"] = ""
        registry.upsert(root, agent_id, unanchored)
        reg["agents"][agent_id] = unanchored
        online[agent_id] = True
        log.write(f"respawn-path {agent_id} pane 锚失效但有 spawn_cmd+在途邮件, 清锚改走 spawn 投递")


def sweep_rate_storms(root: Path, log, active_storms: set) -> set:
    rates_dir = root / paths.RATES_DIR
    if not rates_dir.is_dir():
        return active_storms
    now = time.time()
    for ledger in sorted(rates_dir.glob("*.ledger")):
        pair = ledger.name[: -len(".ledger")]
        recent = 0
        for line in ledger.read_text().splitlines():
            try:
                stamp = float(line)
            except ValueError:
                continue
            if now - stamp < storage.RATE_WINDOW_SECONDS:
                recent += 1
        if recent >= storage.RATE_MAX_PER_WINDOW:
            if pair not in active_storms:
                active_storms.add(pair)
                log.write(f"rate-storm {pair} 窗口内 {recent} 条(无向对合计)——观测告警不拦截, 深度会话不限")
                notify(log, "rate-storm", pair=pair)
        elif pair in active_storms:
            active_storms.discard(pair)
            log.write(f"rate-storm {pair} 平息")
    return active_storms


OFFLINE_STALL_SECONDS = 1800.0
OFFLINE_STALL_REASON = "recipient offline, no pane anchor"
PULL_ONLY_CLIS = cli_detect.PULL_ONLY_CLIS


def sweep_offline_stalled(root: Path, log, reg: dict, online: dict, now: float, deliveries: dict) -> None:
    for agent_id, record in reg["agents"].items():
        if online.get(agent_id):
            continue
        pull_only = str(record.get("cli") or "") in PULL_ONLY_CLIS
        home_hub = str(record.get("ssh_alias") or "") and codexq.anchors_complete(record)
        for envelope in storage.list_queue(root, agent_id):
            msg_id = str(envelope.get("msg_id") or "")
            if not msg_id or f"{agent_id}/{msg_id}" in deliveries:
                continue
            if now - float(envelope.get("created_at") or 0) < OFFLINE_STALL_SECONDS:
                continue
            if home_hub:
                relay_to_home(root, log, agent_id, msg_id, record, envelope, now)
                continue
            if pull_only:
                if float(envelope.get("stall_notified_at") or 0) > 0.0:
                    continue
                storage.stamp_stall_notified(root, agent_id, msg_id, now)
                log.write(
                    f"delivery-stalled {msg_id} to={agent_id} 拉取型收件方(cli={record.get('cli')}) "
                    f"未取件超 {OFFLINE_STALL_SECONDS:g}s——保留队列待 mail_poll 拉取, 不回弹"
                )
                notify(log, "delivery-stalled", agent_id=agent_id, msg_id=msg_id, reason="pull-only recipient, mail awaits pickup")
                continue
            storage.mark_failed(root, agent_id, msg_id)
            log.write(
                f"delivery-stalled {msg_id} to={agent_id} 收件方 offline 且无 pane 锚点, "
                f"滞留超 {OFFLINE_STALL_SECONDS:g}s——回弹发送方"
            )
            notify(log, "delivery-stalled", agent_id=agent_id, msg_id=msg_id, reason=OFFLINE_STALL_REASON)
            enqueue_bounce(root, log, envelope, OFFLINE_STALL_REASON)


def sweep_win_bridge_anchors(reg: dict, root: Path, log, now: float) -> int:
    reanchored = 0
    for agent_id, record in reg["agents"].items():
        if str(record.get("cli") or "") != "unknown":
            continue
        if codexq.anchors_complete(record):
            continue
        started_at = float(record.get("started_at") or 0)
        if not 0 < now - started_at < WIN_REANCHOR_WINDOW_SECONDS:
            continue
        cwd = str(record.get("cwd") or "")
        if not codexq.WIN_CWD_RE.match(cwd):
            continue
        fresh = codexq.locate_win(cwd)
        if not fresh:
            continue
        updated = dict(record)
        updated.update(fresh)
        updated["ssh_alias"] = ""
        registry.upsert(root, agent_id, updated)
        record.update(updated)
        log.write(
            f"win-bridge-reanchored {agent_id} -> {str(fresh.get('codex_thread') or '')[:13]}"
            "(注册时 rollout 未就绪致锚落空, 慢周期补锚; 自指 ssh_alias 一并清除)"
        )
        reanchored += 1
    return reanchored


def sweep_failed_corpses(root: Path, log, now: float) -> int:
    queue_root = root / paths.QUEUE_DIR
    if not queue_root.is_dir():
        return 0
    moved = 0
    for agent_dir in queue_root.iterdir():
        if not agent_dir.is_dir():
            continue
        for corpse in agent_dir.glob("*.failed"):
            try:
                age = now - corpse.stat().st_mtime
            except OSError:
                continue
            if age < FAILED_MORGUE_SECONDS:
                continue
            morgue = root / paths.FORENSICS_DIR / "queue-failed" / agent_dir.name
            morgue.mkdir(parents=True, exist_ok=True)
            corpse.replace(morgue / corpse.name)
            moved += 1
    if moved:
        log.write(f"failed-morgue 超龄 .failed {moved} 具归档 forensics/queue-failed/")
    return moved


def sweep_orphan_queues(root: Path, log, reg: dict, deliveries: dict | None = None) -> list[str]:
    queue_root = root / paths.QUEUE_DIR
    if not queue_root.is_dir():
        return []
    try:
        fresh = registry.try_load(root)["agents"]
    except registry.RegistryUnavailable:
        return []
    orphans = [
        agent_dir.name
        for agent_dir in sorted(queue_root.iterdir())
        if agent_dir.is_dir() and agent_dir.name not in reg["agents"] and agent_dir.name not in fresh
    ]
    for agent_id in orphans:
        settled = settle_agent_mail(root, log, agent_id, DEREGISTERED_REASON, deliveries)
        if settled:
            log.write(f"orphan-sweep {agent_id} 队列目录不在册(重查注册表确认), 处置在途邮件 {settled} 条")
        try:
            (queue_root / agent_id).rmdir()
        except OSError:
            pass
    return orphans


def prune_registry(
    reg: dict,
    root: Path,
    log,
    online: dict,
    now: float,
    remote_exempt: set | None = None,
    deliveries: dict | None = None,
) -> list[str]:
    pruned = []
    settled_total = 0
    exempt = remote_exempt or set()

    def retire(agent_id: str) -> int:
        pruned.append(agent_id)
        record = reg["agents"].pop(agent_id)
        registry.forget(root, agent_id)
        return settle_agent_mail(root, log, agent_id, DEREGISTERED_REASON, deliveries, record)

    for agent_id, record in list(reg["agents"].items()):
        pane_id = record.get("pane_id") or ""
        remote = bool(record.get("ssh_alias"))
        if remote and str(record.get("ssh_alias")) in exempt:
            continue
        if pane_id and online.get(agent_id, True):
            continue
        if pane_id and not remote and online.get(agent_id) is False:
            if not cli_agents.respawn_recipe(str(record.get("cli") or "")):
                settled_total += retire(agent_id)
                continue
        if (
            not pane_id
            and str(record.get("cli") or "") in cli_agents.pull_only_clis()
            and storage.list_queue(root, agent_id)
        ):
            continue
        if remote and storage.list_queue(root, agent_id):
            continue
        if not pane_id and codexq.anchors_complete(record):
            continue
        last_seen = float(record.get("last_seen") or 0)
        prune_ttl = REGISTRY_PRUNE_REMOTE_TTL if remote else REGISTRY_PRUNE_TTL
        if now - last_seen < prune_ttl:
            continue
        settled_total += retire(agent_id)
    if pruned:
        archive = root / paths.HISTORY_DIR / "registry-pruned.jsonl"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with archive.open("a") as handle:
            for agent_id in pruned:
                handle.write(json.dumps({"agent_id": agent_id, "pruned_at": now}, ensure_ascii=False) + "\n")
        log.write(
            f"registry-pruned {', '.join(sorted(pruned))} pane 消亡即时注销或 last_seen 超过 {REGISTRY_PRUNE_TTL:g}s, "
            f"处置在途邮件 {settled_total} 条, 记录归档 history/registry-pruned.jsonl"
        )
    return pruned


def step(
    root: Path,
    reg: dict,
    deliveries: dict,
    log,
    now: float,
    online: dict,
    remote_cache: dict | None = None,
    frame_cache: dict | None = None,
    dirty_agents: set | None = None,
) -> None:
    cache = remote_cache if remote_cache is not None else {}
    frames = frame_cache if frame_cache is not None else None
    if dirty_agents is None:
        scan_targets = [agent_id for agent_id, alive in online.items() if alive]
        probe_targets = [agent_id for agent_id in reg["agents"] if agent_id not in online]
    else:
        scan_targets = [agent_id for agent_id in dirty_agents if online.get(agent_id)]
        probe_targets = [agent_id for agent_id in dirty_agents if not online.get(agent_id)]
    unreadable_reported: set = set()

    def report_unreadable(agent_id: str, path):
        if path in unreadable_reported:
            return
        unreadable_reported.add(path)
        log.write(f"unreadable {path.name} in {agent_id} 队列——json 解析失败, 该信不参与本轮投递")

    for agent_id in scan_targets:
        record = reg["agents"].get(agent_id, {})
        for envelope in storage.list_queue(root, agent_id, on_unreadable=lambda path, aid=agent_id: report_unreadable(aid, path)):
            msg_id = envelope.get("msg_id")
            try:
                key = f"{agent_id}/{msg_id}"
                if key in deliveries:
                    continue
                if storage.recently_injected(envelope, now, REINJECT_GUARD_SECONDS):
                    continue
                if storage.queue_retry_pending(envelope, now):
                    continue
                if (root / paths.HISTORY_DIR / f"{msg_id}.json").exists():
                    storage.discard_msg(root, agent_id, msg_id)
                    log.write(f"duplicate {msg_id} to={agent_id} 已归档又重现队列——丢弃重复副本不重投")
                    continue
                sender = str(envelope.get("from") or "")
                sender_record = reg["agents"].get(sender)
                sender_peer_of = str((sender_record or {}).get("peer_of") or "")
                injected_stamp = float(envelope.get("last_injected_at") or 0)
                if injected_stamp <= 0 and sender_peer_of and sender != agent_id and agent_id != sender_peer_of:
                    storage.mark_failed(root, agent_id, msg_id)
                    log.write(
                        f"scope-reject {msg_id} to={agent_id} from={sender} "
                        f"subagent 仅可对主 {sender_peer_of} 收发——拒收回弹"
                    )
                    notify(log, "delivery-failed", agent_id=agent_id, msg_id=msg_id, reason="subagent scope violated")
                    enqueue_bounce(root, log, envelope, f"subagent scope: 仅可对主 agent {sender_peer_of} 收发")
                    continue
                if (
                    injected_stamp <= 0
                    and record.get("group_only")
                    and sender != HUB_FROM
                    and sender != agent_id
                    and sender not in (record.get("allowed_senders") or [])
                ):
                    storage.mark_failed(root, agent_id, msg_id)
                    log.write(
                        f"group-reject {msg_id} to={agent_id} from={sender} 未准入——拒收回弹"
                    )
                    notify(log, "delivery-failed", agent_id=agent_id, msg_id=msg_id, reason="group-only recipient, sender not admitted")
                    enqueue_bounce(root, log, envelope, "group-only recipient, sender not admitted")
                    continue
                if str(record.get("ssh_alias") or "") and (
                    codexq.anchors_complete(record)
                    or str(record.get("cli") or "") in cli_agents.pull_only_clis()
                    or cli_agents.delivery_kind(str(record.get("cli") or "")) in ("native-inbox", "rpc-inbox")
                ):
                    if float(envelope.get("last_injected_at") or 0) > 0 or nativebox.rcpt_exists(root, agent_id, msg_id):
                        storage.archive_msg(root, agent_id, msg_id)
                        log.write(f"receipt-held {msg_id} to={agent_id} 锚齐收件人归 home hub 管辖, 已投递副本归档不回弹")
                    else:
                        relay_to_home(root, log, agent_id, msg_id, record, envelope, now)
                    continue
                if str(record.get("cli") or "") in cli_agents.pull_only_clis():
                    continue
                delivery = build_delivery(envelope, record, now, root)
                if delivery is None:
                    storage.mark_failed(root, agent_id, msg_id)
                    log.write(f"FAILED {msg_id} to={agent_id} reason=no delivery path")
                    notify(log, "delivery-failed", agent_id=agent_id, msg_id=msg_id, reason="no delivery path")
                    enqueue_bounce(root, log, envelope, "no delivery path")
                    continue
                if delivery.rpc_inbox:
                    if injected_stamp > 0:
                        delivery.resume_after_injection(injected_stamp)
                    elif not delivery.dispatch_rpc_inbox(root, log, now, record):
                        continue
                elif delivery.native:
                    if delivery.queue_daemon:
                        if injected_stamp > 0:
                            delivery.resume_queue_receipted(injected_stamp)
                        elif not delivery.dispatch_queue_daemon(root, log, now, record):
                            continue
                    elif injected_stamp > 0:
                        delivery.resume_after_injection(injected_stamp)
                    else:
                        delivery.dispatch_native(root, log, now)
                elif injected_stamp > 0 and not delivery.spawn_cmd:
                    delivery.resume_after_injection(injected_stamp)
                deliveries[key] = delivery
            except Exception as exc:
                log.write(f"envelope-error {agent_id}/{msg_id}: {exc!r}——脏信封 mark_failed, 单条故障不杀轮")
                if msg_id:
                    storage.mark_failed(root, agent_id, msg_id)
    for agent_id in probe_targets:
        try:
            record = reg["agents"].get(agent_id)
            if record is None:
                continue
            if not storage.list_queue(root, agent_id):
                continue
            if ensure_online(record, online, cache, now):
                log.write(f"agent {agent_id} online")
        except Exception as exc:
            log.write(f"probe-error {agent_id}: {exc!r}——单端探测故障跳过本轮")
    busy_panes: set = set()
    for key in list(deliveries):
        delivery = deliveries[key]
        if delivery.state == STATE_INJECTING:
            busy_panes.add((delivery.ssh_host, delivery.pane_id))
    for key in list(deliveries):
        delivery = deliveries[key]
        if delivery.state == STATE_SETTLING and (delivery.ssh_host, delivery.pane_id) in busy_panes:
            delivery.defer_occupied(log, now)
            continue
        if now < delivery.next_tick_at:
            continue
        try:
            delivery.tick(root, log, now, online.get(delivery.envelope["to"], False), frames)
            delivery.error_strikes = 0
        except Exception as exc:
            log.write(f"delivery-error {key}: {exc!r}——单条投递故障跳过本轮")
            to_id = str(delivery.envelope.get("to") or "")
            msg_id = str(delivery.envelope.get("msg_id") or "")
            if to_id and msg_id and not storage.msg_in_queue(root, to_id, msg_id) and not storage.msg_path(root, to_id, msg_id).with_suffix(".failed").is_file():
                del deliveries[key]
                log.write(f"delivery-evicted {key} 信与死信均已不在档——幽灵投递驱逐, 不再重试")
            else:
                delivery.error_strikes += 1
                if delivery.error_strikes >= DELIVERY_ERROR_STRIKES:
                    delivery.abort_error_loop(root, log, exc)
                else:
                    delivery.next_tick_at = now + DELIVERY_ERROR_RETRY_SECONDS
        if delivery.finished():
            del deliveries[key]


def main() -> None:
    root = paths.mailbox_root()
    paths.ensure_layout(root)
    log = HubLog(root)
    lock_handle = acquire_hub_lock(root)
    if lock_handle is None:
        log.write("hub-lock 已被持有——已有 hub 在跑, 本进程退出")
        return
    log.write(f"hub start pid={os.getpid()} root={root}")
    hub_started_at = time.time()
    deliveries: dict = {}
    online: dict = {}
    remote_cache: dict = {}
    tool_silent: set = set()
    failed_peers: set = set()
    rate_storms: set = set()
    last_pull = 0.0
    try:
        notifier = queuenotify.QueueNotifier(root)
    except OSError as exc:
        notifier = None
        log.write(f"inotify unavailable ({exc}), fallback to {SCAN_INTERVAL_SECONDS:g}s polling")
    reg = registry.load(root)
    sweep_orphan_queues(root, log, reg, deliveries)
    last_slow = 0.0
    frame_cache: dict = {}
    dirty_agents: set = set()
    while True:
      try:
        now = time.time()
        dirty_agents.clear()
        registry_changed = False
        full_scan = False
        if notifier is None:
            time.sleep(SCAN_INTERVAL_SECONDS)
        else:
            timeout = SLOW_INTERVAL_SECONDS - (now - last_slow)
            if deliveries:
                timeout = min(timeout, ACTIVE_TICK_SECONDS)
            events = notifier.wait(timeout if timeout > 0.0 else 0.0)
            for directory, name in events:
                if directory == str(root) and name == paths.REGISTRY_FILE:
                    registry_changed = True
                    continue
                parent = str(Path(directory).parent)
                if parent == str(notifier.queue_root):
                    dirty_agents.add(Path(directory).name)
            if notifier.degraded:
                log.write("inotify watch degraded, 全量回退一轮并重建 watch")
                full_scan = True
                notifier._rebuild()
        now = time.time()
        slow_due = now - last_slow >= SLOW_INTERVAL_SECONDS
        if slow_due or registry_changed or full_scan or notifier is None:
            try:
                reg = registry.try_load(root, on_corrupt=lambda exc: log.write(f"{paths.REGISTRY_FILE} 损坏({exc!r})——按空注册表续跑, 修复后自动恢复"))
            except registry.RegistryUnavailable as exc:
                log.write(f"{paths.REGISTRY_FILE} 瞬态不可读({exc})——本轮跳过, 不做任何孤儿化/剪枝/判活")
                time.sleep(1)
                continue
        NOTIFY_POOL.reap(log, now)
        frame_cache.clear()
        scan_scope = None if (full_scan or slow_due or registry_changed) else dirty_agents
        step(root, reg, deliveries, log, now, online, remote_cache, frame_cache, scan_scope)
        if slow_due:
            snapshots = collect_snapshots(reg)
            reanchor_cwd_panes(reg, root, log, snapshots)
            reanchor_codex_threads(reg, root, log)
            refresh_display_names(reg, root, log, snapshots)
            online = sweep_liveness(reg, root, log, online, remote_cache, now, snapshots)
            tool_silent = sweep_tool_silence(reg, log, tool_silent, now, online)
            respawn_offline_spawners(reg, root, log, online)
            sweep_offline_stalled(root, log, reg, online, now, deliveries)
            storage.write_online(root, online, now)
            rate_storms = sweep_rate_storms(root, log, rate_storms)
            kick_flag = root / FED_PULL_NOW_FILENAME
            if kick_flag.exists():
                kick_flag.unlink(missing_ok=True)
                last_pull = 0.0
            if now - last_pull >= FED_PULL_INTERVAL_SECONDS:
                results = federation.pull_all(root)
                freshly_failed = {str(item.get("peer")) for item in results if not item.get("ok")}
                for item in results:
                    if item.get("pulled"):
                        log.write(f"fed-repatriated {item.get('peer')} 拉回 {item['pulled']} 条已注入在途邮件(本地可读)")
                for alias in sorted(freshly_failed - failed_peers):
                    log.write(f"peer-offline {alias} 联邦拉取失败, 其记录保留陈旧副本(stale)")
                    notify(log, "peer-offline", peer=alias)
                for alias in sorted(failed_peers - freshly_failed):
                    log.write(f"peer-online {alias} 联邦拉取恢复")
                failed_peers = freshly_failed
                last_pull = now
            sweep_win_bridge_anchors(reg, root, log, now)
            sweep_orphan_queues(root, log, reg, deliveries)
            sweep_failed_corpses(root, log, now)
            prune_registry(reg, root, log, online, now, failed_peers, deliveries)
            last_slow = now
            if idle_reap_due(root, reg, deliveries, now, hub_started_at):
                log.write(
                    f"hub-idle-reap MCP 心跳/agent last_seen 均老化超 {IDLE_REAP_SECONDS:g}s 且队列在途全空"
                    "——纯 win 节点空闲自回收, 下次 MCP 调用再拉起"
                )
                notify(log, "hub-idle-reap")
                break
      except Exception as exc:
        log.write(f"hub-tick error: {exc!r}——单轮故障不杀 daemon")


if __name__ == "__main__":
    main()
