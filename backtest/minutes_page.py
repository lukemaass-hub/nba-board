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
MAX_OUT = 3           # a team-game with more than this many key teammates out is left out (unusual nights, user Nov 16 2026)
SHOW_CHANGE = 4       # a difference smaller than this shows as "no change" (user, Nov 16 2026)


def left_injured(games, team_dates):
    """Dates of games a player left hurt (user, Nov 16 2026: Curry played 6 minutes on Nov 11 and then sat): he played
    under half his average of the games before (3+ of them) and was not available for his team's next game."""
    out, seen = set(), []
    for d in sorted(games):
        v = games[d]
        if v > 0 and len(seen) >= 3 and v < 0.5 * st.mean(seen):
            nxt = next((x for x in team_dates if x > d), None)
            if nxt and nxt not in games:
                out.add(d)
                continue
        if v > 0:
            seen.append(v)
    return out


LINES = {}   # optional {"YYYY-MM-DD|normname": our prematch points line}; --lines FILE (internal data: never commit it)


def points_by_game():
    """(date, ESPN player id) -> points scored, this season (backtest/fetch_points.py)."""
    path = os.path.join(HERE, "data", "points_2026-27.csv")
    if not os.path.exists(path):
        return {}
    return {(r["date"], r["player_id"]): int(r["points"]) for r in csv.DictReader(open(path, newline=""))}


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
    pts = points_by_game()
    out = {}
    for season, need in SEASONS.items():
        path = os.path.join(HERE, "data", f"box_{season}.csv")
        if not os.path.exists(path):
            continue
        team_dates, mins, played, starts = defaultdict(set), defaultdict(dict), defaultdict(dict), defaultdict(int)
        info, teams_of, coach_dnp = {}, defaultdict(set), defaultdict(int)
        for r in csv.DictReader(open(path, newline="")):
            t, k = MAP.get(r["team"], r["team"]), r["player_id"]
            team_dates[t].add(r["date"])
            info[(t, k)] = {"name": r["player"], "pos": (r["position"] or "?")[0].replace("P", "G").replace("S", "F")}
            if int(r["played"]):
                mins[(t, k)][r["date"]] = float(r["minutes"])
            elif "COACH" in (r.get("dnp_reason") or "").upper():
                mins[(t, k)][r["date"]] = 0.0          # benched by the coach = 0 minutes
                coach_dnp[(t, k)] += 1
            # any other DNP (injury, illness, rest...) = he wasn't available: left out (user, Nov 16 2026)
            teams_of[k].add(t)
            if int(r["played"]):
                played[(t, k)][r["date"]] = float(r["minutes"])
                starts[(t, k)] += int(r["starter"])
        for key, m in mins.items():          # 0s before his first real game: he was likely hurt too, not benched
            first = min((d for d, v in m.items() if v > 0), default=None)
            for d in [d for d, v in m.items() if v == 0 and (first is None or d < first)]:
                del m[d]
        for (t, k), m in mins.items():
            for d in left_injured(m, sorted(team_dates[t])):
                m.pop(d, None); played[(t, k)].pop(d, None)
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
                listed = len(played[(t, k)]) + coach_dnp[(t, k)]
                if not role or coach_dnp[(t, k)] > 0.25 * listed:     # in and out of the rotation (Danny Wolf): not key
                    continue
                ds = sorted(mins[(t, k)])
                lo, hi = (dates[0], dates[-1]) if len(teams_of[k]) == 1 else (ds[0], ds[-1])   # traded: only his stint
                keys[k] = {"name": info[(t, k)]["name"], "role": role, "pos": info[(t, k)]["pos"], "mpg": round(mpg[k], 1),
                           "sat": [i for i, d in enumerate(dates) if lo <= d <= hi and d not in played[(t, k)]],
                           "on": [i for i, d in enumerate(dates) if lo <= d <= hi]}
            out_count = defaultdict(int)
            for v in keys.values():
                for i in v["sat"]:
                    out_count[i] += 1
            skip = {i for i, n in out_count.items() if n > MAX_OUT}
            for v in keys.values():
                v["sat"] = [i for i in v["sat"] if i not in skip]
                v["on"] = [i for i in v["on"] if i not in skip]
            players = {}
            for k in ks:
                p = {"name": info[(t, k)]["name"], "pos": info[(t, k)]["pos"], "mpg": round(mpg[k], 1),
                     "m": [None if mins[(t, k)].get(d) is None or i in skip else round(mins[(t, k)][d]) for i, d in enumerate(dates)]}
                if season == "2026-27":
                    p["e"] = [exp.get((d, t, norm_name(info[(t, k)]["name"]))) for d in dates]
                    p["p"] = [pts.get((d, k)) for d in dates]
                    if LINES:
                        p["l"] = [LINES.get(f"{d}|{norm_name(info[(t, k)]['name'])}") for d in dates]
                players[k] = p
            sdata[t] = {"dates": [d[5:] for d in dates], "keys": keys, "players": players,
                        "skipped": [dates[i][5:] for i in sorted(skip)]}
        out[season] = sdata
    return out


def season_changes(days=7):
    """This season only (user, Nov 16 2026): each player's minutes a game over the last `days` days vs his average
    before that, 4+ minutes apart (2+ games this week, 3+ before), with a short reason: key teammates out or back,
    his own injury, or a rotation change (starting / bench / coach's DNPs). A coach's DNP is 0; injured DNPs, 0s before
    his first real game, and games he left hurt (left_injured) don't count."""
    import datetime as dt
    m, team, meta, starts, coach = defaultdict(dict), {}, {}, defaultdict(dict), defaultdict(set)
    team_dates = defaultdict(set)
    exp = expected_by_game()
    pts = points_by_game()
    for r in csv.DictReader(open(os.path.join(HERE, "data", "box_2026-27.csv"), newline="")):
        k, tm = r["player_id"], MAP.get(r["team"], r["team"])
        team_dates[tm].add(r["date"])
        if int(r["played"]):
            m[k][r["date"]] = float(r["minutes"])
        elif "COACH" in (r.get("dnp_reason") or "").upper():
            m[k][r["date"]] = 0.0
            coach[k].add(r["date"])
        else:
            continue
        team[k] = (tm, r["player"])
        starts[k][r["date"]] = int(r["starter"])
        meta[(k, r["date"])] = ("@" if r["home"] == "0" else "vs") + " " + MAP.get(r["opponent"], r["opponent"])
    if not m:
        return {"from": "", "to": "", "rows": []}
    last_day = max(d for v in m.values() for d in v)
    start = (dt.date.fromisoformat(last_day) - dt.timedelta(days=days - 1)).isoformat()
    hurt, clean = {}, {}
    for k, games in m.items():
        first = min((d for d, v in games.items() if v > 0), default=None)
        if first is None:
            continue
        g = {d: v for d, v in games.items() if d >= first}
        hurt[k] = left_injured(g, sorted(team_dates[team[k][0]]))
        clean[k] = {d: v for d, v in g.items() if d not in hurt[k]}
    # key teammates (same rule as the rest of the page): start half his games or 20+ MPG, rarely benched by the coach
    keys = defaultdict(list)
    for k, g in clean.items():
        pl = [v for v in g.values() if v > 0]
        if len(pl) >= 2 and len(coach[k]) <= 0.25 * len(g):
            if sum(starts[k].get(d, 0) for d in g) >= 0.5 * len(pl) or st.mean(pl) >= 20:
                keys[team[k][0]].append(k)
    out = []
    for k, g in clean.items():
        week = {d: v for d, v in g.items() if d >= start}
        before = {d: v for d, v in g.items() if d < start}
        if len(week) < 2 or len(before) < 3:
            continue
        a, b = st.mean(week.values()), st.mean(before.values())
        if abs(a - b) < SHOW_CHANGE:
            continue
        tm, why, kind = team[k][0], [], ""
        for o in keys[tm]:
            if o == k:
                continue
            ow = sum(1 for d in week if d not in m[o] or d in hurt.get(o, ()))
            ob = sum(1 for d in before if d not in m[o] or d in hurt.get(o, ()))
            name = team[o][1]
            if a > b and ow >= 0.5 * len(week) and ob < 0.5 * len(before):
                why.append(f"{name} out ({ow} of {len(week)} games)"); kind = kind or "Teammate injuries"
            if a < b and ob >= 0.5 * len(before) and ow < 0.5 * len(week):
                why.append(f"{name} back"); kind = kind or "Teammates back"
        missed_before = [d for d in sorted(team_dates[tm]) if d < start and d not in g][-3:]
        if a > b and len(missed_before) >= 2 and (dt.date.fromisoformat(start) - dt.date.fromisoformat(missed_before[-1])).days <= 10:
            why.append(f"back from his own injury (missed {len(missed_before)}+ games)"); kind = kind or "Back from injury"
        sw = sum(starts[k].get(d, 0) for d in week) / len(week)
        sb = sum(starts[k].get(d, 0) for d in before) / len(before)
        if sw >= 0.5 > sb:
            why.append("moved into the starting lineup"); kind = kind or "Rotation change"
        if sb >= 0.5 > sw:
            why.append("moved to the bench"); kind = kind or "Rotation change"
        cw = len([d for d in week if d in coach[k]])
        if cw:
            why.append(f"benched by the coach in {cw} game{'s' if cw > 1 else ''}"); kind = kind or "Rotation change"
        hw = [d for d in hurt[k] if d >= start]
        if hw:
            why.append("left the " + ", ".join(d[5:] for d in hw) + " game hurt (not counted)")
        if not kind:
            kind, why = "Rotation change", why or ["no injuries involved"]
        log = [[d[5:], meta[(k, d)], round(v), starts[k].get(d, 0), int(d >= start), exp.get((d, tm, norm_name(team[k][1]))),
                int(d in hurt[k]), LINES.get(f"{d}|{norm_name(team[k][1])}"), pts.get((d, k))] for d, v in sorted(g.items(), reverse=True)]
        out.append({"team": tm, "player": team[k][1], "now": round(a, 1), "gp": len(week), "last": round(b, 1),
                    "lgp": len(before), "d": round(a - b, 1), "kind": kind, "why": "; ".join(why), "log": log})
    return {"from": start, "to": last_day, "rows": sorted(out, key=lambda x: -abs(x["d"]))}


CSS = """small.lines{display:block;font-weight:400;color:var(--mut,#777);font-size:11.5px;margin-top:2px}

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
#bmore{margin:10px 0;font-size:13.5px} .empty{padding:22px 10px!important;color:var(--mut)}
.chg{font-weight:700;margin-left:6px} .sub{width:auto;margin:2px 0 8px} .sub th,.sub td{padding:4px 12px;cursor:default;background:none}
details summary{cursor:pointer;color:var(--accent);margin:4px 0} .rank{display:flex;gap:6px;align-items:center;margin-left:auto}
.sortbtn.on{background:var(--accent);color:#fff;border-color:var(--accent)} tr.wk td{font-weight:600} .why{margin:2px 0 8px;font-size:13.5px} td:not(.l),th:not(.l){white-space:nowrap} footer{margin:26px 0 10px;font-size:12.5px;color:var(--mut);max-width:900px}
"""

PTS_SIG = 4        # points tab: 4+ points a game apart counts as a real difference (user, Nov 18 2026)
OVER_SIG = 0.30    # ...or going over our line 30+ percentage points more / less often
MIN_GAMES = 2      # every number on the page needs at least this many games behind it (user, Nov 16 2026)

JS = r"""
const MIN=__MIN__;
const SHOW=__SHOW__;          // smaller differences show as "no change"
const f=v=>v==null?"–":v.toFixed(1), cl=v=>v==null?"":v>=SHOW?"up":v<=-SHOW?"dn":"";
const sg=v=>v==null?"–":Math.abs(v)<SHOW?'<span class="mut">no change</span>':(v>0?"+":"")+v.toFixed(1);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const mean=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:null, POS={G:"G",F:"F",C:"C"}, $=id=>document.getElementById(id);
const avg2=a=>a.length>=MIN?mean(a):null;          // fewer than MIN games: no number
const R=[];
for(const [season,teams] of Object.entries(D)) for(const [team,T] of Object.entries(teams)){
 for(const [pk,P] of Object.entries(T.players)){
  const E=P.e||[], Ln=P.l||[], Pt=P.p||[], groups={};
  for(const [kk,K] of Object.entries(T.keys)){
   if(pk===kk) continue;
   const sat=new Set(K.sat), on=new Set(K.on), og=[], ng=[];
   T.dates.forEach((d,i)=>{ if(P.m[i]==null||!on.has(i)) return; (sat.has(i)?og:ng).push(i); });
   if(og.length<MIN||ng.length<MIN) continue;
   const k=og.join(",")+"|"+ng.join(",");          // teammates out in exactly the same games: one row
   if(groups[k]){ groups[k].names.push(K.name); continue; }
   const eo=og.map(i=>E[i]).filter(x=>x!=null), en=ng.map(i=>E[i]).filter(x=>x!=null), oe=og.filter(i=>E[i]!=null);
   const m={names:[K.name],role:K.role,on:og.length,nn:ng.length,sat,og,ng,
     ao:mean(og.map(i=>P.m[i])),an:mean(ng.map(i=>P.m[i])),eo:avg2(eo),en:avg2(en),neo:eo.length,nen:en.length,
     ea:oe.length>=MIN?mean(oe.map(i=>P.m[i]-E[i])):null,nea:oe.length,
     lo:avg2(og.map(i=>Ln[i]).filter(x=>x!=null)),ln:avg2(ng.map(i=>Ln[i]).filter(x=>x!=null)),
     lso:og.map(i=>Ln[i]).filter(x=>x!=null),lsn:ng.map(i=>Ln[i]).filter(x=>x!=null)};
   m.ld=(m.lo!=null&&m.ln!=null)?m.lo-m.ln:null;
   { const po=og.map(i=>Pt[i]).filter(x=>x!=null), pn=ng.map(i=>Pt[i]).filter(x=>x!=null);
     m.pto=avg2(po); m.ptn=avg2(pn); m.ptd=(m.pto!=null&&m.ptn!=null)?m.pto-m.ptn:null;
     const wo=og.filter(i=>Ln[i]!=null&&Pt[i]!=null), wn=ng.filter(i=>Ln[i]!=null&&Pt[i]!=null);
     m.ovo=wo.filter(i=>Pt[i]>Ln[i]).length; m.novo=wo.length; m.ovn=wn.filter(i=>Pt[i]>Ln[i]).length; m.novn=wn.length;
     m.ovd=(wo.length>=MIN&&wn.length>=MIN)?m.ovo/wo.length-m.ovn/wn.length:null; }
   m.ad=m.ao-m.an; m.ed=(m.eo!=null&&m.en!=null)?m.eo-m.en:null; groups[k]=m;
  }
  const mates=Object.values(groups); mates.forEach(m=>m.name=m.names.join(", "));
  if(!mates.length) continue;
  const games=T.dates.map((d,i)=>P.m[i]==null?null:{d,i,m:P.m[i],e:E[i]??null,l:Ln[i]??null,p:Pt[i]??null,out:mates.filter(x=>x.sat.has(i)).flatMap(x=>x.names)}).filter(Boolean);
  R.push({season,team,player:P.name,pos:P.pos,mpg:P.mpg,gp:games.length,mates:mates.sort((a,b)=>b.ad-a.ad),games});
 }}
function fillTeams(sel,season,blank){const cur=$(sel).value, ts=[...new Set(R.filter(r=>r.season===season).map(r=>r.team))].sort();
 $(sel).innerHTML=`<option value="">${blank}</option>`+ts.map(t=>`<option${t===cur?" selected":""}>${t}</option>`).join("");}
const pair=(a,b,d)=>`${f(a)} → ${f(b)} <span class="${cl(d)} chg">${sg(d)}</span>`;
const HASL=typeof LINES_ON!=="undefined"&&LINES_ON, lpair=(a,b,d)=>`${f(a)} → ${f(b)} ${d==null?"":Math.abs(d)<1?'<span class="mut">no change</span>':`<span class="${d>0?"up":"dn"} chg">${d>0?"+":""}${d.toFixed(1)}</span>`}`;
const gamesTable=(r,ex)=>`<table class="games"><tr><th class="l">Date</th><th>Played</th>${ex?"<th>Expected</th>":""}${ex&&HASL?"<th>Our points line<small>that game</small></th>":""}${ex?"<th>Points</th>":""}<th class="l">Key teammates out</th></tr>
 ${r.games.map(g=>`<tr><td class="l">${g.d}</td><td>${g.m}</td>${ex?`<td>${g.e??"–"}</td>`:""}${ex&&HASL?`<td>${g.l??"–"}</td>`:""}${ex?`<td>${g.p??"–"}</td>`:""}<td class="l">${g.out.length?esc(g.out.join(", ")):'<span class="mut">none</span>'}</td></tr>`).join("")}</table>`;
// ---- tab 1: by team
let key="best",dir=-1;
function draw(){
 const se=$("season").value,t=$("team").value,q=$("q").value.toLowerCase(),ex=se==="2026-27";
 if(!t&&!q){ $("tb").innerHTML=`<tr><td colspan="4" class="l empty">Pick a team or type a player.</td></tr>`; return; }
 const rs=R.filter(r=>r.season===se&&(!t||r.team===t)&&(!q||r.player.toLowerCase().includes(q))).map(r=>({...r,best:r.mates[0].ad}));
 rs.sort((a,b)=>{const x=a[key],y=b[key]; return (typeof x==="string"?x.localeCompare(y):x-y)*dir;});
 $("tb").innerHTML=rs.length?rs.map((r,i)=>`<tr class="p" data-i="${i}"><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team} · ${POS[r.pos]||r.pos}</span></td>
  <td>${r.mpg}</td><td class="l">${esc(r.mates[0].name)} out</td><td class="big ${cl(r.best)}">${sg(r.best)}</td></tr>
  <tr class="d" id="d${i}" hidden><td colspan="4">
  <table class="sub"><tr><th class="l">Player out</th><th>Games he missed</th><th>${esc(r.player)}'s minutes<small>he plays → he's out</small></th>${ex?"<th>His expected minutes<small>he plays → he's out</small></th>":""}${ex&&HASL?"<th>Our points line<small>average · he plays → he's out</small></th>":""}</tr>
  ${r.mates.map(m=>`<tr><td class="l">${esc(m.name)} out <span class="mut">${m.role}</span></td><td>${m.on}</td><td>${pair(m.an,m.ao,m.ad)}</td>${ex?`<td>${m.ed!=null?pair(m.en,m.eo,m.ed):'<span class="mut">not enough saved</span>'}</td>`:""}${ex&&HASL?`<td>${m.ld!=null?lpair(m.ln,m.lo,m.ld):'<span class="mut">not enough bets</span>'}</td>`:""}</tr>`).join("")}</table>
  <details><summary>Every game</summary>${gamesTable(r,ex)}</details></td></tr>`).join("")
  :`<tr><td colspan="4" class="l empty">No players with at least ${MIN} games each way.</td></tr>`;
 document.querySelectorAll("#tb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("d"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll("#head th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k; dir=(key===k)?-dir:(k==="player"?1:-1); key=k; draw();});
$("season").onchange=()=>{fillTeams("team",$("season").value,"Pick a team");draw();}; $("team").onchange=draw; $("q").oninput=draw;
// ---- tab 2: biggest differences
const PAIRS=[]; R.forEach(r=>r.mates.forEach(m=>PAIRS.push({r,m})));
let bkey="ad",blim=50;
function bdraw(){
 const se=$("bseason").value,t=$("bteam").value,ex=se==="2026-27";
 document.querySelectorAll(".bexp").forEach(x=>x.style.display=ex?"":"none");
 if(!ex&&bkey!=="ad") bkey="ad";
 document.querySelectorAll(".sortbtn").forEach(b=>b.classList.toggle("on",b.dataset.k===bkey));
 let rs=PAIRS.filter(x=>x.r.season===se&&(!t||x.r.team===t)&&x.m[bkey]!=null).sort((a,b)=>b.m[bkey]-a.m[bkey]);
 if(bkey==="ea"){ const seen=new Set(); rs=rs.filter(x=>{const k=x.r.season+x.r.team+x.r.player; if(seen.has(k)) return false; seen.add(k); return true;}); }
 $("btb").innerHTML=rs.slice(0,blim).map(({r,m},i)=>`<tr class="p" data-i="${i}"><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team}</span></td>
  <td class="l">${esc(m.name)} <span class="mut">out ${m.on}</span></td><td>${pair(m.an,m.ao,m.ad)}</td>
  <td class="bexp">${m.ed!=null?pair(m.en,m.eo,m.ed):"–"}</td><td class="bexp big ${cl(m.ea)}">${sg(m.ea)}<br><span class="mut">${m.nea>=MIN?m.nea+" games":""}</span></td></tr>
  <tr class="d" id="b${i}" hidden><td colspan="5">${gamesTable(r,ex)}</td></tr>`).join("")
  || `<tr><td colspan="5" class="l empty">Nothing with at least ${MIN} games each way.</td></tr>`;
 $("bmore").innerHTML=rs.length>blim?`Showing the top ${blim} of ${rs.length}. <a href="#" id="ball">Show all</a>`:"";
 if($("ball")) $("ball").onclick=e=>{e.preventDefault();blim=1e9;bdraw();};
 document.querySelectorAll("#btb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("b"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll(".sortbtn").forEach(b=>b.onclick=()=>{bkey=b.dataset.k; blim=50; bdraw();});
$("bseason").onchange=()=>{fillTeams("bteam",$("bseason").value,"All teams");blim=50;bdraw();}; $("bteam").onchange=()=>{blim=50;bdraw();};
// ---- tab 3: biggest misses (2026-27: games a key teammate was out, expected vs played)
const MISSES=[]; R.filter(r=>r.season==="2026-27").forEach(r=>r.games.forEach(g=>{ if(g.out.length&&g.e!=null&&g.m>0) MISSES.push({r,g,miss:g.m-g.e}); }));
let mdir="all",mlim=50;
function mdraw(){
 const t=$("mteam").value;
 document.querySelectorAll(".mbtn").forEach(b=>b.classList.toggle("on",b.dataset.k===mdir));
 const rs=MISSES.filter(x=>(!t||x.r.team===t)&&Math.abs(x.miss)>=SHOW&&(mdir==="all"||(mdir==="more"?x.miss>0:x.miss<0))).sort((a,b)=>Math.abs(b.miss)-Math.abs(a.miss));
 $("mtb").innerHTML=rs.slice(0,mlim).map(({r,g,miss})=>`<tr><td class="l">${g.d}</td><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team}</span></td>
  <td class="l">${esc(g.out.join(", "))}</td><td>${f(g.e)}</td><td>${f(g.m)}</td><td class="big ${cl(miss)}">${sg(miss)}</td></tr>`).join("")
  || `<tr><td colspan="6" class="l empty">No misses of ${SHOW}+ minutes.</td></tr>`;
 $("mmore").innerHTML=rs.length>mlim?`Showing the top ${mlim} of ${rs.length}. <a href="#" id="mall">Show all</a>`:"";
 if($("mall")) $("mall").onclick=e=>{e.preventDefault();mlim=1e9;mdraw();};
}
document.querySelectorAll(".mbtn").forEach(b=>b.onclick=()=>{mdir=b.dataset.k; mlim=50; mdraw();}); $("mteam").onchange=()=>{mlim=50;mdraw();};
// ---- tab 4: minutes changes vs last season (the weekly email's list)
let cdir="all";
function cdraw(){
 const t=$("cteam").value;
 document.querySelectorAll(".cbtn").forEach(b=>b.classList.toggle("on",b.dataset.k===cdir));
 const rs=CH.filter(x=>(!t||x.team===t)&&(cdir==="all"||(cdir==="up"?x.d>0:x.d<0)));
 $("ctb").innerHTML=rs.map((x,i)=>`<tr class="p" data-i="${i}"><td class="l"><b>${esc(x.player)}</b> <span class="mut">${x.team}</span></td><td>${f(x.last)} <span class="mut">(${x.lgp} g)</span></td>
  <td>${f(x.now)} <span class="mut">(${x.gp} g)</span></td><td class="big ${cl(x.d)}">${sg(x.d)}</td>
</tr>
  <tr class="d" id="c${i}" hidden><td colspan="4"><div class="why"><b>Why:</b> ${esc(x.kind)} · ${esc(x.why)}</div><table class="games"><tr><th class="l">Date</th><th class="l">Opponent</th><th>Minutes</th><th>Expected</th>${HASL?"<th>Our points line<small>that game</small></th>":""}<th>Points</th><th class="l"></th></tr>
  ${x.log.map(g=>`<tr${g[4]?' class="wk"':''}><td class="l">${g[0]}</td><td class="l">${g[1]}</td><td>${g[2]}</td><td>${g[5]??"–"}</td>${HASL?`<td>${g[7]??"–"}</td>`:""}<td>${g[8]??"–"}</td>
   <td class="l mut">${g[6]?"left hurt (not counted)":g[3]?"started":g[2]===0?"DNP (coach)":"bench"}${g[4]?" · last week":""}</td></tr>`).join("")}</table></td></tr>`).join("") || `<tr><td colspan="4" class="l empty">None.</td></tr>`;
 document.querySelectorAll("#ctb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("c"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll(".cbtn").forEach(b=>b.onclick=()=>{cdir=b.dataset.k; cdraw();}); $("cteam").onchange=cdraw;
// ---- tab 5: points (and how often he goes over our line) when a key teammate is out (user, Nov 18 2026)
const PTS_SIG=__PTS__, OVER_SIG=__OVER__, pc=v=>Math.round(v*100)+"%";
const PP=[]; R.filter(r=>r.season==="2026-27").forEach(r=>r.mates.forEach(m=>{ m.nmin=Math.min(m.on,m.nn);
  const sp=m.ptd!=null&&Math.abs(m.ptd)>=PTS_SIG, so=m.ovd!=null&&Math.abs(m.ovd)>=OVER_SIG;
  if((sp||so)&&(!HASL||m.ovd!=null)) PP.push({r,m,sp,so});}));   // with our lines: only players with enough bets (user)
let pkey="pts",plim=50;
function pdraw(){
 const t=$("pteam").value;
 document.querySelectorAll(".pbtn").forEach(b=>b.classList.toggle("on",b.dataset.k===pkey));
 const g3=$("p3").checked;
 const rs=PP.filter(x=>(!t||x.r.team===t)&&(pkey!=="over"||x.m.ovd!=null)&&(!g3||(pkey==="over"?Math.min(x.m.novo,x.m.novn)>=3:x.m.nmin>=3)))
   .sort((a,b)=>pkey==="over"?Math.abs(b.m.ovd)-Math.abs(a.m.ovd):Math.abs(b.m.ptd??0)-Math.abs(a.m.ptd??0));
 $("ptb").innerHTML=rs.slice(0,plim).map(({r,m},i)=>{
  const gs=r.games.filter(g=>m.sat.has(g.i)||m.ng.includes(g.i));
  return `<tr class="p" data-i="${i}"><td class="l"><b>${esc(r.player)}</b> <span class="mut">${r.team}</span></td><td class="l">${esc(m.name)} out <span class="mut">${m.on} g out</span></td>
  <td>${m.ptd!=null?lpair(m.ptn,m.pto,m.ptd):"–"}</td>
  ${HASL?`<td>${pc(m.ovn/m.novn)} → ${pc(m.ovo/m.novo)}</td>
  <td>${m.ld!=null?lpair(m.ln,m.lo,m.ld):"–"}</td>`:""}<td>${f(m.an)} → ${f(m.ao)}</td></tr>
  <tr class="d" id="p${i}" hidden><td colspan="${HASL?6:4}"><table class="games"><tr><th class="l">Date</th><th>Minutes</th>${HASL?"<th>Our points line</th>":""}<th>Points</th><th class="l">${esc(m.name)}</th><th class="l">Key teammates out</th></tr>
  ${gs.map(g=>`<tr><td class="l">${g.d}</td><td>${g.m}</td>${HASL?`<td>${g.l??"–"}</td>`:""}<td>${g.p??"–"}</td><td class="l">${m.sat.has(g.i)?"<b>out</b>":"played"}</td><td class="l">${g.out.length?esc(g.out.join(", ")):'<span class="mut">none</span>'}</td></tr>`).join("")}</table></td></tr>`;}).join("")
  || `<tr><td colspan="6" class="l empty">None.</td></tr>`;
 $("pmore").innerHTML=rs.length>plim?`Showing the top ${plim} of ${rs.length}. <a href="#" id="pall">Show all</a>`:"";
 if($("pall")) $("pall").onclick=e=>{e.preventDefault();plim=1e9;pdraw();};
 document.querySelectorAll("#ptb tr.p").forEach(tr=>tr.onclick=()=>{const d=$("p"+tr.dataset.i); d.hidden=!d.hidden; tr.classList.toggle("open",!d.hidden);});
}
document.querySelectorAll(".pbtn").forEach(b=>b.onclick=()=>{pkey=b.dataset.k; plim=50; pdraw();}); $("pteam").onchange=()=>{plim=50;pdraw();}; $("p3").onchange=()=>{plim=50;pdraw();};
if(!HASL) document.querySelectorAll(".pl").forEach(x=>x.style.display="none");
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",x===b));
 ["1","2","3","4","5"].forEach(v=>$("view"+v).hidden=b.dataset.v!==v);});
fillTeams("team","2026-27","Pick a team"); fillTeams("bteam","2026-27","All teams"); fillTeams("mteam","2026-27","All teams"); fillTeams("pteam","2026-27","All teams");
$("cteam").innerHTML='<option value="">All teams</option>'+[...new Set(CH.map(x=>x.team))].sort().map(t=>`<option>${t}</option>`).join("");
draw(); bdraw(); mdraw(); cdraw(); pdraw();
""".replace("__MIN__", str(MIN_GAMES)).replace("__PTS__", str(PTS_SIG)).replace("__OVER__", str(OVER_SIG)).replace("__SHOW__", str(SHOW_CHANGE))

SEASON_OPTS = '<option>2024-25</option><option>2025-26</option><option value="2026-27" selected>2026-27</option>'


def page(D, CH, through):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Minutes When Teammates Sit</title><style>{CSS}</style></head><body>
<h1>Minutes when a key teammate is out</h1>
<p class="lead">How many more (or fewer) minutes a player gets when one of his teammates, a starter or key bench player
(20+ minutes a game), misses the game. Example: "Corey Kispert · Kingston Flemings out · +13.4" means Kispert plays about 13
more minutes in games Flemings misses. Click a player to see every teammate.
Every number uses at least {MIN_GAMES} games. Games through {through}.</p>
<div class="tabs"><button class="tab on" data-v="1">By team</button><button class="tab" data-v="2">Biggest differences</button>
<button class="tab" data-v="3">Biggest misses</button><button class="tab" data-v="4">Minutes changes</button><button class="tab" data-v="5">Points when out</button></div>
<div id="view1">
<div class="bar"><select id="season">{SEASON_OPTS}</select><select id="team"></select><input id="q" placeholder="or type a player" size="16"></div>
<div class="wrap"><table><thead id="head"><tr>
<th class="l" data-k="player">Player</th><th data-k="mpg">Min/game</th><th class="l">Player out</th><th data-k="best">Change in minutes</th>
</tr></thead><tbody id="tb"></tbody></table></div>
</div>
<div id="view2" hidden>
<div class="bar"><select id="bseason">{SEASON_OPTS}</select><select id="bteam"></select>
<span class="rank">Rank by
<button class="sortbtn on" data-k="ad">Minutes gained</button>
<button class="sortbtn bexp" data-k="ea">Played above expected</button>
<button class="sortbtn bexp" data-k="ed">Expected gained</button></span></div>
<div class="wrap"><table><thead><tr>
<th class="l">Player</th><th class="l">Player(s) out</th><th>Player's minutes<small>he plays → he's out</small></th>
<th class="bexp">Player's expected minutes<small>he plays → he's out</small></th><th class="bexp">Played vs expected<small>with the teammate out</small></th>
</tr></thead><tbody id="btb"></tbody></table></div>
<div id="bmore"></div>
</div>
<div id="view3" hidden>
<p class="lead">2026-27 games where a key teammate was out: what the report expected vs what he played, biggest misses first
(at least {SHOW_CHANGE} minutes). Games he didn't play are left out (usually a late scratch).</p>
<div class="bar"><select id="mteam"></select><span class="rank">
<button class="mbtn sortbtn on" data-k="all">All</button><button class="mbtn sortbtn" data-k="more">Played more than expected</button>
<button class="mbtn sortbtn" data-k="less">Played less than expected</button></span></div>
<div class="wrap"><table><thead><tr><th class="l">Date</th><th class="l">Player</th><th class="l">Key teammate(s) out</th>
<th>Expected</th><th>Played</th><th>Miss<small>played − expected</small></th></tr></thead><tbody id="mtb"></tbody></table></div>
<div id="mmore" style="margin:10px 0;font-size:13.5px"></div>
</div>
<div id="view4" hidden>
<p class="lead">Minutes a game in the last week ({CH["from"][5:]} to {CH["to"][5:]}) vs the rest of this season before it,
{SHOW_CHANGE}+ minutes apart (2+ games this week, 3+ before). A coach's DNP counts as 0; games missed injured don't count.
Games he left hurt don't count. Click a player for why it changed and his game log (last week in bold).</p>
<div class="bar"><select id="cteam"></select><span class="rank">
<button class="cbtn sortbtn on" data-k="all">All</button><button class="cbtn sortbtn" data-k="up">More minutes</button>
<button class="cbtn sortbtn" data-k="down">Fewer minutes</button></span></div>
<div class="wrap"><table><thead><tr><th class="l">Player</th><th>Season before this week<small>min a game</small></th><th>Last week<small>min a game</small></th>
<th>Change</th></tr></thead><tbody id="ctb"></tbody></table></div>
</div>
<div id="view5" hidden>
<p class="lead">2026-27: players who score a lot more or less when a key teammate is out ({PTS_SIG}+ points a game apart)<span class="pl">,
or who go over our points line much more or less often than usual ({int(OVER_SIG*100)}+ percentage points apart; "over" = scored more than
our line that game)</span>. 2+ games each way, so small samples: check the games behind each row. Click a player for every game.</p>
<div class="bar"><select id="pteam"></select><label style="font-size:13.5px"><input type="checkbox" id="p3"> Only 3+ games each way</label><span class="rank">Rank by
<button class="pbtn sortbtn on" data-k="pts">Points difference</button><button class="pbtn sortbtn pl" data-k="over">Over-rate difference</button></span></div>
<div class="wrap"><table><thead><tr><th class="l">Player</th><th class="l">Player out</th><th>Points a game<small>he plays → he's out</small></th>
<th class="pl">Went over our line<small>he plays → he's out</small></th><th class="pl">Our points line<small>average · he plays → he's out</small></th>
<th>Minutes<small>he plays → he's out</small></th></tr></thead><tbody id="ptb"></tbody></table></div>
<div id="pmore" style="margin:10px 0;font-size:13.5px"></div>
</div>
<footer>Minutes played: ESPN box scores (a coach's-decision DNP counts as 0). Starters: on this season's depth chart or started at
least half their games. Expected minutes (2026-27, from Oct 27): what the trader bot's report showed (FantasyPros top 10, else RotoWire
for away teams, else SportsLine), or its last read before tip. Teammates who missed exactly the same games share a row.
Left out: DNPs for injury or rest (he wasn't available), 0-minute games before a player's first real game, players often benched
by the coach (not key teammates), and games with more than {MAX_OUT} key teammates out (e.g. Pacers, Nov 2).
Differences under {SHOW_CHANGE} minutes show as "no change".</footer>
<script>const LINES_ON={"true" if LINES else "false"}; const D={json.dumps(D, separators=(",", ":"))}; const CH={json.dumps(CH["rows"], separators=(",", ":"))};
{JS}</script></body></html>"""


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--lines" in args:           # our prematch points lines (from Snowflake); keep that file and the page out of the repo
        i = args.index("--lines")
        LINES.update(json.load(open(args[i + 1])))
        del args[i:i + 2]
    out = args[0] if args else os.path.join(HERE, "minutes_when_out.html")
    D = build_data()
    through = max((r["date"] for r in csv.DictReader(open(os.path.join(HERE, "data", "box_2026-27.csv")))), default="")
    open(out, "w").write(page(D, season_changes(), through))
    print(out, {s: len(t) for s, t in D.items()})
