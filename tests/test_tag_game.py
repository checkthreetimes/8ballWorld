"""Tag gameplay, membership validation, persistence, and daily scheduling."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tag_game import TagGame


class TagGameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db_path = str(Path(self.folder.name) / 'tag.db')
        self.now = datetime(2026, 11, 9, 12, tzinfo=timezone.utc).timestamp()
        self.banned = set()
        self.game = self.new_game()
        self.users = {i: NS(id=i, first_name=f'Player {i}', username=f'user{i}', is_bot=False)
                      for i in range(1, 7)}
        self.status = {}
        async def member(chat_id, uid):
            return NS(user=self.users[uid], status=self.status.get(uid, 'member'), is_member=True)
        self.bot = NS(get_chat_member=AsyncMock(side_effect=member), send_message=AsyncMock())
        self.context = NS(bot=self.bot, args=[])
        for uid in (1, 2, 3, 4):
            self.game._remember(-100, self.users[uid], self.now)

    def new_game(self):
        game = TagGame(lambda: sqlite3.connect(self.db_path),
                       lambda uid: uid in self.banned, 99,
                       now=lambda: self.now, rng=random.Random(1))
        game.init_db()
        return game

    def update(self, uid=1, text='/tag', chat_id=-100, reply_uid=None, chat_type='supergroup'):
        reply = NS(from_user=self.users[reply_uid], date=datetime.fromtimestamp(self.now, timezone.utc)) if reply_uid else None
        return NS(effective_user=self.users[uid], effective_chat=NS(id=chat_id, type=chat_type),
                  message=NS(text=text, date=datetime.fromtimestamp(self.now, timezone.utc),
                             reply_to_message=reply, reply_text=AsyncMock()))

    async def start(self):
        await self.game.command(self.update(), self.context)
        return self.game.state(-100)['holder']

    async def test_start_mentions_recent_member_and_explains_rules(self):
        holder = await self.start()
        self.assertIn(holder, (1, 2, 3, 4))
        message = self.bot.send_message.call_args.kwargs['text']
        self.assertIn(f'tg://user?id={holder}', message)
        self.assertIn('<b>Tag 0/10</b>', message)
        self.assertIn(f'@user{holder}</a>', message)
        self.assertIn('🎯 <b>Pass it on!</b>', message)
        self.assertNotIn('Admins', message)
        self.assertNotIn('No self-tags', message)
        self.assertNotIn('—', message)

    async def test_command_does_not_replace_existing_round(self):
        await self.start()
        before = self.game.state(-100)
        await self.game.command(self.update(2), self.context)
        self.assertEqual(self.game.state(-100), before)
        self.assertIn('already running', self.bot.send_message.call_args.kwargs['text'])

    async def test_username_pass_then_reply_pass(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await self.game.observe(self.update(holder, f'tag @user{target}'), self.context)
        self.assertEqual(self.game.state(-100)['holder'], target)
        next_target = next(i for i in (1, 2, 3, 4) if i not in (holder, target))
        await self.game.observe(self.update(target, 'tag', reply_uid=next_target), self.context)
        self.assertEqual(self.game.state(-100)['holder'], next_target)
        self.assertEqual(self.game.state(-100)['passes'], 2)

    async def test_tenth_pass_ends_round_and_new_round_can_start(self):
        await self.start()
        last = None
        for count in range(1, 11):
            state = self.game.state(-100)
            target = next(i for i in (1, 2, 3, 4) if i not in (state['holder'], state['previous']))
            await self.game.observe(self.update(state['holder'], 'tag', reply_uid=target), self.context)
            self.assertEqual(self.game.state(-100)['passes'], count)
            last = target
        self.assertIsNone(self.game.state(-100)['holder'])
        message = self.bot.send_message.call_args.kwargs['text']
        self.assertIn(f'tg://user?id={last}', message)
        self.assertIn('Round over!', message)
        await self.start()
        self.assertEqual(self.game.state(-100)['passes'], 0)

    async def test_self_bot_non_holder_and_tagback_rejected(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await self.game.observe(self.update(holder, 'tag', reply_uid=holder), self.context)
        await self.game.observe(self.update(target, 'tag', reply_uid=holder), self.context)
        self.users[6].is_bot = True
        await self.game.observe(self.update(holder, 'tag', reply_uid=6), self.context)
        self.assertEqual(self.game.state(-100)['passes'], 0)
        await self.game.observe(self.update(holder, 'tag', reply_uid=target), self.context)
        await self.game.observe(self.update(target, 'tag', reply_uid=holder), self.context)
        self.assertEqual(self.game.state(-100)['holder'], target)
        self.assertEqual(self.game.state(-100)['passes'], 1)

    async def test_banned_and_departed_targets_rejected(self):
        holder = await self.start()
        self.banned.add(5)
        self.status[6] = 'left'
        for target in (5, 6):
            await self.game.observe(self.update(holder, 'tag', reply_uid=target), self.context)
        self.assertEqual(self.game.state(-100)['passes'], 0)

    async def test_unseen_username_gives_reply_instructions(self):
        holder = await self.start()
        await self.game.observe(self.update(holder, 'tag @unknown'), self.context)
        self.assertEqual(self.game.state(-100)['passes'], 0)
        self.assertIn('Reply tag', self.bot.send_message.call_args.kwargs['text'])

    async def test_dm_does_not_start_or_record_game(self):
        update = self.update(chat_id=1, chat_type='private')
        await self.game.command(update, self.context)
        self.assertIsNone(self.game.state(1))
        update.message.reply_text.assert_awaited_once()

    async def test_need_three_recent_eligible_members(self):
        self.banned.update((2, 3, 4))
        await self.game.command(self.update(), self.context)
        self.assertIsNone(self.game.state(-100))
        self.assertIn('at least 3', self.bot.send_message.call_args.kwargs['text'])

    async def test_admin_end_and_non_admin_rejection(self):
        await self.start()
        await self.game.end_command(self.update(1), self.context)
        self.assertIsNotNone(self.game.state(-100)['holder'])
        self.status[1] = 'administrator'
        await self.game.end_command(self.update(1), self.context)
        self.assertIsNone(self.game.state(-100)['holder'])

    async def test_restart_preserves_round(self):
        await self.start()
        before = self.game.state(-100)
        self.assertEqual(self.new_game().state(-100), before)

    async def test_concurrent_starts_only_create_one_round(self):
        await asyncio.gather(*(self.game.command(self.update(i), self.context) for i in (1, 2, 3)))
        messages = [c.kwargs['text'] for c in self.bot.send_message.call_args_list]
        self.assertEqual(sum('tag, you\'re it!' in m for m in messages), 1)

    async def test_duplicate_concurrent_pass_only_counts_once(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await asyncio.gather(*(self.game.observe(self.update(holder, 'tag', reply_uid=target), self.context)
                               for _ in range(2)))
        self.assertEqual(self.game.state(-100)['passes'], 1)

    async def test_daily_schedule_persists_and_only_one_auto_round_per_day(self):
        await self.game.daily_tick(self.bot)
        state = self.game.state(-100)
        due = state['auto_due']
        self.assertGreaterEqual(due, self.now)
        self.assertLess(due, self.now + 12*3600)
        self.assertEqual(self.new_game().state(-100)['auto_due'], due)
        self.now = due + 1
        for uid in (1, 2, 3, 4):
            self.game._remember(-100, self.users[uid], self.now)
        await self.game.daily_tick(self.bot)
        self.assertIsNotNone(self.game.state(-100)['holder'])
        auto_day = self.game.state(-100)['auto_day']
        self.game._query('UPDATE tag_rounds SET holder=NULL WHERE chat_id=-100', write=True)
        self.bot.send_message.reset_mock()
        await self.game.daily_tick(self.bot)
        self.bot.send_message.assert_not_called()
        self.assertEqual(self.game.state(-100)['auto_day'], auto_day)

    async def test_daily_never_overwrites_manual_game(self):
        holder = await self.start()
        await self.game.daily_tick(self.bot)
        self.now = self.game.state(-100)['auto_due'] + 1
        await self.game.daily_tick(self.bot)
        self.assertEqual(self.game.state(-100)['holder'], holder)
        self.assertIsNone(self.game.state(-100)['auto_day'])

    async def test_daily_new_day_can_start_another_round(self):
        await self.game.daily_tick(self.bot)
        self.now = self.game.state(-100)['auto_due'] + 1
        self.game._remember(-100, self.users[1], self.now)
        await self.game.daily_tick(self.bot)
        self.game._query('UPDATE tag_rounds SET holder=NULL WHERE chat_id=-100', write=True)
        self.now = (int(self.now) // 86400 + 1)*86400 + 3600
        for uid in (1, 2, 3, 4):
            self.game._remember(-100, self.users[uid], self.now)
        await self.game.daily_tick(self.bot)
        self.now = self.game.state(-100)['auto_due'] + 1
        self.game._remember(-100, self.users[1], self.now)
        await self.game.daily_tick(self.bot)
        self.assertIsNotNone(self.game.state(-100)['holder'])
        self.assertEqual(self.game.state(-100)['auto_day'],
                         datetime.fromtimestamp(self.now, timezone.utc).date().isoformat())

    async def test_failed_send_does_not_advance_round(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        self.bot.send_message.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            await self.game.observe(self.update(holder, 'tag', reply_uid=target), self.context)
        self.assertEqual(self.game.state(-100)['holder'], holder)
        self.assertEqual(self.game.state(-100)['passes'], 0)

    async def test_stale_username_is_not_tagged(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        self.users[target].username = 'new_handle'
        await self.game.observe(self.update(holder, f'tag @user{target}'), self.context)
        self.assertEqual(self.game.state(-100)['passes'], 0)
        self.assertIn('username has changed', self.bot.send_message.call_args.kwargs['text'])

    async def test_tag_command_reply_selects_that_person(self):
        await self.game.command(self.update(reply_uid=2), self.context)
        self.assertEqual(self.game.state(-100)['holder'], 2)
        self.assertEqual(self.game.state(-100)['passes'], 0)
        self.assertIn('tg://user?id=2', self.bot.send_message.call_args.kwargs['text'])

    async def test_separate_group_has_independent_round(self):
        holder = await self.start()
        for uid in (1, 2, 3):
            self.game._remember(-200, self.users[uid], self.now)
        await self.game.command(self.update(chat_id=-200), self.context)
        self.assertEqual(self.game.state(-100)['holder'], holder)
        self.assertIsNotNone(self.game.state(-200)['holder'])

    async def test_quiet_group_auto_round_waits_for_activity(self):
        await self.game.daily_tick(self.bot)
        self.now = max(self.game.state(-100)['auto_due'] + 1, self.now + 3601)
        await self.game.daily_tick(self.bot)
        self.assertIsNone(self.game.state(-100)['holder'])
        self.game._remember(-100, self.users[1], self.now)
        await self.game.daily_tick(self.bot)
        self.assertIsNotNone(self.game.state(-100)['holder'])

    async def test_existing_group_activity_seeds_recent_members(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE group_message_activity (user_id, chat_id, last_message_ts);
            CREATE TABLE shadow_profiles (user_id, username);
            CREATE TABLE players (user_id, tg_username);
        """)
        conn.execute('INSERT INTO group_message_activity VALUES (?, ?, ?)', (5, -200, self.now))
        conn.execute('INSERT INTO shadow_profiles VALUES (?, ?)', (5, 'Seeded Player'))
        conn.execute('INSERT INTO players VALUES (?, ?)', (5, 'seeded_user'))
        conn.execute('INSERT INTO group_message_activity VALUES (?, ?, ?)', (6, -200, self.now - 90000))
        conn.commit()
        conn.close()
        game = self.new_game()
        member = game._member(-200, 5)
        self.assertEqual(member['name'], 'Seeded Player')
        self.assertEqual(member['username'], 'seeded_user')
        self.assertEqual(len(game._query('SELECT * FROM tag_members WHERE chat_id=-200')), 1)

    async def test_explicit_username_takes_priority_over_reply(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await self.game.observe(self.update(holder, f'tag @user{target}', reply_uid=holder), self.context)
        self.assertEqual(self.game.state(-100)['holder'], target)

    async def test_tag_reply_passes_in_active_round(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await self.game.command(self.update(holder, reply_uid=target), self.context)
        self.assertEqual(self.game.state(-100)['holder'], target)
        self.assertEqual(self.game.state(-100)['passes'], 1)
        self.assertIn('Tag 1/10', self.bot.send_message.call_args.kwargs['text'])

    async def test_tag_reply_can_tag_round_starter_on_first_pass(self):
        await self.game.command(self.update(1, reply_uid=2), self.context)
        await self.game.command(self.update(2, reply_uid=1), self.context)
        self.assertEqual(self.game.state(-100)['holder'], 1)
        self.assertEqual(self.game.state(-100)['passes'], 1)

    async def test_tag_reply_rejects_immediate_tagback(self):
        await self.game.command(self.update(1, reply_uid=2), self.context)
        await self.game.command(self.update(2, reply_uid=3), self.context)
        await self.game.command(self.update(3, reply_uid=2), self.context)
        self.assertEqual(self.game.state(-100)['holder'], 3)
        self.assertEqual(self.game.state(-100)['passes'], 1)
        self.assertIn('No immediate tag-backs', self.bot.send_message.call_args.kwargs['text'])

    async def test_non_holder_tag_reply_does_not_replace_active_round(self):
        await self.game.command(self.update(1, reply_uid=2), self.context)
        await self.game.command(self.update(3, reply_uid=4), self.context)
        self.assertEqual(self.game.state(-100)['holder'], 2)
        self.assertEqual(self.game.state(-100)['passes'], 0)
        self.assertIn('Only the person', self.bot.send_message.call_args.kwargs['text'])
        self.assertIn('<a href="tg://user?id=2">@user2</a> is it!',
                      self.bot.send_message.call_args.kwargs['text'])

    async def test_concurrent_tag_replies_only_count_once(self):
        await self.game.command(self.update(1, reply_uid=2), self.context)
        await asyncio.gather(*(self.game.command(self.update(2, reply_uid=3), self.context)
                               for _ in range(2)))
        self.assertEqual(self.game.state(-100)['holder'], 3)
        self.assertEqual(self.game.state(-100)['passes'], 1)

    async def test_reply_start_rejects_self_bot_banned_and_departed(self):
        self.users[6].is_bot = True
        self.banned.add(5)
        self.status[4] = 'left'
        for uid in (1, 6, 5, 4):
            with self.subTest(uid=uid):
                await self.game.command(self.update(reply_uid=uid), self.context)
                state = self.game.state(-100)
                self.assertTrue(state is None or state['holder'] is None)

    async def test_reply_start_accepts_member_without_username(self):
        self.users[2].username = None
        await self.game.command(self.update(reply_uid=2), self.context)
        self.assertEqual(self.game.state(-100)['holder'], 2)

    async def test_reply_pass_mentions_username_as_account_link(self):
        holder = await self.start()
        target = next(i for i in (1, 2, 3, 4) if i != holder)
        await self.game.observe(self.update(holder, 'tag', reply_uid=target), self.context)
        message = self.bot.send_message.call_args.kwargs['text']
        self.assertIn(f'<a href="tg://user?id={target}">@user{target}</a>', message)
        self.assertIn('<b>Tag 1/10</b>', message)
        self.assertEqual(self.bot.send_message.call_args.kwargs['parse_mode'], 'HTML')
        self.assertNotIn('—', message)

    async def test_mentions_escape_display_names(self):
        self.users[1].first_name = '<b>A & B</b>'
        self.users[1].username = None
        self.game._remember(-100, self.users[1], self.now)
        mention = self.game._mention(self.game._member(-100, 1))
        self.assertIn('&lt;b&gt;A &amp; B&lt;/b&gt;', mention)


if __name__ == '__main__':
    unittest.main()
