import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from finance import transaction_sources as sources


class TransactionSourceTests(unittest.TestCase):
    def test_default_first_monzo_and_other_providers_unchanged(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(sources,'FILE',Path(folder)/'sources.json'):
            ids=['one','two','three']
            self.assertEqual(sources.select('MONZO',ids),['one'])
            self.assertEqual(sources.select('HSBC',ids),ids)
            self.assertEqual(sources.select('AMEX',ids),ids)
            self.assertEqual(sources.select('MONZO',[]),[])
            sources.save('all')
            self.assertEqual(sources.select('MONZO',ids),ids)
            self.assertEqual(sources.FILE.stat().st_mode&0o777,0o600)
            with self.assertRaises(ValueError):sources.save('invalid')
            self.assertEqual(sources.load()['monzo'],'all')
