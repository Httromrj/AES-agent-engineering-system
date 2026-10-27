"""Small authenticated dashboard for the AES research runner."""
import base64
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import innovation

HOST = os.environ.get("AES_DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", os.environ.get("AES_DASHBOARD_PORT", "8080")))
USERNAME = os.environ.get("AES_DASHBOARD_USER", "aes")
PASSWORD = os.environ.get("AES_DASHBOARD_PASSWORD", "")
MAX_STATE_READ = 2_000_000
_process_lock = threading.Lock()
_manual_process = None
_manual_started_at = None

PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AES · Painel de inovação</title><style>
:root{color-scheme:dark;--bg:#101116;--card:#191b23;--line:#2c2f3a;--text:#f2f2f5;--muted:#a7a9b5;--accent:#a78bfa;--green:#57d49a;--red:#ff7777}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% 0,#27203d 0,transparent 44%),var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:1080px;margin:48px auto;padding:0 22px}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.13em;text-transform:uppercase;font-size:12px}h1{margin:7px 0 4px;font-size:clamp(28px,4vw,42px)}.sub{color:var(--muted);margin:0 0 25px}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:22px}.btn{background:#805be8;color:white;border:0;border-radius:10px;padding:12px 18px;font-weight:700;cursor:pointer}.btn:disabled{opacity:.55;cursor:wait}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}.card{background:color-mix(in srgb,var(--card) 90%,transparent);border:1px solid var(--line);border-radius:15px;padding:17px}.label{color:var(--muted);font-size:13px}.metric{font-size:28px;font-weight:750;margin-top:5px}.wide{grid-column:span 2}.section{margin-top:15px}h2{font-size:18px;margin:0 0 11px}.status{display:flex;align-items:center;gap:8px}.dot{width:9px;height:9px;background:var(--green);border-radius:50%}.muted{color:var(--muted)}.error{color:var(--red)}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:460px;overflow:auto;background:#101116;border:1px solid var(--line);border-radius:10px;padding:15px;font:13px/1.6 ui-monospace,monospace}a{color:#c4b5fd}.foot{color:var(--muted);font-size:12px;margin-top:16px}@media(max-width:760px){main{margin:24px auto}.grid{grid-template-columns:repeat(2,1fr)}.wide{grid-column:span 2}.top{align-items:flex-start;flex-direction:column}}
</style></head><body><main>
<div class="top"><div><div class="eyebrow">Agent Engineering System</div><h1>Painel de inovação</h1><p class="sub">Resumo da pesquisa contínua e do estado salvo do AES.</p></div><button class="btn" id="run">Iniciar pesquisa agora</button></div>
<div class="grid">
<section class="card"><div class="label">Estado</div><div class="metric status" id="state">Carregando</div></section>
<section class="card"><div class="label">Última execução</div><div class="metric" id="when">—</div><div class="muted" id="duration"></div></section>
<section class="card"><div class="label">Novidades novas</div><div class="metric" id="new">—</div><div class="muted" id="fetched"></div></section>
<section class="card"><div class="label">Fontes com erro</div><div class="metric" id="errors">—</div></section>
<section class="card"><div class="label">Descobertas registradas</div><div class="metric" id="discoveries">—</div></section>
<section class="card"><div class="label">Propostas</div><div class="metric" id="proposals">—</div></section>
<section class="card wide"><h2>Última execução</h2><div class="muted" id="runDetails">Aguardando dados…</div></section>
<section class="card wide"><h2>Digest mais recente</h2><div class="muted" id="digestDate">Ainda não há digest.</div><pre id="digest">—</pre></section>
</div><p class="foot">Itens coletados são hipóteses baseadas em metadados dos feeds. Revise fontes e aplicabilidade antes de adotar uma mudança. O painel não atualiza projetos automaticamente.</p>
</main><script>
const byId=id=>document.getElementById(id);const fmtDate=v=>v?new Date(v).toLocaleString('pt-BR',{dateStyle:'medium',timeStyle:'short'}):'—';
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();const run=d.latest_run;byId('state').innerHTML='<span class="dot"></span>'+(d.running?'Pesquisa em andamento':d.state_available?'Pronto':'Aguardando primeira execução');byId('when').textContent=run?fmtDate(run.finished_at):'—';byId('duration').textContent=run?`${run.duration_seconds}s de duração`:'Nenhuma execução registrada';byId('new').textContent=run?run.new:'—';byId('fetched').textContent=run?`${run.fetched} itens lidos`:'—';byId('errors').textContent=run?run.source_errors_count:'—';byId('discoveries').textContent=d.discovery_count;byId('proposals').textContent=d.proposal_count;const lastAttempt=d.manual_attempt?` · disparo manual: ${d.manual_attempt.running?'em andamento':d.manual_attempt.exit_code===0?'concluído (código 0)':`falhou (código ${d.manual_attempt.exit_code})`}`:'';byId('runDetails').textContent=(run?`${run.sources_configured} fontes configuradas · ${run.source_counts.length} consultadas · ${run.rejected_by_sensitivity_rules} registros bloqueados pelas regras de sensibilidade`:'A pesquisa ainda não foi executada.')+lastAttempt;byId('digestDate').textContent=d.digest_name||'Ainda não há digest.';byId('digest').textContent=d.digest||'—';byId('run').disabled=!!d.running;byId('run').textContent=d.running?'Pesquisa em andamento…':'Iniciar pesquisa agora'}catch(e){byId('state').innerHTML='<span class="error">Painel indisponível</span>';byId('runDetails').textContent='Não foi possível ler o estado salvo.'}}
byId('run').addEventListener('click',async()=>{byId('run').disabled=true;byId('run').textContent='Iniciando…';try{const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)alert(d.error||'Não foi possível iniciar a pesquisa.')}catch(e){alert('Não foi possível iniciar a pesquisa.')}await refresh()});refresh();setInterval(refresh,10000);
</script></body></html>"""


def _read_jsonl(path):
    try:
        data = path.read_bytes()[-MAX_STATE_READ:]
    except OSError:
        return []
    rows = []
    for line in data.splitlines()[-500:]:
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return rows


def dashboard_status():
    state = innovation.STATE
    runs = _read_jsonl(state / "research" / "runs.jsonl")
    register = _read_jsonl(state / "research" / "register.jsonl")
    digest_files = sorted((state / "research" / "digests").glob("*.md"), reverse=True) if (state / "research" / "digests").exists() else []
    digest_name, digest = None, ""
    if digest_files:
        digest_name = digest_files[0].name
        try:
            digest = digest_files[0].read_text(encoding="utf-8")[-MAX_STATE_READ:]
        except OSError:
            digest = "Digest não pôde ser lido."
    run = runs[-1] if runs else None
    if run:
        run = {key: run.get(key) for key in (
            "started_at", "finished_at", "duration_seconds", "sources_configured", "source_counts",
            "fetched", "new", "rejected_by_sensitivity_rules")}
        run["source_counts"] = run.get("source_counts") or []
        run["source_errors_count"] = len((runs[-1].get("source_errors") or []))
    with _process_lock:
        running = _manual_process is not None and _manual_process.poll() is None
        manual_attempt = ({"started_at": _manual_started_at, "running": running,
                           "exit_code": None if running else _manual_process.poll()}
                          if _manual_process is not None else None)
    return {"state_available": state.exists(), "running": running, "latest_run": run,
            "discovery_count": sum(row.get("kind") == "discovery" for row in register),
            "proposal_count": sum(row.get("kind") == "proposal" for row in register),
            "manual_attempt": manual_attempt,
            "digest_name": digest_name, "digest": digest}


def start_research():
    global _manual_process, _manual_started_at
    with _process_lock:
        if _manual_process is not None and _manual_process.poll() is None:
            return False
        state = innovation.STATE
        log = state / "research" / "dashboard-run.log"
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = log.open("ab")
        try:
            _manual_process = subprocess.Popen(
                [sys.executable, str(innovation.SCRIPT_DIR / "innovation.py"), "research", "--per-source", "10"],
                cwd=str(innovation.ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL,
                stdout=handle, stderr=subprocess.STDOUT, close_fds=True)
            from datetime import datetime, timezone
            _manual_started_at = datetime.now(timezone.utc).isoformat()
        finally:
            handle.close()
        return True


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AESDashboard"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Avoid recording paths, credentials, or user-supplied data in access logs.
        return

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        try:
            scheme, encoded = header.split(" ", 1)
            supplied = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            supplied = ""
            scheme = ""
        expected = f"{USERNAME}:{PASSWORD}"
        if scheme.lower() == "basic" and hmac.compare_digest(supplied, expected):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="AES dashboard", charset="UTF-8"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        if path == "/":
            data = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == "/api/status":
            self._json(200, dashboard_status())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return
        if urlsplit(self.path).path != "/api/run":
            self._json(404, {"error": "not found"})
            return
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc.lower() != self.headers.get("Host", "").lower() or parsed.scheme not in {"http", "https"}:
                self._json(403, {"error": "cross-origin request blocked"})
                return
        try:
            started = start_research()
        except OSError:
            self._json(500, {"error": "research process could not be started"})
            return
        if not started:
            self._json(409, {"error": "research is already running"})
            return
        self._json(202, {"started": True})


def main():
    if not PASSWORD or len(PASSWORD) < 24:
        raise SystemExit("Set AES_DASHBOARD_PASSWORD to a strong password of at least 24 characters.")
    if not USERNAME or ":" in USERNAME:
        raise SystemExit("Set AES_DASHBOARD_USER to a non-empty username without colons.")
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
