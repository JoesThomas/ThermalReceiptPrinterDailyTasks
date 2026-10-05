import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from services import bin_collections as bins


class BinCollectionTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.patches=[patch.object(bins,'FILE',Path(self.folder.name)/'bins.json'),
                      patch.object(bins,'today',return_value=date(2026,10,4)),
                      patch.object(bins,'now',return_value=datetime(2026,10,4,12,tzinfo=timezone.utc))]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.folder.cleanup()

    def configure(self,provider='birmingham',manual=None):
        bins.configure(True,provider,'Example Road','B1 1AA','100000000001',manual or [])

    def test_reminders_day_before_and_fortnightly_manual(self):
        self.configure('manual',[{'date':'2026-10-05','bin':'General waste','repeat':7},
                                 {'date':'2026-10-05','bin':'Recycling','repeat':14}])
        state=bins.load()
        self.assertEqual(bins.due_on(state,date(2026,10,5)),['General waste','Recycling'])
        self.assertEqual(bins.due_on(state,date(2026,10,12)),['General waste'])
        self.assertEqual(len(bins.reminder_lines(state,date(2026,10,4))),2)
        self.assertEqual(bins.reminder_lines(state,date(2026,10,5)),[])
        self.assertEqual(bins.due_on(state,date(2026,9,28)),[])

    def test_address_change_clears_previous_dates(self):
        self.configure()
        with bins.transaction() as state:
            state['collections']=[{'date':'2026-10-05','bin':'Rubbish'}]
            state['last_success']=bins.now().isoformat()
        bins.configure(True,'birmingham','Different Road','B2 2BB','100000000002',[])
        state=bins.load()
        self.assertEqual(state['collections'],[])
        self.assertEqual(state['last_success'],'')

    def test_council_fetch_uses_exact_dates_in_both_column_orders(self):
        self.configure()
        parser=bins.CouncilHTML()
        parser.feed('<table class="data-table"><tr><th>Date</th><th>Type</th></tr><tr><td>Monday 5 October</td><td>Rubbish</td></tr><tr><td>Food</td><td>Mon 05/10/2026</td></tr></table>')
        with patch.object(bins,'council_html',return_value=parser) as fetch:
            result=bins.fetch(bins.load())
        self.assertEqual({row['bin'] for row in result},{'Food','Rubbish'})
        self.assertTrue(all(row['date']=='2026-10-05' for row in result))
        self.assertEqual(fetch.call_args.args[0]['uprn'],'100000000001')

    def test_year_crossover_and_explicit_year(self):
        self.assertEqual(bins.collection_date('Friday 1 January',date(2026,12,31)),date(2027,1,1))
        self.assertEqual(bins.collection_date('31 December',date(2027,1,1)),date(2026,12,31))
        self.assertEqual(bins.collection_date('2026-01-01',date(2026,12,31)),date(2026,1,1))
        self.assertEqual(bins.collection_date('29 February',date(2028,2,1)),date(2028,2,29))

    def test_failure_preserves_recent_cache_but_old_cache_is_not_printed(self):
        self.configure()
        with bins.transaction() as state:
            state.update(collections=[{'date':'2026-10-05','bin':'Rubbish'}],last_success=bins.now().isoformat())
        with patch.object(bins,'fetch',side_effect=bins.requests.Timeout):
            state=bins.refresh(force=True)
        self.assertEqual(bins.due_on(state,date(2026,10,5)),['Rubbish'])
        self.assertTrue(any('cached' in line for line in bins.reminder_lines(state)))
        state['last_success']=(bins.now()-timedelta(days=3)).isoformat()
        self.assertEqual(bins.due_on(state,date(2026,10,5)),[])
        self.assertFalse(any('Put out' in line for line in bins.reminder_lines(state)))

    def test_refresh_is_cached_and_disabled_never_calls_network(self):
        with patch.object(bins,'fetch') as fetch:
            bins.refresh();fetch.assert_not_called()
        self.configure()
        with patch.object(bins,'fetch',return_value=[{'date':'2026-10-05','bin':'Food'}]) as fetch:
            bins.refresh();bins.refresh();self.assertEqual(fetch.call_count,1)

    def test_invalid_input_and_manual_parse(self):
        self.assertEqual(bins.postcode('b1 1aa'),'B1 1AA')
        for code in ('','http://localhost','B1'):
            with self.assertRaises(ValueError):bins.postcode(code)
        with self.assertRaises(ValueError):bins.configure(True,'birmingham','Example','B1 1AA','',[])
        rows=bins.parse_manual('2026-10-05 | Food waste | 7')
        self.assertEqual(rows[0]['repeat'],7)
        with self.assertRaises(ValueError):bins.parse_manual('2026-10-05 | Food waste | 6')
        with self.assertRaises(ValueError):bins.parse_manual('2026-02-30 | Food waste')

    def test_postcode_lookup_preserves_address_option_labels(self):
        parser=bins.CouncilHTML();parser.feed('<select name="uprn"><option value="">Choose</option><option value="100000000001">Example &amp; Road</option></select>')
        with patch.object(bins,'council_html',return_value=parser):
            self.assertEqual(bins.addresses('B1 1AA')[0],{'uprn':'100000000001','address':'Example & Road'})

    def test_manual_web_save_needs_no_address_and_keeps_invalid_draft(self):
        from flask import Flask
        from web_control.bin_tools import register
        app = Flask(__name__, template_folder=str(Path('web_control/templates').resolve()))
        app.secret_key = 'test-only'
        app.jinja_env.globals['csrf_token'] = lambda: 'test'
        register(app, lambda view: view)
        with app.test_client() as client, patch.object(bins, 'refresh') as refresh:
            response = client.post('/bins/manual', data={'manual': '2026-10-05 | Recycling | 14', 'enabled': 'on'})
            self.assertEqual(response.status_code, 302)
            state = bins.load()
            self.assertEqual(state['provider'], 'manual')
            self.assertTrue(state['enabled'])
            self.assertEqual(state['address'], '')
            self.assertEqual(bins.due_on(state, date(2026,10,5)), ['Recycling'])
            refresh.assert_not_called()
            with patch('web_control.bin_tools.render_template', return_value='draft retained') as render:
                response = client.post('/bins/manual', data={'manual': 'bad date'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(render.call_args.kwargs['manual'], 'bad date')
            self.assertEqual(bins.load()['manual'], state['manual'])
