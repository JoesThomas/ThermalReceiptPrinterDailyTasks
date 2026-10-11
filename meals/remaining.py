"""One selection of home meals still needing ingredients or preparation."""
from datetime import date
from receipt.local_time import uk_today


def needs_dinner(meal, today=None, confirmation=None, away=None):
    today = today or uk_today()
    if meal.get('kind') != 'recipe':
        return False
    on = date.fromisoformat(meal['date'])
    if on < today:
        return False
    if away is None:
        from receipt.lifestyle import skip_meal
        away = skip_meal
    if away(on):
        return False
    if confirmation is None:
        from web_control.live_data import meal_confirmation
        confirmation = meal_confirmation
    # A confirmation means dinner was eaten, including a different recipe.
    return not bool(confirmation(on))
