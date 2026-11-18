#!/usr/bin/env python3
"""见闻种子、小人物名册、支线到期提醒。规则见 rules/vignettes.md。只用标准库。

  抽种子   python3 scripts/vignette.py [--seed N] [--count N] [--intel | --no-intel] [--war] [--apply]
  名册     python3 scripts/vignette.py person show [名字]
           python3 scripts/vignette.py person add --name 名 --role 身份 --where 所在 --trait 一句特征 --event 出场 [--apply]
           （新人最好直接用 scripts/persona.py gen：同样记进名册，还按身份表生成属性，见 rules/people.md）
           python3 scripts/vignette.py person seen 名 --event 出场 [--where 新所在] [--apply]
  支线     python3 scripts/vignette.py threads        # 列出进行中的支线，标出到期、过期的
  家事     python3 scripts/vignette.py --family [--seed N] [--count N] [--war] [--apply]
           # 从 world/household.json 抽家里的人和事（rules/household.md 第七节）；战事季写成一封家书

种子只给素材：一个人物、一个地点、一个季节细节、一条眼下的局势张力，可选一条带情报的真实信息。
小景由 GM 依种子现写，不从事件库里取。--apply 把用过的种子记进 world/vignette_log.json，下次避开。
--world 指向别的存档目录（试验用）。
"""
import argparse
import glob
import json
import os
import random
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scenario_lib as S  # noqa: E402

# 下面几张素材表是引擎的默认值，写得尽量不带地域。剧本可在 scenario.json 的 flavor 里整张替换
# （season_details、spots、new_faces、family_spots、family_details），见 scenarios/README.md。

# 季节细节：只是眼前的景物和日常，供小景落笔，不是事件。
SEASON_DETAILS = {
    "春": ["河冰刚开，渡口的船家在补船底", "风大，城头的旗子扯得笔直", "田里在撒种，牛不够用", "柳条才绿，营里有人折了插在帐门口",
           "青黄不接，市上粮价往上走", "雁往北飞，村里在给牛犊上鼻环", "春汛涨了，路上泥深"],
    "夏": ["日头毒，午后街上没人", "麦子黄了，城外在抢收", "雷雨说来就来，营墙塌了一角", "蚊蝇多，伙房门口熏着艾草",
           "瓜熟了，兵卒拿铜钱跟农户换瓜", "马掉膘，马夫赶着往河边放", "井水浅了，打水要排队"],
    "秋": ["新麦晒在城墙根下", "雁往南飞，天高得发白", "马肥了，营里在试新鞍", "家家在腌菜、晒枣",
           "赋税收上来，衙门口排着长队", "夜里已经冷，哨兵换上了夹袄", "猎户进城卖狐皮"],
    "冬": ["雪下了一夜，校场上扫出一条路", "河冻实了，车马直接从冰上过", "炭贵，城里人拆旧屋的木头烧火", "年关近了，市上有卖桃符的",
           "冻伤的兵卒挤在伙房烤火", "乡下人赶着猪羊进城换盐", "夜长，营里有人讲古"],
}

# 地点的小去处，按地形挑。
SPOTS = {
    "city": ["城门洞", "市集", "衙署廊下", "酒肆", "军营伙房", "校场边", "城墙马道", "寺门前", "驿馆", "粮仓"],
    "steppe": ["驿站", "渡口", "烽燧", "田头", "牧场", "商队歇脚的井边", "边市"],
    "mountain": ["山口烽燧", "山民的草棚外", "马场", "山道上的茶棚", "猎户的窝棚", "溪边"],
}

# 新面孔的身份。GM 起名，写进名册。
NEW_FACES = ["驿卒", "织户", "马贩", "老卒", "伙夫", "烽子", "渡口船家", "牧人", "行商", "游方僧", "军中寡妇",
             "衙门小吏", "乡塾先生", "货郎", "降卒", "逃户", "铁匠", "医工", "说书人", "随军的少年", "采桑女",
             "当铺掌柜", "账房", "斥候", "守仓的老兵"]

KNOWING = [
    ("亲眼所见", "只说他自己看见的那一截：人数、旗号、方向，大概对，细节有出入"),
    ("听人转述", "转了一两手，人数可以差到五成上下，时间说得含糊"),
    ("市井传言", "大意沾边，但会添油加醋，或者把两件事说成一件"),
]


def die(msg):
    sys.exit(f"错误：{msg}")


class W:
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

    def text(self, name):
        try:
            with open(self.p(name), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def save(self, name, data):
        with open(self.p(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")


# ---------- 素材池 ----------

def own_faction(w):
    return S.own_faction(w.dir)


def table(w, key, default):
    """剧本 flavor 里有这张表就用剧本的，否则用引擎默认。"""
    v = S.flavor(w.dir, key)
    return v if v else default


def owned_regions(w, regions):
    own = own_faction(w)
    return [r for r, d in regions.items() if str(d.get("owner", "")).startswith(own)]


def dead_names(w):
    h = w.load("history.json", {})
    return set(h.get("deceased", {})) | set(h.get("departed", {}))


def card_people(w, armies):
    """人格卡里的人物（将领、君主）。"""
    out = []
    cdir = os.path.join(os.path.dirname(w.dir), "characters")
    if not os.path.isdir(cdir):
        cdir = os.path.join(ROOT, "characters")
    dead = dead_names(w)
    own = own_faction(w)
    for path in sorted(glob.glob(os.path.join(cdir, "*.md"))):
        base = os.path.basename(path)
        if base.startswith("_") or base == "README.md":
            continue
        with open(path, encoding="utf-8") as f:
            t = f.read()
        m = re.search(r"^姓名:\s*(\S+)", t, re.M)
        name = m.group(1) if m else base[:-3]
        if name in dead:
            continue
        role = re.search(r"^身份:\s*(\S+)", t, re.M)
        if role and role.group(1) in ("家人", "主角"):
            continue  # 家人走 --family，主角不入见闻
        where = None
        for a in armies.values():
            if str(a.get("commander", "")).startswith(name):
                where = a.get("location")
                if str(a.get("faction", "")).startswith(own):
                    break
        title = re.search(r"^- 官职：(.+)$", t, re.M)
        out.append({"kind": "人格卡", "name": name, "role": (title.group(1) if title else (role.group(1) if role else "")),
                    "where": where, "ref": os.path.relpath(path, ROOT) if path.startswith(ROOT) else path})
    return out


def court_people(w, kingdom, armies, card_names):
    """kingdom.json 里的官员、人才（没有人格卡的幕僚、小官）。"""
    out, seen = [], set(card_names)
    dead = dead_names(w)
    for src, label in (("officials", "官员"), ("talents", "人才")):
        for name, role in kingdom.get(src, {}).items():
            name = name.split(" ")[-1]
            if name in seen or name in dead or name == kingdom.get("player", {}).get("name"):
                continue
            seen.add(name)
            where = None
            for a in armies.values():
                if str(a.get("commander", "")).startswith(name):
                    where = a.get("location")
            short = re.split(r"[（(，,；;]", str(role))[0][:30]
            out.append({"kind": label, "name": name, "role": short, "where": where, "ref": f"kingdom.json {src}"})
    return out


def roster_people(w):
    roster = w.load("people.json", {"people": []})
    return [{"kind": "名册", "name": p["name"], "role": p.get("role", ""), "where": p.get("where"),
             "trait": p.get("trait", ""), "seen": len(p.get("appearances", [])), "ref": "people.json"}
            for p in roster.get("people", []) if p.get("status", "在") == "在"]


def tensions(w, kingdom, armies, factions):
    out = []
    for s in kingdom.get("intel", [])[-6:]:
        out.append(("近来消息", s))
    for k, v in kingdom.get("unrest", {}).items():
        out.append(("民情", f"{k}：{v}"))
    own = own_faction(w)
    for name, a in armies.items():
        if str(a.get("faction", "")).startswith(own) and a.get("morale", 100) < 65:
            out.append(("军心", f"{name}在{a.get('location')}，士气低（{a.get('morale')}），{a.get('status', '')}"))
    for k, f in factions.items():
        att = str(f.get("attitude_to_player", ""))
        if "已灭" in att:
            continue
        if any(x in att for x in ("敌", "观望", "分化", "叵测")):
            out.append(("邻境", f"{k}（{f.get('leader', '')}）：{att}；{f.get('note', '')[:60]}"))
    for t in open_threads(w):
        out.append(("支线", f"[{t['id']}] {t['title']}：{t.get('悬念', '')}"))
    for line in w.text("pending_orders.md").splitlines():
        if line.startswith("- "):
            out.append(("待办", line[2:].strip()))
    d = w.load("directives.json", {})
    for cname, xs in d.get("last_settlement", {}).get("exceptions", {}).items():
        for x in xs:
            out.append(("方面", f"{cname}：{x}"))
    # 庙堂：传开了的流言、悬而未决的议题、党争（rules/rumors.md、rules/court.md）
    heat_words = ["无人提起", "私下耳语", "小范围流传", "传开了", "人人在说", "满城风雨"]
    for r in w.load("rumors.json", {}).get("rumors", []):
        if r.get("status") in ("流传", "坐实"):
            hot = [(c, h) for c, h in r.get("heat", {}).items() if h >= 2]
            if hot:
                out.append(("流言", f"{r['text']}（{'、'.join(f'{c}{heat_words[min(h, 5)]}' for c, h in hot)}）"))
    court = w.load("court.json", {})
    for k, iss in court.get("issues", {}).items():
        if not str(iss.get("status", "")).startswith("已决"):
            out.append(("朝议", f"{iss.get('title', k)}：{iss.get('status', '悬而未决')}"))
    for k, f in court.get("feuds", {}).items():
        if f.get("level", "相安") != "相安":
            out.append(("党争", f"{k.replace('|', '与')}：{f['level']}"))
    return out


def intel_pool(w, armies, factions):
    """带情报的见闻可取的真实信息：gm_secrets 的条目、敌对和观望势力的军队动向。"""
    out = []
    sec = w.text("gm_secrets.md")
    section = ""
    gone = dead_names(w)
    for line in sec.splitlines():
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
        elif line.startswith("- ") and len(line) > 12:
            if any(n in section for n in gone):
                continue  # 人已死或已离去，这条秘密不再起作用
            out.append(("隐情", f"{section}｜{line[2:].strip()}"))
    for x in w.load("secrets.json", {}).get("secrets", []):
        if x.get("status") == "隐":
            kn = "、".join(k["name"] for k in x.get("knowers", [])) or "无"
            out.append(("隐情", f"{x['title']}｜{x['truth']}（secrets.json {x['id']}，知情人：{kn}。种子人物不在其中的，"
                                 f"只能写成他从知情人身边听来的一点风声；写进去了就照 secrets.py learn 记他风闻）"))
    own = own_faction(w)
    for name, a in armies.items():
        fac = str(a.get("faction", ""))
        if fac.startswith(own) or "归附" in fac:
            continue
        n = sum(v for v in a.get("units", {}).values() if v)
        out.append(("敌军动向", f"{name}（{fac}）约 {n} 人在{a.get('location')}，{a.get('status', '')}；主将 {a.get('commander', '')}"))
    return out


# ---------- 支线 ----------

THREAD_RE = re.compile(r"^### \[(T\d+)\]\s*(.+)$", re.M)


def open_threads(w):
    text = re.sub(r"<!--.*?-->", "", w.text("threads.md"), flags=re.S)
    out = []
    parts = THREAD_RE.split(text)
    # parts: [前言, id, 标题, 正文, id, 标题, 正文, ...]
    for i in range(1, len(parts) - 2, 3):
        tid, title, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        fields = {}
        for line in body.splitlines():
            m = re.match(r"^- (\S+?)：(.*)$", line.strip())
            if m:
                fields[m.group(1)] = m.group(2).strip()
        t = {"id": tid, "title": title, **fields}
        if not fields.get("状态", "进行中").startswith(("已了结", "作罢")):
            out.append(t)
    return out


def cmd_threads(w, args):
    k = w.load("kingdom.json")
    turn = k.get("turn", 0)
    ts = open_threads(w)
    print(f"=== 进行中的支线（第 {turn} 回合，{k.get('date', '')}） ===")
    if not ts:
        print("  （无）")
    for t in ts:
        m = re.search(r"第\s*(\d+)\s*回合", t.get("最迟", ""))
        due = int(m.group(1)) if m else None
        tag = ""
        if due is not None:
            tag = "【已过期，本季须了结】" if turn > due else "【本季到期】" if turn == due else f"（还剩 {due - turn} 季）"
        print(f"  [{t['id']}] {t['title']}｜{t.get('状态', '进行中')}｜最迟 {t.get('最迟', '未定')} {tag}")
        if t.get("悬念"):
            print(f"      悬念：{t['悬念']}")


# ---------- 抽种子 ----------

def is_war_season(k):
    les = k.get("last_economy_settlement", {})
    return bool(les.get("war")) and les.get("turn") == k.get("turn")


def draw(w, args):
    k = w.load("kingdom.json")
    regions = w.load("map.json")["regions"]
    armies = w.load("armies.json")["armies"]
    factions = w.load("factions.json", {"factions": {}}).get("factions", {})
    log = w.load("vignette_log.json", {"used": []})
    used = log.get("used", [])
    seed = args.seed if args.seed is not None else int(time.time()) % 100000
    rng = random.Random(seed)
    season = k.get("season") or (k.get("date", " 春").split()[-1])
    war = args.war or is_war_season(k)
    count = args.count or (1 if war else 2)
    places = owned_regions(w, regions) or list(regions)
    cards = card_people(w, armies)
    court = court_people(w, k, armies, [c["name"] for c in cards])
    roster = roster_people(w)
    tens = tensions(w, k, armies, factions)
    intel = intel_pool(w, armies, factions)

    recent_people = [u.get("person") for u in used[-6:]]
    recent_tension = [u.get("tension") for u in used[-4:]]
    recent_detail = [u.get("detail") for u in used[-4:]]
    used_intel = {u.get("intel") for u in used if u.get("intel")}
    used_pairs = {(u.get("person"), u.get("place")) for u in used}

    seeds = []
    for i in range(count):
        want_intel = args.intel if args.intel is not None else rng.random() < (0.25 if not war else 0.4)
        for _try in range(60):
            r = rng.random()
            if want_intel:
                r *= 0.7   # 带情报的，多半让小人物来说
            if r < 0.4 or not (cards or court or roster):
                role = rng.choice(table(w, "new_faces", NEW_FACES))
                person = {"kind": "新面孔", "name": None, "role": role, "where": None}
            elif r < 0.65 and roster:
                person = rng.choice(roster)
            else:
                person = rng.choice(cards + court) if (cards or court) else rng.choice(roster)
            key = person["name"] or person["role"]
            if key in recent_people or key in [s["key"] for s in seeds]:
                continue
            where = person.get("where")
            region = next((x for x in places if where and x in where), None)
            if region is None and person["kind"] in ("官员", "人才") and rng.random() < 0.5:
                seat = k.get("player", {}).get("seat")
                region = seat if seat in places else None
            if region is None or rng.random() < 0.3:
                region = rng.choice(places)
            terrain = regions.get(region, {}).get("terrain", "city")
            spots = table(w, "spots", SPOTS)
            spot = rng.choice(spots.get(terrain) or spots.get("city") or SPOTS["city"])
            place = f"{region}·{spot}"
            if (key, place) in used_pairs:
                continue
            fresh = [t for t in tens if t[1] not in recent_tension and t[1] not in [s["tension"][1] for s in seeds]]
            tension = rng.choice(fresh or tens) if tens else ("日常", "无事。写日子本身")
            itm = None
            if want_intel:
                pool = [x for x in intel if x[1] not in used_intel and x[1] not in [s.get("intel_text") for s in seeds]]
                if pool:
                    # 和这个地方、近邻、这个人沾边的消息，抽中的机会大三倍
                    near = {region, *regions.get(region, {}).get("adjacent", [])}
                    if person.get("name"):
                        near.add(person["name"])
                    wts = [3 if any(n in x[1] for n in near) else 1 for x in pool]
                    itm = rng.choices(pool, weights=wts)[0]
            sd = table(w, "season_details", SEASON_DETAILS)
            details = sd.get(season) or SEASON_DETAILS.get(season) or SEASON_DETAILS["春"]
            taken = recent_detail + [x["detail"] for x in seeds]
            detail = rng.choice([x for x in details if x not in taken] or details)
            know = rng.choice(KNOWING) if itm else None
            seeds.append({"key": key, "person": person, "place": place, "region": region,
                          "detail": detail,
                          "tension": tension, "intel": itm, "intel_text": itm[1] if itm else None, "know": know})
            break
    return k, seed, war, seeds, log


def cmd_draw(w, args):
    k, seed, war, seeds, log = draw(w, args)
    print(f"=== 见闻种子：{k.get('date', '')}（第 {k.get('turn')} 回合），seed={seed}，"
          f"{'战事季，建议写 0–1 段' if war else '太平季，建议写 1–2 段'} ===")
    cn = "一二三四五六七八九十"
    for i, s in enumerate(seeds):
        p = s["person"]
        print(f"\n[{cn[i]}]")
        if p["kind"] == "新面孔":
            print(f"  人物：新面孔——{p['role']}（GM 起名，写完用 persona.py gen 名 --role 身份 --apply 记进名册）")
        else:
            extra = f"；特征：{p['trait']}；已出场 {p['seen']} 次" if p.get("trait") else ""
            print(f"  人物：{p['name']}（{p['kind']}：{p['role']}{extra}）  出处：{p['ref']}")
        print(f"  地点：{s['place']}")
        print(f"  季节：{s['detail']}")
        print(f"  张力：〔{s['tension'][0]}〕{s['tension'][1]}")
        if s["intel"]:
            print(f"  情报（真实，只给 GM）：〔{s['intel'][0]}〕{s['intel'][1]}")
            print(f"  知情程度：{s['know'][0]}——{s['know'][1]}")
            print("  迷雾：只写这个人在这个地方合理能见到、听到的部分；不知道的就不说。")
        else:
            print("  情报：无（纯人物小景）")
    if not seeds:
        print("\n（素材都用过了，或者存档里没有可用的人物、地点。）")
    if args.apply:
        for s in seeds:
            log.setdefault("used", []).append({
                "turn": k.get("turn"), "date": k.get("date"), "seed": seed, "person": s["key"],
                "place": s["place"], "detail": s["detail"], "tension": s["tension"][1], "intel": s["intel_text"]})
        log["used"] = log["used"][-200:]
        w.save("vignette_log.json", log)
        print(f"\n已记入 {w.p('vignette_log.json')}。")
    else:
        print("\n（未记入用过的种子。定稿后加 --apply 同一 seed 再跑一次。）")


# ---------- 家事 ----------

FAMILY_SPOTS = ["后宅廊下", "灶间", "佛堂", "后园井边", "马厩", "书房门口", "绣房", "城外庄子", "寺里进香的路上",
                "校场边", "门房", "药铺", "城头", "河边洗衣的石阶"]
FAMILY_DETAILS = {
    "春": ["院里的杏花开了，孩子们在树下捡花", "换下冬衣，箱笼摊了一院子", "清明上坟，香烛纸钱备在廊下",
           "燕子回来，在檐下垒窝", "春寒，母亲屋里还生着炭盆"],
    "夏": ["井里湃着瓜", "午后蝉吵得人睡不着", "晒书、晒衣，竹竿架满了院子", "雨后后园的墙根长了青苔",
           "端午，门上插了艾，孩子腕上系着五色线"],
    "秋": ["后园的枣熟了，打枣的竿子靠在墙上", "腌菜的缸摆在灶间门口", "中秋，月饼供在桌上", "做冬衣，裁缝进了后宅",
           "重阳，母亲要登城头看一看"],
    "冬": ["屋里生着炭盆，窗纸上结了霜花", "腊八，灶间熬着粥", "年关近了，后宅在扫尘、剪窗花", "下了雪，孩子在院里堆雪",
           "守岁，一家人围着火盆"],
}
LETTER_HOOKS = ["信里只说家里都好", "信末添了孩子歪歪扭扭的几个字", "信里夹着一样东西（一缕头发、一片干花、一道平安符）",
                "信写到一半换了一种墨，像是隔了几天才写完", "信里有一句没写完的话被涂掉了"]


def family_draw(w, args):
    import household as H  # 同目录
    hw = H.World(w.dir)
    hh = hw.hh
    k = hw.kingdom
    turn = k.get("turn", 1)
    log = w.load("vignette_log.json", {"used": []})
    used = log.get("used", [])
    seed = args.seed if args.seed is not None else int(time.time()) % 100000
    rng = random.Random(seed)
    war = args.war or is_war_season(k) or bool(H.protagonist_away(hw))
    count = args.count or (1 if war else 2)
    season = k.get("season") or H.year_of(hh, turn)[1]
    ms = {mid: m for mid, m in hw.members().items() if H.alive(m)}
    if not ms:
        return k, seed, war, [], log
    tens = H.family_tensions(hw)
    recent = [u.get("person") for u in used if u.get("family")][-3:]
    seeds = []
    for _ in range(count):
        cands = [mid for mid in ms if ms[mid]["name"] not in recent and mid not in [s["mid"] for s in seeds]]
        if not cands:
            cands = list(ms)
        wts = []
        for mid in cands:
            m = ms[mid]
            n = sum(1 for t in tens if t[2] == mid and t[0] != "日常")
            a = H.age(hh, m, turn)
            wts.append((1 + n) * (0.5 if a < 3 else 1))
        mid = rng.choices(cands, weights=wts)[0]
        m = ms[mid]
        mine = [t for t in tens if t[2] == mid]
        others = [t for t in tens if t[2] != mid and t[0] != "日常"]
        pool = [t for t in mine if t[0] != "日常"] or mine or others
        tension = rng.choice(pool) if pool else ("日常", "无事。写日子本身", mid)
        fd = table(w, "family_details", FAMILY_DETAILS)
        details = fd.get(season) or FAMILY_DETAILS.get(season) or FAMILY_DETAILS["春"]
        taken = [u.get("detail") for u in used[-4:]] + [s["detail"] for s in seeds]
        detail = rng.choice([x for x in details if x not in taken] or details)
        if war:
            form = "家书"
            where = hh.get("protagonist", {}).get("where", "?")
            spot = (f"写给主角，送到{where}军中" if H.protagonist_away(hw)
                    else f"写给主角，送到衙署（战事吃紧，主角宿在{where}衙署、军营，不回后宅）")
            hook = rng.choice(LETTER_HOOKS)
        else:
            form = "小景"
            spot = f"{H.region_of(m.get('residence')) or S.seat(w.dir)}·{rng.choice(table(w, 'family_spots', FAMILY_SPOTS))}"
            hook = None
        seeds.append({"mid": mid, "m": m, "age": H.age(hh, m, turn), "detail": detail, "tension": tension,
                      "form": form, "spot": spot, "hook": hook})
    return k, seed, war, seeds, log


def cmd_family(w, args):
    k, seed, war, seeds, log = family_draw(w, args)
    print(f"=== 家事种子：{k.get('date', '')}（第 {k.get('turn')} 回合），seed={seed}，"
          f"{'战事季或主角在外，写成一封家书' if war else '太平季，写 1–2 段'} ===")
    cn = "一二三四五六七八九十"
    for i, s in enumerate(seeds):
        m = s["m"]
        print(f"\n[{cn[i]}] {s['form']}")
        print(f"  人物：{m['name']}（{m.get('relation')}，{s['age']} 岁；{m.get('trait', '')}）"
              + (f"  人格卡：{m['card']}" if m.get("card") else "  （没有人格卡）"))
        print(f"  在忙：{m.get('busy') or '—'}；身体：{m.get('health', '健朗')}")
        print(f"  地点：{s['spot']}")
        print(f"  季节：{s['detail']}")
        print(f"  家事：〔{s['tension'][0]}〕{s['tension'][1]}")
        if s["hook"]:
            print(f"  信的样子：{s['hook']}")
        print("  写法：白描，一两样具体的东西；亲疏写成举动，不点破。只写家里人能知道的事。")
    if not seeds:
        print("\n（household.json 里没有人。）")
    if args.apply:
        for s in seeds:
            log.setdefault("used", []).append({
                "turn": k.get("turn"), "date": k.get("date"), "seed": seed, "family": True, "person": s["m"]["name"],
                "place": s["spot"], "detail": s["detail"], "tension": s["tension"][1], "intel": None})
        log["used"] = log["used"][-200:]
        w.save("vignette_log.json", log)
        print(f"\n已记入 {w.p('vignette_log.json')}。")
    else:
        print("\n（未记入用过的种子。定稿后加 --apply 同一 seed 再跑一次。）")


# ---------- 名册 ----------

def cmd_person(w, args):
    roster = w.load("people.json", {"people": []})
    people = roster.setdefault("people", [])
    k = w.load("kingdom.json", {})
    when = f"{k.get('date', '')}（第 {k.get('turn', '?')} 回合）"
    if args.action == "show":
        for p in people:
            if args.name and p["name"] != args.name:
                continue
            attrs = "有属性" if p.get("persona") else "还没有属性"
            print(f"{p['name']}｜{p.get('role', '')}｜{p.get('where', '')}｜{p.get('trait', '')}｜{p.get('status', '在')}｜{attrs}")
            for a in p.get("appearances", []):
                print(f"    {a}")
            if p.get("card"):
                print(f"    人格卡：{p['card']}")
        if not people:
            print("（名册还是空的）")
        return
    p = next((x for x in people if x["name"] == args.name), None)
    if args.action == "add":
        if p:
            die(f"名册里已有“{args.name}”，再出场用 person seen")
        if not (args.role and args.where and args.trait):
            die("新增要给 --role、--where、--trait")
        p = {"name": args.name, "role": args.role, "where": args.where, "trait": args.trait,
             "status": "在", "appearances": [], "card": None}
        people.append(p)
    elif args.action == "seen":
        if not p:
            die(f"名册里没有“{args.name}”，先 persona.py gen（或 person add）")
        if args.where:
            p["where"] = args.where
        if args.role:
            p["role"] = args.role
    if args.event:
        p["appearances"].append(f"{when}：{args.event}")
    if args.card:
        p["card"] = args.card
    if args.status:
        p["status"] = args.status
    print(json.dumps(p, ensure_ascii=False, indent=2))
    if args.action == "add":
        print(f"提示：新人要有属性。改用（或接着跑）python3 scripts/persona.py gen {args.name} --role {args.role} --apply"
              "（rules/people.md）；已在名册里的人，gen 只补属性，不动别的字段。")
    if args.apply:
        w.save("people.json", roster)
        print(f"已写入 {w.p('people.json')}。")
    else:
        print("（未写名册。确认后加 --apply。）")


def main():
    ap = argparse.ArgumentParser(description="见闻种子与小人物名册（规则见 rules/vignettes.md）",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=os.path.join(ROOT, "world"))
    ap.add_argument("--seed", type=int)
    ap.add_argument("--count", type=int, help="抽几颗种子；默认太平季 2、战事季 1")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--intel", dest="intel", action="store_true", default=None, help="每颗都带情报")
    g.add_argument("--no-intel", dest="intel", action="store_false", help="都不带情报")
    ap.add_argument("--war", action="store_true", help="按战事季处理（默认看本季经济结算有没有战乱州）")
    ap.add_argument("--family", action="store_true", help="抽家事种子（world/household.json）")
    ap.add_argument("--apply", action="store_true")
    sp = ap.add_subparsers(dest="cmd")
    p = sp.add_parser("person")
    p.add_argument("action", choices=("show", "add", "seen"))
    p.add_argument("name", nargs="?")
    p.add_argument("--name", dest="name_opt")
    p.add_argument("--role")
    p.add_argument("--where")
    p.add_argument("--trait")
    p.add_argument("--event")
    p.add_argument("--card", help="长成人物、建了人格卡后填路径")
    p.add_argument("--status", help="在 / 死 / 离去")
    p.add_argument("--apply", action="store_true", dest="p_apply")
    sp.add_parser("threads")
    args = ap.parse_args()
    w = W(os.path.abspath(args.world))
    if args.cmd == "person":
        args.name = args.name or args.name_opt
        args.apply = args.apply or args.p_apply
        if args.action != "show" and not args.name:
            die("要给名字")
        cmd_person(w, args)
    elif args.cmd == "threads":
        cmd_threads(w, args)
    elif args.family:
        cmd_family(w, args)
    else:
        cmd_draw(w, args)


if __name__ == "__main__":
    main()
