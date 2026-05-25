#!/usr/bin/env python3
"""
The World of 8Ball  -  RPG Bot v13
"""

import os, json, random, logging, sqlite3, re, asyncio
from datetime import datetime, timedelta
from collections import Counter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, filters, CallbackQueryHandler
)

# ── CONFIG ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not set!")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
DB_PATH  = os.environ.get("DB_PATH", "/data/8ball.db")
ADMIN_ID = 15941534

# ── CHANGELOG ─────────────────────────────────────────────────────────────────
CURRENT_VERSION = "v1.21"
CHANGELOG = [
    {"version": "v1.21", "date": "2026-05-24", "changes": [
        "Killstreaks, revenge bonus, wanted system, /claim streak, /forge crafting, /war board, /history, guild wars, guild bank",
    ]},
    {"version": "v1.0",  "date": "2025-01-01", "changes": [
        "Initial release — shadow profile, /pool, /daily, /quest, /train, /explore",
    ]},
    {"version": "v1.1",  "date": "2025-02-01", "changes": [
        "Added 5 base classes and prestige paths",
        "Added /skill, /duel, /arena, /boss, /raid, /soloraid",
        "Added gear system: /equip, /enhance, /enchant",
    ]},
    {"version": "v1.2",  "date": "2025-03-01", "changes": [
        "Added 33 titles with stat bonuses",
        "Added halls (guilds): /guildcreate, /guildjoin, /guilddonate",
        "Added weather system affecting EXP and DMG",
    ]},
    {"version": "v1.13", "date": "2025-05-01", "changes": [
        "Inventory redesigned with named section buttons (Equipped, Weapons, Armors, etc.)",
        "Added class archetype labels and weapon emojis per class",
        "Added /guide page 6 with full command reference",
        "Added 30-minute offline PvP protection with DM notification",
    ]},
    {"version": "v1.14", "date": "2025-05-10", "changes": [
        "Fixed Custom Tip Scroll name mismatch (enchant now works)",
        "Fixed Chalk Vial showing max HP instead of actual capped HP",
        "Added 💬 message count to /stats page 1",
        "Added inline buttons to soloraid, boss, prestige, dungeon, shop, allocate, arena, raid, duel, resetclass, resetstats, guilddisband, class picker",
    ]},
    {"version": "v1.15", "date": "2025-05-15", "changes": [
        "Fixed boss fight: skill HP tracking, alive check, and missing return after defeat",
        "Fixed self-heal inventory overwrite bug",
        "Fixed /heal with no reply now heals yourself",
        "Added defeat logging: last_defeated_by field, DM on defeat, countdown timer",
    ]},
    {"version": "v1.16", "date": "2025-05-20", "changes": [
        "Fixed defeat cause showing generic 'the enemy' for solo/group raid deaths",
        "Defeat cause now records exact enemy name in all combat paths",
    ]},
    {"version": "v1.17", "date": "2025-05-23", "changes": [
        "Added /reinforce [item] — sacrifice duplicate to raise base stats (+1 ATK/DEF per reinforce, max 20)",
        "Added /reinforce ascend [item] — ascend to ★ tier at 20 reinforces (+5 flat bonus, max ★★★)",
        "Added /objectives — 3 daily objectives with EXP/gold rewards, resets midnight",
        "Added 6 item set bonuses for matching legendary gear (shown in /stats gear page)",
        "Added 6 new titles: The Forger, Diamond Grinder, The Ascendant, Three Star General, Objective Rookie, Objective Master",
    ]},
    {"version": "v1.18", "date": "2025-05-23", "changes": [
        "Added /bounty @user [amount] — any player can place a gold bounty on someone",
        "Fixed Railrunner's Execution Order to actually place a free 500g bounty",
        "Added /bounties — public bounty board showing all active bounties",
        "Bounty claims now also trigger in arena, duel, and skill kills (not just /attack)",
        "Added /changelog — view recent bot updates",
        "Bot now DMs admin automatically on startup when a new version is detected",
    ]},
    {"version": "v1.19", "date": "2026-05-23", "changes": [
        "Fixed boss skill picker: damage now written to boss_dict['hp'] (boss was unkillable via picker)",
        "Fixed dead boss no longer counter-attacks after picker kill",
        "Fixed duel wager: gold deducted from both players at accept; no more free-gold exploit",
        "Fixed prestige_skills field added to save_player (was silently lost on every save)",
        "Fixed guild shop discount: level-10 guilds now correctly get 15% (was unreachable branch)",
        "Fixed check_and_claim_bounty: attacker gold now saved (was lost when called via create_task)",
        "Fixed dungeon_run daily objective now tracked on dungeon completion",
        "Fixed Railrunner /bounty contract cap now enforced (max 2, was unlimited)",
        "Fixed arena flee: correct player's HP set to 0 in display (was always p1)",
        "Fixed arena DOT: fight now ends correctly if DOT kills active player mid-turn",
        "Fixed arena: defeated players can no longer issue challenges",
        "Fixed duel: target checked for defeat before challenge is issued",
        "Fixed mig_conn wrapped in try/finally to prevent DB connection leak",
        "Fixed skill_tree_callback: added try/except for IndexError on malformed data",
        "Fixed class_browse_callback: safe parse replaces bare unpack",
        "Fixed double query.answer() removed from class progression/browse callbacks",
        "Fixed level 60/100 auto-advance now gated on class_path like level 30",
    ]},
]

# ── GLOBAL STATE ──────────────────────────────────────────────────────────────
last_bot_message   = {}   # (chat_id, user_id) -> msg_id
active_bosses      = {}   # chat_id -> boss dict
secret_boss_active = {}
active_events      = {}   # chat_id -> event dict
active_raids       = {}   # chat_id -> raid dict
active_soloraids   = {}   # user_id -> solo raid dict
active_drakes      = {}   # chat_id -> drake dict
message_counters   = {}   # chat_id -> int
pending_trades     = {}   # user_id -> trade dict
pending_duels      = {}   # challenger_id -> {target_id, wager, chat_id, expires}
active_arenas      = {}   # chat_id -> arena state
pending_guild_reqs = {}   # guild_id -> [requests]
explore_timers     = {}   # user_id -> asyncio task
active_dungeons    = {}   # user_id -> asyncio task
_wipe_confirm      = {}   # admin_id -> timestamp
pending_marriages  = {}   # proposer_id -> {target_id, chat_id, expires}

# ── SEND HELPERS ──────────────────────────────────────────────────────────────
async def _auto_delete(bot, chat_id, msg_id, delay):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass

async def send_group(update: Update, text: str, parse_mode="Markdown",
                     permanent=False, delay=9, reply_markup=None):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    key     = (chat_id, user_id)
    old_id  = last_bot_message.get(key)
    results = await asyncio.gather(
        update.get_bot().send_message(
            chat_id=chat_id, text=text[:4096],
            parse_mode=parse_mode, reply_markup=reply_markup),
        update.get_bot().delete_message(chat_id=chat_id, message_id=old_id)
            if old_id else asyncio.sleep(0),
        update.message.delete(),
        return_exceptions=True
    )
    new_msg = results[0]
    if isinstance(new_msg, Exception):
        try:
            new_msg = await update.get_bot().send_message(
                chat_id=chat_id, text=text[:4096],
                parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            return None
    if not permanent:
        last_bot_message[key] = new_msg.message_id
        asyncio.create_task(_auto_delete(
            update.get_bot(), chat_id, new_msg.message_id, delay))
    return new_msg

async def announce(bot, chat_id: int, text: str,
                   parse_mode="Markdown", permanent=False, delay=9):
    try:
        msg = await bot.send_message(
            chat_id=chat_id, text=text[:4096], parse_mode=parse_mode)
        if not permanent:
            asyncio.create_task(_auto_delete(bot, chat_id, msg.message_id, delay))
        return msg
    except Exception:
        return None

# ── SAFE HELPERS ──────────────────────────────────────────────────────────────
def sjl(v, d):
    if v is None: return d
    try: return json.loads(v)
    except: return d

def safe_inv(p):    return sjl(p.get("inventory"), [])
def safe_stats(p):
    return sjl(p.get("stats"),
               {"STR":5,"DEF":0,"AGI":5,"INT":5,"WIS":5,"DEX":5,"LUK":5})
def safe_titles(p): return sjl(p.get("titles"), ["Adventurer"])  # default is Adventurer
def safe_cds(p):    return sjl(p.get("passive_cooldowns"), {})
def safe_int(v, d=0):
    try: return int(v or d)
    except: return d

def resolve_item_ci(typed, collection):
    """Return the canonical item name from collection that matches typed (case-insensitive), or None."""
    typed_l = typed.strip().lower()
    for item in collection:
        if item.lower() == typed_l:
            return item
    return None

# ── WORLD & WEATHER ───────────────────────────────────────────────────────────
WORLD_NAME = "The World of 8Ball"

WEATHER_TABLE = [
    {"name":"Clear Skies",         "desc":"The air is sharp and alive. Everything moves exactly as it should.",  "exp_mod":1.20,"dmg_mod":1.00},
    {"name":"Heavy Rain",          "desc":"A cold downpour slows everything down. Movement is sluggish.",          "exp_mod":1.00,"dmg_mod":0.90},
    {"name":"Perfect Conditions",  "desc":"The world is in balance. Ideal for battle and glory alike.",             "exp_mod":1.10,"dmg_mod":1.10},
    {"name":"Arcane Mist",         "desc":"Arcane energy warps the air. Reality flickers. Trust your instincts.",  "exp_mod":0.90,"dmg_mod":1.15},
    {"name":"Blood Moon",          "desc":"Something ancient awakens. The air crackles with power. High stakes incoming.", "exp_mod":1.30,"dmg_mod":1.20,"secret_eligible":True},
    {"name":"Cursed Fog",          "desc":"A thick haze clings to everything. Nothing moves as it should.",         "exp_mod":0.85,"dmg_mod":0.85},
]
_weather_cache = {"weather":None,"set_at":None}
def get_weather():
    now = datetime.now()
    if not _weather_cache["set_at"] or (now-_weather_cache["set_at"]).seconds > 3600:
        _weather_cache["weather"] = random.choice(WEATHER_TABLE)
        _weather_cache["set_at"]  = now
    return _weather_cache["weather"]

# ── EXP CURVE ─────────────────────────────────────────────────────────────────
def exp_for_level(level):
    if level <= 10:   return level * 200
    elif level <= 20: return level * 500
    elif level <= 30: return level * 1000
    elif level <= 40: return level * 2000
    elif level <= 50: return level * 4000
    elif level <= 60: return level * 10000
    elif level <= 70: return level * 25000
    elif level <= 80: return level * 60000
    elif level <= 90: return level * 120000
    else:             return level * 250000

def max_hp_for_level(level): return 100 + (level - 1) * 15

RANK_TIERS = [
    {"name":"👑 Legends",         "emoji":"👑","min":75,"max":100},
    {"name":"🎱 Tournament Players",   "emoji":"🎱","min":50,"max":74},
    {"name":"🔥 On the Rise",          "emoji":"🔥","min":25,"max":49},
    {"name":"💬 Regular Players",      "emoji":"💬","min":10,"max":24},
    {"name":"🌱 Newcomers",          "emoji":"🌱","min":1,  "max":9},
]
def get_tier(level):
    for t in RANK_TIERS:
        if t["min"] <= level <= t["max"]: return t
    return RANK_TIERS[-1]

PAGE_SIZE = 15

# ── CLASS TREE ────────────────────────────────────────────────────────────────
DEFAULT_STATS = {"STR":5,"DEF":0,"AGI":5,"INT":5,"WIS":5,"DEX":5,"LUK":5}

# path: "A" or "B"
# primary_stat: used for damage scaling
# weapon_types: what gear they can equip
# skills: list of {tier, name, type, desc, ...} unlocked at each threshold
CLASS_TREE = {
    # ── WARRIOR ──────────────────────────────────────────────────────────────
    "warrior": {
        "name":"Warrior","primary_stat":"STR","line":"warrior",
        "weapon_types":["sword_1h","sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"A force of nature. Built to crush enemies and dominate any battlefield.",
        "stat_bonus":{"STR":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Iron Will",
             "passive":"Take 10% less damage from all sources.",
             "active":"Shield Bash","type":"stun",
             "desc":"30% chance to stun target  -  they miss their next attack.",
             "passive_key":"iron_will"},
            {"tier":1,"unlock":5,"name":"Defensive Stance",
             "passive":"Reduce incoming damage by 5 when HP is above 70%.",
             "active":"Brace","type":"def_buff",
             "desc":"Gain +10 DEF for 2 minutes.",
             "passive_key":"defensive_stance"},
        ]
    },
    "page": {
        "name":"Page","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"The break is just the beginning. Every hit is a statement.",
        "stat_bonus":{"STR":1,"DEF":2},
        "skills":[
            {"tier":2,"unlock":10,"name":"Holy Stance",
             "passive":"Gain +15% defense when below 50% HP.",
             "active":"Consecrate","type":"dmg_field",
             "desc":"Deal damage + create a holy field for 30 min  -  enemies who attack you take WIS x2 holy damage back.",
             "passive_key":"holy_stance"},
            {"tier":2,"unlock":10,"name":"Shield Wall",
             "passive":"Reduce physical damage by 5 when shield is equipped.",
             "active":"Shield Wall","type":"def_buff",
             "desc":"Negate the next hit completely (lasts 90 seconds).",
             "passive_key":"shield_wall"},
        ]
    },
    "squire": {
        "name":"Squire","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"Controls the table by controlling the shot order. Nothing happens by accident.",
        "stat_bonus":{"STR":2,"DEF":2},
        "skills":[
            {"tier":3,"unlock":30,"name":"Devotion",
             "passive":"Each hit taken charges holy energy (+5 dmg on next strike).",
             "active":"Holy Strike","type":"combo_dmg",
             "desc":"Deal STR + DEF combined damage. Guaranteed stun if target below 40% HP.",
             "passive_key":"devotion"},
        ]
    },
    "knight": {
        "name":"Knight","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"Owns the table. Other players are just guests.",
        "stat_bonus":{"STR":3,"DEF":3},
        "skills":[
            {"tier":4,"unlock":60,"name":"Bulwark",
             "passive":"15% chance to completely block any incoming hit.",
             "active":"Rally","type":"self_heal_buff",
             "desc":"Restore 30% of your own HP. Grant all guild members in chat +15% damage for 10 minutes.",
             "passive_key":"bulwark"},
        ]
    },
    "paladin": {
        "name":"Paladin","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"The pinnacle of pure power. Every strike is a masterclass.",
        "stat_bonus":{"STR":4,"DEF":4,"WIS":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Divine Judgment",
             "passive":"All holy skills deal 25% more damage.",
             "active":"Wrath of the Fallen","type":"holy_nuke",
             "desc":"Massive STR+DEF+WIS x3 combined hit. On kill: all guild members in chat gain +20% damage for 30 minutes.",
             "passive_key":"divine_judgment"},
        ]
    },
    "fighter": {
        "name":"Fighter","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"Takes the hit so the team doesn't have to. Unmovable.",
        "stat_bonus":{"STR":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Bloodlust",
             "passive":"Each hit landed restores 5 HP.",
             "active":"Triple Strike","type":"multihit",
             "desc":"Hit three times. Second hit 70%, third hit 50%. Each has independent crit. If all three crit, Bloodlust heal triples.",
             "passive_key":"bloodlust","hits":3,"mults":[1.0, 0.70, 0.50]},
            {"tier":2,"unlock":10,"name":"Battle Cry",
             "passive":"Gain +3 STR for 1 minute after each kill.",
             "active":"Battle Cry","type":"self_heal_buff",
             "desc":"Restore 20 HP and gain +5 STR for 2 minutes.",
             "passive_key":"battle_cry"},
        ]
    },
    "crusader": {
        "name":"Crusader","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"Locks down the table. Nothing gets through that shouldn't.",
        "stat_bonus":{"STR":4,"DEF":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Warcry",
             "passive":"+20% damage when outnumbered (more enemies than allies attacked you).",
             "active":"Charge","type":"guaranteed_hit",
             "desc":"Guaranteed hit, ignores all dodge. Breaks any root/stun/freeze on yourself before striking.",
             "passive_key":"warcry"},
        ]
    },
    "hero": {
        "name":"Hero","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"The cushion is their weapon. Consistent, relentless, unbreakable.",
        "stat_bonus":{"STR":5,"DEF":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Unbreakable",
             "passive":"Cannot be one-shotted  -  always survive at 1 HP (once per fight).",
             "active":"Rampage","type":"aoe_recent_attackers",
             "desc":"Hit everyone who attacked you in the last 30 minutes. Damage scales +25% per attacker.",
             "passive_key":"unbreakable"},
        ]
    },
    "warlord": {
        "name":"Warlord","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"The Lord of 8ball",
        "stat_bonus":{"STR":6,"DEF":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Conqueror",
             "passive":"Every PVP kill restores 20% HP. Defeated targets take +25% more damage from all sources for 1 hour.",
             "active":"Decimation","type":"execute_nuke",
             "desc":"STR x6 damage, ignores all defense. On kill: target is weakened  -  takes 25% more damage for 1 hour.",
             "passive_key":"conqueror"},
        ]
    },
    # ── MAGE ─────────────────────────────────────────────────────────────────
    "mage": {
        "name":"Mage","primary_stat":"INT","line":"mage",
        "weapon_types":["wand","staff"],
        "armor_type":"mage_armor",
        "desc":"Reads angles others can't see. The table is a puzzle only they can solve.",
        "stat_bonus":{"INT":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Arcane Mind",
             "passive":"Each INT point adds +1 spell damage.",
             "active":"Fireball","type":"spell",
             "desc":"INT-scaled burst damage.",
             "passive_key":"arcane_mind"},
            {"tier":1,"unlock":5,"name":"Arcane Shield",
             "passive":"10% chance to absorb a hit entirely with a mana barrier.",
             "active":"Mana Barrier","type":"heal_shield",
             "desc":"Absorb up to INT x2 incoming damage for 1 minute.",
             "passive_key":"arcane_shield"},
        ]
    },
    "arcanist": {
        "name":"Arcanist","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Shots that shouldn't work. They always work.",
        "stat_bonus":{"INT":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Spell Surge",
             "passive":"20% chance any spell deals double damage.",
             "active":"Chain Lightning","type":"bounce_spell",
             "desc":"Hits target + bounces to 2 nearby active players dealing 50% damage each.",
             "passive_key":"spell_surge"},
            {"tier":2,"unlock":10,"name":"Arcane Pulse",
             "passive":"INT x0.1 bonus damage on every spell.",
             "active":"Arcane Pulse","type":"spell",
             "desc":"INT x2 arcane damage. Cannot be resisted.",
             "passive_key":"arcane_pulse"},
        ]
    },
    "sorcerer": {
        "name":"Sorcerer","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Sees three shots ahead. The geometry is already solved.",
        "stat_bonus":{"INT":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Arcane Mastery",
             "passive":"Every 3rd spell cast deals triple damage (tracked internally).",
             "active":"Meteor","type":"aoe_recent_attackers",
             "desc":"Massive AOE  -  hits target + everyone who attacked them in last 30 minutes.",
             "passive_key":"arcane_mastery"},
        ]
    },
    "archmage": {
        "name":"Archmage","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"The table obeys. Nobody's quite sure why.",
        "stat_bonus":{"INT":5,"AGI":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Mana Overload",
             "passive":"15% chance any attack against you triggers a shock  -  attacker takes INT-scaled damage back.",
             "active":"Supernova","type":"raid_aoe",
             "desc":"INT x5  -  hits all players currently in an active boss or raid fight.",
             "passive_key":"mana_overload"},
        ]
    },
    "sage": {
        "name":"Sage","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Ancient knowledge of every angle, every cushion, every possibility.",
        "stat_bonus":{"INT":6,"WIS":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Eternal Wisdom",
             "passive":"All spells ignore 50% of target defense.",
             "active":"Absolute Zero","type":"freeze_nuke",
             "desc":"INT x6 damage. Target cannot /attack for 60 seconds.",
             "passive_key":"eternal_wisdom"},
        ]
    },
    "hexblade": {
        "name":"Hexblade","primary_stat":"INT","line":"mage","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"A shadow with an edge. The mark never sees it coming.",
        "stat_bonus":{"INT":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Cursed Blade",
             "passive":"Physical attacks carry a hex  -  target deals 10% less damage for 2 minutes.",
             "active":"Hex","type":"debuff",
             "desc":"Curse target  -  they deal 25% less damage for 2 minutes.",
             "passive_key":"cursed_blade"},
            {"tier":2,"unlock":10,"name":"Shadow Hex",
             "passive":"Hexed targets take 5% extra damage from all sources.",
             "active":"Shadow Hex","type":"debuff",
             "desc":"Reduce target ATK and DEF by 5 for 3 minutes.",
             "passive_key":"shadow_hex"},
        ]
    },
    "warlock": {
        "name":"Warlock","primary_stat":"INT","line":"mage","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Curses the table in their favor. Legal? Technically.",
        "stat_bonus":{"INT":3,"WIS":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Soul Pact",
             "passive":"Heal 20% of all spell damage dealt.",
             "active":"Death Curse","type":"drain",
             "desc":"Drain 30% of target current HP, add it to your own.",
             "passive_key":"soul_pact","drain_pct":0.30},
        ]
    },
    "lich": {
        "name":"Lich","primary_stat":"INT","line":"mage","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Death doesn't stop a Rail Wraith. Nothing does.",
        "stat_bonus":{"INT":4,"WIS":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Undying",
             "passive":"Once per day survive a killing blow at 1 HP.",
             "active":"Drain Soul","type":"drain_kill",
             "desc":"Steal 40% of target current HP. On kill: gain +50 temp HP for 2 hours.",
             "passive_key":"undying","drain_pct":0.40},
        ]
    },
    "void_mage": {
        "name":"Void Mage","primary_stat":"INT","line":"mage","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"The last ball on the table. The one that decides everything.",
        "stat_bonus":{"INT":6,"AGI":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Void Rift",
             "passive":"25% chance any attack against you misses  -  absorbed by the void.",
             "active":"Void Collapse","type":"void_nuke",
             "desc":"Target loses 50% of current HP instantly. Cannot be healed for 30 minutes.",
             "passive_key":"void_rift"},
        ]
    },
    # ── THIEF ─────────────────────────────────────────────────────────────────
    "thief": {
        "name":"Thief","primary_stat":"LUK","line":"thief",
        "weapon_types":["dagger","throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Silent, precise, dangerous. In the water before you know it.",
        "stat_bonus":{"AGI":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Quick Hands",
             "passive":"+15% crit chance on all attacks.",
             "active":"Backstab","type":"crit_dmg",
             "desc":"180% damage. Guaranteed crit if target has not attacked yet.",
             "passive_key":"quick_hands","mult":1.8},
            {"tier":1,"unlock":5,"name":"Feint",
             "passive":"5% chance each hit causes target to miss their next attack.",
             "active":"Feint","type":"acc_debuff_only",
             "desc":"Target has 40% miss chance for their next attack.",
             "passive_key":"feint"},
        ]
    },
    "rogue": {
        "name":"Rogue","primary_stat":"LUK","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Gets in, gets out, pockets something on the way.",
        "stat_bonus":{"AGI":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Evasion",
             "passive":"15% chance to dodge any incoming attack.",
             "active":"Smoke Screen","type":"dodge_buff",
             "desc":"Next attack against you automatically misses. Lasts 2 minutes.",
             "passive_key":"evasion"},
            {"tier":2,"unlock":10,"name":"Nimble",
             "passive":"AGI x0.5 bonus dodge chance.",
             "active":"Dash","type":"dodge_buff",
             "desc":"Gain +20% dodge for 1 minute.",
             "passive_key":"nimble"},
        ]
    },
    "shadow": {
        "name":"Shadow","primary_stat":"LUK","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Clears the table quietly. Nobody sees it happen.",
        "stat_bonus":{"AGI":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Shadowstep",
             "passive":"After dodging, next attack deals +50% bonus damage.",
             "active":"Shadow Strike","type":"pierce_dmg",
             "desc":"AGI x3 damage. Cannot be dodged or blocked.",
             "passive_key":"shadowstep"},
        ]
    },
    "phantom": {
        "name":"Phantom","primary_stat":"LUK","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"You can't foul what you can't see.",
        "stat_bonus":{"AGI":5,"INT":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Ghost Form",
             "passive":"20% chance any attack passes through you dealing no damage.",
             "active":"Vanish","type":"vanish",
             "desc":"Become untargetable for 60 seconds. No one can /attack you.",
             "passive_key":"ghost_form"},
        ]
    },
    "wraith": {
        "name":"Wraith","primary_stat":"LUK","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"The blade moves. Nobody held it.",
        "stat_bonus":{"AGI":6,"INT":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Death's Shadow",
             "passive":"Every dodge restores 10 HP.",
             "active":"Soul Rend","type":"fear_kill",
             "desc":"AGI x6 damage. On kill: cannot be attacked for 30 minutes.",
             "passive_key":"deaths_shadow"},
        ]
    },
    "cutthroat": {
        "name":"Cutthroat","primary_stat":"LUK","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Thin cut, maximum damage. Always the hard way.",
        "stat_bonus":{"AGI":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Marked",
             "passive":"First attack on any target deals +25% bonus damage.",
             "active":"Cheap Shot","type":"silence",
             "desc":"150% damage. Target cannot use /skill for 60 seconds.",
             "passive_key":"marked","mult":1.5},
            {"tier":2,"unlock":10,"name":"Throat Cut",
             "passive":"5% chance each hit silences target for 10 seconds.",
             "active":"Throat Cut","type":"silence",
             "desc":"100% damage. Target cannot use /skill for 30 seconds.",
             "passive_key":"throat_cut","mult":1.0},
        ]
    },
    "assassin": {
        "name":"Assassin","primary_stat":"LUK","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Knows the odds. Sets them. Wins them.",
        "stat_bonus":{"AGI":3,"STR":2},
        "skills":[
            {"tier":3,"unlock":30,"name":"Execute",
             "passive":"Attacks against targets below 25% HP deal double damage.",
             "active":"Eviscerate","type":"bleed_crit",
             "desc":"200% damage, always crits. Survivor bleeds 10 damage every 30 seconds for 5 minutes.",
             "passive_key":"execute","mult":2.0},
        ]
    },
    "blade_master": {
        "name":"Blade Master","primary_stat":"LUK","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Fixes every problem the same way  -  by making it disappear.",
        "stat_bonus":{"AGI":4,"STR":3},
        "skills":[
            {"tier":4,"unlock":60,"name":"Flurry",
             "passive":"Every attack has 20% chance to hit twice.",
             "active":"Blade Storm","type":"multihit_crit",
             "desc":"Hit target 5 times for 60% damage each. Each hit has independent crit chance.",
             "passive_key":"flurry","hits":5,"mult":0.6},
        ]
    },
    "specialist": {
        "name":"Specialist","primary_stat":"LUK","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Wins through angles nobody else considered legal.",
        "stat_bonus":{"AGI":5,"STR":4},
        "skills":[
            {"tier":5,"unlock":100,"name":"The Professional",
             "passive":"All debuffs you apply last 50% longer. All attacks ignore 30% of defense.",
             "active":"Contract","type":"bounty_mark",
             "desc":"Mark target for 1 hour. Every attack against them by anyone deals +20% damage. You get 50% of all EXP earned from that target.",
             "passive_key":"the_professional"},
        ]
    },
    # ── ARCHER ────────────────────────────────────────────────────────────────
    "archer": {
        "name":"Archer","primary_stat":"DEX","line":"archer",
        "weapon_types":["bow","crossbow"],
        "armor_type":"archer_armor",
        "desc":"Calls every shot before it happens. Never misses what matters.",
        "stat_bonus":{"AGI":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Eagle Eye",
             "passive":"Never miss when your AGI is higher than target DEF.",
             "active":"Aimed Shot","type":"pierce_dodge",
             "desc":"140% damage. Ignores dodge completely.",
             "passive_key":"eagle_eye","mult":1.4},
            {"tier":1,"unlock":5,"name":"Warning Shot",
             "passive":"First attack each fight reduces target AGI by 2 for 1 minute.",
             "active":"Warning Shot","type":"dmg_acc_debuff",
             "desc":"80% damage. Target has 20% increased miss chance for 2 minutes.",
             "passive_key":"warning_shot","mult":0.8},
        ]
    },
    "scout": {
        "name":"Scout","primary_stat":"DEX","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Calls the corner pocket from downtown. Makes it every time.",
        "stat_bonus":{"AGI":2,"INT":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Trailblazer",
             "passive":"First attack each day deals double damage.",
             "active":"Distract","type":"miss_debuff",
             "desc":"Target has 30% increased miss chance for 3 minutes.",
             "passive_key":"trailblazer"},
            {"tier":2,"unlock":10,"name":"Keen Sight",
             "passive":"DEX x0.5 bonus accuracy on all attacks.",
             "active":"Mark Target","type":"dmg_acc_debuff",
             "desc":"Reduce target dodge by 15% for 2 minutes.",
             "passive_key":"keen_sight"},
        ]
    },
    "ranger": {
        "name":"Ranger","primary_stat":"DEX","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"One shot, one pocket. Distance is irrelevant.",
        "stat_bonus":{"AGI":3,"DEF":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Nature's Bond",
             "passive":"-10% damage taken from all sources.",
             "active":"Entangle","type":"root",
             "desc":"Target cannot /attack for 90 seconds.",
             "passive_key":"natures_bond"},
        ]
    },
    "warden": {
        "name":"Warden","primary_stat":"DEX","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"In the zone. Untouchable. Every shot automatic.",
        "stat_bonus":{"AGI":3,"DEF":3},
        "skills":[
            {"tier":4,"unlock":60,"name":"Guardian Stance",
             "passive":"If a guild member is attacked you have 20% chance to intercept the hit.",
             "active":"Barrage","type":"random_aoe",
             "desc":"Fire 6 arrows at random active players in chat. Each deals AGI x1.5 damage.",
             "passive_key":"guardian_stance"},
        ]
    },
    "strider": {
        "name":"Strider","primary_stat":"DEX","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Moves through the table like it isn't there.",
        "stat_bonus":{"AGI":5,"DEF":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Railfinder",
             "passive":"Cannot be rooted, frozen or stunned by any skill ever.",
             "active":"Storm of Arrows","type":"aoe_recent_attackers",
             "desc":"AGI x8 split across all players who attacked you in last 30 minutes.",
             "passive_key":"pathfinder"},
        ]
    },
    "bounty_hunter": {
        "name":"Bounty Hunter","primary_stat":"DEX","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"Uses every cushion. The long way is the right way.",
        "stat_bonus":{"AGI":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Marked for Death",
             "passive":"Targets you defeat drop +25% more gold. You earn their unclaimed daily EXP on kill.",
             "active":"Execution Order","type":"bounty",
             "desc":"Place a 2,000g bounty on any player. Marks them (+20% dmg taken 30 min). Placer gets 25% back if someone else claims. You get +25% if you collect it yourself.",
             "passive_key":"marked_for_death"},
            {"tier":2,"unlock":10,"name":"Tracker",
             "passive":"Can see target cooldowns via /stats mention.",
             "active":"Cripple","type":"miss_debuff",
             "desc":"Reduce target AGI by 5 and apply 25% miss chance for 2 minutes.",
             "passive_key":"tracker"},
        ]
    },
    "sharpshooter": {
        "name":"Sharpshooter","primary_stat":"DEX","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"Consistency over flash. Wins more than they should.",
        "stat_bonus":{"AGI":3,"STR":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Steady Aim",
             "passive":"Each consecutive attack on same target deals +10% more damage (max 50%).",
             "active":"Piercing Shot","type":"pierce_all",
             "desc":"STR x2 damage. Ignores all defense and passives.",
             "passive_key":"steady_aim"},
        ]
    },
    "sniper": {
        "name":"Sniper","primary_stat":"DEX","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"Never rushes. Never misses.",
        "stat_bonus":{"AGI":4,"STR":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Headshot",
             "passive":"Crits deal 300% instead of 200%.",
             "active":"Killshot","type":"charged_shot",
             "desc":"Charge: next /attack fires AGI x4. Cannot be dodged or blocked.",
             "passive_key":"headshot"},
        ]
    },
    "deadeye": {
        "name":"Deadeye","primary_stat":"DEX","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"The pocket is the only thing that exists.",
        "stat_bonus":{"AGI":6,"STR":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Dead or Alive",
             "passive":"Every kill permanently adds +2 to your max damage ceiling. Stacks forever.",
             "active":"Last Shot","type":"execution_shot",
             "desc":"On kill: target defeated timer doubled to 12 hours. You earn triple gold and EXP. Public announcement names you.",
             "passive_key":"dead_or_alive"},
        ]
    },
    # ── PRIEST ────────────────────────────────────────────────────────────────
    "priest": {
        "name":"Priest","primary_stat":"WIS","line":"priest",
        "weapon_types":["rosary","cross"],
        "armor_type":"priest_armor",
        "desc":"Keeps everyone sharp. The one who holds the team together.",
        "stat_bonus":{"WIS":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Mending Aura",
             "passive":"All heals you cast are 25% more effective.",
             "active":"Holy Light","type":"revive_heal",
             "desc":"Heal target for WIS x5 HP. Works on defeated players  -  revives them.",
             "passive_key":"mending_aura"},
            {"tier":1,"unlock":5,"name":"Mend",
             "passive":"Regen 3 HP every 10 minutes passively.",
             "active":"Mend","type":"self_heal",
             "desc":"Restore WIS x2 HP to yourself.",
             "passive_key":"mend"},
        ]
    },
    "cleric": {
        "name":"Cleric","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"Keeps everything above board. Calls every shot clean.",
        "stat_bonus":{"WIS":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Divine Grace",
             "passive":"Every time you heal someone you restore 10% of your own HP.",
             "active":"Blessing","type":"dmg_reduction_buff",
             "desc":"Grant target 1 hour of damage reduction (15% less damage taken).",
             "passive_key":"divine_grace"},
            {"tier":2,"unlock":10,"name":"Renew",
             "passive":"Heals you cast leave a regen buff  -  5 HP per 30s for 5 minutes.",
             "active":"Renew","type":"regen",
             "desc":"Apply regen to target: restore WIS HP every 30 seconds for 5 minutes.",
             "passive_key":"renew"},
        ]
    },
    "bishop": {
        "name":"Bishop","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"Studies the sacred texts like scripture. Knows the divine arts better than anyone.",
        "stat_bonus":{"WIS":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Sacred Ground",
             "passive":"Players you have healed take 10% less damage for 1 hour after being healed.",
             "active":"Mass Heal","type":"group_heal",
             "desc":"Heal all guild members currently in chat for WIS x3 HP each. No potion required.",
             "passive_key":"sacred_ground"},
        ]
    },
    "high_priest": {
        "name":"High Priest","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"The stakes are never too high. The path never ends.",
        "stat_bonus":{"WIS":5,"DEF":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Resurrection",
             "passive":"Once per day if you reach 0 HP you automatically revive at 30% HP.",
             "active":"Miracle","type":"full_revive",
             "desc":"Fully restore target to max HP. Grant 2 hours invincibility. Costs one Holy Water Vial.",
             "passive_key":"resurrection"},
        ]
    },
    "saint": {
        "name":"Saint","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"The table's guardian. Everyone plays better when they're around.",
        "stat_bonus":{"WIS":6,"DEF":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Divine Presence",
             "passive":"All guild members in active chat gain +5% EXP and regen 5 HP every 30 minutes while you are online.",
             "active":"Absolution","type":"mass_cleanse",
             "desc":"Cleanse ALL debuffs from ALL guild members. Grant 30 minutes of blessed status (+10% all stats). COUNTERS Zealot's revival block.",
             "passive_key":"divine_presence"},
        ]
    },
    "acolyte": {
        "name":"Acolyte","primary_stat":"WIS","line":"priest","path":"B",
        "weapon_types":["cross"],
        "armor_type":"priest_armor",
        "desc":"Watches everything. Misses nothing. Rules on contact.",
        "stat_bonus":{"WIS":2,"INT":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Dark Sense",
             "passive":"Can see all active debuffs on any player via /stats.",
             "active":"Smite","type":"holy_dmg",
             "desc":"WIS x3 holy damage. Deals double against players who have recently defeated others.",
             "passive_key":"dark_sense"},
            {"tier":2,"unlock":10,"name":"Holy Fervor",
             "passive":"WIS x0.1 bonus damage on holy attacks.",
             "active":"Holy Fervor","type":"self_heal_buff",
             "desc":"Gain +5 WIS and restore 15 HP for 2 minutes.",
             "passive_key":"holy_fervor"},
        ]
    },
    "exorcist": {
        "name":"Exorcist","primary_stat":"WIS","line":"priest","path":"B",
        "weapon_types":["cross"],
        "armor_type":"priest_armor",
        "desc":"Enforces the laws of the divine with zero mercy.",
        "stat_bonus":{"WIS":3,"INT":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Purge",
             "passive":"Your attacks strip one active buff from target on every hit.",
             "active":"Banish","type":"strip_debuff",
             "desc":"Remove ALL buffs from target. Deal WIS x2 damage per buff removed. Target cannot gain buffs for 30 minutes.",
             "passive_key":"purge"},
        ]
    },
    "inquisitor": {
        "name":"Inquisitor","primary_stat":"WIS","line":"priest","path":"B",
        "weapon_types":["cross"],
        "armor_type":"priest_armor",
        "desc":"Diagonal movement. Unexpected angles. Ruthless efficiency.",
        "stat_bonus":{"WIS":4,"INT":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Judgement",
             "passive":"Players who attack you take WIS-scaled holy damage back (10% of WIS as reflect).",
             "active":"Trial","type":"bind_attacker",
             "desc":"Put target on trial. They cannot attack anyone except you for 10 minutes. Their attacks against you deal 50% less damage.",
             "passive_key":"judgement"},
        ]
    },
    "zealot": {
        "name":"Zealot","primary_stat":"WIS","line":"priest","path":"B",
        "weapon_types":["cross"],
        "armor_type":"priest_armor",
        "desc":"The final word on the table. Appeals are not accepted.",
        "stat_bonus":{"WIS":6,"INT":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Wrath of the Righteous",
             "passive":"Every debuff you apply deals WIS x0.5 damage per minute until it expires.",
             "active":"Holy Wrath","type":"condemn",
             "desc":"WIS x8 damage. Strip all buffs. Apply all known debuffs simultaneously. On kill: target CANNOT be revived for 2 hours. Only Saint's Absolution can counter this.",
             "passive_key":"wrath_of_the_righteous"},
        ]
    },
    # ── BOTANIST ─────────────────────────────────────────────────────────────
    "botanist": {
        "name":"Botanist","primary_stat":"WIS","line":"botanist",
        "weapon_types":["wand","staff"],
        "armor_type":"mage_armor",
        "desc":"Wielder of nature's power — healing blooms and deadly thorns in equal measure.",
        "stat_bonus":{"WIS":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Natural Growth",
             "passive":"Regen 5 HP every 5 minutes. 12% chance each attack plants a poison seed on target (15 dmg/30s for 2 min).",
             "active":"Healing Bloom","type":"revive_heal",
             "desc":"Bloom restores WIS x4 HP to self or target. Works on defeated allies — revives them.",
             "passive_key":"natural_growth"},
            {"tier":1,"unlock":5,"name":"Thorn Skin",
             "passive":"Attackers take WIS x0.5 damage when hitting you.",
             "active":"Thorn Lash","type":"bleed_crit",
             "desc":"WIS x2 nature strike + apply bleed (15 dmg/30s for 5 min).",
             "passive_key":"thorn_skin"},
        ]
    },
    # Path A — Support/Healing
    "florist": {
        "name":"Florist","primary_stat":"WIS","line":"botanist","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Spreads warmth and healing wherever she walks. Her garden never withers.",
        "stat_bonus":{"WIS":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Garden Aura",
             "passive":"Guild members in chat regen 5 HP every 30 minutes while you are active.",
             "active":"Petal Veil","type":"dodge_buff",
             "desc":"Surround self or target with swirling petals: +25% dodge for 60 seconds.",
             "passive_key":"garden_aura"},
            {"tier":2,"unlock":10,"name":"Blossoming",
             "passive":"All healing you perform is 20% more effective.",
             "active":"Bloom Mend","type":"self_heal",
             "desc":"Restore WIS x3 HP instantly. Remove one active bleed or poison from target.",
             "passive_key":"blossoming"},
        ]
    },
    "bloom_witch": {
        "name":"Bloom Witch","primary_stat":"WIS","line":"botanist","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Where she dances, flowers bloom — and enemies wither.",
        "stat_bonus":{"WIS":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Wildflower Shield",
             "passive":"12% chance to dodge any incoming hit. On dodge: instantly regain 10 HP.",
             "active":"Spore Cloud","type":"aoe_recent_attackers",
             "desc":"Release a toxic cloud: apply poison (20 dmg/30s for 3 min) to target and all recent attackers.",
             "passive_key":"wildflower_shield"},
        ]
    },
    "petal_sage": {
        "name":"Petal Sage","primary_stat":"WIS","line":"botanist","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Ancient wisdom encoded in petals. Her words heal, her silence warns.",
        "stat_bonus":{"WIS":5,"INT":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Verdant Renewal",
             "passive":"Each heal you cast has 20% chance to heal double. Guild members healed by you take 10% less damage for 1 hour.",
             "active":"Garden of Eden","type":"group_heal",
             "desc":"Restore WIS x3 HP to all guild members in chat. Grant regen 10 HP/30s for 2 hours.",
             "passive_key":"verdant_renewal"},
        ]
    },
    "wildflower_empress": {
        "name":"Wildflower Empress","primary_stat":"WIS","line":"botanist","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Nature herself bows. Every petal is a decree.",
        "stat_bonus":{"WIS":6,"INT":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Eternal Bloom",
             "passive":"Cannot be poisoned or diseased. All heals 50% stronger. Allies you've healed gain +5% all stats while in chat.",
             "active":"Blossom Nova","type":"aoe_heal_dmg",
             "desc":"Pulse of pure life: heal all allies for WIS x5 HP. Enemies currently poisoned take WIS x8 burst damage.",
             "passive_key":"eternal_bloom"},
        ]
    },
    # Path B — Poison/Offense
    "thornweaver": {
        "name":"Thornweaver","primary_stat":"WIS","line":"botanist","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"She weaves thorns into every strike. Every bloom hides a barb.",
        "stat_bonus":{"WIS":3,"INT":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Thorn Aura",
             "passive":"Attackers take WIS x1 damage when hitting you.",
             "active":"Briar Whip","type":"bleed_crit",
             "desc":"WIS x2.5 nature strike + apply bleed (15 dmg/30s for 5 min). Cannot be blocked.",
             "passive_key":"thorn_aura"},
            {"tier":2,"unlock":10,"name":"Nettleskin",
             "passive":"10% chance each incoming hit poisons the attacker (15 dmg/30s for 2 min).",
             "active":"Nettle Storm","type":"debuff",
             "desc":"Fling stinging nettles: reduce target ATK and DEF by 8 for 2 minutes.",
             "passive_key":"nettleskin"},
        ]
    },
    "briar_knight": {
        "name":"Briar Knight","primary_stat":"WIS","line":"botanist","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Armed with thorns sharper than any blade.",
        "stat_bonus":{"WIS":4,"INT":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Venomous Growth",
             "passive":"Your poison effects deal 35% more damage. Poisoned targets take +10% damage from all sources.",
             "active":"Toxic Bloom","type":"aoe_poison_strong",
             "desc":"Plant a toxic seed on target: WIS x1 poison damage every 30s for 10 minutes. Spreads to one nearby player.",
             "passive_key":"venomous_growth"},
        ]
    },
    "verdant_warden": {
        "name":"Verdant Warden","primary_stat":"WIS","line":"botanist","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Guardian of the wild. She endures all and poisons all who dare.",
        "stat_bonus":{"WIS":5,"INT":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Ancient Bark",
             "passive":"15% chance to completely absorb incoming damage. Poisoned enemies who hit you take double thorn damage.",
             "active":"Thorn Fortress","type":"def_reflect",
             "desc":"For 2 minutes: reduce all incoming damage by 40% and reflect half back as nature damage.",
             "passive_key":"ancient_bark"},
        ]
    },
    "natures_chosen": {
        "name":"Nature's Chosen","primary_stat":"WIS","line":"botanist","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Nature's wrath made flesh. Neither blade nor spell can hold her.",
        "stat_bonus":{"WIS":6,"INT":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Primal Fury",
             "passive":"All poison effects you apply stack up to 3x. Your attacks deal bonus WIS% nature damage. You cannot be silenced.",
             "active":"Wrath of the Wild","type":"nature_nuke",
             "desc":"WIS x7 nature damage. Apply max-stack poison. Target loses all healing for 30 minutes.",
             "passive_key":"primal_fury"},
        ]
    },
    # ── ENCHANTRESS ──────────────────────────────────────────────────────────
    "enchantress": {
        "name":"Enchantress","primary_stat":"INT","line":"enchantress",
        "weapon_types":["wand","staff"],
        "armor_type":"mage_armor",
        "desc":"Her charm is a weapon. Her hex is a sentence. Both are inescapable.",
        "stat_bonus":{"INT":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Allure",
             "passive":"15% chance to fascinate any attacker — they deal 40% less damage for 60 seconds.",
             "active":"Bewitch","type":"debuff",
             "desc":"Reduce target ATK by 30% for 3 minutes. They cannot be buffed during this time.",
             "passive_key":"allure"},
            {"tier":1,"unlock":5,"name":"Beguile",
             "passive":"8% chance to reflect any skill back at its caster for 50% damage.",
             "active":"Hex Bolt","type":"spell",
             "desc":"INT x1.5 arcane damage + 20% chance to stun target for 30 seconds.",
             "passive_key":"beguile"},
        ]
    },
    # Path A — Curse/Hex
    "hex_dancer": {
        "name":"Hex Dancer","primary_stat":"INT","line":"enchantress","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Her curses move like a dance — fluid, graceful, and absolutely lethal.",
        "stat_bonus":{"INT":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Hexmark",
             "passive":"Targets you debuff take +12% damage from all sources for the debuff's duration.",
             "active":"Mark of Hex","type":"debuff",
             "desc":"INT x2 damage + brand target: all damage they take is increased 12% for 3 minutes.",
             "passive_key":"hexmark"},
            {"tier":2,"unlock":10,"name":"Curse Touch",
             "passive":"8% chance each hit applies Weakness (target deals 10% less dmg for 2 min).",
             "active":"Weaken","type":"debuff",
             "desc":"Reduce target ATK by 20% and DEF by 10 for 2 minutes.",
             "passive_key":"curse_touch"},
        ]
    },
    "cursebinder": {
        "name":"Cursebinder","primary_stat":"INT","line":"enchantress","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Binds fate with curses. Every step is a trap. Every word is a hex.",
        "stat_bonus":{"INT":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Stacking Curses",
             "passive":"You can apply up to 3 different debuffs simultaneously. Each new curse deals INT x0.5 burst damage.",
             "active":"Doom Curse","type":"drain_debuff",
             "desc":"Drain 25% of target current HP. Simultaneously apply: Weak + Hex + Exposed.",
             "passive_key":"stacking_curses"},
        ]
    },
    "vexmistress": {
        "name":"Vexmistress","primary_stat":"INT","line":"enchantress","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Her victims vex themselves. She merely watches and smiles.",
        "stat_bonus":{"INT":5,"AGI":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Misery Aura",
             "passive":"All debuffed enemies within your presence take 10 additional damage per hit from any source.",
             "active":"Vex Chain","type":"curse_chain",
             "desc":"Curse bounces to up to 3 targets: each takes INT x1.5 damage and -25% ATK/DEF for 5 minutes.",
             "passive_key":"misery_aura"},
        ]
    },
    "dread_empress": {
        "name":"Dread Empress","primary_stat":"INT","line":"enchantress","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Empress of ruin. Her name alone weakens the spirit.",
        "stat_bonus":{"INT":6,"AGI":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Empress's Dread",
             "passive":"Your presence causes fear: all enemies have -15% ATK. On kill, your debuffs transfer to a random other target.",
             "active":"Dread Proclamation","type":"mass_debuff",
             "desc":"Apply max-stack curses to ALL players who attacked you in the last hour. Cannot be cleansed for 1 hour.",
             "passive_key":"empress_dread"},
        ]
    },
    # Path B — Charm/Party Buff
    "charmsong": {
        "name":"Charmsong","primary_stat":"INT","line":"enchantress","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Her song lifts hearts and stills swords. An army follows her tune.",
        "stat_bonus":{"INT":2,"WIS":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Harmonize",
             "passive":"Guild members in chat gain +4% ATK while you are active.",
             "active":"Siren's Song","type":"stun",
             "desc":"Target is entranced and cannot attack for 40 seconds. If already stunned, effect doubles.",
             "passive_key":"harmonize"},
            {"tier":2,"unlock":10,"name":"Melody",
             "passive":"Your heals and buffs grant target +2 INT for 5 minutes (stacks up to 3×).",
             "active":"Hymn of Battle","type":"self_heal_buff",
             "desc":"Grant self or target: +10 ATK and +8 DEF for 3 minutes.",
             "passive_key":"melody"},
        ]
    },
    "songweaver": {
        "name":"Songweaver","primary_stat":"INT","line":"enchantress","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Weaves spells into melodies. The battlefield becomes her stage.",
        "stat_bonus":{"INT":3,"WIS":2},
        "skills":[
            {"tier":3,"unlock":30,"name":"Battle Hymn",
             "passive":"Once per fight, the first guild member to drop below 30% HP gains +20% ATK for 3 minutes.",
             "active":"War Song","type":"party_atk_buff",
             "desc":"Grant all guild members in chat +25% ATK for 5 minutes. Stacks with other buffs.",
             "passive_key":"battle_hymn"},
        ]
    },
    "lorewarden": {
        "name":"Lorewarden","primary_stat":"INT","line":"enchantress","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"Keeper of ancient songs. Her lore reshapes the tide of battle.",
        "stat_bonus":{"INT":4,"WIS":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Lorekeeping",
             "passive":"Guild members in chat gain +5% EXP from all sources while you are active.",
             "active":"Ancient Aria","type":"party_full_buff",
             "desc":"Grant all guild members: +15% ATK/DEF/dodge for 10 minutes. Remove 1 debuff from each.",
             "passive_key":"lorekeeping"},
        ]
    },
    "grand_muse": {
        "name":"Grand Muse","primary_stat":"INT","line":"enchantress","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"The muse of muses. Her magnum opus turns warriors into legends.",
        "stat_bonus":{"INT":5,"WIS":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Muse's Grace",
             "passive":"All guild members in chat have their skill cooldowns reduced 10%. Your buff/heal spells cost no cooldown.",
             "active":"Magnum Opus","type":"ultimate_buff",
             "desc":"Grant all guild members: full HP restore, +20% all stats for 30 minutes, immunity to debuffs for 10 minutes.",
             "passive_key":"muses_grace"},
        ]
    },
    # ── VALKYRIE ─────────────────────────────────────────────────────────────
    "valkyrie": {
        "name":"Valkyrie","primary_stat":"STR","line":"valkyrie",
        "weapon_types":["sword_1h","sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"Chosen by fate to stand between life and death. She does not fall.",
        "stat_bonus":{"STR":2,"WIS":1},
        "skills":[
            {"tier":1,"unlock":5,"name":"Einherjar's Will",
             "passive":"When below 30% HP, gain +40% ATK. Once per hour: survive a fatal blow at 1 HP.",
             "active":"War Cry","type":"self_atk_buff",
             "desc":"Unleash a battle cry: gain +30% ATK and +15% DEF for 2 minutes.",
             "passive_key":"einherjar_will"},
            {"tier":1,"unlock":5,"name":"Shield Maiden",
             "passive":"Reduce incoming damage by 5 when above 50% HP.",
             "active":"Aegis Wall","type":"def_buff",
             "desc":"Brace for impact: block the next 3 incoming attacks completely (lasts 90 seconds).",
             "passive_key":"shield_maiden"},
        ]
    },
    # Path A — Defense/Protect
    "shieldmaiden": {
        "name":"Shieldmaiden","primary_stat":"STR","line":"valkyrie","path":"A",
        "weapon_types":["sword_1h"],
        "armor_type":"warrior_armor",
        "desc":"Her shield is her creed. Those behind it need fear nothing.",
        "stat_bonus":{"STR":2,"DEF":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Stalwart",
             "passive":"15% chance to block any incoming hit completely.",
             "active":"Shield Slam","type":"stun_def_dmg",
             "desc":"(STR + DEF) combined damage. 40% chance to stun for 30 seconds.",
             "passive_key":"stalwart"},
            {"tier":2,"unlock":10,"name":"Defender's Oath",
             "passive":"When a guild member in chat is defeated, gain +10% ATK for 10 minutes (up to 3 stacks).",
             "active":"Oath Surge","type":"self_heal_buff",
             "desc":"Honor the fallen: gain +15 DEF and restore 20% max HP for 2 minutes.",
             "passive_key":"defenders_oath"},
        ]
    },
    "runeguard": {
        "name":"Runeguard","primary_stat":"STR","line":"valkyrie","path":"A",
        "weapon_types":["sword_1h"],
        "armor_type":"warrior_armor",
        "desc":"Her armor carved with runes older than kingdoms. Each one a promise.",
        "stat_bonus":{"STR":3,"DEF":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Runic Ward",
             "passive":"Runes absorb the first 20 damage of every incoming hit.",
             "active":"Rune Barrier","type":"party_def_buff",
             "desc":"Grant all guild members in chat 20% damage reduction for 5 minutes.",
             "passive_key":"runic_ward"},
        ]
    },
    "vanguard": {
        "name":"Vanguard","primary_stat":"STR","line":"valkyrie","path":"A",
        "weapon_types":["sword_1h"],
        "armor_type":"warrior_armor",
        "desc":"First into the fight. Last to leave. The wall others hide behind.",
        "stat_bonus":{"STR":4,"DEF":5},
        "skills":[
            {"tier":4,"unlock":60,"name":"Iron Bulwark",
             "passive":"Take 20% less damage from all sources. Guild members you have recently defended gain +5% DEF.",
             "active":"Vanguard's Presence","type":"intercept_aoe",
             "desc":"For 2 minutes: intercept up to 3 attacks aimed at guild members. Each intercepted hit: attacker takes DEF x2 back.",
             "passive_key":"iron_bulwark"},
        ]
    },
    "iron_valkyrie": {
        "name":"Iron Valkyrie","primary_stat":"STR","line":"valkyrie","path":"A",
        "weapon_types":["sword_1h"],
        "armor_type":"warrior_armor",
        "desc":"Legend forged in iron and oath. She has never known defeat.",
        "stat_bonus":{"STR":5,"DEF":6,"WIS":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Immortal Aegis",
             "passive":"Cannot be defeated by a single hit. Resurrect once per fight at 50% HP. All guild members gain +5% DEF while you are in chat.",
             "active":"Bifrost Descent","type":"holy_warrior_nuke",
             "desc":"STR x4 + DEF x4 combined holy strike. Stun target 60s. All guild members heal 30% max HP.",
             "passive_key":"immortal_aegis"},
        ]
    },
    # Path B — Storm/Lightning Offense
    "stormbringer": {
        "name":"Stormbringer","primary_stat":"STR","line":"valkyrie","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"She rides the storm and wears lightning like a crown.",
        "stat_bonus":{"STR":3,"AGI":2},
        "skills":[
            {"tier":2,"unlock":10,"name":"Thunder Step",
             "passive":"After dodging, next attack deals +40% lightning bonus damage.",
             "active":"Chain Lightning","type":"bounce_spell",
             "desc":"STR x2 lightning strike — bounces to up to 3 nearby active players dealing 50% each.",
             "passive_key":"thunder_step"},
            {"tier":2,"unlock":10,"name":"Storm Instinct",
             "passive":"Crits have 25% chance to proc a free second hit at 50% damage.",
             "active":"Thunderclap","type":"stun",
             "desc":"Unleash a thunderclap: target stunned for 30 seconds, cannot attack or use skills.",
             "passive_key":"storm_instinct"},
        ]
    },
    "thunder_sister": {
        "name":"Thunder Sister","primary_stat":"STR","line":"valkyrie","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"Where she strikes, the sky answers.",
        "stat_bonus":{"STR":4,"AGI":2},
        "skills":[
            {"tier":3,"unlock":30,"name":"Thunderstrike",
             "passive":"Crits create a shockwave — target stunned for 15 seconds.",
             "active":"Lightning Lance","type":"pierce_dmg",
             "desc":"STR x3.5 lightning damage. On crit: stun target 30s. Cannot be blocked or dodged.",
             "passive_key":"thunderstrike"},
        ]
    },
    "storm_sovereign": {
        "name":"Storm Sovereign","primary_stat":"STR","line":"valkyrie","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"Sovereign of all storms. The sky is her domain.",
        "stat_bonus":{"STR":5,"AGI":3},
        "skills":[
            {"tier":4,"unlock":60,"name":"Storm's Eye",
             "passive":"Every 5th attack is guaranteed crit. Storm count shown in /stats.",
             "active":"Tempest Fury","type":"aoe_recent_attackers",
             "desc":"STR x4 to primary + STR x2 split across all recent attackers. All hit players slowed for 30 seconds.",
             "passive_key":"storms_eye"},
        ]
    },
    "divine_tempest": {
        "name":"Divine Tempest","primary_stat":"STR","line":"valkyrie","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"The divine storm given form. Nothing standing before her stays standing.",
        "stat_bonus":{"STR":6,"AGI":4},
        "skills":[
            {"tier":5,"unlock":100,"name":"Celestial Wrath",
             "passive":"+25% crit damage. Crits apply lingering lightning (+10 dmg/min for 3 min). On kill: lightning arcs to all recent attackers.",
             "active":"Valhalla's Thunder","type":"godlike_lightning",
             "desc":"STR x8 lightning strike. On kill: gain +50 temp HP, and deal STR x2 AOE lightning to all recent attackers.",
             "passive_key":"celestial_wrath"},
        ]
    },
    # ── PHANTOM DANCER ───────────────────────────────────────────────────────
    "phantom_dancer": {
        "name":"Phantom Dancer","primary_stat":"AGI","line":"phantom_dancer",
        "weapon_types":["dagger","throwing_star"],
        "armor_type":"thief_armor",
        "desc":"She moves like smoke — impossible to hit, impossible to predict, impossible to stop.",
        "stat_bonus":{"AGI":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Waltz",
             "passive":"After dodging, next attack deals +60% bonus damage. All crits restore 5 HP.",
             "active":"Dancer's Step","type":"dodge_buff",
             "desc":"Gain +35% dodge for 45 seconds. If any attack misses during this window, immediately counter for AGI x1.5 damage.",
             "passive_key":"waltz"},
            {"tier":1,"unlock":5,"name":"Rhythm",
             "passive":"Each consecutive hit on same target adds +8% damage (up to 4 stacks, resets on miss).",
             "active":"Spinning Blade","type":"multihit",
             "desc":"Two rapid strikes: AGI x0.8 each, independent crits.",
             "passive_key":"rhythm","hits":2,"mults":[0.8, 0.8]},
        ]
    },
    # Path A — Offense/Combo
    "battle_dancer": {
        "name":"Battle Dancer","primary_stat":"AGI","line":"phantom_dancer","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Every fight is a performance. Every kill is a bow.",
        "stat_bonus":{"AGI":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Flourish",
             "passive":"On crit, immediately hit again for 40% damage.",
             "active":"Pirouette","type":"multihit_crit",
             "desc":"Spin attack: 3 hits at AGI x0.7 each. Third hit is guaranteed crit.",
             "passive_key":"flourish","hits":3,"mults":[0.7, 0.7, 0.7]},
            {"tier":2,"unlock":10,"name":"Adrenaline",
             "passive":"First attack each fight is always a guaranteed crit.",
             "active":"Rush","type":"guaranteed_hit",
             "desc":"Guaranteed hit, ignores dodge: AGI x1.8 damage.",
             "passive_key":"adrenaline","mult":1.8},
        ]
    },
    "blade_spinner": {
        "name":"Blade Spinner","primary_stat":"AGI","line":"phantom_dancer","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"She spins blades where others expect steps. The rhythm is death.",
        "stat_bonus":{"AGI":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Whirlwind",
             "passive":"Every 3rd attack hits all players who attacked you in the last 30 minutes (30% damage each).",
             "active":"Blade Storm","type":"aoe_bleed_multihit",
             "desc":"4 rapid slashes at AGI x0.6 each. Each hit applies bleed (10 dmg/30s for 5 min, stacks to 4).",
             "passive_key":"whirlwind","hits":4,"mult":0.6},
        ]
    },
    "crimson_whirl": {
        "name":"Crimson Whirl","primary_stat":"AGI","line":"phantom_dancer","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Red as the last dance. Her footprints are made of crimson.",
        "stat_bonus":{"AGI":5,"STR":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Death Whirl",
             "passive":"While below 40% HP, all attacks have +30% crit chance. Low-HP crit kills restore 20% HP.",
             "active":"Thousand Cuts","type":"execute_multihit",
             "desc":"8 hits at AGI x0.5 each. Final hit: if target below 30% HP, deal 3x damage.",
             "passive_key":"death_whirl","hits":8,"mult":0.5},
        ]
    },
    "danse_macabre": {
        "name":"Danse Macabre","primary_stat":"AGI","line":"phantom_dancer","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"The final performance. Every kill is an encore.",
        "stat_bonus":{"AGI":6,"STR":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Final Performance",
             "passive":"On kill: reset all cooldowns and gain +50% crit chance for 60 seconds. Stacks to 3 kills.",
             "active":"Macabre Finale","type":"execute_nuke",
             "desc":"AGI x10 damage: 60% primary + 40% secondary strike. On kill: AOE AGI x3 to all recent attackers. Cannot be blocked or dodged.",
             "passive_key":"final_performance"},
        ]
    },
    # Path B — Evasion/Ghost
    "veil_dancer": {
        "name":"Veil Dancer","primary_stat":"AGI","line":"phantom_dancer","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"She dances behind the veil between worlds. Blades pass through her like mist.",
        "stat_bonus":{"AGI":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Ethereal Step",
             "passive":"20% dodge chance. On each successful dodge: regain 8 HP.",
             "active":"Phase Step","type":"vanish_dmg",
             "desc":"Phase out for 30 seconds (unhittable), then reappear dealing AGI x3 burst.",
             "passive_key":"ethereal_step"},
            {"tier":2,"unlock":10,"name":"Mirror Image",
             "passive":"8% chance an attack hits a phantom duplicate instead, dealing zero damage.",
             "active":"Mirage","type":"dodge_buff",
             "desc":"Create decoys: +30% dodge and 12% phantom-block chance for 60 seconds.",
             "passive_key":"mirror_image"},
        ]
    },
    "mistwalker": {
        "name":"Mistwalker","primary_stat":"AGI","line":"phantom_dancer","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"She walks where mist walks. She is the silence between strikes.",
        "stat_bonus":{"AGI":4,"INT":1},
        "skills":[
            {"tier":3,"unlock":30,"name":"Fog of War",
             "passive":"Enemies who miss you have their ATK reduced by 12% for 1 minute.",
             "active":"Mist Form","type":"vanish",
             "desc":"Become untargetable for 45 seconds. During Mist Form: regen 5 HP per 10 seconds.",
             "passive_key":"fog_of_war"},
        ]
    },
    "phantom_prima": {
        "name":"Phantom Prima","primary_stat":"AGI","line":"phantom_dancer","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Prima donna of the phantom stage. Her art cannot be touched.",
        "stat_bonus":{"AGI":5,"INT":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Phantom's Grace",
             "passive":"Dodge chance cannot be reduced below 20% by any effect. Every dodge now also reduces attacker ATK by 5 for 30 seconds.",
             "active":"Spirit Step","type":"pierce_dodge",
             "desc":"Instantly negate any hit (even if stunned) and counter for AGI x4 damage.",
             "passive_key":"phantoms_grace"},
        ]
    },
    "ethereal_sovereign": {
        "name":"Ethereal Sovereign","primary_stat":"AGI","line":"phantom_dancer","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Beyond sight, beyond reach, beyond defeat.",
        "stat_bonus":{"AGI":6,"INT":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Sovereign's Veil",
             "passive":"30% dodge chance. Every dodge heals 15 HP and grants 3-second immunity. You cannot be stunned or rooted.",
             "active":"Ethereal Storm","type":"phantom_aoe",
             "desc":"Phase through all damage for 30 seconds while auto-striking all recent attackers for AGI x2. End: release AGI x6 nova on all targets.",
             "passive_key":"sovereign_veil"},
        ]
    },
}

# Class progression paths
CLASS_PATHS = {
    "warrior": {"A": ["page","squire","knight","paladin"],
                "B": ["fighter","crusader","hero","warlord"]},
    "mage":    {"A": ["arcanist","sorcerer","archmage","sage"],
                "B": ["hexblade","warlock","lich","void_mage"]},
    "thief":   {"A": ["rogue","shadow","phantom","wraith"],
                "B": ["cutthroat","assassin","blade_master","specialist"]},
    "archer":  {"A": ["scout","ranger","warden","strider"],
                "B": ["bounty_hunter","sharpshooter","sniper","deadeye"]},
    "priest":  {"A": ["cleric","bishop","high_priest","saint"],
                "B": ["acolyte","exorcist","inquisitor","zealot"]},
    "botanist":       {"A": ["florist","bloom_witch","petal_sage","wildflower_empress"],
                       "B": ["thornweaver","briar_knight","verdant_warden","natures_chosen"]},
    "enchantress":    {"A": ["hex_dancer","cursebinder","vexmistress","dread_empress"],
                       "B": ["charmsong","songweaver","lorewarden","grand_muse"]},
    "valkyrie":       {"A": ["shieldmaiden","runeguard","vanguard","iron_valkyrie"],
                       "B": ["stormbringer","thunder_sister","storm_sovereign","divine_tempest"]},
    "phantom_dancer": {"A": ["battle_dancer","blade_spinner","crimson_whirl","danse_macabre"],
                       "B": ["veil_dancer","mistwalker","phantom_prima","ethereal_sovereign"]},
}
BASE_CLASSES = ["warrior","mage","thief","archer","priest",
                "botanist","enchantress","valkyrie","phantom_dancer"]

# Maps line key → display label showing class name + archetype for players
LINE_ARCHETYPE = {
    "warrior":        "Warrior",
    "mage":           "Mage",
    "thief":          "Thief",
    "archer":         "Archer",
    "priest":         "Priest",
    "botanist":       "Botanist",
    "enchantress":    "Enchantress",
    "valkyrie":       "Valkyrie",
    "phantom_dancer": "Phantom Dancer",
}

# Priest classes that can revive for free
HEALER_CLASSES = {"priest","cleric","bishop","high_priest","saint"}

# ── TITLES ────────────────────────────────────────────────────────────────────
TITLES = {
    "Adventurer":    {"type":"level","threshold":1},
    "On the Come Up":     {"type":"level","threshold":3},
    "Seasoned Stroke":         {"type":"level","threshold":7},
    "Pocket King":     {"type":"level","threshold":10},
    "Table Legend":          {"type":"level","threshold":15},
    "Never Scratches":    {"type":"level","threshold":20},
    "Gone Pro":    {"type":"prestige","threshold":1},
    "Never Off the Table":  {"type":"wins","threshold":10},
    "The Undefeated":  {"type":"wins","threshold":25},
    "The Closer": {"type":"wins","threshold":5},
    "Ghost at the Table":          {"type":"dodges","threshold":5},
    "Road Player":    {"type":"quests","threshold":20},
    "Dungeon Crawler": {"type":"quests","threshold":10},
    "Treasure Hunter":     {"type":"quests","threshold":5},
    "The Healer":      {"type":"heals","threshold":5},
    "Table Guardian":        {"type":"heals","threshold":10},
    "1-Ball Slayer": {"type":"special","threshold":0},
    "3-Ball Slayer":{"type":"special","threshold":0},
    "5-Ball Slayer":{"type":"special","threshold":0},
    "7-Ball Slayer":{"type":"special","threshold":0},
    "8-Ball Champion":  {"type":"special","threshold":0},
    "Blackball Slayer":     {"type":"special","threshold":0},
    "Railfinder":      {"type":"special","threshold":0},
    "The Angle Reader":        {"type":"special","threshold":0},
    "The Called Shot":  {"type":"special","threshold":0},
    "Guild Founder":   {"type":"special","threshold":0},
    "Break Leader":     {"type":"special","threshold":0},
    "Tip Maker":       {"type":"crafts","threshold":5},
    "The Blacksmith":    {"type":"crafts","threshold":10},
    "Master Craftsman":         {"type":"crafts","threshold":20},
    "Century Break":         {"type":"level","threshold":100},
    # Reinforce / Ascend
    "The Forger":            {"type":"reinforce","threshold":1},
    "Diamond Grinder":       {"type":"reinforce","threshold":50},
    "The Ascendant":         {"type":"ascensions","threshold":1},
    "Three Star General":    {"type":"ascensions","threshold":3},
    # Daily Objectives
    "Objective Rookie":      {"type":"objectives_done","threshold":5},
    "Objective Master":      {"type":"objectives_done","threshold":25},
    # Item Sets
    "Full Set":              {"type":"special","threshold":0},
    # Marriage
    "Beloved":               {"type":"special","threshold":0},
}

TITLE_BONUSES = {
    "Adventurer":           {"all_stats": 1},
    "On the Come Up":       {"all_stats": 2},
    "Seasoned Stroke":      {"STR": 3, "AGI": 3},
    "Pocket King":          {"STR": 5, "DEF": 5},
    "Table Legend":         {"all_stats": 5},
    "Never Scratches":      {"AGI": 8, "LUK": 5},
    "Gone Pro":             {"all_stats": 8},
    "Never Off the Table":  {"STR": 6, "WIS": 6},
    "The Undefeated":       {"STR": 8, "DEF": 6},
    "The Closer":           {"STR": 5, "LUK": 8},
    "Ghost at the Table":   {"AGI": 10, "LUK": 6},
    "Road Player":          {"all_stats": 6},
    "Dungeon Crawler":      {"STR": 4, "DEX": 4, "LUK": 4},
    "Treasure Hunter":      {"LUK": 12},
    "The Healer":           {"WIS": 8},
    "Table Guardian":       {"DEF": 10, "WIS": 5},
    "1-Ball Slayer":        {"STR": 5},
    "3-Ball Slayer":        {"STR": 8},
    "5-Ball Slayer":        {"STR": 10, "AGI": 5},
    "7-Ball Slayer":        {"STR": 12, "DEF": 8},
    "8-Ball Champion":      {"all_stats": 10},
    "Blackball Slayer":     {"all_stats": 15, "LUK": 10},
    "Railfinder":           {"DEX": 12, "AGI": 8},
    "The Angle Reader":     {"INT": 12, "DEX": 8},
    "The Called Shot":      {"all_stats": 12},
    "Guild Founder":        {"WIS": 6, "all_stats": 3},
    "Break Leader":         {"STR": 8, "WIS": 6},
    "Tip Maker":            {"DEX": 6, "LUK": 6},
    "The Blacksmith":       {"STR": 6, "DEX": 8},
    "Master Craftsman":     {"all_stats": 8},
    "Century Break":        {"all_stats": 20, "LUK": 15},
    "The Forger":           {"STR": 5, "DEX": 5},
    "Diamond Grinder":      {"STR": 10, "DEX": 10},
    "The Ascendant":        {"all_stats": 8},
    "Three Star General":   {"all_stats": 15},
    "Objective Rookie":     {"LUK": 6, "all_stats": 3},
    "Objective Master":     {"all_stats": 10, "LUK": 8},
    "Full Set":             {"all_stats": 5},
    "Beloved":              {"WIS": 5, "LUK": 5},
}

# ── ITEM SETS ─────────────────────────────────────────────────────────────────
ITEM_SETS = {
    # ── Warrior sets ──────────────────────────────────────────────────────────
    "Knight's Vow": {
        "pieces": ["Heaven's Cleave", "Dragonscale Plate"],
        "bonus": {"STR": 14, "DEF": 10},
        "desc": "Warrior Knight 2pc — Legendary honor",
    },
    "The Warlord's Throne": {
        "pieces": ["Ruinblade", "Dragonscale Plate"],
        "bonus": {"STR": 18, "DEF": 8},
        "desc": "Warrior Fighter 2pc — Legendary fury",
    },
    "The Knight's Eternal Court": {
        "pieces": ["Heaven's Cleave", "Dragonscale Plate", "Celestial Bulwark"],
        "bonus": {"STR": 25, "DEF": 20, "hp": 60},
        "desc": "Warrior Knight 3pc — Full legendary defense",
    },
    "Arcane Sovereignty": {
        "pieces": ["The Mind's Eye", "Archmage's Sanctum Robe"],
        "bonus": {"INT": 16, "WIS": 10},
        "desc": "Mage Arcane 2pc — Legendary mastery",
    },
    "Void Ascension": {
        "pieces": ["Staff of Unending Night", "Archmage's Sanctum Robe"],
        "bonus": {"INT": 14, "WIS": 12},
        "desc": "Mage Dark Arts 2pc — Legendary dominion",
    },
    "The Phantom Covenant": {
        "pieces": ["Death's Whisper", "The Shadow Wrap"],
        "bonus": {"AGI": 16, "LUK": 12},
        "desc": "Thief Shadow 2pc — Legendary evasion",
    },
    "The Assassin's Pact": {
        "pieces": ["The Reaper's Wheel", "The Death Grasp", "The Shadow Wrap"],
        "bonus": {"AGI": 20, "STR": 12, "LUK": 10},
        "desc": "Thief Assassin 3pc — Full legendary lethality",
    },
    "Ranger's Oath": {
        "pieces": ["The Ghostwood Longbow", "The Shadowmark Leather"],
        "bonus": {"DEX": 16, "AGI": 10},
        "desc": "Archer Ranger 2pc — Legendary precision",
    },
    "Dead Man's Aim": {
        "pieces": ["The Dead Reckoning", "The Shadowmark Leather"],
        "bonus": {"DEX": 14, "AGI": 12},
        "desc": "Archer Bounty Hunter 2pc — Legendary aim",
    },
    "Saint's Radiance": {
        "pieces": ["The Eternal Prayer", "The High Saint's Vestment"],
        "bonus": {"WIS": 16, "INT": 10, "hp": 35},
        "desc": "Priest Cleric 2pc — Legendary blessing",
    },
    "The Eternal Judgment": {
        "pieces": ["The Final Judgment", "The High Saint's Vestment"],
        "bonus": {"WIS": 14, "INT": 14},
        "desc": "Priest Inquisitor 2pc — Legendary wrath",
    },
}

# ── DAILY QUEST POOL ──────────────────────────────────────────────────────────
DAILY_QUEST_POOL = [
    {"id":"arena_win",    "desc":"Win {n} arena match(es)",          "targets":[1,2,3],  "exp":[400,700,1000],"gold":[80,140,200]},
    {"id":"dungeon_run",  "desc":"Complete {n} dungeon run(s)",       "targets":[1,2,3],  "exp":[600,1000,1500],"gold":[100,180,250]},
    {"id":"pvp_win",      "desc":"Win {n} PvP fight(s)",              "targets":[1,2,3],  "exp":[300,600,900],"gold":[60,120,180]},
    {"id":"skill_use",    "desc":"Use your skill {n} time(s)",        "targets":[3,5,8],  "exp":[200,400,600],"gold":[40,80,120]},
    {"id":"quest_run",    "desc":"Complete /quest {n} time(s)",       "targets":[2,4,6],  "exp":[300,500,800],"gold":[60,100,160]},
    {"id":"boss_attempt", "desc":"Participate in {n} boss fight(s)",  "targets":[1,2,3],  "exp":[500,800,1200],"gold":[100,160,220]},
    {"id":"pool_run",     "desc":"Complete {n} adventure(s)",          "targets":[3,6,10], "exp":[200,400,700],"gold":[40,80,140]},
    {"id":"heal_ally",    "desc":"Heal {n} ally(s)",                  "targets":[1,2,4],  "exp":[300,600,900],"gold":[60,120,180]},
    {"id":"solo_win",     "desc":"Win {n} solo raid(s)",              "targets":[1,2,3],  "exp":[500,900,1400],"gold":[100,180,260]},
    {"id":"raid_hit",     "desc":"Land {n} raid hit(s)",              "targets":[5,10,15],"exp":[300,600,900],"gold":[60,120,180]},
]

# ── GEAR SYSTEM ───────────────────────────────────────────────────────────────
WEAPONS = {
    # ── SWORD 1H (warrior base + knight path A) ───────────────────────────────
    "Rusty Shortsword":          {"class":"warrior","type":"sword_1h","atk":4, "rarity":"common",   "line":"warrior"},
    "Chipped Longsword":         {"class":"warrior","type":"sword_1h","atk":4, "rarity":"common",   "line":"warrior"},
    "Iron Broadsword":           {"class":"warrior","type":"sword_1h","atk":9, "rarity":"uncommon", "line":"warrior"},
    "Soldier's Blade":           {"class":"warrior","type":"sword_1h","atk":10,"rarity":"uncommon", "line":"warrior"},
    "Steel Knight Sword":        {"class":"warrior","type":"sword_1h","atk":16,"rarity":"rare",     "line":"warrior"},
    "Champion's Longsword":      {"class":"warrior","type":"sword_1h","atk":17,"rarity":"rare",     "line":"warrior"},
    "Paladin's Edge":            {"class":"warrior","type":"sword_1h","atk":26,"rarity":"epic",     "line":"warrior"},
    "Blessed Crusader Blade":    {"class":"warrior","type":"sword_1h","atk":28,"rarity":"epic",     "line":"warrior"},
    "Heaven's Cleave":           {"class":"warrior","type":"sword_1h","atk":42,"rarity":"legendary","line":"warrior"},
    "Oath of the First Knight":  {"class":"warrior","type":"sword_1h","atk":62,"rarity":"mythic",   "line":"warrior"},
    # ── SWORD 2H (fighter path B only) ───────────────────────────────────────
    "Crude Greatsword":          {"class":"warrior","type":"sword_2h","atk":5, "rarity":"common",   "line":"warrior"},
    "Battered Claymore":         {"class":"warrior","type":"sword_2h","atk":5, "rarity":"common",   "line":"warrior"},
    "Iron Greatsword":           {"class":"warrior","type":"sword_2h","atk":11,"rarity":"uncommon", "line":"warrior"},
    "War Claymore":              {"class":"warrior","type":"sword_2h","atk":11,"rarity":"uncommon", "line":"warrior"},
    "Battle Reaver":             {"class":"warrior","type":"sword_2h","atk":18,"rarity":"rare",     "line":"warrior"},
    "Warbringer's Blade":        {"class":"warrior","type":"sword_2h","atk":18,"rarity":"rare",     "line":"warrior"},
    "Warlord's Edge":            {"class":"warrior","type":"sword_2h","atk":29,"rarity":"epic",     "line":"warrior"},
    "Titan Greatsword":          {"class":"warrior","type":"sword_2h","atk":29,"rarity":"epic",     "line":"warrior"},
    "Ruinblade":                 {"class":"warrior","type":"sword_2h","atk":46,"rarity":"legendary","line":"warrior"},
    "The World Splitter":        {"class":"warrior","type":"sword_2h","atk":66,"rarity":"mythic",   "line":"warrior"},
    # ── WAND (mage base + arcane path A) ─────────────────────────────────────
    "Gnarled Twig Wand":         {"class":"mage","type":"wand","atk":3, "rarity":"common",   "line":"mage"},
    "Smooth Ash Wand":           {"class":"mage","type":"wand","atk":3, "rarity":"common",   "line":"mage"},
    "Crystal Core Wand":         {"class":"mage","type":"wand","atk":8, "rarity":"uncommon", "line":"mage"},
    "Ember Wand":                {"class":"mage","type":"wand","atk":8, "rarity":"uncommon", "line":"mage"},
    "Arcanist's Focus":          {"class":"mage","type":"wand","atk":15,"rarity":"rare",     "line":"mage"},
    "Sapphire Rod":              {"class":"mage","type":"wand","atk":15,"rarity":"rare",     "line":"mage"},
    "Archmage's Scepter":        {"class":"mage","type":"wand","atk":25,"rarity":"epic",     "line":"mage"},
    "Thundercrack Wand":         {"class":"mage","type":"wand","atk":25,"rarity":"epic",     "line":"mage"},
    "The Mind's Eye":            {"class":"mage","type":"wand","atk":40,"rarity":"legendary","line":"mage"},
    "Eternal Arcanum":           {"class":"mage","type":"wand","atk":60,"rarity":"mythic",   "line":"mage"},
    # ── STAFF (dark arts path B) ──────────────────────────────────────────────
    "Gnarled Root Staff":        {"class":"mage","type":"staff","atk":4, "rarity":"common",   "line":"mage"},
    "Carved Bone Staff":         {"class":"mage","type":"staff","atk":4, "rarity":"common",   "line":"mage"},
    "Shadow Oak Staff":          {"class":"mage","type":"staff","atk":9, "rarity":"uncommon", "line":"mage"},
    "Hex-Carved Staff":          {"class":"mage","type":"staff","atk":9, "rarity":"uncommon", "line":"mage"},
    "Warlock's Dread Staff":     {"class":"mage","type":"staff","atk":16,"rarity":"rare",     "line":"mage"},
    "Lich's Conduit":            {"class":"mage","type":"staff","atk":16,"rarity":"rare",     "line":"mage"},
    "Void Channel Staff":        {"class":"mage","type":"staff","atk":27,"rarity":"epic",     "line":"mage"},
    "Soul Siphon Staff":         {"class":"mage","type":"staff","atk":27,"rarity":"epic",     "line":"mage"},
    "Staff of Unending Night":   {"class":"mage","type":"staff","atk":43,"rarity":"legendary","line":"mage"},
    "The Void Throne":           {"class":"mage","type":"staff","atk":63,"rarity":"mythic",   "line":"mage"},
    # ── DAGGER (thief base + shadow path A) ──────────────────────────────────
    "Rusty Shiv":                {"class":"thief","type":"dagger","atk":4, "rarity":"common",   "line":"thief"},
    "Cracked Flint Dagger":      {"class":"thief","type":"dagger","atk":4, "rarity":"common",   "line":"thief"},
    "Iron Stiletto":             {"class":"thief","type":"dagger","atk":10,"rarity":"uncommon", "line":"thief"},
    "Shadow Dirk":               {"class":"thief","type":"dagger","atk":10,"rarity":"uncommon", "line":"thief"},
    "Venomfang Blade":           {"class":"thief","type":"dagger","atk":17,"rarity":"rare",     "line":"thief"},
    "Shadowstep Dagger":         {"class":"thief","type":"dagger","atk":17,"rarity":"rare",     "line":"thief"},
    "Phantom Edge":              {"class":"thief","type":"dagger","atk":27,"rarity":"epic",     "line":"thief"},
    "Soul-Drinker Blade":        {"class":"thief","type":"dagger","atk":27,"rarity":"epic",     "line":"thief"},
    "Death's Whisper":           {"class":"thief","type":"dagger","atk":44,"rarity":"legendary","line":"thief"},
    "The Final Cut":             {"class":"thief","type":"dagger","atk":62,"rarity":"mythic",   "line":"thief"},
    # ── THROWING STAR (assassin path B weapon slot) ───────────────────────────
    "Iron Throwing Star":        {"class":"thief","type":"throwing_star","atk":4, "rarity":"common",   "line":"thief"},
    "Crude Shuriken":            {"class":"thief","type":"throwing_star","atk":4, "rarity":"common",   "line":"thief"},
    "Balanced Steel Star":       {"class":"thief","type":"throwing_star","atk":9, "rarity":"uncommon", "line":"thief"},
    "Razor Wind Star":           {"class":"thief","type":"throwing_star","atk":9, "rarity":"uncommon", "line":"thief"},
    "Bloodsteel Shuriken":       {"class":"thief","type":"throwing_star","atk":16,"rarity":"rare",     "line":"thief"},
    "Executioner's Star":        {"class":"thief","type":"throwing_star","atk":16,"rarity":"rare",     "line":"thief"},
    "Shadow Death Star":         {"class":"thief","type":"throwing_star","atk":26,"rarity":"epic",     "line":"thief"},
    "Void-Edged Shuriken":       {"class":"thief","type":"throwing_star","atk":26,"rarity":"epic",     "line":"thief"},
    "The Reaper's Wheel":        {"class":"thief","type":"throwing_star","atk":42,"rarity":"legendary","line":"thief"},
    "Black Orbit":               {"class":"thief","type":"throwing_star","atk":61,"rarity":"mythic",   "line":"thief"},
    # ── BOW (archer base + ranger path A) ─────────────────────────────────────
    "Frayed Hunting Bow":        {"class":"archer","type":"bow","atk":4, "rarity":"common",   "line":"archer"},
    "Rough-Cut Yew Bow":         {"class":"archer","type":"bow","atk":4, "rarity":"common",   "line":"archer"},
    "Recurve Hunter's Bow":      {"class":"archer","type":"bow","atk":9, "rarity":"uncommon", "line":"archer"},
    "Forest Longbow":            {"class":"archer","type":"bow","atk":9, "rarity":"uncommon", "line":"archer"},
    "Ranger's Marked Bow":       {"class":"archer","type":"bow","atk":16,"rarity":"rare",     "line":"archer"},
    "Stormwood Bow":             {"class":"archer","type":"bow","atk":16,"rarity":"rare",     "line":"archer"},
    "Warden's Gale Bow":         {"class":"archer","type":"bow","atk":26,"rarity":"epic",     "line":"archer"},
    "Swiftshot Greatbow":        {"class":"archer","type":"bow","atk":26,"rarity":"epic",     "line":"archer"},
    "The Ghostwood Longbow":     {"class":"archer","type":"bow","atk":42,"rarity":"legendary","line":"archer"},
    "The Infinity Quiver":       {"class":"archer","type":"bow","atk":60,"rarity":"mythic",   "line":"archer"},
    # ── CROSSBOW (bounty hunter path B) ───────────────────────────────────────
    "Crude Wooden Crossbow":     {"class":"archer","type":"crossbow","atk":4, "rarity":"common",   "line":"archer"},
    "Iron Crossbow":             {"class":"archer","type":"crossbow","atk":4, "rarity":"common",   "line":"archer"},
    "Repeating Crossbow":        {"class":"archer","type":"crossbow","atk":9, "rarity":"uncommon", "line":"archer"},
    "Hunter's Crossbow":         {"class":"archer","type":"crossbow","atk":9, "rarity":"uncommon", "line":"archer"},
    "Precision Bolt Crossbow":   {"class":"archer","type":"crossbow","atk":16,"rarity":"rare",     "line":"archer"},
    "Siege Crossbow":            {"class":"archer","type":"crossbow","atk":17,"rarity":"rare",     "line":"archer"},
    "Deadeye's Repeater":        {"class":"archer","type":"crossbow","atk":27,"rarity":"epic",     "line":"archer"},
    "Rapid-Fire Crossbow":       {"class":"archer","type":"crossbow","atk":27,"rarity":"epic",     "line":"archer"},
    "The Dead Reckoning":        {"class":"archer","type":"crossbow","atk":44,"rarity":"legendary","line":"archer"},
    "The Endless Bolt":          {"class":"archer","type":"crossbow","atk":63,"rarity":"mythic",   "line":"archer"},
    # ── ROSARY (priest base + cleric path A) ──────────────────────────────────
    "Wooden Prayer Beads":       {"class":"priest","type":"rosary","atk":3, "rarity":"common",   "line":"priest"},
    "Clay Rosary":               {"class":"priest","type":"rosary","atk":3, "rarity":"common",   "line":"priest"},
    "Silver Prayer Beads":       {"class":"priest","type":"rosary","atk":7, "rarity":"uncommon", "line":"priest"},
    "Blessed Rosary":            {"class":"priest","type":"rosary","atk":7, "rarity":"uncommon", "line":"priest"},
    "Goldweave Rosary":          {"class":"priest","type":"rosary","atk":14,"rarity":"rare",     "line":"priest"},
    "Saint's Chain":             {"class":"priest","type":"rosary","atk":14,"rarity":"rare",     "line":"priest"},
    "Holy Radiance Rosary":      {"class":"priest","type":"rosary","atk":24,"rarity":"epic",     "line":"priest"},
    "Blessed Pearl Chain":       {"class":"priest","type":"rosary","atk":24,"rarity":"epic",     "line":"priest"},
    "The Eternal Prayer":        {"class":"priest","type":"rosary","atk":38,"rarity":"legendary","line":"priest"},
    "The Divine Rosary":         {"class":"priest","type":"rosary","atk":58,"rarity":"mythic",   "line":"priest"},
    # ── CROSS (inquisitor path B) ─────────────────────────────────────────────
    "Rough Iron Cross":          {"class":"priest","type":"cross","atk":4, "rarity":"common",   "line":"priest"},
    "Carved Bone Cross":         {"class":"priest","type":"cross","atk":4, "rarity":"common",   "line":"priest"},
    "Silver-Etched Cross":       {"class":"priest","type":"cross","atk":9, "rarity":"uncommon", "line":"priest"},
    "Steel Inquisitor Cross":    {"class":"priest","type":"cross","atk":9, "rarity":"uncommon", "line":"priest"},
    "Holy Judge's Cross":        {"class":"priest","type":"cross","atk":16,"rarity":"rare",     "line":"priest"},
    "Knight's Inquisitor Cross": {"class":"priest","type":"cross","atk":16,"rarity":"rare",     "line":"priest"},
    "Grand Inquisitor's Cross":  {"class":"priest","type":"cross","atk":26,"rarity":"epic",     "line":"priest"},
    "Verdict Cross":             {"class":"priest","type":"cross","atk":26,"rarity":"epic",     "line":"priest"},
    "The Final Judgment":        {"class":"priest","type":"cross","atk":43,"rarity":"legendary","line":"priest"},
    "The Eternal Verdict":       {"class":"priest","type":"cross","atk":63,"rarity":"mythic",   "line":"priest"},
}

ARMORS = {
    # ── WARRIOR PLATE ─────────────────────────────────────────────────────────
    "Rusty Iron Vest":           {"class":"warrior","def":4, "rarity":"common",   "line":"warrior"},
    "Studded Leather Plate":     {"class":"warrior","def":5, "rarity":"common",   "line":"warrior"},
    "Iron Chain Mail":           {"class":"warrior","def":10,"rarity":"uncommon", "line":"warrior"},
    "Soldier's Plating":         {"class":"warrior","def":11,"rarity":"uncommon", "line":"warrior"},
    "Steel Breastplate":         {"class":"warrior","def":20,"rarity":"rare",     "line":"warrior"},
    "Knight's Plate Armor":      {"class":"warrior","def":21,"rarity":"rare",     "line":"warrior"},
    "Warlord's Battle Plate":    {"class":"warrior","def":33,"rarity":"epic",     "line":"warrior"},
    "Indomitable Plate":         {"class":"warrior","def":34,"rarity":"epic",     "line":"warrior"},
    "Dragonscale Plate":         {"class":"warrior","def":52,"rarity":"legendary","line":"warrior"},
    "The Titan's Aegis Armor":   {"class":"warrior","def":76,"rarity":"mythic",   "line":"warrior"},
    # ── MAGE ROBES ────────────────────────────────────────────────────────────
    "Worn Cloth Robe":           {"class":"mage","def":3, "rarity":"common",   "line":"mage"},
    "Apprentice's Robe":         {"class":"mage","def":3, "rarity":"common",   "line":"mage"},
    "Scholar's Robe":            {"class":"mage","def":8, "rarity":"uncommon", "line":"mage"},
    "Arcane Weave Robe":         {"class":"mage","def":9, "rarity":"uncommon", "line":"mage"},
    "Sorcerer's Mantle":         {"class":"mage","def":18,"rarity":"rare",     "line":"mage"},
    "Arcane Sigil Robe":         {"class":"mage","def":18,"rarity":"rare",     "line":"mage"},
    "Archmage's Vestment":       {"class":"mage","def":30,"rarity":"epic",     "line":"mage"},
    "Void-Touched Robe":         {"class":"mage","def":30,"rarity":"epic",     "line":"mage"},
    "Archmage's Sanctum Robe":   {"class":"mage","def":46,"rarity":"legendary","line":"mage"},
    "The Eternal Weave":         {"class":"mage","def":70,"rarity":"mythic",   "line":"mage"},
    # ── THIEF LEATHERS ────────────────────────────────────────────────────────
    "Torn Leather Vest":         {"class":"thief","def":3, "rarity":"common",   "line":"thief"},
    "Padded Cloth Armor":        {"class":"thief","def":4, "rarity":"common",   "line":"thief"},
    "Shadow Leathers":           {"class":"thief","def":9, "rarity":"uncommon", "line":"thief"},
    "Rogue's Leathers":          {"class":"thief","def":10,"rarity":"uncommon", "line":"thief"},
    "Nightstalker's Vest":       {"class":"thief","def":19,"rarity":"rare",     "line":"thief"},
    "Shadow Mesh":               {"class":"thief","def":19,"rarity":"rare",     "line":"thief"},
    "Phantom Leathers":          {"class":"thief","def":31,"rarity":"epic",     "line":"thief"},
    "Assassin's Harness":        {"class":"thief","def":31,"rarity":"epic",     "line":"thief"},
    "The Shadow Wrap":           {"class":"thief","def":48,"rarity":"legendary","line":"thief"},
    "The Void Walker's Cloak":   {"class":"thief","def":72,"rarity":"mythic",   "line":"thief"},
    # ── ARCHER LEATHERS ───────────────────────────────────────────────────────
    "Padded Hunting Vest":       {"class":"archer","def":4, "rarity":"common",   "line":"archer"},
    "Traveler's Leathers":       {"class":"archer","def":4, "rarity":"common",   "line":"archer"},
    "Scout's Leathers":          {"class":"archer","def":10,"rarity":"uncommon", "line":"archer"},
    "Ranger's Vest":             {"class":"archer","def":10,"rarity":"uncommon", "line":"archer"},
    "Forest Scout Armor":        {"class":"archer","def":20,"rarity":"rare",     "line":"archer"},
    "Warden's Leather Plate":    {"class":"archer","def":20,"rarity":"rare",     "line":"archer"},
    "Strider's Marked Armor":    {"class":"archer","def":32,"rarity":"epic",     "line":"archer"},
    "Deadeye's Plating":         {"class":"archer","def":32,"rarity":"epic",     "line":"archer"},
    "The Shadowmark Leather":    {"class":"archer","def":50,"rarity":"legendary","line":"archer"},
    "The Ghost Walker Vest":     {"class":"archer","def":74,"rarity":"mythic",   "line":"archer"},
    # ── PRIEST VESTMENTS ──────────────────────────────────────────────────────
    "Simple Cloth Vestment":     {"class":"priest","def":3, "rarity":"common",   "line":"priest"},
    "Acolyte's Robe":            {"class":"priest","def":3, "rarity":"common",   "line":"priest"},
    "Blessed Cloth Robe":        {"class":"priest","def":8, "rarity":"uncommon", "line":"priest"},
    "Initiate's Vestment":       {"class":"priest","def":8, "rarity":"uncommon", "line":"priest"},
    "Sanctified Robe":           {"class":"priest","def":17,"rarity":"rare",     "line":"priest"},
    "Inquisitor's Mantle":       {"class":"priest","def":17,"rarity":"rare",     "line":"priest"},
    "High Cleric's Vestment":    {"class":"priest","def":29,"rarity":"epic",     "line":"priest"},
    "Zealot's Holy Robe":        {"class":"priest","def":29,"rarity":"epic",     "line":"priest"},
    "The High Saint's Vestment": {"class":"priest","def":44,"rarity":"legendary","line":"priest"},
    "Heaven's Blessing Robe":    {"class":"priest","def":68,"rarity":"mythic",   "line":"priest"},
}

# Shields: warrior knight path (A) + assassin claws (B, type="claw" uses "atk" not "def")
SHIELDS = {
    # ── WARRIOR SHIELDS (knight path A) ───────────────────────────────────────
    "Wooden Buckler":            {"class":"warrior","path":"A","def":3, "rarity":"common"},
    "Battered Iron Shield":      {"class":"warrior","path":"A","def":3, "rarity":"common"},
    "Soldier's Kite Shield":     {"class":"warrior","path":"A","def":8, "rarity":"uncommon"},
    "Iron Heater Shield":        {"class":"warrior","path":"A","def":9, "rarity":"uncommon"},
    "Knight's Bulwark":          {"class":"warrior","path":"A","def":17,"rarity":"rare"},
    "Steel Tower Shield":        {"class":"warrior","path":"A","def":17,"rarity":"rare"},
    "Holy Pavise":               {"class":"warrior","path":"A","def":28,"rarity":"epic"},
    "Aegis of the Devoted":      {"class":"warrior","path":"A","def":28,"rarity":"epic"},
    "Celestial Bulwark":         {"class":"warrior","path":"A","def":44,"rarity":"legendary"},
    "The Eternal Oath":          {"class":"warrior","path":"A","def":65,"rarity":"mythic"},
    # ── ASSASSIN CLAWS (assassin path B, shield slot, provides atk bonus) ─────
    "Iron Claw Brace":           {"class":"thief","path":"B","type":"claw","atk":3, "rarity":"common"},
    "Spiked Knuckle Claw":       {"class":"thief","path":"B","type":"claw","atk":3, "rarity":"common"},
    "Razor Claw Gauntlet":       {"class":"thief","path":"B","type":"claw","atk":8, "rarity":"uncommon"},
    "Hunting Claws":             {"class":"thief","path":"B","type":"claw","atk":8, "rarity":"uncommon"},
    "Assassin's Talon":          {"class":"thief","path":"B","type":"claw","atk":15,"rarity":"rare"},
    "Shadow Rend Claw":          {"class":"thief","path":"B","type":"claw","atk":15,"rarity":"rare"},
    "Phantom Rend":              {"class":"thief","path":"B","type":"claw","atk":25,"rarity":"epic"},
    "Venomous Fang Claw":        {"class":"thief","path":"B","type":"claw","atk":25,"rarity":"epic"},
    "The Death Grasp":           {"class":"thief","path":"B","type":"claw","atk":40,"rarity":"legendary"},
    "Soul Ripper Claw":          {"class":"thief","path":"B","type":"claw","atk":60,"rarity":"mythic"},
}

ACCESSORIES = {
    # Common
    "Iron Shard Ring":   {"slot":"ring","effect":{"atk":2},"rarity":"common",
                                "desc":"Slightly sharpens your focus."},
    "Worn Leather Band":    {"slot":"ring","effect":{"hp":10},"rarity":"common",
                                "desc":"+10 max HP."},
    "Brass Ring":              {"slot":"ring","effect":{"any_stat":3},"rarity":"common",
                                "desc":"+3 to one stat of your choice on equip."},
    "Scout's Pendant":             {"slot":"amulet","effect":{"hp":5},"rarity":"common",
                                "desc":"+5 max HP."},
    "Traveler's Coin":       {"slot":"amulet","effect":{"all_stats":2},"rarity":"common",
                                "desc":"+2 to all stats."},
    # Uncommon
    "Silk Band":           {"slot":"ring","effect":{"AGI":6},"rarity":"uncommon",
                                "desc":"+6 AGI."},
    "Rune Ring":           {"slot":"ring","effect":{"WIS":6},"rarity":"uncommon",
                                "desc":"+6 WIS."},
    "Obsidian Stud":       {"slot":"ring","effect":{"any_stat":6},"rarity":"uncommon",
                                "desc":"+6 STR or +6 INT (choose on equip)."},
    "Bloodstone Band":     {"slot":"ring","effect":{"hp":8,"STR":3},"rarity":"uncommon",
                                "desc":"+8 HP, +3 STR."},
    "Shadowmark Signet":   {"slot":"ring","effect":{"atk":4,"gold_bonus":0.05},"rarity":"uncommon",
                                "desc":"+4 ATK, +5% gold drops."},
    "Rune Cross Pendant":  {"slot":"amulet","effect":{"WIS":6},"rarity":"uncommon",
                                "desc":"+6 WIS."},
    "Hunter's Fang":     {"slot":"amulet","effect":{"STR":6,"AGI":3},"rarity":"uncommon",
                                "desc":"+6 STR, +3 AGI."},
    "Crystal Bead Necklace":      {"slot":"amulet","effect":{"INT":8},"rarity":"uncommon",
                                "desc":"+8 INT."},
    # Rare
    "Fortune Coin":               {"slot":"ring","effect":{"AGI":12,"crit_bonus":0.08},"rarity":"rare",
                                "desc":"+12 AGI, +8% crit damage."},
    "War Master's Clasp":         {"slot":"ring","effect":{"STR":12,"DEF":8},"rarity":"rare",
                                "desc":"+12 STR, +8 DEF."},
    "Hawk Eye Medallion":         {"slot":"ring","effect":{"INT":12,"WIS":8},"rarity":"rare",
                                "desc":"+12 INT, +8 WIS."},
    "Phantom Loop":               {"slot":"ring","effect":{"AGI":10,"dodge_bonus":0.10},"rarity":"rare",
                                "desc":"+10 AGI, +10% dodge chance."},
    "Warrior's Band":      {"slot":"ring","effect":{"STR":10,"lifesteal_flat":5},"rarity":"rare",
                                "desc":"+10 STR. Kills restore 5 HP."},
    "Mage's Coil":         {"slot":"ring","effect":{"INT":14},"rarity":"rare",
                                "desc":"+14 INT."},
    "Stone Heart":         {"slot":"amulet","effect":{"DEF":15,"hp":20},"rarity":"rare",
                                "desc":"+15 DEF, +20 HP."},
    "Beast Fang Chain":      {"slot":"amulet","effect":{"STR":10,"lifesteal_flat":5},"rarity":"rare",
                                "desc":"+10 STR. +5 HP per hit landed."},
    "Traveler's Compass":         {"slot":"amulet","effect":{"all_stats":10,"explore_bonus":0.10},"rarity":"rare",
                                "desc":"+10 to all stats, +10% explore rewards."},
    "The Storm Torc":      {"slot":"amulet","effect":{"AGI":10,"INT":10},"rarity":"rare",
                                "desc":"+10 AGI, +10 INT."},
    # Epic
    "Twin Strike Ring":       {"slot":"ring","effect":{"atk":20,"DEF":15},"rarity":"epic",
                                "desc":"+20 ATK, +15 DEF."},
    "Eye of the Void":         {"slot":"ring","effect":{"AGI":18,"dodge_bonus":0.12},"rarity":"epic",
                                "desc":"+18 AGI, +12% dodge."},
    "Void Circle":          {"slot":"ring","effect":{"INT":22,"reflect_pct":0.10},"rarity":"epic",
                                "desc":"+22 INT, 10% reflect damage."},
    "War Knuckle":       {"slot":"ring","effect":{"STR":20,"low_hp_dmg_bonus":0.10},"rarity":"epic",
                                "desc":"+20 STR, +10% damage when below 30% HP."},
    "Cleric's Band":          {"slot":"ring","effect":{"WIS":20,"heal_bonus":0.30},"rarity":"epic",
                                "desc":"+20 WIS, heals are 30% more effective."},
    "Runed Heart":     {"slot":"amulet","effect":{"hp":25,"all_stats":15},"rarity":"epic",
                                "desc":"+25 HP, +15 to all stats."},
    "The Shadow Whisper":        {"slot":"amulet","effect":{"AGI":20,"crit_bonus":0.15},"rarity":"epic",
                                "desc":"+20 AGI, +15% crit chance."},
    "Guardian's Talisman":       {"slot":"amulet","effect":{"DEF":25,"block_chance":0.10},"rarity":"epic",
                                "desc":"+25 DEF, 10% chance to block any incoming hit."},
    "The Crossed Blades Pendant":     {"slot":"amulet","effect":{"WIS":20,"revive_heal_bonus":0.20},"rarity":"epic",
                                "desc":"+20 WIS, revive heals 20% more HP."},
    "The Iron and Flame Pendant":     {"slot":"amulet","effect":{"STR":22,"INT":22},"rarity":"epic",
                                "desc":"+22 STR, +22 INT."},
    # Legendary
    "Shard of the Void":           {"slot":"ring","effect":{"atk":35,"DEF":35},"rarity":"legendary",
                                "desc":"+35 ATK, +35 DEF."},
    "Ring of the Endless":        {"slot":"ring","effect":{"all_stats":30,"hp":50},"rarity":"legendary",
                                "desc":"+30 to all stats, +50 HP."},
    "The Warlord's Ring":   {"slot":"ring","effect":{"primary_stat":40},"rarity":"legendary",
                                "desc":"+40 to your primary class stat."},
    "The Eternal Ring":            {"slot":"ring","effect":{"all_stats":25,"dodge_bonus":0.05},"rarity":"legendary",
                                "desc":"+25 all stats, 5% chance to dodge any attack."},
    "The Last Stand Locket":      {"slot":"amulet","effect":{"revive_once":True},"rarity":"legendary",
                                "desc":"Revive once per combat at 20% HP."},
    "The Soul Amulet":      {"slot":"amulet","effect":{"primary_stat":40,"hp":100},"rarity":"legendary",
                                "desc":"+40 to primary class stat, +100 HP."},
    "The Divine Shard":        {"slot":"amulet","effect":{"WIS":35,"priest_aoe":True},"rarity":"legendary",
                                "desc":"+35 WIS, priest skills affect 2 targets at once."},
    "The Void Mark":          {"slot":"amulet","effect":{"INT":35,"spell_double_chance":0.15},"rarity":"legendary",
                                "desc":"+35 INT, 15% chance spells hit twice."},
}

RARITY_EMOJI = {
    "common":"⚪","uncommon":"🟢","rare":"🔵","epic":"🟣","legendary":"🟡","mythic":"🔴","legacy":"🟤"
}

# ── PET SYSTEM ────────────────────────────────────────────────────────────────
ELEMENT_EMOJI = {
    "fire":"🔥","water":"💧","earth":"🌿","wind":"🌪️",
    "shadow":"🌑","holy":"✨","void":"🌀","lightning":"⚡","nature":"🍃",
}
PERSONALITY_EMOJI = {
    "playful":"🎉","fierce":"😤","calm":"😌","mischievous":"😈",
    "loyal":"💛","lazy":"💤","greedy":"🤑","timid":"🫢",
}
PERSONALITY_FEED = {
    "playful":    "bounces with excitement and gobbles it right up!",
    "fierce":     "snatches the food in one bite and gives you a satisfied grunt.",
    "calm":       "eats slowly and deliberately, then nods in quiet appreciation.",
    "mischievous":"knocks it around the floor first, then eats it while eyeing you sideways.",
    "loyal":      "waits patiently until you're ready, then eats with a happy wag.",
    "lazy":       "barely opens one eye, drags itself over, and eats without fully getting up.",
    "greedy":     "inhales the food before you even finish offering it. Already looking for more.",
    "timid":      "approaches cautiously, sniffs it twice, then eats it quietly.",
}
PERSONALITY_TRAIN = {
    "playful":    "leaps into training like it's a game — loves every second of it!",
    "fierce":     "trains with total intensity. Nothing held back.",
    "calm":       "goes through every exercise with steady, focused patience.",
    "mischievous":"goofs off half the time but somehow still gets stronger.",
    "loyal":      "pushes through every drill just to make you proud.",
    "lazy":       "completes the minimum required and immediately lies back down.",
    "greedy":     "will only train if you promise snacks afterward.",
    "timid":      "hesitates at first but gains confidence as it goes.",
}
PERSONALITY_BATTLE = {
    "playful":    "dives in enthusiastically",
    "fierce":     "launches a ferocious strike",
    "calm":       "strikes with precision",
    "mischievous":"attacks from a completely unexpected angle",
    "loyal":      "fights fiercely to protect you",
    "lazy":       "reluctantly joins in",
    "greedy":     "attacks hard — there's a reward in it after all",
    "timid":      "musters its courage and strikes",
}

# Each species: name, element, rarity, base_atk, base_def, personality, emoji, desc, egg
PET_SPECIES = {
    # ── DOGS ─────────────────────────────────────────────────────────────────
    "iron_hound":       {"name":"Iron Hound",       "element":"earth",    "rarity":"uncommon","base_atk":6, "base_def":4, "personality":"loyal",      "emoji":"🐕","desc":"A rugged mutt with iron-hard hide. Stubborn and reliable.","def_ability":"intercept"},
    "thunder_mastiff":  {"name":"Thunder Mastiff",  "element":"lightning","rarity":"rare",    "base_atk":10,"base_def":5, "personality":"fierce",     "emoji":"🐕","desc":"A massive war-bred mastiff cracking with static charge.","def_ability":"counter"},
    "shadow_pup":       {"name":"Shadow Pup",       "element":"shadow",   "rarity":"uncommon","base_atk":5, "base_def":3, "personality":"mischievous","emoji":"🐕","desc":"A tiny hound that phases in and out of darkness. Trouble magnet.","def_ability":"stun"},
    "frost_husky":      {"name":"Frost Husky",      "element":"water",    "rarity":"rare",    "base_atk":8, "base_def":6, "personality":"playful",    "emoji":"🐕","desc":"A snow-white husky with ice-blue eyes. Loves cold and chaos equally.","def_ability":"shield"},
    "emberpaw":         {"name":"Emberpaw",          "element":"fire",     "rarity":"epic",    "base_atk":14,"base_def":7, "personality":"fierce",     "emoji":"🐕","desc":"A hound wreathed in embers. Leaves scorched pawprints everywhere it walks.","def_ability":"counter"},
    "celestial_shepherd":{"name":"Celestial Shepherd","element":"holy",   "rarity":"legendary","base_atk":20,"base_def":12,"personality":"loyal",     "emoji":"🐕","desc":"Blessed guardian. It has watched over the same bloodline for centuries.","def_ability":"intercept"},
    # ── CATS ─────────────────────────────────────────────────────────────────
    "soot_cat":         {"name":"Soot Cat",         "element":"shadow",   "rarity":"common",  "base_atk":4, "base_def":2, "personality":"mischievous","emoji":"🐈","desc":"Always covered in ash. Knocks things off tables on purpose.","def_ability":"shield"},
    "ember_tabby":      {"name":"Ember Tabby",      "element":"fire",     "rarity":"uncommon","base_atk":6, "base_def":3, "personality":"playful",    "emoji":"🐈","desc":"An orange tabby with a perpetually warm belly and a flair for drama.","def_ability":"stun"},
    "moonwhisker":      {"name":"Moonwhisker",       "element":"void",     "rarity":"rare",    "base_atk":9, "base_def":5, "personality":"calm",       "emoji":"🐈","desc":"Silver-furred and ancient-eyed. It always knows where the danger is.","def_ability":"shield"},
    "storm_lynx":       {"name":"Storm Lynx",        "element":"lightning","rarity":"rare",    "base_atk":11,"base_def":4, "personality":"fierce",     "emoji":"🐈","desc":"A wild lynx that crackles with electricity. Doesn't do cuddling.","def_ability":"stun"},
    "crystal_manx":     {"name":"Crystal Manx",      "element":"earth",    "rarity":"epic",    "base_atk":13,"base_def":9, "personality":"calm",       "emoji":"🐈","desc":"Its fur has crystallized into translucent armor. Unbothered by everything.","def_ability":"intercept"},
    "spectre_panther":  {"name":"Spectre Panther",   "element":"shadow",   "rarity":"legendary","base_atk":22,"base_def":10,"personality":"fierce",    "emoji":"🐈","desc":"A panther that walks between worlds. You only see it when it wants you to.","def_ability":"counter"},
    # ── DRAGONS ──────────────────────────────────────────────────────────────
    "cave_drake":       {"name":"Cave Drake",        "element":"earth",    "rarity":"uncommon","base_atk":8, "base_def":6, "personality":"lazy",       "emoji":"🐉","desc":"A squat cave-dwelling drake. Prefers sleeping on gold to doing anything.","def_ability":"shield"},
    "flame_whelp":      {"name":"Flame Whelp",       "element":"fire",     "rarity":"rare",    "base_atk":11,"base_def":5, "personality":"playful",    "emoji":"🐉","desc":"A baby fire dragon. Adorable. Also highly flammable to everything nearby.","def_ability":"counter"},
    "frost_wyrm":       {"name":"Frost Wyrm",         "element":"water",    "rarity":"rare",    "base_atk":10,"base_def":7, "personality":"calm",       "emoji":"🐉","desc":"A serpentine ice dragon. Glacially patient. Glacially powerful.","def_ability":"intercept"},
    "storm_drake":      {"name":"Storm Drake",        "element":"lightning","rarity":"epic",    "base_atk":16,"base_def":8, "personality":"fierce",     "emoji":"🐉","desc":"A drake born from a lightning storm. Every battle is a thunderstorm.","def_ability":"counter"},
    "void_drake":       {"name":"Void Drake",         "element":"void",     "rarity":"epic",    "base_atk":15,"base_def":9, "personality":"mischievous","emoji":"🐉","desc":"A dragon that exists partially in another dimension. Bites from angles that shouldn't exist.","def_ability":"stun"},
    "ancient_dragon":   {"name":"Ancient Dragon",     "element":"fire",     "rarity":"legendary","base_atk":24,"base_def":14,"personality":"loyal",     "emoji":"🐉","desc":"A dragon old enough to remember the first age. Chooses its partners wisely.","def_ability":"counter"},
    "prismatic_dragon": {"name":"Prismatic Dragon",   "element":"holy",     "rarity":"mythic",  "base_atk":35,"base_def":20,"personality":"timid",     "emoji":"🐉","desc":"A dragon of pure light. Its colors shift with every heartbeat. Extraordinarily rare.","def_ability":"lifesteal"},
    # ── SNAKES ───────────────────────────────────────────────────────────────
    "viridian_cobra":   {"name":"Viridian Cobra",    "element":"nature",   "rarity":"common",  "base_atk":5, "base_def":2, "personality":"timid",     "emoji":"🐍","desc":"A bright green cobra. Shy until provoked — then very much not shy.","def_ability":"poison"},
    "crimson_viper":    {"name":"Crimson Viper",     "element":"fire",     "rarity":"uncommon","base_atk":7, "base_def":3, "personality":"fierce",     "emoji":"🐍","desc":"A blood-red viper with venom that burns like magma. Aggressive by nature.","def_ability":"poison"},
    "shadow_boa":       {"name":"Shadow Boa",         "element":"shadow",   "rarity":"rare",    "base_atk":9, "base_def":6, "personality":"calm",       "emoji":"🐍","desc":"A massive boa that melts into darkness. Wraps enemies in crushing silence.","def_ability":"intercept"},
    "frost_asp":        {"name":"Frost Asp",          "element":"water",    "rarity":"rare",    "base_atk":10,"base_def":5, "personality":"calm",       "emoji":"🐍","desc":"A pale blue asp whose bite freezes the wound instantly. Eerily quiet.","def_ability":"stun"},
    "ghost_mamba":      {"name":"Ghost Mamba",        "element":"shadow",   "rarity":"epic",    "base_atk":15,"base_def":7, "personality":"mischievous","emoji":"🐍","desc":"A translucent mamba that strikes from inside your shadow. You won't see it coming.","def_ability":"poison"},
    "oracle_python":    {"name":"Oracle Python",      "element":"holy",     "rarity":"legendary","base_atk":21,"base_def":12,"personality":"calm",      "emoji":"🐍","desc":"An ancient python with golden eyes that have seen everything. Strikes only when certain.","def_ability":"lifesteal"},
    # ── BEARS ────────────────────────────────────────────────────────────────
    "forest_cub":       {"name":"Forest Cub",         "element":"nature",   "rarity":"common",  "base_atk":5, "base_def":5, "personality":"playful",   "emoji":"🐻","desc":"A roly-poly cub that plays more than it fights. Plenty of time to grow into danger.","def_ability":"intercept"},
    "cave_bear":        {"name":"Cave Bear",           "element":"earth",    "rarity":"uncommon","base_atk":8, "base_def":8, "personality":"fierce",    "emoji":"🐻","desc":"A boulder with fur and opinions. Will protect its partner with everything it has.","def_ability":"intercept"},
    "frost_bear":       {"name":"Frost Bear",          "element":"water",    "rarity":"rare",    "base_atk":11,"base_def":10,"personality":"loyal",     "emoji":"🐻","desc":"A glacier-white bear of immense size and patience. Nothing moves it until it decides to move.","def_ability":"intercept"},
    "shadow_grizzly":   {"name":"Shadow Grizzly",      "element":"shadow",   "rarity":"epic",    "base_atk":17,"base_def":11,"personality":"fierce",    "emoji":"🐻","desc":"A grizzly that hunts in pitch darkness. The only warning is the sound of impact.","def_ability":"counter"},
    # ── HAWKS & BIRDS ─────────────────────────────────────────────────────────
    "swift_sparrow":    {"name":"Swift Sparrow",       "element":"wind",     "rarity":"common",  "base_atk":4, "base_def":2, "personality":"playful",   "emoji":"🦅","desc":"A tiny sparrow with ridiculous speed. Darts in, strikes, gone.","def_ability":"stun"},
    "storm_hawk":       {"name":"Storm Hawk",           "element":"lightning","rarity":"uncommon","base_atk":7, "base_def":3, "personality":"fierce",    "emoji":"🦅","desc":"A raptor that dives through storm clouds. Talons charged with electricity.","def_ability":"stun"},
    "ember_falcon":     {"name":"Ember Falcon",         "element":"fire",     "rarity":"rare",    "base_atk":11,"base_def":4, "personality":"fierce",    "emoji":"🦅","desc":"A falcon trailing fire from its wingtips. Precision predator.","def_ability":"counter"},
    "frost_raven":      {"name":"Frost Raven",           "element":"water",    "rarity":"rare",    "base_atk":9, "base_def":5, "personality":"calm",      "emoji":"🦅","desc":"A raven carved from ice. It watches everything and judges silently.","def_ability":"shield"},
    "shadow_eagle":     {"name":"Shadow Eagle",         "element":"shadow",   "rarity":"epic",    "base_atk":16,"base_def":6, "personality":"mischievous","emoji":"🦅","desc":"An eagle that vanishes into shadow mid-dive. Hits before the target knows it's there.","def_ability":"stun"},
    "celestial_phoenix":{"name":"Celestial Phoenix",   "element":"holy",     "rarity":"legendary","base_atk":23,"base_def":11,"personality":"loyal",    "emoji":"🦅","desc":"A phoenix reborn each dawn. Fights alongside its partner through every kind of death.","def_ability":"lifesteal"},
    # ── WOLVES ───────────────────────────────────────────────────────────────
    "timber_wolf":      {"name":"Timber Wolf",         "element":"earth",    "rarity":"common",  "base_atk":5, "base_def":3, "personality":"fierce",    "emoji":"🐺","desc":"A pack hunter from the deep forest. Loyal to its chosen pack.","def_ability":"intercept"},
    "shadow_wolf":      {"name":"Shadow Wolf",          "element":"shadow",   "rarity":"rare",    "base_atk":10,"base_def":5, "personality":"mischievous","emoji":"🐺","desc":"A wolf that hunts between dimensions. Impossible to track. Loves to play.","def_ability":"stun"},
    "frost_wolf":       {"name":"Frost Wolf",            "element":"water",    "rarity":"rare",    "base_atk":9, "base_def":7, "personality":"loyal",     "emoji":"🐺","desc":"A white wolf born in a blizzard. It would die before abandoning its partner.","def_ability":"intercept"},
    "thunder_wolf":     {"name":"Thunder Wolf",          "element":"lightning","rarity":"epic",    "base_atk":16,"base_def":7, "personality":"fierce",    "emoji":"🐺","desc":"A wolf that outruns lightning. It strikes before the thunder arrives.","def_ability":"counter"},
    "dire_wolf":        {"name":"Dire Wolf",             "element":"void",     "rarity":"legendary","base_atk":25,"base_def":13,"personality":"fierce",   "emoji":"🐺","desc":"An ancient apex predator. Commands silence in any room it enters.","def_ability":"counter"},
    # ── HORSES ───────────────────────────────────────────────────────────────
    "wild_stallion":    {"name":"Wild Stallion",        "element":"earth",    "rarity":"uncommon","base_atk":7, "base_def":5, "personality":"fierce",    "emoji":"🐴","desc":"An untamed horse from the open plains. Respects strength. Nothing else.","def_ability":"shield"},
    "nightmare_steed":  {"name":"Nightmare",            "element":"shadow",   "rarity":"epic",    "base_atk":18,"base_def":9, "personality":"fierce",    "emoji":"🐴","desc":"A horse of living shadow and hellfire. Its hoofbeats echo in places they shouldn't.","def_ability":"counter"},
    "celestial_steed":  {"name":"Celestial Steed",     "element":"holy",     "rarity":"legendary","base_atk":22,"base_def":13,"personality":"loyal",    "emoji":"🐴","desc":"A white war horse that gallops between stars. Chosen few ever ride it.","def_ability":"shield"},
    # ── FANTASY BEASTS ───────────────────────────────────────────────────────
    "slime_wisp":       {"name":"Slime Wisp",           "element":"void",     "rarity":"common",  "base_atk":3, "base_def":4, "personality":"playful",   "emoji":"🫧","desc":"A blobby little wisp that bounces everywhere. Giggles. Somehow deals damage.","def_ability":"shield"},
    "stone_golem_pup":  {"name":"Stone Golem Pup",     "element":"earth",    "rarity":"uncommon","base_atk":5, "base_def":8, "personality":"lazy",      "emoji":"🗿","desc":"A miniature stone golem that moves exactly as fast as it wants to. Very slow.","def_ability":"intercept"},
    "fairy_fox":        {"name":"Fairy Fox",             "element":"wind",     "rarity":"uncommon","base_atk":6, "base_def":3, "personality":"playful",   "emoji":"🦊","desc":"A fox trailing sparkling dust. Charming, fast, and entirely too clever.","def_ability":"stun"},
    "crystal_crab":     {"name":"Crystal Crab",          "element":"earth",    "rarity":"rare",    "base_atk":7, "base_def":12,"personality":"timid",     "emoji":"🦀","desc":"A crab with a shell of solid quartz. Near-impenetrable defense. Pinches only when startled.","def_ability":"intercept"},
    "lava_toad":        {"name":"Lava Toad",             "element":"fire",     "rarity":"rare",    "base_atk":10,"base_def":8, "personality":"lazy",      "emoji":"🐸","desc":"A rotund toad that sweats magma. It will not hurry. It doesn't need to.","def_ability":"counter"},
    "shadow_sprite":    {"name":"Shadow Sprite",         "element":"shadow",   "rarity":"rare",    "base_atk":12,"base_def":4, "personality":"mischievous","emoji":"🌑","desc":"A tiny shadow elemental with a chaotic streak a mile wide.","def_ability":"poison"},
    "arc_elemental":    {"name":"Arc Elemental",         "element":"lightning","rarity":"epic",    "base_atk":17,"base_def":6, "personality":"calm",      "emoji":"⚡","desc":"A being of pure lightning given shape. Measured, dangerous, exact.","def_ability":"stun"},
    "bloodhound_specter":{"name":"Bloodhound Specter",  "element":"shadow",   "rarity":"epic",    "base_atk":19,"base_def":7, "personality":"fierce",    "emoji":"👻","desc":"The ghost of a legendary hunting hound. Still on the hunt. Always.","def_ability":"counter"},
    "void_wisp":        {"name":"Void Wisp",             "element":"void",     "rarity":"epic",    "base_atk":16,"base_def":8, "personality":"mischievous","emoji":"🌀","desc":"A flickering wisp of void energy. It doesn't follow rules. Especially yours.","def_ability":"poison"},
    "storm_titan":      {"name":"Storm Titan",           "element":"lightning","rarity":"legendary","base_atk":26,"base_def":14,"personality":"fierce",   "emoji":"⚡","desc":"An elemental titan born from the heart of the greatest storm ever recorded.","def_ability":"counter"},
    "the_ancient_one":  {"name":"The Ancient One",       "element":"void",     "rarity":"mythic",  "base_atk":38,"base_def":22,"personality":"calm",     "emoji":"🌀","desc":"A being older than the world's name. It watches with the patience of eternity. Extraordinarily rare.","def_ability":"lifesteal"},
    "celestial_pup":    {"name":"Celestial Pup",         "element":"holy",     "rarity":"mythic",  "base_atk":32,"base_def":25,"personality":"loyal",    "emoji":"✨","desc":"A small divine being that chose to look like a puppy. Nobody questions it. It's too cute.","def_ability":"intercept"},
}

# Defensive ability definitions
PET_DEF_ABILITIES = {
    "intercept":  {"name":"Intercept",     "emoji":"🛡️","desc":"Jumps in front of the attack, absorbing damage for you.",     "proc_base":0.20},
    "counter":    {"name":"Counter Strike","emoji":"⚔️","desc":"Retaliates instantly with a fierce counter attack.",           "proc_base":0.18},
    "poison":     {"name":"Venom Bite",    "emoji":"🐍","desc":"Sinks fangs into the attacker, applying poison.",             "proc_base":0.16},
    "stun":       {"name":"Stunning Blow", "emoji":"⚡","desc":"Delivers a blow that stuns the attacker (miss next attack).", "proc_base":0.14},
    "lifesteal":  {"name":"Life Drain",    "emoji":"💜","desc":"Drains life force from the attacker and channels it to you.", "proc_base":0.16},
    "shield":     {"name":"Aura Shield",   "emoji":"✨","desc":"Projects a protective aura that reduces incoming damage.",    "proc_base":0.22},
}

PERSONALITY_DEFEND = {
    "playful":    "leaps in front of you with a gleeful yip!",
    "fierce":     "snarls and throws itself between you and the attacker!",
    "calm":       "steps forward with quiet, unshakable resolve.",
    "mischievous":"appears from nowhere and intercepts the hit!",
    "loyal":      "refuses to let you take that hit alone.",
    "lazy":       "manages to drag itself over just in time.",
    "greedy":     "protects you — but will expect a snack for this.",
    "timid":      "trembles but holds the line for you.",
}

# EXP needed per pet level
def pet_exp_for_level(lvl): return lvl * 50 + (lvl * lvl * 5)

# Passive bonus unlocks by pet level
PET_LEVEL_PASSIVES = {
    5:   {"atk_flat": 2},
    10:  {"atk_flat": 5},
    15:  {"atk_flat": 5,  "crit_bonus": 0.03},
    20:  {"atk_flat": 8,  "crit_bonus": 0.05},
    25:  {"atk_flat": 10, "crit_bonus": 0.05, "dodge_bonus": 0.03},
    30:  {"atk_flat": 12, "crit_bonus": 0.08, "dodge_bonus": 0.05},
    40:  {"atk_flat": 15, "crit_bonus": 0.10, "dodge_bonus": 0.05, "lifesteal_flat": 5},
    50:  {"atk_flat": 20, "crit_bonus": 0.12, "dodge_bonus": 0.08, "lifesteal_flat": 10},
    60:  {"atk_flat": 26, "crit_bonus": 0.14, "dodge_bonus": 0.10, "lifesteal_flat": 13},
    75:  {"atk_flat": 33, "crit_bonus": 0.17, "dodge_bonus": 0.13, "lifesteal_flat": 17},
    100: {"atk_flat": 42, "crit_bonus": 0.22, "dodge_bonus": 0.17, "lifesteal_flat": 22},
}

def get_pet_passives(pet_level):
    bonus = {}
    for threshold in sorted(PET_LEVEL_PASSIVES.keys()):
        if pet_level >= threshold:
            bonus = dict(PET_LEVEL_PASSIVES[threshold])
    return bonus

def get_pet_def_proc_chance(pet):
    """Chance that pet's defensive ability triggers when owner is attacked."""
    sp = PET_SPECIES.get(pet.get("species"), {})
    da = sp.get("def_ability")
    if not da: return 0.0
    lvl = pet.get("level", 1)
    if lvl < 10: return 0.0          # ability not yet unlocked
    base = PET_DEF_ABILITIES[da]["proc_base"]
    level_bonus = min(0.30, lvl * 0.004)   # up to +30% at L75
    hunger_ok = pet.get("hunger", 100) >= 20
    mood_ok   = pet.get("mood", 100)   >= 30
    if not hunger_ok or not mood_ok: return 0.0
    return round(base + level_bonus, 3)

def apply_pet_defense(pet, attacker, dmg_after_def, extra_notes):
    """
    Check if the defender's pet triggers its defensive ability.
    Mutates dmg_after_def (returns new value) and appends to extra_notes.
    Also returns any status to apply to attacker: ("poison"|"stun"|None, value).
    """
    if dmg_after_def <= 0:
        return dmg_after_def, None, None
    chance = get_pet_def_proc_chance(pet)
    if chance <= 0 or random.random() > chance:
        return dmg_after_def, None, None
    sp     = PET_SPECIES.get(pet.get("species"), {})
    da     = sp.get("def_ability", "shield")
    lvl    = pet.get("level", 1)
    pers   = sp.get("personality", "calm")
    emoji  = sp.get("emoji", "🐾")
    pname  = pet.get("nickname") or sp.get("name", "Your Pet")
    defend_flavor = PERSONALITY_DEFEND.get(pers, "steps in to defend you!")
    ability_info  = PET_DEF_ABILITIES.get(da, {})
    ab_emoji = ability_info.get("emoji", "🐾")
    status_type = None
    status_val  = None

    if da == "intercept":
        absorb_pct = min(0.60, 0.20 + lvl * 0.005)
        absorbed   = round(dmg_after_def * absorb_pct)
        dmg_after_def = max(0, dmg_after_def - absorbed)
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Intercept!* Absorbed *{absorbed} dmg*!")

    elif da == "counter":
        counter_dmg = round(5 + lvl * 1.2)
        if attacker:
            attacker["hp"] = max(0, attacker.get("hp", 0) - counter_dmg)
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Counter Strike!* Deals *{counter_dmg} dmg* back!")

    elif da == "poison":
        poison_dmg = round(4 + lvl * 0.5)
        status_type = "poison"
        status_val  = poison_dmg
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Venom Bite!* Attacker is *poisoned* ({poison_dmg} dmg/30s)!")

    elif da == "stun":
        status_type = "stun"
        status_val  = 1
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Stunning Blow!* Attacker is *stunned* — misses next attack!")

    elif da == "lifesteal":
        heal_amt = round(8 + lvl * 0.6)
        status_type = "lifesteal_to_owner"
        status_val  = heal_amt
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Life Drain!* Drained *{heal_amt} HP* from attacker!")

    elif da == "shield":
        shield_pct = min(0.40, 0.10 + lvl * 0.003)
        absorbed   = round(dmg_after_def * shield_pct)
        dmg_after_def = max(0, dmg_after_def - absorbed)
        extra_notes.append(f"{emoji} *{pname}* {defend_flavor}\n{ab_emoji} *Aura Shield!* Shielded *{absorbed} dmg*!")

    return dmg_after_def, status_type, status_val

# Eggs and their hatch pools by rarity weight
PET_EGG_POOLS = {
    "Common Egg":   {"common":0.65,"uncommon":0.30,"rare":0.05},
    "Rare Egg":     {"uncommon":0.40,"rare":0.45,"epic":0.15},
    "Dragon Egg":   {"rare":0.35,"epic":0.50,"legendary":0.15},
    "Mythic Egg":   {"epic":0.40,"legendary":0.45,"mythic":0.15},
}

def _hatch_species(egg_name):
    """Pick a random species from egg pool, weighted by rarity."""
    pool = PET_EGG_POOLS.get(egg_name)
    if not pool: return None
    roll = random.random()
    cumulative = 0.0
    target_rarity = None
    for rarity, weight in pool.items():
        cumulative += weight
        if roll <= cumulative:
            target_rarity = rarity; break
    if not target_rarity:
        target_rarity = list(pool.keys())[-1]
    candidates = [sid for sid, sd in PET_SPECIES.items() if sd["rarity"] == target_rarity]
    return random.choice(candidates) if candidates else None

def get_pet_atk_bonus(pet):
    """Raw ATK a pet contributes per attack. Reduced by low hunger/mood."""
    sp = PET_SPECIES.get(pet.get("species"), {})
    base = sp.get("base_atk", 0) + pet.get("level", 1) * 2
    passives = get_pet_passives(pet.get("level", 1))
    base += passives.get("atk_flat", 0)
    hunger = pet.get("hunger", 100)
    mood   = pet.get("mood", 100)
    if hunger < 20: base = round(base * 0.5)
    elif mood < 40: base = 0
    return max(0, base)

def pet_status_tag(pet):
    """Short status summary for a pet."""
    hunger = pet.get("hunger", 100)
    mood   = pet.get("mood", 100)
    if hunger < 20:   return "😫 Starving"
    if hunger < 50:   return "😕 Hungry"
    if mood < 40:     return "😢 Sad"
    if mood < 70:     return "😐 Okay"
    if mood >= 90:    return "😄 Thrilled"
    return "🙂 Happy"

def _decay_pet(pet):
    """Apply hunger/mood decay based on elapsed time. Mutates in place."""
    now = datetime.now()
    last_fed_str = pet.get("last_fed")
    if last_fed_str:
        try:
            hours_since = (now - datetime.fromisoformat(last_fed_str)).total_seconds() / 3600
            decay = round(hours_since * 5)  # -5 hunger per hour
            pet["hunger"] = max(0, pet.get("hunger", 100) - decay)
        except Exception: pass
    # Mood drops when hungry
    if pet.get("hunger", 100) < 30:
        mood_decay = round((30 - pet["hunger"]) * 0.5)
        pet["mood"] = max(0, pet.get("mood", 100) - mood_decay)

def get_active_pet_record(owner_id):
    """Fetch the active pet for a player from the DB."""
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM pets WHERE owner_id=? AND is_active=1", (owner_id,))
    row = c.fetchone(); conn.close()
    if row:
        pet = dict(row)
        _decay_pet(pet)
        return pet
    return None

def get_all_pets(owner_id):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM pets WHERE owner_id=? ORDER BY is_active DESC, level DESC", (owner_id,))
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    for p in rows: _decay_pet(p)
    return rows

def save_pet(pet):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO pets
        (pet_id,owner_id,species,nickname,level,exp,hunger,mood,last_fed,last_trained,is_active,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pet.get("pet_id"), pet["owner_id"], pet["species"],
         pet.get("nickname"), pet.get("level",1), pet.get("exp",0),
         pet.get("hunger",100), pet.get("mood",100),
         pet.get("last_fed"), pet.get("last_trained"),
         pet.get("is_active",0), pet.get("created_at", datetime.now().isoformat())))
    conn.commit(); conn.close()

def _pet_display_name(pet):
    sp = PET_SPECIES.get(pet.get("species"), {})
    nick = pet.get("nickname")
    base = sp.get("name", pet.get("species","Unknown"))
    return f"{nick} ({base})" if nick else base

def _build_pet_card(pet):
    """Build full status card text for a pet."""
    sp      = PET_SPECIES.get(pet.get("species"), {})
    dname   = _pet_display_name(pet)
    lvl     = pet.get("level", 1)
    exp     = pet.get("exp", 0)
    exp_needed = pet_exp_for_level(lvl)
    hunger  = pet.get("hunger", 100)
    mood    = pet.get("mood", 100)
    elem    = sp.get("element","?")
    rar     = sp.get("rarity","common")
    pers    = sp.get("personality","calm")
    emoji   = sp.get("emoji","🐾")
    elem_e  = ELEMENT_EMOJI.get(elem,"")
    pers_e  = PERSONALITY_EMOJI.get(pers,"")
    rar_e   = RARITY_EMOJI.get(rar,"")
    status  = pet_status_tag(pet)
    atk_bon = get_pet_atk_bonus(pet)
    passives = get_pet_passives(lvl)

    hunger_bar = "█" * round(hunger/10) + "░" * (10 - round(hunger/10))
    mood_bar   = "█" * round(mood/10)   + "░" * (10 - round(mood/10))
    exp_bar_pct = min(1.0, exp / max(1, exp_needed))
    exp_bar     = "█" * int(exp_bar_pct * 8) + "░" * (8 - int(exp_bar_pct * 8))

    lines = [
        f"{emoji} *{dname}*  {rar_e} {rar.capitalize()}",
        f"{elem_e} {elem.capitalize()}  |  {pers_e} {pers.capitalize()}",
        f"_{sp.get('desc','')}_",
        "",
        f"*Level {lvl}*",
        f"✨ EXP: `{exp}/{exp_needed}` [{exp_bar}]",
        f"🍖 Hunger: {hunger}/100  [{hunger_bar}]",
        f"💛 Mood:   {mood}/100  [{mood_bar}]",
        f"Status: {status}",
        "",
        f"⚔️ Combat ATK: +*{atk_bon}* per attack",
    ]
    if passives:
        plines = []
        if passives.get("crit_bonus"):  plines.append(f"+{round(passives['crit_bonus']*100)}% crit")
        if passives.get("dodge_bonus"): plines.append(f"+{round(passives['dodge_bonus']*100)}% dodge")
        if passives.get("lifesteal_flat"): plines.append(f"+{passives['lifesteal_flat']} lifesteal")
        if plines: lines.append("✨ Passives: " + "  |  ".join(plines))
    next_unlock = next((t for t in sorted(PET_LEVEL_PASSIVES) if t > lvl), None)
    if next_unlock:
        lines.append(f"🔒 Next unlock: Level {next_unlock}")
    # Defensive ability
    sp_def = sp.get("def_ability")
    if sp_def and lvl >= 10:
        ab_info = PET_DEF_ABILITIES.get(sp_def, {})
        chance  = round(get_pet_def_proc_chance(pet) * 100)
        lines.append(f"{ab_info.get('emoji','🐾')} *{ab_info.get('name','Ability')}* ({chance}% proc)")
    elif sp_def:
        ab_info = PET_DEF_ABILITIES.get(sp_def, {})
        lines.append(f"🔒 *{ab_info.get('name','Ability')}* unlocks at Level 10")
    return "\n".join(lines)

def _pet_list_markup(pets, page=0, page_size=5):
    start = page * page_size
    chunk = pets[start:start+page_size]
    rows = []
    for pet in chunk:
        sp = PET_SPECIES.get(pet.get("species"),{})
        emoji = sp.get("emoji","🐾")
        dname = _pet_display_name(pet)
        active_tag = " ✅" if pet.get("is_active") else ""
        rows.append([InlineKeyboardButton(
            f"{emoji} {dname} Lv{pet.get('level',1)}{active_tag}",
            callback_data=f"petview_{pet['pet_id']}")])
    nav = []
    if page > 0:    nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"petlist_{page-1}"))
    if start+page_size < len(pets): nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"petlist_{page+1}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="petmain")])
    return InlineKeyboardMarkup(rows)

def _pet_view_markup(pet_id, is_active):
    rows = []
    if not is_active:
        rows.append([InlineKeyboardButton("✅ Make Active", callback_data=f"petactivate_{pet_id}")])
    rows.append([
        InlineKeyboardButton("🍖 Feed",  callback_data=f"petfeed_{pet_id}"),
        InlineKeyboardButton("🏋️ Train", callback_data=f"pettrain_{pet_id}"),
    ])
    rows.append([InlineKeyboardButton("📝 Rename", callback_data=f"petrename_{pet_id}")])
    rows.append([
        InlineKeyboardButton("🔙 All Pets", callback_data="petlist_0"),
        InlineKeyboardButton("❌ Release",  callback_data=f"petrelease_{pet_id}"),
    ])
    return InlineKeyboardMarkup(rows)

def _pet_main_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 My Pets",  callback_data="petlist_0"),
         InlineKeyboardButton("🛒 Pet Shop", callback_data="petshop")],
        [InlineKeyboardButton("🥚 Hatch Egg", callback_data="hatch_egg")],
    ])

# Items that can be found in game
CONSUMABLES = {
    # Healing
    "Health Potion":          {"desc":"Restores 50 HP.","sell":75},
    "Greater Health Potion":  {"desc":"Restores 100 HP.","sell":200},
    "Grand Restorative Flask":{"desc":"Restores 200 HP.","sell":450},
    # Revive
    "Scroll of Revival":      {"desc":"Revive a defeated player.","sell":750},
    # Skill items
    "Holy Water Vial":        {"desc":"Required for Miracle (High Priest skill).","sell":1000},
    # Crafting
    "Iron Shard":             {"desc":"Crafting material. Rare drop.","sell":100},
    "Enchanting Scroll":      {"desc":"Used to enchant gear.","sell":150},
    # Pets
    "Pet Snack":              {"desc":"Feeds your active pet. Restores 30 hunger and 10 mood.","sell":20},
    "Common Egg":             {"desc":"A warm egg. Common or uncommon pet inside.","sell":150},
    "Rare Egg":               {"desc":"A glowing egg. Uncommon to rare pet inside.","sell":400},
    "Dragon Egg":             {"desc":"A heavy scaled egg. Rare to epic pet inside.","sell":1000},
    "Mythic Egg":             {"desc":"A shimmering egg. Epic to mythic pet inside.","sell":3000},
}

# ── CRAFTING RECIPES ──────────────────────────────────────────────────────────
RECIPES = {
    "Iron Compound":  {"mats": {"Iron Shard": 4},                "result": "Steel Knight Sword"},
    "Scale Plating":  {"mats": {"Iron Shard": 3},                "result": "Soldier's Plating"},
    "Charm Craft":    {"mats": {"Iron Shard": 4},                "result": "Silver Prayer Beads"},
    "Enchant Bundle": {"mats": {"Iron Shard": 6},                "result": "Enchanting Scroll"},
    "Scale Blade":    {"mats": {"Iron Shard": 7},                "result": "Ranger's Marked Bow"},
}

SHOP_POOL = [
    {"item":"Health Potion","price":150,"desc":"Restores 50 HP."},
    {"item":"Greater Health Potion","price":400,"desc":"Restores 100 HP."},
    {"item":"Grand Restorative Flask","price":900,"desc":"Restores 200 HP."},
    {"item":"Scroll of Revival","price":1500,"desc":"Revive a defeated player."},
    {"item":"Iron Shard","price":300,"desc":"Crafting material."},
    {"item":"Enchanting Scroll","price":500,"desc":"Enchant gear. Future use."},
]
ENHANCE_COSTS = {1:1, 2:2, 3:3, 4:5, 5:7, 6:10, 7:14, 8:18, 9:23, 10:30}
ENHANCE_RATES = {1:1.00, 2:0.95, 3:0.90, 4:0.85, 5:0.75,
                 6:0.65, 7:0.55, 8:0.45, 9:0.35, 10:0.25}

ENCHANT_EFFECTS = {
    "weapon": [
        {"id":"lifesteal",    "desc":"Each hit restores 3 HP",          "type":"lifesteal_flat","val":3},
        {"id":"flaming",      "desc":"10% chance to burn on hit (5 dmg/20s for 1min)","type":"burn_proc","val":5},
        {"id":"keen",         "desc":"+8% crit chance",                 "type":"crit_bonus","val":0.08},
        {"id":"heavy",        "desc":"+5 flat damage per hit",          "type":"flat_dmg","val":5},
        {"id":"vampiric",     "desc":"Kills restore 15 HP",             "type":"kill_heal","val":15},
        {"id":"swift",        "desc":"+5% dodge chance",                "type":"dodge_bonus","val":0.05},
    ],
    "armor": [
        {"id":"reinforced",   "desc":"+8 DEF",                         "type":"armor_def","val":8},
        {"id":"thorned",      "desc":"Reflect 5 dmg to attacker",      "type":"reflect_flat","val":5},
        {"id":"warded",       "desc":"+10% healing received",           "type":"heal_bonus","val":0.10},
        {"id":"resilient",    "desc":"+15 max HP",                     "type":"max_hp","val":15},
        {"id":"hardened",     "desc":"5% chance to fully block a hit", "type":"block_chance","val":0.05},
        {"id":"quickened",    "desc":"+4% dodge",                      "type":"dodge_bonus","val":0.04},
    ],
    "accessory": [
        {"id":"amplified",    "desc":"+3 to all stats",                "type":"all_stats","val":3},
        {"id":"golden",       "desc":"+10% gold from all sources",     "type":"gold_bonus","val":0.10},
        {"id":"soulbound",    "desc":"+5% EXP from all sources",       "type":"exp_bonus","val":0.05},
        {"id":"fortified",    "desc":"+20 max HP",                     "type":"max_hp","val":20},
        {"id":"empowered",    "desc":"+5 ATK",                         "type":"atk","val":5},
        {"id":"mystical",     "desc":"+6 to primary class stat",       "type":"primary_stat","val":6},
    ],
}

_shop_cache = {"items":None,"date":None}
def get_daily_shop():
    today = datetime.now().strftime("%Y-%m-%d")
    if _shop_cache["date"] != today:
        random.seed(today)
        _shop_cache["items"] = random.sample(SHOP_POOL, min(5, len(SHOP_POOL)))
        random.seed()
        _shop_cache["date"] = today
    return _shop_cache["items"]

# ── BOSSES ────────────────────────────────────────────────────────────────────
BOSSES = {
    "1 ball": {"name":"The 1 Ball","hp":1200,"max_hp":1200,"dmg_min":68,"dmg_max":120,
               "exp":2000,"gold":150,"title":"1-Ball Slayer","desc":"Every warrior left it standing. It has grown tired of waiting.",
               "loot_table":[("Greater Health Potion","uncommon"),("Iron Shard","uncommon"),("Soldier's Plating","uncommon")]},
    "3 ball": {"name":"The 3 Ball","hp":2000,"max_hp":2000,"dmg_min":105,"dmg_max":165,
               "exp":4000,"gold":300,"title":"3-Ball Slayer","desc":"Lurks in the shadows and waits. When it strikes, things shatter.",
               "loot_table":[("Grand Restorative Flask","rare"),("Iron Shard","uncommon"),("Ranger's Marked Bow","rare")]},
    "5 ball": {"name":"The 5 Ball","hp":3000,"max_hp":3000,"dmg_min":143,"dmg_max":210,
               "exp":7000,"gold":500,"title":"5-Ball Slayer","desc":"The heart of the dungeon. The middle cannot be ignored.",
               "loot_table":[("Scroll of Revival","rare"),("Warlock's Dread Staff","rare"),("Fortune Coin","rare")]},
    "7 ball": {"name":"The 7 Ball","hp":4500,"max_hp":4500,"dmg_min":180,"dmg_max":270,
               "exp":12000,"gold":800,"title":"7-Ball Slayer","desc":"The last guardian before the final boss. It knows what it protects.",
               "loot_table":[("Warlord's Edge","epic"),("Void-Touched Robe","epic"),("Twin Strike Ring","epic")]},
    "8 ball": {"name":"The 8 Ball","hp":8000,"max_hp":8000,"dmg_min":225,"dmg_max":375,
               "exp":20000,"gold":2000,"title":"8-Ball Champion","desc":"The final boss. The only one that matters in the end.",
               "loot_table":[("Ruinblade","legendary"),("Archmage's Sanctum Robe","legendary"),("Ring of the Endless","legendary")]},
    "void":   {"name":"The Void Ball","hp":15000,"max_hp":15000,"dmg_min":375,"dmg_max":600,
               "exp":50000,"gold":5000,"title":"Blackball Slayer","desc":"It was never part of this realm. It came from somewhere else.","secret":True,
               "loot_table":[("Shard of the Void","legendary"),("The Last Stand Locket","legendary"),("The Void Mark","legendary")]},
}

RAID_TIERS = [
    {"name":"The Forest Skirmish","min_level":1,"waves":2,"wave_boss_key":"1 ball",
     "wave_enemies":[{"name":"Goblin Scout","hp":150,"dmg_min":15,"dmg_max":30},
                     {"name":"Cursed Wanderer","hp":250,"dmg_min":20,"dmg_max":40}],
     "exp_reward":600,"gold_reward":120,
     "loot_table":[
         ("Iron Broadsword",0.40),("Rusty Shiv",0.35),("Iron Shard Ring",0.30),
         ("Worn Leather Band",0.30),("Scout's Pendant",0.25),("Brass Ring",0.20),
         ("Traveler's Coin",0.15),("Silk Band",0.10),("Obsidian Stud",0.08),
         ("Iron Shard",0.12),("Health Potion",0.20),
     ]},
    {"name":"The Fortress Assault","min_level":5,"waves":3,"wave_boss_key":"3 ball",
     "wave_enemies":[{"name":"Stone Golem","hp":400,"dmg_min":35,"dmg_max":60},
                     {"name":"Pocket Demon","hp":600,"dmg_min":45,"dmg_max":75},
                     {"name":"Cursed Knight","hp":800,"dmg_min":55,"dmg_max":90}],
     "exp_reward":1400,"gold_reward":300,
     "loot_table":[
         ("Steel Knight Sword",0.35),("Crystal Core Wand",0.30),("Warlock's Dread Staff",0.25),
         ("Bloodstone Band",0.25),("Shadowmark Signet",0.20),("Hunter's Fang",0.18),
         ("Crystal Bead Necklace",0.18),("Iron Scale Vest",0.15),("Shadow Leather Coat",0.12),
         ("Iron Shard",0.25),("Fortune Coin",0.10),("Hawk Eye Medallion",0.08),
         ("Enchanting Scroll",0.10),
     ]},
    {"name":"The Citadel Siege","min_level":10,"waves":3,"wave_boss_key":"5 ball",
     "wave_enemies":[{"name":"Ashen Wraith","hp":1000,"dmg_min":65,"dmg_max":100},
                     {"name":"Void Specter","hp":1500,"dmg_min":85,"dmg_max":130},
                     {"name":"Break Titan","hp":2000,"dmg_min":100,"dmg_max":150}],
     "exp_reward":3000,"gold_reward":700,
     "loot_table":[
         ("Warlord's Edge",0.30),("Void Channel Staff",0.20),("Ferrule Dart",0.25),
         ("War Master's Clasp",0.22),("Phantom Loop",0.18),("Warrior's Band",0.16),
         ("Mage's Coil",0.15),("Stone Heart",0.18),("Beast Fang Chain",0.15),
         ("Traveler's Compass",0.12),("The Storm Torc",0.12),
         ("Iron Shard",0.35),("Enchanting Scroll",0.20),("Scroll of Revival",0.08),
     ]},
    {"name":"The Final Sanctum  -  Endgame","min_level":15,"waves":4,"wave_boss_key":"8 ball",
     "wave_enemies":[{"name":"Shadow Knight","hp":2500,"dmg_min":100,"dmg_max":160},
                     {"name":"Void Ball","hp":3500,"dmg_min":130,"dmg_max":200},
                     {"name":"Cursed Sentinel","hp":5000,"dmg_min":150,"dmg_max":230},
                     {"name":"Doom Cluster","hp":6000,"dmg_min":180,"dmg_max":260}],
     "exp_reward":8000,"gold_reward":2000,
     "loot_table":[
         ("Ruinblade",0.12),("The Mind's Eye",0.10),("Runed Finger",0.15),
         ("Twin Strike Ring",0.18),("Eye of the Void",0.16),("Void Circle",0.14),
         ("War Knuckle",0.14),("Cleric's Band",0.12),("Runed Heart",0.14),
         ("The Shadow Whisper",0.12),("Guardian's Talisman",0.10),
         ("Shard of the Void",0.06),("Ring of the Endless",0.05),("The Warlord's Ring",0.04),
         ("The Eternal Ring",0.04),("Iron Shard",0.50),("Enchanting Scroll",0.35),
         ("Scroll of Revival",0.15),
     ]},
]

SOLO_RAID_TIERS = [
    {"name":"The Quiet Ruins","min_level":1,"wave_boss_key":"1 ball",
     "wave_enemies":[
         {"name":"Young Raider","hp":80,"dmg_min":8,"dmg_max":18},
         {"name":"Dungeon Brawler","hp":130,"dmg_min":12,"dmg_max":24},
     ],
     "exp_reward":400,"gold_reward":80,
     "loot_table":[
         ("Iron Broadsword",0.40),("Rusty Shiv",0.35),("Iron Shard Ring",0.30),
         ("Worn Leather Band",0.28),("Scout's Pendant",0.25),("Brass Ring",0.22),
         ("Traveler's Coin",0.18),("Silk Band",0.12),("Obsidian Stud",0.10),
         ("Iron Shard",0.15),("Health Potion",0.25),
     ]},
    {"name":"The Side Pocket Run","min_level":5,"wave_boss_key":"3 ball",
     "wave_enemies":[
         {"name":"Stone Bruiser","hp":200,"dmg_min":20,"dmg_max":38},
         {"name":"Rail Runner","hp":320,"dmg_min":28,"dmg_max":50},
         {"name":"Dungeon Rogue","hp":450,"dmg_min":35,"dmg_max":62},
     ],
     "exp_reward":900,"gold_reward":200,
     "loot_table":[
         ("Steel Knight Sword",0.32),("Crystal Core Wand",0.28),("Warlock's Dread Staff",0.22),
         ("Bloodstone Band",0.24),("Shadowmark Signet",0.20),("Hunter's Fang",0.16),
         ("Crystal Bead Necklace",0.16),("Iron Shard",0.28),
         ("Fortune Coin",0.10),("Hawk Eye Medallion",0.07),
         ("Enchanting Scroll",0.08),
     ]},
    {"name":"The One-Man Break","min_level":10,"wave_boss_key":"5 ball",
     "wave_enemies":[
         {"name":"Iron Enforcer","hp":500,"dmg_min":40,"dmg_max":65},
         {"name":"Shadow Wraith","hp":750,"dmg_min":55,"dmg_max":85},
         {"name":"The Closer's Shadow","hp":1000,"dmg_min":65,"dmg_max":100},
     ],
     "exp_reward":2000,"gold_reward":480,
     "loot_table":[
         ("Warlord's Edge",0.28),("Void Channel Staff",0.18),("Ferrule Dart",0.24),
         ("War Master's Clasp",0.20),("Phantom Loop",0.16),("Warrior's Band",0.14),
         ("Mage's Coil",0.14),("Stone Heart",0.16),("Beast Fang Chain",0.14),
         ("Iron Shard",0.35),("Enchanting Scroll",0.18),("Scroll of Revival",0.07),
     ]},
    {"name":"The Ghost Run","min_level":15,"wave_boss_key":"8 ball",
     "wave_enemies":[
         {"name":"Void Knight","hp":1200,"dmg_min":65,"dmg_max":110},
         {"name":"8Ball Phantom","hp":1800,"dmg_min":85,"dmg_max":140},
         {"name":"The Dead Stroke","hp":2400,"dmg_min":100,"dmg_max":165},
         {"name":"Final Ghost","hp":3000,"dmg_min":115,"dmg_max":185},
     ],
     "exp_reward":5000,"gold_reward":1400,
     "loot_table":[
         ("Runed Finger",0.14),("Twin Strike Ring",0.16),("Eye of the Void",0.14),
         ("Void Circle",0.12),("War Knuckle",0.12),("Cleric's Band",0.10),
         ("Runed Heart",0.12),("The Shadow Whisper",0.10),("Guardian's Talisman",0.09),
         ("Shard of the Void",0.05),("Ring of the Endless",0.04),("The Warlord's Ring",0.03),
         ("The Eternal Ring",0.03),("Iron Shard",0.50),("Enchanting Scroll",0.30),
         ("Scroll of Revival",0.12),
     ]},
]

EXPLORE_ZONES = [
    {"name":"The Ancient Ruins","tier":"Easy","exp":500,"gold":50,
     "loot_table":[("Health Potion",0.15),("Rusty Shiv",0.10),("Wooden Prayer Beads",0.10),
                   ("Iron Shard Ring",0.08),("Worn Leather Band",0.08)],
     "fail_msg":"The road was longer than expected. You return empty-handed."},
    {"name":"The Back Room","tier":"Medium","exp":900,"gold":100,
     "loot_table":[("Greater Health Potion",0.10),("Mushroom Tip Blade",0.08),("Iron Broadsword",0.08),
                   ("Silk Band",0.06),("Bloodstone Band",0.05)],
     "fail_msg":"The bandits were too many. You barely escaped."},
    {"name":"The Condemned Hall","tier":"Hard","exp":1500,"gold":200,
     "loot_table":[("Grand Restorative Flask",0.05),("Scroll of Revival",0.03),("Iron Shard",0.15),
                   ("Fortune Coin",0.05),("Stone Heart",0.05),("Steel Knight Sword",0.04)],
     "fail_msg":"The ruins shifted and swallowed the path. You find nothing."},
    {"name":"The Shadow Den","tier":"Elite","exp":2500,"gold":400,
     "loot_table":[("Iron Shard",0.30),("Enchanting Scroll",0.15),
                   ("Warlord's Edge",0.03),("Void Channel Staff",0.03),
                   ("Twin Strike Ring",0.03),("Runed Heart",0.03)],
     "fail_msg":"The dragon was awake. You fled with your life."},
    {"name":"The Corner Pocket","tier":"Legendary","exp":5000,"gold":800,
     "loot_table":[("Ruinblade",0.01),("The Mind's Eye",0.01),("Shard of the Void",0.01),
                   ("The Last Stand Locket",0.01),("The Void Mark",0.01),
                   ("Iron Shard",0.20),("Enchanting Scroll",0.20)],
     "fail_msg":"The void rejected you. You wake up back at camp, shaken."},
]

SOLO_QUESTS = [
    {"tier":"Easy","text":"You ran a message across town to a wanderer who couldn't leave their post.","exp":30,"gold":5,
     "loot_table":[("Health Potion",0.05),("Rusty Shiv",0.03),("Wooden Prayer Beads",0.03)]},
    {"tier":"Easy","text":"You offered aid to a stranger who'd run out of supplies mid-journey.","exp":25,"gold":8,
     "loot_table":[("Iron Shard Ring",0.05),("Scout's Pendant",0.05)]},
    {"tier":"Easy","text":"You cleared an ancient ruin that hadn't been touched in years.","exp":20,"gold":10,
     "loot_table":[("Health Potion",0.05),("Brass Ring",0.04)]},
    {"tier":"Easy","text":"You walked a recruit home after they lost their coin. Good people exist.","exp":35,"gold":5,
     "loot_table":[("Worn Leather Band",0.05),("Traveler's Coin",0.04)]},
    {"tier":"Easy","text":"You recovered a lost relic for an old wanderer who couldn't make the journey himself.","exp":28,"gold":7,
     "loot_table":[("Health Potion",0.06),("Rusty Shiv",0.03)]},
    {"tier":"Medium","text":"You survived a night in the back room with real stakes on the line.","exp":55,"gold":20,
     "loot_table":[("Greater Health Potion",0.03),("Iron Broadsword",0.04),("Silk Band",0.03)]},
    {"tier":"Medium","text":"You tracked a rogue agent who'd been working the region under a false identity.","exp":60,"gold":25,
     "loot_table":[("Mushroom Tip Blade",0.04),("Bloodstone Band",0.03),("Obsidian Stud",0.03)]},
    {"tier":"Medium","text":"You challenged the region's best warrior. Walked out with their respect.","exp":65,"gold":30,
     "loot_table":[("Iron Shard",0.05),("Shadowmark Signet",0.03),("Hunter's Fang",0.03)]},
    {"tier":"Medium","text":"You stormed a fortified position alone with everyone watching.","exp":70,"gold":25,
     "loot_table":[("Repeating Crossbow",0.04),("Crystal Core Wand",0.04),("Silver Prayer Beads",0.04)]},
    {"tier":"Hard","text":"You shut down a warlord who'd been terrorizing the region for six months.","exp":80,"gold":50,
     "loot_table":[("Iron Shard",0.10),("Grand Restorative Flask",0.01),("Scroll of Revival",0.01),
                   ("Ferrule Dart",0.02),("Warlock's Dread Staff",0.02)]},
    {"tier":"Hard","text":"You broke into the sealed vault and survived every trap inside.","exp":75,"gold":60,
     "loot_table":[("Iron Shard",0.10),("Enchanting Scroll",0.05),
                   ("War Master's Clasp",0.02),("Hawk Eye Medallion",0.02)]},
    {"tier":"Hard","text":"You defeated the fortress champion straight up, no advantage, on their home ground.","exp":80,"gold":55,
     "loot_table":[("Iron Shard",0.12),("Enchanting Scroll",0.05),
                   ("Ranger's Marked Bow",0.02),("Steel Knight Sword",0.02)]},
]

RANDOM_EVENTS = [
    {"key":"traveler","freq":"common",
     "msg":"🎱 *A Road Player has set up at the far table.*\nFirst to /greet gets a tip and something useful.",
     "exp":300,"loot_table":[("Health Potion",0.40),("Iron Shard",0.20),("Iron Shard Ring",0.20),("Scout's Pendant",0.20)]},
    {"key":"bandit","freq":"common",
     "msg":"🗡️ *A rogue warrior who lost badly is looking for someone to blame.* 150 HP. Use /fight. Take them down for +250 EXP.",
     "enemy_hp":150,"exp_reward":250,
     "loot_table":[("Health Potion",0.30),("Rusty Shiv",0.15),("Brass Ring",0.10)]},
    {"key":"ghost","freq":"common",
     "msg":"👻 *Something that used to wander here doesn't know it's gone.* 200 HP. Use /shoot to send it off. +300 EXP.",
     "enemy_hp":200,"exp_reward":300,
     "loot_table":[("Greater Health Potion",0.20),("Worn Leather Band",0.15)]},
    {"key":"merchant","freq":"uncommon",
     "msg":"🛍️ *A traveling merchant just arrived.*\n/greet them for 20% off at the shop for 30 minutes.",
     "discount":0.20,"duration_min":30},
    {"key":"rival","freq":"uncommon",
     "msg":"⚔️ *Someone walked in looking for action.*\nFirst to /fight claims the table. Winner gets bonus EXP and gold."},
    {"key":"drake","freq":"uncommon",
     "msg":"🎱 *A legendary raider just walked in uninvited.* 500 HP. Reply with /strike to run them off. Rewards split by damage dealt.",
     "enemy_hp":500,"exp_reward":1000,
     "loot_table":[("Iron Shard",0.50),("Enchanting Scroll",0.20),("Scroll of Revival",0.10)]},
    {"key":"cache","freq":"uncommon",
     "msg":"💰 *Someone left a bag in the corner and didn't come back.*\nFirst to /claim gets what's inside.",
     "loot_table":[("Iron Shard",0.30),("Greater Health Potion",0.30),("Silk Band",0.20),("Crystal Bead Necklace",0.20)]},
    {"key":"storm","freq":"uncommon",
     "msg":"🌩️ *Something disrupted the ley lines.* The air is different now. Conditions changed."},
    {"key":"legendary_merchant","freq":"rare",
     "msg":"👑 *A legendary craftsman just arrived with rare wares.* 10 minutes only. Use /shop legend.","duration_min":10},
    {"key":"shrine","freq":"rare",
     "msg":"🔮 *An old trophy was found behind the wall.*\nFirst to /pray gets something from it."},
    {"key":"cursed","freq":"rare",
     "msg":"⚰️ *A losing player put something bad into the table on their way out.*\nSomeone's been marked. Use /purge to lift it."},
]

GUILD_PERKS = {
    1:  {"exp_bonus":0,    "gold_bonus":0,    "desc":"No perks yet."},
    2:  {"exp_bonus":0.05, "gold_bonus":0,    "desc":"+5% EXP."},
    3:  {"exp_bonus":0.10, "gold_bonus":0,    "desc":"+10% EXP."},
    4:  {"exp_bonus":0.10, "gold_bonus":0.10, "desc":"+10% EXP, +10% Gold."},
    5:  {"exp_bonus":0.15, "gold_bonus":0.10, "desc":"+15% EXP, +10% Gold."},
    6:  {"exp_bonus":0.20, "gold_bonus":0.15, "desc":"+20% EXP, +15% Gold."},
    7:  {"exp_bonus":0.25, "gold_bonus":0.20, "desc":"+25% EXP, +20% Gold."},
    8:  {"exp_bonus":0.30, "gold_bonus":0.20, "desc":"+30% EXP, +20% Gold."},
    9:  {"exp_bonus":0.35, "gold_bonus":0.25, "desc":"+35% EXP, +25% Gold."},
    10: {"exp_bonus":0.40, "gold_bonus":0.30, "desc":"+40% EXP, +30% Gold. MAX."},
}
def guild_exp_for_level(level): return level * 500

IDLE_TIERS = [
    {"min_hours":1,   "max_hours":3,   "gold":50,   "exp":100,  "item_chances":[]},
    {"min_hours":3,   "max_hours":8,   "gold":150,  "exp":300,  "item_chances":[("common",0.10)]},
    {"min_hours":8,   "max_hours":24,  "gold":400,  "exp":800,  "item_chances":[("uncommon",0.25),("rare",0.10)]},
    {"min_hours":24,  "max_hours":72,  "gold":1000, "exp":2000, "item_chances":[("uncommon",0.40),("rare",0.20),("epic",0.05)]},
    {"min_hours":72,  "max_hours":168, "gold":2500, "exp":5000, "item_chances":[("rare",0.50),("epic",0.15),("legendary",0.02)]},
    {"min_hours":168, "max_hours":9999,"gold":5000, "exp":10000,"item_chances":[("rare",0.60),("epic",0.25),("legendary",0.05)]},
]

IDLE_FLAVOR = {
    "warrior":  "blade still sharp from distant battles",
    "mage":     "robes dusty from arcane research",
    "thief":    "pockets suspiciously full",
    "archer":   "quiver restocked from the wilds",
    "priest":   "returning from a holy pilgrimage",
    None:       "returning from a long journey",
}

# ── DUNGEON CONSTANTS ─────────────────────────────────────────────────────────
DUNGEON_THEMES = [
    {
        "name": "The Sunken Hall",
        "desc": "Ancient ruins reclaimed by groundwater. The stone is still level.",
        "enemy_prefix": ["Drowned","Waterlogged","Barnacled","Tide-Cursed"],
        "trap_flavor": ["a pressure plate beneath inches of dark water",
                        "a rusted portcullis rigged to drop",
                        "flooding pipes hidden in the walls",
                        "a current strong enough to sweep you into the dark"],
        "room_flavor": ["The walls weep saltwater.",
                        "Somewhere deeper, water drips in an endless rhythm.",
                        "The floor is slick and cold beneath your feet.",
                        "Pale fish dart through cracks in the stone."],
        "boss_name": "The Dungeon Lord",
        "boss_desc": "He ruled this place for forty years. It sank with him. He didn't leave.",
    },
    {
        "name": "The Burned Chamber",
        "desc": "A sealed chamber that caught fire mid-battle. The fight was never finished.",
        "enemy_prefix": ["Charred","Cinder","Smoldering","Ash-Born"],
        "trap_flavor": ["jets of flame erupting from the floor",
                        "a tripwire connected to a wall of fire",
                        "superheated air that burns the lungs",
                        "pools of liquid fire hidden under gray ash"],
        "room_flavor": ["The air smells of old smoke and older death.",
                        "Gray ash coats every surface like fresh snow.",
                        "The heat is oppressive and constant.",
                        "Blackened bones line the walls in neat rows."],
        "boss_name": "The Burned Out Champion",
        "boss_desc": "Won everything there was to win. Then the sanctum fell. Now he wanders the ash.",
    },
    {
        "name": "The Abandoned Sanctum",
        "desc": "Sealed without notice. Locked from the outside. Nobody knows why.",
        "enemy_prefix": ["Spectral","Siege-Cursed","Hollow","Battleborn"],
        "trap_flavor": ["a crossbow mounted to the wall still loaded",
                        "a floor section rigged to collapse into darkness",
                        "old siege oil that ignites on contact with air",
                        "a portcullis that slams without warning"],
        "room_flavor": ["Weapons still hang on the walls, rusted but intact.",
                        "The echoes of a battle that ended centuries ago linger here.",
                        "Banners hang in tatters from the vaulted ceiling.",
                        "Arrow shafts protrude from every wooden surface."],
        "boss_name": "The Tournament Director",
        "boss_desc": "Ran the last tournament held here. Still calling the shots. Nobody's listening.",
    },
    {
        "name": "The Shadow Maze",
        "desc": "A hall built of illusion and shadow. The layout changes. The exits don't stay put.",
        "enemy_prefix": ["Vine-Choked","Root-Twisted","Spore-Touched","Feral"],
        "trap_flavor": ["carnivorous vines dropping from the ceiling",
                        "spore clouds that cloud the mind",
                        "root systems that erupt from the floor",
                        "a pit concealed beneath a carpet of living moss"],
        "room_flavor": ["The stone is barely visible beneath layers of growth.",
                        "Something breathes here. You can feel it.",
                        "Bioluminescent fungi cast everything in pale blue light.",
                        "The labyrinth shifts  -  the walls have moved since you passed them."],
        "boss_name": "The Maze Itself",
        "boss_desc": "The labyrinth stopped being stone a long time ago. It has will now.",
    },
    {
        "name": "The Fractured Vault",
        "desc": "Every artifact here is cracked or shattered. They still hum with power. Nobody knows why.",
        "enemy_prefix": ["Fractured","Void-Touched","Rift-Born","Unbound"],
        "trap_flavor": ["unstable arcane nodes that discharge on proximity",
                        "a rift in space that pulls at anything nearby",
                        "gravity inverting without warning",
                        "time distortions that age you rapidly then snap back"],
        "room_flavor": ["Reality here is thin. You can see through the walls to somewhere else.",
                        "Books orbit the ceiling slowly, still open to their last page.",
                        "The floor is translucent. Something massive moves beneath it.",
                        "You hear conversations that happened in this room long ago."],
        "boss_name": "The Corrupted Codex",
        "boss_desc": "Someone rewrote the laws of this place. The vault accepted them. This is the result.",
    },
    {
        "name": "The Deep Vaults",
        "desc": "Below the main level. No windows. No clock. The fighting never stops down here.",
        "enemy_prefix": ["Clockwork","Steam-Wreathed","Corroded","Iron-Boned"],
        "trap_flavor": ["gears that engage and crush without warning",
                        "steam vents at scalding pressure",
                        "a conveyor that leads into grinding machinery",
                        "magnetic floors that snatch weapons from your grip"],
        "room_flavor": ["The machines have no purpose anyone can identify. They run anyway.",
                        "Steam fills every corridor at knee height.",
                        "The noise is constant. You stop being able to hear yourself think.",
                        "Pipes sweat rust-colored water onto everything."],
        "boss_name": "The Iron Construct",
        "boss_desc": "Built to destroy without reason or pause. It has no interest in who wins.",
    },
    {
        "name": "The White Cloth Wastes",
        "desc": "The cloth here is pure white and stretches in every direction. No rails. No pockets.",
        "enemy_prefix": ["Frost-Bitten","Glacial","Ice-Forged","Pale"],
        "trap_flavor": ["ice sheets that shatter into razor shards underfoot",
                        "a wind corridor that freezes exposed skin instantly",
                        "hidden crevasses disguised by snow",
                        "stalactites rigged to drop by vibration"],
        "room_flavor": ["Your breath fogs in great white clouds.",
                        "Something is preserved in the ice wall. It looks back.",
                        "The silence here is total and wrong.",
                        "The cold has a weight to it, like it's alive."],
        "boss_name": "The Cold Stroke Master",
        "boss_desc": "Never rushes. Never reacts. Cold as stone. Hits harder for it.",
    },
    {
        "name": "The Crimson Sanctum",
        "desc": "Red stone from floor to ceiling. The passages are real. So is whatever guards them.",
        "enemy_prefix": ["Corrupted","Tainted","Blasphemous","Hollow-Faithful"],
        "trap_flavor": ["consecrated ground that burns the faithless",
                        "a bell toll that shatters concentration and causes damage",
                        "an altar that demands tribute in HP",
                        "holy water turned acidic in the corruption"],
        "room_flavor": ["The prayers carved in the walls have been scratched out and replaced.",
                        "Candles burn black here.",
                        "The geometry of this place does not match what a sane architect would build.",
                        "You feel watched by something that disapproves of you deeply."],
        "boss_name": "The Disqualified Champion",
        "boss_desc": "Won the championship. Got disqualified on a technicality. Never accepted it.",
    },
]

DUNGEON_LOOT = {
    "normal": {
        "monster":   [("Health Potion",0.30),("Iron Shard",0.12),
                      ("Rusty Shiv",0.08),("Wooden Prayer Beads",0.08)],
        "treasure":  [("Greater Health Potion",0.20),("Iron Shard",0.20),
                      ("Silk Band",0.08),("Bloodstone Band",0.08),
                      ("Iron Broadsword",0.06)],
        "mini_boss": [("Iron Shard",0.40),("Enchanting Scroll",0.10),
                      ("Grand Restorative Flask",0.15),("Fortune Coin",0.06)],
        "boss":      [("Iron Shard",0.50),("Enchanting Scroll",0.20),
                      ("Scroll of Revival",0.10),("War Master's Clasp",0.05)],
        "completion_bonus": {"exp": 800, "gold": 200},
    },
    "hard": {
        "monster":   [("Greater Health Potion",0.15),("Iron Shard",0.20),
                      ("Mushroom Tip Blade",0.07),("Iron Broadsword",0.07)],
        "treasure":  [("Iron Shard",0.30),("Enchanting Scroll",0.15),
                      ("Grand Restorative Flask",0.10),("Fortune Coin",0.07),
                      ("War Master's Clasp",0.05),("Hawk Eye Medallion",0.05)],
        "mini_boss": [("Iron Shard",0.50),("Enchanting Scroll",0.25),
                      ("Scroll of Revival",0.10),("Steel Knight Sword",0.05)],
        "boss":      [("Iron Shard",0.60),("Enchanting Scroll",0.30),
                      ("Scroll of Revival",0.15),("Warlord's Edge",0.04),
                      ("Void Channel Staff",0.04),("Twin Strike Ring",0.04)],
        "completion_bonus": {"exp": 1800, "gold": 450},
    },
    "legendary": {
        "monster":   [("Iron Shard",0.30),("Enchanting Scroll",0.10),
                      ("Grand Restorative Flask",0.12),("Scroll of Revival",0.05)],
        "treasure":  [("Iron Shard",0.40),("Enchanting Scroll",0.25),
                      ("Scroll of Revival",0.12),("Runed Heart",0.05),
                      ("The Shadow Whisper",0.04),("Eye of the Void",0.04)],
        "mini_boss": [("Iron Shard",0.60),("Enchanting Scroll",0.35),
                      ("Warlord's Edge",0.05),("Void-Touched Robe",0.05),
                      ("Twin Strike Ring",0.05)],
        "boss":      [("Iron Shard",0.70),("Enchanting Scroll",0.40),
                      ("Ruinblade",0.02),("The Mind's Eye",0.02),
                      ("Shard of the Void",0.02),("The Last Stand Locket",0.02),
                      ("Ring of the Endless",0.02)],
        "completion_bonus": {"exp": 4000, "gold": 1000},
    },
}

ROOM_STAT_CHECKS = {
    "monster":  {"primary": "combat_power", "threshold": 0.65},
    "trap":     {"primary": "AGI", "secondary": "DEX", "threshold": 0.55,
                 "class_bonus": {"thief": 0.20, "archer": 0.15}},
    "treasure": {"primary": "LUK", "threshold": 0.50,
                 "class_bonus": {"thief": 0.15}},
    "puzzle":   {"primary": "INT", "secondary": "WIS", "threshold": 0.55,
                 "class_bonus": {"mage": 0.20, "priest": 0.15}},
    "rest":     {"primary": "WIS", "threshold": 0.60},
    "merchant": {"primary": "LUK"},
    "altar":    {"primary": "WIS", "threshold": 0.60,
                 "class_bonus": {"priest": 0.40}},
    "ambush":   {"primary": "AGI", "threshold": 0.55,
                 "class_bonus": {"archer": 0.25, "thief": 0.20}},
    "mini_boss":{"primary": "combat_power", "threshold": 0.55},
    "boss":     {"primary": "combat_power", "threshold": 0.50},
}

KEYWORD_TRIGGERS = [
    {"pattern":r"\b(8ball|8ballin|rack|felt|cue|billiards|pool table|corner pocket|break shot|chalk up)\b",
     "exp":60,"gold_chance":0.30,"cooldown":45,"key":"billiards"},
    {"pattern":r"🎱","exp":100,"gold_chance":0.20,"cooldown":300,"key":"8ball_emoji"},
    {"pattern":r"\b(hello|hi|hey|sup|what'?s up|wassup|yo|heya|hiya|howdy)\b",
     "exp":30,"gold_chance":0.10,"cooldown":30,"key":"greet"},
    {"pattern":r"\b(good morning|gm|good night|gn|good evening|good afternoon)\b",
     "exp":35,"gold_chance":0.10,"cooldown":30,"key":"greeting_time"},
    {"pattern":r"\b(lol|lmao|lmfao|haha|hahaha|funny|dead|💀|😂|🤣|bruh|bro|fam)\b",
     "exp":20,"gold_chance":0.05,"cooldown":45,"key":"humor"},
    {"pattern":r"\b(omg|oh my god|no way|wtf|wth|damn|dang|sheesh|fr fr|facts|bet)\b",
     "exp":20,"gold_chance":0.05,"cooldown":40,"key":"reaction"},
    {"pattern":r"\b(thanks|thank you|ty|thx|cheers|appreciated|grateful|respect)\b",
     "exp":35,"gold_chance":0.10,"cooldown":60,"key":"gratitude"},
    {"pattern":r"\b(nice|great|awesome|amazing|sick|fire|goated|legendary|insane|clean)\b",
     "exp":20,"gold_chance":0.05,"cooldown":40,"key":"hype"},
    {"pattern":r"\b(win|won|victory|gg|good game|let'?s go|lets go|dub|clutch|carry)\b",
     "exp":35,"gold_chance":0.10,"cooldown":50,"key":"win"},
    {"pattern":r"\b(grind|grinding|leveling|farm|farming|rank up|ranked)\b",
     "exp":20,"gold_chance":0.05,"cooldown":90,"key":"grind"},
    {"pattern":r"\b(food|eat|eating|hungry|snack|lunch|dinner|breakfast|meal|cook)\b",
     "exp":20,"gold_chance":0.05,"cooldown":45,"key":"food"},
    {"pattern":r"\b(work|working|job|office|meeting|shift|hustle)\b",
     "exp":20,"gold_chance":0.05,"cooldown":60,"key":"work"},
    {"pattern":r"\b(music|song|track|album|artist|rapper|beat|vibes|playlist|banger)\b",
     "exp":20,"gold_chance":0.05,"cooldown":60,"key":"music"},
    {"pattern":r"\b(football|soccer|basketball|tennis|gym|workout|run|running|lift)\b",
     "exp":20,"gold_chance":0.05,"cooldown":60,"key":"sports"},
    {"pattern":r"\b(friend|friends|bro|sis|brother|sister|mate|homie|squad|crew|family)\b",
     "exp":20,"gold_chance":0.05,"cooldown":50,"key":"social"},
    {"pattern":r"\b(dragon|magic|spell|quest|wizard|warrior|dungeon|boss|raid|sword|shield|potion|knight)\b",
     "exp":30,"gold_chance":0.05,"cooldown":90,"key":"fantasy"},
    {"pattern":r".","exp":8,"gold_chance":0.02,"cooldown":10,"key":"passive_trickle"},
]

EASTER_EGGS = [
    {"pattern":r"\b(from beyond the pocket|void calls)\b","exp":0,"gold":0,"secret_boss":True},
]

# ── STATUS EFFECT CHECKERS ────────────────────────────────────────────────────
def _ts_active(p, key):
    ts = p.get(key)
    if not ts: return False
    try: return datetime.now() < datetime.fromisoformat(ts)
    except: return False

def is_defeated(p):
    if p.get("hp", 1) > 0: return False
    return _ts_active(p, "defeated_until")

def is_invincible(p):    return _ts_active(p, "invincible_until")
def is_distracted(p):    return _ts_active(p, "distracted_until")
def is_entangled(p):     return _ts_active(p, "entangled_until")
def is_frozen(p):        return _ts_active(p, "frozen_until")
def is_stunned(p):       return _ts_active(p, "stunned_until")
def is_vanished(p):      return _ts_active(p, "vanish_until")
def is_bleeding(p):      return _ts_active(p, "bleed_until")
def is_hexed(p):         return _ts_active(p, "hexed_until")
def is_blessed(p):       return _ts_active(p, "blessed_until")
def is_weakened(p):      return _ts_active(p, "weakened_until")
def is_healing_blocked(p): return _ts_active(p, "healing_blocked_until")
def is_revival_blocked(p): return _ts_active(p, "revival_blocked_until")
def is_silenced(p):      return _ts_active(p, "silenced_until")
def is_rooted(p):        return is_entangled(p) or is_frozen(p)
def cannot_attack(p):    return is_stunned(p) or is_rooted(p) or is_vanished(p)
def is_poisoned(p): return _ts_active(p, "poison_until")
def is_burning(p):  return _ts_active(p, "burn_until")
def has_ward(p):    return _ts_active(p, "ward_until")
def is_exposed(p):  return _ts_active(p, "exposed_until")
def is_branded(p):  return _ts_active(p, "branded_until")
def is_marked(p):   return _ts_active(p, "marked_until")

def check_cooldown(ts, secs):
    if not ts: return True
    try: return datetime.now() > datetime.fromisoformat(ts) + timedelta(seconds=secs)
    except: return True

def time_remaining(ts, secs):
    if not ts: return "Ready!"
    try:
        end  = datetime.fromisoformat(ts) + timedelta(seconds=secs)
        diff = end - datetime.now()
        if diff.total_seconds() <= 0: return "Ready!"
        m, s = divmod(int(diff.total_seconds()), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h}h {m}m"
        if m > 0: return f"{m}m {s}s"
        return f"{s}s"
    except: return "Ready!"

def time_until(ts):
    """Format time remaining until a target timestamp (e.g. defeated_until)."""
    if not ts: return None
    try:
        diff = datetime.fromisoformat(ts) - datetime.now()
        if diff.total_seconds() <= 0: return None
        m, s = divmod(int(diff.total_seconds()), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h}h {m}m"
        if m > 0: return f"{m}m {s}s"
        return f"{s}s"
    except: return None

def set_status(p, key, duration_seconds):
    p[key] = (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()

def get_active_statuses(p):
    statuses = []
    if is_distracted(p):      statuses.append("😵 Disoriented (30% miss)")
    if is_entangled(p):       statuses.append("🌿 Rooted (can't attack)")
    if is_frozen(p):          statuses.append("🧊 Frozen Solid (can't attack)")
    if is_stunned(p):         statuses.append("⚡ Stunned (miss next attack)")
    if is_vanished(p):        statuses.append("👻 Vanished (untargetable)")
    if is_poisoned(p):    statuses.append(f"🐍 Poisoned ({p.get('poison_damage',6)} dmg/30s)")
    if is_burning(p):     statuses.append(f"🔥 Burning ({p.get('burn_damage',8)} dmg/20s)")
    if has_ward(p):       statuses.append("✨ Warded (next hit -40%)")
    if is_exposed(p):     statuses.append("🗡️ Exposed (+15% dmg taken)")
    if is_branded(p):     statuses.append("🔥 Branded (next attack -30%)")
    if is_marked(p):      statuses.append("🎯 Marked for Death (+20% dmg taken)")
    if is_bleeding(p):        statuses.append(f"🩸 Draw Bleed ({p.get('bleed_damage',10)} dmg/30s)")
    if is_hexed(p):           statuses.append("💀 Hooked (-25% damage)")
    if is_blessed(p):         statuses.append("✨ In Stroke (+10% all stats)")
    if is_weakened(p):        statuses.append("💔 Weakened (+25% dmg taken)")
    if is_healing_blocked(p): statuses.append("🚫 No Revival")
    if is_revival_blocked(p): statuses.append("☠️ Condemned (Verdict's Call)")
    if is_silenced(p):        statuses.append("🤐 Frozen Stroke (no skills)")
    if is_invincible(p):      statuses.append("🛡️ Still Recovering (Invincible)")
    return statuses

# ── GEAR HELPERS ──────────────────────────────────────────────────────────────
def get_equipped_weapon(p):
    name = p.get("equipped_weapon")
    if not name: return None
    return WEAPONS.get(name)

def get_equipped_armor(p):
    name = p.get("equipped_armor")
    if not name: return None
    return ARMORS.get(name)

def get_equipped_shield(p):
    name = p.get("equipped_shield")
    if not name: return None
    return SHIELDS.get(name)

def get_equipped_accessory(p):
    name = p.get("equipped_accessory")
    if not name: return None
    return ACCESSORIES.get(name)

def get_enchant(p, item_name):
    raw = sjl(p.get("enchants"), {}).get(item_name)
    if raw is None: return []
    if isinstance(raw, dict): return [raw]
    if isinstance(raw, list): return raw
    return []

def get_all_enchants(p, item_name):
    return get_enchant(p, item_name)

def set_enchant(p, item_name, effect):
    enchants = sjl(p.get("enchants"), {})
    current = enchants.get(item_name, [])
    if isinstance(current, dict):
        current = [current]
    current = [e for e in current if e.get("id") != effect.get("id")]
    current.append(effect)
    if len(current) > 3:
        current = current[-3:]
    enchants[item_name] = current
    p["enchants"] = json.dumps(enchants)

def get_enchant_bonus(p, stat):
    total = 0
    for slot_key in ["equipped_weapon","equipped_armor",
                      "equipped_shield","equipped_accessory"]:
        name = p.get(slot_key)
        if not name: continue
        for enchant in get_enchant(p, name):
            if enchant.get("type") == stat:
                total += enchant.get("val", 0)
    return total

def get_enhancement(p, item_name):
    return sjl(p.get("enhancements"), {}).get(item_name, 0)

def set_enhancement(p, item_name, level):
    enh = sjl(p.get("enhancements"), {})
    enh[item_name] = level
    p["enhancements"] = json.dumps(enh)

def get_enhance_bonus(p, item_name):
    return get_enhancement(p, item_name) * 2

# ── REINFORCE HELPERS ─────────────────────────────────────────────────────────
def get_reinforce_data(p):
    return json.loads(p.get("item_reinforce_data") or "{}")

def set_reinforce_data(p, data):
    p["item_reinforce_data"] = json.dumps(data)

def get_item_reinforce(p, item_name):
    if not item_name: return {"r": 0, "s": 0}
    return get_reinforce_data(p).get(item_name, {"r": 0, "s": 0})

def star_str(s):
    return ("★" * s + "☆" * (3 - s)) if s < 3 else "★★★"

def reinforce_atk_bonus(p, item_name):
    if not item_name: return 0
    d = get_item_reinforce(p, item_name)
    return d["r"] + d["s"] * 5

# ── ITEM SET HELPERS ───────────────────────────────────────────────────────────
def get_active_set_bonuses(p):
    equipped = {p.get("equipped_weapon"), p.get("equipped_armor"),
                p.get("equipped_shield"), p.get("equipped_accessory")}
    equipped.discard(None)
    bonuses = {}; active_sets = []
    for set_name, data in ITEM_SETS.items():
        if set(data["pieces"]).issubset(equipped):
            active_sets.append(set_name)
            for stat, val in data["bonus"].items():
                bonuses[stat] = bonuses.get(stat, 0) + val
    return bonuses, active_sets

# ── DAILY OBJECTIVE HELPERS ────────────────────────────────────────────────────
def refresh_daily_objectives(p):
    today = datetime.now().strftime("%Y-%m-%d")
    if p.get("daily_obj_date") == today:
        return
    selected = random.sample(DAILY_QUEST_POOL, min(3, len(DAILY_QUEST_POOL)))
    objs = []
    for q in selected:
        tier = random.randint(0, 2)
        target = q["targets"][tier]
        objs.append({
            "id":          q["id"],
            "desc":        q["desc"].format(n=target),
            "progress":    0,
            "target":      target,
            "reward_exp":  q["exp"][tier],
            "reward_gold": q["gold"][tier],
            "done":        False,
        })
    p["daily_objectives"] = json.dumps(objs)
    p["daily_obj_date"]   = today

def track_objective(p, obj_id, amount=1):
    """Increment objective progress. Returns list of (desc, exp, gold) for newly completed ones."""
    refresh_daily_objectives(p)
    objs = json.loads(p.get("daily_objectives") or "[]")
    completed = []
    for obj in objs:
        if obj["id"] == obj_id and not obj.get("done"):
            obj["progress"] = min(obj["progress"] + amount, obj["target"])
            if obj["progress"] >= obj["target"]:
                obj["done"] = True
                completed.append((obj["desc"], obj["reward_exp"], obj["reward_gold"]))
    p["daily_objectives"] = json.dumps(objs)
    if completed:
        p["total_obj_completed"] = safe_int(p.get("total_obj_completed")) + len(completed)
    return completed

def get_weapon_atk(p):
    w = get_equipped_weapon(p)
    if not w: return 0
    name = p.get("equipped_weapon")
    base = w["atk"] + get_enhance_bonus(p, name) + reinforce_atk_bonus(p, name)
    for enchant in get_enchant(p, name):
        if enchant.get("type") == "flat_dmg":
            base += enchant["val"]
        if enchant.get("type") == "atk":
            base += enchant["val"]
    return base

def get_armor_def(p):
    a = get_equipped_armor(p); s = get_equipped_shield(p)
    a_name = p.get("equipped_armor"); s_name = p.get("equipped_shield")
    a_val = (a["def"] + get_enhance_bonus(p, a_name) + reinforce_atk_bonus(p, a_name)) if a else 0
    s_val = (s["def"] + get_enhance_bonus(p, s_name) + reinforce_atk_bonus(p, s_name)) if s else 0
    for enc in (get_enchant(p, a_name) if a_name else []):
        if enc.get("type") == "armor_def": a_val += enc["val"]
    for enc in (get_enchant(p, s_name) if s_name else []):
        if enc.get("type") == "armor_def": s_val += enc["val"]
    return a_val + s_val

def gear_line(p, slot_key):
    """Return a display string for an equipped item slot with reinforce, +enh and ✨enchant tags."""
    name = p.get(slot_key)
    if not name:
        return "None"
    enh   = get_enhancement(p, name)
    encs  = get_enchant(p, name)
    rd    = get_item_reinforce(p, name)
    parts = [name]
    if rd["s"] > 0 or rd["r"] > 0:
        parts.append(star_str(rd["s"]))
        if rd["r"] > 0: parts.append(f"[{rd['r']}/20]")
    if enh:
        parts.append(f"+{enh}")
    if encs:
        parts.append(f"✨×{len(encs)}")
    return " ".join(parts)

def get_accessory_bonus(p, stat):
    acc = get_equipped_accessory(p)
    if not acc: return 0
    effect = acc.get("effect", {})

    # Direct stat match
    if stat in effect:
        return effect[stat]

    # all_stats applies to every stat
    if stat in ("STR","DEF","AGI","INT","WIS","DEX","LUK") and "all_stats" in effect:
        return effect["all_stats"]

    # primary_stat  -  applies only to the player's primary class stat
    if "primary_stat" in effect:
        primary = get_primary_stat(p)
        if stat == primary:
            return effect["primary_stat"]

    return 0

# Maps new class lines → existing gear category so they can use shared weapon/armor pools
_GEAR_LINE_MAP = {
    "botanist":       "mage",
    "enchantress":    "mage",
    "valkyrie":       "warrior",
    "phantom_dancer": "thief",
}

def can_equip_weapon(p, weapon_name):
    w = WEAPONS.get(weapon_name)
    if not w: return False, "Unknown weapon."
    cls_id = p.get("class_id")
    if not cls_id: return False, "Choose a class first."
    cls_data = CLASS_TREE.get(cls_id, {})
    raw_line   = cls_data.get("line", "")
    gear_line  = _GEAR_LINE_MAP.get(raw_line, raw_line)
    weapon_class = w.get("class")
    if weapon_class != gear_line:
        return False, f"Only {weapon_class.capitalize()} classes can use this."
    weapon_type = w.get("type")
    allowed = cls_data.get("weapon_types", [])
    if weapon_type not in allowed:
        path = p.get("class_path","")
        return False, (f"Your current class ({cls_data['name']}) cannot use "
                       f"{weapon_type} weapons. "
                       f"{'Path A uses one-handed weapons.' if path == 'A' else 'Path B uses two-handed weapons.'}")
    return True, ""

def can_equip_armor(p, armor_name):
    a = ARMORS.get(armor_name)
    if not a: return False, "Unknown armor."
    cls_id   = get_player_class_id(p)
    cls_data = CLASS_TREE.get(cls_id, {})
    raw_line  = cls_data.get("line", "")
    gear_line = _GEAR_LINE_MAP.get(raw_line, raw_line)
    if a.get("class") and a["class"] != gear_line:
        return False, f"Only {a['class'].capitalize()} classes can wear this."
    return True, ""

def get_player_class_id(p):
    return p.get("class_id")

def get_player_class(p):
    cid = p.get("class_id")
    if not cid: return None
    return CLASS_TREE.get(cid)

def get_class_line(p):
    cls = get_player_class(p)
    if not cls: return None
    return cls.get("line")

def get_primary_stat(p):
    cls = get_player_class(p)
    if not cls: return "STR"
    return cls.get("primary_stat", "STR")

def get_all_skills(p):
    """Return all skills unlocked by player across all class tiers."""
    return sjl(p.get("all_skills"), [])

def get_class_path(p):
    return p.get("class_path")  # "A" or "B" or None

# ── STAT & DAMAGE CALCULATIONS ────────────────────────────────────────────────
def get_stat(p, stat):
    defaults = {"STR":5,"DEF":0,"AGI":5,"INT":5,"WIS":5,"DEX":5,"LUK":5}
    base  = safe_stats(p).get(stat, defaults.get(stat, 5))
    acc   = get_accessory_bonus(p, stat)
    all_s = get_accessory_bonus(p, "all_stats")
    blessed_bonus = 1 if is_blessed(p) else 0
    # Active title bonus
    active_title = p.get("active_title", "")
    title_bonus_dict = TITLE_BONUSES.get(active_title, {})
    title_bonus = title_bonus_dict.get(stat, 0)
    all_title = title_bonus_dict.get("all_stats", 0)
    # Item set bonus
    set_bonuses, _ = get_active_set_bonuses(p)
    set_stat  = set_bonuses.get(stat, 0)
    set_all   = set_bonuses.get("all_stats", 0)
    if stat in ("STR","AGI","INT","WIS","DEX","LUK"):
        return base + acc + all_s + blessed_bonus + title_bonus + all_title + set_stat + set_all
    return base + acc + all_s + blessed_bonus

def calc_max_hp(p):
    base   = max_hp_for_level(p["level"])
    acc_hp = get_accessory_bonus(p, "hp")
    enc_hp = get_enchant_bonus(p, "max_hp")
    temp   = safe_int(p.get("temp_hp_bonus")) if _ts_active(p, "temp_hp_until") else 0
    set_bonuses, _ = get_active_set_bonuses(p)
    set_hp = set_bonuses.get("hp", 0)
    return base + acc_hp + enc_hp + temp + set_hp

TIER_THRESHOLDS = {1: 5, 2: 10, 3: 30, 4: 60, 5: 100}
 
def get_class_tier(p):
    """Return current class tier 1-5 based on unlock level."""
    cls = get_player_class(p)
    if not cls: return 0
    unlock = cls.get("skills", [{}])[0].get("unlock", 5)
    for tier, lvl in sorted(TIER_THRESHOLDS.items(), reverse=True):
        if unlock >= lvl: return tier
    return 1
 
def get_proc_chance(base_pct, p):
    """Return proc chance scaled by class tier."""
    tier = get_class_tier(p)
    return base_pct + (tier * 0.03)
 
def calc_proc_effect(attacker, defender, dmg):
    """
    Roll for class-specific proc on normal /attack.
    Returns (proc_triggered, proc_message, extra_dmg).
    Mutates attacker/defender state if proc fires.
    """
    cls = get_player_class(attacker)
    if not cls: return False, "", 0
 
    line = cls.get("line")
    path = attacker.get("class_path")
    now  = datetime.now()
 
    # ── WARRIOR PATH A  -  Blessed Strike ──────────────────────
    if line == "warrior" and path == "A":
        chance = get_proc_chance(0.10, attacker)
        if random.random() < chance:
            defender["burn_until"]  = (now + timedelta(minutes=3)).isoformat()
            defender["burn_damage"] = 10
            return True, "⚔️ *Blessed Strike!* Holy fire ignites  -  10 dmg/30s!", 0
 
    # ── WARRIOR PATH B  -  Double Strike ───────────────────────
    elif line == "warrior" and path == "B":
        chance = get_proc_chance(0.15, attacker)
        if random.random() < chance:
            extra = round(dmg * 0.60)
            extra = calc_defense(defender, extra)
            defender["hp"] = max(0, defender["hp"] - extra)
            return True, f"⚔️ *Double Strike!* A second blow lands for {extra} dmg!", extra
 
    # ── MAGE PATH A  -  Arcane Burn ─────────────────────────────
    elif line == "mage" and path == "A":
        chance = get_proc_chance(0.12, attacker)
        if random.random() < chance:
            defender["burn_until"]  = (now + timedelta(seconds=80)).isoformat()
            defender["burn_damage"] = 8
            return True, "🔥 *Arcane Burn!* Magical fire clings to the wound!", 0
 
    # ── MAGE PATH B  -  Soul Drain ──────────────────────────────
    elif line == "mage" and path == "B":
        chance = get_proc_chance(0.12, attacker)
        if random.random() < chance:
            steal = round(dmg * 0.50)
            attacker["hp"] = min(calc_max_hp(attacker), attacker["hp"] + steal)
            return True, f"🌑 *Soul Drain!* Stole {steal} HP from the wound!", 0
 
    # ── THIEF PATH A  -  Poison Strike ─────────────────────────
    elif line == "thief" and path == "A":
        chance = get_proc_chance(0.15, attacker)
        if random.random() < chance:
            defender["poison_until"]  = (now + timedelta(minutes=5)).isoformat()
            defender["poison_damage"] = 6
            return True, "🐍 *Poison Strike!* The blade was coated in poison!", 0
 
    # ── THIEF PATH B  -  Exposed ────────────────────────────────
    elif line == "thief" and path == "B":
        chance = get_proc_chance(0.15, attacker)
        if random.random() < chance:
            defender["exposed_until"] = (now + timedelta(minutes=2)).isoformat()
            return True, "🗡️ *Exposed!* A vital point was struck  -  +15% dmg taken!", 0
 
    # ── ARCHER PATH A  -  Pin Down ──────────────────────────────
    elif line == "archer" and path == "A":
        chance = get_proc_chance(0.12, attacker)
        if random.random() < chance:
            defender["distracted_until"] = (now + timedelta(seconds=30)).isoformat()
            return True, "🏹 *Pin Down!* The arrow grazes their shoulder  -  distracted!", 0
 
    # ── ARCHER PATH B  -  Headshot ──────────────────────────────
    elif line == "archer" and path == "B":
        chance = get_proc_chance(0.12, attacker)
        if random.random() < chance:
            extra = round(dmg * 0.75)  # total becomes 1.75x
            extra = calc_defense(defender, extra)
            defender["hp"] = max(0, defender["hp"] - extra)
            return True, f"🎯 *Headshot!* Clean hit for {extra} bonus dmg!", extra
 
    # ── PRIEST PATH A  -  Holy Ward (on attack) ────────────────
    elif line == "priest" and path == "A":
        chance = get_proc_chance(0.20, attacker)
        if random.random() < chance:
            attacker["ward_until"] = (now + timedelta(minutes=2)).isoformat()
            return True, "✨ *Holy Ward!* Divine light shields the faithful!", 0
 
    # ── PRIEST PATH B  -  Holy Brand ────────────────────────────
    elif line == "priest" and path == "B":
        chance = get_proc_chance(0.15, attacker)
        if random.random() < chance:
            defender["branded_until"] = (now + timedelta(minutes=2)).isoformat()
            return True, "🔥 *Holy Brand!* Branded by judgment  -  next attack weakened!", 0
 
    return False, "", 0

def calc_attack_damage(attacker, weather=None):
    base      = random.randint(1, 10)
    weapon    = get_weapon_atk(attacker)
    perm      = safe_int(attacker.get("perm_dmg_bonus"))
    acc_atk   = get_accessory_bonus(attacker, "atk")
    acc_atk  += get_enchant_bonus(attacker, "atk")
    acc_atk  += get_enchant_bonus(attacker, "flat_dmg")
    stats     = safe_stats(attacker)
    primary   = get_primary_stat(attacker)
    stat_val  = get_stat(attacker, primary)
    stat_bonus = stat_val // 2
    level_bonus = attacker["level"] // 2
    dex_val   = get_stat(attacker, "DEX")
    luk_val   = get_stat(attacker, "LUK")
    dex_bonus = dex_val // 3
    luk_bonus = luk_val // 5

    raw = base + weapon + perm + acc_atk + stat_bonus + level_bonus + dex_bonus + luk_bonus

    # Weather
    if weather: raw = round(raw * weather.get("dmg_mod", 1.0))

    # Buffs
    buff_mod = 1.0
    if is_blessed(attacker):        buff_mod += 0.10
    if is_weakened(attacker):       buff_mod -= 0.25

    # Passive class bonuses that add to damage
    cls = get_player_class(attacker)
    if cls:
        pk = cls.get("passive_key","")
        if pk == "iron_will":       buff_mod += 0.00  # defense passive, no dmg
        if pk == "bloodlust":       pass  # handled in strike logic
        if pk == "warcry":
            recent = sjl(attacker.get("recent_attackers"), [])
            now = datetime.now()
            recent_30 = [r for r in recent
                         if (now - datetime.fromisoformat(r["ts"])).total_seconds() < 1800]
            if len(recent_30) > 1: buff_mod += 0.20
        if pk == "arcane_mind":     raw += get_stat(attacker, "INT")
        if pk == "soul_pact":       pass  # handled in lifesteal
        if pk == "bloodlust":       pass
        if pk == "marked":
            if attacker.get("mark_first_hit"):
                buff_mod += 0.25
        if pk == "steady_aim":
            stacks = safe_int(attacker.get("steady_aim_stacks"))
            buff_mod += min(0.50, stacks * 0.10)
        if pk == "dead_or_alive":
            extra = safe_int(attacker.get("deadeye_kill_bonus"))
            raw += extra
        # ── New class passives ─────────────────────────────────────────────
        # Botanist
        if pk == "natural_growth":  raw += get_stat(attacker, "WIS") * 0.15
        if pk == "thorn_aura":      raw += get_stat(attacker, "WIS") * 0.20
        if pk == "venomous_growth": buff_mod += 0.15
        if pk == "primal_fury":
            raw += get_stat(attacker, "WIS") * 0.25; buff_mod += 0.10
        if pk == "blossoming":      buff_mod += 0.05
        if pk == "eternal_bloom":   buff_mod += 0.10
        # Enchantress
        if pk == "hexmark":         buff_mod += 0.12
        if pk == "stacking_curses": buff_mod += 0.15
        if pk == "misery_aura":     raw += 10
        if pk == "empress_dread":   buff_mod += 0.20
        if pk == "harmonize":
            buff_mod += min(0.12, safe_int(attacker.get("harmony_stacks", 0)) * 0.04)
        if pk == "battle_hymn":     buff_mod += 0.05
        if pk == "muses_grace":     buff_mod += 0.20
        if pk == "lorekeeping":     buff_mod += 0.05
        # Valkyrie
        if pk == "einherjar_will":
            raw += get_stat(attacker, "STR") * 0.10
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.30: buff_mod += 0.40
        if pk == "thunder_step":
            if attacker.get("thunder_dodge_ready"):
                buff_mod += 0.40; attacker["thunder_dodge_ready"] = 0
        if pk == "storms_eye":      buff_mod += 0.05
        if pk == "celestial_wrath": buff_mod += 0.25
        if pk == "defenders_oath":
            buff_mod += min(0.30, safe_int(attacker.get("oath_stacks", 0)) * 0.10)
        if pk == "iron_bulwark":    buff_mod += 0.05
        # Phantom Dancer
        if pk == "waltz":
            if attacker.get("waltz_dodge_ready"):
                buff_mod += 0.60; attacker["waltz_dodge_ready"] = 0
        if pk == "rhythm":
            buff_mod += min(0.20, safe_int(attacker.get("rhythm_stacks", 0)) * 0.04)
        if pk == "flourish":
            buff_mod += min(0.15, safe_int(attacker.get("flourish_stacks", 0)) * 0.05)
        if pk == "adrenaline":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.30: buff_mod += 0.30
        if pk == "death_whirl":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.40: buff_mod += 0.30
        if pk == "final_performance":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.25: buff_mod += 0.50

    # Accessory low HP bonus
    if get_accessory_bonus(attacker, "low_hp_dmg_bonus"):
        hp_pct = attacker["hp"] / max(1, attacker["max_hp"])
        if hp_pct < 0.30:
            buff_mod += get_accessory_bonus(attacker, "low_hp_dmg_bonus")

    return max(1, round(raw * buff_mod))

def calc_defense(defender, dmg):
    stats      = safe_stats(defender)
    def_val    = get_stat(defender, "DEF")
    armor_def  = get_armor_def(defender)

    # Base reduction from DEF stat
    def_reduction  = min(0.50, (def_val / 10) * 0.07)
    # Armor adds flat reduction
    armor_reduction = min(0.20, armor_def / 300)

    # Passive class bonuses
    cls = get_player_class(defender)
    if cls:
        pk = cls.get("passive_key","")
        if pk == "iron_will":      def_reduction += 0.10
        if pk == "holy_stance":
            hp_pct = defender["hp"] / max(1, defender["max_hp"])
            if hp_pct < 0.50:      def_reduction += 0.15
        if pk == "natures_bond":   def_reduction += 0.10
        if pk == "guardian_stance": def_reduction += 0.05
        # New class passives
        if pk == "thorn_skin":     def_reduction += 0.10
        if pk == "eternal_bloom":  def_reduction += 0.15
        if pk == "lorekeeping":    def_reduction += 0.15
        if pk == "fog_of_war":     def_reduction += 0.10
        if pk == "iron_bulwark":   def_reduction += 0.20
        if pk == "einherjar_will": def_reduction += 0.05
        if pk == "shield_maiden":
            if defender["hp"] > defender.get("max_hp", defender["hp"]) * 0.50:
                def_reduction += 0.05
        if pk == "defenders_oath":
            if defender["hp"] < defender.get("max_hp", defender["hp"]) * 0.50:
                def_reduction += 0.10
        if pk == "immortal_aegis": def_reduction += 0.05
        if pk == "stalwart":
            if random.random() < 0.15: return 0
        if pk == "ancient_bark":
            if random.random() < 0.15: return 0
        if pk == "empress_dread":  def_reduction += 0.10

    # def_reflect active status — extra damage reduction
    if _ts_active(defender, "def_reflect_until"):
        def_reduction += 0.40

    # Accessory block chance (handled separately, this is just flat reduction)
    if get_accessory_bonus(defender, "block_chance"):
        if random.random() < get_accessory_bonus(defender, "block_chance"):
            return 0  # blocked entirely
    enc_block = get_enchant_bonus(defender, "block_chance")
    if enc_block and random.random() < enc_block:
        return 0

    total = min(0.80, def_reduction + armor_reduction)
    final = max(1, round(dmg * (1 - total)))
 
    # Exposed debuff  -  target takes +15% more damage
    if _ts_active(defender, "exposed_until"):
        final = round(final * 1.15)

    # Marked (Execution Order)  -  target takes +20% more damage
    if _ts_active(defender, "marked_until"):
        final = round(final * 1.20)

    # Branded  -  attacker's next strike deals 30% less (checked on attacker)
    if _ts_active(defender, "branded_until"):
        final = round(final * 0.70)
        defender["branded_until"] = None  # consumed on hit

    # Runic Ward — absorbs first 20 damage of every hit
    cls_def = get_player_class(defender)
    if cls_def and cls_def.get("passive_key") == "runic_ward":
        final = max(0, final - 20)

    return final

def apply_pvp_death(p, killer_name="the enemy", cause="PvP", killer_id=None):
    """Apply full PvP-style death: 6hr defeat, 10% EXP loss, losses++"""
    exp_loss = round(p.get("exp", 0) * 0.10)
    p["exp"]             = max(0, p.get("exp", 0) - exp_loss)
    p["hp"]              = 0
    p["losses"]          = p.get("losses", 0) + 1
    p["defeated_until"]  = (datetime.now() + timedelta(hours=6)).isoformat()
    p["last_defeated_by"] = f"{killer_name} ({cause})"
    p["kill_streak"]     = 0  # reset streak on death
    if killer_id:
        p["revenge_target"]  = killer_id
        p["revenge_expires"] = (datetime.now() + timedelta(hours=24)).isoformat()
    return exp_loss

def _defeated_msg(p):
    """Build a consistent 'you are defeated' message with countdown."""
    countdown = time_until(p.get("defeated_until"))
    cause     = p.get("last_defeated_by")
    msg = "💀 You're defeated!"
    if cause:  msg += f"\n☠️ Defeated by: _{cause}_"
    if countdown: msg += f"\n⏳ Back in: *{countdown}*"
    msg += "\n_Ask a Priest to revive you, or wait it out._"
    return msg

async def _notify_defeat(bot, p, cause_str):
    """DM the player letting them know what defeated them."""
    try:
        countdown = time_until(p.get("defeated_until")) or "6 hours"
        await bot.send_message(
            chat_id=p["user_id"],
            text=f"💀 You were defeated by *{cause_str}*!\n⏳ Back in: *{countdown}*\n_Use /heal or ask a Priest to get back sooner._",
            parse_mode="Markdown")
    except Exception:
        pass

async def _notify_attack(bot, victim, attacker_name, dmg):
    """DM the victim when attacked but not defeated."""
    try:
        hp_pct = round(victim["hp"] / max(1, victim.get("max_hp", victim["hp"])) * 100)
        await bot.send_message(
            chat_id=victim["user_id"],
            text=f"⚠️ *{attacker_name}* attacked you for *{dmg} damage!*\n"
                 f"❤️ HP: *{victim['hp']}/{victim.get('max_hp', victim['hp'])}* ({hp_pct}%)\n"
                 f"_Respond in the group chat!_",
            parse_mode="Markdown")
    except Exception:
        pass

async def check_and_claim_bounty(bot, attacker, target, chat_id=None):
    """Claim ALL active bounties on target (stacked from multiple players)."""
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; bc = conn.cursor()
    bc.execute("SELECT * FROM bounties WHERE target_id=? AND claimed_by IS NULL AND expires_at > ?",
               (target["user_id"], datetime.now().isoformat()))
    bounties = bc.fetchall()
    if not bounties:
        conn.close(); return 0

    RAILRUNNER_CLASSES = {"bounty_hunter", "sharpshooter", "sniper", "deadeye"}
    is_railrunner = attacker.get("class_id") in RAILRUNNER_CLASSES
    total_reward = 0
    bonus_msgs = []

    for bounty in bounties:
        bc.execute("UPDATE bounties SET claimed_by=? WHERE bounty_id=?",
                   (attacker["user_id"], bounty["bounty_id"]))
        reward     = bounty["reward"]
        self_placed = (bounty["placer_id"] == attacker["user_id"])
        if self_placed and is_railrunner:
            payout = reward + round(reward * 0.25)
            total_reward += payout
            bonus_msgs.append(f"🎯 Your own contract: *+{payout}g* (+25% self-collect!)")
        else:
            total_reward += reward
            if not self_placed:
                placer_p = get_player(bounty["placer_id"])
                if placer_p:
                    refund = round(reward * 0.25)
                    placer_p["gold"] = placer_p.get("gold", 0) + refund
                    save_player(placer_p)
                    try:
                        await bot.send_message(
                            chat_id=placer_p["user_id"],
                            text=f"💰 Your *{reward}g* bounty on *{target['username']}* was claimed!\n"
                                 f"You received *{refund}g* back.",
                            parse_mode="Markdown")
                    except Exception: pass

    conn.commit(); conn.close()
    attacker["gold"] = attacker.get("gold", 0) + total_reward
    save_player(attacker)

    bounty_count = len(bounties)
    stack_note = f" _(×{bounty_count} bounties stacked!)_" if bounty_count > 1 else ""
    try:
        if chat_id:
            await bot.send_message(
                chat_id=chat_id,
                text=f"💰 *BOUNTY CLAIMED!* *{attacker['username']}* defeated *{target['username']}*!\n"
                     f"*+{total_reward}g* collected!{stack_note} 🎯"
                     + ("\n" + "\n".join(bonus_msgs) if bonus_msgs else ""),
                parse_mode="Markdown")
    except Exception: pass
    try:
        await bot.send_message(
            chat_id=target["user_id"],
            text=f"🎯 The bounty on your head was collected by *{attacker['username']}*! Total: *{total_reward}g*",
            parse_mode="Markdown")
    except Exception: pass
    return total_reward

def in_active_raid(user_id, chat_id=None):
    """Returns (raid_dict, kind) where kind is 'solo', 'group', or None."""
    if user_id in active_soloraids:
        return active_soloraids[user_id], "solo"
    if chat_id is not None:
        raid = active_raids.get(chat_id)
        if raid and raid.get("in_progress"):
            if user_id in [u["id"] for u in raid["party"]]:
                return raid, "group"
    # Also search all group raids if no chat_id
    if chat_id is None:
        for cid, raid in active_raids.items():
            if raid.get("in_progress") and user_id in [u["id"] for u in raid["party"]]:
                return raid, "group"
    return None, None

def in_active_boss(user_id, chat_id=None):
    """Returns (boss_dict, chat_id) if player is in a boss fight, else (None, None)."""
    if chat_id is not None:
        bd = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
        if bd and user_id in [u["id"] for u in bd["participants"]]:
            return bd, chat_id
    for cid, bd in list(active_bosses.items()):
        if user_id in [u["id"] for u in bd["participants"]]:
            return bd, cid
    for cid, bd in list(secret_boss_active.items()):
        if user_id in [u["id"] for u in bd["participants"]]:
            return bd, cid
    return None, None

def enemy_status_active(raid_state, key):
    ts = raid_state.get("enemy_statuses", {}).get(key)
    if not ts: return False
    try: return datetime.now() < datetime.fromisoformat(ts)
    except: return False

def set_enemy_status(raid_state, key, seconds):
    if "enemy_statuses" not in raid_state:
        raid_state["enemy_statuses"] = {}
    raid_state["enemy_statuses"][key] = (datetime.now() + timedelta(seconds=seconds)).isoformat()

def tick_enemy_bleed(raid_state):
    """Returns bleed damage dealt this tick, 0 if no tick yet."""
    es = raid_state.get("enemy_statuses", {})
    if not enemy_status_active(raid_state, "bleed_until"): return 0
    last = es.get("bleed_last_tick")
    now  = datetime.now()
    if last and (now - datetime.fromisoformat(last)).total_seconds() < 30: return 0
    dmg = safe_int(es.get("bleed_damage"), 10)
    raid_state["enemy_hp"] = max(0, raid_state["enemy_hp"] - dmg)
    raid_state["enemy_statuses"]["bleed_last_tick"] = now.isoformat()
    return dmg

def apply_skill_to_raid_enemy(p, sk, raid_state, w):
    """
    Apply a skill to the current raid enemy.
    Returns (lines_list, dmg_dealt).
    Handles all skill types that make sense vs an NPC enemy.
    """
    stype   = sk.get("type", "damage")
    base    = calc_attack_damage(p, w)
    dmg     = 0
    lines   = []
    enemy   = raid_state["enemy"]

    if stype == "damage":
        dmg = round(base * sk.get("mult", 1.0))
    elif stype == "multihit":
        hits = sk.get("hits", 2); mult = sk.get("mult", 0.8)
        dmg  = sum(round(calc_attack_damage(p, w) * mult) for _ in range(hits))
        lines.append(f"⚡ {hits}-hit combo! Total: {dmg}")
    elif stype == "crit_dmg":
        dmg = round(base * sk.get("mult", 1.8) * 2)
        lines.append("💥 *Guaranteed Critical!*")
    elif stype == "pierce_dmg":
        dmg = round(get_stat(p, "AGI") * 3)
        lines.append("🌑 *Pierce!* Full damage  -  no defense.")
    elif stype == "pierce_all":
        dmg = round(get_stat(p, "STR") * sk.get("str_mult", 2))
        lines.append("🏹 *Piercing Shot!* Ignores all defense.")
    elif stype == "charged_shot":
        p["charging_killshot"] = 1
        lines.append("🎯 *Charging Killshot!* Next /solostrike or /raidstrike fires it!")
        return lines, 0
    elif stype == "stun":
        dmg = round(base * 1.0)
        if random.random() < 0.45:
            set_enemy_status(raid_state, "stunned_until", 60)
            lines.append(f"⚡ *{enemy['name']}* is *Stunned!* Skips next counter-attack!")
    elif stype == "root":
        set_enemy_status(raid_state, "frozen_until", 90)
        lines.append(f"🌿 *{enemy['name']}* is *Rooted!* Cannot attack for 90 seconds!")
        dmg = round(base * 0.5)
    elif stype == "miss_debuff":
        set_enemy_status(raid_state, "weakened_until", 180)
        lines.append(f"😵 *{enemy['name']}* is *Weakened!* Deals 25% less damage for 3 minutes.")
    elif stype == "bleed_crit":
        dmg = round(base * sk.get("mult", 2.0) * 2)
        set_enemy_status(raid_state, "bleed_until", 300)
        if "enemy_statuses" not in raid_state:
            raid_state["enemy_statuses"] = {}
        raid_state["enemy_statuses"]["bleed_damage"] = 10
        raid_state["enemy_statuses"]["bleed_last_tick"] = datetime.now().isoformat()
        lines.append(f"🩸 *{enemy['name']}* is *Bleeding!* Takes 10 dmg every 30s!")
    elif stype == "drain":
        steal = round(raid_state["enemy_hp"] * sk.get("drain_pct", 0.30))
        dmg   = round(base * sk.get("mult", 1.0))
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        lines.append(f"🩸 Drained *{steal} HP* from {enemy['name']}! You healed {steal}.")
    elif stype == "drain_kill":
        steal = round(raid_state["enemy_hp"] * sk.get("drain_pct", 0.40))
        dmg   = round(base * sk.get("mult", 1.5))
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        lines.append(f"🩸 *Drain Soul!* Stole {steal} HP!")
    elif stype == "debuff":
        set_enemy_status(raid_state, "hexed_until", 120)
        lines.append(f"💀 *Hexed!* {enemy['name']} deals 25% less damage for 2 minutes!")
        dmg = round(base * 0.8)
    elif stype in ("vanish", "holy_shield", "blessing"):
        # Self-buff  -  apply to player, no damage
        if stype == "vanish":
            set_status(p, "vanish_until", 60)
            lines.append("👻 *Vanished!* (No effect in raids  -  treated as stealth stance)")
        elif stype == "blessing":
            set_status(p, "blessed_until", 300)
            lines.append("✨ *Blessed!* +10% damage and healing for 5 minutes.")
        return lines, 0
    elif stype == "silence":
        set_enemy_status(raid_state, "silenced_until", 60)
        dmg = round(base * 1.5)
        lines.append(f"🤐 *Silenced!* {enemy['name']} is dazed  -  reduced damage next hit!")
        set_enemy_status(raid_state, "weakened_until", 60)
    elif stype in ("holy_dmg", "strip_debuff", "condemn"):
        wis = get_stat(p, "WIS")
        if stype == "holy_dmg":    dmg = wis * 3
        elif stype == "strip_debuff": dmg = wis * 4
        elif stype == "condemn":
            dmg = wis * 8
            set_enemy_status(raid_state, "hexed_until", 300)
            set_enemy_status(raid_state, "weakened_until", 3600)
            lines.append(f"⚡ *CONDEMNED!* {enemy['name']} is hexed and weakened!")
    elif stype == "void_nuke":
        dmg = raid_state["enemy_hp"] // 2
        lines.append(f"🌑 *Void Nuke!* Half HP obliterated!")
    elif stype == "freeze_nuke":
        int_v = get_stat(p, "INT")
        dmg   = int_v * 6
        set_enemy_status(raid_state, "frozen_until", 60)
        lines.append(f"❄️ *Frozen!* {enemy['name']} is frozen  -  skips next counter-attack!")
    # ── New class skill types ──────────────────────────────────────────────────
    elif stype == "aoe_heal_dmg":
        wis = get_stat(p, "WIS")
        heal = round(wis * 3)
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        lines.append(f"🌸 *Blossom Nova!* Healed self *+{heal} HP*!")
        if raid_state.get("enemy_statuses", {}).get("poisoned_until") or raid_state.get("enemy_statuses", {}).get("poison_damage"):
            dmg = wis * 6
            lines.append("☠️ Poisoned target takes WIS×6 burst nature damage!")
        else:
            dmg = wis * 3
    elif stype == "aoe_poison_strong":
        wis = get_stat(p, "WIS")
        dmg = round(wis * 1.5)
        set_enemy_status(raid_state, "poisoned_until", 600)
        if "enemy_statuses" not in raid_state:
            raid_state["enemy_statuses"] = {}
        raid_state["enemy_statuses"]["poison_damage"] = max(wis, 10)
        raid_state["enemy_statuses"]["poison_last_tick"] = datetime.now().isoformat()
        lines.append(f"☠️ *Toxic Bloom!* WIS-scaling poison applied for 10 minutes!")
    elif stype == "def_reflect":
        set_status(p, "def_reflect_until", 120)
        lines.append("🌿 *Thorn Fortress!* 40% damage reduction + reflect active for 2 minutes!")
        return lines, 0
    elif stype == "nature_nuke":
        wis = get_stat(p, "WIS")
        dmg = wis * 7
        set_enemy_status(raid_state, "poisoned_until", 300)
        if "enemy_statuses" not in raid_state:
            raid_state["enemy_statuses"] = {}
        raid_state["enemy_statuses"]["poison_damage"] = max(wis * 2, 20)
        raid_state["enemy_statuses"]["poison_last_tick"] = datetime.now().isoformat()
        set_enemy_status(raid_state, "weakened_until", 1800)
        lines.append(f"🌿 *Wrath of the Wild!* WIS×7 = {dmg} nature damage! Poisoned + weakened!")
    elif stype == "drain_debuff":
        steal = round(raid_state["enemy_hp"] * 0.25)
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        dmg = steal
        set_enemy_status(raid_state, "hexed_until", 180)
        set_enemy_status(raid_state, "weakened_until", 180)
        lines.append(f"💀 *Doom Curse!* Drained *{steal} HP*! Hex + Weak applied for 3 minutes!")
    elif stype == "curse_chain":
        int_v = get_stat(p, "INT")
        dmg = round(int_v * 1.5)
        set_enemy_status(raid_state, "hexed_until", 300)
        set_enemy_status(raid_state, "weakened_until", 300)
        lines.append(f"💜 *Vex Chain!* {enemy['name']} cursed: -25% ATK/DEF for 5 minutes!")
    elif stype == "mass_debuff":
        int_v = get_stat(p, "INT")
        dmg = round(int_v * 2.5)
        set_enemy_status(raid_state, "hexed_until", 3600)
        set_enemy_status(raid_state, "weakened_until", 3600)
        set_enemy_status(raid_state, "stunned_until", 60)
        lines.append(f"💜 *Dread Proclamation!* Max curses! Stunned + hexed + weakened for 1 hour!")
    elif stype == "party_atk_buff":
        set_status(p, "blessed_until", 300)
        lines.append("🎵 *War Song!* ATK +25% for 5 minutes!")
        return lines, 0
    elif stype == "party_full_buff":
        set_status(p, "blessed_until", 600)
        for field in ["hexed_until", "weakened_until"]:
            p[field] = None
        lines.append("🎶 *Ancient Aria!* Full stats buffed 10 minutes! Debuffs cleared.")
        return lines, 0
    elif stype == "ultimate_buff":
        p["hp"] = calc_max_hp(p)
        set_status(p, "blessed_until", 1800)
        lines.append("✨ *Magnum Opus!* Full HP restored! +20% all stats for 30 minutes!")
        return lines, 0
    elif stype == "self_atk_buff":
        set_status(p, "blessed_until", 120)
        lines.append("⚔️ *War Cry!* +30% ATK and +15% DEF for 2 minutes!")
        return lines, 0
    elif stype == "stun_def_dmg":
        str_v = get_stat(p, "STR"); def_v = get_stat(p, "DEF")
        dmg = round((str_v + def_v) * sk.get("mult", 1.0))
        if random.random() < 0.40:
            set_enemy_status(raid_state, "stunned_until", 30)
            lines.append(f"🛡️ *Shield Slam!* {dmg} damage! {enemy['name']} *Stunned* 30s!")
        else:
            lines.append(f"🛡️ *Shield Slam!* (STR+DEF) = {dmg} damage!")
    elif stype == "party_def_buff":
        set_status(p, "blessed_until", 300)
        lines.append("🛡️ *Rune Barrier!* DEF +20% for 5 minutes!")
        return lines, 0
    elif stype == "intercept_aoe":
        def_v = get_stat(p, "DEF")
        dmg = round(def_v * 2)
        set_status(p, "def_reflect_until", 120)
        lines.append(f"🛡️ *Vanguard's Presence!* DEF×2 = {dmg} damage! Intercept mode active 2 min!")
    elif stype == "holy_warrior_nuke":
        str_v = get_stat(p, "STR"); def_v = get_stat(p, "DEF")
        dmg = round(str_v * 4 + def_v * 4)
        set_enemy_status(raid_state, "stunned_until", 60)
        lines.append(f"⚡ *Bifrost Descent!* STR×4+DEF×4 = {dmg} holy damage! {enemy['name']} stunned 60s!")
    elif stype == "godlike_lightning":
        str_v = get_stat(p, "STR")
        dmg = round(str_v * 8)
        set_enemy_status(raid_state, "hexed_until", 180)
        set_enemy_status(raid_state, "weakened_until", 180)
        lines.append(f"⚡ *Valhalla's Thunder!* STR×8 = {dmg} divine lightning!")
    elif stype == "aoe_bleed_multihit":
        hits = sk.get("hits", 4)
        dmg = sum(round(base * sk.get("mult", 0.6)) for _ in range(hits))
        set_enemy_status(raid_state, "bleed_until", 300)
        if "enemy_statuses" not in raid_state:
            raid_state["enemy_statuses"] = {}
        raid_state["enemy_statuses"]["bleed_damage"] = 15
        raid_state["enemy_statuses"]["bleed_last_tick"] = datetime.now().isoformat()
        lines.append(f"🌀 *Blade Storm!* {hits}-hit combo ({dmg} total)! *Bleeding* 15/30s!")
    elif stype == "execute_multihit":
        hits = sk.get("hits", 8)
        hp_pct = raid_state["enemy_hp"] / max(1, raid_state["enemy_max_hp"])
        mult = 1.0 if hp_pct <= 0.50 else sk.get("mult", 0.5)
        if hp_pct <= 0.50:
            lines.append(f"💀 *Execute!* Enemy below 50% HP — full power!")
        dmg = sum(round(base * mult) for _ in range(hits))
        lines.append(f"🌀 *Thousand Cuts!* {hits} hits = *{dmg} total damage!*")
    elif stype == "vanish_dmg":
        agi = get_stat(p, "AGI")
        dmg = round(agi * 4)
        set_status(p, "vanish_until", 30)
        lines.append(f"👻 *Phase Step!* Vanished + burst: AGI×4 = {dmg}!")
    elif stype == "phantom_aoe":
        agi = get_stat(p, "AGI")
        dmg = round(agi * 2.5)
        lines.append(f"🌀 *Ethereal Storm!* Phantom wave: AGI×2.5 = {dmg} phantom damage!")
    elif stype == "bounce_spell":
        str_v = get_stat(p, "STR")
        dmg = round(str_v * 2)
        lines.append(f"⚡ *Chain Lightning!* STR×2 = {dmg} lightning damage!")
    elif stype in ("guaranteed_hit", "execute_nuke"):
        stat_key = sk.get("stat", get_primary_stat(p))
        dmg = round(get_stat(p, stat_key) * sk.get("mult", 2.0))
        lines.append(f"💥 *{sk['name']}!* {dmg} damage!")
    else:
        dmg = round(base * sk.get("mult", 1.0))

    # Charged killshot check
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0
        dmg = get_stat(p, "AGI") * 4
        lines.append(f"🎯 *KILLSHOT FIRED!* AGI×4 = *{dmg} damage!*")

    # Apply crit if base damage type
    if dmg > 0 and check_crit(p) and stype not in ("crit_dmg","void_nuke","pierce_all","charged_shot"):
        dmg = apply_crit(p, dmg)
        lines.append("💥 *Critical hit!*")

    raid_state["enemy_hp"] = max(0, raid_state["enemy_hp"] - dmg)
    return lines, dmg

def raid_enemy_counter(p, raid_state, lines):
    """
    Fire the raid enemy's counter-attack against player p.
    Modifies p["hp"] and raid_state in place.
    Returns True if player was killed, False otherwise.
    """
    enemy = raid_state["enemy"]

    # Bleed tick on enemy first
    bleed_dmg = tick_enemy_bleed(raid_state)
    if bleed_dmg:
        lines.append(f"🩸 *{enemy['name']}* bleeds for *{bleed_dmg}*! HP: {raid_state['enemy_hp']}/{raid_state['enemy_max_hp']}")
        if raid_state["enemy_hp"] <= 0:
            return False  # enemy died to bleed  -  caller handles wave clear

    # Check if enemy is stunned/frozen/rooted
    if enemy_status_active(raid_state, "stunned_until") or enemy_status_active(raid_state, "frozen_until"):
        status = "stunned" if enemy_status_active(raid_state, "stunned_until") else "frozen"
        lines.append(f"⚡ *{enemy['name']}* is {status}  -  no counter-attack!")
        return False

    raw = random.randint(enemy["dmg_min"], enemy["dmg_max"])

    # Apply weakened/hexed reduction
    if enemy_status_active(raid_state, "weakened_until") or enemy_status_active(raid_state, "hexed_until"):
        raw = round(raw * 0.75)

    edm = calc_defense(p, raw)

    # Dodge check
    dodge_chance = get_accessory_bonus(p, "dodge_bonus") + get_enchant_bonus(p, "dodge_bonus")
    cls_p = get_player_class(p)
    if cls_p and cls_p.get("passive_key") == "evasion": dodge_chance += 0.10
    if dodge_chance > 0 and random.random() < dodge_chance:
        lines.append(f"💨 *{p['username']}* dodges *{enemy['name']}'s* attack!")
        return False

    p["hp"] = max(0, p["hp"] - edm)
    if p["hp"] == 0:
        exp_loss = apply_pvp_death(p, killer_name=enemy["name"], cause="Solo Raid")
        lines.append(
            f"💀 *{enemy['name']}* kills *{p['username']}*! "
            f"Defeated 6hrs. -{exp_loss} EXP.")
        return True
    else:
        lines.append(
            f"🩸 *{enemy['name']}* hits *{p['username']}* for *{edm}!* "
            f"({p['hp']}/{calc_max_hp(p)} HP)")
        return False

# ── TURN-BASED RAID HELPERS ───────────────────────────────────────────────────

def _get_alive_party(raid_state):
    """Return list of party member dicts who are still alive in this raid instance."""
    return [u for u in raid_state["party"]
            if raid_state["player_hp"].get(u["id"], 1) > 0]

async def _announce_turn(bot, chat_id, raid_state):
    """Announce whose turn it is and start the 25s timer."""
    alive = _get_alive_party(raid_state)
    if not alive:
        return
    idx = raid_state.get("current_turn_idx", 0) % len(alive)
    raid_state["current_turn_idx"] = idx
    current = alive[idx]
    uid = current["id"]
    name = current["name"]

    # Cancel existing timer if any
    old_task = raid_state.get("turn_task")
    if old_task and not old_task.done():
        old_task.cancel()

    enemy = raid_state["enemy"]
    php  = raid_state["player_hp"].get(uid, 0)
    pmhp = raid_state["player_max_hp"].get(uid, php)
    msg = (f"⚔️ *{name}'s turn!* ({php}/{pmhp} HP)\n"
           f"Enemy: *{enemy['name']}* ❤️ {raid_state['enemy_hp']}/{raid_state['enemy_max_hp']}\n"
           f"Use /attack within 25 seconds!")
    raid_turn_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"raid_atk_{uid}"),
    ]])
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown",
                           reply_markup=raid_turn_markup)

    task = asyncio.create_task(
        _raid_turn_timeout(bot, chat_id, raid_state, uid, name))
    raid_state["turn_task"] = task

async def _raid_turn_timeout(bot, chat_id, raid_state, uid, player_name):
    """Fires after 25s if player hasn't acted. Auto-attacks on their behalf."""
    await asyncio.sleep(25)
    alive = _get_alive_party(raid_state)
    if not alive:
        return
    idx = raid_state.get("current_turn_idx", 0) % len(alive)
    if idx >= len(alive) or alive[idx]["id"] != uid:
        return  # Turn already advanced

    p = get_player(uid)
    if not p:
        await _advance_raid_turn(bot, chat_id, raid_state)
        return

    w = get_weather()
    dmg = calc_attack_damage(p, w)
    if check_crit(p): dmg = apply_crit(p, dmg)

    raid_state["enemy_hp"] = max(0, raid_state["enemy_hp"] - dmg)
    raid_state["damage_dealt"][uid] = raid_state["damage_dealt"].get(uid, 0) + dmg

    bleed_dmg = tick_enemy_bleed(raid_state)
    lines = [f"⏱️ *Auto-attack!* *{player_name}* strikes *{raid_state['enemy']['name']}* for *{dmg}!*",
             f"❤️ Enemy HP: {raid_state['enemy_hp']}/{raid_state['enemy_max_hp']}"]
    if bleed_dmg:
        lines.append(f"🩸 Bleed: {bleed_dmg} dmg!")

    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")

    if raid_state["enemy_hp"] <= 0:
        await _handle_wave_clear(bot, chat_id, raid_state, p)
        return

    await _advance_raid_turn(bot, chat_id, raid_state)

async def _advance_raid_turn(bot, chat_id, raid_state):
    """Move to next player, or trigger enemy phase if round complete."""
    alive = _get_alive_party(raid_state)
    if not alive:
        return

    acted = raid_state.get("acted_this_round", set())
    alive_ids = {u["id"] for u in alive}
    remaining = alive_ids - acted

    if not remaining:
        # All players acted  -  enemy phase
        await _enemy_phase(bot, chat_id, raid_state)
    else:
        # Find next alive player who hasn't acted
        current_idx = raid_state.get("current_turn_idx", 0)
        next_idx = (current_idx + 1) % len(alive)
        # Cycle to find one who hasn't acted
        for _ in range(len(alive)):
            if alive[next_idx % len(alive)]["id"] in remaining:
                break
            next_idx += 1
        raid_state["current_turn_idx"] = next_idx % len(alive)
        await _announce_turn(bot, chat_id, raid_state)

async def _enemy_phase(bot, chat_id, raid_state):
    """Enemy attacks 1 or 2 random alive players, then starts new round."""
    alive = _get_alive_party(raid_state)
    if not alive or raid_state["enemy_hp"] <= 0:
        raid_state["acted_this_round"] = set()
        raid_state["current_turn_idx"] = 0
        await _announce_turn(bot, chat_id, raid_state)
        return

    enemy = raid_state["enemy"]
    lines = [f"👹 *{enemy['name']}* attacks!"]

    # 70% hit 1, 30% hit 2
    hit_count = 2 if random.random() < 0.30 else 1
    targets = random.sample(alive, min(hit_count, len(alive)))

    for target in targets:
        uid = target["id"]
        p = get_player(uid)
        if not p: continue

        raw = random.randint(enemy["dmg_min"], enemy["dmg_max"])
        if enemy_status_active(raid_state, "weakened_until") or enemy_status_active(raid_state, "hexed_until"):
            raw = round(raw * 0.75)

        # Dodge check
        dodge = get_accessory_bonus(p, "dodge_bonus") + get_enchant_bonus(p, "dodge_bonus")
        cls_p = get_player_class(p)
        if cls_p and cls_p.get("passive_key") == "evasion": dodge += 0.10
        if dodge > 0 and random.random() < dodge:
            lines.append(f"💨 *{p['username']}* dodges!")
            continue

        edm = calc_defense(p, raw)
        raid_state["player_hp"][uid] = max(0, raid_state["player_hp"].get(uid, 1) - edm)
        php  = raid_state["player_hp"][uid]
        pmhp = raid_state["player_max_hp"].get(uid, php)

        if php == 0:
            exp_loss = apply_pvp_death(p, killer_name=enemy["name"], cause="Raid")
            save_player(p)
            lines.append(f"💀 *{enemy['name']}* kills *{p['username']}*! 6hr defeat. -{exp_loss} EXP.")
        else:
            lines.append(f"🩸 *{p['username']}* takes *{edm} dmg!* ({php}/{pmhp} HP)")
            if php <= round(pmhp * 0.30):
                asyncio.create_task(bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ *{p['username']}* is critically low! ({php}/{pmhp} HP) Use /skill or a healing item!",
                    parse_mode="Markdown"))

    await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")

    # Check if entire party wiped
    still_alive = _get_alive_party(raid_state)
    if not still_alive:
        active_raids.pop(chat_id, None)
        await bot.send_message(chat_id=chat_id,
            text="💀 *All players defeated! Raid failed.*", parse_mode="Markdown")
        return

    # Start new round
    raid_state["acted_this_round"] = set()
    raid_state["current_turn_idx"] = 0
    await _announce_turn(bot, chat_id, raid_state)

async def _handle_wave_clear(bot, chat_id, raid_state, p=None):
    """Handle enemy death  -  advance wave or complete the raid."""
    tier = raid_state["tier"]
    wave_enemies = tier["wave_enemies"]
    cw = raid_state["wave"]
    raid_state.pop("enemy_statuses", None)

    lines = [f"✅ *Wave {cw} cleared!*"]

    if cw < len(wave_enemies):
        raid_state["wave"] += 1
        ne = wave_enemies[cw].copy()
        raid_state["enemy"] = ne
        raid_state["enemy_hp"] = ne["hp"]
        raid_state["enemy_max_hp"] = ne["hp"]
        lines.append(f"\n🌊 *Wave {raid_state['wave']}  -  {ne['name']}*")
        lines.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
        # New wave  -  reset round and announce first turn
        raid_state["acted_this_round"] = set()
        raid_state["current_turn_idx"] = 0
        await _announce_turn(bot, chat_id, raid_state)

    elif cw == len(wave_enemies):
        bd = BOSSES[tier["wave_boss_key"]]
        party_size = len(_get_alive_party(raid_state))
        boss_hp = max(bd["max_hp"]//2, round(bd["max_hp"]*0.6*party_size))
        raid_state["wave"] = len(wave_enemies) + 1
        raid_state["enemy"] = {
            "name": bd["name"] + " ⚡",
            "dmg_min": round(bd["dmg_min"]*0.7),
            "dmg_max": round(bd["dmg_max"]*0.7),
        }
        raid_state["enemy_hp"] = boss_hp
        raid_state["enemy_max_hp"] = boss_hp
        lines.append(f"\n🎱 *FINAL BOSS  -  {bd['name']}!* ❤️ HP: {boss_hp}")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
        raid_state["acted_this_round"] = set()
        raid_state["current_turn_idx"] = 0
        await _announce_turn(bot, chat_id, raid_state)

    else:
        # Raid complete
        active_raids.pop(chat_id, None)
        lines.append(f"\n🏆 *RAID COMPLETE  -  {tier['name']}!*\n")
        total_dmg = sum(raid_state["damage_dealt"].values())
        w2 = get_weather()
        for u in raid_state["party"]:
            pp = get_player(u["id"])
            if not pp: continue
            share = max(0.10, raid_state["damage_dealt"].get(u["id"],0)/max(1,total_dmg))
            exp_r  = round(tier["exp_reward"]*(0.5+share))
            gold_r = round(tier["gold_reward"]*(0.5+share))
            pp["gold"] = pp.get("gold",0) + gold_r
            pp["quests_done"] = pp.get("quests_done",0) + 1
            loot = roll_loot_table(tier.get("loot_table",[]), pp)
            if loot:
                add_item(pp,loot); r=""
                for pool in [WEAPONS,ARMORS,ACCESSORIES]:
                    if loot in pool: r=RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                lines.append(f"🎒 *{pp['username']}* found {r} *{loot}*!")
            if u == raid_state["party"][0] and award_title(pp,"Break Leader"):
                lines.append(f"🏅 *{pp['username']}* earned: *Break Leader*!")
            add_exp(pp, exp_r, w2); save_player(pp)
            lines.append(f"✅ *{pp['username']}* ({int(share*100)}% dmg)  -  +{exp_r:,} EXP | +{gold_r}g")
        await bot.send_message(chat_id=chat_id, text="\n".join(lines)[:4096], parse_mode="Markdown")

def check_miss(attacker, defender):
    """Returns True if attack misses."""
    if is_invincible(defender):  return True
    if is_vanished(defender):    return True
    if cannot_attack(attacker):  return True

    # Base dodge  -  line-specific
    cls_d_line = get_class_line(defender)
    if cls_d_line == "archer":
        dodge_stat = get_stat(defender, "DEX")
    elif cls_d_line == "thief":
        dodge_stat = get_stat(defender, "LUK")
    else:
        dodge_stat = get_stat(defender, "AGI")
    dodge = min(0.40, dodge_stat * 0.008)

    # Accessory dodge bonus
    dodge += get_accessory_bonus(defender, "dodge_bonus")
    dodge += get_enchant_bonus(defender, "dodge_bonus")

    # Class passives
    cls_d = get_player_class(defender)
    if cls_d:
        pk = cls_d.get("passive_key","")
        if pk == "evasion":       dodge += 0.15
        if pk == "ghost_form":    dodge += 0.20
        if pk == "void_rift":     dodge += 0.25
        if pk == "quick_hands":   dodge += get_stat(defender, "AGI") * 0.005
        # New class passives
        if pk == "waltz":         dodge += 0.15
        if pk == "wildflower_shield": dodge += 0.12
        if pk == "shield_maiden": dodge += 0.20
        if pk == "ethereal_step": dodge += 0.20
        if pk == "mirror_image":  dodge += 0.10
        if pk == "phantoms_grace":
            dodge = max(0.20, dodge)  # floor at 20%
            dodge += min(0.20, safe_int(defender.get("phantoms_grace_stacks", 0)) * 0.02)
        if pk == "sovereign_veil":
            dodge += 0.30
            if defender.get("sovereign_veil_active"):
                defender["sovereign_veil_active"] = 0; return True
        if pk == "fog_of_war":    dodge += 0.05
        if pk == "rhythm":        dodge += 0.05
        if pk == "storm_instinct": dodge += 0.05

    # Pet passive dodge bonus (defender)
    def_pet = get_active_pet_record(defender.get("user_id"))
    if def_pet:
        dodge += get_pet_passives(def_pet.get("level",1)).get("dodge_bonus", 0)

    # Attacker miss penalty
    if is_distracted(attacker): dodge += 0.30

    # Attacker passives that pierce dodge
    cls_a = get_player_class(attacker)
    if cls_a:
        pk_a = cls_a.get("passive_key","")
        if pk_a == "eagle_eye":
            if get_stat(attacker, "AGI") > get_stat(defender, "DEF"):
                return False  # never miss

    return random.random() < dodge

def check_crit(attacker):
    cls = get_player_class(attacker)
    line = cls.get("line") if cls else None
    if line == "thief":
        stat_val = get_stat(attacker, "LUK")
        base_crit = min(0.50, stat_val * 0.010)
    elif line == "archer":
        stat_val = get_stat(attacker, "DEX")
        base_crit = min(0.45, stat_val * 0.009)
    else:
        stat_val = get_stat(attacker, "AGI")
        base_crit = min(0.40, stat_val * 0.008)
    base_crit += get_accessory_bonus(attacker, "crit_bonus")
    base_crit += get_enchant_bonus(attacker, "crit_bonus")
    if cls and cls.get("passive_key") == "quick_hands":
        base_crit += 0.15
    # New class passives
    if cls:
        _pk = cls.get("passive_key", "")
        if _pk == "thunder_step":    base_crit += 0.10
        if _pk == "storms_eye":      base_crit += 0.20
        if _pk == "celestial_wrath": base_crit += 0.15
        if _pk == "waltz":           base_crit += 0.05
        if _pk == "rhythm":
            base_crit += min(0.15, safe_int(attacker.get("rhythm_stacks", 0)) * 0.03)
        if _pk == "flourish":
            base_crit += min(0.10, safe_int(attacker.get("flourish_stacks", 0)) * 0.03)
        if _pk == "adrenaline":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.30: base_crit += 0.20
        if _pk == "death_whirl":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.40: base_crit += 0.30
        if _pk == "final_performance":
            _hp_pct = attacker["hp"] / max(1, attacker.get("max_hp", attacker["hp"]))
            if _hp_pct < 0.25: base_crit += 0.40
    atk_pet = get_active_pet_record(attacker.get("user_id"))
    if atk_pet:
        base_crit += get_pet_passives(atk_pet.get("level", 1)).get("crit_bonus", 0)
    return random.random() < base_crit

def apply_crit(attacker, dmg):
    cls = get_player_class(attacker)
    mult = 2.0
    if cls and cls.get("passive_key") == "headshot":
        mult = 3.0
    elif cls and cls.get("passive_key") == "celestial_wrath":
        mult = 2.5
    return round(dmg * mult)

def apply_lifesteal(attacker, dmg):
    cls = get_player_class(attacker)
    pk = cls.get("passive_key","") if cls else ""
    healed = 0
    if pk == "soul_pact":
        healed = round(dmg * 0.20)
    if pk == "bloodlust":
        healed = 5
    # New class passives
    if pk == "verdant_renewal":  healed += round(dmg * 0.15)
    if pk == "eternal_bloom":    healed += round(dmg * 0.10)
    if pk == "natural_growth":   healed += 5
    if pk == "flourish":         healed += safe_int(attacker.get("flourish_stacks", 0)) * 3
    if pk == "waltz":            healed += 5  # crits restore 5 HP
    if pk == "adrenaline":
        _hp_pct = attacker["hp"] / max(1, calc_max_hp(attacker))
        if _hp_pct < 0.30: healed += 10
    if get_accessory_bonus(attacker, "lifesteal_flat"):
        healed += get_accessory_bonus(attacker, "lifesteal_flat")
    enc_heal = get_enchant_bonus(attacker, "lifesteal_flat")
    if enc_heal:
        healed += enc_heal
    ls_pet = get_active_pet_record(attacker.get("user_id"))
    if ls_pet:
        healed += get_pet_passives(ls_pet.get("level", 1)).get("lifesteal_flat", 0)
    if healed:
        attacker["hp"] = min(calc_max_hp(attacker), attacker["hp"] + healed)
    return healed

def apply_reflect(defender, attacker, dmg):
    """Reflect damage back to attacker."""
    cls = get_player_class(defender)
    if not cls: return 0
    pk = cls.get("passive_key","")
    reflect = 0
    if pk == "judgement":
        reflect = round(get_stat(defender, "WIS") * 0.10)
    # New class passives
    if pk == "thorn_skin":   reflect += round(get_stat(defender, "WIS") * 0.5)
    if pk == "thorn_aura":   reflect += round(get_stat(defender, "WIS") * 1.0)
    if pk == "nettleskin":
        if random.random() < 0.10: reflect += 15
    if pk == "ancient_bark": reflect += round(dmg * 0.10)
    if pk == "beguile":
        if random.random() < 0.08: reflect += round(dmg * 0.50)
    # def_reflect status — reflect half of incoming damage
    if _ts_active(defender, "def_reflect_until"):
        reflect += round(dmg * 0.50)
    if get_accessory_bonus(defender, "reflect_pct"):
        reflect += round(dmg * get_accessory_bonus(defender, "reflect_pct"))
    if reflect:
        attacker["hp"] = max(0, attacker["hp"] - reflect)
    return reflect

def check_bleed_tick(p):
    """Called in handle_message  -  tick bleed damage."""
    if not is_bleeding(p): return 0
    last = p.get("bleed_last_tick")
    now  = datetime.now()
    if last:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds()
        if elapsed < 30: return 0
    dmg = safe_int(p.get("bleed_damage"), 10)
    p["hp"] = max(0, p["hp"] - dmg)
    p["bleed_last_tick"] = now.isoformat()
    return dmg

# ── DATABASE ──────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS shadow_profiles (
        user_id INTEGER PRIMARY KEY, username TEXT,
        level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0,
        total_exp INTEGER DEFAULT 0, message_count INTEGER DEFAULT 0,
        passive_cooldowns TEXT DEFAULT '{}',
        ascended INTEGER DEFAULT 0,
        last_seen TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY, username TEXT,
        hp INTEGER DEFAULT 100, max_hp INTEGER DEFAULT 100,
        exp INTEGER DEFAULT 0, level INTEGER DEFAULT 1,
        total_exp INTEGER DEFAULT 0,
        gold INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0, quests_done INTEGER DEFAULT 0,
        heals_given INTEGER DEFAULT 0, dodges INTEGER DEFAULT 0,
        crafts_done INTEGER DEFAULT 0, perm_dmg_bonus INTEGER DEFAULT 0,
        titles TEXT DEFAULT '["Adventurer"]',
        active_title TEXT DEFAULT 'The Newcomer',
        class_id TEXT DEFAULT NULL,
        class_path TEXT DEFAULT NULL,
        all_skills TEXT DEFAULT '[]',
        stat_points INTEGER DEFAULT 0,
        stats TEXT DEFAULT '{"STR":5,"DEF":5,"AGI":5,"INT":5,"WIS":5}',
        inventory TEXT DEFAULT '[]',
        passive_cooldowns TEXT DEFAULT '{}',
        equipped_weapon TEXT DEFAULT NULL,
        equipped_armor TEXT DEFAULT NULL,
        equipped_shield TEXT DEFAULT NULL,
        equipped_accessory TEXT DEFAULT NULL,
        defeated_until TEXT DEFAULT NULL,
        invincible_until TEXT DEFAULT NULL,
        distracted_until TEXT DEFAULT NULL,
        entangled_until TEXT DEFAULT NULL,
        frozen_until TEXT DEFAULT NULL,
        poison_until TEXT DEFAULT NULL,
        poison_damage INTEGER DEFAULT 0,
        poison_last_tick TEXT DEFAULT NULL,
        burn_until TEXT DEFAULT NULL,
        burn_damage INTEGER DEFAULT 0,
        burn_last_tick TEXT DEFAULT NULL,
        ward_until TEXT DEFAULT NULL,
        exposed_until TEXT DEFAULT NULL,
        branded_until TEXT DEFAULT NULL,
        stunned_until TEXT DEFAULT NULL,
        vanish_until TEXT DEFAULT NULL,
        bleed_until TEXT DEFAULT NULL,
        bleed_damage INTEGER DEFAULT 0,
        bleed_last_tick TEXT DEFAULT NULL,
        hexed_until TEXT DEFAULT NULL,
        weakened_until TEXT DEFAULT NULL,
        blessed_until TEXT DEFAULT NULL,
        healing_blocked_until TEXT DEFAULT NULL,
        revival_blocked_until TEXT DEFAULT NULL,
        silenced_until TEXT DEFAULT NULL,
        temp_hp_bonus INTEGER DEFAULT 0,
        temp_hp_until TEXT DEFAULT NULL,
        recent_attackers TEXT DEFAULT '[]',
        contract_target INTEGER DEFAULT NULL,
        contract_until TEXT DEFAULT NULL,
        charging_killshot INTEGER DEFAULT 0,
        steady_aim_target INTEGER DEFAULT NULL,
        steady_aim_stacks INTEGER DEFAULT 0,
        mark_first_hit INTEGER DEFAULT 1,
        deadeye_kill_bonus INTEGER DEFAULT 0,
        spell_cast_count INTEGER DEFAULT 0,
        holy_field_until TEXT DEFAULT NULL,
        devotion_charge INTEGER DEFAULT 0,
        last_daily TEXT DEFAULT NULL,
        last_quest TEXT DEFAULT NULL,
        last_train TEXT DEFAULT NULL,
        last_explore TEXT DEFAULT NULL,
        explore_count_today INTEGER DEFAULT 0,
        explore_date TEXT DEFAULT NULL,
        shop_discount_until TEXT DEFAULT NULL,
        guild_id INTEGER DEFAULT NULL,
        prestige_count INTEGER DEFAULT 0,
        shadow_level_at_ascension INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS guilds (
        guild_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE, leader_id INTEGER,
        members TEXT DEFAULT '[]',
        level INTEGER DEFAULT 1, exp INTEGER DEFAULT 0,
        bank INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS bounties (
        bounty_id INTEGER PRIMARY KEY AUTOINCREMENT,
        placer_id INTEGER, target_id INTEGER,
        reward INTEGER DEFAULT 500,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT,
        claimed_by INTEGER DEFAULT NULL
    )""")

    conn.commit()

    # Migrate existing tables  -  add columns introduced in v13
    migrations = [
        ("players", "poison_until",      "TEXT DEFAULT NULL"),
        ("players", "poison_damage",     "INTEGER DEFAULT 0"),
        ("players", "poison_last_tick",  "TEXT DEFAULT NULL"),
        ("players", "burn_until",        "TEXT DEFAULT NULL"),
        ("players", "burn_damage",       "INTEGER DEFAULT 0"),
        ("players", "burn_last_tick",    "TEXT DEFAULT NULL"),
        ("players", "ward_until",        "TEXT DEFAULT NULL"),
        ("players", "exposed_until",     "TEXT DEFAULT NULL"),
        ("players", "branded_until",     "TEXT DEFAULT NULL"),
        ("players", "marked_until",      "TEXT DEFAULT NULL"),
    ]
    for table, col, definition in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    migrations_v14 = [
        ("players", "DEX",          "INTEGER DEFAULT 5"),
        ("players", "LUK",          "INTEGER DEFAULT 5"),
        ("players", "enhancements", "TEXT DEFAULT '{}'"),
        ("players", "enchants",     "TEXT DEFAULT '{}'"),
        ("players", "last_dungeon", "TEXT DEFAULT NULL"),
    ]
    for table, col, definition in migrations_v14:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    migrations_v15 = [
        ("players",         "last_pool",         "TEXT DEFAULT NULL"),
        ("shadow_profiles", "last_pool",         "TEXT DEFAULT NULL"),
        ("shadow_profiles", "pending_items",     "TEXT DEFAULT '[]'"),
    ]
    for table, col, definition in migrations_v15:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    migrations_v16 = [
        ("players", "last_defeated_by", "TEXT DEFAULT NULL"),
    ]
    for table, col, definition in migrations_v16:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    migrations_v17 = [
        ("players", "item_reinforce_data", "TEXT DEFAULT '{}'"),
        ("players", "daily_objectives",    "TEXT DEFAULT '[]'"),
        ("players", "daily_obj_date",      "TEXT DEFAULT NULL"),
        ("players", "total_reinforces",    "INTEGER DEFAULT 0"),
        ("players", "total_ascensions",    "INTEGER DEFAULT 0"),
        ("players", "total_obj_completed", "INTEGER DEFAULT 0"),
    ]
    for table, col, definition in migrations_v17:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    migrations_v19 = [
        ("players", "prestige_skills", "TEXT DEFAULT '[]'"),
    ]
    for table, col, definition in migrations_v19:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    migrations_v20 = [
        ("players", "kill_streak",      "INTEGER DEFAULT 0"),
        ("players", "max_kill_streak",  "INTEGER DEFAULT 0"),
        ("players", "revenge_target",   "INTEGER DEFAULT NULL"),
        ("players", "revenge_expires",  "TEXT DEFAULT NULL"),
        ("players", "kills_today",      "INTEGER DEFAULT 0"),
        ("players", "kills_today_date", "TEXT DEFAULT NULL"),
        ("players", "last_claim",       "TEXT DEFAULT NULL"),
        ("players", "claim_streak",     "INTEGER DEFAULT 0"),
        ("players", "pvp_history",      "TEXT DEFAULT '[]'"),
        ("guilds",  "war_wins",         "INTEGER DEFAULT 0"),
    ]
    for table, col, definition in migrations_v20:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # Guild wars table
    conn.execute("""CREATE TABLE IF NOT EXISTS guild_wars (
        war_id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild1_id TEXT NOT NULL,
        guild2_id TEXT NOT NULL,
        declared_by TEXT NOT NULL,
        declared_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        kills1 INTEGER DEFAULT 0,
        kills2 INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1
    )""")
    conn.commit()

    # Ensure guilds table has bank_gold column
    try:
        conn.execute("ALTER TABLE guilds ADD COLUMN bank_gold INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # ── Marriage + new status columns ────────────────────────────────────────
    for _mc in [("married_to_id","INTEGER DEFAULT NULL"),
                ("married_to_name","TEXT DEFAULT NULL"),
                ("married_at","TEXT DEFAULT NULL"),
                ("def_reflect_until","TEXT DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE players ADD COLUMN {_mc[0]} {_mc[1]}")
            conn.commit()
        except sqlite3.OperationalError:
            pass

    conn.close()

    # ── v21 Item Rename Migration (pool-hall → RPG fantasy names) ────────────
    ITEM_NAME_MAP_V21 = {
        # Weapons — Warrior
        "Cracked House Cue":       "Rusty Shortsword",
        "Worn Practice Cue":       "Iron Broadsword",
        "Graphite Break Cue":      "Steel Knight Sword",
        "Heavy Breaker Staff":     "Warlord's Edge",
        "The Rack Splitter":       "Ruinblade",
        # Weapons — Mage
        "Chalked Finger":          "Gnarled Twig Wand",
        "Blue Diamond Chalk":      "Crystal Core Wand",
        "Blackwood Bridge Stick":  "Warlock's Dread Staff",
        "The Extension":           "Void Channel Staff",
        "The Grand Bridge":        "The Mind's Eye",
        # Weapons — Archer
        "Bent Triangle":           "Frayed Hunting Bow",
        "Standard Magic Rack":     "Repeating Crossbow",
        "Precision Rack":          "Ranger's Marked Bow",
        "Diamond Rack":            "Warden's Gale Bow",
        "The Perfect Break Rack":  "The Dead Reckoning",
        # Weapons — Thief
        "Chalk Shiv":              "Rusty Shiv",
        "Mushroom Tip Blade":      "Iron Stiletto",
        "Ferrule Dart":            "Bloodsteel Shuriken",
        "Twin Tip Blades":         "Shadow Death Star",
        "The Ball Return":         "Death's Whisper",
        # Weapons — Priest
        "Chalk Beads":             "Wooden Prayer Beads",
        "Iron Chalk Ring":         "Silver Prayer Beads",
        "The Spot Marker":         "Holy Judge's Cross",
        "The Crossed Cues":        "Grand Inquisitor's Cross",
        "The Diamond Staff":       "The Final Judgment",
        # Armors — Warrior
        "Bar Room Vest":           "Rusty Iron Vest",
        "Padded Cue Jacket":       "Rusty Iron Vest",
        "Slate Guard":             "Soldier's Plating",
        "Red Cloth Plate":         "Steel Breastplate",
        "Black Ball Plate":        "Warlord's Battle Plate",
        "Diamond Felt Armor":      "Dragonscale Plate",
        # Armors — Mage
        "Worn Chalk Coat":         "Worn Cloth Robe",
        "Green Baize Robe":        "Arcane Weave Robe",
        "White Glove Wrap":        "Sorcerer's Mantle",
        "Blacklight Cloak":        "Void-Touched Robe",
        "The Nap Robe":            "Archmage's Sanctum Robe",
        # Armors — Archer
        "Corner Pocket Vest":      "Padded Hunting Vest",
        "Rail Leather Chest":      "Scout's Leathers",
        "Diamond Point Plate":     "Forest Scout Armor",
        "Red Baize Brigandine":    "Strider's Marked Armor",
        "The Rack Scale":          "The Shadowmark Leather",
        # Armors — Thief
        "Hustle Coat":             "Torn Leather Vest",
        "Midnight Felt Coat":      "Rogue's Leathers",
        "The Sneak Mesh":          "Nightstalker's Vest",
        "Backdoor Harness":        "Phantom Leathers",
        "The Ghost Coat":          "The Shadow Wrap",
        # Armors — Priest
        "Chalk Cloth Vestments":   "Simple Cloth Vestment",
        "The Rule Book Robe":      "Blessed Cloth Robe",
        "The Referee Hood":        "Sanctified Robe",
        "The Tournament Cloak":    "High Cleric's Vestment",
        "The House Saint Surplice":"The High Saint's Vestment",
        # Shields
        "Cracked Rack Shield":     "Wooden Buckler",
        "Iron Triangle":           "Soldier's Kite Shield",
        "The Break Shield":        "Knight's Bulwark",
        "Black Ball Barrier":      "Holy Pavise",
        "The Diamond Aegis":       "Celestial Bulwark",
    }

    def _v21_list(lst):
        return [ITEM_NAME_MAP_V21.get(x, x) for x in lst]

    def _v21_dict(d):
        return {ITEM_NAME_MAP_V21.get(k, k): v for k, v in d.items()}

    try:
        mig21 = sqlite3.connect(DB_PATH)
        try:
            mig21.row_factory = sqlite3.Row
            c21 = mig21.cursor()
            c21.execute("""SELECT user_id,inventory,equipped_weapon,equipped_armor,
                                  equipped_shield,equipped_accessory,enhancements,enchants
                           FROM players""")
            rows21 = c21.fetchall()
            migrated21 = 0
            for row in rows21:
                changed = False
                uid = row["user_id"]
                inv  = sjl(row["inventory"], [])
                new_inv = _v21_list(inv)
                if new_inv != inv: changed = True
                ew  = ITEM_NAME_MAP_V21.get(row["equipped_weapon"],  row["equipped_weapon"])
                ea  = ITEM_NAME_MAP_V21.get(row["equipped_armor"],   row["equipped_armor"])
                es  = ITEM_NAME_MAP_V21.get(row["equipped_shield"],  row["equipped_shield"])
                eac = ITEM_NAME_MAP_V21.get(row["equipped_accessory"], row["equipped_accessory"])
                if (ew != row["equipped_weapon"] or ea != row["equipped_armor"] or
                        es != row["equipped_shield"] or eac != row["equipped_accessory"]):
                    changed = True
                enh = sjl(row["enhancements"], {}); new_enh = _v21_dict(enh)
                if new_enh != enh: changed = True
                enc = sjl(row["enchants"], {});     new_enc = _v21_dict(enc)
                if new_enc != enc: changed = True
                if changed:
                    c21.execute("""UPDATE players SET inventory=?,equipped_weapon=?,
                                    equipped_armor=?,equipped_shield=?,equipped_accessory=?,
                                    enhancements=?,enchants=? WHERE user_id=?""",
                        (json.dumps(new_inv), ew, ea, es, eac,
                         json.dumps(new_enh), json.dumps(new_enc), uid))
                    migrated21 += 1
            mig21.commit()
            if migrated21 > 0:
                logger.info(f"v21 item rename: updated {migrated21} player(s)")
        finally:
            mig21.close()
    except Exception as e:
        logger.error(f"v21 item rename failed: {e}")

    # ── Pets table ───────────────────────────────────────────────────────────
    _pets_conn = sqlite3.connect(DB_PATH)
    _pets_conn.execute("""CREATE TABLE IF NOT EXISTS pets (
        pet_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id   INTEGER NOT NULL,
        species    TEXT NOT NULL,
        nickname   TEXT,
        level      INTEGER DEFAULT 1,
        exp        INTEGER DEFAULT 0,
        hunger     INTEGER DEFAULT 100,
        mood       INTEGER DEFAULT 100,
        last_fed   TEXT,
        last_trained TEXT,
        is_active  INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    _pets_conn.commit()
    _pets_conn.close()
    # Re-open connection for the v22 consumable rename migration
    try:
        migc = sqlite3.connect(DB_PATH); migc.row_factory = sqlite3.Row; cc = migc.cursor()
        cc.execute("SELECT user_id,inventory,equipped_weapon,equipped_armor,equipped_shield,equipped_accessory,enhancements,enchants FROM players")
        rows_c = cc.fetchall(); mc_count = 0
        for row in rows_c:
            changed = False; uid = row["user_id"]
            inv = sjl(row["inventory"],[])
            new_inv = [_ITEM_RENAME.get(i,i) for i in inv]
            if new_inv != inv: changed = True
            ew  = _ITEM_RENAME.get(row["equipped_weapon"],  row["equipped_weapon"])
            ea  = _ITEM_RENAME.get(row["equipped_armor"],   row["equipped_armor"])
            es  = _ITEM_RENAME.get(row["equipped_shield"],  row["equipped_shield"])
            eac = _ITEM_RENAME.get(row["equipped_accessory"],row["equipped_accessory"])
            if ew!=row["equipped_weapon"] or ea!=row["equipped_armor"] or es!=row["equipped_shield"] or eac!=row["equipped_accessory"]: changed=True
            enh = sjl(row["enhancements"],{}); new_enh={_ITEM_RENAME.get(k,k):v for k,v in enh.items()}
            if new_enh!=enh: changed=True
            enc = sjl(row["enchants"],{});    new_enc={_ITEM_RENAME.get(k,k):v for k,v in enc.items()}
            if new_enc!=enc: changed=True
            if changed:
                cc.execute("UPDATE players SET inventory=?,equipped_weapon=?,equipped_armor=?,equipped_shield=?,equipped_accessory=?,enhancements=?,enchants=? WHERE user_id=?",
                    (json.dumps(new_inv),ew,ea,es,eac,json.dumps(new_enh),json.dumps(new_enc),uid))
                mc_count+=1
        migc.commit(); migc.close()
        if mc_count>0: logger.info(f"v22 consumable rename: updated {mc_count} player(s)")
    except Exception as e: logger.error(f"v22 consumable rename failed: {e}")

    conn = sqlite3.connect(DB_PATH)  # reopen for remaining setup

    # Clear stale explore locks on startup
    conn3 = sqlite3.connect(DB_PATH)
    c3 = conn3.cursor()
    cutoff = (datetime.now() - timedelta(hours=2)).isoformat()
    c3.execute("UPDATE players SET explore_count_today=0 WHERE last_explore < ?", (cutoff,))
    conn3.commit()
    conn3.close()

    # ── v15 Item Name Migration ───────────────────────────────────────────────
    ITEM_NAME_MAP = {
        # Weapons  -  Warrior
        "Broken Longsword":"Cracked House Cue","Militia Falchion":"Worn Practice Cue",
        "Blacksteel Bastard Sword":"Graphite Break Cue","Giantslayer Zweihander":"Heavy Breaker Staff",
        "Worldcleaver":"The Rack Splitter",
        # Weapons  -  Mage
        "Oak Practice Staff":"Chalked Finger","Petrified Willow Wand":"Blue Diamond Chalk",
        "Cursed Ebony Staff":"Blackwood Bridge Stick","Astral Conduit Rod":"The Extension",
        "Nullstar Scepter":"The Grand Bridge",
        # Weapons  -  Archer
        "Makeshift Shortbow":"Bent Triangle","Goat Horn Crossbow":"Standard Magic Rack",
        "Falconwing Recurve Bow":"Precision Rack","Windripper Greatbow":"Diamond Rack",
        "Heaven's Tear Ballista":"The Perfect Break Rack",
        # Weapons  -  Thief
        "Rusty Shiv":"Chalk Shiv","Serrated Kujang":"Mushroom Tip Blade",
        "Venomspike Blowgun":"Ferrule Dart","Shadowstitch Katars":"Twin Tip Blades",
        "Umbral Chain Sickle":"The Ball Return",
        # Weapons  -  Priest
        "Wooden Prayer Beads":"Chalk Beads","Iron Rosary":"Iron Chalk Ring",
        "Sun Disc Pendant":"The Spot Marker","Martyr's Thorned Cross":"The Crossed Cues",
        "Sanctus Aeterna":"The Diamond Staff",
        # Armors  -  Warrior
        "Padded Tunic":"Padded Cue Jacket","Iron Scale Vest":"Slate Guard",
        "Crimson Plackart":"Red Cloth Plate","Onyx Golem Plate":"Black Ball Plate",
        "Titanfoil Carapace":"Diamond Felt Armor",
        # Armors  -  Mage
        "Frayed Spellcloak":"Worn Chalk Coat","Windwoven Silk Robe":"Green Baize Robe",
        "Arctic Fox Stole":"White Glove Wrap","Voidweave Mantle":"Blacklight Cloak",
        "Singularity Robe":"The Nap Robe",
        # Armors  -  Archer
        "Sturdy Leather Jerkin":"Corner Pocket Vest","Hardened Hide Cuirass":"Rail Leather Chest",
        "Griffon Plate Chest":"Diamond Point Plate","Phoenix Down Brigandine":"Red Baize Brigandine",
        "Skybreaker Scale Armor":"The Rack Scale",
        # Armors  -  Thief
        "Dark Hooded Wrap":"Hustle Coat","Oilskin Shadow Coat":"Midnight Felt Coat",
        "Stalker's Mesh Shroud":"The Sneak Mesh","Nocturnal Leather Harness":"Backdoor Harness",
        "Abyssal Cloak of Silence":"The Ghost Coat",
        # Armors  -  Priest
        "Woven Vestments":"Chalk Cloth Vestments","Embroidered Cassock":"The Rule Book Robe",
        "Silver Mitre Hood":"The Referee Hood","Lightweaver Chasuble":"The Tournament Cloak",
        "Seraph's Surplice":"The House Saint Surplice",
        # Shields
        "Splintered Buckler":"Cracked Rack Shield","Ironbound Targe":"Iron Triangle",
        "Kite Shield of the Vow":"The Break Shield","Obsidian Tower Shield":"Black Ball Barrier",
        "Aegis of First Light":"The Diamond Aegis",
        # Accessories  -  Common
        "Pebble of Focus":"Chalk Nub","Frayed Rope Band":"Worn Tip Wrap",
        "Copper Loop":"Brass Rail Ring","Tin Charm":"Pocket Marker",
        "Traveler's Token":"Road Player's Coin",
        # Accessories  -  Uncommon
        "Fox Tail Ring":"Silk Tip Ring","Brass Holy Symbol":"Chalk Cross Pendant",
        "Chipped Onyx Stud":"Black Ball Stud","Bloodstone Band":"Red Ball Band",
        "Mercenary's Signet":"Road Shark Signet","Hunter's Fang Pendant":"Hustler's Tooth",
        "Mana Bead Necklace":"Chalk Bead Necklace",
        # Accessories  -  Rare
        "Whisper Coin":"The Action Coin","Warmaster's Clasp":"Break Master's Clasp",
        "Owl Medallion":"Diamond Sight Medallion","Phantom Loop":"Ghost Ball Loop",
        "Executioner's Band":"Closer's Band","Spellweaver's Coil":"English Coil",
        "Ironheart Medallion":"Slate Heart","Vampiric Fang Chain":"Shark Tooth Chain",
        "Wanderer's Compass":"Road Player's Compass","Stormcaller's Torc":"The Break Torc",
        # Accessories  -  Epic
        "Twin Serpent Ring":"Double Kiss Ring","Eye of the Storm":"Eye of the Table",
        "Void-Touched Circle":"Blackball Circle","Berserker's Knuckle":"Break Knuckle",
        "Saint's Halo Band":"House Saint's Band","Cinder Heart Pendant":"Chalk Heart",
        "Deathwhisper Amulet":"The Hustler's Whisper","Aegis Talisman":"The Safety Talisman",
        "Luminous Crucifix":"The Crossed Cues Pendant","Dragon Soul Pendant":"The Slate and Felt Pendant",
        # Accessories  -  Legendary
        "Godshard Splinter":"Splinter of the Break","Infinity Loop":"The Endless Run",
        "Ring of the Ancients":"The Old Road Ring","Ouroboros":"The Rack Eternal",
        "Last Breath Locket":"The Final Shot Locket","Worldsoul Amulet":"The Felt Soul",
        "Shard of Divinity":"The Diamond Shard","Mark of the Void":"The Blackball Mark",
        # Consumables
        "Health Potion":"Chalk Vial","Super Health Potion":"Premium Chalk Draft",
        "Mega Health Potion":"Champion's Chalk Flask","Revival Charm":"The Re-Rack",
        "Holy Relic":"Holy Water Vial","Dragon Scale":"Iron Shard",
        "Enchanting Scroll":"The Custom Tip Scroll",
    }

    def _migrate_item_list(lst):
        return [ITEM_NAME_MAP.get(x, x) for x in lst]

    def _migrate_item_dict(d):
        return {ITEM_NAME_MAP.get(k, k): v for k, v in d.items()}

    try:
        mig_conn = sqlite3.connect(DB_PATH)
        try:
            mig_conn.row_factory = sqlite3.Row
            mig_c = mig_conn.cursor()
            mig_c.execute("""SELECT user_id,inventory,equipped_weapon,equipped_armor,
                                    equipped_shield,equipped_accessory,enhancements,enchants
                             FROM players""")
            rows = mig_c.fetchall()
            migrated = 0
            for row in rows:
                changed = False
                uid = row["user_id"]
                inv  = sjl(row["inventory"], [])
                new_inv = _migrate_item_list(inv)
                if new_inv != inv: changed = True
                ew  = ITEM_NAME_MAP.get(row["equipped_weapon"],  row["equipped_weapon"])
                ea  = ITEM_NAME_MAP.get(row["equipped_armor"],   row["equipped_armor"])
                es  = ITEM_NAME_MAP.get(row["equipped_shield"],  row["equipped_shield"])
                eac = ITEM_NAME_MAP.get(row["equipped_accessory"], row["equipped_accessory"])
                if ew != row["equipped_weapon"] or ea != row["equipped_armor"] or \
                   es != row["equipped_shield"] or eac != row["equipped_accessory"]:
                    changed = True
                enh = sjl(row["enhancements"], {}); new_enh = _migrate_item_dict(enh)
                if new_enh != enh: changed = True
                enc = sjl(row["enchants"], {});     new_enc = _migrate_item_dict(enc)
                if new_enc != enc: changed = True
                if changed:
                    mig_c.execute("""UPDATE players SET inventory=?,equipped_weapon=?,
                                      equipped_armor=?,equipped_shield=?,equipped_accessory=?,
                                      enhancements=?,enchants=? WHERE user_id=?""",
                        (json.dumps(new_inv), ew, ea, es, eac,
                         json.dumps(new_enh), json.dumps(new_enc), uid))
                    migrated += 1
            mig_conn.commit()
            if migrated > 0:
                logger.info(f"v15 item migration: updated {migrated} player(s)")
        finally:
            mig_conn.close()
    except Exception as e:
        logger.error(f"v15 item migration failed: {e}")

# ── DB HELPERS ────────────────────────────────────────────────────────────────
def _get(table, user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(f"SELECT * FROM {table} WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_shadow(uid):   return _get("shadow_profiles", uid)
def get_player(uid):   return _get("players", uid)

def save_shadow(s):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO shadow_profiles
        (user_id,username,level,exp,total_exp,message_count,
         passive_cooldowns,ascended,last_seen,last_pool,pending_items)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (s["user_id"],s["username"],s["level"],s["exp"],
         safe_int(s.get("total_exp")),s.get("message_count",0),
         s.get("passive_cooldowns","{}"),s.get("ascended",0),
         datetime.now().isoformat(),s.get("last_pool"),
         s.get("pending_items","[]")))
    conn.commit(); conn.close()

# Normalizes pool-hall item names → RPG names at save time (catches loot drops too)
_ITEM_RENAME = {
    # Consumable renames (pool-hall → RPG)
    "Custom Tip Scroll":        "Enchanting Scroll",
    "The Custom Tip Scroll":    "Enchanting Scroll",
    "Chalk Vial":               "Health Potion",
    "Premium Chalk Draft":      "Greater Health Potion",
    "Champion's Chalk Flask":   "Grand Restorative Flask",
    "The Re-Rack":              "Scroll of Revival",
    "The Golden Triangle":      "Holy Water Vial",
    "Slate Fragment":           "Iron Shard",
    # Accessory renames (pool-hall → RPG)
    "Chalk Nub":                "Iron Shard Ring",
    "Worn Tip Wrap":            "Worn Leather Band",
    "Brass Rail Ring":          "Brass Ring",
    "Pocket Marker":            "Scout's Pendant",
    "Road Player's Coin":       "Traveler's Coin",
    "Silk Tip Ring":            "Silk Band",
    "Chalk Cross Pendant":      "Rune Cross Pendant",
    "Black Ball Stud":          "Obsidian Stud",
    "Red Ball Band":            "Bloodstone Band",
    "Road Shark Signet":        "Shadowmark Signet",
    "Hustler's Tooth":          "Hunter's Fang",
    "Chalk Bead Necklace":      "Crystal Bead Necklace",
    "The Action Coin":          "Fortune Coin",
    "Break Master's Clasp":     "War Master's Clasp",
    "Diamond Sight Medallion":  "Hawk Eye Medallion",
    "Ghost Ball Loop":          "Phantom Loop",
    "Closer's Band":            "Warrior's Band",
    "English Coil":             "Mage's Coil",
    "Slate Heart":              "Stone Heart",
    "Shark Tooth Chain":        "Beast Fang Chain",
    "Road Player's Compass":    "Traveler's Compass",
    "The Break Torc":           "The Storm Torc",
    "Double Kiss Ring":         "Twin Strike Ring",
    "Eye of the Table":         "Eye of the Void",
    "Blackball Circle":         "Void Circle",
    "Break Knuckle":            "War Knuckle",
    "House Saint's Band":       "Cleric's Band",
    "Chalk Heart":              "Runed Heart",
    "The Hustler's Whisper":    "The Shadow Whisper",
    "The Safety Talisman":      "Guardian's Talisman",
    "The Crossed Cues Pendant": "The Crossed Blades Pendant",
    "The Slate and Felt Pendant": "The Iron and Flame Pendant",
    "Splinter of the Break":    "Shard of the Void",
    "The Endless Run":          "Ring of the Endless",
    "The Old Road Ring":        "The Warlord's Ring",
    "The Rack Eternal":         "The Eternal Ring",
    "The Final Shot Locket":    "The Last Stand Locket",
    "The Felt Soul":            "The Soul Amulet",
    "The Diamond Shard":        "The Divine Shard",
    "The Blackball Mark":       "The Void Mark",
    "Iron Chalk Ring":          "Silver Prayer Beads",
    "Chalk Beads":              "Wooden Prayer Beads",
    # Weapons
    "Cracked House Cue":   "Rusty Shortsword",
    "Worn Practice Cue":   "Iron Broadsword",
    "Graphite Break Cue":  "Steel Knight Sword",
    "Heavy Breaker Staff": "Warlord's Edge",
    "The Rack Splitter":   "Ruinblade",
    "Chalked Finger":      "Gnarled Twig Wand",
    "Blue Diamond Chalk":  "Crystal Core Wand",
    "Blackwood Bridge Stick": "Warlock's Dread Staff",
    "The Extension":       "Void Channel Staff",
    "The Grand Bridge":    "The Mind's Eye",
    "Bent Triangle":       "Frayed Hunting Bow",
    "Standard Magic Rack": "Repeating Crossbow",
    "Precision Rack":      "Ranger's Marked Bow",
    "Diamond Rack":        "Warden's Gale Bow",
    "The Perfect Break Rack": "The Dead Reckoning",
    "Chalk Shiv":          "Rusty Shiv",
    "Mushroom Tip Blade":  "Iron Stiletto",
    "Ferrule Dart":        "Bloodsteel Shuriken",
    "Twin Tip Blades":     "Shadow Death Star",
    "The Ball Return":     "Death's Whisper",
    "Chalk Beads":         "Wooden Prayer Beads",
    "Iron Chalk Ring":     "Silver Prayer Beads",
    "The Spot Marker":     "Holy Judge's Cross",
    "The Crossed Cues":    "Grand Inquisitor's Cross",
    "The Diamond Staff":   "The Final Judgment",
    # Armors
    "Bar Room Vest":       "Rusty Iron Vest",
    "Padded Cue Jacket":   "Rusty Iron Vest",
    "Slate Guard":         "Soldier's Plating",
    "Red Cloth Plate":     "Steel Breastplate",
    "Black Ball Plate":    "Warlord's Battle Plate",
    "Diamond Felt Armor":  "Dragonscale Plate",
    "Worn Chalk Coat":     "Worn Cloth Robe",
    "Green Baize Robe":    "Arcane Weave Robe",
    "White Glove Wrap":    "Sorcerer's Mantle",
    "Blacklight Cloak":    "Void-Touched Robe",
    "The Nap Robe":        "Archmage's Sanctum Robe",
    "Corner Pocket Vest":  "Padded Hunting Vest",
    "Rail Leather Chest":  "Scout's Leathers",
    "Diamond Point Plate": "Forest Scout Armor",
    "Red Baize Brigandine":"Strider's Marked Armor",
    "The Rack Scale":      "The Shadowmark Leather",
    "Hustle Coat":         "Torn Leather Vest",
    "Midnight Felt Coat":  "Rogue's Leathers",
    "The Sneak Mesh":      "Nightstalker's Vest",
    "Backdoor Harness":    "Phantom Leathers",
    "The Ghost Coat":      "The Shadow Wrap",
    "Chalk Cloth Vestments":"Simple Cloth Vestment",
    "The Rule Book Robe":  "Blessed Cloth Robe",
    "The Referee Hood":    "Sanctified Robe",
    "The Tournament Cloak":"High Cleric's Vestment",
    "The House Saint Surplice":"The High Saint's Vestment",
    # Shields
    "Cracked Rack Shield": "Wooden Buckler",
    "Iron Triangle":       "Soldier's Kite Shield",
    "The Break Shield":    "Knight's Bulwark",
    "Black Ball Barrier":  "Holy Pavise",
    "The Diamond Aegis":   "Celestial Bulwark",
    # Loot-table pool-themed items → RPG names
    "Rack Cloth Vest":     "Rustic Cloth Vest",
    "Reinforced Chalk Coat": "Reinforced Hide Coat",
    "Ferrule Dart":        "Bloodsteel Shuriken",
    "Toughened Rail Coat": "Toughened Leather Coat",
    "Iron Rail Guard":     "Iron Wall Shield",
    "The Chalk Wall":      "The Stone Wall",
    "The Diamond Rack":    "The Crystal Barrier",
    "Legendary Cue Coat":  "Legendary Runecoat",
}

def save_player(p):
    # Normalize old item names → new RPG names on every save
    inv = sjl(p.get("inventory"), [])
    inv = [_ITEM_RENAME.get(i, i) for i in inv]
    p["inventory"] = json.dumps(inv)
    for slot in ("equipped_weapon", "equipped_armor", "equipped_shield", "equipped_accessory"):
        if p.get(slot) in _ITEM_RENAME:
            p[slot] = _ITEM_RENAME[p[slot]]
    enh = sjl(p.get("enhancements"), {})
    if any(k in _ITEM_RENAME for k in enh):
        p["enhancements"] = json.dumps({_ITEM_RENAME.get(k, k): v for k, v in enh.items()})
    enc = sjl(p.get("enchants"), {})
    if any(k in _ITEM_RENAME for k in enc):
        p["enchants"] = json.dumps({_ITEM_RENAME.get(k, k): v for k, v in enc.items()})
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    fields = [
        "user_id","username","hp","max_hp","exp","level","total_exp",
        "gold","wins","losses","quests_done","heals_given","dodges",
        "crafts_done","perm_dmg_bonus","titles","active_title",
        "class_id","class_path","all_skills","stat_points","stats",
        "inventory","passive_cooldowns",
        "equipped_weapon","equipped_armor","equipped_shield","equipped_accessory",
        "defeated_until","invincible_until","distracted_until","entangled_until",
        "frozen_until","stunned_until","vanish_until",
        "poison_until","poison_damage","poison_last_tick",
        "burn_until","burn_damage","burn_last_tick",
        "ward_until","exposed_until","branded_until",
        "bleed_until","bleed_damage","bleed_last_tick",
        "hexed_until","weakened_until","blessed_until",
        "healing_blocked_until","revival_blocked_until","silenced_until",
        "temp_hp_bonus","temp_hp_until",
        "recent_attackers","contract_target","contract_until",
        "charging_killshot","steady_aim_target","steady_aim_stacks",
        "mark_first_hit","deadeye_kill_bonus","spell_cast_count",
        "holy_field_until","devotion_charge",
        "last_daily","last_quest","last_train","last_explore",
        "explore_count_today","explore_date","shop_discount_until",
        "guild_id","prestige_count","prestige_skills","shadow_level_at_ascension","created_at",
        "DEX","LUK","enhancements","enchants",
        "last_dungeon","last_pool","last_defeated_by",
        "item_reinforce_data","daily_objectives","daily_obj_date",
        "total_reinforces","total_ascensions","total_obj_completed",
        "kill_streak","max_kill_streak","revenge_target","revenge_expires",
        "kills_today","kills_today_date","last_claim","claim_streak","pvp_history",
        "married_to_id","married_to_name","married_at",
        "def_reflect_until",
    ]
    vals = [p.get(f) for f in fields]
    placeholders = ",".join(["?"]*len(fields))
    col_str = ",".join(fields)
    c.execute(f"INSERT OR REPLACE INTO players ({col_str}) VALUES({placeholders})", vals)
    conn.commit(); conn.close()

def get_or_create_shadow(uid, username):
    s = get_shadow(uid)
    if not s:
        s = {"user_id":uid,"username":username,"level":1,"exp":0,
             "total_exp":0,"message_count":0,"passive_cooldowns":"{}",
             "ascended":0,"last_seen":datetime.now().isoformat()}
        save_shadow(s)
    return s

def get_guild(gid):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    c = conn.cursor(); c.execute("SELECT * FROM guilds WHERE guild_id=?", (gid,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def get_guild_by_name(name):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM guilds WHERE LOWER(name)=LOWER(?)", (name,))
    row = c.fetchone(); conn.close()
    return dict(row) if row else None

def get_active_war(gid1, gid2=None):
    """Return active war involving gid1 (optionally against gid2)."""
    conn_gw = sqlite3.connect(DB_PATH); conn_gw.row_factory = sqlite3.Row
    c_gw = conn_gw.cursor()
    if gid2:
        c_gw.execute("""SELECT * FROM guild_wars WHERE active=1 AND expires_at > ?
                        AND ((guild1_id=? AND guild2_id=?) OR (guild1_id=? AND guild2_id=?))""",
                     (datetime.now().isoformat(), gid1, gid2, gid2, gid1))
    else:
        c_gw.execute("""SELECT * FROM guild_wars WHERE active=1 AND expires_at > ?
                        AND (guild1_id=? OR guild2_id=?)""",
                     (datetime.now().isoformat(), gid1, gid1))
    row = c_gw.fetchone()
    conn_gw.close()
    return dict(row) if row else None

def save_guild(g):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO guilds
        (guild_id,name,leader_id,members,level,exp,bank,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (g.get("guild_id"),g["name"],g["leader_id"],g["members"],
         safe_int(g.get("level"),1),safe_int(g.get("exp")),
         safe_int(g.get("bank")),
         g.get("created_at",datetime.now().isoformat())))
    conn.commit(); conn.close()

def add_guild_exp(g, amount):
    msgs = []; g["exp"] = safe_int(g.get("exp")) + amount
    max_lv = max(GUILD_PERKS.keys())
    while safe_int(g.get("level"),1) < max_lv and \
          g["exp"] >= guild_exp_for_level(safe_int(g.get("level"),1)):
        g["exp"] -= guild_exp_for_level(safe_int(g.get("level"),1))
        g["level"] = safe_int(g.get("level"),1) + 1
        msgs.append(f"🏰 Hall leveled up to {g['level']}! "
                    f"{GUILD_PERKS.get(g['level'],{}).get('desc','')}")
    return msgs

def new_player(s):
    """Create a new RPG player from shadow profile."""
    slvl = s["level"]
    p = {
        "user_id": s["user_id"], "username": s["username"],
        "hp": max_hp_for_level(slvl), "max_hp": max_hp_for_level(slvl),
        "exp": 0, "level": slvl, "total_exp": safe_int(s.get("total_exp")),
        "gold": max(50, slvl * 10), "wins": 0, "losses": 0,
        "quests_done": 0, "heals_given": 0, "dodges": 0,
        "crafts_done": 0, "perm_dmg_bonus": 0,
        "titles": json.dumps(["Adventurer"]),
        "active_title": "Adventurer",
        "class_id": None, "class_path": None,
        "all_skills": json.dumps([]),
        "stat_points": slvl * 3 + slvl // 5,
        "stats": json.dumps(DEFAULT_STATS.copy()),
        "inventory": json.dumps(["Health Potion", "Health Potion"]),
        "passive_cooldowns": json.dumps({}),
        "equipped_weapon": None, "equipped_armor": None,
        "equipped_shield": None, "equipped_accessory": None,
        "defeated_until": None, "invincible_until": None,
        "distracted_until": None, "entangled_until": None,
        "frozen_until": None, "stunned_until": None,
        "vanish_until": None, "bleed_until": None,
        "bleed_damage": 0, "bleed_last_tick": None,
        "hexed_until": None, "weakened_until": None,
        "blessed_until": None, "healing_blocked_until": None,
        "revival_blocked_until": None, "silenced_until": None,
        "temp_hp_bonus": 0, "temp_hp_until": None,
        "recent_attackers": json.dumps([]),
        "contract_target": None, "contract_until": None,
        "charging_killshot": 0, "steady_aim_target": None,
        "steady_aim_stacks": 0, "mark_first_hit": 1,
        "deadeye_kill_bonus": 0, "spell_cast_count": 0,
        "holy_field_until": None, "devotion_charge": 0,
        "last_daily": None, "last_quest": None,
        "last_train": None, "last_explore": None,
        "explore_count_today": 0, "explore_date": None,
        "shop_discount_until": None,
        "guild_id": None, "prestige_count": 0,
        "shadow_level_at_ascension": slvl,
        "created_at": datetime.now().isoformat(),
        "item_reinforce_data": "{}",
        "daily_objectives":    "[]",
        "daily_obj_date":      None,
        "total_reinforces":    0,
        "total_ascensions":    0,
        "total_obj_completed": 0,
    }
    # Transfer any pending items from shadow profile
    s_pending = sjl(s.get("pending_items"), [])
    if s_pending:
        p["inventory"] = json.dumps(
            sjl(p.get("inventory"), []) + s_pending)
        s["pending_items"] = json.dumps([])
    save_player(p)
    s["ascended"] = 1; save_shadow(s)
    return p

def sync_levels(p, s):
    changed = False
    if s["level"] > p["level"]:
        diff = s["level"] - p["level"]
        p["level"] = s["level"]
        p["max_hp"] = max_hp_for_level(p["level"])
        if p["hp"] > p["max_hp"]: p["hp"] = p["max_hp"]
        p["stat_points"] = safe_int(p.get("stat_points")) + diff * 3
        changed = True
    if p["level"] > s["level"]:
        s["level"] = p["level"]; s["exp"] = 0; changed = True
    if safe_int(p.get("total_exp")) > safe_int(s.get("total_exp")):
        s["total_exp"] = safe_int(p.get("total_exp")); changed = True
    if safe_int(s.get("total_exp")) > safe_int(p.get("total_exp")):
        p["total_exp"] = safe_int(s.get("total_exp")); changed = True
    return changed

# ── CORE HELPERS ──────────────────────────────────────────────────────────────
def award_title(p, title):
    titles = safe_titles(p)
    if title not in titles:
        titles.append(title)
        p["titles"] = json.dumps(titles)
        return True
    return False

def check_titles(p):
    new = []; earned = safe_titles(p)
    for title, data in TITLES.items():
        if title in earned: continue
        t, v = data["type"], data["threshold"]
        if   t == "level"           and p["level"]                              >= v: pass
        elif t == "wins"            and p["wins"]                               >= v: pass
        elif t == "quests"          and p["quests_done"]                        >= v: pass
        elif t == "heals"           and p["heals_given"]                        >= v: pass
        elif t == "dodges"          and p["dodges"]                             >= v: pass
        elif t == "crafts"          and safe_int(p.get("crafts_done"))          >= v: pass
        elif t == "prestige"        and safe_int(p.get("prestige_count"))       >= v: pass
        elif t == "reinforce"       and safe_int(p.get("total_reinforces"))     >= v: pass
        elif t == "ascensions"      and safe_int(p.get("total_ascensions"))     >= v: pass
        elif t == "objectives_done" and safe_int(p.get("total_obj_completed"))  >= v: pass
        else: continue
        earned.append(title); new.append(title)
    p["titles"] = json.dumps(earned)
    return new

def add_exp(p, amount, weather=None):
    if p["level"] >= 100: return [], False
    if weather: amount = round(amount * weather.get("exp_mod", 1.0))
    gid = p.get("guild_id")
    if gid and str(gid) != "None":
        g = get_guild(gid)
        if g:
            bonus = GUILD_PERKS.get(safe_int(g.get("level"),1),{}).get("exp_bonus",0)
            amount = round(amount * (1 + bonus))
    # Marriage bonus: +3% EXP
    if p.get("married_to_id"):
        amount = round(amount * 1.03)
    msgs = []; leveled_up = False
    p["exp"]      += max(0, amount)
    p["total_exp"] = safe_int(p.get("total_exp")) + max(0, amount)
    while p["level"] < 100 and p["exp"] >= exp_for_level(p["level"]):
        p["exp"] -= exp_for_level(p["level"])
        p["level"] += 1; leveled_up = True
        p["max_hp"]      = max_hp_for_level(p["level"])
        p["hp"]          = p["max_hp"]
        points_per_level = 6 if p["level"] > 20 else 3
        p["stat_points"] = safe_int(p.get("stat_points")) + points_per_level
        msgs.append(f"⬆️ *LEVEL UP!* {p['username']} is now *Level {p['level']}*! +{points_per_level} stat points.")
        if p["level"] == 5 and not p.get("class_id"):
            msgs.append("⚔️ You can now choose a class! Use /class.")
        if p["level"] == 10 and p.get("class_id") and not p.get("class_path"):
            msgs.append("🌟 Choose your path! Use /prestige.")
        if p["level"] == 30 and p.get("class_path"):
            _auto_advance_class(p, 30)
        if p["level"] == 60 and p.get("class_path"):
            _auto_advance_class(p, 60)
        if p["level"] == 100 and p.get("class_path"):
            _auto_advance_class(p, 100)
            msgs.append("🏆 *LEVEL 100!* You have reached the pinnacle!")
            award_title(p, "Century Break")
        for t in check_titles(p):
            msgs.append(f"🏅 New title: *{t}*!")
    # Award pet EXP (15% of player EXP)
    if amount > 0 and p.get("user_id"):
        pet_msg = give_pet_exp(p["user_id"], amount)
        if pet_msg:
            msgs.append(pet_msg)
    return msgs, leveled_up

def give_pet_exp(owner_id, raw_amount):
    """Award exp to owner's active pet. Returns level-up message or ''."""
    pet = get_active_pet_record(owner_id)
    if not pet: return ""
    if pet.get("level", 1) >= 100: return ""
    amount = max(1, round(raw_amount * 0.15))
    pet["exp"] = pet.get("exp", 0) + amount
    leveled = False
    msg = ""
    while pet["level"] < 100 and pet["exp"] >= pet_exp_for_level(pet["level"]):
        pet["exp"] -= pet_exp_for_level(pet["level"])
        pet["level"] += 1
        leveled = True
    if leveled:
        sp    = PET_SPECIES.get(pet.get("species"), {})
        pname = pet.get("nickname") or sp.get("name", "Your pet")
        emoji = sp.get("emoji", "🐾")
        msg = f"{emoji} *{pname}* leveled up to *Level {pet['level']}*!"
        # check for ability unlock at L10
        if pet["level"] == 10:
            da = sp.get("def_ability")
            if da:
                ab = PET_DEF_ABILITIES.get(da, {})
                msg += f"\n🔓 *{ab.get('name','Ability')}* defensive ability unlocked!"
        # milestones
        for milestone in [25, 50, 75, 100]:
            if pet["level"] == milestone:
                msg += f"\n🏆 Milestone: Pet reached Level {milestone}!"
    # Save pet
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("UPDATE pets SET exp=?, level=? WHERE pet_id=?",
                  (pet["exp"], pet["level"], pet["pet_id"]))
        conn.commit()
    finally:
        conn.close()
    return msg

def add_shadow_exp(s, amount):
    if s["level"] >= 100: return [], False
    msgs = []; leveled_up = False
    s["exp"]      += max(0, amount)
    s["total_exp"] = safe_int(s.get("total_exp")) + max(0, amount)
    while s["level"] < 100 and s["exp"] >= exp_for_level(s["level"]):
        s["exp"] -= exp_for_level(s["level"])
        s["level"] += 1; leveled_up = True
        msgs.append(f"📈 *{s['username']}* reached *Level {s['level']}*!")
    return msgs, leveled_up

def _auto_advance_class(p, threshold):
    """Automatically advance class at tier thresholds 30, 60, 100."""
    cid  = p.get("class_id")
    path = p.get("class_path")
    if not cid or not path: return
    cls = CLASS_TREE.get(cid, {})
    line = cls.get("line")
    if not line: return
    path_list = CLASS_PATHS.get(line, {}).get(path, [])
    # Find next class in path
    tier_map = {10: 0, 30: 1, 60: 2, 100: 3}
    idx = tier_map.get(threshold)
    if idx is None or idx >= len(path_list): return
    new_cid  = path_list[idx]
    new_cls  = CLASS_TREE.get(new_cid)
    if not new_cls: return
    p["class_id"] = new_cid
    # Apply stat bonuses
    sd = safe_stats(p)
    for stat, bonus in new_cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat, 5) + bonus
    p["stats"] = json.dumps(sd)
    # Unlock new skill
    new_skills = sjl(p.get("all_skills"), [])
    for skill in new_cls.get("skills", []):
        if skill["name"] not in [s["name"] for s in new_skills]:
            new_skills.append(skill)
    p["all_skills"] = json.dumps(new_skills)

def add_item(p, item_name):
    inv = sjl(p.get("inventory"), [])
    inv.append(item_name)
    p["inventory"] = json.dumps(inv)

def get_random_item_by_rarity(rarity):
    """Get a random item of a given rarity from all item pools."""
    pool = []
    for name, data in WEAPONS.items():
        if data["rarity"] == rarity: pool.append(name)
    for name, data in ARMORS.items():
        if data["rarity"] == rarity: pool.append(name)
    for name, data in ACCESSORIES.items():
        if data["rarity"] == rarity: pool.append(name)
    return random.choice(pool) if pool else None

def roll_loot_table(loot_table, p=None):
    luk_bonus = (get_stat(p, "LUK") * 0.005) if p else 0
    for item_name, chance in loot_table:
        weapon_boost = 1.8 if item_name in WEAPONS else 1.0
        adjusted = min(chance * weapon_boost + luk_bonus, 0.95)
        if random.random() < adjusted:
            return item_name
    return None

def update_recent_attackers(defender, attacker_id):
    now = datetime.now()
    recent = sjl(defender.get("recent_attackers"), [])
    recent = [r for r in recent
              if (now - datetime.fromisoformat(r["ts"])).total_seconds() < 1800]
    if not any(r["uid"] == attacker_id for r in recent):
        recent.append({"uid": attacker_id, "ts": now.isoformat()})
    defender["recent_attackers"] = json.dumps(recent)

def get_recent_attackers(p):
    now = datetime.now()
    recent = sjl(p.get("recent_attackers"), [])
    return [r["uid"] for r in recent
            if (now - datetime.fromisoformat(r["ts"])).total_seconds() < 1800]

# ── COMBAT CARD ───────────────────────────────────────────────────────────────
# combat_cards removed in v14  -  using inline send+auto-delete instead

# ── IDLE REWARDS ──────────────────────────────────────────────────────────────
async def check_idle_reward(user, s, p, bot, chat_id):
    last_seen = s.get("last_seen")
    if not last_seen: return
    try:
        away = (datetime.now() - datetime.fromisoformat(last_seen)).total_seconds() / 3600
    except Exception:
        return
    if away < 1: return

    tier = None
    for t in IDLE_TIERS:
        if t["min_hours"] <= away < t["max_hours"]:
            tier = t; break
    if not tier: tier = IDLE_TIERS[-1]

    gold_reward = tier["gold"]
    exp_reward  = tier["exp"]
    item_found  = None

    for rarity, chance in tier["item_chances"]:
        if random.random() < chance:
            item_found = get_random_item_by_rarity(rarity)
            break

    # Build flavor
    line = get_class_line(p) if p else None
    flavor = IDLE_FLAVOR.get(line, IDLE_FLAVOR[None])
    hours_str = f"{int(away)}h" if away < 48 else f"{int(away/24)}d"

    msg = (f"🎱 *{user.first_name}* returns after *{hours_str}* away\n"
           f"💰 +{gold_reward} gold\n"
           f"✨ +{exp_reward} EXP")
    if item_found:
        rarity_tag = ""
        for pool in [WEAPONS, ARMORS, ACCESSORIES]:
            if item_found in pool:
                r = pool[item_found].get("rarity","")
                rarity_tag = RARITY_EMOJI.get(r,"")
                break
        msg += f"\n🎒 +{rarity_tag} *{item_found}*"

    if p:
        p["gold"] = p.get("gold", 0) + gold_reward
        if item_found: add_item(p, item_found)
        lmsgs, leveled = add_exp(p, exp_reward)
        save_player(p)
        if leveled and p["level"] % 10 == 0:
            await announce(bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}*! 🎱",
                permanent=True)
    else:
        lmsgs, leveled = add_shadow_exp(s, exp_reward)
        if leveled and s["level"] % 10 == 0:
            asyncio.create_task(announce(bot, chat_id,
                f"📈 *{s['username']}* reached *Level {s['level']}*!",
                permanent=True))

    await announce(bot, chat_id, msg, delay=8)

async def gear_cmd(update, context):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!"); return

    lines = [f"🎽 *{p['username']}'s Equipped Gear*\n"]

    # Weapon
    weap_name = p.get("equipped_weapon")
    if weap_name and weap_name in WEAPONS:
        w = WEAPONS[weap_name]
        enh = get_enhancement(p, weap_name)
        enc = get_enchant(p, weap_name)
        base_atk = w["atk"]
        enh_bonus = enh * 2
        total_atk = base_atk + enh_bonus
        rarity = RARITY_EMOJI.get(w["rarity"], "")
        lines.append(f"⚔️ *Weapon*")
        lines.append(f"{rarity} {weap_name}")
        lines.append(f"ATK: {base_atk} base + {enh_bonus} enhancement = *{total_atk} total*")
        if enh > 0:
            lines.append(f"Enhancement: *+{enh}* {'⭐' * enh}")
        if enc:
            all_encs = get_all_enchants(p, weap_name)
            if len(all_encs) > 1:
                for e in all_encs:
                    lines.append(f"✨ {e['id'].capitalize()}  -  {e['desc']}")
            else:
                lines.append(f"Enchant: ✨ *{enc[0]['id'].capitalize() if isinstance(enc, list) else enc['id'].capitalize()}*  -  _{enc[0]['desc'] if isinstance(enc, list) else enc['desc']}_")
    else:
        lines.append(f"⚔️ *Weapon*  -  None")

    lines.append("")

    # Armor
    armr_name = p.get("equipped_armor")
    if armr_name and armr_name in ARMORS:
        a = ARMORS[armr_name]
        enh = get_enhancement(p, armr_name)
        enc = get_enchant(p, armr_name)
        base_def = a["def"]
        enh_bonus = enh * 2
        total_def = base_def + enh_bonus
        rarity = RARITY_EMOJI.get(a["rarity"], "")
        lines.append(f"🛡️ *Armor*")
        lines.append(f"{rarity} {armr_name}")
        lines.append(f"DEF: {base_def} base + {enh_bonus} enhancement = *{total_def} total*")
        if enh > 0:
            lines.append(f"Enhancement: *+{enh}* {'⭐' * enh}")
        if enc:
            all_encs = get_all_enchants(p, armr_name)
            for e in all_encs:
                lines.append(f"✨ *{e['id'].capitalize()}*  -  _{e['desc']}_")
    else:
        lines.append(f"🛡️ *Armor*  -  None")

    lines.append("")

    # Shield / Claw
    shld_name = p.get("equipped_shield")
    if shld_name and shld_name in SHIELDS:
        s_data = SHIELDS[shld_name]
        enh = get_enhancement(p, shld_name)
        enh_bonus = enh * 2
        rarity = RARITY_EMOJI.get(s_data["rarity"], "")
        is_claw = s_data.get("type") == "claw"
        if is_claw:
            base_stat = s_data.get("atk", 0)
            total_stat = base_stat + enh_bonus
            lines.append(f"🗡️ *Claw* (shield slot)")
            lines.append(f"{rarity} {shld_name}")
            lines.append(f"ATK: {base_stat} base + {enh_bonus} enhancement = *{total_stat} total*")
        else:
            base_stat = s_data.get("def", 0)
            total_stat = base_stat + enh_bonus
            lines.append(f"🔰 *Shield*")
            lines.append(f"{rarity} {shld_name}")
            lines.append(f"DEF: {base_stat} base + {enh_bonus} enhancement = *{total_stat} total*")
        if enh > 0:
            lines.append(f"Enhancement: *+{enh}* {'⭐' * enh}")
    else:
        lines.append(f"🔰 *Shield / Claw*  -  None")

    lines.append("")

    # Accessory
    acc_name = p.get("equipped_accessory")
    if acc_name and acc_name in ACCESSORIES:
        acc = ACCESSORIES[acc_name]
        enc = get_enchant(p, acc_name)
        rarity = RARITY_EMOJI.get(acc["rarity"], "")
        lines.append(f"💍 *Accessory*")
        lines.append(f"{rarity} {acc_name}")
        lines.append(f"_{acc['desc']}_")
        for k, v in acc.get("effect", {}).items():
            if k == "all_stats":
                lines.append(f"+{v} to all stats")
            elif k in ("STR","AGI","INT","WIS","DEX","LUK","DEF"):
                lines.append(f"+{v} {k}")
            elif k == "atk":
                lines.append(f"+{v} ATK")
            elif k == "hp":
                lines.append(f"+{v} max HP")
            elif k == "dodge_bonus":
                lines.append(f"+{int(v*100)}% dodge chance")
            elif k == "crit_bonus":
                lines.append(f"+{int(v*100)}% crit chance")
            elif k == "heal_bonus":
                lines.append(f"+{int(v*100)}% healing received")
            elif k == "gold_bonus":
                lines.append(f"+{int(v*100)}% gold earned")
            elif k == "lifesteal_flat":
                lines.append(f"+{v} HP lifesteal per hit")
            elif k == "block_chance":
                lines.append(f"+{int(v*100)}% block chance")
        all_encs = get_all_enchants(p, acc_name)
        for e in all_encs:
            lines.append(f"✨ *{e['id'].capitalize()}*  -  _{e['desc']}_")
    else:
        lines.append(f"💍 *Accessory*  -  None")

    lines.append("")
    lines.append(f"Total Weapon ATK: *{get_weapon_atk(p)}*")
    lines.append(f"Total Armor DEF: *{get_armor_def(p)}*")
    lines.append(f"\n`/enhance` to upgrade  |  `/enchant` to enchant")

    await send_group(update, "\n".join(lines), permanent=False, delay=120)

# ── RANK ──────────────────────────────────────────────────────────────────────
async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT user_id,username,level,total_exp,class_id FROM players")
    rpg_rows = c.fetchall()
    c.execute("SELECT user_id,username,level,total_exp FROM shadow_profiles")
    shd_rows = c.fetchall()
    conn.close()

    seen = {}
    for row in shd_rows:
        uid = row["user_id"]
        seen[uid] = {"user_id":uid,"username":row["username"],
                     "level":row["level"],"total_exp":safe_int(row["total_exp"]),
                     "type":"shadow","class_id":None}
    for row in rpg_rows:
        uid = row["user_id"]; rlvl = row["level"]; rtex = safe_int(row["total_exp"])
        if uid not in seen or (rlvl,rtex) >= (seen[uid]["level"],seen[uid]["total_exp"]):
            seen[uid] = {"user_id":uid,"username":row["username"],
                         "level":rlvl,"total_exp":rtex,"type":"rpg","class_id":row["class_id"]}

    all_entries = list(seen.values())
    rpg_entries = sorted([e for e in all_entries if e["type"]=="rpg"], key=lambda x: x["total_exp"], reverse=True)
    shd_entries = sorted([e for e in all_entries if e["type"]=="shadow"], key=lambda x: x["total_exp"], reverse=True)
    ranked = rpg_entries + shd_entries

    total  = len(ranked)

    def fmt_ranked(i, e):
        medals = {1:"🥇",2:"🥈",3:"🥉"}
        prefix = medals.get(i+1, f"{i+1}.")
        cls = CLASS_TREE.get(e.get("class_id") or "", {}).get("name", "No Class") if e["type"]=="rpg" else "Shadow"
        return f"{prefix} *{e['username']}* - Lv {e['level']} - {cls}"

    if context.args and context.args[0].lower() == "wins":
        conn2 = sqlite3.connect(DB_PATH); conn2.row_factory = sqlite3.Row; c2 = conn2.cursor()
        c2.execute("SELECT username, wins, losses, level FROM players ORDER BY wins DESC LIMIT 20")
        rows2 = c2.fetchall(); conn2.close()
        medals2 = {1:"🥇",2:"🥈",3:"🥉"}
        lines2 = ["⚔️ *Top 20  -  PVP Wins*\n"]
        for i2, row2 in enumerate(rows2, 1):
            badge2 = medals2.get(i2, f"#{i2}")
            wl2 = f"{row2['wins']}W / {row2['losses']}L"
            lines2.append(f"{badge2} *{row2['username']}*  -  {wl2} | Lv {row2['level']}")
        await send_group(update, "\n".join(lines2), permanent=False, delay=120); return

    if context.args and context.args[0].lower() == "me":
        pos = next((i+1 for i,e in enumerate(ranked) if e["user_id"]==user.id), None)
        if not pos:
            await send_group(update, "Not ranked yet  -  start chatting!"); return
        start_m = max(0, pos-3); end_m = min(total, pos+2)
        lines = [f"📊 *{user.first_name}'s Rank: #{pos} of {total}*\n"]
        for i, entry in enumerate(ranked[start_m:end_m], start=start_m):
            arrow = "▶️ " if entry["user_id"] == user.id else "    "
            lines.append(f"{arrow}{fmt_ranked(i, entry)}")
        await send_group(update, "\n".join(lines), permanent=False, delay=120); return

    PAGE_SIZE = 10
    page_entries = ranked[:PAGE_SIZE]

    lines = ["🏆 *Hall Rankings*\n"]
    for i, e in enumerate(page_entries):
        lines.append(fmt_ranked(i, e))

    keyboard = []
    if total > PAGE_SIZE:
        keyboard.append([InlineKeyboardButton("➡️ Page 2", callback_data="rank_p_2")])
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try: await update.message.delete()
    except: pass
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(lines)[:4096],
        parse_mode="Markdown",
        reply_markup=markup)

async def rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("rank_p_"): return
    page = int(query.data.split("_")[-1])

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT user_id,username,level,total_exp,class_id FROM players")
    rpg_rows = c.fetchall()
    c.execute("SELECT user_id,username,level,total_exp FROM shadow_profiles")
    shd_rows = c.fetchall()
    conn.close()

    seen = {}
    for row in shd_rows:
        uid = row["user_id"]
        seen[uid] = {"user_id":uid,"username":row["username"],
                     "level":row["level"],"total_exp":safe_int(row["total_exp"]),
                     "type":"shadow","class_id":None}
    for row in rpg_rows:
        uid = row["user_id"]; rlvl = row["level"]; rtex = safe_int(row["total_exp"])
        if uid not in seen or (rlvl,rtex) >= (seen[uid]["level"],seen[uid]["total_exp"]):
            seen[uid] = {"user_id":uid,"username":row["username"],
                         "level":rlvl,"total_exp":rtex,"type":"rpg","class_id":row["class_id"]}

    all_entries = list(seen.values())
    rpg_entries = sorted([e for e in all_entries if e["type"]=="rpg"], key=lambda x: x["total_exp"], reverse=True)
    shd_entries = sorted([e for e in all_entries if e["type"]=="shadow"], key=lambda x: x["total_exp"], reverse=True)
    ranked = rpg_entries + shd_entries

    PAGE_SIZE = 10
    total = len(ranked)
    start = (page-1)*PAGE_SIZE
    end   = start + PAGE_SIZE
    page_entries = ranked[start:end]
    if not page_entries: return

    def fmt(i, e):
        medals = {1:"🥇",2:"🥈",3:"🥉"}
        prefix = medals.get(start+i+1, f"{start+i+1}.")
        cls = CLASS_TREE.get(e.get("class_id") or "", {}).get("name", "No Class") if e["type"]=="rpg" else "Shadow"
        return f"{prefix} *{e['username']}* - Lv {e['level']} - {cls}"

    lines = [f"🏆 *Hall Rankings  -  Page {page}*\n"]
    for i, e in enumerate(page_entries):
        lines.append(fmt(i, e))

    keyboard = []
    if page > 1:
        keyboard.append(InlineKeyboardButton(f"⬅️ Page {page-1}", callback_data=f"rank_p_{page-1}"))
    if end < total:
        keyboard.append(InlineKeyboardButton(f"➡️ Page {page+1}", callback_data=f"rank_p_{page+1}"))
    markup = InlineKeyboardMarkup([keyboard]) if keyboard else None

    await query.edit_message_text(
        text="\n".join(lines)[:4096],
        parse_mode="Markdown",
        reply_markup=markup)

# ── ATTACK ────────────────────────────────────────────────────────────────────
async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    au = update.effective_user
    a  = get_player(au.id)
    if not a:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(a):
        await send_group(update, _defeated_msg(a), delay=15); return
    if is_vanished(a):
        await send_group(update, "👻 You're vanished  -  you can't attack while hidden.", delay=9); return
    if cannot_attack(a):
        await send_group(update, "⚡ You're stunned or rooted  -  can't attack right now.", delay=9); return

    chat_id = update.effective_chat.id

    # ── Instance routing: boss > group raid > solo raid > PvP ──────────────
    # If attacker is in a boss fight, route to boss
    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    if boss_dict and au.id in [u["id"] for u in boss_dict["participants"]]:
        await _attack_boss(update, context, a, boss_dict, chat_id); return

    # If attacker is in a group raid
    raid = active_raids.get(chat_id)
    if raid and raid.get("in_progress") and au.id in [u["id"] for u in raid["party"]]:
        await raidstrike_cmd(update, context); return

    # If attacker is in a solo raid
    if au.id in active_soloraids:
        await solostrike_cmd(update, context); return

    # Block if attacker is in any boss fight in any chat
    a_boss, _ = in_active_boss(au.id, chat_id)
    if a_boss and not (boss_dict and au.id in [u["id"] for u in boss_dict["participants"]]):
        await send_group(update, "⚔️ You're in a boss fight  -  use /attack to strike the boss!", delay=9); return

    # ── PvP below ──────────────────────────────────────────────────────────
    chat = chat_id
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /attack to strike them!", delay=9); return

    du = update.message.reply_to_message.from_user
    if du.id == au.id:
        await send_group(update, "You can't attack yourself.", delay=9); return
    d = get_player(du.id)
    if not d:
        await send_group(update, f"{du.first_name} hasn't ascended yet!", delay=9); return
    if is_defeated(d):
        await send_group(update, f"💀 {d['username']} is already defeated!", delay=9); return
    if is_invincible(d):
        await send_group(update, f"🛡️ {d['username']} is *Still Recovering*  -  invincible for now.", delay=9); return
    raid_d, kind_d = in_active_raid(du.id, chat)
    if raid_d:
        await send_group(update, f"⚔️ *{d['username']}* is in a raid right now  -  can't be targeted!", delay=9); return
    # Block attack if target is in a boss instance
    t_boss, _ = in_active_boss(du.id, chat_id)
    if t_boss:
        await send_group(update, f"⚔️ *{d['username']}* is in a boss fight  -  can't be targeted!", delay=9); return

    # Block friendly fire within the same guild
    if a.get("guild_id") and str(a.get("guild_id")) == str(d.get("guild_id")):
        g = get_guild(a["guild_id"])
        gname = g["name"] if g else "your Guild"
        await send_group(update,
            f"🏰 *{d['username']}* is in *{gname}* — you can't attack your own guild members!",
            delay=9); return

    # Block attack if target has been offline for 30+ minutes
    target_last_seen = d.get("last_seen")
    if target_last_seen:
        try:
            away_secs = (datetime.now() - datetime.fromisoformat(target_last_seen)).total_seconds()
            if away_secs > 1800:
                await send_group(update, f"💤 *{d['username']}* stepped away from the table  -  can't attack offline players.", delay=9)
                try:
                    await context.bot.send_message(
                        chat_id=du.id,
                        text=f"🎱 *{a['username']}* tried to attack you while you were away!\nHead back to the table before someone else takes their shot.",
                        parse_mode="Markdown")
                except Exception:
                    pass
                return
        except Exception:
            pass

    w    = get_weather()
    chat = update.effective_chat.id
    try: await update.message.delete()
    except: pass

    # ── Charged killshot check ────────────────────────────────────────────────
    if safe_int(a.get("charging_killshot")):
        a["charging_killshot"] = 0
        dmg_after_def = get_stat(a, "AGI") * 4
        action = (f"🎯 *KILLSHOT FIRED!* *{a['username']}* → *{d['username']}*  -  "
                  f"AGI×4 = *{dmg_after_def} damage!* Cannot be dodged!")
        d["hp"] = max(0, d["hp"] - dmg_after_def)
        update_recent_attackers(d, au.id)
        lvl_msgs = []
        if d["hp"] <= 0:
            d["hp"] = 0
            d["defeated_until"] = (datetime.now() + timedelta(hours=6)).isoformat()
            d["last_defeated_by"] = f"{a['username']} (Killshot)"
            d["kill_streak"] = 0
            d["revenge_target"] = au.id
            d["revenge_expires"] = (datetime.now() + timedelta(hours=24)).isoformat()
            asyncio.create_task(_notify_defeat(update.get_bot(), d, a['username'] + " (Killshot)"))
            exp_loss = round(d.get("exp",0) * 0.10)
            d["exp"]  = max(0, d.get("exp",0) - exp_loss)
            d["losses"] = d.get("losses",0) + 1
            a["wins"]   = a.get("wins",0) + 1
            # Killstreak for attacker
            a["kill_streak"] = safe_int(a.get("kill_streak")) + 1
            if a["kill_streak"] > safe_int(a.get("max_kill_streak")):
                a["max_kill_streak"] = a["kill_streak"]
            today_str = datetime.now().strftime("%Y-%m-%d")
            if a.get("kills_today_date") != today_str:
                a["kills_today"] = 0; a["kills_today_date"] = today_str
            a["kills_today"] = safe_int(a.get("kills_today")) + 1
            hist_ks = sjl(d.get("pvp_history"), [])
            hist_ks.insert(0, {"attacker": a["username"], "dmg": "KO",
                               "ts": datetime.now().strftime("%m/%d %H:%M")})
            d["pvp_history"] = json.dumps(hist_ks[:5])
            for _desc, _exp, _gold in track_objective(a, "pvp_win"):
                a["gold"] = a.get("gold",0) + _gold; add_exp(a, _exp)
            exp_gain = 60 + a["level"] * 8
            lmsgs, leveled = add_exp(a, exp_gain, w); lvl_msgs = lmsgs
            action += f"\n💀 *{d['username']}* DEFEATED! +{exp_gain} EXP to {a['username']}."
            if leveled and a["level"] % 10 == 0:
                asyncio.create_task(announce(update.get_bot(), chat,
                    f"🎉 *{a['username']}* reached *Level {a['level']}*! ⚔️", permanent=True))
        check_titles(a); check_titles(d)
        save_player(a); save_player(d)
        if d["hp"] > 0:
            hp_pct = d["hp"] / max(1, d["max_hp"])
            filled = round(hp_pct * 10)
            bar = "█" * filled + "░" * (10 - filled)
            action += f"\n❤️ {d['username']}: *{d['hp']}/{d['max_hp']}* [{bar}]"
        if lvl_msgs:
            action += "\n\n" + "\n".join(lvl_msgs)
        try:
            await update.message.delete()
        except Exception: pass
        try:
            msg = await update.get_bot().send_message(
                chat_id=chat, text=action[:4096], parse_mode="Markdown")
            asyncio.create_task(_auto_delete(update.get_bot(), chat, msg.message_id, 30))
        except Exception: pass
        return

    # ── Miss check ────────────────────────────────────────────────────────────
    if check_miss(a, d):
        d["dodges"] = d.get("dodges",0) + 1
        check_titles(d)
        # Shadowstep primed: grant bonus damage on next attack after dodging
        cls_d_miss = get_player_class(d)
        if cls_d_miss:
            pk_d_miss = cls_d_miss.get("passive_key","")
            if pk_d_miss == "shadowstep":
                cds_d = safe_cds(d); cds_d["shadowstep_primed"] = "1"
                d["passive_cooldowns"] = json.dumps(cds_d)
            if pk_d_miss == "deaths_shadow":
                d["hp"] = min(d["max_hp"], d["hp"] + 10)
        save_player(d); save_player(a)
        miss_text = f"🌀 *{a['username']}* swings at *{d['username']}*  -  *MISS!*"
        try:
            await update.message.delete()
        except Exception: pass
        try:
            msg = await update.get_bot().send_message(
                chat_id=chat, text=miss_text, parse_mode="Markdown")
            asyncio.create_task(_auto_delete(update.get_bot(), chat, msg.message_id, 15))
        except Exception: pass
        return

    # ── Damage ────────────────────────────────────────────────────────────────
    dmg = calc_attack_damage(a, w)
    extra_notes = []

    # Assassin dual-equip check: throwing_star requires claw in shield slot
    _a_weap = a.get("equipped_weapon", "")
    _a_weap_type = WEAPONS.get(_a_weap, {}).get("type", "")
    if _a_weap_type == "throwing_star":
        _a_shld = a.get("equipped_shield", "")
        _a_shld_type = SHIELDS.get(_a_shld, {}).get("type", "")
        if _a_shld_type != "claw":
            dmg = round(dmg * 0.75)
            extra_notes.append("⚠️ _Missing claw  -  75% damage (equip a claw to fight at full power)_")

    # Crit check
    crit_forced = safe_cds(a).pop("next_crit_skill", None)
    if crit_forced:
        a["passive_cooldowns"] = json.dumps(safe_cds(a))
    if crit_forced or check_crit(a):
        dmg = apply_crit(a, dmg)
        crit_note = " 💥 CRIT!"
    else:
        crit_note = ""

    # Shadowstep primed bonus (+50% dmg after being dodged)
    cds_a = safe_cds(a)
    if cds_a.get("shadowstep_primed"):
        dmg = round(dmg * 1.50)
        cds_a.pop("shadowstep_primed"); a["passive_cooldowns"] = json.dumps(cds_a)
        extra_notes.append("🌑 *Shadowstep!* +50% damage after dodge!")

    # Attacker class passives
    cls_a = get_player_class(a)
    if cls_a:
        pk_a = cls_a.get("passive_key","")

        # Execute: double damage below 25% HP
        if pk_a == "execute":
            hp_pct = d["hp"] / max(1, d["max_hp"])
            if hp_pct < 0.25:
                dmg *= 2; extra_notes.append("💀 *Execute!* Double damage below 25% HP!")

        # Devotion charge bonus (+5 dmg if charged)
        if pk_a == "devotion":
            charge = safe_int(a.get("devotion_charge"))
            if charge > 0:
                dmg += 5; a["devotion_charge"] = 0
                extra_notes.append("✨ *Devotion charge!* +5 bonus damage!")

        # Warcry: +20% dmg when multiple recent attackers
        if pk_a == "warcry":
            if len(get_recent_attackers(a)) > 1:
                dmg = round(dmg * 1.20)
                extra_notes.append("😤 *Warcry!* +20% damage!")

        # Flurry: random double hit
        if pk_a == "flurry" and random.random() < 0.20:
            dmg *= 2; extra_notes.append("⚡ *Flurry!* Double hit!")

        # One-shot: random 5x damage
        if pk_a == "one_shot" and random.random() < 0.10:
            dmg *= 5; extra_notes.append("🎯 *ONE-SHOT!* 5x damage!")

        # Mark first hit bonus
        if pk_a == "mark_first_hit":
            if safe_int(a.get("mark_first_hit")):
                dmg = round(dmg * 1.25)
                a["mark_first_hit"] = 0
                extra_notes.append("🎯 *First strike bonus!* +25%!")

        # Trailblazer: first attack each day deals double damage
        if pk_a == "trailblazer":
            today = datetime.now().strftime("%Y-%m-%d")
            cds_tb = safe_cds(a)
            if cds_tb.get("trailblazer_date") != today:
                dmg *= 2
                cds_tb["trailblazer_date"] = today
                a["passive_cooldowns"] = json.dumps(cds_tb)
                extra_notes.append("🌅 *Trailblazer!* First strike of the day  -  double damage!")

        # Steady aim tracking
        if pk_a == "steady_aim":
            if a.get("steady_aim_target") == d["user_id"]:
                a["steady_aim_stacks"] = min(5, safe_int(a.get("steady_aim_stacks")) + 1)
            else:
                a["steady_aim_target"] = d["user_id"]
                a["steady_aim_stacks"] = 1

    # Revenge bonus: +15% damage if target is your revenge target
    revenge_bonus_note = ""
    if safe_int(a.get("revenge_target")) == du.id:
        rev_exp = a.get("revenge_expires")
        if rev_exp and datetime.now() < datetime.fromisoformat(rev_exp):
            dmg = round(dmg * 1.15)
            revenge_bonus_note = " 🔥 *Revenge!* +15% dmg"
            a["revenge_target"] = None
            a["revenge_expires"] = None

    # Distracted check: attacker has +30% chance to miss
    if is_distracted(a):
        if random.random() < 0.30:
            extra_notes.append("😵 Distracted  -  shot went wide!")
            save_player(a); save_player(d)
            dist_text = f"😵 *{a['username']}* was *Distracted* and missed *{d['username']}*!"
            try:
                await update.message.delete()
            except Exception: pass
            try:
                msg = await update.get_bot().send_message(
                    chat_id=chat, text=dist_text, parse_mode="Markdown")
                asyncio.create_task(_auto_delete(update.get_bot(), chat, msg.message_id, 15))
            except Exception: pass
            return

    # Defender class passives (pre-defense)
    cls_d = get_player_class(d)
    if cls_d:
        pk_d = cls_d.get("passive_key","")
        # Bulwark: 15% chance to fully block
        if pk_d == "bulwark" and random.random() < 0.15:
            extra_notes.append("🛡️ *Bulwark!* Attack completely blocked!")
            dmg = 0
        # Iron Will: 10% damage reduction
        if pk_d == "iron_will":
            dmg = round(dmg * 0.90)
        # Devotion defender: gain charge when hit
        if pk_d == "devotion":
            d["devotion_charge"] = safe_int(d.get("devotion_charge")) + 1

    # Reflect
    reflect = apply_reflect(d, a, dmg)

    # Holy Ward  -  Priest Path A passive proc on being hit
    if cls_d and cls_d.get("line") == "priest" and d.get("class_path") == "A":
        ward_chance = get_proc_chance(0.15, d)
        if not _ts_active(d, "ward_until") and random.random() < ward_chance:
            d["ward_until"] = (datetime.now() + timedelta(minutes=2)).isoformat()
            dmg = round(dmg * 0.60)
            extra_notes.append("✨ *Holy Ward procs!* Damage reduced by 40%!")
    # Apply existing ward if active
    if _ts_active(d, "ward_until"):
        dmg = round(dmg * 0.60)
        d["ward_until"] = None
        extra_notes.append("✨ *Holy Ward absorbs the hit!* -40% damage.")

    # Apply defense
    if dmg > 0:
        dmg_after_def = calc_defense(d, dmg)
    else:
        dmg_after_def = 0

    # Holy field reflect (Page/Squire/Knight/Paladin)
    if _ts_active(d, "holy_field_until"):
        wis_dmg = round(safe_stats(d).get("WIS",5) * 2)
        a["hp"] = max(0, a["hp"] - wis_dmg)
        reflect_note = f" | ✨ Holy Field reflects {wis_dmg} dmg!"
    else:
        reflect_note = ""

    # Unbreakable passive (Hero)
    if cls_d and cls_d.get("passive_key") == "unbreakable":
        if d["hp"] - dmg_after_def <= 0 and not d.get("unbreakable_used"):
            dmg_after_def = d["hp"] - 1
            d["unbreakable_used"] = True

    # Pet defensive ability (defender's pet may intercept/counter/shield)
    def_pet_rec = get_active_pet_record(du.id) if hasattr(du, 'id') else None
    if def_pet_rec:
        dmg_after_def, pet_status_type, pet_status_val = apply_pet_defense(def_pet_rec, a, dmg_after_def, extra_notes)
        if pet_status_type == "stun" and a:
            set_status(a, "stunned_until", 30)
        elif pet_status_type == "poison" and a and pet_status_val:
            a["poison_damage"] = pet_status_val
            set_status(a, "poison_until", 60)
        elif pet_status_type == "lifesteal_to_owner" and d and pet_status_val:
            d["hp"] = min(calc_max_hp(d), d.get("hp", 0) + pet_status_val)

    # Apply damage
    d["hp"] = max(0, d["hp"] - dmg_after_def)

    # Lifesteal
    healed = apply_lifesteal(a, dmg_after_def)

    # Update recent attackers
    update_recent_attackers(d, au.id)

    proc_fired, proc_msg, proc_extra = calc_proc_effect(a, d, dmg_after_def)

    action = f"⚔️ *{a['username']}* → *{d['username']}* for *{dmg_after_def} dmg*{crit_note}{revenge_bonus_note}{reflect_note}"
    if extra_notes: action += "\n" + "\n".join(extra_notes)
    if healed:      action += f" | 🩸 +{healed} HP"
    if proc_fired:  action += f"\n{proc_msg}"

    # ── Pet auto-attack ───────────────────────────────────────────────────────
    active_pet = get_active_pet_record(au.id)
    if active_pet:
        pet_atk = get_pet_atk_bonus(active_pet)
        sp_pet  = PET_SPECIES.get(active_pet.get("species"), {})
        pname   = _pet_display_name(active_pet)
        pers    = sp_pet.get("personality", "calm")
        emoji_p = sp_pet.get("emoji", "🐾")
        if active_pet.get("hunger", 100) < 20:
            action += f"\n{emoji_p} _{pname} is too hungry to fight!_"
        elif active_pet.get("mood", 100) < 40:
            action += f"\n{emoji_p} _{pname} is too sad to join in._"
        elif pet_atk > 0:
            d["hp"] = max(0, d["hp"] - pet_atk)
            battle_msg = PERSONALITY_BATTLE.get(pers, "attacks")
            action += f"\n{emoji_p} *{pname}* {battle_msg} for *{pet_atk} dmg*!"

    # Check defeat
    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        d["defeated_until"] = (datetime.now() + timedelta(hours=6)).isoformat()
        d["last_defeated_by"] = f"{a['username']} (PvP)"
        d["kill_streak"] = 0
        d["revenge_target"] = au.id
        d["revenge_expires"] = (datetime.now() + timedelta(hours=24)).isoformat()
        exp_loss = round(d.get("exp",0) * 0.10)
        d["exp"]  = max(0, d.get("exp",0) - exp_loss)
        d["losses"] = d.get("losses",0) + 1
        a["wins"]   = a.get("wins",0) + 1
        # Killstreak
        a["kill_streak"] = safe_int(a.get("kill_streak")) + 1
        if a["kill_streak"] > safe_int(a.get("max_kill_streak")):
            a["max_kill_streak"] = a["kill_streak"]
        # Wanted level — track kills today
        today_str = datetime.now().strftime("%Y-%m-%d")
        if a.get("kills_today_date") != today_str:
            a["kills_today"] = 0; a["kills_today_date"] = today_str
        a["kills_today"] = safe_int(a.get("kills_today")) + 1
        # PvP history for victim
        hist = sjl(d.get("pvp_history"), [])
        hist.insert(0, {"attacker": a["username"], "dmg": "KO",
                        "ts": datetime.now().strftime("%m/%d %H:%M")})
        d["pvp_history"] = json.dumps(hist[:5])
        for _desc, _exp, _gold in track_objective(a, "pvp_win"):
            a["gold"] = a.get("gold",0) + _gold; add_exp(a, _exp)
        asyncio.create_task(_notify_defeat(update.get_bot(), d, a['username'] + " (PvP)"))

        # Deadeye Last Shot  -  double timer
        if cls_a and cls_a.get("passive_key") == "dead_or_alive":
            d["defeated_until"] = (datetime.now() + timedelta(hours=12)).isoformat()
            action += f"\n☠️ *LAST SHOT!* {d['username']} defeated for 12 hours!"
            asyncio.create_task(announce(update.get_bot(), chat,
                f"🏹 *{a['username']}* took down *{d['username']}* with *Last Shot*! "
                f"12-hour defeat. Triple rewards earned.", permanent=True))
            a["gold"] = a.get("gold",0) + 150  # triple gold simplified

        exp_gain = 60 + a["level"] * 8
        lmsgs, leveled = add_exp(a, exp_gain, w)
        lvl_msgs = lmsgs

        # Conqueror passive (Warlord)  -  restore 20% HP on kill
        if cls_a and cls_a.get("passive_key") == "conqueror":
            restore = round(a["max_hp"] * 0.20)
            a["hp"] = min(a["max_hp"], a["hp"] + restore)
            set_status(d, "weakened_until", 3600)

        # Bounty check
        asyncio.create_task(check_and_claim_bounty(update.get_bot(), a, d, chat))

        # Guild war kill credit
        a_guild = get_guild(a.get("guild_id")) if a.get("guild_id") else None
        d_guild = get_guild(d.get("guild_id")) if d.get("guild_id") else None
        if a_guild and d_guild and a_guild["guild_id"] != d_guild["guild_id"]:
            war_gw = get_active_war(a_guild["guild_id"], d_guild["guild_id"])
            if war_gw:
                conn_kr = sqlite3.connect(DB_PATH); c_kr = conn_kr.cursor()
                if str(war_gw["guild1_id"]) == str(a_guild["guild_id"]):
                    c_kr.execute("UPDATE guild_wars SET kills1=kills1+1 WHERE war_id=?", (war_gw["war_id"],))
                else:
                    c_kr.execute("UPDATE guild_wars SET kills2=kills2+1 WHERE war_id=?", (war_gw["war_id"],))
                conn_kr.commit(); conn_kr.close()
                action += f"\n⚔️ *Guild War kill!* Score updated for {a_guild['name']}."

        # Deadeye kill bonus
        if cls_a and cls_a.get("passive_key") == "dead_or_alive":
            a["deadeye_kill_bonus"] = safe_int(a.get("deadeye_kill_bonus")) + 2

        action += f"\n💀 *{d['username']}* DEFEATED! +{exp_gain} EXP to {a['username']}."

        if leveled and a["level"] % 10 == 0:
            asyncio.create_task(announce(update.get_bot(), chat,
                f"🎉 *{a['username']}* reached *Level {a['level']}*! ⚔️", permanent=True))

        asyncio.create_task(announce(update.get_bot(), chat,
            f"💀 *{d['username']}* was defeated by *{a['username']}*!\n"
            f"Final HP: 0/{d.get('max_hp', calc_max_hp(d))} - "
            f"Lost {exp_loss:,} EXP - Defeated 6hrs", permanent=False))

    # PvP history for non-lethal hits
    if d["hp"] > 0:
        hist_nl = sjl(d.get("pvp_history"), [])
        hist_nl.insert(0, {"attacker": a["username"], "dmg": dmg_after_def,
                           "ts": datetime.now().strftime("%m/%d %H:%M")})
        d["pvp_history"] = json.dumps(hist_nl[:5])

    check_titles(a); check_titles(d)
    save_player(a); save_player(d)

    if d["hp"] > 0:
        hp_pct = d["hp"] / max(1, d["max_hp"])
        filled = round(hp_pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        action += f"\n❤️ {d['username']}: *{d['hp']}/{d['max_hp']}* [{bar}]"
        asyncio.create_task(_notify_attack(update.get_bot(), d, a["username"], dmg_after_def))

    statuses = get_active_statuses(d)
    if statuses:
        action += "\n" + " | ".join(statuses)

    if lvl_msgs:
        action += "\n\n" + "\n".join(lvl_msgs)

    try:
        await update.message.delete()
    except Exception: pass
    try:
        msg = await update.get_bot().send_message(
            chat_id=chat, text=action[:4096], parse_mode="Markdown")
        asyncio.create_task(_auto_delete(update.get_bot(), chat, msg.message_id, 30))
    except Exception: pass

# ── HEAL ──────────────────────────────────────────────────────────────────────
async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hu = update.effective_user
    h  = get_player(hu.id)
    if not h:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not update.message.reply_to_message:
        # No reply — heal yourself
        tu = hu
        t  = h
    else:
        tu = update.message.reply_to_message.from_user
        t  = get_player(tu.id)
    if not t:
        await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return

    # Check if target can be healed/revived
    target_is_dead = t["hp"] <= 0
    if target_is_dead and is_revival_blocked(t):
        await send_group(update,
            f"☠️ *{t['username']}* has been condemned by a Zealot  -  they cannot be revived for now.\n"
            f"Only a *Saint's Absolution* can lift this.", delay=15); return
    if is_healing_blocked(t) and not target_is_dead:
        await send_group(update,
            f"🚫 *{t['username']}* cannot be healed right now (Void Collapse active).", delay=9); return

    # Block non-priest potions on defeated targets
    if is_defeated(t) and get_class_line(h) != "priest":
        await send_group(update,
            f"❌ *{t['username']}* is defeated  -  vials can't revive them!\n"
            f"Use a *Scroll of Revival* from your inventory, or ask a Priest.", delay=9)
        return

    cid = h.get("class_id","")
    is_priest_healer = cid in HEALER_CLASSES

    inv = sjl(h.get("inventory"), [])
    potion = None
    heal_amount = 0

    if is_priest_healer:
        # Priest line  -  free revive via skill (Holy Light)
        heal_amount = safe_stats(h).get("WIS",5) * 5
        if get_player_class(h) and get_player_class(h).get("passive_key") == "mending_aura":
            heal_amount = round(heal_amount * 1.25)
    else:
        # Non-priest  -  requires potion
        if "Grand Restorative Flask" in inv:
            potion = "Grand Restorative Flask"; heal_amount = 200
        elif "Greater Health Potion" in inv:
            potion = "Greater Health Potion"; heal_amount = 100
        elif "Health Potion" in inv:
            potion = "Health Potion"; heal_amount = 50
        else:
            await send_group(update,
                "❌ You need a Health Potion to heal someone!\n"
                "Chalkers can heal for free with /skill.", delay=9); return
        inv.remove(potion)
        h["inventory"] = json.dumps(inv)

    # WIS bonus
    heal_amount += safe_stats(h).get("WIS",5)

    # Accessory heal bonus
    if get_accessory_bonus(h, "heal_bonus"):
        heal_amount = round(heal_amount * (1 + get_accessory_bonus(h, "heal_bonus")))

    # Apply
    was_defeated = target_is_dead
    t["hp"] = min(t["max_hp"], t["hp"] + heal_amount)
    if was_defeated:
        t["defeated_until"]  = None
        t["invincible_until"] = (datetime.now() + timedelta(hours=1)).isoformat()
        t["hp"] = min(t["max_hp"], heal_amount)

    h["heals_given"] = h.get("heals_given",0) + 1
    if tu.id != hu.id:
        for _d, _e, _g in track_objective(h, "heal_ally"):
            h["gold"] = h.get("gold",0) + _g; add_exp(h, _e)
    new_t = check_titles(h)
    lmsgs, leveled = add_exp(h, 20)
    save_player(h)
    if tu.id != hu.id:
        save_player(t)

    is_self = (tu.id == hu.id)
    if is_priest_healer:
        cls_name_h = get_player_class(h)["name"] if get_player_class(h) else "Priest"
        if is_self and was_defeated:
            msg = (
                f"🙏 *{h['username']}* ({cls_name_h}) channels divine energy and *revives themselves*!\n"
                f"❤️ HP restored: *{heal_amount}* → {t['hp']}/{t['max_hp']}\n"
                f"✨ *1 hour invincibility* granted  -  _(Still Recovering)_"
            )
        elif is_self:
            msg = (
                f"🙏 *{h['username']}* ({cls_name_h}) heals themselves for *{heal_amount} HP*!\n"
                f"❤️ HP: {t['hp']}/{t['max_hp']}"
            )
        else:
            msg = (
                f"🙏 *{h['username']}* ({cls_name_h}) heals *{t['username']}* for *{heal_amount} HP*!\n"
                f"❤️ {t['username']}: {t['hp']}/{t['max_hp']} HP"
            )
            if was_defeated:
                msg += f"\n✨ *{t['username']}* is revived! *1 hour invincibility* granted  -  _(Still Recovering)_"
    else:
        msg = (
            f"💊 *{h['username']}* uses *{potion}* to heal *{t['username']}* for *{heal_amount} HP*!\n"
            f"❤️ {t['username']}: {t['hp']}/{t['max_hp']} HP"
        )
        if was_defeated:
            msg += f"\n✨ *{t['username']}* is revived! *1 hour invincibility* granted  -  _(Still Recovering)_"
    if new_t:
        msg += f"\n🏅 *{h['username']}* earned: *{new_t[0]}*!"
    if leveled and h["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{h['username']}* reached *Level {h['level']}*! 💊", permanent=True))
    await send_group(update, msg, delay=30)

# ── STATS ─────────────────────────────────────────────────────────────────────
def _exp_bar(current, needed, length=10):
    pct    = min(1.0, current / max(1, needed))
    filled = round(pct * length)
    bar    = "█" * filled + "░" * (length - filled)
    return f"✨ [{bar}] {current:,}/{needed:,} EXP ({int(pct*100)}%)"

def _build_stats_pages(p, viewing_name=None):
    real_max     = calc_max_hp(p)
    defeated_str = " *(Defeated)*" if is_defeated(p) else ""
    recovering   = " *(Invincible)*" if is_invincible(p) else ""
    cls          = get_player_class(p)
    cls_name     = cls["name"] if cls else ("Choose at Lv 5  -  /class" if p["level"] >= 5 else "Unlocks at Lv 5")
    path_str     = f"  -  Path {p.get('class_path','?')}" if p.get("class_path") else ""
    eff          = {st: get_stat(p, st) for st in ["STR","AGI","INT","WIS","DEX","LUK"]}
    sp           = safe_int(p.get("stat_points"))
    tier         = get_tier(p["level"])
    w            = get_weather()
    statuses     = get_active_statuses(p)
    cp           = calc_combat_power(p) if callable(globals().get("calc_combat_power")) else 0
    name         = viewing_name or p["username"]

    guild_str = "None"
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"), 1)
            perk = GUILD_PERKS.get(glvl, {})
            guild_str = g['name']

    exp_cur  = safe_int(p.get("exp"))
    exp_need = exp_for_level(p["level"])
    exp_pct  = int(exp_cur / max(1, exp_need) * 100)

    weap_name = p.get("equipped_weapon") or "None"
    armr_name = p.get("equipped_armor") or "None"
    shld_name = p.get("equipped_shield") or "None"
    acc_name  = p.get("equipped_accessory") or "None"

    def quick_gear(n):
        if n == "None": return "None"
        enh  = get_enhancement(p, n)
        encs = get_enchant(p, n)
        return f"{n}{f' +{enh}' if enh else ''}{f' ✨×{len(encs)}' if encs else ''}"

    inv = Counter(sjl(p.get("inventory"), []))
    inv_lines = [
        f"{RARITY_EMOJI.get(WEAPONS.get(k,ARMORS.get(k,ACCESSORIES.get(k,CONSUMABLES.get(k,{})))).get('rarity',''),'⚪')} {k} x{v}"
        for k, v in inv.items()
    ] or ["Empty"]

    title_list = safe_titles(p)
    shadow = get_shadow(p["user_id"])
    msg_count = safe_int(shadow.get("message_count")) if shadow else 0

    # Page 1 - Profile
    defeated_cause   = p.get("last_defeated_by")
    defeat_countdown = time_until(p.get("defeated_until"))
    defeat_line = (
        f"☠️ Defeated by: _{defeated_cause}_\n"
        f"⏳ Back in: *{defeat_countdown}*"
        if is_defeated(p) and defeated_cause and defeat_countdown
        else f"☠️ Defeated by: _{defeated_cause}_" if is_defeated(p) and defeated_cause
        else f"⏳ Back in: *{defeat_countdown}*" if is_defeated(p) and defeat_countdown
        else None
    )

    married_str = ""
    if p.get("married_to_id") and p.get("married_to_name"):
        married_str = f"\n💍 Married to *{p['married_to_name']}*"

    page1_lines = [
        f"🎱 *{name}*{defeated_str}{recovering}",
        f"🏅 {p['active_title']}",
        f"{tier['name']}  -  Level {p['level']}",
        f"🏰 {guild_str}",
        f"🌍 {w['name']}",
    ]
    if married_str:
        page1_lines.append(married_str)
    page1_lines += [
        "",
        f"❤️ HP: {p['hp']}/{real_max}",
        f"✨ {exp_cur:,}/{exp_need:,} EXP ({exp_pct}%)",
        f"🏆 Lifetime EXP: {safe_int(p.get('total_exp')):,}",
        f"💬 Messages: {msg_count:,}",
        f"💰 Gold: {p['gold']}",
        f"⚔️ Wins: {p['wins']}   Losses: {p.get('losses',0)}",
    ]
    if defeat_line:
        page1_lines.append(defeat_line)

    # Page 2 - Class & Stats
    page2_lines = [
        f"🧙 *{cls_name}*{path_str}",
        "",
        f"STR: {eff['STR']}",
        f"AGI: {eff['AGI']}",
        f"INT: {eff['INT']}",
        f"WIS: {eff['WIS']}",
        f"DEX: {eff['DEX']}",
        f"LUK: {eff['LUK']}",
        f"🛡️ DEF: {get_armor_def(p)} (from gear)",
    ]
    if cp > 0:
        page2_lines += ["", f"⚡ Combat Power: *{cp:,}*"]
    if sp > 0:
        page2_lines.append(f"💡 {sp} stat pt{'s' if sp != 1 else ''} to spend  -  /allocate")
    if statuses:
        page2_lines += ["", "⚠️ *Active Effects*"] + [f"  {st}" for st in statuses]

    # Page 3 - Gear
    _, active_sets = get_active_set_bonuses(p)
    set_lines = [f"✨ *{sn}*" for sn in active_sets]
    page3_lines = [
        f"⚔️ {quick_gear(weap_name)}",
        f"🛡️ {quick_gear(armr_name)}",
        f"🔰 {quick_gear(shld_name)}",
        f"💍 {quick_gear(acc_name)}",
        "",
    ]
    if set_lines:
        page3_lines += ["🌟 *Active Set Bonuses:*"] + set_lines + [""]
    page3_lines.append("_/gear for full enhancement + enchant details_")

    # Page 4 - Inventory
    page4_lines = ["🎒 *Inventory*", ""] + inv_lines + ["", "_/inventory for paginated full view_"]

    # Page 5 - Titles
    page5_lines = ["🏅 *Titles*", ""] + ([f"  {t}" for t in title_list] or ["  None"])

    return [
        "\n".join(page1_lines),
        "\n".join(page2_lines),
        "\n".join(page3_lines),
        "\n".join(page4_lines),
        "\n".join(page5_lines),
    ]


async def _send_stats_page(target, target_uid: int, page: int, edit: bool = False,
                           caller_name: str = None):
    p = get_player(target_uid)
    if not p:
        text = "No RPG profile found."
        if edit:
            await target.edit_message_text(text, parse_mode="Markdown")
        else:
            await send_group(target, text, delay=9)
        return

    pages = _build_stats_pages(p, viewing_name=caller_name)
    PAGE_LABELS = ["Profile", "Stats", "Gear", "Inventory", "Titles"]
    total = len(pages)
    page  = max(1, min(page, total))
    text  = pages[page - 1]
    row   = []
    if page > 1:
        label = PAGE_LABELS[page - 2] if page - 2 < len(PAGE_LABELS) else str(page - 1)
        row.append(InlineKeyboardButton(f"◀ {label}", callback_data=f"stats_p_{target_uid}_{page-1}"))
    if page < total:
        label = PAGE_LABELS[page] if page < len(PAGE_LABELS) else str(page + 1)
        row.append(InlineKeyboardButton(f"{label} ▶", callback_data=f"stats_p_{target_uid}_{page+1}"))
    markup = InlineKeyboardMarkup([row]) if row else None
    if edit:
        await target.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await send_group(target, text, permanent=False, delay=120, reply_markup=markup)


async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")   # stats_p_<uid>_<page>
    target_uid = int(parts[2])
    page       = int(parts[3])
    await _send_stats_page(query, target_uid, page, edit=True)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    viewing_other = False
    if update.message.reply_to_message:
        target_uid = update.message.reply_to_message.from_user.id
        if target_uid != user.id:
            viewing_other = True
        else:
            target_uid = user.id
    else:
        target_uid = user.id

    p = get_player(target_uid)
    s = get_shadow(target_uid)
    if not p and not s:
        await send_group(update,
            "No profile yet  -  just start chatting to build your level!", delay=9); return
    if p and not viewing_other: p["username"] = user.first_name
    if s and not viewing_other: s["username"] = user.first_name
    if not p:
        tier = get_tier(s["level"])
        await send_group(update,
            f"👤 *{s['username']}*  -  Shadow Profile\n\n"
            f"{tier['emoji']} Level *{s['level']}*\n"
            f"✨ EXP: {s['exp']:,}/{exp_for_level(s['level']):,}\n"
            f"🏆 Lifetime: *{safe_int(s.get('total_exp')):,}* EXP\n"
            f"💬 Messages: {s.get('message_count',0):,}\n\n"
            f"_Send /ascend in a private chat to enter the RPG!_",
            permanent=False, delay=9); return

    if s and not viewing_other: sync_levels(p, s); save_player(p); save_shadow(s)

    if is_defeated(p) and p["hp"] > 0:
        p["defeated_until"] = None; save_player(p)

    sd_check = safe_stats(p)
    if sd_check.get("DEF", 0) > 0:
        refund_def = sd_check["DEF"]
        sd_check["DEF"] = 0
        p["stats"] = json.dumps(sd_check)
        p["stat_points"] = safe_int(p.get("stat_points")) + refund_def
        save_player(p)

    real_max = calc_max_hp(p)
    if real_max != p["max_hp"] and not viewing_other:
        p["max_hp"] = real_max
        if p["hp"] > real_max: p["hp"] = real_max
        save_player(p)

    caller_name = user.first_name if not viewing_other else None
    if viewing_other:
        target_user = update.message.reply_to_message.from_user
        p["username"] = target_user.first_name

    await _send_stats_page(update, target_uid, page=1, caller_name=caller_name)

# ── BOSS ──────────────────────────────────────────────────────────────────────
def _roll_boss_loot(boss_data):
    table = boss_data.get("loot_table",[])
    if not table: return None
    name, rarity = random.choice(table)
    if name in WEAPONS or name in ARMORS or name in ACCESSORIES:
        return name
    return None

# ── RAID ──────────────────────────────────────────────────────────────────────
async def raid_cmd(update, context):
    user = update.effective_user
    p = get_player(user.id)
    chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!"); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated  -  can't raid!"); return

    raid = active_raids.get(chat_id)

    if raid and not raid["in_progress"]:
        if datetime.now() > datetime.fromisoformat(raid["expires"]):
            active_raids.pop(chat_id, None)
            await send_group(update, "⏰ Raid lobby expired. Use /raid to start a new one.")
            return
        if user.id in [u["id"] for u in raid["party"]]:
            count = len(raid["party"])
            await send_group(update,
                f"⚔️ You're already in the party! ({count} players)\n"
                f"Use /raidstart when ready."); return
        raid["party"].append({"id": user.id, "name": user.first_name})
        count = len(raid["party"])
        await send_group(update,
            f"⚔️ *{user.first_name}* joins the raid party! ({count} players)\n"
            f"Use /raidstart to begin (min 2)."); return

    if raid and raid["in_progress"]:
        await send_group(update,
            f"⚔️ A raid is in progress!\n"
            f"Use /raidstrike to attack."); return

    active_raids[chat_id] = {
        "party": [{"id": user.id, "name": user.first_name}],
        "in_progress": False,
        "wave": 0,
        "tier": None,
        "enemy": None,
        "enemy_hp": 0,
        "enemy_max_hp": 0,
        "expires": (datetime.now() + timedelta(minutes=15)).isoformat(),
        "damage_dealt": {},
    }
    await send_group(update,
        f"🏰 *RAID LOBBY OPEN!*\n\n"
        f"*{user.first_name}* is forming a raid party.\n"
        f"Others: type /raid to join!\n"
        f"Minimum 2 players required.\n\n"
        f"_Leader: /raidstart when ready. Lobby expires in 15 minutes._",
        permanent=False, delay=180)


async def raidstart_cmd(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    raid = active_raids.get(chat_id)

    if not raid:
        await send_group(update, "No raid lobby! Use /raid to start one."); return
    if raid["in_progress"]:
        await send_group(update, "Raid already in progress! Use /raidstrike."); return
    if user.id != raid["party"][0]["id"]:
        await send_group(update, "Only the raid leader can start."); return
    if len(raid["party"]) < 2:
        await send_group(update,
            f"Need at least 2 players. Have {len(raid['party'])}."); return

    levels = []
    for u in raid["party"]:
        pp = get_player(u["id"])
        if pp: levels.append(pp["level"])
    avg = sum(levels) / len(levels) if levels else 1
    eligible = [t for t in RAID_TIERS if t["min_level"] <= avg]
    tier = eligible[-1] if eligible else RAID_TIERS[0]

    first_enemy = tier["wave_enemies"][0].copy()
    raid["tier"] = tier
    raid["in_progress"] = True
    raid["wave"] = 1
    raid["enemy"] = first_enemy
    raid["enemy_hp"] = first_enemy["hp"]
    raid["enemy_max_hp"] = first_enemy["hp"]
    raid["damage_dealt"] = {u["id"]: 0 for u in raid["party"]}

    # Initialize separate raid HP for each party member
    raid["player_hp"] = {}
    raid["player_max_hp"] = {}
    for u in raid["party"]:
        pp = get_player(u["id"])
        if pp:
            mhp = calc_max_hp(pp)
            raid["player_hp"][u["id"]] = mhp
            raid["player_max_hp"][u["id"]] = mhp

    # Initialize turn tracking
    raid["current_turn_idx"] = 0
    raid["acted_this_round"] = set()
    raid["turn_task"] = None

    names = ", ".join(u["name"] for u in raid["party"])
    wave_count = len(tier["wave_enemies"]) + 1
    await send_group(update,
        f"⚔️ *RAID BEGINS  -  {tier['name']}*\n\n"
        f"👥 Party: {names}\n"
        f"📊 Avg Level: {avg:.0f}\n"
        f"🌊 {wave_count} waves total\n\n"
        f"🌊 *Wave 1  -  {first_enemy['name']}*\n"
        f"❤️ HP: {first_enemy['hp']}\n"
        f"💀 Damage: {first_enemy['dmg_min']}-{first_enemy['dmg_max']}\n\n"
        f"Use /raidstrike to attack!",
        permanent=False, delay=180)

    # Start first turn
    await _announce_turn(context.bot, chat_id, raid)


async def raidstrike_cmd(update, context):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    raid = active_raids.get(chat_id)
    if not raid: await send_group(update, "No active raid! Use /raid."); return
    if not raid["in_progress"]: await send_group(update, "Raid hasn't started! Use /raidstart."); return
    if user.id not in [u["id"] for u in raid["party"]]:
        await send_group(update, "You're not in this raid!"); return
    if raid["player_hp"].get(user.id, 0) <= 0:
        await send_group(update, "💀 You're down  -  wait for the next raid!"); return
    if cannot_attack(p):
        await send_group(update, "⚡ Stunned or rooted!", delay=9); return

    # Enforce turn order
    alive = _get_alive_party(raid)
    if alive:
        idx = raid.get("current_turn_idx", 0) % len(alive)
        if alive[idx]["id"] != user.id:
            current_name = alive[idx]["name"]
            await send_group(update, f"⏳ It's *{current_name}'s* turn right now!", delay=9); return

    # Cancel turn timer
    old_task = raid.get("turn_task")
    if old_task and not old_task.done():
        old_task.cancel()
    raid["turn_task"] = None

    enemy = raid["enemy"]; w = get_weather()
    dmg = calc_attack_damage(p, w); is_crit = check_crit(p)
    if is_crit: dmg = apply_crit(p, dmg)
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0; dmg = get_stat(p,"AGI")*4; is_crit = False

    raid["enemy_hp"] = max(0, raid["enemy_hp"] - dmg)
    raid["damage_dealt"][user.id] = raid["damage_dealt"].get(user.id, 0) + dmg
    for _d, _e, _g in track_objective(p, "raid_hit"):
        p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)

    # Mark player as acted this round
    if "acted_this_round" not in raid or not isinstance(raid["acted_this_round"], set):
        raid["acted_this_round"] = set()
    raid["acted_this_round"].add(user.id)

    php  = raid["player_hp"].get(user.id, 0)
    pmhp = raid["player_max_hp"].get(user.id, php)
    lines = [
        f"⚔️ *{user.first_name}* strikes *{enemy['name']}* for *{dmg}{'💥' if is_crit else ''}!*",
        f"❤️ Enemy HP: {raid['enemy_hp']}/{raid['enemy_max_hp']}  |  Your HP: {php}/{pmhp}",
    ]
    bleed_dmg = tick_enemy_bleed(raid)
    if bleed_dmg:
        lines.append(f"🩸 *{enemy['name']}* bleeds for {bleed_dmg}!")

    save_player(p)
    await send_group(update, "\n".join(lines), delay=15)

    if raid["enemy_hp"] <= 0:
        await _handle_wave_clear(context.bot, chat_id, raid, p)
    else:
        await _advance_raid_turn(context.bot, chat_id, raid)


async def raidstatus_cmd(update, context):
    chat_id = update.effective_chat.id
    raid = active_raids.get(chat_id)
    if not raid:
        await send_group(update, "No active raid."); return

    if not raid["in_progress"]:
        names = ", ".join(u["name"] for u in raid["party"])
        await send_group(update,
            f"🏰 *Raid Lobby*  -  {len(raid['party'])} players\n"
            f"👥 {names}\n"
            f"Use /raidstart when ready."); return

    tier = raid["tier"]
    enemy = raid["enemy"]
    wave_count = len(tier["wave_enemies"]) + 1
    names = ", ".join(u["name"] for u in raid["party"])

    dmg_board = sorted(raid.get("damage_dealt", {}).items(), key=lambda x: x[1], reverse=True)
    dmg_lines = []
    for uid, dmg in dmg_board[:5]:
        pp = get_player(uid)
        name = pp["username"] if pp else str(uid)
        dmg_lines.append(f"  {name}: {dmg:,} dmg")

    await send_group(update,
        f"⚔️ *{tier['name']}*\n"
        f"👥 {names}\n"
        f"🌊 Wave {raid['wave']}/{wave_count}  -  *{enemy['name']}*\n"
        f"❤️ HP: {raid['enemy_hp']:,}/{raid['enemy_max_hp']:,}\n\n"
        f"📊 *Damage dealt:*\n" + "\n".join(dmg_lines), delay=20)

async def raidparty_cmd(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    raid = active_raids.get(chat_id)
    sr   = active_soloraids.get(user.id)

    if raid and raid.get("in_progress"):
        lines = [f"👥 *Raid Party - {raid['tier']['name']}*\n"]
        alive = _get_alive_party(raid)
        alive_ids = {u["id"] for u in alive}
        for u in raid["party"]:
            uid = u["id"]
            php  = raid["player_hp"].get(uid, 0)
            pmhp = raid["player_max_hp"].get(uid, php)
            dmg  = raid["damage_dealt"].get(uid, 0)
            status = "✅" if uid in alive_ids else "💀"
            bar_filled = int((php/max(1,pmhp))*10)
            bar = "█"*bar_filled + "░"*(10-bar_filled)
            lines.append(f"{status} *{u['name']}*\n  HP: [{bar}] {php}/{pmhp}\n  Dmg dealt: {dmg:,}")
        # Current turn
        if alive:
            idx = raid.get("current_turn_idx",0) % len(alive)
            lines.append(f"\n⚔️ Current turn: *{alive[idx]['name']}*")
        await send_group(update, "\n".join(lines), delay=20); return

    if sr:
        php  = sr.get("player_hp", 0)
        pmhp = sr.get("player_max_hp", php)
        enemy = sr["enemy"]
        bar_filled = int((php/max(1,pmhp))*10)
        bar = "█"*bar_filled + "░"*(10-bar_filled)
        await send_group(update,
            f"🎱 *Solo Raid Status*\n\n"
            f"Your HP: [{bar}] {php}/{pmhp}\n"
            f"Enemy: *{enemy['name']}* ❤️ {sr['enemy_hp']}/{sr['enemy_max_hp']}\n"
            f"Wave: {sr['wave']} - Total dmg: {sr.get('total_dmg',0):,}", delay=15); return

    await send_group(update, "No active raid.", delay=9)

async def raid_atk_callback(update, context):
    """Handle raid attack button press — delegates to raidstrike_cmd."""
    query = update.callback_query
    await query.answer()
    data = query.data  # raid_atk_{uid}
    parts = data.split("_")
    if len(parts) < 3:
        return
    try:
        uid = int(parts[2])
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your turn button!", show_alert=True)
        return
    # Delegate to raidstrike_cmd — it uses update.effective_user and effective_chat
    await raidstrike_cmd(update, context)

# ── SOLO RAID ─────────────────────────────────────────────────────────────────
async def soloraid_cmd(update, context):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!"); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated  -  can't solo raid!"); return

    if user.id in active_soloraids:
        sr = active_soloraids[user.id]
        enemy = sr["enemy"]
        await send_group(update,
            f"⚔️ Solo raid in progress!\n"
            f"🌊 Wave {sr['wave']}  -  *{enemy['name']}*\n"
            f"❤️ Enemy HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}\n"
            f"Use /solostrike to attack."); return

    tier = None
    for t in reversed(SOLO_RAID_TIERS):
        if p["level"] >= t["min_level"]:
            tier = t; break
    if not tier:
        tier = SOLO_RAID_TIERS[0]

    first_enemy = tier["wave_enemies"][0].copy()
    mhp = calc_max_hp(p)
    active_soloraids[user.id] = {
        "tier": tier,
        "wave": 1,
        "enemy": first_enemy,
        "enemy_hp": first_enemy["hp"],
        "enemy_max_hp": first_enemy["hp"],
        "total_dmg": 0,
        "player_hp": mhp,
        "player_max_hp": mhp,
    }
    wave_count = len(tier["wave_enemies"]) + 1
    sr_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"sr_act_{user.id}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"sr_act_{user.id}_skl"),
    ]])
    await send_group(update,
        f"🎱 *SOLO RAID  -  {tier['name']}*\n\n"
        f"🌊 {wave_count} waves + final boss\n\n"
        f"🌊 *Wave 1  -  {first_enemy['name']}*\n"
        f"❤️ HP: {first_enemy['hp']}\n"
        f"💀 Damage: {first_enemy['dmg_min']}–{first_enemy['dmg_max']}\n\n"
        f"Use /solostrike to attack!",
        permanent=False, delay=120, reply_markup=sr_markup)


async def solostrike_cmd(update, context):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!"); return
    if user.id not in active_soloraids:
        await send_group(update, "No active solo raid! Use /soloraid."); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated  -  can't strike!"); return
    if cannot_attack(p):
        await send_group(update, "⚡ You're stunned or rooted  -  can't act!", delay=9); return

    sr = active_soloraids[user.id]
    enemy = sr["enemy"]
    w = get_weather()
    dmg = calc_attack_damage(p, w)
    is_crit = check_crit(p)
    if is_crit: dmg = apply_crit(p, dmg)
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0; dmg = get_stat(p, "AGI") * 4; is_crit = False

    sr["enemy_hp"] = max(0, sr["enemy_hp"] - dmg)
    sr["total_dmg"] = sr.get("total_dmg", 0) + dmg

    lines = [
        f"⚔️ *{user.first_name}* strikes *{enemy['name']}* for *{dmg}{'💥' if is_crit else ''}!*",
        f"❤️ Enemy HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}  |  Your HP: {sr['player_hp']}/{sr['player_max_hp']}",
    ]
    bleed_dmg = tick_enemy_bleed(sr)
    if bleed_dmg:
        lines.append(f"🩸 *{enemy['name']}* bleeds for {bleed_dmg}! HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}")

    if sr["enemy_hp"] <= 0:
        tier = sr["tier"]; wave_enemies = tier["wave_enemies"]; cw = sr["wave"]
        lines.append(f"\n✅ *Wave {cw} cleared!*")
        sr.pop("enemy_statuses", None)
        if cw < len(wave_enemies):
            sr["wave"] += 1; ne = wave_enemies[cw].copy()
            sr["enemy"] = ne; sr["enemy_hp"] = ne["hp"]; sr["enemy_max_hp"] = ne["hp"]
            lines.append(f"\n🌊 *Wave {sr['wave']}  -  {ne['name']}*")
            lines.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
        elif cw == len(wave_enemies):
            bd = BOSSES[tier["wave_boss_key"]]; boss_hp = bd["max_hp"] // 2
            sr["wave"] = len(wave_enemies) + 1
            sr["enemy"] = {"name": bd["name"] + " ⚡","dmg_min": round(bd["dmg_min"]*0.6),"dmg_max": round(bd["dmg_max"]*0.6)}
            sr["enemy_hp"] = boss_hp; sr["enemy_max_hp"] = boss_hp
            lines.append(f"\n🎱 *FINAL BOSS  -  {bd['name']}!* ❤️ HP: {boss_hp}")
        else:
            active_soloraids.pop(user.id, None)
            exp_r = tier["exp_reward"]; gold_r = tier["gold_reward"]
            p["gold"] = p.get("gold",0) + gold_r; p["quests_done"] = p.get("quests_done",0) + 1
            for _d, _e, _g in track_objective(p, "solo_win"):
                p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
            loot = roll_loot_table(tier.get("loot_table",[]), p)
            loot_line = ""
            if loot:
                add_item(p, loot); r = ""
                for pool in [WEAPONS,ARMORS,ACCESSORIES]:
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                loot_line = f"\n🎒 Found: {r} *{loot}*!"
            add_exp(p, exp_r, get_weather())
            lines.append(f"\n🏆 *SOLO RAID COMPLETE  -  {tier['name']}!*")
            lines.append(f"✅ +{exp_r:,} EXP | +{gold_r}g{loot_line}")
            save_player(p); await send_group(update, "\n".join(lines), delay=25); return
    else:
        # Enemy counter-attack (solo  -  uses separate raid HP)
        enemy = sr["enemy"]
        if enemy_status_active(sr, "stunned_until"):
            await send_group(update, f"⚡ *{enemy['name']}* is stunned  -  no counter!", delay=15)
        elif enemy_status_active(sr, "frozen_until"):
            await send_group(update, f"❄️ *{enemy['name']}* is frozen  -  no counter!", delay=15)
        else:
            raw = random.randint(enemy["dmg_min"], enemy["dmg_max"])
            if enemy_status_active(sr, "weakened_until") or enemy_status_active(sr, "hexed_until"):
                raw = round(raw * 0.75)
            dodge = get_accessory_bonus(p, "dodge_bonus") + get_enchant_bonus(p, "dodge_bonus")
            cls_p = get_player_class(p)
            if cls_p and cls_p.get("passive_key") == "evasion": dodge += 0.10
            if dodge > 0 and random.random() < dodge:
                lines.append(f"💨 *{p['username']}* dodges!")
            else:
                edm = calc_defense(p, raw)
                sr["player_hp"] = max(0, sr["player_hp"] - edm)
                if sr["player_hp"] == 0:
                    exp_loss = apply_pvp_death(p, killer_name=enemy["name"], cause="Solo Raid")
                    asyncio.create_task(_notify_defeat(context.bot, p, enemy["name"] + " (Solo Raid)"))
                    active_soloraids.pop(user.id, None)
                    save_player(p)
                    lines.append(f"💀 *{enemy['name']}* kills *{p['username']}*! 6hr defeat. -{exp_loss} EXP.")
                    await send_group(update, "\n".join(lines), delay=20); return
                else:
                    lines.append(f"🩸 *{enemy['name']}* hits *{p['username']}* for *{edm}!* "
                                 f"({sr['player_hp']}/{sr['player_max_hp']} raid HP)")
                    if sr["player_hp"] > 0 and sr["player_hp"] <= round(sr["player_max_hp"] * 0.30):
                        lines.append(f"⚠️ *Critically low HP!* ({sr['player_hp']}/{sr['player_max_hp']}) Use /skill or a vial!")

    sr_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"sr_act_{user.id}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"sr_act_{user.id}_skl"),
    ]])
    save_player(p)
    await send_group(update, "\n".join(lines), delay=20, reply_markup=sr_markup)


async def soloraidstatus_cmd(update, context):
    user = update.effective_user
    sr = active_soloraids.get(user.id)
    if not sr:
        await send_group(update, "No active solo raid. Use /soloraid to start one."); return
    tier = sr["tier"]
    enemy = sr["enemy"]
    wave_count = len(tier["wave_enemies"]) + 1
    p = get_player(user.id)
    php  = sr.get("player_hp", 0)
    pmhp = sr.get("player_max_hp", php)
    hp_str = f"{php}/{pmhp} (raid HP)"

    status_lines = []
    es = sr.get("enemy_statuses", {})
    if enemy_status_active(sr, "stunned_until"): status_lines.append("  ⚡ Stunned")
    if enemy_status_active(sr, "frozen_until"):  status_lines.append("  ❄️ Frozen")
    if enemy_status_active(sr, "bleed_until"):   status_lines.append("  🩸 Bleeding")
    if enemy_status_active(sr, "hexed_until"):   status_lines.append("  💀 Hexed (-25% dmg)")
    if enemy_status_active(sr, "weakened_until"):status_lines.append("  😵 Weakened (-25% dmg)")

    # Player statuses
    p_statuses = get_active_statuses(p) if p else []

    out = [
        f"🎱 *{tier['name']}*",
        f"🌊 Wave {sr['wave']}/{wave_count}  -  *{enemy['name']}*",
        f"❤️ Enemy HP: {sr['enemy_hp']:,}/{sr['enemy_max_hp']:,}",
        f"🧍 Your HP: {hp_str}",
        f"⚔️ Total dmg dealt: {sr.get('total_dmg',0):,}",
    ]
    if status_lines:
        out.append(f"\n*Enemy Status:*")
        out.extend(status_lines)
    if p_statuses:
        out.append(f"\n*Your Status:*")
        for st in p_statuses: out.append(f"  {st}")

    await send_group(update, "\n".join(out), delay=15)


# ── ASCEND ────────────────────────────────────────────────────────────────────
async def ascend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if get_player(user.id):
        await send_group(update, f"⚔️ You're already in {WORLD_NAME}! Use /stats.", delay=9); return
    s = get_or_create_shadow(user.id, user.first_name)
    if s.get("ascended"):
        await send_group(update, "You've already ascended!", delay=9); return
    p = new_player(s)
    slvl = p["shadow_level_at_ascension"]
    await send_group(update,
        f"⚔️ *{user.first_name} has ASCENDED into {WORLD_NAME}!*\n\n"
        f"Level {slvl} legacy carries over:\n"
        f"⭐ Starting Level: *{p['level']}*\n"
        f"❤️ HP: {p['hp']} | 💰 Gold: {p['gold']}\n"
        f"💡 Stat Points: *{p['stat_points']}*\n\n"
        f"Next steps:\n"
        f"⚔️ /class  -  choose your class at Level 5\n"
        f"📊 /allocate  -  spend stat points\n"
        f"🎁 /daily  -  claim your daily reward\n"
        f"🗺️ /quest  -  go on a quest\n"
        f"🗺️ /explore  -  send yourself on an expedition", delay=30)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{user.first_name}* has ASCENDED! "
        f"Level {slvl} → RPG! 🎱", permanent=True))

# ── CLASS BROWSER ─────────────────────────────────────────────────────────────
_CLASS_EMOJIS = {
    "warrior":"⚔️","mage":"🔮","thief":"🔪","archer":"🏹","priest":"📿",
    "botanist":"🌸","enchantress":"💜","valkyrie":"⚡","phantom_dancer":"🌀",
}
_TIER_REQ     = {2:10, 3:30, 4:60, 5:100}

def _build_class_page(cid):
    """Build a full class info page for /class browsing."""
    base  = CLASS_TREE[cid]
    emoji = _CLASS_EMOJIS.get(cid, "⚔️")
    paths = CLASS_PATHS.get(cid, {})
    lines = [
        f"{emoji} *{base['name']}* — _{base['desc']}_\n",
        f"📈 *Primary Stat:* {base['primary_stat']}",
        f"🔢 *Stat Bonus:* {', '.join(f'+{v} {k}' for k,v in base.get('stat_bonus',{}).items())}\n",
        "─── *Tier 1 Skills (unlocked at Lv 5)* ───",
    ]
    for sk in base.get("skills", []):
        lines.append(f"• *{sk['name']}*")
        lines.append(f"  ☀️ Passive: {sk.get('passive','—')}")
        lines.append(f"  ⚡ Active: {sk['desc']}")
    lines.append("")

    for path_key in ["A","B"]:
        path_cids = paths.get(path_key, [])
        if not path_cids: continue
        path_label = f"Path {path_key}"
        lines.append(f"─── *{path_label}* ───")
        for i, pcid in enumerate(path_cids):
            pc  = CLASS_TREE.get(pcid, {})
            req = _TIER_REQ.get(i+2, 10)
            lines.append(f"🔒 *Tier {i+2} — {pc.get('name',pcid)}* _(Lv {req}+)_")
            lines.append(f"   _{pc.get('desc','')}_")
            for sk in pc.get("skills", []):
                lines.append(f"   • *{sk['name']}*: {sk['desc']}")
        lines.append("")

    lines.append(f"_Tap a button below to pick this class, or browse others._")
    return "\n".join(lines)

async def _send_class_browser(target, uid, page, edit=False):
    total = len(BASE_CLASSES)
    page  = max(0, min(page, total-1))
    cid   = BASE_CLASSES[page]
    text  = _build_class_page(cid)[:4096]

    nav_btns = []
    if page > 0:
        prev_cid = BASE_CLASSES[page-1]
        nav_btns.append(InlineKeyboardButton(
            f"◀ {_CLASS_EMOJIS.get(prev_cid,'')} {CLASS_TREE[prev_cid]['name']}",
            callback_data=f"classbrowse_{uid}_{page-1}"))
    if page < total-1:
        next_cid = BASE_CLASSES[page+1]
        nav_btns.append(InlineKeyboardButton(
            f"{_CLASS_EMOJIS.get(next_cid,'')} {CLASS_TREE[next_cid]['name']} ▶",
            callback_data=f"classbrowse_{uid}_{page+1}"))

    pick_btn = InlineKeyboardButton(
        f"✅ Pick {_CLASS_EMOJIS.get(cid,'')} {CLASS_TREE[cid]['name']}",
        callback_data=f"class_pick_{uid}_{cid}")
    markup = InlineKeyboardMarkup([nav_btns, [pick_btn]] if nav_btns else [[pick_btn]])

    if edit:
        try: await target.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception: pass
    else:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def class_browse_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    try:
        uid = int(parts[1]); page = int(parts[2])
    except (IndexError, ValueError): return
    if query.from_user.id != uid:
        await query.answer("Not your class picker!", show_alert=True); return
    await query.answer()
    await _send_class_browser(query, uid, page, edit=True)

# ── CLASS PROGRESSION BROWSER ─────────────────────────────────────────────────
def _build_class_progression_pages(p):
    """
    Returns a list of text pages, one per class in the player's progression chain:
    [base class, tier-2, tier-3, tier-4, tier-5].
    If no path chosen yet, only page 0 (base) + a "choose path" page.
    """
    CLASS_EMOJIS = {"warrior":"⚔️","mage":"🔮","thief":"🔪","archer":"🏹","priest":"📿"}
    TIER_UNLOCK  = {2:10, 3:30, 4:60, 5:100}

    line       = get_class_line(p) or p.get("class_id")
    if not line or line not in CLASS_TREE:
        return ["No class yet."]
    path       = p.get("class_path")        # "A", "B", or None
    base_cls   = CLASS_TREE[line]
    emoji      = CLASS_EMOJIS.get(line, "⚔️")
    unlocked   = {s["name"] for s in sjl(p.get("all_skills"), [])}
    cur_class  = p.get("class_id")

    def _skill_lines(cls_data, tier_label=""):
        lines = []
        for sk in cls_data.get("skills", []):
            status = "✅" if sk["name"] in unlocked else "🔒"
            lines.append(f"{status} *{sk['name']}*")
            if sk.get("passive"):
                lines.append(f"   🛡️ _Passive:_ {sk['passive']}")
            active_name = sk.get("active", sk["name"])
            lines.append(f"   ⚡ _Active ({active_name}):_ {sk['desc']}")
        return lines

    # Page 0: base class
    pages = []
    arch_label = LINE_ARCHETYPE.get(line, line.capitalize())
    base_lines = [
        f"{emoji} *{base_cls['name']}* ({arch_label}) — Tier 1 (Base)",
        f"_{base_cls.get('desc','')}_\n",
        "*Skills & Passives:*",
    ]
    base_lines += _skill_lines(base_cls)
    if not path:
        base_lines += ["", "_Prestige at Level 10 (/prestige) to choose Path A or B._"]
    pages.append("\n".join(base_lines))

    if not path:
        pages.append(
            f"{emoji} *Choose Your Path at Level 10!*\n\n"
            f"Use /prestige at Level 10 to unlock Path A or Path B.\n"
            f"Each path leads to 4 unique prestige classes with different playstyles.\n\n"
            f"Use /class when you have a class to preview what's ahead."
        )
        return pages

    # Pages 1-4: tier 2-5 classes along chosen path
    path_cids = CLASS_PATHS.get(line, {}).get(path, [])
    for i, cid in enumerate(path_cids):
        tier = i + 2
        req  = TIER_UNLOCK.get(tier, 10)
        pc   = CLASS_TREE.get(cid, {})
        is_current = (cur_class == cid)
        is_locked  = p["level"] < req
        header = f"{emoji} *{pc.get('name', cid)}* ({arch_label}) — Path {path}, Tier {tier}"
        if is_current:
            header += "  _(Current)_"
        elif is_locked:
            header += f"  🔒 _(Requires Lv {req})_"
        lines = [header, f"_{pc.get('desc','')}_\n", "*Skills & Passives:*"]
        lines += _skill_lines(pc)
        lines += ["", f"_Prestige at Level {req} to advance to this class._"]
        pages.append("\n".join(lines))

    return pages

async def _send_class_progression(target, uid, page, edit=False):
    p = get_player(uid)
    if not p: return
    pages = _build_class_progression_pages(p)
    total = len(pages)
    page  = max(0, min(page, total - 1))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"clsprog_{uid}_{page-1}"))
    if page < total - 1:
        pc_next = pages[page + 1].split("*")[1] if page + 1 < total else "Next"
        nav.append(InlineKeyboardButton(f"Next ▶", callback_data=f"clsprog_{uid}_{page+1}"))
    markup = InlineKeyboardMarkup([nav]) if nav else None
    text   = pages[page][:4096]

    if edit:
        try:
            await target.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass
    else:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def class_progression_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")   # clsprog_{uid}_{page}
    try:
        uid  = int(parts[1])
        page = int(parts[2])
    except (IndexError, ValueError):
        return
    if query.from_user.id != uid:
        await query.answer("Not your class info!", show_alert=True); return
    await query.answer()
    await _send_class_progression(query, uid, page, edit=True)

# ── CLASS ─────────────────────────────────────────────────────────────────────
async def class_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if p["level"] < 5:
        await send_group(update, f"⚔️ Classes unlock at *Level 5*. You're Level {p['level']}.", delay=9); return
    if p.get("class_id"):
        await _send_class_progression(update.message, user.id, page=0, edit=False)
        return
    CLASS_EMOJIS = {"warrior":"⚔️","mage":"🔮","thief":"🔪","archer":"🏹","priest":"📿"}
    if not context.args:
        # Paginated class browser — send first page
        await _send_class_browser(update.message, user.id, page=0, edit=False)
        return

    chosen = context.args[0].lower()
    if chosen not in BASE_CLASSES:
        await send_group(update, f"Unknown class. Choose: {', '.join(BASE_CLASSES)}", delay=9); return
    cls = CLASS_TREE[chosen]; p["class_id"] = chosen
    sd = safe_stats(p)
    for stat, bonus in cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat,5) + bonus
    p["stats"] = json.dumps(sd)
    # Unlock ALL tier-1 skills
    all_tier1 = [sk for sk in cls.get("skills",[]) if sk.get("tier",1) == 1]
    if not all_tier1:
        all_tier1 = cls["skills"][:1]
    p["all_skills"] = json.dumps(all_tier1)
    save_player(p)
    sk = all_tier1[0]
    skill_lines = "\n".join(f"🔸 *{s['name']}*  -  {s['desc']}" for s in all_tier1)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{p['username']}* has chosen *{cls['name']}*!"))
    await send_group(update,
        f"⚔️ *{user.first_name}* is now a *{cls['name']}*!\n\n"
        f"_{cls['desc']}_\n\n"
        f"🔹 Passive: {sk['passive']}\n"
        f"{skill_lines}\n\n"
        f"At *Level 10*, use /prestige to choose your path (A or B).",
        delay=30)

async def class_pick_callback(update, context):
    """Handle class picker buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data  # class_pick_{uid}_{class_id}
    parts = data.split("_")
    # Format: class_pick_{uid}_{class_id}
    # parts: ['class','pick',uid,class_id]
    if len(parts) < 4:
        return
    try:
        uid = int(parts[2])
    except (ValueError, IndexError):
        return
    class_id = parts[3]

    if query.from_user.id != uid:
        await query.answer("This class picker isn't for you!", show_alert=True)
        return

    p = get_player(uid)
    if not p:
        await query.answer("Player not found!", show_alert=True)
        return
    if p.get("class_id"):
        await query.answer("You already have a class!", show_alert=True)
        return
    if class_id not in BASE_CLASSES:
        await query.answer("Invalid class!", show_alert=True)
        return

    cls = CLASS_TREE[class_id]
    p["class_id"] = class_id
    sd = safe_stats(p)
    for stat, bonus in cls.get("stat_bonus", {}).items():
        sd[stat] = sd.get(stat, 5) + bonus
    p["stats"] = json.dumps(sd)
    all_tier1 = [sk for sk in cls.get("skills", []) if sk.get("tier", 1) == 1]
    if not all_tier1:
        all_tier1 = cls["skills"][:1]
    p["all_skills"] = json.dumps(all_tier1)
    save_player(p)
    sk = all_tier1[0]
    skill_lines = "\n".join(f"🔸 *{s['name']}*  -  {s['desc']}" for s in all_tier1)
    result = (f"⚔️ *You are now a {cls['name']}!*\n\n"
              f"_{cls['desc']}_\n\n"
              f"🔹 Passive: {sk['passive']}\n"
              f"{skill_lines}\n\n"
              f"At *Level 10*, use /prestige to choose your path (A or B).")
    try:
        await query.edit_message_text(result, parse_mode="Markdown")
    except Exception:
        pass
    try:
        await query.get_bot().send_message(
            chat_id=query.message.chat.id,
            text=f"⚔️ *{p['username']}* has chosen *{cls['name']}*!",
            parse_mode="Markdown")
    except Exception:
        pass

# ── CLASS RESET ───────────────────────────────────────────────────────────────
def _calc_applied_class_bonuses(p):
    """Return total stat bonuses applied through all class advancements so far."""
    cid   = p.get("class_id")
    if not cid:
        return {}
    cls   = CLASS_TREE.get(cid, {})
    line  = cls.get("line") or cid
    path  = p.get("class_path")
    level = safe_int(p.get("level", 1))
    total = {}

    def _add(class_key):
        for stat, val in CLASS_TREE.get(class_key, {}).get("stat_bonus", {}).items():
            total[stat] = total.get(stat, 0) + val

    # Base class (chosen at Lv5)
    if line in BASE_CLASSES:
        _add(line)

    # Path advancements applied based on level thresholds
    if path:
        path_list = CLASS_PATHS.get(line, {}).get(path, [])
        for threshold, idx in [(10, 0), (30, 1), (60, 2), (100, 3)]:
            if level >= threshold and idx < len(path_list):
                _add(path_list[idx])

    return total


async def resetclass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("class_id"):
        await send_group(update, "You don't have a class yet  -  use /class to pick one.", delay=9); return

    cls      = get_player_class(p)
    cls_name = cls["name"] if cls else "Unknown"
    path_str = f" (Path {p['class_path']})" if p.get("class_path") else ""
    cost     = 300

    if not context.args or context.args[0].lower() != "confirm":
        rscls_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm Reset", callback_data=f"rscls_confirm_{user.id}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"rscls_cancel_{user.id}"),
        ]])
        await send_group(update,
            f"⚠️ *Class Reset*\n\n"
            f"Current class: *{cls_name}*{path_str}\n\n"
            f"This will:\n"
            f"  - Remove your class and path\n"
            f"  - Remove all class skills\n"
            f"  - Reverse class stat bonuses\n"
            f"  - Keep your level, allocated stat points, gear, and gold\n\n"
            f"Cost: *{cost}g*\n\n"
            f"Tap Confirm or type /resetclass confirm to proceed.",
            delay=20, reply_markup=rscls_markup); return

    if safe_int(p.get("gold")) < cost:
        await send_group(update,
            f"Not enough gold! Need {cost}g, you have {p.get('gold',0)}g.", delay=9); return

    # Subtract all applied class stat bonuses
    bonuses = _calc_applied_class_bonuses(p)
    sd = safe_stats(p)
    for stat, val in bonuses.items():
        sd[stat] = max(0, sd.get(stat, 0) - val)
    p["stats"]      = json.dumps(sd)
    p["class_id"]   = None
    p["class_path"] = None
    p["all_skills"] = json.dumps([])
    p["gold"]       = safe_int(p.get("gold")) - cost
    save_player(p)

    await send_group(update,
        f"🔄 *{user.first_name}* has reset their class.\n\n"
        f"Class bonuses from *{cls_name}* have been reversed.\n"
        f"Use /class to choose a new class.",
        delay=15)

async def resetclass_callback(update, context):
    """Handle resetclass confirm/cancel buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data  # rscls_confirm_{uid} or rscls_cancel_{uid}
    parts = data.split("_")
    if len(parts) < 3:
        return
    action = parts[1]  # 'confirm' or 'cancel'
    try:
        uid = int(parts[2])
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your reset button!", show_alert=True)
        return

    if action == "cancel":
        try:
            await query.edit_message_text("❌ Class reset cancelled.", parse_mode="Markdown")
        except Exception:
            pass
        return

    # action == "confirm"
    p = get_player(uid)
    if not p or not p.get("class_id"):
        await query.answer("No class to reset!", show_alert=True)
        return
    cost = 300
    if safe_int(p.get("gold")) < cost:
        await query.answer(f"Not enough gold! Need {cost}g.", show_alert=True)
        return
    cls = get_player_class(p)
    cls_name = cls["name"] if cls else "Unknown"
    bonuses = _calc_applied_class_bonuses(p)
    sd = safe_stats(p)
    for stat, val in bonuses.items():
        sd[stat] = max(0, sd.get(stat, 0) - val)
    p["stats"]      = json.dumps(sd)
    p["class_id"]   = None
    p["class_path"] = None
    p["all_skills"] = json.dumps([])
    p["gold"]       = safe_int(p.get("gold")) - cost
    save_player(p)
    result = (f"🔄 *Class reset complete!*\n\n"
              f"Class bonuses from *{cls_name}* have been reversed.\n"
              f"Use /class to choose a new class.")
    try:
        await query.edit_message_text(result, parse_mode="Markdown")
    except Exception:
        pass


# ── PRESTIGE (path selection at Lv 10, auto-advance after) ───────────────────
async def prestige_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    cid = p.get("class_id")
    if not cid:
        await send_group(update, "Choose a class first with /class.", delay=9); return
    cls = CLASS_TREE.get(cid,{})
    line = cls.get("line")
    path = p.get("class_path")

    # Already has path  -  show path status and progression
    if path:
        full_path = CLASS_PATHS.get(line, {}).get(path, [])
        path_names = " → ".join(CLASS_TREE.get(k,{}).get("name","?") for k in full_path)
        current_cls = get_player_class(p)
        current_cls_name = current_cls["name"] if current_cls else "Unknown"
        next_threshold = None
        for lvl in [30,60,100]:
            if p["level"] < lvl:
                next_threshold = lvl; break
        if next_threshold:
            await send_group(update,
                f"🌟 *Path {path}*  -  Current Class: *{current_cls_name}*\n\n"
                f"📜 Path: {path_names}\n\n"
                f"Your class advances automatically at Level *{next_threshold}*.\n"
                f"Keep leveling!", delay=15)
        else:
            await send_group(update,
                f"👑 *Path {path}*  -  Current Class: *{current_cls_name}*\n\n"
                f"📜 Path: {path_names}\n\n"
                f"You have reached *Level 100*  -  the pinnacle of Path {path}!\n"
                f"You may optionally reset and start a new class journey.\n"
                f"Use `/prestige reset` to do so (keeps all stats and skills).", delay=15)
        return

    # Lv 10 path selection
    if p["level"] < 10:
        await send_group(update,
            f"🌟 Path selection unlocks at *Level 10*. You're Level {p['level']}.", delay=9); return

    paths = CLASS_PATHS.get(line, {})
    path_a_first = paths.get("A",[])[0] if paths.get("A") else None
    path_b_first = paths.get("B",[])[0] if paths.get("B") else None

    if not context.args:
        lines = [f"🌟 *Choose your path, {user.first_name}!*\n",
                 "_This choice is permanent._\n"]
        for label, key in [("A", path_a_first), ("B", path_b_first)]:
            if not key: continue
            nc = CLASS_TREE.get(key,{})
            sk = nc.get("skills",[{}])[0]
            full_path = paths.get(label,[])
            path_names = " → ".join(CLASS_TREE.get(k,{}).get("name","?") for k in full_path)
            lines.append(
                f"*Path {label}: {nc.get('name','?')}*\n"
                f"_{nc.get('desc','')}_\n"
                f"🔹 {sk.get('passive','')}\n"
                f"🔸 {sk.get('name','?')}: {sk.get('desc','')}\n"
                f"📜 Full path: {path_names}\n")
        prestige_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Path A", callback_data=f"prestige_{user.id}_A"),
            InlineKeyboardButton("Path B", callback_data=f"prestige_{user.id}_B"),
        ]])
        lines.append("_Tap a button below or use `/prestige A` / `/prestige B` to choose._")
        await send_group(update, "\n".join(lines), delay=60, reply_markup=prestige_markup); return

    if context.args[0].upper() == "RESET" and p["level"] >= 100:
        # Prestige reset
        old_skills = sjl(p.get("all_skills"), [])
        existing_prestige = sjl(p.get("prestige_skills"), [])
        for sk in old_skills:
            if sk not in existing_prestige:
                existing_prestige.append(sk)
        p["prestige_skills"] = json.dumps(existing_prestige)
        p["prestige_count"]  = safe_int(p.get("prestige_count")) + 1
        p["level"] = 1; p["exp"] = 0
        p["class_id"] = None; p["class_path"] = None
        p["all_skills"] = json.dumps([])
        p["max_hp"] = max_hp_for_level(1); p["hp"] = p["max_hp"]
        p["stat_points"] = safe_int(p.get("stat_points")) + 10
        award_title(p, "Gone Pro"); save_player(p)
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🌟 *{p['username']}* has PRESTIGED! A new journey begins! 🌟",
            permanent=True))
        await send_group(update,
            f"🌟 *PRESTIGE {p['prestige_count']}!*\n\n"
            f"All previous skills become permanent passives.\n"
            f"+10 bonus stat points.\n"
            f"Choose a new class with /class.", delay=30); return

    chosen_path = context.args[0].upper()
    if chosen_path not in ("A","B"):
        await send_group(update, "Use `/prestige A` or `/prestige B`.", delay=9); return

    first_class = paths.get(chosen_path,[])[0] if paths.get(chosen_path) else None
    if not first_class:
        await send_group(update, "Invalid path.", delay=9); return

    p["class_path"] = chosen_path
    p["class_id"]   = first_class
    new_cls = CLASS_TREE.get(first_class,{})
    sd = safe_stats(p)
    for stat, bonus in new_cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat,5) + bonus
    p["stats"] = json.dumps(sd)
    # Unlock path skill
    existing = sjl(p.get("all_skills"), [])
    for sk in new_cls.get("skills",[]):
        if sk["name"] not in [s["name"] for s in existing]:
            existing.append(sk)
    p["all_skills"] = json.dumps(existing)
    save_player(p)

    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"🌟 *{p['username']}* chose *Path {chosen_path}*  -  *{new_cls['name']}*!"))
    full_path = paths.get(chosen_path,[])
    path_names = " → ".join(CLASS_TREE.get(k,{}).get("name","?") for k in full_path)
    await send_group(update,
        f"🌟 *Path {chosen_path} chosen!* You are now a *{new_cls['name']}*!\n\n"
        f"_{new_cls['desc']}_\n\n"
        f"📜 Your journey: {path_names}\n\n"
        f"_Your class evolves automatically at Levels 30, 60, and 100._",
        delay=30)

# ── ALLOCATE ──────────────────────────────────────────────────────────────────
async def allocate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    sp = safe_int(p.get("stat_points")); sd = safe_stats(p)
    STAT_NAMES = ["STR","AGI","INT","WIS","DEX","LUK"]
    cls = get_player_class(p)
    rec = cls["primary_stat"] + " recommended" if cls else "Free to allocate"
    if not context.args or len(context.args) < 2:
        alloc_text = (f"📊 *Stat Allocation*  -  *{sp}* points available\n\n"
            f"STR:{sd.get('STR',5)} AGI:{sd.get('AGI',5)} INT:{sd.get('INT',5)} "
            f"WIS:{sd.get('WIS',5)} DEX:{sd.get('DEX',5)} LUK:{sd.get('LUK',5)}\n\n"
            f"📌 STR  -  Attack damage (Warrior)\n"
            f"📌 AGI  -  Dodge & crit\n"
            f"📌 INT  -  Spell damage (Mage)\n"
            f"📌 WIS  -  Heal power (Priest)\n"
            f"📌 DEX  -  Accuracy & crit (Archer)\n"
            f"📌 LUK  -  Crit & gold bonus (Thief)\n"
            f"📌 DEF  -  From gear only (cannot allocate)\n\n"
            f"🧭 {rec}\n\nUsage: `/allocate STR 5`")
        alloc_rows = []
        if sp > 0:
            for s in STAT_NAMES:
                row = [InlineKeyboardButton(f"{s} +1", callback_data=f"alloc_{user.id}_{s}_1")]
                if sp >= 5:
                    row.append(InlineKeyboardButton(f"{s} +5", callback_data=f"alloc_{user.id}_{s}_5"))
                alloc_rows.append(row)
        alloc_markup = InlineKeyboardMarkup(alloc_rows) if alloc_rows else None
        await send_group(update, alloc_text, delay=30, reply_markup=alloc_markup); return
    stat = context.args[0].upper()
    if stat not in STAT_NAMES:
        await send_group(update, f"Unknown stat. Choose: {', '.join(STAT_NAMES)}", delay=9); return
    try: amount = int(context.args[1])
    except:
        await send_group(update, "Usage: `/allocate STR 5`", delay=9); return
    if amount <= 0:
        await send_group(update, "Amount must be positive.", delay=9); return
    if amount > sp:
        await send_group(update, f"Not enough points! You have {sp}.", delay=9); return
    sd[stat] = sd.get(stat,5) + amount
    p["stats"] = json.dumps(sd)
    p["stat_points"] = sp - amount
    save_player(p)
    await send_group(update,
        f"✅ +{amount} to *{stat}*! Now at {sd[stat]}.\n💡 {p['stat_points']} points remaining.",
        delay=9)

# ── DAILY ─────────────────────────────────────────────────────────────────────
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not check_cooldown(p.get("last_daily"), 86400):
        await send_group(update,
            f"🎁 Daily already claimed! Come back in "
            f"{time_remaining(p.get('last_daily'), 86400)}.", delay=9); return
    p["last_daily"] = datetime.now().isoformat()
    gold = 50 + p["level"] * 5; p["gold"] = p.get("gold",0) + gold
    # Rare potion chance
    item = None
    if random.random() < 0.10:
        item = random.choice(["Health Potion","Greater Health Potion","Grand Restorative Flask"])
        add_item(p, item)
    daily_exp = 200 + (p["level"] * 10)
    lmsgs, leveled = add_exp(p, daily_exp)
    save_player(p)
    msg = f"🎁 *Daily Reward!*\n\n✨ +{daily_exp} EXP | 💰 +{gold} Gold"
    if item: msg += f" | 🎒 *{item}* (lucky drop!)"
    else:    msg += f"\n_(Nothing extra today  -  check the /shop)_"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from daily! 🎁",
            permanent=True))
    await send_group(update, msg, delay=30)

# ── TRAIN ─────────────────────────────────────────────────────────────────────
TRAIN_MESSAGES = [
    "You drilled straight shots until your bridge hand went numb.",
    "You ran the same pattern forty times until it became automatic.",
    "You practiced kick shots on an empty table until the angles were memorized.",
    "You studied safety play until safe shots became your first instinct.",
    "You worked on your break until the rack split exactly how you wanted.",
    "You spent an hour on draw shots, learning where the cue ball goes.",
    "You practiced position play  -  potting the ball was never the problem.",
    "You ran ghost ball drills until every cut angle was committed to muscle memory.",
]

async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 Too beaten up to train!", delay=9); return
    if not check_cooldown(p.get("last_train"), 1800):
        await send_group(update,
            f"⏳ Train again in {time_remaining(p.get('last_train'), 1800)}.", delay=9); return
    p["last_train"] = datetime.now().isoformat()
    base = 150 + p["level"] * 5
    cls  = get_player_class(p)
    note = ""
    if cls:
        pk = cls.get("passive_key","")
        if pk in ("arcane_mind","spell_surge","arcane_mastery","mana_overload","eternal_wisdom"):
            base = round(base*1.30); note = f"\n🔮 *{cls['name']}* focus bonus! +30%"
        elif pk in ("iron_will","holy_stance","devotion","bulwark","divine_judgment"):
            base = round(base*1.20); note = f"\n🛡️ *{cls['name']}* endurance bonus! +20%"
        elif pk in ("quick_hands","evasion","shadowstep","ghost_form","deaths_shadow",
                    "eagle_eye","trailblazer","natures_bond","guardian_stance","pathfinder"):
            base = round(base*1.35); note = f"\n⚡ *{cls['name']}* speed bonus! +35%"
        elif pk in ("mending_aura","divine_grace","sacred_ground","resurrection","divine_presence",
                    "dark_sense","purge","judgement","wrath_of_the_righteous"):
            base = round(base*1.15); note = f"\n✨ *{cls['name']}* wisdom bonus! +15%"
    lmsgs, leveled = add_exp(p, base); save_player(p)
    flavor = random.choice(TRAIN_MESSAGES)
    msg = f"🏋️ *Training Session*\n\n_{flavor}_\n\n✨ +{base} EXP{note}"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from training! 🏋️",
            permanent=True))
    await send_group(update, msg, delay=30)

# ── QUEST ─────────────────────────────────────────────────────────────────────
async def quest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, _defeated_msg(p), delay=15); return
    if not check_cooldown(p.get("last_quest"), 3600):
        await send_group(update,
            f"⏳ Next quest in {time_remaining(p.get('last_quest'), 3600)}.", delay=9); return
    p["last_quest"] = datetime.now().isoformat()
    w = get_weather()
    if p["level"] <= 3:   pool = [q for q in SOLO_QUESTS if q["tier"]=="Easy"]
    elif p["level"] <= 7: pool = [q for q in SOLO_QUESTS if q["tier"] in ["Easy","Medium"]]
    else:                 pool = SOLO_QUESTS
    if not pool: pool = SOLO_QUESTS
    q = random.choice(pool)
    item_found = roll_loot_table(q.get("loot_table",[]))
    if item_found: add_item(p, item_found)
    luk_val = get_stat(p, "LUK")
    gold_bonus_pct = luk_val * 0.002
    gold = round(q["gold"] * (1 + gold_bonus_pct))
    p["gold"] = p.get("gold",0) + gold
    p["quests_done"] = p.get("quests_done",0) + 1
    for _d, _e, _g in track_objective(p, "quest_run"):
        p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
    gid = p.get("guild_id")
    if gid and str(gid) != "None":
        g = get_guild(gid)
        if g: add_guild_exp(g, 20); save_guild(g)
    lmsgs, leveled = add_exp(p, q["exp"], w)
    new_t = check_titles(p); save_player(p)
    msg = f"🗺️ *Quest  -  {q['tier']}*\n\n{q['text']}\n\n✨ +{q['exp']} EXP | 💰 +{gold} Gold"
    if item_found:
        rarity = ""
        for pool2 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
            if item_found in pool2:
                r = pool2[item_found].get("rarity","")
                rarity = RARITY_EMOJI.get(r,"")
                break
        msg += f"\n🎒 Found: {rarity} *{item_found}*!"
    if new_t: msg += f"\n🏅 New title: *{new_t[0]}*!"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from a quest! 🗺️",
            permanent=True))
    await send_group(update, msg, delay=45)

# ── EXPLORE ───────────────────────────────────────────────────────────────────
async def explore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 Can't explore while defeated!", delay=9); return
    # Check twice-per-day limit
    today = datetime.now().strftime("%Y-%m-%d")
    if p.get("explore_date") == today and safe_int(p.get("explore_count_today")) >= 2:
        await send_group(update, "🗺️ You've explored twice today. Come back tomorrow!", delay=9); return
    # Check if already on expedition
    if user.id in explore_timers and not explore_timers[user.id].done():
        await send_group(update, "🗺️ You're already on an expedition! Results coming soon.", delay=9); return

    # Pick zone — show buttons if no args
    if not context.args:
        if p["level"] <= 5:     unlocked_tiers = {"Easy"}
        elif p["level"] <= 15:  unlocked_tiers = {"Easy","Medium"}
        elif p["level"] <= 30:  unlocked_tiers = {"Easy","Medium","Hard"}
        elif p["level"] <= 60:  unlocked_tiers = {"Easy","Medium","Hard","Elite"}
        else:                   unlocked_tiers = {"Easy","Medium","Hard","Elite","Legendary"}
        remaining = 2 - safe_int(p.get("explore_count_today") if p.get("explore_date") == datetime.now().strftime("%Y-%m-%d") else 0)
        tier_emoji = {"Easy":"🟢","Medium":"🟡","Hard":"🟠","Elite":"🔴","Legendary":"💀"}
        buttons = []
        for z in EXPLORE_ZONES:
            locked = z["tier"] not in unlocked_tiers
            label = f"{'🔒' if locked else tier_emoji.get(z['tier'],'🗺️')} {z['name']} ({z['tier']})"
            if not locked:
                buttons.append([InlineKeyboardButton(label, callback_data=f"explore_{user.id}_{z['name']}")])
            else:
                buttons.append([InlineKeyboardButton(label, callback_data=f"explore_locked")])
        await send_group(update,
            f"🗺️ *Expedition — Choose a Zone*\n\n"
            f"_{remaining} expedition{'s' if remaining!=1 else ''} remaining today. Results in 1 hour._",
            reply_markup=InlineKeyboardMarkup(buttons), delay=30)
        return

    if context.args:
        zn = " ".join(context.args).lower()
        zone = next((z for z in EXPLORE_ZONES if zn in z["name"].lower()), None)
        if not zone:
            zlist = "\n".join(f"• {z['name']} ({z['tier']})" for z in EXPLORE_ZONES)
            await send_group(update, f"Unknown zone. Available:\n{zlist}", delay=15); return

    # Update explore count
    if p.get("explore_date") != today:
        p["explore_count_today"] = 0
        p["explore_date"] = today
    p["explore_count_today"] = safe_int(p.get("explore_count_today")) + 1
    p["last_explore"] = datetime.now().isoformat()
    save_player(p)

    remaining = 2 - safe_int(p.get("explore_count_today"))
    await send_group(update,
        f"🗺️ *Expedition Started!*\n\n"
        f"📍 Destination: *{zone['name']}* ({zone['tier']})\n"
        f"⏱️ Returns in *1 hour*.\n"
        f"🎒 Results posted in the group when you return.\n\n"
        f"_{remaining} expedition{'s' if remaining != 1 else ''} remaining today._",
        delay=30)

    chat_id = update.effective_chat.id
    bot     = update.get_bot()

    async def deliver_result():
        await asyncio.sleep(3600)  # 1 hour
        pp = get_player(user.id)
        if not pp: return
        w2  = get_weather()
        success = random.random() < 0.70  # 70% base success
        if success:
            exp  = round(zone["exp"] * w2.get("exp_mod",1.0))
            gold = zone["gold"]
            pp["gold"] = pp.get("gold",0) + gold
            item_found = roll_loot_table(zone.get("loot_table",[]))
            if item_found: add_item(pp, item_found)
            lmsgs, leveled = add_exp(pp, exp)
            save_player(pp)
            rarity = ""
            if item_found:
                for pool2 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
                    if item_found in pool2:
                        r = pool2[item_found].get("rarity","")
                        rarity = RARITY_EMOJI.get(r,"")
                        break
            msg = (f"🗺️ *{pp['username']}* returns from *{zone['name']}*!\n\n"
                   f"✅ Expedition successful!\n"
                   f"✨ +{exp} EXP | 💰 +{gold} Gold")
            if item_found: msg += f"\n🎒 Found: {rarity} *{item_found}*!"
            if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
            if leveled and pp["level"] % 10 == 0:
                asyncio.create_task(announce(bot, chat_id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}* from exploring! 🗺️",
                    permanent=True))
        else:
            cons = random.randint(5,20)
            pp["gold"] = pp.get("gold",0) + cons; save_player(pp)
            msg = (f"🗺️ *{pp['username']}* returns from *{zone['name']}*.\n\n"
                   f"❌ {zone['fail_msg']}\n"
                   f"💰 Salvaged {cons} gold on the way back.")
        await announce(bot, chat_id, msg, delay=90)

    task = asyncio.create_task(deliver_result())
    explore_timers[user.id] = task


async def explore_zone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle zone selection button for /explore."""
    query = update.callback_query
    if query.data == "explore_locked":
        await query.answer("Zone locked — level up to unlock!", show_alert=True); return
    parts = query.data.split("_", 2)
    try: uid = int(parts[1]); zone_name = parts[2]
    except (IndexError, ValueError): await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your expedition menu!", show_alert=True); return
    p = get_player(uid)
    if not p: await query.answer("Player not found.", show_alert=True); return
    if is_defeated(p): await query.answer("Can't explore while defeated!", show_alert=True); return
    today = datetime.now().strftime("%Y-%m-%d")
    if p.get("explore_date") == today and safe_int(p.get("explore_count_today")) >= 2:
        await query.answer("You've explored twice today. Come back tomorrow!", show_alert=True); return
    if uid in explore_timers and not explore_timers[uid].done():
        await query.answer("You're already on an expedition!", show_alert=True); return
    zone = next((z for z in EXPLORE_ZONES if z["name"] == zone_name), None)
    if not zone: await query.answer("Zone not found.", show_alert=True); return
    if p.get("explore_date") != today:
        p["explore_count_today"] = 0; p["explore_date"] = today
    p["explore_count_today"] = safe_int(p.get("explore_count_today")) + 1
    p["last_explore"] = datetime.now().isoformat()
    save_player(p)
    remaining = 2 - safe_int(p.get("explore_count_today"))
    await query.answer(f"Expedition started! Returns in 1 hour.")
    await query.edit_message_text(
        f"🗺️ *Expedition Started!*\n\n"
        f"📍 Destination: *{zone['name']}* ({zone['tier']})\n"
        f"⏱️ Returns in *1 hour*.\n"
        f"🎒 Results posted in the group when you return.\n\n"
        f"_{remaining} expedition{'s' if remaining!=1 else ''} remaining today._",
        parse_mode="Markdown")
    chat_id = query.message.chat_id
    bot = context.bot

    async def deliver_result():
        await asyncio.sleep(3600)
        p2 = get_player(uid)
        if not p2: return
        success = random.random() < 0.75
        loot_item = None
        if success:
            for item_name_r, chance in zone["loot_table"]:
                if random.random() < chance:
                    loot_item = item_name_r; break
        gold_r = round(zone["gold"] * random.uniform(0.7, 1.3)) if success else 0
        exp_r  = round(zone["exp"]  * random.uniform(0.7, 1.3)) if success else round(zone["exp"] * 0.1)
        if success:
            msg = (f"🗺️ *{p2['username']}* returns from *{zone['name']}*.\n\n"
                   f"💰 +{gold_r} gold | ✨ +{exp_r} EXP"
                   + (f"\n🎒 Found: *{loot_item}*!" if loot_item else ""))
            p2["gold"] = p2.get("gold", 0) + gold_r
            if loot_item: add_item(p2, loot_item)
            add_exp(p2, exp_r); save_player(p2)
        else:
            cons = round(zone["gold"] * 0.1)
            p2["gold"] = p2.get("gold", 0) + cons
            msg = (f"🗺️ *{p2['username']}* returns from *{zone['name']}*.\n\n"
                   f"❌ {zone['fail_msg']}\n"
                   f"💰 Salvaged {cons} gold on the way back.")
            save_player(p2)
        await announce(bot, chat_id, msg, delay=90)

    task = asyncio.create_task(deliver_result())
    explore_timers[uid] = task


# ── GUILD ─────────────────────────────────────────────────────────────────────
async def purge_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exorcist or anyone can purge the cursed event."""
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "cursed": return
    active_events.pop(chat_id, None)
    target_id = event.get("cursed_player_id")
    if target_id:
        tp = get_player(target_id)
        if tp:
            tp["passive_cooldowns"] = json.dumps({
                k:v for k,v in safe_cds(tp).items() if k != "cursed_until"})
            save_player(tp)
    await send_group(update, f"✨ *{user.first_name}* purges the curse! The afflicted player is free.", delay=20)

async def _handle_drake_strike(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /strike reply to Wild Drake event message."""
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p or is_defeated(p): return
    drake = active_drakes.get(chat_id)
    if not drake: return
    w   = get_weather(); dmg = calc_attack_damage(p, w)
    drake["hp"] = max(0, drake["hp"] - dmg)
    drake.setdefault("fighters",{})
    drake["fighters"][user.id] = drake["fighters"].get(user.id,0) + dmg

    if drake["hp"] <= 0:
        active_drakes.pop(chat_id, None)
        total_dmg = sum(drake["fighters"].values())
        lines = ["🐉 *The Wild Drake has been slain!*\n"]
        for fid, fd in drake["fighters"].items():
            fp = get_player(fid)
            if not fp: continue
            share = fd / max(1, total_dmg)
            exp   = round(drake.get("exp_reward",1000) * share)
            loot  = None
            if random.random() < share * 0.5:
                loot = roll_loot_table([(n,c) for n,c in drake.get("loot_table",[])])
            if loot: add_item(fp, loot)
            lmsgs, leveled = add_exp(fp, exp); save_player(fp)
            lines.append(f"✅ *{fp['username']}*  -  {int(share*100)}% dmg | +{exp} EXP"
                         + (f" | 🎒 {loot}" if loot else ""))
            if leveled and fp["level"] % 10 == 0:
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🎉 *{fp['username']}* reached *Level {fp['level']}*! 🐉", permanent=True))
        await announce(context.bot, chat_id, "\n".join(lines), permanent=True)
    else:
        await announce(context.bot, chat_id,
            f"🐉 *{user.first_name}* hits the Drake for *{dmg}*! ❤️ HP: {drake['hp']}/500")

# ── MAIN ──────────────────────────────────────────────────────────────────────
async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    discount = 0
    if _ts_active(p, "shop_discount_until"): discount = 0.20
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            guild_disc = 0.15 if glvl >= 10 else (0.10 if glvl >= 7 else 0)
            discount = max(discount, guild_disc)

    if not context.args:
        shop = get_daily_shop()
        lines = [f"🛒 *Daily Shop* | 💰 {p['gold']} gold\n"]
        if discount: lines.append(f"🏷️ Discount active: *{int(discount*100)}% off!*\n")
        shop_buttons = []
        for i, entry in enumerate(shop):
            price = round(entry["price"] * (1-discount))
            lines.append(f"{i+1}. *{entry['item']}*  -  {price}g\n   _{entry['desc']}_")
            shop_buttons.append([InlineKeyboardButton(
                f"Buy {i+1}: {entry['item']}", callback_data=f"shop_b_{user.id}_{i}")])
        lines.append(f"\n`/shop buy [1-{len(shop)}]` to purchase.")
        shop_markup = InlineKeyboardMarkup(shop_buttons)
        await send_group(update, "\n".join(lines), delay=30, reply_markup=shop_markup); return

    if context.args[0].lower() == "buy":
        if len(context.args) < 2:
            await send_group(update, f"Usage: `/shop buy [1-5]`", delay=9); return
        try: idx = int(context.args[1]) - 1
        except:
            await send_group(update, f"Usage: `/shop buy [1-5]`", delay=9); return
        shop = get_daily_shop()
        if idx < 0 or idx >= len(shop):
            await send_group(update, "Invalid number.", delay=9); return
        entry = shop[idx]; price = round(entry["price"] * (1-discount))
        if p["gold"] < price:
            await send_group(update, f"❌ Need {price}g, have {p['gold']}g.", delay=9); return
        p["gold"] -= price; add_item(p, entry["item"]); save_player(p)
        await send_group(update,
            f"✅ Bought *{entry['item']}* for {price}g!\n💰 Remaining: {p['gold']}g", delay=15)

# ── INVENTORY / EQUIP / USE / SELL ────────────────────────────────────────────
INV_SECTIONS = ["Equipped", "Weapons", "Armors", "Shields", "Accessories", "Consumables", "Materials"]

def _build_inv_sections(p):
    """Return ordered list of section names that have content for this player."""
    inv = Counter(sjl(p.get("inventory"), []))
    present = []
    has_equipped = any(p.get(k) for k in ["equipped_weapon","equipped_armor","equipped_shield","equipped_accessory"])
    if has_equipped:
        present.append("Equipped")
    if any(k in WEAPONS for k in inv) or p.get("equipped_weapon"):         present.append("Weapons")
    if any(k in ARMORS for k in inv) or p.get("equipped_armor"):           present.append("Armors")
    if any(k in SHIELDS for k in inv) or p.get("equipped_shield"):         present.append("Shields")
    if any(k in ACCESSORIES for k in inv) or p.get("equipped_accessory"): present.append("Accessories")
    if any(k in CONSUMABLES for k in inv): present.append("Consumables")
    if any(k not in {**WEAPONS,**ARMORS,**SHIELDS,**ACCESSORIES,**CONSUMABLES} for k in inv):
        present.append("Materials")
    if not present:
        present.append("Equipped")
    return present

def _render_bag_item(p, item, count):
    """Return formatted line(s) for a single bag item."""
    if item in WEAPONS:
        d = WEAPONS[item]
        line = d.get("line", "")
        arch = LINE_ARCHETYPE.get(line, line.capitalize())
        weap_emoji = {"mage": "🪄", "thief": "🔪", "archer": "🏹", "priest": "📿"}.get(line, "⚔️")
        type_tag = f"{weap_emoji} Weapon [{arch}]" if arch else f"{weap_emoji} Weapon"
        rarity = RARITY_EMOJI.get(d.get("rarity",""), "⚪")
        stat_str = f"+{d['atk']} ATK"
    elif item in ARMORS:
        d = ARMORS[item]
        line = d.get("line", "")
        arch = LINE_ARCHETYPE.get(line, line.capitalize())
        type_tag = f"🛡️ Armor [{arch}]" if arch else "🛡️ Armor"
        rarity = RARITY_EMOJI.get(d.get("rarity",""), "⚪")
        stat_str = f"+{d['def']} DEF"
    elif item in SHIELDS:
        d = SHIELDS[item]
        line = d.get("line", "")
        arch = LINE_ARCHETYPE.get(line, line.capitalize())
        is_claw = d.get("type") == "claw"
        type_tag = (f"🗡️ Claw [{arch}]" if arch else "🗡️ Claw") if is_claw else (f"🔰 Shield [{arch}]" if arch else "🔰 Shield")
        rarity = RARITY_EMOJI.get(d.get("rarity",""), "⚪")
        stat_str = f"+{d.get('atk',0)} ATK" if is_claw else f"+{d.get('def',0)} DEF"
    elif item in ACCESSORIES:
        d = ACCESSORIES[item]
        type_tag = "💍 Accessory"
        rarity = RARITY_EMOJI.get(d.get("rarity",""), "⚪")
        stat_str = d.get("desc","")[:40]
    elif item in CONSUMABLES:
        d = CONSUMABLES[item]
        type_tag = "🧪 Consumable"
        rarity = "⚪"
        stat_str = d.get("desc","")
    else:
        type_tag = "📦 Material"; rarity = "⚪"; stat_str = ""
    enh = get_enhancement(p, item)
    encs = get_enchant(p, item) if item in {**WEAPONS,**ARMORS,**SHIELDS,**ACCESSORIES} else []
    enh_str = f" *+{enh}*" if enh > 0 else ""
    enc_str = f" ✨×{len(encs)}" if encs else ""
    return f"{rarity} *{item}*{enh_str}{enc_str} x{count}\n  {type_tag} - _{stat_str}_"

async def _send_inventory_section(target, p, section="Equipped", edit=False):
    sections = _build_inv_sections(p)
    if section not in sections:
        section = sections[0]

    inv = Counter(sjl(p.get("inventory"), []))
    lines = [f"🎒 *{p['username']}'s Inventory*\n"]

    if section == "Equipped":
        has_any = False
        for slot_key, emoji in [("equipped_weapon","⚔️"),("equipped_armor","🛡️"),
                                  ("equipped_shield","🔰"),("equipped_accessory","💍")]:
            name = p.get(slot_key)
            if not name: continue
            has_any = True
            enh = get_enhancement(p, name)
            encs_slot = get_enchant(p, name)
            tags = []
            if enh: tags.append(f"+{enh}")
            if encs_slot: tags.append(f"✨×{len(encs_slot)}")
            tag_str = " " + " ".join(tags) if tags else ""
            slot_label = slot_key.replace("equipped_","").capitalize()
            lines.append(f"{emoji} *{name}*{tag_str}  _({slot_label})_")
        if not has_any:
            lines.append("_Nothing equipped._")
    else:
        pool_map = {
            "Weapons":     (WEAPONS,     lambda k: k in WEAPONS),
            "Armors":      (ARMORS,      lambda k: k in ARMORS),
            "Shields":     (SHIELDS,     lambda k: k in SHIELDS),
            "Accessories": (ACCESSORIES, lambda k: k in ACCESSORIES),
            "Consumables": (CONSUMABLES, lambda k: k in CONSUMABLES),
            "Materials":   ({},          lambda k: k not in {**WEAPONS,**ARMORS,**SHIELDS,**ACCESSORIES,**CONSUMABLES}),
        }
        _, pred = pool_map[section]
        bucket = [(k, v) for k, v in inv.items() if pred(k)]
        if bucket:
            for item, count in sorted(bucket, key=lambda kv: kv[0]):
                lines.append(_render_bag_item(p, item, count))
        else:
            lines.append(f"_No {section.lower()} in bag._")

    lines.append(f"\n_/equip | /enhance | /enchant | /reinforce | /use_")

    # Navigation buttons — named like /stats
    idx = sections.index(section)
    btn_row = []
    if idx > 0:
        prev = sections[idx - 1]
        btn_row.append(InlineKeyboardButton(f"◀ {prev}", callback_data=f"inv_s_{prev}"))
    if idx < len(sections) - 1:
        nxt = sections[idx + 1]
        btn_row.append(InlineKeyboardButton(f"{nxt} ▶", callback_data=f"inv_s_{nxt}"))
    markup = InlineKeyboardMarkup([btn_row]) if btn_row else None

    # Add per-item sell buttons for bag sections
    sell_buttons = []
    BULK_SELL_PROTECTED = {
        "Iron Shard", "Enchanting Scroll",
        "Scroll of Revival", "Holy Water Vial",
        "Common Egg", "Rare Egg", "Dragon Egg", "Mythic Egg", "Pet Snack",
    }
    RARITY_SELL_VALUES = {"common": 20, "uncommon": 60, "rare": 200, "epic": 600, "legendary": 2000}
    if section not in ("Equipped", "Materials", "Consumables"):
        pool_map_sell = {
            "Weapons": WEAPONS, "Armors": ARMORS,
            "Shields": SHIELDS, "Accessories": ACCESSORIES,
        }
        equipped_set = {p.get("equipped_weapon"), p.get("equipped_armor"),
                        p.get("equipped_shield"), p.get("equipped_accessory")}
        pool_sell = pool_map_sell.get(section, {})
        sellable = [
            k for k in inv if k in pool_sell and k not in BULK_SELL_PROTECTED and k not in equipped_set
        ]
        for it in sorted(set(sellable))[:8]:
            price = RARITY_SELL_VALUES.get(pool_sell[it].get("rarity","common"), 20)
            uid_p = p["user_id"]
            sell_buttons.append([InlineKeyboardButton(
                f"💰 Sell {it} ({price}g)",
                callback_data=f"sll_{uid_p}_{it}")])
    if sell_buttons:
        if markup:
            combined = sell_buttons + list(markup.inline_keyboard)
        else:
            combined = sell_buttons
        markup = InlineKeyboardMarkup(combined)
    text = "\n".join(lines)[:4096]
    if edit:
        await target.edit_message_text(text=text, parse_mode="Markdown", reply_markup=markup)
    else:
        try:
            await target.message.delete()
        except Exception:
            pass
        key = (target.effective_chat.id, target.effective_user.id)
        old_id = last_bot_message.get(key)
        try:
            if old_id:
                await target.get_bot().delete_message(chat_id=target.effective_chat.id, message_id=old_id)
        except Exception:
            pass
        new_msg = await target.get_bot().send_message(
            chat_id=target.effective_chat.id, text=text,
            parse_mode="Markdown", reply_markup=markup)
        last_bot_message[key] = new_msg.message_id

async def inventory_callback(update, context):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("inv_s_"): return
    section = query.data[len("inv_s_"):]
    user = update.effective_user
    p = get_player(user.id)
    if not p: return
    await _send_inventory_section(query, p, section, edit=True)

async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    await _send_inventory_section(update, p, section="Equipped", edit=False)

async def equip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        uid = user.id
        inv = sjl(p.get("inventory"), [])
        equip_buttons = []
        for slot_emoji, slot_label, pool in [
            ("⚔️", "Weapon",    WEAPONS),
            ("🛡️", "Armor",     ARMORS),
            ("🔰", "Shield",    SHIELDS),
            ("💍", "Accessory", ACCESSORIES),
        ]:
            slot_items = sorted(set(k for k in inv if k in pool))
            for it in slot_items:
                d_it = pool[it]
                rarity = RARITY_EMOJI.get(d_it.get("rarity",""), "⚪")
                enh = get_enhancement(p, it)
                enh_str = f" +{enh}" if enh else ""
                stat_val = d_it.get("atk") or d_it.get("def", 0)
                stat_key = "ATK" if "atk" in d_it else "DEF"
                equip_buttons.append([InlineKeyboardButton(
                    f"{slot_emoji} [{slot_label}] {rarity}{it}{enh_str} (+{stat_val} {stat_key})",
                    callback_data=f"eqp_{uid}_{it}")])

        weap = p.get("equipped_weapon") or "None"
        armr = p.get("equipped_armor")  or "None"
        shld = p.get("equipped_shield") or "None"
        acc_e = p.get("equipped_accessory") or "None"

        def _gear_summary_line(slot, name, pool):
            if name == "None": return f"{slot}: _None_"
            enh = get_enhancement(p, name)
            encs_g = get_enchant(p, name)
            enh_str = f" *+{enh}*" if enh else ""
            enc_str = f" ✨×{len(encs_g)}" if encs_g else ""
            d_s = pool.get(name, {})
            stat_val = d_s.get("atk") or d_s.get("def", 0)
            stat_label = "ATK" if "atk" in d_s else "DEF"
            rarity = RARITY_EMOJI.get(d_s.get("rarity",""), "")
            return f"{slot}: {rarity} *{name}*{enh_str}{enc_str} (+{stat_val} {stat_label})"

        lines = [f"🎽 *{p['username']}'s Gear:*\n",
                 _gear_summary_line("⚔️ Weapon",  weap, WEAPONS),
                 _gear_summary_line("🛡️ Armor",   armr, ARMORS),
                 _gear_summary_line("🔰 Shield",  shld, SHIELDS)]
        if acc_e != "None":
            acc_data = ACCESSORIES.get(acc_e, {})
            rarity = RARITY_EMOJI.get(acc_data.get("rarity",""), "")
            encs_acc2 = get_enchant(p, acc_e)
            enc_str = f" ✨×{len(encs_acc2)}" if encs_acc2 else ""
            lines.append(f"💍 Accessory: {rarity} *{acc_e}*{enc_str}  -  _{acc_data.get('desc','')}_")
        else:
            lines.append("💍 Accessory: _None_")

        if equip_buttons:
            lines.append("\n_Select an item to equip:_")
            markup = InlineKeyboardMarkup(equip_buttons)
        else:
            lines.append("\n_No equippable items in bag. Visit /shop!_")
            markup = None
        await send_group(update, "\n".join(lines), delay=60, reply_markup=markup); return
    item_typed = " ".join(context.args)
    inv = sjl(p.get("inventory"), [])
    item_name = resolve_item_ci(item_typed, inv)
    if not item_name:
        await send_group(update, f"You don't have *{item_typed}* in your inventory!", delay=9); return

    # Safety check  -  unknown items are never silently deleted
    all_known = set(WEAPONS) | set(ARMORS) | set(SHIELDS) | set(ACCESSORIES)
    if item_name not in all_known:
        await send_group(update,
            f"⚠️ *{item_name}* is a legacy item from before the reskin.\n"
            f"It will be exchanged automatically  -  please wait for the next deploy.",
            delay=15)
        return

    # Determine item type and equip
    if item_name in WEAPONS:
        ok, reason = can_equip_weapon(p, item_name)
        if not ok:
            await send_group(update, f"❌ {reason}", delay=9); return
        old_name = p.get("equipped_weapon")
        old_atk = get_weapon_atk(p)
        p["equipped_weapon"] = item_name
        inv.remove(item_name)
        if old_name: inv.append(old_name)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_atk = get_weapon_atk(p)
        if old_name:
            compare = f"*{old_name}* ({old_atk} ATK) -> *{item_name}* ({new_atk} ATK)"
        else:
            compare = f"ATK: {old_atk} -> {new_atk}"
        await send_group(update,
            f"⚔️ Equipped *{item_name}*!\n{compare}\n"
            + (f"_Unequipped {old_name}_" if old_name else ""), delay=15)
    elif item_name in ARMORS:
        ok, reason = can_equip_armor(p, item_name)
        if not ok:
            await send_group(update, f"❌ {reason}", delay=9); return
        old_name = p.get("equipped_armor")
        old_def = get_armor_def(p)
        p["equipped_armor"] = item_name
        inv.remove(item_name)
        if old_name: inv.append(old_name)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_def = get_armor_def(p)
        if old_name:
            compare = f"*{old_name}* ({old_def} DEF) -> *{item_name}* ({new_def} DEF)"
        else:
            compare = f"DEF: {old_def} -> {new_def}"
        await send_group(update,
            f"🛡️ Equipped *{item_name}*!\n{compare}\n"
            + (f"_Unequipped {old_name}_" if old_name else ""), delay=15)
    elif item_name in SHIELDS:
        s_data = SHIELDS[item_name]
        cls_line = get_class_line(p)
        path = p.get("class_path")
        is_claw = s_data.get("type") == "claw"
        if is_claw:
            if cls_line != "thief" or path != "B":
                await send_group(update,
                    "❌ Only Assassin path (Cutthroat/Assassin/Blade Master/Specialist) can use claws.", delay=9); return
        else:
            if cls_line != "warrior" or path != "A":
                await send_group(update,
                    "❌ Only Warrior Path A (Page/Squire/Knight/Paladin) can use shields.", delay=9); return
        old_name = p.get("equipped_shield")
        old_def = get_armor_def(p)
        p["equipped_shield"] = item_name
        inv.remove(item_name)
        if old_name: inv.append(old_name)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_def = get_armor_def(p)
        if is_claw:
            stat_val = s_data.get("atk", 0)
            await send_group(update,
                f"🗡️ Equipped *{item_name}*! +{stat_val} ATK (claw slot)\n"
                + (f"_Unequipped {old_name}_" if old_name else ""), delay=15)
        else:
            if old_name:
                compare = f"*{old_name}* ({old_def} DEF) -> *{item_name}* ({new_def} DEF)"
            else:
                compare = f"DEF: {old_def} -> {new_def}"
            await send_group(update,
                f"🔰 Equipped *{item_name}*!\n{compare}\n"
                + (f"_Unequipped {old_name}_" if old_name else ""), delay=15)
    elif item_name in ACCESSORIES:
        old = p.get("equipped_accessory")
        p["equipped_accessory"] = item_name
        inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        acc = ACCESSORIES[item_name]
        await send_group(update,
            f"💍 Equipped *{item_name}*\n_{acc['desc']}_\n"
            + (f"_Unequipped {old}_" if old else ""), delay=15)
    else:
        await send_group(update,
            f"*{item_name}* is not equippable. Use /use for consumables.", delay=9)

async def unequip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    uid = user.id
    slots = [("⚔️ Weapon", "equipped_weapon"), ("🛡️ Armor", "equipped_armor"),
             ("🔰 Shield", "equipped_shield"), ("💍 Accessory", "equipped_accessory")]
    buttons = []
    for label, key in slots:
        name = p.get(key)
        if name:
            buttons.append([InlineKeyboardButton(f"{label}: {name}", callback_data=f"uneqp_{uid}_{key}")])
    if not buttons:
        await send_group(update, "🎽 Nothing equipped!", delay=9); return
    markup = InlineKeyboardMarkup(buttons)
    await send_group(update, "🎽 *Unequip — Select a slot:*", delay=30, reply_markup=markup)

async def unequip_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unequip button: uneqp_{uid}_{slot_key}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid      = int(parts[1])
        slot_key = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your gear!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    name = p.get(slot_key)
    if not name:
        await query.answer("Nothing in that slot!", show_alert=True); return
    await query.answer()
    inv = sjl(p.get("inventory"), [])
    inv.append(name)
    p[slot_key] = None
    p["inventory"] = json.dumps(inv)
    save_player(p)
    slot_label = slot_key.replace("equipped_", "").capitalize()
    await query.edit_message_text(
        f"✅ *{name}* unequipped from {slot_label} slot and moved to inventory.",
        parse_mode="Markdown")

async def use_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /use button: useitem_{uid}_{item_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid       = int(parts[1])
        item_name = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your inventory!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await query.answer(f"{item_name} not in your bag!", show_alert=True); return
    inv.remove(item_name); p["inventory"] = json.dumps(inv)
    msg = f"✅ Used *{item_name}*. "
    if item_name in ("Health Potion", "Greater Health Potion", "Grand Restorative Flask"):
        if is_defeated(p):
            inv.append(item_name); p["inventory"] = json.dumps(inv); save_player(p)
            await query.answer("You're defeated — potions won't help!", show_alert=True); return
        hp_gain = {"Health Potion": 50, "Greater Health Potion": 100, "Grand Restorative Flask": 200}.get(item_name, 50)
        p["hp"] = min(calc_max_hp(p), p["hp"] + hp_gain)
        msg += f"❤️ +{hp_gain} HP ({p['hp']}/{calc_max_hp(p)})"
    elif item_name == "Scroll of Revival":
        if not is_defeated(p):
            inv.append(item_name); p["inventory"] = json.dumps(inv); save_player(p)
            await query.answer("You're not defeated — save it for when you need it!", show_alert=True); return
        if is_revival_blocked(p):
            inv.append(item_name); p["inventory"] = json.dumps(inv); save_player(p)
            await query.answer("You've been condemned — can't be revived!", show_alert=True); return
        p["defeated_until"] = None; p["hp"] = p["max_hp"] // 2
        set_status(p, "invincible_until", 3600)
        msg += f"💚 Revived at {p['hp']} HP! 1 hour invincibility granted."
    else:
        msg += "_(No direct effect)_"
    save_player(p)
    await query.answer()
    await query.edit_message_text(msg, parse_mode="Markdown")

async def settitle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle title equip button: settitle_{uid}_{title_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid   = int(parts[1])
        title = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your titles!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if title not in safe_titles(p):
        await query.answer("You haven't earned that title!", show_alert=True); return
    await query.answer(f"Title set to: {title}!")
    p["active_title"] = title; save_player(p)
    await query.edit_message_text(f"🏅 Title set to *{title}*!", parse_mode="Markdown")

async def equip_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle equip button: eqp_{uid}_{item_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid       = int(parts[1])
        item_name = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your equip menu!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await query.answer(f"{item_name} not in your inventory!", show_alert=True); return
    if item_name in WEAPONS:
        ok, reason = can_equip_weapon(p, item_name)
        if not ok:
            await query.answer(reason, show_alert=True); return
        old = p.get("equipped_weapon")
        p["equipped_weapon"] = item_name; inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_atk = get_weapon_atk(p)
        await query.edit_message_text(
            f"⚔️ *Equipped {item_name}!*\n"
            f"Weapon ATK is now *{new_atk}*" + (f"\n_Unequipped {old}_" if old else ""),
            parse_mode="Markdown")
    elif item_name in ARMORS:
        ok, reason = can_equip_armor(p, item_name)
        if not ok:
            await query.answer(reason, show_alert=True); return
        old = p.get("equipped_armor")
        p["equipped_armor"] = item_name; inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_def = get_armor_def(p)
        await query.edit_message_text(
            f"🛡️ *Equipped {item_name}!*\n"
            f"Armor DEF is now *{new_def}*" + (f"\n_Unequipped {old}_" if old else ""),
            parse_mode="Markdown")
    elif item_name in SHIELDS:
        cls_line = get_class_line(p); path = p.get("class_path")
        if cls_line != "warrior" or path != "A":
            await query.answer("Only Warrior Path A can use shields!", show_alert=True); return
        old = p.get("equipped_shield")
        p["equipped_shield"] = item_name; inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        new_def = get_armor_def(p)
        await query.edit_message_text(
            f"🔰 *Equipped {item_name}!*\n"
            f"Shield DEF is now *{new_def}*" + (f"\n_Unequipped {old}_" if old else ""),
            parse_mode="Markdown")
    elif item_name in ACCESSORIES:
        old = p.get("equipped_accessory")
        p["equipped_accessory"] = item_name; inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        acc = ACCESSORIES[item_name]
        await query.edit_message_text(
            f"💍 *Equipped {item_name}!*\n_{acc['desc']}_" + (f"\n_Unequipped {old}_" if old else ""),
            parse_mode="Markdown")
    else:
        await query.answer(f"{item_name} is not equippable!", show_alert=True)

async def use_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        inv = sjl(p.get("inventory"), [])
        consumables_in_bag = [(k, inv.count(k)) for k in dict.fromkeys(inv) if k in CONSUMABLES]
        if not consumables_in_bag:
            await send_group(update, "🧪 *Use Item*\n\nNo consumables in your bag.", delay=12); return
        uid = user.id
        buttons = []
        for item, count in consumables_in_bag:
            d_c = CONSUMABLES[item]
            buttons.append([InlineKeyboardButton(
                f"🧪 {item} x{count}  —  {d_c.get('desc','')[:40]}",
                callback_data=f"useitem_{uid}_{item}")])
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update, "🧪 *Use Item — Select a consumable:*", delay=30, reply_markup=markup)
        return
    item_typed = " ".join(context.args)
    inv  = sjl(p.get("inventory"), [])
    item = resolve_item_ci(item_typed, inv)
    if not item:
        await send_group(update, f"You don't have *{item_typed}*!", delay=9); return

    # Safety check  -  never silently delete unknown items
    all_known_consumables = set(CONSUMABLES)
    all_known_gear = set(WEAPONS) | set(ARMORS) | set(SHIELDS) | set(ACCESSORIES)
    if item not in all_known_consumables and item not in all_known_gear:
        inv.append(item)
        p["inventory"] = json.dumps(inv)
        save_player(p)
        await send_group(update,
            f"⚠️ *{item}* is a legacy item from before the reskin.\n"
            f"It will be exchanged automatically  -  please wait for the next deploy.",
            delay=15)
        return

    inv.remove(item); p["inventory"] = json.dumps(inv)
    msg = f"✅ Used *{item}*. "
    if item == "Health Potion":
        if is_defeated(p):
            inv.append(item); p["inventory"] = json.dumps(inv)
            save_player(p)
            await send_group(update,
                "❌ You're defeated  -  potions won't help.\n"
                "Use a *Scroll of Revival* to revive yourself, or wait for a Priest.", delay=9)
            return
        p["hp"] = min(calc_max_hp(p), p["hp"]+50);   msg += f"❤️ +50 HP ({p['hp']}/{calc_max_hp(p)})"
    elif item == "Greater Health Potion":
        if is_defeated(p):
            inv.append(item); p["inventory"] = json.dumps(inv)
            save_player(p)
            await send_group(update,
                "❌ You're defeated  -  potions won't help.\n"
                "Use a *Scroll of Revival* to revive yourself, or wait for a Priest.", delay=9)
            return
        p["hp"] = min(calc_max_hp(p), p["hp"]+100);  msg += f"❤️ +100 HP ({p['hp']}/{calc_max_hp(p)})"
    elif item == "Grand Restorative Flask":
        if is_defeated(p):
            inv.append(item); p["inventory"] = json.dumps(inv)
            save_player(p)
            await send_group(update,
                "❌ You're defeated  -  potions won't help.\n"
                "Use a *Scroll of Revival* to revive yourself, or wait for a Priest.", delay=9)
            return
        p["hp"] = min(calc_max_hp(p), p["hp"]+200);  msg += f"❤️ +200 HP ({p['hp']}/{calc_max_hp(p)})"
    elif item == "Scroll of Revival":
        if not is_defeated(p):
            inv.append(item); p["inventory"] = json.dumps(inv)
            save_player(p)
            await send_group(update,
                "You're not defeated  -  save your Scroll of Revival for when you need it!", delay=9)
            return
        if is_revival_blocked(p):
            inv.append(item); p["inventory"] = json.dumps(inv)
            save_player(p)
            await send_group(update,
                "☠️ You have been condemned by Verdict  -  you cannot be revived!\n"
                "Only a *Cleric's Absolution* can lift this curse.", delay=9)
            return
        p["defeated_until"] = None
        p["hp"] = p["max_hp"] // 2
        set_status(p, "invincible_until", 3600)
        msg += f"💚 Revived at {p['hp']} HP! 1 hour invincibility granted."
    else:
        msg += "_(No direct effect  -  used as crafting material or quest item)_"
    save_player(p)
    await send_group(update, msg, delay=15)

async def sell_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sell button from inventory: sll_{uid}_{item_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid       = int(parts[1])
        item_name = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your inventory!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await query.answer(f"{item_name} not in inventory!", show_alert=True); return
    RARITY_SELL_VALUES = {"common": 20, "uncommon": 60, "rare": 200, "epic": 600, "legendary": 2000}
    price = 0
    for pool_c in [WEAPONS, ARMORS, SHIELDS, ACCESSORIES]:
        if item_name in pool_c:
            price = RARITY_SELL_VALUES.get(pool_c[item_name].get("rarity","common"), 20)
            break
    if price == 0:
        await query.answer(f"{item_name} cannot be sold for gold.", show_alert=True); return
    await query.answer(f"Sold {item_name} for {price}g!")
    inv.remove(item_name)
    p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold", 0) + price
    save_player(p)
    await query.edit_message_text(
        f"💰 *Sold {item_name}* for *{price}g*!\nBalance: *{p['gold']}g*",
        parse_mode="Markdown")

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        uid = user.id
        inv = sjl(p.get("inventory"), [])
        if not inv:
            await send_group(update, "Your inventory is empty.", delay=9); return
        buttons = [
            [InlineKeyboardButton("Sell All Common",    callback_data=f"sellr_{uid}_common"),
             InlineKeyboardButton("Sell All Uncommon",  callback_data=f"sellr_{uid}_uncommon")],
            [InlineKeyboardButton("Sell All Rare",      callback_data=f"sellr_{uid}_rare"),
             InlineKeyboardButton("Sell All Epic",      callback_data=f"sellr_{uid}_epic")],
            [InlineKeyboardButton("💰 Sell Everything (non-key)", callback_data=f"sellr_{uid}_all")],
        ]
        await send_group(update,
            "💰 *Sell Items*\n\nPick a rarity to bulk-sell. Key materials and equipped gear are always protected.",
            reply_markup=InlineKeyboardMarkup(buttons), delay=30)
        return

    BULK_SELL_PROTECTED = {
        "Iron Shard", "Enchanting Scroll",
        "Scroll of Revival", "Holy Water Vial",
        "Common Egg", "Rare Egg", "Dragon Egg", "Mythic Egg", "Pet Snack",
    }

    if context.args[0].lower() == "all":
        inv = sjl(p.get("inventory"), [])
        if not inv:
            await send_group(update, "Your inventory is empty.", delay=9); return
        rarity_filter = None
        if len(context.args) > 1:
            rf = context.args[1].lower()
            if rf in ("common","uncommon","rare","epic","legendary"):
                rarity_filter = rf
        sold_items = []; total_gold = 0; remaining_inv = []
        equipped = [p.get("equipped_weapon"), p.get("equipped_armor"),
                    p.get("equipped_shield"), p.get("equipped_accessory")]
        for item_s in inv:
            if item_s in BULK_SELL_PROTECTED:
                remaining_inv.append(item_s)
                continue
            item_rarity = None; item_price = 0
            for pool_s in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS]:
                if item_s in pool_s:
                    item_rarity = pool_s[item_s].get("rarity","common")
                    rarity_prices = {"common":20,"uncommon":60,"rare":200,"epic":600,"legendary":2000}
                    item_price = rarity_prices.get(item_rarity, 20)
                    break
            if item_price == 0:
                for pool_c in [CONSUMABLES]:
                    if item_s in pool_c:
                        item_rarity = "consumable"
                        item_price = pool_c[item_s].get("sell", 10)
                        break
            should_sell = False
            if rarity_filter:
                if rarity_filter == item_rarity: should_sell = True
            else:
                if item_s not in equipped: should_sell = True
            if should_sell and item_price > 0:
                sold_items.append(item_s); total_gold += item_price
            else:
                remaining_inv.append(item_s)
        if not sold_items:
            await send_group(update,
                f"Nothing to sell{' of that rarity' if rarity_filter else ''}.", delay=9); return
        p["inventory"] = json.dumps(remaining_inv)
        p["gold"] = p.get("gold", 0) + total_gold
        save_player(p)
        from collections import Counter as _Counter
        sold_summary = _Counter(sold_items)
        summary_str = ", ".join(f"{k} x{v}" for k, v in sold_summary.items())
        await send_group(update,
            f"💰 *Bulk Sold!*\n_{summary_str}_\n\nEarned *{total_gold}g* | Balance: {p['gold']}g",
            delay=20); return

    SELL_RARITIES = {"common", "uncommon", "rare", "epic", "legendary"}
    if context.args and context.args[0].lower() in SELL_RARITIES:
        target_rarity = context.args[0].lower()
        inv = sjl(p.get("inventory"), [])
        sold_items = []; gold_earned = 0
        remaining = []
        equipped_slots = {p.get("equipped_weapon"), p.get("equipped_armor"),
                          p.get("equipped_shield"), p.get("equipped_accessory")}
        RARITY_SELL_VALUES = {"common":20,"uncommon":60,"rare":200,"epic":600,"legendary":2000}
        for item_r_entry in inv:
            if item_r_entry in BULK_SELL_PROTECTED or item_r_entry in equipped_slots:
                remaining.append(item_r_entry); continue
            item_r = ""; item_val = 0
            for pool_r in [WEAPONS, ARMORS, SHIELDS, ACCESSORIES, CONSUMABLES]:
                if item_r_entry in pool_r:
                    item_r = pool_r[item_r_entry].get("rarity","common")
                    item_val = RARITY_SELL_VALUES.get(item_r, 5)
                    break
            if item_r == target_rarity:
                sold_items.append(item_r_entry)
                gold_earned += item_val
            else:
                remaining.append(item_r_entry)
        if not sold_items:
            await send_group(update, f"No {target_rarity} items to sell.", delay=9); return
        p["inventory"] = json.dumps(remaining)
        p["gold"] = p.get("gold", 0) + gold_earned
        save_player(p)
        await send_group(update,
            f"💰 Sold {len(sold_items)} *{target_rarity}* item(s) for *{gold_earned} gold*.\n"
            f"Items: {', '.join(sold_items[:10])}{'...' if len(sold_items)>10 else ''}", delay=15); return

    # Single-item sell
    # Strip trailing "confirm" from args to get item name
    args_list = list(context.args)
    confirmed = len(args_list) > 1 and args_list[-1].lower() == "confirm"
    if confirmed:
        args_list = args_list[:-1]
    item_typed = " ".join(args_list)
    inv  = sjl(p.get("inventory"), [])
    item_name = resolve_item_ci(item_typed, inv)
    if not item_name:
        await send_group(update, f"You don't have *{item_typed}*!", delay=9); return

    # Check if item is equipped
    equipped_slots = {p.get("equipped_weapon"), p.get("equipped_armor"),
                      p.get("equipped_shield"), p.get("equipped_accessory")}
    if item_name in equipped_slots and not confirmed:
        await send_group(update,
            f"⚠️ *{item_name}* is currently equipped!\n"
            f"Use /equip to swap it out first, or `/sell {item_name} confirm` to sell anyway.", delay=12); return

    # Warn on rare+
    item_rarity = ""
    for pool_check in [WEAPONS, ARMORS, SHIELDS, ACCESSORIES]:
        if item_name in pool_check:
            item_rarity = pool_check[item_name].get("rarity","")
            break
    if item_rarity in ("rare","epic","legendary") and not confirmed:
        rarity_emoji = RARITY_EMOJI.get(item_rarity, "")
        await send_group(update,
            f"⚠️ {rarity_emoji} *{item_name}* is a *{item_rarity.capitalize()}* item!\n"
            f"Type `/sell {item_name} confirm` to sell it.", delay=12); return

    # Determine sell price
    price = 0
    for pool in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS]:
        if item_name in pool:
            d = pool[item_name]
            rarity_prices = {"common":20,"uncommon":60,"rare":200,"epic":600,"legendary":2000}
            price = rarity_prices.get(d.get("rarity","common"),20)
            break
    for pool2 in [CONSUMABLES]:
        if item_name in pool2:
            price = pool2[item_name].get("sell",10); break
    if price == 0: price = 10
    inv.remove(item_name); p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold",0) + price
    save_player(p)
    await send_group(update,
        f"💰 Sold *{item_name}* for *{price} gold*!\nTotal: {p['gold']}g", delay=15)


async def sell_rarity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk-sell by rarity button."""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try: uid = int(parts[1]); rarity_filter = parts[2]
    except (IndexError, ValueError): await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your sell menu!", show_alert=True); return
    p = get_player(uid)
    if not p: await query.answer("Player not found.", show_alert=True); return

    BULK_SELL_PROTECTED = {
        "Iron Shard","Enchanting Scroll",
        "Scroll of Revival","Holy Water Vial",
        "Common Egg","Rare Egg","Dragon Egg","Mythic Egg","Pet Snack",
    }
    rarity_prices = {"common":20,"uncommon":60,"rare":200,"epic":600,"legendary":2000}
    inv = sjl(p.get("inventory"), [])
    equipped = {p.get("equipped_weapon"), p.get("equipped_armor"),
                p.get("equipped_shield"), p.get("equipped_accessory")}
    sold_items = []; total_gold = 0; remaining_inv = []
    for item_s in inv:
        if item_s in BULK_SELL_PROTECTED or item_s in equipped:
            remaining_inv.append(item_s); continue
        item_rarity = None; item_price = 0
        for pool_s in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS]:
            if item_s in pool_s:
                item_rarity = pool_s[item_s].get("rarity","common")
                item_price = rarity_prices.get(item_rarity, 20); break
        if item_price == 0:
            if item_s in CONSUMABLES:
                item_rarity = "consumable"
                item_price = CONSUMABLES[item_s].get("sell", 10)
        should_sell = (rarity_filter == "all") or (item_rarity == rarity_filter)
        if should_sell and item_price > 0:
            sold_items.append(item_s); total_gold += item_price
        else:
            remaining_inv.append(item_s)
    if not sold_items:
        await query.answer(f"Nothing to sell of that rarity.", show_alert=True); return
    p["inventory"] = json.dumps(remaining_inv)
    p["gold"] = p.get("gold", 0) + total_gold
    save_player(p)
    label = rarity_filter.capitalize() if rarity_filter != "all" else "Everything"
    await query.answer(f"Sold {len(sold_items)} items for {total_gold}g!")
    await query.edit_message_text(
        f"💰 *Sold {len(sold_items)} {label} item{'s' if len(sold_items)!=1 else ''}*\n"
        f"+*{total_gold:,}g* | Balance: *{p['gold']:,}g*",
        parse_mode="Markdown")


# ── BOSS ──────────────────────────────────────────────────────────────────────
async def boss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, _defeated_msg(p), delay=15); return
    chat_id = update.effective_chat.id
    if chat_id in active_bosses:
        boss = active_bosses[chat_id]
        if user.id not in [u["id"] for u in boss["participants"]]:
            boss["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        await send_group(update,
            f"⚔️ *{user.first_name}* joins *{boss['data']['name']}*!\n"
            f"❤️ {boss['hp']}/{boss['data']['max_hp']} HP | Use /strike!", delay=15); return
    if not context.args:
        lines = ["⚔️ *Choose a Boss to Summon:*\n"]
        buttons = []
        for k, v in BOSSES.items():
            if v.get("secret"): continue
            lines.append(f"🎱 *{v['name']}*  ❤️ {v['max_hp']} HP | +{v['exp']:,} EXP | +{v['gold']}g")
            buttons.append([InlineKeyboardButton(
                f"⚔️ {v['name']}  ({v['max_hp']} HP)",
                callback_data=f"bossstart_{user.id}_{k}")])
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update, "\n".join(lines), delay=60, reply_markup=markup); return
    key = " ".join(context.args).lower(); bd = BOSSES.get(key)
    if not bd or bd.get("secret"):
        await send_group(update, "Unknown boss. Try `/boss` to see the list.", delay=9); return
    active_bosses[chat_id] = {"data":bd.copy(),"hp":bd["max_hp"],
                               "participants":[{"id":user.id,"name":user.first_name,"dmg":0}]}
    boss_spawn_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"boss_act_{user.id}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"boss_act_{user.id}_skl"),
    ]])
    await send_group(update,
        f"🎱 *{bd['name']} HAS APPEARED!*\n\n_{bd['desc']}_\n\n"
        f"❤️ HP: {bd['max_hp']} | 💀 {bd['dmg_min']}–{bd['dmg_max']} dmg\n\n"
        f"*{user.first_name}* engaged!\nOthers: `/boss {key}` | All: /strike",
        permanent=False, delay=300, reply_markup=boss_spawn_markup)

async def boss_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle boss selection button from /boss menu."""
    query = update.callback_query
    await query.answer()
    # format: bossstart_{uid}_{boss_key}  (boss key may contain spaces)
    parts = query.data.split("_", 2)
    try:
        uid = int(parts[1])
        key = parts[2]
    except (IndexError, ValueError):
        return
    if query.from_user.id != uid:
        await query.answer("Use /boss to summon your own!", show_alert=True); return

    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if is_defeated(p):
        await query.answer("You're defeated — can't summon!", show_alert=True); return

    chat_id = query.message.chat_id
    if chat_id in active_bosses:
        await query.answer("A boss is already active here!", show_alert=True); return

    bd = BOSSES.get(key)
    if not bd or bd.get("secret"):
        await query.answer("Unknown boss.", show_alert=True); return

    active_bosses[chat_id] = {
        "data": bd.copy(), "hp": bd["max_hp"],
        "participants": [{"id": uid, "name": query.from_user.first_name, "dmg": 0}]
    }
    boss_spawn_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"boss_act_{uid}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"boss_act_{uid}_skl"),
    ]])
    try:
        await query.edit_message_text(
            f"🎱 *{bd['name']} HAS APPEARED!*\n\n_{bd['desc']}_\n\n"
            f"❤️ HP: {bd['max_hp']} | 💀 {bd['dmg_min']}–{bd['dmg_max']} dmg\n\n"
            f"*{query.from_user.first_name}* engaged! Use /strike to attack.",
            parse_mode="Markdown", reply_markup=boss_spawn_markup)
    except Exception:
        pass

async def _attack_boss(update, context, p, boss_dict, chat_id):
    """Handle /attack routing to boss fight."""
    user = update.effective_user
    is_secret = chat_id in secret_boss_active

    if is_defeated(p):
        await send_group(update, _defeated_msg(p), delay=15); return
    if cannot_attack(p):
        await send_group(update, "⚡ Stunned or rooted  -  can't act!", delay=9); return

    # Auto-join and init raid HP if not in participants
    if user.id not in [u["id"] for u in boss_dict["participants"]]:
        boss_dict["participants"].append({"id": user.id, "name": user.first_name, "dmg": 0})
        if "player_hp" not in boss_dict:
            boss_dict["player_hp"] = {}
            boss_dict["player_max_hp"] = {}
        mhp = calc_max_hp(p)
        boss_dict["player_hp"][user.id] = mhp
        boss_dict["player_max_hp"][user.id] = mhp
    elif "player_hp" not in boss_dict:
        # Init for existing participants (first attack after boss spawned)
        boss_dict["player_hp"] = {}
        boss_dict["player_max_hp"] = {}
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if pp:
                mhp = calc_max_hp(pp)
                boss_dict["player_hp"][u["id"]] = mhp
                boss_dict["player_max_hp"][u["id"]] = mhp
    participant = next(u for u in boss_dict["participants"] if u["id"] == user.id)

    w = get_weather()
    dmg = calc_attack_damage(p, w)
    if check_crit(p): dmg = apply_crit(p, dmg)
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0; dmg = get_stat(p, "AGI") * 4

    boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
    participant["dmg"] += dmg
    for _d, _e, _g in track_objective(p, "boss_attempt"):
        p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
    save_player(p)

    lines = [
        f"⚔️ *{user.first_name}* strikes *{boss_dict['data']['name']}* for *{dmg}!*",
        f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}"
    ]

    # Boss counter-attack (90% chance)
    alive = [u for u in boss_dict["participants"]
             if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp",{}).get(u["id"],1) > 0]
    if alive and boss_dict["hp"] > 0 and random.random() < 0.90:
        # Boss can hit 1 or 2 players (30% chance for 2)
        hit_count = 2 if random.random() < 0.30 else 1
        targets = random.sample(alive, min(hit_count, len(alive)))
        for target in targets:
            tp = get_player(target["id"])
            if tp and not is_defeated(tp):
                raw = random.randint(boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"])
                edm = calc_defense(tp, raw)
                boss_dict["player_hp"][target["id"]] = max(0,
                    boss_dict["player_hp"].get(target["id"], calc_max_hp(tp)) - edm)
                php  = boss_dict["player_hp"][target["id"]]
                pmhp = boss_dict["player_max_hp"].get(target["id"], calc_max_hp(tp))
                if php == 0:
                    exp_loss = apply_pvp_death(tp, killer_name=boss_dict['data']['name'], cause="Boss")
                    asyncio.create_task(_notify_defeat(context.bot, tp, boss_dict['data']['name'] + " (Boss)"))
                    save_player(tp)
                    lines.append(f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! 6hr defeat. -{exp_loss} EXP.")
                else:
                    lines.append(f"💥 *{boss_dict['data']['name']}* hits *{target['name']}* for *{edm}!* ({php}/{pmhp} boss HP)")
                save_player(tp)

    # All dead check
    alive_after = [u for u in boss_dict["participants"]
                   if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp",{}).get(u["id"],1) > 0]
    if not alive_after and boss_dict["hp"] > 0:
        if is_secret: secret_boss_active.pop(chat_id, None)
        else: active_bosses.pop(chat_id, None)
        lines.append("💀 *ALL PLAYERS DEFEATED!* The boss wins...")
        save_player(p); await send_group(update, "\n".join(lines), delay=30); return

    if boss_dict["hp"] <= 0:
        data = boss_dict["data"]
        if is_secret: secret_boss_active.pop(chat_id, None)
        else: active_bosses.pop(chat_id, None)
        lines.append(f"\n🏆 *{data['name']} DEFEATED!*\n")
        w2 = get_weather()
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if not pp: continue
            pp["gold"] = pp.get("gold", 0) + data["gold"]
            loot = roll_loot_table(data.get("loot_table", []))
            if loot:
                add_item(pp, loot); r = ""
                for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                lines.append(f"🎒 *{pp['username']}* found: {r} *{loot}*!")
            if award_title(pp, data["title"]):
                lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
            add_exp(pp, data["exp"], w2); save_player(pp)
            lines.append(f"✅ *{pp['username']}*  -  +{data['exp']} EXP | +{data['gold']} Gold")

    save_player(p)
    await send_group(update, "\n".join(lines), delay=30)

async def strike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, _defeated_msg(p), delay=15); return

    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    is_secret = chat_id in secret_boss_active
    if not boss_dict:
        await send_group(update, "No active boss! Use /boss.", delay=9); return

    # Auto-join
    if user.id not in [u["id"] for u in boss_dict["participants"]]:
        boss_dict["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
    participant = next(u for u in boss_dict["participants"] if u["id"]==user.id)

    w   = get_weather()
    dmg = calc_attack_damage(p, w)
    boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
    participant["dmg"] += dmg

    lines = [f"⚔️ *{user.first_name}* strikes *{boss_dict['data']['name']}* for *{dmg}!*\n"
             f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}"]

    alive = [u for u in boss_dict["participants"]
             if not is_defeated(get_player(u["id"]))]
    if alive and boss_dict["hp"] > 0 and random.random() < 0.90:
        target = random.choice(alive)
        tp = get_player(target["id"])
        if tp and not is_defeated(tp):
            raw = random.randint(
                boss_dict["data"]["dmg_min"],
                boss_dict["data"]["dmg_max"])
            edm = calc_defense(tp, raw)
            tp["hp"] = max(0, tp["hp"] - edm)
            if tp["hp"] == 0:
                exp_loss = apply_pvp_death(tp, killer_name=boss_dict['data']['name'], cause="Boss")
                asyncio.create_task(_notify_defeat(context.bot, tp, boss_dict['data']['name'] + " (Boss)"))
                lines.append(
                    f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! "
                    f"6hr defeat. -{exp_loss} EXP.")
            else:
                lines.append(
                    f"💥 *{boss_dict['data']['name']}* hits *{target['name']}* "
                    f"for *{edm} damage!* ({tp['hp']}/{tp.get('max_hp', calc_max_hp(tp))} HP)")
            save_player(tp)

    # Check if all players dead  -  end fight
    alive_after = [u for u in boss_dict["participants"]
                   if not is_defeated(get_player(u["id"]))]
    if not alive_after and boss_dict["hp"] > 0:
        if is_secret: secret_boss_active.pop(chat_id, None)
        else:         active_bosses.pop(chat_id, None)
        lines.append(f"\n💀 *ALL PLAYERS DEFEATED!* The boss wins this time...")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=30); return

    if boss_dict["hp"] <= 0:
        data = boss_dict["data"]
        if is_secret: secret_boss_active.pop(chat_id, None)
        else:         active_bosses.pop(chat_id, None)
        lines.append(f"\n🏆 *{data['name']} DEFEATED!*\n")
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if not pp: continue
            pp["gold"] = pp.get("gold",0) + data["gold"]
            loot = roll_loot_table(data.get("loot_table",[]))
            if loot:
                add_item(pp, loot)
                r = ""
                for pool in [WEAPONS,ARMORS,ACCESSORIES]: 
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                lines.append(f"🎒 *{pp['username']}* found: {r} *{loot}*!")
            if award_title(pp, data["title"]):
                lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
            lmsgs, leveled = add_exp(pp, data["exp"], w)
            save_player(pp)
            lines.append(f"✅ *{pp['username']}*  -  +{data['exp']} EXP | +{data['gold']} Gold")
            if leveled and pp["level"] % 10 == 0:
                asyncio.create_task(announce(update.get_bot(), chat_id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}* defeating "
                    f"{data['name']}! 🏆", permanent=True))

    save_player(p)
    await send_group(update, "\n".join(lines), delay=30)

# ── GUILD ─────────────────────────────────────────────────────────────────────
async def guild_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = get_player(update.effective_user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    await send_group(update,
        "🏰 *Hall Commands*\n\n"
        "/guildcreate [name]  -  Found a hall (100g)\n"
        "/guildjoin  -  Browse and join available halls\n"
        "/guildinfo  -  Your hall info and perks\n"
        "/guildlist  -  Top guilds leaderboard\n"
        "/guilddonate [amount]  -  Donate gold to guild bank\n"
        "/guildkick @user  -  Kick a member (leader only)\n"
        "/guildleave  -  Leave your current guild\n"
        "/guilddisband  -  Disband your guild (leader only)",
        delay=15)


async def guildcreate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        await send_group(update, "Usage: /guildcreate [name]", delay=9); return
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        await send_group(update, "You're already in a guild!", delay=9); return
    if p.get("gold",0) < 100:
        await send_group(update, "Need 100 gold to found a hall!", delay=9); return
    name = " ".join(context.args)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("INSERT INTO guilds (name,leader_id,members,level,exp,bank) VALUES(?,?,?,1,0,0)",
                  (name, user.id, json.dumps([user.id])))
        conn.commit(); gid = c.lastrowid
    except sqlite3.IntegrityError:
        await send_group(update, f"Guild '{name}' already exists!", delay=9)
        conn.close(); return
    conn.close()
    p["guild_id"] = gid; p["gold"] = p.get("gold",0) - 100
    award_title(p, "Guild Founder"); save_player(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"🏰 *{name}* guild founded by *{user.first_name}*!"))
    await send_group(update, f"🏰 *{name}* founded!\n🏅 Title: *Guild Founder*!", delay=15)


async def guildjoin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    p = get_player(user.id)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        await query.answer("You're already in a guild!", show_alert=True); return
    gid = int(query.data.split("_")[-1])
    g = get_guild(gid)
    if not g:
        await query.answer("Guild no longer exists.", show_alert=True); return
    members = sjl(g["members"], [])
    if user.id in members:
        await query.answer("You're already in this guild.", show_alert=True); return
    members.append(user.id)
    g["members"] = json.dumps(members); save_guild(g)
    p["guild_id"] = gid; save_player(p)
    asyncio.create_task(announce(context.bot, query.message.chat.id,
        f"🏰 *{user.first_name}* joined *{g['name']}*!"))
    await query.edit_message_text(f"✅ You joined *{g['name']}*!", parse_mode="Markdown")


async def guildjoin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        await send_group(update, "You're already in a guild! Use /guildleave first.", delay=9); return
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT guild_id,name,level,members FROM guilds ORDER BY level DESC LIMIT 10")
    rows = c.fetchall(); conn.close()
    if not rows:
        await send_group(update, "No halls exist yet  -  use /guildcreate to found one!", delay=9); return
    medals = ["🥇","🥈","🥉"] + ["🏰"]*7
    lines = ["🏰 *Available Halls  -  tap to join:*\n"]
    buttons = []
    for i, row in enumerate(rows):
        mcount = len(sjl(row["members"], []))
        lines.append(f"{medals[i]} *{row['name']}*  -  Lv {safe_int(row['level'],1)} | {mcount} members")
        buttons.append([InlineKeyboardButton(
            f"Join {row['name']}", callback_data=f"guildjoin_{row['guild_id']}")])
    markup = InlineKeyboardMarkup(buttons)
    await send_group(update, "\n".join(lines), reply_markup=markup, delay=20)


def _build_guildinfo_overview(g):
    """Return (text, markup) for a guild overview card."""
    member_ids = sjl(g.get("members", "[]"), [])
    leader     = get_player(g["leader_id"])
    glvl       = safe_int(g.get("level"), 1)
    perk       = GUILD_PERKS.get(glvl, {})
    nxt        = guild_exp_for_level(glvl) if glvl < 10 else "MAX"
    wins       = safe_int(g.get("war_wins", 0))
    gid        = g["guild_id"]
    text = (
        f"🏰 *{g['name']}*\n"
        f"👑 Leader: {leader['username'] if leader else '?'}\n"
        f"⭐ Level: {glvl}/10  |  EXP: {safe_int(g.get('exp'))}/{nxt}\n"
        f"🏆 War Wins: {wins}\n"
        f"💰 Bank: {safe_int(g.get('bank'))}g\n"
        f"🎁 Perks: _{perk.get('desc', 'None')}_"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"👥 Members ({len(member_ids)})", callback_data=f"ginfoM_{gid}")],
        [InlineKeyboardButton("🔙 All Halls", callback_data="ginfoList")],
    ])
    return text, markup


async def guildinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    # /guildinfo [Hall Name] — direct typed lookup
    if context.args:
        target_name = " ".join(context.args)
        g = get_guild_by_name(target_name)
        if not g:
            await send_group(update, f"Guild *{target_name}* not found.", delay=9); return
        text, markup = _build_guildinfo_overview(g)
        await send_group(update, text, reply_markup=markup, delay=25)
        return

    # No args — show all halls as a button list
    conn_gi = sqlite3.connect(DB_PATH); conn_gi.row_factory = sqlite3.Row; c_gi = conn_gi.cursor()
    c_gi.execute("SELECT guild_id, name, level, members, war_wins FROM guilds ORDER BY level DESC, war_wins DESC LIMIT 15")
    rows = [dict(r) for r in c_gi.fetchall()]; conn_gi.close()

    if not rows:
        await send_group(update, "No halls exist yet. Use /guildcreate to found one!", delay=9); return

    my_gid = str(p.get("guild_id", ""))
    lines  = ["🏰 *Halls  —  tap to inspect:*\n"]
    buttons = []
    medals  = ["🥇", "🥈", "🥉"] + ["🏰"] * 12
    for i, row in enumerate(rows):
        mcount = len(sjl(row["members"], []))
        star   = " ⭐" if str(row["guild_id"]) == my_gid else ""
        lines.append(f"{medals[i]} *{row['name']}*  Lv {safe_int(row['level'], 1)} | {mcount} members | {safe_int(row['war_wins'])}W{star}")
        buttons.append([InlineKeyboardButton(
            f"🏰 {row['name']}", callback_data=f"ginfo_{row['guild_id']}")])

    await send_group(update, "\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), delay=30)


async def guildinfo_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show guild overview card when a hall is selected."""
    query = update.callback_query
    try:
        gid = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        await query.answer(); return
    g = get_guild(gid)
    if not g:
        await query.answer("Guild no longer exists.", show_alert=True); return
    text, markup = _build_guildinfo_overview(g)
    await query.answer()
    await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")


async def guildinfo_members_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show member list for a guild."""
    query = update.callback_query
    try:
        gid = int(query.data.split("_", 1)[1])
    except (IndexError, ValueError):
        await query.answer(); return
    g = get_guild(gid)
    if not g:
        await query.answer("Guild no longer exists.", show_alert=True); return

    member_ids = sjl(g.get("members", "[]"), [])
    member_rows = []
    if member_ids:
        conn_m = sqlite3.connect(DB_PATH); conn_m.row_factory = sqlite3.Row; c_m = conn_m.cursor()
        placeholders = ",".join("?" * len(member_ids))
        c_m.execute(
            f"SELECT username, level, class_id FROM players WHERE user_id IN ({placeholders})"
            f" ORDER BY level DESC", member_ids)
        member_rows = [dict(r) for r in c_m.fetchall()]
        conn_m.close()

    lines = [f"👥 *{g['name']} — Members ({len(member_ids)})*\n"]
    for r in member_rows:
        cls = CLASS_TREE.get(r["class_id"] or "", {}).get("name", "No Class")
        lines.append(f"• *{r['username']}* — Lv {r['level']} {cls}")
    if not member_rows:
        lines.append("(no registered members)")

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Hall", callback_data=f"ginfo_{gid}")],
    ])
    await query.answer()
    await query.edit_message_text("\n".join(lines), reply_markup=markup, parse_mode="Markdown")


async def guildinfo_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to the full hall list."""
    query = update.callback_query
    conn_gl = sqlite3.connect(DB_PATH); conn_gl.row_factory = sqlite3.Row; c_gl = conn_gl.cursor()
    c_gl.execute("SELECT guild_id, name, level, members, war_wins FROM guilds ORDER BY level DESC, war_wins DESC LIMIT 15")
    rows = [dict(r) for r in c_gl.fetchall()]; conn_gl.close()

    p = get_player(query.from_user.id)
    my_gid = str(p.get("guild_id", "")) if p else ""
    lines   = ["🏰 *Halls  —  tap to inspect:*\n"]
    buttons = []
    medals  = ["🥇", "🥈", "🥉"] + ["🏰"] * 12
    for i, row in enumerate(rows):
        mcount = len(sjl(row["members"], []))
        star   = " ⭐" if str(row["guild_id"]) == my_gid else ""
        lines.append(f"{medals[i]} *{row['name']}*  Lv {safe_int(row['level'], 1)} | {mcount} members | {safe_int(row['war_wins'])}W{star}")
        buttons.append([InlineKeyboardButton(
            f"🏰 {row['name']}", callback_data=f"ginfo_{row['guild_id']}")])

    await query.answer()
    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")


async def guildlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT name,level,members FROM guilds ORDER BY level DESC LIMIT 10")
    rows = c.fetchall(); conn.close()
    if not rows:
        await send_group(update, "No halls yet!", delay=9); return
    medals = ["🥇","🥈","🥉"] + ["🏰"]*7
    lines = ["🏰 *Hall Standings*\n"]
    for i, row in enumerate(rows):
        mcount = len(sjl(row["members"], []))
        lines.append(f"{medals[i]} *{row['name']}*  -  Lv {safe_int(row['level'],1)} | {mcount} members")
    await send_group(update, "\n".join(lines), delay=15)


async def guilddonate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("guild_id"):
        await send_group(update, "You're not in a guild!", delay=9); return
    g = get_guild(p["guild_id"])
    if not g:
        await send_group(update, "Guild not found.", delay=9); return

    # Typed amount still works
    if context.args:
        try: amount = int(context.args[0])
        except: await send_group(update, "Usage: /guilddonate [amount]", delay=9); return
        if amount <= 0 or p.get("gold", 0) < amount:
            await send_group(update, f"Not enough gold! Have {p.get('gold',0)}g.", delay=9); return
        p["gold"] -= amount; g["bank"] = safe_int(g.get("bank")) + amount
        gmsgs = add_guild_exp(g, amount//10); save_guild(g); save_player(p)
        msg = f"💰 *{user.first_name}* donated {amount}g to *{g['name']}*! Bank: {safe_int(g.get('bank'))}g"
        if gmsgs: msg += "\n" + "\n".join(gmsgs)
        await send_group(update, msg, delay=15)
        return

    # Button menu
    gold = safe_int(p.get("gold", 0))
    uid = user.id
    amounts = [50, 100, 250, 500, 1000, 2500]
    buttons = []
    row = []
    for amt in amounts:
        if gold >= amt:
            row.append(InlineKeyboardButton(f"{amt}g", callback_data=f"gdonate_{uid}_{amt}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row: buttons.append(row)
    if not buttons:
        await send_group(update, f"Not enough gold to donate! You have {gold}g.", delay=9); return
    markup = InlineKeyboardMarkup(buttons)
    glvl = safe_int(g.get("level"), 1)
    nxt = guild_exp_for_level(glvl) if glvl < 10 else "MAX"
    await send_group(update,
        f"🏰 *{g['name']}* — Guild Bank: {safe_int(g.get('bank'))}g\n"
        f"⭐ Level {glvl} | EXP: {safe_int(g.get('exp'))}/{nxt}\n"
        f"Your gold: *{gold}g*\n\nHow much to donate?",
        reply_markup=markup, delay=30)


async def guilddonate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_", 2)
    try: uid = int(parts[1]); amount = int(parts[2])
    except (IndexError, ValueError): await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your donation menu!", show_alert=True); return
    p = get_player(uid)
    if not p: await query.answer("Player not found.", show_alert=True); return
    if not p.get("guild_id"): await query.answer("You're not in a guild!", show_alert=True); return
    if p.get("gold", 0) < amount:
        await query.answer(f"Not enough gold! Have {p.get('gold',0)}g.", show_alert=True); return
    g = get_guild(p["guild_id"])
    if not g: await query.answer("Guild not found.", show_alert=True); return
    p["gold"] -= amount; g["bank"] = safe_int(g.get("bank")) + amount
    gmsgs = add_guild_exp(g, amount//10); save_guild(g); save_player(p)
    lv_note = (" ".join(gmsgs) + " ") if gmsgs else ""
    await query.answer(f"Donated {amount}g!")
    await query.edit_message_text(
        f"💰 *{query.from_user.first_name}* donated *{amount}g* to *{g['name']}*!\n"
        f"Guild Bank: *{safe_int(g.get('bank'))}g* {lv_note}",
        parse_mode="Markdown")


async def guildkick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("guild_id"):
        await send_group(update, "You're not in a guild!", delay=9); return
    g = get_guild(p["guild_id"])
    if not g or g["leader_id"] != user.id:
        await send_group(update, "Only the guild leader can kick members.", delay=9); return

    # If replying to a message, kick that player directly
    if update.message.reply_to_message:
        tp = get_player(update.message.reply_to_message.from_user.id)
        if not tp or tp.get("guild_id") != p.get("guild_id"):
            await send_group(update, "That player isn't in your guild.", delay=9); return
        if update.message.reply_to_message.from_user.id == user.id:
            await send_group(update, "You can't kick yourself! Use /guilddisband to close the guild.", delay=9); return
        members = sjl(g["members"], [])
        if update.message.reply_to_message.from_user.id in members:
            members.remove(update.message.reply_to_message.from_user.id)
        g["members"] = json.dumps(members); save_guild(g)
        tp["guild_id"] = None; save_player(tp)
        await send_group(update, f"🚫 *{tp['username']}* has been kicked from *{g['name']}*.", delay=9)
        return

    # No reply — show member picker buttons
    members = sjl(g["members"], [])
    kickable = [mid for mid in members if mid != user.id]
    if not kickable:
        await send_group(update, "No members to kick.", delay=9); return

    buttons = []
    for mid in kickable:
        mp = get_player(mid)
        if mp:
            buttons.append([InlineKeyboardButton(
                f"🚫 Kick: {mp['username']} (Lv {mp['level']})",
                callback_data=f"gkick_{user.id}_{mid}")])

    if not buttons:
        await send_group(update, "No kickable members found.", delay=9); return

    markup = InlineKeyboardMarkup(buttons)
    await send_group(update,
        f"🚫 *{g['name']} — Kick a Member*\n\nSelect who to remove from the guild:",
        delay=30, reply_markup=markup)


async def guildkick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle member kick button."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_", 2)
    try:
        uid = int(parts[1]); target_uid = int(parts[2])
    except (IndexError, ValueError):
        return
    if query.from_user.id != uid:
        await query.answer("Only the Guild leader can kick members!", show_alert=True); return

    p = get_player(uid)
    if not p:
        await query.edit_message_text("Player not found."); return
    g = get_guild(p.get("guild_id")) if p.get("guild_id") else None
    if not g or g.get("leader_id") != uid:
        await query.edit_message_text("Only the Guild leader can kick members."); return

    tp = get_player(target_uid)
    if not tp or str(tp.get("guild_id")) != str(g["guild_id"]):
        await query.edit_message_text("That player is no longer in your guild."); return
    if target_uid == uid:
        await query.edit_message_text("You can't kick yourself!"); return

    members = sjl(g["members"], [])
    if target_uid in members: members.remove(target_uid)
    g["members"] = json.dumps(members); save_guild(g)
    tp["guild_id"] = None; save_player(tp)
    await query.edit_message_text(
        f"🚫 *{tp['username']}* has been kicked from *{g['name']}*.",
        parse_mode="Markdown")


async def guildleave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("guild_id"):
        await send_group(update, "You're not in a guild!", delay=9); return
    g = get_guild(p["guild_id"])
    if g and g["leader_id"] == user.id:
        await send_group(update, "Leaders can't leave  -  use /guilddisband to close the guild.", delay=9); return
    if g:
        members = sjl(g["members"], [])
        if user.id in members: members.remove(user.id)
        g["members"] = json.dumps(members); save_guild(g)
    p["guild_id"] = None; save_player(p)
    await send_group(update, f"👋 You've left *{g['name'] if g else 'your guild'}*.", delay=9)


async def guilddisband_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("guild_id"):
        await send_group(update, "You're not in a guild.", delay=9); return
    g = get_guild(p["guild_id"])
    if not g:
        await send_group(update, "Guild not found.", delay=9); return
    if g["leader_id"] != user.id:
        await send_group(update, "Only the guild leader can disband the guild.", delay=9); return
    if not context.args or context.args[0].lower() != "confirm":
        gdisband_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Disband Guild", callback_data=f"gdisband_confirm_{user.id}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"gdisband_cancel_{user.id}"),
        ]])
        await send_group(update,
            f"⚠️ This permanently disbands *{g['name']}* and removes all members.\n"
            f"Tap Confirm or type /guilddisband confirm to proceed.",
            delay=15, reply_markup=gdisband_markup); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE players SET guild_id=NULL WHERE guild_id=?", (p["guild_id"],))
    c.execute("DELETE FROM guilds WHERE guild_id=?", (p["guild_id"],))
    conn.commit(); conn.close()
    p["guild_id"] = None; save_player(p)
    await send_group(update, f"🏚️ *{g['name']}* has been disbanded.", permanent=False, delay=30)

async def guilddisband_callback(update, context):
    """Handle guild disband confirm/cancel buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data  # gdisband_confirm_{uid} or gdisband_cancel_{uid}
    parts = data.split("_")
    if len(parts) < 3:
        return
    action = parts[1]  # 'confirm' or 'cancel'
    try:
        uid = int(parts[2])
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your button!", show_alert=True)
        return

    if action == "cancel":
        try:
            await query.edit_message_text("❌ Guild disband cancelled.", parse_mode="Markdown")
        except Exception:
            pass
        return

    # action == "confirm"
    p = get_player(uid)
    if not p or not p.get("guild_id"):
        await query.answer("No guild found!", show_alert=True)
        return
    g = get_guild(p["guild_id"])
    if not g or g["leader_id"] != uid:
        await query.answer("Only the guild leader can disband!", show_alert=True)
        return
    guild_name = g["name"]
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE players SET guild_id=NULL WHERE guild_id=?", (p["guild_id"],))
    c.execute("DELETE FROM guilds WHERE guild_id=?", (p["guild_id"],))
    conn.commit(); conn.close()
    p["guild_id"] = None; save_player(p)
    try:
        await query.edit_message_text(f"🏚️ *{guild_name}* has been disbanded.", parse_mode="Markdown")
    except Exception:
        pass

async def resolve_expired_wars(bot=None, chat_id=None):
    """Resolve all expired guild wars: award EXP, mark inactive, return result strings."""
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT * FROM guild_wars WHERE active=1 AND expires_at <= ?",
              (datetime.now().isoformat(),))
    expired = [dict(r) for r in c.fetchall()]
    results = []
    for war in expired:
        c.execute("UPDATE guild_wars SET active=0 WHERE war_id=?", (war["war_id"],))
        g1 = get_guild(war["guild1_id"]); g2 = get_guild(war["guild2_id"])
        if not g1 or not g2:
            continue
        k1, k2 = war["kills1"], war["kills2"]
        if k1 == k2:
            lvl_msgs1 = add_guild_exp(g1, 500); save_guild(g1)
            lvl_msgs2 = add_guild_exp(g2, 500); save_guild(g2)
            results.append(
                f"⚔️ *Guild War Result: TIE!*\n"
                f"*{g1['name']}* vs *{g2['name']}* — {k1}–{k2}\n"
                f"Both halls earn +500 EXP.")
        else:
            winner, loser = (g1, g2) if k1 > k2 else (g2, g1)
            wk = max(k1, k2); lk = min(k1, k2)
            lvl_msgs = add_guild_exp(winner, 2000); save_guild(winner)
            c.execute("UPDATE guilds SET war_wins=war_wins+1 WHERE guild_id=?", (winner["guild_id"],))
            lv_note = (" ".join(lvl_msgs) + " ") if lvl_msgs else ""
            results.append(
                f"⚔️ *Guild War Over!*\n"
                f"🏆 *{winner['name']}* defeats *{loser['name']}* — {wk}–{lk}!\n"
                f"+2,000 Hall EXP awarded to {winner['name']}! {lv_note}")
    conn.commit(); conn.close()
    return results


async def guildwar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    g = get_guild(p.get("guild_id")) if p.get("guild_id") else None
    if not g:
        await send_group(update, "You're not in a Guild. Use /guildjoin first!", delay=9); return

    # Resolve any wars that just expired
    resolved = await resolve_expired_wars()
    if resolved:
        for r in resolved:
            await send_group(update, r, delay=30)

    args = context.args or []

    # View current war or show guild picker
    if not args:
        war = get_active_war(g["guild_id"])
        if war:
            my_gid = str(g["guild_id"])
            enemy_gid = war["guild2_id"] if str(war["guild1_id"]) == my_gid else war["guild1_id"]
            conn_gw2 = sqlite3.connect(DB_PATH); conn_gw2.row_factory = sqlite3.Row; c2 = conn_gw2.cursor()
            c2.execute("SELECT name, members FROM guilds WHERE guild_id=?", (enemy_gid,))
            enemy_row = c2.fetchone(); conn_gw2.close()
            enemy_name    = enemy_row["name"] if enemy_row else "Unknown"
            our_kills     = war["kills1"] if str(war["guild1_id"]) == my_gid else war["kills2"]
            their_kills   = war["kills2"] if str(war["guild1_id"]) == my_gid else war["kills1"]
            exp_str       = time_until(war["expires_at"]) or "ending soon"
            # Fetch enemy member names
            enemy_member_ids = sjl(enemy_row["members"] if enemy_row else "[]", [])
            enemy_names = []
            if enemy_member_ids:
                conn_em = sqlite3.connect(DB_PATH); conn_em.row_factory = sqlite3.Row; c_em = conn_em.cursor()
                placeholders = ",".join("?" * len(enemy_member_ids))
                c_em.execute(f"SELECT username FROM players WHERE user_id IN ({placeholders})", enemy_member_ids)
                enemy_names = [r["username"] for r in c_em.fetchall()]
                conn_em.close()
            targets_line = ("🎯 *Targets:* " + ", ".join(enemy_names)) if enemy_names else ""
            await send_group(update,
                f"⚔️ *Guild War: {g['name']} vs {enemy_name}*\n\n"
                f"Our kills: *{our_kills}*  |  Their kills: *{their_kills}*\n"
                f"Ends in: *{exp_str}* — most kills wins!\n\n"
                f"{targets_line}\n\n"
                f"_Attack any enemy member to score. Each war kill counts double for daily objectives._",
                delay=25)
            return

        # No active war — show guild picker (leader only)
        if g.get("leader_id") != user.id:
            await send_group(update,
                f"⚔️ *{g['name']}* has no active guild war.\n\n"
                f"_Only the Guild leader can declare war._", delay=12)
            return

        conn_gl = sqlite3.connect(DB_PATH); conn_gl.row_factory = sqlite3.Row; c_gl = conn_gl.cursor()
        c_gl.execute("SELECT guild_id, name, level FROM guilds WHERE guild_id != ? ORDER BY level DESC LIMIT 15",
                     (g["guild_id"],))
        all_guilds = [dict(r) for r in c_gl.fetchall()]
        conn_gl.close()

        if not all_guilds:
            await send_group(update, "⚔️ No other Halls to declare war on yet!", delay=9); return

        buttons = []
        for eg in all_guilds:
            buttons.append([InlineKeyboardButton(
                f"⚔️ Declare war on: {eg['name']} (Lv {eg['level']})",
                callback_data=f"gwdeclare_{user.id}_{eg['guild_id']}")])

        markup = InlineKeyboardMarkup(buttons)
        await send_group(update,
            f"⚔️ *{g['name']} — Declare Guild War*\n\n"
            f"Choose a Hall to challenge. War lasts 24 hours.\n"
            f"_Most kills wins. Each PvP kill counts double for objectives._",
            delay=60, reply_markup=markup)
        return

    # Args provided — legacy typed path (still works)
    if g.get("leader_id") != user.id:
        await send_group(update, "Only the Guild leader can declare war!", delay=9); return

    target_name = " ".join(args)
    conn_gw3 = sqlite3.connect(DB_PATH); conn_gw3.row_factory = sqlite3.Row; c3 = conn_gw3.cursor()
    c3.execute("SELECT * FROM guilds WHERE LOWER(name)=LOWER(?)", (target_name,))
    enemy_g = c3.fetchone()
    conn_gw3.close()
    if not enemy_g:
        await send_group(update, f"Guild *{target_name}* not found. Use /guildwar to pick from a list.", delay=12); return
    enemy_g = dict(enemy_g)
    if enemy_g["guild_id"] == g["guild_id"]:
        await send_group(update, "You can't declare war on yourself!", delay=9); return

    existing = get_active_war(g["guild_id"], enemy_g["guild_id"])
    if existing:
        await send_group(update, f"There's already an active war between {g['name']} and {enemy_g['name']}!", delay=12); return

    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    conn_gw4 = sqlite3.connect(DB_PATH); c4 = conn_gw4.cursor()
    c4.execute("""INSERT INTO guild_wars (guild1_id, guild2_id, declared_by, declared_at, expires_at, kills1, kills2, active)
                  VALUES (?,?,?,?,?,0,0,1)""",
               (g["guild_id"], enemy_g["guild_id"], user.first_name, datetime.now().isoformat(), expires))
    conn_gw4.commit(); conn_gw4.close()
    await send_group(update,
        f"⚔️ *WAR DECLARED!*\n\n"
        f"*{g['name']}* has declared war on *{enemy_g['name']}*!\n"
        f"Duration: 24 hours\n"
        f"Every kill against the enemy Hall scores a point.\n"
        f"May the best Hall win! 🔥", delay=30)


async def guildwar_declare_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle guild war target selection button."""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid = int(parts[1]); enemy_gid = int(parts[2])
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Only the Guild leader who opened this can pick!", show_alert=True); return

    try:
        p = get_player(uid)
        if not p:
            await query.answer("Player not found.", show_alert=True); return
        g = get_guild(p.get("guild_id")) if p.get("guild_id") else None
        if not g or g.get("leader_id") != uid:
            await query.answer("Only the Guild leader can declare war.", show_alert=True); return

        conn_e = sqlite3.connect(DB_PATH); conn_e.row_factory = sqlite3.Row; c_e = conn_e.cursor()
        c_e.execute("SELECT * FROM guilds WHERE guild_id=?", (enemy_gid,))
        enemy_row = c_e.fetchone(); conn_e.close()
        if not enemy_row:
            await query.answer("That Guild no longer exists.", show_alert=True); return
        enemy_g = dict(enemy_row)

        g_gid   = str(g["guild_id"])
        e_gid   = str(enemy_g["guild_id"])
        if g_gid == e_gid:
            await query.answer("You can't declare war on yourself!", show_alert=True); return

        existing = get_active_war(g_gid, e_gid)
        if existing:
            await query.answer(
                f"There's already an active war between {g['name']} and {enemy_g['name']}!",
                show_alert=True); return

        expires = (datetime.now() + timedelta(hours=24)).isoformat()
        conn_w = sqlite3.connect(DB_PATH); c_w = conn_w.cursor()
        c_w.execute("""INSERT INTO guild_wars (guild1_id, guild2_id, declared_by, declared_at, expires_at, kills1, kills2, active)
                       VALUES (?,?,?,?,?,0,0,1)""",
                    (g_gid, e_gid, query.from_user.first_name, datetime.now().isoformat(), expires))
        conn_w.commit(); conn_w.close()
        await query.answer()
        await query.edit_message_text(
            f"⚔️ *WAR DECLARED!*\n\n"
            f"*{g['name']}* has declared war on *{enemy_g['name']}*!\n"
            f"Duration: 24 hours — most kills wins!\n"
            f"May the best Hall win! 🔥",
            parse_mode="Markdown")
    except Exception as e:
        try: await query.answer("Something went wrong. Try again!", show_alert=True)
        except Exception: pass

async def gbank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    g = get_guild(p.get("guild_id")) if p.get("guild_id") else None
    if not g:
        await send_group(update, "You're not in a Guild!", delay=9); return

    args = context.args or []

    if not args:
        bank = safe_int(g.get("bank_gold"))
        await send_group(update,
            f"🏦 *{g['name']} Guild Bank*\n\n"
            f"Balance: *{bank:,}g*\n\n"
            f"_/gbank deposit [amount] — add gold_\n"
            f"_/gbank withdraw [amount] — leader only_", delay=15); return

    sub = args[0].lower()
    if sub == "deposit":
        if len(args) < 2:
            await send_group(update, "Usage: /gbank deposit [amount]", delay=9); return
        try:
            amt = int(args[1])
        except Exception:
            await send_group(update, "Invalid amount.", delay=9); return
        if amt <= 0:
            await send_group(update, "Amount must be positive!", delay=9); return
        if p.get("gold", 0) < amt:
            await send_group(update, f"You only have {p.get('gold',0)}g!", delay=9); return
        p["gold"] -= amt; save_player(p)
        conn_gb = sqlite3.connect(DB_PATH); c_gb = conn_gb.cursor()
        c_gb.execute("UPDATE guilds SET bank_gold=bank_gold+? WHERE guild_id=?", (amt, g["guild_id"]))
        conn_gb.commit(); conn_gb.close()
        await send_group(update,
            f"🏦 Deposited *{amt}g* into *{g['name']}* Bank!\n"
            f"Your balance: {p['gold']}g", delay=15)

    elif sub == "withdraw":
        if g.get("leader_id") != user.id:
            await send_group(update, "Only the Guild leader can withdraw!", delay=9); return
        if len(args) < 2:
            await send_group(update, "Usage: /gbank withdraw [amount]", delay=9); return
        try:
            amt = int(args[1])
        except Exception:
            await send_group(update, "Invalid amount.", delay=9); return
        bank = safe_int(g.get("bank_gold"))
        if amt > bank:
            await send_group(update, f"Bank only has {bank}g!", delay=9); return
        p["gold"] = p.get("gold", 0) + amt; save_player(p)
        conn_gb2 = sqlite3.connect(DB_PATH); c_gb2 = conn_gb2.cursor()
        c_gb2.execute("UPDATE guilds SET bank_gold=bank_gold-? WHERE guild_id=?", (amt, g["guild_id"]))
        conn_gb2.commit(); conn_gb2.close()
        await send_group(update,
            f"🏦 Withdrew *{amt}g* from *{g['name']}* Bank!\n"
            f"Your balance: {p['gold']}g", delay=15)
    else:
        await send_group(update, "Usage: /gbank deposit [amt] | /gbank withdraw [amt]", delay=9)

# ── SKILL ─────────────────────────────────────────────────────────────────────
async def skill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    cls = get_player_class(p)
    if not cls:
        await send_group(update, "No class yet! Use /class at Level 5.", delay=9); return
    all_skills = sjl(p.get("all_skills"), [])
    # Sync: add any skills from current class that the player qualifies for but is missing
    skill_names = {s["name"] for s in all_skills}
    changed = False
    for sk in cls.get("skills", []):
        if sk["name"] not in skill_names and p["level"] >= sk.get("unlock", 5):
            all_skills.append(sk)
            skill_names.add(sk["name"])
            changed = True
    if changed:
        p["all_skills"] = json.dumps(all_skills)
        save_player(p)
    if not all_skills:
        await send_group(update, "No skills unlocked yet.", delay=9); return

    OPEN_WORLD_ALLOWED_SKILL_TYPES = {
        "self_heal", "group_heal", "mass_cleanse", "dmg_reduction_buff",
        "revive_heal", "self_heal_buff", "regen", "heal_shield",
    }

    replying = update.message.reply_to_message is not None

    # Resolve which skill to use from args (name or number)
    sk = None
    if context.args:
        arg = " ".join(context.args)
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(all_skills):
                sk = all_skills[idx]
        if not sk:
            sk = next((s for s in all_skills if s["name"].lower() == arg.lower()), None)
        if not sk:
            await send_group(update, f"No skill matching *{arg}*. Use /skill to see your skills.", delay=9); return

    chat_id = update.effective_chat.id

    # Redirect to raid enemy if player is in a raid
    raid_state, raid_kind = in_active_raid(user.id, chat_id)
    if raid_state:
        # Check player can act
        if cannot_attack(p):
            await send_group(update, "⚡ You're stunned or rooted  -  can't use skills!", delay=9); return

        if sk is None:
            if len(all_skills) == 1:
                sk = all_skills[0]
            else:
                markup = _build_skill_picker_keyboard(all_skills, user.id, 0)
                await update.message.reply_text(
                    f"🔮 *vs {raid_state['enemy']['name']}* — choose a skill:",
                    parse_mode="Markdown", reply_markup=markup)
                await update.message.delete()
                return

        w = get_weather()
        sk_lines, sk_dmg = apply_skill_to_raid_enemy(p, sk, raid_state, w)
        enemy = raid_state["enemy"]
        out = [f"🎱 *{user.first_name}* uses *{sk['name']}* on *{enemy['name']}*!"]
        out.extend(sk_lines)
        if sk_dmg > 0:
            out.append(f"💥 *{sk_dmg} damage!* Enemy HP: {raid_state['enemy_hp']}/{raid_state['enemy_max_hp']}")
            if raid_kind == "group":
                raid = active_raids.get(chat_id)
                if raid:
                    raid["damage_dealt"][user.id] = raid["damage_dealt"].get(user.id, 0) + sk_dmg

        # Check if enemy died from skill
        if raid_state["enemy_hp"] <= 0:
            out.append(f"\n✅ *{enemy['name']}* is destroyed by the skill!")
            # Trigger wave advance on next strike  -  set hp to 0 and let strike handle it
            # We do this by calling the wave-advance logic inline:
            if raid_kind == "solo":
                tier = raid_state["tier"]
                wave_enemies = tier["wave_enemies"]
                cw = raid_state["wave"]
                if cw < len(wave_enemies):
                    raid_state["wave"] += 1
                    ne = wave_enemies[cw].copy()
                    raid_state["enemy"] = ne
                    raid_state["enemy_hp"] = ne["hp"]
                    raid_state["enemy_max_hp"] = ne["hp"]
                    raid_state.pop("enemy_statuses", None)
                    out.append(f"\n🌊 *Wave {raid_state['wave']}  -  {ne['name']}*")
                    out.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
                elif cw == len(wave_enemies):
                    bd = BOSSES[tier["wave_boss_key"]]
                    boss_hp = bd["max_hp"] // 2
                    raid_state["wave"] = len(wave_enemies) + 1
                    raid_state["enemy"] = {"name": bd["name"] + " ⚡","dmg_min": round(bd["dmg_min"]*0.6),"dmg_max": round(bd["dmg_max"]*0.6)}
                    raid_state["enemy_hp"] = boss_hp
                    raid_state["enemy_max_hp"] = boss_hp
                    raid_state.pop("enemy_statuses", None)
                    out.append(f"\n🎱 *FINAL BOSS  -  {bd['name']}!* ❤️ HP: {boss_hp}")
                else:
                    # Solo raid victory via skill kill
                    active_soloraids.pop(user.id, None)
                    exp_reward = tier["exp_reward"]; gold_reward = tier["gold_reward"]
                    p["gold"] = p.get("gold", 0) + gold_reward
                    p["quests_done"] = p.get("quests_done", 0) + 1
                    for _d, _e, _g in track_objective(p, "solo_win"):
                        p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
                    loot = roll_loot_table(tier.get("loot_table", []), p)
                    if loot:
                        add_item(p, loot)
                        r = ""
                        for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                            if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                        out.append(f"🎒 Found: {r} *{loot}*!")
                    w2 = get_weather()
                    add_exp(p, exp_reward, w2)
                    out.append(f"\n🏆 *SOLO RAID COMPLETE!* +{exp_reward:,} EXP | +{gold_reward}g")
        else:
            # Enemy still alive  -  counter-attack
            killed = raid_enemy_counter(p, raid_state, out)
            if killed:
                if raid_kind == "solo":
                    active_soloraids.pop(user.id, None)
                save_player(p)
                await send_group(update, "\n".join(out), delay=20); return

        save_player(p)
        await send_group(update, "\n".join(out), delay=20)
        return

    # Boss fight check  -  if player is in a boss fight, skill hits the boss
    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    is_secret_boss = chat_id in secret_boss_active
    player_in_boss = boss_dict and user.id in [u["id"] for u in boss_dict["participants"]]
    if (player_in_boss or (boss_dict and not update.message.reply_to_message)) and not raid_state:
        if sk is None:
            if len(all_skills) == 1:
                sk = all_skills[0]
            else:
                markup = _build_skill_picker_keyboard(all_skills, user.id, 0)
                await update.message.reply_text(
                    f"🔮 *vs {boss_dict['data']['name']}* — choose a skill:",
                    parse_mode="Markdown", reply_markup=markup)
                await update.message.delete()
                return

        if user.id not in [u["id"] for u in boss_dict["participants"]]:
            boss_dict["participants"].append({"id": user.id, "name": user.first_name, "dmg": 0})
        participant = next(u for u in boss_dict["participants"] if u["id"] == user.id)

        w = get_weather()
        stype = sk.get("type", "damage")
        lines = [f"⚡ *{user.first_name}* uses *{sk['name']}* on *{boss_dict['data']['name']}*!"]

        if stype in ("self_heal", "group_heal", "mass_cleanse",
                     "dmg_reduction_buff", "self_heal_buff", "revive_heal",
                     "self_atk_buff", "def_reflect", "party_atk_buff",
                     "party_def_buff", "party_full_buff", "ultimate_buff"):
            if stype == "self_heal":
                heal = round(get_stat(p, "WIS") * sk.get("mult", 3.0))
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"💚 Healed self for *{heal} HP*!")
            elif stype == "self_heal_buff":
                heal = round(p["max_hp"] * 0.30)
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"💚 *Rally!* +{heal} HP restored.")
            elif stype == "self_atk_buff":
                set_status(p, "blessed_until", 120)
                lines.append("⚔️ *War Cry!* +30% ATK for 2 minutes!")
            elif stype == "def_reflect":
                set_status(p, "def_reflect_until", 120)
                lines.append("🌿 *Thorn Fortress!* 40% dmg reduction + reflect active 2 min!")
            elif stype in ("party_atk_buff", "party_def_buff"):
                set_status(p, "blessed_until", 300)
                label = "War Song" if stype == "party_atk_buff" else "Rune Barrier"
                lines.append(f"🎵 *{label}!* Party buffed +25% stats for 5 minutes!")
            elif stype == "party_full_buff":
                set_status(p, "blessed_until", 600)
                for _f in ["hexed_until", "weakened_until"]: p[_f] = None
                lines.append("🎶 *Ancient Aria!* Full buffs 10 minutes! Debuffs cleared.")
            elif stype == "ultimate_buff":
                p["hp"] = calc_max_hp(p)
                set_status(p, "blessed_until", 1800)
                lines.append("✨ *Magnum Opus!* Full HP restored! +20% all stats 30 min!")
            dmg = 0
        else:
            mult = sk.get("mult", 1.0) or 1.0
            hits = sk.get("hits", 1)
            if hits and hits > 1:
                total = 0; hit_log = []
                for _ in range(hits):
                    h = round(calc_attack_damage(p, w) * mult)
                    if check_crit(p): h = apply_crit(p, h); hit_log.append(f"💥{h}")
                    else: hit_log.append(str(h))
                    total += h
                dmg = total
                lines.append(f"⚡ {hits}-hit combo! [{' + '.join(hit_log)}] = {dmg}")
            elif stype in ("freeze_nuke", "execute_nuke", "holy_nuke", "fear_kill",
                           "nature_nuke", "holy_warrior_nuke", "godlike_lightning"):
                stat_key = sk.get("stat", get_primary_stat(p))
                dmg = round(get_stat(p, stat_key) * sk.get("mult", 3.0))
                lines.append(f"💥 *{sk['name']}!* {dmg} damage!")
                if stype == "nature_nuke":
                    lines.append("🌿 Boss poisoned + weakened!")
                elif stype == "godlike_lightning":
                    lines.append("⚡ Divine lightning — boss hexed!")
            elif stype in ("drain", "drain_kill", "hp_drain", "drain_debuff"):
                drain_pct = sk.get("drain_pct", 0.25)
                dmg = round(boss_dict["hp"] * drain_pct)
                heal = round(dmg * sk.get("heal_pct", 0.50))
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"🩸 *{sk['name']}!* Drained {dmg} HP! Healed {heal}.")
                if stype == "drain_debuff": lines.append("💀 Boss hexed + weakened!")
            elif stype in ("stun_def_dmg", "intercept_aoe"):
                str_v = get_stat(p, "STR"); def_v = get_stat(p, "DEF")
                dmg = round((str_v + def_v) * sk.get("mult", 1.0))
                if stype == "intercept_aoe":
                    set_status(p, "def_reflect_until", 120)
                    lines.append(f"🛡️ *{sk['name']}!* DEF-based {dmg} damage + intercept active!")
                else:
                    lines.append(f"🛡️ *{sk['name']}!* {dmg} damage!")
            elif stype in ("curse_chain", "mass_debuff"):
                int_v = get_stat(p, "INT")
                dmg = round(int_v * sk.get("mult", 2.0))
                lines.append(f"💜 *{sk['name']}!* {dmg} damage + max curses!")
            elif stype == "aoe_heal_dmg":
                wis = get_stat(p, "WIS")
                heal = round(wis * 3); p["hp"] = min(p["max_hp"], p["hp"] + heal)
                dmg = round(wis * 5)
                lines.append(f"🌸 *{sk['name']}!* Healed +{heal} HP + {dmg} to boss!")
            elif stype in ("aoe_poison_strong",):
                wis = get_stat(p, "WIS")
                dmg = round(wis * 2)
                lines.append(f"☠️ *{sk['name']}!* {dmg} + boss poisoned for 10 min!")
            else:
                dmg = round(calc_attack_damage(p, w) * mult)
            if stype not in ("multihit", "multi_hit") and hits == 1 and check_crit(p):
                dmg = apply_crit(p, dmg)
                lines.append("💥 *CRITICAL HIT!*")
            boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
            participant["dmg"] += dmg
            lines.append(f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}")

        # Boss counter-attack
        alive = [u for u in boss_dict["participants"]
                 if not is_defeated(get_player(u["id"]))]
        if alive and boss_dict["hp"] > 0 and random.random() < 0.90:
            target = random.choice(alive)
            tp = get_player(target["id"])
            if tp:
                bdmg = calc_defense(tp, random.randint(
                    boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"]))
                tp["hp"] = max(0, tp["hp"] - bdmg)
                if tp["hp"] == 0:
                    tp["defeated_until"] = (datetime.now() + timedelta(hours=6)).isoformat()
                    tp["last_defeated_by"] = f"{boss_dict['data']['name']} (Boss)"
                    asyncio.create_task(_notify_defeat(context.bot, tp, boss_dict['data']['name'] + " (Boss)"))
                    lines.append(f"💀 *{boss_dict['data']['name']}* kills *{target['name']}*!")
                else:
                    lines.append(f"💥 Boss hits *{target['name']}* for {bdmg}!")
                save_player(tp)

        if boss_dict["hp"] <= 0:
            data = boss_dict["data"]
            if is_secret_boss: secret_boss_active.pop(chat_id, None)
            else: active_bosses.pop(chat_id, None)
            lines.append(f"\n🏆 *{data['name']} DEFEATED by {sk['name']}!*\n")
            w2 = get_weather()
            for u in boss_dict["participants"]:
                pp = get_player(u["id"])
                if not pp: continue
                pp["gold"] = pp.get("gold", 0) + data["gold"]
                loot = roll_loot_table(data.get("loot_table", []))
                if loot:
                    add_item(pp, loot)
                    r = ""
                    for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                        if loot in pool:
                            r = RARITY_EMOJI.get(pool[loot].get("rarity", ""), "")
                            break
                    lines.append(f"🎒 *{pp['username']}* found: {r} *{loot}*!")
                if award_title(pp, data["title"]):
                    lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
                lmsgs, leveled = add_exp(pp, data["exp"], w2)
                save_player(pp)
                lines.append(f"✅ *{pp['username']}*  -  +{data['exp']:,} EXP | +{data['gold']} Gold")
                if leveled and pp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{pp['username']}* reached *Level {pp['level']}*! 🏆",
                        permanent=True))

        save_player(p)
        await send_group(update, "\n".join(lines), delay=30)
        return

    if not replying:
        lines = [f"🔮 *Your Skills* ({get_player_class(p)['name']}):\n"]
        for i, s in enumerate(all_skills, 1):
            lines.append(f"*{i}.* *{s['name']}*  -  {s['desc']}")
        lines.append("\n_Reply to a message with /skill [name or number] to use a skill._")
        await send_group(update, "\n".join(lines), delay=20)
        return

    # Replying to a target  -  pick skill
    if sk is None:
        if len(all_skills) == 1:
            sk = all_skills[0]
        else:
            # Show numbered selection prompt
            target_uid = update.message.reply_to_message.from_user.id
            markup = _build_skill_picker_keyboard(all_skills, user.id, 0, target_uid)
            await update.message.reply_text(
                "🔮 Choose a skill to use:",
                parse_mode="Markdown", reply_markup=markup)
            await update.message.delete()
            return

    await _execute_skill(update, context, p, sk)

_SKILL_PAGE_SIZE = 4

def _build_skill_picker_keyboard(all_skills, uid, page, target_uid=None):
    """Return InlineKeyboardMarkup for a page of skills (4 per page)."""
    start = page * _SKILL_PAGE_SIZE
    end   = min(start + _SKILL_PAGE_SIZE, len(all_skills))
    keyboard = []
    for real_idx in range(start, end):
        s  = all_skills[real_idx]
        cb = f"skillpick_{uid}_{real_idx}" if target_uid is None else f"skillpick_{uid}_{real_idx}_{target_uid}"
        keyboard.append([InlineKeyboardButton(f"⚡ {s['name']}  —  {s['desc'][:50]}", callback_data=cb)])
    nav = []
    if page > 0:
        cb = f"skillpage_{uid}_{page-1}" if target_uid is None else f"skillpage_{uid}_{page-1}_{target_uid}"
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=cb))
    if end < len(all_skills):
        cb = f"skillpage_{uid}_{page+1}" if target_uid is None else f"skillpage_{uid}_{page+1}_{target_uid}"
        nav.append(InlineKeyboardButton("Next ▶", callback_data=cb))
    if nav:
        keyboard.append(nav)
    return InlineKeyboardMarkup(keyboard)

async def skillpage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ◀/▶ navigation inside the skill picker."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")  # skillpage_{uid}_{page} or skillpage_{uid}_{page}_{target_uid}
    try:
        uid = int(parts[1]); page = int(parts[2])
        target_uid = int(parts[3]) if len(parts) > 3 else None
    except (IndexError, ValueError):
        return
    if query.from_user.id != uid:
        await query.answer("Not your picker!", show_alert=True); return
    p = get_player(uid)
    if not p: return
    all_skills = sjl(p.get("all_skills"), [])
    chat_id = query.message.chat_id
    raid_state, _ = in_active_raid(uid, chat_id)
    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    if raid_state:
        header = f"🔮 *vs {raid_state['enemy']['name']}* — choose a skill:"
    elif boss_dict:
        header = f"🔮 *vs {boss_dict['data']['name']}* — choose a skill:"
    else:
        header = "🔮 Choose a skill to use:"
    markup = _build_skill_picker_keyboard(all_skills, uid, page, target_uid)
    await query.edit_message_text(header, parse_mode="Markdown", reply_markup=markup)

async def skill_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline button handler for skill picker in raids, boss fights, and PVP."""
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # formats: skillpick_{uid}_{idx}  or  skillpick_{uid}_{idx}_{target_uid}
    try:
        uid = int(parts[1])
        skill_idx = int(parts[2])
        target_uid = int(parts[3]) if len(parts) > 3 else None
    except (IndexError, ValueError):
        return

    if query.from_user.id != uid:
        await query.answer("This skill picker isn't for you!", show_alert=True)
        return

    p = get_player(uid)
    if not p:
        await query.edit_message_text("Player not found!")
        return

    all_skills = sjl(p.get("all_skills"), [])
    if skill_idx >= len(all_skills):
        await query.edit_message_text("Invalid skill selection.")
        return

    sk = all_skills[skill_idx]
    chat_id = query.message.chat_id
    w = get_weather()

    async def send_result(text):
        try:
            await query.edit_message_text(text[:4096], parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id, text[:4096], parse_mode="Markdown")

    # ── Raid context ──────────────────────────────────────────────────────────
    raid_state, raid_kind = in_active_raid(uid, chat_id)
    if raid_state:
        if cannot_attack(p):
            await send_result("⚡ You're stunned or rooted — can't use skills!")
            return
        sk_lines, sk_dmg = apply_skill_to_raid_enemy(p, sk, raid_state, w)
        enemy = raid_state["enemy"]
        out = [f"🎱 *{p['username']}* uses *{sk['name']}* on *{enemy['name']}*!"]
        out.extend(sk_lines)
        if sk_dmg > 0:
            out.append(f"💥 *{sk_dmg} damage!* Enemy HP: {raid_state['enemy_hp']}/{raid_state['enemy_max_hp']}")
            if raid_kind == "group":
                raid = active_raids.get(chat_id)
                if raid:
                    raid["damage_dealt"][uid] = raid["damage_dealt"].get(uid, 0) + sk_dmg
        if raid_state["enemy_hp"] <= 0:
            out.append(f"\n✅ *{enemy['name']}* is destroyed!")
            if raid_kind == "solo":
                tier = raid_state["tier"]
                wave_enemies = tier["wave_enemies"]
                cw = raid_state["wave"]
                if cw < len(wave_enemies):
                    raid_state["wave"] += 1
                    ne = wave_enemies[cw].copy()
                    raid_state["enemy"] = ne
                    raid_state["enemy_hp"] = ne["hp"]
                    raid_state["enemy_max_hp"] = ne["hp"]
                    raid_state.pop("enemy_statuses", None)
                    out.append(f"\n🌊 *Wave {raid_state['wave']} — {ne['name']}*")
                    out.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
                elif cw == len(wave_enemies):
                    bd = BOSSES[tier["wave_boss_key"]]
                    boss_hp = bd["max_hp"] // 2
                    raid_state["wave"] = len(wave_enemies) + 1
                    raid_state["enemy"] = {"name": bd["name"] + " ⚡", "dmg_min": round(bd["dmg_min"]*0.6), "dmg_max": round(bd["dmg_max"]*0.6)}
                    raid_state["enemy_hp"] = boss_hp
                    raid_state["enemy_max_hp"] = boss_hp
                    raid_state.pop("enemy_statuses", None)
                    out.append(f"\n🎱 *FINAL BOSS — {bd['name']}!* ❤️ HP: {boss_hp}")
                else:
                    active_soloraids.pop(uid, None)
                    exp_reward = tier["exp_reward"]; gold_reward = tier["gold_reward"]
                    p["gold"] = p.get("gold", 0) + gold_reward
                    p["quests_done"] = p.get("quests_done", 0) + 1
                    for _d, _e, _g in track_objective(p, "solo_win"):
                        p["gold"] = p.get("gold", 0) + _g; add_exp(p, _e)
                    loot = roll_loot_table(tier.get("loot_table", []), p)
                    if loot:
                        add_item(p, loot)
                        r = ""
                        for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                            if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""), ""); break
                        out.append(f"🎒 Found: {r} *{loot}*!")
                    add_exp(p, exp_reward, w)
                    out.append(f"\n🏆 *SOLO RAID COMPLETE!* +{exp_reward:,} EXP | +{gold_reward}g")
        else:
            killed = raid_enemy_counter(p, raid_state, out)
            if killed and raid_kind == "solo":
                active_soloraids.pop(uid, None)
        save_player(p)
        await send_result("\n".join(out))
        return

    # ── Boss context ──────────────────────────────────────────────────────────
    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    is_secret_boss = chat_id in secret_boss_active
    if boss_dict and uid in [u["id"] for u in boss_dict["participants"]]:
        participant = next(u for u in boss_dict["participants"] if u["id"] == uid)
        stype = sk.get("type", "damage")
        out = [f"⚡ *{p['username']}* uses *{sk['name']}* on *{boss_dict['data']['name']}*!"]
        if stype in ("self_heal", "self_heal_buff"):
            heal = round(p["max_hp"] * 0.30) if stype == "self_heal_buff" else round(get_stat(p, "WIS") * sk.get("mult", 3.0))
            p["hp"] = min(p["max_hp"], p["hp"] + heal)
            out.append(f"💚 Healed self for *{heal} HP*!")
            dmg = 0
        else:
            mult = sk.get("mult", 1.0) or 1.0
            hits = sk.get("hits", 1)
            if hits and hits > 1:
                total = 0; hit_log = []
                for _ in range(hits):
                    h = round(calc_attack_damage(p, w) * mult)
                    if check_crit(p): h = apply_crit(p, h); hit_log.append(f"💥{h}")
                    else: hit_log.append(str(h))
                    total += h
                dmg = total
                out.append(f"⚡ {hits}-hit combo! [{' + '.join(hit_log)}] = {dmg}")
            elif stype in ("freeze_nuke", "execute_nuke", "holy_nuke", "fear_kill"):
                stat_key = sk.get("stat", get_primary_stat(p))
                dmg = round(get_stat(p, stat_key) * sk.get("mult", 3.0))
                out.append(f"💥 *{sk['name']}!* {dmg} damage!")
            elif stype in ("drain", "drain_kill", "hp_drain"):
                drain_pct = sk.get("drain_pct", 0.30)
                dmg = round(boss_dict["data"]["max_hp"] * drain_pct)
                heal = round(dmg * sk.get("heal_pct", 0.50))
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                out.append(f"🩸 *{sk['name']}!* Drained {dmg} HP! Healed {heal}.")
            else:
                dmg = round(calc_attack_damage(p, w) * mult)
            if hits == 1 and check_crit(p):
                dmg = apply_crit(p, dmg)
                out.append("💥 *CRITICAL HIT!*")
            boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
            participant["dmg"] += dmg
            out.append(f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}")
        if boss_dict["hp"] > 0:
            alive = [u for u in boss_dict["participants"]
                     if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp",{}).get(u["id"],1) > 0]
            if alive and random.random() < 0.90:
                hit_count = 2 if random.random() < 0.30 else 1
                targets = random.sample(alive, min(hit_count, len(alive)))
                for target in targets:
                    tp = get_player(target["id"])
                    if tp and not is_defeated(tp):
                        raw = random.randint(boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"])
                        edm = calc_defense(tp, raw)
                        boss_dict["player_hp"][target["id"]] = max(0,
                            boss_dict["player_hp"].get(target["id"], calc_max_hp(tp)) - edm)
                        php  = boss_dict["player_hp"][target["id"]]
                        pmhp = boss_dict["player_max_hp"].get(target["id"], calc_max_hp(tp))
                        if php == 0:
                            exp_loss = apply_pvp_death(tp, killer_name=boss_dict['data']['name'], cause="Boss")
                            save_player(tp)
                            out.append(f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! -{exp_loss} EXP.")
                        else:
                            out.append(f"💥 *{boss_dict['data']['name']}* hits *{target['name']}* for *{edm}!* ({php}/{pmhp} HP)")
                        save_player(tp)
        save_player(p)
        await send_result("\n".join(out))
        return

    # ── PVP context (target_uid provided) ────────────────────────────────────
    if target_uid:
        tp = get_player(target_uid)
        if not tp:
            await send_result("Target player not found!"); return
        stype = sk.get("type", "damage")
        _support_types = {"self_heal", "self_heal_buff", "group_heal", "dmg_reduction_buff",
                          "revive_heal", "regen", "full_revive", "heal_shield", "mass_cleanse"}
        # Block offensive skills on guild members
        if stype not in _support_types:
            if p.get("guild_id") and str(p.get("guild_id")) == str(tp.get("guild_id")):
                g_s = get_guild(p["guild_id"])
                gname_s = g_s["name"] if g_s else "your Guild"
                await send_result(f"🏰 {tp['username']} is in {gname_s} — can't use offensive skills on guild members!"); return
        # Healing/support skills bypass invincibility and defeated checks
        if stype not in _support_types:
            if is_defeated(tp):
                await send_result(f"{tp['username']} is already defeated!"); return
            if is_invincible(tp):
                await send_result(f"🛡️ {tp['username']} is still recovering — invincible."); return
        if is_silenced(p):
            await send_result("🤐 You are silenced — can't use skills!"); return
        base = calc_attack_damage(p, w)
        out = [f"⚡ *{p['username']}* uses *{sk['name']}* on *{tp['username']}*!"]
        if stype in ("self_heal", "self_heal_buff", "group_heal", "mass_cleanse"):
            await send_result("Use self/group skills with /skill (no target).")
            return
        # ── Healing skills on target ──
        if stype == "revive_heal":
            cls_p = get_player_class(p)
            wis = get_stat(p, "WIS")
            mult = 1.25 if cls_p and cls_p.get("passive_key") == "mending_aura" else 1.0
            heal = round(wis * 5 * mult)
            was_defeated = is_defeated(tp)
            if was_defeated:
                if tp.get("revival_blocked_until") and _ts_active(tp, "revival_blocked_until"):
                    await send_result(f"☠️ {tp['username']} is condemned — cannot be revived!"); return
                tp["defeated_until"] = None
                tp["hp"] = min(calc_max_hp(tp), heal)
                tp["invincible_until"] = (datetime.now() + timedelta(hours=1)).isoformat()
                out.append(f"✨ *Holy Light!* *{tp['username']}* revived with *{heal} HP*!\n"
                           f"🛡️ 1 hour invincibility granted.")
            else:
                tp["hp"] = min(calc_max_hp(tp), tp["hp"] + heal)
                out.append(f"💚 Healed *{tp['username']}* for *{heal} HP*! ({tp['hp']}/{tp['max_hp']})")
            save_player(p); save_player(tp)
            await send_result("\n".join(out)); return
        if stype == "regen":
            wis = get_stat(p, "WIS")
            heal = wis * 5
            tp["hp"] = min(calc_max_hp(tp), tp["hp"] + heal)
            out.append(f"💚 *Renew!* +{heal} HP to *{tp['username']}*! ({tp['hp']}/{tp['max_hp']})")
            save_player(p); save_player(tp)
            await send_result("\n".join(out)); return
        if stype == "full_revive":
            inv = sjl(p.get("inventory"), [])
            if "Holy Water Vial" not in inv:
                await send_result("✨ Miracle requires a Holy Water Vial — you don't have one."); return
            if tp.get("revival_blocked_until") and _ts_active(tp, "revival_blocked_until"):
                await send_result(f"☠️ {tp['username']} is condemned — cannot be revived!"); return
            inv.remove("Holy Water Vial")
            p["inventory"] = json.dumps(inv)
            tp["hp"] = calc_max_hp(tp)
            tp["defeated_until"] = None
            tp["invincible_until"] = (datetime.now() + timedelta(hours=2)).isoformat()
            out.append(f"✨ *MIRACLE!* *{tp['username']}* fully restored! 🛡️ 2 hours invincibility.")
            save_player(p); save_player(tp)
            await send_result("\n".join(out)); return
        if stype == "dmg_reduction_buff":
            set_status(tp, "blessed_until", 3600)
            out.append(f"✨ *Blessing!* {tp['username']} takes 15% less damage for 1 hour.")
            save_player(p); save_player(tp)
            await send_result("\n".join(out)); return
        dmg = round(base * sk.get("mult", 1.0))
        if stype == "multihit":
            hits = sk.get("hits", 2)
            dmg = sum(round(calc_attack_damage(p, w) * sk.get("mult", 0.8)) for _ in range(hits))
            out.append(f"⚡ {hits}-hit combo! Total: {dmg}")
        elif stype == "crit_dmg":
            dmg = round(base * sk.get("mult", 1.8) * 2)
            out.append("💥 *Guaranteed Critical!*")
        elif stype == "pierce_dmg":
            dmg = round(get_stat(p, "AGI") * 3)
            out.append("🌑 *Pierce!* Ignores dodge and block.")
        elif stype == "pierce_all":
            dmg = round(get_stat(p, "STR") * sk.get("str_mult", 2))
            out.append("🏹 *Piercing Shot!*")
        if check_crit(p):
            dmg = apply_crit(p, dmg); out.append("💥 *CRITICAL HIT!*")
        # Pet defensive ability for skill damage
        sk_def_pet = get_active_pet_record(tp.get("user_id")) if tp.get("user_id") else None
        if sk_def_pet:
            dmg, sk_pet_st, sk_pet_val = apply_pet_defense(sk_def_pet, p, dmg, out)
            if sk_pet_st == "stun":
                set_status(p, "stunned_until", 30)
            elif sk_pet_st == "poison" and sk_pet_val:
                p["poison_damage"] = sk_pet_val
                set_status(p, "poison_until", 60)
            elif sk_pet_st == "lifesteal_to_owner" and sk_pet_val:
                tp["hp"] = min(calc_max_hp(tp), tp.get("hp", 0) + sk_pet_val)
        tp["hp"] = max(0, tp["hp"] - dmg)
        out.append(f"💥 *{dmg} damage!* {tp['username']} HP: {tp['hp']}/{tp['max_hp']}")
        if tp["hp"] == 0:
            apply_pvp_death(tp, p["username"], sk["name"])
            out.append(f"💀 *{tp['username']}* has been defeated by {sk['name']}!")
            completed = await check_and_claim_bounty(context.bot, p, tp, chat_id)
            if completed:
                out.append(f"🎯 Bounty claimed!")
            for _d, _e, _g in track_objective(p, "pvp_win"):
                p["gold"] = p.get("gold", 0) + _g; add_exp(p, _e)
        save_player(p); save_player(tp)
        await send_result("\n".join(out))

async def _execute_skill(update, context, p, sk):
    """Core skill execution logic."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    w    = get_weather()
    stype = sk.get("type","damage")
    lines = [f"⚡ *{p['username']}* uses *{sk['name']}*!"]

    # ── Healing / support skills ──────────────────────────────────────────────
    if stype == "self_heal":
        wis = safe_stats(p).get("WIS",5)
        heal = wis * sk.get("wis_mult",5)
        p["hp"] = min(p["max_hp"], p["hp"]+heal)
        lines.append(f"💚 Healed self for *{heal} HP*! ({p['hp']}/{p['max_hp']})")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "group_heal":
        wis  = safe_stats(p).get("WIS",5)
        heal = wis * sk.get("wis_mult",3)
        gid  = p.get("guild_id")
        healed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"),[]):
                    mp = get_player(mid)
                    if mp:
                        mp["hp"] = min(mp["max_hp"], mp["hp"]+heal)
                        save_player(mp); healed.append(mp["username"])
        if not healed:
            p["hp"] = min(p["max_hp"], p["hp"]+heal); healed = [p["username"]]
            save_player(p)
        lines.append(f"💚 Healed {', '.join(healed)} for *{heal} HP* each!")
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "mass_cleanse":
        # Saint Absolution
        gid = p.get("guild_id")
        cleansed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"),[]):
                    mp = get_player(mid)
                    if mp:
                        for field in ["hexed_until","distracted_until","entangled_until",
                                      "frozen_until","stunned_until","bleed_until",
                                      "weakened_until","revival_blocked_until",
                                      "healing_blocked_until","silenced_until"]:
                            mp[field] = None
                        set_status(mp, "blessed_until", 1800)
                        save_player(mp); cleansed.append(mp["username"])
        lines.append(f"✨ *Absolution!* Cleansed: {', '.join(cleansed) or 'self'}\n"
                     f"Blessed status +10% all stats for 30 minutes!\n"
                     f"_(Zealot's revival block lifted if active)_")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=30); return

    elif stype == "dmg_reduction_buff":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target with /skill!", delay=9); return
        tu = update.message.reply_to_message.from_user
        tp = get_player(tu.id)
        if not tp:
            await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return
        set_status(tp, "blessed_until", 3600)
        save_player(tp); save_player(p)
        lines.append(f"✨ *Blessing* granted to *{tp['username']}*!\n"
                     f"15% damage reduction for 1 hour.")
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "revive_heal":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target with /skill!", delay=9); return
        tu = update.message.reply_to_message.from_user
        tp = get_player(tu.id)
        if not tp:
            await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return
        cls_p = get_player_class(p)
        wis = get_stat(p, "WIS")
        mult = 1.25 if cls_p and cls_p.get("passive_key") == "mending_aura" else 1.0
        # Accessory bonus
        acc = p.get("equipped_accessory")
        if acc and ACCESSORIES.get(acc, {}).get("effect", {}).get("revive_heal_bonus"):
            mult += ACCESSORIES[acc]["effect"]["revive_heal_bonus"]
        heal = round(wis * 5 * mult)
        was_defeated = is_defeated(tp)
        if was_defeated:
            if tp.get("revival_blocked_until") and _ts_active(tp, "revival_blocked_until"):
                await send_group(update, f"☠️ *{tp['username']}* is condemned — cannot be revived!", delay=9); return
            tp["defeated_until"] = None
            tp["hp"] = min(calc_max_hp(tp), heal)
            tp["invincible_until"] = (datetime.now() + timedelta(hours=1)).isoformat()
            save_player(tp); save_player(p)
            lines.append(f"✨ *Holy Light!* *{tp['username']}* is revived with *{heal} HP*!\n"
                         f"🛡️ 1 hour invincibility granted  -  _(Still Recovering)_")
        else:
            tp["hp"] = min(calc_max_hp(tp), tp["hp"] + heal)
            save_player(tp); save_player(p)
            lines.append(f"💚 *Holy Light!* Healed *{tp['username']}* for *{heal} HP*!\n"
                         f"❤️ {tp['username']}: {tp['hp']}/{tp['max_hp']} HP")
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "regen":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target with /skill!", delay=9); return
        tu = update.message.reply_to_message.from_user
        tp = get_player(tu.id)
        if not tp:
            await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return
        wis = get_stat(p, "WIS")
        # Apply an upfront heal equal to 5 ticks of WIS HP
        heal = wis * 5
        tp["hp"] = min(calc_max_hp(tp), tp["hp"] + heal)
        save_player(tp); save_player(p)
        lines.append(f"💚 *Renew!* Applied regeneration to *{tp['username']}*!\n"
                     f"❤️ +{heal} HP restored ({tp['hp']}/{tp['max_hp']})")
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "full_revive":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target with /skill!", delay=9); return
        tu = update.message.reply_to_message.from_user
        tp = get_player(tu.id)
        if not tp:
            await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return
        inv = sjl(p.get("inventory"), [])
        if "Holy Water Vial" not in inv:
            await send_group(update, "✨ *Miracle* requires a *Holy Water Vial* — you don't have one.", delay=9); return
        if tp.get("revival_blocked_until") and _ts_active(tp, "revival_blocked_until"):
            await send_group(update, f"☠️ *{tp['username']}* is condemned — cannot be revived!", delay=9); return
        inv.remove("Holy Water Vial")
        p["inventory"] = json.dumps(inv)
        tp["hp"] = calc_max_hp(tp)
        tp["defeated_until"] = None
        tp["invincible_until"] = (datetime.now() + timedelta(hours=2)).isoformat()
        save_player(tp); save_player(p)
        lines.append(f"✨ *MIRACLE!* *{tp['username']}* fully restored!\n"
                     f"❤️ Full HP restored! 🛡️ 2 hours invincibility granted.\n"
                     f"_(Used: Holy Water Vial)_")
        await send_group(update, "\n".join(lines), delay=20); return

    elif stype == "self_heal_buff":
        wis = get_stat(p, "WIS")
        p["hp"] = min(calc_max_hp(p), p["hp"] + 15)
        lines.append(f"✨ *Holy Fervor!* Restored 15 HP! ({p['hp']}/{p['max_hp']})\n"
                     f"⚡ WIS boosted — heals more effective for 2 minutes.")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "self_atk_buff":
        set_status(p, "blessed_until", 120)
        lines.append(f"⚔️ *War Cry!* {p['username']} gains *+30% ATK and +15% DEF* for 2 minutes!")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "def_reflect":
        set_status(p, "def_reflect_until", 120)
        lines.append(f"🌿 *Thorn Fortress!* {p['username']}: 40% dmg reduction + reflect active 2 min!")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return

    elif stype == "party_atk_buff":
        gid = p.get("guild_id")
        buffed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"), []):
                    mp = get_player(mid)
                    if mp:
                        set_status(mp, "blessed_until", 300)
                        save_player(mp); buffed.append(mp["username"])
        if not buffed:
            set_status(p, "blessed_until", 300); buffed = [p["username"]]; save_player(p)
        lines.append(f"🎵 *War Song!* +25% ATK for 5 minutes!\n💪 Buffed: {', '.join(buffed)}")
        await send_group(update, "\n".join(lines), delay=20); return

    elif stype == "party_def_buff":
        gid = p.get("guild_id")
        buffed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"), []):
                    mp = get_player(mid)
                    if mp:
                        set_status(mp, "blessed_until", 300)
                        save_player(mp); buffed.append(mp["username"])
        if not buffed:
            set_status(p, "blessed_until", 300); buffed = [p["username"]]; save_player(p)
        lines.append(f"🛡️ *Rune Barrier!* +20% DEF for 5 minutes!\n🛡️ Protected: {', '.join(buffed)}")
        await send_group(update, "\n".join(lines), delay=20); return

    elif stype == "party_full_buff":
        gid = p.get("guild_id")
        buffed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"), []):
                    mp = get_player(mid)
                    if mp:
                        set_status(mp, "blessed_until", 600)
                        for _f in ["hexed_until", "weakened_until"]: mp[_f] = None
                        save_player(mp); buffed.append(mp["username"])
        if not buffed:
            set_status(p, "blessed_until", 600)
            for _f in ["hexed_until", "weakened_until"]: p[_f] = None
            buffed = [p["username"]]; save_player(p)
        lines.append(f"🎶 *Ancient Aria!* +15% ATK/DEF/dodge for 10 min! Debuffs cleared.\n"
                     f"✨ Buffed: {', '.join(buffed)}")
        await send_group(update, "\n".join(lines), delay=20); return

    elif stype == "ultimate_buff":
        gid = p.get("guild_id")
        buffed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"), []):
                    mp = get_player(mid)
                    if mp:
                        mp["hp"] = calc_max_hp(mp)
                        set_status(mp, "blessed_until", 1800)
                        save_player(mp); buffed.append(mp["username"])
        if not buffed:
            p["hp"] = calc_max_hp(p)
            set_status(p, "blessed_until", 1800)
            buffed = [p["username"]]; save_player(p)
        lines.append(f"✨ *Magnum Opus!* Full HP restored! +20% all stats 30 min!\n"
                     f"🎵 Empowered: {', '.join(buffed)}")
        await send_group(update, "\n".join(lines), delay=20); return

    # ── Offensive skills ──────────────────────────────────────────────────────
    if not update.message.reply_to_message:
        await send_group(update, f"Reply to your target's message then use /skill!", delay=9); return
    du = update.message.reply_to_message.from_user
    if du.id == user.id:
        await send_group(update, "Can't target yourself!", delay=9); return
    d = get_player(du.id)
    if not d:
        await send_group(update, f"{du.first_name} hasn't ascended yet!", delay=9); return
    if is_defeated(d):
        await send_group(update, f"{d['username']} is already defeated!", delay=9); return
    if is_invincible(d):
        await send_group(update, f"🛡️ {d['username']} is still recovering  -  invincible.", delay=9); return
    if is_silenced(p):
        await send_group(update, "🤐 You are silenced  -  can't use skills!", delay=9); return

    stats_p = safe_stats(p)
    base    = calc_attack_damage(p, w)
    dmg     = base

    if stype == "damage":
        dmg = round(base * sk.get("mult",1.0))
    elif stype == "multihit":
        hits = sk.get("hits",2); mult = sk.get("mult",0.8)
        dmg  = sum(round(calc_attack_damage(p, w)*mult) for _ in range(hits))
        lines.append(f"⚡ {hits}-hit combo! Total: {dmg}")
    elif stype == "crit_dmg":
        dmg = round(base * sk.get("mult",1.8) * 2)
        lines.append("💥 *Guaranteed Critical!*")
    elif stype == "pierce_dmg":
        dmg = round(get_stat(p,"AGI") * 3)
        lines.append("🌑 *Pierce!* Ignores dodge and block.")
    elif stype == "pierce_all":
        dmg = round(get_stat(p,"STR") * sk.get("str_mult",2))
        lines.append("🏹 *Piercing Shot!* Ignores all defense.")
    elif stype == "charged_shot":
        p["charging_killshot"] = 1; save_player(p)
        lines.append("🎯 *Charging...* Next /attack will fire Killshot!")
        await send_group(update, "\n".join(lines), delay=15); return
    elif stype == "stun":
        dmg = round(base * 1.0)
        if random.random() < 0.30:
            set_status(d, "stunned_until", 30)
            lines.append(f"⚡ *Stunned!* {d['username']} will miss their next attack!")
    elif stype == "miss_debuff":
        set_status(d, "distracted_until", 180)
        lines.append(f"😵 *Distracted!* {d['username']} has +30% miss chance for 3 minutes.")
        save_player(d); save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return
    elif stype == "root":
        set_status(d, "entangled_until", 90)
        lines.append(f"🌿 *Entangled!* {d['username']} cannot attack for 90 seconds.")
        save_player(d); save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return
    elif stype == "bleed_crit":
        dmg = round(base * sk.get("mult",2.0) * 2)
        set_status(d, "bleed_until", 300)
        d["bleed_damage"] = 10
        d["bleed_last_tick"] = datetime.now().isoformat()
        lines.append(f"🩸 *Bleeding!* {d['username']} takes 10 dmg every 30s for 5 minutes!")
    elif stype == "drain":
        steal = round(d["hp"] * sk.get("drain_pct",0.30))
        dmg   = round(base * sk.get("mult",1.0))
        p["hp"] = min(p["max_hp"], p["hp"]+steal)
        lines.append(f"🩸 Drained *{steal} HP* from {d['username']}!")
    elif stype == "drain_kill":
        steal = round(d["hp"] * sk.get("drain_pct",0.40))
        dmg   = round(base * sk.get("mult",1.5))
        p["hp"] = min(p["max_hp"], p["hp"]+steal)
        lines.append(f"🩸 *Drain Soul!* Stole {steal} HP!")
    elif stype == "debuff":
        set_status(d, "hexed_until", 120)
        lines.append(f"💀 *Hexed!* {d['username']} deals 25% less damage for 2 minutes!")
        dmg = round(base * 0.8)
    elif stype == "vanish":
        set_status(p, "vanish_until", 60)
        lines.append(f"👻 *Vanished!* {p['username']} is untargetable for 60 seconds!")
        save_player(p)
        await send_group(update, "\n".join(lines), delay=15); return
    elif stype == "silence":
        set_status(d, "silenced_until", 60)
        dmg = round(base * 1.5)
        lines.append(f"🤐 *Silenced!* {d['username']} cannot use skills for 60 seconds!")
    elif stype == "holy_dmg":
        wis = get_stat(p,"WIS")
        dmg = wis * 3
        # Double against recent killers
        recent_kills = d.get("recent_kills", 0)
        if recent_kills: dmg *= 2; lines.append("✨ *Holy!* Double damage vs a recent killer!")
    elif stype == "strip_debuff":
        # Banish  -  strip buffs
        buffs_stripped = 0
        for bf in ["blessed_until","holy_field_until"]:
            if d.get(bf): d[bf] = None; buffs_stripped += 1
        wis = get_stat(p,"WIS")
        dmg = wis * 2 * max(1,buffs_stripped)
        set_status(d, "healing_blocked_until", 1800)
        lines.append(f"🔥 *Banish!* Stripped {buffs_stripped} buffs. "
                     f"Cannot gain buffs for 30 minutes!")
    elif stype == "condemn":
        # Holy Wrath  -  Zealot ultimate
        wis = get_stat(p,"WIS")
        dmg = wis * 8
        for bf in ["blessed_until","holy_field_until"]:
            d[bf] = None
        set_status(d, "hexed_until", 300)
        set_status(d, "weakened_until", 3600)
        lines.append(f"☠️ *Holy Wrath!* All buffs stripped. All debuffs applied.")
    elif stype == "void_nuke":
        dmg = d["hp"] // 2
        set_status(d, "healing_blocked_until", 1800)
        lines.append(f"🌑 *Void Collapse!* {d['username']} loses 50% HP and cannot be healed for 30 min!")
    elif stype == "freeze_nuke":
        int_v = get_stat(p,"INT")
        dmg   = int_v * 6
        set_status(d, "frozen_until", 60)
        lines.append(f"🧊 *Absolute Zero!* {d['username']} frozen for 60 seconds!")
    elif stype == "bounty":
        # Railrunner: Execution Order — 2000g bounty + Marked debuff (+20% dmg taken 30 min)
        dmg = round(base * 0.6)
        expires = (datetime.now() + timedelta(hours=48)).isoformat()
        placed = False
        try:
            bconn = sqlite3.connect(DB_PATH); bc2 = bconn.cursor()
            active_count = bc2.execute(
                "SELECT COUNT(*) FROM bounties WHERE placer_id=? AND claimed_by IS NULL AND expires_at > ?",
                (p["user_id"], datetime.now().isoformat())).fetchone()[0]
            if active_count < 2:
                bc2.execute("DELETE FROM bounties WHERE target_id=? AND placer_id=? AND claimed_by IS NULL",
                            (d["user_id"], p["user_id"]))
                bc2.execute("INSERT INTO bounties (placer_id,target_id,reward,expires_at) VALUES (?,?,?,?)",
                            (p["user_id"], d["user_id"], 2000, expires))
                bconn.commit(); placed = True
            bconn.close()
        except Exception: pass
        if placed:
            set_status(d, "marked_until", 1800)  # 30 min +20% dmg taken
            lines.append(f"🎯 *Execution Order!* A *2,000g bounty* placed on *{d['username']}*!\n"
                         f"🎯 *Marked for Death!* {d['username']} takes +20% damage for 30 minutes!\n"
                         f"Expires in 48h. First to defeat them collects.")
            asyncio.create_task(context.bot.send_message(
                chat_id=d["user_id"],
                text=f"🎯 *{p['username']}* (Railrunner) placed a *2,000g bounty* on you and marked you!\n"
                     "You take +20% damage for 30 minutes. Watch your back — anyone who defeats you claims it.",
                parse_mode="Markdown"))
        else:
            lines.append(f"🎯 *Execution Order!* You already have 2 active contracts  -  collect or wait.")
    elif stype == "bounty_mark":
        dmg = round(base * 0.8)
        lines.append(f"🔴 *Contract!* Marking *{d['username']}*  -  increased threat level.")
    elif stype == "aoe_heal_dmg":
        wis = get_stat(p, "WIS")
        heal = round(wis * 3)
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        lines.append(f"🌸 Healed self *+{heal} HP*! ({p['hp']}/{p['max_hp']})")
        if _ts_active(d, "poison_until") or d.get("poison_damage"):
            dmg = round(wis * 6)
            lines.append("☠️ *Blossom Nova!* Poisoned target takes WIS×6 burst!")
        else:
            dmg = round(wis * 3)
    elif stype == "aoe_poison_strong":
        wis = get_stat(p, "WIS")
        dmg = round(wis * 1.5)
        set_status(d, "poison_until", 600)
        d["poison_damage"] = max(wis, 15)
        d["poison_last_tick"] = datetime.now().isoformat()
        lines.append(f"☠️ *Toxic Bloom!* WIS-scaling poison applied to {d['username']} for 10 min!")
    elif stype == "nature_nuke":
        wis = get_stat(p, "WIS")
        dmg = round(wis * 7)
        set_status(d, "poison_until", 300)
        d["poison_damage"] = max(wis * 2, 20)
        d["poison_last_tick"] = datetime.now().isoformat()
        set_status(d, "healing_blocked_until", 1800)
        lines.append(f"🌿 *Wrath of the Wild!* WIS×7 = {dmg}! Poisoned + no healing 30 min!")
    elif stype == "drain_debuff":
        steal = round(d["hp"] * 0.25)
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        dmg = steal
        set_status(d, "hexed_until", 180)
        set_status(d, "weakened_until", 180)
        lines.append(f"💀 *Doom Curse!* Drained *{steal} HP* from {d['username']}! Hex + Weak 3 min!")
    elif stype == "curse_chain":
        int_v = get_stat(p, "INT")
        dmg = round(int_v * 1.5)
        set_status(d, "hexed_until", 300)
        set_status(d, "weakened_until", 300)
        set_status(d, "exposed_until", 300)
        lines.append(f"💜 *Vex Chain!* {d['username']}: -25% ATK/DEF + exposed 5 min!")
    elif stype == "mass_debuff":
        int_v = get_stat(p, "INT")
        dmg = round(int_v * 2.5)
        set_status(d, "hexed_until", 3600)
        set_status(d, "weakened_until", 3600)
        set_status(d, "stunned_until", 60)
        lines.append(f"💜 *Dread Proclamation!* Max curses on {d['username']} for 1 hour! Stunned 60s!")
    elif stype == "stun_def_dmg":
        str_v = get_stat(p, "STR"); def_v = get_stat(p, "DEF")
        dmg = round((str_v + def_v) * sk.get("mult", 1.0))
        if random.random() < 0.40:
            set_status(d, "stunned_until", 30)
            lines.append(f"🛡️ *Shield Slam!* {dmg} damage! {d['username']} *Stunned* 30s!")
        else:
            lines.append(f"🛡️ *Shield Slam!* (STR+DEF) = {dmg} damage!")
    elif stype == "intercept_aoe":
        def_v = get_stat(p, "DEF")
        dmg = round(def_v * 2)
        set_status(p, "def_reflect_until", 120)
        lines.append(f"🛡️ *Vanguard's Presence!* DEF×2 = {dmg} damage! Intercept active 2 min!")
    elif stype == "holy_warrior_nuke":
        str_v = get_stat(p, "STR"); def_v = get_stat(p, "DEF")
        dmg = round(str_v * 4 + def_v * 4)
        set_status(d, "stunned_until", 60)
        lines.append(f"⚡ *Bifrost Descent!* STR×4+DEF×4 = {dmg} holy damage! {d['username']} stunned 60s!")
    elif stype == "godlike_lightning":
        str_v = get_stat(p, "STR")
        dmg = round(str_v * 8)
        set_status(d, "hexed_until", 180)
        set_status(d, "weakened_until", 180)
        lines.append(f"⚡ *Valhalla's Thunder!* STR×8 = {dmg} divine lightning! {d['username']} hexed + weakened!")
    elif stype == "aoe_bleed_multihit":
        hits = sk.get("hits", 4)
        dmg = sum(round(base * sk.get("mult", 0.6)) for _ in range(hits))
        set_status(d, "bleed_until", 300)
        d["bleed_damage"] = 15
        d["bleed_last_tick"] = datetime.now().isoformat()
        lines.append(f"🌀 *Blade Storm!* {hits}-hit combo ({dmg} total)! {d['username']} *Bleeding* 15/30s!")
    elif stype == "execute_multihit":
        hits = sk.get("hits", 8)
        hp_pct = d["hp"] / max(1, d["max_hp"])
        mult = 1.0 if hp_pct <= 0.50 else sk.get("mult", 0.5)
        dmg = sum(round(base * mult) for _ in range(hits))
        if hp_pct <= 0.50:
            lines.append(f"💀 *Execute!* {d['username']} below 50% — full power!")
        lines.append(f"🌀 *Thousand Cuts!* {hits} hits = *{dmg} total damage!*")
    elif stype == "vanish_dmg":
        agi = get_stat(p, "AGI")
        dmg = round(agi * 4)
        set_status(p, "vanish_until", 30)
        lines.append(f"👻 *Phase Step!* Vanishes + reappears: AGI×4 = {dmg} burst damage!")
    elif stype == "phantom_aoe":
        agi = get_stat(p, "AGI")
        dmg = round(agi * 2.5)
        lines.append(f"🌀 *Ethereal Storm!* AGI×2.5 = {dmg} phantom damage!")
    elif stype == "bounce_spell":
        str_v = get_stat(p, "STR")
        dmg = round(str_v * 2)
        lines.append(f"⚡ *Chain Lightning!* STR×2 = {dmg} lightning — bounces to nearby targets!")
    elif stype in ("aoe_recent_attackers", "holy_nuke", "execute_nuke", "fear_kill",
                   "random_aoe", "raid_aoe", "bind_attacker", "dmg_field",
                   "combo_dmg", "revive_heal", "execution_shot",
                   "multihit_crit", "pierce_dodge", "guaranteed_hit"):
        stat_key = sk.get("stat", get_primary_stat(p))
        dmg = round(get_stat(p, stat_key) * sk.get("mult", 1.5))
        lines.append(f"💥 *{sk['name']}!* {dmg} damage!")

    # Apply defense
    if stype not in ("pierce_all","void_nuke","holy_dmg"):
        dmg = calc_defense(d, dmg)

    d["hp"] = max(0, d["hp"] - dmg)
    lines.append(f"💥 *{dmg} damage* to *{d['username']}*!\n"
                 f"❤️ {d['username']}: {d['hp']}/{d['max_hp']} HP")

    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        # Check Zealot condemn  -  revival blocked
        if stype == "condemn":
            d["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
            d["last_defeated_by"] = f"{p['username']} (Condemned)"
            asyncio.create_task(_notify_defeat(context.bot, d, p['username'] + " — Condemned (cannot be revived for 2h)"))
            set_status(d, "revival_blocked_until", 7200)
            lines.append(f"☠️ *{d['username']}* is condemned! Cannot be revived for 2 hours.\n"
                         f"Only a *Saint's Absolution* can counter this.")
        else:
            d["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
            d["last_defeated_by"] = f"{p['username']} using {sk['name']} (Skill)"
            asyncio.create_task(_notify_defeat(context.bot, d, f"{p['username']} using {sk['name']}"))
        d["losses"] = d.get("losses",0)+1
        p["wins"]   = p.get("wins",0)+1
        asyncio.create_task(check_and_claim_bounty(context.bot, p, d, chat_id))
        exp_gain = 80 + p["level"]*8
        lmsgs, leveled = add_exp(p, exp_gain, w); lvl_msgs = lmsgs
        lines.append(f"\n💀 *{d['username']}* defeated by *{sk['name']}*! +{exp_gain} EXP")
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}* via {sk['name']}! ⚡",
                permanent=True))

    for _d, _e, _g in track_objective(p, "skill_use"):
        p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
    check_titles(p); check_titles(d)
    save_player(p); save_player(d)
    full = "\n".join(lines)
    if lvl_msgs: full += "\n\n" + "\n".join(lvl_msgs)
    if d["hp"] > 0:
        hp_pct = d["hp"] / max(1, d["max_hp"])
        filled = round(hp_pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        full += f"\n❤️ {d['username']}: *{d['hp']}/{d['max_hp']}* [{bar}]"
    statuses = get_active_statuses(d)
    if statuses:
        full += "\n" + " | ".join(statuses)
    try: await update.message.delete()
    except: pass
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id, text=full[:4096], parse_mode="Markdown")
        asyncio.create_task(_auto_delete(context.bot, chat_id, msg.message_id, 30))
    except Exception: pass

# ── MISC COMMANDS ─────────────────────────────────────────────────────────────
async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = get_weather()
    hint = "\n🌑 _Something stirs in the shadows..._" if w.get("secret_eligible") else ""
    await send_group(update,
        f"🌦️ *Table Conditions: {w['name']}*\n_{w['desc']}_\n\n"
        f"📈 EXP x{w['exp_mod']} | ⚔️ DMG x{w['dmg_mod']}{hint}", delay=15)

async def cooldowns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    s_cd = get_shadow(user.id)
    pool_ts = p.get("last_pool") or (s_cd.get("last_pool") if s_cd else None)
    lines = [f"⏳ *{p['username']}'s Cooldowns:*\n",
             f"🎁 Daily:   {time_remaining(p.get('last_daily'), 86400)}",
             f"🗺️ Quest:   {time_remaining(p.get('last_quest'), 3600)}",
             f"🏋️ Train:   {time_remaining(p.get('last_train'), 1800)}",
             f"🎱 Pool:    {time_remaining(pool_ts, 60)}"]
    today = datetime.now().strftime("%Y-%m-%d")
    exp_count = safe_int(p.get("explore_count_today")) if p.get("explore_date")==today else 0
    lines.append(f"🗺️ Explore: {exp_count}/2 today")
    lines.append(f"🏰 Dungeon Run: {time_remaining(p.get('last_dungeon'), 86400)}")
    if is_defeated(p):
        end  = datetime.fromisoformat(p["defeated_until"])
        diff = end - datetime.now()
        m, s = divmod(int(diff.total_seconds()),60); h, m = divmod(m,60)
        lines.append(f"💀 Defeat:  {h}h {m}m remaining")
    if is_invincible(p):
        lines.append(f"🛡️ Invincible: still recovering")
    await send_group(update, "\n".join(lines), delay=15)

async def who_cmd(update, context):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    c.execute("""SELECT s.user_id, s.username, s.level, s.last_seen,
                        p.class_id, p.hp, p.max_hp, p.kill_streak, p.kills_today,
                        p.invincible_until, p.defeated_until
                 FROM shadow_profiles s
                 LEFT JOIN players p ON p.user_id = s.user_id
                 WHERE s.last_seen > ?
                 ORDER BY s.last_seen DESC LIMIT 20""",
              (cutoff,))
    rows = c.fetchall()

    now_iso = datetime.now().isoformat()
    # Batch-fetch which players have active bounties
    if rows:
        uid_list = [row["user_id"] for row in rows]
        placeholders = ",".join("?" * len(uid_list))
        c.execute(
            f"SELECT DISTINCT target_id FROM bounties WHERE target_id IN ({placeholders})"
            f" AND claimed_by IS NULL AND expires_at > ?",
            uid_list + [now_iso])
        bounty_ids = {r[0] for r in c.fetchall()}
    else:
        bounty_ids = set()
    conn.close()

    if not rows:
        await send_group(update, "No players active in the last 24 hours.", delay=9); return

    lines = ["👥 *Active Players (last 24h)*\n"]
    for row in rows:
        cls = CLASS_TREE.get(row["class_id"] or "", {}).get("name", "No Class")
        hp  = safe_int(row["hp"]); mhp = safe_int(row["max_hp"])
        hp_pct = int((hp / max(1, mhp)) * 100) if mhp else 100
        try:
            inv_until = row["invincible_until"]
            def_until = row["defeated_until"]
        except (IndexError, KeyError):
            inv_until = None; def_until = None
        is_inv  = bool(inv_until and inv_until > now_iso)
        is_def  = bool(def_until and def_until > now_iso)
        if is_inv:
            hp_icon = "🛡️"
        elif is_def or (hp == 0 and mhp > 0):
            hp_icon = "💀"
        elif hp_pct > 50:
            hp_icon = "❤️"
        elif hp_pct > 25:
            hp_icon = "🟡"
        else:
            hp_icon = "🔴"
        try:
            kills_today = safe_int(row["kills_today"])
            ks          = safe_int(row["kill_streak"])
        except (IndexError, KeyError):
            kills_today = 0; ks = 0
        wanted_tag  = " 🔴 WANTED" if kills_today >= 5 else ""
        streak_tag  = f" 🔥×{ks}" if ks >= 3 else ""
        bounty_tag  = " 💰" if row["user_id"] in bounty_ids else ""
        lines.append(f"{hp_icon} *{row['username']}* - Lv {row['level']} {cls}{streak_tag}{wanted_tag}{bounty_tag}")

    await send_group(update, "\n".join(lines), delay=20)

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    hist = sjl(p.get("pvp_history"), [])
    if not hist:
        await send_group(update, "📜 *PvP History*\n\nNo recent PvP activity.", delay=12); return
    lines = ["📜 *Your Last 5 PvP Hits*\n"]
    for entry in hist:
        dmg_str = "KO" if entry.get("dmg") == "KO" else f"{entry.get('dmg', '?')} dmg"
        lines.append(f"⚔️ *{entry.get('attacker','?')}* — {dmg_str}  _{entry.get('ts','')}_")
    await send_group(update, "\n".join(lines), delay=20)

async def war_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Resolve any expired wars first
    resolved = await resolve_expired_wars()
    for r in resolved:
        await send_group(update, r, delay=30)

    lines = ["🔥 *8Ball World — War Board*\n"]

    # Active bounties
    conn_w = sqlite3.connect(DB_PATH); conn_w.row_factory = sqlite3.Row; cw = conn_w.cursor()
    cw.execute("""SELECT b.reward, p.username as target_name, p2.username as placer_name
                  FROM bounties b
                  LEFT JOIN players p  ON b.target_id  = p.user_id
                  LEFT JOIN players p2 ON b.placer_id  = p2.user_id
                  WHERE b.claimed_by IS NULL AND b.expires_at > ?
                  ORDER BY b.reward DESC LIMIT 5""", (datetime.now().isoformat(),))
    brows = cw.fetchall()
    if brows:
        lines.append("🎯 *Active Bounties:*")
        for b in brows:
            lines.append(f"💰 *{b['target_name'] or 'Unknown'}* — {b['reward']}g (by {b['placer_name'] or 'Unknown'})")
    else:
        lines.append("🎯 *Active Bounties:* None")

    # Active guild wars
    cw.execute("""SELECT gw.guild1_id, gw.guild2_id, gw.expires_at, gw.kills1, gw.kills2,
                         g1.name as name1, g2.name as name2
                  FROM guild_wars gw
                  LEFT JOIN guilds g1 ON g1.guild_id = gw.guild1_id
                  LEFT JOIN guilds g2 ON g2.guild_id = gw.guild2_id
                  WHERE gw.active=1 AND gw.expires_at > ?""", (datetime.now().isoformat(),))
    wars = cw.fetchall()
    lines.append("")
    if wars:
        lines.append("⚔️ *Active Guild Wars:*")
        for wrow in wars:
            time_left = time_until(wrow["expires_at"]) or "ending soon"
            lines.append(f"🏰 *{wrow['name1']}* vs *{wrow['name2']}*  ({wrow['kills1']} – {wrow['kills2']}) — {time_left} left")
    else:
        lines.append("⚔️ *Guild Wars:* None active")

    # Hall win records
    cw.execute("SELECT name, war_wins FROM guilds WHERE war_wins > 0 ORDER BY war_wins DESC LIMIT 5")
    hall_champs = cw.fetchall()
    if hall_champs:
        lines.append("")
        lines.append("🏆 *Hall War Records:*")
        for h in hall_champs:
            lines.append(f"🏰 *{h['name']}* — {h['war_wins']} war win{'s' if h['war_wins'] != 1 else ''}")

    # Top killers today
    cw.execute("""SELECT username, kills_today, kill_streak FROM players
                  WHERE kills_today_date=? AND kills_today>0
                  ORDER BY kills_today DESC LIMIT 5""",
               (datetime.now().strftime("%Y-%m-%d"),))
    killers = cw.fetchall()
    conn_w.close()
    lines.append("")
    if killers:
        lines.append("💀 *Today's Top Killers:*")
        for k in killers:
            wanted = " 🔴 WANTED" if safe_int(k["kills_today"]) >= 5 else ""
            lines.append(f"⚔️ *{k['username']}* — {k['kills_today']} kills today, {k['kill_streak']} streak{wanted}")
    else:
        lines.append("💀 *Today's Top Killers:* —")

    await send_group(update, "\n".join(lines), delay=30)

async def claim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)

    # If there's an active cache event, handle it first
    chat_id = update.effective_chat.id
    event = active_events.get(chat_id)
    if event and event.get("key") == "cache":
        active_events.pop(chat_id, None)
        loot = roll_loot_table(event.get("loot_table", []))
        gold = random.randint(50, 200)
        if p:
            if loot: add_item(p, loot)
            p["gold"] = p.get("gold", 0) + gold; save_player(p)
        await send_group(update,
            f"💰 *{user.first_name}* claims the abandoned cache!\n"
            f"💰 +{gold} gold" + (f" | 🎒 *{loot}*!" if loot else ""), delay=15)
        return

    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    last = p.get("last_claim")

    if last == today:
        await send_group(update, "✅ Already claimed today! Come back tomorrow.", delay=12); return

    streak = safe_int(p.get("claim_streak"))
    if last == yesterday:
        streak += 1
    else:
        streak = 1  # reset streak if missed a day

    # Rewards scale with streak
    gold_reward  = 50 + min(streak * 10, 200)
    slate_count  = 1 if streak >= 3 else 0
    scale_count  = 1 if streak >= 7 else 0
    bonus_scroll = streak >= 14

    inv = sjl(p.get("inventory"), [])
    if slate_count:
        inv.extend(["Iron Shard"] * slate_count)
    if scale_count:
        inv.extend(["Iron Shard"] * scale_count)
    if bonus_scroll:
        inv.append("Enchanting Scroll")
    p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold", 0) + gold_reward
    p["last_claim"] = today
    p["claim_streak"] = streak
    save_player(p)

    streak_emojis = "🔥" * min(streak, 7)
    lines = [
        f"🎁 *Daily Claim — Day {streak}!* {streak_emojis}\n",
        f"💰 +{gold_reward} gold",
    ]
    if slate_count:
        lines.append(f"🪨 +{slate_count} Iron Shard (Day 3+ streak)")
    if scale_count:
        lines.append(f"🪨 +{scale_count} Iron Shard (Day 7+ streak)")
    if bonus_scroll:
        lines.append(f"📜 +1 Enchanting Scroll (Day 14+ streak)")
    lines.append(f"\n_Streak: {streak} day{'s' if streak != 1 else ''} — claim again tomorrow to keep it going!_")
    await send_group(update, "\n".join(lines), delay=25)

async def forge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    inv = sjl(p.get("inventory"), [])
    inv_ctr = Counter(inv)

    # Typed craft path still works
    if context.args:
        recipe_name = " ".join(context.args)
        matched = next((k for k in RECIPES if k.lower() == recipe_name.lower()), None)
        if not matched:
            await send_group(update, f"❌ Unknown recipe *{recipe_name}*. Use /forge to see available recipes.", delay=12); return
        recipe = RECIPES[matched]
        for mat, qty in recipe["mats"].items():
            if inv_ctr.get(mat, 0) < qty:
                await send_group(update,
                    f"❌ Need {qty}x *{mat}* (have {inv_ctr.get(mat, 0)}).", delay=12); return
        for mat, qty in recipe["mats"].items():
            for _ in range(qty): inv.remove(mat)
        result_item = recipe["result"]
        inv.append(result_item)
        p["inventory"] = json.dumps(inv)
        p["crafts_done"] = safe_int(p.get("crafts_done")) + 1
        check_titles(p); save_player(p)
        await send_group(update,
            f"⚗️ *Crafted!*\n\n*{matched}* → 🎉 *{result_item}*\n"
            f"Added to your inventory!", delay=20)
        return

    # Button menu
    lines = ["⚗️ *The Forge — Crafting*\n"]
    buttons = []
    uid = user.id
    for recipe_name, recipe in RECIPES.items():
        mats_str = ", ".join(f"{v}x {k}" for k, v in recipe["mats"].items())
        can_craft = all(inv_ctr.get(k, 0) >= v for k, v in recipe["mats"].items())
        status = "✅" if can_craft else "🔒"
        lines.append(f"{status} *{recipe_name}* → *{recipe['result']}*")
        lines.append(f"   Requires: {mats_str}")
        if can_craft:
            buttons.append([InlineKeyboardButton(
                f"⚗️ Craft: {recipe_name}", callback_data=f"forge_{uid}_{recipe_name}")])
    if not buttons:
        lines.append("\n_No recipes available — collect materials to craft._")
    markup = InlineKeyboardMarkup(buttons) if buttons else None
    await send_group(update, "\n".join(lines), reply_markup=markup, delay=30)


async def forge_craft_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_", 2)
    try: uid = int(parts[1]); recipe_name = parts[2]
    except (IndexError, ValueError): await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your forge!", show_alert=True); return
    p = get_player(uid)
    if not p: await query.answer("Player not found.", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    inv_ctr = Counter(inv)
    matched = next((k for k in RECIPES if k == recipe_name), None)
    if not matched: await query.answer("Recipe not found.", show_alert=True); return
    recipe = RECIPES[matched]
    for mat, qty in recipe["mats"].items():
        if inv_ctr.get(mat, 0) < qty:
            await query.answer(f"Need {qty}x {mat} (have {inv_ctr.get(mat,0)}).", show_alert=True); return
    for mat, qty in recipe["mats"].items():
        for _ in range(qty): inv.remove(mat)
    result_item = recipe["result"]
    inv.append(result_item)
    p["inventory"] = json.dumps(inv); p["crafts_done"] = safe_int(p.get("crafts_done")) + 1
    check_titles(p); save_player(p)
    # Rebuild menu with updated materials
    inv_ctr2 = Counter(inv)
    lines = ["⚗️ *The Forge — Crafting*\n", f"✅ Crafted *{matched}* → 🎉 *{result_item}*!\n"]
    buttons = []
    for rn, rec in RECIPES.items():
        mats_str = ", ".join(f"{v}x {k}" for k, v in rec["mats"].items())
        can_craft = all(inv_ctr2.get(k, 0) >= v for k, v in rec["mats"].items())
        status = "✅" if can_craft else "🔒"
        lines.append(f"{status} *{rn}* → *{rec['result']}*")
        lines.append(f"   Requires: {mats_str}")
        if can_craft:
            buttons.append([InlineKeyboardButton(f"⚗️ Craft: {rn}", callback_data=f"forge_{uid}_{rn}")])
    await query.answer(f"Crafted {result_item}!")
    await query.edit_message_text("\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        parse_mode="Markdown")

async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    titles = safe_titles(p)
    if not context.args:
        if not titles:
            await send_group(update, "🏅 No titles earned yet. Complete achievements to earn them!", delay=12); return
        uid = user.id
        lines = [f"🏅 *Your Titles:*\n"]
        buttons = []
        for t in titles:
            bonus = TITLE_BONUSES.get(t, {})
            if bonus:
                bonus_parts = []
                for k, v in bonus.items():
                    if k == "all_stats": bonus_parts.append(f"+{v} all")
                    else: bonus_parts.append(f"+{v} {k}")
                bonus_str = f" _({', '.join(bonus_parts)})_"
            else:
                bonus_str = ""
            active_marker = " ◀️" if t == p.get("active_title") else ""
            lines.append(f"• *{t}*{bonus_str}{active_marker}")
            if t != p.get("active_title"):
                buttons.append([InlineKeyboardButton(f"🏅 Equip: {t}", callback_data=f"settitle_{uid}_{t}")])
        markup = InlineKeyboardMarkup(buttons) if buttons else None
        await send_group(update, "\n".join(lines), permanent=False, delay=90, reply_markup=markup); return
    chosen_typed = " ".join(context.args)
    chosen = resolve_item_ci(chosen_typed, titles)
    if not chosen:
        await send_group(update, f"You haven't earned *{chosen_typed}* yet!", delay=9); return
    p["active_title"] = chosen; save_player(p)
    await send_group(update, f"🏅 Title set to *{chosen}*!", delay=9)

async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    # ── Reply-to flow → show inventory items as buttons ───────────────────────
    if update.message.reply_to_message and not context.args:
        tu = update.message.reply_to_message.from_user
        if tu.id == user.id:
            await send_group(update, "❌ Can't trade with yourself.", delay=9); return
        inv = sjl(p.get("inventory"), [])
        tradeable_pools = set(WEAPONS) | set(ARMORS) | set(SHIELDS) | set(ACCESSORIES) | set(CONSUMABLES)
        trade_items = [(k, inv.count(k)) for k in dict.fromkeys(inv) if k in tradeable_pools]
        if not trade_items:
            await send_group(update, "📦 Nothing tradeable in your inventory.", delay=9); return
        buttons = []
        for item, count in trade_items[:12]:
            label = f"📦 {item} {'x'+str(count) if count>1 else ''}"
            buttons.append([InlineKeyboardButton(label,
                callback_data=f"trdi_{user.id}_{tu.id}_{item}")])
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update,
            f"📦 *Trade with {tu.first_name}*\n\nSelect an item to offer:",
            delay=60, reply_markup=markup)
        return

    # ── Legacy typed path ─────────────────────────────────────────────────────
    if len(context.args) < 3:
        await send_group(update,
            "📦 *Trade*\n\n"
            "Reply to a player's message with `/trade` to pick items via buttons.\n\n"
            "Or type: `/trade @username [item name] [price]`",
            delay=15); return
    target_str = context.args[0].lstrip("@")
    try:
        price = int(context.args[-1])
        item_typed = " ".join(context.args[1:-1])
    except:
        await send_group(update, "Invalid format. Usage: `/trade @username [item] [price]`", delay=9); return
    inv = sjl(p.get("inventory"),[])
    item = resolve_item_ci(item_typed, inv)
    if not item:
        await send_group(update, f"You don't have *{item_typed}* in your inventory!", delay=9); return
    if price < 0:
        await send_group(update, "Price must be 0 or more.", delay=9); return
    pending_trades[user.id] = {
        "seller_id": user.id, "seller_name": user.first_name,
        "item": item, "price": price,
        "target_username": target_str.lower(),
        "created_at": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(minutes=30)).isoformat(),
    }
    await send_group(update,
        f"📦 *Trade Offer Posted!*\n\n"
        f"Selling: *{item}* for *{price}g*\n"
        f"To: @{target_str}\n\n"
        f"_{target_str} can type /accept to complete the trade._", delay=30)


async def trade_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seller picked an item — show price buttons."""
    query = update.callback_query
    parts = query.data.split("_", 3)  # trdi_{seller}_{buyer}_{item}
    try:
        seller_uid = int(parts[1]); buyer_uid = int(parts[2]); item = parts[3]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != seller_uid:
        await query.answer("This isn't your trade!", show_alert=True); return
    await query.answer()
    p = get_player(seller_uid)
    if not p:
        await query.edit_message_text("Player not found."); return
    inv = sjl(p.get("inventory"), [])
    if item not in inv:
        await query.edit_message_text(f"❌ You no longer have *{item}*.", parse_mode="Markdown"); return

    prices = [0, 100, 500, 1000, 2500, 5000]
    buttons = []
    row = []
    for pr in prices:
        label = "🎁 Free" if pr == 0 else f"💰 {pr:,}g"
        row.append(InlineKeyboardButton(label,
            callback_data=f"trdp_{seller_uid}_{buyer_uid}_{pr}_{item}"))
        if len(row) == 3:
            buttons.append(row); row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("◀ Back", callback_data=f"trdback_{seller_uid}_{buyer_uid}")])
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(
        f"📦 *Trade: {item}*\n\nChoose a price to offer to the buyer:",
        parse_mode="Markdown", reply_markup=markup)


async def trade_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seller picked a price — post the trade offer."""
    query = update.callback_query
    parts = query.data.split("_", 4)  # trdp_{seller}_{buyer}_{price}_{item}
    try:
        seller_uid = int(parts[1]); buyer_uid = int(parts[2])
        price = int(parts[3]); item = parts[4]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != seller_uid:
        await query.answer("This isn't your trade!", show_alert=True); return
    await query.answer()
    p = get_player(seller_uid)
    if not p:
        await query.edit_message_text("Player not found."); return
    inv = sjl(p.get("inventory"), [])
    if item not in inv:
        await query.edit_message_text(f"❌ You no longer have *{item}*.", parse_mode="Markdown"); return

    # Look up buyer's username for the target check
    buyer_shadow = get_shadow(buyer_uid)
    buyer_player = get_player(buyer_uid)
    buyer_name   = (buyer_player or buyer_shadow or {}).get("username", str(buyer_uid))

    pending_trades[seller_uid] = {
        "seller_id": seller_uid, "seller_name": p.get("username", "Seller"),
        "item": item, "price": price,
        "target_id": buyer_uid,
        "target_username": buyer_name.lower(),
        "created_at": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(minutes=30)).isoformat(),
    }
    price_str = "FREE" if price == 0 else f"{price:,}g"
    await query.edit_message_text(
        f"📦 *Trade Offer Posted!*\n\n"
        f"Item: *{item}*\nPrice: *{price_str}*\nFor: {buyer_name}\n\n"
        f"_{buyer_name} can type /accept to complete the trade. Expires in 30 min._",
        parse_mode="Markdown")
    try:
        await context.bot.send_message(
            chat_id=buyer_uid,
            text=f"📦 *{p.get('username','Someone')}* wants to trade!\n"
                 f"Item: *{item}* — Price: *{price_str}*\n"
                 f"Type /accept to claim it (30 min).",
            parse_mode="Markdown")
    except Exception: pass


async def trade_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to item selection."""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        seller_uid = int(parts[1]); buyer_uid = int(parts[2])
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != seller_uid:
        await query.answer("This isn't your trade!", show_alert=True); return
    await query.answer()
    p = get_player(seller_uid)
    if not p:
        await query.edit_message_text("Player not found."); return
    inv = sjl(p.get("inventory"), [])
    tradeable_pools = set(WEAPONS) | set(ARMORS) | set(SHIELDS) | set(ACCESSORIES) | set(CONSUMABLES)
    trade_items = [(k, inv.count(k)) for k in dict.fromkeys(inv) if k in tradeable_pools]
    buttons = []
    for item, count in trade_items[:12]:
        label = f"📦 {item} {'x'+str(count) if count>1 else ''}"
        buttons.append([InlineKeyboardButton(label,
            callback_data=f"trdi_{seller_uid}_{buyer_uid}_{item}")])
    markup = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(
        "📦 Select an item to offer:",
        parse_mode="Markdown", reply_markup=markup)

async def accept_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    # Find a trade targeted at this user
    trade = None; seller_id = None
    for sid, t in pending_trades.items():
        if t.get("target_id") == user.id or \
           t["target_username"] == user.first_name.lower() or \
           t["target_username"] == str(user.username or "").lower():
            trade = t; seller_id = sid; break
    if not trade:
        await send_group(update, "No trade offer found for you!", delay=9); return
    if datetime.now() > datetime.fromisoformat(trade.get("expires", datetime.now().isoformat())):
        pending_trades.pop(seller_id, None)
        await send_group(update, "❌ That trade offer has expired.", delay=9); return
    # Non-ascended player  -  store item in shadow profile pending_items
    if not p:
        s_acc = get_shadow(user.id)
        if not s_acc:
            await send_group(update, "You don't have a profile yet.", delay=9); return
        if trade["price"] > 0:
            await send_group(update,
                "You need to /ascend before you can pay for items. "
                "Ask the seller to offer it for free.", delay=9); return
        pending = sjl(s_acc.get("pending_items"), [])
        pending.append(trade["item"])
        s_acc["pending_items"] = json.dumps(pending)
        save_shadow(s_acc)
        seller = get_player(trade["seller_id"])
        if seller:
            s_inv = sjl(seller.get("inventory"),[])
            if trade["item"] in s_inv:
                s_inv.remove(trade["item"])
                seller["inventory"] = json.dumps(s_inv)
                save_player(seller)
        pending_trades.pop(seller_id, None)
        await send_group(update,
            f"✅ *{trade['item']}* is waiting for you when you `/ascend`!", delay=15)
        return
    if p.get("gold",0) < trade["price"]:
        await send_group(update,
            f"❌ Need {trade['price']}g, have {p.get('gold',0)}g.", delay=9); return
    seller = get_player(seller_id)
    if not seller:
        await send_group(update, "Seller not found!", delay=9); return
    s_inv = sjl(seller.get("inventory"),[])
    if trade["item"] not in s_inv:
        await send_group(update, "Seller no longer has that item!", delay=9); return
    # Execute trade
    s_inv.remove(trade["item"]); seller["inventory"] = json.dumps(s_inv)
    seller["gold"] = seller.get("gold",0) + trade["price"]
    add_item(p, trade["item"])
    p["gold"] -= trade["price"]
    save_player(seller); save_player(p)
    pending_trades.pop(seller_id, None)
    await send_group(update,
        f"✅ *Trade Complete!*\n\n"
        f"*{user.first_name}* bought *{trade['item']}* from *{trade['seller_name']}* "
        f"for *{trade['price']}g*!", delay=15)

async def decline_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    trade = pending_trades.pop(user.id, None)
    if not trade:
        await send_group(update, "No pending trade to decline.", delay=9); return
    await send_group(update, f"❌ Trade declined.", delay=9)

# ── ENHANCE ───────────────────────────────────────────────────────────────────
async def enhance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    if not context.args:
        lines = ["⚒️ *Enhancement* — choose a slot:\n"]
        inv = sjl(p.get("inventory"), [])
        lines.append(f"🪨 Iron Shards: {inv.count('Iron Shard')}\n")
        buttons = []
        for slot_label, slot_key, slot_id in [
                ("⚔️ Weapon", "equipped_weapon", "weapon"),
                ("🛡️ Armor",  "equipped_armor",  "armor"),
                ("🔰 Shield", "equipped_shield", "shield")]:
            name = p.get(slot_key)
            if not name: continue
            lv    = get_enhancement(p, name)
            stars = "⭐" * lv if lv else "+0"
            nxt   = "MAX" if lv >= 10 else f"+{lv+1} ({int(ENHANCE_RATES[lv+1]*100)}% | {ENHANCE_COSTS[lv+1]} Shards)"
            lines.append(f"{slot_label}: *{name}* {stars}\n  → {nxt}")
            buttons.append([InlineKeyboardButton(
                f"{slot_label}: {name} {stars}",
                callback_data=f"enhance_{user.id}_{slot_id}")])
        if not buttons:
            await send_group(update, "⚒️ No enhanceable gear equipped!", delay=9); return
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update, "\n".join(lines), delay=30, reply_markup=markup); return

    slot = context.args[0].lower()
    slot_map = {
        "weapon": ("equipped_weapon", "ATK"),
        "armor":  ("equipped_armor",  "DEF"),
        "shield": ("equipped_shield", "DEF"),
    }
    if slot not in slot_map:
        await send_group(update, "Usage: /enhance weapon | armor | shield", delay=9); return

    slot_key, stat_label = slot_map[slot]
    item_name = p.get(slot_key)
    if not item_name:
        await send_group(update, f"No {slot} equipped!", delay=9); return

    current = get_enhancement(p, item_name)
    if current >= 10:
        await send_group(update, f"*{item_name}* is already at +10 MAX!", delay=9); return

    next_lv = current + 1
    cost    = ENHANCE_COSTS[next_lv]
    rate    = ENHANCE_RATES[next_lv]

    inv = sjl(p.get("inventory"), [])
    if inv.count("Iron Shard") < cost:
        await send_group(update,
            f"❌ Need {cost} Iron Shard(s), have {inv.count('Iron Shard')}.\n"
            f"Iron Shards drop from bosses, explores, and quests.", delay=9); return

    for _ in range(cost):
        inv.remove("Iron Shard")
    p["inventory"] = json.dumps(inv)

    if random.random() < rate:
        set_enhancement(p, item_name, next_lv)
        bonus = get_enhance_bonus(p, item_name)
        save_player(p)
        await send_group(update,
            f"⚒️ *Enhancement Success!*\n\n"
            f"*{item_name}* → *+{next_lv}* {'⭐' * next_lv}\n"
            f"+{bonus} {stat_label} total from enhancement\n"
            f"Used {cost} Iron Shard(s).", delay=20)
    else:
        if current >= 6:
            set_enhancement(p, item_name, current - 1)
            save_player(p)
            await send_group(update,
                f"💔 *Enhancement Failed!*\n\n"
                f"*{item_name}* dropped from +{current} to +{current - 1}!\n"
                f"Used {cost} Iron Shard(s). Try again.", delay=20)
        else:
            save_player(p)
            await send_group(update,
                f"💔 *Enhancement Failed!*\n\n"
                f"*{item_name}* stays at +{current}.\n"
                f"Used {cost} Iron Shard(s). Try again.", delay=20)

async def enhance_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle slot button from /enhance menu."""
    query = update.callback_query
    parts = query.data.split("_", 2)  # enhance_{uid}_{slot}
    try:
        uid  = int(parts[1])
        slot = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your enhance menu!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    slot_map = {"weapon": ("equipped_weapon", "ATK"), "armor": ("equipped_armor", "DEF"), "shield": ("equipped_shield", "DEF")}
    if slot not in slot_map:
        await query.answer(); return
    slot_key, stat_label = slot_map[slot]
    item_name = p.get(slot_key)
    if not item_name:
        await query.answer(f"No {slot} equipped!", show_alert=True); return
    current = get_enhancement(p, item_name)
    if current >= 10:
        await query.answer(f"{item_name} is already +10 MAX!", show_alert=True); return
    next_lv = current + 1
    cost = ENHANCE_COSTS[next_lv]; rate = ENHANCE_RATES[next_lv]
    inv = sjl(p.get("inventory"), [])
    if inv.count("Iron Shard") < cost:
        await query.answer(f"Need {cost} Iron Shard(s), have {inv.count('Iron Shard')}.", show_alert=True); return
    await query.answer()
    for _ in range(cost):
        inv.remove("Iron Shard")
    p["inventory"] = json.dumps(inv)
    if random.random() < rate:
        set_enhancement(p, item_name, next_lv)
        bonus = get_enhance_bonus(p, item_name)
        save_player(p)
        await query.edit_message_text(
            f"⚒️ *Enhancement Success!*\n\n*{item_name}* → *+{next_lv}* {'⭐' * next_lv}\n"
            f"+{bonus} {stat_label} total from enhancement\nUsed {cost} Iron Shard(s).",
            parse_mode="Markdown")
    else:
        if current >= 6:
            set_enhancement(p, item_name, current - 1); save_player(p)
            await query.edit_message_text(
                f"💔 *Enhancement Failed!*\n\n*{item_name}* dropped from +{current} to +{current-1}!\n"
                f"Used {cost} Iron Shard(s).", parse_mode="Markdown")
        else:
            save_player(p)
            await query.edit_message_text(
                f"💔 *Enhancement Failed!*\n\n*{item_name}* stays at +{current}.\n"
                f"Used {cost} Iron Shard(s).", parse_mode="Markdown")

# ── ENCHANT ───────────────────────────────────────────────────────────────────
async def enchant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    if not context.args:
        lines = ["✨ *Enchanting* — choose a slot:\n"]
        inv = sjl(p.get("inventory"), [])
        lines.append(f"📜 Enchanting Scrolls: {inv.count('Enchanting Scroll')}\n")
        buttons = []
        for slot_label, slot_key, slot_id in [
                ("⚔️ Weapon",    "equipped_weapon",    "weapon"),
                ("🛡️ Armor",     "equipped_armor",     "armor"),
                ("🔰 Shield",    "equipped_shield",    "shield"),
                ("💍 Accessory", "equipped_accessory", "accessory")]:
            name = p.get(slot_key)
            if not name: continue
            encs = get_enchant(p, name)
            count = len(encs); remaining = 3 - count
            enc_str = ", ".join(e["id"].capitalize() for e in encs) if encs else "None"
            lines.append(f"{slot_label}: *{name}*\n  Enchants ({count}/3): {enc_str} | {remaining} slot(s) left")
            buttons.append([InlineKeyboardButton(
                f"{slot_label}: {name}  ({remaining} slot{'s' if remaining != 1 else ''} left)",
                callback_data=f"enchant_{user.id}_{slot_id}")])
        if not buttons:
            await send_group(update, "✨ No gear equipped to enchant!", delay=9); return
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update, "\n".join(lines), delay=30, reply_markup=markup); return

    slot = context.args[0].lower()
    slot_map = {
        "weapon":    ("equipped_weapon",    "weapon"),
        "armor":     ("equipped_armor",     "armor"),
        "shield":    ("equipped_shield",    "armor"),
        "accessory": ("equipped_accessory", "accessory"),
    }
    if slot not in slot_map:
        await send_group(update,
            "Usage: /enchant weapon | armor | shield | accessory", delay=9); return

    slot_key, effect_pool_key = slot_map[slot]
    item_name = p.get(slot_key)
    if not item_name:
        await send_group(update, f"No {slot} equipped!", delay=9); return

    inv = sjl(p.get("inventory"), [])
    if "Enchanting Scroll" not in inv:
        await send_group(update,
            "❌ You need an *Enchanting Scroll*.\n"
            "They drop from explores, quests, and the shop.", delay=9); return

    encs = get_enchant(p, item_name)
    if len(encs) >= 3:
        await send_group(update,
            f"❌ *{item_name}* already has 3 enchants (maximum).\n"
            f"Current: {', '.join(e['id'].capitalize() for e in encs)}"); return

    inv.remove("Enchanting Scroll")
    p["inventory"] = json.dumps(inv)

    pool = ENCHANT_EFFECTS.get(effect_pool_key, [])
    effect = random.choice(pool)
    set_enchant(p, item_name, effect)
    save_player(p)
    new_encs = get_enchant(p, item_name)
    all_str = "\n".join(f"✨ {e['id'].capitalize()}  -  {e['desc']}" for e in new_encs)
    await send_group(update,
        f"✨ *Enchanted!*\n\n"
        f"*{item_name}*  -  Enchants ({len(new_encs)}/3):\n{all_str}", delay=20)

async def enchant_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle slot button from /enchant menu."""
    query = update.callback_query
    parts = query.data.split("_", 2)  # enchant_{uid}_{slot}
    try:
        uid  = int(parts[1])
        slot = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your enchant menu!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    slot_map = {
        "weapon":    ("equipped_weapon",    "weapon"),
        "armor":     ("equipped_armor",     "armor"),
        "shield":    ("equipped_shield",    "armor"),
        "accessory": ("equipped_accessory", "accessory"),
    }
    if slot not in slot_map:
        await query.answer(); return
    slot_key, effect_pool_key = slot_map[slot]
    item_name = p.get(slot_key)
    if not item_name:
        await query.answer(f"No {slot} equipped!", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    if "Enchanting Scroll" not in inv:
        await query.answer("You need an Enchanting Scroll to enchant!", show_alert=True); return
    encs = get_enchant(p, item_name)
    if len(encs) >= 3:
        await query.answer(f"{item_name} already has 3 enchants (max)!", show_alert=True); return
    await query.answer()
    inv.remove("Enchanting Scroll")
    p["inventory"] = json.dumps(inv)
    pool = ENCHANT_EFFECTS.get(effect_pool_key, [])
    effect = random.choice(pool)
    set_enchant(p, item_name, effect)
    save_player(p)
    new_encs = get_enchant(p, item_name)
    all_str = "\n".join(f"✨ {e['id'].capitalize()}  —  {e['desc']}" for e in new_encs)
    await query.edit_message_text(
        f"✨ *Enchanted!*\n\n*{item_name}*  —  Enchants ({len(new_encs)}/3):\n{all_str}",
        parse_mode="Markdown")

# ── SKILL TREE PAGE BUILDER ───────────────────────────────────────────────────
def _build_skill_tree_pages(p):
    """Build 3 pages: current skills, Path A tree, Path B tree."""
    line         = get_class_line(p) or (p.get("class_id") and CLASS_TREE.get(p["class_id"],{}).get("line"))
    if not line: return ["No class chosen yet. Use /class at Level 5."]
    path_chosen  = p.get("class_path")           # "A", "B", or None
    player_level = p["level"]
    unlocked     = {s["name"] for s in sjl(p.get("all_skills"), [])}
    cls          = get_player_class(p)
    cls_name     = cls["name"] if cls else "Base"
    prestige_lvl = safe_int(p.get("prestige_count"))

    CLASS_EMOJIS = {"warrior":"⚔️","mage":"🔮","thief":"🔪","archer":"🏹","priest":"📿"}
    line_emoji   = CLASS_EMOJIS.get(line, "⚔️")

    # Tier/level labels
    TIER_LABELS = {1:"Lv 5", 2:"Prestige (Lv 10)", 3:"Lv 30", 4:"Lv 60", 5:"Lv 100"}

    def _skill_block(sk, cls_data, path_label, player_path, player_lvl, has_unlocked):
        tier    = sk.get("tier", 1)
        req_lvl = sk.get("unlock", 5)
        name    = sk["name"]
        # Determine status
        if name in has_unlocked:
            status = "✅"
        elif tier == 1 or (path_label == player_path and player_lvl >= req_lvl):
            status = "🔓"  # qualifies but not synced (edge case)
        elif path_label and path_label != player_path and player_path:
            status = "🚫"  # wrong path chosen
        else:
            req_str = TIER_LABELS.get(tier, f"Lv {req_lvl}")
            status = f"🔒 _{req_str}_"
        passive_line = f"   ☀️ *Passive:* {sk.get('passive','—')}"
        active_line  = f"   ⚡ *Active:* {sk['desc']}"
        return f"{status} *{name}*\n{passive_line}\n{active_line}"

    # ── Page 1: Current status + unlocked skills ────────────────────────────
    base_cls     = CLASS_TREE.get(line, {})
    path_tier    = {1:"Base",2:"Tier 2",3:"Tier 3",4:"Tier 4",5:"Tier 5"}
    cur_tier     = get_class_tier(p) if callable(get_class_tier) else 1
    path_str     = f"Path {path_chosen}" if path_chosen else "No path yet (prestige at Lv 10)"
    path_classes = CLASS_PATHS.get(line, {}).get(path_chosen, []) if path_chosen else []

    # Build progression chain for current path
    chain_parts = [f"{line_emoji} *{base_cls.get('name','Base')}*"]
    if path_chosen:
        paths = CLASS_PATHS.get(line, {})
        for cid in paths.get(path_chosen, []):
            pc = CLASS_TREE.get(cid, {})
            chain_parts.append(f"*{pc.get('name',cid)}*")
    chain = " → ".join(chain_parts[:cur_tier+1 if path_chosen else 1])

    p1_lines = [
        f"{line_emoji} *{p['username']}'s Skill Tree*\n",
        f"*Class:* {cls_name}  |  *{path_str}*",
        f"*Progression:* {chain}\n",
    ]
    if not sjl(p.get("all_skills"), []):
        p1_lines.append("_No skills unlocked yet. Reach Level 5 and use /class._")
    else:
        p1_lines.append("*Your Unlocked Skills:*\n")
        for sk in sjl(p.get("all_skills"), []):
            p1_lines.append(f"✅ *{sk['name']}*")
            p1_lines.append(f"   ☀️ *Passive:* {sk.get('passive','—')}")
            p1_lines.append(f"   ⚡ *Active:* {sk['desc']}\n")
    p1_lines.append("_Use buttons to explore Path A and Path B skill trees._")
    if path_chosen:
        p1_lines.append(f"_You are on *Path {path_chosen}*. Path {('B' if path_chosen=='A' else 'A')} skills are unavailable._")

    # ── Page 2 & 3: Full path trees ─────────────────────────────────────────
    def _build_path_page(path_key):
        paths      = CLASS_PATHS.get(line, {})
        path_cids  = paths.get(path_key, [])
        path_name  = f"Path {path_key}"
        is_chosen  = (path_chosen == path_key)
        is_blocked = (path_chosen and path_chosen != path_key)
        pg = [f"{line_emoji} *{LINE_ARCHETYPE.get(line,line.title())} — {path_name}*\n"]
        if is_blocked:
            pg.append(f"🚫 _You chose Path {path_chosen}. These skills are unavailable._\n")
        elif is_chosen:
            pg.append(f"✅ _Your chosen path!_\n")
        else:
            pg.append(f"_Prestige at Level 10 to choose this path._\n")

        # Tier 1: base class skills
        pg.append(f"*── Tier 1 (Base Class: {base_cls.get('name','')})* ──")
        for sk in base_cls.get("skills", []):
            pg.append(_skill_block(sk, base_cls, None, path_chosen, player_level, unlocked))
        pg.append("")

        # Tiers 2-5: path classes
        tier_unlock = {2: 10, 3: 30, 4: 60, 5: 100}
        for i, cid in enumerate(path_cids):
            pc   = CLASS_TREE.get(cid, {})
            tier = i + 2
            req  = tier_unlock.get(tier, 10)
            pc_name = pc.get("name", cid)
            if is_blocked:
                pg.append(f"*── Tier {tier} ({pc_name})* ── 🚫 _Unavailable_")
            elif player_level < req and not is_chosen:
                pg.append(f"*── Tier {tier} ({pc_name})* ── 🔒 _Requires Lv {req} + prestige_")
            else:
                pg.append(f"*── Tier {tier} ({pc_name})* ── _{pc.get('desc','')}_ ")
            for sk in pc.get("skills", []):
                pg.append(_skill_block(sk, pc, path_key, path_chosen, player_level, unlocked))
            pg.append("")
        return "\n".join(pg)

    return [
        "\n".join(p1_lines),
        _build_path_page("A"),
        _build_path_page("B"),
    ]

async def _send_skill_tree(target, uid, page, edit=False):
    p = get_player(uid)
    if not p: return
    pages = _build_skill_tree_pages(p)
    total = len(pages)
    page  = max(0, min(page, total - 1))
    labels = ["Your Skills", "Path A", "Path B"]
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton(f"◀ {labels[page-1]}", callback_data=f"sktree_{uid}_{page-1}"))
    if page < total - 1:
        btns.append(InlineKeyboardButton(f"{labels[page+1]} ▶", callback_data=f"sktree_{uid}_{page+1}"))
    markup = InlineKeyboardMarkup([btns]) if btns else None
    text   = pages[page][:4096]
    if edit:
        try:
            await target.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception: pass
    else:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def skill_tree_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_", 3)       # sktree_{uid}_{page}
    try:
        uid  = int(parts[1]); page = int(parts[2])
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your skill tree!", show_alert=True); return
    await query.answer()
    await _send_skill_tree(query, uid, page, edit=True)

# ── BOUNTY ────────────────────────────────────────────────────────────────────
_RAILRUNNER_CLASSES = {"bounty_hunter", "sharpshooter", "sniper", "deadeye"}

def _bounty_class_perks(p):
    """Return (is_railrunner, is_thief, no_fee, amounts, max_contracts)."""
    cid  = p.get("class_id", "")
    line = CLASS_TREE.get(cid, {}).get("line", "")
    is_railrunner = cid in _RAILRUNNER_CLASSES
    is_thief      = line == "thief"
    no_fee        = is_railrunner or is_thief
    if is_thief:
        # Thieves are the underground bounty operators — premium amounts, no fee, 3 contracts
        amounts       = [750, 2500, 5000, 10000]
        max_contracts = 3
    elif is_railrunner:
        # Railrunners have the bounty skill — no fee, but standard amounts
        amounts       = [100, 500, 1000, 5000]
        max_contracts = 3
    else:
        amounts       = [100, 500, 1000, 5000]
        max_contracts = 99  # unlimited stacking from different players
    return is_railrunner, is_thief, no_fee, amounts, max_contracts

async def bounty_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    is_railrunner, is_thief, no_fee, amounts, _ = _bounty_class_perks(p)

    # ── Reply-to flow → show amount buttons ─────────────────────────────────
    if update.message.reply_to_message:
        tu = update.message.reply_to_message.from_user
        if tu.id == user.id:
            await send_group(update, "❌ Can't place a bounty on yourself.", delay=9); return
        target = get_player(tu.id)
        if not target:
            await send_group(update, "❌ That player hasn't ascended yet.", delay=9); return

        fee_note = " *(FREE — no gold cost)*" if no_fee else f"\n💰 Your gold: *{p.get('gold',0):,}g*"
        rl_note  = "\n🎯 *Railrunner:* premium amounts + no fee!" if is_railrunner else (
                   "\n🗡️ *Thief perk:* bounties cost you nothing!" if is_thief else "")

        buttons = []
        row = []
        for amt in amounts:
            can_afford = no_fee or p.get("gold", 0) >= amt
            label = f"{'✅' if can_afford else '🔴'} {amt:,}g"
            row.append(InlineKeyboardButton(label,
                callback_data=f"bountyamt_{user.id}_{tu.id}_{amt}"))
            if len(row) == 2:
                buttons.append(row); row = []
        if row: buttons.append(row)
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update,
            f"🎯 *Place Bounty on {target['username']}*{rl_note}\n{fee_note}\n\n"
            f"_First player to defeat them collects the full reward. Bounties from multiple players stack!_",
            delay=45, reply_markup=markup)
        return

    # ── No reply → show help ─────────────────────────────────────────────────
    rl_tip = "\n🎯 *Railrunner advantage:* premium amounts (up to 10,000g), no fee, 3 contracts." if is_railrunner else (
             "\n🗡️ *Thief perk:* no bounty fee — place bounties for free!" if is_thief else "")
    await send_group(update,
        f"💰 *Bounty Board*\n\n"
        f"Reply to a player's message with `/bounty` to place a bounty.\n"
        f"Whoever defeats them claims the gold. Bounties from multiple players *stack*!\n"
        f"You get 25% back when yours is claimed.{rl_tip}\n\n"
        f"View active bounties: `/bounties`", delay=20)


async def bounty_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bounty amount button selection."""
    query = update.callback_query
    parts = query.data.split("_", 3)  # bountyamt_{placer}_{target}_{amount}
    try:
        placer_uid = int(parts[1]); target_uid = int(parts[2]); amount = int(parts[3])
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != placer_uid:
        await query.answer("This isn't your bounty!", show_alert=True); return

    await query.answer()
    p = get_player(placer_uid); target = get_player(target_uid)
    if not p or not target:
        await query.edit_message_text("Player not found."); return

    _, _, no_fee, _, max_contracts = _bounty_class_perks(p)

    if not no_fee and p.get("gold", 0) < amount:
        await query.edit_message_text(
            f"❌ Not enough gold! Need *{amount}g*, have *{p.get('gold',0)}g*.",
            parse_mode="Markdown"); return

    bconn = sqlite3.connect(DB_PATH); bconn.row_factory = sqlite3.Row; bc = bconn.cursor()
    now_iso = datetime.now().isoformat()

    # One bounty per placer per target
    existing = bc.execute(
        "SELECT reward FROM bounties WHERE target_id=? AND placer_id=? AND claimed_by IS NULL AND expires_at > ?",
        (target_uid, placer_uid, now_iso)).fetchone()
    if existing:
        bconn.close()
        await query.edit_message_text(
            f"❌ You already have a *{existing['reward']}g* bounty on *{target['username']}*.",
            parse_mode="Markdown"); return

    # Railrunner contract cap
    total_active = bc.execute(
        "SELECT COUNT(*) FROM bounties WHERE placer_id=? AND claimed_by IS NULL AND expires_at > ?",
        (placer_uid, now_iso)).fetchone()[0]
    if total_active >= max_contracts:
        bconn.close()
        await query.edit_message_text(
            f"⚠️ You've hit your active contract limit ({max_contracts}).",
            parse_mode="Markdown"); return

    expires = (datetime.now() + timedelta(hours=24)).isoformat()
    bc.execute("INSERT INTO bounties (placer_id,target_id,reward,expires_at) VALUES (?,?,?,?)",
               (placer_uid, target_uid, amount, expires))
    bconn.commit(); bconn.close()

    if not no_fee:
        p["gold"] = p.get("gold", 0) - amount
        save_player(p)
        cost_line = f"_(−{amount}g from your wallet)_"
    else:
        cost_line = "_(No cost — class perk!)_"

    await query.edit_message_text(
        f"🎯 *BOUNTY PLACED!*\n\n"
        f"Target: *{target['username']}*\n"
        f"Reward: *{amount:,}g* — expires in 24 hours\n{cost_line}\n\n"
        f"_First to defeat them collects it. Others can stack more bounties on top!_",
        parse_mode="Markdown")
    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"🎯 *{p['username']}* placed a *{amount:,}g bounty* on your head!\n"
                 "Watch your back — anyone who defeats you claims it.",
            parse_mode="Markdown")
    except Exception: pass

async def bounties_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT b.*, p.username as target_name, p2.username as placer_name "
        "FROM bounties b "
        "LEFT JOIN players p  ON b.target_id  = p.user_id "
        "LEFT JOIN players p2 ON b.placer_id  = p2.user_id "
        "WHERE b.claimed_by IS NULL AND b.expires_at > ? "
        "ORDER BY b.reward DESC LIMIT 10",
        (datetime.now().isoformat(),)).fetchall()
    conn.close()

    if not rows:
        await send_group(update, "💰 *Bounty Board*\n\n_No active bounties right now._", delay=15)
        return

    # Check which placers are Railrunners
    placer_ids = [row["placer_id"] for row in rows]
    railrunner_ids = set()
    if placer_ids:
        rconn = sqlite3.connect(DB_PATH); rconn.row_factory = sqlite3.Row
        for row in rconn.execute(
            f"SELECT user_id FROM players WHERE class_id='bounty_hunter' AND user_id IN ({','.join('?'*len(placer_ids))})",
            placer_ids).fetchall():
            railrunner_ids.add(row["user_id"])
        rconn.close()

    lines = ["💰 *Bounty Board* — Active Contracts\n"]
    for i, row in enumerate(rows, 1):
        target_name = row["target_name"] or "Unknown"
        placer_name = row["placer_name"] or "Unknown"
        star = "⭐ " if row["placer_id"] in railrunner_ids else ""
        lines.append(f"{i}. {star}🎯 *{target_name}* — *{row['reward']}g*\n   _Posted by {placer_name}_")
    lines.append("\n⭐ = Railrunner contract (professional bounty hunter)")

    await send_group(update, "\n".join(lines), delay=30)

# ── CHANGELOG ─────────────────────────────────────────────────────────────────
async def changelog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    entries = CHANGELOG[-3:]  # Last 3 versions
    lines = [f"📋 *8Ball World  -  Recent Updates*\n"]
    for entry in reversed(entries):
        lines.append(f"*{entry['version']}* _{entry['date']}_")
        for c in entry["changes"]:
            lines.append(f"• {c}")
        lines.append("")
    try:
        await context.bot.send_message(
            chat_id=user.id, text="\n".join(lines), parse_mode="Markdown")
        if update.effective_chat.id != user.id:
            await send_group(update, "📬 Changelog sent to your DM!", delay=10)
    except Exception:
        await send_group(update, "\n".join(lines), delay=40)

# ── REINFORCE ─────────────────────────────────────────────────────────────────
async def reinforce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    args = context.args or []

    # /reinforce ascend [item name]
    if args and args[0].lower() == "ascend":
        item_typed = " ".join(args[1:]).strip()
        if not item_typed:
            await send_group(update,
                "Usage: `/reinforce ascend [item name]`\n"
                "Ascend an item that has reached 20 reinforces.", delay=15)
            return
        inv = json.loads(p.get("inventory") or "[]")
        equipped_slots = [p.get("equipped_weapon"), p.get("equipped_armor"),
                          p.get("equipped_shield"), p.get("equipped_accessory")]
        item_name = resolve_item_ci(item_typed, inv) or resolve_item_ci(item_typed, [s for s in equipped_slots if s])
        if not item_name:
            await send_group(update, f"❌ *{item_typed}* not found in your inventory or equipped slots.", delay=10)
            return
        rd = get_reinforce_data(p)
        entry = rd.get(item_name, {"r": 0, "s": 0})
        if entry["r"] < 20:
            await send_group(update,
                f"❌ *{item_name}* needs 20 reinforces before it can ascend. "
                f"Currently at *{entry['r']}/20*.", delay=12)
            return
        if entry["s"] >= 3:
            await send_group(update,
                f"⭐ *{item_name}* is already at maximum ascension (★★★)! "
                "It can be reinforced up to 20 more times.", delay=12)
            return
        entry["s"] += 1
        entry["r"]  = 0
        rd[item_name] = entry
        set_reinforce_data(p, rd)
        p["total_ascensions"] = safe_int(p.get("total_ascensions")) + 1
        new_titles = check_titles(p)
        save_player(p)
        title_line = "\n".join(f"🏅 New title: *{t}*!" for t in new_titles)
        await send_group(update,
            f"🌟 *ASCENSION!*\n\n"
            f"*{item_name}* → {star_str(entry['s'])}\n"
            f"+5 permanent ATK/DEF bonus per star!\n"
            f"Reinforces reset to 0/20 — keep grinding!\n"
            + (f"\n{title_line}" if title_line else ""), delay=25)
        return

    # /reinforce [item name]
    if not args:
        uid = user.id
        inv = sjl(p.get("inventory"), [])
        inv_ctr = Counter(inv)
        rd = get_reinforce_data(p)
        rf_buttons = []
        asc_buttons = []

        for item, count in inv_ctr.items():
            if item not in WEAPONS and item not in ARMORS and item not in SHIELDS:
                continue
            entry = rd.get(item, {"r": 0, "s": 0})
            pool = WEAPONS if item in WEAPONS else (ARMORS if item in ARMORS else SHIELDS)
            rarity = RARITY_EMOJI.get(pool[item].get("rarity",""), "⚪")
            stars = star_str(entry["s"]) if entry["s"] else ""
            if entry["r"] >= 20:
                if entry["s"] < 3:
                    asc_buttons.append([InlineKeyboardButton(
                        f"⭐ Ascend {rarity}{item} {stars} → {star_str(entry['s']+1)}",
                        callback_data=f"rfasc_{uid}_{item}")])
            elif count >= 2:
                rf_buttons.append([InlineKeyboardButton(
                    f"⚒️ Reinforce {rarity}{item} {stars} [{entry['r']}/20] (x{count})",
                    callback_data=f"rf_{uid}_{item}")])

        all_buttons = rf_buttons + asc_buttons
        if not all_buttons:
            await send_group(update,
                "⚒️ *Reinforce*\n\n"
                "Need *2 copies* of the same weapon, armor, or shield.\n"
                "• Each reinforce: *+1 ATK or DEF*\n"
                "• 20 reinforces → Ascend for *+5 per ★*\n"
                "_Collect duplicate drops from raids and bosses!_", delay=20)
            return
        markup = InlineKeyboardMarkup(all_buttons)
        await send_group(update, "⚒️ *Reinforce — Choose an item:*", delay=60, reply_markup=markup)
        return

    item_typed = " ".join(args).strip()
    inv = json.loads(p.get("inventory") or "[]")
    item_name = resolve_item_ci(item_typed, list(WEAPONS) + list(ARMORS) + list(SHIELDS)) or item_typed
    count = inv.count(item_name)

    # Check if it's a valid reinforceable item
    if item_name not in WEAPONS and item_name not in ARMORS and item_name not in SHIELDS:
        await send_group(update,
            f"❌ *{item_name}* cannot be reinforced. Only weapons, armors, and shields can be reinforced.", delay=12)
        return

    if count < 2:
        rd = get_reinforce_data(p)
        entry = rd.get(item_name, {"r": 0, "s": 0})
        await send_group(update,
            f"❌ You need *at least 2 copies* of *{item_name}* to reinforce.\n"
            f"You have: *{count}* copy(s).\n"
            f"Current: {star_str(entry['s'])} [{entry['r']}/20 reinforces]", delay=15)
        return

    rd = get_reinforce_data(p)
    entry = rd.get(item_name, {"r": 0, "s": 0})

    if entry["r"] >= 20:
        await send_group(update,
            f"⭐ *{item_name}* is maxed at 20 reinforces!\n"
            f"Use `/reinforce ascend {item_name}` to ascend it to {star_str(entry['s']+1)}.", delay=15)
        return

    # Consume one copy
    inv.remove(item_name)
    p["inventory"] = json.dumps(inv)
    entry["r"] += 1
    rd[item_name] = entry
    set_reinforce_data(p, rd)
    p["total_reinforces"] = safe_int(p.get("total_reinforces")) + 1
    new_titles = check_titles(p)
    save_player(p)

    bonus_total = entry["r"] + entry["s"] * 5
    slot_type = "ATK" if item_name in WEAPONS else "DEF"
    title_line = "\n".join(f"🏅 New title: *{t}*!" for t in new_titles)
    ready_to_ascend = entry["r"] == 20

    msg = (
        f"⚒️ *Reinforced!*\n\n"
        f"*{item_name}* {star_str(entry['s'])}\n"
        f"Reinforces: *{entry['r']}/20*\n"
        f"Total {slot_type} bonus: *+{bonus_total}*\n"
        f"1 copy consumed from inventory."
    )
    if ready_to_ascend:
        msg += f"\n\n⭐ *Max reinforces reached!* Use `/reinforce ascend {item_name}` to ascend!"
    if title_line:
        msg += f"\n\n{title_line}"
    await send_group(update, msg, delay=20)

async def reinforce_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reinforce button: rf_{uid}_{item_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid       = int(parts[1])
        item_name = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your reinforce menu!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    if inv.count(item_name) < 2:
        await query.answer(f"Need 2 copies of {item_name}!", show_alert=True); return
    if item_name not in WEAPONS and item_name not in ARMORS and item_name not in SHIELDS:
        await query.answer("That item cannot be reinforced!", show_alert=True); return
    rd = get_reinforce_data(p)
    entry = rd.get(item_name, {"r": 0, "s": 0})
    if entry["r"] >= 20:
        await query.answer(f"{item_name} is maxed at 20 reinforces! Use Ascend.", show_alert=True); return
    await query.answer()
    inv.remove(item_name)
    p["inventory"] = json.dumps(inv)
    entry["r"] += 1
    rd[item_name] = entry
    set_reinforce_data(p, rd)
    p["total_reinforces"] = safe_int(p.get("total_reinforces")) + 1
    check_titles(p); save_player(p)
    bonus_total = entry["r"] + entry["s"] * 5
    slot_type = "ATK" if item_name in WEAPONS else "DEF"
    msg = (
        f"⚒️ *Reinforced!*\n\n"
        f"*{item_name}* {star_str(entry['s']) if entry['s'] else ''}\n"
        f"Reinforces: *{entry['r']}/20*\n"
        f"Total {slot_type} bonus: *+{bonus_total}*\n"
        f"1 copy consumed from inventory."
    )
    if entry["r"] == 20:
        msg += f"\n\n⭐ *Max reinforces!* Tap /reinforce again to Ascend!"
    await query.edit_message_text(msg, parse_mode="Markdown")

async def reinforce_asc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ascend button: rfasc_{uid}_{item_name}"""
    query = update.callback_query
    parts = query.data.split("_", 2)
    try:
        uid       = int(parts[1])
        item_name = parts[2]
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("Not your reinforce menu!", show_alert=True); return
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    rd = get_reinforce_data(p)
    entry = rd.get(item_name, {"r": 0, "s": 0})
    if entry["r"] < 20:
        await query.answer(f"Need 20 reinforces first! Currently {entry['r']}/20.", show_alert=True); return
    if entry["s"] >= 3:
        await query.answer(f"{item_name} is already at max ★★★ ascension!", show_alert=True); return
    await query.answer()
    entry["s"] += 1; entry["r"] = 0
    rd[item_name] = entry
    set_reinforce_data(p, rd)
    p["total_ascensions"] = safe_int(p.get("total_ascensions")) + 1
    check_titles(p); save_player(p)
    await query.edit_message_text(
        f"🌟 *ASCENSION!*\n\n"
        f"*{item_name}* → {star_str(entry['s'])}\n"
        f"+5 permanent ATK/DEF bonus per star!\n"
        f"Reinforces reset to 0/20 — keep grinding!",
        parse_mode="Markdown")

# ── OBJECTIVES ────────────────────────────────────────────────────────────────
async def objectives_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    refresh_daily_objectives(p)
    save_player(p)

    objs = json.loads(p.get("daily_objectives") or "[]")
    total_done = safe_int(p.get("total_obj_completed"))
    lines = ["📋 *Daily Objectives*\n_Reset each day at midnight_\n"]
    for obj in objs:
        prog  = obj["progress"]
        tgt   = obj["target"]
        done  = obj.get("done", False)
        bar   = "█" * prog + "░" * (tgt - prog)
        check = "✅" if done else "🔲"
        reward = f"+{obj['reward_exp']} EXP, +{obj['reward_gold']}g"
        lines.append(
            f"{check} *{obj['desc']}*\n"
            f"   Progress: {bar} ({prog}/{tgt})\n"
            f"   Reward: _{reward}_"
        )
    lines.append(f"\n📊 Total objectives completed: *{total_done}*")
    await send_group(update, "\n\n".join(lines), delay=40)

# ── DUEL ──────────────────────────────────────────────────────────────────────
def calc_combat_power(p):
    stat_total = sum(get_stat(p, st) for st in ["STR","AGI","INT","WIS","DEX","LUK"])
    weapon_val = get_weapon_atk(p) * 3
    armor_val  = get_armor_def(p) * 2
    level_val  = p["level"] * 10
    skill_count = len(sjl(p.get("all_skills"), []))
    skill_val   = skill_count * 50
    enchant_count = len([1 for sk in ["equipped_weapon","equipped_armor",
                                      "equipped_shield","equipped_accessory"]
                         if get_enchant(p, p.get(sk) or "")])
    enchant_val = enchant_count * 30
    return level_val + stat_total + weapon_val + armor_val + skill_val + enchant_val

def calc_dungeon_cp(p):
    sd = safe_stats(p)
    return (p["level"] * 8
            + sum(sd.values())
            + get_weapon_atk(p) * 3
            + get_armor_def(p) * 2
            + len(sjl(p.get("all_skills"),[])) * 30)

# ── MARRIAGE ─────────────────────────────────────────────────────────────────
async def marry_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    # Show own marriage status if no target
    if not update.message.reply_to_message and not context.args:
        if p.get("married_to_id") and p.get("married_to_name"):
            ma = p.get("married_at","unknown date")
            await send_group(update,
                f"💍 *Married to {p['married_to_name']}*\n"
                f"_Since {ma[:10] if ma else '?'}_\n\n"
                f"Use /divorce to end the marriage.", delay=30); return
        await send_group(update,
            "💍 *Marriage*\n\n"
            "Reply to someone's message and type /marry to propose!\n"
            "Costs *1,000 gold* each. Benefits:\n"
            "• 💍 Shown on your /stats profile\n"
            "• 🏅 Exclusive *Beloved* title\n"
            "• ✨ +3% EXP bonus on all gains\n\n"
            "_Both partners must agree._", delay=30); return

    du = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not du:
        await send_group(update, "Reply to the person you want to propose to!", delay=9); return
    if du.id == user.id:
        await send_group(update, "You can't marry yourself!", delay=9); return

    tp = get_player(du.id)
    if not tp:
        await send_group(update, f"{du.first_name} hasn't ascended yet!", delay=9); return

    if p.get("married_to_id"):
        await send_group(update, f"💍 You're already married to *{p.get('married_to_name')}*! Use /divorce first.", delay=12); return
    if tp.get("married_to_id"):
        await send_group(update, f"💔 {du.first_name} is already married!", delay=12); return
    if p.get("gold", 0) < 1000:
        await send_group(update, "💰 You need at least *1,000 gold* to propose!", delay=9); return

    # Send proposal
    pending_marriages[user.id] = {
        "target_id": du.id,
        "chat_id": update.effective_chat.id,
        "expires": (datetime.now() + timedelta(minutes=5)).isoformat(),
    }
    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("💍 Accept",  callback_data=f"marry_accept_{user.id}"),
        InlineKeyboardButton("💔 Decline", callback_data=f"marry_decline_{user.id}"),
    ]])
    await send_group(update,
        f"💍 *{user.first_name}* proposes to *{du.first_name}*!\n\n"
        f"_{du.first_name}, will you accept?_\n"
        f"Cost: 1,000 gold each (2,000 total)\n\n"
        f"_Proposal expires in 5 minutes._",
        permanent=False, delay=300, reply_markup=markup)


async def marry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]          # accept or decline
    proposer_id = int(parts[2])

    proposal = pending_marriages.get(proposer_id)
    if not proposal:
        await query.edit_message_text("💔 This proposal has already expired.", parse_mode="Markdown"); return
    if datetime.now() > datetime.fromisoformat(proposal["expires"]):
        pending_marriages.pop(proposer_id, None)
        await query.edit_message_text("💔 This proposal has expired.", parse_mode="Markdown"); return
    if query.from_user.id != proposal["target_id"]:
        await query.answer("This proposal isn't for you!", show_alert=True); return

    pending_marriages.pop(proposer_id, None)
    proposer = get_player(proposer_id)
    target   = get_player(proposal["target_id"])

    if action == "decline":
        await query.edit_message_text(
            f"💔 *{query.from_user.first_name}* declined the proposal.",
            parse_mode="Markdown"); return

    # Accept — validate
    if not proposer or not target:
        await query.edit_message_text("❌ Player data not found.", parse_mode="Markdown"); return
    if proposer.get("married_to_id") or target.get("married_to_id"):
        await query.edit_message_text("💔 One of you is already married.", parse_mode="Markdown"); return
    if proposer.get("gold", 0) < 1000:
        await query.edit_message_text("💰 The proposer no longer has enough gold!", parse_mode="Markdown"); return
    if target.get("gold", 0) < 1000:
        await query.edit_message_text("💰 You don't have enough gold (need 1,000)!", parse_mode="Markdown"); return

    now_str = datetime.now().isoformat()
    # Deduct gold, link records
    proposer["gold"] -= 1000;  target["gold"] -= 1000
    proposer["married_to_id"]   = target["user_id"]
    proposer["married_to_name"] = target["username"]
    proposer["married_at"]      = now_str
    target["married_to_id"]     = proposer["user_id"]
    target["married_to_name"]   = proposer["username"]
    target["married_at"]        = now_str
    award_title(proposer, "Beloved"); award_title(target, "Beloved")
    save_player(proposer); save_player(target)

    await query.edit_message_text(
        f"💍 *{proposer['username']}* and *{target['username']}* are now married!\n\n"
        f"🏅 Both received the *Beloved* title.\n"
        f"✨ +3% EXP bonus active for both.\n\n"
        f"_Congratulations!_ 🎉",
        parse_mode="Markdown")


async def divorce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not p.get("married_to_id"):
        await send_group(update, "💔 You're not married.", delay=9); return

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm Divorce", callback_data=f"divorce_confirm_{user.id}"),
        InlineKeyboardButton("❌ Cancel",          callback_data=f"divorce_cancel_{user.id}"),
    ]])
    await send_group(update,
        f"💔 Are you sure you want to divorce *{p['married_to_name']}*?\n\n"
        f"_This removes the Beloved title and EXP bonus for both of you._",
        permanent=False, delay=60, reply_markup=markup)


async def divorce_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action = parts[1]  # confirm or cancel
    uid    = int(parts[2])
    if query.from_user.id != uid:
        await query.answer("This isn't your divorce!", show_alert=True); return

    if action == "cancel":
        await query.edit_message_text("_Divorce cancelled._", parse_mode="Markdown"); return

    p = get_player(uid)
    if not p or not p.get("married_to_id"):
        await query.edit_message_text("💔 You are not currently married.", parse_mode="Markdown"); return

    spouse = get_player(p["married_to_id"])
    spouse_name = p["married_to_name"]

    p["married_to_id"] = None; p["married_to_name"] = None; p["married_at"] = None
    save_player(p)
    if spouse:
        spouse["married_to_id"] = None; spouse["married_to_name"] = None; spouse["married_at"] = None
        save_player(spouse)

    await query.edit_message_text(
        f"💔 *{p['username']}* and *{spouse_name}* are now divorced.\n\n"
        f"_The Beloved title and EXP bonus have been removed._",
        parse_mode="Markdown")


async def duel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated  -  can't duel!", delay=9); return

    # Reply-to-message shortcut: replying to a challenge message counts as /duel accept
    if update.message.reply_to_message and (not context.args or context.args[0].lower() != "accept"):
        replied_uid = update.message.reply_to_message.from_user.id
        if replied_uid != user.id:
            duel_check = pending_duels.get(replied_uid)
            if duel_check and duel_check["target_id"] == user.id and duel_check["chat_id"] == chat_id:
                if datetime.now() < datetime.fromisoformat(duel_check["expires"]):
                    context.args = ["accept"]
                else:
                    pending_duels.pop(replied_uid, None)
                    await send_group(update, "⏰ That duel challenge has already expired.", delay=9)
                    return

    if context.args and context.args[0].lower() == "accept":
        duel = None; challenger_id = None
        for cid, d in list(pending_duels.items()):
            if d["target_id"] == user.id and d["chat_id"] == chat_id:
                if datetime.now() < datetime.fromisoformat(d["expires"]):
                    duel = d; challenger_id = cid; break
                else:
                    pending_duels.pop(cid, None)
        if not duel:
            await send_group(update, "No pending duel challenge for you!", delay=9); return
        challenger = get_player(challenger_id)
        if not challenger:
            pending_duels.pop(challenger_id, None)
            await send_group(update, "Challenger not found.", delay=9); return
        wager = duel["wager"]
        if wager > 0 and p["gold"] < wager:
            await send_group(update,
                f"❌ You need {wager}g for the wager. Have {p['gold']}g.", delay=9); return
        if wager > 0 and challenger["gold"] < wager:
            pending_duels.pop(challenger_id, None)
            await send_group(update, "Challenger can no longer afford the wager.", delay=9); return
        pending_duels.pop(challenger_id, None)
        # Deduct wager from both players upfront, then award wager*2 to winner
        if wager > 0:
            p["gold"]          = max(0, p.get("gold", 0) - wager)
            challenger["gold"] = max(0, challenger.get("gold", 0) - wager)
        cp_a = calc_combat_power(challenger)
        cp_b = calc_combat_power(p)
        total = cp_a + cp_b
        winner = challenger if random.random() < (cp_a / total) else p
        loser  = p if winner["user_id"] == challenger["user_id"] else challenger
        if wager > 0:
            winner["gold"] = winner.get("gold",0) + wager * 2
        winner["wins"] = winner.get("wins",0) + 1
        save_player(winner); save_player(loser)
        lines = [
            f"⚔️ *DUEL  -  {challenger['username']} vs {p['username']}*",
            f"━━━━━━━━━━━━━━━━",
            f"🔢 {challenger['username']} CP: *{cp_a:,}*",
            f"🔢 {p['username']} CP: *{cp_b:,}*",
            f"━━━━━━━━━━━━━━━━",
        ]
        advantage = abs(cp_a - cp_b)
        if advantage < total * 0.05:
            lines.append("⚡ *Perfectly matched!* It could have gone either way...")
        elif winner["user_id"] == challenger["user_id"]:
            lines.append(f"📈 {challenger['username']} had the edge  -  *{cp_a - cp_b:,} CP advantage!*")
        else:
            lines.append(f"📈 {p['username']} had the edge  -  *{cp_b - cp_a:,} CP advantage!*")
        lines.append(f"\n🏆 *{winner['username']}* wins the duel!")
        if wager > 0:
            lines.append(f"💰 +{wager}g collected from {loser['username']}.")
        await send_group(update, "\n".join(lines), permanent=False, delay=60)
        return

    if not update.message.reply_to_message:
        await send_group(update,
            "Reply to a player's message to challenge them!\n"
            "`/duel`  -  pick wager via buttons\n"
            "`/duel 500`  -  duel with 500g wager", delay=9); return
    du = update.message.reply_to_message.from_user
    if du.id == user.id:
        await send_group(update, "Can't duel yourself!", delay=9); return
    tp = get_player(du.id)
    if not tp:
        await send_group(update, f"{du.first_name} hasn't ascended yet!", delay=9); return
    if is_defeated(tp):
        await send_group(update, f"{tp['username']} is currently defeated — can't duel them.", delay=9); return
    # Show wager buttons when no amount typed
    if not context.args:
        cp_self = calc_combat_power(p)
        cp_them = calc_combat_power(tp)
        wagers = [0, 100, 500, 1000, 5000]
        buttons = []
        row = []
        for w in wagers:
            can_afford = p.get("gold", 0) >= w
            label = "⚔️ Free Duel" if w == 0 else f"{'✅' if can_afford else '🔴'} {w:,}g wager"
            row.append(InlineKeyboardButton(label,
                callback_data=f"duelwager_{user.id}_{du.id}_{w}"))
            if len(row) == 2 or w == 0:
                buttons.append(row); row = []
        if row: buttons.append(row)
        markup = InlineKeyboardMarkup(buttons)
        await send_group(update,
            f"⚔️ *Duel Challenge — {p['username']} vs {tp['username']}*\n\n"
            f"Your CP: *{cp_self:,}*  |  Their CP: *{cp_them:,}*\n\n"
            f"Pick a wager amount:",
            delay=60, reply_markup=markup)
        return
    wager = 0
    if context.args:
        try: wager = max(0, int(context.args[0]))
        except: pass
    if wager > 0 and p["gold"] < wager:
        await send_group(update,
            f"❌ Need {wager}g for this wager. Have {p['gold']}g.", delay=9); return
    pending_duels[user.id] = {
        "target_id": du.id, "wager": wager,
        "chat_id": chat_id,
        "expires": (datetime.now() + timedelta(minutes=5)).isoformat()
    }
    cp_self = calc_combat_power(p)
    wager_str = f" for *{wager}g*" if wager > 0 else " (no wager)"
    duel_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"duel_acc_{user.id}_{du.id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"duel_dec_{user.id}_{du.id}"),
    ]])
    await send_group(update,
        f"⚔️ *{user.first_name}* challenges *{du.first_name}* to a duel{wager_str}!\n\n"
        f"🔢 {user.first_name}'s CP: *{cp_self:,}*\n\n"
        f"_{du.first_name}: tap Accept/Decline or type `/duel accept`. Expires in 5 minutes._",
        permanent=False, delay=60, reply_markup=duel_markup)

async def duel_wager_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle duel wager selection button."""
    query = update.callback_query
    parts = query.data.split("_", 3)  # duelwager_{challenger}_{target}_{wager}
    try:
        challenger_uid = int(parts[1]); target_uid = int(parts[2]); wager = int(parts[3])
    except (IndexError, ValueError):
        await query.answer(); return
    if query.from_user.id != challenger_uid:
        await query.answer("This isn't your duel!", show_alert=True); return
    await query.answer()

    p  = get_player(challenger_uid)
    tp = get_player(target_uid)
    if not p or not tp:
        await query.edit_message_text("Player not found."); return
    if is_defeated(tp):
        await query.edit_message_text(f"{tp['username']} is now defeated — can't duel them."); return
    if wager > 0 and p.get("gold", 0) < wager:
        await query.edit_message_text(
            f"❌ Not enough gold! Need *{wager:,}g*, have *{p.get('gold',0):,}g*.",
            parse_mode="Markdown"); return

    chat_id = query.message.chat_id
    pending_duels[challenger_uid] = {
        "target_id": target_uid, "wager": wager,
        "chat_id": chat_id,
        "expires": (datetime.now() + timedelta(minutes=5)).isoformat()
    }
    cp_self = calc_combat_power(p)
    wager_str = f" for *{wager:,}g*" if wager > 0 else " (no wager)"
    duel_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"duel_acc_{challenger_uid}_{target_uid}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"duel_dec_{challenger_uid}_{target_uid}"),
    ]])
    await query.edit_message_text(
        f"⚔️ *{p['username']}* challenges *{tp['username']}* to a duel{wager_str}!\n\n"
        f"🔢 {p['username']}'s CP: *{cp_self:,}*\n\n"
        f"_{tp['username']}: tap Accept/Decline or type `/duel accept`. Expires in 5 minutes._",
        parse_mode="Markdown", reply_markup=duel_markup)


async def duel_response_callback(update, context):
    """Handle duel Accept/Decline button presses."""
    query = update.callback_query
    await query.answer()
    data = query.data  # duel_acc_{challenger_uid}_{target_uid} or duel_dec_...
    parts = data.split("_")
    # parts: ['duel','acc'/'dec', challenger_uid, target_uid]
    if len(parts) < 4:
        return
    action = parts[1]  # 'acc' or 'dec'
    try:
        challenger_uid = int(parts[2])
        target_uid     = int(parts[3])
    except (ValueError, IndexError):
        return

    if query.from_user.id != target_uid:
        await query.answer("This duel challenge isn't for you!", show_alert=True)
        return

    if action == "dec":
        pending_duels.pop(challenger_uid, None)
        try:
            await query.edit_message_text("❌ Duel declined.", parse_mode="Markdown")
        except Exception:
            pass
        return

    # action == "acc" — run the accept logic
    duel = pending_duels.get(challenger_uid)
    if not duel:
        await query.answer("No pending duel found!", show_alert=True)
        return
    if duel["target_id"] != target_uid:
        await query.answer("This duel challenge isn't for you!", show_alert=True)
        return
    if datetime.now() > datetime.fromisoformat(duel["expires"]):
        pending_duels.pop(challenger_uid, None)
        await query.answer("Duel challenge has expired!", show_alert=True)
        return

    p = get_player(target_uid)
    challenger = get_player(challenger_uid)
    if not p or not challenger:
        await query.answer("Player data not found!", show_alert=True)
        return

    wager = duel["wager"]
    if wager > 0 and p.get("gold", 0) < wager:
        await query.answer(f"You need {wager}g for the wager!", show_alert=True)
        return
    if wager > 0 and challenger.get("gold", 0) < wager:
        pending_duels.pop(challenger_uid, None)
        await query.answer("Challenger can no longer afford the wager!", show_alert=True)
        return

    pending_duels.pop(challenger_uid, None)
    # Deduct wager from both players upfront, then award wager*2 to winner
    if wager > 0:
        p["gold"]          = max(0, p.get("gold", 0) - wager)
        challenger["gold"] = max(0, challenger.get("gold", 0) - wager)
    cp_a = calc_combat_power(challenger)
    cp_b = calc_combat_power(p)
    total = cp_a + cp_b
    winner = challenger if random.random() < (cp_a / total) else p
    loser  = p if winner["user_id"] == challenger["user_id"] else challenger
    if wager > 0:
        winner["gold"] = winner.get("gold",0) + wager * 2
    winner["wins"] = winner.get("wins",0) + 1
    save_player(winner); save_player(loser)
    lines = [
        f"⚔️ *DUEL  -  {challenger['username']} vs {p['username']}*",
        f"━━━━━━━━━━━━━━━━",
        f"🔢 {challenger['username']} CP: *{cp_a:,}*",
        f"🔢 {p['username']} CP: *{cp_b:,}*",
        f"━━━━━━━━━━━━━━━━",
    ]
    advantage = abs(cp_a - cp_b)
    if advantage < total * 0.05:
        lines.append("⚡ *Perfectly matched!* It could have gone either way...")
    elif winner["user_id"] == challenger["user_id"]:
        lines.append(f"📈 {challenger['username']} had the edge  -  *{cp_a - cp_b:,} CP advantage!*")
    else:
        lines.append(f"📈 {p['username']} had the edge  -  *{cp_b - cp_a:,} CP advantage!*")
    lines.append(f"\n🏆 *{winner['username']}* wins the duel!")
    if wager > 0:
        lines.append(f"💰 +{wager}g collected from {loser['username']}.")
    result_text = "\n".join(lines)
    try:
        await query.edit_message_text(text=result_text[:4096], parse_mode="Markdown")
    except Exception:
        try:
            await query.get_bot().send_message(
                chat_id=duel.get("chat_id", query.message.chat.id),
                text=result_text[:4096], parse_mode="Markdown")
        except Exception:
            pass

# ── ARENA ─────────────────────────────────────────────────────────────────────
def _arena_state():
    return {
        "atk_mod": 1.0, "def_mod": 1.0,
        "dot_type": None, "dot_dmg": 0, "dot_turns": 0,
        "acc_debuff": False, "acc_debuff_pct": 0.0,
        "charge_ready": False, "charge_mult": 1.0,
        "shield_turns": 0, "shield_pct": 0.0,
        "buff_turns": 0, "debuff_turns": 0,
        "taunt": False, "skip_turns": 0,
        "heal_block_turns": 0, "bind_turns": 0,
        "skill_block_turns": 0,
        "regen_hp": 0, "regen_turns": 0,
        "reflect_on_hit": 0, "reflect_turns": 0,
        "reflect_dot": 0, "reflect_dot_turns": 0,
        "next_atk_bonus": 1.0,
        "amplify_pct": 1.0,
        "miss_next_enemy": False,
        "ambush_bonus": 1.0,
        "mark_bonus": 1.0, "mark_attacks": 0,
        "extra_dmg_per_hit": 0, "extra_dmg_turns": 0,
    }

def build_arena_card(arena):
    p1 = arena["p1"]; p2 = arena["p2"]
    hp1 = arena["p1_hp"]; hp2 = arena["p2_hp"]
    max1 = arena["p1_max"]; max2 = arena["p2_max"]
    def bar(hp, mx, length=8):
        pct = hp / max(1, mx)
        filled = round(pct * length)
        return "█" * filled + "░" * (length - filled)
    turn_name = p1["username"] if arena["turn"] == arena["p1_id"] else p2["username"]
    lines = [
        f"🎪 *ARENA  -  Round {arena['round']}*",
        f"━━━━━━━━━━━━━━━━",
        f"⚔️ {p1['username']} [{bar(hp1,max1)}] {hp1}/{max1} HP",
        f"⚔️ {p2['username']} [{bar(hp2,max2)}] {hp2}/{max2} HP",
        f"━━━━━━━━━━━━━━━━",
    ]
    if arena["status"] == "done":
        winner = p1["username"] if hp1 > 0 else p2["username"]
        lines.append(f"🏆 *{winner} WINS!*")
    else:
        lines.append(f"⏳ *{turn_name}'s turn*")
        lines.append("Use `/arena attack`, `/arena skill [1/name]`, or `/arena item [name]`")
    for entry in arena["log"][-5:]:
        lines.append(f"  {entry}")
    return "\n".join(lines)

def build_arena_markup(arena, chat_id):
    """Return InlineKeyboardMarkup for the current player's turn, or None if done."""
    if arena["status"] == "done":
        return None
    uid = arena["turn"]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"arena_act_{chat_id}_{uid}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"arena_act_{chat_id}_{uid}_skl"),
        InlineKeyboardButton("🏃 Flee",   callback_data=f"arena_act_{chat_id}_{uid}_flee"),
    ]])

async def arena_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p): await send_group(update, _defeated_msg(p), delay=15); return

    # Reply-to-message shortcut: replying to a challenge message counts as /arena accept
    if update.message.reply_to_message and (not context.args or context.args[0].lower() != "accept"):
        replied_uid = update.message.reply_to_message.from_user.id
        if replied_uid != user.id:
            arena_check = active_arenas.get(chat_id)
            if (arena_check
                    and arena_check["status"] == "waiting"
                    and arena_check["p1_id"] == replied_uid
                    and arena_check["p2_id"] == user.id):
                if datetime.now() < datetime.fromisoformat(arena_check["expires"]):
                    context.args = ["accept"]
                else:
                    active_arenas.pop(chat_id, None)
                    await send_group(update, "⏰ That arena challenge has already expired.", delay=9)
                    return

    # /arena accept
    if context.args and context.args[0].lower() == "accept":
        arena = active_arenas.get(chat_id)
        if not arena or arena["status"] != "waiting":
            await send_group(update, "No pending arena challenge here!", delay=9); return
        if arena["p2_id"] != user.id:
            await send_group(update, "This challenge isn't for you!", delay=9); return
        if datetime.now() > datetime.fromisoformat(arena["expires"]):
            active_arenas.pop(chat_id, None)
            await send_group(update, "Challenge expired.", delay=9); return
        wager = arena["wager"]
        if wager > 0 and p["gold"] < wager:
            await send_group(update, f"❌ Need {wager}g. Have {p['gold']}g.", delay=9); return
        p1 = get_player(arena["p1_id"])
        if not p1:
            active_arenas.pop(chat_id, None); return
        if wager > 0 and p1["gold"] < wager:
            active_arenas.pop(chat_id, None)
            await send_group(update, "❌ Challenger can no longer afford the wager.", delay=9); return
        if wager > 0:
            p["gold"] = p.get("gold", 0) - wager
            p1["gold"] = p1.get("gold", 0) - wager
            save_player(p)
            save_player(p1)
        arena["p1"] = p1; arena["p2"] = p
        arena["p1_hp"]  = p1["max_hp"]; arena["p2_hp"]  = p["max_hp"]
        arena["p1_max"] = p1["max_hp"]; arena["p2_max"] = p["max_hp"]
        arena["p1_items"] = dict(Counter(sjl(p1.get("inventory"),[])))
        arena["p2_items"] = dict(Counter(sjl(p.get("inventory"),[])))
        arena["turn"]   = arena["p1_id"]
        arena["round"]  = 1
        arena["status"] = "active"
        arena["log"]    = ["⚔️ Arena battle begins!"]
        card_text = build_arena_card(arena)
        markup = build_arena_markup(arena, chat_id)
        try:
            msg = await update.get_bot().send_message(
                chat_id=chat_id, text=card_text[:4096], parse_mode="Markdown",
                reply_markup=markup)
            arena["msg_id"] = msg.message_id
        except Exception:
            arena["msg_id"] = None
        return

    # Active arena turn handling
    arena = active_arenas.get(chat_id)
    if arena and arena["status"] == "active":
        if arena["turn"] != user.id:
            await send_group(update, "It's not your turn!", delay=5); return
        is_p1 = (user.id == arena["p1_id"])
        attacker_data  = arena["p1"] if is_p1 else arena["p2"]
        defender_data  = arena["p2"] if is_p1 else arena["p1"]
        atk_hp_key     = "p1_hp" if is_p1 else "p2_hp"
        def_hp_key     = "p2_hp" if is_p1 else "p1_hp"
        atk_max_key    = "p1_max" if is_p1 else "p2_max"
        def_max_key    = "p2_max" if is_p1 else "p1_max"
        atk_items_key  = "p1_items" if is_p1 else "p2_items"
        atk_state_key  = "p1_state" if is_p1 else "p2_state"
        def_state_key  = "p2_state" if is_p1 else "p1_state"
        atk_name  = attacker_data["username"]
        def_name  = defender_data["username"]
        atk_state = arena[atk_state_key]
        def_state = arena[def_state_key]
        log_entry = ""

        # Turn-start effects for the ACTING player
        if atk_state["dot_turns"] > 0:
            arena[atk_hp_key] = max(0, arena[atk_hp_key] - atk_state["dot_dmg"])
            atk_state["dot_turns"] -= 1
            arena["log"].append(f"🩸 {atk_name} takes {atk_state['dot_dmg']} from {atk_state['dot_type']}!")
            if atk_state["dot_turns"] == 0:
                atk_state["dot_type"] = None; atk_state["dot_dmg"] = 0
        if atk_state["regen_turns"] > 0:
            arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + atk_state["regen_hp"])
            atk_state["regen_turns"] -= 1
            arena["log"].append(f"💚 {atk_name} regenerates {atk_state['regen_hp']} HP!")
        if atk_state["buff_turns"] > 0:
            atk_state["buff_turns"] -= 1
            if atk_state["buff_turns"] == 0: atk_state["atk_mod"] = 1.0
        if atk_state["debuff_turns"] > 0:
            atk_state["debuff_turns"] -= 1
            if atk_state["debuff_turns"] == 0:
                atk_state["def_mod"] = 1.0; atk_state["acc_debuff"] = False; atk_state["acc_debuff_pct"] = 0.0
        for timer_key in ["heal_block_turns","bind_turns","skill_block_turns","extra_dmg_turns"]:
            if atk_state.get(timer_key, 0) > 0:
                atk_state[timer_key] -= 1
        if atk_state.get("reflect_turns", 0) > 0:
            atk_state["reflect_turns"] -= 1
            if atk_state["reflect_turns"] == 0: atk_state["reflect_on_hit"] = 0
        if atk_state.get("reflect_dot_turns", 0) > 0:
            atk_state["reflect_dot_turns"] -= 1
            if atk_state["reflect_dot_turns"] == 0: atk_state["reflect_dot"] = 0
        if atk_state.get("skip_turns", 0) > 0:
            atk_state["skip_turns"] -= 1
            arena["log"].append(f"⚡ {atk_name} is stunned  -  turn skipped!")
            arena["turn"] = arena["p2_id"] if is_p1 else arena["p1_id"]
            arena["round"] += 1
            card_text = build_arena_card(arena)
            stun_markup = build_arena_markup(arena, chat_id)
            if arena.get("msg_id"):
                try:
                    await update.get_bot().delete_message(chat_id=chat_id, message_id=arena["msg_id"])
                except Exception: pass
            try:
                msg = await update.get_bot().send_message(
                    chat_id=chat_id, text=card_text[:4096], parse_mode="Markdown",
                    reply_markup=stun_markup)
                arena["msg_id"] = msg.message_id
            except Exception: pass
            return

        action = context.args[0].lower() if context.args else "attack"

        if atk_state.get("bind_turns", 0) > 0 and action in ("skill","item"):
            await send_group(update, "⛓️ You are bound  -  only `/arena attack` is available!", delay=5); return
        if action == "skill" and atk_state.get("skill_block_turns", 0) > 0:
            await send_group(update, "🤐 You're silenced  -  no skills this turn!", delay=5); return

        w = get_weather()
        skip_turn_after = False

        if action == "attack":
            dmg = calc_attack_damage(attacker_data, w)
            dmg = round(dmg * atk_state["atk_mod"])
            if atk_state.get("mark_attacks", 0) > 0:
                dmg = round(dmg * atk_state.get("mark_bonus", 1.0))
                atk_state["mark_attacks"] -= 1
                if atk_state["mark_attacks"] == 0: atk_state["mark_bonus"] = 1.0
            if atk_state.get("ambush_bonus", 1.0) > 1.0:
                dmg = round(dmg * atk_state["ambush_bonus"])
                atk_state["ambush_bonus"] = 1.0
                arena["log"].append(f"🌑 *Ambush!* Bonus damage!")
            if atk_state.get("next_atk_bonus", 1.0) > 1.0:
                dmg = round(dmg * atk_state["next_atk_bonus"])
                atk_state["next_atk_bonus"] = 1.0
            if atk_state.get("charge_ready"):
                dmg = round(dmg * atk_state.get("charge_mult", 2.0))
                atk_state["charge_ready"] = False; atk_state["charge_mult"] = 1.0
                arena["log"].append(f"💥 *CHARGED STRIKE!*")
            if atk_state.get("acc_debuff") and random.random() < atk_state.get("acc_debuff_pct", 0.40):
                arena["log"].append(f"😵 {atk_name} missed  -  accuracy debuffed!")
                dmg = 0
            if def_state.get("miss_next_enemy"):
                def_state["miss_next_enemy"] = False
                arena["log"].append(f"🌫️ {def_name}'s evasion causes {atk_name} to miss!")
                dmg = 0
            if dmg > 0 and check_crit(attacker_data):
                dmg = apply_crit(attacker_data, dmg)
                log_entry = f"💥 CRIT! {atk_name} hits {def_name} for *{dmg}*!"
            else:
                log_entry = f"⚔️ {atk_name} hits {def_name} for *{dmg}*." if dmg > 0 else f"🌀 {atk_name} missed!"
            if dmg > 0:
                dmg = round(dmg * def_state.get("def_mod", 1.0))
                dmg = round(dmg * def_state.get("amplify_pct", 1.0))
                if def_state.get("extra_dmg_turns", 0) > 0:
                    dmg += def_state.get("extra_dmg_per_hit", 0)
                if def_state["shield_turns"] > 0:
                    dmg = round(dmg * (1 - def_state["shield_pct"]))
                    def_state["shield_turns"] -= 1
                    if def_state["shield_turns"] == 0: def_state["shield_pct"] = 0.0
                if def_state.get("reflect_on_hit", 0) > 0 and def_state.get("reflect_turns", 0) > 0:
                    arena[atk_hp_key] = max(0, arena[atk_hp_key] - def_state["reflect_on_hit"])
                    arena["log"].append(f"⚡ {def_name} reflects {def_state['reflect_on_hit']} dmg!")
                if def_state.get("bind_turns", 0) > 0:
                    dmg = round(dmg * def_state.get("bind_dmg_mod", 1.0))
            arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)

        elif action == "skill":
            skills = sjl(attacker_data.get("all_skills"), [])
            sk = None
            if len(context.args) > 1:
                arg = " ".join(context.args[1:])
                if arg.isdigit():
                    idx = int(arg) - 1
                    if 0 <= idx < len(skills): sk = skills[idx]
                if not sk:
                    sk = next((s for s in skills if s["name"].lower() == arg.lower()), None)
            if not sk and skills:
                sk = skills[0]
            if not sk:
                await send_group(update, "No skill found.", delay=5); return
            stype = sk.get("type", "damage")
            base_dmg = calc_attack_damage(attacker_data, w)
            base_dmg = round(base_dmg * atk_state["atk_mod"])
            dmg = 0

            if stype == "atk_buff":
                atk_state["atk_mod"] = sk.get("atk_mod", 1.40)
                atk_state["buff_turns"] = sk.get("buff_turns", 3)
                log_entry = f"💪 {atk_name} uses *{sk['name']}*! ATK ×{sk.get('atk_mod',1.4)} for {sk.get('buff_turns',3)} turns."
            elif stype in ("def_buff","dmg_reduction_buff"):
                def_mod = sk.get("def_mod", 0.65)
                atk_state["def_mod"] = def_mod
                atk_state["buff_turns"] = sk.get("buff_turns", 2)
                log_entry = f"🛡️ {atk_name} uses *{sk['name']}*! Damage reduced for {sk.get('buff_turns',2)} turns."
            elif stype in ("self_heal","revive_heal"):
                if atk_state.get("heal_block_turns", 0) > 0:
                    arena["log"].append(f"🚫 {atk_name} cannot be healed!")
                    log_entry = f"🚫 {atk_name}'s healing is blocked!"
                else:
                    stat_name = sk.get("stat","WIS")
                    heal_mult = sk.get("mult", sk.get("wis_mult", 4.0))
                    heal_flat = sk.get("heal_flat", 0)
                    heal = round(get_stat(attacker_data, stat_name) * heal_mult) + heal_flat
                    arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal)
                    log_entry = f"💚 {atk_name} uses *{sk['name']}*! Restored {heal} HP."
            elif stype == "heal_shield":
                if atk_state.get("heal_block_turns", 0) <= 0:
                    stat_name = sk.get("stat","WIS")
                    heal = round(get_stat(attacker_data, stat_name) * sk.get("heal_mult", 2.0)) + sk.get("heal_flat", 0)
                    arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal)
                atk_state["shield_pct"] = sk.get("shield_pct", 0.35)
                atk_state["shield_turns"] = sk.get("shield_turns", 2)
                log_entry = f"🛡️ {atk_name} uses *{sk['name']}*! Shield + heal applied."
            elif stype == "dmg_shield":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.0))
                if def_state["shield_turns"] > 0:
                    dmg = round(dmg * (1 - def_state["shield_pct"]))
                    def_state["shield_turns"] -= 1
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                atk_state["shield_pct"] = sk.get("shield_pct", 0.30)
                atk_state["shield_turns"] = sk.get("shield_turns", 2)
                log_entry = f"⚔️🛡️ {atk_name} uses *{sk['name']}*! {dmg} dmg + shield!"
            elif stype == "stun":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.80))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if random.random() < sk.get("stun_chance", 0.75):
                    def_state["skip_turns"] = def_state.get("skip_turns", 0) + 1
                    log_entry = f"💫 {atk_name} uses *{sk['name']}*! {dmg} dmg + STUN!"
                else:
                    log_entry = f"⚔️ {atk_name} uses *{sk['name']}*! {dmg} dmg. (Stun missed)"
            elif stype == "stun_dmg":
                stat_name = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_name) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if random.random() < sk.get("stun_chance", 0.40):
                    def_state["skip_turns"] = def_state.get("skip_turns", 0) + 1
                    log_entry = f"💫 {atk_name} uses *{sk['name']}*! {dmg} dmg + STUN!"
                else:
                    log_entry = f"⚔️ {atk_name} uses *{sk['name']}*! {dmg} dmg."
            elif stype == "def_shred":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.80))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["def_mod"] = sk.get("def_mod", 0.60)
                def_state["debuff_turns"] = sk.get("debuff_turns", 3)
                log_entry = f"🩹 {atk_name} uses *{sk['name']}*! {dmg} dmg + DEF shred!"
            elif stype == "multi_hit":
                hits = sk.get("hits", 3); mult = sk.get("dmg_mult", 0.60)
                total_dmg = 0
                for _ in range(hits):
                    h = round(base_dmg * mult)
                    if check_crit(attacker_data): h = apply_crit(attacker_data, h)
                    total_dmg += h
                arena[def_hp_key] = max(0, arena[def_hp_key] - total_dmg)
                log_entry = f"⚡ {atk_name} uses *{sk['name']}*! {hits} hits for *{total_dmg}* total!"
            elif stype in ("charge_nuke","charge_pierce","charge_execute","charge_multihit"):
                atk_state["charge_ready"] = True
                atk_state["charge_mult"] = sk.get("charge_mult", sk.get("mult", 2.0))
                log_entry = f"🔋 {atk_name} is *charging*! Next attack hits at ×{atk_state['charge_mult']}!"
            elif stype == "charge_heal_shield":
                atk_state["charge_ready"] = True
                atk_state["charge_mult"] = 1.0
                atk_state["charge_heal_pct"] = sk.get("heal_pct", 0.60)
                atk_state["charge_shield_pct"] = sk.get("shield_pct", 0.40)
                atk_state["charge_shield_turns"] = sk.get("shield_turns", 2)
                log_entry = f"🙏 {atk_name} is *channeling*! Next turn: massive heal + shield."
            elif stype in ("dmg_dot","guaranteed_crit_bleed"):
                if stype == "guaranteed_crit_bleed":
                    dmg = apply_crit(attacker_data, round(base_dmg * sk.get("dmg_mult", 1.80)))
                else:
                    stat_n = sk.get("stat")
                    if stat_n:
                        dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 3.0))
                    else:
                        dmg = round(base_dmg * sk.get("dmg_mult", 0.90))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["dot_type"] = sk.get("dot_type","poison")
                def_state["dot_dmg"]  = sk.get("dot_dmg", 8)
                def_state["dot_turns"] = sk.get("dot_turns", 3)
                log_entry = f"☠️ {atk_name} uses *{sk['name']}*! {dmg} dmg + {def_state['dot_type']} DOT!"
            elif stype == "hp_drain":
                drain = round(arena[def_hp_key] * sk.get("drain_pct", 0.35))
                heal  = round(drain * sk.get("heal_pct", 0.50))
                arena[def_hp_key] = max(0, arena[def_hp_key] - drain)
                if atk_state.get("heal_block_turns", 0) <= 0:
                    arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal)
                log_entry = f"🧛 {atk_name} uses *{sk['name']}*! Drained {drain} HP, healed {heal}!"
            elif stype == "lifesteal":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                heal = round(dmg * sk.get("steal_pct", 0.25))
                if atk_state.get("heal_block_turns", 0) <= 0:
                    arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal)
                log_entry = f"🩸 {atk_name} uses *{sk['name']}*! {dmg} dmg, +{heal} HP!"
            elif stype == "crit_execute":
                threshold = sk.get("execute_threshold", 0.50)
                hp_pct = arena[def_hp_key] / max(1, arena[def_max_key])
                mult = sk.get("execute_mult", 1.80) if hp_pct < threshold else sk.get("dmg_mult", 1.20)
                dmg = apply_crit(attacker_data, round(base_dmg * mult))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                tag = " *(EXECUTE!)*" if hp_pct < threshold else " *(CRIT!)*"
                log_entry = f"💥 {atk_name} uses *{sk['name']}*!{tag} {dmg} dmg!"
            elif stype == "dual_buff_debuff":
                atk_state["atk_mod"] = sk.get("atk_mod", 1.60)
                atk_state["buff_turns"] = sk.get("buff_turns", 2)
                def_state["atk_mod"] = sk.get("enemy_atk_mod", 0.80)
                def_state["debuff_turns"] = sk.get("debuff_turns", 2)
                log_entry = f"📢 {atk_name} uses *{sk['name']}*! ATK up + enemy ATK down!"
            elif stype == "dmg_acc_debuff":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["acc_debuff"] = True
                def_state["acc_debuff_pct"] = sk.get("acc_debuff_pct", 0.40)
                def_state["debuff_turns"] = sk.get("debuff_turns", 2)
                log_entry = f"🎯 {atk_name} uses *{sk['name']}*! {dmg} dmg + accuracy debuff!"
            elif stype == "acc_debuff_only":
                def_state["acc_debuff"] = True
                def_state["acc_debuff_pct"] = sk.get("acc_debuff_pct", 0.50)
                def_state["debuff_turns"] = sk.get("debuff_turns", 1)
                log_entry = f"👻 {atk_name} uses *{sk['name']}*! Enemy accuracy reduced!"
            elif stype == "mark_buff":
                atk_state["mark_bonus"] = sk.get("mark_bonus", 1.30)
                atk_state["mark_attacks"] = sk.get("mark_attacks", 3)
                log_entry = f"🎯 {atk_name} uses *{sk['name']}*! Next {sk.get('mark_attacks',3)} attacks ×{sk.get('mark_bonus',1.3)}!"
            elif stype == "atk_buff_recoil":
                atk_state["atk_mod"] = sk.get("atk_mod", 1.50)
                atk_state["buff_turns"] = sk.get("buff_turns", 2)
                self_dmg = sk.get("self_dmg", 15)
                arena[atk_hp_key] = max(0, arena[atk_hp_key] - self_dmg)
                log_entry = f"💉 {atk_name} uses *{sk['name']}*! ATK boosted but -{self_dmg} HP!"
            elif stype == "dot_aura":
                stat_n = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                atk_state["reflect_dot"] = sk.get("reflect_dot", 6)
                atk_state["reflect_dot_turns"] = sk.get("reflect_turns", 3)
                log_entry = f"🔥 {atk_name} uses *{sk['name']}*! {dmg} dmg + radiance aura!"
            elif stype == "dot_on_attack":
                atk_state["reflect_on_hit"] = sk.get("reflect_on_hit", 10)
                atk_state["reflect_turns"] = sk.get("reflect_turns", 3)
                log_entry = f"⚡ {atk_name} uses *{sk['name']}*! Static field charged  -  {sk.get('reflect_on_hit',10)} dmg on hit!"
            elif stype == "atk_debuff":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.70))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["atk_mod"] = sk.get("enemy_atk_mod", 0.70)
                def_state["debuff_turns"] = sk.get("debuff_turns", 3)
                log_entry = f"💀 {atk_name} uses *{sk['name']}*! {dmg} dmg + enemy ATK reduced!"
            elif stype == "dodge_buff":
                atk_state["miss_next_enemy"] = sk.get("dodge_next", True)
                atk_state["next_atk_bonus"] = sk.get("next_atk_bonus", 1.40)
                log_entry = f"🌫️ {atk_name} uses *{sk['name']}*! Next hit on them misses, next attack boosted!"
            elif stype == "silence_dmg":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.90))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["skill_block_turns"] = sk.get("skill_block_turns", 2)
                log_entry = f"🤐 {atk_name} uses *{sk['name']}*! {dmg} dmg + silenced for {sk.get('skill_block_turns',2)} turns!"
            elif stype == "regen":
                atk_state["regen_hp"] = sk.get("regen_hp", 12)
                atk_state["regen_turns"] = sk.get("regen_turns", 3)
                log_entry = f"🌿 {atk_name} uses *{sk['name']}*! Regenerating {sk.get('regen_hp',12)} HP/turn for {sk.get('regen_turns',3)} turns."
            elif stype == "crit_followup":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.70))
                if check_crit(attacker_data):
                    dmg = apply_crit(attacker_data, dmg)
                    followup = round(base_dmg * sk.get("followup_mult", 1.20))
                    arena[def_hp_key] = max(0, arena[def_hp_key] - dmg - followup)
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! CRIT {dmg} + Shadowstep {followup}!"
                    dmg += followup
                else:
                    arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! {dmg} dmg."
            elif stype == "vanish_ambush":
                def_state["miss_next_enemy"] = True
                atk_state["ambush_bonus"] = sk.get("ambush_bonus", 1.80)
                log_entry = f"👻 {atk_name} *vanishes*! Next enemy attack misses + ambush ready!"
            elif stype == "pierce_dodge":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.40))
                dmg = round(dmg * def_state.get("def_mod", 1.0))
                dmg = round(dmg * def_state.get("amplify_pct", 1.0))
                if def_state["shield_turns"] > 0:
                    dmg = round(dmg * (1 - def_state["shield_pct"]))
                    def_state["shield_turns"] -= 1
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"🏹 {atk_name} uses *{sk['name']}*! Piercing shot for {dmg} dmg!"
            elif stype == "crit_conditional":
                force_crit = sk.get("first_turn_crit") and arena["round"] <= 2
                dmg = round(base_dmg * sk.get("dmg_mult", 1.80))
                if force_crit or check_crit(attacker_data):
                    dmg = apply_crit(attacker_data, dmg)
                    log_entry = f"🗡️ {atk_name} uses *{sk['name']}*! CRIT {dmg} dmg!"
                else:
                    log_entry = f"🗡️ {atk_name} uses *{sk['name']}*! {dmg} dmg."
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
            elif stype == "dodge_counter":
                atk_state["miss_next_enemy"] = sk.get("dodge_next", True)
                counter_dmg = round(base_dmg * sk.get("counter_mult", 0.60))
                arena[def_hp_key] = max(0, arena[def_hp_key] - counter_dmg)
                dmg = counter_dmg
                log_entry = f"💨 {atk_name} uses *{sk['name']}*! Dodge set + counter {counter_dmg}!"
            elif stype == "hp_percentage_nuke":
                dmg = round(arena[def_hp_key] * sk.get("pct", 0.50))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if sk.get("heal_block_turns", 0) > 0:
                    def_state["heal_block_turns"] = sk["heal_block_turns"]
                log_entry = f"💀 {atk_name} uses *{sk['name']}*! Ripped {dmg} HP instantly!"
            elif stype == "dmg_heal_block":
                stat_n = sk.get("stat","INT")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 3.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["heal_block_turns"] = sk.get("block_turns", 3)
                log_entry = f"🚫 {atk_name} uses *{sk['name']}*! {dmg} dmg + heal blocked!"
            elif stype == "strip_heal_block":
                stat_n = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["atk_mod"] = 1.0; def_state["buff_turns"] = 0
                def_state["shield_turns"] = 0
                def_state["heal_block_turns"] = sk.get("heal_block_turns", 2)
                log_entry = f"✝️ {atk_name} uses *{sk['name']}*! {dmg} dmg + buffs stripped + heal blocked!"
            elif stype == "amplify_debuff":
                def_state["extra_dmg_per_hit"] = sk.get("extra_dmg_per_hit", 8)
                def_state["extra_dmg_turns"] = sk.get("debuff_turns", 3)
                log_entry = f"🔍 {atk_name} uses *{sk['name']}*! {def_name} takes +{sk.get('extra_dmg_per_hit',8)} per hit for {sk.get('debuff_turns',3)} turns."
            elif stype == "full_bind":
                def_state["bind_turns"] = sk.get("bind_turns", 3)
                def_state["bind_dmg_mod"] = sk.get("dmg_reduction", 0.70)
                log_entry = f"⛓️ {atk_name} uses *{sk['name']}*! {def_name} bound for {sk.get('bind_turns',3)} turns!"
            elif stype == "cleanse_nuke_buff":
                stat_n = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 5.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                for field in ["dot_type","dot_dmg","dot_turns","acc_debuff","debuff_turns","heal_block_turns","bind_turns","skill_block_turns"]:
                    if field in ("dot_type",): atk_state[field] = None
                    elif field in ("acc_debuff",): atk_state[field] = False
                    else: atk_state[field] = 0
                atk_state["atk_mod"] = sk.get("atk_buff", 1.20)
                atk_state["buff_turns"] = sk.get("buff_turns", 3)
                log_entry = f"✨ {atk_name} uses *{sk['name']}*! {dmg} dmg + cleansed + buffed!"
            elif stype == "everything_debuff_nuke":
                stat_n = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 8.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["atk_mod"] = 1.0; def_state["buff_turns"] = 0; def_state["shield_turns"] = 0
                def_state["dot_type"] = sk.get("dot_type","bleed"); def_state["dot_dmg"] = sk.get("dot_dmg",10); def_state["dot_turns"] = sk.get("dot_turns",3)
                def_state["acc_debuff"] = True; def_state["acc_debuff_pct"] = sk.get("acc_debuff", 0.30); def_state["debuff_turns"] = sk.get("dot_turns",3)
                def_state["heal_block_turns"] = sk.get("heal_block_turns", 2)
                def_state["atk_mod"] = sk.get("atk_debuff", 0.75)
                log_entry = f"💀 {atk_name} uses *{sk['name']}*! {dmg} MASSIVE dmg + all debuffs!"
            elif stype == "ignore_def_stat":
                stat_n = sk.get("stat","DEX")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"🎯 {atk_name} uses *{sk['name']}*! Piercing {dmg} dmg (ignores DEF)!"
            elif stype == "ignore_def_nuke":
                stat_n = sk.get("stat","STR")
                combo_stats = sk.get("stat_combo", [stat_n])
                combo_val = sum(get_stat(attacker_data, s) for s in combo_stats)
                dmg = round(combo_val * sk.get("mult", 6.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"⚔️ {atk_name} uses *{sk['name']}*! Unstoppable {dmg} dmg!"
            elif stype == "nuke_debuff":
                stat_n = sk.get("stat","DEX")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 5.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if arena[def_hp_key] > 0 and sk.get("survive_debuff"):
                    def_state["atk_mod"] = sk["survive_debuff"]
                    def_state["debuff_turns"] = 99
                log_entry = f"🏹 {atk_name} uses *{sk['name']}*! {dmg} dmg!"
            elif stype == "dmg_multi_debuff":
                dmg = round(base_dmg * sk.get("dmg_mult", 0.60))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                def_state["acc_debuff"] = True; def_state["acc_debuff_pct"] = sk.get("acc_mod", 0.50)
                def_state["atk_mod"] = sk.get("atk_mod", 0.80); def_state["debuff_turns"] = sk.get("debuff_turns", 2)
                log_entry = f"🎯 {atk_name} uses *{sk['name']}*! {dmg} dmg + multi-debuff!"
            elif stype == "amplify_debuff_no_dmg":
                def_state["amplify_pct"] = sk.get("amplify_pct", 1.25)
                def_state["debuff_turns"] = sk.get("debuff_turns", 3)
                log_entry = f"🔍 {atk_name} uses *{sk['name']}*! {def_name} takes 25% more damage for {sk.get('debuff_turns',3)} turns!"
            elif stype == "stat_nuke":
                stat_n = sk.get("stat","INT")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"🔮 {atk_name} uses *{sk['name']}*! {dmg} dmg!"
            elif stype == "surge_hit":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.20))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"💥 {atk_name} uses *{sk['name']}*! {dmg} dmg!"
                if random.random() < sk.get("surge_chance", 0.30):
                    surge_dmg = round(base_dmg * sk.get("surge_mult", 0.60))
                    arena[def_hp_key] = max(0, arena[def_hp_key] - surge_dmg)
                    log_entry += f" SURGE! +{surge_dmg}!"
            elif stype == "dmg_debuff_chance":
                stat_n = sk.get("stat","INT")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 1.5))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if random.random() < sk.get("hex_chance", 0.25):
                    def_state["atk_mod"] = sk.get("hex_mod", 0.80)
                    def_state["debuff_turns"] = sk.get("hex_turns", 2)
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! {dmg} dmg + HEX!"
                else:
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! {dmg} dmg."
            elif stype == "multi_hit_proc":
                hits = sk.get("hits", 4); mult = sk.get("dmg_mult", 0.50)
                total_dmg = 0; proc_fired = False
                for i in range(hits):
                    h = round(base_dmg * mult)
                    total_dmg += h
                    if i == 0 and random.random() < sk.get("proc_chance", 0.30):
                        def_state["skip_turns"] = def_state.get("skip_turns", 0) + 1
                        proc_fired = True
                arena[def_hp_key] = max(0, arena[def_hp_key] - total_dmg)
                log_entry = f"🏹 {atk_name} uses *{sk['name']}*! {total_dmg} dmg!"
                if proc_fired: log_entry += " PIN!"
            elif stype == "crit_announce":
                dmg = round(base_dmg * sk.get("dmg_mult", 1.10))
                if check_crit(attacker_data):
                    dmg = apply_crit(attacker_data, dmg)
                    log_entry = f"💥 *HEADSHOT!* {atk_name} deals {dmg} dmg!"
                else:
                    log_entry = f"🎯 {atk_name} uses *{sk['name']}*! {dmg} dmg."
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
            elif stype == "execute_buff":
                stat_n = sk.get("stat","AGI")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 4.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"⚔️ {atk_name} uses *{sk['name']}*! {dmg} dmg!"
                if arena[def_hp_key] <= 0 and sk.get("kill_atk_bonus"):
                    atk_state["atk_mod"] = 1.0 + sk["kill_atk_bonus"]
                    atk_state["buff_turns"] = 99
                    log_entry += " KILL BONUS  -  ATK surged!"
            elif stype == "undodgeable_execute":
                stat_n = sk.get("stat","AGI")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 6.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"💀 {atk_name} uses *{sk['name']}*! Unavoidable {dmg} dmg!"
            elif stype == "risky_hit":
                if random.random() < sk.get("miss_chance", 0.20):
                    log_entry = f"💨 {atk_name} uses *{sk['name']}*! MISSED the wild swing!"
                    dmg = 0
                else:
                    dmg = round(base_dmg * sk.get("dmg_mult", 1.50))
                    arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                    log_entry = f"💥 {atk_name} uses *{sk['name']}*! Reckless {dmg} dmg!"
            elif stype == "stun_nuke":
                stat_n = sk.get("stat","WIS")
                dmg = round(get_stat(attacker_data, stat_n) * sk.get("mult", 2.0))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                if random.random() < sk.get("stun_chance", 0.35):
                    def_state["skip_turns"] = def_state.get("skip_turns", 0) + 1
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! {dmg} dmg + STUN!"
                else:
                    log_entry = f"🌑 {atk_name} uses *{sk['name']}*! {dmg} dmg."
            else:
                dmg = round(base_dmg * sk.get("dmg_mult", sk.get("mult", 1.2)))
                arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
                log_entry = f"⚡ {atk_name} uses *{sk['name']}*! {dmg} dmg."

        elif action == "item":
            if len(context.args) < 2:
                await send_group(update, "Usage: /arena item [item name]", delay=5); return
            item_name = " ".join(context.args[1:])
            items = arena[atk_items_key]
            if not items.get(item_name, 0):
                await send_group(update, f"You don't have *{item_name}* in your arena kit.", delay=5); return
            if atk_state.get("heal_block_turns", 0) > 0 and ("Chalk" in item_name or "Flask" in item_name):
                arena["log"].append(f"🚫 {atk_name}'s healing is blocked!")
                await send_group(update, "Your healing is blocked!", delay=5); return
            items[item_name] -= 1
            if items[item_name] <= 0: del items[item_name]
            if "Health Potion" in item_name or "Restorative Flask" in item_name or "Greater Health" in item_name:
                heal_val = {"Health Potion":50,"Greater Health Potion":100,"Grand Restorative Flask":200}.get(item_name,50)
                arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal_val)
                log_entry = f"🧪 {atk_name} drinks *{item_name}*! +{heal_val} HP."
            else:
                log_entry = f"🎒 {atk_name} used *{item_name}*."
        else:
            await send_group(update, "Use: `/arena attack`, `/arena skill [number]`, `/arena item [name]`", delay=5); return

        if log_entry:
            arena["log"].append(log_entry)

        if arena["p1_hp"] <= 0 or arena["p2_hp"] <= 0:
            arena["status"] = "done"
            winner_id = arena["p1_id"] if arena["p1_hp"] > 0 else arena["p2_id"]
            loser_id  = arena["p2_id"] if winner_id == arena["p1_id"] else arena["p1_id"]
            wp = get_player(winner_id); lp = get_player(loser_id)
            wager = arena["wager"]
            if wp and lp:
                if wager > 0:
                    wp["gold"] = wp.get("gold",0) + wager * 2
                wp["wins"] = wp.get("wins",0) + 1
                for _d, _e, _g in track_objective(wp, "arena_win"):
                    wp["gold"] = wp.get("gold",0) + _g; add_exp(wp, _e)
                asyncio.create_task(check_and_claim_bounty(update.get_bot(), wp, lp, chat_id))
                exp_gain = 50 + wp["level"] * 5
                add_exp(wp, exp_gain)
                save_player(wp); save_player(lp)
            w_name = arena["p1"]["username"] if arena["p1_hp"] > 0 else arena["p2"]["username"]
            arena["log"].append(f"🏆 *{w_name}* wins the arena!")
            active_arenas.pop(chat_id, None)
        else:
            arena["turn"] = arena["p2_id"] if is_p1 else arena["p1_id"]
            arena["round"] += 1

        card_text = build_arena_card(arena)
        end_markup = build_arena_markup(arena, chat_id)
        if arena.get("msg_id"):
            try:
                await update.get_bot().delete_message(chat_id=chat_id, message_id=arena["msg_id"])
            except Exception: pass
        try:
            msg = await update.get_bot().send_message(
                chat_id=chat_id, text=card_text[:4096], parse_mode="Markdown",
                reply_markup=end_markup)
            arena["msg_id"] = msg.message_id
        except Exception: pass
        return

    # Challenge initiation
    if not update.message.reply_to_message:
        await send_group(update,
            "⚔️ *Arena  -  Turn-based PvP*\n\n"
            "Reply to a player's message to challenge them!\n"
            "`/arena`  -  free fight\n"
            "`/arena 200`  -  fight with 200g wager\n\n"
            "Each turn: `/arena attack`, `/arena skill [1-7]`, `/arena item [name]`",
            delay=30); return

    du = update.message.reply_to_message.from_user
    if du.id == user.id:
        await send_group(update, "Can't challenge yourself!", delay=9); return
    tp = get_player(du.id)
    if not tp:
        await send_group(update, f"{du.first_name} hasn't ascended yet!", delay=9); return
    if chat_id in active_arenas:
        await send_group(update, "An arena fight is already active here!", delay=9); return
    wager = 0
    if context.args:
        try: wager = max(0, int(context.args[0]))
        except: pass
    if wager > 0 and p["gold"] < wager:
        await send_group(update, f"❌ Need {wager}g for the wager. Have {p['gold']}g.", delay=9); return

    active_arenas[chat_id] = {
        "p1_id": user.id, "p2_id": du.id,
        "p1": None, "p2": None,
        "p1_hp": 0, "p2_hp": 0, "p1_max": 0, "p2_max": 0,
        "turn": user.id, "round": 0, "log": [], "msg_id": None,
        "wager": wager, "status": "waiting",
        "p1_items": {}, "p2_items": {},
        "p1_state": _arena_state(), "p2_state": _arena_state(),
        "expires": (datetime.now() + timedelta(minutes=5)).isoformat(),
    }
    wager_str = f" for *{wager}g*" if wager > 0 else " (no wager)"
    await send_group(update,
        f"🎪 *{user.first_name}* challenges *{du.first_name}* to an Arena fight{wager_str}!\n\n"
        f"_{du.first_name}: type `/arena accept` to begin._\n"
        f"_HP changes are arena-only  -  your real HP is safe._\n\n"
        f"Challenge expires in 5 minutes.", permanent=False, delay=300)

async def arena_act_callback(update, context):
    """Handle arena button presses: attack, skill, flee."""
    query = update.callback_query
    await query.answer()
    data = query.data  # arena_act_{chat_id}_{uid}_{action}
    parts = data.split("_")
    # Format: arena_act_{chat_id}_{uid}_{action}
    # parts: ['arena','act',chat_id,uid,action]
    if len(parts) < 5:
        return
    try:
        chat_id = int(parts[2])
        uid     = int(parts[3])
        action  = parts[4]
    except (ValueError, IndexError):
        return

    if query.from_user.id != uid:
        await query.answer("It's not your turn!", show_alert=True)
        return

    arena = active_arenas.get(chat_id)
    if not arena or arena["status"] != "active":
        await query.answer("No active arena.", show_alert=True)
        return
    if arena["turn"] != uid:
        await query.answer("It's not your turn!", show_alert=True)
        return

    is_p1 = (uid == arena["p1_id"])
    attacker_data = arena["p1"] if is_p1 else arena["p2"]
    defender_data = arena["p2"] if is_p1 else arena["p1"]
    atk_hp_key    = "p1_hp" if is_p1 else "p2_hp"
    def_hp_key    = "p2_hp" if is_p1 else "p1_hp"
    atk_max_key   = "p1_max" if is_p1 else "p2_max"
    atk_state_key = "p1_state" if is_p1 else "p2_state"
    def_state_key = "p2_state" if is_p1 else "p1_state"
    atk_name  = attacker_data["username"]
    def_name  = defender_data["username"]
    atk_state = arena[atk_state_key]
    def_state = arena[def_state_key]

    # Turn-start DOT / regen effects
    if atk_state["dot_turns"] > 0:
        arena[atk_hp_key] = max(0, arena[atk_hp_key] - atk_state["dot_dmg"])
        atk_state["dot_turns"] -= 1
        arena["log"].append(f"🩸 {atk_name} takes {atk_state['dot_dmg']} from {atk_state['dot_type']}!")
        if atk_state["dot_turns"] == 0:
            atk_state["dot_type"] = None; atk_state["dot_dmg"] = 0
    if atk_state["regen_turns"] > 0:
        arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + atk_state["regen_hp"])
        atk_state["regen_turns"] -= 1
        arena["log"].append(f"💚 {atk_name} regenerates {atk_state['regen_hp']} HP!")
    if atk_state["buff_turns"] > 0:
        atk_state["buff_turns"] -= 1
        if atk_state["buff_turns"] == 0: atk_state["atk_mod"] = 1.0
    if atk_state["debuff_turns"] > 0:
        atk_state["debuff_turns"] -= 1
        if atk_state["debuff_turns"] == 0:
            atk_state["def_mod"] = 1.0; atk_state["acc_debuff"] = False; atk_state["acc_debuff_pct"] = 0.0
    for timer_key in ["heal_block_turns","bind_turns","skill_block_turns","extra_dmg_turns"]:
        if atk_state.get(timer_key, 0) > 0:
            atk_state[timer_key] -= 1

    # DOT death check — if attacker dies to DOT, end the fight
    if arena[atk_hp_key] <= 0:
        arena["status"] = "done"
        winner_id = arena["p2_id"] if is_p1 else arena["p1_id"]
        loser_id  = arena["p1_id"] if is_p1 else arena["p2_id"]
        wp = get_player(winner_id); lp = get_player(loser_id)
        wager = arena["wager"]
        if wp and lp:
            if wager > 0:
                wp["gold"] = wp.get("gold",0) + wager * 2
            wp["wins"] = wp.get("wins",0) + 1
            save_player(wp); save_player(lp)
        w_name = arena["p1"]["username"] if winner_id == arena["p1_id"] else arena["p2"]["username"]
        arena["log"].append(f"☠️ {atk_name} dies to damage over time! 🏆 *{w_name}* wins!")
        active_arenas.pop(chat_id, None)
        card_text = build_arena_card(arena)
        markup = build_arena_markup(arena, chat_id)
        try:
            await query.edit_message_text(text=card_text[:4096], parse_mode="Markdown", reply_markup=markup)
        except Exception: pass
        return

    # Stun check
    if atk_state.get("skip_turns", 0) > 0:
        atk_state["skip_turns"] -= 1
        arena["log"].append(f"⚡ {atk_name} is stunned — turn skipped!")
        arena["turn"] = arena["p2_id"] if is_p1 else arena["p1_id"]
        arena["round"] += 1
        card_text = build_arena_card(arena)
        markup = build_arena_markup(arena, chat_id)
        try:
            await query.edit_message_text(text=card_text[:4096], parse_mode="Markdown", reply_markup=markup)
        except Exception: pass
        return

    log_entry = ""
    w = get_weather()

    if action == "flee":
        # End the arena — declare the other player winner
        arena["status"] = "done"
        winner_id = arena["p2_id"] if is_p1 else arena["p1_id"]
        loser_id  = uid
        wp = get_player(winner_id); lp = get_player(loser_id)
        wager = arena["wager"]
        if wp and lp:
            if wager > 0:
                wp["gold"] = wp.get("gold",0) + wager * 2
            wp["wins"] = wp.get("wins",0) + 1
            for _d, _e, _g in track_objective(wp, "arena_win"):
                wp["gold"] = wp.get("gold",0) + _g; add_exp(wp, _e)
            asyncio.create_task(check_and_claim_bounty(query.get_bot(), wp, lp, chat_id))
            exp_gain = 50 + wp["level"] * 5
            add_exp(wp, exp_gain)
            save_player(wp); save_player(lp)
        w_name = defender_data["username"]
        arena["log"].append(f"🏃 {atk_name} flees! 🏆 *{w_name}* wins the arena!")
        if is_p1:
            arena["p1_hp"] = 0  # Force done display
        else:
            arena["p2_hp"] = 0  # Force done display
        active_arenas.pop(chat_id, None)
        card_text = build_arena_card(arena)
        try:
            await query.edit_message_text(text=card_text[:4096], parse_mode="Markdown")
        except Exception: pass
        return

    elif action == "atk":
        dmg = calc_attack_damage(attacker_data, w)
        dmg = round(dmg * atk_state["atk_mod"])
        if atk_state.get("mark_attacks", 0) > 0:
            dmg = round(dmg * atk_state.get("mark_bonus", 1.0))
            atk_state["mark_attacks"] -= 1
            if atk_state["mark_attacks"] == 0: atk_state["mark_bonus"] = 1.0
        if atk_state.get("ambush_bonus", 1.0) > 1.0:
            dmg = round(dmg * atk_state["ambush_bonus"])
            atk_state["ambush_bonus"] = 1.0
            arena["log"].append(f"🌑 *Ambush!* Bonus damage!")
        if atk_state.get("next_atk_bonus", 1.0) > 1.0:
            dmg = round(dmg * atk_state["next_atk_bonus"])
            atk_state["next_atk_bonus"] = 1.0
        if atk_state.get("charge_ready"):
            dmg = round(dmg * atk_state.get("charge_mult", 2.0))
            atk_state["charge_ready"] = False; atk_state["charge_mult"] = 1.0
            arena["log"].append(f"💥 *CHARGED STRIKE!*")
        if atk_state.get("acc_debuff") and random.random() < atk_state.get("acc_debuff_pct", 0.40):
            arena["log"].append(f"😵 {atk_name} missed — accuracy debuffed!")
            dmg = 0
        if def_state.get("miss_next_enemy"):
            def_state["miss_next_enemy"] = False
            arena["log"].append(f"🌫️ {def_name}'s evasion causes {atk_name} to miss!")
            dmg = 0
        if dmg > 0 and check_crit(attacker_data):
            dmg = apply_crit(attacker_data, dmg)
            log_entry = f"💥 CRIT! {atk_name} hits {def_name} for *{dmg}*!"
        else:
            log_entry = f"⚔️ {atk_name} hits {def_name} for *{dmg}*." if dmg > 0 else f"🌀 {atk_name} missed!"
        if dmg > 0:
            dmg = round(dmg * def_state.get("def_mod", 1.0))
            dmg = round(dmg * def_state.get("amplify_pct", 1.0))
            if def_state.get("extra_dmg_turns", 0) > 0:
                dmg += def_state.get("extra_dmg_per_hit", 0)
            if def_state["shield_turns"] > 0:
                dmg = round(dmg * (1 - def_state["shield_pct"]))
                def_state["shield_turns"] -= 1
                if def_state["shield_turns"] == 0: def_state["shield_pct"] = 0.0
            if def_state.get("reflect_on_hit", 0) > 0 and def_state.get("reflect_turns", 0) > 0:
                arena[atk_hp_key] = max(0, arena[atk_hp_key] - def_state["reflect_on_hit"])
                arena["log"].append(f"⚡ {def_name} reflects {def_state['reflect_on_hit']} dmg!")
            if def_state.get("bind_turns", 0) > 0:
                dmg = round(dmg * def_state.get("bind_dmg_mod", 1.0))
        arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)

    elif action == "skl":
        if atk_state.get("skill_block_turns", 0) > 0:
            await query.answer("You're silenced — no skills this turn!", show_alert=True)
            return
        skills = sjl(attacker_data.get("all_skills"), [])
        sk = skills[0] if skills else None
        if not sk:
            await query.answer("No skills available!", show_alert=True)
            return
        stype = sk.get("type", "damage")
        base_dmg = calc_attack_damage(attacker_data, w)
        base_dmg = round(base_dmg * atk_state["atk_mod"])
        dmg = 0

        if stype == "atk_buff":
            atk_state["atk_mod"] = sk.get("atk_mod", 1.40)
            atk_state["buff_turns"] = sk.get("buff_turns", 3)
            log_entry = f"💪 {atk_name} uses *{sk['name']}*! ATK ×{sk.get('atk_mod',1.4)} for {sk.get('buff_turns',3)} turns."
        elif stype in ("def_buff","dmg_reduction_buff"):
            def_mod = sk.get("def_mod", 0.65)
            atk_state["def_mod"] = def_mod
            atk_state["buff_turns"] = sk.get("buff_turns", 2)
            log_entry = f"🛡️ {atk_name} uses *{sk['name']}*! Damage reduced for {sk.get('buff_turns',2)} turns."
        elif stype in ("self_heal","revive_heal"):
            if atk_state.get("heal_block_turns", 0) > 0:
                log_entry = f"🚫 {atk_name}'s healing is blocked!"
            else:
                stat_name = sk.get("stat","WIS")
                heal_mult = sk.get("mult", sk.get("wis_mult", 4.0))
                heal = round(get_stat(attacker_data, stat_name) * heal_mult)
                arena[atk_hp_key] = min(arena[atk_max_key], arena[atk_hp_key] + heal)
                log_entry = f"💚 {atk_name} uses *{sk['name']}*! Restored {heal} HP."
        elif stype == "stun":
            dmg = round(base_dmg * sk.get("dmg_mult", 0.80))
            arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
            if random.random() < sk.get("stun_chance", 0.75):
                def_state["skip_turns"] = def_state.get("skip_turns", 0) + 1
                log_entry = f"💫 {atk_name} uses *{sk['name']}*! {dmg} dmg + STUN!"
            else:
                log_entry = f"⚔️ {atk_name} uses *{sk['name']}*! {dmg} dmg. (Stun missed)"
        elif stype == "dodge_buff":
            atk_state["miss_next_enemy"] = sk.get("dodge_next", True)
            atk_state["next_atk_bonus"] = sk.get("next_atk_bonus", 1.40)
            log_entry = f"🌫️ {atk_name} uses *{sk['name']}*! Next hit on them misses, next attack boosted!"
        elif stype == "regen":
            atk_state["regen_hp"] = sk.get("regen_hp", 12)
            atk_state["regen_turns"] = sk.get("regen_turns", 3)
            log_entry = f"🌿 {atk_name} uses *{sk['name']}*! Regenerating {sk.get('regen_hp',12)} HP/turn for {sk.get('regen_turns',3)} turns."
        else:
            dmg = round(base_dmg * sk.get("dmg_mult", sk.get("mult", 1.2)))
            arena[def_hp_key] = max(0, arena[def_hp_key] - dmg)
            log_entry = f"⚡ {atk_name} uses *{sk['name']}*! {dmg} dmg."
    else:
        return

    if log_entry:
        arena["log"].append(log_entry)

    if arena["p1_hp"] <= 0 or arena["p2_hp"] <= 0:
        arena["status"] = "done"
        winner_id = arena["p1_id"] if arena["p1_hp"] > 0 else arena["p2_id"]
        loser_id  = arena["p2_id"] if winner_id == arena["p1_id"] else arena["p1_id"]
        wp = get_player(winner_id); lp = get_player(loser_id)
        wager = arena["wager"]
        if wp and lp:
            if wager > 0:
                wp["gold"] = wp.get("gold",0) + wager * 2
            wp["wins"] = wp.get("wins",0) + 1
            for _d, _e, _g in track_objective(wp, "arena_win"):
                wp["gold"] = wp.get("gold",0) + _g; add_exp(wp, _e)
            asyncio.create_task(check_and_claim_bounty(query.get_bot(), wp, lp, chat_id))
            exp_gain = 50 + wp["level"] * 5
            add_exp(wp, exp_gain)
            save_player(wp); save_player(lp)
        w_name = arena["p1"]["username"] if arena["p1_hp"] > 0 else arena["p2"]["username"]
        arena["log"].append(f"🏆 *{w_name}* wins the arena!")
        active_arenas.pop(chat_id, None)
    else:
        arena["turn"] = arena["p2_id"] if is_p1 else arena["p1_id"]
        arena["round"] += 1

    card_text = build_arena_card(arena)
    markup = build_arena_markup(arena, chat_id)
    try:
        await query.edit_message_text(text=card_text[:4096], parse_mode="Markdown", reply_markup=markup)
    except Exception: pass

# ── DUNGEON ───────────────────────────────────────────────────────────────────
def _resolve_dungeon_room(p, room_type, theme, diff, room_num, hp_remaining, class_line):
    check       = ROOM_STAT_CHECKS.get(room_type, {})
    threshold   = check.get("threshold", 0.60)
    primary_key = check.get("primary", "combat_power")
    if primary_key == "combat_power":
        stat_val = calc_dungeon_cp(p)
        stat_mod = min(0.30, stat_val / 2000)
    else:
        stat_val = get_stat(p, primary_key)
        sec = check.get("secondary")
        if sec: stat_val = max(stat_val, get_stat(p, sec))
        stat_mod = min(0.25, stat_val / 200)
    class_bonus    = check.get("class_bonus", {}).get(class_line, 0)
    success_chance = min(0.92, threshold + stat_mod + class_bonus)
    roll    = random.random()
    crit    = roll < success_chance * 0.35
    success = crit or roll < success_chance

    enemy_name  = (random.choice(theme["enemy_prefix"]) + " " +
                   random.choice(["Sentry","Lurker","Revenant","Warden",
                                  "Shade","Brute","Keeper","Hollow"]))
    trap_desc   = random.choice(theme["trap_flavor"])
    room_flavor = random.choice(theme["room_flavor"])

    setup_pools = {
        "monster":  [f"A {enemy_name} lurches from the shadows.",
                     f"You round a corner and find a {enemy_name} waiting.",
                     f"The {enemy_name} drops from the ceiling without warning.",
                     f"Something moves in the dark ahead  -  a {enemy_name}.",
                     f"The {enemy_name} was already watching you enter.",
                     f"You hear it before you see it. A {enemy_name} in the passage.",
                     f"It smells you first. The {enemy_name} charges.",
                     f"A {enemy_name} blocks the only path forward."],
        "trap":     [f"The corridor looks clear until {trap_desc}.",
                     f"You feel the floor shift  -  {trap_desc}.",
                     f"Something about the room is wrong. Then {trap_desc} proves it.",
                     f"You notice {trap_desc} a moment too late.",
                     f"The passage narrows just as {trap_desc} activates."],
        "treasure": ["A chest sits in the center of the room. Old iron, heavy lock.",
                     "Something valuable was stashed here by someone who expected to return.",
                     "The chest is half-buried under fallen stone. Someone tried to hide it.",
                     "A cache wedged into a niche in the wall. Easy to miss. You didn't.",
                     "A locked chest sits on a stone plinth like it was left for you."],
        "puzzle":   ["The door ahead has no handle. Only symbols carved in a pattern that almost makes sense.",
                     "A mechanism of interlocking rings blocks the passage.",
                     "The room reconfigures itself as you enter. Pathways shift.",
                     "An inscription demands you solve something before you pass.",
                     "Three levers, no markings. The wrong combination triggers something bad.",
                     "The floor tiles are a pressure sequence. Step wrong and something happens."],
        "rest":     ["A small alcove off the main corridor. Dry, defensible, quiet.",
                     "Someone camped here before you. Their fire ring is cold but you restart it.",
                     "Not ideal. But you've slept in worse places.",
                     "A natural chamber  -  wide enough to breathe in.",
                     "The dungeon run offers a rare moment of silence. You take it."],
        "altar":    ["A stone altar dominates the room. Old carvings. Something dried on the surface.",
                     "The altar pulses with a light that has no source.",
                     "Offerings have been left here recently. Someone else has been through.",
                     "The altar is intact while everything around it is rubble.",
                     "A shrine to something that has no name in any language you know."],
        "ambush":   [f"The room seems clear. Then the walls start moving  -  a {enemy_name}.",
                     f"You walk into it. A coordinated ambush. Two {enemy_name}s from either side.",
                     f"They were in the ceiling. {enemy_name}s, plural. Dropping together.",
                     f"A second {enemy_name} you didn't see. The first was a distraction.",
                     f"The passage narrows right as the {enemy_name}s spring their trap."],
        "merchant": ["A hooded figure sits cross-legged on a bedroll with wares. Inside a dungeon run.",
                     "You smell pipe smoke before you see them  -  a merchant, impossibly calm.",
                     "A small stall set up in an alcove. The merchant nods like they expected you.",
                     "Someone has been down here long enough to set up shop. They look comfortable."],
        "mini_boss":[f"The room is too large and too quiet. Then you see why  -  a {enemy_name} Champion.",
                     f"It heard you coming three rooms back. The {enemy_name} Lord was ready.",
                     f"This one is different. Bigger. Smarter. A {enemy_name} Alpha.",
                     f"You smell it before you see it. A {enemy_name} Warlord. Old and mean.",
                     f"The {enemy_name} Sovereign hasn't moved. Waiting for you to go first."],
    }
    setup = random.choice(setup_pools.get(room_type, [f"Room {room_num}."]))

    if crit and success:
        outcome = random.choice([
            "You handle it perfectly. Textbook execution from start to finish.",
            "Better than you had any right to expect. Clean and efficient.",
            "Everything lands. This one goes in the memory as a good run.",
            "You read it before it started. The outcome was never in doubt.",
            "The kind of moment that makes it worth doing this.",
        ])
    elif success:
        outcome = random.choice([
            "You get through it. Not gracefully, but through.",
            "It costs you something but less than it could have.",
            "A workable result. You've had worse.",
            "Done. You move on.",
            "Good enough. The next room awaits.",
            "You manage it. That's all that matters down here.",
        ])
    else:
        outcome = random.choice([
            "It gets more of you than you wanted. You push through.",
            "Not your finest moment. You survive it.",
            "You take the hit and keep moving. No other option.",
            "The dungeon run wins this exchange. You absorb it and press on.",
            "A rough one. You'll feel this in the later rooms.",
        ])

    class_additions = {
        "warrior": ["Your armor absorbs the worst of it.",
                    "Battlefield instinct carries you through.",
                    "You've trained for rooms exactly like this."],
        "mage":    ["Arcane awareness gives you a half-second advantage.",
                    "You analyze it before committing. That saves you.",
                    "The magic bends slightly in your favor."],
        "thief":   ["You find the angle nobody else would have thought to look for.",
                    "Quick hands and quicker thinking.",
                    "The shadows cooperate. They usually do."],
        "archer":  ["Distance and patience. Your two best tools.",
                    "You read the room from the entrance before stepping in.",
                    "You never let it get close enough to be a real problem."],
        "priest":  ["Faith steadies your hand when sense might have failed.",
                    "The light holds. It always holds.",
                    "You endure. That's what the path demands."],
    }
    class_add = ""
    if random.random() < 0.35 and class_line in class_additions:
        class_add = " " + random.choice(class_additions[class_line])

    narrative = f"{room_flavor} {setup} {outcome}{class_add}"

    exp_ranges = {
        "normal":    {"monster":(80,120),"trap":(30,60),"treasure":(20,40),
                      "puzzle":(60,100),"rest":(0,0),"merchant":(0,0),
                      "altar":(40,80),"ambush":(50,90),"mini_boss":(180,220)},
        "hard":      {"monster":(150,200),"trap":(60,100),"treasure":(40,70),
                      "puzzle":(100,160),"rest":(0,0),"merchant":(0,0),
                      "altar":(80,130),"ambush":(90,140),"mini_boss":(380,420)},
        "legendary": {"monster":(250,350),"trap":(100,160),"treasure":(70,110),
                      "puzzle":(180,260),"rest":(0,0),"merchant":(0,0),
                      "altar":(150,220),"ambush":(160,240),"mini_boss":(680,720)},
    }
    exp_range = exp_ranges.get(diff, exp_ranges["normal"]).get(room_type, (0, 0))
    base_exp = random.randint(*exp_range) if exp_range[1] > 0 else 0
    if not success: base_exp = round(base_exp * 0.3)
    if crit: base_exp = round(base_exp * 1.5)

    gold = 0
    if success and room_type in ("monster","treasure","mini_boss"):
        gold_ranges = {"normal":(10,40),"hard":(25,80),"legendary":(60,180)}
        gr = gold_ranges.get(diff, (10,40))
        gold = random.randint(*gr)

    item = None
    if success and room_type in ("monster","treasure","mini_boss"):
        loot_table = DUNGEON_LOOT.get(diff, {}).get(room_type, [])
        luk_bonus  = get_stat(p, "LUK") * 0.003
        for item_name, chance in loot_table:
            if random.random() < min(chance + luk_bonus, 0.95):
                item = item_name; break

    hp_cost = 0
    if not success:
        dmg_ranges = {"normal":(10,25),"hard":(20,45),"legendary":(35,70)}
        hp_cost = random.randint(*dmg_ranges.get(diff, (10,25)))
        if room_type in ("trap","ambush"): hp_cost = round(hp_cost * 1.4)
        if class_line == "warrior":        hp_cost = round(hp_cost * 0.75)

    return {"type": room_type, "narrative": narrative, "success": success,
            "crit": crit, "exp": base_exp, "gold": gold, "item": item,
            "hp_cost": hp_cost}


def _resolve_dungeon_boss(p, theme, diff, class_line):
    cp = calc_dungeon_cp(p)
    boss_thresholds = {"normal": 800, "hard": 1600, "legendary": 3000}
    threshold = boss_thresholds.get(diff, 800)
    success_chance = min(0.88, 0.45 + (cp / (threshold * 3.5)))
    roll    = random.random()
    epic    = roll < success_chance * 0.25
    success = epic or roll < success_chance

    intro = random.choice([
        f"The final door opens into a chamber built for something that should not exist.",
        f"The {theme['boss_name']}'s chamber is vast. It has been here a very long time.",
        f"You hear it breathing before the door is fully open.",
        f"The {theme['boss_name']} doesn't move when you enter. It watches.",
        f"Everything in the dungeon run led here. The {theme['boss_name']} is the reason.",
    ])
    if epic:
        outcome = random.choice([
            (f"A perfect fight. You understand the {theme['boss_name']}'s pattern by the second "
             f"exchange and dismantle it methodically. It falls and does not rise."),
            (f"The {theme['boss_name']} is everything its reputation promised. You're better. "
             f"Faster than it expects. The chamber goes quiet when it falls."),
            (f"You've faced worse. The {theme['boss_name']} underestimates you in the first "
             f"exchange and never gets a chance to correct the mistake."),
        ])
    elif success:
        outcome = random.choice([
            (f"The {theme['boss_name']} is every bit the threat the dungeon run promised. "
             f"You give everything. A long brutal exchange. You're still standing. Barely."),
            (f"It takes several attempts to find the pattern. When you do, the "
             f"{theme['boss_name']} falls on your terms, not its own."),
            (f"You go in hard and don't let up. The {theme['boss_name']} is stronger "
             f"than anything else in this dungeon run. So are you, today."),
            (f"A war of attrition. The {theme['boss_name']} has endurance. You have more. "
             f"When it drops the silence is absolute."),
        ])
    else:
        outcome = random.choice([
            (f"The {theme['boss_name']} is too much. You get through two phases before "
             f"it drives you back. Not a defeat  -  a tactical retreat."),
            (f"It outpaces you. Not by much, but enough. You leave with your life "
             f"and a clear picture of what needs to improve."),
            (f"The {theme['boss_name']} has fought hundreds like you. It shows. "
             f"You survive the encounter and carry the lesson home."),
        ])

    exp_rewards  = {"normal": 350, "hard": 700, "legendary": 1400}
    gold_rewards = {"normal": 80,  "hard": 200, "legendary": 500}
    exp  = exp_rewards.get(diff, 350)  if success else round(exp_rewards.get(diff, 350)  * 0.20)
    gold = gold_rewards.get(diff, 80)  if success else 0
    item = None
    if success:
        loot_table = DUNGEON_LOOT.get(diff, {}).get("boss", [])
        luk_bonus  = get_stat(p, "LUK") * 0.004
        for item_name, chance in loot_table:
            if random.random() < min(chance + luk_bonus, 0.95):
                item = item_name; break

    return {"type": "boss", "narrative": f"{intro}\n\n{outcome}",
            "success": success, "crit": epic,
            "exp": exp, "gold": gold, "item": item}


def _build_dungeon_recap(p, theme, diff, results, total_exp, total_gold,
                         items_found, run_failed, lmsgs):
    lines = [
        f"🏰 *{p['username']} returns from {theme['name']}*",
        f"_{theme['desc']}_",
        "━━━━━━━━━━━━━━━━",
    ]
    emoji_map = {
        "monster":"⚔️","trap":"⚠️","treasure":"💰","puzzle":"🔮",
        "rest":"🌿","merchant":"🛍️","altar":"🕯️","ambush":"🗡️",
        "mini_boss":"💀","boss":"🎱",
    }
    room_num = 0
    for result in results:
        if result["type"] == "defeat":
            lines.append(f"\n💀 *RETREAT*\n_{result['narrative']}_")
            break
        room_num += 1
        emoji    = emoji_map.get(result["type"], "🚪")
        crit_tag = " ✨" if result.get("crit")    else ""
        fail_tag = " ❌" if not result.get("success") else ""
        if result["type"] == "boss":
            room_label = f"*⚔️ Final Boss  -  {theme['boss_name']}{crit_tag}{fail_tag}*"
        else:
            room_label = (f"*Room {room_num}  -  "
                          f"{result['type'].replace('_',' ').title()}{crit_tag}{fail_tag}*")
        lines.append(f"\n{emoji} {room_label}")
        lines.append(f"_{result['narrative']}_")
        rewards = []
        if result.get("exp"):      rewards.append(f"+{result['exp']} EXP")
        if result.get("gold"):     rewards.append(f"+{result['gold']}g")
        if result.get("item"):
            rt = ""
            for pool in [WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES, SHIELDS]:
                if result["item"] in pool:
                    rt = RARITY_EMOJI.get(pool[result["item"]].get("rarity",""), "")
                    break
            rewards.append(f"🎒 {rt} {result['item']}")
        if result.get("hp_cost"):  rewards.append(f"❤️ -{result['hp_cost']} HP")
        if rewards: lines.append("  " + " | ".join(rewards))

    lines.append("\n━━━━━━━━━━━━━━━━")
    if not run_failed:
        lines.append(f"✅ *Dungeon Run Complete  -  {diff.capitalize()}*\n")
    else:
        lines.append("🏃 *Dungeon Run Abandoned  -  retreated alive*\n")
    lines.append("🏆 *Total Rewards:*")
    lines.append(f"✨ +{total_exp:,} EXP | 💰 +{total_gold:,} gold")
    for item in items_found:
        rt = ""
        for pool in [WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES, SHIELDS]:
            if item in pool:
                rt = RARITY_EMOJI.get(pool[item].get("rarity",""), "")
                break
        lines.append(f"🎒 {rt} *{item}*")
    if lmsgs:
        lines.append("")
        lines.extend(lmsgs)
    return "\n".join(lines)[:4096]


async def dungeon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 You're too beaten up to enter a dungeon run!", delay=9); return
    if not check_cooldown(p.get("last_dungeon"), 86400):
        await send_group(update,
            f"⏳ Dungeon run cooldown: {time_remaining(p.get('last_dungeon'), 86400)}", delay=9); return
    if user.id in active_dungeons:
        await send_group(update, "🏰 You're already in a dungeon run! Wait for your return.", delay=9); return

    if not context.args:
        # Show difficulty picker with inline buttons
        dungeon_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Normal",    callback_data=f"dungeon_d_{user.id}_normal"),
            InlineKeyboardButton("Hard",      callback_data=f"dungeon_d_{user.id}_hard"),
            InlineKeyboardButton("Legendary", callback_data=f"dungeon_d_{user.id}_legendary"),
        ]])
        await send_group(update,
            f"🏰 *Choose your difficulty:*\n\n"
            f"⚔️ Normal  -  Level 1+\n"
            f"🔥 Hard  -  Level 15+\n"
            f"👑 Legendary  -  Level 40+",
            delay=30, reply_markup=dungeon_markup)
        return

    diff = "normal"
    arg = context.args[0].lower()
    if arg in ("hard","h"):             diff = "hard"
    elif arg in ("legendary","l","leg"): diff = "legendary"

    level_reqs = {"normal": 1, "hard": 15, "legendary": 40}
    if p["level"] < level_reqs[diff]:
        await send_group(update,
            f"❌ *{diff.capitalize()}* dungeon runs require Level {level_reqs[diff]}. "
            f"You're Level {p['level']}.", delay=9); return

    theme = random.choice(DUNGEON_THEMES)
    room_distributions = {
        "normal":    ["monster","trap","treasure","puzzle","rest"],
        "hard":      ["monster","trap","treasure","puzzle","rest","monster","mini_boss"],
        "legendary": ["monster","trap","treasure","puzzle","rest",
                      "ambush","merchant","altar","monster","mini_boss"],
    }
    rooms = room_distributions[diff].copy()
    random.shuffle(rooms)
    timers        = {"normal": 2700, "hard": 3600, "legendary": 5400}
    timer_display = {"normal": "45 minutes", "hard": "1 hour", "legendary": "90 minutes"}

    p["last_dungeon"] = datetime.now().isoformat()
    save_player(p)
    cls      = get_player_class(p)
    cls_name = cls["name"] if cls else "Player"
    await send_group(update,
        f"🏰 *{user.first_name}* enters *{theme['name']}!*\n\n"
        f"_{theme['desc']}_\n\n"
        f"⚔️ Class: {cls_name} | 📊 Level {p['level']}\n"
        f"🎯 Difficulty: *{diff.capitalize()}*\n"
        f"🚪 {len(rooms)} rooms + final boss\n\n"
        f"_Results in {timer_display[diff]}._",
        permanent=False, delay=300)

    async def run_dungeon():
        await asyncio.sleep(timers[diff])
        active_dungeons.pop(user.id, None)
        fp = get_player(user.id)
        if not fp: return
        results      = []
        total_exp    = 0
        total_gold   = 0
        items_found  = []
        hp_remaining = fp["max_hp"]
        run_failed   = False
        line = get_class_line(fp)
        for i, room_type in enumerate(rooms, 1):
            if run_failed: break
            result = _resolve_dungeon_room(
                fp, room_type, theme, diff, i, hp_remaining, line)
            hp_remaining = max(1, hp_remaining - result.get("hp_cost", 0))
            total_exp  += result.get("exp", 0)
            total_gold += result.get("gold", 0)
            if result.get("item"): items_found.append(result["item"])
            results.append(result)
            if hp_remaining <= 1 and not result.get("success"):
                run_failed = True
                results.append({"type":"defeat","narrative":(
                    f"Room {i+1} would have finished you. "
                    f"You make the call to retreat while you still can. "
                    f"The hall lets you go. This time.")})
        if not run_failed:
            boss_result = _resolve_dungeon_boss(fp, theme, diff, line)
            total_exp  += boss_result.get("exp", 0)
            total_gold += boss_result.get("gold", 0)
            if boss_result.get("item"): items_found.append(boss_result["item"])
            results.append(boss_result)
            bonus = DUNGEON_LOOT[diff]["completion_bonus"]
            total_exp  += bonus["exp"]
            total_gold += bonus["gold"]
        lmsgs, leveled = add_exp(fp, total_exp)
        fp["gold"] = fp.get("gold", 0) + total_gold
        for item in items_found: add_item(fp, item)
        if not run_failed:
            for _d, _e, _g in track_objective(fp, "dungeon_run"):
                fp["gold"] = fp.get("gold", 0) + _g; add_exp(fp, _e)
        save_player(fp)
        recap = _build_dungeon_recap(
            fp, theme, diff, results, total_exp, total_gold,
            items_found, run_failed, lmsgs)
        await announce(context.bot, chat_id, recap, delay=180)
        if leveled and fp["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{fp['username']}* reached *Level {fp['level']}* "
                f"from the depths of *{theme['name']}*! 🏰", permanent=True))

    task = asyncio.create_task(run_dungeon())
    active_dungeons[user.id] = task


async def dungeonhard_cmd(update, context):
    context.args = ["hard"]
    await dungeon_cmd(update, context)

async def dungeonlegendary_cmd(update, context):
    context.args = ["legendary"]
    await dungeon_cmd(update, context)

async def rankme_cmd(update, context):
    context.args = ["me"]
    await rank_cmd(update, context)

async def rankwins_cmd(update, context):
    context.args = ["wins"]
    await rank_cmd(update, context)


GUIDE_PAGES = [
    # Page 1 - Getting Started
    (
        "🎱 *8Ball World  -  Getting Started* (1/9)\n"
        "\n"
        "Welcome to 8Ball World  -  a fantasy RPG built inside Telegram.\n"
        "\n"
        "*Two ways to play:*\n"
        "Shadow  -  Just chat in the group. You earn EXP automatically from messages and level up over time. No setup needed.\n"
        "\n"
        "RPG  -  Full game with classes, gear, combat, raids, and gold. To join, send /ascend to this bot in a *private message*.\n"
        "\n"
        "*Your first steps as an RPG player:*\n"
        "1. Send /ascend in DM to create your character\n"
        "2. Use /hustle daily to earn EXP, gold, and loot\n"
        "3. Pick a class at Level 5 with /class\n"
        "4. Equip gear and start fighting at Level 3+\n"
        "\n"
        "💡 Chatting in the group earns passive EXP. Your Shadow and RPG levels stay in sync. Level-up announcements broadcast at every 10th level."
    ),
    # Page 2 - Character Building
    (
        "🎱 *8Ball World  -  Building Your Character* (2/9)\n"
        "\n"
        "Use /class at Level 5 to pick your starting class. Browse with arrows to see each class's Path A and Path B.\n"
        "\n"
        "⚔️ *Warrior* — STR. Tank/bruiser. Absorbs hits, dominates the battlefield.\n"
        "  Path A (Paladin): Holy tank — shields, group buffs, divine nukes\n"
        "  Path B (Warlord): Pure damage — Triple Strike, Rampage, Decimation\n"
        "\n"
        "🔮 *Mage* — INT. Powerful spells and crowd control.\n"
        "  Path A (Sage): Pure magic — Chain Lightning, Meteor AOE, Absolute Zero\n"
        "  Path B (Void Mage): Dark arts — Hexes, drain, void collapse\n"
        "\n"
        "🔪 *Thief* — LUK/AGI. Crits, evasion, gold generation.\n"
        "  Path A (Wraith): Ghost — stealth, phantom strike, undetectable dodge\n"
        "  Path B (Specialist): Assassination — poison, bleeds, execute\n"
        "\n"
        "🏹 *Archer* — DEX. Precision and bounty hunting.\n"
        "  Path A (Strider): Ranger — steady aim, nature bond, arrow storm\n"
        "  Path B (Deadeye): Bounty — contracts, 12-hour kills, escalating damage\n"
        "\n"
        "📿 *Priest* — WIS. The only class that can revive players.\n"
        "  Path A (Saint): Holy healer — group heals, mass resurrection, EXP aura\n"
        "  Path B (Zealot): Dark cleric — condemn (unrevivable), curse stacking\n"
        "\n"
        "🌸 *Botanist* — WIS. Nature magic, healing, and deadly poisons.\n"
        "  Path A (Wildflower Empress): Healing/support — bloom heals, petal veil, Garden of Eden\n"
        "  Path B (Nature's Chosen): Offense/poison — thorn aura, toxic bloom, Wrath of the Wild\n"
        "\n"
        "💜 *Enchantress* — INT. Charms, hexes, and party buffs.\n"
        "  Path A (Dread Empress): Curse stacking — hexmark, doom curse, mass debuffs\n"
        "  Path B (Grand Muse): Party support — war song, ancient aria, Magnum Opus\n"
        "\n"
        "⚡ *Valkyrie* — STR. Norse warrior-healer hybrid.\n"
        "  Path A (Iron Valkyrie): Defense — block, runic ward, Bifrost Descent\n"
        "  Path B (Divine Tempest): Lightning offense — storm crits, chain lightning, Valhalla's Thunder\n"
        "\n"
        "🌀 *Phantom Dancer* — AGI. Evasion, combos, and ghost-step.\n"
        "  Path A (Danse Macabre): Combo offense — blade storm, thousand cuts, Macabre Finale\n"
        "  Path B (Ethereal Sovereign): Evasion — phase step, mist form, Ethereal Storm\n"
        "\n"
        "At Lv 10, use /prestige to choose Path A or B. Class evolves at Lv 30, 60, 100.\n"
        "\n"
        "*Stats:* STR — Physical dmg | INT — Magic dmg | AGI — Dodge | DEX — Crit | WIS — Healing | LUK — Loot"
    ),
    # Page 3 - Daily Activities
    (
        "🎱 *8Ball World  -  Daily Activities* (3/9)\n"
        "\n"
        "The fastest way to grow is to run all your activities regularly. Use /hustle to do them all at once.\n"
        "\n"
        "*Activities and their cooldowns:*\n"
        "/claim  -  Daily streak reward. Gold + bonus materials every day. Streak builds over consecutive days (24 hours)\n"
        "/daily  -  Gold + EXP reward  (24 hours)\n"
        "/train  -  EXP gain with class bonus  (30 min)\n"
        "/quest  -  EXP + gold + possible loot  (1 hour)\n"
        "/explore  -  Best loot drops, big EXP  (1hr, 2x per day)\n"
        "/pool  -  Roll for EXP, gold, and items  (8 seconds)\n"
        "/dungeon  -  Dungeon Run solo boss encounter  (once per day)\n"
        "/dungeonhard  -  Harder dungeon run, better rewards (Lv 15+)\n"
        "/dungeonlegendary  -  Hardest dungeon run, best loot (Lv 40+)\n"
        "\n"
        "💡 /pool is your main source of rare weapons and accessories. The rarer the roll (epic, legendary), the better the potential drop. Keep rolling.\n"
        "\n"
        "💡 /hustle runs all ready cooldowns at once — daily, train, quest, pool, claim, and explore. Use it every time you're in the group."
    ),
    # Page 4 - Combat & Raids
    (
        "🎱 *8Ball World  -  Combat & Raids* (4/9)\n"
        "\n"
        "*PvP  -  Player vs Player*\n"
        "Reply to any player's message and use /attack to fight them. Winners steal gold and EXP. Losers are defeated for 6 hours and lose 10% EXP.\n"
        "\n"
        "*Killstreaks*\n"
        "Every consecutive kill without dying extends your streak (shown in /who with 🔥). Streaks reset on death.\n"
        "\n"
        "*Revenge*\n"
        "When you're killed, you gain a 24-hour revenge window. Attacking your killer deals +15% bonus damage (one-time).\n"
        "\n"
        "*Wanted*\n"
        "Kill 5+ players in a single day and you become 🔴 WANTED — visible on /who and /war. High-risk, high-reward.\n"
        "\n"
        "*/who Icons*\n"
        "❤️ Healthy (above 50% HP)  |  🟡 Injured (25–50%)  |  🔴 Critical (below 25%)\n"
        "💀 Defeated — out for 6 hours, cannot be attacked\n"
        "🛡️ Invincible — immune to all damage (from revival items or Priest skills)\n"
        "🔥×N Kill streak  |  🔴 WANTED — 5+ kills today  |  💰 Active bounty on this player\n"
        "\n"
        "*Duels and Arena*\n"
        "/duel  -  Reply to a player to challenge them. Pick a wager via buttons (0 = free). Decided by Combat Power.\n"
        "/arena  -  Reply to a player for turn-based skill combat.\n"
        "\n"
        "*Boss Fights*\n"
        "Use /boss to start a group boss encounter (button menu). /attack and /skill redirect to the boss automatically while it's active.\n"
        "\n"
        "*Raids*\n"
        "/raid  -  Create a party (up to 4 players). Others type /raid to join. Use /raidstart when ready.\n"
        "Turn-based: each player has 25 seconds to /attack or /skill before it auto-advances.\n"
        "/soloraid  -  Private raid scaled to your level. Great for solo farming.\n"
        "\n"
        "*Defeat & Revival*\n"
        "When your HP hits 0 you are defeated for 6 hours and lose 10% EXP. Options to recover:\n"
        "• Wait it out (6 hours)\n"
        "• Use *Scroll of Revival* from your inventory (/use)\n"
        "• Ask a Priest to /heal you  -  they revive for free\n"
        "• 📿 Chalkers can also /heal themselves with no reply to self-revive\n"
        "\n"
        "*Pets in Combat*\n"
        "Your active pet auto-attacks with you. If attacked, it may trigger its defensive ability (intercept, counter, poison, stun, lifesteal, or shield). Defensive abilities unlock at pet Level 10."
    ),
    # Page 5 - Gear & Economy
    (
        "🎱 *8Ball World  -  Gear & Economy* (5/9)\n"
        "\n"
        "*Gear Slots*\n"
        "Weapon, Armor, Shield, Accessory. Use /equip to browse your bag and tap to equip. Use /unequip to remove gear.\n"
        "/enhance  -  Upgrade gear with Iron Shards. Tap the slot button. +1 to +10 max. Fails are possible at high levels.\n"
        "/enchant  -  Add random enchants via Enchanting Scrolls (up to 3 per item). Tap slot to enchant.\n"
        "/reinforce  -  Sacrifice a duplicate weapon or armor to permanently raise its base stats (+1 ATK/DEF per reinforce, max 20). Tap to select.\n"
        "/reinforce ascend  -  After 20 reinforces, Ascend the item to ★ tier (+5 flat bonus, resets to 0/20). Up to ★★★.\n"
        "\n"
        "*Consumable Items*\n"
        "Use /use to open your consumables and tap to use an item.\n"
        "• Health Potion — +50 HP\n"
        "• Greater Health Potion — +100 HP\n"
        "• Grand Restorative Flask — +200 HP\n"
        "• Scroll of Revival — Full self-revive from defeat (1 hour invincibility after)\n"
        "• Iron Shard — Used for /enhance\n"
        "• Iron Shard — Crafting material for /forge\n"
        "• Enchanting Scroll — Used for /enchant\n"
        "\n"
        "*Titles*\n"
        "/title — View your earned titles and tap to equip one. Titles show on your /stats and some grant stat bonuses.\n"
        "\n"
        "*Daily Claim*\n"
        "/claim — Daily reward with streak bonuses: Iron Shards (Day 3+), Iron Shards (Day 7+), Enchanting Scrolls (Day 14+).\n"
        "\n"
        "*Crafting*\n"
        "/forge — View recipes and craft items from Iron Shards.\n"
        "\n"
        "*Trading*\n"
        "/trade  -  Reply to a player to open the trade menu. Pick an item from buttons, then pick a price (or gift for free). They type /accept to complete it.\n"
        "\n"
        "*Economy*\n"
        "/inventory — Browse your bag by category. Tap 💰 Sell buttons to sell items directly.\n"
        "/shop  -  Daily rotating shop (Guild members get a discount at guild level 7+)\n"
        "\n"
        "*Set Bonuses*\n"
        "Equip matching legendary pieces to unlock set bonuses shown in /stats Gear page."
    ),
    # Page 6 - Command Reference
    (
        "🎱 *8Ball World  -  Command Reference* (6/9)\n"
        "\n"
        "*Character*\n"
        "/ascend  -  Create your RPG character (DM only)\n"
        "/stats  -  Your profile (or /stats @user)\n"
        "/class  -  Pick or view classes\n"
        "/prestige  -  Choose Path A or B (Lv 10+)\n"
        "/allocate [stat] [amt]  -  Spend stat points\n"
        "/resetstats  -  Refund all stat points\n"
        "/resetclass  -  Reset class (300g)\n"
        "/inventory  -  View your bag\n"
        "/gear  -  View equipped gear\n"
        "\n"
        "*Activities*\n"
        "/hustle  -  Run all ready cooldowns at once\n"
        "/daily  -  Daily gold + EXP (24hr)\n"
        "/train  -  EXP training (30min)\n"
        "/quest  -  EXP + gold + loot (1hr)\n"
        "/explore  -  Big drops, big EXP (1hr, 2x/day)\n"
        "/pool  -  Roll for EXP, gold, items (8s)\n"
        "/dungeon  -  Solo boss run (daily)\n"
        "/dungeonhard  -  Hard dungeon\n"
        "/dungeonlegendary  -  Legendary dungeon\n"
        "\n"
        "*Combat*\n"
        "/attack  -  Attack reply target or active boss\n"
        "/skill  -  Use your class skill in battle\n"
        "/duel  -  Reply to challenge. Wager buttons pop up.\n"
        "/arena  -  Reply for turn-based skill combat\n"
        "/heal  -  Heal yourself (or reply to heal ally). Chalkers heal free + can self-revive.\n"
        "/boss  -  Start a group boss (button menu)\n"
        "/raid  -  Create or join a raid party\n"
        "/raidstart  -  Start the raid\n"
        "/raidparty  -  View current party\n"
        "/soloraid  -  Private raid scaled to you\n"
        "\n"
        "*Gear & Economy*\n"
        "/equip  -  Browse bag and tap to equip\n"
        "/unequip  -  Tap a slot to unequip gear back to bag\n"
        "/enhance  -  Upgrade gear with Iron Shards (button menu)\n"
        "/enchant  -  Add enchants via Enchanting Scrolls (button menu)\n"
        "/reinforce  -  Tap to sacrifice duplicate gear for +1 ATK/DEF\n"
        "/use  -  Use a consumable (button menu)\n"
        "/title  -  View and equip your earned titles\n"
        "/objectives  -  View daily objectives\n"
        "/sell [rarity]  -  Bulk sell by rarity (common/uncommon/rare/epic/legendary)\n"
        "/forge  -  Craft items from materials\n"
        "/claim  -  Daily streak reward (gold + materials)\n"
        "/trade @user [item] [price]  -  Trade with a player\n"
        "/shop  -  Daily rotating shop\n"
        "\n"
        "*Leaderboards & Info*\n"
        "/rank  -  Leaderboard\n"
        "/rankme  -  Your rank\n"
        "/rankwins  -  Wins leaderboard\n"
        "/who  -  Active players with HP/status\n"
        "/history  -  Your last 5 PvP hits\n"
        "/war  -  Active bounties, guild wars, top killers\n"
        "/world  -  Current world info\n"
        "/changelog  -  Recent bot updates\n"
        "\n"
        "*Bounties*\n"
        "/bounty  -  Reply to a player. Amount buttons pop up (100–5000g). Multiple players can stack bounties!\n"
        "/bounties  -  View the active bounty board\n"
        "_Thief classes: no fee + premium amounts (up to 10,000g), max 3 contracts. Railrunner: no fee + Execution Order (2,000g bounty + Marked debuff via skill)._\n"
        "\n"
        "*Guilds*\n"
        "/guildjoin  -  Browse + join a guild\n"
        "/guildcreate [name]  -  Create a guild (100g)\n"
        "/guildinfo [Guild Name]  -  Your guild details (or look up any guild)\n"
        "/guildlist  -  All active guilds\n"
        "/guilddonate [amt]  -  Donate gold to guild\n"
        "/guildkick @user  -  Kick member (leader)\n"
        "/guildleave  -  Leave your guild\n"
        "/guilddisband confirm  -  Disband your guild\n"
        "/guildwar  -  Declare war via guild picker (leader, 24hr)\n"
        "/gbank deposit/withdraw  -  Guild bank\n"
        "\n"
        "*Marriage*\n"
        "/marry  -  Propose (reply to target) or check marriage status\n"
        "/divorce  -  End your marriage (button confirmation)"
    ),
    # Page 7 - Guilds & Advanced
    (
        "🎱 *8Ball World  -  Guilds & Advanced Systems* (7/9)\n"
        "\n"
        "*Guilds*\n"
        "Guilds level up as members donate gold via /guilddonate, unlocking EXP bonuses, shop discounts, and more.\n"
        "/guildjoin  -  Browse and join a Guild\n"
        "/guildcreate [name]  -  Create a Guild (100g)\n"
        "/guildinfo  -  View your Guild details and perks\n"
        "\n"
        "*Guild Bank*\n"
        "/gbank — View the Guild treasury. Members can deposit gold. Leaders can withdraw for upgrades or emergencies.\n"
        "\n"
        "*Guild Wars*\n"
        "/guildwar — Guild leaders tap a guild from the list to declare a 24-hour war.\n"
        "During a war, /guildwar shows the live score AND lists the enemy Guild members by name so you know who to hunt.\n"
        "Each kill against an enemy member scores a point. Most points after 24 hours wins.\n"
        "Each war kill also counts as double EXP toward your daily objectives.\n"
        "When the war ends, the winning Guild earns +2,000 Guild EXP (ties get +500 each) and a Win is recorded on /war.\n"
        "/guildinfo [Guild Name] — Look up any Guild's members, level, and war record.\n"
        "\n"
        "*Bounties*\n"
        "/bounty  -  Reply to any player's message. Amount buttons appear (100–5000g). Multiple players can stack bounties on the same target.\n"
        "/bounties  -  View the live bounty board\n"
        "Defeating a player who has active bounties automatically claims all stacked rewards.\n"
        "If someone else collects your bounty, you get 25% of it back as a finder's fee.\n"
        "_Railrunner's Execution Order: places a 2,000g bounty via skill + marks the target (+20% dmg taken 30 min)._\n"
        "\n"
        "*Kill Streaks & Wanted System*\n"
        "Every kill without dying extends your streak (visible in /who). 5+ kills in one day marks you as 🔴 WANTED — higher risk but all eyes on you.\n"
        "\n"
        "🎱 *Good luck on your adventure.*"
    ),
    # Page 8 - Pets
    (
        "🎱 *8Ball World  -  Pets* (8/9)\n"
        "\n"
        "*Getting a Pet*\n"
        "Buy eggs from the Pet Shop (/petshop) or find them in dungeons and quests.\n"
        "Use /hatch to hatch an egg. You can own multiple pets but only one is active at a time.\n"
        "\n"
        "*Pet Combat (Automatic)*\n"
        "Your active pet auto-attacks alongside you every /attack or /skill.\n"
        "Well-fed pets (hunger > 20) with good mood (mood > 40) join the fight.\n"
        "When YOU are attacked, your pet may trigger its defensive ability:\n"
        "🛡️ Intercept — absorbs a portion of incoming damage\n"
        "⚔️ Counter Strike — retaliates against the attacker\n"
        "🐍 Venom Bite — poisons the attacker\n"
        "⚡ Stunning Blow — stuns the attacker (miss next attack)\n"
        "💜 Life Drain — steals HP from attacker and heals you\n"
        "✨ Aura Shield — reduces incoming damage\n"
        "Defensive abilities unlock at pet Level 10.\n"
        "\n"
        "*Pet Care*\n"
        "Use /pet to manage your pet. Feed with 🍖 and train with 🏋️.\n"
        "Hungry or sad pets won't fight at full power.\n"
        "Keep hunger > 20 and mood > 40 for full combat effectiveness.\n"
        "\n"
        "*Pet Leveling*\n"
        "Your pet earns 15% of all EXP you gain — passively, with no effort required.\n"
        "Pets level from 1 to 100. As they grow:\n"
        "  L5+: Attack bonus begins\n"
        "  L10: Defensive ability unlocks\n"
        "  L15: Crit bonus starts\n"
        "  L25: Dodge bonus starts\n"
        "  L40: Lifesteal passive starts\n"
        "  L75–100: Elite tier bonuses\n"
        "\n"
        "*Species & Rarity*\n"
        "Common → Uncommon → Rare → Epic → Legendary → Mythic\n"
        "Higher rarity = higher base stats and better ability proc chance.\n"
        "55+ species: dogs, cats, dragons, wolves, bears, birds, snakes, horses, fantasy beasts.\n"
        "\n"
        "*Commands*\n"
        "/pet — manage your active pet\n"
        "/petshop — buy eggs and snacks\n"
        "/hatch — hatch an egg from your inventory\n"
        "/petrename [name] — rename your active pet\n"
    ),
    # Page 9 - Marriage
    (
        "🎱 *8Ball World  -  Marriage* (9/9)\n"
        "\n"
        "*Getting Married*\n"
        "Reply to any player's message and type /marry to propose.\n"
        "The proposal costs *1,000 gold from each partner* (2,000 total).\n"
        "Your partner gets Accept / Decline buttons. Proposal expires in 5 minutes.\n"
        "\n"
        "*Marriage Benefits*\n"
        "💍 Marriage is shown on your /stats profile\n"
        "🏅 Both partners receive the exclusive *Beloved* title\n"
        "✨ +3% EXP bonus on every EXP gain, forever\n"
        "\n"
        "*Commands*\n"
        "/marry — Propose (reply to partner) or check your own marriage status\n"
        "/divorce — End the marriage (confirmation button required)\n"
        "\n"
        "*Notes*\n"
        "• You can only be married to one person at a time\n"
        "• Divorce removes the EXP bonus for both partners\n"
        "• Marriage date shows on your /stats profile\n"
        "• The Beloved title remains earned even after divorce\n"
        "\n"
        "💍 _Love in a Telegram RPG. We're not judging._"
    ),
]

GUIDE_PAGE_LABELS = ["Getting Started", "Character", "Activities", "Combat", "Gear & Economy", "Commands", "Guilds & Advanced", "Pets", "Marriage"]

async def _send_guide_page(chat_id: int, bot, page: int, edit_msg=None):
    total = len(GUIDE_PAGES)
    page  = max(1, min(page, total))
    text  = GUIDE_PAGES[page - 1]
    row   = []
    if page > 1:
        row.append(InlineKeyboardButton(f"◀ {GUIDE_PAGE_LABELS[page-2]}", callback_data=f"guide_p_{page-1}"))
    if page < total:
        row.append(InlineKeyboardButton(f"{GUIDE_PAGE_LABELS[page]} ▶", callback_data=f"guide_p_{page+1}"))
    markup = InlineKeyboardMarkup([row]) if row else None
    if edit_msg:
        await edit_msg.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await bot.send_message(chat_id=chat_id, text=text,
                               parse_mode="Markdown", reply_markup=markup)

async def guide_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    await _send_guide_page(query.message.chat.id, context.bot, page, edit_msg=query.message)

# ═══════════════════════════════════════════════════════════════════════════════
# PET COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

async def pet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "🐾 Register first with /start.", delay=9); return
    try: await update.message.delete()
    except: pass
    pet = get_active_pet_record(user.id)
    if not pet:
        text = (f"🐾 *{p['username']}'s Pets*\n\n"
                "You don't have an active pet yet!\n"
                "Get eggs from dungeons, quests, or the *Pet Shop*.\n"
                "Get eggs from the *Pet Shop*, then hatch them from your bag using /hatch or the button below!")
        markup = _pet_main_markup()
    else:
        text = _build_pet_card(pet)
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🍖 Feed",    callback_data=f"petfeed_{pet['pet_id']}"),
             InlineKeyboardButton("🏋️ Train",  callback_data=f"pettrain_{pet['pet_id']}")],
            [InlineKeyboardButton("📝 Rename",  callback_data=f"petrename_{pet['pet_id']}"),
             InlineKeyboardButton("📋 All Pets", callback_data="petlist_0")],
            [InlineKeyboardButton("🛒 Pet Shop", callback_data="petshop")],
        ])
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown",
        reply_markup=markup)
    asyncio.create_task(_auto_delete(context.bot, update.effective_chat.id, msg.message_id, 120))

async def petshop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: await update.message.delete()
    except: pass
    user = update.effective_user
    p = get_player(user.id)
    if not p: return
    text, markup = _build_petshop_menu(p)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown",
        reply_markup=markup)
    asyncio.create_task(_auto_delete(context.bot, update.effective_chat.id, msg.message_id, 90))

def _build_petshop_menu(p):
    text = (f"🐾 *Pet Shop*\n💰 Your Gold: *{p.get('gold',0):,}g*\n\n"
            "Buy eggs then tap *🥚 Hatch Egg* in your pet menu!\n\n"
            "🥚 *Common Egg* — 300g\nCommon or Uncommon pet\n\n"
            "🥚 *Rare Egg* — 800g\nUncommon to Rare pet\n\n"
            "🥚 *Dragon Egg* — 2,000g\nRare to Epic pet\n\n"
            "🥚 *Mythic Egg* — 5,000g\nEpic to Mythic pet\n\n"
            "🍖 *Pet Snack* — 25g\nFeeds your active pet")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥚 Common Egg  300g",  callback_data="pbuy_Common Egg_300"),
         InlineKeyboardButton("🥚 Rare Egg  800g",    callback_data="pbuy_Rare Egg_800")],
        [InlineKeyboardButton("🥚 Dragon Egg  2000g", callback_data="pbuy_Dragon Egg_2000"),
         InlineKeyboardButton("🥚 Mythic Egg  5000g", callback_data="pbuy_Mythic Egg_5000")],
        [InlineKeyboardButton("🍖 Pet Snack  25g",    callback_data="pbuy_Pet Snack_25")],
        [InlineKeyboardButton("🔙 Back",              callback_data="petmain")],
    ])
    return text, markup

async def petshop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user  = query.from_user
    p = get_player(user.id)
    if not p: await query.answer("Register first.", show_alert=True); return
    data = query.data  # petshop or pbuy_ItemName_price

    if data == "petshop":
        text, markup = _build_petshop_menu(p)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        await query.answer()
        return

    # pbuy_ItemName_price
    _, item_name, price_str = data.split("_", 2)
    price = int(price_str)
    if p.get("gold", 0) < price:
        await query.answer(f"Not enough gold! Need {price:,}g.", show_alert=True); return
    p["gold"] -= price
    inv = sjl(p.get("inventory"), [])
    inv.append(item_name)
    p["inventory"] = json.dumps(inv)
    save_player(p)
    await query.answer(f"✅ Bought {item_name}! Use /hatch to hatch eggs.")
    text, markup = _build_petshop_menu(p)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

async def hatch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    if not p:
        await send_group(update, "Register first.", delay=8); return
    inv = sjl(p.get("inventory"), [])
    egg_types = ["Common Egg","Rare Egg","Dragon Egg","Mythic Egg"]
    egg = next((e for e in egg_types if e in inv), None)
    if not egg:
        await send_group(update, "🥚 You don't have any eggs. Buy them from the *Pet Shop* (/petshop).", delay=12); return
    try: await update.message.delete()
    except: pass
    inv.remove(egg)
    p["inventory"] = json.dumps(inv)
    save_player(p)
    species_id = _hatch_species(egg)
    if not species_id:
        await send_group(update, "❌ The egg crumbled. Nothing hatched.", delay=10); return
    sp = PET_SPECIES[species_id]
    new_pet = {
        "owner_id": user.id, "species": species_id,
        "nickname": None, "level": 1, "exp": 0,
        "hunger": 100, "mood": 100,
        "last_fed": None, "last_trained": None,
        "is_active": 0, "created_at": datetime.now().isoformat(),
    }
    # Auto-activate if no active pet
    all_pets = get_all_pets(user.id)
    if not any(pet.get("is_active") for pet in all_pets):
        new_pet["is_active"] = 1
    save_pet(new_pet)
    rar_e = RARITY_EMOJI.get(sp["rarity"],"")
    elem_e = ELEMENT_EMOJI.get(sp["element"],"")
    active_note = " They're now your active companion!" if new_pet["is_active"] else " Use /pet → All Pets to activate them."
    text = (f"🥚 *Hatch!*\n\n"
            f"{sp['emoji']} *{sp['name']}* appeared!\n"
            f"{rar_e} {sp['rarity'].capitalize()}  |  {elem_e} {sp['element'].capitalize()}\n\n"
            f"_{sp['desc']}_\n\n"
            f"Base ATK: +{sp['base_atk']}  |  Base DEF: +{sp['base_def']}\n"
            f"Personality: {PERSONALITY_EMOJI.get(sp['personality'],'')} {sp['personality'].capitalize()}\n\n"
            + active_note)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")
    asyncio.create_task(_auto_delete(context.bot, update.effective_chat.id, msg.message_id, 60))

async def hatch_egg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback version of hatch_cmd triggered by the 🥚 Hatch Egg button."""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    p = get_player(user.id)
    if not p:
        await query.answer("Register first.", show_alert=True); return
    inv = sjl(p.get("inventory"), [])
    egg_types = ["Common Egg","Rare Egg","Dragon Egg","Mythic Egg"]
    egg = next((e for e in egg_types if e in inv), None)
    if not egg:
        await query.answer("🥚 No eggs in your bag! Buy some from the Pet Shop.", show_alert=True); return
    inv.remove(egg)
    p["inventory"] = json.dumps(inv)
    save_player(p)
    species_id = _hatch_species(egg)
    if not species_id:
        await query.answer("❌ The egg crumbled. Nothing hatched.", show_alert=True); return
    sp = PET_SPECIES[species_id]
    new_pet = {
        "owner_id": user.id, "species": species_id,
        "nickname": None, "level": 1, "exp": 0,
        "hunger": 100, "mood": 100,
        "last_fed": None, "last_trained": None,
        "is_active": 0, "created_at": datetime.now().isoformat(),
    }
    all_pets = get_all_pets(user.id)
    if not any(pet.get("is_active") for pet in all_pets):
        new_pet["is_active"] = 1
    save_pet(new_pet)
    rar_e  = RARITY_EMOJI.get(sp["rarity"],"")
    elem_e = ELEMENT_EMOJI.get(sp["element"],"")
    active_note = " Now your active companion!" if new_pet["is_active"] else " Activate via /pet → All Pets."
    text = (f"🥚 *Hatch!*\n\n"
            f"{sp['emoji']} *{sp['name']}* appeared!\n"
            f"{rar_e} {sp['rarity'].capitalize()}  |  {elem_e} {sp['element'].capitalize()}\n\n"
            f"_{sp['desc']}_\n\n"
            f"Base ATK: +{sp['base_atk']}  |  Base DEF: +{sp['base_def']}\n"
            f"Personality: {PERSONALITY_EMOJI.get(sp['personality'],'')} {sp['personality'].capitalize()}\n\n"
            + active_note)
    msg = await context.bot.send_message(
        chat_id=query.message.chat.id, text=text, parse_mode="Markdown")
    asyncio.create_task(_auto_delete(context.bot, query.message.chat.id, msg.message_id, 60))

async def pet_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles petmain, petlist_N, petview_ID, petactivate_ID, petfeed_ID, pettrain_ID, petrelease_ID"""
    query = update.callback_query
    user  = query.from_user
    data  = query.data

    if data == "petmain":
        p = get_player(user.id)
        pet = get_active_pet_record(user.id)
        if not pet:
            text = "🐾 No active pet. Get eggs from dungeons or the Pet Shop!"
            markup = _pet_main_markup()
        else:
            text = _build_pet_card(pet)
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🍖 Feed",    callback_data=f"petfeed_{pet['pet_id']}"),
                 InlineKeyboardButton("🏋️ Train",  callback_data=f"pettrain_{pet['pet_id']}")],
                [InlineKeyboardButton("📝 Rename",  callback_data=f"petrename_{pet['pet_id']}"),
                 InlineKeyboardButton("📋 All Pets", callback_data="petlist_0")],
                [InlineKeyboardButton("🛒 Pet Shop", callback_data="petshop")],
            ])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        await query.answer(); return

    if data.startswith("petlist_"):
        page = int(data.split("_")[1])
        pets = get_all_pets(user.id)
        if not pets:
            await query.edit_message_text("🐾 You have no pets yet!", reply_markup=_pet_main_markup())
            await query.answer(); return
        await query.edit_message_text(
            f"🐾 *Your Pets* ({len(pets)} total)\nTap a pet to view or manage.",
            parse_mode="Markdown", reply_markup=_pet_list_markup(pets, page))
        await query.answer(); return

    if data.startswith("petview_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone(); conn.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row); _decay_pet(pet)
        await query.edit_message_text(_build_pet_card(pet), parse_mode="Markdown",
            reply_markup=_pet_view_markup(pid, bool(pet.get("is_active"))))
        await query.answer(); return

    if data.startswith("petactivate_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE pets SET is_active=0 WHERE owner_id=?", (user.id,))
        c.execute("UPDATE pets SET is_active=1 WHERE pet_id=? AND owner_id=?", (pid, user.id))
        conn.commit(); conn.close()
        conn2 = sqlite3.connect(DB_PATH); conn2.row_factory = sqlite3.Row; c2 = conn2.cursor()
        c2.execute("SELECT * FROM pets WHERE pet_id=?", (pid,))
        row = c2.fetchone(); conn2.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row); _decay_pet(pet)
        sp = PET_SPECIES.get(pet["species"],{})
        await query.answer(f"✅ {sp.get('name','Pet')} is now your active companion!")
        await query.edit_message_text(_build_pet_card(pet), parse_mode="Markdown",
            reply_markup=_pet_view_markup(pid, True)); return

    if data.startswith("petfeed_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone(); conn.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row); _decay_pet(pet)
        p = get_player(user.id)
        inv = sjl(p.get("inventory"), [])
        sp = PET_SPECIES.get(pet["species"], {})
        pname = _pet_display_name(pet)
        pers  = sp.get("personality","calm")
        if "Pet Snack" in inv:
            inv.remove("Pet Snack"); p["inventory"] = json.dumps(inv); save_player(p)
            cost_note = "_(used 1 Pet Snack)_"
        elif p.get("gold",0) >= 10:
            p["gold"] -= 10; save_player(p)
            cost_note = "_(cost 10g)_"
        else:
            await query.answer("No Pet Snacks and not enough gold (need 10g).", show_alert=True); return
        pet["hunger"] = min(100, pet.get("hunger",0) + 30)
        pet["mood"]   = min(100, pet.get("mood",0)   + 10)
        pet["last_fed"] = datetime.now().isoformat()
        save_pet(pet)
        feed_msg = PERSONALITY_FEED.get(pers, "eats happily.")
        await query.answer(f"🍖 Fed {pname}!")
        await query.edit_message_text(
            f"🍖 *{pname}* {feed_msg}\n{cost_note}\n\n" + _build_pet_card(pet),
            parse_mode="Markdown", reply_markup=_pet_view_markup(pid, bool(pet.get("is_active")))); return

    if data.startswith("pettrain_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone(); conn.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row); _decay_pet(pet)
        sp = PET_SPECIES.get(pet["species"], {})
        pname = _pet_display_name(pet)
        pers  = sp.get("personality","calm")
        # Cooldown: 4 hours
        last_trained = pet.get("last_trained")
        if last_trained:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(last_trained)).total_seconds()
                if elapsed < 14400:
                    remaining = round((14400 - elapsed) / 60)
                    await query.answer(f"⏳ {pname} needs rest. Try again in {remaining} min.", show_alert=True); return
            except Exception: pass
        if pet.get("hunger", 100) < 20:
            await query.answer(f"😫 {pname} is too hungry to train! Feed them first.", show_alert=True); return
        gain = 30 + pet.get("level",1) * 5
        pet["exp"] += gain
        pet["mood"] = min(100, pet.get("mood",100) + 5)
        pet["last_trained"] = datetime.now().isoformat()
        # Level up
        lvl_ups = []
        while pet["exp"] >= pet_exp_for_level(pet["level"]):
            pet["exp"] -= pet_exp_for_level(pet["level"])
            pet["level"] += 1
            lvl_ups.append(pet["level"])
        save_pet(pet)
        train_msg = PERSONALITY_TRAIN.get(pers, "trains diligently.")
        lvl_note = "".join(f"\n🎉 *Level Up!* {pname} is now level {l}!" for l in lvl_ups)
        await query.answer(f"🏋️ {pname} trained! +{gain} EXP")
        await query.edit_message_text(
            f"🏋️ *{pname}* {train_msg}\n+{gain} EXP gained!{lvl_note}\n\n" + _build_pet_card(pet),
            parse_mode="Markdown", reply_markup=_pet_view_markup(pid, bool(pet.get("is_active")))); return

    if data.startswith("petrelease_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone(); conn.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row)
        sp = PET_SPECIES.get(pet["species"],{})
        pname = _pet_display_name(pet)
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("💔 Yes, release", callback_data=f"petrelease_confirm_{pid}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"petview_{pid}"),
        ]])
        await query.edit_message_text(
            f"⚠️ *Release {pname}?*\n\nThis is permanent. {pname} will be gone forever.",
            parse_mode="Markdown", reply_markup=markup)
        await query.answer(); return

    if data.startswith("petrelease_confirm_"):
        pid = int(data.split("_")[2])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone()
        if not row: conn.close(); await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row); sp = PET_SPECIES.get(pet["species"],{})
        pname = _pet_display_name(pet)
        c.execute("DELETE FROM pets WHERE pet_id=?", (pid,)); conn.commit(); conn.close()
        await query.answer(f"💔 {pname} has been released.")
        await query.edit_message_text(
            f"💔 *{pname}* has been released into the wild.\n_Goodbye, old friend._",
            parse_mode="Markdown"); return

    if data == "petshop":
        p = get_player(user.id)
        text, markup = _build_petshop_menu(p)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        await query.answer(); return

    if data.startswith("petrename_"):
        pid = int(data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT * FROM pets WHERE pet_id=? AND owner_id=?", (pid, user.id))
        row = c.fetchone(); conn.close()
        if not row: await query.answer("Pet not found.", show_alert=True); return
        pet = dict(row)
        sp = PET_SPECIES.get(pet["species"], {})
        pname = _pet_display_name(pet)
        await query.answer(
            f"Type /petrename <name> in chat to rename {pname}!\nExample: /petrename Shadow",
            show_alert=True)
        return

    await query.answer()

async def petrename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    if not p: return
    pet = get_active_pet_record(user.id)
    if not pet:
        await send_group(update, "🐾 No active pet to rename.", delay=8); return
    args = context.args
    if not args:
        await send_group(update, "Usage: `/petrename <nickname>`", delay=8); return
    nickname = " ".join(args)[:24]
    pet["nickname"] = nickname
    save_pet(pet)
    sp = PET_SPECIES.get(pet["species"],{})
    await send_group(update, f"📝 Your {sp.get('name','pet')} is now called *{nickname}*!", delay=15)

async def guide_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await _send_guide_page(user.id, context.bot, page=1)
        if update.effective_chat.id != user.id:
            try: await update.message.delete()
            except: pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📖 *{user.first_name}*, check your DMs for the guide!",
                parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"📖 *{user.first_name}*  -  start a DM with me first, then use /guide again!",
            parse_mode="Markdown")

# ── POOL ACTIVITY ─────────────────────────────────────────────────────────────
POOL_SHOTS = [
    {"id":"scratch","weight":40,"rarity":"common",
     "text":"Scratch. Cue ball drops into the corner pocket. Rookie mistake.",
     "exp":19,"gold":0,"loot":None},
    {"id":"rail_kiss","weight":40,"rarity":"common",
     "text":"Rail kiss, no pocket. The felt absorbs the hit and gives nothing back.",
     "exp":25,"gold":0,"loot":None},
    {"id":"cluster_stuck","weight":40,"rarity":"common",
     "text":"You crack the cluster but nothing drops. The rack laughs at you.",
     "exp":25,"gold":2,"loot":None},
    {"id":"thin_cut","weight":38,"rarity":"common",
     "text":"Thin cut on the 3 ball. It grazes the pocket and rolls away.",
     "exp":31,"gold":3,"loot":None},
    {"id":"safe_play","weight":38,"rarity":"common",
     "text":"You play safe. Smart. Boring. The table respects it.",
     "exp":38,"gold":5,"loot":None},
    {"id":"solid_pot","weight":35,"rarity":"common",
     "text":"Clean pot on the 2 ball. Nothing fancy, just good fundamentals.",
     "exp":44,"gold":5,"loot":None},
    {"id":"two_ball_run","weight":35,"rarity":"common",
     "text":"Two ball run before the pattern breaks. You'll take it.",
     "exp":50,"gold":8,"loot":[("Health Potion",0.08)]},
    {"id":"long_pot","weight":33,"rarity":"common",
     "text":"Long pot, full length of the table. The satisfying thud of a good hit.",
     "exp":56,"gold":8,"loot":[("Health Potion",0.10)]},
    {"id":"three_cushion","weight":30,"rarity":"common",
     "text":"Three cushion shot, exactly as planned. Nobody saw it but you know.",
     "exp":63,"gold":10,"loot":[("Health Potion",0.12)]},
    {"id":"position_play","weight":30,"rarity":"common",
     "text":"Perfect position play. You pot the ball and land exactly where you wanted.",
     "exp":69,"gold":12,"loot":[("Health Potion",0.12),("Brass Ring",0.05)]},
    {"id":"break_and_run","weight":20,"rarity":"uncommon",
     "text":"Break and run. Four targets drop on the break and you clear the field from there.",
     "exp":100,"gold":20,"loot":[("Greater Health Potion",0.12),("Iron Shard Ring",0.08)]},
    {"id":"masse_shot","weight":20,"rarity":"uncommon",
     "text":"Massé shot curves around the obstacle perfectly. The crowd would have gone wild.",
     "exp":106,"gold":22,"loot":[("Greater Health Potion",0.15),("Scout's Pendant",0.08)]},
    {"id":"bank_pot","weight":18,"rarity":"uncommon",
     "text":"Bank pot off the far wall drops clean. Calculated.",
     "exp":113,"gold":25,"loot":[("Greater Health Potion",0.15),("Iron Shard",0.06)]},
    {"id":"combo_pot","weight":18,"rarity":"uncommon",
     "text":"Combo strike  -  clips the 5, sends the 7 into the corner. Beautiful.",
     "exp":119,"gold":28,"loot":[("Greater Health Potion",0.15),("Iron Shard",0.08)]},
    {"id":"five_ball_run","weight":16,"rarity":"uncommon",
     "text":"Five target run. Your focus is absolute. The field offers no resistance.",
     "exp":125,"gold":30,"loot":[("Iron Shard",0.12),("Worn Leather Band",0.08)]},
    {"id":"called_shot","weight":16,"rarity":"uncommon",
     "text":"Called shot  -  6 ball, side pocket, two walls. You called it. It dropped.",
     "exp":138,"gold":35,"loot":[("Iron Shard",0.15),("Silk Band",0.05)]},
    {"id":"century_break","weight":14,"rarity":"uncommon",
     "text":"Century break. You stop counting at twelve balls. The table is yours.",
     "exp":150,"gold":40,"loot":[("Iron Shard",0.18),("Bloodstone Band",0.06)]},
    {"id":"maximum_break","weight":8,"rarity":"rare",
     "text":"Maximum break. Every ball. Every pocket. The felt bows to your command.",
     "exp":250,"gold":80,"loot":[("Iron Shard",0.30),("Enchanting Scroll",0.12),("Fortune Coin",0.06)]},
    {"id":"trick_shot","weight":8,"rarity":"rare",
     "text":"Trick shot  -  a blind shot over the cluster, corner pocket. "
            "You don't even watch it drop. You already knew.",
     "exp":275,"gold":90,"loot":[("Iron Shard",0.30),("Enchanting Scroll",0.15),("War Master's Clasp",0.04)]},
    {"id":"ghost_ball","weight":7,"rarity":"rare",
     "text":"Ghost ball method on an impossible cut. The path threads a gap "
            "that shouldn't exist. It drops. You breathe.",
     "exp":300,"gold":100,"loot":[("Iron Shard",0.35),("Enchanting Scroll",0.18),("Hawk Eye Medallion",0.04)]},
    {"id":"full_rack_clear","weight":6,"rarity":"rare",
     "text":"Full rack clear on the break. All fifteen targets. One strike. "
            "The field is empty before the echo dies.",
     "exp":350,"gold":120,"loot":[("Iron Shard",0.40),("Enchanting Scroll",0.20),
                                   ("Scroll of Revival",0.08),("Phantom Loop",0.04)]},
    {"id":"void_pocket","weight":3,"rarity":"epic",
     "text":"The path leads toward a void that wasn't there a moment ago. "
            "A pocket between worlds. Something disappears. Something falls out "
            "that was never inside it.",
     "exp":625,"gold":200,"loot":[("Iron Shard",0.60),("Enchanting Scroll",0.35),
                                   ("Scroll of Revival",0.15),("Runed Heart",0.05),
                                   ("Eye of the Void",0.04)]},
    {"id":"eight_ball_break","weight":3,"rarity":"epic",
     "text":"8 ball on the break. Dead center. Corner pocket. "
            "The felt goes silent. Something ancient stirs beneath.",
     "exp":750,"gold":250,"loot":[("Iron Shard",0.65),("Enchanting Scroll",0.40),
                                   ("The Shadow Whisper",0.05),("Guardian's Talisman",0.04)]},
    {"id":"corner_pocket_singularity","weight":1,"rarity":"legendary",
     "text":"The void opens. Not just opens  -  becomes. "
            "Every target in the field rolls toward it simultaneously without being struck. "
            "They vanish one by one. The field is left perfectly bare. "
            "You didn't do that. Or maybe you did. The dust settles. "
            "Something was left behind.",
     "exp":1500,"gold":500,"loot":[("Iron Shard",0.80),("Enchanting Scroll",0.60),
                                    ("Shard of the Void",0.03),("Ring of the Endless",0.03),
                                    ("The Last Stand Locket",0.03)]},

    # ── Additional Common ────────────────────────────────────────────────
    {"id":"chalk_up","weight":38,"rarity":"common",
     "text":"You chalk up carefully. Take your time. Miss anyway.",
     "exp":22,"gold":0,"loot":None},

    {"id":"wrong_ball","weight":36,"rarity":"common",
     "text":"Wrong ball first. Foul. Your opponent would have loved that.",
     "exp":18,"gold":0,"loot":None},

    {"id":"kitchen_shot","weight":34,"rarity":"common",
     "text":"Ball in hand from the kitchen. You make the most of it.",
     "exp":38,"gold":6,"loot":[("Health Potion",0.10)]},

    {"id":"frozen_ball","weight":33,"rarity":"common",
     "text":"Frozen ball on the rail. You play it safe and take the defensive.",
     "exp":32,"gold":4,"loot":None},

    {"id":"diamond_system","weight":31,"rarity":"common",
     "text":"You use the diamond system for a kick shot. It works. You act like it always does.",
     "exp":42,"gold":7,"loot":[("Health Potion",0.08)]},

    {"id":"one_pocket_defense","weight":30,"rarity":"common",
     "text":"A defensive shot worthy of one pocket. Nothing to pocket but nowhere to run either.",
     "exp":45,"gold":9,"loot":[("Health Potion",0.10)]},

    {"id":"stroke_check","weight":28,"rarity":"common",
     "text":"You pause. Check your stroke. Restart. It was worth the delay.",
     "exp":48,"gold":10,"loot":[("Health Potion",0.12),("Brass Ring",0.05)]},

    # ── Additional Uncommon ──────────────────────────────────────────────
    {"id":"running_english","weight":18,"rarity":"uncommon",
     "text":"Running English off the far cushion opens the table completely. "
            "You read it perfectly.",
     "exp":105,"gold":32,"loot":[("Iron Shard",0.10),("Silk Band",0.07)]},

    {"id":"stun_shot","weight":17,"rarity":"uncommon",
     "text":"Stun shot. Dead stop. Exactly where you needed it. "
            "Nobody else saw that coming.",
     "exp":115,"gold":36,"loot":[("Iron Shard",0.12),("Shadowmark Signet",0.04)]},

    {"id":"screw_back","weight":16,"rarity":"uncommon",
     "text":"Strong draw back across the field. "
            "It returns to you like it owed you something.",
     "exp":125,"gold":40,"loot":[("Iron Shard",0.15),("Obsidian Stud",0.05)]},

    {"id":"two_way_shot","weight":15,"rarity":"uncommon",
     "text":"Two-way shot. If you make it, great. If you miss, you left them nothing. "
            "You make it.",
     "exp":130,"gold":42,"loot":[("Iron Shard",0.18),("Enchanting Scroll",0.08)]},

    {"id":"jump_shot","weight":14,"rarity":"uncommon",
     "text":"Jump shot over the obstacle. Clean contact. The blocker never had a chance.",
     "exp":140,"gold":45,"loot":[("Iron Shard",0.20),("Enchanting Scroll",0.10),
                                   ("Worn Leather Band",0.06)]},

    {"id":"nine_ball_rotation","weight":13,"rarity":"uncommon",
     "text":"Nine ball rotation  -  lowest target first, every time, "
            "three targets cleared in sequence. The field is learning to fear you.",
     "exp":150,"gold":50,"loot":[("Iron Shard",0.22),("Enchanting Scroll",0.12),
                                   ("Traveler's Coin",0.05)]},

    # ── Additional Rare ──────────────────────────────────────────────────
    {"id":"masse_curve","weight":6,"rarity":"rare",
     "text":"Power strike with extreme spin, "
            "the path curves around the blocker like it changed its mind. "
            "The field remembers this moment.",
     "exp":260,"gold":110,"loot":[("Iron Shard",0.40),("Enchanting Scroll",0.22),
                                    ("Scroll of Revival",0.06),("Fortune Coin",0.05)]},

    {"id":"ghost_ball_method","weight":5,"rarity":"rare",
     "text":"Ghost ball method on a thin cut  -  you aim at where the strike "
            "needs to land, not where the target stands. It drops clean.",
     "exp":290,"gold":125,"loot":[("Iron Shard",0.45),("Enchanting Scroll",0.25),
                                    ("Scroll of Revival",0.08),("Phantom Loop",0.04)]},

    {"id":"three_cushion_carom","weight":4,"rarity":"rare",
     "text":"Three cushion carom. Three walls before the second target. "
            "Technically you weren't even trying to drop anything. "
            "Somehow something falls.",
     "exp":320,"gold":135,"loot":[("Iron Shard",0.50),("Enchanting Scroll",0.28),
                                    ("Scroll of Revival",0.10),("Hawk Eye Medallion",0.04)]},

    # ── Additional Epic ──────────────────────────────────────────────────
    {"id":"golden_break","weight":2,"rarity":"epic",
     "text":"Golden break. Nine ball drops on the break. "
            "You called it. Nobody believed you. "
            "The table is already empty. The game is already won.",
     "exp":700,"gold":280,"loot":[("Iron Shard",0.70),("Enchanting Scroll",0.45),
                                    ("Scroll of Revival",0.20),("Deathwhisper Amulet",0.06),
                                    ("Dragon Soul Pendant",0.04)]},

    {"id":"call_shot_perfection","weight":2,"rarity":"epic",
     "text":"Every ball called before every shot. "
            "Every ball dropped in the called pocket. "
            "Not one fluke, not one assumption. "
            "Pure declared intention, executed perfectly.",
     "exp":750,"gold":300,"loot":[("Iron Shard",0.72),("Enchanting Scroll",0.48),
                                    ("Scroll of Revival",0.22),("Eye of the Storm",0.05),
                                    ("Aegis Talisman",0.04)]},
]

# Rolled on every /pool use as a secondary item chance
POOL_ITEM_TABLE = [
    # ── Common weapons ──
    ("Iron Broadsword",0.018),("Rusty Shiv",0.018),("Steel Knight Sword",0.012),
    # ── Common armors ──
    ("Rusty Iron Vest",0.018),("Rustic Cloth Vest",0.018),("Reinforced Hide Coat",0.012),
    # ── Common accessories ──
    ("Iron Shard Ring",0.020),("Worn Leather Band",0.020),("Scout's Pendant",0.018),
    ("Brass Ring",0.016),("Traveler's Coin",0.016),
    # ── Uncommon weapons ──
    ("Crystal Core Wand",0.008),("Warlock's Dread Staff",0.007),("Bloodsteel Shuriken",0.007),
    # ── Uncommon armors ──
    ("Iron Scale Vest",0.008),("Shadow Leather Coat",0.007),("Toughened Leather Coat",0.007),
    # ── Uncommon accessories ──
    ("Silk Band",0.008),("Rune Ring",0.008),("Obsidian Stud",0.007),
    ("Bloodstone Band",0.007),("Shadowmark Signet",0.006),("Hunter's Fang",0.006),
    ("Crystal Bead Necklace",0.006),
    # ── Rare weapons ──
    ("Warlord's Edge",0.003),("Void Channel Staff",0.003),("Gnarled Twig Wand",0.002),
    ("The Mind's Eye",0.002),
    # ── Rare armors ──
    ("Warlord's Plate",0.003),("Champion's Coat",0.003),("Shadowweave Armor",0.002),
    # ── Rare accessories ──
    ("Fortune Coin",0.003),("War Master's Clasp",0.003),("Hawk Eye Medallion",0.003),
    ("Phantom Loop",0.002),("Warrior's Band",0.002),("Mage's Coil",0.002),
    ("Stone Heart",0.002),("Beast Fang Chain",0.002),("Traveler's Compass",0.002),
    ("The Storm Torc",0.002),
    # ── Rare shields ──
    ("Iron Wall Shield",0.002),("The Stone Wall",0.002),
    # ── Epic weapons ──
    ("Ruinblade",0.0005),("Shadow Death Star",0.0005),
    # ── Epic armors ──
    ("Void-Touched Armor",0.0005),("Sentinel's Plate",0.0005),
    # ── Epic accessories ──
    ("Twin Strike Ring",0.0005),("Eye of the Void",0.0005),("Void Circle",0.0004),
    ("War Knuckle",0.0004),("Cleric's Band",0.0004),("Runed Heart",0.0004),
    ("The Shadow Whisper",0.0004),("Guardian's Talisman",0.0004),
    ("The Crossed Blades Pendant",0.0003),("The Iron and Flame Pendant",0.0003),
    # ── Epic shields ──
    ("The Crystal Barrier",0.0003),
    # ── Legendary weapons ──
    ("Grand Inquisitor's Cross",0.00008),("The Final Judgment",0.00008),
    # ── Legendary armors ──
    ("Legendary Runecoat",0.00008),
    # ── Legendary accessories ──
    ("Shard of the Void",0.00006),("Ring of the Endless",0.00006),
    ("The Warlord's Ring",0.00005),("The Eternal Ring",0.00005),
    # ── Legendary shields ──
    ("The Dead Reckoning",0.00004),
    # ── Crafting/consumables ──
    ("Iron Shard",0.025),("Enchanting Scroll",0.008),("Scroll of Revival",0.003),
]

POOL_CLASS_FLAVOR = {
    "warrior": [
        "Your grip on the cue is iron.",
        "You approach every shot like a battle. It works.",
        "Discipline over finesse. It gets results.",
    ],
    "mage": [
        "You calculated the angles before you touched the cue.",
        "Physics is just applied magic.",
        "You whispered something to the cue ball. It listened.",
    ],
    "thief": [
        "You found an angle nobody else was looking at.",
        "The table didn't see you coming. It never does.",
        "Quick hands, quiet confidence.",
    ],
    "archer": [
        "Range and precision. Same principles, different equipment.",
        "You sighted the pocket like a target. Clean release.",
        "Patience paid off. It always does.",
    ],
    "priest": [
        "Something guided your hand. You'll take it.",
        "Faith and geometry are closer than most people think.",
        "The light favors the prepared.",
    ],
    "botanist": [
        "The table blooms with possibility beneath your touch.",
        "Every angle is a petal. Every shot a bloom.",
        "Nature guided the cue. You just held it.",
    ],
    "enchantress": [
        "The balls moved before you touched them. Coincidence.",
        "You charmed the pocket into cooperating.",
        "A whisper, a wink — the shot went exactly where you wanted.",
    ],
    "valkyrie": [
        "Chosen by the table itself. The shot rang like thunder.",
        "You struck as if fate demanded it. It did.",
        "Where there is will, there is a way in.",
    ],
    "phantom_dancer": [
        "You were already in position before the cue ball stopped.",
        "They blinked. You cleared the rack.",
        "Grace and speed — the two things that never miss.",
    ],
}

def roll_pool_shot():
    total_weight = sum(s["weight"] for s in POOL_SHOTS)
    roll = random.randint(0, total_weight - 1)
    cumulative = 0
    for shot in POOL_SHOTS:
        cumulative += shot["weight"]
        if roll < cumulative:
            return shot
    return POOL_SHOTS[0]

def roll_pool_shot_with_luk(p):
    shot = roll_pool_shot()
    luk = get_stat(p, "LUK")
    upgrade_chance = luk * 0.003
    if random.random() < upgrade_chance:
        tier_order = ["common","uncommon","rare","epic","legendary"]
        current_idx = tier_order.index(shot["rarity"])
        if current_idx < len(tier_order) - 1:
            next_rarity = tier_order[current_idx + 1]
            upgraded = [s for s in POOL_SHOTS if s["rarity"] == next_rarity]
            if upgraded:
                shot = random.choice(upgraded)
    return shot

async def pool_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    s = get_or_create_shadow(user.id, user.first_name)
    p = get_player(user.id) if s.get("ascended") else None

    last_pool = p.get("last_pool") if p else s.get("last_pool")
    if last_pool:
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_pool)).total_seconds()
            if elapsed < 8:
                remaining = int(8 - elapsed)
                await send_group(update, f"🎱 Cooldown: {remaining}s", delay=5)
                return
        except Exception:
            pass

    shot = roll_pool_shot_with_luk(p) if p else roll_pool_shot()

    flavor = ""
    if p and random.random() < 0.25:
        line = get_class_line(p)
        options = POOL_CLASS_FLAVOR.get(line, [])
        if options:
            flavor = " " + random.choice(options)

    rarity_prefix = {
        "common":"🎱","uncommon":"🎯","rare":"🔵","epic":"🟣","legendary":"🟡",
    }.get(shot["rarity"], "🎱")

    item_found = None
    if shot.get("loot") and p:
        item_found = roll_loot_table(shot["loot"])
        if item_found:
            add_item(p, item_found)

    exp_gain  = shot["exp"]
    gold_gain = shot["gold"]

    if p:
        p["gold"] = p.get("gold", 0) + gold_gain
        p["last_pool"] = datetime.now().isoformat()
        lmsgs, leveled = add_exp(p, exp_gain)
        for _d, _e, _g in track_objective(p, "pool_run"):
            p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
        save_player(p)
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}*! 🎱",
                permanent=True))
    else:
        s["last_pool"] = datetime.now().isoformat()
        lmsgs, leveled = add_shadow_exp(s, exp_gain)
        save_shadow(s)

    lines = [f"{rarity_prefix} *{user.first_name}*"]
    lines.append(f"_{shot['text']}{flavor}_")
    lines.append("")
    if exp_gain > 0: lines.append(f"✨ +{exp_gain} EXP")
    if gold_gain > 0: lines.append(f"💰 +{gold_gain} gold")
    if item_found:
        rarity_tag = ""
        for pool3 in [WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES]:
            if item_found in pool3:
                r = pool3[item_found].get("rarity", "")
                rarity_tag = RARITY_EMOJI.get(r, "")
                break
        lines.append(f"🎒 {rarity_tag} *{item_found}*!")

    # Secondary item roll from global pool
    if p:
        bonus_item = roll_loot_table(POOL_ITEM_TABLE, p)
        if bonus_item:
            add_item(p, bonus_item)
            save_player(p)
            bi_rarity = ""
            for pool_check in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS]:
                if bonus_item in pool_check:
                    bi_rarity = RARITY_EMOJI.get(pool_check[bonus_item].get("rarity",""), "")
                    break
            lines.append(f"🎱 *Table Drop:* {bi_rarity} *{bonus_item}*!")

    key = (chat_id, user.id)
    old_id = last_bot_message.get(key)
    if old_id:
        try:
            await update.get_bot().delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass

    msg_obj = await update.get_bot().send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="Markdown")
    last_bot_message[key] = msg_obj.message_id
    asyncio.create_task(_auto_delete(update.get_bot(), chat_id, msg_obj.message_id, 9))
    try:
        await update.message.delete()
    except Exception:
        pass

# ── HUSTLE ────────────────────────────────────────────────────────────────────
async def hustle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run all ready activities (daily, train, quest, pool, claim, explore) in one shot."""
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 Too beaten up to hustle right now.", delay=9); return

    now    = datetime.now()
    lines  = []
    ran    = []
    skipped = []
    w      = get_weather()

    # ── Daily ──────────────────────────────────────────────────────────────────
    if check_cooldown(p.get("last_daily"), 86400):
        p["last_daily"] = now.isoformat()
        gold = 50 + p["level"] * 5; p["gold"] = p.get("gold",0) + gold
        item = None
        if random.random() < 0.10:
            item = random.choice(["Health Potion","Greater Health Potion","Grand Restorative Flask"])
            add_item(p, item)
        daily_exp = 200 + p["level"] * 10
        lmsgs, _ = add_exp(p, daily_exp)
        entry = f"🎁 *Daily:* +{daily_exp} EXP, +{gold}g"
        if item: entry += f", *{item}*!"
        ran.append(entry)
        if lmsgs: ran.extend(f"  {m}" for m in lmsgs)
    else:
        skipped.append(f"🎁 Daily  -  {time_remaining(p.get('last_daily'), 86400)}")

    # ── Train ──────────────────────────────────────────────────────────────────
    if check_cooldown(p.get("last_train"), 1800):
        p["last_train"] = now.isoformat()
        base = 150 + p["level"] * 5
        cls  = get_player_class(p)
        if cls:
            pk = cls.get("passive_key","")
            if pk in ("arcane_mind","spell_surge","arcane_mastery","mana_overload","eternal_wisdom"):
                base = round(base * 1.30)
            elif pk in ("iron_will","holy_stance","devotion","bulwark","divine_judgment"):
                base = round(base * 1.20)
            elif pk in ("quick_hands","evasion","shadowstep","ghost_form","deaths_shadow",
                        "eagle_eye","trailblazer","natures_bond","guardian_stance","pathfinder"):
                base = round(base * 1.35)
            elif pk in ("mending_aura","divine_grace","sacred_ground","resurrection","divine_presence",
                        "dark_sense","purge","judgement","wrath_of_the_righteous"):
                base = round(base * 1.15)
        lmsgs, _ = add_exp(p, base)
        ran.append(f"🏋️ *Train:* +{base} EXP")
        if lmsgs: ran.extend(f"  {m}" for m in lmsgs)
    else:
        skipped.append(f"🏋️ Train  -  {time_remaining(p.get('last_train'), 1800)}")

    # ── Quest ──────────────────────────────────────────────────────────────────
    if check_cooldown(p.get("last_quest"), 3600):
        p["last_quest"] = now.isoformat()
        if p["level"] <= 3:   qpool = [q for q in SOLO_QUESTS if q["tier"]=="Easy"]
        elif p["level"] <= 7: qpool = [q for q in SOLO_QUESTS if q["tier"] in ["Easy","Medium"]]
        else:                 qpool = SOLO_QUESTS
        q  = random.choice(qpool or SOLO_QUESTS)
        item_found = roll_loot_table(q.get("loot_table",[]))
        if item_found: add_item(p, item_found)
        luk_val = get_stat(p, "LUK")
        gold    = round(q["gold"] * (1 + luk_val * 0.002))
        p["gold"] = p.get("gold",0) + gold
        p["quests_done"] = p.get("quests_done",0) + 1
        lmsgs, _ = add_exp(p, q["exp"], w)
        check_titles(p)
        entry = f"🗺️ *Quest:* +{q['exp']} EXP, +{gold}g"
        if item_found: entry += f", *{item_found}*!"
        ran.append(entry)
        if lmsgs: ran.extend(f"  {m}" for m in lmsgs)
    else:
        skipped.append(f"🗺️ Quest  -  {time_remaining(p.get('last_quest'), 3600)}")

    # ── Pool shot ──────────────────────────────────────────────────────────────
    last_pool = p.get("last_pool")
    pool_ready = True
    if last_pool:
        try:
            elapsed = (now - datetime.fromisoformat(last_pool)).total_seconds()
            if elapsed < 8:
                pool_ready = False
                skipped.append(f"🎱 Pool  -  {int(8 - elapsed)}s")
        except: pass
    if pool_ready:
        p["last_pool"] = now.isoformat()
        shot      = roll_pool_shot_with_luk(p)
        exp_gain  = shot["exp"]; gold_gain = shot["gold"]
        p["gold"] = p.get("gold",0) + gold_gain
        item_found = None
        if shot.get("loot"):
            item_found = roll_loot_table(shot["loot"])
            if item_found: add_item(p, item_found)
        bonus_item = roll_loot_table(POOL_ITEM_TABLE, p)
        if bonus_item: add_item(p, bonus_item)
        lmsgs, _ = add_exp(p, exp_gain)
        rarity_prefix = {"common":"🎱","uncommon":"🎯","rare":"🔵","epic":"🟣","legendary":"🟡"}.get(shot["rarity"],"🎱")
        entry = f"{rarity_prefix} *Pool:* +{exp_gain} EXP"
        if gold_gain: entry += f", +{gold_gain}g"
        if item_found: entry += f", *{item_found}*!"
        if bonus_item: entry += f"\n  🎱 Table drop: *{bonus_item}*!"
        ran.append(entry)
        if lmsgs: ran.extend(f"  {m}" for m in lmsgs)

    # ── Claim ─────────────────────────────────────────────────────────────────
    today_str     = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    last_claim    = p.get("last_claim")
    if last_claim == today_str:
        skipped.append("🎁 Claim  -  already claimed today")
    else:
        streak = safe_int(p.get("claim_streak"))
        streak = streak + 1 if last_claim == yesterday_str else 1
        gold_reward  = 50 + min(streak * 10, 200)
        slate_count  = 1 if streak >= 3 else 0
        scale_count  = 1 if streak >= 7 else 0
        bonus_scroll = streak >= 14
        inv = sjl(p.get("inventory"), [])
        if slate_count: inv.extend(["Iron Shard"] * slate_count)
        if scale_count: inv.extend(["Iron Shard"] * scale_count)
        if bonus_scroll: inv.append("Enchanting Scroll")
        p["inventory"] = json.dumps(inv)
        p["gold"] = p.get("gold", 0) + gold_reward
        p["last_claim"] = today_str
        p["claim_streak"] = streak
        streak_emojis = "🔥" * min(streak, 7)
        claim_entry = f"🎁 *Claim Day {streak}* {streak_emojis}: +{gold_reward}g"
        if slate_count or scale_count:
            claim_entry += f", +{slate_count + scale_count} Iron Shard"
        if bonus_scroll:
            claim_entry += ", +1 Enchanting Scroll"
        ran.append(claim_entry)

    # ── Explore ────────────────────────────────────────────────────────────────
    if p.get("explore_date") == today_str and safe_int(p.get("explore_count_today")) >= 2:
        skipped.append("🗺️ Explore  -  2/2 used today")
    elif user.id in explore_timers and not explore_timers[user.id].done():
        skipped.append("🗺️ Explore  -  expedition in progress")
    else:
        if p["level"] <= 5:     _elig = [z for z in EXPLORE_ZONES if z["tier"]=="Easy"]
        elif p["level"] <= 15:  _elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium"]]
        elif p["level"] <= 30:  _elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium","Hard"]]
        elif p["level"] <= 60:  _elig = [z for z in EXPLORE_ZONES if z["tier"] != "Legendary"]
        else:                   _elig = EXPLORE_ZONES
        _zone = random.choice(_elig)
        if p.get("explore_date") != today_str:
            p["explore_count_today"] = 0
            p["explore_date"] = today_str
        p["explore_count_today"] = safe_int(p.get("explore_count_today")) + 1
        p["last_explore"] = now.isoformat()
        _remaining = 2 - safe_int(p.get("explore_count_today"))
        ran.append(f"🗺️ *Explore:* Expedition to *{_zone['name']}* started — results in 1 hour! ({_remaining} left today)")
        chat_id   = update.effective_chat.id
        _bot      = update.get_bot()
        _uid      = user.id
        _uname    = p.get("username", user.first_name)
        _zone_ref = _zone

        async def _hustle_explore():
            await asyncio.sleep(3600)
            pp = get_player(_uid)
            if not pp: return
            w2 = get_weather()
            success = random.random() < 0.70
            if success:
                exp  = round(_zone_ref["exp"] * w2.get("exp_mod", 1.0))
                gold = _zone_ref["gold"]
                pp["gold"] = pp.get("gold", 0) + gold
                item_found = roll_loot_table(_zone_ref.get("loot_table", []))
                if item_found: add_item(pp, item_found)
                lmsgs, leveled = add_exp(pp, exp)
                save_player(pp)
                rarity = ""
                if item_found:
                    for _pool in [WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES]:
                        if item_found in _pool:
                            rarity = RARITY_EMOJI.get(_pool[item_found].get("rarity", ""), "")
                            break
                msg = (f"🗺️ *{pp['username']}* returns from *{_zone_ref['name']}*!\n\n"
                       f"✅ Expedition successful!\n"
                       f"✨ +{exp} EXP | 💰 +{gold} Gold")
                if item_found: msg += f"\n🎒 Found: {rarity} *{item_found}*!"
                if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
            else:
                save_player(pp)
                msg = (f"🗺️ *{pp['username']}* returns from *{_zone_ref['name']}*!\n\n"
                       f"❌ The expedition failed — nothing to show for it.")
            try:
                await _bot.send_message(chat_id, msg, parse_mode="Markdown")
            except Exception:
                pass

        _task = asyncio.create_task(_hustle_explore())
        explore_timers[_uid] = _task

    if not ran:
        cd_list = "\n".join(f"  {s}" for s in skipped)
        await send_group(update,
            f"🎱 *{user.first_name}*  -  nothing ready yet.\n\n{cd_list}", delay=15); return

    save_player(p)

    out = [f"🎱 *{user.first_name}* runs the table!\n"]
    out += ran
    if skipped:
        out += ["", "⏳ *Still cooling down:*"] + [f"  {s}" for s in skipped]
    await send_group(update, "\n".join(out), delay=45)


# ── RESETSTATS ────────────────────────────────────────────────────────────────
def _do_resetstats(p):
    """Execute the stat reset and return (new_stats, refunded)."""
    sd = safe_stats(p)
    base_defaults = {"STR":5,"AGI":5,"INT":5,"WIS":5,"DEX":5,"LUK":5,"DEF":0}
    total_allocated = 0
    for stat, base in base_defaults.items():
        current = sd.get(stat, base)
        if current > base:
            total_allocated += (current - base)
    def_points = sd.get("DEF", 0)
    if def_points > 0:
        total_allocated += def_points
    new_stats = {"STR":5,"AGI":5,"INT":5,"WIS":5,"DEX":5,"LUK":5,"DEF":0}
    cid = p.get("class_id")
    if cid:
        base_line = CLASS_TREE.get(cid, {}).get("line")
        if base_line:
            base_cls = CLASS_TREE.get(base_line, {})
            for stat, bonus in base_cls.get("stat_bonus", {}).items():
                if stat in new_stats:
                    new_stats[stat] = new_stats.get(stat, 5) + bonus
        current_cls = CLASS_TREE.get(cid, {})
        for stat, bonus in current_cls.get("stat_bonus", {}).items():
            if stat in new_stats:
                new_stats[stat] = new_stats.get(stat, 5) + bonus
    refunded = total_allocated + safe_int(p.get("stat_points"))
    p["stats"] = json.dumps(new_stats)
    p["stat_points"] = refunded
    save_player(p)
    return new_stats, refunded

async def resetstats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return

    if not context.args or context.args[0].lower() != "confirm":
        rsstat_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm Reset", callback_data=f"rsstat_confirm_{user.id}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"rsstat_cancel_{user.id}"),
        ]])
        sd = safe_stats(p)
        await send_group(update,
            f"⚠️ *Stat Reset*\n\n"
            f"This will refund ALL allocated stat points back to your pool.\n"
            f"Your class stat bonuses will be preserved.\n\n"
            f"Current stats: STR:{sd.get('STR',5)} AGI:{sd.get('AGI',5)} "
            f"INT:{sd.get('INT',5)} WIS:{sd.get('WIS',5)} "
            f"DEX:{sd.get('DEX',5)} LUK:{sd.get('LUK',5)}\n\n"
            f"Tap Confirm or type /resetstats confirm to proceed.",
            delay=20, reply_markup=rsstat_markup); return

    new_stats, refunded = _do_resetstats(p)
    await send_group(update,
        f"🔄 *Stat Reset Complete!*\n\n"
        f"All allocated stat points have been refunded.\n"
        f"💡 *{refunded} points* returned to your pool.\n\n"
        f"DEF is now gear-only  -  armor and shields provide your defense.\n\n"
        f"Use `/allocate` to redistribute your points.\n"
        f"Current stats after class bonuses:\n"
        f"STR:{new_stats['STR']} AGI:{new_stats['AGI']} "
        f"INT:{new_stats['INT']} WIS:{new_stats['WIS']} "
        f"DEX:{new_stats['DEX']} LUK:{new_stats['LUK']}",
        delay=60)

async def resetstats_callback(update, context):
    """Handle resetstats confirm/cancel buttons."""
    query = update.callback_query
    await query.answer()
    data = query.data  # rsstat_confirm_{uid} or rsstat_cancel_{uid}
    parts = data.split("_")
    if len(parts) < 3:
        return
    action = parts[1]  # 'confirm' or 'cancel'
    try:
        uid = int(parts[2])
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your reset button!", show_alert=True)
        return

    if action == "cancel":
        try:
            await query.edit_message_text("❌ Stat reset cancelled.", parse_mode="Markdown")
        except Exception:
            pass
        return

    # action == "confirm"
    p = get_player(uid)
    if not p:
        await query.answer("Player not found!", show_alert=True)
        return
    new_stats, refunded = _do_resetstats(p)
    result = (f"🔄 *Stat Reset Complete!*\n\n"
              f"All allocated stat points have been refunded.\n"
              f"💡 *{refunded} points* returned to your pool.\n\n"
              f"DEF is now gear-only  -  armor and shields provide your defense.\n\n"
              f"Use `/allocate` to redistribute your points.\n"
              f"Current stats after class bonuses:\n"
              f"STR:{new_stats['STR']} AGI:{new_stats['AGI']} "
              f"INT:{new_stats['INT']} WIS:{new_stats['WIS']} "
              f"DEX:{new_stats['DEX']} LUK:{new_stats['LUK']}")
    try:
        await query.edit_message_text(result, parse_mode="Markdown")
    except Exception:
        pass

# ── WIPE (admin only) ─────────────────────────────────────────────────────────
async def wipe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await send_group(update, "❌ Admin only.", delay=9); return

    last = _wipe_confirm.get(user.id)
    if not last or (datetime.now() - datetime.fromisoformat(last)).total_seconds() > 30:
        _wipe_confirm[user.id] = datetime.now().isoformat()
        await send_group(update,
            "⚠️ *Are you sure?* This wipes ALL player data.\n"
            "Type /wipe again within 30 seconds to confirm.", delay=30)
        return

    _wipe_confirm.pop(user.id, None)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS shadow_profiles")
    c.execute("DROP TABLE IF EXISTS players")
    c.execute("DROP TABLE IF EXISTS guilds")
    c.execute("DROP TABLE IF EXISTS bounties")
    conn.commit(); conn.close()
    init_db()
    # Clear memory state
    active_bosses.clear(); secret_boss_active.clear()
    active_events.clear(); active_raids.clear(); active_soloraids.clear()
    message_counters.clear()
    pending_trades.clear(); pending_guild_reqs.clear()
    pending_duels.clear(); active_arenas.clear()
    await send_group(update,
        "🗑️ *Database wiped and reset.*\n"
        "All players, guilds, and data cleared.\n"
        "Fresh start!", delay=30)

# ── PASSIVE MESSAGE HANDLER ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    user = update.effective_user
    if not user or user.is_bot: return
    if update.message.text and update.message.text.startswith("/"):
        return
    chat_id = update.effective_chat.id
    text    = (update.message.text or "").lower()

    # Non-text messages (stickers, photos, etc.)  -  track shadow profile but skip keyword triggers
    if not update.message.text:
        s = get_or_create_shadow(user.id, user.first_name)
        s["username"]      = user.first_name
        s["message_count"] = s.get("message_count", 0) + 1
        s["last_seen"]     = datetime.now().isoformat()
        save_shadow(s)
        return

    # Railrunner target-spotted notification (rate-limited: once per 10 min per target)
    _bounty_spot_cache = context.bot_data.setdefault("bounty_spot_cache", {})
    cache_key = (user.id, chat_id)
    last_spot = _bounty_spot_cache.get(cache_key, 0)
    if (datetime.now().timestamp() - last_spot) > 600:
        try:
            bconn = sqlite3.connect(DB_PATH); bconn.row_factory = sqlite3.Row
            rows = bconn.execute(
                "SELECT b.placer_id FROM bounties b "
                "JOIN players rp ON rp.user_id = b.placer_id AND rp.class_id = 'bounty_hunter' "
                "WHERE b.target_id=? AND b.claimed_by IS NULL AND b.expires_at > ?",
                (user.id, datetime.now().isoformat())).fetchall()
            bconn.close()
            for row in rows:
                if row["placer_id"] != user.id:
                    asyncio.create_task(context.bot.send_message(
                        chat_id=row["placer_id"],
                        text=f"🔭 *Target spotted!* Your bounty target *{user.first_name}* "
                             f"just sent a message in the group.",
                        parse_mode="Markdown"))
            if rows:
                _bounty_spot_cache[cache_key] = datetime.now().timestamp()
        except Exception: pass

    # Random events  -  every 2500 messages
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    cnt = message_counters[chat_id]

    # Periodic cleanup every 500 messages
    if cnt % 500 == 0:
        now_iso = datetime.now().isoformat()
        expired_trades = [uid for uid, t in pending_trades.items()
                          if t.get("expires", now_iso) < now_iso]
        for uid in expired_trades:
            pending_trades.pop(uid, None)
        expired_raids = [cid for cid, r in active_raids.items()
                         if not r.get("in_progress")
                         and r.get("expires", now_iso) < now_iso]
        for cid in expired_raids:
            active_raids.pop(cid, None)

    if cnt % 2500 == 0 and chat_id not in active_events:
        roll = random.random()
        if roll < 0.70:   freq = "common"
        elif roll < 0.90: freq = "uncommon"
        else:             freq = "rare"
        pool = [e for e in RANDOM_EVENTS if e["freq"]==freq]
        if pool:
            event = random.choice(pool).copy()
            active_events[chat_id] = event
            msg = await update.message.reply_text(event["msg"], parse_mode="Markdown")
            # Store drake message id for reply detection
            if event["key"] == "drake":
                active_drakes[chat_id] = {
                    "msg_id": msg.message_id,
                    "hp": event["enemy_hp"],
                    "max_hp": event["enemy_hp"],
                    "fighters": {},
                    "loot_table": event.get("loot_table",[]),
                    "exp_reward": event["exp_reward"],
                }
                active_events.pop(chat_id, None)

    # Shadow profile
    s = get_or_create_shadow(user.id, user.first_name)
    s["username"] = user.first_name

    # Idle reward check
    p = get_player(user.id) if s.get("ascended") else None
    await check_idle_reward(user, s, p, context.bot, chat_id)

    # Update last_seen
    s["message_count"] = s.get("message_count",0) + 1
    s["last_seen"]     = datetime.now().isoformat()

    if p and s: sync_levels(p, s)

    cds_s = safe_cds(s)
    cds_p = safe_cds(p) if p else {}

    shadow_exp = 0; rpg_exp = 0; rpg_gold = 0

    # Bleed tick
    if p and is_bleeding(p):
        tick_dmg = check_bleed_tick(p)
        if tick_dmg:
            if p["hp"] <= 0:
                p["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
                p["last_defeated_by"] = "Bleed damage (DoT)"
                asyncio.create_task(_notify_defeat(context.bot, p, "Bleed damage (you bled out)"))
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🩸 *{p['username']}* bled out and is defeated for 6 hours!",
                    permanent=True))
            save_player(p)

    # Cannot earn EXP while defeated
    defeated_no_exp = p and is_defeated(p)

    # Easter eggs
    for egg in EASTER_EGGS:
        if re.search(egg["pattern"], text, re.IGNORECASE):
            if egg.get("secret_boss"):
                w = get_weather()
                if w.get("secret_eligible") and \
                   chat_id not in secret_boss_active and \
                   chat_id not in active_bosses:
                    bd = BOSSES["void"]
                    secret_boss_active[chat_id] = {
                        "data":bd.copy(),"hp":bd["max_hp"],
                        "participants":[{"id":user.id,"name":user.first_name,"dmg":0}]}
                    await update.message.reply_text(
                        f"🌑 *THE VOID BALL AWAKENS!*\n_{bd['desc']}_\n\n"
                        f"❤️ HP: {bd['max_hp']}\n*{user.first_name}* called it forth! /strike!",
                        parse_mode="Markdown")
            break

    # Keyword triggers
    if not defeated_no_exp:
        for trigger in KEYWORD_TRIGGERS:
            if re.search(trigger["pattern"], text, re.IGNORECASE):
                key = trigger["key"]
                if not cds_s.get(key) or \
                   datetime.now() > datetime.fromisoformat(cds_s[key]) + timedelta(seconds=trigger["cooldown"]):
                    cds_s[key] = datetime.now().isoformat()
                    if trigger["exp"] > 0:
                        shadow_exp += trigger["exp"]
                        if p: rpg_exp += trigger["exp"]
                    elif trigger["exp"] < 0:
                        s["exp"] = max(0, s["exp"]+trigger["exp"])
                        if p: p["exp"] = max(0, p.get("exp",0)+trigger["exp"])
                    if trigger.get("gold_chance") and random.random() < trigger["gold_chance"]:
                        rpg_gold += 1
                break

        # Daily first message bonus
        today = datetime.now().strftime("%Y-%m-%d")
        if cds_s.get("daily_date") != today:
            cds_s.update({"daily_date":today,"daily_messages":0,
                          "daily_bonus_given":False,
                          "streak_50":False,"streak_100":False,"streak_500":False})
        if not cds_s.get("daily_bonus_given"):
            cds_s["daily_bonus_given"] = True
            shadow_exp += 50
            if p: rpg_exp += 50

        cds_s["daily_messages"] = cds_s.get("daily_messages",0) + 1
        dm = cds_s["daily_messages"]
        if dm >= 50 and not cds_s.get("streak_50"):
            cds_s["streak_50"] = True; shadow_exp += 150
            if p: rpg_exp += 150
            asyncio.create_task(announce(context.bot, chat_id,
                f"🔥 *{user.first_name}* hit a *50 message streak!* +150 EXP!",
                delay=8))
        if dm >= 100 and not cds_s.get("streak_100"):
            cds_s["streak_100"] = True; shadow_exp += 300; rpg_gold += 30
            if p: rpg_exp += 300
            asyncio.create_task(announce(context.bot, chat_id,
                f"🔥 *{user.first_name}* hit a *100 message streak!* +300 EXP!",
                delay=8))
        if dm >= 500 and not cds_s.get("streak_500"):
            cds_s["streak_500"] = True; shadow_exp += 800
            if p: rpg_exp += 800
            asyncio.create_task(announce(context.bot, chat_id,
                f"🏆 *{user.first_name}* hit a *500 message streak!* +800 EXP! 🎱",
                delay=8))

    # Apply shadow EXP
    s["passive_cooldowns"] = json.dumps(cds_s)
    if shadow_exp > 0 and not defeated_no_exp:
        lmsgs, did_level = add_shadow_exp(s, shadow_exp)
        save_shadow(s)
        if did_level and s["level"] % 10 == 0:
            hint = ""
            if not s.get("ascended") and s["level"] >= 5:
                hint = "\n_Type /ascend in a private chat to enter the RPG!_"
            tier = get_tier(s["level"])
            asyncio.create_task(announce(context.bot, chat_id,
                f"{tier['emoji']} *{s['username']}* reached *Level {s['level']}*!{hint}",
                permanent=True))
    else:
        save_shadow(s)

    # Apply RPG EXP
    if p and not defeated_no_exp:
        p["gold"] = p.get("gold",0) + rpg_gold
        p["passive_cooldowns"] = json.dumps(cds_p)
        if rpg_exp > 0:
            lmsgs, did_level = add_exp(p, rpg_exp)
            if did_level and p["level"] > s["level"]:
                s["level"] = p["level"]; s["exp"] = 0; save_shadow(s)
            save_player(p)
            if did_level and p["level"] % 10 == 0:
                cls = get_player_class(p)
                cnote = f" the *{cls['name']}*" if cls else ""
                ann = [f"🎉 *{p['username']}*{cnote} reached *Level {p['level']}*! 🎱"]
                for msg in lmsgs:
                    if any(x in msg for x in ["choose a class","Choose your path","LEVEL 100"]):
                        ann.append(msg)
                asyncio.create_task(announce(context.bot, chat_id,
                    "\n".join(ann), permanent=True))
        else:
            save_player(p)

    # Drake reply detection  -  if message is a reply to drake message
    if chat_id in active_drakes:
        drake = active_drakes[chat_id]
        if (update.message.reply_to_message and
                update.message.reply_to_message.message_id == drake["msg_id"] and
                p and not is_defeated(p)):
            dmg = random.randint(10,30) + p["level"]//2
            drake["hp"] = max(0, drake["hp"]-dmg)
            uid = user.id
            drake["fighters"][uid] = drake["fighters"].get(uid,0) + dmg
            lines = [f"🐉 *{user.first_name}* strikes the Wild Drake for *{dmg}*!\n"
                     f"❤️ Drake HP: {drake['hp']}/{drake['max_hp']}"]
            if drake["hp"] <= 0:
                active_drakes.pop(chat_id, None)
                lines.append("\n🏆 *Wild Drake defeated!*\n")
                total_dmg = sum(drake["fighters"].values())
                for fid, fdmg in drake["fighters"].items():
                    fp = get_player(fid)
                    if not fp: continue
                    share = fdmg/max(1,total_dmg)
                    exp_share = round(drake["exp_reward"] * share)
                    loot = roll_loot_table(drake.get("loot_table",[]))
                    if loot: add_item(fp, loot)
                    lmsgs, leveled = add_exp(fp, exp_share)
                    save_player(fp)
                    lines.append(f"✅ *{fp['username']}*  -  +{exp_share} EXP"
                                 + (f" | 🎒 *{loot}*!" if loot else ""))
                    if leveled and fp["level"] % 10 == 0:
                        asyncio.create_task(announce(context.bot, chat_id,
                            f"🎉 *{fp['username']}* reached *Level {fp['level']}* from the Drake! 🐉",
                            permanent=True))
            try:
                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            except Exception:
                pass

# ── EVENT HANDLERS ────────────────────────────────────────────────────────────
async def greet_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] not in ("traveler","merchant","shrine"): return
    s = get_or_create_shadow(user.id, user.first_name)
    p = get_player(user.id)
    active_events.pop(chat_id, None)
    if event["key"] == "traveler":
        loot = roll_loot_table(event.get("loot_table",[]))
        if p and not is_defeated(p):
            if loot: add_item(p, loot)
            lmsgs, leveled = add_exp(p, event["exp"]); save_player(p)
            msg = f"🧙 *{user.first_name}* greets the traveler! +{event['exp']} EXP"
            if loot: msg += f" | 🎒 *{loot}*!"
        else:
            lmsgs, leveled = add_shadow_exp(s, event["exp"]); save_shadow(s)
            msg = f"🧙 *{user.first_name}* greets the traveler! +{event['exp']} EXP"
        await send_group(update, msg, delay=15)
    elif event["key"] == "merchant":
        if p:
            set_status(p, "shop_discount_until", event["duration_min"]*60)
            save_player(p)
        await send_group(update,
            f"🛍️ *{user.first_name}* greeted the merchant!\n"
            f"*20% shop discount* for {event['duration_min']} minutes! Use /shop", delay=15)
    elif event["key"] == "shrine":
        if p:
            stat = random.choice(["STR","DEF","AGI","INT","WIS"])
            sd = safe_stats(p); sd[stat] = sd.get(stat,5)+5; p["stats"] = json.dumps(sd)
            save_player(p)
            await send_group(update,
                f"🔮 *{user.first_name}* prays at the shrine!\n*+5 {stat}* for 2 hours!", delay=15)

async def fight_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "bandit": return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(10,30)
    event["enemy_hp"] = event.get("enemy_hp",150) - dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"🗡️ *{user.first_name}* strikes the bandit for {dmg}! "
             f"(HP: {max(0,event['enemy_hp'])}/150)"]
    if event["enemy_hp"] <= 0:
        active_events.pop(chat_id, None)
        lines.append("💀 *Bandit defeated!* +250 EXP each!")
        for fid in event["fighters"]:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp and not is_defeated(fp):
                loot = roll_loot_table(event.get("loot_table",[]))
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, 250); save_player(fp)
                if loot: lines.append(f"🎒 *{fp['username']}* found *{loot}*!")
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}* from battle! ⚔️",
                        permanent=True))
            elif fs:
                lmsgs, leveled = add_shadow_exp(fs, 250); save_shadow(fs)
    await send_group(update, "\n".join(lines), delay=15)

async def shoot_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "ghost": return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(15,35)
    event["enemy_hp"] = event.get("enemy_hp",200) - dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"👻 *{user.first_name}* shoots the spirit for {dmg}! "
             f"(HP: {max(0,event['enemy_hp'])}/200)"]
    if event["enemy_hp"] <= 0:
        active_events.pop(chat_id, None)
        lines.append("✨ *Spirit banished!* +300 EXP each!")
        for fid in event["fighters"]:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp and not is_defeated(fp):
                loot = roll_loot_table(event.get("loot_table",[]))
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, 300); save_player(fp)
                if loot: lines.append(f"🎒 *{fp['username']}* found *{loot}*!")
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}* from the ghost! 👻",
                        permanent=True))
            elif fs:
                lmsgs, leveled = add_shadow_exp(fs, 300); save_shadow(fs)
    await send_group(update, "\n".join(lines), delay=15)

async def claim_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "cache": return
    active_events.pop(chat_id, None)
    p = get_player(user.id)
    loot = roll_loot_table(event.get("loot_table",[]))
    gold = random.randint(50,200)
    if p:
        if loot: add_item(p, loot)
        p["gold"] = p.get("gold",0) + gold; save_player(p)
    await send_group(update,
        f"💰 *{user.first_name}* claims the abandoned cache!\n"
        f"💰 +{gold} gold" + (f" | 🎒 *{loot}*!" if loot else ""), delay=15)

async def pray_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await greet_event(update, context)  # shrine handled in greet

# ── INLINE CALLBACKS ──────────────────────────────────────────────────────────

# ── Solo Raid Attack/Skill callback ──
async def soloraid_act_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # format: sr_act_{uid}_{action}
    if len(parts) < 4:
        return
    try:
        uid = int(parts[2])
        action = parts[3]
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your raid!", show_alert=True)
        return

    user = query.from_user
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if uid not in active_soloraids:
        await query.answer("No active solo raid! Use /soloraid.", show_alert=True); return
    if is_defeated(p):
        await query.answer("You're defeated — can't act!", show_alert=True); return
    if cannot_attack(p):
        await query.answer("You're stunned or rooted — can't act!", show_alert=True); return

    chat_id = query.message.chat.id

    if action == "skl":
        # Trigger skill against solo raid enemy
        all_skills = sjl(p.get("all_skills"), [])
        if not all_skills:
            await query.answer("No skills unlocked yet!", show_alert=True); return
        sr = active_soloraids[uid]
        if len(all_skills) > 1:
            markup = _build_skill_picker_keyboard(all_skills, uid, 0)
            await query.edit_message_text(
                f"🔮 *vs {sr['enemy']['name']}* — choose a skill:",
                parse_mode="Markdown", reply_markup=markup)
            return
        sk = all_skills[0]
        w = get_weather()
        sk_lines, sk_dmg = apply_skill_to_raid_enemy(p, sk, sr, w)
        enemy = sr["enemy"]
        out = [f"⚡ *{user.first_name}* uses *{sk['name']}* on *{enemy['name']}*!"]
        out.extend(sk_lines)
        if sk_dmg > 0:
            out.append(f"💥 *{sk_dmg} damage!* Enemy HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}")

        if sr["enemy_hp"] <= 0:
            out.append(f"\n✅ *{enemy['name']}* destroyed!")
            tier = sr["tier"]; wave_enemies = tier["wave_enemies"]; cw = sr["wave"]
            if cw < len(wave_enemies):
                sr["wave"] += 1; ne = wave_enemies[cw].copy()
                sr["enemy"] = ne; sr["enemy_hp"] = ne["hp"]; sr["enemy_max_hp"] = ne["hp"]
                sr.pop("enemy_statuses", None)
                out.append(f"\n🌊 *Wave {sr['wave']}  -  {ne['name']}*")
                out.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
            elif cw == len(wave_enemies):
                bd = BOSSES[tier["wave_boss_key"]]; boss_hp = bd["max_hp"] // 2
                sr["wave"] = len(wave_enemies) + 1
                sr["enemy"] = {"name": bd["name"] + " ⚡","dmg_min": round(bd["dmg_min"]*0.6),"dmg_max": round(bd["dmg_max"]*0.6)}
                sr["enemy_hp"] = boss_hp; sr["enemy_max_hp"] = boss_hp
                sr.pop("enemy_statuses", None)
                out.append(f"\n🎱 *FINAL BOSS  -  {bd['name']}!* ❤️ HP: {boss_hp}")
            else:
                active_soloraids.pop(uid, None)
                exp_r = tier["exp_reward"]; gold_r = tier["gold_reward"]
                p["gold"] = p.get("gold", 0) + gold_r; p["quests_done"] = p.get("quests_done", 0) + 1
                for _d, _e, _g in track_objective(p, "solo_win"):
                    p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
                loot = roll_loot_table(tier.get("loot_table", []), p)
                if loot:
                    add_item(p, loot)
                    r = ""
                    for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                        if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity", ""), ""); break
                    out.append(f"🎒 Found: {r} *{loot}*!")
                add_exp(p, exp_r, get_weather())
                out.append(f"\n🏆 *SOLO RAID COMPLETE!* +{exp_r:,} EXP | +{gold_r}g")
                save_player(p)
                try:
                    await query.edit_message_text(text="\n".join(out)[:4096], parse_mode="Markdown")
                except Exception: pass
                return
        else:
            killed = raid_enemy_counter(p, sr, out)
            if killed:
                active_soloraids.pop(uid, None)
                save_player(p)
                try:
                    await query.edit_message_text(text="\n".join(out)[:4096], parse_mode="Markdown")
                except Exception:
                    pass
                return

        save_player(p)
        sr_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚔️ Attack", callback_data=f"sr_act_{uid}_atk"),
            InlineKeyboardButton("✨ Skill",  callback_data=f"sr_act_{uid}_skl"),
        ]])
        try:
            await query.edit_message_text(text="\n".join(out)[:4096], parse_mode="Markdown", reply_markup=sr_markup)
        except Exception: pass
        return

    # action == "atk" — standard attack
    sr = active_soloraids[uid]
    enemy = sr["enemy"]
    w = get_weather()
    dmg = calc_attack_damage(p, w)
    is_crit = check_crit(p)
    if is_crit: dmg = apply_crit(p, dmg)
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0; dmg = get_stat(p, "AGI") * 4; is_crit = False

    sr["enemy_hp"] = max(0, sr["enemy_hp"] - dmg)
    sr["total_dmg"] = sr.get("total_dmg", 0) + dmg

    lines = [
        f"⚔️ *{user.first_name}* strikes *{enemy['name']}* for *{dmg}{'💥' if is_crit else ''}!*",
        f"❤️ Enemy HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}  |  Your HP: {sr['player_hp']}/{sr['player_max_hp']}",
    ]
    bleed_dmg = tick_enemy_bleed(sr)
    if bleed_dmg:
        lines.append(f"🩸 *{enemy['name']}* bleeds for {bleed_dmg}! HP: {sr['enemy_hp']}/{sr['enemy_max_hp']}")

    if sr["enemy_hp"] <= 0:
        tier = sr["tier"]; wave_enemies = tier["wave_enemies"]; cw = sr["wave"]
        lines.append(f"\n✅ *Wave {cw} cleared!*")
        sr.pop("enemy_statuses", None)
        if cw < len(wave_enemies):
            sr["wave"] += 1; ne = wave_enemies[cw].copy()
            sr["enemy"] = ne; sr["enemy_hp"] = ne["hp"]; sr["enemy_max_hp"] = ne["hp"]
            lines.append(f"\n🌊 *Wave {sr['wave']}  -  {ne['name']}*")
            lines.append(f"❤️ HP: {ne['hp']} | 💀 {ne['dmg_min']}–{ne['dmg_max']}")
        elif cw == len(wave_enemies):
            bd = BOSSES[tier["wave_boss_key"]]; boss_hp = bd["max_hp"] // 2
            sr["wave"] = len(wave_enemies) + 1
            sr["enemy"] = {"name": bd["name"] + " ⚡","dmg_min": round(bd["dmg_min"]*0.6),"dmg_max": round(bd["dmg_max"]*0.6)}
            sr["enemy_hp"] = boss_hp; sr["enemy_max_hp"] = boss_hp
            lines.append(f"\n🎱 *FINAL BOSS  -  {bd['name']}!* ❤️ HP: {boss_hp}")
        else:
            active_soloraids.pop(uid, None)
            exp_r = tier["exp_reward"]; gold_r = tier["gold_reward"]
            p["gold"] = p.get("gold", 0) + gold_r; p["quests_done"] = p.get("quests_done", 0) + 1
            for _d, _e, _g in track_objective(p, "solo_win"):
                p["gold"] = p.get("gold",0) + _g; add_exp(p, _e)
            loot = roll_loot_table(tier.get("loot_table", []), p)
            loot_line = ""
            if loot:
                add_item(p, loot); r = ""
                for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity", ""), ""); break
                loot_line = f"\n🎒 Found: {r} *{loot}*!"
            add_exp(p, exp_r, get_weather())
            lines.append(f"\n🏆 *SOLO RAID COMPLETE  -  {tier['name']}!*")
            lines.append(f"✅ +{exp_r:,} EXP | +{gold_r}g{loot_line}")
            save_player(p)
            try:
                await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown")
            except Exception: pass
            return
    else:
        enemy = sr["enemy"]
        if enemy_status_active(sr, "stunned_until"):
            lines.append(f"⚡ *{enemy['name']}* is stunned  -  no counter!")
        elif enemy_status_active(sr, "frozen_until"):
            lines.append(f"❄️ *{enemy['name']}* is frozen  -  no counter!")
        else:
            raw = random.randint(enemy["dmg_min"], enemy["dmg_max"])
            if enemy_status_active(sr, "weakened_until") or enemy_status_active(sr, "hexed_until"):
                raw = round(raw * 0.75)
            dodge = get_accessory_bonus(p, "dodge_bonus") + get_enchant_bonus(p, "dodge_bonus")
            cls_p = get_player_class(p)
            if cls_p and cls_p.get("passive_key") == "evasion": dodge += 0.10
            if dodge > 0 and random.random() < dodge:
                lines.append(f"💨 *{p['username']}* dodges!")
            else:
                edm = calc_defense(p, raw)
                sr["player_hp"] = max(0, sr["player_hp"] - edm)
                if sr["player_hp"] == 0:
                    exp_loss = apply_pvp_death(p, killer_name=enemy["name"], cause="Solo Raid")
                    asyncio.create_task(_notify_defeat(context.bot, p, enemy["name"] + " (Solo Raid)"))
                    active_soloraids.pop(uid, None)
                    save_player(p)
                    lines.append(f"💀 *{enemy['name']}* kills *{p['username']}*! 6hr defeat. -{exp_loss} EXP.")
                    try:
                        await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown")
                    except Exception: pass
                    return
                else:
                    lines.append(f"🩸 *{enemy['name']}* hits *{p['username']}* for *{edm}!* "
                                 f"({sr['player_hp']}/{sr['player_max_hp']} raid HP)")
                    if sr["player_hp"] <= round(sr["player_max_hp"] * 0.30):
                        lines.append(f"⚠️ *Critically low HP!* Use /skill or a vial!")

    sr_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"sr_act_{uid}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"sr_act_{uid}_skl"),
    ]])
    save_player(p)
    try:
        await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown", reply_markup=sr_markup)
    except Exception: pass


# ── Boss Attack/Skill callback ──
async def boss_act_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # format: boss_act_{uid}_{action}
    if len(parts) < 4:
        return
    try:
        uid = int(parts[2])
        action = parts[3]
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your fight!", show_alert=True)
        return

    user = query.from_user
    p = get_player(uid)
    chat_id = query.message.chat.id

    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if is_defeated(p):
        await query.answer("You're defeated!", show_alert=True); return
    if cannot_attack(p):
        await query.answer("Stunned or rooted — can't act!", show_alert=True); return

    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    if not boss_dict:
        await query.answer("No active boss in this chat!", show_alert=True); return

    is_secret = chat_id in secret_boss_active

    if action == "skl":
        all_skills = sjl(p.get("all_skills"), [])
        if not all_skills:
            await query.answer("No skills unlocked yet!", show_alert=True); return
        if len(all_skills) > 1:
            markup = _build_skill_picker_keyboard(all_skills, uid, 0)
            await query.edit_message_text(
                f"🔮 *vs {boss_dict['data']['name']}* — choose a skill:",
                parse_mode="Markdown", reply_markup=markup)
            return
        sk = all_skills[0]

        if uid not in [u["id"] for u in boss_dict["participants"]]:
            boss_dict["participants"].append({"id": uid, "name": user.first_name, "dmg": 0})
        participant = next(u for u in boss_dict["participants"] if u["id"] == uid)

        w = get_weather()
        stype = sk.get("type", "damage")
        lines = [f"⚡ *{user.first_name}* uses *{sk['name']}* on *{boss_dict['data']['name']}*!"]

        if stype in ("self_heal", "group_heal", "mass_cleanse",
                     "dmg_reduction_buff", "self_heal_buff", "revive_heal"):
            if stype == "self_heal":
                heal = round(get_stat(p, "WIS") * sk.get("mult", 3.0))
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"💚 Healed self for *{heal} HP*!")
            elif stype == "self_heal_buff":
                heal = round(p["max_hp"] * 0.30)
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"💚 *Rally!* +{heal} HP restored.")
            dmg = 0
        else:
            mult = sk.get("mult", 1.0) or 1.0
            hits = sk.get("hits", 1)
            if hits and hits > 1:
                total = 0; hit_log = []
                for _ in range(hits):
                    h = round(calc_attack_damage(p, w) * mult)
                    if check_crit(p): h = apply_crit(p, h); hit_log.append(f"💥{h}")
                    else: hit_log.append(str(h))
                    total += h
                dmg = total
                lines.append(f"⚡ {hits}-hit combo! [{' + '.join(hit_log)}] = {dmg}")
            elif stype in ("freeze_nuke", "execute_nuke", "holy_nuke", "fear_kill"):
                stat_key = sk.get("stat", get_primary_stat(p))
                dmg = round(get_stat(p, stat_key) * sk.get("mult", 3.0))
                lines.append(f"💥 *{sk['name']}!* {dmg} damage!")
            elif stype in ("drain", "drain_kill", "hp_drain"):
                drain_pct = sk.get("drain_pct", 0.30)
                dmg = round(boss_dict["hp"] * drain_pct)
                heal = round(dmg * 0.50)
                p["hp"] = min(p["max_hp"], p["hp"] + heal)
                lines.append(f"🩸 *{sk['name']}!* Drained {dmg} HP! Healed {heal}.")
            else:
                dmg = round(calc_attack_damage(p, w) * mult)
            if stype not in ("multihit", "multi_hit") and hits == 1 and check_crit(p):
                dmg = apply_crit(p, dmg)
                lines.append("💥 *CRITICAL HIT!*")
            boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
            participant["dmg"] += dmg
            lines.append(f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}")

        # Counter-attack
        alive = [u for u in boss_dict["participants"]
                 if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp",{}).get(u["id"],1) > 0]
        if alive and boss_dict["hp"] > 0 and random.random() < 0.90:
            target = random.choice(alive)
            tp = get_player(target["id"])
            if tp:
                if "player_hp" not in boss_dict:
                    boss_dict["player_hp"] = {}; boss_dict["player_max_hp"] = {}
                    for u in boss_dict["participants"]:
                        pp2 = get_player(u["id"])
                        if pp2:
                            mhp2 = calc_max_hp(pp2)
                            boss_dict["player_hp"][u["id"]] = mhp2
                            boss_dict["player_max_hp"][u["id"]] = mhp2
                bdmg = calc_defense(tp, random.randint(
                    boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"]))
                boss_dict["player_hp"][target["id"]] = max(0,
                    boss_dict["player_hp"].get(target["id"], calc_max_hp(tp)) - bdmg)
                php  = boss_dict["player_hp"][target["id"]]
                pmhp = boss_dict["player_max_hp"].get(target["id"], calc_max_hp(tp))
                if php == 0:
                    exp_loss = apply_pvp_death(tp, killer_name=boss_dict['data']['name'], cause="Boss")
                    asyncio.create_task(_notify_defeat(context.bot, tp, boss_dict['data']['name'] + " (Boss)"))
                    save_player(tp)
                    lines.append(f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! 6hr defeat. -{exp_loss} EXP.")
                else:
                    lines.append(f"💥 Boss hits *{target['name']}* for *{bdmg}!* ({php}/{pmhp} HP)")
                save_player(tp)

        if boss_dict["hp"] <= 0:
            data = boss_dict["data"]
            if is_secret: secret_boss_active.pop(chat_id, None)
            else: active_bosses.pop(chat_id, None)
            lines.append(f"\n🏆 *{data['name']} DEFEATED by {sk['name']}!*\n")
            w2 = get_weather()
            for u in boss_dict["participants"]:
                pp = get_player(u["id"])
                if not pp: continue
                pp["gold"] = pp.get("gold", 0) + data["gold"]
                loot = roll_loot_table(data.get("loot_table", []))
                if loot:
                    add_item(pp, loot)
                    r = ""
                    for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                        if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity", ""), ""); break
                    lines.append(f"🎒 *{pp['username']}* found: {r} *{loot}*!")
                if award_title(pp, data["title"]):
                    lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
                lmsgs, leveled = add_exp(pp, data["exp"], w2)
                save_player(pp)
                lines.append(f"✅ *{pp['username']}*  -  +{data['exp']:,} EXP | +{data['gold']} Gold")
            save_player(p)
            try:
                await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown")
            except Exception: pass
            return

        save_player(p)
        boss_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚔️ Attack", callback_data=f"boss_act_{uid}_atk"),
            InlineKeyboardButton("✨ Skill",  callback_data=f"boss_act_{uid}_skl"),
        ]])
        try:
            await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown", reply_markup=boss_markup)
        except Exception: pass
        return

    # action == "atk"
    if uid not in [u["id"] for u in boss_dict["participants"]]:
        boss_dict["participants"].append({"id": uid, "name": user.first_name, "dmg": 0})
        if "player_hp" not in boss_dict:
            boss_dict["player_hp"] = {}; boss_dict["player_max_hp"] = {}
        mhp = calc_max_hp(p)
        boss_dict["player_hp"][uid] = mhp; boss_dict["player_max_hp"][uid] = mhp
    elif "player_hp" not in boss_dict:
        boss_dict["player_hp"] = {}; boss_dict["player_max_hp"] = {}
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if pp:
                mhp = calc_max_hp(pp)
                boss_dict["player_hp"][u["id"]] = mhp; boss_dict["player_max_hp"][u["id"]] = mhp
    participant = next(u for u in boss_dict["participants"] if u["id"] == uid)

    w = get_weather()
    dmg = calc_attack_damage(p, w)
    if check_crit(p): dmg = apply_crit(p, dmg)
    if safe_int(p.get("charging_killshot")):
        p["charging_killshot"] = 0; dmg = get_stat(p, "AGI") * 4

    boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
    participant["dmg"] += dmg

    lines = [
        f"⚔️ *{user.first_name}* strikes *{boss_dict['data']['name']}* for *{dmg}!*",
        f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}"
    ]

    alive = [u for u in boss_dict["participants"]
             if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp", {}).get(u["id"], 1) > 0]
    if alive and boss_dict["hp"] > 0 and random.random() < 0.90:
        hit_count = 2 if random.random() < 0.30 else 1
        targets = random.sample(alive, min(hit_count, len(alive)))
        for target in targets:
            tp = get_player(target["id"])
            if tp and not is_defeated(tp):
                raw = random.randint(boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"])
                edm = calc_defense(tp, raw)
                boss_dict["player_hp"][target["id"]] = max(0,
                    boss_dict["player_hp"].get(target["id"], calc_max_hp(tp)) - edm)
                php = boss_dict["player_hp"][target["id"]]
                pmhp = boss_dict["player_max_hp"].get(target["id"], calc_max_hp(tp))
                if php == 0:
                    exp_loss = apply_pvp_death(tp, killer_name=boss_dict['data']['name'], cause="Boss")
                    asyncio.create_task(_notify_defeat(context.bot, tp, boss_dict['data']['name'] + " (Boss)"))
                    save_player(tp)
                    lines.append(f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! 6hr defeat. -{exp_loss} EXP.")
                else:
                    lines.append(f"💥 *{boss_dict['data']['name']}* hits *{target['name']}* for *{edm}!* ({php}/{pmhp} HP)")
                save_player(tp)

    alive_after = [u for u in boss_dict["participants"]
                   if not is_defeated(get_player(u["id"])) and boss_dict.get("player_hp", {}).get(u["id"], 1) > 0]
    if not alive_after and boss_dict["hp"] > 0:
        if is_secret: secret_boss_active.pop(chat_id, None)
        else: active_bosses.pop(chat_id, None)
        lines.append("💀 *ALL PLAYERS DEFEATED!* The boss wins...")
        save_player(p)
        try:
            await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown")
        except Exception: pass
        return

    if boss_dict["hp"] <= 0:
        data = boss_dict["data"]
        if is_secret: secret_boss_active.pop(chat_id, None)
        else: active_bosses.pop(chat_id, None)
        lines.append(f"\n🏆 *{data['name']} DEFEATED!*\n")
        w2 = get_weather()
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if not pp: continue
            pp["gold"] = pp.get("gold", 0) + data["gold"]
            loot = roll_loot_table(data.get("loot_table", []))
            if loot:
                add_item(pp, loot); r = ""
                for pool in [WEAPONS, ARMORS, ACCESSORIES]:
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity", ""), ""); break
                lines.append(f"🎒 *{pp['username']}* found: {r} *{loot}*!")
            if award_title(pp, data["title"]):
                lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
            add_exp(pp, data["exp"], w2); save_player(pp)
            lines.append(f"✅ *{pp['username']}*  -  +{data['exp']} EXP | +{data['gold']} Gold")
        save_player(p)
        try:
            await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown")
        except Exception: pass
        return

    save_player(p)
    boss_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Attack", callback_data=f"boss_act_{uid}_atk"),
        InlineKeyboardButton("✨ Skill",  callback_data=f"boss_act_{uid}_skl"),
    ]])
    try:
        await query.edit_message_text(text="\n".join(lines)[:4096], parse_mode="Markdown", reply_markup=boss_markup)
    except Exception: pass


# ── Prestige Path callback ──
async def prestige_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # format: prestige_{uid}_{path}
    if len(parts) < 3:
        return
    try:
        uid = int(parts[1])
        path = parts[2].upper()
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your prestige menu!", show_alert=True)
        return

    user = query.from_user
    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return

    cid = p.get("class_id")
    if not cid:
        await query.answer("Choose a class first with /class.", show_alert=True); return
    cls = CLASS_TREE.get(cid, {})
    line = cls.get("line")
    existing_path = p.get("class_path")
    if existing_path:
        await query.answer("You already chose a path!", show_alert=True); return
    if p["level"] < 10:
        await query.answer("Path selection requires Level 10!", show_alert=True); return
    if path not in ("A", "B"):
        await query.answer("Invalid path.", show_alert=True); return

    paths = CLASS_PATHS.get(line, {})
    first_class = paths.get(path, [])[0] if paths.get(path) else None
    if not first_class:
        await query.answer("Invalid path for your class.", show_alert=True); return

    p["class_path"] = path
    p["class_id"] = first_class
    new_cls = CLASS_TREE.get(first_class, {})
    sd = safe_stats(p)
    for stat, bonus in new_cls.get("stat_bonus", {}).items():
        sd[stat] = sd.get(stat, 5) + bonus
    p["stats"] = json.dumps(sd)
    existing_skills = sjl(p.get("all_skills"), [])
    for sk in new_cls.get("skills", []):
        if sk["name"] not in [s["name"] for s in existing_skills]:
            existing_skills.append(sk)
    p["all_skills"] = json.dumps(existing_skills)
    save_player(p)

    asyncio.create_task(announce(context.bot, query.message.chat.id,
        f"🌟 *{p['username']}* chose *Path {path}*  -  *{new_cls['name']}*!"))
    full_path = paths.get(path, [])
    path_names = " → ".join(CLASS_TREE.get(k, {}).get("name", "?") for k in full_path)
    msg = (f"🌟 *Path {path} chosen!* You are now a *{new_cls['name']}*!\n\n"
           f"_{new_cls['desc']}_\n\n"
           f"📜 Your journey: {path_names}\n\n"
           f"_Your class evolves automatically at Levels 30, 60, and 100._")
    try:
        await query.edit_message_text(msg, parse_mode="Markdown")
    except Exception:
        pass


# ── Dungeon difficulty callback ──
async def dungeon_diff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # format: dungeon_d_{uid}_{diff}
    if len(parts) < 4:
        return
    try:
        uid = int(parts[2])
        diff = parts[3].lower()
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your dungeon picker!", show_alert=True)
        return

    user = query.from_user
    p = get_player(uid)
    chat_id = query.message.chat.id

    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return
    if is_defeated(p):
        await query.answer("You're too beaten up to enter a dungeon run!", show_alert=True); return
    if not check_cooldown(p.get("last_dungeon"), 86400):
        remaining = time_remaining(p.get("last_dungeon"), 86400)
        await query.answer(f"Dungeon run cooldown: {remaining}", show_alert=True); return
    if uid in active_dungeons:
        await query.answer("You're already in a dungeon run!", show_alert=True); return

    if diff not in ("normal", "hard", "legendary"):
        diff = "normal"

    level_reqs = {"normal": 1, "hard": 15, "legendary": 40}
    if p["level"] < level_reqs[diff]:
        await query.answer(
            f"{diff.capitalize()} requires Level {level_reqs[diff]}. You're Level {p['level']}.",
            show_alert=True); return

    # Delete the picker message
    try:
        await query.delete_message()
    except Exception:
        pass

    theme = random.choice(DUNGEON_THEMES)
    room_distributions = {
        "normal":    ["monster","trap","treasure","puzzle","rest"],
        "hard":      ["monster","trap","treasure","puzzle","rest","monster","mini_boss"],
        "legendary": ["monster","trap","treasure","puzzle","rest",
                      "ambush","merchant","altar","monster","mini_boss"],
    }
    rooms = room_distributions[diff].copy()
    random.shuffle(rooms)
    timers        = {"normal": 2700, "hard": 3600, "legendary": 5400}
    timer_display = {"normal": "45 minutes", "hard": "1 hour", "legendary": "90 minutes"}

    p["last_dungeon"] = datetime.now().isoformat()
    save_player(p)
    cls      = get_player_class(p)
    cls_name = cls["name"] if cls else "Player"
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(f"🏰 *{user.first_name}* enters *{theme['name']}!*\n\n"
                  f"_{theme['desc']}_\n\n"
                  f"⚔️ Class: {cls_name} | 📊 Level {p['level']}\n"
                  f"🎯 Difficulty: *{diff.capitalize()}*\n"
                  f"🚪 {len(rooms)} rooms + final boss\n\n"
                  f"_Results in {timer_display[diff]}._")[:4096],
            parse_mode="Markdown")
    except Exception:
        pass

    async def run_dungeon():
        await asyncio.sleep(timers[diff])
        active_dungeons.pop(uid, None)
        fp = get_player(uid)
        if not fp: return
        results      = []
        total_exp    = 0
        total_gold   = 0
        items_found  = []
        hp_remaining = fp["max_hp"]
        run_failed   = False
        line = get_class_line(fp)
        for i, room_type in enumerate(rooms, 1):
            if run_failed: break
            result = _resolve_dungeon_room(fp, room_type, theme, diff, i, hp_remaining, line)
            hp_remaining = max(1, hp_remaining - result.get("hp_cost", 0))
            total_exp  += result.get("exp", 0)
            total_gold += result.get("gold", 0)
            if result.get("item"): items_found.append(result["item"])
            results.append(result)
            if hp_remaining <= 1 and not result.get("success"):
                run_failed = True
                results.append({"type":"defeat","narrative":(
                    f"Room {i+1} would have finished you. "
                    f"You make the call to retreat while you still can. "
                    f"The hall lets you go. This time.")})
        if not run_failed:
            boss_result = _resolve_dungeon_boss(fp, theme, diff, line)
            total_exp  += boss_result.get("exp", 0)
            total_gold += boss_result.get("gold", 0)
            if boss_result.get("item"): items_found.append(boss_result["item"])
            results.append(boss_result)
            bonus = DUNGEON_LOOT[diff]["completion_bonus"]
            total_exp  += bonus["exp"]
            total_gold += bonus["gold"]
        lmsgs, leveled = add_exp(fp, total_exp)
        fp["gold"] = fp.get("gold", 0) + total_gold
        for item in items_found: add_item(fp, item)
        if not run_failed:
            for _d, _e, _g in track_objective(fp, "dungeon_run"):
                fp["gold"] = fp.get("gold", 0) + _g; add_exp(fp, _e)
        save_player(fp)
        recap = _build_dungeon_recap(fp, theme, diff, results, total_exp, total_gold,
                                     items_found, run_failed, lmsgs)
        await announce(context.bot, chat_id, recap, delay=180)
        if leveled and fp["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{fp['username']}* reached *Level {fp['level']}* "
                f"from the depths of *{theme['name']}*! 🏰", permanent=True))

    task = asyncio.create_task(run_dungeon())
    active_dungeons[uid] = task


# ── Shop Buy callback ──
async def shop_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    # format: shop_b_{uid}_{idx}
    if len(parts) < 4:
        return
    try:
        uid = int(parts[2])
        idx = int(parts[3])
    except (ValueError, IndexError):
        return
    if query.from_user.id != uid:
        await query.answer("This isn't your shop!", show_alert=True)
        return

    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return

    discount = 0
    if _ts_active(p, "shop_discount_until"): discount = 0.20
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"), 1)
            guild_disc = 0.15 if glvl >= 10 else (0.10 if glvl >= 7 else 0)
            discount = max(discount, guild_disc)

    shop = get_daily_shop()
    if idx < 0 or idx >= len(shop):
        await query.answer("Invalid item.", show_alert=True); return

    entry = shop[idx]
    price = round(entry["price"] * (1 - discount))
    if p["gold"] < price:
        await query.answer(f"Not enough gold! Need {price}g, have {p['gold']}g.", show_alert=True); return

    p["gold"] -= price
    add_item(p, entry["item"])
    save_player(p)

    # Rebuild the shop display with updated gold
    lines = [f"🛒 *Daily Shop* | 💰 {p['gold']} gold\n"]
    if discount: lines.append(f"🏷️ Discount active: *{int(discount*100)}% off!*\n")
    buttons = []
    for i, e in enumerate(shop):
        ep = round(e["price"] * (1 - discount))
        lines.append(f"{i+1}. *{e['item']}*  -  {ep}g\n   _{e['desc']}_")
        buttons.append([InlineKeyboardButton(f"Buy {i+1}: {e['item']}", callback_data=f"shop_b_{uid}_{i}")])
    markup = InlineKeyboardMarkup(buttons)
    lines.append(f"\n✅ Bought *{entry['item']}* for {price}g!")

    try:
        await query.edit_message_text("\n".join(lines)[:4096], parse_mode="Markdown",
                                      reply_markup=markup)
    except Exception:
        pass


# ── Allocate Stats callback ──
async def allocate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split("_")
    # format: alloc_{uid}_{stat}_{amt}
    if len(parts) < 4:
        await query.answer(); return
    try:
        uid  = int(parts[1])
        stat = parts[2].upper()
        amt  = int(parts[3])
    except (ValueError, IndexError):
        await query.answer(); return
    if query.from_user.id != uid:
        await query.answer("This isn't your stat screen!", show_alert=True)
        return

    p = get_player(uid)
    if not p:
        await query.answer("Use /ascend first!", show_alert=True); return

    STAT_NAMES = ["STR","AGI","INT","WIS","DEX","LUK"]
    if stat not in STAT_NAMES:
        await query.answer("Invalid stat.", show_alert=True); return

    sp = safe_int(p.get("stat_points"))
    if amt > sp:
        await query.answer("Not enough stat points!", show_alert=True); return

    sd = safe_stats(p)
    sd[stat] = sd.get(stat, 5) + amt
    p["stats"] = json.dumps(sd)
    p["stat_points"] = sp - amt
    save_player(p)
    sp = p["stat_points"]

    await query.answer(f"+{amt} {stat}! {sp} points left.")

    # Rebuild the allocate message with updated stats and buttons
    cls = get_player_class(p)
    rec = cls["primary_stat"] + " recommended" if cls else "Free to allocate"
    text = (f"📊 *Stat Allocation*  -  *{sp}* points available\n\n"
            f"STR:{sd.get('STR',5)} AGI:{sd.get('AGI',5)} INT:{sd.get('INT',5)} "
            f"WIS:{sd.get('WIS',5)} DEX:{sd.get('DEX',5)} LUK:{sd.get('LUK',5)}\n\n"
            f"📌 STR  -  Attack damage (Warrior)\n"
            f"📌 AGI  -  Dodge & crit\n"
            f"📌 INT  -  Spell damage (Mage)\n"
            f"📌 WIS  -  Heal power (Priest)\n"
            f"📌 DEX  -  Accuracy & crit (Archer)\n"
            f"📌 LUK  -  Crit & gold bonus (Thief)\n"
            f"📌 DEF  -  From gear only (cannot allocate)\n\n"
            f"🧭 {rec}")
    rows = []
    if sp > 0:
        for s in STAT_NAMES:
            row = [InlineKeyboardButton(f"{s} +1", callback_data=f"alloc_{uid}_{s}_1")]
            if sp >= 5:
                row.append(InlineKeyboardButton(f"{s} +5", callback_data=f"alloc_{uid}_{s}_5"))
            rows.append(row)
    markup = InlineKeyboardMarkup(rows) if rows else None
    try:
        await query.edit_message_text(text[:4096], parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass


# ── MAIN ──────────────────────────────────────────────────────────────────────
async def _post_init(application):
    """On startup: DM admin if bot version changed."""
    version_file = "/data/bot_version.txt"
    try:
        with open(version_file) as f:
            last_version = f.read().strip()
    except Exception:
        last_version = None
    if last_version == CURRENT_VERSION:
        return
    try:
        with open(version_file, "w") as f:
            f.write(CURRENT_VERSION)
    except Exception: pass
    entry = next((e for e in reversed(CHANGELOG) if e["version"] == CURRENT_VERSION), None)
    if not entry: return
    changes_text = "\n".join(f"• {c}" for c in entry["changes"])
    msg = (f"🎱 *Bot Updated to {CURRENT_VERSION}*\n"
           f"_{entry['date']}_\n\n"
           f"{changes_text}")
    try:
        await application.bot.send_message(
            chat_id=ADMIN_ID, text=msg, parse_mode="Markdown")
    except Exception: pass

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    # Universal
    app.add_handler(CommandHandler("rank",         rank_cmd))
    app.add_handler(CommandHandler("rankme",       rankme_cmd))
    app.add_handler(CommandHandler("rankwins",     rankwins_cmd))
    app.add_handler(CommandHandler("stats",        stats_cmd))
    app.add_handler(CommandHandler("guide",        guide_cmd))
    app.add_handler(CommandHandler("help",         guide_cmd))
    # ── Pets ──────────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("pet",          pet_cmd))
    app.add_handler(CommandHandler("pets",         pet_cmd))
    app.add_handler(CommandHandler("petshop",      petshop_cmd))
    app.add_handler(CommandHandler("hatch",        hatch_cmd))
    app.add_handler(CommandHandler("petrename",    petrename_cmd))
    app.add_handler(CommandHandler("weather",      weather_cmd))
    app.add_handler(CommandHandler("ascend",       ascend_cmd))
    app.add_handler(CommandHandler("cooldowns",    cooldowns_cmd))
    app.add_handler(CommandHandler("who",          who_cmd))
    app.add_handler(CommandHandler("history",      history_cmd))
    app.add_handler(CommandHandler("war",          war_cmd))
    app.add_handler(CommandHandler("forge",        forge_cmd))

    # Class & progression
    app.add_handler(CommandHandler("class",     class_cmd))
    app.add_handler(CommandHandler("prestige",  prestige_cmd))
    app.add_handler(CommandHandler("allocate",  allocate_cmd))
    app.add_handler(CommandHandler("resetstats",  resetstats_cmd))
    app.add_handler(CommandHandler("resetclass",  resetclass_cmd))
    app.add_handler(CommandHandler("skill",     skill_cmd))
    app.add_handler(CommandHandler("title",     title_cmd))

    # Activities
    app.add_handler(CommandHandler("daily",     daily_cmd))
    app.add_handler(CommandHandler("train",     train_cmd))
    app.add_handler(CommandHandler("quest",     quest_cmd))
    app.add_handler(CommandHandler("explore",   explore_cmd))
    app.add_handler(CommandHandler("pool",      pool_cmd))
    app.add_handler(CommandHandler("hustle",    hustle_cmd))

    # Economy
    app.add_handler(CommandHandler("shop",      shop_cmd))
    app.add_handler(CommandHandler("inventory", inventory_cmd))
    app.add_handler(CommandHandler("equip",     equip_cmd))
    app.add_handler(CommandHandler("unequip",   unequip_cmd))
    app.add_handler(CommandHandler("use",       use_item_cmd))
    app.add_handler(CommandHandler("sell",      sell_cmd))
    app.add_handler(CommandHandler("trade",     trade_cmd))
    app.add_handler(CommandHandler("accept",    accept_trade_cmd))
    app.add_handler(CommandHandler("decline",   decline_trade_cmd))
    app.add_handler(CommandHandler("enhance",    enhance_cmd))
    app.add_handler(CommandHandler("enchant",    enchant_cmd))
    app.add_handler(CommandHandler("reinforce",  reinforce_cmd))
    app.add_handler(CommandHandler("objectives", objectives_cmd))
    app.add_handler(CommandHandler("bounty",     bounty_cmd))
    app.add_handler(CommandHandler("bounties",   bounties_cmd))
    app.add_handler(CommandHandler("changelog",  changelog_cmd))
    app.add_handler(CommandHandler("gear",       gear_cmd))

    # Marriage
    app.add_handler(CommandHandler("marry",   marry_cmd))
    app.add_handler(CommandHandler("divorce", divorce_cmd))
    app.add_handler(CallbackQueryHandler(marry_callback,   pattern="^marry_(accept|decline)_"))
    app.add_handler(CallbackQueryHandler(divorce_callback, pattern="^divorce_(confirm|cancel)_"))

    # Combat & Dungeons
    app.add_handler(CommandHandler("duel",       duel_cmd))
    app.add_handler(CommandHandler("arena",      arena_cmd))
    app.add_handler(CommandHandler("attack",     attack_cmd))
    app.add_handler(CommandHandler("heal",       heal_cmd))
    app.add_handler(CommandHandler("boss",       boss_cmd))
    # strike_cmd kept for reference but unregistered  -  use /attack instead
    # app.add_handler(CommandHandler("strike",     strike_cmd))
    app.add_handler(CommandHandler("dungeon",          dungeon_cmd))
    app.add_handler(CommandHandler("dungeonhard",      dungeonhard_cmd))
    app.add_handler(CommandHandler("dungeonlegendary", dungeonlegendary_cmd))
    app.add_handler(CommandHandler("raid",          raid_cmd))
    app.add_handler(CommandHandler("raidstart",     raidstart_cmd))
    app.add_handler(CommandHandler("raidstrike",    raidstrike_cmd))
    app.add_handler(CommandHandler("raidstatus",    raidstatus_cmd))
    app.add_handler(CommandHandler("raidparty",     raidparty_cmd))
    app.add_handler(CommandHandler("soloraid",      soloraid_cmd))
    app.add_handler(CommandHandler("solostrike",    solostrike_cmd))
    app.add_handler(CommandHandler("soloraidstatus",soloraidstatus_cmd))

    # Guild
    app.add_handler(CommandHandler("guild",          guild_cmd))
    app.add_handler(CommandHandler("guildcreate",    guildcreate_cmd))
    app.add_handler(CommandHandler("guildjoin",      guildjoin_cmd))
    app.add_handler(CommandHandler("guildinfo",      guildinfo_cmd))
    app.add_handler(CommandHandler("guildlist",      guildlist_cmd))
    app.add_handler(CommandHandler("guilddonate",    guilddonate_cmd))
    app.add_handler(CommandHandler("guildkick",      guildkick_cmd))
    app.add_handler(CommandHandler("guildleave",     guildleave_cmd))
    app.add_handler(CommandHandler("guilddisband",   guilddisband_cmd))
    app.add_handler(CommandHandler("guildwar",       guildwar_cmd))
    app.add_handler(CommandHandler("gbank",          gbank_cmd))

    # Events
    app.add_handler(CommandHandler("greet",     greet_event))
    app.add_handler(CommandHandler("fight",     fight_event))
    app.add_handler(CommandHandler("shoot",     shoot_event))
    app.add_handler(CommandHandler("claim",     claim_cmd))
    app.add_handler(CommandHandler("pray",      pray_event))

    # Admin
    app.add_handler(CommandHandler("wipe",      wipe_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(rank_callback,         pattern="^rank_p_"))
    app.add_handler(CallbackQueryHandler(inventory_callback,    pattern="^inv_s_"))
    app.add_handler(CallbackQueryHandler(guide_callback,        pattern="^guide_p_"))
    app.add_handler(CallbackQueryHandler(stats_callback,        pattern="^stats_p_"))
    app.add_handler(CallbackQueryHandler(guildjoin_callback,       pattern="^guildjoin_"))
    app.add_handler(CallbackQueryHandler(guildwar_declare_callback, pattern="^gwdeclare_"))
    app.add_handler(CallbackQueryHandler(guildkick_callback,        pattern="^gkick_"))
    app.add_handler(CallbackQueryHandler(guildinfo_view_callback,   pattern="^ginfo_"))
    app.add_handler(CallbackQueryHandler(guildinfo_members_callback,pattern="^ginfoM_"))
    app.add_handler(CallbackQueryHandler(guildinfo_list_callback,   pattern="^ginfoList$"))
    app.add_handler(CallbackQueryHandler(bounty_amount_callback,    pattern="^bountyamt_"))
    app.add_handler(CallbackQueryHandler(trade_item_callback,       pattern="^trdi_"))
    app.add_handler(CallbackQueryHandler(trade_price_callback,      pattern="^trdp_"))
    app.add_handler(CallbackQueryHandler(trade_back_callback,       pattern="^trdback_"))
    app.add_handler(CallbackQueryHandler(duel_wager_callback,       pattern="^duelwager_"))
    app.add_handler(CallbackQueryHandler(soloraid_act_callback, pattern="^sr_act_"))
    app.add_handler(CallbackQueryHandler(boss_act_callback,     pattern="^boss_act_"))
    app.add_handler(CallbackQueryHandler(prestige_callback,     pattern="^prestige_"))
    app.add_handler(CallbackQueryHandler(dungeon_diff_callback, pattern="^dungeon_d_"))
    app.add_handler(CallbackQueryHandler(shop_buy_callback,     pattern="^shop_b_"))
    app.add_handler(CallbackQueryHandler(boss_start_callback,   pattern="^bossstart_"))
    app.add_handler(CallbackQueryHandler(enhance_slot_callback, pattern="^enhance_"))
    app.add_handler(CallbackQueryHandler(enchant_slot_callback, pattern="^enchant_"))
    app.add_handler(CallbackQueryHandler(allocate_callback,     pattern="^alloc_"))
    # New inline button callbacks
    app.add_handler(CallbackQueryHandler(arena_act_callback,     pattern="^arena_act_"))
    app.add_handler(CallbackQueryHandler(raid_atk_callback,      pattern="^raid_atk_"))
    app.add_handler(CallbackQueryHandler(duel_response_callback, pattern="^duel_(acc|dec)_"))
    app.add_handler(CallbackQueryHandler(resetclass_callback,    pattern="^rscls_"))
    app.add_handler(CallbackQueryHandler(resetstats_callback,    pattern="^rsstat_"))
    app.add_handler(CallbackQueryHandler(guilddisband_callback,  pattern="^gdisband_"))
    app.add_handler(CallbackQueryHandler(class_pick_callback,    pattern="^class_pick_"))
    app.add_handler(CallbackQueryHandler(class_browse_callback,      pattern="^classbrowse_"))
    app.add_handler(CallbackQueryHandler(class_progression_callback, pattern="^clsprog_"))
    app.add_handler(CallbackQueryHandler(skill_tree_callback,    pattern="^sktree_"))
    app.add_handler(CallbackQueryHandler(skill_pick_callback,   pattern="^skillpick_"))
    app.add_handler(CallbackQueryHandler(skillpage_callback,    pattern="^skillpage_"))
    app.add_handler(CallbackQueryHandler(equip_item_callback,   pattern="^eqp_"))
    app.add_handler(CallbackQueryHandler(unequip_slot_callback, pattern="^uneqp_"))
    app.add_handler(CallbackQueryHandler(use_item_callback,     pattern="^useitem_"))
    app.add_handler(CallbackQueryHandler(settitle_callback,     pattern="^settitle_"))
    app.add_handler(CallbackQueryHandler(reinforce_item_callback, pattern="^rf_"))
    app.add_handler(CallbackQueryHandler(reinforce_asc_callback,  pattern="^rfasc_"))
    app.add_handler(CallbackQueryHandler(sell_item_callback,    pattern="^sll_"))
    app.add_handler(CallbackQueryHandler(sell_rarity_callback,  pattern="^sellr_"))
    app.add_handler(CallbackQueryHandler(forge_craft_callback,  pattern="^forge_"))
    app.add_handler(CallbackQueryHandler(explore_zone_callback, pattern="^explore_"))
    app.add_handler(CallbackQueryHandler(guilddonate_callback,  pattern="^gdonate_"))
    # ── Pets ──────────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(petshop_callback,    pattern="^(petshop|pbuy_)"))
    app.add_handler(CallbackQueryHandler(hatch_egg_callback,  pattern="^hatch_egg$"))
    app.add_handler(CallbackQueryHandler(pet_main_callback,
        pattern="^(petmain|petlist_|petview_|petactivate_|petfeed_|pettrain_|petrelease_|petrename_)"))

    # Passive
    app.add_handler(MessageHandler(~filters.COMMAND, handle_message))

    explore_timers.clear()
    print(f"🎱 {WORLD_NAME} {CURRENT_VERSION} is running...")
    app.run_polling(poll_interval=0.3)

if __name__ == "__main__":
    main()
