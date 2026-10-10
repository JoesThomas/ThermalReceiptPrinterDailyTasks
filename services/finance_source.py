"""Finance collection orchestration separated from receipt rendering."""
from dataclasses import dataclass
from typing import Callable, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests


@dataclass(frozen=True)
class FinanceDependencies:
    today: Callable[..., Any]
    _dedupe_regular_payments: Callable[..., Any]
    _dedupe_subscriptions_against_regular: Callable[..., Any]
    _incoming_total: Callable[..., Any]
    _initial_truelayer_refresh_token: Callable[..., Any]
    _is_incoming_transaction: Callable[..., Any]
    _last_n_day_spend: Callable[..., Any]
    _looks_like_internal_transfer: Callable[..., Any]
    _monthlyised_spend: Callable[..., Any]
    _normalise_regular_payment: Callable[..., Any]
    _other_incoming_category: Callable[..., Any]
    _refresh_truelayer_access_token: Callable[..., Any]
    _transaction_date: Callable[..., Any]
    _truelayer_account_ids: Callable[..., Any]
    _truelayer_card_ids: Callable[..., Any]
    _truelayer_regular_payments: Callable[..., Any]
    _truelayer_transactions: Callable[..., Any]
    analyse_incoming_payments: Callable[..., Any]
    infer_subscriptions: Callable[..., Any]
    load_receipt_settings: Callable[..., Any]
    FINANCE_TRANSACTION_LOOKBACK_DAYS: int


def collect(dependencies: FinanceDependencies, *, persist=True):
    """
    Retrieve live regular-payment and transaction information from
    TrueLayer for HSBC, Monzo and Amex.

    Returns:
      all_transactions
      direct_debits
      standing_orders
      inferred subscriptions
      spending_summary

    HSBC + Monzo are treated as bank accounts.
    Amex is treated as a credit card.
    """
    today = dependencies.today()
    from_date = today - timedelta(days=dependencies.FINANCE_TRANSACTION_LOOKBACK_DAYS)
    direct_debits = []
    standing_orders = []
    all_transactions = []
    provider_tokens = {}
    transaction_range_info = {}
    source_coverage = []
    collection_sources = []
    fetch_attempted = 0
    fetch_succeeded = 0
    fetch_failed = 0
    for provider in ('HSBC', 'MONZO', 'AMEX'):
        try:
            provider_tokens[provider] = dependencies._refresh_truelayer_access_token(provider, dependencies._initial_truelayer_refresh_token(provider))
        except Exception as error:
            print(f'{provider} unavailable:', repr(error))
            provider_tokens[provider] = None
            fetch_failed += 1
            source_coverage.append({'provider': provider, 'source': 'Connection', 'status': 'Unavailable', 'count': None})
    from finance.transaction_sources import load as load_source_settings, select as select_sources
    source_settings = load_source_settings()
    for provider in ('HSBC', 'MONZO'):
        access_token = provider_tokens.get(provider)
        if not access_token:
            continue
        try:
            account_ids = dependencies._truelayer_account_ids(access_token)
        except requests.RequestException as error:
            print(f'{provider} account-list error:', error)
            fetch_failed += 1
            source_coverage.append({'provider': provider, 'source': 'Account list', 'status': 'Unavailable', 'count': None})
            continue
        if not account_ids:
            fetch_failed += 1
            source_coverage.append({'provider': provider, 'source': 'Account list', 'status': 'No accounts returned', 'count': 0})
        included_ids = select_sources(provider, account_ids, source_settings)
        collection_sources.append({'provider':provider,'mode':source_settings['monzo'] if provider=='MONZO' else 'all','included':len(included_ids),'available':len(account_ids)})
        if len(included_ids) < len(account_ids):
            source_coverage.append({'provider': provider, 'source': f'{len(account_ids) - len(included_ids)} other accounts', 'status': 'Disabled by first-account setting', 'count': None})
        for source_number, account_id in enumerate(included_ids, 1):
            try:
                dd_items = dependencies._truelayer_regular_payments(access_token, account_id, 'direct_debits')
                direct_debits.extend((dependencies._normalise_regular_payment(item, 'DD') for item in dd_items))
            except requests.RequestException as error:
                print(f'{provider} direct-debit error:', error)
            try:
                so_items = dependencies._truelayer_regular_payments(access_token, account_id, 'standing_orders')
                standing_orders.extend((dependencies._normalise_regular_payment(item, 'SO') for item in so_items))
            except requests.RequestException as error:
                print(f'{provider} standing-order error:', error)
            try:
                fetch_attempted += 1
                fetched = dependencies._truelayer_transactions(access_token, 'accounts', account_id, from_date, today, range_info=transaction_range_info)
                all_transactions.extend(fetched)
                source_coverage.append({'provider': provider, 'source': f'Account {source_number}', 'status': 'Loaded', 'count': len(fetched)})
                fetch_succeeded += 1
            except requests.RequestException as error:
                fetch_failed += 1
                source_coverage.append({'provider': provider, 'source': f'Account {source_number}', 'status': 'Unavailable', 'count': None})
                print(f'{provider} transaction error:', error)
    amex_token = provider_tokens.get('AMEX')
    if amex_token:
        try:
            card_ids = dependencies._truelayer_card_ids(amex_token)
        except requests.RequestException as error:
            print('AMEX card-list error:', error)
            fetch_failed += 1
            card_ids = []
        if not card_ids:
            fetch_failed += 1
            source_coverage.append({'provider': 'AMEX', 'source': 'Card list', 'status': 'Unavailable or empty', 'count': None})
        collection_sources.append({'provider':'AMEX','mode':'all','included':len(card_ids),'available':len(card_ids)})
        for source_number, card_id in enumerate(card_ids, 1):
            try:
                fetch_attempted += 1
                card_transactions = dependencies._truelayer_transactions(amex_token, 'cards', card_id, from_date, today, range_info=transaction_range_info)
                for transaction in card_transactions:
                    all_transactions.append({**transaction, '_source_provider': 'AMEX'})
                source_coverage.append({'provider': 'AMEX', 'source': f'Card {source_number}', 'status': 'Loaded', 'count': len(card_transactions)})
                fetch_succeeded += 1
            except requests.RequestException as error:
                fetch_failed += 1
                source_coverage.append({'provider': 'AMEX', 'source': f'Card {source_number}', 'status': 'Unavailable', 'count': None})
                print('AMEX transaction error:', error)
    direct_debits = dependencies._dedupe_regular_payments(direct_debits)
    standing_orders = dependencies._dedupe_regular_payments(standing_orders)
    subscriptions = dependencies.infer_subscriptions(all_transactions)
    subscriptions = dependencies._dedupe_subscriptions_against_regular(subscriptions, direct_debits, standing_orders)
    average_days = 30 if transaction_range_info.get('shortened') else dependencies.FINANCE_TRANSACTION_LOOKBACK_DAYS
    ninety_day_average = dependencies._monthlyised_spend(all_transactions, average_days, essential_only=False)
    essential_monthly_burn = dependencies._monthlyised_spend(all_transactions, average_days, essential_only=True)
    last_30_days = dependencies._last_n_day_spend(all_transactions, 30)
    salary_incomings, other_incomings = dependencies.analyse_incoming_payments(all_transactions, salary_payee=dependencies.load_receipt_settings().get('finance', {}).get('salary_payee', ''))
    if persist:
        from finance.premium_bonds import capture as capture_bond_prizes
        try:
            capture_bond_prizes(all_transactions, dependencies._other_incoming_category, dependencies._is_incoming_transaction, dependencies._looks_like_internal_transfer, dependencies._transaction_date)
        except (ValueError, OSError):
            print('Premium Bonds history could not be saved; check the private ledger file.')
    salary_30 = dependencies._incoming_total(salary_incomings, days=30)
    other_30 = dependencies._incoming_total(other_incomings, days=30)
    total_incoming_30 = salary_30 + other_30
    net_flow_30 = total_incoming_30 - last_30_days
    bank_data_status = 'unavailable' if not fetch_succeeded else 'partial' if fetch_failed else 'complete'
    spending_summary = {'average_period_days': average_days, 'bank_data_status': bank_data_status, 'source_coverage': source_coverage, 'collection_scope': {'monzo':source_settings['monzo'],'sources':collection_sources}, 'requested_from': (today - timedelta(days=29) if transaction_range_info.get('shortened') else from_date).isoformat(), 'requested_to': today.isoformat(), 'bank_fetch_attempted': fetch_attempted, 'bank_fetch_succeeded': fetch_succeeded, 'normal_monthly_burn': ninety_day_average, 'essential_monthly_burn': essential_monthly_burn, 'last_30_days': last_30_days, 'ninety_day_average': ninety_day_average, 'salary_incomings': salary_incomings, 'other_incomings': other_incomings, 'salary_30_days': salary_30, 'other_incoming_30_days': other_30, 'total_incoming_30_days': total_incoming_30, 'net_flow_30_days': net_flow_30}
    print('DIRECT DEBITS:', repr(direct_debits))
    print('STANDING ORDERS:', repr(standing_orders))
    return (all_transactions, direct_debits, standing_orders, subscriptions, spending_summary)
