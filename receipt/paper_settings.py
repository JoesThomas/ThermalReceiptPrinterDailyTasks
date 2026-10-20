"""Local roll-consumption assumptions and restart-applied printer geometry."""
from copy import deepcopy
import math
import os
from pathlib import Path

FILE = Path(os.environ.get('RECEIPT_PAPER_SETTINGS', str(Path(__file__).resolve().parents[1] / 'data' / 'printer_paper.json')))
PRESETS = {
    '80mm': dict(paper_width_mm=80, columns=48, printable_pixels=576, dpi=203, font_dots=12),
    '58mm': dict(paper_width_mm=58, columns=30, printable_pixels=384, dpi=203, font_dots=12),
}
GEOMETRY_KEYS = tuple(PRESETS['80mm'])
DEFAULT = dict(PRESETS['80mm'], preset='80mm', roll_length_m=80.0, prints_per_week=7.0,
               waste_percent=5.0, line_mm=3.75, cutter_mm=15.0)


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('Paper settings must be an object.')
    result = deepcopy(DEFAULT)
    result.update({key: value[key] for key in DEFAULT if key in value})
    if not isinstance(result['preset'], str) or result['preset'] not in {*PRESETS, 'custom'}:
        raise ValueError('Choose an 80 mm, 58 mm or custom printer profile.')
    limits = dict(paper_width_mm=(40,120), columns=(20,80), printable_pixels=(256,1024),
                  dpi=(180,600), font_dots=(8,32), roll_length_m=(1,1000),
                  prints_per_week=(0,70), waste_percent=(0,50), line_mm=(1,10), cutter_mm=(0,50))
    for key, (low, high) in limits.items():
        number = result[key]
        if isinstance(number, bool) or not isinstance(number, (int,float)) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'Invalid {key.replace("_", " ")}: use {low} to {high}.')
    for key in ('columns','printable_pixels','dpi','font_dots'):
        if int(result[key]) != result[key]:
            raise ValueError(f'{key.replace("_", " ").title()} must be a whole number.')
        result[key] = int(result[key])
    # Upgrade the previous standard 80 mm profile after the successful 48-column
    # physical test. Custom profiles retain their explicitly chosen dimensions.
    if result['preset'] == '80mm' and all(result[key] == number for key, number in
        dict(paper_width_mm=80, columns=46, printable_pixels=576, dpi=203, font_dots=12).items()):
        result['columns'] = 48
    if result['printable_pixels'] % 8:
        raise ValueError('Printable width must be a multiple of eight dots.')
    if result['columns'] * result['font_dots'] > result['printable_pixels']:
        raise ValueError('Text columns exceed the printer printable width.')
    if result['printable_pixels'] * 25.4 / result['dpi'] > result['paper_width_mm']:
        raise ValueError('Printable area exceeds the paper width at this resolution.')
    return result


def store():
    from storage import PrivateStore
    return PrivateStore(FILE, default=lambda: deepcopy(DEFAULT), validate=validate, max_bytes=16384)


def state():
    try:
        return validate(store().read()), None
    except (OSError, ValueError):
        return deepcopy(DEFAULT), 'Paper settings could not be read. Using the 80 mm defaults; review and save the settings.'


def load():
    return state()[0]


def save(value):
    from storage import file_lock, write_json
    result = validate(value)
    with file_lock(FILE):
        write_json(FILE, result)
    return result


def geometry(value):
    return {key: value[key] for key in GEOMETRY_KEYS}
