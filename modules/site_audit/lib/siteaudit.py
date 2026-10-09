"""Shared helpers for the site_audit module tools.

Standard library only. Imported by the scripts in ../tools, which the loader
never sees here — it reads manifest.json and tools/ and nothing else.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_ERROR = 2
EXIT_USAGE = 3

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROJECT_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

STATUSES = (
    "crawling",
    "scoring",
    "transforming",
    "deploying",
    "deployed",
    "failed",
    "cancelled",
)

TERMINAL_STATES = ("deployed", "failed", "cancelled")


# --- output ------------------------------------------------------------------


def ok(message=None, **fields):
    payload = {"success": True}
    if message:
        payload["message"] = message
    payload.update(fields)
    print(json.dumps(payload, indent=2))
    sys.exit(EXIT_OK)


def fail(error, code=EXIT_ERROR, **fields):
    payload = {"error": error}
    payload.update(fields)
    print(json.dumps(payload), file=sys.stderr)
    sys.exit(code)


# --- environment -------------------------------------------------------------


def params():
    try:
        value = json.loads(os.environ.get("HUB_PARAMS") or "{}")
    except json.JSONDecodeError as exc:
        fail(f"HUB_PARAMS is not valid JSON: {exc}", EXIT_USAGE)
    if not isinstance(value, dict):
        fail("HUB_PARAMS must be a JSON object", EXIT_USAGE)
    return value


def data_dir():
    value = os.environ.get("HUB_MODULE_DATA")
    if not value:
        fail("HUB_MODULE_DATA is not set", EXIT_ERROR)
    return Path(value).expanduser()


# --- files -------------------------------------------------------------------


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read {path}: {exc}", EXIT_ERROR)


def write_json(path, value, indent=2):
    ensure_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(value, indent=indent) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        fail(f"Cannot write {path}: {exc}", EXIT_ERROR)


def dir_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# --- text and time -----------------------------------------------------------


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def page_slug(url):
    """Match psi-fetch.sh's url_slug: "/" -> home, "/a/b/" -> a-b.

    Case is preserved and the derivation is path-only, because the archives
    Phase 2 reads are named after it.
    """
    path = urlparse(str(url or "")).path
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path.strip("/")).strip("-")
    return slug or "home"


def today():
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def days_old(date):
    """Days between a YYYY-MM-DD run date and today. Negative for the future."""
    return (datetime.now().date() - datetime.strptime(date, "%Y-%m-%d").date()).days


# --- validation --------------------------------------------------------------


def require_url(value, field):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        fail(f"{field} must be an absolute http(s) URL", EXIT_USAGE, given=value)
    return parsed.geturl()


def require_project(value, field="cloudflare_project"):
    text = str(value or "").strip()
    if not PROJECT_RE.match(text):
        fail(
            f"{field} becomes part of the report's address, so it takes "
            "lowercase letters, numbers and hyphens only",
            EXIT_USAGE,
            given=value,
        )
    return text


def require_date(value, field="date"):
    text = str(value or "").strip()
    if not DATE_RE.match(text):
        fail(f"{field} must be YYYY-MM-DD", EXIT_USAGE, given=value)
    return text


def as_bool(value, field):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "yes", "1"):
        return True
    if text in ("false", "no", "0"):
        return False
    fail(f"{field} must be true or false", EXIT_USAGE, given=value)


def as_int(value, field, minimum=None):
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        fail(f"{field} must be a number", EXIT_USAGE, given=value)
    if minimum is not None and number < minimum:
        fail(f"{field} must be at least {minimum}", EXIT_USAGE, given=value)
    return number


# --- clients -----------------------------------------------------------------


def clients_dir():
    return data_dir() / "clients"


def client_path(slug):
    return clients_dir() / f"{slug}.json"


def all_clients():
    """(slug, record) for every stored client, slug-ordered."""
    found = []
    for path in sorted(clients_dir().glob("*.json")):
        record = read_json(path)
        if isinstance(record, dict):
            found.append((path.stem, record))
    return found


def host_keys(base_url):
    """A base_url's hostname, and that hostname without its final label."""
    host = (urlparse(str(base_url or "")).hostname or "").lower()
    if not host:
        return []
    bare = host[4:] if host.startswith("www.") else host
    keys = [bare]
    if "." in bare:
        keys.append(bare.rsplit(".", 1)[0])
    return keys


def resolve_client(identifier):
    """Find a client by slug, then name, then hostname, then prefix.

    Tiers are tried in order and the first with any hit wins, so an exact slug
    is never overruled by a loose hostname match. Two hits in one tier is
    ambiguous and reported rather than guessed at.
    """
    needle = str(identifier or "").strip().lower()
    clients = all_clients()
    if not clients:
        fail("No audit clients yet — add one with add_client", EXIT_NOT_FOUND)
    if not needle:
        fail("client is required", EXIT_USAGE, known=[s for s, _ in clients])

    def name_of(record):
        return str(record.get("name") or "").lower()

    tiers = (
        [s for s, _ in clients if s.lower() == needle],
        [s for s, r in clients if name_of(r) == needle],
        [s for s, r in clients if needle in host_keys(r.get("base_url"))],
        [
            s
            for s, r in clients
            if s.lower().startswith(needle)
            or name_of(r).startswith(needle)
            or any(k.startswith(needle) for k in host_keys(r.get("base_url")))
        ],
    )

    for tier in tiers:
        hits = sorted(set(tier))
        if len(hits) == 1:
            slug = hits[0]
            return slug, dict(next(r for s, r in clients if s == slug))
        if len(hits) > 1:
            fail(
                f"'{identifier}' matches more than one audit client",
                EXIT_USAGE,
                candidates=hits,
            )

    fail(
        f"No audit client matching '{identifier}'",
        EXIT_NOT_FOUND,
        known=[s for s, _ in clients],
    )


CLIENT_KEYS = ("client", "slug", "name", "item")


def client_identifier(values, keys=CLIENT_KEYS):
    """The client a caller named, under any of the keys that can carry it.

    `client` is canonical; `slug` is what the plan's workflow examples use, and
    `name` and `item` are what the intent matcher extracts from a sentence. A
    tool that owns one of those names for something else narrows `keys`.
    """
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def save_client(slug, record):
    write_json(client_path(slug), record)


# --- runs --------------------------------------------------------------------


def runs_dir():
    return data_dir() / "runs"


def client_runs_dir(slug):
    return runs_dir() / slug


def run_dir(slug, date):
    return client_runs_dir(slug) / date


def run_record_path(slug, date):
    return run_dir(slug, date) / "record.json"


def run_dates(slug):
    """Dated run directories for a client, newest first."""
    root = client_runs_dir(slug)
    if not root.is_dir():
        return []
    return sorted(
        (p.name for p in root.iterdir() if p.is_dir() and DATE_RE.match(p.name)),
        reverse=True,
    )


def read_run(slug, date):
    record = read_json(run_record_path(slug, date))
    return record if isinstance(record, dict) else None


def run_archives(slug, date):
    """Archive filenames sitting beside a run's record."""
    directory = run_dir(slug, date)
    if not directory.is_dir():
        return []
    return sorted(
        p.name for p in directory.iterdir() if p.is_file() and p.name != "record.json"
    )
