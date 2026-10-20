// Run: node --test prop-compare/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseFdGames, parseFdQuotes, parseDkQuotes, parseDkGames, decimalFromAmerican } from '../extension/lib/books.js';
import { alignTick, buildRows, tickToRecords, toCsv, CSV_HEADERS, oddsScale, oddsLabel } from '../extension/lib/compare.js';
import { playerMatch, sameGame, tokenScore } from '../extension/lib/match.js';

const fx = (n) => JSON.parse(fs.readFileSync(new URL(`./fixtures/${n}`, import.meta.url)));

test('FD slate (real response): NBA + preseason games only; futures and eBasketball dropped', () => {
  const g = parseFdGames(fx('fd_slate.json'));
  assert.deepEqual(g.map(x => x.name), ['Boston Celtics @ Philadelphia 76ers', 'Toronto Raptors @ Detroit Pistons',
    'Boston Celtics @ Detroit Pistons', 'Philadelphia 76ers @ New York Knicks']);
  assert.ok(g.every(x => /^NBA/.test(x.competition)));
});

test('FD player-points tab (real response): O/U both sides + alt lines, no game markets', () => {
  const q = parseFdQuotes(Object.values(fx('fd_points_tab.json').attachments.markets));
  const cade = q.filter(x => x.player === 'Cade Cunningham' && x.kind === 'ou');
  assert.deepEqual(cade.map(x => [x.side, x.line, x.american]), [['over', 24.5, '-106'], ['under', 24.5, '-125']]);
  const alt = q.filter(x => x.kind === 'alt');
  assert.ok(alt.length >= 10);
  assert.ok(alt.every(x => x.side === 'over' && x.line % 1 === 0.5));
  assert.ok(q.some(x => x.player === 'Jayson Tatum' && x.kind === 'alt' && x.line === 39.5 && x.american === '+800'));
  assert.ok(!q.some(x => /celtics|pistons|over|under/i.test(x.player)), 'game lines must not leak in');
});

test('DK parser (synthetic shape): points only, suspended skipped, unicode minus', () => {
  const q = parseDkQuotes(fx('dk_points_synthetic.json'));
  assert.equal(q.length, 6);
  assert.deepEqual(q.find(x => x.player === 'Cade Cunningham' && x.side === 'under'), { book: 'DK', player: 'Cade Cunningham', kind: 'ou', line: 24.5, side: 'under', american: '-120', decimal: decimalFromAmerican(-120) });
  assert.ok(q.some(x => x.player === 'Jayson Tatum' && x.kind === 'alt' && x.line === 39.5));
  assert.ok(!q.some(x => x.line === 44.5), 'suspended 45+ must be skipped');
  assert.ok(!q.some(x => x.line === 6.5), 'rebounds must be skipped');
});

test('DK games', () => {
  const g = parseDkGames({ events: [{ id: 1, startEventDate: '2026-10-21T23:30:00Z', participants: [{ name: 'BOS Celtics', venueRole: 'Away' }, { name: 'NY Knicks', venueRole: 'Home' }] }] });
  assert.equal(g[0].name, 'BOS Celtics @ NY Knicks');
  assert.ok(sameGame([g[0].away, g[0].home], ['Boston Celtics', 'New York Knicks']));
  assert.ok(!sameGame([g[0].home, g[0].away], ['Boston Celtics', 'New York Knicks']));
  assert.ok(sameGame(['POR Trail Blazers', 'LA Lakers'], ['Portland Trail Blazers', 'Los Angeles Lakers']));
});

test('player matching', () => {
  assert.ok(playerMatch('Nikola Jokić', 'Nikola Jokic'));
  assert.ok(playerMatch('Jaren Jackson Jr.', 'Jaren Jackson'));
  assert.ok(playerMatch('S. Gilgeous-Alexander', 'Shai Gilgeous-Alexander'));
  assert.ok(!playerMatch('Jalen Williams', 'Jaylin Williams'));
});

test('alignment: late or failed book is left out, never mixed in', () => {
  assert.equal(alignTick({ DK: { ok: true, at: 1000 }, FD: { ok: true, at: 2500 } }, 2000, ['DK', 'FD']).aligned, true);
  assert.equal(alignTick({ DK: { ok: true, at: 1000 }, FD: { ok: true, at: 2500 } }, 2000).aligned, false, 'ours expected but missing');
  const three = alignTick({ DK: { ok: true, at: 1000 }, FD: { ok: true, at: 1200 }, OURS: { ok: true, at: 1900 } }, 2000, ['DK', 'FD', 'OURS']);
  assert.deepEqual([three.aligned, three.spreadMs], [true, 900]);
  const late = alignTick({ DK: { ok: true, at: 1000 }, FD: { ok: true, at: 3500 } }, 2000, ['DK', 'FD']);
  assert.deepEqual([late.aligned, late.used.DK, late.used.FD, late.spreadMs], [false, true, false, 2500]);
  const fail = alignTick({ DK: { ok: false }, FD: { ok: true, at: 1 } }, 2000, ['DK', 'FD']);
  assert.deepEqual([fail.aligned, fail.used.DK, fail.used.FD], [false, false, true]);
});

test('rows line up DK, FD and ours by player + line; CSV is odds only', () => {
  const FD = parseFdQuotes(Object.values(fx('fd_points_tab.json').attachments.markets));
  const DK = parseDkQuotes(fx('dk_points_synthetic.json'));
  const OURS = [{ book: 'OURS', player: 'Cade Cunningham', kind: 'ou', line: 24.5, side: 'over', american: '-104', decimal: 1.961 },
                { book: 'OURS', player: 'CADE CUNNINGHAM', kind: 'alt', line: 39.5, side: 'over', american: '+1100', decimal: 12 }];
  const rows = buildRows({ DK, FD, OURS });
  const cade = rows.find(r => r.player === 'Cade Cunningham' && r.kind === 'ou' && r.line === 24.5);
  assert.deepEqual([cade.books.DK.over.american, cade.books.FD.over.american, cade.books.OURS.over.american], ['-110', '-106', '-104']);
  assert.ok(rows.find(r => r.kind === 'alt' && r.line === 39.5 && r.player === 'Cade Cunningham').books.OURS, 'upper-case Dolly name matches');
  assert.equal(cade.diff, 6);   // ours -104 vs DK -110 = 6 cents (vs FD -106 = 2)
  assert.equal(oddsScale('+110') - oddsScale('-110'), 20);
  assert.equal(oddsLabel(oddsScale('-104')), '-104'); assert.equal(oddsLabel(oddsScale('+250')), '+250');
  const tick = { id: 7, t: Date.UTC(2026, 9, 21, 23, 30), game: 'Boston Celtics @ Detroit Pistons', aligned: true, spreadMs: 120,
    used: { DK: true, FD: true, OURS: true }, at: { DK: 1, FD: 1, OURS: 1 }, rows };
  const recs = tickToRecords(tick);
  assert.ok(recs.every(r => r.length === CSV_HEADERS.length));
  assert.ok(!CSV_HEADERS.some(h => /prob|gap|of_/.test(h)));
  assert.match(toCsv(recs), /Cade Cunningham,Points O\/U 24.5,24.5,-110,-120,[^,]*,-106,-125,[^,]*,-104,/);
});

test('MLB suite team matching (tokenScore) on NBA names', () => {
  assert.equal(tokenScore('Boston Celtics', 'BOS Celtics'), 1);
  assert.equal(tokenScore('Los Angeles Lakers', 'LA Clippers'), 0);
  assert.equal(tokenScore('Portland Trail Blazers', 'Trail Blazers'), 1);
});

test('anomalies: ours vs DK/FD by payout (profit on a $1 win); a new row every pull', async () => {
  const { findAnomalies, anomalyRows, payout, americanFromPayout } = await import('../extension/lib/anomaly.js');
  assert.ok(Math.abs(payout('-225') - 0.4444) < 1e-4); assert.equal(payout('+150'), 1.5);
  assert.equal(americanFromPayout(0.4444444), '-225'); assert.equal(americanFromPayout(1.5), '+150');
  const row = (ours, dk, fd) => ({ key: 'tatum|alt|24.5', player: 'Jayson Tatum', kind: 'alt', line: 24.5,
    books: { OURS: { over: { american: ours } }, ...(dk ? { DK: { over: { american: dk } } } : {}), ...(fd ? { FD: { over: { american: fd } } } : {}) } });
  assert.equal(findAnomalies([row('-110', '-112', '-108')], 10, 20).length, 0);        // normal spread: fine
  // the user's case: -225 vs FD -5000 is not "29% off": we pay 22x as much
  const fav = findAnomalies([row('-225', null, '-5000')], 10, 20)[0];
  assert.ok(fav && Math.round(fav.pctFd) === 2122 && fav.why === '20%+ off FD');
  const a = findAnomalies([row('+120', '-178', '-174')], 10, 20)[0];                 // we pay 1.20 vs avg 0.57
  assert.ok(a.pct > 110 && a.pct < 112 && a.avg === '-176', JSON.stringify(a));
  // one book way off on a pull: the average can look fine while one book alone is 20%+ away
  const one = findAnomalies([row('-150', '-115', '-175')], 10, 20)[0];               // ours 0.667 vs avg 0.72 (-7%), DK 0.87 (-23%)
  assert.ok(one && Math.abs(one.pct) < 10 && one.pctDk < -20 && one.why === '20%+ off DK', JSON.stringify(one));
  // a log: every pull adds a row for each side that is off, with that pull's time and prices
  const t = (id) => ({ gameKey: 'g', game: 'BOS @ DET', id, t: id * 15000, aligned: true });
  const log = [];
  for (const [id, ours] of [[1, '+120'], [2, '+150'], [3, '-170']]) log.push(...anomalyRows(findAnomalies([row(ours, '-178', '-174')], 10, 20), t(id)));
  assert.deepEqual(log.map(e => [e.tickId, e.t, e.ours, e.dk, e.fd]), [[1, 15000, '+120', '-178', '-174'], [2, 30000, '+150', '-178', '-174']]);
  assert.equal(new Set(log.map(e => e.id)).size, 2);
});

test('UAT and Prod side by side: own columns, UAT-vs-Prod gap, anomalies per Dolly, old setting kept', async () => {
  const { findAnomalies, anomalyRows } = await import('../extension/lib/anomaly.js');
  const { envOn, activeEnvs } = await import('../extension/lib/dolly-env.js');
  const q = (book, american) => ({ book, player: 'Cade Cunningham', kind: 'ou', line: 24.5, side: 'over', american, decimal: decimalFromAmerican(american) });
  const rows = buildRows({ DK: [q('DK', '-110')], FD: [q('FD', '-110')], OURS: [q('OURS', '-110')], PROD: [q('PROD', '+150')] });
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].books.OURS.over.american, rows[0].books.PROD.over.american], ['-110', '+150']);
  assert.equal(rows[0].envDiff, 60);   // -110 -> -10, +150 -> +50
  const tick = { gameKey: 'g', game: 'A @ B', id: 1, t: 0, aligned: true, used: { DK: true, FD: true, OURS: true, PROD: true }, at: {}, rows };
  const rec = tickToRecords(tick);
  assert.equal(rec[0].length, CSV_HEADERS.length);
  assert.deepEqual(rec[0].slice(-6, -4), ['-110', '']);
  assert.deepEqual(rec[0].slice(-3, -1), ['+150', '']);
  assert.equal(findAnomalies(rows, 10, 20, 'OURS').length, 0, 'UAT matches the books');
  const prod = anomalyRows(findAnomalies(rows, 10, 20, 'PROD'), tick);
  assert.equal(prod.length, 1); assert.equal(prod[0].env, 'prod'); assert.match(prod[0].id, /\|prod$/);
  // settings
  assert.deepEqual(activeEnvs({}).map(e => e.key), ['test']);
  assert.deepEqual(activeEnvs({ dollyEnv: 'prod' }).map(e => e.key), ['prod']);
  assert.deepEqual(activeEnvs({ dollyTest: true, dollyProd: true }).map(e => e.key), ['test', 'prod']);
  assert.equal(envOn({ dollyTest: false, dollyProd: false }, 'test'), false);
});
