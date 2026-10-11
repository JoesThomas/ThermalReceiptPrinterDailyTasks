import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from services import api_health as health


class APIHealthTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.patches=[patch.object(health,'ROOT',self.root),patch.object(health,'FILE',self.root/'data'/'health.json'),
                      patch.object(health,'RUN_LOCK',self.root/'data'/'run.lock')]
        for item in self.patches:item.start()
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.folder.cleanup()
    def response(self,body=b'{"current":{"temperature_2m":12}}',code=200,headers=None):
        value=SimpleNamespace(status_code=code,headers=headers or {},iter_content=lambda size:[body])
        class Context:
            def __enter__(self):return value
            def __exit__(self,*args):pass
        return Context()

    def test_probe_validates_weather_and_records_no_body_or_url(self):
        with patch.object(health.requests,'get',return_value=self.response()) as get:
            health.probe(('Weather','https://api.open-meteo.com/v1/forecast',None,'weather'))
        row=health.load()['services']['Weather']
        self.assertEqual(row['status'],'healthy')
        self.assertEqual(row['mode'],'active')
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        raw=health.FILE.read_text()
        self.assertNotIn('temperature_2m',raw);self.assertNotIn('https://',raw)

    def test_timeout_http_auth_rate_limit_and_invalid_body(self):
        with patch.object(health.requests,'get',side_effect=health.requests.Timeout('SECRET')):
            health.probe(('Weather','https://api.open-meteo.com/v1/forecast',None,'weather'))
        self.assertEqual(health.load()['services']['Weather']['reason'],'timeout')
        self.assertNotIn('SECRET',health.FILE.read_text())
        for code,status in ((403,'failed'),(429,'degraded')):
            with patch.object(health.requests,'get',return_value=self.response(code=code)):
                health.probe(('Weather','https://api.open-meteo.com/v1/forecast',None,'weather'))
            self.assertEqual(health.load()['services']['Weather']['status'],status)
        with patch.object(health.requests,'get',return_value=self.response(b'<html>sign in</html>')):
            health.probe(('Weather','https://api.open-meteo.com/v1/forecast',None,'weather'))
        self.assertEqual(health.load()['services']['Weather']['reason'],'invalid_response')

    def test_redirect_cannot_reach_local_network(self):
        with patch.object(health.requests,'get',return_value=self.response(code=302,headers={'Location':'http://127.0.0.1/secret'})) as get:
            health.probe(('Weather','https://api.open-meteo.com/v1/forecast',None,'weather'))
        self.assertEqual(get.call_count,1)
        self.assertEqual(health.load()['services']['Weather']['status'],'failed')

    def test_rss_dtd_and_body_limit_fail_closed(self):
        for body in (b'<!DOCTYPE rss [<!ENTITY leak SYSTEM "file:///etc/passwd">]><rss>&leak;</rss>',b'x'*512001):
            with patch.object(health.requests,'get',return_value=self.response(body)):
                health.probe(('UK news','https://news.google.com/rss',None,'rss'))
            self.assertEqual(health.load()['services']['UK news']['status'],'failed')

    def test_history_is_bounded_and_failed_health_store_does_not_break_calls(self):
        for _ in range(35):health.record('Gmail','failed',reason='connection')
        health.record('Gmail','healthy')
        row=health.load()['services']['Gmail']
        self.assertEqual(len(row['history']),30);self.assertEqual(row['failures'],0)
        response=SimpleNamespace(status_code=200)
        with patch('services.api_health.write_json',side_effect=OSError):
            self.assertIs(health.observed_call('DVLA',lambda:response),response)

    def test_interval_disable_and_print_job_skip(self):
        specs=[('Weather','https://api.open-meteo.com/v1/forecast',None,'weather')]
        with patch.object(health,'specifications',return_value=specs),patch.object(health,'probe') as probe,patch.object(health,'options',return_value={'enabled':True,'interval_minutes':60}):
            self.assertTrue(health.check_once());self.assertFalse(health.check_once());self.assertEqual(probe.call_count,1)
        with patch.object(health,'options',return_value={'enabled':False,'interval_minutes':60}),patch.object(health,'probe') as probe:
            self.assertFalse(health.check_once());probe.assert_not_called()
        with patch.object(health,'receipt_busy',return_value=True),patch.object(health,'probe') as probe:
            self.assertFalse(health.check_once(force=True));probe.assert_not_called()

    def test_only_safe_configured_google_endpoints_are_added(self):
        private={'google_docs':{'todo_url':'https://docs.google.com/document/d/test_doc/edit'},'calendar':{'ical_url':'http://127.0.0.1/private'}}
        names={s[0] for s in health.specifications(private=private)}
        self.assertIn('Google Docs – tasks',names);self.assertNotIn('Google Calendar',names)
        self.assertFalse(health.safe_url('https://docs.google.com.evil.test/path'))

    def test_old_dead_receipt_lock_does_not_pause_monitor(self):
        (self.root/'data').mkdir();(self.root/'data'/'.print_now.lock').write_text('2147483647')
        with patch.object(health.os,'kill',side_effect=ProcessLookupError):self.assertFalse(health.receipt_busy())
