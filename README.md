# 8ballWorld
A fun 8Ball game

## Group tag

- `/tag` starts a round when the group has no active game and at least three eligible people have posted in the last 24 hours. Replying `/tag` to someone's message makes that person it. Plain `/tag` picks the starting player randomly.
- Whoever is it sends `tag @username` or replies `tag` or `/tag` to another member's message. An exact `@username` message also works. Username tags require the bot to have seen that user in the group.
- The initial pick is tag 0. The tenth successful pass ends the round; its recipient loses. No self-tags, bot tags, or immediate tag-backs. Rounds do not expire. Recovery rules keep stalled turns moving; points are separate from RPG EXP and gold.
- Group admins or the bot admin can use `/endtag` to close a stalled round.
- Each group gets a persistent random daily slot using UTC dates. At most one automatic round starts per day, once the slot arrives and the group has recent activity and enough eligible members. An active round blocks new starts. Manual rounds do not consume the automatic daily allowance.
- Rounds, member activity, and daily schedules persist in the existing SQLite database.

### Tag statistics

Use `/tagstats` in the group for the current holder and hold duration, total tags and completed rounds, top five taggers, most tagged players, most caught players, fastest escapes, and your own totals. Statistics are group-specific and persist across restarts. Initial assignments do not count as successful tags, and admin-ended games do not count as losses.

Tracking begins when this update is deployed. Earlier tags cannot be reconstructed. Existing rounds continue, but their current hold duration is unknown until the next pass. Stats pages display names without pinging everyone listed.

### Points and stalled turns

- Each successful pass earns 1 point. Escaping within 5 minutes adds 1, and the tenth/final pass adds 3. Weekly leaderboards reset each Monday at 00:00 UTC; all-time totals remain. Initial assignments, reminders, and takeovers award no points.
- Tags 8 and 9 show danger-zone messages.
- After 30 minutes holding the tag, the holder gets one reminder. After 30 minutes, another eligible group member can volunteer with `/takeit`. This keeps the same tag count and starts a fresh turn; the volunteer cannot immediately give it back to the stalled holder.
- After 1 hour, open tag lets anyone tag another eligible group member and continue the same round. The rescuing tag counts normally, but a player who was not it receives no speed bonus or fastest-escape record for that pass.
- Recovery state and reminders persist across restarts. Existing turns start their recovery clock at deployment because their prior hold time was not recorded.
- Statistics and leaderboards appear on demand with `/tagstats`; they are not automatically posted. Automatic guild-raid starts and daily group leaderboard digests are disabled. Manual commands and daily settlements continue.
