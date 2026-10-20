// Which Dolly environments the extension reads our prices from. Test (UAT) is on by default.
// Prod is opt-in: the extension has no permission for prod until the user ticks it in Settings
// (Chrome asks), and the reader is only loaded into the ticked environments' pages (background.js).
// Both can be on at once: each is its own column ("Ours UAT" / "Ours Prod") so the two can be compared.
export const DOLLY_ENVS = {
  test: { key: 'test', book: 'OURS', label: 'UAT', name: 'Test (UAT)', origin: 'https://dolly.uat.oddsfactorytrading.bet/*' },
  prod: { key: 'prod', book: 'PROD', label: 'PROD', name: 'Prod', origin: 'https://dolly.1.oddsfactorytrading.com/*' },
};
// settings from before 0.22 had one choice, dollyEnv 'test' | 'prod'
export const envOn = (settings, key) => {
  const v = settings?.[key === 'prod' ? 'dollyProd' : 'dollyTest'];
  if (typeof v === 'boolean') return v;
  return (settings?.dollyEnv === 'prod') === (key === 'prod');
};
export const activeEnvs = (settings) => Object.values(DOLLY_ENVS).filter(e => envOn(settings, e.key));
export const envOfBook = (book) => Object.values(DOLLY_ENVS).find(e => e.book === book);
