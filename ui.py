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
    compute_earliest_time,
    compute_status,
    compute_timeout_time,
    format_base_time,
    get_server_time,
    is_expired_beyond,
)

# 状态 -> (中文标签, 背景色)
STATUS_DISPLAY = {
    Status.UNRECORDED: ("未记录", "#9E9E9E"),
    Status.PENDING: ("待刷新", "#4CAF50"),
    Status.WINDOW: ("刷新期", "#FFC107"),
    Status.EXPIRED: ("已刷新", "#F44336"),
}

# 注释角标颜色（浅蓝，区别于状态色与文字色）
NOTE_BADGE_COLOR = "#29B6F6"

def _center_over_parent(toplevel: tk.Toplevel, parent) -> None:
    """将弹窗居中于其最顶层窗口（主窗口），可跨显示器定位。

    使用 parent.winfo_toplevel() 作为定位参考，确保即使 parent 是
    另一个弹窗（如击杀时间弹窗的父是编辑弹窗），也统一居中于主窗口。

    注意：跨显示器时主窗口坐标可能为负（副显示器在主显示器左侧/上方），
    因此不能对坐标做 max(0, ...) 截断，否则弹窗会被拉回主显示器。
    """
    root = parent.winfo_toplevel()

    def _apply():
        root.update_idletasks()
        w = toplevel.winfo_width()
        h = toplevel.winfo_height()
        px = root.winfo_rootx()
        py = root.winfo_rooty()
        pw = root.winfo_width()
        ph = root.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        toplevel.geometry(f"+{x}+{y}")

    # 先立即定位一次，再延迟一次兜底（确保窗口映射后尺寸准确）
    toplevel.update_idletasks()
    _apply()
    toplevel.after(50, _apply)


def _bind_escape(toplevel: tk.Toplevel) -> None:
    """为弹窗绑定 ESC 键关闭，并确保弹窗获得键盘焦点。

    同时给所有子控件绑定 ESC，确保焦点落在输入框/按钮时也能触发关闭。
    """
    toplevel.bind("<Escape>", lambda e: toplevel.destroy())

    def _bind_recursive(widget):
        for child in widget.winfo_children():
            child.bind("<Escape>", lambda e: toplevel.destroy())
            _bind_recursive(child)

    _bind_recursive(toplevel)

    # 延迟聚焦，确保窗口映射完成后再强制焦点
    def _focus():
        toplevel.focus_force()
        toplevel.lift()

    toplevel.after(50, _focus)


# 每行固定显示的格子列数
GRID_COLUMNS = 6

# 格子固定字号
CELL_FONT_SIZE = 11             # 格子正文
CELL_SMALL_FONT_SIZE = 8        # 格子小字

# 页签激活/非激活时的背景色
TAB_ACTIVE_BG = "#FFFFFF"
TAB_INACTIVE_BG = "#DDDDDD"


class MainWindow:
    """主窗口，支持多文件页签。"""

    def __init__(
        self,
        root: tk.Tk,
        on_change=None,
        on_load_file=None,
        on_new_file=None,
        on_list_files=None,
        on_delete_file=None,
        on_close_tab=None,
        on_switch_tab=None,
        on_move_tab=None,
    ):
        self.root = root
        self.on_change = on_change  # 数据变更回调（用于持久化）
        self.on_load_file = on_load_file  # 新打开文件回调
        self.on_new_file = on_new_file  # 新建文件回调
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
        # 注释角标控件：id -> Canvas（位于格子右上角的红色三角）
        self.note_badges: dict[int, tk.Canvas] = {}

        # 页签栏相关控件
        self.tab_frame = None
        self.tab_buttons = {}  # index -> (标签 Frame, 文本 Label, 关闭 Label)

        # 注释 tooltip 相关
        self._note_tooltip = None  # 当前显示的注释提示框（Toplevel）

        self._build_filebar()
        self._build_clock()
        self._build_tabbar()
        self._build_channelbar()
        self._build_settings()
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
        """构建页签栏（第一行，仅页签），下方带分隔线。"""
        self.tabbar_frame = tk.Frame(self.root)
        self.tabbar_frame.pack(fill="x", padx=10, pady=(5, 0))

        # 动态页签容器
        self.tab_frame = tk.Frame(self.tabbar_frame)
        self.tab_frame.pack(side="top", fill="x")

        # 分隔线
        separator = tk.Frame(self.tabbar_frame, height=1, bg="#CCCCCC")
        separator.pack(side="top", fill="x")

    def _build_filebar(self):
        """构建文件操作栏（顶部工具栏，Windows 98 银灰配色，始终可见）。"""
        self.filebar_frame = tk.Frame(self.root, bg="#C0C0C0")
        self.filebar_frame.pack(fill="x", padx=0, pady=0)

        # 内层容器用于控制内边距
        inner = tk.Frame(self.filebar_frame, bg="#C0C0C0")
        inner.pack(fill="x", padx=6, pady=4)

        # "新建文件"在左，"读取文件"在右（Win98 凸起立体按钮）
        new_btn = tk.Button(
            inner,
            text="新建文件",
            command=self._new_file,
            bg="#C0C0C0",
            fg="#000000",
            activebackground="#C0C0C0",
            activeforeground="#000000",
            relief="raised",
            bd=1,
            padx=8,
            pady=2,
        )
        new_btn.pack(side="left", padx=(0, 4))

        open_btn = tk.Button(
            inner,
            text="读取文件",
            command=self._load_from_file,
            bg="#C0C0C0",
            fg="#000000",
            activebackground="#C0C0C0",
            activeforeground="#000000",
            relief="raised",
            bd=1,
            padx=8,
            pady=2,
        )
        open_btn.pack(side="left", padx=(0, 4))

        help_btn = tk.Button(
            inner,
            text="帮助",
            command=self._show_help,
            bg="#C0C0C0",
            fg="#000000",
            activebackground="#C0C0C0",
            activeforeground="#000000",
            relief="raised",
            bd=1,
            padx=8,
            pady=2,
        )
        help_btn.pack(side="left")

    def _build_channelbar(self):
        """构建频道操作栏（第三行）：增加频道 + 删除频道 + 一键设为未记录。"""
        self.channelbar_frame = tk.Frame(self.root)
        self.channelbar_frame.pack(fill="x", padx=10, pady=(5, 0))

        tk.Button(
            self.channelbar_frame, text="+ 增加频道", command=self._add_channel
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            self.channelbar_frame, text="- 删除频道", command=self._remove_channel
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            self.channelbar_frame,
            text="一键设为未记录",
            command=self._reset_all,
            fg="#F44336",
        ).pack(side="left")

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
        ).pack(side="left")

    def _build_grid(self):
        # 外层容器：用于整体 pack / pack_forget（空状态切换）
        self.grid_container = tk.Frame(self.root)

        # 画布 + 滚动条，实现频道格子区域可滚动
        self.grid_canvas = tk.Canvas(self.grid_container, highlightthickness=0)
        self.grid_scrollbar = tk.Scrollbar(
            self.grid_container, orient="vertical", command=self.grid_canvas.yview
        )
        self.grid_canvas.configure(yscrollcommand=self.grid_scrollbar.set)

        self.grid_scrollbar.pack(side="right", fill="y")
        self.grid_canvas.pack(side="left", fill="both", expand=True)

        # 实际承载格子的 frame，放在 canvas 内部
        self.grid_frame = tk.Frame(self.grid_canvas)
        self._grid_window_id = self.grid_canvas.create_window(
            (0, 0), window=self.grid_frame, anchor="nw"
        )

        # 当 canvas 尺寸变化时，让内部 frame 宽度跟随
        self.grid_canvas.bind(
            "<Configure>",
            lambda e: self.grid_canvas.itemconfigure(
                self._grid_window_id, width=e.width
            ),
        )

        # 支持鼠标滚轮滚动
        self.grid_frame.bind("<Enter>", lambda e: self._bind_wheel())
        self.grid_frame.bind("<Leave>", lambda e: self._unbind_wheel())

    def _bind_wheel(self):
        self.root.bind_all(
            "<MouseWheel>", self._on_mousewheel, add="+"
        )

    def _unbind_wheel(self):
        self.root.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.grid_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _update_scrollregion(self):
        """更新画布滚动区域以包含所有格子。"""
        self.grid_canvas.configure(scrollregion=self.grid_canvas.bbox("all"))

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
        """根据是否有聚焦文件，显示/隐藏频道操作栏、设置栏与格子（文件操作栏始终可见）。"""
        has_data = self.data is not None
        if has_data:
            self.channelbar_frame.pack(fill="x", padx=10, pady=5)
            self.settings_frame.pack(fill="x", padx=10, pady=5)
            self.grid_container.pack(fill="both", expand=True, padx=10, pady=10)
        else:
            self.channelbar_frame.pack_forget()
            self.settings_frame.pack_forget()
            self.grid_container.pack_forget()

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

    def _new_file(self):
        """输入文件名并新建一个空白数据文件（作为新页签）。"""
        if self.on_new_file is None:
            messagebox.showinfo("提示", "未提供新建文件功能。")
            return
        name = simpledialog.askstring(
            "新建文件", "请输入文件名（不含扩展名）：", parent=self.root
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror("输入错误", "文件名不能为空。")
            return
        result = self.on_new_file(name)
        if isinstance(result, str):
            messagebox.showerror("新建失败", result)

    def _show_help(self):
        HelpDialog(self.root)

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
        self.note_badges.clear()

        if self.data is None:
            return

        channels = self._get_channels()
        for idx, ch in enumerate(channels):
            cell = tk.Text(
                self.grid_frame,
                bg="#4CAF50",
                fg="#FFFFFF",
                font=("Arial", CELL_FONT_SIZE, "bold"),
                width=14,
                height=4,
                relief="solid",
                bd=1,
                cursor="hand2",
                highlightthickness=0,
                wrap="none",
            )
            cell.tag_configure("green", foreground="#29B6F6")
            cell.tag_configure("small", font=("Arial", CELL_SMALL_FONT_SIZE))
            cell.bind(
                "<Button-1>",
                lambda e, cid=ch["id"]: self._open_edit_dialog(cid),
            )
            cell.bind(
                "<Button-3>",
                lambda e, cid=ch["id"]: self._open_note_dialog(cid),
            )
            cell.bind(
                "<Enter>",
                lambda e, cid=ch["id"]: self._show_note_tooltip(cid, e),
            )
            cell.bind(
                "<Leave>",
                lambda e: self._hide_note_tooltip(),
            )
            row = idx // GRID_COLUMNS
            col = idx % GRID_COLUMNS
            cell.grid(row=row, column=col, padx=5, pady=5)
            self.channel_buttons[ch["id"]] = cell

            # 注释角标：覆盖右上顶点的红色直角三角形（类似 Excel 注释角标），初始隐藏
            badge_size = 9
            badge = tk.Canvas(
                cell,
                width=badge_size,
                height=badge_size,
                bg=cell.cget("bg"),
                highlightthickness=0,
                bd=0,
            )
            # 直角三角形：直角在右上顶点（右上、左上、右下三点围成）
            badge.create_polygon(
                badge_size, 0,
                0, 0,
                badge_size, badge_size,
                fill=NOTE_BADGE_COLOR,
                outline="",
            )
            badge.place(relx=1.0, rely=0.0, anchor="ne", bordermode="outside")
            self.note_badges[ch["id"]] = badge

        # 创建后立即更新一次显示
        self._update_channel_display()

        # 布局完成后更新滚动区域
        self.root.after(10, self._update_scrollregion)

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

            # 更新注释角标显隐
            badge = self.note_badges.get(ch["id"])
            if badge is not None:
                if ch.get("note", ""):
                    badge.place()
                else:
                    badge.place_forget()

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
                self._set_cell_text(
                    cell,
                    head,
                    checked_text,
                    color,
                    highlight_tail=True,
                    channel_id=ch["id"],
                )
                continue

            status = compute_status(ch["base_time"], now, lower, upper)
            status_label, color = STATUS_DISPLAY[status]
            countdown = compute_countdown_text(ch["base_time"], now, lower, upper)
            last_kill = format_base_time(ch.get("base_time", ""))

            # 有记录：第1行"频道名(状态)"，第2行"上次：{击杀时间}"（小字），第3行倒计时
            head = f"{ch['name']}({status_label})"
            small_head = f"上次：{last_kill}" if last_kill else ""
            extra_tail = ""
            if status == Status.PENDING:
                # 待刷新：额外小字行，显示刷新窗口 "下次:{进入刷新时间}~{超时时间}"
                window_range = compute_earliest_time(
                    ch.get("base_time", ""), lower, upper
                )
                if window_range:
                    extra_tail = f"下次:{window_range}"
            elif status == Status.WINDOW:
                # 刷新期：额外小字行，显示超时时间
                timeout = compute_timeout_time(ch.get("base_time", ""), upper)
                if timeout:
                    extra_tail = f"超时于:{timeout}"

            self._set_cell_text(
                cell,
                head,
                countdown,
                color,
                highlight_tail=False,
                small_tail=extra_tail,
                small_head=small_head,
                channel_id=ch["id"],
            )

    def _set_cell_text(
        self,
        cell: tk.Text,
        head: str,
        tail: str,
        bg: str,
        highlight_tail: bool = False,
        small_tail: str = "",
        small_head: str = "",
        channel_id: int | None = None,
    ):
        """设置格子内容并居中。

        highlight_tail=True 时，尾部（倒计时）套用蓝色 tag；
        small_head 非空时，作为头部之后的小字行（"上次：..."）；
        small_tail 非空时，作为最后一行小字追加（仅待刷新状态使用）。
        """
        cell.config(state="normal", bg=bg)
        cell.delete("1.0", "end")

        # 同步注释角标背景色（角标是 cell 的子控件，不自动跟随 cell 背景）
        if channel_id is not None:
            badge = self.note_badges.get(channel_id)
            if badge is not None:
                badge.config(bg=bg)

        cell.insert("1.0", head)

        if small_head:
            cell.insert("end", "\n" + small_head, "small")

        if tail:
            cell.insert("end", "\n")
            if highlight_tail:
                cell.insert("end", tail, "green")
            else:
                cell.insert("end", tail)

        if small_tail:
            cell.insert("end", "\n" + small_tail, "small")

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

    # ---------- 注释功能 ----------

    def _open_note_dialog(self, channel_id: int):
        channel = next(
            (c for c in self._get_channels() if c["id"] == channel_id), None
        )
        if channel is None:
            return
        self._hide_note_tooltip()
        NoteEditDialog(self.root, channel, self._on_note_apply)

    def _on_note_apply(self, channel: dict):
        """注释弹窗保存后的回调，更新对应频道并刷新。"""
        for i, ch in enumerate(self._get_channels()):
            if ch["id"] == channel["id"]:
                self.data["channels"][i] = channel
                break
        self._save()
        self._refresh_channels()

    def _show_note_tooltip(self, channel_id: int, event):
        """鼠标悬停时，若频道有注释，则在格子侧面弹出注释内容。"""
        channel = next(
            (c for c in self._get_channels() if c["id"] == channel_id), None
        )
        if channel is None:
            return
        note = channel.get("note", "")
        if not note:
            return
        self._hide_note_tooltip()

        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)  # 无边框
        tip.attributes("-topmost", True)
        tk.Label(
            tip,
            text=note,
            bg="#FFFFE0",
            fg="#000000",
            justify="left",
            padx=8,
            pady=6,
            relief="solid",
            bd=1,
        ).pack()
        # 定位到鼠标右侧
        x = event.x_root + 15
        y = event.y_root + 10
        tip.geometry(f"+{x}+{y}")
        self._note_tooltip = tip

    def _hide_note_tooltip(self):
        if self._note_tooltip is not None:
            try:
                self._note_tooltip.destroy()
            except tk.TclError:
                pass
            self._note_tooltip = None


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

        # 是否已记录数据勾选框
        recorded_row = tk.Frame(self)
        recorded_row.pack(padx=20, pady=(5, 0))

        self.recorded_var = tk.BooleanVar(value=bool(channel.get("recorded", False)))
        tk.Checkbutton(
            recorded_row,
            text="记录当前频道",
            variable=self.recorded_var,
            command=self._toggle_recorded,
        ).pack(side="left")

        tk.Button(
            self,
            text="记录当前时间为击杀",
            width=24,
            command=self._do_init,
            bg="#4CAF50",
            fg="#FFFFFF",
            activebackground="#43A047",
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

        _center_over_parent(self, parent)
        _bind_escape(self)

    def _toggle_recorded(self):
        """勾选/取消勾选时即时同步 recorded 字段。"""
        self.channel["recorded"] = bool(self.recorded_var.get())
        self.on_apply(self.channel)

    def _do_init(self):
        self.channel["base_time"] = get_server_time().isoformat()
        self.channel["source"] = "init"
        self.channel["recorded"] = True  # 记录击杀时间即视为已记录，格子进入三态
        self.channel["checked_time"] = ""  # 清除"记为已查"，回到默认无时间显示
        self.recorded_var.set(True)  # 同步勾选框状态
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
        ).pack(padx=20, pady=(0, 5))

        # 增加分钟：输入框 + √ 按钮
        add_frame = tk.Frame(self)
        add_frame.pack(padx=20, pady=(0, 10))

        tk.Label(add_frame, text="增加分钟:").pack(side="left")
        self.minutes_entry = tk.Entry(add_frame, width=6)
        self.minutes_entry.pack(side="left", padx=(5, 5))
        tk.Button(
            add_frame,
            text="√",
            width=2,
            command=self._add_minutes,
            bg="#81C784",
            fg="#FFFFFF",
            activebackground="#66BB6A",
        ).pack(side="left")

        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=20, pady=(0, 20))
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

        _center_over_parent(self, parent)
        _bind_escape(self)

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

    def _add_minutes(self):
        """在当前击杀时间基础上增加指定分钟数，并更新输入框显示。"""
        from datetime import timedelta

        minutes_text = self.minutes_entry.get().strip()
        try:
            minutes = int(minutes_text)
        except ValueError:
            messagebox.showerror("输入错误", "增加分钟数必须为整数。")
            return

        text = self.entry.get().strip()
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            messagebox.showerror("输入错误", "时间格式不正确，应为 YYYY-MM-DD HH:MM:SS。")
            return

        dt = dt + timedelta(minutes=minutes)
        new_text = dt.strftime("%Y-%m-%d %H:%M:%S")
        self.entry.delete(0, "end")
        self.entry.insert(0, new_text)

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

        _center_over_parent(self, parent)
        _bind_escape(self)

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


class HelpDialog(tk.Toplevel):
    """帮助弹窗：展示说明文字（可多行换行），含"我知道了"按钮。"""

    HELP_TEXT = "右键频道可以加注释！\n如果有建议请告诉我。\n请多帮助等级低的小朋友吧！\nMade by 小曰哥 qq 958679431"

    def __init__(self, parent):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("帮助")
        self.resizable(False, False)

        tk.Label(
            self,
            text=self.HELP_TEXT,
            font=("Arial", 10),
            justify="left",
            padx=20,
            pady=16,
        ).pack()

        tk.Button(
            self,
            text="我知道了",
            width=12,
            command=self.destroy,
            bg="#4CAF50",
            fg="#FFFFFF",
            activebackground="#43A047",
        ).pack(padx=20, pady=(0, 20))

        _center_over_parent(self, parent)
        _bind_escape(self)


class NoteEditDialog(tk.Toplevel):
    """注释编辑弹窗：多行文本输入，含"开启蹲守计时""确认""清除"按钮。"""

    def __init__(self, parent, channel: dict, on_apply):
        super().__init__(parent)
        self.channel = channel
        self.on_apply = on_apply

        self.transient(parent)
        self.grab_set()
        self.title(f"编辑注释 - {channel['name']}")
        self.resizable(False, False)

        tk.Label(self, text="注释内容（支持换行）：", anchor="w").pack(
            fill="x", padx=20, pady=(15, 5)
        )

        self.text = tk.Text(self, width=36, height=10, wrap="word")
        self.text.pack(padx=20, pady=5)
        # 预填现有注释
        existing = channel.get("note", "")
        if existing:
            self.text.insert("1.0", existing)

        # 开启蹲守计时：单独一排，与底部确认/清除隔开
        tk.Button(
            self,
            text="开启蹲守计时",
            width=10,
            command=self._mark_checked,
            bg="#FF9800",
            fg="#FFFFFF",
            activebackground="#F57C00",
        ).pack(padx=20, pady=(5, 0))

        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=20, pady=(5, 20))

        tk.Button(
            btn_frame,
            text="确认",
            width=10,
            command=self._confirm,
            bg="#4CAF50",
            fg="#FFFFFF",
            activebackground="#43A047",
        ).pack(side="left", padx=5)

        tk.Button(
            btn_frame,
            text="清除",
            width=10,
            command=self._clear,
            bg="#9E9E9E",
            fg="#FFFFFF",
            activebackground="#757575",
        ).pack(side="left", padx=5)

        _center_over_parent(self, parent)
        _bind_escape(self)

    def _mark_checked(self):
        """开启蹲守计时：记录当前时刻，供未记录频道显示 a 分钟内的正计时。"""
        self.channel["checked_time"] = get_server_time().isoformat()
        self.on_apply(self.channel)

    def _confirm(self):
        """保存输入框中的注释并关闭弹窗。"""
        self.channel["note"] = self.text.get("1.0", "end").strip()
        self.on_apply(self.channel)
        self.destroy()

    def _clear(self):
        """清空注释（字段与输入框），但不关闭弹窗。"""
        self.channel["note"] = ""
        self.on_apply(self.channel)
        self.text.delete("1.0", "end")



