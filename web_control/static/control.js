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
