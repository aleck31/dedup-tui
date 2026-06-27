# Architecture Decision Records

一决策一文件。每条记录决策及其理由，多数“理由”来自真实开发/测试中踩到的坑。

| # | 主题 | 状态 |
|---|---|---|
| [0001](0001-dedup-engine.md) | 查重引擎：rmlint 优先，内置后备 | Accepted |
| [0002](0002-keep-oldest-original.md) | “最原始”判定：创建时间优先，跨平台 | Accepted |
| [0003](0003-virtualized-datatable.md) | UI 用虚拟化 DataTable | Accepted |
| [0004](0004-quarantine-not-rm.md) | 删除走隔离区 + 删前校验 | Accepted |
| [0005](0005-fault-tolerance-and-recheck.md) | 单文件容错 + apply 后复查 | Accepted |
| [0006](0006-multi-keep.md) | 多保留模型（≥1） | Accepted |
| [0007](0007-focus-navigation.md) | 焦点切换交互模型 | Accepted |
| [0008](0008-dev-docs-in-git.md) | 开发文档放 .dev/ 并提交 | Accepted |

新增决策：复制最新编号 +1 的文件，沿用 状态/背景/决策/影响 结构。取代旧决策时在新 ADR 标注“取代 ADR-XXXX”，并把旧 ADR 状态改为 Superseded。
