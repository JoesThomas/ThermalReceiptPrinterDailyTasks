"""Versioned private subscriptions, preserving existing rows during upgrades."""
from storage import PrivateStore
from finance.money import parse


def validate(value):
    if not isinstance(value, dict) or value.get('schema_version', 1) != 1:
        raise ValueError('Unsupported subscription data version')
    for field in ('monthly', 'yearly', 'instalments'):
        rows = value.get(field, [])
        if not isinstance(rows, list) or len(rows) > 1000:
            raise ValueError('Invalid subscription records')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('name'), str):
                raise ValueError('Invalid subscription entry')
            for key in ('amount', 'monthly_payment', 'remaining_balance', 'paid_to_date', 'total_price'):
                if row.get(key) is not None and parse(row[key]) is None:
                    raise ValueError('Invalid subscription amount')


def legacy(value):
    return {'monthly': [], 'yearly': [], 'instalments': [], **value}


def store(path):
    return PrivateStore(path, default=lambda: legacy({}), validate=validate,
                        schema_version=1, migrations={0: legacy})


def load(path):
    return store(path).read()


def save(path, value):
    validate(value)
    def replace(current):
        current.clear()
        current.update(value)
    store(path).update(replace)
