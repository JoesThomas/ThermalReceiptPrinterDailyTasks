from flask import render_template
from organiser.weekly_review import review


def register(app, login_required):
    @app.context_processor
    def weekly_review_context():
        return {"weekly_review_available": True}

    @app.get("/weekly-review")
    @login_required
    def weekly_review():
        return render_template("weekly_review.html", view=review())
