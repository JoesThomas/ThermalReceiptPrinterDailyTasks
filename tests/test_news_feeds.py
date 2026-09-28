import unittest
from datetime import datetime, timezone, timedelta
from services.news_feeds import is_bbc_article, select_bbc_articles

NOW = datetime(2026, 9, 27, tzinfo=timezone.utc)


def story(title, link, published=NOW):
    return {'headline': title, 'link': link, 'published': published, 'summary': ''}


class NewsFeedTests(unittest.TestCase):
    def test_local_accepts_article_without_city_in_headline(self):
        article = story('Council approves new city centre housing plan',
                        'https://www.bbc.co.uk/news/articles/c1234567890')
        self.assertTrue(is_bbc_article(article, 'local'))
        regional = story('Council approves plans for new coastal flood barriers',
                         'https://www.bbc.co.uk/news/england/merseyside/articles/c1234567890')
        self.assertTrue(is_bbc_article(regional, 'local'))

    def test_rejects_hubs_previews_live_and_other_publishers(self):
        cases = [
            story('Birmingham and Black Country latest news',
                  'https://www.bbc.co.uk/news/england/birmingham_and_black_country'),
            story('Live: Council meeting and reaction today',
                  'https://www.bbc.co.uk/news/live/c1234567890'),
            story('Watch: All the latest news today',
                  'https://www.bbc.co.uk/news/articles/c1234567890'),
            story('Preview: Aston Villa against Wolves match',
                  'https://www.bbc.co.uk/sport/football/articles/c1234567890'),
            story('Council approves new city centre housing plan',
                  'https://example.com/news/articles/c1234567890'),
            story('Aston Villa football club results and latest news',
                  'https://www.bbc.co.uk/sport/football/teams/aston-villa'),
            story('Council approves new city centre housing plan',
                  'https://www.bbc.co.uk/news/articles/c1234567890', None),
        ]
        self.assertFalse(any(is_bbc_article(item, 'local') for item in cases))
        self.assertFalse(is_bbc_article(cases[3], 'sport'))
        self.assertFalse(is_bbc_article(cases[5], 'sport'))

    def test_sport_is_separate_and_keeps_recent_stories(self):
        sport = story('Villa sign defender on long-term contract',
                      'https://www.bbc.co.uk/sport/football/articles/c1234567890')
        local = story('Council agrees plans for new housing',
                      'https://www.bbc.co.uk/news/articles/c9876543210',
                      NOW + timedelta(hours=1))
        self.assertEqual(select_bbc_articles([sport, local, sport], 'sport', 3), [sport])
        self.assertEqual(select_bbc_articles([sport, local], 'local', 3), [local])

if __name__ == '__main__':
    unittest.main()
