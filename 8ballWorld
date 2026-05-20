#!/usr/bin/env python3
"""
The World of 8Ball — RPG Bot v13
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

# ── GLOBAL STATE ──────────────────────────────────────────────────────────────
last_bot_message   = {}   # (chat_id, user_id) -> msg_id
active_bosses      = {}   # chat_id -> boss dict
secret_boss_active = {}
active_events      = {}   # chat_id -> event dict
active_raids       = {}   # chat_id -> raid dict
active_drakes      = {}   # chat_id -> drake dict
combat_cards       = {}   # chat_id -> {target_id, msg_id, attackers[]}
message_counters   = {}   # chat_id -> int
pending_trades     = {}   # user_id -> trade dict
pending_guild_reqs = {}   # guild_id -> [requests]
explore_timers     = {}   # user_id -> asyncio task

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
def safe_stats(p):  return sjl(p.get("stats"), {"STR":5,"DEF":5,"AGI":5,"INT":5,"WIS":5})
def safe_titles(p): return sjl(p.get("titles"), ["The Newcomer"])
def safe_cds(p):    return sjl(p.get("passive_cooldowns"), {})
def safe_int(v, d=0):
    try: return int(v or d)
    except: return d

# ── WORLD & WEATHER ───────────────────────────────────────────────────────────
WORLD_NAME = "The World of 8Ball"

WEATHER_TABLE = [
    {"name":"Freshly Felted",     "desc":"The table is pristine.",          "exp_mod":1.20,"dmg_mod":1.00},
    {"name":"High Humidity",      "desc":"The felt is damp and slow.",      "exp_mod":1.00,"dmg_mod":0.90},
    {"name":"Perfect Conditions", "desc":"Everything is in balance.",       "exp_mod":1.10,"dmg_mod":1.10},
    {"name":"Chalk Dust Storm",   "desc":"Visibility is low.",              "exp_mod":0.90,"dmg_mod":1.15},
    {"name":"The Break Hour",     "desc":"Energy surges through the felt.", "exp_mod":1.30,"dmg_mod":1.20,"secret_eligible":True},
    {"name":"Dead Cloth",         "desc":"The felt is worn and sluggish.",  "exp_mod":0.85,"dmg_mod":0.85},
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
    {"name":"👑 Legends",   "emoji":"👑","min":75,"max":100},
    {"name":"⚔️ Veterans",  "emoji":"⚔️","min":50,"max":74},
    {"name":"🔥 Rising",    "emoji":"🔥","min":25,"max":49},
    {"name":"💬 Active",    "emoji":"💬","min":10,"max":24},
    {"name":"🌱 Newcomers", "emoji":"🌱","min":1,  "max":9},
]
def get_tier(level):
    for t in RANK_TIERS:
        if t["min"] <= level <= t["max"]: return t
    return RANK_TIERS[-1]

PAGE_SIZE = 15

# ── CLASS TREE ────────────────────────────────────────────────────────────────
DEFAULT_STATS = {"STR":5,"DEF":5,"AGI":5,"INT":5,"WIS":5}

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
        "desc":"A master of the blade. Tough, relentless, built to endure.",
        "stat_bonus":{"STR":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Iron Will",
             "passive":"Take 10% less damage from all sources.",
             "active":"Shield Bash","type":"stun",
             "desc":"30% chance to stun target — they miss their next attack.",
             "passive_key":"iron_will"},
        ]
    },
    "page": {
        "name":"Page","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"A holy knight in training. Defense and devotion.",
        "stat_bonus":{"STR":1,"DEF":2},
        "skills":[
            {"tier":2,"unlock":10,"name":"Holy Stance",
             "passive":"Gain +15% defense when below 50% HP.",
             "active":"Consecrate","type":"dmg_field",
             "desc":"Deal damage + create a holy field for 30 min — enemies who attack you take WIS x2 holy damage back.",
             "passive_key":"holy_stance"},
        ]
    },
    "squire": {
        "name":"Squire","primary_stat":"STR","line":"warrior","path":"A",
        "weapon_types":["sword_1h","shield"],
        "armor_type":"warrior_armor",
        "desc":"Devoted to the holy path. Each blow fuels the next.",
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
        "desc":"A true knight. Near-unbreakable defense and rallying power.",
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
        "desc":"The pinnacle of the holy knight. Divine judgment incarnate.",
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
        "desc":"Raw aggression. Every hit heals, every kill fuels the next.",
        "stat_bonus":{"STR":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Bloodlust",
             "passive":"Each hit landed restores 5 HP.",
             "active":"Double Strike","type":"multihit",
             "desc":"Hit twice. Each hit has independent crit chance. If both crit, Bloodlust heal triples.",
             "passive_key":"bloodlust","hits":2},
        ]
    },
    "crusader": {
        "name":"Crusader","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"A charging force of nature. Unstoppable momentum.",
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
        "desc":"A living legend. Cannot be one-shotted. Rampage is inevitable.",
        "stat_bonus":{"STR":5,"DEF":2},
        "skills":[
            {"tier":4,"unlock":60,"name":"Unbreakable",
             "passive":"Cannot be one-shotted — always survive at 1 HP (once per fight).",
             "active":"Rampage","type":"aoe_recent_attackers",
             "desc":"Hit everyone who attacked you in the last 30 minutes. Damage scales +25% per attacker.",
             "passive_key":"unbreakable"},
        ]
    },
    "warlord": {
        "name":"Warlord","primary_stat":"STR","line":"warrior","path":"B",
        "weapon_types":["sword_2h"],
        "armor_type":"warrior_armor",
        "desc":"The apex predator. Every kill makes you stronger.",
        "stat_bonus":{"STR":6,"DEF":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Conqueror",
             "passive":"Every PVP kill restores 20% HP. Defeated targets take +25% more damage from all sources for 1 hour.",
             "active":"Decimation","type":"execute_nuke",
             "desc":"STR x6 damage, ignores all defense. On kill: target is weakened — takes 25% more damage for 1 hour.",
             "passive_key":"conqueror"},
        ]
    },
    # ── MAGE ─────────────────────────────────────────────────────────────────
    "mage": {
        "name":"Mage","primary_stat":"INT","line":"mage",
        "weapon_types":["wand","staff"],
        "armor_type":"mage_armor",
        "desc":"Wielder of arcane power. Intelligence is the deadliest weapon.",
        "stat_bonus":{"INT":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Arcane Mind",
             "passive":"Each INT point adds +1 spell damage.",
             "active":"Fireball","type":"spell",
             "desc":"INT-scaled burst damage.",
             "passive_key":"arcane_mind"},
        ]
    },
    "arcanist": {
        "name":"Arcanist","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Pure arcane power. Spells surge and chain.",
        "stat_bonus":{"INT":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Spell Surge",
             "passive":"20% chance any spell deals double damage.",
             "active":"Chain Lightning","type":"bounce_spell",
             "desc":"Hits target + bounces to 2 nearby active players dealing 50% damage each.",
             "passive_key":"spell_surge"},
        ]
    },
    "sorcerer": {
        "name":"Sorcerer","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Every third spell is catastrophic.",
        "stat_bonus":{"INT":4},
        "skills":[
            {"tier":3,"unlock":30,"name":"Arcane Mastery",
             "passive":"Every 3rd spell cast deals triple damage (tracked internally).",
             "active":"Meteor","type":"aoe_recent_attackers",
             "desc":"Massive AOE — hits target + everyone who attacked them in last 30 minutes.",
             "passive_key":"arcane_mastery"},
        ]
    },
    "archmage": {
        "name":"Archmage","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Magic flows through you. Attackers pay in kind.",
        "stat_bonus":{"INT":5,"AGI":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Mana Overload",
             "passive":"15% chance any attack against you triggers a shock — attacker takes INT-scaled damage back.",
             "active":"Supernova","type":"raid_aoe",
             "desc":"INT x5 — hits all players currently in an active boss or raid fight.",
             "passive_key":"mana_overload"},
        ]
    },
    "sage": {
        "name":"Sage","primary_stat":"INT","line":"mage","path":"A",
        "weapon_types":["wand"],
        "armor_type":"mage_armor",
        "desc":"Ancient wisdom made lethal. Spells cut through all resistance.",
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
        "desc":"Dark magic fused with steel. Curses that linger.",
        "stat_bonus":{"INT":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Cursed Blade",
             "passive":"Physical attacks carry a hex — target deals 10% less damage for 2 minutes.",
             "active":"Hex","type":"debuff",
             "desc":"Curse target — they deal 25% less damage for 2 minutes.",
             "passive_key":"cursed_blade"},
        ]
    },
    "warlock": {
        "name":"Warlock","primary_stat":"INT","line":"mage","path":"B",
        "weapon_types":["staff"],
        "armor_type":"mage_armor",
        "desc":"A pact with darkness. Life drains into power.",
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
        "desc":"Undead sorcerer. Death cannot hold you.",
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
        "desc":"Master of the void. Reality itself bends to your will.",
        "stat_bonus":{"INT":6,"AGI":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Void Rift",
             "passive":"25% chance any attack against you misses — absorbed by the void.",
             "active":"Void Collapse","type":"void_nuke",
             "desc":"Target loses 50% of current HP instantly. Cannot be healed for 30 minutes.",
             "passive_key":"void_rift"},
        ]
    },
    # ── THIEF ─────────────────────────────────────────────────────────────────
    "thief": {
        "name":"Thief","primary_stat":"AGI","line":"thief",
        "weapon_types":["dagger","throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Fast, sneaky, lethal. Strike before they see you coming.",
        "stat_bonus":{"AGI":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Quick Hands",
             "passive":"+15% crit chance on all attacks.",
             "active":"Backstab","type":"crit_dmg",
             "desc":"180% damage. Guaranteed crit if target has not attacked yet.",
             "passive_key":"quick_hands","mult":1.8},
        ]
    },
    "rogue": {
        "name":"Rogue","primary_stat":"AGI","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Evasion and shadows. Hard to hit, deadly when you do.",
        "stat_bonus":{"AGI":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Evasion",
             "passive":"15% chance to dodge any incoming attack.",
             "active":"Smoke Screen","type":"dodge_buff",
             "desc":"Next attack against you automatically misses. Lasts 2 minutes.",
             "passive_key":"evasion"},
        ]
    },
    "shadow": {
        "name":"Shadow","primary_stat":"AGI","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"You are the darkness. Every dodge fuels destruction.",
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
        "name":"Phantom","primary_stat":"AGI","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"More ghost than person. Attacks pass through you.",
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
        "name":"Wraith","primary_stat":"AGI","line":"thief","path":"A",
        "weapon_types":["dagger"],
        "armor_type":"thief_armor",
        "desc":"Death made flesh. Every dodge restores, every kill protects.",
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
        "name":"Cutthroat","primary_stat":"AGI","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"First strike, last strike. Mark them and end them.",
        "stat_bonus":{"AGI":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Marked",
             "passive":"First attack on any target deals +25% bonus damage.",
             "active":"Cheap Shot","type":"silence",
             "desc":"150% damage. Target cannot use /skill for 60 seconds.",
             "passive_key":"marked","mult":1.5},
        ]
    },
    "assassin": {
        "name":"Assassin","primary_stat":"AGI","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"Executioner of the weak. Low HP targets never survive.",
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
        "name":"Blade Master","primary_stat":"AGI","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"A storm of blades. Every attack has a chance to hit twice.",
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
        "name":"Specialist","primary_stat":"AGI","line":"thief","path":"B",
        "weapon_types":["throwing_star"],
        "armor_type":"thief_armor",
        "desc":"The professional. Every debuff lingers, every kill profits.",
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
        "name":"Archer","primary_stat":"AGI","line":"archer",
        "weapon_types":["bow","crossbow"],
        "armor_type":"archer_armor",
        "desc":"Precise and deadly at range. Never miss a shot that matters.",
        "stat_bonus":{"AGI":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Eagle Eye",
             "passive":"Never miss when your AGI is higher than target DEF.",
             "active":"Aimed Shot","type":"pierce_dodge",
             "desc":"140% damage. Ignores dodge completely.",
             "passive_key":"eagle_eye","mult":1.4},
        ]
    },
    "scout": {
        "name":"Scout","primary_stat":"AGI","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Intelligence and disruption. Control the battlefield.",
        "stat_bonus":{"AGI":2,"INT":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Trailblazer",
             "passive":"First attack each day deals double damage.",
             "active":"Distract","type":"miss_debuff",
             "desc":"Target has 30% increased miss chance for 3 minutes.",
             "passive_key":"trailblazer"},
        ]
    },
    "ranger": {
        "name":"Ranger","primary_stat":"AGI","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Nature's guardian. Reduced damage, locked-down enemies.",
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
        "name":"Warden","primary_stat":"AGI","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Protector of allies. Intercepts hits, rains arrows on crowds.",
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
        "name":"Strider","primary_stat":"AGI","line":"archer","path":"A",
        "weapon_types":["bow"],
        "armor_type":"archer_armor",
        "desc":"Unstoppable pathfinder. No root can hold you. Retribution is swift.",
        "stat_bonus":{"AGI":5,"DEF":3},
        "skills":[
            {"tier":5,"unlock":100,"name":"Pathfinder",
             "passive":"Cannot be rooted, frozen or stunned by any skill ever.",
             "active":"Storm of Arrows","type":"aoe_recent_attackers",
             "desc":"AGI x8 split across all players who attacked you in last 30 minutes.",
             "passive_key":"pathfinder"},
        ]
    },
    "bounty_hunter": {
        "name":"Bounty Hunter","primary_stat":"AGI","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"Every target has a price. You always collect.",
        "stat_bonus":{"AGI":2,"STR":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Marked for Death",
             "passive":"Targets you defeat drop +25% more gold. You earn their unclaimed daily EXP on kill.",
             "active":"Execution Order","type":"bounty",
             "desc":"Place a bounty on any player. First to defeat them gets 500 gold. You get 250 gold regardless.",
             "passive_key":"marked_for_death"},
        ]
    },
    "sharpshooter": {
        "name":"Sharpshooter","primary_stat":"AGI","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"Consistency is power. Every hit builds toward devastation.",
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
        "name":"Sniper","primary_stat":"AGI","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"One shot, one kill. Crits hit harder than anyone else.",
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
        "name":"Deadeye","primary_stat":"AGI","line":"archer","path":"B",
        "weapon_types":["crossbow"],
        "armor_type":"archer_armor",
        "desc":"The final form. Every kill makes you deadlier forever.",
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
        "desc":"Healer and protector. The backbone of any group.",
        "stat_bonus":{"WIS":2},
        "skills":[
            {"tier":1,"unlock":5,"name":"Mending Aura",
             "passive":"All heals you cast are 25% more effective.",
             "active":"Holy Light","type":"revive_heal",
             "desc":"Heal target for WIS x5 HP. Works on defeated players — revives them.",
             "passive_key":"mending_aura"},
        ]
    },
    "cleric": {
        "name":"Cleric","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"Devoted healer. Every heal bounces back to you.",
        "stat_bonus":{"WIS":3},
        "skills":[
            {"tier":2,"unlock":10,"name":"Divine Grace",
             "passive":"Every time you heal someone you restore 10% of your own HP.",
             "active":"Blessing","type":"dmg_reduction_buff",
             "desc":"Grant target 1 hour of damage reduction (15% less damage taken).",
             "passive_key":"divine_grace"},
        ]
    },
    "bishop": {
        "name":"Bishop","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"Sacred ground follows your healing. Group protection is your gift.",
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
        "desc":"Death cannot claim you. Miracles are real.",
        "stat_bonus":{"WIS":5,"DEF":1},
        "skills":[
            {"tier":4,"unlock":60,"name":"Resurrection",
             "passive":"Once per day if you reach 0 HP you automatically revive at 30% HP.",
             "active":"Miracle","type":"full_revive",
             "desc":"Fully restore target to max HP. Grant 2 hours invincibility. Costs one Holy Relic.",
             "passive_key":"resurrection"},
        ]
    },
    "saint": {
        "name":"Saint","primary_stat":"WIS","line":"priest","path":"A",
        "weapon_types":["rosary"],
        "armor_type":"priest_armor",
        "desc":"A living blessing. Your presence alone uplifts the faithful.",
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
        "desc":"Dark sense and holy wrath. You see what others cannot.",
        "stat_bonus":{"WIS":2,"INT":1},
        "skills":[
            {"tier":2,"unlock":10,"name":"Dark Sense",
             "passive":"Can see all active debuffs on any player via /stats.",
             "active":"Smite","type":"holy_dmg",
             "desc":"WIS x3 holy damage. Deals double against players who have recently defeated others.",
             "passive_key":"dark_sense"},
        ]
    },
    "exorcist": {
        "name":"Exorcist","primary_stat":"WIS","line":"priest","path":"B",
        "weapon_types":["cross"],
        "armor_type":"priest_armor",
        "desc":"Purge the wicked. Strip their power and punish their sins.",
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
        "desc":"Justice is your shield. Attackers are punished. Targets are judged.",
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
        "desc":"Holy wrath without mercy. The righteous cannot be brought back.",
        "stat_bonus":{"WIS":6,"INT":2},
        "skills":[
            {"tier":5,"unlock":100,"name":"Wrath of the Righteous",
             "passive":"Every debuff you apply deals WIS x0.5 damage per minute until it expires.",
             "active":"Holy Wrath","type":"condemn",
             "desc":"WIS x8 damage. Strip all buffs. Apply all known debuffs simultaneously. On kill: target CANNOT be revived for 2 hours. Only Saint's Absolution can counter this.",
             "passive_key":"wrath_of_the_righteous"},
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
}
BASE_CLASSES = ["warrior","mage","thief","archer","priest"]

# Priest classes that can revive for free
HEALER_CLASSES = {"priest","cleric","bishop","high_priest","saint"}

# ── TITLES ────────────────────────────────────────────────────────────────────
TITLES = {
    "The Newcomer":    {"type":"level","threshold":1},
    "Rising Star":     {"type":"level","threshold":3},
    "Veteran":         {"type":"level","threshold":7},
    "Pocket King":     {"type":"level","threshold":10},
    "Legend":          {"type":"level","threshold":15},
    "The Immortal":    {"type":"level","threshold":20},
    "The Ascended":    {"type":"prestige","threshold":1},
    "The Relentless":  {"type":"wins","threshold":10},
    "The Undefeated":  {"type":"wins","threshold":25},
    "The Executioner": {"type":"wins","threshold":5},
    "Shadow":          {"type":"dodges","threshold":5},
    "The Wanderer":    {"type":"quests","threshold":20},
    "Dungeon Crawler": {"type":"quests","threshold":10},
    "Loot Goblin":     {"type":"quests","threshold":5},
    "The Healer":      {"type":"heals","threshold":5},
    "Guardian":        {"type":"heals","threshold":10},
    "One Ball Slayer": {"type":"special","threshold":0},
    "Three Ball Slayer":{"type":"special","threshold":0},
    "Five Ball Slayer":{"type":"special","threshold":0},
    "Seven Ball Slayer":{"type":"special","threshold":0},
    "8Ball Champion":  {"type":"special","threshold":0},
    "Void Slayer":     {"type":"special","threshold":0},
    "Pathfinder":      {"type":"special","threshold":0},
    "The Seer":        {"type":"special","threshold":0},
    "The Chosen One":  {"type":"special","threshold":0},
    "Guild Founder":   {"type":"special","threshold":0},
    "Raid Leader":     {"type":"special","threshold":0},
    "Alchemist":       {"type":"crafts","threshold":5},
    "Master Smith":    {"type":"crafts","threshold":10},
    "Artisan":         {"type":"crafts","threshold":20},
    "Century":         {"type":"level","threshold":100},
}

# ── GEAR SYSTEM ───────────────────────────────────────────────────────────────
WEAPONS = {
    # ── WARRIOR ──────────────────────────────────────────────────────────────
    "Broken Longsword":        {"class":"warrior","type":"sword_1h","atk":3, "rarity":"common"},
    "Militia Falchion":        {"class":"warrior","type":"sword_1h","atk":7, "rarity":"uncommon"},
    "Blacksteel Bastard Sword":{"class":"warrior","type":"sword_1h","atk":14,"rarity":"rare"},
    "Giantslayer Zweihander":  {"class":"warrior","type":"sword_2h","atk":24,"rarity":"epic"},
    "Worldcleaver":            {"class":"warrior","type":"sword_2h","atk":40,"rarity":"legendary"},
    # ── MAGE ─────────────────────────────────────────────────────────────────
    "Oak Practice Staff":      {"class":"mage","type":"wand","atk":2, "rarity":"common"},
    "Petrified Willow Wand":   {"class":"mage","type":"wand","atk":8, "rarity":"uncommon"},
    "Cursed Ebony Staff":      {"class":"mage","type":"staff","atk":15,"rarity":"rare"},
    "Astral Conduit Rod":      {"class":"mage","type":"staff","atk":26,"rarity":"epic"},
    "Nullstar Scepter":        {"class":"mage","type":"wand","atk":42,"rarity":"legendary"},
    # ── ARCHER ────────────────────────────────────────────────────────────────
    "Makeshift Shortbow":      {"class":"archer","type":"bow","atk":3, "rarity":"common"},
    "Goat Horn Crossbow":      {"class":"archer","type":"crossbow","atk":7,"rarity":"uncommon"},
    "Falconwing Recurve Bow":  {"class":"archer","type":"bow","atk":13,"rarity":"rare"},
    "Windripper Greatbow":     {"class":"archer","type":"bow","atk":23,"rarity":"epic"},
    "Heaven's Tear Ballista":  {"class":"archer","type":"crossbow","atk":38,"rarity":"legendary"},
    # ── THIEF ─────────────────────────────────────────────────────────────────
    "Rusty Shiv":              {"class":"thief","type":"dagger","atk":4, "rarity":"common"},
    "Serrated Kujang":         {"class":"thief","type":"dagger","atk":9, "rarity":"uncommon"},
    "Venomspike Blowgun":      {"class":"thief","type":"throwing_star","atk":14,"rarity":"rare"},
    "Shadowstitch Katars":     {"class":"thief","type":"throwing_star","atk":25,"rarity":"epic"},
    "Umbral Chain Sickle":     {"class":"thief","type":"dagger","atk":44,"rarity":"legendary"},
    # ── PRIEST ────────────────────────────────────────────────────────────────
    "Wooden Prayer Beads":     {"class":"priest","type":"rosary","atk":2, "rarity":"common"},
    "Iron Rosary":             {"class":"priest","type":"rosary","atk":6, "rarity":"uncommon"},
    "Sun Disc Pendant":        {"class":"priest","type":"cross","atk":12,"rarity":"rare"},
    "Martyr's Thorned Cross":  {"class":"priest","type":"cross","atk":22,"rarity":"epic"},
    "Sanctus Aeterna":         {"class":"priest","type":"cross","atk":36,"rarity":"legendary"},
}

ARMORS = {
    "Padded Tunic":            {"class":"warrior","def":4, "rarity":"common"},
    "Iron Scale Vest":         {"class":"warrior","def":11,"rarity":"uncommon"},
    "Crimson Plackart":        {"class":"warrior","def":22,"rarity":"rare"},
    "Onyx Golem Plate":        {"class":"warrior","def":34,"rarity":"epic"},
    "Titanfoil Carapace":      {"class":"warrior","def":50,"rarity":"legendary"},
    "Frayed Spellcloak":       {"class":"mage","def":3,  "rarity":"common"},
    "Windwoven Silk Robe":     {"class":"mage","def":9,  "rarity":"uncommon"},
    "Arctic Fox Stole":        {"class":"mage","def":18, "rarity":"rare"},
    "Voidweave Mantle":        {"class":"mage","def":28, "rarity":"epic"},
    "Singularity Robe":        {"class":"mage","def":44, "rarity":"legendary"},
    "Sturdy Leather Jerkin":   {"class":"archer","def":4, "rarity":"common"},
    "Hardened Hide Cuirass":   {"class":"archer","def":10,"rarity":"uncommon"},
    "Griffon Plate Chest":     {"class":"archer","def":20,"rarity":"rare"},
    "Phoenix Down Brigandine": {"class":"archer","def":31,"rarity":"epic"},
    "Skybreaker Scale Armor":  {"class":"archer","def":47,"rarity":"legendary"},
    "Dark Hooded Wrap":        {"class":"thief","def":3,  "rarity":"common"},
    "Oilskin Shadow Coat":     {"class":"thief","def":10, "rarity":"uncommon"},
    "Stalker's Mesh Shroud":   {"class":"thief","def":19, "rarity":"rare"},
    "Nocturnal Leather Harness":{"class":"thief","def":30,"rarity":"epic"},
    "Abyssal Cloak of Silence":{"class":"thief","def":48, "rarity":"legendary"},
    "Woven Vestments":         {"class":"priest","def":3, "rarity":"common"},
    "Embroidered Cassock":     {"class":"priest","def":8, "rarity":"uncommon"},
    "Silver Mitre Hood":       {"class":"priest","def":17,"rarity":"rare"},
    "Lightweaver Chasuble":    {"class":"priest","def":27,"rarity":"epic"},
    "Seraph's Surplice":       {"class":"priest","def":42,"rarity":"legendary"},
}

SHIELDS = {
    "Splintered Buckler":      {"class":"warrior","path":"A","def":3, "rarity":"common"},
    "Ironbound Targe":         {"class":"warrior","path":"A","def":8, "rarity":"uncommon"},
    "Kite Shield of the Vow":  {"class":"warrior","path":"A","def":16,"rarity":"rare"},
    "Obsidian Tower Shield":   {"class":"warrior","path":"A","def":26,"rarity":"epic"},
    "Aegis of First Light":    {"class":"warrior","path":"A","def":40,"rarity":"legendary"},
}

ACCESSORIES = {
    # Common
    "Pebble of Focus":         {"slot":"ring","effect":{"atk":2},"rarity":"common",
                                "desc":"Slightly sharpens your focus."},
    "Frayed Rope Band":        {"slot":"ring","effect":{"hp":10},"rarity":"common",
                                "desc":"+10 max HP."},
    "Copper Loop":             {"slot":"ring","effect":{"any_stat":3},"rarity":"common",
                                "desc":"+3 to one stat of your choice on equip."},
    "Tin Charm":               {"slot":"amulet","effect":{"hp":5},"rarity":"common",
                                "desc":"+5 max HP."},
    "Traveler's Token":        {"slot":"amulet","effect":{"all_stats":2},"rarity":"common",
                                "desc":"+2 to all stats."},
    # Uncommon
    "Fox Tail Ring":           {"slot":"ring","effect":{"AGI":6},"rarity":"uncommon",
                                "desc":"+6 AGI."},
    "Brass Holy Symbol":       {"slot":"ring","effect":{"WIS":6},"rarity":"uncommon",
                                "desc":"+6 WIS."},
    "Chipped Onyx Stud":       {"slot":"ring","effect":{"any_stat":6},"rarity":"uncommon",
                                "desc":"+6 STR or +6 INT (choose on equip)."},
    "Bloodstone Band":         {"slot":"ring","effect":{"hp":8,"STR":3},"rarity":"uncommon",
                                "desc":"+8 HP, +3 STR."},
    "Mercenary's Signet":      {"slot":"ring","effect":{"atk":4,"gold_bonus":0.05},"rarity":"uncommon",
                                "desc":"+4 ATK, +5% gold drops."},
    "Brass Holy Symbol":       {"slot":"amulet","effect":{"WIS":6},"rarity":"uncommon",
                                "desc":"+6 WIS."},
    "Hunter's Fang Pendant":   {"slot":"amulet","effect":{"STR":6,"AGI":3},"rarity":"uncommon",
                                "desc":"+6 STR, +3 AGI."},
    "Mana Bead Necklace":      {"slot":"amulet","effect":{"INT":8},"rarity":"uncommon",
                                "desc":"+8 INT."},
    # Rare
    "Whisper Coin":            {"slot":"ring","effect":{"AGI":12,"crit_bonus":0.08},"rarity":"rare",
                                "desc":"+12 AGI, +8% crit damage."},
    "Warmaster's Clasp":       {"slot":"ring","effect":{"STR":12,"DEF":8},"rarity":"rare",
                                "desc":"+12 STR, +8 DEF."},
    "Owl Medallion":           {"slot":"ring","effect":{"INT":12,"WIS":8},"rarity":"rare",
                                "desc":"+12 INT, +8 WIS."},
    "Phantom Loop":            {"slot":"ring","effect":{"AGI":10,"dodge_bonus":0.10},"rarity":"rare",
                                "desc":"+10 AGI, +10% dodge chance."},
    "Executioner's Band":      {"slot":"ring","effect":{"STR":10,"lifesteal_flat":5},"rarity":"rare",
                                "desc":"+10 STR. Kills restore 5 HP."},
    "Spellweaver's Coil":      {"slot":"ring","effect":{"INT":14},"rarity":"rare",
                                "desc":"+14 INT."},
    "Ironheart Medallion":     {"slot":"amulet","effect":{"DEF":15,"hp":20},"rarity":"rare",
                                "desc":"+15 DEF, +20 HP."},
    "Vampiric Fang Chain":     {"slot":"amulet","effect":{"STR":10,"lifesteal_flat":5},"rarity":"rare",
                                "desc":"+10 STR. +5 HP per hit landed."},
    "Wanderer's Compass":      {"slot":"amulet","effect":{"all_stats":10,"explore_bonus":0.10},"rarity":"rare",
                                "desc":"+10 to all stats, +10% explore rewards."},
    "Stormcaller's Torc":      {"slot":"amulet","effect":{"AGI":10,"INT":10},"rarity":"rare",
                                "desc":"+10 AGI, +10 INT."},
    # Epic
    "Twin Serpent Ring":       {"slot":"ring","effect":{"atk":20,"DEF":15},"rarity":"epic",
                                "desc":"+20 ATK, +15 DEF."},
    "Eye of the Storm":        {"slot":"ring","effect":{"AGI":18,"dodge_bonus":0.12},"rarity":"epic",
                                "desc":"+18 AGI, +12% dodge."},
    "Void-Touched Circle":     {"slot":"ring","effect":{"INT":22,"reflect_pct":0.10},"rarity":"epic",
                                "desc":"+22 INT, 10% reflect damage."},
    "Berserker's Knuckle":     {"slot":"ring","effect":{"STR":20,"low_hp_dmg_bonus":0.10},"rarity":"epic",
                                "desc":"+20 STR, +10% damage when below 30% HP."},
    "Saint's Halo Band":       {"slot":"ring","effect":{"WIS":20,"heal_bonus":0.30},"rarity":"epic",
                                "desc":"+20 WIS, heals are 30% more effective."},
    "Cinder Heart Pendant":    {"slot":"amulet","effect":{"hp":25,"all_stats":15},"rarity":"epic",
                                "desc":"+25 HP, +15 to all stats."},
    "Deathwhisper Amulet":     {"slot":"amulet","effect":{"AGI":20,"crit_bonus":0.15},"rarity":"epic",
                                "desc":"+20 AGI, +15% crit chance."},
    "Aegis Talisman":          {"slot":"amulet","effect":{"DEF":25,"block_chance":0.10},"rarity":"epic",
                                "desc":"+25 DEF, 10% chance to block any incoming hit."},
    "Luminous Crucifix":       {"slot":"amulet","effect":{"WIS":20,"revive_heal_bonus":0.20},"rarity":"epic",
                                "desc":"+20 WIS, revive heals 20% more HP."},
    "Dragon Soul Pendant":     {"slot":"amulet","effect":{"STR":22,"INT":22},"rarity":"epic",
                                "desc":"+22 STR, +22 INT."},
    # Legendary
    "Godshard Splinter":       {"slot":"ring","effect":{"atk":35,"DEF":35},"rarity":"legendary",
                                "desc":"+35 ATK, +35 DEF."},
    "Infinity Loop":           {"slot":"ring","effect":{"all_stats":30,"hp":50},"rarity":"legendary",
                                "desc":"+30 to all stats, +50 HP."},
    "Ring of the Ancients":    {"slot":"ring","effect":{"primary_stat":40},"rarity":"legendary",
                                "desc":"+40 to your primary class stat."},
    "Ouroboros":               {"slot":"ring","effect":{"all_stats":25,"dodge_bonus":0.05},"rarity":"legendary",
                                "desc":"+25 all stats, 5% chance to dodge any attack."},
    "Last Breath Locket":      {"slot":"amulet","effect":{"revive_once":True},"rarity":"legendary",
                                "desc":"Revive once per combat at 20% HP."},
    "Worldsoul Amulet":        {"slot":"amulet","effect":{"primary_stat":40,"hp":100},"rarity":"legendary",
                                "desc":"+40 to primary class stat, +100 HP."},
    "Shard of Divinity":       {"slot":"amulet","effect":{"WIS":35,"priest_aoe":True},"rarity":"legendary",
                                "desc":"+35 WIS, priest skills affect 2 targets at once."},
    "Mark of the Void":        {"slot":"amulet","effect":{"INT":35,"spell_double_chance":0.15},"rarity":"legendary",
                                "desc":"+35 INT, 15% chance spells hit twice."},
}

RARITY_EMOJI = {
    "common":"⚪","uncommon":"🟢","rare":"🔵","epic":"🟣","legendary":"🟡"
}

# Items that can be found in game
CONSUMABLES = {
    "Health Potion":       {"desc":"Restores 50 HP.","sell":75},
    "Super Health Potion": {"desc":"Restores 100 HP.","sell":200},
    "Mega Health Potion":  {"desc":"Restores 200 HP.","sell":450},
    "Revival Charm":       {"desc":"Revive a defeated player.","sell":750},
    "Holy Relic":          {"desc":"Required for Miracle (High Priest skill).","sell":1000},
    "Dragon Scale":        {"desc":"Crafting material. Rare drop.","sell":100},
    "Enchanting Scroll":   {"desc":"Used to enchant gear. Future system.","sell":150},
}

SHOP_POOL = [
    {"item":"Health Potion","price":150,"desc":"Restores 50 HP."},
    {"item":"Super Health Potion","price":400,"desc":"Restores 100 HP."},
    {"item":"Mega Health Potion","price":900,"desc":"Restores 200 HP."},
    {"item":"Revival Charm","price":1500,"desc":"Revive a defeated player."},
    {"item":"Dragon Scale","price":300,"desc":"Crafting material."},
    {"item":"Enchanting Scroll","price":500,"desc":"Enchant gear. Future use."},
]
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
    "1 ball": {"name":"The 1 Ball","hp":1200,"max_hp":1200,"dmg_min":45,"dmg_max":80,
               "exp":800,"gold":150,"title":"One Ball Slayer","desc":"The loneliest ball — now furious.",
               "loot_table":[("Super Health Potion","uncommon"),("Dragon Scale","uncommon"),("Iron Scale Vest","uncommon")]},
    "3 ball": {"name":"The 3 Ball","hp":2000,"max_hp":2000,"dmg_min":70,"dmg_max":110,
               "exp":1600,"gold":300,"title":"Three Ball Slayer","desc":"A red wrecking ball.",
               "loot_table":[("Mega Health Potion","rare"),("Dragon Scale","uncommon"),("Falconwing Recurve Bow","rare")]},
    "5 ball": {"name":"The 5 Ball","hp":3000,"max_hp":3000,"dmg_min":95,"dmg_max":140,
               "exp":2500,"gold":500,"title":"Five Ball Slayer","desc":"Orange and merciless.",
               "loot_table":[("Revival Charm","rare"),("Cursed Ebony Staff","rare"),("Whisper Coin","rare")]},
    "7 ball": {"name":"The 7 Ball","hp":4500,"max_hp":4500,"dmg_min":120,"dmg_max":180,
               "exp":4000,"gold":800,"title":"Seven Ball Slayer","desc":"Maroon and relentless.",
               "loot_table":[("Giantslayer Zweihander","epic"),("Voidweave Mantle","epic"),("Twin Serpent Ring","epic")]},
    "8 ball": {"name":"The 8 Ball","hp":8000,"max_hp":8000,"dmg_min":150,"dmg_max":250,
               "exp":8000,"gold":2000,"title":"8Ball Champion","desc":"Black as the Corner Pocket itself.",
               "loot_table":[("Worldcleaver","legendary"),("Singularity Robe","legendary"),("Infinity Loop","legendary")]},
    "void":   {"name":"The Void Ball","hp":15000,"max_hp":15000,"dmg_min":250,"dmg_max":400,
               "exp":20000,"gold":5000,"title":"Void Slayer","desc":"A secret boss from beyond the table.","secret":True,
               "loot_table":[("Godshard Splinter","legendary"),("Last Breath Locket","legendary"),("Mark of the Void","legendary")]},
}

RAID_TIERS = [
    {"name":"The Felt Skirmish","min_level":1,"waves":2,"wave_boss_key":"1 ball",
     "wave_enemies":[{"name":"Rack Grunt","hp":150,"dmg_min":15,"dmg_max":30},
                     {"name":"Side Rail Mob","hp":250,"dmg_min":20,"dmg_max":40}],
     "exp_reward":600,"gold_reward":120,
     "loot_table":[("Health Potion","common"),("Dragon Scale","uncommon"),("Militia Falchion","uncommon")]},
    {"name":"The Corner Pocket Assault","min_level":5,"waves":3,"wave_boss_key":"3 ball",
     "wave_enemies":[{"name":"Chalk Golem","hp":400,"dmg_min":35,"dmg_max":60},
                     {"name":"Pocket Demon","hp":600,"dmg_min":45,"dmg_max":75},
                     {"name":"Rack Fiend","hp":800,"dmg_min":55,"dmg_max":90}],
     "exp_reward":1400,"gold_reward":300,
     "loot_table":[("Super Health Potion","uncommon"),("Blacksteel Bastard Sword","rare"),("Owl Medallion","rare")]},
    {"name":"The Break Line Siege","min_level":10,"waves":3,"wave_boss_key":"5 ball",
     "wave_enemies":[{"name":"Felt Wraith","hp":1000,"dmg_min":65,"dmg_max":100},
                     {"name":"Cue Specter","hp":1500,"dmg_min":85,"dmg_max":130},
                     {"name":"Break Titan","hp":2000,"dmg_min":100,"dmg_max":150}],
     "exp_reward":3000,"gold_reward":700,
     "loot_table":[("Revival Charm","rare"),("Astral Conduit Rod","epic"),("Warmaster's Clasp","rare")]},
    {"name":"The Final Rack — Endgame","min_level":15,"waves":4,"wave_boss_key":"8 ball",
     "wave_enemies":[{"name":"Shadow Rack","hp":2500,"dmg_min":100,"dmg_max":160},
                     {"name":"Void Ball","hp":3500,"dmg_min":130,"dmg_max":200},
                     {"name":"8Ball Sentinel","hp":5000,"dmg_min":150,"dmg_max":230},
                     {"name":"Doom Cluster","hp":6000,"dmg_min":180,"dmg_max":260}],
     "exp_reward":8000,"gold_reward":2000,
     "loot_table":[("Worldcleaver","legendary"),("Nullstar Scepter","legendary"),("Godshard Splinter","legendary")]},
]

EXPLORE_ZONES = [
    {"name":"The Forgotten Crossroads","tier":"Easy","exp":500,"gold":50,
     "loot_table":[("Health Potion",0.15),("Rusty Shiv",0.10),("Wooden Prayer Beads",0.10),
                   ("Pebble of Focus",0.08),("Frayed Rope Band",0.08)],
     "fail_msg":"The road was longer than expected. You return empty-handed."},
    {"name":"The Bandit Caves","tier":"Medium","exp":900,"gold":100,
     "loot_table":[("Super Health Potion",0.10),("Serrated Kujang",0.08),("Militia Falchion",0.08),
                   ("Fox Tail Ring",0.06),("Bloodstone Band",0.05)],
     "fail_msg":"The bandits were too many. You barely escaped."},
    {"name":"The Ancient Ruins","tier":"Hard","exp":1500,"gold":200,
     "loot_table":[("Mega Health Potion",0.05),("Revival Charm",0.03),("Dragon Scale",0.15),
                   ("Whisper Coin",0.05),("Ironheart Medallion",0.05),("Blacksteel Bastard Sword",0.04)],
     "fail_msg":"The ruins shifted and swallowed the path. You find nothing."},
    {"name":"The Dragon's Lair","tier":"Elite","exp":2500,"gold":400,
     "loot_table":[("Dragon Scale",0.30),("Enchanting Scroll",0.15),
                   ("Giantslayer Zweihander",0.03),("Astral Conduit Rod",0.03),
                   ("Twin Serpent Ring",0.03),("Cinder Heart Pendant",0.03)],
     "fail_msg":"The dragon was awake. You fled with your life."},
    {"name":"The Void Rift","tier":"Legendary","exp":5000,"gold":800,
     "loot_table":[("Worldcleaver",0.01),("Nullstar Scepter",0.01),("Godshard Splinter",0.01),
                   ("Last Breath Locket",0.01),("Mark of the Void",0.01),
                   ("Dragon Scale",0.20),("Enchanting Scroll",0.20)],
     "fail_msg":"The void rejected you. You wake up back at camp, shaken."},
]

SOLO_QUESTS = [
    {"tier":"Easy","text":"You helped a merchant fend off a pack of wolves.","exp":30,"gold":5,
     "loot_table":[("Health Potion",0.05),("Rusty Shiv",0.03),("Wooden Prayer Beads",0.03)]},
    {"tier":"Easy","text":"You ran a message across town before dawn.","exp":25,"gold":8,
     "loot_table":[("Pebble of Focus",0.05),("Tin Charm",0.05)]},
    {"tier":"Easy","text":"You cleared rats from a tavern basement.","exp":20,"gold":10,
     "loot_table":[("Health Potion",0.05),("Copper Loop",0.04)]},
    {"tier":"Easy","text":"You escorted a child back to their village.","exp":35,"gold":5,
     "loot_table":[("Frayed Rope Band",0.05),("Traveler's Token",0.04)]},
    {"tier":"Easy","text":"You dug up an old cache for a dying soldier.","exp":28,"gold":7,
     "loot_table":[("Health Potion",0.06),("Rusty Shiv",0.03)]},
    {"tier":"Medium","text":"You survived a night in the mercenary camp.","exp":55,"gold":20,
     "loot_table":[("Super Health Potion",0.03),("Militia Falchion",0.04),("Fox Tail Ring",0.03)]},
    {"tier":"Medium","text":"You tracked a thief through the city sewers.","exp":60,"gold":25,
     "loot_table":[("Serrated Kujang",0.04),("Bloodstone Band",0.03),("Chipped Onyx Stud",0.03)]},
    {"tier":"Medium","text":"You defeated the local dueling champion.","exp":65,"gold":30,
     "loot_table":[("Dragon Scale",0.05),("Mercenary's Signet",0.03),("Hunter's Fang Pendant",0.03)]},
    {"tier":"Medium","text":"You cleared a dungeon room single-handedly.","exp":70,"gold":25,
     "loot_table":[("Goat Horn Crossbow",0.04),("Petrified Willow Wand",0.04),("Iron Rosary",0.04)]},
    {"tier":"Hard","text":"You slew a beast terrorizing the outer villages.","exp":80,"gold":50,
     "loot_table":[("Dragon Scale",0.10),("Mega Health Potion",0.01),("Revival Charm",0.01),
                   ("Venomspike Blowgun",0.02),("Cursed Ebony Staff",0.02)]},
    {"tier":"Hard","text":"You raided a fortified dungeon beneath the cliffs.","exp":75,"gold":60,
     "loot_table":[("Dragon Scale",0.10),("Enchanting Scroll",0.05),
                   ("Warmaster's Clasp",0.02),("Owl Medallion",0.02)]},
    {"tier":"Hard","text":"You defeated a demonic commander in single combat.","exp":80,"gold":55,
     "loot_table":[("Dragon Scale",0.12),("Enchanting Scroll",0.05),
                   ("Falconwing Recurve Bow",0.02),("Blacksteel Bastard Sword",0.02)]},
]

RANDOM_EVENTS = [
    {"key":"traveler","freq":"common",
     "msg":"🧙 *A Mysterious Traveler appears!*\nFirst to /greet gets +300 EXP and a random item!",
     "exp":300,"loot_table":[("Health Potion",0.40),("Dragon Scale",0.20),("Pebble of Focus",0.20),("Tin Charm",0.20)]},
    {"key":"bandit","freq":"common",
     "msg":"🗡️ *Bandit Ambush!* A bandit (150 HP) attacks!\nUse /fight to strike. Defeat for +250 EXP!",
     "enemy_hp":150,"exp_reward":250,
     "loot_table":[("Health Potion",0.30),("Rusty Shiv",0.15),("Copper Loop",0.10)]},
    {"key":"ghost","freq":"common",
     "msg":"👻 *A Restless Spirit appears!* (200 HP)\nUse /shoot to banish it. Reward: +300 EXP!",
     "enemy_hp":200,"exp_reward":300,
     "loot_table":[("Super Health Potion",0.20),("Frayed Rope Band",0.15)]},
    {"key":"merchant","freq":"uncommon",
     "msg":"🛍️ *A Wandering Merchant sets up shop!*\n/greet them for a 20% shop discount for 30 minutes!",
     "discount":0.20,"duration_min":30},
    {"key":"rival","freq":"uncommon",
     "msg":"⚔️ *A Rival Adventurer challenges someone!*\nFirst to /fight claims the duel! Winner gets bonus EXP and gold."},
    {"key":"drake","freq":"uncommon",
     "msg":"🐉 *A Wild Drake appears!* (500 HP)\nReply to this message with /strike to attack!\nRewards split by damage dealt!",
     "enemy_hp":500,"exp_reward":1000,
     "loot_table":[("Dragon Scale",0.50),("Enchanting Scroll",0.20),("Revival Charm",0.10)]},
    {"key":"cache","freq":"uncommon",
     "msg":"💰 *An Abandoned Cache was discovered!*\nFirst to /claim it gets the reward!",
     "loot_table":[("Dragon Scale",0.30),("Super Health Potion",0.30),("Fox Tail Ring",0.20),("Mana Bead Necklace",0.20)]},
    {"key":"storm","freq":"uncommon",
     "msg":"🌩️ *A Storm rolls in!* Weather changes immediately — EXP and DMG modifiers shift!"},
    {"key":"legendary_merchant","freq":"rare",
     "msg":"👑 *A Legendary Merchant appears for 10 minutes!*\nUse /shop legend to browse rare and epic gear!","duration_min":10},
    {"key":"shrine","freq":"rare",
     "msg":"🔮 *An Ancient Shrine has been uncovered!*\nFirst to /pray receives a random stat boost for 2 hours!"},
    {"key":"cursed","freq":"rare",
     "msg":"⚰️ *A Cursed Wanderer passes through!*\nA random player has been cursed — they lose 10% EXP per hour until another player uses /purge on them!"},
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

def set_status(p, key, duration_seconds):
    p[key] = (datetime.now() + timedelta(seconds=duration_seconds)).isoformat()

def get_active_statuses(p):
    statuses = []
    if is_distracted(p):      statuses.append("😵 Distracted (30% miss)")
    if is_entangled(p):       statuses.append("🌿 Entangled (can't attack)")
    if is_frozen(p):          statuses.append("🧊 Frozen (can't attack)")
    if is_stunned(p):         statuses.append("⚡ Stunned (miss next attack)")
    if is_vanished(p):        statuses.append("👻 Vanished (untargetable)")
    if is_bleeding(p):        statuses.append(f"🩸 Bleeding ({p.get('bleed_damage',10)} dmg/30s)")
    if is_hexed(p):           statuses.append("💀 Hexed (-25% damage)")
    if is_blessed(p):         statuses.append("✨ Blessed (+10% all stats)")
    if is_weakened(p):        statuses.append("💔 Weakened (+25% dmg taken)")
    if is_healing_blocked(p): statuses.append("🚫 Healing Blocked")
    if is_revival_blocked(p): statuses.append("☠️ Revival Blocked (Zealot)")
    if is_silenced(p):        statuses.append("🤐 Silenced (no skills)")
    if is_invincible(p):      statuses.append("🛡️ Invincible (Still Recovering)")
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

def get_weapon_atk(p):
    w = get_equipped_weapon(p)
    return w["atk"] if w else 0

def get_armor_def(p):
    a = get_equipped_armor(p)
    s = get_equipped_shield(p)
    return (a["def"] if a else 0) + (s["def"] if s else 0)

def get_accessory_bonus(p, stat):
    acc = get_equipped_accessory(p)
    if not acc: return 0
    effect = acc.get("effect", {})
    if stat in effect: return effect[stat]
    if stat == "all_stats" and "all_stats" in effect: return effect["all_stats"]
    return 0

def can_equip_weapon(p, weapon_name):
    w = WEAPONS.get(weapon_name)
    if not w: return False, "Unknown weapon."
    cls = get_player_class_id(p)
    cls_data = CLASS_TREE.get(cls, {})
    base_line = cls_data.get("line")
    weapon_class = w.get("class")
    if weapon_class != base_line:
        return False, f"Only {weapon_class.capitalize()} classes can use this."
    weapon_type = w.get("type")
    allowed = cls_data.get("weapon_types", [])
    if weapon_type not in allowed:
        return False, f"Your current class path cannot use {weapon_type} weapons."
    return True, ""

def can_equip_armor(p, armor_name):
    a = ARMORS.get(armor_name)
    if not a: return False, "Unknown armor."
    cls = get_player_class_id(p)
    cls_data = CLASS_TREE.get(cls, {})
    armor_type = cls_data.get("armor_type")
    if a.get("class") and a["class"] != cls_data.get("line"):
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
    base  = safe_stats(p).get(stat, 5)
    acc   = get_accessory_bonus(p, stat)
    all_s = get_accessory_bonus(p, "all_stats")
    blessed_bonus = 1 if is_blessed(p) else 0  # flat +1 per stat when blessed (simplified)
    return base + acc + all_s + blessed_bonus

def calc_max_hp(p):
    base  = max_hp_for_level(p["level"])
    acc_hp = get_accessory_bonus(p, "hp")
    temp   = safe_int(p.get("temp_hp_bonus")) if _ts_active(p, "temp_hp_until") else 0
    return base + acc_hp + temp

def calc_attack_damage(attacker, weather=None):
    base      = random.randint(1, 10)
    weapon    = get_weapon_atk(attacker)
    perm      = safe_int(attacker.get("perm_dmg_bonus"))
    acc_atk   = get_accessory_bonus(attacker, "atk")
    stats     = safe_stats(attacker)
    primary   = get_primary_stat(attacker)
    stat_val  = get_stat(attacker, primary)
    stat_bonus = stat_val // 2
    level_bonus = attacker["level"] // 2

    raw = base + weapon + perm + acc_atk + stat_bonus + level_bonus

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

    # Accessory block chance (handled separately, this is just flat reduction)
    if get_accessory_bonus(defender, "block_chance"):
        if random.random() < get_accessory_bonus(defender, "block_chance"):
            return 0  # blocked entirely

    total = min(0.80, def_reduction + armor_reduction)
    return max(1, round(dmg * (1 - total)))

def check_miss(attacker, defender):
    """Returns True if attack misses."""
    if is_invincible(defender):  return True
    if is_vanished(defender):    return True
    if cannot_attack(attacker):  return True

    # Base dodge from AGI
    agi = get_stat(defender, "AGI")
    dodge = min(0.40, agi * 0.008)

    # Accessory dodge bonus
    dodge += get_accessory_bonus(defender, "dodge_bonus")

    # Class passives
    cls_d = get_player_class(defender)
    if cls_d:
        pk = cls_d.get("passive_key","")
        if pk == "evasion":       dodge += 0.15
        if pk == "ghost_form":    dodge += 0.20
        if pk == "void_rift":     dodge += 0.25
        if pk == "quick_hands":   dodge += get_stat(defender, "AGI") * 0.005

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
    agi = get_stat(attacker, "AGI")
    base_crit = min(0.45, agi * 0.008)
    base_crit += get_accessory_bonus(attacker, "crit_bonus")
    cls = get_player_class(attacker)
    if cls and cls.get("passive_key") == "quick_hands":
        base_crit += 0.15
    return random.random() < base_crit

def apply_crit(attacker, dmg):
    cls = get_player_class(attacker)
    mult = 2.0
    if cls and cls.get("passive_key") == "headshot":
        mult = 3.0
    return round(dmg * mult)

def apply_lifesteal(attacker, dmg):
    cls = get_player_class(attacker)
    if not cls: return 0
    pk = cls.get("passive_key","")
    healed = 0
    if pk == "soul_pact":
        healed = round(dmg * 0.20)
    if pk == "bloodlust":
        healed = 5
    if get_accessory_bonus(attacker, "lifesteal_flat"):
        healed += get_accessory_bonus(attacker, "lifesteal_flat")
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
    if get_accessory_bonus(defender, "reflect_pct"):
        reflect += round(dmg * get_accessory_bonus(defender, "reflect_pct"))
    if reflect:
        attacker["hp"] = max(0, attacker["hp"] - reflect)
    return reflect

def check_bleed_tick(p):
    """Called in handle_message — tick bleed damage."""
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
        titles TEXT DEFAULT '["The Newcomer"]',
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
    conn.close()

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
         passive_cooldowns,ascended,last_seen)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (s["user_id"],s["username"],s["level"],s["exp"],
         safe_int(s.get("total_exp")),s.get("message_count",0),
         s.get("passive_cooldowns","{}"),s.get("ascended",0),
         datetime.now().isoformat()))
    conn.commit(); conn.close()

def save_player(p):
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
        "guild_id","prestige_count","shadow_level_at_ascension","created_at"
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
        msgs.append(f"🏰 Guild leveled up to {g['level']}! "
                    f"{GUILD_PERKS.get(g['level'],{}).get('desc','')}")
    return msgs

def new_player(s):
    """Create a new RPG player from shadow profile."""
    slvl = s["level"]
    p = {
        "user_id": s["user_id"], "username": s["username"],
        "hp": max_hp_for_level(slvl), "max_hp": max_hp_for_level(slvl),
        "exp": 0, "level": slvl, "total_exp": safe_int(s.get("total_exp")),
        "gold": slvl * 10, "wins": 0, "losses": 0,
        "quests_done": 0, "heals_given": 0, "dodges": 0,
        "crafts_done": 0, "perm_dmg_bonus": 0,
        "titles": json.dumps(["The Newcomer"]),
        "active_title": "The Newcomer",
        "class_id": None, "class_path": None,
        "all_skills": json.dumps([]),
        "stat_points": slvl * 3 + slvl // 5,
        "stats": json.dumps(DEFAULT_STATS.copy()),
        "inventory": json.dumps([]),
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
    }
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
        if   t == "level"    and p["level"]                        >= v: pass
        elif t == "wins"     and p["wins"]                         >= v: pass
        elif t == "quests"   and p["quests_done"]                  >= v: pass
        elif t == "heals"    and p["heals_given"]                  >= v: pass
        elif t == "dodges"   and p["dodges"]                       >= v: pass
        elif t == "crafts"   and safe_int(p.get("crafts_done"))    >= v: pass
        elif t == "prestige" and safe_int(p.get("prestige_count")) >= v: pass
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
    msgs = []; leveled_up = False
    p["exp"]      += max(0, amount)
    p["total_exp"] = safe_int(p.get("total_exp")) + max(0, amount)
    while p["level"] < 100 and p["exp"] >= exp_for_level(p["level"]):
        p["exp"] -= exp_for_level(p["level"])
        p["level"] += 1; leveled_up = True
        p["max_hp"]      = max_hp_for_level(p["level"])
        p["hp"]          = p["max_hp"]
        p["stat_points"] = safe_int(p.get("stat_points")) + 3
        msgs.append(f"⬆️ *LEVEL UP!* {p['username']} is now *Level {p['level']}*! +3 stat points.")
        if p["level"] == 5 and not p.get("class_id"):
            msgs.append("⚔️ You can now choose a class! Use /class.")
        if p["level"] == 10 and p.get("class_id") and not p.get("class_path"):
            msgs.append("🌟 Choose your path! Use /prestige.")
        if p["level"] == 30 and p.get("class_path"):
            _auto_advance_class(p, 30)
        if p["level"] == 60:
            _auto_advance_class(p, 60)
        if p["level"] == 100:
            _auto_advance_class(p, 100)
            msgs.append("🏆 *LEVEL 100!* You have reached the pinnacle!")
            award_title(p, "Century")
        for t in check_titles(p):
            msgs.append(f"🏅 New title: *{t}*!")
    return msgs, leveled_up

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

def roll_loot_table(loot_table):
    """Roll on a loot table and return item or None."""
    for item_name, chance in loot_table:
        if random.random() < chance:
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
def build_combat_card(target, attackers_info, finished=False):
    hp_bar_len = 10
    hp_pct = target["hp"] / max(1, target["max_hp"])
    filled  = round(hp_pct * hp_bar_len)
    bar     = "█" * filled + "░" * (hp_bar_len - filled)
    status  = "💀 DEFEATED" if target["hp"] <= 0 else f"❤️ {target['hp']}/{target['max_hp']}"
    header  = "⚔️ *OPEN PVP — FINISHED*" if finished else "⚔️ *OPEN PVP*"
    lines   = [
        header,
        "━━━━━━━━━━━━━━━━",
        f"🎯 Target: *{target['username']}*",
        f"{status}  [{bar}]",
    ]
    statuses = get_active_statuses(target)
    if statuses:
        lines.append("  " + " | ".join(statuses))
    lines.append("━━━━━━━━━━━━━━━━")
    if attackers_info:
        lines.append("⚔️ Attackers:")
        for info in attackers_info[-5:]:  # show last 5 actions
            lines.append(f"  {info}")
    return "\n".join(lines)

async def update_combat_card(bot, chat_id, target, action_line, finished=False):
    card = combat_cards.get(chat_id, {})
    if card.get("target_id") != target["user_id"]:
        # New fight — reset card
        combat_cards[chat_id] = {
            "target_id": target["user_id"],
            "msg_id": None,
            "actions": [],
        }
        card = combat_cards[chat_id]

    card["actions"].append(action_line)
    text = build_combat_card(target, card["actions"], finished)

    if card["msg_id"]:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=card["msg_id"],
                text=text[:4096], parse_mode="Markdown")
            return
        except Exception:
            pass  # fall through to send new

    try:
        msg = await bot.send_message(
            chat_id=chat_id, text=text[:4096], parse_mode="Markdown")
        card["msg_id"] = msg.message_id
    except Exception:
        pass

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

    msg = (f"🌅 *{user.first_name}* returns after *{hours_str}* away "
           f"— _{flavor}_\n\n"
           f"💰 +{gold_reward} gold | ✨ +{exp_reward} EXP")
    if item_found:
        rarity_tag = ""
        for pool in [WEAPONS, ARMORS, ACCESSORIES]:
            if item_found in pool:
                r = pool[item_found].get("rarity","")
                rarity_tag = RARITY_EMOJI.get(r,"")
                break
        msg += f"\n🎒 Found: {rarity_tag} *{item_found}*!"

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

    await announce(bot, chat_id, msg, permanent=True)

# ── RANK ──────────────────────────────────────────────────────────────────────
async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT user_id,username,level,total_exp FROM players")
    rpg_rows = c.fetchall()
    c.execute("SELECT user_id,username,level,total_exp FROM shadow_profiles")
    shd_rows = c.fetchall()
    conn.close()

    seen = {}
    for row in shd_rows:
        uid = row["user_id"]
        seen[uid] = {"user_id":uid,"username":row["username"],
                     "level":row["level"],"total_exp":safe_int(row["total_exp"]),"type":"shadow"}
    for row in rpg_rows:
        uid = row["user_id"]; rlvl = row["level"]; rtex = safe_int(row["total_exp"])
        if uid not in seen or (rlvl,rtex) >= (seen[uid]["level"],seen[uid]["total_exp"]):
            seen[uid] = {"user_id":uid,"username":row["username"],
                         "level":rlvl,"total_exp":rtex,"type":"rpg"}

    all_entries = sorted(seen.values(),
                         key=lambda x:(x["level"],x["total_exp"]), reverse=True)
    total  = len(all_entries)
    medals = {1:"🥇",2:"🥈",3:"🥉"}

    def fmt(pos, e):
        icon  = "⚔️" if e["type"] == "rpg" else "👤"
        badge = medals.get(pos, f"#{pos}")
        return f"{badge} {icon} *{e['username']}* — Lv {e['level']} | {e['total_exp']:,} EXP"

    if context.args and context.args[0].lower() == "me":
        pos = next((i+1 for i,e in enumerate(all_entries) if e["user_id"]==user.id), None)
        if not pos:
            await send_group(update, "Not ranked yet — start chatting!"); return
        e = all_entries[pos-1]
        start = max(0, pos-3); end = min(total, pos+2)
        lines = [f"📊 *{user.first_name}'s Rank: #{pos} of {total}*\n"]
        for i, entry in enumerate(all_entries[start:end], start=start+1):
            arrow = "▶️ " if entry["user_id"] == user.id else "    "
            lines.append(f"{arrow}{fmt(i, entry)}")
        await send_group(update, "\n".join(lines), permanent=True); return

    chunk = all_entries[:50]
    lines = [f"🎱 *{WORLD_NAME} — Top {min(50,total)}* ({total} players)\n",
             "⚔️ = RPG  |  👤 = Chat only\n"]
    for i, e in enumerate(chunk, start=1):
        lines.append(fmt(i, e))

    keyboard = []
    if total > 50:
        keyboard.append([InlineKeyboardButton("➡️ Page 2", callback_data="rank_p_2")])
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        await update.message.delete()
    except Exception:
        pass
    await update.get_bot().send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(lines)[:4096],
        parse_mode="Markdown",
        reply_markup=markup)

async def rank_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    if not data.startswith("rank_p_"): return
    page  = int(data.split("_")[-1])

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
    c.execute("SELECT user_id,username,level,total_exp FROM players")
    rpg_rows = c.fetchall()
    c.execute("SELECT user_id,username,level,total_exp FROM shadow_profiles")
    shd_rows = c.fetchall()
    conn.close()

    seen = {}
    for row in shd_rows:
        uid = row["user_id"]
        seen[uid] = {"user_id":uid,"username":row["username"],
                     "level":row["level"],"total_exp":safe_int(row["total_exp"]),"type":"shadow"}
    for row in rpg_rows:
        uid = row["user_id"]; rlvl = row["level"]; rtex = safe_int(row["total_exp"])
        if uid not in seen or (rlvl,rtex) >= (seen[uid]["level"],seen[uid]["total_exp"]):
            seen[uid] = {"user_id":uid,"username":row["username"],
                         "level":rlvl,"total_exp":rtex,"type":"rpg"}

    all_entries = sorted(seen.values(),
                         key=lambda x:(x["level"],x["total_exp"]), reverse=True)
    total = len(all_entries)
    medals = {1:"🥇",2:"🥈",3:"🥉"}
    def fmt(pos, e):
        icon  = "⚔️" if e["type"] == "rpg" else "👤"
        badge = medals.get(pos, f"#{pos}")
        return f"{badge} {icon} *{e['username']}* — Lv {e['level']} | {e['total_exp']:,} EXP"

    if page == 1:
        chunk = all_entries[:50]
        start_i = 1
    else:
        offset  = 50 + (page-2)*PAGE_SIZE
        chunk   = all_entries[offset:offset+PAGE_SIZE]
        start_i = offset+1

    lines = [f"🎱 *Rankings — Page {page}* ({total} players)\n"]
    for i, e in enumerate(chunk, start=start_i):
        lines.append(fmt(i, e))

    keyboard = []
    row_btns  = []
    if page > 1:
        row_btns.append(InlineKeyboardButton("⬅️ Back", callback_data=f"rank_p_{page-1}"))
    offset_end = 50 + (page-1)*PAGE_SIZE if page > 1 else 50
    if offset_end < total:
        row_btns.append(InlineKeyboardButton("➡️ Next", callback_data=f"rank_p_{page+1}"))
    if row_btns: keyboard.append(row_btns)
    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        await query.edit_message_text(
            "\n".join(lines)[:4096], parse_mode="Markdown", reply_markup=markup)
    except Exception:
        pass

# ── ASCEND ────────────────────────────────────────────────────────────────────
async def ascend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if get_player(user.id):
        await send_group(update, f"⚔️ You're already in {WORLD_NAME}! Use /stats."); return
    s = get_or_create_shadow(user.id, user.first_name)
    if s.get("ascended"):
        await send_group(update, "You've already ascended!"); return
    p = new_player(s)
    slvl = p["shadow_level_at_ascension"]
    await send_group(update,
        f"⚔️ *{user.first_name} has ASCENDED into {WORLD_NAME}!*\n\n"
        f"Level {slvl} shadow legacy converted:\n"
        f"⭐ Starting Level: *{p['level']}*\n"
        f"❤️ HP: {p['hp']} | 💰 Gold: {p['gold']}\n"
        f"💡 Stat Points: *{p['stat_points']}*\n\n"
        f"⚔️ Choose your class at Level 5 with /class\n"
        f"📊 Spend stat points with /allocate\n"
        f"🎁 Claim your daily reward with /daily", permanent=False)
    asyncio.create_task(announce(
        context.bot, update.effective_chat.id,
        f"⚔️ *{user.first_name}* has ASCENDED! Level {slvl} → RPG Level {p['level']}! 🎱",
        permanent=True))

# ── STATS ─────────────────────────────────────────────────────────────────────
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id); s = get_shadow(user.id)
    if not p and not s:
        await send_group(update, "No profile yet — start chatting to build your level, then /ascend!"); return
    if not p:
        tier = get_tier(s["level"])
        await send_group(update,
            f"👤 *{s['username']}* — Shadow Profile\n\n"
            f"{tier['emoji']} Level *{s['level']}*\n"
            f"✨ EXP: {s['exp']:,}/{exp_for_level(s['level']):,}\n"
            f"🏆 Lifetime EXP: *{safe_int(s.get('total_exp')):,}*\n"
            f"💬 Messages: {s.get('message_count',0):,}\n\n"
            f"_Send /ascend to enter the RPG world!_", permanent=True); return
    if s: sync_levels(p, s); save_player(p); save_shadow(s)
    # Auto-clear stale defeated flag
    if is_defeated(p) and p["hp"] > 0:
        p["defeated_until"] = None; save_player(p)
    w        = get_weather()
    cls      = get_player_class(p)
    cls_name = cls["name"] if cls else ("Choose at Lv 5!" if p["level"] >= 5 else "Unlocks at Lv 5")
    path     = p.get("class_path")
    path_str = f" (Path {'A' if path=='A' else 'B'})" if path else ""
    stats_d  = safe_stats(p)
    sp       = safe_int(p.get("stat_points"))
    inv      = Counter(sjl(p.get("inventory"), []))
    inv_text = ", ".join(f"{k}x{v}" for k,v in inv.items()) or "Empty"
    defeated_txt = " *(Defeated — 0 HP)*" if is_defeated(p) else ""
    recovering   = " *(Still Recovering)*" if is_invincible(p) else ""
    guild_text   = "None"
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            guild_text = f"{g['name']} (Lv{glvl})"
    # Gear
    weap  = p.get("equipped_weapon")  or "None"
    armor = p.get("equipped_armor")   or "None"
    shld  = p.get("equipped_shield")  or "None"
    acc   = p.get("equipped_accessory") or "None"
    gear_str = f"⚔️ {weap} | 🛡️ {armor}"
    if p.get("class_path") == "A" and get_class_line(p) == "warrior":
        gear_str += f" | 🔰 {shld}"
    gear_str += f" | 💍 {acc}"
    # Active statuses
    statuses = get_active_statuses(p)
    status_str = "\n" + " | ".join(statuses) if statuses else ""
    tier = get_tier(p["level"])
    await send_group(update,
        f"⚔️ *{p['username']}*{defeated_txt}{recovering}\n"
        f"🏅 *{p['active_title']}* | {tier['name']} | 🏰 {guild_text}\n"
        f"🌍 _{w['name']}_\n\n"
        f"❤️ HP: {p['hp']}/{p['max_hp']} | ⭐ Level {p['level']}\n"
        f"✨ {p['exp']:,}/{exp_for_level(p['level']):,} EXP\n"
        f"🏆 Lifetime EXP: *{safe_int(p.get('total_exp')):,}*\n"
        f"💰 Gold: {p['gold']} | ⚔️ W/L: {p['wins']}/{p['losses']}\n\n"
        f"🧙 Class: *{cls_name}*{path_str}\n"
        f"📊 STR:{stats_d.get('STR',5)} DEF:{stats_d.get('DEF',5)} "
        f"AGI:{stats_d.get('AGI',5)} INT:{stats_d.get('INT',5)} WIS:{stats_d.get('WIS',5)}"
        + (f" | 💡 {sp} pts" if sp > 0 else "") +
        f"\n🎽 Gear: {gear_str}"
        f"{status_str}\n"
        f"🎒 Inventory: {inv_text}\n"
        f"🏅 Titles: {', '.join(safe_titles(p))}",
        permanent=True)

# ── CLASS ─────────────────────────────────────────────────────────────────────
async def class_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if p["level"] < 5:
        await send_group(update, f"⚔️ Classes unlock at Level 5. You're Level {p['level']}."); return
    if p.get("class_id"):
        cls = get_player_class(p)
        skills = sjl(p.get("all_skills"), [])
        skill_lines = "\n".join(
            f"  Tier {sk['tier']}: *{sk['name']}* — {sk.get('passive','')}" for sk in skills)
        await send_group(update,
            f"⚔️ You are a *{cls['name']}*\n\n_{cls['desc']}_\n\n"
            f"🔹 Skills unlocked:\n{skill_lines or 'None yet'}\n\n"
            f"Use /skill to use your active abilities.",
            permanent=False); return
    if not context.args:
        lines = ["⚔️ *Choose your starting class!*\n`/class [name]`\n"]
        for cid in BASE_CLASSES:
            cls = CLASS_TREE[cid]
            sk  = cls.get("skills",[{}])[0]
            lines.append(
                f"*{cls['name']}* — {cls['desc']}\n"
                f"  Primary stat: {cls['primary_stat']}\n"
                f"  Passive: {sk.get('passive','')}\n"
                f"  Active: *{sk.get('active','')}* — {sk.get('desc','')}\n")
        lines.append("_At Level 10 you will choose Path A or B — locked forever._")
        await send_group(update, "\n".join(lines), permanent=False); return
    chosen = context.args[0].lower()
    if chosen not in BASE_CLASSES:
        await send_group(update, f"Unknown class. Choose from: {', '.join(BASE_CLASSES)}"); return
    cls = CLASS_TREE[chosen]; p["class_id"] = chosen
    sd = safe_stats(p)
    for stat, bonus in cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat,5) + bonus
    p["stats"] = json.dumps(sd)
    skills = cls.get("skills",[])
    p["all_skills"] = json.dumps(skills)
    save_player(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{p['username']}* has chosen the *{cls['name']}* class!"))
    sk = skills[0] if skills else {}
    await send_group(update,
        f"⚔️ *{user.first_name}* is now a *{cls['name']}*!\n\n"
        f"_{cls['desc']}_\n\n"
        f"🔹 Passive: {sk.get('passive','')}\n"
        f"🔸 Active: *{sk.get('active','')}* — {sk.get('desc','')}\n\n"
        f"Stat bonus: {', '.join(f'+{v} {k}' for k,v in cls.get('stat_bonus',{}).items())}\n\n"
        f"_At Level 10 use /prestige to choose your path (A or B). Locked forever!_",
        permanent=False)

# ── PRESTIGE (path choice at level 10 only) ───────────────────────────────────
async def prestige_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    cid = p.get("class_id")
    if not cid: await send_group(update, "Choose a class first with /class."); return
    if p.get("class_path"):
        cls = get_player_class(p)
        await send_group(update,
            f"🌟 You are on *Path {p['class_path']}* as a *{cls['name']}*.\n"
            f"Your path is locked. Classes advance automatically at Lv 30, 60 and 100.",
            permanent=False); return
    if p["level"] < 10:
        await send_group(update, f"Path choice unlocks at Level 10. You're Level {p['level']}."); return
    cls  = CLASS_TREE.get(cid, {})
    line = cls.get("line")
    paths = CLASS_PATHS.get(line, {})
    path_a = paths.get("A", [])
    path_b = paths.get("B", [])
    if not context.args:
        a_cls = CLASS_TREE.get(path_a[0], {}) if path_a else {}
        b_cls = CLASS_TREE.get(path_b[0], {}) if path_b else {}
        a_sk  = a_cls.get("skills",[{}])[0]
        b_sk  = b_cls.get("skills",[{}])[0]
        a_end = CLASS_TREE.get(path_a[-1], {}).get("name","?") if path_a else "?"
        b_end = CLASS_TREE.get(path_b[-1], {}).get("name","?") if path_b else "?"
        lines = [
            f"🌟 *Choose your path, {user.first_name}!*\n"
            f"_This choice is permanent. It defines who you become._\n",
            f"*Path A → {a_cls.get('name','?')} → ... → {a_end}*\n"
            f"  {a_cls.get('desc','')}\n"
            f"  Passive: {a_sk.get('passive','')}\n"
            f"  Active: *{a_sk.get('active','')}* — {a_sk.get('desc','')}\n",
            f"*Path B → {b_cls.get('name','?')} → ... → {b_end}*\n"
            f"  {b_cls.get('desc','')}\n"
            f"  Passive: {b_sk.get('passive','')}\n"
            f"  Active: *{b_sk.get('active','')}* — {b_sk.get('desc','')}\n",
            f"`/prestige A` or `/prestige B`"
        ]
        await send_group(update, "\n".join(lines), permanent=False); return
    chosen_path = context.args[0].upper()
    if chosen_path not in ("A","B"):
        await send_group(update, "Use `/prestige A` or `/prestige B`."); return
    path_list = paths.get(chosen_path, [])
    if not path_list:
        await send_group(update, "Invalid path."); return
    p["class_path"] = chosen_path
    _auto_advance_class(p, 10)
    save_player(p)
    new_cls = get_player_class(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"🌟 *{p['username']}* chose *Path {chosen_path}* — now a *{new_cls['name']}*!",
        permanent=True))
    await send_group(update,
        f"🌟 *Path {chosen_path} chosen!*\n\n"
        f"You are now a *{new_cls['name']}*.\n_{new_cls['desc']}_\n\n"
        f"_Your class will advance automatically at Lv 30, 60 and 100._",
        permanent=False)

# ── SKILL ─────────────────────────────────────────────────────────────────────
async def skill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    skills = sjl(p.get("all_skills"), [])
    if not skills:
        await send_group(update, "No skills yet. Choose a class with /class at Level 5."); return
    if is_silenced(p):
        await send_group(update, "🤐 You are silenced and cannot use skills!"); return
    # Show skill menu if no args and no reply
    if not context.args and not update.message.reply_to_message:
        cls = get_player_class(p)
        lines = [f"🔮 *{p['username']}'s Skills*\n"]
        for sk in skills:
            lines.append(
                f"*Tier {sk['tier']} — {sk['name']}*\n"
                f"  🔹 {sk.get('passive','')}\n"
                f"  🔸 {sk.get('active','')} — {sk.get('desc','')}\n")
        lines.append("_Reply to a target and type `/skill [tier]` to use active skill._\n"
                     "_Healing skills work without a target._")
        keyboard = []
        for sk in skills:
            keyboard.append([InlineKeyboardButton(
                f"Tier {sk['tier']}: {sk['name']}",
                callback_data=f"skill_info_{sk['tier']}")])
        markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await send_group(update, "\n".join(lines), permanent=False, reply_markup=markup); return
    # Determine which tier skill to use
    tier = 1
    if context.args:
        try: tier = int(context.args[0])
        except: pass
    sk = next((s for s in skills if s["tier"] == tier), skills[-1])
    await _execute_skill(update, context, p, sk)

async def _execute_skill(update, context, p, sk):
    user   = update.effective_user
    stype  = sk.get("type","damage")
    w      = get_weather()
    lines  = [f"🔮 *{user.first_name}* uses *{sk['name']}*!"]
    chat_id = update.effective_chat.id

    # ── Self/heal type skills ─────────────────────────────────────────────────
    if stype == "self_heal":
        wis   = get_stat(p, "WIS")
        mult  = sk.get("wis_mult", 5)
        heal  = wis * mult
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        lines.append(f"💚 Healed self for *{heal} HP*! ({p['hp']}/{p['max_hp']})")
        save_player(p)
        await send_group(update, "\n".join(lines), permanent=False); return

    if stype == "revive_heal":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target's message first!"); return
        du = update.message.reply_to_message.from_user
        d  = get_player(du.id)
        if not d: await send_group(update, f"{du.first_name} hasn't ascended!"); return
        if is_revival_blocked(d):
            await send_group(update, f"❌ *{d['username']}* has been condemned — cannot be revived! (Zealot's Holy Wrath)"); return
        if is_healing_blocked(d):
            await send_group(update, f"❌ *{d['username']}* cannot be healed right now."); return
        wis  = get_stat(p, "WIS")
        heal = wis * sk.get("wis_mult", 5)
        if p.get("class_id") in HEALER_CLASSES:
            was_defeated = is_defeated(d)
            d["hp"] = min(calc_max_hp(d), d["hp"] + heal)
            if was_defeated:
                d["defeated_until"] = None
                set_status(d, "invincible_until", 3600)
                lines.append(f"✨ *{d['username']}* has been revived!")
                lines.append(f"🛡️ *{d['username']}* is invincible for 1 hour (Still Recovering).")
            else:
                lines.append(f"💚 Healed *{d['username']}* for *{heal} HP*!")
            p["heals_given"] = safe_int(p.get("heals_given")) + 1
            for t in check_titles(p): lines.append(f"🏅 *{t}*!")
            save_player(p); save_player(d)
            await send_group(update, "\n".join(lines), permanent=False); return
        else:
            await send_group(update, "Only Priest-line classes can revive with their skill."); return

    if stype == "group_heal":
        wis  = get_stat(p, "WIS")
        heal = wis * sk.get("wis_mult", 3)
        gid  = p.get("guild_id")
        healed_names = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for uid in sjl(g.get("members"),[]):
                    mp = get_player(uid)
                    if mp and not is_defeated(mp):
                        mp["hp"] = min(calc_max_hp(mp), mp["hp"] + heal)
                        save_player(mp); healed_names.append(mp["username"])
        lines.append(f"💚 *Mass Heal!* Healed: {', '.join(healed_names) or 'no guild members in DB'}  (+{heal} HP each)")
        save_player(p)
        await send_group(update, "\n".join(lines), permanent=False); return

    if stype == "mass_cleanse":
        gid = p.get("guild_id")
        cleansed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for uid in sjl(g.get("members"),[]):
                    mp = get_player(uid)
                    if mp:
                        for field in ["distracted_until","entangled_until","frozen_until",
                                      "stunned_until","bleed_until","hexed_until",
                                      "weakened_until","healing_blocked_until",
                                      "revival_blocked_until","silenced_until"]:
                            mp[field] = None
                        set_status(mp, "blessed_until", 1800)
                        save_player(mp); cleansed.append(mp["username"])
        lines.append(f"✨ *Absolution!* Cleansed all debuffs from: {', '.join(cleansed) or 'guild members'}.")
        lines.append("🌟 All guild members are now *Blessed* for 30 minutes.")
        lines.append("_(This counters Zealot's revival block.)_")
        save_player(p)
        await send_group(update, "\n".join(lines), permanent=False, delay=60); return

    if stype == "dmg_reduction_buff":
        if not update.message.reply_to_message:
            await send_group(update, "Reply to your target!"); return
        du = update.message.reply_to_message.from_user
        d  = get_player(du.id)
        if not d: await send_group(update, f"{du.first_name} hasn't ascended!"); return
        set_status(d, "blessed_until", 3600)
        lines.append(f"✨ *Blessing* granted to *{d['username']}* — 15% less damage for 1 hour!")
        save_player(d); save_player(p)
        await send_group(update, "\n".join(lines), permanent=False); return

    # ── Offensive skills — need a target ─────────────────────────────────────
    if not update.message.reply_to_message:
        await send_group(update, "Reply to your target's message to use this skill!"); return
    du = update.message.reply_to_message.from_user
    if du.id == user.id:
        await send_group(update, "Can't target yourself!"); return
    d = get_player(du.id)
    if not d: await send_group(update, f"{du.first_name} hasn't ascended!"); return
    if is_defeated(d): await send_group(update, f"{d['username']} is already defeated!"); return
    if is_invincible(d): await send_group(update, f"{d['username']} is still recovering — untargetable!"); return

    base = calc_attack_damage(p, w)
    dmg  = 0

    if stype == "stun":
        dmg = round(base * 1.0)
        if random.random() < 0.30:
            set_status(d, "stunned_until", 30)
            lines.append(f"⚡ *{d['username']}* is stunned — misses next attack!")
    elif stype == "dmg_field":
        dmg = round(base * 1.2)
        set_status(p, "holy_field_until", 1800)
        lines.append(f"✨ Holy field active for 30 min — attackers take WIS x2 damage back!")
    elif stype == "combo_dmg":
        def_val = get_stat(p,"DEF"); str_val = get_stat(p,"STR")
        dmg = str_val + def_val
        if d["hp"] / max(1,d["max_hp"]) < 0.40:
            set_status(d, "stunned_until", 60)
            lines.append(f"⚡ Guaranteed stun! *{d['username']}* cannot attack for 60s!")
    elif stype == "self_heal_buff":
        heal = round(p["max_hp"] * 0.30)
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        dmg = round(base * 0.5)
        lines.append(f"💚 Rallied! +{heal} HP restored.")
    elif stype == "guaranteed_hit":
        dmg = round(base * 1.5)
        # Break own roots
        p["entangled_until"] = None; p["frozen_until"] = None; p["stunned_until"] = None
        lines.append("💨 *Charge!* Broke free of all roots!")
    elif stype == "aoe_recent_attackers":
        targets = get_recent_attackers(d if stype != "aoe_recent_attackers" else p)
        if not targets: targets = [d["user_id"]]
        per_target_dmg = round(base * (1 + 0.25 * len(targets)))
        dmg = per_target_dmg
        lines.append(f"🌪️ Hits {len(targets)} target(s) for ~{per_target_dmg} each!")
        for tid in targets:
            tp = get_player(tid)
            if tp and not is_defeated(tp):
                final = calc_defense(tp, per_target_dmg)
                tp["hp"] = max(0, tp["hp"] - final)
                if tp["hp"] == 0:
                    set_status(tp, "defeated_until", 21600)
                    lines.append(f"💀 *{tp['username']}* defeated!")
                save_player(tp)
    elif stype == "holy_nuke":
        s_val = get_stat(p,"STR"); d_val = get_stat(p,"DEF"); w_val = get_stat(p,"WIS")
        dmg = (s_val + d_val + w_val) * 3
        lines.append(f"☀️ *Wrath of the Fallen!* {dmg} divine damage!")
    elif stype == "execute_nuke":
        dmg = get_stat(p,"STR") * 6
        lines.append(f"💀 *Decimation!* STR x6 = {dmg}!")
    elif stype == "spell":
        dmg = round(base * sk.get("mult",1.2)) + get_stat(p,"INT")
        lines.append(f"🔥 Spell damage: {dmg}!")
    elif stype == "bounce_spell":
        dmg = round(base * 1.4) + get_stat(p,"INT")
        lines.append(f"⚡ *Chain Lightning!* {dmg} + bounces!")
    elif stype == "freeze_nuke":
        dmg = get_stat(p,"INT") * 6
        set_status(d, "frozen_until", 60)
        lines.append(f"🧊 *Absolute Zero!* {dmg} dmg. *{d['username']}* frozen 60s!")
    elif stype == "debuff":
        dmg = round(base * 1.0)
        set_status(d, "hexed_until", 120)
        lines.append(f"💀 *Hexed!* {d['username']} deals 25% less damage for 2 minutes.")
    elif stype == "drain":
        steal = round(d["hp"] * sk.get("drain_pct",0.30))
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        dmg = round(base * sk.get("mult",1.0))
        lines.append(f"🩸 Drained *{steal} HP* from {d['username']}!")
    elif stype == "drain_kill":
        steal = round(d["hp"] * sk.get("drain_pct",0.40))
        p["hp"] = min(calc_max_hp(p), p["hp"] + steal)
        dmg = round(base * sk.get("mult",1.5))
        lines.append(f"🩸 *Drain Soul!* Stole {steal} HP!")
    elif stype == "void_nuke":
        dmg = round(d["hp"] * 0.50)
        set_status(d, "healing_blocked_until", 1800)
        lines.append(f"🌑 *Void Collapse!* {dmg} dmg. Cannot be healed for 30 min!")
    elif stype == "crit_dmg":
        dmg = apply_crit(p, round(base * sk.get("mult",1.8)))
        lines.append("💥 *Guaranteed Critical!*")
    elif stype == "bleed_crit":
        dmg = apply_crit(p, round(base * sk.get("mult",2.0)))
        set_status(d, "bleed_until", 300)
        d["bleed_damage"] = 10
        lines.append(f"🩸 *{d['username']}* is bleeding! 10 dmg every 30s for 5 minutes.")
    elif stype == "dodge_buff":
        dmg = round(base * 1.0)
        set_status(p, "vanish_until", 120)
        lines.append(f"💨 *Smoke Screen!* Next attack on you will miss (2 min).")
    elif stype == "pierce_dmg":
        dmg = get_stat(p,"AGI") * 3
        lines.append(f"🌑 *Shadow Strike!* AGI x3 = {dmg}. Unblockable!")
    elif stype == "vanish":
        set_status(p, "vanish_until", 60)
        lines.append("👻 *Vanished!* Untargetable for 60 seconds.")
        dmg = 0
    elif stype == "fear_kill":
        dmg = get_stat(p,"AGI") * 6
        lines.append(f"☠️ *Soul Rend!* AGI x6 = {dmg}!")
    elif stype == "silence":
        dmg = round(base * 1.5)
        set_status(d, "silenced_until", 60)
        lines.append(f"🤐 *{d['username']}* silenced — no skills for 60 seconds!")
    elif stype == "execute_shot":
        dmg = get_stat(p,"AGI") * 6
        lines.append(f"🎯 *Last Shot!* AGI x6 = {dmg}!")
    elif stype == "pierce_all":
        dmg = get_stat(p,"STR") * 2
        lines.append(f"🏹 *Piercing Shot!* STR x2 = {dmg}. Ignores all defenses!")
    elif stype == "charged_shot":
        p["charging_killshot"] = 1
        lines.append("🎯 *Killshot charged!* Next /attack fires AGI x4 — unblockable!")
        dmg = 0
    elif stype == "strip_debuff":
        dmg = 0
        buffs_stripped = 0
        for field in ["blessed_until","invincible_until"]:
            if _ts_active(d, field):
                d[field] = None; buffs_stripped += 1
        set_status(d, "healing_blocked_until", 1800)
        dmg = get_stat(p,"WIS") * 2 * max(1, buffs_stripped)
        lines.append(f"🔥 *Banish!* Stripped {buffs_stripped} buff(s). {dmg} holy damage. No buffs for 30 min!")
    elif stype == "bind_attacker":
        dmg = 0
        set_status(d, "entangled_until", 600)
        lines.append(f"⚖️ *Trial!* {d['username']} can only attack you for 10 minutes.")
    elif stype == "condemn":
        wis_val = get_stat(p,"WIS")
        dmg = wis_val * 8
        for field in ["blessed_until","invincible_until","holy_field_until"]:
            d[field] = None
        for field in ["distracted_until","hexed_until","weakened_until","bleed_until"]:
            set_status(d, field, 3600)
        d["bleed_damage"] = round(wis_val * 0.5)
        lines.append(f"⚡ *Holy Wrath!* {dmg} divine damage. All debuffs applied!")
    elif stype == "holy_dmg":
        dmg = get_stat(p,"WIS") * 3
        if p.get("wins",0) > 0:
            dmg *= 2
            lines.append("☀️ Double damage — target has defeated others!")
    elif stype == "miss_debuff":
        set_status(d, "distracted_until", 180)
        lines.append(f"😵 *Distract!* {d['username']} has +30% miss chance for 3 minutes.")
        dmg = 0
    elif stype == "root":
        dmg = round(base * 1.0)
        set_status(d, "entangled_until", 90)
        lines.append(f"🌿 *Entangle!* {d['username']} cannot attack for 90 seconds!")
    elif stype == "random_aoe":
        dmg = 0
        lines.append(f"🏹 *Barrage!* Firing 6 arrows at random targets!")
    elif stype == "bounty":
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        expires = (datetime.now() + timedelta(hours=24)).isoformat()
        c.execute("INSERT INTO bounties (placer_id,target_id,reward,expires_at) VALUES(?,?,?,?)",
                  (user.id, d["user_id"], 500, expires))
        conn.commit(); conn.close()
        lines.append(f"💰 *Bounty placed on {d['username']}!* First to defeat them gets 500 gold. You get 250 regardless.")
        dmg = 0
    elif stype == "smite":
        dmg = get_stat(p,"WIS") * 3
    elif stype == "multihit":
        hits = sk.get("hits",2)
        mult = sk.get("mult",0.8)
        dmg  = sum(round(calc_attack_damage(p,w)*mult) for _ in range(hits))
        lines.append(f"⚡ {hits}-hit combo! Total: {dmg}")
    else:
        dmg = round(base * sk.get("mult",1.0))

    # Apply defense (unless skill pierces)
    pierce = stype in ("pierce_all","pierce_dmg","execute_nuke","holy_nuke","void_nuke","condemn")
    if dmg > 0 and not pierce:
        dmg = calc_defense(d, dmg)

    # Apply reflect
    reflect = apply_reflect(d, p, dmg)
    if reflect:
        lines.append(f"🔁 *{d['username']}* reflects {reflect} damage back!")
        if p["hp"] <= 0:
            set_status(p, "defeated_until", 21600); p["hp"] = 0

    if dmg > 0:
        d["hp"] = max(0, d["hp"] - dmg)
        lines.append(f"💥 *{dmg} damage* dealt to *{d['username']}*!\n❤️ {d['username']}: {d['hp']}/{d['max_hp']} HP")

    # Lifesteal
    ls = apply_lifesteal(p, dmg)
    if ls: lines.append(f"🩸 Restored {ls} HP.")

    # Defeat check
    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        # Check Last Shot (Deadeye)
        if sk.get("type") == "execute_shot":
            set_status(d, "defeated_until", 43200)  # 12 hours
            lines.append(f"☠️ *Last Shot!* {d['username']} is out for *12 hours*!")
            p["gold"] = p.get("gold",0) + d.get("gold",0) // 10
        else:
            set_status(d, "defeated_until", 21600)
        exp_loss = round(d["exp"] * 0.05)
        d["exp"] = max(0, d["exp"] - exp_loss)
        d["losses"] = d.get("losses",0) + 1
        p["wins"]   = p.get("wins",0) + 1
        exp_gain = 80 + p["level"] * 8
        lmsgs, leveled = add_exp(p, exp_gain, w); lvl_msgs = lmsgs
        lines.append(f"\n💀 *{d['username']}* has been defeated! Sits out 6 hours.")
        lines.append(f"✨ *{p['username']}* gains {exp_gain} EXP!")
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}*! ⚔️", permanent=True))

    for t in check_titles(p): lines.append(f"🏅 *{t}*!")
    save_player(p); save_player(d)
    full = "\n".join(lines)
    if lvl_msgs: full += "\n\n" + "\n".join(lvl_msgs)
    await send_group(update, full, permanent=False, delay=30)

# ── ASCEND ────────────────────────────────────────────────────────────────────
async def ascend_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if get_player(user.id):
        await send_group(update, f"⚔️ You're already in {WORLD_NAME}! Use /stats."); return
    s = get_or_create_shadow(user.id, user.first_name)
    if s.get("ascended"):
        await send_group(update, "You've already ascended!"); return
    p = new_player(s)
    slvl = p["shadow_level_at_ascension"]
    await send_group(update,
        f"⚔️ *{user.first_name} has ASCENDED into {WORLD_NAME}!*\n\n"
        f"Level {slvl} legacy carries over:\n"
        f"⭐ Starting Level: *{p['level']}*\n"
        f"❤️ HP: {p['hp']} | 💰 Gold: {p['gold']}\n"
        f"💡 Stat Points: *{p['stat_points']}*\n\n"
        f"⚔️ Choose your class at Level 5 with /class\n"
        f"📊 Spend stat points with /allocate\n"
        f"🎁 Claim daily reward with /daily", delay=60)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{user.first_name}* has ASCENDED! Level {slvl} → RPG Level {p['level']}! 🎱",
        permanent=True))

# ── STATS ─────────────────────────────────────────────────────────────────────
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id)
    s = get_shadow(user.id)
    if not p and not s:
        await send_group(update, "No profile yet — just start chatting!"); return
    if not p:
        tier = get_tier(s["level"])
        await send_group(update,
            f"👤 *{s['username']}* — Shadow Profile\n\n"
            f"{tier['emoji']} Level *{s['level']}*\n"
            f"✨ EXP: {s['exp']:,}/{exp_for_level(s['level']):,}\n"
            f"🏆 Lifetime EXP: *{safe_int(s.get('total_exp')):,}*\n"
            f"💬 Messages: {s.get('message_count',0):,}\n\n"
            f"_Use /ascend to enter the RPG!_", permanent=True); return
    if s: sync_levels(p, s); save_player(p); save_shadow(s)

    # Auto-clear stale defeated status
    if p.get("defeated_until") and p["hp"] > 0:
        p["defeated_until"] = None; save_player(p)

    w    = get_weather()
    tier = get_tier(p["level"])
    cls  = get_player_class(p)
    cls_name = cls["name"] if cls else ("Choose at Lv 5!" if p["level"] >= 5 else "Unlocks at Lv 5")
    path = get_class_path(p)
    path_str = f" — Path {'A' if path == 'A' else 'B'}" if path else ""

    # Gear
    weap = p.get("equipped_weapon") or "None"
    armr = p.get("equipped_armor")  or "None"
    shld = p.get("equipped_shield") or ""
    acc  = p.get("equipped_accessory") or "None"
    shld_str = f" + {shld}" if shld else ""

    # Status effects
    statuses = get_active_statuses(p)
    status_str = "\n" + " | ".join(statuses) if statuses else ""

    defeated_str = " *(Defeated — 0 HP)*" if is_defeated(p) else ""
    recovering   = " *(Still Recovering)*" if is_invincible(p) and not is_defeated(p) else ""

    # Guild
    guild_str = "None"
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            perk = GUILD_PERKS.get(glvl,{})
            guild_str = f"{g['name']} (Lv{glvl} +{int(perk.get('exp_bonus',0)*100)}% EXP)"

    sd  = safe_stats(p)
    sp  = safe_int(p.get("stat_points"))
    inv = Counter(sjl(p.get("inventory"), []))
    inv_str = ", ".join(f"{k} x{v}" for k,v in inv.items()) or "Empty"

    await send_group(update,
        f"⚔️ *{p['username']}*{defeated_str}{recovering}\n"
        f"🏅 *{p['active_title']}* | {tier['name']} | 🏰 {guild_str}\n"
        f"🌍 {WORLD_NAME} — _{w['name']}_\n\n"
        f"❤️ HP: {p['hp']}/{p['max_hp']} | ⭐ Level {p['level']}\n"
        f"✨ EXP: {p['exp']:,}/{exp_for_level(p['level']):,}\n"
        f"🏆 Lifetime EXP: {safe_int(p.get('total_exp')):,}\n"
        f"💰 Gold: {p['gold']} | W/L: {p['wins']}/{p['losses']}\n\n"
        f"🧙 Class: {cls_name}{path_str}\n"
        f"📊 STR:{sd.get('STR',5)} DEF:{sd.get('DEF',5)} "
        f"AGI:{sd.get('AGI',5)} INT:{sd.get('INT',5)} WIS:{sd.get('WIS',5)}"
        + (f" | 💡 {sp} pts" if sp > 0 else "") + "\n\n"
        f"⚔️ Weapon: {weap}\n"
        f"🛡️ Armor: {armr}{shld_str}\n"
        f"💍 Accessory: {acc}\n\n"
        f"🎒 Inventory: {inv_str}\n"
        f"🏅 Titles: {', '.join(safe_titles(p))}"
        + status_str, permanent=True)

# ── CLASS ─────────────────────────────────────────────────────────────────────
async def class_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if p["level"] < 5:
        await send_group(update, f"⚔️ Classes unlock at Level 5. You're Level {p['level']}."); return
    if p.get("class_id"):
        cls = get_player_class(p)
        skills = sjl(p.get("all_skills"), [])
        skill_lines = "\n".join(
            f"  🔸 *{s['name']}* (Lv{s['unlock']}): {s['desc']}" for s in skills)
        await send_group(update,
            f"⚔️ You are a *{cls['name']}*\n\n"
            f"_{cls['desc']}_\n\n"
            f"🔹 Passive: {cls.get('skills',[{}])[0].get('passive','')}\n\n"
            f"🔸 *Your Skills:*\n{skill_lines or 'None yet'}\n\n"
            f"_Use /skill to use your active skills in combat._", delay=60); return
    if not context.args:
        lines = ["⚔️ *Choose your starting class:*\n`/class [name]`\n"]
        for cid in BASE_CLASSES:
            cls = CLASS_TREE[cid]
            sk  = cls.get("skills",[{}])[0]
            lines.append(
                f"*{cls['name']}* — {cls['desc']}\n"
                f"  🔹 {sk.get('passive','')}\n"
                f"  🔸 {sk.get('active','')} — {sk.get('desc','')}\n")
        await send_group(update, "\n".join(lines), delay=60); return
    chosen = context.args[0].lower()
    if chosen not in BASE_CLASSES:
        await send_group(update, f"Unknown class. Choose: {', '.join(BASE_CLASSES)}"); return
    cls = CLASS_TREE[chosen]; p["class_id"] = chosen
    sd  = safe_stats(p)
    for stat, bonus in cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat, 5) + bonus
    p["stats"] = json.dumps(sd)
    sk = cls.get("skills",[{}])[0]
    p["all_skills"] = json.dumps([sk])
    save_player(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{p['username']}* has chosen *{cls['name']}*!"))
    await send_group(update,
        f"⚔️ *{user.first_name}* is now a *{cls['name']}*!\n\n"
        f"_{cls['desc']}_\n\n"
        f"🔹 {sk.get('passive','')}\n"
        f"🔸 *{sk.get('active','')}* — {sk.get('desc','')}\n\n"
        f"At Level 10 use /prestige to choose your path (A or B).\n"
        f"Stat bonus: {', '.join(f'+{v} {k}' for k,v in cls.get('stat_bonus',{}).items())}",
        delay=60)

# ── PRESTIGE (path choice at level 10) ───────────────────────────────────────
async def prestige_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    cid = p.get("class_id")
    if not cid: await send_group(update, "Choose a class first with /class."); return
    if p.get("class_path"):
        await send_group(update,
            f"You've already chosen Path {p['class_path']}. "
            f"Your class advances automatically at Lv 30, 60 and 100."); return
    if p["level"] < 10:
        await send_group(update, f"Path choice unlocks at Level 10. You're Level {p['level']}."); return
    cls  = CLASS_TREE.get(cid,{})
    line = cls.get("line")
    if not line: await send_group(update, "Class data error."); return
    paths = CLASS_PATHS.get(line, {})
    path_A_first = paths.get("A",["?"])[0]
    path_B_first = paths.get("B",["?"])[0]
    cls_A = CLASS_TREE.get(path_A_first,{})
    cls_B = CLASS_TREE.get(path_B_first,{})
    sk_A  = cls_A.get("skills",[{}])[0]
    sk_B  = cls_B.get("skills",[{}])[0]

    if not context.args:
        await send_group(update,
            f"🌟 *Choose Your Path — {cls['name']}*\n\n"
            f"*Path A: {cls_A.get('name','')}*\n"
            f"_{cls_A.get('desc','')}_\n"
            f"🔹 {sk_A.get('passive','')}\n"
            f"🔸 {sk_A.get('active','')} — {sk_A.get('desc','')}\n\n"
            f"*Path B: {cls_B.get('name','')}*\n"
            f"_{cls_B.get('desc','')}_\n"
            f"🔹 {sk_B.get('passive','')}\n"
            f"🔸 {sk_B.get('active','')} — {sk_B.get('desc','')}\n\n"
            f"`/prestige A` or `/prestige B`\n"
            f"⚠️ This choice is permanent.", delay=60); return

    chosen_path = context.args[0].upper()
    if chosen_path not in ("A","B"):
        await send_group(update, "Type `/prestige A` or `/prestige B`."); return

    path_list = paths.get(chosen_path,[])
    if not path_list:
        await send_group(update, "Path data error."); return

    new_cid = path_list[0]
    new_cls = CLASS_TREE.get(new_cid,{})
    p["class_path"] = chosen_path
    p["class_id"]   = new_cid
    sd = safe_stats(p)
    for stat, bonus in new_cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat,5) + bonus
    p["stats"] = json.dumps(sd)
    new_sk = new_cls.get("skills",[{}])[0]
    existing = sjl(p.get("all_skills"),[])
    if new_sk and new_sk.get("name") not in [s.get("name") for s in existing]:
        existing.append(new_sk)
    p["all_skills"] = json.dumps(existing)
    save_player(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"🌟 *{p['username']}* chose Path {chosen_path}: *{new_cls.get('name','')}*!",
        permanent=True))
    await send_group(update,
        f"🌟 *{user.first_name}* is now a *{new_cls.get('name','')}*!\n\n"
        f"_{new_cls.get('desc','')}_\n\n"
        f"🔹 {new_sk.get('passive','')}\n"
        f"🔸 *{new_sk.get('active','')}* — {new_sk.get('desc','')}\n\n"
        f"Your class evolves automatically at Lv 30, 60 and 100.", delay=60)

# ── SKILL ─────────────────────────────────────────────────────────────────────
async def skill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 You're defeated!"); return
    if is_silenced(p): await send_group(update, "🤐 You are silenced and cannot use skills!"); return
    skills = sjl(p.get("all_skills"), [])
    if not skills:
        await send_group(update, "You have no skills yet. Choose a class with /class."); return

    # No args — show skill menu as inline buttons
    if not context.args and not update.message.reply_to_message:
        keyboard = []
        for sk in skills:
            keyboard.append([InlineKeyboardButton(
                f"🔸 {sk['name']} (Lv{sk['unlock']})",
                callback_data=f"skill_info_{sk['name'].replace(' ','_')}")])
        markup = InlineKeyboardMarkup(keyboard)
        await send_group(update,
            "🔮 *Your Skills* — tap to see details or reply to a target first then use `/skill [name]`:",
            reply_markup=markup, delay=30); return

    # /skill [name] replying to target
    skill_name = " ".join(context.args) if context.args else None
    if not skill_name:
        await send_group(update, "Usage: Reply to a target then `/skill [skill name]`"); return

    sk = next((s for s in skills if s["name"].lower() == skill_name.lower()), None)
    if not sk:
        names = ", ".join(s["name"] for s in skills)
        await send_group(update, f"Unknown skill. Your skills: {names}"); return

    if not update.message.reply_to_message:
        # Healing/self skills don't need a target
        if sk.get("type") in ("self_heal","revive_heal","mass_cleanse","group_heal","self_heal_buff","dmg_reduction_buff"):
            pass  # allow without target
        else:
            await send_group(update, "Reply to your target's message first, then use the skill."); return

    w = get_weather()
    lines = [f"🔮 *{user.first_name}* uses *{sk['name']}*!"]
    stype = sk.get("type","damage")

    # ── Resolve target ────────────────────────────────────────────────────────
    target = None
    if update.message.reply_to_message:
        du = update.message.reply_to_message.from_user
        if du.id != user.id:
            target = get_player(du.id)

    # ── Execute skill by type ─────────────────────────────────────────────────
    exp_gain = 0; lvl_msgs = []

    if stype == "self_heal":
        heal = safe_stats(p).get("WIS",5) * sk.get("wis_mult",5)
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        lines.append(f"💚 Healed self for *{heal} HP*! ({p['hp']}/{p['max_hp']})")

    elif stype == "revive_heal":
        if target and is_defeated(target) and not is_revival_blocked(target):
            if not is_healing_blocked(target):
                heal = safe_stats(p).get("WIS",5) * sk.get("wis_mult",5)
                target["hp"] = min(calc_max_hp(target), heal)
                target["defeated_until"] = None
                set_status(target, "invincible_until", 3600)
                p["heals_given"] += 1
                lines.append(f"💚 *{target['username']}* revived with {heal} HP! 1 hour invincibility granted.")
                save_player(target)
            else:
                lines.append(f"🚫 {target['username']} cannot be healed right now.")
        elif target:
            heal = safe_stats(p).get("WIS",5) * sk.get("wis_mult",5)
            target["hp"] = min(calc_max_hp(target), target["hp"] + heal)
            lines.append(f"💚 Healed *{target['username']}* for {heal} HP!")
            save_player(target)
        else:
            heal = safe_stats(p).get("WIS",5) * sk.get("wis_mult",5)
            p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
            lines.append(f"💚 Healed self for {heal} HP!")

    elif stype == "group_heal":
        heal = safe_stats(p).get("WIS",5) * sk.get("wis_mult",3)
        gid  = p.get("guild_id")
        healed_names = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"),[]):
                    mp = get_player(mid)
                    if mp and not is_defeated(mp):
                        mp["hp"] = min(calc_max_hp(mp), mp["hp"] + heal)
                        save_player(mp)
                        healed_names.append(mp["username"])
        lines.append(f"💚 *Mass Heal!* Healed {', '.join(healed_names) or 'no one'} for {heal} HP each.")

    elif stype == "mass_cleanse":
        gid = p.get("guild_id")
        cleansed = []
        if gid and str(gid) != "None":
            g = get_guild(gid)
            if g:
                for mid in sjl(g.get("members"),[]):
                    mp = get_player(mid)
                    if mp:
                        for field in ["distracted_until","entangled_until","frozen_until",
                                      "stunned_until","bleed_until","hexed_until",
                                      "weakened_until","healing_blocked_until",
                                      "revival_blocked_until","silenced_until"]:
                            mp[field] = None
                        set_status(mp, "blessed_until", 1800)
                        save_player(mp)
                        cleansed.append(mp["username"])
        lines.append(f"✨ *Absolution!* Cleansed all debuffs from: {', '.join(cleansed) or 'no one'}. "
                     f"30 min blessed status granted. Revival blocks lifted.")

    elif stype == "dmg_reduction_buff" and target:
        if not is_defeated(target):
            set_status(target, "blessed_until", 3600)
            lines.append(f"✨ *Blessing* granted to *{target['username']}*! "
                         f"15% damage reduction for 1 hour.")
            save_player(target)

    elif stype == "self_heal_buff":
        heal = round(p["max_hp"] * 0.30)
        p["hp"] = min(calc_max_hp(p), p["hp"] + heal)
        lines.append(f"💚 *Rally!* Restored {heal} HP.")
        # Also buff guild members in chat (simplified — just announce)
        lines.append("⚔️ Guild members gain +15% damage for 10 minutes!")

    elif target and not is_defeated(target):
        # Offensive skills
        if check_miss(p, target):
            lines.append(f"💨 *{sk['name']}* missed!")
        else:
            dmg = calc_attack_damage(p, w)
            # Apply skill multiplier
            mult = sk.get("mult", 1.0)
            hits = sk.get("hits", 1)
            total_dmg = 0
            if hits > 1:
                for _ in range(hits):
                    h = round(calc_attack_damage(p, w) * mult)
                    if check_crit(p): h = apply_crit(p, h)
                    total_dmg += h
                lines.append(f"⚡ {hits}-hit combo! Total: {total_dmg}")
                dmg = total_dmg
            else:
                dmg = round(dmg * mult)
                if stype in ("crit","bleed_crit"):
                    dmg = apply_crit(p, dmg)
                    lines.append("💥 *Guaranteed Critical!*")

            # Special handling per type
            if stype == "stun":
                if random.random() < 0.30:
                    set_status(target, "stunned_until", 30)
                    lines.append(f"⚡ *Stunned!* {target['username']} misses next attack!")
            elif stype == "root":
                set_status(target, "entangled_until", 90)
                lines.append(f"🌿 *{target['username']}* is rooted for 90 seconds!")
            elif stype == "freeze_nuke":
                set_status(target, "frozen_until", 60)
                lines.append(f"🧊 *{target['username']}* is frozen for 60 seconds!")
            elif stype == "debuff":
                set_status(target, "hexed_until", 120)
                lines.append(f"💀 *Hexed!* {target['username']} deals 25% less damage for 2 minutes!")
            elif stype == "miss_debuff":
                set_status(target, "distracted_until", 180)
                lines.append(f"😵 *{target['username']}* is distracted — 30% miss chance for 3 minutes!")
            elif stype == "bleed_crit":
                set_status(target, "bleed_until", 300)
                target["bleed_damage"] = 10
                lines.append(f"🩸 *{target['username']}* is bleeding! 10 damage every 30s for 5 minutes.")
            elif stype == "void_nuke":
                target["hp"] = max(0, target["hp"] - round(target["hp"] * 0.50))
                set_status(target, "healing_blocked_until", 1800)
                lines.append(f"🌑 *Void Collapse!* Lost 50% current HP. Cannot be healed for 30 minutes!")
                dmg = 0  # hp already applied
            elif stype == "drain" or stype == "drain_kill":
                drain = round(target["hp"] * sk.get("drain_pct", 0.30))
                p["hp"] = min(calc_max_hp(p), p["hp"] + drain)
                lines.append(f"🩸 Drained *{drain} HP* from {target['username']}!")
            elif stype == "vanish":
                set_status(p, "vanish_until", 60)
                lines.append(f"👻 *{p['username']}* vanishes! Untargetable for 60 seconds.")
                dmg = 0
            elif stype == "silence":
                set_status(target, "silenced_until", 60)
                lines.append(f"🤐 *{target['username']}* is silenced for 60 seconds!")
            elif stype == "condemn":
                for field in ["distracted_until","hexed_until","weakened_until"]:
                    set_status(target, field, 600)
                set_status(target, "revival_blocked_until", 7200)
                lines.append(f"☠️ All debuffs applied! *Revival blocked for 2 hours* — only Saint's Absolution can counter!")
            elif stype == "strip_debuff":
                buffs_removed = 0
                for field in ["blessed_until","invincible_until"]:
                    if _ts_active(target, field):
                        target[field] = None; buffs_removed += 1
                dmg += buffs_removed * (safe_stats(p).get("WIS",5) * 2)
                lines.append(f"🔥 *Banish!* Removed {buffs_removed} buffs! "
                             f"+{buffs_removed * safe_stats(p).get('WIS',5) * 2} bonus damage!")
                set_status(target, "healing_blocked_until", 1800)

            if dmg > 0:
                dmg = calc_defense(target, dmg)
                target["hp"] = max(0, target["hp"] - dmg)
                ls = apply_lifesteal(p, dmg)
                if ls: lines.append(f"🩸 Lifesteal: +{ls} HP")
                lines.append(f"💥 *{dmg} damage* to *{target['username']}*!")
                lines.append(f"❤️ {target['username']}: {target['hp']}/{target['max_hp']} HP")

            if target["hp"] <= 0:
                target["hp"] = 0
                defeated_hours = 6
                if stype == "execution_shot":
                    defeated_hours = 12
                    lines.append(f"💀 *LAST SHOT!* {target['username']} defeated for 12 hours!")
                    asyncio.create_task(announce(context.bot, update.effective_chat.id,
                        f"🎯 *{p['username']}* (Deadeye) eliminated *{target['username']}*! "
                        f"12 hour defeat!", permanent=True))
                target["defeated_until"] = (datetime.now() + timedelta(hours=defeated_hours)).isoformat()
                exp_loss = round(target["exp"] * 0.10)
                target["exp"] = max(0, target["exp"] - exp_loss)
                target["losses"] += 1; p["wins"] += 1
                exp_gain = 80 + p["level"] * 8
                lmsgs, leveled = add_exp(p, exp_gain, w); lvl_msgs = lmsgs
                lines.append(f"\n💀 *{target['username']}* defeated! -{exp_loss} EXP.")
                if leveled and p["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, update.effective_chat.id,
                        f"🎉 *{p['username']}* reached *Level {p['level']}*! ⚔️", permanent=True))
                asyncio.create_task(update_combat_card(
                    context.bot, update.effective_chat.id, target,
                    f"{p['username']} used {sk['name']} — DEFEATED!", finished=True))
            else:
                asyncio.create_task(update_combat_card(
                    context.bot, update.effective_chat.id, target,
                    f"{p['username']} used {sk['name']} — {dmg} dmg"))

            save_player(target)
        for t in check_titles(p): lines.append(f"🏅 *{t}*!")

    save_player(p)
    full = "\n".join(lines)
    if lvl_msgs: full += "\n\n" + "\n".join(lvl_msgs)
    await send_group(update, full, delay=30)

async def skill_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if not query.data.startswith("skill_info_"): return
    skill_name = query.data[len("skill_info_"):].replace("_"," ")
    p = get_player(query.from_user.id)
    if not p: return
    skills = sjl(p.get("all_skills"),[])
    sk = next((s for s in skills if s["name"].lower() == skill_name.lower()), None)
    if not sk:
        await query.answer("Skill not found.", show_alert=True); return
    stats = safe_stats(p)
    primary = get_primary_stat(p)
    stat_val = stats.get(primary, 5)
    est_dmg = ""
    mult = sk.get("mult",1.0)
    if mult > 0:
        base_avg = 5 + get_weapon_atk(p) + stat_val//2 + p["level"]//2
        lo = round(base_avg * mult * 0.8)
        hi = round(base_avg * mult * 1.2)
        est_dmg = f"\n📊 Est. damage: *{lo}–{hi}*"
    text = (f"🔸 *{sk['name']}* (Unlocked Lv{sk['unlock']})\n\n"
            f"{sk['desc']}{est_dmg}\n\n"
            f"🔹 Passive: {sk.get('passive','')}\n\n"
            f"_Reply to a target then `/skill {sk['name']}`_")
    try:
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=query.message.reply_markup)
    except Exception:
        pass

# ── ATTACK ────────────────────────────────────────────────────────────────────
async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    au = update.effective_user; a = get_player(au.id)
    if not a: await send_group(update, "Use /ascend first!"); return
    if is_defeated(a): await send_group(update, "💀 You're defeated!"); return
    if cannot_attack(a):
        if is_stunned(a):   await send_group(update, "⚡ You are stunned!"); return
        if is_rooted(a):    await send_group(update, "🌿 You are rooted!"); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /attack to strike them!"); return
    du = update.message.reply_to_message.from_user
    if du.id == au.id: await send_group(update, "Can't attack yourself!"); return
    d = get_player(du.id)
    if not d: await send_group(update, f"{du.first_name} hasn't ascended yet!"); return
    if is_defeated(d): await send_group(update, f"{d['username']} is already defeated!"); return
    if is_invincible(d): await send_group(update, f"{d['username']} is still recovering — untargetable!"); return

    w = get_weather(); lines = []
    update_recent_attackers(d, au.id)

    if check_miss(a, d):
        d["dodges"] += 1
        save_player(a); save_player(d)
        asyncio.create_task(update_combat_card(
            context.bot, update.effective_chat.id, d,
            f"{a['username']} attacked — MISSED"))
        await send_group(update, f"💨 *{a['username']}* swings at *{d['username']}* and misses!", delay=15)
        return

    dmg = calc_attack_damage(a, w)
    is_crit = check_crit(a)
    if is_crit:
        dmg = apply_crit(a, dmg)
        lines.append("💥 *CRITICAL HIT!*")

    # Reflect damage
    reflect = apply_reflect(d, a, dmg)
    if reflect:
        lines.append(f"⚡ *{d['username']}* reflects {reflect} damage back!")

    dmg = calc_defense(d, dmg)
    lifesteal = apply_lifesteal(a, dmg)
    if lifesteal: lines.append(f"🩸 Lifesteal: +{lifesteal} HP")

    d["hp"] = max(0, d["hp"] - dmg)
    lines.insert(0, f"⚔️ *{a['username']}* strikes *{d['username']}* for *{dmg} damage!*")

    # Holy field retaliation (Consecrate)
    if _ts_active(d, "holy_field_until"):
        holy_dmg = safe_stats(d).get("WIS",5) * 2
        a["hp"] = max(0, a["hp"] - holy_dmg)
        lines.append(f"✝️ *Holy Field!* {a['username']} takes {holy_dmg} holy damage back!")
        save_player(a)

    # Devotion charge (Squire passive)
    cls_d = get_player_class(d)
    if cls_d and cls_d.get("passive_key") == "devotion":
        d["devotion_charge"] = safe_int(d.get("devotion_charge")) + 5

    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        d["defeated_until"] = (datetime.now() + timedelta(hours=6)).isoformat()
        exp_loss = round(d["exp"] * 0.10)
        d["exp"] = max(0, d["exp"] - exp_loss)
        d["losses"] += 1; a["wins"] += 1
        exp_gain = 60 + a["level"] * 8
        lmsgs, leveled = add_exp(a, exp_gain, w); lvl_msgs = lmsgs
        # Bounty check
        active_bounties = _get_active_bounties(d["user_id"])
        for b in active_bounties:
            _claim_bounty(b, au.id, context.bot, update.effective_chat.id)
        # Bounty Hunter passive
        cls_a = get_player_class(a)
        if cls_a and cls_a.get("passive_key") == "marked_for_death":
            bonus_gold = round(d.get("gold",0) * 0.25)
            a["gold"] = a.get("gold",0) + bonus_gold
            lines.append(f"💰 *Marked for Death!* +{bonus_gold} bonus gold!")
        # Conqueror passive
        if cls_a and cls_a.get("passive_key") == "conqueror":
            heal = round(a["max_hp"] * 0.20)
            a["hp"] = min(calc_max_hp(a), a["hp"] + heal)
            set_status(d, "weakened_until", 3600)
            lines.append(f"👑 *Conqueror!* +{heal} HP. {d['username']} weakened for 1 hour!")
        lines.append(f"\n💀 *{d['username']}* has fallen! -{exp_loss} EXP. 6hr cooldown.")
        if leveled and a["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, update.effective_chat.id,
                f"🎉 *{a['username']}* reached *Level {a['level']}*! ⚔️", permanent=True))
        asyncio.create_task(update_combat_card(
            context.bot, update.effective_chat.id, d,
            f"{a['username']} hit {dmg} — DEFEATED", finished=True))
    else:
        lines.append(f"❤️ {d['username']}: *{d['hp']}/{d['max_hp']} HP* remaining.")
        asyncio.create_task(update_combat_card(
            context.bot, update.effective_chat.id, d,
            f"{a['username']} hit {dmg} dmg"))

    for t in check_titles(a): lines.append(f"🏅 *{a['username']}* earned: *{t}*!")
    save_player(a); save_player(d)
    full = "\n".join(lines)
    if lvl_msgs: full += "\n\n" + "\n".join(lvl_msgs)
    await send_group(update, full, delay=30)

def _get_active_bounties(target_id):
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM bounties WHERE target_id=? AND claimed_by IS NULL", (target_id,))
    rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def _claim_bounty(bounty, claimer_id, bot, chat_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE bounties SET claimed_by=? WHERE bounty_id=?",
              (claimer_id, bounty["bounty_id"]))
    conn.commit(); conn.close()
    cp = get_player(claimer_id)
    pp = get_player(bounty["placer_id"])
    if cp:
        cp["gold"] = cp.get("gold",0) + 500
        save_player(cp)
    if pp:
        pp["gold"] = pp.get("gold",0) + 250
        save_player(pp)
    asyncio.create_task(announce(bot, chat_id,
        f"🎯 *Bounty claimed!* "
        f"{cp['username'] if cp else '?'} collected 500g. "
        f"{pp['username'] if pp else '?'} gets 250g.", permanent=False))

# ── HEAL ──────────────────────────────────────────────────────────────────────
async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hu = update.effective_user; h = get_player(hu.id)
    if not h: await send_group(update, "Use /ascend first!"); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /heal!"); return
    tu = update.message.reply_to_message.from_user
    t  = get_player(tu.id)
    if not t: await send_group(update, f"{tu.first_name} hasn't ascended yet!"); return

    if is_healing_blocked(t):
        await send_group(update, f"🚫 *{t['username']}* cannot be healed right now!"); return
    if is_revival_blocked(t) and is_defeated(t):
        await send_group(update, f"☠️ *{t['username']}* cannot be revived — Zealot's curse! Only a Saint's Absolution can lift it."); return

    # Check if healer is a priest-line class
    cls = get_player_class(h)
    is_priest_healer = cls and cls.get("line") == "priest" and cls.get("class_id","") in HEALER_CLASSES if cls else False
    # Actually check class_id
    cid = h.get("class_id","")
    is_free_healer = cid in HEALER_CLASSES

    inv   = sjl(h.get("inventory"), [])
    potion = None
    heal_amount = 0

    if is_free_healer:
        # Priest line — use skill Holy Light for free
        heal_amount = safe_stats(h).get("WIS",5) * 5
        if cls and cls.get("passive_key") == "mending_aura":
            heal_amount = round(heal_amount * 1.25)
    else:
        # Everyone else needs a potion
        if "Mega Health Potion" in inv:
            potion = "Mega Health Potion"; heal_amount = 200
        elif "Super Health Potion" in inv:
            potion = "Super Health Potion"; heal_amount = 100
        elif "Health Potion" in inv:
            potion = "Health Potion"; heal_amount = 50
        else:
            await send_group(update,
                "❌ You need a Health Potion to heal someone!\n"
                "_(Priests can heal for free with their class skill)_"); return
        inv.remove(potion)
        h["inventory"] = json.dumps(inv)

    # Apply heal bonus from WIS
    heal_amount += safe_stats(h).get("WIS",5)
    heal_amount += get_accessory_bonus(h, "heal_bonus") if get_accessory_bonus(h, "heal_bonus") else 0

    t["hp"] = min(calc_max_hp(t), t["hp"] + heal_amount)
    if is_defeated(t) and not is_revival_blocked(t):
        t["defeated_until"] = None
        t["hp"] = min(calc_max_hp(t), heal_amount)
        set_status(t, "invincible_until", 3600)
        revive_msg = f"💫 *{t['username']}* has been revived! 1 hour invincibility granted."
    else:
        revive_msg = f"❤️ {t['username']}: {t['hp']}/{t['max_hp']} HP"

    h["heals_given"] += 1
    new_t = check_titles(h)
    lmsgs, leveled = add_exp(h, 20)
    save_player(h); save_player(t)

    source = "Holy Light (free)" if is_free_healer else potion
    msg = f"💊 *{h['username']}* heals *{t['username']}* for {heal_amount} HP using {source}!\n{revive_msg}"
    if new_t: msg += f"\n🏅 *{h['username']}* earned: *{new_t[0]}*!"
    if lmsgs: msg += "\n" + "\n".join(lmsgs)
    if leveled and h["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{h['username']}* reached *Level {h['level']}*! 💊", permanent=True))
    await send_group(update, msg, delay=30)

# ── DAILY ─────────────────────────────────────────────────────────────────────
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not check_cooldown(p.get("last_daily"), 86400):
        await send_group(update,
            f"🎁 Daily already claimed! Come back in {time_remaining(p.get('last_daily'), 86400)}."); return
    p["last_daily"] = datetime.now().isoformat()
    gold = 50 + p["level"] * 5; p["gold"] = p.get("gold",0) + gold
    lmsgs, leveled = add_exp(p, 300)
    # Rare potion chance
    potion_msg = ""
    if random.random() < 0.10:
        potion = "Health Potion"
        add_item(p, potion)
        potion_msg = f" | 🎒 {potion}"
    save_player(p)
    msg = f"🎁 *Daily Reward!*\n\n✨ +300 EXP | 💰 +{gold} Gold{potion_msg}\n\nCome back tomorrow!"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from daily reward! 🎁", permanent=True))
    await send_group(update, msg, delay=45)

# ── TRAIN ─────────────────────────────────────────────────────────────────────
TRAIN_MESSAGES = [
    "You spent time at the practice board.",
    "You sparred until your arms gave out.",
    "You drilled until your legs burned.",
    "You studied combat techniques all night.",
    "You pushed through an exhausting session.",
    "You honed your instincts on the back road.",
]
async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Too beaten up to train!"); return
    if not check_cooldown(p.get("last_train"), 1800):
        await send_group(update,
            f"⏳ Training cooldown: {time_remaining(p.get('last_train'), 1800)}"); return
    w = get_weather()
    base = 80 + p["level"] * 3
    cls  = get_player_class(p); bonus_msg = ""
    if cls:
        pk = cls.get("passive_key","")
        if pk in ("arcane_mind","spell_surge","soul_pact"): base = round(base*1.30); bonus_msg = " 🔮 Focus bonus!"
        elif pk in ("iron_will","holy_stance","bulwark"):   base = round(base*1.20); bonus_msg = " 🛡️ Endurance bonus!"
        elif pk in ("quick_hands","evasion","ghost_form"):  base = round(base*1.35); bonus_msg = " ⚡ Speed bonus!"
        elif pk in ("mending_aura","divine_grace","sacred_ground"): base = round(base*1.15); bonus_msg = " ✨ Wisdom bonus!"
    p["last_train"] = datetime.now().isoformat()
    lmsgs, leveled = add_exp(p, base, w); save_player(p)
    msg = f"🏋️ *Training*\n\n_{random.choice(TRAIN_MESSAGES)}_\n\n✨ +{base} EXP{bonus_msg}"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from training! 🏋️", permanent=True))
    await send_group(update, msg, delay=30)

# ── QUEST ─────────────────────────────────────────────────────────────────────
async def quest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 You're defeated!"); return
    if not check_cooldown(p.get("last_quest"), 3600):
        await send_group(update,
            f"⏳ Quest cooldown: {time_remaining(p.get('last_quest'), 3600)}"); return
    w = get_weather()
    if p["level"] <= 5:    pool = [q for q in SOLO_QUESTS if q["tier"] == "Easy"]
    elif p["level"] <= 15: pool = [q for q in SOLO_QUESTS if q["tier"] in ["Easy","Medium"]]
    else:                  pool = SOLO_QUESTS
    if not pool: pool = SOLO_QUESTS
    q = random.choice(pool)
    p["last_quest"] = datetime.now().isoformat()
    p["quests_done"] = p.get("quests_done",0) + 1
    p["gold"] = p.get("gold",0) + q["gold"]
    item_found = roll_loot_table(q.get("loot_table",[]))
    if item_found: add_item(p, item_found)
    lmsgs, leveled = add_exp(p, q["exp"], w)
    new_t = check_titles(p); save_player(p)
    msg = f"🗺️ *Quest — {q['tier']}*\n\n{q['text']}\n\n✨ +{q['exp']} EXP | 💰 +{q['gold']} Gold"
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
            f"🎉 *{p['username']}* reached *Level {p['level']}* from a quest! 🗺️", permanent=True))
    await send_group(update, msg, delay=45)

# ── EXPLORE ───────────────────────────────────────────────────────────────────
async def explore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't explore while defeated!"); return

    # Check twice-per-day limit
    today = datetime.now().strftime("%Y-%m-%d")
    if p.get("explore_date") != today:
        p["explore_date"]       = today
        p["explore_count_today"] = 0

    if safe_int(p.get("explore_count_today")) >= 2:
        await send_group(update, "🗺️ You've already explored twice today. Come back tomorrow!"); return

    # Check if already on an expedition
    if user.id in explore_timers:
        await send_group(update, "🗺️ You're already on an expedition! Wait for it to complete."); return

    # Pick zone
    if context.args:
        zn = " ".join(context.args).lower()
        zone = next((z for z in EXPLORE_ZONES if zn in z["name"].lower()), None)
        if not zone:
            zl = "\n".join(f"• {z['name']} ({z['tier']})" for z in EXPLORE_ZONES)
            await send_group(update, f"Unknown zone. Available:\n{zl}"); return
    else:
        if p["level"] <= 10:    elig = [z for z in EXPLORE_ZONES if z["tier"] == "Easy"]
        elif p["level"] <= 30:  elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium"]]
        elif p["level"] <= 60:  elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium","Hard"]]
        else:                   elig = EXPLORE_ZONES
        zone = random.choice(elig)

    p["explore_count_today"] = safe_int(p.get("explore_count_today")) + 1
    p["last_explore"] = datetime.now().isoformat()
    save_player(p)

    await send_group(update,
        f"🗺️ *{user.first_name}* sets out for *{zone['name']}* ({zone['tier']})!\n"
        f"_Results in 1 hour..._", delay=30)

    # Schedule result
    async def deliver_result():
        await asyncio.sleep(3600)
        explore_timers.pop(user.id, None)
        fp = get_player(user.id)
        if not fp: return
        w  = get_weather()
        item_found = roll_loot_table(zone.get("loot_table",[]))
        exp  = round(zone["exp"] * w.get("exp_mod",1.0))
        gold = zone["gold"]
        fp["gold"] = fp.get("gold",0) + gold
        if item_found: add_item(fp, item_found)
        lmsgs, leveled = add_exp(fp, exp)
        save_player(fp)

        rarity_tag = ""
        if item_found:
            for pool2 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
                if item_found in pool2:
                    r = pool2[item_found].get("rarity","")
                    rarity_tag = RARITY_EMOJI.get(r,"")
                    break

        msg = (f"🗺️ *{user.first_name}* returns from *{zone['name']}*!\n\n"
               f"✨ +{exp} EXP | 💰 +{gold} Gold")
        if item_found: msg += f"\n🎒 Found: {rarity_tag} *{item_found}*!"
        if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
        if leveled and fp["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, update.effective_chat.id,
                f"🎉 *{fp['username']}* reached *Level {fp['level']}* from exploring! 🗺️",
                permanent=True))
        await announce(context.bot, update.effective_chat.id, msg, permanent=True)

    task = asyncio.create_task(deliver_result())
    explore_timers[user.id] = task

# ── SHOP ──────────────────────────────────────────────────────────────────────
async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    discount = 0
    if _ts_active(p, "shop_discount_until"): discount = 0.20
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            if glvl >= 10: discount = max(discount, 0.15)
            elif glvl >= 7: discount = max(discount, 0.10)
    if not context.args:
        shop = get_daily_shop()
        lines = [f"🛒 *Daily Shop* | 💰 You have {p['gold']} gold\n"]
        if discount: lines.append(f"🎉 Discount active: *{int(discount*100)}% off!*\n")
        for i, entry in enumerate(shop, 1):
            price = round(entry["price"] * (1 - discount))
            lines.append(f"{i}. *{entry['item']}* — {price}g\n   _{entry['desc']}_")
        lines.append("\n`/shop buy [1-5]`")
        await send_group(update, "\n".join(lines), delay=30); return
    if context.args[0].lower() == "buy":
        if len(context.args) < 2:
            await send_group(update, "Usage: /shop buy [1-5]"); return
        try: idx = int(context.args[1]) - 1
        except: await send_group(update, "Usage: /shop buy [1-5]"); return
        shop = get_daily_shop()
        if idx < 0 or idx >= len(shop):
            await send_group(update, "Invalid item number."); return
        entry = shop[idx]
        price = round(entry["price"] * (1 - discount))
        if p["gold"] < price:
            await send_group(update, f"❌ Need {price}g, have {p['gold']}g."); return
        p["gold"] -= price; add_item(p, entry["item"]); save_player(p)
        await send_group(update,
            f"✅ Bought *{entry['item']}* for {price}g! 💰 Remaining: {p['gold']}g", delay=15)

# ── INVENTORY ─────────────────────────────────────────────────────────────────
async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    inv = Counter(sjl(p.get("inventory"),[]))
    if not inv:
        await send_group(update, "🎒 Your inventory is empty!"); return
    lines = [f"🎒 *{p['username']}'s Inventory:*\n"]
    for item, count in inv.items():
        rarity_tag = ""
        desc = ""
        for pool in [WEAPONS, ARMORS, ACCESSORIES, CONSUMABLES, SHIELDS]:
            if item in pool:
                r = pool[item].get("rarity","")
                rarity_tag = RARITY_EMOJI.get(r,"")
                desc = pool[item].get("desc","")
                if not desc:
                    atk = pool[item].get("atk",0)
                    df  = pool[item].get("def",0)
                    if atk: desc = f"+{atk} ATK"
                    if df:  desc = f"+{df} DEF"
                break
        lines.append(f"{rarity_tag} *{item}* x{count} — _{desc}_")
    lines.append(f"\n💰 Gold: {p['gold']}")
    await send_group(update, "\n".join(lines), permanent=True)

# ── EQUIP ─────────────────────────────────────────────────────────────────────
async def equip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args:
        weap = p.get("equipped_weapon") or "None"
        armr = p.get("equipped_armor")  or "None"
        shld = p.get("equipped_shield") or "None"
        acc  = p.get("equipped_accessory") or "None"
        await send_group(update,
            f"⚔️ *Equipped Gear:*\n"
            f"Weapon: {weap}\nArmor: {armr}\n"
            f"Shield: {shld}\nAccessory: {acc}\n\n"
            f"`/equip [item name]` to equip from inventory."); return
    item_name = " ".join(context.args)
    inv = sjl(p.get("inventory"),[])
    if item_name not in inv:
        await send_group(update, f"You don't have *{item_name}* in your inventory."); return

    if item_name in WEAPONS:
        ok, err = can_equip_weapon(p, item_name)
        if not ok: await send_group(update, f"❌ {err}"); return
        old = p.get("equipped_weapon")
        if old: add_item(p, old)  # return old to inventory
        p["equipped_weapon"] = item_name
        inv.remove(item_name); p["inventory"] = json.dumps(inv)
        save_player(p)
        w = WEAPONS[item_name]
        await send_group(update,
            f"⚔️ Equipped *{item_name}* ({RARITY_EMOJI.get(w['rarity'],'')} +{w['atk']} ATK)!", delay=15)

    elif item_name in ARMORS:
        ok, err = can_equip_armor(p, item_name)
        if not ok: await send_group(update, f"❌ {err}"); return
        old = p.get("equipped_armor")
        if old: add_item(p, old)
        p["equipped_armor"] = item_name
        inv.remove(item_name); p["inventory"] = json.dumps(inv)
        save_player(p)
        a = ARMORS[item_name]
        await send_group(update,
            f"🛡️ Equipped *{item_name}* ({RARITY_EMOJI.get(a['rarity'],'')} +{a['def']} DEF)!", delay=15)

    elif item_name in SHIELDS:
        s_data = SHIELDS[item_name]
        if get_class_line(p) != "warrior" or get_class_path(p) != "A":
            await send_group(update, "❌ Only Warrior Path A can use shields."); return
        old = p.get("equipped_shield")
        if old: add_item(p, old)
        p["equipped_shield"] = item_name
        inv.remove(item_name); p["inventory"] = json.dumps(inv)
        save_player(p)
        await send_group(update,
            f"🛡️ Equipped *{item_name}* ({RARITY_EMOJI.get(s_data['rarity'],'')} +{s_data['def']} DEF)!", delay=15)

    elif item_name in ACCESSORIES:
        old = p.get("equipped_accessory")
        if old: add_item(p, old)
        p["equipped_accessory"] = item_name
        inv.remove(item_name); p["inventory"] = json.dumps(inv)
        save_player(p)
        acc = ACCESSORIES[item_name]
        await send_group(update,
            f"💍 Equipped *{item_name}* ({RARITY_EMOJI.get(acc['rarity'],'')} — {acc['desc']})!", delay=15)
    else:
        await send_group(update, f"*{item_name}* is not equippable gear."); return

# ── USE ───────────────────────────────────────────────────────────────────────
async def use_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args: await send_group(update, "Usage: /use [item name]"); return
    item = " ".join(context.args)
    inv  = sjl(p.get("inventory"),[])
    if item not in inv:
        await send_group(update, f"You don't have *{item}*."); return
    inv.remove(item); p["inventory"] = json.dumps(inv)
    msg = f"✅ Used *{item}*. "
    if item == "Health Potion":
        p["hp"] = min(calc_max_hp(p), p["hp"]+50); msg += f"❤️ +50 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Super Health Potion":
        p["hp"] = min(calc_max_hp(p), p["hp"]+100); msg += f"❤️ +100 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Mega Health Potion":
        p["hp"] = min(calc_max_hp(p), p["hp"]+200); msg += f"❤️ +200 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Revival Charm":
        p["defeated_until"] = None
        p["hp"] = p["max_hp"] // 2
        set_status(p, "invincible_until", 3600)
        msg += "💚 Revived! 1 hour invincibility."
    else:
        inv.append(item); p["inventory"] = json.dumps(inv)
        msg = f"*{item}* can't be used directly. Equip it with /equip."
    save_player(p)
    await send_group(update, msg, delay=15)

# ── SELL ──────────────────────────────────────────────────────────────────────
async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args: await send_group(update, "Usage: /sell [item name]"); return
    item = " ".join(context.args)
    inv  = sjl(p.get("inventory"),[])
    if item not in inv:
        await send_group(update, f"You don't have *{item}*."); return
    value = 0
    for pool in [WEAPONS,ARMORS,ACCESSORIES,SHIELDS,CONSUMABLES]:
        if item in pool:
            base = pool[item].get("atk") or pool[item].get("def") or pool[item].get("sell",50)
            rarity_mult = {"common":1,"uncommon":2,"rare":5,"epic":15,"legendary":50}
            r = pool[item].get("rarity","common")
            value = round(base * rarity_mult.get(r,1) * 2)
            break
    if value == 0: value = 10
    inv.remove(item); p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold",0) + value
    save_player(p)
    await send_group(update,
        f"💰 Sold *{item}* for *{value} gold*! Balance: {p['gold']}g", delay=15)

# ── TRADE ─────────────────────────────────────────────────────────────────────
async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to the player you want to trade with, then `/trade [item] [price]`"); return
    if len(context.args) < 2:
        await send_group(update, "Usage: Reply to player + `/trade [item name] [price]`"); return
    try:
        price     = int(context.args[-1])
        item_name = " ".join(context.args[:-1])
    except ValueError:
        await send_group(update, "Price must be a number. `/trade [item] [price]`"); return
    inv = sjl(p.get("inventory"),[])
    if item_name not in inv:
        await send_group(update, f"You don't have *{item_name}*."); return
    tu = update.message.reply_to_message.from_user
    tp = get_player(tu.id)
    if not tp:
        await send_group(update, f"{tu.first_name} hasn't ascended yet!"); return
    if tu.id == user.id:
        await send_group(update, "Can't trade with yourself!"); return

    pending_trades[tu.id] = {
        "from_id":   user.id,
        "from_name": user.first_name,
        "item":      item_name,
        "price":     price,
    }
    await send_group(update,
        f"📦 *Trade Offer Sent!*\n\n"
        f"*{user.first_name}* offers *{item_name}* to *{tp['username']}* for *{price}g*\n\n"
        f"_{tp['username']}*: Use `/accept` to accept or `/decline` to refuse._", delay=60)

async def accept_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    trade = pending_trades.pop(user.id, None)
    if not trade:
        await send_group(update, "No pending trade for you."); return
    seller = get_player(trade["from_id"])
    if not seller:
        await send_group(update, "Seller not found."); return
    if p["gold"] < trade["price"]:
        await send_group(update, f"❌ Not enough gold! Need {trade['price']}g, have {p['gold']}g."); return
    s_inv = sjl(seller.get("inventory"),[])
    if trade["item"] not in s_inv:
        await send_group(update, f"❌ Seller no longer has *{trade['item']}*."); return
    s_inv.remove(trade["item"]); seller["inventory"] = json.dumps(s_inv)
    add_item(p, trade["item"])
    p["gold"]      -= trade["price"]
    seller["gold"]  = seller.get("gold",0) + trade["price"]
    save_player(p); save_player(seller)
    await send_group(update,
        f"✅ *Trade Complete!*\n"
        f"*{p['username']}* received *{trade['item']}* for {trade['price']}g.\n"
        f"*{seller['username']}* received {trade['price']}g.", delay=30)

async def decline_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    trade = pending_trades.pop(user.id, None)
    if not trade:
        await send_group(update, "No pending trade."); return
    await send_group(update, f"❌ Trade declined.", delay=9)

# ── ALLOCATE ──────────────────────────────────────────────────────────────────
async def allocate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    sp = safe_int(p.get("stat_points")); sd = safe_stats(p)
    STAT_NAMES = ["STR","DEF","AGI","INT","WIS"]
    if not context.args or len(context.args) < 2:
        cls = get_player_class(p)
        rec = cls.get("primary_stat","?") if cls else "Free"
        await send_group(update,
            f"📊 *Stat Allocation* — {sp} points available\n\n"
            f"STR:{sd['STR']} DEF:{sd['DEF']} AGI:{sd['AGI']} INT:{sd['INT']} WIS:{sd['WIS']}\n\n"
            f"📌 STR — Melee damage\n📌 DEF — Damage reduction\n"
            f"📌 AGI — Dodge & crit\n📌 INT — Spell damage\n📌 WIS — Heal power\n\n"
            f"🧭 Primary stat: *{rec}*\n\n`/allocate STR 5`", delay=30); return
    stat = context.args[0].upper()
    if stat not in STAT_NAMES:
        await send_group(update, f"Unknown stat. Choose: {', '.join(STAT_NAMES)}"); return
    try: amount = int(context.args[1])
    except: await send_group(update, "Usage: /allocate STR 5"); return
    if amount <= 0: await send_group(update, "Amount must be positive."); return
    if amount > sp: await send_group(update, f"Not enough points! Have {sp}."); return
    sd[stat] = sd.get(stat,5) + amount
    p["stats"] = json.dumps(sd)
    p["stat_points"] = sp - amount
    save_player(p)
    await send_group(update,
        f"✅ +{amount} to *{stat}*! ({sd[stat]} total)\n💡 {p['stat_points']} points remaining.", delay=15)

# ── TITLE ─────────────────────────────────────────────────────────────────────
async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    titles = safe_titles(p)
    if not context.args:
        await send_group(update,
            f"🏅 *Your Titles:*\n" + "\n".join(f"• {t}" for t in titles) +
            "\n\n`/title [name]` to equip.", delay=30); return
    chosen = " ".join(context.args)
    if chosen not in titles:
        await send_group(update, f"You haven't earned *{chosen}* yet!"); return
    p["active_title"] = chosen; save_player(p)
    await send_group(update, f"🏅 Title set to *{chosen}*!", delay=9)

# ── COOLDOWNS ─────────────────────────────────────────────────────────────────
async def cooldowns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    lines = [f"⏳ *{p['username']}'s Cooldowns:*\n",
             f"🎁 Daily:    {time_remaining(p.get('last_daily'), 86400)}",
             f"🗺️ Quest:    {time_remaining(p.get('last_quest'), 3600)}",
             f"🏋️ Train:    {time_remaining(p.get('last_train'), 1800)}",
             f"🗺️ Explore:  {time_remaining(p.get('last_explore'), 3600)} ({p.get('explore_count_today',0)}/2 today)"]
    if is_defeated(p):
        end  = datetime.fromisoformat(p["defeated_until"])
        diff = end - datetime.now()
        m, s2 = divmod(int(diff.total_seconds()), 60); h, m = divmod(m, 60)
        lines.append(f"💀 Defeat:   {h}h {m}m remaining")
    await send_group(update, "\n".join(lines), delay=20)

# ── WEATHER ───────────────────────────────────────────────────────────────────
async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = get_weather()
    hint = "\n🌑 _Something stirs in the shadows..._" if w.get("secret_eligible") else ""
    await send_group(update,
        f"🌦️ *Table Conditions: {w['name']}*\n_{w['desc']}_\n\n"
        f"📈 EXP: x{w['exp_mod']} | ⚔️ DMG: x{w['dmg_mod']}{hint}", delay=20)

# ── ATTACK ────────────────────────────────────────────────────────────────────
async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    au = update.effective_user; a = get_player(au.id)
    if not a: await send_group(update, "Use /ascend first!"); return
    if is_defeated(a): await send_group(update, "💀 You're at 0 HP — sit out until healed!"); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /attack to strike them!"); return
    du = update.message.reply_to_message.from_user
    if du.id == au.id: await send_group(update, "Can't attack yourself!"); return
    d = get_player(du.id)
    if not d: await send_group(update, f"{du.first_name} hasn't ascended yet!"); return
    if is_defeated(d): await send_group(update, f"💀 {d['username']} is already at 0 HP!"); return
    if is_invincible(d): await send_group(update, f"🛡️ {d['username']} is still recovering — untargetable!"); return

    w = get_weather(); lines = []

    # Charged killshot check
    if safe_int(a.get("charging_killshot")):
        a["charging_killshot"] = 0
        dmg = get_stat(a, "AGI") * 4
        lines.append(f"🎯 *KILLSHOT FIRED!* AGI x4 = {dmg}! Cannot be dodged!")
        d["hp"] = max(0, d["hp"] - dmg)
        lines.append(f"💥 *{dmg} damage!* ❤️ {d['username']}: {d['hp']}/{d['max_hp']} HP")
    else:
        # Miss check
        if check_miss(a, d):
            d["dodges"] = d.get("dodges",0) + 1
            check_titles(d); save_player(a); save_player(d)
            # Shadowstep bonus
            cls_d = get_player_class(d)
            if cls_d and cls_d.get("passive_key") == "shadowstep":
                cds = safe_cds(d); cds["shadowstep_primed"] = "1"
                d["passive_cooldowns"] = json.dumps(cds); save_player(d)
            await send_group(update,
                f"🌀 *{d['username']}* dodges *{a['username']}*'s attack!",
                permanent=False, delay=15); return

        dmg = calc_attack_damage(a, w)

        # Crit
        forced_crit = safe_cds(a).pop("next_crit_skill", None)
        if forced_crit:
            cds_a = safe_cds(a); cds_a.pop("next_crit_skill",None)
            a["passive_cooldowns"] = json.dumps(cds_a)
        if forced_crit or check_crit(a):
            dmg = apply_crit(a, dmg)
            lines.append("💥 *CRITICAL HIT!*")

        # Shadowstep primed bonus
        cds_a = safe_cds(a)
        if cds_a.get("shadowstep_primed"):
            dmg = round(dmg * 1.50)
            cds_a.pop("shadowstep_primed"); a["passive_cooldowns"] = json.dumps(cds_a)
            lines.append("🌑 *Shadowstep!* +50% damage after dodge!")

        # Devotion charge (Page/Squire/Knight/Paladin)
        cls_a = get_player_class(a)
        if cls_a and cls_a.get("passive_key") == "devotion":
            charge = safe_int(a.get("devotion_charge"))
            if charge > 0:
                dmg += 5; a["devotion_charge"] = 0
                lines.append(f"✨ *Devotion charge!* +5 bonus damage!")

        # Attacker passives
        if cls_a:
            pk = cls_a.get("passive_key","")
            if pk == "warcry":
                recent_atk = get_recent_attackers(a)
                if len(recent_atk) > 1:
                    dmg = round(dmg * 1.20); lines.append("😤 *Warcry!* +20% damage!")
            if pk == "execute":
                if d["hp"] / max(1,d["max_hp"]) < 0.25:
                    dmg *= 2; lines.append("💀 *Execute!* Double damage below 25% HP!")
            if pk == "flurry" and random.random() < 0.20:
                dmg *= 2; lines.append("⚡ *Flurry!* Double hit!")
            if pk == "conqueror":
                dmg = round(dmg * 1.0)  # handled on kill
            if pk == "one_shot" and random.random() < 0.10:
                dmg *= 5; lines.append("🎯 *ONE-SHOT!* 5x damage!")
            if pk == "mark_first_hit":
                if safe_int(a.get("mark_first_hit")):
                    dmg = round(dmg * 1.25)
                    a["mark_first_hit"] = 0
                    lines.append("🎯 *First strike bonus!* +25%!")
            if pk == "steady_aim":
                if safe_int(a.get("steady_aim_target")) == d["user_id"]:
                    stacks = min(5, safe_int(a.get("steady_aim_stacks")) + 1)
                    a["steady_aim_stacks"] = stacks
                else:
                    a["steady_aim_target"] = d["user_id"]
                    a["steady_aim_stacks"] = 1

        # Defender passives
        if is_distracted(a):
            if random.random() < 0.30:
                lines.append(f"😵 Distracted — shot went wide!")
                save_player(a); save_player(d)
                await send_group(update, "\n".join(lines), permanent=False, delay=15); return

        # Holy field
        if _ts_active(d, "holy_field_until"):
            reflect_dmg = get_stat(d,"WIS") * 2
            a["hp"] = max(0, a["hp"] - reflect_dmg)
            lines.append(f"✨ *Holy Field!* {reflect_dmg} reflected to attacker!")

        # Apply defense
        cls_d = get_player_class(d)
        if cls_d:
            pk_d = cls_d.get("passive_key","")
            if pk_d == "bulwark" and random.random() < 0.15:
                lines.append("🛡️ *Bulwark!* Attack completely blocked!"); dmg = 0
            if pk_d == "iron_will": dmg = round(dmg * 0.90)
            if pk_d == "devotion":
                charge = safe_int(d.get("devotion_charge"))
                d["devotion_charge"] = charge + 1

        if dmg > 0:
            dmg = calc_defense(d, dmg)

        reflect = apply_reflect(d, a, dmg)
        if reflect:
            lines.append(f"🔁 {reflect} reflected to attacker!")

        d["hp"] = max(0, d["hp"] - dmg)
        ls = apply_lifesteal(a, dmg)
        if ls: lines.append(f"🩸 +{ls} HP lifesteal.")

        lines.insert(0, f"⚔️ *{a['username']}* strikes *{d['username']}* for *{dmg} damage!*")

    # Update recent attackers on target
    update_recent_attackers(d, a["user_id"])

    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        set_status(d, "defeated_until", 21600)
        exp_loss = round(d["exp"] * 0.05); d["exp"] = max(0, d["exp"] - exp_loss)
        d["losses"] = d.get("losses",0) + 1
        a["wins"]   = a.get("wins",0) + 1
        exp_gain    = 60 + a["level"] * 8
        lmsgs, leveled = add_exp(a, exp_gain, w); lvl_msgs = lmsgs
        # Conqueror — restore 20% HP on kill
        cls_a2 = get_player_class(a)
        if cls_a2 and cls_a2.get("passive_key") == "conqueror":
            restore = round(a["max_hp"] * 0.20)
            a["hp"] = min(calc_max_hp(a), a["hp"] + restore)
            lines.append(f"⚔️ *Conqueror!* +{restore} HP on kill!")
        # Deadeye stacking bonus
        if cls_a2 and cls_a2.get("passive_key") == "dead_or_alive":
            a["deadeye_kill_bonus"] = safe_int(a.get("deadeye_kill_bonus")) + 2
            lines.append(f"🎯 *Dead or Alive!* Permanent +2 damage ceiling. Total: +{a['deadeye_kill_bonus']}")
        # Bounty check
        conn2 = sqlite3.connect(DB_PATH); c2 = conn2.cursor()
        c2.execute("SELECT * FROM bounties WHERE target_id=? AND claimed_by IS NULL AND expires_at>?",
                   (d["user_id"], datetime.now().isoformat()))
        bounty = c2.fetchone()
        if bounty:
            c2.execute("UPDATE bounties SET claimed_by=? WHERE bounty_id=?",
                       (a["user_id"], bounty[0]))
            conn2.commit()
            a["gold"] = a.get("gold",0) + 500
            placer = get_player(bounty[1])
            if placer:
                placer["gold"] = placer.get("gold",0) + 250
                save_player(placer)
            lines.append(f"💰 *Bounty claimed!* +500 gold for {a['username']}!")
        conn2.close()
        lines.append(f"\n💀 *{d['username']}* has fallen! Out for 6 hours.\n✨ +{exp_gain} EXP!")
        if leveled and a["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, update.effective_chat.id,
                f"🎉 *{a['username']}* reached *Level {a['level']}*! ⚔️", permanent=True))
    else:
        lines.append(f"❤️ {d['username']}: *{d['hp']}/{d['max_hp']} HP*")

    for t in check_titles(a): lines.append(f"🏅 *{t}*!")
    save_player(a); save_player(d)

    action = lines[0] if lines else "Attacked"
    await update_combat_card(context.bot, update.effective_chat.id, d, action,
                              finished=(d["hp"]==0))
    try: await update.message.delete()
    except: pass
    if lvl_msgs:
        await announce(context.bot, update.effective_chat.id,
                       "\n".join(lvl_msgs), permanent=False, delay=30)

# ── HEAL ──────────────────────────────────────────────────────────────────────
async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hu = update.effective_user; h = get_player(hu.id)
    if not h: await send_group(update, "Use /ascend first!"); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /heal!"); return
    tu = update.message.reply_to_message.from_user
    t  = get_player(tu.id)
    if not t: await send_group(update, f"{tu.first_name} hasn't ascended!"); return
    if is_revival_blocked(t):
        await send_group(update, f"❌ *{t['username']}* has been condemned by a Zealot — cannot be revived!"); return
    if is_healing_blocked(t):
        await send_group(update, f"❌ *{t['username']}* cannot be healed right now."); return

    inv = sjl(h.get("inventory"), [])
    potion = None; heal_amount = 0
    if "Mega Health Potion" in inv:   potion = "Mega Health Potion";  heal_amount = 200
    elif "Super Health Potion" in inv: potion = "Super Health Potion"; heal_amount = 100
    elif "Health Potion" in inv:       potion = "Health Potion";       heal_amount = 50
    else:
        await send_group(update,
            "❌ You need a Health Potion to heal someone.\n"
            "Only Priest-line classes can revive for free with /skill."); return

    inv.remove(potion); h["inventory"] = json.dumps(inv)
    wis  = get_stat(h, "WIS")
    heal = heal_amount + wis
    cls  = get_player_class(h)
    if cls and cls.get("passive_key") == "mending_aura":
        heal = round(heal * 1.25)
    was_defeated = is_defeated(t)
    t["hp"] = min(calc_max_hp(t), t["hp"] + heal)
    if was_defeated:
        t["defeated_until"] = None
        set_status(t, "invincible_until", 3600)
    h["heals_given"] = h.get("heals_given",0) + 1
    lmsgs, leveled = add_exp(h, 20)
    new_t = check_titles(h)
    save_player(h); save_player(t)
    msg = (f"💊 *{h['username']}* uses *{potion}* on *{t['username']}*! +{heal} HP\n"
           f"❤️ {t['username']}: {t['hp']}/{t['max_hp']} HP")
    if was_defeated:
        msg += f"\n✨ *{t['username']}* is revived! Invincible for 1 hour."
    if new_t: msg += f"\n🏅 *{h['username']}* earned: *{new_t[0]}*!"
    if lmsgs: msg += "\n" + "\n".join(lmsgs)
    if leveled and h["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{h['username']}* reached *Level {h['level']}*! 💊", permanent=True))
    await send_group(update, msg, permanent=False, delay=30)

# ── DAILY ─────────────────────────────────────────────────────────────────────
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not check_cooldown(p.get("last_daily"), 86400):
        await send_group(update,
            f"🎁 Daily already claimed! Come back in {time_remaining(p.get('last_daily'), 86400)}."); return
    p["last_daily"] = datetime.now().isoformat()
    gold = 50 + p["level"] * 5; p["gold"] = p.get("gold",0) + gold
    lmsgs, leveled = add_exp(p, 200)
    item_msg = ""
    if random.random() < 0.10:
        add_item(p, "Health Potion"); item_msg = "\n🎒 Lucky! Found a *Health Potion*!"
    save_player(p)
    msg = f"🎁 *Daily Reward!*\n\n✨ +200 EXP | 💰 +{gold} Gold{item_msg}\n\nCome back tomorrow!"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from daily! 🎁", permanent=True))
    await send_group(update, msg, permanent=False, delay=45)

# ── TRAIN ─────────────────────────────────────────────────────────────────────
TRAIN_MESSAGES = [
    "You spent hours drilling at the practice board.",
    "You sparred with a training dummy until your arms gave out.",
    "You ran drills across the field until your legs burned.",
    "You studied combat techniques late into the night.",
    "You meditated on your abilities and sharpened your focus.",
    "You pushed through an exhausting training session.",
    "You reviewed battle tactics and honed your instincts.",
    "You worked on your weaknesses until they became strengths.",
]
async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't train at 0 HP!"); return
    if not check_cooldown(p.get("last_train"), 1800):
        await send_group(update,
            f"⏳ Train cooldown: {time_remaining(p.get('last_train'), 1800)}"); return
    w = get_weather(); base = 80 + p["level"] * 3
    cls = get_player_class(p); bonus_msg = ""
    if cls:
        pk = cls.get("passive_key","")
        if pk in ("arcane_mind","spell_surge","arcane_mastery","mana_overload","eternal_wisdom",
                  "soul_pact","cursed_blade","undying","void_rift"):
            base = round(base*1.30); bonus_msg = f"\n🔮 INT focus bonus! +30% EXP."
        elif pk in ("iron_will","holy_stance","devotion","bulwark","divine_judgment",
                    "bloodlust","warcry","unbreakable","conqueror"):
            base = round(base*1.20); bonus_msg = f"\n🛡️ Endurance bonus! +20% EXP."
        elif pk in ("quick_hands","evasion","shadowstep","ghost_form","deaths_shadow",
                    "marked","execute","flurry","the_professional",
                    "eagle_eye","trailblazer","natures_bond","guardian_stance","pathfinder",
                    "marked_for_death","steady_aim","headshot","dead_or_alive"):
            base = round(base*1.35); bonus_msg = f"\n⚡ Speed bonus! +35% EXP."
        elif pk in ("mending_aura","divine_grace","sacred_ground","resurrection","divine_presence",
                    "dark_sense","purge","judgement","wrath_of_the_righteous"):
            base = round(base*1.15); bonus_msg = f"\n✨ Wisdom bonus! +15% EXP."
    p["last_train"] = datetime.now().isoformat()
    lmsgs, leveled = add_exp(p, base, w); save_player(p)
    flavor = random.choice(TRAIN_MESSAGES)
    msg = f"🏋️ *Training Session*\n\n_{flavor}_\n\n✨ +{base} EXP{bonus_msg}"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from training! 🏋️", permanent=True))
    await send_group(update, msg, permanent=False, delay=30)

# ── QUEST ─────────────────────────────────────────────────────────────────────
async def quest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't quest at 0 HP!"); return
    if not check_cooldown(p.get("last_quest"), 3600):
        await send_group(update,
            f"⏳ Quest cooldown: {time_remaining(p.get('last_quest'), 3600)}"); return
    w = get_weather()
    if p["level"] <= 5:    pool = [q for q in SOLO_QUESTS if q["tier"]=="Easy"]
    elif p["level"] <= 15: pool = [q for q in SOLO_QUESTS if q["tier"] in ("Easy","Medium")]
    else:                  pool = SOLO_QUESTS
    if not pool: pool = SOLO_QUESTS
    q = random.choice(pool)
    p["last_quest"] = datetime.now().isoformat()
    p["gold"] = p.get("gold",0) + q["gold"]; p["quests_done"] = p.get("quests_done",0) + 1
    item_gained = roll_loot_table(q["loot_table"])
    if item_gained: add_item(p, item_gained)
    lmsgs, leveled = add_exp(p, q["exp"], w)
    new_t = check_titles(p); save_player(p)
    msg = f"🗺️ *Quest — {q['tier']}*\n\n{q['text']}\n\n✨ +{q['exp']} EXP | 💰 +{q['gold']} Gold"
    if item_gained:
        rarity = ""
        for pool2 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
            if item_gained in pool2:
                r = pool2[item_gained].get("rarity","")
                rarity = RARITY_EMOJI.get(r,"")
                break
        msg += f"\n🎒 Found: {rarity} *{item_gained}*!"
    if new_t: msg += f"\n🏅 New title: *{new_t[0]}*!"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from a quest! 🗺️", permanent=True))
    await send_group(update, msg, permanent=False, delay=45)

# ── EXPLORE ───────────────────────────────────────────────────────────────────
async def explore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't explore at 0 HP!"); return
    today = datetime.now().strftime("%Y-%m-%d")
    if p.get("explore_date") == today and safe_int(p.get("explore_count_today")) >= 2:
        await send_group(update, "🗺️ You've done 2 expeditions today. Rest up and try tomorrow!"); return
    if p.get("explore_date") != today:
        p["explore_date"] = today; p["explore_count_today"] = 0
    if p.get("last_explore"):
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(p["last_explore"])).total_seconds()
            if elapsed < 3600:
                remaining = 3600 - elapsed
                mins = int(remaining // 60); secs = int(remaining % 60)
                await send_group(update, f"⏳ Expedition in progress! Returns in {mins}m {secs}s."); return
        except Exception:
            pass
    if p["level"] <= 5:    elig = [EXPLORE_ZONES[0]]
    elif p["level"] <= 15: elig = EXPLORE_ZONES[:3]
    elif p["level"] <= 40: elig = EXPLORE_ZONES[:4]
    else:                  elig = EXPLORE_ZONES
    zone = random.choice(elig)
    p["last_explore"]       = datetime.now().isoformat()
    p["explore_count_today"] = safe_int(p.get("explore_count_today")) + 1
    save_player(p)
    await send_group(update,
        f"🗺️ *{p['username']}* sets out for *{zone['name']}*!\n"
        f"_{zone['tier']} expedition — results in 1 hour._\n\n"
        f"Expedition {p['explore_count_today']}/2 used today.",
        permanent=False, delay=30)
    # Schedule result delivery after 1 hour
    async def deliver_results():
        await asyncio.sleep(3600)
        pp = get_player(user.id)
        if not pp: return
        w = get_weather()
        success_roll = random.random()
        success_threshold = {"Easy":0.85,"Medium":0.65,"Hard":0.45,"Elite":0.25,"Legendary":0.15}
        threshold = success_threshold.get(zone["tier"], 0.60)
        if success_roll < threshold:
            exp = round(zone["exp"] * w.get("exp_mod",1.0))
            pp["gold"] = pp.get("gold",0) + zone["gold"]
            item_found = roll_loot_table(zone["loot_table"])
            if item_found: add_item(pp, item_found)
            lmsgs, leveled = add_exp(pp, exp)
            save_player(pp)
            rarity_tag = ""
            if item_found:
                for pool3 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
                    if item_found in pool3:
                        r = pool3[item_found].get("rarity","")
                        rarity_tag = RARITY_EMOJI.get(r,"")
                        break
            msg = (f"🗺️ *Expedition Complete — {zone['name']}!*\n\n"
                   f"✅ *{p['username']}* returns victorious!\n"
                   f"✨ +{exp} EXP | 💰 +{zone['gold']} Gold")
            if item_found: msg += f"\n🎒 Found: {rarity_tag} *{item_found}*!"
            if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
            if leveled and pp["level"] % 10 == 0:
                await announce(context.bot, update.effective_chat.id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}* from exploring! 🗺️",
                    permanent=True)
        else:
            cons = random.randint(5,30)
            pp["gold"] = pp.get("gold",0) + cons; save_player(pp)
            msg = (f"🗺️ *Expedition Failed — {zone['name']}*\n\n"
                   f"❌ *{p['username']}* {zone['fail_msg']}\n💰 +{cons} gold consolation.")
        await announce(context.bot, update.effective_chat.id, msg, permanent=True)
    asyncio.create_task(deliver_results())

# ── SHOP ──────────────────────────────────────────────────────────────────────
async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    discount = 0
    if _ts_active(p, "shop_discount_until"): discount = 0.20
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            if glvl >= 10: discount = max(discount, 0.15)
            elif glvl >= 7: discount = max(discount, 0.10)
    if not context.args:
        shop = get_daily_shop()
        lines = [f"🛒 *Daily Shop* | 💰 You have {p['gold']} gold\n"]
        if discount: lines.append(f"💸 Discount active: *{int(discount*100)}% off!*\n")
        for i, entry in enumerate(shop, 1):
            price = round(entry["price"] * (1 - discount))
            lines.append(f"{i}. *{entry['item']}* — {price}g\n   _{entry['desc']}_")
        lines.append("\n`/shop buy [1-5]` to purchase.")
        await send_group(update, "\n".join(lines), permanent=False, delay=30); return
    if context.args[0].lower() == "buy":
        if len(context.args) < 2: await send_group(update, "Usage: /shop buy [1-5]"); return
        try: idx = int(context.args[1]) - 1
        except: await send_group(update, "Usage: /shop buy [1-5]"); return
        shop = get_daily_shop()
        if idx < 0 or idx >= len(shop): await send_group(update, "Invalid number."); return
        entry = shop[idx]; price = round(entry["price"] * (1 - discount))
        if p["gold"] < price:
            await send_group(update, f"❌ Need {price}g, have {p['gold']}g."); return
        p["gold"] -= price; add_item(p, entry["item"]); save_player(p)
        await send_group(update, f"✅ Bought *{entry['item']}* for {price}g! 💰 Remaining: {p['gold']}g",
                         permanent=False, delay=15)

# ── INVENTORY ─────────────────────────────────────────────────────────────────
async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    inv = Counter(sjl(p.get("inventory"), []))
    if not inv: await send_group(update, "🎒 Your inventory is empty!"); return
    lines = [f"🎒 *{p['username']}'s Inventory:*\n"]
    for item, count in inv.items():
        desc = ""
        for pool4 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
            if item in pool4:
                d = pool4[item]
                rarity = d.get("rarity","")
                emoji  = RARITY_EMOJI.get(rarity,"")
                if "atk" in d:   desc = f"+{d['atk']} ATK"
                elif "def" in d: desc = f"+{d['def']} DEF"
                elif "desc" in d: desc = d["desc"]
                lines.append(f"{emoji} *{item}* x{count} — {desc}")
                break
        else:
            lines.append(f"• *{item}* x{count}")
    await send_group(update, "\n".join(lines), permanent=False, delay=30)

# ── EQUIP ─────────────────────────────────────────────────────────────────────
async def equip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args: await send_group(update, "Usage: /equip [item name]"); return
    item_name = " ".join(context.args)
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await send_group(update, f"You don't have *{item_name}* in your inventory."); return
    if item_name in WEAPONS:
        ok, err = can_equip_weapon(p, item_name)
        if not ok: await send_group(update, f"❌ {err}"); return
        p["equipped_weapon"] = item_name
        await send_group(update, f"⚔️ Equipped *{item_name}*! +{WEAPONS[item_name]['atk']} ATK")
    elif item_name in ARMORS:
        ok, err = can_equip_armor(p, item_name)
        if not ok: await send_group(update, f"❌ {err}"); return
        p["equipped_armor"] = item_name
        await send_group(update, f"🛡️ Equipped *{item_name}*! +{ARMORS[item_name]['def']} DEF")
    elif item_name in SHIELDS:
        if get_class_line(p) != "warrior" or p.get("class_path") != "A":
            await send_group(update, "❌ Only Warrior Path A can equip shields."); return
        p["equipped_shield"] = item_name
        await send_group(update, f"🔰 Equipped *{item_name}*! +{SHIELDS[item_name]['def']} DEF")
    elif item_name in ACCESSORIES:
        p["equipped_accessory"] = item_name
        eff = ACCESSORIES[item_name].get("desc","")
        await send_group(update, f"💍 Equipped *{item_name}*! {eff}")
    else:
        await send_group(update, f"*{item_name}* is not equippable."); return
    save_player(p)

# ── SELL ──────────────────────────────────────────────────────────────────────
async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args: await send_group(update, "Usage: /sell [item name]"); return
    item_name = " ".join(context.args)
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await send_group(update, f"You don't have *{item_name}*."); return
    sell_price = 0
    for pool5 in [CONSUMABLES]:
        if item_name in pool5:
            sell_price = pool5[item_name].get("sell", 10); break
    if sell_price == 0:
        for pool6, base in [(WEAPONS,"atk"),(ARMORS,"def"),(SHIELDS,"def")]:
            if item_name in pool6:
                val = pool6[item_name].get(base, 10)
                sell_price = round(val * 5); break
    if sell_price == 0:
        if item_name in ACCESSORIES:
            rarity = ACCESSORIES[item_name].get("rarity","common")
            rarity_val = {"common":50,"uncommon":150,"rare":400,"epic":1000,"legendary":3000}
            sell_price = rarity_val.get(rarity,50)
    inv.remove(item_name); p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold",0) + sell_price; save_player(p)
    await send_group(update, f"💰 Sold *{item_name}* for *{sell_price}g*! Total: {p['gold']}g",
                     permanent=False, delay=15)

# ── ALLOCATE ──────────────────────────────────────────────────────────────────
async def allocate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    sp = safe_int(p.get("stat_points")); sd = safe_stats(p)
    STAT_NAMES = ["STR","DEF","AGI","INT","WIS"]
    if not context.args or len(context.args) < 2:
        cls = get_player_class(p)
        rec = cls.get("recommended","Free to allocate") if cls else "Free to allocate"
        primary = get_primary_stat(p)
        await send_group(update,
            f"📊 *Stat Allocation* — *{sp} points available*\n\n"
            f"STR:{sd['STR']} DEF:{sd['DEF']} AGI:{sd['AGI']} INT:{sd['INT']} WIS:{sd['WIS']}\n\n"
            f"📌 STR — Base damage\n📌 DEF — Damage reduction\n"
            f"📌 AGI — Dodge & crit chance\n📌 INT — Spell damage\n📌 WIS — Heal power\n\n"
            f"🎯 Primary stat: *{primary}*\n"
            f"🧭 Recommended: _{rec}_\n\n"
            f"Usage: `/allocate STR 5`", permanent=False, delay=30); return
    stat = context.args[0].upper()
    if stat not in STAT_NAMES:
        await send_group(update, f"Unknown stat. Choose: {', '.join(STAT_NAMES)}"); return
    try: amount = int(context.args[1])
    except: await send_group(update, "Usage: /allocate STR 5"); return
    if amount <= 0: await send_group(update, "Amount must be positive."); return
    if amount > sp: await send_group(update, f"Not enough points! You have {sp}."); return
    sd[stat] = sd.get(stat,5) + amount
    p["stats"] = json.dumps(sd); p["stat_points"] = sp - amount
    save_player(p)
    await send_group(update,
        f"✅ +{amount} to *{stat}*! Now {sd[stat]} total.\n💡 {p['stat_points']} points remaining.",
        permanent=False, delay=15)

# ── TITLE ─────────────────────────────────────────────────────────────────────
async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    titles = safe_titles(p)
    if not context.args:
        await send_group(update,
            f"🏅 *Your Titles:*\n" + "\n".join(f"• {t}" for t in titles) +
            "\n\nUse `/title [name]` to equip.", permanent=False, delay=30); return
    chosen = " ".join(context.args)
    if chosen not in titles:
        await send_group(update, f"You haven't earned *{chosen}* yet!"); return
    p["active_title"] = chosen; save_player(p)
    await send_group(update, f"🏅 Title set to *{chosen}*!", permanent=False, delay=15)

# ── COOLDOWNS ─────────────────────────────────────────────────────────────────
async def cooldowns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    today = datetime.now().strftime("%Y-%m-%d")
    explores_left = 2 - safe_int(p.get("explore_count_today")) \
        if p.get("explore_date") == today else 2
    lines = [
        f"⏳ *{p['username']}'s Cooldowns:*\n",
        f"🎁 Daily:    {time_remaining(p.get('last_daily'), 86400)}",
        f"🗺️ Quest:    {time_remaining(p.get('last_quest'), 3600)}",
        f"🏋️ Train:    {time_remaining(p.get('last_train'), 1800)}",
        f"🧭 Explore:  {time_remaining(p.get('last_explore'), 3600)} ({explores_left}/2 remaining today)",
    ]
    if is_defeated(p):
        end = p["defeated_until"]
        try:
            diff = datetime.fromisoformat(end) - datetime.now()
            h, m = divmod(int(diff.total_seconds()//60), 60)
            lines.append(f"💀 Defeated: {h}h {m}m remaining")
        except: pass
    await send_group(update, "\n".join(lines), permanent=False, delay=20)

# ── WEATHER ───────────────────────────────────────────────────────────────────
async def weather_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    w = get_weather()
    hint = "\n🌑 _Something stirs in the shadows..._" if w.get("secret_eligible") else ""
    await send_group(update,
        f"🌦️ *Table Conditions: {w['name']}*\n_{w['desc']}_\n\n"
        f"📈 EXP: x{w['exp_mod']} | ⚔️ DMG: x{w['dmg_mod']}{hint}",
        permanent=False, delay=20)

# ── BOSS ──────────────────────────────────────────────────────────────────────
async def boss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't fight at 0 HP!"); return
    if chat_id in active_bosses:
        boss = active_bosses[chat_id]
        if user.id in [u["id"] for u in boss["participants"]]:
            await send_group(update, f"You're already fighting *{boss['data']['name']}*!"); return
        boss["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        await send_group(update,
            f"⚔️ *{user.first_name}* joins the fight!\n"
            f"❤️ Boss HP: {boss['hp']}/{boss['data']['max_hp']}\nUse /strike!",
            permanent=False, delay=30); return
    if not context.args:
        bl = "\n".join(f"• `{k}` — {v['name']} (HP: {v['max_hp']})"
                       for k,v in BOSSES.items() if not v.get("secret"))
        await send_group(update, f"⚔️ *Available Bosses:*\n{bl}\n\nExample: `/boss 1 ball`",
                         permanent=False, delay=30); return
    key = " ".join(context.args).lower(); bd = BOSSES.get(key)
    if not bd or bd.get("secret"):
        await send_group(update, "Unknown boss!"); return
    active_bosses[chat_id] = {
        "data": bd.copy(), "hp": bd["max_hp"],
        "participants": [{"id":user.id,"name":user.first_name,"dmg":0}]
    }
    await send_group(update,
        f"🎱 *{bd['name']} HAS APPEARED!*\n\n_{bd['desc']}_\n\n"
        f"❤️ HP: {bd['max_hp']} | 💀 {bd['dmg_min']}–{bd['dmg_max']} dmg\n\n"
        f"*{user.first_name}* engaged! Others type `/boss {key}` to join.\n"
        f"All: use /strike to attack!",
        permanent=True)

# ── STRIKE ────────────────────────────────────────────────────────────────────
async def strike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't strike at 0 HP!"); return
    boss_dict = active_bosses.get(chat_id) or secret_boss_active.get(chat_id)
    if not boss_dict: await send_group(update, "No active boss! Use /boss."); return
    is_secret = chat_id in secret_boss_active
    participant = next((u for u in boss_dict["participants"] if u["id"]==user.id), None)
    if not participant:
        boss_dict["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        participant = boss_dict["participants"][-1]
    w   = get_weather()
    dmg = calc_attack_damage(p, w)
    # Check crit
    if check_crit(p): dmg = apply_crit(p, dmg); 
    boss_dict["hp"] = max(0, boss_dict["hp"] - dmg)
    participant["dmg"] += dmg
    lines = [
        f"⚔️ *{user.first_name}* strikes *{boss_dict['data']['name']}* for *{dmg}!*",
        f"❤️ Boss HP: {boss_dict['hp']}/{boss_dict['data']['max_hp']}"
    ]
    # Boss counter-attack
    if random.random() < 0.80 and boss_dict["hp"] > 0:
        target = random.choice(boss_dict["participants"])
        tp = get_player(target["id"])
        if tp and not is_defeated(tp):
            bdmg = calc_defense(tp, random.randint(
                boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"]))
            tp["hp"] = max(0, tp["hp"] - bdmg)
            if tp["hp"] == 0:
                set_status(tp, "defeated_until", 21600)
                lines.append(f"💀 *{boss_dict['data']['name']}* kills *{target['name']}*! Out 6 hours.")
                # Check if all participants defeated
                all_defeated = all(
                    is_defeated(get_player(u["id"]) or {"hp":0,"defeated_until":"9999"})
                    for u in boss_dict["participants"])
                if all_defeated:
                    lines.append(f"💀 *All fighters defeated!* The boss remains at {boss_dict['hp']} HP.")
                    if is_secret: secret_boss_active.pop(chat_id,None)
                    else:         active_bosses.pop(chat_id,None)
                    save_player(tp); save_player(p)
                    await send_group(update, "\n".join(lines), permanent=True); return
            else:
                lines.append(f"💀 *{boss_dict['data']['name']}* hits *{target['name']}* for {bdmg}!")
            save_player(tp)
    if boss_dict["hp"] <= 0:
        data = boss_dict["data"]
        if is_secret: secret_boss_active.pop(chat_id,None)
        else:         active_bosses.pop(chat_id,None)
        lines.append(f"\n🏆 *{data['name']} DEFEATED!*\n")
        w2 = get_weather()
        for u in boss_dict["participants"]:
            pp = get_player(u["id"])
            if not pp: continue
            pp["gold"] = pp.get("gold",0) + data["gold"]
            pp["quests_done"] = pp.get("quests_done",0) + 1
            loot = roll_loot_table(data.get("loot_table",[]))
            if loot:
                add_item(pp, loot)
                rarity = ""
                for pool7 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
                    if loot in pool7:
                        r = pool7[loot].get("rarity","")
                        rarity = RARITY_EMOJI.get(r,"")
                        break
                lines.append(f"🎒 *{pp['username']}* found: {rarity} *{loot}*!")
            if award_title(pp, data["title"]): lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
            lmsgs, leveled = add_exp(pp, data["exp"], w2)
            lines.append(f"✅ *{pp['username']}* — +{data['exp']} EXP | +{data['gold']} Gold")
            lines.extend(lmsgs)
            if leveled and pp["level"] % 10 == 0:
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}*! 🏆", permanent=True))
            save_player(pp)
    save_player(p)
    await send_group(update, "\n".join(lines), permanent=False, delay=30)

# ── GUILD ─────────────────────────────────────────────────────────────────────
async def guild_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args:
        await send_group(update,
            "🏰 *Guild Commands:*\n"
            "/guild create [name] — 100 gold\n"
            "/guild join [name]\n/guild approve [name]\n/guild deny [name]\n"
            "/guild info\n/guild list\n/guild bank [amount]\n/guild leave",
            permanent=False, delay=20); return
    sub = context.args[0].lower()
    if sub == "create":
        if len(context.args) < 2: await send_group(update, "Usage: /guild create [name]"); return
        if p.get("guild_id") and str(p.get("guild_id")) != "None":
            await send_group(update, "You're already in a guild!"); return
        if p.get("gold",0) < 100: await send_group(update, "Need 100 gold!"); return
        name = " ".join(context.args[1:])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        try:
            c.execute("INSERT INTO guilds (name,leader_id,members,level,exp,bank) VALUES(?,?,?,1,0,0)",
                      (name, user.id, json.dumps([user.id])))
            conn.commit(); gid = c.lastrowid
        except sqlite3.IntegrityError:
            await send_group(update, f"Guild '{name}' already exists!"); conn.close(); return
        conn.close()
        p["guild_id"] = gid; p["gold"] = p.get("gold",0) - 100
        award_title(p,"Guild Founder"); save_player(p)
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🏰 *{name}* guild founded by *{user.first_name}*!"))
        await send_group(update, f"🏰 *{name}* founded!\n🏅 Title: *Guild Founder*!",
                         permanent=False, delay=20)
    elif sub == "join":
        if len(context.args) < 2: await send_group(update, "Usage: /guild join [name]"); return
        if p.get("guild_id") and str(p.get("guild_id")) != "None":
            await send_group(update, "You're already in a guild!"); return
        name = " ".join(context.args[1:]); g = get_guild_by_name(name)
        if not g: await send_group(update, f"No guild named *{name}*."); return
        gid = g["guild_id"]
        if gid not in pending_guild_reqs: pending_guild_reqs[gid] = []
        if any(r["user_id"]==user.id for r in pending_guild_reqs[gid]):
            await send_group(update, "Request already pending."); return
        pending_guild_reqs[gid].append({"user_id":user.id,"username":user.first_name})
        leader = get_player(g["leader_id"])
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                text=f"🏰 *Guild Join Request*\n*{user.first_name}* wants to join *{g['name']}*!\n"
                     f"Leader *{leader['username'] if leader else '?'}*: "
                     f"`/guild approve {user.first_name}` or `/guild deny {user.first_name}`",
                parse_mode="Markdown")
        except Exception: pass
        await send_group(update, f"📨 Request sent to join *{g['name']}*!", permanent=False, delay=15)
    elif sub == "approve":
        if len(context.args) < 2: await send_group(update, "Usage: /guild approve [username]"); return
        if not p.get("guild_id") or str(p.get("guild_id"))=="None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if not g or g["leader_id"] != user.id:
            await send_group(update, "Only the guild leader can approve."); return
        tn = " ".join(context.args[1:]).lower(); gid = g["guild_id"]
        reqs = pending_guild_reqs.get(gid,[])
        match = next((r for r in reqs if r["username"].lower()==tn), None)
        if not match: await send_group(update, f"No request from *{tn}*."); return
        tp = get_player(match["user_id"])
        if not tp: await send_group(update, "Player not found."); return
        members = sjl(g["members"],[]); members.append(match["user_id"])
        g["members"] = json.dumps(members); save_guild(g)
        tp["guild_id"] = gid; save_player(tp)
        pending_guild_reqs[gid] = [r for r in reqs if r["user_id"]!=match["user_id"]]
        await send_group(update, f"✅ *{match['username']}* joined *{g['name']}*!",
                         permanent=False, delay=15)
    elif sub == "deny":
        if len(context.args) < 2: await send_group(update, "Usage: /guild deny [username]"); return
        if not p.get("guild_id") or str(p.get("guild_id"))=="None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if not g or g["leader_id"] != user.id:
            await send_group(update, "Only the guild leader can deny."); return
        tn = " ".join(context.args[1:]).lower(); gid = g["guild_id"]
        reqs = pending_guild_reqs.get(gid,[])
        match = next((r for r in reqs if r["username"].lower()==tn), None)
        if not match: await send_group(update, f"No request from *{tn}*."); return
        pending_guild_reqs[gid] = [r for r in reqs if r["user_id"]!=match["user_id"]]
        await send_group(update, f"❌ *{match['username']}*'s request denied.", permanent=False, delay=15)
    elif sub == "info":
        if not p.get("guild_id") or str(p.get("guild_id"))=="None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if not g: await send_group(update, "Guild not found."); return
        members = sjl(g["members"],[]); leader = get_player(g["leader_id"])
        glvl = safe_int(g.get("level"),1); perk = GUILD_PERKS.get(glvl,{})
        nxt = guild_exp_for_level(glvl) if glvl < 10 else "MAX"
        await send_group(update,
            f"🏰 *{g['name']}*\n👑 Leader: {leader['username'] if leader else '?'}\n"
            f"👥 Members: {len(members)}\n⭐ Level: {glvl}/10 | EXP: {safe_int(g.get('exp'))}/{nxt}\n"
            f"💰 Bank: {safe_int(g.get('bank'))}g\n🎁 Perks: _{perk.get('desc','None')}_",
            permanent=True)
    elif sub == "bank":
        if len(context.args) < 2: await send_group(update, "Usage: /guild bank [amount]"); return
        if not p.get("guild_id") or str(p.get("guild_id"))=="None":
            await send_group(update, "You're not in a guild!"); return
        try: amount = int(context.args[1])
        except: await send_group(update, "Usage: /guild bank [amount]"); return
        if amount <= 0 or p.get("gold",0) < amount:
            await send_group(update, f"Not enough gold! Have {p.get('gold',0)}g."); return
        g = get_guild(p["guild_id"])
        if not g: await send_group(update, "Guild not found."); return
        p["gold"] = p.get("gold",0) - amount
        g["bank"] = safe_int(g.get("bank")) + amount
        gmsgs = add_guild_exp(g, amount//10); save_guild(g); save_player(p)
        msg = f"💰 *{user.first_name}* donated {amount}g! Bank: {g['bank']}g"
        if gmsgs: msg += "\n" + "\n".join(gmsgs)
        await send_group(update, msg, permanent=False, delay=15)
    elif sub == "list":
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT name,level,exp,members FROM guilds ORDER BY level DESC,exp DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows: await send_group(update, "No guilds yet!", permanent=False); return
        medals2 = ["🥇","🥈","🥉"] + ["🏰"]*7
        lines = ["🏰 *Guild Leaderboard:*\n"]
        for i, row in enumerate(rows):
            mcount = len(sjl(row["members"],[]))
            lines.append(f"{medals2[i]} *{row['name']}* — Lv {safe_int(row['level'],1)} | {mcount} members")
        await send_group(update, "\n".join(lines), permanent=False, delay=30)
    elif sub == "leave":
        if not p.get("guild_id") or str(p.get("guild_id"))=="None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if g and g["leader_id"] == user.id:
            await send_group(update, "Guild leaders can't leave!"); return
        if g:
            members = sjl(g["members"],[])
            if user.id in members: members.remove(user.id)
            g["members"] = json.dumps(members); save_guild(g)
        p["guild_id"] = None; save_player(p)
        await send_group(update, "You've left your guild.", permanent=False, delay=15)

# ── RAID ──────────────────────────────────────────────────────────────────────
async def raid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 Can't raid at 0 HP!"); return
    if chat_id in active_raids:
        raid = active_raids[chat_id]
        if raid.get("in_progress"): await send_group(update, "Raid in progress! Use /raidstrike."); return
        if user.id in [u["id"] for u in raid["party"]]:
            await send_group(update, f"Already in party! ({len(raid['party'])} players)\nUse /raidstart."); return
        raid["party"].append({"id":user.id,"name":user.first_name})
        await send_group(update, f"⚔️ *{user.first_name}* joins! ({len(raid['party'])} players)",
                         permanent=False, delay=20); return
    active_raids[chat_id] = {"party":[{"id":user.id,"name":user.first_name}],
                              "in_progress":False,"wave":0,"tier":None,"enemy":None,"enemy_hp":0}
    await send_group(update,
        f"🏰 *RAID LOBBY!*\n\n*{user.first_name}* is forming a party.\nOthers: /raid to join (min 2)\nLeader: /raidstart when ready.",
        permanent=True)

async def raidstart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; chat_id = update.effective_chat.id
    if chat_id not in active_raids: await send_group(update, "No raid lobby! Use /raid."); return
    raid = active_raids[chat_id]
    if raid.get("in_progress"): await send_group(update, "Raid already started!"); return
    if len(raid["party"]) < 2: await send_group(update, f"Need at least 2 players! Have {len(raid['party'])}."); return
    levels = [get_player(u["id"])["level"] for u in raid["party"] if get_player(u["id"])]
    avg = sum(levels)/len(levels) if levels else 1
    eligible = [t for t in RAID_TIERS if t["min_level"] <= avg]
    tier = eligible[-1] if eligible else RAID_TIERS[0]
    raid["tier"] = tier; raid["in_progress"] = True; raid["wave"] = 1
    fe = tier["wave_enemies"][0].copy()
    raid["enemy"] = fe; raid["enemy_hp"] = fe["hp"]; raid["enemy_max_hp"] = fe["hp"]
    names = ", ".join(u["name"] for u in raid["party"])
    await send_group(update,
        f"⚔️ *RAID — {tier['name']}*\n👥 {names}\n📊 Avg Lv: {avg:.0f}\n\n"
        f"🌊 *Wave 1 — {fe['name']}*\n❤️ HP: {fe['hp']} | 💀 {fe['dmg_min']}–{fe['dmg_max']}\n\nUse /raidstrike!",
        permanent=True)

async def raidstrike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if chat_id not in active_raids: await send_group(update, "No active raid!"); return
    raid = active_raids[chat_id]
    if not raid.get("in_progress"): await send_group(update, "Raid not started! Use /raidstart."); return
    if user.id not in [u["id"] for u in raid["party"]]: await send_group(update, "You're not in this raid!"); return
    if is_defeated(p): await send_group(update, "💀 Can't strike at 0 HP!"); return
    w = get_weather(); dmg = calc_attack_damage(p, w)
    if check_crit(p): dmg = apply_crit(p, dmg)
    enemy = raid["enemy"]; raid["enemy_hp"] = max(0, raid["enemy_hp"] - dmg)
    lines = [f"⚔️ *{user.first_name}* strikes *{enemy['name']}* for *{dmg}!*",
             f"❤️ HP: {raid['enemy_hp']}/{raid['enemy_max_hp']}"]
    alive = [u for u in raid["party"] if not is_defeated(get_player(u["id"]) or {"hp":0,"defeated_until":"9999"})]
    if alive and raid["enemy_hp"] > 0 and random.random() < 0.65:
        target = random.choice(alive); tp = get_player(target["id"])
        if tp:
            edm = calc_defense(tp, random.randint(enemy["dmg_min"],enemy["dmg_max"]))
            tp["hp"] = max(0, tp["hp"]-edm)
            if tp["hp"] == 0: set_status(tp, "defeated_until", 7200)
            save_player(tp)
            lines.append(f"🩸 *{enemy['name']}* hits *{target['name']}* for {edm}! ({tp['hp']}/{tp['max_hp']} HP)")
    if raid["enemy_hp"] <= 0:
        tier = raid["tier"]; wave_enemies = tier["wave_enemies"]; cw = raid["wave"]
        lines.append(f"\n✅ *Wave {cw} cleared!*")
        if cw < len(wave_enemies):
            raid["wave"] += 1; ne = wave_enemies[cw].copy()
            raid["enemy"] = ne; raid["enemy_hp"] = ne["hp"]; raid["enemy_max_hp"] = ne["hp"]
            lines.append(f"\n🌊 *Wave {raid['wave']} — {ne['name']}*\n❤️ HP: {ne['hp']}")
        elif cw == len(wave_enemies):
            bd = BOSSES[tier["wave_boss_key"]]
            rbhp = round(bd["max_hp"]*0.5*len(raid["party"]))
            raid["wave"] = len(wave_enemies)+1
            raid["enemy"] = {"name":bd["name"]+" ⚡",
                             "dmg_min":round(bd["dmg_min"]*0.6),"dmg_max":round(bd["dmg_max"]*0.6)}
            raid["enemy_hp"] = rbhp; raid["enemy_max_hp"] = rbhp
            lines.append(f"\n🎱 *FINAL BOSS — {bd['name']}!*\n❤️ HP: {rbhp}")
        else:
            lines.append(f"\n🏆 *RAID COMPLETE — {tier['name']}!*\n")
            active_raids.pop(chat_id,None)
            w2 = get_weather()
            for u in raid["party"]:
                pp = get_player(u["id"])
                if not pp: continue
                pp["gold"] = pp.get("gold",0) + tier["gold_reward"]
                pp["quests_done"] = pp.get("quests_done",0) + 1
                loot = roll_loot_table(tier["loot_table"])
                if loot:
                    add_item(pp, loot)
                    rarity8 = ""
                    for pool8 in [WEAPONS,ARMORS,ACCESSORIES,CONSUMABLES]:
                        if loot in pool8:
                            r8 = pool8[loot].get("rarity","")
                            rarity8 = RARITY_EMOJI.get(r8,"")
                            break
                    lines.append(f"🎒 *{pp['username']}* found: {rarity8} *{loot}*!")
                if u == raid["party"][0] and award_title(pp,"Raid Leader"):
                    lines.append(f"🏅 *{pp['username']}* earned: *Raid Leader*!")
                lmsgs, leveled = add_exp(pp, tier["exp_reward"], w2); save_player(pp)
                lines.append(f"✅ *{pp['username']}* — +{tier['exp_reward']} EXP | +{tier['gold_reward']} Gold")
                lines.extend(lmsgs)
                if leveled and pp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{pp['username']}* reached *Level {pp['level']}* from raid! 🏰", permanent=True))
    save_player(p)
    await send_group(update, "\n".join(lines), permanent=False, delay=30)

async def raidstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in active_raids: await send_group(update, "No active raid."); return
    raid = active_raids[chat_id]
    if not raid.get("in_progress"):
        names = ", ".join(u["name"] for u in raid["party"])
        await send_group(update, f"🏰 *Raid Lobby* — {len(raid['party'])} players: {names}\nUse /raidstart.",
                         permanent=False, delay=20); return
    tier = raid["tier"]; enemy = raid["enemy"]
    names = ", ".join(u["name"] for u in raid["party"])
    await send_group(update,
        f"⚔️ *{tier['name']}*\n👥 {names}\n"
        f"🌊 Wave {raid['wave']}/{len(tier['wave_enemies'])+1} — *{enemy['name']}*\n"
        f"❤️ HP: {raid['enemy_hp']}/{raid['enemy_max_hp']}",
        permanent=False, delay=20)

# ── RANDOM EVENTS ─────────────────────────────────────────────────────────────
async def greet_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] not in ("traveler","merchant","shrine"): return
    s = get_or_create_shadow(user.id, user.first_name); p = get_player(user.id)
    if event["key"] == "merchant":
        if p:
            set_status(p, "shop_discount_until", 1800); save_player(p)
            await send_group(update, f"🛍️ *{user.first_name}* greeted the merchant! 20% shop discount for 30 min!",
                             permanent=False, delay=30)
        active_events.pop(chat_id, None); return
    if event["key"] == "shrine":
        if p:
            stat_choices = ["STR","DEF","AGI","INT","WIS"]
            chosen_stat = random.choice(stat_choices)
            sd = safe_stats(p); sd[chosen_stat] = sd.get(chosen_stat,5) + 3
            p["stats"] = json.dumps(sd); save_player(p)
            await send_group(update, f"🔮 *{user.first_name}* prayed at the shrine! +3 {chosen_stat} for 2 hours!",
                             permanent=False, delay=30)
        active_events.pop(chat_id, None); return
    loot = roll_loot_table(event["loot_table"]); active_events.pop(chat_id, None)
    if p:
        if loot: add_item(p, loot)
        lmsgs, leveled = add_exp(p, event["exp"]); save_player(p)
        msg = f"🧙 *{user.first_name}* greets the traveler! +{event['exp']} EXP"
        if loot: msg += f" + *{loot}*!"
        if lmsgs: msg += "\n" + "\n".join(lmsgs)
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}*! 🧙", permanent=True))
        await send_group(update, msg, permanent=False, delay=20)
    else:
        lmsgs, leveled = add_shadow_exp(s, event["exp"]); save_shadow(s)
        await send_group(update, f"🧙 *{user.first_name}* greets the traveler! +{event['exp']} EXP",
                         permanent=False, delay=20)

async def fight_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "bandit": return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(10,30); event["enemy_hp"] -= dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"🗡️ *{user.first_name}* strikes the bandit for {dmg}! (HP: {max(0,event['enemy_hp'])}/150)"]
    if event["enemy_hp"] <= 0:
        fighters = event.get("fighters",[user.id]); active_events.pop(chat_id,None)
        loot = roll_loot_table(event.get("loot_table",[]))
        lines.append(f"💀 *Bandit defeated!* All fighters earn +{event['exp_reward']} EXP!")
        for fid in fighters:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp:
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, event["exp_reward"]); save_player(fp)
                lines.extend(lmsgs)
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}*! ⚔️", permanent=True))
            elif fs:
                add_shadow_exp(fs, event["exp_reward"]); save_shadow(fs)
    await send_group(update, "\n".join(lines), permanent=False, delay=30)

async def shoot_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "ghost": return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(15,35); event["enemy_hp"] -= dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"👻 *{user.first_name}* shoots the ghost for {dmg}! (HP: {max(0,event['enemy_hp'])}/200)"]
    if event["enemy_hp"] <= 0:
        fighters = event.get("fighters",[user.id]); active_events.pop(chat_id,None)
        loot = roll_loot_table(event.get("loot_table",[]))
        lines.append(f"✨ *Ghost vanished!* All fighters earn +{event['exp_reward']} EXP!")
        for fid in fighters:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp:
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, event["exp_reward"]); save_player(fp)
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}*! 👻", permanent=True))
            elif fs:
                add_shadow_exp(fs, event["exp_reward"]); save_shadow(fs)
    await send_group(update, "\n".join(lines), permanent=False, delay=30)

async def claim_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "cache": return
    active_events.pop(chat_id, None)
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    loot = roll_loot_table(event["loot_table"])
    if p:
        if loot: add_item(p, loot); save_player(p)
        msg = f"💰 *{user.first_name}* claimed the cache!"
        if loot: msg += f" Found: *{loot}*!"
        await send_group(update, msg, permanent=False, delay=20)
    else:
        lmsgs, _ = add_shadow_exp(s, 100); save_shadow(s)
        await send_group(update, f"💰 *{user.first_name}* claimed the cache! +100 EXP",
                         permanent=False, delay=20)

async def pray_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    event   = active_events.get(chat_id)
    if not event or event["key"] != "shrine": return
    await greet_event(update, context)  # reuse greet logic for shrine

# ── HELP ──────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_group(update,
        f"⚔️ *{WORLD_NAME} v13 — Commands*\n\n"
        "👤 *Everyone:*\n"
        "*/rank* — Leaderboard (paginated)\n*/rank me* — Your position\n"
        "*/stats* — Full profile\n*/ascend* — Enter the RPG\n"
        "*/weather* — Table conditions\n\n"
        "⚔️ *Combat:*\n"
        "*/attack* — Reply + /attack to strike\n"
        "*/heal* — Reply + /heal (uses potion)\n"
        "*/skill* — Show/use class skills\n"
        "*/skill [tier]* — Use specific tier skill\n\n"
        "📱 *Character:*\n"
        "*/class* — Choose starting class (Lv 5)\n"
        "*/prestige A|B* — Choose path (Lv 10, locked forever)\n"
        "*/allocate STR 5* — Spend stat points\n"
        "*/title [name]* — Equip a title\n"
        "*/equip [item]* — Equip gear\n"
        "*/sell [item]* — Sell for gold\n"
        "*/inventory* — Your items\n\n"
        "🗺️ *Activities:*\n"
        "*/daily* — Daily reward (24h)\n"
        "*/train* — Train (30min)\n"
        "*/quest* — Solo quest (1hr)\n"
        "*/explore* — Expedition (1hr, 2x/day)\n"
        "*/shop* — Daily shop\n"
        "*/cooldowns* — Check timers\n\n"
        "🏰 *Social:*\n"
        "*/guild* — Guild commands\n"
        "*/boss [name]* — Start boss fight\n"
        "*/strike* — Attack active boss\n"
        "*/raid* — Start/join raid\n"
        "*/raidstart* — Begin raid\n"
        "*/raidstrike* — Attack in raid\n"
        "*/raidstatus* — Raid progress\n\n"
        "💬 *Chatting earns EXP. Level up milestones announced. Secrets lurk...* 🎱",
        permanent=False, delay=60)

# ── WIPE (admin only) ─────────────────────────────────────────────────────────
async def wipe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await send_group(update, "❌ Admin only."); return
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS shadow_profiles")
        c.execute("DROP TABLE IF EXISTS players")
        c.execute("DROP TABLE IF EXISTS guilds")
        c.execute("DROP TABLE IF EXISTS bounties")
        conn.commit(); conn.close()
        init_db()
        active_bosses.clear(); active_raids.clear()
        active_events.clear(); combat_cards.clear()
        await send_group(update, "🗑️ *Database wiped and reset.* Fresh start!", permanent=True)
    except Exception as e:
        await send_group(update, f"❌ Wipe failed: {e}", permanent=False)

# ── PASSIVE MESSAGE HANDLER ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user    = update.effective_user
    chat_id = update.effective_chat.id
    text    = update.message.text.lower()

    # Random events — every 2500 messages
    message_counters[chat_id] = message_counters.get(chat_id,0) + 1
    if message_counters[chat_id] % 2500 == 0 and chat_id not in active_events:
        roll = random.random()
        if roll < 0.70:
            freq_pool = [e for e in RANDOM_EVENTS if e["freq"]=="common"]
        elif roll < 0.90:
            freq_pool = [e for e in RANDOM_EVENTS if e["freq"]=="uncommon"]
        else:
            freq_pool = [e for e in RANDOM_EVENTS if e["freq"]=="rare"]
        if freq_pool:
            event = random.choice(freq_pool).copy()
            active_events[chat_id] = event
            # Special handling
            if event["key"] == "storm":
                _weather_cache["weather"] = random.choice(WEATHER_TABLE)
                _weather_cache["set_at"]  = datetime.now()
                active_events.pop(chat_id, None)
            elif event["key"] == "cursed":
                conn2 = sqlite3.connect(DB_PATH); conn2.row_factory = sqlite3.Row; c2 = conn2.cursor()
                c2.execute("SELECT user_id FROM players ORDER BY RANDOM() LIMIT 1")
                row2 = c2.fetchone(); conn2.close()
                if row2:
                    cp = get_player(row2["user_id"])
                    if cp:
                        event["cursed_id"] = cp["user_id"]
                        event["cursed_name"] = cp["username"]
            try:
                msg_text = event["msg"]
                if event["key"] == "cursed" and event.get("cursed_name"):
                    msg_text = f"⚰️ *{event['cursed_name']}* has been cursed! They lose 10% EXP per hour until someone uses /purge on them!"
                await update.message.reply_text(msg_text, parse_mode="Markdown")
            except Exception:
                pass

    # Shadow profile
    s = get_or_create_shadow(user.id, user.first_name)
    prev_seen = s.get("last_seen")
    s["username"]      = user.first_name
    s["message_count"] = s.get("message_count",0) + 1

    p = get_player(user.id) if s.get("ascended") else None

    # Sync levels
    if p and s:
        if sync_levels(p, s):
            save_player(p); save_shadow(s)

    # Idle reward
    if prev_seen:
        try:
            away_hours = (datetime.now() - datetime.fromisoformat(prev_seen)).total_seconds() / 3600
            if away_hours >= 1:
                await check_idle_reward(user, s, p, context.bot, chat_id)
        except Exception:
            pass

    # Update last_seen
    s["last_seen"] = datetime.now().isoformat()

    # Skip EXP if defeated
    if p and is_defeated(p):
        save_shadow(s); return

    cds_s = safe_cds(s)
    shadow_exp = 0; rpg_exp = 0; rpg_gold = 0

    # Easter eggs
    for egg in EASTER_EGGS:
        if re.search(egg["pattern"], text, re.IGNORECASE):
            if egg.get("secret_boss"):
                w = get_weather()
                if w.get("secret_eligible") and chat_id not in secret_boss_active:
                    bd = BOSSES["void"]
                    secret_boss_active[chat_id] = {
                        "data": bd.copy(), "hp": bd["max_hp"],
                        "participants": [{"id":user.id,"name":user.first_name,"dmg":0}]
                    }
                    await update.message.reply_text(
                        f"🌑 *THE VOID BALL AWAKENS!*\n\n_{bd['desc']}_\n\n"
                        f"❤️ HP: {bd['max_hp']}\n*{user.first_name}* called it forth! Use /strike!",
                        parse_mode="Markdown")
            break

    # Keyword triggers
    for trigger in KEYWORD_TRIGGERS:
        if re.search(trigger["pattern"], text, re.IGNORECASE):
            key = trigger["key"]
            if not cds_s.get(key) or \
               (datetime.now() - datetime.fromisoformat(cds_s[key])).total_seconds() > trigger["cooldown"]:
                cds_s[key] = datetime.now().isoformat()
                if trigger["exp"] > 0:
                    shadow_exp += trigger["exp"]
                    if p: rpg_exp += trigger["exp"]
                elif trigger["exp"] < 0:
                    s["exp"] = max(0, s["exp"] + trigger["exp"])
                    if p: p["exp"] = max(0, p["exp"] + trigger["exp"])
                if trigger.get("gold_chance") and random.random() < trigger["gold_chance"]:
                    rpg_gold += 1
            break

    # Daily first message bonus
    today = datetime.now().strftime("%Y-%m-%d")
    if cds_s.get("daily_date") != today:
        cds_s.update({"daily_date":today,"daily_messages":0,
                      "daily_bonus_given":False,"streak_50":False,
                      "streak_100":False,"streak_500":False})
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
            f"🔥 *{user.first_name}* hit a *50 message streak!* +150 EXP!"))
    if dm >= 100 and not cds_s.get("streak_100"):
        cds_s["streak_100"] = True; shadow_exp += 300; rpg_gold += 30
        if p: rpg_exp += 300
        asyncio.create_task(announce(context.bot, chat_id,
            f"🔥 *{user.first_name}* hit a *100 message streak!* +300 EXP +30 Gold!"))
    if dm >= 500 and not cds_s.get("streak_500"):
        cds_s["streak_500"] = True; shadow_exp += 800
        if p: rpg_exp += 800
        asyncio.create_task(announce(context.bot, chat_id,
            f"🏆 *{user.first_name}* hit a *500 message streak!* +800 EXP! 🎱"))

    # Bleed tick
    if p and is_bleeding(p):
        tick_dmg = check_bleed_tick(p)
        if tick_dmg > 0 and p["hp"] == 0:
            set_status(p, "defeated_until", 21600)
            asyncio.create_task(announce(context.bot, chat_id,
                f"🩸 *{p['username']}* bled out! Defeated for 6 hours."))

    # Apply shadow EXP
    s["passive_cooldowns"] = json.dumps(cds_s)
    if shadow_exp > 0:
        lmsgs, did_level = add_shadow_exp(s, shadow_exp)
        save_shadow(s)
        if did_level and s["level"] % 10 == 0:
            hint = ("\n_Type /ascend to enter the World of 8Ball!_"
                    if not s.get("ascended") and s["level"] >= 5 else "")
            tier = get_tier(s["level"])
            asyncio.create_task(announce(context.bot, chat_id,
                f"{tier['emoji']} *{s['username']}* reached *Level {s['level']}*!{hint}",
                permanent=True))
    else:
        save_shadow(s)

    # Apply RPG EXP
    if p:
        p["gold"] = p.get("gold",0) + rpg_gold
        if rpg_exp > 0:
            lmsgs, did_level = add_exp(p, rpg_exp)
            save_player(p)
            if did_level:
                if p["level"] > s["level"]:
                    s["level"] = p["level"]; s["exp"] = 0; save_shadow(s)
                if p["level"] % 10 == 0:
                    cls = get_player_class(p)
                    cnote = f" the *{cls['name']}*" if cls else ""
                    ann_lines = [f"🎉 *{p['username']}*{cnote} reached *Level {p['level']}*! 🎱"]
                    for msg_line in lmsgs:
                        if any(x in msg_line for x in
                               ["Choose a class","Choose your path","LEVEL 100"]):
                            ann_lines.append(msg_line)
                    asyncio.create_task(announce(context.bot, chat_id,
                        "\n".join(ann_lines), permanent=True))
        else:
            save_player(p)

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Universal
    app.add_handler(CommandHandler("rank",       rank_cmd))
    app.add_handler(CommandHandler("stats",      stats_cmd))
    app.add_handler(CommandHandler("help",       help_cmd))
    app.add_handler(CommandHandler("weather",    weather_cmd))
    app.add_handler(CommandHandler("ascend",     ascend_cmd))
    app.add_handler(CommandHandler("wipe",       wipe_cmd))

    # Character
    app.add_handler(CommandHandler("class",      class_cmd))
    app.add_handler(CommandHandler("prestige",   prestige_cmd))
    app.add_handler(CommandHandler("allocate",   allocate_cmd))
    app.add_handler(CommandHandler("title",      title_cmd))
    app.add_handler(CommandHandler("skill",      skill_cmd))
    app.add_handler(CommandHandler("equip",      equip_cmd))
    app.add_handler(CommandHandler("sell",       sell_cmd))
    app.add_handler(CommandHandler("inventory",  inventory_cmd))
    app.add_handler(CommandHandler("cooldowns",  cooldowns_cmd))

    # Activities
    app.add_handler(CommandHandler("daily",      daily_cmd))
    app.add_handler(CommandHandler("train",      train_cmd))
    app.add_handler(CommandHandler("quest",      quest_cmd))
    app.add_handler(CommandHandler("explore",    explore_cmd))
    app.add_handler(CommandHandler("shop",       shop_cmd))

    # Combat
    app.add_handler(CommandHandler("attack",     attack_cmd))
    app.add_handler(CommandHandler("heal",       heal_cmd))
    app.add_handler(CommandHandler("boss",       boss_cmd))
    app.add_handler(CommandHandler("strike",     strike_cmd))
    app.add_handler(CommandHandler("raid",       raid_cmd))
    app.add_handler(CommandHandler("raidstart",  raidstart_cmd))
    app.add_handler(CommandHandler("raidstrike", raidstrike_cmd))
    app.add_handler(CommandHandler("raidstatus", raidstatus_cmd))

    # Events
    app.add_handler(CommandHandler("greet",      greet_event))
    app.add_handler(CommandHandler("fight",      fight_event))
    app.add_handler(CommandHandler("shoot",      shoot_event))
    app.add_handler(CommandHandler("claim",      claim_event))
    app.add_handler(CommandHandler("pray",       pray_event))

    # Guild
    app.add_handler(CommandHandler("guild",      guild_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(rank_callback, pattern="^rank_p_"))

    # Passive
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"🎱 {WORLD_NAME} RPG Bot v13 is running...")
    app.run_polling(poll_interval=0.3)

if __name__ == "__main__":
    main()
# ── ATTACK ────────────────────────────────────────────────────────────────────
async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    au = update.effective_user
    a  = get_player(au.id)
    if not a:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(a):
        await send_group(update, "💀 You're defeated! Wait for a heal or sit out.", delay=9); return
    if is_vanished(a):
        await send_group(update, "👻 You're vanished — you can't attack while hidden.", delay=9); return
    if cannot_attack(a):
        await send_group(update, "⚡ You're stunned or rooted — can't attack right now.", delay=9); return
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
        await send_group(update, f"🛡️ {d['username']} is *Still Recovering* — invincible for now.", delay=9); return

    w    = get_weather()
    chat = update.effective_chat.id
    try: await update.message.delete()
    except: pass

    # Miss check
    if check_miss(a, d):
        d["dodges"] = d.get("dodges",0) + 1
        check_titles(d); save_player(d); save_player(a)
        await update_combat_card(update.get_bot(), chat, d,
            f"🌀 *{a['username']}* missed *{d['username']}*!")
        return

    # Damage
    dmg = calc_attack_damage(a, w)

    # Crit check
    crit_forced = safe_cds(a).pop("next_crit_skill", None)
    if crit_forced:
        a["passive_cooldowns"] = json.dumps(safe_cds(a))
    if crit_forced or check_crit(a):
        dmg = apply_crit(a, dmg)
        crit_note = " 💥 CRIT!"
    else:
        crit_note = ""

    # Class passives — execution
    cls_a = get_player_class(a)
    if cls_a and cls_a.get("passive_key") == "execute":
        hp_pct = d["hp"] / max(1, d["max_hp"])
        if hp_pct < 0.25:
            dmg *= 2

    # Defender passives / reflect
    reflect = apply_reflect(d, a, dmg)
    dmg_after_def = calc_defense(d, dmg)

    # Holy field reflect (Page/Squire/Knight/Paladin)
    if _ts_active(d, "holy_field_until"):
        wis_dmg = round(safe_stats(d).get("WIS",5) * 2)
        a["hp"] = max(0, a["hp"] - wis_dmg)
        reflect_note = f" | ✨ Holy Field reflects {wis_dmg} dmg!"
    else:
        reflect_note = ""

    # Unbreakable passive (Hero)
    if cls_d := get_player_class(d):
        if cls_d.get("passive_key") == "unbreakable":
            if d["hp"] - dmg_after_def <= 0 and not d.get("unbreakable_used"):
                dmg_after_def = d["hp"] - 1
                d["unbreakable_used"] = True

    # Apply damage
    d["hp"] = max(0, d["hp"] - dmg_after_def)

    # Lifesteal
    healed = apply_lifesteal(a, dmg_after_def)

    # Steady aim tracking
    if cls_a and cls_a.get("passive_key") == "steady_aim":
        if a.get("steady_aim_target") == d["user_id"]:
            a["steady_aim_stacks"] = min(5, safe_int(a.get("steady_aim_stacks")) + 1)
        else:
            a["steady_aim_target"] = d["user_id"]
            a["steady_aim_stacks"] = 1

    # Mark first hit tracking
    if cls_a and cls_a.get("passive_key") == "marked":
        a["mark_first_hit"] = 0  # used

    # Update recent attackers
    update_recent_attackers(d, au.id)

    action = f"⚔️ *{a['username']}* → *{d['username']}* for *{dmg_after_def} dmg*{crit_note}{reflect_note}"
    if healed: action += f" | 🩸 +{healed} HP"

    # Check defeat
    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        d["defeated_until"] = (datetime.now() + timedelta(hours=6)).isoformat()
        exp_loss = round(d.get("exp",0) * 0.10)
        d["exp"]  = max(0, d.get("exp",0) - exp_loss)
        d["losses"] = d.get("losses",0) + 1
        a["wins"]   = a.get("wins",0) + 1

        # Deadeye Last Shot — double timer
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

        # Conqueror passive (Warlord) — restore 20% HP on kill
        if cls_a and cls_a.get("passive_key") == "conqueror":
            restore = round(a["max_hp"] * 0.20)
            a["hp"] = min(a["max_hp"], a["hp"] + restore)
            set_status(d, "weakened_until", 3600)

        # Bounty check
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; bc = conn.cursor()
        bc.execute("SELECT * FROM bounties WHERE target_id=? AND claimed_by IS NULL AND expires_at > ?",
                   (d["user_id"], datetime.now().isoformat()))
        bounty = bc.fetchone()
        if bounty:
            bc.execute("UPDATE bounties SET claimed_by=? WHERE bounty_id=?",
                       (au.id, bounty["bounty_id"]))
            conn.commit()
            a["gold"] = a.get("gold",0) + bounty["reward"]
            placer_p = get_player(bounty["placer_id"])
            if placer_p:
                placer_p["gold"] = placer_p.get("gold",0) + 250
                save_player(placer_p)
            action += f"\n💰 BOUNTY CLAIMED! +{bounty['reward']} gold!"
        conn.close()

        # Deadeye kill bonus
        if cls_a and cls_a.get("passive_key") == "dead_or_alive":
            a["deadeye_kill_bonus"] = safe_int(a.get("deadeye_kill_bonus")) + 2

        action += f"\n💀 *{d['username']}* DEFEATED! +{exp_gain} EXP to {a['username']}."

        if leveled and a["level"] % 10 == 0:
            asyncio.create_task(announce(update.get_bot(), chat,
                f"🎉 *{a['username']}* reached *Level {a['level']}*! ⚔️", permanent=True))

    check_titles(a); check_titles(d)
    save_player(a); save_player(d)
    await update_combat_card(update.get_bot(), chat, d, action,
                             finished=(d["hp"] <= 0))

# ── HEAL ──────────────────────────────────────────────────────────────────────
async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hu = update.effective_user
    h  = get_player(hu.id)
    if not h:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not update.message.reply_to_message:
        await send_group(update, "Reply to someone's message with /heal!", delay=9); return

    tu = update.message.reply_to_message.from_user
    t  = get_player(tu.id)
    if not t:
        await send_group(update, f"{tu.first_name} hasn't ascended yet!", delay=9); return

    # Check if target can be healed/revived
    target_is_dead = t["hp"] <= 0
    if target_is_dead and is_revival_blocked(t):
        await send_group(update,
            f"☠️ *{t['username']}* has been condemned by a Zealot — they cannot be revived for now.\n"
            f"Only a *Saint's Absolution* can lift this.", delay=15); return
    if is_healing_blocked(t) and not target_is_dead:
        await send_group(update,
            f"🚫 *{t['username']}* cannot be healed right now (Void Collapse active).", delay=9); return

    cid = h.get("class_id","")
    is_priest_healer = cid in HEALER_CLASSES

    inv = sjl(h.get("inventory"), [])
    potion = None
    heal_amount = 0

    if is_priest_healer:
        # Priest line — free revive via skill (Holy Light)
        heal_amount = safe_stats(h).get("WIS",5) * 5
        if get_player_class(h) and get_player_class(h).get("passive_key") == "mending_aura":
            heal_amount = round(heal_amount * 1.25)
    else:
        # Non-priest — requires potion
        if "Mega Health Potion" in inv:
            potion = "Mega Health Potion"; heal_amount = 200
        elif "Super Health Potion" in inv:
            potion = "Super Health Potion"; heal_amount = 100
        elif "Health Potion" in inv:
            potion = "Health Potion"; heal_amount = 50
        else:
            await send_group(update,
                "❌ You need a Health Potion to heal someone!\n"
                "Priests can heal for free with /skill.", delay=9); return
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
    new_t = check_titles(h)
    lmsgs, leveled = add_exp(h, 20)
    save_player(h); save_player(t)

    if is_priest_healer:
        who = f"🙏 *{h['username']}* ({get_player_class(h)['name']}) heals"
    else:
        who = f"💊 *{h['username']}* uses *{potion}* to heal"

    msg = (f"{who} *{t['username']}* for *{heal_amount} HP*!\n"
           f"❤️ {t['username']}: {t['hp']}/{t['max_hp']} HP")
    if was_defeated:
        msg += f"\n✨ *{t['username']}* is revived! *1 hour invincibility* granted — _(Still Recovering)_"
    if new_t:
        msg += f"\n🏅 *{h['username']}* earned: *{new_t[0]}*!"
    if leveled and h["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{h['username']}* reached *Level {h['level']}*! 💊", permanent=True))
    await send_group(update, msg, delay=30)

# ── STATS ─────────────────────────────────────────────────────────────────────
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player(user.id); s = get_shadow(user.id)
    if not p and not s:
        await send_group(update,
            "No profile yet — just start chatting to build your level!", delay=9); return
    if not p:
        tier = get_tier(s["level"])
        await send_group(update,
            f"👤 *{s['username']}* — Shadow Profile\n\n"
            f"{tier['emoji']} Level *{s['level']}*\n"
            f"✨ EXP: {s['exp']:,}/{exp_for_level(s['level']):,}\n"
            f"🏆 Lifetime: *{safe_int(s.get('total_exp')):,}* EXP\n"
            f"💬 Messages: {s.get('message_count',0):,}\n\n"
            f"_Send /ascend in a private chat to enter the RPG!_",
            permanent=False, delay=9); return

    if s: sync_levels(p, s); save_player(p); save_shadow(s)

    # Auto-clear bad defeated state
    if is_defeated(p) and p["hp"] > 0:
        p["defeated_until"] = None; save_player(p)

    w   = get_weather()
    inv = Counter(sjl(p.get("inventory"), []))
    inv_text = ", ".join(f"{k} x{v}" for k,v in inv.items()) or "Empty"

    guild_text = "None"
    if p.get("guild_id") and str(p.get("guild_id")) != "None":
        g = get_guild(p["guild_id"])
        if g:
            glvl = safe_int(g.get("level"),1)
            perk = GUILD_PERKS.get(glvl,{})
            guild_text = f"{g['name']} (Lv{glvl} +{int(perk.get('exp_bonus',0)*100)}% EXP)"

    cls       = get_player_class(p)
    cls_name  = cls["name"] if cls else ("*Choose at Lv 5!* — /class" if p["level"] >= 5 else "Unlocks at Lv 5")
    path_str  = f" | Path {p.get('class_path','?')}" if p.get("class_path") else ""
    stats_d   = safe_stats(p)
    sp        = safe_int(p.get("stat_points"))
    statuses  = get_active_statuses(p)
    status_str = "\n" + " | ".join(statuses) if statuses else ""

    defeated_str = " *(Defeated — 0 HP)*" if is_defeated(p) else ""
    recovering   = " *(Still Recovering)*" if is_invincible(p) else ""

    # Gear display
    weap = p.get("equipped_weapon") or "None"
    armo = p.get("equipped_armor")  or "None"
    shld = p.get("equipped_shield") or "None"
    acc  = p.get("equipped_accessory") or "None"

    # Skills
    all_skills = sjl(p.get("all_skills"), [])
    skill_names = [s["name"] for s in all_skills] if all_skills else ["None yet"]

    await send_group(update,
        f"⚔️ *{p['username']}*{defeated_str}{recovering}\n"
        f"🏅 *{p['active_title']}* | {get_tier(p['level'])['name']} | 🏰 {guild_text}\n"
        f"🌍 {WORLD_NAME} — _{w['name']}_\n{status_str}\n\n"
        f"❤️ HP: {p['hp']}/{p['max_hp']} | ⭐ Level {p['level']} | "
        f"✨ {p['exp']:,}/{exp_for_level(p['level']):,} EXP\n"
        f"🏆 Lifetime: *{safe_int(p.get('total_exp')):,}* EXP\n"
        f"💰 Gold: {p['gold']} | ⚔️ W/L: {p['wins']}/{p.get('losses',0)}\n"
        f"🗺️ Quests: {p['quests_done']} | 🔨 Crafts: {safe_int(p.get('crafts_done'))}\n\n"
        f"🧙 Class: {cls_name}{path_str}\n"
        f"📊 STR:{stats_d.get('STR',5)} DEF:{stats_d.get('DEF',5)} "
        f"AGI:{stats_d.get('AGI',5)} INT:{stats_d.get('INT',5)} WIS:{stats_d.get('WIS',5)}"
        + (f" | 💡 {sp} pts (/allocate)" if sp > 0 else "") + "\n"
        f"🔮 Skills: {', '.join(skill_names)}\n\n"
        f"⚔️ Weapon: {weap} | 🛡️ Armor: {armo}\n"
        f"🔰 Shield: {shld} | 💍 Accessory: {acc}\n"
        f"🎒 Inventory: {inv_text}\n"
        f"🏅 Titles: {', '.join(safe_titles(p))}",
        permanent=True)

# ── BOSS ──────────────────────────────────────────────────────────────────────
async def boss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 You're defeated!"); return
    chat_id = update.effective_chat.id

    if chat_id in active_bosses:
        boss = active_bosses[chat_id]
        if user.id in [u["id"] for u in boss["participants"]]:
            await send_group(update,
                f"You're already fighting *{boss['data']['name']}*! Use /strike."); return
        if is_defeated(p): await send_group(update, "💀 Defeated players can't join!"); return
        boss["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        await send_group(update,
            f"⚔️ *{user.first_name}* joins the fight!\n"
            f"❤️ Boss HP: {boss['hp']}/{boss['data']['max_hp']}\nUse /strike!", delay=20); return

    if not context.args:
        bl = "\n".join(
            f"• `{k}` — {v['name']} (HP: {v['max_hp']}, EXP: {v['exp']:,})"
            for k, v in BOSSES.items() if not v.get("secret"))
        await send_group(update, f"⚔️ *Available Bosses:*\n{bl}\n\n`/boss 1 ball`", delay=30); return

    key = " ".join(context.args).lower()
    bd  = BOSSES.get(key)
    if not bd or bd.get("secret"):
        await send_group(update, "Unknown boss."); return

    active_bosses[chat_id] = {
        "data": bd.copy(), "hp": bd["max_hp"],
        "participants": [{"id": user.id, "name": user.first_name, "dmg": 0}]
    }
    await send_group(update,
        f"🎱 *{bd['name']} HAS APPEARED!*\n\n_{bd['desc']}_\n\n"
        f"❤️ HP: {bd['max_hp']} | 💀 {bd['dmg_min']}–{bd['dmg_max']} dmg\n"
        f"🏆 Reward: {bd['exp']:,} EXP | {bd['gold']} Gold\n\n"
        f"*{user.first_name}* engaged! Others: `/boss {key}` to join | /strike to attack!",
        permanent=True)

async def strike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return

    # Handle secret void boss
    if chat_id in secret_boss_active:
        boss = secret_boss_active[chat_id]
        if user.id not in [u["id"] for u in boss["participants"]]:
            if is_defeated(p):
                await send_group(update, "💀 Defeated players can't join the fight!"); return
            boss["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        participant = next(u for u in boss["participants"] if u["id"] == user.id)
        if is_defeated(p):
            await send_group(update, "💀 You've been defeated! You can't strike."); return
        w   = get_weather(); dmg = calc_attack_damage(p, w); lines = []
        boss["hp"] = max(0, boss["hp"]-dmg); participant["dmg"] += dmg
        lines.append(f"⚔️ *{user.first_name}* strikes *{boss['data']['name']}* for *{dmg}!*\n"
                     f"❤️ HP: {boss['hp']}/{boss['data']['max_hp']}")
        # Boss retaliation — can kill
        alive = [u for u in boss["participants"] if not is_defeated(get_player(u["id"]))]
        if alive and boss["hp"] > 0 and random.random() < 0.80:
            target = random.choice(alive); tp = get_player(target["id"])
            if tp:
                bdmg = calc_defense(tp, random.randint(
                    boss["data"]["dmg_min"], boss["data"]["dmg_max"]))
                tp["hp"] = max(0, tp["hp"] - bdmg)
                if tp["hp"] == 0:
                    tp["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
                    lines.append(f"💀 *{boss['data']['name']}* kills *{target['name']}*! 6hr defeat.")
                else:
                    lines.append(f"🌑 Boss hits *{target['name']}* for {bdmg}! ({tp['hp']}/{tp['max_hp']} HP)")
                save_player(tp)
        # Check if all participants defeated
        all_dead = all(is_defeated(get_player(u["id"])) for u in boss["participants"])
        if all_dead and boss["hp"] > 0:
            secret_boss_active.pop(chat_id, None)
            lines.append(f"\n💀 *All fighters have fallen!* The Void Ball retreats... for now.")
            await send_group(update, "\n".join(lines), delay=30); return
        if boss["hp"] <= 0:
            data = boss["data"]; secret_boss_active.pop(chat_id, None)
            lines.append(f"\n🏆 *THE VOID BALL IS DEFEATED!*\n")
            for u in boss["participants"]:
                pp = get_player(u["id"])
                if not pp: continue
                pp["gold"] = pp.get("gold",0) + data["gold"]
                loot = _roll_boss_loot(data)
                if loot: add_item(pp, loot); lines.append(f"🎒 *{pp['username']}* found {RARITY_EMOJI.get(WEAPONS.get(loot,ARMORS.get(loot,ACCESSORIES.get(loot,{}))).get('rarity',''),'⚪')} *{loot}*!")
                lmsgs, leveled = add_exp(pp, data["exp"], w)
                if award_title(pp, data["title"]): lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
                save_player(pp)
                lines.append(f"✅ *{pp['username']}* — +{data['exp']:,} EXP | +{data['gold']} Gold")
                if leveled and pp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{pp['username']}* reached *Level {pp['level']}*! 🌑", permanent=True))
        save_player(p); await send_group(update, "\n".join(lines), delay=30); return

    if chat_id not in active_bosses:
        await send_group(update, "No active boss! Use /boss."); return
    boss = active_bosses[chat_id]
    participant = next((u for u in boss["participants"] if u["id"] == user.id), None)
    if not participant:
        await send_group(update, "Use `/boss [name]` to join first."); return
    if is_defeated(p):
        await send_group(update, "💀 You've been defeated! You can't strike."); return

    w   = get_weather(); dmg = calc_attack_damage(p, w); lines = []
    boss["hp"] = max(0, boss["hp"]-dmg); participant["dmg"] += dmg
    lines.append(f"⚔️ *{user.first_name}* strikes *{boss['data']['name']}* for *{dmg}!*\n"
                 f"❤️ Boss HP: {boss['hp']}/{boss['data']['max_hp']}")

    # Boss retaliation
    alive = [u for u in boss["participants"] if not is_defeated(get_player(u["id"]))]
    if alive and boss["hp"] > 0 and random.random() < 0.80:
        target = random.choice(alive); tp = get_player(target["id"])
        if tp:
            bdmg = calc_defense(tp, random.randint(
                boss["data"]["dmg_min"], boss["data"]["dmg_max"]))
            tp["hp"] = max(0, tp["hp"] - bdmg)
            if tp["hp"] == 0:
                tp["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
                lines.append(f"💀 *{boss['data']['name']}* kills *{target['name']}*! 6hr defeat.")
            else:
                lines.append(f"💀 Boss hits *{target['name']}* for {bdmg}! ({tp['hp']}/{tp['max_hp']} HP)")
            save_player(tp)

    # Check if all dead
    all_dead = all(is_defeated(get_player(u["id"])) for u in boss["participants"])
    if all_dead and boss["hp"] > 0:
        active_bosses.pop(chat_id, None)
        lines.append(f"\n💀 *All fighters defeated!* {boss['data']['name']} wins this round.")
        await send_group(update, "\n".join(lines), delay=30); return

    if boss["hp"] <= 0:
        data = boss["data"]; active_bosses.pop(chat_id, None)
        lines.append(f"\n🏆 *{data['name']} DEFEATED!*\n")
        for u in boss["participants"]:
            pp = get_player(u["id"])
            if not pp: continue
            pp["gold"] = pp.get("gold",0) + data["gold"]
            loot = _roll_boss_loot(data)
            if loot:
                add_item(pp, loot)
                r = ""
                for pool in [WEAPONS,ARMORS,ACCESSORIES]:
                    if loot in pool: r = RARITY_EMOJI.get(pool[loot].get("rarity",""),""); break
                lines.append(f"🎒 *{pp['username']}* found {r} *{loot}*!")
            lmsgs, leveled = add_exp(pp, data["exp"], w)
            if award_title(pp, data["title"]): lines.append(f"🏅 *{pp['username']}* earned: *{data['title']}*!")
            save_player(pp)
            lines.append(f"✅ *{pp['username']}* — +{data['exp']:,} EXP | +{data['gold']} Gold")
            if leveled and pp["level"] % 10 == 0:
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}* defeating {data['name']}! 🏆",
                    permanent=True))
    save_player(p); await send_group(update, "\n".join(lines), delay=30)

def _roll_boss_loot(boss_data):
    table = boss_data.get("loot_table",[])
    if not table: return None
    name, rarity = random.choice(table)
    if name in WEAPONS or name in ARMORS or name in ACCESSORIES:
        return name
    return None

# ── RAID ──────────────────────────────────────────────────────────────────────
async def raid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if is_defeated(p): await send_group(update, "💀 You're defeated!"); return
    if chat_id in active_raids:
        raid = active_raids[chat_id]
        if raid.get("in_progress"):
            await send_group(update, "⚔️ Raid in progress! Use /raidstrike."); return
        if user.id in [u["id"] for u in raid["party"]]:
            await send_group(update,
                f"Already in party! ({len(raid['party'])} players)\nUse /raidstart when ready."); return
        raid["party"].append({"id":user.id,"name":user.first_name})
        await send_group(update,
            f"⚔️ *{user.first_name}* joins! ({len(raid['party'])} players)\nUse /raidstart (min 2)."); return
    active_raids[chat_id] = {
        "party":[{"id":user.id,"name":user.first_name}],
        "in_progress":False,"wave":0,"tier":None,
        "enemy":None,"enemy_hp":0,"enemy_max_hp":0
    }
    await send_group(update,
        f"🏰 *RAID LOBBY!*\n\n*{user.first_name}* is forming a party.\n"
        f"Others: /raid to join! (Min 2)\n\nLeader: /raidstart when ready.", delay=60)

async def raidstart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; chat_id = update.effective_chat.id
    if chat_id not in active_raids:
        await send_group(update, "No raid lobby! Use /raid."); return
    raid = active_raids[chat_id]
    if raid.get("in_progress"):
        await send_group(update, "Raid already started!"); return
    if len(raid["party"]) < 2:
        await send_group(update, f"Need at least 2 players! Have {len(raid['party'])}."); return
    levels = [get_player(u["id"])["level"] for u in raid["party"] if get_player(u["id"])]
    avg    = sum(levels)/len(levels) if levels else 1
    tier   = ([t for t in RAID_TIERS if t["min_level"] <= avg] or [RAID_TIERS[0]])[-1]
    raid["tier"]        = tier
    raid["in_progress"] = True
    raid["wave"]        = 1
    fe = tier["wave_enemies"][0].copy()
    raid["enemy"]       = fe
    raid["enemy_hp"]    = fe["hp"]
    raid["enemy_max_hp"]= fe["hp"]
    names = ", ".join(u["name"] for u in raid["party"])
    await send_group(update,
        f"⚔️ *RAID — {tier['name']}*\n\n👥 {names}\n"
        f"📊 Avg Lv: {avg:.0f} | Waves: {len(tier['wave_enemies'])+1}\n\n"
        f"🌊 *Wave 1 — {fe['name']}*\n❤️ HP: {fe['hp']}\n\nUse /raidstrike!", delay=60)

async def raidstrike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p: await send_group(update, "Use /ascend first!"); return
    if chat_id not in active_raids:
        await send_group(update, "No active raid!"); return
    raid = active_raids[chat_id]
    if not raid.get("in_progress"):
        await send_group(update, "Raid hasn't started! Use /raidstart."); return
    if user.id not in [u["id"] for u in raid["party"]]:
        await send_group(update, "You're not in this raid!"); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated!"); return
    w   = get_weather(); dmg = calc_attack_damage(p, w); enemy = raid["enemy"]; lines = []
    raid["enemy_hp"] = max(0, raid["enemy_hp"]-dmg)
    lines.append(f"⚔️ *{user.first_name}* strikes *{enemy['name']}* for *{dmg}!*\n"
                 f"❤️ HP: {raid['enemy_hp']}/{raid['enemy_max_hp']}")
    alive = [u for u in raid["party"] if not is_defeated(get_player(u["id"]))]
    if alive and raid["enemy_hp"] > 0 and random.random() < 0.65:
        target = random.choice(alive); tp = get_player(target["id"])
        if tp:
            edm = calc_defense(tp, random.randint(enemy["dmg_min"],enemy["dmg_max"]))
            tp["hp"] = max(0, tp["hp"]-edm)
            if tp["hp"] == 0:
                tp["defeated_until"] = (datetime.now()+timedelta(hours=2)).isoformat()
            save_player(tp)
            lines.append(f"🩸 Enemy hits *{target['name']}* for {edm}! ({tp['hp']}/{tp['max_hp']} HP)")
    if raid["enemy_hp"] <= 0:
        tier = raid["tier"]; we = tier["wave_enemies"]; cw = raid["wave"]
        lines.append(f"\n✅ *Wave {cw} cleared!*")
        if cw < len(we):
            raid["wave"] += 1; ne = we[cw].copy()
            raid["enemy"] = ne; raid["enemy_hp"] = ne["hp"]; raid["enemy_max_hp"] = ne["hp"]
            lines.append(f"\n🌊 *Wave {raid['wave']} — {ne['name']}*\n❤️ HP: {ne['hp']}")
        elif cw == len(we):
            bd   = BOSSES[tier["wave_boss_key"]]
            rbhp = round(bd["max_hp"] * 0.5 * len(raid["party"]))
            raid["wave"] = len(we)+1
            raid["enemy"] = {"name":bd["name"]+" ⚡",
                             "dmg_min":round(bd["dmg_min"]*0.6),
                             "dmg_max":round(bd["dmg_max"]*0.6)}
            raid["enemy_hp"] = rbhp; raid["enemy_max_hp"] = rbhp
            lines.append(f"\n🎱 *FINAL BOSS — {bd['name']}!*\n❤️ HP: {rbhp}")
        else:
            lines.append(f"\n🏆 *RAID COMPLETE — {tier['name']}!*\n")
            bd = BOSSES[tier["wave_boss_key"]]; active_raids.pop(chat_id, None)
            for u in raid["party"]:
                pp = get_player(u["id"])
                if not pp: continue
                pp["gold"] = pp.get("gold",0) + tier["gold_reward"]
                pp["quests_done"] = pp.get("quests_done",0) + 1
                loot = roll_loot_table([(n,0.33) for n,_ in tier.get("loot_table",[])])
                if loot: add_item(pp, loot); lines.append(f"🎒 *{pp['username']}* found *{loot}*!")
                if u == raid["party"][0] and award_title(pp, "Raid Leader"):
                    lines.append(f"🏅 *{pp['username']}* earned: *Raid Leader*!")
                lmsgs, leveled = add_exp(pp, tier["exp_reward"], w); save_player(pp)
                lines.append(f"✅ *{pp['username']}* — +{tier['exp_reward']:,} EXP | +{tier['gold_reward']} Gold")
                if leveled and pp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{pp['username']}* reached *Level {pp['level']}* from the raid! 🏰",
                        permanent=True))
    save_player(p); await send_group(update, "\n".join(lines), delay=30)

async def raidstatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id not in active_raids:
        await send_group(update, "No active raid."); return
    raid = active_raids[chat_id]
    if not raid.get("in_progress"):
        names = ", ".join(u["name"] for u in raid["party"])
        await send_group(update,
            f"🏰 *Raid Lobby* — {len(raid['party'])} players: {names}\nUse /raidstart."); return
    tier = raid["tier"]; enemy = raid["enemy"]
    names = ", ".join(u["name"] for u in raid["party"])
    await send_group(update,
        f"⚔️ *{tier['name']}*\n👥 {names}\n"
        f"🌊 Wave {raid['wave']}/{len(tier['wave_enemies'])+1} — *{enemy['name']}*\n"
        f"❤️ HP: {raid['enemy_hp']}/{raid['enemy_max_hp']}", delay=20)

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
        f"⚔️ /class — choose your class at Level 5\n"
        f"📊 /allocate — spend stat points\n"
        f"🎁 /daily — claim your daily reward\n"
        f"🗺️ /quest — go on a quest\n"
        f"🗺️ /explore — send yourself on an expedition", delay=30)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{user.first_name}* has ASCENDED! "
        f"Level {slvl} → RPG! 🎱", permanent=True))

# ── CLASS ─────────────────────────────────────────────────────────────────────
async def class_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if p["level"] < 5:
        await send_group(update, f"⚔️ Classes unlock at *Level 5*. You're Level {p['level']}.", delay=9); return
    if p.get("class_id"):
        cls = get_player_class(p)
        path = p.get("class_path","")
        path_str = f" (Path {path})" if path else " (choose path at Lv 10 with /prestige)"
        skills = sjl(p.get("all_skills"), [])
        skill_lines = []
        for sk in skills:
            skill_lines.append(f"  🔸 *{sk['name']}* — {sk['desc']}")
        await send_group(update,
            f"⚔️ You are a *{cls['name']}*{path_str}\n\n"
            f"_{cls['desc']}_\n\n"
            f"🔹 Passive: {cls['skills'][0]['passive']}\n\n"
            f"🔮 Your Skills:\n" + "\n".join(skill_lines) if skill_lines else "None yet",
            delay=30); return
    if not context.args:
        lines = ["⚔️ *Choose your starting class!*\n`/class [name]`\n"]
        for cid in BASE_CLASSES:
            cls = CLASS_TREE[cid]
            sk  = cls["skills"][0]
            lines.append(
                f"*{cls['name']}* — {cls['desc']}\n"
                f"  📈 Primary: {cls['primary_stat']}\n"
                f"  🔹 {sk['passive']}\n"
                f"  🔸 {sk['name']}: {sk['desc']}\n")
        await send_group(update, "\n".join(lines), delay=30); return

    chosen = context.args[0].lower()
    if chosen not in BASE_CLASSES:
        await send_group(update, f"Unknown class. Choose: {', '.join(BASE_CLASSES)}", delay=9); return
    cls = CLASS_TREE[chosen]; p["class_id"] = chosen
    sd = safe_stats(p)
    for stat, bonus in cls.get("stat_bonus",{}).items():
        sd[stat] = sd.get(stat,5) + bonus
    p["stats"] = json.dumps(sd)
    # Unlock tier 1 skill
    sk = cls["skills"][0]
    p["all_skills"] = json.dumps([sk])
    save_player(p)
    asyncio.create_task(announce(context.bot, update.effective_chat.id,
        f"⚔️ *{p['username']}* has chosen *{cls['name']}*!"))
    await send_group(update,
        f"⚔️ *{user.first_name}* is now a *{cls['name']}*!\n\n"
        f"_{cls['desc']}_\n\n"
        f"🔹 Passive: {sk['passive']}\n"
        f"🔸 Active: *{sk['name']}* — {sk['desc']}\n\n"
        f"At *Level 10*, use /prestige to choose your path (A or B).",
        delay=30)

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

    # Already has path — just show status
    if path:
        next_threshold = None
        for lvl in [30,60,100]:
            if p["level"] < lvl:
                next_threshold = lvl; break
        if next_threshold:
            await send_group(update,
                f"🌟 You are on *Path {path}*.\n"
                f"Your class advances automatically at Level *{next_threshold}*.\n"
                f"Keep leveling!", delay=9)
        else:
            await send_group(update,
                f"👑 You have reached *Level 100* — the pinnacle of Path {path}!\n"
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
        lines.append("Use `/prestige A` or `/prestige B` to choose.")
        await send_group(update, "\n".join(lines), delay=60); return

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
        award_title(p, "The Ascended"); save_player(p)
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
        f"🌟 *{p['username']}* chose *Path {chosen_path}* — *{new_cls['name']}*!"))
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
    STAT_NAMES = ["STR","DEF","AGI","INT","WIS"]
    cls = get_player_class(p)
    rec = cls["primary_stat"] + " recommended" if cls else "Free to allocate"
    if not context.args or len(context.args) < 2:
        await send_group(update,
            f"📊 *Stat Allocation* — *{sp}* points available\n\n"
            f"STR:{sd['STR']} DEF:{sd['DEF']} AGI:{sd['AGI']} INT:{sd['INT']} WIS:{sd['WIS']}\n\n"
            f"📌 STR — Attack damage (Warrior)\n"
            f"📌 DEF — Damage reduction\n"
            f"📌 AGI — Dodge & crit (Thief/Archer)\n"
            f"📌 INT — Spell damage (Mage)\n"
            f"📌 WIS — Heal power (Priest)\n\n"
            f"🧭 {rec}\n\nUsage: `/allocate STR 5`", delay=30); return
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
        item = random.choice(["Health Potion","Super Health Potion","Mega Health Potion"])
        add_item(p, item)
    lmsgs, leveled = add_exp(p, 200)
    save_player(p)
    msg = f"🎁 *Daily Reward!*\n\n✨ +200 EXP | 💰 +{gold} Gold"
    if item: msg += f" | 🎒 *{item}* (lucky drop!)"
    else:    msg += f"\n_(No potion today — check the /shop)_"
    if lmsgs: msg += "\n\n" + "\n".join(lmsgs)
    if leveled and p["level"] % 10 == 0:
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🎉 *{p['username']}* reached *Level {p['level']}* from daily! 🎁",
            permanent=True))
    await send_group(update, msg, delay=30)

# ── TRAIN ─────────────────────────────────────────────────────────────────────
TRAIN_MESSAGES = [
    "You drilled your form at the practice board until your arms gave out.",
    "You sparred with a training dummy for hours.",
    "You ran laps across The Felt until your legs burned.",
    "You studied combat technique late into the night.",
    "You meditated on your class abilities and sharpened your instincts.",
    "You pushed through an exhausting session in the back alley.",
    "You reviewed battle tactics and practiced your weaknesses.",
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
    base = 80 + p["level"] * 3
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
        await send_group(update, "💀 You're defeated!", delay=9); return
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
    p["gold"] = p.get("gold",0) + q["gold"]
    p["quests_done"] = p.get("quests_done",0) + 1
    gid = p.get("guild_id")
    if gid and str(gid) != "None":
        g = get_guild(gid)
        if g: add_guild_exp(g, 20); save_guild(g)
    lmsgs, leveled = add_exp(p, q["exp"], w)
    new_t = check_titles(p); save_player(p)
    msg = f"🗺️ *Quest — {q['tier']}*\n\n{q['text']}\n\n✨ +{q['exp']} EXP | 💰 +{q['gold']} Gold"
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

    # Pick zone
    if context.args:
        zn = " ".join(context.args).lower()
        zone = next((z for z in EXPLORE_ZONES if zn in z["name"].lower()), None)
        if not zone:
            zlist = "\n".join(f"• {z['name']} ({z['tier']})" for z in EXPLORE_ZONES)
            await send_group(update, f"Unknown zone. Available:\n{zlist}", delay=15); return
    else:
        if p["level"] <= 5:     elig = [z for z in EXPLORE_ZONES if z["tier"]=="Easy"]
        elif p["level"] <= 15:  elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium"]]
        elif p["level"] <= 30:  elig = [z for z in EXPLORE_ZONES if z["tier"] in ["Easy","Medium","Hard"]]
        elif p["level"] <= 60:  elig = [z for z in EXPLORE_ZONES if z["tier"] != "Legendary"]
        else:                   elig = EXPLORE_ZONES
        zone = random.choice(elig)

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
        await announce(bot, chat_id, msg, permanent=True)

    task = asyncio.create_task(deliver_result())
    explore_timers[user.id] = task

# ── GUILD ─────────────────────────────────────────────────────────────────────
async def guild_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p: await send_group(update, "Use /ascend first!"); return
    if not context.args:
        await send_group(update,
            "🏰 *Guild Commands:*\n"
            "/guild create [name]\n/guild join [name]\n"
            "/guild approve [name]\n/guild deny [name]\n"
            "/guild info\n/guild list\n/guild bank [amount]\n/guild leave", delay=20); return
    sub = context.args[0].lower()

    if sub == "create":
        if len(context.args) < 2: await send_group(update, "Usage: /guild create [name]"); return
        if p.get("guild_id") and str(p.get("guild_id")) != "None":
            await send_group(update, "You're already in a guild!"); return
        if p["gold"] < 100: await send_group(update, "Need 100 gold to found a guild!"); return
        name = " ".join(context.args[1:])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        try:
            c.execute("INSERT INTO guilds (name,leader_id,members,level,exp,bank) VALUES(?,?,?,1,0,0)",
                      (name, user.id, json.dumps([user.id])))
            conn.commit(); gid = c.lastrowid
        except sqlite3.IntegrityError:
            conn.close(); await send_group(update, f"A guild named '{name}' already exists!"); return
        conn.close()
        p["guild_id"] = gid; p["gold"] -= 100
        award_title(p, "Guild Founder"); save_player(p)
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🏰 *{name}* guild founded by *{user.first_name}*!"))
        await send_group(update, f"🏰 *{name}* founded!\n🏅 Title: *Guild Founder*!", delay=20)

    elif sub == "join":
        if len(context.args) < 2: await send_group(update, "Usage: /guild join [name]"); return
        if p.get("guild_id") and str(p.get("guild_id")) != "None":
            await send_group(update, "You're already in a guild!"); return
        name = " ".join(context.args[1:]); g = get_guild_by_name(name)
        if not g: await send_group(update, f"No guild named *{name}* found!"); return
        gid = g["guild_id"]
        if gid not in pending_guild_reqs: pending_guild_reqs[gid] = []
        if any(r["user_id"] == user.id for r in pending_guild_reqs[gid]):
            await send_group(update, "You already have a pending request."); return
        pending_guild_reqs[gid].append({"user_id":user.id,"username":user.first_name})
        leader = get_player(g["leader_id"])
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🏰 *Guild Join Request*\n"
                     f"*{user.first_name}* wants to join *{g['name']}*!\n"
                     f"Leader *{leader['username'] if leader else '?'}*: "
                     f"`/guild approve {user.first_name}` or `/guild deny {user.first_name}`",
                parse_mode="Markdown")
        except Exception: pass
        await send_group(update, f"📨 Request sent to join *{g['name']}*!", delay=20)

    elif sub in ("approve","deny"):
        if len(context.args) < 2:
            await send_group(update, f"Usage: /guild {sub} [username]"); return
        if not p.get("guild_id") or str(p.get("guild_id")) == "None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if not g or g["leader_id"] != user.id:
            await send_group(update, "Only the guild leader can do this."); return
        tn   = " ".join(context.args[1:]).lower()
        gid  = g["guild_id"]
        reqs = pending_guild_reqs.get(gid,[])
        match = next((r for r in reqs if r["username"].lower() == tn), None)
        if not match: await send_group(update, f"No pending request from *{tn}*."); return
        if sub == "approve":
            tp = get_player(match["user_id"])
            if not tp: await send_group(update, "Player not found."); return
            members = sjl(g["members"],[]); members.append(match["user_id"])
            g["members"] = json.dumps(members); save_guild(g)
            tp["guild_id"] = gid; save_player(tp)
            pending_guild_reqs[gid] = [r for r in reqs if r["user_id"] != match["user_id"]]
            await send_group(update, f"✅ *{match['username']}* joined *{g['name']}*!", delay=20)
        else:
            pending_guild_reqs[gid] = [r for r in reqs if r["user_id"] != match["user_id"]]
            await send_group(update, f"❌ *{match['username']}*'s request denied.", delay=9)

    elif sub == "info":
        if not p.get("guild_id") or str(p.get("guild_id")) == "None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if not g: await send_group(update, "Guild not found."); return
        members = sjl(g["members"],[]); leader = get_player(g["leader_id"])
        glvl = safe_int(g.get("level"),1); perk = GUILD_PERKS.get(glvl,{})
        nxt  = guild_exp_for_level(glvl) if glvl < 10 else "MAX"
        await send_group(update,
            f"🏰 *{g['name']}*\n"
            f"👑 Leader: {leader['username'] if leader else '?'}\n"
            f"👥 Members: {len(members)}\n"
            f"⭐ Level: {glvl}/10 | ✨ EXP: {safe_int(g.get('exp'))}/{nxt}\n"
            f"💰 Bank: {safe_int(g.get('bank'))}g\n"
            f"🎁 Perks: _{perk.get('desc','None')}_", permanent=True)

    elif sub == "bank":
        if len(context.args) < 2: await send_group(update, "Usage: /guild bank [amount]"); return
        if not p.get("guild_id") or str(p.get("guild_id")) == "None":
            await send_group(update, "You're not in a guild!"); return
        try: amount = int(context.args[1])
        except: await send_group(update, "Usage: /guild bank [amount]"); return
        if amount <= 0 or p["gold"] < amount:
            await send_group(update, f"Not enough gold! Have {p['gold']}g."); return
        g = get_guild(p["guild_id"])
        if not g: await send_group(update, "Guild not found."); return
        p["gold"] -= amount; g["bank"] = safe_int(g.get("bank")) + amount
        gmsgs = add_guild_exp(g, amount//10)
        save_guild(g); save_player(p)
        msg = f"💰 *{user.first_name}* donated {amount}g! Bank: {g['bank']}g"
        if gmsgs: msg += "\n" + "\n".join(gmsgs)
        await send_group(update, msg, delay=20)

    elif sub == "list":
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT name,level,exp,members FROM guilds ORDER BY level DESC,exp DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows: await send_group(update, "No guilds yet!"); return
        medals = ["🥇","🥈","🥉"]+["🏰"]*7
        lines  = ["🏰 *Guild Leaderboard:*\n"]
        for i, row in enumerate(rows):
            mc = len(sjl(row["members"],[]))
            lines.append(f"{medals[i]} *{row['name']}* — Lv {safe_int(row['level'],1)} | {mc} members")
        await send_group(update, "\n".join(lines), delay=30)

    elif sub == "leave":
        if not p.get("guild_id") or str(p.get("guild_id")) == "None":
            await send_group(update, "You're not in a guild!"); return
        g = get_guild(p["guild_id"])
        if g and g["leader_id"] == user.id:
            await send_group(update, "Leaders can't leave their guild!"); return
        if g:
            members = sjl(g["members"],[])
            if user.id in members: members.remove(user.id)
            g["members"] = json.dumps(members); save_guild(g)
        p["guild_id"] = None; save_player(p)
        await send_group(update, "You've left your guild.", delay=9)

# ── EVENT HANDLERS ────────────────────────────────────────────────────────────
async def greet_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] not in ("traveler","merchant","shrine"): return
    s = get_or_create_shadow(user.id, user.first_name)
    p = get_player(user.id)
    active_events.pop(chat_id, None)

    if event["key"] == "merchant":
        if p:
            set_status(p, "shop_discount_until", 1800)
            save_player(p)
            await send_group(update, f"🛍️ *{user.first_name}* greets the merchant! 20% shop discount for 30 minutes!", delay=20)
        return

    if event["key"] == "shrine":
        if p:
            stat = random.choice(["STR","DEF","AGI","INT","WIS"])
            sd   = safe_stats(p); sd[stat] = sd.get(stat,5) + 5
            p["stats"] = json.dumps(sd); save_player(p)
            await send_group(update, f"🔮 *{user.first_name}* prays at the shrine! +5 {stat} for 2 hours!", delay=20)
        return

    loot = roll_loot_table([(n,c) for n,c in event.get("loot_table",[])])
    exp  = event.get("exp",300)
    if p:
        if loot: add_item(p, loot)
        lmsgs, leveled = add_exp(p, exp); save_player(p)
        msg = f"🧙 *{user.first_name}* greets the traveler! +{exp} EXP"
        if loot: msg += f" | 🎒 Found *{loot}*!"
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}*! 🧙", permanent=True))
        await send_group(update, msg, delay=20)
    else:
        lmsgs, leveled = add_shadow_exp(s, exp); save_shadow(s)
        msg = f"🧙 *{user.first_name}* greets the traveler! +{exp} EXP"
        if leveled and s["level"] % 10 == 0 and not s.get("ascended"):
            asyncio.create_task(announce(context.bot, chat_id,
                f"📈 *{s['username']}* reached *Level {s['level']}*!\n"
                f"_Use /ascend to enter the RPG!_", permanent=True))
        await send_group(update, msg, delay=20)

async def fight_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] not in ("bandit","rival"): return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(10,30); event["enemy_hp"] = event.get("enemy_hp",150) - dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"🗡️ *{user.first_name}* strikes for {dmg}! (HP: {max(0,event['enemy_hp'])}/150)"]
    if event["enemy_hp"] <= 0:
        fighters = event.get("fighters",[user.id]); active_events.pop(chat_id, None)
        lines.append("💀 *Bandit defeated!* Fighters earn +250 EXP!")
        for fid in fighters:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp:
                loot = roll_loot_table(event.get("loot_table",[("Health Potion",0.30)]))
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, 250); save_player(fp)
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}*! ⚔️", permanent=True))
            elif fs:
                lmsgs, leveled = add_shadow_exp(fs, 250); save_shadow(fs)
                if leveled and fs["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"📈 *{fs['username']}* reached *Level {fs['level']}*!", permanent=True))
    await send_group(update, "\n".join(lines), delay=20)

async def shoot_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "ghost": return
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    dmg = random.randint(15,35); event["enemy_hp"] = event.get("enemy_hp",200) - dmg
    event.setdefault("fighters",[])
    if user.id not in event["fighters"]: event["fighters"].append(user.id)
    lines = [f"👻 *{user.first_name}* shoots for {dmg}! (HP: {max(0,event['enemy_hp'])}/200)"]
    if event["enemy_hp"] <= 0:
        fighters = event.get("fighters",[user.id]); active_events.pop(chat_id, None)
        lines.append("✨ *Ghost vanishes!* Fighters earn +300 EXP!")
        for fid in fighters:
            fp = get_player(fid); fs = get_shadow(fid)
            if fp:
                loot = roll_loot_table(event.get("loot_table",[("Health Potion",0.20)]))
                if loot: add_item(fp, loot)
                lmsgs, leveled = add_exp(fp, 300); save_player(fp)
                if leveled and fp["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"🎉 *{fp['username']}* reached *Level {fp['level']}*! 👻", permanent=True))
            elif fs:
                lmsgs, leveled = add_shadow_exp(fs, 300); save_shadow(fs)
                if leveled and fs["level"] % 10 == 0:
                    asyncio.create_task(announce(context.bot, chat_id,
                        f"📈 *{fs['username']}* reached *Level {fs['level']}*! 👻", permanent=True))
    await send_group(update, "\n".join(lines), delay=20)

async def claim_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id; user = update.effective_user
    event = active_events.get(chat_id)
    if not event or event["key"] != "cache": return
    active_events.pop(chat_id, None)
    p = get_player(user.id); s = get_or_create_shadow(user.id, user.first_name)
    loot = roll_loot_table([(n,c) for n,c in event.get("loot_table",[])])
    msg = f"💰 *{user.first_name}* claims the cache!"
    if loot:
        if p: add_item(p, loot); save_player(p)
        msg += f" Found: *{loot}*!"
    await send_group(update, msg, delay=20)

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

async def pray_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await greet_event(update, context)  # reuses greet handler with shrine key

# ── HELP ──────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_group(update,
        f"⚔️ *{WORLD_NAME} v13 — Commands*\n\n"
        "👤 *Everyone:*\n"
        "*/rank* — Leaderboard (paginated)\n"
        "*/rank me* — Your position\n"
        "*/stats* — Your full profile\n"
        "*/ascend* — Enter the RPG\n\n"
        "⚔️ *Combat:*\n"
        "*/attack* — Reply + /attack to strike\n"
        "*/skill* — Show & use class skills\n"
        "*/heal* — Reply + /heal (needs potion or Priest)\n"
        "*/boss [name]* — Start boss fight\n"
        "*/strike* — Attack active boss\n"
        "*/raid* — Start/join raid\n"
        "*/raidstart* — Begin the raid\n"
        "*/raidstrike* — Attack in raid\n"
        "*/raidstatus* — Raid progress\n\n"
        "📱 *RPG:*\n"
        "*/daily* — Daily reward (24h)\n"
        "*/train* — Train (30min)\n"
        "*/quest* — Solo quest (1hr)\n"
        "*/explore* — Expedition (2x/day, 1hr)\n"
        "*/shop* — Daily shop\n"
        "*/inventory* — Your items\n"
        "*/equip [item]* — Equip gear\n"
        "*/use [item]* — Use consumable\n"
        "*/sell [item]* — Sell for gold\n"
        "*/trade [item] [price]* — Trade with player\n"
        "*/accept* — Accept trade offer\n"
        "*/decline* — Decline trade offer\n"
        "*/class* — Choose/view class\n"
        "*/prestige* — Choose path at Lv 10\n"
        "*/allocate STR 5* — Spend stat points\n"
        "*/title [name]* — Equip a title\n"
        "*/cooldowns* — Check timers\n"
        "*/weather* — Table conditions\n"
        "*/guild* — Guild commands\n\n"
        "🎲 *Events:*\n"
        "*/greet* — Greet traveler/merchant\n"
        "*/fight* — Fight bandit\n"
        "*/shoot* — Shoot ghost\n"
        "*/claim* — Claim abandoned cache\n"
        "*/purge* — Purge a curse\n\n"
        "💬 _Chatting earns EXP. Level-up announcements at x10. Secrets lurk._ 🎱",
        delay=60)

# ── WIPE (admin only) ─────────────────────────────────────────────────────────
async def wipe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await send_group(update, "❌ Admin only."); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    for table in ["shadow_profiles","players","guilds","bounties"]:
        c.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit(); conn.close()
    init_db()
    await send_group(update, "💣 *Database wiped and reset.* Fresh start!", permanent=True)

# ── PASSIVE MESSAGE HANDLER ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user    = update.effective_user
    chat_id = update.effective_chat.id
    text    = update.message.text.lower()

    # Random events — every 2500 messages
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    cnt = message_counters[chat_id]
    if cnt % 2500 == 0 and chat_id not in active_events:
        roll = random.random()
        if roll < 0.70:
            pool = [e for e in RANDOM_EVENTS if e["freq"] == "common"]
        elif roll < 0.90:
            pool = [e for e in RANDOM_EVENTS if e["freq"] == "uncommon"]
        else:
            pool = [e for e in RANDOM_EVENTS if e["freq"] == "rare"]
        if pool:
            event = random.choice(pool).copy()
            active_events[chat_id] = event
            # Handle cursed event — pick random player
            if event["key"] == "cursed":
                conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
                c2   = conn.cursor()
                c2.execute("SELECT user_id FROM players ORDER BY RANDOM() LIMIT 1")
                row  = c2.fetchone(); conn.close()
                if row:
                    event["cursed_player_id"] = row["user_id"]
                    cp = get_player(row["user_id"])
                    if cp:
                        cds = safe_cds(cp)
                        cds["cursed_until"] = (datetime.now()+timedelta(hours=1)).isoformat()
                        cp["passive_cooldowns"] = json.dumps(cds)
                        save_player(cp)
            # Storm event — change weather immediately
            if event["key"] == "storm":
                _weather_cache["weather"] = random.choice(WEATHER_TABLE)
                _weather_cache["set_at"]  = datetime.now()
            await update.message.reply_text(event["msg"], parse_mode="Markdown")

    # Wild Drake event — reply to drake message with /strike handled separately
    if chat_id in active_drakes and update.message.reply_to_message:
        drake = active_drakes[chat_id]
        if update.message.reply_to_message.message_id == drake.get("msg_id"):
            if text.startswith("/strike"):
                await _handle_drake_strike(update, context)
                return

    # Shadow profile — always
    s = get_or_create_shadow(user.id, user.first_name)
    was_last_seen = s.get("last_seen")
    s["username"]      = user.first_name
    s["message_count"] = s.get("message_count",0) + 1

    p = get_player(user.id) if s.get("ascended") else None
    if p and s: sync_levels(p, s)

    # Idle reward check
    if was_last_seen:
        try:
            away_hours = (datetime.now()-datetime.fromisoformat(was_last_seen)).total_seconds()/3600
            if away_hours >= 1:
                await check_idle_reward(user, s, p, context.bot, chat_id)
        except Exception:
            pass

    # Cannot earn EXP if defeated
    if p and is_defeated(p):
        s["last_seen"] = datetime.now().isoformat()
        save_shadow(s)
        return

    # Bleed tick
    if p and is_bleeding(p):
        bleed_dmg = check_bleed_tick(p)
        if bleed_dmg > 0:
            save_player(p)
            if p["hp"] == 0:
                p["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
                save_player(p)
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🩸 *{p['username']}* bled out and has been defeated! 6hr cooldown.",
                    permanent=False))

    # Easter eggs
    matched_egg = False
    for egg in EASTER_EGGS:
        if re.search(egg["pattern"], text, re.IGNORECASE):
            if egg.get("secret_boss"):
                w = get_weather()
                if w.get("secret_eligible") and \
                   chat_id not in secret_boss_active and \
                   chat_id not in active_bosses:
                    bd = BOSSES["void"]
                    secret_boss_active[chat_id] = {
                        "data": bd.copy(), "hp": bd["max_hp"],
                        "participants": [{"id":user.id,"name":user.first_name,"dmg":0}]
                    }
                    await update.message.reply_text(
                        f"🌑 *THE VOID BALL AWAKENS!*\n\n_{bd['desc']}_\n\n"
                        f"❤️ HP: {bd['max_hp']}\n\n"
                        f"*{user.first_name}* called it forth! /strike!",
                        parse_mode="Markdown")
            matched_egg = True; break

    # EXP accumulation
    shadow_exp = 0; rpg_exp = 0; rpg_gold = 0
    cds_s = safe_cds(s)
    cds_p = safe_cds(p) if p else {}

    if not matched_egg:
        for trigger in KEYWORD_TRIGGERS:
            if re.search(trigger["pattern"], text, re.IGNORECASE):
                key = trigger["key"]
                if not cds_s.get(key) or \
                   datetime.now() > datetime.fromisoformat(cds_s[key]) + timedelta(seconds=trigger["cooldown"]):
                    cds_s[key] = datetime.now().isoformat()
                    exp = trigger["exp"]
                    if exp > 0:
                        shadow_exp += exp
                        if p: rpg_exp += exp
                    elif exp < 0:
                        s["exp"] = max(0, s["exp"] + exp)
                        if p: p["exp"] = max(0, p["exp"] + exp)
                    if trigger.get("gold_chance") and random.random() < trigger["gold_chance"]:
                        rpg_gold += 1
                break  # only first matching trigger

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
            f"🔥 *{user.first_name}* hit a *50 message streak!* +150 EXP!"))
    if dm >= 100 and not cds_s.get("streak_100"):
        cds_s["streak_100"] = True; shadow_exp += 300; rpg_gold += 10
        if p: rpg_exp += 300
        asyncio.create_task(announce(context.bot, chat_id,
            f"🔥 *{user.first_name}* hit a *100 message streak!* +300 EXP!"))
    if dm >= 500 and not cds_s.get("streak_500"):
        cds_s["streak_500"] = True; shadow_exp += 800
        if p: rpg_exp += 800
        asyncio.create_task(announce(context.bot, chat_id,
            f"🏆 *{user.first_name}* hit a *500 message streak!* +800 EXP! 🎱"))

    # Apply shadow EXP
    s["passive_cooldowns"] = json.dumps(cds_s)
    s["last_seen"]          = datetime.now().isoformat()
    if shadow_exp > 0:
        lmsgs, did_level = add_shadow_exp(s, shadow_exp)
        save_shadow(s)
        if did_level and s["level"] % 10 == 0:
            hint = ""
            if s["level"] >= 5 and not s.get("ascended"):
                hint = "\n_Use /ascend to enter the World of 8Ball!_"
            tier = get_tier(s["level"])
            asyncio.create_task(announce(context.bot, chat_id,
                f"{tier['emoji']} *{s['username']}* reached *Level {s['level']}*!{hint}",
                permanent=True))
    else:
        save_shadow(s)

    # Apply RPG EXP
    if p:
        p["gold"]             = p.get("gold",0) + rpg_gold
        p["passive_cooldowns"] = json.dumps(cds_p)
        if rpg_exp > 0:
            lmsgs, did_level = add_exp(p, rpg_exp)
            if did_level and p["level"] > s["level"]:
                s["level"] = p["level"]; s["exp"] = 0; save_shadow(s)
            save_player(p)
            if did_level and p["level"] % 10 == 0:
                cls = get_player_class(p)
                cnote = f" the *{cls['name']}*" if cls else ""
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🎉 *{p['username']}*{cnote} reached *Level {p['level']}*! 🎱",
                    permanent=True))
        else:
            save_player(p)

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
            lines.append(f"✅ *{fp['username']}* — {int(share*100)}% dmg | +{exp} EXP"
                         + (f" | 🎒 {loot}" if loot else ""))
            if leveled and fp["level"] % 10 == 0:
                asyncio.create_task(announce(context.bot, chat_id,
                    f"🎉 *{fp['username']}* reached *Level {fp['level']}*! 🐉", permanent=True))
        await announce(context.bot, chat_id, "\n".join(lines), permanent=True)
    else:
        await announce(context.bot, chat_id,
            f"🐉 *{user.first_name}* hits the Drake for *{dmg}*! ❤️ HP: {drake['hp']}/500")

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Universal
    app.add_handler(CommandHandler("rank",        rank_cmd))
    app.add_handler(CommandHandler("stats",       stats_cmd))
    app.add_handler(CommandHandler("help",        help_cmd))
    app.add_handler(CommandHandler("weather",     weather_cmd))
    app.add_handler(CommandHandler("ascend",      ascend_cmd))
    app.add_handler(CommandHandler("wipe",        wipe_cmd))

    # Combat
    app.add_handler(CommandHandler("attack",      attack_cmd))
    app.add_handler(CommandHandler("skill",       skill_cmd))
    app.add_handler(CommandHandler("heal",        heal_cmd))
    app.add_handler(CommandHandler("boss",        boss_cmd))
    app.add_handler(CommandHandler("strike",      strike_cmd))
    app.add_handler(CommandHandler("raid",        raid_cmd))
    app.add_handler(CommandHandler("raidstart",   raidstart_cmd))
    app.add_handler(CommandHandler("raidstrike",  raidstrike_cmd))
    app.add_handler(CommandHandler("raidstatus",  raidstatus_cmd))

    # RPG
    app.add_handler(CommandHandler("daily",       daily_cmd))
    app.add_handler(CommandHandler("train",       train_cmd))
    app.add_handler(CommandHandler("quest",       quest_cmd))
    app.add_handler(CommandHandler("explore",     explore_cmd))
    app.add_handler(CommandHandler("shop",        shop_cmd))
    app.add_handler(CommandHandler("inventory",   inventory_cmd))
    app.add_handler(CommandHandler("equip",       equip_cmd))
    app.add_handler(CommandHandler("use",         use_cmd))
    app.add_handler(CommandHandler("sell",        sell_cmd))
    app.add_handler(CommandHandler("trade",       trade_cmd))
    app.add_handler(CommandHandler("accept",      accept_trade_cmd))
    app.add_handler(CommandHandler("decline",     decline_trade_cmd))
    app.add_handler(CommandHandler("class",       class_cmd))
    app.add_handler(CommandHandler("prestige",    prestige_cmd))
    app.add_handler(CommandHandler("allocate",    allocate_cmd))
    app.add_handler(CommandHandler("title",       title_cmd))
    app.add_handler(CommandHandler("cooldowns",   cooldowns_cmd))
    app.add_handler(CommandHandler("guild",       guild_cmd))

    # Events
    app.add_handler(CommandHandler("greet",       greet_event))
    app.add_handler(CommandHandler("fight",       fight_event))
    app.add_handler(CommandHandler("shoot",       shoot_event))
    app.add_handler(CommandHandler("claim",       claim_event))
    app.add_handler(CommandHandler("purge",       purge_event))
    app.add_handler(CommandHandler("pray",        pray_event))

    # Callbacks
    app.add_handler(CallbackQueryHandler(rank_callback,       pattern="^rank_p_"))
    app.add_handler(CallbackQueryHandler(skill_info_callback, pattern="^skill_info_"))

    # Passive handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"🎱 {WORLD_NAME} v13 is running...")
    app.run_polling(poll_interval=0.3)

if __name__ == "__main__":
    main()
# ── SHOP ──────────────────────────────────────────────────────────────────────
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
            guild_disc = 0.10 if glvl >= 7 else (0.15 if glvl >= 10 else 0)
            discount = max(discount, guild_disc)

    if not context.args:
        shop = get_daily_shop()
        lines = [f"🛒 *Daily Shop* | 💰 {p['gold']} gold\n"]
        if discount: lines.append(f"🏷️ Discount active: *{int(discount*100)}% off!*\n")
        for i, entry in enumerate(shop, 1):
            price = round(entry["price"] * (1-discount))
            lines.append(f"{i}. *{entry['item']}* — {price}g\n   _{entry['desc']}_")
        lines.append(f"\n`/shop buy [1-{len(shop)}]` to purchase.")
        await send_group(update, "\n".join(lines), delay=30); return

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
async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    inv = Counter(sjl(p.get("inventory"), []))
    if not inv:
        await send_group(update, "🎒 Your inventory is empty!", delay=9); return
    lines = [f"🎒 *{p['username']}'s Inventory:*\n"]
    for item, count in inv.items():
        desc = ""
        for pool in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS, CONSUMABLES]:
            if item in pool:
                d = pool[item]
                if "atk" in d:   desc = f"+{d['atk']} ATK"
                elif "def" in d: desc = f"+{d['def']} DEF"
                elif "desc" in d: desc = d["desc"]
                rarity = RARITY_EMOJI.get(d.get("rarity",""),"")
                break
        lines.append(f"{rarity} *{item}* x{count} — _{desc}_")
    lines.append("\n_/equip [item] to equip | /sell [item] to sell | /use [item] to use_")
    await send_group(update, "\n".join(lines), delay=30)

async def equip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        await send_group(update, "Usage: `/equip [item name]`", delay=9); return
    item_name = " ".join(context.args)
    inv = sjl(p.get("inventory"), [])
    if item_name not in inv:
        await send_group(update, f"You don't have *{item_name}* in your inventory!", delay=9); return

    # Determine item type and equip
    if item_name in WEAPONS:
        ok, reason = can_equip_weapon(p, item_name)
        if not ok:
            await send_group(update, f"❌ {reason}", delay=9); return
        old = p.get("equipped_weapon")
        p["equipped_weapon"] = item_name
        inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        w = WEAPONS[item_name]
        await send_group(update,
            f"⚔️ Equipped *{item_name}* (+{w['atk']} ATK)\n"
            + (f"_Unequipped {old}_" if old else ""), delay=15)
    elif item_name in ARMORS:
        ok, reason = can_equip_armor(p, item_name)
        if not ok:
            await send_group(update, f"❌ {reason}", delay=9); return
        old = p.get("equipped_armor")
        p["equipped_armor"] = item_name
        inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        a = ARMORS[item_name]
        await send_group(update,
            f"🛡️ Equipped *{item_name}* (+{a['def']} DEF)\n"
            + (f"_Unequipped {old}_" if old else ""), delay=15)
    elif item_name in SHIELDS:
        s_data = SHIELDS[item_name]
        cls_line = get_class_line(p)
        path = p.get("class_path")
        if cls_line != "warrior" or path != "A":
            await send_group(update,
                "❌ Only Warrior Path A (Page/Squire/Knight/Paladin) can use shields.", delay=9); return
        old = p.get("equipped_shield")
        p["equipped_shield"] = item_name
        inv.remove(item_name)
        if old: inv.append(old)
        p["inventory"] = json.dumps(inv); save_player(p)
        await send_group(update,
            f"🔰 Equipped *{item_name}* (+{s_data['def']} DEF)\n"
            + (f"_Unequipped {old}_" if old else ""), delay=15)
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

async def use_item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        await send_group(update, "Usage: `/use [item name]`", delay=9); return
    item = " ".join(context.args)
    inv  = sjl(p.get("inventory"), [])
    if item not in inv:
        await send_group(update, f"You don't have *{item}*!", delay=9); return
    inv.remove(item); p["inventory"] = json.dumps(inv)
    msg = f"✅ Used *{item}*. "
    if item == "Health Potion":
        p["hp"] = min(p["max_hp"], p["hp"]+50); msg += f"❤️ +50 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Super Health Potion":
        p["hp"] = min(p["max_hp"], p["hp"]+100); msg += f"❤️ +100 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Mega Health Potion":
        p["hp"] = min(p["max_hp"], p["hp"]+200); msg += f"❤️ +200 HP ({p['hp']}/{p['max_hp']})"
    elif item == "Revival Charm":
        p["defeated_until"] = None
        p["invincible_until"] = (datetime.now()+timedelta(hours=1)).isoformat()
        p["hp"] = p["max_hp"]//2
        msg += f"💚 Revived! {p['hp']} HP. 1hr invincibility granted."
    else:
        msg += "_(No direct effect — used as crafting material or quest item)_"
    save_player(p)
    await send_group(update, msg, delay=15)

async def sell_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        await send_group(update, "Usage: `/sell [item name]`", delay=9); return
    item = " ".join(context.args)
    inv  = sjl(p.get("inventory"), [])
    if item not in inv:
        await send_group(update, f"You don't have *{item}*!", delay=9); return
    # Determine sell price (50% of base value)
    price = 0
    for pool in [WEAPONS, ARMORS, ACCESSORIES, SHIELDS]:
        if item in pool:
            d = pool[item]
            rarity_prices = {"common":20,"uncommon":60,"rare":200,"epic":600,"legendary":2000}
            price = rarity_prices.get(d.get("rarity","common"),20)
            break
    for pool2 in [CONSUMABLES]:
        if item in pool2:
            price = pool2[item].get("sell",10); break
    if price == 0: price = 10
    inv.remove(item); p["inventory"] = json.dumps(inv)
    p["gold"] = p.get("gold",0) + price
    save_player(p)
    await send_group(update,
        f"💰 Sold *{item}* for *{price} gold*!\nTotal: {p['gold']}g", delay=15)

# ── BOSS ──────────────────────────────────────────────────────────────────────
async def boss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated!", delay=9); return
    chat_id = update.effective_chat.id
    if chat_id in active_bosses:
        boss = active_bosses[chat_id]
        if user.id not in [u["id"] for u in boss["participants"]]:
            boss["participants"].append({"id":user.id,"name":user.first_name,"dmg":0})
        await send_group(update,
            f"⚔️ *{user.first_name}* joins *{boss['data']['name']}*!\n"
            f"❤️ {boss['hp']}/{boss['data']['max_hp']} HP | Use /strike!", delay=15); return
    if not context.args:
        bl = "\n".join(f"• `{k}` — {v['name']} (HP:{v['max_hp']} | EXP:{v['exp']})"
                       for k,v in BOSSES.items() if not v.get("secret"))
        await send_group(update, f"⚔️ *Available Bosses:*\n\n{bl}\n\nExample: `/boss 1 ball`", delay=30); return
    key = " ".join(context.args).lower(); bd = BOSSES.get(key)
    if not bd or bd.get("secret"):
        await send_group(update, "Unknown boss. Try `/boss` to see the list.", delay=9); return
    active_bosses[chat_id] = {"data":bd.copy(),"hp":bd["max_hp"],
                               "participants":[{"id":user.id,"name":user.first_name,"dmg":0}]}
    await send_group(update,
        f"🎱 *{bd['name']} HAS APPEARED!*\n\n_{bd['desc']}_\n\n"
        f"❤️ HP: {bd['max_hp']} | 💀 {bd['dmg_min']}–{bd['dmg_max']} dmg\n\n"
        f"*{user.first_name}* engaged!\nOthers: `/boss {key}` | All: /strike",
        permanent=True)

async def strike_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id); chat_id = update.effective_chat.id
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if is_defeated(p):
        await send_group(update, "💀 You're defeated!", delay=9); return

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

    # Boss counterattack (80% chance, lethal)
    alive = [u for u in boss_dict["participants"]
             if not is_defeated(get_player(u["id"]))]
    if alive and boss_dict["hp"] > 0 and random.random() < 0.80:
        target = random.choice(alive)
        tp = get_player(target["id"])
        if tp:
            bdmg = calc_defense(tp, random.randint(
                boss_dict["data"]["dmg_min"], boss_dict["data"]["dmg_max"]))
            tp["hp"] = max(0, tp["hp"] - bdmg)
            if tp["hp"] == 0:
                tp["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
                lines.append(f"💀 *{boss_dict['data']['name']}* KILLS *{target['name']}*! 6hr defeat.")
            else:
                lines.append(f"💥 *{boss_dict['data']['name']}* hits *{target['name']}* for {bdmg}!")
            save_player(tp)

    # Check if all players dead — end fight
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
            lines.append(f"✅ *{pp['username']}* — +{data['exp']} EXP | +{data['gold']} Gold")
            if leveled and pp["level"] % 10 == 0:
                asyncio.create_task(announce(update.get_bot(), chat_id,
                    f"🎉 *{pp['username']}* reached *Level {pp['level']}* defeating "
                    f"{data['name']}! 🏆", permanent=True))

    save_player(p)
    await send_group(update, "\n".join(lines), delay=30)

# ── GUILD ─────────────────────────────────────────────────────────────────────
async def guild_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if not context.args:
        await send_group(update,
            "🏰 *Guild Commands:*\n"
            "/guild create [name] — 100g to found\n"
            "/guild join [name] — request to join\n"
            "/guild approve [name] — leader approves\n"
            "/guild deny [name] — leader denies\n"
            "/guild info — your guild info\n"
            "/guild list — top guilds\n"
            "/guild bank [amount] — donate gold\n"
            "/guild leave — leave your guild", delay=15); return
    sub = context.args[0].lower()
    if sub == "create":
        if len(context.args) < 2:
            await send_group(update, "Usage: /guild create [name]", delay=9); return
        if p.get("guild_id") and str(p.get("guild_id")) != "None":
            await send_group(update, "You're already in a guild!", delay=9); return
        if p.get("gold",0) < 100:
            await send_group(update, "Need 100 gold to found a guild!", delay=9); return
        name = " ".join(context.args[1:])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        try:
            c.execute("INSERT INTO guilds (name,leader_id,members,level,exp,bank) VALUES(?,?,?,1,0,0)",
                      (name, user.id, json.dumps([user.id])))
            conn.commit(); gid = c.lastrowid
        except sqlite3.IntegrityError:
            await send_group(update, f"Guild '{name}' already exists!", delay=9)
            conn.close(); return
        conn.close()
        p["guild_id"] = gid; p["gold"] = p.get("gold",0)-100
        award_title(p,"Guild Founder"); save_player(p)
        asyncio.create_task(announce(context.bot, update.effective_chat.id,
            f"🏰 *{name}* guild founded by *{user.first_name}*!"))
        await send_group(update, f"🏰 *{name}* founded!\n🏅 Title: *Guild Founder*!", delay=15)
    elif sub == "join":
        if len(context.args) < 2:
            await send_group(update, "Usage: /guild join [name]", delay=9); return
        name = " ".join(context.args[1:]); g = get_guild_by_name(name)
        if not g:
            await send_group(update, f"No guild named *{name}*.", delay=9); return
        gid = g["guild_id"]
        if gid not in pending_guild_reqs: pending_guild_reqs[gid] = []
        if any(r["user_id"]==user.id for r in pending_guild_reqs[gid]):
            await send_group(update, "Request already pending.", delay=9); return
        pending_guild_reqs[gid].append({"user_id":user.id,"username":user.first_name})
        leader = get_player(g["leader_id"])
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id,
                text=f"🏰 *{user.first_name}* wants to join *{g['name']}*!\n"
                     f"Leader: `/guild approve {user.first_name}` or `/guild deny {user.first_name}`",
                parse_mode="Markdown")
        except: pass
        await send_group(update, f"📨 Request sent to *{g['name']}*!", delay=9)
    elif sub == "approve":
        if len(context.args) < 2:
            await send_group(update, "Usage: /guild approve [username]", delay=9); return
        if not p.get("guild_id"):
            await send_group(update, "You're not in a guild!", delay=9); return
        g = get_guild(p["guild_id"])
        if not g or g["leader_id"] != user.id:
            await send_group(update, "Only the guild leader can approve.", delay=9); return
        tn = " ".join(context.args[1:]).lower()
        reqs = pending_guild_reqs.get(g["guild_id"],[])
        match = next((r for r in reqs if r["username"].lower()==tn), None)
        if not match:
            await send_group(update, f"No pending request from *{tn}*.", delay=9); return
        tp = get_player(match["user_id"])
        if not tp:
            await send_group(update, "Player not found.", delay=9); return
        members = sjl(g["members"],[]); members.append(match["user_id"])
        g["members"] = json.dumps(members); save_guild(g)
        tp["guild_id"] = g["guild_id"]; save_player(tp)
        pending_guild_reqs[g["guild_id"]] = [r for r in reqs if r["user_id"]!=match["user_id"]]
        await send_group(update, f"✅ *{match['username']}* joined *{g['name']}*!", delay=9)
    elif sub == "deny":
        if len(context.args) < 2:
            await send_group(update, "Usage: /guild deny [username]", delay=9); return
        if not p.get("guild_id"):
            await send_group(update, "You're not in a guild!", delay=9); return
        g = get_guild(p["guild_id"])
        if not g or g["leader_id"] != user.id:
            await send_group(update, "Only the guild leader can deny.", delay=9); return
        tn = " ".join(context.args[1:]).lower()
        reqs = pending_guild_reqs.get(g["guild_id"],[])
        match = next((r for r in reqs if r["username"].lower()==tn), None)
        if not match:
            await send_group(update, f"No pending request from *{tn}*.", delay=9); return
        pending_guild_reqs[g["guild_id"]] = [r for r in reqs if r["user_id"]!=match["user_id"]]
        await send_group(update, f"❌ *{match['username']}*'s request denied.", delay=9)
    elif sub == "info":
        if not p.get("guild_id"):
            await send_group(update, "You're not in a guild!", delay=9); return
        g = get_guild(p["guild_id"])
        if not g:
            await send_group(update, "Guild not found.", delay=9); return
        members = sjl(g["members"],[]); leader = get_player(g["leader_id"])
        glvl = safe_int(g.get("level"),1); perk = GUILD_PERKS.get(glvl,{})
        nxt = guild_exp_for_level(glvl) if glvl < 10 else "MAX"
        await send_group(update,
            f"🏰 *{g['name']}*\n"
            f"👑 Leader: {leader['username'] if leader else '?'}\n"
            f"👥 Members: {len(members)}\n"
            f"⭐ Level: {glvl}/10 | EXP: {safe_int(g.get('exp'))}/{nxt}\n"
            f"💰 Bank: {safe_int(g.get('bank'))}g\n"
            f"🎁 Perks: _{perk.get('desc','None')}_",
            permanent=True)
    elif sub == "bank":
        if len(context.args) < 2:
            await send_group(update, "Usage: /guild bank [amount]", delay=9); return
        if not p.get("guild_id"):
            await send_group(update, "You're not in a guild!", delay=9); return
        try: amount = int(context.args[1])
        except:
            await send_group(update, "Usage: /guild bank [amount]", delay=9); return
        if amount <= 0 or p.get("gold",0) < amount:
            await send_group(update, f"Not enough gold! Have {p.get('gold',0)}g.", delay=9); return
        g = get_guild(p["guild_id"])
        if not g:
            await send_group(update, "Guild not found.", delay=9); return
        p["gold"] -= amount; g["bank"] = safe_int(g.get("bank"))+amount
        gmsgs = add_guild_exp(g, amount//10); save_guild(g); save_player(p)
        msg = f"💰 *{user.first_name}* donated {amount}g! Bank: {g['bank']}g"
        if gmsgs: msg += "\n" + "\n".join(gmsgs)
        await send_group(update, msg, delay=15)
    elif sub == "list":
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor()
        c.execute("SELECT name,level,members FROM guilds ORDER BY level DESC LIMIT 10")
        rows = c.fetchall(); conn.close()
        if not rows:
            await send_group(update, "No guilds yet!", delay=9); return
        medals = ["🥇","🥈","🥉"]+["🏰"]*7
        lines = ["🏰 *Guild Leaderboard:*\n"]
        for i, row in enumerate(rows):
            members = len(sjl(row["members"],[]))
            lines.append(f"{medals[i]} *{row['name']}* — Lv {safe_int(row['level'],1)} | {members} members")
        await send_group(update, "\n".join(lines), delay=15)
    elif sub == "leave":
        if not p.get("guild_id"):
            await send_group(update, "You're not in a guild!", delay=9); return
        g = get_guild(p["guild_id"])
        if g and g["leader_id"] == user.id:
            await send_group(update, "Guild leaders can't leave!", delay=9); return
        if g:
            members = sjl(g["members"],[])
            if user.id in members: members.remove(user.id)
            g["members"] = json.dumps(members); save_guild(g)
        p["guild_id"] = None; save_player(p)
        await send_group(update, "You've left your guild.", delay=9)

# ── SKILL MENU (inline buttons) ───────────────────────────────────────────────
async def skill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    cls = get_player_class(p)
    if not cls:
        await send_group(update, "No class yet! Use /class at Level 5.", delay=9); return
    all_skills = sjl(p.get("all_skills"), [])
    if not all_skills:
        await send_group(update, "No skills unlocked yet.", delay=9); return

    if not update.message.reply_to_message and not context.args:
        # Show skill menu with inline buttons
        lines = [f"🔮 *{p['username']}'s Skills:*\n"]
        keyboard = []
        for sk in all_skills:
            # Estimate damage for display
            base_est = 5 + get_weapon_atk(p) + get_stat(p, get_primary_stat(p))//2 + p["level"]//2
            mult = sk.get("mult", 1.0)
            dmg_est = round(base_est * mult) if mult else "varies"
            lines.append(
                f"🔸 *{sk['name']}*\n"
                f"   {sk['desc']}\n"
                f"   Est. damage: ~{dmg_est}\n")
            keyboard.append([InlineKeyboardButton(
                f"Use {sk['name']}", callback_data=f"skill_{sk['name'][:30]}")])
        markup = InlineKeyboardMarkup(keyboard)
        await send_group(update, "\n".join(lines), reply_markup=markup, delay=30); return

    # Direct use — find skill to use
    if context.args:
        skill_name = " ".join(context.args)
        sk = next((s for s in all_skills if s["name"].lower() == skill_name.lower()), None)
        if not sk:
            await send_group(update, f"You don't have a skill named *{skill_name}*.", delay=9); return
    else:
        sk = all_skills[0]  # default to first skill if replying

    await _execute_skill(update, context, p, sk)

async def skill_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("skill_"): return
    skill_name = query.data[6:]
    user = query.from_user; p = get_player(user.id)
    if not p: return
    all_skills = sjl(p.get("all_skills"), [])
    sk = next((s for s in all_skills if s["name"].startswith(skill_name)), None)
    if not sk:
        await query.answer("Skill not found!", show_alert=True); return
    # For offensive skills, prompt for target
    if sk.get("type") in ("self_heal","group_heal","mass_cleanse","dmg_reduction_buff"):
        # No target needed
        class FakeUpdate:
            effective_user = user
            effective_chat = query.message.chat
            message = query.message
            get_bot = lambda self: query.get_bot()
        await _execute_skill(FakeUpdate(), context, p, sk)
    else:
        await query.answer(
            f"Reply to your target's message and use /skill {sk['name']} to strike!",
            show_alert=True)

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
        await send_group(update, f"🛡️ {d['username']} is still recovering — invincible.", delay=9); return
    if is_silenced(p):
        await send_group(update, "🤐 You are silenced — can't use skills!", delay=9); return

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
        # Banish — strip buffs
        buffs_stripped = 0
        for bf in ["blessed_until","holy_field_until"]:
            if d.get(bf): d[bf] = None; buffs_stripped += 1
        wis = get_stat(p,"WIS")
        dmg = wis * 2 * max(1,buffs_stripped)
        set_status(d, "healing_blocked_until", 1800)
        lines.append(f"🔥 *Banish!* Stripped {buffs_stripped} buffs. "
                     f"Cannot gain buffs for 30 minutes!")
    elif stype == "condemn":
        # Holy Wrath — Zealot ultimate
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
    elif stype in ("aoe_recent_attackers","holy_nuke","execute_nuke","fear_kill",
                   "random_aoe","bounce_spell","raid_aoe","bounty","bounty_mark",
                   "bind_attacker","dmg_field","combo_dmg","self_heal_buff",
                   "revive_heal","execution_shot","multihit_crit","pierce_dodge"):
        # Simplified fallback for complex skills
        dmg = round(base * sk.get("mult",1.2))
        lines.append(f"_(Full {stype} effect active)_")

    # Apply defense
    if stype not in ("pierce_all","void_nuke","holy_dmg"):
        dmg = calc_defense(d, dmg)

    d["hp"] = max(0, d["hp"] - dmg)
    lines.append(f"💥 *{dmg} damage* to *{d['username']}*!\n"
                 f"❤️ {d['username']}: {d['hp']}/{d['max_hp']} HP")

    lvl_msgs = []
    if d["hp"] <= 0:
        d["hp"] = 0
        # Check Zealot condemn — revival blocked
        if stype == "condemn":
            d["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
            set_status(d, "revival_blocked_until", 7200)
            lines.append(f"☠️ *{d['username']}* is condemned! Cannot be revived for 2 hours.\n"
                         f"Only a *Saint's Absolution* can counter this.")
        else:
            d["defeated_until"] = (datetime.now()+timedelta(hours=6)).isoformat()
        d["losses"] = d.get("losses",0)+1
        p["wins"]   = p.get("wins",0)+1
        exp_gain = 80 + p["level"]*8
        lmsgs, leveled = add_exp(p, exp_gain, w); lvl_msgs = lmsgs
        lines.append(f"\n💀 *{d['username']}* defeated by *{sk['name']}*! +{exp_gain} EXP")
        if leveled and p["level"] % 10 == 0:
            asyncio.create_task(announce(context.bot, chat_id,
                f"🎉 *{p['username']}* reached *Level {p['level']}* via {sk['name']}! ⚡",
                permanent=True))

    check_titles(p); check_titles(d)
    save_player(p); save_player(d)
    if lvl_msgs: lines.extend(lvl_msgs)
    await update_combat_card(context.bot, chat_id, d,
        f"⚡ *{p['username']}* used *{sk['name']}* for {dmg} dmg",
        finished=(d["hp"]<=0))
    try: await update.message.delete()
    except: pass

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
    lines = [f"⏳ *{p['username']}'s Cooldowns:*\n",
             f"🎁 Daily:   {time_remaining(p.get('last_daily'), 86400)}",
             f"🗺️ Quest:   {time_remaining(p.get('last_quest'), 3600)}",
             f"🏋️ Train:   {time_remaining(p.get('last_train'), 1800)}"]
    today = datetime.now().strftime("%Y-%m-%d")
    exp_count = safe_int(p.get("explore_count_today")) if p.get("explore_date")==today else 0
    lines.append(f"🗺️ Explore: {exp_count}/2 today")
    if is_defeated(p):
        end  = datetime.fromisoformat(p["defeated_until"])
        diff = end - datetime.now()
        m, s = divmod(int(diff.total_seconds()),60); h, m = divmod(m,60)
        lines.append(f"💀 Defeat:  {h}h {m}m remaining")
    if is_invincible(p):
        lines.append(f"🛡️ Invincible: still recovering")
    await send_group(update, "\n".join(lines), delay=15)

async def title_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    titles = safe_titles(p)
    if not context.args:
        await send_group(update,
            f"🏅 *Your Titles:*\n" + "\n".join(f"• {t}" for t in titles) +
            f"\n\nCurrent: *{p['active_title']}*\nUse `/title [name]` to equip.", delay=15); return
    chosen = " ".join(context.args)
    if chosen not in titles:
        await send_group(update, f"You haven't earned *{chosen}* yet!", delay=9); return
    p["active_title"] = chosen; save_player(p)
    await send_group(update, f"🏅 Title set to *{chosen}*!", delay=9)

async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    if len(context.args) < 3:
        await send_group(update,
            "Usage: `/trade @username [item name] [price]`\n\nExample: `/trade @bob Iron Rosary 200`",
            delay=15); return
    # Parse: first arg is @username, last arg is price, middle is item
    target_str = context.args[0].lstrip("@")
    try:
        price = int(context.args[-1])
        item  = " ".join(context.args[1:-1])
    except:
        await send_group(update, "Invalid format. Usage: `/trade @username [item] [price]`", delay=9); return
    inv = sjl(p.get("inventory"),[])
    if item not in inv:
        await send_group(update, f"You don't have *{item}* in your inventory!", delay=9); return
    if price < 0:
        await send_group(update, "Price must be 0 or more.", delay=9); return
    # Store pending trade
    pending_trades[user.id] = {
        "seller_id": user.id, "seller_name": user.first_name,
        "item": item, "price": price,
        "target_username": target_str.lower(),
        "created_at": datetime.now().isoformat()
    }
    await send_group(update,
        f"📦 *Trade Offer Posted!*\n\n"
        f"Selling: *{item}* for *{price}g*\n"
        f"To: @{target_str}\n\n"
        f"_{target_str} can type /accept to complete the trade._", delay=30)

async def accept_trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; p = get_player(user.id)
    if not p:
        await send_group(update, "Use /ascend first!", delay=9); return
    # Find a trade targeted at this user
    trade = None; seller_id = None
    for sid, t in pending_trades.items():
        if t["target_username"] == user.first_name.lower() or \
           t["target_username"] == str(user.username or "").lower():
            trade = t; seller_id = sid; break
    if not trade:
        await send_group(update, "No trade offer found for you!", delay=9); return
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

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_group(update,
        f"⚔️ *{WORLD_NAME} v13 — Commands*\n\n"
        "👤 *Everyone:*\n"
        "*/rank* — Leaderboard (paginated)\n"
        "*/rank me* — Your position\n"
        "*/stats* — Full profile\n"
        "*/ascend* — Enter the RPG (private chat)\n\n"
        "📱 *RPG:*\n"
        "*/class* — Choose class (Lv 5)\n"
        "*/prestige* — Choose path (Lv 10)\n"
        "*/allocate STR 5* — Spend stat points\n"
        "*/skill* — View and use your skills\n"
        "*/daily* — Daily reward (24hr)\n"
        "*/cooldowns* — Check timers\n"
        "*/train* — Train (30min)\n"
        "*/quest* — Go on a quest (1hr)\n"
        "*/explore* — Expedition (1hr, 2x/day)\n"
        "*/shop* — Daily shop\n"
        "*/inventory* — Your items\n"
        "*/equip [item]* — Equip gear\n"
        "*/use [item]* — Use consumable\n"
        "*/sell [item]* — Sell for gold\n"
        "*/trade @user [item] [price]* — Trade\n"
        "*/accept* — Accept a trade offer\n"
        "*/title [name]* — Equip a title\n"
        "*/weather* — Table conditions\n\n"
        "⚔️ *Combat:*\n"
        "*/attack* — Reply + /attack to strike\n"
        "*/heal* — Reply + /heal (needs potion)\n"
        "*/skill* — Reply + /skill to use ability\n"
        "*/boss [name]* — Start boss fight\n"
        "*/strike* — Attack active boss\n\n"
        "🏰 *Guild:*\n"
        "*/guild* — All guild commands\n\n"
        "💬 *Chat earns EXP. Level-ups announced at x10. Secrets lurk...* 🎱",
        delay=30)

# ── WIPE (admin only) ─────────────────────────────────────────────────────────
async def wipe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await send_group(update, "❌ Admin only.", delay=9); return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS shadow_profiles")
    c.execute("DROP TABLE IF EXISTS players")
    c.execute("DROP TABLE IF EXISTS guilds")
    c.execute("DROP TABLE IF EXISTS bounties")
    conn.commit(); conn.close()
    init_db()
    # Clear memory state
    active_bosses.clear(); secret_boss_active.clear()
    active_events.clear(); active_raids.clear()
    combat_cards.clear(); message_counters.clear()
    pending_trades.clear(); pending_guild_reqs.clear()
    await send_group(update,
        "🗑️ *Database wiped and reset.*\n"
        "All players, guilds, and data cleared.\n"
        "Fresh start!", delay=30)

# ── PASSIVE MESSAGE HANDLER ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user    = update.effective_user
    chat_id = update.effective_chat.id
    text    = update.message.text.lower()

    # Random events — every 2500 messages
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    cnt = message_counters[chat_id]
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
                f"🔥 *{user.first_name}* hit a *50 message streak!* +150 EXP!"))
        if dm >= 100 and not cds_s.get("streak_100"):
            cds_s["streak_100"] = True; shadow_exp += 300; rpg_gold += 30
            if p: rpg_exp += 300
            asyncio.create_task(announce(context.bot, chat_id,
                f"🔥 *{user.first_name}* hit a *100 message streak!* +300 EXP!"))
        if dm >= 500 and not cds_s.get("streak_500"):
            cds_s["streak_500"] = True; shadow_exp += 800
            if p: rpg_exp += 800
            asyncio.create_task(announce(context.bot, chat_id,
                f"🏆 *{user.first_name}* hit a *500 message streak!* +800 EXP! 🎱"))

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

    # Drake reply detection — if message is a reply to drake message
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
                    lines.append(f"✅ *{fp['username']}* — +{exp_share} EXP"
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

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # Universal
    app.add_handler(CommandHandler("rank",      rank_cmd))
    app.add_handler(CommandHandler("stats",     stats_cmd))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("weather",   weather_cmd))
    app.add_handler(CommandHandler("ascend",    ascend_cmd))
    app.add_handler(CommandHandler("cooldowns", cooldowns_cmd))

    # Class & progression
    app.add_handler(CommandHandler("class",     class_cmd))
    app.add_handler(CommandHandler("prestige",  prestige_cmd))
    app.add_handler(CommandHandler("allocate",  allocate_cmd))
    app.add_handler(CommandHandler("skill",     skill_cmd))
    app.add_handler(CommandHandler("title",     title_cmd))

    # Activities
    app.add_handler(CommandHandler("daily",     daily_cmd))
    app.add_handler(CommandHandler("train",     train_cmd))
    app.add_handler(CommandHandler("quest",     quest_cmd))
    app.add_handler(CommandHandler("explore",   explore_cmd))

    # Economy
    app.add_handler(CommandHandler("shop",      shop_cmd))
    app.add_handler(CommandHandler("inventory", inventory_cmd))
    app.add_handler(CommandHandler("equip",     equip_cmd))
    app.add_handler(CommandHandler("use",       use_item_cmd))
    app.add_handler(CommandHandler("sell",      sell_cmd))
    app.add_handler(CommandHandler("trade",     trade_cmd))
    app.add_handler(CommandHandler("accept",    accept_trade_cmd))

    # Combat
    app.add_handler(CommandHandler("attack",    attack_cmd))
    app.add_handler(CommandHandler("heal",      heal_cmd))
    app.add_handler(CommandHandler("boss",      boss_cmd))
    app.add_handler(CommandHandler("strike",    strike_cmd))

    # Guild
    app.add_handler(CommandHandler("guild",     guild_cmd))

    # Events
    app.add_handler(CommandHandler("greet",     greet_event))
    app.add_handler(CommandHandler("fight",     fight_event))
    app.add_handler(CommandHandler("shoot",     shoot_event))
    app.add_handler(CommandHandler("claim",     claim_event))
    app.add_handler(CommandHandler("pray",      pray_event))

    # Admin
    app.add_handler(CommandHandler("wipe",      wipe_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(rank_callback,  pattern="^rank_p_"))
    app.add_handler(CallbackQueryHandler(skill_callback, pattern="^skill_"))

    # Passive
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print(f"🎱 {WORLD_NAME} v13 is running...")
    app.run_polling(poll_interval=0.3)

if __name__ == "__main__":
    main()
