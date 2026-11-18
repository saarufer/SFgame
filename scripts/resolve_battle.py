#!/usr/bin/env python3
"""宏观战斗结算（托管的仗）。规则见 rules/combat.md、rules/units.md、rules/terrain.md。
玩家亲临指挥的仗，用 scripts/tactical.py。

用法：
  python3 scripts/resolve_battle.py battle.json
  echo '{...}' | python3 scripts/resolve_battle.py
  python3 scripts/resolve_battle.py battle.json --trials 2000   # 只跑统计：攻方胜率、平均伤亡

输入 JSON（旧格式照样能用，新字段都可省略）：
{
  "terrain": "plain|steppe|river|forest|mountain|pass|city",
  "fortification": 0,            # 城防，仅 city 有效
  "intensity": "assault|skirmish",
  "seed": 123,                   # 可选，便于复现
  "attacker": {"name": "马军", "commander": "某将", "统率": 6, "武勇": 9, "charge": true,
               "units": {"cavalry": 2000, "infantry": 500}, "morale": 80,
               "tactic": "ambush|surprised|formed|none",
               "formed": false,    # 新增：步阵严整、有准备（拒马、列阵待敌）
               "armor": "barded",  # 可选：护甲，整方一个值，或按兵种 {"heavy_cavalry": "barded", "infantry": "light"}
               "drill": "elite",   # 可选：操练，写法同上
               "morale_bonus": 0}, # 可选：开战前士气的加减，例如阵前单挑的胜负（scripts/contest.py 给出），加完夹在 0–100
  "defender": {...同上}
}

兵种代码可用别名（见 UNIT_ALIASES），输出的伤亡按输入时写的代码返回，可以直接写回存档。
护甲：none 无甲、light 皮甲、heavy 铁甲、barded 人马俱甲（也可写中文）；操练：raw 新募、regular 堪战、elite 精锐。
不写就用兵种表的默认值（rules/units.md）。伤亡怎么算见 rules/combat.md“伤亡”一节。
"""
import statistics
import json
import random
import sys

# ---------------------------------------------------------------- 兵种
# cls: shock=冲击骑兵, ha=骑射, foot=近战步兵, missile=弓弩
# anti_cav: 严整时抵消骑兵冲击的程度（0~1）
# armor/drill: 默认护甲、操练；pen: 破甲（把对方护甲的作用抵消几成）；pursue: 追击能力（每人）
UNITS = {
    "infantry":      {"name": "步卒", "cls": "foot", "base": 1.0, "anti_cav": 0.7,
                      "armor": "light", "drill": "regular", "pen": 0.15, "pursue": 0.08},
    "spear":         {"name": "长枪手", "cls": "foot", "base": 1.0, "anti_cav": 1.0,
                      "armor": "light", "drill": "regular", "pen": 0.2, "pursue": 0.06},
    "militia":       {"name": "民兵", "cls": "foot", "base": 0.6, "anti_cav": 0.4,
                      "armor": "none", "drill": "raw", "pen": 0.0, "pursue": 0.05},
    "archer":        {"name": "弓弩手", "cls": "missile", "base": 1.0, "anti_cav": 0.3,
                      "armor": "none", "drill": "regular", "pen": 0.0, "pursue": 0.05},
    "crossbow":      {"name": "弩手", "cls": "missile", "base": 1.05, "anti_cav": 0.3,
                      "armor": "none", "drill": "regular", "pen": 0.3, "pursue": 0.05},
    "cavalry":       {"name": "骑兵", "cls": "shock", "base": 1.6, "anti_cav": 0,
                      "armor": "light", "drill": "regular", "pen": 0.15, "pursue": 1.0},
    "heavy_cavalry": {"name": "具装骑兵", "cls": "shock", "base": 2.2, "anti_cav": 0,
                      "armor": "barded", "drill": "regular", "pen": 0.5, "pursue": 0.7},
    "horse_archer":  {"name": "骑射", "cls": "ha", "base": 1.5, "anti_cav": 0,
                      "armor": "light", "drill": "regular", "pen": 0.0, "pursue": 0.8},
}
# 护甲：近战、箭矢能透进来几成（未计破甲）；战力修正（只在改了默认护甲时按比值计）
ARMOR = {
    "none":   {"name": "无甲", "melee": 1.0, "missile": 1.0, "power": 0.9},
    "light":  {"name": "皮甲", "melee": 0.8, "missile": 0.75, "power": 1.0},
    "heavy":  {"name": "铁甲", "melee": 0.55, "missile": 0.4, "power": 1.12},
    "barded": {"name": "人马俱甲", "melee": 0.4, "missile": 0.25, "power": 1.25},
}
ARMOR_ALIASES = {"无甲": "none", "皮甲": "light", "leather": "light", "铁甲": "heavy", "iron": "heavy",
                 "明光甲": "heavy", "人马俱甲": "barded", "具装": "barded", "cataphract": "barded"}
# 操练：战力、杀伤、受创（伤亡乘数）、溃散倾向
DRILL = {
    "raw":     {"name": "新募", "power": 0.85, "kill": 0.85, "guard": 1.15, "rout": 0.15},
    "regular": {"name": "堪战", "power": 1.0, "kill": 1.0, "guard": 1.0, "rout": 0.0},
    "elite":   {"name": "精锐", "power": 1.15, "kill": 1.15, "guard": 0.85, "rout": -0.2},
}
DRILL_ALIASES = {"新募": "raw", "新兵": "raw", "green": "raw", "堪战": "regular", "老兵": "regular",
                 "veteran": "regular", "精锐": "elite", "精兵": "elite"}
UNIT_ALIASES = {
    "light_cavalry": "cavalry", "轻骑": "cavalry", "骑兵": "cavalry",
    "cataphract": "heavy_cavalry", "具装": "heavy_cavalry", "具装骑兵": "heavy_cavalry",
    "horse_archers": "horse_archer", "骑射": "horse_archer",
    "pike": "spear", "pikemen": "spear", "长枪": "spear", "枪步": "spear", "长枪手": "spear",
    "步卒": "infantry", "刀盾": "infantry", "shield": "infantry",
    "弓弩": "archer", "弓弩手": "archer", "弓手": "archer",
    "弩手": "crossbow", "弩": "crossbow",
    "民兵": "militia", "团结兵": "militia",
}
MOUNTED = ("shock", "ha")

# ---------------------------------------------------------------- 地形
OPEN = {"plain": 1.0, "steppe": 1.0, "river": 0.5, "forest": 0.4,
        "mountain": 0.3, "pass": 0.2, "city": 0.2}
# 冲击骑兵对近战步兵的优势系数：(对松散步兵, 对严整长枪阵)
CAV_VS_FOOT = {
    "steppe":   (1.60, 1.25),
    "plain":    (1.45, 1.15),
    "river":    (1.40, 1.15),
    "forest":   (1.20, 1.00),
    "mountain": (1.25, 1.05),
    "pass":     (1.20, 1.00),
    "city":     (1.00, 1.00),   # 城池另有守城加成和攻城骑兵 ×0.6
}
# 守方地利。山地、林地、隘口里骑兵用不上地利，只给步兵、弓弩
DEF_TERRAIN = {"mountain": 1.15, "pass": 1.25, "river": 1.1, "forest": 1.05}
TERRAIN_ALIASES = {"平原": "plain", "草原": "steppe", "沙碛": "steppe", "河": "river",
                   "渡口": "river", "林": "forest", "山": "mountain", "山地": "mountain",
                   "隘口": "pass", "关隘": "pass", "城": "city", "城池": "city"}


def canon_unit(code):
    c = UNIT_ALIASES.get(code, code)
    if c not in UNITS:
        sys.exit(f"错误：未知兵种 {code}。可用：{', '.join(UNITS)}，或别名 {', '.join(UNIT_ALIASES)}")
    return c


def trait_map(side, key, table, aliases, units):
    """把一方的 armor / drill 展开成 {兵种代码: 值}。可以写一个值（整方），或按兵种写字典。"""
    raw = side.get(key)
    out = {u: UNITS[u][key] for u in units}
    if raw is None:
        return out
    if isinstance(raw, str):
        raw = {u: raw for u in units}
    if not isinstance(raw, dict):
        sys.exit(f"错误：{side.get('name', '')} 的 {key} 要写成字符串或 {{兵种: 值}}")
    for u, v in raw.items():
        cu = canon_unit(u)
        val = aliases.get(v, v)
        if val not in table:
            sys.exit(f"错误：{side.get('name', '')} 的 {key} {v!r} 不认识。可用：{', '.join(table)}，"
                     f"或 {', '.join(aliases)}")
        if cu in out:
            out[cu] = val
    return out


def side_context(side, foe, terrain, is_defender):
    """一方的阵形状态：formed（步阵严整）、protected（弓弩有步阵掩护），以及各兵种的护甲、操练。"""
    tactic = side.get("tactic", "none")
    formed = bool(side.get("formed")) or tactic in ("formed", "prepared")
    if is_defender and terrain == "city":
        formed = True
    if tactic == "surprised" or foe.get("tactic") == "ambush":
        formed = False
    units = {canon_unit(u): 0 for u in side["units"]}
    for u, n in side["units"].items():
        units[canon_unit(u)] += n
    foot = sum(n for u, n in units.items() if UNITS[u]["cls"] == "foot")
    missile = sum(n for u, n in units.items() if UNITS[u]["cls"] == "missile")
    protected = (is_defender and terrain == "city") or (formed and missile > 0 and foot >= 0.5 * missile)
    armor = trait_map(side, "armor", ARMOR, ARMOR_ALIASES, units)
    drill = trait_map(side, "drill", DRILL, DRILL_ALIASES, units)
    return {"formed": formed, "protected": protected, "units": units, "armor": armor, "drill": drill}


def raw_edge(a, b, ca, cb, terrain):
    """a 对 b 的优势系数（>1 对 a 有利）。只写一个方向，另一方向取倒数。返回 None 表示没有专门规则。"""
    A, B = UNITS[a], UNITS[b]
    op = OPEN.get(terrain, 1.0)
    if A["cls"] == "shock" and B["cls"] == "foot":
        loose, formed = CAV_VS_FOOT.get(terrain, CAV_VS_FOOT["plain"])
        e = loose - (loose - formed) * B["anti_cav"] if cb["formed"] else loose
        if a == "heavy_cavalry":
            e *= 1.05 if cb["formed"] else 1.15
        return e
    if A["cls"] == "shock" and B["cls"] == "missile":
        if cb["protected"]:
            e = 1.0 if b == "archer" else 0.9
        else:
            e = CAV_VS_FOOT.get(terrain, CAV_VS_FOOT["plain"])[0]
        if a == "heavy_cavalry":
            e *= 1.15
        return e
    if A["cls"] == "ha" and B["cls"] == "foot":
        if op >= 1.0:
            return 1.25 if cb["formed"] else 1.15
        return 1.0 if op >= 0.5 else 0.8
    if A["cls"] == "ha" and B["cls"] == "missile":
        return 0.95 if b == "archer" else 0.8
    if a == "heavy_cavalry" and b == "cavalry":
        # 轻骑披了铁甲、马也披甲的，具装的优势就小了
        return {"heavy": 1.1, "barded": 1.0}.get(cb["armor"].get(b), 1.25)
    if a == "heavy_cavalry" and b == "horse_archer":
        return 1.0 if op < 1.0 else 0.9
    if A["cls"] == "missile" and B["cls"] == "foot":
        e = 1.2 if cb["formed"] else 0.85
        return e * (0.9 if terrain == "forest" else 1.0)
    if A["cls"] == "foot" and B["cls"] == "foot":
        if terrain == "city":
            return 1.0
        if ca["formed"] and not cb["formed"]:
            return 1.1
        if cb["formed"] and not ca["formed"]:
            return 1 / 1.1
        return 1.0
    return None


def edge(a, b, ca, cb, terrain):
    e = raw_edge(a, b, ca, cb, terrain)
    if e is not None:
        return e
    e = raw_edge(b, a, cb, ca, terrain)
    return 1 / e if e is not None else 1.0


def terrain_flat(u, terrain, is_defender):
    m = 1.0
    if is_defender and not (UNITS[u]["cls"] in MOUNTED and terrain in ("mountain", "forest", "pass")):
        m *= DEF_TERRAIN.get(terrain, 1.0)
    if terrain == "city":
        cls = UNITS[u]["cls"]
        if is_defender and cls in ("foot", "missile"):
            m *= 1.5
        if not is_defender and cls in MOUNTED:
            m *= 0.6
    return m


def power(side, ctx, foe_ctx, terrain, is_defender, fort, rng):
    enemy = foe_ctx["units"]
    total_enemy = sum(enemy.values()) or 1
    p = 0.0
    for u, n in ctx["units"].items():
        if n <= 0:
            continue
        mult = sum(edge(u, e, ctx, foe_ctx, terrain) ** 0.5 * en / total_enemy for e, en in enemy.items())
        q = DRILL[ctx["drill"][u]]["power"] / DRILL[UNITS[u]["drill"]]["power"]
        q *= ARMOR[ctx["armor"][u]]["power"] / ARMOR[UNITS[u]["armor"]]["power"]
        p += n / 1000 * UNITS[u]["base"] * mult * terrain_flat(u, terrain, is_defender) * q
    p *= side.get("morale", 70) / 80
    p *= 1 + (side.get("统率", 5) - 5) * 0.04
    tactic = side.get("tactic", "none")
    if tactic == "ambush":
        p *= 1.3
    elif tactic == "surprised":
        p *= 0.85
    if is_defender and terrain == "city":
        p *= 1 + fort / 200
    roll = rng.uniform(0.85, 1.15)
    return p * roll, roll


def share(units, cls_set):
    tot = sum(units.values()) or 1
    return sum(n for u, n in units.items() if UNITS[u]["cls"] in cls_set) / tot


# ---------------------------------------------------------------- 伤亡
REF_THROUGH = 0.8   # 皮甲挡近战后透进来的比例，作为“1.0”的基准


def through(u, armor):
    """u 的兵器打在这种甲上，透进去几成（已计破甲），除以 u 打皮甲时的值。"""
    kind = "missile" if UNITS[u]["cls"] in ("missile", "ha") else "melee"
    pen = UNITS[u]["pen"]

    def t(a):
        return 1 - (1 - ARMOR[a][kind]) * (1 - pen)
    return t(armor) / t("light")


def contact(u, v, cu, cv, terrain):
    """接阵情形：u 打 v 时，因冲击、阵形、闪避而来的杀伤倍数。cu、cv 是双方的阵形状态。"""
    A, B = UNITS[u]["cls"], UNITS[v]["cls"]
    o = 0.0 if terrain == "city" else OPEN.get(terrain, 1.0)   # 冲得起来的程度；城里谈不上冲阵
    if A == "shock" and B == "foot":
        return 1 - 0.3 * UNITS[v]["anti_cav"] * o if cv["formed"] else 1.0
    if A == "shock" and B == "missile":
        return 1 - 0.2 * o if cv["protected"] else 1.0
    if A == "foot" and B == "shock":
        # 严整的枪阵迎着冲来的马，杀伤加重；没列阵的步兵被一冲就散，几乎还不了手
        return 1 + 0.4 * UNITS[u]["anti_cav"] * o if cu["formed"] else 1 - 0.8 * o
    if A == "missile" and B == "shock":
        return 1.0 if cu["protected"] else 1 - 0.7 * o
    if A == "shock" and B == "shock":
        return 1 + 0.25 * o
    if A == "shock" and B == "ha":
        return 1 - 0.65 * o         # 骑射散开退走，冲不着
    if A == "foot" and B == "ha":
        return 1 - 0.7 * o          # 步兵追不上骑射
    return 1.0


def hit_on(v, foe_ctx, own_ctx, terrain, collapse_foe=False):
    """对方（foe）打在本方兵种 v 上的杀伤倍数：兵器对甲、接阵情形、对方操练、本方操练，按对方人数加权。"""
    tot = sum(foe_ctx["units"].values()) or 1
    h = 0.0
    for u, n in foe_ctx["units"].items():
        if n <= 0:
            continue
        x = through(u, own_ctx["armor"][v]) * contact(u, v, foe_ctx, own_ctx, terrain)
        x *= DRILL[foe_ctx["drill"][u]]["kill"]
        h += n / tot * x
    return h * DRILL[own_ctx["drill"][v]]["guard"]


def resolve(b, rng):
    terrain = TERRAIN_ALIASES.get(b.get("terrain", "plain"), b.get("terrain", "plain"))
    if terrain not in OPEN:
        sys.exit(f"错误：未知地形 {terrain}。可用：{', '.join(OPEN)}")
    fort = b.get("fortification", 0) if terrain == "city" else 0
    intensity = b.get("intensity", "assault")
    assault = intensity == "assault"
    A, D = dict(b["attacker"]), dict(b["defender"])
    for s in (A, D):   # 阵前单挑等带来的士气加减（rules/combat.md“输入”、rules/contest.md 第七节）
        if s.get("morale_bonus"):
            s["morale"] = max(0, min(100, s.get("morale", 70) + s["morale_bonus"]))
    ca = side_context(A, D, terrain, False)
    cd = side_context(D, A, terrain, True)

    pa, ra = power(A, ca, cd, terrain, False, 0, rng)
    pd, rd = power(D, cd, ca, terrain, True, fort, rng)
    share_a = pa / (pa + pd)

    winner = "attacker" if pa > pd else "defender"
    W, L = (A, D) if winner == "attacker" else (D, A)
    wc, lc = (ca, cd) if winner == "attacker" else (cd, ca)
    s_w = max(share_a, 1 - share_a)
    op = OPEN[terrain]
    events, notes = [], []

    # ---- 一触即溃：冲击骑兵在开阔地上冲没列阵的步卒、没掩护的弓弩
    exposed = sum(n for u, n in lc["units"].items()
                  if (UNITS[u]["cls"] == "foot" and not lc["formed"])
                  or (UNITS[u]["cls"] == "missile" and not lc["protected"])) / (sum(lc["units"].values()) or 1)
    w_shock = share(wc["units"], ("shock",))
    l_drill = sum(DRILL[lc["drill"][u]]["rout"] * n for u, n in lc["units"].items()) / (sum(lc["units"].values()) or 1)
    collapse = False
    if assault and op >= 0.5 and w_shock >= 0.25 and exposed >= 0.5 and s_w >= 0.55:
        w_heavy = sum(n for u, n in wc["units"].items() if UNITS[u]["cls"] == "shock"
                      and wc["armor"][u] in ("heavy", "barded")) / (sum(wc["units"].values()) or 1)
        p = min(1.0, (s_w - 0.5) * 8) * exposed * min(1.0, w_shock * 2) + 0.15 * w_heavy + l_drill
        collapse = rng.random() < p

    # ---- 交锋伤亡：烈度 × 对方战力占比 × 1.6 × 对方打在本兵种上的杀伤倍数
    base_rate = 0.30 if assault else 0.10
    ha_a, ha_d = share(ca["units"], ("ha",)), share(cd["units"], ("ha",))
    rate = {"attacker": {}, "defender": {}}
    for key, own, foe, foe_share, foe_ha in (("attacker", ca, cd, 1 - share_a, ha_d),
                                              ("defender", cd, ca, share_a, ha_a)):
        for v in own["units"]:
            r = base_rate * foe_share * 1.6 * hit_on(v, foe, own, terrain)
            r *= 1 - 0.4 * foe_ha                       # 骑射多的一方打的是消耗
            if terrain == "city" and key == "defender":
                r *= 0.8                                  # 城垛掩护
            rate[key][v] = r
    wkey, lkey = winner, ("defender" if winner == "attacker" else "attacker")
    if collapse:
        # 败方一冲就散，没怎么还手：胜方伤亡再打六折；败方阵前死得少，死在追击里
        for v in rate[wkey]:
            rate[wkey][v] *= 0.6
        for v in rate[lkey]:
            rate[lkey][v] *= 0.7
    # 败方骑兵多于胜方：败了也跑得掉（旧规则的下限 0.85）
    escape = 1 + 0.6 * (share(wc["units"], MOUNTED) - share(lc["units"], MOUNTED)) * op
    escape = max(0.85, min(1.0, escape))
    for v in rate[lkey]:
        rate[lkey][v] *= escape

    # ---- 士气、溃散
    morale_drop = rng.randint(15, 25) if assault else rng.randint(5, 10)
    loser_morale = L.get("morale", 70) - morale_drop
    routed = collapse
    if collapse:
        events.append(f"{L['name']}未及成列，被骑兵一冲即溃")
    elif assault and loser_morale < 30 and rng.random() < 0.6 + l_drill:
        routed = True
        events.append(f"{L['name']}士气崩溃，阵线溃散，追加损失")
    if routed:
        for v in rate[lkey]:   # 溃散时自相践踏、丢弃辎重
            rate[lkey][v] += 0.10 * DRILL[lc["drill"][v]]["guard"] * (0.5 if UNITS[v]["cls"] in MOUNTED else 1.0)

    # ---- 追击：按胜方能追的人马算杀伤人数，摊到败方各兵种（骑兵跑得掉）
    rem_l = {v: n * (1 - min(0.9, rate[lkey][v])) for v, n in lc["units"].items()}
    flee = {"foot": 1.0, "missile": 1.0, "shock": 0.3, "ha": 0.2}
    weight = {v: n * flee[UNITS[v]["cls"]] for v, n in rem_l.items()}
    wsum = sum(weight.values()) or 1
    chase = 0.0
    if assault or routed:
        for u, n in wc["units"].items():
            chase += n * UNITS[u]["pursue"] * DRILL[wc["drill"][u]]["kill"] * W.get("morale", 70) / 80
        chase *= op * (1.0 if routed else 0.25) * (1.0 if assault else 0.4)
    cap_frac = 0.4 if routed else 0.2
    pursued, captured_by_w = {}, {}
    for v, n in rem_l.items():
        k = min(chase * weight[v] / wsum, cap_frac * n * flee[UNITS[v]["cls"]])
        pursued[v] = k
        captured_by_w[v] = k * (0.4 if routed else 0.25)
    pre = sum(rate[lkey][v] * n for v, n in lc["units"].items())
    for v, n in lc["units"].items():
        if n:
            rate[lkey][v] += pursued[v] / n
    post = sum(rate[lkey][v] * n for v, n in lc["units"].items())
    pursuit = post / pre if pre > 0 else 1.0
    if chase > 0 and pursuit >= 1.15:
        notes.append("胜方骑兵追击，败方步卒在开阔地上难以脱身")
    elif escape <= 0.9:
        notes.append("败方以骑兵为主，胜方追不上，败方得以脱身")

    for side in (rate["attacker"], rate["defender"]):
        for v in side:
            side[v] = min(side[v], 0.9)

    # ---- 提示
    if collapse:
        notes.append("骑兵冲到时步卒还没列成阵，一触即溃，胜方几乎没有折损")
    if wc["formed"] and share(wc["units"], ("foot", "missile")) > 0.5 and share(lc["units"], ("shock",)) > 0.5:
        notes.append("骑兵冲阵不动，自损在先")
    for c, s, foe_c in ((ca, A, cd), (cd, D, ca)):
        if c["formed"] and share(c["units"], ("foot",)) > 0 and share(foe_c["units"], ("shock",)) > 0:
            notes.append(f"{s['name']}步阵严整，骑兵正面冲击受阻")
        if share(c["units"], ("missile",)) > 0 and not c["protected"] and share(foe_c["units"], ("shock",)) > 0 \
                and OPEN[terrain] >= 1.0:
            notes.append(f"{s['name']}的弓弩没有步阵掩护，被骑兵近身")
        if any(c["armor"][u] in ("heavy", "barded") for u in c["units"]) \
                and share(foe_c["units"], ("missile", "ha")) > 0.3:
            notes.append(f"{s['name']}甲坚，箭矢多被挡住")
    if A.get("tactic") == "ambush" or D.get("tactic") == "surprised":
        notes.append("守方仓促应战，未能列阵")

    def apply(side, ctx, rates, caps):
        losses, remaining, cap = {}, {}, {}
        for code, n in side["units"].items():
            cu = canon_unit(code)
            lost = round(n * rates[cu])
            losses[code] = lost
            remaining[code] = n - lost
            if caps is not None:
                cap[code] = min(lost, round(n * caps.get(cu, 0) / (ctx["units"][cu] or 1)))
        return losses, remaining, cap

    loss_a, rem_a, cap_a = apply(A, ca, rate["attacker"], captured_by_w if lkey == "attacker" else None)
    loss_d, rem_d, cap_d = apply(D, cd, rate["defender"], captured_by_w if lkey == "defender" else None)
    # captured：本方俘获的敌兵，按敌方兵种（和 tactical.py 的 captured 同义）
    captured = {"attacker": cap_d if lkey == "defender" else {}, "defender": cap_a if lkey == "attacker" else {}}

    for side, foe in ((A, D), (D, A)):
        if side.get("charge"):
            w = side.get("武勇", 5)
            if rng.random() < 0.02 * max(0, w - 5):
                events.append(f"{side.get('commander', side['name'])}亲自冲阵，阵斩{foe.get('commander', foe['name'])}麾下一员大将")
            if rng.random() < 0.08:
                events.append(f"{side.get('commander', side['name'])}冲阵时负伤")
    if sum(captured[wkey].values()) > 0:
        events.append(f"{W['name']}俘获败兵约 {sum(captured[wkey].values())} 人")

    captured_region = assault and winner == "attacker" and share_a >= 0.55
    morale_after = {
        "attacker": A.get("morale", 70) + (rng.randint(5, 10) if winner == "attacker" else -morale_drop),
        "defender": D.get("morale", 70) + (rng.randint(5, 10) if winner == "defender" else -morale_drop),
    }
    trait = {k: {u: f"{ARMOR[c['armor'][u]]['name']}·{DRILL[c['drill'][u]]['name']}" for u in c["units"]}
             for k, c in (("attacker", ca), ("defender", cd))}
    return {
        "winner": winner,
        "power": {"attacker": round(pa, 2), "defender": round(pd, 2),
                  "attacker_share": round(share_a, 3), "luck": {"attacker": round(ra, 2), "defender": round(rd, 2)}},
        "losses": {"attacker": loss_a, "defender": loss_d},
        "remaining": {"attacker": rem_a, "defender": rem_d},
        "captured": captured,
        "morale_after": {k: max(0, min(100, v)) for k, v in morale_after.items()},
        "region_captured": captured_region,
        "events": events,
        "notes": notes,
        "state": {"terrain": terrain, "attacker_formed": ca["formed"], "defender_formed": cd["formed"],
                  "pursuit": round(pursuit, 2), "routed": routed, "collapse": collapse, "traits": trait},
    }


def trials(b, n):
    rng = random.Random(b.get("seed", 1))
    wins = cap = 0
    la, ld, lw, ll = [], [], [], []
    ta = sum(b["attacker"]["units"].values()) or 1
    td = sum(b["defender"]["units"].values()) or 1
    for _ in range(n):
        r = resolve(b, rng)
        aw = r["winner"] == "attacker"
        wins += aw
        cap += r["region_captured"]
        xa = sum(r["losses"]["attacker"].values()) / ta
        xd = sum(r["losses"]["defender"].values()) / td
        la.append(xa)
        ld.append(xd)
        lw.append(xa if aw else xd)
        ll.append(xd if aw else xa)
    med = statistics.median
    return {"trials": n, "attacker_win_rate": round(wins / n, 3), "capture_rate": round(cap / n, 3),
            "attacker_loss_pct": round(100 * sum(la) / n, 1), "defender_loss_pct": round(100 * sum(ld) / n, 1),
            "attacker_loss_median": round(100 * med(la), 1), "defender_loss_median": round(100 * med(ld), 1),
            "winner_loss_median": round(100 * med(lw), 1), "loser_loss_median": round(100 * med(ll), 1)}


def main():
    args = sys.argv[1:]
    n_trials = 0
    if "--trials" in args:
        i = args.index("--trials")
        n_trials = int(args[i + 1])
        del args[i:i + 2]
    raw = open(args[0], encoding="utf-8").read() if args else sys.stdin.read()
    b = json.loads(raw)
    if n_trials:
        print(json.dumps(trials(b, n_trials), ensure_ascii=False, indent=2))
        return
    result = resolve(b, random.Random(b.get("seed")))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
