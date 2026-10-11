import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from actions import checklists as lists


class DailyChecklistTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = patch.object(lists, 'FILE', Path(self.folder.name) / 'list.json')
        self.path.start()
    def tearDown(self):
        self.path.stop(); self.folder.cleanup()

    def test_task_completion_survives_refresh_and_local_items_print(self):
        lists.sync('Read the book.\nignored line', 'tasks')
        item = lists.rows('tasks')[0]
        lists.update('tasks', 'toggle', item['id'])
        lists.update('tasks', 'add', title='Buy milk')
        self.assertEqual(lists.task_text('Read the book.'), 'Buy milk.')
        lists.update('tasks', 'toggle', item['id'])
        self.assertIn('Read the book.', lists.task_text('Read the book.'))

    def test_whole_exercise_lines_daily_plan_and_completion_reset(self):
        lists.sync('Squats 3 sets of 10\nStretch for five minutes', 'exercises')
        with patch.object(lists, 'today', return_value='2026-10-03'):
            before = lists.exercise_plan(5)
            self.assertEqual({row['title'] for row in before}, {'Squats 3 sets of 10', 'Stretch for five minutes'})
            lists.update('exercises', 'toggle', before[0]['id'])
            after = lists.exercise_plan(5)
            self.assertEqual([row['id'] for row in before], [row['id'] for row in after])
            self.assertEqual(sum(row['completed'] for row in after), 1)
        with patch.object(lists, 'today', return_value='2026-10-04'):
            self.assertFalse(any(row['completed'] for row in lists.rows('exercises')))

    def test_google_doc_source_cannot_be_edited_or_deleted_locally(self):
        lists.sync('A task.', 'tasks')
        key = lists.rows('tasks')[0]['id']
        for action in ['save', 'delete']:
            with self.assertRaises(ValueError): lists.update('tasks', action, key, 'Changed')
        self.assertEqual(lists.rows('tasks')[0]['title'], 'A task')

    def test_edit_delete_and_invalid_input(self):
        lists.update('tasks', 'add', title='Local task')
        key = lists.rows('tasks')[0]['id']
        lists.update('tasks', 'save', key, 'Updated task')
        self.assertEqual(lists.rows('tasks')[0]['title'], 'Updated task')
        with self.assertRaises(ValueError): lists.update('tasks', 'add', title='.')
        lists.update('tasks', 'delete', key)
        self.assertEqual(lists.rows('tasks'), [])

    def test_receipt_prints_whole_exercise_without_second_fetch(self):
        import ast
        from types import SimpleNamespace
        source = ast.parse(Path('services/live_pipeline.py').read_text())
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'print_random_document_lines')
        printed = []
        namespace = {'RANDOM_LINES': 5, 'print_line': lambda *args: None,
                     'left': lambda *args: None, 'printer_safe_text': str,
                     'print_wrapped': lambda printer, value, width: printed.append(value)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<exercises>', 'exec'), namespace)
        with patch.object(lists, 'today', return_value='2026-10-06'):
            namespace['print_random_document_lines'](SimpleNamespace(set=lambda **kw: None), 'Squats 3 sets of 10')
        self.assertTrue(any('Bicep curls' in line for line in printed))
        self.assertFalse(any('Squats' in line for line in printed))

    def test_equipment_suggestion_and_receipt_follow_saved_plan(self):
        lists.sync('Dumb bell curls\nRowing\nPlank\nUnknown exercise', 'exercises')
        with patch.object(lists, 'today', return_value='2026-10-04'):
            lists.save_equipment(['dumbbells'])
            self.assertEqual(lists.set_plan(), 2)
            self.assertEqual({r['title'] for r in lists.exercise_plan(5)}, {'Dumb bell curls', 'Plank'})
            lists.save_equipment(['rowing_machine'])
            lists.set_plan()
            self.assertEqual({r['title'] for r in lists.exercise_plan(5)}, {'Rowing', 'Plank'})
            rowing = next(r for r in lists.rows('exercises') if r['title'] == 'Rowing')
            lists.update('exercises', 'skip', rowing['id'])
            self.assertEqual([r['title'] for r in lists.exercise_plan(5)], ['Plank'])
            lists.update('exercises', 'skip', rowing['id'])
            self.assertEqual(len(lists.exercise_plan(5)), 2)

    def test_manual_selection_instructions_and_history(self):
        lists.update('exercises', 'add', title='Curls', equipment=['dumbbells'], sets='3', reps='10')
        key = lists.rows('exercises')[0]['id']
        lists.set_plan([key])
        self.assertEqual(lists.exercise_plan(5)[0]['title'], 'Curls — 3 sets — 10 reps')
        lists.update('exercises', 'toggle', key)
        self.assertEqual(lists.rows('exercises')[0]['history'], [lists.today()])
        lists.update('exercises', 'toggle', key)
        self.assertEqual(lists.rows('exercises')[0]['history'], [])
        with self.assertRaises(ValueError): lists.set_plan(['missing'])
        with self.assertRaises(ValueError): lists.save_equipment(['unrecognised'])

    def test_task_dates_priorities_recurrence_and_source_metadata(self):
        lists.sync('Read book.', 'tasks')
        key = lists.rows('tasks')[0]['id']
        with patch.object(lists, 'today', return_value='2026-10-04'):
            lists.update('tasks', 'details', key, due='2026-10-04', priority='high', repeat='daily')
            lists.update('tasks', 'toggle', key)
            lists.sync('Read book.', 'tasks')
            self.assertTrue(lists.rows('tasks')[0]['completed'])
            self.assertEqual(lists.task_text('Read book.'), '')
        with patch.object(lists, 'today', return_value='2026-10-05'):
            self.assertFalse(lists.rows('tasks')[0]['completed'])
            self.assertEqual(lists.task_text('Read book.'), 'Read book.')
        with self.assertRaises(ValueError): lists.update('tasks', 'details', key, due='invalid')
        self.assertEqual(lists.rows('tasks')[0]['priority'], 'high')
