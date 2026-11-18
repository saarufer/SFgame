#!/usr/bin/env python3
"""剧本包校验：检查一个剧本包（或当前存档 world/）是否完整、前后一致。只用标准库，只读不写。

用法：
  python3 scripts/scenario_check.py scenarios/<剧本名>     # 剧本包：scenario.json、world/、characters/ 在同一目录
  python3 scripts/scenario_check.py world                  # 当前存档：world/scenario.json，卡片在项目根目录的 characters/
  python3 scripts/scenario_check.py                        # 不给参数，等于检查 world/

查的东西：
  scenario.json 必填字段；地图相邻关系对称、没有孤立地区；军队所在地区存在；
  兵种都在 rules/units.md 和 economy.json 的粮饷表里；factions 里 controlled_by 为 ruler 的有 card 且文件存在；
  人格卡的数值块能被 loyalty.py 解析；household.json 里的卡存在；directives.json 引用的地区和军存在；
  年号表能覆盖开局年份；治所、己方势力名、季节名前后一致；特色收入条目对得上 economy.json；
  人格卡的十一项属性、识人、伤势（rules/people.md）；名册 people.json 的属性块；剧本追加的身份（people.identities）；
  庙堂几样存档（有就查）：relations.json、court.json（含仕途阶梯 ladders）、rumors.json、secrets.json、households/*.json，人格卡的名望、心迹；
  scenario.json 的 player.role（君主 / 臣子）；个人钱物 purse.json；场景 scenes.json、行动件数 actions.json；
  scenario.json 的 scene（夜禁时辰）、actions（每季件数）、purse（钱的单位）。

输出“通过”，或者“问题清单”（必须改）和“提醒”（可以不改）。有问题时退出码为 1。
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import loyalty as L  # noqa: E402
import scenario_lib as S  # noqa: E402

REQUIRED = {
    "format_version": int,
    "id": str,
    "name": str,
    "era": str,
    "tagline": str,
    "start": dict,
    "calendar": dict,
    "turn_unit": dict,
    "player": dict,
    "terms": dict,
    "units": list,
    "newgame": dict,
}
REQUIRED_SUB = {
    "start": ["year", "season", "date"],
    "calendar": ["style"],
    "turn_unit": ["name", "seasons"],
    "player": ["faction", "protagonist", "title", "seat"],
    "terms": ["ruler", "regional_commander", "local_official", "region_unit", "army_unit"],
    "newgame": ["family", "rounds"],
}
CAL_STYLES = ("年号", "干支", "公元")
FEATURE_STATUS = ("已计入", "已建", "可建", "规则")
FLAVOR_KEYS = ("season_details", "spots", "new_faces", "family_spots", "family_details")


class Report:
    def __init__(self):
        self.problems, self.notes, self.ok = [], [], []

    def bad(self, msg):
        self.problems.append(msg)

    def warn(self, msg):
        self.notes.append(msg)

    def good(self, msg):
        self.ok.append(msg)


def load_json(path, rep, required=True):
    if not os.path.exists(path):
        if required:
            rep.bad(f"缺文件：{path}")
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except ValueError as e:
        rep.bad(f"{path} 不是合法的 JSON：{e}")
        return None


def unit_codes_from_rules():
    """从 rules/units.md 的兵种表里取代码（第二列）。"""
    path = os.path.join(ROOT, "rules", "units.md")
    codes = set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 3 and re.fullmatch(r"[a-z_]+", cells[1] or ""):
                    codes.add(cells[1])
    except OSError:
        pass
    return codes


def parse_card(path):
    """用 loyalty.py 的解析器读卡；主角卡只要求有数值块和姓名。返回 (错误或 None, 身份, 姓名)。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return f"读不到：{e}", None, None
    m = L.YAML_RE.search(text)
    if not m:
        return "没有 ```yaml 数值块", None, None
    yaml = {}
    for line in m.group(1).splitlines():
        lm = L.LINE_RE.match(line)
        if lm:
            yaml[lm.group(2).strip()] = lm.group(3).strip()
    role = yaml.get("身份", "将领")
    name = yaml.get("姓名")
    if not name:
        return "数值块里没有“姓名”", role, None
    if role == "主角":
        return None, role, name
    try:
        L.Card(path)
    except SystemExit as e:
        return str(e.code).replace("错误：", ""), role, name
    return None, role, name


# ---------------------------------------------------------------- 各项检查

def rules_base(sc, base, package):
    """剧本规则补充所在的目录：剧本包就是它自己；开局后的存档去 scenarios/<id>/ 找。"""
    if package:
        return base
    d = os.path.join(base, "scenarios", str(sc.get("id", "")))
    return d if sc.get("id") and os.path.isdir(d) else None


def check_scenario(sc, base, rep, package):
    for key, typ in REQUIRED.items():
        if key not in sc:
            rep.bad(f"scenario.json 缺必填字段 {key}")
        elif not isinstance(sc[key], typ):
            rep.bad(f"scenario.json 的 {key} 应为 {typ.__name__}")
    for key, subs in REQUIRED_SUB.items():
        v = sc.get(key)
        if isinstance(v, dict):
            for s in subs:
                if v.get(s) in (None, "", []):
                    rep.bad(f"scenario.json 缺 {key}.{s}")
    if package and sc.get("id") and sc["id"] != os.path.basename(os.path.normpath(base)):
        rep.warn(f"scenario.json 的 id（{sc['id']}）和目录名（{os.path.basename(os.path.normpath(base))}）不同")
    intro = sc.get("intro", "intro.md")
    if package and not os.path.exists(os.path.join(base, intro)):
        rep.bad(f"缺剧本简介 {intro}")
    seasons = sc.get("turn_unit", {}).get("seasons")
    if seasons and list(seasons) != S.STD_SEASONS:
        rep.bad(f"turn_unit.seasons 现在只支持 春夏秋冬 四季（脚本按这四个字结算），写的是 {seasons}")
    if sc.get("start", {}).get("season") and sc["start"]["season"] not in S.STD_SEASONS:
        rep.bad(f"start.season 应为 春/夏/秋/冬：{sc['start']['season']}")
    cal = sc.get("calendar", {})
    if cal.get("style") and cal["style"] not in CAL_STYLES:
        rep.bad(f"calendar.style 应为 {'/'.join(CAL_STYLES)}：{cal['style']}")
    if cal.get("style") == "年号" and not cal.get("eras"):
        rep.bad("calendar.style 是“年号”，但没有 eras 年号表")
    for e in cal.get("eras") or []:
        if not isinstance(e, dict) or "from" not in e or "name" not in e:
            rep.bad(f"年号表的每一条要写成 {{\"from\": 公元年, \"name\": 年号}}：{e}")
    role = sc.get("player", {}).get("role")
    if role is not None and role not in ("君主", "臣子"):
        rep.bad(f"player.role 只能是 君主 或 臣子：{role!r}")
    for d in sc.get("dest_labels", {}):
        if d not in L.DESTS:
            rep.bad(f"dest_labels 的键只能是 {'/'.join(L.DESTS)}：{d}")
    for k in sc.get("flavor", {}):
        if k not in FLAVOR_KEYS:
            rep.warn(f"flavor.{k} 脚本不认（认得的：{'、'.join(FLAVOR_KEYS)}）")
    rb = rules_base(sc, base, package)
    if rb is None and (sc.get("extra_rules") or sc.get("economy_features")):
        rep.warn(f"找不到剧本目录 scenarios/{sc.get('id')}/，规则补充文件没法核对")
    for r in sc.get("extra_rules", []) if rb else []:
        if not os.path.exists(os.path.join(rb, r)):
            rep.bad(f"extra_rules 里的 {r} 不存在")
    ng = sc.get("newgame", {})
    fam = ng.get("family", {})
    if isinstance(fam, dict) and "enabled" not in fam:
        rep.bad("newgame.family 缺 enabled（默认家人启用与否）")
    for i, rd in enumerate(ng.get("rounds", []), 1):
        qs = rd.get("questions", [])
        if len(qs) > 4:
            rep.bad(f"newgame 第 {i} 轮有 {len(qs)} 题，AskUserQuestion 每轮最多 4 题")
        for q in qs:
            tag = f"newgame 第 {i} 轮“{q.get('header') or q.get('key')}”"
            if not q.get("header"):
                rep.bad(f"{tag} 缺 header")
            elif len(q["header"]) > 12:
                rep.warn(f"{tag} 的 header 太长（{len(q['header'])} 字），题头最好在 12 字以内")
            opts = q.get("options", [])
            if not 2 <= len(opts) <= 4:
                rep.bad(f"{tag} 有 {len(opts)} 个选项，应为 2–4 个（玩家另可选“其他”）")
            if sum(1 for o in opts if o.get("default")) > 1:
                rep.bad(f"{tag} 有不止一个默认选项")


def check_calendar(sc, world, kingdom, household, rep):
    try:
        cal = S.calendar(world, household=household or {})
    except SystemExit as e:
        rep.bad(str(e.code).replace("错误：", ""))
        return
    year = (sc.get("start") or {}).get("year") or cal.get("turn1_year")
    if year is None:
        return
    if not S.era_covers(cal, int(year)):
        rep.bad(f"年号表覆盖不到开局年份 {year}（最早的年号从 {min(e['from'] for e in cal.get('eras', []))} 年起）")
        return
    label = S.year_label(cal, int(year)) + (cal.get("turn1_season") or "春")
    rep.good(f"纪年：第 1 回合是 {label}")
    hcal = (household or {}).get("calendar")
    if hcal and sc.get("calendar"):
        for k in ("eras", "turn1_year"):
            sv = sc["calendar"].get(k) if k != "turn1_year" else sc.get("start", {}).get("year")
            if hcal.get(k) is not None and sv is not None and hcal.get(k) != sv:
                rep.warn(f"household.json 的 calendar.{k} 和 scenario.json 不同，脚本以 household.json 为准")
    if kingdom and kingdom.get("turn") == 1:
        date = str(kingdom.get("date", "")).replace(" ", "")
        if date and date != label:
            rep.warn(f"kingdom.json 的 date（{kingdom.get('date')}）和纪年算出来的（{label}）不一样")
    sd = str((sc.get("start") or {}).get("date", "")).replace(" ", "")
    if sd and sd != label:
        rep.warn(f"scenario.json 的 start.date（{sc['start']['date']}）和纪年算出来的（{label}）不一样")


def check_map(regions, rep):
    for r, d in regions.items():
        adj = d.get("adjacent", [])
        if not adj:
            rep.bad(f"地图：{r} 没有相邻地区（孤立）")
        for a in adj:
            if a == r:
                rep.bad(f"地图：{r} 和自己相邻")
            elif a not in regions:
                rep.bad(f"地图：{r} 的相邻地区 {a} 不在 map.json 里")
            elif r not in regions[a].get("adjacent", []):
                rep.bad(f"地图：{r} → {a} 相邻，但 {a} 的 adjacent 里没有 {r}（不对称）")
        if "income" not in d:
            rep.warn(f"地图：{r} 没有 income")
        if not d.get("terrain"):
            rep.bad(f"地图：{r} 没有 terrain")
    if regions:
        start = next(iter(regions))
        seen = set(L.bfs(regions, start))
        rest = [r for r in regions if r not in seen]
        if rest:
            rep.warn(f"地图不连通：从 {start} 走不到 {'、'.join(rest)}")
        rep.good(f"地图：{len(regions)} 个地区")


def region_of_location(loc, regions):
    if loc in regions:
        return loc
    hits = [r for r in regions if r and r in str(loc)]
    return max(hits, key=len) if hits else None


ARMOR_CODES = ("none", "light", "heavy", "barded")
DRILL_CODES = ("raw", "regular", "elite")


def check_armies(armies, regions, factions, eco, rep, own, scen_units):
    rule_codes = unit_codes_from_rules()
    upkeep = (eco or {}).get("upkeep_per_1000", {})
    fac_names = set(factions)
    for name, a in armies.items():
        loc = a.get("location")
        reg = region_of_location(loc, regions)
        if reg is None:
            rep.bad(f"军队 {name} 的所在地 {loc!r} 不在地图上")
        elif reg != loc:
            rep.warn(f"军队 {name} 的所在地写成 {loc!r}，脚本按 {reg} 算")
        fac = str(a.get("faction", ""))
        if not any(fac == f or fac.startswith(f) for f in fac_names):
            rep.bad(f"军队 {name} 的势力 {fac!r} 不在 factions.json 里")
        for u, n in a.get("units", {}).items():
            if rule_codes and u not in rule_codes:
                rep.bad(f"军队 {name} 的兵种 {u} 不在 rules/units.md 的兵种表里（要写代码，别名只能用在战斗输入里）")
            if u not in upkeep:
                rep.bad(f"军队 {name} 的兵种 {u} 不在 economy.json 的 upkeep_per_1000 粮饷表里")
            if scen_units and u not in scen_units:
                rep.warn(f"军队 {name} 的兵种 {u} 没列在 scenario.json 的 units 里")
            if not isinstance(n, int) or n < 0:
                rep.bad(f"军队 {name} 的 {u} 人数不是非负整数：{n!r}")
        # 可选：护甲、操练（rules/units.md“护甲与操练”），整军一个值，或按兵种写
        for key, allowed in (("armor", ARMOR_CODES), ("drill", DRILL_CODES)):
            val = a.get(key)
            if val is None:
                continue
            items = {"(整军)": val} if isinstance(val, str) else val if isinstance(val, dict) else None
            if items is None:
                rep.bad(f"军队 {name} 的 {key} 要写成字符串或 {{兵种: 值}}：{val!r}")
                continue
            for u, v in items.items():
                if u != "(整军)" and u not in a.get("units", {}):
                    rep.warn(f"军队 {name} 的 {key} 写了 {u}，但这支军没有这个兵种")
                if v not in allowed:
                    rep.bad(f"军队 {name} 的 {key} {v!r} 不认识，可用：{'、'.join(allowed)}")
    for u in scen_units:
        if rule_codes and u not in rule_codes:
            rep.bad(f"scenario.json 的兵种 {u} 不在 rules/units.md 的兵种表里")
        if upkeep and u not in upkeep:
            rep.bad(f"scenario.json 的兵种 {u} 不在 economy.json 的 upkeep_per_1000 粮饷表里")
    mine = [n for n, a in armies.items() if str(a.get("faction", "")).startswith(own)] if own else []
    rep.good(f"军队：{len(armies)} 支，其中己方 {len(mine)} 支，共 "
             f"{sum(sum(a.get('units', {}).values()) for n, a in armies.items() if n in mine)} 人")


def card_file(base, rel):
    if not rel:
        return None
    return rel if os.path.isabs(rel) else os.path.join(base, rel)


def check_factions(factions, regions, base, rep, own, vassal=False):
    players = [k for k, f in factions.items() if f.get("controlled_by") == "player"]
    if vassal:
        if len(players) > 1:
            rep.bad(f"factions.json 里 controlled_by 为 player 的势力至多一个，现在是 {players}")
        players = players or [own]
    elif len(players) != 1:
        rep.bad(f"factions.json 里 controlled_by 为 player 的势力应有且只有一个，现在是 {players or '没有'}"
                "（主角不是一方之主的，scenario.json 的 player.role 写“臣子”）")
    if own and own not in factions:
        rep.bad(f"己方势力 {own} 不在 factions.json 里")
    elif own and players and players[0] != own and not vassal:
        rep.bad(f"factions.json 的玩家势力是 {players[0]}，scenario.json 的 player.faction 是 {own}")
    for k, f in factions.items():
        cb = str(f.get("controlled_by", ""))
        if cb == "ruler":
            c = f.get("card")
            if not c:
                rep.bad(f"势力 {k} 由 ruler 扮演，但没写 card（人格卡路径）")
            elif not os.path.exists(card_file(base, c)):
                rep.bad(f"势力 {k} 的人格卡 {c} 不存在")
        elif cb.startswith("agent:"):
            rep.warn(f"势力 {k} 写的是旧版专属 agent（{cb}），新局请改成 ruler + card")
        elif cb not in ("player", "GM", "ruler"):
            rep.warn(f"势力 {k} 的 controlled_by 是 {cb!r}，应为 player / ruler / GM")
    owners = {d.get("owner") for d in regions.values()}
    for o in owners:
        if o and o not in factions and not any(str(o).startswith(f) for f in factions):
            rep.bad(f"地图上的主人 {o} 不在 factions.json 里")


def check_cards(base, rep):
    cdir = os.path.join(base, "characters")
    names = {}
    if not os.path.isdir(cdir):
        rep.bad(f"缺人格卡目录 {cdir}")
        return names
    n = 0
    for path in sorted(glob.glob(os.path.join(cdir, "*.md"))):
        b = os.path.basename(path)
        if b.startswith("_") or b == "README.md":
            continue
        err, role, name = parse_card(path)
        n += 1
        if err:
            rep.bad(f"人格卡 {b}：{err}")
        else:
            names[name] = (b, role)
    rep.good(f"人格卡：{n} 张，数值块和账本都能被 loyalty.py 解析" if n and not any("人格卡" in p for p in rep.problems)
             else f"人格卡：{n} 张")
    return names


def check_persona(base, world, rep, sc, package=True):
    """人物属性：人格卡的数值块、名册的 persona、剧本追加的身份（rules/people.md）。
    剧本包里的卡缺属性算问题；开局后的旧存档缺属性只提醒（脚本会按身份临时补，persona.py fill 可以写回）。"""
    import persona as P
    try:
        T = P.Tables(world)
    except SystemExit as e:
        rep.bad(f"身份表：{str(e.code).replace('错误：', '')}")
        return
    if (sc.get("people") or {}).get("identities"):
        rep.good(f"身份表：引擎 {sum(1 for i in T.identities.values() if i['source'] == '引擎')} 种，"
                 f"剧本追加 {sum(1 for i in T.identities.values() if i['source'] == '剧本')} 种")
    for idn in T.identities.values():
        for a, m in idn["mean"].items():
            if not 1 <= m <= 10:
                rep.bad(f"身份“{idn['name']}”的 {a} 均值 {m} 不在 1–10")
    cdir = os.path.join(base, "characters")
    n_ok = 0
    for path in sorted(glob.glob(os.path.join(cdir, "*.md"))):
        b = os.path.basename(path)
        if b.startswith("_") or b == "README.md":
            continue
        with open(path, encoding="utf-8") as f:
            y = P.read_yaml(f.read()) or {}
        miss = [a for a in P.ATTRS if a not in y]
        if miss:
            msg = f"人格卡 {b} 缺属性 {'、'.join(miss)}（rules/people.md 第二节；旧卡可用 persona.py fill 补齐）"
            rep.bad(msg) if package else rep.warn(msg)
            continue
        bad = []
        for a in P.ATTRS:
            try:
                v = int(y[a])
                if not 1 <= v <= 10:
                    bad.append(f"{a}={v}")
            except ValueError:
                bad.append(f"{a}={y[a]!r}")
        if bad:
            rep.bad(f"人格卡 {b} 的属性应为 1–10 的整数：{'、'.join(bad)}")
            continue
        for k in ("特长", "短处", "性情"):
            if not y.get(k):
                rep.warn(f"人格卡 {b} 没写“{k}”")
        for t in P.split_list(y.get("特长", "")):
            if t not in T.tags:
                rep.warn(f"人格卡 {b} 的特长“{t}”不在特长表里，只作描写，较量里没有加成")
        if y.get("身份") != "主角":
            try:
                k = int(y.get("识人", "x"))
                if not 0 <= k <= 3:
                    raise ValueError
            except ValueError:
                rep.bad(f"人格卡 {b} 的“识人”应为 0–3：{y.get('识人')!r}")
        inj = y.get("伤势")
        if inj is None:
            rep.bad(f"人格卡 {b} 没有“伤势”（写“无”）")
        elif inj.strip() != "无" and not inj.startswith("亡故"):
            pi = P.parse_injury(inj)
            if not pi or pi["level"] not in P.INJURY_LEVELS:
                rep.bad(f"人格卡 {b} 的伤势看不懂：{inj!r}（写成“无”或“轻伤｜部位｜余 N 季”）")
        n_ok += 1
    roster = load_json(os.path.join(world, "people.json"), rep, required=False) or {}
    n_p = 0
    for e in roster.get("people", []):
        per = e.get("persona")
        if not per:
            if e.get("status", "在") == "在" and not e.get("card"):
                rep.warn(f"名册里的 {e.get('name')} 还没有属性（persona.py gen {e.get('name')} --role {e.get('role', '身份')} --apply）")
            continue
        n_p += 1
        at = per.get("attrs", {})
        miss = [a for a in P.ATTRS if a not in at]
        if miss:
            rep.bad(f"名册里 {e.get('name')} 的属性缺 {'、'.join(miss)}")
        elif any(not (isinstance(at[a], int) and 1 <= at[a] <= 10) for a in P.ATTRS):
            rep.bad(f"名册里 {e.get('name')} 的属性应为 1–10 的整数")
        if not 0 <= int(e.get("识人", 0)) <= 3:
            rep.bad(f"名册里 {e.get('name')} 的识人应为 0–3")
    for obs, d in (roster.get("acquaintance") or {}).items():
        for tgt, k in d.items():
            if not (isinstance(k, int) and 0 <= k <= 3):
                rep.bad(f"名册 acquaintance：{obs} 对 {tgt} 的进度应为 0–3：{k!r}")
    rep.good(f"人物属性：人格卡 {n_ok} 张齐全" + (f"，名册 {n_p} 人有属性" if n_p else ""))


def check_household(hh, regions, base, rep, sc):
    fam = (sc.get("newgame") or {}).get("family", {})
    if hh is None:
        if isinstance(fam, dict) and fam.get("enabled"):
            rep.bad("newgame.family.enabled 为 true，但没有 world/household.json")
        return
    p = hh.get("protagonist", {})
    c = p.get("card")
    if c and not os.path.exists(card_file(base, c)):
        rep.bad(f"household.json 的主角卡 {c} 不存在")
    if sc.get("player", {}).get("protagonist") and p.get("name") and p["name"] != sc["player"]["protagonist"]:
        rep.warn(f"household.json 的主角（{p['name']}）和 scenario.json 的 player.protagonist（{sc['player']['protagonist']}）不同")
    for mid, m in hh.get("members", {}).items():
        c = m.get("card")
        if c and not os.path.exists(card_file(base, c)):
            rep.bad(f"household.json 里 {mid}（{m.get('name')}）的卡 {c} 不存在")
        try:
            int(m.get("born"))
        except (TypeError, ValueError):
            rep.bad(f"household.json 里 {mid} 的 born 不是年份：{m.get('born')!r}")
        reg = (m.get("residence") or "").split("·")[0]
        if reg and reg not in regions and m.get("status", "在") == "在":
            rep.warn(f"household.json 里 {mid} 住在 {reg}，地图上没有这个地区")
    rep.good(f"家宅：主角加 {len(hh.get('members', {}))} 位家人")


def check_directives(d, regions, armies, rep):
    if d is None:
        return
    seat = d.get("council", {}).get("seat")
    if seat and seat not in regions:
        rep.bad(f"directives.json 的 council.seat {seat} 不在地图上")
    for kind in ("commands", "loose"):
        for name, c in d.get(kind, {}).items():
            for r in c.get("regions", []):
                if r not in regions:
                    rep.bad(f"directives.json 的 {kind}.{name} 引用的地区 {r} 不存在")
            for a in c.get("armies", []):
                if a not in armies:
                    rep.bad(f"directives.json 的 {kind}.{name} 引用的军 {a} 不存在")
            if kind == "commands" and c.get("seat") and c["seat"] not in regions:
                rep.bad(f"directives.json 的 commands.{name}.seat {c['seat']} 不在地图上")
    for a in d.get("establishment", {}):
        if a not in armies:
            rep.bad(f"directives.json 的 establishment 引用的军 {a} 不存在")


def check_consistency(sc, kingdom, eco, regions, rep):
    own = sc.get("player", {}).get("faction")
    seat = sc.get("player", {}).get("seat")
    if kingdom:
        ks = kingdom.get("player", {}).get("seat")
        if ks and seat and ks != seat:
            rep.warn(f"kingdom.json 的治所（{ks}）和 scenario.json（{seat}）不同；开局时应一致")
        for key in ("turn", "date", "treasury"):
            if key not in kingdom:
                rep.bad(f"kingdom.json 缺 {key}")
        tr = kingdom.get("treasury", {})
        for k in ("money", "grain", "horses"):
            if k not in tr:
                rep.bad(f"kingdom.json 的 treasury 缺 {k}")
    vassal = sc.get("player", {}).get("role") == "臣子"
    if seat:
        if seat not in regions:
            rep.bad(f"治所 {seat} 不在地图上")
        elif own and regions[seat].get("owner") != own and not vassal:
            rep.bad(f"治所 {seat} 的主人是 {regions[seat].get('owner')}，不是己方 {own}")
    if eco:
        if eco.get("own_faction") and own and eco["own_faction"] != own:
            rep.bad(f"economy.json 的 own_faction（{eco['own_faction']}）和 scenario.json 的 player.faction（{own}）不同")
        sm = eco.get("season_multiplier", {})
        for k in ("grain", "money"):
            keys = set(sm.get(k, {}))
            if keys != set(S.STD_SEASONS):
                rep.bad(f"economy.json 的 season_multiplier.{k} 应有春夏秋冬四项：{sorted(keys)}")
        for k in ("war_multiplier", "upkeep_per_1000"):
            if k not in eco:
                rep.bad(f"economy.json 缺 {k}")


def check_features(sc, eco, regions, base, rep, package):
    names = {i.get("name") for k in ("fixed_income", "fixed_expense") for i in (eco or {}).get(k, [])}
    for f in sc.get("economy_features", []):
        key = f.get("key", "?")
        st = f.get("status")
        if st not in FEATURE_STATUS:
            rep.bad(f"特色收入 {key} 的 status 应为 {'/'.join(FEATURE_STATUS)}：{st!r}")
        rb = rules_base(sc, base, package)
        if f.get("rule") and rb and not os.path.exists(os.path.join(rb, f["rule"])):
            rep.bad(f"特色收入 {key} 的规则文件 {f['rule']} 不存在")
        item = f.get("economy_item")
        if f.get("region") and f["region"] not in regions:
            rep.bad(f"特色收入 {key} 的地区 {f['region']} 不在地图上")
        if st == "已建":
            if not item or item.get("name") not in names:
                rep.bad(f"特色收入 {key} 标为“已建”，但 economy.json 的固定收支里找不到 {item and item.get('name')!r}")
        if item:
            if item.get("list") not in ("fixed_income", "fixed_expense"):
                rep.bad(f"特色收入 {key} 的 economy_item.list 应为 fixed_income 或 fixed_expense")
            if not item.get("name"):
                rep.bad(f"特色收入 {key} 的 economy_item 缺 name")
            if item.get("region") and item["region"] not in regions:
                rep.bad(f"特色收入 {key} 依托的地区 {item['region']} 不在地图上")


# ---------------------------------------------------------------- 庙堂几样存档

def known_people(base, world):
    """人格卡和名册里的名字，外加 household 里的人。"""
    import persona as P
    names = set()
    for path in glob.glob(os.path.join(base, "characters", "*.md")):
        with open(path, encoding="utf-8") as f:
            y = P.read_yaml(f.read()) or {}
        if y.get("姓名"):
            names.add(y["姓名"])
    roster = load_json(os.path.join(world, "people.json"), Report(), required=False) or {}
    names |= {e.get("name") for e in roster.get("people", [])}
    for hp in [os.path.join(world, "household.json")] + glob.glob(os.path.join(world, "households", "*.json")):
        hh = load_json(hp, Report(), required=False) or {}
        names |= {m.get("name") for m in hh.get("members", {}).values()}
        if hh.get("protagonist", {}).get("name"):
            names.add(hh["protagonist"]["name"])
    return names


def check_social(base, world, rep, sc):
    import social_lib as X
    files = [f for f in ("relations.json", "court.json", "rumors.json", "secrets.json") if os.path.exists(os.path.join(world, f))]
    hfiles = sorted(glob.glob(os.path.join(world, "households", "*.json")))
    cards = [p for p in glob.glob(os.path.join(base, "characters", "*.md")) if not os.path.basename(p).startswith("_")]
    if not files and not hfiles and not any("名望" in open(p, encoding="utf-8").read() for p in cards):
        return
    who = known_people(base, world)

    def person(n, where):
        if n and n not in who:
            rep.warn(f"{where} 里的 {n} 不在人格卡、名册、家宅里（属性、名望没处读；persona.py gen 记进名册）")

    # 名望、心迹
    import persona as P
    rumors = load_json(os.path.join(world, "rumors.json"), rep, required=False) or {}
    kinds = rumors.get("fame_kinds") or X.FAME_KINDS
    for path in cards:
        with open(path, encoding="utf-8") as f:
            y = P.read_yaml(f.read()) or {}
        b = os.path.basename(path)
        if y.get("名望"):
            try:
                fm = X.parse_fame(y["名望"])
                for k, v in fm.items():
                    if k not in kinds:
                        rep.bad(f"人格卡 {b} 的名望“{k}”不是名望的种类（{'、'.join(kinds)}）")
                    if not 0 <= v <= 10:
                        rep.bad(f"人格卡 {b} 的名望 {k}{v} 不在 0–10")
            except SystemExit as e:
                rep.bad(f"人格卡 {b}：{str(e.code).replace('错误：', '')}")
        if y.get("身份") in X.COURT_ROLES:
            import court as C0
            if y.get("心迹", "恭谨") not in C0.MIND_LEVELS:
                rep.bad(f"人格卡 {b} 的心迹应为 {'/'.join(C0.MIND_LEVELS)}：{y.get('心迹')!r}")
    # 关系网
    rel = load_json(os.path.join(world, "relations.json"), rep, required=False)
    if rel is not None:
        import relations as REL
        for p in rel.get("pairs", []):
            if not p.get("a") or not p.get("b") or p["a"] == p["b"]:
                rep.bad(f"relations.json 有一对关系的 a、b 不对：{p.get('a')!r}、{p.get('b')!r}")
                continue
            for t in p.get("tags", []):
                if t.get("tag") not in REL.TAGS:
                    rep.warn(f"relations.json：{p['a']}—{p['b']} 的标签“{t.get('tag')}”不在标签表里，底子按 0 算")
                for k in (t.get("roles") or {}):
                    if k not in (p["a"], p["b"]):
                        rep.bad(f"relations.json：{p['a']}—{p['b']} 的标签 roles 里有外人 {k}")
            for side, v in (p.get("base") or {}).items():
                if v is not None and not -2 <= int(v) <= 2:
                    rep.bad(f"relations.json：{p['a']}—{p['b']} 的底子 {side}={v} 不在 −2..2")
            person(p["a"], "relations.json")
            person(p["b"], "relations.json")
        ids = set()
        for x in rel.get("deeds", []):
            tag = f"relations.json 恩怨 [{x.get('id')}]"
            if x.get("id") in ids:
                rep.bad(f"{tag} 编号重复")
            ids.add(x.get("id"))
            if x.get("kind") not in ("恩", "怨"):
                rep.bad(f"{tag} 的 kind 应为 恩 或 怨")
            if not (isinstance(x.get("s"), int) and 0 <= x["s"] <= 3):
                rep.bad(f"{tag} 的强度应为 0–3")
            if x.get("known") not in REL.KNOWN:
                rep.bad(f"{tag} 的 known 应为 {'/'.join(REL.KNOWN)}")
            if x.get("holder") == x.get("toward"):
                rep.bad(f"{tag} 记在同一个人身上")
        if ids and rel.get("next_id", 0) <= max(i for i in ids if isinstance(i, int)):
            rep.bad("relations.json 的 next_id 不比已有的编号大")
        rep.good(f"关系网：{len(rel.get('pairs', []))} 对关系，{len(rel.get('deeds', []))} 笔恩怨")
    # 朝廷
    court = load_json(os.path.join(world, "court.json"), rep, required=False)
    if court is not None:
        import court as C0
        facs = court.get("factions", {})
        person(court.get("sovereign"), "court.json 的 sovereign")
        seen = {}
        for f, r in facs.items():
            if r.get("leader") and r["leader"] not in r.get("members", []):
                rep.bad(f"court.json：{f} 的首领 {r['leader']} 不在成员里")
            if not 0 <= int(r.get("voice", 5)) <= 10:
                rep.bad(f"court.json：{f} 的声量应为 0–10")
            for m in r.get("members", []):
                if m in seen:
                    rep.bad(f"court.json：{m} 同时在 {seen[m]} 和 {f}")
                seen[m] = f
                person(m, f"court.json 的{f}")
        holders = {}
        for o, r in court.get("offices", {}).items():
            try:
                rk = int(r.get("rank"))
                if not 1 <= rk <= 9:
                    raise ValueError
            except (TypeError, ValueError):
                rep.bad(f"court.json：官职 {o} 的品级应为 1–9：{r.get('rank')!r}")
            h = r.get("holder")
            if h:
                if h in holders:
                    rep.warn(f"court.json：{h} 同时任 {holders[h]} 和 {o}")
                holders[h] = o
                person(h, f"court.json 的官职 {o}")
        for k, iss in court.get("issues", {}).items():
            opts = iss.get("options", [])
            sv = iss.get("sovereign", {})
            if sv.get("signal") and sv["signal"] not in C0.SIGNALS:
                rep.bad(f"court.json：议题 {k} 的圣意 signal 应为 {'/'.join(C0.SIGNALS)}")
            if sv.get("lean") and opts and sv["lean"] not in opts:
                rep.warn(f"court.json：议题 {k} 的圣意“{sv['lean']}”不在选项里")
            for f, pos in iss.get("positions", {}).items():
                if f not in facs:
                    rep.bad(f"court.json：议题 {k} 的立场里有不存在的派系 {f}")
                for x in [pos.get("want")] + list(pos.get("accept", [])) + list(pos.get("bottom", [])):
                    if x and opts and x not in opts:
                        rep.warn(f"court.json：议题 {k} 里 {f} 的主张“{x}”不在选项（{'、'.join(opts)}）里")
                if not 1 <= int(pos.get("weight", 2)) <= 3:
                    rep.bad(f"court.json：议题 {k} 里 {f} 的 weight 应为 1–3")
        for m in court.get("memorials", []):
            if m.get("kind") not in C0.KINDS:
                rep.bad(f"court.json：奏疏 {m.get('id')} 的 kind 应为 {'/'.join(C0.KINDS)}")
        for key, fd in court.get("feuds", {}).items():
            a, _, b = key.partition("|")
            for f in (a, b):
                if f not in facs:
                    rep.bad(f"court.json：党争 {key} 里的 {f} 不是派系")
            if fd.get("level", "相安") not in C0.FEUD_LEVELS:
                rep.bad(f"court.json：党争 {key} 的 level 应为 {'/'.join(C0.FEUD_LEVELS)}")
            for e in fd.get("entries", []):
                if not 1 <= int(e.get("s", 0)) <= 3:
                    rep.bad(f"court.json：党争 {key} 的积怨强度应为 1–3")
        for n, car in court.get("careers", {}).items():
            person(n, "court.json 的仕途")
            person(car.get("superior"), f"court.json 里 {n} 的上司")
            if not -3 <= int(car.get("regard", 0)) <= 3:
                rep.bad(f"court.json：{n} 的器重应为 −3..3")
        for n, v in court.get("out", {}).items():
            if v.get("status") not in C0.OUT_STATUS:
                rep.bad(f"court.json：{n} 的 out.status 应为 {'/'.join(C0.OUT_STATUS)}")
        if sc.get("player", {}).get("role") == "臣子" and sc.get("player", {}).get("protagonist") not in court.get("careers", {}):
            rep.warn("主角是臣子，但 court.json 的 careers 里没有他（官职、上司、器重）")
        rep.good(f"朝廷：{len(facs)} 派，{len(court.get('offices', {}))} 个官职，{len(court.get('issues', {}))} 个议题")
    # 流言与文献
    if rumors:
        cs = rumors.get("circles") or X.DEFAULT_CIRCLES
        for c, v in cs.items():
            if v.get("fame") and v["fame"] not in kinds:
                rep.bad(f"rumors.json：圈子 {c} 的名望种类“{v['fame']}”不在 fame_kinds 里")
            for c2, L_ in v.get("links", {}).items():
                if c2 not in cs:
                    rep.bad(f"rumors.json：圈子 {c} 连到不存在的圈子 {c2}")
                if not 0 <= float(L_) <= 1:
                    rep.bad(f"rumors.json：圈子 {c}→{c2} 的往来应为 0–1")
        for n, lst in rumors.get("members", {}).items():
            for c in lst:
                if c not in cs:
                    rep.bad(f"rumors.json：{n} 所在的圈子 {c} 不存在")
        for r in rumors.get("rumors", []):
            tag = f"rumors.json 流言 {r.get('id')}"
            if r.get("truth") not in ("真", "假", "半真"):
                rep.bad(f"{tag} 的 truth 应为 真/假/半真")
            if not 0 <= int(r.get("cred", 0)) <= 5:
                rep.bad(f"{tag} 的可信度应为 0–5")
            for c, h in r.get("heat", {}).items():
                if c not in cs:
                    rep.bad(f"{tag} 在不存在的圈子 {c} 里流传")
                if not 0 <= int(h) <= 5:
                    rep.bad(f"{tag} 在 {c} 的热度应为 0–5")
            for n, eff in (r.get("effects") or {}).items():
                for k in eff:
                    if k not in kinds:
                        rep.bad(f"{tag} 的名望影响“{k}”不是名望的种类")
        for d in rumors.get("docs", []):
            for c, h in d.get("reach", {}).items():
                if c not in cs:
                    rep.bad(f"rumors.json 文献 {d.get('id')} 流布到不存在的圈子 {c}")
        rep.good(f"流言：{len(cs)} 个圈子，{len(rumors.get('rumors', []))} 条流言，{len(rumors.get('docs', []))} 部文献")
    # 秘密
    sec = load_json(os.path.join(world, "secrets.json"), rep, required=False)
    if sec is not None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("game_secrets", os.path.join(HERE, "secrets.py"))
        SE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(SE)
        rids = {r.get("id") for r in rumors.get("rumors", [])} if rumors else set()
        for s_ in sec.get("secrets", []):
            tag = f"secrets.json 秘密 {s_.get('id')}"
            for k in s_.get("knowers", []):
                if k.get("depth") not in SE.DEPTHS:
                    rep.bad(f"{tag} 里 {k.get('name')} 的 depth 应为 {'/'.join(SE.DEPTHS)}")
                person(k.get("name"), tag)
            for e in s_.get("evidence", []):
                if e.get("kind") not in SE.EV_KINDS or e.get("status") not in SE.EV_STATUS:
                    rep.bad(f"{tag} 的证据 {e.get('id')} 种类或状态不对")
            if s_.get("rumor") and s_["rumor"] not in rids:
                rep.bad(f"{tag} 说泄成了流言 {s_['rumor']}，rumors.json 里没有")
            if int(s_.get("danger", 2)) not in (1, 2, 3):
                rep.bad(f"{tag} 的 danger 应为 1–3")
        rep.good(f"秘密：{len(sec.get('secrets', []))} 条")
    # 别的家宅
    for hp in hfiles:
        hh = load_json(hp, rep) or {}
        b = os.path.basename(hp)
        if hh.get("kind") not in ("palace", "clan"):
            rep.bad(f"households/{b} 的 kind 应为 palace 或 clan")
        ms = hh.get("members", {})
        if hh.get("head") and hh["head"] not in ms:
            rep.bad(f"households/{b} 的 head {hh['head']} 不在 members 里")
        for mid, m in ms.items():
            try:
                int(m.get("born"))
            except (TypeError, ValueError):
                rep.bad(f"households/{b} 里 {mid} 的 born 不是年份")
            c = m.get("card")
            if c and not os.path.exists(card_file(base, c)):
                rep.bad(f"households/{b} 里 {mid}（{m.get('name')}）的卡 {c} 不存在")
            if "favor" in m and not 0 <= int(m["favor"]) <= 3:
                rep.bad(f"households/{b} 里 {mid} 的宠爱应为 0–3")
            il = m.get("illness")
            if il:
                st = il.get("stages") or ["隐疾", "时发", "沉疴", "弥留"]
                if not 0 <= int(il.get("stage", 0)) < len(st):
                    rep.bad(f"households/{b} 里 {mid} 的病程档位超出 0–{len(st) - 1}")
            if m.get("mother") and m["mother"] not in ms:
                rep.warn(f"households/{b} 里 {mid} 的 mother {m['mother']} 不在这一家")
        for cl, v in hh.get("clans", {}).items():
            if v.get("faction") and court is not None and v["faction"] not in court.get("factions", {}):
                rep.bad(f"households/{b} 的外戚 {cl} 属的派系 {v['faction']} 不在 court.json 里")
        rep.good(f"家宅 {b}：{hh.get('title', '')}（{hh.get('kind')}），{len(ms)} 人")


# ---------------------------------------------------------------- 场景、件数、个人钱物

def check_scene_purse(base, world, rep, sc):
    who = known_people(base, world)
    # scenario.json 的 scene、actions、purse
    scn = sc.get("scene") or {}
    if scn:
        import scene as SCN
        cf = scn.get("curfew") or {}
        for k in ("from", "to"):
            if cf and not cf.get(k):
                rep.bad(f"scenario.json 的 scene.curfew 缺 {k}（夜禁从几时到几时，写成 戌初、寅正）")
        for k, v in list(cf.items()) + list((scn.get("drums") or {}).items()):
            if k in ("from", "to") or k in (scn.get("drums") or {}):
                try:
                    SCN.t_index(v)
                except SystemExit:
                    rep.bad(f"scenario.json 的 scene 里时辰看不懂：{k}={v!r}（写成 戌初、寅正、五更）")
        for season, lst in (scn.get("weather") or {}).items():
            if season not in S.STD_SEASONS or not isinstance(lst, list):
                rep.bad(f"scenario.json 的 scene.weather 要写成 {{春: [天气, …]}}：{season}")
        if cf:
            rep.good(f"场景：{cf.get('name', '夜禁')} {cf.get('from')}–{cf.get('to')}")
    act = sc.get("actions") or {}
    for k in ("cap_peace", "cap_busy"):
        if k in act and not (isinstance(act[k], int) and 1 <= act[k] <= 6):
            rep.bad(f"scenario.json 的 actions.{k} 应为 1–6 的整数：{act[k]!r}")
    pc = sc.get("purse") or {}
    if pc:
        if not isinstance(pc.get("per_big", 1), int) or int(pc.get("per_big", 1)) < 1:
            rep.bad("scenario.json 的 purse.per_big 应为正整数（一大单位合多少小单位）")
        if int(pc.get("per_big", 1)) > 1 and not (pc.get("unit") and pc.get("big_unit")):
            rep.bad("scenario.json 的 purse 分大小单位时要写 unit（小单位）和 big_unit（大单位）")
    # purse.json
    pu = load_json(os.path.join(world, "purse.json"), rep, required=False)
    if pu is not None:
        ids = set()
        hero = (sc.get("player") or {}).get("protagonist")
        for name, p in (pu.get("people") or {}).items():
            if name not in who:
                rep.warn(f"purse.json 里的 {name} 不在人格卡、名册、家宅里")
            for k in ("cash", "living"):
                if not isinstance(p.get(k, 0), int) or p.get(k, 0) < 0:
                    rep.bad(f"purse.json：{name} 的 {k} 应为非负整数（小单位）")
            if p.get("home") and name == hero and (sc.get("player") or {}).get("role") == "臣子":
                rep.warn(f"purse.json：主角 {name} 的家当记在 kingdom.json 的 treasury.money，purse.json 里的 home 不算")
            for it in p.get("items", []):
                iid = it.get("id")
                if iid in ids:
                    rep.bad(f"purse.json：物件编号 {iid} 重复")
                ids.add(iid)
                if it.get("kind") not in ("兵器", "马", "衣甲", "物件", "文书"):
                    rep.bad(f"purse.json：物件 {iid} 的 kind 应为 兵器/马/衣甲/物件/文书：{it.get('kind')!r}")
                if it.get("status", "在") not in ("在", "当了", "卖了", "送人", "失", "毁"):
                    rep.bad(f"purse.json：物件 {iid} 的 status 不对：{it.get('status')!r}")
                if not isinstance(it.get("story", []), list):
                    rep.bad(f"purse.json：物件 {iid} 的 story 应为列表（一段一段的来历）")
        sec = load_json(os.path.join(world, "secrets.json"), Report(), required=False) or {}
        sids = {x.get("id") for x in sec.get("secrets", [])}
        for name, p in (pu.get("people") or {}).items():
            for it in p.get("items", []):
                if it.get("secret") and it["secret"] not in sids:
                    rep.bad(f"purse.json：物件 {it.get('id')} 连着秘密 {it['secret']}，secrets.json 里没有")
        nums = [int(str(i)[1:]) for i in ids if str(i)[1:].isdigit()]
        if nums and int((pu.get("next") or {}).get("I", 1)) <= max(nums):
            rep.bad("purse.json 的 next.I 不比已有的物件编号大")
        for x in pu.get("debts", []):
            if x.get("status") not in ("未还", "已还", "赖账", "免了"):
                rep.bad(f"purse.json：借据 {x.get('id')} 的 status 不对")
        rep.good(f"个人钱物：{len(pu.get('people', {}))} 人，{len(ids)} 件物件，{len(pu.get('debts', []))} 张借据")
    # court.json 的仕途阶梯
    court = load_json(os.path.join(world, "court.json"), Report(), required=False)
    if court:
        lads = court.get("ladders") or {}
        for lname, lad in lads.items():
            posts = set()
            for r in lad.get("rungs", []):
                if not r.get("post"):
                    rep.bad(f"court.json：阶梯 {lname} 有一阶没写 post")
                    continue
                if r["post"] in posts:
                    rep.bad(f"court.json：阶梯 {lname} 的 {r['post']} 写了两回")
                posts.add(r["post"])
                if r.get("rank") is not None and not (isinstance(r["rank"], int) and 1 <= r["rank"] <= 9):
                    rep.bad(f"court.json：阶梯 {lname} 的 {r['post']} 品级应为 1–9 或 null（流外）")
                if r.get("pay") is not None and not isinstance(r["pay"], (int, float)):
                    rep.bad(f"court.json：阶梯 {lname} 的 {r['post']} 俸钱应为数")
                if r.get("office") and r["post"] not in court.get("offices", {}):
                    rep.bad(f"court.json：阶梯 {lname} 的 {r['post']} 标着 office，官职表里却没有这个位子")
        for n, car in court.get("careers", {}).items():
            ln = car.get("ladder")
            if ln:
                if ln not in lads:
                    rep.bad(f"court.json：{n} 的仕途阶梯 {ln} 不在 ladders 里")
                elif car.get("post") not in {r.get("post") for r in lads[ln].get("rungs", [])}:
                    rep.warn(f"court.json：{n} 眼下的职 {car.get('post')} 不在阶梯 {ln} 上（借调、外放的可以不管）")
        if lads:
            desc = "、".join(f"{k}（{len(v.get('rungs', []))} 阶）" for k, v in lads.items())
            rep.good(f"仕途阶梯：{desc}")
    # scenes.json、actions.json（开局后才有）
    scn_d = load_json(os.path.join(world, "scenes.json"), rep, required=False)
    if scn_d and scn_d.get("current"):
        rep.warn(f"scenes.json 里还开着场景 {scn_d['current'].get('id')}“{scn_d['current'].get('title')}”：季末之前要 close 或 cancel")
    act_d = load_json(os.path.join(world, "actions.json"), rep, required=False)
    if act_d:
        for t, v in (act_d.get("turns") or {}).items():
            if v.get("mode") not in ("太平", "事多"):
                rep.bad(f"actions.json 第 {t} 回合的 mode 应为 太平 或 事多")


# ---------------------------------------------------------------- 主程序

def locate(target):
    """返回 (base, world, scenario.json 路径, 是否剧本包)。"""
    t = os.path.abspath(target)
    if os.path.exists(os.path.join(t, "scenario.json")) and os.path.isdir(os.path.join(t, "world")):
        return t, os.path.join(t, "world"), os.path.join(t, "scenario.json"), True
    if os.path.exists(os.path.join(t, "kingdom.json")) or os.path.basename(t) == "world":
        return os.path.dirname(t), t, os.path.join(t, "scenario.json"), False
    if os.path.isdir(os.path.join(t, "world")):
        return t, os.path.join(t, "world"), os.path.join(t, "scenario.json"), True
    sys.exit(f"错误：{target} 既不是剧本包（scenario.json + world/），也不是存档目录（kingdom.json）")


def run(target):
    base, world, sc_path, package = locate(target)
    rep = Report()
    sc = load_json(sc_path, rep) or {}
    if not sc and not package:
        rep.problems[-1:] = [f"缺 {sc_path}：开局时要把剧本的 scenario.json 复制进来（旧存档没有它，脚本退回读 economy.json 和 household.json）"]
    if sc:
        check_scenario(sc, base, rep, package)
    regions = ((load_json(os.path.join(world, "map.json"), rep) or {}).get("regions")) or {}
    armies = ((load_json(os.path.join(world, "armies.json"), rep) or {}).get("armies")) or {}
    factions = ((load_json(os.path.join(world, "factions.json"), rep) or {}).get("factions")) or {}
    kingdom = load_json(os.path.join(world, "kingdom.json"), rep)
    eco = load_json(os.path.join(world, "economy.json"), rep)
    hh = load_json(os.path.join(world, "household.json"), rep, required=False)
    d = load_json(os.path.join(world, "directives.json"), rep, required=False)
    own = sc.get("player", {}).get("faction") or (eco or {}).get("own_faction")
    scen_units = [u.get("code") for u in sc.get("units", []) if isinstance(u, dict)]

    check_map(regions, rep)
    check_armies(armies, regions, factions, eco, rep, own, scen_units)
    check_factions(factions, regions, base, rep, own, vassal=sc.get("player", {}).get("role") == "臣子")
    check_cards(base, rep)
    check_persona(base, world, rep, sc, package)
    check_household(hh, regions, base, rep, sc)
    check_directives(d, regions, armies, rep)
    check_consistency(sc, kingdom, eco, regions, rep)
    check_features(sc, eco, regions, base, rep, package)
    if sc or hh:
        check_calendar(sc, world, kingdom, hh, rep)
    check_social(base, world, rep, sc)
    check_scene_purse(base, world, rep, sc)

    title = f"{sc.get('name', '')}（{sc.get('id', os.path.basename(base))}）" if sc else world
    print(f"=== 剧本校验：{title} ===")
    print(f"  {'剧本包' if package else '存档'}：{base if package else world}")
    for x in rep.ok:
        print(f"  · {x}")
    if rep.problems:
        print(f"\n问题清单（{len(rep.problems)} 条，要改）：")
        for i, x in enumerate(rep.problems, 1):
            print(f"  {i}. {x}")
    if rep.notes:
        print(f"\n提醒（{len(rep.notes)} 条，可以不改）：")
        for x in rep.notes:
            print(f"  - {x}")
    print("\n结果：" + ("通过" if not rep.problems else "未通过"))
    return 0 if not rep.problems else 1


def main():
    ap = argparse.ArgumentParser(description="剧本包校验（只读）", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("target", nargs="?", default=os.path.join(ROOT, "world"),
                    help="剧本包目录（scenarios/<剧本名>）或存档目录（world/）")
    args = ap.parse_args()
    sys.exit(run(args.target))


if __name__ == "__main__":
    main()
