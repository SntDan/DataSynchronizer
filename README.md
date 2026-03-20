# Data Synchronizer

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## 📁 Data Synchronizer

A lightweight, GUI-based file synchronization tool built with Python and PySide6. It compares a source directory against a target directory, shows a structured diff of all differences, and lets you copy or mirror changes with a single click.

### ✨ Features

- **Visual Diff Tree** — Browse new, modified, and extra files in a hierarchical tree view before committing any changes
- **One-way Sync** — Copy new and modified files from source to target without touching anything else
- **Mirror Mode** — Optionally delete files and folders in the target that no longer exist in the source
- **Resume Support** — Interrupted file copies are automatically resumed from where they left off
- **Snapshot Database** — Stores file metadata (size, mtime, xxHash) in a local SQLite database for fast incremental scans
- **Deep Hash Verification** — Optional xxHash-based content comparison to catch changes that bypass mtime/size checks
- **Bilingual UI** — Toggle between Simplified Chinese and English at any time

### 🔧 Requirements

| Dependency | Version |
|---|---|
| Python | ≥ 3.10 |
| PySide6 | ≥ 6.5 |
| xxhash | ≥ 3.0 |

### 🚀 Usage

```bash
python main.py
```

1. **Set directories** — Select a source directory and a target directory using the Browse buttons.
2. **Scan** — Click **1. Scan Differences** to compare the two directories. The tree view will show:
   - 🟢 `[NEW]` — files present in source but missing in target
   - 🟠 `[MODIFIED]` — files whose size or modification time has changed
   - ⚫ `[EXTRA]` / `[EXTRA_DIR]` — files/folders in target that don't exist in source
3. **Sync** — Click **2. Start Synchronization**. A confirmation dialog summarises what will happen before anything is written.

**Mirror Mode** (optional): Check *Remove Extra Files in Target* to also delete `[EXTRA]` and `[EXTRA_DIR]` items during sync. These items are highlighted in red as a reminder.

### 🗂️ Project Structure

```
.
├── main.py           # Application entry point and main window (UI logic)
├── core_scanner.py   # Directory scanner and diff engine
├── copy_manager.py   # Multithreaded copy/delete engine with resume support
├── ui_model.py       # Qt item model powering the diff tree view
└── sync_snapshot.db  # Auto-generated SQLite snapshot (created on first scan)
```

### ⚙️ How It Works

1. **Scan phase** — `SyncScanner` walks the source and target trees concurrently. Each file is compared against the snapshot database by size and mtime. If deep-hash mode is enabled, xxHash is used for byte-level comparison.
2. **Diff phase** — Results are streamed to the UI in batches of 1 000 items so the interface stays responsive even for very large directories.
3. **Sync phase** — `CopyManager` processes the diff list with a thread pool. Large files are chunked (4 MB blocks) and support resume. After each successful copy the snapshot is updated atomically via SQLite `INSERT OR REPLACE`.

### 📄 License

[MIT](LICENSE)

---

<a name="中文"></a>
## 📁 数据同步工具（Data Synchronizer）

一款基于 Python 和 PySide6 开发的轻量级图形化文件同步工具。它可以对比源目录与目标目录的差异，以结构化树状列表直观呈现所有变更，并支持一键复制或镜像同步。

### ✨ 功能特性

- **可视化差异树** — 在执行任何操作前，以层级树状结构浏览新增、修改、多余的文件
- **单向同步** — 仅将源目录中新增或修改的文件复制到目标目录，不影响其他内容
- **镜像模式** — 可选择删除目标目录中源目录已不存在的文件和文件夹
- **断点续传** — 中断的文件复制任务在下次同步时自动从中断处继续
- **快照数据库** — 将文件元数据（大小、修改时间、xxHash）存入本地 SQLite 数据库，加速增量扫描
- **深度哈希校验** — 可选基于 xxHash 的内容级对比，捕获绕过 mtime/size 检测的变更
- **双语界面** — 随时在简体中文与英文之间切换

### 🔧 运行依赖

| 依赖项 | 版本要求 |
|---|---|
| Python | ≥ 3.10 |
| PySide6 | ≥ 6.5 |
| xxhash | ≥ 3.0 |

### 🚀 使用方法

```bash
python main.py
```

1. **设置目录** — 点击「浏览...」按钮分别选择源目录和目标目录。
2. **扫描** — 点击 **1. 扫描差异**，对两个目录进行对比。树状列表将展示：
   - 🟢 `[NEW]` — 源目录存在、目标目录缺失的文件
   - 🟠 `[MODIFIED]` — 大小或修改时间发生变化的文件
   - ⚫ `[EXTRA]` / `[EXTRA_DIR]` — 目标目录中源目录已不存在的文件/文件夹
3. **同步** — 点击 **2. 开始同步**，确认弹窗会汇总本次操作内容，确认后再执行写入。

**镜像模式**（可选）：勾选「删除目标目录多余文件」，同步时将一并删除 `[EXTRA]` 和 `[EXTRA_DIR]` 项目。这些条目会以红色高亮显示以作提示。

### 🗂️ 项目结构

```
.
├── main.py           # 程序入口与主窗口（界面逻辑）
├── core_scanner.py   # 目录扫描与差异对比引擎
├── copy_manager.py   # 多线程复制/删除引擎，支持断点续传
├── ui_model.py       # 驱动差异树视图的 Qt 数据模型
└── sync_snapshot.db  # 自动生成的 SQLite 快照文件（首次扫描后创建）
```

### ⚙️ 工作原理

1. **扫描阶段** — `SyncScanner` 并发遍历源目录与目标目录，将每个文件的大小和修改时间与快照数据库比对。开启深度哈希模式后，将使用 xxHash 进行字节级内容比对。
2. **差异阶段** — 结果以每批 1000 项的方式流式推送至界面，确保在处理超大目录时 UI 依然流畅响应。
3. **同步阶段** — `CopyManager` 通过线程池并行处理差异列表。大文件采用 4 MB 分块传输并支持续传；每次复制完成后通过 SQLite `INSERT OR REPLACE` 原子性更新快照。

### 📄 许可证

[MIT](LICENSE)
