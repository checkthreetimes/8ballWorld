# 8ballWorld
A fun 8Ball game

## Group tag

- `/tag` starts a round when the group has no active game and at least three eligible people have posted in the last 24 hours. The starting player is chosen randomly.
- Whoever is it sends `tag @username` or replies `tag` to another member's message. An exact `@username` message also works. Username tags require the bot to have seen that user in the group.
- The initial pick is tag 0. The tenth successful pass ends the round; its recipient loses. No self-tags, bot tags, or immediate tag-backs. There are no gameplay timers or rewards.
- Group admins or the bot admin can use `/endtag` to close a stalled round.
- Each group gets a persistent random daily slot using UTC dates. At most one automatic round starts per day, once the slot arrives and the group has recent activity and enough eligible members. An active round blocks new starts. Manual rounds do not consume the automatic daily allowance.
- Rounds, member activity, and daily schedules persist in the existing SQLite database.
