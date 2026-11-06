"""Create .env from .env.example, replacing every `change_me` with a random secret.

An existing .env is never rewritten: regenerating secrets would lock the running containers out
of their own volumes (postgres passwords, minio keys). It only gets the keys of .env.example that
it lacks, appended at the end, so a new service can ship a new secret without a manual edit.
"""

import base64
import secrets
import sys
from pathlib import Path

EXAMPLE = Path(".env.example")
TARGET = Path(".env")
PLACEHOLDER = "change_me"
# Airflow decrypts connections with Fernet, which accepts only urlsafe base64 of 32 bytes.
FERNET_KEY = "AIRFLOW_FERNET_KEY"


def secret_for(key: str) -> str:
    if key == FERNET_KEY:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    return secrets.token_urlsafe(24)


def render(example: str) -> tuple[str, int]:
    """Return the .env text and the number of secrets generated."""
    lines: list[str] = []
    generated = 0
    for line in example.splitlines():
        key, sep, value = line.partition("=")
        if sep and value.split("#", 1)[0].strip() == PLACEHOLDER:
            line = f"{key}={secret_for(key)}"
            generated += 1
        lines.append(line)
    return "\n".join(lines) + "\n", generated


def key_of(line: str) -> str:
    """The variable name of a KEY=value line, as a shell or compose reads it."""
    key = line.partition("=")[0].strip()
    return key.removeprefix("export ").strip()


def missing_lines(example: str, existing: str) -> tuple[str, int]:
    """Return the lines to append to `existing` and how many keys they add."""
    present = {key_of(line) for line in existing.splitlines() if "=" in line}
    wanted = [
        line
        for line in example.splitlines()
        if "=" in line and not line.lstrip().startswith("#") and key_of(line) not in present
    ]
    text, _ = render("\n".join(wanted) + "\n") if wanted else ("", 0)
    return text, len(wanted)


def append_missing() -> int:
    # Private before anything is appended: a secret must never sit in a world-readable file.
    TARGET.chmod(0o600)
    existing = TARGET.read_text()
    addition, added = missing_lines(EXAMPLE.read_text(), existing)
    if added:
        # A file without a final newline would glue the first new key to its last line.
        separator = "" if existing.endswith("\n") or not existing else "\n"
        with TARGET.open("a") as env:
            env.write(separator + addition)
    print(f"{TARGET} exists, kept as it is, {added} missing keys appended")
    return 0


def main() -> int:
    if TARGET.exists():
        return append_missing()
    text, generated = render(EXAMPLE.read_text())
    TARGET.write_text(text)
    TARGET.chmod(0o600)
    print(f"wrote {TARGET} ({generated} secrets generated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
