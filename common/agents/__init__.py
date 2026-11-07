import importlib
import pkgutil

DELIVERY_KINDS = ("tmux", "native-inbox", "queue-daemon", "pull-only")

_SPECS: dict[str, dict] = {}
_PROC_NAME_TO_CLI: dict[str, str] = {}


def _load_all() -> None:
    for module_info in pkgutil.iter_modules(__path__):
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, dict):
            continue
        cli = str(spec.get("cli") or "")
        if cli and cli not in _SPECS:
            _SPECS[cli] = spec
            for name in spec.get("proc_names") or ():
                _PROC_NAME_TO_CLI[str(name)] = cli


_load_all()


def spec_for(cli: str) -> dict:
    return _SPECS.get(str(cli or ""), {})


def delivery_kind(cli: str) -> str:
    return str(spec_for(cli).get("delivery_kind") or "tmux")


def cli_names() -> tuple[str, ...]:
    return tuple(sorted(_SPECS))


def proc_names() -> tuple[str, ...]:
    return tuple(sorted(_PROC_NAME_TO_CLI))


def pane_commands_for(cli: str) -> tuple[str, ...]:
    spec = spec_for(cli)
    return tuple(spec.get("pane_commands") or spec.get("proc_names") or ())


def cli_of_proc_name(name: str) -> str:
    return _PROC_NAME_TO_CLI.get(str(name), "")


def respawn_recipe(cli: str) -> dict:
    return dict(spec_for(cli).get("respawn") or {})


def multi_instance_key(cli: str) -> str:
    return str((spec_for(cli).get("multi_instance") or {}).get("key") or "")


def pull_only_clis() -> tuple[str, ...]:
    return tuple(sorted(cli for cli, spec in _SPECS.items() if spec.get("delivery_kind") == "pull-only"))


def native_inbox_clis() -> tuple[str, ...]:
    return tuple(sorted(cli for cli, spec in _SPECS.items() if spec.get("delivery_kind") == "native-inbox"))


def queue_daemon_clis() -> tuple[str, ...]:
    return tuple(sorted(cli for cli, spec in _SPECS.items() if spec.get("delivery_kind") == "queue-daemon"))
