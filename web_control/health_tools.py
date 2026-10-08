from threading import Thread
from flask import flash, redirect, render_template, request, url_for
from services import api_health as health
from receipt.local_time import uk_receipt_time
from receipt_settings import load_receipt_settings, save_receipt_settings


def register(app,login_required):
    @app.get('/api-health')
    @login_required
    def api_health_page():
        config=health.options(); state=health.load()
        try: active={spec[0] for spec in health.specifications()}
        except (ValueError,TypeError):active=set(health.PUBLIC)
        names=[*health.PUBLIC,'Google Calendar','Google Docs – tasks','Google Docs – exercises',
               'Google Docs – food shop','Google Docs – subscriptions',*health.OBSERVED]
        rows=[]
        for name in names:
            row=state['services'].get(name,{})
            if not isinstance(row,dict):row={}
            status=row.get('status','not checked' if name in (*active,*health.OBSERVED) else 'not configured')
            stale=bool(row.get('checked_at')) and health.age(row.get('checked_at'))>max(7200,config['interval_minutes']*120)
            history=[x for x in row.get('history',[]) if isinstance(x,dict)] if isinstance(row.get('history',[]),list) else []
            rows.append(dict(name=name,status=status,stale=stale,checked=uk_receipt_time(row.get('checked_at')),
                             last_success=uk_receipt_time(row.get('last_success')),code=row.get('code'),
                             duration=row.get('duration_ms'),failures=row.get('failures',0),
                             mode='Periodic check' if name in active else 'Observed during normal use',
                             history=[dict(item,local=uk_receipt_time(item.get('checked_at'))) for item in reversed(history)]))
        from health import run_health_checks
        local_checks = run_health_checks()
        running=health.running()
        return render_template('api_health.html',rows=rows,local_checks=local_checks,health_options=config,intervals=health.INTERVALS,
                               running=running,current_service=state.get('current_service',''),last_cycle=uk_receipt_time(state.get('last_cycle')))

    @app.post('/api-health/settings')
    @login_required
    def api_health_settings():
        try:
            interval=int(request.form.get('interval','60'))
            if interval not in health.INTERVALS:raise ValueError()
            settings=load_receipt_settings()
            settings['api_health']={'enabled':request.form.get('enabled')=='on','interval_minutes':interval}
            save_receipt_settings(settings);flash('Integration check settings saved.')
        except ValueError:flash('Choose one of the available check intervals.')
        return redirect(url_for('api_health_page'))

    @app.post('/api-health/check')
    @login_required
    def api_health_check():
        service = request.form.get('service') or None
        if service is not None and service not in {spec[0] for spec in health.specifications()}:
            from flask import abort
            abort(400)
        def run():
            try:health.check_once(force=True, **({'service':service} if service else {}))
            except Exception:app.logger.warning('Requested integration check failed.')
        Thread(target=run,daemon=True,name='receipt-health-now').start()
        flash('Integration checks requested. Refresh this page to see the results.')
        return redirect(url_for('api_health_page'))
