"""Bounded integration checks and redacted observations from ordinary app use."""
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urljoin, urlsplit
import fcntl
import requests
from storage import write_json

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'data' / 'api_health.json'
RUN_LOCK = ROOT / 'data' / 'api_health_run.lock'
INTERVALS = (15,30,60,180,360,1440)
PUBLIC = ('Weather','UK news','Local news','Sport news')
OBSERVED = ('Bank transactions','Gmail','DVLA','Ticketmaster','Transport API','Football API','Bin collections','Google Docs')
HOSTS = {'api.open-meteo.com','news.google.com','feeds.bbci.co.uk','docs.google.com','calendar.google.com'}
_thread = None
_start_lock = Lock()


def stamp(): return datetime.now(timezone.utc).isoformat()


def age(value):
    try: return max(0, time.time()-datetime.fromisoformat(value).timestamp())
    except (ValueError,TypeError): return float('inf')


def options(settings=None):
    from receipt_settings import load_receipt_settings
    value=(settings if settings is not None else load_receipt_settings()).get('api_health',{})
    interval=value.get('interval_minutes',60)
    return {'enabled':value.get('enabled',True) is True,
            'interval_minutes':interval if type(interval) is int and interval in INTERVALS else 60}


def load():
    try:
        value=json.loads(FILE.read_text())
        if isinstance(value,dict) and isinstance(value.get('services'),dict): return value
    except (ValueError,OSError): pass
    return {'services':{}}


@contextmanager
def transaction():
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            value=load();yield value;write_json(FILE,value)
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def record(name,status='healthy',code=None,duration=None,mode='observed',reason=''):
    if name not in (*PUBLIC,*OBSERVED,'Google Calendar','Google Docs – tasks','Google Docs – exercises','Google Docs – food shop','Google Docs – subscriptions','Google Docs'):
        return
    if status not in {'healthy','degraded','failed'}: status='degraded'
    if mode not in {'active','observed'}:mode='observed'
    # These are fixed reason categories, never raw exception messages or URLs.
    if reason not in {'timeout','connection','http','invalid_response','unsafe_redirect','too_large','unavailable'}:reason=''
    code=code if type(code) is int and 100<=code<=599 else None
    duration=round(max(0,min(120000,duration)),1) if isinstance(duration,(int,float)) else None
    try:
        with transaction() as value:
            old=value['services'].get(name,{})
            if not isinstance(old,dict):old={}
            checked=stamp()
            history=old.get('history',[])
            if not isinstance(history,list):history=[]
            sample={'checked_at':checked,'status':status,'code':code,'duration_ms':duration,'mode':mode,'reason':reason}
            value['services'][name]={**sample,'history':(history+[sample])[-30:],
                                     'last_success':checked if status=='healthy' else old.get('last_success'),
                                     'failures':0 if status=='healthy' else int(old.get('failures',0))+1}
    except (OSError,ValueError,TypeError):
        logging.getLogger(__name__).warning('Could not save integration health status.')


def observed_call(name, function, *args, **kwargs):
    started=time.monotonic()
    try: response=function(*args,**kwargs)
    except requests.RequestException as error:
        record(name,'failed',duration=(time.monotonic()-started)*1000,
               reason='timeout' if isinstance(error,requests.Timeout) else 'connection')
        raise
    code=getattr(response,'status_code',None)
    if type(code) is int:
        record(name,'healthy' if 200<=code<300 else 'degraded' if code==429 else 'failed',code,
               (time.monotonic()-started)*1000,reason='' if 200<=code<300 else 'http')
    return response


def observed_request(name, method, *args, **kwargs):
    return observed_call(name, getattr(requests,method.lower()), *args, **kwargs)


def receipt_busy():
    for name in ('.print_now.lock','.live_preview.lock'):
        try:
            pid=int((ROOT/'data'/name).read_text().strip())
            if 0<pid<=2147483647:
                os.kill(pid,0)
                return True
        except PermissionError:return True
        except (OSError,ValueError):pass
    return False


def private_config():
    try:
        value=json.loads((ROOT/'passwords.json').read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def safe_url(url):
    parsed=urlsplit(url)
    return parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and (
        parsed.hostname in HOSTS or (parsed.hostname or '').endswith('.googleusercontent.com'))


def specifications(settings=None, private=None):
    from receipt_settings import load_receipt_settings
    from receipt.location_settings import DEFAULT_LOCATION,validate_location
    settings=settings if settings is not None else load_receipt_settings()
    private=private if private is not None else private_config()
    location=validate_location(settings.get('location',DEFAULT_LOCATION))
    specs=[('Weather','https://api.open-meteo.com/v1/forecast',{'latitude':location['latitude'],'longitude':location['longitude'],'current':'temperature_2m'},'weather'),
           ('UK news','https://news.google.com/rss?hl=en-GB&gl=GB&ceid=GB:en',None,'rss'),
           ('Local news',location['local_news_feed'],None,'rss'),
           ('Sport news','https://feeds.bbci.co.uk/sport/rss.xml',None,'rss')]
    docs=private.get('google_docs',{})
    if not isinstance(docs,dict):docs={}
    for key,label in [('todo_url','tasks'),('random_url','exercises'),('food_shop_url','food shop'),('subscriptions_url','subscriptions')]:
        value=docs.get(key,'')
        if not isinstance(value,str) or not value:continue
        match=re.search(r'/document/d/([A-Za-z0-9_-]+)',value)
        doc=match.group(1) if match else value
        if re.fullmatch(r'[A-Za-z0-9_-]+',doc):
            specs.append(('Google Docs – '+label,f'https://docs.google.com/document/d/{doc}/export?format=txt',None,'doc'))
    calendar=private.get('calendar',{})
    calendar=calendar.get('ical_url','') if isinstance(calendar,dict) else ''
    if isinstance(calendar,str) and calendar and urlsplit(calendar).hostname=='calendar.google.com' and safe_url(calendar):
        specs.append(('Google Calendar',calendar,None,'calendar'))
    return specs


def probe(spec):
    name,url,params,kind=spec;started=time.monotonic();code=None
    try:
        for redirect in range(4):
            if not safe_url(url):raise ValueError('unsafe_redirect')
            remaining=12-(time.monotonic()-started)
            if remaining<=0:raise ValueError('timeout')
            with requests.get(url,params=params,timeout=(min(3,remaining),min(6,remaining)),stream=True,allow_redirects=False) as response:
                code=response.status_code
                if code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('Location',''));params=None
                    continue
                if not 200<=code<300:
                    record(name,'degraded' if code==429 else 'failed',code,(time.monotonic()-started)*1000,'active','http');return
                content=bytearray()
                for chunk in response.iter_content(16384):
                    if time.monotonic()-started>12:raise ValueError('timeout')
                    content.extend(chunk)
                    if len(content)>512000:raise ValueError('too_large')
                body=content.decode('utf-8',errors='replace').lstrip('\ufeff').strip()
                if kind=='weather':
                    data=json.loads(body)
                    if not isinstance(data,dict) or not isinstance(data.get('current'),dict):raise ValueError('invalid_response')
                elif kind=='rss':
                    from services.safe_xml import parse_feed
                    root=parse_feed(content)
                    if root.tag.split('}')[-1] not in {'rss','feed'}:raise ValueError('invalid_response')
                elif kind=='calendar' and not body.startswith('BEGIN:VCALENDAR'):raise ValueError('invalid_response')
                elif kind=='doc' and ('text/html' in response.headers.get('Content-Type','').lower() or body.lower().startswith(('<!doctype','<html'))):raise ValueError('invalid_response')
                record(name,'healthy',code,(time.monotonic()-started)*1000,'active');return
        raise ValueError('unsafe_redirect')
    except requests.RequestException as error:
        reason='timeout' if isinstance(error,requests.Timeout) else 'connection'
    except ValueError as error:
        reason=str(error) if str(error) in {'timeout','too_large','unsafe_redirect'} else 'invalid_response'
    except Exception:
        reason='invalid_response'
    record(name,'failed',code,(time.monotonic()-started)*1000,'active',reason)


def check_once(force=False, service=None):
    config=options()
    if receipt_busy():return False
    if not config['enabled'] and not force:return False
    RUN_LOCK.parent.mkdir(parents=True,exist_ok=True)
    with RUN_LOCK.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        try:
            if service is None and age(load().get('last_cycle'))<(30 if force else config['interval_minutes']*60):return False
            with transaction() as value:value.update(running=True,started_at=stamp())
            completed=True
            try:
                specs = specifications()
                if service is not None:
                    specs = [spec for spec in specs if spec[0] == service]
                    if not specs: return False
                for spec in specs:
                    if receipt_busy():completed=False;break
                    with transaction() as value:value['current_service']=spec[0]
                    probe(spec)
            finally:
                with transaction() as value:
                    value['running']=False
                    if completed and service is None:value['last_cycle']=stamp()
            return True
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def running():
    try:
        with RUN_LOCK.open('r') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return True
            fcntl.flock(lock,fcntl.LOCK_UN)
    except OSError:pass
    return False


def monitor_loop(stop):
    while not stop.is_set():
        try:
            # Avoid competing with a physical print or live preview.
            if not receipt_busy():check_once()
        except Exception:logging.getLogger(__name__).warning('Integration health cycle failed.')
        stop.wait(30)


def start_monitor():
    global _thread
    with _start_lock:
        if _thread is None or not _thread.is_alive():
            _thread=Thread(target=monitor_loop,args=(Event(),),daemon=True,name='receipt-api-health')
            _thread.start()
        return _thread
