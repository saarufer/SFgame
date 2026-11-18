# 旧版专属 agent（存档）

这里的三个文件是早期为唐末朔方写的专属 agent，原来放在 `.claude/agents/`：

- `general-xue-chong.md`：马军都指挥使薛崇
- `general-zhou-yansi.md`：步军都指挥使周延嗣
- `enemy-li-sijian.md`：定难军节度使李思谏

现在一律改用通用 agent 加人格卡：薛崇、周延嗣走 `general` + `characters/xue-chong.md`、`characters/zhou-yansi.md`，
李思谏走 `ruler` + `characters/li-sijian.md`（`world/factions.json` 里定难的 `controlled_by` 已改为 `ruler`，`card` 指向这张卡）。

这几个文件放在这里只作查考，不会被 Claude Code 加载。旧存档里写着 `agent:enemy-li-sijian` 的，GM 按 `ruler` + `characters/li-sijian.md` 处理。
要恢复原样，从 `saves/备份_剧本包前/.claude/agents/` 复制回去。
