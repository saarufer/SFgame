#!/usr/bin/env python3
"""关系网：任意两人之间的关系标签、亲疏、恩怨，以及谁知道这层关系。规则见 rules/relations.md。只用标准库。

存档是 world/relations.json。会改存档的命令默认只打印，加 --apply 才写回。

  查看     show 名 [--as 观者] [--all]          一个人的关系网（--as：只列观者知道的）
           pair 甲 乙                          两人之间的一切
  标签     tag 甲 乙 --tag 师生 [--roles 甲=师,乙=生] [--hidden] [--knowers 名,名] [--since 时间] [--note …] [--remove]
  底子     base 甲 --toward 乙 --value -2..2 --why …   GM 改“底子”（不写就按标签算）；--clear 恢复按标签算
  恩怨     add 持有者 --toward 对方 --kind 恩|怨 --what 事由 --strength 1-3 [--known 公开|两人|暗] [--when 时间]
           event 事件 --by 做事的人 --to 受者 [--what …] [--known …]   按“常见的事怎么记”一表记账
           settle 编号 --by 报答|报复|和解|抵偿|加深|淡忘|不计 [--note 说明]
  知情     know 观者 --pair 甲,乙 | --deed 编号          观者得知一层暗的关系、一笔暗的恩怨
  引荐     path 我 目标 [--max 3] [--known-by 名]    经过熟人，谁能替我引荐到谁面前
  季末     season [--when 时间]                         恩怨按时间淡化，和人格卡上的心结对账

所有命令都有 --world（试验用）。
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import social_lib as X  # noqa: E402

FILE = "relations.json"
EMPTY = {"version": 1, "pairs": [], "deeds": [], "next_id": 1, "last_season_turn": 0}

# 标签：底子（这一层关系本身让两人亲近或疏远多少）、两头的称呼（有方向的才写）
TAGS = {
    "姻亲": {"base": 1, "roles": None, "note": "两家结了亲"},
    "亲族": {"base": 1, "roles": None, "note": "同宗、近亲"},
    "师生": {"base": 1, "roles": ("师", "生"), "note": "受过业、座主门生也算"},
    "同门": {"base": 1, "roles": None, "note": "同一位老师门下"},
    "同年": {"base": 1, "roles": None, "note": "同一年登第、同一批出仕"},
    "同乡": {"base": 1, "roles": None, "note": ""},
    "旧部": {"base": 1, "roles": ("旧主", "旧部"), "note": "在谁手下做过事"},
    "同袍": {"base": 1, "roles": None, "note": "一起打过仗"},
    "主仆": {"base": 1, "roles": ("主", "仆"), "note": "家仆、门客、幕宾"},
    "私交": {"base": 2, "roles": None, "note": "朋友、酒友、诗友"},
    "盟好": {"base": 1, "roles": None, "note": "约定互相照应"},
    "私情": {"base": 2, "roles": None, "note": "多半是暗的"},
    "世交": {"base": 1, "roles": None, "note": "两家上一辈的交情"},
    "上下级": {"base": 0, "roles": ("上司", "下属"), "note": "眼下的上司和下属；冷暖看器重和恩怨"},
    "政敌": {"base": -2, "roles": None, "note": "在朝中立场相对，彼此都知道"},
    "世仇": {"base": -2, "roles": None, "note": "两家上一辈结下的仇"},
}
TAG_ALIASES = {"座主": "师生", "门生": "师生", "姻戚": "姻亲", "宗亲": "亲族", "故旧": "私交", "朋友": "私交",
               "旧主": "旧部", "仇家": "世仇"}
CLOSE_WORDS = {-3: "势同水火", -2: "交恶", -1: "不睦", 0: "平常", 1: "有交情", 2: "交好", 3: "生死之交"}
KNOWN = ("公开", "两人", "暗")
SETTLE = ("报答", "报复", "和解", "抵偿", "加深", "淡忘", "不计")
# 时间淡化：(强度, 季数, 结果)。强度 3 的不会自己淡
FADE = {"恩": {1: 4, 2: 8}, "怨": {1: 6, 2: 12}}

# 常见的事怎么记：事件 → (持有者, 对方, 恩/怨, 强度, 默认的知情范围)。“受”是受这件事的人，“做”是做这件事的人
EVENTS = {
    "举荐": ("受", "做", "恩", 2, "两人", "举荐他做官、替他说话谋得差事"),
    "提携": ("受", "做", "恩", 1, "两人", "给了差事、指点门路"),
    "援手": ("受", "做", "恩", 1, "两人", "朝议上附议、替他说情、解围"),
    "厚赠": ("受", "做", "恩", 1, "两人", "送了一份重礼、接济困顿"),
    "救命": ("受", "做", "恩", 3, "两人", "救过他的命，或救了他的至亲"),
    "辟谣": ("受", "做", "恩", 1, "公开", "替他辟谣、当众替他说话"),
    "驳倒": ("受", "做", "怨", 1, "公开", "当众驳倒他（contest.py 辩论“驳倒”）"),
    "恼羞成怒": ("受", "做", "怨", 2, "公开", "当众驳得他下不来台（辩论“恼羞成怒”）"),
    "羞辱": ("受", "做", "怨", 2, "公开", "当众斥骂、讥讽、给他难堪"),
    "弹劾": ("受", "做", "怨", 2, "公开", "上奏弹劾他（不论准不准）"),
    "罢官": ("受", "做", "怨", 3, "公开", "因这个人被罢官、下狱、流放"),
    "抢功": ("受", "做", "怨", 2, "两人", "夺了他的位子、抢了他的功劳"),
    "背约": ("受", "做", "怨", 2, "两人", "答应的事不作数、出卖他"),
    "要挟": ("受", "做", "怨", 2, "两人", "拿把柄要挟他（secrets.py leverage）"),
    "构陷": ("受", "做", "怨", 3, "两人", "罗织罪名陷害他（他知道是谁干的时才记）"),
    "杀亲": ("受", "做", "怨", 3, "公开", "杀了他的至亲"),
}
TAG_EVENTS = {"联姻": "姻亲", "结亲": "姻亲", "拜师": "师生", "结交": "私交", "结盟": "盟好"}


# ---------------------------------------------------------------- 存档

class Net:
    def __init__(self, world):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        self.d.setdefault("pairs", [])
        self.d.setdefault("deeds", [])
        self.d.setdefault("next_id", max([x["id"] for x in self.d["deeds"]] + [0]) + 1)

    def save(self):
        return X.save_json(self.world, FILE, self.d)

    # --- 两人 ---
    def pair(self, a, b, create=False):
        for p in self.d["pairs"]:
            if {p["a"], p["b"]} == {a, b}:
                return p
        if not create:
            return None
        p = {"a": a, "b": b, "tags": [], "base": {a: None, b: None}, "note": ""}
        self.d["pairs"].append(p)
        return p

    def names(self):
        s = set()
        for p in self.d["pairs"]:
            s.update((p["a"], p["b"]))
        for x in self.d["deeds"]:
            s.update((x["holder"], x["toward"]))
        return s

    def deeds(self, holder=None, toward=None, active=True):
        out = []
        for x in self.d["deeds"]:
            if holder and x["holder"] != holder:
                continue
            if toward and x["toward"] != toward:
                continue
            if active and x["status"] != "未了":
                continue
            out.append(x)
        return out

    def deed(self, did):
        x = next((x for x in self.d["deeds"] if x["id"] == did), None)
        if not x:
            X.die(f"关系网里没有编号 {did} 的恩怨")
        return x

    # --- 亲疏 ---
    def tag_base(self, p, side):
        if p is None:
            return 0
        b = p.get("base", {}).get(side)
        if b is not None:
            return int(b)
        return X.clamp(sum(TAGS.get(t["tag"], {}).get("base", 0) for t in p["tags"]), -2, 2)

    def closeness(self, holder, toward, observer=None):
        """holder 眼里和 toward 的亲疏，−3..+3。observer 给了，只算 observer 知道的部分（看人的眼光）。"""
        p = self.pair(holder, toward)
        if observer is None or observer in (holder, toward):
            base = self.tag_base(p, holder)
        else:
            vis = [t for t in (p["tags"] if p else []) if tag_visible(t, p, observer)]
            base = X.clamp(sum(TAGS.get(t["tag"], {}).get("base", 0) for t in vis), -2, 2)
        s = base
        for x in self.deeds(holder, toward):
            if observer is not None and not deed_visible(x, observer):
                continue
            s += x["s"] if x["kind"] == "恩" else -x["s"]
        return X.clamp(s, -3, 3)

    def add_deed(self, holder, toward, kind, what, s, when, turn, known="两人", knowers=(), source="", ref=""):
        if kind not in ("恩", "怨"):
            X.die("--kind 只能是 恩 或 怨")
        if not 1 <= s <= 3:
            X.die("恩怨的强度是 1–3")
        if known not in KNOWN:
            X.die(f"--known 只能是 {'/'.join(KNOWN)}")
        if holder == toward:
            X.die("恩怨要记在两个人之间")
        x = {"id": self.d["next_id"], "holder": holder, "toward": toward, "kind": kind, "what": what, "s": s,
             "when": when, "turn": turn, "status": "未了", "age": 0, "known": known, "knowers": list(knowers),
             "eased": False}
        if source:
            x["source"] = source
        if ref:
            x["ref"] = ref
        self.d["next_id"] += 1
        self.d["deeds"].append(x)
        return x


def tag_visible(t, p, observer):
    return (not t.get("hidden")) or observer in (p["a"], p["b"]) or observer in t.get("knowers", [])


def deed_visible(x, observer):
    if observer == x["holder"] or observer in x.get("knowers", []):
        return True
    if x["known"] == "公开":
        return True
    if x["known"] == "两人":
        return observer == x["toward"]
    return False


def close_word(v):
    return CLOSE_WORDS[X.clamp(int(v), -3, 3)]


def canon_tag(t):
    t = TAG_ALIASES.get(t, t)
    return t


def fmt_deed(x, gm=True):
    st = x["status"] if x["status"] != "未了" else f"未了，已历 {x['age']} 季"
    vis = x["known"] + (f"（另有 {'、'.join(x['knowers'])} 知道）" if x.get("knowers") else "")
    src = f"｜来自 {x['source']}" if gm and x.get("source") else ""
    return f"[{x['id']}] {x['holder']} 对 {x['toward']}：{x['kind']} {x['s']}｜{x['when']}｜{x['what']}｜{st}｜{vis}{src}"


def fmt_tag(t, p):
    roles = ""
    if t.get("roles"):
        roles = "（" + "，".join(f"{k}为{v}" for k, v in t["roles"].items()) + "）"
    hid = "【暗】" + (f"知情：{'、'.join(t.get('knowers', []))}" if t.get("knowers") else "只有两人知道") if t.get("hidden") else ""
    since = f"，{t['since']}起" if t.get("since") else ""
    return f"{t['tag']}{roles}{since}{hid}"


# ---------------------------------------------------------------- 命令

def finish(net, args, msg="关系网"):
    if args.apply:
        print(f"\n已写入 {X.rel(net.save())}。")
    else:
        print(f"\n（未写入{msg}。确认无误后加 --apply。）")


def cmd_show(net, args):
    me = args.name
    obs = args.as_
    others = set()
    for p in net.d["pairs"]:
        if me in (p["a"], p["b"]):
            others.add(p["b"] if p["a"] == me else p["a"])
    for x in net.d["deeds"]:
        if me in (x["holder"], x["toward"]) and (args.all or x["status"] == "未了"):
            others.add(x["toward"] if x["holder"] == me else x["holder"])
    title = f"=== 关系网：{me}" + (f"（{obs}所知）" if obs else "（GM 全知）") + " ==="
    print(title)
    if not others:
        print("  （关系网里还没有这个人）")
        return
    rows = []
    for o in sorted(others):
        p = net.pair(me, o)
        if obs:
            tags = [t for t in (p["tags"] if p else []) if tag_visible(t, p, obs)]
            ds = [x for x in net.d["deeds"] if {x["holder"], x["toward"]} == {me, o}
                  and deed_visible(x, obs) and (args.all or x["status"] == "未了")]
        else:
            tags = p["tags"] if p else []
            ds = [x for x in net.d["deeds"] if {x["holder"], x["toward"]} == {me, o} and (args.all or x["status"] == "未了")]
        if obs and not tags and not ds:
            continue
        c1 = net.closeness(me, o, observer=obs)
        c2 = net.closeness(o, me, observer=obs)
        rows.append((-(abs(c1) + abs(c2)), o, c1, c2, tags, ds, p))
    for _, o, c1, c2, tags, ds, p in sorted(rows):
        print(f"  {X.pad(o, 10)} {me}看他：{close_word(c1)}（{c1:+d}）  他看{me}：{close_word(c2)}（{c2:+d}）")
        if tags:
            print("      关系：" + "；".join(fmt_tag(t, p) for t in tags))
        for x in ds:
            print("      " + fmt_deed(x, gm=not obs))
    if obs and not rows:
        print(f"  （{obs}不知道{me}和谁有什么关系）")


def cmd_pair(net, args):
    a, b = args.a, args.b
    p = net.pair(a, b)
    print(f"=== {a} 与 {b} ===")
    if p:
        print("  关系：" + ("；".join(fmt_tag(t, p) for t in p["tags"]) if p["tags"] else "无标签"))
        for side in (a, b):
            bb = p.get("base", {}).get(side)
            if bb is not None:
                print(f"  底子（GM 改过）：{side} {bb:+d}" + (f"｜{p.get('base_why', {}).get(side, '')}" if p.get("base_why") else ""))
    else:
        print("  没有标签")
    for h, t in ((a, b), (b, a)):
        c = net.closeness(h, t)
        print(f"  {h} 看 {t}：{close_word(c)}（{c:+d}；底子 {net.tag_base(p, h):+d}）")
    ds = [x for x in net.d["deeds"] if {x["holder"], x["toward"]} == {a, b}]
    for x in ds:
        print("  " + fmt_deed(x))


def cmd_tag(net, args):
    tag = canon_tag(args.tag)
    if tag not in TAGS:
        print(f"注：“{tag}”不在标签表里（{'、'.join(TAGS)}），照记，底子按 0 算。")
    p = net.pair(args.a, args.b, create=True)
    old = next((t for t in p["tags"] if t["tag"] == tag), None)
    if args.remove:
        if not old:
            X.die(f"{args.a} 和 {args.b} 之间没有“{tag}”")
        p["tags"].remove(old)
        print(f"去掉 {args.a}—{args.b} 的“{tag}”" + (f"（{args.note}）" if args.note else ""))
        return finish(net, args)
    t = old or {"tag": tag}
    roles = {}
    if args.roles:
        for tok in X.split_names(args.roles):
            if "=" not in tok:
                X.die("--roles 写成 甲=师,乙=生")
            k, v = tok.split("=", 1)
            if k not in (args.a, args.b):
                X.die(f"--roles 里的 {k} 不是 {args.a} 或 {args.b}")
            roles[k] = v
    elif TAGS.get(tag, {}).get("roles") and not t.get("roles"):
        r = TAGS[tag]["roles"]
        roles = {args.a: r[0], args.b: r[1]}
        print(f"注：“{tag}”有方向，按 {args.a} 为{r[0]}、{args.b} 为{r[1]} 记；反了就用 --roles 改。")
    if roles:
        t["roles"] = roles
    if args.since:
        t["since"] = args.since
    if args.hidden:
        t["hidden"] = True
    if args.public:
        t.pop("hidden", None)
    if args.knowers:
        t["knowers"] = sorted(set(t.get("knowers", [])) | set(X.split_names(args.knowers)))
    if args.note:
        t["note"] = args.note
    if not old:
        p["tags"].append(t)
    print(("改" if old else "记") + f" {args.a}—{args.b}：{fmt_tag(t, p)}")
    for h, o in ((args.a, args.b), (args.b, args.a)):
        print(f"  {h} 看 {o}：{close_word(net.closeness(h, o))}（{net.closeness(h, o):+d}）")
    finish(net, args)


def cmd_base(net, args):
    p = net.pair(args.name, args.toward, create=True)
    p.setdefault("base", {})
    p.setdefault("base_why", {})
    old = net.closeness(args.name, args.toward)
    if args.clear:
        p["base"][args.name] = None
        p["base_why"].pop(args.name, None)
    else:
        if args.value is None or not args.why:
            X.die("改底子要给 --value（−2..2）和 --why")
        if not -2 <= args.value <= 2:
            X.die("底子只能在 −2..+2（恩怨另记）")
        p["base"][args.name] = args.value
        p["base_why"][args.name] = args.why
    new = net.closeness(args.name, args.toward)
    print(f"{args.name} 看 {args.toward}：{close_word(old)}（{old:+d}）→ {close_word(new)}（{new:+d}）"
          + (f"｜{args.why}" if args.why else "｜恢复按标签算"))
    finish(net, args)


def cmd_add(net, args):
    turn = X.turn_of(net.world)
    x = net.add_deed(args.holder, args.toward, args.kind, args.what, args.strength, X.when_of(net.world, args.when), turn,
                     args.known, X.split_names(args.knowers), source=args.source or "")
    print("记下：" + fmt_deed(x))
    c = net.closeness(args.holder, args.toward)
    print(f"  {args.holder} 看 {args.toward}：{close_word(c)}（{c:+d}）")
    finish(net, args)


def cmd_event(net, args):
    ev = args.event
    if ev in TAG_EVENTS:
        args.a, args.b, args.tag = args.by, args.to, TAG_EVENTS[ev]
        args.roles = args.since = args.knowers = args.note = None
        args.hidden = args.known == "暗"
        args.public = False
        args.remove = False
        return cmd_tag(net, args)
    if ev not in EVENTS:
        X.die(f"事件“{ev}”不在表里。可用：{'、'.join(list(EVENTS) + list(TAG_EVENTS))}；别的事用 add 手记")
    h, t, kind, s, known, desc = EVENTS[ev]
    holder = args.to if h == "受" else args.by
    toward = args.by if t == "做" else args.to
    if args.strength:
        s = args.strength
    what = args.what or f"{args.by}{ev}{args.to}"
    x = net.add_deed(holder, toward, kind, what, s, X.when_of(net.world, args.when), X.turn_of(net.world),
                     args.known or known, X.split_names(args.knowers), source=args.source or ev)
    print(f"事件“{ev}”（{desc}）→ " + fmt_deed(x))
    c = net.closeness(holder, toward)
    print(f"  {holder} 看 {toward}：{close_word(c)}（{c:+d}）")
    finish(net, args)


def cmd_settle(net, args):
    x = net.deed(args.id)
    if x["status"] != "未了" and args.by != "加深":
        X.die(f"[{x['id']}] 已经是“{x['status']}”")
    before = f"{x['kind']} {x['s']}｜{x['status']}"
    note = args.note or ""
    if args.by == "报答":
        if x["kind"] != "恩":
            X.die("报答只用于恩；怨的了结用“报复”“和解”“抵偿”")
        x["status"] = f"已报（{note or '报答了'}）"
    elif args.by == "报复":
        if x["kind"] != "怨":
            X.die("报复只用于怨")
        x["status"] = f"已报（{note or '报复了'}）"
        print("注：报复本身是一件新事。对方因此记的怨，另用 add 或 event 记。")
    elif args.by == "和解":
        if x.get("eased"):
            X.die(f"[{x['id']}] 已经和解过一次。同一笔恩怨，和解只算一次")
        x["eased"] = True
        x["s"] -= 1
        if x["s"] <= 0:
            x["s"] = 0
            x["status"] = f"已解（{note or '和解'}）"
    elif args.by == "抵偿":
        if not note:
            X.die("抵偿要用 --note 写明拿什么抵的")
        x["status"] = f"已抵偿（{note}）"
    elif args.by == "加深":
        x["status"] = "未了"
        x["s"] = min(3, x["s"] + 1)
        x["age"] = 0
    elif args.by in ("淡忘", "不计"):
        if not note:
            X.die(f"--by {args.by} 要用 --note 写明缘由")
        x["status"] = f"{'已淡忘' if args.by == '淡忘' else '不计'}（{note}）"
    print(f"[{x['id']}] {x['holder']} 对 {x['toward']}：{before} → {x['kind']} {x['s']}｜{x['status']}")
    c = net.closeness(x["holder"], x["toward"])
    print(f"  {x['holder']} 看 {x['toward']}：{close_word(c)}（{c:+d}）")
    if x.get("ref", "").startswith("card:"):
        print(f"注：这一笔和人格卡上的心结相连（{x['ref']}），卡上的那一条用 loyalty.py ease 一并处理。")
    finish(net, args)


def cmd_know(net, args):
    who = args.who
    if args.pair:
        ab = X.split_names(args.pair)
        if len(ab) != 2:
            X.die("--pair 写成 甲,乙")
        p = net.pair(*ab)
        if not p:
            X.die(f"{ab[0]} 和 {ab[1]} 之间没有记过关系")
        hit = [t for t in p["tags"] if t.get("hidden") and (not args.tag or t["tag"] == canon_tag(args.tag))]
        if not hit:
            X.die("这两人之间没有暗的关系标签")
        for t in hit:
            if who not in t.setdefault("knowers", []) and who not in (p["a"], p["b"]):
                t["knowers"].append(who)
            print(f"{who} 得知：{p['a']}—{p['b']} {fmt_tag(t, p)}")
    elif args.deed:
        x = net.deed(args.deed)
        if who not in x.setdefault("knowers", []) and who not in (x["holder"],):
            x["knowers"].append(who)
        print(f"{who} 得知：{fmt_deed(x)}")
    else:
        X.die("给 --pair 甲,乙 或 --deed 编号")
    finish(net, args)


def faction_map(world):
    """court.json 里谁在哪一派（派系是公开的）。同派的人互相说得上话，引荐时按“有交情”算。"""
    try:
        court = X.load_json(world, "court.json", {})
    except SystemExit:
        return {}
    out = {}
    for f, r in court.get("factions", {}).items():
        for m in r.get("members", []):
            out[m] = f
    return out


def listens(net, speaker, listener, observer=None, factions=None):
    """speaker 能在 listener 面前说上话：listener 看 speaker ≥ +1，speaker 看 listener ≥ 0。返回 listener 的亲疏或 None。
    同在一派的，没有别的恩怨时按 +1 算。"""
    c_l = net.closeness(listener, speaker, observer)
    c_s = net.closeness(speaker, listener, observer)
    if factions and factions.get(speaker) and factions.get(speaker) == factions.get(listener):
        c_l = max(c_l, 1) if c_l >= 0 else c_l
    if c_l >= 1 and c_s >= 0:
        return c_l
    return None


def find_paths(net, start, target, max_mid=3, observer=None, limit=5):
    facs = faction_map(net.world)
    people = net.names() | {start, target} | set(facs)
    # 广度优先，路径上不重复
    out = []
    frontier = [[start]]
    for depth in range(max_mid + 1):
        nxt = []
        for path in frontier:
            last = path[-1]
            for y in people:
                if y in path:
                    continue
                c = listens(net, last, y, observer, facs)
                if c is None:
                    continue
                np = path + [y]
                if y == target:
                    out.append(np)
                elif depth < max_mid:
                    nxt.append(np)
        if out:
            break
        frontier = nxt
    def strength(path):
        return min(listens(net, path[i], path[i + 1], observer, facs) or 0 for i in range(len(path) - 1))
    out.sort(key=lambda p: (len(p), -strength(p)))
    return [(p, strength(p)) for p in out[:limit]]


def hop_hidden(net, a, b, observer):
    """这一跳靠的是不是 observer 不知道的关系。"""
    if observer is None:
        return False
    return net.closeness(b, a, observer) != net.closeness(b, a) or net.closeness(a, b, observer) != net.closeness(a, b)


def cmd_path(net, args):
    s, t = args.start, args.target
    print(f"=== 引荐：{s} → {t}" + (f"（只走 {args.known_by} 知道的关系）" if args.known_by else "（GM 全知）") + " ===")
    facs = faction_map(net.world)
    facs = faction_map(net.world)
    c = listens(net, s, t, args.known_by, facs)
    if c is not None:
        print(f"  不用人引荐：{t} 看 {s} {close_word(c)}，{s}自己就能说上话。")
    paths = find_paths(net, s, t, args.max, args.known_by)
    if not paths:
        print(f"  找不到 {args.max} 个中间人以内的路。{t} 身边的人和 {s} 都还没有交情；可以先结交 {t} 看重的人：")
        near = sorted(((listens(net, o, t, args.known_by, facs) or 0, o) for o in net.names() | set(facs) if o not in (s, t)),
                      reverse=True)[:5]
        for v, o in near:
            if v >= 1:
                print(f"    · {o}（{t} 看他 {close_word(v)}" + ("，同派" if facs.get(o) and facs.get(o) == facs.get(t) else "") + "）")
        return
    try:
        import court as C
        court = C.Court(net.world)
    except SystemExit:
        court = None
    for path, st in paths:
        hops = []
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            mark = "（这一层玩家未必知道）" if args.gm_mark and hop_hidden(net, a, b, args.gm_mark) else ""
            same = "，同派" if facs.get(a) and facs.get(a) == facs.get(b) else ""
            hops.append(f"{a} →（{b} 看他 {close_word(listens(net, a, b, None, facs) or net.closeness(b, a))}{same}）{mark}")
        print(f"  · {' '.join(hops)} → {t}   最弱的一环：{close_word(st)}")
        if court is not None:
            posts = [f"{x}（{court.post_of(x) or '无官'}）" for x in path[1:-1]]
            if posts:
                print(f"      中间人：{'、'.join(posts)}")
    print("  一跳的条件：听话的人看说话的人 ≥ 有交情（+1），说话的人看听话的人不交恶（≥ 0）。"
          "托人引荐算欠一份人情：成了就记 relations.py event 提携 或 援手。")


def sync_card(net, x):
    """和人格卡上的心结对账：ref 写成 card:<路径>#<编号>。返回说明或 None。"""
    ref = x.get("ref", "")
    if not ref.startswith("card:"):
        return None
    path, _, gid = ref[5:].rpartition("#")
    full = path if os.path.isabs(path) else None
    for base in (os.path.dirname(net.world), X.ROOT):
        c = os.path.join(base, path)
        if os.path.exists(c):
            full = c
            break
    if not full or not os.path.exists(full):
        return f"[{x['id']}] 对应的人格卡 {path} 找不到了"
    import loyalty as L
    card = L.Card(full)
    g = next((g for g in card.grudges if str(g["id"]) == gid), None)
    if g is None:
        return f"[{x['id']}] 对应的心结 {gid} 在 {path} 上找不到了"
    changed = []
    if g["s"] != x["s"] and g["s"] > 0:
        changed.append(f"强度 {x['s']} → {g['s']}")
        x["s"] = g["s"]
    if g["status"] != "未解" and x["status"] == "未了":
        x["status"] = g["status"].replace("已解", "已解").replace("已抵消", "已抵偿")
        changed.append(f"状态 → {x['status']}")
    x["age"] = g.get("age", x["age"])
    return f"[{x['id']}] 和 {X.rel(full)} 的心结 [{gid}] 对账：{'；'.join(changed)}" if changed else None


def cmd_season(net, args):
    turn = X.turn_of(net.world)
    if net.d.get("last_season_turn") == turn and not args.force:
        X.die(f"第 {turn} 回合的关系网已经推进过。确要重跑加 --force")
    print(f"=== 关系网季末：{X.when_of(net.world, args.when)}（第 {turn} 回合） ===")
    lines = []
    for x in net.d["deeds"]:
        if x["status"] != "未了":
            continue
        if x.get("ref", "").startswith("card:"):
            msg = sync_card(net, x)
            if msg:
                lines.append(msg)
            continue
        x["age"] += 1
        lim = FADE[x["kind"]].get(x["s"])
        if lim and x["age"] >= lim:
            if x["s"] == 1:
                x["status"] = f"已淡忘（{lim} 季没人再提）"
                lines.append(f"[{x['id']}] {x['holder']} 对 {x['toward']} 的{x['kind']}（强度 1）已历 {lim} 季 → 淡忘")
            else:
                x["s"], x["age"] = 1, 0
                lines.append(f"[{x['id']}] {x['holder']} 对 {x['toward']} 的{x['kind']}（强度 2）已历 {lim} 季 → 降为 1")
    for l in lines or ["（没有恩怨到期淡化）"]:
        print("  " + l)
    act = [x for x in net.d["deeds"] if x["status"] == "未了"]
    print(f"  未了的恩怨：恩 {sum(1 for x in act if x['kind'] == '恩')} 笔，怨 {sum(1 for x in act if x['kind'] == '怨')} 笔")
    deep = [x for x in act if x["kind"] == "怨" and x["s"] >= 3]
    if deep:
        print("  记着深仇（强度 3，不会自己淡）：")
        for x in deep:
            print("    · " + fmt_deed(x))
    net.d["last_season_turn"] = turn
    finish(net, args)


def main():
    ap = argparse.ArgumentParser(description="关系网（规则见 rules/relations.md）",
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

    p = add("show", "一个人的关系网", cmd_show, write=False)
    p.add_argument("name")
    p.add_argument("--as", dest="as_", help="只列这个人知道的")
    p.add_argument("--all", action="store_true", help="连了结的恩怨一起列")
    p = add("pair", "两人之间", cmd_pair, write=False)
    p.add_argument("a")
    p.add_argument("b")
    p = add("tag", "记或去掉一个关系标签", cmd_tag)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--tag", required=True, help="、".join(TAGS))
    p.add_argument("--roles", help="有方向的标签：甲=师,乙=生")
    p.add_argument("--since")
    p.add_argument("--hidden", action="store_true", help="暗的：只有两人和 --knowers 知道")
    p.add_argument("--public", action="store_true", help="改成公开")
    p.add_argument("--knowers", help="另外知道这层关系的人，逗号分隔")
    p.add_argument("--note")
    p.add_argument("--remove", action="store_true")
    p = add("base", "GM 改底子", cmd_base)
    p.add_argument("name")
    p.add_argument("--toward", required=True)
    p.add_argument("--value", type=int)
    p.add_argument("--why")
    p.add_argument("--clear", action="store_true")
    p = add("add", "记一笔恩或怨", cmd_add)
    p.add_argument("holder", help="记着这份恩、这份怨的人")
    p.add_argument("--toward", required=True)
    p.add_argument("--kind", required=True, choices=("恩", "怨"))
    p.add_argument("--what", required=True)
    p.add_argument("--strength", type=int, required=True)
    p.add_argument("--known", default="两人", choices=KNOWN)
    p.add_argument("--knowers")
    p.add_argument("--when")
    p.add_argument("--source", help="来自哪件事（court:M3、contest、household…）")
    p = add("event", "按常见的事记账", cmd_event)
    p.add_argument("event", help="、".join(list(EVENTS) + list(TAG_EVENTS)))
    p.add_argument("--by", required=True, help="做这件事的人")
    p.add_argument("--to", required=True, help="受这件事的人")
    p.add_argument("--what")
    p.add_argument("--strength", type=int, choices=(1, 2, 3))
    p.add_argument("--known", choices=KNOWN)
    p.add_argument("--knowers")
    p.add_argument("--when")
    p.add_argument("--source")
    p = add("settle", "了结、消解或加深一笔恩怨", cmd_settle)
    p.add_argument("id", type=int)
    p.add_argument("--by", required=True, choices=SETTLE)
    p.add_argument("--note")
    p = add("know", "某人得知一层暗的关系", cmd_know)
    p.add_argument("who")
    p.add_argument("--pair", help="甲,乙")
    p.add_argument("--tag")
    p.add_argument("--deed", type=int)
    p = add("path", "谁能替我引荐", cmd_path, write=False)
    p.add_argument("start")
    p.add_argument("target")
    p.add_argument("--max", type=int, default=3, help="最多几个中间人")
    p.add_argument("--known-by", help="只走这个人知道的关系（给玩家看的答案）")
    p.add_argument("--gm-mark", help="GM 全知时，标出这个人不知道的那几跳")
    p = add("season", "季末淡化恩怨", cmd_season)
    p.add_argument("--when")
    p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    args.fn(Net(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
