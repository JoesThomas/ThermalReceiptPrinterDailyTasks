"""News rendering; compatibility helpers are injected by the live facade."""

def _print_news_stories(printer, heading, stories, include_summary=None, *, _context):
    _news_summary_is_useful = _context.get('_news_summary_is_useful')
    left = _context.get('left')
    print_line = _context.get('print_line')
    print_wrapped = _context.get('print_wrapped')
    if not stories:
        return
    print_line(printer, '=')
    printer.set(bold=True)
    left(printer, heading)
    printer.set(bold=False)
    for index, story in enumerate(stories[:5], 1):
        if index > 1:
            printer.text('\n')
        headline = story.get('headline', '')
        summary = story.get('summary', '')
        print_wrapped(printer, f'{index}. {headline}', width=40)
        if include_summary and _news_summary_is_useful(headline, summary):
            print_wrapped(printer, summary, width=40)

def print_news(printer, stories, *, _context):
    _print_news_stories = _context.get('_print_news_stories')
    _print_news_stories(printer, 'UK NEWS', stories, include_summary=False)

def print_local_news(printer, stories, label=None, *, _context):
    _print_news_stories = _context.get('_print_news_stories')
    _print_news_stories(printer, f'BBC {label.upper()}', stories, include_summary=False)

def print_sport_news(printer, stories, *, _context):
    _print_news_stories = _context.get('_print_news_stories')
    _print_news_stories(printer, 'SPORT', stories)
