#!/usr/bin/env python3
"""个人钱物：随身钱、家当、俸钱、兵器、马、随身物件（带来历）、借贷、罚俸。规则见 rules/purse.md。只用标准库。

存档是 world/purse.json。会改存档的命令默认只打印，加 --apply 才写回。
钱的单位照剧本 scenario.json 的 purse 一节（例：一贯一千文，存档里一律记小单位“文”）；没有这一节就用 terms.money_unit，不分大小单位。
主角是臣子的（scenario.json 的 player.role 为“臣子”），他的“家当”就是 kingdom.json 的 treasury.money（以大单位记），
本脚本直接读写那里；别人的家当记在 purse.json。主角是一方之主的，府库是公家的，他的私房钱照别人一样记在 purse.json。

  查看     show [名] [--all]            ledger 名 [--n 20]
  建档     open 名 [--cash 钱] [--home 钱] [--living 钱] [--note …]
  花钱     spend 名 --amount 钱 --what 事由 [--from cash|home] [--to 收钱的人] [--kind 吃喝|打点|药钱|赁屋|买物|赏人|其他]
  进项     earn 名 --amount 钱 --what 事由 [--to cash|home] [--from 给钱的人]
  给       give 甲 --to 乙 (--amount 钱 | --item 物件编号) --what 事由 [--kind 赏赐|送礼|行贿|周济]
  存取     move 名 --amount 钱 --to cash|home
  物件     item add 名 --kind 兵器|马|衣甲|物件|文书 --name 名称 [--desc …] [--story 来历] [--value 钱] [--where 随身|家中|…]
                    [--secret 秘密编号] [--feed 钱] [--issued]
           item story 编号 --add 一段故事          item set 编号 字段=值 …
           item give 编号 --to 名 [--what …]      item status 编号 --status 在|当了|卖了|送人|失|毁 [--amount 钱] --why …
  借贷     borrow 名 --from 债主 --amount 钱 [--rate 每季利息，如 0.05] [--due 回合] --what …
           repay 借据编号 [--amount 钱] [--why …]     debt 借据编号 --status 赖账|免了 --why …
  罚俸     fine 名 (--seasons N | --amount 钱) --why …
  常例     stipend 名 --amount 钱(可负) --what … [--remove 序号]      每季固定的进项或开销（家里寄来、寄回家里）
  俸钱     pay [名]                         本季的俸钱（按 court.json 的仕途阶梯或品级），只发一次
  季末     season                           俸钱、常例、马料、用度、利息、到期的债、罚俸倒数

钱可以写成 “2贯300文”“1.5贯”“300文”“300”（不带单位的按小单位）。所有命令都有 --world（试验用）。
"""
import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario_lib as S  # noqa: E402
import social_lib as X  # noqa: E402

FILE = "purse.json"
EMPTY = {"version": 1, "people": {}, "debts": [], "next": {"I": 1, "D": 1}, "last_season_turn": 0}
ITEM_KINDS = ("兵器", "马", "衣甲", "物件", "文书")
ITEM_STATUS = ("在", "当了", "卖了", "送人", "失", "毁")
DEBT_STATUS = ("未还", "已还", "赖账", "免了")
SPEND_KINDS = ("吃喝", "打点", "药钱", "赁屋", "买物", "赏人", "其他")
GIVE_KINDS = ("赏赐", "送礼", "行贿", "周济", "还情")
LEDGER_KEEP = 80


# ---------------------------------------------------------------- 单位

class Money:
    """钱的单位：小单位（文）记账，大单位（贯）给人看；主角家当在 kingdom.json 里以大单位记。"""

    def __init__(self, world):
        sc = S.load(world)
        cfg = sc.get("purse") or {}
        self.big = cfg.get("big_unit") or S.term(world, "money_unit")
        self.unit = cfg.get("unit") or self.big
        self.per = int(cfg.get("per_big") or 1)
        self.horse_feed = int(cfg.get("horse_feed") or 0)
        self.cfg = cfg

    def parse(self, s):
        """“2贯300文”“1.5贯”“300文”“300” → 小单位整数。"""
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return int(round(s))
        t = str(s).strip().replace(" ", "").replace("，", "")
        neg = t.startswith("-") or t.startswith("−")
        t = t.lstrip("-−+")
        total, matched = 0.0, False
        if self.big != self.unit:
            m = re.match(r"^(\d+(?:\.\d+)?)" + re.escape(self.big), t)
            if m:
                total += float(m.group(1)) * self.per
                t = t[m.end():]
                matched = True
        m = re.match(r"^(\d+(?:\.\d+)?)(" + re.escape(self.unit) + ")?$", t)
        if m:
            total += float(m.group(1))
            t = ""
            matched = True
        if t or not matched:
            X.die(f"看不懂钱数“{s}”。写成 2{self.big}300{self.unit}、1.5{self.big}、300{self.unit} 或 300")
        v = int(round(total))
        return -v if neg else v

    def fmt(self, v):
        v = int(v)
        sign = "−" if v < 0 else ""
        v = abs(v)
        if self.per <= 1:
            return f"{sign}{v}{self.unit}"
        b, s = divmod(v, self.per)
        if b and s:
            return f"{sign}{b}{self.big}{s}{self.unit}"
        if b:
            return f"{sign}{b}{self.big}"
        return f"{sign}{s}{self.unit}"


# ---------------------------------------------------------------- 存档

class Purse:
    def __init__(self, world):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        for k, v in EMPTY.items():
            self.d.setdefault(k, json.loads(json.dumps(v)))
        self.M = Money(world)
        sc = S.load(world)
        self.hero = (sc.get("player") or {}).get("protagonist")
        self.vassal = (sc.get("player") or {}).get("role") == "臣子"
        self._kingdom = None
        self.turn = X.turn_of(world)
        self.when = X.when_of(world)

    # --- 主角的家当在 kingdom.json ---
    @property
    def kingdom(self):
        if self._kingdom is None:
            self._kingdom = X.kingdom(self.world)
        return self._kingdom

    def home_in_treasury(self, name):
        return self.vassal and name == self.hero

    def home(self, name):
        if self.home_in_treasury(name):
            return int(round(float(self.kingdom.get("treasury", {}).get("money", 0)) * self.M.per))
        return int(self.person(name).get("home") or 0)

    def set_home(self, name, v):
        if self.home_in_treasury(name):
            if v % self.M.per:
                X.die("内部错误：主角家当要整大单位")
            self.kingdom.setdefault("treasury", {})["money"] = v // self.M.per
        else:
            self.person(name)["home"] = v

    def save(self):
        X.save_json(self.world, FILE, self.d)
        if self._kingdom is not None:
            X.save_json(self.world, "kingdom.json", self._kingdom)

    # --- 人 ---
    def person(self, name, create=False):
        p = self.d["people"].get(name)
        if p is None:
            if not create:
                X.die(f"purse.json 里没有 {name}（有：{'、'.join(self.d['people']) or '无'}）。先 open {name}")
            p = self.d["people"][name] = {"cash": 0, "home": 0, "living": 0, "items": [], "fines": [], "stipends": [],
                                          "ledger": [], "last_pay_turn": 0, "note": ""}
        for k, v in (("items", []), ("fines", []), ("stipends", []), ("ledger", []), ("cash", 0), ("living", 0)):
            p.setdefault(k, v)
        return p

    def has(self, name):
        return name in self.d["people"]

    def log(self, name, delta, where, what):
        p = self.person(name)
        p["ledger"].append({"turn": self.turn, "when": self.when, "delta": delta, "where": where, "what": what,
                            "cash": p["cash"], "home": self.home(name)})
        p["ledger"] = p["ledger"][-LEDGER_KEEP:]

    def add_cash(self, name, delta, what):
        p = self.person(name)
        p["cash"] = int(p["cash"]) + delta
        self.log(name, delta, "随身", what)

    def add_home(self, name, delta, what):
        """家当加减。主角的家当是大单位整数：取钱时多取的找零进随身钱，存钱时零头留在随身钱里。返回说明。"""
        cur = self.home(name)
        if not self.home_in_treasury(name) or self.M.per <= 1:
            self.set_home(name, cur + delta)
            self.log(name, delta, "家当", what)
            return ""
        per = self.M.per
        if delta >= 0:
            whole = (delta // per) * per
            rest = delta - whole
            self.set_home(name, cur + whole)
            self.log(name, whole, "家当", what)
            if rest:
                self.add_cash(name, rest, f"{what}（零头留在身上）")
                return f"零头 {self.M.fmt(rest)} 留在随身钱里"
            return ""
        need = -delta
        take = math.ceil(need / per) * per
        self.set_home(name, cur - take)
        self.log(name, -take, "家当", what)
        change = take - need
        if change:
            self.add_cash(name, change, f"{what}（找零）")
            return f"从家当取了 {self.M.fmt(take)}，找零 {self.M.fmt(change)} 进随身钱"
        return ""

    def items(self, name=None):
        for n, p in self.d["people"].items():
            if name and n != name:
                continue
            for it in p.get("items", []):
                yield n, it

    def item(self, iid):
        for n, it in self.items():
            if it["id"] == iid:
                return n, it
        X.die(f"没有物件 {iid}")

    def debt(self, did):
        x = next((x for x in self.d["debts"] if x["id"] == did), None)
        return x or X.die(f"没有借据 {did}（有：{'、'.join(x['id'] for x in self.d['debts']) or '无'}）")

    def horses(self, name):
        return [it for _, it in self.items(name) if it.get("kind") == "马" and it.get("status", "在") == "在"]


def finish(P, args, msg=""):
    if getattr(args, "apply", False):
        P.save()
        print(f"\n已写入 {X.rel(os.path.join(P.world, FILE))}" + ("、kingdom.json" if P._kingdom is not None else "") + msg)
    else:
        print("\n（未写入。确认后加 --apply。）")


# ---------------------------------------------------------------- 俸钱（court.json 的仕途阶梯或品级）

def salary_of(world, name):
    """本季俸钱（小单位）和说明。没有仕途记录的返回 (0, None)。"""
    try:
        import court as C0
    except SystemExit:
        return 0, None
    if not os.path.exists(os.path.join(world, "court.json")):
        return 0, None
    C = C0.Court(world)
    big, why = C0.salary(C, name)
    if big is None:
        return 0, why
    M = Money(world)
    return int(round(big * M.per)), why


def pay_one(P, name, quiet=False):
    """发本季俸钱：罚俸的扣掉。返回发了多少（小单位）。同一回合只发一次。"""
    p = P.person(name)
    if int(p.get("last_pay_turn") or 0) == P.turn:
        if not quiet:
            print(f"  {name}：第 {P.turn} 回合的俸钱已经发过")
        return 0
    amt, why = salary_of(P.world, name)
    if not amt:
        if why and not quiet:
            print(f"  {name}：{why}")
        return 0
    fines = [f for f in p.get("fines", []) if f.get("seasons_left", 0) > 0]
    if fines:
        f = fines[0]
        f["seasons_left"] -= 1
        print(f"  {name}：俸钱 {P.M.fmt(amt)}（{why}），罚俸中（{f['why']}，还剩 {f['seasons_left']} 季），本季不发")
        p["last_pay_turn"] = P.turn
        P.log(name, 0, "随身", f"罚俸：{f['why']}")
        return 0
    P.add_cash(name, amt, f"本季俸钱（{why}）")
    p["last_pay_turn"] = P.turn
    print(f"  {name}：俸钱 +{P.M.fmt(amt)}（{why}），进随身钱")
    return amt


# ---------------------------------------------------------------- 命令

def show_person(P, name, n_ledger=5):
    p = P.person(name)
    home_where = "kingdom.json 的家当" if P.home_in_treasury(name) else "家当"
    print(f"=== {name} 的钱物 ===")
    print(f"  随身钱：{P.M.fmt(p['cash'])}   {home_where}：{P.M.fmt(P.home(name))}"
          + (f"   用度：每季 {P.M.fmt(p['living'])}" if p.get("living") else ""))
    amt, why = salary_of(P.world, name)
    if amt or why:
        print(f"  俸钱：{('每季 ' + P.M.fmt(amt) + '（' + why + '）') if amt else why}")
    for f in p.get("fines", []):
        if f.get("seasons_left", 0) > 0:
            print(f"  罚俸：还剩 {f['seasons_left']} 季（{f['why']}）")
    for i, s in enumerate(p.get("stipends", []), 1):
        print(f"  常例 {i}：每季 {'+' if s['amount'] >= 0 else ''}{P.M.fmt(s['amount'])}（{s['what']}）")
    its = [it for _, it in P.items(name)]
    if its:
        print("  物件：")
        for it in its:
            st = it.get("status", "在")
            extra = []
            if it.get("value"):
                extra.append(f"约值 {P.M.fmt(it['value'])}")
            if it.get("where"):
                extra.append(it["where"])
            if it.get("issued"):
                extra.append("公家发的")
            if it.get("kind") == "马":
                feed = it.get("feed")
                extra.append(f"马料每季 {P.M.fmt(feed if feed is not None else P.M.horse_feed)}")
            print(f"    [{it['id']}] {it['kind']}·{it['name']}" + (f"（{st}）" if st != "在" else "")
                  + (f"：{it['desc']}" if it.get("desc") else "") + (f"｜{'，'.join(extra)}" if extra else ""))
            for s in it.get("story", []):
                print(f"         来历：{s}")
    ds = [x for x in P.d["debts"] if x["status"] == "未还" and name in (x["debtor"], x["creditor"])]
    for x in ds:
        side = "欠" if x["debtor"] == name else "借给"
        other = x["creditor"] if x["debtor"] == name else x["debtor"]
        due = f"，第 {x['due_turn']} 回合到期" if x.get("due_turn") else ""
        print(f"  借据 {x['id']}：{side} {other} {P.M.fmt(x['owed'])}（本 {P.M.fmt(x['principal'])}，每季利 {x['rate']:.0%}{due}）：{x['what']}")
    if n_ledger:
        led = p.get("ledger", [])[-n_ledger:]
        if led:
            print(f"  最近的账：")
            for e in led:
                print(f"    {e['when']}  {e['where']} {'+' if e['delta'] >= 0 else ''}{P.M.fmt(e['delta'])}  {e['what']}")


def cmd_show(P, args):
    names = [args.name] if args.name else list(P.d["people"])
    if not names:
        print("purse.json 里还没有人。open 名 建档。")
    for i, n in enumerate(names):
        if i:
            print()
        show_person(P, n, 8 if args.name else (5 if args.all else 0))


def cmd_ledger(P, args):
    p = P.person(args.name)
    print(f"=== {args.name} 的账（最近 {args.n} 笔） ===")
    for e in p.get("ledger", [])[-args.n:]:
        print(f"  {e['when']}  {e['where']} {'+' if e['delta'] >= 0 else ''}{P.M.fmt(e['delta'])}  {e['what']}"
              f"   （随身 {P.M.fmt(e['cash'])}，家当 {P.M.fmt(e['home'])}）")


def cmd_open(P, args):
    if P.has(args.name):
        X.die(f"{args.name} 已经有了。改钱用 earn / spend / move")
    p = P.person(args.name, create=True)
    p["cash"] = P.M.parse(args.cash) or 0
    if args.home:
        h = P.M.parse(args.home)
        if P.home_in_treasury(args.name):
            print(f"注意：{args.name} 是主角，家当在 kingdom.json 的 treasury.money，--home 不记在这里；要改用 earn --to home")
        else:
            p["home"] = h
    p["living"] = P.M.parse(args.living) or 0
    p["note"] = args.note or ""
    print(f"建档：{args.name}，随身 {P.M.fmt(p['cash'])}，家当 {P.M.fmt(P.home(args.name))}")
    finish(P, args)


def take(P, name, amount, src, what):
    """从随身钱或家当里出钱。随身钱不够、又是从随身出的，报错（让 GM 先存取或改 --from）。返回说明。"""
    p = P.person(name)
    if src == "home":
        if P.home(name) < amount:
            X.die(f"{name} 的家当只有 {P.M.fmt(P.home(name))}，不够 {P.M.fmt(amount)}")
        return P.add_home(name, -amount, what)
    if int(p["cash"]) < amount:
        X.die(f"{name} 身上只有 {P.M.fmt(p['cash'])}，不够 {P.M.fmt(amount)}。家当还有 {P.M.fmt(P.home(name))}：先 move 取钱，或者 --from home")
    P.add_cash(name, -amount, what)
    return ""


def cmd_spend(P, args):
    amt = P.M.parse(args.amount)
    if amt <= 0:
        X.die("--amount 要大于 0")
    what = f"{args.kind + '：' if args.kind else ''}{args.what}" + (f"（给 {args.to}）" if args.to else "")
    note = take(P, args.name, amt, args.from_, what)
    print(f"{args.name} 花了 {P.M.fmt(amt)}：{what}" + (f"；{note}" if note else ""))
    if args.to and P.has(args.to):
        P.add_cash(args.to, amt, f"{args.name} 给的：{args.what}")
        print(f"  {args.to} 收了 {P.M.fmt(amt)}")
    print(f"  {args.name} 随身 {P.M.fmt(P.person(args.name)['cash'])}，家当 {P.M.fmt(P.home(args.name))}")
    finish(P, args)


def cmd_earn(P, args):
    amt = P.M.parse(args.amount)
    if amt <= 0:
        X.die("--amount 要大于 0")
    what = args.what + (f"（{args.from_} 给的）" if args.from_ else "")
    if args.from_ and P.has(args.from_):
        take(P, args.from_, amt, "cash", f"给 {args.name}：{args.what}")
    note = ""
    if args.to == "home":
        note = P.add_home(args.name, amt, what)
    else:
        P.add_cash(args.name, amt, what)
    print(f"{args.name} 进了 {P.M.fmt(amt)}：{what}" + (f"；{note}" if note else ""))
    print(f"  随身 {P.M.fmt(P.person(args.name)['cash'])}，家当 {P.M.fmt(P.home(args.name))}")
    finish(P, args)


def gift_hint(P, giver, to, value, kind):
    """厚赠、行贿的关系网建议（rules/purse.md 第五节）。"""
    big = P.M.per
    if kind == "行贿":
        print(f"  关系网：行贿不自动记恩。收了的人若办了事，GM 照实记；行贿本身可以登记成一条秘密（secrets.py add，受贿的人、经手的人知情）")
    elif value >= 3 * big:
        print(f"  关系网建议：relations.py event 厚赠 --by {giver} --to {to} --what … --apply（一份厚礼，{to} 记一份情）")


def cmd_give(P, args):
    if bool(args.amount) == bool(args.item):
        X.die("--amount 和 --item 给一个")
    if args.item:
        owner, it = P.item(args.item)
        if owner != args.name:
            X.die(f"物件 {args.item} 在 {owner} 手里，不在 {args.name} 手里")
        if it.get("status", "在") != "在":
            X.die(f"物件 {args.item} 眼下是“{it['status']}”，给不出去")
        P.person(args.name)["items"].remove(it)
        it.setdefault("log", []).append(f"{P.when}：{args.name} {args.kind or '送'}给 {args.to}：{args.what}")
        P.person(args.to, create=True)["items"].append(it)
        print(f"{args.name} 把 [{it['id']}] {it['name']} {args.kind or '给'}了 {args.to}：{args.what}")
        if it.get("secret"):
            print(f"  这件东西连着秘密 {it['secret']}：要不要 secrets.py evidence --move / learn，GM 看情形定")
        gift_hint(P, args.name, args.to, int(it.get("value") or 0), args.kind)
    else:
        amt = P.M.parse(args.amount)
        take(P, args.name, amt, args.from_, f"{args.kind or '给'} {args.to}：{args.what}")
        P.person(args.to, create=True)
        P.add_cash(args.to, amt, f"{args.name} {args.kind or '给'}的：{args.what}")
        print(f"{args.name} {args.kind or '给'} {args.to} {P.M.fmt(amt)}：{args.what}")
        gift_hint(P, args.name, args.to, amt, args.kind)
    finish(P, args)


def cmd_move(P, args):
    amt = P.M.parse(args.amount)
    if args.to == "cash":
        if P.home(args.name) < amt:
            X.die(f"家当只有 {P.M.fmt(P.home(args.name))}")
        note = P.add_home(args.name, -amt, "从家当取钱")
        P.add_cash(args.name, amt, "从家当取钱")
        print(f"{args.name} 从家当取 {P.M.fmt(amt)} 带在身上" + (f"；{note}" if note else ""))
    else:
        p = P.person(args.name)
        if p["cash"] < amt:
            X.die(f"身上只有 {P.M.fmt(p['cash'])}")
        P.add_cash(args.name, -amt, "存进家当")
        note = P.add_home(args.name, amt, "存进家当")
        print(f"{args.name} 把 {P.M.fmt(amt)} 存进家当" + (f"；{note}" if note else ""))
    print(f"  随身 {P.M.fmt(P.person(args.name)['cash'])}，家当 {P.M.fmt(P.home(args.name))}")
    finish(P, args)


def cmd_item(P, args):
    if args.sub == "add":
        if args.kind not in ITEM_KINDS:
            X.die(f"--kind 只有 {'、'.join(ITEM_KINDS)}")
        iid = f"I{P.d['next']['I']}"
        P.d["next"]["I"] += 1
        it = {"id": iid, "kind": args.kind, "name": args.name_, "desc": args.desc or "", "story": [args.story] if args.story else [],
              "value": P.M.parse(args.value) if args.value else 0, "where": args.where or "随身", "status": "在", "log": [f"{P.when}：入账"]}
        if args.secret:
            it["secret"] = args.secret
        if args.feed is not None:
            it["feed"] = P.M.parse(args.feed)
        if args.issued:
            it["issued"] = True
        P.person(args.owner, create=not P.has(args.owner))["items"].append(it)
        print(f"{args.owner} 添了一件：[{iid}] {args.kind}·{args.name_}" + (f"，来历：{args.story}" if args.story else ""))
    elif args.sub == "story":
        owner, it = P.item(args.id)
        it.setdefault("story", []).append(args.add)
        print(f"[{it['id']}] {it['name']} 添了一段来历：{args.add}")
    elif args.sub == "set":
        owner, it = P.item(args.id)
        for kv in args.fields:
            k, _, v = kv.partition("=")
            if k in ("value", "feed"):
                v = P.M.parse(v)
            elif k == "status" and v not in ITEM_STATUS:
                X.die(f"status 只有 {'、'.join(ITEM_STATUS)}")
            elif k in ("id", "story", "log"):
                X.die(f"{k} 不能用 set 改")
            it[k] = v
            print(f"[{it['id']}] {k} = {v}")
        it.setdefault("log", []).append(f"{P.when}：改 {'，'.join(args.fields)}")
    elif args.sub == "give":
        args2 = argparse.Namespace(**vars(args))
        owner, it = P.item(args.id)
        args2.name, args2.item, args2.amount, args2.kind = owner, args.id, None, args.kind
        args2.what = args.what or "送人"
        return cmd_give(P, args2)
    elif args.sub == "status":
        owner, it = P.item(args.id)
        if args.status not in ITEM_STATUS:
            X.die(f"--status 只有 {'、'.join(ITEM_STATUS)}")
        old = it.get("status", "在")
        it["status"] = args.status
        it.setdefault("log", []).append(f"{P.when}：{old} → {args.status}，{args.why}")
        print(f"[{it['id']}] {it['name']}：{old} → {args.status}（{args.why}）")
        if args.amount:
            amt = P.M.parse(args.amount)
            P.add_cash(owner, amt, f"{it['name']}{args.status}：{args.why}")
            print(f"  {owner} 得钱 {P.M.fmt(amt)}")
        if args.status == "当了":
            print(f"  赎回时：item status {it['id']} --status 在 --why 赎回，再 spend {owner} --amount … --what 赎当")
        if it.get("secret") and args.status in ("失", "毁", "送人", "卖了", "当了"):
            print(f"  这件东西连着秘密 {it['secret']}：它落到了谁手里，GM 看要不要 secrets.py learn / evidence")
    finish(P, args)


def cmd_borrow(P, args):
    amt = P.M.parse(args.amount)
    did = f"D{P.d['next']['D']}"
    P.d["next"]["D"] += 1
    x = {"id": did, "debtor": args.name, "creditor": args.from_, "principal": amt, "owed": amt, "rate": args.rate,
         "since_turn": P.turn, "due_turn": args.due, "what": args.what, "status": "未还", "log": [f"{P.when}：借 {P.M.fmt(amt)}"]}
    P.d["debts"].append(x)
    if P.has(args.from_):
        take(P, args.from_, amt, "cash", f"借给 {args.name}：{args.what}")
    P.add_cash(args.name, amt, f"向 {args.from_} 借：{args.what}")
    print(f"借据 {did}：{args.name} 向 {args.from_} 借 {P.M.fmt(amt)}，每季利 {args.rate:.0%}"
          + (f"，第 {args.due} 回合到期" if args.due else "，没约定日子") + f"。事由：{args.what}")
    if not P.has(args.from_):
        print(f"  （{args.from_} 不在 purse.json 里：柜坊、寺库、放债的，钱从外头来）")
    print(f"  人情：借钱的多半记债主一份小人情（relations.py event 援手 --by {args.from_} --to {args.name}），GM 看情形")
    finish(P, args)


def cmd_repay(P, args):
    x = P.debt(args.id)
    if x["status"] != "未还":
        X.die(f"借据 {x['id']} 已经{x['status']}了")
    amt = P.M.parse(args.amount) if args.amount else x["owed"]
    amt = min(amt, x["owed"])
    take(P, x["debtor"], amt, args.from_, f"还 {x['creditor']}（借据 {x['id']}）")
    if P.has(x["creditor"]):
        P.add_cash(x["creditor"], amt, f"{x['debtor']} 还钱（借据 {x['id']}）")
    x["owed"] -= amt
    x["log"].append(f"{P.when}：还 {P.M.fmt(amt)}" + (f"，{args.why}" if args.why else ""))
    if x["owed"] <= 0:
        x["status"] = "已还"
    print(f"{x['debtor']} 还 {x['creditor']} {P.M.fmt(amt)}；" + ("还清了" if x["status"] == "已还" else f"还欠 {P.M.fmt(x['owed'])}"))
    finish(P, args)


def cmd_debt(P, args):
    x = P.debt(args.id)
    old = x["status"]
    x["status"] = args.status
    x["log"].append(f"{P.when}：{old} → {args.status}，{args.why}")
    print(f"借据 {x['id']}：{old} → {args.status}（{args.why}）")
    if args.status == "赖账":
        print(f"  关系网建议：relations.py event 背约 --by {x['debtor']} --to {x['creditor']} --what 赖了借据 {x['id']} --apply")
    elif args.status == "免了":
        print(f"  关系网建议：relations.py event 援手 --by {x['creditor']} --to {x['debtor']} --what 免了一笔债 --apply")
    finish(P, args)


def cmd_fine(P, args):
    p = P.person(args.name)
    if args.seasons:
        p["fines"].append({"seasons_left": args.seasons, "why": args.why, "turn": P.turn})
        print(f"{args.name} 罚俸 {args.seasons} 季：{args.why}（季末发俸时扣掉）")
    elif args.amount:
        amt = P.M.parse(args.amount)
        cash = int(p["cash"])
        if cash >= amt:
            P.add_cash(args.name, -amt, f"罚钱：{args.why}")
        else:
            P.add_cash(args.name, -cash, f"罚钱：{args.why}")
            rest = amt - cash
            if P.home(args.name) < rest:
                X.die(f"{args.name} 身上和家当都不够罚 {P.M.fmt(amt)}；可以改罚俸几季，或者记一笔欠官的借据（borrow --from 官）")
            P.add_home(args.name, -rest, f"罚钱：{args.why}")
        print(f"{args.name} 罚钱 {P.M.fmt(amt)}：{args.why}")
    else:
        X.die("给 --seasons 或 --amount")
    print(f"  人心：罚俸算一次处分，心里不痛快的，GM 照 rules/court.md 第六节记器重或心结")
    finish(P, args)


def cmd_stipend(P, args):
    p = P.person(args.name)
    if args.remove:
        s = p["stipends"].pop(args.remove - 1)
        print(f"{args.name} 去掉常例：{s['what']}")
    else:
        amt = P.M.parse(args.amount)
        p["stipends"].append({"amount": amt, "what": args.what, "since_turn": P.turn})
        print(f"{args.name} 添常例：每季 {'+' if amt >= 0 else ''}{P.M.fmt(amt)}（{args.what}）")
    finish(P, args)


def cmd_pay(P, args):
    print(f"=== 俸钱：{P.when}（第 {P.turn} 回合） ===")
    names = [args.name] if args.name else list(P.d["people"])
    total = 0
    for n in names:
        total += pay_one(P, n)
    if not total:
        print("  （本季没有要发的俸钱）")
    finish(P, args)


def cmd_season(P, args):
    if P.d.get("last_season_turn") == P.turn and not args.force:
        X.die(f"第 {P.turn} 回合的钱物已经结过。确要重跑加 --force")
    print(f"=== 钱物季末：{P.when}（第 {P.turn} 回合） ===")
    warn = []
    for name, p in P.d["people"].items():
        print(f"--- {name} ---")
        pay_one(P, name, quiet=True)
        for s in p.get("stipends", []):
            if s["amount"] >= 0:
                P.add_cash(name, s["amount"], f"常例：{s['what']}")
                print(f"  常例 +{P.M.fmt(s['amount'])}（{s['what']}）")
            else:
                need = -s["amount"]
                if p["cash"] >= need:
                    P.add_cash(name, -need, f"常例：{s['what']}")
                    print(f"  常例 −{P.M.fmt(need)}（{s['what']}）")
                else:
                    warn.append(f"{name}：常例“{s['what']}”要 {P.M.fmt(need)}，身上不够，没付")
        cost = 0
        parts = []
        for h in P.horses(name):
            if h.get("issued"):
                continue
            feed = h.get("feed")
            feed = P.M.horse_feed if feed is None else int(feed)
            if feed:
                cost += feed
                parts.append(f"{h['name']}马料 {P.M.fmt(feed)}")
        if p.get("living"):
            cost += int(p["living"])
            parts.append(f"用度 {P.M.fmt(p['living'])}")
        if cost:
            if p["cash"] >= cost:
                P.add_cash(name, -cost, "本季开销：" + "，".join(parts))
                print(f"  开销 −{P.M.fmt(cost)}（{'，'.join(parts)}）")
            elif p["cash"] + P.home(name) >= cost:
                rest = cost - p["cash"]
                P.add_cash(name, -p["cash"], "本季开销：" + "，".join(parts))
                note = P.add_home(name, -rest, "本季开销（身上不够，动了家当）")
                print(f"  开销 −{P.M.fmt(cost)}（{'，'.join(parts)}），身上不够，动了家当" + (f"；{note}" if note else ""))
            else:
                warn.append(f"{name}：本季开销 {P.M.fmt(cost)}（{'，'.join(parts)}），身上和家当都不够——要借钱、当东西，或者马要饿瘦")
        print(f"  随身 {P.M.fmt(p['cash'])}，家当 {P.M.fmt(P.home(name))}")
    print("--- 借贷 ---")
    any_d = False
    for x in P.d["debts"]:
        if x["status"] != "未还":
            continue
        any_d = True
        if x["since_turn"] < P.turn and x.get("rate"):
            inc = int(round(x["owed"] * float(x["rate"])))
            x["owed"] += inc
            x["log"].append(f"{P.when}：利 {P.M.fmt(inc)}")
        line = f"  {x['id']} {x['debtor']} 欠 {x['creditor']} {P.M.fmt(x['owed'])}（{x['what']}）"
        if x.get("due_turn") and P.turn >= int(x["due_turn"]):
            line += "——到期了"
            warn.append(f"借据 {x['id']}：{x['debtor']} 欠 {x['creditor']} {P.M.fmt(x['owed'])} 到期；债主会来要（GM 照债主的性子写）")
        print(line)
    if not any_d:
        print("  （没有未还的借据）")
    if warn:
        print("\n要 GM 留意：")
        for w in warn:
            print(f"  · {w}")
    P.d["last_season_turn"] = P.turn
    if P.hero in P.d["people"] and P.home_in_treasury(P.hero):
        n = len(P.horses(P.hero))
        P.kingdom.setdefault("treasury", {})["horses"] = n
    finish(P, args)


# ---------------------------------------------------------------- 主程序

def main():
    ap = argparse.ArgumentParser(description="个人钱物（规则见 rules/purse.md）", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--world", default=X.DEFAULT_WORLD)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn, write=True):
        p = sp.add_parser(name, help=help_)
        p.add_argument("--world", default=argparse.SUPPRESS)
        if write:
            p.add_argument("--apply", action="store_true")
        p.set_defaults(fn=fn)
        return p

    p = add("show", "看钱物", cmd_show, write=False)
    p.add_argument("name", nargs="?")
    p.add_argument("--all", action="store_true")
    p = add("ledger", "看账", cmd_ledger, write=False)
    p.add_argument("name")
    p.add_argument("--n", type=int, default=20)
    p = add("open", "建档", cmd_open)
    p.add_argument("name")
    p.add_argument("--cash")
    p.add_argument("--home")
    p.add_argument("--living")
    p.add_argument("--note")
    p = add("spend", "花钱", cmd_spend)
    p.add_argument("name")
    p.add_argument("--amount", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--from", dest="from_", choices=("cash", "home"), default="cash")
    p.add_argument("--to")
    p.add_argument("--kind", choices=SPEND_KINDS)
    p = add("earn", "进项", cmd_earn)
    p.add_argument("name")
    p.add_argument("--amount", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--to", choices=("cash", "home"), default="cash")
    p.add_argument("--from", dest="from_")
    p = add("give", "给钱、给东西", cmd_give)
    p.add_argument("name")
    p.add_argument("--to", required=True)
    p.add_argument("--amount")
    p.add_argument("--item")
    p.add_argument("--what", required=True)
    p.add_argument("--kind", choices=GIVE_KINDS)
    p.add_argument("--from", dest="from_", choices=("cash", "home"), default="cash")
    p = add("move", "存钱、取钱", cmd_move)
    p.add_argument("name")
    p.add_argument("--amount", required=True)
    p.add_argument("--to", required=True, choices=("cash", "home"))
    p = add("item", "物件", cmd_item)
    isp = p.add_subparsers(dest="sub", required=True)
    q = isp.add_parser("add")
    q.add_argument("owner")
    q.add_argument("--kind", required=True)
    q.add_argument("--name", dest="name_", required=True)
    q.add_argument("--desc")
    q.add_argument("--story")
    q.add_argument("--value")
    q.add_argument("--where")
    q.add_argument("--secret")
    q.add_argument("--feed")
    q.add_argument("--issued", action="store_true")
    q = isp.add_parser("story")
    q.add_argument("id")
    q.add_argument("--add", required=True)
    q = isp.add_parser("set")
    q.add_argument("id")
    q.add_argument("fields", nargs="+")
    q = isp.add_parser("give")
    q.add_argument("id")
    q.add_argument("--to", required=True)
    q.add_argument("--what")
    q.add_argument("--kind", choices=GIVE_KINDS)
    q = isp.add_parser("status")
    q.add_argument("id")
    q.add_argument("--status", required=True)
    q.add_argument("--amount")
    q.add_argument("--why", required=True)
    for q in isp.choices.values():
        q.add_argument("--apply", action="store_true")
        q.add_argument("--world", default=argparse.SUPPRESS)
    p = add("borrow", "借钱", cmd_borrow)
    p.add_argument("name")
    p.add_argument("--from", dest="from_", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--rate", type=float, default=0.0)
    p.add_argument("--due", type=int)
    p.add_argument("--what", required=True)
    p = add("repay", "还钱", cmd_repay)
    p.add_argument("id")
    p.add_argument("--amount")
    p.add_argument("--from", dest="from_", choices=("cash", "home"), default="cash")
    p.add_argument("--why")
    p = add("debt", "借据改状态", cmd_debt)
    p.add_argument("id")
    p.add_argument("--status", required=True, choices=("赖账", "免了"))
    p.add_argument("--why", required=True)
    p = add("fine", "罚俸、罚钱", cmd_fine)
    p.add_argument("name")
    p.add_argument("--seasons", type=int)
    p.add_argument("--amount")
    p.add_argument("--why", required=True)
    p = add("stipend", "每季常例", cmd_stipend)
    p.add_argument("name")
    p.add_argument("--amount")
    p.add_argument("--what")
    p.add_argument("--remove", type=int)
    p = add("pay", "发本季俸钱", cmd_pay)
    p.add_argument("name", nargs="?")
    p = add("season", "季末", cmd_season)
    p.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.cmd == "stipend" and not args.remove and (args.amount is None or not args.what):
        X.die("添常例要 --amount 和 --what；去掉用 --remove 序号")
    args.fn(Purse(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
