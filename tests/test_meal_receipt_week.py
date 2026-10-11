"""Weekly receipt shopping must follow the week shown in its overview."""
from datetime import datetime
import unittest
from unittest.mock import Mock, patch
from meals import legacy_planner as planner


class MealReceiptWeekTests(unittest.TestCase):
    def test_saturday_overview_and_shopping_use_upcoming_week(self):
        clock = Mock()
        clock.now.return_value = datetime(2026, 10, 10, 9, tzinfo=planner.TZ)
        plan = {'meals': [], 'shopping': {'VEG': ['next-week carrots']}}
        printed = []
        with patch.object(planner, 'datetime', clock), patch.object(
            planner, 'generate_week', return_value=plan
        ) as generate, patch.object(planner, 'load_plan_for') as load:
            planner.print_weekly_overview(Mock(), lambda p, s: printed.append(s), Mock())
            planner.print_shopping_list(Mock(), lambda p, s: printed.append(s), Mock())
        self.assertEqual(generate.call_count, 2)
        self.assertEqual(generate.call_args_list[0], generate.call_args_list[1])
        self.assertEqual(generate.call_args.args[0].isoformat(), '2026-10-11')
        load.assert_not_called()
        self.assertIn('[ ] next-week carrots', printed)

    def test_indented_description_preserves_all_words_and_width(self):
        overview = 'Chicken with tomato, mozzarella, basil and crisp potatoes.'
        plan = {'meals': [{'date': '2026-10-11', 'kind': 'recipe',
                          'recipe': {'name': 'Chicken', 'overview': overview}}]}
        printed = []
        with patch.object(planner, 'generate_week', return_value=plan):
            planner.print_weekly_overview(Mock(), lambda p, s: printed.append(s), Mock())
        description = [s for s in printed if s.startswith('  ') and ' KCAL' not in s]
        self.assertEqual(' '.join(s.strip() for s in description), overview)
        self.assertTrue(all(len(s) <= planner.RECEIPT_WIDTH for s in description))

    def test_explicit_plan_is_used_without_loading_another_week(self):
        printed = []
        with patch.object(planner, 'generate_week') as generate, patch.object(planner, 'load_plan_for') as load:
            planner.print_shopping_list(Mock(), lambda p, s: printed.append(s), Mock(),
                                        plan={'shopping': {'BAKERY': ['bread']}})
        generate.assert_not_called()
        load.assert_not_called()
        self.assertIn('[ ] bread', printed)
