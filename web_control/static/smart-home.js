// Remove sensitive page content at expiry and when leaving; server expiry is authoritative.
(() => {
    const area = document.getElementById('smart-home-private');
    if (!area?.dataset.expires) return;
    const expires = Number(area.dataset.expires) * 1000;
    const clear = () => area.replaceChildren();
    const check = () => {
        if (Date.now() >= expires) { clear(); location.replace('/smart-home'); }
    };
    setInterval(check, 1000);
    document.addEventListener('visibilitychange', check);
    window.addEventListener('pagehide', clear);
    window.addEventListener('pageshow', event => { if (event.persisted) location.reload(); });
    check();
})();
