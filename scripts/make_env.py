"""Create .env from .env.example, replacing every `change_me` with a random secret."""

import secrets
from pathlib import Path

EXAMPLE = Path(".env.example")
TARGET = Path(".env")


def main() -> None:
    lines = []
    for line in EXAMPLE.read_text().splitlines():
        if "=change_me" in line:
            key = line.split("=", 1)[0]
            line = f"{key}={secrets.token_urlsafe(24)}"
        lines.append(line)
    TARGET.write_text("\n".join(lines) + "\n")
    TARGET.chmod(0o600)
    print(f"wrote {TARGET} ({sum('token' in _ for _ in lines)} secrets generated)")


if __name__ == "__main__":
    main()
