"""Exercise idle reward delivery without Telegram or a live database."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
import unittest
from unittest.mock import AsyncMock, Mock


class IdleNotificationTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        function = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                        and n.name == '_try_idle_reward')
        self.shadow = {'username': 'Alice', 'home_group': -100123}
        self.env = dict(time=time, datetime=datetime, timedelta=timedelta,
                        asyncio=asyncio, _auto_delete=AsyncMock(),
                        _idle_last_awarded={}, get_player=lambda uid: None,
                        _calc_idle_exp=Mock(side_effect=lambda secs, level: 50 if secs >= 1800 else 0),
                        get_shadow=lambda uid: self.shadow,
                        add_shadow_exp=Mock(), save_shadow=Mock(),
                        fmt_num=str, escape_markdown=lambda name: name)
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'main.py', 'exec'), self.env)
        self.bot = Mock(send_message=AsyncMock())

    def run_reward(self, group=None, minutes=65):
        asyncio.run(self.env['_try_idle_reward'](
            42, self.bot, (datetime.now() - timedelta(minutes=minutes)).isoformat(), group))

    def test_group_return_awards_silently(self):
        self.run_reward(-100999)
        self.bot.send_message.assert_not_called()
        self.env['_auto_delete'].assert_not_called()
        self.env['add_shadow_exp'].assert_called_once_with(self.shadow, 50)

    def test_dm_return_does_not_announce_or_award(self):
        self.run_reward()
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_not_called()

    def test_no_group_does_not_award(self):
        self.shadow['home_group'] = None
        self.run_reward()
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_not_called()

    def test_short_absence_is_silent(self):
        self.run_reward(-100999, minutes=10)
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_not_called()

    def test_message_timestamps_ignore_processing_delay(self):
        previous = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
        returned = previous + timedelta(hours=5, minutes=38, seconds=59)
        asyncio.run(self.env['_try_idle_reward'](
            42, self.bot, previous.isoformat(), -100123,
            returned_at=returned, display_name='Jesse'))
        self.env['_calc_idle_exp'].assert_called_once_with(5 * 3600 + 38 * 60 + 59, 1)
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_called_once_with(self.shadow, 50)

    def test_sub_hour_absence_awards_silently(self):
        self.run_reward(-100999, minutes=45)
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_called_once_with(self.shadow, 50)
        self.env['_auto_delete'].assert_not_called()

    def test_exact_hour_stays_silent_and_awards(self):
        previous = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)
        asyncio.run(self.env['_try_idle_reward'](
            42, self.bot, previous.isoformat(), -100123,
            returned_at=previous + timedelta(hours=1)))
        self.bot.send_message.assert_not_called()
        self.env['_auto_delete'].assert_not_called()
        self.env['add_shadow_exp'].assert_called_once_with(self.shadow, 50)

    def test_rapid_repeat_does_not_announce_or_award_twice(self):
        self.run_reward(-100999)
        self.run_reward(-100999)
        self.bot.send_message.assert_not_called()
        self.env['add_shadow_exp'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
