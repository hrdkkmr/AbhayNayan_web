const DB_NAME = 'abhaynayan-demo';
const DB_VERSION = 2;
let dbPromise;

function openDb() {
  if (!('indexedDB' in globalThis)) return Promise.resolve(null);
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('patients')) db.createObjectStore('patients', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('screenings')) db.createObjectStore('screenings', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('syncQueue')) db.createObjectStore('syncQueue', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('settings')) db.createObjectStore('settings', { keyPath: 'key' });
        if (!db.objectStoreNames.contains('referrals')) db.createObjectStore('referrals', { keyPath: 'id' });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('Local database could not be opened.'));
    });
  }
  return dbPromise;
}

function fallbackRead(store) {
  try { return JSON.parse(localStorage.getItem(`abn_${store}`) || '[]'); }
  catch { return []; }
}

function fallbackWrite(store, rows) {
  localStorage.setItem(`abn_${store}`, JSON.stringify(rows));
}

export async function getAll(store) {
  const db = await openDb().catch(() => null);
  if (!db) return fallbackRead(store);
  return new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readonly').objectStore(store).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

export async function getOne(store, key) {
  const db = await openDb().catch(() => null);
  if (!db) return fallbackRead(store).find((item) => item.id === key || item.key === key) || null;
  return new Promise((resolve, reject) => {
    const request = db.transaction(store, 'readonly').objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

export async function put(store, record) {
  const db = await openDb().catch(() => null);
  if (!db) {
    const rows = fallbackRead(store);
    const key = record.id ?? record.key;
    const idx = rows.findIndex((item) => (item.id ?? item.key) === key);
    if (idx >= 0) rows[idx] = record; else rows.push(record);
    fallbackWrite(store, rows);
    return record;
  }
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).put(record);
    tx.oncomplete = () => resolve(record);
    tx.onerror = () => reject(tx.error);
  });
}

export async function remove(store, key) {
  const db = await openDb().catch(() => null);
  if (!db) {
    fallbackWrite(store, fallbackRead(store).filter((item) => (item.id ?? item.key) !== key));
    return;
  }
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, 'readwrite');
    tx.objectStore(store).delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function getSetting(key, fallback = null) {
  const row = await getOne('settings', key);
  return row?.value ?? fallback;
}

export async function setSetting(key, value) {
  return put('settings', { key, value });
}

export async function makePatientId() {
  const date = new Date();
  const year = date.getFullYear();
  const patients = await getAll('patients');
  const next = patients.filter((p) => String(p.id).startsWith(`ABH-${year}-`)).length + 1;
  return `ABH-${year}-${String(next).padStart(4, '0')}`;
}

export async function ensureDemoPatient(kind = 'maternal') {
  const demoKind = kind === 'newborn' ? 'newborn' : 'maternal';
  const patients = await getAll('patients');
  let existing = patients.find((p) => p.isDemo && p.demoKind === demoKind);
  // Migrate the original single-profile prototype record as the maternal fixture.
  if (!existing && demoKind === 'maternal') existing = patients.find((p) => p.isDemo && !p.demoKind);
  if (existing) {
    if (!existing.demoKind) {
      existing.demoKind = 'maternal';
      await put('patients', existing);
    }
    return existing;
  }
  const id = await makePatientId();
  const patient = demoKind === 'newborn'
    ? {
      id, name: 'Demo Newborn', age: 0, sex: 'unknown', pregnancy: false,
      gestationalWeek: null, infantAgeHours: 36, village: 'Demo Village',
      phone: '', consent: true, isDemo: true, demoKind,
      createdAt: new Date().toISOString(),
    }
    : {
      id, name: 'Demo Patient', age: 26, sex: 'female', pregnancy: true,
      gestationalWeek: 28, infantAgeHours: null, village: 'Demo Village',
      phone: '', consent: true, isDemo: true, demoKind,
      createdAt: new Date().toISOString(),
    };
  await put('patients', patient);
  return patient;
}

export async function clearAllLocalData() {
  const db = await openDb().catch(() => null);
  const stores = ['patients', 'screenings', 'syncQueue', 'settings', 'referrals'];
  if (!db) {
    for (const name of stores) localStorage.removeItem(`abn_${name}`);
    return;
  }
  await new Promise((resolve, reject) => {
    const tx = db.transaction(stores, 'readwrite');
    for (const name of stores) if (db.objectStoreNames.contains(name)) tx.objectStore(name).clear();
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('Local data purge was aborted.'));
  });
}

export async function localStoreStatus() {
  const db = await openDb().catch(() => null);
  return { indexedDb: Boolean(db), fallback: !db, name: DB_NAME };
}
