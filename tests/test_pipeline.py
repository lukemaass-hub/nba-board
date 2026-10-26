import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import datetime as dt
import update_data as u
u.today_et = lambda: dt.date(2026, 10, 6)

CBS = """
<div class="TableBaseWrapper"><div class="TeamLogoNameLockup"><span class="TeamName"><a>L.A. Clippers</a></span></div>
<table><tbody>
<tr><td><span class="CellPlayerName--short"><a>M. Strus</a></span><span class="CellPlayerName--long"><a>Max Strus</a></span></td>
<td>SG</td><td>Mon, Oct 5</td><td>Foot</td><td>Expected to be out until at least Nov 2</td></tr>
<tr><td><span class="CellPlayerName--long"><a>Bradley Beal</a></span></td><td>SG</td><td>Sun, Oct 4</td><td>Knee</td><td>Game Time Decision</td></tr>
</tbody></table></div>"""

# Real Covers layout (Oct 6 2026): <b> status, padded abbreviated names, note in a collapsed row.
COVERS = """
<div class="covers-CoversMatchups-teamName"><a class="covers-CoversMatchups-imgLink" href="/sport/basketball/nba/teams/main/atlanta-hawks">Atlanta<br/><span>Hawks</span></a></div>
<table class="table table-sm covers-CoversMatchups-Table"><thead><tr><th>Player</th><th>POS</th><th>Status</th><th></th></tr></thead><tbody>
<tr><td><a class="player-link" href="/sport/basketball/nba/players/403756/henri-veesaar">H.                                        Veesaar</a></td><td>C</td>
<td><b>Out For Season - ACL</b><br/>(
Sun, Sep 20)</td><td><a href="#injuryCollapseAATL0"></a></td></tr>
<tr class="collapse" id="injuryCollapseAATL0"><td colspan="4"><div>Veesaar was diagnosed with a torn right ACL and is expected to miss the 2026-27 season.</div></td></tr>
<tr><td><a class="player-link" href="/sport/basketball/nba/players/239513/mouhamed-gueye">M.                                        Gueye</a></td><td>PF</td>
<td><b>Out - Foot</b><br/>(
Tue, Jul 14)</td><td><a href="#injuryCollapseAATL1"></a></td></tr>
<tr class="collapse" id="injuryCollapseAATL1"><td colspan="4"><div>Gueye underwent surgery on fractured foot and is to be re-evaluated in 3-4 months.</div></td></tr>
<tr><td><a class="player-link" href="/sport/basketball/nba/players/1/trae-young">T. Young</a></td><td>PG</td>
<td><b>Questionable - Ankle</b><br/>( Mon, Oct 5)</td><td></td></tr>
</tbody></table>"""

ESPN = {"injuries": [{"displayName": "Boston Celtics", "injuries": [
    {"status": "Out", "date": "2026-10-04T12:00Z", "athlete": {"displayName": "Jayson Tatum"},
     "details": {"type": "Achilles", "returnDate": "2026-12-01"}, "shortComment": "Rehab continues."},
    {"status": "Day-To-Day", "date": "2026-10-05T12:00Z", "athlete": {"displayName": "Derrick White"},
     "details": {"type": "Ankle", "side": "Left"}},
    {"status": "Day-To-Day", "date": "2026-10-06T00:29Z", "athlete": {"displayName": "Aaron Wiggins"},
     "details": {"type": "Not Specified", "detail": "Laceration", "location": "Lips"}}]}]}

def espn_team(name, **cols):
    return {"team": {"displayName": name}, "depthchart": [{"positions": {
        p: {"athletes": [{"displayName": n} for n in names]} for p, names in cols.items()}}]}


# Real RotoWire layout (Oct 6 2026), trimmed to one game.
ROTO = """<h1>NBA Daily Starting Lineups</h1><div>Starting lineups for October 6, 2026</div>
<div class="lineup is-nba"><div class="lineup__time">7:00 PM ET</div>
<a class="lineup__team is-visit"><div class="lineup__abbr">BKN</div></a><a class="lineup__team is-home"><div class="lineup__abbr">CHA</div></a>
<ul class="lineup__list is-visit"><li class="lineup__status is-confirmed">Confirmed Lineup</li>
<li class="lineup__player"><div class="lineup__pos">PG</div><a title="Ben Saraf">Ben Saraf</a></li>
<li class="lineup__player"><div class="lineup__pos">SF</div><a title="Michael Porter">M. Porter</a><span class="lineup__inj">Ques</span></li>
<li><button>Projected Minutes</button></li>
<li class="lineup__title is-middle">MAY NOT PLAY</li>
<li class="lineup__player has-injury-status"><div class="lineup__pos">G</div><a title="Mikel Brown">M. Brown</a><span class="lineup__inj">Out</span></li>
<li class="lineup__player has-injury-status"><div class="lineup__pos">F</div><a title="Noah Clowney">N. Clowney</a><span class="lineup__inj">Prob</span></li></ul>
<ul class="lineup__list is-home"><li class="lineup__status is-expected">Expected Lineup</li>
<li class="lineup__player"><div class="lineup__pos">PG</div><a title="Dennis Schroder">D. Schroder</a></li></ul></div>"""


def test_until_parsers():
    assert u.parse_until("Expected to be out until at least Jan 2") == "2027-01-02"
    assert u.parse_until("Expected to be out until at least Nov 2") == "2026-11-02"
    assert u.parse_duration_until("out at least 4 weeks", "2026-10-04") == "2026-11-01"
    assert u.parse_duration_until("re-evaluated in two weeks", "2026-10-04") == "2026-10-18"
    assert u.parse_duration_until("expected to miss the season", "2026-10-04") == ""


def test_cbs():
    r = u.parse_cbs(CBS)
    assert [(x["team"], x["player"], x["kind"], x["until"]) for x in r] == [
        ("LAC", "Max Strus", "O", "2026-11-02"), ("LAC", "Bradley Beal", "G", "")]
    assert r[1]["through"]


def test_covers():
    r = u.parse_covers(COVERS)
    assert [(x["team"], x["player"], x["kind"], x.get("st")) for x in r] == [
        ("ATL", "Henri Veesaar", "O", None), ("ATL", "Mouhamed Gueye", "O", None), ("ATL", "Trae Young", "G", "q")]
    assert r[0]["upd"] == "2026-09-20" and r[0]["until"] == "" and r[0]["injury"] == "ACL"
    assert r[1]["upd"] == "2026-07-14" and r[1]["until"] == "2026-10-12"
    assert r[2]["through"] and r[2]["injury"] == "Ankle"
    assert r[0]["url"].endswith("#:~:text=H.%20Veesaar")      # the name as Covers prints it


def test_status_words():
    assert [u.classify_status(t) for t in ["Out", "Out For Season", "Day-To-Day", "Game Time Decision", "Doubtful"]] == ["O", "O", "G", "G", "G"]
    assert [u.status_code(t) for t in ["Doubtful", "Questionable", "Probable", "Game Time Decision", "Day-To-Day"]] == ["doubt", "q", "prob", None, None]


def test_espn():
    r = u.parse_espn(ESPN)
    assert r[0]["kind"] == "O" and r[0]["until"] == "2026-12-01" and r[0]["injury"] == "Achilles"
    assert r[1]["kind"] == "G" and r[1]["injury"] == "Left Ankle"
    assert r[2]["injury"] == "Laceration"


def test_espn_depth():
    team, d = u.parse_espn_depth(espn_team("Atlanta Hawks",
        pg=["CJ McCollum", "Kingston Flemings", "RayJ Dennis"], sg=["Nickeil Alexander-Walker", "CJ McCollum", "Luguentz Dort"],
        sf=["Dyson Daniels", "Aaron Wiggins"], pf=["Jalen Johnson", "Aaron Wiggins", "Mouhamed Gueye"],
        c=["Onyeka Okongwu", "Jock Landale", "Zuby Ejiofor", "Henri Veesaar"]))
    assert team == "ATL"
    # bench ranked by best depth slot: Flemings, Wiggins, Landale (2nd), Dennis, Dort (3rd) = rotation; Gueye 6th
    assert d["PG"] == "CJ McCollum/Kingston Flemings,RayJ Dennis/"
    assert d["SG"] == "Nickeil Alexander-Walker/Luguentz Dort/"
    assert d["SF"] == "Dyson Daniels/Aaron Wiggins/"
    assert d["PF"] == "Jalen Johnson//Mouhamed Gueye"
    assert d["C"] == "Onyeka Okongwu/Jock Landale/Zuby Ejiofor,Henri Veesaar"


def test_rotowire():
    lineups, inj = u.parse_rotowire(ROTO)
    assert lineups["BKN"] == {"date": "2026-10-06", "time": "19:00", "vs": "CHA", "home": False, "confirmed": True,
                              "starters": [{"pos": "PG", "name": "Ben Saraf"}, {"pos": "SF", "name": "Michael Porter"}]}
    assert lineups["CHA"]["confirmed"] is False
    assert [(r["player"], r["st"], r["kind"], r["through"]) for r in inj] == [
        ("Michael Porter", "q", "G", "2026-10-06"), ("Mikel Brown", "out", "O", "2026-10-06"),   # tag "Out" = out
        ("Noah Clowney", "q", "G", "2026-10-06")]                                        # other tags = questionable
    assert inj[1]["note"] == "RotoWire tag: Out"
    assert inj[1]["url"].endswith("#:~:text=M.%20Brown")


def test_schedule_et():
    g, sk = u.parse_schedule([
        {"DateUtc": "2026-10-21 01:30:00Z", "HomeTeam": "San Antonio Spurs", "AwayTeam": "Oklahoma City Thunder", "Location": "Frost Bank Center"},
        {"DateUtc": "2026-11-28 00:00:00Z", "HomeTeam": "New York Knicks", "AwayTeam": "Miami Heat", "Location": "MSG"},
        {"DateUtc": "2026-12-04 05:00:00Z", "HomeTeam": "To be announced", "AwayTeam": "To be announced", "Location": "TBA"}])
    assert (g[0]["date"], g[0]["time"]) == ("2026-10-20", "21:30")
    assert (g[1]["date"], g[1]["time"]) == ("2026-11-27", "19:00") and sk == 1


def test_minutes_csv():
    m = u.parse_minutes_csv("player,team,mpg\nJalen Brunson,NYK,35.2\nBad,NYK,x\n")
    assert m == {"Jalen Brunson": 35.2}


def test_beat_classification():
    tweets = [{"text": "Alvarado is questionable for tonight with a sore knee.", "created_at": "2026-10-06T15:00:00Z", "handle": "writer", "url": "https://x.com/writer/status/1"},
              {"text": "Great win last night.", "created_at": "2026-10-06T15:01:00Z", "handle": "writer", "url": "https://x.com/writer/status/2"}]
    fake = lambda p: '[{"player":"Jose Alvarado","status":"questionable","injury":"knee","note":"Sore knee.","tweet_index":0},{"player":"X","status":"bogus","tweet_index":0}]'
    r = u.classify_tweets("NYK", tweets, fake)
    assert len(r) == 1 and r[0]["src"] == "@writer" and r[0]["st"] == "q" and r[0]["through"] == "2026-10-08"


def test_pregame_window():
    sch = [{"date": "2026-10-21", "time": "19:30"}]
    at = lambda h, m: dt.datetime(2026, 10, 21, h, m, tzinfo=u.ET)
    assert u.game_starting_soon(sch, at(18, 50), 45)
    assert not u.game_starting_soon(sch, at(18, 30), 45)
    assert not u.game_starting_soon(sch, at(19, 45), 45)


def test_email_due_and_build():
    import email_report as e
    data = {"schedule": [{"date": "2026-10-21", "time": "19:30", "away": "MIA", "home": "NYK"}],
            "lineups": {"CHA": {"date": "2026-10-21", "time": "19:00", "vs": "BKN", "home": True, "confirmed": False,
                                "starters": [{"pos": "PG", "name": "Dennis Schroder"}]}},
            "depth": {"NYK": {"PG": "Jalen Brunson/Miles McBride/", "C": "Karl-Anthony Towns//"}},
            "injuries": [{"team": "NYK", "player": "Jalen Brunson", "src": "ESPN", "kind": "O", "injury": "Ankle",
                          "until": "", "through": "", "url": "https://x/#b"}]}
    now = dt.datetime(2026, 10, 21, 18, 55, tzinfo=u.ET)
    assert [k for k, _ in e.due_games(data, now, 40, {})] == ["2026-10-21 BKN@CHA", "2026-10-21 MIA@NYK"]
    assert [k for k, _ in e.due_games(data, now, 40, {"2026-10-21 BKN@CHA": "x"})] == ["2026-10-21 MIA@NYK"]
    subject, body, text = e.build(data, [g for _, g in e.due_games(data, now, 40, {})], "2026-10-21")
    assert "MIA @ NYK 7:30 PM" in subject and 'href="https://x/#b"' in body
    assert "PG Miles McBride (in for Jalen Brunson)" in text and "Expected starters (RotoWire" in text


def test_matchup_alerts():
    import build_matchup_alerts as b, email_report as e
    opps = ["ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GS", "HOU", "IND", "LAC", "LAL", "MEM",
            "MIA", "MIL", "MIN", "NO", "NY", "OKC", "ORL", "PHI", "PHX", "POR", "SA", "SAC", "TOR", "UTAH", "WSH"]
    jokic = ["Nikola Jokic"] + [35.0] * 30 + ["DEN"]
    jokic[opps.index("DET") + 1] = 28.0          # well below his usual
    jokic[opps.index("DEN") + 1] = None          # never plays his own team
    grid = [[None] + opps + ["team"], jokic, ["Empty Row"] + [None] * 30 + ["SA"]]
    jokic[opps.index("BOS") + 1] = 44.0          # well above, but only 3 games -> no alert
    log = [(False, str(i), 28.0, "DET", "Nikola Jokic", "2025-26", "DEN") for i in range(5)] + \
          [(False, str(i), 44.0, "BOS", "Nikola Jokic", "2025-26", "DEN") for i in range(3)] + \
          [(True, "9", None, "DET", "Nikola Jokic", "2025-26", "DEN")]    # did not play: not counted
    games = b.games_played(log)
    assert games[("Nikola Jokic", "DET")] == 5 and games[("Nikola Jokic", "BOS")] == 3
    alerts = b.alerts_from_grid(grid, games)
    assert [(a["player"], a["opp"], a["dir"], a["games"]) for a in alerts] == [("Nikola Jokic", "DET", "down", 5)]
    data = {"matchup_alerts": alerts, "depth": {"DEN": {"C": "Nikola Jokic//"}}}
    assert e.matchup_alerts_for(data, "DEN", "DET", [], []) == [("Nikola Jokic", "down")]
    out = [{"player": "Nikola Jokic", "st": "out"}]
    assert e.matchup_alerts_for(data, "DEN", "DET", out, []) == []           # not shown when he's out


def test_slack_message_and_once_per_game(tmp_path, monkeypatch):
    import email_report as e, http.server, threading
    got = []

    class Fake(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tip = dt.datetime.now(u.ET) + dt.timedelta(minutes=15)
    data = {"schedule": [{"date": tip.date().isoformat(), "time": tip.strftime("%H:%M"), "away": "MIA", "home": "NYK"}],
            "depth": {"NYK": {"PG": "Jalen Brunson/Miles McBride/"}},
            "injuries": [{"team": "NYK", "player": "Jalen Brunson", "src": "ESPN", "kind": "O", "url": "https://x/#b"}],
            "matchup_alerts": [{"player": "Miles McBride", "opp": "MIA", "dir": "up"}]}
    (tmp_path / "data.json").write_text(json.dumps(data))
    log = tmp_path / "log.json"
    monkeypatch.setenv("SLACK_WEBHOOK_URL", f"http://127.0.0.1:{srv.server_port}/hook")
    for v in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.delenv(v, raising=False)
    for _ in range(2):                                   # second run must not post again
        monkeypatch.setattr(sys, "argv", ["x", "--data", str(tmp_path / "data.json"), "--log", str(log)])
        e.main()
    srv.shutdown()
    assert len(got) == 1
    blocks = got[0]["blocks"]
    assert blocks[0]["type"] == "header" and "Miami Heat @ New York Knicks" in blocks[0]["text"]["text"]
    text = json.dumps(blocks)
    assert "Miles McBride" in text and "in for Jalen Brunson" in text and "<https://x/#b|Jalen Brunson>" in text
    assert "usually plays *more* minutes vs Heat" in text and len(blocks) <= 50
    assert list(json.loads(log.read_text())) == [f"slack {tip.date().isoformat()} MIA@NYK"]


NEWS_RSS = """<?xml version="1.0"?><rss><channel>
<item><guid>nba1</guid><title>Zach Edey: More minutes on tap</title><link>https://www.rotowire.com//basketball/player/zach-edey-6263</link>
<description>Edey will play Friday and is expected to see an uptick in minutes, Rob Fischer of FanDuel Sports Network Southeast reports.

        Visit RotoWire.com for more analysis on this update.</description><pubDate>Fri, 09 Oct 2026 3:45:00 PM PDT</pubDate></item>
<item><guid>nba2</guid><title>Kevin Durant: Will sit out Sunday</title><link>https://www.rotowire.com/x</link>
<description>Durant will not play Sunday, Varun Shankar of the Houston Chronicle reports.</description><pubDate>Fri, 09 Oct 2026 8:03:00 AM PDT</pubDate></item>
</channel></rss>"""


def test_news_feed():
    items = u.parse_news(NEWS_RSS)
    assert items[0] == {"id": "nba1", "player": "Zach Edey", "headline": "More minutes on tap",
                        "text": "Edey will play Friday and is expected to see an uptick in minutes, Rob Fischer of FanDuel Sports Network Southeast reports.",
                        "reporter": "Rob Fischer", "outlet": "FanDuel Sports Network Southeast",
                        "url": "https://www.rotowire.com/basketball/player/zach-edey-6263", "at": "2026-10-09T22:45:00+00:00"}
    assert (items[1]["reporter"], items[1]["outlet"]) == ("Varun Shankar", "Houston Chronicle")
    data = {"depth": {"MEM": {"C": "Zach Edey//"}, "HOU": {"SF": "Kevin Durant//"}}}
    now = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)
    old = [{"id": "nba0", "player": "Old News", "at": "2026-10-01T00:00:00+00:00"}]          # > 3 days: dropped
    kept = u.merge_news(old, items + items, data, now)                                          # duplicates collapse
    assert [(i["id"], i["team"]) for i in kept] == [("nba1", "MEM"), ("nba2", "HOU")]
    import email_report as e
    later = dt.datetime(2026, 10, 11, 6, tzinfo=dt.timezone.utc)      # Edey item 31 h old, Durant item 39 h old
    assert [i["id"] for i in e.news_for({"news": kept}, "MEM", later)] == ["nba1"]
    assert e.news_for({"news": kept}, "HOU", later) == []                                      # older than 36 hours


def test_news_sets_status_and_restrictions():
    fri = dt.datetime(2026, 10, 9, 20, tzinfo=dt.timezone.utc)              # posted Friday afternoon ET
    assert u.news_status("Durant will not play in Sunday's game") == "out"
    assert u.news_status("Sarr's status for Saturday's game remains uncertain") == "q"
    assert u.news_status("Irving is scheduled to play Sunday") == "prob"
    assert u.news_status("Bridges participated in Friday's practice") is None
    assert u.news_dates("Durant will not play in Sunday's game", fri) == ("2026-10-11", "2026-10-11")
    assert u.news_dates("Coach said Friday that Sarr's status for Saturday's game is uncertain", fri) == ("2026-10-10", "2026-10-10")
    assert u.news_dates("Brunson is questionable tonight", fri) == ("2026-10-09", "2026-10-10")
    assert u.RESTRICTION.search("will be on a minutes restriction") and u.RESTRICTION.search("limited to about 20 minutes")
    assert not u.RESTRICTION.search("He played 31 minutes") and not u.RESTRICTION.search("an uptick in minutes")

    data = {"injuries": [{"team": "NYK", "player": "Jalen Brunson", "src": "ESPN", "kind": "O", "st": "out"}],
            "news": [{"id": "n1", "team": "NYK", "player": "Jalen Brunson", "headline": "Questionable Friday", "at": fri.isoformat(),
                      "text": "Brunson is questionable for Friday's game and will be on a minutes restriction if he plays, A B of C reports.",
                      "reporter": "A B", "outlet": "C", "url": "https://r/1"}]}
    u.apply_news(data)
    u.apply_news(data)                                                       # running twice doesn't duplicate
    assert len(data["injuries"]) == 2 and len(data["restrictions"]) == 1
    import email_report as e
    inj = e.injuries_for(data, "NYK", "2026-10-09")
    assert (inj[0]["st"], inj[0]["beat"], inj[0]["differ"]) == ("q", "A B", True)   # writer beats ESPN's "out"
    assert e.injuries_for(data, "NYK", "2026-10-08")[0]["st"] == "out"                 # news not in effect yet
    assert [w["player"] for w in e.restrictions_for(data, ("NYK", "MIA"), "2026-10-09")] == ["Jalen Brunson"]
    assert e.restrictions_for(data, ("NYK",), "2026-10-12") == []


def test_season_minutes_and_weekly():
    import email_report as e
    j = {"athletes": [{"athlete": {"displayName": "Jalen Brunson", "teamShortName": "NY"},
                       "categories": [{"name": "general", "totals": ["74", "35.0", "2.1"]}]}]}
    assert u.parse_season_stats(j) == {"Jalen Brunson": [74, 35.0, "NYK"]}
    assert u.espn_season(dt.date(2026, 10, 9)) == 2027 and u.season_label(2027) == "2026-27"
    # ESPN answers a season that hasn't started with the last finished one: that must count as no data
    real_get = u.get
    class R:
        def __init__(self, year): self.year = year
        def json(self): return {**j, "requestedSeason": {"year": self.year}}
    try:
        u.get = lambda url: R(2026)
        assert u.season_stats(2027) == {} and u.season_stats(2026) == {"Jalen Brunson": [74, 35.0, "NYK"]}
    finally:
        u.get = real_get
    sm = {"season": "2026-27", "last_season": "2025-26", "fetched_at": "2026-11-20T11:00:00+00:00",
          "current": {"Jalen Brunson": [2, 30.0, "NYK"], "Miles McBride": [16, 29.0, "NYK"], "Josh Hart": [8, 33.0, "NYK"],
                      "Mitchell Robinson": [9, 25.0, "NYK"]},
          "last": {"Jalen Brunson": [74, 35.0, "NYK"], "Miles McBride": [70, 20.0, "NYK"], "Josh Hart": [77, 32.0, "NYK"]},
          "prior": {"Mitchell Robinson": [17, 22.0, "NYK"]}}   # an old 2024-25 entry must be ignored
    data = {"season_minutes": sm}
    # Oct 26 2026: this season's average as soon as he has played (was: after 15 games)
    assert e.avg_minutes(data, "Jalen Brunson") == (30.0, "2026-27")       # 2 games this season: this season
    assert e.avg_minutes(data, "Josh Hart") == (33.0, "2026-27")
    assert e.avg_minutes(data, "Miles McBride") == (29.0, "2026-27")
    assert e.avg_minutes(data, "Mitchell Robinson") == (25.0, "2026-27")   # 2024-25 is never used
    assert e.mins_tag(data, "Josh Hart", True) == " (33.0 MPG)"
    no_games = {"season_minutes": {**{k: v for k, v in sm.items() if k != "_idx"}, "current": {}}}
    assert e.mins_tag(no_games, "Josh Hart", True) == " (32.0 MPG, 2025-26)"   # last season says so
    assert e.avg_minutes(no_games, "Mitchell Robinson") is None
    assert e.minutes_change(data, "Mitchell Robinson") is None
    assert e.mins_tag(data, "Nobody") == ""
    assert e.minutes_change(data, "Miles McBride") == (9.0, 29.0, 20.0, "2025-26")
    assert e.minutes_change(data, "Josh Hart") is None and e.minutes_change(data, "Jalen Brunson") is None
    rows = e.weekly_changes(data)
    assert [(r["player"], r["diff"]) for r in rows] == [("Miles McBride", 9.0)]
    title, body, text = e.build_weekly(data, rows)
    assert "1 players" in title and "Miles McBride (NYK): 29.0 vs 20.0 in 2025-26 (+9.0), 16 games" in text


def test_dolly_expected_minutes(monkeypatch):
    import email_report as _e
    monkeypatch.setattr(_e, 'EXPECTED_ENABLED', True)   # Dolly is disconnected; the feature is kept for later
    import email_report as e
    now = dt.datetime(2026, 10, 20, 18, 0, tzinfo=dt.timezone.utc)
    at = "2026-10-20T15:00:00+00:00"
    data = {"season_minutes": {"season": "2026-27", "last_season": "2025-26",
                               "current": {"Cade Cunningham": [3, 36.0, "DET"]},
                               "last": {"Cade Cunningham": [64, 33.9, "DET"], "Jalen Duren": [70, 26.0, "DET"],
                                        "Daniss Jenkins": [40, 27.5, "DET"], "Ausar Thompson": [60, 24.0, "DET"]}},
            "expected_minutes": {"players": [
                {"name": "Cade Cunningham", "team": "DET", "expected": 31.6, "game_date": "2026-10-20", "at": at},   # -2.3: no note
                {"name": "Jalen Duren", "team": "DET", "expected": 20.1, "game_date": "2026-10-20", "at": at},       # -5.9
                {"name": "Daniss Jenkins", "team": "DET", "expected": 30.5, "game_date": "2026-10-20", "at": at},    # +3.0: exactly 3
                {"name": "Ausar Thompson", "team": "DET", "expected": 30.0, "game_date": "2026-10-19", "at": at},    # other day
                {"name": "Jaylen Brown", "team": "BOS", "expected": 40.0, "game_date": "2026-10-20", "at": at}]}}
    data["season_minutes"]["last"].update({"Tolu Smith": [30, 9.1, "DET"], "Isaac Jones": [20, 5.1, "DET"]})
    data["expected_minutes"]["players"] += [
        {"name": "Tolu Smith", "team": "DET", "expected": 0.0, "game_date": "2026-10-20", "at": at},     # under 5 expected
        {"name": "Isaac Jones", "team": "DET", "expected": 11.0, "game_date": "2026-10-20", "at": at}]   # +5.9 but not rotation
    data["expected_minutes"]["players"][2]["expected"] = 32.5   # Jenkins +5.0 (exactly 5); Cade -2.3 stays untagged
    got = e.expected_minutes_for(data, "DET", "2026-10-20", now=now)
    assert [(n, x, a, d) for n, x, a, d, _ in got] == [("Jalen Duren", 20.1, 26.0, -5.9), ("Daniss Jenkins", 32.5, 27.5, 5.0)]
    assert e.expected_minutes_for(data, "DET", "2026-10-20", now=now, skip={"jalen duren"})[0][0] == "Daniss Jenkins"
    # shown next to the name: green with +, red with a minus sign
    tags = {e.norm_name(n): (x, d) for n, x, a, d, _ in got}
    assert "#1e8449" in e.exp_html(tags, "Daniss Jenkins") and "Exp 32.5 (+5.0)" in e.exp_html(tags, "Daniss Jenkins")
    assert "#c0392b" in e.exp_html(tags, "Jalen Duren") and "Exp 20.1 (−5.9)" in e.exp_html(tags, "Jalen Duren")
    assert e.exp_html(tags, "Cade Cunningham") == "" and e.exp_text(tags, "Jalen Duren") == " 📉 Expected 20.1 (-5.9)"
    assert e.expected_minutes_for(data, "DET", "2026-10-20", now=now + dt.timedelta(hours=40)) == []   # stale


def test_deep_bench_only_when_expected_up(monkeypatch):
    import email_report as _e
    monkeypatch.setattr(_e, 'EXPECTED_ENABLED', True)   # Dolly is disconnected; the feature is kept for later
    import email_report as e
    now = dt.datetime(2026, 10, 20, 18, 0, tzinfo=dt.timezone.utc)
    at = "2026-10-20T15:00:00+00:00"
    data = {"season_minutes": {"season": "2026-27", "last_season": "2025-26", "current": {},
                               "last": {"Paul Reed": [60, 13.9, "DET"], "Tolu Smith": [30, 9.1, "DET"], "Chaz Lanier": [20, 7.7, "DET"]}},
            "expected_minutes": {"players": [
                {"name": "Paul Reed", "team": "DET", "expected": 14.5, "game_date": "2026-10-20", "at": at},     # +0.6: any increase counts
                {"name": "Tolu Smith", "team": "DET", "expected": 0.0, "game_date": "2026-10-20", "at": at},     # down: hidden
                {"name": "Ugonna Onyenso", "team": "DET", "expected": 6.0, "game_date": "2026-10-20", "at": at}]}}   # no average, 5+
    deep = [("C", "Tolu Smith", ""), ("C", "Paul Reed", ""), ("SG", "Chaz Lanier", ""), ("C", "Ugonna Onyenso", "")]
    assert e.deep_bench_up(data, "DET", "2026-10-20", deep, now=now) == [("Paul Reed", 14.5, 0.6), ("Ugonna Onyenso", 6.0, None)]
    assert e.deep_bench_up(data, "DET", "2026-10-20", deep, skip={"paul reed"}, now=now) == [("Ugonna Onyenso", 6.0, None)]


def test_news_only_injuries_suspensions_restrictions():
    import email_report as e
    keep = ["Bona (foot) is questionable for Tuesday's meeting in New York.",
            "Murray (toe) said Monday he'll be fine to play in Wednesday's season opener.",
            "Smith was suspended three games for leaving the bench.",
            "Head coach Ime Udoka said Sunday that VanVleet won't face any minutes restrictions."]
    drop = ["The 76ers exercised the third-year team option on Edgecombe's contract.",
            "Miller agreed to a five-year, $209 million rookie-scale contract extension with Charlotte.",
            "Queta will come off the bench for Tuesday's season opener against Detroit.",
            "Head coach Steve Kerr confirmed Monday that Lendeborg will start Wednesday's opener."]
    assert all(e.news_relevant({"headline": "", "text": t}) for t in keep)
    assert not any(e.news_relevant({"headline": "", "text": t}) for t in drop)


def test_trader_schedule_parsed_and_dms_follow_mode(monkeypatch):
    import email_report as e, slack_assign as sa
    text = open(os.path.join(os.path.dirname(__file__), "fixtures", "schedule_1020.txt")).read()
    assert sa.is_schedule(text, dt.date(2026, 10, 20)) and not sa.is_schedule(text, dt.date(2026, 10, 21))
    s = sa.parse_schedule(text)
    assert set(s) == {("BOS", "DET"), ("PHI", "NYK"), ("OKC", "SAS")}          # NHL / NCAAF lines ignored
    assert s[("PHI", "NYK")] == [{"user": "U09BNHCQD5Z", "name": "Evan Finger", "role": "Cores"},
                                 {"user": "U0ACFA2QDFF", "name": "Amol Singh", "role": "Props"}]
    assert s[("BOS", "DET")] == [{"user": "U07P8A9C5N0", "name": "Ben Fortney", "role": ""}]
    assert sa.team_code("LA Clippers") == "LAC" and sa.team_code("Portland Trail Blazers") == "POR"

    game = {"date": "2026-10-20", "time": "19:00", "away": "PHI", "home": "NYK", "venue": ""}
    sentto = []
    monkeypatch.setattr(sa, "fetch_schedule", lambda token, date: text)
    monkeypatch.setattr(sa, "user_name", lambda token, user: "Name " + user)
    monkeypatch.setattr(sa, "dm", lambda token, user, title, blocks: sentto.append((user, blocks)))
    monkeypatch.setattr(sa, "post_channel", lambda token, ch, title, blocks: sentto.append((ch, blocks)))
    monkeypatch.setattr(sa, "group_dm", lambda token, users, title, blocks: sentto.append((",".join(users), blocks)))
    monkeypatch.setattr(e, "build_slack", lambda data, g, date, test=False: ("t", []))
    monkeypatch.setattr(e, "all_games", lambda data: [game])
    lineups = lambda c: {"lineups": {t: {"date": "2026-10-20", "confirmed": c} for t in ("PHI", "NYK")}}
    early, late = dt.datetime(2026, 10, 20, 18, 20, tzinfo=e.ET), dt.datetime(2026, 10, 20, 18, 47, tzinfo=e.ET)

    def run(mode, data, now):
        monkeypatch.setenv("SLACK_DM_MODE", mode); sentto.clear(); log = {}
        e.dm_traders(data, "xoxb", now, 25, log, "now")
        return [u for u, _ in sentto], log

    # 40 min out, lineups not confirmed yet: wait
    assert run("on", lineups(False), early) == ([], {})
    # lineups confirmed: one group DM with the Cores and Props traders (Evan, Amol), just the report
    users, log = run("on", lineups(True), early)
    assert users == ["U09BNHCQD5Z,U0ACFA2QDFF"] and "dm 2026-10-20 PHI@NYK" in log and sentto[0][1] == []
    # never confirmed: sent anyway 15 min before tip
    assert run("on", lineups(False), late)[0] == ["U09BNHCQD5Z,U0ACFA2QDFF"]
    # extra people for a date (the owner on Oct 26 2026) join the group
    monkeypatch.setattr(sa, "ALSO_INCLUDE", {"2026-10-20": ["U0B5EP4PV3M"]})
    assert run("on", lineups(True), early)[0] == ["U09BNHCQD5Z,U0ACFA2QDFF,U0B5EP4PV3M"]
    monkeypatch.setattr(sa, "ALSO_INCLUDE", {})
    # off: nothing sent, nothing logged; test: owner only, says who and why
    assert run("off", lineups(True), early) == ([], {})
    assert run("test", lineups(True), early)[0] == ["U0B5EP4PV3M"]
    assert "Would go to a group DM with: Evan Finger (Cores), Amol Singh (Props) (lineups confirmed)" in sentto[0][1][0]["elements"][0]["text"]
    monkeypatch.setenv("SLACK_TEST_CHANNEL", "C0TEST")
    assert run("test", lineups(True), early)[0] == ["C0TEST"]
    monkeypatch.delenv("SLACK_TEST_CHANNEL")
    # already sent: not again
    monkeypatch.setenv("SLACK_DM_MODE", "on"); sentto.clear()
    e.dm_traders(lineups(True), "xoxb", early, 25, {"dm 2026-10-20 PHI@NYK": "x"}, "now")
    assert sentto == []


def test_newest_dolly_minutes_used(tmp_path, monkeypatch):
    import email_report as _e
    monkeypatch.setattr(_e, 'EXPECTED_ENABLED', True)   # Dolly is disconnected; the feature is kept for later
    import email_report as e
    p = tmp_path / "expected_minutes.json"
    p.write_text(json.dumps({"updated_at": "2026-10-21T21:00:00Z", "players": [{"name": "A B", "teamName": "Boston Celtics", "expected": 30}]}))
    data = {"expected_minutes": {"updated_at": "2026-10-21T20:00:00Z", "players": []}}
    e.fresh_expected_minutes(data, str(p))
    assert data["expected_minutes"]["players"][0]["team"] == "BOS"
    old = {"expected_minutes": {"updated_at": "2026-10-21T22:00:00Z", "players": []}}
    e.fresh_expected_minutes(old, str(p))
    assert old["expected_minutes"]["players"] == []


def test_back_to_back_warning():
    import email_report as e
    data = {"schedule": [
        {"date": "2026-10-25", "time": "19:00", "away": "BKN", "home": "IND", "venue": ""},
        {"date": "2026-10-26", "time": "19:00", "away": "IND", "home": "MIL", "venue": ""},
        {"date": "2026-10-27", "time": "19:30", "away": "MIA", "home": "MIL", "venue": ""}]}
    g = data["schedule"][1]
    b = e.b2b_for(data, g)
    assert [(t, w) for t, w, _ in b] == [("IND", "2nd"), ("MIL", "1st")]
    assert e.b2b_text(*b[0]) == "2nd game of a back-to-back: played vs BKN last night"
    assert e.b2b_text(*b[1]) == "1st game of a back-to-back: vs MIA tomorrow 7:30 PM ET"
    assert e.b2b_for(data, data["schedule"][0]) == [("IND", "1st", g)]
    _, blocks = e.build_slack(data, g, g["date"])
    assert "BACK-TO-BACK: Indiana Pacers" in json.dumps(blocks) and "BACK-TO-BACK: Milwaukee Bucks" in json.dumps(blocks)


def test_dolly_minutes_left_out_while_disconnected():
    import email_report as e
    data = {"expected_minutes": {"players": [{"name": "A B", "team": "BOS", "expected": 40, "at": "2099-01-01T00:00:00+00:00"}]}}
    assert e.EXPECTED_ENABLED is False and e.expected_raw(data, "BOS", "2026-10-26") == []


def test_presserwire_official_report_and_notes():
    import update_data as u, email_report as e
    fx = lambda n: open(os.path.join(os.path.dirname(__file__), "fixtures", n)).read()
    recs, notes = u.parse_pw_injury_report(fx("presserwire_injury_report.html"), "2026-10-26T22:00:00+00:00")
    by = {r["player"]: r for r in recs}
    assert by["Henri Veesaar"]["kind"] == "O" and by["Henri Veesaar"]["team"] == "ATL" and by["Henri Veesaar"]["src"] == "NBA report"
    assert by["Jock Landale"]["st"] == "avail" and by["Coby White"]["kind"] == "O"
    assert by["Devin Carter"]["from"] == by["Devin Carter"]["through"] == "2026-10-26" and by["Devin Carter"]["override"]
    assert notes and notes[0]["players"] == ["Jock Landale"] and notes[0]["url"].startswith("https://x.com/")
    av = u.parse_pw_availability(fx("presserwire_availability.html"))
    assert av[0]["team"] == "NOP" and "Yves Missi" in av[0]["players"] and av[0]["at"].startswith("2026-10-26T21:33")
    # official status wins over the sites; "per NBA report" only when it decided it
    data = {"injuries": [u.rec("ATL", "Jock Landale", "CBS", "G", st="q"), by["Jock Landale"], u.rec("ATL", "Henri Veesaar", "CBS", "O"),
                         by["Henri Veesaar"]],
            "presserwire": {"notes": av}}
    inj = {i["player"]: i for i in e.injuries_for(data, "ATL", "2026-10-26")}
    assert inj["Jock Landale"]["st"] == "avail" and inj["Jock Landale"]["beat"] == "NBA report"
    assert inj["Henri Veesaar"]["st"] == "out" and inj["Henri Veesaar"]["beat"] == ""
    now = dt.datetime(2026, 10, 26, 23, 0, tzinfo=dt.timezone.utc)
    assert e.pressers_for(data, "NOP", now) and e.pressers_for(data, "NOP", now + dt.timedelta(days=3)) == []
