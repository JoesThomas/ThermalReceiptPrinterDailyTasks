// No chart library or external requests: the server supplies the same forecast values.
document.addEventListener('change', event => {
  const id=event.target.dataset.chartSeries;
  if (!id) return;
  const line=document.getElementById(id);
  if (line) line.style.display=event.target.checked ? '' : 'none';
});
