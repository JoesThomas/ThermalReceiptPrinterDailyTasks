import ast
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from receipt.capture import RecordingPrinter, load_capture
from receipt.layout import begin
from receipt.live_preview import VirtualPrinter
from receipt.selection import apply_preferences
from receipt_settings import DEFAULT_SETTINGS, feature_enabled, validate_settings


class MealsToggleTests(unittest.TestCase):
    def test_legacy_defaults_and_boolean_validation(self):
        self.assertTrue(DEFAULT_SETTINGS['features']['meals'])
        self.assertTrue(feature_enabled({'features':{}},'meals'))
        validate_settings({'features':{'meals':False}})
        with self.assertRaises(ValueError): validate_settings({'features':{'meals':'off'}})

    def test_selection_filters_meals_only_and_rejects_empty_request(self):
        settings={'features':{'meals':False}}
        self.assertEqual(apply_preferences(['food','finance','actions'],settings),['finance','actions'])
        with self.assertRaisesRegex(ValueError,'Meals on receipt is turned off'):
            apply_preferences(['food'],settings)

    def test_streaming_capture_keeps_finance_label_when_food_is_omitted(self):
        printer=RecordingPrinter(VirtualPrinter())
        with tempfile.TemporaryDirectory() as directory, patch('receipt.archive.save'),patch('web_control.today_summary.snapshot_changes'):
            for page in ['information','actions','finance']:
                begin(printer,page);printer.text(page+'\n');printer.cut()
            path=Path(directory)/'capture.json'
            printer.save(path=path,replace=True)
            self.assertEqual(load_capture(path)['pages'],{'information':'information','actions':'actions','finance':'finance'})
            self.assertEqual(printer.capture_order,['information','actions','finance'])

    def pipeline(self, enabled):
        from receipt.location_settings import DEFAULT_LOCATION, validate_location
        source=ast.parse(Path('services/live_pipeline.py').read_text())
        function=next(row for row in source.body if isinstance(row,ast.FunctionDef) and row.name=='run_live_pipeline')
        settings=deepcopy(DEFAULT_SETTINGS)
        settings['features']={key:False for key in settings['features']}
        settings['features']['meals']=enabled
        printer=RecordingPrinter(VirtualPrinter())
        meals=Mock()
        namespace=dict(os=os,datetime=datetime,ZoneInfo=ZoneInfo,
                       load_receipt_settings=lambda:settings,DEFAULT_LOCATION=DEFAULT_LOCATION,
                       validate_location=validate_location,clear_route_cache=lambda:None,
                       Usb=Mock(return_value=printer),PRINTER_VENDOR_ID=1,PRINTER_PRODUCT_ID=2,
                       setup_printer=lambda *args:None,one_shot_requested=lambda *args:False,
                       feature_enabled=feature_enabled,preview_progress=lambda *args:None,
                       print_header=lambda p,loc:p.text('INFORMATION\n'),
                       print_footer=lambda p:p.text('FOOTER\n'),cut_receipt_section=lambda p:p.cut(),
                       print_line=lambda *args:None,left=lambda *args:None,
                       print_wrapped=lambda *args,**kwargs:None,printer_safe_text=str,meals=meals)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'live_pipeline.py','exec'),namespace)
        return namespace,printer,meals

    def test_disabled_meals_are_not_generated_or_cut(self):
        namespace,printer,meals=self.pipeline(False)
        with patch('services.local_gigs.options',return_value={'enabled':False}),patch('builtins.print'):
            namespace['run_live_pipeline'](selected_pages=['information','food'])
        self.assertEqual(printer.capture_order,['information'])
        self.assertEqual(''.join(printer.lines).count('--- CUT ---'),1)
        self.assertEqual(meals.mock_calls,[])

    def test_disabled_explicit_food_request_does_not_open_hardware(self):
        namespace,_,meals=self.pipeline(False)
        with self.assertRaisesRegex(ValueError,'Meals on receipt is turned off'),patch('builtins.print'):
            namespace['run_live_pipeline'](only_page='food')
        namespace['Usb'].assert_not_called()
        self.assertEqual(meals.mock_calls,[])

    def test_enabled_food_page_keeps_existing_recipe_output(self):
        namespace,printer,meals=self.pipeline(True)
        with patch('builtins.print'):
            namespace['run_live_pipeline'](only_page='food')
        meals.print_today_recipe.assert_called_once()
        self.assertEqual(printer.capture_order,['food'])
        self.assertEqual(''.join(printer.lines).count('--- CUT ---'),1)
