# -*- coding: utf-8 -*-
"""Combat-system runtime audit / regression harness for The 8Ball Empire.
Verifies, without a live bot:
  1. every class's finisher (kill condition) is reachable from its OWN kit
  2. the support-skill ally gate (can't heal/revive/buff an enemy)
  3. the deep-audit fixes are intact (ELEMENT_EMOJI, dungeon buffs, no grace)
Run:  python combat_audit.py   (exit 0 = all pass)
"""
import os, tempfile, sys
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("BOT_TOKEN", "x"); os.environ.setdefault("ADMIN_ID", "1")
sys.path.insert(0, "/home/user/8ballWorld")
import main
main.init_db()

fails = []
def check(name, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok: fails.append(name)

# rider-key -> debuff field it applies
RIDER_FIELD = {"bleed":"bleed_stacks", "hex":"hex_turns", "poison":"poison_stacks",
               "distract":"distract_turns", "expose":"exposed_hits", "exposed":"exposed_hits",
               "weaken":"weakened_hits", "burn":"burn_stacks", "mark":"marked_hits"}

print("\n[1] Finisher reachability — each class's kill-condition debuff must be produced by its own kit")
KITS = main.CLASS_KITS
for cls, kc in main._KILL_CONDITIONS.items():
    field, need = kc["conds"][0]
    kit = KITS.get(cls, {})
    # collect per-full-loadout foe-debuff production for `field`
    per_cast = 0
    sources = []
    main_sk = kit.get("main", {})
    rider = main_sk.get("rider", {}) or {}
    for rk, rv in rider.items():
        if RIDER_FIELD.get(rk) == field and isinstance(rv, int):
            per_cast += rv; sources.append(f"main:{rk}+{rv}")
    for slot in ("s1", "s2"):
        for eff in kit.get(slot, {}).get("effect", []) or []:
            tgt, fld, op, val = eff
            if tgt == "foe" and fld == field and op in ("add", "setmax") and isinstance(val, int):
                if op == "add":
                    per_cast += val; sources.append(f"{slot}:{fld}+{val}")
                else:
                    sources.append(f"{slot}:{fld}={val}(cap)")
    # reachable if a single loadout pass already hits threshold, or it stacks over casts
    stacks_ok = per_cast >= need or (per_cast > 0)  # >0 means repeatable casts reach it
    check(f"{cls}: needs {field}>={need}, kit makes +{per_cast}/pass [{', '.join(sources) or 'NONE'}]",
          bool(sources) and stacks_ok)

print("\n[2] _check_kill_condition fires when the debuff is actually present")
for cls, kc in main._KILL_CONDITIONS.items():
    field, need = kc["conds"][0]
    atk = {"user_id":1, "class_id":cls, "class_path":cls}
    # get_class_line must resolve to cls; fall back to setting the line directly
    tgt_no = {field: need-1}; tgt_yes = {field: need}
    # patch get_class_line for a clean unit check
    import types
    orig = main.get_class_line
    main.get_class_line = lambda p, _c=cls: _c
    try:
        no  = main._check_kill_condition(atk, tgt_no)
        yes = main._check_kill_condition(atk, tgt_yes)
    finally:
        main.get_class_line = orig
    check(f"{cls}: below-threshold=False & at-threshold=True", (no is False and yes is True))

print("\n[3] Support ally-gate — support aimed at an ENEMY must not aid them")
a = {"user_id":1, "guild_id":"G", "marriages":"[]"}
ally = {"user_id":2, "guild_id":"G", "marriages":"[]"}
enemy = {"user_id":3, "guild_id":None, "marriages":"[]"}
check("ally recognised", main._are_allies(a, ally) is True)
check("enemy rejected", main._are_allies(a, enemy) is False)
check("self recognised", main._are_allies(a, a) is True)

print("\n[4] Deep-audit fixes intact")
E = main.ELEMENT_EMOJI
check("ELEMENT_EMOJI covers pet+encounter elements",
      all(k in E for k in ("shadow","nature","dark","physical","ice","poison","fire","void")))
buffs = {b["key"] for b in main._DNG_SHRINE_BUFFS}
mods  = {m["key"] for m in main._DNG_FLOOR_MODIFIERS}
check("shrine buffs re-enabled (mp_surge, sharpened)", {"mp_surge","sharpened"} <= buffs)
check("floor modifier re-enabled (silence)", "silence" in mods)
check("opening-grace fully removed", not hasattr(main, "_pvp_start_grace")
                                     and not hasattr(main, "_pvp_grace_remaining"))

print("\n" + ("="*60))
if fails:
    print(f"❌ {len(fails)} FAILURE(S):"); [print("   -", f) for f in fails]; sys.exit(1)
print("✅ ALL COMBAT-AUDIT CHECKS PASSED")
os.remove(os.environ["DB_PATH"])
