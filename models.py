"""数据模型与状态机逻辑。

本模块与 UI/IO 解耦，仅包含：
- Status 枚举：频道三态
- Channel dataclass：频道数据模型
- compute_status()：纯函数，根据基准时间与 a/b 计算当前状态
- get_server_time()：时间来源抽象（当前返回本地时间，预留服务器时间扩展）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class Status(Enum):
    """频道 Boss 的状态。"""

    UNRECORDED = "unrecorded"  # 未记录数据（灰）
    PENDING = "pending"        # 待刷新（绿）
    WINDOW = "window"          # 刷新窗口期（黄）
    EXPIRED = "expired"        # 已刷新（红）


@dataclass
class Channel:
    """单个频道的数据模型。

    base_time 为 ISO 8601 字符串，作为状态判定的基准时间；
    source 记录基准来源："init"（初始化）或 "kill"（击杀时间）；
    recorded 标记是否已记录数据（False=灰色未记录态，不参与倒计时）。
    """

    id: int
    name: str
    base_time: str = field(default_factory=lambda: get_server_time().isoformat())
    source: str = "init"
    recorded: bool = False
    checked_time: str = ""  # 最近一次"记为已查"的时刻（ISO 8601，空串表示从未记录）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "base_time": self.base_time,
            "source": self.source,
            "recorded": self.recorded,
            "checked_time": self.checked_time,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Channel":
        return cls(
            id=int(data["id"]),
            name=str(data["name"]),
            base_time=str(data["base_time"]),
            source=str(data.get("source", "init")),
            recorded=bool(data.get("recorded", False)),
            checked_time=str(data.get("checked_time", "")),
        )


def compute_status(
    base_time: str,
    now: datetime,
    a_minutes: float,
    b_minutes: float,
) -> Status:
    """根据基准时间与当前时间计算频道状态。

    状态判定（now - base 为已流逝时长）：
    - 0 <= elapsed < a：待刷新 PENDING
    - a <= elapsed < b：刷新窗口期 WINDOW
    - elapsed >= b：已刷新 EXPIRED
    """
    try:
        base = datetime.fromisoformat(base_time)
    except (ValueError, TypeError):
        # 基准时间非法时，按"已刷新"处理，避免异常扩散
        return Status.EXPIRED

    elapsed = now - base

    # 基准时间在未来（时钟回拨等异常），按待刷新处理
    if elapsed < timedelta(0):
        return Status.PENDING

    if elapsed < timedelta(minutes=a_minutes):
        return Status.PENDING
    if elapsed < timedelta(minutes=b_minutes):
        return Status.WINDOW
    return Status.EXPIRED


def is_expired_beyond(base_time: str, now: datetime, b_minutes: float, factor: float = 2.0) -> bool:
    """判断频道是否已超过刷新周期 b 的 factor 倍时长（默认 2 倍）。

    用于"超时 2 倍 b 以上自动恢复未记录"的判定。
    基准时间非法时返回 False（不触发恢复）。
    """
    try:
        base = datetime.fromisoformat(base_time)
    except (ValueError, TypeError):
        return False
    elapsed = now - base
    return elapsed >= timedelta(minutes=b_minutes * factor)


def format_duration(seconds: float) -> str:
    """将秒数格式化为 "X天X小时X分X秒" 的可读文本，省略前导零单位。"""
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    parts.append(f"{secs}秒")
    return "".join(parts)


def compute_countdown_text(
    base_time: str,
    now: datetime,
    a_minutes: float,
    b_minutes: float,
) -> str:
    """根据基准时间计算格子的倒计时/正计时文本。

    - 待刷新：显示距进入窗口期的剩余时间 "剩余:{倒计时}"
    - 窗口期：显示从进入窗口（a）起的已流逝时长 "已经过:{正计时}"
    - 已刷新：显示超时正计时 "已超时:{正计时}"
    """
    try:
        base = datetime.fromisoformat(base_time)
    except (ValueError, TypeError):
        return "已超时:0秒"

    elapsed = now - base

    if elapsed < timedelta(minutes=a_minutes):
        remaining = timedelta(minutes=a_minutes) - elapsed
        return f"剩余:{format_duration(remaining.total_seconds())}"

    if elapsed < timedelta(minutes=b_minutes):
        since_window = elapsed - timedelta(minutes=a_minutes)
        return f"已经过:{format_duration(since_window.total_seconds())}"

    overtime = elapsed - timedelta(minutes=b_minutes)
    return f"已超时:{format_duration(overtime.total_seconds())}"


def compute_checked_text(
    checked_time: str,
    now: datetime,
    a_minutes: float,
) -> str:
    """根据"记为已查"时刻计算正计时文本。

    - checked_time 为空串 → 返回空字符串（无时间显示）
    - now - checked_time < a_minutes → 返回 "经过:{正计时}"
    - now - checked_time >= a_minutes → 返回空字符串（超过 a 后恢复无时间）
    """
    if not checked_time:
        return ""
    try:
        checked = datetime.fromisoformat(checked_time)
    except (ValueError, TypeError):
        return ""

    elapsed = now - checked
    if elapsed < timedelta(0):
        # 查询时刻在未来（异常），按无时间处理
        return ""

    if elapsed >= timedelta(minutes=a_minutes):
        return ""

    return f"经过:{format_duration(elapsed.total_seconds())}"


def get_server_time() -> datetime:
    """时间来源抽象。

    当前返回本地系统时间；未来接入 NTP/网络 API 时只需修改此处。
    """
    return datetime.now()
