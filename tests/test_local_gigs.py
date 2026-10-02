import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from services import local_gigs as gigs

LOCATION = {'name':'Example city','latitude':52.48,'longitude':-1.90}
DAY = date(2026,10,1)

def event(name='Example gig', **kw):
    data = {'name':name,'dates':{'start':{'localDate':'2026-10-01','localTime':'19:30:00'},'status':{'code':'onsale'}},
            'classifications':[{'segment':{'name':'Music'}}], 'url':'https://example.com/tickets',
            '_embedded':{'venues':[{'name':'Example venue','location':{'latitude':'52.48','longitude':'-1.90'}}]}}
    data.update(kw)
    return data

class FakeResponse:
    def __init__(self,data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,*args): return json.dumps(self.data).encode()

class LocalGigsTests(unittest.TestCase):
    def setUp(self): gigs._CACHE.clear()
    def test_filters_wrong_dates_cancelled_sport_and_distance(self):
        wrong = event('Other date',dates={'start':{'localDate':'2026-10-02'}})
        cancelled = event('Cancelled',dates={'start':{'localDate':'2026-10-01'},'status':{'code':'cancelled'}})
        sport=event('Sports',classifications=[{'segment':{'name':'Sports'}}])
        far=event('Far',_embedded={'venues':[{'name':'Far venue','location':{'latitude':51.5,'longitude':0}}]})
        result=gigs.normalise([event(),event(),wrong,cancelled,sport,far],DAY,LOCATION,25)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['time'],'19:30')
        self.assertEqual(result[0]['distance'],0)
    def test_time_tbc_and_safe_links(self):
        row=event(url='javascript:alert(1)', dates={'start':{'localDate':DAY.isoformat(),'timeTBA':True,'localTime':'18:00:00'}})
        result=gigs.normalise([row],DAY,LOCATION,25)[0]
        self.assertEqual(result['time'],'')
        self.assertEqual(result['url'],'')
    def test_local_date_request_cache_and_location_changes(self):
        payload={'_embedded':{'events':[event()]},'page':{'totalPages':1}}
        with patch.object(gigs,'api_key',return_value='test-key'),patch.object(gigs,'urlopen',return_value=FakeResponse(payload)) as fetch:
            result=gigs.get_gigs(LOCATION,DAY)
            self.assertEqual(result['status'],'ok')
            self.assertEqual(len(result['events']),1)
            url=fetch.call_args.args[0]
            self.assertIn('localStartDateTime=2026-10-01T00%3A00%3A00%2C2026-10-01T23%3A59%3A59',url)
            self.assertIn('geoPoint=',url)
            gigs.get_gigs(LOCATION,DAY)
            self.assertEqual(fetch.call_count,1)
            gigs.get_gigs(dict(LOCATION,latitude=53),DAY)
            self.assertEqual(fetch.call_count,2)
    def test_unavailable_and_partial_are_not_empty_success(self):
        with patch.object(gigs,'api_key',return_value='test-key'),patch.object(gigs,'urlopen',side_effect=RuntimeError('secret-url')):
            result=gigs.get_gigs(LOCATION,DAY)
            self.assertEqual(result['status'],'unavailable')
            self.assertNotIn('secret-url',str(result))
        gigs._CACHE.clear()
        with patch.object(gigs,'api_key',return_value='test-key'),patch.object(gigs,'urlopen',side_effect=[FakeResponse({'_embedded':{'events':[event()]},'page':{'totalPages':2}}),RuntimeError()]):
            result=gigs.get_gigs(LOCATION,DAY)
            self.assertEqual(result['status'],'partial')
            self.assertEqual(len(result['events']),1)
            self.assertIn('LISTINGS INCOMPLETE',gigs.receipt_lines(result))
    def test_private_configuration_and_environment_key(self):
        with tempfile.TemporaryDirectory() as d,patch.object(gigs,'CONFIG_FILE',Path(d)/'config.json'),patch.dict('os.environ',{},clear=True):
            self.assertEqual(gigs.get_gigs(LOCATION,DAY)['status'],'not_configured')
            gigs.save_api_key('ExampleKey')
            self.assertEqual(gigs.api_key(),'ExampleKey')
            gigs.save_api_key('')
            self.assertEqual(gigs.api_key(),'ExampleKey')
            with patch.dict('os.environ',{'TICKETMASTER_API_KEY':'EnvironmentKey'}):
                gigs.save_api_key('')
                self.assertEqual(gigs.api_key(),'EnvironmentKey')
            gigs.save_api_key('',clear=True)
            self.assertEqual(gigs.api_key(),'')
    def test_receipt_wrapping_limits_and_empty_source(self):
        result={'events':[{'name':'Example gig '*10,'venue':'Example venue','time':'19:30'}]*10,'status':'ok','location':'Example city','radius':25,'truncated':False}
        lines=gigs.receipt_lines(result,2)
        self.assertTrue(all(len(line)<=40 for line in lines))
        self.assertIn('+8 MORE ON WEB GIGS PAGE',lines)
        result['events']=[]
        self.assertEqual(gigs.receipt_lines(result), [])
    def test_geohash_reference(self):
        self.assertTrue(gigs.geohash(42.6,-5.6).startswith('ezs42'))
