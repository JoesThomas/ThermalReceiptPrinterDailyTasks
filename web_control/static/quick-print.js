(() => {
  const text = document.querySelector('#quick-note');
  const count = document.querySelector('#quick-note-count');
  const advice = document.querySelector('#quick-note-advice');
  if (!text || !count || !advice) return;
  const update = () => {
    const length = text.value.length;
    count.textContent = length.toLocaleString() + ' / ' + text.maxLength.toLocaleString() + ' characters';
    advice.textContent = length > text.maxLength
      ? 'Your draft exceeds the current limit. Shorten it or increase the limit in Quick Print settings.'
      : length > 2000
        ? 'Long note: preview the layout and consider printing only key points or splitting it into shorter notes.'
        : '';
  };
  text.addEventListener('input', update);
  update();
})();
