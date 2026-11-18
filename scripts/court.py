#!/usr/bin/env python3
"""派系与朝议：派系、官职、议题、奏疏、朝议结算、党争、仕途（器重与考课）、朝臣的心迹。规则见 rules/court.md。只用标准库。

存档是 world/court.json。会改存档的命令默认只打印，加 --apply 才写回；有掷骰的地方支持 --seed。
大事不靠骰子：各派附议还是反对，由立场、利害、关系网、圣意算出来；骰子只在廷辩（contest.py）里。
最后的定夺由 GM 调 ruler agent（天子）或主事者的 agent 按人格卡决定，脚本只给“各方意见汇总”和“建议提示”。

  总览     show [--faction 派] [--issue 议题] [--person 名]
  上奏     memorial --by 名 --kind 提议|弹劾|举荐|请辞 [--issue 议题 --ask 主张] [--target 名] [--penalty 罢官]
                    [--office 职] --text 原话摘要 [--point -1..2] [--evidence 证据] [--cite 文献=得当] [--bypass] [--fabricated]
  朝议     session 奏疏编号 [--debate 甲:乙] [--point-a N --point-b N] [--style-a … --style-b …] [--cite-a … --cite-b …]
                    [--lean 准|驳 --signal 明示|暗示|未露] [--seed N]
  定夺     decide 奏疏编号 --ruling 准|驳|留中|折中 [--penalty …] [--office 职] [--where 地] [--false] [--note …]
  任免     appoint 名 --office 职 [--rank N] [--council] [--why …]
           remove 名 --status 外放|罢官|下狱|致仕|丁忧|流放|死 [--where 地] --why …
  派系     faction 派 [--new --leader 名 --stance 立场] [--join 名] [--leave 名] [--voice-delta N --why …]
  议题     issue 议题 [--title …] [--options a,b,c] [--lean 主张 --signal 明示|暗示|未露] [--status …]
           position 派 --issue 议题 --want 主张 [--accept a,b] [--bottom c] [--weight 1-3]
  党争     feud 甲派 乙派 --what 事由 --strength 1-3 [--when 时间]
  仕途     career 名 [--post 职] [--ladder 阶梯] [--superior 名] [--duty 差事 --due 回合]
           ladder [阶梯]                        仕途阶梯（流外小吏、武职一阶一阶往上走）：每阶的品级、俸钱、谁在这一阶
           promote 名 [--down] [--to 阶] --why …  在阶梯上升一阶、降一阶或跳到某一阶
           regard 名 [--event 办成差事|办砸|越级上奏|顶撞|担责|献策被用|结交政敌] [--delta N] --why …
           duty 名 --result 上|中|下|误事 --what …
  提示     hint 名                              写进 courtier agent prompt 的“朝中提示”
  季末     season [--when 时间] [--trigger 名=事件 …] [--pay] [--seed N]

所有命令都有 --world（试验用）。
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import social_lib as X  # noqa: E402

FILE = "court.json"
EMPTY = {"version": 1, "sovereign": None, "fame_kind": "士林", "review_every": 4, "factions": {}, "offices": {},
         "issues": {}, "memorials": [], "feuds": {}, "careers": {}, "ladders": {}, "out": {}, "next_memorial": 1,
         "last_season_turn": 0, "log": []}

KINDS = ("提议", "弹劾", "举荐", "请辞")
RULINGS = ("准", "驳", "留中", "折中")
SIGNALS = ("明示", "暗示", "未露")
# 处分：(受罚的人记的怨, 他那一派声量 −, 两派之间党争的强度, 去不去职)
PENALTIES = {
    "申饬": (1, 0, 1, False), "罚俸": (1, 0, 1, False), "降职": (2, 1, 2, False), "外放": (2, 1, 2, True),
    "罢官": (3, 2, 3, True), "下狱": (3, 2, 3, True), "流放": (3, 2, 3, True),
}
OUT_STATUS = ("外放", "罢官", "下狱", "致仕", "丁忧", "流放", "死")

FEUD_LEVELS = ["相安", "龃龉", "攻讦", "罗织", "死斗"]
FEUD_CEILING = {
    "相安": "就事论事：朝议上可以反对对方的主张，不攻击对方的人。",
    "龃龉": "可以在议事时讥讽、私下说对方的不是、不附议对方的人；不上弹章。",
    "攻讦": "可以上奏弹劾对方的人（要有实据，或者照例风闻奏事），朝议上当众驳斥；不捏造罪名。",
    "罗织": "可以翻旧账、收买对方门下的人作证、借流言造势、把小过说成大罪；捏造的罪名要登记成一条秘密（谁构陷了谁），会泄露。",
    "死斗": "可以图谋让对方的人下狱、流放、抄家，勾结宫中、外戚、禁军；行刺另走 household.py plot 的办法，不在朝议里结算。",
}
FEUD_SIGNS = {
    "相安": ["议事时各说各的，散朝还一同出宫。"],
    "龃龉": ["议事时有人话里带刺；两派的人宴集不再互请。", "门下的人在酒肆里互相讥笑。"],
    "攻讦": ["弹章一道接一道，奏的都是对方的人。", "朝会上当面争执，有人拂袖而去。"],
    "罗织": ["有人在翻对方十年前的旧案；对方门下的书吏忽然被叫去问话。", "市井里出了关于某人的怪话，来路不明。"],
    "死斗": ["有人下了狱，家里被抄；两派的人在宫门口相遇都不说话。", "禁军换防不照常例；有人深夜入宫。"],
}

MIND_LEVELS = ["恭谨", "怠慢", "怨望", "异志"]
MIND_TRIGGERS = {
    "性命之危": "被拘审、将被问罪处死，或确知上面要他的命",
    "罢官下狱": "被罢官、下狱、流放",
    "储位被夺": "已有的储位、许下的名分被夺（皇子、母妃）",
    "当众受辱": "当着百官、宫人的面被斥辱、责打",
    "至亲受害": "至亲因上面的处置被囚、被杀、被逐",
}
MIND_CEILING = {
    "恭谨": "尽心办事，有话直说或婉言进谏；不和外人私议上面的不是。",
    "怠慢": "照章办事，不多出主意，奏对简短；不在外头说上面的不是。",
    "怨望": "可以私下发牢骚、称病不朝、在议事时顶撞、拖着不办不合意的差事、向亲近的人诉苦；不结外援，不递禁中的消息出去。",
    "异志": "可以私下结党、联络外援（皇子、外藩、敌国、别的派系）、递消息、为自己安排后路；"
            "手里有兵或外援接应、又出了触发事件的，可以谋废立、宫变，GM 照兵变的规矩结算。不行刺（行刺另走 plot）。",
}
MIND_SIGNS = {
    "恭谨": ["没有异样。"],
    "怠慢": ["奏对简短，不再多说一句。", "该他上的条陈迟迟不上。"],
    "怨望": ["称病不朝，或者朝会上冷着脸。", "门下的人说他私下叹过气、摔过东西。", "和失意的旧人走动多了。"],
    "异志": ["府上夜里有生面孔出入。", "和某位皇子、某个外镇的人书信往来勤了。", "家眷、细软悄悄往别处挪。"],
}

REGARD_WORDS = {-3: "厌弃", -2: "不喜", -1: "冷淡", 0: "寻常", 1: "看重", 2: "器重", 3: "倚为心腹"}
REGARD_EVENTS = {
    "办成差事": (1, "交办的事办成了"),
    "办得出色": (2, "差事办得出色，上面脸上有光"),
    "办砸": (-1, "差事办砸了"),
    "误事": (-2, "误了大事，连累上司"),
    "越级上奏": (-1, "没经他就直接上奏"),
    "顶撞": (-1, "当众顶撞他"),
    "担责": (1, "替他担了干系"),
    "献策被用": (1, "出的主意被采纳"),
    "结交政敌": (-1, "和他的政敌走得近（他知道的）"),
}
DUTY = {"上": 2, "中": 1, "下": -1, "误事": -2}
# 每季俸禄（钱，单位照剧本的 money_unit），按品级。只给不是一方之主的主角记家财用
SALARY = {1: 600, 2: 450, 3: 330, 4: 240, 5: 170, 6: 120, 7: 80, 8: 55, 9: 40}
# 剧本可以在 court.json 的 ladders 里写仕途阶梯：流外的小吏、武职一阶一阶往上走的路，每阶写品级和每季俸钱（rules/court.md 第六节）


# ---------------------------------------------------------------- 存档

class Court:
    def __init__(self, world):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        for k, v in EMPTY.items():
            self.d.setdefault(k, json.loads(json.dumps(v)))
        self._people = None
        self._net = None

    @property
    def people(self):
        if self._people is None:
            self._people = X.People(self.world)
        return self._people

    @property
    def net(self):
        if self._net is None:
            import relations as REL
            self._net = REL.Net(self.world)
        return self._net

    def save(self):
        return X.save_json(self.world, FILE, self.d)

    # --- 查 ---
    @property
    def factions(self):
        return self.d["factions"]

    @property
    def offices(self):
        return self.d["offices"]

    def faction_of(self, name):
        for f, r in self.factions.items():
            if name in r.get("members", []) or r.get("leader") == name:
                return f
        return None

    def office_of(self, name):
        for o, r in self.offices.items():
            if r.get("holder") == name:
                return o, r
        return None, None

    def post_of(self, name):
        o, r = self.office_of(name)
        if o:
            return o
        out = self.d["out"].get(name)
        if out:
            return f"{out['status']}" + (f"（{out['where']}）" if out.get("where") else "")
        car = self.d["careers"].get(name)
        return car.get("post") if car else None

    def rank_of(self, name):
        o, r = self.office_of(name)
        return int(r.get("rank", 9)) if r else None

    def seat_weight(self, name):
        o, r = self.office_of(name)
        if not r:
            return 0
        rank = int(r.get("rank", 9))
        if r.get("council"):
            return 3 if rank <= 3 else 2
        return 1 if rank <= 5 else 0.5

    def memorial(self, mid):
        m = next((m for m in self.d["memorials"] if m["id"] == mid), None)
        if not m:
            X.die(f"没有奏疏 {mid}（有：{'、'.join(x['id'] for x in self.d['memorials']) or '无'}）")
        return m

    def fame(self, name):
        return X.fame_of(self.people, name, self.d.get("fame_kind", "士林"))

    # --- 仕途阶梯 ---
    def ladder(self, lname):
        lad = self.d.get("ladders", {}).get(lname)
        if lad is None:
            X.die(f"court.json 的 ladders 里没有“{lname}”（有：{'、'.join(self.d.get('ladders', {})) or '无'}）")
        return lad

    def ladder_pos(self, name):
        """他在仕途阶梯上的位置：(阶梯名, 第几阶, 这一阶)。没记阶梯的返回 (None, None, None)；
        记了阶梯、眼下的职不在阶梯上的（借调、外放），返回 (阶梯名, None, None)。"""
        car = self.d["careers"].get(name) or {}
        lname = car.get("ladder")
        if not lname:
            return None, None, None
        post = self.post_of(name)
        for i, r in enumerate(self.ladder(lname).get("rungs", [])):
            if r.get("post") == post:
                return lname, i, r
        return lname, None, None

    def person_rank(self, name):
        """品级：任着官职的按官职，阶梯上的按这一阶；流外、无官返回 None。"""
        r = self.rank_of(name)
        if r:
            return r
        _, _, rung = self.ladder_pos(name)
        return int(rung["rank"]) if rung and rung.get("rank") else None

    # --- 党争 ---
    def feud_key(self, a, b):
        return "|".join(sorted((a, b)))

    def feud(self, a, b, create=False):
        if not a or not b or a == b:
            return None
        k = self.feud_key(a, b)
        f = self.d["feuds"].get(k)
        if f is None and create:
            f = self.d["feuds"][k] = {"entries": [], "level": "相安", "log": []}
        return f

    def feud_level(self, a, b):
        f = self.feud(a, b)
        return FEUD_LEVELS.index(f["level"]) if f else 0

    def add_feud(self, a, b, what, s, when):
        f = self.feud(a, b, create=True)
        if f is None:
            return None
        e = {"id": max([x["id"] for x in f["entries"]] + [0]) + 1, "when": when, "what": what, "s": s,
             "status": "未了", "age": 0}
        f["entries"].append(e)
        return e


def feud_heat(f):
    return sum(e["s"] for e in f["entries"] if e["status"] == "未了")


def rung_text(rung):
    if not rung:
        return ""
    rk = rung.get("rank_name") or (f"{rung['rank']}品" if rung.get("rank") else "流外")
    pay = f"，每季俸 {rung['pay']}" if rung.get("pay") is not None else ""
    return f"{rung['post']}（{rk}{pay}）"


def salary(C, name):
    """本季俸钱（剧本的大单位，可以带小数）和说明。阶梯上写了 pay 的按 pay；否则按品级表 SALARY。
    没有官、没有阶梯的返回 (None, 说明或 None)。罚俸、发到哪里由 scripts/purse.py 管。"""
    lname, i, rung = C.ladder_pos(name)
    if rung and rung.get("pay") is not None:
        return float(rung["pay"]), f"{lname}·{rung['post']}"
    rank = C.person_rank(name)
    if rank:
        return float(SALARY.get(rank, 0)), f"{C.post_of(name)}，{rank}品"
    if name in C.d["careers"]:
        return None, f"{C.post_of(name) or '无官'}：没有品级，阶梯上也没写俸钱"
    return None, None


def regard_word(v):
    return REGARD_WORDS[X.clamp(int(v), -3, 3)]


# ---------------------------------------------------------------- 立场

def align_issue(pos, ask):
    if not pos or not ask:
        return 0.0, None
    w = int(pos.get("weight", 2)) / 2
    if ask == pos.get("want"):
        return 2 * w, f"正合本派主张（{ask}）"
    if ask in pos.get("bottom", []):
        return -3 * w, f"碰了本派的底线（{pos.get('bottom_text') or ask}）"
    if ask in pos.get("accept", []):
        return 1 * w, f"本派可以接受（{ask}）"
    if pos.get("want"):
        return -1 * w, f"和本派的主张（{pos['want']}）相左"
    return 0.0, None


def lean_of(C, m, override=None):
    """圣意：(主张, 透露的程度)。奏疏上 GM 写的为先，其次议题上的。"""
    if override and override[0]:
        return override
    if m.get("lean"):
        return m["lean"], m.get("signal", "未露")
    if m["kind"] == "提议":
        iss = C.d["issues"].get(m.get("issue") or "")
        if iss and iss.get("sovereign"):
            return iss["sovereign"].get("lean"), iss["sovereign"].get("signal", "未露")
    return None, "未露"


def lean_favors(m, lean):
    """圣意偏向这道奏疏（+1）、反对（−1）、无关（0）。"""
    if not lean:
        return 0
    if m["kind"] == "提议":
        return 1 if lean == m.get("ask") else -1
    return 1 if lean == "准" else -1 if lean == "驳" else 0


def rumor_pressure(C, target):
    """说到 target 的流言，在朝堂里传开、多半信了的，算舆论。返回 (加分, 说明)。"""
    try:
        B = X.load_json(C.world, "rumors.json", {})
    except SystemExit:
        return 0, ""
    hot = [r for r in B.get("rumors", []) if target in r.get("about", []) and r.get("status") in ("流传", "坐实")
           and r.get("heat", {}).get("朝堂", 0) >= 3 and r.get("cred", 0) >= 3]
    if hot:
        return 1.0, f"朝堂上正传着说他的话（{'、'.join(r['id'] for r in hot)}）"
    return 0, ""


def stance(C, m, actor, faction, sov):
    """一个人（一派的首领代表一派，或不在派里的重臣）对这道奏疏的分。返回 (分, 理由)。"""
    s, why = 0.0, []
    net = C.net
    pf = C.faction_of(m["by"])
    # 议题
    if m["kind"] == "提议":
        iss = C.d["issues"].get(m.get("issue") or "", {})
        a, w = align_issue(iss.get("positions", {}).get(faction) if faction else None, m.get("ask"))
        if w:
            s += a
            why.append(f"{w} {a:+.1f}")
    # 上奏的人
    if actor == m["by"]:
        s += 4
        why.append("他自己上的奏 +4")
    elif faction and pf == faction:
        s += 2
        why.append("本派的人上的奏 +2")
    elif faction and pf:
        lv = C.feud_level(faction, pf)
        if lv:
            s -= 0.75 * lv
            why.append(f"和{pf}{FEUD_LEVELS[lv]} {-0.75 * lv:+.2f}")
    c = net.closeness(actor, m["by"])
    if c:
        s += 0.5 * c
        why.append(f"{actor}看{m['by']}{'亲' if c > 0 else '疏'}（{c:+d}）{0.5 * c:+.1f}")
    # 被弹劾、被举荐的人
    t = m.get("target")
    if t and m["kind"] in ("弹劾", "举荐"):
        tf = C.faction_of(t)
        sign = -1 if m["kind"] == "弹劾" else 1
        if faction and tf == faction:
            v = -4 if sign < 0 else 2
            s += v
            why.append(f"{t}是本派的人 {v:+d}")
        elif faction and tf:
            lv = C.feud_level(faction, tf)
            if lv:
                s += -sign * 0.75 * lv
                why.append(f"{t}是{tf}的人，两派{FEUD_LEVELS[lv]} {-sign * 0.75 * lv:+.2f}")
        ct = net.closeness(actor, t)
        if ct:
            s += sign * 0.7 * ct
            why.append(f"{actor}看{t}{'亲' if ct > 0 else '疏'}（{ct:+d}）{sign * 0.7 * ct:+.1f}")
        if m["kind"] == "弹劾":
            if C.fame(t) >= 7:
                s -= 1
                why.append(f"{t}名重，动他要掂量 −1")
            rp, rw = rumor_pressure(C, t)
            if rp:
                s += rp
                why.append(f"{rw} +1")
    # 奏疏本身
    pt = int(m.get("point", 0))
    if pt:
        s += pt
        why.append(f"奏疏说得{'在理' if pt > 0 else '不在理'} {pt:+d}")
    ev = min(len(m.get("evidence", [])), 2)
    if ev:
        s += ev
        why.append(f"有凭据 {ev} 件 +{ev}")
    if m.get("cite_value"):
        s += m["cite_value"]
        why.append(f"引文献 {m['cite_value']:+.1f}")
    f_by = C.fame(m["by"])
    if f_by >= 7:
        s += 0.5
        why.append(f"{m['by']}名重 +0.5")
    elif f_by <= 1:
        s -= 0.5
        why.append(f"{m['by']}人微言轻 −0.5")
    # 圣意
    lean, signal = sov
    fav = lean_favors(m, lean)
    if fav and signal in ("明示", "暗示"):
        v = fav * (1.5 if signal == "明示" else 0.75)
        s += v
        why.append(f"圣意{signal}{'赞成' if fav > 0 else '不赞成'} {v:+.2f}")
    return s, why


def verdict(s):
    return "附议" if s >= 1.5 else "反对" if s <= -1.5 else "观望"


def council_people(C):
    return [(o, r) for o, r in C.offices.items() if r.get("council") and r.get("holder")]


def best_speaker(C, names):
    best, bv = None, -1
    for n in names:
        a = C.people.attrs(n)
        if not a:
            continue
        v = a.get("辩", 5) * 0.45 + a.get("智", 5) * 0.3 + a.get("学", 5) * 0.25
        if v > bv:
            best, bv = n, v
    return best


# ---------------------------------------------------------------- 命令：总览

def finish(C, args, extra=""):
    if getattr(args, "apply", False):
        print(f"\n已写入 {X.rel(C.save())}{extra}。")
    else:
        print("\n（未写入。确认无误后同一 seed 加 --apply。）")


def cmd_show(C, args):
    d = C.d
    print(f"=== 朝廷（第 {X.turn_of(C.world)} 回合）：定夺者 {d.get('sovereign') or '未写'}；朝议看{d.get('fame_kind')}的名望 ===")
    if args.person:
        n = args.person
        o, r = C.office_of(n)
        print(f"  {n}：{C.post_of(n) or '无官'}" + (f"（{r.get('rank')}品{'，有议政之权' if r.get('council') else ''}）" if r else "")
              + f"；派系 {C.faction_of(n) or '无'}；{d['fame_kind']}名望 {C.fame(n)}")
        car = d["careers"].get(n)
        if car:
            print(f"  仕途：上司 {car.get('superior')}，器重 {regard_word(car.get('regard', 0))}（{car.get('regard', 0):+d}），"
                  f"考绩 {car.get('merit', 0)}，差事 {car.get('duty') or '无'}")
            lname, i, rung = C.ladder_pos(n)
            if lname:
                rungs = C.ladder(lname)["rungs"]
                nxt = rungs[i + 1] if i is not None and i + 1 < len(rungs) else None
                print(f"  阶梯：{lname}，眼下 {rung_text(rung) if rung else '（不在阶梯上）'}" + (f"；再往上是 {rung_text(nxt)}" if nxt else ""))
            big, why = salary(C, n)
            if big is not None:
                print(f"  俸钱：每季 {big:g}（{why}）")
        return
    for f, r in d["factions"].items():
        if args.faction and f != args.faction:
            continue
        seats = [f"{m}（{C.post_of(m) or '无官'}）" for m in r.get("members", [])]
        print(f"  【{f}】首领 {r.get('leader')}，声量 {r.get('voice', 5)}；{r.get('stance', '')}")
        print(f"      成员：{'、'.join(seats)}")
    if not args.faction and not args.issue:
        print("  官职：")
        for o, r in sorted(d["offices"].items(), key=lambda x: int(x[1].get("rank", 9))):
            print(f"    {X.pad(o, 14)} {r.get('rank')}品 {'议政' if r.get('council') else '    '} {r.get('holder') or '（缺）'}"
                  + (f"〔{C.faction_of(r['holder'])}〕" if r.get("holder") and C.faction_of(r["holder"]) else ""))
        if d["out"]:
            print("  不在朝的：" + "；".join(f"{n} {v['status']}" + (f"于{v['where']}" if v.get("where") else "") for n, v in d["out"].items()))
    for k, iss in d["issues"].items():
        if args.issue and k != args.issue:
            continue
        sv = iss.get("sovereign", {})
        print(f"  议题【{iss.get('title', k)}】{iss.get('status', '悬而未决')}；可选：{'、'.join(iss.get('options', []))}"
              f"；圣意（GM）：{sv.get('lean') or '未定'}（{sv.get('signal', '未露')}）")
        for f, p in iss.get("positions", {}).items():
            print(f"      {f}：要 {p.get('want')}；可接受 {'、'.join(p.get('accept', [])) or '—'}；底线 {'、'.join(p.get('bottom', [])) or '—'}"
                  + (f"（{p['bottom_text']}）" if p.get("bottom_text") else "") + f"；看重 {p.get('weight', 2)}")
    if not args.faction and not args.issue:
        for k, f in d["feuds"].items():
            print(f"  党争 {k.replace('|', ' 与 ')}：{f['level']}（积怨 {feud_heat(f)}）")
        pend = [m for m in d["memorials"] if m["status"] in ("待议", "已议")]
        for m in pend:
            print(f"  奏疏 {m['id']}（{m['status']}）：{m['by']}{m['kind']}" + (f"{m.get('target')}" if m.get("target") else "")
                  + (f"〔{m.get('issue')}：{m.get('ask')}〕" if m.get("issue") else "") + f"——{m['text'][:30]}")
        for n, car in d["careers"].items():
            print(f"  仕途 {n}：{car.get('post')}，上司 {car.get('superior')}，器重 {regard_word(car.get('regard', 0))}，考绩 {car.get('merit', 0)}")


# ---------------------------------------------------------------- 上奏

def cmd_memorial(C, args):
    if args.kind not in KINDS:
        X.die(f"--kind 只能是 {'/'.join(KINDS)}")
    m = {"id": f"M{C.d['next_memorial']}", "turn": X.turn_of(C.world), "when": X.when_of(C.world, args.when),
         "by": args.by, "kind": args.kind, "text": args.text, "point": args.point or 0,
         "evidence": X.split_names(args.evidence), "status": "待议", "co_signers": X.split_names(args.co)}
    if args.kind == "提议":
        if not args.issue or not args.ask:
            X.die("提议要写 --issue 议题 和 --ask 主张")
        iss = C.d["issues"].get(args.issue)
        if not iss:
            X.die(f"没有议题“{args.issue}”（有：{'、'.join(C.d['issues']) or '无'}）。新议题先用 issue 建")
        if iss.get("options") and args.ask not in iss["options"]:
            print(f"注：“{args.ask}”不在这个议题原有的选项里（{'、'.join(iss['options'])}），照记，各派的立场按“无关”算。")
        m["issue"], m["ask"] = args.issue, args.ask
    elif args.kind in ("弹劾", "举荐"):
        if not args.target:
            X.die(f"{args.kind}要写 --target 名")
        m["target"] = args.target
        if args.kind == "弹劾":
            m["ask"] = args.penalty or "罢官"
            if m["ask"] not in PENALTIES:
                X.die(f"--penalty 只能是 {'/'.join(PENALTIES)}")
        else:
            if not args.office:
                X.die("举荐要写 --office 职（举荐他做什么官）")
            m["office"] = m["ask"] = args.office
    else:
        o, r = C.office_of(args.by)
        m["office"] = args.office or o
        m["ask"] = "准辞"
    if args.cite:
        import rumors as R
        doc, _, fit = args.cite.rpartition("=")
        v, why = R.cite_value(C.world, doc, fit, "朝堂")
        m["cite"], m["cite_value"] = args.cite, v
        print(f"  引文献：{why}")
    if args.bypass:
        m["bypass"] = True
    if args.fabricated:
        m["fabricated"] = True
    if args.lean:
        m["lean"], m["signal"] = args.lean, args.signal or "未露"
    C.d["next_memorial"] += 1
    C.d["memorials"].append(m)
    print(f"奏疏 {m['id']}：{m['by']}（{C.post_of(m['by']) or '无官'}，{C.faction_of(m['by']) or '不在派'}）{m['kind']}"
          + (f" {m.get('target')}" if m.get("target") else "") + f"，所请：{m.get('ask')}")
    print(f"  原话摘要：{m['text']}")
    print(f"  论点分（GM 照 rules/contest.md 第四节的刻度给奏疏打）：{m['point']:+d}；凭据 {len(m['evidence'])} 件")
    car = C.d["careers"].get(args.by)
    if car and args.bypass:
        print(f"  越级上奏：上司 {car.get('superior')} 事先不知道。定夺后按 rules/court.md 第六节记器重。")
    if args.fabricated:
        print("  这道弹章里有捏造的罪名：照 rules/court.md 第五节，登记一条秘密（谁构陷了谁），"
              f"secrets.py add --title \"{args.by}构陷{args.target}\" … --knower {args.by}=全知 --apply。查实了要反坐。")
    car_t = C.d["careers"].get(args.target or "")
    finish(C, args)


# ---------------------------------------------------------------- 朝议

def participants(C, m):
    """参与表态的：每一派（首领代表），不在派里的议政重臣。"""
    out = []
    for f, r in C.factions.items():
        if r.get("leader"):
            out.append(("派", f, r["leader"], r.get("voice", 5)))
    for o, r in council_people(C):
        h = r["holder"]
        if not C.faction_of(h):
            out.append(("臣", None, h, C.seat_weight(h)))
    return out


def tally(C, m, sov, swing=None):
    """返回 rows: [(类型, 派, 人, 分量, 分, 表态, 理由)] 和 倒戈的人。"""
    rows, breaks = [], []
    for typ, f, who, wt, in participants(C, m):
        if who in (m["by"],) and typ == "臣":
            continue
        s, why = stance(C, m, who, f, sov)
        if swing and verdict(s) == "观望":
            s += swing[0]
            why.append(swing[1])
        rows.append((typ, f, who, wt, s, verdict(s), why))
    # 派里有议政之权的人，私人的分差得远就不随本派
    for o, r in council_people(C):
        h = r["holder"]
        f = C.faction_of(h)
        if not f or h == C.factions[f].get("leader") or h == m["by"]:
            continue
        fs = next((x for x in rows if x[1] == f), None)
        if not fs:
            continue
        s, why = stance(C, m, h, f, sov)
        if verdict(s) != fs[5] and abs(s - fs[4]) >= 3:
            breaks.append((h, f, C.seat_weight(h), s, verdict(s), why))
    return rows, breaks


def weigh(rows, breaks):
    w = {"附议": 0.0, "反对": 0.0, "观望": 0.0}
    for typ, f, who, wt, s, v, why in rows:
        w[v] += wt
    for h, f, wt, s, v, why in breaks:
        w[v] += wt
    return w


def print_rows(rows, breaks):
    for typ, f, who, wt, s, v, why in rows:
        label = f"{f}（{who}领，声量 {wt}）" if typ == "派" else f"{who}（重臣，分量 {wt}）"
        print(f"  {X.pad(label, 28)} {v}  分 {s:+.1f}：{'；'.join(why) or '无所谓'}")
    for h, f, wt, s, v, why in breaks:
        print(f"  {X.pad(h + '（' + f + '，不随本派）', 28)} {v}  分 {s:+.1f}：{'；'.join(why)}")


def consequences(C, m, ruling, penalty=None, office=None, false=False):
    """定夺之后的后果，返回 [(说明, 动作)]。动作是 dict，apply_ops 照着写存档。"""
    ops = []
    when = X.when_of(C.world)
    by, t = m["by"], m.get("target")
    pf, tf = C.faction_of(by), C.faction_of(t) if t else None
    src = f"court:{m['id']}"
    if m["kind"] == "弹劾":
        if ruling == "准":
            pen = penalty or m.get("ask") or "罢官"
            grudge, vloss, fs, leave = PENALTIES[pen]
            ops.append((f"{t} {pen}", {"op": "penalty", "who": t, "penalty": pen}))
            ops.append((f"{t} 记 {by} 一笔怨（{grudge}）", {"op": "deed", "holder": t, "toward": by, "kind": "怨",
                        "s": grudge, "what": f"被{by}弹劾，{pen}", "known": "公开"}))
            if tf and vloss:
                ops.append((f"{tf} 声量 −{vloss}", {"op": "voice", "faction": tf, "delta": -vloss}))
            if pf and pf != tf:
                ops.append((f"{pf} 声量 +1", {"op": "voice", "faction": pf, "delta": 1}))
            if pf and tf and pf != tf:
                ops.append((f"{pf} 与 {tf} 积怨 +{fs}", {"op": "feud", "a": pf, "b": tf, "s": fs,
                            "what": f"{by}弹劾{t}，{pen}"}))
            if pen in ("罢官", "下狱", "流放"):
                ops.append((f"{t} 的{C.d['fame_kind']}名望 −1", {"op": "fame", "who": t, "delta": -1}))
        elif ruling == "驳":
            ops.append((f"{t} 记 {by} 一笔怨（1）", {"op": "deed", "holder": t, "toward": by, "kind": "怨", "s": 1,
                        "what": f"{by}上章弹劾他，被驳回", "known": "公开"}))
            if pf:
                ops.append((f"{pf} 声量 −1", {"op": "voice", "faction": pf, "delta": -1}))
            if pf and tf and pf != tf:
                ops.append((f"{pf} 与 {tf} 积怨 +1", {"op": "feud", "a": pf, "b": tf, "s": 1, "what": f"{by}弹劾{t}未成"}))
            if false:
                pen = m.get("ask") or "罢官"
                ops.append((f"诬告反坐：{by} {pen}", {"op": "penalty", "who": by, "penalty": pen}))
                ops.append((f"{t} 记 {by} 一笔深怨（3）", {"op": "deed", "holder": t, "toward": by, "kind": "怨", "s": 3,
                            "what": f"{by}捏造罪名构陷他", "known": "公开"}))
                if pf:
                    ops.append((f"{pf} 声量再 −1", {"op": "voice", "faction": pf, "delta": -1}))
                if pf and tf and pf != tf:
                    ops.append((f"{pf} 与 {tf} 积怨 +3", {"op": "feud", "a": tf, "b": pf, "s": 3, "what": f"{by}诬告{t}，反坐"}))
                ops.append((f"{by} 的{C.d['fame_kind']}名望 −2", {"op": "fame", "who": by, "delta": -2}))
    elif m["kind"] == "举荐":
        off = office or m.get("office")
        if ruling == "准":
            ops.append((f"{t} 任 {off}", {"op": "appoint", "who": t, "office": off}))
            ops.append((f"{t} 记 {by} 一份恩（2）", {"op": "deed", "holder": t, "toward": by, "kind": "恩", "s": 2,
                        "what": f"{by}举荐他任{off}", "known": "两人"}))
            old = C.offices.get(off, {}).get("holder")
            of = C.faction_of(old) if old else None
            if old and old != t:
                ops.append((f"原任 {old} 去职（GM 另行安置）", {"op": "note", "text": f"{old} 让出 {off}"}))
                if of and tf and of != tf:
                    ops.append((f"{of} 与 {tf} 积怨 +1", {"op": "feud", "a": of, "b": tf, "s": 1,
                                "what": f"{off}一职由{old}换成{t}"}))
            if pf and tf == pf:
                ops.append((f"{pf} 声量 +1", {"op": "voice", "faction": pf, "delta": 1}))
        elif ruling == "驳":
            ops.append((f"{by} 举荐未成，{t} 仍记 {by} 一份情（1）", {"op": "deed", "holder": t, "toward": by, "kind": "恩",
                        "s": 1, "what": f"{by}举荐过他", "known": "两人"}))
    elif m["kind"] == "提议":
        iss = C.d["issues"].get(m["issue"], {})
        if ruling == "准":
            ops.append((f"议题【{iss.get('title', m['issue'])}】定为：{m['ask']}", {"op": "issue", "issue": m["issue"], "result": m["ask"]}))
            hdir = os.path.join(C.world, "households")
            for fn in (sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []):
                hh = X.load_json(hdir, fn, {}) if fn.endswith(".json") else {}
                if hh.get("succession_issue") == m["issue"]:
                    ops.append((f"宫中照此立储：household.py --house {fn[:-5]} heir <皇子id> --why \"{m['ask']}\" --apply（GM 另跑）",
                                {"op": "note", "text": "立储"}))
            for f, pos in iss.get("positions", {}).items():
                if m["ask"] == pos.get("want"):
                    ops.append((f"{f} 声量 +1（所求得遂）", {"op": "voice", "faction": f, "delta": 1}))
                elif m["ask"] in pos.get("bottom", []):
                    ops.append((f"{f} 声量 −1（底线被破）", {"op": "voice", "faction": f, "delta": -1}))
                    if pf and pf != f:
                        ops.append((f"{f} 与 {pf} 积怨 +2", {"op": "feud", "a": f, "b": pf, "s": 2,
                                    "what": f"{by}所奏“{m['ask']}”得准，破了{f}的底线"}))
                    ld = C.factions.get(f, {}).get("leader")
                    if ld and ld != by:
                        ops.append((f"{ld} 记 {by} 一笔怨（2）", {"op": "deed", "holder": ld, "toward": by, "kind": "怨",
                                    "s": 2, "what": f"{by}奏准“{m['ask']}”，破了本派的底线", "known": "公开"}))
        elif ruling == "驳":
            pos = iss.get("positions", {}).get(pf or "", {})
            if pf and pos.get("want") == m["ask"] and int(pos.get("weight", 2)) >= 3:
                ops.append((f"{pf} 声量 −1（本派最看重的事被驳）", {"op": "voice", "faction": pf, "delta": -1}))
    elif m["kind"] == "请辞":
        if ruling == "准":
            ops.append((f"{by} 致仕，{m.get('office') or '原职'}出缺", {"op": "remove", "who": by, "status": "致仕"}))
        elif ruling == "驳":
            ops.append((f"挽留：{by} 记定夺者一份情（1）", {"op": "deed", "holder": by, "toward": C.d.get("sovereign") or "定夺者",
                        "kind": "恩", "s": 1, "what": "请辞不准，温旨挽留", "known": "公开"}))
    if ruling == "留中":
        ops.append(("奏疏留中不发：什么都不改；上奏的人心里不痛快（有人格卡的，GM 可记心结 1）", {"op": "note", "text": "留中"}))
    if ruling == "折中":
        ops.append(("折中：GM 照定夺者的原话，用 appoint / remove / faction --voice-delta / feud 逐项记", {"op": "note", "text": "折中"}))
    # 仕途：小官上奏
    car = C.d["careers"].get(by)
    if car and car.get("superior"):
        sup = car["superior"]
        sf = C.faction_of(sup)
        if m.get("bypass"):
            backed = any(str(x).startswith(sf or "\0") for x in (m.get("session") or {}).get("附议", [])) or sup in (m.get("session") or {}).get("附议", [])
            if ruling == "准" and (not sf or sf == pf or backed):
                ops.append((f"越级上奏得准，{sup}{'那一派也附议了' if backed else ''}：面上不说，器重不变", {"op": "note", "text": "越级得准"}))
            else:
                ops.append((f"越级上奏：{sup} 的器重 −1", {"op": "regard", "who": by, "delta": -1, "why": f"越级上奏（{m['id']}）"}))
        if ruling == "准":
            ops.append((f"{by} 考绩 +1（所奏得准）", {"op": "merit", "who": by, "delta": 1, "why": f"{m['id']} 得准"}))
        if t and sf and C.faction_of(t) == sf and m["kind"] == "弹劾":
            ops.append((f"弹劾的是上司 {sup} 那一派的人：器重 −1", {"op": "regard", "who": by, "delta": -1,
                        "why": f"弹劾{sf}的{t}"}))
    return ops


def apply_ops(C, ops, src):
    net = C.net
    when = X.when_of(C.world)
    turn = X.turn_of(C.world)
    fame_touched = []
    for desc, op in ops:
        k = op["op"]
        if k == "deed":
            if op["holder"] == op["toward"]:
                continue
            net.add_deed(op["holder"], op["toward"], op["kind"], op["what"], op["s"], when, turn, op.get("known", "两人"), source=src)
        elif k == "voice":
            f = C.factions.get(op["faction"])
            if f is not None:
                f["voice"] = X.clamp(int(f.get("voice", 5)) + op["delta"], 0, 10)
                f.setdefault("log", []).append(f"{when}：声量 {op['delta']:+d}（{src}）")
        elif k == "feud":
            C.add_feud(op["a"], op["b"], op["what"], op["s"], when)
        elif k == "penalty":
            pen = op["penalty"]
            if PENALTIES[pen][3]:
                vacate(C, op["who"])
                C.d["out"][op["who"]] = {"status": pen, "where": op.get("where", ""), "since_turn": turn, "why": src}
            else:
                C.d["log"].append(f"{when}：{op['who']}{pen}（{src}）")
        elif k == "appoint":
            appoint(C, op["who"], op["office"], why=src)
        elif k == "remove":
            vacate(C, op["who"])
            C.d["out"][op["who"]] = {"status": op["status"], "where": "", "since_turn": turn, "why": src}
        elif k == "issue":
            iss = C.d["issues"][op["issue"]]
            iss["status"] = f"已决：{op['result']}"
            iss.setdefault("log", []).append(f"{when}：定为{op['result']}（{src}）")
        elif k == "regard":
            car = C.d["careers"][op["who"]]
            car["regard"] = X.clamp(int(car.get("regard", 0)) + op["delta"], -3, 3)
            car.setdefault("log", []).append(f"{when}：器重 {op['delta']:+d}，{op['why']}")
        elif k == "merit":
            car = C.d["careers"][op["who"]]
            car["merit"] = int(car.get("merit", 0)) + op["delta"]
            car.setdefault("log", []).append(f"{when}：考绩 {op['delta']:+d}，{op['why']}")
        elif k == "fame":
            fame_touched.append((op["who"], op["delta"]))
    net.save()
    for who, delta in fame_touched:
        f = C.people.fame(who)
        kind = C.d.get("fame_kind", "士林")
        f[kind] = X.clamp(f.get(kind, X.FAME_DEFAULT) + delta, 0, 10)
        where = C.people.set_fame(who, f)
        print(f"  名望：{who} {kind} {delta:+d} → {f[kind]}" + (f"（写入 {where}）" if where else "（不在卡和名册里，没处记）"))


def vacate(C, who):
    for o, r in C.offices.items():
        if r.get("holder") == who:
            r["holder"] = None
            r.setdefault("log", []).append(f"{X.when_of(C.world)}：{who} 去职")


def appoint(C, who, office, rank=None, council=None, why=""):
    r = C.offices.get(office)
    if r is None:
        if rank is None:
            X.die(f"没有官职“{office}”。新设的官职要给 --rank（1–9）")
        r = C.offices[office] = {"rank": rank, "holder": None, "council": bool(council), "log": []}
    if rank is not None:
        r["rank"] = rank
    if council is not None:
        r["council"] = bool(council)
    old = r.get("holder")
    vacate(C, who)
    r["holder"] = who
    r.setdefault("log", []).append(f"{X.when_of(C.world)}：{who} 任职" + (f"（{why}）" if why else ""))
    C.d["out"].pop(who, None)
    car = C.d["careers"].get(who)
    if car:
        car["post"] = office
    return old


def cmd_session(C, args):
    m = C.memorial(args.id)
    if m["status"] not in ("待议", "已议") and not args.force:
        X.die(f"奏疏 {m['id']} 已经{m['status']}")
    if args.apply and m["status"] == "已议" and not args.force:
        X.die(f"奏疏 {m['id']} 已经朝议过、记过账了。只想再看一遍就去掉 --apply；确要重议再记一次账，加 --force")
    sov = lean_of(C, m, (args.lean, args.signal or "未露") if args.lean else None)
    print(f"=== 朝议：{m['id']} {m['by']}{m['kind']}" + (f" {m.get('target')}" if m.get("target") else "")
          + f"，所请“{m.get('ask')}”（{m['when']}） ===")
    print(f"  奏疏：{m['text']}")
    print(f"  圣意（GM 才知道）：{sov[0] or '未定'}，{sov[1]}")
    rows, breaks = tally(C, m, sov)
    print("--- 各方初议 ---")
    print_rows(rows, breaks)
    w = weigh(rows, breaks)
    print(f"  合计：附议 {w['附议']:.1f}，反对 {w['反对']:.1f}，观望 {w['观望']:.1f}")
    debate = None
    if args.debate or (args.auto_debate and w["附议"] > 0 and w["反对"] > 0):
        if args.debate:
            a, _, b = args.debate.partition(":")
        else:
            a = m["by"]
            opp = [x[2] for x in rows if x[5] == "反对"] + [x[0] for x in breaks if x[4] == "反对"]
            for x in rows:
                if x[5] == "反对" and x[0] == "派":
                    opp += [n for n in C.factions[x[1]].get("members", []) if C.office_of(n)[0]]
            b = best_speaker(C, opp)
        if not b:
            X.die("找不到反对一方出来辩的人，用 --debate 甲:乙 指定")
        judge = None
        fav = lean_favors(m, sov[0])
        if fav > 0:
            judge = "A"
        elif fav < 0:
            judge = "B"
        crowd = "A" if w["附议"] > w["反对"] + 2 else "B" if w["反对"] > w["附议"] + 2 else None
        import contest as K
        seed = args.seed if args.seed is not None else random.randrange(1, 10 ** 6)
        W, bt, res, cons = K.run_debate(C.world, a, b, seed, occasion="朝堂", judge=judge, crowd=crowd,
                                        point_a=args.point_a or 0, point_b=args.point_b or 0,
                                        style_a=args.style_a, style_b=args.style_b, cite_a=args.cite_a, cite_b=args.cite_b)
        print(f"--- 廷辩：{a} 对 {b}（seed={seed}；主事者偏向 {judge or '无'}，在场的人偏向 {crowd or '无'}） ---")
        print(f"  {a}：打法“{bt.A.style}”，论点分 {args.point_a or 0:+d}；{b}：打法“{bt.B.style}”，论点分 {args.point_b or 0:+d}")
        for l in bt.lines:
            print(f"  {l}")
        print(f"  结果：{res['outcome']}")
        debate = {"a": a, "b": b, "seed": seed, "code": res["code"], "outcome": res["outcome"],
                  "winner": (a if res.get("winner") == "A" else b if res.get("winner") == "B" else None),
                  "lean": res.get("lean")}
        wside = res.get("winner") or res.get("lean")
        swing = None
        if wside == "A":
            swing = (1.0, f"廷辩{a}占了上风 +1")
        elif wside == "B":
            swing = (-1.0, f"廷辩{b}占了上风 −1")
        if swing:
            rows, breaks = tally(C, m, sov, swing)
            if res["code"] == "说服" and res.get("winner") == "A":
                bf = C.faction_of(b)
                rows = [(t, f, who, wt, s + 1.5, verdict(s + 1.5), why + [f"{b}被说服，本派松口 +1.5"]) if f == bf and f
                        else (t, f, who, wt, s, v, why) for t, f, who, wt, s, v, why in rows]
            print("--- 廷辩之后 ---")
            print_rows(rows, breaks)
            w = weigh(rows, breaks)
            print(f"  合计：附议 {w['附议']:.1f}，反对 {w['反对']:.1f}，观望 {w['观望']:.1f}")
        debate["cons"] = cons
    # 给定夺者的意见汇总
    sup = [x[2] if x[0] == "臣" else f"{x[1]}（{x[2]}）" for x in rows if x[5] == "附议"] + [x[0] for x in breaks if x[4] == "附议"]
    opp = [x[2] if x[0] == "臣" else f"{x[1]}（{x[2]}）" for x in rows if x[5] == "反对"] + [x[0] for x in breaks if x[4] == "反对"]
    mid = [x[2] if x[0] == "臣" else f"{x[1]}（{x[2]}）" for x in rows if x[5] == "观望"] + [x[0] for x in breaks if x[4] == "观望"]
    total = w["附议"] + w["反对"] + w["观望"] or 1
    print("\n--- 各方意见汇总（写进定夺者 ruler agent 的 prompt；不写圣意、不写分数） ---")
    print(f"  {m['by']}（{C.post_of(m['by']) or '无官'}）上奏{m['kind']}" + (f"{m.get('target')}" if m.get("target") else "")
          + f"，请{m.get('ask')}。原话：{m['text']}")
    print(f"  附议：{'、'.join(sup) or '无'}；反对：{'、'.join(opp) or '无'}；观望：{'、'.join(mid) or '无'}")
    if debate:
        print(f"  廷辩：{debate['a']}与{debate['b']}当殿辩论，{debate['outcome']}。")
    print(f"  朝议所向：附议约占{w['附议'] / total:.0%}，反对约占{w['反对'] / total:.0%}。")
    print("--- 建议提示（给 GM：各种定夺的后果） ---")
    for r in ("准", "驳", "留中"):
        ops = consequences(C, m, r)
        print(f"  若{r}：" + ("；".join(d for d, _ in ops) or "没有什么变化"))
    print("  定夺者看重什么、偏向哪边，由 ruler agent 读他自己的人格卡决定；GM 照 decide 记。"
          "群议和圣意相左时，强行定夺的，GM 可给输的一方首领记心结或怨（rules/court.md 第四节）。")
    if args.apply:
        m["status"] = "已议"
        m["session"] = {"turn": X.turn_of(C.world), "附议": sup, "反对": opp, "观望": mid,
                        "weights": {k: round(v, 1) for k, v in w.items()},
                        "debate": {k: v for k, v in (debate or {}).items() if k != "cons"} or None}
        if debate:
            cons = debate["cons"]
            K.apply(W, bt, res, cons)
            if res.get("winner") and res["code"] in ("驳倒", "恼羞成怒"):
                win = debate["winner"]
                lose = b if win == a else a
                C.net.add_deed(lose, win, "怨", f"廷辩上被{win}当众{'驳倒' if res['code'] == '驳倒' else '驳得下不来台'}（{m['id']}）",
                               2 if res["code"] == "恼羞成怒" else 1,
                               X.when_of(C.world), X.turn_of(C.world), "公开", source=f"court:{m['id']}")
                C.net.save()
                print(f"  关系网：{lose} 记 {win} 一笔怨")
            fk = C.d.get("fame_kind", "士林")
            if res.get("winner") and res["code"] in ("说服", "驳倒", "恼羞成怒"):
                win = debate["winner"]
                lose = b if win == a else a
                for who, dl in ((win, 1), (lose, -1 if res["code"] == "恼羞成怒" else 0)):
                    if dl:
                        f = C.people.fame(who)
                        f[fk] = X.clamp(f.get(fk, X.FAME_DEFAULT) + dl, 0, 10)
                        C.people.set_fame(who, f)
                        print(f"  名望：{who} {fk} {dl:+d} → {f[fk]}")
    finish(C, args)


def cmd_decide(C, args):
    m = C.memorial(args.id)
    if m["status"] in ("已准", "已驳", "留中", "折中") and not args.force:
        X.die(f"奏疏 {m['id']} 已经定夺（{m['status']}）")
    if m["status"] == "待议" and not args.force:
        print("注：这道奏疏还没有朝议（session）。小事可以不经朝议直接定夺；大事先跑 session。")
    if args.penalty and args.penalty not in PENALTIES:
        X.die(f"--penalty 只能是 {'/'.join(PENALTIES)}")
    ops = consequences(C, m, args.ruling, args.penalty, args.office, args.false)
    for _, op in ops:
        if op["op"] == "penalty" and args.where:
            op["where"] = args.where
    print(f"=== 定夺：{m['id']} {m['by']}{m['kind']}" + (f" {m.get('target')}" if m.get("target") else "")
          + f" → {args.ruling}" + (f"（{args.penalty}）" if args.penalty else "") + f"；定夺者 {args.by or C.d.get('sovereign') or '?'} ===")
    if args.note:
        print(f"  原话：{args.note}")
    for d, op in ops:
        print(f"  · {d}")
    # 有人格卡的人：建议记心结、触发事件
    for d, op in ops:
        if op["op"] == "penalty":
            who = op["who"]
            cp = C.people.card_path(who)
            if cp and C.people.role(who) == "主角":
                print(f"  {who} 是主角：没有账本，处分照实写进汇报；他的官职、器重照上面改")
            elif cp:
                s = {"申饬": 1, "罚俸": 1, "降职": 2, "外放": 2}.get(op["penalty"], 3)
                cause = f"因{m['by']}所劾，{op['penalty']}" if who != m["by"] else f"诬告反坐，{op['penalty']}"
                print(f"  人心账本（建议）：python3 scripts/loyalty.py grudge {X.rel(cp)} --when <本季> "
                      f"--what \"{cause}\" --strength {s} --heard 幕僚可闻 --apply"
                      f"（心结记的是对定夺者、所事之人的；对{m['by']}的怨上面已记进关系网，不要再加 --toward）")
                if op["penalty"] in ("罢官", "下狱", "流放"):
                    print(f"    季末 court.py season 带 --trigger {who}=罢官下狱" + ("（下狱的再加 性命之危）" if op["penalty"] == "下狱" else ""))
    if args.apply:
        m["status"] = {"准": "已准", "驳": "已驳", "留中": "留中", "折中": "折中"}[args.ruling]
        m["ruling"] = {"ruling": args.ruling, "penalty": args.penalty, "by": args.by or C.d.get("sovereign"),
                       "note": args.note or "", "turn": X.turn_of(C.world), "false": bool(args.false)}
        apply_ops(C, ops, f"court:{m['id']}")
    finish(C, args, "（关系网一并写入）" if args.apply else "")


# ---------------------------------------------------------------- 任免、派系、议题、党争

def cmd_appoint(C, args):
    old = appoint(C, args.name, args.office, args.rank, True if args.council else None, args.why or "")
    r = C.offices[args.office]
    print(f"{args.name} 任 {args.office}（{r['rank']}品{'，有议政之权' if r.get('council') else ''}）" + (f"；原任 {old} 去职" if old and old != args.name else ""))
    if old and old != args.name:
        print(f"  {old} 另行安置：appoint 或 remove。他若因此失意，GM 照 relations.py event 抢功 记一笔（谁顶了他）。")
    finish(C, args)


def cmd_remove(C, args):
    if args.status not in OUT_STATUS:
        X.die(f"--status 只能是 {'/'.join(OUT_STATUS)}")
    o, r = C.office_of(args.name)
    vacate(C, args.name)
    C.d["out"][args.name] = {"status": args.status, "where": args.where or "", "since_turn": X.turn_of(C.world), "why": args.why}
    print(f"{args.name} {args.status}" + (f"于{args.where}" if args.where else "") + (f"，{o} 出缺" if o else "") + f"（{args.why}）")
    if args.status in ("罢官", "下狱", "流放"):
        print(f"  季末 court.py season 带 --trigger {args.name}=罢官下狱；有人格卡的照 loyalty.py grudge 记心结。")
    finish(C, args)


def cmd_faction(C, args):
    f = C.factions.get(args.name)
    if args.new:
        if f:
            X.die(f"已经有“{args.name}”了")
        f = C.factions[args.name] = {"leader": args.leader, "members": [args.leader] if args.leader else [], "voice": args.voice or 4,
                                     "stance": args.stance or "", "log": []}
        print(f"新立派系“{args.name}”，首领 {args.leader}，声量 {f['voice']}")
    elif not f:
        X.die(f"没有派系“{args.name}”（有：{'、'.join(C.factions) or '无'}）")
    for n in X.split_names(args.join):
        old = C.faction_of(n)
        if old and old != args.name:
            C.factions[old]["members"].remove(n)
            print(f"  {n} 离开 {old}")
        if n not in f["members"]:
            f["members"].append(n)
            print(f"  {n} 加入 {args.name}")
    for n in X.split_names(args.leave):
        if n in f["members"]:
            f["members"].remove(n)
            print(f"  {n} 离开 {args.name}")
    if args.leader and not args.new:
        f["leader"] = args.leader
        if args.leader not in f["members"]:
            f["members"].append(args.leader)
        print(f"  首领改为 {args.leader}")
    if args.voice_delta:
        if not args.why:
            X.die("改声量要写 --why")
        old = f.get("voice", 5)
        f["voice"] = X.clamp(old + args.voice_delta, 0, 10)
        f.setdefault("log", []).append(f"{X.when_of(C.world)}：声量 {old} → {f['voice']}（{args.why}）")
        print(f"  声量 {old} → {f['voice']}（{args.why}）")
    if args.stance and not args.new:
        f["stance"] = args.stance
    finish(C, args)


def cmd_issue(C, args):
    iss = C.d["issues"].setdefault(args.name, {"title": args.name, "status": "悬而未决", "options": [], "sovereign": {},
                                               "positions": {}, "log": []})
    if args.title:
        iss["title"] = args.title
    if args.options:
        iss["options"] = X.split_names(args.options)
    if args.lean is not None:
        iss.setdefault("sovereign", {})["lean"] = args.lean
    if args.signal:
        iss.setdefault("sovereign", {})["signal"] = args.signal
    if args.status:
        iss["status"] = args.status
    print(f"议题【{iss['title']}】{iss['status']}；可选：{'、'.join(iss['options'])}；"
          f"圣意（GM）：{iss.get('sovereign', {}).get('lean') or '未定'}（{iss.get('sovereign', {}).get('signal', '未露')}）")
    finish(C, args)


def cmd_position(C, args):
    if args.faction not in C.factions:
        X.die(f"没有派系“{args.faction}”")
    iss = C.d["issues"].get(args.issue)
    if not iss:
        X.die(f"没有议题“{args.issue}”")
    p = iss["positions"].setdefault(args.faction, {"want": None, "accept": [], "bottom": [], "weight": 2})
    if args.want:
        p["want"] = args.want
    if args.accept is not None:
        p["accept"] = X.split_names(args.accept)
    if args.bottom is not None:
        p["bottom"] = X.split_names(args.bottom)
    if args.bottom_text:
        p["bottom_text"] = args.bottom_text
    if args.weight:
        p["weight"] = args.weight
    print(f"{args.faction} 对【{iss['title']}】：要 {p['want']}；可接受 {'、'.join(p['accept']) or '—'}；底线 {'、'.join(p['bottom']) or '—'}；看重 {p['weight']}")
    finish(C, args)


def cmd_feud(C, args):
    for f in (args.a, args.b):
        if f not in C.factions:
            X.die(f"没有派系“{f}”")
    e = C.add_feud(args.a, args.b, args.what, args.strength, X.when_of(C.world, args.when))
    f = C.feud(args.a, args.b)
    print(f"{args.a} 与 {args.b} 积怨 [{e['id']}] {args.what}（{args.strength}）；积怨合计 {feud_heat(f)}，眼下 {f['level']}（季末推进）")
    finish(C, args)


# ---------------------------------------------------------------- 仕途

def cmd_career(C, args):
    car = C.d["careers"].setdefault(args.name, {"post": None, "superior": None, "regard": 0, "merit": 0, "duty": None,
                                                "since_turn": X.turn_of(C.world), "log": []})
    if args.post:
        car["post"] = args.post
    if args.superior:
        car["superior"] = args.superior
    if args.ladder:
        C.ladder(args.ladder)
        car["ladder"] = args.ladder
    if args.duty:
        car["duty"] = {"what": args.duty, "due_turn": args.due or X.turn_of(C.world) + 1, "given_turn": X.turn_of(C.world)}
    if args.regard is not None:
        car["regard"] = X.clamp(args.regard, -3, 3)
    print(f"{args.name}：{car['post']}，上司 {car['superior']}，器重 {regard_word(car['regard'])}（{car['regard']:+d}），考绩 {car['merit']}"
          + (f"；差事：{car['duty']['what']}（第 {car['duty']['due_turn']} 回合前回报）" if car.get("duty") else ""))
    finish(C, args)


def cmd_ladder(C, args):
    lads = C.d.get("ladders", {})
    if not lads:
        print("court.json 里没有仕途阶梯（ladders）。官职表见 show。")
        return
    for lname, lad in lads.items():
        if args.name and lname != args.name:
            continue
        print(f"=== 仕途阶梯：{lname}（俸钱单位 {lad.get('unit', '剧本的钱')}） ===")
        if lad.get("note"):
            print(f"  {lad['note']}")
        on = {}
        for n, car in C.d["careers"].items():
            if car.get("ladder") == lname:
                on.setdefault(C.post_of(n), []).append(n)
        for i, r in enumerate(lad.get("rungs", []), 1):
            who = on.get(r["post"], [])
            if r.get("office"):
                h = C.offices.get(r["post"], {}).get("holder")
                who = who or ([h] if h else [])
            print(f"  {i:>2}. {rung_text(r)}" + (f"：{r['duty']}" if r.get("duty") else "") + (f"  ← {'、'.join(who)}" if who else ""))


def cmd_promote(C, args):
    car = C.d["careers"].get(args.name) or X.die(f"{args.name} 没有仕途记录，先用 career 建（--ladder 阶梯）")
    lname, i, rung = C.ladder_pos(args.name)
    if not lname:
        X.die(f"{args.name} 的仕途没记阶梯（career {args.name} --ladder 阶梯名），升官职用 appoint")
    rungs = C.ladder(lname)["rungs"]
    if args.to:
        j = next((k for k, r in enumerate(rungs) if r["post"] == args.to), None)
        if j is None:
            X.die(f"阶梯“{lname}”里没有“{args.to}”（有：{'、'.join(r['post'] for r in rungs)}）")
    else:
        if i is None:
            X.die(f"{args.name} 眼下的职“{C.post_of(args.name)}”不在阶梯上，用 --to 指定回到哪一阶")
        j = i - 1 if args.down else i + 1
        if not 0 <= j < len(rungs):
            X.die("已经在阶梯的" + ("最底下" if args.down else "最上面") + "了")
    new = rungs[j]
    old_post = C.post_of(args.name)
    if new.get("office"):
        prev = appoint(C, args.name, new["post"], rank=new.get("rank"), why=args.why)
        if prev and prev != args.name:
            print(f"  原任 {new['post']} 的 {prev} 去职，GM 另行安置")
    else:
        vacate(C, args.name)
        car["post"] = new["post"]
    up = i is None or j > i
    car["post_since_turn"] = X.turn_of(C.world)
    car.setdefault("log", []).append(f"{X.when_of(C.world)}：{old_post} → {new['post']}（{'升' if up else '降'}），{args.why}")
    print(f"{args.name}：{old_post} → {rung_text(new)}（{args.why}）")
    if new.get("duty"):
        print(f"  这一阶管：{new['duty']}")
    if up:
        print(f"  升阶多半有人说了话：上司或举荐的人，GM 照实记 relations.py event 提携 --by 某人 --to {args.name} --apply")
        print(f"  上司换不换人：career {args.name} --superior 新上司 --apply")
    else:
        print(f"  降阶算一次处分：有人格卡的照 rules/court.md 第六节记心结；同僚看在眼里，名望可以照 rumors.py fame 记")
    finish(C, args)


def cmd_regard(C, args):
    car = C.d["careers"].get(args.name) or X.die(f"{args.name} 没有仕途记录，先用 career 建")
    delta = args.delta
    why = args.why
    if args.event:
        if args.event not in REGARD_EVENTS:
            X.die(f"--event 只有 {'、'.join(REGARD_EVENTS)}")
        d0, w0 = REGARD_EVENTS[args.event]
        delta = d0 if delta is None else delta
        why = why or w0
    if delta is None or not why:
        X.die("给 --event，或者 --delta 加 --why")
    old = car.get("regard", 0)
    car["regard"] = X.clamp(old + delta, -3, 3)
    car.setdefault("log", []).append(f"{X.when_of(C.world)}：器重 {old:+d} → {car['regard']:+d}，{why}")
    print(f"{car.get('superior')} 对 {args.name}：{regard_word(old)} → {regard_word(car['regard'])}（{why}）")
    if args.event == "顶撞":
        print(f"  关系网：relations.py event 羞辱 --by {args.name} --to {car.get('superior')} --strength 1 --apply（他记一笔小怨）")
    if args.event == "担责":
        print(f"  关系网：relations.py event 援手 --by {args.name} --to {car.get('superior')} --apply（他欠一份情）")
    finish(C, args)


def cmd_duty(C, args):
    car = C.d["careers"].get(args.name) or X.die(f"{args.name} 没有仕途记录")
    d = DUTY[args.result]
    car["merit"] = int(car.get("merit", 0)) + d
    ev = {"上": "办得出色", "中": "办成差事", "下": "办砸", "误事": "误事"}[args.result]
    rd = REGARD_EVENTS[ev][0]
    old = car.get("regard", 0)
    car["regard"] = X.clamp(old + rd, -3, 3)
    car.setdefault("log", []).append(f"{X.when_of(C.world)}：差事“{args.what}”{args.result}，考绩 {d:+d}，器重 {rd:+d}")
    car["duty"] = None
    print(f"{args.name} 的差事“{args.what}”：{args.result}。考绩 {d:+d} → {car['merit']}；"
          f"{car.get('superior')} 的器重 {regard_word(old)} → {regard_word(car['regard'])}")
    finish(C, args)


# ---------------------------------------------------------------- 朝臣的心迹

def court_cards(C):
    import loyalty as L
    out = []
    for name, path in C.people.W.card_files().items():
        with open(path, encoding="utf-8") as f:
            y = C.people.P.read_yaml(f.read()) or {}
        if y.get("身份") in X.COURT_ROLES:
            out.append(L.Card(path))
    return out


def mind_level(card):
    lv = card.yaml.get("心迹", "恭谨")
    if lv not in MIND_LEVELS:
        X.die(f"{card.path} 的“心迹”应为 {'/'.join(MIND_LEVELS)}：{lv!r}")
    return lv


def mind_target(card, triggers):
    import loyalty as L
    P = L.pressure(card)
    gap = L.gap(card)
    x = P + gap
    base = 0 if x < 4 else 1 if x < 6 else 2 if x < 8 else 3
    why = [f"怨望分 {x:.1f}（未解心结 {P} + 需求缺口 {gap:.1f}）→ {MIND_LEVELS[base]}"]
    cap = 1 if P == 0 else 2
    if P >= 3 and (card.ties or triggers):
        cap = 3
    if base > cap:
        why.append("没有未解的心结：最多“怠慢”" if cap == 1 else
                   (f"未解心结只有 {P}：最多“怨望”" if P < 3 else "心结够深，但外头没人牵扯、本季也没有触发事件：最多“怨望”"))
        base = cap
    if triggers:
        why.append(f"触发：{'、'.join(triggers)}")
    return base, why


def courtier_hint(C, name):
    """写进 courtier agent prompt 的“朝中提示”：心迹和行动上限、党争的上限、器重。只给 GM 和这个人。"""
    parts = []
    cp = C.people.card_path(name)
    if cp:
        import loyalty as L
        card = L.Card(cp)
        if card.role in X.COURT_ROLES:
            lv = mind_level(card)
            parts.append(f"心迹：{lv}。行动上限：{MIND_CEILING[lv]}")
            if card.ties:
                parts.append(f"外头的牵扯：{'；'.join(card.ties)}")
    f = C.faction_of(name)
    if f:
        lines = []
        for g in C.factions:
            if g == f:
                continue
            lv = C.feud_level(f, g)
            if lv:
                lines.append(f"对{g}：{FEUD_LEVELS[lv]}——{FEUD_CEILING[FEUD_LEVELS[lv]]}")
        parts.append(f"你在{f}" + ("。" + "；".join(lines) if lines else "，眼下和各派相安：" + FEUD_CEILING["相安"]))
    car = C.d["careers"].get(name)
    if car:
        parts.append(f"上司 {car.get('superior')} 对你{regard_word(car.get('regard', 0))}")
    for k, v in C.d["careers"].items():
        if v.get("superior") == name:
            parts.append(f"你手下的 {k}，你对他{regard_word(v.get('regard', 0))}")
    return "。".join(x.rstrip("。") for x in parts) + "。" if parts else "（不在朝中各派里，也没有账本：按人格卡行事）"


def cmd_hint(C, args):
    name = args.name
    print(f"=== 朝中提示：{name}（{C.post_of(name) or '无官'}） ===")
    cp = C.people.card_path(name)
    if cp:
        import loyalty as L
        card = L.Card(cp)
        L.print_ledger(card)
        if card.role in X.COURT_ROLES:
            print("\n本级可观察的迹象（GM 经旁人透露）：")
            for s in MIND_SIGNS[mind_level(card)]:
                print(f"  · {s}")
    print("\n写进 courtier agent prompt 的朝中提示：")
    print("  " + courtier_hint(C, name))
    print(f"\n情报包另跑：python3 scripts/secrets.py brief {name} --with <在场的人>")


# ---------------------------------------------------------------- 季末

def seat_root(C, f):
    r = C.factions[f]
    s = sum(C.seat_weight(n) for n in r.get("members", []))
    root = X.clamp(round(s), 1, 10)
    if r.get("leader") and C.fame(r["leader"]) >= 7:
        root = min(10, root + 1)
    return root


def feud_target(C, key, f):
    net = C.net
    heat = feud_heat(f)
    base = 0 if heat < 2 else 1 if heat < 4 else 2 if heat < 7 else 3 if heat < 10 else 4
    why = [f"积怨 {heat} → {FEUD_LEVELS[base]}"]
    a, b = key.split("|")
    ma = C.factions.get(a, {}).get("members", [])
    mb = C.factions.get(b, {}).get("members", [])
    personal = [x for x in net.deeds() if x["kind"] == "怨" and x["s"] >= 2 and
                ((x["holder"] in ma and x["toward"] in mb) or (x["holder"] in mb and x["toward"] in ma))]
    cap = 4
    if not personal:
        cap = 2
    elif not any(e["s"] >= 3 and e["status"] == "未了" for e in f["entries"]):
        cap = 3
    if base > cap:
        why.append("两派的人之间还没有记着私仇（关系网里 ≥2 的怨）：最多“攻讦”" if cap == 2 else
                   "还没出过罢官下狱一级的事（积怨里强度 3 的一条）：最多“罗织”")
        base = cap
    if personal:
        why.append("私仇：" + "；".join(f"{x['holder']}恨{x['toward']}（{x['s']}）" for x in personal[:3]))
    return base, why


def cmd_season(C, args):
    turn = X.turn_of(C.world)
    if C.d.get("last_season_turn") == turn and not args.force:
        X.die(f"第 {turn} 回合的朝廷已经推进过。确要重跑加 --force")
    when = X.when_of(C.world, args.when)
    print(f"=== 朝廷季末：{when}（第 {turn} 回合） ===")
    notes_player = []
    # 1. 党争
    print("--- 党争 ---")
    for key, f in C.d["feuds"].items():
        faded = []
        for e in f["entries"]:
            if e["status"] != "未了":
                continue
            e["age"] += 1
            if e["s"] == 1 and e["age"] >= 4:
                e["status"] = "已淡（四季无事）"
                faded.append(f"[{e['id']}] 淡了")
            elif e["s"] == 2 and e["age"] >= 8:
                e["s"], e["age"] = 1, 0
                faded.append(f"[{e['id']}] 降为 1")
        t, why = feud_target(C, key, f)
        cur = FEUD_LEVELS.index(f["level"])
        new = cur + (1 if t > cur else -1 if t < cur else 0)
        f["level"] = FEUD_LEVELS[new]
        f["log"].append(f"{when}：{FEUD_LEVELS[cur]} → {FEUD_LEVELS[new]}｜积怨 {feud_heat(f)}")
        print(f"  {key.replace('|', ' 与 ')}：{'；'.join(why)}；上季“{FEUD_LEVELS[cur]}” → 本季【{FEUD_LEVELS[new]}】"
              + (f"（{'，'.join(faded)}）" if faded else ""))
        print(f"      上限：{FEUD_CEILING[FEUD_LEVELS[new]]}")
        if new >= 1:
            notes_player.append(f"{key.replace('|', '与')}（{FEUD_LEVELS[new]}）：{FEUD_SIGNS[FEUD_LEVELS[new]][turn % len(FEUD_SIGNS[FEUD_LEVELS[new]])]}")
    if not C.d["feuds"]:
        print("  （各派之间还没有积怨）")
    # 2. 声量
    print("--- 声量（每季向根基靠一步） ---")
    for name, f in C.factions.items():
        root = seat_root(C, name)
        old = int(f.get("voice", 5))
        new = old + (1 if root > old else -1 if root < old else 0)
        f["voice"] = new
        print(f"  {X.pad(name, 10)} 根基 {root}（在朝的位子{'，首领名重 +1' if C.fame(f.get('leader') or '') >= 7 else ''}）；声量 {old} → {new}")
    # 3. 朝臣的心迹
    print("--- 朝臣的心迹（有人格卡的文臣、宫人、皇子、后妃……） ---")
    import loyalty as L
    trig = {}
    for t in args.trigger:
        n, _, e = t.partition("=")
        if e not in MIND_TRIGGERS:
            X.die(f"触发事件只有：{'、'.join(MIND_TRIGGERS)}")
        trig.setdefault(n, []).append(e)
    cards = court_cards(C)
    for card in cards:
        cur = MIND_LEVELS.index(mind_level(card))
        t, why = mind_target(card, trig.get(card.name, []))
        new = L.step(cur, t)
        faded = L.fade(card)
        card.log.append(f"{when}：{MIND_LEVELS[cur]} → {MIND_LEVELS[new]}｜心结 {L.pressure(card)}｜缺口 {L.gap(card):.1f}"
                        + (f"｜触发 {'、'.join(trig.get(card.name, []))}" if trig.get(card.name) else ""))
        card.set_yaml("心迹", MIND_LEVELS[new])
        print(f"  {card.name}（{card.role}）：{'；'.join(why)}；上季“{MIND_LEVELS[cur]}” → 本季【{MIND_LEVELS[new]}】"
              + (f"；{'；'.join(faded)}" if faded else ""))
        if new >= 1:
            notes_player.append(f"{card.name}（{MIND_LEVELS[new]}）：{MIND_SIGNS[MIND_LEVELS[new]][turn % len(MIND_SIGNS[MIND_LEVELS[new]])]}")
        if args.apply:
            card.save()
    if not cards:
        print("  （没有朝臣的人格卡）")
    # 4. 仕途
    print("--- 仕途 ---")
    sc = X.load_json(C.world, "scenario.json", {}) if os.path.exists(os.path.join(C.world, "scenario.json")) else {}
    hero = sc.get("player", {}).get("protagonist")
    is_vassal = sc.get("player", {}).get("role") == "臣子"
    pay = 0
    for name, car in C.d["careers"].items():
        line = f"  {name}：{car.get('post')}，上司 {car.get('superior')}，器重 {regard_word(car.get('regard', 0))}，考绩 {car.get('merit', 0)}"
        if car.get("duty") and car["duty"].get("due_turn", 99999) <= turn:
            line += f"；差事“{car['duty']['what']}”到期，要回报（duty --result）"
        print(line)
        since = int(car.get("review_turn", car.get("since_turn", 1)))
        if turn - since + 1 >= int(C.d.get("review_every", 4)):
            mr, rg = int(car.get("merit", 0)), int(car.get("regard", 0))
            if mr >= 3 and rg >= 1:
                lname, li, lr = C.ladder_pos(name)
                rungs = C.ladder(lname)["rungs"] if lname else []
                nxt = rungs[li + 1] if li is not None and li + 1 < len(rungs) else None
                res = ("上考：可升一阶。上司愿意举荐（memorial --kind 举荐），或照资叙迁（appoint）"
                       + (f"；阶梯上的下一阶是 {rung_text(nxt)}：court.py promote {name} --why …" if nxt else ""))
            elif mr >= 3:
                res = "功劳够了，上司却不报：要升，得另找门路（relations.py path）"
            elif mr <= -2 or rg <= -2:
                res = "下考：左迁或外放（remove --status 外放），GM 照上司的意思定"
            else:
                res = "中考：照旧"
            print(f"      考课（每 {C.d.get('review_every', 4)} 季一次）：{res}")
            car["review_turn"] = turn + 1
            car.setdefault("log", []).append(f"{when}：考课，考绩 {mr}，器重 {rg:+d} → {res.split('：')[0]}")
            car["merit"] = 0
        if name == hero and is_vassal:
            big, why = salary(C, name)
            if big:
                pay = big
                dest = "purse.json 的随身钱（scripts/purse.py，罚俸照扣）" if os.path.exists(os.path.join(C.world, "purse.json")) else "kingdom.json 的家财"
                print(f"      俸禄：{why}，本季 {big:g}（主角不是一方之主，俸禄进{dest}；加 --pay 写入）")
            elif why:
                print(f"      俸禄：{why}")
    if not C.d["careers"]:
        print("  （没有记仕途的人）")
    # 5. 不在朝的
    for n, v in C.d["out"].items():
        if v["status"] in ("外放", "丁忧") and turn - int(v.get("since_turn", turn)) >= 8:
            print(f"  {n} {v['status']}已满八季，可议召还（举荐、appoint）")
    if notes_player:
        print("\n可以经旁人透露给玩家的迹象（择一两条；从关系网里找一个玩家熟的人带出来）：")
        for n in notes_player:
            print(f"  · {n}")
    C.d["last_season_turn"] = turn
    if args.apply and args.pay and pay:
        if os.path.exists(os.path.join(C.world, "purse.json")):
            import purse as PU
            P = PU.Purse(C.world)
            if P.has(hero):
                print()
                PU.pay_one(P, hero)
                P.save()
            else:
                print(f"\n俸禄没发：purse.json 里没有 {hero}（purse.py open {hero}）")
        else:
            k = X.kingdom(C.world)
            k.setdefault("treasury", {})["money"] = int(k["treasury"].get("money", 0)) + int(round(pay))
            X.save_json(C.world, "kingdom.json", k)
            print(f"\n俸禄 {pay:g} 已进 kingdom.json 的家财。")
    finish(C, args, f"（和 {len(cards)} 张人格卡）" if cards and args.apply else "")


# ---------------------------------------------------------------- 主程序

def main():
    ap = argparse.ArgumentParser(description="派系与朝议（规则见 rules/court.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=X.DEFAULT_WORLD)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn, write=True):
        p = sp.add_parser(name, help=help_)
        p.add_argument("--world", default=argparse.SUPPRESS)
        if write:
            p.add_argument("--apply", action="store_true")
        p.set_defaults(fn=fn)
        return p

    p = add("show", "总览", cmd_show, write=False)
    p.add_argument("--faction")
    p.add_argument("--issue")
    p.add_argument("--person")
    p = add("memorial", "上一道奏疏", cmd_memorial)
    p.add_argument("--by", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--issue")
    p.add_argument("--ask")
    p.add_argument("--target")
    p.add_argument("--penalty", choices=tuple(PENALTIES))
    p.add_argument("--office")
    p.add_argument("--text", required=True)
    p.add_argument("--point", type=int, choices=(-1, 0, 1, 2))
    p.add_argument("--evidence", help="拿出来的凭据：证据编号（secrets.py 的 E…）、人证名字，逗号分隔")
    p.add_argument("--cite", help="引用的文献：编号=得当|牵强|失当")
    p.add_argument("--co", help="联名的人")
    p.add_argument("--bypass", action="store_true", help="越过上司直接上奏")
    p.add_argument("--fabricated", action="store_true", help="弹章里有捏造的罪名")
    p.add_argument("--lean", help="圣意（GM）：准 或 驳")
    p.add_argument("--signal", choices=SIGNALS)
    p.add_argument("--when")
    p = add("session", "朝议结算", cmd_session)
    p.add_argument("id")
    p.add_argument("--debate", help="廷辩：附议一方:反对一方")
    p.add_argument("--auto-debate", action="store_true", help="两边都有人时，自动挑人廷辩")
    p.add_argument("--point-a", type=int, choices=(-1, 0, 1, 2))
    p.add_argument("--point-b", type=int, choices=(-1, 0, 1, 2))
    p.add_argument("--style-a")
    p.add_argument("--style-b")
    p.add_argument("--cite-a")
    p.add_argument("--cite-b")
    p.add_argument("--lean", help="圣意（GM）：准|驳，或提议的某个主张")
    p.add_argument("--signal", choices=SIGNALS)
    p.add_argument("--seed", type=int)
    p.add_argument("--force", action="store_true")
    p = add("decide", "定夺", cmd_decide)
    p.add_argument("id")
    p.add_argument("--ruling", required=True, choices=RULINGS)
    p.add_argument("--penalty", choices=tuple(PENALTIES))
    p.add_argument("--office")
    p.add_argument("--where")
    p.add_argument("--by")
    p.add_argument("--false", action="store_true", help="查实是诬告（反坐）")
    p.add_argument("--note")
    p.add_argument("--force", action="store_true")
    p = add("appoint", "任命", cmd_appoint)
    p.add_argument("name")
    p.add_argument("--office", required=True)
    p.add_argument("--rank", type=int, choices=range(1, 10))
    p.add_argument("--council", action="store_true")
    p.add_argument("--why")
    p = add("remove", "去职", cmd_remove)
    p.add_argument("name")
    p.add_argument("--status", required=True, choices=OUT_STATUS)
    p.add_argument("--where")
    p.add_argument("--why", required=True)
    p = add("faction", "派系", cmd_faction)
    p.add_argument("name")
    p.add_argument("--new", action="store_true")
    p.add_argument("--leader")
    p.add_argument("--stance")
    p.add_argument("--voice", type=int)
    p.add_argument("--voice-delta", type=int)
    p.add_argument("--join")
    p.add_argument("--leave")
    p.add_argument("--why")
    p = add("issue", "议题", cmd_issue)
    p.add_argument("name")
    p.add_argument("--title")
    p.add_argument("--options")
    p.add_argument("--lean")
    p.add_argument("--signal", choices=SIGNALS)
    p.add_argument("--status")
    p = add("position", "一派对一个议题的立场", cmd_position)
    p.add_argument("faction")
    p.add_argument("--issue", required=True)
    p.add_argument("--want")
    p.add_argument("--accept")
    p.add_argument("--bottom")
    p.add_argument("--bottom-text")
    p.add_argument("--weight", type=int, choices=(1, 2, 3))
    p = add("feud", "两派之间记一笔积怨", cmd_feud)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--what", required=True)
    p.add_argument("--strength", type=int, required=True, choices=(1, 2, 3))
    p.add_argument("--when")
    p = add("career", "仕途", cmd_career)
    p.add_argument("name")
    p.add_argument("--post")
    p.add_argument("--ladder")
    p.add_argument("--superior")
    p.add_argument("--duty")
    p.add_argument("--due", type=int)
    p.add_argument("--regard", type=int)
    p = add("ladder", "仕途阶梯", cmd_ladder, write=False)
    p.add_argument("name", nargs="?")
    p = add("promote", "在阶梯上升降一阶", cmd_promote)
    p.add_argument("name")
    p.add_argument("--down", action="store_true")
    p.add_argument("--to")
    p.add_argument("--why", required=True)
    p = add("regard", "上司的器重", cmd_regard)
    p.add_argument("name")
    p.add_argument("--event", help="、".join(REGARD_EVENTS))
    p.add_argument("--delta", type=int)
    p.add_argument("--why")
    p = add("duty", "差事回报", cmd_duty)
    p.add_argument("name")
    p.add_argument("--result", required=True, choices=tuple(DUTY))
    p.add_argument("--what", required=True)
    p = add("hint", "朝中提示", cmd_hint, write=False)
    p.add_argument("name")
    p = add("season", "季末推进", cmd_season)
    p.add_argument("--when")
    p.add_argument("--trigger", action="append", default=[], help="名=事件：" + "、".join(MIND_TRIGGERS))
    p.add_argument("--pay", action="store_true", help="主角的俸禄写进家财")
    p.add_argument("--seed", type=int)
    p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    args.fn(Court(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
