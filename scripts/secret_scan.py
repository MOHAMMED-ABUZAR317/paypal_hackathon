"""Fail the build if a credential is committed.

Run from the repository root::

    python scripts/secret_scan.py

The scan covers tracked and untracked-but-not-ignored files. It reports the
file and line, never the matched value. Exit code 1 means at least one finding.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".pdf",
    ".zip", ".gz", ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".webm",
    ".db", ".sqlite", ".sqlite3",
}
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".venv", "venv"}
MAX_BYTES = 512 * 1024

# (name, regex, allow_if_line_contains)
PATTERNS: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    (
        "private-key",
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |PGP )?PRIVATE KEY-----"),
        (),
    ),
    (
        "aws-access-key",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        (),
    ),
    (
        "github-token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
        (),
    ),
    (
        "openai-style-key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        (),
    ),
    (
        "paypal-client-secret",
        re.compile(r"PAYPAL_CLIENT_SECRET\s*=\s*([^\s#]+)"),
        ("your-", "<", "changeme", "example", "placeholder", "xxx", "test"),
    ),
    (
        "ai-api-key",
        re.compile(r"AI_API_KEY\s*=\s*([^\s#]+)"),
        ("your-", "<", "changeme", "example", "placeholder", "xxx", "test"),
    ),
    (
        "hardcoded-secret",
        re.compile(
            r"""(?i)\b(?:client_secret|api_key|apikey|access_token|auth_token|password)\b"""
            r"""\s*[:=]\s*["']([^"'\s]{16,})["']"""
        ),
        (
            "your-", "<", "changeme", "example", "placeholder", "xxx", "test",
            "mock", "dev-", "dummy", "sample",
        ),
    ),
]

# Lines that document a variable rather than assign a credential.
DOC_ONLY = (
    "os.environ[",
    "getenv(",
    "settings.",
    "example",
    "placeholder",
    "your-client",
    "replace",
)


def candidate_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"secret-scan: git ls-files failed: {exc}")
        return []
    files: list[Path] = []
    for line in output.splitlines():
        path = ROOT / line.strip()
        if not line.strip() or not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            if b"\x00" in path.read_bytes()[:2048]:
                continue
        except OSError:
            continue
        files.append(path)
    return files


def is_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    stripped = value.strip().strip("\"'")
    if not stripped:
        return True
    # "sk-...", "...", "…", "***", "---", "___" are documentation, not keys.
    stripped = re.sub(r"(?i)^(?:sk|pk|rk)-", "", stripped)
    return set(stripped) <= {".", "\u2026", "*", "-", "_"}


def scan() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if any(marker in line for marker in DOC_ONLY):
                continue
            for name, pattern, allow in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                lowered = line.lower()
                if any(token in lowered for token in allow):
                    continue
                value = match.group(1) if match.lastindex else None
                if is_placeholder(value):
                    continue
                findings.append((rel, number, name))
                break
    return findings


def main() -> int:
    files = candidate_files()
    findings = scan()
    if not findings:
        print(f"secret-scan: clean ({len(files)} files scanned)")
        return 0
    print(f"secret-scan: {len(findings)} possible secret(s) found")
    for rel, number, name in findings:
        print(f"  {rel}:{number}  {name}")
    print("\nRemove the value, rotate the credential, and use an environment variable.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
