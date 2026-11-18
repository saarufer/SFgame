# 经济（每回合末由 GM 结算）

这里写通用机制。各剧本特有的收入（盐池、互市、商路之类）写在 `scenarios/<剧本>/rules/` 里，
怎么接进结算见文末“特色收入怎么接入”。下文的例子标了“例（唐末朔方）”的，取自唐末朔方剧本。

## 收入

- 每个己方地区每季产出 `world/map.json` 里的 `income`（钱、粮）。己方是 `world/scenario.json` 的 `player.faction`。
- **秋季**粮食产出 ×3，**冬季**粮食产出 ×0.5（季节系数在 `economy.json` 的 `season_multiplier`，剧本可以改）。
- 地区本身的特产（例（唐末朔方）：盐州的盐池）可以直接算进它的 `income`。
- 战乱地区（本季发生过战斗）产出减半。

## 支出

- 军粮和军饷按 `rules/units.md` 计算，按全部兵马合计。
- 粮或钱不够：差额部分算作欠饷/断粮，相关军队士气 -15；拖欠一季以上，统兵将领可记一条心结（强度 1–2，见 `rules/loyalty.md`）。

## 其他

- 招募：只能在己方治所或人口较多的地区招募，当季下令，下季到营。
- 进贡朝廷 / 贿赂邻国：由玩家自行决定数额，GM 判断效果。
- 买马：剧本里有卖马的势力时，价钱写在剧本的规则补充里；一次性开销走 `--extra-cost`。

## 常用的内政项目

下面几项不挑剧本，GM 可以直接用。数字是唐末朔方那一局定下来的，别的剧本可以照搬，也可以在剧本规则里改。

- **屯田（军屯）**：抽调驻军屯垦。每 1000 名步卒屯田，从下一季起每季多产粮 2000 石（秋季照样 ×3）。
  屯田的兵马战力 ×0.8（一半时间在种地），但不额外增加饷钱。只能在己方的城池或平原地区屯田。
  条目写成 `fixed_income`，`"seasonal": true`。
- **粜粮**：每 1000 石卖 250 贯，秋收后 200 贯。一次性进项，走 `--extra-income` 和 `--extra-grain-cost`。
- **劝课农桑**：在一个己方地区投入 1000 贯（修渠、贷种、减赋），从下一季起该地每季粮食产出 +1500 石（秋季照样 ×3）。每地最多投两次。
  条目写成 `fixed_income`，`"seasonal": true`，`region` 写那个地区。
- **加税**：各直辖地区钱收入 ×1.25（写进 `region_modifiers`）。每季每地有 15% 的几率出现民怨（GM 掷骰）。民怨的地区下一季收入减半；连续加税，几率逐季递增 5%。
- **民兵轮番**：平时一半归农，粮饷减半（每千人粮 300、钱 50）。烽火报警时全数上城；若没有预警就遭袭，守城民兵按半数计。

## 结算脚本

经济不手算，每回合用脚本结算：

```
python3 scripts/economy.py --season 冬 [--war 甲州,乙州] [--extra-cost 3000] [--apply]
```

- 参数都在 `world/economy.json`：季节系数、加税等按地区修正、固定收入、固定支出、各兵种粮饷单价。新增或撤销一项收入，改这个文件即可。
- 各地区基础钱粮取 `world/map.json` 的 `income`，只计 `owner` 是己方的地区；粮饷只计 `faction` 以己方势力名开头的军队
  （例如“某某（归附）”也算；藩属自养的不计）。己方势力名读 `world/scenario.json` 的 `player.faction`；
  旧存档没有 scenario.json 的，读 `economy.json` 的 `own_faction`；都没有，脚本报错。
- `--war`：本季打过仗的地区，该地产出减半；依托该地的固定收入也减半（条目可用 `war_multiplier` 另定，0 表示全失）。
- 买马、招募、赏赐、赈济等一次性开销，用 `--extra-cost`（钱）、`--extra-grain-cost`（粮）传入；一次性进项用 `--extra-income`、`--extra-grain`。
- 不加 `--apply` 只打印明细；加了才写回 `kingdom.json` 的 `treasury`，并记下 `last_economy_settlement`，同一回合不能重复写入（必要时加 `--force`）。
- 钱粮不够时，府库记 0，脚本打印欠饷/断粮的数额，士气和心结的后果仍由 GM 按上文判定。
- 输出里的地区单位（州、郡、国……）和钱粮单位取 `scenario.json` 的 `terms`。

## 特色收入怎么接入

每个剧本可以有几样自己的进项（例（唐末朔方）：盐场、互市、榷场、西路贸易）。做法：

1. 在 `scenarios/<剧本>/rules/` 里写一份规则补充：投入多少、每季收多少、什么情况下减半或全失、对势力关系有什么影响。
2. 在 `scenario.json` 的 `economy_features` 里登记每一项：`key`、`status`（`已计入` / `已建` / `可建` / `规则`）、`rule`（规则文件），
   能落成固定收支的写 `economy_item`（就是将来要加进 `economy.json` 的那一行，带 `list: fixed_income` 或 `fixed_expense`）。
3. 开局就有的，直接写进剧本的 `world/economy.json`，`status` 写 `已建`；还没兴办的写 `可建`，玩家下令、投入结算之后，
   GM 把 `economy_item` 去掉 `list` 字段，加进 `world/economy.json` 对应的列表。
4. 条目字段：`name`、`money`、`grain`、`region`（依托的地区：不归己方时不计，战乱时乘 `war_multiplier`）、`seasonal`（粮食是否乘季节系数）。
5. `scripts/scenario_check.py` 会核对：`已建` 的条目在 `economy.json` 里找得到，`可建` 的条目依托的地区在地图上。

## 分层托管与政令衰减（规则见 `rules/governance.md`）

- 有 `world/directives.json` 时，委任、羁縻的地区不进 `economy.py` 的“各地产出”，它们的军队不进“粮饷”。
  委任方面的收入先按方针里的上供比例交府库，余下进方面库，粮饷、补员从方面库出（`governance.py season` 结算）。
  `economy.py` 收入里多一行“委任方面上供”，支出里多一行“委任方面请拨、代垫”，马匹按方面支取的数扣。
  每季先跑 `governance.py season --apply`，再跑 `economy.py --apply`；顺序反了，`economy.py` 拒绝写入。
- 羁縻的地区、军队自养，不进府库。他们的贡献照旧写成 `fixed_income`。
- **政令衰减**：`economy.json` 里有 `governance` 参数时，亲领地区的钱粮乘政令系数：
  离治所超过两程，每多一程 −5%；亲领地区超过八个，每多一个各地再 −1%；最低六折。固定收入不打折。
  没有这一块的旧存档，结算结果和从前一样。
- `economy.py --world 目录` 可以拿存档副本试算。
