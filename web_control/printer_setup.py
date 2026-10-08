"""Offline installation checks usable on a Pi or the development machine."""
import importlib.util
import os
import platform
import sys
from pathlib import Path


def installation_checks(root):
    from receipt.printer import DEFAULT_NETWORK_HOST, DEFAULT_NETWORK_PORT
    from receipt.local_time import uk_now
    checks = [{'name':'Python', 'ok':sys.version_info >= (3,11), 'detail':platform.python_version()},
              {'name':'Local scheduling', 'ok':True, 'detail':uk_now().strftime('%d %b %H:%M %Z')}]
    for name in ('flask','waitress','escpos','requests','icalendar'):
        checks.append({'name':name, 'ok':importlib.util.find_spec(name) is not None, 'detail':'Required Python dependency'})
    for name in ('data','logs'):
        path=root/name
        checks.append({'name':name+' storage', 'ok':os.access(path if path.exists() else root,os.W_OK), 'detail':'Must be writable by the service user'})
    try:
        port=int(os.environ.get('RECEIPT_PRINTER_PORT',DEFAULT_NETWORK_PORT))
        host=os.environ.get('RECEIPT_PRINTER_HOST',DEFAULT_NETWORK_HOST).strip()
        valid=bool(host) and 1<=port<=65535
    except ValueError: valid=False
    checks.append({'name':'Printer configuration', 'ok':valid, 'detail':'Network address/port configured; reachability checked separately'})
    checks.append({'name':'Host platform', 'ok':True, 'detail':platform.system()+' '+platform.machine()+'; physical Pi reboot/reconnection testing still required'})
    return checks
