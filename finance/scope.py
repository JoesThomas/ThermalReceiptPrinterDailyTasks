"""Privacy-safe provenance for aggregate finance observations."""


def validate(value):
    if not isinstance(value,dict) or value.get('monzo') not in {'first','all'} or not isinstance(value.get('sources'),list) or len(value['sources'])>3:
        raise ValueError('Invalid collection scope')
    for row in value['sources']:
        if not isinstance(row,dict) or set(row)-{'provider','mode','included','available'} or row.get('provider') not in {'HSBC','MONZO','AMEX'} or row.get('mode') not in {'first','all'}:
            raise ValueError('Invalid collection source')
        if any(type(row.get(key)) is not int or not 0<=row[key]<=1000 for key in ('included','available')) or row['included']>row['available']:
            raise ValueError('Invalid collection source count')
