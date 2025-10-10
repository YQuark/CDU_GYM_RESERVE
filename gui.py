"""Simple Tkinter GUI for running CDU_GYM_RESERVE tasks on Windows."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import List, Optional, Sequence, Tuple

from config import AccountConfig, AppConfig, TaskConfig
from config_utils import parse_date_list, parse_delay, parse_keywords
from runner import TaskExecutionRecord, run_tasks

DEFAULT_SHOP_ID = "612773420"


class QueueWriter:
    """Write stdout/stderr data into a Tkinter-safe queue."""

    def __init__(self, target: "queue.Queue[tuple[str, object]]") -> None:
        self._target = target

    def write(self, data: str) -> None:  # pragma: no cover - UI side-effect
        if not data:
            return
        self._target.put(("log", data))

    def flush(self) -> None:  # pragma: no cover - compatibility
        pass


class VisualApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("styd.cn 自动预约 - 可视化面板")
        self.root.geometry("960x680")
        self.root.minsize(860, 600)

        self._init_styles()

        self.log_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._is_running = False

        self._build_widgets()
        self.root.after(100, self._poll_log_queue)

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    def _init_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.configure(bg="#f5f7fb")
        self.root.option_add("*Font", "Microsoft YaHei UI 10")

        style.configure(
            "TNotebook",
            background="#f5f7fb",
            borderwidth=0,
            padding=6,
        )
        style.configure(
            "TNotebook.Tab",
            padding=(16, 10),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#3f8cff")],
            foreground=[("selected", "white"), ("!selected", "#4a5568")],
        )

        style.configure(
            "Card.TFrame",
            background="white",
            relief="flat",
        )
        style.configure(
            "CardHeading.TLabel",
            font=("Microsoft YaHei UI", 14, "bold"),
            foreground="#1a202c",
            background="white",
        )
        style.configure(
            "Section.TLabel",
            font=("Microsoft YaHei UI", 10),
            foreground="#2d3748",
            background="white",
        )
        style.configure(
            "Card.TCheckbutton",
            background="white",
            foreground="#2d3748",
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Accent.TButton",
            font=("Microsoft YaHei UI", 11, "bold"),
            foreground="white",
            background="#3f8cff",
            padding=(16, 10),
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("pressed", "#2667d1"), ("active", "#2667d1")],
        )
        style.configure(
            "TEntry",
            fieldbackground="#f7fafc",
            bordercolor="#cbd5f5",
            lightcolor="#93c5fd",
            darkcolor="#93c5fd",
            relief="flat",
            padding=6,
        )

    def _build_widgets(self) -> None:
        wrapper = ttk.Frame(self.root, style="Card.TFrame")
        wrapper.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        header = ttk.Frame(wrapper, style="Card.TFrame")
        header.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(
            header,
            text="styd.cn 自动预约",
            style="CardHeading.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="填写账号信息与课程筛选条件后即可一键执行预约",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(6, 0))

        notebook = ttk.Notebook(wrapper)
        notebook.pack(fill=tk.BOTH, expand=True)

        self.form_frame = ttk.Frame(notebook, style="Card.TFrame")
        self.log_frame = ttk.Frame(notebook, style="Card.TFrame")
        notebook.add(self.form_frame, text="配置")
        notebook.add(self.log_frame, text="日志")

        self._build_form(self.form_frame)
        self._build_log(self.log_frame)

    def _build_form(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, borderwidth=0, background="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        self.form_container = ttk.Frame(canvas, style="Card.TFrame")

        self.form_container.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.form_container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        row = 0
        # Account
        ttk.Label(self.form_container, text="账号昵称", style="Section.TLabel").grid(
            row=row, column=0, sticky="w", pady=6
        )
        self.account_name_var = tk.StringVar(value="QL-Account")
        ttk.Entry(self.form_container, textvariable=self.account_name_var, width=50).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(self.form_container, text="Cookie", style="Section.TLabel").grid(
            row=row, column=0, sticky="nw", pady=6
        )
        self.cookie_text = tk.Text(
            self.form_container,
            height=4,
            width=60,
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            background="#f7fafc",
        )
        self.cookie_text.grid(row=row, column=1, sticky="we", pady=6)
        row += 1

        ttk.Label(
            self.form_container, text="优先会员卡关键字", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.preferred_cards_var = tk.StringVar()
        ttk.Entry(self.form_container, textvariable=self.preferred_cards_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Separator(self.form_container, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container,
            text="课程标题关键字 (逗号/竖线/换行分隔)",
            style="Section.TLabel",
        ).grid(
            row=row, column=0, sticky="w", pady=6
        )
        self.title_keywords_var = tk.StringVar()
        ttk.Entry(self.form_container, textvariable=self.title_keywords_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container, text="时段关键字", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.time_keywords_var = tk.StringVar()
        ttk.Entry(self.form_container, textvariable=self.time_keywords_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container,
            text="预约日期 (支持 2024-01-01 或区间 2024-01-01~2024-01-05)",
            style="Section.TLabel",
        ).grid(
            row=row, column=0, sticky="w", pady=6
        )
        self.date_var = tk.StringVar()
        ttk.Entry(self.form_container, textvariable=self.date_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container, text="最大重试次数", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.max_attempts_var = tk.StringVar(value="1")
        ttk.Entry(self.form_container, textvariable=self.max_attempts_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container, text="重试间隔 (ms, 例如 120,300)", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.delay_var = tk.StringVar(value="120,300")
        ttk.Entry(self.form_container, textvariable=self.delay_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        self.strict_match_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.form_container,
            text="严格匹配关键字",
            variable=self.strict_match_var,
            style="Card.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
        row += 1

        self.allow_fallback_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self.form_container,
            text="匹配失败时允许任意可约课程",
            variable=self.allow_fallback_var,
            style="Card.TCheckbutton",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
        row += 1

        ttk.Separator(self.form_container, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky="we", pady=6
        )
        row += 1

        ttk.Label(self.form_container, text="shop_id", style="Section.TLabel").grid(
            row=row, column=0, sticky="w", pady=6
        )
        self.shop_id_var = tk.StringVar(value=DEFAULT_SHOP_ID)
        ttk.Entry(self.form_container, textvariable=self.shop_id_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container, text="全局超时 (ms，可选)", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.global_timeout_var = tk.StringVar()
        ttk.Entry(self.form_container, textvariable=self.global_timeout_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        ttk.Label(
            self.form_container, text="并发数", style="Section.TLabel"
        ).grid(row=row, column=0, sticky="w", pady=6)
        self.concurrency_var = tk.StringVar(value="1")
        ttk.Entry(self.form_container, textvariable=self.concurrency_var).grid(
            row=row, column=1, sticky="we", pady=6
        )
        row += 1

        self.log_json_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.form_container,
            text="输出 JSON 日志",
            variable=self.log_json_var,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
        row += 1

        ttk.Label(
            self.form_container,
            text="提示：关键字可使用逗号、竖线或换行分隔；多日期会自动拆分为多个任务。",
            style="Section.TLabel",
            wraplength=520,
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=10)
        row += 1

        self.run_button = ttk.Button(
            self.form_container,
            text="执行预约",
            command=self._on_run_clicked,
            style="Accent.TButton",
        )
        self.run_button.grid(row=row, column=0, columnspan=2, pady=16, sticky="we")

        button_shadow = tk.Frame(
            self.form_container,
            background="#2667d1",
            height=2,
        )
        button_shadow.grid(row=row + 1, column=0, columnspan=2, sticky="we", pady=(0, 12))
        row += 2

        for child in self.form_container.winfo_children():
            if isinstance(child, (ttk.Entry, tk.Text)):
                child.configure(takefocus=True)
        self.form_container.columnconfigure(1, weight=1)

    def _build_log(self, parent: ttk.Frame) -> None:
        container = ttk.Frame(parent, style="Card.TFrame")
        container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.log_text = scrolledtext.ScrolledText(
            container,
            state=tk.DISABLED,
            font=("Cascadia Code", 10),
            background="#1f2933",
            foreground="#f7fafc",
            insertbackground="#f7fafc",
            relief="flat",
            borderwidth=0,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _append_log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                kind, payload = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(payload))
            elif kind == "done":
                success, message = payload  # type: ignore[assignment]
                self._append_log(f"\n--- {message} ---\n")
                self._is_running = False
                self.run_button.configure(state=tk.NORMAL)
                if success:
                    messagebox.showinfo("任务完成", message)
                else:
                    messagebox.showwarning("任务完成", message)
        self.root.after(100, self._poll_log_queue)

    def _read_text(self, widget: tk.Text) -> str:
        return widget.get("1.0", tk.END).strip()

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
        cookie = self._read_text(self.cookie_text)
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
            messagebox.showerror("配置错误", str(exc))
            return

        self._is_running = True
        self.run_button.configure(state=tk.DISABLED)
        self._append_log("\n=== 开始执行预约任务 ===\n")

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
    root = tk.Tk()
    app = VisualApp(root)
    root.mainloop()


if __name__ == "__main__":  # pragma: no cover - script entry
    main()
