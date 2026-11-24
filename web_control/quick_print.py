"""Preview and print a private one-off text receipt."""
from hashlib import sha256

from flask import flash, redirect, render_template, request, url_for

from receipt import quick_note, repeat_guard


def register(app, login_required, start_print, root):
    @app.context_processor
    def quick_print_context():
        return {"quick_print_available": True}

    @app.route("/quick-print", methods=["GET", "POST"])
    @login_required
    def quick_print():
        title, text, preview, checklist = "", "", "", False
        settings = quick_note.settings_store(root)
        try:
            max_chars = settings.read()["max_chars"]
        except (ValueError, OSError):
            return render_template(
                "quick_print.html", title="", text="", preview="", checklist=False,
                max_chars=quick_note.MAX_CHARS, max_title_chars=quick_note.MAX_TITLE_CHARS,
                max_allowed_chars=quick_note.MAX_ALLOWED_CHARS, advice="",
                settings_error="Quick Print settings are unavailable. Check or restore data/quick_print_settings.json.",
            ), 503
        if request.method == "POST":
            title = request.form.get("title", "")
            text = request.form.get("text", "")
            checklist = request.form.get("checklist") == "on"
            try:
                if request.form.get("intent") == "save_settings":
                    try:
                        chosen = int(request.form.get("max_chars", ""))
                    except ValueError:
                        raise ValueError("Enter a whole-number character limit.") from None
                    quick_note.validate_limit(chosen)
                    settings.update(lambda value: value.update(max_chars=chosen))
                    max_chars = chosen
                    flash("Quick Print character limit saved. Your draft is still below.")
                    if len(text) > max_chars:
                        flash("Your draft exceeds the new limit. Shorten it or raise the limit before printing.")
                else:
                    preview = quick_note.format_note(text, checklist, title=title, max_chars=max_chars)
                if request.form.get("intent") == "print":
                    signature = ["--quick-note-content", sha256(preview.encode()).hexdigest()]
                    if repeat_guard.recent(root, signature) and request.form.get("allow_repeat") != "on":
                        flash("This note was just queued. Allow an intentional reprint to send it again.")
                    else:
                        key = quick_note.spool(root, preview)
                        started = False
                        try:
                            started, error = start_print(["--quick-note", key])
                        finally:
                            if not started:
                                quick_note.path_for(root, key).unlink(missing_ok=True)
                        if started:
                            try:
                                repeat_guard.record(root, signature)
                            except OSError:
                                app.logger.warning("Could not save the Quick Print repeat marker.")
                            advice = quick_note.length_advice(preview)
                            if advice:
                                flash(advice)
                            flash("Quick Print note queued.")
                            return redirect(url_for("quick_print"))
                        flash(error)
            except ValueError as error:
                flash(str(error))
                title = title[:quick_note.MAX_TITLE_CHARS]
                # Keep the draft intact so a validation error never silently cuts it.
            except OSError:
                flash("Quick Print could not prepare the note.")
        return render_template(
            "quick_print.html", title=title, max_title_chars=quick_note.MAX_TITLE_CHARS,
            text=text, preview=preview, checklist=checklist,
            max_chars=max_chars, max_allowed_chars=quick_note.MAX_ALLOWED_CHARS,
            advice=quick_note.length_advice(preview), settings_error="",
        )
