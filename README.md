# Data Synchronizer

[English](#english) | [中文](#中文)

---

<a name="english"></a>
## Data Synchronizer

A small PySide6 desktop tool for one-way file synchronization. It compares source and target folders, shows the differences, then copies new or modified files after confirmation.

## Features

- Compare multiple source/target directory pairs in one run
- Show new, modified, and extra target files in a tree view
- Copy new and modified files from source to target
- Optional mirror mode to remove extra target files and folders
- Resume interrupted copies
- Use a local SQLite snapshot database for faster later scans
- Treat `/`, `\`, and Windows path casing as the same snapshot identity
- Switch between English and Simplified Chinese

## Requirements

| Dependency | Version |
|---|---|
| Python | >= 3.10 |
| PySide6 | >= 6.5 |
| xxhash | >= 3.0 |

## Usage

```bash
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
    }
  ],
  "copy_workers": 4,
  "default_language": "zh_CN"
}
```

- `directory_pairs`: independent one-way sync groups
- `copy_workers`: maximum concurrent copy workers
- `default_language`: `en_US` or `zh_CN`

## Notes

Folders that contain differences are always shown. If one folder has many changed files, only the first 10 files are shown at first; click **... Show All** to expand them.

Mirror mode deletes `[EXTRA]` and `[EXTRA_DIR]` items from the target. Keep it off if the target contains files you want to preserve.

## Project Structure

```
.
├── main.py           # UI and application entry point
├── core_scanner.py   # Directory scanner and diff engine
├── copy_manager.py   # Copy/delete engine with resume support
├── ui_model.py       # Qt model for the diff tree
├── config.json       # User configuration
└── sync_snapshot.db  # Generated snapshot database
```

## Build

```bash
pyinstaller --noconfirm --onefile --windowed --name DataSynchronizer main.py
```

## License

[MIT](LICENSE)

---

<a name="中文"></a>
## Data Synchronizer

一个基于 PySide6 的轻量文件同步工具。它会比较源目录和目标目录，先显示差异，确认后再把新增或修改的文件复制到目标目录。

## 功能

- 一次处理多组源目录和目标目录
- 用树状列表显示新增、修改和目标端多余文件
- 单向同步：源目录复制到目标目录
- 可选镜像模式：删除目标端多余文件和文件夹
- 支持中断后续传
- 使用本地 SQLite 快照数据库加快后续扫描
- 正反斜杠和 Windows 路径大小写会按同一组快照识别
- 支持英文和简体中文界面

## 运行要求

| 依赖 | 版本 |
|---|---|
| Python | >= 3.10 |
| PySide6 | >= 6.5 |
| xxhash | >= 3.0 |

## 使用方法

```bash
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
    }
  ],
  "copy_workers": 4,
  "default_language": "zh_CN"
}
```

- `directory_pairs`：独立的单向同步组
- `copy_workers`：最大并发复制线程数
- `default_language`：`en_US` 或 `zh_CN`

## 说明

所有包含差异的文件夹都会显示。单个文件夹内文件过多时，默认只显示前 10 个文件，点击 **... Show All** 可展开其余内容。

镜像模式会删除目标目录中的 `[EXTRA]` 和 `[EXTRA_DIR]` 项。如果目标目录里有需要保留的文件，请不要开启镜像模式。

## 项目结构

```
.
├── main.py           # 界面和程序入口
├── core_scanner.py   # 目录扫描和差异比较
├── copy_manager.py   # 复制和删除逻辑，支持续传
├── ui_model.py       # 差异树的 Qt 数据模型
├── config.json       # 用户配置
└── sync_snapshot.db  # 自动生成的快照数据库
```

## 打包

```bash
pyinstaller --noconfirm --onefile --windowed --name DataSynchronizer main.py
```

## 许可

[MIT](LICENSE)
