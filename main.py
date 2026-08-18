"""程序入口：加载数据、构建主窗口、绑定持久化、启动 Tkinter 主循环。

支持同时打开多个数据文件，以页签形式展示。
"""

import json
import os

import tkinter as tk

from storage import load_data, save_data
from ui import MainWindow

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")  # 用户数据文件目录
STATE_DIR = os.path.join(BASE_DIR, ".bosstimer")  # 内部状态文件目录
DATA_PATH = os.path.join(DATA_DIR, "data.json")
LAST_FILE_PATH = os.path.join(STATE_DIR, "last_file.txt")
LAST_FILES_PATH = os.path.join(STATE_DIR, "last_files.json")

# 文件名中禁止出现的字符（避免路径穿越/非法路径）
_INVALID_NAME_CHARS = set('\\/:*?"<>|')


def _ensure_dirs() -> None:
    """确保数据目录与状态目录存在。"""
    for d in (DATA_DIR, STATE_DIR):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def _is_valid_name(name: str) -> bool:
    """校验文件名是否合法：非空、不含路径分隔符与非法字符、不含 '..'。"""
    if not name or not name.strip():
        return False
    if os.sep in name or (os.altsep and os.altsep in name):
        return False
    if name in (".", "..") or name.startswith("../") or name.startswith("..\\"):
        return False
    if any(c in _INVALID_NAME_CHARS for c in name):
        return False
    return True


def _load_last_state() -> tuple[list[str], str]:
    """读取上次打开的文件列表与聚焦文件。

    返回 (files, current)，files 为有序文件名列表（不含扩展名），
    current 为聚焦文件名（不含扩展名），可能为空串。
    优先读取新格式 last_files.json；兼容旧的 last_file.txt。
    """
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


class App:
    """应用控制器：管理多文件页签状态，并桥接 UI 与持久化。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        # 每个打开的文件：{"name": 不含扩展名, "path": 完整路径, "data": dict}
        self.open_files: list[dict] = []
        # 当前聚焦文件在 open_files 中的索引；-1 表示未打开任何文件
        self.current_index: int = -1

        self.window = MainWindow(
            root,
            on_change=self.on_change,
            on_save_file=self.on_save_file,
            on_load_file=self.on_load_file,
            on_list_files=list_data_files,
            on_delete_file=self.on_delete_file,
            on_close_tab=self.on_close_tab,
            on_switch_tab=self.on_switch_tab,
            on_move_tab=self.on_move_tab,
        )

    # ---------- 内部工具 ----------

    def _display_name(self, name: str) -> str:
        """页签/标题显示名：默认 data 文件显示为 BossTimer。"""
        return "BossTimer" if name == "data" else name

    def _current(self) -> dict | None:
        if 0 <= self.current_index < len(self.open_files):
            return self.open_files[self.current_index]
        return None

    def _persist_state(self):
        files = [f["name"] for f in self.open_files]
        cur = self._current()
        current_name = cur["name"] if cur is not None else ""
        _save_last_state(files, current_name)

    def _update_title(self):
        cur = self._current()
        self.root.title(self._display_name(cur["name"]) if cur is not None else "BossTimer")

    def _commit(self):
        """状态变更后的统一收尾：持久化 + 刷新 UI + 更新标题。"""
        self._persist_state()
        self.window.on_files_changed(self.open_files, self.current_index)
        self.window.on_data_changed(self._current())
        self._update_title()

    def _save_current(self, file: dict) -> str | None:
        """安全保存单个文件，返回错误信息（None 表示成功）。"""
        try:
            save_data(file["data"], file["path"])
        except OSError as e:
            return f"无法写入文件：{e}"
        return None

    # ---------- UI 回调 ----------

    def on_change(self, current_data):
        """数据变更时立即写回当前聚焦文件。"""
        cur = self._current()
        if cur is not None:
            self._save_current(cur)

    def on_save_file(self, name: str):
        """将当前聚焦文件的数据另存为到用户命名的文件。

        返回 None 表示成功，返回 str 表示错误信息。
        """
        if not _is_valid_name(name):
            return "文件名不合法。"
        cur = self._current()
        if cur is None:
            return "当前没有打开的文件。"
        path = _normalize_filename(name)
        err = self._save_current({"data": cur["data"], "path": path})
        if err is not None:
            return err
        cur["name"] = name
        cur["path"] = path
        self._commit()
        return None

    def on_load_file(self, name: str):
        """新打开一个文件（作为新页签），而非替换当前文件。

        返回 dict 表示成功，返回 str 表示错误信息。
        """
        if not _is_valid_name(name):
            return "文件名不合法。"
        path = _normalize_filename(name)
        # 若同名文件已打开，直接聚焦到它
        for i, f in enumerate(self.open_files):
            if os.path.abspath(f["path"]) == os.path.abspath(path):
                self.current_index = i
                self._commit()
                return f["data"]

        if not os.path.exists(path):
            return f"文件不存在：{path}"
        loaded = load_data(path)
        if loaded is None:
            return "文件内容无效。"

        self.open_files.append({"name": name, "path": path, "data": loaded})
        self.current_index = len(self.open_files) - 1
        self._commit()
        return loaded

    def on_delete_file(self, name: str):
        """删除指定数据文件；返回 None 表示成功，返回 str 表示错误信息。"""
        if not _is_valid_name(name):
            return "文件名不合法。"
        path = _normalize_filename(name)
        if not os.path.exists(path):
            return f"文件不存在：{path}"
        try:
            os.remove(path)
        except OSError as e:
            return f"无法删除文件：{e}"

        # 若该文件正打开，关闭其页签
        for i in range(len(self.open_files) - 1, -1, -1):
            if os.path.abspath(self.open_files[i]["path"]) == os.path.abspath(path):
                del self.open_files[i]
        self._fix_index_after_removal()
        self._commit()
        return None

    def on_close_tab(self, index: int):
        """关闭指定索引的页签（不删除磁盘文件）。"""
        if 0 <= index < len(self.open_files):
            del self.open_files[index]
        self._fix_index_after_removal()
        self._commit()

    def on_switch_tab(self, index: int):
        """切换到指定索引的页签。"""
        if 0 <= index < len(self.open_files):
            self.current_index = index
            self._commit()

    def on_move_tab(self, index: int, direction: int):
        """移动指定索引的页签顺序（direction 为 -1 左移、1 右移）。"""
        n = len(self.open_files)
        target = index + direction
        if not (0 <= index < n and 0 <= target < n):
            return
        self.open_files[index], self.open_files[target] = (
            self.open_files[target],
            self.open_files[index],
        )
        # 同步更新聚焦索引
        if self.current_index == index:
            self.current_index = target
        elif self.current_index == target:
            self.current_index = index
        self._commit()

    def _fix_index_after_removal(self):
        """删除页签后修正聚焦索引。"""
        if not self.open_files:
            self.current_index = -1
        elif self.current_index >= len(self.open_files):
            self.current_index = len(self.open_files) - 1
        elif self.current_index < 0:
            self.current_index = 0

    # ---------- 启动与关闭 ----------

    def restore_last_session(self):
        """启动时恢复上次打开的所有文件与聚焦文件。"""
        last_files, last_current = _load_last_state()
        for name in last_files:
            path = _normalize_filename(name)
            if os.path.exists(path):
                self.open_files.append(
                    {"name": name, "path": path, "data": load_data(path)}
                )
        if self.open_files:
            target = -1
            for i, f in enumerate(self.open_files):
                if f["name"] == last_current:
                    target = i
                    break
            self.current_index = target if target >= 0 else 0
        self.window.on_files_changed(self.open_files, self.current_index)
        self.window.on_data_changed(self._current())
        self._update_title()

    def on_close(self):
        """窗口关闭前做最终保存兜底，并记录当前打开的所有文件与聚焦文件。"""
        for f in self.open_files:
            self._save_current(f)
        self._persist_state()
        self.root.destroy()


def main():
    _ensure_dirs()
    root = tk.Tk()
    app = App(root)
    app.restore_last_session()
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
