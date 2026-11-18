#!/usr/bin/env python3
"""亲临指挥的战斗（一刻一回合）。规则见 rules/tactics.md。纯标准库。

用法：
  python3 scripts/tactical.py new   --from rules/tactics_example.json --state 战场.json [--seed N]
  python3 scripts/tactical.py show  --state 战场.json [--view A|B] [--json]
  python3 scripts/tactical.py turn  --state 战场.json --orders 军令.json [--seed N] [--dry-run] [--json]
  python3 scripts/tactical.py report --state 战场.json
  python3 scripts/tactical.py morale --state 战场.json --side A --delta 10 [--leader 名=负伤] [--why 阵前单挑]
                                     # 阵前单挑等带来的士气加减（scripts/contest.py 给出），该方在场各部都加
初始战例里 sides.X.morale_bonus 也可以写：new 的时候加到该方各部的士气上（只加一次）。
每支部队可写 "armor"（none 无甲 / light 皮甲 / heavy 铁甲 / barded 人马俱甲）和 "drill"（raw 新募 / regular 堪战 /
elite 精锐），不写用兵种默认值。冲击、射击、近战的伤亡按护甲和操练修正（rules/tactics.md 第二节）。

军令 JSON（双方同时下令；没写到的部队按“常令”行事，默认坚守）：
{
  "A": [
    {"unit": "左厢轻骑", "order": "charge", "target": "枪阵甲"},
    {"unit": "右厢轻骑", "order": "flank", "sector": "右"},
    {"unit": "骑射队",   "order": "shoot", "target": "枪阵甲", "standing": "charge_if_loose"}
  ],
  "B": [{"unit": "全军", "order": "hold"}]
}
命令：advance 前进、charge 冲击、attack 接战、shoot 射击、hold 坚守、flank 绕侧（"to": "rear" 为绕后）、
      withdraw 撤回、rally 回整、commit 投入（预备队，需 sector、可选 line）、move 移动（sector、line）、
      pursue 追击、retreat 撤出战场。
常令（standing）：hold 坚守、shoot 见敌即射、charge_if_loose 见敌阵松动即冲、pursue 见溃即追。
"""
import argparse
import json
import random
import sys

# ------------------------------------------------------------------ 兵种
# melee 近战、charge 冲击、brace 受冲时的抗冲力（严整/松动/混乱）、missile 射击、
# vuln 中箭程度（未计护甲：身形、盾牌、散开与否）、speed 每刻能走几步、pursuit 追击、army 写回存档时的兵种代码
# armor 默认护甲、pen 破甲（近战；弓弩、骑射的破甲写在 mpen）
TYPES = {
    "spear":        {"name": "枪步", "mounted": False, "melee": 1.0, "charge": 0.6, "brace": (2.2, 1.1, 0.5),
                     "missile": 0, "vuln": 1.0, "speed": 1, "pursuit": 0.4, "army": "infantry",
                     "armor": "light", "pen": 0.2},
    "shield":       {"name": "刀盾", "mounted": False, "melee": 1.25, "charge": 0.8, "brace": (1.5, 0.9, 0.45),
                     "missile": 0, "vuln": 0.6, "speed": 1, "pursuit": 0.5, "army": "infantry",
                     "armor": "light", "pen": 0.15},
    "infantry":     {"name": "步卒", "mounted": False, "melee": 1.1, "charge": 0.7, "brace": (1.8, 1.0, 0.5),
                     "missile": 0, "vuln": 0.8, "speed": 1, "pursuit": 0.45, "army": "infantry",
                     "armor": "light", "pen": 0.15},
    "archer":       {"name": "弓手", "mounted": False, "melee": 0.5, "charge": 0.3, "brace": (0.6, 0.4, 0.25),
                     "missile": 1.0, "range": 1, "vuln": 0.75, "speed": 1, "pursuit": 0.4, "army": "archer",
                     "armor": "none", "pen": 0.0, "mpen": 0.0},
    "crossbow":     {"name": "弩手", "mounted": False, "melee": 0.5, "charge": 0.3, "brace": (0.6, 0.4, 0.25),
                     "missile": 1.15, "range": 2, "vuln": 0.75, "speed": 1, "pursuit": 0.4, "army": "archer",
                     "armor": "none", "pen": 0.0, "mpen": 0.3},
    "militia":      {"name": "民兵", "mounted": False, "melee": 0.6, "charge": 0.4, "brace": (1.2, 0.6, 0.3),
                     "missile": 0, "vuln": 0.825, "speed": 1, "pursuit": 0.4, "army": "militia", "fragile": 10,
                     "armor": "none", "pen": 0.0, "drill": "raw"},
    "light_cav":    {"name": "轻骑", "mounted": True, "melee": 0.9, "charge": 1.4, "brace": (0.9, 0.7, 0.4),
                     "missile": 0, "vuln": 0.8, "speed": 2, "pursuit": 1.6, "army": "cavalry", "charge_gap": 2,
                     "armor": "light", "pen": 0.15},
    "heavy_cav":    {"name": "具装", "mounted": True, "melee": 1.4, "charge": 2.0, "brace": (1.4, 1.0, 0.6),
                     "missile": 0, "vuln": 0.9, "speed": 1, "pursuit": 1.0, "army": "cavalry", "charge_gap": 1,
                     "charge_fatigue": 40, "armor": "barded", "pen": 0.5},
    "horse_archer": {"name": "骑射", "mounted": True, "melee": 0.6, "charge": 0.9, "brace": (0.6, 0.5, 0.3),
                     "missile": 0.8, "range": 1, "vuln": 0.4, "speed": 2, "pursuit": 1.3, "army": "cavalry",
                     "charge_gap": 1, "evade": True, "armor": "light", "pen": 0.0, "mpen": 0.0},
}
# 护甲：近战、箭矢透进来几成（未计破甲），和 resolve_battle.py 同一张表
ARMOR = {
    "none":   {"name": "无甲", "melee": 1.0, "missile": 1.0},
    "light":  {"name": "皮甲", "melee": 0.8, "missile": 0.75},
    "heavy":  {"name": "铁甲", "melee": 0.55, "missile": 0.4},
    "barded": {"name": "人马俱甲", "melee": 0.4, "missile": 0.25},
}
ARMOR_ALIASES = {"无甲": "none", "皮甲": "light", "leather": "light", "铁甲": "heavy", "iron": "heavy",
                 "明光甲": "heavy", "人马俱甲": "barded", "具装": "barded", "cataphract": "barded"}
# 操练：有效战力（相对兵种默认）、杀伤、受创、溃散门槛的加减
DRILL = {
    "raw":     {"name": "新募", "eff": 0.9, "kill": 0.85, "guard": 1.15, "thr": 5},
    "regular": {"name": "堪战", "eff": 1.0, "kill": 1.0, "guard": 1.0, "thr": 0},
    "elite":   {"name": "精锐", "eff": 1.1, "kill": 1.15, "guard": 0.85, "thr": -5},
}
DRILL_ALIASES = {"新募": "raw", "新兵": "raw", "green": "raw", "堪战": "regular", "老兵": "regular",
                 "veteran": "regular", "精锐": "elite", "精兵": "elite"}
TYPE_ALIASES = {
    "cavalry": "light_cav", "light_cavalry": "light_cav", "轻骑": "light_cav", "骑兵": "light_cav",
    "heavy_cavalry": "heavy_cav", "cataphract": "heavy_cav", "具装": "heavy_cav", "具装骑兵": "heavy_cav",
    "骑射": "horse_archer", "horse_archers": "horse_archer",
    "枪步": "spear", "长枪": "spear", "长枪手": "spear", "pike": "spear",
    "刀盾": "shield", "步卒": "infantry",
    "弓手": "archer", "弓弩": "archer", "弓弩手": "archer",
    "弩手": "crossbow", "弩": "crossbow", "团结兵": "militia", "民兵": "militia",
}
FORMS = ["严整", "松动", "混乱", "溃散"]
FORM_MULT = {"严整": 1.0, "松动": 0.8, "混乱": 0.55, "溃散": 0.2}
DIR_MULT = {"正面": 1.0, "侧面": 1.6, "背后": 2.2}
SIDE_BRACE = {"侧面": 0.6, "背后": 0.4}
SECTORS = ["左", "中", "右"]
SECTOR_NAME = {"左": "左翼", "中": "中军", "右": "右翼"}
GAP_NAME = {0: "接战", 1: "一箭之地", 2: "相距一里", 3: "遥遥相望"}
LINE_NAME = {"front": "前", "back": "后", "reserve": "预备", "flank": "侧翼", "rear": "背后", "transit": "运动中",
             "off": "已离场", "gone": "覆灭"}
ORDER_ALIASES = {
    "前进": "advance", "冲击": "charge", "冲锋": "charge", "接战": "attack", "搏战": "attack", "射击": "shoot",
    "坚守": "hold", "绕侧": "flank", "绕后": "flank", "撤回": "withdraw", "回整": "rally", "整队": "rally",
    "投入": "commit", "移动": "move", "追击": "pursue", "撤出": "retreat", "撤出战场": "retreat",
    "转向": "face", "变阵": "face",
}
FACE_ALIASES = {"flank": "侧面", "rear": "背后", "front": "正面", "侧": "侧面", "后": "背后", "前": "正面"}
STANDING_ALIASES = {"坚守": "hold", "见敌即射": "shoot", "见松即冲": "charge_if_loose",
                    "见敌阵松动即冲": "charge_if_loose", "见溃即追": "pursue"}
TICK_NAMES = ["卯初", "卯正", "辰初", "辰正", "巳初", "巳正", "午初", "午正", "未初", "未正", "申初", "申正",
              "酉初", "酉正", "戌初"]


def die(msg):
    sys.exit("错误：" + msg)


# ------------------------------------------------------------------ 基础取值
def T(u):
    return TYPES[u["type"]]


def other(side):
    return "B" if side == "A" else "A"


def active(u):
    return u["line"] not in ("off", "gone") and u["formation"] != "溃散" and u["men"] > 0


def on_field(u):
    return u["line"] not in ("off", "gone") and u["men"] > 0


def leader_of(state, u):
    name = u.get("leader")
    if not name:
        return None
    ld = state["sides"][u["side"]].get("leaders", {}).get(name)
    if ld is None or ld.get("status") in ("阵亡", "被俘"):
        return None
    return dict(ld, name=name)


def lead_mult(state, u):
    ld = leader_of(state, u)
    if not ld or ld.get("status") == "负伤":
        return 1.0
    return 1 + (ld.get("统率", 5) - 5) * 0.04


def drill_of(u):
    return DRILL[u.get("drill") or T(u).get("drill", "regular")]


def drill_eff(u):
    """操练对有效战力的修正，相对兵种默认（民兵默认新募，其余默认堪战）。"""
    return drill_of(u)["eff"] / DRILL[T(u).get("drill", "regular")]["eff"]


def through(att, tgt, kind="melee"):
    """att 的兵器打在 tgt 的甲上透进去几成（已计破甲），除以打皮甲时的值。"""
    pen = T(att).get("mpen" if kind == "missile" else "pen", 0.0)

    def t(a):
        return 1 - (1 - ARMOR[a][kind]) * (1 - pen)
    return t(tgt.get("armor") or T(tgt)["armor"]) / t("light")


def hurt(att, tgt, kind="melee"):
    """伤亡的护甲、操练修正：att 打 tgt。"""
    return through(att, tgt, kind) * drill_of(att)["kill"] * drill_of(tgt)["guard"]


def eff(state, u):
    """有效战力（千人当量）：人数 × 阵形 × 疲劳 × 士气 × 统帅 × 操练。"""
    fat = max(0.5, 1 - u["fatigue"] / 200)
    mor = 0.5 + u["morale"] / 160
    return u["men"] / 1000 * FORM_MULT[u["formation"]] * fat * mor * lead_mult(state, u) * drill_eff(u)


def feature(state, sector, kind):
    for f in state["sectors"][sector].get("features", []):
        if f.get("type") == kind:
            return f
    return None


def degrade(u, steps=1):
    i = min(FORMS.index(u["formation"]) + steps, 2)
    if FORMS.index(u["formation"]) < 3:
        u["formation"] = FORMS[i]


def improve(u):
    i = FORMS.index(u["formation"])
    if 0 < i < 3:
        u["formation"] = FORMS[i - 1]


def units_at(state, side, sector, line, only_active=True):
    return [u for u in state["units"] if u["side"] == side and u["sector"] == sector and u["line"] == line
            and (active(u) if only_active else on_field(u))]


def find(state, uid):
    for u in state["units"]:
        if u["id"] == uid:
            return u
    return None


def label(u):
    return f"{u['id']}（{T(u)['name']}）"


# ------------------------------------------------------------------ 建立战场
def normalize_state(st):
    st.setdefault("tick", 0)
    st.setdefault("sunset", 10)
    st.setdefault("weather", {})
    st.setdefault("log", [])
    st.setdefault("finished", False)
    st.setdefault("seed", 1)
    for s in SECTORS:
        st["sectors"].setdefault(s, {})
        st["sectors"][s].setdefault("gap", 2)
        st["sectors"][s].setdefault("features", [])
    for k in ("A", "B"):
        st["sides"][k].setdefault("leaders", {})
        st["sides"][k].setdefault("shaken", False)
    ids = set()
    for u in st["units"]:
        t = TYPE_ALIASES.get(u["type"], u["type"])
        if t not in TYPES:
            die(f"{u['id']} 的兵种 {u['type']} 不认识。可用：{', '.join(TYPES)}")
        if u["id"] in ids:
            die(f"部队名重复：{u['id']}")
        ids.add(u["id"])
        u["type"] = t
        u.setdefault("army_code", TYPES[t]["army"])
        for key, table, aliases in (("armor", ARMOR, ARMOR_ALIASES), ("drill", DRILL, DRILL_ALIASES)):
            v = u.get(key) or TYPES[t].get(key, "regular")
            v = aliases.get(v, v)
            if v not in table:
                die(f"{u['id']} 的 {key} {u.get(key)!r} 不认识。可用：{', '.join(table)}，或 {', '.join(aliases)}")
            u[key] = v
        u.setdefault("morale", 70)
        u.setdefault("fatigue", 0)
        u.setdefault("formation", "严整")
        u.setdefault("sector", "中")
        u.setdefault("line", "front")
        u.setdefault("hidden", False)
        u.setdefault("standing", "hold")
        u.setdefault("men0", u["men"])
        u.setdefault("killed", 0)
        u.setdefault("captured", 0)
        u.setdefault("dispersed", 0)
        u.setdefault("took", {"captured": 0})
        if u["line"] == "reserve":
            u["sector"] = "中"
    for k in ("A", "B"):   # 开战前的士气加减（阵前单挑），只加一次
        mb = st["sides"][k].get("morale_bonus")
        if mb and not st["sides"][k].get("morale_bonus_applied"):
            for u in st["units"]:
                if u["side"] == k:
                    u["morale"] = max(0, min(100, u["morale"] + mb))
            st["sides"][k]["morale_bonus_applied"] = True
    return st


def shift_morale(st, side, delta, leaders, why):
    """阵前单挑等：一方在场各部士气加减，可顺带改将领状态。返回纪事。"""
    out = []
    for u in st["units"]:
        if u["side"] == side and on_field(u):
            u["morale"] = max(0, min(100, u["morale"] + delta))
    out.append(f"{st['sides'][side]['name']}{why}，各部士气 {delta:+d}")
    for kv in leaders:
        if "=" not in kv:
            die(f"--leader 写成 名=负伤|阵亡|被俘|无恙：{kv!r}")
        name, status = kv.split("=", 1)
        if status not in ("负伤", "阵亡", "被俘", "无恙"):
            die("将领状态只有 负伤、阵亡、被俘、无恙")
        lds = st["sides"][side].setdefault("leaders", {})
        if name not in lds:
            die(f"{side} 方没有将领 {name}（有：{'、'.join(lds) or '无'}）")
        lds[name]["status"] = status
        out.append(f"{name}{status}")
    st["log"].append({"tick": st["tick"], "events": out})
    return out


# ------------------------------------------------------------------ 可达与方向
def direction(state, att, tgt):
    """att 能否打到 tgt，返回受击方向（正面/侧面/背后）或 None。考虑 tgt 的朝向。"""
    d = raw_direction(state, att, tgt)
    if d is None:
        return None
    facing = tgt.get("facing", "正面")
    if facing == "正面":
        return d
    if d == facing:
        return "正面"
    return "侧面" if d == "正面" else d


def raw_direction(state, att, tgt):
    if not on_field(tgt) or tgt["side"] == att["side"]:
        return None
    a_line, t_line = att["line"], tgt["line"]
    same = att["sector"] == tgt["sector"]
    if a_line == "front" and same:
        if t_line == "front":
            return "正面"
        if t_line == "back" and not units_at(state, tgt["side"], tgt["sector"], "front"):
            return "正面"
        if t_line in ("flank", "rear"):  # 打进本方侧后的敌军
            return "正面"
    if a_line in ("back", "reserve") and t_line in ("flank", "rear"):
        if same or a_line == "reserve":
            return "正面"
    if a_line == "back" and same and t_line == "front" and not units_at(state, att["side"], att["sector"], "front"):
        return "正面"
    if a_line == "flank" and same and t_line in ("front", "back"):
        return "侧面"
    if a_line == "rear" and same and t_line in ("front", "back"):
        return "背后"
    if a_line == "rear" and att["sector"] == "中" and t_line == "reserve":
        return "背后"
    return None


def frontal(att, tgt):
    return att["line"] in ("front", "back") and tgt["line"] in ("front", "back")


def pick_target(state, u, cand_filter, prefer=None):
    """在可达的敌军里挑一个：先看命令指定的，再挑人数最多的。"""
    if prefer:
        t = find(state, prefer)
        if t and cand_filter(t) and direction(state, u, t):
            return t
    cands = [t for t in state["units"] if t["side"] != u["side"] and cand_filter(t) and direction(state, u, t)
             and not (t["hidden"] and t["line"] in ("flank", "rear", "back"))]
    if not cands:
        return None
    cands.sort(key=lambda t: (t["formation"] == "溃散", t["line"] != "front", -t["men"]))
    return cands[0]


# ------------------------------------------------------------------ 伤亡、士气
class Tick:
    def __init__(self, state, rng):
        self.state = state
        self.rng = rng
        self.events = []      # 写战报用的条目
        self.hit = {}         # uid -> {"cas": 人数, "dirs": set}
        self.routed_now = []

    def ev(self, s):
        self.events.append(s)

    def damage(self, u, cas, direction_=None, morale=0.0, killer=None, captured=0):
        cas = int(min(u["men"], max(0, round(cas))))
        captured = min(captured, cas)
        u["men"] -= cas
        u["killed"] += cas - captured
        u["captured"] += captured
        if killer is not None and captured:
            killer["took"]["captured"] = killer["took"].get("captured", 0) + captured
        h = self.hit.setdefault(u["id"], {"cas": 0, "dirs": set(), "men_before": u["men"] + cas})
        h["cas"] += cas
        if direction_:
            h["dirs"].add(direction_)
        u["morale"] = max(0, round(u["morale"] - morale))
        if u["men"] <= 0:
            u["line"] = "gone"
        return cas


def reveal(t, u):
    if u.get("hidden"):
        u["hidden"] = False
        t.ev(f"伏兵杀出：{label(u)}从{SECTOR_NAME[u['sector']]}{LINE_NAME.get(u['line'], '')}现身")
        return True
    return False


# ------------------------------------------------------------------ 各阶段
def phase_move(t, orders):
    st = t.state
    advancing = {(s, side): False for s in SECTORS for side in "AB"}
    for u in st["units"]:
        if not on_field(u):
            continue
        o = orders.get(u["id"], {})
        kind = o.get("order")
        if u["formation"] == "溃散":
            continue
        engaged = u["line"] == "front" and st["sectors"][u["sector"]]["gap"] == 0 \
            and units_at(st, other(u["side"]), u["sector"], "front")
        if kind == "face":
            d = o.get("dir", "侧面")
            d = FACE_ALIASES.get(d, d)
            if d not in ("正面", "侧面", "背后"):
                t.ev(f"[军令无效] {u['id']}：转向只能是 正面/侧面/背后")
                continue
            if u.get("facing", "正面") != d:
                u["facing"] = d
                if engaged or T(u)["mounted"] is False and u["formation"] == "严整" and u["men"] > 1000:
                    degrade(u)
                t.ev(f"{label(u)}转向{d}列阵，阵形{u['formation']}")
        elif kind == "advance":
            reveal(t, u)
            if u["line"] == "back":
                u["line"] = "front"
                u["fatigue"] += 5
            elif u["line"] == "front":
                advancing[(u["sector"], u["side"])] = True
                u["fatigue"] += 5
        elif kind == "withdraw":
            if u["line"] == "front":
                if engaged and not T(u)["mounted"]:
                    t.damage(u, u["men"] * 0.02, morale=5)
                    degrade(u)
                    t.ev(f"{label(u)}且战且退，阵脚松动")
                u["line"] = "back"
            elif u["line"] in ("flank", "rear"):
                u["line"] = "back"
                t.ev(f"{label(u)}从敌军侧后撤回本阵")
            elif u["line"] == "back" and u["sector"] == "中":
                u["line"] = "reserve"
        elif kind == "retreat":
            if u["line"] == "front":
                if engaged and not T(u)["mounted"]:
                    t.damage(u, u["men"] * 0.02, morale=5)
                    degrade(u)
                u["line"] = "back"
                t.ev(f"{label(u)}{'脱离接战，' if engaged else ''}向后撤，准备离开战场")
            else:
                u["line"] = "off"
                t.ev(f"{label(u)}撤出战场")
        elif kind in ("commit", "move"):
            reveal(t, u)
            dest = o.get("sector", u["sector"])
            line = o.get("line", "back" if kind == "commit" else u["line"])
            if dest not in SECTORS or line not in ("front", "back", "reserve"):
                t.ev(f"[军令无效] {u['id']}：去向 {dest}/{line} 不对")
                continue
            if engaged:
                t.ev(f"[军令无效] {u['id']} 正在接战，须先撤回才能调动")
                continue
            far = abs(SECTORS.index(dest) - SECTORS.index(u["sector"])) > 1 and u["line"] != "reserve"
            if far and T(u)["speed"] < 2:
                u["sector"] = "中"
                u["line"] = "back"
                t.ev(f"{label(u)}向{SECTOR_NAME[dest]}转移，本刻先到中军后方")
            else:
                u["sector"] = "中" if line == "reserve" else dest
                u["line"] = line
                t.ev(f"{label(u)}{'投入' if kind == 'commit' else '调往'}{SECTOR_NAME[dest]}{LINE_NAME[line]}线")
            u["fatigue"] += 5
        elif kind == "flank":
            to = o.get("to", "flank")
            dest = o.get("sector", u["sector"])
            if engaged:
                t.ev(f"[军令无效] {u['id']} 正在接战，不能绕侧")
                continue
            if to == "rear":
                if u["line"] != "flank" and not (u["line"] == "rear"):
                    t.ev(f"[军令无效] {u['id']} 须先到敌军侧翼，才能绕到背后")
                    continue
                u["line"] = "rear"
                u["fatigue"] += 10
                t.ev(f"{label(u)}绕到{SECTOR_NAME[u['sector']]}敌阵背后")
                continue
            foe = other(u["side"])
            if dest == "中":
                open_wing = any(not units_at(st, foe, s, "front") for s in ("左", "右"))
                if not open_wing:
                    t.ev(f"[军令无效] {u['id']}：两翼都有敌军，绕不到中军侧面")
                    continue
            if T(u)["mounted"] and T(u)["speed"] >= 2:
                u["sector"], u["line"] = dest, "flank"
                u["fatigue"] += 10
                t.ev(f"{label(u)}兜出阵外，绕到{SECTOR_NAME[dest]}敌阵侧面")
            elif T(u)["mounted"] or u["sector"] == dest:
                u["sector"], u["line"] = dest, "transit"
                u["dest"] = "flank"
                u["fatigue"] += 10
                t.ev(f"{label(u)}开始向{SECTOR_NAME[dest]}敌阵侧面迂回（下一刻到位）")
            else:
                t.ev(f"[军令无效] {u['id']} 是步兵，只能在本翼迂回")
    # 上一刻在路上的部队到位
    for u in st["units"]:
        if u["line"] == "transit" and orders.get(u["id"], {}).get("order") != "flank":
            u["line"] = u.pop("dest", "flank")
            t.ev(f"{label(u)}迂回到位，现在{SECTOR_NAME[u['sector']]}敌阵{LINE_NAME[u['line']]}")
    for s in SECTORS:
        n = sum(advancing[(s, side)] for side in "AB")
        if n:
            sec = st["sectors"][s]
            before = sec["gap"]
            sec["gap"] = max(0, sec["gap"] - n)
            if before != sec["gap"]:
                if sec["gap"] == 0 and feature(st, s, "river"):
                    for side in "AB":
                        if advancing[(s, side)]:
                            for u in units_at(st, side, s, "front"):
                                degrade(u)
                    t.ev(f"{SECTOR_NAME[s]}两军在河中相接，涉水一方阵形散乱")
                t.ev(f"{SECTOR_NAME[s]}两军逼近：{GAP_NAME[before]} → {GAP_NAME[sec['gap']]}")


def shoot_mult(st, shooter, tgt):
    m = 1.0
    s = tgt["sector"]
    if feature(st, s, "forest"):
        m *= 0.6
    hill = feature(st, s, "hill")
    if hill and hill.get("holder") == shooter["side"]:
        m *= 1.15
    camp = feature(st, s, "camp")
    if camp and camp.get("holder") == tgt["side"] and tgt["line"] == "front":
        m *= 0.6
    if st["weather"].get("fog"):
        m *= 0.6
    if shooter["type"] == "crossbow" and tgt["type"] == "horse_archer":
        m *= 1.5
    if shooter["type"] == "horse_archer" and tgt["type"] == "crossbow":
        m *= 0.6
    return m


def phase_shoot(t, orders):
    st = t.state
    shots = []
    for u in st["units"]:
        if not active(u) or T(u)["missile"] <= 0:
            continue
        o = orders.get(u["id"], {})
        if o.get("order") != "shoot":
            continue
        if u["formation"] == "混乱":
            factor = 0.5
        else:
            factor = 1.0
        rng_ok = T(u).get("range", 1)
        if u["line"] == "back":
            front = units_at(st, u["side"], u["sector"], "front")
            if not front:
                u_line_eff = "front"
            else:
                u_line_eff = "back"
                factor *= 0.7
        else:
            u_line_eff = u["line"]
        gap = st["sectors"][u["sector"]]["gap"]

        def ok(tg):
            if not on_field(tg) or tg["side"] == u["side"] or tg.get("hidden"):
                return False
            if st["weather"].get("fog") and not visible(st, u["side"], tg):
                return False
            if u_line_eff in ("flank", "rear"):
                return tg["sector"] == u["sector"] and tg["line"] in ("front", "back")
            if tg["sector"] != u["sector"]:
                return False
            if tg["line"] in ("flank", "rear"):
                return True
            if tg["line"] == "front":
                return gap <= rng_ok
            if tg["line"] == "back":
                return gap <= rng_ok - 1 or (gap <= rng_ok and not units_at(st, tg["side"], tg["sector"], "front"))
            return False
        cands = [x for x in st["units"] if ok(x)]
        if not cands:
            t.ev(f"{label(u)}奉命射击，但射程内没有敌军")
            continue
        tgt = find(st, o.get("target")) if o.get("target") else None
        if tgt not in cands:
            cands.sort(key=lambda x: (x["line"] != "front", -x["men"]))
            tgt = cands[0]
        if gap == 2 and u_line_eff in ("front", "back"):
            factor *= 0.6   # 弩在远处射
        engaged = u["line"] == "front" and gap == 0 and units_at(st, other(u["side"]), u["sector"], "front")
        if engaged:
            factor *= 0.4
        reveal(t, u)
        shots.append((u, tgt, eff(st, u) * T(u)["missile"] * factor * shoot_mult(st, u, tgt), engaged))
    for u, tgt, power, engaged in shots:
        dens = {"严整": 1.2, "松动": 1.0, "混乱": 0.9, "溃散": 0.8}[tgt["formation"]]
        cas = 40 * power * T(tgt)["vuln"] * hurt(u, tgt, "missile") * dens * t.rng.uniform(0.8, 1.2)
        pct = cas / max(1, tgt["men"])
        mor = pct * 80 + 1
        cas = t.damage(tgt, cas, "正面", morale=mor)
        u["fatigue"] += 5
        txt = f"{label(u)}射{label(tgt)}，杀伤 {cas}"
        if engaged:
            txt += "（已被近身，射不开）"
        if tgt["line"] != "gone" and tgt["formation"] in ("严整", "松动"):
            p = (0.1 + pct * 6) if tgt["formation"] == "严整" else pct * 4
            if T(tgt)["mounted"]:
                p *= 0.3
            if t.rng.random() < min(0.6, p):
                degrade(tgt)
                txt += f"，{tgt['id']}阵形转为{tgt['formation']}"
        t.ev(txt)


def charge_result(t, att, tgt, dirn, ratio):
    st = t.state
    # 伤亡按护甲、操练修正：冲方打在目标甲上透进去多少，目标的枪刀打在冲方甲上透进去多少
    tm, am = tgt["men"] * hurt(att, tgt), att["men"] * hurt(tgt, att)
    T_att = T(att)
    if ratio >= 1.5:
        cas_t = tm * min(0.25, 0.06 * ratio)
        cas_a = am * 0.02
        t.damage(tgt, cas_t, dirn, morale=25, killer=att)
        t.damage(att, cas_a)
        if ratio >= 2.5 or tgt["formation"] == "混乱":
            tgt["formation"] = "溃散"
            t.routed_now.append(tgt)
            res = "冲垮，当即溃散"
        else:
            tgt["formation"] = "混乱"
            res = "冲垮，阵形大乱"
        att["morale"] = min(100, att["morale"] + 5)
        degrade(att)
    elif ratio >= 1.0:
        t.damage(tgt, tm * 0.05, dirn, morale=12, killer=att)
        t.damage(att, am * 0.03)
        degrade(tgt)
        degrade(att)
        res = f"冲动敌阵，{tgt['id']}阵形转为{tgt['formation']}"
    elif ratio >= 0.75:
        am = att["men"] * hurt(tgt, att) ** 0.5   # 撞在枪林上，马被扎倒，甲只挡得住一半
        t.damage(tgt, tm * 0.02, dirn, morale=4, killer=att)
        t.damage(att, am * 0.04, morale=5)
        degrade(att)
        res = "相持不下，冲势已尽"
    else:
        am = att["men"] * hurt(tgt, att) ** 0.5
        t.damage(tgt, tm * 0.01, dirn, morale=0, killer=att)
        t.damage(att, am * 0.07, morale=12)
        att["formation"] = "混乱"
        res = "冲不动，撞在枪林上，自损不轻" if tgt["type"] in ("spear", "infantry", "shield") else "冲不动，被挡了回来"
    return res


def charge_power(st, att, tgt, dirn):
    p = eff(st, att) * T(att)["charge"] * DIR_MULT[dirn]
    s = tgt["sector"]
    if feature(st, s, "forest"):
        p *= 0.5
    if feature(st, s, "river") and dirn == "正面":
        p *= 0.5
    hill = feature(st, s, "hill")
    if hill and hill.get("holder") == tgt["side"] and dirn == "正面":
        p *= 0.7
    camp = feature(st, s, "camp")
    if camp and camp.get("holder") == tgt["side"] and dirn == "正面" and tgt["line"] == "front":
        p *= 0.35
    return p


def brace_power(st, tgt, dirn, att_men=None):
    fi = min(FORMS.index(tgt["formation"]), 2)
    men = tgt["men"]
    if dirn == "正面":
        b = T(tgt)["brace"][fi]
    else:
        b = min(T(tgt)["brace"][fi], SIDE_BRACE[dirn])
        if att_men:
            men = min(men, att_men)   # 侧后受冲，只有靠近的那一截能转身抵挡
    if tgt["formation"] == "溃散":
        b = 0.1
    fat = max(0.5, 1 - tgt["fatigue"] / 200)
    mor = 0.5 + tgt["morale"] / 160
    return men / 1000 * b * fat * mor * lead_mult(st, tgt) * drill_eff(tgt)


def leader_charge_events(t, att, tgt, broke):
    st = t.state
    ld = leader_of(st, att)
    if not ld:
        return
    w = ld.get("武勇", 5)
    if broke:
        tl = leader_of(st, tgt)
        if tl and t.rng.random() < 0.03 * max(0, w - 5):
            st["sides"][tgt["side"]]["leaders"][tl["name"]]["status"] = "阵亡"
            t.ev(f"{ld['name']}亲自冲阵，阵斩{tl['name']}")
            tgt["morale"] = max(0, tgt["morale"] - 15)
    if t.rng.random() < 0.05:
        st["sides"][att["side"]]["leaders"][ld["name"]]["status"] = "负伤"
        t.ev(f"{ld['name']}冲阵时负伤")


def phase_charge(t, orders):
    st = t.state
    plans = []
    for u in st["units"]:
        if not active(u):
            continue
        o = orders.get(u["id"], {})
        if o.get("order") != "charge":
            continue
        if u["formation"] == "混乱":
            t.ev(f"[军令无效] {u['id']} 阵形混乱，冲不起来，须先回整")
            continue
        if u["fatigue"] >= 70:
            t.ev(f"[军令无效] {u['id']} 人马疲乏（疲劳 {u['fatigue']}），冲不动了")
            continue
        gap_max = T(u).get("charge_gap", 1)
        gap = st["sectors"][u["sector"]]["gap"]
        tgt = pick_target(st, u, on_field, o.get("target"))
        if tgt is None:
            t.ev(f"{label(u)}要冲击，但够得着的地方没有敌军")
            continue
        dirn = direction(st, u, tgt)
        if frontal(u, tgt) and gap > gap_max:
            t.ev(f"{label(u)}要冲击，但离敌阵还远（{GAP_NAME[gap]}），本刻只能逼近")
            st["sectors"][u["sector"]]["gap"] = max(0, gap - 1)
            continue
        plans.append((u, tgt, dirn))
    # 同时结算：先按本阶段开始时的状态算出比值
    calc = []
    for u, tgt, dirn in plans:
        surprise = reveal(t, u)
        ratio = charge_power(st, u, tgt, dirn) / max(0.05, brace_power(st, tgt, dirn, u["men"]))
        if dirn == "正面":
            # 正面宽度有限：人数之比只按平方根算
            ratio *= (u["men"] / max(1, tgt["men"])) ** -0.5
        ratio *= t.rng.uniform(0.85, 1.15)
        if surprise:
            ratio *= 1.3
        calc.append((u, tgt, dirn, ratio, surprise))
    for u, tgt, dirn, ratio, surprise in calc:
        if not on_field(tgt):
            continue
        if T(tgt).get("evade") and tgt["formation"] != "混乱" and tgt["fatigue"] < 70 and not surprise \
                and orders.get(tgt["id"], {}).get("order") not in ("charge", "attack"):
            catch = {"light_cav": 0.5, "heavy_cav": 0.2}.get(u["type"], 0.0)
            if t.rng.random() >= catch:
                u["fatigue"] += 15
                t.ev(f"{label(u)}冲向{label(tgt)}，骑射散开退走，扑了个空")
                continue
        if surprise:
            tgt["morale"] = max(0, tgt["morale"] - 10)
        res = charge_result(t, u, tgt, dirn, ratio)
        u["fatigue"] += T(u).get("charge_fatigue", 30 if T(u)["mounted"] else 15)
        tag = "" if dirn == "正面" else f"从{dirn}"
        t.ev(f"{label(u)}{tag}冲击{label(tgt)}（冲击比 {ratio:.2f}）：{res}")
        leader_charge_events(t, u, tgt, ratio >= 1.5)
        if frontal(u, tgt):
            st["sectors"][u["sector"]]["gap"] = 0
            if ratio < 1.0 and T(u)["mounted"]:
                u["line"] = "back"
                t.ev(f"{u['id']}冲势受挫，退回本阵后方")
                if not units_at(st, u["side"], u["sector"], "front"):
                    st["sectors"][u["sector"]]["gap"] = 1
        u["_charged"] = True


def melee_mult(st, u, tgt):
    m = 1.0
    s = u["sector"]
    hill = feature(st, s, "hill")
    if hill and hill.get("holder") == u["side"]:
        m *= 1.15
    camp = feature(st, s, "camp")
    if camp and camp.get("holder") == u["side"] and u["line"] == "front":
        m *= 1.3
    if feature(st, s, "forest") and T(u)["mounted"]:
        m *= 0.7
    return m * hurt(u, tgt)   # 护甲、操练（旧版“打具装 ×0.7”并入这里）


def phase_melee(t, orders):
    st = t.state
    blows = []
    for u in st["units"]:
        if not active(u) or u.get("_charged"):
            continue
        o = orders.get(u["id"], {})
        kind = o.get("order", "hold")
        if kind in ("withdraw", "retreat", "rally", "flank", "commit", "move", "pursue"):
            continue
        gap = st["sectors"][u["sector"]]["gap"]
        if u["line"] == "front":
            if kind == "attack" and gap == 1:
                st["sectors"][u["sector"]]["gap"] = 0
                gap = 0
                t.ev(f"{label(u)}向前逼近，与敌接战")
            if gap != 0:
                continue
        elif kind != "attack":
            # 侧后的部队、后队、预备队，只有下了“接战”令才动手
            continue

        def ok(x):
            return active(x) or x["formation"] == "溃散"
        tgt = pick_target(st, u, ok, o.get("target"))
        if tgt is None:
            continue
        dirn = direction(st, u, tgt)
        if T(tgt).get("evade") and tgt["formation"] != "混乱" and tgt["fatigue"] < 70 and not T(u)["mounted"] \
                and orders.get(tgt["id"], {}).get("order") not in ("charge", "attack"):
            t.ev(f"{label(u)}逼向{label(tgt)}，骑射退开，追不上")
            if u["line"] == "front":
                st["sectors"][u["sector"]]["gap"] = max(st["sectors"][u["sector"]]["gap"], 1)
            continue
        reveal(t, u)
        power = eff(st, u) * T(u)["melee"] * DIR_MULT[dirn] * melee_mult(st, u, tgt)
        if kind == "advance":
            power *= 1.1
        if kind == "shoot":
            power *= 0.5
        blows.append((u, tgt, dirn, power))
    for u, tgt, dirn, power in blows:
        if not on_field(tgt):
            continue
        cas = 35 * power * t.rng.uniform(0.8, 1.2)
        pct = cas / max(1, tgt["men"])
        extra = {"正面": 0, "侧面": 5, "背后": 10}[dirn]
        cas = t.damage(tgt, cas, dirn, morale=pct * 100 + extra, killer=u)
        u["fatigue"] += 8 if not T(u)["mounted"] else 10
        dpow = eff(st, tgt) * T(tgt)["melee"] if on_field(tgt) else 0.01
        pr = power / max(0.05, dpow)
        txt = f"{label(u)}{'' if dirn == '正面' else '从' + dirn}与{label(tgt)}搏战，杀伤 {cas}"
        if on_field(tgt) and tgt["formation"] in ("严整", "松动"):
            p = 0.5 if pr > 1.5 else (0.2 if pr > 1.0 else 0.0)
            if dirn != "正面":
                p += 0.3
            if t.rng.random() < p:
                degrade(tgt)
                txt += f"，{tgt['id']}阵形转为{tgt['formation']}"
        t.ev(txt)


def phase_pursue(t, orders):
    st = t.state
    for u in st["units"]:
        if not active(u):
            continue
        o = orders.get(u["id"], {})
        if o.get("order") != "pursue":
            continue
        routed = [x for x in st["units"] if x["side"] != u["side"] and on_field(x) and x["formation"] == "溃散"
                  and (x["sector"] == u["sector"] or T(u)["speed"] >= 2)]
        if not routed:
            t.ev(f"{label(u)}要追击，但附近没有溃兵")
            continue
        tgt = find(st, o.get("target")) if o.get("target") else None
        if tgt not in routed:
            routed.sort(key=lambda x: (x["sector"] != u["sector"], -x["men"]))
            tgt = routed[0]
        mult = 1.5 if u["line"] == "rear" else 1.0
        cas = min(tgt["men"] * 0.4, 150 * eff(st, u) / max(0.3, FORM_MULT[u["formation"]])
                  * T(u)["pursuit"] * drill_of(u)["kill"] * mult * t.rng.uniform(0.8, 1.2))
        cap = round(cas * 0.4)
        cas = t.damage(tgt, cas, "背后", morale=5, killer=u, captured=cap)
        u["fatigue"] += 15 if T(u)["mounted"] else 10
        if u["line"] in ("flank", "rear", "back", "reserve"):
            pass
        u["sector"] = tgt["sector"] if tgt["line"] != "off" else u["sector"]
        if u["line"] not in ("flank", "rear"):
            u["line"] = "front"
        t.ev(f"{label(u)}追杀{label(tgt)}，斩获 {cas}（其中生俘约 {cap}）")
        ld = leader_of(st, tgt)
        if ld and T(u)["mounted"]:
            r = t.rng.random()
            if r < 0.08:
                st["sides"][tgt["side"]]["leaders"][ld["name"]]["status"] = "被俘"
                t.ev(f"{ld['name']}在乱军中被擒")
            elif r < 0.12:
                st["sides"][tgt["side"]]["leaders"][ld["name"]]["status"] = "阵亡"
                t.ev(f"{ld['name']}死于乱军之中")


def neighbours(st, u):
    res = []
    i = SECTORS.index(u["sector"]) if u["sector"] in SECTORS else 1
    for x in st["units"]:
        if x is u or x["side"] != u["side"] or not active(x):
            continue
        if x["sector"] == u["sector"] and x["line"] in ("front", "back"):
            res.append((x, 12))
        elif x["line"] == "front" and x["sector"] in SECTORS and abs(SECTORS.index(x["sector"]) - i) == 1 \
                and u["line"] == "front":
            res.append((x, 8))
        elif x["line"] == "reserve" and u["sector"] == "中":
            res.append((x, 8))
    return res


def rout(t, u, why):
    u["formation"] = "溃散"
    t.routed_now.append(u)
    t.ev(f"【溃】{label(u)}{why}，阵脚大乱，掉头奔逃")


def phase_morale(t):
    st = t.state
    checked = set()
    queue = []
    for u in st["units"]:
        if not active(u):
            continue
        h = t.hit.get(u["id"])
        if not h and u["formation"] != "混乱":
            continue
        thr = 40 + T(u).get("fragile", 0) + drill_of(u)["thr"] - DRILL[T(u).get("drill", "regular")]["thr"]
        if u["morale"] <= 20:
            rout(t, u, "士气已尽")
        elif u["morale"] < thr:
            p = (thr - u["morale"]) / thr * 0.8
            if u["formation"] == "混乱":
                p += 0.2
            if h and h["dirs"] & {"侧面", "背后"}:
                p += 0.2
            if t.rng.random() < p:
                rout(t, u, f"士气跌到 {u['morale']}")
        checked.add(u["id"])
    queue = list(t.routed_now)
    seen_chain = set()
    while queue:
        r = queue.pop(0)
        if r["id"] in seen_chain:
            continue
        seen_chain.add(r["id"])
        for x, drop in neighbours(st, r):
            if x["id"] in seen_chain:
                continue
            x["morale"] = max(0, x["morale"] - drop)
            thr = 45 + T(x).get("fragile", 0) + drill_of(x)["thr"] - DRILL[T(x).get("drill", "regular")]["thr"]
            if x["morale"] < thr and active(x):
                p = (thr - x["morale"]) / thr
                if x["formation"] == "混乱":
                    p += 0.2
                if t.rng.random() < p:
                    rout(t, x, f"见{r['id']}溃退，跟着动摇")
                    queue.append(x)
                else:
                    t.ev(f"{label(x)}见{r['id']}溃退，军心动摇，勉强稳住（士气 {x['morale']}）")
    # 全军动摇：损失过半
    for side in "AB":
        men0 = sum(u["men0"] for u in st["units"] if u["side"] == side)
        bad = sum(u["men0"] - u["men"] + (u["men"] if on_field(u) and u["formation"] == "溃散" else 0)
                  for u in st["units"] if u["side"] == side)
        if not st["sides"][side]["shaken"] and men0 and bad / men0 >= 0.5:
            st["sides"][side]["shaken"] = True
            for u in st["units"]:
                if u["side"] == side and active(u):
                    u["morale"] = max(0, u["morale"] - 10)
            t.ev(f"{st['sides'][side]['name']}折损过半，全军动摇（各部士气 -10）")


def phase_recover(t, orders):
    st = t.state
    for u in st["units"]:
        if not on_field(u):
            continue
        o = orders.get(u["id"], {})
        kind = o.get("order", "hold")
        hit = u["id"] in t.hit
        if u["formation"] == "溃散":
            if u in t.routed_now:
                continue
            if kind == "rally" and not hit:
                ld = leader_of(st, u)
                p = 0.25 + ((ld.get("统率", 5) - 5) * 0.05 if ld else 0) + (0.15 if u["line"] != "front" else 0)
                if t.rng.random() < p:
                    u["formation"] = "混乱"
                    u["morale"] = max(u["morale"], 30)
                    t.ev(f"{label(u)}收住溃兵，重新聚拢（阵形混乱，士气 {u['morale']}）")
                    continue
            # 溃兵后撤：前 → 后 → 离场
            if u["line"] in ("front", "flank", "rear", "transit"):
                u["line"] = "back" if u["line"] == "front" else "off"
            elif u["line"] in ("back", "reserve"):
                u["line"] = "off"
            if u["line"] == "off":
                lost = round(u["men"] * 0.2)
                u["men"] -= lost
                u["dispersed"] += lost
                t.ev(f"{label(u)}逃出战场，沿途逃散 {lost} 人，余 {u['men']} 人")
            else:
                lost = round(u["men"] * 0.03)
                u["men"] -= lost
                u["dispersed"] += lost
            continue
        contact = u["line"] == "front" and st["sectors"][u["sector"]]["gap"] == 0 \
            and units_at(st, other(u["side"]), u["sector"], "front")
        if kind == "rally":
            if contact or hit:
                t.ev(f"{label(u)}想回整，但{'正与敌接战' if contact else '正受敌箭矢、冲击'}，整不起来")
            else:
                improve(u)
                u["fatigue"] = max(0, u["fatigue"] - 20)
                u["morale"] = min(100, u["morale"] + 3)
                t.ev(f"{label(u)}回整队伍，阵形恢复为{u['formation']}")
        elif kind == "hold" and not contact:
            u["fatigue"] = max(0, u["fatigue"] - 5)
            if not hit and u["formation"] == "松动" and t.rng.random() < 0.5:
                improve(u)
        if u["line"] in ("back", "reserve") and not hit and kind in ("hold", "rally"):
            u["fatigue"] = max(0, u["fatigue"] - 10)
        u["fatigue"] = max(0, min(100, u["fatigue"]))
        u.pop("_charged", None)
    # 一侧前线空了，接战解除
    for s in SECTORS:
        sec = st["sectors"][s]
        if sec["gap"] == 0 and (not units_at(st, "A", s, "front") or not units_at(st, "B", s, "front")):
            sec["gap"] = 1


def standing_orders(st, orders):
    """没有明令的部队按常令行事。"""
    for u in st["units"]:
        if not active(u) or u["id"] in orders:
            continue
        sd = STANDING_ALIASES.get(u.get("standing", "hold"), u.get("standing", "hold"))
        gap = st["sectors"][u["sector"]]["gap"] if u["sector"] in SECTORS else 9
        foe = [x for x in st["units"] if x["side"] != u["side"] and on_field(x) and not x["hidden"]
               and direction(st, u, x)]
        if sd in ("pursue", "charge_if_loose") and T(u)["mounted"]:
            routed = [x for x in st["units"] if x["side"] != u["side"] and on_field(x) and x["formation"] == "溃散"
                      and x["sector"] == u["sector"]]
            if routed:
                orders[u["id"]] = {"order": "pursue", "target": routed[0]["id"], "auto": "常令：见溃即追"}
                continue
        if sd == "charge_if_loose" and T(u)["mounted"] and u["fatigue"] < 60 and u["formation"] != "混乱":
            loose = [x for x in foe if x["formation"] in ("松动", "混乱")
                     and (not frontal(u, x) or gap <= T(u).get("charge_gap", 1))]
            if loose:
                loose.sort(key=lambda x: (x["formation"] != "混乱", -x["men"]))
                orders[u["id"]] = {"order": "charge", "target": loose[0]["id"], "auto": "常令：见敌阵松动即冲"}
                continue
        if sd == "pursue" and not T(u)["mounted"]:
            routed = [x for x in foe if x["formation"] == "溃散"]
            if routed:
                orders[u["id"]] = {"order": "pursue", "target": routed[0]["id"], "auto": "常令：见溃即追"}
                continue
        if sd == "shoot" and T(u)["missile"] > 0:
            orders[u["id"]] = {"order": "shoot", "auto": "常令：见敌即射"}
            continue


def parse_orders(st, raw):
    orders, notes = {}, []
    for side in ("A", "B"):
        lst = raw.get(side, [])
        if isinstance(lst, dict):
            lst = [dict(v, unit=k) for k, v in lst.items()]
        for o in lst:
            uid = o.get("unit")
            targets = [u for u in st["units"] if u["side"] == side and on_field(u)] if uid in ("全军", "*", "all") \
                else [find(st, uid)]
            for u in targets:
                if u is None or u["side"] != side:
                    notes.append(f"[军令无效] {side} 方没有部队 {uid}")
                    continue
                oo = dict(o)
                oo.pop("unit", None)
                if "standing" in oo:
                    sd = STANDING_ALIASES.get(oo.pop("standing"), None) or o["standing"]
                    u["standing"] = sd
                if "order" in oo:
                    oo["order"] = ORDER_ALIASES.get(oo["order"], oo["order"])
                    if oo["order"] == "flank" and o.get("order") == "绕后":
                        oo["to"] = "rear"
                    if oo["order"] not in ("advance", "charge", "attack", "shoot", "hold", "flank", "withdraw",
                                           "rally", "commit", "move", "pursue", "retreat", "face"):
                        notes.append(f"[军令无效] {u['id']}：不认识的命令 {o['order']}")
                        continue
                    orders[u["id"]] = oo
    return orders, notes


# ------------------------------------------------------------------ 胜负
def side_status(st, side):
    act = [u for u in st["units"] if u["side"] == side and active(u)]
    return act, sum(u["men"] for u in act), sum(u["men0"] for u in st["units"] if u["side"] == side)


def check_end(st, t):
    a_act, a_men, a0 = side_status(st, "A")
    b_act, b_men, b0 = side_status(st, "B")
    names = {k: st["sides"][k]["name"] for k in "AB"}
    if not a_act and not b_act:
        return "draw", "两军俱散"
    for side, act in (("A", a_act), ("B", b_act)):
        if not act:
            routed = any(u["side"] == side and u["formation"] == "溃散" for u in st["units"])
            how = "全军溃散" if routed and not any(u["side"] == side and u["line"] == "off" and u["formation"] != "溃散"
                                                for u in st["units"]) else ("兵败撤出战场" if routed else "收兵撤出战场")
            return other(side), f"{names[side]}{how}"
    if st["tick"] >= st["sunset"]:
        ra, rb = a_men / max(1, a0), b_men / max(1, b0)
        if ra <= 0.4 or rb <= 0.4:
            if ra < rb:
                return "B", f"日落收兵。{names['A']}能战之兵只剩{ra:.0%}，退出战场"
            return "A", f"日落收兵。{names['B']}能战之兵只剩{rb:.0%}，退出战场"
        return "draw", "日落收兵，胜负未分"
    return None, None


def finalize(st, winner, why):
    st["finished"] = True
    events = []
    # 战场上还没跑掉的溃兵：胜方有骑兵就多被俘一些
    for u in st["units"]:
        if on_field(u) and u["formation"] == "溃散" and winner in ("A", "B") and u["side"] != winner:
            has_cav = any(x["side"] == winner and active(x) and T(x)["mounted"] for x in st["units"])
            cap = round(u["men"] * (0.3 if has_cav else 0.1))
            u["men"] -= cap
            u["captured"] += cap
            taker = next((x for x in st["units"] if x["side"] == winner and active(x)), None)
            if taker:
                taker["took"]["captured"] += cap
            events.append(f"{label(u)}没能逃出，被俘 {cap} 人")
    res = {"winner": winner, "outcome": why, "ticks": st["tick"], "losses": {}, "remaining": {}, "captured": {},
           "morale_after": {}, "units": [], "leaders": {}, "events": events}
    for side in "AB":
        loss, rem, took = {}, {}, {}
        mor_w = mor_n = 0
        for u in st["units"]:
            if u["side"] != side:
                continue
            code = u["army_code"]
            loss[code] = loss.get(code, 0) + u["killed"] + u["captured"] + u["dispersed"]
            rem[code] = rem.get(code, 0) + max(0, u["men"])
            mor_w += u["morale"] * max(0, u["men"])
            mor_n += max(0, u["men"])
            res["units"].append({"id": u["id"], "side": side, "army_code": code, "men0": u["men0"], "men": u["men"],
                                 "killed": u["killed"], "captured_by_enemy": u["captured"],
                                 "dispersed": u["dispersed"], "morale": u["morale"],
                                 "status": "覆灭" if u["line"] == "gone" else ("溃散" if u["formation"] == "溃散"
                                                                            else ("离场" if u["line"] == "off" else "在阵"))})
        for u in st["units"]:
            if u["side"] == other(side):
                code = u["army_code"]
                took[code] = took.get(code, 0) + u["captured"]
        res["losses"][side] = loss
        res["remaining"][side] = rem
        res["captured"][side] = took   # 本方俘获的敌兵，按敌方兵种
        res["morale_after"][side] = round(mor_w / mor_n) if mor_n else 0
        res["leaders"][side] = {k: v.get("status", "无恙") for k, v in st["sides"][side].get("leaders", {}).items()}
    for side in "AB":
        role = st["sides"][side].get("role")
        if role in ("attacker", "defender"):
            res.setdefault("by_role", {})[role] = side
    st["result"] = res
    return res


# ------------------------------------------------------------------ 显示
def morale_word(m):
    return "高昂" if m >= 75 else "尚可" if m >= 55 else "动摇" if m >= 35 else "低落"


def visible(st, viewer, u):
    if u["side"] == viewer:
        return True
    if u["hidden"] or not on_field(u):
        return False
    if u["line"] == "reserve":
        return not st["weather"].get("fog") and any(
            x["side"] == viewer and active(x) and x["line"] in ("flank", "rear") for x in st["units"])
    if not st["weather"].get("fog"):
        return True
    # 雾：只看得见近处
    s = u["sector"]
    mine = [x for x in st["units"] if x["side"] == viewer and active(x) and x["sector"] == s]
    if u["line"] in ("flank", "rear"):
        return bool(mine)
    if any(x["line"] in ("flank", "rear") for x in mine):
        return True
    return any(x["line"] == "front" for x in mine) and st["sectors"][s]["gap"] <= 1 and u["line"] == "front"


def unit_line(u, exact):
    face = f" 面向{u['facing']}" if u.get("facing", "正面") != "正面" else ""
    if exact:
        s = f"{u['id']} {T(u)['name']}{u['men']} {u['formation']}{face} 士气{u['morale']} 疲劳{u['fatigue']}"
        if u.get("armor", T(u)["armor"]) != T(u)["armor"] or u.get("drill", "regular") != T(u).get("drill", "regular"):
            s += f" {ARMOR[u['armor']]['name']}·{DRILL[u['drill']]['name']}"
        if u.get("leader"):
            s += f" [{u['leader']}]"
        if u.get("hidden"):
            s += " (伏)"
        if u.get("standing", "hold") != "hold":
            s += f" 常令:{u['standing']}"
    else:
        s = f"{u['id']} {T(u)['name']}约{int(round(u['men'], -2))} {u['formation']}{face} 士气{morale_word(u['morale'])}"
    return s


def render(st, viewer=None, events=None):
    exact_all = viewer is None
    out = []
    tk = st["tick"]
    name = TICK_NAMES[tk] if tk < len(TICK_NAMES) else f"第{tk}刻"
    out.append(f"━━ {st.get('title', '战场')} · 第{tk}刻（{name}），距日落还有 {max(0, st['sunset'] - tk)} 刻"
               f"{' · 有雾' if st['weather'].get('fog') else ''} ━━")
    if viewer:
        out.append(f"（{st['sides'][viewer]['name']}所见）")
    if events:
        out.append("本刻纪事：")
        for e in events:
            out.append("  · " + e)
    for s in SECTORS:
        sec = st["sectors"][s]
        feats = "、".join({"river": "河", "forest": "林", "hill": "高地", "camp": "营垒"}.get(f["type"], f["type"])
                         + (f"（{st['sides'][f['holder']]['name']}据守）" if f.get("holder") else "")
                         for f in sec["features"]) or "平地"
        out.append(f"【{SECTOR_NAME[s]}】两军{GAP_NAME.get(sec['gap'], '相距甚远')} · 地形：{feats}")
        for side in "AB":
            nm = st["sides"][side]["name"]
            for line in ("front", "back", "flank", "rear", "transit"):
                us = [u for u in st["units"] if u["side"] == side and u["sector"] == s and u["line"] == line
                      and on_field(u) and visible(st, viewer or side, u)]
                if not us:
                    if line in ("front", "back") and (exact_all or side == viewer or not st["weather"].get("fog")):
                        out.append(f"    {nm} {LINE_NAME[line]}：—")
                    continue
                where = {"flank": f"在{st['sides'][other(side)]['name']}侧翼",
                         "rear": f"在{st['sides'][other(side)]['name']}背后",
                         "transit": "迂回途中"}.get(line, LINE_NAME[line])
                exact = exact_all or side == viewer
                out.append(f"    {nm} {where}：" + "；".join(unit_line(u, exact) for u in us))
    for side in "AB":
        us = [u for u in st["units"] if u["side"] == side and u["line"] == "reserve" and on_field(u)]
        if us and (exact_all or side == viewer):
            out.append(f"【预备】{st['sides'][side]['name']}：" + "；".join(unit_line(u, True) for u in us))
        elif us and any(visible(st, viewer, u) for u in us):
            out.append(f"【预备】{st['sides'][side]['name']}：" + "；".join(unit_line(u, False) for u in us
                                                                       if visible(st, viewer, u)))
        elif us and not st["weather"].get("fog") and any(not u["hidden"] for u in us):
            out.append(f"【预备】{st['sides'][side]['name']}：后方另有一部人马，看不真切")
    gone = [u for u in st["units"] if not on_field(u) or (u["line"] == "off")]
    gone = [u for u in gone if exact_all or u["side"] == viewer]
    if gone:
        out.append("【已离场】" + "；".join(f"{u['id']}{'覆灭' if u['line'] == 'gone' else '离场'}"
                                         f"（余{max(0, u['men'])}）" for u in gone))
    for side in "AB":
        if exact_all or side == viewer:
            lds = st["sides"][side].get("leaders", {})
            bad = [f"{k}{v['status']}" for k, v in lds.items() if v.get("status")]
            if bad:
                out.append(f"【将领】{st['sides'][side]['name']}：" + "、".join(bad))
    return "\n".join(out)


def view_json(st, viewer):
    res = {"tick": st["tick"], "sunset": st["sunset"], "fog": bool(st["weather"].get("fog")),
           "sectors": {s: {"gap": st["sectors"][s]["gap"], "features": st["sectors"][s]["features"]}
                       for s in SECTORS}, "units": []}
    for u in st["units"]:
        if viewer and not visible(st, viewer, u):
            continue
        exact = viewer is None or u["side"] == viewer
        d = {"id": u["id"], "side": u["side"], "type": u["type"], "sector": u["sector"], "line": u["line"],
             "formation": u["formation"]}
        if exact:
            d.update(men=u["men"], morale=u["morale"], fatigue=u["fatigue"], leader=u.get("leader"),
                     standing=u.get("standing"), hidden=u.get("hidden"))
        else:
            d.update(men_est=int(round(u["men"], -2)), morale=morale_word(u["morale"]))
        res["units"].append(d)
    return res


# ------------------------------------------------------------------ 主流程
def run_tick(st, raw_orders, seed=None):
    if st.get("finished"):
        die("这一仗已经打完了。用 report 查看结果。")
    if seed is not None:
        st["seed"] = seed
    st["tick"] += 1
    rng = random.Random(f"{st['seed']}:{st['tick']}")
    t = Tick(st, rng)
    orders, notes = parse_orders(st, raw_orders)
    for n in notes:
        t.ev(n)
    standing_orders(st, orders)
    for uid, o in orders.items():
        if o.get("auto"):
            t.ev(f"{label(find(st, uid))}按{o['auto']}行事")
    phase_move(t, orders)
    phase_shoot(t, orders)
    phase_charge(t, orders)
    phase_melee(t, orders)
    phase_pursue(t, orders)
    phase_morale(t)
    phase_recover(t, orders)
    for u in st["units"]:
        u.pop("_charged", None)
    st["log"].append({"tick": st["tick"], "events": t.events,
                      "orders": {k: v for k, v in orders.items()}})
    winner, why = check_end(st, t)
    res = None
    if winner:
        res = finalize(st, winner, why)
    return t.events, res


def summary_text(st, res):
    nm = {k: st["sides"][k]["name"] for k in "AB"}
    w = res["winner"]
    out = [f"══ 战罢：{res['outcome']}。" + (f"胜者：{nm[w]}" if w in nm else "不分胜负") + f"（共 {res['ticks']} 刻）══"]
    for side in "AB":
        loss = res["losses"][side]
        out.append(f"{nm[side]}  损失：" + "，".join(f"{k} {v}" for k, v in loss.items())
                   + f"；尚存：" + "，".join(f"{k} {v}" for k, v in res["remaining"][side].items())
                   + f"；俘获敌兵：{sum(res['captured'][side].values())}；平均士气 {res['morale_after'][side]}")
    for e in res["events"]:
        out.append("  · " + e)
    return "\n".join(out)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, st):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description="亲临指挥的战斗（一刻一回合）")
    ap.add_argument("cmd", choices=["new", "show", "turn", "report", "morale"])
    ap.add_argument("--state", required=True, help="战场状态文件（读写）")
    ap.add_argument("--from", dest="src", help="new：初始战例文件")
    ap.add_argument("--orders", help="turn：本刻双方军令（JSON 文件，- 表示从标准输入读）")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--view", choices=["A", "B"], help="只显示这一方看得见的东西（给角色 agent 用）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--dry-run", action="store_true", help="turn：只演算，不写回状态文件")
    ap.add_argument("--side", choices=["A", "B"], help="morale：哪一方")
    ap.add_argument("--delta", type=int, help="morale：士气加减")
    ap.add_argument("--leader", action="append", default=[], help="morale：名=负伤|阵亡|被俘|无恙，可重复")
    ap.add_argument("--why", default="阵前单挑", help="morale：缘由，记进纪事")
    a = ap.parse_args()

    if a.cmd == "new":
        if not a.src:
            die("new 需要 --from 初始战例文件")
        st = normalize_state(load(a.src))
        if a.seed is not None:
            st["seed"] = a.seed
        save(a.state, st)
        print(render(st))
        return
    st = normalize_state(load(a.state))
    if a.cmd == "show":
        if a.json:
            print(json.dumps(view_json(st, a.view), ensure_ascii=False, indent=1))
        else:
            print(render(st, a.view))
        return
    if a.cmd == "morale":
        if not a.side or a.delta is None:
            die("morale 需要 --side 和 --delta")
        for e in shift_morale(st, a.side, a.delta, a.leader, a.why):
            print(e)
        save(a.state, st)
        return
    if a.cmd == "report":
        if not st.get("result"):
            print("这一仗还没打完。")
            print(render(st))
        else:
            print(summary_text(st, st["result"]) if not a.json else
                  json.dumps(st["result"], ensure_ascii=False, indent=1))
        return
    if not a.orders:
        die("turn 需要 --orders 军令文件")
    raw = json.loads(sys.stdin.read() if a.orders == "-" else open(a.orders, encoding="utf-8").read())
    events, res = run_tick(st, raw, a.seed)
    if not a.dry_run:
        save(a.state, st)
    if a.json:
        print(json.dumps({"tick": st["tick"], "events": events, "view": view_json(st, None), "result": res},
                         ensure_ascii=False, indent=1))
    else:
        print(render(st, None, events))
        if res:
            print(summary_text(st, res))


if __name__ == "__main__":
    main()
