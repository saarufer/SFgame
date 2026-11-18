# 场景

一回合是一季。季里大多数事一句话就结了：上一道奏疏、托一个人、写一封信。有些事要一步一步走：巡一夜的街、赴一场约、追一个人、吃一席酒、站一回朝会、拿一个人。
这些事开成一个**场景**，按一夜、一日、一个时辰往前走，谁在场、几更天、夜禁没有、花了多少钱、谁受了伤，都记着；场景收场时，把这些交给现有的脚本写回存档，再回到季里。

存档是 `world/scenes.json`，由 `scripts/scene.py` 读写。夜禁的时辰照剧本 `scenario.json` 的 `scene` 一节。

几条底线：

- **场景不推进回合。** 场景发生在当季里面，收场后季照常结算。一季可以有几个场景，也可以一个没有。
- **场景里的数字照样交给脚本。** 打架、比射、辩论走 `contest.py`；花钱走 `purse.py`；恩怨、得知秘密、流言、伤势各走各的脚本。`scene.py` 只是把它们收齐，收场时一并写回。
- **先演一遍再写。** 每记一件事，脚本先在一份存档副本（沙盘）上试跑那条命令，跑不通的不记；收场不加 `--apply` 时，整套写回在新的副本上演一遍给 GM 看，没错再 `close --apply`。
- **场景也算件数。** 主角是臣子的，自己起意的场景算本季的一件（大场景两件）；当值、奉差的是本分，不算（第五节）。

本文的例子取自《长安夜》剧本，标作“例（长安夜）”。

---

## 一、季和场景怎么交替

```
季初  玩家下令（上奏、拜访、托人、写信……；要一步一步走的事说“开个场景”）
  │
  ├─ 场景：scene.py open → 记事（走动、见面、花钱、较量、得知……）→ tick 推时辰 → close --apply
  ├─ 场景……（一季里几个都行；同一时间只开一个）
  │
季末  照 CLAUDE.md 的回合流程结算（朝议、家事、秘密、流言、关系网、朝廷、钱物、见闻），回合数 +1
```

- 一个场景开着的时候，不跑季末的脚本。季末之前，开着的场景要 `close` 或 `cancel`（`scenario_check.py` 会提醒）。
- 场景里定下来的事，季末照常进各脚本的季末结算：场景里欠下的人情会淡化，场景里漏出去的话会扩散，场景里受的伤季末养。
- 开局那一场（剧本的序幕，例（长安夜）：开场那一夜）用 `--prologue`，不算件数。
- 玩家说“这一夜我去平康坊找苏婵”“明天去城西军屯看赵满仓”，GM 判断要不要开场景：只要一个结果的（“托人带个话”），照季里的办法一句话结；要看过程、可能临时变卦、要花钱打点、可能动手的，开场景。

---

## 二、开场：`scene.py open`

```
scene.py open --title 题目 --kind 巡夜|宿卫|朝会|赴约|追人|宴席|拿人|私访|其他 --where 地区 --time 时辰
              [--date 二月廿八] [--spot 去处] [--people 名,名] [--pass 名,名] [--mounted 名,名]
              [--weather 天气|随机] [--curfew auto|on|off] [--size 小|大] [--count 0|1|2] [--duty] [--prologue] [--span 一夜|一日|一个时辰]
```

- **地点**是地图上的地区（`map.json`），`--spot` 写地区里的小去处（酒楼的楼上、坊门口）。远地（`far: true`）也能开，只是城里的夜禁不管那边。
- **在场的人**：主角自动在场；`--people` 写别人。人格卡、名册里没有的新面孔，先用 `person 名 --role 身份` 记进来（第四节）。
- **`--pass`**：夜禁中能在街上走的人（当值的、有文牒的）。**`--mounted`**：骑马的人。
- **天气**：GM 给，或者 `随机`（按季节从表里抽，剧本可以在 `scenario.json` 的 `scene.weather` 里换）。
- **夜禁**：`auto` 照剧本的时辰算；`on`、`off` 是 GM 定（上元节弛禁、宫变那一夜全城戒严）。
- **预定走多久**：`--span` 一夜（到五更开门鼓）、一日（到酉正）、一个时辰。到了点脚本提醒一句，要接着走也行。
- **件数**：照第五节，按种类和大小给默认，`--count` 可改。

---

## 三、时辰与夜禁

- 一天分十二个时辰，每个时辰分“初”“正”两步，一步合半个时辰（一个钟头）。脚本按这 24 步走：子初是夜里十一点，子正半夜，丑初一点……亥正十点。
- 夜里另报更：戌是一更，亥二更，子三更，丑四更，寅五更。
- 时辰可以写成：戌初、戌正、戌（等于戌初）、一更（戌初）、三更（子初）、黄昏（酉正）、拂晓（卯初）、半夜（子初）。
- **推时辰**：`tick --steps N` 或 `tick --to 时辰`；每条记事也可以带 `--tick N`（这件事花了几步）。过了子初算第二日。脚本会在夜禁开始、解除、更鼓响的那一步提醒。
- **走动**：`move 名,名 --to 地区`。相邻的地区一格走一步（半个时辰）；骑马两格一步；同去的人里有步行的，按步行算。城里走不经过远地；远地要走好些日子，场景里不走。
- **夜禁中出坊上大街**：没有 `--pass` 的人，脚本提醒“犯夜”。撞没撞上巡街的、被谁拿住，GM 照当夜的情形定（剧本的规矩写在 `scenarios/<id>/rules/`，例（长安夜）：犯夜笞二十，有文牒放行）。坊里面走动不算犯夜。
- 剧本没写夜禁的（`scenario.json` 里没有 `scene.curfew`），就没有夜禁，脚本只报时辰。

---

## 四、记事与写回

场景里的每一件事记一行；有数字的，记成一条待写回的命令，收场时交给对应的脚本。

| 发生了什么 | 命令 | 收场时写回到 |
|---|---|---|
| 谁来了、谁走了 | `join 名 [--pass]`、`leave 名` | 只进场景记录；名册里的人收场时记一笔出场（`vignette.py person seen`） |
| 新面孔 | `person 名 --role 身份 [--hint …]` | 名册（`persona.py gen`，带属性） |
| 谁见了谁 | `meet 甲 乙 --how 见面|长谈|共事|交手` | 识人（`persona.py know`）；见面只记一笔 |
| 谁知道了什么 | `learn 名,名 --secret S --depth 全知|大略|风闻 --how 亲见…` | 秘密的知情人（`secrets.py learn`） |
| 证据易手、毁了、呈上去 | `evidence S --add … / --move E --to 名 / --status E=毁` | `secrets.py evidence` |
| 结了恩怨 | `deed --event 救命|援手|羞辱|… --by --to`，或 `deed --holder --toward --kind --what --strength` | 关系网（`relations.py event / add`） |
| 结了交情、拜了师 | `tag 甲 乙 --tag 私交` | `relations.py tag` |
| 花钱、给钱、得钱、得了东西 | `spend`、`give`、`earn`、`item` | 个人钱物（`purse.py`，`rules/purse.md`） |
| 受了伤 | `wound 名 --level 轻伤 --where 左臂` | 人格卡或名册的伤势（`contest.py wound`） |
| 有了一句话 | `rumor --text … --truth … --circle …` | 流言（`rumors.py spread`） |
| 打了一架、比了一场 | 先 `try contest.py run … --seed N` 在沙盘上看结果，再 `op contest.py run … --seed N` 记下 | `contest.py run --apply`（伤势、识人、名册里的死活） |
| 别的 | `op 脚本名 参数…`（不写 `--world`、`--apply`） | 那个脚本 |
| 只是情节 | `note 一句话` | 只进场景记录，写史书用 |

- **试跑**：每条有写回的记事，脚本先在沙盘（一份存档副本，放在系统临时目录）上加 `--apply` 跑一遍。跑不通的（钱不够、名字写错、秘密编号不对）不记，报错给 GM。沙盘里的状态一条一条累积，所以前面花了钱，后面就少了。
- 场景开着时 GM 又直接改了真存档（比如单独跑了一场 `contest.py --apply`），沙盘就旧了：`resync` 重建。
- **记事本身**直接存进 `scenes.json`（场景的草稿本），不用 `--apply`；写回关系网、秘密、钱物这些别的存档，要等 `close --apply`。
- **`try`**：在沙盘上跑一条命令看看，不记、不写回。较量用它先看结果；定下来照同一个 seed `op` 记，收场时结果一样。

### 收场：`close`

1. 把记下的写回命令，加上自动的几条（名册里在场过的人记一笔出场），在**新的**存档副本上从头演一遍。有跑不通的，列出来；加了 `--apply` 也不写，改好再收。
2. 加 `--apply`：在真存档上依次跑这些命令；在 `actions.json` 里记本季的件数（第五节）；场景记进 `scenes.json` 的 `history`（时间、地点、在场的人、每一件事、写回了什么）。
3. 打印“场景记录”，GM 照它写进本季的史书。

`cancel --why …`：这个场景作罢，记下的事都不写回（玩家改主意了、GM 开错了）。

---

## 五、件数：场景算几件

主角是臣子的（`player.role` 为“臣子”），每季亲自做的事有个数：太平季 3 件，事多的季 2 件（`rules/court.md` 第九节；剧本可以在 `scenario.json` 的 `actions` 里改）。由 `scripts/actions.py` 记账，场景收场时自动记进去。

| 场景 | 件数 |
|---|---|
| 当值、奉差：巡夜、宿卫、朝会上列班、奉命拿人 | 0（本分） |
| 自己起意：赴约、追人、宴席、私访、自己去拿人 | 1 |
| 大场景：跨了一夜一日以上，或者牵动三方以上的人，或者朝会上主角出班上奏 | 2（`--size 大`，或 `--count 2`） |
| 当值的场景里另做了自己的事（借巡夜去见一个人、打听一件事） | 另记 1 件（`act --what …`） |
| 剧本的序幕 | 0（`--prologue`） |

- 开场时脚本看本季的账，这一场记上就超了的，提醒 GM 先和玩家商量；收场时照记（GM 和玩家商量过才开的），超了再提醒一句。
- 场景之外的事（上奏、拜访、托人、写信）用 `actions.py add --what … --kind …` 记；超了不写，商量过再加 `--force`。事多的季用 `actions.py mode 事多 --why …`。
- 家事不占件数（`rules/household.md` 第三节）；场景里和家人说了半夜的话，可以 `op household.py visit …` 记成一件家事。
- 主角是一方之主的，场景算不算帅府亲裁的一件，GM 照 `governance.py council` 定；`actions.py` 只记账。

---

## 六、GM 怎么用

1. 玩家要做的事要一步一步走，开场景；写一段开场的白描（时辰、天气、谁在、街上什么样）。
2. 玩家每说一句、每做一个动作，GM 照情形写场面，在场的 agent（`courtier`、`general`、`kin`）照常调，prompt 里写眼下的时辰、地点、谁在场；他们说了什么、做了什么，GM 用上面的命令记下。
3. 要掷骰的（较量）先 `try`，照结果写场面，再 `op` 记下同一个 seed。
4. 时间往前走就 `tick`、`move`；夜禁、更鼓的提醒写进场面里。
5. 收场：`close` 看一遍，`close --apply` 写回；把“场景记录”改写进史书的本季纪事。
6. 季末之前，确认没有开着的场景（`scene.py status`）。

### 命令一览

```
python3 scripts/scene.py open --title … --kind … --where 地区 --time 时辰 [--date …] [--people …] [--pass …] [--mounted …] [--weather …|随机] [--curfew auto|on|off] [--size 小|大] [--count N] [--duty] [--prologue] [--span …]
python3 scripts/scene.py status | log [场景编号]
python3 scripts/scene.py tick [--steps N | --to 时辰] [--note …]
python3 scripts/scene.py move 名,名 --to 地区 [--mounted] [--no-tick] [--tick N]
python3 scripts/scene.py join 名 [--where 地区] [--pass] [--mounted] | leave 名 [--why …]
python3 scripts/scene.py person 名 --role 身份 [--hint 特征 …] [--age N] [--sex 男|女] [--trait …] [--where 地区]
python3 scripts/scene.py meet 甲 乙 [--how 见面|长谈|共事|交手]
python3 scripts/scene.py learn 名,名 --secret S --depth 全知|大略|风闻 [--how …] [--from 名] [--what …]
python3 scripts/scene.py evidence S [--add 种类:描述@持有人] [--move E --to 名] [--status E=毁|失|呈上]
python3 scripts/scene.py deed --event 事件 --by 甲 --to 乙 [--what …] [--strength N] [--known …]
python3 scripts/scene.py deed --holder 甲 --toward 乙 --kind 恩|怨 --what … --strength N [--known …]
python3 scripts/scene.py tag 甲 乙 --tag 标签 [--hidden] [--knowers …] [--roles …]
python3 scripts/scene.py spend 名 --amount 钱 --what … [--to 名] [--kind …] [--from cash|home]
python3 scripts/scene.py give 甲 --to 乙 (--amount 钱 | --item 物件) --what … [--kind …]
python3 scripts/scene.py earn 名 --amount 钱 --what … [--from 名]
python3 scripts/scene.py item 名 --kind 兵器|马|衣甲|物件|文书 --name 名称 [--desc …] [--story 来历] [--value 钱] [--secret S]
python3 scripts/scene.py wound 名 --level 轻伤|重伤|危 [--where 部位] [--seasons N]
python3 scripts/scene.py rumor --text … --truth 真|假|半真 --circle 圈子 [--source …] [--about …] [--heat N] [--cred N] [--effect …]
python3 scripts/scene.py try 脚本 参数…     |  op 脚本 参数… [--say 记录里怎么写]  |  note 一句话  |  act --what … [--weight 2]
python3 scripts/scene.py close [--apply] | cancel --why … | resync
python3 scripts/actions.py show | add --what … --kind 上奏|拜访|密谈|托人|写信|场景|较量|其他 [--weight 2] [--duty] [--force] --apply
python3 scripts/actions.py mode 太平|事多 --why … --apply | drop 序号 --apply
```

每条记事都可以带 `--tick N`。所有命令都有 `--world 目录`，拿存档副本试。

---

## 七、例（长安夜）：开场那一夜（草稿副本试验）

```
$ scene.py open --title 开远门外的盐纲 --kind 其他 --prologue --where 开远门 --time 酉正 --date 二月廿八 \
      --people 白敬,老郭 --mounted 白玫,白敬 --weather 晴，有风 --span 一夜
  承平二十七年春 二月廿八，酉正，开远门；夜禁：不在；闭门鼓正在敲；算本季 0 件
$ scene.py spend 白敬 --amount 300文 --what 塞给开远门门吏牛守义，放车进城 --kind 打点
$ scene.py tick --to 戌初            · 夜禁开始了（戌初（一更））：城门、坊门关了
$ scene.py move 白玫,白敬,老郭 --to 城西诸坊   · 夜禁中出坊走大街：没有公事、没有文牒，撞上巡街的就算犯夜
  ……（经皇城南到平康坊，亥正二更）
$ scene.py person 张狗儿 --role 壮汉 --hint 蒙着脸
$ scene.py try contest.py run --kind 打架 --a 白玫 --b 张狗儿 --occasion 街市 --seed 7    → 第三回合被人拉开
$ scene.py op contest.py run --kind 打架 --a 白玫 --b 张狗儿 --occasion 街市 --seed 7 --say 白玫和蒙面的打手扭在一处
$ scene.py join 李琰 --pass
$ scene.py deed --event 援手 --by 白玫 --to 李琰 --what 白玫拦住了要跑的打手
$ scene.py meet 白玫 李琰 --how 共事        → 收场时 李琰：初见 → 略知
$ scene.py learn 李琰 --secret S7 --depth 风闻 --how 亲见 --what 翻倒的车边，有官印的盐包和没官印的混在一起
$ scene.py wound 老郭 --level 轻伤 --where 右手
$ scene.py spend 白玫 --amount 200文 --what 请郎中给老郭包手 --kind 药钱
$ scene.py close --apply                  → 写回 15 条；序幕不算件数
```
