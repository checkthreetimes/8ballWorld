"""Persistent, group-scoped tag rounds. No game expiry or gameplay rewards."""
import asyncio
from datetime import datetime, timezone
from html import escape
import logging
import random
import re
import time

logger = logging.getLogger(__name__)
RECENT_SECONDS = 24 * 60 * 60
TAG_LIMIT = 10


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
        return (
            f'🏃💨 {self._mention(member)}, <b>tag, you\'re it!</b>\n\n'
            '🎯 <b>Pass it on!</b>\n'
            'Send <code>tag @username</code>\n'
            'or reply <code>tag</code> or <code>/tag</code> to someone\'s message.\n\n'
            f'🔢 <b>Tag {passes}/{TAG_LIMIT}</b>\n'
            f'💥 Whoever gets tagged on pass {TAG_LIMIT} loses!'
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
        self._query('''INSERT INTO tag_rounds (chat_id, holder, previous, passes, auto_day)
            VALUES (?, ?, NULL, 0, ?) ON CONFLICT(chat_id) DO UPDATE SET
            holder=excluded.holder, previous=NULL, passes=0,
            auto_day=CASE WHEN ? THEN excluded.auto_day ELSE tag_rounds.auto_day END''',
            (chat_id, holder['user_id'], today if automatic else None, automatic), write=True)
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
        if state['holder'] != uid:
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
        self._query('UPDATE tag_rounds SET holder=?, previous=?, passes=? WHERE chat_id=?',
            (None if passes == TAG_LIMIT else target_uid, uid, passes, chat_id), write=True)


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
            self._query('UPDATE tag_rounds SET holder=NULL, previous=NULL WHERE chat_id=?', (chat_id,), write=True)

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
                await self.daily_tick(bot)
            except Exception:
                logger.exception('Tag scheduler failed')
            await asyncio.sleep(60)
