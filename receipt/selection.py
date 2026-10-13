"""Validate explicit multi-page requests without changing the default layout."""
from receipt.capture import PAGE_NAMES


def validate(pages):
    if not isinstance(pages,list) or not 1<=len(pages)<=4 or any(p not in PAGE_NAMES for p in pages) or len(set(pages))!=len(pages):
        raise ValueError('Choose one or more distinct receipt sections.')
    return pages


def apply_preferences(pages, settings):
    pages = validate(pages)
    if not settings.get('features', {}).get('meals', True):
        pages = [page for page in pages if page != 'food']
        if not pages:
            raise ValueError('Meals on receipt is turned off. Enable it in Settings before generating a food page.')
    return pages
