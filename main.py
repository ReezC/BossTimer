"""程序入口：加载数据、构建主窗口、绑定持久化、启动 Tkinter 主循环。

支持同时打开多个数据文件，以页签形式展示。
"""

import json
import os

import tkinter as tk
from tkinter import messagebox

from storage import load_data, save_data
from ui import MainWindow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")  # 用户数据文件目录
STATE_DIR = os.path.join(BASE_DIR, ".bosstimer")  # 内部状态文件目录
DATA_PATH = os.path.join(DATA_DIR, "data.json")
LAST_FILE_PATH = os.path.join(STATE_DIR, "last_file.txt")
LAST_FILES_PATH = os.path.join(STATE_DIR, "last_files.json")


def _ensure_dirs() -> None:
    """确保数据目录与状态目录存在。"""
    for d in (DATA_DIR, STATE_DIR):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def _is_valid_name(name: str) -> bool:
    """校验文件名是否合法（非空且不含路径分隔符）。"""
    if not name:
        return False
    if os.sep in name:
        return False
    if os.altsep and os.altsep in name:
        return False
    return True


def _load_last_state() -> tuple[list[str], str]:
    """读取上次打开的文件列表与聚焦文件。

    返回 (files, current)，files 为有序文件名列表（不含扩展名），
    current 为聚焦文件名（不含扩展名），可能为空串。
    优先读取新格式 last_files.json；兼容旧的 last_file.txt。
    """
    # 新格式：JSON，记录所有打开文件
    if os.path.exists(LAST_FILES_PATH):
        try:
            with open(LAST_FILES_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            if isinstance(state, dict):
                files = state.get("files", [])
                current = state.get("current", "")
                files = [n for n in files if isinstance(n, str) and _is_valid_name(n)]
                if not isinstance(current, str) or not _is_valid_name(current):
                    current = files[-1] if files else ""
                return files, current
        except (json.JSONDecodeError, OSError):
            pass

    # 兼容旧格式：单文件 last_file.txt
    try:
        with open(LAST_FILE_PATH, "r", encoding="utf-8") as f:
            name = f.read().strip()
    except OSError:
        return [], ""
    if _is_valid_name(name):
        return [name], name
    return [], ""


def _save_last_state(files: list[str], current: str) -> None:
    """保存打开文件列表与聚焦文件到状态文件。"""
    try:
        with open(LAST_FILES_PATH, "w", encoding="utf-8") as f:
            json.dump({"files": files, "current": current}, f, ensure_ascii=False)
    except OSError:
        pass


def _normalize_filename(name: str) -> str:
    """确保文件名以 .json 结尾，并返回数据目录下的完整路径。"""
    name = name.strip()
    if not name.lower().endswith(".json"):
        name += ".json"
    return os.path.join(DATA_DIR, name)


def list_data_files() -> list[str]:
    """列出数据目录下所有 .json 数据文件（不含扩展名）。"""
    if not os.path.isdir(DATA_DIR):
        return []
    names = []
    for f in os.listdir(DATA_DIR):
        if f.lower().endswith(".json"):
            names.append(f[:-5])  # 去掉 .json 后缀
    names.sort()
    return names


def main():
    _ensure_dirs()
    root = tk.Tk()

    # 每个打开的文件：{"name": 不含扩展名, "path": 完整路径, "data": dict}
    open_files = []

    # 当前聚焦文件在 open_files 中的索引；-1 表示未打开任何文件
    current_index = {"i": -1}

    def _display_name(name: str) -> str:
        """页签/标题显示名：默认 data 文件显示为 BossTimer。"""
        if name == "data":
            return "BossTimer"
        return name

    def _current() -> dict | None:
        i = current_index["i"]
        if 0 <= i < len(open_files):
            return open_files[i]
        return None

    def _persist_state():
        """将当前打开文件列表与聚焦文件写入状态文件。"""
        files = [f["name"] for f in open_files]
        cur = _current()
        current_name = cur["name"] if cur is not None else ""
        _save_last_state(files, current_name)

    def _update_title():
        cur = _current()
        if cur is None:
            root.title("BossTimer")
        else:
            root.title(_display_name(cur["name"]))

    def _notify_open_files_changed():
        """页签集合变化后，通知 UI 刷新页签栏与当前内容。"""
        window.on_files_changed(open_files, current_index["i"])
        window.on_data_changed(_current())

    def _notify_data_changed():
        """当前聚焦文件数据变化后，通知 UI 刷新内容。"""
        window.on_data_changed(_current())

    def on_change(current_data):
        """数据变更时立即写回当前聚焦文件。"""
        cur = _current()
        if cur is not None:
            save_data(current_data, cur["path"])

    def on_save_file(name: str):
        """将当前聚焦文件的数据保存（另存为）到用户命名的文件。

        保存成功后，当前聚焦文件的路径切换到新文件。
        返回 None 表示成功，返回 str 表示错误信息。
        """
        cur = _current()
        if cur is None:
            return "当前没有打开的文件。"
        try:
            path = _normalize_filename(name)
            save_data(cur["data"], path)
        except OSError as e:
            return f"无法写入文件：{e}"
        cur["name"] = name
        cur["path"] = path
        _persist_state()
        _notify_open_files_changed()
        _update_title()
        return None

    def on_load_file(name: str):
        """新打开一个文件（作为新页签），而非替换当前文件。

        返回 dict 表示成功，返回 str 表示错误信息。
        """
        path = _normalize_filename(name)
        # 若同名文件已打开，直接聚焦到它
        for i, f in enumerate(open_files):
            if os.path.abspath(f["path"]) == os.path.abspath(path):
                current_index["i"] = i
                _persist_state()
                _notify_open_files_changed()
                _update_title()
                return f["data"]

        if not os.path.exists(path):
            return f"文件不存在：{path}"
        loaded = load_data(path)
        if loaded is None:
            return "文件内容无效。"

        open_files.append({"name": name, "path": path, "data": loaded})
        current_index["i"] = len(open_files) - 1
        _persist_state()
        _notify_open_files_changed()
        _update_title()
        return loaded

    def on_delete_file(name: str):
        """删除指定数据文件；返回 None 表示成功，返回 str 表示错误信息。"""
        path = _normalize_filename(name)
        if not os.path.exists(path):
            return f"文件不存在：{path}"
        try:
            os.remove(path)
        except OSError as e:
            return f"无法删除文件：{e}"

        # 若该文件正打开，关闭其页签
        for i in range(len(open_files) - 1, -1, -1):
            if os.path.abspath(open_files[i]["path"]) == os.path.abspath(path):
                del open_files[i]
        # 修正聚焦索引
        if current_index["i"] >= len(open_files):
            current_index["i"] = len(open_files) - 1
        elif current_index["i"] < 0 and open_files:
            current_index["i"] = 0
        _persist_state()
        _notify_open_files_changed()
        _update_title()
        return None

    def on_close_tab(index: int):
        """关闭指定索引的页签（不删除磁盘文件）。"""
        if 0 <= index < len(open_files):
            del open_files[index]
        if not open_files:
            current_index["i"] = -1
        else:
            # 删除后聚焦到相邻页签：优先保持在原位置，越界则回退到最后一个
            if current_index["i"] >= len(open_files):
                current_index["i"] = len(open_files) - 1
            elif current_index["i"] < 0:
                current_index["i"] = 0
        _persist_state()
        _notify_open_files_changed()
        _update_title()

    def on_switch_tab(index: int):
        """切换到指定索引的页签。"""
        if 0 <= index < len(open_files):
            current_index["i"] = index
            _persist_state()
            _notify_open_files_changed()
            _update_title()

    def on_move_tab(index: int, direction: int):
        """移动指定索引的页签顺序（direction 为 -1 左移、1 右移）。"""
        n = len(open_files)
        target = index + direction
        if not (0 <= index < n and 0 <= target < n):
            return
        # 交换 open_files 中相邻两项
        open_files[index], open_files[target] = open_files[target], open_files[index]
        # 同步更新聚焦索引
        if current_index["i"] == index:
            current_index["i"] = target
        elif current_index["i"] == target:
            current_index["i"] = index
        _persist_state()
        _notify_open_files_changed()
        _update_title()

    # 创建主窗口（初始可能没有打开文件）
    window = MainWindow(
        root,
        on_change=on_change,
        on_save_file=on_save_file,
        on_load_file=on_load_file,
        on_list_files=list_data_files,
        on_delete_file=on_delete_file,
        on_close_tab=on_close_tab,
        on_switch_tab=on_switch_tab,
        on_move_tab=on_move_tab,
    )

    # 启动时尝试恢复上次打开的所有文件与聚焦文件
    last_files, last_current = _load_last_state()
    for name in last_files:
        path = _normalize_filename(name)
        if os.path.exists(path):
            open_files.append(
                {"name": name, "path": path, "data": load_data(path)}
            )
    # 定位聚焦文件
    if open_files:
        target = -1
        for i, f in enumerate(open_files):
            if f["name"] == last_current:
                target = i
                break
        current_index["i"] = target if target >= 0 else 0

    _notify_open_files_changed()
    _update_title()

    def on_close():
        """窗口关闭前做最终保存兜底，并记录当前打开的所有文件与聚焦文件。"""
        for f in open_files:
            save_data(f["data"], f["path"])
        _persist_state()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
