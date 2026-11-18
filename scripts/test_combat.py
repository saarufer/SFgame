#!/usr/bin/env python3
"""战斗规则自检。改了 resolve_battle.py 或 tactical.py 之后跑一遍：
  python3 scripts/test_combat.py
每一项跑多次随机，打印统计并检查是否符合 rules/combat.md、rules/tactics.md 写明的关系。
"""
import copy
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolve_battle as rb  # noqa: E402
import tactical as tc  # noqa: E402

N = 400
fails = []


def check(name, cond, detail):
    print(f"[{'通过' if cond else '不符'}] {name}：{detail}")
    if not cond:
        fails.append(name)


# ------------------------------------------------------------------ 宏观
def macro(terrain, a_units, d_units, a_formed=False, d_formed=False, n=2000, a_kw=None, d_kw=None):
    b = {"terrain": terrain, "intensity": "assault", "seed": 3,
         "attacker": dict({"name": "攻", "units": a_units, "morale": 75, "formed": a_formed}, **(a_kw or {})),
         "defender": dict({"name": "守", "units": d_units, "morale": 75, "formed": d_formed}, **(d_kw or {}))}
    return rb.trials(b, n)


def macro_tests():
    print("== 宏观引擎 ==")
    old = {"terrain": "plain", "intensity": "assault", "seed": 1,
           "attacker": {"name": "马军", "commander": "某将", "统率": 6, "武勇": 9, "charge": True,
                        "units": {"cavalry": 2000, "infantry": 500}, "morale": 80, "tactic": "none"},
           "defender": {"name": "敌", "commander": "某", "统率": 5, "units": {"infantry": 1500, "archer": 500},
                        "morale": 70}}
    r = rb.resolve(old, random.Random(1))
    check("旧格式输入", set(r) >= {"winner", "power", "losses", "remaining", "morale_after", "region_captured",
                                "events"}, f"winner={r['winner']}")
    a = macro("plain", {"cavalry": 1000}, {"infantry": 2000})
    b = macro("plain", {"cavalry": 1000}, {"infantry": 2000}, d_formed=True)
    c = macro("mountain", {"cavalry": 1000}, {"infantry": 2000}, d_formed=True)
    check("平原骑兵冲没列阵的步兵占优", a["attacker_win_rate"] > 0.7, f"胜率 {a['attacker_win_rate']}")
    check("步兵列阵后平原上大致对等", 0.3 < b["attacker_win_rate"] < 0.65, f"胜率 {b['attacker_win_rate']}")
    check("山地列阵步兵占优", c["attacker_win_rate"] < 0.3, f"骑兵胜率 {c['attacker_win_rate']}")
    d = macro("steppe", {"horse_archer": 1000}, {"crossbow": 1200}, d_formed=True)
    e = macro("steppe", {"horse_archer": 1000}, {"archer": 1200}, d_formed=True)
    check("弩对骑射有射程优势", d["attacker_win_rate"] < e["attacker_win_rate"],
          f"骑射对弩 {d['attacker_win_rate']}，对弓 {e['attacker_win_rate']}")

    # 护甲、操练、伤亡不对称（rules/combat.md“伤亡”）
    r = rb.resolve(dict(old, attacker=dict(old["attacker"], armor={"cavalry": "heavy"}, drill="elite")),
                   random.Random(1))
    check("新字段：护甲、操练、俘获", "captured" in r and r["state"]["traits"]["attacker"]["cavalry"] == "铁甲·精锐",
          f"{r['state']['traits']['attacker']}")
    elite = {"drill": "elite"}
    f = macro("plain", {"heavy_cavalry": 2000}, {"infantry": 6000}, a_kw=elite)
    check("具装精锐冲没列阵的步卒：胜方伤亡很小，败方过半",
          f["attacker_win_rate"] > 0.9 and f["winner_loss_median"] <= 3 and f["loser_loss_median"] >= 45,
          f"胜率 {f['attacker_win_rate']}，胜方伤亡中位 {f['winner_loss_median']}%，败方 {f['loser_loss_median']}%")
    g = macro("plain", {"heavy_cavalry": 2000}, {"spear": 6000}, d_formed=True, a_kw=elite)
    check("具装冲严整枪阵代价大增", g["attacker_loss_median"] >= 10 and g["attacker_win_rate"] < 0.7
          and g["attacker_loss_median"] > 5 * f["attacker_loss_median"],
          f"胜率 {g['attacker_win_rate']}，具装伤亡中位 {g['attacker_loss_median']}%（冲散兵时 {f['attacker_loss_median']}%）")
    h = macro("plain", {"heavy_cavalry": 2000}, {"heavy_cavalry": 2000}, a_kw=elite,
              d_kw={"drill": "elite", "armor": "heavy"})
    check("重骑对冲双方伤亡都重", h["attacker_loss_median"] > 12 and h["defender_loss_median"] > 12,
          f"攻方伤亡中位 {h['attacker_loss_median']}%，守方 {h['defender_loss_median']}%")
    k_heavy = rb.through("archer", "barded") / rb.through("archer", "light")
    k_none = rb.through("archer", "none") / rb.through("archer", "light")
    check("弓箭射人马俱甲打大折扣，射无甲照旧", k_heavy < 0.4 and k_none >= 1.0,
          f"射具装 ×{k_heavy:.2f}，射无甲 ×{k_none:.2f}（以皮甲为 1）")
    m1 = macro("plain", {"cavalry": 1500}, {"archer": 2000, "infantry": 2000}, d_formed=True)
    m2 = macro("plain", {"cavalry": 1500}, {"archer": 2000, "infantry": 2000}, d_formed=True,
               a_kw={"armor": "barded"})
    check("同样的骑兵披了重甲，挨弓弩步阵时伤亡少得多", m2["attacker_loss_median"] < 0.7 * m1["attacker_loss_median"],
          f"皮甲 {m1['attacker_loss_median']}%，人马俱甲 {m2['attacker_loss_median']}%")
    p = macro("pass", {"infantry": 2000}, {"infantry": 2000}, d_formed=True)
    check("隘口守方照旧占优", p["attacker_win_rate"] < 0.2, f"攻方胜率 {p['attacker_win_rate']}")


# ------------------------------------------------------------------ 战术
def field(units, sectors=None, sunset=10):
    st = {"title": "测试", "seed": 1, "sunset": sunset, "weather": {},
          "sectors": sectors or {"左": {"gap": 2}, "中": {"gap": 1}, "右": {"gap": 2}},
          "sides": {"A": {"name": "甲"}, "B": {"name": "乙"}}, "units": units}
    return tc.normalize_state(st)


def one_tick(st, orders, seed):
    st = copy.deepcopy(st)
    st["seed"] = seed
    tc.run_tick(st, orders)
    return st


def cav(uid="骑", men=1000, line="front", sector="中", **kw):
    return dict({"id": uid, "side": "A", "type": "light_cav", "men": men, "morale": 80, "sector": sector,
                 "line": line}, **kw)


def spear(uid="枪", men=1000, formation="严整", **kw):
    return dict({"id": uid, "side": "B", "type": "spear", "men": men, "morale": 75, "sector": "中",
                 "line": "front", "formation": formation}, **kw)


def tactical_tests():
    print("== 战术模块 ==")
    # 1. 正面冲严整枪阵
    base = field([cav(), spear()])
    broke = att_loss = def_loss = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
        c, p = tc.find(s, "骑"), tc.find(s, "枪")
        broke += p["formation"] in ("混乱", "溃散")
        att_loss += 1000 - c["men"]
        def_loss += 1000 - p["men"]
    check("轻骑正面冲严整枪阵冲不动、自损多于对方", broke / N < 0.05 and att_loss > 2 * def_loss,
          f"冲乱 {broke / N:.0%}，骑兵平均伤 {att_loss / N:.0f}，枪阵平均伤 {def_loss / N:.0f}")

    # 2. 冲松动的枪阵
    base = field([cav(), spear(formation="松动")])
    pressed = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
        pressed += tc.find(s, "枪")["formation"] in ("混乱", "溃散")
    check("冲松动的枪阵能冲动", pressed / N > 0.6, f"把枪阵冲到混乱或溃散 {pressed / N:.0%}")

    # 3. 侧击
    base = field([cav(men=700, line="flank"), spear(men=1500)])
    routed = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
        routed += tc.find(s, "枪")["formation"] == "溃散"
    check("侧击严整枪阵大多冲垮", routed / N > 0.6, f"700 骑侧击 1500 枪，溃散 {routed / N:.0%}")

    # 4. 转向迎敌后侧击失效
    base = field([cav(men=700, line="flank"), spear(men=1500, facing="侧面")])
    routed = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
        routed += tc.find(s, "枪")["formation"] == "溃散"
    check("枪阵转向侧面后，侧击变成正面冲击", routed / N < 0.05, f"溃散 {routed / N:.0%}")

    # 5. 追击溃兵
    def pursue_loss(ptype):
        base = field([dict(cav(), type=ptype), spear(formation="溃散", line="back")])
        tot = 0
        for i in range(N):
            s = one_tick(base, {"A": [{"unit": "骑", "order": "pursue", "target": "枪"}]}, i)
            u = tc.find(s, "枪")
            tot += u["killed"] + u["captured"]
        return tot / N
    lc, ft = pursue_loss("light_cav"), pursue_loss("spear")
    check("轻骑追溃兵杀伤远大于步兵追击", lc > 2.5 * ft, f"一刻之内溃兵被杀、被俘：轻骑追 {lc:.0f}，步兵追 {ft:.0f}")

    # 6. 弓弩射密集阵、射骑射
    base = field([dict(cav(uid="弩"), type="crossbow", men=1000), spear(),
                  dict(cav(uid="骑射"), side="B", type="horse_archer", sector="左", men=1000)],
                 sectors={"左": {"gap": 1}, "中": {"gap": 1}, "右": {"gap": 2}})
    loose = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "弩", "order": "shoot", "target": "枪"}]}, i)
        loose += tc.find(s, "枪")["formation"] != "严整"
    check("弩射严整枪阵能把阵形射松", 0.15 < loose / N < 0.7, f"一刻射松 {loose / N:.0%}")
    a2 = field([dict(cav(uid="弓"), type="archer", men=1000), spear(),
                dict(cav(uid="骑射"), side="B", type="horse_archer", men=1000)])
    k_sp = k_ha = 0
    for i in range(N):
        s = one_tick(a2, {"A": [{"unit": "弓", "order": "shoot", "target": "枪"}]}, i)
        k_sp += 1000 - tc.find(s, "枪")["men"]
        s = one_tick(a2, {"A": [{"unit": "弓", "order": "shoot", "target": "骑射"}]}, i)
        k_ha += 1000 - tc.find(s, "骑射")["men"]
    check("弓箭射散开的骑射效果差", k_ha < 0.5 * k_sp, f"射枪阵平均杀伤 {k_sp / N:.0f}，射骑射 {k_ha / N:.0f}")

    # 7. 弓弩被近身
    base = field([cav(), dict(spear(uid="弓"), type="archer")])
    routed = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "弓"}]}, i)
        routed += tc.find(s, "弓")["formation"] in ("混乱", "溃散")
    check("没有掩护的弓手被骑兵冲到就垮", routed / N > 0.9, f"冲乱或冲溃 {routed / N:.0%}")

    # 8. 骑射磨步阵：杀伤不大，但阵形会松
    base = field([dict(cav(uid="骑射"), type="horse_archer", men=1000), spear()])
    loose = kill = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑射", "order": "shoot", "target": "枪"}]}, i)
        sp = tc.find(s, "枪")
        loose += sp["formation"] != "严整"
        kill += 1000 - sp["men"]
    check("骑射对步阵是消耗：杀伤小，能磨松阵形", kill / N < 40 and loose / N > 0.1,
          f"一刻平均杀伤 {kill / N:.0f}，射松 {loose / N:.0%}")
    # 步兵追不上骑射
    s = one_tick(base, {"B": [{"unit": "枪", "order": "attack", "target": "骑射"}]}, 1)
    check("步兵逼近骑射，骑射退开", tc.find(s, "骑射")["men"] == 1000,
          f"骑射剩 {tc.find(s, '骑射')['men']}")

    # 9. 士气连锁
    units = [cav(men=900, line="flank"), spear(men=800, morale=60),
             spear(uid="邻翼", men=800, morale=46, sector="左"),
             dict(spear(uid="后队", men=500, morale=48), line="back", type="militia")]
    base = field(units)
    chain = 0
    for i in range(N):
        s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
        if tc.find(s, "枪")["formation"] == "溃散":
            chain += sum(tc.find(s, k)["formation"] == "溃散" for k in ("邻翼", "后队")) > 0
    check("一部溃散会牵连邻近部队", chain > 0, f"{N} 次里有 {chain} 次牵连")

    # 10. 护甲、操练（rules/tactics.md 第二节、第四节）
    def charge_loss(units):
        base = field(units)
        a = d = 0
        for i in range(N):
            s = one_tick(base, {"A": [{"unit": "骑", "order": "charge", "target": "枪"}]}, i)
            a += 1000 - tc.find(s, "骑")["men"]
            d += 1000 - tc.find(s, "枪")["men"]
        return a / N, d / N
    hv = cav(type="heavy_cav", drill="elite")
    la, ld = charge_loss([hv, spear(formation="混乱", type="infantry")])
    check("具装精锐冲乱阵：自损百分之一二，对方大溃", la <= 20 and ld > 300, f"具装伤 {la:.0f}，步卒伤 {ld:.0f}")
    fa, _ = charge_loss([hv, spear()])
    check("具装冲严整枪阵自损比冲乱阵多", fa > 1.4 * la, f"冲严整 {fa:.0f}，冲乱阵 {la:.0f}")

    def shot(ttype, **kw):
        base = field([dict(cav(uid="弓"), type="archer"), dict(spear(uid="靶"), type=ttype, **kw)])
        k = 0
        for i in range(N):
            s = one_tick(base, {"A": [{"unit": "弓", "order": "shoot", "target": "靶"}]}, i)
            k += 1000 - tc.find(s, "靶")["men"]
        return k / N
    kh, kl, kh2 = shot("heavy_cav"), shot("light_cav"), shot("light_cav", armor="barded")
    check("弓箭射具装打大折扣", kh < 0.5 * kl and kh2 < 0.5 * kl,
          f"一刻杀伤：射具装 {kh:.0f}，射轻骑 {kl:.0f}，射披了人马俱甲的轻骑 {kh2:.0f}")

    # 11. 示范战例能跑完
    here = os.path.dirname(os.path.abspath(__file__))
    st = tc.normalize_state(tc.load(os.path.join(here, "..", "rules", "tactics_example.json")))
    res = None
    for _ in range(20):
        _, res = tc.run_tick(st, {"A": [{"unit": "全军", "order": "hold"}]})
        if res:
            break
    check("示范战例双方坚守，日落收兵", res is not None and res["winner"] == "draw", f"{res and res['outcome']}")


if __name__ == "__main__":
    macro_tests()
    tactical_tests()
    print("\n全部通过" if not fails else f"\n不符：{fails}")
    sys.exit(1 if fails else 0)
