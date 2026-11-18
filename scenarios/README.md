# 剧本包

引擎（`rules/`、`scripts/`、`.claude/`）和剧本分开放。一个剧本就是 `scenarios/` 下的一个目录，里面是开局存档、开局人格卡和剧本的元数据。
换一个历史题材，只需要准备一个这样的目录；引擎不用改。

- 开新局：`/newgame`，先选剧本，再问主角和家人（`.claude/commands/newgame.md`）。
- 新做一个剧本：`/scenario`，说一个时代、地点和身份，GM 起草一份剧本包（`.claude/commands/scenario.md`）。
- 校验：`python3 scripts/scenario_check.py scenarios/<剧本名>`，输出“通过”或问题清单。

## 目录结构

```
scenarios/
  README.md                  本文件
  <剧本名>/
    scenario.json            剧本元数据（字段见下）
    intro.md                 剧本简介和开场背景，给玩家选剧本时看
    world/                   开局存档，开局时整个复制到项目根目录的 world/
    characters/              开局人格卡，开局时复制到项目根目录的 characters/
    rules/                   本剧本特有的规则补充（可选），开局后 GM 直接从这里读，不复制
    legacy_agents/           （可选）旧版专属 agent 的存档，不会被加载
```

目录名就是剧本的 `id`。现有剧本：

| 剧本 | 时代 | 主角 |
|---|---|---|
| `唐末朔方/` | 唐末天复二年（902）春起 | 朔方节度使，驻灵州 |
| `长安夜/` | 承平二十七年（956）春起，《朔方》三十年后 | 左金吾卫左街骑卒白玫（臣子），住平康坊 |

### world/ 里要有的文件

| 文件 | 必需 | 说明 |
|---|---|---|
| `kingdom.json` | 是 | `turn`（开局为 1）、`date`、`season`、`player`（name、title、seat）、`treasury`（money、grain、horses）、`generals`、`intel` |
| `map.json` | 是 | `regions`：每个地区 `terrain`、`fortification`、`owner`、`adjacent`（相邻关系要对称）、`income`（money、grain）、`note` |
| `armies.json` | 是 | `armies`：每支军 `faction`、`commander`、`location`（地区名）、`units`（兵种代码 → 人数）、`morale`、`status`；可选 `armor`、`drill`（护甲、操练，整军一个值或按兵种写，见 `rules/units.md`“护甲与操练”），例（长安夜）：长安军的具装人马俱甲、精锐 |
| `factions.json` | 是 | `factions`：己方一个 `controlled_by: player`；主要敌对君主 `controlled_by: ruler` 加 `card`；其余 `GM` |
| `economy.json` | 是 | 季节系数、`war_multiplier`、`fixed_income`、`fixed_expense`、`upkeep_per_1000`（每个用到的兵种都要有）、`governance` |
| `directives.json` | 是 | 分层托管；开局一般只填 `council.seat`（治所） |
| `household.json` | 家人启用时 | 默认的一家人；`/newgame` 会按玩家的回答重写 |
| `people.json`、`vignette_log.json`、`threads.md`、`gm_secrets.md`、`pending_orders.md` | 是 | 开局多半是空的。`people.json` 开局就有人的，每人带属性块（`persona.py gen` 生成）；顶上可写 `acquaintance`（别人对主角知道多少，`rules/people.md` 第二节） |
| `relations.json` | 否 | 关系网：人物之间开局就有的关系标签、恩怨（`rules/relations.md`）。没有的话第一次记账时自动建 |
| `court.json` | 庙堂剧本 | 派系、官职表、议题和各派立场、主角的仕途（`rules/court.md`，见下面“庙堂”一节） |
| `rumors.json` | 庙堂剧本 | 圈子、名望的种类、开局的流言和文献（`rules/rumors.md`） |
| `secrets.json` | 否 | 开局就有的秘密：真相、知情人、证据（`rules/secrets.md`） |
| `households/<名字>.json` | 否 | 主角家以外的家宅：宫中（`kind: palace`）、某个大族（`kind: clan`）（`rules/household.md` 第九节） |
| `purse.json` | 否 | 个人钱物：随身钱、家当、物件（带来历）、借据（`rules/purse.md`）。主角是臣子的，他的家当记在 `kingdom.json` 的 treasury，不记在这里 |
| `scenes.json`、`actions.json` | 否 | 开局后自动建：场景（`rules/scene.md`）、每季的行动件数。剧本包里一般不放 |

格式照 `唐末朔方/world/` 抄最省事。

### characters/ 里要有的卡

- 主角卡（`身份: 主角`，模板 `characters/_template_protagonist.md`）。
- 有兵权的己方部将、敌方大将，每人一张将领卡（模板 `_template.md`）。
- `factions.json` 里 `controlled_by` 为 `ruler` 的君主，每人一张君主卡，路径写进那个势力的 `card`。
- 家人启用时，`household.json` 里有 `card` 的家人各一张（模板 `_template_kin.md`）。
- 没有兵权、又要拿主意的朝中人物（文臣、宦官、宫人、皇子、后妃、外戚、宗室），各一张朝臣卡（模板 `_template_courtier.md`，由 `courtier` agent 扮演）。天子用君主卡。
  不在朝、又要拿主意的使节、外臣、僧道、布衣（商人、老兵、闺秀、乐伎、细作的明面身份）也用朝臣卡，身份照写这几个词（`rules/court.md` 第七节）。

每张卡的数值块都要有十一项属性（统、武、智、骑、射、体、胆、辩、学、政、魅）、特长、短处、性情、识人（主角卡没有这一项）、伤势，写法见 `rules/people.md` 第二节；`scenario_check.py` 会查。

卡里的路径一律写成 `characters/<拼音>.md`，相对剧本目录（开局后就是相对项目根目录）。
不要在剧本的 characters/ 里放 `README.md` 或 `_` 开头的文件，开局时会和引擎的同名文件冲突。

## scenario.json 字段

开局时 `scenario.json` 复制成 `world/scenario.json`。脚本从这里读己方势力名、治所、纪年和称谓；读不到的，不再默认唐末，直接报错。

| 字段 | 必需 | 说明 |
|---|---|---|
| `format_version` | 是 | 现在是 `1` |
| `id` | 是 | 剧本名，和目录名一样 |
| `name` | 是 | 给玩家看的名字（例（唐末朔方）：“朔方风云”） |
| `era` | 是 | 时代，一句 |
| `tagline` | 是 | 简介一句，选剧本时列在选项说明里 |
| `intro` | 否 | 简介文件，默认 `intro.md` |
| `start` | 是 | `turn`（1）、`year`（公元年，公元前写负数）、`season`（春/夏/秋/冬）、`date`（和 `kingdom.json` 的 date 一致） |
| `calendar` | 是 | 纪年。`style`：`年号` / `干支` / `公元`。`年号` 要有 `eras` 年号表（`[{"from": 公元年, "name": "年号"}]`，按 from 排，最早一条要早于或等于开局年份）；`干支` 可以带 `eras` 当前缀（例：某王 + 干支）；`公元` 直接写“公元前 N 年”“公元 N 年”。君主纪年（“某公十九年”）也用 `年号` 写 |
| `turn_unit` | 是 | `name`（“季”）、`per_year`（4）、`seasons`（现在只支持 `["春","夏","秋","冬"]`，脚本按这四个字结算） |
| `player` | 是 | `faction`（己方势力名，和 factions.json、map.json 的 owner 一致）、`protagonist`（默认主角名）、`title`（官职）、`seat`（治所）、`card`（主角卡）；`role`（可选）：`君主`（默认，一方之主）或 `臣子`（朝中的一个人，见“庙堂”一节） |
| `terms` | 是 | 称谓表，见下 |
| `dest_labels` | 否 | 出走去处的说法。人心账本的四种去处（投胡、投藩镇、自立、归朝廷）是引擎的分类，卡上照旧写这四个词；这里写本剧本里各指什么 |
| `units` | 是 | 本剧本可用的兵种：`[{"code": "infantry", "name": "步卒", "aliases": [...]}]`。`code` 必须是 `rules/units.md` 里的代码，`name`、`aliases` 是本剧本的叫法，只用在叙述里；存档里写代码 |
| `economy_features` | 否 | 特色收入，见下 |
| `extra_rules` | 否 | 剧本规则补充的文件列表（相对剧本目录），GM 开局后要读 |
| `people` | 否 | `identities`：本剧本追加或覆盖的身份（盐户、押衙之类），`persona.py` 生成人物时用，格式见 `rules/people.md` 第四节 |
| `newgame` | 是 | `/newgame` 的提问，见下 |
| `flavor` | 否 | 见闻素材表，整张替换引擎的默认值：`season_details`（季节 → 句子列表）、`spots`（地形 → 去处列表）、`new_faces`（新面孔身份）、`family_spots`、`family_details` |
| `scene` | 否 | 场景的设置：`curfew`（夜禁 `from`、`to` 写时辰，`name`、`note`）、`drums`（更鼓 → 时辰）、`weather`（季节 → 天气列表）。没有就没有夜禁（`rules/scene.md` 第三节） |
| `actions` | 否 | 主角是臣子时每季的件数：`cap_peace`（太平季，默认 3）、`cap_busy`（事多的季，默认 2） |
| `purse` | 否 | 个人钱物的单位：`unit`（小单位，存档里记这个）、`big_unit`、`per_big`（一大单位合多少小单位）、`horse_feed`（一匹马一季的马料） |
| `factions_note`、`legacy_agents` | 否 | 给 GM 看的备注 |

### 称谓表 `terms`

| 键 | 必需 | 意思 | 例（唐末朔方） | 缺项时脚本用 |
|---|---|---|---|---|
| `ruler` | 是 | 主角这一级君主的称号 | 节度使 | 主公 |
| `regional_commander` | 是 | 方面大将 | 都指挥使 | 方面大将 |
| `local_official` | 是 | 地方长官 | 刺史 | 地方长官 |
| `region_unit` | 是 | 行政单位 | 州 | 地区 |
| `army_unit` | 是 | 军队单位 | 军 | 军 |
| `sovereign` | 否 | 名义上的最高君主 | 天子 | 天子 |
| `lord_address` | 否 | 部将怎么称呼主角 | 大帅、韩公、使君 | 主公 |
| `hq` | 否 | 主角的衙署 | 帅府 | 帅府 |
| `court` | 否 | 中央 | 朝廷 | 朝廷 |
| `money_unit` / `grain_unit` / `horse_unit` | 否 | 钱、粮、马的单位 | 贯 / 石 / 匹 | 贯 / 石 / 匹 |

脚本的输出用 `region_unit`（经济明细、汇报里的“各州产出”“亲领 2 州”）和三个单位；其余称谓给 GM 和 agent 写叙述用。
规则文件里统一写“主公”“方面大将”“治所”“地区”，照这张表换成剧本里的叫法。

### 特色收入 `economy_features`

每一项：

```json
{"key": "制盐", "status": "可建", "cost": 1000, "rule": "rules/特色经济.md",
 "economy_item": {"list": "fixed_income", "name": "盐场", "money": 1500, "region": "盐州", "war_multiplier": 0}}
```

- `status`：`已计入`（已经算在某个地区的 income 里，写 `region`）、`已建`（开局就在 economy.json 里，`economy_item.name` 必须找得到）、`可建`（玩家下令兴办后，GM 把 `economy_item` 加进 economy.json）、`规则`（只是一条规矩，比如买马价）。
- `economy_item`：将来要加进 `world/economy.json` 的那一行；`list` 指明加到 `fixed_income` 还是 `fixed_expense`，加的时候去掉 `list`。字段照 `rules/economy.md`。

### `/newgame` 的提问 `newgame`

```json
"newgame": {
  "family": {"enabled": true, "default_members": "一句话说明默认的一家人"},
  "protagonist_default": {"name": "…", "age": 39, "card": "characters/….md"},
  "rounds": [
    {"title": "主角", "questions": [
      {"key": "origin", "header": "出身", "prompt": "主角是什么出身？", "multi": false, "options": [
        {"label": "将门之后", "note": "多一位父亲旧部", "default": true,
         "effect": {"new_person": "…", "card_change": "…"}}]}]}],
  "spouse_origins": ["妻子的娘家可以落在哪些势力、人家"],
  "kin_posts": "家人开局能挂什么职名",
  "address": "家人、部将怎么称呼主角"
}
```

- 每轮最多 4 题，每题 2–4 个选项（玩家另外总能选“其他”自己填），至多一个 `default`。`header` 写短（12 字以内）。
- `multi: true` 表示可多选；`ask_if` 写这题什么时候才问（“有妹妹”）。
- 出身选项的 `effect` 对应 `rules/newgame.md` 第三节的开局倾向；心事选项的 `thread_seed` 是支线种子的方向。
  `effect.attrs` 写这个出身让主角哪几项属性偏高、偏低（加减合计为 0，例（唐末朔方）：将门之后 `{"统": 1, "骑": 1, "武": 1, "学": -1, "辩": -1, "政": -1}`），`effect.tags` 写带来的特长；`persona.py hero` 照它调主角属性。不写的，按 `rules/people.md` 的出身倾向表找关键词。
- `family.enabled` 为 `false` 时，`/newgame` 跳过家人那一轮，不生成 `household.json`（家事、家书的步骤都跳过）。

## 庙堂：朝廷、宫中、主角是臣子

剧本以朝堂、宫闱为主时，开局存档里多几样东西。引擎的规则在 `rules/court.md`、`rules/rumors.md`、`rules/secrets.md`、`rules/relations.md`、`rules/household.md` 第九节；剧本只写数据，特有的规矩写在剧本自己的 `rules/` 里。

### 主角是臣子（`player.role: 臣子`）

- `player.faction` 写他所事的那一方（例：朝廷）；`factions.json` 里可以没有 `controlled_by: player` 的势力，那一方照常由 GM 或 `ruler` 扮演；`seat` 写他住的地方（京城），不必归“己方”。
- `kingdom.json` 的 `treasury` 记主角自家的钱粮（家财，几百贯上下）；不跑 `economy.py`，俸禄由 `court.py season --pay` 记。`armies.json`、`map.json`、`economy.json` 照常写（朝廷和各镇的兵马、地图），`scenario_check.py` 照常查。
- `court.json` 的 `careers` 里要有主角：官职、上司、器重（开局多半 0–1）。主角的官职也写进 `offices`。
- `newgame` 的提问照 `rules/newgame.md` 第四节写：出身、入仕的门路、朝中的旧识、心事；出身选项的 `effect` 可以写 `relations`（开局的人情，至多两笔）。

### `court.json`

- `sovereign`：天子（君主卡，`ruler` agent）。`fame_kind`：朝议看哪一种名望。
- `factions`：三四派为宜。每派首领、成员、声量（开局 3–7）、立场一句。一个人至多在一派；不在派里的重臣也要有。
- `offices`：官职表，品级 1–9、谁任、有没有议政之权。议政的位子决定各派的根基（`rules/court.md` 第二节），开局各派的声量和根基别差太远。
- `issues`：悬而未决的议题（立储、削藩、清查寺田、科举、对外的和战……照时代写），每个议题的选项、圣意（`lean`、`signal`）、各派的 `want`、`accept`、`bottom`（底线，写一句 `bottom_text`）、`weight`。
- 开局的党争（`feuds`）可以写几条旧积怨，事由写成开局前的旧事。
- 主角走的是一阶一阶往上的路（流外小吏、卫里的骑卒）的，写 `ladders`（仕途阶梯：每阶的职名、品级、每季俸钱、管什么），主角的 `careers` 写 `ladder`（`rules/court.md` 第六节）。

### `purse.json` 和场景

- 主角是小人物的剧本，个人的钱物比府库要紧：写 `purse.json`（主角和要紧的人：随身钱、物件、马；有来历的物件写 `story`，连着秘密的写 `secret`），`scenario.json` 写 `purse` 的单位和剧本的物价（`rules/` 里一份物价表）。
- 城里有夜禁、坊门、更鼓的，`scenario.json` 写 `scene.curfew`。开局那一夜这样的序幕，写在 `intro.md` 的“开场”和 `gm_secrets.md` 里，开局时走成一个 `--prologue` 场景。

### `rumors.json`

- `fame_kinds`：名望的种类，默认士林、军中、市井、诸蕃。
- `circles`：消息流传的圈子和往来（0–1），照时代写。例（第二部可能的写法）：宫中、朝堂、士林、长安市井、军中、诸蕃、江南、契丹。每个圈子写它的口碑算进哪种名望（`fame`，没有的写 `null`）。
- `members`：主角和要紧的人在哪些圈子（推不出来的才写）。
- 开局就在流传的流言、开局就有的文献（书、檄文），各写真假、来源、热度、可信、流布。
- 人格卡写一行 `名望`；名册里要紧的人写 `名望` 字段。

### `secrets.json`、`households/palace.json`

- 开局的秘密：真相、外面的说法、知情人（知道多少）、证据在谁手里、分量。天子的病、某段身世、一笔糊涂账。
- 宫中家宅：天子、后妃、皇子公主（年纪、嫡庶、宠爱、母家）、外戚（`clans`，在朝属哪一派）、天子的病程（`illness`，连上 `secrets.json` 里那一条）。皇子、后妃要拿主意的建朝臣卡，需求里可以有“储位”。

`scenario_check.py` 会查这几样：派系的成员和首领、官职的品级、议题的立场和选项、圈子的往来、流言的热度和可信、秘密的知情人、宫中家宅的家主和病程，人格卡的名望和心迹。

## 开局时怎么铺（`/newgame` 第二步）

1. 删掉 `world/` 下的所有文件，把 `scenarios/<剧本>/world/` 下的文件（连同 `households/` 子目录）复制进去；再把 `scenarios/<剧本>/scenario.json` 复制成 `world/scenario.json`。
2. `characters/` 里，除了 `_` 开头的模板和 `README.md`，其余卡片删掉；把 `scenarios/<剧本>/characters/` 下的卡片复制进去。
3. 清空 `chronicle/` 和 `archive/`（上一局先存进 `saves/`）。
4. `rules/`、`scripts/`、`.claude/` 不动。剧本的 `rules/` 不复制，GM 照 `world/scenario.json` 的 `id` 去 `scenarios/<id>/rules/` 读。
5. 跑 `python3 scripts/scenario_check.py world`，应当通过。

## 新做一个剧本

用 `/scenario` 最省事。手做的话：

1. 复制 `唐末朔方/` 成新目录，改目录名。
2. 改 `scenario.json`：id、名字、时代、纪年、主角、称谓、兵种、提问。
3. 改 `world/`：地图（十到二十个地区，相邻关系对称）、势力、军队、府库。数值规模参照唐末朔方的开局（见 `.claude/commands/scenario.md` 的“平衡”一节）。
4. 写人格卡：主角一张，部将、幕僚三到五位，敌对君主两三位，家人若干。每张卡带属性块（`rules/people.md`）。
5. 写 `intro.md`，有特色收入的写 `rules/` 和 `economy_features`。
6. 跑 `python3 scripts/scenario_check.py scenarios/<新剧本>`，改到通过为止。

剧本里的改动只动 `scenarios/<剧本>/`；要改引擎（规则、脚本、agent），按 `.claude/agents/rules-engineer.md` 的分工另做。
