# Data Synchronizer

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## Data Synchronizer

A small PySide6 desktop tool for one-way file synchronization. It compares source and target paths, shows the differences, then copies new or modified files after confirmation.

## Features

- Compare multiple source/target directory pairs in one run
- Select a folder or an individual file on both sides
- Show new, modified, and extra target files in a tree view
- Copy new and modified files from source to target
- Optional mirror mode to remove extra target files and folders
- Resume interrupted copies
- Use a local SQLite snapshot database for faster later scans
- Treat `/`, `\`, and Windows path casing as the same snapshot identity
- Switch between English and Simplified Chinese
- Persist gitignore-style rules in `.syncignore`; show ignored items in a distinct gray
- Right-click tree items to open them, reveal their location, or ignore them
- Confirm before closing the window while scanning or synchronizing

## Requirements

| Dependency | Version |
|---|---|
| Python | >= 3.10 |
| PySide6 | 6.12.0 |
| xxhash | >= 3.0 |
| pathspec | >= 0.12, < 2 |

## Usage

```bash
python -m pip install -r requirements.txt
python main.py
```

1. Edit `config.json` to define directory pairs.
2. Start the app. Each pair is shown as one row.
3. Use **Edit**, **Add Grp**, or **Del Grp** for temporary changes in the current run.
4. Click **1. Scan** to compare active pairs.
5. Click **2. Sync** to copy confirmed changes.

UI changes do not write back to `config.json`.

## Configuration

`config.json` is read when the app starts. If it is missing, the app creates an empty default file.

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
    },
    {
      "source": "D:/Settings/app.ini",
      "target": "E:/Backup/app-backup.ini",
      "target_type": "file"
    }
  ],
  "copy_workers": 4,
  "default_language": "zh_CN"
}
```

- `directory_pairs`: independent one-way sync groups
- `target_type`: optional `file` or `directory`; useful when a configured target file does not exist yet
- `copy_workers`: maximum concurrent copy workers
- `default_language`: `en_US` or `zh_CN`

## Notes

`.syncignore` lives beside `main.py` (or the packaged executable) and is created with default system-file exclusions if missing. Rules apply to paths relative to **each** source/target pair, on both sides. It supports gitignore syntax: comments (`#`), wildcards (`*.tmp`, `**/logs/`), root anchoring (`/report.txt`), directories (`cache/`), and exceptions (`!keep.tmp`). Windows matching is case insensitive. To include a file inside an ignored directory, first unignore the directory itself. For a single-file pair, rules match the original source filename, even if the target is renamed.

Right-click a scan result and select **Ignore in Scans** to save its literal relative path to `.syncignore` and update the list immediately. The rule applies to that relative path in all pairs. Ignored files and directories remain visible in a distinct gray with `[IGNORED]` / `[IGNORED_DIR]` labels; ignored directories are not traversed. They are never copied or deleted, including in mirror mode. An extra directory containing ignored items is labeled `[PRESERVED_DIR]`; its unignored extras can still be deleted. Extra target directories are traversed during scanning to identify protected descendants. Edit `.syncignore` and scan again to remove or change exclusions. Rules are also reloaded before synchronizing.

Closing the window during a scan or synchronization asks whether to stop the task and close. **No** is the default and leaves the task running; **Yes** cancels the task and waits for its workers to finish before exiting.

The default ignore file is restored at startup if it has been deleted. Directory junctions and symbolic links are preserved without traversing them. A source read error stops the scan and prevents synchronizing partial results. Interrupted copies only resume after verifying that the target matches the source prefix; copy and snapshot errors are reported instead of showing success.

Folders that contain differences are always shown. If one folder has many changed files, only the first 10 files are shown at first; click **... Show All** to expand them.

Mirror mode deletes `[EXTRA]` and `[EXTRA_DIR]` items from the target. Keep it off if the target contains files you want to preserve.

An individual source file can target either a folder or a specific file. When targeting a folder, the original filename is used; when targeting a file, that exact path and filename are used. Mirror mode never removes unrelated files from the target folder. A source folder cannot target one individual file.

## Project Structure

```
.
├── main.py           # UI and application entry point
├── core_scanner.py   # Directory scanner and diff engine
├── copy_manager.py   # Copy/delete engine with resume support
├── ui_model.py       # Qt model for the diff tree
├── ignore_rules.py   # Gitignore-style matching and persistent rules
├── .syncignore       # Editable scan/sync exclusions
├── config.json       # User configuration
└── sync_snapshot.db  # Generated snapshot database
```

## Build

Use the same Python environment to install dependencies and build the executable.
PySide6 6.12.0 with the Windows frame workaround was verified by moving the window between 100% and 175% scale monitors.

```bash
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean DataSynchronizer.spec
```

## License

[MIT](LICENSE)

---

<a name="中文"></a>
## Data Synchronizer

一个基于 PySide6 的轻量文件同步工具。它会比较源路径和目标路径，先显示差异，确认后再复制新增或修改的文件。

## 功能

- 一次处理多组源目录和目标目录
- 源路径和目标路径均可选择文件夹或单个文件
- 用树状列表显示新增、修改和目标端多余文件
- 单向同步：源目录复制到目标目录
- 可选镜像模式：删除目标端多余文件和文件夹
- 支持中断后续传
- 使用本地 SQLite 快照数据库加快后续扫描
- 正反斜杠和 Windows 路径大小写会按同一组快照识别
- 支持英文和简体中文界面
- 使用 `.syncignore` 持久保存类似 gitignore 的规则，忽略项用独立的灰色显示
- 树状列表右键可打开文件、定位文件和添加忽略规则
- 扫描或同步过程中关闭窗口需要确认

## 运行要求

| 依赖 | 版本 |
|---|---|
| Python | >= 3.10 |
| PySide6 | 6.12.0 |
| xxhash | >= 3.0 |
| pathspec | >= 0.12, < 2 |

## 使用方法

```bash
python -m pip install -r requirements.txt
python main.py
```

1. 修改 `config.json`，写入目录组。
2. 启动程序，每组目录会显示为一行。
3. 使用「更改」「添加组」「删除组」临时调整本次任务。
4. 点击「1. 扫描差异」查看结果。
5. 点击「2. 开始同步」确认后执行复制。

界面里的临时调整不会写回 `config.json`。

## 配置文件

程序启动时读取 `config.json`。如果文件不存在，会自动创建空配置。

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
    },
    {
      "source": "D:/设置/app.ini",
      "target": "E:/备份/app-backup.ini",
      "target_type": "file"
    }
  ],
  "copy_workers": 4,
  "default_language": "zh_CN"
}
```

- `directory_pairs`：独立的单向同步组
- `target_type`：可选值为 `file` 或 `directory`；目标文件尚不存在时可用它明确类型
- `copy_workers`：最大并发复制线程数
- `default_language`：`en_US` 或 `zh_CN`

## 说明

`.syncignore` 位于 `main.py`（打包后为可执行文件）的同级目录；文件不存在时，会自动创建并写入默认系统文件忽略规则。规则相对于**每组**源路径和目标路径的根目录，对两端均生效。支持 gitignore 风格的注释（`#`）、通配符（`*.tmp`、`**/logs/`）、根路径匹配（`/report.txt`）、目录规则（`cache/`）和例外（`!keep.tmp`）。Windows 下匹配不区分大小写。若要保留被忽略目录内某个文件参与同步，需先取消对该目录本身的忽略。单文件组按源文件的原始文件名匹配，目标重命名不影响规则。

在扫描结果中右键选择「在扫描中忽略」，会把该项目的准确相对路径保存到 `.syncignore`，并立即更新列表。同一相对路径的规则对所有路径组生效。忽略的文件和目录保留显示，用独立灰色和 `[IGNORED]` / `[IGNORED_DIR]` 标记；忽略目录不继续扫描内部内容。忽略项不会被复制或删除，镜像模式也会保留。包含忽略项的目标多余目录显示为 `[PRESERVED_DIR]`，其中未被忽略的多余项仍可删除。扫描会遍历目标多余目录，以识别其中需要保留的内容。手动修改 `.syncignore` 后重新扫描即可取消或调整忽略；同步前也会重新读取规则。

扫描或同步时关闭窗口，会询问是否停止任务并关闭。默认选择「否」，任务继续执行；选择「是」后取消任务，等待工作线程退出再关闭程序。

忽略文件被删除后，下次启动会恢复默认文件。目录联接和符号链接会保留且不继续遍历。读取源目录出错时，中止扫描并禁止同步残缺结果。断点续传前会核对已有内容与源文件是否一致；复制和快照写入失败会明确提示，不会显示同步成功。

所有包含差异的文件夹都会显示。单个文件夹内文件过多时，默认只显示前 10 个文件，点击 **... Show All** 可展开其余内容。

镜像模式会删除目标目录中的 `[EXTRA]` 和 `[EXTRA_DIR]` 项。如果目标目录里有需要保留的文件，请不要开启镜像模式。

单个源文件既可同步到目标目录，也可同步到指定的目标文件。目标为目录时保留原文件名；目标为文件时使用指定的完整路径和文件名。镜像模式不会删除目标目录里的无关文件。源目录不能同步到单个目标文件。

## 项目结构

```
.
├── main.py           # 界面和程序入口
├── core_scanner.py   # 目录扫描和差异比较
├── copy_manager.py   # 复制和删除逻辑，支持续传
├── ui_model.py       # 差异树的 Qt 数据模型
├── ignore_rules.py   # Gitignore 风格匹配和忽略规则保存
├── .syncignore       # 可编辑的扫描和同步忽略规则
├── config.json       # 用户配置
└── sync_snapshot.db  # 自动生成的快照数据库
```

## 打包

请在同一个 Python 环境中安装依赖并打包。
PySide6 6.12.0 配合 Windows 窗口 frame 修复，已通过 100% 与 175% 缩放屏幕之间的手动拖动验证。

```bash
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean DataSynchronizer.spec
```

## 许可

[MIT](LICENSE)
