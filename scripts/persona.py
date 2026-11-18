#!/usr/bin/env python3
"""人物属性：固定逻辑生成、名册、识人与印象、升格成人格卡。规则见 rules/people.md。只用标准库。

身份表、特长、短处、提示词、性情、描述词这几张表直接从 rules/people.md 读；剧本可在
scenario.json 的 people.identities 里追加或覆盖身份。随机种子取“剧本 id｜姓名｜身份”的哈希，
同一个人每次生成的结果一样。

  生成     gen 名 --role 身份 [--age N] [--sex 男|女] [--hint 特征 ...] [--where 所在] [--trait 特征] [--event 出场] [--apply]
  查看     show 名 [--json]
  印象     impress 名 [--level 0-3] [--by 观者] [--gm]
  识人     know 名 --how 见面|长谈|共事|交手|打听 [--long] [--by 观者] [--set N] [--note 说明] [--apply]
  升格     promote 名 --card characters/x.md --kind 将领|家人|君主 [--apply]
  主角     hero 主角卡 --origin 出身 [--temper 性格 ...] [--age N] [--apply]
  补齐     fill 卡片 [--role 身份] [--apply]
  身份表   roles
  抽样     stats [--role 身份] [--n 200]

会改存档、改卡片的命令默认只打印；加 --apply 才写回。--world 指向别的存档目录（试验用）。
"""
import argparse
import glob
import hashlib
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

ATTRS = ["统", "武", "智", "骑", "射", "体", "胆", "辩", "学", "政", "魅"]
ATTR_NOUN = {"统": "带兵", "武": "武艺", "智": "心计", "骑": "骑术", "射": "射艺", "体": "体力", "胆": "胆气",
             "辩": "口才", "学": "学问", "政": "理事", "魅": "人望"}
KNOW_NAMES = ["初见", "略知", "熟知", "知根知底"]
DEFAULT_SPREAD = 1.2
RULES_PATH = os.path.join(ROOT, "rules", "people.md")
INJURY_LEVELS = ["轻伤", "重伤", "危"]
# 每项属性的说明，写进人格卡数值块的注释
ATTR_NOTE = {"统": "统兵 1–10（十一项属性见 rules/people.md）", "武": "武艺膂力", "智": "谋略", "骑": "骑术",
             "射": "射艺", "体": "体魄耐力", "胆": "胆气", "辩": "口才", "学": "学识", "政": "理事", "魅": "人望"}
KNOW_NOTE = "主角对他知道多少：0 初见 / 1 略知 / 2 熟知 / 3 知根知底"
INJURY_NOTE = "无，或 轻伤｜部位｜余 N 季（scripts/contest.py heal 逐季恢复）"
AGE_MODS = [  # (上限, 修正)
    (15, {"统": -2, "武": -2, "体": -2, "政": -2, "学": -1}),
    (24, {"体": 1, "学": -1, "政": -1}),
    (44, {}),
    (59, {"体": -1}),
    (999, {"体": -3, "武": -2, "骑": -1, "射": -1, "学": 1}),
]
HOW = {  # 识人进度怎么涨：(增量, 上限)；打听是“到 1”
    "见面": (0, 0), "长谈": (1, 2), "共事": (1, 2), "交手": (1, 3), "打听": (None, 1),
}


def die(msg):
    sys.exit(f"错误：{msg}")


def clamp(x, lo=1, hi=10):
    return max(lo, min(hi, x))


def tier(v):
    """1–2→0，3–4→1，5–6→2，7–8→3，9–10→4"""
    return min(4, max(0, (int(round(v)) - 1) // 2))


# ---------------------------------------------------------------- 读 rules/people.md

def md_table(text, heading):
    """返回 heading 下第一张表：(表头, [行])。同名标题有几个的，取第一个下面直接有表的。"""
    lines = text.splitlines()
    starts = [i + 1 for i, l in enumerate(lines) if re.match(r"^#+\s*" + re.escape(heading) + r"\s*$", l.strip())]
    if not starts:
        die(f"rules/people.md 里找不到“{heading}”一节")
    for start in starts:
        rows, header = [], None
        for l in lines[start:]:
            s = l.strip()
            if s.startswith("#"):
                break
            if not s.startswith("|"):
                if header is not None:
                    break
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if header is None:
                header = cells
            elif all(re.fullmatch(r":?-+:?", c) for c in cells if c):
                continue
            else:
                rows.append(cells)
        if header is not None:
            return header, rows
    die(f"rules/people.md 的“{heading}”下面没有表")


MOD_RE = re.compile(r"([^\s+\-=、，,]+?)\s*([+\-])\s*(\d+(?:\.\d+)?)(%?)")


def parse_mods(cell):
    """“武+1 体−2 诈术+10% 易中诈 短处=腿脚不便” → ({键: 数}, [标记], {键: 值})"""
    s = (cell or "").replace("−", "-").replace("＋", "+")
    mods, flags, sets = {}, [], {}
    for m in re.finditer(r"(\S+?)=(\S+)", s):
        sets[m.group(1)] = m.group(2)
    s2 = re.sub(r"\S+?=\S+", " ", s)
    for m in MOD_RE.finditer(s2):
        v = float(m.group(3)) / (100 if m.group(4) else 1)
        mods[m.group(1)] = mods.get(m.group(1), 0) + (v if m.group(2) == "+" else -v)
    rest = MOD_RE.sub(" ", s2)
    flags = [w for w in re.split(r"[\s、，,]+", rest) if w]
    return mods, flags, sets


def split_list(cell):
    return [x.strip() for x in re.split(r"[、，,；;]", cell or "") if x.strip() and x.strip() not in ("—", "-", "无")]


def parse_mean(cell):
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:±\s*(\d+(?:\.\d+)?))?\s*$", str(cell))
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2)) if m.group(2) else DEFAULT_SPREAD


class Tables:
    def __init__(self, world):
        try:
            with open(RULES_PATH, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            die(f"读不到 {RULES_PATH}：{e}")
        self.identities = {}
        hdr, rows = md_table(text, "身份表")
        col = {h: i for i, h in enumerate(hdr)}
        for a in ATTRS:
            if a not in col:
                die(f"rules/people.md 的身份表缺“{a}”一列")
        for r in rows:
            if len(r) < len(hdr):
                continue
            idn = {"name": r[col["身份"]], "aliases": split_list(r[col["别名"]]), "mean": {}, "spread": {},
                   "tags": split_list(r[col["常见特长"]]), "flaws": split_list(r[col["常见短处"]]), "source": "引擎"}
            idn["age"], idn["sex"] = parse_age(r[col["年纪"]])
            for a in ATTRS:
                m, sp = parse_mean(r[col[a]])
                if m is None:
                    die(f"rules/people.md 身份表“{idn['name']}”的“{a}”看不懂：{r[col[a]]!r}")
                idn["mean"][a], idn["spread"][a] = m, sp
            self.identities[idn["name"]] = idn
        self.tags = self._mod_table(text, "特长")
        self.flaws = self._mod_table(text, "短处")
        self.hints = []
        _, rows = md_table(text, "提示词")
        for r in rows:
            mods, flags, sets = parse_mods(r[1])
            self.hints.append({"words": split_list(r[0]), "mods": mods, "flaw": sets.get("短处"), "tag": sets.get("特长")})
        self.tempers = []
        _, rows = md_table(text, "性情")
        for r in rows:
            self.tempers.append((r[0], [x.strip() for x in re.split(r"[；;]", r[1]) if x.strip()]))
        self.looks = self._word_table(text, "外表")
        self.desc = self._word_table(text, "描述词")
        self.origins = []
        _, rows = md_table(text, "出身倾向")
        for r in rows:
            up, _, _ = parse_mods(r[1])
            down, _, _ = parse_mods(r[2])
            self.origins.append({"key": r[0], "up": up, "down": down, "tags": split_list(r[3])})
        self.temper_mods = {}
        _, rows = md_table(text, "性格倾向")
        for r in rows:
            up, _, _ = parse_mods(r[1])
            down, _, _ = parse_mods(r[2])
            self.temper_mods[r[0]] = {**up, **down}
        self._scenario(world)

    @staticmethod
    def _mod_table(text, heading):
        out = {}
        _, rows = md_table(text, heading)
        for r in rows:
            gen, _, _ = parse_mods(r[1])
            con, flags, _ = parse_mods(r[2] if len(r) > 2 else "")
            out[r[0]] = {"gen": gen, "contest": con, "flags": flags, "note": r[3] if len(r) > 3 else ""}
        return out

    @staticmethod
    def _word_table(text, heading):
        hdr, rows = md_table(text, heading)
        out = {}
        for r in rows:
            if r[0] in ATTRS and len(r) >= 6:
                out[r[0]] = r[1:6]
        return out

    def _scenario(self, world):
        sc = S.load(world) if world else {}
        for e in (sc.get("people") or {}).get("identities", []):
            name = e.get("name")
            if not name:
                die("scenario.json 的 people.identities 里有一条没写 name")
            if e.get("base"):
                b = self.identities.get(e["base"])
                if not b:
                    die(f"scenario.json 的身份“{name}”的 base“{e['base']}”不在 rules/people.md 的身份表里")
                idn = json.loads(json.dumps(b))
            else:
                idn = {"aliases": [], "mean": {}, "spread": {}, "tags": [], "flaws": [], "age": (18, 50), "sex": "男"}
            idn["name"] = name
            idn["source"] = "剧本"
            idn["aliases"] = list(e.get("aliases", []))
            for a, v in (e.get("attrs") or {}).items():
                if a not in ATTRS:
                    die(f"scenario.json 的身份“{name}”的属性“{a}”不认识（只有 {'、'.join(ATTRS)}）")
                m, sp = parse_mean(v)
                if m is None:
                    die(f"scenario.json 的身份“{name}”的“{a}”看不懂：{v!r}")
                idn["mean"][a], idn["spread"][a] = m, sp
            missing = [a for a in ATTRS if a not in idn["mean"]]
            if missing:
                die(f"scenario.json 的身份“{name}”没有 base，又缺属性：{'、'.join(missing)}")
            if e.get("tags") is not None:
                idn["tags"] = list(e["tags"])
            if e.get("flaws") is not None:
                idn["flaws"] = list(e["flaws"])
            if e.get("age"):
                idn["age"], _ = parse_age(str(e["age"]))
            if e.get("sex"):
                idn["sex"] = e["sex"]
            self.identities[name] = idn

    def identity(self, role, strict=True):
        role = (role or "").strip()
        if role in self.identities:
            return self.identities[role]
        for idn in self.identities.values():
            if role in idn["aliases"]:
                return idn
        hits = []
        for idn in self.identities.values():
            for w in [idn["name"]] + idn["aliases"]:
                if w and w in role:
                    hits.append((len(w), idn))
        if hits:
            return max(hits, key=lambda x: x[0])[1]
        if strict:
            die(f"身份“{role}”不在身份表里。可用：{'、'.join(self.identities)}（rules/people.md 第三节；剧本可在 scenario.json 的 people.identities 里追加）")
        return None


def parse_age(cell):
    m = re.search(r"(\d+)\s*[-–—~]\s*(\d+)", cell or "")
    age = (int(m.group(1)), int(m.group(2))) if m else (18, 50)
    return age, ("女" if "女" in (cell or "") else "男")


# ---------------------------------------------------------------- 生成

def scenario_id(world):
    sid = S.load(world).get("id")
    if not sid:
        die(f"{world} 里没有 scenario.json 的 id：生成人物要用剧本 id 作种子。新局请从 scenarios/<剧本>/ 铺开")
    return sid


def seed_key(sid, name, identity):
    return f"{sid}|{name}|{identity}"


def seed_int(key):
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16)


def age_mods(age):
    for hi, mods in AGE_MODS:
        if age <= hi:
            return mods
    return {}


def generate(T, sid, name, role, age=None, sex=None, hints=()):
    """按身份表生成一个人。同样的 剧本 id、姓名、身份，结果相同。"""
    idn = T.identity(role)
    key = seed_key(sid, name, idn["name"])
    rng = random.Random(seed_int(key))
    lo, hi = idn["age"]
    age0 = rng.randint(lo, hi)        # 总是先掷，给了年纪也不影响后面的骰子
    age = int(age) if age else age0
    sex = sex or idn["sex"]
    vals = {a: idn["mean"][a] + rng.gauss(0, idn["spread"][a]) for a in ATTRS}
    notes = []
    # 年纪修正：按和这个身份常见年纪（年纪范围的中间）的差别算，身份表的均值已经是常见年纪的样子
    typical = age_mods((lo + hi) // 2)
    for a, d in age_mods(age).items():
        vals[a] += d
    for a, d in typical.items():
        vals[a] -= d
    if sex == "女" and idn["sex"] != "女":
        vals["武"] -= 1
        vals["体"] -= 1
    # 特长、短处
    pool = list(idn["tags"])
    rng.shuffle(pool)
    n = 1 + (rng.random() < 0.5)
    tags = pool[:n]
    if rng.random() < 0.3:
        # 表外的特长：读书一类（生成时加“学”的）只给识字的身份
        extra = [t for t in T.tags if t not in tags and t not in ("藏拙",)
                 and not ("学" in T.tags[t]["gen"] and idn["mean"]["学"] < 4)]
        if extra:
            tags.append(rng.choice(sorted(extra)))
    flaw = rng.choice(idn["flaws"]) if idn["flaws"] else rng.choice(sorted(T.flaws))
    # 提示词
    for h in hints:
        for row in T.hints:
            if any(w and w in h for w in row["words"]):
                for a, d in row["mods"].items():
                    if a in vals:
                        vals[a] += d
                if row.get("flaw"):
                    flaw = row["flaw"]
                if row.get("tag") and row["tag"] not in tags:
                    tags.append(row["tag"])
        for t in T.tags:
            if t in h and t not in tags:
                tags.append(t)
        for fl in T.flaws:
            if fl in h:
                flaw = fl
    for t in tags:
        for a, d in T.tags.get(t, {}).get("gen", {}).items():
            if a in vals:
                vals[a] += d
    for a, d in T.flaws.get(flaw, {}).get("gen", {}).items():
        if a in vals:
            vals[a] += d
    attrs = {a: clamp(int(round(vals[a]))) for a in ATTRS}
    # 意外
    surprise = None
    r = rng.random()
    if r < 0.05:
        cands = [a for a in ATTRS if idn["mean"][a] <= 5]
        a = rng.choice(cands)
        new = clamp(int(round(idn["mean"][a])) + rng.randint(4, 6))
        if new > attrs[a]:
            surprise = {"attr": a, "kind": "高", "was": attrs[a]}
            attrs[a] = new
    elif r < 0.08:
        cands = [a for a in ATTRS if idn["mean"][a] >= 6]
        if cands:
            a = rng.choice(cands)
            new = clamp(int(round(idn["mean"][a])) - 3)
            if new < attrs[a]:
                surprise = {"attr": a, "kind": "低", "was": attrs[a]}
                attrs[a] = new
    temper = pick_temper(T, attrs, rng)
    return {"identity": idn["name"], "age": age, "sex": sex, "hints": list(hints), "seed": key,
            "attrs": attrs, "tags": tags[:3], "flaw": flaw, "temper": temper, "surprise": surprise}


COND_RE = re.compile(r"^(\S)\s*([≥≤])\s*(\d+)$")


def pick_temper(T, attrs, rng):
    best, best_dev, other = None, -1, None
    for cond, phrases in T.tempers:
        m = COND_RE.match(cond)
        if not m:
            other = phrases
            continue
        a, op, n = m.group(1), m.group(2), int(m.group(3))
        v = attrs.get(a, 5)
        ok = v >= n if op == "≥" else v <= n
        if ok:
            dev = abs(v - 5.5)
            if dev > best_dev:
                best, best_dev = phrases, dev
    choice = best or other or ["寻常人"]
    return rng.choice(choice)


# ---------------------------------------------------------------- 人物：人格卡或名册

def cards_dir(world):
    d = os.path.join(os.path.dirname(os.path.abspath(world)), "characters")
    return d if os.path.isdir(d) else os.path.join(ROOT, "characters")


def read_yaml(text):
    m = L.YAML_RE.search(text)
    if not m:
        return None
    y = {}
    for line in m.group(1).splitlines():
        lm = L.LINE_RE.match(line)
        if lm:
            y[lm.group(2).strip()] = lm.group(3).strip()
    return y


def section(text, *names):
    for n in names:
        m = re.search(r"^## " + re.escape(n) + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        if m:
            body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip()
            if body:
                return body
    return ""


def parse_injury(s):
    """“重伤｜左肩｜余 2 季｜原为危” → dict；“无”→ None"""
    if not s or s.strip() in ("无", "—", "-", "（无）"):
        return None
    parts = [p.strip() for p in s.split("｜")]
    lv = parts[0]
    if lv not in INJURY_LEVELS:
        return {"level": lv, "where": "", "left": 0, "raw": s}
    where = parts[1] if len(parts) > 1 else ""
    m = re.search(r"余\s*(\d+)\s*季", s)
    left = int(m.group(1)) if m else 1
    w = re.search(r"原为(\S+?)(?:｜|$)", s)
    worst = w.group(1) if w and w.group(1) in INJURY_LEVELS else lv
    return {"level": lv, "where": where, "left": left, "worst": worst}


def fmt_injury(inj):
    if not inj:
        return "无"
    s = f"{inj['level']}｜{inj.get('where') or '身上'}｜余 {inj.get('left', 1)} 季"
    if inj.get("worst") and inj["worst"] != inj["level"]:
        s += f"｜原为{inj['worst']}"
    return s


class Person:
    """一个有属性的人。source：card（人格卡）或 roster（名册）。"""

    def __init__(self):
        self.name = ""
        self.source = ""
        self.path = None
        self.entry = None
        self.attrs = {}
        self.tags, self.flaws = [], []
        self.temper = ""
        self.injury = None
        self.know = 0
        self.rumor = None
        self.identity = ""
        self.age = None
        self.sex = ""
        self.role = ""
        self.text = ""
        self.surprise = None
        self.hints = []
        self.generated = False   # 属性是临时补的（旧卡或名册里没有 persona）

    @property
    def is_protagonist(self):
        return self.role == "主角"

    def label(self):
        return f"{self.name}（{self.identity or self.role}）"

    def all_marks(self, T):
        """特长和短处在较量里的加成、标记。"""
        out = []
        for t in self.tags:
            if t in T.tags:
                out.append(T.tags[t])
        for f in self.flaws:
            if f in T.flaws:
                out.append(T.flaws[f])
        return out

    def flags(self, T):
        fs = set()
        for x in self.all_marks(T):
            fs.update(x["flags"])
        return fs

    def disguise(self, T):
        if "藏拙" in self.flags(T):
            return 1
        return 1 if any(w in (self.temper or "") for w in ("深沉", "不露", "藏拙")) else 0


class World:
    def __init__(self, path):
        self.dir = os.path.abspath(path)
        self.T = Tables(self.dir)
        self._roster = None
        self._cards = None

    def p(self, name):
        return os.path.join(self.dir, name)

    def kingdom(self):
        try:
            with open(self.p("kingdom.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def when(self):
        k = self.kingdom()
        return f"{k.get('date', '')}（第 {k.get('turn', '?')} 回合）"

    @property
    def roster(self):
        if self._roster is None:
            try:
                with open(self.p("people.json"), encoding="utf-8") as f:
                    self._roster = json.load(f)
            except FileNotFoundError:
                self._roster = {"people": []}
            except ValueError as e:
                die(f"{self.p('people.json')} 不是合法的 JSON：{e}")
            self._roster.setdefault("people", [])
        return self._roster

    def save_roster(self):
        with open(self.p("people.json"), "w", encoding="utf-8") as f:
            json.dump(self.roster, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def roster_entry(self, name):
        return next((x for x in self.roster["people"] if x.get("name") == name), None)

    def card_files(self):
        if self._cards is None:
            self._cards = {}
            for path in sorted(glob.glob(os.path.join(cards_dir(self.dir), "*.md"))):
                b = os.path.basename(path)
                if b.startswith("_") or b == "README.md":
                    continue
                with open(path, encoding="utf-8") as f:
                    y = read_yaml(f.read()) or {}
                if y.get("姓名"):
                    self._cards[y["姓名"]] = path
        return self._cards

    def resolve_card(self, rel):
        if not rel:
            return None
        if os.path.isabs(rel):
            return rel if os.path.exists(rel) else None
        for base in (os.path.dirname(self.dir), ROOT):
            c = os.path.join(base, rel)
            if os.path.exists(c):
                return c
        return None

    def find(self, name, quiet=False):
        path = self.card_files().get(name)
        if path:
            return self.load_card(path)
        e = self.roster_entry(name)
        if e:
            if e.get("card"):
                cp = self.resolve_card(e["card"])
                if cp:
                    return self.load_card(cp)
            return self.load_roster(e)
        if quiet:
            return None
        die(f"找不到“{name}”：人格卡（{cards_dir(self.dir)}）和名册（{self.p('people.json')}）里都没有。"
            f"新人先用 persona.py gen {name} --role 身份 --apply")

    def protagonist(self):
        for name, path in self.card_files().items():
            with open(path, encoding="utf-8") as f:
                y = read_yaml(f.read()) or {}
            if y.get("身份") == "主角":
                return self.load_card(path)
        sc = S.load(self.dir)
        c = self.resolve_card(sc.get("player", {}).get("card"))
        if c:
            return self.load_card(c)
        die("找不到主角卡（身份: 主角）")

    def load_card(self, path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        y = read_yaml(text)
        if y is None:
            die(f"{path} 里没有 ```yaml 数值块")
        p = Person()
        p.source, p.path = "card", path
        p.text = " ".join(section(text, n) for n in ("天性", "性情", "性格"))   # 自动选打法时认关键词用
        p.name = y.get("姓名") or os.path.splitext(os.path.basename(path))[0]
        p.role = y.get("身份", "将领")
        p.identity = y.get("出身身份") or {"将领": "将领", "君主": "君主", "主角": "君主"}.get(p.role, "")
        if not p.identity and p.role == "家人":
            rel = re.search(r"^- 与主角：\s*(\S+)", text, re.M)
            p.identity = "世家女" if rel and rel.group(1)[:1] in "母妻妾妹姊女" else "贵家子弟"
        missing = []
        for a in ATTRS:
            v = y.get(a)
            try:
                p.attrs[a] = clamp(int(v))
            except (TypeError, ValueError):
                missing.append(a)
        p.tags = split_list(y.get("特长", ""))
        p.flaws = split_list(y.get("短处", ""))
        p.temper = y.get("性情") or first_line(section(text, "天性", "性情", "性格"))
        p.injury = parse_injury(y.get("伤势"))
        try:
            p.know = max(0, min(3, int(y.get("识人", 0))))
        except ValueError:
            p.know = 0
        if y.get("识人传闻"):
            mods, _, _ = parse_mods(y["识人传闻"])
            if mods:
                a, d = next(iter(mods.items()))
                p.rumor = {"attr": a, "off": int(d)}
        if missing:
            g = generate(self.T, scenario_id(self.dir), p.name, p.identity or "将领")
            for a in missing:
                p.attrs[a] = g["attrs"][a]
            p.generated = missing
            if not p.tags:
                p.tags = g["tags"]
            if not p.flaws:
                p.flaws = [g["flaw"]]
        return p

    def load_roster(self, e):
        p = Person()
        p.source, p.entry = "roster", e
        p.name = e["name"]
        p.role = "名册"
        per = e.get("persona")
        if not per:
            per = generate(self.T, scenario_id(self.dir), e["name"], e.get("role", ""))
            p.generated = ATTRS
        p.identity = per["identity"]
        p.age, p.sex = per.get("age"), per.get("sex")
        p.attrs = {a: clamp(int(per["attrs"][a])) for a in ATTRS}
        p.tags = list(per.get("tags", []))
        p.flaws = [per["flaw"]] if per.get("flaw") else []
        p.flaws += [f for f in per.get("extra_flaws", []) if f not in p.flaws]
        p.temper = per.get("temper", "")
        p.surprise = per.get("surprise")
        hs = list(per.get("hints", []))
        tr = e.get("trait")
        if tr and tr not in hs and tr != "；".join(hs) and tr != per.get("temper"):
            hs.append(tr)
        p.hints = hs
        p.injury = e.get("injury")
        p.know = int(e.get("识人", 0))
        p.rumor = e.get("识人传闻")
        p.text = " ".join([p.temper, e.get("trait", "")])
        return p

    # --- 写回 ---
    def set_know(self, observer, target, level, rumor="keep", log=None):
        """记识人进度。观者是主角：写在对象的卡或名册条目上；否则写进 people.json 的 acquaintance。"""
        if observer.is_protagonist:
            if target.source == "card":
                fields = {"识人": level}
                if rumor != "keep":
                    fields["识人传闻"] = f"{rumor['attr']}{rumor['off']:+d}" if rumor else None
                set_card_fields(target.path, fields)
            else:
                target.entry["识人"] = level
                if rumor != "keep":
                    if rumor:
                        target.entry["识人传闻"] = rumor
                    else:
                        target.entry.pop("识人传闻", None)
                if log:
                    target.entry.setdefault("识人记录", []).append(log)
                return "roster"
            return "card"
        acq = self.roster.setdefault("acquaintance", {})
        acq.setdefault(observer.name, {})[target.name] = level
        return "roster"

    def know_level(self, observer, target):
        if observer.is_protagonist:
            return target.know
        return int(self.roster.get("acquaintance", {}).get(observer.name, {}).get(target.name, 0))


def first_line(s):
    for l in (s or "").splitlines():
        l = l.strip().lstrip("-").strip()
        if l and not l.startswith("（"):
            return l[:60]
    return ""


# ---------------------------------------------------------------- 改人格卡的数值块

def set_card_fields(path, fields):
    """改人格卡 ```yaml 块里的字段：有就改值（保留注释），没有就加在块尾；值为 None 的删掉。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = L.YAML_RE.search(text)
    if not m:
        die(f"{path} 里没有 ```yaml 数值块")
    lines = m.group(1).rstrip("\n").split("\n")
    done = set()
    out = []
    for line in lines:
        lm = L.LINE_RE.match(line)
        if lm and lm.group(2).strip() in fields:
            key = lm.group(2).strip()
            done.add(key)
            val = fields[key]
            if val is None:
                continue
            indent, k, old, comment = lm.group(1), lm.group(2), lm.group(3), lm.group(4) or ""
            new = str(val)
            if comment:
                lead = len(comment) - len(comment.lstrip())
                fill = max(L.dwidth(old) + lead - L.dwidth(new), 1)
                out.append(f"{indent}{k}: {new}{' ' * fill}{comment.lstrip()}")
            else:
                out.append(f"{indent}{k}: {new}")
        else:
            out.append(line)
    for key, val in fields.items():
        if key in done or val is None:
            continue
        note = ATTR_NOTE.get(key) or {"识人": KNOW_NOTE, "伤势": INJURY_NOTE}.get(key)
        line = f"{key}: {val}"
        if note:
            line = line + " " * max(19 - L.dwidth(line), 1) + "# " + note
        out.append(line)
    block = "\n".join(out) + "\n"
    text = text[:m.start(1)] + block + text[m.end(1):]
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def card_attr_fields(attrs, tags, flaws, temper, know=None, injury="无"):
    f = {a: attrs[a] for a in ATTRS}
    f["特长"] = "、".join(tags) if tags else "—"
    f["短处"] = "、".join(flaws) if flaws else "—"
    f["性情"] = (temper or "—").replace(":", "：").replace("#", "")
    if know is not None:
        f["识人"] = know
    if injury is not None:
        f["伤势"] = injury
    return f


# ---------------------------------------------------------------- 印象

def eye_of(T, p):
    e = p.attrs.get("智", 5)
    for x in p.all_marks(T):
        e += x["contest"].get("眼力", 0)
    return e


def perceive(W, observer, target, level):
    """主观看到的属性：{属性: 估值}，以及看走眼的说明。"""
    T = W.T
    eye = eye_of(T, observer)
    sd = [2.2, 1.3, 0.7, 0.3][level] * max(0.5, 1 - 0.15 * (eye - 5))
    rng = random.Random(seed_int(f"印象|{observer.name}|{target.name}|{level}"))
    idn = T.identity(target.identity, strict=False) if target.identity else None
    disg = target.disguise(T)
    seen, notes = {}, []
    for a in ATTRS:
        true = target.attrs[a]
        base = float(true)
        noticed = rng.random()
        if target.surprise and target.surprise.get("attr") == a:
            if level == 0 or (level == 1 and noticed < 0.5):
                base = idn["mean"][a] if idn else 5.5
                notes.append(f"{a}：意外（实 {true}），这一级看不出来，按身份的寻常样子看")
        if disg and level <= 1:
            base = base + (5.5 - base) * 0.5
        if target.rumor and level == 1 and target.rumor.get("attr") == a:
            base += target.rumor.get("off", 0)
            notes.append(f"{a}：打听来的传闻偏 {target.rumor.get('off', 0):+d}")
        v = clamp(int(round(base + rng.gauss(0, sd))))
        seen[a] = v
        if tier(v) != tier(true):
            notes.append(f"{a}：看成 {v}（实 {true}）")
    return seen, notes


def impression(W, observer, target, level=None, gm=False):
    T = W.T
    if level is None:
        level = W.know_level(observer, target)
    level = max(0, min(3, int(level)))
    seen, notes = perceive(W, observer, target, level)
    out = []
    if level == 0:
        bits = [T.looks[a][tier(seen[a])] for a in ("体", "胆", "魅") if a in T.looks]
        who = target.identity or ""
        age = f"，{age_word(target.age)}" if target.age else ""
        if who and target.source == "roster":
            out.append(f"看样子是个{who}{age}。")
        out.append("；".join(bits) + "。")
        hint = [h for h in target.hints if h]
        if hint:
            out.append("、".join(hint) + "。")
    elif level == 1:
        hi = max(ATTRS, key=lambda a: seen[a])
        lo = min(ATTRS, key=lambda a: seen[a])
        parts = []
        if seen[hi] >= 7:
            parts.append(T.desc[hi][tier(seen[hi])])
        if seen[lo] <= 3 and (len(parts) == 0 or seen[lo] <= 2):
            parts.append(("只是" if parts else "") + T.desc[lo][tier(seen[lo])])
        if not parts:
            out.append("听人说起，他样样都还平常，没什么出挑的地方。")
        else:
            out.append("听说他" + "，".join(parts) + "。")
        if target.hints:
            out.append("、".join(target.hints) + "。")
    else:
        good = sorted([a for a in ATTRS if seen[a] >= 7], key=lambda a: -seen[a])[:4]
        bad = sorted([a for a in ATTRS if seen[a] <= (4 if level == 3 else 3)], key=lambda a: seen[a])[:3]
        s = "，".join(T.desc[a][tier(seen[a])] for a in good) if good else "没什么特别出挑的地方"
        if bad:
            s += "；只是" + "，".join(T.desc[a][tier(seen[a])] for a in bad)
        out.append(s + "。")
        if target.tags:
            out.append("、".join(target.tags) + "，是他的本事。")
        fl = [f for f in target.flaws if f and f != "—"]
        if fl:
            out.append("毛病是" + "、".join(fl) + "。")
        if level == 3:
            cmp_ = comparisons(W, observer, target, seen)
            if cmp_:
                out.append("；".join(cmp_) + "。")
            if target.surprise and target.identity:
                a = target.surprise["attr"]
                out.append(f"别看他是个{target.identity}，{T.desc[a][tier(target.attrs[a])]}。")
    if target.injury:
        inj = target.injury
        out.append(f"眼下{inj.get('where') or '身上'}带着{inj['level']}。")
    text = "".join(out)
    head = f"【{KNOW_NAMES[level]}】"
    if gm:
        nums = "  ".join(f"{a}{target.attrs[a]}" + (f"(看成{seen[a]})" if seen[a] != target.attrs[a] else "") for a in ATTRS)
        return head + text + "\n    [GM] " + nums + ("\n    [GM] 看走眼：" + "；".join(notes) if notes else "")
    return head + text


def age_word(age):
    if age < 15:
        return "还是个孩子"
    if age < 20:
        return "十几岁"
    d = min(age // 10, 9)
    return f"{'二三四五六七八九'[d - 2]}十来岁"


def comparisons(W, observer, target, seen):
    """知根知底时，拿观者熟知的人作比：比他最拿得出手的两项，先找带兵的、当家的人作比。"""
    refs = []
    for name in list(W.card_files()) + [e["name"] for e in W.roster["people"] if e.get("persona")]:
        if name in (target.name, observer.name):
            continue
        q = W.find(name, quiet=True)
        if not q or q.generated:
            continue
        if W.know_level(observer, q) >= 2:
            refs.append(q)
    if not refs:
        return []
    out = []
    top = [a for a in sorted(ATTRS, key=lambda a: -target.attrs[a])[:2] if target.attrs[a] >= 6]
    for a in top:
        ref = min(refs, key=lambda q: (0 if q.role in ("将领", "君主", "主角") else 1,
                                      abs(q.attrs[a] - target.attrs[a]), q.name))
        d = target.attrs[a] - ref.attrs[a]
        noun = ATTR_NOUN[a]
        if d >= 2:
            out.append(f"他的{noun}远在{ref.name}之上")
        elif d == 1:
            out.append(f"他的{noun}略胜{ref.name}一筹")
        elif d == 0:
            out.append(f"他的{noun}和{ref.name}相当")
        elif d == -1:
            out.append(f"他的{noun}约在{ref.name}之下")
        else:
            out.append(f"他的{noun}远不如{ref.name}")
    return out


# ---------------------------------------------------------------- 命令

def fmt_attrs(attrs):
    return "  ".join(f"{a} {attrs[a]}" for a in ATTRS)


def print_person(W, p, observer=None):
    src = {"card": f"人格卡 {rel(p.path)}", "roster": "名册 people.json"}.get(p.source, p.source)
    extra = []
    if p.age:
        extra.append(f"{p.age} 岁")
    if p.sex:
        extra.append(p.sex)
    print(f"=== {p.name}（{p.identity or p.role}{('，' + '，'.join(extra)) if extra else ''}）｜{src} ===")
    print(f"  {fmt_attrs(p.attrs)}")
    print(f"  特长：{'、'.join(p.tags) or '—'}    短处：{'、'.join(p.flaws) or '—'}")
    print(f"  性情：{p.temper or '—'}")
    if p.surprise:
        s = p.surprise
        print(f"  意外：{s['attr']} {p.attrs[s['attr']]}（{'远超' if s['kind'] == '高' else '远低于'}身份，原本该是 {s.get('was')} 上下）")
    print(f"  伤势：{fmt_injury(p.injury)}")
    if not p.is_protagonist:
        print(f"  识人（主角对他）：{p.know} {KNOW_NAMES[p.know]}" + (f"；传闻偏差 {p.rumor}" if p.rumor else ""))
    if p.generated:
        print(f"  注意：{'、'.join(p.generated)} 是按身份临时补的，还没写进{'卡' if p.source == 'card' else '名册'}"
              f"（{'persona.py fill' if p.source == 'card' else 'persona.py gen'} … --apply）")


def rel(path):
    if not path:
        return ""
    ap = os.path.abspath(path)
    return os.path.relpath(ap, ROOT) if ap.startswith(ROOT + os.sep) else path


def cmd_gen(W, args):
    sid = scenario_id(W.dir)
    e = W.roster_entry(args.name)
    if args.name in W.card_files():
        die(f"{args.name} 已有人格卡（{rel(W.card_files()[args.name])}），属性在卡上；用 show 看")
    if e and e.get("persona"):
        per = e["persona"]
        print(f"（名册里已有 {args.name}，属性不重掷。）")
        if args.role and W.T.identity(args.role)["name"] != per["identity"]:
            print(f"注意：这次给的身份“{args.role}”和名册里的“{per['identity']}”不同；身份变了（升了队正之类）照旧用名册的属性，要改就手改 people.json")
    else:
        if not args.role:
            die("新人要给 --role 身份")
        per = generate(W.T, sid, args.name, args.role, args.age, args.sex, args.hint or [])
        if not e:
            e = {"name": args.name, "role": args.role, "where": args.where or "", "trait": args.trait or "；".join(args.hint or []) or per["temper"],
                 "status": "在", "appearances": [], "card": None}
            W.roster["people"].append(e)
            print(f"新人：{args.name}，记进名册。")
        else:
            print(f"名册里已有 {args.name}，补上属性。")
        e["persona"] = per
        e.setdefault("识人", 0)
        e.setdefault("识人记录", [])
        e.setdefault("injury", None)
    if args.where:
        e["where"] = args.where
    if args.trait:
        e["trait"] = args.trait
    if args.event:
        e.setdefault("appearances", []).append(f"{W.when()}：{args.event}")
    p = W.load_roster(e)
    print_person(W, p)
    print(f"  种子：{per['seed']}")
    obs = W.protagonist()
    print("  " + impression(W, obs, p, 0))
    if args.json:
        print(json.dumps(e, ensure_ascii=False, indent=2))
    if args.apply:
        W.save_roster()
        print(f"已写入 {W.p('people.json')}。")
    else:
        print("（未写名册。确认后加 --apply。）")


def cmd_show(W, args):
    p = W.find(args.name)
    if args.json:
        print(json.dumps({"name": p.name, "source": p.source, "attrs": p.attrs, "tags": p.tags, "flaws": p.flaws,
                          "temper": p.temper, "injury": p.injury, "识人": p.know, "identity": p.identity},
                         ensure_ascii=False, indent=2))
        return
    print_person(W, p)


def cmd_impress(W, args):
    target = W.find(args.name)
    obs = W.find(args.by) if args.by else W.protagonist()
    lv = args.level if args.level is not None else W.know_level(obs, target)
    print(f"{obs.name} 眼里的 {target.name}（识人 {lv}，眼力 {eye_of(W.T, obs)}）：")
    print("  " + impression(W, obs, target, lv, gm=args.gm))


def cmd_know(W, args):
    target = W.find(args.name)
    obs = W.find(args.by) if args.by else W.protagonist()
    cur = W.know_level(obs, target)
    rumor = "keep"
    if args.set is not None:
        new = max(0, min(3, args.set))
        how = "GM 校正"
        if new >= 2:
            rumor = None
    else:
        if args.how not in HOW:
            die(f"--how 只有 {'、'.join(HOW)}")
        how = args.how
        inc, cap = HOW[how]
        if how == "共事" and args.long:
            cap = 3
        if how == "打听":
            new = max(cur, 1)
            if cur < 1:
                rng = random.Random(seed_int(f"打听|{obs.name}|{target.name}"))
                a = rng.choice(ATTRS)
                rumor = {"attr": a, "off": rng.choice([-2, 2])}
        else:
            new = min(cap, cur + inc) if cur < cap else cur
        if new >= 2 and target.rumor:
            rumor = None
    when = W.when()
    log = f"{when}：{how}，{cur} → {new}" + (f"（{args.note}）" if args.note else "")
    print(f"{obs.name} 对 {target.name}：{KNOW_NAMES[cur]}（{cur}） → {KNOW_NAMES[new]}（{new}），因为{how}"
          + (f"；{args.note}" if args.note else ""))
    if rumor not in ("keep", None):
        print(f"  打听来的有一项是传闻：{rumor['attr']} 偏 {rumor['off']:+d}（略知时照传闻说，熟知以后才纠正）")
    if rumor is None and target.rumor:
        print("  早先打听来的传闻，这下纠正过来了。")
    if new == cur and how not in ("见面", "GM 校正"):
        print(f"  已到“{how}”能到的上限，不再涨。")
    if args.apply:
        where = W.set_know(obs, target, new, rumor, log)
        if where == "roster":
            W.save_roster()
            print(f"已写入 {W.p('people.json')}。")
        else:
            print(f"已写入 {rel(target.path)}。")
        target.know = new if obs.is_protagonist else target.know
        if rumor != "keep":
            target.rumor = rumor
    else:
        print("（未写入。确认后加 --apply。）")
    target2 = W.find(args.name) if args.apply else target
    if not args.apply and obs.is_protagonist:
        target2.know = new
        if rumor != "keep":
            target2.rumor = rumor
    print("  新的印象：" + impression(W, obs, target2, new))


def cmd_promote(W, args):
    e = W.roster_entry(args.name)
    if not e:
        die(f"名册里没有“{args.name}”")
    if e.get("card") and W.resolve_card(e["card"]):
        die(f"{args.name} 已经有人格卡：{e['card']}")
    p = W.load_roster(e)
    kind = args.kind
    if kind not in ("将领", "家人", "君主"):
        die("--kind 只有 将领、家人、君主")
    path = args.card if os.path.isabs(args.card) else os.path.join(os.path.dirname(W.dir), args.card)
    if os.path.exists(path):
        die(f"{path} 已存在")
    text = build_card(W, p, kind, e)
    print(text)
    if args.apply:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        L.Card(path)  # 校验能被 loyalty.py 读
        e["card"] = args.card
        W.save_roster()
        print(f"已写入 {path}，名册里 {args.name} 的 card 改为 {args.card}。需求、天性、说话方式请 GM 当场按 rules/loyalty.md 填。")
    else:
        print("（未写卡。确认后加 --apply。）")


def build_card(W, p, kind, e):
    f = card_attr_fields(p.attrs, p.tags, p.flaws, p.temper, p.know, fmt_injury(p.injury))
    lines = [f"姓名: {p.name}", f"身份: {kind}"]
    lines.append(f"出身身份: {p.identity}")
    for k, v in f.items():
        note = ATTR_NOTE.get(k) or {"识人": KNOW_NOTE, "伤势": INJURY_NOTE}.get(k)
        line = f"{k}: {v}"
        lines.append(line + (" " * max(19 - L.dwidth(line), 1) + "# " + note if note else ""))
    if kind == "将领":
        lines += ["部曲: 10             # 从小人物长起来的，部曲从 10 以下起", "门槛: 3", "名节: 投胡3 投藩镇1 自立1 归朝廷0",
                  "急进: 1", "持重: 1", "家眷: 主公手里", "名分: 2", "离心: 安分"]
    elif kind == "君主":
        lines += ["部曲: 30"]
    else:
        lines += ["亲疏: 亲近"]
    mem = [f"- {a}" for a in e.get("appearances", [])] or ["- "]
    if kind == "家人":
        ledger = ["### 需求", "", "- 待定｜权重 2｜满足 2｜GM 升格时按 rules/household.md 第二节填", "",
                  "### 心结", "", "- （无）", "", "### 牵扯", "", "- 无", "", "### 阶梯记录", "", "- 升格建卡：亲近"]
        tmpl = "_template_kin.md"
    else:
        ledger = ["### 需求", "", "- 待定｜权重 2｜满足 2｜GM 升格时按 rules/loyalty.md 第二节填", "",
                  "### 心结", "", "- （无）", ""]
        if kind == "将领":
            ledger += ["### 开价", "", "- 无", "", "### 阶梯记录", "", "- 升格建卡：安分"]
        tmpl = "_template.md"
    body = [f"# {p.name}", "",
            f"<!-- 人格卡（模板见 characters/{tmpl}）。由名册里的小人物升格（persona.py promote），属性照搬名册。 -->", "",
            "## 基本信息", "", f"- 身份：{kind}", "- 所属：", f"- 官职：（原是{p.identity}）",
            f"- 年纪：{p.age or ''}", f"- 驻地与兵马：{e.get('where', '')}", "",
            "## 数值", "", "```yaml"] + lines + ["```", "",
            "## 出身", "", f"{p.identity}。{e.get('trait', '')}", "",
            "## 天性", "", f"- {p.temper}", "",
            "## 近况", "", f"（{W.when()} 升格）", "",
            "## 说话方式", "", "（待 GM 补）", "",
            "## 人心账本", "", "<!-- 由 scripts/loyalty.py 读写，规则见 rules/loyalty.md。 -->", ""] + ledger + ["",
            "## 与主公的关系史", "", "（待 GM 补）", "",
            "## 记忆", ""] + mem + [""]
    return "\n".join(body)


def cmd_hero(W, args):
    path = args.card if os.path.isabs(args.card) else (W.resolve_card(args.card) or os.path.join(ROOT, args.card))
    p = W.load_card(path)
    if p.generated:
        die(f"{rel(path)} 缺属性（{'、'.join(p.generated)}）：主角卡要先有剧本的默认属性，再按出身调整")
    base = dict(p.attrs)
    mods, tags, why = {}, [], []
    sc = S.load(W.dir)
    opt = None
    for rd in (sc.get("newgame") or {}).get("rounds", []):
        for q in rd.get("questions", []):
            if q.get("key") == "origin":
                opt = next((o for o in q.get("options", []) if o.get("label") == args.origin), None)
    eff = (opt or {}).get("effect", {})
    if eff.get("attrs"):
        for a, d in eff["attrs"].items():
            mods[a] = mods.get(a, 0) + d
        tags += eff.get("tags", [])
        why.append(f"出身“{args.origin}”（剧本选项）：" + " ".join(f"{a}{d:+d}" for a, d in eff["attrs"].items()))
    else:
        row = next((o for o in W.T.origins if o["key"] in args.origin), None)
        if row:
            for a, d in list(row["up"].items()) + list(row["down"].items()):
                mods[a] = mods.get(a, 0) + int(d)
            tags += row["tags"]
            why.append(f"出身“{args.origin}”（关键词 {row['key']}）：" + " ".join(f"{a}{int(d):+d}" for a, d in {**row['up'], **row['down']}.items()))
        else:
            why.append(f"出身“{args.origin}”：表里没有对得上的关键词，不调整")
    for t in args.temper or []:
        tm = W.T.temper_mods.get(t)
        if tm:
            for a, d in tm.items():
                mods[a] = mods.get(a, 0) + int(d)
            why.append(f"性格“{t}”：" + " ".join(f"{a}{int(d):+d}" for a, d in tm.items()))
    if args.age:
        if args.age < 30:
            mods["体"] = mods.get("体", 0) + 1
            mods["学"] = mods.get("学", 0) - 1
            why.append("三十岁以下：体+1 学−1")
        elif args.age >= 50:
            mods["体"] = mods.get("体", 0) - 1
            mods["学"] = mods.get("学", 0) + 1
            why.append("五十岁以上：体−1 学+1")
    new = {a: base[a] + mods.get(a, 0) for a in ATTRS}
    new["统"] = max(base["统"] - 1, min(base["统"] + 1, new["统"]))
    new = {a: clamp(v) for a, v in new.items()}
    total0 = sum(base.values())
    ups = [a for a, d in sorted(mods.items(), key=lambda x: -x[1]) if d > 0 and a in ATTRS]
    guard = 0
    while sum(new.values()) > total0 and guard < 50:
        guard += 1
        a = max((x for x in ATTRS if new[x] > 1 and x != "统"), key=lambda x: (new[x] - base[x], new[x]))
        new[a] -= 1
    while sum(new.values()) < total0 and guard < 100:
        guard += 1
        cands = [x for x in (ups or ATTRS) if new[x] < 10 and x != "统"] or [x for x in ATTRS if new[x] < 10 and x != "统"]
        a = min(cands, key=lambda x: (new[x] - base[x], -new[x]))
        new[a] += 1
    alltags = list(p.tags)
    for t in tags:
        if t not in alltags and len(alltags) < 3:
            alltags.append(t)
    print(f"=== 主角属性：{p.name}（{rel(path)}） ===")
    for w in why:
        print(f"  {w}")
    print(f"  原来：{fmt_attrs(base)}（合计 {total0}）")
    print(f"  调整：{fmt_attrs(new)}（合计 {sum(new.values())}，统兵 {base['统']} → {new['统']}）")
    print(f"  特长：{'、'.join(alltags) or '—'}")
    if args.apply:
        f = {a: new[a] for a in ATTRS}
        f["特长"] = "、".join(alltags) if alltags else "—"
        set_card_fields(path, f)
        print(f"已写入 {rel(path)}。")
    else:
        print("（未写卡。确认后加 --apply。）")


def cmd_fill(W, args):
    path = args.card if os.path.isabs(args.card) else (W.resolve_card(args.card) or os.path.join(ROOT, args.card))
    p = W.load_card(path)
    if args.role:
        p.identity = W.T.identity(args.role)["name"]
        q = W.load_card(path)
        g = generate(W.T, scenario_id(W.dir), p.name, p.identity)
        for a in (q.generated or []):
            p.attrs[a] = g["attrs"][a]
    with open(path, encoding="utf-8") as f:
        y = read_yaml(f.read()) or {}
    fields = {}
    for a in ATTRS:
        if a not in y:
            fields[a] = p.attrs[a]
    if "特长" not in y:
        fields["特长"] = "、".join(p.tags) or "—"
    if "短处" not in y:
        fields["短处"] = "、".join(p.flaws) or "—"
    if "性情" not in y:
        fields["性情"] = (p.temper or "—").replace(":", "：").replace("#", "")
    if "识人" not in y and p.role != "主角":
        fields["识人"] = 1
    if "伤势" not in y:
        fields["伤势"] = "无"
    if not fields:
        print(f"{p.name} 的卡属性齐全，不用补。")
        return
    print(f"=== 补齐属性：{p.name}（{rel(path)}，按身份“{p.identity}”） ===")
    for k, v in fields.items():
        print(f"  {k}: {v}")
    if args.apply:
        set_card_fields(path, fields)
        print(f"已写入 {rel(path)}。补出来的数是按身份掷的，GM 可以再照人物设定手改。")
    else:
        print("（未写卡。确认后加 --apply。）")


def cmd_roles(W, args):
    print(f"身份表（rules/people.md 第三节{'，含剧本追加' if any(i['source'] == '剧本' for i in W.T.identities.values()) else ''}）：")
    for idn in W.T.identities.values():
        means = " ".join(f"{a}{idn['mean'][a]:g}" for a in ATTRS)
        print(f"  {idn['name']}{'〔剧本〕' if idn['source'] == '剧本' else ''}（{'、'.join(idn['aliases']) or '—'}；"
              f"{idn['age'][0]}-{idn['age'][1]} 岁{'，女' if idn['sex'] == '女' else ''}）  {means}")


def cmd_stats(W, args):
    sid = scenario_id(W.dir)
    roles = [args.role] if args.role else list(W.T.identities)
    total_n = total_sur = 0
    for r in roles:
        idn = W.T.identity(r)
        sums = {a: 0 for a in ATTRS}
        sur = {"高": 0, "低": 0}
        for i in range(args.n):
            g = generate(W.T, sid, f"抽样{i}", idn["name"])
            for a in ATTRS:
                sums[a] += g["attrs"][a]
            if g["surprise"]:
                sur[g["surprise"]["kind"]] += 1
        total_n += args.n
        total_sur += sur["高"] + sur["低"]
        print(f"{idn['name']}（{args.n} 人）  意外：远超 {sur['高']}，远低 {sur['低']}（{(sur['高'] + sur['低']) / args.n:.1%}）")
        print("   表：" + "  ".join(f"{a}{idn['mean'][a]:>4.1f}" for a in ATTRS))
        print("   实：" + "  ".join(f"{a}{sums[a] / args.n:>4.1f}" for a in ATTRS))
    if len(roles) > 1:
        print(f"合计 {total_n} 人，意外 {total_sur} 人（{total_sur / total_n:.1%}）")


def main():
    ap = argparse.ArgumentParser(description="人物属性、名册与识人（规则见 rules/people.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=os.path.join(ROOT, "world"))
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, fn):
        p = sp.add_parser(name, help=help_)
        p.add_argument("--world", default=argparse.SUPPRESS)
        p.set_defaults(fn=fn)
        return p

    p = add("gen", "生成一个人，记进名册", cmd_gen)
    p.add_argument("name")
    p.add_argument("--role", help="身份（身份表或别名）")
    p.add_argument("--age", type=int)
    p.add_argument("--sex", choices=("男", "女"))
    p.add_argument("--hint", action="append", help="GM 看到的特征，可重复")
    p.add_argument("--where")
    p.add_argument("--trait", help="名册里的一句特征（默认取提示词或性情）")
    p.add_argument("--event", help="这次出场做了什么")
    p.add_argument("--json", action="store_true")
    p.add_argument("--apply", action="store_true")
    p = add("show", "GM 看一个人的属性", cmd_show)
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p = add("impress", "按识人进度写印象", cmd_impress)
    p.add_argument("name")
    p.add_argument("--level", type=int, choices=range(0, 4))
    p.add_argument("--by", help="观者，默认主角")
    p.add_argument("--gm", action="store_true", help="标出实数和看走眼的地方")
    p = add("know", "记识人进度", cmd_know)
    p.add_argument("name")
    p.add_argument("--how", default="见面")
    p.add_argument("--long", action="store_true", help="共事已满四季（可到知根知底）")
    p.add_argument("--by")
    p.add_argument("--set", type=int)
    p.add_argument("--note")
    p.add_argument("--apply", action="store_true")
    p = add("promote", "名册里的人升格成人格卡", cmd_promote)
    p.add_argument("name")
    p.add_argument("--card", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--apply", action="store_true")
    p = add("hero", "按出身、性格、年纪调整主角属性", cmd_hero)
    p.add_argument("card")
    p.add_argument("--origin", required=True)
    p.add_argument("--temper", action="append")
    p.add_argument("--age", type=int)
    p.add_argument("--apply", action="store_true")
    p = add("fill", "旧卡缺属性时按身份补齐", cmd_fill)
    p.add_argument("card")
    p.add_argument("--role")
    p.add_argument("--apply", action="store_true")
    add("roles", "列出身份表", cmd_roles)
    p = add("stats", "抽样检查身份表", cmd_stats)
    p.add_argument("--role")
    p.add_argument("--n", type=int, default=200)
    args = ap.parse_args()
    W = World(args.world)
    args.fn(W, args)


if __name__ == "__main__":
    main()
