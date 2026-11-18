---
description: 开新局：存好上一局，先选剧本，铺开该剧本的开局存档，按剧本的提问问主角和家人，生成主角卡、家人卡和家宅存档后开场
---

按下面的步骤开一局新游戏。规矩见 `rules/newgame.md`（能改什么、不能改什么、开局倾向的上限）、`rules/household.md`（家宅存档、家人卡），
剧本包的格式见 `scenarios/README.md`。
和玩家说话照 CLAUDE.md 的“文风”：平实、友好，不催促。

## 一、存好上一局

1. 读 `world/kingdom.json` 的 `turn` 和 `date`。
2. 看 `saves/` 下有没有一份存档的 `world/kingdom.json` 和它的 `turn`、`date` 一样（`saves/当前进度/` 或带日期的文件夹）。
   - 有，而且 `world/summary.md` 也一样：告诉玩家“上一局已存在 saves/某某”，接着往下走。
   - 没有：先存档。新建 `saves/存档_<date>_第<turn>回合/`，把 `world/`、`characters/`、`chronicle/`、`archive/` 整个复制进去，告诉玩家存到了哪里。
   - `world/` 里本来就是开局模板（turn 为 1、没有 `chronicle/turn_*.md`）的，不用存。

## 二、选剧本

1. 列出 `scenarios/` 下的每个目录，读它的 `scenario.json`（`name`、`era`、`tagline`、`player.title`）和 `intro.md` 的头几行。
2. 用 AskUserQuestion 问一题（header：剧本）：每个剧本一个选项，label 写剧本名，说明写“时代——一句简介”；
   另加一个选项“我想玩别的题材”（说明：说一个时代、地点和身份，GM 起草一个新剧本）。剧本多于三个时，先列三个最近改过的，其余请玩家在“其他”里写名字。
3. 玩家选了“我想玩别的题材”：转去 `/scenario`（`.claude/commands/scenario.md`），新剧本做好、校验通过后，回到这里的第三步。
4. 选定以后，把那个剧本的 `intro.md` 全文给玩家看（这是公开的背景，不含隐藏信息），然后问一次：
   “上一局已存到 saves/……，现在开新局会覆盖 world/ 和 characters/。开始吗？”选项：开始 / 先不开。选“先不开”就停下。

下文的 `<剧本>` 指选定的剧本目录名，`SC` 指它的 `scenario.json`。

## 三、铺开开局存档

照 `scenarios/README.md` 的“开局时怎么铺”：

1. 删掉 `world/` 下的所有文件，把 `scenarios/<剧本>/world/` 下的文件（连同 `households/` 子目录）复制进去；再把 `scenarios/<剧本>/scenario.json` 复制成 `world/scenario.json`。
2. `characters/` 里，除了 `_` 开头的模板和 `README.md`，其余卡片删掉；再把 `scenarios/<剧本>/characters/` 下的卡片复制进去。
3. 清空 `chronicle/` 和 `archive/`（上一局已经存档）。
4. `rules/`、`scripts/`、`.claude/` 不动。剧本自己的规则补充（`SC.extra_rules`）留在 `scenarios/<剧本>/rules/`，GM 现在读一遍。
5. 跑 `python3 scripts/scenario_check.py world`，应当通过；不通过就停下，把问题清单告诉玩家，交给 `rules-engineer` 修剧本包。

## 四、问玩家

题目取自 `SC.newgame.rounds`：每一轮用一次 AskUserQuestion（每轮最多 4 题），按顺序问。每题玩家都可以选“其他”自己填。
题面用 `prompt`，header 用 `header`，选项用 `options` 的 `label`，选项说明用 `note`；带 `default` 的选项在说明末尾写“（默认）”。
`multi` 为真的题用 multiSelect。带 `ask_if` 的题，照前面的回答判断要不要问（“有妹妹”才问妹妹的性情），没有的人不问；一轮里的题都不用问，就跳过这一轮。

- `SC.newgame.family.enabled` 为 `false`：跳过问家人的那几轮，不生成家人卡和 `household.json`，第五步里与家人有关的几条都跳过。
- 问完，用一句话请玩家自由补充：“还有什么想补上的背景？一两句就行，也可以跳过。”（选项：跳过 / 我来补充（选“其他”填写）。）
- 玩家答得含糊、或者答的东西碰到了 `rules/newgame.md` 第一节“不能改”的（“我想多带三千骑兵”），用一句话说明开局的大数字不变，再问他要不要换成一位旧部、一段人情。

例（唐末朔方）：三轮。主角（姓名、年纪、出身、性格），家人（父母、妻子、子女、兄弟姐妹），性情与心事（弟弟、妹妹、妻子的性情，开局的心事）。

**主角不是一方之主时**（`SC.player.role` 为“臣子”，规矩见 `rules/newgame.md` 第四节）：剧本的提问一般问这几样，照剧本写的问，没写到的 GM 补问一轮（最多 4 题）：

- 出身：哪一家、什么门第（将门、寒门、世家、外邦归附之家……）；
- 入仕的门路：科举（哪一年、座主是谁）、荫补、征辟、从军；
- 和朝中谁有旧：座主、同年、父辈的故旧或旧怨（落在剧本已有的人身上，至多两笔，`rules/newgame.md` 第四节）；
- 心事：想做成什么事、想查清什么事、想离开什么人。

先用一句话说明：官职、品级、上司照剧本写的，选什么都不改；出身和门路换来的是朝中的人情。

## 五、生成

按 `rules/newgame.md` 第二、三节生成，数量照那里的上限：

1. **主角卡**：照 `characters/_template_protagonist.md`，写成 `characters/<拼音>.md`（默认 `SC.player.card`，换名字就换文件名）。删掉开局模板里的默认主角卡（如果文件名不同）。
   官职、治所照 `SC.player.title`、`SC.player.seat`，称呼照 `SC.newgame.address` 和 `SC.terms`。
   数值块里的属性先照开局默认卡抄（换了名字的也一样），再按出身、性格、年纪调整：
   `python3 scripts/persona.py hero characters/<主角>.md --origin <出身> --temper <性格> … --age <年纪>`，看过再加 `--apply`（`rules/newgame.md` 第三节）。“性情”一行照性格写一句。
2. **家人卡**：每位满六岁的家人照 `characters/_template_kin.md` 写一张 `characters/kin-<拼音>.md`。开局模板里用不上的默认家人卡删掉。
   需求用家里的说法（`rules/household.md` 第二节），满足度照开局处境定；性情写成具体的做事倾向；“家里知道的事”只写家里能知道的。
   数值块带十一项属性、特长、短处、性情、识人、伤势（`rules/people.md`），照性情填（`rules/newgame.md` 第二节）。
   妻子的娘家落在 `SC.newgame.spouse_origins` 里的势力或人家上。
3. **`world/household.json`**：照剧本开局版本的格式重写。`protagonist.born` 和主角卡一致；每人的 `born` 按年纪倒推
   （虚岁，开局年份是 `SC.start.year`，公元前写负数）；已过的人生节点记进 `milestones`；`last_seen_turn` 都写 1。
   纪年由 `world/scenario.json` 的 `calendar` 提供，`household.json` 里不用写 `calendar`。
   可以用 `python3 scripts/household.py add … --apply` 逐个加，再手改细节。
4. **开局倾向**：按出身加一位新人物（出身选项的 `effect.new_person`；用 `python3 scripts/persona.py gen 名 --role 身份 [--hint 特征] --apply` 生成属性、记进名册，
   识人照旧事定（父亲旧部、老兄弟 `persona.py know 名 --set 2 --apply`）；幕僚另写进 `world/directives.json` 的 `council.staff`，能力不超过 5）；对现有将领卡至多两处改动（`effect.card_change`；
   `python3 scripts/loyalty.py grudge / need … --apply`，记忆手写）。
5. **执念**：写进主角卡；照心事选项的 `thread_seed` 在 `world/threads.md` 开一两条支线；真相写进 `world/gm_secrets.md`（要泄露、要进情报包的，登记进 `world/secrets.json`）。
   主角是臣子的：开局的人情用 `python3 scripts/relations.py tag / add … --apply` 记（至多两笔）；`world/court.json` 的 `careers` 里改主角的名字（官职、上司照剧本）；`rumors.json` 的 `members` 写主角所在的圈子；主角卡写一行名望（多半是士林 2–3）。
   **个人钱物**（剧本有 `world/purse.json` 的）：照玩家答的武艺、长处改兵器和物件（`python3 scripts/purse.py item add / item status … --apply`；有来历的写 `--story`），钱数照剧本不改（`rules/newgame.md` 第一节“不能改”）。主角改了名字的，`purse.json` 里的名字一并改。
6. **改名**：主角换了名字的，照 `rules/newgame.md` 第一节改 `kingdom.json`、`factions.json` 和各卡里的称呼；`world/scenario.json` 的 `player.protagonist` 也改掉。
7. 自检：`python3 scripts/scenario_check.py world`（会查每张卡的属性块，以及关系网、朝廷、流言、秘密、宫中家宅几样存档）；主角是臣子的，再跑 `python3 scripts/court.py show --person <主角>` 和 `python3 scripts/secrets.py brief <主角>`，看他的官职、上司、知道的事对不对；`python3 scripts/household.py show`、`python3 scripts/household.py season`（只看，不加 `--apply`），
   确认年纪、节点都对得上；对每张家人卡跑一次 `python3 scripts/household.py hint <id>`，确认能读。

## 六、家世简述

给玩家看一份“家世简述”（`rules/newgame.md` 第五节）：主角一段；每位家人两三句；旧部人情、心事各一两句。白描，不写判词，不写隐藏的东西。
末尾问一句：“这样可以吗？哪里想改，直接说。”玩家要改就改，改完再给他看一次。

## 七、开场

玩家确认后，写 `world/summary.md`（开局模板里没有，新建；第一行写剧本名和 `id`；日期、府库、兵马、人事照开局；加“家人”一节；主角是臣子的，“府库、兵马”换成“家财、官职、上司、朝中各派、悬着的议题”；“GM 隐藏要点”写支线真相、圣意、宫中的病情），
然后照 CLAUDE.md“新会话接续游戏”的样子，用一段场景把玩家带到主角的案前，并带出一位家人（家人启用时）：母亲差人送来一碗汤、女儿在门口探头、弟弟闯进来请战。
剧本写了开场的序幕（`intro.md` 的“开场”、`gm_secrets.md` 里的开场那一场）的，开场就是这个序幕：用 `python3 scripts/scene.py open … --prologue` 开一个场景（不算件数），和玩家一步一步走完，`close --apply` 写回，再进第一季（`rules/scene.md`）。
场景之后，附上开局的简明数字（府库、兵马），和一句“请下令”。

$ARGUMENTS
