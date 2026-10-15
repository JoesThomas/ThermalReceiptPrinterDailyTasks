const scenarioForm = document.getElementById('test-finance-form');
const scenarioButtons = [...(scenarioForm?.querySelectorAll('button[type="submit"]') || [])];
const buttonLabels = scenarioButtons.map(button => button.textContent);
scenarioForm?.addEventListener('submit', function (event) {
    const saving = event.submitter?.getAttribute('formaction')?.endsWith('/scenarios/save');
    const status = document.getElementById('test-finance-loading');
    status.textContent = saving ? 'Saving named scenario inputs…' : 'Checking bank balances and payments, then building your salary simulation…';
    status.hidden = false;
    this.setAttribute('aria-busy', 'true');
    // Keep the submitter enabled until its formaction has been processed.
    setTimeout(() => scenarioButtons.forEach(button => { button.disabled = true; }), 0);
});
window.addEventListener('pageshow', () => {
    if (!scenarioForm) return;
    scenarioForm.removeAttribute('aria-busy');
    document.getElementById('test-finance-loading').hidden = true;
    scenarioButtons.forEach((button, index) => {
        button.disabled = false;
        button.textContent = buttonLabels[index];
    });
});

function updateScenarioFields() {
    const form = document.getElementById('test-finance-form');
    if (!form) return;
    const lump = form.elements.mode.value === 'lump';
    const hasLump = lump || form.elements.mode.value === 'lump_income';
    for (const name of ['salary', 'existing_salary', 'other_income', 'savings_target', 'save_all']) {
        form.elements[name].disabled = lump;
        form.elements[name].closest('label').hidden = lump;
    }
    form.elements.existing_salary.closest('label').hidden = form.elements.mode.value !== 'additional';
    if (form.elements.use_saved_accounts) form.elements.starting_savings.disabled = form.elements.use_saved_accounts.checked;
    if (form.elements.strategy) {
        form.elements.amex_split.closest('label').hidden = form.elements.strategy.value !== 'split';
    }
    const allSurplus = form.elements.save_all.checked;
    form.elements.savings_target.disabled = lump;
    form.elements.savings_target.closest('label').hidden = lump || allSurplus;
    if (form.elements.use_saved_accounts) {
        const saved = form.elements.use_saved_accounts.checked;
        form.elements.starting_savings.closest('label').hidden = saved;
        form.elements.equal_savings.closest('label').hidden = !saved;
    }
    form.elements.lump_sum.disabled = !hasLump;
    form.elements.lump_sum.required = hasLump;
    form.elements.lump_sum.closest('label').hidden = !hasLump;
}
document.querySelector('#test-finance-form select[name="mode"]')?.addEventListener('change', updateScenarioFields);
window.addEventListener('pageshow', updateScenarioFields);
updateScenarioFields();

document.querySelector('#test-finance-form select[name="strategy"]')?.addEventListener('change', updateScenarioFields);

document.querySelector('#test-finance-form input[name="use_saved_accounts"]')?.addEventListener('change', updateScenarioFields);

const compareForm = document.getElementById('scenario-compare-form');
compareForm?.addEventListener('submit', () => {
    document.getElementById('scenario-compare-status').hidden = false;
    compareForm.setAttribute('aria-busy', 'true');
    setTimeout(() => { compareForm.querySelector('button').disabled = true; }, 0);
});
window.addEventListener('pageshow', () => {
    if (!compareForm) return;
    compareForm.querySelector('button').disabled = false;
    compareForm.removeAttribute('aria-busy');
    document.getElementById('scenario-compare-status').hidden = true;
});

scenarioForm?.addEventListener('invalid', event => {
    for (let parent=event.target.parentElement; parent; parent=parent.parentElement) {
        if (parent.tagName==='DETAILS') parent.open=true;
    }
}, true);

document.querySelector('#test-finance-form input[name=save_all]')?.addEventListener('change', updateScenarioFields);
