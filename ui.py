"""UI 层：主窗口、页签栏、频道格子、编辑弹窗与击杀时间输入弹窗。

包含：
- MainWindow：顶部页签栏、实时时钟、a/b 设置栏、频道增删按钮、格子网格
- ChannelEditDialog：点击格子弹出的编辑弹窗（初始化 / 自定义击杀时间）
- KillTimeDialog：击杀时间输入弹窗
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog
from datetime import datetime

from models import (
    Channel,
    Status,
    compute_checked_text,
    compute_countdown_text,
    compute_status,
    get_server_time,
    is_expired_beyond,
)

# 状态 -> (中文标签, 背景色)
STATUS_DISPLAY = {
    Status.UNRECORDED: ("未记录", "#9E9E9E"),
    Status.PENDING: ("待刷新", "#4CAF50"),
    Status.WINDOW: ("窗口期", "#FFC107"),
    Status.EXPIRED: ("已刷新", "#F44336"),
}

# 格子网格每行的格子数量
GRID_COLUMNS = 6

# 页签激活/非激活时的背景色
TAB_ACTIVE_BG = "#FFFFFF"
TAB_INACTIVE_BG = "#DDDDDD"


class MainWindow:
    """主窗口，支持多文件页签。"""

    def __init__(
        self,
        root: tk.Tk,
        on_change=None,
        on_save_file=None,
        on_load_file=None,
        on_list_files=None,
        on_delete_file=None,
        on_close_tab=None,
        on_switch_tab=None,
        on_move_tab=None,
    ):
        self.root = root
        self.on_change = on_change  # 数据变更回调（用于持久化）
        self.on_save_file = on_save_file  # 保存到指定文件回调
        self.on_load_file = on_load_file  # 新打开文件回调
        self.on_list_files = on_list_files  # 列出已有数据文件的回调
        self.on_delete_file = on_delete_file  # 删除数据文件的回调
        self.on_close_tab = on_close_tab  # 关闭页签回调
        self.on_switch_tab = on_switch_tab  # 切换页签回调
        self.on_move_tab = on_move_tab  # 移动页签顺序回调

        # 当前聚焦文件数据（dict）或 None（未打开任何文件）
        self.data = None
        # 当前聚焦文件的显示名（不含扩展名），None 表示无
        self.current_name = None

        self.lower_var = tk.StringVar(value="")
        self.upper_var = tk.StringVar(value="")

        # 频道格子控件：id -> Text
        self.channel_buttons: dict[int, tk.Text] = {}

        # 页签栏相关控件
        self.tab_frame = None
        self.tab_buttons = {}  # index -> (标签 Frame, 文本 Label, 关闭 Label)

        self._build_clock()
        self._build_tabbar()
        self._build_settings()
        self._build_filebar()
        self._build_grid()

        self._update_empty_state()
        self._tick()

    # ---------- 构建 UI ----------

    def _build_clock(self):
        frame = tk.Frame(self.root)
        frame.pack(fill="x", padx=10, pady=(10, 0))
        self.clock_label = tk.Label(
            frame, text="", font=("Arial", 20, "bold"), fg="#333333"
        )
        self.clock_label.pack()

    def _build_tabbar(self):
        """构建页签栏：左侧固定"打开文件"按钮，右侧动态页签区。"""
        self.tabbar_frame = tk.Frame(self.root)
        self.tabbar_frame.pack(fill="x", padx=10, pady=(5, 0))

        # 始终可见的"打开文件"按钮（空状态时也需要能打开文件）
        open_btn = tk.Button(
            self.tabbar_frame, text="从文件读取（新开）", command=self._load_from_file
        )
        open_btn.pack(side="left", padx=(0, 10))

        # 动态页签容器
        self.tab_frame = tk.Frame(self.tabbar_frame)
        self.tab_frame.pack(side="left", fill="x")

    def _build_settings(self):
        self.settings_frame = tk.Frame(self.root)

        tk.Label(self.settings_frame, text="刷新周期下限 a (分钟):").pack(side="left")
        tk.Entry(self.settings_frame, textvariable=self.lower_var, width=6).pack(
            side="left", padx=(0, 10)
        )

        tk.Label(self.settings_frame, text="上限 b (分钟):").pack(side="left")
        tk.Entry(self.settings_frame, textvariable=self.upper_var, width=6).pack(
            side="left", padx=(0, 10)
        )

        tk.Button(
            self.settings_frame, text="应用", command=self._apply_settings
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            self.settings_frame, text="+ 增加频道", command=self._add_channel
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            self.settings_frame, text="- 删除频道", command=self._remove_channel
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            self.settings_frame,
            text="一键重置",
            command=self._reset_all,
            fg="#F44336",
        ).pack(side="left")

    def _build_filebar(self):
        self.filebar_frame = tk.Frame(self.root)

        tk.Button(
            self.filebar_frame, text="另存为", command=self._save_to_file
        ).pack(side="left")

    def _build_grid(self):
        self.grid_frame = tk.Frame(self.root)

    # ---------- 页签栏渲染 ----------

    def on_files_changed(self, open_files: list, current_index: int):
        """页签集合变化后由 main 调用：重建页签栏、高亮当前页签。"""
        self._render_tabs(open_files, current_index)

    def on_data_changed(self, current_file: dict | None):
        """当前聚焦文件的数据/名称变化后，由 main 调用刷新内容。"""
        if current_file is None:
            self.data = None
            self.current_name = None
        else:
            self.data = current_file["data"]
            self.current_name = current_file["name"]
        self._sync_vars_and_grid()

    def _render_tabs(self, open_files: list, current_index: int):
        """重建页签栏按钮。"""
        for w in self.tab_frame.winfo_children():
            w.destroy()
        self.tab_buttons.clear()

        n = len(open_files)
        for i, f in enumerate(open_files):
            name = f["name"]
            display = "BossTimer" if name == "data" else name

            tab = tk.Frame(self.tab_frame, bg=TAB_INACTIVE_BG, bd=1, relief="raised")
            tab.pack(side="left", padx=(0, 2), pady=2)

            # 左移按钮（第一个页签禁用）
            left_btn = tk.Label(
                tab,
                text="◀",
                bg=TAB_INACTIVE_BG,
                fg="#888888" if i > 0 else "#CCCCCC",
                padx=2,
                pady=3,
                cursor="hand2" if i > 0 else "arrow",
            )
            left_btn.pack(side="left")

            label = tk.Label(
                tab,
                text=display,
                bg=TAB_INACTIVE_BG,
                fg="#333333",
                padx=6,
                pady=3,
                cursor="hand2",
            )
            label.pack(side="left")

            # 右移按钮（最后一个页签禁用）
            right_btn = tk.Label(
                tab,
                text="▶",
                bg=TAB_INACTIVE_BG,
                fg="#888888" if i < n - 1 else "#CCCCCC",
                padx=2,
                pady=3,
                cursor="hand2" if i < n - 1 else "arrow",
            )
            right_btn.pack(side="left")

            close_btn = tk.Label(
                tab,
                text="  ✕  ",
                bg=TAB_INACTIVE_BG,
                fg="#888888",
                padx=2,
                pady=3,
                cursor="hand2",
            )
            close_btn.pack(side="left")

            label.bind("<Button-1>", lambda e, idx=i: self._switch_tab(idx))
            close_btn.bind("<Button-1>", lambda e, idx=i: self._close_tab(idx))
            if i > 0:
                left_btn.bind("<Button-1>", lambda e, idx=i: self._move_tab(idx, -1))
            if i < n - 1:
                right_btn.bind("<Button-1>", lambda e, idx=i: self._move_tab(idx, 1))

            self.tab_buttons[i] = (tab, label, close_btn, left_btn, right_btn)

        self._highlight_tab(current_index)

    def _highlight_tab(self, current_index: int):
        """高亮当前聚焦的页签。"""
        for i, (tab, label, close_btn, left_btn, right_btn) in self.tab_buttons.items():
            if i == current_index:
                tab.config(bg=TAB_ACTIVE_BG)
                label.config(bg=TAB_ACTIVE_BG, fg="#000000")
                close_btn.config(bg=TAB_ACTIVE_BG, fg="#000000")
                left_btn.config(bg=TAB_ACTIVE_BG)
                right_btn.config(bg=TAB_ACTIVE_BG)
            else:
                tab.config(bg=TAB_INACTIVE_BG)
                label.config(bg=TAB_INACTIVE_BG, fg="#333333")
                close_btn.config(bg=TAB_INACTIVE_BG, fg="#888888")
                left_btn.config(bg=TAB_INACTIVE_BG)
                right_btn.config(bg=TAB_INACTIVE_BG)

    def _close_tab(self, index: int):
        if self.on_close_tab is not None:
            self.on_close_tab(index)

    def _switch_tab(self, index: int):
        if self.on_switch_tab is not None:
            self.on_switch_tab(index)

    def _move_tab(self, index: int, direction: int):
        if self.on_move_tab is not None:
            self.on_move_tab(index, direction)

    # ---------- 空状态 ----------

    def _update_empty_state(self):
        """根据是否有聚焦文件，显示/隐藏设置栏、文件栏与格子。"""
        has_data = self.data is not None
        if has_data:
            self.settings_frame.pack(fill="x", padx=10, pady=5)
            self.filebar_frame.pack(fill="x", padx=10, pady=5)
            self.grid_frame.pack(fill="both", expand=True, padx=10, pady=10)
        else:
            self.settings_frame.pack_forget()
            self.filebar_frame.pack_forget()
            self.grid_frame.pack_forget()

    # ---------- 数据访问 ----------

    def _compute_next_id(self) -> int:
        ids = [c["id"] for c in self.data["channels"]]
        return max(ids, default=0) + 1

    def _get_channels(self) -> list[dict]:
        if self.data is None:
            return []
        return self.data["channels"]

    def _save(self):
        if self.data is not None and self.on_change is not None:
            self.on_change(self.data)

    def _sync_vars_and_grid(self):
        """根据当前数据同步 a/b 输入框并重建格子与空状态。"""
        if self.data is None:
            self.lower_var.set("")
            self.upper_var.set("")
        else:
            self.lower_var.set(str(self.data["refresh_lower_minutes"]))
            self.upper_var.set(str(self.data["refresh_upper_minutes"]))
        self._update_empty_state()
        self._refresh_channels()

    def _save_to_file(self):
        """弹窗选择已有文件或新建文件，保存当前聚焦数据到该文件。"""
        if self.data is None:
            messagebox.showinfo("提示", "当前没有打开的文件。")
            return
        if self.on_save_file is None:
            messagebox.showinfo("提示", "未提供文件保存功能。")
            return
        name = FileSaveDialog(self.root, self.on_list_files).result()
        if name is None:
            return
        result = self.on_save_file(name)
        if isinstance(result, str):
            messagebox.showerror("保存失败", result)

    def _load_from_file(self):
        """弹窗选择/输入文件名并新打开一个文件（作为新页签）。"""
        if self.on_load_file is None:
            messagebox.showinfo("提示", "未提供文件读取功能。")
            return
        name = FileSelectDialog(
            self.root, self.on_list_files, self.on_delete_file
        ).result()
        if name is None:
            return
        result = self.on_load_file(name)
        if isinstance(result, str):
            messagebox.showerror("读取失败", result)

    # ---------- 设置与频道操作 ----------

    def _apply_settings(self):
        if self.data is None:
            return
        try:
            lower = float(self.lower_var.get())
            upper = float(self.upper_var.get())
        except ValueError:
            messagebox.showerror("输入错误", "a / b 必须为数字。")
            return

        if not (0 < lower < upper):
            messagebox.showerror("输入错误", "必须满足 0 < a < b。")
            return

        self.data["refresh_lower_minutes"] = lower
        self.data["refresh_upper_minutes"] = upper
        self._save()
        self._refresh_channels()

    def _add_channel(self):
        if self.data is None:
            return
        new_id = self._compute_next_id()
        channel = Channel(
            id=new_id,
            name=f"频道{new_id}",
            base_time=get_server_time().isoformat(),
            source="init",
        ).to_dict()
        self.data["channels"].append(channel)
        self._save()
        self._refresh_channels()

    def _remove_channel(self):
        if self.data is None:
            return
        channels = self._get_channels()
        if not channels:
            messagebox.showinfo("提示", "没有可删除的频道。")
            return
        self.data["channels"] = channels[:-1]
        self._save()
        self._refresh_channels()

    def _reset_all(self):
        """一键重置：二次确认后，将所有频道改为未记录状态。"""
        if self.data is None:
            return
        if not messagebox.askyesno(
            "一键重置",
            "确定要将所有频道重置为「未记录」状态吗？\n此操作不可恢复。",
            parent=self.root,
        ):
            return
        for ch in self._get_channels():
            ch["recorded"] = False
        self._save()
        self._refresh_channels()

    # ---------- 状态刷新 ----------

    def _refresh_channels(self):
        """根据当前数据（重新）创建格子。

        仅在结构变化（增删频道、修改 a/b、编辑状态、切换文件）时调用。
        """
        # 清空现有格子
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.channel_buttons.clear()

        if self.data is None:
            return

        channels = self._get_channels()
        for idx, ch in enumerate(channels):
            cell = tk.Text(
                self.grid_frame,
                bg="#4CAF50",
                fg="#FFFFFF",
                font=("Arial", 11, "bold"),
                width=14,
                height=4,
                relief="raised",
                cursor="hand2",
                highlightthickness=0,
            )
            cell.tag_configure("green", foreground="#29B6F6")
            cell.bind("<Button-1>", lambda e, cid=ch["id"]: self._open_edit_dialog(cid))
            row = idx // GRID_COLUMNS
            col = idx % GRID_COLUMNS
            cell.grid(row=row, column=col, padx=5, pady=5)
            self.channel_buttons[ch["id"]] = cell

        # 创建后立即更新一次显示
        self._update_channel_display()

    def _update_channel_display(self):
        """更新已有格子的文本与颜色（不重建控件，避免闪烁）。"""
        if self.data is None:
            return
        lower = self.data["refresh_lower_minutes"]
        upper = self.data["refresh_upper_minutes"]
        now = get_server_time()

        for ch in self._get_channels():
            cell = self.channel_buttons.get(ch["id"])
            if cell is None:
                continue

            recorded = bool(ch.get("recorded", False))

            # 已记录但超时 2 倍 b 以上：自动降级为未记录（灰色）
            if recorded and is_expired_beyond(ch.get("base_time", ""), now, upper):
                recorded = False

            if not recorded:
                # 未记录数据：灰色，不参与倒计时
                label_text, color = STATUS_DISPLAY[Status.UNRECORDED]
                checked_text = compute_checked_text(
                    ch.get("checked_time", ""), now, lower
                )
                head = f"{ch['name']}\n{label_text}"
                self._set_cell_text(cell, head, checked_text, color, highlight_tail=True)
                continue

            status = compute_status(ch["base_time"], now, lower, upper)
            label_text, color = STATUS_DISPLAY[status]
            countdown = compute_countdown_text(ch["base_time"], now, lower, upper)

            self._set_cell_text(cell, f"{ch['name']}\n{label_text}", countdown, color)

    def _set_cell_text(
        self, cell: tk.Text, head: str, tail: str, bg: str, highlight_tail: bool = False
    ):
        """设置格子内容并居中。

        highlight_tail=True 时，尾部（倒计时）套用蓝色 tag；
        否则尾部与头部一样使用默认前景色（白色）。
        """
        cell.config(state="normal", bg=bg)
        cell.delete("1.0", "end")

        if tail:
            cell.insert("1.0", head + "\n")
            if highlight_tail:
                cell.insert("end", tail, "green")
            else:
                cell.insert("end", tail)
        else:
            cell.insert("1.0", head)

        # 整块居中
        cell.tag_configure("center", justify="center")
        cell.tag_add("center", "1.0", "end")

        cell.config(state="disabled")

    def _tick(self):
        """每秒更新时钟与格子显示（仅改属性，不重建）。"""
        self.clock_label.config(
            text=get_server_time().strftime("%Y-%m-%d %H:%M:%S")
        )
        self._update_channel_display()
        self.root.after(1000, self._tick)

    # ---------- 编辑弹窗 ----------

    def _open_edit_dialog(self, channel_id: int):
        channel = next(
            (c for c in self._get_channels() if c["id"] == channel_id), None
        )
        if channel is None:
            return
        ChannelEditDialog(self.root, channel, self._on_edit_apply)

    def _on_edit_apply(self, channel: dict):
        """编辑弹窗提交后的回调，更新对应频道并刷新。"""
        for i, ch in enumerate(self._get_channels()):
            if ch["id"] == channel["id"]:
                self.data["channels"][i] = channel
                break
        self._save()
        self._refresh_channels()


class ChannelEditDialog(tk.Toplevel):
    """频道编辑弹窗：展示频道信息，提供初始化与自定义击杀时间按钮。"""

    def __init__(self, parent, channel: dict, on_apply):
        super().__init__(parent)
        self.channel = channel
        self.on_apply = on_apply

        self.title(f"编辑 {channel['name']}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        tk.Label(
            self,
            text=channel["name"],
            font=("Arial", 14, "bold"),
        ).pack(padx=20, pady=(20, 5))

        base_label = f"基准时间：{channel['base_time']}\n来源：{'击杀' if channel['source'] == 'kill' else '初始化'}"
        tk.Label(self, text=base_label).pack(padx=20, pady=5)

        # 是否已记录数据勾选框 + "记为已查"按钮（同一行）
        recorded_row = tk.Frame(self)
        recorded_row.pack(padx=20, pady=(5, 0))

        self.recorded_var = tk.BooleanVar(value=bool(channel.get("recorded", False)))
        tk.Checkbutton(
            recorded_row,
            text="已记录数据（勾选后按时间进入三态）",
            variable=self.recorded_var,
            command=self._toggle_recorded,
        ).pack(side="left")

        tk.Button(
            recorded_row,
            text="记为已查",
            command=self._mark_checked,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            self,
            text="初始化（重置为待刷新）",
            width=24,
            command=self._do_init,
        ).pack(padx=20, pady=(10, 5))

        tk.Button(
            self,
            text="自定义（输入击杀时间）",
            width=24,
            command=self._do_custom,
        ).pack(padx=20, pady=5)

        tk.Button(
            self,
            text="关闭",
            width=24,
            command=self.destroy,
        ).pack(padx=20, pady=(5, 20))

    def _toggle_recorded(self):
        """勾选/取消勾选时即时同步 recorded 字段。"""
        self.channel["recorded"] = bool(self.recorded_var.get())
        self.on_apply(self.channel)

    def _mark_checked(self):
        """记为已查：记录当前时刻，供未记录频道显示 a 分钟内的正计时。"""
        self.channel["checked_time"] = get_server_time().isoformat()
        self.on_apply(self.channel)

    def _do_init(self):
        self.channel["base_time"] = get_server_time().isoformat()
        self.channel["source"] = "init"
        self.channel["checked_time"] = ""  # 清除"记为已查"，回到默认无时间显示
        self.on_apply(self.channel)
        self.destroy()

    def _do_custom(self):
        KillTimeDialog(self, self.channel, self.on_apply)


class KillTimeDialog(tk.Toplevel):
    """击杀时间输入弹窗：输入基准时间，格式 YYYY-MM-DD HH:MM:SS。"""

    def __init__(self, parent, channel: dict, on_apply):
        super().__init__(parent)
        self.channel = channel
        self.on_apply = on_apply

        self.title("输入击杀时间")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        tk.Label(
            self,
            text="请输入击杀时间（基准时间）：",
        ).pack(padx=20, pady=(20, 5))

        self.entry = tk.Entry(self, width=24)
        self.entry.insert(0, self._default_text())
        self.entry.pack(padx=20, pady=5)

        tk.Label(
            self,
            text="格式：YYYY-MM-DD HH:MM:SS",
            fg="#888888",
        ).pack(padx=20, pady=(0, 10))

        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=20, pady=(0, 10))
        tk.Button(
            btn_frame,
            text="确定",
            width=10,
            command=self._confirm,
            bg="#4CAF50",
            fg="#FFFFFF",
            activebackground="#43A047",
        ).pack(side="left", padx=5)
        tk.Button(
            btn_frame,
            text="取消",
            width=10,
            command=self.destroy,
            bg="#9E9E9E",
            fg="#FFFFFF",
            activebackground="#757575",
        ).pack(side="left", padx=5)

        tk.Button(
            self,
            text="一键记录为10s前",
            width=24,
            command=self._record_10s_ago,
        ).pack(padx=20, pady=(0, 20))

    def _default_text(self) -> str:
        """预填文本：优先使用该频道已记录的基准时间，否则用当前时间。"""
        base_time = self.channel.get("base_time", "")
        if base_time:
            try:
                dt = datetime.fromisoformat(base_time)
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass
        return get_server_time().strftime("%Y-%m-%d %H:%M:%S")

    def _record_10s_ago(self):
        """将击杀时间一键记录为当前时间前 10 秒。"""
        from datetime import timedelta

        dt = get_server_time() - timedelta(seconds=10)
        self.channel["base_time"] = dt.isoformat()
        self.channel["source"] = "kill"
        self.on_apply(self.channel)
        self.destroy()

    def _confirm(self):
        text = self.entry.get().strip()
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("输入错误", "时间格式不正确，应为 YYYY-MM-DD HH:MM:SS。")
            return

        self.channel["base_time"] = dt.isoformat()
        self.channel["source"] = "kill"
        self.on_apply(self.channel)
        self.destroy()


class FileSelectDialog(tk.Toplevel):
    """文件选择弹窗：列出已有数据文件供选择，支持读取与删除。"""

    def __init__(self, parent, on_list_files=None, on_delete_file=None):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("选择要读取的文件")
        self.resizable(False, False)
        self._result = None
        self.on_delete_file = on_delete_file

        # 获取已有文件列表
        files = []
        if on_list_files is not None:
            try:
                files = list(on_list_files())
            except Exception:
                files = []

        self.listbox = None

        if files:
            tk.Label(
                self, text="已有数据文件（点击选择）：", anchor="w"
            ).pack(fill="x", padx=20, pady=(15, 5))

            list_frame = tk.Frame(self)
            list_frame.pack(fill="both", expand=True, padx=20)

            self.listbox = tk.Listbox(list_frame, width=30, height=10)
            self.listbox.pack(side="left", fill="both", expand=True)
            scrollbar = tk.Scrollbar(list_frame, orient="vertical")
            scrollbar.config(command=self.listbox.yview)
            scrollbar.pack(side="right", fill="y")
            self.listbox.config(yscrollcommand=scrollbar.set)

            for f in files:
                self.listbox.insert("end", f)

            self.listbox.bind("<Double-Button-1>", lambda e: self._choose_list())

            btn_frame = tk.Frame(self)
            btn_frame.pack(pady=5)
            tk.Button(
                btn_frame, text="读取选中的文件", width=14, command=self._choose_list
            ).pack(side="left", padx=5)
            tk.Button(
                btn_frame, text="删除选中的文件", width=14, command=self._delete_list
            ).pack(side="left", padx=5)
        else:
            tk.Label(
                self, text="（暂无已有数据文件）", fg="#888888"
            ).pack(padx=20, pady=(15, 5))

        # 底部操作按钮
        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=20, pady=(10, 20))
        tk.Button(btn_frame, text="取消", width=10, command=self.destroy).pack(
            side="left", padx=5
        )

    def _selected_name(self):
        if self.listbox is None:
            return None
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先在列表中选择一个文件。")
            return None
        return self.listbox.get(selection[0]).strip()

    def _choose_list(self):
        name = self._selected_name()
        if name is None:
            return
        self._result = name
        self.destroy()

    def _delete_list(self):
        name = self._selected_name()
        if name is None:
            return
        # 二次确认
        if not messagebox.askyesno(
            "确认删除",
            f"确定要删除文件「{name}.json」吗？\n此操作不可恢复。",
            parent=self,
        ):
            return
        if self.on_delete_file is None:
            messagebox.showinfo("提示", "未提供文件删除功能。")
            return
        result = self.on_delete_file(name)
        if isinstance(result, str):
            messagebox.showerror("删除失败", result)
            return
        # 删除成功：从列表中移除
        selection = self.listbox.curselection()
        if selection:
            self.listbox.delete(selection[0])

    def result(self):
        """阻塞等待并返回用户选择的文件名（不含扩展名），取消返回 None。"""
        self.wait_window()
        return self._result


class FileSaveDialog(tk.Toplevel):
    """另存为弹窗：列出已有数据文件供选择覆盖保存，或新建文件（仅新建时手动输入文件名）。"""

    def __init__(self, parent, on_list_files=None):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("另存为")
        self.resizable(False, False)
        self._result = None

        # 获取已有文件列表
        self.files = []
        if on_list_files is not None:
            try:
                self.files = list(on_list_files())
            except Exception:
                self.files = []

        self.listbox = None

        if self.files:
            tk.Label(
                self, text="已有数据文件（点击选择后覆盖保存）：", anchor="w"
            ).pack(fill="x", padx=20, pady=(15, 5))

            list_frame = tk.Frame(self)
            list_frame.pack(fill="both", expand=True, padx=20)

            self.listbox = tk.Listbox(list_frame, width=30, height=10)
            self.listbox.pack(side="left", fill="both", expand=True)
            scrollbar = tk.Scrollbar(list_frame, orient="vertical")
            scrollbar.config(command=self.listbox.yview)
            scrollbar.pack(side="right", fill="y")
            self.listbox.config(yscrollcommand=scrollbar.set)

            for f in self.files:
                self.listbox.insert("end", f)

            self.listbox.bind("<Double-Button-1>", lambda e: self._choose_list())

            tk.Button(
                self, text="覆盖保存到选中的文件", width=20, command=self._choose_list
            ).pack(pady=5)
        else:
            tk.Label(
                self, text="（暂无已有数据文件）", fg="#888888"
            ).pack(padx=20, pady=(15, 5))

        # 底部操作按钮
        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=20, pady=(10, 20))
        tk.Button(
            btn_frame, text="新建文件", width=10, command=self._new_file
        ).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", width=10, command=self.destroy).pack(
            side="left", padx=5
        )

    def _selected_name(self):
        if self.listbox is None:
            return None
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先在列表中选择一个文件。")
            return None
        return self.listbox.get(selection[0]).strip()

    def _choose_list(self):
        name = self._selected_name()
        if name is None:
            return
        # 覆盖已有文件前二次确认
        if not messagebox.askyesno(
            "确认覆盖",
            f"确定要用当前数据覆盖文件「{name}.json」吗？\n此操作不可恢复。",
            parent=self,
        ):
            return
        self._result = name
        self.destroy()

    def _new_file(self):
        """新建文件：手动输入文件名，重复则提示「已有文件」。"""
        name = simpledialog.askstring(
            "新建文件", "请输入文件名（不含扩展名）：", parent=self
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("输入错误", "文件名不能为空。")
            return
        # 检查是否与已有文件重复
        if name in self.files or (name + ".json") in self.files:
            messagebox.showwarning("已有文件", "已有文件")
            return
        self._result = name
        self.destroy()

    def result(self):
        """阻塞等待并返回用户选择的文件名（不含扩展名），取消返回 None。"""
        self.wait_window()
        return self._result
