#!/usr/bin/env python3
"""关系网、朝议、流言、秘密几个脚本共用的小工具。只用标准库。

- 读写 world/ 下的 JSON 存档（默认只读，--apply 才写）；
- 当前回合和日期（kingdom.json 的 turn、date）；
- 名望：记在人格卡数值块的“名望”一行（“士林6 军中3”），或名册条目的“名望”字段；
- 圈子和名望的种类：world/rumors.json 的 circles、fame_kinds，没有就用中性的默认值。

规则见 rules/relations.md、rules/court.md、rules/rumors.md、rules/secrets.md。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

DEFAULT_WORLD = os.path.join(ROOT, "world")

# 名望的种类（剧本可在 rumors.json 的 fame_kinds 里换）
FAME_KINDS = ["士林", "军中", "市井", "诸蕃"]
FAME_DEFAULT = 2          # 没写名望的人，按“无闻”
FAME_WORDS = [(2, "无闻"), (4, "小有名气"), (6, "有名"), (8, "名重一时"), (10, "名满天下")]

# 圈子：消息在哪些人群里流传。fame 是这个圈子里的口碑算进哪一种名望；links 是圈子之间的往来（0–1）
DEFAULT_CIRCLES = {
    "宫中": {"fame": None, "links": {"朝堂": 0.5, "市井": 0.15}, "note": "后妃、宫人、宦官、近侍"},
    "朝堂": {"fame": "士林", "links": {"宫中": 0.3, "士林": 0.6, "市井": 0.3, "军中": 0.25}, "note": "在朝的官员"},
    "士林": {"fame": "士林", "links": {"朝堂": 0.5, "市井": 0.35}, "note": "读书人、举子、在野的名士"},
    "市井": {"fame": "市井", "links": {"士林": 0.25, "军中": 0.3, "朝堂": 0.15}, "note": "城里的百姓、商贩、酒肆茶坊"},
    "军中": {"fame": "军中", "links": {"市井": 0.3, "朝堂": 0.2, "诸蕃": 0.15}, "note": "将校、士卒"},
    "诸蕃": {"fame": "诸蕃", "links": {"军中": 0.2, "市井": 0.1}, "note": "外族、外藩、互市的胡商"},
}

HEAT_WORDS = ["无人提起", "私下耳语", "小范围流传", "传开了", "人人在说", "满城风雨"]
CRED_WORDS = ["没人信", "姑妄听之", "将信将疑", "多半信了", "深信不疑", "已经坐实"]


def die(msg):
    sys.exit(f"错误：{msg}")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def pad(s, width):
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(s))
    return str(s) + " " * max(width - w, 0)


# ---------------------------------------------------------------- 存档

def load_json(world, name, default=None):
    path = os.path.join(world, name)
    if not os.path.exists(path):
        if default is None:
            die(f"找不到 {path}")
        return json.loads(json.dumps(default))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        die(f"{path} 不是合法的 JSON：{e}")


def save_json(world, name, data):
    path = os.path.join(world, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def kingdom(world):
    return load_json(world, "kingdom.json", {})


def turn_of(world):
    return int(kingdom(world).get("turn", 1))


def when_of(world, when=None):
    """写进存档的时间：GM 给了就用，没给就用 kingdom.json 的 date。"""
    if when:
        return when
    k = kingdom(world)
    return k.get("date") or f"第 {k.get('turn', '?')} 回合"


def rel(path):
    ap = os.path.abspath(path)
    return os.path.relpath(ap, ROOT) if ap.startswith(ROOT + os.sep) else path


def split_names(s):
    if not s:
        return []
    if isinstance(s, list):
        out = []
        for x in s:
            out += split_names(x)
        return out
    return [x.strip() for x in re.split(r"[,，、]", s) if x.strip()]


# ---------------------------------------------------------------- 圈子与名望

def rumors_cfg(world):
    return load_json(world, "rumors.json", {})


def circles(world):
    c = rumors_cfg(world).get("circles")
    return c if c else DEFAULT_CIRCLES


def fame_kinds(world):
    return rumors_cfg(world).get("fame_kinds") or FAME_KINDS


def fame_word(v):
    for hi, w in FAME_WORDS:
        if v <= hi:
            return w
    return FAME_WORDS[-1][1]


def parse_fame(s):
    out = {}
    if not s:
        return out
    if isinstance(s, dict):
        return {k: int(v) for k, v in s.items()}
    for tok in str(s).split():
        m = re.match(r"^(\D+?)(-?\d+)$", tok)
        if not m:
            die(f"名望的写法是“士林6 军中3”，看不懂：{tok!r}")
        out[m.group(1)] = int(m.group(2))
    return out


def fmt_fame(d):
    return " ".join(f"{k}{v}" for k, v in d.items()) if d else "—"


class People:
    """借 persona.py 的 World 找人（人格卡或名册），读写名望。"""

    def __init__(self, world):
        import persona as P
        self.P = P
        self.W = P.World(world)
        self.world = world
        self._dirty_roster = False

    def find(self, name):
        return self.W.find(name, quiet=True)

    def exists(self, name):
        return self.find(name) is not None

    def house_member(self, name):
        """宫中、大族家宅里的人（没有人格卡、也不在名册里的），名望记在家宅条目上。返回 (文件名, 家宅, 条目) 或 None。"""
        cands = [os.path.join(self.world, "household.json")]
        hdir = os.path.join(self.world, "households")
        if os.path.isdir(hdir):
            cands += [os.path.join(hdir, f) for f in sorted(os.listdir(hdir)) if f.endswith(".json")]
        for path in cands:
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                hh = json.load(f)
            for m in hh.get("members", {}).values():
                if m.get("name") == name:
                    return path, hh, m
        return None

    def fame(self, name):
        p = self.find(name)
        d = {}
        if p is None:
            hm = self.house_member(name)
            if hm:
                d = parse_fame(hm[2].get("名望"))
        elif p.source == "card":
            with open(p.path, encoding="utf-8") as f:
                y = self.P.read_yaml(f.read()) or {}
            d = parse_fame(y.get("名望"))
        else:
            d = parse_fame(p.entry.get("名望"))
        return {k: d.get(k, FAME_DEFAULT) for k in fame_kinds(self.world)} | {k: v for k, v in d.items()}

    def set_fame(self, name, d):
        """写回名望。返回写到了哪里（卡片路径或“名册”）；找不到人返回 None。"""
        p = self.find(name)
        d = {k: clamp(int(v), 0, 10) for k, v in d.items()}
        if p is None:
            hm = self.house_member(name)
            if not hm:
                return None
            path, hh, m = hm
            m["名望"] = d
            with open(path, "w", encoding="utf-8") as f:
                json.dump(hh, f, ensure_ascii=False, indent=2)
                f.write("\n")
            return rel(path)
        if p.source == "card":
            self.P.set_card_fields(p.path, {"名望": fmt_fame(d)})
            return rel(p.path)
        p.entry["名望"] = d
        self.W.save_roster()
        return "名册"

    def attrs(self, name):
        p = self.find(name)
        return dict(p.attrs) if p else {}

    def tags(self, name):
        p = self.find(name)
        return (list(p.tags) + list(p.flaws)) if p else []

    def card_path(self, name):
        p = self.find(name)
        return p.path if p is not None and p.source == "card" else None

    def role(self, name):
        p = self.find(name)
        return p.role if p else None


def fame_of(people, name, kind):
    if people is None:
        return FAME_DEFAULT
    return people.fame(name).get(kind, FAME_DEFAULT)


# ---------------------------------------------------------------- 人在哪些圈子里

COURT_ROLES = ("文臣", "宫人", "皇子", "公主", "后妃", "外戚", "宗室", "宦官", "朝臣", "使节", "外臣", "僧道", "布衣")


def person_circles(world, name, people=None):
    """一个人平常在哪些圈子里听消息：rumors.json 的 members 写明的为准，再加上推得出来的。"""
    cfg = rumors_cfg(world)
    cs = circles(world)
    out = list(cfg.get("members", {}).get(name, []))
    court = load_json(world, "court.json", {})
    if any(o.get("holder") == name for o in court.get("offices", {}).values()) or name == court.get("sovereign"):
        out.append("朝堂")
    if name == court.get("sovereign"):
        out.append("宫中")
    hdir = os.path.join(world, "households")
    if os.path.isdir(hdir):
        for fn in os.listdir(hdir):
            if fn.endswith(".json"):
                hh = load_json(hdir, fn, {})
                if hh.get("kind") == "palace" and any(m.get("name") == name for m in hh.get("members", {}).values()):
                    out.append("宫中")
    if people is not None:
        r = people.role(name)
        if r == "将领":
            out.append("军中")
        elif r in ("宫人", "后妃", "皇子", "公主", "宦官"):
            out.append("宫中")
        elif r in ("文臣", "朝臣"):
            out.append("朝堂")
        elif r in ("僧道", "布衣", "使节"):
            # 剧本的圈子可能改了名（例（长安夜）：“长安市井”），按口碑算进哪种名望来找：僧道、布衣在市井，使节在诸蕃
            want = "诸蕃" if r == "使节" else "市井"
            hit = want if want in cs else next((c for c, v in cs.items() if v.get("fame") == want), None)
            if hit:
                out.append(hit)
        # 外臣（外邦的官）在哪个圈子，照 rumors.json 的 members 写
    seen, res = set(), []
    for c in out:
        if c in cs and c not in seen:
            seen.add(c)
            res.append(c)
    return res
