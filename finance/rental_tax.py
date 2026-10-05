"""Private, bounded 2026/27 estimate for personally owned UK residential lets."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from storage import PrivateStore
from finance.money import parse, ZERO
from receipt.local_time import uk_today

FILE = Path(__file__).resolve().parents[1] / 'data' / 'rental_tax.json'
FIELDS = ('other_income', 'rent', 'expenses', 'interest', 'losses', 'finance_carried', 'reserved')
DEFAULT = {'enabled': False, 'protect': False, 'year': '2026/27', 'region': 'England/Wales/NI', 'method': 'expenses', **{key: '' for key in FIELDS}}


def validate(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool or type(value.get('protect')) is not bool:
        raise ValueError('Invalid tax settings')
    if value.get('year') != '2026/27' or value.get('region') != 'England/Wales/NI' or value.get('method') not in ('expenses', 'allowance'):
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


def income_tax(income):
    allowance = max(ZERO, Decimal('12570') - max(ZERO, income - Decimal('100000')) / 2)
    taxable = max(ZERO, income - allowance)
    basic = min(taxable, Decimal('37700'))
    higher = min(max(ZERO, taxable - basic), Decimal('87440'))
    additional = max(ZERO, taxable - basic - higher)
    return basic * Decimal('.20') + higher * Decimal('.40') + additional * Decimal('.45'), allowance


def estimate(value, today=None):
    validate(value)
    today = today or uk_today()
    if not value['enabled']: return None
    if not date(2026, 4, 6) <= today <= date(2027, 4, 5): return None
    amounts = {key: parse(value[key]) for key in FIELDS}
    deduction = Decimal('1000') if value['method'] == 'allowance' else amounts['expenses']
    profit_before_losses = max(ZERO, amounts['rent'] - deduction)
    profit = max(ZERO, profit_before_losses - amounts['losses'])
    total_income = amounts['other_income'] + profit
    combined_tax, allowance = income_tax(total_income)
    base_tax, _ = income_tax(amounts['other_income'])
    finance_costs = amounts['interest'] + amounts['finance_carried']
    eligible = min(finance_costs, profit, max(ZERO, total_income - allowance)) if value['method'] == 'expenses' else ZERO
    relief = min(combined_tax, eligible * Decimal('.20'))
    rental_tax = max(ZERO, combined_tax - relief - base_tax).quantize(Decimal('.01'))
    gap = max(ZERO, rental_tax - amounts['reserved'])
    # Monthly slots including the current tax month, ending on 5 April.
    tax_month = (today.year - 2026) * 12 + today.month - 4 - (today.day < 6)
    months = max(1, 12 - tax_month)
    monthly = (gap / months).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    return {'tax': rental_tax, 'profit': profit, 'rent': amounts['rent'], 'allowance': allowance,
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
