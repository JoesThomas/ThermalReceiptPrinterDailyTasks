"""Authenticated local vehicle editor."""

from flask import flash, redirect, render_template, request, url_for
from services import vehicle_records as records


def register(app, login_required):
    @app.context_processor
    def vehicle_context():
        return {"vehicles_available": True}

    def display(draft=None):
        try:
            rows = records.load()["vehicles"]
        except (OSError, ValueError):
            flash("Saved vehicles could not be read. Check the private data file.")
            rows = []
        return render_template(
            "vehicles.html",
            vehicles=rows,
            draft=draft or {},
            dates=records.DATES,
            details=records.DETAILS,
            expiry_label=records.expiry_label,
        )

    @app.get("/vehicles")
    @login_required
    def vehicle_list():
        return display()

    @app.post("/vehicles/save")
    @login_required
    def vehicle_save():
        try:
            records.update(
                request.form.to_dict(),
                request.form.get("id", ""),
                request.form.get("action") == "remove",
            )
            flash(
                "Vehicle removed."
                if request.form.get("action") == "remove"
                else "Vehicle saved. Generate a fresh receipt to include the change."
            )
        except (OSError, ValueError) as error:
            flash(
                str(error)
                if isinstance(error, ValueError)
                else "Vehicle changes could not be saved."
            )
            return display(request.form.to_dict())
        try:
            records.sync_mot_tasks()
        except (OSError, ValueError):
            flash("Vehicle saved, but MOT tasks could not be updated. Check task data.")
        return redirect(url_for("vehicle_list"))
