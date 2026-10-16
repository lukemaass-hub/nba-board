// Every tick is saved in IndexedDB (browser storage that survives restarts), so an export
// covers the whole session, not just what's on screen.
const DB = 'prop-compare', STORE = 'ticks';

function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => {
      const s = req.result.createObjectStore(STORE, { keyPath: ['gameKey', 'id'] });
      s.createIndex('gameKey', 'gameKey');
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
