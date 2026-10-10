document.getElementById('test-finance-form')?.addEventListener('submit', function () {
    document.getElementById('test-finance-loading').hidden = false;
    const button = this.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = 'Generating test receipt…';
    this.setAttribute('aria-busy', 'true');
});
window.addEventListener('pageshow', () => {
    const form = document.getElementById('test-finance-form');
    if (!form) return;
    form.removeAttribute('aria-busy');
    document.getElementById('test-finance-loading').hidden = true;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = false;
    button.textContent = 'Generate test receipt';
});
