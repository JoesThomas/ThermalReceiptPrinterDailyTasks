"""Private, bounded 2026/27 estimate for personally owned UK residential lets."""
import json
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from storage import PrivateStore
from finance.money import parse, ZERO
from receipt.local_time import uk_today

FILE = Path(__file__).resolve().parents[1] / 'data' / 'rental_tax.json'
RULES = json.loads(Path(__file__).with_name('tax_rules.json').read_text())
FIELDS = ('other_income', 'rent', 'expenses', 'interest', 'losses', 'finance_carried', 'reserved')
DEFAULT = {'enabled': False, 'protect': False, 'year': '2026/27', 'region': 'England/Wales/NI', 'method': 'expenses', **{key: '' for key in FIELDS}}


def validate(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool or type(value.get('protect')) is not bool:
        raise ValueError('Invalid tax settings')
    if value.get('year') not in RULES or value.get('region') != 'England/Wales/NI' or value.get('method') not in ('expenses', 'allowance'):
        raise ValueError('This estimate supports only 2026/27 and England, Wales or Northern Ireland')
    for key in FIELDS:
        amount = parse(value.get(key))
        if value.get(key) == '' and not value['enabled']: continue
        if amount is None or not ZERO <= amount <= Decimal('100000000'):
            raise ValueError('Enter a non-negative annual amount for ' + key.replace('_', ' '))
    if value['enabled'] and value['method'] == 'allowance' and (parse(value['interest']) or parse(value['finance_carried'])):
        raise ValueError('The property allowance cannot be combined with residential finance-cost relief; choose actual expenses')


def store():
    return PrivateStore(FILE, default=lambda: deepcopy(DEFAULT), validate=validate)


def load():
    return store().read()


def income_tax(income, year="2026/27"):
    rules = RULES[year]
    rate = lambda key: Decimal(rules[key])
    allowance = max(ZERO, rate('personal_allowance') - max(ZERO, income - rate('taper_start')) / 2)
    taxable = max(ZERO, income - allowance)
    basic = min(taxable, rate('basic_width'))
    higher = min(max(ZERO, taxable - basic), rate('higher_width'))
    additional = max(ZERO, taxable - basic - higher)
    return basic * rate('basic_rate') + higher * rate('higher_rate') + additional * rate('additional_rate'), allowance


def estimate(value, today=None):
    validate(value)
    today = today or uk_today()
    if not value['enabled']: return None
    rules = RULES[value['year']]
    start, end = date.fromisoformat(rules['start']), date.fromisoformat(rules['end'])
    if not start <= today <= end: return None
    amounts = {key: parse(value[key]) for key in FIELDS}
    deduction = Decimal(rules['property_allowance']) if value['method'] == 'allowance' else amounts['expenses']
    profit_before_losses = max(ZERO, amounts['rent'] - deduction)
    profit = max(ZERO, profit_before_losses - amounts['losses'])
    total_income = amounts['other_income'] + profit
    combined_tax, allowance = income_tax(total_income, value['year'])
    base_tax, _ = income_tax(amounts['other_income'], value['year'])
    finance_costs = amounts['interest'] + amounts['finance_carried']
    eligible = min(finance_costs, profit, max(ZERO, total_income - allowance)) if value['method'] == 'expenses' else ZERO
    relief = min(combined_tax, eligible * Decimal(rules['finance_relief_rate']))
    rental_tax = max(ZERO, combined_tax - relief - base_tax).quantize(Decimal('.01'))
    gap = max(ZERO, rental_tax - amounts['reserved'])
    # Monthly slots including the current tax month, ending on 5 April.
    tax_month = (today.year - start.year) * 12 + today.month - start.month - (today.day < start.day)
    months = max(1, 12 - tax_month)
    monthly = (gap / months).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    return {'rules':rules,'year':value['year'],'deduction':deduction,'losses_used':min(profit_before_losses,amounts['losses']),'base_tax':base_tax,'combined_tax':combined_tax,'eligible_finance':eligible,'other_income':amounts['other_income'],'taxable_total':total_income,'tax': rental_tax, 'profit': profit, 'rent': amounts['rent'], 'allowance': allowance,
            'relief': relief, 'gap': gap, 'monthly': monthly, 'months': months,
            'reserved': amounts['reserved'], 'protect': value['protect'],
            'protected': max(rental_tax, amounts['reserved']) if value['protect'] else ZERO,
            'unused_losses': max(ZERO, amounts['losses'] - profit_before_losses),
            'unused_finance': max(ZERO, finance_costs - eligible),
            'cash_after_tax_interest': amounts['rent'] - amounts['expenses'] - amounts['interest'] - rental_tax}


def protected_reserve():
    value = load()
    result = estimate(value)
    if result is None and value['enabled'] and value['protect']:
        raise ValueError('Rental-tax reserve rules have expired; update the tax plan before relying on cash forecasts')
    return result['protected'] if result else ZERO
