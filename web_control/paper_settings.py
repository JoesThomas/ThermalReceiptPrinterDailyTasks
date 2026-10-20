"""Paper controls share Receipt Control's login and CSRF protection."""
from flask import abort, flash, redirect, request, url_for
from receipt import paper_settings as paper
from receipt.profile import restart_required


def register(app, login_required):
    @app.context_processor
    def paper_context():
        settings, warning = paper.state()
        return dict(paper_settings=settings, paper_settings_warning=warning, printer_presets=paper.PRESETS)

    @app.before_request
    def prevent_mixed_width_jobs():
        if request.method == 'POST' and restart_required() and (
            request.path.startswith(('/print-', '/preview/print', '/finance/test/generate', '/finance/test/print', '/printer-diagnostics/paper-test'))
            or request.path == '/preview/generate'
        ):
            flash('Restart Receipt Control to apply the new printer size before generating or printing receipts.')
            return redirect(url_for('index', view='settings'))

    @app.post('/settings/printer-paper')
    @login_required
    def save_printer_paper():
        try:
            value = paper.load()
            preset = request.form.get('preset', value['preset'])
            value['preset'] = preset
            if preset in paper.PRESETS:
                value.update(paper.PRESETS[preset])
            elif preset == 'custom':
                for key in paper.GEOMETRY_KEYS:
                    value[key] = float(request.form.get(key, ''))
            else:
                abort(400)
            for key in ('roll_length_m','prints_per_week','waste_percent','line_mm','cutter_mm'):
                value[key] = float(request.form.get(key, ''))
            paper.save(value)
            flash('Paper settings saved.' + (' Restart Receipt Control to apply the new printer size before generating or printing.' if restart_required() else ' Roll estimates update immediately.'))
        except (ValueError, OSError) as error:
            flash(str(error) if isinstance(error, ValueError) else 'Paper settings could not be saved. Check local storage.')
        return redirect(url_for('index', view='settings', _anchor='printer-paper'))
