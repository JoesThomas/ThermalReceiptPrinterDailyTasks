from datetime import date, datetime
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from meals import food_storage as storage, legacy_planner as planner

TODAY = date(2026, 10, 19)


class FoodStorageTests(TestCase):
    def test_all_builtin_components_have_specific_guidance(self):
        components = json.loads(Path(planner.COMPONENTS_FILE).read_text())['components']
        view = storage.web_guidance(None, components, TODAY)
        self.assertEqual(len(view['components']), 9)
        for item in view['components']:
            text = ' '.join(item['lines'])
            self.assertNotIn('No verified', text)
            self.assertIn('earlier', text.lower())
        mayo = storage.component_guidance({'id': 'mayonnaise', 'action': 'make'}, TODAY)
        self.assertIn('pasteurised egg', ' '.join(mayo))
        self.assertIn('use today, Mon 19 Oct', ' '.join(mayo))
        self.assertNotIn(storage.FREEZE, mayo)
        bread = storage.component_guidance({'id': 'focaccia', 'action': 'make'}, TODAY)
        self.assertNotIn(storage.COOL, bread)
        self.assertIn('cool, dry cupboard', ' '.join(bread))

    def test_leftovers_rice_and_ordinary_limits_with_conditional_dates(self):
        for ingredients, hours, day in [(['chicken', 'couscous'], 48, 'Wed 21 Oct'),
                                         (['75g basmati rice'], 24, 'Tue 20 Oct')]:
            rows = storage.leftover_guidance({'ingredients': ingredients}, TODAY)
            text = ' '.join(rows)
            self.assertIn(f'within {hours} hours', text)
            self.assertIn(f'If made today: use or freeze by {day}', text)
            self.assertIn('not end of day', text)
            self.assertIn(storage.REHEAT, rows)
            self.assertIn('raw meat/fish', text)
            compact = ' '.join(storage.receipt_lines(rows, True))
            self.assertIn(day, compact)
            self.assertIn('fridge', compact)
            if hours == 24:
                self.assertIn('within 1h', compact)
                self.assertIn('eat immediately', compact)
        # Date transitions must not give an extra day at month/year boundaries.
        self.assertIn('Fri 01 Jan', ' '.join(storage.leftover_guidance({}, date(2026, 12, 30))))

    def test_custom_and_bought_items_do_not_get_invented_durations(self):
        rows = storage.component_guidance({'id': 'custom', 'action': 'make', 'details': {'storage': 'Specific local recipe note'}}, TODAY)
        self.assertIn('No verified', ' '.join(rows))
        self.assertIn('Specific local recipe note', rows)
        self.assertNotIn('If made today', ' '.join(rows))
        bought = storage.component_guidance({'id': 'mayonnaise', 'action': 'buy'}, TODAY)
        self.assertIn('pack storage', ' '.join(bought))
        self.assertNotIn('use today', ' '.join(bought))

    def test_receipt_handles_lunch_override_and_toggle(self):
        meal = {'kind': 'recipe', 'recipe': {'name': 'Chicken rice', 'ingredients': ['rice'], 'lunch': {'name': 'Lunch'}}}
        for enabled in (True, False):
            printed = []
            with patch.object(planner, 'get_meal', return_value=meal), patch.object(planner, '_override_for', return_value={'type': 'buy_lunch'}), patch.object(planner, 'preferences', return_value={'cooking_style': {'show_storage_guidance': enabled}}):
                printer = Mock(paper_saver=True)
                planner.print_today_recipe(printer, lambda p, s: printed.append(s), Mock())
            text = '\n'.join(printed)
            self.assertEqual('LEFTOVERS / STORAGE' in text, enabled)
            self.assertTrue(all(len(s) <= 42 for s in printed))
            if enabled:
                self.assertIn('within 1h', text)
                self.assertIn('24 hours', text)

    def test_sunday_prep_uses_policy_even_for_old_cached_plans(self):
        printed = []
        clock = Mock()
        clock.now.return_value = datetime(2026, 10, 18, 9, tzinfo=planner.TZ)
        plan = {'prep': [{'id': 'chicken_stock', 'name': 'Stock', 'action': 'make', 'details': {}}]}
        with patch.object(planner, 'datetime', clock), patch.object(planner, 'load_plan_for', return_value=plan), patch.object(planner, 'preferences', return_value={}):
            planner.print_sunday_prep(Mock(paper_saver=True), lambda p, s: printed.append(s), Mock())
        self.assertIn('STORE / USE', printed)
        self.assertIn('Tue 20 Oct', '\n'.join(printed))
        self.assertTrue(all(len(s) <= 42 for s in printed))

    def test_web_template_shows_all_guides_and_escapes_local_notes(self):
        from flask import Flask
        app = Flask(__name__, template_folder=str(Path('web_control/templates').resolve()))
        app.add_url_rule('/', 'index', lambda: '')
        # Render the actual section within the full template without unrelated navigation.
        template = Path('web_control/templates/meals.html').read_text()
        section = template[template.index('            <section>\n                <h2>Storage'):template.index('            <section>\n                <h2>Confirm')]
        view = storage.web_guidance({'kind': 'recipe', 'recipe': {'ingredients': ['rice']}}, [{'id': 'custom', 'name': '<script>', 'make': {'storage': '<script>alert(1)</script>'}}], TODAY)
        from flask import render_template_string
        with app.test_request_context():
            html = render_template_string(section, storage=view)
        self.assertIn('24 hours', html)
        self.assertIn('Bulk prep storage guide', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('gov.uk', html)
