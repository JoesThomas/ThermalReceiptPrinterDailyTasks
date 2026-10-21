// Read only small local alerts. Never fetch bank data or reload unsaved forms.
(() => {
  const panel = document.getElementById('amex-interest-alert');
  if (!panel) return;
  let busy = false;
  async function poll() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(panel.dataset.statusUrl, {cache: 'no-store', signal: AbortSignal.timeout(8000)});
      if (!response.ok) return;
      const state = await response.json();
      const charges = state.charges || [];
      panel.hidden = !charges.length && !state.error;
      document.getElementById('amex-interest-error').textContent = state.error || '';
      document.getElementById('amex-interest-charges').replaceChildren(...charges.map(row => {
        const li = document.createElement('li');
        li.textContent = `${row.date}: ${row.currency === 'GBP' ? '£' : row.currency + ' '}${row.amount} interest charged`;
        return li;
      }));
      document.getElementById('amex-interest-ids').replaceChildren(...charges.map(row => {
        const input = document.createElement('input');
        input.type = 'hidden'; input.name = 'charge_id'; input.value = row.id;
        return input;
      }));
      document.getElementById('amex-interest-acknowledge').hidden = !charges.length;
    } catch (_) { /* Retain the last warning when the local server is unavailable. */ }
    finally { busy = false; }
  }
  setInterval(poll, 10000);
  document.addEventListener('visibilitychange', poll);
  poll();
})();
