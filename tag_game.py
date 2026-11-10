"""Persistent, group-scoped tag rounds. No game expiry or gameplay rewards."""
import asyncio
from datetime import datetime, timezone, timedelta
from html import escape
import logging
import random
import re
import time

logger = logging.getLogger(__name__)
RECENT_SECONDS = 24 * 60 * 60
TAG_LIMIT = 10
REMINDER_AFTER = 2 * 3600
TAKEOVER_AFTER = 4 * 3600
OPEN_AFTER = 6 * 3600


class TagGame:
    def __init__(self, connect_db, is_banned, admin_id, *, now=time.time, rng=None):
        self.connect_db = connect_db
        self.is_banned = is_banned
        self.admin_id = admin_id
        self.now = now
        self.rng = rng or random.Random()
        self.locks = {}

    def init_db(self):
        conn = self.connect_db()
        try:
            conn.execute('''CREATE TABLE IF NOT EXISTS tag_members (
                chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                name TEXT NOT NULL, username TEXT, last_message_ts REAL NOT NULL,
                PRIMARY KEY (chat_id, user_id))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS tag_rounds (
                chat_id INTEGER PRIMARY KEY, holder INTEGER, previous INTEGER,
                passes INTEGER NOT NULL DEFAULT 0,
                schedule_day TEXT, auto_due REAL, auto_day TEXT)''')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(tag_rounds)')}
            for column, definition in (('holder_since', 'REAL'), ('reminded', 'INTEGER NOT NULL DEFAULT 0'),
                                       ('opened', 'INTEGER NOT NULL DEFAULT 0')):
                if column not in columns:
                    conn.execute(f'ALTER TABLE tag_rounds ADD COLUMN {column} {definition}')
            # Old active turns get a recovery baseline without inventing a hold duration.
            if 'recovery_since' not in columns:
                conn.execute('ALTER TABLE tag_rounds ADD COLUMN recovery_since REAL')
            conn.execute('UPDATE tag_rounds SET recovery_since=? WHERE holder IS NOT NULL AND recovery_since IS NULL',
                         (self.now(),))
            conn.execute('''CREATE TABLE IF NOT EXISTS tag_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL, kind TEXT NOT NULL,
                actor_id INTEGER, target_id INTEGER, pass_number INTEGER NOT NULL,
                happened_at REAL NOT NULL, held_seconds REAL)''')
            event_columns = {row[1] for row in conn.execute('PRAGMA table_info(tag_events)')}
            if 'points' not in event_columns:
                conn.execute('ALTER TABLE tag_events ADD COLUMN points INTEGER NOT NULL DEFAULT 0')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tag_events_chat ON tag_events(chat_id, kind)')
            conn.execute('CREATE TABLE IF NOT EXISTS tag_stats_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute("INSERT OR IGNORE INTO tag_stats_meta VALUES ('tracking_since', ?)", (str(self.now()),))
            # Reuse reliable group activity already recorded before this feature.
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'group_message_activity', 'shadow_profiles', 'players'} <= tables:
                conn.execute('''INSERT OR IGNORE INTO tag_members
                    (chat_id, user_id, name, username, last_message_ts)
                    SELECT g.chat_id, g.user_id, COALESCE(s.username, CAST(g.user_id AS TEXT)),
                           p.tg_username, g.last_message_ts
                    FROM group_message_activity g
                    LEFT JOIN shadow_profiles s ON s.user_id=g.user_id
                    LEFT JOIN players p ON p.user_id=g.user_id
                    WHERE g.last_message_ts >= ?''', (self.now() - RECENT_SECONDS,))
            conn.commit()
        finally:
            conn.close()

    def _lock(self, chat_id):
        return self.locks.setdefault(chat_id, asyncio.Lock())

    def _query(self, sql, params=(), *, write=False):
        conn = self.connect_db()
        try:
            cursor = conn.execute(sql, params)
            if write:
                conn.commit()
                return
            return [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _transition(self, sql, params, *, chat_id, kind, actor=None, target=None,
                    passes=0, held=None, when=None, points=0):
        """Commit the game change and its statistics together."""
        conn = self.connect_db()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(sql, params)
            conn.execute('''INSERT INTO tag_events
                (chat_id, kind, actor_id, target_id, pass_number, happened_at, held_seconds, points)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (chat_id, kind, actor, target, passes, self.now() if when is None else when, held, points))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _duration(seconds):
        seconds = max(0, int(seconds))
        if seconds >= 86400:
            return f'{seconds // 86400}d {(seconds % 86400) // 3600}h'
        if seconds >= 3600:
            return f'{seconds // 3600}h {(seconds % 3600) // 60}m'
        if seconds >= 60:
            return f'{seconds // 60}m {seconds % 60}s'
        return f'{seconds}s'

    def statistics(self, chat_id, uid):
        totals = self._query('''SELECT
            SUM(CASE WHEN kind='pass' THEN 1 ELSE 0 END) AS tags,
            SUM(CASE WHEN kind='pass' AND pass_number=? THEN 1 ELSE 0 END) AS finished,
            SUM(CASE WHEN kind='pass' AND actor_id=? THEN 1 ELSE 0 END) AS sent,
            SUM(CASE WHEN kind='pass' AND target_id=? THEN 1 ELSE 0 END) AS received,
            SUM(CASE WHEN kind='pass' AND pass_number=? AND target_id=? THEN 1 ELSE 0 END) AS caught
            FROM tag_events WHERE chat_id=?''', (TAG_LIMIT, uid, uid, TAG_LIMIT, uid, chat_id))[0]
        totals = {key: value or 0 for key, value in totals.items()}
        now = datetime.fromtimestamp(self.now(), timezone.utc)
        week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        points = self._query('''SELECT COALESCE(SUM(points), 0) AS points,
            COALESCE(SUM(CASE WHEN happened_at >= ? AND happened_at < ? THEN points ELSE 0 END), 0) AS week_points
            FROM tag_events WHERE chat_id=? AND actor_id=? AND kind='pass' ''',
            (week, week + 7*86400, chat_id, uid))[0]
        totals.update(points)
        leaders = {'weekly': self._query('''SELECT actor_id AS user_id, SUM(points) AS value
            FROM tag_events WHERE chat_id=? AND kind='pass' AND actor_id IS NOT NULL
            AND happened_at>=? AND happened_at<? GROUP BY actor_id HAVING SUM(points)>0
            ORDER BY value DESC, user_id ASC LIMIT 5''', (chat_id, week, week + 7*86400))}

        for key, column, condition in (
            ('sent', 'actor_id', "kind='pass'"),
            ('received', 'target_id', "kind='pass'"),
            ('caught', 'target_id', f"kind='pass' AND pass_number={TAG_LIMIT}"),
        ):
            leaders[key] = self._query(f'''SELECT {column} AS user_id, COUNT(*) AS value
                FROM tag_events WHERE chat_id=? AND {condition} AND {column} IS NOT NULL
                GROUP BY {column} ORDER BY value DESC, user_id ASC LIMIT 5''', (chat_id,))
        leaders['fastest'] = self._query('''SELECT actor_id AS user_id, MIN(held_seconds) AS value
            FROM tag_events WHERE chat_id=? AND kind='pass' AND held_seconds >= 0
            AND actor_id IS NOT NULL GROUP BY actor_id
            ORDER BY value ASC, user_id ASC LIMIT 5''', (chat_id,))
        return totals, leaders

    def _stats_name(self, chat_id, uid):
        member = self._member(chat_id, uid)
        # Display names here rather than pinging a whole leaderboard on each view.
        return escape(member.get('username') or member['name'])

    async def stats_command(self, update, context):
        if not self._group_update(update):
            await update.message.reply_text('Use /tagstats in your group to see its tag leaderboard.')
            return
        if self.is_banned(update.effective_user.id):
            return
        chat_id, uid = update.effective_chat.id, update.effective_user.id
        async with self._lock(chat_id):
            state = self.state(chat_id)
            totals, leaders = self.statistics(chat_id, uid)
            lines = ['🏃💨 <b>TAG STATS</b>']
            if state and state['holder'] is not None:
                if state['opened'] or self._hold_age(state) >= OPEN_AFTER:
                    lines.append('🔓 Open tag! Anyone can pass it on.')
                elif self._hold_age(state) >= TAKEOVER_AFTER:
                    lines.append('🙋 /takeit is available to keep this round moving.')
                lines.append(f'🎯 It: <b>{self._stats_name(chat_id, state["holder"])}</b> '
                             f'({state["passes"]}/{TAG_LIMIT})')
                if state['holder_since'] is not None:
                    lines.append(f'⏳ Holding for {self._duration(self.now() - state["holder_since"])}')
                else:
                    lines.append('⏳ Holding since before stats tracking')
            else:
                lines.append('🎯 No active round. Use /tag to start one.')
            lines.append(f'📊 {totals["tags"]} tags · {totals["finished"]} rounds finished')
            for key, title in (('weekly', '🏆 Weekly points'), ('sent', '🔥 Top taggers'), ('received', '🎯 Most tagged'),
                               ('caught', '💥 Most caught'), ('fastest', '⚡ Fastest escapes')):
                lines.append(f'\n<b>{title}</b>')
                if not leaders[key]:
                    lines.append('No records yet.')
                for place, row in enumerate(leaders[key], 1):
                    value = self._duration(row['value']) if key == 'fastest' else str(row['value'])
                    lines.append(f'{place}. {self._stats_name(chat_id, row["user_id"])} · {value}')
            lines.append(f'\n👤 <b>You:</b> {totals["sent"]} tags sent · {totals["received"]} received · '
                         f'{totals["caught"]} caught')
            lines.append(f'⭐ {totals["week_points"]} points this week · {totals["points"]} all-time')
            lines.append('<i>+1 per pass · +1 within 5m · +3 final pass. Week resets Monday UTC.</i>')
            since = float(self._query("SELECT value FROM tag_stats_meta WHERE key='tracking_since'")[0]['value'])
            date = datetime.fromtimestamp(since, timezone.utc).strftime('%d %b %Y')
            lines.append(f'<i>Tracked since {date}. Earlier tags are not included.</i>')
            text = '\n'.join(lines)
        await self._say(context.bot, chat_id, text)

    def state(self, chat_id):
        rows = self._query('SELECT * FROM tag_rounds WHERE chat_id=?', (chat_id,))
        return rows[0] if rows else None

    def _member(self, chat_id, uid):
        rows = self._query('SELECT * FROM tag_members WHERE chat_id=? AND user_id=?', (chat_id, uid))
        return rows[0] if rows else {'user_id': uid, 'name': str(uid)}

    @staticmethod
    def _mention(member):
        label = f"@{member['username']}" if member.get('username') else member['name']
        return f'<a href="tg://user?id={int(member["user_id"])}">{escape(label)}</a>'

    def _round_text(self, member, passes):
        emoji = '🚨' if passes == 9 else '🔥' if passes == 8 else '🏃💨'
        warning = 'Last escape! ' if passes == 9 else 'Danger zone! ' if passes == 8 else ''
        return (
            f'{emoji} {self._mention(member)}, <b>you\'re it! ({passes}/{TAG_LIMIT})</b>\n'
            f'{warning}Reply <code>/tag</code> or send <code>tag @username</code>. Tag {TAG_LIMIT} loses!'
        )

    @staticmethod
    def _group_update(update):
        return (update.message is not None and update.effective_chat is not None
                and update.effective_chat.type in ('group', 'supergroup')
                and update.effective_user is not None and not update.effective_user.is_bot)

    def _remember(self, chat_id, user, sent_at):
        self._query('''INSERT INTO tag_members (chat_id, user_id, name, username, last_message_ts)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET
            name=excluded.name, username=excluded.username, last_message_ts=excluded.last_message_ts
            WHERE excluded.last_message_ts >= tag_members.last_message_ts''',
            (chat_id, user.id, user.first_name or str(user.id), user.username, sent_at), write=True)

    async def _eligible_member(self, bot, chat_id, uid):
        if self.is_banned(uid):
            return False
        try:
            member = await bot.get_chat_member(chat_id, uid)
            return (not member.user.is_bot and member.status not in ('left', 'kicked')
                    and (member.status != 'restricted' or member.is_member))
        except Exception:
            logger.warning('Could not verify tag participant %s in chat %s', uid, chat_id)
            return False

    async def _say(self, bot, chat_id, text):
        await bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')

    async def _start_locked(self, bot, chat_id, *, automatic=False, initial_target=None):
        state = self.state(chat_id)
        if state and state['holder'] is not None:
            if not automatic:
                await self._say(bot, chat_id,
                    f'🏃 A round is already running. {self._mention(self._member(chat_id, state["holder"]))} '
                    f'is it! Tag {state["passes"]}/{TAG_LIMIT}.')
            return False
        if initial_target is not None and not await self._eligible_member(bot, chat_id, initial_target['user_id']):
            await self._say(bot, chat_id, '🏃 Pick a current group member who can play.')
            return False
        candidates = self._query('''SELECT * FROM tag_members
            WHERE chat_id=? AND last_message_ts>=?''', (chat_id, self.now() - RECENT_SECONDS))
        self.rng.shuffle(candidates)
        eligible = []
        for candidate in candidates:
            if await self._eligible_member(bot, chat_id, candidate['user_id']):
                eligible.append(candidate)
            if len(eligible) == 3:
                break
        if len(eligible) < 3:
            if not automatic:
                await self._say(bot, chat_id, '🏃 Tag needs at least 3 people who posted in this group in the last 24 hours.')
            return False
        holder = initial_target or eligible[0]  # Plain /tag and daily starts stay random.
        await self._say(bot, chat_id, self._round_text(holder, 0))
        today = datetime.fromtimestamp(self.now(), timezone.utc).date().isoformat()
        started = self.now()
        self._transition('''INSERT INTO tag_rounds (chat_id, holder, previous, passes, auto_day, holder_since, recovery_since)
            VALUES (?, ?, NULL, 0, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET
            holder=excluded.holder, previous=NULL, passes=0, holder_since=excluded.holder_since, recovery_since=excluded.recovery_since, reminded=0, opened=0,
            auto_day=CASE WHEN ? THEN excluded.auto_day ELSE tag_rounds.auto_day END''',
            (chat_id, holder['user_id'], today if automatic else None, started, started, automatic),
            chat_id=chat_id, kind='start', target=holder['user_id'], when=started)
        return True

    async def command(self, update, context):
        if not self._group_update(update):
            await update.message.reply_text('🏃 Tag is played in a group. Use /tag there to start a round.')
            return
        if self.is_banned(update.effective_user.id):
            return
        chat_id = update.effective_chat.id
        self._remember(chat_id, update.effective_user, update.message.date.timestamp())
        if context.args:
            await self._pass(update, context, ' '.join(context.args))
            return
        async with self._lock(chat_id):
            state = self.state(chat_id)
            if update.message.reply_to_message and state and state['holder'] is not None:
                await self._pass_locked(update, context, '')
                return
            initial_target = None
            if update.message.reply_to_message and (not state or state['holder'] is None):
                initial_target, error = await self._target(update, '', context.bot)
                if not error and initial_target['user_id'] == update.effective_user.id:
                    error = '🏃 You cannot tag yourself.'
                if error:
                    await self._say(context.bot, chat_id, error)
                    return
            await self._start_locked(context.bot, chat_id, initial_target=initial_target)

    async def observe(self, update, context):
        if not self._group_update(update) or self.is_banned(update.effective_user.id):
            return
        self._remember(update.effective_chat.id, update.effective_user, update.message.date.timestamp())
        text = (update.message.text or '').strip()
        if text.lower() == 'tag' or re.fullmatch(r'(?:tag\s+)?@\w+', text, re.IGNORECASE):
            await self._pass(update, context, re.sub(r'^tag\s+', '', text, flags=re.IGNORECASE))

    async def _target(self, update, argument, bot):
        if re.fullmatch(r'@\w+', argument):
            rows = self._query('''SELECT * FROM tag_members WHERE chat_id=?
                AND LOWER(username)=LOWER(?) ORDER BY last_message_ts DESC LIMIT 1''',
                (update.effective_chat.id, argument[1:]))
            if rows:
                # Telegram usernames can change owners. Never tag a stale mapping.
                try:
                    member = await bot.get_chat_member(update.effective_chat.id, rows[0]['user_id'])
                    username = member.user.username or ''
                    if username.casefold() == argument[1:].casefold():
                        return rows[0], None
                except Exception:
                    logger.warning('Could not resolve tag username in chat %s', update.effective_chat.id)
                return None, 'That username has changed or could not be verified. Reply tag to their message instead.'
            return None, 'I have not seen that username in this group. Reply tag to their message instead.'
        reply = update.message.reply_to_message
        if reply and reply.from_user:
            user = reply.from_user
            if user.is_bot:
                return None, 'You cannot tag a bot.'
            self._remember(update.effective_chat.id, user, reply.date.timestamp())
            return {'user_id': user.id, 'name': user.first_name or str(user.id),
                    'username': user.username}, None
        return None, 'Send tag @username, or reply tag to someone\'s message.'

    async def _pass(self, update, context, argument):
        async with self._lock(update.effective_chat.id):
            await self._pass_locked(update, context, argument)

    async def _pass_locked(self, update, context, argument):
        """Shared pass logic. Caller holds the group lock for the whole operation."""
        chat_id, uid = update.effective_chat.id, update.effective_user.id
        state = self.state(chat_id)
        if not state or state['holder'] is None:
            # Plain conversation saying "tag" should not create noise.
            if (update.message.text or '').startswith('/'):
                await self._say(context.bot, chat_id, '🏃 No round is running. Use /tag to start one.')
            return
        is_open = state['opened'] or self._hold_age(state) >= OPEN_AFTER
        if state['holder'] != uid and not is_open:
            await self._say(context.bot, chat_id,
                f'🏃 {self._mention(self._member(chat_id, state["holder"]))} is it! '
                'Only the person who is it can tag someone.')
            return
        target, error = await self._target(update, argument, context.bot)
        if error:
            await self._say(context.bot, chat_id, error)
            return
        target_uid = target['user_id']
        if target_uid == uid:
            await self._say(context.bot, chat_id, '🏃 You cannot tag yourself.')
            return
        if target_uid == state['holder']:
            await self._say(context.bot, chat_id, '🏃 They are already it. Pick someone else.')
            return
        if target_uid == state['previous']:
            await self._say(context.bot, chat_id, '🏃 No immediate tag-backs. Pick someone else.')
            return
        if not await self._eligible_member(context.bot, chat_id, target_uid):
            await self._say(context.bot, chat_id, '🏃 Pick a current group member who can play.')
            return
        passes = state['passes'] + 1
        if passes == TAG_LIMIT:
            text = (f'💥 <b>CAUGHT!</b>\n'
                    f'{self._mention(target)} got caught holding the tag!\n\n'
                    f'🏁 <b>Tag {passes}/{TAG_LIMIT}. Round over!</b>\n'
                    '🔄 Use /tag to play again.')
        else:
            text = self._round_text(target, passes)
        await self._say(context.bot, chat_id, text)
        passed_at = self.now()
        held = passed_at - state['holder_since'] if state['holder_since'] is not None and uid == state['holder'] else None
        points = 1 + (1 if held is not None and 0 <= held <= 300 else 0) + (3 if passes == TAG_LIMIT else 0)
        self._transition('UPDATE tag_rounds SET holder=?, previous=?, passes=?, holder_since=?, recovery_since=?, reminded=0, opened=0 WHERE chat_id=?',
            (None if passes == TAG_LIMIT else target_uid, uid, passes,
             None if passes == TAG_LIMIT else passed_at, None if passes == TAG_LIMIT else passed_at, chat_id),
            chat_id=chat_id, kind='pass', actor=uid, target=target_uid,
            passes=passes, held=held if held is not None and held >= 0 else None, when=passed_at, points=points)

    def _hold_age(self, state):
        since = state['recovery_since']
        return max(0, self.now() - since) if since is not None else 0

    async def _recover_locked(self, bot, chat_id):
        state = self.state(chat_id)
        if not state or state['holder'] is None:
            return
        age = self._hold_age(state)
        if age >= OPEN_AFTER and not state['opened']:
            await self._say(bot, chat_id,
                f'🔓 <b>Open tag! ({state["passes"]}/{TAG_LIMIT})</b> Anyone can tag a group member to keep it moving. '
                'Reply /tag or send tag @username.')
            self._transition('UPDATE tag_rounds SET opened=1, reminded=1 WHERE chat_id=?',
                (chat_id,), chat_id=chat_id, kind='open', target=state['holder'], passes=state['passes'])
        elif age >= REMINDER_AFTER and not state['reminded']:
            await self._say(bot, chat_id,
                f'👀 {self._mention(self._member(chat_id, state["holder"]))}, still it! '
                'Pass it on. After 4h, someone can volunteer with /takeit; after 6h, anyone can tag.')
            self._transition('UPDATE tag_rounds SET reminded=1 WHERE chat_id=?',
                (chat_id,), chat_id=chat_id, kind='reminder', target=state['holder'], passes=state['passes'])

    async def takeover_command(self, update, context):
        if not self._group_update(update):
            await update.message.reply_text('Use /takeit in your group to volunteer for a stalled turn.')
            return
        uid, chat_id = update.effective_user.id, update.effective_chat.id
        if self.is_banned(uid):
            return
        async with self._lock(chat_id):
            state = self.state(chat_id)
            if not state or state['holder'] is None:
                await self._say(context.bot, chat_id, 'No active tag round. Use /tag to start one.')
                return
            if state['holder'] == uid:
                await self._say(context.bot, chat_id, 'You are already it. Pass it on!')
                return
            if self._hold_age(state) < TAKEOVER_AFTER:
                remaining = self._duration(TAKEOVER_AFTER - self._hold_age(state))
                await self._say(context.bot, chat_id, f'🙋 /takeit unlocks in {remaining}.')
                return
            if not await self._eligible_member(context.bot, chat_id, uid):
                return
            self._remember(chat_id, update.effective_user, update.message.date.timestamp())
            await self._say(context.bot, chat_id,
                f'🙋 {self._mention(self._member(chat_id, uid))} took over! '
                f'<b>Still {state["passes"]}/{TAG_LIMIT}.</b> Reply /tag or send tag @username.')
            now = self.now()
            self._transition('UPDATE tag_rounds SET holder=?, previous=?, holder_since=?, recovery_since=?, '
                             'reminded=0, opened=0 WHERE chat_id=?',
                (uid, state['holder'], now, now, chat_id), chat_id=chat_id, kind='takeover',
                actor=uid, target=state['holder'], passes=state['passes'], when=now)

    async def recovery_tick(self, bot):
        for row in self._query('SELECT chat_id FROM tag_rounds WHERE holder IS NOT NULL'):
            try:
                async with self._lock(row['chat_id']):
                    await self._recover_locked(bot, row['chat_id'])
            except Exception:
                logger.exception('Tag recovery failed in chat %s', row['chat_id'])

    async def end_command(self, update, context):
        if not self._group_update(update):
            await update.message.reply_text('Use /endtag in the group where the round is running.')
            return
        uid, chat_id = update.effective_user.id, update.effective_chat.id
        if uid != self.admin_id:
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status not in ('administrator', 'creator'):
                await self._say(context.bot, chat_id, 'Only group admins can end a tag round.')
                return
        async with self._lock(chat_id):
            state = self.state(chat_id)
            if not state or state['holder'] is None:
                await self._say(context.bot, chat_id, '🏃 No tag round is running.')
                return
            await self._say(context.bot, chat_id, '🏁 The tag round was ended by an admin. Use /tag to start another.')
            self._transition('UPDATE tag_rounds SET holder=NULL, previous=NULL, holder_since=NULL, recovery_since=NULL, reminded=0, opened=0 WHERE chat_id=?',
                (chat_id,), chat_id=chat_id, kind='end', actor=uid, target=state['holder'], passes=state['passes'])

    async def daily_tick(self, bot):
        now = self.now()
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        end_of_day = (int(now) // 86400 + 1) * 86400
        chats = self._query('''SELECT DISTINCT chat_id FROM tag_members
            WHERE last_message_ts>=?''', (now - RECENT_SECONDS,))
        for row in chats:
            chat_id = row['chat_id']
            try:
                async with self._lock(chat_id):
                    state = self.state(chat_id)
                    if not state or state['schedule_day'] != today:
                        due = self.rng.randint(int(now), max(int(now), end_of_day - 120))
                        self._query('''INSERT INTO tag_rounds (chat_id, schedule_day, auto_due)
                            VALUES (?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET
                            schedule_day=excluded.schedule_day, auto_due=excluded.auto_due''',
                            (chat_id, today, due), write=True)
                        state = self.state(chat_id)
                    if state['auto_day'] == today or state['holder'] is not None or now < state['auto_due']:
                        continue
                    # Wait for an active group rather than waking everyone in a quiet one.
                    active = self._query('SELECT MAX(last_message_ts) AS last FROM tag_members WHERE chat_id=?', (chat_id,))
                    if active[0]['last'] < now - 3600:
                        continue
                    await self._start_locked(bot, chat_id, automatic=True)
            except Exception:
                logger.exception('Could not run daily tag in chat %s', chat_id)

    async def daily_loop(self, bot):
        while True:
            try:
                await self.recovery_tick(bot)
                await self.daily_tick(bot)
            except Exception:
                logger.exception('Tag scheduler failed')
            await asyncio.sleep(60)
