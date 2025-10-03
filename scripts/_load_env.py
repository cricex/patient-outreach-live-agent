from __future__ import annotations

import shlex
import sys
from pathlib import Path

try:
    from dotenv import dotenv_values
except ModuleNotFoundError as exc:  # pragma: no cover - handled in caller
    print(f"python-dotenv is required but not installed: {exc}", file=sys.stderr)
    sys.exit(2)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str]) -> int:
    merged: dict[str, str] = {}

    for raw_path in argv:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            continue
        data = dotenv_values(path)
        for key, value in data.items():
            if value is None:
                continue
            merged[key] = value

    for key, value in merged.items():
        print(f"export {key}={shlex.quote(value)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
