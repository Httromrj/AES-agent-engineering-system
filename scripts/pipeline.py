"""Background pipeline run by the dashboard: translate and rate, collect community signals, discover trending
repositories, rank everything, and let the autopilot adopt the best items into registered projects."""
from datetime import datetime, timedelta, timezone
import json
import threading
import time

import adopt
import innovation
import signals
import translate

INTERVAL_SECONDS = 180
TRENDING_EVERY = timedelta(hours=6)
status = {"last_cycle": None, "last_trending": None, "trending_added": 0, "signals_checked": 0,
          "autopilot": {"state": "off"}, "last_error": None}
_lock = threading.Lock()


def _triage():
    result = {}
    try:
        with (innovation.STATE / "research" / "triage.jsonl").open("rb") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("source"), str):
                    result[row["source"].strip().lower()] = row.get("state")
    except OSError:
        pass
    return result


def ranked():
    """Every discovery with its score inputs, highest score first."""
    translations, sig, triage = translate.load(), signals.latest(), _triage()
    items = []
    for row in adopt.innovation_rows():
        if row.get("kind") != "discovery" or not isinstance(row.get("source"), str):
            continue
        key = row["source"].strip().lower()
        rating = translations.get(key, {})
        result = signals.score(sig.get(key), rating.get("relevance"), row.get("source_authority"))
        items.append({"source": row["source"], "relevance": rating.get("relevance"), "actionable": rating.get("actionable"),
                      "why": rating.get("why"), "triage": triage.get(key, "new"), "signal": sig.get(key, {}), **result})
    items.sort(key=lambda i: i["score"], reverse=True)
    return items


def cycle(transport=None):
    if not _lock.acquire(blocking=False):
        return
    try:
        translate.translate_pending(transport)
        now = datetime.now(timezone.utc)
        last = status["last_trending"]
        if last is None or now - datetime.fromisoformat(last) >= TRENDING_EVERY:
            status["trending_added"] = signals.discover_trending()
            status["last_trending"] = now.isoformat()
        status["signals_checked"] = signals.refresh()
        status["autopilot"] = adopt.autopilot_run(ranked(), transport)
        status.update(last_cycle=datetime.now(timezone.utc).isoformat(), last_error=None)
    except Exception as exc:  # noqa: BLE001 - keep the background loop alive; surface a safe message
        status["last_error"] = str(exc) if isinstance(exc, adopt.AdoptionError) else "Falha inesperada no ciclo automático."
    finally:
        _lock.release()


def trigger():
    threading.Thread(target=cycle, daemon=True).start()


def _loop():
    while True:
        cycle()
        time.sleep(INTERVAL_SECONDS)


def start_background():
    threading.Thread(target=_loop, daemon=True, name="aes-pipeline").start()
