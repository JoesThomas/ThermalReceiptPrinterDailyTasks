"""Authenticated birthday CRUD and bounded private CSV import/export."""

from io import BytesIO
from flask import flash, redirect, render_template, request, send_file, url_for
from actions import birthdays


def register(app, login_required):
    @app.context_processor
    def birthday_context():
        return {"birthdays_available": True}

    def display(draft=None):
        try:
            rows = birthdays.load()
            upcoming = birthdays.upcoming(rows)
        except (OSError, ValueError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Birthday file could not be read."
            )
            rows = []
            upcoming = []
        return render_template(
            "birthdays.html",
            birthdays=sorted(
                rows, key=lambda row: (row["month"], row["day"], row["name"].casefold())
            ),
            upcoming=upcoming,
            draft=draft or {},
            current_year=birthdays.today().year,
        )

    @app.get("/birthdays")
    @login_required
    def birthday_list():
        return display()

    @app.post("/birthdays/save")
    @login_required
    def birthday_save():
        try:
            birthdays.update(
                request.form.get("name", ""),
                request.form.get("year", ""),
                request.form.get("month", ""),
                request.form.get("day", ""),
                request.form.get("id", ""),
                request.form.get("action") == "remove",
            )
            flash(
                "Birthday removed."
                if request.form.get("action") == "remove"
                else "Birthday saved. Generate a fresh receipt to include the change."
            )
        except (OSError, ValueError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Birthday changes could not be saved."
            )
            return display(request.form.to_dict())
        return redirect(url_for("birthday_list"))

    @app.post("/birthdays/import")
    @login_required
    def birthday_import():
        upload = request.files.get("file")
        try:
            if upload is None:
                raise ValueError("Choose a birthday CSV to import.")
            result = birthdays.import_csv(upload.stream.read(birthdays.MAX_BYTES + 1))
            flash(
                f"Imported {result['added']} birthdays; {result['total']} saved. Removed {result['blank']} blank rows and {result['duplicates']} exact duplicate rows."
            )
        except (OSError, ValueError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Birthday CSV could not be saved."
            )
        return redirect(url_for("birthday_list"))

    @app.get("/birthdays/export")
    @login_required
    def birthday_export():
        try:
            raw = birthdays.csv_bytes(birthdays.load())
        except (OSError, ValueError):
            flash("Birthday file could not be exported. Review the saved data.")
            return redirect(url_for("birthday_list"))
        response = send_file(
            BytesIO(raw),
            mimetype="text/csv",
            as_attachment=True,
            download_name="birthdays.csv",
        )
        response.headers["Cache-Control"] = "no-store"
        return response
