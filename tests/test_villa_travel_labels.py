from datetime import datetime
from unittest import TestCase
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from services import villa


class VillaTravelTests(TestCase):
    def render(self, trains=None, error=None):
        kickoff = datetime(2026, 10, 10, 15, tzinfo=ZoneInfo('Europe/London'))
        lines = []
        with patch.object(villa, 'get_villa_matchday_trains', return_value=trains, side_effect=error):
            villa.print_villa_matchday(Mock(), {'is_home': True, 'kickoff': kickoff},
                include_trains=True, left=lambda p, s: lines.append(s),
                centre=Mock(), line=Mock(), safe_text=str)
        return '\n'.join(lines)

    def test_scheduled_service_never_invents_live_status(self):
        output = self.render([{'departure': datetime(2026, 10, 10, 13), 'platform': '-',
                             'expected_departure': None, 'arrival': datetime(2026, 10, 10, 13, 25)}])
        self.assertIn('Platform TBC', output)
        self.assertIn('SCHEDULED', output)
        self.assertNotIn('ON TIME', output)
        self.assertIn('Aston arrival: 13:25 (scheduled)', output)

    def test_cancelled_status_takes_priority_over_estimate(self):
        output = self.render([{'departure': datetime(2026, 10, 10, 13), 'status': 'CANCELLED',
                             'expected_departure': datetime(2026, 10, 10, 13)}])
        self.assertIn('CANCELLED', output)
        self.assertNotIn('ON TIME', output)

    def test_failed_and_empty_lookup_remain_visible(self):
        self.assertIn('Train times unavailable', self.render(error=RuntimeError('missing key')))
        self.assertIn('No trains returned', self.render([]))

    def test_arrival_is_read_at_aston_not_departure_station(self):
        departures = Mock()
        departures.json.return_value = {'departures': {'all': [{
            'aimed_departure_time': '13:00', 'service_timetable': {
                'id': 'https://transportapi.com/v3/uk/train/service/train_uid:X/2026-10-10/timetable.json?app_key=old'}}]}}
        timetable = Mock()
        timetable.json.return_value = {'stops': [
            {'station_code': 'BRV', 'aimed_arrival_time': '12:59'},
            {'station_code': 'AST', 'aimed_arrival_time': '13:25'}]}
        with patch.object(villa, 'get', side_effect=[departures, timetable]) as get:
            trains = villa.get_villa_matchday_trains(datetime(2026, 10, 10, 15, tzinfo=ZoneInfo('Europe/London')), 'id', 'key')
        self.assertEqual(trains[0]['arrival'].strftime('%H:%M'), '13:25')
        self.assertIsNone(trains[0]['expected_departure'])
        self.assertNotIn('app_key', get.call_args.args[0])
