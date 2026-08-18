# -*- coding: utf-8 -*-
"""Class balance simulator for The 8Ball Empire.

Builds an optimally-built fighter per class (identical stat BUDGET poured into
that class's own primary stat) and runs turn-by-turn duels using the REAL
calc_attack_damage / calc_defense, plus each class's actual kit: strike mults,
riders, finisher (kill condition), DoTs, AND the survivability skills the kit
grants — shields (halve next hits), vanish (dodge next hits), regen, self-heals,
war-cry ramp and empower.

DoT uses the game's real model: a percentage of the victim's MAX HP per action
(poison_pct / bleed_pct / hex), decaying as stacks run down — not a per-stack
multiplier.

*** READ THIS — the per-class win rates are INDICATIVE, NOT authoritative. ***
A single greedy AI plays every class, so kits whose optimal play differs from
"spam the finisher combo" are misrepresented (e.g. archer never fires Aimed
Shot / Focus here). It also omits path passives, on-hit weapon procs, companion
echoes, crit-tuning and gear. The one ROBUST signal that survives the modeling
noise: %-of-max-HP DoT (poison/bleed/hex) scales with the HP pool and outpaces
flat/stat damage as levels climb — so DoT + sustain classes trend strong at high
HP totals. Treat individual class numbers as hypotheses to verify against REAL
PvP logs, not facts.

Run:  python tests/balance_sim.py [sims_per_matchup]
"""
import os, tempfile, sys, random, statistics
os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db")
os.environ.setdefault("BOT_TOKEN", "x"); os.environ.setdefault("ADMIN_ID", "1")
sys.path.insert(0, "/home/user/8ballWorld")
import main

LEVEL, PRIMARY, DEF_STAT, BASE_STAT = 120, 220, 45, 12
MP_MAX, MP_REGEN, MAX_TURNS = 320, 16, 60
SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 150

RIDER_FIELD = {"bleed":"bleed_stacks","hex":"hex_turns","poison":"poison_stacks",
               "distract":"distract_turns","expose":"exposed_hits","exposed":"exposed_hits",
               "weaken":"weakened_hits","burn":"burn_stacks","mark":"marked_hits"}
# DoT stack-field -> the pct field that carries its per-action % (game model)
DOT_PCT_FIELD = {"poison_stacks":"poison_pct","bleed_stacks":"bleed_pct","burn_stacks":"burn_pct"}
DEFAULT_DOT_PCT = {"poison_stacks":10,"bleed_stacks":8,"burn_stacks":10,"hex_turns":6}
DMG_TAKEN = {"exposed_hits":0.15,"marked_hits":0.20}  # +% damage the victim takes

def make_fighter(cls):
    prim = main._KILL_CONDITIONS[cls]["stat"]
    stats = {k: BASE_STAT for k in ("STR","AGI","INT","WIS","DEX","LUK")}
    stats["DEF"] = DEF_STAT; stats[prim] = PRIMARY
    p = {"user_id": hash(cls)&0xffff, "username":cls, "level":LEVEL,
         "class_id":cls, "class_path":None, "stats":main.json.dumps(stats),
         "perm_dmg_bonus":0, "marriages":"[]"}
    p["max_hp"] = main.calc_max_hp(p); p["hp"] = p["max_hp"]
    return p

def kit(cls): return main.CLASS_KITS.get(cls, {})

def st_new():
    return {"mp":MP_MAX, "cd":{}, "shield":0, "vanish":0, "regen_c":0, "regen_a":0.0,
            "warcry":0, "empower":0.0, "ramp":0,   # ramp = archer Focus / phantom Momentum
            # debuffs WE placed on the FOE:
            "foe": {}, "foe_pct": {}}

def apply_skill_effects(st, sk):
    """Apply a skill's self-buffs into st, and return its foe-debuffs dict."""
    for eff in sk.get("effect", []) or []:
        tgt, fld, op, val = eff
        if tgt == "self":
            if fld == "shield_charges" and op=="add": st["shield"] += val
            elif fld == "vanish_turns" and op=="add": st["vanish"] += val
            elif fld == "regen_charges" and op=="add": st["regen_c"] += val
            elif fld == "regen_amt" and op=="setmax": st["regen_a"] = max(st["regen_a"], val)
            elif fld == "warcry_stacks" and op=="add": st["warcry"] += val
            elif fld == "empower_next" and op=="set": st["empower"] = val
        elif tgt == "foe":
            if fld in DOT_PCT_FIELD.values() and op=="setmax":
                st["foe_pct"][fld] = max(st["foe_pct"].get(fld,0), val)
            elif isinstance(val, int) and op=="add":
                st["foe"][fld] = st["foe"].get(fld,0) + val
    # riders (main strike) — foe debuffs
    for rk, rv in (sk.get("rider", {}) or {}).items():
        f = RIDER_FIELD.get(rk)
        if f and isinstance(rv, int):
            st["foe"][f] = st["foe"].get(f,0) + rv

def dot_on(victim_p, attacker_st):
    """Damage the victim takes this action from the attacker's placed DoTs."""
    dmg = 0
    for field in ("poison_stacks","bleed_stacks","burn_stacks","hex_turns"):
        stacks = attacker_st["foe"].get(field,0)
        if stacks <= 0: continue
        pctfield = DOT_PCT_FIELD.get(field)
        pct = attacker_st["foe_pct"].get(pctfield, DEFAULT_DOT_PCT[field]) if pctfield else DEFAULT_DOT_PCT[field]
        dmg += victim_p["max_hp"] * (pct/100.0)
        attacker_st["foe"][field] = stacks - 1
    return dmg

def has_heal(sk): return sk and (sk.get("heal_pct",0) > 0)

def take_hit(def_st, raw):
    """Apply defender's vanish/shield to an incoming raw damage number."""
    if def_st["vanish"] > 0:
        def_st["vanish"] -= 1; return 0
    if def_st["shield"] > 0:
        def_st["shield"] -= 1; return raw * 0.5   # kits say 'halve the next hits'
    return raw

def act(me_p, me_st, foe_p, foe_st, my_hp_frac):
    """One action. Returns raw damage aimed at the foe (before foe mitigation)."""
    cls = me_p["class_id"]; k = kit(cls); kc = main._KILL_CONDITIONS[cls]
    field, need = kc["conds"][0]
    me_st["mp"] = min(MP_MAX, me_st["mp"]+MP_REGEN)
    for s in list(me_st["cd"]):
        me_st["cd"][s]-=1
        if me_st["cd"][s]<=0: del me_st["cd"][s]
    # start-of-turn regen
    heal = 0
    if me_st["regen_c"] > 0:
        heal += me_p["max_hp"] * me_st["regen_a"]; me_st["regen_c"] -= 1
    def ready(slot):
        sk=k.get(slot); return sk and slot not in me_st["cd"] and me_st["mp"]>=sk.get("mp",0)
    def use(slot):
        sk=k[slot]; me_st["mp"]-=sk.get("mp",0)
        if sk.get("cd"): me_st["cd"][slot]=sk["cd"]
        return sk
    me_p["hp"] = min(me_p["max_hp"], me_p["hp"]+heal)

    # 1) survive: low HP + a heal skill available
    if my_hp_frac < 0.40:
        for slot in ("s2","s1"):
            sk=k.get(slot)
            if has_heal(sk) and ready(slot):
                use(slot); apply_skill_effects(me_st, sk)
                me_p["hp"] = min(me_p["max_hp"], me_p["hp"]+me_p["max_hp"]*sk["heal_pct"])
                return 0
    # 2) finisher
    if me_st["foe"].get(field,0) >= need and me_st["mp"]>=20:
        me_st["mp"]-=20
        fin = main.get_stat(me_p, kc["stat"]) * kc.get("mult",6.0)
        if kc.get("drain_pct"): fin += foe_p["max_hp"]*foe_st_hpfrac[0]*kc["drain_pct"]
        me_st["foe"][field]=0
        return fin  # burst — bypasses normal mitigation
    # 3) build the finisher debuff
    for slot in ("s2","s1"):
        sk=k.get(slot)
        if not sk: continue
        adv = any(t=="foe" and (RIDER_FIELD.get(fx,fx)==field or fx==field)
                  for (t,fx,o,v) in (sk.get("effect") or []))
        if adv and ready(slot) and me_st["foe"].get(field,0)<need:
            use(slot); apply_skill_effects(me_st, sk); return 0
    # 4) main strike
    sk=k.get("main",{}); mult=1.0
    if sk and me_st["mp"]>=sk.get("mp",0) and "main" not in me_st["cd"]:
        me_st["mp"]-=sk.get("mp",0)
        if sk.get("cd"): me_st["cd"]["main"]=sk["cd"]
        mult=sk.get("mult",1.0); apply_skill_effects(me_st, sk)
    # Signature ramps build from EVERY attack (incl. basics): archer Focus
    # (+25%/stack) and phantom Momentum (+8%/stack).
    _mainr = (k.get("main",{}).get("rider",{}) or {})
    if _mainr.get("focus"):
        me_st["ramp"] = min(4, me_st["ramp"]+1); mult *= 1 + 0.25*me_st["ramp"]
    elif _mainr.get("momentum"):
        me_st["ramp"] = min(8, me_st["ramp"]+1); mult *= 1 + 0.08*me_st["ramp"]
    try: base = main.calc_attack_damage(me_p)
    except Exception: base = me_p["level"]*4
    dmg = base*mult
    dmg *= 1 + 0.15*me_st["warcry"]
    if me_st["empower"]>0: dmg *= 1+me_st["empower"]; me_st["empower"]=0
    if random.random() < 0.10 + (sk.get("rider",{}).get("crit",0) if sk else 0) + main.get_stat(me_p,"LUK")*0.002:
        dmg *= 1.6
    for f,e in DMG_TAKEN.items():
        if me_st["foe"].get(f,0)>0: dmg *= 1+e; me_st["foe"][f]-=1
    return dmg

foe_st_hpfrac = [1.0]  # tiny shared cell for finisher drain read

def duel(a_cls, b_cls):
    A, B = make_fighter(a_cls), make_fighter(b_cls)
    Ast, Bst = st_new(), st_new()
    fighters = [(A,Ast),(B,Bst)]
    for turn in range(MAX_TURNS*2):
        me, mest = fighters[turn%2]; foe, foest = fighters[(turn+1)%2]
        me["hp"] -= dot_on(me, foest)          # DoTs the foe placed tick on me
        if me["hp"] <= 0: return ("b" if turn%2==0 else "a"), turn//2
        foe_st_hpfrac[0] = max(0.0, foe["hp"]/foe["max_hp"])
        raw = act(me, mest, foe, foest, me["hp"]/me["max_hp"])
        if raw > 0:
            dealt = take_hit(foest, raw)
            if dealt > 0 and raw < main.get_stat(me,"STR")*99:  # normal hit → mitigate
                try: dealt = main.calc_defense(foe, round(dealt))
                except Exception: dealt = round(dealt*0.6)
            foe["hp"] -= dealt
        if foe["hp"] <= 0: return ("a" if turn%2==0 else "b"), turn//2
    return ("a" if A["hp"]>=B["hp"] else "b"), MAX_TURNS

def run():
    classes = list(main._KILL_CONDITIONS.keys())
    print(f"Balance sim — {len(classes)} classes, {SIMS} duels/matchup, Lv{LEVEL}, "
          f"primary={PRIMARY}/DEF={DEF_STAT}\n(models kit mults, riders, finishers, real %-DoT, "
          f"shields, vanish, regen, self-heals)\n")
    wins={c:0 for c in classes}; games={c:0 for c in classes}; ttk=[]
    for a in classes:
        for b in classes:
            if a==b: continue
            for _ in range(SIMS):
                w,t = duel(a,b)
                if w=="a": wins[a]+=1
                else: wins[b]+=1
                games[a]+=1; games[b]+=1; ttk.append(t)
    print("── Overall win rate (avg vs all opponents) ──")
    for c in sorted(classes, key=lambda c: wins[c]/games[c], reverse=True):
        wr=wins[c]/games[c]*100
        flag="  ⚠️ STRONG" if wr>60 else ("  ⚠️ WEAK" if wr<40 else "")
        print(f"  {c:15} {wr:5.1f}%  {'█'*round(wr/3)}{flag}")
    print(f"\nMedian TTK: {statistics.median(ttk):.0f} turns "
          f"(p10={statistics.quantiles(ttk,n=10)[0]:.0f}, p90={statistics.quantiles(ttk,n=10)[-1]:.0f})")
    out=[c for c in classes if not (0.40<=wins[c]/games[c]<=0.60)]
    print("\n"+"="*56)
    print("⚠️ Outliers (outside 40–60%): "+", ".join(out) if out
          else "✅ Every class lands within 40–60% overall.")
    os.remove(os.environ["DB_PATH"])

if __name__ == "__main__":
    run()
