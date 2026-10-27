"""Small authenticated dashboard for the AES research runner."""
import base64
from collections import deque
from datetime import datetime, timezone
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
MAX_DISCOVERIES = 400
MAX_RUN_HISTORY = 12
MAX_POST_BYTES = 4096
TRIAGE_STATES = {"new", "interesting", "dismissed"}
_process_lock = threading.Lock()
_triage_lock = threading.Lock()
_manual_process = None
_manual_started_at = None

PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AES · Painel de inovação</title><style>
:root{color-scheme:dark;--bg:#101116;--card:#191b23;--card2:#1f2230;--line:#2c2f3a;--text:#f2f2f5;--muted:#a7a9b5;--accent:#a78bfa;--accent2:#805be8;--green:#57d49a;--amber:#f5c26b;--red:#ff7777}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% 0,#27203d 0,transparent 44%),var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:1180px;margin:40px auto;padding:0 16px}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.13em;text-transform:uppercase;font-size:12px}h1{margin:7px 0 4px;font-size:clamp(26px,4vw,40px);line-height:1.15}.sub{color:var(--muted);margin:0}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:24px}.top-actions{display:flex;flex-direction:column;align-items:flex-end;gap:6px}
.btn{background:var(--accent2);color:#fff;border:0;border-radius:10px;padding:11px 18px;font:inherit;font-weight:700;cursor:pointer}.btn:disabled{opacity:.55;cursor:wait}.btn:focus-visible,.chip-btn:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card{background:color-mix(in srgb,var(--card) 92%,transparent);border:1px solid var(--line);border-radius:14px;padding:16px;min-width:0}
.label{color:var(--muted);font-size:13px}.metric{font-size:26px;font-weight:750;margin-top:4px;line-height:1.2;font-variant-numeric:tabular-nums}.hint{color:var(--muted);font-size:13px;margin-top:4px}
.status{display:flex;align-items:center;gap:8px}.dot{flex:none;width:9px;height:9px;border-radius:50%;background:var(--green)}.dot.run{background:var(--amber);animation:pulse 1.2s infinite}.dot.err{background:var(--red)}.dot.off{background:var(--muted)}@keyframes pulse{50%{opacity:.35}}
.layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:12px;margin-top:12px;align-items:start}.side{display:grid;gap:12px}
h2{font-size:17px;margin:0}.head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:12px}.count{color:var(--muted);font-size:13px}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}.toolbar input,.toolbar select{background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:8px 10px;font:inherit;font-size:14px;min-width:0}.toolbar input{flex:1 1 200px}.toolbar select{flex:0 1 200px}
.seg{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px}.chip-btn{background:transparent;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}.chip-btn[aria-pressed=true]{background:color-mix(in srgb,var(--accent2) 30%,transparent);border-color:var(--accent);color:var(--text)}
.list{display:grid;gap:8px;list-style:none;margin:0;padding:0}.item{background:var(--card2);border:1px solid var(--line);border-radius:11px;padding:12px 14px}.item.dismissed{opacity:.6}.item.interesting{border-color:color-mix(in srgb,var(--amber) 55%,var(--line))}
.item a.title{color:var(--text);font-weight:650;text-decoration:none;overflow-wrap:anywhere}.item a.title:hover{color:#c4b5fd;text-decoration:underline}.meta{color:var(--muted);font-size:12.5px;margin-top:3px;display:flex;flex-wrap:wrap;gap:4px 10px}
.evidence{color:#cfd0d8;font-size:13.5px;margin:6px 0 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:7px}.tag{font-size:11.5px;color:#c4b5fd;background:color-mix(in srgb,var(--accent2) 16%,transparent);border-radius:6px;padding:1px 7px}
.actions{display:flex;gap:6px;margin-top:9px}.actions .chip-btn{padding:3px 10px;font-size:12.5px}.chip-btn.on-int{border-color:var(--amber);color:var(--amber)}
.empty{color:var(--muted);text-align:center;padding:28px 10px;border:1px dashed var(--line);border-radius:11px}.more{margin-top:10px;width:100%}
.rows{list-style:none;margin:0;padding:0;display:grid;gap:2px}.rows li{display:flex;align-items:center;gap:9px;padding:7px 0;border-top:1px solid var(--line);font-size:13.5px}.rows li:first-child{border-top:0}.rows .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rows .num{color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}
.bars{display:flex;align-items:flex-end;gap:4px;height:46px;margin:4px 0 8px}.bars span{flex:1;background:var(--accent2);border-radius:3px 3px 0 0;min-height:2px}.bars span.zero{background:var(--line)}
.badge{font-size:11.5px;border-radius:6px;padding:1px 7px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}.badge.accepted{color:var(--green);border-color:var(--green)}.badge.rejected{color:var(--red);border-color:var(--red)}.badge.deferred{color:var(--amber);border-color:var(--amber)}
details.card summary{cursor:pointer;font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:460px;overflow:auto;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:14px;font:13px/1.6 ui-monospace,monospace;margin:12px 0 0}
code{font:12.5px ui-monospace,monospace;background:var(--bg);border-radius:5px;padding:1px 5px}.error{color:var(--red)}.foot{color:var(--muted);font-size:12px;margin-top:16px}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:10px 16px;font-size:14px;max-width:calc(100% - 32px);display:none}.toast.show{display:block}
@media(max-width:900px){.layout{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){main{margin:20px auto}.top{flex-direction:column;align-items:stretch}.top-actions{align-items:stretch}.metric{font-size:22px}.toolbar select{flex:1 1 100%}}
</style></head><body><main>
<header class="top"><div><div class="eyebrow">Agent Engineering System</div><h1>Painel de inovação</h1><p class="sub">Pesquisa contínua, triagem de descobertas e estado salvo do AES.</p></div>
<div class="top-actions"><button class="btn" id="run">Iniciar pesquisa agora</button><span class="hint" id="updated" aria-live="polite"></span></div></header>
<div class="kpis">
<section class="card"><div class="label">Estado</div><div class="metric status" id="state"><span class="dot off"></span>Carregando</div><div class="hint" id="attempt"></div></section>
<section class="card"><div class="label">Última execução</div><div class="metric" id="when">—</div><div class="hint" id="whenDetail"></div></section>
<section class="card"><div class="label">Novos na última execução</div><div class="metric" id="new">—</div><div class="hint" id="fetched"></div></section>
<section class="card"><div class="label">Para triar</div><div class="metric" id="untriaged">—</div><div class="hint" id="triageDetail"></div></section>
</div>
<div class="layout">
<section class="card" aria-labelledby="discTitle"><div class="head"><h2 id="discTitle">Descobertas</h2><span class="count" id="discCount"></span></div>
<div class="seg" role="group" aria-label="Filtrar por triagem" id="seg">
<button class="chip-btn" data-f="new" aria-pressed="true">Para triar</button><button class="chip-btn" data-f="interesting" aria-pressed="false">Interessantes</button><button class="chip-btn" data-f="dismissed" aria-pressed="false">Descartadas</button><button class="chip-btn" data-f="all" aria-pressed="false">Todas</button></div>
<div class="toolbar"><input id="q" type="search" placeholder="Buscar por título, resumo ou tópico" aria-label="Buscar descobertas"><select id="src" aria-label="Filtrar por fonte"><option value="">Todas as fontes</option></select></div>
<ul class="list" id="list"></ul><button class="chip-btn more" id="more" hidden>Mostrar mais</button></section>
<div class="side">
<section class="card" aria-labelledby="srcTitle"><div class="head"><h2 id="srcTitle">Fontes</h2><span class="count" id="srcCount"></span></div><ul class="rows" id="sources"></ul></section>
<section class="card" aria-labelledby="histTitle"><div class="head"><h2 id="histTitle">Histórico</h2><span class="count">novos por execução</span></div><div class="bars" id="bars" aria-hidden="true"></div><ul class="rows" id="history"></ul></section>
<section class="card" aria-labelledby="propTitle"><div class="head"><h2 id="propTitle">Propostas</h2><span class="count" id="propCount"></span></div><ul class="rows" id="proposals"></ul></section>
</div></div>
<details class="card" style="margin-top:12px"><summary>Digest mais recente <span class="count" id="digestDate"></span></summary><pre id="digest">—</pre></details>
<p class="foot">Itens coletados são hipóteses baseadas em metadados dos feeds. A triagem só organiza a fila de leitura: não verifica fontes nem cria propostas. Para registrar uma proposta, revise a fonte primária e use <code>innovation.py record proposal</code>. O painel não atualiza projetos automaticamente.</p>
</main><div class="toast" id="toast" role="status"></div><script>
const $=id=>document.getElementById(id);const PAGE_SIZE=25;
const ERR={HTTP404:'feed não encontrado (404)',HTTP403:'acesso negado (403)',HTTP429:'limite de requisições (429)',Timeout:'tempo esgotado',NetworkError:'falha de rede',MalformedXml:'XML inválido',UnsafeXml:'XML com DTD bloqueado',ResponseSizeLimit:'resposta acima de 2 MB',InvalidFeed:'feed inválido',InvalidSourceConfig:'configuração inválida'};
const LABEL={new:'Para triar',interesting:'Interessante',dismissed:'Descartada'};
const DECISION={proposed:'proposta',accepted:'aceita',rejected:'rejeitada',deferred:'adiada'};
let items=[],filter='new',shown=PAGE_SIZE,wasRunning=false;
const num=n=>Number(n||0).toLocaleString('pt-BR');
function fmtDate(v,opt){if(!v)return'—';const d=new Date(v);return isNaN(d)?v:d.toLocaleString('pt-BR',opt||{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'})}
function ago(v){if(!v)return'';const s=(Date.now()-new Date(v))/1000;if(s<60)return'agora mesmo';const m=s/60;if(m<60)return`há ${Math.round(m)} min`;const h=m/60;if(h<24)return`há ${Math.round(h)} h`;const d=h/24;return`há ${Math.round(d)} dia${Math.round(d)>1?'s':''}`}
function secs(v){return v==null?'':`${Number(v).toLocaleString('pt-BR',{maximumFractionDigits:1})} s`}
function el(tag,attrs,...kids){const e=document.createElement(tag);for(const[k,v]of Object.entries(attrs||{})){if(k==='class')e.className=v;else if(k==='text')e.textContent=v;else e.setAttribute(k,v)}for(const k of kids)if(k!=null)e.append(k);return e}
function toast(msg){const t=$('toast');t.textContent=msg;t.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>t.classList.remove('show'),3500)}
function setState(cls,text){const s=$('state');s.replaceChildren(el('span',{class:'dot '+cls}),text)}
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const d=await r.json();const run=d.latest_run;
setState(d.running?'run':!d.state_available?'off':run&&run.source_errors_count?'err':'',d.running?'Pesquisando…':!d.state_available?'Sem dados':run&&run.source_errors_count?'Com alertas':'Pronto');
const a=d.manual_attempt;$('attempt').textContent=a?`Disparo manual ${a.running?'em andamento':a.exit_code===0?'concluído':`falhou (código ${a.exit_code})`} · ${ago(a.started_at)}`:'';
$('when').textContent=run?ago(run.finished_at):'—';$('whenDetail').textContent=run?`${fmtDate(run.finished_at)} · ${secs(run.duration_seconds)}`:'Nenhuma execução registrada';
$('new').textContent=run?num(run.new):'—';$('fetched').textContent=run?`de ${num(run.fetched)} itens lidos`+(run.rejected_by_sensitivity_rules?` · ${run.rejected_by_sensitivity_rules} bloqueados por sensibilidade`:''):'';
const t=d.triage_counts||{};$('untriaged').textContent=num(t.new);$('triageDetail').textContent=`${num(t.interesting)} interessantes · ${num(t.dismissed)} descartadas · ${num(d.discovery_count)} no total`;
renderSources(d.sources||[]);renderHistory(d.run_history||[]);renderProposals(d.proposals||[],d.proposal_count);
$('digestDate').textContent=d.digest_name?'· '+d.digest_name:'· ainda não há digest';$('digest').textContent=d.digest||'—';
$('run').disabled=!!d.running;$('run').textContent=d.running?'Pesquisa em andamento…':'Iniciar pesquisa agora';$('updated').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
if(wasRunning&&!d.running){toast(run?`Pesquisa concluída: ${run.new} novos itens.`:'Pesquisa concluída.');loadDiscoveries()}wasRunning=!!d.running}
catch(e){setState('err','Indisponível');$('updated').textContent='Não foi possível ler o estado salvo.'}}
function renderSources(list){const ul=$('sources');ul.replaceChildren();let ok=0,on=0;for(const s of list){if(s.enabled)on++;if(s.enabled&&!s.error)ok++;
const dot=el('span',{class:'dot '+(!s.enabled?'off':s.error?'err':s.items==null?'off':'')});const detail=!s.enabled?'desativada':s.error?(ERR[s.error]||s.error):s.items==null?'sem dados':`${s.items} itens`;
ul.append(el('li',{title:s.url||''},dot,el('span',{class:'grow',text:s.name}),el('span',{class:'num'+(s.error?' error':''),text:detail})))}
if(!list.length)ul.append(el('li',{},el('span',{class:'grow',text:'Nenhuma fonte configurada.'})));$('srcCount').textContent=`${ok}/${on} ok`}
function renderHistory(runs){const bars=$('bars'),ul=$('history');bars.replaceChildren();ul.replaceChildren();const max=Math.max(1,...runs.map(r=>r.new||0));
for(const r of runs)bars.append(el('span',{class:r.new?'':'zero',style:`height:${Math.max(4,(r.new||0)/max*100)}%`,title:`${fmtDate(r.finished_at)}: ${r.new} novos`}));
for(const r of runs.slice().reverse().slice(0,5))ul.append(el('li',{},el('span',{class:'grow',text:fmtDate(r.finished_at)}),el('span',{class:'num',text:`+${r.new} de ${r.fetched}`}),r.source_errors_count?el('span',{class:'badge rejected',text:`${r.source_errors_count} erro${r.source_errors_count>1?'s':''}`}):null));
if(!runs.length)ul.append(el('li',{},el('span',{class:'grow',text:'Nenhuma execução ainda.'})))}
function renderProposals(list,total){const ul=$('proposals');ul.replaceChildren();$('propCount').textContent=total?`${list.length} · ${total} revisões`:'';
for(const p of list){const link=p.url?el('a',{href:p.url,target:'_blank',rel:'noopener noreferrer',class:'grow',text:p.title}):el('span',{class:'grow',text:p.title});
ul.append(el('li',{},link,el('span',{class:'badge '+(p.decision||''),text:DECISION[p.decision]||p.decision||'—'})))}
if(!list.length)ul.append(el('li',{},el('span',{class:'hint',text:'Nenhuma proposta ainda. Marque leads como interessantes, verifique a fonte primária e registre a proposta pelo CLI.'})))}
async function loadDiscoveries(){try{const r=await fetch('/api/discoveries',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();items=d.discoveries||[];
const sel=$('src'),cur=sel.value;sel.replaceChildren(el('option',{value:'',text:'Todas as fontes'}));for(const s of d.feeds||[])sel.append(el('option',{value:s.feed,text:`${s.name} (${s.count})`}));sel.value=cur;renderList()}
catch(e){$('list').replaceChildren(el('li',{class:'empty',text:'Não foi possível carregar as descobertas.'}))}}
function matches(it){if(filter!=='all'&&it.triage!==filter)return false;if($('src').value&&it.feed!==$('src').value)return false;const q=$('q').value.trim().toLowerCase();if(!q)return true;return[it.title,it.summary,(it.topics||[]).join(' '),it.feed_name].join(' ').toLowerCase().includes(q)}
function renderList(){const ul=$('list');ul.replaceChildren();const found=items.filter(matches);$('discCount').textContent=`${num(found.length)} de ${num(items.length)}`;
for(const it of found.slice(0,shown))ul.append(card(it));
if(!found.length)ul.append(el('li',{class:'empty',text:filter==='new'&&items.length?'Fila vazia: todas as descobertas já foram triadas.':items.length?'Nenhuma descoberta corresponde aos filtros.':'Nenhuma descoberta registrada ainda. Inicie uma pesquisa.'}));
$('more').hidden=found.length<=shown;$('more').textContent=`Mostrar mais (${num(found.length-shown)} restantes)`}
function card(it){const title=it.url?el('a',{class:'title',href:it.url,target:'_blank',rel:'noopener noreferrer',text:it.title}):el('span',{class:'title',text:it.title});
const meta=el('div',{class:'meta'},el('span',{text:it.feed_name||'Fonte desconhecida'}),el('span',{text:it.date?fmtDate(it.date+'T12:00:00',{day:'2-digit',month:'short',year:'numeric'}):''}),it.triage!=='new'?el('span',{text:LABEL[it.triage]}):null);
const tags=el('div',{class:'tags'});for(const t of(it.topics||[]).slice(0,5))tags.append(el('span',{class:'tag',text:t}));
const acts=el('div',{class:'actions'});
if(it.triage!=='interesting')acts.append(btn('★ Interessante','interesting',it,'on-int'));if(it.triage!=='dismissed')acts.append(btn('Descartar','dismissed',it));if(it.triage!=='new')acts.append(btn('Voltar para triagem','new',it));
return el('li',{class:'item '+it.triage},title,meta,it.summary?el('p',{class:'evidence',text:it.summary}):null,tags,acts)}
function btn(text,state,it,cls){const b=el('button',{class:'chip-btn '+(cls||''),type:'button',text});b.addEventListener('click',()=>triage(it,state,b));return b}
async function triage(it,state,b){b.disabled=true;try{const r=await fetch('/api/triage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:it.source,state})});const d=await r.json();if(!r.ok)throw Error(d.error);
it.triage=state;renderList();refresh()}catch(e){b.disabled=false;toast('Não foi possível salvar a triagem.')}}
$('seg').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;filter=b.dataset.f;shown=PAGE_SIZE;for(const x of $('seg').children)x.setAttribute('aria-pressed',x===b);renderList()});
$('q').addEventListener('input',()=>{shown=PAGE_SIZE;renderList()});$('src').addEventListener('change',()=>{shown=PAGE_SIZE;renderList()});$('more').addEventListener('click',()=>{shown+=PAGE_SIZE;renderList()});
$('run').addEventListener('click',async()=>{$('run').disabled=true;$('run').textContent='Iniciando…';try{const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'}});const d=await r.json();if(!r.ok)toast(d.error==='research is already running'?'Já existe uma pesquisa em andamento.':'Não foi possível iniciar a pesquisa.');else{wasRunning=true;toast('Pesquisa iniciada.')}}catch(e){toast('Não foi possível iniciar a pesquisa.')}await refresh()});
refresh();loadDiscoveries();setInterval(refresh,10000);
</script></body></html>"""


def _read_jsonl(path, keep=None):
    """Read dict rows from a JSONL file, skipping malformed lines; keep only the last ``keep`` when given."""
    rows = deque(maxlen=keep)
    try:
        with path.open("rb") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except OSError:
        return []
    return list(rows)


def _https_or_none(value):
    return value if isinstance(value, str) and urlsplit(value).scheme == "https" else None


def _key(source):
    return (source or "").strip().lower()


def _load_sources():
    try:
        config = json.loads(innovation.SOURCES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sources = config.get("sources") if isinstance(config, dict) else None
    return [s for s in sources if isinstance(s, dict)] if isinstance(sources, list) else []


def _triage_path():
    return innovation.STATE / "research" / "triage.jsonl"


def _triage_map():
    result = {}
    for row in _read_jsonl(_triage_path()):
        if row.get("state") in TRIAGE_STATES and isinstance(row.get("source"), str):
            result[_key(row["source"])] = row["state"]
    return result


def _run_summary(row):
    return {"finished_at": row.get("finished_at"), "duration_seconds": row.get("duration_seconds"),
            "fetched": row.get("fetched", 0), "new": row.get("new", 0),
            "source_errors_count": len(row.get("source_errors") or [])}


def dashboard_status():
    state = innovation.STATE
    research = state / "research"
    runs = _read_jsonl(research / "runs.jsonl", keep=200)
    register = _read_jsonl(research / "register.jsonl")
    digest_files = sorted((research / "digests").glob("*.md"), reverse=True) if (research / "digests").exists() else []
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

    # Per-source health comes from the most recent run that consulted or failed each source.
    last_items, last_errors = {}, {}
    for row in runs:
        for count in row.get("source_counts") or []:
            last_items[count.get("source_id")] = count.get("items")
            last_errors.pop(count.get("source_id"), None)
        for error in row.get("source_errors") or []:
            last_errors[error.get("source_id")] = error.get("error")
            last_items.pop(error.get("source_id"), None)
    sources = [{"id": s.get("id"), "name": s.get("name") or s.get("id"), "url": _https_or_none(s.get("url")),
                "enabled": bool(s.get("enabled", True)), "items": last_items.get(s.get("id")),
                "error": last_errors.get(s.get("id"))} for s in _load_sources()]

    triage = _triage_map()
    discoveries = [row for row in register if row.get("kind") == "discovery"]
    triage_counts = {state_name: 0 for state_name in TRIAGE_STATES}
    for row in discoveries:
        triage_counts[triage.get(_key(row.get("source")), "new")] += 1

    latest_proposals = {}
    for row in register:
        if row.get("kind") == "proposal":
            latest_proposals[(_key(row.get("source")), _key(row.get("title")))] = row
    proposals = [{"title": str(p.get("title", ""))[:240], "url": _https_or_none(p.get("source")),
                  "decision": p.get("decision"), "priority": p.get("priority"), "revision": p.get("revision", 1),
                  "recorded_at": p.get("recorded_at")}
                 for p in sorted(latest_proposals.values(), key=lambda p: p.get("recorded_at") or "", reverse=True)]

    return {"state_available": state.exists(), "running": running, "latest_run": run,
            "discovery_count": len(discoveries),
            "proposal_count": sum(row.get("kind") == "proposal" for row in register),
            "triage_counts": triage_counts, "sources": sources, "proposals": proposals[:20],
            "run_history": [_run_summary(row) for row in runs[-MAX_RUN_HISTORY:]],
            "manual_attempt": manual_attempt,
            "digest_name": digest_name, "digest": digest}


def dashboard_discoveries():
    register = _read_jsonl(innovation.STATE / "research" / "register.jsonl")
    triage = _triage_map()
    names = {s.get("url"): s.get("name") for s in _load_sources()}
    rows = [row for row in register if row.get("kind") == "discovery" and isinstance(row.get("source"), str)]
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("recorded_at") or "")), reverse=True)
    discoveries, feeds = [], {}
    prefix = "RSS/Atom metadata from "
    for row in rows[:MAX_DISCOVERIES]:
        feed = row.get("source_feed") if isinstance(row.get("source_feed"), str) else ""
        feed_name = names.get(feed) or urlsplit(feed).hostname or "Fonte desconhecida"
        summary = str(row.get("evidence") or "")
        # Strip the generated "RSS/Atom metadata from <name>." prefix; the feed name is shown separately.
        if summary.startswith(prefix):
            summary = summary.split(". ", 1)[1] if ". " in summary else ""
        discoveries.append({
            "title": str(row.get("title", ""))[:240], "source": row["source"],
            "url": _https_or_none(row["source"]), "date": row.get("date"), "summary": summary[:500],
            "topics": [str(t)[:40] for t in (row.get("topics") or []) if isinstance(t, str)][:8],
            "feed": feed, "feed_name": feed_name, "status": row.get("status"),
            "triage": triage.get(_key(row["source"]), "new")})
        entry = feeds.setdefault(feed, {"feed": feed, "name": feed_name, "count": 0})
        entry["count"] += 1
    return {"discoveries": discoveries, "total": len(rows),
            "feeds": sorted(feeds.values(), key=lambda f: f["name"].lower())}


def set_triage(source, triage_state):
    """Append a triage decision for a recorded discovery. Returns False if the discovery is unknown."""
    if triage_state not in TRIAGE_STATES or not isinstance(source, str) or not source or len(source) > 2048:
        raise ValueError("invalid triage request")
    register = _read_jsonl(innovation.STATE / "research" / "register.jsonl")
    if not any(row.get("kind") == "discovery" and _key(row.get("source")) == _key(source) for row in register):
        return False
    path = _triage_path()
    with _triage_lock:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": datetime.now(timezone.utc).isoformat(), "source": source,
                                "state": triage_state}, ensure_ascii=False) + "\n")
        if os.name != "nt":
            path.chmod(0o600)
    return True


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

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc.lower() != self.headers.get("Host", "").lower() or parsed.scheme not in {"http", "https"}:
                self._json(403, {"error": "cross-origin request blocked"})
                return False
        return True

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_POST_BYTES:
            self._json(413, {"error": "request body too large"})
            return None
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._json(415, {"error": "expected application/json"})
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            self._json(400, {"error": "invalid JSON body"})
            return None
        return payload

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
        elif path == "/api/discoveries":
            self._json(200, dashboard_discoveries())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        if path not in {"/api/run", "/api/triage"}:
            self._json(404, {"error": "not found"})
            return
        if not self._same_origin():
            return
        if path == "/api/triage":
            payload = self._read_json_body()
            if payload is None:
                return
            try:
                saved = set_triage(payload.get("source"), payload.get("state"))
            except ValueError:
                self._json(400, {"error": "invalid triage request"})
                return
            except OSError:
                self._json(500, {"error": "triage could not be saved"})
                return
            if not saved:
                self._json(404, {"error": "discovery not found"})
                return
            self._json(200, {"saved": True})
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
