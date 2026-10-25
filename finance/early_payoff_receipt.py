"""Render recorded settlements; never recalculate payment amounts."""

def overview(page, forecast, inputs, detailed=False):
    if not inputs.get('early_payoff'):
        return
    page.section('EARLY INSTALMENT PAYOFFS')
    if forecast.get('early_payoff_warning'):
        page.text(forecast['early_payoff_warning'])
        return
    entries = forecast.get('early_payoffs', [])
    if not entries:
        page.text('No selected plan can be settled early within the available allocation. Normal payments continue.')
    else:
        page.amount('Early settlements over forecast', forecast['early_payoff_total'])
    for item in entries if detailed else entries[:3]:
        page.amount(f"{item['date']:%d %b %Y} {item['name']}", item['amount'])
        if detailed:
            page.amount('Replaces bills in that period', item['scheduled_replaced'])
            page.amount('Extra above those bills', item['extra'])
    if not detailed and len(entries) > 3:
        page.text(f'{len(entries) - 3} more settlements shown on the webpage.')
    if entries:
        page.text('Replaced instalments removed from bills. Confirm settlement figures and scheduled collections with the provider; plan only.')
    if detailed:
        for row in forecast.get('instalment_balances', []):
            page.amount(row['name'] + ' owed at end', row['remaining'])
