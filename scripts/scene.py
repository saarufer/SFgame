#!/usr/bin/env python3
"""场景模式：一回合是一季，季里面可以单独走一个“场景”——巡夜、赴约、追人、宴席、朝会、拿人——按一夜、一日、一个时辰推进。
规则见 rules/scene.md。只用标准库。

存档是 world/scenes.json（眼下开着的场景、走完的场景）。场景里发生的事先记成“待写回”的几条命令，
场景结束（close）时一并交给现有的脚本写回：关系网 relations.py、秘密 secrets.py、流言 rumors.py、
个人钱物 purse.py、伤势 contest.py、名册与识人 persona.py / vignette.py；再在 actions.json 里记本季的行动件数。
每记一件事，脚本先在一份存档副本（沙盘）里试跑一遍那条命令，跑不通的不记；close 不加 --apply 时，整套写回在新的副本上演一遍给 GM 看。

  开场     open --title 题目 --kind 巡夜|宿卫|朝会|赴约|追人|宴席|拿人|私访|其他 --where 地区 --time 时辰
                [--date 二月廿八] [--spot 去处] [--people 名,名] [--pass 名,名] [--mounted 名,名]
                [--weather 天气|随机] [--curfew auto|on|off] [--size 小|大] [--count 0|1|2] [--duty] [--prologue] [--span 一夜|一日|一个时辰]
  看       status                    log [场景编号]
  时辰     tick [--steps N | --to 时辰] [--note …]        时辰写成 戌初、戌正、亥、三更、黄昏……；一步是半个时辰
  走动     move 名,名 --to 地区 [--mounted] [--no-tick]    相邻一格走一步（骑马两格一步）；夜禁中穿坊的提醒犯夜
  人       join 名 [--where 地区] [--pass]    leave 名
           person 名 --role 身份 [--hint 特征 …] [--age N] [--sex 男|女] [--trait …]    新面孔：记进名册（persona.py gen）并入场
  见面     meet 甲 乙 [--how 见面|长谈|共事|交手]        有主角的记识人；见面只记一笔
  得知     learn 名,名 --secret 编号 --depth 全知|大略|风闻 [--how 亲见|转述|…] [--from 名]
  证据     evidence 编号 [--add 种类:描述@持有人] [--move 证据编号 --to 名] [--status 证据编号=毁|失|呈上]
  恩怨     deed --event 救命|援手|羞辱|… --by 做事的人 --to 受者 [--what …] [--strength N] [--known 公开|两人|暗]
           deed --holder 甲 --toward 乙 --kind 恩|怨 --what … --strength N [--known …]
           tag 甲 乙 --tag 私交 [--hidden] [--knowers 名,名]
  钱物     spend 名 --amount 钱 --what … [--to 名] [--kind …] [--from cash|home]
           give 甲 --to 乙 (--amount 钱 | --item 物件) --what … [--kind 赏赐|送礼|行贿|周济]
           earn 名 --amount 钱 --what … [--from 名]
           item 名 --kind 兵器|马|衣甲|物件|文书 --name 名称 [--desc …] [--story 来历] [--value 钱] [--secret 编号]
  伤势     wound 名 --level 轻伤|重伤|危 [--where 部位] [--seasons N]
  流言     rumor --text … --truth 真|假|半真 --circle 圈子 [--source 谁] [--about 名] [--heat N] [--cred N] [--effect …]
  别的     op 脚本名 参数…           例：op household.py visit baijing --what 兄弟俩在邸店说了半夜话（不写 --world、--apply）
           try 脚本名 参数…          在场景的沙盘上跑一条命令看看，不记、不写回（例：try contest.py run --kind 打架 --a 主角 --b 新面孔 --seed 7）
           note 一句话               只进场景记录（写史书用）
           act --what …              当值的场景里主角另做了自己的事，另记一件
  收场     close [--apply]           写回各存档、记本季件数；不加 --apply 只在副本上演一遍
           cancel --why …            作罢，什么都不写回

每条记事可以加 --tick N（这件事花了几步）。所有命令都有 --world。
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import scenario_lib as S  # noqa: E402
import social_lib as X  # noqa: E402

FILE = "scenes.json"
EMPTY = {"version": 1, "current": None, "history": [], "next": 1}

# ---------------------------------------------------------------- 时辰

ZHI = "子丑寅卯辰巳午未申酉戌亥"
STEPS = 24          # 一天 24 步：每个时辰分初、正两步（各合一个钟头）
GENG = {20: "一更", 21: "一更", 22: "二更", 23: "二更", 0: "三更", 1: "三更", 2: "四更", 3: "四更", 4: "五更", 5: "五更"}
ALIASES = {"夜半": "子初", "半夜": "子初", "子夜": "子初", "鸡鸣": "丑正", "黎明": "寅正", "拂晓": "卯初", "天亮": "卯初", "日出": "卯正",
           "清早": "辰初", "早上": "辰初", "上午": "巳初", "中午": "午正", "正午": "午正", "午后": "未初", "下午": "申初",
           "傍晚": "酉初", "日落": "酉正", "黄昏": "酉正", "入夜": "戌初", "夜里": "戌正", "深夜": "亥正"}
SPANS = {"一夜": None, "一日": None, "一个时辰": 2, "半个时辰": 1}
KINDS = {  # 默认：是不是本分（当值、奉差）、算几件、默认走多久
    "巡夜": {"duty": True, "count": 0, "span": "一夜"},
    "宿卫": {"duty": True, "count": 0, "span": "一夜"},
    "朝会": {"duty": True, "count": 0, "span": "一个时辰"},
    "拿人": {"duty": False, "count": 1, "span": "一夜"},
    "赴约": {"duty": False, "count": 1, "span": "一个时辰"},
    "追人": {"duty": False, "count": 1, "span": "一夜"},
    "宴席": {"duty": False, "count": 1, "span": "一个时辰"},
    "私访": {"duty": False, "count": 1, "span": "一个时辰"},
    "其他": {"duty": False, "count": 1, "span": "一个时辰"},
}
WEATHER = {
    "春": ["晴，有风", "多云", "微雨", "风大，扬着沙", "阴，有些冷", "晴，月色好"],
    "夏": ["晴热", "闷热，没有风", "雷雨", "阴", "夜里凉快些，星星很多"],
    "秋": ["晴，天高", "秋雨，路上泥泞", "起风了", "薄雾", "夜凉如水"],
    "冬": ["晴冷", "下雪", "大风", "阴寒", "雪停了，地上反光"],
}


def t_index(s):
    """“戌初”“戌正”“戌”“一更”“三更”“黄昏” → 0–23。"""
    s = str(s).strip()
    s = ALIASES.get(s, s)
    for i, g in enumerate(("一更", "二更", "三更", "四更", "五更")):
        if s.startswith(g):
            return {0: 20, 1: 22, 2: 0, 3: 2, 4: 4}[i]
    s = s.replace("时", "")
    if s and s[0] in ZHI:
        base = ZHI.index(s[0]) * 2
        rest = s[1:]
        if rest in ("", "初"):
            return base
        if rest == "正":
            return base + 1
    X.die(f"看不懂时辰“{s}”：写成 戌初、戌正、亥、三更、黄昏")


def t_label(i, geng=True):
    i %= STEPS
    lab = f"{ZHI[i // 2]}{'初' if i % 2 == 0 else '正'}"
    if geng and i in GENG:
        lab += f"（{GENG[i]}）"
    return lab


class Curfew:
    def __init__(self, world):
        sc = S.load(world)
        cfg = (sc.get("scene") or {}).get("curfew") or {}
        self.name = cfg.get("name") or "夜禁"
        self.f = t_index(cfg["from"]) if cfg.get("from") else None
        self.t = t_index(cfg["to"]) if cfg.get("to") else None
        self.note = cfg.get("note", "")
        self.drums = (sc.get("scene") or {}).get("drums") or {}

    @property
    def exists(self):
        return self.f is not None and self.t is not None

    def active(self, i, mode="auto"):
        if mode == "on":
            return True
        if mode == "off" or not self.exists:
            return False
        i %= STEPS
        return (self.f <= i < self.t) if self.f <= self.t else (i >= self.f or i < self.t)


# ---------------------------------------------------------------- 存档与沙盘

class Book:
    def __init__(self, world):
        self.world = os.path.abspath(world)
        self.d = X.load_json(self.world, FILE, EMPTY)
        for k, v in EMPTY.items():
            self.d.setdefault(k, json.loads(json.dumps(v)))
        self.curfew = Curfew(self.world)
        self._map = None

    @property
    def cur(self):
        return self.d.get("current")

    def need(self):
        if not self.cur:
            X.die("眼下没有开着的场景。open 开一个")
        return self.cur

    def save(self):
        return X.save_json(self.world, FILE, self.d)

    @property
    def regions(self):
        if self._map is None:
            self._map = X.load_json(self.world, "map.json", {"regions": {}}).get("regions", {})
        return self._map


def cards_dir(world):
    d = os.path.join(os.path.dirname(os.path.abspath(world)), "characters")
    return d if os.path.isdir(d) else os.path.join(ROOT, "characters")


def make_sandbox(world):
    """把存档和人格卡复制一份到临时目录，返回副本里的 world 路径。"""
    tmp = tempfile.mkdtemp(prefix="scene_sandbox_")
    w2 = os.path.join(tmp, "world")
    shutil.copytree(world, w2, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(cards_dir(world), os.path.join(tmp, "characters"))
    parent_sc = os.path.join(os.path.dirname(os.path.abspath(world)), "scenario.json")
    if not os.path.exists(os.path.join(world, "scenario.json")) and os.path.exists(parent_sc):
        shutil.copy(parent_sc, os.path.join(tmp, "scenario.json"))
    return w2


def drop_sandbox(w2):
    if w2 and os.path.basename(w2) == "world" and "scene_sandbox_" in w2:
        shutil.rmtree(os.path.dirname(w2), ignore_errors=True)


def run_op(op, world, apply=True):
    """跑一条写回命令：op 是 [脚本名, 参数…]。返回 (成功与否, 输出)。"""
    script = os.path.join(HERE, op[0])
    if not os.path.exists(script):
        return False, f"没有脚本 {op[0]}"
    argv = [sys.executable, script, "--world", world] + list(op[1:]) + (["--apply"] if apply else [])
    r = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out.strip()


def sandbox(B):
    """场景的沙盘：记事时用。没有、或者被删了，就从真存档重建，把已记的命令重放一遍。"""
    sc = B.need()
    w2 = sc.get("sandbox")
    if w2 and os.path.isdir(w2):
        return w2
    w2 = make_sandbox(B.world)
    for ev in sc["events"]:
        if ev.get("op"):
            ok, out = run_op(ev["op"], w2)
            if not ok:
                print(f"  提醒：重建沙盘时，之前记的一条没跑通（真存档在场景开着时改过？）：{' '.join(ev['op'])}\n    {last_lines(out)}")
    sc["sandbox"] = w2
    return w2


def last_lines(out, n=3):
    lines = [l for l in out.splitlines() if l.strip()]
    return "\n    ".join(lines[-n:])


def shown(op):
    return "python3 scripts/" + " ".join(str(x) if " " not in str(x) else f'"{x}"' for x in op)


# ---------------------------------------------------------------- 场景里的人和地方

def people_index(world):
    import persona as P
    W = P.World(world)
    return W


def here(B, sc):
    """主角眼下在哪（场景开着时）；没有主角就用场景开场的地方。"""
    hero = (S.load(B.world).get("player") or {}).get("protagonist")
    return (sc["present"].get(hero) or {}).get("where") or sc["where"]


def label_now(sc):
    return f"第{sc['day']}日 {t_label(sc['clock'])}" if sc.get("day", 1) > 1 else t_label(sc["clock"])


def advance(B, steps, why=""):
    sc = B.need()
    out = []
    for _ in range(int(steps)):
        before = B.curfew.active(sc["clock"], sc.get("curfew", "auto"))
        sc["clock"] += 1
        if sc["clock"] >= STEPS:
            sc["clock"] -= STEPS
            sc["day"] = sc.get("day", 1) + 1
            out.append(f"过了子初，算第 {sc['day']} 日")
        after = B.curfew.active(sc["clock"], sc.get("curfew", "auto"))
        if after and not before:
            out.append(f"{B.curfew.name}开始了（{t_label(sc['clock'])}）：城门、坊门关了，大街上不许走动")
        if before and not after:
            out.append(f"{B.curfew.name}解了（{t_label(sc['clock'])}）：开门鼓响，坊门开了")
        for drum, at in (B.curfew.drums or {}).items():
            if t_index(at) == sc["clock"]:
                out.append(f"{drum}响了")
    if steps:
        sc["events"].append({"t": label_now(sc), "kind": "tick", "text": f"过了 {steps} 步（{steps * 0.5:g} 个时辰）" + (f"：{why}" if why else ""), "op": None})
    end = sc.get("end_plan")
    if end and (sc["day"], sc["clock"]) >= (end["day"], end["clock"]) and not sc.get("over_warned"):
        out.append(f"已到预定收场的时辰（{t_label(end['clock'])}）：该 close 了，要接着走也可以")
        sc["over_warned"] = True
    return out


def path(regions, a, b):
    """城里的路：不经过远地。返回经过的地区列表（含起止），走不到返回 None。"""
    if a == b:
        return [a]
    seen, q = {a: None}, [a]
    while q:
        x = q.pop(0)
        for y in regions.get(x, {}).get("adjacent", []):
            if y in seen or (regions.get(y, {}).get("far") and y != b):
                continue
            seen[y] = x
            if y == b:
                p = [y]
                while seen[p[-1]] is not None:
                    p.append(seen[p[-1]])
                return list(reversed(p))
            q.append(y)
    return None


# ---------------------------------------------------------------- 命令

def cmd_open(B, args):
    if B.cur:
        X.die(f"已经开着一个场景：{B.cur['id']}“{B.cur['title']}”。先 close 或 cancel")
    if args.where not in B.regions:
        X.die(f"地图上没有“{args.where}”")
    if B.regions[args.where].get("far"):
        print(f"提醒：{args.where} 是远地，场景照样能开（主角去了那里），只是城里的夜禁、坊门不管那边")
    kd = KINDS.get(args.kind) or X.die(f"--kind 只有 {'、'.join(KINDS)}")
    sc_meta = S.load(B.world)
    hero = (sc_meta.get("player") or {}).get("protagonist")
    clock = t_index(args.time)
    duty = args.duty or kd["duty"]
    count = args.count if args.count is not None else (0 if duty else (2 if args.size == "大" else kd["count"]))
    if args.prologue:
        count = 0
    span = args.span or kd["span"]
    if span == "一夜":
        end = {"day": 2 if clock >= 6 else 1, "clock": t_index("寅正")}
    elif span == "一日":
        end = {"day": 1, "clock": t_index("酉正")} if clock < t_index("酉正") else {"day": 2, "clock": t_index("酉正")}
    else:
        steps = SPANS.get(span) or X.die(f"--span 只有 {'、'.join(SPANS)}")
        e = clock + steps
        end = {"day": 1 + e // STEPS, "clock": e % STEPS}
    kingdom = X.kingdom(B.world)
    season = kingdom.get("season") or "春"
    sid = f"C{B.d['next']}"
    weather = args.weather
    if not weather or weather == "随机":
        table = ((sc_meta.get("scene") or {}).get("weather") or {}).get(season) or WEATHER.get(season) or WEATHER["春"]
        weather = random.Random(f"{sc_meta.get('id')}|{sid}|{X.turn_of(B.world)}").choice(table)
    W = people_index(B.world)
    present = {}
    names = [hero] + X.split_names(args.people) if hero else X.split_names(args.people)
    passes = set(X.split_names(args.pass_))
    mounted = set(X.split_names(args.mounted))
    unknown = []
    for n in names:
        if n in present:
            continue
        if W.find(n, quiet=True) is None:
            unknown.append(n)
        present[n] = {"where": args.where, "pass": n in passes, "mounted": n in mounted}
    sc = {"id": sid, "title": args.title, "kind": args.kind, "size": args.size, "duty": duty, "prologue": args.prologue,
          "count": count, "turn": X.turn_of(B.world), "season": season, "when": X.when_of(B.world), "date": args.date or "",
          "where": args.where, "spot": args.spot or "", "clock": clock, "day": 1, "start": {"day": 1, "clock": clock}, "end_plan": end,
          "weather": weather, "curfew": args.curfew, "present": present, "events": [], "sandbox": None, "acts": []}
    B.d["current"] = sc
    B.d["next"] += 1
    print(f"=== 开场 {sid}：{args.title}（{args.kind}{'，本分' if duty else ''}{'，序幕' if args.prologue else ''}） ===")
    print(f"  {sc['when']}" + (f" {sc['date']}" if sc["date"] else "") + f"，{t_label(clock)}，{args.where}" + (f"·{args.spot}" if args.spot else ""))
    print(f"  天气：{weather}；{B.curfew.name}：{'在' if B.curfew.active(clock, args.curfew) else '不在'}" + ("" if args.curfew == "auto" else f"（GM 定为 {args.curfew}）"))
    print(f"  在场：{'、'.join(present)}" + (f"；有公事、夜禁中能走：{'、'.join(passes)}" if passes else ""))
    print(f"  预定走到：{'第2日 ' if end['day'] > 1 else ''}{t_label(end['clock'])}（{span}）；算本季 {count} 件" + ("（本分）" if duty and not args.prologue else ""))
    for drum, at in (B.curfew.drums or {}).items():
        if t_index(at) == clock:
            print(f"  {drum}正在敲")
    if unknown:
        print(f"  提醒：{'、'.join(unknown)} 不在人格卡和名册里——新面孔用 person 名 --role 身份 记进来，再写场面")
    if count and (sc_meta.get("player") or {}).get("role") == "臣子":
        import actions as A
        AB = A.Book(B.world)
        if AB.used() + count > AB.cap():
            print(f"  提醒：本季已用 {AB.used()} / {AB.cap()} 件，这个场景再算 {count} 件就超了；先和玩家商量（或 --count 0 当本分、--duty）")
    if B.curfew.exists and B.curfew.note:
        print(f"  {B.curfew.name}的规矩：{B.curfew.note}")


def cmd_status(B, args):
    sc = B.need()
    print(f"=== 场景 {sc['id']}：{sc['title']}（{sc['kind']}，算 {sc['count']} 件） ===")
    print(f"  眼下：{label_now(sc)}；{B.curfew.name}{'中' if B.curfew.active(sc['clock'], sc.get('curfew', 'auto')) else '已解/未到'}；天气 {sc['weather']}")
    print("  在场：" + "；".join(f"{n}在{p['where']}" + ("（有公事）" if p.get("pass") else "") + ("（骑马）" if p.get("mounted") else "")
                              for n, p in sc["present"].items()))
    print("  记下的事：")
    for ev in sc["events"]:
        if ev["kind"] == "tick":
            continue
        print(f"    [{ev['t']}] {ev['text']}" + ("  → 待写回" if ev.get("op") else ""))
    n = sum(1 for ev in sc["events"] if ev.get("op"))
    print(f"  待写回 {n} 条；另记件数 {len(sc.get('acts', []))} 件")


def cmd_log(B, args):
    hist = B.d["history"]
    if not args.id:
        for h in hist:
            print(f"  {h['id']} 第 {h['turn']} 回合 {h.get('date', '')} {h['title']}（{h['kind']}，{h['where']}，{h['start']}→{h['end']}，{h['status']}）")
        if not hist:
            print("  （还没有走完的场景）")
        return
    h = next((x for x in hist if x["id"] == args.id), None) or X.die(f"没有场景 {args.id}")
    print(json.dumps(h, ensure_ascii=False, indent=2))


def record(B, args, kind, text, op=None, tick=0, check=True):
    """记一件事：有写回命令的先在沙盘里试跑；跑不通的不记。"""
    sc = B.need()
    out = ""
    if op and check:
        w2 = sandbox(B)
        ok, out = run_op(op, w2)
        if not ok:
            X.die(f"这一条在存档副本里没跑通，没有记：\n  {shown(op)}\n  {last_lines(out, 6)}")
    notes = advance(B, tick, text) if tick else []
    ev = {"t": label_now(sc), "kind": kind, "text": text, "op": op}
    sc["events"].append(ev)
    print(f"[{ev['t']}] {text}")
    if op:
        print(f"  待写回：{shown(op)}")
        if out:
            print(f"  （副本里试跑：{last_lines(out, 2)}）")
    for n in notes:
        print(f"  · {n}")
    return ev


def cmd_tick(B, args):
    sc = B.need()
    if args.to:
        target = t_index(args.to)
        steps = (target - sc["clock"]) % STEPS or STEPS
    else:
        steps = args.steps
    notes = advance(B, steps, args.note or "")
    print(f"过了 {steps} 步，到 {label_now(sc)}" + (f"：{args.note}" if args.note else ""))
    for n in notes:
        print(f"  · {n}")


def cmd_move(B, args):
    sc = B.need()
    who = X.split_names(args.names)
    if args.to not in B.regions:
        X.die(f"地图上没有“{args.to}”")
    if B.regions[args.to].get("far"):
        X.die(f"{args.to} 是远地，要走好些日子，场景里不走；收了场，在季里写他出远门")
    starts = {sc["present"][n]["where"] for n in who if n in sc["present"]}
    for n in who:
        if n not in sc["present"]:
            X.die(f"{n} 不在场（先 join）")
    if len(starts) > 1:
        X.die(f"这几个人不在一处（{'、'.join(starts)}），分开走")
    a = starts.pop()
    if a == args.to:
        X.die(f"{'、'.join(who)} 已经在 {a} 了")
    p = path(B.regions, a, args.to)
    if p is None:
        X.die(f"从 {a} 走不到 {args.to}")
    hops = len(p) - 1
    mounted = args.mounted or all(sc["present"][n].get("mounted") for n in who)
    steps = (hops + 1) // 2 if mounted else hops
    if args.tick is not None:
        steps = args.tick
    warn = []
    if hops and B.curfew.active(sc["clock"], sc.get("curfew", "auto")):
        bad = [n for n in who if not sc["present"][n].get("pass")]
        if bad:
            warn.append(f"{B.curfew.name}中出坊走大街：{'、'.join(bad)} 没有公事、没有文牒，撞上巡街的就算犯夜（剧本规矩）")
    for n in who:
        sc["present"][n]["where"] = args.to
        if args.mounted:
            sc["present"][n]["mounted"] = True
    text = f"{'、'.join(who)} 从 {a} 到 {args.to}" + (f"（经 {'、'.join(p[1:-1])}）" if len(p) > 2 else "") + ("，骑马" if mounted else "")
    notes = advance(B, 0 if args.no_tick else steps, text)
    sc["events"].append({"t": label_now(sc), "kind": "move", "text": text, "op": None})
    print(f"[{label_now(sc)}] {text}，走了 {0 if args.no_tick else steps} 步")
    for w in warn + notes:
        print(f"  · {w}")


def cmd_join(B, args):
    sc = B.need()
    W = people_index(B.world)
    if W.find(args.name, quiet=True) is None and not any(ev.get("kind") == "person" and ev.get("who") == args.name for ev in sc["events"]):
        X.die(f"{args.name} 不在人格卡和名册里。新面孔用 person {args.name} --role 身份")
    where = args.where or here(B, sc)
    sc["present"][args.name] = {"where": where, "pass": args.pass_, "mounted": args.mounted}
    record(B, args, "join", f"{args.name} 来了（{where}）", tick=args.tick)


def cmd_leave(B, args):
    sc = B.need()
    if args.name not in sc["present"]:
        X.die(f"{args.name} 不在场")
    sc.setdefault("gone", {})[args.name] = sc["present"].pop(args.name)
    record(B, args, "leave", f"{args.name} 走了" + (f"：{args.why}" if args.why else ""), tick=args.tick)


def cmd_person(B, args):
    sc = B.need()
    op = ["persona.py", "gen", args.name, "--role", args.role, "--where", args.where or here(B, sc),
          "--event", f"{sc['title']}（{sc.get('date') or sc['when']}）"]
    for h in args.hint or []:
        op += ["--hint", h]
    if args.age:
        op += ["--age", str(args.age)]
    if args.sex:
        op += ["--sex", args.sex]
    if args.trait:
        op += ["--trait", args.trait]
    sc["present"][args.name] = {"where": args.where or here(B, sc), "pass": args.pass_, "mounted": False}
    ev = record(B, args, "person", f"新面孔：{args.name}（{args.role}）" + (f"，{'；'.join(args.hint)}" if args.hint else ""), op, tick=args.tick)
    ev["who"] = args.name


def cmd_meet(B, args):
    sc = B.need()
    hero = (S.load(B.world).get("player") or {}).get("protagonist")
    a, b = args.a, args.b
    how = args.how
    sc.setdefault("meets", []).append([a, b, how])
    if how == "见面":
        return record(B, args, "meet", f"{a} 见了 {b}", tick=args.tick)
    if hero in (a, b):
        other = b if a == hero else a
        op = ["persona.py", "know", other, "--how", how, "--note", sc["title"]]
    else:
        op = ["persona.py", "know", b, "--by", a, "--how", how, "--note", sc["title"]]
    record(B, args, "meet", f"{a} 和 {b} {how}", op, tick=args.tick)


def cmd_learn(B, args):
    for n in X.split_names(args.names):
        op = ["secrets.py", "learn", args.secret, "--who", n, "--depth", args.depth]
        if args.how:
            op += ["--how", args.how]
        if args.from_:
            op += ["--from", args.from_]
        if args.knows:
            op += ["--knows", args.knows]
        record(B, args, "learn", f"{n} 得知秘密 {args.secret}（{args.depth}" + (f"，{args.how}" if args.how else "") + "）"
               + (f"：{args.what}" if args.what else ""), op, tick=args.tick)
        args.tick = 0


def cmd_evidence(B, args):
    op = ["secrets.py", "evidence", args.secret]
    if args.add:
        op += ["--add", args.add]
    if args.move:
        op += ["--move", args.move, "--to", args.to]
    if args.status:
        op += ["--status", args.status]
    if len(op) == 3:
        X.die("给 --add、--move 或 --status")
    record(B, args, "evidence", f"证据（秘密 {args.secret}）：{args.add or args.move or args.status}" + (f" → {args.to}" if args.to else ""), op, tick=args.tick)


def cmd_deed(B, args):
    if args.event:
        if not (args.by and args.to):
            X.die("--event 要 --by 和 --to")
        op = ["relations.py", "event", args.event, "--by", args.by, "--to", args.to]
        text = f"{args.by} 对 {args.to}：{args.event}" + (f"（{args.what}）" if args.what else "")
    else:
        if not (args.holder and args.toward and args.kind and args.what and args.strength):
            X.die("手记一笔要 --holder --toward --kind --what --strength")
        op = ["relations.py", "add", args.holder, "--toward", args.toward, "--kind", args.kind, "--strength", str(args.strength)]
        text = f"{args.holder} 记 {args.toward} 一笔{args.kind}（{args.strength}）：{args.what}"
    if args.what:
        op += ["--what", args.what]
    if args.strength and args.event:
        op += ["--strength", str(args.strength)]
    if args.known:
        op += ["--known", args.known]
    record(B, args, "deed", text, op, tick=args.tick)


def cmd_tag(B, args):
    op = ["relations.py", "tag", args.a, args.b, "--tag", args.tag]
    if args.hidden:
        op.append("--hidden")
    if args.knowers:
        op += ["--knowers", args.knowers]
    if args.roles:
        op += ["--roles", args.roles]
    record(B, args, "tag", f"{args.a} 和 {args.b}：{args.tag}" + ("（暗的）" if args.hidden else ""), op, tick=args.tick)


def cmd_spend(B, args):
    op = ["purse.py", "spend", args.name, "--amount", args.amount, "--what", args.what, "--from", args.from_]
    if args.to:
        op += ["--to", args.to]
    if args.kind:
        op += ["--kind", args.kind]
    record(B, args, "spend", f"{args.name} 花 {args.amount}：{args.what}" + (f"（给 {args.to}）" if args.to else ""), op, tick=args.tick)


def cmd_give(B, args):
    op = ["purse.py", "give", args.name, "--to", args.to, "--what", args.what]
    if args.amount:
        op += ["--amount", args.amount]
    if args.item:
        op += ["--item", args.item]
    if args.kind:
        op += ["--kind", args.kind]
    record(B, args, "give", f"{args.name} {args.kind or '给'} {args.to} {args.amount or args.item}：{args.what}", op, tick=args.tick)


def cmd_earn(B, args):
    op = ["purse.py", "earn", args.name, "--amount", args.amount, "--what", args.what]
    if args.from_:
        op += ["--from", args.from_]
    record(B, args, "earn", f"{args.name} 得 {args.amount}：{args.what}" + (f"（{args.from_} 给的）" if args.from_ else ""), op, tick=args.tick)


def cmd_item(B, args):
    op = ["purse.py", "item", "add", args.name, "--kind", args.kind, "--name", args.item_name]
    for k in ("desc", "story", "value", "secret", "where"):
        v = getattr(args, k)
        if v:
            op += [f"--{k}", v]
    record(B, args, "item", f"{args.name} 得了一件{args.kind}：{args.item_name}" + (f"（{args.story}）" if args.story else ""), op, tick=args.tick)


def cmd_wound(B, args):
    op = ["contest.py", "wound", args.name, "--level", args.level]
    if args.where:
        op += ["--where", args.where]
    if args.seasons:
        op += ["--seasons", str(args.seasons)]
    record(B, args, "wound", f"{args.name} 受了{args.level}" + (f"（{args.where}）" if args.where else ""), op, tick=args.tick)


def cmd_rumor(B, args):
    op = ["rumors.py", "spread", "--text", args.text, "--truth", args.truth, "--circle", args.circle]
    for k in ("source", "about", "heat", "cred", "effect", "note"):
        v = getattr(args, k)
        if v not in (None, ""):
            op += [f"--{k}", str(v)]
    record(B, args, "rumor", f"有了一句话（{args.circle}）：{args.text}", op, tick=args.tick)


def pull(op, flag):
    """从 REMAINDER 里取出 scene.py 自己的参数（--say、--tick），返回值或 None。"""
    if flag in op:
        i = op.index(flag)
        if i + 1 >= len(op):
            X.die(f"{flag} 后面要写值")
        v = op[i + 1]
        del op[i:i + 2]
        return v
    return None


def cmd_op(B, args):
    if not args.argv:
        X.die("op 后面写脚本名和参数，例：op household.py visit baijing --what …")
    op = list(args.argv)
    if op and op[0] == "--":
        op = op[1:]
    say = pull(op, "--say")
    tick = pull(op, "--tick")
    args.say = say or args.say
    args.tick = int(tick) if tick else args.tick
    if not op[0].endswith(".py"):
        op[0] += ".py"
    if "--world" in op or "--apply" in op:
        X.die("op 里不要写 --world、--apply：脚本会自己加")
    record(B, args, "op", args.say or f"写回：{' '.join(op)}", op, tick=args.tick)


def cmd_try(B, args):
    op = list(args.argv)
    if op and op[0] == "--":
        op = op[1:]
    if not op:
        X.die("try 后面写脚本名和参数")
    if not op[0].endswith(".py"):
        op[0] += ".py"
    w2 = sandbox(B)
    ok, out = run_op(op, w2, apply=False)
    print(out)
    if not ok:
        print("（没跑通）")
    print("\n（这是沙盘上的预演，什么都没记。结果要写回的，照它用 wound、deed、learn… 记下来；较量的 seed 记住，好让结果对得上）")


def cmd_note(B, args):
    record(B, args, "note", args.text, tick=args.tick)


def cmd_act(B, args):
    sc = B.need()
    sc.setdefault("acts", []).append({"what": args.what, "weight": args.weight})
    record(B, args, "act", f"（另记一件）{args.what}", tick=args.tick)


def auto_ops(B, sc):
    """收场时自动加的写回：名册里的人记一笔出场（vignette.py person seen）。"""
    W = people_index(B.world)
    ops = []
    new = {ev.get("who") for ev in sc["events"] if ev.get("kind") == "person"}
    everyone = dict(sc.get("gone", {}))
    everyone.update(sc["present"])
    for n, info in everyone.items():
        if n in new:
            continue
        p = W.find(n, quiet=True)
        if p is not None and p.source != "card":
            ops.append(["vignette.py", "person", "seen", n, "--event", f"{sc['title']}（{sc.get('date') or sc['when']}）",
                        "--where", info["where"]])
    return ops


def cmd_close(B, args):
    sc = B.need()
    ops = [ev["op"] for ev in sc["events"] if ev.get("op")] + auto_ops(B, sc)
    meta = S.load(B.world)
    vassal = (meta.get("player") or {}).get("role") == "臣子"
    print(f"=== 收场 {sc['id']}：{sc['title']}（{label_now(sc)}） ===")
    # 先在新的副本上把整套写回演一遍
    w2 = make_sandbox(B.world)
    fails = []
    for op in ops:
        ok, out = run_op(op, w2)
        if not ok:
            fails.append((op, out))
    drop_sandbox(w2)
    print(f"  写回 {len(ops)} 条：")
    for op in ops:
        print(f"    {shown(op)}")
    if fails:
        print("\n  副本里有几条没跑通（真存档在场景开着时改过？）：")
        for op, out in fails:
            print(f"    {shown(op)}\n      {last_lines(out, 4)}")
        if args.apply:
            X.die("有写回没跑通，什么都没写。改好（或 cancel 重来）再 close --apply")
    count = 0 if sc.get("prologue") else int(sc.get("count", 0))
    acts = sc.get("acts", [])
    if vassal:
        print(f"  本季件数：场景 {count} 件" + (f" + 另记 {sum(a['weight'] for a in acts)} 件" if acts else "")
              + ("（序幕，不算）" if sc.get("prologue") else "（本分）" if sc.get("duty") and not count else ""))
    else:
        print("  主角是一方之主：这个场景算不算亲裁的一件，GM 照 governance.py council 定")
    if not args.apply:
        print("\n（只在副本上演了一遍，真存档没动。确认后 close --apply。）")
        return
    real_fail = []
    for op in ops:
        ok, out = run_op(op, B.world)
        if not ok:
            real_fail.append((op, out))
    if real_fail:
        print("\n  写回时有几条出错（副本里是通的，多半是同时有别的改动）：")
        for op, out in real_fail:
            print(f"    {shown(op)}\n      {last_lines(out, 4)}")
    if vassal:
        import actions as A
        AB = A.Book(B.world)
        ref = f"场景 {sc['id']}"
        if count or sc.get("duty"):
            A.add_item(AB, sc["title"], "场景", weight=max(count, 1), duty=(count == 0), ref=ref, force=True)
        for a in acts:
            A.add_item(AB, a["what"], "其他", weight=a["weight"], ref=ref, force=True)
        AB.save()
        print(f"  {A.summary_line(AB)}" + ("——超了，和玩家商量" if AB.used() > AB.cap() else ""))
    drop_sandbox(sc.get("sandbox"))
    hist = {k: sc[k] for k in ("id", "title", "kind", "turn", "when", "date", "where", "spot", "weather", "count", "duty", "prologue")}
    hist.update({"start": t_label(sc["start"]["clock"]), "end": label_now(sc), "present": list(sc["present"]),
                 "left_early": list(sc.get("gone", {})), "meets": sc.get("meets", []), "events": [f"[{e['t']}] {e['text']}" for e in sc["events"] if e["kind"] != "tick"],
                 "writebacks": [shown(op) for op in ops], "status": "已收场" + ("（有写回出错）" if real_fail else "")})
    B.d["history"].append(hist)
    B.d["current"] = None
    B.save()
    print("\n场景记录（写史书用）：")
    for e in hist["events"]:
        print(f"  {e}")
    print(f"\n已写回，场景 {sc['id']} 收场。")


def cmd_cancel(B, args):
    sc = B.need()
    drop_sandbox(sc.get("sandbox"))
    hist = {k: sc[k] for k in ("id", "title", "kind", "turn", "when", "date", "where")}
    hist.update({"start": t_label(sc["start"]["clock"]), "end": label_now(sc), "status": f"作罢：{args.why}", "events": []})
    B.d["history"].append(hist)
    B.d["current"] = None
    print(f"场景 {sc['id']} 作罢：{args.why}（记下的事都不写回）")


def cmd_resync(B, args):
    sc = B.need()
    drop_sandbox(sc.get("sandbox"))
    sc["sandbox"] = None
    sandbox(B)
    print(f"沙盘重建了：从眼下的真存档复制一份，把场景里已记的 {sum(1 for e in sc['events'] if e.get('op'))} 条写回重放了一遍")


# ---------------------------------------------------------------- 主程序

def main():
    ap = argparse.ArgumentParser(description="场景模式（规则见 rules/scene.md）", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=X.DEFAULT_WORLD)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, tick=True):
        p = sp.add_parser(name)
        p.add_argument("--world", default=argparse.SUPPRESS)
        p.add_argument("--apply", action="store_true")
        if tick:
            p.add_argument("--tick", type=int, default=0, help="这件事花了几步（一步半个时辰）")
        p.set_defaults(fn=fn)
        return p

    p = add("open", cmd_open, tick=False)
    p.add_argument("--title", required=True)
    p.add_argument("--kind", required=True, choices=tuple(KINDS))
    p.add_argument("--where", required=True)
    p.add_argument("--time", required=True)
    p.add_argument("--date")
    p.add_argument("--spot")
    p.add_argument("--people")
    p.add_argument("--pass", dest="pass_")
    p.add_argument("--mounted")
    p.add_argument("--weather")
    p.add_argument("--curfew", choices=("auto", "on", "off"), default="auto")
    p.add_argument("--size", choices=("小", "大"), default="小")
    p.add_argument("--count", type=int, choices=(0, 1, 2))
    p.add_argument("--duty", action="store_true")
    p.add_argument("--prologue", action="store_true", help="序幕（开局那一场），不算件数")
    p.add_argument("--span", choices=tuple(SPANS))
    add("status", cmd_status, tick=False)
    p = add("log", cmd_log, tick=False)
    p.add_argument("id", nargs="?")
    p = add("tick", cmd_tick, tick=False)
    p.add_argument("--steps", type=int, default=1)
    p.add_argument("--to")
    p.add_argument("--note")
    p = add("move", cmd_move, tick=False)
    p.add_argument("names")
    p.add_argument("--to", required=True)
    p.add_argument("--mounted", action="store_true")
    p.add_argument("--no-tick", action="store_true")
    p.add_argument("--tick", type=int)
    p = add("join", cmd_join)
    p.add_argument("name")
    p.add_argument("--where")
    p.add_argument("--pass", dest="pass_", action="store_true")
    p.add_argument("--mounted", action="store_true")
    p = add("leave", cmd_leave)
    p.add_argument("name")
    p.add_argument("--why")
    p = add("person", cmd_person)
    p.add_argument("name")
    p.add_argument("--role", required=True)
    p.add_argument("--hint", action="append")
    p.add_argument("--age", type=int)
    p.add_argument("--sex", choices=("男", "女"))
    p.add_argument("--trait")
    p.add_argument("--where")
    p.add_argument("--pass", dest="pass_", action="store_true")
    p = add("meet", cmd_meet)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--how", choices=("见面", "长谈", "共事", "交手"), default="见面")
    p = add("learn", cmd_learn)
    p.add_argument("names")
    p.add_argument("--secret", required=True)
    p.add_argument("--depth", required=True, choices=("全知", "大略", "风闻"))
    p.add_argument("--how")
    p.add_argument("--from", dest="from_")
    p.add_argument("--what", help="只进场景记录：他看见、听见了什么")
    p.add_argument("--knows", help="他知道的那一截（大略、风闻的人），写进秘密的知情人条目，情报包照它给")
    p = add("evidence", cmd_evidence)
    p.add_argument("secret")
    p.add_argument("--add")
    p.add_argument("--move")
    p.add_argument("--to")
    p.add_argument("--status")
    p = add("deed", cmd_deed)
    p.add_argument("--event")
    p.add_argument("--by")
    p.add_argument("--to")
    p.add_argument("--holder")
    p.add_argument("--toward")
    p.add_argument("--kind", choices=("恩", "怨"))
    p.add_argument("--what")
    p.add_argument("--strength", type=int, choices=(1, 2, 3))
    p.add_argument("--known", choices=("公开", "两人", "暗"))
    p = add("tag", cmd_tag)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--tag", required=True)
    p.add_argument("--hidden", action="store_true")
    p.add_argument("--knowers")
    p.add_argument("--roles")
    p = add("spend", cmd_spend)
    p.add_argument("name")
    p.add_argument("--amount", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--to")
    p.add_argument("--kind")
    p.add_argument("--from", dest="from_", choices=("cash", "home"), default="cash")
    p = add("give", cmd_give)
    p.add_argument("name")
    p.add_argument("--to", required=True)
    p.add_argument("--amount")
    p.add_argument("--item")
    p.add_argument("--what", required=True)
    p.add_argument("--kind")
    p = add("earn", cmd_earn)
    p.add_argument("name")
    p.add_argument("--amount", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--from", dest="from_")
    p = add("item", cmd_item)
    p.add_argument("name")
    p.add_argument("--kind", required=True)
    p.add_argument("--name", dest="item_name", required=True)
    p.add_argument("--desc")
    p.add_argument("--story")
    p.add_argument("--value")
    p.add_argument("--secret")
    p.add_argument("--where")
    p = add("wound", cmd_wound)
    p.add_argument("name")
    p.add_argument("--level", required=True, choices=("轻伤", "重伤", "危"))
    p.add_argument("--where")
    p.add_argument("--seasons", type=int)
    p = add("rumor", cmd_rumor)
    p.add_argument("--text", required=True)
    p.add_argument("--truth", required=True, choices=("真", "假", "半真"))
    p.add_argument("--circle", required=True)
    p.add_argument("--source")
    p.add_argument("--about")
    p.add_argument("--heat", type=int)
    p.add_argument("--cred", type=int)
    p.add_argument("--effect")
    p.add_argument("--note")
    p = add("op", cmd_op)
    p.add_argument("--say", help="这一条在场景记录里怎么写")
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p = add("try", cmd_try, tick=False)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p = add("note", cmd_note)
    p.add_argument("text")
    p = add("act", cmd_act)
    p.add_argument("--what", required=True)
    p.add_argument("--weight", type=int, choices=(1, 2), default=1)
    add("close", cmd_close, tick=False)
    add("resync", cmd_resync, tick=False)
    p = add("cancel", cmd_cancel, tick=False)
    p.add_argument("--why", required=True)
    args = ap.parse_args()
    B = Book(os.path.abspath(args.world))
    args.fn(B, args)
    # 场景里的记事是场景自己的草稿本（scenes.json），记了就存；写回关系网、秘密、钱物这些别的存档，要等 close --apply
    if args.cmd not in ("status", "log", "close"):
        B.save()


if __name__ == "__main__":
    main()
