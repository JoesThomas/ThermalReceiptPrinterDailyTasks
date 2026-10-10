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

function updateScenarioFields() {
    const form = document.getElementById('test-finance-form');
    if (!form) return;
    const lump = form.elements.mode.value === 'lump';
    const hasLump = lump || form.elements.mode.value === 'lump_income';
    for (const name of ['salary', 'existing_salary', 'other_income', 'savings_target', 'save_all']) {
        form.elements[name].disabled = lump;
        form.elements[name].closest('label').hidden = lump;
    }
    form.elements.lump_sum.disabled = !hasLump;
    form.elements.lump_sum.required = hasLump;
    form.elements.lump_sum.closest('label').hidden = !hasLump;
}
document.querySelector('#test-finance-form select[name="mode"]')?.addEventListener('change', updateScenarioFields);
window.addEventListener('pageshow', updateScenarioFields);
updateScenarioFields();
