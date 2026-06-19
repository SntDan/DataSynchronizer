# Data Synchronizer

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## 📁 Data Synchronizer

A lightweight, GUI-based file synchronization tool built with Python and PySide6. It compares multiple source/target directory pairs, shows a structured diff of all differences, and lets you copy or mirror changes with a single click.

### ✨ Features

- **Visual Diff Tree** — Browse new, modified, and extra files in a hierarchical tree view before committing any changes
- **Multiple Directory Pairs** — Configure and process multiple independent source/target groups in one run
- **One-way Sync** — Copy new and modified files from source to target without touching anything else
- **Mirror Mode** — Optionally delete files and folders in the target that no longer exist in the source
- **Resume Support** — Interrupted file copies are automatically resumed from where they left off
- **Snapshot Database** — Stores file metadata (size, mtime, xxHash) in a local SQLite database for fast incremental scans
- **Deep Hash Verification** — Optional xxHash-based content comparison to catch changes that bypass mtime/size checks
- **Bilingual UI** — Toggle between Simplified Chinese and English at any time
- **Stable Path Identity** — Treat slash direction and Windows path casing consistently when matching snapshots

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

1. **Configure groups** — Define directory pairs in `config.json`. Each group is loaded into one compact row when the application starts.
2. **Adjust this run** — Use **Edit**, **Add Grp**, or **Del Grp** to change which groups participate in the current run. UI changes never overwrite `config.json`.
3. **Scan** — Click **1. Scan** to compare all active groups. The tree view will show:
   - 🟢 `[NEW]` — files present in source but missing in target
   - 🟠 `[MODIFIED]` — files whose size or modification time has changed
   - ⚫ `[EXTRA]` / `[EXTRA_DIR]` — files/folders in target that don't exist in source
4. **Sync** — Click **2. Sync**. A confirmation dialog summarises what will happen before anything is written.

**Mirror Mode** (optional): Check *Remove extras* to also delete `[EXTRA]` and `[EXTRA_DIR]` items during sync. These items are highlighted in red as a reminder.

Folders containing differences always remain visible in the tree. When one folder contains many changed files, only the first 10 files are shown initially; click **... Show All** to reveal the rest.

### 🧩 Configuration

`config.json` is read-only while the application is running. If it does not exist, an empty default file is created automatically.

```json
{
  "directory_pairs": [
    {
      "source": "D:/Photos",
      "target": "//192.168.0.19/backup/Photos"
    },
    {
      "source": "D:/Documents",
      "target": "E:/Backup/Documents"
    }
  ],
  "copy_workers": 4
}
```

Each object in `directory_pairs` is an independent one-way synchronization group. `copy_workers` controls the maximum number of files copied concurrently across all groups.

### 🗂️ Project Structure

```
.
├── main.py           # Application entry point and main window (UI logic)
├── core_scanner.py   # Directory scanner and diff engine
├── copy_manager.py   # Multithreaded copy/delete engine with resume support
├── ui_model.py       # Qt item model powering the diff tree view
├── config.json       # Read-only directory-pair configuration
└── sync_snapshot.db  # Auto-generated SQLite snapshot database
```

### ⚙️ How It Works

1. **Scan phase** — `SyncScanner` processes directory groups sequentially and walks each source/target tree with `os.scandir`. Files are compared against the snapshot database by size and mtime. If deep-hash mode is enabled, xxHash is used for byte-level comparison.
2. **Diff phase** — Results are streamed to the UI in batches of 1 000 items. Folder nodes containing differences stay visible, while long file lists are collapsed for responsive rendering.
3. **Sync phase** — `CopyManager` uses a bounded worker pool across all groups. Large files are transferred in 4 MB blocks, and successful operations update SQLite snapshots in batches.
4. **Snapshot identity** — Source and target paths are canonicalized before database access, so `/`, `\`, and Windows path casing do not split one directory pair into multiple snapshot groups.

### 📄 License

[MIT](LICENSE)

---

<a name="中文"></a>
## 📁 数据同步工具（Data Synchronizer）

一款基于 Python 和 PySide6 开发的轻量级图形化文件同步工具。它可以同时处理多组源目录与目标目录，以结构化树状列表直观呈现所有变更，并支持一键复制或镜像同步。

### ✨ 功能特性

- **可视化差异树** — 在执行任何操作前，以层级树状结构浏览新增、修改、多余的文件
- **多组目录同步** — 一次配置并处理多组相互独立的源目录与目标目录
- **单向同步** — 仅将源目录中新增或修改的文件复制到目标目录，不影响其他内容
- **镜像模式** — 可选择删除目标目录中源目录已不存在的文件和文件夹
- **断点续传** — 中断的文件复制任务在下次同步时自动从中断处继续
- **快照数据库** — 将文件元数据（大小、修改时间、xxHash）存入本地 SQLite 数据库，加速增量扫描
- **深度哈希校验** — 可选基于 xxHash 的内容级对比，捕获绕过 mtime/size 检测的变更
- **双语界面** — 随时在简体中文与英文之间切换
- **稳定路径标识** — 统一处理斜杠方向和 Windows 路径大小写，避免快照分裂

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

1. **配置目录组** — 在 `config.json` 中定义目录组，程序启动时会按组生成紧凑的配置行。
2. **调整本次任务** — 使用「更改」「添加组」或「删除组」调整本次参与同步的目录组，界面操作不会写回 `config.json`。
3. **扫描** — 点击 **1. 扫描差异**，对所有启用的目录组进行比较。树状列表将展示：
   - 🟢 `[NEW]` — 源目录存在、目标目录缺失的文件
   - 🟠 `[MODIFIED]` — 大小或修改时间发生变化的文件
   - ⚫ `[EXTRA]` / `[EXTRA_DIR]` — 目标目录中源目录已不存在的文件/文件夹
4. **同步** — 点击 **2. 开始同步**，确认弹窗会汇总本次操作内容，确认后再执行写入。

**镜像模式**（可选）：勾选「删除多余文件」，同步时将一并删除 `[EXTRA]` 和 `[EXTRA_DIR]` 项目。这些条目会以红色高亮显示以作提示。

所有包含差异的文件夹都会保留显示。单个文件夹内的差异文件过多时，默认仅展示前 10 个文件，点击 **... Show All** 可查看其余内容。

### 🧩 配置文件

程序运行期间只读取 `config.json`，不会写回界面中的临时调整。配置文件不存在时，程序会自动创建一份空配置。

```json
{
  "directory_pairs": [
    {
      "source": "D:/照片",
      "target": "//192.168.0.19/backup/照片"
    },
    {
      "source": "D:/文档",
      "target": "E:/备份/文档"
    }
  ],
  "copy_workers": 4
}
```

`directory_pairs` 中的每个对象都是一组独立的单向同步任务。`copy_workers` 控制所有目录组共享的最大并发复制文件数。

### 🗂️ 项目结构

```
.
├── main.py           # 程序入口与主窗口（界面逻辑）
├── core_scanner.py   # 目录扫描与差异对比引擎
├── copy_manager.py   # 多线程复制/删除引擎，支持断点续传
├── ui_model.py       # 驱动差异树视图的 Qt 数据模型
├── config.json       # 只读的目录组配置文件
└── sync_snapshot.db  # 自动生成的 SQLite 快照数据库
```

### ⚙️ 工作原理

1. **扫描阶段** — `SyncScanner` 依次处理各目录组，并使用 `os.scandir` 遍历源目录和目标目录。文件大小和修改时间会与快照数据库进行比对；开启深度哈希模式后，将使用 xxHash 进行字节级内容校验。
2. **差异阶段** — 结果以每批 1000 项的方式流式推送至界面。包含差异的文件夹始终显示，过长的文件列表则默认折叠，以保持界面响应速度。
3. **同步阶段** — `CopyManager` 使用有界线程池处理所有目录组。大文件采用 4 MB 分块传输，成功完成的操作会分批写入 SQLite 快照。
4. **快照标识** — 数据库访问前会统一规范源目录和目标目录路径，使 `/`、`\` 和 Windows 路径大小写差异不会拆分成多个快照组。

### 📄 许可证

[MIT](LICENSE)
