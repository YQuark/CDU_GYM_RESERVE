"""Modern Tkinter GUI for configuring CDU_GYM_RESERVE with privacy safeguards."""

from __future__ import annotations

import datetime as dt
import json
import queue
import sys
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from config import AccountConfig, AppConfig, TaskConfig
from config_utils import parse_date_list, parse_delay
from privacy import mask_identifier, sanitize_payload, sanitize_text, sanitise_and_dump_json
from runner import TaskExecutionRecord, run_tasks

DEFAULT_SHOP_ID = "SHOP_0001"
EXAMPLE_COOKIE = "SESSION=EXAMPLE; TOKEN=EXAMPLE; ID=SHOP_0001"

_THEME_MAP: Dict[str, Dict[str, str]] = {
    "light": {
        "primary": "#2563eb",
        "primary-active": "#1d4ed8",
        "text": "#111827",
        "text-muted": "#6b7280",
        "bg": "#f7fafc",
        "bg-elev": "#ffffff",
        "border": "#e2e8f0",
        "focus": "#93c5fd",
        "danger": "#ef4444",
        "success": "#10b981",
    },
    "dark": {
        "primary": "#60a5fa",
        "primary-active": "#3b82f6",
        "text": "#e2e8f0",
        "text-muted": "#94a3b8",
        "bg": "#0f172a",
        "bg-elev": "#1e293b",
        "border": "#334155",
        "focus": "#60a5fa",
        "danger": "#f87171",
        "success": "#34d399",
    },
}


class QueueWriter:
    """Write stdout/stderr data into a Tk-safe queue."""

    def __init__(self, target: "queue.Queue[tuple[str, object]]") -> None:
        self._target = target

    def write(self, data: str) -> None:  # pragma: no cover - UI side-effect
        if not data:
            return
        self._target.put(("log", data))

    def flush(self) -> None:  # pragma: no cover - compatibility
        pass


class PlaceholderEntry(ttk.Frame):
    """Entry widget with a subtle placeholder label."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        placeholder: str,
        textvariable: Optional[tk.StringVar] = None,
        **entry_kwargs: object,
    ) -> None:
        super().__init__(master)
        self.variable = textvariable or tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.variable, **entry_kwargs)
        self.entry.pack(fill="x")
        self.placeholder = placeholder
        self._placeholder_label = ttk.Label(self, text=placeholder, style="Placeholder.TLabel")
        self._placeholder_label.place(in_=self.entry, relx=0.02, rely=0.5, anchor="w")
        self.variable.trace_add("write", lambda *_: self._toggle_placeholder())
        self.entry.bind("<FocusIn>", lambda _: self._hide_placeholder())
        self.entry.bind("<FocusOut>", lambda _: self._toggle_placeholder())
        self._toggle_placeholder()

    def _toggle_placeholder(self) -> None:
        if self.variable.get().strip():
            self._hide_placeholder()
        else:
            self._placeholder_label.place(in_=self.entry, relx=0.02, rely=0.5, anchor="w")

    def _hide_placeholder(self) -> None:
        self._placeholder_label.place_forget()

    def get(self) -> str:
        return self.variable.get().strip()

    def set(self, value: str) -> None:
        self.variable.set(value)
        self._toggle_placeholder()

    def focus_set(self) -> None:  # pragma: no cover - UI helper
        self.entry.focus_set()


class ValidationMessage(ttk.Label):
    """Small label to surface validation feedback."""

    def __init__(self, master: tk.Widget) -> None:
        super().__init__(master, text="", style="Validation.Info.TLabel", anchor="w")

    def clear(self) -> None:
        self.configure(text="", style="Validation.Info.TLabel")

    def show(self, message: str, *, kind: str = "info") -> None:
        icon_map = {"info": "ℹ", "error": "⚠", "success": "✔"}
        style_map = {
            "info": "Validation.Info.TLabel",
            "error": "Validation.Error.TLabel",
            "success": "Validation.Success.TLabel",
        }
        icon = icon_map.get(kind, "ℹ")
        style = style_map.get(kind, "Validation.Info.TLabel")
        self.configure(text=f"{icon} {message}", style=style)


class TagInput(ttk.Frame):
    """Interactive tag input that renders chips for each keyword."""

    def __init__(
        self,
        master: tk.Widget,
        *,
        placeholder: str,
        on_change: Optional[callable] = None,
    ) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self._tags: List[str] = []
        self._on_change = on_change
        self._entry = PlaceholderEntry(self, placeholder=placeholder)
        self._entry.grid(row=0, column=0, sticky="ew")
        self._entry.entry.bind("<Return>", self._handle_commit)
        self._entry.entry.bind("<FocusOut>", self._handle_commit)
        self._chips = ttk.Frame(self)
        self._chips.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._chips.columnconfigure(0, weight=1)

    def _handle_commit(self, event: tk.Event[tk.Widget]) -> None:  # pragma: no cover
        value = self._entry.get()
        if not value:
            return
        parts = [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
        for part in parts:
            if part not in self._tags:
                self._tags.append(part)
        self._entry.set("")
        self._render_tags()
        if self._on_change:
            self._on_change()

    def _render_tags(self) -> None:
        for child in list(self._chips.winfo_children()):
            child.destroy()
        if not self._tags:
            hint = ttk.Label(self._chips, text="示例：瑜伽、力量", style="Hint.TLabel")
            hint.grid(row=0, column=0, sticky="w")
            return
        for idx, tag in enumerate(self._tags):
            chip = ttk.Frame(self._chips, style="Tag.TFrame")
            chip.grid(row=idx // 3, column=idx % 3, padx=(0, 8), pady=(0, 8), sticky="w")
            ttk.Label(chip, text=tag, style="Tag.TLabel").pack(side="left", padx=(8, 4))
            remove_btn = ttk.Button(
                chip,
                text="✕",
                width=2,
                command=lambda value=tag: self.remove(value),
            )
            remove_btn.pack(side="right", padx=(0, 6))

    def remove(self, value: str) -> None:
        if value in self._tags:
            self._tags.remove(value)
            self._render_tags()
            if self._on_change:
                self._on_change()

    def get_tags(self) -> List[str]:
        return list(self._tags)

    def set_tags(self, tags: Iterable[str]) -> None:
        self._tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        self._render_tags()
        if self._on_change:
            self._on_change()

    def clear(self) -> None:
        self._tags.clear()
        self._render_tags()
        if self._on_change:
            self._on_change()


class DateRangePicker(ttk.Frame):
    """Simple date range picker that supports multiple segments."""

    def __init__(self, master: tk.Widget, *, on_change: Optional[callable] = None) -> None:
        super().__init__(master)
        self.columnconfigure(0, weight=1)
        self._segments: List[str] = []
        self._on_change = on_change
        actions = ttk.Frame(self)
        actions.grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="新增日期", command=self._open_dialog).pack(side="left")
        ttk.Label(
            actions,
            text="支持单日或区间，例如 2025-05-01~2025-05-03",
            style="Hint.TLabel",
        ).pack(side="left", padx=(12, 0))
        self._chips = ttk.Frame(self)
        self._chips.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self._chips.columnconfigure(0, weight=1)

    def _open_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("选择日期")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.geometry("320x200")

        start_var = tk.StringVar()
        end_var = tk.StringVar()

        ttk.Label(dialog, text="开始日期 (YYYY-MM-DD)").pack(anchor="w", padx=16, pady=(16, 4))
        start_entry = ttk.Entry(dialog, textvariable=start_var)
        start_entry.pack(fill="x", padx=16)
        start_entry.focus_set()

        ttk.Label(dialog, text="结束日期 (可选)").pack(anchor="w", padx=16, pady=(12, 4))
        end_entry = ttk.Entry(dialog, textvariable=end_var)
        end_entry.pack(fill="x", padx=16)

        def commit() -> None:
            start = start_var.get().strip()
            end = end_var.get().strip()
            if not start:
                messagebox.showerror("日期无效", "请填写开始日期", parent=dialog)
                return
            if not self._validate_date(start):
                messagebox.showerror("日期无效", "日期格式需为 YYYY-MM-DD", parent=dialog)
                return
            token = start
            if end:
                if not self._validate_date(end):
                    messagebox.showerror("日期无效", "结束日期格式需为 YYYY-MM-DD", parent=dialog)
                    return
                token = f"{start}~{end}"
            if token not in self._segments:
                self._segments.append(token)
                self._render_segments()
                if self._on_change:
                    self._on_change()
            dialog.destroy()

        ttk.Button(dialog, text="添加", command=commit, style="Primary.TButton").pack(
            side="left", padx=(16, 8), pady=24
        )
        ttk.Button(dialog, text="取消", command=dialog.destroy).pack(
            side="right", padx=(8, 16), pady=24
        )

    @staticmethod
    def _validate_date(value: str) -> bool:
        if len(value) != 10:
            return False
        try:
            dt.datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return False
        return True

    def _render_segments(self) -> None:
        for child in list(self._chips.winfo_children()):
            child.destroy()
        if not self._segments:
            ttk.Label(self._chips, text="尚未选择日期", style="Hint.TLabel").grid(
                row=0, column=0, sticky="w"
            )
            return
        for idx, token in enumerate(self._segments):
            chip = ttk.Frame(self._chips, style="Tag.TFrame")
            chip.grid(row=idx // 2, column=idx % 2, padx=(0, 8), pady=(0, 8), sticky="w")
            ttk.Label(chip, text=token, style="Tag.TLabel").pack(side="left", padx=(8, 4))
            ttk.Button(
                chip,
                text="✕",
                width=2,
                command=lambda value=token: self.remove(value),
            ).pack(side="right", padx=(0, 6))

    def remove(self, token: str) -> None:
        if token in self._segments:
            self._segments.remove(token)
            self._render_segments()
            if self._on_change:
                self._on_change()

    def get_tokens(self) -> List[str]:
        return list(self._segments)

    def set_tokens(self, values: Iterable[str]) -> None:
        self._segments = [str(v).strip() for v in values if str(v).strip()]
        self._render_segments()
        if self._on_change:
            self._on_change()


class VisualApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("预约任务控制台（示例数据）")
        self.geometry("1200x760")
        self.minsize(1024, 680)

        self.log_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._is_running = False
        self._current_theme = "light"
        self._log_records: List[Dict[str, object]] = []
        self._history: List[Dict[str, object]] = []
        self._current_run_started: Optional[dt.datetime] = None
        self._side_visible = False

        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:  # pragma: no cover - fallback
            pass

        self._build_styles()
        self._build_widgets()
        self._apply_theme(self._current_theme)

        self.after(150, self._poll_log_queue)

    # ------------------------------------------------------------------
    # Style & layout helpers
    # ------------------------------------------------------------------
    def _build_styles(self) -> None:
        self.option_add("*Font", "Segoe UI 11")
        self.option_add("*TCombobox*Listbox.font", "Segoe UI 11")
        self.style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        self.style.configure("Subtitle.TLabel", font=("Segoe UI", 12))
        self.style.configure("CardTitle.TLabel", font=("Segoe UI", 14, "bold"))
        self.style.configure("CardSubtitle.TLabel", font=("Segoe UI", 11))
        self.style.configure("FormLabel.TLabel", font=("Segoe UI", 11))
        self.style.configure("Hint.TLabel", font=("Segoe UI", 10))
        self.style.configure("Placeholder.TLabel", font=("Segoe UI", 10))
        self.style.configure("Validation.Info.TLabel", font=("Segoe UI", 10))
        self.style.configure("Validation.Error.TLabel", font=("Segoe UI", 10, "bold"))
        self.style.configure("Validation.Success.TLabel", font=("Segoe UI", 10, "bold"))
        self.style.configure(
            "Primary.TButton",
            padding=(16, 10),
            font=("Segoe UI", 11, "bold"),
        )
        self.style.configure("Tag.TFrame", padding=(4, 2), relief="flat")
        self.style.configure("Tag.TLabel", font=("Segoe UI", 10))
        self.style.configure("Card.TFrame", padding=(18, 18))

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="示例预约自动化面板", style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")

        buttons = ttk.Frame(header)
        buttons.grid(row=0, column=1, sticky="e")
        self.example_button = ttk.Button(buttons, text="填充示例值", command=self._fill_examples)
        self.example_button.pack(side="right", padx=(12, 0))
        self.side_toggle_button = ttk.Button(
            buttons, text="展开预览面板", command=self._toggle_side_panel
        )
        self.side_toggle_button.pack(side="right", padx=(12, 0))
        self.theme_toggle = ttk.Button(buttons, text="切换至深色模式", command=self._toggle_theme)
        self.theme_toggle.pack(side="right")

        subtitle = ttk.Label(
            header,
            text="请使用示例或脱敏数据进行演示。真实凭证需在后端安全存储。",
            style="Subtitle.TLabel",
            wraplength=640,
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

        left_container = ttk.Frame(outer)
        left_container.grid(row=1, column=0, sticky="nsew")
        left_container.rowconfigure(0, weight=1)
        left_container.columnconfigure(0, weight=1)

        canvas = tk.Canvas(left_container, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        self.form_frame = ttk.Frame(canvas)
        self.form_frame.columnconfigure(0, weight=1)
        canvas.create_window((0, 0), window=self.form_frame, anchor="nw")

        def _on_configure(event: tk.Event[tk.Widget]) -> None:  # pragma: no cover - UI plumbing
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(1, width=event.width)

        self.form_frame.bind("<Configure>", _on_configure)

        self._build_connection_section(self.form_frame)
        self._build_task_section(self.form_frame)
        self._build_execution_section(self.form_frame)
        self._build_privacy_section(self.form_frame)

        self.side_panel = ttk.Frame(outer, style="Card.TFrame", padding=(18, 18))
        self.side_panel.grid(row=1, column=1, sticky="nsew", padx=(18, 0))
        self.side_panel.columnconfigure(0, weight=1)
        self.side_panel.rowconfigure(1, weight=1)
        self.side_panel.grid_remove()
        self._build_side_panel(self.side_panel)

    def _create_card(
        self, parent: ttk.Frame, *, title: str, description: str, row: int
    ) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame")
        card.grid(row=row, column=0, sticky="ew", pady=(0, 18))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(card, text=description, style="CardSubtitle.TLabel", wraplength=640).grid(
            row=1, column=0, sticky="w", pady=(4, 12)
        )
        return card

    def _build_connection_section(self, parent: ttk.Frame) -> None:
        card = self._create_card(
            parent,
            title="连接配置",
            description="账号昵称与 shop_id 会被自动脱敏。Cookie 仅用于本地运行，不会写入日志。",
            row=0,
        )
        card.columnconfigure(1, weight=1)

        self.account_name_var = tk.StringVar()
        ttk.Label(card, text="账号昵称", style="FormLabel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 12)
        )
        self.account_entry = PlaceholderEntry(
            card,
            placeholder="示例：demo_account",
            textvariable=self.account_name_var,
        )
        self.account_entry.grid(row=2, column=1, sticky="ew")
        self.account_validation = ValidationMessage(card)
        self.account_validation.grid(row=3, column=1, sticky="ew", pady=(4, 0))

        self.shop_id_var = tk.StringVar(value=DEFAULT_SHOP_ID)
        ttk.Label(card, text="shop_id", style="FormLabel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(12, 12)
        )
        self.shop_entry = PlaceholderEntry(
            card,
            placeholder="示例：SHOP_0001",
            textvariable=self.shop_id_var,
        )
        self.shop_entry.grid(row=4, column=1, sticky="ew")
        self.shop_validation = ValidationMessage(card)
        self.shop_validation.grid(row=5, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(card, text="Cookie", style="FormLabel.TLabel").grid(
            row=6, column=0, sticky="nw", pady=(12, 8)
        )
        self.cookie_text = scrolledtext.ScrolledText(card, height=6, wrap=tk.WORD)
        self.cookie_text.grid(row=6, column=1, sticky="ew")
        self.cookie_text.insert("1.0", "")
        self.cookie_validation = ValidationMessage(card)
        self.cookie_validation.grid(row=7, column=1, sticky="ew", pady=(4, 0))
        self.cookie_text.bind("<KeyRelease>", lambda _event: self._refresh_preview())

    def _build_task_section(self, parent: ttk.Frame) -> None:
        card = self._create_card(
            parent,
            title="任务规则",
            description="关键字段会实时校验，并展示为标签形式。",
            row=1,
        )
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="优先会员卡关键字", style="FormLabel.TLabel").grid(
            row=2, column=0, sticky="nw"
        )
        self.preferred_tags = TagInput(
            card,
            placeholder="输入关键字后回车，例如：尊享卡",
            on_change=self._refresh_preview,
        )
        self.preferred_tags.grid(row=2, column=1, sticky="ew")

        ttk.Label(card, text="课程标题关键字", style="FormLabel.TLabel").grid(
            row=3, column=0, sticky="nw", pady=(12, 0)
        )
        self.title_tags = TagInput(
            card,
            placeholder="示例：瑜伽、普拉提",
            on_change=self._refresh_preview,
        )
        self.title_tags.grid(row=3, column=1, sticky="ew", pady=(12, 0))
        self.title_validation = ValidationMessage(card)
        self.title_validation.grid(row=4, column=1, sticky="ew", pady=(4, 0))

        ttk.Label(card, text="时段关键字", style="FormLabel.TLabel").grid(
            row=5, column=0, sticky="nw", pady=(12, 0)
        )
        self.time_tags = TagInput(
            card,
            placeholder="示例：18:00-19:00",
            on_change=self._refresh_preview,
        )
        self.time_tags.grid(row=5, column=1, sticky="ew", pady=(12, 0))

        ttk.Label(card, text="日期选择", style="FormLabel.TLabel").grid(
            row=6, column=0, sticky="nw", pady=(16, 0)
        )
        self.date_picker = DateRangePicker(card, on_change=self._refresh_preview)
        self.date_picker.grid(row=6, column=1, sticky="ew", pady=(16, 0))

        options = ttk.Frame(card)
        options.grid(row=7, column=0, columnspan=2, sticky="w", pady=(16, 0))
        self.strict_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="严格匹配关键字", variable=self.strict_var).pack(
            side="left"
        )
        self.allow_fallback_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options, text="匹配失败允许候选课程", variable=self.allow_fallback_var
        ).pack(side="left", padx=(24, 0))

    def _build_execution_section(self, parent: ttk.Frame) -> None:
        card = self._create_card(
            parent,
            title="执行参数",
            description="调整重试、并发与超时策略。滑块与步进器会实时更新概览。",
            row=2,
        )
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="最大重试次数", style="FormLabel.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.max_attempts_var = tk.IntVar(value=1)
        self.max_attempts_spin = ttk.Spinbox(
            card,
            from_=1,
            to=10,
            textvariable=self.max_attempts_var,
            width=6,
            command=self._refresh_preview,
        )
        self.max_attempts_spin.grid(row=2, column=1, sticky="w")
        self.max_attempts_spin.bind("<FocusOut>", lambda _event: self._refresh_preview())

        delay_frame = ttk.Frame(card)
        delay_frame.grid(row=3, column=0, columnspan=2, sticky="w", pady=(16, 0))
        ttk.Label(delay_frame, text="重试间隔", style="FormLabel.TLabel").pack(
            side="left", padx=(0, 12)
        )
        self.delay_low_var = tk.IntVar(value=120)
        self.delay_high_var = tk.IntVar(value=300)
        ttk.Spinbox(
            delay_frame,
            from_=10,
            to=5000,
            increment=10,
            textvariable=self.delay_low_var,
            width=6,
            command=self._update_delay_display,
        ).pack(side="left")
        ttk.Label(delay_frame, text="ms", style="Hint.TLabel").pack(side="left", padx=(4, 12))
        ttk.Spinbox(
            delay_frame,
            from_=10,
            to=8000,
            increment=10,
            textvariable=self.delay_high_var,
            width=6,
            command=self._update_delay_display,
        ).pack(side="left")
        ttk.Label(delay_frame, text="ms", style="Hint.TLabel").pack(side="left", padx=(4, 12))
        self.delay_display = ttk.Label(delay_frame, text="120 ms / 300 ms", style="Hint.TLabel")
        self.delay_display.pack(side="left")

        ttk.Label(card, text="并发数", style="FormLabel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(16, 0)
        )
        self.concurrency_var = tk.IntVar(value=1)
        self.concurrency_scale = ttk.Scale(
            card,
            from_=1,
            to=5,
            orient="horizontal",
            command=self._on_concurrency_changed,
        )
        self.concurrency_scale.set(1)
        self.concurrency_scale.grid(row=4, column=1, sticky="ew", pady=(16, 0))
        self.concurrency_label = ttk.Label(
            card, text="并发：1", style="Hint.TLabel"
        )
        self.concurrency_label.grid(row=5, column=1, sticky="w", pady=(4, 0))

        ttk.Label(card, text="全局超时 (ms，可选)", style="FormLabel.TLabel").grid(
            row=6, column=0, sticky="w", pady=(16, 0)
        )
        self.global_timeout_var = tk.StringVar()
        self.global_timeout_entry = PlaceholderEntry(
            card,
            placeholder="示例：60000",
            textvariable=self.global_timeout_var,
        )
        self.global_timeout_entry.grid(row=6, column=1, sticky="ew")

    def _build_privacy_section(self, parent: ttk.Frame) -> None:
        card = self._create_card(
            parent,
            title="隐私与操作",
            description="导出日志时会自动脱敏，敏感信息显示需二次确认。",
            row=3,
        )
        card.columnconfigure(0, weight=1)

        self.log_json_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(card, text="输出 JSON 日志", variable=self.log_json_var).grid(
            row=2, column=0, sticky="w"
        )
        self.show_sensitive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            card,
            text="显示敏感信息（需确认）",
            variable=self.show_sensitive_var,
            command=self._toggle_sensitive_display,
        ).grid(row=3, column=0, sticky="w", pady=(12, 0))

        buttons = ttk.Frame(card)
        buttons.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        buttons.columnconfigure(0, weight=1)
        self.run_button = ttk.Button(
            buttons,
            text="开始执行",
            style="Primary.TButton",
            command=self._on_run_clicked,
        )
        self.run_button.grid(row=0, column=0, sticky="ew")
        self.export_button = ttk.Button(
            buttons,
            text="导出日志（脱敏）",
            command=self._export_desensitised_log,
        )
        self.export_button.grid(row=0, column=1, sticky="ew", padx=(12, 0))

        self.busy_indicator = ttk.Progressbar(card, mode="indeterminate")
        self.busy_indicator.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        self.busy_indicator.grid_remove()

        self.status_chip = ttk.Label(card, text="准备就绪", style="CardSubtitle.TLabel")
        self.status_chip.grid(row=6, column=0, sticky="w", pady=(12, 0))

    def _build_side_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="预览 / 日志 / 历史", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.side_notebook = ttk.Notebook(parent)
        self.side_notebook.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        preview_tab = ttk.Frame(self.side_notebook)
        preview_tab.columnconfigure(0, weight=1)
        self.preview_text = scrolledtext.ScrolledText(preview_tab, height=12, wrap=tk.WORD)
        self.preview_text.grid(row=0, column=0, sticky="nsew")
        self.preview_text.configure(state="disabled")
        self.side_notebook.add(preview_tab, text="预览")

        log_tab = ttk.Frame(self.side_notebook)
        log_tab.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(log_tab)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="级别筛选", style="FormLabel.TLabel").pack(side="left")
        self.log_filter_var = tk.StringVar(value="全部")
        self.log_filter = ttk.Combobox(
            toolbar,
            textvariable=self.log_filter_var,
            values=["全部", "INFO", "WARN", "ERROR"],
            state="readonly",
            width=8,
        )
        self.log_filter.pack(side="left", padx=(12, 0))
        self.log_filter.bind("<<ComboboxSelected>>", lambda _event: self._refresh_log_display())
        self.clear_log_button = ttk.Button(
            toolbar, text="清除日志", command=self._clear_log
        )
        self.clear_log_button.pack(side="right")

        self.log_text = scrolledtext.ScrolledText(log_tab, height=14, wrap=tk.WORD)
        self.log_text.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.log_text.configure(state="disabled")
        self.side_notebook.add(log_tab, text="日志")

        history_tab = ttk.Frame(self.side_notebook)
        history_tab.columnconfigure(0, weight=1)
        history_tab.rowconfigure(0, weight=1)
        columns = ("started", "duration", "result")
        self.history_tree = ttk.Treeview(
            history_tab,
            columns=columns,
            show="headings",
            height=6,
        )
        self.history_tree.heading("started", text="开始时间")
        self.history_tree.heading("duration", text="耗时")
        self.history_tree.heading("result", text="结果")
        self.history_tree.column("started", width=140)
        self.history_tree.column("duration", width=80, anchor="center")
        self.history_tree.column("result", width=80, anchor="center")
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        self.side_notebook.add(history_tab, text="运行历史")

        help_tab = ttk.Frame(self.side_notebook)
        help_tab.columnconfigure(0, weight=1)
        help_message = (
            "• 示例数据模式确保不会泄露真实信息。\n"
            "• 导出日志将调用脱敏器过滤 URL、cookie、shop_id 等字段。\n"
            "• 若需线上部署，请将真实凭证保存在后端的环境变量或密钥服务中。"
        )
        ttk.Label(help_tab, text=help_message, style="Subtitle.TLabel", wraplength=320).grid(
            row=0, column=0, sticky="nw"
        )
        self.side_notebook.add(help_tab, text="操作说明")

    # ------------------------------------------------------------------
    # Interactivity helpers
    # ------------------------------------------------------------------
    def _toggle_side_panel(self) -> None:
        self._side_visible = not self._side_visible
        if self._side_visible:
            self.side_panel.grid()
            self.side_toggle_button.configure(text="收起预览面板")
        else:
            self.side_panel.grid_remove()
            self.side_toggle_button.configure(text="展开预览面板")

    def _toggle_theme(self) -> None:
        new_theme = "dark" if self._current_theme == "light" else "light"
        self._apply_theme(new_theme)
        self.status_chip.configure(text="已切换主题" if new_theme == "dark" else "准备就绪")

    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        palette = _THEME_MAP.get(theme, _THEME_MAP["light"])

        self.configure(bg=palette["bg"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("Title.TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure(
            "Subtitle.TLabel", background=palette["bg"], foreground=palette["text-muted"]
        )
        self.style.configure(
            "CardTitle.TLabel", background=palette["bg"], foreground=palette["text"]
        )
        self.style.configure(
            "CardSubtitle.TLabel", background=palette["bg"], foreground=palette["text-muted"]
        )
        self.style.configure(
            "FormLabel.TLabel", background=palette["bg"], foreground=palette["text"]
        )
        self.style.configure("Hint.TLabel", background=palette["bg"], foreground=palette["text-muted"])
        self.style.configure(
            "Placeholder.TLabel", background=palette["bg"], foreground=palette["text-muted"]
        )
        self.style.configure(
            "Validation.Info.TLabel",
            background=palette["bg"],
            foreground=palette["text-muted"],
        )
        self.style.configure(
            "Validation.Error.TLabel",
            background=palette["bg"],
            foreground=palette["danger"],
        )
        self.style.configure(
            "Validation.Success.TLabel",
            background=palette["bg"],
            foreground=palette["success"],
        )
        self.style.configure(
            "Card.TFrame",
            background=palette["bg-elev"],
            relief="flat",
            borderwidth=0,
        )
        self.style.configure(
            "Tag.TFrame",
            background=palette["bg-elev"],
            relief="solid",
            bordercolor=palette["border"],
        )
        self.style.configure(
            "Tag.TLabel", background=palette["bg-elev"], foreground=palette["text"]
        )
        self.style.configure(
            "Primary.TButton",
            background=palette["primary"],
            foreground="#ffffff",
            focusthickness=3,
            focuscolor=palette["focus"],
            bordercolor=palette["primary"],
        )
        self.style.map(
            "Primary.TButton",
            background=[
                ("pressed", palette["primary-active"]),
                ("active", palette["primary-active"]),
                ("!disabled", palette["primary"]),
            ],
            foreground=[("disabled", palette["text-muted"]), ("!disabled", "#ffffff")],
        )
        self.style.configure(
            "TButton",
            background=palette["bg-elev"],
            foreground=palette["text"],
            bordercolor=palette["border"],
        )
        self.style.map(
            "TButton",
            background=[("pressed", palette["border"]), ("active", palette["focus"])],
            foreground=[("disabled", palette["text-muted"]), ("!disabled", palette["text"])],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=palette["primary"],
            troughcolor=palette["bg-elev"],
            bordercolor=palette["border"],
        )
        self.theme_toggle.configure(
            text="切换至浅色模式" if theme == "dark" else "切换至深色模式"
        )

        for widget in (self.preview_text, self.log_text):
            widget.configure(
                background=palette["bg-elev"],
                foreground=palette["text"],
                insertbackground=palette["primary"],
                highlightthickness=1,
                highlightbackground=palette["border"],
                highlightcolor=palette["focus"],
            )

    def _update_delay_display(self) -> None:
        low = max(1, int(self.delay_low_var.get() or 1))
        high = max(low, int(self.delay_high_var.get() or low))
        self.delay_low_var.set(low)
        self.delay_high_var.set(high)
        self.delay_display.configure(text=f"{low} ms / {high} ms")
        self._refresh_preview()

    def _on_concurrency_changed(self, value: str) -> None:  # pragma: no cover - UI side-effect
        try:
            current = int(float(value))
        except ValueError:
            current = 1
        current = max(1, min(5, current))
        self.concurrency_var.set(current)
        self.concurrency_label.configure(text=f"并发：{current}")
        self._refresh_preview()

    def _toggle_sensitive_display(self) -> None:
        if self.show_sensitive_var.get():
            confirmed = messagebox.askyesno(
                "显示敏感信息",
                "确定要显示敏感信息吗？该操作会在日志中记录。",
                parent=self,
            )
            if not confirmed:
                self.show_sensitive_var.set(False)
                return
            self._append_log("[提示] 已启用敏感信息显示。\n")
        else:
            self._append_log("[提示] 已恢复脱敏显示。\n")
        self._refresh_log_display()

    def _fill_examples(self) -> None:
        self.account_name_var.set("demo_account")
        self.shop_id_var.set("SHOP_0001")
        self.cookie_text.delete("1.0", tk.END)
        self.cookie_text.insert("1.0", EXAMPLE_COOKIE)
        self.preferred_tags.set_tags(["尊享卡"])
        self.title_tags.set_tags(["瑜伽", "普拉提"])
        self.time_tags.set_tags(["18:00-19:00", "20:00-21:00"])
        self.date_picker.set_tokens(["2025-05-01~2025-05-03"])
        self.max_attempts_var.set(2)
        self.delay_low_var.set(120)
        self.delay_high_var.set(240)
        self.concurrency_scale.set(1)
        self.global_timeout_var.set("60000")
        self.log_json_var.set(True)
        self._update_delay_display()
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        payload = self._collect_preview_payload()
        preview = sanitise_and_dump_json(payload)
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", preview)
        self.preview_text.configure(state="disabled")
        self._validate_form()

    def _collect_preview_payload(self) -> Dict[str, object]:
        shop_id = self.shop_id_var.get().strip() or DEFAULT_SHOP_ID
        masked_shop = mask_identifier(shop_id, placeholder="SHOP")
        account_name = self.account_name_var.get().strip() or "account"
        payload = {
            "shop_id": masked_shop,
            "account": mask_identifier(account_name, placeholder="ACCOUNT"),
            "preferred_cards": self.preferred_tags.get_tags(),
            "title_keywords": self.title_tags.get_tags(),
            "time_keywords": self.time_tags.get_tags(),
            "dates": self.date_picker.get_tokens(),
            "strict_match": bool(self.strict_var.get()),
            "allow_fallback": bool(self.allow_fallback_var.get()),
            "max_attempts": int(self.max_attempts_var.get() or 1),
            "delay_ms": [int(self.delay_low_var.get() or 120), int(self.delay_high_var.get() or 300)],
            "concurrency": int(self.concurrency_var.get() or 1),
            "global_timeout_ms": self.global_timeout_var.get().strip() or None,
            "log_json": bool(self.log_json_var.get()),
        }
        return sanitize_payload(payload)

    def _validate_form(self) -> None:
        self.account_validation.clear()
        self.shop_validation.clear()
        self.cookie_validation.clear()
        self.title_validation.clear()

        if not self.account_name_var.get().strip():
            self.account_validation.show("未填写昵称，将使用示例账户。", kind="info")
        else:
            self.account_validation.show("昵称已就绪。", kind="success")

        shop_raw = self.shop_id_var.get().strip()
        if not shop_raw:
            self.shop_validation.show("未填写，将使用 SHOP_0001。", kind="info")
        elif "http" in shop_raw.lower():
            self.shop_validation.show("请填写 ID，而不是 URL。", kind="error")
        else:
            self.shop_validation.show("shop_id 格式有效。", kind="success")

        if not self.cookie_text.get("1.0", tk.END).strip():
            self.cookie_validation.show("Cookie 不能为空。", kind="error")
        else:
            self.cookie_validation.show("Cookie 已填写（仅本地使用）。", kind="success")

        if not self.title_tags.get_tags() and not self.time_tags.get_tags():
            self.title_validation.show("请至少配置课程标题或时段关键字。", kind="error")
        else:
            self.title_validation.show("关键字配置齐全。", kind="success")

    # ------------------------------------------------------------------
    # Logging & history helpers
    # ------------------------------------------------------------------
    def _append_log(self, text: str) -> None:
        if not text:
            return
        lines = text.splitlines(True)
        for raw_line in lines:
            level = self._detect_level(raw_line)
            record = {
                "level": level,
                "raw": raw_line,
                "sanitized": sanitize_text(raw_line),
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
            }
            self._log_records.append(record)
        self._refresh_log_display()

    @staticmethod
    def _detect_level(line: str) -> str:
        upper = line.upper()
        if "[ERROR" in upper or "ERROR" in upper:
            return "ERROR"
        if "[WARN" in upper or "WARNING" in upper:
            return "WARN"
        return "INFO"

    def _refresh_log_display(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        target_level = self.log_filter_var.get()
        show_sensitive = bool(self.show_sensitive_var.get())
        for record in self._log_records:
            if target_level != "全部" and record["level"] != target_level:
                continue
            line = record["raw"] if show_sensitive else record["sanitized"]
            self.log_text.insert(tk.END, line)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        if not self._log_records:
            return
        confirm = messagebox.askyesno(
            "清除日志",
            "确认要清除日志吗？该操作会删除已脱敏的记录。",
            parent=self,
        )
        if not confirm:
            return
        self._log_records.clear()
        self._refresh_log_display()

    def _export_desensitised_log(self) -> None:
        if not self._log_records:
            messagebox.showinfo("导出日志", "暂无日志可导出。", parent=self)
            return
        file_path = filedialog.asksaveasfilename(
            parent=self,
            title="导出脱敏日志",
            defaultextension=".json",
            filetypes=(("JSON", "*.json"), ("所有文件", "*.*")),
        )
        if not file_path:
            return
        payload = {
            "exported_at": dt.datetime.now().isoformat(),
            "records": [
                {
                    "ts": record["ts"],
                    "level": record["level"],
                    "message": record["sanitized"],
                }
                for record in self._log_records
            ],
        }
        Path(file_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        messagebox.showinfo("导出完成", "日志已脱敏并导出。", parent=self)

    def _record_history(self, payload: Dict[str, object]) -> None:
        self._history.append(payload)
        started = payload.get("started")
        duration = payload.get("duration")
        result = payload.get("result")
        self.history_tree.insert(
            "",
            tk.END,
            values=(started or "--", duration or "--", result or "--"),
        )

    def _show_busy(self) -> None:
        self.busy_indicator.grid()
        self.busy_indicator.start(8)

    def _hide_busy(self) -> None:
        self.busy_indicator.stop()
        self.busy_indicator.grid_remove()

    def _poll_log_queue(self) -> None:
        updated = False
        while True:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break
            updated = True
            if kind == "log":
                self._append_log(str(payload))
            elif kind == "done":
                success, message = payload  # type: ignore[assignment]
                self._append_log(f"\n--- {message} ---\n")
                self._is_running = False
                self.run_button.state(["!disabled"])
                self._hide_busy()
                self.status_chip.configure(text=message)
                if success:
                    messagebox.showinfo("任务完成", message, parent=self)
                else:
                    messagebox.showwarning("任务完成", message, parent=self)
            elif kind == "history":
                self._record_history(payload)  # type: ignore[arg-type]
        if self._is_running:
            self._show_busy()
        elif not updated:
            self._hide_busy()
        self.after(160, self._poll_log_queue)

    def _read_cookie(self) -> str:
        return self.cookie_text.get("1.0", tk.END).strip()

    def _build_tasks(
        self,
        title_keywords: Sequence[str],
        time_keywords: Sequence[str],
        dates: Sequence[Optional[str]],
        strict_match: bool,
        allow_fallback: bool,
        max_attempts: int,
        delay_ms: Tuple[int, int],
    ) -> List[TaskConfig]:
        tasks: List[TaskConfig] = []
        base = TaskConfig(
            title_keywords=list(title_keywords),
            time_keywords=list(time_keywords),
            strict_match=strict_match,
            allow_fallback=allow_fallback,
            max_attempts=max_attempts,
            delay_ms=delay_ms,
        )
        if not dates:
            tasks.append(base)
        else:
            for date in dates:
                task = TaskConfig(
                    title_keywords=list(title_keywords),
                    time_keywords=list(time_keywords),
                    date=date,
                    strict_match=strict_match,
                    allow_fallback=allow_fallback,
                    max_attempts=max_attempts,
                    delay_ms=delay_ms,
                )
                tasks.append(task)
        return tasks

    def _build_config(self) -> AppConfig:
        cookie = self._read_cookie()
        if not cookie:
            raise ValueError("Cookie 不能为空。")

        title_keywords = self.title_tags.get_tags()
        time_keywords = self.time_tags.get_tags()
        if not title_keywords and not time_keywords:
            raise ValueError("请至少填写课程标题或时段关键字。")

        preferred_cards = self.preferred_tags.get_tags()
        date_tokens = self.date_picker.get_tokens()
        date_value = "\n".join(date_tokens)
        dates = parse_date_list(date_value) if date_value else []

        max_attempts = max(1, int(self.max_attempts_var.get() or 1))
        try:
            delay = parse_delay(f"{self.delay_low_var.get()},{self.delay_high_var.get()}")
        except ValueError as exc:
            raise ValueError(str(exc))
        if not delay:
            delay = (120, 300)

        strict_match = bool(self.strict_var.get())
        allow_fallback = bool(self.allow_fallback_var.get())

        shop_id = self.shop_id_var.get().strip() or DEFAULT_SHOP_ID

        global_timeout_ms: Optional[int]
        if self.global_timeout_var.get().strip():
            try:
                global_timeout_ms = int(self.global_timeout_var.get().strip())
            except ValueError as exc:
                raise ValueError("全局超时需要为整数毫秒。") from exc
        else:
            global_timeout_ms = None

        concurrency = max(1, int(self.concurrency_var.get() or 1))

        account = AccountConfig(
            name=self.account_name_var.get().strip() or "ACCOUNT_PLACEHOLDER",
            cookie=cookie,
            preferred_cards=preferred_cards,
        )

        tasks = self._build_tasks(
            title_keywords=title_keywords,
            time_keywords=time_keywords,
            dates=dates,
            strict_match=strict_match,
            allow_fallback=allow_fallback,
            max_attempts=max_attempts,
            delay_ms=(int(delay[0]), int(delay[1])),
        )

        config = AppConfig(
            shop_id=shop_id,
            accounts=[account],
            tasks=tasks,
            date_rule=None,
            global_timeout_ms=global_timeout_ms,
            concurrency=concurrency,
            log_json=bool(self.log_json_var.get()),
        )
        return config

    def _on_run_clicked(self) -> None:
        if self._is_running:
            return
        try:
            config = self._build_config()
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc), parent=self)
            return

        self._is_running = True
        self.run_button.state(["disabled"])
        self.status_chip.configure(text="正在执行...")
        self._append_log("\n=== 开始执行预约任务 ===\n")
        self._show_busy()
        self._current_run_started = dt.datetime.now()

        thread = threading.Thread(
            target=self._run_worker,
            args=(config, self._current_run_started),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, config: AppConfig, started_at: dt.datetime) -> None:
        writer = QueueWriter(self.log_queue)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = writer
        try:
            records = run_tasks(config)
        except Exception as exc:  # pragma: no cover - runtime safety
            self.log_queue.put(("log", f"[异常] {exc}\n"))
            self.log_queue.put(("done", (False, "执行失败，请查看日志")))
        else:
            success, message = self._summarise_records(records)
            finished_at = dt.datetime.now()
            duration = (finished_at - started_at).total_seconds()
            history_payload = {
                "started": started_at.strftime("%H:%M:%S"),
                "duration": f"{duration:.1f}s",
                "result": "成功" if success else "失败",
                "summary": sanitize_payload(
                    {
                        "tasks": len(records),
                        "success": success,
                        "message": message,
                    }
                ),
            }
            self.log_queue.put(("history", history_payload))
            self.log_queue.put(("done", (success, message)))
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def _summarise_records(
        self, records: Sequence[TaskExecutionRecord]
    ) -> Tuple[bool, str]:
        if not records:
            return False, "没有可执行的任务，请检查关键字或日期配置"
        success = all(record.outcome.success for record in records)
        if success:
            return True, "所有任务执行成功"
        return False, "部分任务执行失败，详见日志"


def main() -> None:  # pragma: no cover - UI bootstrap
    app = VisualApp()
    app.mainloop()


if __name__ == "__main__":  # pragma: no cover - script entry
    main()
