"""Create .env from .env.example, replacing every `change_me` with a random secret.

Refuses to overwrite an existing .env: regenerating secrets would lock the running
containers out of their own volumes (postgres passwords, minio keys).
"""

import secrets
import sys
from pathlib import Path

EXAMPLE = Path(".env.example")
TARGET = Path(".env")
PLACEHOLDER = "change_me"


def render(example: str) -> tuple[str, int]:
    """Return the .env text and the number of secrets generated."""
    lines: list[str] = []
    generated = 0
    for line in example.splitlines():
        key, sep, value = line.partition("=")
        if sep and value.split("#", 1)[0].strip() == PLACEHOLDER:
            line = f"{key}={secrets.token_urlsafe(24)}"
            generated += 1
        lines.append(line)
    return "\n".join(lines) + "\n", generated


def main() -> int:
    if TARGET.exists():
        print(f"{TARGET} exists, not overwriting", file=sys.stderr)
        return 1
    text, generated = render(EXAMPLE.read_text())
    TARGET.write_text(text)
    TARGET.chmod(0o600)
    print(f"wrote {TARGET} ({generated} secrets generated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
