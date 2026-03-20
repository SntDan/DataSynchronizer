# Data Synchronizer (数据同步工具)

[English](#english) | [中文](#中文)

---

<span id="english"></span>
## 🇬🇧 English

**Data Synchronizer** is a high-performance, responsive desktop application built with Python and PySide6, specifically designed for syncing such as massive photo libraries, massive codebases, and backups. It bypasses standard UI bottlenecks to provide a smooth, freeze-free synchronization experience.

### 🌟 Key Features

- **Extreme Scanning Performance**: Combines `os.scandir` with a local `SQLite` snapshot cache. Reduces repetitive disk I/O by comparing Size, MTime, and an optional `xxhash` deep validation.
- **Anti-Freeze Smart UI**: Renders millions of differences without crashing. The custom `QTreeView` implements smart truncation (shows 10 items + `... Show All` per folder level) ensuring O(1) render complexity.
- **Intelligent Color Aggregation**: Folders smoothly inherit the status of their contents. A folder turns **Green** if it only contains new files, **Orange** for modified files, and **Red/Gray** for removable "extra" files.
- **HDD Optimized Copying**: Uses a tightly controlled `ThreadPoolExecutor` single-thread queue dispatcher to minimize mechanical hard drive (HDD) seek times, along with breakpoint-resume (`ab` mode) for large file interruptions.
- **Mirror Mode (Delete Extra Files)**: Dynamically checks and marks files that exist in the target but not in the source. Highlights them conditionally (Red when deletion is enabled, Gray when ignored).
- **Read-Only Permission Penetration**: Automatically mitigates Windows `[WinError 5]` access denied errors to smoothly clean up stubborn read-only objects (like `.git` files or `.base` objects).
- **Bilingual Interface**: Seamlessly toggle between English and Chinese inside the app.

### 🚀 Installation & Usage

1. **Install Dependencies**:
   Ensure you have Python 3.8+ installed, then run:
   ```bash
   pip install PySide6 xxhash
   ```

2. **Run the App**:
   ```bash
   python main.py
   ```

3. **Workflow**:
   - **Browse**: Select your `Source` and `Target` directories.
   - **Check 'Remove Extra Files'**: Turn on if you want a perfect mirror (deletes destination-only files).
   - **Scan**: Click `Scan Differences`. The app fetches everything safely in the background.
   - **Sync**: Verify the dynamic tree list and click `Start Synchronization`.

---

<span id="中文"></span>
## 🇨🇳 中文

**数据同步工具 (Data Synchronizer)** 是一款基于 Python 和 PySide6 开发的高性能桌面端文件同步软件。专为处理海量照片库、复杂代码库、深度备份的同步而设计，告别传统同步工具在海量文件下的卡顿和内存溢出问题。

### 🌟 核心特性

- **极致扫描性能**：将底层最高效的 `os.scandir` 结合 `SQLite` 本地快照缓存。通过比对文件大小 (Size)、修改时间 (MTime) 以及可选的 `xxHash` 深度校验，极限压缩机械硬盘的重复寻道。
- **抗压大容量 UI**：独创的树形控件截断渲染技术。单文件夹超过10个文件自动折叠为 `... Show All`，保障再庞大的文件树也能光速渲染，拒绝 UI 卡死崩溃。
- **智能状态冒泡着色**：文件夹会根据子集文件的状态自动推导颜色。内部全是新增文件则变**绿**，全是修改变**橙**，包含多余文件则变**红**。
- **机械硬盘 (HDD) 优化拷贝**：采用并发池调度，优化物理读写逻辑。支持大文件的块级断点续传（`ab` 模式追加），中断重连无须重头开始。
- **镜像模式（清理多余文件）**：安全识别目标盘多余文件。勾选删除选项时动态高亮为红色（警示），未勾选则显示为灰色（安全），做到心中有数。
- **强制权限穿透**：无惧 Windows `[WinError 5]` 拒绝访问报错，自动处理深层带有只读属性的难缠文件（如庞大的 `.git` 历史对象或锁定文件）的移除。
- **双语极简界面**：内置一键中英双语切换，操作直观。

### 🚀 安装与使用

1. **安装依赖**：
   请确保你的电脑已安装 Python 3.8+，然后执行：
   ```bash
   pip install PySide6 xxhash
   ```

2. **启动程序**：
   ```bash
   python main.py
   ```

3. **使用流程**：
   - **选择路径**：设置 `源目录 (Source)` 与 `目标目录 (Target)`。
   - **镜像选项**：如有清空目标目录无用文件的需求，请勾选“删除目标多余文件”。
   - **一键扫描**：点击 `1. 扫描差异`，程序将在后台非阻塞极速比对。
   - **审核与同步**：在渲染出的树状图中检查各颜色标记的文件，确认无误后点击 `2. 开始同步`。

### 🛠 技术栈 / Architecture
- **GUI Framework**: Qt for Python (`PySide6`) - QTreeView, QAbstractItemModel
- **Data Caching**: `sqlite3`
- **Hash Check**: `xxhash`
- **Concurrency**: `QThread`, `concurrent.futures.ThreadPoolExecutor`