// Runs in a dedicated Web Worker. Browsers heavily throttle timers on hidden tabs
// (down to once a minute), but not timers inside a worker, so the 15-second tick keeps
// its pace when the dashboard isn't the visible tab.
let timer = null;
self.onmessage = (e) => {
  const { cmd, ms } = e.data || {};
  if (timer) { clearInterval(timer); timer = null; }
  if (cmd === 'start') {
    self.postMessage('tick');                          // first tick right away
    timer = setInterval(() => self.postMessage('tick'), ms);
  }
};
