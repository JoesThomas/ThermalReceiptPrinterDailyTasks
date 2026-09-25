import requests
HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "ThermalReceiptPrinterDailyTasks/1.0"})
DEFAULT_TIMEOUT = 10

def get(url, *, timeout=DEFAULT_TIMEOUT, **kwargs): return HTTP.get(url, timeout=timeout, **kwargs)
def post(url, *, timeout=DEFAULT_TIMEOUT, **kwargs): return HTTP.post(url, timeout=timeout, **kwargs)
