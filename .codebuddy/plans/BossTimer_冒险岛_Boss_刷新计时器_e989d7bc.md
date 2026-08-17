---
name: BossTimer 冒险岛 Boss 刷新计时器
overview: 用 Python + Tkinter 开发一个桌面计时器，记录冒险岛各频道 Boss 刷新状态（待刷新/刷新窗口期/已刷新），支持动态配置频道数量和刷新周期参数，数据本地持久化。
todos:
  - id: models
    content: 创建 models.py：实现 Status 枚举、Channel dataclass、compute_status() 纯函数与 get_server_time() 时间来源抽象
    status: completed
  - id: storage
    content: 创建 storage.py：实现 load_data()/save_data()，JSON 读写与默认值初始化
    status: completed
    dependencies:
      - models
  - id: ui-window
    content: 创建 ui.py 主窗口：顶部实时时钟、a/b 设置栏、频道增删与格子网格布局
    status: completed
    dependencies:
      - models
      - storage
  - id: ui-dialogs
    content: 创建 ui.py 弹窗：频道编辑弹窗（初始化/自定义按钮）与击杀时间输入弹窗，含输入校验
    status: completed
    dependencies:
      - ui-window
  - id: main
    content: 创建 main.py 程序入口：加载数据、构建主窗口、绑定状态刷新与保存、启动主循环
    status: completed
    dependencies:
      - ui-window
      - ui-dialogs
  - id: polish-test
    content: 整体运行验证：状态切换颜色、持久化恢复、增删频道与 a/b 修改的正确性
    status: completed
    dependencies:
      - main
---

## 产品概述

一个记录冒险岛 Boss 刷新时间的桌面面板程序，使用 Python + Tkinter 开发，本地窗口运行。用户可在面板上管理多个频道（格子），跟踪每个频道 Boss 的刷新状态，并通过颜色直观区分「待刷新」「刷新窗口期」「已刷新」。

## 核心功能

1. **顶部实时时钟**：面板顶部显示当前时间（先采用本地系统时间，预留服务器时间扩展接口）。
2. **频道格子**：面板可设置 n 个格子，每个格子代表一个频道，用于记录该频道 Boss 状态；支持界面内动态增加/删除频道。
3. **刷新周期配置**：面板可配置 Boss 刷新周期下限 a 与上限 b（单位：小时）。
4. **三态可视化**：格子状态分为「待刷新」「刷新窗口期」「已刷新」，用不同颜色区分（待刷新=绿，窗口期=黄，已刷新=红）。
5. **状态判定逻辑**：以每频道「基准时间」（击杀/初始化时间）为起点：经过 < a 小时为待刷新；a ≤ 经过时间 < b 为窗口期；≥ b 为已刷新。
6. **点击编辑弹窗**：点击任意格子弹出编辑弹窗，含「初始化」按钮（重置为初始待刷新状态，基准时间=当前时间）和「自定义」按钮（弹窗输入击杀时间，以该时间为基准初始化）。
7. **数据持久化**：关闭程序后重新打开，能恢复各频道状态、a/b 参数、频道数量（本地 JSON 文件存储）。

## 技术栈

- **语言/框架**：Python 3 + Tkinter（标准库，无第三方依赖）
- **数据持久化**：本地 JSON 文件（`data.json`），使用 `json` 标准库
- **时间处理**：`datetime` / `time` 标准库；定时刷新用 Tkinter `after()` 方法

## 实现方案

### 整体策略

采用单文件分层结构（models / storage / ui / main），核心状态机逻辑与 UI 分离，便于测试与后续扩展服务器时间。数据模型用 dataclass 表示频道，配置项（a/b/频道列表）与频道数据统一存于 JSON。

### 状态机设计

每个频道保存一个「基准时间」（ISO 字符串）及可选的「基准来源」（初始化 / 击杀）。

- 待刷新：`0 <= (now - base) < a小时`
- 刷新窗口期：`a小时 <= (now - base) < b小时`
- 已刷新：`(now - base) >= b小时`

状态由纯函数 `compute_status(base_time, now, a, b) -> Status` 计算，返回枚举（PENDING / WINDOW / EXPIRED）。

### 时间刷新机制

- 主窗口用 `after(1000, tick)` 每秒更新顶部时间显示。
- 每次 tick 同时重新计算所有频道当前状态并更新格子颜色。频道数量通常为个位数到几十，每秒重算与颜色更新开销可忽略。
- 预留 `get_server_time()` 函数作为时间来源抽象，当前返回 `datetime.now()`，未来可替换为 NTP/网络 API。

### 持久化设计

JSON 结构：

```
{
  "refresh_lower_hours": 4,
  "refresh_upper_hours": 6,
  "channels": [
    {"id": 1, "name": "频道1", "base_time": "2026-08-16T10:00:00", "source": "kill"}
  ]
}
```

- 启动时读取 `data.json`，不存在则用默认值初始化。
- 每次修改（增删频道、编辑状态、修改 a/b）后立即写回文件。
- 窗口关闭事件（`WM_DELETE_WINDOW` 协议）做最终保存兜底。

### 性能与可靠性

- 时间采用 `datetime.now()` 与 `datetime.fromisoformat()`，避免浮点时间误差。
- 所有弹窗输入做合法性校验（击杀时间格式、a/b 数值需满足 `0 < a < b`），非法输入弹提示且不写入。

## 目录结构

全新项目，创建以下文件：

```
BossTimer/
├── main.py          # [NEW] 程序入口，创建主窗口并启动 Tkinter 主循环
├── models.py        # [NEW] 数据模型与状态机逻辑：Status 枚举、Channel dataclass、compute_status() 纯函数、get_server_time()
├── storage.py       # [NEW] 持久化层：load_data() / save_data()，读写 data.json，默认值初始化
├── ui.py            # [NEW] UI 层：MainWindow 主窗口类、ChannelEditDialog 编辑弹窗类、KillTimeDialog 击杀时间输入弹窗
└── data.json        # [NEW] 运行时自动生成的持久化数据文件（首次运行创建）
```

## 关键代码结构

### models.py 核心接口

```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class Status(Enum):
    PENDING = "pending"   # 待刷新
    WINDOW = "window"     # 刷新窗口期
    EXPIRED = "expired"   # 已刷新

@dataclass
class Channel:
    id: int
    name: str
    base_time: str          # ISO 8601 字符串
    source: str = "init"    # "init" 或 "kill"

def compute_status(base_time: str, now: datetime, a_hours: float, b_hours: float) -> Status: ...
def get_server_time() -> datetime: ...  # 当前返回 datetime.now()，预留扩展
```

### storage.py 核心接口

```python
def load_data(path: str = "data.json") -> dict: ...  # 不存在则返回默认
def save_data(data: dict, path: str = "data.json") -> None: ...
```

### ui.py 核心接口

```python
class MainWindow:  # Tk 主窗口
    def _build_clock(self): ...       # 顶部时间标签
    def _build_settings(self): ...    # a/b 输入 + 增删频道按钮
    def _build_grid(self): ...        # 频道格子网格
    def _refresh_channels(self): ...  # 重算状态并更新格子颜色
    def _tick(self): ...              # after 每秒触发

class ChannelEditDialog:  # 频道编辑弹窗（初始化 + 自定义击杀时间）
class KillTimeDialog:      # 击杀时间输入弹窗
```

## 设计说明

- **单一职责**：models 管状态机、storage 管 IO、ui 管交互、main 管启动，逻辑与界面解耦。
- **可扩展性**：时间来源抽象为 `get_server_time()`，后续接 NTP/API 只需改一处。
- **颜色可视化**：格子背景色映射状态（绿/黄/红），格子内显示频道名与状态文字。
- **数据校验**：a/b 需满足 `0 < a < b`，击杀时间需为合法日期时间。