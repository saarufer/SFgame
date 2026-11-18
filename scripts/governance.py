#!/usr/bin/env python3
"""分层托管：亲领、委任、羁縻。规则见 rules/governance.md，存档见 world/directives.json。

  查看     show
  委任     delegate 方面 --holder 名 --card 卡片 --regions 地区,地区 --armies 军,军 [方针参数] [--grant 钱,粮]
  改方针   directive 方面 [方针参数]
  季结     season --season 季 [--war 地区,地区] [--seed N]
  收回     recall 方面 --mode 入朝|夺权 [--post 新职]
  轮换     rotate 方面 --holder 新人 --card 新卡
  亲裁     council [--assign 幕僚 --task 事由 --kind 内政|军务|外交|人事] [--seed N]

方针参数：--posture 攻|守|养  --refill 0.8  --latitude 严|中|宽  --money N --grain N --horses N
          --tribute 0.3  --term 季数  --seat 治所  --words "方针原话"
          --report 缺员=0.3,士气=60,敌军=3000,粮季=1

会改存档的命令默认只打印；加 --apply 才写回。--world 指向别的存档目录（试验用）。
本脚本不写 kingdom.json 的府库：上供、请拨记进 directives.json 的 last_settlement，
由 economy.py 结算时一并计入。人心账本的改动（权柄、部曲、心结）直接写人格卡。
"""
import argparse
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import loyalty  # noqa: E402
import scenario_lib as S  # noqa: E402

SEASONS = ("春", "夏", "秋", "冬")
UNIT_NAMES = {"infantry": "步", "cavalry": "骑", "archer": "弓", "militia": "民兵"}
POSTURES = ("攻", "守", "养")
TIERS = ("严", "中", "宽")

DEFAULT_GOV = {
    "decay_free_steps": 2,          # 离帅府（或方面治所）几程以内不衰减
    "decay_per_step": 0.05,         # 再远一程，钱粮少收 5%
    "scale_free_regions": 8,        # 亲领州数在此以内不衰减
    "scale_decay_per_region": 0.01, # 亲领州数每多一州，各亲领州再少收 1%
    "decay_floor": 0.6,             # 最多打到六折
    "recruit_cap_per_region": 800,  # 委任方面每州每季最多募兵
    "recruit_cost_per_1000": {"infantry": 1500, "cavalry": 4000, "archer": 2000, "militia": 800},
    "horses_per_1000_cavalry": 1000,
    "train_cost_per_1000": 100,     # 姿态“养”的练兵费
    "deviation_per_step": 2,        # 方面治所离帅府每多一程（超出免衰减的程数），拖延、变通各 +2 个百分点
    "council_base": 3,              # 帅府每季亲裁的基数
    "council_max_bonus": 3,         # 幕僚最多再加几件
    "council_staff_min": 6,         # 能力几以上的幕僚才算一件
}
DEFAULT_REPORT = {"缺员": 0.3, "士气": 60, "敌军": 3000, "粮季": 1}


def die(msg):
    sys.exit(f"错误：{msg}")


def split_list(s):
    if not s:
        return []
    return [x.strip() for x in s.replace("，", ",").replace("、", ",").split(",") if x.strip()]


# ---------- 存档 ----------

class World:
    def __init__(self, path):
        self.dir = path

    def p(self, name):
        return os.path.join(self.dir, name)

    def load(self, name, default=None):
        try:
            with open(self.p(name), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            if default is not None:
                return default
            die(f"找不到 {self.p(name)}")

    def save(self, name, data):
        with open(self.p(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def all(self):
        self.kingdom = self.load("kingdom.json")
        self.regions = self.load("map.json")["regions"]
        self.armies = self.load("armies.json")["armies"]
        self.eco = self.load("economy.json", {})
        self.factions = self.load("factions.json", {"factions": {}}).get("factions", {})
        self.d = self.load("directives.json", empty_directives())
        self.gov = dict(DEFAULT_GOV)
        self.gov.update({k: v for k, v in self.eco.get("governance", {}).items() if not k.startswith("说明")})
        return self


def empty_directives():
    return {"council": {}, "establishment": {}, "commands": {}, "loose": {}, "last_settlement": {}}


def seat_of(w):
    """治所：directives 的 council.seat → kingdom 的 player.seat → scenario.json。都没有就报错。"""
    return S.seat(w.dir, kingdom=w.kingdom, directives=w.d)


def bfs(regions, start):
    return loyalty.bfs(regions, start)


def own_faction(w):
    """己方势力名：scenario.json 的 player.faction（旧存档读 economy.json 的 own_faction）。"""
    return S.own_faction(w.dir, w.eco)


def is_own_army(w, arm):
    """军队的 faction 以己方势力名开头（如“某某（归附）”）就算己方。"""
    return str(arm.get("faction", "")).startswith(S.army_prefix(w.dir, w.eco))


def tier_maps(w):
    """返回 (州→(层级, 方面名), 军→(层级, 方面名))。不在委任、羁縻里的己方州、军都是亲领。"""
    rt, at = {}, {}
    for name, c in w.d.get("commands", {}).items():
        for r in c.get("regions", []):
            rt[r] = ("委任", name)
        for a in c.get("armies", []):
            at[a] = ("委任", name)
    for name, c in w.d.get("loose", {}).items():
        for r in c.get("regions", []):
            rt[r] = ("羁縻", name)
        for a in c.get("armies", []):
            at[a] = ("羁縻", name)
    own = own_faction(w)
    for r, info in w.regions.items():
        if info.get("owner") == own and r not in rt:
            rt[r] = ("亲领", None)
    for a, arm in w.armies.items():
        if is_own_army(w, arm) and a not in at:
            at[a] = ("亲领", None)
    return rt, at


def decay(w, region, origin, n_regions=0, scale=True):
    """政令系数：离 origin 越远、亲领州越多，收得越少。返回 (系数, 说明)。"""
    g = w.gov
    dist = bfs(w.regions, origin).get(region)
    notes, k = [], 1.0
    if dist is None:
        dist = 99
    over = max(dist - g["decay_free_steps"], 0)
    if over:
        k -= over * g["decay_per_step"]
        notes.append(f"距{origin}{dist}程")
    if scale:
        extra = max(n_regions - g["scale_free_regions"], 0)
        if extra:
            k -= extra * g["scale_decay_per_region"]
            notes.append(f"亲领{n_regions}{S.term(w.dir, 'region_unit')}")
    k = max(k, g["decay_floor"])
    return round(k, 2), "，".join(notes)


def units_total(units):
    return sum(v for v in units.values() if v)


def fmt_units(units):
    return " ".join(f"{UNIT_NAMES.get(u, u)}{n}" for u, n in units.items() if n)


def upkeep(w, units):
    rates = w.eco.get("upkeep_per_1000", {})
    m = g = 0.0
    for u, n in units.items():
        r = rates.get(u, {"grain": 900, "money": 300})
        m += n / 1000 * r["money"]
        g += n / 1000 * r["grain"]
    return m, g


def hostile_factions(w):
    out = []
    for k, f in w.factions.items():
        att = str(f.get("attitude_to_player", ""))
        if "敌" in att and "已灭" not in att:
            out.append(k.split("（")[0])
    out += w.d.get("hostile", [])
    return out


def is_hostile(w, arm):
    fac = str(arm.get("faction", ""))
    if fac.startswith(own_faction(w)):
        return False
    return any(fac.startswith(h) for h in hostile_factions(w))


def enemies_near(w, regions):
    """在这些州或相邻州里的敌军。按 armies.json 的 location 文字匹配州名。"""
    near = set(regions)
    for r in regions:
        near.update(w.regions.get(r, {}).get("adjacent", []))
    out = []
    for name, arm in w.armies.items():
        if not is_hostile(w, arm):
            continue
        loc = str(arm.get("location", ""))
        hit = [r for r in near if r in loc]
        if hit:
            out.append((name, arm, hit[0], hit[0] in regions))
    return out


# ---------- 方面结算 ----------

def card_path(cp):
    if not cp:
        return None
    return cp if os.path.isabs(cp) else os.path.join(ROOT, cp)


def open_card(c):
    p = card_path(c.get("card"))
    if p and os.path.exists(p):
        return loyalty.Card(p)
    return None


def settle_command(w, name, c, season, war, rng):
    """结算一个委任方面的一季。改 w.armies 和 c（内存里），返回明细 dict。"""
    g = w.gov
    d = c.setdefault("directive", {})
    rep = dict(DEFAULT_REPORT)
    rep.update(d.get("report", {}))
    lat = d.get("latitude", {"tier": "中", "money": 0, "grain": 0, "horses": 0})
    hq = c.get("seat") or (c.get("regions") or [seat_of(w)])[0]
    gm = w.eco.get("season_multiplier", {}).get("grain", {}).get(season, 1)
    mm = w.eco.get("season_multiplier", {}).get("money", {}).get(season, 1)
    wm = w.eco.get("war_multiplier", 0.5)
    own = own_faction(w)
    out = {"name": name, "holder": c.get("holder"), "lines": [], "exceptions": [], "gm": []}
    L, X = out["lines"].append, out["exceptions"].append
    treasury_draw = {"money": 0, "grain": 0, "horses": 0}

    # 1. 执行偏差
    card = open_card(c)
    seat = seat_of(w)
    dist = bfs(w.regions, seat).get(hq, 99)
    far = max(dist - g["decay_free_steps"], 0)
    seasons = max(w.kingdom.get("turn", 0) - int(c.get("since_turn", w.kingdom.get("turn", 0))), 0) + 1
    extra = far * g["deviation_per_step"]
    new_hand = 5 if seasons <= 1 else 0
    if card and card.role == "将领":
        probs = loyalty.daily_probs(card, d.get("posture") == "攻", extra + new_hand, extra)
        dev = loyalty.pick(probs, rng.uniform(0, 100))
        level = card.level
    else:
        probs, dev, level = {}, "照办", "—"
        out["gm"].append("没有人格卡，按“照办”结算。")
    out["deviation"] = dev
    out["probs"] = probs
    L(f"执行：{dev}（帅府到治所{hq} {dist} 程" + (f"，新官上任" if new_hand else "") + "）")

    # 2. 在途补员到营
    for a, units in c.pop("in_transit", {}).items():
        if a in w.armies:
            for u, n in units.items():
                w.armies[a].setdefault("units", {})[u] = w.armies[a]["units"].get(u, 0) + n
            L(f"上季所募到营：{a} {fmt_units(units)}")

    # 3. 收入（按方面治所算距离，不计帅府的亲领州数衰减）
    inc_m = inc_g = 0.0
    for r in c.get("regions", []):
        info = w.regions.get(r, {})
        if info.get("owner") != own:
            out["gm"].append(f"{r} 已不在我手，不计收入。")
            continue
        inc = info.get("income", {})
        m, gr = inc.get("money", 0) * mm, inc.get("grain", 0) * gm
        mod = w.eco.get("region_modifiers", {}).get(r, {})
        m *= mod.get("money", 1)
        gr *= mod.get("grain", 1)
        k, _ = decay(w, r, hq, scale=False)
        m, gr = m * k, gr * k
        if r in war:
            m, gr = m * wm, gr * wm
        inc_m += m
        inc_g += gr
    inc_m, inc_g = round(inc_m), round(inc_g)
    rate = float(d.get("tribute", 0.3))
    if dev == "变通":
        rate *= 0.8
    elif dev == "抗命":
        rate *= 0.5
    trib_m, trib_g = round(inc_m * rate), round(inc_g * rate)
    store = c.setdefault("store", {"money": 0, "grain": 0})
    store["money"] += inc_m - trib_m
    store["grain"] += inc_g - trib_g
    L(f"收入：钱 {inc_m}，粮 {inc_g}；上供 {rate:.0%}：钱 {trib_m}，粮 {trib_g}"
      + ("（变通，截留两成）" if dev == "变通" else "（抗命，上供减半）" if dev == "抗命" else ""))

    # 4. 粮饷
    um = ug = 0.0
    for a in c.get("armies", []):
        if a in w.armies:
            m, gr = upkeep(w, w.armies[a].get("units", {}))
            um += m
            ug += gr
    um, ug = round(um), round(ug)
    store["money"] -= um
    store["grain"] -= ug
    L(f"粮饷：钱 {um}，粮 {ug}")
    for k in ("money", "grain"):
        if store[k] < 0:
            treasury_draw[k] += -store[k]
            X(f"{name}库里{'钱' if k == 'money' else '粮'}不够发饷，府库代垫 {-store[k]}")
            store[k] = 0
    out["upkeep"] = (um, ug)

    # 5. 补员（在钱粮权限以内；先用方面库，不够再向府库请拨）
    budget = {"money": lat.get("money", 0), "grain": lat.get("grain", 0), "horses": lat.get("horses", 0)}
    target = float(d.get("refill", 0))
    if dev == "超额执行":
        target = min(target + 0.1, 1.0)
        budget["money"] = round(budget["money"] * 1.2)
    elif dev == "变通":
        target = max(target - 0.1, 0)
    cap_left = g["recruit_cap_per_region"] * len(c.get("regions", []))
    est = w.d.setdefault("establishment", {})
    spent = 0
    transit = {}
    if dev in ("拖延", "抗命") or target <= 0:
        if target > 0:
            L(f"补员：本季未办（{dev}）")
    else:
        costs = g["recruit_cost_per_1000"]
        for a in c.get("armies", []):
            if a not in w.armies or a not in est:
                continue
            have = w.armies[a].get("units", {})
            for u, full in est[a].items():
                want = math.floor(full * target) - have.get(u, 0)
                if want <= 0 or cap_left <= 0:
                    continue
                n = min(want, cap_left)
                if u == "cavalry":
                    horses_ok = budget["horses"] * 1000 // g["horses_per_1000_cavalry"]
                    if n > horses_ok:
                        X(f"{a} 骑兵缺 {want}，钱粮权限里马匹不够（可用 {budget['horses']} 匹），待帅府拨马")
                        n = horses_ok
                cost_each = costs.get(u, 1500) / 1000
                afford = int((budget["money"] - spent) // cost_each) if cost_each else n
                n = max(min(n, afford), 0)
                if n <= 0:
                    continue
                n = (n // 50) * 50 or n
                cost = round(n * cost_each)
                spent += cost
                cap_left -= n
                if u == "cavalry":
                    hneed = math.ceil(n * g["horses_per_1000_cavalry"] / 1000)
                    budget["horses"] -= hneed
                    treasury_draw["horses"] += hneed
                transit.setdefault(a, {})[u] = transit.get(a, {}).get(u, 0) + n
        if transit:
            c["in_transit"] = transit
            L("补员：募 " + "；".join(f"{a} {fmt_units(us)}" for a, us in transit.items())
              + f"，花钱 {spent}，下季到营")
    # 6. 练兵
    posture = d.get("posture", "守")
    train = 0
    for a in c.get("armies", []):
        if a not in w.armies:
            continue
        arm = w.armies[a]
        mo = arm.get("morale", 70)
        if posture == "养" and dev not in ("拖延", "抗命"):
            fee = round(units_total(arm.get("units", {})) / 1000 * g["train_cost_per_1000"])
            if spent + train + fee <= budget["money"]:
                train += fee
                arm["morale"] = min(mo + 5, 90) if mo < 90 else mo
        elif posture == "守" and mo < 80:
            arm["morale"] = min(mo + 2, 80)
        elif posture == "攻":
            arm["morale"] = max(mo - 2, 0)
    if train:
        L(f"练兵：花钱 {train}")
    # 钱从方面库出，不够的向府库请拨（仍在权限以内）
    pay = spent + train
    from_store = min(store["money"], pay)
    store["money"] -= from_store
    if pay - from_store:
        treasury_draw["money"] += pay - from_store
        L(f"方面库不够，向府库请拨钱 {pay - from_store}")
    out["draw"] = treasury_draw
    out["tribute"] = {"money": trib_m, "grain": trib_g}

    # 7. 例外
    for a in c.get("armies", []):
        if a not in w.armies:
            X(f"{a} 不在 armies.json 里（已撤编或改名？）")
            continue
        arm = w.armies[a]
        full = units_total(est.get(a, {}))
        have = units_total(arm.get("units", {}))
        if full and have / full < 1 - rep["缺员"]:
            X(f"{a} 缺员 {1 - have / full:.0%}（{have}/{full}）")
        if arm.get("morale", 100) < rep["士气"]:
            X(f"{a} 士气 {arm['morale']}")
    seasons_food = store["grain"] / ug if ug else 99
    if seasons_food < rep["粮季"]:
        X(f"{name}库粮只够 {seasons_food:.1f} 季")
    for en, arm, where, inside in enemies_near(w, c.get("regions", [])):
        n = units_total(arm.get("units", {}))
        if n >= rep["敌军"]:
            X(f"敌军{'入境' if inside else '压境'}：{en} 约 {n} 人在{arm.get('location')}")
    if dev == "抗命":
        X(f"{c.get('holder')} 本季未照方针行事")
    if card and card.role == "将领":
        prev = c.get("seen_grudges", [])
        new = [gg for gg in card.active() if gg["id"] not in prev]
        if new:
            out["gm"].append("新添或未见过的未解心结：" + "；".join(f"[{gg['id']}]{gg['what']}" for gg in new))
            for gg in new:
                if gg["heard"] != "不外传":
                    X(f"幕僚听说：{c.get('holder')}为“{gg['what']}”一事心里不痛快")
        c["seen_grudges"] = [gg["id"] for gg in card.active()]
        if loyalty.LEVELS.index(level) >= 2:
            out["gm"].append(f"{c.get('holder')} 离心“{level}”：按 rules/loyalty.md 择迹象透露，不直接报。")
        out["gm"].append(f"部曲 {loyalty.card_corps(card)}（起点 {c.get('corps_start', '?')}）")
    if dev in ("超额执行", "变通", "抗命"):
        out["gm"].append(f"执行偏差“{dev}”：可召 general agent 让{c.get('holder')}回禀缘由（见 rules/governance.md 第四节）。")
    term = c.get("term")
    if term and seasons >= int(term):
        X(f"{c.get('holder')}任期已满（{seasons}/{term} 季），可按期轮换")
    c.setdefault("log", []).append(
        f"{w.kingdom.get('date', '')}：{dev}；上供钱{trib_m}粮{trib_g}；补员花钱{spent}；库 钱{store['money']} 粮{store['grain']}")
    c["log"] = c["log"][-12:]
    return out


def cmd_season(w, args):
    war = split_list(args.war)
    rng = random.Random(args.seed)
    cmds = w.d.get("commands", {})
    if not cmds:
        print("没有委任的方面，无需结算。")
        return
    tot = {"tribute": {"money": 0, "grain": 0}, "draw": {"money": 0, "grain": 0, "horses": 0}}
    devs, results = {}, []
    print(f"=== 委任方面季结：{w.kingdom.get('date', '')}（{args.season}季） ===")
    for name, c in cmds.items():
        r = settle_command(w, name, c, args.season, war, rng)
        results.append(r)
        devs[name] = r["deviation"]
        for k in tot["tribute"]:
            tot["tribute"][k] += r["tribute"][k]
        for k in tot["draw"]:
            tot["draw"][k] += r["draw"][k]
        print(f"\n【{name}】{c.get('holder')}  方针：{c.get('directive', {}).get('posture', '守')}"
              f"，补员到{c.get('directive', {}).get('refill', 0):.0%}，权限{c.get('directive', {}).get('latitude', {}).get('tier', '中')}")
        for l in r["lines"]:
            print(f"  {l}")
        print(f"  方面库：钱 {c['store']['money']}，粮 {c['store']['grain']}")
        for x in r["exceptions"]:
            print(f"  ！例外：{x}")
        for x in r["gm"]:
            print(f"  （GM）{x}")
    print(f"\n合计上供：钱 {tot['tribute']['money']}，粮 {tot['tribute']['grain']}；"
          f"请拨／代垫：钱 {tot['draw']['money']}，粮 {tot['draw']['grain']}，马 {tot['draw']['horses']}")
    print("（上供和请拨由 economy.py 计入府库。）")
    w.d["last_settlement"] = {
        "turn": w.kingdom.get("turn"), "date": w.kingdom.get("date"), "season": args.season,
        "tribute": tot["tribute"], "draw": tot["draw"], "deviation": devs,
        "exceptions": {r["name"]: r["exceptions"] for r in results if r["exceptions"]},
    }
    if not args.apply:
        print("\n（未写存档。确认无误后加 --apply。）")
        return
    last = w.load("directives.json", empty_directives()).get("last_settlement", {})
    if last.get("turn") == w.kingdom.get("turn") and not args.force:
        die(f"第 {w.kingdom.get('turn')} 回合的委任方面已经结算过。确需重算加 --force。")
    w.save("directives.json", w.d)
    arm_doc = w.load("armies.json")
    arm_doc["armies"] = w.armies
    w.save("armies.json", arm_doc)
    print(f"\n已写入 {w.p('directives.json')}、{w.p('armies.json')}。")


# ---------- 委任、改方针、收回、轮换 ----------

def directive_from_args(args, base=None):
    d = dict(base or {"posture": "守", "refill": 0.8, "tribute": 0.3,
                      "latitude": {"tier": "中", "money": 2000, "grain": 0, "horses": 0},
                      "report": dict(DEFAULT_REPORT)})
    d["latitude"] = dict(d.get("latitude", {}))
    if args.posture:
        d["posture"] = args.posture
    if args.refill is not None:
        d["refill"] = args.refill
    if args.tribute is not None:
        d["tribute"] = args.tribute
    if args.latitude:
        d["latitude"]["tier"] = args.latitude
    for k in ("money", "grain", "horses"):
        v = getattr(args, k)
        if v is not None:
            d["latitude"][k] = v
    if args.report:
        rep = dict(d.get("report", DEFAULT_REPORT))
        for tok in split_list(args.report):
            k, v = tok.split("=", 1)
            rep[k] = float(v) if "." in v else int(v)
        d["report"] = rep
    if args.words:
        d["words"] = args.words
    return d


def cmd_delegate(w, args):
    cmds = w.d.setdefault("commands", {})
    if args.name in cmds:
        die(f"方面“{args.name}”已经存在。改方针用 directive，换人用 rotate")
    regions, armies = split_list(args.regions), split_list(args.armies)
    rt, at = tier_maps(w)
    for r in regions:
        if r not in w.regions:
            die(f"{r} 不在 map.json 里")
        if rt.get(r, ("亲领",))[0] != "亲领":
            die(f"{r} 已属{rt[r][0]}“{rt[r][1]}”，先收回")
    for a in armies:
        if a not in w.armies:
            die(f"{a} 不在 armies.json 里")
        if at.get(a, ("亲领",))[0] != "亲领":
            die(f"{a} 已属{at[a][0]}“{at[a][1]}”，先收回")
    card = loyalty.Card(card_path(args.card)) if args.card else None
    grant = [int(x) for x in split_list(args.grant)] if args.grant else [0, 0]
    est = w.d.setdefault("establishment", {})
    for a in armies:
        est.setdefault(a, dict(w.armies[a].get("units", {})))
    c = {
        "holder": args.holder, "card": args.card, "seat": args.seat or (regions[0] if regions else None),
        "regions": regions, "armies": armies, "since_turn": w.kingdom.get("turn"), "term": args.term,
        "corps_start": loyalty.card_corps(card) if card else None,
        "directive": directive_from_args(args),
        "store": {"money": grant[0], "grain": grant[1] if len(grant) > 1 else 0},
        "log": [f"{w.kingdom.get('date', '')}：委任{args.holder}"],
    }
    if card:
        c["seen_grudges"] = [g["id"] for g in card.active()]
    cmds[args.name] = c
    print(f"委任：{args.name} 交给 {args.holder}，治所 {c['seat']}")
    print(f"  {S.term(w.dir, 'region_unit')}：{'、'.join(regions) or '无'}")
    print("  军：" + ("、".join(f"{a}（{fmt_units(w.armies[a].get('units', {}))}）" for a in armies) or "无"))
    print(f"  方针：{json.dumps(c['directive'], ensure_ascii=False)}")
    print(f"  任期：{args.term or '未定'} 季；起始方面库：钱 {c['store']['money']}，粮 {c['store']['grain']}（从府库拨出，"
          f"economy.py 用 --extra-cost/--extra-grain-cost 记支出）")
    if card:
        for line in loyalty.shift_power_need(card, 1, f"{w.kingdom.get('date', '')}受委任统领{args.name}"):
            print(f"  人心：{line}")
        card.log.append(f"{w.kingdom.get('date', '')}：受委任统领{args.name}｜部曲 {loyalty.card_corps(card)}")
    finish(w, card, args.apply)


def cmd_directive(w, args):
    c = w.d.get("commands", {}).get(args.name) or die(f"没有方面“{args.name}”")
    old = c.get("directive", {})
    c["directive"] = directive_from_args(args, old)
    print(f"{args.name} 方针：\n  旧 {json.dumps(old, ensure_ascii=False)}\n  新 {json.dumps(c['directive'], ensure_ascii=False)}")
    c.setdefault("log", []).append(f"{w.kingdom.get('date', '')}：改方针")
    print("（改方针算帅府本季亲裁的一件。）")
    finish(w, None, args.apply)


def _release(w, name, c):
    """方面撤销，库存归府库。"""
    st = c.get("store", {})
    print(f"  方面库归府库：钱 {st.get('money', 0)}，粮 {st.get('grain', 0)}（economy.py 用 --extra-income/--extra-grain 记入）")
    for a, us in c.get("in_transit", {}).items():
        print(f"  在途补员 {a} {fmt_units(us)} 仍于下季到营（GM 手动加进 armies.json）")


def cmd_recall(w, args):
    cmds = w.d.get("commands", {})
    c = cmds.get(args.name) or die(f"没有方面“{args.name}”")
    card = open_card(c)
    turn = w.kingdom.get("turn", 0)
    seasons = max(turn - int(c.get("since_turn", turn)), 0)
    term = c.get("term")
    early = not term or seasons < int(term)
    when = w.kingdom.get("date", "")
    print(f"收回：{args.name}（{c.get('holder')}，委任 {seasons} 季，任期 {term or '未定'}），方式：{args.mode}")
    if card:
        cur = loyalty.card_corps(card)
        start = c.get("corps_start")
        gained = max(cur - start, 0) if start is not None else 0
        cut = gained if args.mode == "夺权" else math.ceil(gained * (0.75 if args.mode == "入朝" else 0.5))
        old, new = loyalty.set_corps(card, cur - cut, f"{when} 收回{args.name}（{args.mode}）")
        print(f"  部曲 {old} → {new}（委任期间涨了 {gained}，收回去掉 {cut}）")
        if args.mode == "入朝":
            for l in loyalty.shift_power_need(card, -1, f"{when}离开{args.name}，入朝{args.post or ''}"):
                print(f"  人心：{l}")
            if early:
                g = loyalty.add_grudge(card, when, f"任期未满被召回{args.name}", 1, "幕僚可闻")
                print(f"  人心：心结 [{g['id']}] {g['what']}｜强度 1（任期未满；按期召回不记）")
        else:
            for l in loyalty.shift_power_need(card, -2, f"{when}被夺{args.name}兵权"):
                print(f"  人心：{l}")
            g = loyalty.add_grudge(card, when, f"被夺{args.name}兵权", 3, "幕僚可闻")
            print(f"  人心：心结 [{g['id']}] {g['what']}｜强度 3；本季 season 加 --trigger 被夺兵权")
    _release(w, args.name, c)
    del cmds[args.name]
    print(f"  {'、'.join(c.get('regions', []))} 及 {'、'.join(c.get('armies', []))} 回到亲领。")
    finish(w, card, args.apply)


def cmd_rotate(w, args):
    cmds = w.d.get("commands", {})
    c = cmds.get(args.name) or die(f"没有方面“{args.name}”")
    old_card = open_card(c)
    turn = w.kingdom.get("turn", 0)
    seasons = max(turn - int(c.get("since_turn", turn)), 0)
    term = c.get("term")
    on_time = term and seasons >= int(term)
    when = w.kingdom.get("date", "")
    print(f"轮换：{args.name} 由 {c.get('holder')} 换成 {args.holder}（委任 {seasons} 季，任期 {term or '未定'}，"
          f"{'按期' if on_time else '未满期'}）")
    if old_card:
        cur = loyalty.card_corps(old_card)
        start = c.get("corps_start")
        gained = max(cur - start, 0) if start is not None else 0
        cut = math.ceil(gained * 0.5)
        o, n = loyalty.set_corps(old_card, cur - cut, f"{when} 轮换离开{args.name}")
        print(f"  {old_card.name} 部曲 {o} → {n}（委任期间涨了 {gained}，轮换去掉一半）")
        if not on_time:
            g = loyalty.add_grudge(old_card, when, f"未满任期被调离{args.name}旧部", 2, "幕僚可闻")
            print(f"  人心：{old_card.name} 心结 [{g['id']}] {g['what']}｜强度 2")
        else:
            print(f"  人心：按期轮换，事先说定，不记心结。{old_card.name} 的新职由 GM 另行安排（新方面再跑 delegate）。")
        if args.apply:
            old_card.save()
    new_card = loyalty.Card(card_path(args.card)) if args.card else None
    c["holder"], c["card"], c["since_turn"] = args.holder, args.card, turn
    c["corps_start"] = loyalty.card_corps(new_card) if new_card else None
    c["seen_grudges"] = [g["id"] for g in new_card.active()] if new_card else []
    if args.term is not None:
        c["term"] = args.term
    c.setdefault("log", []).append(f"{when}：轮换，{args.holder}接任")
    if new_card:
        for l in loyalty.shift_power_need(new_card, 1, f"{when}接任{args.name}"):
            print(f"  人心：{new_card.name} {l}")
        new_card.log.append(f"{when}：接任{args.name}｜部曲 {loyalty.card_corps(new_card)}")
    print("  新官上任第一季，拖延概率 +5 个百分点。")
    finish(w, new_card, args.apply)


def finish(w, card, apply):
    if not apply:
        print("\n（未写存档。确认无误后加 --apply。）")
        return
    w.save("directives.json", w.d)
    msg = [w.p("directives.json")]
    if card:
        card.save()
        msg.append(card.path)
    print("\n已写入 " + "、".join(msg) + "。")


# ---------- 亲裁与交办 ----------

def council_limit(w):
    g = w.gov
    staff = w.d.get("council", {}).get("staff", [])
    able = [s for s in staff if s.get("ability", 0) >= g["council_staff_min"] and s.get("status", "在") == "在"]
    return g["council_base"] + min(len(able), g["council_max_bonus"]), able


def cmd_council(w, args):
    limit, able = council_limit(w)
    staff = w.d.get("council", {}).get("staff", [])
    if not args.assign:
        print(f"=== 帅府亲裁：每季 {limit} 件（基数 {w.gov['council_base']}，能办事的幕僚 {len(able)} 人） ===")
        for s in staff:
            print(f"  {s['name']}：能 {s.get('ability', '?')}，所长 {'、'.join(s.get('forte', [])) or '—'}，"
                  f"偏好 {s.get('lean', '—')}" + (f"，{s['status']}" if s.get("status", "在") != "在" else ""))
        log = w.d.get("council", {}).get("log", [])
        cur = [l for l in log if l.get("turn") == w.kingdom.get("turn")]
        if cur:
            print("  本季已交办：")
            for l in cur:
                print(f"    {l['staff']}｜{l['task']}｜{l['result']}")
        return
    s = next((x for x in staff if x["name"] == args.assign), None) or die(f"幕僚里没有“{args.assign}”")
    rng = random.Random(args.seed)
    die6 = rng.randint(1, 6)
    fit = 1 if args.kind in s.get("forte", []) else -1 if s.get("forte") else 0
    score = s.get("ability", 5) + die6 + fit
    if score >= 13:
        res, note = "办得漂亮", "效果照足，另有一点添头（GM 依幕僚所长添一笔：多省些钱、多带回一条消息、多结一个人）"
    elif score >= 10:
        res, note = "办妥", "照原意办成"
    elif score >= 7:
        res, note = "打折", "办成一半：效果减半，或拖到下季才见效"
    else:
        res, note = "走样", f"按幕僚自己的偏好（{s.get('lean', '—')}）改了办法，结果由 GM 依此叙述"
    print(f"交办：{s['name']}（能 {s.get('ability')}，所长 {'、'.join(s.get('forte', [])) or '—'}，偏好 {s.get('lean', '—')}）")
    print(f"  事由：{args.task}（{args.kind}）")
    print(f"  检定：能 {s.get('ability')} + d6={die6} + 对口 {fit:+d} = {score} → 【{res}】{note}")
    lg = w.d.setdefault("council", {}).setdefault("log", [])
    lg.append({"turn": w.kingdom.get("turn"), "staff": s["name"], "task": args.task, "kind": args.kind, "result": res})
    w.d["council"]["log"] = lg[-30:]
    finish(w, None, args.apply)


# ---------- 查看 ----------

def cmd_show(w, args):
    rt, at = tier_maps(w)
    seat = seat_of(w)
    own = [r for r, (t, _) in rt.items() if t == "亲领"]
    print(f"=== 分层：帅府治所 {seat}（{w.kingdom.get('date', '')}，第 {w.kingdom.get('turn')} 回合） ===")
    R = S.term(w.dir, "region_unit")
    print(f"亲领{R}（{len(own)}）：")
    for r in own:
        k, note = decay(w, r, seat, len(own))
        print(f"  {r}  政令 ×{k}" + (f"（{note}）" if note else ""))
    print("亲领军：" + "、".join(a for a, (t, _) in at.items() if t == "亲领"))
    for name, c in w.d.get("commands", {}).items():
        d = c.get("directive", {})
        print(f"委任「{name}」{c.get('holder')}，治所 {c.get('seat')}，自第 {c.get('since_turn')} 回合，任期 {c.get('term') or '未定'}")
        print(f"  {R}：{'、'.join(c.get('regions', []))}；军：{'、'.join(c.get('armies', []))}")
        print(f"  方针：{d.get('posture')}，补员到 {d.get('refill', 0):.0%}，上供 {d.get('tribute', 0):.0%}，"
              f"权限 {d.get('latitude', {})}，上报 {d.get('report', {})}")
        if d.get("words"):
            print(f"  原话：{d['words']}")
    for name, c in w.d.get("loose", {}).items():
        print(f"羁縻「{name}」{R}：{'、'.join(c.get('regions', []))}；态度：{c.get('attitude', '—')}；动向：{c.get('movement', '—')}")
    limit, _ = council_limit(w)
    print(f"帅府每季亲裁 {limit} 件。")


def main():
    ap = argparse.ArgumentParser(description="分层托管（规则见 rules/governance.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=os.path.join(ROOT, "world"), help="存档目录，默认 world/")
    sp = ap.add_subparsers(dest="cmd", required=True)

    def dir_args(p):
        p.add_argument("--posture", choices=POSTURES)
        p.add_argument("--refill", type=float, help="补员目标，建制的几成，如 0.8")
        p.add_argument("--latitude", choices=TIERS, help="钱粮权限档")
        p.add_argument("--money", type=int, help="每季可自行动支的钱")
        p.add_argument("--grain", type=int, help="每季可自行动支的粮")
        p.add_argument("--horses", type=int, help="每季可向府库支取的马")
        p.add_argument("--tribute", type=float, help="上供比例，如 0.3")
        p.add_argument("--report", help="上报条件，如 缺员=0.3,士气=60,敌军=3000,粮季=1")
        p.add_argument("--words", help="方针原话")
        p.add_argument("--apply", action="store_true")

    p = sp.add_parser("show")
    p.set_defaults(fn=cmd_show)
    p = sp.add_parser("delegate")
    p.add_argument("name")
    p.add_argument("--holder", required=True)
    p.add_argument("--card")
    p.add_argument("--regions", default="")
    p.add_argument("--armies", default="")
    p.add_argument("--seat")
    p.add_argument("--term", type=int)
    p.add_argument("--grant", help="起始方面库，从府库拨，如 5000,20000")
    dir_args(p)
    p.set_defaults(fn=cmd_delegate)
    p = sp.add_parser("directive")
    p.add_argument("name")
    dir_args(p)
    p.set_defaults(fn=cmd_directive)
    p = sp.add_parser("season")
    p.add_argument("--season", required=True, choices=SEASONS)
    p.add_argument("--war", default="")
    p.add_argument("--seed", type=int)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_season)
    p = sp.add_parser("recall")
    p.add_argument("name")
    p.add_argument("--mode", required=True, choices=("入朝", "夺权"))
    p.add_argument("--post", help="入朝后的新职")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_recall)
    p = sp.add_parser("rotate")
    p.add_argument("name")
    p.add_argument("--holder", required=True)
    p.add_argument("--card")
    p.add_argument("--term", type=int)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_rotate)
    p = sp.add_parser("council")
    p.add_argument("--assign")
    p.add_argument("--task")
    p.add_argument("--kind", default="内政", choices=("内政", "军务", "外交", "人事"))
    p.add_argument("--seed", type=int)
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_council)
    args = ap.parse_args()
    w = World(os.path.abspath(args.world)).all()
    args.fn(w, args)


if __name__ == "__main__":
    main()
