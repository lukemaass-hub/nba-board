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

DEPTH = """
<h2>2026-2027 Atlanta Hawks Depth Chart</h2>
<table><thead><tr><th></th><th>PG</th><th>SG</th></tr></thead><tbody>
<tr><td>Starters</td><td><a href="/player/CJ-McCollum/Summary/1">C.J. McCollum</a> 19p</td><td><a href="/player/Nickeil-Alexander-Walker/Summary/2">N. Alexander-Walker</a></td></tr>
<tr><td>Rotation</td><td></td><td><a href="/player/Foo-Bar/Summary/3">Foo Bar</a></td></tr>
<tr><td>Lim PT</td><td><a href="/player/RayJ-Dennis/Summary/4">RayJ Dennis</a></td><td></td></tr>
</tbody></table>"""


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


def test_status_words():
    assert [u.classify_status(t) for t in ["Out", "Out For Season", "Day-To-Day", "Game Time Decision", "Doubtful"]] == ["O", "O", "G", "G", "G"]
    assert [u.status_code(t) for t in ["Doubtful", "Questionable", "Probable", "Game Time Decision", "Day-To-Day"]] == ["doubt", "q", "prob", None, None]


def test_espn():
    r = u.parse_espn(ESPN)
    assert r[0]["kind"] == "O" and r[0]["until"] == "2026-12-01" and r[0]["injury"] == "Achilles"
    assert r[1]["kind"] == "G" and r[1]["injury"] == "Left Ankle"
    assert r[2]["injury"] == "Laceration"


def test_depth():
    d = u.parse_realgm_depth(DEPTH)
    assert d["ATL"]["PG"] == "CJ McCollum//RayJ Dennis"
    assert d["ATL"]["SG"] == "Nickeil Alexander Walker/Foo Bar/"
    assert u.norm_name("Nickeil Alexander Walker") == u.norm_name("Nickeil Alexander-Walker")


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
