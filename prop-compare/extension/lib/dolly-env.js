// Which Dolly the extension reads our prices from. Test (UAT) is the default. Prod is opt-in:
// the extension has no permission for prod until the user picks it in Settings (Chrome asks),
// and the reader is only loaded into the selected environment's pages (background.js).
export const DOLLY_ENVS = {
  test: { label: 'TEST', name: 'Test (UAT)', origin: 'https://dolly.uat.oddsfactorytrading.bet/*' },
  prod: { label: 'PROD', name: 'Prod', origin: 'https://dolly.1.oddsfactorytrading.com/*' },
};
export const dollyEnv = (settings) => (settings?.dollyEnv === 'prod' ? 'prod' : 'test');
