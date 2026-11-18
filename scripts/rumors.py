#!/usr/bin/env python3
"""流言、名望与文献。规则见 rules/rumors.md。只用标准库。

存档是 world/rumors.json（圈子、流言、文献）；名望记在人格卡数值块的“名望”一行，或名册条目的“名望”字段。
会改存档的命令默认只打印，加 --apply 才写回；有掷骰的命令支持 --seed。

  造谣     spread --text 内容 --truth 真|假|半真 --circle 圈子 [--source 谁] [--about 名,名] [--heat 1-3] [--cred 0-5]
                  [--effect 名:士林=-1,…] [--note GM 备注]
  辟谣     refute 编号 --by 谁 [--circle 圈子] [--evidence 文献或证据] [--point -1..2] [--seed N]
  坐实     confirm 编号 --why …                  证据摆出来了：可信度到 5，名望的影响全部落下
  季末     season [--seed N]                     流言在圈子之间扩散或消退；文献流布；名望随之升降
  查看     circle 圈子 [--gm]                    这个圈子里眼下流传什么
           heard 名                              这个人听到过哪些流言（按他所在的圈子）
           show [编号]                            全部流言（GM 用）
  名望     fame 名 [--set 士林=6,军中=3] [--delta 士林=-1 --why …]
  文献     doc add --title 题目 --kind 书|檄文|奏疏|诗文|书信 [--author 谁] --summary 摘要 [--claim 说法=真 …]
                   [--reach 士林=2,市井=1] [--holders 名,名] [--weight 1-3]
           doc show [编号]  |  doc spawn 编号 --claim-no N --circle 圈子   （文献里的一个说法变成流言）
           doc ban 编号 --why …                   （禁毁）
           cite 编号 --fit 得当|牵强|失当 [--audience 圈子]   辩论里引用文献的论点加减（contest.py --cite-a 同样算）

所有命令都有 --world（试验用）。
"""
import argparse
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import social_lib as X  # noqa: E402

FILE = "rumors.json"
EMPTY = {"version": 1, "rumors": [], "docs": [], "members": {}, "next": {"R": 1, "D": 1}, "last_season_turn": 0}
TRUTH = ("真", "假", "半真")
FITS = ("得当", "牵强", "失当")
DOC_KINDS = ("书", "檄文", "奏疏", "诗文", "书信", "告示", "其他")


class Board:
    def __init__(self, world):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        for k, v in EMPTY.items():
            self.d.setdefault(k, json_copy(v))
        self.circles = self.d.get("circles") or X.DEFAULT_CIRCLES
        self.kinds = self.d.get("fame_kinds") or X.FAME_KINDS
        self._people = None

    @property
    def people(self):
        if self._people is None:
            self._people = X.People(self.world)
        return self._people

    def save(self):
        return X.save_json(self.world, FILE, self.d)

    def new_id(self, kind):
        n = self.d["next"].get(kind, 1)
        self.d["next"][kind] = n + 1
        return f"{kind}{n}"

    def rumor(self, rid):
        r = next((x for x in self.d["rumors"] if x["id"] == rid), None)
        if not r:
            X.die(f"没有编号 {rid} 的流言（有：{'、'.join(x['id'] for x in self.d['rumors']) or '无'}）")
        return r

    def doc(self, did):
        r = next((x for x in self.d["docs"] if x["id"] == did or x["title"].strip("《》") == did.strip("《》")), None)
        if not r:
            X.die(f"没有文献 {did}（有：{'、'.join(x['id'] + x['title'] for x in self.d['docs']) or '无'}）")
        return r

    def circle(self, c):
        if c not in self.circles:
            X.die(f"圈子“{c}”不认识。有：{'、'.join(self.circles)}（剧本可在 rumors.json 的 circles 里改）")
        return self.circles[c]

    def fame_kind_of(self, c):
        return self.circles.get(c, {}).get("fame")


def json_copy(v):
    import json
    return json.loads(json.dumps(v))


def heat_word(h):
    return X.HEAT_WORDS[X.clamp(int(h), 0, 5)]


def cred_word(c):
    return X.CRED_WORDS[X.clamp(int(c), 0, 5)]


def active(r):
    return r["status"] in ("流传", "坐实")


def parse_effects(s):
    """名:士林=-1,军中=-1;名2:市井=+1 → {名: {士林: -1, ...}}"""
    out = {}
    if not s:
        return out
    for chunk in s.replace("；", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk and "：" not in chunk:
            X.die(f"--effect 写成 名:士林=-1,军中=-1（多人用分号隔开）：{chunk!r}")
        name, rest = chunk.replace("：", ":").split(":", 1)
        d = {}
        for tok in X.split_names(rest):
            k, _, v = tok.partition("=")
            d[k.strip()] = int(v)
        out[name.strip()] = d
    return out


def parse_kv(s, cast=int):
    out = {}
    for tok in X.split_names(s):
        if "=" not in tok:
            X.die(f"写成 键=值，逗号分隔：{tok!r}")
        k, v = tok.split("=", 1)
        out[k.strip()] = cast(v)
    return out


def fmt_rumor(B, r, gm=True, circle=None):
    hs = "，".join(f"{c}{heat_word(h)}" for c, h in r["heat"].items() if h > 0) or "已经没人提了"
    head = f"[{r['id']}] {r['text']}"
    parts = [f"可信：{cred_word(r['cred'])}（{r['cred']}）", f"流传：{hs}", f"状态：{r['status']}"]
    if gm:
        parts.insert(0, f"真假：{r['truth']}")
        parts.append(f"来源：{r.get('source') or '不明'}")
        if r.get("about"):
            parts.append(f"说的是：{'、'.join(r['about'])}")
        if r.get("from_doc"):
            parts.append(f"出自文献 {r['from_doc']}")
        if r.get("from_secret"):
            parts.append(f"由秘密 {r['from_secret']} 泄露")
        if r.get("gm_note"):
            parts.append(f"GM：{r['gm_note']}")
    return head + "\n      " + "｜".join(parts)


# ---------------------------------------------------------------- 名望的影响

def apply_effects(B, r, lines, force=False):
    """流言在某个圈子“传开了”（热度≥3）且“多半信了”（可信≥3）时，对应名望升降一次。返回改动 [(名, 种类, 旧, 新)]。"""
    changes = []
    applied = r.setdefault("applied", {})
    for name, eff in (r.get("effects") or {}).items():
        for kind, delta in eff.items():
            key = f"{name}|{kind}"
            if key in applied:
                continue
            hot = [c for c, h in r["heat"].items() if h >= 3 and B.fame_kind_of(c) == kind]
            if force or (hot and r["cred"] >= 3):
                applied[key] = delta
                changes.append((name, kind, delta, hot))
    return changes


def write_fame(B, changes, lines, apply):
    """changes: [(名, 种类, 增减, 原因)]。"""
    by = {}
    for name, kind, delta, why in changes:
        by.setdefault(name, []).append((kind, delta, why))
    for name, items in by.items():
        f = B.people.fame(name)
        old = dict(f)
        for kind, delta, why in items:
            f[kind] = X.clamp(f.get(kind, X.FAME_DEFAULT) + delta, 0, 10)
        diff = "，".join(f"{k} {old.get(k, X.FAME_DEFAULT)} → {f[k]}" for k, _, _ in items)
        lines.append(f"名望：{name} {diff}（{'；'.join(str(w) for _, _, w in items)}）")
        for k, _, _ in items:
            for lo in (3,):
                if old.get(k, X.FAME_DEFAULT) > lo >= f[k] and k == "军中":
                    lines.append(f"  提醒：{name} 在军中的名望跌到 {f[k]}。他麾下或奉他为主的将领，名分可 −1"
                                 f"（loyalty.py state --standing），GM 看流言说的是什么再定（rules/rumors.md 第三节）")
        if apply:
            where = B.people.set_fame(name, f)
            if where is None:
                lines.append(f"  注：{name} 不在人格卡或名册里，名望没处记。先用 persona.py gen {name} --role 身份 --apply")
            else:
                lines.append(f"  已写入 {where}")


# ---------------------------------------------------------------- 命令

def finish(B, args, extra=""):
    if getattr(args, "apply", False):
        print(f"\n已写入 {X.rel(B.save())}{extra}。")
    else:
        print("\n（未写入。确认无误后同一 seed 加 --apply。）")


def default_cred(B, source, circle):
    kind = B.fame_kind_of(circle)
    cred = 2
    if source and kind and source not in ("不明", "无名氏"):
        f = X.fame_of(B.people, source, kind)
        cred += 1 if f >= 6 else 0
        cred -= 1 if f <= 1 else 0
    return X.clamp(cred, 0, 5)


def cmd_spread(B, args):
    B.circle(args.circle)
    if args.truth not in TRUTH:
        X.die(f"--truth 只能是 {'/'.join(TRUTH)}")
    cred = args.cred if args.cred is not None else default_cred(B, args.source, args.circle)
    r = {"id": B.new_id("R"), "text": args.text, "truth": args.truth, "source": args.source or "不明",
         "about": X.split_names(args.about), "heat": {args.circle: X.clamp(args.heat, 1, 5)}, "cred": cred,
         "since_turn": X.turn_of(B.world), "when": X.when_of(B.world, args.when), "status": "流传",
         "effects": parse_effects(args.effect), "applied": {}, "age": 0, "gm_note": args.note or "", "log": []}
    if args.secret:
        r["from_secret"] = args.secret
    if args.doc:
        r["from_doc"] = args.doc
    for name, eff in r["effects"].items():
        for k in eff:
            if k not in B.kinds:
                X.die(f"--effect 里的“{k}”不是名望的种类（{'、'.join(B.kinds)}）")
    B.d["rumors"].append(r)
    print("新流言：" + fmt_rumor(B, r))
    if args.cred is None:
        print(f"  可信度按来源在{args.circle}的名望定：{cred}（{cred_word(cred)}）")
    if args.source and args.source != "不明" and args.truth == "假":
        print(f"  提醒：是谁放的这条假话，本身就是一条秘密：secrets.py add --title \"{args.source}造谣\" … --knower {args.source}=全知")
    finish(B, args)


def cmd_refute(B, args):
    r = B.rumor(args.id)
    rng = random.Random(args.seed)
    cs = [args.circle] if args.circle else [c for c, h in r["heat"].items() if h > 0]
    for c in cs:
        B.circle(c)
    lines = []
    kind = B.fame_kind_of(cs[0]) if cs else None
    f = X.fame_of(B.people, args.by, kind) if kind else X.FAME_DEFAULT
    force = 1 + (1 if f >= 7 else 0) + (1 if args.evidence else 0) + max(args.point or 0, 0)
    why = [f"辟谣的人在{kind or '这个圈子'}的名望 {f}" + ("（名重，+1）" if f >= 7 else ""),
           "有凭据 +1" if args.evidence else "没有凭据", f"说辞 {args.point or 0:+d}"]
    if args.by in r.get("about", []):
        force -= 1
        why.append("本人出来辟谣 −1")
    if (args.point or 0) < 0:
        force -= 1
    backfire = False
    if r["truth"] == "真" and not args.evidence:
        p = 0.25 + 0.05 * r["cred"]
        roll = rng.random()
        why.append(f"流言是真的、又拿不出凭据：越描越黑的机会 {p:.0%}，掷 {roll:.2f}")
        backfire = roll < p
    old = r["cred"]
    if backfire:
        r["cred"] = min(5, r["cred"] + 1)
        for c in cs:
            r["heat"][c] = min(5, r["heat"].get(c, 0) + 1)
        lines.append(f"越描越黑：可信 {old} → {r['cred']}，{'、'.join(cs)}的热度各 +1")
    else:
        force = max(force, 0)
        r["cred"] = max(0, r["cred"] - force)
        for c in cs:
            r["heat"][c] = max(0, r["heat"].get(c, 0) - 1)
        lines.append(f"辟谣：可信 {old} → {r['cred']}（降 {force}），{'、'.join(cs)}的热度各 −1")
    if r["cred"] <= 1 and not backfire:
        r["status"] = "已辟" if r["cred"] == 0 or not any(r["heat"].values()) else r["status"]
        restore = []
        for key, delta in list(r.get("applied", {}).items()):
            name, k = key.split("|")
            back = (1 if delta < 0 else -1) * ((abs(delta) + 1) // 2)
            if back:
                restore.append((name, k, back, f"{r['id']} 已被辟谣，回一半"))
        if restore:
            write_fame(B, restore, lines, args.apply)
    if r["status"] == "已辟":
        lines.append("这条流言算是辟清了（状态：已辟）；还记得的人，偶尔当笑话提起")
    r.setdefault("log", []).append(f"{X.when_of(B.world)}：{args.by}辟谣，可信 {old} → {r['cred']}" + ("（越描越黑）" if backfire else ""))
    print(f"=== 辟谣：[{r['id']}] {r['text']} ===")
    print("  " + "；".join(why))
    for l in lines:
        print("  " + l)
    if args.by not in r.get("about", []) and r.get("about"):
        print(f"  关系网：{'、'.join(r['about'])} 可记一份“辟谣”之恩：relations.py event 辟谣 --by {args.by} --to {r['about'][0]} --apply")
    finish(B, args)


def cmd_confirm(B, args):
    r = B.rumor(args.id)
    old = r["cred"]
    r["cred"] = 5
    r["status"] = "坐实"
    lines = [f"坐实：可信 {old} → 5（{args.why}）"]
    ch = apply_effects(B, r, lines, force=True)
    write_fame(B, [(n, k, d, f"{r['id']} 坐实") for n, k, d, _ in ch], lines, args.apply)
    r.setdefault("log", []).append(f"{X.when_of(B.world)}：坐实（{args.why}）")
    for l in lines:
        print("  " + l)
    finish(B, args)


def doc_season(B, rng, lines, proposals):
    for d in B.d["docs"]:
        if d.get("status") == "秘藏":
            continue
        for c in list(d.get("reach", {})):
            h = d["reach"][c]
            if d.get("status") == "禁毁":
                if rng.random() < 0.5 and h > 0:
                    d["reach"][c] = h - 1
                    lines.append(f"{d['title']}被禁，{c}里少有人敢传（流布 {h} → {h - 1}）")
                if B.fame_kind_of(c) == "市井" and rng.random() < 0.2 and d["reach"][c] < 5:
                    d["reach"][c] += 1
                    lines.append(f"{d['title']}越禁越有人私下传抄（{c} 流布 +1）")
                continue
            cap = d.get("weight", 1) + 2
            p = 0.25 + 0.05 * d.get("weight", 1)
            if 0 < h < cap and rng.random() < p:
                d["reach"][c] = h + 1
                lines.append(f"{d['title']}在{c}里又多了些读者（流布 {h} → {h + 1}）")
            # 往有往来的圈子流
            for c2, L in B.circles.get(c, {}).get("links", {}).items():
                if d["reach"].get(c2, 0) == 0 and h >= 2 and rng.random() < L * 0.4:
                    d["reach"][c2] = 1
                    lines.append(f"{d['title']}传到了{c2}（流布 1）")
        # 文献里的说法生出流言：流布 ≥2 的圈子，每季四分之一的机会，GM 确认后用 doc spawn
        for i, cl in enumerate(d.get("claims", []), 1):
            if cl.get("rumor"):
                continue
            hot = [c for c, h in d.get("reach", {}).items() if h >= 2]
            if hot and rng.random() < 0.25:
                c = rng.choice(hot)
                proposals.append(f"{d['id']} {d['title']}里的说法 {i}“{cl['text']}”在{c}被人拿出来说："
                                 f"rumors.py doc spawn {d['id']} --claim-no {i} --circle {c} --apply")


def cmd_season(B, args):
    turn = X.turn_of(B.world)
    if B.d.get("last_season_turn") == turn and not args.force:
        X.die(f"第 {turn} 回合的流言已经推进过。确要重跑加 --force")
    rng = random.Random(args.seed if args.seed is not None else turn * 104729 + 7)
    print(f"=== 流言季末：{X.when_of(B.world, args.when)}（第 {turn} 回合，seed={args.seed if args.seed is not None else '按回合'}） ===")
    lines, fame_changes = [], []
    for r in B.d["rumors"]:
        if not active(r):
            continue
        r["age"] = r.get("age", 0) + 1
        old = dict(r["heat"])
        new = dict(old)
        cred = r["cred"]
        notes = []
        raised = set()
        for c, h in old.items():
            if h <= 0:
                continue
            # 往外传
            for c2, L in B.circles.get(c, {}).get("links", {}).items():
                if old.get(c2, 0) >= h:
                    continue
                p = min(0.9, L * (h / 3) * (0.5 + cred / 10))
                if rng.random() < p and c2 not in raised:
                    new[c2] = max(new.get(c2, 0), old.get(c2, 0) + 1)
                    raised.add(c2)
                    notes.append(f"传到{c2}（{heat_word(new[c2])}）")
            # 圈子里越传越开，或者淡下去
            grow = 0.25 + 0.05 * (cred - 3) if cred >= 3 and h < 5 and r["age"] <= 4 and r["status"] != "坐实" else 0
            decay = max(0.05, 0.45 - 0.08 * cred) + 0.1 * max(0, r["age"] - 4)
            if r["status"] == "坐实":
                decay = 0.15 + 0.1 * max(0, r["age"] - 6)
            if r["age"] <= 1:
                decay = 0      # 这一季刚冒出来的流言，这一季不会淡下去
            x = rng.random()
            if c in raised:
                continue       # 这一季刚从别处传进来，不再另算涨落
            if x < grow:
                new[c] = min(5, new.get(c, h) + 1)
                raised.add(c)
                notes.append(f"{c}越传越开（{heat_word(new[c])}）")
            elif x > 1 - decay:
                new[c] = max(0, min(new.get(c, h), h) - 1)
                notes.append(f"{c}里提的人少了（{heat_word(new[c])}）")
        r["heat"] = {c: h for c, h in new.items() if h > 0 or c in old}
        if not any(r["heat"].values()):
            r["status"] = "消退"
            notes.append("已经没人提了 → 消退")
        if notes:
            lines.append(f"[{r['id']}] {r['text'][:30]}：" + "；".join(notes))
        ch = apply_effects(B, r, lines)
        for n, k, d, hot in ch:
            fame_changes.append((n, k, d, f"{r['id']} 在{'、'.join(hot)}传开、多半信了"))
    proposals = []
    doc_season(B, rng, lines, proposals)
    for l in lines or ["（各条流言都没什么动静）"]:
        print("  " + l)
    if fame_changes:
        out = []
        write_fame(B, fame_changes, out, args.apply)
        print("--- 名望 ---")
        for l in out:
            print("  " + l)
    if proposals:
        print("--- 文献生出流言（GM 确认后跑） ---")
        for p in proposals:
            print("  · " + p)
    print("--- 各圈子眼下最热的 ---")
    for c in B.circles:
        hot = sorted((r for r in B.d["rumors"] if active(r) and r["heat"].get(c, 0) > 0),
                     key=lambda r: -r["heat"][c])[:3]
        if hot:
            print(f"  {c}：" + "；".join(f"[{r['id']}]{r['text'][:18]}（{heat_word(r['heat'][c])}）" for r in hot))
    B.d["last_season_turn"] = turn
    finish(B, args)


def cmd_circle(B, args):
    B.circle(args.circle)
    rows = sorted((r for r in B.d["rumors"] if active(r) and r["heat"].get(args.circle, 0) >= args.min_heat),
                  key=lambda r: -r["heat"][args.circle])
    print(f"=== {args.circle}里眼下流传的（{B.circles[args.circle].get('note', '')}） ===")
    for r in rows:
        print(f"  [{r['id']}] {r['text']}——{heat_word(r['heat'][args.circle])}，{cred_word(r['cred'])}"
              + (f"｜GM：{r['truth']}，来源 {r.get('source')}" if args.gm else ""))
    docs = [d for d in B.d["docs"] if d.get("reach", {}).get(args.circle, 0) > 0]
    for d in docs:
        print(f"  文献：{d['title']}（{d['kind']}）——流布 {d['reach'][args.circle]}" + ("，已禁" if d.get("status") == "禁毁" else ""))
    if not rows and not docs:
        print("  （没什么新鲜的）")


def heard_by(B, name, people=None):
    """这个人听到过的流言：他所在的圈子里热度 ≥2；消息灵通的人 ≥1；流言的来源、说到的人总知道。"""
    cs = X.person_circles(B.world, name, people or B.people)
    sharp = "消息灵通" in (people or B.people).tags(name)
    out = []
    for r in B.d["rumors"]:
        if r["status"] == "消退" and name not in r.get("about", []):
            continue
        where = [c for c in cs if r["heat"].get(c, 0) >= (1 if sharp else 2)]
        if where or name == r.get("source") or (name in r.get("about", []) and any(h >= 2 for h in r["heat"].values())):
            out.append((r, where))
    return cs, out


def docs_read_by(B, name, people=None):
    cs = X.person_circles(B.world, name, people or B.people)
    out = []
    lit = (people or B.people).attrs(name).get("学", 5) >= 3
    for d in B.d["docs"]:
        if name in d.get("holders", []) or name == d.get("author"):
            out.append((d, "手里有"))
        elif lit and any(d.get("reach", {}).get(c, 0) >= 2 for c in cs):
            out.append((d, "读到过或听人讲过"))
    return out


def cmd_heard(B, args):
    cs, rows = heard_by(B, args.name)
    print(f"=== {args.name} 听到过的流言（他在：{'、'.join(cs) or '没有登记圈子'}） ===")
    for r, where in rows:
        src = "（他自己放出去的）" if args.name == r.get("source") else ("（说的是他）" if args.name in r.get("about", []) else "")
        print(f"  [{r['id']}] {r['text']}——{('在' + '、'.join(where) + '听到') if where else ''}{src}，他估摸着{cred_word(r['cred'])}")
    if not rows:
        print("  （没听到什么）")
    for d, how in docs_read_by(B, args.name):
        print(f"  文献：{d['title']}（{how}）：{d['summary']}")


def cmd_show(B, args):
    rows = [B.rumor(args.id)] if args.id else B.d["rumors"]
    print("=== 流言（GM 全知） ===")
    for r in rows:
        if args.id or args.all or active(r):
            print("  " + fmt_rumor(B, r))
            if args.id:
                for l in r.get("log", []):
                    print(f"      · {l}")
    print("  圈子：" + "；".join(f"{c}（口碑算进{v.get('fame') or '—'}）" for c, v in B.circles.items()))


def cmd_fame(B, args):
    f = B.people.fame(args.name)
    old = dict(f)
    if args.set:
        for k, v in parse_kv(args.set).items():
            if k not in B.kinds:
                X.die(f"名望的种类只有 {'、'.join(B.kinds)}")
            f[k] = X.clamp(v, 0, 10)
    if args.delta:
        if not args.why:
            X.die("改名望要用 --why 写明缘由")
        for k, v in parse_kv(args.delta).items():
            if k not in B.kinds:
                X.die(f"名望的种类只有 {'、'.join(B.kinds)}")
            f[k] = X.clamp(f.get(k, X.FAME_DEFAULT) + v, 0, 10)
    print(f"=== 名望：{args.name} ===")
    for k in B.kinds:
        mark = f"（{old.get(k)} → {f[k]}）" if old.get(k) != f[k] else ""
        print(f"  {X.pad(k, 6)} {f[k]:2d}  {X.fame_word(f[k])}{mark}")
    if args.set or args.delta:
        if args.why:
            print(f"  缘由：{args.why}")
        if args.apply:
            where = B.people.set_fame(args.name, f)
            print(f"\n已写入 {where}。" if where else f"\n{args.name} 不在人格卡或名册里，没处记。")
        else:
            print("\n（未写入。确认无误后加 --apply。）")


def cmd_doc(B, args):
    if args.action == "add":
        if not args.title or not args.summary:
            X.die("doc add 要 --title 和 --summary")
        if args.kind not in DOC_KINDS:
            X.die(f"--kind 只能是 {'/'.join(DOC_KINDS)}")
        claims = []
        for c in args.claim or []:
            text, _, truth = c.rpartition("=")
            if truth not in TRUTH:
                X.die(f"--claim 写成 说法=真|假|半真：{c!r}")
            claims.append({"text": text, "truth": truth})
        reach = parse_kv(args.reach) if args.reach else {}
        for c in reach:
            B.circle(c)
        d = {"id": B.new_id("D"), "title": args.title if args.title.startswith("《") else f"《{args.title}》",
             "kind": args.kind, "author": args.author or "佚名", "summary": args.summary, "claims": claims,
             "reach": reach, "holders": X.split_names(args.holders), "weight": X.clamp(args.weight, 1, 3),
             "status": args.status or "流传", "since_turn": X.turn_of(B.world), "log": []}
        B.d["docs"].append(d)
        print_doc(B, d)
        return finish(B, args)
    if args.action == "show":
        for d in ([B.doc(args.id)] if args.id else B.d["docs"]):
            print_doc(B, d)
        return
    d = B.doc(args.id or X.die("要给文献编号"))
    if args.action == "spawn":
        if not args.claim_no or not args.circle:
            X.die("doc spawn 要 --claim-no 序号 和 --circle 圈子")
        cl = d["claims"][args.claim_no - 1]
        B.circle(args.circle)
        cred = X.clamp(2 + (1 if d.get("weight", 1) >= 3 else 0)
                       + (1 if X.fame_of(B.people, d.get("author"), B.fame_kind_of(args.circle) or "士林") >= 7 else 0), 0, 5)
        r = {"id": B.new_id("R"), "text": cl["text"], "truth": cl["truth"], "source": f"{d['title']}",
             "about": X.split_names(args.about), "heat": {args.circle: 1 + (1 if d["reach"].get(args.circle, 0) >= 3 else 0)},
             "cred": cred, "since_turn": X.turn_of(B.world), "when": X.when_of(B.world), "status": "流传",
             "effects": parse_effects(args.effect), "applied": {}, "age": 0, "from_doc": d["id"], "gm_note": "", "log": []}
        cl["rumor"] = r["id"]
        B.d["rumors"].append(r)
        print("文献生出流言：" + fmt_rumor(B, r))
        return finish(B, args)
    if args.action == "ban":
        d["status"] = "禁毁"
        d["log"].append(f"{X.when_of(B.world)}：禁毁（{args.why or ''}）")
        print(f"{d['title']} 禁毁。此后各圈子的流布每季一半的机会 −1，市井里两成的机会越禁越传。藏书的人：{'、'.join(d.get('holders', [])) or '不明'}")
        print("  禁书在朝堂上被人引用，辩论里另 −0.5（cite），引的人也担风险。")
        return finish(B, args)
    if args.action == "give":
        for n in X.split_names(args.holders):
            if n not in d["holders"]:
                d["holders"].append(n)
        print(f"{d['title']} 现在在这些人手里：{'、'.join(d['holders'])}")
        return finish(B, args)


def print_doc(B, d):
    print(f"[{d['id']}] {d['title']}（{d['kind']}，{d.get('author', '佚名')}；分量 {d.get('weight', 1)}；{d.get('status', '流传')}）")
    print(f"      摘要：{d['summary']}")
    for i, c in enumerate(d.get("claims", []), 1):
        print(f"      说法 {i}：{c['text']}（GM：{c['truth']}）" + (f" → 已生出流言 {c['rumor']}" if c.get("rumor") else ""))
    print(f"      流布：{'，'.join(f'{c}{h}' for c, h in d.get('reach', {}).items()) or '无'}；手里有的人：{'、'.join(d.get('holders', [])) or '—'}")


def cite_value(world, doc_ref, fit, audience=None):
    """辩论里引用文献：返回 (每轮加减, 说明)。contest.py --cite-a 也用它。"""
    B = Board(world)
    d = B.doc(doc_ref)
    if fit not in FITS:
        X.die(f"引用得当不得当只能是 {'/'.join(FITS)}")
    reach = d.get("reach", {}).get(audience, 0) if audience else max(d.get("reach", {}).values() or [0])
    why = []
    if fit == "得当":
        v = 0.5
        why.append("引得得当 +0.5")
        if d.get("weight", 1) >= 2 and reach >= 2:
            v += 0.5
            why.append(f"在座的人多半读过（流布 {reach}）、文献有分量，+0.5")
    elif fit == "牵强":
        v = 0.0
        why.append("引得牵强 0")
        if reach >= 3:
            v -= 0.5
            why.append(f"在座的人都读过（流布 {reach}），看得出是牵强附会，−0.5")
    else:
        v = -1.0
        why.append("引错了、断章取义，−1")
    if d.get("status") == "禁毁":
        v -= 0.5
        why.append("引的是禁书，−0.5（引的人也担风险）")
    v = X.clamp(v, -1.5, 1.0)
    return v, f"{d['title']}：" + "，".join(why) + f" → 每轮 {v:+.1f}"


def cmd_cite(B, args):
    v, why = cite_value(B.world, args.id, args.fit, args.audience)
    print(why)
    print(f"接到 contest.py：--cite-a \"{args.id}={args.fit}\"（或 --cite-b），脚本按同一办法算。")


def main():
    ap = argparse.ArgumentParser(description="流言、名望与文献（规则见 rules/rumors.md）",
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

    p = add("spread", "放出一条流言", cmd_spread)
    p.add_argument("--text", required=True)
    p.add_argument("--truth", required=True, choices=TRUTH)
    p.add_argument("--circle", required=True)
    p.add_argument("--source")
    p.add_argument("--about")
    p.add_argument("--heat", type=int, default=1)
    p.add_argument("--cred", type=int)
    p.add_argument("--effect", help="名:士林=-1,军中=-1；多人用分号隔开")
    p.add_argument("--secret", help="由哪条秘密泄露出来")
    p.add_argument("--doc", help="出自哪部文献")
    p.add_argument("--note")
    p.add_argument("--when")
    p = add("refute", "辟谣", cmd_refute)
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p.add_argument("--circle")
    p.add_argument("--evidence", help="拿出来的凭据（文献编号、证据编号、人证）")
    p.add_argument("--point", type=int, choices=(-1, 0, 1, 2), help="辟谣的说辞，GM 照辩论的刻度打")
    p.add_argument("--seed", type=int)
    p = add("confirm", "坐实", cmd_confirm)
    p.add_argument("id")
    p.add_argument("--why", required=True)
    p = add("season", "季末传播", cmd_season)
    p.add_argument("--seed", type=int)
    p.add_argument("--when")
    p.add_argument("--force", action="store_true")
    p = add("circle", "一个圈子里流传什么", cmd_circle, write=False)
    p.add_argument("circle")
    p.add_argument("--gm", action="store_true")
    p.add_argument("--min-heat", type=int, default=1)
    p = add("heard", "一个人听到过什么", cmd_heard, write=False)
    p.add_argument("name")
    p = add("show", "全部流言", cmd_show, write=False)
    p.add_argument("id", nargs="?")
    p.add_argument("--all", action="store_true")
    p = add("fame", "查或改名望", cmd_fame)
    p.add_argument("name")
    p.add_argument("--set")
    p.add_argument("--delta")
    p.add_argument("--why")
    p = add("doc", "文献", cmd_doc)
    p.add_argument("action", choices=("add", "show", "spawn", "ban", "give"))
    p.add_argument("id", nargs="?")
    p.add_argument("--title")
    p.add_argument("--kind", default="书")
    p.add_argument("--author")
    p.add_argument("--summary")
    p.add_argument("--claim", action="append", help="说法=真|假|半真（add）；可重复")
    p.add_argument("--claim-no", dest="claim_no", type=int, help="spawn：第几个说法")
    p.add_argument("--reach", help="士林=2,市井=1")
    p.add_argument("--holders")
    p.add_argument("--weight", type=int, default=1)
    p.add_argument("--status", choices=("流传", "禁毁", "秘藏"))
    p.add_argument("--circle")
    p.add_argument("--about")
    p.add_argument("--effect")
    p.add_argument("--why")
    p = add("cite", "辩论里引用文献的加减", cmd_cite, write=False)
    p.add_argument("id")
    p.add_argument("--fit", required=True, choices=FITS)
    p.add_argument("--audience", help="在座的人属于哪个圈子（朝堂、士林……）")
    args = ap.parse_args()
    args.fn(Board(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
