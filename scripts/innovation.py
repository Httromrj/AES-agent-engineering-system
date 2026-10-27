"""Local AES sensitivity scan and evidence register; stdlib only."""
import argparse
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from html import unescape
import json
import ipaddress
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urldefrag, urljoin
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1] if SCRIPT_DIR.parent.name == ".agent-engineering" else SCRIPT_DIR.parent
def state_directory():
    configured = os.environ.get("AES_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(base) / "AES-agent-engineering-system"
    base = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(base) / "aes-agent-engineering-system"


STATE = state_directory()
PRIVATE = STATE / "private"
AUDIT = PRIVATE / "audit.jsonl"
REGISTER = STATE / "research" / "register.jsonl"
SOURCES = (ROOT / ".agent-engineering" / "research" / "sources.json"
           if SCRIPT_DIR.parent.name == ".agent-engineering" else ROOT / "research" / "sources.json")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".aes-private"}
MAX_BYTES = 2_000_000
OPAQUE_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".7z", ".rar", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".parquet", ".db", ".sqlite"}
for output_stream in (sys.stdout, sys.stderr):
    if hasattr(output_stream, "reconfigure"):
        output_stream.reconfigure(encoding="utf-8", errors="backslashreplace")

# Report only rule IDs and paths. Never copy matching text into logs or output.
RULES = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("credential_assignment", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\b\s*[:=]\s*[\"'][^\"']{8,}[\"']")),
    ("provider_token", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|(?:sk|rk)_live_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{25,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35})\b")),
    ("jwt_token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("connection_string", re.compile(r"(?i)\b(?:postgres|mysql|mongodb(?:\+srv)?):\/\/[^\s\"']+")),
    ("personal_data_marker", re.compile(r"(?i)\b(?:SSN|CPF|passport number|social security number)\b\s*[:#]?\s*[0-9.\-/]{8,}")),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("confidentiality_marker", re.compile(r"(?im)^\s*(?:CONFIDENTIAL|STRICTLY CONFIDENTIAL|INTERNAL USE ONLY|RESTRICTED)\s*$")),
]
SENSITIVE_PATH_COMPONENTS = {"private", "confidential", "restricted", "payroll", "customer-data", "client-data", "employee-data"}


def classify(path: Path):
    try:
        if path.is_symlink():
            return ["unscanned_symlink"]
        if not path.is_file():
            return []
        if path.suffix.lower() in OPAQUE_EXTENSIONS:
            return ["unscanned_binary"]
        if path.stat().st_size > MAX_BYTES:
            return ["unscanned_large_file"]
        data = path.read_bytes()
        if b"\0" in data:
            return ["unscanned_binary"]
        text = data.decode("utf-8", errors="replace")
    except OSError:
        return ["unreadable"]
    hits = [name for name, rule in RULES if rule.search(text)]
    if path.name.lower().startswith(".env") or path.name.lower() in {"credentials", "secrets.json", "id_rsa", "id_ed25519"}:
        hits.append("sensitive_filename")
    if any(part.lower() in SENSITIVE_PATH_COMPONENTS for part in path.parts):
        hits.append("sensitive_location")
    return sorted(set(hits))


def scan(paths):
    findings = []
    for item in paths:
        path = item.absolute()
        if path.is_symlink():
            findings.append({"path": str(path), "rules": ["unscanned_symlink"]})
            continue
        if not path.exists():
            findings.append({"path": str(path), "rules": ["missing_path"]})
            continue
        if path.is_file():
            candidates = [path]
        else:
            candidates = []
            def walk_error(error):
                findings.append({"path": str(getattr(error, "filename", path)), "rules": ["unreadable"]})
            for current, dirs, names in os.walk(path, topdown=True, onerror=walk_error, followlinks=False):
                kept_dirs = []
                for name in dirs:
                    child = Path(current) / name
                    if name in SKIP_DIRS:
                        continue
                    if child.is_symlink():
                        findings.append({"path": str(child), "rules": ["unscanned_symlink"]})
                    else:
                        kept_dirs.append(name)
                dirs[:] = kept_dirs
                candidates.extend(Path(current) / name for name in names)
        for candidate in candidates:
            rules = classify(candidate)
            if rules:
                findings.append({"path": str(candidate), "rules": rules})
    return findings


def audit(action, findings):
    if os.name != "nt":
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not os.environ.get("AES_STATE_DIR"):
            STATE.chmod(0o700)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        PRIVATE.chmod(0o700)
    row = {"time": datetime.now(timezone.utc).isoformat(), "action": action,
           "findings": [{"path": x["path"], "rules": x["rules"]} for x in findings],
           "decision": "blocked" if findings else "clear"}
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if os.name != "nt":
        AUDIT.chmod(0o600)


def add_record(kind, payload):
    if not isinstance(payload, dict):
        raise ValueError("Record must be a JSON object")
    required = ("title", "source", "date", "evidence", "limitations", "applicability", "status")
    missing = [key for key in required if not payload.get(key)]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))
    if kind == "discovery" and payload["status"] not in {"verified", "hypothesis", "commercial_claim", "experimental"}:
        raise ValueError("Invalid discovery status")
    if kind == "proposal" and not payload.get("success_criteria"):
        raise ValueError("Proposal requires success_criteria")
    if kind == "proposal":
        score_fields = ("priority", "expected_impact", "confidence", "effort")
        absent = [key for key in score_fields if not payload.get(key)]
        if absent:
            raise ValueError("Proposal requires prioritization fields: " + ", ".join(absent))
        if payload.get("decision") not in {"proposed", "accepted", "rejected", "deferred"}:
            raise ValueError("Proposal decision must be proposed, accepted, rejected, or deferred")
        if not payload.get("decision_rationale"):
            raise ValueError("Proposal requires decision_rationale")
    encoded = json.dumps(payload, ensure_ascii=False)
    matched = [name for name, rule in RULES if rule.search(encoded)]
    if matched:
        raise ValueError("Record rejected by sensitivity rules: " + ", ".join(matched))
    REGISTER.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        REGISTER.parent.chmod(0o700)
    entry = {"kind": kind, "recorded_at": datetime.now(timezone.utc).isoformat(), **payload}
    # Deduplicate feed discoveries; proposals are append-only decision history.
    key = (kind, payload["source"].strip().lower(), payload["title"].strip().lower())
    revision = 1
    if REGISTER.exists():
        for line in REGISTER.read_text(encoding="utf-8").splitlines():
            try:
                old = json.loads(line)
                oldkey = (old["kind"], old.get("source", "").strip().lower(), old.get("title", "").strip().lower())
                if kind == "discovery" and key == oldkey:
                    print("Duplicate record; unchanged.")
                    return False
                if kind == "proposal" and key == oldkey:
                    revision = max(revision, int(old.get("revision", 1)) + 1)
            except (ValueError, KeyError):
                continue
    if kind == "proposal":
        entry["revision"] = revision
    with REGISTER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if os.name != "nt":
        REGISTER.chmod(0o600)
    suffix = f" revision {revision}" if kind == "proposal" else ""
    print(f"Recorded {kind}{suffix}: {payload['title']}")
    return True


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname or new.username or new.password:
            raise urllib.error.HTTPError(req.full_url, code, "Cross-host or non-HTTPS redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_feed_url(value):
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return True


def xml_child_text(element, *names):
    wanted = set(names)
    for child in element:
        child_name = child.tag.rsplit("}", 1)[-1]
        if child_name in wanted:
            if child_name == "link":
                if child.attrib.get("href"):
                    if child.attrib.get("rel", "alternate") in {"alternate", ""}:
                        return child.attrib["href"].strip()
                    continue
                return " ".join("".join(child.itertext()).split())
            return " ".join("".join(child.itertext()).split())
    return ""


def parse_feed(data, source, limit):
    root_start = re.search(rb"<(?![!?/])[^>]+>", data)
    prolog = data[:root_start.start()] if root_start else data
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", prolog, re.IGNORECASE):
        raise ValueError("DTD/entity declarations are not accepted")
    root = ET.fromstring(data)
    elements = [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] in {"item", "entry"}][:limit]
    records = []
    for element in elements:
        title = xml_child_text(element, "title")
        raw_link = xml_child_text(element, "link", "guid", "id")
        if not title or not raw_link:
            continue
        link = urljoin(source["url"], raw_link)
        if not safe_feed_url(link):
            continue
        link = urldefrag(link)[0]
        date_raw = xml_child_text(element, "pubDate", "published", "updated", "date")
        try:
            date = parsedate_to_datetime(date_raw).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            try:
                date = datetime.fromisoformat(date_raw.replace("Z", "+00:00")).date().isoformat()
            except (TypeError, ValueError):
                date = datetime.now(timezone.utc).date().isoformat()
        summary = xml_child_text(element, "description", "summary", "content")
        summary = re.sub(r"<[^>]*>", " ", unescape(summary))
        summary = " ".join(summary.split())[:500]
        records.append({
            "title": title[:240], "source": link, "date": date,
            "evidence": f"RSS/Atom metadata from {source['name']}. {summary}".strip(),
            "alternatives": [],
            "limitations": "Discovery-stage feed metadata only; article not independently verified or tested.",
            "applicability": "Unassessed hypothesis; compare against AES and relevant consumer projects.",
            "status": "hypothesis", "source_feed": source["url"],
            "source_authority": source.get("authority", "unrated"),
            "topics": source.get("topics", []), "source_priority": source.get("priority", 3),
        })
    return records


def fetch_source(source, limit):
    if not safe_feed_url(source.get("url", "")):
        raise ValueError("source URL must be HTTPS without embedded credentials")
    opener = urllib.request.build_opener(SafeRedirect)
    request = urllib.request.Request(source["url"], headers={"User-Agent": "AES-Research/0.1 (+configurable RSS reader)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with opener.open(request, timeout=15) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("feed exceeds 2 MB limit")
    return parse_feed(data, source, limit)


@contextmanager
def research_lock():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and not os.environ.get("AES_STATE_DIR"):
        STATE.chmod(0o700)
    lock_path = STATE / "research-cycle.lock"
    handle = lock_path.open("a+b")
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        if handle.tell() == 0 and lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            handle.close()
            raise RuntimeError("research cycle already running") from exc
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("research cycle already running") from exc
    try:
        yield
    finally:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def append_run_log(row):
    run_log = STATE / "research" / "runs.jsonl"
    run_log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        run_log.parent.chmod(0o700)
    with run_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if os.name != "nt":
        run_log.chmod(0o600)


def research_cycle(config_path, limit):
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sources = config.get("sources")
    if not isinstance(sources, list) or not sources or len(sources) > 40:
        raise ValueError("sources config must contain between 1 and 40 sources")
    candidates, errors, source_counts = [], [], []
    for source in sources:
        if not isinstance(source, dict) or not source.get("id") or not source.get("name"):
            errors.append({"source_id": "invalid", "error": "InvalidSourceConfig"})
            continue
        if not source.get("enabled", True):
            continue
        try:
            records = fetch_source(source, limit)
            candidates.extend(records)
            source_counts.append({"source_id": source["id"], "items": len(records)})
        except (OSError, ValueError, ET.ParseError, urllib.error.URLError) as exc:
            if isinstance(exc, urllib.error.HTTPError):
                category = f"HTTP{exc.code}"
            elif isinstance(exc, ET.ParseError):
                category = "MalformedXml"
            elif isinstance(exc, ValueError) and "2 MB" in str(exc):
                category = "ResponseSizeLimit"
            elif isinstance(exc, ValueError) and "DTD/entity" in str(exc):
                category = "UnsafeXml"
            elif isinstance(exc, ValueError):
                category = "InvalidFeed"
            elif isinstance(exc, TimeoutError):
                category = "Timeout"
            else:
                category = "NetworkError"
            errors.append({"source_id": source.get("id", "unknown"), "error": category})
    candidates.sort(key=lambda item: item["date"], reverse=True)
    candidates.sort(key=lambda item: int(item.get("source_priority", 3)))
    added, rejected = [], 0
    for record in candidates:
        try:
            if add_record("discovery", record):
                added.append(record)
        except ValueError:
            rejected += 1
    digest_dir = STATE / "research" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        digest_dir.chmod(0o700)
    digest_path = digest_dir / (datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".md")
    lines = ["# AES innovation research digest", "", f"Generated: {datetime.now(timezone.utc).isoformat()}",
             "", "Every item below is an unverified hypothesis from feed metadata. Review the linked primary source, compare alternatives, and map it to a consumer project before recommending or testing it.", ""]
    for item in added:
        title = re.sub(r"([\\`*_{}\[\]()#+.!|>])", r"\\\1", item["title"])
        evidence = re.sub(r"([\\`*_{}\[\]()#+.!|>])", r"\\\1", item["evidence"])
        lines.extend([f"## [{title}](<{item['source']}>)", "",
                      f"- Source: {item['source_feed']} ({item['source_authority']})",
                      f"- Published: {item['date']}", f"- Topics: {', '.join(item['topics']) or 'unclassified'}",
                      f"- Evidence: {evidence}", "- Assessment: hypothesis; applicability and alternatives still need review.", ""])
    if not added:
        lines.append("No new candidates were recorded in this run.")
    digest_path.write_text("\n".join(lines), encoding="utf-8")
    result = {"started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
              "duration_seconds": round(time.monotonic() - started, 3), "sources_configured": len(sources),
              "source_counts": source_counts,
              "fetched": len(candidates), "new": len(added), "rejected_by_sensitivity_rules": rejected,
              "source_errors": errors, "digest": str(digest_path), "external_model_calls": 0,
              "model_api_cost": 0, "infrastructure_cost": "not measured"}
    append_run_log(result)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if errors and not candidates else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan", help="Classify files before external use")
    s.add_argument("paths", nargs="+", type=Path)
    s.add_argument("--action", choices=["index", "summarize", "external_model", "publish", "share"], default="external_model")
    r = sub.add_parser("record", help="Append a discovery or improvement proposal")
    r.add_argument("kind", choices=["discovery", "proposal"])
    r.add_argument("json_file", type=Path, help="UTF-8 JSON object with evidence metadata")
    q = sub.add_parser("research", help="Fetch configured RSS/Atom sources and write a local digest")
    q.add_argument("--sources", type=Path, default=SOURCES)
    q.add_argument("--per-source", type=int, default=10)
    args = parser.parse_args()
    if args.command == "scan":
        try:
            findings = scan(args.paths)
            audit(args.action, findings)
        except OSError:
            print("BLOCKED: scan or audit could not complete.", file=sys.stderr)
            return 2
        for finding in findings:
            print(json.dumps(finding, ensure_ascii=False))
        print("BLOCKED: review findings before external use." if findings else "CLEAR: no configured detector matched; this is not proof of safety.")
        return 2 if findings else 0
    if args.command == "research":
        if args.per_source < 1 or args.per_source > 50:
            print("per-source limit must be between 1 and 50", file=sys.stderr)
            return 2
        try:
            with research_lock():
                return research_cycle(args.sources, args.per_source)
        except RuntimeError:
            print("Research cycle already running; this invocation was not started.", file=sys.stderr)
            return 2
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Research cycle failed: {type(exc).__name__}", file=sys.stderr)
            return 2
    try:
        add_record(args.kind, json.loads(args.json_file.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Record rejected: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
