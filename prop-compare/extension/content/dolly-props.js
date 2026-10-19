// Reads OUR in-app player-points prices (the "App" column) off the Dolly Market Manager screen.
// Read-only: nothing is clicked, typed, changed or sent anywhere. Layout-free: it never measures
// the page (measuring forces Dolly to recalculate its whole layout, which froze it in v0.11/0.12).
// It walks the page's text in order, keeps track of the market heading it is under (PLAYER TOTAL
// POINTS, ALTERNATE PLAYER POINTS, ...), reads each points selection ("JORDAN WALSH OVER 0.5",
// "DUNCAN ROBINSON TO SCORE 5+ POINTS"), and takes that row's App cell (see appPrice).
// Runs only when the dashboard asks (DOLLY_READ), once per pull.
(() => {
  if (window.__propCompareDolly) return;
  window.__propCompareDolly = true;

  const PRICE = /^\d+\.\d+$/;
  // a selection row's label: "JORDAN WALSH OVER 0.5" / "... UNDER 0.5" (under its market heading),
  // or "DUNCAN ROBINSON TO SCORE 5+ POINTS"
  const OU = /^(.+?)\s+(over|under)\s+(\d+(?:\.\d+)?)(?:\s+(?:total\s+)?(?:points|pts))?$/i;
  const ALT = /^(.+?)\s+to score\s+(\d+)\s*\+\s*(?:points|pts)?$/i;
  const SEL = /\s(over|under)\s+\d+(\.\d+)?$|\sto (score|get|record)\s+\d+\s*\+/i;
  // market headings, e.g. "PLAYER TOTAL POINTS", "ALTERNATE PLAYER POINTS", "PLAYER REBOUNDS"
  const MARKET = /^(alternate\s+)?player\s+[a-z0-9' +&-]+$/i;
  const POINTS_MARKET = (m) => /\bpoints\b/i.test(m) && !/three|rebound|assist|steal|block|combo|\+|&/i.test(m);
  const titleCase = (n) => n === n.toUpperCase() ? n.toLowerCase().replace(/(^|[\s'-])([a-z])/g, (m, p, c) => p + c.toUpperCase()).replace(/\b(Ii|Iii|Iv)\b/g, (m) => m.toUpperCase()) : n;
  const american = (d) => !(d > 1) ? null : d >= 2 ? `+${Math.round((d - 1) * 100)}` : String(Math.round(-100 / (d - 1)));

  function parseSel(t, market) {
    let m = t.match(ALT);
    if (m) return { player: titleCase(m[1]), kind: 'alt', line: parseInt(m[2], 10) - 0.5, side: 'over' };
    m = t.match(OU);
    if (m && (POINTS_MARKET(market) || /\b(points|pts)$/i.test(t))) return { player: titleCase(m[1]), kind: 'ou', line: parseFloat(m[3]), side: m[2].toLowerCase() };
    return null;
  }

  // App price for the row holding this selection label. The row's prices shown as text are, in
  // order: AF (e.g. 1.00, may be blank), App, OF; Hard / Soft / Trading are input boxes (not text).
  // So with three numbers App is the 2nd, with two (AF blank) it is the 1st.
  function appPrice(labelEl) {
    let row = labelEl;
    for (let i = 0; i < 8 && row.parentElement; i++) {
      row = row.parentElement;
      const w = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
      let n, labels = 0;
      const nums = [];
      while ((n = w.nextNode())) {
        const s = n.nodeValue.replace(/\s+/g, ' ').trim();
        if (!s) continue;
        if (SEL.test(s)) { if (++labels > 1) return null; }   // climbed past the row into the table
        else if (PRICE.test(s)) nums.push(parseFloat(s));
      }
      if (nums.length >= 2) return nums.length >= 3 ? nums[1] : nums[0];
    }
    return null;
  }

  function read() {
    const quotes = [], sample = [], markets = [];
    let rows = 0, market = '';
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const s = n.nodeValue.replace(/\s+/g, ' ').trim();
      if (s.length < 8 || s.length > 80) continue;
      if (MARKET.test(s) && s === s.toUpperCase() && !SEL.test(s)) { market = s; if (markets.length < 12 && !markets.includes(s)) markets.push(s); continue; }
      if (!SEL.test(s)) continue;
      rows++;
      const q = parseSel(s, market);
      if (!q) continue;
      const d = appPrice(n.parentElement);
      if (!(d > 1)) continue;
      if (sample.length < 3) sample.push(`${market}: ${s} → App ${d}`);
      quotes.push({ book: 'OURS', ...q, american: american(d), decimal: d });
    }
    return { quotes, rows, sample, markets };
  }

  function teams() {
    const m = (document.title || '').match(/(.+?)\s+(?:v|vs\.?|@)\s+(.+?)(?:\s+[-|–]|$)/i);
    return m ? [m[1].trim(), m[2].trim()] : [];
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'DOLLY_READ') return false;
    if (window.top === window && !/market-manager/.test(location.href)) { sendResponse({ ok: false, error: 'not a Market Manager page' }); return false; }
    try {
      const t0 = performance.now();
      const r = read();
      if (window.top !== window && !r.quotes.length) return false;   // sub-frames answer only if they hold the prices
      sendResponse({ ok: true, version: chrome.runtime.getManifest().version, at: Date.now(), readMs: Math.round(performance.now() - t0), url: location.href,
        frame: window.top === window ? 'top' : location.href, teams: teams(), hidden: document.hidden, ...r });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
    return false;
  });

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
