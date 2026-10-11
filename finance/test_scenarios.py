"""Read-only spending comparisons and serializable forecast details."""
from datetime import date
from decimal import Decimal
from finance.test_receipt import build

ZERO=Decimal(0)


def pounds(value): return f"{'-' if value<0 else ''}£{abs(value):,.2f}" if value is not None else 'Unavailable'


def goal_date(value,today):
    if value=='already': return today
    return value if isinstance(value,date) else None


def snapshot(result,today):
    forecast=result['forecast'];inputs=result['inputs']
    accounts=[]
    for row in result['account_plan']['accounts'] if inputs['use_accounts'] else []:
        reached=goal_date(row['goal_date'] or row.get('extended_goal_date'),today)
        accounts.append({'name':row['name'],'balance':pounds(row['balance']),'target':pounds(row['target']),
                         'projected':pounds(row['projected']),'goal_date':reached.isoformat() if reached else None,
                         'extended':bool(reached and reached>forecast['end']),
                         'reached':bool(row['goal_date'])})
    reached=forecast['goal_date'] or forecast.get('extended_goal_date')
    return {'end':forecast['end'].isoformat(),'payoff':forecast['payoff'].isoformat() if forecast['payoff'] else None,
            'amex_end':pounds(forecast['card_end']),'savings_end':pounds(forecast['savings_end']),
            'minimum_bank':pounds(forecast['minimum_bank']),'minimum_date':forecast['minimum_date'].isoformat(),
            'bank_reserve':pounds(result['projection']['buffer']-(result['projection'].get('reserve_details') or {}).get('gap',ZERO)-(result['projection'].get('reserve_details') or {}).get('tax_reserve',ZERO)),
            'reserves_hold':forecast['run_out'] is None,'shortfall_date':forecast['run_out'].isoformat() if forecast['run_out'] else None,
            'goal_date':reached.isoformat() if reached else None,'goal_extended':bool(reached and reached>forecast['end']),
            'has_goal':bool(inputs['goal']),'accounts':accounts,
            'periods':[{'date':p['date'].isoformat(),'salary':pounds(p['salary']),'costs':pounds(p['costs']),
                        'spending':pounds(p['variable']),'extra':pounds(p['extra']),'savings':pounds(p['savings']),
                        'automatic':pounds(p['automatic_savings'])} for p in forecast['payments']],
            'checkpoints':[{'months':months,'cash':pounds(cash)} for months,cash in result['checkpoints']]}


def compare(projection,values,today,*,current=None):
    current=current or build(projection,values,today)
    difference=current['inputs']['comparison_spend']
    lower=build(projection,values,today,spending_adjustment=-difference)
    higher=build(projection,values,today,spending_adjustment=difference)
    sensitivity=lower if difference==100 else build(projection,values,today,spending_adjustment=Decimal(-100))
    changes=[]
    for row,other in zip(current['account_plan']['accounts'],sensitivity['account_plan']['accounts']):
        original=goal_date(row['goal_date'] or row.get('extended_goal_date'),today)
        improved=goal_date(other['goal_date'] or other.get('extended_goal_date'),today)
        if not row['target']: continue
        if original and improved:
            months=max(0,round((original-improved).days/30.4375))
            message=f'About {months} '+('month' if months==1 else 'months')+' sooner' if months else 'Same approximate timing'
        elif improved: message=f'Funded goal date: {improved:%d %b %Y}'
        else: message='No funded goal date within the planning horizon'
        changes.append({'name':row['name'],'message':message})
    original=current['forecast']['goal_date'] or current['forecast'].get('extended_goal_date')
    improved=sensitivity['forecast']['goal_date'] or sensitivity['forecast'].get('extended_goal_date')
    goal_message=None
    if original and improved:
        months=max(0,round((original-improved).days/30.4375))
        goal_message=f'Overall goal about {months} '+('month' if months==1 else 'months')+' sooner.' if months else 'Overall goal: same approximate timing.'
    delta=sensitivity['forecast']['savings_end']-current['forecast']['savings_end']
    amex_message=None
    if current['forecast']['payoff'] and sensitivity['forecast']['payoff']:
        months=max(0,round((current['forecast']['payoff']-sensitivity['forecast']['payoff']).days/30.4375))
        amex_message=f'Amex clears about {months} '+('month' if months==1 else 'months')+' sooner' if months else 'Amex: same approximate clearance timing'
    return {'scenarios':[dict(snapshot(result,today),name=name,adjustment=pounds(adjustment))
                         for name,adjustment,result in [('Lower spending',-difference,lower),('Current plan',ZERO,current),('Higher spending',difference,higher)]],
            'comparison_spend':pounds(difference),'sensitivity':{'savings_change':pounds(delta),
                'message':f'Up to £100/month less everyday spending: {pounds(delta)} more savings by forecast end.',
                'goal_message':goal_message,'amex_message':amex_message,'goals':changes}}
