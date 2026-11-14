from common import codexq, peers, registry, sshio, storage


def pull_inbound_msgs(root, alias: str, local_ids: set, envelopes: list) -> int:
    local_reg = registry.load(root)["agents"]
    pulled = 0
    for envelope in envelopes:
        try:
            to = str(envelope.get("to") or "")
            msg_id = str(envelope.get("msg_id") or "")
            if to not in local_ids or not sshio.SAFE_ID_RE.match(msg_id):
                continue
            if not storage.to_epoch(envelope.get("last_injected_at")) > 0:
                continue
            home_record = local_reg.get(to) or {}
            if codexq.anchors_complete(home_record):
                continue
            if (
                storage.read_msg(root, to, msg_id) is not None
                or (root / "queue" / to / f"{msg_id}.failed").exists()
                or (root / "history" / f"{msg_id}.json").exists()
            ):
                continue
            envelope.setdefault("home_relay_first_at", storage.to_epoch(envelope.get("last_injected_at")))
            storage.enqueue(root, envelope)
            pulled += 1
        except (TypeError, ValueError, OSError):
            continue
    return pulled


def settle_mirrored_msgs(root, alias: str, local_ids: set, envelopes: list, settled_map: dict) -> int:
    origin_ids = {str(envelope.get("msg_id") or "") for envelope in envelopes if isinstance(envelope, dict)}
    settled = 0
    for agent_id in local_ids:
        for envelope in storage.list_queue(root, agent_id):
            msg_id = str(envelope.get("msg_id") or "")
            if not msg_id or msg_id in origin_ids:
                continue
            if not storage.to_epoch(envelope.get("last_injected_at")) > 0:
                continue
            if storage.to_epoch(envelope.get("home_relay_first_at")) > 0:
                continue
            outcome = settled_map.get(msg_id)
            if outcome == "archived":
                storage.archive_msg(root, agent_id, msg_id)
                settled += 1
                continue
            if outcome == "failed":
                storage.mark_failed(root, agent_id, msg_id)
                settled += 1
    return settled


FED_MERGED_EXEC_FIELDS = (
    "spawn_cmd",
    "codex_bin",
    "codex_home",
    "codex_thread",
    "rpc_inbox_url",
    "magpie_hook",
)


def sanitize_merged_record(record: dict) -> dict:
    clean = {key: value for key, value in record.items() if key not in FED_MERGED_EXEC_FIELDS}
    return clean


def pull_peer(root, alias: str) -> dict:
    local_ids = {
        agent_id
        for agent_id, record in registry.load(root)["agents"].items()
        if not str(record.get("ssh_alias") or "")
    }
    probe_ids = [
        str(envelope.get("msg_id") or "")
        for agent_id in local_ids
        for envelope in storage.list_queue(root, agent_id)
        if str(envelope.get("msg_id") or "")
    ]
    status, snapshot = sshio.read_remote_federation_snapshot(alias, probe_ids)
    payload = (snapshot or {}).get("registry")
    if status != sshio.REMOTE_OK or not isinstance(payload, dict) or not isinstance(payload.get("agents"), dict):
        return {"peer": alias, "ok": False, "merged": 0, "pulled": 0, "status": status}
    envelopes = [item for item in (snapshot or {}).get("queue") or [] if isinstance(item, dict)]
    settled_map = (snapshot or {}).get("settled") or {}
    merged_records = {}
    for agent_id, record in payload["agents"].items():
        if not isinstance(record, dict):
            continue
        stamped = str(record.get("ssh_alias") or "")
        if stamped and stamped != alias:
            continue
        remote_record = sanitize_merged_record(record)
        remote_record["ssh_alias"] = alias
        merged_records[agent_id] = remote_record
    registry.apply_batch(root, merged_records)
    pulled = pull_inbound_msgs(root, alias, local_ids, envelopes)
    settled = settle_mirrored_msgs(root, alias, local_ids, envelopes, settled_map)
    return {"peer": alias, "ok": True, "merged": len(merged_records), "pulled": pulled, "status": status}


def pull_all(root) -> list:
    return [pull_peer(root, alias) for alias in peers.load_peers(root)]
