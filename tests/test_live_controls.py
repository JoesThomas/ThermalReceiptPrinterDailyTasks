import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from web_control import live_data


class LiveControlTests(unittest.TestCase):
    def test_food_shop_override_can_be_saved_and_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'shopping.json'
            with patch.object(live_data, 'FOOD_SHOP_FILE', file):
                self.assertIsNone(live_data.food_shop_override())
                self.assertEqual(live_data.save_food_shop('Bread\n\nMilk 2L\n'), ['Bread', 'Milk 2L'])
                self.assertEqual(live_data.food_shop_override(), ['Bread', 'Milk 2L'])
                self.assertRaises(ValueError, live_data.save_food_shop, 'a' * 181)

    def test_tesco_progress_requires_current_item(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live_data, 'TESCO_PROGRESS_FILE', Path(directory) / 'tesco.json'):
                live_data.mark_tesco_item('Milk', ['Milk'], True)
                self.assertEqual(live_data.tesco_progress(['Milk', 'Eggs']),
                                 {'Milk': True, 'Eggs': False})
                self.assertRaises(ValueError, live_data.mark_tesco_item,
                                  'Old item', ['Milk'], True)

    def test_meal_confirmation_is_for_selected_recipe_and_undoes(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(live_data, 'MEALS_EATEN_FILE', Path(directory) / 'eaten.json'):
                today = date.today()
                live_data.confirm_meal(today, 'Pasta', {'Pasta', 'Curry'})
                self.assertEqual(live_data.meal_confirmation(today)['recipe'], 'Pasta')
                self.assertRaises(ValueError, live_data.confirm_meal, today, 'Unknown', {'Pasta'})
                live_data.clear_meal_confirmation(today)
                self.assertIsNone(live_data.meal_confirmation(today))

    def test_map_query_encodes_location(self):
        self.assertIn('Birmingham+New+Street', live_data.map_embed_url('Birmingham New Street'))
        self.assertIsNone(live_data.map_link_url(''))


if __name__ == '__main__':
    unittest.main()
