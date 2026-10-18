// Every tick is saved in IndexedDB (browser storage that survives restarts), so an export
// covers the whole session, not just what's on screen.
const DB = 'prop-compare', STORE = 'ticks', ANOM = 'anomalies';

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 2);
    req.onupgradeneeded = (ev) => {
      const db = req.result;
      if (ev.oldVersion < 1) db.createObjectStore(STORE, { keyPath: ['gameKey', 'id'] }).createIndex('gameKey', 'gameKey');
      // v2: anomaly episodes (lib/anomaly.js), one record per side per stretch of being off the market
      if (ev.oldVersion < 2) db.createObjectStore(ANOM, { keyPath: 'id' }).createIndex('gameKey', 'gameKey');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
const dbp = open();

export async function saveTick(tick) {
  const db = await dbp;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put(tick);
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
}

export async function ticksFor(gameKey) {
  const db = await dbp;
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE).objectStore(STORE).index('gameKey').getAll(gameKey);
    req.onsuccess = () => resolve(req.result.sort((a, b) => a.id - b.id));
    req.onerror = () => reject(req.error);
  });
}

export async function gamesStored() {
  const db = await dbp;
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE).objectStore(STORE).index('gameKey').openKeyCursor(null, 'nextunique');
    const out = [];
    req.onsuccess = () => { const c = req.result; if (c) { out.push(c.key); c.continue(); } else resolve(out); };
    req.onerror = () => reject(req.error);
  });
}

export async function clearGame(gameKey) {
  const db = await dbp;
  const ticks = await ticksFor(gameKey);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    for (const t of ticks) tx.objectStore(STORE).delete([gameKey, t.id]);
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
}

export async function saveAnomalies(list) {
  if (!list.length) return;
  const db = await dbp;
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ANOM, 'readwrite');
    for (const e of list) tx.objectStore(ANOM).put({ ...e, id: `${e.gameKey}|${e.key}|${e.startT}` });
    tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
  });
}

export async function anomaliesFor(gameKey) {
  const db = await dbp;
  return new Promise((resolve, reject) => {
    const req = db.transaction(ANOM).objectStore(ANOM).index('gameKey').getAll(gameKey);
    req.onsuccess = () => resolve(req.result.sort((a, b) => b.startT - a.startT));
    req.onerror = () => reject(req.error);
  });
}
