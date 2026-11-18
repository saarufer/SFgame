#!/usr/bin/env python3
"""秘密与知情：谁知道什么、知道多少、证据在谁手里；季末泄露检定；把柄；以及给角色 agent 的“情报包”。
规则见 rules/secrets.md。只用标准库。

存档是 world/secrets.json。会改存档的命令默认只打印，加 --apply 才写回；掷骰的命令支持 --seed。

  登记     add --title 题目 --truth 真相 [--cover 外面的说法] [--about 名,名] [--danger 1-3]
               [--knower 名=全知|大略|风闻[:怎么知道的] …] [--evidence 书信|人证|物证|账册:描述@持有人 …]
  得知     learn 编号 --who 名 --depth 全知|大略|风闻 [--how 亲历|亲见|转述|推测|供状|书信] [--from 名] [--knows 他知道的那一截]
  证据     evidence 编号 [--add 种类:描述@持有人] [--move 证据编号 --to 名] [--status 证据编号=毁|失|呈上]
  查看     show [编号]  |  known 名                  某人知道哪些秘密、手里有什么证据
  泄露     season [--seed N] [--when 时间]          每条未泄的秘密掷一次泄露；泄了的变成流言（rumors.json）
           leak 编号 --by 名 [--circle 圈子]        有人故意把它说出去（不掷骰）
  外象     expose 编号 --level 0-3 --why …      旁人从外面看得出多少端倪（病中久不视朝、账目对不上），每档每季 +5%
  把柄     leverage 编号 --by 甲 --on 乙 --demand 要他做什么
  情报包   brief 名 [--with 在场的人,…] [--json]    调用任何角色 agent 前，生成“此人知道什么”

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

FILE = "secrets.json"
EMPTY = {"version": 1, "secrets": [], "next": 1, "last_season_turn": 0}
DEPTHS = ("全知", "大略", "风闻")
HOWS = ("亲历", "亲见", "转述", "推测", "供状", "书信")
EV_KINDS = ("书信", "人证", "物证", "账册")
EV_STATUS = ("在", "毁", "失", "呈上")
DANGER = {1: "传出去难堪", 2: "传出去丢官、失宠", 3: "传出去要掉脑袋、动摇大位"}

# 口风：每季把秘密说漏的机会（rules/secrets.md 第三节）
LOOSE = {"嘴不严": 0.12, "贪杯": 0.06, "消息灵通": 0.05, "能说会道": 0.03, "好面子": 0.02}
BASE_LEAK = 0.03


class Vault:
    def __init__(self, world):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        for k, v in EMPTY.items():
            self.d.setdefault(k, json.loads(json.dumps(v)))
        self._people = None

    @property
    def people(self):
        if self._people is None:
            self._people = X.People(self.world)
        return self._people

    def save(self):
        return X.save_json(self.world, FILE, self.d)

    def get(self, sid):
        s = next((x for x in self.d["secrets"] if x["id"] == sid), None)
        if not s:
            X.die(f"没有秘密 {sid}（有：{'、'.join(x['id'] for x in self.d['secrets']) or '无'}）")
        return s


def knower(s, name):
    return next((k for k in s["knowers"] if k["name"] == name), None)


def parse_knower(tok):
    name, _, rest = tok.partition("=")
    depth, _, how = rest.partition(":")
    if depth not in DEPTHS:
        X.die(f"--knower 写成 名=全知|大略|风闻[:怎么知道的]：{tok!r}")
    return {"name": name.strip(), "depth": depth, "how": how or "亲历"}


def parse_ev(tok, n):
    kind, _, rest = tok.partition(":")
    desc, _, holder = rest.rpartition("@")
    if kind not in EV_KINDS or not holder:
        X.die(f"--evidence 写成 书信|人证|物证|账册:描述@持有人：{tok!r}")
    return {"id": f"E{n}", "kind": kind, "desc": desc, "holder": holder.strip(), "status": "在"}


def next_ev(V):
    n = 1
    for s in V.d["secrets"]:
        for e in s.get("evidence", []):
            try:
                n = max(n, int(e["id"][1:]) + 1)
            except ValueError:
                pass
    return n


def what_he_knows(s, k):
    """按知道的程度给出他知道的内容。知情人条目里写了 knows（他自己知道的那一截）的，大略、风闻照它给。"""
    if k["depth"] == "全知":
        return s["truth"]
    if k.get("knows"):
        return f"{k['knows']}" + ("（只知大略，细处不清）" if k["depth"] == "大略" else "（风闻，背后似乎另有隐情）")
    if k["depth"] == "大略":
        return f"{s['truth']}（只知大略，细处不清）"
    return f"风闻：{s.get('cover') or s['title']}，背后似乎另有隐情"


def fmt_secret(s):
    ks = "、".join(f"{k['name']}（{k['depth']}，{k.get('how', '')}）" for k in s["knowers"]) or "无人"
    ev = "；".join(f"{e['id']} {e['kind']}：{e['desc']}，在{e['holder']}手里（{e['status']}）" for e in s.get("evidence", [])) or "无"
    return (f"[{s['id']}] {s['title']}（{DANGER.get(s.get('danger', 2), '')}；{s['status']}）\n"
            f"      真相：{s['truth']}\n      外面的说法：{s.get('cover') or '—'}\n"
            f"      说的是：{'、'.join(s.get('about', [])) or '—'}\n      知情：{ks}\n      证据：{ev}"
            + (f"\n      已泄成流言 {s['rumor']}" if s.get("rumor") else ""))


def finish(V, args, extra=""):
    if getattr(args, "apply", False):
        print(f"\n已写入 {X.rel(V.save())}{extra}。")
    else:
        print("\n（未写入。确认无误后同一 seed 加 --apply。）")


# ---------------------------------------------------------------- 命令

def cmd_add(V, args):
    s = {"id": f"S{V.d['next']}", "title": args.title, "truth": args.truth, "cover": args.cover or "",
         "about": X.split_names(args.about), "danger": args.danger, "since_turn": X.turn_of(V.world),
         "when": X.when_of(V.world, args.when), "knowers": [], "evidence": [], "status": "隐", "rumor": None,
         "leak_log": [], "uses": [], "note": args.note or ""}
    for tok in args.knower or []:
        k = parse_knower(tok)
        k["since_turn"] = s["since_turn"]
        s["knowers"].append(k)
    n = next_ev(V)
    for tok in args.evidence or []:
        s["evidence"].append(parse_ev(tok, n))
        n += 1
    V.d["next"] += 1
    V.d["secrets"].append(s)
    print("登记秘密：" + fmt_secret(s))
    print(f"  每季泄露的机会（按眼下的知情人）：{leak_chance(V, s)[0]:.0%}")
    finish(V, args)


def cmd_learn(V, args):
    s = V.get(args.id)
    if args.depth not in DEPTHS:
        X.die(f"--depth 只能是 {'/'.join(DEPTHS)}")
    k = knower(s, args.who)
    order = {d: i for i, d in enumerate(DEPTHS)}
    if k:
        if order[args.depth] < order[k["depth"]]:
            print(f"{args.who} 原先{k['depth']}，现在{args.depth}")
            k["depth"] = args.depth
            k["how"] = args.how or k.get("how")
        else:
            print(f"{args.who} 早已知道（{k['depth']}），不变")
    else:
        k = {"name": args.who, "depth": args.depth, "how": args.how or "转述", "since_turn": X.turn_of(V.world)}
        if args.from_:
            k["from"] = args.from_
        s["knowers"].append(k)
        print(f"{args.who} 得知 [{s['id']}] {s['title']}：{args.depth}（{k['how']}" + (f"，听{args.from_}说" if args.from_ else "") + "）")
    if args.knows and k["depth"] != "全知":
        k["knows"] = args.knows
    print(f"  他知道的是：{what_he_knows(s, k)}")
    print(f"  知情 {len(s['knowers'])} 人；每季泄露的机会 {leak_chance(V, s)[0]:.0%}")
    if args.from_:
        print(f"  {args.from_} 把这件事告诉了 {args.who}：两人之间多了一层信任，或者一个把柄（GM 照 relations.py 记）")
    finish(V, args)


def cmd_evidence(V, args):
    s = V.get(args.id)
    if args.add:
        e = parse_ev(args.add, next_ev(V))
        s["evidence"].append(e)
        print(f"新证据 {e['id']}：{e['kind']}，{e['desc']}，在{e['holder']}手里")
    if args.move:
        e = next((e for e in s["evidence"] if e["id"] == args.move), None) or X.die(f"没有证据 {args.move}")
        old = e["holder"]
        e["holder"] = args.to or X.die("--move 要配 --to")
        print(f"证据 {e['id']} 从{old}手里到了{e['holder']}手里")
        if not knower(s, e["holder"]):
            s["knowers"].append({"name": e["holder"], "depth": "大略", "how": "书信" if e["kind"] == "书信" else "亲见",
                                 "since_turn": X.turn_of(V.world)})
            print(f"  {e['holder']} 拿到证据，算知道了大略（learn 可改）")
    if args.status:
        eid, _, st = args.status.partition("=")
        if st not in EV_STATUS:
            X.die(f"证据状态只能是 {'/'.join(EV_STATUS)}")
        e = next((e for e in s["evidence"] if e["id"] == eid), None) or X.die(f"没有证据 {eid}")
        e["status"] = st
        print(f"证据 {eid} → {st}")
        if st == "呈上":
            print("  证据摆到了朝堂或定夺者面前：说这件事的流言可以坐实（rumors.py confirm），奏疏里算一件凭据（court.py memorial --evidence）")
    finish(V, args)


def cmd_expose(V, args):
    s = V.get(args.id)
    old = int(s.get("exposure", 0))
    s["exposure"] = args.level
    s.setdefault("leak_log", []).append(f"{X.when_of(V.world)}：外象 {old} → {args.level}（{args.why}）")
    print(f"[{s['id']}] {s['title']}：外象 {old} → {args.level}（{args.why}）；每季泄露的机会 {leak_chance(V, s)[0]:.0%}")
    finish(V, args)


def cmd_show(V, args):
    rows = [V.get(args.id)] if args.id else V.d["secrets"]
    print("=== 秘密（GM 全知） ===")
    for s in rows:
        print("  " + fmt_secret(s))
        if s["status"] == "隐":
            p, parts = leak_chance(V, s)
            print(f"      每季泄露 {p:.0%}：" + "；".join(f"{n} {x:.0%}" for n, x in parts))
        for u in s.get("uses", []):
            print(f"      把柄：{u}")


def known_by(V, name):
    out = []
    for s in V.d["secrets"]:
        k = knower(s, name)
        held = [e for e in s.get("evidence", []) if e["holder"] == name and e["status"] == "在"]
        if k or held:
            out.append((s, k, held))
    return out


def cmd_known(V, args):
    rows = known_by(V, args.name)
    print(f"=== {args.name} 知道的秘密 ===")
    for s, k, held in rows:
        depth = k["depth"] if k else "（只拿着证据）"
        print(f"  [{s['id']}] {s['title']}：{depth}" + (f"（{k.get('how')}）" if k else ""))
        if k:
            print(f"      {what_he_knows(s, k)}")
        for e in held:
            print(f"      手里有 {e['id']} {e['kind']}：{e['desc']}")
    if not rows:
        print("  （没有）")


def leak_chance(V, s):
    """每个知情人每季说漏的机会，合起来。返回 (合计, [(名, 机会)])。"""
    parts = []
    try:
        import relations as REL
        net = REL.Net(V.world)
    except SystemExit:
        net = None
    try:
        out = X.load_json(V.world, "court.json", {}).get("out", {})
    except SystemExit:
        out = {}
    for k in s["knowers"]:
        n = k["name"]
        if out.get(n, {}).get("status") == "死":
            continue
        tags = V.people.tags(n)
        attrs = V.people.attrs(n)
        p = BASE_LEAK + sum(v for t, v in LOOSE.items() if t in tags)
        if attrs.get("智", 5) >= 7:
            p -= 0.01
        if attrs.get("胆", 5) <= 3:
            p -= 0.01
        if k["depth"] == "风闻":
            p *= 0.5
        if n in s.get("about", []):
            p *= 0.3          # 说的就是他自己，守得紧
        elif net is not None and s.get("about"):
            c = max(net.closeness(n, a) for a in s["about"])
            cmin = min(net.closeness(n, a) for a in s["about"])
            if c >= 2:
                p *= 0.5      # 护着他
            elif cmin <= -2:
                p *= 2.0      # 巴不得他出事
        p *= {1: 1.3, 2: 1.0, 3: 0.6}.get(int(s.get("danger", 2)), 1.0)
        p = X.clamp(p, 0.0, 0.4)
        parts.append((n, p))
    for e in s.get("evidence", []):
        if e["status"] == "在":
            parts.append((f"证据 {e['id']}（{e['kind']}在{e['holder']}手里）", 0.03 if e["kind"] == "书信" else 0.02))
    if int(s.get("exposure", 0)):
        parts.append((f"外象 {s['exposure']}（旁人看得出端倪）", 0.05 * int(s["exposure"])))
    q = 1.0
    for _, p in parts:
        q *= (1 - p)
    return 1 - q, parts


def make_rumor(V, s, leaker, circle=None, depth=None):
    """泄露的秘密变成一条流言（还没写进 rumors.json）。"""
    import rumors as R
    B = R.Board(V.world)
    k = knower(s, leaker)
    depth = depth or (k["depth"] if k else "大略")
    cs = X.person_circles(V.world, leaker, V.people) if leaker and not leaker.startswith("证据") else []
    circle = circle or (cs[0] if cs else next(iter(B.circles)))
    cred = {"全知": 3, "大略": 3, "风闻": 2}[depth]
    if any(e["holder"] == leaker and e["status"] == "在" for e in s.get("evidence", [])):
        cred += 1
    if depth == "大略" and k and k.get("knows"):
        text = k["knows"]
    elif depth == "风闻":
        text = f"{(k or {}).get('knows') or s.get('cover') or s['title']}，听说另有隐情"
    else:
        text = s["truth"]
    heat = 2 if leaker and any(t in V.people.tags(leaker) for t in ("嘴不严", "消息灵通")) else 1
    return B, {"text": text, "truth": "真" if depth != "风闻" else "半真", "circle": circle, "cred": X.clamp(cred, 0, 5),
               "heat": heat, "about": s.get("about", []), "depth": depth}


def write_rumor(V, B, s, prop, leaker, apply):
    r = {"id": B.new_id("R"), "text": prop["text"], "truth": prop["truth"], "source": leaker or "不明",
         "about": prop["about"], "heat": {prop["circle"]: prop["heat"]}, "cred": prop["cred"],
         "since_turn": X.turn_of(V.world), "when": X.when_of(V.world), "status": "流传", "effects": {},
         "applied": {}, "age": 0, "from_secret": s["id"],
         "gm_note": f"由秘密 {s['id']} 泄露（{prop['depth']}）；名望的影响由 GM 用 rumors.py 补 effects", "log": []}
    B.d["rumors"].append(r)
    s["status"] = "已泄"
    s["rumor"] = r["id"]
    s["leak_log"].append(f"{X.when_of(V.world)}：{leaker or '不明'}说漏，成了流言 {r['id']}（{prop['circle']}）")
    if apply:
        B.save()
    return r


def cmd_season(V, args):
    turn = X.turn_of(V.world)
    if V.d.get("last_season_turn") == turn and not args.force:
        X.die(f"第 {turn} 回合的秘密已经检定过。确要重跑加 --force")
    rng = random.Random(args.seed if args.seed is not None else turn * 7907 + 3)
    print(f"=== 秘密季末：{X.when_of(V.world, args.when)}（第 {turn} 回合）泄露检定 ===")
    any_leak = False
    for s in V.d["secrets"]:
        if s["status"] != "隐":
            continue
        p, parts = leak_chance(V, s)
        r = rng.random()
        line = f"  [{s['id']}] {s['title']}：知情 {len(s['knowers'])} 人，泄露 {p:.0%}，掷 {r:.2f}"
        if r >= p:
            print(line + " → 守住了")
            continue
        any_leak = True
        tot = sum(x for _, x in parts) or 1
        pick = rng.random() * tot
        acc, leaker = 0, parts[0][0]
        for n, x in parts:
            acc += x
            if pick <= acc:
                leaker = n
                break
        if leaker.startswith("外象"):
            src, depth, circle = None, "风闻", None
            who = "没有谁说漏，是旁人从外象里看出了端倪"
        elif leaker.startswith("证据"):
            eid = leaker.split()[1].rstrip("（")
            ev = next((e for e in s.get("evidence", []) if e["id"] == eid), {})
            src, depth = None, "大略"
            cs = X.person_circles(V.world, ev.get("holder", ""), V.people)
            circle = cs[0] if cs else None
            who = f"证据 {eid}（{ev.get('kind', '')}）经了别人的手，有人看到了"
        else:
            src, depth, circle, who = leaker, None, None, f"说漏的是：{leaker}"
        if circle is None and src is None:
            cs = [c for a in s.get("about", []) for c in X.person_circles(V.world, a, V.people)]
            circle = cs[0] if cs else None
        B, prop = make_rumor(V, s, src, circle, depth)
        print(line + f" → 泄露了。{who}")
        print(f"      变成流言：“{prop['text']}”——在{prop['circle']}{X.HEAT_WORDS[prop['heat']]}，可信 {prop['cred']}（{prop['depth']}）")
        r2 = write_rumor(V, B, s, prop, src, args.apply)
        print(f"      流言编号 {r2['id']}" + ("（已写入 rumors.json）" if args.apply else "（加 --apply 写入）")
              + "。GM 可改措辞，再用 rumors.py 给它补名望的影响。")
    if not any_leak:
        print("  这一季没有秘密传出去。")
    V.d["last_season_turn"] = turn
    finish(V, args)


def cmd_leak(V, args):
    s = V.get(args.id)
    B, prop = make_rumor(V, s, args.by, args.circle)
    print(f"{args.by} 把 [{s['id']}] {s['title']} 说了出去（故意的，不掷骰）：")
    print(f"  流言：“{prop['text']}”——在{prop['circle']}，可信 {prop['cred']}")
    r = write_rumor(V, B, s, prop, args.by, args.apply)
    print(f"  流言编号 {r['id']}")
    if s.get("about"):
        print(f"  关系网：{'、'.join(s['about'])} 知道是他说出去的，记一笔怨：relations.py event 背约 --by {args.by} --to {s['about'][0]} --apply")
    finish(V, args)


def cmd_leverage(V, args):
    s = V.get(args.id)
    k = knower(s, args.by)
    if not k:
        X.die(f"{args.by} 不知道 [{s['id']}]，拿不来要挟人")
    held = [e for e in s.get("evidence", []) if e["holder"] == args.by and e["status"] == "在"]
    danger = int(s.get("danger", 2))
    pressure = danger + (1 if held else 0) + (1 if k["depth"] == "全知" else 0) - (1 if k["depth"] == "风闻" else 0)
    stake = args.on in s.get("about", [])
    if not stake:
        pressure -= 1
    print(f"=== 把柄：{args.by} 拿 [{s['id']}] {s['title']} 要挟 {args.on} ===")
    print(f"  要他做的事：{args.demand}")
    print(f"  分量 {pressure}：秘密的分量 {danger}（{DANGER.get(danger)}）"
          + ("，手里有证据 +1" if held else "，手里没证据") + (f"，{args.by}知道全部 +1" if k["depth"] == "全知" else "")
          + (f"，{args.by}只是风闻 −1" if k["depth"] == "风闻" else "") + ("" if stake else f"，说的不是{args.on}本人 −1"))
    print("  他能怎么应（不掷骰，GM 召他的 agent 按人格卡定；分量越重，越难不理）：")
    print("    · 从：照办。记账见下。")
    print("    · 拖：敷衍、讨价还价，看对方有没有真凭据。分量 ≤2 的多半会拖。")
    print("    · 反制：拿对方的把柄回敬（secrets.py known 看他知道对方什么）、先去定夺者面前自首。")
    print("    · 灭口、毁证：要走 household.py plot 或别的规矩；毁证用 evidence --status Ex=毁。")
    print("  记账（--apply 写关系网）：")
    print(f"    · {args.on} 记 {args.by} 一笔怨（2，两人知道）")
    cp = V.people.card_path(args.on)
    if cp:
        role = V.people.role(args.on)
        if role == "将领":
            print(f"    · {args.on} 是将领：要他背主的要挟，GM 照 rules/loyalty.md 第四节记成开价（所给里‘性命’‘家眷平安’一类按秘密的分量折算），"
                  "照旧走算盘，不直接改离心。")
        elif role == "家人":
            print(f"    · {args.on} 是家人：记成牵扯，household.py tie {args.on} --from {args.by} --aim \"{args.demand}\" --promise \"守住秘密\" --apply")
        else:
            print(f"    · {args.on} 有人格卡：记成牵扯（卡上“牵扯”一节），季末 court.py season 照心迹推进。")
    if args.apply:
        import relations as REL
        net = REL.Net(V.world)
        net.add_deed(args.on, args.by, "怨", f"{args.by}拿“{s['title']}”要挟他：{args.demand}", 2, X.when_of(V.world),
                     X.turn_of(V.world), "两人", source=f"secret:{s['id']}")
        net.save()
        s["uses"].append(f"{X.when_of(V.world)}：{args.by}要挟{args.on}——{args.demand}（分量 {pressure}）")
        kk = knower(s, args.on)
        if not kk:
            s["knowers"].append({"name": args.on, "depth": "大略", "how": "转述", "since_turn": X.turn_of(V.world)})
    finish(V, args, "（关系网一并写入）" if args.apply else "")


# ---------------------------------------------------------------- 情报包

def build_brief(world, name, with_=()):
    V = Vault(world)
    people = V.people
    import relations as REL
    import rumors as R
    net = REL.Net(world)
    B = R.Board(world)
    brief = {"name": name, "circles": X.person_circles(world, name, people), "secrets": [], "rumors": [], "docs": [],
             "present": [], "court": None, "hint": None}
    # 秘密
    for s, k, held in known_by(V, name):
        item = {"id": s["id"], "title": s["title"], "depth": k["depth"] if k else "只拿着证据",
                "content": what_he_knows(s, k) if k else s.get("cover") or s["title"],
                "evidence": [f"{e['kind']}：{e['desc']}" for e in held]}
        brief["secrets"].append(item)
    # 流言
    _, rows = R.heard_by(B, name, people)
    for r, where in rows:
        brief["rumors"].append({"id": r["id"], "text": r["text"], "where": where,
                                "spread": "；".join(f"{c}{X.HEAT_WORDS[h]}" for c, h in r["heat"].items() if h > 0 and c in brief["circles"]) or "",
                                "belief": X.CRED_WORDS[X.clamp(r["cred"], 0, 5)],
                                "about_him": name in r.get("about", [])})
    for d, how in R.docs_read_by(B, name, people):
        brief["docs"].append({"id": d["id"], "title": d["title"], "how": how, "summary": d["summary"],
                              "banned": d.get("status") == "禁毁"})
    # 在场之人
    for o in with_:
        if o == name:
            continue
        p = net.pair(name, o)
        tags = [REL.fmt_tag(dict(t, knowers=[]), p).replace("【暗】只有两人知道", "（暗的，外人不知道）")
                for t in (p["tags"] if p else []) if REL.tag_visible(t, p, name)]
        mine = [x for x in net.deeds(name, o)]
        theirs = [x for x in net.deeds(o, name) if REL.deed_visible(x, name)]
        c = net.closeness(name, o)
        # 他以为对方怎么看他：只算他知道的
        c2 = net.closeness(o, name, observer=name)
        imp = None
        try:
            import persona as P
            W = P.World(world)
            obs, tgt = W.find(name, quiet=True), W.find(o, quiet=True)
            if obs and tgt:
                lvl = W.know_level(obs, tgt)
                imp = P.impression(W, obs, tgt, lvl) if hasattr(P, "impression") else None
        except SystemExit:
            imp = None
        brief["present"].append({"name": o, "view": f"{REL.close_word(c)}（{c:+d}）", "thinks_he_views_me": REL.close_word(c2),
                                 "tags": tags, "my_deeds": [f"{x['kind']}{x['s']}：{x['what']}" for x in mine],
                                 "their_deeds_i_know": [f"{x['kind']}{x['s']}：{x['what']}" for x in theirs],
                                 "impression": imp})
    # 朝中
    try:
        import court as C0
        C = C0.Court(world)
        f = C.faction_of(name)
        brief["court"] = {"post": C.post_of(name), "faction": f,
                          "issues": [], "superior": (C.d["careers"].get(name) or {}).get("superior")}
        for k, iss in C.d["issues"].items():
            if str(iss.get("status", "")).startswith("已决"):
                continue
            pos = iss.get("positions", {}).get(f or "", {})
            brief["court"]["issues"].append(f"{iss.get('title', k)}：{iss.get('status')}" + (f"；本派要{pos.get('want')}" if pos.get("want") else ""))
        pend = [m for m in C.d["memorials"] if m["status"] in ("待议", "已议")]
        brief["court"]["docket"] = [f"{m['id']} {m['by']}{m['kind']}{m.get('target') or ''}（{m.get('ask')}）" for m in pend]
        brief["hint"] = C0.courtier_hint(C, name)
    except SystemExit:
        pass
    return brief


def print_brief(b):
    n = b["name"]
    print(f"=== 情报包：{n}（只含他知道的；照原样或改写后写进 agent 的 prompt） ===")
    if b.get("court"):
        c = b["court"]
        print(f"【身份】{c.get('post') or '无官'}；{('在' + c['faction']) if c.get('faction') else '不在哪一派'}"
              + (f"；上司 {c['superior']}" if c.get("superior") else "") + f"；平常在{'、'.join(b['circles']) or '—'}走动")
    print("【他知道的秘密】")
    for s in b["secrets"]:
        print(f"  · {s['title']}（{s['depth']}）：{s['content']}" + (f"；手里有：{'；'.join(s['evidence'])}" if s["evidence"] else ""))
    if not b["secrets"]:
        print("  （无）")
    print("【他听到过的流言】（他不知道真假）")
    for r in b["rumors"]:
        print(f"  · {r['text']}——{r['spread'] or '有人跟他说起'}，听的人{r['belief']}" + ("（说的就是他）" if r["about_him"] else ""))
    if not b["rumors"]:
        print("  （无）")
    if b["docs"]:
        print("【他读过的文献】")
        for d in b["docs"]:
            print(f"  · {d['title']}（{d['how']}{'，已禁' if d['banned'] else ''}）：{d['summary']}")
    if b["present"]:
        print("【他和在场的人】")
        for p in b["present"]:
            print(f"  · {p['name']}：他看对方{p['view']}；他觉得对方看他{p['thinks_he_views_me']}"
                  + (f"；关系：{'、'.join(p['tags'])}" if p["tags"] else ""))
            for x in p["my_deeds"]:
                print(f"      他记着对方的{x}")
            for x in p["their_deeds_i_know"]:
                print(f"      他知道对方记着他的{x}")
            if p.get("impression"):
                print(f"      他眼里的对方：{p['impression']}")
    if b.get("court"):
        c = b["court"]
        if c.get("issues") or c.get("docket"):
            print("【朝中眼下的事】")
            for i in c.get("issues", []):
                print(f"  · 议题 {i}")
            for m in c.get("docket", []):
                print(f"  · 奏疏 {m}")
    if b.get("hint"):
        print("【朝中提示（他心里的事，不要原样说出来）】")
        print(f"  {b['hint']}")


def cmd_brief(V, args):
    b = build_brief(V.world, args.name, X.split_names(args.with_))
    if args.json:
        print(json.dumps(b, ensure_ascii=False, indent=2))
    else:
        print_brief(b)


def main():
    ap = argparse.ArgumentParser(description="秘密与知情（规则见 rules/secrets.md）",
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

    p = add("add", "登记一条秘密", cmd_add)
    p.add_argument("--title", required=True)
    p.add_argument("--truth", required=True)
    p.add_argument("--cover")
    p.add_argument("--about")
    p.add_argument("--danger", type=int, default=2, choices=(1, 2, 3))
    p.add_argument("--knower", action="append", help="名=全知|大略|风闻[:怎么知道的]，可重复")
    p.add_argument("--evidence", action="append", help="书信|人证|物证|账册:描述@持有人，可重复")
    p.add_argument("--note")
    p.add_argument("--when")
    p = add("learn", "某人得知", cmd_learn)
    p.add_argument("id")
    p.add_argument("--who", required=True)
    p.add_argument("--depth", required=True, choices=DEPTHS)
    p.add_argument("--how", choices=HOWS)
    p.add_argument("--from", dest="from_")
    p.add_argument("--knows", help="他知道的那一截（大略、风闻的人；情报包照它给，不给全部真相）")
    p = add("evidence", "证据", cmd_evidence)
    p.add_argument("id")
    p.add_argument("--add")
    p.add_argument("--move")
    p.add_argument("--to")
    p.add_argument("--status")
    p = add("expose", "外象：旁人从外面看得出多少端倪（0–3）", cmd_expose)
    p.add_argument("id")
    p.add_argument("--level", type=int, required=True, choices=(0, 1, 2, 3))
    p.add_argument("--why", required=True)
    p = add("show", "全部秘密", cmd_show, write=False)
    p.add_argument("id", nargs="?")
    p = add("known", "某人知道什么", cmd_known, write=False)
    p.add_argument("name")
    p = add("season", "季末泄露检定", cmd_season)
    p.add_argument("--seed", type=int)
    p.add_argument("--when")
    p.add_argument("--force", action="store_true")
    p = add("leak", "有人故意说出去", cmd_leak)
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p.add_argument("--circle")
    p = add("leverage", "拿把柄要挟", cmd_leverage)
    p.add_argument("id")
    p.add_argument("--by", required=True)
    p.add_argument("--on", required=True)
    p.add_argument("--demand", required=True)
    p = add("brief", "情报包", cmd_brief, write=False)
    p.add_argument("name")
    p.add_argument("--with", dest="with_")
    p.add_argument("--json", action="store_true")
    args = ap.parse_args()
    args.fn(Vault(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
