/**
 * Prop Price Compare: Google Sheet receiver (Apps Script web app).
 * Same pattern as the MLB suite's audit-handler.gs: the extension POSTs rows, this
 * appends them to one tab per game ("2026-10-21 Boston Celtics @ New York Knicks").
 * Access is gated by the deployment's "Who has access: Anyone within betfanatics.com".
 * doPost only appends; it never edits or deletes.
 *
 * SETUP: see prop-compare/README.md, "Google Sheet".
 */
const VERSION = 'prop-compare-1';

function doPost(e) {
  const lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (err) { return json({ ok: false, error: 'busy, try again' }); }
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    const rows = body.rows || [];
    if (!rows.length) return json({ ok: true, added: 0 });
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const name = String(body.tab || 'prop-compare').replace(/[\[\]*\/\\?:]/g, '_').replace(/^'+|'+$/g, '').slice(0, 90);
    let sh = ss.getSheetByName(name);
    if (!sh) { sh = ss.insertSheet(name); }
    if (sh.getLastRow() === 0 && body.headers) { sh.appendRow(body.headers); sh.setFrozenRows(1); }
    const width = Math.max.apply(null, rows.map(function (r) { return r.length; }));
    // "+120" would otherwise be read as the number 120 and lose its sign: keep it as text.
    const padded = rows.map(function (r) {
      const c = r.map(function (v) { return (typeof v === 'string' && /^\+\d/.test(v)) ? "'" + v : v; });
      while (c.length < width) c.push('');
      return c;
    });
    sh.getRange(sh.getLastRow() + 1, 1, padded.length, width).setValues(padded);
    return json({ ok: true, added: padded.length, tab: name });
  } catch (err) {
    return json({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// Opening the /exec URL in a browser is a health check (and the one-time "Allow" step).
function doGet() {
  return json({ ok: true, version: VERSION, serverTime: new Date().toISOString() });
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
