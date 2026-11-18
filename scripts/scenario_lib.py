#!/usr/bin/env python3
"""剧本元数据的读取（各脚本共用）。只用标准库。

剧本包的格式见 scenarios/README.md。开新局时 scenario.json 复制到 world/scenario.json，
脚本从那里读己方势力名、治所、纪年、称谓。

查找顺序：
  1. <存档目录>/scenario.json            （开局后的 world/scenario.json）
  2. <存档目录的上一级>/scenario.json      （直接拿剧本包 scenarios/<名>/world 试算时）
找不到 scenario.json 时，只对旧存档做兼容：己方势力名读 economy.json 的 own_faction，
治所读 kingdom.json 的 player.seat，纪年读 household.json 的 calendar。都没有就报错，不猜。
"""
import json
import os
import sys

TIANGAN = "甲乙丙丁戊己庚辛壬癸"
DIZHI = "子丑寅卯辰巳午未申酉戌亥"
CN = "〇一二三四五六七八九"
STD_SEASONS = ["春", "夏", "秋", "冬"]

# 称谓表缺项时的中性说法（不带任何剧本的专名）
NEUTRAL_TERMS = {
    "sovereign": "天子",
    "ruler": "主公",
    "lord_address": "主公",
    "regional_commander": "方面大将",
    "local_official": "地方长官",
    "region_unit": "地区",
    "army_unit": "军",
    "hq": "帅府",
    "court": "朝廷",
    "money_unit": "贯",
    "grain_unit": "石",
    "horse_unit": "匹",
}

_cache = {}


def die(msg):
    sys.exit(f"错误：{msg}")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find(world_dir):
    """返回 scenario.json 的路径，找不到返回 None。"""
    world_dir = os.path.abspath(world_dir)
    for cand in (os.path.join(world_dir, "scenario.json"),
                 os.path.join(os.path.dirname(world_dir), "scenario.json")):
        if os.path.exists(cand):
            return cand
    return None


def load(world_dir):
    """读剧本元数据；没有就返回 {}。"""
    path = find(world_dir)
    if not path:
        return {}
    if path not in _cache:
        try:
            _cache[path] = _read_json(path)
        except ValueError as e:
            die(f"{path} 不是合法的 JSON：{e}")
    return _cache[path]


def _world_json(world_dir, name):
    p = os.path.join(world_dir, name)
    if not os.path.exists(p):
        return {}
    try:
        return _read_json(p)
    except ValueError:
        return {}


def own_faction(world_dir, eco=None):
    """己方势力名：scenario.json 的 player.faction；旧存档读 economy.json 的 own_faction。"""
    sc = load(world_dir)
    name = sc.get("player", {}).get("faction")
    if name:
        return name
    eco = eco if eco is not None else _world_json(world_dir, "economy.json")
    if eco.get("own_faction"):
        return eco["own_faction"]
    die(f"不知道己方势力叫什么：{world_dir} 里没有 scenario.json（player.faction），"
        "economy.json 里也没有 own_faction。新局请从 scenarios/<剧本>/ 铺开，会带上 scenario.json。")


def army_prefix(world_dir, eco=None):
    """军队 faction 以这个名字开头就算己方（如“某某（归附）”）。旧存档可在 economy.json 写 army_faction_prefix。"""
    eco = eco if eco is not None else _world_json(world_dir, "economy.json")
    return eco.get("army_faction_prefix") or own_faction(world_dir, eco)


def seat(world_dir, kingdom=None, directives=None):
    """主角治所：directives.json 的 council.seat → kingdom.json 的 player.seat → scenario.json 的 player.seat。"""
    d = directives if directives is not None else _world_json(world_dir, "directives.json")
    s = (d or {}).get("council", {}).get("seat")
    if s:
        return s
    k = kingdom if kingdom is not None else _world_json(world_dir, "kingdom.json")
    s = (k or {}).get("player", {}).get("seat")
    if s:
        return s
    s = load(world_dir).get("player", {}).get("seat")
    if s:
        return s
    die(f"不知道治所在哪里：{world_dir} 的 kingdom.json 没有 player.seat，scenario.json 也没有 player.seat。")


def term(world_dir, key):
    """称谓：scenario.json 的 terms，缺项用中性说法。"""
    t = load(world_dir).get("terms", {})
    v = t.get(key)
    if isinstance(v, dict):  # 允许写成 {"name": ..., "note": ...}
        v = v.get("name")
    return v or NEUTRAL_TERMS.get(key, key)


def seasons(world_dir):
    return list(load(world_dir).get("turn_unit", {}).get("seasons") or STD_SEASONS)


def flavor(world_dir, key):
    """剧本给的见闻素材（季节细节、新面孔、去处）；没有返回 None。"""
    return load(world_dir).get("flavor", {}).get(key)


# ---------- 纪年 ----------

def calendar(world_dir, household=None):
    """纪年设置。household.json 里有 calendar 的（旧存档）优先，其次 scenario.json。

    返回 {"style": 年号|干支|公元, "turn1_year", "turn1_season", "eras": [...]}。
    """
    hh = household if household is not None else _world_json(world_dir, "household.json")
    cal = dict((hh or {}).get("calendar") or {})
    sc = load(world_dir)
    scal = sc.get("calendar") or {}
    start = sc.get("start") or {}
    for k, v in scal.items():
        cal.setdefault(k, v)
    cal.setdefault("turn1_year", start.get("year"))
    cal.setdefault("turn1_season", start.get("season"))
    if not cal.get("style"):
        cal["style"] = "年号" if cal.get("eras") else None
    if cal.get("turn1_year") is None or not cal.get("style"):
        die(f"不知道纪年：{world_dir} 里没有 scenario.json 的 calendar / start.year，"
            "household.json 里也没有 calendar。新局请从 scenarios/<剧本>/ 铺开。")
    cal.setdefault("turn1_season", STD_SEASONS[0])
    return cal


def cn_num(n):
    if n <= 10:
        return "十" if n == 10 else CN[n]
    if n < 20:
        return "十" + (CN[n - 10] if n > 10 else "")
    if n < 100:
        t, u = divmod(n, 10)
        return CN[t] + "十" + (CN[u] if u else "")
    return str(n)


def ganzhi(year):
    """公元年（负数为公元前，没有 0 年）对应的干支。"""
    y = year if year > 0 else year + 1  # 天文纪年：公元前 1 年 = 0
    i = (y - 4) % 60
    return TIANGAN[i % 10] + DIZHI[i % 12]


def gregorian(year):
    return f"公元{year}年" if year > 0 else f"公元前{-year}年"


def year_label(cal, year):
    style = cal.get("style", "年号")
    if style == "公元":
        return gregorian(year)
    if style == "干支":
        prefix = ""
        if cal.get("eras"):
            prefix = era_only(cal, year) or ""
        return f"{prefix}{ganzhi(year)}年"
    return era_only(cal, year, with_year=True) or gregorian(year)


def era_only(cal, year, with_year=False):
    name, start = None, None
    for e in sorted(cal.get("eras") or [], key=lambda e: e["from"]):
        if year >= e["from"]:
            name, start = e["name"], e["from"]
    if name is None:
        return None
    if not with_year:
        return name
    n = year - start + 1
    return f"{name}{'元' if n == 1 else cn_num(n)}年"


def era_covers(cal, year):
    """年号表能不能写出这一年（干支、公元总能写）。"""
    if cal.get("style") in ("干支", "公元"):
        return True
    return era_only(cal, year) is not None
