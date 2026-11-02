'use strict';
(() => {
  const status = document.getElementById('helper-job');
  if (!status || status.dataset.state !== 'running') return;
  let attempts = 0;
  async function poll() {
    try {
      const response = await fetch(status.dataset.url, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('Refresh status unavailable');
      const job = await response.json();
      status.textContent = job.message || 'Refresh status unavailable. Reload this page to check.';
      if (job.state === 'complete') { window.location.reload(); return; }
      if (job.state === 'failed' || !job.state) return;
      if (++attempts < 60) window.setTimeout(poll, 1500);
      else status.textContent = 'Still working. Reload this page to check; do not submit another refresh.';
    } catch (_) { status.textContent = 'Could not check progress. Reload this page to check.'; }
  }
  window.setTimeout(poll, 500);
})();
