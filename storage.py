"""持久化层：JSON 文件的读写与默认值初始化。

数据文件结构：
{
  "refresh_lower_minutes": 25,
  "refresh_upper_minutes": 35,
  "channels": [
    {"id": 1, "name": "频道1", "base_time": "2026-08-16T10:00:00", "source": "kill"}
  ]
}
"""

from __future__ import annotations

import json
import os

from models import Channel, get_server_time

DEFAULT_LOWER_MINUTES = 25
DEFAULT_UPPER_MINUTES = 35
DEFAULT_CHANNEL_COUNT = 60


def new_data() -> dict:
    """生成一份新的默认数据（新建文件 / 首次运行使用）。

    默认频道 recorded=False（未记录数据，灰色），等待用户勾选标记。
    """
    channels = [
        Channel(
            id=i + 1,
            name=f"频道{i + 1}",
            base_time=get_server_time().isoformat(),
            source="init",
            recorded=False,
        ).to_dict()
        for i in range(DEFAULT_CHANNEL_COUNT)
    ]
    return {
        "refresh_lower_minutes": DEFAULT_LOWER_MINUTES,
        "refresh_upper_minutes": DEFAULT_UPPER_MINUTES,
        "channels": channels,
    }


def _default_data() -> dict:
    """向后兼容别名（load_data 内部使用）。"""
    return new_data()


def load_data(path: str = "data.json") -> dict:
    """从文件加载数据；文件不存在或内容非法时返回默认数据。

    兼容旧版本数据：若存在 refresh_lower_hours / refresh_upper_hours
    （单位为小时），则将其值 ×60 转换为分钟。
    """
    if not os.path.exists(path):
        return _default_data()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_data()

    # 基本结构校验与补齐
    if not isinstance(data, dict):
        return _default_data()

    try:
        if "refresh_lower_minutes" in data or "refresh_upper_minutes" in data:
            # 新格式：直接读取分钟值
            lower = float(data.get("refresh_lower_minutes", DEFAULT_LOWER_MINUTES))
            upper = float(data.get("refresh_upper_minutes", DEFAULT_UPPER_MINUTES))
        elif "refresh_lower_hours" in data or "refresh_upper_hours" in data:
            # 旧格式：单位为小时，转换为分钟
            lower = float(data.get("refresh_lower_hours", DEFAULT_LOWER_MINUTES)) * 60
            upper = float(data.get("refresh_upper_hours", DEFAULT_UPPER_MINUTES)) * 60
        else:
            lower = DEFAULT_LOWER_MINUTES
            upper = DEFAULT_UPPER_MINUTES
    except (TypeError, ValueError):
        lower = DEFAULT_LOWER_MINUTES
        upper = DEFAULT_UPPER_MINUTES

    # 保证 0 < lower < upper，否则回退默认
    if not (0 < lower < upper):
        lower = DEFAULT_LOWER_MINUTES
        upper = DEFAULT_UPPER_MINUTES

    channels_raw = data.get("channels", [])
    channels = []
    if isinstance(channels_raw, list):
        for item in channels_raw:
            if not isinstance(item, dict):
                continue
            try:
                channels.append(Channel.from_dict(item))
            except (KeyError, ValueError, TypeError):
                continue

    # 若频道为空，回退为一个默认频道
    if not channels:
        channels = [
            Channel(
                id=1,
                name="频道1",
                base_time=get_server_time().isoformat(),
                source="init",
            )
        ]

    return {
        "refresh_lower_minutes": lower,
        "refresh_upper_minutes": upper,
        "channels": [c.to_dict() for c in channels],
    }


def save_data(data: dict, path: str = "data.json") -> None:
    """将数据原子地写回 JSON 文件。

    先写入同目录下的临时文件，再替换目标文件，避免写入中断导致文件损坏。
    写入失败时抛出 OSError，由调用方处理。
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
