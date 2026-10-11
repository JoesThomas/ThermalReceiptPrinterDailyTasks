"""Regression coverage for offline sources, clock changes and remaining meals."""
import copy
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services import source_cache, public_sources
from receipt.local_time import local_run, uk_receipt_time
from meals.remaining import needs_dinner


class ResilienceTests(unittest.TestCase):
    def test_timeout_uses_last_success_without_changing_its_age(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache, 'FILE', Path(folder)/'cache.json'):
            with patch.object(source_cache.time, 'time', return_value=1000):
                self.assertEqual(source_cache.get('Calendar', 'identity', lambda: [{'date':date(2026,10,5)}]), [{'date':date(2026,10,5)}])
            with patch.object(source_cache.time, 'time', return_value=1400):
                def timeout(): raise TimeoutError()
                self.assertEqual(source_cache.get('Calendar', 'identity', timeout)[0]['date'], date(2026,10,5))
                row=next(iter(source_cache.load().values()))
                self.assertEqual(row['saved_epoch'],1000)
                self.assertEqual(row['status'],'cached after error')
            with patch.object(source_cache.time, 'time', return_value=90000):
                with self.assertRaises(TimeoutError): source_cache.get('Calendar','identity',timeout)

    def test_partial_mailbox_does_not_erase_last_good_deliveries(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache, 'FILE', Path(folder)/'cache.json'):
            original=[{'item':'Needles','date':date(2026,10,5)}]
            with patch.object(source_cache.time,'time',return_value=1000):source_cache.get('Deliveries','identity',lambda:original)
            with patch.object(source_cache.time,'time',return_value=1400):
                self.assertEqual(source_cache.get('Deliveries','identity',lambda:([],'partial')),original)
                self.assertEqual(next(iter(source_cache.load().values()))['saved_epoch'],1000)

    def test_news_cache_cannot_cross_local_midnight(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache,'FILE',Path(folder)/'cache.json'):
            with patch('receipt.local_time.uk_today',return_value=date(2026,10,5)):
                public_sources.cached('UK news','feed',3,lambda:[{'headline':'Yesterday'}])
            with patch('receipt.local_time.uk_today',return_value=date(2026,10,6)):
                def unavailable():raise TimeoutError()
                with self.assertRaises(TimeoutError):public_sources.cached('UK news','feed',3,unavailable)

    def test_dst_gap_repeat_and_saved_utc_display(self):
        self.assertEqual(local_run(date(2026,3,29),1,30).strftime('%H:%M %Z'),'02:00 BST')
        repeated=local_run(date(2026,10,25),1,30)
        self.assertEqual(repeated.astimezone(timezone.utc).hour,0)
        self.assertEqual(repeated.fold,0)
        self.assertIn('00:30 BST',uk_receipt_time('2026-10-04T23:30:00Z'))

    def test_remaining_meals_react_to_confirmations_away_and_replacement(self):
        meal={'date':'2026-10-05','kind':'recipe','recipe':{'name':'Pasta'}}
        original=copy.deepcopy(meal)
        kwargs={'today':date(2026,10,5),'away':lambda day:False}
        self.assertTrue(needs_dinner(meal,confirmation=lambda day:None,**kwargs))
        self.assertFalse(needs_dinner(meal,confirmation=lambda day:{'recipe':'Different dinner'},**kwargs))
        self.assertFalse(needs_dinner(meal,today=date(2026,10,6),confirmation=lambda day:None,away=lambda day:False))
        self.assertFalse(needs_dinner(meal,today=date(2026,10,5),confirmation=lambda day:None,away=lambda day:True))
        self.assertEqual(meal,original)

    def test_calendar_recurring_events_keep_location_across_dst(self):
        from services.calendar_source import parse
        content='''BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:fixture\r
DTSTART;TZID=Europe/London:20261024T090000\r
DTEND;TZID=Europe/London:20261024T100000\r
RRULE:FREQ=DAILY;COUNT=3\r
SUMMARY:Lesson\r
LOCATION:Community hall\r
END:VEVENT\r
END:VCALENDAR\r
'''
        rows=parse(content,date(2026,10,24),3)
        self.assertEqual(len(rows),3)
        self.assertEqual([row['time'] for row in rows],['09:00-10:00']*3)
        self.assertTrue(all(row['location']=='Community hall' for row in rows))
        self.assertEqual(rows[0]['start_dt'].utcoffset().total_seconds(),3600)
        self.assertEqual(rows[1]['start_dt'].utcoffset().total_seconds(),0)

    def test_shopping_retains_shared_items_lunch_extras_and_pantry_filter(self):
        from meals import legacy_planner as meals
        plan={'meals':[
            {'date':'2026-10-05','kind':'recipe','recipe':{'name':'Eaten','ingredients':['rice','chicken'],'lunch':{'extra_ingredients':['wraps']}}},
            {'date':'2026-10-06','kind':'recipe','recipe':{'name':'Next','ingredients':['rice','fish','salt']}}]}
        with patch('receipt.local_time.uk_today',return_value=date(2026,10,5)), patch('receipt.lifestyle.skip_meal',return_value=False), patch('web_control.live_data.meal_confirmation',side_effect=lambda day: {'recipe':'Eaten'} if day==date(2026,10,5) else None), patch.object(meals,'_pantry_has',side_effect=lambda item:item=='salt'), patch.object(meals,'_override_for',return_value=None):
            items=[item for group in meals.build_shopping_list(plan).values() for item in group]
        self.assertEqual(set(items),{'rice','fish','wraps'})

    def test_malformed_news_falls_back_to_last_parsed_stories(self):
        from services.news_source import stories
        identity=lambda value:value
        def collect():
            return stories('feed',sanitize=identity,compact_summary=identity,useful_summary=lambda *args:False)
        valid=b'<rss><channel><item><title>News headline</title><description>News headline</description></item></channel></rss>'
        with tempfile.TemporaryDirectory() as folder, patch.object(source_cache,'FILE',Path(folder)/'cache.json'):
            with patch.object(source_cache.time,'time',return_value=1000), patch('services.news_source.download',return_value=valid):
                original=public_sources.cached('UK news','feed',3,collect)
            with patch.object(source_cache.time,'time',return_value=1400), patch('services.news_source.download',return_value=b'<rss><broken>'):
                self.assertEqual(public_sources.cached('UK news','feed',3,collect),original)
                self.assertEqual(original[0]['summary'],'')
