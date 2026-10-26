// Read only small local alerts. Never fetch bank data or reload unsaved forms.
(() => {
    const panel = document.getElementById('amex-interest-alert');
    if (!panel) return;
    let busy = false;
    let lastBalanceState = '';
    async function poll() {
        if (busy || document.hidden) return;
        busy = true;
        try {
            const response = await fetch(panel.dataset.statusUrl, {
                cache: 'no-store',
                signal: AbortSignal.timeout(8000)
            });
            if (!response.ok) return;
            const state = await response.json();
            const charges = state.charges || [];
            const balancePanel = document.getElementById('amex-balance-alert');
            const balanceKey = JSON.stringify(state.balance);
            if (balancePanel && state.balance && balanceKey !== lastBalanceState) {
                const balance = state.balance;
                balancePanel.hidden = !balance.show;
                balancePanel.dataset.level = balance.level;
                for (const [id, value] of [
                        ['title', balance.title],
                        ['amount', balance.amount_text],
                        ['threshold', balance.threshold_text],
                        ['message', balance.message],
                        ['checked', balance.checked]
                    ]) {
                    document.getElementById('amex-balance-' + id).textContent = value;
                }
                lastBalanceState = balanceKey;
            }

            const protection = document.getElementById('amex-protection-alert');
            if (protection && state.protection) {
                protection.hidden = !state.protection.length;
                document.getElementById('amex-protection-warnings').replaceChildren(...state.protection.map(text => {
                    const li = document.createElement('li');
                    li.textContent = text;
                    return li;
                }));
            }
            panel.hidden = !charges.length && !state.error;
            document.getElementById('amex-interest-error').textContent = state.error || '';
            document.getElementById('amex-interest-charges').replaceChildren(...charges.map(row => {
                const li = document.createElement('li');
                li.textContent = `${row.date}: ${row.currency === 'GBP' ? '£' : row.currency + ' '}${row.amount} interest charged`;
                return li;
            }));
            document.getElementById('amex-interest-ids').replaceChildren(...charges.map(row => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'charge_id';
                input.value = row.id;
                return input;
            }));
            document.getElementById('amex-interest-acknowledge').hidden = !charges.length;
        } catch (_) {
            /* Retain the last warning when the local server is unavailable. */ } finally {
            busy = false;
        }
    }
    setInterval(poll, 10000);
    document.addEventListener('visibilitychange', poll);
    poll();
})();
