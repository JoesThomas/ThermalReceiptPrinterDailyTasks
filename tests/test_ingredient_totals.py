from datetime import date
from unittest import TestCase
from unittest.mock import patch
from meals.ingredients import aggregate
from meals import legacy_planner as planner


class IngredientTotalsTests(TestCase):
    def test_counts_fractions_and_plural_names_are_added(self):
        self.assertEqual(aggregate(['2 onions', '1/2 onion', '1 tortilla', '2 tortillas']),
                         ['2 1/2 onions', '3 tortillas'])
        self.assertEqual(aggregate(['2 onions', '2 onions']), ['4 onions'])
        self.assertEqual(aggregate(['½ onion', '1 onion']), ['1 1/2 onions'])

    def test_units_convert_but_different_ingredients_remain_separate(self):
        self.assertEqual(aggregate(['0.5kg rice', '250g rice']), ['750g rice'])
        self.assertEqual(aggregate(['1 tbsp soy sauce', '3 tsp soy sauce']), ['2 tbsp soy sauce'])
        self.assertEqual(aggregate(['2 onions', '1/2 red onion', '2 spring onions']),
                         ['2 onions', '1/2 red onion', '2 spring onions'])
        self.assertEqual(len(aggregate(['150g tomatoes', '1 tomato'])), 2)
        self.assertEqual(len(aggregate(['600g lean beef mince', '150g lean beef'])), 2)

    def test_unmeasured_items_are_not_guessed(self):
        self.assertEqual(aggregate(['lettuce', 'lettuce']), ['lettuce'])
        self.assertEqual(aggregate(['handful of lettuce', 'lettuce']), ['handful of lettuce', 'lettuce'])

    def test_lunch_and_dinner_quantities_accumulate_with_pantry_exclusions(self):
        plan = {'meals': [{'date': '2026-10-11', 'kind': 'recipe', 'recipe': {
            'ingredients': ['2 onions', '1 tortilla', '1 tsp salt'],
            'lunch': {'extra_ingredients': ['2 tortillas']}}},
            {'date': '2026-10-12', 'kind': 'recipe', 'recipe': {'ingredients': ['1/2 onion']}}]}
        with patch('receipt.local_time.uk_today', return_value=date(2026, 10, 10)), patch(
            'receipt.lifestyle.skip_meal', return_value=False), patch(
            'web_control.live_data.meal_confirmation', return_value=None), patch.object(
            planner, '_override_for', return_value=None), patch.object(
            planner, '_pantry_has', side_effect=lambda item: 'salt' in item):
            shopping = planner.build_shopping_list(plan)
        self.assertEqual(shopping['FRUIT / VEG'], ['3 onions (need 2 1/2)'])
        self.assertEqual(shopping['BAKERY'], ['3 tortillas'])
        self.assertNotIn('TINNED / DRY', shopping)

    def test_canned_tomatoes_and_frozen_peas_are_not_fresh_produce(self):
        self.assertEqual(planner._section('2 tins chopped tomatoes'), 'TINNED / DRY')
        self.assertEqual(planner._section('80g frozen peas'), 'TINNED / DRY')
        self.assertEqual(planner._section('150g tomatoes'), 'FRUIT / VEG')

    def test_purchase_counts_round_up_after_combining(self):
        self.assertEqual(aggregate(['2 onions', '1/2 onion'], for_shopping=True),
                         ['3 onions (need 2 1/2)'])
        self.assertEqual(aggregate(['1/2 broccoli', '1/2 broccoli'], for_shopping=True), ['1 broccoli'])
        self.assertEqual(aggregate(['1/2 broccoli'], for_shopping=True), ['1 broccoli (need 1/2)'])

    def test_configured_pack_sizes_round_up_but_unknown_sizes_are_not_invented(self):
        packs = {'basmati rice': {'unit': 'g', 'packs': [500, 1000]}}
        self.assertEqual(aggregate(['200g basmati rice', '175g basmati rice'], for_shopping=True, pack_sizes=packs),
                         ['500g basmati rice (need 375g)'])
        self.assertEqual(aggregate(['150g turkey'], for_shopping=True, pack_sizes=packs), ['150g turkey'])
