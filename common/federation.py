from common import codexq, paths, peers, registry, sshio, storage


def pull_inbound_msgs(root, alias: str, local_ids: set) -> int:
    status, envelopes = sshio.read_remote_queue_msgs(alias)
    if status != sshio.REMOTE_OK:
        return 0
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
            storage.enqueue(root, envelope)
            pulled += 1
        except (TypeError, ValueError, OSError):
            continue
    return pulled


def settle_mirrored_msgs(root, alias: str, local_ids: set) -> int:
    status, envelopes = sshio.read_remote_queue_msgs(alias)
    if status != sshio.REMOTE_OK:
        return 0
    origin_ids = {str(envelope.get("msg_id") or "") for envelope in envelopes if isinstance(envelope, dict)}
    settled = 0
    for agent_id in local_ids:
        for envelope in storage.list_queue(root, agent_id):
            msg_id = str(envelope.get("msg_id") or "")
            if not msg_id or msg_id in origin_ids:
                continue
            if not storage.to_epoch(envelope.get("last_injected_at")) > 0:
                continue
            archived, _ = sshio.read_remote_json_status(alias, f".agents-mailbox/{paths.HISTORY_DIR}/{msg_id}.json")
            if archived == sshio.REMOTE_OK:
                storage.archive_msg(root, agent_id, msg_id)
                settled += 1
                continue
            failed, _ = sshio.read_remote_json_status(
                alias, f".agents-mailbox/{paths.QUEUE_DIR}/{agent_id}/{msg_id}.failed"
            )
            if failed == sshio.REMOTE_OK:
                storage.mark_failed(root, agent_id, msg_id)
                settled += 1
    return settled


def pull_peer(root, alias: str) -> dict:
    local_ids = set(registry.load(root)["agents"])
    status, payload = sshio.read_remote_json_status(alias, f".agents-mailbox/{paths.REGISTRY_FILE}")
    if status != sshio.REMOTE_OK or not isinstance(payload.get("agents"), dict):
        return {"peer": alias, "ok": False, "merged": 0, "pulled": 0, "status": status}
    merged = 0
    for agent_id, record in payload["agents"].items():
        if not isinstance(record, dict):
            continue
        stamped = str(record.get("ssh_alias") or "")
        if stamped and stamped != alias:
            continue
        remote_record = dict(record)
        remote_record["ssh_alias"] = alias
        registry.upsert(root, agent_id, remote_record)
        merged += 1
    pulled = pull_inbound_msgs(root, alias, local_ids)
    settle_mirrored_msgs(root, alias, local_ids)
    return {"peer": alias, "ok": True, "merged": merged, "pulled": pulled, "status": status}


def pull_all(root) -> list:
    return [pull_peer(root, alias) for alias in peers.load_peers(root)]


def failed_peers(results: list) -> list:
    return [item.get("peer") for item in results if not item.get("ok")]
