#!/usr/bin/env python3
"""按层级生成汇报用的数字。规则见 rules/governance.md 第三节。

  python3 scripts/report.py                 # 分层汇报：亲领精确，委任取约数和档位，羁縻只看态度
  python3 scripts/report.py --exceptions    # 只列例外
  python3 scripts/report.py --exact         # 全部按亲领精确列出（对照用）
  python3 scripts/report.py --gm            # 加上 GM 才能看的条目（离心、部曲、未外传的心结）
  python3 scripts/report.py --world 目录 [--directives 文件]   # 用别的存档或层级配置试算

存档里的数字始终精确；本脚本只读不写，取整只发生在汇报里。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import governance as gv  # noqa: E402
import loyalty  # noqa: E402
import scenario_lib as S  # noqa: E402

DIG = "零一二三四五六七八九"


def cn(n, lead=True):
    """1–99 的中文数字；lead 为真时 2 读作“两”。"""
    if n < 10:
        return "两" if (n == 2 and lead) else DIG[n]
    t, o = divmod(n, 10)
    return ("十" if t == 1 else DIG[t] + "十") + (DIG[o] if o else "")


def approx(n):
    """约数：一万以上取到千，一千以上取到五百，一百以上取到百。"""
    n = int(round(n))
    if n <= 0:
        return "无"
    if n < 100:
        return "数十"
    if n < 1000:
        r = int(round(n / 100.0))
        return "一千" if r >= 10 else f"{DIG[r]}百"
    if n < 10000:
        r = int(round(n / 500.0)) * 500
        if r >= 10000:
            return "一万"
        q, h = divmod(r, 1000)
        return f"{cn(q)}千" + ("五" if h else "")
    if n < 100000:
        r = int(round(n / 1000.0)) * 1000
        w, q = divmod(r, 10000)
        return f"{cn(w)}万" + (DIG[q // 1000] if q else "")
    r = int(round(n / 10000.0))
    return f"{cn(r)}万"


def band(x, cuts):
    for limit, word in cuts:
        if x >= limit:
            return word
    return cuts[-1][1]


STRENGTH = [(0.95, "满编"), (0.8, "堪战"), (0.6, "缺员"), (0, "残破")]
MORALE = [(85, "高昂"), (70, "平稳"), (55, "低落"), (0, "涣散")]
STOCK = [(4, "充裕"), (2, "够用"), (1, "吃紧"), (0, "告急")]


def seasons_word(s):
    if s >= 8:
        return "两年以上"
    s = int(s)
    return f"{cn(s, False) if s != 2 else '两'}季" if s >= 1 else "不足一季"


def kinds(units):
    k = []
    if units.get("infantry"):
        k.append("步")
    if units.get("cavalry"):
        k.append("骑")
    if units.get("archer"):
        k.append("弓")
    return "".join(k) or "民兵"


def sum_units(w, armies):
    tot = {}
    for a in armies:
        for u, n in w.armies.get(a, {}).get("units", {}).items():
            tot[u] = tot.get(u, 0) + (n or 0)
    return tot


# ---------- 例外 ----------

def exceptions(w, gm=False):
    rt, at = gv.tier_maps(w)
    est = w.d.get("establishment", {})
    out = []
    seen = set()

    def add(s):
        if s not in seen:
            seen.add(s)
            out.append(s)

    # 各军：缺员、士气（亲领、委任都查；委任用方面自己的上报条件）
    for a, (tier, cname) in at.items():
        if tier == "羁縻" or a not in w.armies:
            continue
        rep = dict(gv.DEFAULT_REPORT)
        if tier == "委任":
            rep.update(w.d["commands"][cname].get("directive", {}).get("report", {}))
        arm = w.armies[a]
        have = gv.units_total(arm.get("units", {}))
        full = gv.units_total(est.get(a, {}))
        where = f"（{cname}）" if cname else ""
        if full and have / full < 1 - rep["缺员"]:
            add(f"{a}{where}缺员{cn(round((1 - have / full) * 10))}成：现有{approx(have) if tier == '委任' else have}，建制{approx(full) if tier == '委任' else full}")
        if arm.get("morale", 100) < rep["士气"]:
            m = arm["morale"]
            add(f"{a}{where}士气{band(m, MORALE)}" + (f"（{m}）" if tier == "亲领" else ""))
    # 委任方面：粮
    for cname, c in w.d.get("commands", {}).items():
        rep = dict(gv.DEFAULT_REPORT)
        rep.update(c.get("directive", {}).get("report", {}))
        _, ug = gv.upkeep(w, sum_units(w, c.get("armies", [])))
        st = c.get("store", {})
        if ug and st.get("grain", 0) / ug < rep["粮季"]:
            s_ = st.get("grain", 0) / ug
            add(f"{cname}库粮{band(s_, STOCK)}，" + (f"只够{seasons_word(s_)}" if s_ >= 1 else "不足一季"))
    # 敌军压境：亲领州用默认门槛，委任方面用自己的
    groups = [(None, [r for r, (t, _) in rt.items() if t == "亲领"], gv.DEFAULT_REPORT["敌军"], True)]
    for cname, c in w.d.get("commands", {}).items():
        thr = c.get("directive", {}).get("report", {}).get("敌军", gv.DEFAULT_REPORT["敌军"])
        groups.append((cname, c.get("regions", []), thr, False))
    for cname, regs, thr, exact in groups:
        for en, arm, where, inside in gv.enemies_near(w, regs):
            n = gv.units_total(arm.get("units", {}))
            if n >= thr:
                add(f"敌军{'入境' if inside else '压境'}{('（' + cname + '）') if cname else ''}：{en}，"
                    f"{n if exact else '约' + approx(n)}人，在{arm.get('location')}")
    # 府库
    tr = w.kingdom.get("treasury", {})
    les = w.kingdom.get("last_economy_settlement", {})
    if les.get("arrears_money") or les.get("arrears_grain"):
        add(f"府库欠饷 {les.get('arrears_money', 0)} {S.term(w.dir, 'money_unit')}、断粮 {les.get('arrears_grain', 0)} {S.term(w.dir, 'grain_unit')}")
    if tr and tr.get("grain", 1) <= 0:
        add("府库无粮")
    # 委任方面本季结算带出的例外（代垫、任期满、未照方针、外传的心结）
    last = w.d.get("last_settlement", {})
    if last.get("turn") == w.kingdom.get("turn"):
        for cname, xs in last.get("exceptions", {}).items():
            for x in xs:
                if any(k in x for k in ("代垫", "任期", "未照方针", "幕僚听说", "拨马")):
                    add(f"{x}" if cname in x else f"{x}（{cname}）")
    # GM 才看的
    if gm:
        for cname, c in w.d.get("commands", {}).items():
            card = gv.open_card(c)
            if not card or card.role != "将领":
                continue
            corps = loyalty.card_corps(card)
            lv = card.level
            if loyalty.LEVELS.index(lv) >= 2 or corps >= 70:
                add(f"（GM）{c.get('holder')}：离心“{lv}”，部曲 {corps}")
    return out


# ---------- 分层汇报 ----------

def treasury_line(w, tr):
    t = lambda k: S.term(w.dir, k)  # noqa: E731
    return (f"【府库】钱 {tr.get('money', 0)} {t('money_unit')}，粮 {tr.get('grain', 0)} {t('grain_unit')}，"
            f"马 {tr.get('horses', 0)} {t('horse_unit')}")


def tiered(w, gm=False):
    rt, at = gv.tier_maps(w)
    out = []
    p = out.append
    k = w.kingdom
    tr = k.get("treasury", {})
    R = S.term(w.dir, "region_unit")
    p(f"=== 帅府汇报：{k.get('date', '')}（第 {k.get('turn')} 回合） ===")
    p(treasury_line(w, tr))
    seat = gv.seat_of(w)
    direct = [r for r, (t, _) in rt.items() if t == "亲领"]
    p(f"【亲领】{len(direct)} {R}：{'、'.join(direct)}")
    for a, (t, _) in at.items():
        if t != "亲领" or a not in w.armies:
            continue
        arm = w.armies[a]
        p(f"  {a}  {arm.get('location', '')}  {gv.fmt_units(arm.get('units', {}))}  士气 {arm.get('morale', '?')}"
          + (f"  {arm.get('commander')}" if arm.get("commander") not in (None, "—") else ""))
    for cname, c in w.d.get("commands", {}).items():
        d = c.get("directive", {})
        units = sum_units(w, c.get("armies", []))
        militia = units.pop("militia", 0)
        regular = gv.units_total(units)
        full_units = {}
        for a in c.get("armies", []):
            for u, n in w.d.get("establishment", {}).get(a, {}).items():
                full_units[u] = full_units.get(u, 0) + n
        full = gv.units_total(full_units)
        have = regular + militia
        strength = band(have / full, STRENGTH) if full else "建制未定"
        morales = [(w.armies[a].get("morale", 70), gv.units_total(w.armies[a].get("units", {})))
                   for a in c.get("armies", []) if a in w.armies]
        wsum = sum(n for _, n in morales) or 1
        mo = sum(m * n for m, n in morales) / wsum
        um, ug = gv.upkeep(w, sum_units(w, c.get("armies", [])))
        st = c.get("store", {})
        g_s = st.get("grain", 0) / ug if ug else 99
        m_s = st.get("money", 0) / um if um else 99
        turn = k.get("turn", 0)
        n_season = max(turn - int(c.get("since_turn", turn)), 0) + 1
        term = f"，任期 {n_season}/{c['term']} 季" if c.get("term") else ""
        p(f"【委任】{cname}（{c.get('holder')}，治所{c.get('seat')}；方针：{d.get('posture', '守')}{term}）")
        p(f"  辖 {len(c.get('regions', []))} {R}：{'、'.join(c.get('regions', []))}")
        troops = f"{kinds(units)}约{approx(regular)}" if regular else ""
        if militia:
            troops += ("，" if troops else "") + f"民兵约{approx(militia)}"
        p(f"  兵：{troops}，{strength}；士气{band(mo, MORALE)}")
        food = f"粮够{seasons_word(g_s)}" if g_s >= 1 else "粮不足一季"
        p(f"  库：{food}（{band(g_s, STOCK)}），钱{band(m_s, STOCK)}")
        last = w.d.get("last_settlement", {})
        if gm and last.get("turn") == turn:
            p(f"  （GM）本季执行：{last.get('deviation', {}).get(cname, '照办')}")
    for lname, c in w.d.get("loose", {}).items():
        p(f"【羁縻】{lname}（{'、'.join(c.get('regions', [])) or '—'}）：{c.get('attitude', '—')}；{c.get('movement', '动向未闻')}")
    ex = exceptions(w, gm)
    p("【例外】" + ("无" if not ex else ""))
    for x in ex:
        p(f"  · {x}")
    return "\n".join(out)


def exact(w):
    """全部按亲领精确列出（对照用，等于原来逐军逐州的汇报）。"""
    out = []
    p = out.append
    k = w.kingdom
    tr = k.get("treasury", {})
    p(f"=== 帅府汇报（全部精确）：{k.get('date', '')}（第 {k.get('turn')} 回合） ===")
    p(treasury_line(w, tr))
    p(f"【{S.term(w.dir, 'region_unit')}】")
    own = gv.own_faction(w)
    for r, info in w.regions.items():
        if str(info.get("owner", "")).startswith(own):
            inc = info.get("income", {})
            p(f"  {r}  城防 {info.get('fortification', 0)}  每季钱 {inc.get('money', 0)} 粮 {inc.get('grain', 0)}"
              + (f"  （{info['owner']}）" if info.get("owner") != own else ""))
    p("【军】")
    tot = {}
    for a, arm in w.armies.items():
        if not gv.is_own_army(w, arm):
            continue
        for u, n in arm.get("units", {}).items():
            tot[u] = tot.get(u, 0) + n
        p(f"  {a}  {arm.get('commander', '')}  {arm.get('location', '')}  {gv.fmt_units(arm.get('units', {}))}"
          f"  士气 {arm.get('morale', '?')}  {arm.get('status', '')}")
    p(f"  合计：{gv.fmt_units(tot)}，共 {sum(tot.values())} 人")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="分层汇报（只读）")
    ap.add_argument("--world", default=os.path.join(ROOT, "world"))
    ap.add_argument("--directives", help="层级配置文件，默认取存档目录里的 directives.json")
    ap.add_argument("--exact", action="store_true")
    ap.add_argument("--exceptions", action="store_true")
    ap.add_argument("--gm", action="store_true")
    args = ap.parse_args()
    w = gv.World(os.path.abspath(args.world)).all()
    if args.directives:
        with open(args.directives, encoding="utf-8") as f:
            w.d = json.load(f)
    if args.exact:
        print(exact(w))
    elif args.exceptions:
        ex = exceptions(w, args.gm)
        print("【例外】" + ("无" if not ex else ""))
        for x in ex:
            print(f"  · {x}")
    else:
        print(tiered(w, args.gm))


if __name__ == "__main__":
    main()
