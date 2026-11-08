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
        text, preview, checklist = "", "", False
        if request.method == "POST":
            text = request.form.get("text", "")
            checklist = request.form.get("checklist") == "on"
            try:
                preview = quick_note.format_note(text, checklist)
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
                            flash("Quick Print note queued.")
                            return redirect(url_for("quick_print"))
                        flash(error)
            except ValueError as error:
                flash(str(error))
                text = text[:quick_note.MAX_CHARS]
            except OSError:
                flash("Quick Print could not prepare the note.")
        return render_template("quick_print.html", text=text, preview=preview, checklist=checklist)
