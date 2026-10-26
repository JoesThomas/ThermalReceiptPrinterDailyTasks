(() => {
    'use strict';
    const form = document.getElementById('long-term-form');
    if (!form) return;

    function choices() {
        const rows = [...form.querySelectorAll('[data-plan-row="account"]')].map(r => ({
            id: r.querySelector('[name=a_id]').value,
            name: r.querySelector('[name=a_name]').value,
            kind: r.querySelector('[name=a_kind]').value
        }));
        form.querySelectorAll('select[data-account-options]').forEach(select => {
            const old = select.value;
            select.replaceChildren();
            if (select.hasAttribute('data-payout')) {
                for (const [id, name] of [
                        ['self', 'Reinvest in this account'],
                        ['bank', 'Separate assumed payout cash']
                    ]) select.add(new Option(name, id));
            }
            for (const row of rows) {
                if (select.hasAttribute('data-payout') && ['debt', 'property', 'pension'].includes(row.kind)) continue;
                select.add(new Option(row.name, row.id));
            }
            if ([...select.options].some(o => o.value === old)) select.value = old;
            else if (old) {
                select.add(new Option('Removed account — choose again', old));
                select.value = old;
            }
        });
    }
    form.addEventListener('click', event => {
        const add = event.target.closest('[data-add]');
        if (add) {
            const type = add.dataset.add;
            const fragment = document.getElementById(`long-${type}-template`).content.cloneNode(true);
            if (type !== 'account') fragment.querySelector('input[type=date]').value = form.querySelector('[name=start]').value;
            if (type === 'account') fragment.querySelector('[name=a_id]').value = [...crypto.getRandomValues(new Uint8Array(6))].map(v => v.toString(16).padStart(2, '0')).join('');
            document.getElementById(type === 'account' ? 'long-accounts' : type === 'event' ? 'long-events' : 'long-goals').append(fragment);
            choices();
            return;
        }
        const remove = event.target.closest('[data-remove-row]');
        if (remove) {
            remove.closest('[data-plan-row]').remove();
            choices();
        }
    });
    form.addEventListener('change', event => {
        if (['a_name', 'a_kind'].includes(event.target.name)) {
            if (event.target.name === 'a_kind' && ['bank', 'cash', 'pension', 'property', 'debt'].includes(event.target.value)) event.target.closest('[data-plan-row]').querySelector('[name=a_extra]').value = 'no';
            choices();
        }
    });
    form.addEventListener('submit', () => {
        document.getElementById('long-status').hidden = false;
    });
})();
