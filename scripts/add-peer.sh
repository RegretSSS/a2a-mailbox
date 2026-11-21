#!/usr/bin/env bash
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
ALIAS="${1:?用法: scripts/add-peer.sh <对方ssh别名> [本机对外别名](缺省自动探测)}"
SELF_ALIAS="${2:-$(python3 -c "import sys; sys.path.insert(0, '${REPO}'); from common import detect; print(detect.tailscale_self_name() or detect.local_host().split('.')[0])")}"
ROOT="${A2A_MAILBOX_ROOT:-$HOME/.agents-mailbox}"

probe_peer() {
  ssh -o BatchMode=yes -o ConnectTimeout=3 "$1" true >/dev/null 2>&1
}

if ! probe_peer "$ALIAS"; then
  echo ">> ssh $ALIAS 免密不通, 尝试 ssh-copy-id(可能要输一次密码)"
  ssh-copy-id "$ALIAS" >/dev/null
  probe_peer "$ALIAS" || { echo "!! $ALIAS 仍不可达——先解决网络/别名(tailscale up 或 ~/.ssh/config HostName), 再重跑"; exit 1; }
fi
echo ">> ssh $ALIAS 免密 OK"

python3 - "$ROOT" "$REPO" "$ALIAS" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from common import peers

root = Path(sys.argv[1])
alias = sys.argv[3]
if peers.add_peer(root, alias):
    print(f">> 本机 peers.json 已加 {alias}")
else:
    print(f">> 本机 peers.json 已有 {alias}(幂等跳过)")
PY

ssh "$ALIAS" python3 - "$SELF_ALIAS" <<'PY'
import json
import sys
from pathlib import Path

root = Path.home() / ".agents-mailbox"
path = root / "peers.json"
try:
    payload = json.loads(path.read_text())
except (OSError, ValueError):
    payload = {"peers": []}
alias = sys.argv[1]
if alias not in payload.get("peers", []):
    payload.setdefault("peers", []).append(alias)
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f">> 对端 peers.json 已加 {alias}")
else:
    print(f">> 对端 peers.json 已有 {alias}(幂等跳过)")
PY

RESULT=$(python3 - "$ROOT" "$REPO" "$ALIAS" <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from common import federation

print(json.dumps(federation.pull_peer(Path(sys.argv[1]), sys.argv[3]), ensure_ascii=False))
PY
)
echo ">> pull 验证: $RESULT"
echo "$RESULT" | grep -q '"ok": true' || { echo "!! 拉取失败——对端需先部署本仓(hub/registry 同结构), 部署后重跑本脚本验证"; exit 1; }
echo ">> 联邦就绪: $ALIAS <-> $SELF_ALIAS"
