(() => {
  const main = document.querySelector('main');
  if (main) main.id = 'main-content';
  // Native disclosures keep editing available without a large wall of form fields.
  document.querySelectorAll('.instalment').forEach(row => {
    if (row.closest('details.editor-disclosure')) return;
    const name = row.querySelector('[name="name"]')?.value || row.querySelector('h3')?.textContent.trim();
    if (!name || !row.querySelector('input:not([type="hidden"])')) return;
    const details = document.createElement('details');
    details.className = 'editor-disclosure';
    const summary = document.createElement('summary');
    const title = document.createElement('strong');
    title.textContent = name;
    summary.append(title);
    const amount = row.querySelector('[name="amount"]')?.value;
    const hint = document.createElement('span');
    hint.textContent = amount && Number.isFinite(Number(amount)) ?
      new Intl.NumberFormat('en-GB', {style:'currency',currency:'GBP'}).format(amount) + ' · Edit' : 'Edit details';
    summary.append(hint);
    details.append(summary);
    row.replaceWith(details);
    details.append(row);
  });
  // Reduce visual noise in the large receipt-settings form without dropping fields.
  if (document.body.dataset.controlView) {
    document.querySelectorAll('section').forEach(section => {
      const heading = section.querySelector(':scope > h2');
      if (!heading || section.closest('#overview') || section.closest('#live-data')) return;
      const names = ['Therapy payment reminder','Salary identification','Receipt location','Output'];
      const collapse = names.includes(heading.textContent.trim()) ||
        (document.body.dataset.controlView === 'settings' && ['Next receipt','Daily receipt'].includes(heading.textContent.trim()));
      if (!collapse) return;
      const details = document.createElement('details');
      details.className = 'section-disclosure';
      if (document.body.dataset.controlView === 'settings' && ['Receipt location'].includes(heading.textContent.trim())) details.open = true;
      const summary = document.createElement('summary');
      summary.textContent = heading.textContent;
      heading.remove();
      const nodes = [...section.childNodes];
      details.append(summary, ...nodes);
      section.append(details);
    });
  }
  // Existing bookmarked anchors still lead to the appropriate focused view.
  const routes = {'routines':'tasks','food-shop':'tasks','to-buy':'tasks','future-tasks':'tasks','instalments':'accounts','commitments':'accounts','annual-subscriptions':'accounts','printing':'settings','next-receipt':'receipt','daily-receipt':'receipt'};
  const anchor = location.hash.slice(1);
  const view = routes[anchor];
  if (document.body.dataset.controlView && view && view !== document.body.dataset.controlView) {
    const url = new URL(location.href); url.searchParams.set('view',view); location.replace(url);
  }
  document.querySelectorAll('form').forEach(form => form.addEventListener('invalid',event => {
    let parent = event.target.parentElement;
    while (parent) { if (parent.tagName === 'DETAILS') parent.open = true; parent = parent.parentElement; }
  },true));
})();

(() => {
  const panel = document.getElementById('global-job-panel');
  if (!panel) return;
  let busy = false;
  let wasActive = false;
  async function poll() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch(panel.dataset.statusUrl, {cache:'no-store', signal:AbortSignal.timeout(8000)});
      if (!response.ok) throw new Error('status unavailable');
      const jobs = await response.json();
      const kind = jobs.print?.state === 'running' ? 'print' : jobs.preview?.state === 'running' ? 'preview' : null;
      panel.hidden = !kind;
      if (!kind) {
        if (wasActive) location.reload();
        return;
      }
      wasActive = true;
      const job = jobs[kind];
      document.getElementById('global-job-kind').value = kind;
      document.getElementById('global-job-title').textContent = kind === 'print' ? 'Printing your receipt' : 'Building your preview';
      document.getElementById('global-job-stage').textContent = job.stage || 'Starting…';
      const done = Math.max(0, Math.min(5, Number(job.completed) || 0));
      document.getElementById('global-job-progress').value = done;
      const start = Date.parse(job.started_at || job.updated_at);
      const seconds = Number.isFinite(start) ? Math.max(0, Math.floor((Date.now()-start)/1000)) : 0;
      document.getElementById('global-job-time').textContent = `${done}/5 sections · ${Math.floor(seconds/60)}m ${seconds%60}s elapsed · Job ${job.job_id || 'earlier job'}`;
      document.querySelectorAll('form[action$="/print-page"], form[action$="/print-now"], form[action$="/preview/generate"]').forEach(form => {
        form.querySelectorAll('button[type="submit"],button:not([type])').forEach(button => button.disabled = true);
      });
    } catch (_) {
      if (wasActive) document.getElementById('global-job-stage').textContent = 'Reconnecting to job updates…';
    } finally { busy = false; }
  }
  poll(); setInterval(poll, 2000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
})();

// Give slow review pages immediate feedback without trapping browser back navigation.
(() => {
  const notice = document.createElement('div');
  notice.className = 'navigation-loading'; notice.hidden = true;
  notice.setAttribute('role','status');
  const spinner = document.createElement('span'); spinner.className='preview-spinner'; spinner.setAttribute('aria-hidden','true');
  const text = document.createElement('span'); text.textContent='Loading your review…';
  notice.append(spinner,text); document.body.append(notice);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target || event.button !== 0) return;
    const url = new URL(link.href);
    if (url.origin === location.origin && ['/finance-review','savings-review','gigs','meals','calendar-map'].includes(url.pathname)) {
      notice.hidden=false;
      setTimeout(() => { notice.hidden=true; },15000);
    }
  });
  window.addEventListener('pageshow', () => { notice.hidden=true; });
})();
