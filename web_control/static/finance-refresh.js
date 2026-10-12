// Poll only local job metadata; bank requests run once in the server worker.
(() => {
  const panel = document.getElementById('finance-refresh');
  if (!panel) return;
  const form = document.getElementById('finance-refresh-form');
  const button = form.querySelector('button');
  const stage = document.getElementById('finance-refresh-stage');
  const detail = document.getElementById('finance-refresh-detail');
  const timings = document.getElementById('finance-refresh-timings');
  let dirty = false;
  let pending = false;
  const newData = document.getElementById('finance-new-data');
  const apply = document.getElementById('finance-apply-data');
  document.addEventListener('input', event => {
    if (event.target.closest('form') && !event.target.closest('#finance-refresh-form')) dirty = true;
  });
  document.addEventListener('change', event => {
    if (event.target.closest('form') && !event.target.closest('#finance-refresh-form')) dirty = true;
  });
  document.addEventListener('submit', event => {
    queueMicrotask(() => { if (!event.defaultPrevented) dirty = false; });
  });
  const updateReview = () => {
    if (!dirty) { location.reload(); return; }
    pending = true; active = false; button.disabled = false;
    newData.hidden = false;
  };
  apply.addEventListener('click', () => { dirty = false; location.reload(); });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  let busy = false;
  let active = panel.dataset.state === 'running';
  let timer;
  function display(job) {
    active = job.state === 'running';
    button.disabled = active;
    stage.textContent = job.stage || 'Waiting for bank retrieval';
    timings.replaceChildren(...(job.timings || []).map(row => {
      const li = document.createElement('li');
      li.textContent = `${row.stage} · ${Number(row.seconds).toFixed(1)}s`;
      return li;
    }));
    if (job.state === 'failed') {
      if (panel.dataset.state !== 'failed') {
        if (dirty) {
          detail.textContent = 'Bank refresh failed. Forecasts are withheld while your unsaved edits are kept.';
          document.querySelectorAll('[data-bank-forecast]').forEach(node => node.hidden = true);
        }
        updateReview(); return;
      }
      detail.textContent = panel.dataset.snapshot
        ? 'Showing a previous bank check. Forecasts are withheld until fresh, complete bank data is available. You can try again.'
        : 'No successful bank snapshot yet. Check bank connections and try again.';
    }
    if (job.checked_at && job.checked_at !== panel.dataset.snapshot) {
      // Reload only when a new snapshot is available; failed jobs retain the old one.
      updateReview();
    }
  }
  async function poll() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(panel.dataset.statusUrl, {cache:'no-store', signal:AbortSignal.timeout(8000)});
      if (response.redirected || response.status === 401 || response.status === 403) {
        active = false; button.disabled = false;
        stage.textContent = 'Sign in again to retrieve bank data.';
        return;
      }
      if (!response.ok) throw new Error('Status unavailable');
      display(await response.json());
    } catch (_) {
      stage.textContent = 'Retrieval status temporarily unavailable. Refresh the page to check again.';
      button.disabled = false;
    } finally {
      busy = false;
      clearTimeout(timer);
      if (active && !pending) timer = setTimeout(poll, 2000);
    }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (button.disabled) return;
    button.disabled = true; active = true;
    stage.textContent = 'Starting bank retrieval…';
    try {
      const response = await fetch(form.action, {method:'POST', body:new FormData(form),
        headers:{Accept:'application/json'}, signal:AbortSignal.timeout(8000)});
      if (!response.ok || response.redirected) throw new Error('Refresh unavailable');
      display(await response.json());
      poll();
    } catch (_) {
      active = false; button.disabled = false;
      stage.textContent = 'Could not start refresh. Reload the page or try again.';
    }
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  document.addEventListener('visibilitychange', () => { if (!document.hidden && active) poll(); });
  poll();
})();
