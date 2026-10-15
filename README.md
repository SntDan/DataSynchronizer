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
- Toggle between xxHash64 content verification and fast metadata scanning
- Keep synchronization history in a local SQLite snapshot database
- Update read-only targets safely; preserve read-only mirror extras as `[READ_ONLY]`
- Treat `/`, `\`, and Windows path casing consistently in scans, ignore rules, tree items and snapshots
- Switch between English and Simplified Chinese
- Persist global and pair-specific gitignore rules in `.syncignore`; hide global exclusions and show pair exclusions in gray
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

Temporary path changes do not write back to `config.json` automatically. Click **Save Groups** at the lower right to save all current path pairs, including file/directory target types. Language, content verification and mirror options are in **Settings**, beside **Add Grp**, and take effect when you click **Apply**. **Cancel** closes Settings and discards changes made since the last Apply. A compact transfer speed display to the left of the progress bar refreshes every half second while synchronizing and is hidden when idle.

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
  "default_language": "zh_CN",
  "verify_contents": false,
  "mirror_mode": false
}
```

- `directory_pairs`: independent one-way sync groups
- `target_type`: optional `file` or `directory`; useful when a configured target file does not exist yet
- `copy_workers`: maximum concurrent copy workers
- `default_language`: `en_US` or `zh_CN`
- `verify_contents`: enable xxHash64 content verification; defaults to `false`
- `mirror_mode`: remove extra target files and folders; defaults to `false`

## Notes

With **Verify contents (xxHash)** enabled in **Settings**, scanning compares the current source and target: a missing target is new, a different size is modified, and equal-sized files are read completely on both sides and compared with xxHash64. Timestamps and historical snapshots do not decide whether contents match. Identical contents with different timestamps are skipped; equal sizes and timestamps cannot hide different contents. Full verification reads both sides on every scan, so large collections and network drives can take longer. xxHash64 is a fast non-cryptographic hash with a very small, nonzero collision risk. Read errors or changes detected while hashing stop the scan and prevent synchronizing partial results.

Content verification is off by default, using the original fast scan based on sizes, timestamps and saved snapshots without reading file contents. This mode can miss equal-sized content changes. The Settings dialog also contains **Remove extras**; both options are saved to `config.json` and restored at startup. Settings cannot be changed while scanning or synchronizing. Long status messages are truncated on the right with an ellipsis instead of widening the window; hover over the status to read the full text.

Read-only target files with content changes appear as `[MODIFIED]` and can be updated. The original target stays read-only during copying; its read-only flag is cleared only immediately before replacing it with the complete staged file. The replacement follows the existing source-attribute rules. If replacement fails or is cancelled, the original target's read-only flag is restored. Actual access-denied errors are still reported, and read-only sources remain readable and copyable. Read-only mirror extras appear as `[READ_ONLY]` and are preserved without deletion.

`.syncignore` lives beside `main.py` (or the packaged executable) and is created with default system-file exclusions if missing. Rules apply to paths relative to **each** source/target pair, on both sides. It supports gitignore syntax: comments (`#`), wildcards (`*.tmp`, `**/logs/`), root anchoring (`/report.txt`), directories (`cache/`), and exceptions (`!keep.tmp`). Windows matching is case insensitive. To include a file inside an ignored directory, first unignore the directory itself. For a single-file pair, rules match the original source filename, even if the target is renamed.

Rules before any scope header, or under `# @global`, apply to all pairs. Global exclusions are skipped without appearing in scan results, ignored totals or checked-file counts. The default system-file rules are global. A `# @pair {...}` header binds the following rules to the specified source, target and target type. Changing either path selects another scope; returning to the original pair restores its rules. Pair rules cannot override global exclusions.

```gitignore
# @global
.DS_Store
Thumbs.db

# @pair {"source": "D:/Photos", "target": "E:/Backup/Photos", "target_is_file": false}
/temporary/
/private.txt
```

Right-click a scan result and select **Ignore in This Pair** or **Ignore Globally (Hide)** to save its literal relative path in the appropriate scope and update the list immediately. Pair exclusions remain visible in gray with `[IGNORED]` / `[IGNORED_DIR]` labels; global exclusions disappear. Ignored directories are not traversed. Both scopes protect files from copying and deletion, including mirror mode. An extra directory containing protected items is labeled `[PRESERVED_DIR]`; its unignored extras can still be deleted. Edit `.syncignore` and scan again to remove or change exclusions. Existing files without scope headers are read as global rules. Rules are reloaded before scanning and synchronizing.

Scan-result classification and synchronization preparation run in the background. The synchronization confirmation appears after the reloaded ignore rules have been checked.

Path groups are locked while a task runs. Editing paths or changing content verification invalidates the old results and requires another scan. Sources and targets must not contain one another; different groups must not share overlapping destinations or write into another group's source. Scanning does not create missing target folders.

Closing the window during a scan, synchronization preparation or synchronization asks whether to stop the task and close. **No** is the default and leaves the task running; **Yes** cancels the task and waits for its workers to finish before exiting.

The default ignore file is restored at startup if it has been deleted. Directory junctions and symbolic links are preserved without traversing them. A source read error stops the scan and prevents synchronizing partial results. Interrupted copies only resume after verifying that the target matches the source prefix; copy and snapshot errors are reported instead of showing success.

Files are staged in the target folder and replaced only after a complete copy and change checks. Cancellation or read errors preserve the existing target. Staging needs temporary space for the complete file. Windows uses native `CopyFileEx` with cancellation for files of at least 1 MiB and files with named data streams. Small files with only a main stream, unsupported operations and other platforms use buffered copying. Copying no longer computes an unused historical hash. The xxHash content-scan option still compares both current files in full. Configuration and ignore-file updates also use atomic replacement.

Files of at least 64 MiB can retain incomplete copies in a reserved `.ds-sync/` directory beside the destination file. A later run checks the source and target identities, verifies the existing prefix against the source, and writes only the remaining data. A changed source/target restarts the copy; damaged or preallocated tails are never trusted. Internal state is hidden from scans and protected from mirror deletion independently of `.syncignore`. Removing it manually discards resume progress without changing the actual destination file. Files with Windows named data streams, or storage that cannot enumerate them, use a full native copy to preserve those streams.

Folders that contain differences are always shown. If one folder has many changed files, only the first 10 files are shown at first; click **... Show All** to expand them.

Mirror mode deletes `[EXTRA]` and `[EXTRA_DIR]` items from the target. Keep it off if the target contains files you want to preserve.

An individual source file can target either a folder or a specific file. When targeting a folder, the original filename is used; when targeting a file, that exact path and filename are used. Mirror mode never removes unrelated files from the target folder. A source folder cannot target one individual file.

## Project Structure

```
.
├── main.py           # UI and application entry point
├── core_scanner.py   # Directory scanner and diff engine
├── copy_manager.py   # Copy/delete engine with resume support
├── file_transfer.py  # Native Windows copying and resumable-file ownership
├── ui_model.py       # Qt model for the diff tree
├── ignore_rules.py   # Gitignore-style matching and persistent rules
├── storage.py        # Atomic configuration and ignore-file writes
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
- 可切换 xxHash64 内容校验与按文件属性快速扫描
- 使用本地 SQLite 快照数据库记录同步历史
- 安全更新只读目标文件；镜像模式中保留只读多余文件并标记为 `[READ_ONLY]`
- 扫描、忽略、树列表和快照统一处理正反斜杠及 Windows 路径大小写，避免误判多余文件
- 支持英文和简体中文界面
- 使用 `.syncignore` 保存全局和路径组忽略规则，全局忽略项隐藏，路径组忽略项显示为灰色
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

路径组的临时调整不会自动写回 `config.json`。点击右下角的「保存组」，即可保存当前所有路径组（包括目标为文件或目录的类型）。语言、内容校验和删除多余文件选项集中在「添加组」左侧的「设置」中，点击「应用」保存并生效；「取消」关闭窗口并放弃尚未应用的修改。进度条左侧显示简洁的实时传输速度，同步时每半秒刷新，空闲时隐藏。

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
  "default_language": "zh_CN",
  "verify_contents": false,
  "mirror_mode": false
}
```

- `directory_pairs`：独立的单向同步组
- `target_type`：可选值为 `file` 或 `directory`；目标文件尚不存在时可用它明确类型
- `copy_workers`：最大并发复制线程数
- `default_language`：`en_US` 或 `zh_CN`
- `verify_contents`：启用 xxHash64 内容校验，默认 `false`
- `mirror_mode`：删除目标端多余文件和文件夹，默认 `false`

## 说明

在设置中开启「内容校验（xxHash）」后，扫描比较当前源文件和目标文件，目标不存在时标记为新增，大小不同时标记为修改；大小相同时完整读取两端文件，用 xxHash64 比较内容。时间戳和历史快照不决定内容是否一致。内容相同但时间不同的文件会跳过；大小和时间均相同也不会掩盖内容差异。每次扫描都会读取两端进行完整校验，大量文件和网络盘可能需要更长时间。xxHash64 是快速的非加密哈希，碰撞风险很低但不为零。读取失败或校验过程中检测到文件变化时，会中止扫描并禁止同步残缺结果。

内容校验默认关闭，采用原来按大小、时间和已有快照进行的快速扫描，不读取文件内容，可能漏掉同大小的内容变化。设置弹窗还包含「删除多余文件」，两个选项会保存到 `config.json`，下次启动时恢复。扫描和同步期间不可更改设置。底部状态过长时在右侧显示省略号，不会撑宽窗口；悬停可查看完整文字。

需要更新内容的只读目标文件显示为 `[MODIFIED]`，可以正常同步。复制期间原目标保持只读，仅在完整临时文件即将替换目标时解除只读；替换后的文件沿用既有的源文件属性规则。替换失败或取消时，会恢复原目标的只读属性。真正的访问权限不足仍会报错，源文件只读不影响读取和复制。镜像模式中的只读多余文件仍标记为 `[READ_ONLY]`，保留而不删除。

`.syncignore` 位于 `main.py`（打包后为可执行文件）的同级目录；文件不存在时，会自动创建并写入默认系统文件忽略规则。规则相对于**每组**源路径和目标路径的根目录，对两端均生效。支持 gitignore 风格的注释（`#`）、通配符（`*.tmp`、`**/logs/`）、根路径匹配（`/report.txt`）、目录规则（`cache/`）和例外（`!keep.tmp`）。Windows 下匹配不区分大小写。若要保留被忽略目录内某个文件参与同步，需先取消对该目录本身的忽略。单文件组按源文件的原始文件名匹配，目标重命名不影响规则。

文件开头未指定作用域的规则，以及 `# @global` 下面的规则，对所有路径组生效。全局忽略项直接跳过，不出现在扫描列表中，也不计入忽略数量或已检查文件数；默认的系统文件规则属于全局规则。`# @pair {...}` 下的规则绑定指定的源路径、目标路径和目标类型。源或目标改变时切换到另一作用域，切回原路径组时仍可使用原规则。路径组规则不能覆盖全局忽略。

```gitignore
# @global
.DS_Store
Thumbs.db

# @pair {"source": "D:/照片", "target": "E:/备份/照片", "target_is_file": false}
/临时文件/
/private.txt
```

扫描结果右键可选择「仅在当前路径组忽略」或「全局忽略（不显示）」，把准确的相对路径保存到对应作用域，并立即更新列表。路径组忽略项保留灰色和 `[IGNORED]` / `[IGNORED_DIR]` 标记，全局忽略项从列表移除。忽略目录不继续遍历。两类忽略项均不会被复制或删除，镜像模式也会保留。包含保护项的目标多余目录显示为 `[PRESERVED_DIR]`，其中未被忽略的多余项仍可删除。手动修改 `.syncignore` 后重新扫描即可取消或调整忽略。旧文件没有作用域标记时按全局规则读取；扫描和同步前都会重新加载规则。

扫描结果整理和同步准备在后台执行，重新检查忽略规则完成后才显示同步确认框。

任务运行期间锁定路径组。修改路径或切换内容校验后，旧结果失效，需要重新扫描。源和目标不能互相包含；不同组的目标不能重叠，也不能覆盖其他组的源路径。扫描不会创建尚不存在的目标文件夹。

扫描、同步准备或同步时关闭窗口，会询问是否停止任务并关闭。默认选择「否」，任务继续执行；选择「是」后取消任务，等待工作线程退出再关闭程序。

忽略文件被删除后，下次启动会恢复默认文件。目录联接和符号链接会保留且不继续遍历。读取源目录出错时，中止扫描并禁止同步残缺结果。断点续传前会核对已有内容与源文件是否一致；复制和快照写入失败会明确提示，不会显示同步成功。

文件先在目标文件夹中完整生成，通过变化检查后再替换原文件。取消或读取失败会保留原目标，因此需要容纳完整文件的临时空间。Windows 对至少 1 MiB 的文件，以及带附加数据流的文件，使用支持取消的原生 `CopyFileEx`；仅有主数据流的小文件、原生操作不受支持时，以及其他平台上，采用缓冲复制。复制时不再计算未被使用的历史哈希；内容校验选项仍完整读取两端文件进行 xxHash 比较。配置和忽略文件也采用原子替换保存。

至少 64 MiB 的文件可以将未完成内容保存在目标文件旁的专用 `.ds-sync/` 目录中。下次同步会检查源和目标的身份，并逐块验证已有前缀，仅继续写入剩余部分。源或目标发生变化时重新复制；损坏内容和预分配的尾部不会被直接当作已完成数据。内部状态独立于 `.syncignore`，始终从扫描中隐藏并防止被镜像删除。手动删除该目录只会清除续传进度，不会改变实际目标文件。带 Windows 附加数据流的文件，或无法枚举数据流的存储，使用完整原生复制来保留这些内容。

所有包含差异的文件夹都会显示。单个文件夹内文件过多时，默认只显示前 10 个文件，点击 **... Show All** 可展开其余内容。

镜像模式会删除目标目录中的 `[EXTRA]` 和 `[EXTRA_DIR]` 项。如果目标目录里有需要保留的文件，请不要开启镜像模式。

单个源文件既可同步到目标目录，也可同步到指定的目标文件。目标为目录时保留原文件名；目标为文件时使用指定的完整路径和文件名。镜像模式不会删除目标目录里的无关文件。源目录不能同步到单个目标文件。

## 项目结构

```
.
├── main.py           # 界面和程序入口
├── core_scanner.py   # 目录扫描和差异比较
├── copy_manager.py   # 复制和删除逻辑，支持续传
├── file_transfer.py  # Windows 原生复制和续传文件的独占保护
├── ui_model.py       # 差异树的 Qt 数据模型
├── ignore_rules.py   # Gitignore 风格匹配和忽略规则保存
├── storage.py        # 配置和忽略文件的原子保存
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
