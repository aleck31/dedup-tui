# ADR-0003 UI 用虚拟化 DataTable，不用 ListView + 多 widget

- **状态**: Accepted
- **日期**: 2026-06

## 背景

TUI 要展示数千个重复组、单组可达数百副本。

## 决策

组列表和组内副本列表都用 Textual 的 `DataTable`（虚拟化，只渲染可见行）。每组状态（keep/drop 标记、组内光标）存普通 Python 列表，**不存在 widget 里**。

## 影响

- 填充 7533 组仅 ~0.73s，上下移动流畅。

## 踩坑记录

初版用 `ListView` + 每组一个多行 `ListItem`，7533 组 = 7533 个 widget，真实终端**渲染卡死**（`_populate` 超时 >2 分钟）。headless 测试没暴露（不真渲染）。

**教训**：几千个 widget 会冻结 Textual，大列表必须虚拟化。
