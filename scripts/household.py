#!/usr/bin/env python3
"""家宅：家人的年龄、身体、人生节点、陪伴与冷落、亲疏阶梯，以及家事对主线的牵连。

规则见 rules/household.md。存档是 world/household.json，家人的人格卡模板见 characters/_template_kin.md。
人心账本（需求、心结、牵扯）和将领共用格式，由 scripts/loyalty.py 的 Card 读写。
只用标准库。所有会改存档、改卡片的命令，默认只打印；加 --apply 才写回。

  总览     show [id]                       家里每个人：年纪、住处、身体、亲疏、在忙什么、多久没见
  提示     hint id                         写进 kin agent prompt 的“亲疏提示”
  季末     season [--when 某年夏] [--seed N] [--war] [--trigger id=事件 ...] [--care id ...]
                                           推进一季：冷落计时、心结淡化、亲疏阶梯、怀孕、身体、到点的人生节点
  家事     visit id --what 做了什么 [--earnest] [--letter]
                                           记一件家事（陪伴或家书），每季有上限；用心陪伴可消解冷落的心结
  节点     milestone id 节点 --choice 走向 | --defer 季数
  有孕     pregnant id
  出生     birth 母亲id --id 新id --name 名 --sex 男|女 [--card 路径]
  议亲     match id --to 对方 --kind 联姻|结亲|本地|自择 --consent 愿意|勉强|不愿 [--fit 0-3] [--faction 势力] [--due 回合]
  为质     hostage id --to 势力 --consent 愿意|勉强|不愿
  牵扯     tie id --from 谁 --aim 所图 --promise 许以 | --withdraw 序号
  图谋     plot id --kind 收买|离间|绑架|行刺 --by 谁 [--guard 0-2] [--seed N]
  立嗣     heir id --why 缘由
  新增     add --id x --name 名 --relation 弟 --sex 男 --born 876 --residence 治所·帅府 [--card ...] [--trait ...]
  改字段   set id 字段=值 [字段=值 ...]       busy、residence、health、status、spouse、closeness、neglect_limit、trait
  主角     where 地名                        主角眼下所在（出征时改，回治所再改回）
  家事记录 event --kind 喜|丧|病|其他 --what 事由

多个家宅（rules/household.md 第九节）：--house 指定哪一家。默认 main 是主角家（world/household.json）；
宫中、某个大族放在 world/households/<名字>.json（kind: palace / clan），例如 --house palace。
  病程     illness id [--name 病名] [--stage N] [--pace 0.12] [--major 2] [--known-by 名,名] [--secret S1]
  宠爱     favor id --delta N --why 来由
  家宅     houses                           列出所有家宅
别的家宅能用 show、season（宫中另推病程、宠爱、储位形势）、add、set、event、pregnant、birth、milestone、
match、tie、plot、heir；visit、hint、where 只用于主角家。

--world 指向别的存档目录（试验用）。卡片路径相对存档目录的上一级解析，找不到再相对项目根目录。
"""
import argparse
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import loyalty as L  # noqa: E402
import scenario_lib as S  # noqa: E402

SEASONS = ["春", "夏", "秋", "冬"]
CN = "〇一二三四五六七八九"

KIN_LEVELS = ["亲近", "疏淡", "怨怼", "另有打算"]
KIN_TRIGGERS = {
    "逼婚": "不顾本人不愿，定下或办了婚事",
    "送质": "不顾本人不愿，送去别家为质",
    "至亲受害": "因主角之过，他的至亲（子女、母族、配偶）被囚、被杀、被逐",
    "废立": "已有的名分被夺：嫡子被废、正妻被降、许下的嗣位改给别人",
    "当众羞辱": "当着外人、下人的面被斥骂、责打",
}
KIN_CEILING = {
    "亲近": "愿意说心里话，替主角在家里周旋、在外头说好话；母族来信会拿给主角看。不瞒事。",
    "疏淡": "话少，不主动开口；家事照办，不多操心；心里的事不说。不和外人私下往来。",
    "怨怼": "可以当面顶撞、哭闹、冷脸、托病不见，向母族、兄弟、乳母诉苦；不合意的安排可以拖着（拖婚期、不肯启程）。"
            "不和外人私下密谋，不递消息出去。",
    "另有打算": "可以私下和外头往来（母族、意中人、敌方来人、朝中一派），给自己安排后路（私蓄、私定终身、结交将领），"
               "逃避或推掉安排（逃婚、出家、回母族）；有人拉拢时可以递消息。不行刺、不举兵（领兵的兄弟改走将领规则）。",
}
KIN_SIGNS = {
    "亲近": ["没有异样。说话随意，有事先来商量。"],
    "疏淡": ["请安、问话都答得规矩，不多说一句。", "以前常来书房，近来不来了。", "家里的事办得周全，但不再问主角的意思。"],
    "怨怼": ["当着下人冷着脸，或者红着眼出来。", "乳母、仆妇私下说她（他）夜里哭过，或者摔过东西。",
             "托病不见；吩咐的事拖着不办。", "往母族、兄弟处写信诉苦，信使比往常勤。"],
    "另有打算": ["生面孔出入后宅，说是母族来人、寺里的师父、卖首饰的。", "私房钱、首饰悄悄往外挪。",
                 "和某位将领、某家的人走得近，说话避着人。", "打听出城的路、远处的亲戚，或者忽然肯答应原先不肯的事。"],
}

HEALTH = ["健朗", "小恙", "多病", "病重"]
STATUS_ALIVE = ("在", "出嫁", "为质", "被掳", "离去", "幽禁", "出居")
# 宫中的称呼照家里的算：皇子、公主是子女，皇后是正妻，妃嫔是侧室（rules/household.md 第九节）
SON_REL = {"子", "皇子"}
DAUGHTER_REL = {"女", "公主"}
CHILD_REL = SON_REL | DAUGHTER_REL
YOUNG_REL = CHILD_REL | {"弟", "妹", "侄", "侄女", "孙", "孙女", "皇孙"}
MAIN_WIFE = {"妻", "皇后"}
SPOUSE_REL = {"妻", "妾", "皇后", "贵妃", "淑妃", "德妃", "贤妃", "妃", "嫔", "昭仪", "昭容", "昭媛", "修仪", "婕妤",
              "美人", "才人", "夫人", "宝林", "御女", "采女"}


def list_houses(world):
    d = os.path.join(world, "households")
    if not os.path.isdir(d):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(d) if f.endswith(".json"))

# 人生节点：名称、谁、虚岁窗口（上限 None 表示没有上限）、可选的走向（GM 写成家事交给玩家）
MILESTONES = [
    ("启蒙", None, 6, 8, [
        "请塾师在家教书（读经史；日后可入仕、可议亲士族）",
        "送入寺学（和城中子弟同学，结识人家；僧人也会说话）",
        "由母亲教母族的话和规矩（两边的人都认；母族体面 +1）",
        "再缓一年（孩子还小，或家里顾不上）"]),
    ("习武", None, 9, 12, [
        "主角亲自教骑射（“被父亲看见”一类需求 +1，每季占一件家事）",
        "交给一位将领带（那位将领与这个孩子结下情分；将领“被信任”一类需求可 +1）",
        "入亲军少年营（和军中子弟一起长大，日后有自己的人）",
        "偏重读书，不学武（女儿不学的也写这一项）"]),
    ("及笄", "女", 15, 16, [
        "在家行礼，请亲族女眷来（俭）", "大办，请部将家眷、本地大族（常或丰；顺带看人家）", "从母族的风俗办"]),
    ("冠礼", "男", 20, 21, [
        "请一位将领或幕僚做宾，取字（那人与他结下情分）", "主角亲自加冠（父子、兄弟情分）", "简办（战事或家计）"]),
    ("从仕", "男", 16, 18, [
        "授牙内职，留在帅府学事（日后可委任）", "随军出征（有立功之望，也有凶险）",
        "读书应举或入朝（远离治所，可在朝中结交）", "留在身边，暂不任事"]),
    ("议亲", None, None, None, [
        "与邻镇、部落联姻：可结盟或缓和，先问本人愿不愿意（match --kind 联姻）",
        "许给部将或部将之子：笼络将领（match --kind 结亲；那位将领“被信任/被重用”一类需求 +1，或抵消一条心结）",
        "本地大族：安内，大族可捐输（match --kind 本地；一次进项不超过帅府一季钱收入的一成）",
        "让本人自己相看（match --kind 自择；本人婚事一类需求 +1 到 +2，政治上没有所得）",
        "暂缓（--defer 4；一年后再提，年岁渐长，母亲、本人可能着急）"]),
]
MARRY_AGE = {"女": 14, "男": 16}

# 宫中的人生节点（皇子、公主）：同样到点列出走向，GM 写成宫中的事，玩家多半只从旁人嘴里听到
PALACE_MILESTONES = [
    ("就学", None, 6, 8, [
        "请一位大臣做师傅（两人记“师生”，relations.py tag；那位大臣和他那一派从此和这位皇子连在一起）",
        "在宫中内学读书（和宗室子弟同学，师傅是宫里的人）",
        "再缓一年"]),
    ("习武", "男", 9, 12, [
        "请禁军将领教骑射（将门和这位皇子有了来往）", "只读书，不学武"]),
    ("出阁", "男", 14, 16, [
        "封王开府、出居宫外（有了自己的僚属，可以结交朝臣；离天子远了）",
        "留在宫中（离天子近，离朝臣远）"]),
    ("冠礼", "男", 16, 20, ["天子亲临加冠（宠爱的表示）", "照常例办", "简办（宫中多事）"]),
    ("及笄", "女", 15, 16, ["照常例在宫中行礼", "大办（母妃得宠的表示）"]),
    ("议亲", "男", None, None, [
        "选妃于大族（那一家成了外戚，和他们那一派连在一起；match --kind 联姻）",
        "选妃于小户（不添外戚的分量，朝中各派都放心些）",
        "暂缓（--defer 4）"]),
    ("议亲", "女", None, None, [
        "下嫁大族、重臣之子（驸马家和宫中结亲，那一派多一层倚仗；match --kind 联姻）",
        "下嫁将门（和军中连在一起）",
        "暂缓（--defer 4）"]),
]

BUDGET = {
    "俭": {"money": 300, "grain": 300, "说明": "简办。本人、亲家可能觉得不体面"},
    "常": {"money": 800, "grain": 600, "说明": "照常例"},
    "丰": {"money": 2000, "grain": 1200, "说明": "大办。亲家、部将家眷都看在眼里"},
}


def die(msg):
    sys.exit(f"错误：{msg}")


def cn_num(n):
    if n <= 10:
        return "十" if n == 10 else CN[n]
    if n < 20:
        return "十" + (CN[n - 10] if n > 10 else "")
    t, u = divmod(n, 10)
    return CN[t] + "十" + (CN[u] if u else "")


# ---------- 存档 ----------

MAIN_HOUSE = ("main", "主角", "家")


class World:
    def __init__(self, path, house=None):
        global WORLD_DIR
        self.dir = os.path.abspath(path)
        WORLD_DIR = self.dir
        self.house = house or "main"
        self.is_main = self.house in MAIN_HOUSE
        # 主角家照旧是 world/household.json；别的家宅（宫中、某个大族）在 world/households/<名字>.json
        self.fname = "household.json" if self.is_main else os.path.join("households", f"{self.house}.json")
        self.hh = self.load(self.fname)
        self.kind = "main" if self.is_main else self.hh.get("kind", "clan")
        self.kingdom = self.load("kingdom.json", {})
        self.turn = self.kingdom.get("turn", 1)

    def head_id(self):
        """非主角家的家主（宫中是天子）：household 里的 head。"""
        h = self.hh.get("head")
        if h and h in self.members():
            return h
        return None

    def head(self):
        h = self.head_id()
        return self.members()[h] if h else None

    def father_name(self):
        if self.is_main:
            return self.hh.get("protagonist", {}).get("name")
        h = self.head()
        return h.get("name") if h else None

    def p(self, name):
        return os.path.join(self.dir, name)

    def load(self, name, default=None):
        try:
            with open(self.p(name), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            if default is not None:
                return default
            if name.startswith("households"):
                die(f"找不到 {self.p(name)}。家宅只有：{'、'.join(list_houses(self.dir)) or '主角家（household.json）'}；"
                    "新的家宅照 rules/household.md 第九节建")
            die(f"找不到 {self.p(name)}（新局从 scenarios/<剧本>/world/ 铺开，见 /newgame）")

    def save(self):
        os.makedirs(os.path.dirname(self.p(self.fname)), exist_ok=True)
        with open(self.p(self.fname), "w", encoding="utf-8") as f:
            json.dump(self.hh, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def card_path(self, rel):
        if not rel:
            return None
        if os.path.isabs(rel):
            return rel if os.path.exists(rel) else None
        for base in (os.path.dirname(self.dir), ROOT):
            cand = os.path.join(base, rel)
            if os.path.exists(cand):
                return cand
        return None

    def members(self):
        return self.hh.setdefault("members", {})

    def m(self, mid):
        ms = self.members()
        if mid in ms:
            return ms[mid]
        for k, v in ms.items():
            if v.get("name") == mid:
                return v
        names = "、".join(f"{k}={v.get('name')}" for k, v in ms.items())
        die(f"家里没有“{mid}”（有：{names}）")

    def mid(self, mid):
        ms = self.members()
        if mid in ms:
            return mid
        for k, v in ms.items():
            if v.get("name") == mid:
                return k
        return self.m(mid) and mid


# ---------- 历法 ----------

WORLD_DIR = os.path.join(ROOT, "world")  # World() 打开存档时改成实际目录


def _cal(hh):
    """纪年：household.json 的 calendar（旧存档）优先，其次 world/scenario.json。都没有就报错。"""
    return S.calendar(WORLD_DIR, household=hh)


def year_of(hh, turn):
    cal = _cal(hh)
    s0 = SEASONS.index(cal.get("turn1_season") or "春")
    idx = s0 + turn - 1
    return int(cal["turn1_year"]) + idx // 4, SEASONS[idx % 4]


def era_label(hh, year):
    return S.year_label(_cal(hh), year)


def date_label(hh, turn):
    y, s = year_of(hh, turn)
    return f"{era_label(hh, y)}{s}"


def age(hh, member, turn):
    """虚岁：生年算一岁，每年春天长一岁。"""
    y, _ = year_of(hh, turn)
    return y - int(member["born"]) + 1


def region_of(place):
    return (place or "").split("·")[0]


def alive(m):
    return m.get("status", "在") in STATUS_ALIVE


def at_side(w, m):
    """是否在主角身边（同一个州）；别的家宅，是否在家主身边。"""
    if not w.is_main:
        h = w.head()
        return bool(h and alive(h) and m.get("status", "在") == "在"
                    and region_of(m.get("residence")) == region_of(h.get("residence")))
    here = w.hh.get("protagonist", {}).get("where") or w.kingdom.get("player", {}).get("seat")
    return m.get("status", "在") == "在" and region_of(m.get("residence")) == here


def war_season(w, args):
    if getattr(args, "war", False):
        return True
    les = w.kingdom.get("last_economy_settlement", {})
    return bool(les.get("war")) and les.get("turn") == w.turn


def protagonist_away(w):
    p = w.hh.get("protagonist", {})
    return p.get("where") and p.get("where") != w.kingdom.get("player", {}).get("seat", p.get("where"))


def visit_cap(w, args):
    cfg = w.hh.get("rules", {})
    if protagonist_away(w):
        return cfg.get("cap_away", 1), "主角出征在外：只能写家书，或陪同在军中的家人"
    if war_season(w, args):
        return cfg.get("cap_war", 1), "战事季"
    return cfg.get("cap_peace", 2), "太平季"


# ---------- 卡片 ----------

def load_card(w, m):
    path = w.card_path(m.get("card"))
    if not path:
        return None
    return L.Card(path)


def kin_level(card):
    lv = card.yaml.get("亲疏", "亲近")
    if lv not in KIN_LEVELS:
        die(f"{card.path} 的“亲疏”应为 {'/'.join(KIN_LEVELS)}：{lv!r}")
    return lv


def neglect_grudge(card):
    return next((g for g in card.active() if "冷落" in g["extra"]), None)


def kin_target(card, triggers):
    P = L.pressure(card)
    gap = L.gap(card)
    X = P + gap
    base = 0 if X < 4 else 1 if X < 6 else 2 if X < 8 else 3
    why = [f"疏离分 {X:.1f}（未解心结 {P} + 需求缺口 {gap:.1f}）→ {KIN_LEVELS[base]}"]
    cap = 1 if P == 0 else 2
    if P >= 3 and (card.ties or triggers):
        cap = 3
    if base > cap:
        if cap == 1:
            why.append("没有未解的心结：最多“疏淡”。光是心愿落空，冷淡下来，说不出怨谁")
        elif P < 3:
            why.append(f"未解心结只有 {P}：最多“怨怼”")
        else:
            why.append("心结够深，但外头没人牵扯、本季也没有触发事件：最多“怨怼”")
        base = cap
    if triggers:
        why.append(f"触发事件：{'、'.join(triggers)}")
    return base, why


def kin_fade(card, still_neglected):
    """季末淡化，同 loyalty.fade；但冷落还在继续时，冷落的心结不淡化（计时照走，供加深用）。"""
    out = []
    for g in card.active():
        g["age"] += 1
        if "冷落" in g["extra"] and still_neglected:
            continue
        if g["s"] == 1 and g["age"] >= 4:
            g["status"] = "已淡忘（四季无人再提）"
            out.append(f"[{g['id']}] 强度 1，已历 4 季 → 已淡忘")
        elif g["s"] == 2 and g["age"] >= 8:
            g["s"], g["age"] = 1, 0
            out.append(f"[{g['id']}] 强度 2，已历 8 季 → 降为 1")
    return out


def kin_hint(card, level, w=None, m=None, mid=None):
    s = f"亲疏：{level}。行动上限：{KIN_CEILING[level]}"
    if card.ties:
        s += f" 外头的牵扯：{'；'.join(card.ties)}。"
    if w and m:
        n = w.turn - int(m.get("last_seen_turn", w.turn))
        if n >= 2:
            s += f" 主角已经 {n} 季没来看过{'她' if m.get('sex') == '女' else '他'}。"
    return s


# ---------- show / hint ----------

def fmt_member(w, mid, m, verbose=False):
    hh = w.hh
    a = age(hh, m, w.turn)
    seen = w.turn - int(m.get("last_seen_turn", w.turn))
    lim = int(m.get("neglect_limit", default_limit(m)))
    card = load_card(w, m) if m.get("card") else None
    close = m.get("closeness", "—")
    role = ""
    if card:
        if card.role == "家人":
            close = kin_level(card)
        elif card.role == "将领":
            close = "领兵"
            role = f"，离心 {card.yaml.get('离心', '?')}（按将领规则）"
        elif card.role in L.COURT_ROLES:
            close = f"心迹 {card.yaml.get('心迹', '恭谨')}"
    if not w.is_main:
        close = close if card and card.role in L.COURT_ROLES else ""
        if "favor" in m:
            role += f"｜宠爱 {favor_word(m['favor'])}"
        if m.get("illness"):
            il = m["illness"]
            st = (il.get("stages") or ILL_STAGES)[int(il.get("stage", 0))]
            role += f"｜{il.get('name', '病')}·{st}"
        if m.get("clan"):
            role += f"｜{m['clan']}"
    flag = ""
    if w.is_main and alive(m) and a >= 3:
        if seen >= lim:
            flag = f"【已 {seen} 季没见】"
        elif seen >= lim - 1 and seen >= 1:
            flag = f"（{seen} 季没见，再一季记心结）" if card else f"（{seen} 季没见）"
    line = (f"{m['name']}（{m.get('relation', '')}，{a} 岁，{m.get('sex', '')}）｜{m.get('residence', '')}｜"
            f"{m.get('health', '健朗')}｜{close}{role}｜{m.get('status', '在')} {flag}")
    out = [f"  [{mid}] {line}"]
    if verbose or True:
        if m.get("busy"):
            out.append(f"        在忙：{m['busy']}")
        if verbose and m.get("trait"):
            out.append(f"        性情：{m['trait']}")
        if verbose and m.get("spouse"):
            out.append(f"        配偶：{m['spouse']}")
        if verbose and m.get("milestones"):
            out.append("        节点：" + "；".join(f"{k}：{v}" for k, v in m["milestones"].items()))
        if verbose and card:
            out.append(f"        人格卡：{m.get('card')}  未解心结 {L.pressure(card)}  缺口 {L.gap(card):.1f}"
                       + (f"  牵扯 {len(card.ties)}" if card.ties else ""))
    return out


def default_limit(m):
    rel = m.get("relation", "")
    st = m.get("status", "在")
    if st in ("出嫁", "为质", "离去"):
        return 8
    if rel in ("母", "父"):
        return 4
    if rel in SPOUSE_REL:
        return 3
    if rel in CHILD_REL:
        return 3
    return 4


def cmd_show(w, args):
    hh = w.hh
    p = hh.get("protagonist", {})
    if not w.is_main:
        h = w.head()
        print(f"=== {hh.get('title', w.house)}（{w.house}，{'宫中' if w.kind == 'palace' else '大族'}）：{date_label(hh, w.turn)}（第 {w.turn} 回合） ===")
        if h:
            print(f"  家主 {h['name']}（{h.get('relation')}，{age(hh, h, w.turn)} 岁）")
        if hh.get("heir"):
            print(f"  {'储君' if w.kind == 'palace' else '嗣子'}：{hh['heir']}")
        for mid, m in w.members().items():
            if args.id and args.id not in (mid, m.get("name")):
                continue
            if not args.all and not alive(m):
                continue
            for l in fmt_member(w, mid, m, verbose=bool(args.id)):
                print(l)
        for pg in hh.get("pregnancies", []):
            print(f"  有孕：{w.members().get(pg['mother'], {}).get('name', pg['mother'])}，第 {pg['due_turn']} 回合临盆")
        for c, v in hh.get("clans", {}).items():
            print(f"  外戚 {c}：家主 {v.get('head', '?')}" + (f"，在朝属{v['faction']}" if v.get("faction") else "") + (f"；{v['note']}" if v.get("note") else ""))
        return
    if p:
        print(f"  主角 {p.get('name')}，{age(hh, p, w.turn)} 岁，眼下在 {p.get('where', '?')}；人格卡 {p.get('card', '无')}")
    if hh.get("heir"):
        print(f"  嗣子：{hh['heir']}")
    ms = w.members()
    for mid, m in ms.items():
        if args.id and args.id not in (mid, m.get("name")):
            continue
        if not args.all and not alive(m):
            continue
        for l in fmt_member(w, mid, m, verbose=bool(args.id)):
            print(l)
    if not args.id:
        for pg in hh.get("pregnancies", []):
            mm = ms.get(pg["mother"], {})
            print(f"  有孕：{mm.get('name', pg['mother'])}，第 {pg['since_turn']} 回合起，预计第 {pg['due_turn']} 回合临盆")
        for pl in hh.get("plans", []):
            if not pl.get("done"):
                print(f"  约定：{pl['what']}（第 {pl.get('due_turn', '?')} 回合）")
        b = hh.get("budget", {}).get("tier", "常")
        print(f"  家中用度：{b}（{BUDGET.get(b, {}).get('说明', '')}；平日用度已含在帅府开支里，不另扣）")
        vs = [v for v in hh.get("visits", []) if v.get("turn") == w.turn]
        cap, why = visit_cap(w, args)
        print(f"  本季家事：{len(vs)}/{cap}（{why}）" + ("：" + "；".join(f"{ms.get(v['with'], {}).get('name', v['with'])}·{v['what']}" for v in vs) if vs else ""))


def cmd_hint(w, args):
    if not w.is_main:
        die("hint 是给 kin agent 的亲疏提示，只用于主角家。宫中、大族的人用 court.py hint 和 secrets.py brief")
    m = w.m(args.id)
    card = load_card(w, m)
    if not card:
        die(f"{m['name']} 没有人格卡，不能派 kin agent。先照 characters/_template_kin.md 建卡")
    if card.role == "将领":
        print(f"{m['name']} 领兵，按将领规则：python3 scripts/loyalty.py show {m['card']}；"
              f"派 general agent，家事问话时也可派 kin agent，把 loyalty.py 的人心提示一并写进去。")
        return
    lv = kin_level(card)
    L.print_ledger(card)
    print("\n写进 kin agent prompt 的亲疏提示：")
    print("  " + kin_hint(card, lv, w, m))
    print("\n本级可观察的迹象（GM 经家里人透露给玩家）：")
    for s in KIN_SIGNS[lv]:
        print(f"  · {s}")


# ---------- season ----------

def parse_triggers(w, items):
    out = {}
    for t in items:
        if "=" not in t:
            die(f"--trigger 写成 id=事件：{t!r}")
        k, v = t.split("=", 1)
        if v not in KIN_TRIGGERS:
            die(f"家人的触发事件只有：{'、'.join(KIN_TRIGGERS)}")
        out.setdefault(w.mid(k), []).append(v)
    return out


def health_roll(rng, m, a, care):
    """返回 (新身体, 说明) 或 None。"""
    h = m.get("health", "健朗")
    i = HEALTH.index(h) if h in HEALTH else 0
    r = rng.random()
    if h == "病重":
        p = min(0.25 + max(a - 60, 0) * 0.01, 0.6) - (0.1 if care else 0)
        if a < 16:
            p = 0.2 - (0.1 if care else 0)
        if r < p:
            return "亡故", f"病重不起（本季凶险 {p:.0%}，掷 {r:.2f}）"
        if r > 0.85 - (0.1 if care else 0):
            return "多病", f"熬过来了，转为多病（掷 {r:.2f}）"
        return None
    if a >= 50:
        p = min((a - 45) * 0.01, 0.4) - (0.05 if care else 0)
        if r < p:
            return HEALTH[min(i + 1, 3)], f"年老体衰，身体差了一档（本季 {p:.0%}，掷 {r:.2f}）"
    elif a < 6:
        if r < 0.05:
            return HEALTH[min(i + 1, 3)], f"小儿病了一场（5%，掷 {r:.2f}）"
    elif r < 0.02:
        return HEALTH[min(i + 1, 3)], f"染病（2%，掷 {r:.2f}）"
    r2 = rng.random()
    if h == "小恙" and r2 < 0.6:
        return "健朗", f"病好了（掷 {r2:.2f}）"
    if h == "多病" and r2 < (0.25 if care else 0.1) and a < 60:
        return "小恙", f"调养见效（掷 {r2:.2f}）"
    return None


def due_milestones(w, mid, m, a):
    out = []
    if not alive(m) or m.get("status") != "在":
        return out
    rel = m.get("relation", "")
    done = m.get("milestones", {})
    deferred = m.get("deferred", {})
    for name, sex, lo, hi, choices in (PALACE_MILESTONES if w.kind == "palace" else MILESTONES):
        if name in done:
            continue
        if deferred.get(name, 0) > w.turn:
            continue
        if name == "议亲":
            if rel not in YOUNG_REL or m.get("spouse"):
                continue
            if sex and m.get("sex") != sex:
                continue
            if a < MARRY_AGE.get(m.get("sex"), 16):
                continue
        else:
            if rel not in YOUNG_REL:
                continue
            if sex and m.get("sex") != sex:
                continue
            if not (lo <= a <= hi):
                continue
        out.append((name, choices))
    return out


def cmd_season(w, args):
    if not w.is_main:
        return house_season(w, args)
    hh = w.hh
    turn = args.turn or w.turn
    w.turn = turn
    when = args.when or date_label(hh, turn)
    if hh.get("last_season_turn") == turn and not args.force:
        die(f"第 {turn} 回合的家宅已经推进过（last_season_turn）。确要重跑加 --force")
    rng = random.Random(args.seed if args.seed is not None else turn * 7919 + 13)
    triggers = parse_triggers(w, args.trigger)
    pending = hh.get("pending_triggers", {})
    for k, vs in pending.items():
        triggers.setdefault(k, [])
        triggers[k] += [v for v in vs if v not in triggers[k]]
    for pl in hh.get("plans", []):
        # 本人不愿的婚事，没办完之前每季都算“逼婚”；办完的那一季也算（rules/household.md 第五节）
        if pl.get("consent") == "不愿" and pl.get("who") in w.members() and (not pl.get("done") or pl.get("done_turn") == turn):
            lst = triggers.setdefault(pl["who"], [])
            if "逼婚" not in lst:
                lst.append("逼婚")
    care = {w.mid(x) for x in args.care}
    ms = w.members()
    y, s = year_of(hh, turn)
    print(f"=== 家宅季末：{when}（第 {turn} 回合，{y if y > 0 else f'前{-y}'} 年{s}）" + ("，战事季" if war_season(w, args) else "") + " ===")
    cards_to_save = []
    notes_gm, notes_player = [], []

    # 1. 年纪
    if s == "春" or turn == 1:
        print("\n--- " + ("开局的年纪" if turn == 1 else "新年，各长一岁") + " ---")
        for mid, m in ms.items():
            if alive(m):
                print(f"  {m['name']} {age(hh, m, turn)} 岁")

    # 2. 冷落、淡化、亲疏阶梯
    print("\n--- 陪伴与冷落、亲疏 ---")
    for mid, m in ms.items():
        if not alive(m):
            continue
        a = age(hh, m, turn)
        seen = turn - int(m.get("last_seen_turn", turn))
        lim = int(m.get("neglect_limit", default_limit(m)))
        card = load_card(w, m)
        if not card or card.role not in ("家人", "将领"):
            if a >= 3 and seen >= lim:
                print(f"  {m['name']}：已经 {seen} 季没见过了（没有人格卡，不记心结；写进家事小景）")
            continue
        faded = kin_fade(card, still_neglected=(seen >= lim and a >= 6)) if card.role == "家人" else []
        # 冷落
        g = neglect_grudge(card)
        if seen >= lim and a >= 6:
            if g is None:
                g = L.add_grudge(card, when, f"已经{cn_num(seen)}季没来看过{('她' if m.get('sex') == '女' else '他')}",
                                 1, heard="家中可闻")
                g["extra"].append("冷落")
                print(f"  {m['name']}：{seen} 季没见 → 记心结 [{g['id']}]“{g['what']}”强度 1（家中可闻）")
            elif seen >= 2 * lim and g["s"] < 2 and g["age"] >= lim:
                g["s"], g["age"] = 2, 0
                print(f"  {m['name']}：{seen} 季没见，冷落加深 → 心结 [{g['id']}] 强度 2")
            else:
                print(f"  {m['name']}：{seen} 季没见，冷落的心结 [{g['id']}] 仍在（强度 {g['s']}）")
        elif seen >= lim - 1 and seen >= 1 and a >= 6:
            print(f"  {m['name']}：已经 {seen} 季没见，再一季不见就记心结")
        for f in faded:
            print(f"  {m['name']}：时间淡化 {f}")
        if card.role == "将领":
            print(f"  {m['name']} 领兵：离心按 loyalty.py season 推进（冷落的心结已记在同一本账上）")
            cards_to_save.append(card)
            continue
        cur = KIN_LEVELS.index(kin_level(card))
        trig = triggers.get(mid, [])
        t, why = kin_target(card, trig)
        new = L.step(cur, t)
        if new != cur or args.verbose or t != cur:
            move = "不变" if new == cur else ("近一级" if new < cur else "远一级")
            print(f"  {m['name']}：{'；'.join(why)}；账面“{KIN_LEVELS[t]}”，上季“{KIN_LEVELS[cur]}” → 本季【{KIN_LEVELS[new]}】{move}")
        else:
            print(f"  {m['name']}：{KIN_LEVELS[cur]}（不变）")
        card.log.append(f"{when}：{KIN_LEVELS[cur]} → {KIN_LEVELS[new]}｜心结 {L.pressure(card)}｜缺口 {L.gap(card):.1f}"
                        + (f"｜牵扯 {len(card.ties)}" if card.ties else "") + (f"｜触发 {'、'.join(trig)}" if trig else ""))
        card.set_yaml("亲疏", KIN_LEVELS[new])
        m["closeness"] = KIN_LEVELS[new]
        cards_to_save.append(card)
        if new >= 1:
            sign = rng.choice(KIN_SIGNS[KIN_LEVELS[new]])
            notes_player.append(f"{m['name']}（{KIN_LEVELS[new]}）：{sign}")
        heard = [x for x in card.active() if x["heard"] != "不外传"]
        for x in heard:
            notes_gm.append(f"{m['name']} 心结 [{x['id']}] {x['what']}（{x['heard']}）")

    # 3. 怀孕与临盆
    print("\n--- 添丁 ---")
    n_lines = 0
    preg = hh.setdefault("pregnancies", [])
    for pg in list(preg):
        mm = ms.get(pg["mother"])
        if not mm:
            continue
        if turn >= pg["due_turn"]:
            r = rng.random()
            sex = "男" if rng.random() < 0.5 else "女"
            if r < 0.85:
                how = "平安"
            elif r < 0.97:
                how = "难产，母子保住了，产妇身体差一档"
            else:
                how = "凶险：GM 写成家事交给玩家（请名医、祈福；保大还是保小）"
            n_lines += 1
            print(f"  {mm['name']} 临盆：生{sex}，{how}（掷 {r:.2f}）。记出生：household.py birth {pg['mother']} --id … --name … --sex {sex}")
        else:
            n_lines += 1
            print(f"  {mm['name']} 有孕，第 {pg['due_turn']} 回合临盆（还有 {pg['due_turn'] - turn} 季）")
    for mid, m in ms.items():
        if m.get("sex") != "女" or m.get("status") != "在" or not alive(m):
            continue
        if any(pg["mother"] == mid for pg in preg):
            continue
        a = age(hh, m, turn)
        if not (16 <= a <= 40):
            continue
        husband_here = False
        if m.get("relation") in SPOUSE_REL:
            husband_here = at_side(w, m)
        elif m.get("spouse"):
            hsb = next((x for x in ms.values() if x.get("name") == m["spouse"]), None)
            husband_here = bool(hsb and hsb.get("status") == "在" and region_of(hsb.get("residence")) == region_of(m.get("residence")))
        if not husband_here:
            continue
        last_child = max([int(x.get("born_turn", -99)) for x in ms.values() if x.get("mother") == mid] + [-99])
        if turn - last_child < 4:
            continue
        p = 0.12 + (0.12 if any(v.get("with") == mid and v.get("turn") == turn and v.get("kind") == "陪伴"
                                for v in hh.get("visits", [])) else 0)
        r = rng.random()
        if r < p:
            n_lines += 1
            print(f"  {m['name']} 有喜了（本季 {p:.0%}，掷 {r:.2f}）。确认后：household.py pregnant {mid}")
    if not n_lines:
        print("  （无）")
    # 4. 身体
    print("\n--- 身体 ---")
    any_h = False
    for mid, m in ms.items():
        if not alive(m):
            continue
        a = age(hh, m, turn)
        res = health_roll(rng, m, a, mid in care)
        if res:
            any_h = True
            new, why = res
            print(f"  {m['name']}（{a} 岁）：{m.get('health', '健朗')} → {new}，{why}")
            if new == "亡故":
                print(f"    确认后：household.py set {mid} status=亡 health=亡故；丧事用度见 rules/household.md 第六节")
            else:
                m["health"] = new
            if new in ("多病", "病重"):
                print("    可选：请名医（下季 --care，用度 +300 钱）、接到身边、祈福；病重的，家里人会来问后事")
        elif m.get("health", "健朗") != "健朗":
            any_h = True
            print(f"  {m['name']}（{a} 岁）：仍是{m['health']}")
    if not any_h:
        print("  家里人身体都好")

    # 5. 人生节点
    print("\n--- 到点的人生节点（GM 写成家事，交给玩家定） ---")
    any_m = False
    for mid, m in ms.items():
        a = age(hh, m, turn)
        for name, choices in due_milestones(w, mid, m, a):
            any_m = True
            first = m.setdefault("prompted", {}).setdefault(name, turn)
            if first < turn:
                print(f"  {m['name']}（{m.get('relation')}，{a} 岁）：{name}，第 {first} 回合起仍待定"
                      f"（走向见那一季的提示；定了用 milestone {mid} {name} --choice …，缓议用 --defer）")
                continue
            print(f"  {m['name']}（{m.get('relation')}，{a} 岁）：{name}")
            for c in choices:
                print(f"      · {c}")
            print(f"      定了以后：household.py milestone {mid} {name} --choice …")
    sons = [(mid, m) for mid, m in ms.items() if m.get("relation") == "子" and alive(m)]
    if len(sons) >= 2 and not hh.get("heir") and max(age(hh, m, turn) for _, m in sons) >= 12:
        any_m = True
        print(f"  立嗣：{'、'.join(m['name'] + '（' + m.get('line', '嫡') + '，' + str(age(hh, m, turn)) + '岁）' for _, m in sons)}"
              f"——长子已过十二，家里和军中开始有人问。见 rules/household.md 第五节“继承”")
    for pl in hh.get("plans", []):
        if not pl.get("done") and pl.get("due_turn") and pl["due_turn"] <= turn:
            any_m = True
            print(f"  到期的约定：{pl['what']}（第 {pl['due_turn']} 回合）。办完 set … spouse=… status=…，"
                  f"用度按 rules/household.md 第六节走 economy.py --extra-cost")
    if not any_m:
        print("  （无）")

    # 6. 本季家事
    vs = [v for v in hh.get("visits", []) if v.get("turn") == turn]
    cap, why = visit_cap(w, args)
    print(f"\n--- 本季家事 {len(vs)}/{cap}（{why}） ---")
    for v in vs:
        print(f"  {ms.get(v['with'], {}).get('name', v['with'])}：{v['what']}（{v['kind']}{'，用心' if v.get('earnest') else ''}）")
    if notes_player:
        print("\n可以经家里人透露给玩家的迹象（择一两条）：")
        for n in notes_player:
            print(f"  · {n}")
    if notes_gm:
        print("玩家可能从家里人口中听说的心结：")
        for n in notes_gm:
            print(f"  · {n}")

    hh["last_season_turn"] = turn
    hh["pending_triggers"] = {}
    if args.apply:
        for c in cards_to_save:
            c.save()
        w.save()
        print(f"\n已写入 {w.p(w.fname)} 和 {len(cards_to_save)} 张人格卡。怀孕、出生、节点、亡故要另用对应命令确认。")
    else:
        print("\n（未写入。确认后同一 seed 加 --apply。怀孕、出生、节点、亡故要另用对应命令确认。）")


# ---------- visit ----------

def cmd_visit(w, args):
    if not w.is_main:
        die("visit 记的是主角的家事，只用于主角家。主角去宫中、别家拜访，记识人（persona.py know）和关系（relations.py）")
    hh = w.hh
    mid = w.mid(args.id)
    m = w.members()[mid]
    if not alive(m):
        die(f"{m['name']} 已不在（{m.get('status')}）")
    vs = [v for v in hh.setdefault("visits", []) if v.get("turn") == w.turn]
    cap, why = visit_cap(w, args)
    if len(vs) >= cap and not args.force:
        die(f"本季家事已满 {len(vs)}/{cap}（{why}）：" + "；".join(v["what"] for v in vs)
            + "。家事不占帅府亲裁限额，但每季有上限（rules/household.md 第三节）")
    side = at_side(w, m)
    kind = "家书" if args.letter else "陪伴"
    if kind == "陪伴" and not side:
        die(f"{m['name']} 不在主角身边（{m.get('residence')}，主角在 {hh.get('protagonist', {}).get('where')}）：只能写家书（--letter）")
    if kind == "家书" and side:
        print("注：人就在身边，写信也算一件，但不如当面。")
    card = load_card(w, m)
    old = m.get("last_seen_turn")
    m["last_seen_turn"] = w.turn
    rec = {"turn": w.turn, "with": mid, "what": args.what, "kind": kind, "earnest": bool(args.earnest)}
    hh["visits"].append(rec)
    hh["visits"] = hh["visits"][-80:]
    print(f"{date_label(hh, w.turn)}：{kind}·{m['name']}——{args.what}（本季第 {len(vs) + 1}/{cap} 件）")
    print(f"  冷落计时归零（上次见面：第 {old} 回合）")
    if card:
        g = neglect_grudge(card)
        if args.earnest and kind == "陪伴" and g:
            if any(v.get("with") == mid and v.get("earnest") for v in vs):
                print("  本季已经用心陪过他（她）一次，同一季只算一次")
            else:
                before = g["s"]
                g["s"] -= 1
                if g["s"] <= 0:
                    g["s"] = 0
                    g["status"] = f"已解（{date_label(hh, w.turn)}，{args.what}）"
                print(f"  用心陪伴：冷落的心结 [{g['id']}] 强度 {before} → {g['s']}｜{g['status']}")
        elif args.earnest and kind == "家书" and g:
            print("  家书只能让冷落不再加深，消不了心结；要当面陪")
        elif g:
            print(f"  冷落的心结 [{g['id']}] 不再加深；要消解，得用心陪（--earnest：做的事对上他的需求）")
        if args.earnest and kind == "陪伴":
            print("  若这件事正对上他的某项需求（例：教儿子射箭 对“被父亲看见”），GM 可另用 loyalty.py need 上调一档，写明依据")
    if args.apply:
        if card:
            card.save()
        w.save()
        print(f"已写入 {w.p(w.fname)}" + (f" 和 {m['card']}" if card else "") + "。")
    else:
        print("（未写入。确认后加 --apply。）")


# ---------- milestone / pregnant / birth ----------

def cmd_milestone(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    names = [x[0] for x in MILESTONES + PALACE_MILESTONES] + ["成婚", "立嗣", "立储", "其他"]
    if args.name not in names:
        die(f"节点只有：{'、'.join(names)}")
    when = date_label(w.hh, w.turn)
    if args.defer:
        m.setdefault("deferred", {})[args.name] = w.turn + args.defer
        print(f"{m['name']} 的{args.name}缓到第 {w.turn + args.defer} 回合再提")
    else:
        if not args.choice:
            die("给 --choice（定下的走向），或 --defer 季数")
        m.setdefault("milestones", {})[args.name] = f"{when}（第 {w.turn} 回合）：{args.choice}"
        m.get("deferred", {}).pop(args.name, None)
        print(f"{m['name']}·{args.name}：{args.choice}")
        print("  牵连主线的部分（将领情分、母族体面、需求满足度）按 rules/household.md 第五节另行记账")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_pregnant(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    preg = w.hh.setdefault("pregnancies", [])
    if any(p["mother"] == mid for p in preg):
        die(f"{m['name']} 已经有孕")
    rec = {"mother": mid, "since_turn": w.turn, "due_turn": w.turn + 3}
    preg.append(rec)
    m["busy"] = "有孕在身"
    print(f"{m['name']} 有孕，预计第 {rec['due_turn']} 回合（{date_label(w.hh, rec['due_turn'])}）临盆")
    w.hh.setdefault("events", []).append({"turn": w.turn, "kind": "喜", "what": f"{m['name']}有孕"})
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_birth(w, args):
    hh = w.hh
    mom_id = w.mid(args.mother)
    mom = w.members()[mom_id]
    if args.id in w.members():
        die(f"id {args.id} 已有人用")
    rel_mom = mom.get("relation")
    pname = w.father_name()
    if rel_mom in SPOUSE_REL:
        if w.kind == "palace":
            relation = "皇子" if args.sex == "男" else "公主"
        else:
            relation = "子" if args.sex == "男" else "女"
        line = "嫡" if rel_mom in MAIN_WIFE else "庶"
        father = pname
    else:
        relation = "侄" if args.sex == "男" else "侄女"
        line = ""
        father = mom.get("spouse")
    y, _ = year_of(hh, w.turn)
    new = {"name": args.name, "relation": relation, "sex": args.sex, "born": y, "born_turn": w.turn,
           "residence": mom.get("residence"), "health": "健朗", "closeness": "亲近", "busy": "襁褓之中",
           "card": args.card, "status": "在", "spouse": None, "mother": mom_id, "father": father, "line": line,
           "last_seen_turn": w.turn, "milestones": {}, "trait": args.trait or ""}
    w.members()[args.id] = new
    hh["pregnancies"] = [p for p in hh.get("pregnancies", []) if p["mother"] != mom_id]
    mom["busy"] = "坐月子"
    if args.hard:
        i = HEALTH.index(mom.get("health", "健朗")) if mom.get("health", "健朗") in HEALTH else 0
        mom["health"] = HEALTH[min(i + 1, 3)]
    hh.setdefault("events", []).append({"turn": w.turn, "kind": "喜", "what": f"{mom['name']}生{relation}{args.name}"})
    print(f"{date_label(hh, w.turn)}：{mom['name']}生{relation}，名{args.name}（{line or '—'}）")
    if relation in CHILD_REL:
        n = sum(1 for x in w.members().values() if x.get("relation") in SON_REL and alive(x))
        if relation in SON_REL and line == "庶" and any(x.get("relation") in SON_REL and x.get("line") == "嫡" for x in w.members().values()):
            print("  庶子出世：正妻那边可能有心思；见 rules/household.md 第五节“继承”")
        if relation in SON_REL and n >= 2 and not hh.get("heir"):
            print("  家里有了两个儿子，立嗣的事迟早要提" if w.is_main else "  又添了一位皇子（或子嗣），储位之争多了一个人")
        if w.kind == "palace" and "favor" in mom:
            mom["favor"] = min(3, int(mom.get("favor", 1)) + 1)
            print(f"  {mom['name']} 生育有功，宠爱 +1 → {favor_word(mom['favor'])}")
    print("  满六岁（启蒙）前不建人格卡")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


# ---------- match / hostage ----------

MATCH_KINDS = {"联姻": "与邻镇、部落、朝中结亲", "结亲": "许给部将或部将之子", "本地": "本地大族", "自择": "本人自己相看"}


def find_need(card, keys):
    return next((n for n in card.needs if any(k in n["name"] for k in keys)), None)


def cmd_match(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    hh = w.hh
    when = date_label(hh, w.turn)
    if args.kind not in MATCH_KINDS:
        die(f"--kind 只有：{'、'.join(MATCH_KINDS)}")
    if args.consent not in ("愿意", "勉强", "不愿"):
        die("--consent 写 愿意 / 勉强 / 不愿（先召 kin agent 问本人）")
    card = load_card(w, m)
    pron = "她" if m.get("sex") == "女" else "他"
    who = "兄长" if m.get("relation") in ("弟", "妹") else "父亲" if m.get("relation") in CHILD_REL else "家里"
    print(f"=== 议亲：{m['name']} 许{args.to}（{args.kind}：{MATCH_KINDS[args.kind]}），本人{args.consent} ===")
    due = args.due or w.turn + 2
    hh.setdefault("plans", []).append({"what": f"{m['name']}与{args.to}成婚", "who": mid, "to": args.to, "kind": args.kind,
                                       "faction": args.faction, "consent": args.consent, "made_turn": w.turn,
                                       "due_turn": due, "done": False})
    m.setdefault("milestones", {})["议亲"] = f"{when}（第 {w.turn} 回合）：许{args.to}，本人{args.consent}"
    m["busy"] = f"待嫁（许{args.to}，第 {due} 回合成婚）" if m.get("sex") == "女" else f"待娶（{args.to}，第 {due} 回合成婚）"
    if card and card.role in ("家人", "将领"):
        marry = find_need(card, ("嫁", "婚", "亲事", "娶"))
        pawn = find_need(card, ("筹码", "自己做主", "自主"))
        if args.consent == "愿意":
            print(f"  本人愿意：不记心结。")
            if marry:
                fit = args.fit if args.fit is not None else 2
                print(f"  需求“{marry['name']}”满足 {marry['m']} → {fit}（这门亲合不合{pron}的心意，GM 依 kin agent 的回答定 --fit）")
                marry["m"], marry["why"] = fit, f"{when}许{args.to}，本人愿意"
            if pawn:
                print(f"  需求“{pawn['name']}”满足 {pawn['m']} → {max(pawn['m'], 2)}（问过{pron}，{pron}点了头）")
                pawn["m"], pawn["why"] = max(pawn["m"], 2), f"{when}议亲时问过本人"
        elif args.consent == "勉强":
            g = L.add_grudge(card, when, f"{who}把{pron}许给{args.to}，{pron}点了头，心里不情愿", 1, heard="家中可闻")
            g["extra"].append("婚事")
            print(f"  本人勉强：记心结 [{g['id']}]“{g['what']}”强度 1（家中可闻）")
            if marry:
                fit = args.fit if args.fit is not None else 1
                marry["m"], marry["why"] = fit, f"{when}许{args.to}，本人勉强"
                print(f"  需求“{marry['name']}”满足 → {fit}")
        else:
            g = L.add_grudge(card, when, f"不顾{pron}不愿，{who}把{pron}许给{args.to}", 3, heard="家中可闻")
            g["extra"].append("婚事")
            print(f"  本人不愿：记心结 [{g['id']}]“{g['what']}”强度 3（家中可闻）；到成婚那一季为止，每季末都带触发事件“逼婚”")
            if marry:
                marry["m"], marry["why"] = 0, f"{when}被许给{args.to}，本人不愿"
                print(f"  需求“{marry['name']}”满足 → 0")
            if pawn:
                pawn["m"], pawn["why"] = 0, f"{when}被当作筹码许给{args.to}"
                print(f"  需求“{pawn['name']}”满足 → 0")
        mem = f"- {when}：{who}把{pron}许给{args.to}（{args.kind}）。{pron}{'答应了' if args.consent == '愿意' else '勉强点了头' if args.consent == '勉强' else '不愿意'}。"
        append_memory(card, mem)
        cards = [card]
    else:
        cards = []
        print("  （没有人格卡：只记进家宅）")
    # 牵连主线
    print("\n  牵连主线（rules/household.md 第五节）：")
    if args.kind == "联姻":
        print(f"  · {args.faction or '对方势力'}：成婚那一季，GM 把态度上调一档；结盟能不能稳，看{m['name']}嫁过去以后的亲疏："
              "亲近——会替娘家说话；疏淡——不帮也不害；怨怼——娘家的事不管；另有打算——可能替夫家打娘家的主意。")
    elif args.kind == "结亲":
        print(f"  · 对方是部将家：那位将领“被信任/被重用”一类需求 +1，或抵消一条对得上的心结（loyalty.py need / ease --by 抵消）。")
    elif args.kind == "本地":
        print("  · 本地大族：可有一次捐输，走 economy.py --extra-income，不超过帅府一季钱收入的一成。")
    else:
        print("  · 自择：政治上没有所得；本人婚事一类需求另 +1。")
    print(f"  · 婚期第 {due} 回合。用度按第六节走 economy.py --extra-cost。")
    if args.apply:
        for c in cards:
            c.save()
        w.save()
        print(f"\n已写入 {w.p(w.fname)}" + (f" 和 {m['card']}" if cards else "") + "。")
    else:
        print("\n（未写入。确认后加 --apply。）")


def append_memory(card, line):
    t = card.text
    if "## 记忆" in t:
        t = t.rstrip("\n") + "\n" + line + "\n"
    else:
        t = t.rstrip("\n") + "\n\n## 记忆\n\n" + line + "\n"
    card.text = t


def cmd_hostage(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    hh = w.hh
    when = date_label(hh, w.turn)
    if args.consent not in ("愿意", "勉强", "不愿"):
        die("--consent 写 愿意 / 勉强 / 不愿（先召 kin agent 问本人）")
    pron = "她" if m.get("sex") == "女" else "他"
    s = {"愿意": 1, "勉强": 2, "不愿": 3}[args.consent]
    print(f"=== 为质：{m['name']} 去{args.to}，本人{args.consent} ===")
    cards = []
    card = load_card(w, m)
    if card:
        g = L.add_grudge(card, when, f"被送去{args.to}为质" + ("（自己答应的）" if args.consent == "愿意" else ""),
                         s, heard="家中可闻")
        g["extra"].append("为质")
        print(f"  {m['name']}：记心结 [{g['id']}] 强度 {s}" + ("，下次季末带触发事件“送质”" if s == 3 else ""))
        if s == 3:
            hh.setdefault("pending_triggers", {}).setdefault(mid, []).append("送质")
        append_memory(card, f"- {when}：被送去{args.to}为质，{pron}{'自己答应了' if s == 1 else '勉强去了' if s == 2 else '不肯，还是被送走了'}。")
        cards.append(card)
    # 牵连母亲、妻子
    ms = w.members()
    kin_ids = set()
    if m.get("mother") in ms:
        kin_ids.add(m["mother"])
    if m.get("relation") in ("弟", "妹", "兄", "姊"):
        kin_ids |= {k for k, v in ms.items() if v.get("relation") == "母" and alive(v)}
    if m.get("spouse"):
        kin_ids |= {k for k, v in ms.items() if v.get("name") == m["spouse"]}
    for k in kin_ids:
        km = ms[k]
        kc = load_card(w, km)
        if kc and kc.role == "家人":
            g = L.add_grudge(kc, when, f"把{m['name']}送去{args.to}为质", 2 if s >= 2 else 1, heard="家中可闻")
            g["extra"].append("为质")
            print(f"  {km['name']}：记心结 [{g['id']}] 强度 {g['s']}")
            cards.append(kc)
    m["status"] = "为质"
    m["residence"] = args.to
    m["busy"] = f"在{args.to}为质"
    hh.setdefault("events", []).append({"turn": w.turn, "kind": "其他", "what": f"{m['name']}赴{args.to}为质"})
    print(f"\n  牵连主线：{args.to}手里有了{S.own_faction(w.dir)}的人。对方的态度可上调一档；但{m['name']}在那边的亲疏会变成筹码："
          "亲疏到“另有打算”的，可能替对方说话、递消息（rules/household.md 第五节）。")
    if args.apply:
        for c in cards:
            c.save()
        w.save()
        print(f"\n已写入 {w.p(w.fname)} 和 {len(cards)} 张人格卡。")
    else:
        print("\n（未写入。确认后加 --apply。）")


# ---------- tie / plot / heir ----------

def cmd_tie(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    card = load_card(w, m)
    if not card or not (card.role == "家人" or card.role in L.COURT_ROLES):
        die(f"{m['name']} 没有家人卡或朝臣卡（或已改为将领卡；将领的收买用 loyalty.py offer）")
    when = date_label(w.hh, w.turn)
    if args.withdraw is not None:
        if not 1 <= args.withdraw <= len(card.ties):
            die(f"{m['name']} 的牵扯只有 {len(card.ties)} 条")
        gone = card.ties.pop(args.withdraw - 1)
        print(f"{m['name']}：牵扯撤去——{gone}")
    else:
        if not (args.from_ and args.aim):
            die("给 --from 谁、--aim 所图（拉拢、离间、要消息、劝归母族……）")
        line = f"来自 {args.from_}｜所图 {args.aim}｜许以 {args.promise or '未明说'}｜时间 {when}"
        card.ties.append(line)
        print(f"{m['name']}：记下牵扯——{line}")
        if card.role in L.COURT_ROLES:
            print("  牵扯本身不改心迹；心结够深（未解 ≥3）时，它让“异志”成为可能（rules/court.md 第七节）")
        else:
            print("  牵扯本身不改亲疏；心结够深（未解 ≥3）时，它让“另有打算”成为可能（rules/household.md 第二节）")
    if args.apply:
        card.save()
        print(f"已写入 {m['card']}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_plot(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    hh = w.hh
    when = date_label(hh, w.turn)
    rng = random.Random(args.seed)
    print(f"=== 图谋：{args.by} 对 {m['name']}（{args.kind}） ===")
    if args.kind in ("收买", "离间"):
        print(f"  不掷骰子。记成牵扯：household.py tie {mid} --from {args.by} --aim {args.kind} --promise …")
        print("  起不起作用看账本：心结浅的，来人被打发走，多半还会告诉主角；心结深的，才有“另有打算”。")
        return
    here = region_of(m.get("residence"))
    seat = w.kingdom.get("player", {}).get("seat") if w.is_main else region_of((w.head() or {}).get("residence"))
    st = m.get("status", "在")
    if st in ("出嫁", "为质") or args.road:
        base, where = 0.35, "在路上或在别家"
    elif here == seat:
        base, where = 0.10, "在帅府"
    else:
        base, where = 0.20, f"在{here}"
    if args.kind == "行刺":
        base /= 2
    p = max(base - 0.05 * args.guard, 0.02)
    r = rng.random()
    print(f"  {where}，看护 {args.guard} 档 → 得手 {p:.0%}；掷 {r:.2f}")
    if r < p:
        out = "得手"
        if args.kind == "绑架":
            m["status"], m["residence"], m["busy"] = "被掳", f"{args.by}手里", f"被{args.by}掳去"
            print(f"  【得手】{m['name']}被掳。领兵的家人、将领的“家眷”若牵涉其中，按 loyalty.py 第三节记；"
                  "对方会拿人谈条件，GM 用 ruler agent 开价")
        else:
            m["health"] = "病重"
            print(f"  【得手】{m['name']}重伤（身体记为病重，季末按病重掷生死）")
    else:
        r2 = rng.random()
        out = "败露" if r2 < 0.4 else "未遂"
        print(f"  【{out}】" + ("刺客、贼人被拿住，可审出主使（情报）" if out == "败露" else "没得手，对方的人走脱了；家里受了惊"))
    hh.setdefault("events", []).append({"turn": w.turn, "kind": "其他", "what": f"{args.by}{args.kind}{m['name']}：{out}"})
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后同一 seed 加 --apply。）")


def cmd_heir(w, args):
    hh = w.hh
    mid = w.mid(args.id)
    m = w.members()[mid]
    when = date_label(hh, w.turn)
    old = hh.get("heir")
    print(f"=== 立嗣：{m['name']}（{m.get('line', '')}）｜{args.why} ===")
    cards = []
    for k, x in w.members().items():
        if k == mid or not alive(x):
            continue
        if x.get("relation") in SON_REL:
            c = load_card(w, x)
            s = 3 if old == x["name"] else 2 if (x.get("line") == "嫡" and m.get("line") != "嫡") or \
                (age(hh, x, w.turn) > age(hh, m, w.turn) and x.get("line") == m.get("line")) else 0
            if c and s:
                g = L.add_grudge(c, when, f"嗣位给了{m['name']}", s, heard="家中可闻")
                g["extra"].append("继承")
                print(f"  {x['name']}：心结 [{g['id']}] 强度 {s}" + ("，下次季末带触发“废立”" if s == 3 else ""))
                if s == 3 and c.role == "家人":
                    hh.setdefault("pending_triggers", {}).setdefault(k, []).append("废立")
                elif c.role in L.COURT_ROLES:
                    print(f"    储位：他卡上“储位”一类需求降到 0（loyalty.py need）；季末 court.py season --trigger {x['name']}=储位被夺"
                          if s == 3 else f"    储位：他卡上“储位”一类需求降到 0（loyalty.py need）")
                cards.append(c)
            elif s:
                print(f"  {x['name']}：还没有人格卡；长大后建卡时写进记忆和心结（强度 {s}）")
        if x.get("relation") in SPOUSE_REL:
            own = [y for y in w.members().values() if y.get("mother") == k and y.get("relation") in SON_REL and alive(y)]
            if own and m.get("mother") != k:
                c = load_card(w, x)
                if c and (c.role == "家人" or c.role in L.COURT_ROLES):
                    g = L.add_grudge(c, when, f"嗣位没给自己的儿子，给了{m['name']}", 2, heard="家中可闻")
                    g["extra"].append("继承")
                    print(f"  {x['name']}：心结 [{g['id']}] 强度 2")
                    cards.append(c)
    if not w.is_main:
        for k, x in w.members().items():
            if k == mid or not alive(x) or x.get("relation") not in SON_REL:
                continue
            c = load_card(w, x)
            nd = c and next((n for n in c.needs if "储" in n["name"] or "嗣" in n["name"]), None)
            if nd and nd["m"] > 0:
                print(f"  {x['name']}：卡上“{nd['name']}”满足 {nd['m']} → 0（GM 照此跑 loyalty.py need {x['card']} {nd['name']} 0 "
                      f"--why \"立了{m['name']}\" --apply）")
    hh["heir"] = m["name"]
    hh.setdefault("events", []).append({"turn": w.turn, "kind": "其他", "what": f"立{m['name']}为嗣（{args.why}）"})
    if w.kind == "palace":
        print("  朝中：立储的议题改为已决（court.py issue 立储 --status \"已决：…\"）；拥立落选皇子的那一派，"
              "照 court.py feud 记一笔积怨，首领的怨照 relations.py 记（rules/household.md 第九节）")
    else:
        print("  将领站队：GM 依各将领与诸子的情分（启蒙、习武、冠礼时结下的）决定谁说话，必要时记牵扯或心结")
    if args.apply:
        for c in cards:
            c.save()
        w.save()
        print(f"已写入 {w.p(w.fname)} 和 {len(cards)} 张人格卡。")
    else:
        print("（未写入。确认后加 --apply。）")


# ---------- add / set / where / event ----------

def cmd_add(w, args):
    if args.id in w.members():
        die(f"id {args.id} 已有人用")
    m = {"name": args.name, "relation": args.relation, "sex": args.sex, "born": args.born,
         "residence": args.residence, "health": args.health, "closeness": "亲近", "busy": args.busy or "",
         "card": args.card, "status": "在", "spouse": args.spouse, "mother": args.mother, "father": args.father,
         "line": args.line or "", "last_seen_turn": w.turn, "milestones": {}, "trait": args.trait or ""}
    if args.neglect_limit:
        m["neglect_limit"] = args.neglect_limit
    for d in args.done or []:
        m["milestones"][d] = "开局前已过"
    w.members()[args.id] = m
    print(json.dumps({args.id: m}, ensure_ascii=False, indent=2))
    print(f"{age(w.hh, m, w.turn)} 岁")
    if args.card and not w.card_path(args.card):
        print(f"注意：人格卡 {args.card} 还不存在，照 characters/_template_kin.md 建")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


FIELDS = {"busy", "residence", "health", "status", "spouse", "closeness", "neglect_limit", "trait", "card", "name",
          "line", "relation", "mother", "father", "last_seen_turn"}


def cmd_set(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    for kv in args.pairs:
        if "=" not in kv:
            die(f"写成 字段=值：{kv!r}")
        k, v = kv.split("=", 1)
        if k not in FIELDS:
            die(f"能改的字段：{'、'.join(sorted(FIELDS))}")
        if k in ("neglect_limit", "last_seen_turn"):
            v = int(v)
        if k == "health" and v not in HEALTH + ["亡故"]:
            die(f"身体写 {'/'.join(HEALTH)} 或 亡故")
        if k == "status" and v not in STATUS_ALIVE + ("亡",):
            die(f"状态写 {'/'.join(STATUS_ALIVE)} 或 亡")
        print(f"{m['name']}.{k}：{m.get(k)!r} → {v!r}")
        m[k] = v
        if k == "status" and v == "亡":
            w.hh.setdefault("events", []).append({"turn": w.turn, "kind": "丧", "what": f"{m['name']}亡故"})
            if w.hh.get("heir") == m["name"]:
                print("  嗣子亡故，立嗣的事重新提起")
            print("  丧事用度见 rules/household.md 第六节；生平记进 world/history.json，人格卡移到 archive/")
        if k == "spouse" and v:
            for pl in w.hh.get("plans", []):
                if pl.get("who") == mid and not pl.get("done"):
                    pl["done"] = True
                    pl["done_turn"] = w.turn
                    w.hh.setdefault("events", []).append({"turn": w.turn, "kind": "喜", "what": pl["what"]})
                    print(f"  约定办完：{pl['what']}")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_where(w, args):
    if not w.is_main:
        die("where 是主角眼下所在，只用于主角家")
    p = w.hh.setdefault("protagonist", {})
    print(f"主角所在：{p.get('where')} → {args.place}")
    p["where"] = args.place
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_event(w, args):
    rec = {"turn": w.turn, "kind": args.kind, "what": args.what}
    w.hh.setdefault("events", []).append(rec)
    print(f"{date_label(w.hh, w.turn)}：〔{args.kind}〕{args.what}")
    if args.kind in ("喜", "丧") and args.tier:
        b = BUDGET[args.tier]
        print(f"  用度（{args.tier}）：钱 {b['money']}、粮 {b['grain']}——"
              f"python3 scripts/economy.py --season … --extra-cost {b['money']} --extra-grain-cost {b['grain']}。{b['说明']}")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


# ---------- 宫中与大族（rules/household.md 第九节） ----------

FAVOR_WORDS = ["失宠", "平常", "得宠", "专宠"]
ILL_STAGES = ["隐疾", "时发", "沉疴", "弥留"]
# 病到第几档时，外头看得见什么、传到哪些圈子
ILL_SIGNS = {
    0: ("没有外象；只有御医和贴身的人知道", []),
    1: ("隔些日子罢朝一两日，说是偶感风寒；医官进出勤了", ["宫中"]),
    2: ("久不视朝，奏章由近臣代批；宫中有人私下议论后事", ["宫中", "朝堂"]),
    3: ("宫门戒严，夜里召重臣入宫；各处的人都在打听宫里的消息", ["宫中", "朝堂", "市井"]),
}


def favor_word(v):
    return FAVOR_WORDS[max(0, min(3, int(v)))]


def ill_stage_health(stage, n):
    """病程档位对应 household 的 health 一栏。"""
    if stage <= 0:
        return None
    return "多病" if stage == 1 else "病重"


def illness_roll(rng, m, a, care, strain):
    """病程推进。返回 (新档位或“亡故”, 说明, 要不要 GM 确认)；没变返回 None。"""
    il = m["illness"]
    stages = il.get("stages") or ILL_STAGES
    st = int(il.get("stage", 0))
    last = len(stages) - 1
    major = int(il.get("major_from", 2))
    pace = float(il.get("pace", 0.12))
    r = rng.random()
    if st >= last:
        p = 0.35 - (0.1 if care else 0) + (0.1 if strain else 0)
        if r < p:
            return "亡故", f"{stages[st]}之中不起（本季凶险 {p:.0%}，掷 {r:.2f}）", True
        return None
    pw = pace + max(0, a - 55) * 0.01 + (0.15 if strain else 0) - (0.06 if care else 0)
    pb = (0.08 + (0.1 if care else 0)) if 0 < st < last else 0
    if r < pw:
        new = st + 1
        return new, f"病势加重：{stages[st]} → {stages[new]}（本季 {pw:.0%}，掷 {r:.2f}）", new >= major
    if r > 1 - pb:
        new = st - 1
        return new, f"调养见效：{stages[st]} → {stages[new]}（本季 {pb:.0%}，掷 {r:.2f}）", False
    return None


def succession(w):
    """储位形势：每位皇子（或诸子）的年纪、嫡庶、母亲的宠爱、外戚、支持他的派系、名望。不掷骰，给 GM 看。"""
    hh = w.hh
    ms = w.members()
    try:
        import court as C0
        C = C0.Court(w.dir)
    except SystemExit:
        C = None
    issue = hh.get("succession_issue", "立储")
    rows = []
    for mid, m in ms.items():
        if m.get("relation") not in SON_REL or not alive(m):
            continue
        a = age(hh, m, w.turn)
        mom = ms.get(m.get("mother") or "", {})
        clan = mom.get("clan") or m.get("clan")
        cinfo = hh.get("clans", {}).get(clan or "", {})
        fac = cinfo.get("faction")
        sup = []
        if C:
            iss = C.d["issues"].get(issue, {})
            for f, pos in iss.get("positions", {}).items():
                want = str(pos.get("want") or "")
                if m["name"] in want or mid in want:
                    sup.append(f"{f}（声量 {C.factions.get(f, {}).get('voice', '?')}）")
        fame = C.fame(m["name"]) if C else None
        card = load_card(w, m)
        mind = card.yaml.get("心迹") if card and card.role in L.COURT_ROLES else None
        rows.append((mid, m, a, mom, clan, fac, sup, fame, mind))
    return rows


def house_season(w, args):
    hh = w.hh
    turn = args.turn or w.turn
    w.turn = turn
    when = args.when or date_label(hh, turn)
    if hh.get("last_season_turn") == turn and not args.force:
        die(f"第 {turn} 回合的{hh.get('title', w.house)}已经推进过（last_season_turn）。确要重跑加 --force")
    rng = random.Random(args.seed if args.seed is not None else turn * 6151 + len(w.house))
    care = {w.mid(x) for x in args.care}
    strain = {w.mid(x) for x in args.strain}
    ms = w.members()
    y, s = year_of(hh, turn)
    palace = w.kind == "palace"
    print(f"=== {hh.get('title', w.house)}季末：{when}（第 {turn} 回合） ===")
    signs = []      # 外头看得见的（经谁、在哪个圈子）
    confirm = []    # 要 GM 确认的重大转折

    if s == "春" or turn == 1:
        print("\n--- " + ("开局的年纪" if turn == 1 else "新年，各长一岁") + " ---")
        print("  " + "；".join(f"{m['name']} {age(hh, m, turn)} 岁" for m in ms.values() if alive(m)))

    # 病程与身体
    print("\n--- 身体与病程 ---")
    any_h = False
    for mid, m in ms.items():
        if not alive(m):
            continue
        a = age(hh, m, turn)
        if m.get("illness"):
            any_h = True
            il = m["illness"]
            stages = il.get("stages") or ILL_STAGES
            st = int(il.get("stage", 0))
            res = illness_roll(rng, m, a, mid in care, mid in strain)
            tag = ("，请了名医" if mid in care else "") + ("，本季劳神动怒" if mid in strain else "")
            if res is None:
                print(f"  {m['name']}（{a} 岁）：{il.get('name', '病')}仍在“{stages[st]}”{tag}")
                new = st
            else:
                new, why, major = res
                if major:
                    word = "驾崩" if m.get("relation") == "天子" else "亡故"
                    print(f"  {m['name']}（{a} 岁）：【重大转折，待 GM 确认】{why}{tag}")
                    if new == "亡故":
                        confirm.append(f"{m['name']}{word}：household.py --house {w.house} set {mid} status=亡 health=亡故 --apply"
                                       "；继位照 rules/household.md 第九节、court.py")
                    else:
                        confirm.append(f"{m['name']}病入“{stages[new]}”：household.py --house {w.house} illness {mid} --stage {new} --apply")
                    new = st
                else:
                    print(f"  {m['name']}（{a} 岁）：{why}{tag}")
                    il["stage"] = new
                    il.setdefault("log", []).append(f"{when}：{why}")
                    h = ill_stage_health(new, len(stages))
                    if h:
                        m["health"] = h
            if il.get("known_by"):
                print(f"      知情的人：{'、'.join(il['known_by'])}" + (f"（秘密 {il['secret']}，泄露照 secrets.py season）" if il.get("secret") else ""))
            sign, cs = ILL_SIGNS.get(min(int(new), 3), ILL_SIGNS[3])
            if cs:
                signs.append(f"{m['name']}：{sign}（{'、'.join(cs)}可闻）")
            continue
        res = health_roll(rng, m, a, mid in care)
        if res:
            any_h = True
            new, why = res
            print(f"  {m['name']}（{a} 岁）：{m.get('health', '健朗')} → {new}，{why}")
            if new == "亡故":
                confirm.append(f"{m['name']}亡故：household.py --house {w.house} set {mid} status=亡 health=亡故 --apply")
            else:
                m["health"] = new
        elif m.get("health", "健朗") != "健朗":
            any_h = True
            print(f"  {m['name']}（{a} 岁）：仍是{m['health']}")
    if not any_h:
        print("  都还安好")

    # 添丁
    print("\n--- 添丁 ---")
    n_lines = 0
    preg = hh.setdefault("pregnancies", [])
    for pg in list(preg):
        mm = ms.get(pg["mother"])
        if not mm:
            continue
        n_lines += 1
        if turn >= pg["due_turn"]:
            r = rng.random()
            sex = "男" if rng.random() < 0.5 else "女"
            how = "平安" if r < 0.85 else "难产，母子保住了" if r < 0.97 else "凶险：GM 写成宫中的事"
            print(f"  {mm['name']} 临盆：生{sex}，{how}（掷 {r:.2f}）。记出生：household.py --house {w.house} birth {pg['mother']} --id … --name … --sex {sex}")
        else:
            print(f"  {mm['name']} 有孕，第 {pg['due_turn']} 回合临盆")
    head = w.head()
    head_ok = head and alive(head) and int((head.get("illness") or {}).get("stage", 0)) < int((head.get("illness") or {}).get("major_from", 2))
    for mid, m in ms.items():
        if m.get("relation") not in SPOUSE_REL or m.get("status") != "在" or not alive(m):
            continue
        if any(pg["mother"] == mid for pg in preg):
            continue
        a = age(hh, m, turn)
        if not (16 <= a <= 40) or not head_ok or not at_side(w, m):
            continue
        last_child = max([int(x.get("born_turn", -99)) for x in ms.values() if x.get("mother") == mid] + [-99])
        if turn - last_child < 4:
            continue
        p = 0.03 + 0.04 * int(m.get("favor", 1)) if palace else 0.12
        r = rng.random()
        if r < p:
            n_lines += 1
            print(f"  {m['name']} 有喜了（本季 {p:.0%}，掷 {r:.2f}）。确认后：household.py --house {w.house} pregnant {mid} --apply")
            if palace:
                signs.append(f"{m['name']}宫里添了医女、换了膳食（宫中可闻）")
    if not n_lines:
        print("  （无）")

    # 宠爱
    if palace:
        print("\n--- 宠爱（事件改，不随季漂；favor 命令记来由） ---")
        for mid, m in ms.items():
            if "favor" in m and alive(m):
                print(f"  {X_pad(m['name'], 8)}（{m.get('relation')}）：{favor_word(m['favor'])}"
                      + (f"；母族 {m['clan']}" if m.get("clan") else ""))

    # 人生节点
    print("\n--- 到点的人生节点（GM 写成宫中、府中的事） ---")
    any_m = False
    for mid, m in ms.items():
        a = age(hh, m, turn)
        for name, choices in due_milestones(w, mid, m, a):
            any_m = True
            first = m.setdefault("prompted", {}).setdefault(name, turn)
            if first < turn:
                print(f"  {m['name']}（{m.get('relation')}，{a} 岁）：{name}，第 {first} 回合起仍待定")
                continue
            print(f"  {m['name']}（{m.get('relation')}，{a} 岁）：{name}")
            for c in choices:
                print(f"      · {c}")
            print(f"      定了以后：household.py --house {w.house} milestone {mid} {name} --choice …")
    if not any_m:
        print("  （无）")

    # 储位
    rows = succession(w)
    if rows:
        print("\n--- " + ("储位形势" if palace else "继承") + "（不掷骰；给 GM 掂量，玩家只从流言、旁人嘴里知道一部分） ---")
        print(f"  {'储君' if palace else '嗣子'}：{hh.get('heir') or '未立'}")
        for mid, m, a, mom, clan, fac, sup, fame, mind in rows:
            print(f"  {m['name']}：{a} 岁，{m.get('line') or '—'}出；母 {mom.get('name', '—')}"
                  + (f"（{favor_word(mom['favor'])}）" if "favor" in mom else "")
                  + (f"；本人{favor_word(m['favor'])}" if "favor" in m else "")
                  + (f"；外戚 {clan}" + (f"，在朝属{fac}" if fac else "") if clan else "")
                  + (f"；拥立他的：{'、'.join(sup)}" if sup else "") + (f"；名望 {fame}" if fame is not None else "")
                  + (f"；心迹 {mind}" if mind else ""))
        sons = [r for r in rows if r[2] >= 12]
        if palace and not hh.get("heir") and len(rows) >= 2 and sons:
            print("  储位未定，长皇子已过十二：朝中会有人上奏请立储（court.py memorial --kind 提议 --issue 立储）")

    if signs:
        print("\n可以经旁人透露给玩家的迹象（只给从这些圈子、这些人身边能听到的；rules/household.md 第九节）：")
        for x in signs:
            print(f"  · {x}")
    if confirm:
        print("\n要 GM 确认的重大转折：")
        for x in confirm:
            print(f"  · {x}")
    hh["last_season_turn"] = turn
    if args.apply:
        w.save()
        print(f"\n已写入 {w.p(w.fname)}。重大转折要另用命令确认。")
    else:
        print("\n（未写入。确认后同一 seed 加 --apply。重大转折要另用命令确认。）")


def X_pad(s, n):
    return L.pad(s, n)


def cmd_illness(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    if args.clear:
        old = m.pop("illness", None)
        print(f"{m['name']} 的病程撤去（原：{old}）")
    else:
        il = m.setdefault("illness", {"name": args.name or "病", "stage": 0, "stages": ILL_STAGES, "pace": 0.12,
                                      "major_from": 2, "known_by": [], "log": []})
        if args.name:
            il["name"] = args.name
        if args.stages:
            il["stages"] = [x.strip() for x in re.split(r"[,，、]", args.stages) if x.strip()]
        if args.pace is not None:
            il["pace"] = args.pace
        if args.major is not None:
            il["major_from"] = args.major
        if args.known_by:
            il["known_by"] = sorted(set(il.get("known_by", [])) | {x.strip() for x in re.split(r"[,，、]", args.known_by) if x.strip()})
        if args.secret:
            il["secret"] = args.secret
        if args.stage is not None:
            stages = il.get("stages") or ILL_STAGES
            if not 0 <= args.stage < len(stages):
                die(f"档位 0–{len(stages) - 1}：{'、'.join(stages)}")
            old = il.get("stage", 0)
            il["stage"] = args.stage
            il.setdefault("log", []).append(f"{date_label(w.hh, w.turn)}：GM 确认 {stages[old]} → {stages[args.stage]}")
            h = ill_stage_health(args.stage, len(stages))
            if h:
                m["health"] = h
            print(f"{m['name']}：{il['name']} {stages[old]} → {stages[args.stage]}")
            sign, cs = ILL_SIGNS.get(min(args.stage, 3))
            print(f"  外头看得见的：{sign}" + (f"（{'、'.join(cs)}可闻；流言用 rumors.py spread）" if cs else ""))
            if il.get("secret"):
                print(f"  病情是秘密 {il['secret']}：外象跟着改，secrets.py expose {il['secret']} --level {min(args.stage, 3)} --why \"{sign.split('；')[0]}\" --apply")
        stages = il.get("stages") or ILL_STAGES
        print(f"{m['name']} 的病程：{il['name']}，眼下“{stages[int(il.get('stage', 0))]}”；"
              f"每季加重的底数 {il.get('pace')}；从“{stages[min(int(il.get('major_from', 2)), len(stages) - 1)]}”起每一步要 GM 确认；"
              f"知情：{'、'.join(il.get('known_by', [])) or '无'}")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_favor(w, args):
    mid = w.mid(args.id)
    m = w.members()[mid]
    old = int(m.get("favor", 1))
    if args.set is not None:
        new = args.set
    elif args.delta is not None:
        new = old + args.delta
    else:
        die("给 --delta 或 --set")
    if not args.why:
        die("宠爱的升降要用 --why 写明来由")
    new = max(0, min(3, new))
    m["favor"] = new
    m.setdefault("favor_log", []).append(f"{date_label(w.hh, w.turn)}：{favor_word(old)} → {favor_word(new)}（{args.why}）")
    print(f"{m['name']}：{favor_word(old)} → {favor_word(new)}（{args.why}）")
    clan = m.get("clan")
    cinfo = w.hh.get("clans", {}).get(clan or "", {})
    if clan and cinfo.get("faction") and new != old:
        print(f"  外戚 {clan} 在朝属{cinfo['faction']}：GM 可照 rules/household.md 第九节给那一派的声量 {'+' if new > old else '−'}1"
              f"（court.py faction {cinfo['faction']} --voice-delta {'1' if new > old else '-1'} --why …）")
    if args.apply:
        w.save()
        print(f"已写入 {w.p(w.fname)}。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_houses(w, args):
    print("=== 家宅 ===")
    print(f"  main：主角家（{os.path.join(w.dir, 'household.json')}）" + ("" if os.path.exists(os.path.join(w.dir, "household.json")) else "（没有）"))
    for h in list_houses(w.dir):
        try:
            with open(os.path.join(w.dir, "households", h + ".json"), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        print(f"  {h}：{d.get('title', h)}（{d.get('kind', 'clan')}），{len(d.get('members', {}))} 人")


# ---------- 给 vignette.py 用 ----------

def family_tensions(w):
    """家里眼下的张力，给 vignette.py --family 当素材。返回 [(类别, 文字, 牵涉的成员id)]。"""
    hh = w.hh
    out = []
    ms = w.members()
    for mid, m in ms.items():
        if not alive(m):
            continue
        a = age(hh, m, w.turn)
        seen = w.turn - int(m.get("last_seen_turn", w.turn))
        lim = int(m.get("neglect_limit", default_limit(m)))
        if a >= 3 and seen >= max(lim - 1, 2):
            out.append(("冷落", f"主角已经 {seen} 季没见过{m['name']}（{m.get('relation')}，{a} 岁）", mid))
        if m.get("health", "健朗") != "健朗":
            out.append(("身体", f"{m['name']}{m['health']}", mid))
        for name, _ in due_milestones(w, mid, m, a):
            out.append(("节点", f"{m['name']}，{a} 岁，到了{name}的年纪", mid))
        if m.get("status") in ("出嫁", "为质", "被掳"):
            out.append(("在外", f"{m['name']}{m['status']}，在{m.get('residence')}", mid))
        if m.get("closeness") in ("疏淡", "怨怼", "另有打算"):
            out.append(("亲疏", f"{m['name']}近来和主角{m['closeness']}（只给 GM：写迹象，不点破）", mid))
        if m.get("busy"):
            out.append(("日常", f"{m['name']}在忙：{m['busy']}", mid))
    for pg in hh.get("pregnancies", []):
        out.append(("添丁", f"{ms.get(pg['mother'], {}).get('name', '')}有孕，第 {pg['due_turn']} 回合临盆", pg["mother"]))
    for pl in hh.get("plans", []):
        if not pl.get("done"):
            out.append(("婚事", f"{pl['what']}，第 {pl.get('due_turn')} 回合", pl.get("who")))
    return out


def main():
    ap = argparse.ArgumentParser(description="家宅（规则见 rules/household.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=os.path.join(ROOT, "world"))
    ap.add_argument("--house", default="main", help="哪一家：main（主角家，household.json）或 world/households/ 下的名字（palace 等）")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn):
        p = sp.add_parser(name, help=help_)
        p.add_argument("--world", default=argparse.SUPPRESS)
        p.add_argument("--house", default=argparse.SUPPRESS)
        p.add_argument("--apply", action="store_true")
        p.set_defaults(fn=fn)
        return p

    p = add("show", "家宅总览", cmd_show)
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true", help="连已亡故的一起列")
    p.add_argument("--war", action="store_true")
    p = add("hint", "kin agent 的亲疏提示", cmd_hint)
    p.add_argument("id")
    p = add("season", "季末推进", cmd_season)
    p.add_argument("--when")
    p.add_argument("--turn", type=int, help="默认取 kingdom.json 的 turn")
    p.add_argument("--seed", type=int)
    p.add_argument("--war", action="store_true")
    p.add_argument("--trigger", action="append", default=[], help="id=事件：" + "、".join(KIN_TRIGGERS))
    p.add_argument("--care", action="append", default=[], help="本季请了名医、用心照料的人 id")
    p.add_argument("--strain", action="append", default=[], help="（宫中、大族）本季劳神、动怒、受了打击的人 id：病势加重的机会 +15%")
    p.add_argument("--force", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p = add("visit", "记一件家事", cmd_visit)
    p.add_argument("id")
    p.add_argument("--what", required=True)
    p.add_argument("--earnest", action="store_true", help="用心：做的事对上了这个人的需求")
    p.add_argument("--letter", action="store_true", help="家书")
    p.add_argument("--war", action="store_true")
    p.add_argument("--force", action="store_true", help="超出上限也记（GM 特许，写进 GM 备注）")
    p = add("milestone", "定下人生节点的走向", cmd_milestone)
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--choice")
    p.add_argument("--defer", type=int)
    p = add("pregnant", "记有孕", cmd_pregnant)
    p.add_argument("id")
    p = add("birth", "记出生", cmd_birth)
    p.add_argument("mother")
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--sex", required=True, choices=("男", "女"))
    p.add_argument("--card")
    p.add_argument("--trait")
    p.add_argument("--hard", action="store_true", help="难产：产妇身体差一档")
    p = add("match", "议亲", cmd_match)
    p.add_argument("id")
    p.add_argument("--to", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--consent", required=True)
    p.add_argument("--fit", type=int, choices=range(0, 4))
    p.add_argument("--faction")
    p.add_argument("--due", type=int)
    p = add("hostage", "送去为质", cmd_hostage)
    p.add_argument("id")
    p.add_argument("--to", required=True)
    p.add_argument("--consent", required=True)
    p = add("tie", "记下或撤去外头的牵扯", cmd_tie)
    p.add_argument("id")
    p.add_argument("--from", dest="from_")
    p.add_argument("--aim")
    p.add_argument("--promise")
    p.add_argument("--withdraw", type=int)
    p = add("plot", "敌方对家人的图谋", cmd_plot)
    p.add_argument("id")
    p.add_argument("--kind", required=True, choices=("收买", "离间", "绑架", "行刺"))
    p.add_argument("--by", required=True)
    p.add_argument("--guard", type=int, default=0, choices=range(0, 3))
    p.add_argument("--road", action="store_true", help="人在路上（出行、远嫁途中）")
    p.add_argument("--seed", type=int)
    p = add("heir", "立嗣", cmd_heir)
    p.add_argument("id")
    p.add_argument("--why", required=True)
    p = add("add", "新增家人", cmd_add)
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--relation", required=True)
    p.add_argument("--sex", required=True, choices=("男", "女"))
    p.add_argument("--born", type=int, required=True, help="公元生年")
    p.add_argument("--residence", required=True)
    p.add_argument("--health", default="健朗")
    p.add_argument("--busy")
    p.add_argument("--card")
    p.add_argument("--trait")
    p.add_argument("--spouse")
    p.add_argument("--mother")
    p.add_argument("--father")
    p.add_argument("--line")
    p.add_argument("--neglect-limit", type=int)
    p.add_argument("--done", action="append", help="开局前已过的节点")
    p = add("set", "改字段", cmd_set)
    p.add_argument("id")
    p.add_argument("pairs", nargs="+")
    p = add("where", "主角所在", cmd_where)
    p.add_argument("place")
    p = add("event", "记家事", cmd_event)
    p.add_argument("--kind", required=True, choices=("喜", "丧", "病", "其他"))
    p.add_argument("--what", required=True)
    p.add_argument("--tier", choices=tuple(BUDGET))
    p = add("illness", "（宫中、大族）病程：建立、改档、撤去", cmd_illness)
    p.add_argument("id")
    p.add_argument("--name", help="病名")
    p.add_argument("--stage", type=int, help="GM 确认的档位（0 起）")
    p.add_argument("--stages", help="自定义病程各档，逗号分隔；默认 " + "、".join(ILL_STAGES))
    p.add_argument("--pace", type=float, help="每季加重的底数，默认 0.12")
    p.add_argument("--major", type=int, help="从第几档起每一步要 GM 确认，默认 2")
    p.add_argument("--known-by", help="知道病情的人，逗号分隔")
    p.add_argument("--secret", help="对应的秘密编号（secrets.json）")
    p.add_argument("--clear", action="store_true")
    p = add("favor", "（宫中）宠爱升降", cmd_favor)
    p.add_argument("id")
    p.add_argument("--delta", type=int)
    p.add_argument("--set", type=int, choices=range(0, 4))
    p.add_argument("--why")
    p = add("houses", "列出所有家宅", cmd_houses)
    args = ap.parse_args()
    w = World(args.world, getattr(args, "house", "main"))
    args.fn(w, args)


if __name__ == "__main__":
    main()
