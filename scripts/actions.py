#!/usr/bin/env python3
"""本季的行动件数：主角是臣子时，每季亲自做的事有个数（上奏、拜访、密谈、托人、写要紧的信、自己起意的场景）。
规则见 rules/court.md 第九节、rules/scene.md 第五节。只用标准库。

存档是 world/actions.json，按回合记。会改存档的命令默认只打印，加 --apply 才写回。
上限：太平季 3 件、事多的季 2 件；剧本可在 scenario.json 的 actions 里改（cap_peace、cap_busy）。
交下来的差事是本分，不占件数（--duty 记一笔，不算数）；家事另算（household.py visit）。
大的事（跨一夜一日以上的场景、朝会上出班上奏这一类）算两件（--weight 2）。超出上限不拦，打印提醒，GM 先和玩家商量。

  看本季   show [--turn N]
  记一件   add --what 做了什么 --kind 上奏|拜访|密谈|托人|写信|场景|较量|其他 [--weight 1|2] [--duty] [--ref 场景编号]
  去掉     drop 序号 [--why …]
  事多     mode 太平|事多 --why …          本季事多（朝中出了大事、在办急差）上限降到 2

主角是一方之主的（player.role 不是“臣子”），本脚本只记账，上限看 governance.py council。所有命令都有 --world。
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenario_lib as S  # noqa: E402
import social_lib as X  # noqa: E402

FILE = "actions.json"
EMPTY = {"version": 1, "turns": {}}
KINDS = ("上奏", "拜访", "密谈", "托人", "写信", "场景", "较量", "其他")
MODES = ("太平", "事多")


class Book:
    def __init__(self, world, turn=None):
        self.world = world
        self.d = X.load_json(world, FILE, EMPTY)
        self.d.setdefault("turns", {})
        sc = S.load(world)
        cfg = sc.get("actions") or {}
        self.caps = {"太平": int(cfg.get("cap_peace", 3)), "事多": int(cfg.get("cap_busy", 2))}
        self.vassal = (sc.get("player") or {}).get("role") == "臣子"
        self.turn = turn or X.turn_of(world)
        self.when = X.when_of(world)

    def season(self, turn=None):
        t = str(turn or self.turn)
        return self.d["turns"].setdefault(t, {"mode": "太平", "why": "", "items": []})

    def cap(self, turn=None):
        return self.caps[self.season(turn)["mode"]]

    def used(self, turn=None):
        return sum(int(i.get("weight", 1)) for i in self.season(turn)["items"] if not i.get("duty") and not i.get("dropped"))

    def save(self):
        return X.save_json(self.world, FILE, self.d)


def summary_line(B, turn=None):
    s = B.season(turn)
    return f"第 {turn or B.turn} 回合（{s['mode']}季）：已用 {B.used(turn)} / {B.cap(turn)} 件"


def add_item(B, what, kind, weight=1, duty=False, ref=None, force=False):
    """记一件；返回 (条目, 提醒)。scene.py 也调它。"""
    if kind not in KINDS:
        X.die(f"--kind 只有 {'、'.join(KINDS)}")
    s = B.season()
    item = {"no": len(s["items"]) + 1, "what": what, "kind": kind, "weight": 0 if duty else int(weight), "duty": bool(duty),
            "when": B.when}
    if ref:
        item["ref"] = ref
    warn = ""
    after = B.used() + item["weight"]
    if not duty and after > B.cap():
        warn = (f"本季已经用了 {B.used()} 件，上限 {B.cap()} 件（{s['mode']}季），这一件记上就是 {after} 件："
                "先和玩家商量哪几件放到下一季" + ("" if force else "（GM 和玩家商量过的，加 --force 照记）"))
    s["items"].append(item)
    return item, warn


def cmd_show(B, args):
    t = args.turn or B.turn
    s = B.season(t)
    print(f"=== 本季行动：{summary_line(B, t)} ===")
    if not B.vassal:
        print("  （主角是一方之主：帅府亲裁的限额看 governance.py council；这里只记账）")
    if s.get("why"):
        print(f"  事多的缘由：{s['why']}")
    for i in s["items"]:
        tag = "本分，不占件数" if i.get("duty") else ("已去掉" if i.get("dropped") else f"{i['weight']} 件")
        print(f"  {i['no']}. 〔{i['kind']}〕{i['what']}（{tag}）" + (f"  ← {i['ref']}" if i.get("ref") else ""))
    if not s["items"]:
        print("  （本季还没有记）")
    left = B.cap(t) - B.used(t)
    print(f"  还能做 {max(left, 0)} 件。" + ("超了，先和玩家商量。" if left < 0 else ""))


def cmd_add(B, args):
    item, warn = add_item(B, args.what, args.kind, args.weight, args.duty, args.ref, args.force)
    print(f"记一件：〔{item['kind']}〕{item['what']}（{'本分' if item['duty'] else str(item['weight']) + ' 件'}）")
    print(f"  {summary_line(B)}")
    if warn:
        print(f"  提醒：{warn}")
        if not args.force:
            args.apply = False
    finish(B, args)


def cmd_drop(B, args):
    s = B.season()
    it = next((i for i in s["items"] if i["no"] == args.no), None) or X.die(f"本季没有第 {args.no} 件")
    it["dropped"] = True
    it["drop_why"] = args.why or ""
    print(f"去掉第 {args.no} 件：{it['what']}。{summary_line(B)}")
    finish(B, args)


def cmd_mode(B, args):
    s = B.season()
    old = s["mode"]
    s["mode"], s["why"] = args.mode, args.why
    print(f"本季：{old}季 → {args.mode}季（{args.why}）。{summary_line(B)}")
    if B.used() > B.cap():
        print("  提醒：已经记的件数超过了新的上限，和玩家商量哪几件挪到下一季（drop 序号）")
    finish(B, args)


def finish(B, args):
    if getattr(args, "apply", False):
        print(f"\n已写入 {X.rel(B.save())}。")
    else:
        print("\n（未写入。确认后加 --apply。）")


def main():
    ap = argparse.ArgumentParser(description="本季行动件数", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--world", default=X.DEFAULT_WORLD)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, write=True):
        p = sp.add_parser(name)
        p.add_argument("--world", default=argparse.SUPPRESS)
        if write:
            p.add_argument("--apply", action="store_true")
        p.set_defaults(fn=fn)
        return p

    p = add("show", cmd_show, write=False)
    p.add_argument("--turn", type=int)
    p = add("add", cmd_add)
    p.add_argument("--what", required=True)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--weight", type=int, choices=(1, 2), default=1)
    p.add_argument("--duty", action="store_true", help="交下来的差事，本分，不占件数")
    p.add_argument("--ref")
    p.add_argument("--force", action="store_true")
    p = add("drop", cmd_drop)
    p.add_argument("no", type=int)
    p.add_argument("--why")
    p = add("mode", cmd_mode)
    p.add_argument("mode", choices=MODES)
    p.add_argument("--why", required=True)
    args = ap.parse_args()
    args.fn(Book(os.path.abspath(args.world)), args)


if __name__ == "__main__":
    main()
