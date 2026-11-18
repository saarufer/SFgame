#!/usr/bin/env python3
"""经济结算。规则见 rules/economy.md，参数见 world/economy.json。

用法：
  python3 scripts/economy.py --season 冬
  python3 scripts/economy.py --season 秋 --war 甲州,乙州 --extra-cost 3000
  python3 scripts/economy.py --season 冬 --apply      # 把结果写回 kingdom.json 的 treasury

不加 --apply 只打印明细；加了才写存档。同一回合重复 --apply 会被拒绝（防止结算两次），
确需重算时加 --force。

有 world/directives.json 时（分层托管，见 rules/governance.md）：委任、羁縻的州和军不进这里的明细，
委任方面改记“上供”（收入）和“请拨、代垫”（支出），数字取 governance.py season 的结算。
economy.json 里有 governance 参数时，亲领州按政令系数打折（离帅府远、亲领州多）。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORLD = os.path.join(ROOT, "world")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scenario_lib as S  # noqa: E402
SEASONS = ("春", "夏", "秋", "冬")
UNIT_NAMES = {"infantry": "步", "cavalry": "骑", "archer": "弓", "militia": "民兵"}


def load(name):
    with open(os.path.join(WORLD, name), encoding="utf-8") as f:
        return json.load(f)


def split_list(s):
    if not s:
        return []
    return [x.strip() for x in s.replace("，", ",").replace("、", ",").split(",") if x.strip()]


def governance_view():
    """有 directives.json 时，返回 (World, 州层级, 军层级)；否则 None。"""
    if not os.path.exists(os.path.join(WORLD, "directives.json")):
        return None
    import governance
    w = governance.World(WORLD).all()
    rt, at = governance.tier_maps(w)
    return w, rt, at


def compute(season, war, extra_cost=0, extra_income=0, extra_grain_cost=0, extra_grain=0):
    eco, regions, armies = load("economy.json"), load("map.json")["regions"], load("armies.json")["armies"]
    own = S.own_faction(WORLD, eco)
    gm = eco["season_multiplier"]["grain"][season]
    mm = eco["season_multiplier"]["money"][season]
    war_mult = eco["war_multiplier"]
    owned = [r for r, d in regions.items() if d.get("owner") == own]
    unknown = [r for r in war if r not in regions]
    if unknown:
        sys.exit(f"错误：战乱地区不在 map.json 里：{'、'.join(unknown)}")
    gv = governance_view()
    delegated_regions, delegated_armies, gov_rows, gov_exp, gov_horses, gov_note = {}, {}, [], [], 0, ""
    if gv:
        w, rt, at = gv
        delegated_regions = {r: t for r, t in rt.items() if t[0] != "亲领"}
        delegated_armies = {a: t for a, t in at.items() if t[0] != "亲领"}
        last = w.d.get("last_settlement", {})
        if w.d.get("commands"):
            if last.get("turn") == load("kingdom.json").get("turn"):
                tr, dr = last.get("tribute", {}), last.get("draw", {})
                gov_rows.append(("委任方面上供", tr.get("money", 0), tr.get("grain", 0), "governance.py 本季已结算"))
                gov_exp.append(("委任方面请拨、代垫", dr.get("money", 0), dr.get("grain", 0)))
                gov_horses = dr.get("horses", 0)
            else:
                gov_note = "委任方面本季还没结算：先跑 governance.py season --apply，上供和请拨才计入。"
    owned_direct = [r for r in owned if r not in delegated_regions]
    gov_params = "governance" in eco
    if gov_params:
        import governance
        gw = gv[0] if gv else governance.World(WORLD).all()
        seat = governance.seat_of(gw)

    income_rows = []  # (名目, 钱, 粮, 备注)
    for r in owned:
        if r in delegated_regions:
            continue
        inc = regions[r].get("income", {})
        money, grain = inc.get("money", 0) * mm, inc.get("grain", 0) * gm
        notes = []
        if gov_params:
            k, why = governance.decay(gw, r, seat, len(owned_direct))
            if k < 1:
                money *= k
                grain *= k
                notes.append(f"政令×{k}（{why}）")
        mod = eco.get("region_modifiers", {}).get(r, {})
        if "money" in mod:
            money *= mod["money"]
            notes.append(f"钱×{mod['money']}")
        if "grain" in mod:
            grain *= mod["grain"]
            notes.append(f"粮×{mod['grain']}")
        if r in war:
            money *= war_mult
            grain *= war_mult
            notes.append(f"战乱×{war_mult}")
        income_rows.append((r, round(money), round(grain), "，".join(notes)))

    fixed_rows = []
    for item in eco.get("fixed_income", []):
        money, grain, notes = item.get("money", 0) * mm, item.get("grain", 0), []
        if item.get("seasonal"):
            grain *= gm
        reg = item.get("region")
        if reg and regions.get(reg, {}).get("owner") != own:
            notes.append(f"{reg}不在我手，不计")
            money = grain = 0
        elif reg in war:
            wm = item.get("war_multiplier", war_mult)
            money *= wm
            grain *= wm
            notes.append(f"{reg}战乱×{wm}")
        fixed_rows.append((item["name"], round(money), round(grain), "，".join(notes)))

    expense_rows = [(e["name"], e.get("money", 0), e.get("grain", 0)) for e in eco.get("fixed_expense", [])]

    prefix = S.army_prefix(WORLD, eco)
    rates = eco["upkeep_per_1000"]
    totals = {u: 0 for u in rates}
    army_rows, skipped = [], []
    for name, arm in armies.items():
        if not str(arm.get("faction", "")).startswith(prefix):
            skipped.append(f"{name}（{arm.get('faction')}）")
            continue
        if name in delegated_armies:
            continue
        g = m = 0
        for u, n in arm.get("units", {}).items():
            if u not in rates:
                sys.exit(f"错误：{name} 有未知兵种 {u}，请在 economy.json 的 upkeep_per_1000 里补上")
            totals[u] += n
            g += n / 1000 * rates[u]["grain"]
            m += n / 1000 * rates[u]["money"]
        army_rows.append((name, arm.get("units", {}), round(m), round(g)))
    upkeep_money = round(sum(totals[u] / 1000 * rates[u]["money"] for u in rates))
    upkeep_grain = round(sum(totals[u] / 1000 * rates[u]["grain"] for u in rates))

    fixed_rows += gov_rows
    expense_rows += gov_exp
    inc_money = sum(r[1] for r in income_rows) + sum(r[1] for r in fixed_rows) + extra_income
    inc_grain = sum(r[2] for r in income_rows) + sum(r[2] for r in fixed_rows) + extra_grain
    exp_money = sum(r[1] for r in expense_rows) + upkeep_money + extra_cost
    exp_grain = sum(r[2] for r in expense_rows) + upkeep_grain + extra_grain_cost
    return {
        "season": season, "war": war, "owned": owned,
        "income_rows": income_rows, "fixed_rows": fixed_rows, "expense_rows": expense_rows,
        "army_rows": army_rows, "skipped": skipped, "totals": totals,
        "upkeep_money": upkeep_money, "upkeep_grain": upkeep_grain,
        "extra": (extra_income, extra_cost, extra_grain, extra_grain_cost),
        "inc_money": inc_money, "inc_grain": inc_grain,
        "exp_money": exp_money, "exp_grain": exp_grain,
        "net_money": inc_money - exp_money, "net_grain": inc_grain - exp_grain,
        "delegated_regions": delegated_regions, "delegated_armies": delegated_armies, "horses_out": gov_horses, "gov_note": gov_note,
        "own": own, "prefix": prefix, "R": S.term(WORLD, "region_unit"),
    }


def fmt_units(units):
    return " ".join(f"{UNIT_NAMES.get(u, u)}{n}" for u, n in units.items() if n)


def report(res, treasury):
    out = []
    p = out.append
    war = "、".join(res["war"]) or "无"
    R = res["R"]
    p(f"=== 经济结算：{res['season']}季（战乱{R}：{war}） ===")
    p("")
    p(f"【各{R}产出】" + (f"（亲领{R}）" if res["delegated_regions"] else ""))
    for name, mo, gr, note in res["income_rows"]:
        p(f"  {name:<6} 钱 {mo:>6}  粮 {gr:>7}  {note}")
    if res["delegated_regions"]:
        by = {}
        for r, (t, n) in res["delegated_regions"].items():
            by.setdefault(f"{t}：{n}", []).append(r)
        for k, rs in by.items():
            p(f"  （{k}——{'、'.join(rs)}，不进府库明细）")
    if res["gov_note"]:
        p(f"  !! {res['gov_note']}")
    p("【固定收入】")
    for name, mo, gr, note in res["fixed_rows"]:
        p(f"  {name:<14} 钱 {mo:>6}  粮 {gr:>7}  {note}")
    ei, ec, eg, egc = res["extra"]
    if ei or eg:
        p(f"  临时收入           钱 {ei:>6}  粮 {eg:>7}")
    p(f"  —— 收入合计：钱 {res['inc_money']}，粮 {res['inc_grain']}")
    p("")
    p(f"【粮饷】（faction 以“{res['prefix']}”开头的军队）")
    for name, units, mo, gr in res["army_rows"]:
        p(f"  {name:<10} {fmt_units(units):<24} 钱 {mo:>6}  粮 {gr:>7}")
    t = res["totals"]
    p(f"  兵员合计：{fmt_units(t)}，共 {sum(t.values())} 人")
    p(f"  —— 粮饷合计：钱 {res['upkeep_money']}，粮 {res['upkeep_grain']}")
    if res["skipped"]:
        p(f"  （不由府库供给：{'、'.join(res['skipped'])}）")
    if res["delegated_armies"]:
        by = {}
        for a, (t, n) in res["delegated_armies"].items():
            by.setdefault(f"{t}“{n}”", []).append(a)
        p("  （委任、羁縻的军队由方面自养：" + "；".join(f"{k} {len(v)} 军" for k, v in by.items()) + "）")
    p("【固定支出】")
    for name, mo, gr in res["expense_rows"]:
        p(f"  {name:<10} 钱 {mo:>6}  粮 {gr:>7}")
    if ec or egc:
        p(f"  临时支出     钱 {ec:>6}  粮 {egc:>7}")
    p(f"  —— 支出合计：钱 {res['exp_money']}，粮 {res['exp_grain']}")
    p("")
    nm, ng = res["net_money"], res["net_grain"]
    p(f"【结余】钱 {nm:+d}，粮 {ng:+d}")
    new_m, new_g = treasury["money"] + nm, treasury["grain"] + ng
    ho = res["horses_out"]
    horse_txt = (f"马 {treasury.get('horses', 0)} → {treasury.get('horses', 0) - ho}（委任方面支取 {ho}）" if ho
                 else f"马 {treasury.get('horses', 0)}（不变）")
    p(f"【府库】钱 {treasury['money']} → {max(new_m, 0)}；粮 {treasury['grain']} → {max(new_g, 0)}；{horse_txt}")
    if new_m < 0:
        p(f"  !! 欠饷 {-new_m} 贯：相关军队士气 -15，由 GM 判定（rules/economy.md）")
    if new_g < 0:
        p(f"  !! 断粮 {-new_g} 石：相关军队士气 -15，由 GM 判定（rules/economy.md）")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="经济结算（规则见 rules/economy.md）")
    ap.add_argument("--season", required=True, choices=SEASONS)
    ap.add_argument("--war", default="", help="本季打过仗的州（地区），逗号分隔，如 甲州,乙州")
    ap.add_argument("--extra-cost", type=int, default=0, help="本季临时支出（钱）")
    ap.add_argument("--extra-income", type=int, default=0, help="本季临时收入（钱）")
    ap.add_argument("--extra-grain-cost", type=int, default=0, help="本季临时支出（粮）")
    ap.add_argument("--extra-grain", type=int, default=0, help="本季临时收入（粮）")
    ap.add_argument("--apply", action="store_true", help="把结果写回 kingdom.json 的 treasury")
    ap.add_argument("--force", action="store_true", help="允许同一回合再次 --apply")
    ap.add_argument("--world", help="存档目录（试验用），默认 world/")
    args = ap.parse_args()
    if args.world:
        global WORLD
        WORLD = os.path.abspath(args.world)

    kingdom = load("kingdom.json")
    if kingdom.get("season") and kingdom["season"] != args.season:
        print(f"注意：存档当前季节是“{kingdom['season']}”，你传入的是“{args.season}”。", file=sys.stderr)
    res = compute(args.season, split_list(args.war), args.extra_cost, args.extra_income,
                  args.extra_grain_cost, args.extra_grain)
    tr = kingdom["treasury"]
    print(report(res, tr))

    if not args.apply:
        print("\n（未写存档。确认无误后加 --apply。）")
        return
    last = kingdom.get("last_economy_settlement", {})
    if last.get("turn") == kingdom.get("turn") and not args.force:
        sys.exit(f"\n拒绝写入：第 {kingdom.get('turn')} 回合已经结算过经济。确需重算请加 --force。")
    if res["gov_note"] and not args.force:
        sys.exit(f"\n拒绝写入：{res['gov_note']}（确需跳过加 --force）")
    new_m, new_g = tr["money"] + res["net_money"], tr["grain"] + res["net_grain"]
    tr["money"], tr["grain"] = max(new_m, 0), max(new_g, 0)
    if res["horses_out"]:
        tr["horses"] = max(tr.get("horses", 0) - res["horses_out"], 0)
    kingdom["last_economy_settlement"] = {
        "turn": kingdom.get("turn"), "date": kingdom.get("date"), "season": args.season,
        "war": res["war"], "net_money": res["net_money"], "net_grain": res["net_grain"],
        "arrears_money": max(-new_m, 0), "arrears_grain": max(-new_g, 0),
    }
    with open(os.path.join(WORLD, "kingdom.json"), "w", encoding="utf-8") as f:
        json.dump(kingdom, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n已写入 {os.path.join(WORLD, 'kingdom.json')}：钱 {tr['money']}，粮 {tr['grain']}。")


if __name__ == "__main__":
    main()
