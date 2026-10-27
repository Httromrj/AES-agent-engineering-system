"""Community signals for discoveries: Hacker News discussion and GitHub stars, plus trending-repo discovery.

Popularity is a proxy for what practitioners find valuable, not proof of quality: stars can be bought and
topics are self-assigned. Scores therefore combine popularity with the model's relevance rating for the
registered projects and the source's authority, and trending repos must pass basic anti-spam checks.
"""
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import adopt
import innovation

HN_API = "https://hn.algolia.com/api/v1/search"
# Only a repository's own page earns its stars; a release or issue inside a popular repo is not itself popular.
GITHUB_REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)/?$")
CHECK_EVERY = timedelta(hours=12)
MAX_CHECKS_PER_CYCLE = 60
TRENDING_FEED = "https://github.com/search?type=repositories (AES trending)"
TRENDING_QUERIES = [
    ("agent-skills", "topic:agent-skills"), ("claude-code", "topic:claude-code"), ("mcp", "topic:mcp-server"),
    ("codex", "topic:codex"), ("design-system", "topic:design-system"), ("ai-coding", "topic:ai-coding"),
]
TRENDING_MIN_STARS = 150


def _now():
    return datetime.now(timezone.utc)


def _path():
    return innovation.STATE / "research" / "signals.jsonl"


def _key(url):
    return (url or "").strip().lower()


def _get_json(url, headers=None, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": "AES-signals", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(3_000_000).decode("utf-8"))


def _github(path):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = adopt.github_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    return _get_json("https://api.github.com" + path, headers)


def snapshots():
    """All snapshots grouped by discovery URL, oldest first."""
    result = {}
    try:
        with _path().open("rb") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("source"):
                    result.setdefault(_key(row["source"]), []).append(row)
    except OSError:
        pass
    return result


def latest():
    """Latest signal per discovery, with the 7-day star growth computed from older snapshots."""
    result = {}
    week_ago = (_now() - timedelta(days=7)).isoformat()
    for key, rows in snapshots().items():
        last = dict(rows[-1])
        stars = [r for r in rows if r.get("stars") is not None]
        if stars:
            base = next((r for r in stars if r["at"] >= week_ago), stars[0])
            last["stars_delta"] = max(0, int(stars[-1]["stars"]) - int(base["stars"]))
        result[key] = last
    return result


def hacker_news(url):
    bare = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    query = urllib.parse.urlencode({"query": bare, "restrictSearchableAttributes": "url", "tags": "story", "hitsPerPage": 5})
    hits = [h for h in _get_json(f"{HN_API}?{query}").get("hits", [])
            if bare.lower() in re.sub(r"^https?://(www\.)?", "", h.get("url") or "").lower()]
    if not hits:
        return {"hn_points": 0, "hn_comments": 0}
    top = max(hits, key=lambda h: h.get("points") or 0)
    return {"hn_points": sum(h.get("points") or 0 for h in hits), "hn_comments": sum(h.get("num_comments") or 0 for h in hits),
            "hn_url": f"https://news.ycombinator.com/item?id={top['objectID']}"}


def github_repo(url):
    match = GITHUB_REPO_RE.match(url or "")
    if not match:
        return {}
    repo = _github(f"/repos/{match.group(1)}/{match.group(2).removesuffix('.git')}")
    return {"stars": repo.get("stargazers_count", 0), "forks": repo.get("forks_count", 0), "repo": repo.get("full_name")}


def refresh(limit=MAX_CHECKS_PER_CYCLE):
    """Fetch signals for recent discoveries that were never checked or were checked more than 12 hours ago."""
    seen = latest()
    cutoff = (_now() - timedelta(days=45)).date().isoformat()
    stale = (_now() - CHECK_EVERY).isoformat()
    rows = [r for r in adopt.innovation_rows() if r.get("kind") == "discovery" and isinstance(r.get("source"), str)
            and str(r.get("date") or "") >= cutoff and seen.get(_key(r["source"]), {}).get("at", "") < stale]
    rows.sort(key=lambda r: seen.get(_key(r["source"]), {}).get("at", ""))
    written = 0
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for row in rows[:limit]:
        snapshot = {"source": row["source"], "at": _now().isoformat()}
        try:
            snapshot.update(hacker_news(row["source"]))
            snapshot.update(github_repo(row["source"]))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        written += 1
    return written


def discover_trending():
    """Record new, fast-rising GitHub repositories in agent, skills, MCP, and design topics as discoveries."""
    since = (_now() - timedelta(days=30)).date().isoformat()
    added = 0
    for label, query in TRENDING_QUERIES:
        q = urllib.parse.quote(f"{query} created:>{since} archived:false fork:false")
        try:
            items = _github(f"/search/repositories?q={q}&sort=stars&order=desc&per_page=10").get("items", [])
        except (OSError, ValueError, urllib.error.URLError):
            continue
        for repo in items:
            stars, forks = repo.get("stargazers_count", 0), repo.get("forks_count", 0)
            description = " ".join(str(repo.get("description") or "").split())[:300]
            # Bought stars rarely come with forks; repos without a description are rarely useful.
            if stars < TRENDING_MIN_STARS or forks < max(3, stars // 100) or not description:
                continue
            record = {
                "title": f"{repo['full_name']}: {description}"[:240], "source": repo["html_url"],
                "date": str(repo.get("created_at") or "")[:10] or _now().date().isoformat(),
                "evidence": f"GitHub em alta. {description} Estrelas: {stars}; forks: {forks}; linguagem: {repo.get('language') or 'n/d'}.",
                "alternatives": [], "limitations": "Popularidade no GitHub não comprova qualidade; revise o repositório.",
                "applicability": "Hipótese; avaliar contra os projetos cadastrados.", "status": "hypothesis",
                "source_feed": TRENDING_FEED, "source_authority": "community", "topics": [label], "source_priority": 2,
            }
            try:
                if innovation.add_record("discovery", record):
                    added += 1
            except ValueError:
                continue
    return added


def score(signal, rating, authority):
    """0-100: popularity (max 50) + relevance to registered projects (max 40) + official source (10)."""
    signal = signal or {}
    hn = 9 * math.log10(1 + (signal.get("hn_points") or 0) + 2 * (signal.get("hn_comments") or 0))
    gh = 7 * math.log10(1 + (signal.get("stars") or 0)) + min(15, 7 * math.log10(1 + (signal.get("stars_delta") or 0)))
    popularity = min(50.0, min(35.0, hn) + min(35.0, gh))
    relevance = None if rating is None else max(0, min(10, int(rating))) * 4
    total = popularity + (relevance or 0) + (10 if authority == "official" else 0)
    return {"score": round(min(100, total)), "popularity": round(popularity), "relevance_points": relevance}
