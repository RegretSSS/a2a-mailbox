#!/usr/bin/env python3
import argparse
import importlib.util
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "mcp" / "mailbox_mcp.py"
SPEC = importlib.util.spec_from_file_location("mailbox_mcp", SERVER)
MAILBOX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAILBOX)


def main() -> None:
    parser = argparse.ArgumentParser(description="hub 侧手工投递: 不经 MCP 挂载直接 mail_send")
    parser.add_argument("from_id")
    parser.add_argument("to_id")
    parser.add_argument("body")
    parser.add_argument("--in-reply-to", default=None)
    parser.add_argument("--context", default="")
    parser.add_argument("--expect-reply", action="store_true")
    args = parser.parse_args()
    try:
        MAILBOX.self_register()
    except Exception:
        pass
    print(MAILBOX.do_send(args.from_id, args.to_id, args.body, args.in_reply_to, args.context, args.expect_reply))


if __name__ == "__main__":
    main()
