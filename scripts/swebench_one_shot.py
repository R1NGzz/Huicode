from __future__ import annotations

import argparse
import builtins
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one HuiCode task as one non-interactive input")
    parser.add_argument("task_file", type=Path)
    parser.add_argument("config_file", type=Path)
    parser.add_argument("huicode_root", type=Path)
    args = parser.parse_args()

    task = args.task_file.read_text(encoding="utf-8")
    sys.path.insert(0, str(args.huicode_root.resolve()))

    used = False

    def read_one_input(prompt: str = "") -> str:
        nonlocal used
        if used:
            raise EOFError()
        used = True
        return task

    builtins.input = read_one_input

    import huicode.sse as sse

    real_urlopen = sse.urlopen

    def long_urlopen(request, timeout=None, *positional, **keyword):  # noqa: ANN001
        if timeout is None or timeout < 600:
            timeout = 600
        return real_urlopen(request, timeout=timeout, *positional, **keyword)

    sse.urlopen = long_urlopen

    from huicode.cli import main as cli_main

    return cli_main(["-c", str(args.config_file.resolve())])


if __name__ == "__main__":
    raise SystemExit(main())
