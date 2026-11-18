# 个人钱物

一方之主有府库；朝中的一个小人物，只有自己身上的几贯钱、一匹马、一口刀，和几件有来历的东西。
这一本账记的就是这个：随身钱、家当、俸钱、兵器、马、随身物件（带着它的故事）、借贷、罚俸。存档是 `world/purse.json`，由 `scripts/purse.py` 读写。

几条底线：

- **钱有数。** 吃一顿酒、打点一个门吏、请一回大夫，都照剧本的物价记一笔。身上的钱不够，脚本不让花：先从家当里取，或者借、当东西。
- **东西有来历。** 一件物件可以挂几段“故事”：谁给的、从哪里来、经过什么事。物件易手，故事跟着走；连着秘密的，GM 知道它落到了谁手里意味着什么。
- **俸钱照阶发。** 有仕途的人，每季照 `court.json` 的仕途阶梯或品级发俸，罚俸的扣掉。
- **默认只打印。** 会改存档的命令加 `--apply` 才写回。场景里花的钱由 `scene.py` 收场时一并写回（`rules/scene.md`）。

本文的例子取自《长安夜》剧本，标作“例（长安夜）”。

---

## 一、单位

剧本 `scenario.json` 的 `purse` 一节：

```json
"purse": {"unit": "文", "big_unit": "贯", "per_big": 1000, "horse_feed": 1800}
```

- 存档里的钱一律记**小单位**（例（长安夜）：文）。命令里可以写 `2贯300文`、`1.5贯`、`300文`、`300`（不带单位的按小单位）。
- `horse_feed`：一匹马一季的马料（小单位）。物件上写了 `feed` 的按物件，公家发的马（`issued`）不算。
- 剧本没有这一节：小单位就是 `terms.money_unit`，不分大小。

## 二、存档：`world/purse.json`

例（长安夜）：

```json
{"version": 1,
 "people": {"白玫": {"cash": 2300, "home": 0, "living": 600,
                     "items": [{"id": "I1", "kind": "物件", "name": "盛威营铜腰牌", "desc": "…", "story": ["祖父留下的"],
                                "value": 50, "where": "随身", "status": "在", "secret": "S9", "log": []}],
                     "fines": [], "stipends": [], "ledger": [], "last_pay_turn": 0}},
 "debts": [], "next": {"I": 8, "D": 1}, "last_season_turn": 0}
```

| 字段 | 说明 |
|---|---|
| `cash` | 随身钱（小单位）。场景里花钱从这里出 |
| `home` | 家当：存在住处、柜坊里的钱。**主角是臣子的，他的家当就是 `kingdom.json` 的 `treasury.money`（以大单位记），不记在这里**；别人的记在这里 |
| `living` | 每季的用度（吃住零花），季末扣。住衙署、吃公家伙食的人可以很少 |
| `items` | 物件：`kind` 兵器 / 马 / 衣甲 / 物件 / 文书；`story` 来历（一段一段）；`value` 约值；`where` 随身 / 家中 / 寄存何处；`status` 在 / 当了 / 卖了 / 送人 / 失 / 毁；`secret` 连着 `secrets.json` 的哪一条（只给 GM）；马另有 `feed`；公家发的写 `issued` |
| `fines` | 罚俸：还剩几季 |
| `stipends` | 每季固定的进项或开销（家里每季寄来的钱、每季寄回家的钱） |
| `ledger` | 流水账，留最近八十笔 |
| `debts` | 借据：借的人、债主、本、欠、每季利、到期回合、状态（未还 / 已还 / 赖账 / 免了） |

主角是臣子时，家当用大单位整数记在 `treasury.money`：从家当里取零钱，脚本取整贯，找零进随身钱；存零钱，整贯存进去，零头留在身上。`treasury.horses` 季末跟着主角名下的马数更新。

---

## 三、俸钱

- 有仕途记录的人（`court.json` 的 `careers`），每季的俸钱：
  - 记了仕途阶梯的（`careers.<名>.ladder`），照阶梯上这一阶的 `pay`（大单位，可以带小数）；
  - 否则照官职的品级，用 `rules/court.md` 第六节的品级表。
- 俸钱进**随身钱**。罚俸中的那一季不发，罚俸的季数减一。
- 每回合只发一次：`purse.py season` 或 `court.py season --pay` 谁先跑谁发，另一个不再发。
- 没有仕途记录的人（家人、商人）没有俸钱；家里寄来的钱记成常例（`stipend`）。

## 四、季末：`purse.py season`

每个人依次：

1. 发俸（还没发的话）；
2. 常例：每季的进项加上，开销扣掉（身上不够的，没付，列给 GM）；
3. 开销：马料（不是公家的马）和用度。身上不够，动家当；家当也不够，列给 GM（借钱、当东西，或者马要饿瘦）；
4. 借据：未还的按每季利息加到欠款上（当季借的不计息）；到期的列出来，债主会来要。

## 五、花钱、给钱、借钱

| 事 | 命令 | 另记 |
|---|---|---|
| 吃喝、打点、药钱、赁屋、买东西 | `spend 名 --amount … --what … [--kind …] [--to 收钱的人]` | 收钱的人有档的，记进他的随身钱 |
| 得钱：赏赐、卖东西、外快 | `earn 名 --amount … --what … [--from 给钱的人]` | |
| 给人钱、给人东西 | `give 甲 --to 乙 --amount … / --item I3 --what … --kind 赏赐|送礼|行贿|周济|还情` | 值三个大单位以上的，脚本提议 `relations.py event 厚赠`；行贿不记恩，办了事照实记，行贿本身可以登记成一条秘密 |
| 存、取 | `move 名 --amount … --to cash|home` | |
| 借钱 | `borrow 名 --from 债主 --amount … [--rate 0.1] [--due 回合] --what …` | 债主有档的，钱从他身上出；没档的（柜坊、寺里的质库）钱从外头来 |
| 还钱 | `repay D1 [--amount …]` | |
| 赖账、免了 | `debt D1 --status 赖账|免了 --why …` | 脚本提议关系网的一笔（背约 / 援手） |
| 当东西、卖东西、丢了、毁了 | `item status I3 --status 当了|卖了|失|毁|在 [--amount 当价] --why …` | 连着秘密的物件，脚本提醒 GM 看它落到了谁手里 |
| 罚俸、罚钱 | `fine 名 --seasons N --why …` / `fine 名 --amount … --why …` | 罚俸是一次处分，照 `rules/court.md` 第六节看器重、心结 |
| 每季固定的进出 | `stipend 名 --amount …（可负） --what …` | |

## 六、物件的故事

- 一件东西入账时写 `--story 来历`；后来又经过了什么事，用 `item story I1 --add …` 再挂一段。
- 东西送人（`item give`）、当掉、丢了，故事跟着走，记在物件的 `log` 里。
- 有的物件本身就是一条秘密的线索（例（长安夜）：白玫身上那块“盛威营”铜腰牌连着秘密 S9）：`secret` 字段只给 GM 看；玩家只知道 `story` 里写的那几句（家里人怎么说的）。这样的物件不登记成秘密的证据，免得情报包里露出来；它被谁看见、落到谁手里，GM 照情形用 `secrets.py learn` 记。

## 七、GM 怎么用

1. 开局：剧本的 `purse.json` 写好主角（和要紧的人）的钱物；`/newgame` 照玩家答的武艺改兵器（`item add`、`item status … --status 卖了` 之类）。
2. 场景里花钱、得东西，用 `scene.py spend / give / earn / item`，收场一并写回；场景外的，直接用 `purse.py`。
3. 写场面时照剧本的物价（例（长安夜）：`scenarios/长安夜/rules/俸钱与物价.md`）给钱数。
4. 季末：`purse.py season`，看过加 `--apply`；`court.py season --pay` 发俸也行（两者不重复发）。
5. 向玩家汇报时，数字表里写随身钱、家当、本季俸钱和开销；欠债、到期写出来。

### 命令一览

```
python3 scripts/purse.py show [名] [--all] | ledger 名 [--n 20]
python3 scripts/purse.py open 名 [--cash 钱] [--home 钱] [--living 钱] [--note …] --apply
python3 scripts/purse.py spend 名 --amount 钱 --what … [--from cash|home] [--to 名] [--kind 吃喝|打点|药钱|赁屋|买物|赏人|其他] --apply
python3 scripts/purse.py earn 名 --amount 钱 --what … [--to cash|home] [--from 名] --apply
python3 scripts/purse.py give 甲 --to 乙 (--amount 钱 | --item 编号) --what … [--kind 赏赐|送礼|行贿|周济|还情] --apply
python3 scripts/purse.py move 名 --amount 钱 --to cash|home --apply
python3 scripts/purse.py item add 名 --kind 兵器|马|衣甲|物件|文书 --name 名称 [--desc …] [--story 来历] [--value 钱] [--where …] [--secret S] [--feed 钱] [--issued] --apply
python3 scripts/purse.py item story 编号 --add … --apply | item set 编号 字段=值 --apply | item give 编号 --to 名 --apply
python3 scripts/purse.py item status 编号 --status 在|当了|卖了|送人|失|毁 [--amount 钱] --why … --apply
python3 scripts/purse.py borrow 名 --from 债主 --amount 钱 [--rate 0.1] [--due 回合] --what … --apply
python3 scripts/purse.py repay 借据 [--amount 钱] --apply | debt 借据 --status 赖账|免了 --why … --apply
python3 scripts/purse.py fine 名 (--seasons N | --amount 钱) --why … --apply
python3 scripts/purse.py stipend 名 --amount 钱 --what … --apply | stipend 名 --remove 序号 --apply
python3 scripts/purse.py pay [名] --apply | season --apply
```

所有命令都有 `--world 目录`。

---

## 八、例（长安夜，草稿副本试验）

开局白玫随身 2 贯 300 文，家当 8 贯（`treasury.money`），每季用度 600 文，马“老黄”入了金吾卫，卫里给草料。开场那一夜请郎中给车把式包手花了 200 文；第一季去曲江赴约买了两角酒，60 文。季末：

```
$ court.py season --pay --apply      白玫：俸钱 +2贯400文（金吾卫·骑卒），进随身钱
$ purse.py season --apply
--- 白玫 ---   开销 −600文（用度 600文）   随身 3贯840文，家当 8贯
--- 白敬 ---   开销 −1贯800文（枣骝马料 1贯800文）   随身 15贯900文
```
