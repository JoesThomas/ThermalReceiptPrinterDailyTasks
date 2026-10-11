import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from actions import checklists
from actions.receipt_workout import plan, PRESETS


class ReceiptWorkoutTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.patch=patch.object(checklists,'FILE',Path(self.folder.name)/'lists.json')
        self.patch.start()
    def tearDown(self):
        self.patch.stop();self.folder.cleanup()

    def test_cycle_covers_only_six_and_is_stable_on_reprint(self):
        checklists.sync('Squats\nPlank\nBurpees','exercises')
        found=set()
        for offset in range(8):
            day=(date(2026,10,6)+timedelta(days=offset)).isoformat()
            rows=plan(day)
            self.assertEqual(rows,plan(day))
            found.update(row['id'] for row in rows)
            self.assertEqual(len(rows),4 if offset%2==0 else 1)
        self.assertEqual(found,{'receipt-exercise-'+item[0] for item in PRESETS})
        self.assertEqual(len(checklists.rows('exercises')),9)

    def test_completion_skip_equipment_and_editable_targets(self):
        with patch.object(checklists,'today',return_value='2026-10-06'):
            rows=plan();key=rows[0]['id']
            checklists.update('exercises','toggle',key)
            self.assertTrue(plan()[0]['completed'])
            checklists.update('exercises','details',key,sets='3',reps='12',duration='',equipment=['dumbbells'])
            self.assertIn('3 sets',plan()[0]['title'])
            checklists.update('exercises','skip',key)
            self.assertNotIn(key,{row['id'] for row in plan()})
            checklists.save_equipment([])
            self.assertEqual({row['id'] for row in plan()},{'receipt-exercise-situps','receipt-exercise-press_ups'})
        self.assertEqual(plan('2026-10-07')[0]['id'],'receipt-exercise-jogging')
        checklists.save_equipment(['rowing_machine'])
        self.assertEqual(plan('2026-10-07')[0]['id'],'receipt-exercise-rowing')
        self.assertFalse(any(row['completed'] for row in plan('2026-10-08')))

    def test_existing_strength_targets_migrate_once_and_preserve_completion(self):
        plan('2026-10-06')
        with checklists.transaction() as state:
            for row in state['items']:
                row.pop('receipt_target_version', None)
                if row['sets']:
                    row.update(sets='2',reps='10',done=True,done_on='2026-10-06')
        rows=plan('2026-10-06')
        self.assertTrue(all(row['sets']=='4' and row['reps']=='20' and row['completed'] for row in rows))
        with checklists.transaction() as state:
            state['items'][0].update(sets='3',reps='12')
        self.assertEqual(plan('2026-10-06')[0]['sets'],'3')
        self.assertEqual(plan('2026-10-07')[0]['duration'],'15 min, steady pace')
