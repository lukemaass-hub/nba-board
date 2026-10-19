// NBA board: reads Dolly's prematch Expected Mins off the Rosters screen (test Dolly only) for the daily email.
// Read-only: text only, nothing clicked, typed or changed, and it never measures the page (that slows Dolly).
// Separate from the DraftKings/FanDuel props extension on purpose.
(() => {
  if (window.__nbaBoardDollyMinutes) return;
  window.__nbaBoardDollyMinutes = true;
  // ------------------------------------------------------------ Rosters: Dolly's prematch expected minutes
  // The Rosters screen lists each team ("Detroit Pistons") and rows like "Cade Cunningham - 62002068637" with
  // Starting Weight (a box), Expected Mins (text, e.g. 31.6), Adjust Mins and Closing Weight (boxes). So in each
  // row the first decimal shown as TEXT is Expected Mins. Text only, read-only, as above.
  const NBA_TEAMS = ['Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets', 'Chicago Bulls', 'Cleveland Cavaliers',
    'Dallas Mavericks', 'Denver Nuggets', 'Detroit Pistons', 'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers',
    'LA Clippers', 'Los Angeles Clippers', 'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat', 'Milwaukee Bucks',
    'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks', 'Oklahoma City Thunder', 'Orlando Magic',
    'Philadelphia 76ers', 'Phoenix Suns', 'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors',
    'Utah Jazz', 'Washington Wizards'];
  const ROSTER_ROW = /^(.+?)\s+-\s+\d{6,}$/;
  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

  function rowNumber(labelEl) {
    let row = labelEl;
    for (let i = 0; i < 6 && row.parentElement; i++) {
      row = row.parentElement;
      const w = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
      let n, labels = 0, num = null;
      while ((n = w.nextNode())) {
        if (n.parentElement && n.parentElement.closest('option, select')) continue;   // the role dropdown
        const t = n.nodeValue.trim();
        if (!t) continue;
        if (ROSTER_ROW.test(t)) { if (++labels > 1) return null; }
        else if (num == null && /^\d{1,2}(\.\d)?$/.test(t)) num = parseFloat(t);
      }
      if (num != null) return num;
    }
    return null;
  }

  function readRosters() {
    const players = [];
    let team = null, gameDate = null, n;
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while ((n = w.nextNode())) {
      const t = n.nodeValue.replace(/\s+/g, ' ').trim();
      if (!t || t.length > 60) continue;
      if (!gameDate) { const d = t.match(/^([A-Z][a-z]{2})\s+(\d{1,2})\s+\d{1,2}:\d{2}$/); if (d && MONTHS[d[1].toLowerCase()]) {
        const now = new Date(), m = MONTHS[d[1].toLowerCase()], y = now.getFullYear() + (m < now.getMonth() - 5 ? 1 : 0);
        gameDate = `${y}-${String(m).padStart(2, '0')}-${String(d[2]).padStart(2, '0')}`; } }
      if (NBA_TEAMS.includes(t)) { team = t; continue; }
      const m = t.match(ROSTER_ROW);
      if (!m || !team) continue;
      const exp = rowNumber(n.parentElement);
      if (exp != null) players.push({ name: m[1].trim(), teamName: team, expected: exp });
    }
    return { players, gameDate, fixtureId: (location.pathname.match(/\/fixture\/(\d+)/) || [])[1] || null };
  }

  // While a Rosters screen is open, send its numbers to the extension about once a minute (only when they change).
  let lastSent = '';
  setInterval(() => {
    if (!/expected\s*mins/i.test(document.body.textContent)) return;   // text only: innerText would make Dolly re-measure its layout
    try {
      const r = readRosters();
      if (!r.players.length) return;
      const sig = JSON.stringify(r);
      if (sig === lastSent) return;
      lastSent = sig;
      chrome.runtime.sendMessage({ type: 'DOLLY_ROSTERS', ...r, at: Date.now(), url: location.href });
    } catch { /* never disturb Dolly */ }
  }, 60_000);
  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (msg?.type !== 'DOLLY_ROSTERS_NOW') return false;
    try { sendResponse({ ok: true, ...readRosters() }); } catch (e) { sendResponse({ ok: false, error: String(e) }); }
    return false;
  });
})();
