import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from web_control import future_tasks

class FutureTasksTests(unittest.TestCase):
    def test_edit_complete_reopen_delete_and_validation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(future_tasks, 'TASKS_FILE', Path(directory) / 'tasks.json'):
            self.assertEqual(future_tasks.load_tasks(), [])
            task = future_tasks.update_task(title='Example goal', next_step='First step')[0]
            future_tasks.update_task(task['id'], title='Updated goal')
            self.assertEqual(future_tasks.load_tasks()[0]['title'], 'Updated goal')
            self.assertTrue(future_tasks.update_task(task['id'], action='toggle')[0]['done'])
            self.assertFalse(future_tasks.update_task(task['id'], action='toggle')[0]['done'])
            with self.assertRaises(ValueError):
                future_tasks.update_task(title='x' * 161)
            self.assertEqual(len(future_tasks.load_tasks()), 1)
            self.assertEqual(future_tasks.update_task(task['id'], action='delete'), [])

    def test_receipt_skips_completed_goals(self):
        source = ast.parse(Path('services/live_pipeline.py').read_text())
        node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'print_future_tasks')
        lines = []
        namespace = dict(print_line=lambda *a: None, centre=lambda p,t: lines.append(t), left=lambda p,t: lines.append(t), print_wrapped=lambda p,t,width: lines.append((t,width)), printer_safe_text=lambda t:t)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<receipt>', 'exec'), namespace)
        namespace['print_future_tasks'](SimpleNamespace(set=lambda **kw:None), [{'title':'Pending', 'next_step':'Start here', 'done':False}, {'title':'Finished','next_step':'','done':True}])
        self.assertEqual(lines, ['FUTURE TASKS', ('[ ] Pending',40), ('Next: Start here',40)])
