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
