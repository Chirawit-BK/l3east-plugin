"""Shared helpers for skillkit scripts.

Scripts run under `python3 -I`, so each one inserts its own directory into
sys.path before `import common`.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

MASK = "***"
DESC_LIMIT = 1536
SECRET_KEY_RE = re.compile(r"(?i)(token|secret|passw(?:or)?d|pwd|api[-_]?key|authorization|private[-_]?key)")
SECRET_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-=+]{32,}$")
JWT_RE = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
USERINFO_RE = re.compile(r"://[^/\s@]+:[^/\s@]+@")
# Free-text masking. A secret word may sit inside a longer env-style name (PGPASSWORD, DB_PWD,
# GITHUB_TOKEN); the whole name is kept and the value masked. Quotes count as token boundaries.
_SECRET_WORDS = r"(?:token|secret|passw(?:or)?d|pwd|api[-_]?key|private[-_]?key)"
_TEXT_URL_RE = re.compile(r"""(?i)\b([a-z][a-z0-9+.\-]*://[^\s"'<>]+)""")  # any scheme: postgresql://, wss://, ...
_TEXT_BEARER_RE = re.compile(r"(?i)\bbearer\s+\S+")
_TEXT_AUTH_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(authorization)\b\s*[=:]\s*(?:\w+\s+)?\S+")
_TEXT_USER_RE = re.compile(r"(?<![\w-])(-[A-Za-z]*u|--user)(\s+|=)(\S*:\S+)")  # curl -u / -su / --user[=] user:pass
_TEXT_KEYVAL_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])([A-Za-z0-9_]*" + _SECRET_WORDS + r"[A-Za-z0-9_]*)\s*[=:]\s*\S+")
_TEXT_FLAG_RE = re.compile(r"(?i)(?<![\w-])(--?[\w-]*(?:" + _SECRET_WORDS + r"|authorization)[\w-]*)\s+(\S+)")
_TEXT_TOKEN_RE = re.compile(r"[^\s=:,\"']+")


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def project_slug(path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(path).resolve()))


def est_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Tolerant YAML subset: `key: value`, quoted values, `>`/`|` blocks, indented continuations."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict = {}
    key = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal key, buf
        if key is not None:
            meta[key] = " ".join(s.strip() for s in buf if s.strip()).strip()
        key, buf = None, []

    for raw in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if m and not raw.startswith((" ", "\t")):
            flush()
            key = m.group(1)
            val = m.group(2).strip()
            buf = [] if val in (">", "|", ">-", "|-") else [val]
        elif key is not None:
            buf.append(raw)
    flush()
    for k, v in list(meta.items()):
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            meta[k] = v[1:-1]
        elif v.lower() in ("true", "false"):
            meta[k] = v.lower() == "true"
    return meta, "\n".join(lines[end + 1:])


def mask_secrets(obj):
    """Deep copy with secret-looking values replaced by MASK. Never mutates the input."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k in ("env", "headers") and isinstance(v, dict):
                out[k] = {ek: MASK for ek in v}
            elif isinstance(k, str) and SECRET_KEY_RE.search(k) and v is not None:
                out[k] = MASK
            else:
                out[k] = mask_secrets(v)
        return out
    if isinstance(obj, list):
        return [mask_secrets(x) for x in obj]
    if isinstance(obj, str) and SECRET_VALUE_RE.match(obj):
        return MASK
    return obj


def mask_strings(obj):
    """Apply mask_text to every string in an already mask_secrets'd structure (url, args, command).

    In a list, the item after a secret-named arg such as `--token` or `API_KEY` is masked whole,
    unless that arg carries its own value (`--token=x`, `Authorization: ...`).
    """
    if isinstance(obj, dict):
        return {k: mask_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        out = []
        prev = None
        for x in obj:
            if isinstance(x, str) and isinstance(prev, str) and SECRET_KEY_RE.search(prev) and not re.search(r"[=:]", prev):
                out.append(MASK)
            else:
                out.append(mask_strings(x))
            prev = x
        return out
    return mask_text(obj) if isinstance(obj, str) else obj


def _blob(s: str) -> bool:
    """A long token-like value or a JWT."""
    return bool(SECRET_VALUE_RE.match(s) or JWT_RE.search(s))


def mask_url(url: str) -> str:
    """Drop userinfo and fragment; mask blob path segments and secret query values; keep other params."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc.rpartition("@")[2]
    except ValueError:
        return MASK
    path = "/".join(MASK if _blob(urllib.parse.unquote(seg)) else seg for seg in parts.path.split("/"))
    query = []
    for pair in parts.query.split("&") if parts.query else []:
        k, sep, v = pair.partition("=")
        if v and (SECRET_KEY_RE.search(urllib.parse.unquote(k)) or _blob(urllib.parse.unquote(v))):
            v = MASK
        elif not sep and _blob(urllib.parse.unquote(k)):
            k = MASK
        query.append(k + sep + v)
    return urllib.parse.urlunsplit((parts.scheme, host, path, "&".join(query), ""))


def _mask_plain_text(s: str) -> str:
    s = _TEXT_BEARER_RE.sub("bearer ***", s)
    s = _TEXT_AUTH_RE.sub(lambda m: m.group(1) + "=***", s)
    s = _TEXT_USER_RE.sub(lambda m: m.group(1) + m.group(2)[:1] + MASK, s)
    s = _TEXT_KEYVAL_RE.sub(lambda m: m.group(1) + "=***", s)
    s = _TEXT_FLAG_RE.sub(lambda m: m.group(1) + " " + MASK, s)
    s = JWT_RE.sub(MASK, s)
    return _TEXT_TOKEN_RE.sub(lambda m: MASK if SECRET_VALUE_RE.match(m.group(0)) else m.group(0), s)


def mask_text(s: str) -> str:
    """Mask secrets inside free text: URLs via mask_url, auth headers, key=value and --flag secrets, long blobs."""
    pieces = _TEXT_URL_RE.split(s)
    return "".join(mask_url(x) if i % 2 else _mask_plain_text(x) for i, x in enumerate(pieces))


def _is_ref(v: str) -> bool:
    """`${VAR}` anywhere in a value makes it an env reference, not a plaintext secret."""
    return "${" in v


def _secret_pair(name: str, value: str) -> bool:
    return bool(value) and not _is_ref(value) and bool(SECRET_KEY_RE.search(name))


def _plaintext_in_strings(key: str, v) -> bool:
    """In `url`, `args` or `command`: URL userinfo, a JWT, or a secret-named arg/param with a value."""
    items = [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]
    for x in items:
        if not _is_ref(x) and (USERINFO_RE.search(x) or JWT_RE.search(x)):
            return True
    if key == "url":
        for x in items:
            try:
                query = urllib.parse.urlsplit(x).query
            except ValueError:
                continue
            if any(_secret_pair(k, val) for k, val in urllib.parse.parse_qsl(query)):
                return True
        return False
    tokens = [t for x in items for t in (x.split() if key == "command" else [x])]
    prev = None
    for t in tokens:
        name, sep, val = t.partition("=")
        if sep and _secret_pair(name, val):  # --token=abc, API_KEY=abc
            return True
        if prev is not None and not re.search(r"[=:]", prev) and _secret_pair(prev, t):  # --token abc
            return True
        prev = t
    return False


def has_plaintext_secret(obj) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and SECRET_KEY_RE.search(k) and isinstance(v, str) and v and not _is_ref(v):
                return True
            if k in ("url", "args", "command") and _plaintext_in_strings(k, v):
                return True
            if has_plaintext_secret(v):
                return True
    elif isinstance(obj, list):
        return any(has_plaintext_secret(x) for x in obj)
    return False


def _cache_fallback(home: Path) -> list[dict]:
    found = []
    cache = home / "plugins" / "cache"
    if not cache.is_dir():
        return found
    for mp in sorted(p for p in cache.iterdir() if p.is_dir()):
        for plug in sorted(p for p in mp.iterdir() if p.is_dir()):
            versions = sorted(p for p in plug.iterdir() if p.is_dir())
            if versions:
                found.append({
                    "id": f"{plug.name}@{mp.name}",
                    "version": versions[-1].name,
                    "scope": "unknown",
                    "enabled": "unknown",
                    "installPath": str(versions[-1]),
                })
    return found


def load_plugin_list(home: Path, override: Path | None = None) -> tuple[list[dict], list[str]]:
    """Enabled plugins from `claude plugin list --json`, an override file, or the cache."""
    warnings: list[str] = []
    if override is not None:
        data = read_json(override)
        if isinstance(data, list):
            return data, warnings
        warnings.append(f"plugin list override unreadable: {override}")
    else:
        try:
            out = subprocess.run(["claude", "plugin", "list", "--json"], capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                data = json.loads(out.stdout)
                if isinstance(data, list):
                    return data, warnings
            warnings.append(f"claude plugin list failed (rc={out.returncode})")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            warnings.append(f"claude plugin list unavailable: {exc}")
    warnings.append("plugin list taken from plugins/cache scan; enabled state unknown")
    return _cache_fallback(home), warnings
