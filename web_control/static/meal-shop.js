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
