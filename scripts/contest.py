#!/usr/bin/env python3
"""较量：单挑（马上 / 步下）、打架、比射、辩论，共用一套框架。规则见 rules/contest.md。只用标准库。

双方的属性、特长、短处、伤势从人格卡或名册读（scripts/persona.py）。打法可以写名字，也可以写一句话，
脚本从里面认关键词；不写就按性情自动选。

  较量   run --kind 马战|步战|打架|比射|辩论 --a 名 --b 名 [--style-a 打法或一句话] [--style-b …]
             [--occasion 阵前|私下|营中|校场|朝堂|酒肆|街市|众目睽睽] [--crowd A|B] [--judge A|B]
             [--point-a −1..2] [--point-b −1..2] [--cite-a 文献=得当|牵强|失当] [--cite-b …] [--intent-a 斩|擒] [--intent-b 斩|擒]
             [--rescue-a 0–1] [--rescue-b 0–1] [--lead-a] [--lead-b] [--dirty A|B] [--dusk N]
             [--mounted] [--arrows N] [--rounds N] [--seed N] [--json] [--trials N] [--force] [--apply]
  打法   styles [--kind 种类]
  伤势   wound 名 --level 轻伤|重伤|危 [--where 部位] [--seasons N] [--apply]
  季末   heal [--care 名 ...] [--seed N] [--apply]

--apply 把伤势、死亡（名册里的人）、识人进度写回卡片和名册；人格卡上的人死了、被擒了，脚本只打印该做的事，由 GM 处理。
--trials N 同一场跑 N 次，只看胜负和伤亡的分布（调平衡、给 GM 掂量用，不用来结算正式的较量）。
--world 指向别的存档目录（试验用）。
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import persona as P  # noqa: E402
import scenario_lib as S  # noqa: E402

# ---------------------------------------------------------------- 种类

KINDS = {
    "马战": {"label": "马上单挑", "family": "combat", "unit": "合", "max": 30, "attrs": {"武": .45, "骑": .35, "胆": .20}},
    "步战": {"label": "步下单挑", "family": "combat", "unit": "合", "max": 20, "attrs": {"武": .55, "体": .20, "胆": .25}},
    "打架": {"label": "打架斗殴", "family": "brawl", "unit": "回合", "max": 12, "attrs": {"武": .40, "体": .40, "胆": .20}},
    "比射": {"label": "比射", "family": "archery", "unit": "轮", "max": 3, "attrs": {"射": 1.0}},
    "辩论": {"label": "辩论", "family": "debate", "unit": "轮", "max": 6, "attrs": {"辩": .45, "智": .30, "学": .25}},
}
KIND_ALIASES = {"马上单挑": "马战", "单挑": "马战", "马上": "马战", "步下单挑": "步战", "步下": "步战",
                "斗殴": "打架", "打一架": "打架", "射箭": "比射", "比箭": "比射", "舌辩": "辩论", "说服": "辩论", "论辩": "辩论"}

# 打法：cost 每合耗的体力；open 开头几合的加成 (合数, 加成)；def 守势（体力过半才有相克加成）；
# drain 让对方每合多耗的体力；trick 诈术（一次）；attrs 改用的属性；mounted 只能马上用；
# stall 搅局（双方的气势损失减半，自己赢不了）；keys 从玩家的话里认的关键词
STYLES = {
    "combat": {
        "猛攻": {"cost": 1.3, "open": (6, 0.5), "keys": ["猛攻", "抢攻", "强攻", "直取", "硬冲", "猛冲", "快攻", "先发制人", "冲上去", "猛"]},
        "稳守": {"cost": 0.7, "def": True, "keys": ["稳守", "以逸待劳", "招架", "守", "稳", "防"]},
        "缠斗耗力": {"cost": 1.0, "drain": 0.5, "keys": ["缠斗", "耗力", "耗他", "拖住", "周旋", "缠", "磨", "耗"]},
        "诈败回马": {"cost": 1.0, "trick": True, "keys": ["诈败", "回马", "拖刀", "佯败", "诱敌", "回身", "诈"]},
        "游走骑射": {"cost": 1.2, "mounted": True, "attrs": {"射": .50, "骑": .35, "胆": .15},
                 "keys": ["骑射", "游走", "放箭", "射他", "远射", "射"]},
    },
    "brawl": {
        "猛扑": {"cost": 1.5, "open": (4, 0.4), "keys": ["猛扑", "猛攻", "先下手", "抡拳", "冲上去", "猛"]},
        "招架": {"cost": 0.7, "def": True, "keys": ["招架", "稳守", "躲", "守", "防", "稳"]},
        "缠抱摔跤": {"cost": 1.2, "drain": 0.4, "keys": ["摔跤", "抱摔", "扭打", "抱住", "摔", "抱", "缠"]},
        "使绊子": {"cost": 1.0, "trick": True, "keys": ["使绊", "阴招", "下黑手", "使诈", "偷袭", "绊", "诈"]},
        "游斗": {"cost": 0.9, "keys": ["游斗", "绕着", "闪", "游走", "耗"]},
    },
    "archery": {
        "稳射": {"keys": ["稳射", "稳", "慢", "求稳"]},
        "求险": {"keys": ["求险", "红心", "射难的", "险", "远靶"]},
        "抢快": {"keys": ["抢快", "连珠", "快射", "快"]},
    },
    "debate": {
        "引经据典": {"attrs": {"学": .45, "辩": .35, "智": .20}, "keys": ["引经据典", "圣人", "古人", "经", "典", "史书", "书上"]},
        "以理服人": {"attrs": {"智": .45, "辩": .35, "学": .20}, "keys": ["以理服人", "利害", "算账", "道理", "讲明", "据实", "理"]},
        "以情动人": {"attrs": {"魅": .45, "辩": .40, "智": .15}, "keys": ["以情动人", "动之以情", "恳求", "义气", "恩情", "情", "哭"]},
        "抓破绽": {"attrs": {"智": .50, "辩": .35, "学": .15}, "keys": ["抓破绽", "破绽", "反问", "质问", "追问", "漏洞", "问他", "驳", "揪"]},
        "拖延搅局": {"attrs": {"辩": .60, "智": .40}, "stall": True,
                 "keys": ["拖延", "搅局", "打岔", "东拉西扯", "顾左右", "转移", "拖", "搅"]},
    },
}
# 相克：(打法, 对方打法) → 本方每合加成；反过来自动取负
COUNTER = {
    "combat": {("稳守", "猛攻"): 0.4, ("猛攻", "缠斗耗力"): 0.4, ("缠斗耗力", "稳守"): 0.4,
               ("游走骑射", "稳守"): 0.5, ("猛攻", "游走骑射"): 0.4, ("游走骑射", "缠斗耗力"): 0.3},
    "brawl": {("缠抱摔跤", "猛扑"): 0.5, ("猛扑", "游斗"): 0.4, ("游斗", "缠抱摔跤"): 0.4,
              ("招架", "猛扑"): 0.4, ("缠抱摔跤", "招架"): 0.3},
    "archery": {},
    "debate": {("抓破绽", "引经据典"): 0.6, ("引经据典", "以情动人"): 0.5, ("以情动人", "以理服人"): 0.5,
               ("以理服人", "拖延搅局"): 0.6, ("以理服人", "抓破绽"): 0.3, ("拖延搅局", "抓破绽"): 0.3},
}
# 场合：lethal 会不会死人；rescue 本阵抢救的机会；separate 打架时旁人拉开的机会（每回合，从第三回合起）；
# public 当众（辩论的恼羞成怒、心结外传）；style 这个场合偏向的打法
OCCASIONS = {
    "阵前": {"lethal": True, "rescue": 0.5, "separate": 0.0, "public": True},
    "私下": {"lethal": True, "rescue": 0.0, "separate": 0.0, "public": False},
    "营中": {"lethal": False, "rescue": 0.0, "separate": 0.10, "public": True},
    "校场": {"lethal": False, "rescue": 0.0, "separate": 0.06, "public": True},
    "朝堂": {"lethal": False, "rescue": 0.0, "separate": 0.20, "public": True, "style": {"引经据典": 0.4}},
    "酒肆": {"lethal": False, "rescue": 0.0, "separate": 0.08, "public": True, "style": {"以情动人": 0.4}},
    "街市": {"lethal": False, "rescue": 0.0, "separate": 0.08, "public": True, "style": {"以情动人": 0.4}},
    "众目睽睽": {"lethal": False, "rescue": 0.0, "separate": 0.08, "public": True, "style": {"以情动人": 0.4}},
}
# 自动选打法：性情（数值块那一行，算两倍）和天性、性情、性格一节里的词
AUTO = {
    "combat": [("猛攻", ["骄", "勇", "急", "猛", "躁", "狠", "粗", "抢", "冲", "悍"]),
               ("稳守", ["谨慎", "慎", "稳", "持重", "沉住", "深沉", "细心", "守成"]),
               ("诈败回马", ["狡", "诈", "计", "滑", "谋", "算计"]),
               ("缠斗耗力", ["倔", "韧", "耐", "磨"])],
    "brawl": [("猛扑", ["骄", "勇", "急", "猛", "躁", "狠", "粗", "抢", "冲", "悍"]),
              ("招架", ["谨慎", "慎", "稳", "沉住", "怕事", "胆小"]),
              ("使绊子", ["狡", "诈", "计", "滑", "阴"]),
              ("缠抱摔跤", ["倔", "韧", "耐", "摔"])],
    "archery": [("求险", ["骄", "勇", "猛", "抢", "狂"]), ("抢快", ["躁", "急"]), ("稳射", ["谨慎", "慎", "稳", "持重", "深沉", "细心"])],
    "debate": [("引经据典", ["经史", "典故", "读书", "引书", "书上的话", "引经"]),
               ("以理服人", ["讲理", "道理", "算账", "利害", "先算"]),
               ("以情动人", ["重情", "动情", "和气", "厚道", "仁厚", "心善", "义气", "念旧", "恩"]),
               ("抓破绽", ["刻薄", "多疑", "挑剔", "精明", "心思细", "较真"]),
               ("拖延搅局", ["圆滑", "油滑", "拖延", "躲事", "打哈哈"])],
}
ROLL_SD = {"combat": 2.0, "brawl": 2.0, "debate": 1.6}
# 本事（属性加权 + 特长加成）在每合的分里打几折：打法相克、体力、骰子才有分量，弱的一方用对了打法能翻盘
SKILL = {"combat": 0.5, "brawl": 0.5, "debate": 0.6}
EDGE, HIT, HEAVY = 1.2, 3.0, 5.0
HEAVY_BRAWL = 6.0     # 打架里重手少一些
POINT = 1.0           # 辩论：论点分每一分，每轮加多少
INJ_PENALTY = {"轻伤": (0.9, 0), "重伤": (0.7, 1), "危": (0.4, 2)}   # (武骑射体 打几折, 胆 减几)
BODY = ["左肩", "右臂", "左臂", "肋下", "大腿", "额角", "后背", "右肩", "手腕", "小腿", "腰间"]
MORALE = {"斩": (12, -15), "擒": (10, -12), "负伤退走": (6, -8), "力竭退走": (4, -5), "平手": (0, 0)}


def die(msg):
    sys.exit(f"错误：{msg}")


def cn(n):
    return S.cn_num(n)


# ---------------------------------------------------------------- 人

class Fighter:
    def __init__(self, W, person, side, kind, opts):
        self.W, self.p, self.side, self.kind = W, person, side, kind
        self.name = person.name
        self.T = W.T
        self.eff = eff_attrs(person)
        self.flags = person.flags(W.T)
        self.style = None
        self.style_note = ""
        self.wounds = 0
        self.trick_used = False
        self.marks = person.all_marks(W.T)
        stam_bonus = sum(m["contest"].get("体力", 0) for m in self.marks)
        self.max_st = (8 + 2.2 * self.eff["体"]) * (1 + stam_bonus) * (0.75 if "久战不支" in self.flags else 1)
        self.st = self.max_st
        self.morale = 6 + 0.4 * self.eff["胆"] + 0.3 * self.eff["魅"]   # 辩论的气势
        self.hits_taken = []

    def bonus(self, keys):
        """特长、短处在这一场的加成：种类、打法、场合对上了才算。正的合计最多 +1。"""
        pos = neg = 0.0
        for m in self.marks:
            for k, v in m["contest"].items():
                if k in keys:
                    if v > 0:
                        pos += v
                    else:
                        neg += v
        return min(pos, 1.0) + neg

    def trick_bonus(self):
        return sum(m["contest"].get("诈术", 0) for m in self.marks)

    def weapon(self):
        if self.kind == "马战":
            return "槊" if "使槊" in self.p.tags else "刀"
        if self.kind == "步战":
            return "剑" if "剑术" in self.p.tags else "刀"
        return "拳"


def eff_attrs(p):
    a = dict(p.attrs)
    if p.injury and p.injury.get("level") in INJ_PENALTY:
        k, d = INJ_PENALTY[p.injury["level"]]
        for x in ("武", "骑", "射", "体"):
            a[x] = a[x] * k
        a["胆"] = max(1, a["胆"] - d)
    return a


def weighted(eff, weights):
    return sum(eff[a] * w for a, w in weights.items())


# ---------------------------------------------------------------- 打法

def canon_kind(k):
    k = KIND_ALIASES.get(k, k)
    if k not in KINDS:
        die(f"种类“{k}”不认识。可用：{'、'.join(KINDS)}（别名：{'、'.join(KIND_ALIASES)}）")
    return k


NEG = ("别", "不", "莫", "勿", "休", "免得", "防着")


def parse_style(text, family, mounted):
    if not text:
        return None, ""
    table = STYLES[family]
    if text in table:
        return text, ""
    best = None
    for name, s in table.items():
        if s.get("mounted") and not mounted:
            continue
        for k in s["keys"]:
            for i in [j for j in range(len(text)) if text.startswith(k, j)]:
                if any(n in text[max(0, i - 3):i] for n in NEG):
                    continue   # “别让他抱住”“不要硬冲”：说的是不要这样打
                if best is None or len(k) > best[0]:
                    best = (len(k), name, k)
    if best:
        return best[1], f"从“{text}”里认出“{best[2]}”"
    return None, f"“{text}”里认不出打法"


def auto_style(f, foe, family, mounted):
    score = {}
    for style, words in AUTO[family]:
        if STYLES[family][style].get("mounted") and not mounted:
            continue
        score[style] = sum(2 * (f.p.temper or "").count(w) + (f.p.text or "").count(w) for w in words)
    if family == "combat" and mounted and f.eff["射"] >= f.eff["武"] + 2:
        return "游走骑射", "射艺远胜武艺，按性情选游走骑射"
    if family == "brawl" and "摔跤" in f.p.tags:
        return "缠抱摔跤", "会摔跤"
    best = max(score.items(), key=lambda x: x[1]) if score else (None, 0)
    if best[1] > 0:
        return best[0], f"按性情（{f.p.temper or '天性'}）自动选"
    if family == "debate":
        st = max(STYLES["debate"], key=lambda s: weighted(f.eff, STYLES["debate"][s].get("attrs") or KINDS["辩论"]["attrs"])
                 if not STYLES["debate"][s].get("stall") else -1)
        return st, "性情里看不出偏好，按最拿手的属性选"
    if family == "archery":
        return "稳射", "默认"
    first = {"combat": ("猛攻", "稳守"), "brawl": ("猛扑", "招架")}[family]
    w = KINDS[f.kind]["attrs"]
    return (first[0] if weighted(f.eff, w) >= weighted(foe.eff, w) else first[1]), "性情里看不出偏好，按强弱选"


def counter(family, a, b):
    c = COUNTER[family]
    if (a, b) in c:
        return c[(a, b)]
    if (b, a) in c:
        return -c[(b, a)]
    return 0.0


# ---------------------------------------------------------------- 结算：单挑、打架

class Bout:
    def __init__(self, W, kind, A, B, args, rng):
        self.W, self.kind, self.A, self.B, self.args, self.rng = W, kind, A, B, args, rng
        self.K = KINDS[kind]
        self.family = self.K["family"]
        self.occ = OCCASIONS.get(args.occasion, OCCASIONS["私下"])
        self.lines = []          # 过程摘要
        self.events = []         # 场外变数
        self.result = {}
        self.rounds = 0

    def know(self, obs, tgt):
        return self.W.know_level(obs.p, tgt.p)

    def say(self, r, text):
        self.lines.append(f"第{cn(r)}{self.K['unit']}，{text}" if r else text)


def fight(W, kind, A, B, args, rng, quiet=False):
    """马战、步战、打架。"""
    bt = Bout(W, kind, A, B, args, rng)
    fam = bt.family
    lethal = bt.occ["lethal"] and fam == "combat"
    max_r = args.rounds or (min(args.dusk, bt.K["max"]) if args.dusk else bt.K["max"])
    crowd = {"A": 0.3 if args.crowd == "A" else 0, "B": 0.3 if args.crowd == "B" else 0}
    names = {A: A.name, B: B.name}
    fallen = None
    ended = None
    long_quiet = 0
    for r in range(1, max_r + 1):
        bt.rounds = r
        sc = {}
        trick_ev = {}
        for f, o in ((A, B), (B, A)):
            st = STYLES[fam][f.style]
            s = SKILL[fam] * (weighted(f.eff, st.get("attrs") or bt.K["attrs"]) + f.bonus({kind, f.style, args.occasion}))
            c = counter(fam, f.style, o.style)
            if c > 0 and st.get("def") and f.st < 0.5 * f.max_st:
                c = 0   # 体力不济，守不住了
            if c < 0 and STYLES[fam][o.style].get("def") and o.st < 0.5 * o.max_st:
                c = 0
            s += c
            if st.get("open") and r <= st["open"][0]:
                s += st["open"][1]
            s += 0.1 * bt.know(f, o)
            s += crowd[f.side]
            if f.st <= 0:
                s -= 2.5
            elif f.st < 0.35 * f.max_st:
                s -= 1.0
            s += rng.gauss(0, ROLL_SD[fam])
            # 诈术：落了下风或斗到第八合，用一次
            if st.get("trick") and not f.trick_used and r >= 4 and (
                    f.wounds > o.wounds or f.st / f.max_st < o.st / o.max_st - 0.1 or r == 8):
                f.trick_used = True
                p = 0.45 + 0.08 * (f.eff["智"] - o.eff["智"]) + f.trick_bonus()
                ost = STYLES[fam][o.style]
                if ost.get("open") or o.style in ("猛攻", "猛扑"):
                    p += 0.25
                if ost.get("def"):
                    p -= 0.35
                if "易中诈" in o.flags:
                    p += 0.15
                if "不易中诈" in o.flags:
                    p -= 0.20
                p -= 0.1 * bt.know(o, f)
                p = max(0.05, min(0.9, p))
                ok = rng.random() < p
                s += 3.5 if ok else -1.5
                trick_ev[f] = (ok, p)
            sc[f] = s
        d = sc[A] - sc[B]
        win, lose = (A, B) if d > 0 else (B, A)
        ad = abs(d)
        for f in (A, B):
            f.st -= STYLES[fam][f.style]["cost"]
            other = B if f is A else A
            f.st -= STYLES[fam][other.style].get("drain", 0)
        for f, (ok, p) in trick_ev.items():
            o = B if f is A else A
            if fam == "combat":
                what = "拨马佯败" if kind == "马战" else "佯败回身"
                bt.say(r, f"{f.name}{what}，{o.name}{'追了上去，' + f.name + '回身一' + f.weapon() if ok else '没有上当，勒住了马' if kind == '马战' else '没有上当'}"
                       f"（成算 {p:.0%}，{'得手' if ok else '落空'}）")
            else:
                bt.say(r, f"{f.name}脚下使绊，{'把' + o.name + '绊了个趔趄' if ok else '被' + o.name + '看破'}（成算 {p:.0%}）")
        if ad >= EDGE:
            lose.st -= 0.4
        if ad >= HIT:
            n = 2 if ad >= (HEAVY if fam == "combat" else HEAVY_BRAWL) else 1
            lose.wounds += n
            part = rng.choice(BODY)
            lose.hits_taken.append(part)
            if fam == "combat":
                verb = "一箭射中" if win.style == "游走骑射" else f"一{win.weapon()}{'刺' if win.weapon() in ('槊', '剑') else '砍'}中"
                bt.say(r, f"{win.name}{verb}{lose.name}{part}，{'伤得重' if n == 2 else '见了血'}")
            else:
                bt.say(r, f"{win.name}{'一拳打在' if win.style != '缠抱摔跤' else '把人摔在地上，压住了'}"
                       f"{lose.name}{part if win.style != '缠抱摔跤' else ''}{'，半天爬不起来' if n == 2 else ''}")
            long_quiet = 0
        else:
            long_quiet += 1
        if r == 1 and not bt.lines:
            first = {"马战": "两马相交，" + ("各试了一招" if ad < EDGE else f"{win.name}占了先手"),
                     "步战": "两人步下交手，" + ("各试了一招" if ad < EDGE else f"{win.name}占了先手"),
                     "打架": "两人扭到一处，" + ("谁也没占到便宜" if ad < EDGE else f"{win.name}先动的手，占了便宜")}[kind]
            bt.say(r, first)
        if long_quiet == 10:
            bt.say(r, "两边你来我往，不分胜负" + ("，两阵上一片喝彩" if args.occasion == "阵前" else ""))
        # 场外：冷箭
        if args.occasion == "阵前" and not fallen:
            for f, o in ((A, B), (B, A)):
                behind = f.wounds > o.wounds
                p = 0.003 * (4 if args.dirty == f.side else 1) * (2 if behind else 1)
                if rng.random() < p:
                    hit = rng.random() < 0.5
                    bt.events.append({"type": "冷箭", "from": f.side, "hit": hit})
                    if hit:
                        o.wounds += 1
                        bt.say(r, f"{f.name}阵中放出一支冷箭，射中{o.name}{rng.choice(BODY)}，两阵哗然，单挑打不下去了")
                        ended = ("冷箭", f, o)
                    else:
                        bt.say(r, f"{f.name}阵中有人放冷箭，擦着{o.name}过去了，两阵哗然")
            if ended:
                break
        # 打架：旁人拉开
        if fam == "brawl" and r >= 3 and rng.random() < bt.occ["separate"]:
            bt.say(r, "旁边的人一拥而上，把两人拉开了")
            ended = ("拉开", None, None)
            break
        if fam == "brawl" and A.wounds >= 2 and B.wounds >= 2:
            ended = ("两败俱伤", None, None)
            bt.say(r, "两人都挂了彩，喘着粗气，谁也打不动了")
            break
        for f in (A, B):
            if f.wounds >= 3:
                fallen = f
        if fallen:
            break
        # 力竭
        # 力竭：体力耗尽、伤又不比对方轻的，想退；占着上风的咬牙再斗（每合 −2.5）
        tired = [f for f in (A, B) if f.st <= 0 and f.wounds >= (B if f is A else A).wounds]
        if tired and fam == "combat":
            f = min(tired, key=lambda x: x.st)
            o = B if f is A else A
            if not lethal or rng.random() < rescue_p(bt, f, args):
                ended = ("力竭", f, o)
                bt.say(r, f"{f.name}气力不支，{'拨马' if kind == '马战' else '抽身'}退回本阵" if lethal
                       else f"{f.name}气力不支，认输")
                break
        if tired and fam == "brawl":
            f = min(tired, key=lambda x: x.st)
            ended = ("力竭", f, B if f is A else A)
            bt.say(r, f"{f.name}喘不上气，摆手不打了")
            break
    return settle_fight(bt, fallen, ended, lethal, max_r)


def rescue_p(bt, f, args):
    over = args.rescue_a if f.side == "A" else args.rescue_b
    if over is not None:
        return over
    p = bt.occ["rescue"]
    if p and f.p.is_protagonist:
        p += 0.2
    if p and (args.lead_a if f.side == "A" else args.lead_b):
        p += 0.1
    return min(p, 0.95)


def intent_of(bt, f, args):
    v = args.intent_a if f.side == "A" else args.intent_b
    if v:
        return v
    hard = any(c in f"{f.p.temper} {f.p.text}" for c in "狠骄悍")
    return "斩" if bt.rng.random() < (0.6 if hard else 0.4) else "擒"


def inj_seasons(level, p):
    t = p.attrs.get("体", 5)
    if level == "轻伤":
        return 1
    if level == "重伤":
        return 3 if t <= 4 else 2
    return 4 if t <= 4 else 3


def settle_fight(bt, fallen, ended, lethal, max_r):
    A, B, rng = bt.A, bt.B, bt.rng
    res = {"winner": None, "outcome": "", "code": "", "deaths": [], "captured": [], "injuries": {}}
    loser = winner = None
    if fallen:
        loser = fallen
        winner = B if fallen is A else A
        if lethal:
            if rng.random() < rescue_p(bt, loser, bt.args):
                res["code"] = "负伤退走"
                res["injuries"][loser] = "危" if loser.wounds >= 4 else "重伤"
                bt.say(bt.rounds, f"{loser.name}落马，本阵的人拼死抢了回去")
            else:
                how = intent_of(bt, winner, bt.args)
                if how == "斩":
                    if rng.random() < (0.95 if loser.wounds >= 4 else 0.8):
                        res["code"] = "斩"
                        res["deaths"].append(loser)
                        bt.say(bt.rounds, f"{winner.name}追上去，一{winner.weapon()}结果了{loser.name}")
                    else:
                        res["code"] = "擒"
                        res["captured"].append(loser)
                        res["injuries"][loser] = "危"
                        bt.say(bt.rounds, f"{winner.name}一{winner.weapon()}下去，{loser.name}没死，被拖了回去")
                else:
                    res["code"] = "擒"
                    res["captured"].append(loser)
                    res["injuries"][loser] = "危" if loser.wounds >= 4 else "重伤"
                    bt.say(bt.rounds, f"{winner.name}把{loser.name}{'打落马下' if bt.kind == '马战' else '打倒在地'}，活捉了")
        else:
            res["code"] = "打服" if bt.family == "brawl" else "落败"
            bt.say(bt.rounds, f"{loser.name}{'被打得爬不起来，服了软' if bt.family == 'brawl' else '落败认输'}")
    elif ended:
        kind, f, o = ended
        if kind == "冷箭":
            res["code"] = "冷箭"
            loser, winner = o, None
            if o.wounds >= 2:
                res["injuries"][o] = "重伤"
        elif kind == "力竭":
            loser, winner = f, o
            res["code"] = "力竭退走" if lethal else ("力竭认输" if bt.family == "combat" else "打服")
        elif kind == "拉开":
            res["code"] = "被人拉开"
        elif kind == "两败俱伤":
            res["code"] = "两败俱伤"
    else:
        # 打满了合数
        da = A.wounds - B.wounds
        ra, rb = A.st / A.max_st, B.st / B.max_st
        if abs(da) >= 1 or abs(ra - rb) >= 0.3:
            loser = A if (da > 0 or (da == 0 and ra < rb)) else B
            winner = B if loser is A else A
            res["code"] = "负伤退走" if loser.wounds else "力竭退走"
            if not lethal:
                res["code"] = "点数落败" if bt.family == "combat" else "打服"
            bt.say(bt.rounds, f"{'天色已晚，' if bt.args.dusk else ''}{loser.name}支持不住，{'拨马回阵' if bt.kind == '马战' else '退了下去'}")
        else:
            res["code"] = "平手"
            bt.say(bt.rounds, f"{'天色已晚，' if bt.args.dusk else ''}斗了{cn(bt.rounds)}{bt.K['unit']}，不分胜负，各自收兵" if bt.family == "combat"
                   else "打了半天，谁也没服谁")
    res["winner"] = winner.side if winner else None
    res["loser"] = loser.side if loser else None
    # 伤势：带伤的人
    for f in (A, B):
        if f in res["injuries"] or f in res["deaths"]:
            continue
        w = f.wounds
        if lethal:
            lv = "重伤" if w >= 2 else "轻伤" if w == 1 else None
        elif bt.family == "combat":   # 营中、校场比武，点到为止
            x = rng.random()
            lv = None
            if w >= 3:
                lv = "重伤" if x < 0.05 else "轻伤" if x < 0.5 else None
            elif w == 2 and x < 0.25:
                lv = "轻伤"
        else:
            lv = None
            if w >= 3:
                x = rng.random()
                lv = "重伤" if x < 0.05 else "轻伤" if x < 0.35 else None
            elif w == 2 and rng.random() < 0.15:
                lv = "轻伤"
        if lv:
            res["injuries"][f] = lv
    res["outcome"] = outcome_text(bt, res, winner, loser)
    return bt, res


def outcome_text(bt, res, winner, loser):
    c = res["code"]
    if c == "斩":
        return f"{winner.name}斩{loser.name}"
    if c == "擒":
        return f"{winner.name}擒{loser.name}"
    if c in ("负伤退走", "力竭退走"):
        return f"{winner.name}胜，{loser.name}{c}"
    if c in ("落败", "打服", "力竭认输", "点数落败"):
        return f"{winner.name}胜，{loser.name}{'服了' if c == '打服' else '认输'}"
    if c == "冷箭":
        ev = bt.events[-1]
        shooter = bt.A if ev["from"] == "A" else bt.B
        return f"{shooter.name}一方放冷箭，{loser.name}{'中箭' if ev['hit'] else '躲过'}，单挑作罢"
    return {"平手": "平手", "被人拉开": "被人拉开", "两败俱伤": "两败俱伤"}.get(c, c)


# ---------------------------------------------------------------- 结算：比射

def archery(W, kind, A, B, args, rng, quiet=False):
    bt = Bout(W, kind, A, B, args, rng)
    rounds = args.rounds or 3
    arrows = args.arrows or 3
    pts = {A: 0, B: 0}

    def prob(f, o, last):
        sk = 0.6 * f.eff["射"] + 0.4 * f.eff["骑"] if args.mounted else f.eff["射"]
        p = 0.20 + 0.07 * sk + 0.06 * f.bonus({"比射", f.style, args.occasion})
        if f.style == "求险":
            p -= 0.20
        if f.style == "抢快":
            p -= 0.05
        if o.style == "抢快":
            p -= 0.04
        if last:
            p += 0.02 * (f.eff["胆"] - 5)
        if OCCASIONS.get(args.occasion, {}).get("public"):
            p += 0.015 * (f.eff["胆"] - 5)
        if args.crowd == f.side:
            p += 0.02
        return max(0.03, min(0.97, p))

    for r in range(1, rounds + 1):
        bt.rounds = r
        got = {}
        for f, o in ((A, B), (B, A)):
            p = prob(f, o, r == rounds)
            hits = sum(1 for _ in range(arrows) if rng.random() < p)
            got[f] = hits
            pts[f] += hits * (3 if f.style == "求险" else 2)
        bt.say(r, f"{A.name}{cn(arrows)}箭中{cn(got[A]) if got[A] else '零'}，{B.name}{cn(arrows)}箭中{cn(got[B]) if got[B] else '零'}"
               f"（合计 {pts[A]} 比 {pts[B]}）")
    extra = 0
    while pts[A] == pts[B] and extra < 5:
        extra += 1
        for f, o in ((A, B), (B, A)):
            if rng.random() < prob(f, o, True):
                pts[f] += 2
        bt.say(0, f"加射第{cn(extra)}箭：{pts[A]} 比 {pts[B]}")
    res = {"deaths": [], "captured": [], "injuries": {}}
    if pts[A] == pts[B]:
        res.update(winner=None, loser=None, code="平手", outcome="平手")
    else:
        w, l = (A, B) if pts[A] > pts[B] else (B, A)
        res.update(winner=w.side, loser=l.side, code="胜", outcome=f"{w.name}胜（{pts[w]} 比 {pts[l]}）")
    res["score"] = {A.side: pts[A], B.side: pts[B]}
    return bt, res


# ---------------------------------------------------------------- 结算：辩论

CITE_AUDIENCE = {"朝堂": "朝堂", "酒肆": "市井", "街市": "市井", "众目睽睽": "市井", "营中": "军中", "校场": "军中"}


def cite_of(W, spec, occasion):
    """辩论里引用文献（rules/rumors.md 第四节）：spec 写成“文献=得当|牵强|失当”。返回 (每轮加减, 说明)。"""
    if not spec:
        return 0.0, ""
    doc, _, fit = spec.rpartition("=")
    if not doc:
        die(f"--cite 写成 文献编号或书名=得当|牵强|失当：{spec!r}")
    import rumors as R
    v, why = R.cite_value(W.dir, doc, fit, CITE_AUDIENCE.get(occasion))
    return v, why

def debate(W, kind, A, B, args, rng, quiet=False):
    bt = Bout(W, kind, A, B, args, rng)
    rounds = args.rounds or bt.K["max"]
    occ = bt.occ
    point = {A: args.point_a or 0, B: args.point_b or 0}
    for f in (A, B):
        if not -1 <= point[f] <= 2:
            die("论点分只能是 −1 到 +2（rules/contest.md 第四节）")
    stall = any(STYLES["debate"][f.style].get("stall") for f in (A, B))
    cite = {A: cite_of(W, getattr(args, "cite_a", None), args.occasion), B: cite_of(W, getattr(args, "cite_b", None), args.occasion)}
    for f in (A, B):
        if cite[f][1]:
            bt.say(0, f"{f.name}引{cite[f][1]}")
    fallen = None
    for r in range(1, rounds + 1):
        bt.rounds = r
        sc = {}
        for f, o in ((A, B), (B, A)):
            st = STYLES["debate"][f.style]
            s = SKILL["debate"] * (weighted(f.eff, st.get("attrs") or bt.K["attrs"]) + f.bonus({kind, f.style, args.occasion}))
            s += counter("debate", f.style, o.style)
            s += occ.get("style", {}).get(f.style, 0)
            s += POINT * point[f] + cite[f][0]
            if args.judge == f.side:
                s += 0.8
            if args.crowd == f.side:
                s += 0.4
            s += 0.1 * bt.know(f, o)
            s += rng.gauss(0, ROLL_SD["debate"])
            sc[f] = s
        d = sc[A] - sc[B]
        win, lose = (A, B) if d > 0 else (B, A)
        ad = abs(d)
        k = 0.5 if stall else 1.0
        if ad < 1:
            A.morale -= 0.5 * k
            B.morale -= 0.5 * k
            line = "各有来回，谁也没压住谁"
        elif ad < 3:
            lose.morale -= 2.5 * k
            line = f"{win.name}占了上风，{lose.name}答得勉强"
        else:
            lose.morale -= 4 * k
            line = f"{win.name}一句话问住了{lose.name}，{lose.name}半天接不上"
        if r == 1 or ad >= 3 or r == rounds:
            bt.say(r, line)
        for f in (A, B):
            if f.morale <= 0:
                fallen = f
        if fallen:
            break
    res = {"deaths": [], "captured": [], "injuries": {}}
    if fallen:
        loser = fallen
        winner = B if fallen is A else A
        p = 0.12 + (0.25 if "易怒" in loser.flags else 0) + (0.1 if loser.eff["胆"] >= 7 and loser.eff["智"] <= 5 else 0) \
            + (0.1 if occ["public"] else 0) - (0.1 if loser.eff["智"] >= 7 else 0)
        p = max(0.02, min(0.7, p))
        if STYLES["debate"][winner.style].get("stall"):
            res.update(winner=None, loser=None, code="各执一词",
                       outcome=f"各执一词（{winner.name}搅得{loser.name}说不下去，但也没说服谁）")
        elif rng.random() < p:
            res.update(winner=winner.side, loser=loser.side, code="恼羞成怒",
                       outcome=f"{loser.name}恼羞成怒")
            bt.say(bt.rounds, f"{loser.name}脸色一变，拂袖不谈了（恼羞成怒的机会 {p:.0%}）")
        elif winner.style == "抓破绽":
            res.update(winner=winner.side, loser=loser.side, code="驳倒", outcome=f"{winner.name}驳倒{loser.name}")
        else:
            res.update(winner=winner.side, loser=loser.side, code="说服", outcome=f"{winner.name}说服了{loser.name}")
    else:
        diff = A.morale - B.morale
        if abs(diff) < 3:
            res.update(winner=None, loser=None, code="各执一词", outcome="各执一词")
        else:
            lead = A if diff > 0 else B
            res.update(winner=None, loser=None, code="各执一词", lean=lead.side,
                       outcome=f"各执一词，{lead.name}略占上风")
    res["morale_left"] = {A.side: round(A.morale, 1), B.side: round(B.morale, 1)}
    return bt, res


FAMILY_FN = {"combat": fight, "brawl": fight, "archery": archery, "debate": debate}


# ---------------------------------------------------------------- 后果

def consequences(W, bt, res, args):
    A, B = bt.A, bt.B
    side = {"A": A, "B": B}
    c = {"injuries": [], "deaths": [], "captured": [], "morale": None, "renown": [], "know": [], "ledger": [],
         "relations": [], "protagonist_dead": False, "battle": None}
    for f, lv in res["injuries"].items():
        seasons = inj_seasons(lv, f.p)
        k, dd = INJ_PENALTY[lv]
        part = f.hits_taken[-1] if f.hits_taken else bt.rng.choice(BODY)
        c["injuries"].append({"who": f.name, "level": lv, "where": part, "seasons": seasons,
                              "penalty": f"武、骑、射、体打{int(k * 10)}折" + (f"，胆−{dd}" if dd else "")
                              + ("；危：每季末掷一次凶险（contest.py heal）" if lv == "危" else "")})
    for f in res["deaths"]:
        c["deaths"].append(f.name)
        if f.p.is_protagonist:
            c["protagonist_dead"] = True
    for f in res["captured"]:
        c["captured"].append(f.name)
    fam = bt.family
    # 士气：阵前的单挑
    if args.occasion == "阵前" and fam in ("combat",):
        code = res["code"]
        key = code if code in MORALE else ("平手" if code in ("平手",) else None)
        m = {"A": 0, "B": 0}
        if key and res.get("winner"):
            up, down = MORALE[key]
            m[res["winner"]] += up
            m[res["loser"]] += down
        if code == "平手" and bt.rounds >= 20:
            m["A"] += 2
            m["B"] += 2
        for ev in bt.events:
            if ev["type"] == "冷箭":
                m[ev["from"]] -= 5
                m["B" if ev["from"] == "A" else "A"] += 5
        for s, f in side.items():
            lead = args.lead_a if s == "A" else args.lead_b
            if lead and res.get("loser") == s:
                m[s] -= 5
        leaders = {}
        for s, f in side.items():
            if (args.lead_a if s == "A" else args.lead_b):
                if f.name in c["deaths"]:
                    leaders[f.name] = "阵亡"
                elif f.name in c["captured"]:
                    leaders[f.name] = "被俘"
                elif any(i["who"] == f.name and i["level"] in ("重伤", "危") for i in c["injuries"]):
                    leaders[f.name] = "负伤"
        c["morale"] = {"A": m["A"], "B": m["B"], "A方": A.name, "B方": B.name}
        c["battle"] = {
            "resolve_battle": f"在 A 方（{A.name}一方）那一边的输入里加 \"morale_bonus\": {m['A']}，B 方加 \"morale_bonus\": {m['B']}"
                              + ("；主将重伤、阵亡、被俘的一方，统率按 5 算，不写 charge" if leaders else ""),
            "tactical": f"python3 scripts/tactical.py morale --state <战场.json> --side <A 方在战场上的代号> --delta {m['A']}"
                        f" --why \"阵前单挑\"（B 方 --delta {m['B']}）"
                        + ("".join(f" --leader {k}={v}" for k, v in leaders.items()) if leaders else ""),
            "leaders": leaders,
        }
    # 名望
    pub = bt.occ.get("public")
    if res.get("winner") and pub:
        w = side[res["winner"]]
        l = side[res["loser"]]
        if fam in ("combat", "brawl"):
            c["renown"].append(f"{w.name}{'阵前' if args.occasion == '阵前' else '当众'}胜了{l.name}，这件事会传开")
        elif fam == "archery":
            c["renown"].append(f"{w.name}比射胜了{l.name}，看的人都记住了")
        else:
            c["renown"].append(f"{w.name}在{args.occasion}上{res['code']}{l.name}，在场的人都听见了")
    # 识人：交过手，互相 +1（到 3 为止）
    for f, o in ((A, B), (B, A)):
        cur = W.know_level(f.p, o.p)
        if cur < 3:
            c["know"].append({"who": f.name, "of": o.name, "from": cur, "to": cur + 1})
    # 人心账本的建议
    for f, o in ((A, B), (B, A)):
        if f.p.source != "card" or f.p.role not in ("将领", "家人"):
            continue
        lost = res.get("loser") == f.side
        if fam == "debate" and lost and res["code"] in ("驳倒", "恼羞成怒", "说服") and pub:
            s = 2 if (res["code"] == "恼羞成怒" or "易怒" in f.flags) else 1
            if res["code"] == "说服":
                s = 0
            if s:
                c["ledger"].append(f"python3 scripts/loyalty.py grudge {P.rel(f.p.path)} --when <本季> "
                                   f"--what \"在{args.occasion}上被{o.name}当众{'驳倒' if res['code'] != '恼羞成怒' else '驳得下不来台'}\" "
                                   f"--strength {s} --heard 幕僚可闻")
            else:
                c["ledger"].append(f"{f.name}被说服了：不记心结。说服的事若正对上他的某项需求，GM 可视情 need 上调")
        if fam in ("combat", "brawl") and lost and pub and args.occasion != "阵前" and \
                ({"易怒"} & f.flags or any(x in f.p.flaws for x in ("好面子", "骄横"))):
            c["ledger"].append(f"python3 scripts/loyalty.py grudge {P.rel(f.p.path)} --when <本季> "
                               f"--what \"{args.occasion}里当众输给{o.name}\" --strength 1 --heard 幕僚可闻")
        if fam in ("combat", "brawl") and o.p.is_protagonist and f.name in [i["who"] for i in c["injuries"]] \
                and args.occasion != "阵前":
            c["ledger"].append(f"{f.name}被主角打伤：GM 看缘由定，比武点到为止的不记；下手重了，记心结 1")
    # 关系网（rules/relations.md 第三节）：当众驳倒、驳得下不来台，不论是谁，输的一方记一笔怨
    if fam == "debate" and pub and res.get("winner") and res["code"] in ("驳倒", "恼羞成怒"):
        w, l = side[res["winner"]], side[res["loser"]]
        c["relations"].append(f"python3 scripts/relations.py event {res['code']} --by {w.name} --to {l.name} "
                              f"--what \"在{args.occasion}上被{w.name}当众{'驳倒' if res['code'] == '驳倒' else '驳得下不来台'}\" --apply")
    if c["protagonist_dead"]:
        c["ledger"].append("主角战死：照 rules/contest.md 第八节，由嗣子接手；先跑 household.py show 看嗣子")
    return c


# ---------------------------------------------------------------- 命令

def setup(W, args, rng):
    kind = canon_kind(args.kind)
    fam = KINDS[kind]["family"]
    if args.occasion and args.occasion not in OCCASIONS:
        die(f"场合“{args.occasion}”不认识。可用：{'、'.join(OCCASIONS)}")
    if not args.occasion:
        args.occasion = "阵前" if fam == "combat" else ("酒肆" if fam == "brawl" else ("校场" if fam == "archery" else "私下"))
    mounted = kind == "马战" or (fam == "archery" and args.mounted)
    pa, pb = W.find(args.a), W.find(args.b)
    if pa.name == pb.name:
        die("双方是同一个人")
    A = Fighter(W, pa, "A", kind, args)
    B = Fighter(W, pb, "B", kind, args)
    for f in (A, B):
        if f.p.injury and f.p.injury.get("level") == "危" and fam in ("combat", "brawl", "archery") and not args.force:
            die(f"{f.name} 伤势危重（{P.fmt_injury(f.p.injury)}），下不了场。真要上，加 --force")
    for f, o, txt in ((A, B, args.style_a), (B, A, args.style_b)):
        st, note = parse_style(txt, fam, mounted)
        if st is None:
            st, n2 = auto_style(f, o, fam, mounted)
            note = (note + "；" if note else "") + n2
        if STYLES[fam][st].get("mounted") and not mounted:
            st, note = auto_style(f, o, fam, False)
        f.style, f.style_note = st, note
    return kind, A, B


def debate_args(**kw):
    """给别的脚本（court.py 的廷辩）用：照 run 的参数造一份，只填辩论用得到的。"""
    d = dict(kind="辩论", a=None, b=None, style_a=None, style_b=None, occasion="朝堂", crowd=None, judge=None,
             point_a=0, point_b=0, cite_a=None, cite_b=None, intent_a=None, intent_b=None, rescue_a=None, rescue_b=None,
             lead_a=False, lead_b=False, dirty=None, dusk=None, mounted=False, arrows=None, rounds=None, seed=None,
             json=False, trials=None, force=False, apply=False)
    d.update(kw)
    return argparse.Namespace(**d)


def run_debate(world, a, b, seed, **kw):
    """一场辩论，返回 (W, bt, res, 后果)。court.py 的廷辩调用它；--apply 时再调 apply(W, bt, res, 后果)。"""
    W = P.World(world)
    args = debate_args(a=a, b=b, **kw)
    kind, bt, res = run_once(W, args, seed)
    return W, bt, res, consequences(W, bt, res, args)


def run_once(W, args, seed):
    rng = random.Random(seed)
    kind, A, B = setup(W, args, rng)
    bt, res = FAMILY_FN[KINDS[kind]["family"]](W, kind, A, B, args, rng)
    return kind, bt, res


def cmd_run(W, args):
    if args.trials:
        return trials(W, args)
    seed = args.seed if args.seed is not None else random.randrange(1, 10 ** 6)
    kind, bt, res = run_once(W, args, seed)
    A, B = bt.A, bt.B
    c = consequences(W, bt, res, args)
    out = {"kind": kind, "label": KINDS[kind]["label"], "occasion": args.occasion, "seed": seed,
           "A": {"name": A.name, "style": A.style, "style_note": A.style_note},
           "B": {"name": B.name, "style": B.style, "style_note": B.style_note},
           "rounds": bt.rounds, "unit": bt.K["unit"], "outcome": res["outcome"], "code": res["code"],
           "winner": res.get("winner"), "highlights": bt.lines, "consequences": c}
    for k in ("score", "morale_left", "lean"):
        if k in res:
            out[k] = res[k]
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"=== {KINDS[kind]['label']}：{A.name} 对 {B.name}（{args.occasion}，seed={seed}） ===")
        for f in (A, B):
            inj = f"，带{f.p.injury['level']}" if f.p.injury else ""
            print(f"  {f.side} {f.name}：打法“{f.style}”" + (f"（{f.style_note}）" if f.style_note else "") + inj)
        if KINDS[kind]["family"] == "debate":
            print(f"  论点分：{A.name} {args.point_a or 0:+d}，{B.name} {args.point_b or 0:+d}"
                  + (f"；主事者偏向 {args.judge}" if args.judge else "") + (f"；围观的偏向 {args.crowd}" if args.crowd else ""))
            for side, spec in (("A", getattr(args, "cite_a", None)), ("B", getattr(args, "cite_b", None))):
                if spec:
                    print(f"  {side} 引用文献：{cite_of(W, spec, args.occasion)[1]}")
        print("--- 过程（关键几处）---")
        for l in bt.lines:
            print(f"  {l}")
        print(f"--- 结果：{res['outcome']}（共 {cn(bt.rounds)}{bt.K['unit']}） ---")
        print_consequences(c)
        print("\n后果（JSON）：")
        print(json.dumps(c, ensure_ascii=False, indent=2))
    if args.apply:
        apply(W, bt, res, c)
    else:
        print("\n（未写入。确认后同一 seed 加 --apply：伤势、名册里的死亡、识人进度写回。）")


def print_consequences(c):
    for i in c["injuries"]:
        print(f"  伤势：{i['who']} {i['level']}（{i['where']}），约 {i['seasons']} 季养好；养伤期间{i['penalty']}")
    for d in c["deaths"]:
        print(f"  死亡：{d}")
    for d in c["captured"]:
        print(f"  被擒：{d}")
    if c["morale"]:
        m = c["morale"]
        print(f"  士气：{m['A方']}一方 {m['A']:+d}，{m['B方']}一方 {m['B']:+d}")
        print(f"    接 resolve_battle.py：{c['battle']['resolve_battle']}")
        print(f"    接 tactical.py：{c['battle']['tactical']}")
    for r in c["renown"]:
        print(f"  名声：{r}")
    for k in c["know"]:
        print(f"  识人：{k['who']} 对 {k['of']} {k['from']} → {k['to']}（交过手）")
    for l in c["ledger"]:
        print(f"  人心账本（建议）：{l}")
    for l in c.get("relations", []):
        print(f"  关系网（建议）：{l}")


def apply(W, bt, res, c):
    changed_roster = False
    side = {bt.A.name: bt.A, bt.B.name: bt.B}
    for i in c["injuries"]:
        f = side[i["who"]]
        inj = {"level": i["level"], "where": i["where"], "left": i["seasons"], "worst": i["level"]}
        changed_roster |= set_injury(W, f.p, inj)
        print(f"已记伤势：{i['who']} {P.fmt_injury(inj)}")
    for d in c["deaths"]:
        f = side[d]
        if f.p.source == "roster":
            f.p.entry["status"] = "死"
            f.p.entry.setdefault("appearances", []).append(f"{W.when()}：{bt.K['label']}，死于{bt.B.name if f is bt.A else bt.A.name}之手")
            changed_roster = True
            print(f"名册：{d} 记为死。")
        else:
            print(f"人格卡上的 {d} 死了：生平记进 world/history.json，卡片移到 archive/；"
                  + ("主角战死，照 rules/contest.md 第八节立嗣接手。" if f.p.is_protagonist else "君主死了，照 ruler.md 为继承人建卡。"))
    for d in c["captured"]:
        print(f"被擒的 {d}：GM 照被俘处理（关押、赎回、劝降），写进存档和他的记忆。")
    for k in c["know"]:
        obs, tgt = side[k["who"]], side[k["of"]]
        where = W.set_know(obs.p, tgt.p, k["to"], log=f"{W.when()}：交手（{bt.K['label']}），{k['from']} → {k['to']}")
        changed_roster |= where == "roster"
        print(f"已记识人：{k['who']} 对 {k['of']} → {k['to']}")
    for f in (bt.A, bt.B):
        if f.p.source == "roster" and f.p.entry.get("status", "在") == "在":
            f.p.entry.setdefault("appearances", []).append(f"{W.when()}：和{(bt.B if f is bt.A else bt.A).name}{bt.K['label']}，{res['outcome']}")
            changed_roster = True
    if changed_roster:
        W.save_roster()
        print(f"已写入 {W.p('people.json')}。")


def set_injury(W, p, inj):
    """记伤势。返回是否改了名册。"""
    if p.source == "card":
        P.set_card_fields(p.path, {"伤势": P.fmt_injury(inj)})
        return False
    p.entry["injury"] = inj
    return True


def trials(W, args):
    n = args.trials
    base = args.seed if args.seed is not None else 1
    tally, deaths, inj, rounds = {}, {"A": 0, "B": 0}, {"A": {}, "B": {}}, 0
    wins = {"A": 0, "B": 0, None: 0}
    style = None
    for i in range(n):
        kind, bt, res = run_once(W, args, base + i)
        style = (bt.A.style, bt.B.style)
        key = res["code"] + (f"·{'A' if res.get('winner') == 'A' else 'B'}胜" if res.get("winner") else "")
        tally[key] = tally.get(key, 0) + 1
        wins[res.get("winner")] += 1
        rounds += bt.rounds
        for f in res["deaths"]:
            deaths[f.side] += 1
        for f, lv in res["injuries"].items():
            inj[f.side][lv] = inj[f.side].get(lv, 0) + 1
    A, B = W.find(args.a).name, W.find(args.b).name
    print(f"=== {KINDS[canon_kind(args.kind)]['label']}：{A}（{style[0]}）对 {B}（{style[1]}），{args.occasion}，{n} 次 ===")
    print(f"  {A} 胜 {wins['A'] / n:.1%}   {B} 胜 {wins['B'] / n:.1%}   不分胜负 {wins[None] / n:.1%}   平均 {rounds / n:.1f} {KINDS[canon_kind(args.kind)]['unit']}")
    if KINDS[canon_kind(args.kind)]["family"] in ("combat", "brawl"):
        for s, nm in (("A", A), ("B", B)):
            print(f"  {nm} 战死 {deaths[s] / n:.1%}，受伤 " + ("、".join(f"{k} {v / n:.1%}" for k, v in sorted(inj[s].items())) or "无"))
    print("  结局：" + "；".join(f"{k} {v / n:.1%}" for k, v in sorted(tally.items(), key=lambda x: -x[1])))
    return wins, deaths, inj


def cmd_styles(W, args):
    kinds = [canon_kind(args.kind)] if args.kind else list(KINDS)
    for k in kinds:
        fam = KINDS[k]["family"]
        print(f"{k}（{KINDS[k]['label']}）：每{KINDS[k]['unit']}比 " + "、".join(f"{a}×{w}" for a, w in KINDS[k]["attrs"].items()))
        for name, s in STYLES[fam].items():
            if s.get("mounted") and k != "马战":
                continue
            beats = [f"{b}+{v}" for (a, b), v in COUNTER[fam].items() if a == name]
            print(f"  {name}：关键词 {'、'.join(s['keys'][:5])}" + (f"；克 {'、'.join(beats)}" if beats else ""))


def cmd_wound(W, args):
    p = W.find(args.name)
    if args.level not in P.INJURY_LEVELS and args.level != "无":
        die("--level 只有 轻伤、重伤、危、无")
    inj = None if args.level == "无" else {"level": args.level, "where": args.where or "身上",
                                           "left": args.seasons or inj_seasons(args.level, p), "worst": args.level}
    print(f"{p.name}：伤势 {P.fmt_injury(p.injury)} → {P.fmt_injury(inj)}")
    if args.apply:
        if set_injury(W, p, inj):
            W.save_roster()
        print("已写入。")
    else:
        print("（未写入。确认后加 --apply。）")


def cmd_heal(W, args):
    k = W.kingdom()
    seed = args.seed if args.seed is not None else int(k.get("turn", 1)) * 7717 + 3
    rng = random.Random(seed)
    care = set(args.care or [])
    people = []
    for name in W.card_files():
        people.append(W.find(name))
    for e in W.roster["people"]:
        if e.get("status", "在") == "在" and e.get("injury") and not (e.get("card") and W.resolve_card(e["card"])):
            people.append(W.load_roster(e))
    print(f"=== 养伤：{W.when()}，seed={seed} ===")
    any_ = False
    changed = False
    for p in people:
        inj = p.injury
        if not inj or inj.get("level") not in P.INJURY_LEVELS:
            continue
        any_ = True
        new = dict(inj)
        note = ""
        if inj["level"] == "危":
            risk = 0.2 * (0.5 if p.name in care else 1)
            r = rng.random()
            if r < risk:
                print(f"  {p.name}：伤势危重，没能熬过这一季（凶险 {risk:.0%}，掷 {r:.2f}）")
                if args.apply:
                    if p.source == "roster":
                        p.entry["status"] = "死"
                        p.entry.setdefault("appearances", []).append(f"{W.when()}：伤重不治")
                        changed = True
                    else:
                        P.set_card_fields(p.path, {"伤势": f"亡故（{W.when()}，伤重不治）"})
                        print(f"    人格卡上的人：卡上伤势记为亡故；生平记进 world/history.json，卡片移到 archive/"
                              + ("；主角伤重不治，照 rules/contest.md 第八节立嗣接手" if p.is_protagonist else ""))
                continue
            note = f"熬过了这一季（凶险 {risk:.0%}，掷 {r:.2f}）"
        new["left"] = inj.get("left", 1) - 1
        if new["left"] <= 0:
            new = None
        elif inj["level"] == "危" and new["left"] <= 2:
            new["level"] = "重伤"
        elif inj["level"] == "重伤" and new["left"] <= 1:
            new["level"] = "轻伤"
        line = f"  {p.name}：{P.fmt_injury(inj)} → {P.fmt_injury(new) if new else '痊愈'}"
        if note:
            line += f"；{note}"
        flaw = None
        if new is None and inj.get("worst", inj["level"]) in ("重伤", "危") and "旧伤" not in p.flaws:
            r = rng.random()
            if r < 0.2:
                flaw = "旧伤"
                line += f"；落下旧伤（体−1，久战不支；掷 {r:.2f}）"
        print(line)
        if args.apply:
            if p.source == "card":
                f = {"伤势": P.fmt_injury(new)}
                if flaw:
                    fl = [x for x in p.flaws if x and x != "—"] + [flaw]
                    f["短处"] = "、".join(fl)
                    f["体"] = max(1, p.attrs["体"] - 1)
                P.set_card_fields(p.path, f)
            else:
                p.entry["injury"] = new
                if flaw:
                    per = p.entry.setdefault("persona", {})
                    per.setdefault("extra_flaws", []).append(flaw)
                    if per.get("attrs"):
                        per["attrs"]["体"] = max(1, per["attrs"]["体"] - 1)
                changed = True
    if not any_:
        print("  （没有人带伤）")
    if args.apply:
        if changed:
            W.save_roster()
        print("已写入。")
    else:
        print("（未写入。确认后同一 seed 加 --apply。）")


def main():
    ap = argparse.ArgumentParser(description="较量（规则见 rules/contest.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=os.path.join(ROOT, "world"))
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn):
        p = sp.add_parser(name, help=help_)
        p.add_argument("--world", default=argparse.SUPPRESS)
        p.set_defaults(fn=fn)
        return p

    p = add("run", "结算一场较量", cmd_run)
    p.add_argument("--kind", required=True)
    p.add_argument("--a", required=True, help="A 方（一般是主角或挑战的一方）")
    p.add_argument("--b", required=True)
    p.add_argument("--style-a")
    p.add_argument("--style-b")
    p.add_argument("--occasion")
    p.add_argument("--crowd", choices=("A", "B"), help="围观的人偏向哪一方")
    p.add_argument("--judge", choices=("A", "B"), help="辩论：主事者、听众偏向哪一方")
    p.add_argument("--point-a", type=int, help="辩论：A 方原话的论点分 −1..2")
    p.add_argument("--point-b", type=int, help="辩论：B 方原话的论点分 −1..2")
    p.add_argument("--cite-a", help="辩论：A 方引用的文献，写成 文献编号=得当|牵强|失当（rules/rumors.md）")
    p.add_argument("--cite-b", help="辩论：B 方引用的文献")
    p.add_argument("--intent-a", choices=("斩", "擒"))
    p.add_argument("--intent-b", choices=("斩", "擒"))
    p.add_argument("--rescue-a", type=float, help="A 落马时本阵抢回的机会（0–1），默认按场合")
    p.add_argument("--rescue-b", type=float)
    p.add_argument("--lead-a", action="store_true", help="A 是这一军的主将")
    p.add_argument("--lead-b", action="store_true")
    p.add_argument("--dirty", choices=("A", "B"), help="哪一方阵中有人想放冷箭")
    p.add_argument("--dusk", type=int, help="天黑前还能斗几合")
    p.add_argument("--mounted", action="store_true", help="比射：马上射")
    p.add_argument("--arrows", type=int)
    p.add_argument("--rounds", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--json", action="store_true")
    p.add_argument("--trials", type=int)
    p.add_argument("--force", action="store_true")
    p.add_argument("--apply", action="store_true")
    p = add("styles", "列出打法和相克", cmd_styles)
    p.add_argument("--kind")
    p = add("wound", "记伤势（战斗里负的伤也用它）", cmd_wound)
    p.add_argument("name")
    p.add_argument("--level", required=True)
    p.add_argument("--where")
    p.add_argument("--seasons", type=int)
    p.add_argument("--apply", action="store_true")
    p = add("heal", "季末养伤", cmd_heal)
    p.add_argument("--care", action="append", help="有名医、懂医的人照料的，凶险减半")
    p.add_argument("--seed", type=int)
    p.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    W = P.World(args.world)
    args.fn(W, args)


if __name__ == "__main__":
    main()
