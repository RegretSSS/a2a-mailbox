import importlib.util
import os
import sys
import threading
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common import paths, registry

BIND_ENV = "A2A_MCP_HTTP_BIND"
PORT_ENV = "A2A_MCP_HTTP_PORT"
TOKEN_FILENAME = "http-token"
KICK_FILENAME = "fed-pull-now"
DEFAULT_PORT = 8765

MODULE_LOAD_LOCK = threading.Lock()
MODULES: dict[tuple[str, str], object] = {}
TOKEN_CACHE: dict[str, dict] = {}
REGISTRY_CACHE: dict[str, dict] = {}


def loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def token_state(root: Path) -> dict:
    path = root / TOKEN_FILENAME
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"mtime": None, "token": "", "expected": b""}
    cached = TOKEN_CACHE.get(key)
    if cached is not None and cached["mtime"] == mtime:
        return cached
    try:
        token = path.read_text().strip()
    except (OSError, ValueError):
        token = ""
    state = {"mtime": mtime, "token": token, "expected": f"Bearer {token}".encode()}
    TOKEN_CACHE[key] = state
    return state


def registered_ids(root: Path) -> set:
    path = registry.registry_file(root)
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return set()
    cached = REGISTRY_CACHE.get(key)
    if cached is not None and cached["mtime"] == mtime:
        return cached["agents"]
    agents = set(registry.load(root)["agents"])
    REGISTRY_CACHE[key] = {"mtime": mtime, "agents": agents}
    return agents


def load_agent_module(root: Path, agent_id: str):
    record = registry.get(root, agent_id)
    if not record:
        return None
    with MODULE_LOAD_LOCK:
        cache_key = (str(root), agent_id)
        cached = MODULES.get(cache_key)
        if cached is not None:
            return cached
        spec = importlib.util.spec_from_file_location(
            f"mailbox_http_{agent_id.replace('-', '_')}",
            str(Path(__file__).resolve().parent / "mailbox_mcp.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.SELF = dict(record)
        MODULES[cache_key] = module
        return module


async def deny(scope, receive, send, message: str, status: int):
    await JSONResponse({"error": message}, status_code=status)(scope, receive, send)


class GatewayGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope["app"].state
        path = scope.get("path", "")
        current_token = token_state(state.root)
        if not loopback(state.bind_host) and not current_token["token"]:
            await deny(scope, receive, send, "token required for non-loopback bind", 503)
            return
        if current_token["token"] and not (
            path == "/healthz" and loopback(state.bind_host)
        ):
            auth = None
            for key, value in scope.get("headers", []):
                if key == b"authorization":
                    auth = value
                    break
            if auth != current_token["expected"]:
                await deny(scope, receive, send, "unauthorized", 401)
                return
        segments = path.lstrip("/").split("/", 1)
        if len(segments) == 2 and segments[1].rstrip("/") == "mcp":
            if segments[0] not in registered_ids(state.root):
                await deny(scope, receive, send, "agent not registered", 404)
                return
        await self.app(scope, receive, send)


async def healthz(request):
    mounted = set(request.app.state.agents)
    return JSONResponse(
        {"ok": True, "agents": sorted(mounted & registered_ids(request.app.state.root))}
    )


async def kick(request):
    (request.app.state.root / KICK_FILENAME).touch()
    return JSONResponse({"ok": True})


def build_app(root: Path, bind_host: str | None = None) -> Starlette:
    subs = []
    agents_snapshot = registry.load(root)["agents"]
    for agent_id in sorted(agents_snapshot):
        module = load_agent_module(root, agent_id)
        if module is not None:
            subs.append((agent_id, module.mcp.http_app(path="/mcp")))
    if not subs:
        print(
            f"a2a-mailbox-http: registry 无在册档({registry.registry_file(root)}), "
            "全部 agent 路由将 404——若非新装机请检查 registry 完整性",
            file=sys.stderr,
        )

    @asynccontextmanager
    async def gateway_lifespan(app):
        async with AsyncExitStack() as stack:
            for _, sub in subs:
                await stack.enter_async_context(sub.lifespan(app))
            yield

    routes = [
        Route("/healthz", healthz),
        Route("/kick", kick, methods=["POST"]),
    ]
    routes.extend(Mount(f"/{agent_id}", app=sub) for agent_id, sub in subs)
    app = Starlette(
        routes=routes,
        lifespan=gateway_lifespan,
        middleware=[Middleware(GatewayGuard)],
    )
    app.state.root = root
    app.state.bind_host = bind_host if bind_host is not None else os.environ.get(BIND_ENV, "127.0.0.1")
    app.state.agents = [agent_id for agent_id, _ in subs]
    return app


def main() -> None:
    import uvicorn

    root = paths.mailbox_root()
    host = os.environ.get(BIND_ENV, "127.0.0.1")
    port = int(os.environ.get(PORT_ENV, DEFAULT_PORT))
    if not loopback(host) and not token_state(root)["token"]:
        raise SystemExit(f"non-loopback bind requires {root / TOKEN_FILENAME}")
    paths.ensure_layout(root)
    uvicorn.run(build_app(root, bind_host=host), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
