# >>> changed
"""PyQt5 GUI for running CDU_GYM_RESERVE tasks on desktop platforms."""

from __future__ import annotations

# >>> changed
import queue
# >>> changed
import sys
# >>> changed
import threading
# >>> changed
from typing import Dict, List, Optional, Sequence, Tuple

# >>> changed
from PyQt5 import QtCore, QtGui, QtWidgets

from config import AccountConfig, AppConfig, TaskConfig
from config_utils import parse_date_list, parse_delay, parse_keywords
from runner import TaskExecutionRecord, run_tasks

DEFAULT_SHOP_ID = "612773420"

# >>> added
_THEME_MAP: Dict[str, Dict[str, str]] = {
    "light": {
        "primary": "#3b82f6",
        "text": "#1f2937",
        "text-muted": "#6b7280",
        "bg": "#ffffff",
        "bg-elev": "#f8fafc",
        "border": "#e5e7eb",
        "focus": "#2563eb",
        "danger": "#ef4444",
        "success": "#10b981",
        "shadow": "rgba(0,0,0,0.08)",
    },
    "dark": {
        "primary": "#60a5fa",
        "text": "#e5e7eb",
        "text-muted": "#9ca3af",
        "bg": "#0b0f14",
        "bg-elev": "#111827",
        "border": "#1f2937",
        "focus": "#60a5fa",
        "danger": "#f87171",
        "success": "#34d399",
        "shadow": "rgba(0,0,0,0.5)",
    },
}


# >>> added
def _load_qss_template() -> str:
    with open("modern.qss", "r", encoding="utf-8") as fh:
        return fh.read()


# >>> added
def apply_theme(app: QtWidgets.QApplication, theme: str = "light") -> None:
    palette = _THEME_MAP.get(theme, _THEME_MAP["light"])
    qss = _load_qss_template()
    for key, value in sorted(palette.items(), key=lambda item: -len(item[0])):
        qss = qss.replace(f"@{key}", value)
    app.setProperty("theme", theme)
    app.setStyleSheet(qss)
    for widget in app.topLevelWidgets():
        widget.setProperty("theme", theme)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class QueueWriter:
    """Write stdout/stderr data into a Qt-safe queue."""

    def __init__(self, target: "queue.Queue[tuple[str, object]]") -> None:
        self._target = target

    def write(self, data: str) -> None:  # pragma: no cover - UI side-effect
        if not data:
            return
        self._target.put(("log", data))

    def flush(self) -> None:  # pragma: no cover - compatibility
        pass


# >>> added
class BusyOverlay(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setObjectName("BusyOverlay")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch()
        spinner = QtWidgets.QProgressBar(self)
        spinner.setObjectName("BusySpinner")
        spinner.setRange(0, 0)
        spinner.setFixedWidth(180)
        spinner.setTextVisible(False)
        spinner.setFocusPolicy(QtCore.Qt.NoFocus)
        spinner.setAccessibleName("busy-indicator")
        layout.addWidget(spinner, 0, QtCore.Qt.AlignHCenter)
        layout.addStretch()
        self.hide()

    def showEvent(self, event: QtGui.QShowEvent) -> None:  # pragma: no cover - UI sizing
        super().showEvent(event)
        if self.parent():
            self.resize(self.parent().size())

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # pragma: no cover - UI sizing
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(self.parent().rect())


# >>> added
class _LineEditBinding:
    def __init__(self, widget: QtWidgets.QLineEdit) -> None:
        self._widget = widget

    def get(self) -> str:
        return self._widget.text()

    def set(self, value: str) -> None:
        self._widget.setText(value)


# >>> added
class _PlainTextBinding:
    def __init__(self, widget: QtWidgets.QPlainTextEdit) -> None:
        self._widget = widget

    def get(self) -> str:
        return self._widget.toPlainText()

    def set(self, value: str) -> None:
        self._widget.setPlainText(value)


# >>> added
class _CheckBinding:
    def __init__(self, widget: QtWidgets.QCheckBox) -> None:
        self._widget = widget

    def get(self) -> bool:
        return self._widget.isChecked()

    def set(self, value: bool) -> None:
        self._widget.setChecked(bool(value))


# >>> changed
class VisualApp(QtWidgets.QMainWindow):
    def __init__(self, root: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent=root)
        self.setObjectName("VisualApp")
        self.setWindowTitle("styd.cn 自动预约 - 可视化面板")
        self.resize(1024, 720)
        self.setMinimumSize(900, 640)

        self.log_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._is_running = False
        self._current_theme = "light"

        self._init_styles()
        self._build_widgets()

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(120)
        self._poll_timer.timeout.connect(self._poll_log_queue)
        self._poll_timer.start()

        self._busy_overlay = BusyOverlay(self.centralWidget())
        self._busy_overlay.hide()

    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    def _init_styles(self) -> None:
        font = QtGui.QFont("Microsoft YaHei UI", 10)
        self.setFont(font)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setFont(font)

    def _build_widgets(self) -> None:
        central = QtWidgets.QWidget(self)
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_frame = QtWidgets.QFrame(central)
        header_layout = QtWidgets.QVBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        header_title = QtWidgets.QLabel("styd.cn 自动预约", header_frame)
        header_title.setObjectName("PageTitle")
        header_title.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        header_title.setAccessibleName("page-title")
        header_layout.addWidget(header_title)

        subtitle = QtWidgets.QLabel(
            "填写账号信息与课程筛选条件后即可一键执行预约",
            header_frame,
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setAccessibleName("page-subtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        layout.addWidget(header_frame)

        self.tab_widget = QtWidgets.QTabWidget(central)
        self.tab_widget.setObjectName("MainTab")
        layout.addWidget(self.tab_widget)

        self.form_tab = QtWidgets.QWidget()
        self.log_tab = QtWidgets.QWidget()
        self.tab_widget.addTab(self.form_tab, "配置")
        self.tab_widget.addTab(self.log_tab, "日志")

        self._build_form(self.form_tab)
        self._build_log(self.log_tab)

    def _build_form(self, parent: QtWidgets.QWidget) -> None:
        form_layout = QtWidgets.QVBoxLayout(parent)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea(parent)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setObjectName("FormScroll")
        form_layout.addWidget(scroll)

        container = QtWidgets.QWidget()
        container.setObjectName("FormContainer")
        scroll.setWidget(container)

        grid = QtWidgets.QGridLayout(container)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setVerticalSpacing(12)
        grid.setHorizontalSpacing(18)

        row = 0

        def add_label(text: str) -> QtWidgets.QLabel:
            label = QtWidgets.QLabel(text, container)
            label.setProperty("formLabel", True)
            label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            label.setAccessibleName(f"label-{text}")
            return label

        self.account_name_edit = QtWidgets.QLineEdit(container)
        self.account_name_edit.setPlaceholderText("QL-Account")
        self.account_name_edit.setClearButtonEnabled(True)
        self.account_name_edit.setAccessibleName("account-name")
        self.account_name_edit.setToolTip("预约所使用的青龙账号昵称")
        self.account_name_edit.setText("QL-Account")
        self.account_name_var = _LineEditBinding(self.account_name_edit)
        grid.addWidget(add_label("账号昵称"), row, 0)
        grid.addWidget(self.account_name_edit, row, 1)
        row += 1

        self.cookie_edit = QtWidgets.QPlainTextEdit(container)
        self.cookie_edit.setPlaceholderText("粘贴 Cookie")
        self.cookie_edit.setFixedHeight(120)
        self.cookie_edit.setAccessibleName("cookie-text")
        self.cookie_edit.setToolTip("粘贴完整的 Cookie 内容")
        self.cookie_text = _PlainTextBinding(self.cookie_edit)
        grid.addWidget(add_label("Cookie"), row, 0, QtCore.Qt.AlignTop)
        grid.addWidget(self.cookie_edit, row, 1)
        row += 1

        self.preferred_cards_edit = QtWidgets.QLineEdit(container)
        self.preferred_cards_edit.setPlaceholderText("尊享卡, 青铜卡")
        self.preferred_cards_edit.setClearButtonEnabled(True)
        self.preferred_cards_edit.setAccessibleName("preferred-cards")
        self.preferred_cards_edit.setToolTip("优先匹配的会员卡关键字，逗号或竖线分隔")
        self.preferred_cards_var = _LineEditBinding(self.preferred_cards_edit)
        grid.addWidget(add_label("优先会员卡关键字"), row, 0)
        grid.addWidget(self.preferred_cards_edit, row, 1)
        row += 1

        title_label = QtWidgets.QLabel(
            "课程标题关键字 (逗号/竖线/换行分隔)",
            container,
        )
        title_label.setProperty("formLabel", True)
        title_label.setAccessibleName("label-title-keywords")
        self.title_keywords_edit = QtWidgets.QLineEdit(container)
        self.title_keywords_edit.setPlaceholderText("瑜伽, 跑步")
        self.title_keywords_edit.setClearButtonEnabled(True)
        self.title_keywords_edit.setAccessibleName("title-keywords")
        self.title_keywords_edit.setToolTip("课程标题关键字，支持逗号/竖线/换行")
        self.title_keywords_var = _LineEditBinding(self.title_keywords_edit)
        grid.addWidget(title_label, row, 0)
        grid.addWidget(self.title_keywords_edit, row, 1)
        row += 1

        self.time_keywords_edit = QtWidgets.QLineEdit(container)
        self.time_keywords_edit.setPlaceholderText("早上, 下午")
        self.time_keywords_edit.setClearButtonEnabled(True)
        self.time_keywords_edit.setAccessibleName("time-keywords")
        self.time_keywords_edit.setToolTip("时段关键字，例如 18:00")
        self.time_keywords_var = _LineEditBinding(self.time_keywords_edit)
        grid.addWidget(add_label("时段关键字"), row, 0)
        grid.addWidget(self.time_keywords_edit, row, 1)
        row += 1

        date_label = QtWidgets.QLabel(
            "预约日期 (支持 2024-01-01 或区间 2024-01-01~2024-01-05)",
            container,
        )
        date_label.setProperty("formLabel", True)
        date_label.setAccessibleName("label-date-range")
        self.date_edit = QtWidgets.QLineEdit(container)
        self.date_edit.setPlaceholderText("2024-01-01 或 2024-01-01~2024-01-05")
        self.date_edit.setClearButtonEnabled(True)
        self.date_edit.setAccessibleName("date-range")
        self.date_edit.setToolTip("支持单个日期或日期区间，多个日期用逗号分隔")
        self.date_var = _LineEditBinding(self.date_edit)
        grid.addWidget(date_label, row, 0)
        grid.addWidget(self.date_edit, row, 1)
        row += 1

        self.max_attempts_edit = QtWidgets.QLineEdit(container)
        self.max_attempts_edit.setPlaceholderText("1")
        self.max_attempts_edit.setClearButtonEnabled(True)
        self.max_attempts_edit.setAccessibleName("max-attempts")
        self.max_attempts_edit.setToolTip("单个任务失败后的最大重试次数")
        self.max_attempts_edit.setText("1")
        self.max_attempts_var = _LineEditBinding(self.max_attempts_edit)
        grid.addWidget(add_label("最大重试次数"), row, 0)
        grid.addWidget(self.max_attempts_edit, row, 1)
        row += 1

        self.delay_edit = QtWidgets.QLineEdit(container)
        self.delay_edit.setPlaceholderText("120,300")
        self.delay_edit.setClearButtonEnabled(True)
        self.delay_edit.setAccessibleName("delay-range")
        self.delay_edit.setToolTip("重试间隔毫秒，使用起止值，例如 120,300")
        self.delay_edit.setText("120,300")
        self.delay_var = _LineEditBinding(self.delay_edit)
        grid.addWidget(add_label("重试间隔 (ms, 例如 120,300)"), row, 0)
        grid.addWidget(self.delay_edit, row, 1)
        row += 1

        self.strict_match_check = QtWidgets.QCheckBox("严格匹配关键字", container)
        self.strict_match_check.setChecked(True)
        self.strict_match_check.setAccessibleName("strict-match")
        self.strict_match_check.setToolTip("仅当课程完全匹配关键字时才尝试预约")
        self.strict_match_var = _CheckBinding(self.strict_match_check)
        grid.addWidget(self.strict_match_check, row, 0, 1, 2)
        row += 1

        self.allow_fallback_check = QtWidgets.QCheckBox(
            "匹配失败时允许任意可约课程",
            container,
        )
        self.allow_fallback_check.setChecked(True)
        self.allow_fallback_check.setAccessibleName("allow-fallback")
        self.allow_fallback_check.setToolTip("若关键字不匹配则尝试任意可约课程")
        self.allow_fallback_var = _CheckBinding(self.allow_fallback_check)
        grid.addWidget(self.allow_fallback_check, row, 0, 1, 2)
        row += 1

        separator = QtWidgets.QFrame(container)
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator.setObjectName("FormSeparator")
        grid.addWidget(separator, row, 0, 1, 2)
        row += 1

        self.shop_id_edit = QtWidgets.QLineEdit(container)
        self.shop_id_edit.setPlaceholderText(DEFAULT_SHOP_ID)
        self.shop_id_edit.setAccessibleName("shop-id")
        self.shop_id_edit.setToolTip("目标门店 shop_id，默认为系统推荐值")
        self.shop_id_edit.setText(DEFAULT_SHOP_ID)
        self.shop_id_var = _LineEditBinding(self.shop_id_edit)
        grid.addWidget(add_label("shop_id"), row, 0)
        grid.addWidget(self.shop_id_edit, row, 1)
        row += 1

        self.global_timeout_edit = QtWidgets.QLineEdit(container)
        self.global_timeout_edit.setPlaceholderText("例如 30000")
        self.global_timeout_edit.setAccessibleName("global-timeout")
        self.global_timeout_edit.setToolTip("全局任务超时时间，单位毫秒，可选")
        self.global_timeout_var = _LineEditBinding(self.global_timeout_edit)
        grid.addWidget(add_label("全局超时 (ms，可选)"), row, 0)
        grid.addWidget(self.global_timeout_edit, row, 1)
        row += 1

        self.concurrency_edit = QtWidgets.QLineEdit(container)
        self.concurrency_edit.setPlaceholderText("1")
        self.concurrency_edit.setAccessibleName("concurrency")
        self.concurrency_edit.setToolTip("并发执行的任务数量")
        self.concurrency_edit.setText("1")
        self.concurrency_var = _LineEditBinding(self.concurrency_edit)
        grid.addWidget(add_label("并发数"), row, 0)
        grid.addWidget(self.concurrency_edit, row, 1)
        row += 1

        self.log_json_check = QtWidgets.QCheckBox("输出 JSON 日志", container)
        self.log_json_check.setAccessibleName("log-json")
        self.log_json_check.setToolTip("将执行日志额外输出为 JSON 格式")
        self.log_json_var = _CheckBinding(self.log_json_check)
        grid.addWidget(self.log_json_check, row, 0, 1, 2)
        row += 1

        hint = QtWidgets.QLabel(
            "提示：关键字可使用逗号、竖线或换行分隔；多日期会自动拆分为多个任务。",
            container,
        )
        hint.setWordWrap(True)
        hint.setProperty("hintLabel", True)
        hint.setAccessibleName("hint-label")
        grid.addWidget(hint, row, 0, 1, 2)
        row += 1

        self.run_button = QtWidgets.QPushButton("执行预约", container)
        self.run_button.setProperty("primary", True)
        self.run_button.setObjectName("RunButton")
        self.run_button.setDefault(True)
        self.run_button.setAutoDefault(True)
        self.run_button.setShortcut("Ctrl+Return")
        self.run_button.setToolTip("Ctrl+Enter 快速启动预约任务")
        self.run_button.setAccessibleName("run-button")
        self.run_button.clicked.connect(self._on_run_clicked)
        grid.addWidget(self.run_button, row, 0, 1, 2)
        row += 1

        grid.setColumnStretch(1, 1)

        self.setTabOrder(self.account_name_edit, self.cookie_edit)
        self.setTabOrder(self.cookie_edit, self.preferred_cards_edit)
        self.setTabOrder(self.preferred_cards_edit, self.title_keywords_edit)
        self.setTabOrder(self.title_keywords_edit, self.time_keywords_edit)
        self.setTabOrder(self.time_keywords_edit, self.date_edit)
        self.setTabOrder(self.date_edit, self.max_attempts_edit)
        self.setTabOrder(self.max_attempts_edit, self.delay_edit)
        self.setTabOrder(self.delay_edit, self.strict_match_check)
        self.setTabOrder(self.strict_match_check, self.allow_fallback_check)
        self.setTabOrder(self.allow_fallback_check, self.shop_id_edit)
        self.setTabOrder(self.shop_id_edit, self.global_timeout_edit)
        self.setTabOrder(self.global_timeout_edit, self.concurrency_edit)
        self.setTabOrder(self.concurrency_edit, self.log_json_check)
        self.setTabOrder(self.log_json_check, self.run_button)

    def _build_log(self, parent: QtWidgets.QWidget) -> None:
        layout = QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setSpacing(8)
        title = QtWidgets.QLabel("执行日志", parent)
        title.setProperty("formLabel", True)
        title.setAccessibleName("label-log-title")
        toolbar.addWidget(title)
        toolbar.addStretch(1)

        self.theme_toggle = QtWidgets.QPushButton("切换主题", parent)
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.setToolTip("在浅色/深色模式之间切换")
        self.theme_toggle.setAccessibleName("toggle-theme")
        self.theme_toggle.clicked.connect(self._toggle_theme)
        toolbar.addWidget(self.theme_toggle)

        clear_button = QtWidgets.QPushButton("清空", parent)
        clear_button.setToolTip("清空日志输出")
        clear_button.setAccessibleName("clear-log")
        clear_button.clicked.connect(self._clear_log)
        toolbar.addWidget(clear_button)

        layout.addLayout(toolbar)

        self.log_text = QtWidgets.QPlainTextEdit(parent)
        self.log_text.setObjectName("LogOutput")
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.log_text.setFont(QtGui.QFont("Cascadia Code", 10))
        self.log_text.setAccessibleName("log-output")
        layout.addWidget(self.log_text, 1)

        self.status_chip = QtWidgets.QLabel("准备就绪", parent)
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.status_chip.setAccessibleName("status-chip")
        layout.addWidget(self.status_chip)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _append_log(self, text: str) -> None:
        cursor = self.log_text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

    def _clear_log(self) -> None:
        self.log_text.clear()

    def _toggle_theme(self) -> None:
        self._current_theme = "dark" if self._current_theme == "light" else "light"
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_theme(app, self._current_theme)
        self.theme_toggle.setChecked(self._current_theme == "dark")
        self.status_chip.setText("已切换主题" if self._current_theme == "dark" else "准备就绪")

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
                self.run_button.setEnabled(True)
                self._busy_overlay.hide()
                self.status_chip.setText(message)
                icon = QtWidgets.QMessageBox.Information if success else QtWidgets.QMessageBox.Warning
                QtWidgets.QMessageBox(
                    icon,
                    "任务完成",
                    message,
                    QtWidgets.QMessageBox.Ok,
                    self,
                ).exec_()
        if self._is_running:
            self._busy_overlay.show()
            self._busy_overlay.raise_()
        else:
            self._busy_overlay.hide()

    def _read_text(self, binding: _PlainTextBinding) -> str:
        return binding.get().strip()

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
            QtWidgets.QMessageBox.critical(self, "配置错误", str(exc))
            return

        self._is_running = True
        self.run_button.setEnabled(False)
        self.status_chip.setText("正在执行...")
        self._append_log("\n=== 开始执行预约任务 ===\n")
        self._busy_overlay.show()
        self._busy_overlay.raise_()

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
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)  # >>> added
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)  # >>> added
    app = QtWidgets.QApplication(sys.argv)  # >>> changed
    window = VisualApp()  # >>> changed
    apply_theme(app, "light")  # >>> added
    window.show()  # >>> changed
    sys.exit(app.exec_())  # >>> changed


if __name__ == "__main__":  # pragma: no cover - script entry
    main()
