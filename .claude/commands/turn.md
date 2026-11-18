---
description: 结束本季，按 CLAUDE.md 的回合流程结算一回合
---

按照 CLAUDE.md 里的“回合流程”结算本回合。

**季和场景**：一回合是一季。季里要一步一步走的事（巡夜、赴约、追人、宴席、朝会、拿人）在季里当场开场景走（`scripts/scene.py`，`rules/scene.md`），不等季末；`/turn` 结算的是季末。
所以第 0 步：`python3 scripts/scene.py status`，还开着的场景先和玩家走完、`close --apply`（或 `cancel`），再往下结算。玩家这一季的命令里有要一步一步走的，先开场景走完，再回来结算季末。

1. 读取 `world/summary.md`、`world/pending_orders.md`，需要细节时再读 `world/*.json`（分层看 `world/directives.json`）和最近一期 `chronicle/`。
   当前剧本看 `world/scenario.json`：称谓照它的 `terms` 写，剧本特有的规则在 `scenarios/<id>/rules/`（例如特色收入怎么结算）。
2. **分层整理命令**（`rules/governance.md`）：把玩家本回合的命令归纳到每位将领、每个地区，再分开：
   - 亲领的地区和军：每条命令单独结算，和从前一样。
   - 委任方面：玩家的话拆成方针，`python3 scripts/governance.py delegate / directive / recall / rotate …` 先看再加 `--apply`。
   - 羁縻：GM 依态度定反应，改 `directives.json` 里的态度和动向。
   - 跑 `python3 scripts/governance.py council` 看本季亲裁限额。超出的先和玩家商量哪几件亲裁，其余交幕僚，逐件 `council --assign 幕僚 --task … --kind …`，看过再加 `--apply`。
   没有收到命令的将领按原状态行事，但他们也会根据性格自主行动。
   主角是臣子的（`world/scenario.json` 的 `player.role`）：没有帅府、委任和亲裁限额，这一步改成清点玩家本季要做的事（上奏、拜访、密谈、托人、写信、自己起意的场景，太平季 3 件、事多的季 2 件，`rules/court.md` 第九节）和交下来的差事。
   `python3 scripts/actions.py show` 看本季已经用了几件（场景收场时自动记了）；这一季还要做的，逐件 `actions.py add --what … --kind … --apply`，超了的先和玩家商量放到下一季（商量过照记加 `--force`）。朝中出了大事、他在办急差的，`actions.py mode 事多 --why … --apply`。
3. **人心提示**：对每位有兵权的将领跑 `python3 scripts/loyalty.py show characters/<名>.md`，记下“人心提示”（离心级别、出走的算盘、行动上限）；有军令的再跑 `python3 scripts/loyalty.py roll characters/<名>.md [--risky]`（命令凶险加 `--risky`），记下“日常提示”。这些只给 GM 和该将领 agent，不告诉玩家。
4. 在同一条消息里**并行**调用：
   - 每位相关将领：`general` agent。prompt 写明扮演谁、人格卡路径、主公原话、麾下兵马、所在和相邻地区的已知情况、斥候情报、人心提示、日常提示。委任方面的大将，本季没有新军令、方针没变的，不必调用。
   - 每个敌对势力之主：`ruler` agent（见 `world/factions.json` 的 `controlled_by` 和 `card`；没有人格卡的由 GM 扮演）。prompt 写明扮演谁、人格卡路径、他视角内的情报和收到的书信。
   - 朝中本季要说话、要上奏、要表态的人：`courtier` agent。prompt 写明扮演谁、人格卡路径、场景、主角或旁人的原话，加上 `python3 scripts/court.py hint <名>` 的朝中提示和 `python3 scripts/secrets.py brief <名> --with <在场的人>` 的情报包。
   - 情报包对所有 agent 都能用：调 `general`、`ruler`、`kin` 之前也可以跑 `secrets.py brief`，把“他知道什么”换成情报包里的内容（`rules/secrets.md` 第五节）。
   - 每个 agent 的 prompt 开头写一句时代和称谓（取 `world/scenario.json` 的 `era`、`player.title`、`terms`），agent 不读存档。
   - 每个 agent 只给它视角内的信息，不要把存档或别人的卡传给它。提到别人时，给这位角色眼里的印象（`python3 scripts/persona.py impress <某人> --by <这位角色>`），不给数字。
5. **理由校验**：对照 `rules/loyalty.md` 第七节核对每位将领的回复；朝臣照 `rules/court.md` 第七节（心迹的上限、党争的上限，异志要引用未解心结和牵扯或触发）。行动超出离心级别的上限，或者暗通、举事没有引用账本上未解的心结、没说清出走的算盘，或者脚本算出来不动念，就驳回，改按这一级能做的最高一档结算。ruler 回复里的“收买”，对照被收买将领的需求换算成开价，记到他的卡上（`offer`）。
6. 结算移动、战斗（用 `scripts/resolve_battle.py`，委任方面的仗也一样）。阵前有单挑的，先用 `scripts/contest.py run` 结算，把它给的 `morale_bonus` 加进这一仗的输入（`rules/contest.md` 第七节）；将领在仗里负了伤，用 `contest.py wound` 记下。然后：
   - 委任方面：`python3 scripts/governance.py season --season <季> [--war ...]`，先看明细，再加 `--apply`。偏差不是“照办”的，可召一次 `general` agent，把方针原话和本季偏差告诉他，让他回禀缘由。
   - 经济：`python3 scripts/economy.py --season <季> [--war ...]`，先看明细，再加 `--apply`（必须在上一步 `--apply` 之后）。主角是臣子的不跑，俸禄在第 8 步由 `court.py season --pay` 记。
   - **朝议**（`rules/court.md` 第四节）：本季的奏疏逐道结算。玩家的奏疏照原话 `python3 scripts/court.py memorial … --point N`（GM 照 `rules/contest.md` 第四节打论点分；越级加 `--bypass`），agent 的照它“上奏或密谋”里写的。然后 `court.py session 编号 [--debate 甲:乙 --point-a N --point-b N]`，看过加 `--apply`；把打印的“各方意见汇总”和 `secrets.py brief <天子>` 交给天子的 `ruler` agent，照它的“定夺”跑 `court.py decide 编号 --ruling … --apply`。被处分的人有人格卡的，照打印的建议记心结。
7. **家事**（`rules/household.md`）：
   - 玩家本季吩咐的家事用 `python3 scripts/household.py visit <id> --what … [--earnest] [--letter]` 记下，先看再加 `--apply`。每季有上限（太平季 2、战事季 1、出征在外 1 封家书），不占亲裁限额。做的事正对上那人的心愿才加 `--earnest`，写明依据。
   - 议亲、为质、立嗣：先调用 `kin` agent 问本人（prompt 写扮演谁、人格卡路径、场景、主角原话、`household.py hint <id>` 的亲疏提示，只给家里能知道的事），按回复里的“本人意思”跑 `match` / `hostage` / `heir`。这几件算亲裁的一件。玩家召见家人、或家人有话要说，同样调用 `kin`。
   - kin agent 要做“另有打算”一级的事，核对是否引用了未解心结、说清了牵扯或触发事件；不成立就驳回，改按这一级能做的最高一档结算。
   - 敌方 ruler 的“收买”指向家人的：收买、离间记成牵扯（`tie`）；绑架、行刺用 `plot … --seed N` 掷一次。
   - 回合数 +1 之前跑 `python3 scripts/household.py season --when <本季> [--war] [--care <id>] [--trigger <id>=事件]`，看过再加 `--apply`。到点的人生节点、有孕、临盆、病重，写成家事，下季交给玩家定（确认后用 `milestone`、`pregnant`、`birth`、`set` 记下）。
   - 别的家宅（`python3 scripts/household.py houses` 列出）：`household.py --house <名字> season [--care id] [--strain id]`，看过再加 `--apply`。宫中的病程走到要 GM 确认的一步，照剧情确认（`illness <id> --stage N --apply`），病情是秘密的，照提示调外象（`secrets.py expose`）。储位形势、宠爱只进 GM 备注；“可以经旁人透露的迹象”择一条，经玩家熟的人带出来（`rules/household.md` 第九节）。
8. **记账与季末推进**：本季发生的事按 `rules/loyalty.md` 第三节记进账本（`grudge`、`ease`、`need`、`offer`、`state`，先看再加 `--apply`）。然后每位有兵权的将领跑 `python3 scripts/loyalty.py season characters/<名>.md --when <本季> [--trigger …]`，看过再加 `--apply`（方面大将的部曲按委任自动上涨）。把新发生的重要事件追加到各卡片的“记忆”；每年一次（或大事之后）重写“近况”。
   - **养伤**：`python3 scripts/contest.py heal [--care <名>]`，看过再加 `--apply`（`rules/contest.md` 第六节）。危重的人每季掷一次凶险；伤重不治的，人格卡上的人照死亡处理，主角照 `rules/contest.md` 第八节由继承人接手。
   - **识人**：本季主角和谁长谈、共事过，用 `python3 scripts/persona.py know <名> --how 长谈|共事 --apply` 记进度（`rules/people.md` 第七节）；较量过的，`contest.py --apply` 已经记了。
   - **秘密、流言、关系网、朝廷**（有这几样存档的才跑），按顺序，各自先看再加 `--apply`：
     `python3 scripts/secrets.py season`（泄露检定；泄了的变成流言）→ `python3 scripts/rumors.py season`（扩散、消退、文献流布、名望）→
     `python3 scripts/relations.py season`（恩怨淡化）→ `python3 scripts/court.py season [--trigger <名>=事件] [--pay]`（党争、声量、朝臣的心迹、差事与考课、俸禄）→
     `python3 scripts/purse.py season`（有 `world/purse.json` 的：俸钱（`--pay` 已发过的不再发）、常例、马料、用度、利息、到期的债；“要 GM 留意”的几条写进汇报或下季的事）。
     考课“上考”的，阶梯上的下一阶照上司的意思 `court.py promote <名> --why … --apply`。
     本季发生的恩怨（引荐、救命、羞辱、要挟……）先用 `relations.py event` 记上；针对某个人的心结用 `loyalty.py grudge … --toward <名>`。
9. **见闻与家事**（`rules/vignettes.md`、`rules/household.md` 第七节）：`python3 scripts/vignette.py` 抽种子，依种子写一两段小景（战事季零到一段）。带情报的只写那个小人物能知道的，真假记进 GM 备注。定稿后同一 seed 加 `--apply`；新面孔用 `python3 scripts/persona.py gen <名> --role <身份> [--hint 特征] --apply` 记进名册（带属性；只说一句话的龙套可以不建）。跑 `vignette.py threads`，到期的支线本季收束；玩家搭理过的见闻开成支线，写进 `world/threads.md`。
   再跑 `python3 scripts/vignette.py --family` 抽家事种子，写一段“家事”（太平季一两段，战事季或出征时一封家书），家人优先。`household.py season` 打印的“可以经家里人透露的迹象”择一两条写进去，亲疏只写举动。定稿后同一 seed 加 `--apply`。
10. 更新存档，写 `chronicle/turn_NNN.md`（含“见闻”“家事”两节；有朝议的加“朝议”一节；本季走过场景的加“场景”一节，照 `scene.py log` 的场景记录改写）。GM 备注里记下圣意、各派的分、朝臣的心迹和私下盘算、流言的真假、秘密的泄露，以及：各将领的离心级别和变化、出走的算盘、驳回了什么、各 agent 的私下盘算、可观察的迹象、方面执行偏差、`report.py --gm` 的条目、见闻情报的真假。
11. **更新 `world/summary.md`**（含“家人”一节：谁在哪里、身体、待定的家事）。
12. 向玩家汇报（主角是臣子的，写成同僚、门生、仆人来说，邸报，上司的话；数字表里写随身钱、家当、本季俸钱和开销、欠债（`purse.py show <主角>`），以及本季用了几件事；玩家听到的流言照 `rumors.py heard <主角>`，不说真假）。写到人时用印象，不写属性数字；伤势写成看得见的样子（“左臂还吊着”）。数字用 `python3 scripts/report.py` 取：亲领精确，委任写约数和档位，羁縻写态度，例外逐条列。见闻、家事附在战报之后；待定的人生节点、有孕、病重，写成家里来人禀报的样子，请玩家定。不要泄露隐藏信息（账本、离心级别、亲疏级别、部曲、私下盘算、敌方部署）。将领的异样只用迹象来写：幕僚听到的话、斥候看到的事，从“可观察的迹象”和“玩家可能听说的心结”里择一两条。

$ARGUMENTS
