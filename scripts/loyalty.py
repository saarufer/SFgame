#!/usr/bin/env python3
"""人心账本：需求、心结、开价、出走的算盘、离心阶梯，以及日常小波动的骰子。

规则见 rules/loyalty.md。人格卡格式见 characters/_template.md。
所有会改卡片的命令，默认只打印结果；加 --apply 才写回。

  查看     show    卡片 [--public]
  需求     need    卡片 需求名 满足度 [--weight N] [--why 依据]
  心结     grudge  卡片 --when 时间 --what 事由 --strength 1-3 [--heard 外传] [--toward 某人]
           （--toward：心结针对某个具体的人，同时在关系网里记一笔怨，见 rules/relations.md）
  消解     ease    卡片 编号 --by 抵消|补偿|道歉|淡忘|加深|不计 [--note 说明]
  开价     offer   卡片 --from 谁 --dest 去处 --give 需求=满足,... [--pursuit 0-3] [--extract] [--when] [--terms]
           offer   卡片 --withdraw
  算盘     reckon  卡片 [开价参数，试算，不存]
  季末     season  卡片 --when 时间 [--trigger 触发事件 ...] [开价参数]
  状态     state   卡片 [--level 级别] [--kin 家眷] [--standing 名分] --why 说明
  日常     roll    卡片 [--risky] [--seed N]
  部曲     corps   卡片 --delta N --why 说明

季末 season 会读 world/directives.json：卡片的主人若正受委任统领一个方面，部曲按委任时长、
方针权限自动上涨（规则见 rules/governance.md 第五节）。用 --world 指向别的存档目录做试验。

例（唐末朔方剧本）：
  python3 scripts/loyalty.py show characters/zhou-yansi.md
  python3 scripts/loyalty.py grudge characters/zhou-yansi.md --when 天复二年夏 \\
      --what 杜昶接管盐务，断我财路 --strength 2 --heard 幕僚可闻 --apply
  python3 scripts/loyalty.py season characters/zhou-yansi.md --when 天复二年冬 \\
      --from 李思谏 --dest 自立 --give 权柄=3,家眷平安=3,读书人被认可=1 --pursuit 2 --apply

去处四种是引擎的分类：投胡（投外族之主）、投藩镇（改投别的割据势力或权臣）、自立、归朝廷（归附名义上的中央）。
各剧本怎么称呼它们，写在 scenario.json 的 dest_labels 里，卡片上照旧写这四个词。
"""
import argparse
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEVELS = ["安分", "不满", "怨言", "留后路", "暗通", "举事"]
DESTS = ["投胡", "投藩镇", "自立", "归朝廷"]
KIN_RISK = {"随身": 0, "主公手里": 2, "对方手里": 0, "无": 0}
TRIGGERS = {
    "被夺兵权": "收回兵马、派人接替、监军带兵入城夺他的城",
    "性命之危": "被拘审、将被问罪处死、刺客，或确知主公要杀他",
    "主公大败": "主公主力新败，治所危急，自身难保",
    "家眷受害": "家人因主公之过被囚、被杀",
    "接应已到": "对方兵马已到城下或约定的接应就在眼前",
}
EASE_MODES = ("抵消", "补偿", "道歉", "淡忘", "加深", "不计")
# 没有兵权的朝臣卡（rules/court.md 第七节）：账本只记需求、心结、牵扯，心迹（恭谨 → 怠慢 → 怨望 → 异志）由 court.py season 推进
# 使节（在京的外邦使者）、外臣（外邦的官）、僧道、布衣（不在官、不在宫的人：商人、老兵、闺秀、乐伎）也用朝臣卡
COURT_ROLES = ("文臣", "宫人", "皇子", "公主", "后妃", "外戚", "宗室", "宦官", "朝臣", "使节", "外臣", "僧道", "布衣")
# 心结的外传途径。“家中可闻”用于家人：仆妇、乳母、管家会说起，玩家经家里人听到（rules/household.md）
HEARD = ("幕僚可闻", "细作可探", "家中可闻", "不外传")

# 每一级：可观察的迹象（GM 经幕僚、斥候、细作透露给玩家）
SIGNS = {
    "安分": ["没有异样。回禀如常，领赏谢恩，办事上心。"],
    "不满": ["回禀比往日简短，少了几句客气话。",
             "领赏时谢得淡；问他有什么难处，答“没什么”。",
             "该他办的事照办，但不再多出主意。"],
    "怨言": ["酒后对旁人说主公偏心、赏罚不公，话会传到幕僚耳朵里。",
             "议事时当众顶一两句，或者冷着脸不说话。",
             "接到军令先讨价还价：要钱、要粮、要人。",
             "部下也跟着发牢骚。"],
    "留后路": ["有生面孔的商人、僧人、远客出入他的府邸。",
               "收了外人的礼没有报上来；问起来，说“打发走了”。",
               "把钱财往别处挪，或者打听把家眷搬去别处。",
               "对监军、对帅府派来的人格外客气，或者格外提防。"],
    "暗通": ["夜里有人出城，守门的说是他的家人或亲兵。",
             "亲兵换防、调班不合常例；城门、渡口换上他的心腹。",
             "敌方的人、俘虏被悄悄放走；遇敌不救，或者打得很松。",
             "斥候在敌境见到他的信使；对入觐、调防一再推托。"],
    "举事": ["关城门、杀监军、亲兵披甲上城；城头换旗。",
             "或者人连夜不见了，家眷、细软一并带走。"],
}

# 每一级：agent 行动的上限（写进 general agent 的 prompt）
CEILING = {
    "安分": "本季心无旁骛。可以按天性拖延、变通、超额执行；不和外人私下往来，敌方来使就上报或打发走。",
    "不满": "心里不痛快，办事不如以前上心。可以推诿、少出主意；不发牢骚到外面，不和外人私下往来。",
    "怨言": "可以对旁人发牢骚、当面顶撞、讨价还价，命令不合意可以拖延或打折扣；不私收敌礼，不回敌方的信。",
    "留后路": "可以收礼不答复、不揭发来使、私蓄钱财、给家眷安排去处；不许回信承诺任何事，不透露军情。",
    "暗通": "可以回信、讲条件、透露军情、放走敌方的人、遇敌不救；不许举兵、开城、出奔。",
    "举事": "时机合适可以举兵、开城、出奔。去不去、怎么做，按天性和眼前形势自己定。",
}


def die(msg):
    sys.exit(f"错误：{msg}")


def pad(s, width):
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)
    return s + " " * max(width - w, 0)


# ---------- 读卡 ----------

YAML_RE = re.compile(r"```yaml\n(.*?)```", re.S)
LINE_RE = re.compile(r"^(\s*)([^\s:#][^:#]*?)\s*:\s*([^#\n]*?)(\s*#.*)?$")
LEDGER_RE = re.compile(r"^## 人心账本[^\n]*\n(.*?)(?=^## |\Z)", re.S | re.M)
SUB_RE = re.compile(r"^### (\S+)[^\n]*\n(.*?)(?=^### |\Z)", re.S | re.M)


class Card:
    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding="utf-8") as f:
                self.text = f.read()
        except OSError as e:
            die(f"读不到人格卡 {path}：{e}")
        m = YAML_RE.search(self.text)
        if not m:
            die(f"{path} 里没有 ```yaml 数值块（模板见 characters/_template.md）")
        self.yaml = {}
        for line in m.group(1).splitlines():
            lm = LINE_RE.match(line)
            if lm:
                self.yaml[lm.group(2).strip()] = lm.group(3).strip()
        self.name = self.yaml.get("姓名") or os.path.splitext(os.path.basename(path))[0]
        self.role = self.yaml.get("身份", "将领")
        self.yaml_changes = {}
        self._parse_ledger()
        if self.role == "将领":
            self._parse_general_fields()

    # --- yaml 字段 ---
    def _int(self, key, lo, hi, default=None):
        v = self.yaml.get(key)
        if v is None:
            if default is None:
                die(f"{self.path} 的数值块缺少“{key}”")
            return default
        try:
            n = int(v)
        except ValueError:
            die(f"{self.path} 的“{key}”不是整数：{v!r}")
        if not lo <= n <= hi:
            die(f"{self.path} 的“{key}”应在 {lo}–{hi} 之间：{n}")
        return n

    def _parse_general_fields(self):
        self.threshold = self._int("门槛", 0, 9)
        self.zeal = self._int("急进", 0, 3, 0)
        self.caution = self._int("持重", 0, 3, 0)
        self.standing = self._int("名分", 0, 3)
        self.kin = self.yaml.get("家眷", "随身")
        if self.kin not in KIN_RISK:
            die(f"{self.path} 的“家眷”应为 {'/'.join(KIN_RISK)}：{self.kin!r}")
        lv = self.yaml.get("离心", "安分")
        if lv not in LEVELS:
            die(f"{self.path} 的“离心”应为 {'/'.join(LEVELS)}：{lv!r}")
        self.level = lv
        self.honor = {}
        for tok in self.yaml.get("名节", "").split():
            mm = re.match(r"^(\D+?)(\d+)$", tok)
            if not mm or mm.group(1) not in DESTS:
                die(f"{self.path} 的“名节”写法应为“投胡3 投藩镇1 自立1 归朝廷0”，看不懂：{tok!r}")
            self.honor[mm.group(1)] = int(mm.group(2))
        for d in DESTS:
            self.honor.setdefault(d, 0)

    def set_yaml(self, key, value):
        self.yaml[key] = str(value)
        self.yaml_changes[key] = str(value)

    # --- 账本 ---
    def _parse_ledger(self):
        lm = LEDGER_RE.search(self.text)
        if not lm:
            die(f"{self.path} 里没有“## 人心账本”一节（模板见 characters/_template.md）")
        self.needs, self.grudges, self.offer, self.log = [], [], None, []
        subs = {k: v for k, v in SUB_RE.findall(lm.group(1))}
        for line in self._items(subs.get("需求", "")):
            self.needs.append(self._parse_need(line))
        for line in self._items(subs.get("心结", "")):
            self.grudges.append(self._parse_grudge(line))
        offers = [l for l in self._items(subs.get("开价", "")) if l != "无"]
        if offers:
            self.offer = self._parse_offer(offers[-1])
        self.log = self._items(subs.get("阶梯记录", ""))
        # 家人卡（身份: 家人）没有开价，改记“牵扯”：外头的人对他的拉拢、离间（rules/household.md）
        self.ties = [l for l in self._items(subs.get("牵扯", "")) if l != "无"]
        if not self.needs:
            die(f"{self.path} 的“### 需求”下一条也没有")
        if self.role == "将领" and abs(sum(n["w"] for n in self.needs)) == 0:
            die(f"{self.path} 的需求权重合计为 0")

    @staticmethod
    def _items(block):
        block = re.sub(r"<!--.*?-->", "", block, flags=re.S)
        return [l.strip()[2:].strip() for l in block.splitlines()
                if l.strip().startswith("- ") and l.strip()[2:].strip() not in ("", "（无）")]

    def _parse_need(self, line):
        parts = [p.strip() for p in line.split("｜")]
        need = {"name": parts[0], "w": None, "m": None, "why": ""}
        rest = []
        for p in parts[1:]:
            if p.startswith("权重"):
                need["w"] = int(p[2:].strip())
            elif p.startswith("满足"):
                need["m"] = int(p[2:].strip())
            else:
                rest.append(p)
        need["why"] = "｜".join(rest)
        if need["w"] is None or need["m"] is None:
            die(f"{self.path} 的需求行缺权重或满足：{line}")
        if not (1 <= need["w"] <= 3 and 0 <= need["m"] <= 3):
            die(f"{self.path} 的需求行数字超出范围（权重 1–3，满足 0–3）：{line}")
        return need

    def _parse_grudge(self, line):
        mm = re.match(r"^\[(\d+)\]\s*(.*)$", line)
        if not mm:
            die(f"{self.path} 的心结行要以 [编号] 开头：{line}")
        parts = [p.strip() for p in mm.group(2).split("｜")]
        if len(parts) < 4:
            die(f"{self.path} 的心结行字段不够（时间｜事由｜强度｜状态）：{line}")
        g = {"id": int(mm.group(1)), "when": parts[0], "what": parts[1], "s": None,
             "status": None, "heard": "不外传", "age": 0, "apologized": False, "extra": []}
        for p in parts[2:]:
            if p.startswith("强度"):
                g["s"] = int(p[2:].strip())
            elif p.startswith("状态"):
                g["status"] = p.split("：", 1)[1].strip() if "：" in p else p[2:].strip()
            elif p.startswith("外传"):
                g["heard"] = p.split("：", 1)[1].strip() if "：" in p else p[2:].strip()
            elif p.startswith("已历"):
                g["age"] = int(re.sub(r"\D", "", p) or 0)
            elif p == "已致歉":
                g["apologized"] = True
            else:
                g["extra"].append(p)
        if g["s"] is None or g["status"] is None:
            die(f"{self.path} 的心结行缺强度或状态：{line}")
        return g

    def _parse_offer(self, line):
        o = {"from": "", "dest": "", "give": {}, "pursuit": 0, "extract": False, "when": "", "terms": ""}
        for p in [x.strip() for x in line.split("｜")]:
            if p.startswith("来自"):
                o["from"] = p[2:].strip()
            elif p.startswith("去处"):
                o["dest"] = p[2:].strip()
            elif p.startswith("所给"):
                o["give"] = parse_give(p[2:].strip())
            elif p.startswith("追杀"):
                o["pursuit"] = int(p[2:].strip())
            elif p.startswith("接家眷"):
                o["extract"] = p[3:].strip() == "是"
            elif p.startswith("时间"):
                o["when"] = p[2:].strip()
            elif p.startswith("条件"):
                o["terms"] = p[2:].strip()
        return o

    def active(self):
        return [g for g in self.grudges if g["status"] == "未解"]

    # --- 写回 ---
    def render_ledger(self):
        court = self.role in COURT_ROLES
        out = ["## 人心账本", "",
               ("<!-- 由 scripts/loyalty.py 和 scripts/court.py 读写，规则见 rules/court.md 第七节。每条占一行，字段用全角竖线“｜”分隔。 -->"
                if court else
                "<!-- 由 scripts/loyalty.py 读写，规则见 rules/loyalty.md。可以手改，但每条占一行，字段用全角竖线“｜”分隔。 -->"),
               "", "### 需求", "",
               ("<!-- 名称｜权重 1–3｜满足 0–3｜依据。家里的心愿，满足度由 GM 依存档和记忆评定（rules/household.md 第二节）。 -->"
                if self.role == "家人" else
                "<!-- 名称｜权重 1–3｜满足 0–3｜依据。朝臣写他想要的：相位、清名、所主张的事办成；皇子可以有“储位”。 -->"
                if court else
                "<!-- 名称｜权重 1–3｜满足 0–3｜依据。满足度由 GM 依存档和记忆评定。名称里带“家眷”的一项，算盘里按家眷处理。 -->")]
        out += [f"- {n['name']}｜权重 {n['w']}｜满足 {n['m']}" + (f"｜{n['why']}" if n["why"] else "") for n in self.needs]
        out += ["", "### 心结", "",
                "<!-- [编号] 时间｜事由｜强度 1–3｜状态：未解 / 已抵消（…）/ 已解（…）/ 已淡忘（…）/ 不计（…）｜外传：幕僚可闻 / 细作可探 / 家中可闻 / 不外传｜已历 N 季 -->"]
        if self.grudges:
            for g in self.grudges:
                fields = [f"[{g['id']}] {g['when']}", g["what"], f"强度 {g['s']}", f"状态：{g['status']}",
                          f"外传：{g['heard']}"]
                if g["status"] == "未解":
                    fields.append(f"已历 {g['age']} 季")
                if g["apologized"]:
                    fields.append("已致歉")
                fields += g["extra"]
                out.append("- " + "｜".join(fields))
        else:
            out.append("- （无）")
        if self.role == "将领":
            out += ["", "### 开价", "",
                    "<!-- 眼下仍然有效的外部开价，只记最新一条。没有就写“无”。 -->"]
            out.append("- " + (fmt_offer_line(self.offer) if self.offer else "无"))
            out += ["", "### 阶梯记录", ""]
            out += [f"- {l}" for l in self.log[-12:]]
        elif self.role == "家人" or self.role in COURT_ROLES:
            out += ["", "### 牵扯", "",
                    "<!-- 外头的人对他的拉拢、离间、许诺，一条一行：来自 谁｜所图 什么｜许以 什么｜时间。没有就写“无”。"
                    + ("由 scripts/household.py tie 读写。 -->" if self.role == "家人" else "朝臣卡的心迹由 scripts/court.py season 推进（rules/court.md 第七节）。 -->")]
            out += [f"- {t}" for t in self.ties] or ["- 无"]
            out += ["", "### 阶梯记录", ""]
            out += [f"- {l}" for l in self.log[-12:]]
        return "\n".join(out) + "\n\n"

    def save(self):
        text = self.text
        if self.yaml_changes:
            m = YAML_RE.search(text)

            def sub(line):
                lm = LINE_RE.match(line)
                if lm and lm.group(2).strip() in self.yaml_changes:
                    indent, key, val, comment = lm.group(1), lm.group(2), lm.group(3), lm.group(4) or ""
                    new_val = self.yaml_changes[key.strip()]
                    if not comment:
                        return f"{indent}{key}: {new_val}"
                    lead = len(comment) - len(comment.lstrip())
                    fill = max(dwidth(val) + lead - dwidth(new_val), 1)
                    return f"{indent}{key}: {new_val}{' ' * fill}{comment.lstrip()}"
                return line
            block = "\n".join(sub(l) for l in m.group(1).split("\n"))
            text = text[:m.start(1)] + block + text[m.end(1):]
        lm = LEDGER_RE.search(text)
        text = text[:lm.start()] + self.render_ledger() + text[lm.end():]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)


def dwidth(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def parse_give(s):
    give = {}
    for tok in re.split(r"[,，、]", s):
        tok = tok.strip()
        if not tok:
            continue
        if "=" not in tok:
            die(f"--give 的写法是 需求名=满足度（0–3），用逗号分隔：{tok!r}")
        k, v = tok.split("=", 1)
        try:
            n = int(v)
        except ValueError:
            die(f"--give 里“{k}”的满足度不是整数：{v!r}")
        if not 0 <= n <= 3:
            die(f"--give 里“{k}”的满足度应在 0–3：{n}")
        give[k.strip()] = n
    return give


def fmt_offer_line(o):
    give = ",".join(f"{k}={v}" for k, v in o["give"].items())
    parts = [f"来自 {o['from']}", f"去处 {o['dest']}", f"所给 {give}", f"追杀 {o['pursuit']}",
             f"接家眷 {'是' if o['extract'] else '否'}"]
    if o["when"]:
        parts.append(f"时间 {o['when']}")
    if o["terms"]:
        parts.append(f"条件 {o['terms']}")
    return "｜".join(parts)


# ---------- 计算 ----------

def is_kin(need):
    return "家眷" in need["name"]


def gap(card):
    return sum(n["w"] * (3 - n["m"]) for n in card.needs) / 3


def pressure(card):
    return sum(g["s"] for g in card.active())


def reckon(card, offer):
    """出走的算盘。返回 dict；offer 为 None 时 G 为 None。"""
    P = pressure(card)
    need_score = sum(n["w"] * n["m"] for n in card.needs)
    S = need_score + card.standing - P
    r = {"S": S, "need_score": need_score, "standing": card.standing, "P": P,
         "G": None, "moved": False, "notes": []}
    if offer is None:
        r["notes"].append("无人开价：出走的算盘不成立。")
        return r
    if offer["dest"] not in DESTS:
        die(f"去处应为 {'/'.join(DESTS)}：{offer['dest']!r}")
    names = [n["name"] for n in card.needs]
    unknown = [k for k in offer["give"] if k not in names]
    if unknown:
        die(f"开价里的需求“{'、'.join(unknown)}”不在 {card.name} 的需求表里（有：{'、'.join(names)}）")
    give_score, parts = 0, []
    kin_risk = KIN_RISK[card.kin]
    if card.kin == "主公手里" and offer["extract"]:
        kin_risk = 1
    for n in card.needs:
        o = offer["give"].get(n["name"])
        if o is None:
            o = 0
            r["notes"].append(f"开价没说到“{n['name']}”，按 0 计。")
        if is_kin(n) and card.kin == "主公手里" and not offer["extract"]:
            if o:
                r["notes"].append(f"家眷在主公手里、对方没许诺接出：“{n['name']}”按 0 计。")
            o = 0
        give_score += n["w"] * o
        parts.append(f"{n['name']}{o}×{n['w']}")
    honor = card.honor.get(offer["dest"], 0)
    corps_cut = corps_relief(card, offer["dest"])
    if corps_cut:
        r["notes"].append(f"部曲 {card_corps(card)}，兵认他，据地自立的风险 −{corps_cut}。")
    risk = max(kin_risk + offer["pursuit"] + honor - corps_cut, 0)
    G = give_score - risk
    r.update({"G": G, "give_score": give_score, "give_parts": parts, "risk": risk,
              "kin_risk": kin_risk, "pursuit": offer["pursuit"], "honor": honor, "corps_cut": corps_cut,
              "diff": G - S, "moved": G - S > card.threshold})
    return r


def card_corps(card):
    try:
        return max(0, min(100, int(card.yaml.get("部曲", 0))))
    except ValueError:
        die(f"{card.path} 的“部曲”不是整数：{card.yaml.get('部曲')!r}")


def corps_relief(card, dest):
    """部曲高的将领，去处为“自立”时风险下调（rules/governance.md 第五节）。"""
    if dest != "自立":
        return 0
    c = card_corps(card)
    return 2 if c >= 80 else 1 if c >= 60 else 0


def set_corps(card, value, why):
    """改部曲（0–100），记进阶梯记录。返回 (旧, 新)。"""
    old = card_corps(card)
    new = max(0, min(100, int(round(value))))
    if new != old:
        card.set_yaml("部曲", new)
        if card.role == "将领":
            card.log.append(f"部曲 {old} → {new}｜{why}")
    return old, new


def add_grudge(card, when, what, strength, heard="不外传"):
    gid = max([g["id"] for g in card.grudges] + [0]) + 1
    g = {"id": gid, "when": when, "what": what, "s": strength, "status": "未解",
         "heard": heard, "age": 0, "apologized": False, "extra": []}
    card.grudges.append(g)
    return g


POWER_NEEDS = ("权柄", "重用", "独当一面", "兵权", "被信任")


def shift_power_need(card, delta, why):
    """把“权柄”一类需求的满足度加减 delta（夹在 0–3）。返回改动说明列表。"""
    out = []
    for n in card.needs:
        if any(k in n["name"] for k in POWER_NEEDS):
            old = n["m"]
            n["m"] = max(0, min(3, n["m"] + delta))
            if n["m"] != old:
                n["why"] = why
                out.append(f"需求 {n['name']}：满足 {old} → {n['m']}（{why}）")
    return out


# ---------- 委任对部曲的影响（rules/governance.md 第五节） ----------

def find_command(card, world):
    """在 world/directives.json 里找这张卡的主人正统领的方面。返回 (方面名, 记录, 当前回合) 或 None。"""
    import json
    path = os.path.join(world, "directives.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    turn = 0
    kp = os.path.join(world, "kingdom.json")
    if os.path.exists(kp):
        with open(kp, encoding="utf-8") as f:
            turn = json.load(f).get("turn", 0)
    me = os.path.normpath(os.path.abspath(card.path))
    for name, c in d.get("commands", {}).items():
        cp = c.get("card")
        if not cp:
            continue
        cands = [cp] if os.path.isabs(cp) else [os.path.join(ROOT, cp), os.path.join(os.path.dirname(world), cp)]
        if any(os.path.normpath(os.path.abspath(x)) == me for x in cands) or c.get("holder") == card.name:
            return name, c, turn, d
    return None


CORPS_CAP = 90


def corps_drift(card, cmd, turn, directives):
    """委任中每季部曲的涨幅。返回 (涨幅, 说明列表)。"""
    seasons = max(turn - int(cmd.get("since_turn", turn)), 0) + 1   # 本季算在内
    d = cmd.get("directive", {})
    lat = d.get("latitude", {}).get("tier", "中")
    parts = [("委任中", 1)]
    if seasons > 4:
        parts.append((f"委任已历 {seasons} 季（满四季）", 1))
    if lat == "宽":
        parts.append(("钱粮权限宽", 1))
    if d.get("posture") == "攻":
        parts.append(("姿态为攻，兵随他打仗", 1))
    dev = directives.get("last_settlement", {}).get("deviation", {}).get(cmd.get("_name", ""))
    if dev == "变通" and directives.get("last_settlement", {}).get("turn") == turn:
        parts.append(("本季截留钱粮，自行犒军", 1))
    if cmd.get("far"):
        parts.append((f"离帅府远（{cmd['far']} 程）", 1))
    total = sum(v for _, v in parts)
    cur = card_corps(card)
    if cur + total > CORPS_CAP:
        total = max(CORPS_CAP - cur, 0)
    return total, seasons, [f"{k} +{v}" for k, v in parts]


def target_level(card, rk, triggers):
    """账面上该到哪一级（还没算“每季最多升一级”）。返回 (级别序号, 说明)。"""
    P = pressure(card)
    X = P + gap(card)
    base = 0 if X < 3 else 1 if X < 5 else 2 if X < 7 else 3
    why = [f"离心分 {X:.1f}（心结 {P} + 缺口 {gap(card):.1f}）→ {LEVELS[base]}"]
    cap = 1 if P == 0 else 2 if P < 3 else 3
    if base > cap:
        why.append(f"未解心结只有 {P}，最多到“{LEVELS[cap]}”")
        base = cap
    t = base
    if rk["moved"]:
        if P >= 3:
            t = 4
            why.append("有开价、动念、未解心结 ≥3 → 可到“暗通”")
        else:
            t = max(t, 3)
            why.append("动念，但未解心结不足 3 → 至多“留后路”")
    cur = LEVELS.index(card.level)
    if cur == 4 and rk["moved"] and triggers:
        t = 5
        why.append(f"上季已在暗通、算盘成立、有触发事件（{'、'.join(triggers)}）→ 可“举事”")
    elif triggers and cur != 4:
        why.append("有触发事件，但上季不在“暗通”，不能举事")
    elif triggers and not rk["moved"]:
        why.append("有触发事件，但出走的算盘不成立，不能举事")
    return t, why


def step(cur, target):
    if target > cur:
        return cur + 1
    if target < cur:
        return cur - 1
    return cur


def fade(card):
    """季末：未解心结已历 +1，按时间淡化。返回说明行。"""
    out = []
    for g in card.active():
        g["age"] += 1
        if g["s"] == 1 and g["age"] >= 4:
            g["status"] = "已淡忘（四季无人再提）"
            out.append(f"[{g['id']}] 强度 1，已历 4 季 → 已淡忘")
        elif g["s"] == 2 and g["age"] >= 8:
            g["s"], g["age"] = 1, 0
            out.append(f"[{g['id']}] 强度 2，已历 8 季 → 降为 1")
    return out


# ---------- 打印 ----------

def rel(path):
    ap = os.path.abspath(path)
    return os.path.relpath(ap, ROOT) if ap.startswith(ROOT + os.sep) else path


def print_ledger(card, public=False):
    print(f"=== 人心账本：{card.name}（{card.role}，{rel(card.path)}） ===")
    if card.role == "将领" and not public:
        print(f"  离心：{card.level}    家眷：{card.kin}    名分：{card.standing}    门槛：{card.threshold}    "
              f"名节：" + " ".join(f"{d}{card.honor[d]}" for d in DESTS))
    if not public:
        print("  需求：")
        for n in card.needs:
            print(f"    {pad(n['name'], 14)} 权重 {n['w']}  满足 {n['m']}   {n['why']}")
    print("  心结：" if not public else "  玩家可能听说的心结（经幕僚或细作）：")
    shown = 0
    for g in card.grudges:
        if public and (g["status"] != "未解" or g["heard"] == "不外传"):
            continue
        tag = f"已历 {g['age']} 季" if g["status"] == "未解" else ""
        print(f"    [{g['id']}] {g['when']}｜{g['what']}｜强度 {g['s']}｜{g['status']}｜外传：{g['heard']}  {tag}")
        shown += 1
    if not shown:
        print("    （无）")
    if card.role == "将领" and not public:
        print(f"  未解心结合计 {pressure(card)}；需求缺口 {gap(card):.1f}")
        print("  开价：" + (fmt_offer_line(card.offer) if card.offer else "无"))
        if card.log:
            print("  阶梯记录（近几季）：")
            for l in card.log[-6:]:
                print(f"    {l}")


def print_reckon(card, rk, offer):
    print("--- 出走的算盘 ---")
    print(f"  留下 = 需求 {rk['need_score']} + 名分 {rk['standing']} − 未解心结 {rk['P']} = {rk['S']}")
    if rk["G"] is None:
        for n in rk["notes"]:
            print(f"  {n}")
        return
    print(f"  开价：来自 {offer['from']}，去处 {offer['dest']}" + (f"，条件：{offer['terms']}" if offer["terms"] else ""))
    print(f"  出走 = 所给 {rk['give_score']}（{' + '.join(rk['give_parts'])}）"
          f" − 风险 {rk['risk']}（家眷 {rk['kin_risk']} + 追杀 {rk['pursuit']} + 名节 {rk['honor']}"
          + (f" − 部曲 {rk['corps_cut']}" if rk.get("corps_cut") else "") + f"）= {rk['G']}")
    verdict = "动念" if rk["moved"] else "不动念"
    print(f"  出走 − 留下 = {rk['diff']:+d}，性格门槛 {card.threshold} → 【{verdict}】")
    for n in rk["notes"]:
        print(f"  注：{n}")


def agent_hint(card, rk, new_level):
    if rk["G"] is None:
        calc = "无人开价，出走的算盘不成立"
    else:
        calc = (f"{'成立' if rk['moved'] else '不成立'}（留下 {rk['S']}，出走 {rk['G']}，门槛 {card.threshold}）")
    return f"离心级别：{new_level}。出走的算盘：{calc}。行动上限：{CEILING[new_level]}"


# ---------- 命令 ----------

def offer_from_args(args, card):
    if getattr(args, "withdraw", False):
        return "withdraw"
    if not getattr(args, "from_", None):
        return None
    if not args.dest or args.give is None:
        die("开价要同时给 --from、--dest、--give")
    return {"from": args.from_, "dest": args.dest, "give": parse_give(args.give),
            "pursuit": args.pursuit, "extract": args.extract,
            "when": args.when_offer or getattr(args, "when", None) or "",
            "terms": args.terms or ""}


def need_general(card, what):
    if card.role == "家人":
        die(f"{card.name} 的身份是家人：{what}只用于将领。家人的亲疏阶梯用 scripts/household.py season（rules/household.md）；"
            f"他若领了兵，把卡上的身份改成“将领”并补齐将领字段，再用本脚本。")
    if card.role in COURT_ROLES:
        die(f"{card.name} 的身份是{card.role}：{what}只用于将领。朝臣卡的心迹用 scripts/court.py season 推进，"
            f"朝中提示用 court.py hint（rules/court.md 第七节）。")
    if card.role != "将领":
        die(f"{card.name} 的身份是{card.role}：{what}只用于将领。君主的账本只记需求和心结，供 ruler agent 参考。")


def finish(card, apply):
    if apply:
        card.save()
        print(f"\n已写入 {rel(card.path)}。")
    else:
        print("\n（未写卡片。确认无误后加 --apply。）")


def cmd_show(card, args):
    print_ledger(card, public=args.public)
    if card.role == "将领" and not args.public:
        rk = reckon(card, card.offer)
        print()
        print_reckon(card, rk, card.offer)
        print()
        print("写进 general agent prompt 的人心提示：")
        print("  " + agent_hint(card, rk, card.level))
        print(f"\n本级可观察的迹象（GM 经幕僚、斥候透露）：")
        for s in SIGNS[card.level]:
            print(f"  · {s}")


def cmd_need(card, args):
    for n in card.needs:
        if n["name"] == args.need:
            break
    else:
        if args.weight is None:
            die(f"{card.name} 没有需求“{args.need}”。新加一项需要 --weight（有：{'、'.join(x['name'] for x in card.needs)}）")
        n = {"name": args.need, "w": args.weight, "m": 0, "why": ""}
        card.needs.append(n)
        print(f"新增需求：{args.need}（权重 {args.weight}）")
    if not 0 <= args.value <= 3:
        die("满足度应在 0–3")
    old = n["m"]
    n["m"] = args.value
    if args.weight is not None:
        if not 1 <= args.weight <= 3:
            die("权重应在 1–3")
        n["w"] = args.weight
    if args.why:
        n["why"] = args.why
    print(f"{card.name}｜{n['name']}：满足 {old} → {n['m']}（权重 {n['w']}）  {n['why']}")
    finish(card, args.apply)


# 心结的外传 → 关系网里这笔怨有谁知道（rules/relations.md 第三节）
HEARD_KNOWN = {"幕僚可闻": "公开", "家中可闻": "两人", "细作可探": "暗", "不外传": "暗"}


def toward_of(g):
    """心结若是针对某个具体的人，事由后面带一段“对 某人”。"""
    for x in g["extra"]:
        if x.startswith("对 "):
            return x[2:].strip()
    return None


def card_ref(card, g):
    return f"card:{rel(card.path)}#{g['id']}"


def relations_net(world):
    import json  # noqa: F401
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import relations as REL
    return REL.Net(world)


def cmd_grudge(card, args):
    if not 1 <= args.strength <= 3:
        die("强度应在 1–3")
    if args.heard not in HEARD:
        die("--heard 应为 " + " / ".join(HEARD))
    gid = max([g["id"] for g in card.grudges] + [0]) + 1
    g = {"id": gid, "when": args.when, "what": args.what, "s": args.strength, "status": "未解",
         "heard": args.heard, "age": 0, "apologized": False, "extra": []}
    if args.toward:
        g["extra"].append(f"对 {args.toward}")
    card.grudges.append(g)
    print(f"{card.name} 新添心结 [{gid}] {args.when}｜{args.what}｜强度 {args.strength}｜外传：{args.heard}"
          + (f"｜对 {args.toward}" if args.toward else ""))
    print(f"未解心结合计：{pressure(card) - args.strength} → {pressure(card)}")
    net = None
    if args.toward:
        net = relations_net(args.world)
        x = net.add_deed(card.name, args.toward, "怨", args.what, args.strength, args.when,
                         _turn(args.world), HEARD_KNOWN[args.heard], ref=card_ref(card, g))
        print(f"关系网：{card.name} 对 {args.toward} 记怨 {args.strength}（[{x['id']}]，{x['known']}），和这条心结相连")
    finish(card, args.apply)
    if args.apply and net is not None:
        print(f"已写入 {rel(net.save())}。")


def _turn(world):
    import json
    try:
        with open(os.path.join(world, "kingdom.json"), encoding="utf-8") as f:
            return json.load(f).get("turn", 0)
    except (OSError, ValueError):
        return 0


def cmd_ease(card, args):
    g = next((x for x in card.grudges if x["id"] == args.id), None)
    if not g:
        die(f"{card.name} 没有编号 [{args.id}] 的心结")
    if g["status"] != "未解" and args.by != "加深":
        die(f"[{g['id']}] 已经是“{g['status']}”，无需再消解")
    before = f"强度 {g['s']}｜{g['status']}"
    note = args.note or ""
    if args.by in ("抵消", "淡忘", "不计"):
        if not note:
            die(f"--by {args.by} 要用 --note 写明缘由（例如“某年冬总管盐铁”）")
        g["status"] = f"{'已抵消' if args.by == '抵消' else '已淡忘' if args.by == '淡忘' else '不计'}（{note}）"
    elif args.by in ("补偿", "道歉"):
        if args.by == "道歉":
            if g["apologized"]:
                die(f"[{g['id']}] 已经道过歉。同一条心结，道歉只算一次")
            g["apologized"] = True
        g["s"] -= 1
        if g["s"] <= 0:
            g["s"] = 0
            g["status"] = f"已解（{note or args.by}）"
    elif args.by == "加深":
        if g["status"] != "未解":
            g["status"] = "未解"
        g["s"] = min(g["s"] + 1, 3)
        g["age"] = 0
    print(f"{card.name} 心结 [{g['id']}] {g['what']}：{before} → 强度 {g['s']}｜{g['status']}"
          + (f"   （{args.by}：{note}）" if note else f"   （{args.by}）"))
    print(f"未解心结合计：{pressure(card)}")
    net = None
    if toward_of(g):
        net = relations_net(args.world)
        ref = card_ref(card, g)
        x = next((d for d in net.d["deeds"] if d.get("ref") == ref), None)
        if x:
            x["s"] = g["s"]
            if g["status"] != "未解":
                x["status"] = g["status"].replace("已抵消", "已抵偿")
            elif x["status"] != "未了":
                x["status"] = "未了"
            x["age"] = g["age"]
            print(f"关系网：{card.name} 对 {toward_of(g)} 的怨 [{x['id']}] 同步为 强度 {x['s']}｜{x['status']}")
        else:
            net = None
    finish(card, args.apply)
    if args.apply and net is not None:
        print(f"已写入 {rel(net.save())}。")


def cmd_offer(card, args):
    need_general(card, "开价")
    o = offer_from_args(args, card)
    if o is None:
        die("给出 --from/--dest/--give，或 --withdraw")
    if o == "withdraw":
        print(f"{card.name} 的开价撤销（原：{fmt_offer_line(card.offer) if card.offer else '无'}）")
        card.offer = None
    else:
        reckon(card, o)  # 校验需求名
        card.offer = o
        print(f"{card.name} 记下开价：{fmt_offer_line(o)}")
    finish(card, args.apply)


def cmd_reckon(card, args):
    need_general(card, "出走的算盘")
    o = offer_from_args(args, card)
    if o == "withdraw":
        o = None
    elif o is None:
        o = card.offer
    print(f"=== 出走的算盘（试算，不写卡）：{card.name} ===")
    print_reckon(card, reckon(card, o), o)


def cmd_season(card, args):
    need_general(card, "季末推进")
    for t in args.trigger:
        if t not in TRIGGERS:
            die(f"触发事件“{t}”不在表里。可用：{'、'.join(TRIGGERS)}")
    o = offer_from_args(args, card)
    if o == "withdraw":
        card.offer = None
    elif o is not None:
        card.offer = o
    rk = reckon(card, card.offer)
    print(f"=== 季末人心：{card.name}（{args.when}） ===")
    for n in card.needs:
        print(f"  需求 {pad(n['name'], 14)} 权重 {n['w']}  满足 {n['m']}")
    for g in card.active():
        print(f"  心结 [{g['id']}] {g['what']}（强度 {g['s']}，已历 {g['age']} 季）")
    if not card.active():
        print("  心结：无未解")
    print_reckon(card, rk, card.offer)
    t, why = target_level(card, rk, args.trigger)
    cur = LEVELS.index(card.level)
    new = step(cur, t)
    print("--- 离心阶梯 ---")
    for w in why:
        print(f"  {w}")
    move = "不变" if new == cur else ("升一级" if new > cur else "降一级")
    capnote = "（每季最多升降一级）" if abs(t - cur) > 1 else ""
    print(f"  账面目标“{LEVELS[t]}”；上季“{LEVELS[cur]}” → 本季【{LEVELS[new]}】，{move}{capnote}")
    if args.trigger:
        print(f"  触发事件：{'、'.join(f'{x}（{TRIGGERS[x]}）' for x in args.trigger)}")
    faded = fade(card)
    for f in faded:
        print(f"  时间淡化：{f}")
    lv = LEVELS[new]
    print(f"\n本级可观察的迹象（GM 经幕僚、斥候透露）：")
    for s in SIGNS[lv]:
        print(f"  · {s}")
    heard = [g for g in card.active() if g["heard"] != "不外传"]
    if heard:
        print("玩家可能听说的心结：")
        for g in heard:
            print(f"  · [{g['id']}] {g['what']}（{g['heard']}）")
    print("\n写进下季 general agent prompt 的人心提示：")
    print("  " + agent_hint(card, rk, lv))
    if lv == "举事":
        print(f"  （若真举兵，约 {card.yaml.get('部曲', '?')}% 的麾下兵马随他走，其余由 GM 判定。）")
    calc = "无开价" if rk["G"] is None else f"留{rk['S']}/走{rk['G']}{'动念' if rk['moved'] else ''}"
    card.log.append(f"{args.when}：{LEVELS[cur]} → {lv}｜心结 {rk['P']}｜缺口 {gap(card):.1f}｜{calc}"
                    + (f"｜触发 {'、'.join(args.trigger)}" if args.trigger else ""))
    card.level = lv
    card.set_yaml("离心", lv)
    found = find_command(card, args.world)
    if found:
        cname, cmd, turn, d = found
        cmd["_name"] = cname
        cmd["far"] = _far(cmd, d, args.world)
        up, seasons, parts = corps_drift(card, cmd, turn, d)
        print(f"\n--- 委任：{cname}（第 {seasons} 季） ---")
        print(f"  部曲涨幅：{'，'.join(parts)}" + (f"（封顶 {CORPS_CAP}，实涨 {up}）" if up < len(parts) else ""))
        old, new = set_corps(card, card_corps(card) + up, f"{args.when} 委任{cname}第 {seasons} 季")
        print(f"  部曲 {old} → {new}")
        if new >= 60:
            print(f"  注意：部曲 ≥60，算盘里“自立”的风险 −{corps_relief(card, '自立')}；举事时约 {new}% 兵马随他走。")
    finish(card, args.apply)


def _far(cmd, d, world):
    """方面治所离帅府几程，超出 4 程的部分。"""
    import json
    try:
        with open(os.path.join(world, "map.json"), encoding="utf-8") as f:
            regions = json.load(f)["regions"]
    except (OSError, KeyError, ValueError):
        return 0
    seat = d.get("council", {}).get("seat")
    if not seat:
        try:
            with open(os.path.join(world, "kingdom.json"), encoding="utf-8") as f:
                seat = json.load(f)["player"]["seat"]
        except (OSError, KeyError, ValueError):
            return 0
    hq = cmd.get("seat") or (cmd.get("regions") or [None])[0]
    dist = bfs(regions, seat).get(hq)
    return dist if dist is not None and dist >= 4 else 0


def bfs(regions, start):
    dist, frontier = {start: 0}, [start]
    while frontier:
        nxt = []
        for r in frontier:
            for a in regions.get(r, {}).get("adjacent", []):
                if a not in dist:
                    dist[a] = dist[r] + 1
                    nxt.append(a)
        frontier = nxt
    return dist


def cmd_corps(card, args):
    need_general(card, "部曲")
    if not args.why:
        die("改部曲要用 --why 写明缘由，会记进阶梯记录")
    old, new = set_corps(card, card_corps(card) + args.delta, args.why)
    print(f"{card.name}：部曲 {old} → {new}（{args.why}）")
    finish(card, args.apply)


def cmd_state(card, args):
    need_general(card, "状态")
    if not args.why:
        die("改状态要用 --why 写明缘由，会记进阶梯记录")
    changes = []
    if args.level:
        if args.level not in LEVELS:
            die(f"--level 应为 {'/'.join(LEVELS)}")
        changes.append(f"离心 {card.level} → {args.level}")
        card.level = args.level
        card.set_yaml("离心", args.level)
    if args.kin:
        if args.kin not in KIN_RISK:
            die(f"--kin 应为 {'/'.join(KIN_RISK)}")
        changes.append(f"家眷 {card.kin} → {args.kin}")
        card.set_yaml("家眷", args.kin)
    if args.standing is not None:
        if not 0 <= args.standing <= 3:
            die("--standing 应在 0–3")
        changes.append(f"名分 {card.standing} → {args.standing}")
        card.set_yaml("名分", args.standing)
    if not changes:
        die("没有要改的：给 --level、--kin 或 --standing")
    card.log.append(f"GM 调整：{'；'.join(changes)}｜{args.why}")
    print(f"{card.name}：{'；'.join(changes)}（{args.why}）")
    finish(card, args.apply)


def daily_probs(card, risky=False, extra_delay=0.0, extra_adapt=0.0):
    """日常检定的概率（%）。extra_* 是委任方面因路远、新官等加的百分点（rules/governance.md）。"""
    lv = LEVELS.index(card.level)
    k = 1.5 if risky else 1.0
    p = {
        "抗命": max(lv - 1, 0) * 4 * k,
        "拖延": (3 + lv * 5) * k + extra_delay,
        "变通": (card.caution * 5 + lv * 3) * k + extra_adapt,
        "超额执行": max(card.zeal * 8 - lv * 3, 0),
    }
    total = sum(p.values())
    if total > 90:
        p = {x: v * 90 / total for x, v in p.items()}
    return p


def pick(p, r):
    acc = 0.0
    for x, pr in p.items():
        if acc <= r < acc + pr:
            return x
        acc += pr
    return "照办"


def cmd_roll(card, args):
    need_general(card, "日常检定")
    p = daily_probs(card, args.risky)
    rng = random.Random(args.seed)
    r = rng.uniform(0, 100)
    acc, result = 0.0, "照办"
    print(f"=== 日常检定：{card.name}（离心：{card.level}，急进 {card.zeal}，持重 {card.caution}"
          + ("，命令凶险" if args.risky else "") + "） ===")
    for x, pr in p.items():
        print(f"  {pad(x, 10)} {pr:5.1f}%   （区间 {acc:5.1f} – {acc + pr:5.1f}）")
        if result == "照办" and acc <= r < acc + pr:
            result = x
        acc += pr
    print(f"  {pad('照办', 10)} {100 - acc:5.1f}%")
    seed = f"，seed={args.seed}" if args.seed is not None else ""
    print(f"  掷骰 d100 = {r:.1f}{seed} → 【{result}】")
    hints = {
        "照办": "这道命令他大体照办。",
        "超额执行": "这道命令他倾向于多打一点：袭扰打成强攻，追击追得太远。",
        "变通": "这道命令他倾向于变通：换打法、换路线、减兵，大意不违。",
        "拖延": "这道命令他倾向于拖一拖：找理由晚出兵、慢行军。",
        "抗命": "这道命令若不合他的意，他可能当面推辞，或者擅自改成别的事。",
    }
    print(f"\n日常提示（写进 agent prompt）：{hints[result]}")
    print("（日常检定只管拖延、变通、超额执行这类小事，不影响离心阶梯，也不会掷出暗通、叛变。）")


def main():
    ap = argparse.ArgumentParser(description="人心账本（规则见 rules/loyalty.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_):
        p = sp.add_parser(name, help=help_)
        p.add_argument("card", help="人格卡路径，如 characters/<拼音>.md")
        return p

    def offer_args(p):
        p.add_argument("--from", dest="from_", help="开价的人")
        p.add_argument("--dest", choices=DESTS, help="去处")
        p.add_argument("--give", help="开价对各项需求的满足度，如 权柄=3,家眷平安=3")
        p.add_argument("--pursuit", type=int, default=0, choices=range(0, 4), help="被追杀、讨伐的可能 0–3")
        p.add_argument("--extract", action="store_true", help="对方许诺并有能力接出家眷")
        p.add_argument("--offer-when", dest="when_offer", help="开价的时间")
        p.add_argument("--terms", help="开价原话摘要")
        p.add_argument("--withdraw", action="store_true", help="开价已撤销或失效")

    p = add("show", "查看账本、算盘和迹象")
    p.add_argument("--public", action="store_true", help="只列玩家可能听说的心结")
    p.set_defaults(fn=cmd_show)

    p = add("need", "更新一项需求的满足度")
    p.add_argument("need")
    p.add_argument("value", type=int)
    p.add_argument("--weight", type=int)
    p.add_argument("--why")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_need)

    p = add("grudge", "添一条心结")
    p.add_argument("--when", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--strength", type=int, required=True)
    p.add_argument("--heard", default="不外传")
    p.add_argument("--toward", help="心结针对某个具体的人：同时在关系网（world/relations.json）里记一笔怨")
    p.add_argument("--world", default=os.path.join(ROOT, "world"), help="存档目录（写关系网用），默认 world/")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_grudge)

    p = add("ease", "消解或加深一条心结")
    p.add_argument("id", type=int)
    p.add_argument("--by", required=True, choices=EASE_MODES)
    p.add_argument("--note")
    p.add_argument("--world", default=os.path.join(ROOT, "world"), help="存档目录（同步关系网用），默认 world/")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_ease)

    p = add("offer", "记下或撤销外部开价")
    offer_args(p)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_offer)

    p = add("reckon", "试算出走的算盘（不写卡）")
    offer_args(p)
    p.set_defaults(fn=cmd_reckon)

    p = add("season", "季末推进离心阶梯")
    p.add_argument("--when", required=True, help="本季，如 某年冬（照 kingdom.json 的 date 写）")
    p.add_argument("--trigger", action="append", default=[], help="触发事件，可重复：" + "、".join(TRIGGERS))
    p.add_argument("--world", default=os.path.join(ROOT, "world"),
                   help="存档目录（读 directives.json 算委任部曲），默认 world/")
    offer_args(p)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_season)

    p = add("state", "GM 直接改离心级别、家眷、名分")
    p.add_argument("--level")
    p.add_argument("--kin")
    p.add_argument("--standing", type=int)
    p.add_argument("--why")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_state)

    p = add("corps", "GM 手改部曲")
    p.add_argument("--delta", type=int, required=True)
    p.add_argument("--why")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_corps)

    p = add("roll", "日常小波动的骰子")
    p.add_argument("--risky", action="store_true", help="命令凶险：抗命、拖延、变通 ×1.5")
    p.add_argument("--seed", type=int)
    p.set_defaults(fn=cmd_roll)

    args = ap.parse_args()
    path = args.card if os.path.isabs(args.card) else os.path.join(ROOT, args.card)
    if not os.path.exists(path) and os.path.exists(args.card):
        path = os.path.abspath(args.card)
    args.fn(Card(path), args)


if __name__ == "__main__":
    main()
