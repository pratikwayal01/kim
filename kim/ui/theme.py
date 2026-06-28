"""
theme.py — Application-wide QSS stylesheet for the kim Qt UI.

Design language: clean, neutral, modern flat (IBM Carbon-inspired light).
Apply once via QApplication.setStyleSheet(KIM_STYLESHEET).
"""

# ---------------------------------------------------------------------------
# Colour tokens
# ---------------------------------------------------------------------------
# Background layers
_BG0 = "#f4f4f4"  # app / window background
_BG1 = "#ffffff"  # widget fill (inputs, tables, panels)
_BG2 = "#e8e8e8"  # subtle secondary fill (toolbar, groupbox bg)
_BG_HOVER = "#e0e0e0"  # hover state
_BG_PRESS = "#c6c6c6"  # pressed state

# Borders
_BORDER = "#c6c6c6"
_BORDER_FOCUS = "#0f62fe"

# Text
_TEXT = "#161616"
_TEXT_SUB = "#525252"
_TEXT_DISABLED = "#8d8d8d"
_TEXT_ON_PRIMARY = "#ffffff"

# Accent (IBM Carbon Interactive Blue)
_ACCENT = "#0f62fe"
_ACCENT_HOVER = "#0353e9"
_ACCENT_PRESS = "#002d9c"

# Status / urgency
_OK = "#198038"
_WARN = "#f1c21b"
_ERROR = "#da1e28"

# Selection
_SEL_BG = "#d0e2ff"
_SEL_TEXT = "#001d6c"

# Table alternating
_ROW_ALT = "#f4f4f4"

# Tab
_TAB_ACTIVE_BG = "#ffffff"
_TAB_INACTIVE_BG = "#e8e8e8"
_TAB_ACTIVE_BORDER = _ACCENT

# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

KIM_STYLESHEET = f"""

/* ── Global ─────────────────────────────────────────────────────────── */

QWidget {{
    background-color: {_BG0};
    color: {_TEXT};
    font-size: 13px;
}}

QMainWindow {{
    background-color: {_BG0};
}}

/* ── Toolbar ─────────────────────────────────────────────────────────── */

QToolBar {{
    background-color: {_BG1};
    border: none;
    border-bottom: 1px solid {_BORDER};
    spacing: 2px;
    padding: 3px 6px;
}}

QToolBar::separator {{
    width: 1px;
    background-color: {_BORDER};
    margin: 4px 4px;
}}

QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px 10px;
    color: {_TEXT};
    font-size: 13px;
    min-width: 36px;
}}

QToolButton:hover {{
    background-color: {_BG_HOVER};
    border-color: {_BORDER};
}}

QToolButton:pressed {{
    background-color: {_BG_PRESS};
}}

QToolButton:disabled {{
    color: {_TEXT_DISABLED};
}}

/* ── Tab bar ─────────────────────────────────────────────────────────── */

QTabWidget::pane {{
    border: 1px solid {_BORDER};
    border-top: none;
    background-color: {_BG1};
}}

QTabBar::tab {{
    background-color: {_TAB_INACTIVE_BG};
    color: {_TEXT_SUB};
    border: 1px solid {_BORDER};
    border-bottom: none;
    padding: 7px 20px;
    margin-right: 2px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    background-color: {_TAB_ACTIVE_BG};
    color: {_TEXT};
    border-bottom: 2px solid {_TAB_ACTIVE_BORDER};
    font-weight: 600;
}}

QTabBar::tab:hover:!selected {{
    background-color: {_BG_HOVER};
    color: {_TEXT};
}}

/* ── Tables ──────────────────────────────────────────────────────────── */

QTableWidget {{
    background-color: {_BG1};
    alternate-background-color: {_ROW_ALT};
    gridline-color: transparent;
    border: none;
    font-size: 13px;
    selection-background-color: {_SEL_BG};
    selection-color: {_SEL_TEXT};
    outline: none;
}}

QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}

QTableWidget::item:selected {{
    background-color: {_SEL_BG};
    color: {_SEL_TEXT};
}}

QHeaderView {{
    background-color: {_BG1};
    border: none;
}}

QHeaderView::section {{
    background-color: {_BG0};
    color: {_TEXT_SUB};
    border: none;
    border-bottom: 1px solid {_BORDER};
    border-right: 1px solid {_BORDER};
    padding: 5px 8px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

QHeaderView::section:last {{
    border-right: none;
}}

/* ── Status bar ──────────────────────────────────────────────────────── */

QStatusBar {{
    background-color: {_BG1};
    border-top: 1px solid {_BORDER};
    color: {_TEXT_SUB};
    font-size: 12px;
    padding: 2px 8px;
}}

QStatusBar::item {{
    border: none;
}}

/* ── Push buttons ────────────────────────────────────────────────────── */

QPushButton {{
    background-color: {_BG2};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    padding: 5px 16px;
    font-size: 13px;
    min-width: 72px;
}}

QPushButton:hover {{
    background-color: {_BG_HOVER};
    border-color: {_TEXT_DISABLED};
}}

QPushButton:pressed {{
    background-color: {_BG_PRESS};
}}

QPushButton:disabled {{
    color: {_TEXT_DISABLED};
    background-color: {_BG2};
    border-color: {_BORDER};
}}

/* Primary (OK / Save / Schedule) buttons in dialog button boxes */
QDialogButtonBox QPushButton[text="OK"],
QDialogButtonBox QPushButton[text="Save"],
QDialogButtonBox QPushButton[text="Schedule"] {{
    background-color: {_ACCENT};
    color: {_TEXT_ON_PRIMARY};
    border-color: {_ACCENT};
}}

QDialogButtonBox QPushButton[text="OK"]:hover,
QDialogButtonBox QPushButton[text="Save"]:hover,
QDialogButtonBox QPushButton[text="Schedule"]:hover {{
    background-color: {_ACCENT_HOVER};
    border-color: {_ACCENT_HOVER};
}}

QDialogButtonBox QPushButton[text="OK"]:pressed,
QDialogButtonBox QPushButton[text="Save"]:pressed,
QDialogButtonBox QPushButton[text="Schedule"]:pressed {{
    background-color: {_ACCENT_PRESS};
    border-color: {_ACCENT_PRESS};
}}

/* ── Line edits / inputs ─────────────────────────────────────────────── */

QLineEdit, QTimeEdit, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {_BG1};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
    selection-background-color: {_SEL_BG};
    selection-color: {_SEL_TEXT};
}}

QLineEdit:focus, QTimeEdit:focus, QDateEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {_BORDER_FOCUS};
    outline: none;
}}

QLineEdit:disabled, QTimeEdit:disabled, QDateEdit:disabled {{
    background-color: {_BG0};
    color: {_TEXT_DISABLED};
}}

QLineEdit::placeholder {{
    color: {_TEXT_DISABLED};
}}

/* ── Combo box ───────────────────────────────────────────────────────── */

QComboBox {{
    background-color: {_BG1};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 13px;
    min-width: 80px;
}}

QComboBox:focus {{
    border-color: {_BORDER_FOCUS};
}}

QComboBox:hover {{
    border-color: {_TEXT_DISABLED};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: right center;
    width: 22px;
    border-left: 1px solid {_BORDER};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}

QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-style: solid;
    border-width: 5px 4px 0 4px;
    border-color: {_TEXT_SUB} transparent transparent transparent;
}}

QComboBox QAbstractItemView {{
    background-color: {_BG1};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    selection-background-color: {_SEL_BG};
    selection-color: {_SEL_TEXT};
    outline: none;
    padding: 2px;
}}

/* ── Group box ───────────────────────────────────────────────────────── */

QGroupBox {{
    background-color: {_BG1};
    border: 1px solid {_BORDER};
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 8px;
    font-size: 12px;
    font-weight: 600;
    color: {_TEXT_SUB};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: -1px;
    padding: 0 4px;
    background-color: {_BG0};
    color: {_TEXT_SUB};
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* ── Checkboxes & radio buttons ──────────────────────────────────────── */

QCheckBox, QRadioButton {{
    color: {_TEXT};
    font-size: 13px;
    spacing: 6px;
    background-color: transparent;
}}

QCheckBox:disabled, QRadioButton:disabled {{
    color: {_TEXT_DISABLED};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {_BORDER};
    border-radius: 3px;
    background-color: {_BG1};
}}

QCheckBox::indicator:checked {{
    background-color: {_ACCENT};
    border-color: {_ACCENT};
}}

QCheckBox::indicator:hover {{
    border-color: {_BORDER_FOCUS};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {_BORDER};
    border-radius: 8px;
    background-color: {_BG1};
}}

QRadioButton::indicator:checked {{
    background-color: {_ACCENT};
    border-color: {_ACCENT};
}}

QRadioButton::indicator:hover {{
    border-color: {_BORDER_FOCUS};
}}

/* ── Plain text / log viewer ─────────────────────────────────────────── */

QPlainTextEdit, QTextEdit {{
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid {_BORDER};
    border-radius: 4px;
    font-size: 12px;
    padding: 4px;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}}

/* ── Scroll bars ─────────────────────────────────────────────────────── */

QScrollBar:vertical {{
    background-color: transparent;
    width: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: {_BORDER};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {_TEXT_DISABLED};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: transparent;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background-color: {_BORDER};
    border-radius: 4px;
    min-width: 24px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {_TEXT_DISABLED};
}}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Dialog ──────────────────────────────────────────────────────────── */

QDialog {{
    background-color: {_BG0};
}}

/* ── Message boxes ───────────────────────────────────────────────────── */

QMessageBox {{
    background-color: {_BG0};
}}

/* ── Labels ──────────────────────────────────────────────────────────── */

QLabel {{
    background-color: transparent;
    color: {_TEXT};
}}

/* ── Spin box arrows ─────────────────────────────────────────────────── */

QTimeEdit::up-button, QDateEdit::up-button,
QSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {_BORDER};
    border-bottom: 1px solid {_BORDER};
    border-top-right-radius: 4px;
    background-color: {_BG0};
}}

QTimeEdit::down-button, QDateEdit::down-button,
QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid {_BORDER};
    border-bottom-right-radius: 4px;
    background-color: {_BG0};
}}

QTimeEdit::up-button:hover, QDateEdit::up-button:hover,
QSpinBox::up-button:hover,
QTimeEdit::down-button:hover, QDateEdit::down-button:hover,
QSpinBox::down-button:hover {{
    background-color: {_BG_HOVER};
}}

"""  # noqa: E501
