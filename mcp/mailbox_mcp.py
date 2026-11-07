import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP

from common import atomicio, codexq, detect, federation, lockfile, msgfmt, paths, peers, registry, sshio, storage, tmuxio
from common import agents as agent_specs
from common.version import SCHEMA_VERSION

SAFE_INSTANCE_RE = re.compile(r"^[0-9a-z%]{1,12}$")

mcp = FastMCP("mailbox")

SELF: dict = {}
REGISTER_FAILURE = ""


def ensure_self() -> dict:
    global SELF, REGISTER_FAILURE
    if SELF:
        return SELF
    try:
        SELF = self_register()
        REGISTER_FAILURE = ""
    except Exception as exc:
        REGISTER_FAILURE = str(exc)
    return SELF


def guard_error() -> str:
    record = ensure_self()
    if record:
        return ""
    reason = REGISTER_FAILURE or "无 tmux pane 环境或注册失败"
    return (
        f"本会话自注册失败: {reason}——"
        "双开冲突时换 tmux 窗名即可自愈(下次工具调用自动重试注册); "
        "无 tmux 环境则本进程无法注册收信"
    )


def spawn_cmd_from_env() -> list[str] | None:
    raw = os.environ.get("A2A_SPAWN_CMD")
    if not raw:
        return None
    try:
        parts = shlex.split(raw)
    except ValueError:
        return None
    return parts or None


SSH_ALIAS_ENV = "A2A_SSH_ALIAS"
PEER_OF_ENV = "A2A_PEER_OF"


def ssh_alias_from_env() -> str:
    return os.environ.get(SSH_ALIAS_ENV, "")


def peer_of_from_env() -> str:
    return os.environ.get(PEER_OF_ENV, "").strip()


CC_SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def session_env_id() -> str:
    return os.environ.get(CC_SESSION_ENV, "").strip()


def instance_key_for(cli: str, pane_id: str) -> str:
    kind = agent_specs.multi_instance_key(cli)
    if kind == "session":
        return session_env_id()[:8]
    if kind == "pane":
        return pane_id
    return ""


def split_instance_target(to: str) -> tuple[str, str]:
    base, marker, instance = str(to or "").rpartition("@")
    if marker and base and SAFE_INSTANCE_RE.match(instance):
        return base, instance
    return str(to or ""), ""


def respawn_offline_target(root: Path, target_id: str) -> str:
    record = registry.get(root, target_id)
    if record is None or str(record.get("ssh_alias") or ""):
        return ""
    if storage.load_online(root).get(target_id) is not False:
        return ""
    recipe = agent_specs.respawn_recipe(str(record.get("cli") or ""))
    if not recipe:
        return ""
    proc = str(record.get("cli") or "")
    resume_args = list(recipe.get("resume_args") or [])
    command = [proc, *resume_args]
    backend = str(recipe.get("backend") or "")
    if backend == "tmux":
        slot = str(record.get("slot") or "")
        if not slot:
            return f"（{target_id} 已下线且无固定窗, 无法自动恢复——手工 respawn 后再发）"
        cwd = str(record.get("cwd") or "")
        if not tmuxio.respawn_window(slot, command) and not tmuxio.recreate_window(slot, cwd, command):
            return f"（{target_id} 已下线, respawn {slot} 失败——手工恢复后再发）"
        return f"（{target_id} 已下线, 已 respawn {slot} 恢复对话({' '.join(command)}), 信入队待其上线注入）"
    if backend == "direct":
        try:
            subprocess.Popen(
                [shutil.which(proc) or proc, *resume_args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return f"（{target_id} 已下线, 后台拉起失败——手工恢复后再发）"
        return f"（{target_id} 已下线, 已后台拉起恢复, 信入队待其上线注入）"
    return ""


def new_fingerprint() -> str:
    return f"conv-{uuid.uuid4().hex[:10]}"


HUB_CMD_ENV = "A2A_HUB_CMD"
HUB_ENTRY = Path(__file__).resolve().parent.parent / "hub" / "hub.py"


def hub_boot_command() -> list[str] | None:
    raw = os.environ.get(HUB_CMD_ENV, "").strip()
    parts = shlex.split(raw) if raw else [sys.executable, str(HUB_ENTRY)]
    if not parts:
        return None
    if os.name != "nt" and any(part.endswith(".exe") for part in parts):
        return None
    return parts


def boot_hub_if_absent(root: Path) -> None:
    try:
        handle = open(root / paths.HUB_LOCK_FILE, "w")
    except OSError:
        return
    try:
        lockfile.lock_exclusive(handle)
    except OSError:
        handle.close()
        return
    detach = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    }
    try:
        command = hub_boot_command()
        if command:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **detach,
            )
    except Exception:
        return
    finally:
        lockfile.unlock(handle)
        handle.close()


def touch_heartbeat() -> None:
    path = paths.mailbox_root() / paths.MCP_HEARTBEAT_FILE
    try:
        os.utime(path, None)
    except OSError:
        try:
            path.touch()
        except OSError:
            pass


def self_register() -> dict:
    record = register_record()
    boot_hub_if_absent(paths.mailbox_root())
    touch_heartbeat()
    return record


FINGERPRINT_ENV = "A2A_FINGERPRINT"


def continued_fingerprint() -> str:
    raw = os.environ.get(FINGERPRINT_ENV, "").strip()
    return raw if 0 < len(raw) <= 64 else new_fingerprint()


def codex_anchor_fields() -> dict:
    which = shutil.which("codex")
    thread = codexq.thread_from_ancestors()
    pane_override = ""
    if not thread and which and not os.environ.get(detect.PANELESS_ENV):
        tui = codexq.locate_tui(os.getcwd())
        if tui:
            thread = tui.get("thread") or ""
            pane_override = tui.get("pane_id") or ""
    if not thread:
        win = codexq.locate_win(os.getcwd())
        if win:
            return win
    if not which:
        return {}
    fields = {"codex_bin": which, "codex_home": str(codexq.default_codex_home())}
    if pane_override:
        fields["codex_pane_id"] = pane_override
    if thread:
        fields["codex_thread"] = thread
    return fields


def attach_instance_entry(record: dict, held: dict | None, cli: str, pane_id: str, pane_pid: str, slot: str) -> dict:
    key = instance_key_for(cli, pane_id)
    if not key or not pane_id:
        return record
    instances = {}
    for entry_key, entry in (dict(held or {}).get("instances") or {}).items():
        if pane_pid and str(entry.get("pane_pid") or "") == pane_pid:
            continue
        instances[entry_key] = entry
    instances[key] = {
        "session_id": session_env_id(),
        "pane_id": pane_id,
        "pane_pid": pane_pid,
        "slot": slot,
        "fingerprint": record.get("fingerprint"),
        "last_seen": time.time(),
    }
    record["instances"] = instances
    return record


def adopt_held_record(root, agent_id: str, held: dict, cli: str, host: str, pane_id: str, pane_pid: str, slot: str, display_name: str, cwd: str, anchor: dict) -> dict:
    record = dict(held)
    record.update(
        {
            "cli": cli,
            "host": host,
            "pane_id": pane_id,
            "pane_pid": pane_pid,
            "slot": slot,
            "display_name": display_name,
            "cwd": cwd,
            "peer_of": peer_of_from_env() or str(held.get("peer_of") or ""),
            "ssh_alias": (
                ""
                if anchor.get("codex_thread")
                else (
                    ssh_alias_from_env()
                    if tmuxio.pane_pid_matches(pane_id, pane_pid)
                    else str(held.get("ssh_alias") or "")
                )
            ),
            **anchor,
            "last_seen": time.time(),
        }
    )
    record = attach_instance_entry(record, held, cli, pane_id, pane_pid, slot)
    registry.upsert(root, agent_id, record)
    return record


def register_record() -> dict:
    root = paths.mailbox_root()
    paths.ensure_layout(root)
    pane_id = detect.current_pane_id()
    cli = detect.detect_cli()
    host = detect.local_host()
    cwd = os.getcwd()
    anchor = codex_anchor_fields() if cli == "codex" else {}
    pane_id = str(anchor.pop("codex_pane_id", "") or "") or pane_id
    slot = tmuxio.pane_slot(pane_id) if pane_id else ""
    pane_pid = tmuxio.pane_pid(pane_id) if pane_id else ""
    display_name = tmuxio.pane_window_name(pane_id) if pane_id else ""
    existing = registry.load(root)["agents"]
    session_proof = session_env_id()
    if session_proof:
        for agent_id, held in existing.items():
            for entry in (held.get("instances") or {}).values():
                if str(entry.get("session_id") or "") == session_proof:
                    return adopt_held_record(root, agent_id, held, cli, host, pane_id, pane_pid, slot, display_name, cwd, anchor)
    for agent_id, held in existing.items():
        if not slot or held.get("slot") != slot:
            continue
        if str(held.get("cwd") or "") != cwd:
            continue
        held_pid = str(held.get("pane_pid") or "")
        if held_pid and held_pid != pane_pid and tmuxio.pane_pid_matches(str(held.get("pane_id") or ""), held_pid):
            raise RuntimeError(f"slot {slot} 已有活跃对话({agent_id}), 同 tmux 名禁止双开——换窗名再启动")
        return adopt_held_record(root, agent_id, held, cli, host, pane_id, pane_pid, slot, display_name, cwd, anchor)
    agent_id = detect.build_agent_id(cli, cwd)
    if not os.environ.get(detect.AGENT_ID_ENV, "").strip():
        anchored_ids = [
            aid
            for aid, held_rec in existing.items()
            if aid != agent_id
            and held_rec.get("codex_home")
            and not held_rec.get("ssh_alias")
            and held_rec.get("cwd") == cwd
            and held_rec.get("host") == host
        ]
        if len(anchored_ids) == 1:
            agent_id = anchored_ids[0]
            cli = str(existing[agent_id].get("cli") or cli)
    held = existing.get(agent_id)
    if held is not None:
        held_slot = str(held.get("slot") or "")
        held_ssh = str(held.get("ssh_alias") or "")
        if (
            held_slot
            and slot
            and held_slot != slot
            and tmuxio.pane_pid_matches(str(held.get("pane_id") or ""), str(held.get("pane_pid") or ""), held_ssh or None)
            and not instance_key_for(cli, pane_id)
        ):
            raise RuntimeError(
                f"agent_id {agent_id} 已在 slot {held_slot} 活跃, 异窗双开被拒——"
                "回原窗口工作, 或等其退出后再启动"
            )
    record = {
        "agent_id": agent_id,
        "cli": cli,
        "host": host,
        "tailnet_host": detect.tailnet_host(),
        "pane_id": pane_id,
        "pane_pid": pane_pid,
        "slot": slot,
        "display_name": display_name,
        "fingerprint": continued_fingerprint(),
        "cwd": cwd,
        "started_at": time.time(),
        "spawn_cmd": spawn_cmd_from_env(),
        "peer_of": peer_of_from_env(),
        **anchor,
        "ssh_alias": "" if anchor.get("codex_thread") else ssh_alias_from_env(),
    }
    if held is not None:
        record["fingerprint"] = str(held.get("fingerprint") or record["fingerprint"])
        record["started_at"] = held.get("started_at") or record["started_at"]
        for key in ("codex_bin", "codex_home", "codex_thread"):
            if held.get(key) and not record.get(key):
                record[key] = held[key]
        if isinstance(held.get("spawn_cmd"), list) and held["spawn_cmd"]:
            record["spawn_cmd"] = held["spawn_cmd"]
        if (
            held.get("ssh_alias")
            and not anchor.get("codex_thread")
            and not record.get("codex_thread")
            and (not pane_id or not tmuxio.pane_pid_matches(pane_id, pane_pid))
        ):
            record["ssh_alias"] = held["ssh_alias"]
        if record.get("codex_thread"):
            record["ssh_alias"] = ""
    record = attach_instance_entry(record, held, cli, pane_id, pane_pid, slot)
    registry.upsert(root, agent_id, record)
    return record


def result_ok(payload: dict) -> str:
    payload["ok"] = True
    return json.dumps(payload, ensure_ascii=False)


def result_error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def send_gate_error(self_id: str, self_record: dict | None, target: dict, to: str) -> str:
    peer_of = str((self_record or {}).get("peer_of") or "")
    if peer_of and to != peer_of:
        return f"subagent 发送锁: 本端声明为 {peer_of} 的 subagent, 仅可对主 agent 收发(当前 to={to})"
    if target.get("group_only"):
        allowed = target.get("allowed_senders") or []
        if self_id not in allowed:
            group = str(target.get("group") or "")
            tag = f"({group})" if group else ""
            return (
                f"{to}{tag} 为 group-only 收件人, 发件方未准入——"
                "先 mail_group(action=join, agent_id=门主) 申请, 门主 mail_group(action=admit) 通过后再发"
            )
    return ""


def join_request_path(root: Path, to: str, sender: str) -> Path:
    return root / paths.JOIN_DIR / to / f"{sender}.json"


def do_request_join(self_id: str, to: str, note: str = "") -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    if registry.get(root, to) is None:
        return result_error(f"目标 {to} 未注册，先调 mail_who 查询在册 agent")
    if self_id == to:
        return result_error("不能向自己申请加入")
    target = registry.get(root, to)
    if self_id in (target.get("allowed_senders") or []):
        return result_ok({"requested": to, "already_admitted": True})
    if not sshio.SAFE_ID_RE.match(self_id):
        return result_error("agent_id 格式不合法")
    request = {"from": self_id, "to": to, "note": (note or "").strip()[:200], "ts": time.time()}
    alias = str(target.get("ssh_alias") or "")
    if alias:
        status = sshio.write_remote_join(alias, to, self_id, request)
        if status != sshio.REMOTE_OK:
            return result_error(f"申请直投 {alias} 失败({status})——稍后重试")
        registry.touch(root, self_id)
        return result_ok({"requested": to, "relayed_to": alias, "visible_to": "对方 mail_group(action=pending) 可见"})
    request_path = join_request_path(root, to, self_id)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(request_path, request)
    registry.touch(root, self_id)
    return result_ok({"requested": to, "visible_to": "对方 mail_group(action=pending) 可见"})


def do_pending_joins(self_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    requests = []
    for path in sorted((root / paths.JOIN_DIR / self_id).glob("*.json")):
        payload = storage.read_json(path)
        if payload:
            requests.append(payload)
    registry.touch(root, self_id)
    return result_ok({"requests": requests})


def do_admit(self_id: str, agent_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    if registry.get(root, agent_id) is None:
        return result_error(f"{agent_id} 未注册")
    record = dict(registry.get(root, self_id) or {})
    allowed = [str(item) for item in (record.get("allowed_senders") or [])]
    if agent_id not in allowed:
        allowed.append(agent_id)
    record["allowed_senders"] = allowed
    registry.upsert(root, self_id, record)
    join_request_path(root, self_id, agent_id).unlink(missing_ok=True)
    payload = {"admitted": agent_id, "members": len(allowed)}
    if not record.get("group_only"):
        payload["hint"] = "尚未 mail_group(action=gate, group_only=true)——当前名单未生效, 全网仍可发"
    return result_ok(payload)


def do_revoke(self_id: str, agent_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    record = dict(registry.get(root, self_id) or {})
    allowed = [str(item) for item in (record.get("allowed_senders") or [])]
    if agent_id not in allowed:
        return result_error(f"{agent_id} 不在准入名单")
    allowed.remove(agent_id)
    record["allowed_senders"] = allowed
    registry.upsert(root, self_id, record)
    return result_ok({"revoked": agent_id, "members": len(allowed)})


def do_group_gate(self_id: str, group_only: bool, group: str = "") -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    record = dict(registry.get(root, self_id) or {})
    record["group_only"] = bool(group_only)
    if group:
        record["group"] = group.strip()
    registry.upsert(root, self_id, record)
    allowed = [str(item) for item in (record.get("allowed_senders") or [])]
    return result_ok({"group_only": bool(group_only), "group": record.get("group", ""), "members": len(allowed)})


PEER_UNREACHABLE_CACHE: dict = {}
PEER_UNREACHABLE_TTL = 30.0


def peer_reachable(alias: str, now: float) -> bool:
    marked_at = PEER_UNREACHABLE_CACHE.get(alias, 0.0)
    return now - marked_at >= PEER_UNREACHABLE_TTL


def find_remote_origin(root: Path, msg_id: str) -> tuple[dict | None, list]:
    if not sshio.SAFE_ID_RE.match(msg_id):
        return None, []
    now = time.time()
    unreachable: list = []
    for alias in peers.load_peers(root):
        if not peer_reachable(alias, now):
            unreachable.append(alias)
            continue
        for relative in (f".agents-mailbox/queue/*/{msg_id}.msg", f".agents-mailbox/history/{msg_id}.json"):
            status, payload = sshio.read_remote_json_status(alias, relative)
            if status == sshio.REMOTE_OK and payload.get("msg_id") == msg_id:
                return payload, []
            if status == sshio.REMOTE_UNREACHABLE:
                PEER_UNREACHABLE_CACHE[alias] = now
                unreachable.append(alias)
                break
    return None, unreachable


IN_REPLY_TO_ABSENT_TOKENS = ("", "null", "none", "None", "NULL")


def normalize_in_reply_to(in_reply_to) -> str:
    if in_reply_to is None:
        return ""
    return "" if str(in_reply_to).strip() in IN_REPLY_TO_ABSENT_TOKENS else str(in_reply_to).strip()


def do_send(self_id: str, to: str, body: str, in_reply_to=None, context: str = "", expect_reply: bool = False) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    body = (body or "").strip()
    if not body:
        return result_error("body 为空——没有内容的消息无法投递")
    to, to_instance = split_instance_target(to)
    if registry.get(root, to) is None:
        return result_error(f"目标 {to} 未注册，先调 mail_who 查询在册 agent")
    target = registry.get(root, to)
    if to_instance and to_instance not in (target.get("instances") or {}):
        live = sorted((target.get("instances") or {}).keys())
        return result_error(f"{to}@{to_instance} 实例不存在——当前在册实例: {live or '无'}")
    gate = send_gate_error(self_id, registry.get(root, self_id), target, to)
    if gate:
        return result_error(gate)
    in_reply_to = normalize_in_reply_to(in_reply_to)
    hint = ""
    hop = 1
    acked_origin = False
    if in_reply_to:
        origin = storage.find_msg(root, in_reply_to)
        unreachable: list = []
        if origin is None:
            origin, unreachable = find_remote_origin(root, in_reply_to)
        if origin is None:
            if unreachable:
                return result_error(
                    f"peer {', '.join(unreachable)} 不可达，in_reply_to={in_reply_to} 的锚点无法验证——"
                    "稍后重试（peer 恢复后可解析），或去掉 in_reply_to 直接发送"
                )
            return result_error(
                f"in_reply_to={in_reply_to} 在本机与 peer 的队列及已投递历史均未找到"
                "（不存在或已过期）；回执场景可直接去掉 in_reply_to 发送，"
                f"引用时请用 mail_read 返回的 msg_id（形如 1a89a37e1930），不要手写 null"
            )
        hop = int(origin.get("hop", 1)) + 1
        if origin.get("to") == self_id:
            origin_ack_id = str(origin.get("ack_id") or "")
            if origin_ack_id and not storage.ack_exists(root, origin_ack_id):
                storage.write_ack(root, origin_ack_id, self_id)
                acked_origin = True
    elif msgfmt.is_revival_request(body):
        if not msgfmt.has_rebuild_clue(body):
            hint = "续传类消息补线索文件路径(含 /)可省收件方一轮追问"
    elif not msgfmt.has_actionable_directive(body) and not msgfmt.is_reply_receipt(body):
        hint = "body 未见动词性指令, 收件方可能需要一轮澄清"
    if not target.get("pane_id") and not target.get("spawn_cmd"):
        if str(target.get("cli") or "") in detect.PULL_ONLY_CLIS:
            hint = hint or "拉取型收件方(无 pane), 邮件入队待其 mail_poll 拉取"
        elif codexq.anchors_complete(target):
            hint = hint or "daemon 队列通道收件方(无 pane), 经 codex queue 原生投递"
        else:
            hint = hint or "收件方无 pane 锚点(tmux 外注册), 投递将滞留直至其在 tmux 内激活"
    allowed, retry_after = storage.rate_gate(root, self_id, to)
    if not allowed:
        return result_error(
            f"速率限制：{self_id} → {to} 在 {storage.RATE_WINDOW_SECONDS:g}s 内"
            f"超过 {storage.RATE_MAX_PER_WINDOW} 条, {retry_after:.0f}s 后可重试"
        )
    msg_id, ack_id = storage.new_ids()
    wake_text = msgfmt.compose_wake(self_id, msg_id, body, expect_reply)
    revived = respawn_offline_target(root, to)
    if revived:
        hint = (hint + " " + revived).strip() if hint else revived
    envelope = {
        "msg_id": msg_id,
        "ack_id": ack_id,
        "from": self_id,
        "to": to,
        "to_instance": to_instance,
        "body": body,
        "context": context or "",
        "in_reply_to": in_reply_to,
        "hop": hop,
        "schema_version": SCHEMA_VERSION,
        "created_at": time.time(),
        "expect_reply": bool(expect_reply),
        "hint": hint,
        "wake_text": wake_text,
    }
    remote_home = ""
    if not target.get("pane_id") and not target.get("spawn_cmd"):
        alias = str(target.get("ssh_alias") or "")
        if alias and codexq.anchors_complete(target):
            remote_home = alias
    if remote_home:
        status = sshio.write_remote_envelope(remote_home, envelope)
        if status == sshio.REMOTE_OK:
            registry.touch(root, self_id)
            payload = {"msg_id": msg_id, "relayed_to": remote_home}
            if hint:
                payload["hint"] = hint
            return result_ok(payload)
        hint = f"远端入队失败({status}), 已回落本机队列待联邦拉取"
    storage.enqueue(root, envelope)
    registry.touch(root, self_id)
    receipt = {"msg_id": msg_id}
    if acked_origin:
        receipt["acked_origin"] = True
    if hint:
        receipt["hint"] = hint
    if hop > msgfmt.HOP_WARNING_THRESHOLD:
        receipt["hop_warning"] = f"hop={hop} 超 {msgfmt.HOP_WARNING_THRESHOLD}, 疑似转发风暴——请核查对话回路"
    return result_ok(receipt)


def summary_head(body: str) -> str:
    return " ".join(body.split())[:80]


def do_poll(self_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    items = []
    for envelope in storage.list_queue(root, self_id):
        item = {
            "msg_id": envelope.get("msg_id"),
            "from": envelope.get("from"),
            "created_at": envelope.get("created_at"),
            "head": summary_head(envelope.get("body", "")),
        }
        in_reply_to = envelope.get("in_reply_to")
        if in_reply_to:
            item["in_reply_to"] = in_reply_to
        hop = envelope.get("hop")
        if hop and hop != 1:
            item["hop"] = hop
        items.append(item)
    registry.touch(root, self_id)
    return result_ok({"messages": items})


def do_read(self_id: str, msg_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    envelope = storage.read_msg(root, self_id, msg_id)
    if envelope is None:
        origin, _unreachable = find_remote_origin(root, msg_id)
        if origin is not None and str(origin.get("to") or "") == self_id:
            envelope = origin
    if envelope is None:
        return result_error(f"{msg_id} 不在自己的邮箱队列")
    registry.touch(root, self_id)
    payload = {
        "msg_id": envelope.get("msg_id"),
        "from": envelope.get("from"),
        "ack_id": envelope.get("ack_id"),
        "in_reply_to": envelope.get("in_reply_to") or "",
        "body": envelope.get("body"),
        "context": envelope.get("context") or "",
    }
    if envelope.get("expect_reply"):
        payload["expect_reply"] = True
    return result_ok(payload)


def do_ack(self_id: str, ack_id: str) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    if storage.ack_exists(root, ack_id):
        registry.touch(root, self_id)
        return result_ok({"ack_id": ack_id, "already_acked": True})
    envelope = storage.find_ack_target(root, ack_id)
    if (
        envelope is not None
        and envelope.get("to") != self_id
        and not storage.msg_in_queue(root, self_id, str(envelope.get("msg_id") or ""))
    ):
        return result_error(f"{ack_id} 是发给 {envelope.get('to')} 的消息，只能由接收方确认")
    storage.write_ack(root, ack_id, self_id)
    if envelope is not None:
        storage.archive_msg(root, self_id, str(envelope.get("msg_id") or ""))
    registry.touch(root, self_id)
    return result_ok({"ack_id": ack_id, "already_acked": False, "self_attested": envelope is None})


def do_who(self_id: str, include_all: bool = False) -> str:
    touch_heartbeat()
    root = paths.mailbox_root()
    results = federation.pull_all(root)
    failed = {str(item.get("peer")) for item in results if not item.get("ok")}
    peer_states = [
        {"peer": item.get("peer"), "ok": item.get("ok"), "status": item.get("status")}
        for item in results
    ]
    liveness = storage.load_online(root)
    roster = []
    for agent_id, record in registry.load(root)["agents"].items():
        alive = liveness.get(agent_id)
        state = "unknown" if alive is None else ("active" if alive else "stale")
        remote = bool(str(record.get("ssh_alias") or ""))
        if not include_all and state == "stale":
            continue
        entry = {
            "agent_id": agent_id,
            "display_name": record.get("display_name") or "",
            "cwd": record.get("cwd"),
            "state": state,
        }
        group = str(record.get("group") or "")
        if group:
            entry["group"] = group
        if record.get("group_only"):
            entry["group_only"] = True
            entry["members"] = len(record.get("allowed_senders") or [])
        if str(record.get("peer_of") or ""):
            entry["subagent_of"] = record["peer_of"]
        if agent_id == self_id and record.get("group_only"):
            entry["allowed_senders"] = [str(item) for item in (record.get("allowed_senders") or [])]
        if str(record.get("ssh_alias") or "") in failed:
            entry["peer_down"] = True
        roster.append(entry)
        if state == "active" and not remote:
            for inst_key, inst in sorted((record.get("instances") or {}).items()):
                roster.append(
                    {
                        "agent_id": f"{agent_id}@{inst_key}",
                        "instance_of": agent_id,
                        "state": "active",
                        "slot": inst.get("slot") or "",
                        "pane_id": inst.get("pane_id") or "",
                        "session_id": inst.get("session_id") or "",
                    }
                )
    registry.touch(root, self_id)
    return result_ok({"agents": roster, "peers": peer_states})


@mcp.tool()
def mail_send(to: str, body: str, in_reply_to: str | None = None, context: str = "", expect_reply: bool = False) -> str:
    """发消息给另一 agent。in_reply_to 用 mail_read 返回的 msg_id（可自动确认原消息）；expect_reply=True 唤醒词尾加『[需回函]』。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_send(SELF["agent_id"], to, body, in_reply_to, context, expect_reply)


@mcp.tool()
def mail_poll() -> str:
    """列出自己邮箱待处理消息的摘要（不消费，可反复查）。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_poll(SELF["agent_id"])


@mcp.tool()
def mail_read(msg_id: str) -> str:
    """读自己邮箱一条消息全文（含 ack_id——业务确认用）。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_read(SELF["agent_id"], msg_id)


@mcp.tool()
def mail_ack(ack_id: str) -> str:
    """确认一条消息（幂等）。ack_id 用 mail_read 返回的；跨主机传输不可见时自证落盘 self_attested。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_ack(SELF["agent_id"], ack_id)


@mcp.tool()
def mail_who(all: bool = False) -> str:
    """列出在册 agent（默认只列在线 active，含同目录分身行 agent_id@session短码 可定向发信；all=true 附已下线 stale）。group-only 标记与成员计数，附联邦 peers 状态。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_who(SELF["agent_id"], include_all=bool(all))


GROUP_ACTIONS = ("join", "pending", "admit", "revoke", "gate")
GROUP_USAGE = (
    "未知或缺失参数——用法: mail_group(action=join, agent_id=门主agent_id, note=来意) "
    "| mail_group(action=pending) | mail_group(action=admit, agent_id=申请者) "
    "| mail_group(action=revoke, agent_id=成员) "
    "| mail_group(action=gate, group_only=true/false, group=展示名)"
)


def do_group(self_id: str, action: str, agent_id: str = "", note: str = "", group: str = "", group_only: bool = False) -> str:
    touch_heartbeat()
    normalized = (action or "").strip().lower()
    if normalized == "join":
        if not agent_id:
            return result_error(GROUP_USAGE)
        return do_request_join(self_id, agent_id, note)
    if normalized == "pending":
        return do_pending_joins(self_id)
    if normalized == "admit":
        if not agent_id:
            return result_error(GROUP_USAGE)
        return do_admit(self_id, agent_id)
    if normalized == "revoke":
        if not agent_id:
            return result_error(GROUP_USAGE)
        return do_revoke(self_id, agent_id)
    if normalized == "gate":
        return do_group_gate(self_id, group_only, group)
    return result_error(GROUP_USAGE)


@mcp.tool()
def mail_group(action: str, agent_id: str = "", note: str = "", group: str = "", group_only: bool = False) -> str:
    """群组权限五合一。action=join 申请加入对方 group(agent_id=门主,note=来意)；action=pending 列自己的待审申请；action=admit 批准 agent_id 可发给自己；action=revoke 移出 agent_id；action=gate 开关仅准入名单收件闸(group_only=true 开,group 为展示名)。错误返回含完整用法。"""
    blocked = guard_error()
    if blocked:
        return result_error(blocked)
    return do_group(SELF["agent_id"], action, agent_id, note, group, group_only)


def main() -> None:
    global SELF, REGISTER_FAILURE
    try:
        SELF = self_register()
    except Exception as exc:
        REGISTER_FAILURE = str(exc)
        print(f"mailbox self-register failed: {exc}", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
