# ADR-0001 查重引擎：优先 rmlint，无则内置纯 Python

- **状态**: Accepted
- **日期**: 2026-06

## 背景

需要在 macOS / Linux / Windows 上找出内容相同的重复文件。`rmlint` 在大目录上极快且支持 `-D` 目录级合并，但 **Windows 上基本不可用**。

## 决策

检测 PATH 上有 `rmlint` 就用它；否则回退到内置纯 Python 引擎（size 分组 → 4KiB 部分哈希 → 全量 SHA-256）。`--no-rmlint` 可强制走内置。

判重一律基于**内容哈希**，与文件名/修改时间无关。

## 影响

- 真跨平台：有 rmlint 的环境快，没有也能跑。
- 不同名但内容相同的文件会被判为同组（实测 `护照-肖学嵩.pdf` 与 `1.passport.pdf` 同组）。
- 内置引擎在超大目录上慢于 rmlint，属可接受代价。
