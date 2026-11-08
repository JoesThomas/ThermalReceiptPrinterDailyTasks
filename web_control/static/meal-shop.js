(() => {
  const list = document.querySelector('#shop-copy-text');
  const button = document.querySelector('#shop-copy-button');
  if (!list || !button) return;
  const status = document.querySelector('#shop-copy-status');
  const options = Array.from(document.querySelectorAll('[data-shop-amount]'));
  const update = () => {
    list.value = options.filter(item => item.checked).map(item => item.dataset.shopAmount).join('\n');
    button.disabled = !list.value;
    status.textContent = '';
  };
  options.forEach(item => item.addEventListener('change', update));
  button.hidden = false;
  update();
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(list.value);
      status.textContent = 'Shopping list copied.';
    } catch {
      list.focus();
      list.select();
      status.textContent = 'Copy the selected text.';
    }
  });
})();

(() => {
  const mode = document.querySelector('#shop-mode');
  if (!mode) return;
  const key = 'receipt-shop:' + mode.dataset.shopKey;
  const progress = document.querySelector('#shop-progress');
  const boxes = Array.from(mode.querySelectorAll('[data-shop-got]'));
  const selects = new Map(Array.from(mode.querySelectorAll('[data-shop-state]'),
    field => [field.dataset.shopState, field]));
  let states = {};
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) states = saved;
  } catch { /* The list still works when storage is unavailable. */ }
  const update = () => {
    const counts = {got: 0, have: 0, missing: 0, '': 0};
    boxes.forEach(box => {
      const id = box.dataset.shopGot;
      const value = ['got', 'have', 'missing'].includes(states[id]) ? states[id] : '';
      box.checked = value === 'got';
      selects.get(id).value = value === 'got' ? '' : value;
      counts[value]++;
    });
    progress.textContent = `${counts['']} still to get · ${counts.got} got · ${counts.have} already have · ${counts.missing} couldn’t find`;
  };
  const set = (id, value) => {
    if (value) states[id] = value;
    else delete states[id];
    update();
    try {
      localStorage.setItem(key, JSON.stringify(states));
      const lists = Object.keys(localStorage).filter(name => name.startsWith('receipt-shop:'));
      lists.filter(name => name !== key).slice(0, Math.max(0, lists.length - 30))
        .forEach(name => localStorage.removeItem(name));
    } catch { progress.textContent += ' · Progress could not be saved'; }
  };
  boxes.forEach(box => box.addEventListener('change', () => set(box.dataset.shopGot, box.checked ? 'got' : '')));
  selects.forEach((field, id) => field.addEventListener('change', () => set(id, field.value)));
  update();
  mode.hidden = false;
})();
