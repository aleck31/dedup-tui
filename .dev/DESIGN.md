# 架构 / 规格设计

## 模块职责

```
src/dedup_tui/
├── core.py        引擎与文件操作，无 UI。扫描、判重、隔离、校验、apply。
├── app.py         Textual TUI。展示组/副本，收集 keep/drop 决策。
└── __main__.py    CLI 入口。参数解析、串联 scan→决策→apply→复查。
```

- **core 不依赖 app**：可单独用（`--auto` 模式完全不进 TUI）。
- **app 不直接删文件**：它只产出 `decisions`，由 `__main__` 调 `core.apply_decisions` 执行。

## 数据流

```
目录或 rmlint.json
   │  core.scan() / groups_from_rmlint_json()
   ▼
list[Group]   (Group = {kind: file|dir, members: [路径...], size})
   │  排序：按 waste 降序
   ▼
决策阶段：
  --auto  → 每组保留 members[0]（最原始）
  TUI     → 用户逐组 keep/drop（app.py），返回 decisions
   │
   ▼
decisions = [(keeper, victims, kind, new_path|None), ...]
   │  core.apply_decisions(verify=True)
   ▼
移除 victims → 隔离区（删前 re-hash 校验，失败容错）
   │  返回 (removed, skipped, failed)
   ▼
复查：重新 scan，报告残留重复组数
```

## 关键数据结构

- `Group`（core.py，dataclass）：`kind`、`members`（按 originality_key 排序，index 0 = 最原始）、`size`、`waste` 属性。
- `app` 状态：
  - `keep_flags[g][m]: bool` — 第 g 组第 m 个副本是否保留（多保留模型）。
  - `cursor[g]: int` — 第 g 组当前高亮的副本索引（←/→ 移动）。
  - `visible_idx` — 过滤后可见的组索引。
- `core.LAST_STATS`（ScanStats）：rmlint footer 解析出的统计，含 `aborted` 标志（检测扫描被中断 → 结果不完整）。

## 排除规则

默认排除这些目录名下的文件不参与移除（防止破坏依赖/虚拟环境）：
`node_modules .cache .venv venv .git __pycache__ .tox .gradle .npm site-packages .dist-info vendor .Trash $RECYCLE.BIN`
`--exclude NAME` 可追加。

## 安全不变量（必须始终成立）

1. 每组**至少保留 1 个**副本，apply 时若 keepers 为空则跳过整组（绝不清空一组）。
2. 删除前**重新哈希校验**内容一致（`--no-verify` 显式关闭）。
3. 移除是**移动到隔离区**，非 `rm`，可恢复。
4. 单文件失败**不中断**整体；失败不留双份脏状态。
5. apply 后**自动复查**（`--no-recheck` 显式关闭）。

## CLI 选项

| 选项 | 作用 |
|---|---|
| `--apply` | 真正执行（否则 dry-run） |
| `--auto` | 非交互，每组保留最原始 |
| `--exclude NAME` | 追加排除目录名（可重复） |
| `--no-rmlint` | 强制内置引擎 |
| `--no-verify` | 跳过删除前 re-hash |
| `--no-recheck` | 跳过 apply 后复查 |

## 已知边界 / 待改进

- 单组副本数实测最多 294（SAP Examtopics），DataTable 虚拟化足以应对。
- macOS `uchg`/`schg` 锁定文件：`uchg`（用户级）会尝试清除标志后重试；`schg`（系统级，SIP）无法处理，记为 failed。
- 无断点续跑：中断后重跑是重新全量扫描（扫描很快，5s 量级，可接受）。
- 未实现的 `--top N` / `--min-size`（只处理最大的 N 组 / 忽略小组）等“减少决策量”的功能 —— 见 PRD 非目标，刻意不做。
