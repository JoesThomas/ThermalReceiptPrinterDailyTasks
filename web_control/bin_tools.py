import json
from flask import flash, redirect, render_template, request, url_for
from services import bin_collections as bins
from receipt.local_time import uk_receipt_time


def register(app, login_required):
    def display(choices=None, code="", manual_draft=None, editor_draft=None):
        try:
            state = bins.load()
        except ValueError as error:
            flash(str(error))
            state = dict(bins.DEFAULT)
        return render_template(
            "bins.html",
            bins=state,
            choices=choices or [],
            lookup_postcode=code,
            checked=uk_receipt_time(state.get("last_success")),
            manual=manual_draft
            if manual_draft is not None
            else bins.manual_text(state["manual"]),
            summary=bins.schedule_summary(state),
            advanced_draft=manual_draft is not None,
            editor_rows=editor_draft if editor_draft is not None else state["manual"],
        )

    @app.get("/bins")
    @login_required
    def bin_settings():
        return display()

    @app.post("/bins/lookup")
    @login_required
    def bin_address_lookup():
        try:
            code = bins.postcode(request.form.get("postcode", ""))
            return display(bins.addresses(code), code)
        except (ValueError, bins.requests.RequestException):
            flash(
                "Address lookup unavailable. Enter the address, postcode and UPRN below. Your saved address was kept."
            )
            return redirect(url_for("bin_settings"))

    @app.post("/bins/save")
    @login_required
    def bin_settings_save():
        try:
            choice = (
                json.loads(request.form["choice"]) if "choice" in request.form else None
            )
            if choice is not None and not isinstance(choice, dict):
                raise ValueError("Choose a valid address.")
            bins.configure(
                request.form.get("enabled") == "on",
                request.form.get("provider", "birmingham"),
                choice.get("address", "")
                if choice
                else request.form.get("address", ""),
                request.form.get("postcode", ""),
                choice.get("uprn", "") if choice else request.form.get("uprn", ""),
                bins.parse_manual(request.form.get("manual", "")),
            )
            state = bins.refresh(force=True)
            flash(
                "Bin settings saved."
                + (
                    " Council check failed; see the status below."
                    if state.get("error")
                    else ""
                )
            )
        except (ValueError, TypeError) as error:
            flash(str(error))
        return redirect(url_for("bin_settings"))

    @app.post("/bins/manual")
    @login_required
    def bin_manual_save():
        try:
            if request.form.get("editor") == "rows":
                dates = request.form.getlist("collection_date")
                names = request.form.getlist("bin_name")
                repeats = request.form.getlist("repeat_days")
                if not len(dates) == len(names) == len(repeats) or len(dates) > 501:
                    raise ValueError("Invalid collection rows.")
                removed = set(request.form.getlist("remove_row"))
                rows = []
                for index, (stamp, name, repeat) in enumerate(
                    zip(dates, names, repeats)
                ):
                    if str(index) in removed or (
                        not stamp.strip() and not name.strip()
                    ):
                        continue
                    rows.append(dict(date=stamp, bin=name, repeat=int(repeat)))
                bins.validate({**bins.DEFAULT, "manual": rows})
            else:
                rows = bins.parse_manual(request.form.get("manual", ""))
            if not rows:
                raise ValueError("Enter at least one manual collection date.")
            with bins.transaction() as state:
                state.update(
                    provider="manual",
                    manual=rows,
                    enabled=request.form.get("enabled") == "on",
                    collections=[],
                    last_success="",
                    last_attempt="",
                    error="",
                )
            flash("Manual schedule saved and selected.")
            summary = bins.schedule_summary(state)
            flash(summary["status"])
            for warning in summary["warnings"][:3]:
                flash(warning)
        except (ValueError, TypeError) as error:
            flash(str(error))
            if request.form.get("editor") == "rows":
                draft = [
                    dict(date=stamp, bin=name, repeat=repeat)
                    for stamp, name, repeat in zip(
                        request.form.getlist("collection_date"),
                        request.form.getlist("bin_name"),
                        request.form.getlist("repeat_days"),
                    )
                ][:501]
                return display(editor_draft=draft)
            return display(manual_draft=request.form.get("manual", ""))
        return redirect(url_for("bin_settings"))

    @app.post("/bins/refresh")
    @login_required
    def bin_schedule_refresh():
        try:
            state = bins.refresh(force=True)
            flash(state.get("error") or "Bin schedule checked.")
        except ValueError as error:
            flash(str(error))
        return redirect(url_for("bin_settings"))
