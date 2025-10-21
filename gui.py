"""Tkinter-based GUI for running CDU_GYM_RESERVE tasks on desktop platforms."""

from __future__ import annotations

import queue
import sys
import threading
from typing import Dict, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from config import AccountConfig, AppConfig, TaskConfig
from config_utils import parse_date_list, parse_delay, parse_keywords
from runner import TaskExecutionRecord, run_tasks

DEFAULT_SHOP_ID = "612773420"

_THEME_MAP: Dict[str, Dict[str, str]] = {
    "light": {
        "primary": "#2563eb",
        "primary-active": "#1d4ed8",
        "text": "#1f2937",
        "text-muted": "#6b7280",
        "bg": "#f8fafc",
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


class VisualApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("styd.cn 自动预约 - 可视化面板")
        self.geometry("1024x720")
        self.minsize(900, 640)

        self.log_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._is_running = False
        self._current_theme = "light"
        self._text_widgets: List[tk.Text] = []

        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except tk.TclError:  # pragma: no cover - fallback
            pass

        self._build_styles()
        self._build_widgets()
        self._apply_theme(self._current_theme)

        self.after(120, self._poll_log_queue)

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    def _build_styles(self) -> None:
        self.option_add("*Font", "Microsoft YaHei UI 10")
        self.option_add("*TCombobox*Listbox.font", "Microsoft YaHei UI 10")
        self.style.configure("Title.TLabel", font=("Microsoft YaHei UI", 20, "bold"))
        self.style.configure("Subtitle.TLabel", font=("Microsoft YaHei UI", 12))
        self.style.configure("FormLabel.TLabel", font=("Microsoft YaHei UI", 10))
        self.style.configure("Hint.TLabel", font=("Microsoft YaHei UI", 9))
        self.style.configure("Primary.TButton", padding=(16, 10))
        self.style.configure("Chip.TLabel", padding=(14, 6))
        self.style.configure("Card.TFrame", borderwidth=1, relief="solid")

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title = ttk.Label(header, text="styd.cn 自动预约", style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")

        subtitle = ttk.Label(
            header,
            text="填写账号信息与课程筛选条件后即可一键执行预约",
            style="Subtitle.TLabel",
            wraplength=760,
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew", pady=(18, 0))

        self.form_tab = ttk.Frame(notebook)
        self.log_tab = ttk.Frame(notebook)
        self.form_tab.columnconfigure(1, weight=1)

        notebook.add(self.form_tab, text="配置")
        notebook.add(self.log_tab, text="日志")

        self._build_form(self.form_tab)
        self._build_log(self.log_tab)

    def _build_form(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        padx = (0, 16)
        pady = 6

        def add_label(text: str, row: int) -> None:
            label = ttk.Label(parent, text=text, style="FormLabel.TLabel")
            label.grid(row=row, column=0, sticky="nw", padx=padx, pady=pady)

        row = 0

        self.account_name_var = tk.StringVar(value="QL-Account")
        add_label("账号昵称", row)
        account_entry = ttk.Entry(parent, textvariable=self.account_name_var)
        account_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.cookie_text = scrolledtext.ScrolledText(parent, height=6, wrap=tk.WORD)
        self.cookie_text.insert("1.0", "")
        self._text_widgets.append(self.cookie_text)
        add_label("Cookie", row)
        self.cookie_text.grid(row=row, column=1, sticky="nsew", pady=pady)
        parent.rowconfigure(row, weight=1)
        row += 1

        self.preferred_cards_var = tk.StringVar()
        add_label("优先会员卡关键字", row)
        preferred_entry = ttk.Entry(parent, textvariable=self.preferred_cards_var)
        preferred_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.title_keywords_var = tk.StringVar()
        add_label("课程标题关键字 (逗号/竖线/换行分隔)", row)
        title_entry = ttk.Entry(parent, textvariable=self.title_keywords_var)
        title_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.time_keywords_var = tk.StringVar()
        add_label("时段关键字", row)
        time_entry = ttk.Entry(parent, textvariable=self.time_keywords_var)
        time_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.date_var = tk.StringVar()
        add_label("预约日期 (支持 2024-01-01 或区间 2024-01-01~2024-01-05)", row)
        date_entry = ttk.Entry(parent, textvariable=self.date_var)
        date_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.max_attempts_var = tk.StringVar(value="1")
        add_label("最大重试次数", row)
        max_attempts_entry = ttk.Entry(parent, textvariable=self.max_attempts_var)
        max_attempts_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.delay_var = tk.StringVar(value="120,300")
        add_label("重试间隔 (ms, 例如 120,300)", row)
        delay_entry = ttk.Entry(parent, textvariable=self.delay_var)
        delay_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.strict_match_var = tk.BooleanVar(value=True)
        strict_check = ttk.Checkbutton(
            parent,
            text="严格匹配关键字",
            variable=self.strict_match_var,
        )
        strict_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=pady)
        row += 1

        self.allow_fallback_var = tk.BooleanVar(value=True)
        allow_check = ttk.Checkbutton(
            parent,
            text="匹配失败时允许任意可约课程",
            variable=self.allow_fallback_var,
        )
        allow_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=pady)
        row += 1

        separator = ttk.Separator(parent)
        separator.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 12))
        row += 1

        self.shop_id_var = tk.StringVar(value=DEFAULT_SHOP_ID)
        add_label("shop_id", row)
        shop_entry = ttk.Entry(parent, textvariable=self.shop_id_var)
        shop_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.global_timeout_var = tk.StringVar()
        add_label("全局超时 (ms，可选)", row)
        timeout_entry = ttk.Entry(parent, textvariable=self.global_timeout_var)
        timeout_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.concurrency_var = tk.StringVar(value="1")
        add_label("并发数", row)
        concurrency_entry = ttk.Entry(parent, textvariable=self.concurrency_var)
        concurrency_entry.grid(row=row, column=1, sticky="ew", pady=pady)
        row += 1

        self.log_json_var = tk.BooleanVar(value=False)
        log_json_check = ttk.Checkbutton(
            parent,
            text="输出 JSON 日志",
            variable=self.log_json_var,
        )
        log_json_check.grid(row=row, column=0, columnspan=2, sticky="w", pady=pady)
        row += 1

        hint = ttk.Label(
            parent,
            text="提示：关键字可使用逗号、竖线或换行分隔；多日期会自动拆分为多个任务。",
            style="Hint.TLabel",
            wraplength=760,
        )
        hint.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 12))
        row += 1

        self.run_button = ttk.Button(
            parent,
            text="执行预约",
            style="Primary.TButton",
            command=self._on_run_clicked,
        )
        self.run_button.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def _build_log(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)

        title = ttk.Label(toolbar, text="执行日志", style="FormLabel.TLabel")
        title.grid(row=0, column=0, sticky="w")

        self.theme_toggle = ttk.Button(toolbar, text="切换至深色模式", command=self._toggle_theme)
        self.theme_toggle.grid(row=0, column=1, padx=(12, 0))

        clear_button = ttk.Button(toolbar, text="清空", command=self._clear_log)
        clear_button.grid(row=0, column=2, padx=(12, 0))

        self.log_text = scrolledtext.ScrolledText(parent, height=20, wrap=tk.NONE)
        self.log_text.grid(row=1, column=0, sticky="nsew")
        parent.rowconfigure(1, weight=1)
        self.log_text.configure(state="disabled")
        self._text_widgets.append(self.log_text)

        status_frame = ttk.Frame(parent)
        status_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        status_frame.columnconfigure(0, weight=1)

        self.busy_indicator = ttk.Progressbar(status_frame, mode="indeterminate")
        self.busy_indicator.grid(row=0, column=0, sticky="ew")
        self.busy_indicator.grid_remove()

        self.status_chip = ttk.Label(
            status_frame,
            text="准备就绪",
            style="Chip.TLabel",
            anchor="e",
        )
        self.status_chip.grid(row=1, column=0, sticky="ew", pady=(8, 0))

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _apply_theme(self, theme: str) -> None:
        self._current_theme = theme
        palette = _THEME_MAP.get(theme, _THEME_MAP["light"])

        self.configure(bg=palette["bg"])
        self.style.configure("TFrame", background=palette["bg"])
        self.style.configure("Title.TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure("Subtitle.TLabel", background=palette["bg"], foreground=palette["text-muted"])
        self.style.configure("FormLabel.TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure("Hint.TLabel", background=palette["bg"], foreground=palette["text-muted"])
        self.style.configure("Chip.TLabel", background=palette["bg-elev"], foreground=palette["text"])
        self.style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
        self.style.configure("TLabel", background=palette["bg"], foreground=palette["text"])
        self.style.configure(
            "TNotebook",
            background=palette["bg"],
            tabmargins=(0, 10, 0, 0),
            borderwidth=0,
        )
        self.style.configure(
            "TNotebook.Tab",
            background=palette["bg-elev"],
            foreground=palette["text"],
            padding=(18, 8),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", palette["primary"]), ("active", palette["focus"])],
            foreground=[("selected", "#ffffff"), ("active", palette["text"])],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=palette["bg-elev"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            lightcolor=palette["focus"],
            darkcolor=palette["border"],
        )
        self.style.map(
            "TEntry",
            fieldbackground=[("disabled", palette["bg"])],
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
            background=[("pressed", palette["primary-active"]), ("active", palette["primary-active"]), ("!disabled", palette["primary"])],
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
            background=[("pressed", palette["border"]), ("active", palette["focus"]), ("!disabled", palette["bg-elev"])],
            foreground=[("disabled", palette["text-muted"]), ("!disabled", palette["text"])],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            background=palette["primary"],
            troughcolor=palette["bg-elev"],
            bordercolor=palette["border"],
        )

        for widget in self._text_widgets:
            widget.configure(
                background=palette["bg-elev"],
                foreground=palette["text"],
                insertbackground=palette["primary"],
                highlightthickness=1,
                highlightbackground=palette["border"],
                highlightcolor=palette["focus"],
            )

        self.theme_toggle.configure(
            text="切换至浅色模式" if theme == "dark" else "切换至深色模式"
        )

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _toggle_theme(self) -> None:
        new_theme = "dark" if self._current_theme == "light" else "light"
        self._apply_theme(new_theme)
        self.status_chip.configure(text="已切换主题" if new_theme == "dark" else "准备就绪")

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

        title_keywords = parse_keywords(self.title_keywords_var.get())
        time_keywords = parse_keywords(self.time_keywords_var.get())
        if not title_keywords and not time_keywords:
            raise ValueError("请至少填写课程标题或时段关键字。")

        preferred_cards = parse_keywords(self.preferred_cards_var.get())
        dates = parse_date_list(self.date_var.get())
        if not dates:
            dates_seq: List[Optional[str]] = []
        else:
            dates_seq = dates

        try:
            max_attempts = int(self.max_attempts_var.get() or 1)
        except ValueError as exc:
            raise ValueError("最大重试次数需要为整数。") from exc
        if max_attempts < 1:
            max_attempts = 1

        try:
            delay = parse_delay(self.delay_var.get()) or (120, 300)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        strict_match = bool(self.strict_match_var.get())
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

        try:
            concurrency = int(self.concurrency_var.get() or "1")
        except ValueError as exc:
            raise ValueError("并发数需要为整数。") from exc
        if concurrency < 1:
            concurrency = 1

        account = AccountConfig(
            name=self.account_name_var.get().strip() or "QL-Account",
            cookie=cookie,
            preferred_cards=preferred_cards,
        )

        tasks = self._build_tasks(
            title_keywords=title_keywords,
            time_keywords=time_keywords,
            dates=dates_seq,
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

        thread = threading.Thread(target=self._run_worker, args=(config,), daemon=True)
        thread.start()

    def _run_worker(self, config: AppConfig) -> None:
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
