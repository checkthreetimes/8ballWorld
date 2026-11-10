"""Scheduled leaderboards and guild raids stay quiet; daily work still runs."""
import ast
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock


class BackgroundPostsTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        names = {'_post_daily_digest', '_engagement_loop'}
        nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec')

    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = sqlite3.connect(str(Path(self.folder.name) / 'daily.db'))
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE shadow_profiles (user_id, home_group, last_seen, message_count, msg_week_base, msg_month_base);
            CREATE TABLE players (user_id, username, total_exp, wins, kill_streak, level);
            CREATE TABLE pet_catches (user_id, username, species, rarity, is_shiny, was_new, chat_id, caught_at);
            CREATE TABLE bounties (claimed_by, expires_at);
            INSERT INTO players VALUES (1, 'Alice', 100, 2, 0, 5);
            INSERT INTO bounties VALUES (NULL, '2000-01-01');
        ''')
        self.db.execute('INSERT INTO shadow_profiles VALUES (1, -100, ?, 1, 0, 0)', (datetime.now().isoformat(),))
        self.db.commit()
        now = datetime.now()
        values = dict(msg_week_key=f'{now.isocalendar()[0]}-W{now.isocalendar()[1]}', msg_month_key=now.strftime('%Y-%m'))
        self.env = dict(_db=lambda: self.db, datetime=datetime, timedelta=timedelta,
            time=time, sqlite3=sqlite3, _ws_get=lambda key, default=None: values.get(key, time.time()),
            _ws_set=Mock(), get_weather=lambda: dict(name='Clear', exp_mod=1, dmg_mod=1),
            safe_int=lambda n: int(n or 0), _catch_log_conn=lambda: self.db,
            _get_king=lambda: None, _goal_check_reward=AsyncMock(return_value='Goal'),
            _lottery_draw=AsyncMock(return_value='Lottery'), ADMIN_ID=99, logger=Mock(),
            asyncio=NS(sleep=AsyncMock()), random=NS(random=lambda: 0), _daily_budget_ok=lambda *args: True)
        names = ('_pet_care_sweep', '_weather_watch', '_crate_scheduler', '_fortune_drop_scheduler',
                 '_chat_games_scheduler', '_fire_random_world_events', '_ambush_spawner',
                 '_weekly_guild_boss_sweep', '_oracle_attack_sweep', '_winback_sweep')
        self.env.update({name: AsyncMock() for name in names})
        exec(self.code, self.env)
        self.bot = NS(send_message=AsyncMock())

    async def test_daily_job_does_not_post_boards_but_settles_and_cleans_up(self):
        await self.env['_post_daily_digest'](self.bot)
        self.bot.send_message.assert_not_called()
        self.env['_goal_check_reward'].assert_awaited_once_with(self.bot)
        self.env['_lottery_draw'].assert_awaited_once_with(self.bot)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM bounties').fetchone()[0], 0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM digest_snap').fetchone()[0], 1)

    async def test_digest_reaches_broadcast_section_when_explicitly_requested(self):
        await self.env['_post_daily_digest'](self.bot, post_to_groups=True)
        self.bot.send_message.assert_awaited_once()
        self.assertEqual(self.bot.send_message.call_args.args[0], -100)
        self.assertIn('DAILY DIGEST', self.bot.send_message.call_args.args[1])

    async def test_heartbeat_does_not_start_guild_raids(self):
        self.env['asyncio'].sleep.side_effect = [None, asyncio.CancelledError()]
        with self.assertRaises(asyncio.CancelledError):
            await self.env['_engagement_loop'](self.bot)
        self.env['_weekly_guild_boss_sweep'].assert_not_called()
        self.env['_chat_games_scheduler'].assert_awaited_once()
        self.env['_fire_random_world_events'].assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
