"""Builds the "Minutes when a starter or key bench player is out" page (user, Nov 2026). Not part of the bot.

    python backtest/minutes_page.py OUT.html

For every player and each key teammate (a starter, or a bench player with 20+ MPG), his minutes in games that teammate
played vs games he was out, while both were on the team; plus SportsLine/RotoWire/FantasyPros expected minutes for
2026-27 from pipeline/expected_history.csv (the number the report showed when it went out, else the last pre-tip read;
a player a site dropped before tip has none). Two tabs: "By team" (pick a team, one row per player, click for each
teammate and every game) and "Biggest differences" (one row per player + teammate(s) out, sortable three ways).

Data: backtest/data/box_<season>.csv (ESPN box scores; 2026-27 is refreshed every morning by the live test),
data.json (depth charts: this season's starters). Starters in past seasons = started at least half of his games.
"""
import csv, json, os, re, statistics as st, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from update_data import norm_name  # noqa: E402

MAP = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
SEASONS = {"2024-25": 10, "2025-26": 10, "2026-27": 2}       # games played to count as a player / key teammate


def expected_by_game():
    out = {}
    path = os.path.join(ROOT, "pipeline", "expected_history.csv")
    for r in csv.DictReader(open(path, newline="")):
        v = r.get("at_send") or ("" if r.get("dropped_at") else r.get("expected"))
        if v:
            out[(r["date"], r["team"], norm_name(r["player"]))] = float(v)
    return out


def build_data():
    depth = json.load(open(os.path.join(ROOT, "data.json"))).get("depth", {})
    exp = expected_by_game()
    out = {}
    for season, need in SEASONS.items():
        path = os.path.join(HERE, "data", f"box_{season}.csv")
        if not os.path.exists(path):
            continue
        team_dates, mins, played, starts = defaultdict(set), defaultdict(dict), defaultdict(dict), defaultdict(int)
        info, teams_of = {}, defaultdict(set)
        for r in csv.DictReader(open(path, newline="")):
            t, k = MAP.get(r["team"], r["team"]), r["player_id"]
            team_dates[t].add(r["date"])
            info[(t, k)] = {"name": r["player"], "pos": (r["position"] or "?")[0].replace("P", "G").replace("S", "F")}
            mins[(t, k)][r["date"]] = float(r["minutes"]) if int(r["played"]) else 0.0     # coach's DNP = 0
            teams_of[k].add(t)
            if int(r["played"]):
                played[(t, k)][r["date"]] = float(r["minutes"])
                starts[(t, k)] += int(r["starter"])
        sdata = {}
        for t, dates in team_dates.items():
            dates = sorted(dates)
            ks = [k for (tt, k) in played if tt == t and len(played[(t, k)]) >= need]
            mpg = {k: st.mean(played[(t, k)].values()) for k in ks}
            if season == "2026-27":
                first = {norm_name(re.split(r"[/,]", v)[0].strip()) for v in depth.get(t, {}).values() if isinstance(v, str) and v.strip()}
                # on today's depth chart, or started at least half his games (an injured starter drops off the chart)
                starter = {k: norm_name(info[(t, k)]["name"]) in first or starts[(t, k)] >= 0.5 * len(played[(t, k)]) for k in ks}
            else:
                starter = {k: starts[(t, k)] >= 0.5 * len(played[(t, k)]) for k in ks}
            keys = {}
            for k in ks:
                role = "starter" if starter[k] else "key bench" if mpg[k] >= 20 else None
                if not role:
                    continue
                ds = sorted(mins[(t, k)])
                lo, hi = (dates[0], dates[-1]) if len(teams_of[k]) == 1 else (ds[0], ds[-1])   # traded: only his stint
                keys[k] = {"name": info[(t, k)]["name"], "role": role, "pos": info[(t, k)]["pos"], "mpg": round(mpg[k], 1),
                           "sat": [i for i, d in enumerate(dates) if lo <= d <= hi and d not in played[(t, k)]],
                           "on": [i for i, d in enumerate(dates) if lo <= d <= hi]}
            players = {}
            for k in ks:
                p = {"name": info[(t, k)]["name"], "pos": info[(t, k)]["pos"], "mpg": round(mpg[k], 1),
                     "m": [None if mins[(t, k)].get(d) is None else round(mins[(t, k)][d]) for d in dates]}
                if season == "2026-27":
                    p["e"] = [exp.get((d, t, norm_name(info[(t, k)]["name"]))) for d in dates]
                players[k] = p
            sdata[t] = {"dates": [d[5:] for d in dates], "keys": keys, "players": players}
        out[season] = sdata
    return out


CSS = """
:root{--bg:#fcfcfb;--card:#fff;--ink:#0b0b0b;--ink2:#33322f;--mut:#6f6e69;--line:#ecebe6;--line2:#e6e5e0;--accent:#2a78d6;--sub:#f7f6f2;--hover:#f4f3ef}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#1a1a19;--card:#222220;--ink:#f0efec;--ink2:#d6d5cf;--mut:#a8a79f;--line:#2e2e2b;--line2:#33332f;--sub:#20201e;--hover:#242422}}
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink);max-width:1240px;margin:24px auto;padding:0 16px;line-height:1.45}
h1{font-size:22px;margin:0 0 6px} .lead{font-size:15px;color:var(--ink2);margin:0 0 14px;max-width:900px}
.tabs{display:flex;gap:6px;margin:10px 0 12px} .tab{font-size:14px;padding:7px 14px;border:1px solid var(--line2);border-radius:8px;background:var(--card);cursor:pointer;color:var(--ink2)}
.tab.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.bar{display:flex;gap:14px;align-items:center;margin:8px 0 10px;font-size:13.5px;flex-wrap:wrap;background:var(--card);border:1px solid var(--line2);border-radius:10px;padding:10px 12px}
select,input{font-size:13.5px;padding:5px 7px;border:1px solid var(--line2);border-radius:6px;background:var(--card);color:var(--ink)}
.sortbtn{font-size:13px;padding:4px 10px;border:1px solid var(--line2);border-radius:6px;background:var(--card);cursor:pointer;color:var(--accent)}
.wrap{overflow-x:auto} table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th{color:var(--ink2);font-weight:600;cursor:pointer;background:var(--bg);font-size:12.5px} th small{display:block;font-weight:400;color:var(--mut)}
th.on,th.on small{color:var(--accent)} td.l,th.l{text-align:left} .mut{color:var(--mut);font-size:12px}
.up::before{content:"▲ ";color:#2a78d6} .dn::before{content:"▼ ";color:#eb6834} td.big{font-weight:700;font-size:14.5px}
tr.p{cursor:pointer} tr.p:hover{background:var(--hover)} tr.p td:first-child::before{content:"▸";display:inline-block;width:14px;color:var(--mut)} tr.p.open td:first-child::before{content:"▾"}
tr.d>td{background:var(--sub);font-size:12.5px;text-align:left;line-height:1.7;padding:10px 14px} .grp{border-left:2px solid var(--line2)}
.mate{margin:4px 0 12px;padding:8px 12px;border:1px solid var(--line2);border-radius:8px;background:var(--card);max-width:720px} .mate .ln{margin:2px 0}
.games td,.games th{padding:3px 10px;font-size:12.5px;background:none;cursor:default}
.gl span{display:inline-block;margin:0 10px 2px 0;white-space:nowrap} .gl span.o{font-weight:700}
#more,#bmore{margin:10px 0;font-size:13.5px} footer{margin:26px 0 10px;font-size:12.5px;color:var(--mut);max-width:900px}
"""

JS = r"""
const f=v=>v==null?"–":v.toFixed(1), sg=v=>v==null?"–":(v>0?"+":"")+v.toFixed(1), cl=v=>v==null?"":v>=0.05?"up":v<=-0.05?"dn":"";
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null, POS={G:"Guard",F:"Forward",C:"Center"}, $=id=>document.getElementById(id);
const R=[];
for(const [season,teams] of Object.entries(D)) for(const [team,T] of Object.entries(teams)){
 for(const [pk,P] of Object.entries(T.players)){
  const E=P.e||[], mates=[];
  for(const [kk,K] of Object.entries(T.keys)){
   if(pk===kk) continue;
   const sat=new Set(K.sat), on=new Set(K.on), og=[], ng=[];
   T.dates.forEach((d,i)=>{ if(P.m[i]==null||!on.has(i)) return; (sat.has(i)?og:ng).push(i); });
   if(!og.length||!ng.length) continue;
   const eo=og.map(i=>E[i]).filter(x=>x!=null), en=ng.map(i=>E[i]).filter(x=>x!=null), oe=og.filter(i=>E[i]!=null);
   const m={name:K.name,role:K.role,pos:K.pos,mpg:K.mpg,on:og.length,nn:ng.length,sat,og,ng,
     ao:mean(og.map(i=>P.m[i])),an:mean(ng.map(i=>P.m[i])),eo:eo.length?mean(eo):null,en:en.length?mean(en):null,neo:eo.length,nen:en.length,
     ea:oe.length?mean(oe.map(i=>P.m[i]-E[i])):null,nea:oe.length};
   m.ad=m.ao-m.an; m.ed=(m.eo!=null&&m.en!=null)?m.eo-m.en:null; mates.push(m);
  }
  if(!mates.length) continue;
  const games=T.dates.map((d,i)=>P.m[i]==null?null:{d,i,m:P.m[i],e:E[i]??null,out:mates.filter(x=>x.sat.has(i)).map(x=>x.name)}).filter(Boolean);
  R.push({season,team,player:P.name,pos:P.pos,mpg:P.mpg,gp:games.length,mates,games});
 }}
function fillTeams(sel,season,blank){const cur=$(sel).value, ts=[...new Set(R.filter(r=>r.season===season).map(r=>r.team))].sort();
 $(sel).innerHTML=`<option value="">${blank}</option>`+ts.map(t=>`<option${t===cur?" selected":""}>${t}</option>`).join("");}
// ---- tab 1: by team
let key="best",dir=-1,limit=100;
function draw(){
 const se=$("season").value,t=$("team").value,q=$("q").value.toLowerCase(),mq=$("mq").value.toLowerCase(),mo=+$("minout").value,ex=se==="2026-27";
 if(!t&&!q&&!mq){ $("tb").innerHTML=`<tr><td colspan="6" class="l" style="padding:22px 10px;color:var(--mut)">Pick a team, or type a player or a teammate, to see players.</td></tr>`; $("more").innerHTML=""; return; }
 const rs=[];
 for(const r of R){
  if(r.season!==se||(t&&r.team!==t)||(q&&!r.player.toLowerCase().includes(q))) continue;
  const ms=r.mates.filter(m=>m.on>=mo&&m.nn>=mo&&(!mq||m.name.toLowerCase().includes(mq))).sort((a,b)=>b.ad-a.ad);
  if(ms.length) rs.push({...r,ms,best:ms[0].ad,bestm:ms[0]});
 }
 rs.sort((a,b)=>{const x=a[key],y=b[key]; return (typeof x==="string"?x.localeCompare(y):x-y)*dir;});
 $("tb").innerHTML=rs.slice(0,limit).map((r,i)=>`<tr class="p" data-i="${i}"><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team} · ${POS[r.pos]||r.pos}</span></td>
  <td>${r.mpg}</td><td>${r.gp}</td><td class="l">${esc(r.bestm.name)} <span class="mut">${r.bestm.role}, out ${r.bestm.on} game${r.bestm.on>1?"s":""}</span></td>
  <td class="big ${cl(r.best)}">${sg(r.best)}</td><td>${r.ms.length}</td></tr>
  <tr class="d" id="d${i}" hidden><td colspan="6">
  ${r.ms.map(m=>`<div class="mate"><b>${esc(m.name)}</b> <span class="mut">${m.role} · ${POS[m.pos]||m.pos} · ${m.mpg} min a game</span>
   <div class="ln">Minutes when ${esc(m.name)} was healthy: <b>${f(m.an)}</b> <span class="mut">(${m.nn} games)</span></div>
   <div class="ln">Minutes played when ${esc(m.name)} was out: <b>${f(m.ao)}</b> <span class="mut">(${m.on} games)</span> &nbsp;<span class="${cl(m.ad)}"><b>${sg(m.ad)}</b></span></div>
   ${ex?`<div class="ln">Expected minutes when ${esc(m.name)} was healthy: <b>${f(m.en)}</b> <span class="mut">${m.en!=null?"("+m.nen+" games)":"(not saved)"}</span></div>
   <div class="ln">Expected minutes when ${esc(m.name)} was out: <b>${f(m.eo)}</b> <span class="mut">${m.eo!=null?"("+m.neo+" games)":"(not saved)"}</span>${m.ed!=null?` &nbsp;<span class="${cl(m.ed)}"><b>${sg(m.ed)}</b></span>`:""}</div>`:""}</div>`).join("")}
  <b>Every game</b>
  <table class="games"><tr><th class="l">Date</th><th>Minutes played</th>${ex?"<th>Expected minutes</th>":""}<th class="l">Key teammates out</th></tr>
   ${r.games.map(g=>`<tr><td class="l">${g.d}</td><td>${g.m}</td>${ex?`<td>${g.e??"–"}</td>`:""}<td class="l">${g.out.length?"<b>"+esc(g.out.join(", "))+"</b>":'<span class="mut">none</span>'}</td></tr>`).join("")}</table>
  </td></tr>`).join("");
 $("more").innerHTML=rs.length>limit?`Showing ${limit} of ${rs.length} players. <a href="#" id="all">Show all</a>`:`${rs.length} players`;
 if($("all")) $("all").onclick=e=>{e.preventDefault();limit=1e9;draw();};
 document.querySelectorAll("#tb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("d"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll("#head th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k; dir=(key===k)?-dir:(k==="player"?1:-1); key=k; draw();});
$("season").onchange=()=>{fillTeams("team",$("season").value,"Pick a team");limit=100;draw();};
["team","minout"].forEach(id=>$(id).onchange=()=>{limit=100;draw();}); ["q","mq"].forEach(id=>$(id).oninput=()=>{limit=100;draw();});
// ---- tab 2: biggest differences (teammates out in exactly the same games share a row)
const PAIRS=[]; R.forEach(r=>{const seen={}; r.mates.forEach(m=>{const k=m.og.join(",")+"|"+m.ng.join(",");
 if(seen[k]){ seen[k].m.name+=", "+m.name; if(!seen[k].m.role.includes(m.role)) seen[k].m.role+=" / "+m.role; return; }
 const x={r,m:{...m}}; seen[k]=x; PAIRS.push(x);});});
let bkey="ad",bdir=-1,blim=100;
const gm=(r,j)=>r.games.find(g=>g.i===j);
function bdraw(){
 const se=$("bseason").value,t=$("bteam").value,mo=+$("bmin").value,ro=$("brole").value,ex=se==="2026-27";
 document.querySelectorAll(".bexp").forEach(x=>x.style.display=ex?"":"none");
 const val=x=>x.m[bkey];
 const rs=PAIRS.filter(x=>x.r.season===se&&(!t||x.r.team===t)&&(!ro||x.m.role.includes(ro))&&x.m.on>=mo&&x.m.nn>=mo&&val(x)!=null).sort((a,b)=>(val(a)-val(b))*bdir);
 if(bkey==="ea"){ const keep={}; rs.forEach(x=>{const k=x.r.season+x.r.team+x.r.player, o=keep[k]; if(!o||x.m.nea>o.m.nea||(x.m.nea===o.m.nea&&x.m.on>o.m.on)) keep[k]=x;});
  const ok=new Set(Object.values(keep)); for(let i=rs.length-1;i>=0;i--) if(!ok.has(rs[i])) rs.splice(i,1); }
 document.querySelectorAll("#bhead th[data-k]").forEach(th=>th.classList.toggle("on",th.dataset.k===bkey));
 const were=m=>m.name.includes(",")?"were":"was";
 $("btb").innerHTML=rs.slice(0,blim).map(({r,m},i)=>`<tr class="p" data-i="${i}"><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team} · ${POS[r.pos]||r.pos}</span></td>
  <td class="l">${esc(m.name)} <span class="mut">${m.role}, out ${m.on}</span></td>
  <td class="grp">${f(m.an)}</td><td>${f(m.ao)}</td><td class="big ${cl(m.ad)}">${sg(m.ad)}</td>
  <td class="grp bexp">${f(m.eo)}</td><td class="bexp big ${cl(m.ea)}">${sg(m.ea)}<br><span class="mut">${m.nea?m.nea+(m.nea>1?" games":" game"):""}</span></td>
  <td class="grp bexp">${f(m.en)}</td><td class="bexp">${f(m.eo)}</td><td class="bexp big ${cl(m.ed)}">${sg(m.ed)}</td></tr>
  <tr class="d" id="b${i}" hidden><td colspan="10"><b>Games ${esc(m.name)} ${were(m)} out</b> <span class="mut">(date: ${esc(r.player)}'s minutes played${ex?", expected":""})</span>
  <div class="gl">${m.og.map(j=>{const g=gm(r,j); return `<span class="o">${g.d}: ${g.m}${ex&&g.e!=null?" (exp "+g.e+")":""}</span>`}).join("")}</div>
  <b>Games ${esc(m.name)} ${were(m)} healthy</b><div class="gl">${m.ng.map(j=>{const g=gm(r,j); return `<span>${g.d}: ${g.m}${ex&&g.e!=null?" (exp "+g.e+")":""}</span>`}).join("")}</div></td></tr>`).join("");
 $("bmore").innerHTML=rs.length>blim?`Showing ${blim} of ${rs.length}. <a href="#" id="ball">Show all</a>`:`${rs.length} rows`;
 if($("ball")) $("ball").onclick=e=>{e.preventDefault();blim=1e9;bdraw();};
 document.querySelectorAll("#btb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("b"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll("#bhead th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k; bdir=(bkey===k)?-bdir:-1; bkey=k; bdraw();});
document.querySelectorAll(".sortbtn").forEach(b=>b.onclick=()=>{bkey=b.dataset.k; bdir=-1; bdraw();});
$("bseason").onchange=()=>{fillTeams("bteam",$("bseason").value,"All teams");blim=100;bdraw();}; ["bteam","bmin","brole"].forEach(id=>$(id).onchange=()=>{blim=100;bdraw();});
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===b));
 $("view1").hidden=b.dataset.v!=="1"; $("view2").hidden=b.dataset.v!=="2";});
fillTeams("team","2026-27","Pick a team"); fillTeams("bteam","2026-27","All teams"); draw(); bdraw();
"""

SEASON_OPTS = '<option>2024-25</option><option>2025-26</option><option value="2026-27" selected>2026-27 (so far)</option>'


def page(D, through):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minutes When Teammates Sit</title><style>{CSS}</style></head><body>
<h1>Minutes when a starter or key bench player is out</h1>
<p class="lead">Pick a team (or type a name). Click a player to see his minutes when each key teammate was healthy and when he was out,
and every game. Key teammate = a starter or a bench player who plays 20+ minutes a game. Games through {through}.</p>
<div class="tabs"><button class="tab on" data-v="1">By team</button><button class="tab" data-v="2">Biggest differences</button></div>
<div id="view1">
<div class="bar">
<label>Season <select id="season">{SEASON_OPTS}</select></label>
<label><b>Team</b> <select id="team"></select></label>
<label>Player <input id="q" placeholder="type a name" size="12"></label>
<label>Teammate who was out <input id="mq" placeholder="e.g. Curry" size="12"></label>
<label>At least <select id="minout"><option selected>1</option><option>3</option><option>5</option><option>10</option></select> games healthy and out</label>
</div>
<div class="wrap"><table><thead id="head"><tr>
<th class="l" data-k="player">Player</th><th data-k="mpg">Minutes<small>a game</small></th><th data-k="gp">Games<small>played</small></th>
<th class="l">Biggest boost<small>teammate who was out</small></th><th data-k="best">Extra minutes<small>when he was out</small></th><th>Key teammates<small>who missed games</small></th>
</tr></thead><tbody id="tb"></tbody></table></div>
<div id="more"></div>
</div>
<div id="view2" hidden>
<p class="lead">Every player paired with a key teammate who was out, ranked by the biggest gaps. Click a row for the games.</p>
<div class="bar">
<label>Season <select id="bseason">{SEASON_OPTS}</select></label>
<label>Team <select id="bteam"></select></label>
<label>Teammate type <select id="brole"><option value="">Starters and key bench</option><option value="starter">Starters only</option><option value="key bench">Key bench only</option></select></label>
<label>At least <select id="bmin"><option selected>1</option><option>2</option><option>3</option><option>5</option><option>10</option></select> games healthy and out</label>
</div>
<div class="bar">Rank by:
<button class="sortbtn" data-k="ad">Minutes played: teammate out vs healthy</button>
<button class="sortbtn bexp" data-k="ea">Minutes played vs expected, when teammate out</button>
<button class="sortbtn bexp" data-k="ed">Expected minutes: teammate out vs healthy</button>
<span class="mut">Click a blue column title again to flip it. For "played vs expected" each player is listed once.</span></div>
<div class="wrap"><table><thead id="bhead"><tr>
<th class="l">Player</th><th class="l">Key teammate(s) who were out</th>
<th class="grp">Minutes played<small>teammate healthy</small></th><th>Minutes played<small>teammate out</small></th><th data-k="ad">Difference<small>out vs healthy</small></th>
<th class="grp bexp">Expected<small>teammate out</small></th><th class="bexp" data-k="ea">Played vs expected<small>when teammate out</small></th>
<th class="grp bexp">Expected<small>teammate healthy</small></th><th class="bexp">Expected<small>teammate out</small></th><th class="bexp" data-k="ed">Expected difference<small>out vs healthy</small></th>
</tr></thead><tbody id="btb"></tbody></table></div>
<div id="bmore"></div>
</div>
<footer>Minutes played: ESPN box scores (regular season; a coach's-decision DNP counts as 0). Starters: on this season's depth chart or
started at least half their games. Expected minutes (2026-27 only, from Oct 27): the number the trader bot's
report showed (FantasyPros top 10, else RotoWire for away teams, else SportsLine), or its last read before tip; a player the site dropped
before tip has none. A traded player shows under each team. Small samples swing a lot.</footer>
<script>const D={json.dumps(D, separators=(",", ":"))};
{JS}</script></body></html>"""


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "minutes_when_out.html")
    D = build_data()
    through = max((r["date"] for r in csv.DictReader(open(os.path.join(HERE, "data", "box_2026-27.csv")))), default="")
    open(out, "w").write(page(D, through))
    print(out, {s: len(t) for s, t in D.items()})
