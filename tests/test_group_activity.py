"""Real SQLite persistence and event routing for group-only away tracking."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


class GroupActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'main.py').read_text())
        names = {'_record_group_message', '_group_activity_pre_filter', 'save_shadow'}
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in names]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec')
        init = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'init_db')
        cls.schema = next(n.value for n in ast.walk(init) if isinstance(n, ast.Constant)
                          and isinstance(n.value, str)
                          and 'CREATE TABLE IF NOT EXISTS group_message_activity' in n.value)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name) / 'activity.db')
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute(self.schema)
        self.db.execute('''CREATE TABLE shadow_profiles (
            user_id INTEGER PRIMARY KEY, username, level, exp, total_exp, message_count,
            passive_cooldowns, ascended, last_seen, last_pool, pending_items, pet_notify_ts, home_group)''')
        self.env = dict(_connect_db=lambda: sqlite3.connect(self.path), _db=lambda: self.db,
            datetime=datetime, timezone=timezone, asyncio=asyncio, Update=object,
            ContextTypes=SimpleNamespace(DEFAULT_TYPE=object),
            is_banned=lambda uid: False, logger=Mock(),
            get_or_create_shadow=Mock(), _try_idle_reward=AsyncMock(),
            safe_int=lambda n: int(n or 0), _INT_SAFE_MAX=2**63-1)
        exec(self.code, self.env)
        self.record = self.env['_record_group_message']

    def test_independent_users_and_groups(self):
        self.assertIsNone(self.record(42, -100, 1000))
        self.assertIsNone(self.record(42, -200, 2000))
        self.assertIsNone(self.record(43, -100, 3000))
        self.assertEqual(self.record(42, -100, 4000), 1000)
        self.assertEqual(self.record(42, -200, 5000), 2000)
        self.assertEqual(self.record(43, -100, 6000), 3000)

    def test_duplicate_and_out_of_order_updates_do_not_move_clock(self):
        self.record(42, -100, 4000)
        self.assertIsNone(self.record(42, -100, 4000))
        self.assertIsNone(self.record(42, -100, 1000))
        self.assertEqual(self.record(42, -100, 5000), 4000)

    def test_profile_save_cannot_reset_group_clock(self):
        self.record(42, -100, 1000)
        self.env['save_shadow'](dict(user_id=42, username='Alice', level=1, exp=0,
                                     total_exp=0, last_seen='2099-01-01'))
        self.assertEqual(self.record(42, -100, 5000), 1000)

    def test_concurrent_duplicate_updates_only_claim_gap_once(self):
        self.record(42, -100, 1000)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.record(42, -100, 10000), range(8)))
        self.assertEqual(results.count(1000), 1)
        self.assertEqual(results.count(None), 7)

    def test_schema_creation_is_idempotent(self):
        self.record(42, -100, 1000)
        self.db.execute(self.schema)
        self.assertEqual(self.record(42, -100, 5000), 1000)

    def test_tracker_survives_restart(self):
        self.record(42, -100, 1000)
        # All recording calls open fresh connections, just as after a restart.
        self.assertEqual(self.record(42, -100, 10000), 1000)

    def update(self, ts, chat_type='supergroup', text='hello', has_message=True):
        return SimpleNamespace(message=SimpleNamespace(
            date=datetime.fromtimestamp(ts, timezone.utc), text=text) if has_message else None,
            effective_user=SimpleNamespace(id=42, first_name='Alice', is_bot=False),
            effective_chat=SimpleNamespace(id=-100, type=chat_type))

    def handle(self, update):
        async def run():
            await self.env['_group_activity_pre_filter'](update, SimpleNamespace(bot='bot'))
            await asyncio.sleep(0)  # Let the reward task run.
        asyncio.run(run())

    def test_dms_and_buttons_do_not_reset_or_trigger(self):
        self.handle(self.update(1000))
        self.handle(self.update(9000, chat_type='private'))
        self.handle(self.update(9500, has_message=False))
        self.env['_try_idle_reward'].assert_not_called()
        self.handle(self.update(10000))
        call = self.env['_try_idle_reward'].call_args
        self.assertEqual(call.args[2], datetime.fromtimestamp(1000, timezone.utc).isoformat())
        self.assertEqual(call.kwargs['returned_at'].timestamp(), 10000)

    def test_commands_and_media_count_as_group_messages(self):
        self.handle(self.update(1000))
        self.handle(self.update(2000, text='/pet'))
        self.handle(self.update(3000, text=None))
        self.env['_try_idle_reward'].assert_not_called()
        self.handle(self.update(5000))
        self.env['_try_idle_reward'].assert_called_once()
        self.assertEqual(self.env['_try_idle_reward'].call_args.args[2],
                         datetime.fromtimestamp(3000, timezone.utc).isoformat())

    def test_exact_thirty_minute_threshold(self):
        self.handle(self.update(1000))
        self.handle(self.update(2799))
        self.env['_try_idle_reward'].assert_not_called()
        self.handle(self.update(4599))
        self.env['_try_idle_reward'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
