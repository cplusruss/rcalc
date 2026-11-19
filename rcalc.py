"""
rcalc - comprehensive RF calculation toolkit.

Tabs of live calculators. Type in any field, others recompute instantly.
Ctrl+Space (or Ctrl+F) opens a fuzzy finder over every field in every tab -
type a few letters, hit Enter, jump straight into the field ready to type a number.

Run:  C:\\Python\\313\\python.exe rf_converter.py
"""

import ctypes
import ctypes.wintypes
import itertools
import json
import math
import os
import re
import sys
from math import atan, erfc, exp, floor, log, log2, log10, pi, sqrt

from PyQt5.QtCore import (
    QEvent, QPoint, QPointF, QRectF, QSize, Qt, QStringListModel,
    QTimer, pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontDatabase, QFontMetrics, QFontMetricsF,
    QIcon, QKeySequence, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QPolygon, QPolygonF, QRadialGradient, QSyntaxHighlighter,
    QTextCharFormat,
)
from PyQt5.QtWidgets import (
    QAbstractButton, QAbstractItemView, QAction, QApplication, QButtonGroup,
    QCheckBox, QColorDialog, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFontDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMenuBar, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QShortcut,
    QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyleFactory,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
    qDrawWinPanel,
)

# Optional plotting / RF libraries — Smith chart tab degrades gracefully
# if not installed.  We force the Qt5Agg backend BEFORE importing pyplot
# transitively (skrf pulls in pyplot) so the canvas always lands in our Qt
# event loop instead of an Agg-only headless backend.
try:
    import matplotlib
    matplotlib.use("Qt5Agg", force=True)
    import numpy as np
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import skrf as rf
    HAS_SMITH = True
    _smith_err = None
except Exception as _e:
    HAS_SMITH = False
    _smith_err = repr(_e)

__version__ = "0.1.0"

# a one-file exe unpacks to a temp folder deleted on exit: settings and
# user-supplied files live beside the exe instead
APP_DIR = os.path.dirname(
    sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
)

# ---------- physical constants ----------
C_LIGHT = 299_792_458.0           # m/s
K_BOLTZ = 1.380649e-23            # J/K
T0_REF  = 290.0                   # K (IEEE reference noise temp)
ETA0    = 376.730313668           # ohm (free-space impedance)
MU0     = 4 * pi * 1e-7           # H/m
NP2DB   = 8.685889638             # nepers/m → dB/m  (20·log10 e)
Z0      = 50.0                    # system impedance, fixed

# ---------- general physics constants ----------
H_PLANCK = 6.62607015e-34         # J·s
EV_TO_J  = 1.602176634e-19        # J/eV
R_GAS    = 8.314462618            # J/(mol·K)
G_EARTH  = 9.80665                # m/s²

# ---------- field background colours ----------
# Inputs go yellow only while focused; outputs are always green.  Defined as
# QColor instances at module load time so every CalcCard can reuse them.
FIELD_BG_INPUT_FOCUS = QColor(255, 247, 192)   # light yellow — active entry
FIELD_BG_INPUT_IDLE  = QColor(255, 255, 255)   # white       — idle input
FIELD_BG_SOLVED      = QColor(190, 214, 250)   # clear blue  — the solve-for target field

# ---------- theme (light / dark) ----------
THEME = "light"          # set by apply_theme()
DEFAULT_LENGTH_UNIT = "mm"   # length unit applied to every length field; user-configurable
DEFAULT_FREQ_UNIT   = "MHz"  # default unit for frequency I/O; user-configurable

# History-list styling for the Calc tab.  Populated from the JSON config
# at startup; CalcTab reads it via _apply_history_style_from_globals().
CALC_HISTORY_STYLE = {
    "font_family": None,    # None → keep widget's current font
    "font_size":   None,
    "fg":          None,    # None → inherit theme
    "bg":          None,
}

# Calc-tab intellisense (autocomplete popup) on/off.  Set from the JSON
# config at startup; a live CalcTab reads it into self._intellisense_enabled.
CALC_INTELLISENSE = True

# Allowed length units and conversion factors.  The basic invariant:
#       value_in_mm = value_in_unit  *  LENGTH_TO_MM[unit]
LENGTH_TO_MM = {
    "mm":  1.0,
    "cm":  10.0,
    "m":   1000.0,
    "mil": 0.0254,
    "in":  25.4,
    "ft":  304.8,
}
VALID_LENGTH_UNITS = tuple(LENGTH_TO_MM.keys())


def make_light_palette():
    from PyQt5.QtWidgets import QApplication
    return QApplication.style().standardPalette()


def make_dark_palette():
    """Deep-black variant of Windows Classic.  Backgrounds near #181818,
    inputs near pure black, text near white."""
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(24, 24, 24))     # was 45
    pal.setColor(QPalette.WindowText,      QColor(225, 225, 225))
    pal.setColor(QPalette.Base,            QColor(12, 12, 12))     # input bg
    pal.setColor(QPalette.AlternateBase,   QColor(28, 28, 28))
    pal.setColor(QPalette.ToolTipBase,     QColor(40, 40, 40))
    pal.setColor(QPalette.ToolTipText,     QColor(225, 225, 225))
    pal.setColor(QPalette.Text,            QColor(225, 225, 225))
    pal.setColor(QPalette.Button,          QColor(38, 38, 38))     # was 60
    pal.setColor(QPalette.ButtonText,      QColor(225, 225, 225))
    pal.setColor(QPalette.BrightText,      QColor(255, 100, 100))
    pal.setColor(QPalette.Link,            QColor(120, 180, 240))
    pal.setColor(QPalette.Highlight,       QColor(60, 100, 180))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.Disabled, QPalette.Text,       QColor(120, 120, 120))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(120, 120, 120))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    return pal


def apply_theme(app, theme):
    """Apply the light / dark theme palette and stylesheet to the app."""
    global THEME
    THEME = theme if theme in ("dark", "light") else "light"
    if THEME == "dark":
        app.setPalette(make_dark_palette())
        # The Windows Classic style ignores QPalette.Base/Text for editable
        # widgets; we need explicit QSS to make text actually visible.
        app.setStyleSheet(
            "QToolTip { color:#e0e0e0; background:#2a2a2a; border:1px solid #444; } "
            "QMenuBar { background:#1a1a1a; color:#e0e0e0; } "
            "QMenuBar::item:selected { background:#3a4a70; } "
            "QMenu { background:#1a1a1a; color:#e0e0e0; border:1px solid #333; } "
            "QMenu::item:selected { background:#3a4a70; } "
            "QStatusBar { background:#1a1a1a; color:#aaa; } "
            "QTabWidget::pane { background:#181818; border:1px solid #333; } "
            "QTabBar::tab { background:#222; color:#ccc; padding:4px 10px; "
                          "border:1px solid #333; border-bottom:none; } "
            "QTabBar::tab:selected { background:#181818; color:#fff; } "
            "QGroupBox { color:#e0e0e0; } "
            "QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox { "
                "background:#0c0c0c; color:#e1e1e1; border:1px solid #333; "
                "selection-background-color:#3c5e92; selection-color:#fff; } "
            "QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#777; } "
            "QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, "
            "QSpinBox:focus, QDoubleSpinBox:focus { border:1px solid #4a6e9c; } "
            "QComboBox { background:#1a1a1a; color:#e1e1e1; border:1px solid #333; } "
            "QComboBox QAbstractItemView { background:#181818; color:#e1e1e1; "
                "selection-background-color:#3c5e92; } "
            "QListWidget, QTreeWidget, QTableWidget { background:#181818; color:#e1e1e1; "
                "gridline-color:#2c2c2c; } "
            "QHeaderView::section { background:#222; color:#e1e1e1; "
                "border:1px solid #333; padding:2px 4px; } "
            "QTableCornerButton::section { background:#222; border:1px solid #333; } "
            "QPushButton { background:#262626; color:#e1e1e1; border:1px solid #3a3a3a; "
                "padding:3px 8px; } "
            "QPushButton:hover { background:#303030; } "
            "QPushButton:pressed { background:#1c1c1c; } "
            "QPushButton:disabled { color:#666; border-color:#2a2a2a; } "
            "QCheckBox, QRadioButton { color:#e1e1e1; } "
            "QScrollArea { background:#181818; }"
        )
    else:
        app.setPalette(make_light_palette())
        app.setStyleSheet("")


# ---------- local JSON config (window geometry, last tab) ----------
CONFIG_PATH = os.path.join(APP_DIR, "rcalc.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass


# ---------- periodic-table data (pre-baked from mendeleev) ----------
# See `temp/bake_periodic.py` to regenerate `resource/periodic_data.py`
# when a new element is added.  Loading via spec_from_file_location
# avoids needing an __init__.py in resource/.
def _load_periodic_data():
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "resource", "periodic_data.py")
        if not os.path.exists(path):
            return []
        spec = importlib.util.spec_from_file_location("_periodic", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return list(getattr(mod, "ELEMENTS", []))
    except Exception:
        return []


PERIODIC_ELEMENTS = _load_periodic_data()


# ---------- mechanical reference data ----------
def _load_mechanical_data():
    try:
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "resource", "mechanical_data.py")
        if not os.path.exists(path):
            return None
        spec = importlib.util.spec_from_file_location("_mech", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


MECH_DATA = _load_mechanical_data()


# ---------- helpers ----------
def fmt(v):
    """Format a float compactly without trailing zero noise."""
    if v is None:
        return ""
    if not math.isfinite(v):
        return ""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e9 or a < 1e-4:
        return f"{v:.6g}"
    return f"{v:.6g}"


def parse(text):
    """Parse a number, returning None if invalid. Accepts engineering suffixes like '2k', '5M', '3.3G', '100m', '50u', '10n', '2p'."""
    if text is None:
        return None
    s = text.strip().replace(",", "")
    if not s:
        return None
    suff = {"T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
            "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    mult = 1.0
    if s and s[-1] in suff:
        mult = suff[s[-1]]
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


# --------------------------------------------------------------------
#  Unit registry — used for "the user typed an SI prefix, so renormalise
#  to the field's display unit instead of multiplying blindly".
#
#  Each entry maps the display-unit string to (base_unit_name, scale).
#  scale = factor that converts from the display unit to the base unit:
#       value_in_base = value_in_display * scale
#  When a typed value ends in a known SI prefix character, the parser
#  treats the post-suffix value as already-in-the-base-unit, then divides
#  by `scale` so the field-level math sees the value in the field's unit.
# --------------------------------------------------------------------
UNIT_REGISTRY = {
    # Frequency (base = Hz)
    "Hz":  ("Hz", 1.0),
    "kHz": ("Hz", 1e3),
    "MHz": ("Hz", 1e6),
    "GHz": ("Hz", 1e9),
    "THz": ("Hz", 1e12),
    # Time (base = s)
    "s":   ("s",  1.0),
    "ms":  ("s",  1e-3),
    "µs":  ("s",  1e-6),
    "us":  ("s",  1e-6),
    "ns":  ("s",  1e-9),
    "ps":  ("s",  1e-12),
    "fs":  ("s",  1e-15),
    # Length (base = m)
    "m":   ("m",  1.0),
    "km":  ("m",  1e3),
    "cm":  ("m",  1e-2),
    "mm":  ("m",  1e-3),
    "µm":  ("m",  1e-6),
    "um":  ("m",  1e-6),
    # Power (base = W)
    "W":   ("W",  1.0),
    "kW":  ("W",  1e3),
    "MW":  ("W",  1e6),
    "mW":  ("W",  1e-3),
    "µW":  ("W",  1e-6),
    "uW":  ("W",  1e-6),
    "nW":  ("W",  1e-9),
    # Voltage (base = V)
    "V":   ("V",  1.0),
    "kV":  ("V",  1e3),
    "mV":  ("V",  1e-3),
    "µV":  ("V",  1e-6),
    "uV":  ("V",  1e-6),
    # Current (base = A)
    "A":   ("A",  1.0),
    "mA":  ("A",  1e-3),
    "µA":  ("A",  1e-6),
    "uA":  ("A",  1e-6),
    "kA":  ("A",  1e3),
    # Resistance (base = Ω)
    "Ω":   ("Ω",  1.0),
    "mΩ":  ("Ω",  1e-3),
    "kΩ":  ("Ω",  1e3),
    "MΩ":  ("Ω",  1e6),
    # Capacitance (base = F)
    "F":   ("F",  1.0),
    "mF":  ("F",  1e-3),
    "µF":  ("F",  1e-6),
    "uF":  ("F",  1e-6),
    "nF":  ("F",  1e-9),
    "pF":  ("F",  1e-12),
    # Inductance (base = H)
    "H":   ("H",  1.0),
    "mH":  ("H",  1e-3),
    "µH":  ("H",  1e-6),
    "uH":  ("H",  1e-6),
    "nH":  ("H",  1e-9),
    "pH":  ("H",  1e-12),
}

# All single-character SI prefixes that parse() recognises.
_SI_PREFIX_CHARS = "TGMkKmunpfµ"


def parse_field(text, unit):
    """Parse `text` for a field whose label is `unit`.  If the typed value
    ends in an SI prefix and `unit` is in UNIT_REGISTRY, the value is
    interpreted as already-in-the-base-unit and divided down to the field's
    unit so the surrounding formula still sees a number in its native scale.

    Examples (field unit = "MHz"):
        "10"     -> 10.0       (plain number → MHz directly)
        "10G"    -> 10000.0    (10 GHz, expressed as MHz)
        "100k"   -> 0.1        (100 kHz, expressed as MHz)
    """
    if text is None:
        return None
    s = text.strip().replace(",", "")
    if not s:
        return None
    last = s[-1]
    used_suffix = last in _SI_PREFIX_CHARS
    v = parse(s)                          # delegate base parsing
    if v is None:
        return None
    if used_suffix and unit in UNIT_REGISTRY:
        _base, scale = UNIT_REGISTRY[unit]
        v = v / scale                     # base-unit value → field unit
    return v


def base_unit_name(unit):
    """Return the SI base-unit name for a registered display unit
    (e.g. base_unit_name('MHz') == 'Hz'), or None for unknown units."""
    info = UNIT_REGISTRY.get(unit)
    return info[0] if info else None


def Q_func(x):
    """Q-function = 0.5 * erfc(x/sqrt(2))."""
    return 0.5 * erfc(x / sqrt(2.0))


def db_to_lin(db):
    return 10 ** (db / 10.0)


def lin_to_db(x):
    if x is None or x <= 0:
        return None
    return 10.0 * log10(x)


# ---------- field + card framework ----------
class ClickableUnitLabel(QLabel):
    """A QLabel whose unit text is clickable.  Emits the global mouse
    position so the receiver can pop a quick-select menu next to the
    cursor."""
    clicked = pyqtSignal(QPoint)   # emits global cursor position on left-click

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(ev.globalPos())
            ev.accept()
            return
        super().mousePressEvent(ev)


class Field:
    """Metadata for one input/output line in a card.

    `declared_unit` is the unit the card's `compute()` was *coded* for
    (e.g. MHz for `f_mhz`).  `unit` is the unit currently shown to the
    user — the two diverge if the user picks a different display unit
    via the quick-select popup, in which case CalcCard's I/O boundary
    converts between them so compute() always sees its declared unit."""

    __slots__ = ("name", "label", "unit", "declared_unit", "edit",
                 "label_widget", "unit_label", "is_output", "card")

    def __init__(self, name, label, unit="", is_output=False):
        self.name = name
        self.label = label
        self.unit = unit
        self.declared_unit = unit          # never changes after construction
        self.is_output = is_output
        self.edit = None
        self.label_widget = None
        self.unit_label = None
        self.card = None


class CalcCard(QWidget):
    """A calculator section.  Renders as:

        ▼ Title of region ────────────────────────────
            label: [edit] unit
            label: [edit] unit                [diagram]
            ...

    Click the header row to collapse/expand the body.  No groupbox
    border — the section header (chevron + bold title + horizontal
    line) is the only visual separator.  Subclasses override compute()."""

    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self._title = title
        self._updating = False
        self._collapsed = False
        self._body_widget = None      # set in _build_ui
        self._title_label = None      # set in _build_ui
        self.fields = {f.name: f for f in fields}
        for f in self.fields.values():
            f.card = self
        self._build_ui()

    def title(self):
        """Compatibility shim — used by the fuzzy finder's search index."""
        return self._title

    # ------- collapsible header -------
    def set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed and self._body_widget is not None:
            # still re-apply visibility in case the body got toggled by another path
            self._body_widget.setVisible(not collapsed)
        self._collapsed = collapsed
        if self._body_widget is not None:
            self._body_widget.setVisible(not collapsed)
        if self._title_label is not None:
            self._title_label.setText(self._formatted_title())

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def _formatted_title(self):
        return ("►  " if self._collapsed else "▼  ") + self._title

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 4, 2, 4)
        outer.setSpacing(3)

        # ---- header: chevron + bold title + horizontal line filling the rest ----
        header_widget = _HeaderRow(self)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title_lbl = QLabel(self._formatted_title())
        title_lbl.setStyleSheet("font-weight: bold;")
        title_lbl.setCursor(Qt.PointingHandCursor)
        self._title_label = title_lbl
        header.addWidget(title_lbl, 0)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        header.addWidget(line, 1)
        outer.addWidget(header_widget)

        # ---- body wrapper (so we can hide it on collapse) ----
        body_widget = QWidget()
        diagram_above = bool(getattr(self, "_diagram_above", False))
        diagram_below = bool(getattr(self, "_diagram_below", False))
        if diagram_above or diagram_below:
            # Diagram stacks above (or below) the field grid — used when a
            # wide chart / datagrid needs the full card width.
            body = QVBoxLayout(body_widget)
        else:
            body = QHBoxLayout(body_widget)
        body.setContentsMargins(10, 0, 0, 0)
        body.setSpacing(8)

        fields_w = QWidget()
        fv = QVBoxLayout(fields_w)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(2)

        extras = self.make_extras()
        if extras is not None:
            fv.addWidget(extras)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(1)
        # Opt-in two-column field grid: inputs in the left (label/edit/unit)
        # triple, outputs in the right triple, so a tall card is half as high.
        # Off by default — `_two_col_fields = True` on a subclass enables it.
        two_col = bool(getattr(self, "_two_col_fields", False))
        edit_min, edit_max = (70, 92) if two_col else (90, 140)

        def _place_field(f, row, base):
            lab = QLabel(f.label + ":")
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            edit = QLineEdit()
            edit.setMinimumWidth(edit_min)
            edit.setMaximumWidth(edit_max)
            edit.setMaximumHeight(18)
            if not f.is_output:
                # Light yellow on focus = "this is what you're typing into";
                # white otherwise.  Tracked through a focus event filter on
                # the card itself (see CalcCard.eventFilter).
                # Output fields keep the default background — the green
                # shading was removed at user request.
                edit.installEventFilter(self)
            edit.textEdited.connect(lambda txt, name=f.name: self._on_edit(name, txt))
            edit.textChanged.connect(self._refresh_figure)
            unit = ClickableUnitLabel(f.unit)
            unit.setStyleSheet("color: #555;")
            unit.clicked.connect(lambda pos, ff=f: self._on_unit_label_clicked(ff, pos))
            f.edit = edit
            f.label_widget = lab
            f.unit_label = unit
            grid.addWidget(lab, row, base)
            grid.addWidget(edit, row, base + 1)
            grid.addWidget(unit, row, base + 2)

        if two_col:
            inputs = [f for f in self.fields.values() if not f.is_output]
            outputs = [f for f in self.fields.values() if f.is_output]
            for i, f in enumerate(inputs):
                _place_field(f, i, 0)
            for j, f in enumerate(outputs):
                _place_field(f, j, 4)
            grid.setColumnMinimumWidth(3, 18)   # gutter between the two triples
        else:
            for row, f in enumerate(self.fields.values()):
                _place_field(f, row, 0)
        diag = self.make_diagram()
        self._has_diagram = diag is not None
        # A Figure reads this card's values at paint time; field edits and
        # recomputes call _refresh_figure.
        self._figure = diag if isinstance(diag, CardFigure) else None
        if self._figure is not None and self._figure.card is None:
            self._figure.card = self
        if diag is None:
            grid.setColumnStretch(2, 1)
        fv.addWidget(grid_w)

        extras_below = self.make_extras_below()
        if extras_below is not None:
            fv.addWidget(extras_below)

        # fields_w never grows vertically — its height = sizeHint.  Without
        # this, when a sibling diagram on the right is taller than the
        # column of fields, fields_w stretches to match and the QGridLayout
        # inside spaces its rows apart.
        fields_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if diagram_above and diag is not None:
            # `_diagram_full_width = True` lets the diagram stretch
            # horizontally (used by the Bands tab so the chart and
            # datagrid span the application window).  Without it the
            # default AlignLeft flag pins the diagram to its sizeHint.
            if getattr(self, "_diagram_full_width", False):
                # Stretch=1 + no vertical alignment flag → diagram also
                # takes whatever vertical space the parent will give us,
                # so the Bands datagrid fills down to the bottom edge.
                body.addWidget(diag, 1)
            else:
                body.addWidget(diag, 0, Qt.AlignLeft | Qt.AlignTop)
            body.addWidget(fields_w, 0, Qt.AlignTop)
        elif diagram_below and diag is not None:
            body.addWidget(fields_w, 0, Qt.AlignTop)
            if getattr(self, "_diagram_full_width", False):
                body.addWidget(diag, 1)
            else:
                body.addWidget(diag, 0, Qt.AlignLeft | Qt.AlignTop)
        else:
            body.addWidget(fields_w, 0, Qt.AlignTop)
            if diag is not None:
                body.addWidget(diag, 0, Qt.AlignTop)
        # When the diagram is configured to take all available space,
        # there's nothing left to stretch into; the trailing addStretch
        # would force the BandTable above into its sizeHint instead.
        full_width_diag = bool(diag is not None
                               and getattr(self, "_diagram_full_width", False))
        if not ((diagram_above or diagram_below) and full_width_diag):
            body.addStretch(1)
        outer.addWidget(body_widget)
        self._body_widget = body_widget
        # Exposed so build_tab() can pin every card's field column to the
        # same width — that keeps diagrams (e.g. on the TLines tab) lined
        # up vertically across the column.
        self._fields_widget = fields_w
        # A trailing stretch absorbs any extra vertical space the grid cell
        # gives this card (because a sibling card on the same row has more
        # fields).  Without it, QVBoxLayout would distribute the slack
        # *between* rows and the field spacing would drift between cards.
        outer.addStretch(1)


    def eventFilter(self, obj, ev):
        """Light-yellow background on the input the user is currently typing
        into; revert to white when focus leaves.  Output fields are skipped —
        they are coloured green once at construction and stay that way."""
        if isinstance(obj, QLineEdit):
            t = ev.type()
            if t == QEvent.FocusIn:
                pal = obj.palette()
                pal.setColor(QPalette.Base, FIELD_BG_INPUT_FOCUS)
                obj.setPalette(pal)
            elif t == QEvent.FocusOut:
                pal = obj.palette()
                pal.setColor(QPalette.Base, self._idle_field_bg(obj))
                obj.setPalette(pal)
        return super().eventFilter(obj, ev)

    def _idle_field_bg(self, edit):
        """Background to restore when an input loses focus.  Subclasses
        override to keep a persistent highlight (e.g. the solve-for target
        on TLine cards)."""
        return FIELD_BG_INPUT_IDLE

    def make_diagram(self):
        """Override to return a QWidget shown on the right side of the card."""
        return None

    def make_extras(self):
        """Override to return a QWidget shown above the field grid (e.g. a
        material / unit / 'solve for' selector row)."""
        return None

    def make_extras_below(self):
        """Override to return a QWidget shown *below* the field grid (e.g. an
        action button row that shouldn't widen the control column)."""
        return None

    # ----- card-level state for persistence (collapse, selectors, units, …) -----
    def get_card_state(self):
        return {"collapsed": self._collapsed} if self._collapsed else {}

    def set_card_state(self, state):
        if isinstance(state, dict):
            self.set_collapsed(bool(state.get("collapsed", False)))

    def _collect(self):
        out = {}
        for name, f in self.fields.items():
            v = parse_field(f.edit.text(), f.unit)
            out[name] = self._to_declared(v, f)
        return out

    @staticmethod
    def _to_declared(value, field):
        """Convert a value parsed in the field's *display* unit into the
        unit the card's compute() was written for.  No-op when display ==
        declared, when either is unregistered, or when value isn't numeric."""
        if value is None or field is None or not isinstance(value, (int, float)):
            return value
        if field.unit == field.declared_unit:
            return value
        if field.unit not in CALC_UNIT_TABLE or field.declared_unit not in CALC_UNIT_TABLE:
            return value
        try:
            cat_v = _calc_to_base(value, field.unit)
            if cat_v is None:
                return value
            return _calc_from_base(cat_v[1], field.declared_unit)
        except Exception:
            return value

    @staticmethod
    def _to_display(value, field):
        """Inverse of `_to_declared` — used when writing a compute() result
        back into a field whose display unit differs from declared."""
        if value is None or field is None or not isinstance(value, (int, float)):
            return value
        if field.unit == field.declared_unit:
            return value
        if field.unit not in CALC_UNIT_TABLE or field.declared_unit not in CALC_UNIT_TABLE:
            return value
        try:
            cat_v = _calc_to_base(value, field.declared_unit)
            if cat_v is None:
                return value
            return _calc_from_base(cat_v[1], field.unit)
        except Exception:
            return value

    @staticmethod
    def _format_for_field(val, field=None):
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        # Ω-labelled fields read in engineering units: 10k, 2k, 1.02M —
        # never 10000 or 1.02e+06.  parse_field() reads the suffix back.
        if field is not None and field.unit == "Ω":
            a = abs(val)
            if a >= 1e6:
                return f"{val / 1e6:.6g}M"
            if a >= 1e3:
                return f"{val / 1e3:.6g}k"
        return fmt(val)

    def _maybe_relabel_unit(self, field, raw_text):
        """If the typed value ends in an SI prefix and the field's unit has a
        registered base, swap the unit label to that base (e.g. MHz → Hz) so
        '10G' in a MHz field reads unambiguously as '10G Hz' = 10 GHz.
        Restores the original label when no prefix is typed."""
        if field is None or field.unit_label is None:
            return
        if field.unit not in UNIT_REGISTRY:
            return
        base, _scale = UNIT_REGISTRY[field.unit]
        s = (raw_text or "").strip()
        used_suffix = bool(s) and s[-1] in _SI_PREFIX_CHARS
        desired = base if used_suffix and base != field.unit else field.unit
        if field.unit_label.text() != desired:
            field.unit_label.setText(desired)

    def _on_edit(self, driver, text):
        if self._updating:
            return
        field = self.fields.get(driver)
        self._maybe_relabel_unit(field, text)
        # Parse in display unit, then push through to declared unit so
        # compute() sees the value in the unit it was coded for.
        v_disp = parse_field(text, field.unit if field else "")
        v_decl = self._to_declared(v_disp, field) if field else v_disp
        vals = self._collect()
        vals[driver] = v_decl
        try:
            results = self.compute(driver, vals)
        except Exception:
            results = None
        if not results:
            return
        self._updating = True
        try:
            for k, val in results.items():
                if k == driver:
                    continue
                f = self.fields.get(k)
                if not f:
                    continue
                # Result is in declared unit; convert to current display unit.
                val_disp = self._to_display(val, f)
                f.edit.setText(self._format_for_field(val_disp, f))
                # The new value we just stamped in won't have an SI prefix,
                # so make sure any earlier suffix-relabel on that field
                # gets reverted.
                self._maybe_relabel_unit(f, f.edit.text())
        finally:
            self._updating = False

    # ------------------------------------------------------------------
    # Quick-select unit picker — pops up next to a clicked unit label.
    # ------------------------------------------------------------------
    def _on_unit_label_clicked(self, field, global_pos):
        if field is None or not field.unit:
            return
        cat = _calc_unit_category(field.unit)
        if cat is None:
            return
        choices = CALC_CATEGORY_UNITS.get(cat, [])
        if not choices:
            return
        menu = QMenu(self)
        for u in choices:
            if u == field.unit:
                act = menu.addAction(f"{u}   (current)")
                act.setEnabled(False)
            else:
                act = menu.addAction(u)
                act.triggered.connect(
                    lambda _checked=False, ff=field, uu=u: self._switch_field_unit(ff, uu))
        menu.exec_(global_pos)

    def _switch_field_unit(self, field, new_unit):
        """Quick-select on a unit label.  Changes the *display* unit only —
        `field.declared_unit` stays at its original value so the card's
        compute() keeps seeing values in the unit it was coded for, and
        CalcCard's I/O boundary (`_to_declared` / `_to_display`) does the
        conversion automatically.

        Cards with shared-unit dimension fields (TLineCard /
        RectangularCavityCard) override this to cascade the change across
        every length field at once."""
        if field is None or new_unit == field.unit:
            return
        old_unit = field.unit
        if field.edit is not None:
            txt = field.edit.text().strip()
            if txt:
                # parse_field handles the case where the field already
                # contains an SI-prefixed value like "10G" — the parsed
                # number comes back in `old_unit` regardless.
                v = parse_field(txt, old_unit)
                if v is not None:
                    try:
                        cat_v = _calc_to_base(v, old_unit)
                        if cat_v is not None:
                            new_v = _calc_from_base(cat_v[1], new_unit)
                            field.edit.blockSignals(True)
                            field.edit.setText(fmt(new_v))
                            field.edit.blockSignals(False)
                    except Exception:
                        pass
        field.unit = new_unit
        if field.unit_label is not None:
            field.unit_label.setText(new_unit)
        # Recompute through the new I/O boundary — the card's compute()
        # will receive `field`'s value re-converted to declared_unit.
        self.recompute_from_inputs()

    def _refresh_figure(self, *_):
        fig = getattr(self, "_figure", None)
        if fig is not None:
            fig.update()

    def recompute_from_inputs(self):
        """Recompute outputs from current inputs (used when Z0 or a card-level
        selector changes)."""
        self._refresh_figure()
        vals = self._collect()
        for name, val in vals.items():
            if val is not None and not self.fields[name].is_output:
                try:
                    results = self.compute(name, vals)
                except Exception:
                    results = None
                if results:
                    self._updating = True
                    try:
                        for k, v in results.items():
                            if k == name:
                                continue
                            f = self.fields.get(k)
                            if not f:
                                continue
                            v_disp = self._to_display(v, f)
                            f.edit.setText(self._format_for_field(v_disp, f))
                    finally:
                        self._updating = False
                return

    def compute(self, driver, v):
        return {}

    # for fuzzy index
    def search_entries(self, tab_name):
        out = []
        for f in self.fields.values():
            label = f"{tab_name}  →  {self.title()}  →  {f.label}"
            if f.unit:
                label += f"  ({f.unit})"
            out.append((label, f.edit, self))
        return out


class _HeaderRow(QWidget):
    """Click-to-toggle wrapper around a CalcCard's title row."""
    def __init__(self, card):
        super().__init__(card)
        self._card = card
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._card.toggle_collapsed()
        super().mousePressEvent(ev)


# CompactCard used to render fields in a single horizontal row.  After the
# layout overhaul, every card uses the same "title + ─── line + stacked fields"
# style, so CompactCard is now just an alias kept for backwards compatibility
# with the Physics card subclasses below.
class CompactCard(CalcCard):
    pass


# ====================================================================
#  POWER / dB
# ====================================================================

class PowerWattsCard(CalcCard):
    def __init__(self):
        super().__init__("dBm ↔ dBW ↔ Watts", [
            Field("dbm", "dBm", "dBm"),
            Field("dbw", "dBW", "dBW"),
            Field("w",   "Watts", "W"),
            Field("mw",  "milliwatts", "mW"),
            Field("uw",  "microwatts", "µW"),
            Field("kw",  "kilowatts", "kW"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None:
            return {}
        try:
            if driver == "dbm": w = 10 ** ((x - 30) / 10)
            elif driver == "dbw": w = 10 ** (x / 10)
            elif driver == "w":  w = x
            elif driver == "mw": w = x * 1e-3
            elif driver == "uw": w = x * 1e-6
            elif driver == "kw": w = x * 1e3
            else: return {}
        except OverflowError:
            return {}
        if w <= 0:
            return {k: None for k in self.fields if k != driver}
        return {
            "dbm": 10 * log10(w * 1e3),
            "dbw": 10 * log10(w),
            "w": w, "mw": w * 1e3, "uw": w * 1e6, "kw": w * 1e-3,
        }


class PulsePowerCard(CalcCard):
    """duty = pulse width / period ;  P_peak = P_avg / duty"""
    def __init__(self):
        super().__init__("Pulse peak power  (P_pk = P_avg / duty)", [
            Field("pavg",     "P avg",       "W"),
            Field("pavg_dbm", "P avg",       "dBm"),
            Field("ppk",      "P peak",      "W"),
            Field("ppk_dbm",  "P peak",      "dBm"),
            Field("pw",       "Pulse width", "s"),
            Field("period",   "Period",      "s"),
            Field("duty",     "Duty",        "%"),
        ])

    def compute(self, driver, v):
        pw, T = v.get("pw"), v.get("period")
        d = v.get("duty"); d = d / 100.0 if d is not None else None
        pavg, ppk = v.get("pavg"), v.get("ppk")
        if driver == "pavg_dbm" and v.get("pavg_dbm") is not None:
            pavg = 10 ** ((v["pavg_dbm"] - 30) / 10)
        if driver == "ppk_dbm" and v.get("ppk_dbm") is not None:
            ppk = 10 ** ((v["ppk_dbm"] - 30) / 10)
        if driver == "duty" and d is not None and d > 0:
            if pw is not None and pw > 0:   T = pw / d      # keep pulse width
            elif T is not None and T > 0:   pw = T * d
        if pw is not None and T is not None and T > 0:
            d = pw / T
        if driver in ("ppk", "ppk_dbm") and ppk is not None and ppk > 0 and d is not None and d > 0:
            pavg = ppk * d
        if pavg is not None and d is not None and d > 0:
            ppk = pavg / d
        out = {}
        if pw   is not None: out["pw"]     = pw
        if T    is not None: out["period"] = T
        if d    is not None: out["duty"]   = d * 100.0
        if pavg is not None:
            out["pavg"] = pavg
            if pavg > 0: out["pavg_dbm"] = 10 * log10(pavg * 1e3)
        if ppk is not None:
            out["ppk"] = ppk
            if ppk > 0: out["ppk_dbm"] = 10 * log10(ppk * 1e3)
        return out


class DBRatioCard(CalcCard):
    def __init__(self):
        super().__init__("dB ratio (power & voltage)", [
            Field("db_p", "dB (power, 10 log)", "dB"),
            Field("ratio_p", "Power ratio (linear)", "x"),
            Field("db_v", "dB (voltage/field, 20 log)", "dB"),
            Field("ratio_v", "Voltage ratio (linear)", "x"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        try:
            if driver == "db_p":
                rp = 10 ** (x / 10); rv = sqrt(rp); db_v = 20 * log10(rv)
                return {"db_p": x, "ratio_p": rp, "ratio_v": rv, "db_v": db_v}
            if driver == "ratio_p":
                if x <= 0: return {}
                rv = sqrt(x); return {"db_p": 10*log10(x), "ratio_p": x, "ratio_v": rv, "db_v": 20*log10(rv)}
            if driver == "db_v":
                rv = 10 ** (x / 20); rp = rv * rv
                return {"db_v": x, "ratio_v": rv, "ratio_p": rp, "db_p": 10*log10(rp)}
            if driver == "ratio_v":
                if x <= 0: return {}
                rp = x * x; return {"ratio_v": x, "db_v": 20*log10(x), "ratio_p": rp, "db_p": 10*log10(rp)}
        except (OverflowError, ValueError):
            return {}
        return {}


class VoltageCard(CalcCard):
    """dBm <-> Vrms <-> Vp <-> Vpp <-> dBuV <-> dBmV  (depends on Z0)"""
    def __init__(self):
        super().__init__("dBm ↔ Vrms ↔ dBµV ↔ dBmV  (uses Z₀)", [
            Field("dbm",   "dBm", "dBm"),
            Field("vrms",  "Vrms", "V"),
            Field("vp",    "Vpeak", "V"),
            Field("vpp",   "Vpeak-peak", "V"),
            Field("dbuv",  "dBµV", "dBµV"),
            Field("dbmv",  "dBmV", "dBmV"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        try:
            if driver == "dbm":
                p_w = 10 ** ((x - 30) / 10); vrms = sqrt(p_w * Z0)
            elif driver == "vrms":
                if x < 0: return {}
                vrms = x
            elif driver == "vp":
                if x < 0: return {}
                vrms = x / sqrt(2)
            elif driver == "vpp":
                if x < 0: return {}
                vrms = x / (2 * sqrt(2))
            elif driver == "dbuv":
                vrms = 10 ** (x / 20) * 1e-6
            elif driver == "dbmv":
                vrms = 10 ** (x / 20) * 1e-3
            else:
                return {}
        except OverflowError:
            return {}
        if vrms < 0: return {}
        p_w = vrms * vrms / Z0 if Z0 > 0 else 0
        out = {
            "vrms": vrms,
            "vp":  vrms * sqrt(2),
            "vpp": vrms * 2 * sqrt(2),
            "dbuv": 20 * log10(vrms / 1e-6) if vrms > 0 else None,
            "dbmv": 20 * log10(vrms / 1e-3) if vrms > 0 else None,
            "dbm": 10 * log10(p_w * 1e3) if p_w > 0 else None,
        }
        return out


class PowerSumCard(CalcCard):
    """Add two powers in dBm (non-coherent sum)."""
    def __init__(self):
        super().__init__("Sum two powers (non-coherent)", [
            Field("p1", "P1", "dBm"),
            Field("p2", "P2", "dBm"),
            Field("psum", "Psum", "dBm", is_output=True),
            Field("delta", "P1 - Psum", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        p1, p2 = v.get("p1"), v.get("p2")
        if p1 is None or p2 is None:
            return {}
        w = 10 ** ((p1 - 30) / 10) + 10 ** ((p2 - 30) / 10)
        if w <= 0: return {}
        psum = 10 * log10(w * 1e3)
        return {"psum": psum, "delta": p1 - psum}


class SourceLoadCard(CalcCard):
    """Source [loss] → Load.

    Source: type in either dBm or W (linked).
    Loss: specify any one of dB, W, return-loss dB, VSWR — the other
    three follow.  Return-loss / VSWR enter the chain as mismatch loss
    ML = -10·log10(1 - |Γ|²).
    Load: dBm and W (read-only).
    """
    _diagram_above = True
    def __init__(self):
        super().__init__("Source  [loss]  →  Load", [
            Field("src_dbm",  "Source",      "dBm"),
            Field("src_w",    "Source",      "W"),
            Field("loss_db",  "Loss",        "dB"),
            Field("loss_w",   "Loss",        "W"),
            Field("rl_db",    "Return loss", "dB"),
            Field("vswr",     "VSWR",        ":1"),
            Field("load_dbm", "Load",        "dBm", is_output=True),
            Field("load_w",   "Load",        "W",   is_output=True),
        ])

    def _src_watts(self, driver, v):
        sd = v.get("src_dbm"); sw = v.get("src_w")
        if driver == "src_dbm" and sd is not None:
            return 10 ** ((sd - 30) / 10)
        if driver == "src_w" and sw is not None and sw > 0:
            return sw
        if sw is not None and sw > 0:
            return sw
        if sd is not None:
            return 10 ** ((sd - 30) / 10)
        return None

    @staticmethod
    def _ml_from_rho(rho):
        """Mismatch loss in dB given |Γ|."""
        if rho <= 0:
            return 0.0
        if rho >= 1:
            return None
        return -10 * log10(1 - rho * rho)

    def _loss_db(self, driver, v, src_w):
        ld = v.get("loss_db"); lw = v.get("loss_w")
        rl = v.get("rl_db");   vs = v.get("vswr")

        def from_rl(r):
            if r is None or r <= 0: return None
            rho = 10 ** (-r / 20)
            return self._ml_from_rho(rho)

        def from_vswr(s):
            if s is None or s < 1: return None
            rho = (s - 1) / (s + 1)
            return self._ml_from_rho(rho)

        def from_lw(w):
            if w is None or src_w is None or src_w <= 0: return None
            if w == 0: return 0.0
            if w < 0 or w >= src_w: return None
            return -10 * log10(1 - w / src_w)

        # the driver field decides which loss spec is canonical
        if driver == "loss_db":
            return ld if (ld is not None and ld >= 0) else None
        if driver == "loss_w":  return from_lw(lw)
        if driver == "rl_db":   return from_rl(rl)
        if driver == "vswr":    return from_vswr(vs)

        # source-driven (or any other driver): keep whichever loss
        # specification is still valid, in priority order.  loss_w is
        # last because it depends on the source level.
        if ld is not None and ld >= 0:
            return ld
        out = from_rl(rl)
        if out is not None: return out
        out = from_vswr(vs)
        if out is not None: return out
        return from_lw(lw)

    def make_diagram(self):
        return SourceLoadDiagram()

    def compute(self, driver, v):
        out = {}
        src_w = self._src_watts(driver, v)
        if src_w is not None and src_w > 0:
            out["src_w"]   = src_w
            out["src_dbm"] = 10 * log10(src_w * 1e3)

        loss_db = self._loss_db(driver, v, src_w)
        if loss_db is not None and loss_db >= 0:
            out["loss_db"] = loss_db
            try:
                rho_sq = 1 - 10 ** (-loss_db / 10)
            except OverflowError:
                rho_sq = 1.0
            if rho_sq <= 0:
                out["vswr"] = 1.0     # rl_db is "infinite" — leave blank
            elif rho_sq < 1:
                rho = sqrt(rho_sq)
                out["rl_db"] = -20 * log10(rho)
                out["vswr"] = (1 + rho) / (1 - rho)
            if src_w is not None and src_w > 0:
                atten = 10 ** (-loss_db / 10)
                load_w = src_w * atten
                out["loss_w"] = src_w - load_w
                out["load_w"] = load_w
                if load_w > 0:
                    out["load_dbm"] = 10 * log10(load_w * 1e3)
        return out


# ====================================================================
#  FREQUENCY / WAVELENGTH
# ====================================================================

class FreqWaveCard(CalcCard):
    def __init__(self):
        super().__init__("Frequency ↔ Wavelength ↔ Period (vacuum)", [
            Field("hz",  "Frequency", "Hz"),
            Field("khz", "Frequency", "kHz"),
            Field("mhz", "Frequency", "MHz"),
            Field("ghz", "Frequency", "GHz"),
            Field("lam_m",  "Wavelength", "m"),
            Field("lam_cm", "Wavelength", "cm"),
            Field("lam_mm", "Wavelength", "mm"),
            Field("lam_in", "Wavelength", "in"),
            Field("quarter_mm", "λ/4", "mm", is_output=True),
            Field("half_mm",    "λ/2", "mm", is_output=True),
            Field("period_ns",  "Period", "ns", is_output=True),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None or x == 0: return {}
        if driver in ("hz", "khz", "mhz", "ghz"):
            f = x * {"hz":1, "khz":1e3, "mhz":1e6, "ghz":1e9}[driver]
            lam = C_LIGHT / f
        elif driver in ("lam_m", "lam_cm", "lam_mm", "lam_in"):
            lam = x * {"lam_m":1, "lam_cm":1e-2, "lam_mm":1e-3, "lam_in":0.0254}[driver]
            f = C_LIGHT / lam
        elif driver in ("quarter_mm", "half_mm"):
            lam = x * {"quarter_mm":4, "half_mm":2}[driver] * 1e-3
            f = C_LIGHT / lam
        elif driver == "period_ns":
            f = 1.0 / (x * 1e-9); lam = C_LIGHT / f
        else:
            return {}
        return {
            "hz": f, "khz": f/1e3, "mhz": f/1e6, "ghz": f/1e9,
            "lam_m": lam, "lam_cm": lam*100, "lam_mm": lam*1000, "lam_in": lam/0.0254,
            "quarter_mm": lam*1000/4, "half_mm": lam*1000/2,
            "period_ns": 1e9 / f,
        }


class FreqMediumCard(CalcCard):
    def __init__(self):
        super().__init__("Wavelength in medium (Vp / εr)", [
            Field("f_mhz", "Frequency", "MHz"),
            Field("vf",    "Velocity factor (Vp/c)", "0..1"),
            Field("er",    "Dielectric constant εr", ""),
            Field("lam_mm", "λ in medium", "mm", is_output=True),
            Field("quarter_mm", "λ/4", "mm", is_output=True),
        ])

    def compute(self, driver, v):
        f = v.get("f_mhz"); vf = v.get("vf"); er = v.get("er")
        # vf and er are linked
        if driver == "vf" and vf and vf > 0:
            er = 1.0 / (vf * vf)
        elif driver == "er" and er and er > 0:
            vf = 1.0 / sqrt(er)
        if f is None or f <= 0: return {"vf": vf, "er": er}
        if vf is None or vf <= 0:
            if er and er > 0: vf = 1.0 / sqrt(er)
        if vf is None or vf <= 0: return {"vf": vf, "er": er}
        if er is None or er <= 0: er = 1.0 / (vf * vf)
        lam_m = (vf * C_LIGHT) / (f * 1e6)
        return {"vf": vf, "er": er, "lam_mm": lam_m * 1000, "quarter_mm": lam_m * 1000 / 4}


# ====================================================================
#  VSWR / MATCH
# ====================================================================

class VSWRCard(CalcCard):
    def __init__(self):
        super().__init__("VSWR ↔ |Γ| ↔ Return Loss ↔ Mismatch Loss", [
            Field("vswr", "VSWR", ":1"),
            Field("rho",  "|Γ| (refl. coeff.)", ""),
            Field("rho_pct", "|Γ|", "%"),
            Field("rl",   "Return loss", "dB"),
            Field("ml",   "Mismatch loss", "dB"),
            Field("pct_ref", "Power reflected", "%"),
            Field("pct_thru", "Power delivered", "%"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        rho = None
        if driver == "vswr":
            if x < 1: return {}
            rho = (x - 1) / (x + 1)
        elif driver == "rho":
            if x < 0 or x >= 1: return {}
            rho = x
        elif driver == "rho_pct":
            if x < 0 or x >= 100: return {}
            rho = x / 100
        elif driver == "rl":
            if x < 0: return {}
            rho = 10 ** (-x / 20)
        elif driver == "ml":
            if x < 0: return {}
            try:
                rho_sq = 1 - 10 ** (-x / 10); rho = sqrt(max(0.0, rho_sq))
            except ValueError: return {}
        elif driver == "pct_ref":
            if x < 0 or x >= 100: return {}
            rho = sqrt(x / 100)
        elif driver == "pct_thru":
            if x <= 0 or x > 100: return {}
            rho = sqrt(1 - x / 100)
        if rho is None: return {}
        if rho >= 1: rho = 0.99999999
        vswr = (1 + rho) / (1 - rho) if rho < 1 else None
        rl = -20 * log10(rho) if rho > 0 else None
        ml = -10 * log10(1 - rho * rho) if rho < 1 else None
        return {
            "vswr": vswr, "rho": rho, "rho_pct": rho * 100,
            "rl": rl, "ml": ml,
            "pct_ref": rho * rho * 100,
            "pct_thru": (1 - rho * rho) * 100,
        }


class ZGammaCard(CalcCard):
    """Z (real) <-> Gamma using Z0."""
    def __init__(self):
        super().__init__("Real impedance Z ↔ Γ  (uses Z₀)", [
            Field("z",     "Z (real)", "Ω"),
            Field("gamma", "Γ (signed)", ""),
            Field("vswr",  "VSWR", ":1", is_output=True),
            Field("rl",    "Return loss", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        if Z0 <= 0: return {}
        x = v.get(driver)
        if x is None: return {}
        if driver == "z":
            if x < 0: return {}
            g = (x - Z0) / (x + Z0); z = x
        elif driver == "gamma":
            if x <= -1 or x >= 1: return {}
            z = Z0 * (1 + x) / (1 - x); g = x
        else:
            return {}
        rho = abs(g)
        return {
            "z": z, "gamma": g,
            "vswr": (1 + rho) / (1 - rho) if rho < 1 else None,
            "rl": -20 * log10(rho) if rho > 0 else None,
        }


class ComplexZCard(CalcCard):
    """Complex Z = R + jX <-> complex Gamma (mag, angle)."""
    def __init__(self):
        super().__init__("Complex Z = R + jX  ↔  Γ∠θ  (uses Z₀)", [
            Field("r", "R", "Ω"),
            Field("x", "X", "Ω"),
            Field("rho",   "|Γ|", "", is_output=True),
            Field("theta", "∠Γ", "deg", is_output=True),
            Field("vswr",  "VSWR", ":1", is_output=True),
            Field("rl",    "Return loss", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        R, X = v.get("r"), v.get("x")
        if R is None or X is None: return {}
        Z = complex(R, X)
        try:
            G = (Z - Z0) / (Z + Z0)
        except ZeroDivisionError:
            return {}
        rho = abs(G); theta = math.degrees(math.atan2(G.imag, G.real))
        return {
            "rho": rho, "theta": theta,
            "vswr": (1 + rho) / (1 - rho) if rho < 1 else None,
            "rl": -20 * log10(rho) if rho > 0 else None,
        }


# ====================================================================
#  ANTENNA
# ====================================================================

class DBiDBdCard(CalcCard):
    def __init__(self):
        super().__init__("dBi ↔ dBd", [
            Field("dbi", "Gain", "dBi"),
            Field("dbd", "Gain", "dBd"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        if driver == "dbi": return {"dbi": x, "dbd": x - 2.15}
        return {"dbi": x + 2.15, "dbd": x}


class GainApertureCard(CalcCard):
    def __init__(self):
        super().__init__("Gain ↔ Effective Aperture (uses freq)", [
            Field("f_mhz", "Frequency", "MHz"),
            Field("g_dbi", "Gain", "dBi"),
            Field("ae_m2", "Effective aperture", "m²", is_output=True),
            Field("ae_cm2","Effective aperture", "cm²", is_output=True),
        ])

    def make_diagram(self):
        return GainApertureDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); g = v.get("g_dbi")
        if f is None or g is None or f <= 0: return {}
        lam = C_LIGHT / (f * 1e6)
        Ae = (10 ** (g / 10)) * lam * lam / (4 * pi)
        return {"ae_m2": Ae, "ae_cm2": Ae * 1e4}


class EIRPCard(CalcCard):
    def __init__(self):
        super().__init__("EIRP / ERP", [
            Field("pt_dbm", "Transmit power", "dBm"),
            Field("g_dbi",  "Antenna gain", "dBi"),
            Field("loss_db","Cable / line loss", "dB"),
            Field("eirp",   "EIRP", "dBm", is_output=True),
            Field("erp",    "ERP", "dBm", is_output=True),
            Field("eirp_w", "EIRP", "W", is_output=True),
        ])

    def make_diagram(self):
        return EIRPDiagram()

    def compute(self, driver, v):
        pt, g, l = v.get("pt_dbm"), v.get("g_dbi"), v.get("loss_db")
        if pt is None or g is None: return {}
        if l is None: l = 0
        eirp = pt + g - l
        erp  = eirp - 2.15
        return {"eirp": eirp, "erp": erp, "eirp_w": 10 ** ((eirp - 30) / 10)}


class BeamwidthCard(CalcCard):
    def __init__(self):
        super().__init__("Beamwidth ↔ Gain (Krauss approximation)", [
            Field("be", "E-plane 3dB beamwidth", "deg"),
            Field("bh", "H-plane 3dB beamwidth", "deg"),
            Field("g_dbi", "Approx. gain", "dBi", is_output=True),
            Field("eta",   "Aperture efficiency", "0..1"),
        ])

    def make_diagram(self):
        return BeamwidthDiagram()

    def compute(self, driver, v):
        be, bh = v.get("be"), v.get("bh")
        eta = v.get("eta")
        if eta is None or eta <= 0: eta = 0.7
        if be is None or bh is None or be <= 0 or bh <= 0:
            return {"eta": eta}
        # Krauss: G_iso = 41253 / (theta_E * theta_H)
        g_lin = 41253.0 / (be * bh) * eta / 0.7  # tweak for efficiency
        return {"g_dbi": 10 * log10(g_lin), "eta": eta}


class DipoleLengthCard(CalcCard):
    def __init__(self):
        super().__init__("Dipole / monopole physical length", [
            Field("f_mhz", "Frequency", "MHz"),
            Field("vf",    "Velocity factor", "0..1"),
            Field("dipole_m", "1/2-wave dipole", "m", is_output=True),
            Field("dipole_in","1/2-wave dipole", "in", is_output=True),
            Field("monopole_m","1/4-wave monopole", "m", is_output=True),
            Field("monopole_in","1/4-wave monopole", "in", is_output=True),
        ])

    def make_diagram(self):
        return DipoleDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); vf = v.get("vf")
        if vf is None or vf <= 0: vf = 0.95  # ~95% typical for thin wire
        if f is None or f <= 0: return {"vf": vf}
        lam = vf * C_LIGHT / (f * 1e6)
        return {
            "vf": vf,
            "dipole_m": lam / 2, "dipole_in": (lam / 2) / 0.0254,
            "monopole_m": lam / 4, "monopole_in": (lam / 4) / 0.0254,
        }


# ====================================================================
#  PATH LOSS / LINK
# ====================================================================

class FSPLCard(CalcCard):
    def __init__(self):
        super().__init__("Free-Space Path Loss (Friis)", [
            Field("f_mhz",   "Frequency", "MHz"),
            Field("d_km",    "Distance", "km"),
            Field("d_mi",    "Distance", "mi"),
            Field("d_m",     "Distance", "m"),
            Field("d_ft",    "Distance", "ft"),
            Field("fspl_db", "FSPL", "dB", is_output=True),
        ])

    def make_diagram(self):
        return FSPLDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz")
        d_km = v.get("d_km"); d_mi = v.get("d_mi")
        d_m  = v.get("d_m");  d_ft = v.get("d_ft")
        # link distances together via the driver
        if driver == "d_km" and d_km is not None:
            d_mi = d_km * 0.621371; d_m = d_km * 1000; d_ft = d_m / 0.3048
        elif driver == "d_mi" and d_mi is not None:
            d_km = d_mi / 0.621371; d_m = d_km * 1000; d_ft = d_m / 0.3048
        elif driver == "d_m" and d_m is not None:
            d_km = d_m / 1000; d_mi = d_km * 0.621371; d_ft = d_m / 0.3048
        elif driver == "d_ft" and d_ft is not None:
            d_m = d_ft * 0.3048; d_km = d_m / 1000; d_mi = d_km * 0.621371
        out = {"d_km": d_km, "d_mi": d_mi, "d_m": d_m, "d_ft": d_ft}
        if f is not None and d_km is not None and f > 0 and d_km > 0:
            out["fspl_db"] = 20 * log10(d_km) + 20 * log10(f) + 32.4478
        return out


class LinkBudgetCard(CalcCard):
    def __init__(self):
        super().__init__("Link Budget (received power)", [
            Field("pt_dbm", "Tx power", "dBm"),
            Field("gt_dbi", "Tx antenna gain", "dBi"),
            Field("gr_dbi", "Rx antenna gain", "dBi"),
            Field("loss_other", "Other losses", "dB"),
            Field("fspl_db",   "FSPL", "dB"),
            Field("pr_dbm",    "Rx power", "dBm", is_output=True),
            Field("pr_uw",     "Rx power", "µW", is_output=True),
        ])

    def compute(self, driver, v):
        pt, gt, gr = v.get("pt_dbm"), v.get("gt_dbi"), v.get("gr_dbi")
        lo = v.get("loss_other") or 0; fs = v.get("fspl_db")
        if None in (pt, gt, gr, fs): return {}
        pr = pt + gt + gr - fs - lo
        return {"pr_dbm": pr, "pr_uw": 10 ** ((pr - 30) / 10) * 1e6}


class FresnelCard(CalcCard):
    def __init__(self):
        super().__init__("Fresnel Zone Radius", [
            Field("f_mhz", "Frequency", "MHz"),
            Field("d1_km", "d1 (Tx → obstacle)", "km"),
            Field("d2_km", "d2 (obstacle → Rx)", "km"),
            Field("n",     "Zone number n", ""),
            Field("rn_m",  "Fresnel radius", "m", is_output=True),
            Field("clear_60_m","60% clearance", "m", is_output=True),
        ])

    def make_diagram(self):
        return FresnelDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); d1, d2 = v.get("d1_km"), v.get("d2_km"); n = v.get("n")
        if n is None or n <= 0: n = 1
        if None in (f, d1, d2) or f <= 0 or d1 <= 0 or d2 <= 0:
            return {"n": n}
        lam = C_LIGHT / (f * 1e6)
        rn = sqrt(n * lam * (d1 * 1000) * (d2 * 1000) / ((d1 + d2) * 1000))
        return {"n": n, "rn_m": rn, "clear_60_m": rn * 0.6}


class HorizonCard(CalcCard):
    def __init__(self):
        super().__init__("Radio Horizon (4/3 earth)", [
            Field("ht_m", "Tx antenna height", "m"),
            Field("hr_m", "Rx antenna height", "m"),
            Field("dt_km",   "Tx horizon", "km", is_output=True),
            Field("dr_km",   "Rx horizon", "km", is_output=True),
            Field("dtot_km", "Total range", "km", is_output=True),
            Field("dtot_mi", "Total range", "mi", is_output=True),
        ])

    def make_diagram(self):
        return HorizonDiagram()

    def compute(self, driver, v):
        ht = v.get("ht_m") or 0; hr = v.get("hr_m") or 0
        if ht <= 0 and hr <= 0: return {}
        dt = 4.12 * sqrt(ht) if ht > 0 else 0
        dr = 4.12 * sqrt(hr) if hr > 0 else 0
        dtot = dt + dr
        return {"dt_km": dt, "dr_km": dr, "dtot_km": dtot, "dtot_mi": dtot * 0.621371}


# ====================================================================
#  NOISE
# ====================================================================

class NFCard(CalcCard):
    def __init__(self):
        super().__init__("Noise Figure ↔ Noise Temperature", [
            Field("nf_db", "Noise figure", "dB"),
            Field("nf_lin","Noise factor", ""),
            Field("te_k",  "Equivalent noise temp", "K"),
            Field("yfact_db","Y-factor (290 K / 77 K)", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        if driver == "nf_db":
            F = 10 ** (x / 10); Te = (F - 1) * T0_REF
        elif driver == "nf_lin":
            if x < 1: return {}
            F = x; Te = (F - 1) * T0_REF
        elif driver == "te_k":
            if x < 0: return {}
            Te = x; F = 1 + Te / T0_REF
        else: return {}
        # Y-factor for hot=290K, cold=77K
        Th, Tc = 290, 77
        Y = (Th + Te) / (Tc + Te)
        return {"nf_db": 10*log10(F), "nf_lin": F, "te_k": Te, "yfact_db": 10*log10(Y)}


class ThermalNoiseCard(CalcCard):
    def __init__(self):
        super().__init__("Thermal Noise Floor (kTB)", [
            Field("t_k",   "Temperature", "K"),
            Field("bw_hz", "Bandwidth", "Hz"),
            Field("nf_db", "Noise figure (added)", "dB"),
            Field("kt_dbm_hz", "kT", "dBm/Hz", is_output=True),
            Field("noise_dbm", "Noise floor", "dBm", is_output=True),
            Field("noise_dbm_nf","Floor + NF", "dBm", is_output=True),
        ])
        # default values
        self.fields["t_k"].edit.setText("290")
        self.fields["nf_db"].edit.setText("0")

    def compute(self, driver, v):
        T = v.get("t_k"); B = v.get("bw_hz"); NF = v.get("nf_db") or 0
        if T is None or T <= 0: return {}
        kT_dbm_hz = 10 * log10(K_BOLTZ * T * 1e3)
        out = {"kt_dbm_hz": kT_dbm_hz}
        if B and B > 0:
            n = kT_dbm_hz + 10 * log10(B)
            out["noise_dbm"] = n
            out["noise_dbm_nf"] = n + NF
        return out


class CascadeNFCard(CalcCard):
    """3-stage Friis cascade noise figure."""
    _diagram_above = True
    def __init__(self):
        super().__init__("Cascade Noise Figure (Friis, 3 stages)", [
            Field("g1", "Stage 1 gain", "dB"),
            Field("nf1","Stage 1 NF", "dB"),
            Field("g2", "Stage 2 gain", "dB"),
            Field("nf2","Stage 2 NF", "dB"),
            Field("g3", "Stage 3 gain", "dB"),
            Field("nf3","Stage 3 NF", "dB"),
            Field("g_tot",  "Total gain", "dB", is_output=True),
            Field("nf_tot", "Total NF", "dB", is_output=True),
        ])

    def make_diagram(self):
        return CascadeNFDiagram()

    def compute(self, driver, v):
        g1, nf1 = v.get("g1"), v.get("nf1")
        g2, nf2 = v.get("g2"), v.get("nf2")
        g3, nf3 = v.get("g3"), v.get("nf3")
        if None in (g1, nf1): return {}
        F1 = 10 ** (nf1/10); G1 = 10 ** (g1/10)
        F = F1; G = G1
        if g2 is not None and nf2 is not None:
            F2 = 10 ** (nf2/10); G2 = 10 ** (g2/10)
            F = F + (F2 - 1) / G1; G = G * G2
            if g3 is not None and nf3 is not None:
                F3 = 10 ** (nf3/10); G3 = 10 ** (g3/10)
                F = F + (F3 - 1) / (G1 * G2); G = G * G3
        return {"g_tot": 10 * log10(G), "nf_tot": 10 * log10(F)}


class SNRCard(CalcCard):
    def __init__(self):
        super().__init__("SNR ↔ Eb/N₀  (given Rb, BW)", [
            Field("rb_bps", "Bit rate Rb", "bps"),
            Field("bw_hz",  "Bandwidth", "Hz"),
            Field("snr_db", "SNR", "dB"),
            Field("ebno_db","Eb/N₀", "dB"),
        ])

    def compute(self, driver, v):
        Rb, B = v.get("rb_bps"), v.get("bw_hz")
        snr, eb = v.get("snr_db"), v.get("ebno_db")
        if Rb is None or B is None or Rb <= 0 or B <= 0: return {}
        # SNR = Eb/N0 + 10log(Rb/B)
        offset = 10 * log10(Rb / B)
        if driver == "snr_db" and snr is not None:
            return {"ebno_db": snr - offset}
        if driver == "ebno_db" and eb is not None:
            return {"snr_db": eb + offset}
        # if Rb or B changed, recompute one based on the other
        if snr is not None:
            return {"ebno_db": snr - offset}
        if eb is not None:
            return {"snr_db": eb + offset}
        return {}


# ====================================================================
#  MIXER / IM / DYNAMIC RANGE
# ====================================================================

class IP3Card(CalcCard):
    def __init__(self):
        super().__init__("IP3 / 1 dB Compression / IM3", [
            Field("p1db", "P₁𝐅 (1 dB compression)", "dBm"),
            Field("oip3", "OIP3", "dBm"),
            Field("iip3", "IIP3", "dBm"),
            Field("gain", "Gain", "dB"),
            Field("pin",  "Single-tone Pin (each tone)", "dBm"),
            Field("im3_dbc", "IM3 below carrier", "dBc", is_output=True),
            Field("im3_dbm", "IM3 product power", "dBm", is_output=True),
        ])

    def compute(self, driver, v):
        # Rule of thumb: OIP3 ~ P1dB + 10 dB (some use 9.6)
        p1, oip3, iip3, g, pin = (v.get(k) for k in ("p1db", "oip3", "iip3", "gain", "pin"))
        out = {}
        if driver == "p1db" and p1 is not None:
            oip3 = p1 + 10
            out["oip3"] = oip3
            if g is not None: out["iip3"] = oip3 - g
        elif driver == "oip3" and oip3 is not None:
            out["p1db"] = oip3 - 10
            if g is not None: out["iip3"] = oip3 - g
        elif driver == "iip3" and iip3 is not None:
            if g is not None:
                oip3 = iip3 + g; out["oip3"] = oip3; out["p1db"] = oip3 - 10
        elif driver == "gain" and g is not None:
            if oip3 is not None: out["iip3"] = oip3 - g
            elif iip3 is not None: out["oip3"] = iip3 + g
        # IM3 calc requires Pin & IIP3 (or Pout & OIP3)
        if pin is not None and iip3 is not None:
            im3_dbc = 2 * (iip3 - pin)
            im3_in_dbm = pin - im3_dbc
            out["im3_dbc"] = im3_dbc
            if g is not None:
                out["im3_dbm"] = im3_in_dbm + g
            else:
                out["im3_dbm"] = im3_in_dbm
        return out


class SFDRCard(CalcCard):
    def __init__(self):
        super().__init__("Spurious-Free Dynamic Range", [
            Field("iip3", "IIP3", "dBm"),
            Field("nf_db","NF", "dB"),
            Field("bw_hz","Bandwidth", "Hz"),
            Field("mds_dbm", "MDS (noise floor)", "dBm", is_output=True),
            Field("sfdr_db", "SFDR", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        iip3, nf, B = v.get("iip3"), v.get("nf_db"), v.get("bw_hz")
        if None in (iip3, nf, B) or B <= 0: return {}
        mds = -174 + nf + 10 * log10(B)
        sfdr = (2.0 / 3.0) * (iip3 - mds)
        return {"mds_dbm": mds, "sfdr_db": sfdr}


class MixerImageCard(CalcCard):
    def __init__(self):
        super().__init__("Mixer: RF / LO / IF / Image", [
            Field("rf_mhz", "RF", "MHz"),
            Field("lo_mhz", "LO", "MHz"),
            Field("if_mhz", "IF", "MHz", is_output=True),
            Field("img_high", "Image (high-side LO)", "MHz", is_output=True),
            Field("img_low",  "Image (low-side LO)", "MHz", is_output=True),
        ])

    def compute(self, driver, v):
        rf, lo = v.get("rf_mhz"), v.get("lo_mhz")
        if rf is None or lo is None: return {}
        return {
            "if_mhz": abs(rf - lo),
            "img_high": lo + abs(rf - lo),  # if LO > RF, image is at LO + IF
            "img_low":  lo - abs(rf - lo),
        }


# ====================================================================
#  MODULATION / DIGITAL
# ====================================================================

class ShannonCard(CalcCard):
    def __init__(self):
        super().__init__("Shannon Capacity", [
            Field("bw_hz",  "Bandwidth", "Hz"),
            Field("snr_db", "SNR", "dB"),
            Field("c_bps",  "Capacity", "bps", is_output=True),
            Field("eff_bphz","Spectral efficiency", "bit/s/Hz", is_output=True),
        ])

    def compute(self, driver, v):
        B, snr_db = v.get("bw_hz"), v.get("snr_db")
        if B is None or snr_db is None or B <= 0: return {}
        snr_lin = 10 ** (snr_db / 10)
        eff = log2(1 + snr_lin)
        return {"c_bps": B * eff, "eff_bphz": eff}


class SymbolBitCard(CalcCard):
    def __init__(self):
        super().__init__("Symbol Rate ↔ Bit Rate ↔ Bandwidth (Nyquist)", [
            Field("rb_bps",  "Bit rate Rb", "bps"),
            Field("rs_baud", "Symbol rate Rs", "Baud"),
            Field("m",       "Modulation order M", ""),
            Field("alpha",   "Roll-off α", "0..1"),
            Field("bw_hz",   "Occupied BW = Rs(1+α)", "Hz", is_output=True),
            Field("k",       "Bits/symbol = log₂ M", "", is_output=True),
        ])

    def compute(self, driver, v):
        Rb, Rs = v.get("rb_bps"), v.get("rs_baud")
        M, a = v.get("m"), v.get("alpha")
        if a is None: a = 0.35
        if M is None or M < 2: M = 2
        k = log2(M)
        if driver == "rb_bps" and Rb is not None:
            Rs = Rb / k
        elif driver == "rs_baud" and Rs is not None:
            Rb = Rs * k
        elif driver in ("m",):
            if Rb is not None: Rs = Rb / k
            elif Rs is not None: Rb = Rs * k
        elif driver in ("alpha",):
            pass
        out = {"alpha": a, "m": M, "k": k, "rb_bps": Rb, "rs_baud": Rs}
        if Rs is not None and Rs > 0:
            out["bw_hz"] = Rs * (1 + a)
        return out


class BERCard(CalcCard):
    def __init__(self):
        super().__init__("BER vs Eb/N₀  (theoretical AWGN)", [
            Field("ebno_db", "Eb/N₀", "dB"),
            Field("ber_bpsk", "BER BPSK / QPSK", "", is_output=True),
            Field("ber_8psk", "BER 8-PSK (approx)", "", is_output=True),
            Field("ber_16qam","BER 16-QAM", "", is_output=True),
            Field("ber_64qam","BER 64-QAM", "", is_output=True),
        ])

    def compute(self, driver, v):
        ebno = v.get("ebno_db")
        if ebno is None: return {}
        x = 10 ** (ebno / 10)
        # BPSK / QPSK
        bpsk = Q_func(sqrt(2 * x))
        # 8-PSK (Gray): BER ~ (2/3) Q(sqrt(2 k Eb/N0) sin(pi/8)), k=3
        try:
            psk8 = (2.0 / 3.0) * Q_func(sqrt(2 * 3 * x) * math.sin(pi / 8))
        except Exception:
            psk8 = None
        # M-QAM (square) approx: BER ~ (4/k)(1 - 1/sqrt(M)) Q(sqrt(3 k Eb/N0 / (M-1)))
        def qam(M):
            k = log2(M)
            return (4.0 / k) * (1 - 1 / sqrt(M)) * Q_func(sqrt(3 * k * x / (M - 1)))
        return {
            "ber_bpsk": bpsk,
            "ber_8psk": psk8,
            "ber_16qam": qam(16),
            "ber_64qam": qam(64),
        }


class FMDeviationCard(CalcCard):
    def __init__(self):
        super().__init__("FM bandwidth (Carson's rule)", [
            Field("dev_khz", "Peak deviation Δf", "kHz"),
            Field("fmod_khz","Modulating freq fm", "kHz"),
            Field("bw_khz",  "Carson BW = 2(Δf + fm)", "kHz", is_output=True),
            Field("beta",    "Modulation index β = Δf/fm", "", is_output=True),
        ])

    def compute(self, driver, v):
        dev, fm = v.get("dev_khz"), v.get("fmod_khz")
        if dev is None or fm is None or fm <= 0: return {}
        return {"bw_khz": 2 * (dev + fm), "beta": dev / fm}


class PhaseNoiseJitterCard(CalcCard):
    """Convert integrated phase noise (dBc) ↔ RMS jitter at a carrier."""
    def __init__(self):
        super().__init__("Integrated phase noise ↔ RMS jitter", [
            Field("f0_mhz",   "Carrier frequency f₀", "MHz"),
            Field("phn_dbc",  "Integrated phase noise", "dBc"),
            Field("phn_rad",  "RMS phase σφ", "rad", is_output=True),
            Field("phn_deg",  "RMS phase σφ", "deg", is_output=True),
            Field("phn_mdeg", "RMS phase σφ", "m°", is_output=True),
            Field("jit_ps",   "RMS jitter", "ps", is_output=True),
            Field("jit_fs",   "RMS jitter", "fs", is_output=True),
        ])

    def compute(self, driver, v):
        f0 = v.get("f0_mhz"); pn = v.get("phn_dbc")
        out = {}
        # support driving from any field
        if driver in ("phn_rad", "phn_deg", "phn_mdeg", "jit_ps", "jit_fs"):
            if driver == "phn_rad":
                sig = v.get("phn_rad")
            elif driver == "phn_deg":
                sig = (v.get("phn_deg") or 0) * pi / 180
            elif driver == "phn_mdeg":
                sig = (v.get("phn_mdeg") or 0) * 1e-3 * pi / 180
            elif driver == "jit_ps" and f0 and f0 > 0:
                sig = (v.get("jit_ps") or 0) * 1e-12 * 2 * pi * f0 * 1e6
            elif driver == "jit_fs" and f0 and f0 > 0:
                sig = (v.get("jit_fs") or 0) * 1e-15 * 2 * pi * f0 * 1e6
            else:
                sig = None
            if sig is None or sig <= 0: return {}
            pn_dbc = 10 * log10(sig * sig / 2)
            out["phn_dbc"] = pn_dbc
            pn = pn_dbc
        if pn is None: return out
        sigma = sqrt(2 * 10 ** (pn / 10))   # rad RMS
        out["phn_rad"]  = sigma
        out["phn_deg"]  = sigma * 180 / pi
        out["phn_mdeg"] = sigma * 180 / pi * 1000
        if f0 is not None and f0 > 0:
            jit_s = sigma / (2 * pi * f0 * 1e6)
            out["jit_ps"] = jit_s * 1e12
            out["jit_fs"] = jit_s * 1e15
        return out


class JitterSNRCard(CalcCard):
    """Aperture-jitter SNR limit (Walden, ADC sampling).
       SNR = -20·log10(2π·f·σt)"""
    def __init__(self):
        super().__init__("Aperture-jitter SNR limit", [
            Field("f_mhz",  "Signal frequency f", "MHz"),
            Field("jit_ps", "Aperture jitter σt", "ps"),
            Field("snr_db", "Max SNR (jitter only)", "dB",   is_output=True),
            Field("enob",   "Equivalent ENOB", "bits",       is_output=True),
        ])

    def compute(self, driver, v):
        f = v.get("f_mhz"); jit = v.get("jit_ps")
        if f is None or jit is None or f <= 0 or jit <= 0: return {}
        snr = -20 * log10(2 * pi * f * 1e6 * jit * 1e-12)
        # ENOB from SNR = 6.02 N + 1.76
        enob = (snr - 1.76) / 6.02
        return {"snr_db": snr, "enob": enob}


class ADCDynamicRangeCard(CalcCard):
    """Full ADC dynamic-range budget — combines quantization noise,
    aperture-jitter noise, and an externally-supplied thermal floor into
    one SNR / ENOB / NSD readout.

    Quantization SNR    = 6.02·N + 1.76 dB           (full-scale sine)
    Jitter SNR          = −20·log10(2π·f_in·σ_t) dB
    Thermal noise floor = entered directly as dBFS in-band

    All three noise sources combine in power; ENOB and noise-spectral-
    density (NSD, in dBFS/Hz) follow.  NSD assumes white noise spread
    across the Nyquist band F_s/2.
    """
    def __init__(self):
        super().__init__("ADC dynamic range (SNR / ENOB / NSD)", [
            Field("bits",         "Resolution",                 "bits"),
            Field("fs_msps",      "Sample rate",                "MSPS"),
            Field("fin_mhz",      "Input frequency",            "MHz"),
            Field("jit_fs",       "Clock jitter (RMS)",         "fs"),
            Field("thermal_dbfs", "Thermal floor (in-band)",    "dBFS"),
            Field("snr_quant",    "Quantization SNR",           "dB",
                  is_output=True),
            Field("snr_jit",      "Jitter SNR",                 "dB",
                  is_output=True),
            Field("snr_total",    "Total SNR",                  "dB",
                  is_output=True),
            Field("enob",         "ENOB",                       "bits",
                  is_output=True),
            Field("nsd",          "Noise spectral density",     "dBFS/Hz",
                  is_output=True),
        ])
        # Reasonable defaults for a modern high-speed ADC
        self.fields["bits"].edit.setText("16")
        self.fields["fs_msps"].edit.setText("250")
        self.fields["fin_mhz"].edit.setText("70")
        self.fields["jit_fs"].edit.setText("100")
        self.fields["thermal_dbfs"].edit.setText("-160")
        # All inputs default-populated — fire one compute pass so the
        # outputs aren't blank when the user first lands on the tab.
        self.recompute_from_inputs()

    def compute(self, driver, v):
        bits  = v.get("bits")
        fs    = v.get("fs_msps")
        fin   = v.get("fin_mhz")
        jit   = v.get("jit_fs")
        therm = v.get("thermal_dbfs")
        out = {}
        # Each contribution as a linear noise power (relative to FS).
        contributions = []
        if bits is not None and bits > 0:
            snr_q = 6.02 * bits + 1.76
            out["snr_quant"] = snr_q
            contributions.append(10 ** (-snr_q / 10.0))
        if fin is not None and fin > 0 and jit is not None and jit > 0:
            snr_j = -20.0 * log10(2 * pi * fin * 1e6 * jit * 1e-15)
            out["snr_jit"] = snr_j
            contributions.append(10 ** (-snr_j / 10.0))
        if therm is not None:
            contributions.append(10 ** (therm / 10.0))
        if not contributions:
            return out
        total_lin = sum(contributions)
        if total_lin <= 0:
            return out
        snr_total = -10.0 * log10(total_lin)
        out["snr_total"] = snr_total
        out["enob"]      = (snr_total - 1.76) / 6.02
        if fs is not None and fs > 0:
            # NSD spread over Nyquist band Fs/2.
            out["nsd"] = -snr_total - 10.0 * log10(fs * 1e6 / 2.0)
        return out


# ---------- frequency band tables ----------
IEEE_BANDS = [
    (3e6,    30e6,   "HF"),
    (30e6,   300e6,  "VHF"),
    (300e6,  1e9,    "UHF"),
    (1e9,    2e9,    "L"),
    (2e9,    4e9,    "S"),
    (4e9,    8e9,    "C"),
    (8e9,    12e9,   "X"),
    (12e9,   18e9,   "Ku"),
    (18e9,   27e9,   "K"),
    (27e9,   40e9,   "Ka"),
    (40e9,   75e9,   "V"),
    (75e9,   110e9,  "W"),
    (110e9,  300e9,  "mm-wave (D, G, Y)"),
]
ITU_BANDS = [
    (3,      30,     "ELF"),
    (30,     300,    "SLF"),
    (300,    3e3,    "ULF"),
    (3e3,    30e3,   "VLF"),
    (30e3,   300e3,  "LF"),
    (300e3,  3e6,    "MF"),
    (3e6,    30e6,   "HF"),
    (30e6,   300e6,  "VHF"),
    (300e6,  3e9,    "UHF"),
    (3e9,    30e9,   "SHF"),
    (30e9,   300e9,  "EHF"),
]
COMMON_BANDS = [
    (148.5e3,    283.5e3,  "AM longwave (Europe)"),
    (530e3,      1700e3,   "AM mediumwave"),
    (3.5e6,      4.0e6,    "80 m amateur"),
    (5.33e6,     5.41e6,   "60 m amateur"),
    (7.0e6,      7.3e6,    "40 m amateur"),
    (10.1e6,     10.15e6,  "30 m amateur"),
    (14.0e6,     14.35e6,  "20 m amateur"),
    (18.068e6,   18.168e6, "17 m amateur"),
    (21.0e6,     21.45e6,  "15 m amateur"),
    (24.89e6,    24.99e6,  "12 m amateur"),
    (26.965e6,   27.405e6, "CB"),
    (28.0e6,     29.7e6,   "10 m amateur"),
    (50.0e6,     54.0e6,   "6 m amateur"),
    (87.5e6,     108e6,    "FM broadcast"),
    (108e6,      137e6,    "Aviation VHF"),
    (144e6,      148e6,    "2 m amateur"),
    (174e6,      216e6,    "VHF TV ch 7-13"),
    (430e6,      450e6,    "70 cm amateur"),
    (470e6,      608e6,    "UHF TV"),
    (824e6,      894e6,    "Cellular 850 (B5)"),
    (880e6,      960e6,    "GSM 900 / LTE B8"),
    (902e6,      928e6,    "33 cm ISM (US)"),
    (1227.6e6,   1227.6e6, "GPS L2"),
    (1240e6,     1300e6,   "23 cm amateur"),
    (1525e6,     1559e6,   "Inmarsat downlink"),
    (1559e6,     1610e6,   "GNSS L1 (GPS 1575.42, GLONASS, Galileo)"),
    (1710e6,     1880e6,   "GSM 1800 / LTE B3"),
    (1850e6,     1990e6,   "PCS 1900 / LTE B2"),
    (2110e6,     2170e6,   "UMTS / LTE B1 DL"),
    (2400e6,     2500e6,   "2.4 GHz ISM (Wi-Fi 1/2/3, BT, ZigBee)"),
    (3300e6,     3800e6,   "C-band 5G (n77/n78)"),
    (4400e6,     5000e6,   "5 GHz lower (Wi-Fi 4/5/6 UNII-1/2A)"),
    (5150e6,     5350e6,   "Wi-Fi UNII-1/2A"),
    (5470e6,     5725e6,   "Wi-Fi UNII-2C"),
    (5725e6,     5875e6,   "5 GHz ISM / Wi-Fi UNII-3"),
    (5925e6,     7125e6,   "6 GHz UNII (Wi-Fi 6E / 7)"),
    (10.5e9,     10.55e9,  "X-band amateur / radar"),
    (24.05e9,    24.25e9,  "24 GHz ISM"),
    (24.25e9,    27.5e9,   "5G FR2 n258"),
    (37e9,       40e9,     "5G FR2 n260"),
    (57e9,       64e9,     "60 GHz unlicensed (WiGig)"),
    (76e9,       81e9,     "Auto radar 77 GHz"),
    (94e9,       94e9,     "W-band imaging"),
]

# ---------- detailed reference table shown in the Bands tab ----------
# This is the "ultra-detailed" datagrid the user sees: ITU classification,
# IEEE 521-2019 radar/microwave letters, NATO/ECM bands, EIA/IEC waveguide
# bands (with TE10 cutoffs), and common services.  Cross-checked against
# IEEE 521-2019, ITU-R V.431, Wikipedia "Waveguide (radio frequency)", and
# Microwaves101.  Where sources disagree (e.g. NATO L 40-60 GHz vs IEEE L
# 1-2 GHz), the conflict is called out in the notes column.
# Each row: (lo_hz, hi_hz, band_name, system, notes).
BAND_TABLE = [
    # ---- ITU radio band classification (ITU-R V.431) ----
    (3.0,       30.0,        "ITU ELF",    "ITU",       "Extremely Low Frequency – submarine comms, geophysics"),
    (30.0,      300.0,       "ITU SLF",    "ITU",       "Super Low Frequency – power-grid harmonics, ELF research"),
    (300.0,     3.0e3,       "ITU ULF",    "ITU",       "Ultra Low Frequency – mine comms, earth-mode telegraphy"),
    (3.0e3,     30.0e3,      "ITU VLF",    "ITU",       "Very Low Frequency – navigation (Omega), time signals"),
    (30.0e3,    300.0e3,     "ITU LF",     "ITU",       "Low Frequency – LORAN-C, AM longwave broadcast, RFID 125 kHz"),
    (300.0e3,   3.0e6,       "ITU MF",     "ITU",       "Medium Frequency – AM broadcast band, maritime, NDBs"),
    (3.0e6,     30.0e6,      "ITU HF",     "ITU",       "High Frequency – shortwave, amateur, OTH radar, CB 27 MHz"),
    (30.0e6,    300.0e6,     "ITU VHF",    "ITU",       "Very High Frequency – FM broadcast, TV, air-band, 2 m ham"),
    (300.0e6,   3.0e9,       "ITU UHF",    "ITU",       "Ultra High Frequency – TV, cellular, GPS L-band, Wi-Fi 2.4"),
    (3.0e9,     30.0e9,      "ITU SHF",    "ITU",       "Super High Frequency – microwave links, satellite, radar"),
    (30.0e9,    300.0e9,     "ITU EHF",    "ITU",       "Extremely High Frequency – mm-wave, 5G FR2, auto radar"),
    (300.0e9,   3.0e12,      "ITU THF",    "ITU",       "Tremendously High Frequency – sub-mm / terahertz imaging"),

    # ---- IEEE 521-2019 radar / microwave letter bands ----
    (3.0e6,     30.0e6,      "IEEE HF",    "IEEE",      "IEEE radar HF – OTH skywave radar (e.g. ROTHR, JORN)"),
    (30.0e6,    300.0e6,     "IEEE VHF",   "IEEE",      "IEEE radar VHF – early-warning, anti-stealth surveillance"),
    (300.0e6,   1.0e9,       "IEEE UHF",   "IEEE",      "IEEE radar UHF – long-range surveillance, ballistic missile"),
    (1.0e9,     2.0e9,       "IEEE L",     "IEEE",      "L-band – air-traffic surveillance, GPS L1 1.575 GHz"),
    (2.0e9,     4.0e9,       "IEEE S",     "IEEE",      "S-band – weather radar (NEXRAD), airport surveillance"),
    (4.0e9,     8.0e9,       "IEEE C",     "IEEE",      "C-band – weather radar, satcom, 5G n77/n78 lower edge"),
    (8.0e9,     12.0e9,      "IEEE X",     "IEEE",      "X-band – fire-control, marine, airborne intercept radar"),
    (12.0e9,    18.0e9,      "IEEE Ku",    "IEEE",      "Ku-band – DBS satellite TV downlink, VSAT, police radar"),
    (18.0e9,    27.0e9,      "IEEE K",     "IEEE",      "K-band – police radar 24.15 GHz, 22 GHz H₂O absorption"),
    (27.0e9,    40.0e9,      "IEEE Ka",    "IEEE",      "Ka-band – high-cap satcom, 5G n258/n261, mm-wave imaging"),
    (40.0e9,    75.0e9,      "IEEE V",     "IEEE",      "V-band – 60 GHz O₂ absorption, WiGig 802.11ad/ay"),
    (75.0e9,    110.0e9,     "IEEE W",     "IEEE",      "W-band – 77/79 GHz auto radar, cloud radar, mm-wave imaging"),
    (110.0e9,   300.0e9,     "IEEE mm/G",  "IEEE",      "mm-wave / G-band – radio astronomy, security imaging, 6G R&D"),

    # ---- NATO / EU / US ECM letter bands (electronic warfare) ----
    (0.0,       250.0e6,     "NATO A",     "NATO/ECM",  "NATO A – HF/VHF EW; comms intercept, broadcast jamming"),
    (250.0e6,   500.0e6,     "NATO B",     "NATO/ECM",  "NATO B – upper VHF / lower UHF EW"),
    (500.0e6,   1.0e9,       "NATO C",     "NATO/ECM",  "NATO C – UHF EW; covers IEEE UHF radar upper half"),
    (1.0e9,     2.0e9,       "NATO D",     "NATO/ECM",  "NATO D – overlaps IEEE L-band; air-search radar EW"),
    (2.0e9,     3.0e9,       "NATO E",     "NATO/ECM",  "NATO E – lower S-band; airport surveillance"),
    (3.0e9,     4.0e9,       "NATO F",     "NATO/ECM",  "NATO F – upper S-band; long-range air-search"),
    (4.0e9,     6.0e9,       "NATO G",     "NATO/ECM",  "NATO G – lower C-band; satcom uplink, weather radar"),
    (6.0e9,     8.0e9,       "NATO H",     "NATO/ECM",  "NATO H – upper C-band; military satcom"),
    (8.0e9,     10.0e9,      "NATO I",     "NATO/ECM",  "NATO I – lower X-band; fire-control, missile seekers"),
    (10.0e9,    20.0e9,      "NATO J",     "NATO/ECM",  "NATO J – upper X / Ku; tracking, missile, satcom"),
    (20.0e9,    40.0e9,      "NATO K",     "NATO/ECM",  "NATO K – covers IEEE K + Ka in one block"),
    (40.0e9,    60.0e9,      "NATO L",     "NATO/ECM",  "NATO L – lower V-band (note: clashes with IEEE L!)"),
    (60.0e9,    100.0e9,     "NATO M",     "NATO/ECM",  "NATO M – upper V / W-band EW"),

    # ---- Standard rectangular waveguide bands (EIA WR / IEC R) ----
    (320.0e6,   450.0e6,     "WR-2300",    "Waveguide", "R3 / L-band guide; TE10 cutoff 0.257 GHz"),
    (500.0e6,   750.0e6,     "WR-1500",    "Waveguide", "R6 UHF guide; TE10 cutoff 0.393 GHz"),
    (750.0e6,   1.15e9,      "WR-975",     "Waveguide", "R9 / L-band guide; TE10 cutoff 0.605 GHz"),
    (1.15e9,    1.72e9,      "WR-650",     "Waveguide", "R14 / L-band (WG6); TE10 cutoff 0.908 GHz"),
    (1.72e9,    2.60e9,      "WR-430",     "Waveguide", "R22 / S-band lower; TE10 cutoff 1.372 GHz"),
    (2.60e9,    3.95e9,      "WR-284",     "Waveguide", "R32 / S-band; TE10 cutoff 2.078 GHz; weather radar feed"),
    (3.95e9,    5.85e9,      "WR-187",     "Waveguide", "R48 / C-band lower; TE10 cutoff 3.153 GHz"),
    (5.85e9,    8.20e9,      "WR-137",     "Waveguide", "R70 / C-band upper; TE10 cutoff 4.301 GHz"),
    (7.05e9,    10.0e9,      "WR-112",     "Waveguide", "R84 / X-band lower; TE10 cutoff 5.260 GHz"),
    (8.20e9,    12.40e9,     "WR-90",      "Waveguide", "R100 / X-band; TE10 cutoff 6.557 GHz; classic radar"),
    (10.0e9,    15.0e9,      "WR-75",      "Waveguide", "R120 / Ku lower; TE10 cutoff 7.869 GHz"),
    (12.4e9,    18.0e9,      "WR-62",      "Waveguide", "R140 / Ku-band; TE10 cutoff 9.488 GHz"),
    (18.0e9,    26.5e9,      "WR-42",      "Waveguide", "R220 / K-band; TE10 cutoff 14.051 GHz"),
    (22.0e9,    33.0e9,      "WR-34",      "Waveguide", "R260 / Ka lower; TE10 cutoff 17.357 GHz"),
    (26.5e9,    40.0e9,      "WR-28",      "Waveguide", "R320 / Ka-band; TE10 cutoff 21.077 GHz; 5G n257/n261"),
    (33.0e9,    50.0e9,      "WR-22",      "Waveguide", "R400 / Q-band; TE10 cutoff 26.346 GHz"),
    (40.0e9,    60.0e9,      "WR-19",      "Waveguide", "R500 / U-band; TE10 cutoff 31.391 GHz"),
    (50.0e9,    75.0e9,      "WR-15",      "Waveguide", "R620 / V-band; TE10 cutoff 39.875 GHz; 60 GHz WiGig"),
    (60.0e9,    90.0e9,      "WR-12",      "Waveguide", "R740 / E-band lower; TE10 cutoff 48.373 GHz"),
    (75.0e9,    110.0e9,     "WR-10",      "Waveguide", "R900 / W-band; TE10 cutoff 59.015 GHz; auto radar 77 GHz"),
    (90.0e9,    140.0e9,     "WR-8",       "Waveguide", "R1200 / F-band; TE10 cutoff 73.768 GHz"),
    (110.0e9,   170.0e9,     "WR-6",       "Waveguide", "R1400 / D-band; TE10 cutoff 90.791 GHz"),
    (140.0e9,   220.0e9,     "WR-5",       "Waveguide", "R1800 / G-band; TE10 cutoff ~115.7 GHz"),
    (170.0e9,   260.0e9,     "WR-4",       "Waveguide", "R2200 / H-band; TE10 cutoff ~137.5 GHz"),
    (220.0e9,   330.0e9,     "WR-3",       "Waveguide", "R2600 / Y-band; TE10 cutoff ~173.6 GHz"),

    # ---- Common services / use-case bands ----
    (535.0e3,   1.705e6,     "AM Broadcast",        "Service", "AM medium-wave broadcast band (ITU Region 2)"),
    (87.5e6,    108.0e6,     "FM Broadcast",        "Service", "FM stereo broadcast band (ITU Regions 1/2/3)"),
    (108.0e6,   137.0e6,     "Aero VHF",            "Service", "Aviation voice (118–137) and VOR/ILS (108–118)"),
    (1.2276e9,  1.5754e9,    "GNSS L-band",         "Service", "GPS L1 1575.42, L2 1227.60, GLONASS, Galileo E1/E5"),
    (2.400e9,   2.4835e9,    "ISM 2.4 GHz",         "Service", "Wi-Fi 2.4 GHz, Bluetooth, Zigbee, microwave ovens"),
    (5.150e9,   5.895e9,     "U-NII 5 GHz",         "Service", "Wi-Fi 5 / 6 (UNII-1/2A/2C/3); 5.8 GHz ISM overlap"),
    (5.925e9,   7.125e9,     "Wi-Fi 6E / 7",        "Service", "Unlicensed 6 GHz Wi-Fi 6E and Wi-Fi 7 (UNII-5..8)"),
    (10.7e9,    12.75e9,     "Ku DBS DL",           "Service", "Satellite TV downlink (DBS / FSS Ku-band)"),
    (24.25e9,   29.5e9,      "5G FR2 n257/258/261", "Service", "5G mm-wave 26/28 GHz (n258 24.25–27.5, n257 26.5–29.5)"),
    (37.0e9,    40.0e9,      "5G FR2 n260",         "Service", "5G mm-wave 39 GHz band (US allocation)"),
    (76.0e9,    81.0e9,      "Auto Radar",          "Service", "Automotive 77 GHz LRR + 79 GHz SRR (76–81 GHz)"),
]


def _fmt_band_freq(f_hz):
    """Auto-unit Hz formatter used by the BandTable: picks Hz / kHz / MHz /
    GHz / THz so the printed ranges stay readable across 9 decades."""
    if f_hz <= 0:
        return "0"
    if f_hz < 1e3:
        return f"{f_hz:g} Hz"
    if f_hz < 1e6:
        return f"{f_hz/1e3:g} kHz"
    if f_hz < 1e9:
        return f"{f_hz/1e6:g} MHz"
    if f_hz < 1e12:
        return f"{f_hz/1e9:g} GHz"
    return f"{f_hz/1e12:g} THz"


class FreqBandChart(QWidget):
    """Horizontal log-axis strip showing every IEEE band (and the ITU
    decade boundaries beneath) with a marker for the current frequency
    and an optional highlighted range overlay.

    Stretches horizontally with its parent — the band rectangles spread
    over the full panel so a marker placed near 1 GHz on a 1200-px-wide
    canvas still lands somewhere sensible."""
    F_MIN = 3e6      # 3 MHz (low end of HF)
    F_MAX = 300e9    # 300 GHz

    PALETTE = [
        "#bd6f6f", "#bd9d6f", "#bdb76f", "#9dbd6f", "#6fbd80",
        "#6fbdb1", "#6f96bd", "#7c6fbd", "#a86fbd", "#bd6fa6",
        "#bd6f76", "#8a6fbd", "#6fbda1",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        # Fixed height, but expands horizontally to fill the band panel.
        self.setMinimumHeight(96)
        self.setMaximumHeight(96)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._f_hz = None
        self._range = None

    def set_freq(self, f_hz):
        self._f_hz = f_hz
        self.update()

    def set_range(self, lo, hi):
        self._range = (lo, hi) if (lo and hi and hi > lo) else None
        self.update()

    def _x_of(self, f, x0, w):
        if f <= self.F_MIN: return x0
        if f >= self.F_MAX: return x0 + w
        return x0 + w * (log10(f) - log10(self.F_MIN)) / (log10(self.F_MAX) - log10(self.F_MIN))

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fam = QApplication.font().family()
        margin = 4
        x0, y0 = margin, 18
        w = self.width() - 2 * margin
        bar_h = 38
        if THEME == "dark":
            text_col, border_col = QColor(220, 220, 220), QColor(70, 70, 70)
        else:
            text_col, border_col = QColor(40, 40, 40), QColor(245, 245, 245)
        lab_font = QFont(fam); lab_font.setPointSize(8); lab_font.setBold(True)
        for i, (lo, hi, name) in enumerate(IEEE_BANDS):
            xl, xr = self._x_of(lo, x0, w), self._x_of(hi, x0, w)
            p.setPen(QPen(border_col, 1.0)); p.setBrush(QColor(self.PALETTE[i % len(self.PALETTE)]))
            p.drawRect(QRectF(xl, y0, max(2.0, xr - xl), bar_h))
            p.setFont(lab_font); p.setPen(QColor(255, 255, 255))
            first = name.split()[0] if name else ""
            for label in (first, first.split("-")[0]):
                tw = p.fontMetrics().horizontalAdvance(label)
                if label and xr - xl > tw + 4:
                    p.drawText(QPointF((xl + xr) / 2 - tw / 2, y0 + bar_h / 2 + 4), label)
                    break
        tick_font = QFont(fam); tick_font.setPointSize(7); p.setFont(tick_font)
        for k, txt in ((7, "10M"), (8, "100M"), (9, "1G"), (10, "10G"), (11, "100G")):
            x = self._x_of(10 ** k, x0, w)
            p.setPen(QPen(text_col, 0.8)); p.drawLine(QPointF(x, y0 + bar_h), QPointF(x, y0 + bar_h + 4))
            tw = p.fontMetrics().horizontalAdvance(txt)
            p.drawText(QPointF(x - tw / 2, y0 + bar_h + 16), txt)
        if self._range:
            lo, hi = self._range
            xl, xr = self._x_of(lo, x0, w), self._x_of(hi, x0, w)
            p.setBrush(QColor(0, 150, 255, 70)); p.setPen(QPen(QColor(0, 120, 200), 1.4))
            p.drawRect(QRectF(xl, y0 - 3, max(2.0, xr - xl), bar_h + 6))
        if self._f_hz and self.F_MIN <= self._f_hz <= self.F_MAX:
            xm = self._x_of(self._f_hz, x0, w)
            red = QColor(220, 30, 30)
            p.setPen(QPen(red, 2.0))
            # skip the label band in the middle of the strip
            p.drawLine(QPointF(xm, y0), QPointF(xm, y0 + bar_h * 0.28))
            p.drawLine(QPointF(xm, y0 + bar_h * 0.72), QPointF(xm, y0 + bar_h + 4))
            p.setPen(Qt.NoPen); p.setBrush(red)
            p.drawPolygon(QPolygonF([QPointF(xm, y0 + 1), QPointF(xm - 4.5, y0 - 6), QPointF(xm + 4.5, y0 - 6)]))
            rf = QFont(fam); rf.setPointSize(8); rf.setBold(True); p.setFont(rf); p.setPen(red)
            txt = eng(self._f_hz, "Hz")
            tw = p.fontMetrics().horizontalAdvance(txt)
            tx = min(max(xm - tw / 2, 2.0), self.width() - tw - 2)
            p.drawText(QPointF(tx, y0 - 8), txt)
        p.end()


class BandTable(QWidget):
    """Bands-tab composite widget: colour band-strip on top, then a
    System filter row, then a wide read-only data grid.

    Both layers update in lock-step:
      • set_freq()  – red marker on the strip + highlight rows whose
                      interval contains f
      • set_range() – blue overlay on the strip + filter the grid to
                      rows that overlap the range (clearing the range
                      input shows every row again)
    System checkboxes filter row visibility independently of the
    frequency / range driver."""

    HIGHLIGHT_BG = QColor(255, 235, 130)      # amber

    SYSTEMS = ("IEEE", "ITU", "NATO/ECM", "Waveguide", "Service")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._f_hz = None
        self._range = None
        self._lit_rows = set()
        # Take all the horizontal space the parent will give us — the
        # Bands tab card sets _diagram_full_width=True so the whole
        # panel spans the application window.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ---- band-strip figure ----
        self.chart = FreqBandChart(self)
        outer.addWidget(self.chart)

        # ---- system filter checkboxes + master "Filter" toggle ----
        # The "Filter" master, when checked, hides every row that doesn't
        # match the current frequency / range / band-name driver above.
        # When unchecked the conversion drivers only highlight matches —
        # they don't hide non-matching rows.  System checkboxes filter
        # independently in either mode.
        sys_row = QHBoxLayout()
        sys_row.setContentsMargins(2, 0, 2, 0)
        sys_row.setSpacing(10)
        self.filter_cb = QCheckBox("Filter")
        self.filter_cb.setChecked(False)
        self.filter_cb.setToolTip(
            "When checked, only rows that match the Frequency / Range / "
            "Band input above are shown.  Unchecked = highlight only.")
        self.filter_cb.toggled.connect(lambda *_: self._apply_filters())
        sys_row.addWidget(self.filter_cb)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setFrameShadow(QFrame.Sunken)
        sys_row.addWidget(sep)
        sys_label = QLabel("System:")
        sys_label.setStyleSheet("color:#555;")
        sys_row.addWidget(sys_label)
        self._sys_checkboxes = {}
        for s in self.SYSTEMS:
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.toggled.connect(lambda *_: self._apply_filters())
            self._sys_checkboxes[s] = cb
            sys_row.addWidget(cb)
        sys_row.addStretch(1)
        outer.addLayout(sys_row)

        # ---- data grid (full width) ----
        self.table = QTableWidget(len(BAND_TABLE), 4, self)
        self.table.setHorizontalHeaderLabels(["Band", "System", "Range", "Notes"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        # CLAUDE.md: no alternating row colours on data grids.
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(16)
        self.table.verticalHeader().setMinimumSectionSize(16)

        for r, (lo, hi, name, system, notes) in enumerate(BAND_TABLE):
            range_txt = f"{_fmt_band_freq(lo)} – {_fmt_band_freq(hi)}"
            cells = (
                (name,      Qt.AlignLeft   | Qt.AlignVCenter, name),
                (system,    Qt.AlignCenter,                   system),
                (range_txt, Qt.AlignRight  | Qt.AlignVCenter, range_txt),
                (notes,     Qt.AlignLeft   | Qt.AlignVCenter, notes),
            )
            for c, (txt, align, tip) in enumerate(cells):
                it = QTableWidgetItem(txt)
                it.setTextAlignment(align)
                it.setToolTip(tip)
                self.table.setItem(r, c, it)

        # Auto-size the first three columns to content; let Notes take
        # whatever remains.  Eliding keeps the cell narrow at small
        # window widths (the full text stays in the cell tooltip).
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setStretchLastSection(True)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setWordWrap(False)
        self.table.resizeColumnsToContents()

        # No height cap — the table fills whatever vertical space the
        # parent gives it.  Expanding size policy on both axes ensures
        # it grows to the bottom of the window.
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self.table, 1)

    # ---- public API (preserves the old FreqBandChart shape) ----------
    # set_freq and set_range are mutually exclusive — calling one clears
    # the other.  FreqBandCard.compute() picks exactly one per driver
    # path: Frequency field → set_freq (point match), Range or Band
    # field → set_range (overlap match + row filter).
    def set_freq(self, f_hz):
        self._f_hz = f_hz if (f_hz and f_hz > 0) else None
        self._range = None
        self.chart.set_freq(self._f_hz)
        self.chart.set_range(None, None)
        self._apply_filters()

    def set_range(self, lo, hi):
        self._range = (lo, hi) if (lo and hi and hi > lo) else None
        self._f_hz = None
        self.chart.set_freq(None)
        if self._range:
            self.chart.set_range(*self._range)
        else:
            self.chart.set_range(None, None)
        self._apply_filters()

    # ---- internal ----------------------------------------------------
    def _apply_filters(self):
        # Clear previous highlights
        for r in self._lit_rows:
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it is not None:
                    it.setBackground(QColor(0, 0, 0, 0))
        self._lit_rows.clear()

        selected = {s for s, cb in self._sys_checkboxes.items()
                    if cb.isChecked()}
        filter_on = bool(self.filter_cb.isChecked())

        # Whether a row "matches the conversion driver" — used both for
        # highlight and (when the master Filter toggle is on) for
        # visibility.  No driver set → every row matches.
        def matches(blo, bhi):
            if self._range is not None:
                lo, hi = self._range
                return not (bhi <= lo or blo >= hi)
            if self._f_hz is not None:
                return blo <= self._f_hz < bhi
            return True

        for r, (blo, bhi, name, system, notes) in enumerate(BAND_TABLE):
            visible = system in selected
            if visible and filter_on:
                visible = matches(blo, bhi)
            self.table.setRowHidden(r, not visible)
            if visible and matches(blo, bhi) and (
                    self._range is not None or self._f_hz is not None):
                self._lit_rows.add(r)

        for r in self._lit_rows:
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it is not None:
                    it.setBackground(self.HIGHLIGHT_BG)

    # ---- persistence (filter / system checkbox state) ----------------
    def get_filter_state(self):
        return {
            "filter":  bool(self.filter_cb.isChecked()),
            "systems": {s: bool(cb.isChecked())
                        for s, cb in self._sys_checkboxes.items()},
        }

    def set_filter_state(self, st):
        if not isinstance(st, dict):
            return
        if "filter" in st:
            self.filter_cb.blockSignals(True)
            self.filter_cb.setChecked(bool(st["filter"]))
            self.filter_cb.blockSignals(False)
        systems = st.get("systems") or {}
        if isinstance(systems, dict):
            for s, cb in self._sys_checkboxes.items():
                if s in systems:
                    cb.blockSignals(True)
                    cb.setChecked(bool(systems[s]))
                    cb.blockSignals(False)
        self._apply_filters()

        # Scroll the first highlighted, visible row into view
        for r in sorted(self._lit_rows):
            if not self.table.isRowHidden(r):
                self.table.scrollToItem(
                    self.table.item(r, 0),
                    QAbstractItemView.PositionAtCenter,
                )
                break


class FreqBandCard(CalcCard):
    """Look up a frequency, a frequency range, or an IEEE/ITU band name in
    the IEEE / ITU / common-service tables.  Type into any of:

      Frequency  →  prints the containing IEEE / ITU / service bands
      Range      →  e.g.  "100-200" (MHz assumed),  "1-2 GHz",  "8G to 12G"
                    prints the bands that overlap the range
      Band name  →  e.g.  "X", "Ku", "VHF" → prints the corresponding range
    """
    _diagram_above = True
    # The Bands panel (chart + checkboxes + datagrid) wants the full
    # window width, not just its sizeHint — _build_ui drops the
    # AlignLeft flag for cards that opt in.
    _diagram_full_width = True

    @staticmethod
    def _parse_range(text):
        """Return (lo_hz, hi_hz) or None.  A side with no engineering suffix
        defaults to MHz; a side with a suffix is already absolute Hz."""
        if not text or not text.strip():
            return None
        s = text.strip()
        # Normalize "*Hz" units (case-insensitive) into bare engineering
        # suffix characters that parse() understands.  Order matters — strip
        # the longer matches first.
        for old, new in (("GHz", "G"), ("MHz", "M"), ("kHz", "k"),
                         ("KHz", "k"), ("ghz", "G"), ("mhz", "M"),
                         ("khz", "k"), ("Hz", ""), ("hz", "")):
            s = s.replace(old, new)
        sep = None
        for cand in (" to ", "..", "—", "–", "-"):
            if cand in s:
                sep = cand; break
        if sep is None:
            return None
        lo_s, hi_s = (x.strip() for x in s.split(sep, 1))

        suff_chars = "TGMkKmunpfµ"   # matches parse()'s suffix table

        def to_hz(side):
            v = parse(side)
            if v is None:
                return None
            last = side[-1] if side else ""
            if last not in suff_chars:
                v *= 1e6                  # bare number → MHz default
            return v

        lo = to_hz(lo_s); hi = to_hz(hi_s)
        if lo is None or hi is None:
            return None
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    @staticmethod
    def _find_named_band(name):
        """Return (lo_hz, hi_hz, source) for an IEEE or ITU band name match,
        or None.  Source is 'ieee' or 'itu'."""
        if not name:
            return None
        target = name.strip().upper()
        for lo, hi, n in IEEE_BANDS:
            if n.upper().split()[0] == target or n.upper() == target:
                return (lo, hi, "ieee", n)
        for lo, hi, n in ITU_BANDS:
            if n.upper() == target:
                return (lo, hi, "itu", n)
        return None

    def __init__(self):
        super().__init__("Frequency band lookup", [
            Field("f_mhz",  "Frequency",       "MHz"),
            Field("range",  "Range",           ""),
            Field("name",   "Band",            ""),
            Field("ieee",   "IEEE band",       "", is_output=True),
            Field("itu",    "ITU band",        "", is_output=True),
            Field("common", "Common services", "", is_output=True),
        ])
        # Hint text for the two free-form inputs
        self.fields["range"].edit.setPlaceholderText("100-200, 1-2 GHz, 8G–12G")
        self.fields["name"].edit.setPlaceholderText("X, Ku, VHF")

    def make_diagram(self):
        self._chart = BandTable()
        return self._chart

    # ---- card-level state persists the BandTable filter checkboxes ----
    def get_card_state(self):
        st = super().get_card_state() or {}
        chart = getattr(self, "_chart", None)
        if chart is not None:
            st["bands"] = chart.get_filter_state()
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if isinstance(state, dict):
            chart = getattr(self, "_chart", None)
            if chart is not None and isinstance(state.get("bands"), dict):
                chart.set_filter_state(state["bands"])

    def _set_chart_freq(self, f_hz):
        chart = getattr(self, "_chart", None)
        if chart is not None:
            chart.set_freq(f_hz)

    def _set_chart_range(self, lo, hi):
        chart = getattr(self, "_chart", None)
        if chart is not None:
            chart.set_range(lo, hi)

    def compute(self, driver, v):
        # Free-form fields: read the raw text directly because parse() will
        # have nulled them out in `v`.
        range_txt = self.fields["range"].edit.text() if "range" in self.fields else ""
        name_txt  = self.fields["name"].edit.text()  if "name"  in self.fields else ""

        if driver == "name":
            hit = self._find_named_band(name_txt)
            if hit is None:
                self._set_chart_range(None, None)
                return {}
            lo, hi, source, full_name = hit
            f_mid = sqrt(lo * hi)
            # Band/range lookups → highlight every overlapping row.
            self._set_chart_range(lo, hi)
            return {
                "f_mhz":  f_mid / 1e6,
                "range":  f"{lo/1e6:g}–{hi/1e6:g} MHz",
                "ieee":   full_name if source == "ieee" else "—",
                "itu":    full_name if source == "itu"  else "—",
                "common": "—",
            }

        if driver == "range":
            r = self._parse_range(range_txt)
            if r is None:
                self._set_chart_range(None, None)
                return {}
            lo, hi = r
            f_mid = sqrt(lo * hi)
            ieees   = [n for blo, bhi, n in IEEE_BANDS   if not (bhi <= lo or blo >= hi)]
            itus    = [n for blo, bhi, n in ITU_BANDS    if not (bhi <= lo or blo >= hi)]
            commons = [n for blo, bhi, n in COMMON_BANDS if not (bhi <= lo or blo >= hi)]
            self._set_chart_range(lo, hi)
            return {
                "f_mhz":  f_mid / 1e6,
                "name":   ", ".join({n.split()[0] for n in ieees}) or "—",
                "ieee":   ", ".join(ieees)   if ieees   else "—",
                "itu":    ", ".join(itus)    if itus    else "—",
                "common": "; ".join(commons) if commons else "—",
            }

        # Driver is f_mhz (or any other numeric field that fed into v)
        f = v.get("f_mhz")
        if f is None or f <= 0:
            self._set_chart_freq(None)
            return {"ieee": "", "itu": "", "common": "", "range": "", "name": ""}
        f_hz = f * 1e6
        out = {}
        ieee = "—"; ieee_lo = ieee_hi = None
        for lo, hi, name in IEEE_BANDS:
            if lo <= f_hz < hi:
                ieee = name; ieee_lo, ieee_hi = lo, hi
                out["range"] = f"{lo/1e6:g}–{hi/1e6:g} MHz"
                out["name"]  = name.split()[0]
                break
        itu = "—"
        for lo, hi, name in ITU_BANDS:
            if lo <= f_hz < hi:
                itu = name; break
        matches = [name for lo, hi, name in COMMON_BANDS if lo <= f_hz <= hi]
        out["ieee"]   = ieee
        out["itu"]    = itu
        out["common"] = "; ".join(matches) if matches else "—"
        # Single-frequency lookup → highlight only the rows whose interval
        # contains f.  set_freq clears any prior range mode automatically.
        self._set_chart_freq(f_hz)
        return out


# ====================================================================
#  CABLE / TRANSMISSION LINE
# ====================================================================

# ---------- coax cable database (loss in dB / 100 ft, from public datasheets) ----------
# Each entry: list of (f_MHz, loss_dB_per_100ft).  Lookup interpolates log-log.
CABLES = {
    "(custom)":      None,
    "RG-58":         [(50, 1.5), (146, 2.6), (450, 4.6), (900, 6.7), (2000, 10.0), (5800, 18.0)],
    "RG-58 (foam)":  [(50, 1.2), (146, 2.1), (450, 3.7), (900, 5.5), (2000, 8.5),  (5800, 15.5)],
    "RG-8":          [(50, 0.7), (146, 1.3), (450, 2.3), (900, 3.4), (2000, 5.4),  (5800, 11.0)],
    "RG-8X":         [(50, 1.0), (146, 1.8), (450, 3.2), (900, 4.6), (2000, 7.3),  (5800, 14.0)],
    "RG-174":        [(50, 3.5), (146, 6.0), (450, 11.0),(900, 17.0),(2000, 28.0), (5800, 60.0)],
    "RG-178":        [(50, 5.6), (146, 9.0), (450, 16.0),(900, 24.0),(2000, 38.0), (5800, 80.0)],
    "RG-188":        [(50, 3.1), (146, 5.4), (450, 9.6), (900, 14.0),(2000, 22.0), (5800, 47.0)],
    "RG-213":        [(50, 0.9), (146, 1.6), (450, 2.8), (900, 4.0), (2000, 6.0),  (5800, 12.0)],
    "RG-214":        [(50, 0.9), (146, 1.6), (450, 2.8), (900, 4.0), (2000, 6.0),  (5800, 12.0)],
    "RG-316":        [(50, 3.2), (146, 5.5), (450, 10.0),(900, 15.0),(2000, 23.0), (5800, 48.0)],
    "LMR-100A":      [(50, 1.7), (146, 2.8), (450, 5.0), (900, 7.1), (2000, 10.9), (5800, 19.6)],
    "LMR-195":       [(50, 1.0), (146, 1.7), (450, 3.1), (900, 4.4), (2000, 6.7),  (5800, 12.5)],
    "LMR-200":       [(50, 0.9), (146, 1.5), (450, 2.7), (900, 3.9), (2000, 5.9),  (5800, 10.6)],
    "LMR-240":       [(50, 0.7), (146, 1.3), (450, 2.3), (900, 3.3), (2000, 5.0),  (5800, 9.0)],
    "LMR-300":       [(50, 0.5), (146, 1.0), (450, 1.7), (900, 2.5), (2000, 3.8),  (5800, 6.8)],
    "LMR-400":       [(50, 0.5), (146, 0.9), (450, 1.5), (900, 2.2), (2000, 3.4),  (5800, 6.0)],
    "LMR-500":       [(50, 0.4), (146, 0.7), (450, 1.3), (900, 1.8), (2000, 2.8),  (5800, 5.0)],
    "LMR-600":       [(50, 0.3), (146, 0.6), (450, 1.0), (900, 1.5), (2000, 2.3),  (5800, 4.1)],
    "LMR-900":       [(50, 0.2), (146, 0.4), (450, 0.7), (900, 1.0), (2000, 1.5),  (5800, 2.7)],
    "LMR-1200":      [(50, 0.2), (146, 0.3), (450, 0.5), (900, 0.7), (2000, 1.1),  (5800, 2.0)],
    'Heliax LDF4-50A 1/2"':  [(50, 0.2), (146, 0.4), (450, 0.7), (900, 1.0), (2000, 1.5), (5800, 2.6)],
    'Heliax LDF5-50A 7/8"':  [(50, 0.1), (146, 0.2), (450, 0.4), (900, 0.6), (2000, 0.9), (5800, 1.5)],
    'Heliax LDF7-50A 1-5/8"':[(50, 0.07),(146, 0.13),(450, 0.24),(900, 0.35),(2000, 0.56),(5800, 1.0)],
}


def cable_loss_db_per_100ft(name, f_mhz):
    """Interpolate the cable's loss/100ft at f_mhz (log-log between table points)."""
    data = CABLES.get(name)
    if not data or f_mhz is None or f_mhz <= 0:
        return None
    if f_mhz <= data[0][0]:
        return data[0][1]
    if f_mhz >= data[-1][0]:
        return data[-1][1]
    for i in range(len(data) - 1):
        f1, l1 = data[i]; f2, l2 = data[i + 1]
        if f1 <= f_mhz <= f2:
            return l1 * (l2 / l1) ** ((log(f_mhz) - log(f1)) / (log(f2) - log(f1)))
    return None


class CableLossCard(CalcCard):
    """Cable loss with a built-in coax database (RG / LMR / Heliax).
    Pick a cable + frequency and the loss/100ft auto-populates."""
    def __init__(self):
        super().__init__("Cable Loss (with coax library)", [
            Field("f_mhz",          "Frequency", "MHz"),
            Field("loss_per_100ft", "Loss per 100 ft", "dB"),
            Field("length_ft",      "Length", "ft"),
            Field("length_m",       "Length", "m"),
            Field("total_loss",     "Total loss", "dB", is_output=True),
            Field("p_in_dbm",       "Input power", "dBm"),
            Field("p_out_dbm",      "Output power", "dBm", is_output=True),
            Field("eff_pct",        "Efficiency", "%", is_output=True),
        ])
        self._cable = "(custom)"
        self._cable_combo = None

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Cable:"))
        c = QComboBox()
        for name in CABLES:
            c.addItem(name)
        c.setMinimumWidth(190)
        c.setMaximumHeight(20)
        c.currentTextChanged.connect(self._on_cable_changed)
        self._cable_combo = c
        h.addWidget(c)
        h.addStretch(1)
        return w

    def _on_cable_changed(self, name):
        self._cable = name
        if name == "(custom)":
            return
        f_mhz = parse(self.fields["f_mhz"].edit.text())
        if f_mhz is None or f_mhz <= 0:
            return
        loss = cable_loss_db_per_100ft(name, f_mhz)
        if loss is None:
            return
        self.fields["loss_per_100ft"].edit.blockSignals(True)
        self.fields["loss_per_100ft"].edit.setText(fmt(loss))
        self.fields["loss_per_100ft"].edit.blockSignals(False)
        self.recompute_from_inputs()

    def get_card_state(self):
        st = super().get_card_state()
        st["cable"] = self._cable
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if isinstance(state, dict) and self._cable_combo is not None:
            name = state.get("cable")
            if isinstance(name, str):
                i = self._cable_combo.findText(name)
                if i >= 0:
                    self._cable_combo.setCurrentIndex(i)

    def compute(self, driver, v):
        f_mhz = v.get("f_mhz")
        out = {}
        if self._cable != "(custom)" and f_mhz is not None and f_mhz > 0:
            loss = cable_loss_db_per_100ft(self._cable, f_mhz)
            if loss is not None:
                v["loss_per_100ft"] = loss
                out["loss_per_100ft"] = loss
        lp = v.get("loss_per_100ft"); lf = v.get("length_ft"); lm = v.get("length_m")
        if driver == "length_m" and lm is not None: lf = lm / 0.3048
        elif driver == "length_ft" and lf is not None: lm = lf * 0.3048
        out["length_ft"] = lf; out["length_m"] = lm
        if lp is not None and lf is not None:
            tot = lp * lf / 100.0
            out["total_loss"] = tot
            pin = v.get("p_in_dbm")
            if pin is not None:
                out["p_out_dbm"] = pin - tot
                out["eff_pct"] = 10 ** (-tot / 10) * 100
        return out


class SkinDepthCard(CalcCard):
    CONDUCTORS = {
        "Copper":   1.68e-8,
        "Aluminum": 2.65e-8,
        "Silver":   1.59e-8,
        "Gold":     2.44e-8,
        "Brass":    7.0e-8,
        "Steel":    1.43e-7,
    }

    def __init__(self):
        super().__init__("Skin Depth (δ = sqrt(ρ/πfμ))", [
            Field("f_mhz",   "Frequency", "MHz"),
            Field("rho",     "Resistivity ρ", "Ω·m"),
            Field("delta_um","Skin depth δ", "µm", is_output=True),
            Field("delta_mil","Skin depth δ", "mil", is_output=True),
            Field("rs_mohm", "Sheet resistance Rs", "mΩ/sq", is_output=True),
        ])
        # default: copper resistivity
        self.fields["rho"].edit.setText("1.68e-8")

    def make_diagram(self):
        return SkinDepthDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); rho = v.get("rho")
        if f is None or rho is None or f <= 0 or rho <= 0: return {}
        delta = sqrt(rho / (pi * f * 1e6 * MU0))
        Rs = rho / delta  # ohm/square
        return {
            "delta_um": delta * 1e6,
            "delta_mil": delta * 1e6 / 25.4,
            "rs_mohm": Rs * 1e3,
        }


# ---------- material library (εr at 10 GHz, from Rogers product selector + common refs) ----------
MATERIALS = [
    # (display name, εr, tan δ @ 10 GHz)  — None εr = "(custom)" sentinel, no auto-fill
    ("(custom)",                None,  None),
    ("Air",                     1.0006, 0.0),
    ("FR-4 (typ.)",             4.4,   0.020),
    ("PTFE / Teflon",           2.1,   0.0002),
    ("Alumina (99.5%)",         9.8,   0.0001),
    ("Rogers RO3003",           3.00,  0.0010),
    ("Rogers RO3006",           6.15,  0.0020),
    ("Rogers RO3010",           10.2,  0.0023),
    ("Rogers RO3203",           3.02,  0.0016),
    ("Rogers RO3210",           10.2,  0.0027),
    ("Rogers RO4003C",          3.38,  0.0027),
    ("Rogers RO4350B",          3.48,  0.0037),
    ("Rogers RO4450B",          3.54,  0.0040),
    ("Rogers RT/duroid 5870",   2.33,  0.0012),
    ("Rogers RT/duroid 5880",   2.20,  0.0009),
    ("Rogers RT/duroid 6002",   2.94,  0.0012),
    ("Rogers RT/duroid 6006",   6.15,  0.0019),
    ("Rogers RT/duroid 6010LM", 10.2,  0.0023),
    ("Rogers TMM3",             3.27,  0.0020),
    ("Rogers TMM4",             4.50,  0.0020),
    ("Rogers TMM6",             6.00,  0.0023),
    ("Rogers TMM10",            9.20,  0.0023),
    ("Rogers TMM10i",           9.80,  0.0023),
    ("Rogers ULTRALAM 2000",    2.50,  0.0019),
]


CONDUCTORS = [
    # (display name, resistivity ρ in Ω·m at ≈20 °C — standard CODATA values)
    ("Copper",   1.68e-8),
    ("Silver",   1.59e-8),
    ("Gold",     2.44e-8),
    ("Aluminum", 2.65e-8),
    ("Brass",    7.0e-8),
    ("Nickel",   6.99e-8),
    ("Tin",      11.0e-8),
    ("Lead",     22.0e-8),
]


class TLineCard(CalcCard):
    """Base for transmission-line cards with three extra controls:
       Material library  |  Solve-for selector  |  mm/mil unit toggle.

    Subclasses set:
      DIM_FIELDS  — tuple of length-valued field names (toggled by units)
      SOLVABLE    — tuple of field names that can be the unknown
                    (first entry is the default)
      SOLVE_LABEL — display text for the solve-for combo, by field name
      ER_FIELD    — name of the εr field the material library writes into
                    (default 'er')

    Subclasses override compute(driver, v) and consult self._unknown to
    decide which variable to solve for.  Helper _bisect() solves
    monotonic forward formulas numerically.

    Subclasses may also override loss_components_db_per_m(f_hz) to return
    (conductor, dielectric) loss; when present, the base class wires up a
    "Loss table…" button and the Cond./Diel./Total Loss read-out fields.
    """
    DIM_FIELDS  = ()
    SOLVABLE    = ()
    SOLVE_LABEL = {}
    ER_FIELD    = "er"

    def __init__(self, title, fields):
        # init *before* super so make_extras (called from _build_ui) sees them
        self._unit         = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "mm"
        self._unknown      = self.SOLVABLE[0] if self.SOLVABLE else None
        self._material     = "(custom)"
        self._tan_d        = None      # set when a material is selected
        self._cond_rho     = 1.68e-8   # default copper
        self._cond_name    = "Copper"
        self._solve_combo  = None
        self._mat_combo    = None
        self._cond_combo   = None
        self._length_edit  = None
        self._loss_btn     = None
        super().__init__(title, fields)
        self._sync_unknown_styling()
        # Sync DIM_FIELDS' displayed units to the global default after the
        # UI is built (Field instances were constructed with hard-coded
        # "mm" labels).
        self._sync_dim_unit_labels()
        # Seed the Frequency input (cards with a loss model) so the Loss
        # field computes out of the box; persisted state overrides it later.
        fq = self.fields.get("freq")
        if fq is not None and fq.edit is not None and not fq.edit.text().strip():
            fq.edit.blockSignals(True)
            fq.edit.setText("10")
            fq.edit.blockSignals(False)
        self._update_total_loss()

    # ------------------------------------------------------------------
    # extras rows (above the field grid)
    # ------------------------------------------------------------------
    def make_extras(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        # ---- top row: dielectric + solve + units --------------------
        top = QWidget(); h = QHBoxLayout(top)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Material:"))
        mat = QComboBox()
        for name, _er, _tan in MATERIALS:
            mat.addItem(name)
        mat.setMaximumHeight(20); mat.setMinimumWidth(150)
        mat.currentTextChanged.connect(self._on_material_changed)
        self._mat_combo = mat
        h.addWidget(mat)
        h.addSpacing(4); h.addWidget(QLabel("Solve:"))
        sv = QComboBox()
        for fname in self.SOLVABLE:
            sv.addItem(self.SOLVE_LABEL.get(fname, fname), fname)
        sv.setMaximumHeight(20); sv.setMinimumWidth(60)
        sv.currentIndexChanged.connect(self._on_solve_changed)
        self._solve_combo = sv
        h.addWidget(sv)
        # Length-unit picker removed — the unit comes from the global
        # `default_length_unit` setting and is applied uniformly to every
        # length field in the app.
        h.addStretch(1)
        v.addWidget(top)

        # ---- second row: conductor + length + loss table -----------
        # Only meaningful for cards that implement loss_components_db_per_m().
        # We always render the row (so the layout is uniform), but the
        # button is disabled on cards without a loss model.
        bot = QWidget(); h2 = QHBoxLayout(bot)
        h2.setContentsMargins(0, 0, 0, 0); h2.setSpacing(4)
        h2.addWidget(QLabel("Conductor:"))
        cc = QComboBox()
        for name, _rho in CONDUCTORS:
            cc.addItem(name)
        cc.setMaximumHeight(20); cc.setMinimumWidth(100)
        cc.currentTextChanged.connect(self._on_conductor_changed)
        self._cond_combo = cc
        h2.addWidget(cc)
        h2.addSpacing(4); h2.addWidget(QLabel("Length:"))
        le = QLineEdit("1")
        le.setMaximumHeight(18); le.setMaximumWidth(60)
        le.textEdited.connect(lambda *_: self._update_total_loss())
        self._length_edit = le
        h2.addWidget(le)
        h2.addWidget(QLabel("in"))
        # The computed loss now lives in the 'Loss' grid field (driven by the
        # 'Frequency' field + this Length); cards without a loss model have
        # neither field and just disable the conductor / length inputs.
        if not self.has_loss_model():
            le.setEnabled(False)
            cc.setEnabled(False)
        h2.addStretch(1)
        v.addWidget(bot)

        return w

    def make_extras_below(self):
        """Loss-table button, placed below the field grid so it doesn't
        widen the control column — letting the diagram sit further left."""
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        btn = QPushButton("Loss table…")
        btn.setMaximumHeight(20)
        btn.clicked.connect(self._open_loss_table)
        if not self.has_loss_model():
            btn.setEnabled(False)
            btn.setToolTip("No closed-form loss model implemented for this geometry yet.")
        self._loss_btn = btn
        h.addWidget(btn)
        h.addStretch(1)
        return w

    def has_loss_model(self):
        """A card has a loss model when it overrides loss_components_db_per_m()."""
        return type(self).loss_components_db_per_m is not \
            TLineCard.loss_components_db_per_m

    # Subclasses override to return (conductor_dB_per_m, dielectric_dB_per_m)
    # at f_hz, or None when the geometry / material isn't fully specified.
    def loss_components_db_per_m(self, f_hz):
        return None

    def loss_db_per_m(self, f_hz):
        """Total loss (dB/m) = conductor + dielectric.  Consumed by the
        loss-table dialog; subclasses supply the split via
        loss_components_db_per_m()."""
        c = self.loss_components_db_per_m(f_hz)
        return None if c is None else (c[0] + c[1])

    def _surface_roughness_m(self):
        """RMS conductor surface roughness (metres) from the card's 'rough'
        field (entered in µm).  0 when absent/blank → smooth conductor."""
        f = self.fields.get("rough")
        if f is not None and f.edit is not None:
            val = parse(f.edit.text())
            if val is not None and val > 0:
                return val * 1e-6
        return 0.0

    def _roughness_factor(self, f_hz):
        """Hammerstad-Bekkadal conductor-roughness multiplier
        Kr = 1 + (2/π)·atan(1.4·(Δ/δ)²), δ = skin depth at f_hz.
        Saturates near 2; equals 1 for a smooth conductor."""
        rough = self._surface_roughness_m()
        if rough <= 0 or f_hz is None or f_hz <= 0:
            return 1.0
        delta = sqrt(self._cond_rho / (pi * f_hz * MU0))   # skin depth (m)
        if delta <= 0:
            return 1.0
        return 1.0 + (2.0 / pi) * atan(1.4 * (rough / delta) ** 2)

    def _on_conductor_changed(self, name):
        for n, rho in CONDUCTORS:
            if n == name:
                self._cond_name = n
                self._cond_rho = rho
                self._update_total_loss()
                return

    def _update_total_loss(self):
        """Populate the read-only conductor / dielectric / total Loss fields
        with the loss over the current Length at the current Frequency.
        No-op on cards without a loss model or loss fields."""
        if self.fields.get("loss") is None or not self.has_loss_model():
            return
        f = self._loss_eval_frequency()
        L_in = parse(self._length_edit.text() if self._length_edit else "0")
        cc = dd = tt = None
        if f is not None and f > 0 and L_in is not None:
            try:
                comps = self.loss_components_db_per_m(f)
            except Exception:
                comps = None
            if comps is not None:
                L_m = L_in * 0.0254
                cc = comps[0] * L_m
                dd = comps[1] * L_m
                tt = cc + dd
        self._set_loss_field("loss_c", cc)
        self._set_loss_field("loss_d", dd)
        self._set_loss_field("loss",   tt)

    def _set_loss_field(self, name, value):
        f = self.fields.get(name)
        if f is None or f.edit is None:
            return
        f.edit.blockSignals(True)
        f.edit.setText(fmt(value) if value is not None else "")
        f.edit.blockSignals(False)

    def _loss_eval_frequency(self):
        """Frequency (Hz) for the Loss field, taken from the card's
        'Frequency' input (honouring its display unit).  Falls back to
        10 GHz when there is no freq field or the box is blank/invalid."""
        f = self.fields.get("freq")
        if f is not None and f.edit is not None:
            val = parse_field(f.edit.text(), f.unit)
            if val is not None:
                tup = _calc_to_base(val, f.unit)
                if tup is not None and tup[0] == "freq" and tup[1] > 0:
                    return tup[1]
        return 10.0e9

    def _open_loss_table(self):
        if not self.has_loss_model():
            return
        TLineLossTableDialog(self, parent=self.window()).exec_()

    # ------------------------------------------------------------------
    # styling
    # ------------------------------------------------------------------
    def _sync_unknown_styling(self):
        for fname in self.SOLVABLE:
            f = self.fields.get(fname)
            if f is None or f.edit is None:
                continue
            pal = f.edit.palette()
            if fname == self._unknown:
                pal.setColor(QPalette.Base, FIELD_BG_SOLVED)
            else:
                pal.setColor(QPalette.Base, QColor(255, 255, 255))
            f.edit.setPalette(pal)

    def _idle_field_bg(self, edit):
        """Keep the solve-for target field tinted even after it loses focus;
        every other input reverts to white."""
        f = self.fields.get(self._unknown) if self._unknown else None
        if f is not None and f.edit is edit:
            return FIELD_BG_SOLVED
        return FIELD_BG_INPUT_IDLE

    # ------------------------------------------------------------------
    # combo handlers
    # ------------------------------------------------------------------
    def _on_solve_changed(self, idx):
        if idx < 0 or idx >= len(self.SOLVABLE):
            return
        new_unknown = self.SOLVABLE[idx]
        if new_unknown == self._unknown:
            return
        self._unknown = new_unknown
        self._sync_unknown_styling()
        self.recompute_from_inputs()

    def _on_material_changed(self, name):
        for n, er, tan_d in MATERIALS:
            if n != name:
                continue
            self._material = name
            self._tan_d    = tan_d           # may be None for "(custom)"
            if er is not None:
                f = self.fields.get(self.ER_FIELD)
                if f is not None and f.edit is not None:
                    f.edit.blockSignals(True)
                    f.edit.setText(fmt(er))
                    f.edit.blockSignals(False)
                    if self._unknown != self.ER_FIELD:
                        self.recompute_from_inputs()
            self._update_total_loss()
            return

    def recompute_from_inputs(self):
        """Re-solve self._unknown from the current inputs and write the
        result back — including the unknown itself.

        The base version picks the first non-None input as a pseudo-driver
        and skips writing that key, which silently drops the unknown when it
        happens to sort first in the field order (e.g. Microstrip 'w' with
        Solve=W).  compute() here keys off self._unknown, so we drive from
        any *other* input and stamp every returned field."""
        self._refresh_figure()
        if self._unknown is None:
            return super().recompute_from_inputs()
        vals = self._collect()
        driver = next((n for n in vals
                       if n != self._unknown and vals[n] is not None
                       and not self.fields[n].is_output),
                      self._unknown)
        try:
            results = self.compute(driver, vals)
        except Exception:
            results = None
        if results:
            self._updating = True
            try:
                for k, val in results.items():
                    f = self.fields.get(k)
                    if not f or f.edit is None:
                        continue
                    val_disp = self._to_display(val, f)
                    f.edit.setText(self._format_for_field(val_disp, f))
                    self._maybe_relabel_unit(f, f.edit.text())
            finally:
                self._updating = False
        # Loss depends on geometry / conductor / frequency / length — refresh
        # the read-only Loss field on every recompute (also covers the
        # post-restore recompute in _restore_form_state).
        self._update_total_loss()

    def _on_edit(self, driver, text):
        """After the base per-field recompute, refresh the Loss field so it
        tracks edits to geometry, frequency and εr in real time.  Writing the
        Loss field blocks signals, so this never recurses — and typing into
        the read-only Loss field just gets overwritten with the computed
        value (it is always solved)."""
        super()._on_edit(driver, text)
        self._update_total_loss()

    def apply_global_length_unit(self):
        """Re-render this card in the current global length unit
        (DEFAULT_LENGTH_UNIT).  Field unit labels are swapped and any
        existing values are converted so the underlying physical
        dimensions stay the same."""
        new_unit = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "mm"
        self._cascade_length_unit(new_unit)

    def _switch_field_unit(self, field, new_unit):
        """Quick-select on a unit label.  Length fields cascade across all
        DIM_FIELDS so the card stays internally consistent; everything
        else falls through to CalcCard's per-field default."""
        if field is not None and field.name in self.DIM_FIELDS \
                and new_unit in VALID_LENGTH_UNITS:
            self._cascade_length_unit(new_unit)
            return
        super()._switch_field_unit(field, new_unit)

    def _cascade_length_unit(self, new_unit):
        if new_unit not in VALID_LENGTH_UNITS or new_unit == self._unit:
            self._sync_dim_unit_labels()
            return
        old_factor = LENGTH_TO_MM[self._unit]
        new_factor = LENGTH_TO_MM[new_unit]
        scale = old_factor / new_factor
        self._unit = new_unit
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None or f.edit is None:
                continue
            txt = f.edit.text().strip()
            if txt:
                v = parse(txt)
                if v is not None:
                    f.edit.blockSignals(True)
                    f.edit.setText(fmt(v * scale))
                    f.edit.blockSignals(False)
        self._sync_dim_unit_labels()
        self.recompute_from_inputs()

    def _sync_dim_unit_labels(self):
        """Push self._unit onto every DIM_FIELDS' unit-label widget and
        Field.unit / Field.declared_unit attributes.  Keeping declared in
        sync with display means CalcCard's _to_declared boundary
        conversion is a no-op for these fields — _dim_to_mm already does
        the unit→mm step that compute() relies on."""
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None:
                continue
            f.unit = self._unit
            f.declared_unit = self._unit
            if f.unit_label is not None:
                f.unit_label.setText(self._unit)

    # ------------------------------------------------------------------
    # length-unit conversion helpers (all formulas work in mm)
    # ------------------------------------------------------------------
    def _dim_to_mm(self, value):
        if value is None:
            return None
        return value * LENGTH_TO_MM.get(self._unit, 1.0)

    def _mm_to_dim(self, value):
        if value is None:
            return None
        return value / LENGTH_TO_MM.get(self._unit, 1.0)

    # ------------------------------------------------------------------
    # numerical solver — bisection on a monotonic forward formula
    # ------------------------------------------------------------------
    @staticmethod
    def _bisect(fn, target, lo, hi, increasing, tol=1e-10, max_iter=80):
        try:
            f_lo = fn(lo); f_hi = fn(hi)
        except Exception:
            return None
        if f_lo is None or f_hi is None:
            return None
        if increasing:
            if target < f_lo or target > f_hi:
                return None
        else:
            if target > f_lo or target < f_hi:
                return None
        for _ in range(max_iter):
            mid = (lo + hi) / 2
            try:
                fm = fn(mid)
            except Exception:
                return None
            if fm is None:
                return None
            if (increasing and fm > target) or (not increasing and fm < target):
                hi = mid
            else:
                lo = mid
            if (hi - lo) < tol * max(1.0, abs(mid)):
                break
        return (lo + hi) / 2

    # ------------------------------------------------------------------
    # persistence — save/restore selectors with the form state
    # ------------------------------------------------------------------
    def get_card_state(self):
        st = super().get_card_state()
        st.update({
            "unit":     self._unit,
            "unknown":  self._unknown,
            "material": self._material,
        })
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if not isinstance(state, dict):
            return
        # The "unit" key from older saves is intentionally ignored now —
        # the length unit is taken from the global default on each launch.
        un = state.get("unknown")
        if un in self.SOLVABLE and self._solve_combo is not None:
            self._solve_combo.setCurrentIndex(self.SOLVABLE.index(un))
        mat = state.get("material")
        if isinstance(mat, str) and self._mat_combo is not None:
            i = self._mat_combo.findText(mat)
            if i >= 0:
                self._mat_combo.setCurrentIndex(i)


class CoaxZ0Card(TLineCard):
    """Air/dielectric coax characteristic impedance.

      Forward:  Z₀ = (60 / √εr) · ln(D/d),   Vf = 1/√εr
      Inverse:  D = d · exp(Z₀ · √εr / 60)
                d = D / exp(Z₀ · √εr / 60)
                εr = (60 · ln(D/d) / Z₀)²
    """
    DIM_FIELDS  = ("D", "d")
    SOLVABLE    = ("z0", "D", "d", "er")
    SOLVE_LABEL = {"z0": "Z₀", "D": "D", "d": "d", "er": "εr"}

    def __init__(self):
        super().__init__("Coax Z₀ from D / d / εr", [
            Field("D",  "Outer conductor ID (D)", "mm"),
            Field("d",  "Inner conductor OD (d)", "mm"),
            Field("er", "Dielectric εr",          ""),
            Field("z0", "Z₀",                     "Ω"),
            Field("vf", "Velocity factor",        "", is_output=True),
            Field("freq",   "Frequency",          "GHz"),
            Field("rough",  "Surface roughness",  "µm"),
            Field("loss_c", "Cond. loss",         "dB", is_output=True),
            Field("loss_d", "Diel. loss",         "dB", is_output=True),
            Field("loss",   "Total loss",         "dB", is_output=True),
        ])

    def make_diagram(self):
        return CoaxDiagram()

    def compute(self, driver, v):
        # Length values come in user units (mm or mil); convert to mm for the
        # formula and back when writing length results out.
        D  = self._dim_to_mm(v.get("D"))
        d  = self._dim_to_mm(v.get("d"))
        er = v.get("er")
        z0 = v.get("z0")
        unk = self._unknown

        if unk == "z0":
            if None in (D, d, er) or D <= 0 or d <= 0 or er <= 0 or D <= d:
                return {}
            z0_calc = (60.0 / sqrt(er)) * log(D / d)
            return {"z0": z0_calc, "vf": 1.0 / sqrt(er)}

        if unk == "D":
            if None in (z0, d, er) or z0 <= 0 or d <= 0 or er <= 0:
                return {}
            D_mm = d * math.exp(z0 * sqrt(er) / 60.0)
            return {"D": self._mm_to_dim(D_mm), "vf": 1.0 / sqrt(er)}

        if unk == "d":
            if None in (z0, D, er) or z0 <= 0 or D <= 0 or er <= 0:
                return {}
            d_mm = D / math.exp(z0 * sqrt(er) / 60.0)
            return {"d": self._mm_to_dim(d_mm), "vf": 1.0 / sqrt(er)}

        if unk == "er":
            if None in (z0, D, d) or z0 <= 0 or D <= 0 or d <= 0 or D <= d:
                return {}
            er_calc = (60.0 * log(D / d) / z0) ** 2
            if er_calc <= 0:
                return {}
            return {"er": er_calc, "vf": 1.0 / sqrt(er_calc)}

        return {}

    # ------------------------------------------------------------------
    # Coax loss model — conductor (skin effect on inner + outer) plus
    # uniform-fill dielectric tan δ.  Returns dB/m.
    # ------------------------------------------------------------------
    def loss_components_db_per_m(self, f_hz):
        v = self._collect()
        D_mm = self._dim_to_mm(v.get("D"))
        d_mm = self._dim_to_mm(v.get("d"))
        er   = v.get("er")
        if None in (D_mm, d_mm, er) or D_mm <= 0 or d_mm <= 0 or er <= 0 or D_mm <= d_mm:
            return None
        if f_hz is None or f_hz <= 0:
            return None
        a = (d_mm * 1e-3) / 2.0          # inner radius
        b = (D_mm * 1e-3) / 2.0          # outer radius
        z0 = (60.0 / sqrt(er)) * log(b / a)
        if z0 <= 0:
            return None
        Rs = sqrt(pi * f_hz * MU0 * self._cond_rho)
        alpha_c = (Rs / (4.0 * pi * z0)) * (1.0 / a + 1.0 / b) \
            * self._roughness_factor(f_hz)                             # Np/m
        tan_d = self._tan_d if self._tan_d is not None else 0.0
        k0 = 2 * pi * f_hz / C_LIGHT
        alpha_d = (k0 * sqrt(er) * tan_d) / 2.0                        # Np/m
        return alpha_c * NP2DB, alpha_d * NP2DB                        # dB/m


class MicrostripCard(TLineCard):
    DIM_FIELDS  = ("w", "h", "t")
    SOLVABLE    = ("z0", "w", "h", "er")
    SOLVE_LABEL = {"z0": "Z₀", "w": "W", "h": "h", "er": "εr"}

    def __init__(self):
        super().__init__("Microstrip Z₀ (Hammerstad)", [
            Field("w",  "Trace width W",      "mm"),
            Field("h",  "Substrate height h", "mm"),
            Field("t",  "Trace thickness t",  "mm"),
            Field("er", "Dielectric εr",      ""),
            Field("z0", "Z₀",                 "Ω"),
            Field("eeff",   "Effective ε",    "",  is_output=True),
            Field("vp_pct", "Vp (% of c)",    "%", is_output=True),
            Field("freq",   "Frequency",         "GHz"),
            Field("rough",  "Surface roughness", "µm"),
            Field("loss_c", "Cond. loss",        "dB", is_output=True),
            Field("loss_d", "Diel. loss",        "dB", is_output=True),
            Field("loss",   "Total loss",        "dB", is_output=True),
        ])

    def make_diagram(self):
        return MicrostripDiagram()

    @staticmethod
    def _eff_width(W, h, t):
        """Hammerstad/Wheeler conductor-thickness correction: a strip of
        finite thickness t behaves like a thin strip of larger width.
        Returns the effective width We (≥ W); no correction for t≤0 or t≥h.

        We = W + (t/π)·(1 + ln(2h/t))        for W/h ≥ 1/2π
        We = W + (t/π)·(1 + ln(4πW/t))       for W/h < 1/2π

        Matches the Rogers MWI microstrip calculator (e.g. RO3003, h=10 mil,
        t=1.4 mil, 50 Ω → 23.72 mil vs the thin-strip model's 25.35 mil)."""
        if t is None or t <= 0 or h <= 0 or t >= h or W <= 0:
            return W
        if W / h >= 1.0 / (2.0 * pi):
            dW = (t / pi) * (1.0 + log(2.0 * h / t))
        else:
            dW = (t / pi) * (1.0 + log(4.0 * pi * W / t))
        # Thickness can only widen the effective strip; the narrow-strip
        # branch goes negative for pathologically thin W (well outside the
        # model's validity and only hit at the far end of a solver bracket),
        # so floor the increment at zero to keep We positive and monotonic.
        return W + max(0.0, dW)

    @staticmethod
    def _z0_eeff(W, h, er, t=0.0):
        if W is None or h is None or er is None: return None
        if W <= 0 or h <= 0 or er <= 0: return None
        u = MicrostripCard._eff_width(W, h, t) / h
        if u <= 1:
            eeff = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + 0.04 * (1 - u) ** 2)
            z0 = 60 / sqrt(eeff) * log(8 / u + u / 4)
        else:
            eeff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
            z0 = 120 * pi / (sqrt(eeff) * (u + 1.393 + 0.667 * log(u + 1.444)))
        return z0, eeff

    def compute(self, driver, v):
        W  = self._dim_to_mm(v.get("w"))
        h  = self._dim_to_mm(v.get("h"))
        t  = self._dim_to_mm(v.get("t"))     # conductor thickness (mm), may be None
        er = v.get("er")
        z0 = v.get("z0")
        unk = self._unknown

        if unk == "z0":
            r = self._z0_eeff(W, h, er, t)
            if r is None: return {}
            return {"z0": r[0], "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if z0 is None or z0 <= 0:
            return {}
        if unk == "w":
            if h is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(x, h, er, t)[0], z0, 1e-4, 1e3, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(sol, h, er, t)
            return {"w": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "h":
            if W is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(W, x, er, t)[0], z0, 1e-4, 1e3, increasing=True)
            if sol is None: return {}
            r = self._z0_eeff(W, sol, er, t)
            return {"h": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "er":
            if W is None or h is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(W, h, x, t)[0], z0, 1.001, 100, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(W, h, sol, t)
            return {"er": sol, "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        return {}

    # ------------------------------------------------------------------
    # Loss model (Hammerstad-Jensen).  Conductor:
    #   α_c = Rs/(Z₀·W) · K_i · K_r
    # where K_i = exp(-1.2·(Z₀/η₀)^0.7) is the current-distribution factor
    # (≈0.75 at 50 Ω — the simple Rs/Z₀W alone overestimates) and K_r is the
    # Hammerstad-Bekkadal surface-roughness multiplier.  Dielectric is the
    # filling-factor × tan δ form.  Returns (conductor, dielectric) dB/m.
    # ------------------------------------------------------------------
    def loss_components_db_per_m(self, f_hz):
        v = self._collect()
        W_mm = self._dim_to_mm(v.get("w"))
        h_mm = self._dim_to_mm(v.get("h"))
        t_mm = self._dim_to_mm(v.get("t"))
        er   = v.get("er")
        if None in (W_mm, h_mm, er) or W_mm <= 0 or h_mm <= 0 or er <= 1:
            return None
        if f_hz is None or f_hz <= 0:
            return None
        W = W_mm * 1e-3
        r = self._z0_eeff(W_mm, h_mm, er, t_mm)
        if r is None:
            return None
        z0, eeff = r
        if z0 <= 0 or eeff <= 0:
            return None
        Rs = sqrt(pi * f_hz * MU0 * self._cond_rho)
        ki = exp(-1.2 * (z0 / ETA0) ** 0.7)                   # current distribution
        kr = self._roughness_factor(f_hz)                     # surface roughness
        alpha_c = (Rs / (z0 * W)) * ki * kr                   # Np/m
        tan_d = self._tan_d if self._tan_d is not None else 0.0
        k0 = 2 * pi * f_hz / C_LIGHT
        if er > 1.0:
            alpha_d = (k0 * er * (eeff - 1.0) * tan_d) / (2.0 * sqrt(eeff) * (er - 1.0))
        else:
            alpha_d = 0.0
        return alpha_c * NP2DB, alpha_d * NP2DB


# ====================================================================
#  TRANSMISSION LINE — diagrams + extra line types
# ====================================================================

# ====================================================================
#  Figure kit — every card figure draws on this.  Theme palette,
#  rdoc-style ANSI symbols (zigzag R, plate C, coil L, 3-bar ground;
#  outline-only, constant line weight), engineering dimension lines,
#  subscript labels whose boxes are recorded for the layout test, and
#  live values read from the owning card at paint time.
# ====================================================================
_SI_PREFIX = ((1e18, "E"), (1e15, "P"), (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""), (1e-3, "m"),
              (1e-6, "µ"), (1e-9, "n"), (1e-12, "p"), (1e-15, "f"))


def eng(v, unit=""):
    """3-significant-figure SI form: 22.1k, 4.7µF, 120nH."""
    if v is None or not math.isfinite(v):
        return ""
    if v == 0:
        return "0" + unit
    a = abs(v)
    scale, pre = 1e-15, "f"
    for s, pf in _SI_PREFIX:
        if a >= s * 0.9995:
            scale, pre = s, pf
            break
    x = v / scale
    t = f"{x:.3g}"
    if "e" in t:          # beyond the prefix table: plain fixed-point
        t = f"{x:.0f}" if abs(x) >= 1 else (f"{x:.3f}".rstrip("0").rstrip(".") or "0")
    return f"{t}{pre}{unit}"


def db_txt(v, unit="dB"):
    """Log-unit value (dB, dBm, dBi) to 3 significant figures, no SI prefix."""
    if v is None or not math.isfinite(v):
        return ""
    a = abs(v)
    t = f"{v:.{0 if a >= 100 else 1 if a >= 10 else 2}f}"
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    if t in ("-0", ""):
        t = "0"
    return f"{t}{unit}"


def sig3(v):
    """3 significant figures, fixed-point, no exponent (areas, ratios)."""
    if v is None or not math.isfinite(v):
        return ""
    if v == 0:
        return "0"
    if abs(v) >= 1e6:
        return eng(v)
    t = f"{v:.{max(0, 2 - math.floor(math.log10(abs(v))))}f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _text_runs(s):
    """'V_{out}' / 'R_1' / 'x^{2}' -> [(text, kind)], kind 0 base, -1 sub, +1 sup."""
    out, buf, i = [], "", 0
    while i < len(s):
        c = s[i]
        if c in "_^" and i + 1 < len(s):
            if buf:
                out.append((buf, 0)); buf = ""
            kind = -1 if c == "_" else 1
            if s[i + 1] == "{":
                j = s.index("}", i + 2)
                out.append((s[i + 2:j], kind)); i = j + 1
            else:
                out.append((s[i + 1], kind)); i += 2
            continue
        buf += c; i += 1
    if buf:
        out.append((buf, 0))
    return out


class _FigPalette:
    def __init__(self, dark):
        if dark:
            self.ink, self.muted = QColor(222, 222, 222), QColor(150, 150, 150)
            self.dim, self.sig = QColor(120, 170, 240), QColor(111, 163, 255)
            self.cu, self.cu_edge = QColor(201, 138, 69), QColor(236, 178, 112)
            self.diel, self.diel_edge = QColor(42, 58, 74), QColor(100, 128, 154)
            self.accent, self.ok = QColor(255, 123, 107), QColor(102, 195, 122)
            self.fill, self.hatch = QColor(56, 56, 56), QColor(120, 120, 120)
            self.earth, self.earth_edge = QColor(44, 56, 40), QColor(110, 140, 95)
            self.metal, self.metal_edge = QColor(74, 78, 86), QColor(150, 155, 165)
        else:
            self.ink, self.muted = QColor(30, 30, 30), QColor(100, 100, 100)
            self.dim, self.sig = QColor(31, 95, 168), QColor(42, 98, 184)
            self.cu, self.cu_edge = QColor(214, 140, 62), QColor(128, 82, 30)
            self.diel, self.diel_edge = QColor(221, 236, 248), QColor(120, 144, 166)
            self.accent, self.ok = QColor(192, 57, 43), QColor(46, 139, 62)
            self.fill, self.hatch = QColor(250, 250, 250), QColor(150, 150, 150)
            self.earth, self.earth_edge = QColor(226, 236, 214), QColor(120, 150, 100)
            self.metal, self.metal_edge = QColor(205, 208, 214), QColor(95, 100, 110)


class CardFigure(QWidget):
    """Base for card figures.  Subclasses set W_PX / H_PX and implement
    draw(p).  `card` is attached by CalcCard after make_diagram(), so
    val(name) returns the card's current value (declared unit) or None."""

    W_PX, H_PX = 220, 150
    FONT_PT = 9.0
    LW = 1.4                      # symbol + wire weight (rdoc: constant)

    def __init__(self, card=None, parent=None):
        super().__init__(parent)
        self.card = card
        self.labels = []          # (text, QRectF) recorded during paint
        self.setFixedSize(self.W_PX, self.H_PX)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ---- live values --------------------------------------------------
    def val(self, name):
        if self.card is None:
            return None
        v = self.card._collect().get(name)
        return v if isinstance(v, (int, float)) and math.isfinite(v) else None

    def vals(self, *names):
        return [self.val(n) for n in names]

    # ---- paint plumbing -----------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        self.c = _FigPalette(THEME == "dark")
        self._bg = self.palette().window().color()
        self._family = QApplication.font().family()
        self.labels = []
        p.setFont(QFont(self._family, 9))
        self.draw(p)
        p.end()

    def draw(self, p):
        pass

    def pen(self, color=None, width=None, style=Qt.SolidLine):
        pn = QPen(color or self.c.ink, width or self.LW, style)
        pn.setJoinStyle(Qt.MiterJoin)
        pn.setCapStyle(Qt.FlatCap)
        return pn

    # ---- text ---------------------------------------------------------
    def text(self, p, s, x, y, align="cm", color=None, size=None, bold=False,
             knock=False, italic=False):
        """Draw `s` (subscript markup allowed) anchored at (x, y); align is
        [l|c|r][t|m|b].  Returns and records the text box."""
        if not s:
            return QRectF(x, y, 0, 0)
        f = QFont(self._family); f.setPointSizeF(size or self.FONT_PT)
        f.setBold(bold); f.setItalic(italic)
        fs = QFont(f); fs.setPointSizeF(f.pointSizeF() * 0.72)
        fm, fms = QFontMetricsF(f), QFontMetricsF(fs)
        runs = _text_runs(s)
        w = sum((fm if k == 0 else fms).horizontalAdvance(t) for t, k in runs)
        h = fm.ascent() + fm.descent()
        left = x - {"l": 0.0, "c": 0.5, "r": 1.0}[align[0]] * w
        top = y - {"t": 0.0, "m": 0.5, "b": 1.0}[align[1]] * h
        kinds = {k for _, k in runs}
        y_lo = top + fm.ascent() + fm.ascent() * 0.28 + fms.descent() if -1 in kinds else top + h
        y_hi = top + fm.ascent() - fm.ascent() * 0.42 - fms.ascent() if 1 in kinds else top
        rect = QRectF(left, min(top, y_hi), w, max(top + h, y_lo) - min(top, y_hi))
        if knock:
            p.fillRect(rect.adjusted(-2, 0, 2, 0), self._bg)
        p.setPen(color or self.c.ink)
        base, cx = top + fm.ascent(), left
        for t, k in runs:
            if k == 0:
                p.setFont(f)
                p.drawText(QPointF(cx, base), t)
                cx += fm.horizontalAdvance(t)
            else:
                p.setFont(fs)
                dy = fm.ascent() * 0.28 if k < 0 else -fm.ascent() * 0.42
                p.drawText(QPointF(cx, base + dy), t)
                cx += fms.horizontalAdvance(t)
        p.setFont(f)
        self.labels.append((s, rect))
        return rect

    def text_w(self, s, size=None, bold=False):
        f = QFont(self._family); f.setPointSizeF(size or self.FONT_PT); f.setBold(bold)
        fs = QFont(f); fs.setPointSizeF(f.pointSizeF() * 0.72)
        fm, fms = QFontMetricsF(f), QFontMetricsF(fs)
        return sum((fm if k == 0 else fms).horizontalAdvance(t) for t, k in _text_runs(s))

    def stack(self, p, ref, val, x, y, h="l", color=None, size=None):
        """Reference label centred on y, its value just below its real box
        (subscript drop included); h = l / c / r horizontal anchor."""
        r = self.text(p, ref, x, y, h + "m", color, size)
        if val:
            self.text(p, val, x, r.bottom() + 0.5, h + "t", self.c.muted, 8)
        return r

    # ---- wiring -------------------------------------------------------
    def wire(self, p, *pts, color=None):
        p.setPen(self.pen(color)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(*q) for q in pts]))

    def node(self, p, x, y):
        p.setPen(Qt.NoPen); p.setBrush(self.c.ink)
        p.drawEllipse(QPointF(x, y), 2.4, 2.4)

    def term(self, p, x, y):
        p.setPen(self.pen(width=1.2)); p.setBrush(self._bg)
        p.drawEllipse(QPointF(x, y), 2.8, 2.8)

    def ground(self, p, x, y, w=14, lead=5):
        """Ground symbol hanging below (x, y)."""
        p.setPen(self.pen())
        p.drawLine(QPointF(x, y), QPointF(x, y + lead))
        for i, f in enumerate((1.0, 0.62, 0.26)):
            yy = y + lead + i * 3.2
            p.drawLine(QPointF(x - w * f / 2, yy), QPointF(x + w * f / 2, yy))

    def antenna(self, p, x, y_base, y_top, w=6.5, color=None):
        """Mast from y_base up to y_top carrying an inverted-triangle radiator."""
        p.setPen(self.pen(color)); p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(x, y_base), QPointF(x, y_top))
        p.drawPolygon(QPolygonF([QPointF(x, y_top), QPointF(x - w, y_top - 1.4 * w),
                                 QPointF(x + w, y_top - 1.4 * w)]))

    # ---- two-terminal symbols, a -> b in any orientation ----------------
    def _frame(self, p, a, b):
        """Rotate the painter so a is the origin and b lies on +x; returns L."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        p.save()
        p.translate(a[0], a[1])
        p.rotate(math.degrees(math.atan2(dy, dx)))
        return math.hypot(dx, dy)

    def resistor(self, p, a, b, body=26, dashed=False):
        L = self._frame(p, a, b)
        body = min(body, L); s0 = (L - body) / 2; amp = body / 7.0
        pts = [QPointF(0, 0), QPointF(s0, 0)]
        for i, sgn in zip(range(1, 12, 2), (-1, 1, -1, 1, -1, 1)):
            pts.append(QPointF(s0 + body * i / 12, sgn * amp))
        pts += [QPointF(s0 + body, 0), QPointF(L, 0)]
        pn = self.pen(self.c.muted if dashed else None)
        if dashed:
            pn.setDashPattern([1.6, 1.4])
        p.setPen(pn)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        p.restore()

    def capacitor(self, p, a, b, gap=5, plate=15):
        L = self._frame(p, a, b)
        m, h = L / 2, plate / 2
        p.setPen(self.pen())
        p.drawLine(QPointF(0, 0), QPointF(m - gap / 2, 0))
        p.drawLine(QPointF(m + gap / 2, 0), QPointF(L, 0))
        p.setPen(self.pen(width=self.LW + 0.4))
        p.drawLine(QPointF(m - gap / 2, -h), QPointF(m - gap / 2, h))
        p.drawLine(QPointF(m + gap / 2, -h), QPointF(m + gap / 2, h))
        p.restore()

    def inductor(self, p, a, b, body=28, n=4):
        L = self._frame(p, a, b)
        body = min(body, L); s0 = (L - body) / 2; r = body / (2 * n)
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(s0, 0)
        for i in range(n):
            path.arcTo(QRectF(s0 + 2 * r * i, -r, 2 * r, 2 * r), 180, -180)
        path.lineTo(L, 0)
        p.setPen(self.pen()); p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.restore()

    def box(self, p, x, y, w, h, fill=None):
        p.setPen(self.pen()); p.setBrush(fill if fill is not None else Qt.NoBrush)
        p.drawRect(QRectF(x, y, w, h))

    def amp(self, p, x, cy, w=26, h=26, fill=None):
        """Gain block: triangle from x (input side) pointing right."""
        p.setPen(self.pen()); p.setBrush(fill if fill is not None else Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(x, cy - h / 2), QPointF(x + w, cy),
                                 QPointF(x, cy + h / 2)]))

    def mixer(self, p, cx, cy, r=11):
        p.setPen(self.pen()); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        k = r * 0.7071
        p.drawLine(QPointF(cx - k, cy - k), QPointF(cx + k, cy + k))
        p.drawLine(QPointF(cx - k, cy + k), QPointF(cx + k, cy - k))

    def source(self, p, cx, cy, r=10):
        """Voltage source: circle with + over -."""
        p.setPen(self.pen()); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(self.pen(width=1.1))
        p.drawLine(QPointF(cx - 3, cy - r * 0.45), QPointF(cx + 3, cy - r * 0.45))
        p.drawLine(QPointF(cx, cy - r * 0.45 - 3), QPointF(cx, cy - r * 0.45 + 3))
        p.drawLine(QPointF(cx - 3, cy + r * 0.45), QPointF(cx + 3, cy + r * 0.45))

    # ---- arrows + dimensions --------------------------------------------
    def arrowhead(self, p, tip, ux, uy, color=None, size=6.5):
        nx, ny, k = -uy, ux, size * 0.36
        bx, by = tip[0] - ux * size, tip[1] - uy * size
        p.setPen(Qt.NoPen); p.setBrush(color or self.c.ink)
        p.drawPolygon(QPolygonF([QPointF(*tip), QPointF(bx + nx * k, by + ny * k),
                                 QPointF(bx - nx * k, by - ny * k)]))

    def arrow(self, p, a, b, color=None, width=1.2, size=6.5):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        p.setPen(self.pen(color, width))
        p.drawLine(QPointF(*a), QPointF(b[0] - ux * size * 0.8, b[1] - uy * size * 0.8))
        self.arrowhead(p, b, ux, uy, color, size)

    def dim_h(self, p, x1, x2, y, label="", feat=None, above=True, size=8.0):
        """Horizontal dimension x1..x2 on line y.  `feat` = y of the
        measured feature(s) for extension lines (a number, or a pair for
        the left / right ends).  Arrows sit outside when the span is short."""
        c = self.c.dim
        if x2 < x1:
            x1, x2 = x2, x1
        if feat is not None:
            f1, f2 = feat if isinstance(feat, tuple) else (feat, feat)
            p.setPen(self.pen(c, 0.8))
            for xx, ff in ((x1, f1), (x2, f2)):
                sgn = 1.0 if y > ff else -1.0
                p.drawLine(QPointF(xx, ff + sgn * 2), QPointF(xx, y + sgn * 3))
        span, a = x2 - x1, 5.5
        p.setPen(self.pen(c, 0.9))
        if span >= 2 * a + 4:
            p.drawLine(QPointF(x1, y), QPointF(x2, y))
            self.arrowhead(p, (x1, y), -1, 0, c, a)
            self.arrowhead(p, (x2, y), 1, 0, c, a)
        else:
            p.drawLine(QPointF(x1 - 9, y), QPointF(x2 + 9, y))
            self.arrowhead(p, (x1, y), 1, 0, c, a)
            self.arrowhead(p, (x2, y), -1, 0, c, a)
        if label:
            if above:
                self.text(p, label, (x1 + x2) / 2, y - 1.5, "cb", c, size)
            else:
                self.text(p, label, (x1 + x2) / 2, y + 1.5, "ct", c, size)

    def dim_v(self, p, y1, y2, x, label="", feat=None, left=True, size=8.0):
        """Vertical dimension y1..y2 on line x; label beside it (left or
        right), horizontal.  `feat` = x of the feature for extension lines."""
        c = self.c.dim
        if y2 < y1:
            y1, y2 = y2, y1
        if feat is not None:
            f1, f2 = feat if isinstance(feat, tuple) else (feat, feat)
            p.setPen(self.pen(c, 0.8))
            for yy, ff in ((y1, f1), (y2, f2)):
                sgn = 1.0 if x > ff else -1.0
                p.drawLine(QPointF(ff + sgn * 2, yy), QPointF(x + sgn * 3, yy))
        span, a = y2 - y1, 5.5
        p.setPen(self.pen(c, 0.9))
        if span >= 2 * a + 4:
            p.drawLine(QPointF(x, y1), QPointF(x, y2))
            self.arrowhead(p, (x, y1), 0, -1, c, a)
            self.arrowhead(p, (x, y2), 0, 1, c, a)
        else:
            p.drawLine(QPointF(x, y1 - 9), QPointF(x, y2 + 9))
            self.arrowhead(p, (x, y1), 0, 1, c, a)
            self.arrowhead(p, (x, y2), 0, -1, c, a)
        if label:
            if left:
                self.text(p, label, x - 4, (y1 + y2) / 2, "rm", c, size)
            else:
                self.text(p, label, x + 4, (y1 + y2) / 2, "lm", c, size)

    def dim_aligned(self, p, a, b, off, label="", size=8.0):
        """Dimension parallel to a->b, offset `off` px along its screen-left
        normal (negative = right side), with extension lines and arrows."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        nx, ny = uy, -ux
        sg = 1.0 if off > 0 else -1.0
        a2 = (a[0] + nx * off, a[1] + ny * off)
        b2 = (b[0] + nx * off, b[1] + ny * off)
        c = self.c.dim
        p.setPen(self.pen(c, 0.8))
        for f, g in ((a, a2), (b, b2)):
            p.drawLine(QPointF(f[0] + nx * 2 * sg, f[1] + ny * 2 * sg),
                       QPointF(g[0] + nx * 3 * sg, g[1] + ny * 3 * sg))
        p.setPen(self.pen(c, 0.9)); p.drawLine(QPointF(*a2), QPointF(*b2))
        self.arrowhead(p, a2, -ux, -uy, c, 5.5)
        self.arrowhead(p, b2, ux, uy, c, 5.5)
        if label:
            mx, my = (a2[0] + b2[0]) / 2 + nx * sg * 8, (a2[1] + b2[1]) / 2 + ny * sg * 8
            self.text(p, label, mx, my, "cm", c, size)

    def leader(self, p, target, at, label, align="lm", color=None):
        """Callout: label at `at`, thin leader to a dot on `target`."""
        c = color or self.c.ink
        p.setPen(self.pen(c, 0.8)); p.drawLine(QPointF(*at), QPointF(*target))
        p.setPen(Qt.NoPen); p.setBrush(c); p.drawEllipse(QPointF(*target), 1.6, 1.6)
        dx = {"l": 2, "r": -2, "c": 0}[align[0]]
        return self.text(p, label, at[0] + dx, at[1], align, c, 8.0)

    # ---- materials ------------------------------------------------------
    def slab(self, p, rect, fill, edge, width=1.0):
        p.setPen(self.pen(edge, width)); p.setBrush(fill)
        p.drawRect(rect)

    def hatch(self, p, rect, spacing=5.0, color=None):
        p.save()
        p.setClipRect(rect, Qt.IntersectClip if p.hasClipping() else Qt.ReplaceClip)
        p.setPen(self.pen(color or self.c.hatch, 0.7))
        x = rect.left() - rect.height()
        while x < rect.right():
            p.drawLine(QPointF(x, rect.bottom()), QPointF(x + rect.height(), rect.top()))
            x += spacing
        p.restore()

    def copper(self, p, rect):
        self.slab(p, rect, self.c.cu, self.c.cu_edge, 0.9)


# ---- RF link + antenna figures ------------------------------------------

class FSPLDiagram(CardFigure):
    W_PX, H_PX = 220, 112

    def draw(self, p):
        d_km, L = self.vals("d_km", "fspl_db")
        xt, xr, yb, ytop = 24.0, 196.0, 84.0, 48.0
        self.antenna(p, xt, yb, ytop); self.antenna(p, xr, yb, ytop)
        cy = ytop - 4
        for k, r in enumerate(range(16, 168, 15)):
            col = QColor(self.c.sig); col.setAlpha(max(45, 235 - k * 19))
            p.setPen(self.pen(col, 1.2)); p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(xt - r, cy - r, 2 * r, 2 * r), -16 * 16, 32 * 16)
        self.text(p, "Tx", xt + 6, yb - 8, "lm", self.c.muted, 8)
        self.text(p, "Rx", xr - 6, yb - 8, "rm", self.c.muted, 8)
        self.dim_h(p, xt, xr, 97, "d" + (" = " + eng(d_km * 1e3, "m") if d_km is not None else ""),
                   feat=yb, above=False)
        if L is not None:
            self.text(p, "L_{FS} = " + db_txt(L), 110, 3, "ct")


class FresnelDiagram(CardFigure):
    W_PX, H_PX = 220, 128

    def draw(self, p):
        mu = self.c.muted
        d1, d2, n, rn = self.vals("d1_km", "d2_km", "n", "rn_m")
        x0, x1, yl, yb, b = 22.0, 198.0, 50.0, 96.0, 24.0
        xc, a = (x0 + x1) / 2, (x1 - x0) / 2
        frac = _clamp(d1 / (d1 + d2), 0.14, 0.86) if d1 and d2 and d1 > 0 and d2 > 0 else 0.5
        xp = x0 + (x1 - x0) * frac
        # terrain with a hill under the path, just clear of the 60 % zone
        peak = yl + b * 0.6 + 5
        ground = QPainterPath(QPointF(0, yb))
        ground.lineTo(xp - 34, yb)
        ground.cubicTo(QPointF(xp - 14, yb), QPointF(xp - 12, peak), QPointF(xp, peak))
        ground.cubicTo(QPointF(xp + 12, peak), QPointF(xp + 14, yb), QPointF(xp + 34, yb))
        ground.lineTo(self.W_PX, yb); ground.lineTo(self.W_PX, self.H_PX); ground.lineTo(0, self.H_PX)
        ground.closeSubpath()
        p.setPen(self.pen(self.c.earth_edge, 1.0)); p.setBrush(self.c.earth)
        p.drawPath(ground)
        self.antenna(p, x0, yb, yl); self.antenna(p, x1, yb, yl)
        p.setPen(self.pen(mu, 1.0, Qt.DashLine)); p.drawLine(QPointF(x0, yl), QPointF(x1, yl))
        p.setBrush(Qt.NoBrush)
        p.setPen(self.pen(self.c.accent, 1.6)); p.drawEllipse(QPointF(xc, yl), a, b)
        p.setPen(self.pen(self.c.accent, 0.9, Qt.DashLine)); p.drawEllipse(QPointF(xc, yl), a, b * 0.6)
        r = b * math.sqrt(max(0.0, 1 - ((xp - xc) / a) ** 2))
        self.dim_v(p, yl - r, yl, xp)
        ref = f"R_{{{int(n)}}}" if n is not None and n >= 1 else "R_n"
        lbl = ref + (" " + eng(rn, "m") if rn is not None else "")
        if xp > xc:
            self.text(p, lbl, xp - 5, yl - r / 2, "rm", self.c.dim, 8, knock=True)
        else:
            self.text(p, lbl, xp + 5, yl - r / 2, "lm", self.c.dim, 8, knock=True)
        self.text(p, "Tx", x0 - 4, yb - 12, "rm", mu, 8)
        self.text(p, "Rx", x1 + 4, yb - 12, "lm", mu, 8)
        self.dim_h(p, x0, xp, 110, "d_1" + (" " + eng(d1 * 1e3, "m") if d1 else ""), feat=yb, above=False)
        self.dim_h(p, xp, x1, 110, "d_2" + (" " + eng(d2 * 1e3, "m") if d2 else ""), feat=yb, above=False)


class HorizonDiagram(CardFigure):
    """Vertical masts on a 4/3-earth bulge; the line of sight is tangent to
    the surface at the horizon point, placed by the card's d_t : d_r."""
    W_PX, H_PX = 220, 124

    def draw(self, p):
        dt, dr, dtot = self.vals("dt_km", "dr_km", "dtot_km")
        cx, Re, ytop = 110.0, 140.0, 92.0
        yc = ytop + Re
        xt, xr = 30.0, 190.0
        f = _clamp(dt / (dt + dr), 0.3, 0.7) if dt and dr and dt > 0 and dr > 0 else 0.5
        xh = xt + (xr - xt) * f
        al = math.asin((xh - cx) / Re)
        p.setPen(self.pen(self.c.earth_edge, 1.0)); p.setBrush(self.c.earth)
        p.drawEllipse(QPointF(cx, yc), Re, Re)
        def surf(x):
            return yc - math.sqrt(Re * Re - (x - cx) ** 2)
        def los(x):
            return yc + ((x - cx) * math.sin(al) - Re) / math.cos(al)
        tops = [(xt, los(xt)), (xr, los(xr))]
        for x, yt in tops:
            self.antenna(p, x, surf(x), yt)
        p.setPen(self.pen(self.c.sig, 1.1, Qt.DashLine))
        p.drawLine(QPointF(xt, tops[0][1]), QPointF(xr, tops[1][1]))
        yh = surf(xh)
        p.setPen(Qt.NoPen); p.setBrush(self.c.sig); p.drawEllipse(QPointF(xh, yh), 2.2, 2.2)
        yd = min(tops[0][1], tops[1][1]) - 20
        self.dim_h(p, xt, xh, yd, "d_t" + (" " + eng(dt * 1e3, "m") if dt else ""), feat=(tops[0][1] - 10, yh - 3))
        self.dim_h(p, xh, xr, yd, "d_r" + (" " + eng(dr * 1e3, "m") if dr else ""), feat=(yh - 3, tops[1][1] - 10))
        self.text(p, "h_t", xt - 5, (tops[0][1] + surf(xt)) / 2, "rm", None, 8.5)
        self.text(p, "h_r", xr + 5, (tops[1][1] + surf(xr)) / 2, "lm", None, 8.5)
        if dtot is not None:
            self.text(p, "d = " + eng(dtot * 1e3, "m"), 110, 3, "ct")


class DipoleDiagram(CardFigure):
    W_PX, H_PX = 220, 92

    def draw(self, p):
        L_m = self.val("dipole_m")
        y, xl, xr, cx, gap = 52.0, 26.0, 194.0, 110.0, 5.0
        for sgn in (-1, 1):
            pts = [QPointF(x, y + sgn * 16 * math.cos(math.pi * (x - cx) / (xr - xl)))
                   for x in range(int(xl), int(xr) + 1)]
            p.setPen(self.pen(self.c.accent, 1.0, Qt.DashLine)); p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts))
        p.setPen(self.pen(self.c.cu_edge, 4.0))
        p.drawLine(QPointF(xl, y), QPointF(cx - gap, y)); p.drawLine(QPointF(cx + gap, y), QPointF(xr, y))
        self.wire(p, (cx - gap, y), (cx - gap, y + 30)); self.wire(p, (cx + gap, y), (cx + gap, y + 30))
        self.text(p, "I", cx + 40, y - 15, "lb", self.c.accent, 8)
        self.dim_h(p, xl, xr, 18, "L" + (" = " + eng(L_m, "m") if L_m is not None else " = λ/2"),
                   feat=y - 3)


class BeamwidthDiagram(CardFigure):
    """E-plane main lobe, field ∝ cosⁿφ with the −3 dB points at ±θ/2."""
    W_PX, H_PX = 220, 132

    def draw(self, p):
        be, bh, g = self.vals("be", "bh", "g_dbi")
        th = _clamp(be if be else 40.0, 4.0, 170.0)
        ox, oy, R = 28.0, 66.0, 118.0
        n = math.log(math.sqrt(0.5)) / math.log(math.cos(math.radians(th / 2)))
        pts = []
        for k in range(-900, 901, 5):
            ph = math.radians(k / 10)
            r = math.cos(ph) ** n if math.cos(ph) > 0 else 0.0
            pts.append((r * math.cos(ph), r * math.sin(ph)))
        span = max(abs(y) for _, y in pts) or 1.0
        R = min(R, 58.0 / span)
        p.setPen(self.pen(self.c.muted, 0.6, Qt.DotLine)); p.setBrush(Qt.NoBrush)
        for k in (0.5, 1.0):
            p.drawArc(QRectF(ox - R * k, oy - R * k, 2 * R * k, 2 * R * k), -90 * 16, 180 * 16)
        p.drawLine(QPointF(ox, oy), QPointF(ox + R + 6, oy))
        lobe = QPolygonF([QPointF(ox + R * x, oy - R * y) for x, y in pts])
        fill = QColor(self.c.accent); fill.setAlpha(45)
        p.setPen(self.pen(self.c.accent, 1.5)); p.setBrush(fill)
        p.drawPolygon(lobe)
        half = math.radians(th / 2)
        p.setPen(self.pen(self.c.dim, 0.9, Qt.DashLine))
        for s in (-1, 1):
            p.drawLine(QPointF(ox, oy), QPointF(ox + (R + 4) * math.cos(half), oy - s * (R + 4) * math.sin(half)))
        ra = R * 0.45
        if ra * 2 * half > 16:
            p.setPen(self.pen(self.c.dim, 0.9)); p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(ox - ra, oy - ra, 2 * ra, 2 * ra), int(-th / 2 * 16), int(th * 16))
            for s in (-1, 1):
                tip = (ox + ra * math.cos(half), oy - s * ra * math.sin(half))
                self.arrowhead(p, tip, -math.sin(half), -s * math.cos(half), self.c.dim, 5.5)
        xl = ox + R + 8
        self.stack(p, "θ_E" + (" " + sig3(be) + "°" if be is not None else ""),
                   ("θ_H " + sig3(bh) + "°") if bh else "", xl, oy, "l", self.c.dim)
        if g is not None:
            self.text(p, "G " + db_txt(g, "dBi"), 216, 128, "rb", self.c.muted, 8)


class GainApertureDiagram(CardFigure):
    W_PX, H_PX = 220, 112

    def draw(self, p):
        g, ae_m2, ae_cm2 = self.vals("g_dbi", "ae_m2", "ae_cm2")
        cy = 54.0
        p.setPen(self.pen(self.c.metal_edge, 1.1)); p.setBrush(self.c.metal)
        p.drawRect(QRectF(14, cy - 8, 24, 16))
        p.drawPolygon(QPolygonF([QPointF(38, cy - 8), QPointF(92, cy - 32), QPointF(92, cy + 32),
                                 QPointF(38, cy + 8)]))
        ap = QRectF(96, cy - 32, 7, 64)
        fill = QColor(self.c.accent); fill.setAlpha(60)
        p.setPen(self.pen(self.c.accent, 1.2)); p.setBrush(fill); p.drawRect(ap)
        for x in (128, 150, 172, 194):
            p.setPen(self.pen(self.c.sig, 1.2)); p.drawLine(QPointF(x, cy - 30), QPointF(x, cy + 30))
        self.arrow(p, (214, cy), (112, cy), self.c.sig, 1.1)
        if ae_m2 is not None:
            area = (sig3(ae_m2) + " m²") if ae_m2 >= 0.1 else (sig3(ae_cm2 if ae_cm2 is not None else ae_m2 * 1e4) + " cm²")
            self.text(p, "A_e = " + area, 99, cy + 36, "ct", self.c.accent, 8.5)
        else:
            self.text(p, "A_e", 99, cy + 36, "ct", self.c.accent, 8.5)
        if g is not None:
            self.text(p, "G " + db_txt(g, "dBi"), 52, cy - 36, "cb", self.c.muted, 8)


class EIRPDiagram(CardFigure):
    W_PX, H_PX = 220, 100

    def draw(self, p):
        mu = self.c.muted
        pt, g, loss, eirp = self.vals("pt_dbm", "g_dbi", "loss_db", "eirp")
        y, xa = 70.0, 132.0
        self.text(p, "EIRP = P_t + G − L", 110, 2, "ct", mu, 8)
        self.box(p, 8, y - 13, 36, 26); self.text(p, "Tx", 26, y, "cm", None, 8.5)
        self.wire(p, (44, y), (66, y))
        self.box(p, 66, y - 8, 32, 16); self.hatch(p, QRectF(66, y - 8, 32, 16), 5, mu)
        self.box(p, 66, y - 8, 32, 16)
        self.wire(p, (98, y), (xa, y))
        self.antenna(p, xa, y, y - 26)
        top = (xa, y - 34)
        for k, r in enumerate((10, 18, 26)):
            col = QColor(self.c.accent); col.setAlpha(230 - k * 50)
            p.setPen(self.pen(col, 1.3)); p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(top[0] - r, top[1] - r, 2 * r, 2 * r), -35 * 16, 70 * 16)
        self.arrow(p, (162, top[1]), (184, top[1]), self.c.accent)
        self.text(p, "P_t" + (" " + db_txt(pt, "dBm") if pt is not None else ""), 6, y - 17, "lb", None, 8)
        self.text(p, "L" + (" " + db_txt(loss) if loss is not None else ""), 82, y + 11, "ct", None, 8)
        self.text(p, "G" + (" " + db_txt(g, "dBi") if g is not None else ""), xa + 6, y + 4, "lt", None, 8)
        self.text(p, "EIRP", 214, top[1] - 8, "rb", self.c.accent, 8)
        if eirp is not None:
            self.text(p, db_txt(eirp, "dBm"), 214, top[1] + 6, "rt", self.c.accent, 8)


class AntennaSketch(CardFigure):
    """Geometry of the Antenna Designer's selected type (set_kind)."""
    W_PX, H_PX = 300, 230
    KINDS = ("dipole", "monopole", "patch", "horn", "dish", "yagi", "helix")

    def __init__(self, parent=None):
        super().__init__(None, parent)
        self._kind = "dipole"

    def set_kind(self, k):
        self._kind = k
        self.update()

    def draw(self, p):
        getattr(self, f"_draw_{self._kind}", self._draw_dipole)(p)
        self.text(p, self._kind.replace("_", " ").title(), 8, self.H_PX - 4, "lb", self.c.dim, 8.5, bold=True)

    def _rod(self, p, a, b, w=4.0):
        p.setPen(self.pen(self.c.cu_edge, w)); p.drawLine(QPointF(*a), QPointF(*b))

    def _envelope(self, p, pts):
        p.setPen(self.pen(self.c.accent, 1.0, Qt.DashLine)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(*q) for q in pts]))

    def _draw_dipole(self, p):
        y, xl, xr, cx = 104.0, 40.0, 260.0, 150.0
        for s in (-1, 1):
            self._envelope(p, [(x, y + s * 26 * math.cos(math.pi * (x - cx) / (xr - xl)))
                               for x in range(int(xl), int(xr) + 1)])
        self._rod(p, (xl, y), (cx - 6, y)); self._rod(p, (cx + 6, y), (xr, y))
        self.wire(p, (cx - 6, y), (cx - 6, 170)); self.wire(p, (cx + 6, y), (cx + 6, 170))
        self.term(p, cx - 6, 172); self.term(p, cx + 6, 172)
        self.dim_h(p, xl, xr, 52, "L = λ/2", feat=y - 4, size=9)
        self.text(p, "I", cx + 52, y - 26, "lb", self.c.accent, 8.5)

    def _draw_monopole(self, p):
        gy, top, x = 170.0, 64.0, 150.0
        L = gy - top
        self._envelope(p, [(x + 24 * math.cos(math.pi * (gy - yy) / (2 * L)), yy)
                           for yy in range(int(top), int(gy) + 1)])
        self.copper(p, QRectF(30, gy, 240, 6)); self.hatch(p, QRectF(30, gy + 6, 240, 10), 6)
        self._rod(p, (x, gy), (x, top))
        self.dim_v(p, top, gy, 214, "L = λ/4", feat=x + 4, left=False, size=9)
        self.text(p, "I", x + 26, gy - 8, "lb", self.c.accent, 8.5)

    def _draw_patch(self, p):
        # top view
        sub = QRectF(40, 22, 170, 112)
        self.slab(p, sub, self.c.diel, self.c.diel_edge)
        patch = QRectF(80, 44, 90, 62)
        self.copper(p, patch)
        self.copper(p, QRectF(122, 106, 6, 28))
        self.dim_h(p, patch.left(), patch.right(), 36, "W", feat=patch.top(), size=9)
        self.dim_v(p, patch.top(), patch.bottom(), 230, "L", feat=sub.right(), left=False, size=9)
        # side view
        y0 = 166.0
        self.copper(p, QRectF(80, y0 - 4, 90, 4))
        self.slab(p, QRectF(40, y0, 170, 16), self.c.diel, self.c.diel_edge)
        self.copper(p, QRectF(40, y0 + 16, 170, 5))
        self.dim_v(p, y0, y0 + 16, 230, "h", feat=210, left=False, size=9)

    def _draw_horn(self, p):
        cy, x0, x1, x2 = 112.0, 34.0, 84.0, 232.0
        p.setPen(self.pen(self.c.metal_edge, 1.2)); p.setBrush(self.c.metal)
        p.drawRect(QRectF(x0, cy - 15, x1 - x0, 30))
        p.drawPolygon(QPolygonF([QPointF(x1, cy - 15), QPointF(x2, cy - 74), QPointF(x2, cy + 74),
                                 QPointF(x1, cy + 15)]))
        self.dim_v(p, cy - 74, cy + 74, 252, "A", feat=x2, left=False, size=9)
        self.dim_h(p, x1, x2, 204, "L", feat=cy + 76, above=False, size=9)

    def _draw_dish(self, p):
        vx, cy, f, half = 64.0, 112.0, 62.0, 86.0
        rim_x = vx + half * half / (4 * f)
        pts = [QPointF(vx + yy * yy / (4 * f), cy + yy) for yy in range(int(-half), int(half) + 1)]
        p.setPen(self.pen(self.c.metal_edge, 3.0)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        fx = vx + f
        for yy in (-half * 0.62, half * 0.62):
            hit = (vx + yy * yy / (4 * f), cy + yy)
            p.setPen(self.pen(self.c.accent, 0.9))
            p.drawLine(QPointF(250, cy + yy), QPointF(*hit)); p.drawLine(QPointF(*hit), QPointF(fx, cy))
        p.setPen(self.pen(self.c.muted, 0.8, Qt.DashDotLine))
        p.drawLine(QPointF(vx - 10, cy), QPointF(260, cy))
        for yy in (-half, half):
            p.setPen(self.pen(self.c.muted, 0.9)); p.drawLine(QPointF(rim_x, cy + yy), QPointF(fx, cy))
        p.setPen(self.pen()); p.setBrush(self.c.metal)
        p.drawPolygon(QPolygonF([QPointF(fx - 6, cy), QPointF(fx + 6, cy - 6), QPointF(fx + 6, cy + 6)]))
        self.dim_v(p, cy - half, cy + half, 278, "D", feat=rim_x, left=False, size=9)
        self.dim_h(p, vx, fx, 214, "f", feat=cy + 4, above=False, size=9)

    def _draw_yagi(self, p):
        y = 112.0
        xs = (46, 92, 138, 180, 220, 258)
        lens = (122, 110, 100, 96, 92, 88)
        refs = ("R", "DE", "D_1", "D_2", "D_3", "D_4")
        p.setPen(self.pen(self.c.ink, 2.2)); p.drawLine(QPointF(30, y), QPointF(274, y))
        for x, L, ref in zip(xs, lens, refs):
            if ref == "DE":
                self._rod(p, (x, y - L / 2), (x, y - 5), 3.0); self._rod(p, (x, y + 5), (x, y + L / 2), 3.0)
            else:
                self._rod(p, (x, y - L / 2), (x, y + L / 2), 3.0)
            self.text(p, ref, x, y - L / 2 - 3, "cb", None, 8.5)
        self.arrow(p, (232, 196), (286, 196), self.c.accent, 1.4)
        self.dim_h(p, xs[0], xs[1], 186, "S", feat=y + lens[0] / 2, above=False, size=9)

    def _draw_helix(self, p):
        cy, x0, R, S, N = 110.0, 66.0, 36.0, 36.0, 5
        self.copper(p, QRectF(44, cy - 72, 8, 144))
        front, back = [], []
        steps = N * 60
        for k in range(steps + 1):
            t = k / 60
            pt = QPointF(x0 + S * t, cy - R * math.cos(2 * math.pi * t))
            (front if math.sin(2 * math.pi * t) >= 0 else back).append((k, pt))
        def runs(seq):
            out, cur, last = [], [], None
            for k, pt in seq:
                if last is not None and k != last + 1:
                    out.append(cur); cur = []
                cur.append(pt); last = k
            if cur:
                out.append(cur)
            return out
        p.setBrush(Qt.NoBrush)
        p.setPen(self.pen(self.c.cu_edge, 1.2, Qt.DashLine))
        for r in runs(back):
            p.drawPolyline(QPolygonF(r))
        p.setPen(self.pen(self.c.cu_edge, 2.6))
        for r in runs(front):
            p.drawPolyline(QPolygonF(r))
        self.wire(p, (52, cy), (x0, cy - R))
        xe = x0 + S * N
        self.dim_v(p, cy - R, cy + R, xe + 18, "D", feat=xe, left=False, size=9)
        self.dim_h(p, x0 + S, x0 + 2 * S, cy - R - 14, "S", feat=cy - R, size=9)


# ---- geometry + reference figures -----------------------------------------

class PowerTriangleDiagram(CardFigure):
    """P along x, Q perpendicular, S the hypotenuse at φ (drawn to φ;
    a leading / negative φ puts Q below the baseline)."""
    W_PX, H_PX = 220, 128

    def draw(self, p):
        phi = self.val("phi")
        P, Q, S = self.vals("p_w", "q_var", "s_va")
        lead = phi is not None and phi < 0
        ph = math.radians(_clamp(abs(phi) if phi is not None else 36.87, 4.0, 76.0))
        Lp = min(126.0, 74.0 / math.tan(ph))
        Lq = Lp * math.tan(ph)
        x0 = 30.0
        y0 = 22.0 if lead else 104.0
        sg = -1.0 if lead else 1.0
        A, B, C = (x0, y0), (x0 + Lp, y0), (x0 + Lp, y0 - sg * Lq)
        fill = QColor(self.c.sig); fill.setAlpha(28)
        p.setPen(Qt.NoPen); p.setBrush(fill)
        p.drawPolygon(QPolygonF([QPointF(*A), QPointF(*B), QPointF(*C)]))
        for (u, v), col in (((A, B), self.c.ok), ((B, C), self.c.accent), ((A, C), self.c.sig)):
            p.setPen(self.pen(col, 2.0)); p.drawLine(QPointF(*u), QPointF(*v))
        k = 7.0
        p.setPen(self.pen(self.c.muted, 0.9)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(B[0] - k, y0), QPointF(B[0] - k, y0 - sg * k), QPointF(B[0], y0 - sg * k)]))
        r = 24.0
        span = math.degrees(ph) * (1 if not lead else -1)
        p.setPen(self.pen(self.c.ink, 1.0))
        p.drawArc(QRectF(x0 - r, y0 - r, 2 * r, 2 * r), 0, int(span * 16))
        mid = ph / 2
        self.text(p, "φ", x0 + (r + 7) * math.cos(mid), y0 - sg * (r + 7) * math.sin(mid), "cm", None, 9)
        self.text(p, "P" + (" " + eng(P, "W") if P is not None else ""), x0 + Lp / 2, y0 + sg * 4,
                  "ct" if not lead else "cb", self.c.ok, 8.5)
        self.text(p, "Q" + (" " + eng(Q, "VAr") if Q is not None else ""), B[0] + 6, y0 - sg * Lq / 2,
                  "lm", self.c.accent, 8.5)
        mx, my = x0 + Lp / 2, y0 - sg * Lq / 2
        nx, ny = -math.sin(ph), -sg * math.cos(ph)
        s_lbl = "S" + (" " + eng(S, "VA") if S is not None else "")
        sx = mx + nx * 6
        if sx - self.text_w(s_lbl, 8.5) < 4:
            self.text(p, s_lbl, C[0], C[1] - sg * 3, "rb" if not lead else "rt", self.c.sig, 8.5)
        else:
            self.text(p, s_lbl, sx, my + ny * 6, "rb" if not lead else "rt", self.c.sig, 8.5)


class CavityDiagram(CardFigure):
    """Oblique projection of the a × b × c cavity, drawn to its proportions."""
    W_PX, H_PX = 220, 150

    def draw(self, p):
        a, b, c, m, n, q, f = self.vals("a_m", "b_m", "c_m", "m", "n", "p", "f_mhz")
        a = a if a and a > 0 else 1.0
        b = b if b and b > 0 else 0.5
        c = c if c and c > 0 else 0.8
        k = min(118.0 / (a + 0.52 * c), 74.0 / (b + 0.30 * c))
        A, B, C = max(a * k, 18.0), max(b * k, 16.0), max(c * k, 18.0)
        dx, dy = 0.52 * C, -0.30 * C
        x0, yb = 34.0, 118.0
        f0 = [(x0, yb), (x0 + A, yb), (x0 + A, yb - B), (x0, yb - B)]
        bk = [(x + dx, y + dy) for x, y in f0]
        mt = self.c.metal
        top = QColor(mt).lighter(108); side = QColor(mt).darker(112)
        p.setPen(self.pen(self.c.metal_edge, 1.2))
        p.setBrush(side); p.drawPolygon(QPolygonF([QPointF(*f0[1]), QPointF(*bk[1]), QPointF(*bk[2]), QPointF(*f0[2])]))
        p.setBrush(top); p.drawPolygon(QPolygonF([QPointF(*f0[3]), QPointF(*f0[2]), QPointF(*bk[2]), QPointF(*bk[3])]))
        p.setBrush(mt); p.drawPolygon(QPolygonF([QPointF(*q_) for q_ in f0]))
        p.setPen(self.pen(self.c.metal_edge, 0.9, Qt.DashLine)); p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(*f0[0]), QPointF(*bk[0]))
        p.drawLine(QPointF(*bk[0]), QPointF(*bk[1])); p.drawLine(QPointF(*bk[0]), QPointF(*bk[3]))
        self.dim_h(p, f0[0][0], f0[1][0], yb + 11, "a", feat=yb, above=False)
        self.dim_v(p, yb - B, yb, x0 - 11, "b", feat=x0)
        self.dim_aligned(p, f0[1], bk[1], -11, "c")
        if None not in (m, n, q):
            idx = f"{int(m)}{int(n)}{int(q)}"
            self.text(p, f"f_{{{idx}}}" + (" = " + eng(f * 1e6, "Hz") if f is not None else ""), 6, 4, "lt")


class WaveguideDiagram(CardFigure):
    """Rectangular guide cross-section, TE₁₀ E-field ∝ sin(πx/a), to a : b."""
    W_PX, H_PX = 220, 138

    def draw(self, p):
        a, b, er = self.vals("a_mm", "b_mm", "eps_r")
        ar = _ratio(a, b, 2.0)
        k = min(150.0 / ar, 78.0)
        w, h = ar * k, max(k, 22.0)
        x0, y0 = (220 - w) / 2 - 8, 26.0 + (78 - h) / 2
        wall = 6.0
        p.setPen(self.pen(self.c.metal_edge, 1.0)); p.setBrush(self.c.metal)
        p.drawRect(QRectF(x0 - wall, y0 - wall, w + 2 * wall, h + 2 * wall))
        inner = self.c.diel if er is not None and er > 1.0 else self._bg
        p.setBrush(inner); p.drawRect(QRectF(x0, y0, w, h))
        for i in range(1, 10):
            xx = x0 + w * i / 10
            amp = math.sin(math.pi * i / 10)
            yt, ybt = y0 + h / 2 - amp * h * 0.42, y0 + h / 2 + amp * h * 0.42
            if ybt - yt > 8:
                self.arrow(p, (xx, ybt), (xx, yt), self.c.sig, 1.2, 5.5)
        self.text(p, "TE_{10}", x0, y0 - wall - 3, "lb", self.c.muted, 8.5)
        self.dim_h(p, x0, x0 + w, y0 + h + wall + 12, "a", feat=y0 + h + wall, above=False)
        self.dim_v(p, y0, y0 + h, x0 + w + wall + 12, "b", feat=x0 + w + wall, left=False)
        if er is not None and er > 1.0:
            self.text(p, "ε_r " + sig3(er), x0 + w, y0 - wall - 3, "rb", self.c.muted, 8)


class EmbeddedResistorDiagram(CardFigure):
    """IPC-2316 planar resistor, top view: film between overlapping copper
    terminations, drawn to L / W, with the square count and R."""
    W_PX, H_PX = 240, 134

    def draw(self, p):
        L, W, sq, R = self.vals("L_mil", "W_mil", "squares", "R_ohm")
        ratio = _ratio(L, W, 2.0)
        k = min(150.0 / ratio, 54.0)
        lp, wp = max(ratio * k, 20.0), max(k, 10.0)
        cx, cy = 116.0, 64.0
        film = QRectF(cx - lp / 2, cy - wp / 2, lp, wp)
        p.setPen(self.pen(self.c.ink, 0.9)); p.setBrush(QColor(80, 80, 84) if THEME != "dark" else QColor(150, 150, 156))
        p.drawRect(film)
        ov, tw = 6.0, 22.0
        for xx in (film.left() - tw + ov, film.right() - ov):
            self.copper(p, QRectF(xx, cy - wp / 2 - 6, tw, wp + 12))
        self.dim_h(p, film.left() + ov, film.right() - ov, cy - wp / 2 - 18, "L", feat=cy - wp / 2 - 6)
        self.dim_v(p, film.top(), film.bottom(), film.right() + tw - ov + 12, "W", feat=film.right() + tw - ov, left=False)
        parts = []
        if sq is not None:
            parts.append(f"N_□ {sig3(sq)}")
        if R is not None:
            parts.append("R " + eng(R, "Ω"))
        self.text(p, "    ".join(parts), cx, cy + wp / 2 + 18, "ct", None, 8.5)


class ViaDiagram(CardFigure):
    """Plated through-hole via: plane-layer top view (antipad, pad, barrel)
    above the cross-section, both to the card's diameters."""
    W_PX, H_PX = 250, 206

    def draw(self, p):
        dv, dp, da, H, T = self.vals("d_via", "d_pad", "d_anti", "h", "t_plate")
        da_ = da if da and da > 0 else 40.0
        ra = 38.0
        rp = _clamp(_ratio(dp, da_, 0.5) * ra, 8.0, ra - 4)
        rv = _clamp(_ratio(dv, da_, 0.25) * ra, 4.0, rp - 3)
        tp = _clamp(_ratio(T, da_, 0.025) * ra, 1.5, 5.0)
        cx = 72.0
        # plane-layer top view
        cy = 50.0
        plane = QRectF(16, cy - 44, 112, 88)
        self.copper(p, plane)
        p.setPen(self.pen(self.c.diel_edge, 0.9)); p.setBrush(self.c.diel)
        p.drawEllipse(QPointF(cx, cy), ra, ra)
        p.setPen(self.pen(self.c.cu_edge, 0.9)); p.setBrush(self.c.cu)
        p.drawEllipse(QPointF(cx, cy), rp, rp)
        p.setBrush(self._bg); p.drawEllipse(QPointF(cx, cy), rv, rv)
        p.setPen(self.pen(self.c.cu_edge, tp)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), rv + tp / 2, rv + tp / 2)
        def lbl(name, v):
            return name + (" " + sig3(v) + " mil" if v is not None else "")
        for r_, y_, name, v in ((ra, cy - 30, "D_{anti}", da), (rp, cy - 6, "D_{pad}", dp),
                                (rv, cy + 18, "D_{via}", dv)):
            ang = math.asin(_clamp((y_ - cy) / r_, -0.95, 0.95))
            tgt = (cx + r_ * math.cos(ang), cy + r_ * math.sin(ang))
            self.leader(p, tgt, (140, y_), lbl(name, v))
        # cross-section
        yt, hb = 112.0, 64.0
        yb_ = yt + hb
        board = QRectF(16, yt, 112, hb)
        self.slab(p, board, self.c.diel, self.c.diel_edge)
        ym = yt + hb / 2
        for x_a, x_b in ((16, cx - ra), (cx + ra, 128)):
            self.copper(p, QRectF(x_a, ym - 1.5, x_b - x_a, 3))
        for yy in (yt - 3, yb_):
            self.copper(p, QRectF(cx - rp, yy, 2 * rp, 3))
        self.copper(p, QRectF(cx - rv - tp, yt - 3, tp, hb + 6))
        self.copper(p, QRectF(cx + rv, yt - 3, tp, hb + 6))
        p.setPen(Qt.NoPen); p.setBrush(self._bg)
        p.drawRect(QRectF(cx - rv, yt - 3, 2 * rv, hb + 6))
        self.dim_v(p, yt, yb_, 140, "H" + (" " + sig3(H) + " mil" if H is not None else ""), feat=128, left=False)
        self.leader(p, (cx + rv + tp / 2, yb_ - 10), (140, yb_ + 14),
                    "T" + (" " + sig3(T) + " mil" if T is not None else ""))


class CountersinkDiagram(CardFigure):
    """Section through a countersunk hole, drawn to OD, ID and θ."""
    W_PX, H_PX = 270, 176

    def draw(self, p):
        od, i_d, th, dep = self.vals("od", "id", "theta", "depth")
        od_ = od if od and od > 0 else 3.0
        id_ = i_d if i_d and 0 < i_d < od_ else od_ * 0.6
        th_ = _clamp(th if th else 90.0, 30.0, 150.0)
        k = 150.0 / od_
        ODp, IDp = od_ * k, id_ * k
        Dp = _clamp((ODp - IDp) / 2 / math.tan(math.radians(th_ / 2)), 3.0, 60.0)
        cx, top = 112.0, 44.0
        bot = top + max(Dp + 34, 64.0)
        x_l, x_r = 14.0, 242.0
        halves = (
            [(x_l, top), (cx - ODp / 2, top), (cx - IDp / 2, top + Dp), (cx - IDp / 2, bot), (x_l, bot)],
            [(x_r, top), (cx + ODp / 2, top), (cx + IDp / 2, top + Dp), (cx + IDp / 2, bot), (x_r, bot)],
        )
        for poly in halves:
            pg = QPolygonF([QPointF(*q_) for q_ in poly])
            p.setPen(Qt.NoPen); p.setBrush(self.c.metal); p.drawPolygon(pg)
            path = QPainterPath(); path.addPolygon(pg)
            p.save(); p.setClipPath(path)
            self.hatch(p, QRectF(x_l, top, x_r - x_l, bot - top), 6.0, self.c.metal_edge)
            p.restore()
            p.setPen(self.pen(self.c.metal_edge, 1.2)); p.setBrush(Qt.NoBrush); p.drawPolygon(pg)
        p.setPen(self.pen(self.c.muted, 0.8, Qt.DashDotLine))
        p.drawLine(QPointF(cx, top - 4), QPointF(cx, bot + 6))
        self.dim_h(p, cx - ODp / 2, cx + ODp / 2, top - 12,
                   "OD" + (" " + sig3(od) + " mm" if od is not None else ""), feat=top)
        self.dim_h(p, cx - IDp / 2, cx + IDp / 2, bot + 12,
                   "ID" + (" " + sig3(i_d) + " mm" if i_d is not None else ""), feat=bot, above=False)
        self.dim_v(p, top, top + Dp, cx + ODp / 2 + 14,
                   "D" + (" " + sig3(dep) + " mm" if dep is not None else ""),
                   feat=(cx + ODp / 2, cx + IDp / 2), left=False)
        self.text(p, "θ" + (" " + sig3(th) + "°" if th is not None else ""), cx - 8, top + Dp + 14, "rt", self.c.dim, 8.5)


# ---- schematic figures ------------------------------------------------

def _f(v, scale):
    return None if v is None else v * scale


class _CapReactanceDiagram(CardFigure):
    W_PX, H_PX = 220, 62

    def draw(self, p):
        y = 26
        esr, c_pf = self.vals("r_esr", "c_pf")
        self.term(p, 10, y); self.term(p, 210, y)
        self.resistor(p, (12.8, y), (104, y))
        self.capacitor(p, (104, y), (207.2, y))
        self.text(p, "ESR", 58, y - 7, "cb")
        self.text(p, eng(esr, "Ω"), 58, y + 7, "ct", self.c.muted, 8)
        self.text(p, "C", 156, y - 10, "cb")
        self.text(p, eng(_f(c_pf, 1e-12), "F"), 156, y + 10, "ct", self.c.muted, 8)


class _IndReactanceDiagram(CardFigure):
    W_PX, H_PX = 220, 62

    def draw(self, p):
        y = 26
        rdc, l_nh = self.vals("r_dc", "l_nh")
        self.term(p, 10, y); self.term(p, 210, y)
        self.resistor(p, (12.8, y), (104, y))
        self.inductor(p, (104, y), (207.2, y))
        self.text(p, "R_{DC}", 58, y - 7, "cb")
        self.text(p, eng(rdc, "Ω"), 58, y + 7, "ct", self.c.muted, 8)
        self.text(p, "L", 156, y - 7, "cb")
        self.text(p, eng(_f(l_nh, 1e-9), "H"), 156, y + 6, "ct", self.c.muted, 8)


class _RLCComboDiagram(CardFigure):
    W_PX, H_PX = 220, 146

    def draw(self, p):
        r, l_uh, c_pf = self.vals("r_ohm", "l_uh", "c_pf")
        vr, vl, vc = eng(r, "Ω"), eng(_f(l_uh, 1e-6), "H"), eng(_f(c_pf, 1e-12), "F")
        mu = self.c.muted
        # series R-L-C
        y = 32
        self.text(p, "Series", 6, 4, "lt", mu, 8)
        self.term(p, 12, y); self.term(p, 208, y)
        self.resistor(p, (14.8, y), (78, y))
        self.inductor(p, (78, y), (142, y))
        self.capacitor(p, (142, y), (205.2, y))
        for x, ref, val, up, dn in ((46.4, "R", vr, 7, 7), (110, "L", vl, 7, 6),
                                     (173.6, "C", vc, 10, 10)):
            self.text(p, ref, x, y - up, "cb")
            self.text(p, val, x, y + dn, "ct", mu, 8)
        # parallel R || L || C between two rails
        top, bot = 84, 134
        self.text(p, "Parallel", 6, 62, "lt", mu, 8)
        self.term(p, 12, top); self.term(p, 12, bot)
        self.wire(p, (14.8, top), (168, top))
        self.wire(p, (14.8, bot), (168, bot))
        self.resistor(p, (64, top), (64, bot))
        self.inductor(p, (116, top), (116, bot))
        self.capacitor(p, (168, top), (168, bot))
        for x in (64, 116):
            self.node(p, x, top); self.node(p, x, bot)
        for x, ref, val in ((72, "R", vr), (126, "L", vl), (178, "C", vc)):
            self.text(p, ref, x, 103, "lm")
            self.text(p, val, x, 115, "lm", mu, 8)


class AttenuatorPadDiagram(CardFigure):
    W_PX, H_PX = 220, 168

    def draw(self, p):
        mu = self.c.muted
        pi_rs, pi_rp, t_rs, t_rp = self.vals("pi_rs", "pi_rp", "t_rs", "t_rp")
        # Π pad
        y, g = 28, 74
        self.text(p, "Π", 6, 4, "lt", mu, 9, bold=True)
        self.term(p, 12, y); self.term(p, 208, y)
        self.wire(p, (14.8, y), (52, y)); self.wire(p, (168, y), (205.2, y))
        self.resistor(p, (52, y), (168, y))
        self.resistor(p, (52, y), (52, g)); self.resistor(p, (168, y), (168, g))
        self.wire(p, (52, g), (168, g))
        self.node(p, 52, y); self.node(p, 168, y); self.node(p, 110, g)
        self.ground(p, 110, g)
        self.text(p, "R_s", 110, y - 7, "cb")
        self.text(p, eng(pi_rs, "Ω"), 110, y + 7, "ct", mu, 8)
        self.stack(p, "R_p", eng(pi_rp, "Ω"), 44, 45, "r")
        self.stack(p, "R_p", eng(pi_rp, "Ω"), 176, 45, "l")
        # T pad
        y = 116
        self.text(p, "T", 6, 92, "lt", mu, 9, bold=True)
        self.term(p, 12, y); self.term(p, 208, y)
        self.resistor(p, (14.8, y), (110, y)); self.resistor(p, (110, y), (205.2, y))
        self.resistor(p, (110, y), (110, 150))
        self.node(p, 110, y); self.ground(p, 110, 150)
        for x in (62, 158):
            self.text(p, "R_s", x, y - 7, "cb")
            self.text(p, eng(t_rs, "Ω"), x, y + 7, "ct", mu, 8)
        self.stack(p, "R_p", eng(t_rp, "Ω"), 118, 131)


class VoltageDividerDiagram(CardFigure):
    W_PX, H_PX = 200, 172

    def draw(self, p):
        mu = self.c.muted
        vin, r1, r2, rl, vout = self.vals("vin", "r1", "r2", "rload", "vout")
        x, xl, tap, bot = 60, 122, 86, 150
        self.term(p, x, 14)
        self.text(p, "V_{in}", x - 7, 14, "rm"); self.text(p, eng(vin, "V"), x + 7, 14, "lm", mu, 8)
        self.resistor(p, (x, 16.8), (x, tap)); self.resistor(p, (x, tap), (x, bot))
        self.wire(p, (x, tap), (169.2, tap)); self.term(p, 172, tap); self.node(p, x, tap)
        self.text(p, "V_{out}", 172, tap - 8, "cb")
        self.text(p, eng(vout, "V"), 172, tap + 8, "ct", mu, 8)
        loaded = rl is not None and rl > 0
        self.resistor(p, (xl, tap), (xl, bot), dashed=not loaded)
        self.node(p, xl, tap)
        self.wire(p, (x, bot), (xl, bot)); self.node(p, 91, bot); self.ground(p, 91, bot)
        self.stack(p, "R_1", eng(r1, "Ω"), x + 10, 46, "l")
        self.stack(p, "R_2", eng(r2, "Ω"), x + 10, 112, "l")
        self.stack(p, "R_L", eng(rl, "Ω") if loaded else "", xl + 9, 112)


class _VoltageDropDiagram(CardFigure):
    W_PX, H_PX = 220, 104

    def draw(self, p):
        mu = self.c.muted
        i_a, r_w, vd = self.vals("i_a", "r_ohm", "vdrop")
        y, yb, xs, xl = 28, 92, 26, 186
        self.source(p, xs, 58, 11)
        self.wire(p, (xs, 47), (xs, y), (60, y))
        self.resistor(p, (60, y), (132, y))
        self.wire(p, (132, y), (xl, y), (xl, 44))
        self.box(p, xl - 8, 44, 16, 32)
        self.wire(p, (xl, 76), (xl, yb), (xs, yb), (xs, 69))
        self.text(p, "V_s", xs + 16, 58, "lm")
        self.text(p, "load", xl - 13, 60, "rm", mu, 8)
        self.text(p, "R_{wire}", 96, y - 8, "cb")
        self.text(p, eng(r_w, "Ω"), 96, y + 8, "ct", mu, 8)
        self.text(p, ("ΔV " + eng(vd, "V")) if vd is not None else "", 96, y + 20, "ct", mu, 8)
        self.arrow(p, (144, 18), (166, 18), self.c.sig)
        self.text(p, ("I " + eng(i_a, "A")) if i_a is not None else "I", 170, 18, "lm", self.c.sig, 8)


class _SeriesParallelDiagram(CardFigure):
    """kind 'R' or 'C'; draws as many parts as the card has values (2..6)."""
    W_PX, H_PX = 220, 150

    def __init__(self, kind="R", parent=None):
        super().__init__(None, parent)
        self.kind = kind

    def draw(self, p):
        mu = self.c.muted
        key, unit = ("r", "Ω") if self.kind == "R" else ("c", "F")
        vals = [(i, self.val(f"{key}{i}")) for i in range(1, 7)]
        parts = [(i, v) for i, v in vals if v is not None] or [(1, None), (2, None), (3, None)]
        if len(parts) == 1:
            parts.append((parts[0][0] + 1, None))
        n = len(parts)
        sym = self.resistor if self.kind == "R" else self.capacitor
        ref = self.kind
        vsz = 7.0 if n >= 5 else 8.0
        up, dn = (7, 7) if self.kind == "R" else (10, 10)
        # series chain
        y = 38
        self.text(p, "Series", 6, 2, "lt", mu, 8)
        self.term(p, 12, y); self.term(p, 208, y)
        x0, x1 = 14.8, 205.2
        seg = (x1 - x0) / n
        for k, (i, v) in enumerate(parts):
            a, b = x0 + k * seg, x0 + (k + 1) * seg
            if self.kind == "R":
                sym(p, (a, y), (b, y), body=min(26, seg - 8))
            else:
                sym(p, (a, y), (b, y))
            cx = (a + b) / 2
            self.text(p, f"{ref}_{i}", cx, y - up, "cb", None, 8.5)
            self.text(p, eng(v, unit), cx, y + dn, "ct", mu, vsz)
        # parallel branches between two rails
        top, bot = 82, 114
        self.text(p, "Parallel", 6, 62, "lt", mu, 8)
        self.term(p, 12, top); self.term(p, 12, bot)
        xs = [50 + k * (146 / (n - 1)) for k in range(n)]
        self.wire(p, (14.8, top), (xs[-1], top)); self.wire(p, (14.8, bot), (xs[-1], bot))
        for k, ((i, v), bx) in enumerate(zip(parts, xs)):
            if self.kind == "R":
                sym(p, (bx, top), (bx, bot), body=24)
            else:
                sym(p, (bx, top), (bx, bot))
            if k < n - 1:
                self.node(p, bx, top); self.node(p, bx, bot)
            self.text(p, f"{ref}_{i}", bx, bot + 5, "ct", None, 8.5)
            self.text(p, eng(v, unit), bx, bot + 21, "ct", mu, vsz)


class _RiseFallDiagram(CardFigure):
    """RC low-pass with its step response and the 10-90 % rise time."""
    W_PX, H_PX = 220, 116

    def draw(self, p):
        mu = self.c.muted
        r, c = self.vals("r", "c")
        y = 30
        self.term(p, 10, y); self.term(p, 112, y)
        self.resistor(p, (12.8, y), (84, y))
        self.wire(p, (84, y), (109.2, y)); self.node(p, 84, y)
        self.capacitor(p, (84, y), (84, 76)); self.ground(p, 84, 76)
        self.text(p, "R", 48, y - 7, "cb"); self.text(p, eng(r, "Ω"), 48, y + 7, "ct", mu, 8)
        self.stack(p, "C", eng(c, "F"), 94, 49, "l")
        # step response panel
        x0, x1, yb, yt, x_on, tau = 130.0, 214.0, 86.0, 24.0, 136.0, 13.0
        p.setPen(self.pen(mu, 0.8))
        p.drawLine(QPointF(x0, yt - 6), QPointF(x0, yb)); p.drawLine(QPointF(x0, yb), QPointF(x1, yb))
        p.setPen(self.pen(mu, 1.0, Qt.DashLine))
        p.drawPolyline(QPolygonF([QPointF(x0, yb), QPointF(x_on, yb), QPointF(x_on, yt),
                                  QPointF(x1, yt)]))
        pts = [QPointF(x_on + t, yb - (1 - math.exp(-t / tau)) * (yb - yt))
               for t in [k * 0.5 for k in range(int((x1 - x_on) * 2) + 1)]]
        p.setPen(self.pen(self.c.accent, 1.6)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        t10, t90 = -tau * math.log(0.9), -tau * math.log(0.1)
        y10, y90 = yb - 0.1 * (yb - yt), yb - 0.9 * (yb - yt)
        self.dim_h(p, x_on + t10, x_on + t90, 99, "t_r", feat=(y10, y90), above=False)
        self.text(p, "v_{in}", x1, yt - 3, "rb", mu, 8)
        self.text(p, "v_{out}", x1, 56, "rm", self.c.accent, 8)


class _DeltaWyeDiagram(CardFigure):
    """Nodes 1-3 match the card's formulas: R_a is opposite node 1."""
    W_PX, H_PX = 264, 130

    def draw(self, p):
        mu = self.c.muted
        ra, rb, rc, r1, r2, r3 = self.vals("ra", "rb", "rc", "r1", "r2", "r3")
        n1, n2, n3 = (60, 20), (24, 108), (96, 108)
        self.resistor(p, n1, n2); self.resistor(p, n1, n3); self.resistor(p, n2, n3)
        for q in (n1, n2, n3):
            self.term(p, *q)
        self.text(p, "1", 60, 12, "cb", mu, 8)
        self.text(p, "2", 18, 108, "rm", mu, 8)
        self.text(p, "3", 102, 108, "lm", mu, 8)
        self.stack(p, "R_c", eng(rc, "Ω"), 34, 58, "r")
        self.stack(p, "R_b", eng(rb, "Ω"), 86, 58, "l")
        self.text(p, "R_a", 58, 113, "rt"); self.text(p, eng(ra, "Ω"), 62, 114, "lt", mu, 8)
        self.arrow(p, (138, 64), (126, 64), mu); self.arrow(p, (138, 64), (150, 64), mu)
        cen, t1, t2, t3 = (198, 64), (198, 12), (162, 108), (234, 108)
        for t in (t1, t2, t3):
            self.resistor(p, cen, t)
            self.term(p, *t)
        self.node(p, *cen)
        self.text(p, "1", 205, 12, "lm", mu, 8)
        self.text(p, "2", 162, 114, "ct", mu, 8)
        self.text(p, "3", 234, 114, "ct", mu, 8)
        self.stack(p, "R_1", eng(r1, "Ω"), 206, 33, "l")
        self.stack(p, "R_2", eng(r2, "Ω"), 167, 78, "r")
        self.stack(p, "R_3", eng(r3, "Ω"), 226, 76, "l")


class _DirCouplerDiagram(CardFigure):
    W_PX, H_PX = 220, 118

    def draw(self, p):
        mu = self.c.muted
        pin, pth, pcp, pis, cdb, ddb = self.vals("pin", "p_thru", "p_cpl", "p_iso", "c_db", "d_db")
        ym, ys = 34, 82
        p.setPen(self.pen(mu, 1.0)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(58, 18, 104, 80), 6, 6)
        for x in (12, 208):
            self.term(p, x, ym); self.term(p, x, ys)
        self.wire(p, (14.8, ym), (82, ym), (90, 52), (130, 52), (138, ym), (205.2, ym))
        self.wire(p, (14.8, ys), (82, ys), (90, 64), (130, 64), (138, ys), (205.2, ys))
        for lbl, v, x, yy, al in (("P_{in}", pin, 10, ym, "l"), ("P_{thru}", pth, 210, ym, "r"),
                                  ("P_{iso}", pis, 10, ys, "l"), ("P_{cpl}", pcp, 210, ys, "r")):
            self.text(p, lbl, x, yy - 5, al + "b")
            self.text(p, db_txt(v, "dBm"), x, yy + 5, al + "t", mu, 8)
        parts = [s for s in (("C " + db_txt(cdb)) if cdb is not None else "",
                             ("D " + db_txt(ddb)) if ddb is not None else "") if s]
        self.text(p, "   ".join(parts), 110, 103, "ct", mu, 8)


class _ButterworthLadderDiagram(CardFigure):
    """kind 'LP' (series L, shunt C) or 'HP' (series C, shunt L), N = 3."""
    W_PX, H_PX = 220, 104

    def __init__(self, kind="LP", parent=None):
        super().__init__(None, parent)
        self.kind = kind

    def draw(self, p):
        mu = self.c.muted
        y, g, n = 34, 84, 110
        z0 = self.val("z0")
        self.term(p, 12, y); self.term(p, 208, y); self.node(p, n, y)
        if self.kind == "LP":
            l1, c2, l3 = self.vals("l1_nh", "c2_pf", "l3_nh")
            self.inductor(p, (14.8, y), (n, y)); self.inductor(p, (n, y), (205.2, y))
            self.capacitor(p, (n, y), (n, g))
            ser = (("L_1", eng(_f(l1, 1e-9), "H")), ("L_3", eng(_f(l3, 1e-9), "H")))
            sh = ("C_2", eng(_f(c2, 1e-12), "F"))
            up, dn, sx = 7, 6, n + 10
        else:
            c1, l2, c3 = self.vals("c1_pf", "l2_nh", "c3_pf")
            self.capacitor(p, (14.8, y), (n, y)); self.capacitor(p, (n, y), (205.2, y))
            self.inductor(p, (n, y), (n, g))
            ser = (("C_1", eng(_f(c1, 1e-12), "F")), ("C_3", eng(_f(c3, 1e-12), "F")))
            sh = ("L_2", eng(_f(l2, 1e-9), "H"))
            up, dn, sx = 10, 10, n + 10
        self.ground(p, n, g)
        for (ref, val), x in zip(ser, (62, 158)):
            self.text(p, ref, x, y - up, "cb")
            self.text(p, val, x, y + dn, "ct", mu, 8)
        self.stack(p, sh[0], sh[1], sx, 56)
        zt = eng(z0, "Ω")
        self.text(p, zt, 4, y + 6, "lt", mu, 8); self.text(p, zt, 216, y + 6, "rt", mu, 8)


class OpAmpDiagram(CardFigure):
    """Non-inverting or inverting gain stage, from the card's topology."""
    W_PX, H_PX = 240, 186

    def draw(self, p):
        mu = self.c.muted
        rf, rg = self.vals("rf", "rg")
        inv = self.card is not None and self.card._topo() == "inv"
        lx, ty, by, ax = 96.0, 40.0, 100.0, 150.0
        my, yn, yp = (ty + by) / 2, 54.0, 86.0
        p.setPen(self.pen()); p.setBrush(self.c.fill if THEME != "dark" else Qt.NoBrush)
        p.drawPolygon(QPolygonF([QPointF(lx, ty), QPointF(ax, my), QPointF(lx, by)]))
        minus_y, plus_y = (yn, yp) if inv else (yp, yn)
        self.text(p, "−", lx + 5, minus_y, "lm", None, 11)
        self.text(p, "+", lx + 5, plus_y, "lm", None, 11)
        tap, xo = 200.0, 230.0
        self.wire(p, (ax, my), (xo - 2.8, my)); self.term(p, xo, my); self.node(p, tap, my)
        self.text(p, "V_{out}", xo + 4, my - 8, "rb")
        if not inv:
            self.term(p, 10, yn); self.wire(p, (12.8, yn), (lx, yn))
            self.text(p, "V_{in}", 6, yn - 6, "lb")
            a = (70.0, 128.0)
            self.wire(p, (lx, yp), (a[0], yp), a); self.node(p, *a)
            self.resistor(p, a, (tap, a[1])); self.wire(p, (tap, a[1]), (tap, my))
            self.resistor(p, a, (a[0], 166)); self.ground(p, a[0], 166)
            self.text(p, "R_f", 135, a[1] - 7, "cb"); self.text(p, eng(rf, "Ω"), 135, a[1] + 7, "ct", mu, 8)
            self.stack(p, "R_g", eng(rg, "Ω"), 80, 141, "l")
        else:
            b, top = (70.0, yn), 24.0
            self.term(p, 10, yn); self.resistor(p, (12.8, yn), b)
            self.wire(p, b, (lx, yn)); self.node(p, *b)
            self.text(p, "V_{in}", 6, yn - 8, "lb")
            self.text(p, "R_{in}", 42, yn - 7, "cb"); self.text(p, eng(rg, "Ω"), 42, yn + 7, "ct", mu, 8)
            self.wire(p, b, (b[0], top)); self.resistor(p, (b[0], top), (tap, top))
            self.wire(p, (tap, top), (tap, my))
            self.text(p, "R_f", 135, top - 7, "cb"); self.text(p, eng(rf, "Ω"), 135, top + 7, "ct", mu, 8)
            self.wire(p, (lx, yp), (80, yp), (80, 98)); self.ground(p, 80, 98)


class CascadeNFDiagram(CardFigure):
    W_PX, H_PX = 220, 78

    def draw(self, p):
        mu = self.c.muted
        y = 40
        self.term(p, 8, y)
        xs = (30, 98, 166)
        self.wire(p, (10.8, y), (xs[0], y))
        for k, x in enumerate(xs):
            self.amp(p, x, y)
            nxt = xs[k + 1] if k < 2 else None
            if nxt:
                self.wire(p, (x + 26, y), (nxt, y))
            g, nf = self.vals(f"g{k + 1}", f"nf{k + 1}")
            cx = x + 13
            self.text(p, f"G_{k + 1}" + (" " + db_txt(g) if g is not None else ""), cx, y - 16, "cb", None, 8)
            self.text(p, f"NF_{k + 1}" + (" " + db_txt(nf) if nf is not None else ""), cx, y + 16, "ct", mu, 8)
        self.arrow(p, (192, y), (214, y))


class SourceLoadDiagram(CardFigure):
    W_PX, H_PX = 220, 66

    def draw(self, p):
        mu = self.c.muted
        src, loss, load = self.vals("src_dbm", "loss_db", "load_dbm")
        yt, h, w = 28, 28, 52
        cy = yt + h / 2
        for x, name in ((6, "Source"), (162, "Load")):
            self.box(p, x, yt, w, h)
            self.text(p, name, x + w / 2, cy, "cm", None, 8.5)
        self.box(p, 84, yt, w, h)
        self.hatch(p, QRectF(84, yt, w, h), 6, mu)
        self.box(p, 84, yt, w, h)
        self.text(p, db_txt(loss) if loss is not None else "loss", 110, cy, "cm", None, 8.5, knock=True)
        self.arrow(p, (58, cy), (84, cy)); self.arrow(p, (136, cy), (162, cy))
        self.text(p, db_txt(src, "dBm"), 32, yt - 4, "cb", mu, 8)
        self.text(p, db_txt(load, "dBm"), 188, yt - 4, "cb", mu, 8)


# ---- transmission-line cross-sections, drawn to the entered geometry ----

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _ratio(a, b, default):
    """a/b when both are positive, else `default` (a static proportion)."""
    if a is None or b is None or a <= 0 or b <= 0:
        return default
    return _clamp(a / b, 1e-6, 1e6)


def _mix(a, b, t):
    t = _clamp(t, 0.0, 1.0)
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class _XSection(CardFigure):
    """PCB / cable cross-section: copper, dielectric, eps_r readout."""
    W_PX, H_PX = 220, 128

    def diel(self, p, rect):
        self.slab(p, rect, self.c.diel, self.c.diel_edge)

    def er_label(self, p, x, y, align="cm"):
        er = self.val("er")
        self.text(p, "ε_r" + (" " + sig3(er) if er is not None else ""), x, y, align,
                  self.c.muted, 8)


class MicrostripDiagram(_XSection):
    W_PX, H_PX = 220, 116

    def draw(self, p):
        w, h, t = self.vals("w", "h", "t")
        hp = 44.0
        wp = _clamp(_ratio(w, h, 2.0) * hp, 10, 148)
        tp = _clamp(_ratio(t, h, 0.07) * hp, 2.5, 10)
        x0, x1, top = 34.0, 194.0, 60.0
        bot, cx = top + hp, (x0 + x1) / 2
        self.diel(p, QRectF(x0, top, x1 - x0, hp))
        self.copper(p, QRectF(x0, bot, x1 - x0, 6))
        tr = QRectF(cx - wp / 2, top - tp, wp, tp)
        self.copper(p, tr)
        self.dim_h(p, tr.left(), tr.right(), tr.top() - 9, "W", feat=tr.top())
        self.dim_v(p, tr.top(), top, tr.right() + 10, "t", feat=tr.right(), left=False)
        self.dim_v(p, top, bot, x0 - 10, "h", feat=x0)
        self.er_label(p, cx, top + hp / 2 + 4)


class StriplineDiagram(_XSection):
    W_PX, H_PX = 220, 104

    def draw(self, p):
        w, b, t = self.vals("w", "b", "t")
        bp = 60.0
        wp = _clamp(_ratio(w, b, 0.8) * bp, 10, 148)
        tp = _clamp(_ratio(t, b, 0.05) * bp, 2.5, 10)
        x0, x1, top = 34.0, 194.0, 22.0
        bot, cx, cy = top + bp, (x0 + x1) / 2, top + bp / 2
        self.copper(p, QRectF(x0, top - 6, x1 - x0, 6))
        self.diel(p, QRectF(x0, top, x1 - x0, bp))
        self.copper(p, QRectF(x0, bot, x1 - x0, 6))
        tr = QRectF(cx - wp / 2, cy - tp / 2 + 4, wp, tp)
        self.copper(p, tr)
        self.dim_h(p, tr.left(), tr.right(), tr.top() - 8, "W", feat=tr.top())
        self.dim_v(p, tr.top(), tr.bottom(), tr.right() + 10, "t", feat=tr.right(), left=False)
        self.dim_v(p, top, bot, x0 - 10, "b", feat=x0)
        self.er_label(p, x0 + 6, bot - 8, "lm")


class CPWDiagram(_XSection):
    """Coplanar waveguide; GCPWDiagram adds the backside ground and h."""
    W_PX, H_PX = 220, 112
    GROUNDED = False

    def draw(self, p):
        w, s = self.vals("w", "s")
        ws = _ratio(w, s, 2.0)
        sp = 120.0 / (ws + 2)
        wp, sp = max(ws * sp, 16.0), max(sp, 16.0)
        x0, x1, top, ct = 30.0, 196.0, 50.0, 5.0
        cx = (x0 + x1) / 2
        if self.GROUNDED:
            h = self.val("h")
            hp = _clamp(_ratio(h, (w or 0) + 2 * (s or 0), 0.4) * (wp + 2 * sp), 18, 54)
        else:
            hp = 46.0
        bot = top + hp
        self.diel(p, QRectF(x0, top, x1 - x0, hp))
        if self.GROUNDED:
            self.copper(p, QRectF(x0, bot, x1 - x0, 6))
            self.dim_v(p, top, bot, x0 - 10, "h", feat=x0)
        g1, g2 = cx - wp / 2 - sp, cx + wp / 2 + sp
        for r in (QRectF(x0, top - ct, g1 - x0, ct), QRectF(cx - wp / 2, top - ct, wp, ct),
                  QRectF(g2, top - ct, x1 - g2, ct)):
            self.copper(p, r)
        yd = top - ct - 9
        self.dim_h(p, g1, cx - wp / 2, yd, "S", feat=top - ct)
        self.dim_h(p, cx - wp / 2, cx + wp / 2, yd, "W", feat=top - ct)
        self.dim_h(p, cx + wp / 2, g2, yd, "S", feat=top - ct)
        self.er_label(p, cx, top + hp / 2 + 3)


class GCPWDiagram(CPWDiagram):
    W_PX, H_PX = 220, 116
    GROUNDED = True


class CoaxDiagram(_XSection):
    W_PX, H_PX = 220, 136

    def draw(self, p):
        D, d = self.vals("D", "d")
        cx, cy, R, ring = 110.0, 56.0, 44.0, 6.0
        rd = _clamp(_ratio(d, D, 0.3) * R, 3.0, R - 6)
        for rad, fill, edge in ((R + ring, self.c.cu, self.c.cu_edge),
                                (R, self.c.diel, self.c.diel_edge),
                                (rd, self.c.cu, self.c.cu_edge)):
            p.setPen(self.pen(edge, 0.9)); p.setBrush(fill)
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        self.dim_h(p, cx - rd, cx + rd, cy)
        self.text(p, "d", cx, cy - rd - 2, "cb", self.c.dim, 8)
        self.dim_h(p, cx - R, cx + R, cy + R + ring + 12, "D", feat=cy, above=False)
        self.er_label(p, cx - R * 0.5, cy - R * 0.55)


class TwinLeadDiagram(_XSection):
    W_PX, H_PX = 220, 122

    def draw(self, p):
        s, d, er = self.vals("s", "d", "er")
        sp, cy = 96.0, 62.0
        dp = _clamp(_ratio(d, s, 0.25) * sp, 6.0, 56.0)
        x1, x2 = 110 - sp / 2, 110 + sp / 2
        web = er is not None and er > 1.05
        if web:
            self.slab(p, QRectF(x1, cy - 7, sp, 14), self.c.diel, self.c.diel_edge)
        for x in (x1, x2):
            p.setPen(self.pen(self.c.cu_edge, 0.9)); p.setBrush(self.c.cu)
            p.drawEllipse(QPointF(x, cy), dp / 2, dp / 2)
            p.setPen(self.pen(self.c.cu_edge, 0.7))
            p.drawLine(QPointF(x - 2.5, cy), QPointF(x + 2.5, cy))
            p.drawLine(QPointF(x, cy - 2.5), QPointF(x, cy + 2.5))
        self.dim_h(p, x1 - dp / 2, x1 + dp / 2, cy - dp / 2 - 10, "d", feat=cy)
        self.dim_h(p, x1, x2, cy + max(dp / 2, 7) + 14, "S", feat=cy, above=False)
        if web:
            self.er_label(p, 110, cy)


class SkinDepthDiagram(CardFigure):
    """Conductor cross-section shaded by current density J ∝ exp(−x/δ),
    peaking at the surface, plus J against depth."""
    W_PX, H_PX = 220, 124

    def draw(self, p):
        d_um = self.val("delta_um")
        cx, cy, R, dp = 70.0, 62.0, 46.0, 11.0
        lo = QColor(246, 232, 214) if THEME != "dark" else QColor(58, 46, 34)
        g = QRadialGradient(QPointF(cx, cy), R)
        for k in range(21):
            r = k / 20
            g.setColorAt(r, _mix(lo, self.c.cu, math.exp(-(1 - r) * R / dp)))
        p.setPen(self.pen(self.c.cu_edge, 1.0)); p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), R, R)
        p.setPen(self.pen(self.c.cu_edge, 0.8, Qt.DashLine)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), R - dp, R - dp)
        self.dim_h(p, cx - R, cx - R + dp, cy)
        self.text(p, "δ", cx - R - 12, cy, "rm", self.c.dim, 9)
        # J against depth: J/J_s = exp(-x/δ), δ at the 1/e point
        x0, x1, yb, yt = 140.0, 212.0, 96.0, 30.0
        dx = 22.0
        p.setPen(self.pen(self.c.muted, 0.8))
        p.drawLine(QPointF(x0, yt - 4), QPointF(x0, yb)); p.drawLine(QPointF(x0, yb), QPointF(x1, yb))
        pts = [QPointF(x0 + t, yb - (yb - yt) * math.exp(-t / dx)) for t in range(0, int(x1 - x0) + 1)]
        p.setPen(self.pen(self.c.accent, 1.6)); p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        ye = yb - (yb - yt) / math.e
        p.setPen(self.pen(self.c.dim, 0.8, Qt.DashLine))
        p.drawLine(QPointF(x0, ye), QPointF(x0 + dx, ye)); p.drawLine(QPointF(x0 + dx, ye), QPointF(x0 + dx, yb))
        self.text(p, "J", x0 - 3, yt - 2, "rm", self.c.muted, 8)
        self.text(p, "x", x1, yb + 2, "rt", self.c.muted, 8)
        self.text(p, "1/e", x0 - 3, ye, "rm", self.c.dim, 7.5)
        self.text(p, "δ", x0 + dx, yb + 2, "ct", self.c.dim, 8)
        if d_um is not None:
            self.text(p, "δ = " + eng(d_um * 1e-6, "m"), cx, cy + R + 9, "cm", self.c.dim, 8.5)


class StriplineCard(TLineCard):
    DIM_FIELDS  = ("w", "b", "t")
    SOLVABLE    = ("z0", "w", "b", "er")
    SOLVE_LABEL = {"z0": "Z₀", "w": "W", "b": "b", "er": "εr"}

    def __init__(self):
        super().__init__("Stripline Z₀ (IPC-2141)", [
            Field("w",  "Trace width W",     "mm"),
            Field("b",  "Plate spacing b",   "mm"),
            Field("t",  "Trace thickness t", "mm"),
            Field("er", "Dielectric εr",     ""),
            Field("z0", "Z₀",                "Ω"),
            Field("vp_pct", "Vp (% of c)",   "%", is_output=True),
        ])

    def make_diagram(self):
        return StriplineDiagram()

    @staticmethod
    def _z0(W, b, t, er):
        if None in (W, b, er) or W <= 0 or b <= 0 or er <= 0:
            return None
        if t is None: t = 0.0
        if t < 0 or t >= b: return None
        try:
            return (60.0 / sqrt(er)) * log(1.9 * b / (0.8 * W + t))
        except (ValueError, ZeroDivisionError):
            return None

    def compute(self, driver, v):
        W  = self._dim_to_mm(v.get("w"))
        b  = self._dim_to_mm(v.get("b"))
        t  = self._dim_to_mm(v.get("t"))
        if t is None: t = 0.0
        er = v.get("er")
        z0 = v.get("z0")
        unk = self._unknown

        if unk == "z0":
            r = self._z0(W, b, t, er)
            if r is None or r <= 0: return {}
            return {"z0": r, "vp_pct": 100 / sqrt(er)}
        if z0 is None or z0 <= 0:
            return {}
        if unk == "w":
            if b is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0(x, b, t, er), z0, 1e-4, max(b - t - 1e-6, 1e-3) * 50, increasing=False)
            if sol is None: return {}
            return {"w": self._mm_to_dim(sol), "vp_pct": 100 / sqrt(er)}
        if unk == "b":
            if W is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0(W, x, t, er), z0, max(t + 1e-6, 1e-4), 1e3, increasing=True)
            if sol is None: return {}
            return {"b": self._mm_to_dim(sol), "vp_pct": 100 / sqrt(er)}
        if unk == "er":
            if W is None or b is None: return {}
            sol = self._bisect(lambda x: self._z0(W, b, t, x), z0, 1.001, 100, increasing=False)
            if sol is None: return {}
            return {"er": sol, "vp_pct": 100 / sqrt(sol)}
        return {}


class CPWCard(TLineCard):
    """Coplanar waveguide on infinite dielectric (no backside ground)."""
    DIM_FIELDS  = ("w", "s")
    SOLVABLE    = ("z0", "w", "s", "er")
    SOLVE_LABEL = {"z0": "Z₀", "w": "W", "s": "S", "er": "εr"}

    def __init__(self):
        super().__init__("CPW Z₀  (no backside ground, Hilberg)", [
            Field("w",  "Center trace width W", "mm"),
            Field("s",  "Gap S",                "mm"),
            Field("er", "Dielectric εr",        ""),
            Field("z0", "Z₀",                   "Ω"),
            Field("eeff",   "Effective ε",      "",  is_output=True),
            Field("vp_pct", "Vp (% of c)",      "%", is_output=True),
        ])

    def make_diagram(self):
        return CPWDiagram()

    @staticmethod
    def _z0_eeff(W, s, er):
        if None in (W, s, er) or W <= 0 or s <= 0 or er <= 0:
            return None
        k = W / (W + 2 * s)
        kp = sqrt(max(0.0, 1 - k * k))
        try:
            if k <= 1.0 / sqrt(2):
                sk = sqrt(kp)
                kk = pi / log(2 * (1 + sk) / (1 - sk))
            else:
                sk = sqrt(k)
                kk = log(2 * (1 + sk) / (1 - sk)) / pi
            kpk = 1.0 / kk
        except (ValueError, ZeroDivisionError):
            return None
        eeff = (er + 1) / 2.0
        z0 = (30.0 * pi / sqrt(eeff)) * kpk
        return z0, eeff

    def compute(self, driver, v):
        W  = self._dim_to_mm(v.get("w"))
        s  = self._dim_to_mm(v.get("s"))
        er = v.get("er")
        z0 = v.get("z0")
        unk = self._unknown

        if unk == "z0":
            r = self._z0_eeff(W, s, er)
            if r is None: return {}
            return {"z0": r[0], "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if z0 is None or z0 <= 0:
            return {}
        if unk == "w":
            if s is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(x, s, er)[0], z0, 1e-4, 1e3, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(sol, s, er)
            return {"w": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "s":
            if W is None or er is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(W, x, er)[0], z0, 1e-4, 1e3, increasing=True)
            if sol is None: return {}
            r = self._z0_eeff(W, sol, er)
            return {"s": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "er":
            if W is None or s is None: return {}
            sol = self._bisect(lambda x: self._z0_eeff(W, s, x)[0], z0, 1.001, 100, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(W, s, sol)
            return {"er": sol, "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        return {}


class GCPWCard(TLineCard):
    """Conductor-backed (grounded) coplanar waveguide.

    Top conductors (signal + coplanar grounds) sit on a substrate of height
    h with a continuous ground plane on the back side.  This is the geometry
    almost every PCB designer actually builds.

    εeff = (1 + εr · q) / (1 + q),   q = (K(k₃)/K(k₃')) / (K(k₁)/K(k₁'))
    Z₀   = 60π / √εeff / ( K(k₁)/K(k₁') + K(k₃)/K(k₃') )
    where  k₁ = W/(W+2S),   k₃ = tanh(πW/4h) / tanh(π(W+2S)/4h)
    """
    DIM_FIELDS  = ("w", "s", "h")
    SOLVABLE    = ("z0", "w", "s", "h", "er")
    SOLVE_LABEL = {"z0": "Z₀", "w": "W", "s": "S", "h": "h", "er": "εr"}

    def __init__(self):
        super().__init__("Grounded CPW (CB-CPW) Z₀", [
            Field("w",  "Center trace width W", "mm"),
            Field("s",  "Gap S",                "mm"),
            Field("h",  "Substrate height h",   "mm"),
            Field("er", "Dielectric εr",        ""),
            Field("z0", "Z₀",                   "Ω"),
            Field("eeff",   "Effective ε",      "",  is_output=True),
            Field("vp_pct", "Vp (% of c)",      "%", is_output=True),
            Field("freq",   "Frequency",         "GHz"),
            Field("rough",  "Surface roughness", "µm"),
            Field("loss_c", "Cond. loss",        "dB", is_output=True),
            Field("loss_d", "Diel. loss",        "dB", is_output=True),
            Field("loss",   "Total loss",        "dB", is_output=True),
        ])

    def make_diagram(self):
        return GCPWDiagram()

    @staticmethod
    def _kk_ratio(k):
        """K(k)/K(k') via Hilberg approximation. Returns None for k ∉ (0, 1)."""
        if k is None or k <= 0 or k >= 1:
            return None
        kp = sqrt(max(0.0, 1 - k * k))
        try:
            if k <= 1.0 / sqrt(2):
                sk = sqrt(kp)
                return pi / log(2 * (1 + sk) / (1 - sk))
            else:
                sk = sqrt(k)
                return log(2 * (1 + sk) / (1 - sk)) / pi
        except (ValueError, ZeroDivisionError):
            return None

    @classmethod
    def _z0_eeff(cls, W, s, h, er):
        if None in (W, s, h, er) or W <= 0 or s <= 0 or h <= 0 or er <= 0:
            return None
        try:
            k1 = W / (W + 2 * s)
            t1 = math.tanh(pi * W / (4 * h))
            t2 = math.tanh(pi * (W + 2 * s) / (4 * h))
            if t2 <= 0:
                return None
            k3 = t1 / t2
            # tanh saturates to exactly 1.0 for large W/h; clamp k₁,k₃ just
            # below 1 so K(k)/K(k') stays finite (the limit is "very large").
            k1 = min(max(k1, 1e-12), 1.0 - 1e-12)
            k3 = min(max(k3, 1e-12), 1.0 - 1e-12)
            kk1 = cls._kk_ratio(k1)
            kk3 = cls._kk_ratio(k3)
            if kk1 is None or kk3 is None or kk1 <= 0 or kk3 <= 0:
                return None
            q = kk3 / kk1
            eeff = (1 + er * q) / (1 + q)
            z0 = 60 * pi / (sqrt(eeff) * (kk1 + kk3))
            return z0, eeff
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

    def compute(self, driver, v):
        W  = self._dim_to_mm(v.get("w"))
        s  = self._dim_to_mm(v.get("s"))
        h  = self._dim_to_mm(v.get("h"))
        er = v.get("er")
        z0 = v.get("z0")
        unk = self._unknown

        def _z(W, s, h, er):
            r = self._z0_eeff(W, s, h, er)
            return r[0] if r else None

        if unk == "z0":
            r = self._z0_eeff(W, s, h, er)
            if r is None: return {}
            return {"z0": r[0], "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if z0 is None or z0 <= 0:
            return {}
        if unk == "w":
            if s is None or h is None or er is None: return {}
            sol = self._bisect(lambda x: _z(x, s, h, er), z0, 1e-4, 1e3, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(sol, s, h, er)
            return {"w": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "s":
            if W is None or h is None or er is None: return {}
            sol = self._bisect(lambda x: _z(W, x, h, er), z0, 1e-4, 1e3, increasing=True)
            if sol is None: return {}
            r = self._z0_eeff(W, sol, h, er)
            return {"s": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "h":
            if W is None or s is None or er is None: return {}
            sol = self._bisect(lambda x: _z(W, s, x, er), z0, 1e-4, 1e4, increasing=True)
            if sol is None: return {}
            r = self._z0_eeff(W, s, sol, er)
            return {"h": self._mm_to_dim(sol), "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        if unk == "er":
            if W is None or s is None or h is None: return {}
            sol = self._bisect(lambda x: _z(W, s, h, x), z0, 1.001, 100, increasing=False)
            if sol is None: return {}
            r = self._z0_eeff(W, s, h, sol)
            return {"er": sol, "eeff": r[1], "vp_pct": 100 / sqrt(r[1])}
        return {}

    # ------------------------------------------------------------------
    # GCPW loss (approximate).  Conductor loss uses the simple Rs/(Z₀·W)
    # microstrip-style estimate (close for GCPW where the ground spacing
    # is comparable to or larger than h); dielectric loss uses the
    # filling-factor form of microstrip.  Returns dB/m or None.
    # ------------------------------------------------------------------
    def loss_components_db_per_m(self, f_hz):
        v = self._collect()
        W_mm = self._dim_to_mm(v.get("w"))
        s_mm = self._dim_to_mm(v.get("s"))
        h_mm = self._dim_to_mm(v.get("h"))
        er   = v.get("er")
        if None in (W_mm, s_mm, h_mm, er) or W_mm <= 0 or s_mm <= 0 or h_mm <= 0 or er <= 1:
            return None
        if f_hz is None or f_hz <= 0:
            return None
        r = self._z0_eeff(W_mm, s_mm, h_mm, er)
        if r is None:
            return None
        z0, eeff = r
        if z0 <= 0 or eeff <= 0:
            return None
        Rs = sqrt(pi * f_hz * MU0 * self._cond_rho)
        W = W_mm * 1e-3
        alpha_c = (Rs / (z0 * W)) * self._roughness_factor(f_hz)
        tan_d = self._tan_d if self._tan_d is not None else 0.0
        k0 = 2 * pi * f_hz / C_LIGHT
        if er > 1.0:
            alpha_d = (k0 * er * (eeff - 1.0) * tan_d) / (2.0 * sqrt(eeff) * (er - 1.0))
        else:
            alpha_d = 0.0
        return alpha_c * NP2DB, alpha_d * NP2DB


class TwinLeadCard(CalcCard):
    """Two parallel cylindrical wires (S = center-to-center, d = wire OD)."""
    def __init__(self):
        super().__init__("Twin-lead / parallel-wire Z₀", [
            Field("s",  "Center-to-center S", "any unit"),
            Field("d",  "Wire diameter d", "same unit"),
            Field("er", "Surrounding εr", ""),
            Field("z0", "Z₀", "Ω", is_output=True),
            Field("vp_pct", "Vp (% of c)", "%", is_output=True),
        ])
        self.fields["er"].edit.setText("1")

    def make_diagram(self):
        return TwinLeadDiagram()

    def compute(self, driver, v):
        s = v.get("s"); d = v.get("d"); er = v.get("er")
        if er is None or er <= 0:
            er = 1.0
        if None in (s, d) or s <= 0 or d <= 0 or s <= d:
            return {"er": er}
        ratio = s / d
        try:
            z0 = (120.0 / sqrt(er)) * log(ratio + sqrt(ratio * ratio - 1))
        except (ValueError, ZeroDivisionError):
            return {"er": er}
        return {"er": er, "z0": z0, "vp_pct": 100 / sqrt(er)}


class ElectricalLengthCard(CalcCard):
    """Physical length ↔ electrical length / phase / time delay."""
    def __init__(self):
        super().__init__("Electrical length / phase / delay", [
            Field("len_mm", "Physical length", "mm"),
            Field("len_in", "Physical length", "in"),
            Field("f_mhz",  "Frequency", "MHz"),
            Field("vf",     "Velocity factor", "0..1"),
            Field("er_eff", "Effective εr", ""),
            Field("elen_lam", "Electrical length", "λ", is_output=True),
            Field("elen_deg", "Electrical length", "deg", is_output=True),
            Field("delay_ns", "One-way delay", "ns", is_output=True),
        ])
        self.fields["vf"].edit.setText("1")

    def compute(self, driver, v):
        L_mm = v.get("len_mm"); L_in = v.get("len_in")
        f = v.get("f_mhz"); vf = v.get("vf"); er = v.get("er_eff")
        # link length units
        if driver == "len_mm" and L_mm is not None:
            L_in = L_mm / 25.4
        elif driver == "len_in" and L_in is not None:
            L_mm = L_in * 25.4
        # link vf <-> er
        if driver == "vf" and vf and vf > 0:
            er = 1.0 / (vf * vf)
        elif driver == "er_eff" and er and er > 0:
            vf = 1.0 / sqrt(er)
        out = {"len_mm": L_mm, "len_in": L_in, "vf": vf, "er_eff": er}
        if vf is None or vf <= 0:
            return out
        if L_mm is None or f is None or f <= 0:
            return out
        v_p = vf * C_LIGHT
        L_m = L_mm * 1e-3
        wavelen_m = v_p / (f * 1e6)
        elen_lam = L_m / wavelen_m
        out.update({
            "elen_lam": elen_lam,
            "elen_deg": elen_lam * 360.0,
            "delay_ns": (L_m / v_p) * 1e9,
        })
        return out


# ====================================================================
#  TLINES TAB — global "apply to all" header
# ====================================================================

class TLinesHeader(QWidget):
    """Top-of-tab control bar that drives Material / Solve / Conductor /
    Length on every TLineCard below.  Built before the cards by
    build_tab(); after card construction the runtime calls
    `connect_cards(cards)` to register the targets.

    Each control change is propagated by writing through to the per-card
    combos so the cards' existing handlers (palette, recompute, loss
    refresh) fire normally.  Cards whose SOLVABLE list doesn't include
    the chosen Solve target are simply left alone."""

    SOLVE_GLOBAL = (("Z₀", "z0"), ("εr", "er"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards = []
        self._propagating = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)

        # Two rows so the bar fits a 630 px window.
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0); row2.setSpacing(6)
        row.addWidget(QLabel("Material:"))
        self.mat = QComboBox()
        for name, _er, _tan in MATERIALS:
            self.mat.addItem(name)
        self.mat.setMinimumWidth(160); self.mat.setMaximumHeight(20)
        self.mat.currentTextChanged.connect(self._on_mat)
        row.addWidget(self.mat)

        row.addSpacing(6); row.addWidget(QLabel("Solve:"))
        self.solve = QComboBox()
        for label, _ in self.SOLVE_GLOBAL:
            self.solve.addItem(label)
        self.solve.setMaximumHeight(20); self.solve.setMinimumWidth(60)
        self.solve.currentIndexChanged.connect(self._on_solve)
        row.addWidget(self.solve)

        row.addStretch(1)

        row2.addWidget(QLabel("Conductor:"))
        self.cond = QComboBox()
        for name, _rho in CONDUCTORS:
            self.cond.addItem(name)
        self.cond.setMinimumWidth(110); self.cond.setMaximumHeight(20)
        self.cond.currentTextChanged.connect(self._on_cond)
        row2.addWidget(self.cond)

        row2.addSpacing(6); row2.addWidget(QLabel("Length:"))
        self.length = QLineEdit("1")
        self.length.setMaximumWidth(70); self.length.setMaximumHeight(18)
        self.length.textEdited.connect(self._on_length)
        row2.addWidget(self.length)
        row2.addWidget(QLabel("in"))

        row2.addSpacing(6); row2.addWidget(QLabel("Freq:"))
        self.freq = QLineEdit("10")
        self.freq.setMaximumWidth(60); self.freq.setMaximumHeight(18)
        self.freq.textEdited.connect(self._on_freq)
        row2.addWidget(self.freq)
        row2.addWidget(QLabel("GHz"))
        row2.addStretch(1)
        outer.addLayout(row)
        outer.addLayout(row2)

    def connect_cards(self, cards):
        """Filter to TLineCard instances and remember them as propagation
        targets.  Pulls the initial state of each combo from the first
        card so the header reflects what's already on screen."""
        self._cards = [c for c in cards if isinstance(c, TLineCard)]
        if not self._cards:
            return
        first = self._cards[0]
        self._propagating = True
        try:
            if first._mat_combo is not None:
                idx = self.mat.findText(first._mat_combo.currentText())
                if idx >= 0: self.mat.setCurrentIndex(idx)
            if first._cond_combo is not None:
                idx = self.cond.findText(first._cond_combo.currentText())
                if idx >= 0: self.cond.setCurrentIndex(idx)
            if first._length_edit is not None:
                self.length.setText(first._length_edit.text())
            # Frequency lives on loss-capable cards only — seed from the
            # first card that has one.
            for c in self._cards:
                fq = c.fields.get("freq")
                if fq is not None and fq.edit is not None and fq.edit.text().strip():
                    self.freq.setText(fq.edit.text())
                    break
        finally:
            self._propagating = False

    # ---- propagation -------------------------------------------------
    def _on_mat(self, name):
        if self._propagating:
            return
        self._propagating = True
        try:
            for c in self._cards:
                if c._mat_combo is not None:
                    c._mat_combo.setCurrentText(name)
        finally:
            self._propagating = False

    def _on_cond(self, name):
        if self._propagating:
            return
        self._propagating = True
        try:
            for c in self._cards:
                if c._cond_combo is not None:
                    c._cond_combo.setCurrentText(name)
        finally:
            self._propagating = False

    def _on_length(self, text):
        if self._propagating:
            return
        for c in self._cards:
            if c._length_edit is not None:
                c._length_edit.setText(text)
                c._update_total_loss()

    def _on_freq(self, text):
        if self._propagating:
            return
        for c in self._cards:
            fq = c.fields.get("freq")
            if fq is not None and fq.edit is not None:
                fq.edit.blockSignals(True)
                fq.edit.setText(text)
                fq.edit.blockSignals(False)
                c._update_total_loss()

    def _on_solve(self, idx):
        if self._propagating or idx < 0:
            return
        target = self.SOLVE_GLOBAL[idx][1]
        for c in self._cards:
            if target in c.SOLVABLE and c._solve_combo is not None:
                c._solve_combo.setCurrentIndex(c.SOLVABLE.index(target))


# ====================================================================
#  TRANSMISSION-LINE LOSS TABLE DIALOG
# ====================================================================

class TLineLossTableDialog(QDialog):
    """2-D table of total transmission-line loss vs frequency × length,
    with an optional matplotlib plot below.  Clicking a column header
    plots loss vs frequency at that length; clicking a row header plots
    loss vs length at that frequency."""

    FREQS_GHZ  = list(range(1, 51))                                # 1..50 GHz
    LENGTHS_IN = [round(0.1 * i, 1) for i in range(0, 101)]        # 0.0..10.0 in

    def __init__(self, card, parent=None):
        super().__init__(parent)
        self.card = card
        self.setWindowTitle(f"Loss table — {card.title()}")
        self.resize(960, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # Header line summarising the assumed material parameters
        cond = card._cond_name
        rho  = card._cond_rho
        tan_d = card._tan_d if card._tan_d is not None else 0.0
        info = QLabel(
            f"Conductor: <b>{cond}</b> (ρ = {rho:.2e} Ω·m)   "
            f"|   tan δ = <b>{tan_d:g}</b>   "
            f"|   Click a column header to plot loss vs frequency, "
            f"or a row header to plot loss vs length."
        )
        info.setTextFormat(Qt.RichText)
        info.setStyleSheet("padding:2px 6px;")
        layout.addWidget(info)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        # ---- table -----------------------------------------------------
        n_rows = len(self.FREQS_GHZ)
        n_cols = len(self.LENGTHS_IN)
        self.table = QTableWidget(n_rows, n_cols)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(16)
        self.table.horizontalHeader().setDefaultSectionSize(46)
        for r, f_ghz in enumerate(self.FREQS_GHZ):
            self.table.setVerticalHeaderItem(r, QTableWidgetItem(f"{f_ghz} GHz"))
        for c, L_in in enumerate(self.LENGTHS_IN):
            self.table.setHorizontalHeaderItem(c, QTableWidgetItem(f"{L_in:.1f}\""))
        # Compute dB/m once per frequency (fast) then multiply by lengths.
        self._loss_per_m = []
        for f_ghz in self.FREQS_GHZ:
            try:
                v = self.card.loss_db_per_m(f_ghz * 1e9)
            except Exception:
                v = None
            self._loss_per_m.append(v)
        for r, db_per_m in enumerate(self._loss_per_m):
            for c, L_in in enumerate(self.LENGTHS_IN):
                if db_per_m is None:
                    text = "—"
                else:
                    val = db_per_m * (L_in * 0.0254)
                    text = f"{val:.3f}"
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.table.horizontalHeader().sectionClicked.connect(self._plot_vs_freq)
        self.table.verticalHeader().sectionClicked.connect(self._plot_vs_length)
        splitter.addWidget(self.table)

        # ---- plot canvas ----------------------------------------------
        if HAS_SMITH:
            self.fig = Figure(figsize=(7, 3), dpi=100, tight_layout=True)
            self.canvas = FigureCanvas(self.fig)
            self.ax = self.fig.add_subplot(111)
            self.ax.grid(True, ls=":", lw=0.5)
            splitter.addWidget(self.canvas)
            splitter.setSizes([400, 200])
            # Default: plot loss vs frequency at 5"
            try:
                idx5 = self.LENGTHS_IN.index(5.0)
                self._plot_vs_freq(idx5)
            except ValueError:
                pass
        else:
            note = QLabel("matplotlib not available — install matplotlib for plots")
            note.setStyleSheet("padding:8px; color:#888;")
            splitter.addWidget(note)

        # Close button row
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ---- plot handlers -------------------------------------------------
    def _plot_vs_freq(self, col):
        if not HAS_SMITH or col < 0 or col >= len(self.LENGTHS_IN):
            return
        L_in = self.LENGTHS_IN[col]
        L_m  = L_in * 0.0254
        ys = []
        xs = []
        for f_ghz, db_per_m in zip(self.FREQS_GHZ, self._loss_per_m):
            if db_per_m is None:
                continue
            xs.append(f_ghz)
            ys.append(db_per_m * L_m)
        self.ax.clear()
        self.ax.plot(xs, ys, marker="o", markersize=3, lw=1.2, color="#2266cc")
        self.ax.set_title(f"Loss vs frequency  —  length = {L_in:.1f}\"")
        self.ax.set_xlabel("Frequency (GHz)")
        self.ax.set_ylabel("Loss (dB)")
        self.ax.grid(True, ls=":", lw=0.5)
        self.canvas.draw_idle()

    def _plot_vs_length(self, row):
        if not HAS_SMITH or row < 0 or row >= len(self.FREQS_GHZ):
            return
        f_ghz = self.FREQS_GHZ[row]
        db_per_m = self._loss_per_m[row]
        if db_per_m is None:
            return
        xs = self.LENGTHS_IN
        ys = [db_per_m * (L * 0.0254) for L in xs]
        self.ax.clear()
        self.ax.plot(xs, ys, marker="o", markersize=3, lw=1.2, color="#cc6622")
        self.ax.set_title(f"Loss vs length  —  f = {f_ghz} GHz")
        self.ax.set_xlabel("Length (inches)")
        self.ax.set_ylabel("Loss (dB)")
        self.ax.grid(True, ls=":", lw=0.5)
        self.canvas.draw_idle()


# ====================================================================
#  FIELD STRENGTH / UNITS
# ====================================================================

class FieldStrengthCard(CalcCard):
    def __init__(self):
        super().__init__("Field Strength: V/m ↔ dBµV/m ↔ W/m² ↔ dBm/m²", [
            Field("v_per_m",    "E", "V/m"),
            Field("uv_per_m",   "E", "µV/m"),
            Field("dbuv_per_m", "E", "dBµV/m"),
            Field("w_per_m2",   "Power density", "W/m²"),
            Field("uw_per_cm2", "Power density", "µW/cm²"),
            Field("dbm_per_m2", "Power density", "dBm/m²", is_output=True),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        try:
            if driver == "v_per_m":
                if x < 0: return {}
                E = x
            elif driver == "uv_per_m":
                if x < 0: return {}
                E = x * 1e-6
            elif driver == "dbuv_per_m":
                E = (10 ** (x / 20)) * 1e-6
            elif driver == "w_per_m2":
                if x < 0: return {}
                E = sqrt(x * ETA0)
            elif driver == "uw_per_cm2":
                if x < 0: return {}
                S = x * 1e-2  # 1 uW/cm2 = 0.01 W/m2
                E = sqrt(S * ETA0)
            else:
                return {}
        except (ValueError, OverflowError):
            return {}
        S = E * E / ETA0
        return {
            "v_per_m": E,
            "uv_per_m": E * 1e6,
            "dbuv_per_m": 20 * log10(E / 1e-6) if E > 0 else None,
            "w_per_m2": S,
            "uw_per_cm2": S * 100,
            "dbm_per_m2": 10 * log10(S * 1e3) if S > 0 else None,
        }


class LengthCard(CalcCard):
    def __init__(self):
        super().__init__("Length", [
            Field("m",   "meters", "m"),
            Field("cm",  "centimeters", "cm"),
            Field("mm",  "millimeters", "mm"),
            Field("um",  "micrometers", "µm"),
            Field("in_", "inches", "in"),
            Field("mil", "mils", "mil"),
            Field("ft",  "feet", "ft"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        m = x * {"m":1, "cm":1e-2, "mm":1e-3, "um":1e-6,
                 "in_":0.0254, "mil":0.0254e-3, "ft":0.3048}[driver]
        return {"m":m, "cm":m*100, "mm":m*1000, "um":m*1e6,
                "in_":m/0.0254, "mil":m/0.0254*1000, "ft":m/0.3048}


class TemperatureCard(CalcCard):
    def __init__(self):
        super().__init__("Temperature", [
            Field("k", "Kelvin", "K"),
            Field("c", "Celsius", "°C"),
            Field("f", "Fahrenheit", "°F"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None: return {}
        if driver == "k":   k = x
        elif driver == "c": k = x + 273.15
        elif driver == "f": k = (x - 32) * 5/9 + 273.15
        else: return {}
        return {"k": k, "c": k - 273.15, "f": (k - 273.15) * 9/5 + 32}


# ====================================================================
#  FUZZY FINDER DIALOG
# ====================================================================

def fuzzy_score(query, target):
    if not query: return 0
    q = query.lower(); t = target.lower()
    if q in t:
        return 1000 - t.index(q) - len(t) // 4
    i = 0; score = 0; last = -2
    for c in q:
        idx = t.find(c, i)
        if idx < 0: return -1
        if idx == last + 1: score += 6
        elif idx > 0 and not t[idx - 1].isalnum(): score += 4
        score += 2
        i = idx + 1; last = idx
    return score - len(t) // 8


class FinderWindow(QDialog):
    """Frameless floating fuzzy finder.  Shown ABOVE the main window and
    magnetically attached to its top edge: when the main window moves or
    resizes, the finder follows.

    Live preview: as the user navigates the list, the main window switches
    to the tab containing the field and highlights it in bright green.
    Esc reverts the tab and removes the highlight; Enter or double-click
    keeps the tab and focuses the field for typing.
    """
    HIGHLIGHT_COLOR = QColor(120, 255, 120)
    MAX_H           = 250

    def __init__(self, parent_main):
        super().__init__(parent_main)
        self.parent_main = parent_main
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setMaximumHeight(self.MAX_H)
        self.setStyleSheet(
            "FinderWindow { background:#f0f0f0; border:1px solid #888; }")

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)

        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Type to filter   ↑↓ navigate   Enter jump   Esc cancel")
        self.input.setMinimumHeight(30)
        self.input.setFocusPolicy(Qt.StrongFocus)
        v.addWidget(self.input)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        # NoFocus on the list means a mouse-click selects an item but does
        # NOT steal keyboard focus — the input stays focused so typed text
        # always lands in it, and ↑↓ arrows always reach the input's
        # event filter (which forwards them to the list).
        self.list.setFocusPolicy(Qt.NoFocus)
        v.addWidget(self.list, 1)

        self.input.textChanged.connect(self._filter)
        self.input.installEventFilter(self)
        self.list.currentRowChanged.connect(self._on_row_changed)
        self.list.itemClicked.connect(lambda _: None)  # ensure clicks land
        self.list.itemDoubleClicked.connect(lambda _: self._accept())

        self._search_index = []
        self._original_tab = None
        self._highlighted_edit = None
        self._original_palette = None
        # Track collapse state of the previewed card so we can revert it
        # if the user cancels (Esc) instead of accepting (Enter).
        self._highlighted_card = None
        self._was_collapsed = False
        # Filter mode: "fields" lists every field;  "groups" lists each
        # card once and a pick drops you into that card's first cell.
        self.mode = "fields"

    def show_above(self, search_index):
        self._search_index = search_index
        self._original_tab = self.parent_main.tabs.currentIndex()
        self.input.clear()
        self._filter("")
        self._reposition()
        self.show()
        self.raise_()
        # On Windows, frameless Qt.Tool windows don't always receive
        # keyboard focus on show(); explicitly activate this window first
        # *then* focus the input.
        self.activateWindow()
        self.input.setFocus(Qt.OtherFocusReason)
        self.input.selectAll()

    def _reposition(self):
        if not self.parent_main:
            return
        m = self.parent_main.frameGeometry()
        my_w = m.width()
        my_h = min(self.MAX_H, max(self.height(), self.MAX_H))
        my_x = m.x()
        my_y = m.y() - my_h - 2
        if my_y < 0:
            my_y = 0
        self.setGeometry(my_x, my_y, my_w, my_h)

    def _filter(self, q):
        self.list.blockSignals(True)
        self.list.clear()
        scored = []
        if self.mode == "groups":
            # one entry per card; the target edit is the card's first field
            seen = set()
            for label, edit, card in self._search_index:
                if id(card) in seen:
                    continue
                seen.add(id(card))
                tab = label.split("  →  ")[0] if "  →  " in label else ""
                group_label = f"{tab}  →  {card.title()}" if tab else card.title()
                s = fuzzy_score(q, group_label)
                if s >= 0:
                    # CalcCards expose a `fields` dict — drop into the first
                    # field's edit.  Special tabs (ResistorTab, SmithChartTab)
                    # don't, so we use the edit supplied by their
                    # search_entries() — which is already a usable target.
                    if isinstance(card, CalcCard):
                        first_edit = next(iter(card.fields.values())).edit
                    else:
                        first_edit = edit
                    scored.append((s, group_label, first_edit, card))
        else:
            for label, edit, card in self._search_index:
                s = fuzzy_score(q, label)
                if s >= 0:
                    scored.append((s, label, edit, card))
        scored.sort(key=lambda x: -x[0])
        for s, label, edit, card in scored[:300]:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, (edit, card))
            self.list.addItem(it)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._unhighlight()

    def _on_row_changed(self, row):
        if row < 0:
            self._unhighlight()
            return
        item = self.list.item(row)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        edit, card = data
        self._unhighlight()
        self.parent_main._jump_to_card_only(card)
        self._highlight(edit, card)

    def _highlight(self, edit, card):
        # `edit` may be None for tab-only search hits.  In that case we
        # have nothing to recolour — just remember the card so the
        # collapse state can still be previewed.
        self._highlighted_edit = edit
        if edit is not None:
            self._original_palette = QPalette(edit.palette())
            pal = QPalette(self._original_palette)
            pal.setColor(QPalette.Base, self.HIGHLIGHT_COLOR)
            edit.setPalette(pal)
        else:
            self._original_palette = None
        # Remember whether the card was collapsed; expand it for preview.
        self._highlighted_card = card
        self._was_collapsed = bool(getattr(card, "_collapsed", False))
        if self._was_collapsed:
            card.set_collapsed(False)

    def _unhighlight(self, revert_collapse=True):
        if self._highlighted_edit and self._original_palette:
            self._highlighted_edit.setPalette(self._original_palette)
        if (revert_collapse and self._highlighted_card is not None
                and self._was_collapsed):
            self._highlighted_card.set_collapsed(True)
        self._highlighted_edit = None
        self._original_palette = None
        self._highlighted_card = None
        self._was_collapsed = False

    def _accept(self):
        item = self.list.currentItem()
        if not item:
            return self._cancel()
        data = item.data(Qt.UserRole)
        if not data:
            return self._cancel()
        edit, _card = data
        # Tabs that index sub-items (e.g. the ICs part list) select the
        # picked one; everything else just takes focus below.
        act = getattr(_card, "activate_search_entry", None)
        if act is not None:
            try:
                act(item.text())
            except Exception:
                pass
        # Keep the card open if we just expanded it for preview.
        self._unhighlight(revert_collapse=False)
        self.hide()
        # `edit` is the focus target.  It may be None (for tab-only
        # entries where the tab has no obvious main input), and even
        # when set it might be a QComboBox which lacks selectAll().
        # Skip silently in either case — the tab-jump already happened.
        if edit is not None:
            QTimer.singleShot(
                0,
                lambda e=edit: (
                    e.setFocus() if hasattr(e, "setFocus") else None,
                    e.selectAll() if hasattr(e, "selectAll") else None,
                ),
            )

    def _cancel(self):
        # Revert the previewed card's collapse state and the original tab.
        self._unhighlight(revert_collapse=True)
        if self._original_tab is not None:
            self.parent_main.tabs.setCurrentIndex(self._original_tab)
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                self.list.keyPressEvent(ev)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._accept()
                return True
            if k == Qt.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, ev)

    def closeEvent(self, ev):
        self._cancel()
        super().closeEvent(ev)


# ====================================================================
#  GENERAL SCIENCE / PHYSICS  (compact single-row cards)
# ====================================================================

class OhmsLawCard(CompactCard):
    """V = I·R    P = V·I"""
    def __init__(self):
        super().__init__("Ohm's law", [
            Field("v", "V", "V"),
            Field("i", "I", "A"),
            Field("r", "R", "Ω"),
            Field("p", "P", "W", is_output=True),
        ])

    def compute(self, driver, v):
        V, I, R = v.get("v"), v.get("i"), v.get("r")
        if driver == "v" and V is not None:
            if R is not None and R != 0:   I = V / R
            elif I is not None and I != 0: R = V / I
        elif driver == "i" and I is not None:
            if R is not None:              V = I * R
            elif V is not None and I != 0: R = V / I
        elif driver == "r" and R is not None:
            if I is not None:              V = I * R
            elif V is not None and R != 0: I = V / R
        out = {}
        if V is not None: out["v"] = V
        if I is not None: out["i"] = I
        if R is not None: out["r"] = R
        if V is not None and I is not None:
            out["p"] = V * I
        return out


class RCTimeCard(CompactCard):
    """τ = R·C    fc = 1/(2π·R·C)"""
    def __init__(self):
        super().__init__("RC time constant", [
            Field("r",   "R",  "Ω"),
            Field("c",   "C",  "F"),
            Field("tau", "τ",  "s"),
            Field("fc",  "fc", "Hz"),
        ])

    def compute(self, driver, v):
        R, C, tau, fc = v.get("r"), v.get("c"), v.get("tau"), v.get("fc")
        if driver == "tau" and tau is not None and tau > 0:
            if R is not None and R > 0:   C = tau / R
            elif C is not None and C > 0: R = tau / C
        elif driver == "fc" and fc is not None and fc > 0:
            rc = 1 / (2 * pi * fc)
            if R is not None and R > 0:   C = rc / R
            elif C is not None and C > 0: R = rc / C
        if R is not None and C is not None and R > 0 and C > 0:
            tau = R * C
            fc  = 1 / (2 * pi * tau)
        out = {}
        if R   is not None: out["r"]   = R
        if C   is not None: out["c"]   = C
        if tau is not None: out["tau"] = tau
        if fc  is not None: out["fc"]  = fc
        return out


class LCResonanceCard(CompactCard):
    """fres = 1/(2π√(L·C))"""
    def __init__(self):
        super().__init__("LC resonance", [
            Field("l", "L",    "H"),
            Field("c", "C",    "F"),
            Field("f", "fres", "Hz"),
        ])

    def compute(self, driver, v):
        L, C, f = v.get("l"), v.get("c"), v.get("f")
        if driver == "f" and f is not None and f > 0:
            w = 2 * pi * f
            if L is not None and L > 0:   C = 1 / (L * w * w)
            elif C is not None and C > 0: L = 1 / (C * w * w)
        if L is not None and C is not None and L > 0 and C > 0:
            f = 1 / (2 * pi * sqrt(L * C))
        out = {}
        if L is not None: out["l"] = L
        if C is not None: out["c"] = C
        if f is not None: out["f"] = f
        return out


class PhotonEnergyCard(CompactCard):
    """E = h·f = h·c/λ"""
    def __init__(self):
        super().__init__("Photon  E = hf = hc/λ", [
            Field("f",    "f", "Hz"),
            Field("lam",  "λ", "m"),
            Field("e_j",  "E", "J"),
            Field("e_ev", "E", "eV"),
        ])

    def compute(self, driver, v):
        f = v.get("f"); lam = v.get("lam"); E_J = v.get("e_j"); E_eV = v.get("e_ev")
        if driver == "f" and f is not None and f > 0:
            E_J = H_PLANCK * f; lam = C_LIGHT / f
        elif driver == "lam" and lam is not None and lam > 0:
            f = C_LIGHT / lam;   E_J = H_PLANCK * f
        elif driver == "e_j" and E_J is not None and E_J > 0:
            f = E_J / H_PLANCK;  lam = C_LIGHT / f
        elif driver == "e_ev" and E_eV is not None and E_eV > 0:
            E_J = E_eV * EV_TO_J; f = E_J / H_PLANCK; lam = C_LIGHT / f
        if E_J is not None: E_eV = E_J / EV_TO_J
        out = {}
        if f    is not None: out["f"]    = f
        if lam  is not None: out["lam"]  = lam
        if E_J  is not None: out["e_j"]  = E_J
        if E_eV is not None: out["e_ev"] = E_eV
        return out


class WaveSpeedCard(CompactCard):
    """v = f·λ"""
    def __init__(self):
        super().__init__("Wave speed  v = fλ", [
            Field("v",   "v", "m/s"),
            Field("f",   "f", "Hz"),
            Field("lam", "λ", "m"),
        ])

    def compute(self, driver, v):
        vel = v.get("v"); f = v.get("f"); lam = v.get("lam")
        if driver == "v" and vel is not None and vel > 0:
            if f   is not None and f   > 0: lam = vel / f
            elif lam is not None and lam > 0: f = vel / lam
        elif driver == "f" and f is not None and f > 0:
            if vel is not None and vel > 0: lam = vel / f
            elif lam is not None and lam > 0: vel = f * lam
        elif driver == "lam" and lam is not None and lam > 0:
            if vel is not None and vel > 0: f = vel / lam
            elif f is not None and f > 0: vel = f * lam
        if f is not None and lam is not None and f > 0 and lam > 0:
            vel = f * lam
        out = {}
        if vel is not None: out["v"]   = vel
        if f   is not None: out["f"]   = f
        if lam is not None: out["lam"] = lam
        return out


class MassEnergyCard(CompactCard):
    """E = m·c²"""
    def __init__(self):
        super().__init__("Mass-energy  E = mc²", [
            Field("m",     "m", "kg"),
            Field("e_j",   "E", "J"),
            Field("e_mev", "E", "MeV"),
        ])

    def compute(self, driver, v):
        m = v.get("m"); E_J = v.get("e_j"); E_MeV = v.get("e_mev")
        c2 = C_LIGHT * C_LIGHT
        if driver == "m" and m is not None:
            E_J = m * c2
        elif driver == "e_j" and E_J is not None:
            m = E_J / c2
        elif driver == "e_mev" and E_MeV is not None:
            E_J = E_MeV * 1e6 * EV_TO_J
            m = E_J / c2
        if E_J is not None:
            E_MeV = E_J / (1e6 * EV_TO_J)
        out = {}
        if m     is not None: out["m"]     = m
        if E_J   is not None: out["e_j"]   = E_J
        if E_MeV is not None: out["e_mev"] = E_MeV
        return out


class KineticEnergyCard(CompactCard):
    """KE = ½·m·v²"""
    def __init__(self):
        super().__init__("Kinetic energy  KE = ½mv²", [
            Field("m",  "m",  "kg"),
            Field("v",  "v",  "m/s"),
            Field("ke", "KE", "J"),
        ])

    def compute(self, driver, v):
        m = v.get("m"); vel = v.get("v"); ke = v.get("ke")
        if driver == "ke" and ke is not None and ke >= 0:
            if m is not None and m > 0:
                vel = sqrt(2 * ke / m)
            elif vel is not None and vel > 0:
                m = 2 * ke / (vel * vel)
        if m is not None and vel is not None and m >= 0:
            ke = 0.5 * m * vel * vel
        out = {}
        if m   is not None: out["m"]  = m
        if vel is not None: out["v"]  = vel
        if ke  is not None: out["ke"] = ke
        return out


class IdealGasCard(CompactCard):
    """P·V = n·R·T   (R = 8.314 J/mol·K)"""
    def __init__(self):
        super().__init__("Ideal gas  PV = nRT", [
            Field("p", "P", "Pa"),
            Field("v", "V", "m³"),
            Field("n", "n", "mol"),
            Field("t", "T", "K"),
        ])

    def compute(self, driver, v):
        P = v.get("p"); V = v.get("v"); n = v.get("n"); T = v.get("t")
        if driver != "p" and V is not None and n is not None and T is not None and V > 0:
            P = n * R_GAS * T / V
        elif driver != "v" and P is not None and n is not None and T is not None and P > 0:
            V = n * R_GAS * T / P
        elif driver != "n" and P is not None and V is not None and T is not None and T > 0:
            n = P * V / (R_GAS * T)
        elif driver != "t" and P is not None and V is not None and n is not None and n > 0:
            T = P * V / (n * R_GAS)
        out = {}
        if P is not None: out["p"] = P
        if V is not None: out["v"] = V
        if n is not None: out["n"] = n
        if T is not None: out["t"] = T
        return out


class LensEqnCard(CompactCard):
    """1/f = 1/u + 1/v   M = -v/u"""
    def __init__(self):
        super().__init__("Thin lens  1/f = 1/u + 1/v", [
            Field("u", "u", "m"),
            Field("v", "v", "m"),
            Field("f", "f", "m"),
            Field("m", "M", "",  is_output=True),
        ])

    def compute(self, driver, v):
        u = v.get("u"); vd = v.get("v"); f = v.get("f")
        try:
            if u is not None and vd is not None and (driver in ("u", "v") or f is None):
                f = 1 / (1 / u + 1 / vd)
            elif u is not None and f is not None and (driver in ("u", "f") or vd is None):
                vd = 1 / (1 / f - 1 / u)
            elif vd is not None and f is not None and (driver in ("v", "f") or u is None):
                u = 1 / (1 / f - 1 / vd)
        except (ZeroDivisionError, ValueError):
            pass
        M = (-vd / u) if (u is not None and vd is not None and u != 0) else None
        out = {}
        if u  is not None: out["u"] = u
        if vd is not None: out["v"] = vd
        if f  is not None: out["f"] = f
        if M  is not None: out["m"] = M
        return out


class SnellsLawCard(CompactCard):
    """n₁·sin θ₁ = n₂·sin θ₂"""
    def __init__(self):
        super().__init__("Snell's law  n₁sinθ₁ = n₂sinθ₂", [
            Field("n1", "n₁", ""),
            Field("a1", "θ₁", "deg"),
            Field("n2", "n₂", ""),
            Field("a2", "θ₂", "deg"),
        ])

    def compute(self, driver, v):
        n1 = v.get("n1"); a1 = v.get("a1"); n2 = v.get("n2"); a2 = v.get("a2")
        try:
            if driver == "a1" and a1 is not None and n1 is not None and n2 is not None and n2 != 0:
                s = (n1 / n2) * math.sin(math.radians(a1))
                if -1 <= s <= 1: a2 = math.degrees(math.asin(s))
            elif driver == "a2" and a2 is not None and n1 is not None and n2 is not None and n1 != 0:
                s = (n2 / n1) * math.sin(math.radians(a2))
                if -1 <= s <= 1: a1 = math.degrees(math.asin(s))
            elif driver == "n2" and a1 is not None and a2 is not None and n1 is not None:
                sa2 = math.sin(math.radians(a2))
                if sa2 != 0: n2 = n1 * math.sin(math.radians(a1)) / sa2
            elif driver == "n1" and a1 is not None and a2 is not None and n2 is not None:
                sa1 = math.sin(math.radians(a1))
                if sa1 != 0: n1 = n2 * math.sin(math.radians(a2)) / sa1
        except (ValueError, OverflowError):
            pass
        out = {}
        if n1 is not None: out["n1"] = n1
        if a1 is not None: out["a1"] = a1
        if n2 is not None: out["n2"] = n2
        if a2 is not None: out["a2"] = a2
        return out


class PendulumCard(CompactCard):
    """T = 2π·√(L/g)"""
    def __init__(self):
        super().__init__("Pendulum  T = 2π√(L/g)", [
            Field("l", "L", "m"),
            Field("t", "T", "s"),
            Field("g", "g", "m/s²"),
        ])

    def compute(self, driver, v):
        L = v.get("l"); T = v.get("t"); g = v.get("g")
        if g is None or g <= 0: g = G_EARTH
        if driver == "t" and T is not None and T > 0:
            L = g * (T / (2 * pi)) ** 2
        elif driver == "l" and L is not None and L > 0:
            T = 2 * pi * sqrt(L / g)
        elif driver == "g" and L is not None and L > 0:
            T = 2 * pi * sqrt(L / g)
        if L is not None and L > 0 and T is None:
            T = 2 * pi * sqrt(L / g)
        out = {"g": g}
        if L is not None: out["l"] = L
        if T is not None: out["t"] = T
        return out


class QuadraticCard(CompactCard):
    """ax² + bx + c = 0   →   x = (-b ± √Δ) / 2a"""
    def __init__(self):
        super().__init__("Quadratic  ax² + bx + c = 0", [
            Field("a",  "a",  ""),
            Field("b",  "b",  ""),
            Field("c",  "c",  ""),
            Field("d",  "Δ",  "",  is_output=True),
            Field("x1", "x₁", "", is_output=True),
            Field("x2", "x₂", "", is_output=True),
        ])

    def compute(self, driver, v):
        a, b, c = v.get("a"), v.get("b"), v.get("c")
        if a is None or b is None or c is None or a == 0:
            return {}
        disc = b * b - 4 * a * c
        out = {"d": disc}
        if disc >= 0:
            sq = sqrt(disc)
            out["x1"] = (-b + sq) / (2 * a)
            out["x2"] = (-b - sq) / (2 * a)
        else:
            out["x1"] = None
            out["x2"] = None
        return out


class DopplerCard(CompactCard):
    """f' = f · (c + v_obs) / (c + v_src)   (sign convention: + toward)"""
    def __init__(self):
        super().__init__("Doppler  f' = f·(c+v_obs)/(c+v_src)", [
            Field("f",   "f",     "Hz"),
            Field("v_o", "v_obs", "m/s"),
            Field("v_s", "v_src", "m/s"),
            Field("c",   "c",     "m/s"),
            Field("fp",  "f'",    "Hz", is_output=True),
        ])

    def compute(self, driver, v):
        f = v.get("f"); vo = v.get("v_o") or 0; vs = v.get("v_s") or 0; c = v.get("c")
        if c is None or c <= 0:
            c = C_LIGHT  # default to speed of light; user can switch to 343 for sound
        if f is None: return {"c": c}
        denom = c + vs
        if denom == 0: return {"c": c}
        fp = f * (c + vo) / denom
        return {"c": c, "fp": fp}


class CoulombCard(CompactCard):
    """F = k·q₁·q₂ / r²    (k = 8.988e9 N·m²/C²)"""
    K_E = 8.9875517873681764e9
    def __init__(self):
        super().__init__("Coulomb  F = kq₁q₂/r²", [
            Field("q1", "q₁", "C"),
            Field("q2", "q₂", "C"),
            Field("r",  "r",  "m"),
            Field("f",  "F",  "N",  is_output=True),
        ])

    def compute(self, driver, v):
        q1 = v.get("q1"); q2 = v.get("q2"); r = v.get("r")
        if None in (q1, q2, r) or r == 0: return {}
        F = self.K_E * q1 * q2 / (r * r)
        return {"f": F}


# ====================================================================
#  ADDITIONAL RF CALCULATORS
# ====================================================================

class AttenuatorPadCard(CalcCard):
    """Matched-impedance Pi and T resistive attenuator pads.

    For a given attenuation A (dB) and characteristic impedance Z₀:
      N = 10^(A/10)            (linear power ratio)
      a = 10^(A/20) = √N       (linear voltage ratio)

    Pi  pad:  R_series = Z₀·(N−1)/(2·a)         R_shunt = Z₀·(a+1)/(a−1)
    Tee pad:  R_series = Z₀·(a−1)/(a+1)         R_shunt = Z₀·(2·a)/(N−1)
    """
    def __init__(self):
        super().__init__("Pi / T resistive attenuator (matched)", [
            Field("a_db", "Attenuation",      "dB"),
            Field("z0",   "Z₀",               "Ω"),
            Field("pi_rs", "Pi  R_series",    "Ω", is_output=True),
            Field("pi_rp", "Pi  R_shunt",     "Ω", is_output=True),
            Field("t_rs",  "Tee R_series",    "Ω", is_output=True),
            Field("t_rp",  "Tee R_shunt",     "Ω", is_output=True),
        ])

    def make_diagram(self):
        return AttenuatorPadDiagram()

    def compute(self, driver, v):
        a_db = v.get("a_db"); z0 = v.get("z0")
        if a_db is None or z0 is None: return {}
        if a_db <= 0 or z0 <= 0: return {}
        try:
            N = 10 ** (a_db / 10.0)
            a = 10 ** (a_db / 20.0)
            if abs(a - 1) < 1e-12 or abs(N - 1) < 1e-12:
                return {}
            pi_rs = z0 * (N - 1) / (2 * a)
            pi_rp = z0 * (a + 1) / (a - 1)
            t_rs  = z0 * (a - 1) / (a + 1)
            t_rp  = z0 * (2 * a) / (N - 1)
        except (OverflowError, ZeroDivisionError):
            return {}
        return {"pi_rs": pi_rs, "pi_rp": pi_rp, "t_rs": t_rs, "t_rp": t_rp}


class CapacitorReactanceCard(CalcCard):
    """Capacitor reactance and impedance magnitude at a given frequency.
    X_C = 1/(2π·f·C),   |Z| = √(R²+X_C²),   Q = X_C/R."""
    def __init__(self):
        super().__init__("Capacitor reactance  X_C = 1/(2π f C)", [
            Field("f_mhz", "Frequency",        "MHz"),
            Field("c_pf",  "Capacitance",      "pF"),
            Field("r_esr", "ESR (optional)",   "Ω"),
            Field("xc",    "|X_C|",            "Ω", is_output=True),
            Field("z_mag", "|Z| (R + jX_C)",   "Ω", is_output=True),
            Field("q",     "Q = X_C/R",        "",  is_output=True),
        ])

    def make_diagram(self):
        return _CapReactanceDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); c = v.get("c_pf"); r = v.get("r_esr")
        if f is None or c is None or f <= 0 or c <= 0: return {}
        try:
            xc = 1.0 / (2 * pi * (f * 1e6) * (c * 1e-12))
        except (OverflowError, ZeroDivisionError):
            return {}
        out = {"xc": xc}
        if r is not None and r > 0:
            out["z_mag"] = sqrt(r * r + xc * xc)
            out["q"]     = xc / r
        return out


class InductorReactanceCard(CalcCard):
    """Inductor reactance and impedance magnitude at a given frequency.
    X_L = 2π·f·L,   |Z| = √(R²+X_L²),   Q = X_L/R."""
    def __init__(self):
        super().__init__("Inductor reactance  X_L = 2π f L", [
            Field("f_mhz", "Frequency",        "MHz"),
            Field("l_nh",  "Inductance",       "nH"),
            Field("r_dc",  "R_DC (optional)",  "Ω"),
            Field("xl",    "|X_L|",            "Ω", is_output=True),
            Field("z_mag", "|Z| (R + jX_L)",   "Ω", is_output=True),
            Field("q",     "Q = X_L/R",        "",  is_output=True),
        ])

    def make_diagram(self):
        return _IndReactanceDiagram()

    def compute(self, driver, v):
        f = v.get("f_mhz"); L = v.get("l_nh"); r = v.get("r_dc")
        if f is None or L is None or f <= 0 or L <= 0: return {}
        try:
            xl = 2 * pi * (f * 1e6) * (L * 1e-9)
        except OverflowError:
            return {}
        out = {"xl": xl}
        if r is not None and r > 0:
            out["z_mag"] = sqrt(r * r + xl * xl)
            out["q"]     = xl / r
        return out


class RLCComboCard(CalcCard):
    """Series and parallel R-L-C combinations at frequency f.

      Series:    Z_s = R + j(X_L − X_C)
      Parallel:  Y_p = 1/R + 1/(jX_L) + jωC,  Z_p = 1/Y_p
      Resonance: f_r = 1 / (2π√(LC))
    """
    def __init__(self):
        super().__init__("R-L-C series & parallel impedance", [
            Field("r_ohm", "R",                "Ω"),
            Field("l_uh",  "L",                "µH"),
            Field("c_pf",  "C",                "pF"),
            Field("f_mhz", "Frequency",        "MHz"),
            Field("zs_mag",   "|Z_series|",     "Ω",  is_output=True),
            Field("zs_phase", "∠Z_series",      "°",  is_output=True),
            Field("zp_mag",   "|Z_parallel|",   "Ω",  is_output=True),
            Field("zp_phase", "∠Z_parallel",    "°",  is_output=True),
            Field("fr_mhz",   "f_resonance",    "MHz", is_output=True),
        ])

    def make_diagram(self):
        return _RLCComboDiagram()

    def compute(self, driver, v):
        R   = v.get("r_ohm")
        L   = v.get("l_uh");   L = L * 1e-6 if L is not None else None
        C   = v.get("c_pf");   C = C * 1e-12 if C is not None else None
        fmh = v.get("f_mhz");  f = fmh * 1e6 if fmh is not None else None
        out = {}
        if L is not None and C is not None and L > 0 and C > 0:
            out["fr_mhz"] = 1.0 / (2 * pi * sqrt(L * C)) / 1e6
        if f is None or f <= 0: return out
        try:
            xl = 2 * pi * f * L if L is not None else 0.0
            xc = 1.0 / (2 * pi * f * C) if C is not None and C > 0 else 0.0
        except (OverflowError, ZeroDivisionError):
            return out
        # Series
        if R is not None or L is not None or C is not None:
            zs = complex(R or 0.0, xl - xc)
            out["zs_mag"]   = abs(zs)
            out["zs_phase"] = math.degrees(math.atan2(zs.imag, zs.real))
        # Parallel — admittance sum
        try:
            yp = 0j
            if R is not None and R > 0: yp += complex(1.0 / R, 0)
            if L is not None and xl > 0: yp += complex(0, -1.0 / xl)
            if C is not None and xc > 0: yp += complex(0,  1.0 / xc)
            if yp != 0:
                zp = 1.0 / yp
                out["zp_mag"]   = abs(zp)
                out["zp_phase"] = math.degrees(math.atan2(zp.imag, zp.real))
        except ZeroDivisionError:
            pass
        return out


class DirectionalCouplerCard(CalcCard):
    """Directional coupler power flow.  Conventions:
       coupling factor C  = P_in − P_coupled        (always positive dB)
       directivity   D    = P_coupled − P_isolated  (always positive dB)
       isolation         = C + D
       mainline (insertion) loss = 10·log10(1 / (1 − 10^(−C/10))) plus
       small-element loss; we report the ideal coupling-only mainline loss."""
    def __init__(self):
        super().__init__("Directional coupler", [
            Field("pin",   "Input  P₁",         "dBm"),
            Field("c_db",  "Coupling factor C", "dB"),
            Field("d_db",  "Directivity D",     "dB"),
            Field("p_thru", "Through P₂",       "dBm", is_output=True),
            Field("p_cpl",  "Coupled P₃",       "dBm", is_output=True),
            Field("p_iso",  "Isolated P₄",      "dBm", is_output=True),
            Field("iso_db", "Isolation (C+D)",  "dB",  is_output=True),
            Field("ml_db",  "Mainline loss",    "dB",  is_output=True),
        ])

    def make_diagram(self):
        return _DirCouplerDiagram()

    def compute(self, driver, v):
        pin = v.get("pin"); c = v.get("c_db"); d = v.get("d_db")
        if pin is None or c is None or c <= 0: return {}
        try:
            ml = -10.0 * log10(1.0 - 10 ** (-c / 10.0))
        except (ValueError, OverflowError):
            return {}
        out = {
            "p_thru": pin - ml,
            "p_cpl":  pin - c,
            "ml_db":  ml,
        }
        if d is not None and d >= 0:
            out["p_iso"] = pin - c - d
            out["iso_db"] = c + d
        return out


class DeltaWyeCard(CalcCard):
    """Δ ↔ Y resistor-network transformation.

    Δ → Y:  R₁ = (R_b·R_c)/(R_a+R_b+R_c),  cyclic for R₂, R₃.
    Y → Δ:  R_a = (R₁R₂+R₂R₃+R₃R₁)/R₁,    cyclic.

    Type any value into the network you have; the other network re-computes."""
    def __init__(self):
        super().__init__("Δ ↔ Y resistor transform", [
            Field("ra", "Δ  R_a",  "Ω"),
            Field("rb", "Δ  R_b",  "Ω"),
            Field("rc", "Δ  R_c",  "Ω"),
            Field("r1", "Y  R₁",   "Ω"),
            Field("r2", "Y  R₂",   "Ω"),
            Field("r3", "Y  R₃",   "Ω"),
        ])

    def make_diagram(self):
        return _DeltaWyeDiagram()

    def compute(self, driver, v):
        ra = v.get("ra"); rb = v.get("rb"); rc = v.get("rc")
        r1 = v.get("r1"); r2 = v.get("r2"); r3 = v.get("r3")
        # Driver in Δ-side → recompute Y
        if driver in ("ra", "rb", "rc"):
            if None in (ra, rb, rc): return {}
            s = ra + rb + rc
            if s <= 0: return {}
            return {"r1": rb * rc / s,
                    "r2": ra * rc / s,
                    "r3": ra * rb / s}
        # Driver in Y-side → recompute Δ
        if driver in ("r1", "r2", "r3"):
            if None in (r1, r2, r3) or r1 == 0 or r2 == 0 or r3 == 0:
                return {}
            num = r1 * r2 + r2 * r3 + r3 * r1
            return {"ra": num / r1,
                    "rb": num / r2,
                    "rc": num / r3}
        return {}


class NearFarFieldCard(CalcCard):
    """Antenna field-region boundaries based on max aperture dimension D
    and free-space wavelength λ:

      Reactive near-field   r < 0.62·√(D³/λ)
      Radiating near-field  0.62·√(D³/λ) ≤ r < 2D²/λ
      Far field (Fraunhofer) r ≥ 2D²/λ
    """
    def __init__(self):
        super().__init__("Antenna near / far-field boundaries", [
            Field("f_mhz",  "Frequency",            "MHz"),
            Field("d_m",    "Max dimension D",      "m"),
            Field("lambda", "λ",                    "m",  is_output=True),
            Field("r_react", "Reactive boundary",   "m",  is_output=True),
            Field("r_far",   "Far-field boundary",  "m",  is_output=True),
        ])

    def compute(self, driver, v):
        f = v.get("f_mhz"); D = v.get("d_m")
        if f is None or f <= 0: return {}
        lam = C_LIGHT / (f * 1e6)
        out = {"lambda": lam}
        if D is not None and D > 0:
            out["r_react"] = 0.62 * sqrt(D ** 3 / lam)
            out["r_far"]   = 2.0 * D * D / lam
        return out


class RadarRangeCard(CalcCard):
    """Straightforward radar link budget with explicit Tx/Rx architecture.

      P_r,in = P_t - L_tx + G_t + G_r - L_rx
               + 10log10(σ) + 20log10(λ) - 30log10(4π) - 40log10(R)

    Leave exactly one of {P_t, G_t, G_r, σ, R, f, P_r} blank; the card
    solves it from the others. Tx/Rx losses default to 0 dB when blank.
    Noise-floor outputs use receiver input power, bandwidth, and NF."""
    def __init__(self):
        super().__init__("Radar equation + simple Tx/Rx architecture", [
            Field("pt_dbm",  "Tx output power",       "dBm"),
            Field("tx_loss", "Tx feed / switch loss", "dB"),
            Field("gt_dbi",  "Tx antenna gain",       "dBi"),
            Field("gr_dbi",  "Rx antenna gain",       "dBi"),
            Field("rx_loss", "Rx front-end loss",     "dB"),
            Field("rcs",     "Target RCS  σ",         "m²"),
            Field("range_m", "Range R",               "m"),
            Field("f_mhz",   "Frequency",             "MHz"),
            Field("pr_dbm",  "Rx input power",        "dBm"),
            Field("bw_hz",   "Receiver noise BW",     "Hz"),
            Field("nf_db",   "Receiver NF",           "dB"),
            Field("rx_gain", "Receiver gain",         "dB"),
            Field("snr_req", "Required SNR",          "dB"),
            Field("eirp_dbm", "EIRP",                 "dBm", is_output=True),
            Field("pr_ant_dbm", "Power at Rx antenna", "dBm", is_output=True),
            Field("pout_dbm", "Rx chain output",      "dBm", is_output=True),
            Field("noise_dbm", "Noise floor + NF",    "dBm", is_output=True),
            Field("snr_db",  "SNR at Rx input",       "dB",  is_output=True),
            Field("margin_db", "SNR margin",          "dB",  is_output=True),
            Field("lam",     "λ",                     "m",   is_output=True),
            Field("path_db", "Tx output to Rx input loss", "dB", is_output=True),
        ])

    def compute(self, driver, v):
        pt = v.get("pt_dbm")
        gt = v.get("gt_dbi", v.get("gt"))
        gr = v.get("gr_dbi")
        if gr is None and "gr_dbi" not in v:
            gr = v.get("gt") if "gt" in v else gt
        rcs = v.get("rcs")
        R = v.get("range_m"); f = v.get("f_mhz"); pr = v.get("pr_dbm")
        tx_loss = v.get("tx_loss") or 0.0
        rx_loss = v.get("rx_loss") or 0.0
        bw = v.get("bw_hz")
        nf = v.get("nf_db") or 0.0
        rx_gain = v.get("rx_gain") or 0.0
        snr_req = v.get("snr_req")
        out = {}

        if f is not None and f > 0:
            out["lam"] = C_LIGHT / (f * 1e6)

        K = 30.0 * log10(4.0 * pi)   # ≈ 32.98 dB
        main = {"pt_dbm": pt, "gt_dbi": gt, "gr_dbi": gr, "rcs": rcs,
                "range_m": R, "f_mhz": f, "pr_dbm": pr}
        # Domain guards: σ, R, f, BW must be strictly positive when known.
        bad = ((rcs is not None and rcs <= 0) or
               (R   is not None and R   <= 0) or
               (f   is not None and f   <= 0) or
               (bw  is not None and bw  <= 0))
        missing = [k for k, val in main.items() if val is None]

        if not bad and len(missing) <= 1:
            # Pick which variable to solve for: the blank one, or if all
            # seven are filled, recompute Pr unless the user is driving Pr
            # (in which case solve for R, the most natural reverse).
            if len(missing) == 1:
                unknown = missing[0]
            else:
                unknown = "range_m" if driver == "pr_dbm" else "pr_dbm"

            try:
                if unknown == "pr_dbm":
                    lam = C_LIGHT / (f * 1e6)
                    out["pr_dbm"] = (pt - tx_loss + gt + gr - rx_loss
                                     + 10*log10(rcs) + 20*log10(lam)
                                     - K - 40*log10(R))
                elif unknown == "pt_dbm":
                    lam = C_LIGHT / (f * 1e6)
                    out["pt_dbm"] = (pr + tx_loss - gt - gr + rx_loss
                                     - 10*log10(rcs) - 20*log10(lam)
                                     + K + 40*log10(R))
                elif unknown == "gt_dbi":
                    lam = C_LIGHT / (f * 1e6)
                    out["gt_dbi"] = (pr - pt + tx_loss - gr + rx_loss
                                     - 10*log10(rcs) - 20*log10(lam)
                                     + K + 40*log10(R))
                elif unknown == "gr_dbi":
                    lam = C_LIGHT / (f * 1e6)
                    out["gr_dbi"] = (pr - pt + tx_loss - gt + rx_loss
                                     - 10*log10(rcs) - 20*log10(lam)
                                     + K + 40*log10(R))
                elif unknown == "rcs":
                    lam = C_LIGHT / (f * 1e6)
                    exp = (pr - pt + tx_loss - gt - gr + rx_loss
                           - 20*log10(lam) + K + 40*log10(R)) / 10.0
                    out["rcs"] = 10 ** exp
                elif unknown == "range_m":
                    lam = C_LIGHT / (f * 1e6)
                    exp = (pt - tx_loss + gt + gr - rx_loss
                           + 10*log10(rcs) + 20*log10(lam) - K - pr) / 40.0
                    out["range_m"] = 10 ** exp
                elif unknown == "f_mhz":
                    exp = (pr - pt + tx_loss - gt - gr + rx_loss
                           - 10*log10(rcs) + K + 40*log10(R)) / 20.0
                    lam_new = 10 ** exp
                    out["f_mhz"] = (C_LIGHT / lam_new) / 1e6
                    out["lam"] = lam_new
            except (ValueError, OverflowError, ZeroDivisionError):
                pass

        pt_f = out.get("pt_dbm", pt)
        gt_f = out.get("gt_dbi", gt)
        pr_f = out.get("pr_dbm", pr)
        if pt_f is not None and gt_f is not None:
            out["eirp_dbm"] = pt_f - tx_loss + gt_f
        if pr_f is not None:
            out["pr_ant_dbm"] = pr_f + rx_loss
            out["pout_dbm"] = pr_f + rx_gain
        if pt_f is not None and pr_f is not None:
            out["path_db"] = pt_f - pr_f
        if bw is not None and bw > 0:
            noise = -174.0 + 10.0 * log10(bw) + nf
            out["noise_dbm"] = noise
            if pr_f is not None:
                snr = pr_f - noise
                out["snr_db"] = snr
                if snr_req is not None:
                    out["margin_db"] = snr - snr_req
        return out


class PowerFactorCard(CalcCard):
    """Single-phase AC power triangle.

      Real     P = V·I·cos(φ)
      Reactive Q = V·I·sin(φ)
      Apparent S = V·I
      PF = cos(φ) = P/S
    """
    _diagram_above = True
    def __init__(self):
        super().__init__("Power factor / power triangle", [
            Field("v_rms", "V_rms",         "V"),
            Field("i_rms", "I_rms",         "A"),
            Field("phi",   "Phase φ",       "°"),
            Field("pf",    "Power factor",  "",   is_output=True),
            Field("p_w",   "Real power P",  "W",  is_output=True),
            Field("q_var", "Reactive Q",    "VAr",is_output=True),
            Field("s_va",  "Apparent S",    "VA", is_output=True),
        ])

    def make_diagram(self):
        return PowerTriangleDiagram()

    def compute(self, driver, v):
        V = v.get("v_rms"); I = v.get("i_rms"); phi = v.get("phi")
        if None in (V, I, phi) or V < 0 or I < 0: return {}
        rad = math.radians(phi)
        S = V * I
        return {
            "s_va":  S,
            "p_w":   S * math.cos(rad),
            "q_var": S * math.sin(rad),
            "pf":    math.cos(rad),
        }


class PropagationTimeCard(CalcCard):
    """Propagation time and electrical length over a distance through a
    medium with relative permittivity ε_r.

      v_p = c / √ε_r
      t   = d / v_p
      λ   = v_p / f
      n   = d / λ        (number of wavelengths along the path)
    """
    def __init__(self):
        super().__init__("Propagation time / electrical length", [
            Field("d_m",    "Distance",          "m"),
            Field("eps_r",  "ε_r",               ""),
            Field("f_mhz",  "Frequency",         "MHz"),
            Field("vp",     "v_p",               "m/s",  is_output=True),
            Field("t_ns",   "Propagation time",  "ns",   is_output=True),
            Field("lam",    "λ",                 "m",    is_output=True),
            Field("n_lam",  "# wavelengths",     "",     is_output=True),
        ])

    def compute(self, driver, v):
        d = v.get("d_m"); eps = v.get("eps_r"); f = v.get("f_mhz")
        if eps is None or eps <= 0: return {}
        vp = C_LIGHT / sqrt(eps)
        out = {"vp": vp}
        if d is not None and d > 0:
            out["t_ns"] = (d / vp) * 1e9
        if f is not None and f > 0:
            lam = vp / (f * 1e6)
            out["lam"] = lam
            if d is not None and d > 0:
                out["n_lam"] = d / lam
        return out


class ViaFenceIsolationCard(CalcCard):
    """Approximate isolation of a single-row PCB via fence used as a
    parallel-plate cavity sidewall or stripline shield.

    The dominant leakage path is the *air gap* between adjacent vias,
    not the centre-to-centre spacing, so the formula uses
    g = s − d (the actual conducting-cylinder gap):

        λ_g = c / (f · √ε_r)             (guided wavelength)
        Iso ≈ 20 · log10(λ_g / 2g)  dB

    Rule of thumb the formula encodes (for g = s − d):
        g = λ_g / 10  → ≈ 14 dB
        g = λ_g / 20  → ≈ 20 dB
        g = λ_g / 63  → ≈ 30 dB

    Treat as a coarse single-row upper bound — denser arrays, blind /
    buried vias, stacked rows, and stitching to a continuous plane all
    push isolation higher.  Formula clamps to 0 dB once s ≥ λ_g/2 (the
    first leaky-mode resonance — fence stops acting like a wall).
    """
    def __init__(self):
        super().__init__("Via fence isolation (PCB shielding)", [
            Field("f_mhz", "Frequency",            "MHz"),
            Field("eps_r", "ε_r (substrate)",      ""),
            Field("d_mm",  "Via drill ∅",          "mm"),
            Field("s_mm",  "Via spacing (ctr-ctr)", "mm"),
            Field("n_rows","Rows N",                ""),
            Field("lam",   "λ in substrate",       "mm", is_output=True),
            Field("gap",   "Gap (s − d)",          "mm", is_output=True),
            Field("iso_row","Iso per row",         "dB", is_output=True),
            Field("iso",   "Total isolation",      "dB", is_output=True),
            Field("s30",   "s for 30 dB target (1 row)", "mm",
                  is_output=True),
        ])
        # Sensible defaults: FR-4 substrate, 0.3 mm through-via drill, 1 row
        self.fields["eps_r"].edit.setText("4.2")
        self.fields["d_mm"].edit.setText("0.3")
        self.fields["n_rows"].edit.setText("1")

    def compute(self, driver, v):
        f_mhz = v.get("f_mhz")
        eps_r = v.get("eps_r")
        d_mm  = v.get("d_mm")
        s_mm  = v.get("s_mm")
        n_rows = v.get("n_rows")
        if n_rows is None or n_rows < 1:
            n_rows = 1
        n_int = max(1, int(round(n_rows)))
        if f_mhz is None or f_mhz <= 0 or eps_r is None or eps_r <= 0:
            return {}
        # Guided wavelength in mm
        lam_mm = (C_LIGHT / (f_mhz * 1e6 * sqrt(eps_r))) * 1000.0
        # 30 dB target gap: 20·log10(λ / 2g) = 30  →  g = λ / (2·10^1.5)
        gap30 = lam_mm / (2.0 * 10 ** 1.5)
        # Add the via diameter back in to get the spacing recommendation.
        s30 = gap30 + (d_mm if (d_mm is not None and d_mm > 0) else 0.0)
        out = {"lam": lam_mm, "s30": s30}
        if s_mm is None or s_mm <= 0:
            return out
        d_val = d_mm if (d_mm is not None and d_mm > 0) else 0.0
        gap = s_mm - d_val
        if gap <= 0:
            # Via diameter ≥ spacing — physically impossible, vias overlap.
            return {**out, "gap": gap}
        out["gap"] = gap
        # Always evaluate the formula and clamp negatives. The previous
        # version short-circuited to 0 dB once s ≥ λ_g/2 which made the
        # output look stuck at zero — the formula already produces a
        # non-positive result there (20·log10(λ/2g) ≤ 0), so the explicit
        # gate was redundant.
        iso_one_row = max(0.0, 20.0 * log10(lam_mm / (2.0 * gap)))
        out["iso_row"] = iso_one_row
        # Linear stacking — each additional row roughly multiplies the
        # per-row isolation in dB. Coarse approximation: works for N≤4
        # rows of staggered vias; beyond that coupling between rows
        # diminishes the return per added row.
        out["iso"] = iso_one_row * n_int
        return out


class RadarBlindSpeedCard(CalcCard):
    """Pulse-Doppler radar radial blind speeds.

      v_n = n · λ · PRF / 2     (m/s)

    First five blind speeds reported."""
    def __init__(self):
        super().__init__("Radar blind speeds  v_n = n·λ·PRF/2", [
            Field("f_mhz", "Frequency",        "MHz"),
            Field("prf",   "PRF",              "Hz"),
            Field("v1",    "1st blind speed",  "m/s",  is_output=True),
            Field("v2",    "2nd",              "m/s",  is_output=True),
            Field("v3",    "3rd",              "m/s",  is_output=True),
            Field("v4",    "4th",              "m/s",  is_output=True),
            Field("v5",    "5th",              "m/s",  is_output=True),
        ])

    def compute(self, driver, v):
        f = v.get("f_mhz"); prf = v.get("prf")
        if None in (f, prf) or f <= 0 or prf <= 0: return {}
        lam = C_LIGHT / (f * 1e6)
        v1 = lam * prf / 2.0
        return {"v1": v1, "v2": 2*v1, "v3": 3*v1, "v4": 4*v1, "v5": 5*v1}


class RectangularCavityCard(CalcCard):
    """TE_mnp / TM_mnp resonant frequency of a rectangular cavity:

      f_mnp = (c / 2√(μ_r·ε_r)) · √((m/a)² + (n/b)² + (p/c)²)

    (m, n, p are the mode integers; one of them may be zero, but two
    cannot both be zero.)  Cavity dimensions are entered in the global
    `default_length_unit` set in Options."""

    DIM_FIELDS = ("a_m", "b_m", "c_m")

    def __init__(self):
        self._len_unit = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "m"
        super().__init__("Rectangular cavity resonance", [
            Field("a_m",   "a",      self._len_unit),
            Field("b_m",   "b",      self._len_unit),
            Field("c_m",   "c",      self._len_unit),
            Field("m",     "m",      ""),
            Field("n",     "n",      ""),
            Field("p",     "p",      ""),
            Field("eps_r", "ε_r",    ""),
            Field("mu_r",  "μ_r",    ""),
            Field("f_mhz", "f_mnp",  "MHz", is_output=True),
        ])
        self._sync_dim_unit_labels()

    def _sync_dim_unit_labels(self):
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None:
                continue
            f.unit = self._len_unit
            f.declared_unit = self._len_unit   # keep in sync; compute() does its own m-conversion
            if f.unit_label is not None:
                f.unit_label.setText(self._len_unit)

    def apply_global_length_unit(self):
        new_unit = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "m"
        self._cascade_length_unit(new_unit)

    def _switch_field_unit(self, field, new_unit):
        if field is not None and field.name in self.DIM_FIELDS \
                and new_unit in VALID_LENGTH_UNITS:
            self._cascade_length_unit(new_unit)
            return
        super()._switch_field_unit(field, new_unit)

    def _cascade_length_unit(self, new_unit):
        if new_unit not in VALID_LENGTH_UNITS or new_unit == self._len_unit:
            self._sync_dim_unit_labels()
            return
        old_to_m = LENGTH_TO_MM[self._len_unit] / 1000.0
        new_to_m = LENGTH_TO_MM[new_unit]      / 1000.0
        scale = old_to_m / new_to_m
        self._len_unit = new_unit
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None or f.edit is None:
                continue
            v = parse(f.edit.text())
            if v is not None:
                f.edit.blockSignals(True)
                f.edit.setText(fmt(v * scale))
                f.edit.blockSignals(False)
        self._sync_dim_unit_labels()
        self.recompute_from_inputs()

    def make_diagram(self):
        return CavityDiagram()

    def compute(self, driver, v):
        a = v.get("a_m"); b = v.get("b_m"); cc = v.get("c_m")
        m = v.get("m");   n = v.get("n");   p  = v.get("p")
        eps = v.get("eps_r") or 1.0
        mu  = v.get("mu_r")  or 1.0
        if None in (a, b, cc, m, n, p): return {}
        if a <= 0 or b <= 0 or cc <= 0 or eps <= 0 or mu <= 0: return {}
        # Convert displayed dimensions (in self._len_unit) to metres.
        to_m = LENGTH_TO_MM[self._len_unit] / 1000.0
        a *= to_m; b *= to_m; cc *= to_m
        terms = 0.0
        if m: terms += (m / a) ** 2
        if n: terms += (n / b) ** 2
        if p: terms += (p / cc) ** 2
        if terms <= 0: return {}
        f = (C_LIGHT / (2.0 * sqrt(mu * eps))) * sqrt(terms)
        return {"f_mhz": f / 1e6}

    # No per-card persistence is needed — the unit is taken from the
    # global default_length_unit setting on each launch.


class CavityModesTable(QWidget):
    """Compact lowest-N cavity-modes list.  Two columns: mode label
    (f_mnp with subscript indices) and resonant frequency.  Used by
    PCBShieldModesCard as its `make_diagram()` widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        cap = QLabel("Lowest cavity modes")
        cap.setStyleSheet("color:#555; font-weight:bold;")
        outer.addWidget(cap)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Mode", "f"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(16)
        self.table.verticalHeader().setMinimumSectionSize(16)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        # Project-wide convention: no zebra striping on data grids.
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumWidth(200)
        # Tall enough to show ~20 mode rows + header without scrolling
        # when stacked below the field grid.
        self.table.setMinimumHeight(340)
        outer.addWidget(self.table)

    def set_modes(self, rows):
        """rows: iterable of (label, f_hz).  First row is highlighted as
        the dominant mode."""
        rows = list(rows)
        self.table.setRowCount(len(rows))
        for i, (label, f_hz) in enumerate(rows):
            mode_it = QTableWidgetItem(label)
            mode_it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, mode_it)
            f_it = QTableWidgetItem(_fmt_band_freq(f_hz))
            f_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 1, f_it)
            if i == 0:
                # Dominant — paint with the same light-yellow used for
                # active-input fields so the eye lands on it first.
                for c in range(2):
                    self.table.item(i, c).setBackground(FIELD_BG_INPUT_FOCUS)


_SUBSCRIPT_DIGITS = "₀₁₂₃₄₅₆₇₈₉"


def _mnp_subscript(m, n, p):
    return "".join(_SUBSCRIPT_DIGITS[d] for d in (m, n, p))


class PCBShieldModesCard(CalcCard):
    """Lowest cavity-resonance frequencies for a rectangular PCB shield.

    The shield is treated as a closed metal box (the PCB ground plane is
    the bottom wall; the soldered shield supplies the other five).
    Internal radiators — vias, traces, connector launches — can excite
    any of the cavity's TE_mnp / TM_mnp eigenmodes, so the user just
    wants to know which resonances live closest to the band of
    interest.  The card enumerates (m, n, p) with at most one zero, ranks
    them by f_mnp, and shows the lowest rows in a side-table.

      f_mnp = (c / 2√(μ_r·ε_r)) · √((m/a)² + (n/b)² + (p/c)²)

    The dominant (lowest-f) mode is highlighted."""

    DIM_FIELDS = ("a_m", "b_m", "c_m")
    N_MODES = 20          # number of rows shown in the table below the fields
    MAX_INDEX = 4         # max value of m, n, p in the enumeration
    _diagram_below = True
    _diagram_full_width = True

    def __init__(self):
        self._len_unit = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "m"
        super().__init__("PCB-shield cavity modes (lowest f)", [
            Field("a_m",   "a (width)",  self._len_unit),
            Field("b_m",   "b (height)", self._len_unit),
            Field("c_m",   "c (depth)",  self._len_unit),
            Field("eps_r", "ε_r",        ""),
            Field("mu_r",  "μ_r",        ""),
        ])
        self._sync_dim_unit_labels()
        # The cavity inside a soldered PCB shield is air; the substrate
        # FR-4 sits *below* the ground plane, not inside the cavity, so
        # ε_r should normally stay at 1.  Show that as the default text
        # and explain the assumption in a tooltip — users were typing
        # the substrate's 4.4 here and getting nonsensical mode numbers.
        eps_edit = self.fields["eps_r"].edit
        mu_edit  = self.fields["mu_r"].edit
        eps_edit.setPlaceholderText("1 (air)")
        mu_edit.setPlaceholderText("1")
        air_tip = (
            "ε_r of whatever fills the cavity volume.  "
            "A typical PCB shield encloses air → leave at 1.  "
            "Only change if the cavity is potted / filled with absorber "
            "or encapsulant; the PCB substrate sits below the ground "
            "plane and does NOT enter this calculation.")
        eps_edit.setToolTip(air_tip)
        mu_edit.setToolTip(
            "μ_r of whatever fills the cavity volume — leave at 1 "
            "unless the fill is ferromagnetic.")

    # Identical length-unit cascade plumbing as RectangularCavityCard —
    # the two cards share the global default-length-unit + click-to-pick
    # behaviour so a/b/c always render in the same unit across the tab.
    def _sync_dim_unit_labels(self):
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None:
                continue
            f.unit = self._len_unit
            f.declared_unit = self._len_unit
            if f.unit_label is not None:
                f.unit_label.setText(self._len_unit)

    def apply_global_length_unit(self):
        new_unit = DEFAULT_LENGTH_UNIT if DEFAULT_LENGTH_UNIT in VALID_LENGTH_UNITS else "m"
        self._cascade_length_unit(new_unit)

    def _switch_field_unit(self, field, new_unit):
        if field is not None and field.name in self.DIM_FIELDS \
                and new_unit in VALID_LENGTH_UNITS:
            self._cascade_length_unit(new_unit)
            return
        super()._switch_field_unit(field, new_unit)

    def _cascade_length_unit(self, new_unit):
        if new_unit not in VALID_LENGTH_UNITS or new_unit == self._len_unit:
            self._sync_dim_unit_labels()
            return
        old_to_m = LENGTH_TO_MM[self._len_unit] / 1000.0
        new_to_m = LENGTH_TO_MM[new_unit]      / 1000.0
        scale = old_to_m / new_to_m
        self._len_unit = new_unit
        for fname in self.DIM_FIELDS:
            f = self.fields.get(fname)
            if f is None or f.edit is None:
                continue
            v = parse(f.edit.text())
            if v is not None:
                f.edit.blockSignals(True)
                f.edit.setText(fmt(v * scale))
                f.edit.blockSignals(False)
        self._sync_dim_unit_labels()
        self.recompute_from_inputs()

    def make_diagram(self):
        self._modes_table = CavityModesTable()
        return self._modes_table

    def compute(self, driver, v):
        a = v.get("a_m"); b = v.get("b_m"); cc = v.get("c_m")
        eps = v.get("eps_r") or 1.0
        mu  = v.get("mu_r")  or 1.0
        # Push results into the side-table (it lives next to the field
        # grid via make_diagram).  No output fields, so we always return
        # an empty dict — the parent _on_edit() exits early and that's OK.
        if (None in (a, b, cc) or a <= 0 or b <= 0 or cc <= 0
                or eps <= 0 or mu <= 0):
            if hasattr(self, "_modes_table"):
                self._modes_table.set_modes([])
            return {}
        to_m = LENGTH_TO_MM[self._len_unit] / 1000.0
        a_m, b_m, c_m = a * to_m, b * to_m, cc * to_m
        scale = C_LIGHT / (2.0 * sqrt(mu * eps))
        modes = []
        N = self.MAX_INDEX
        for m in range(N + 1):
            for nn in range(N + 1):
                for p in range(N + 1):
                    # At most one of (m, n, p) may be zero — two zeros
                    # would mean field variation in only one axis, which
                    # can't satisfy the perpendicular-wall boundary
                    # conditions.
                    zeros = (m == 0) + (nn == 0) + (p == 0)
                    if zeros >= 2:
                        continue
                    f = scale * sqrt((m / a_m) ** 2
                                     + (nn / b_m) ** 2
                                     + (p / c_m) ** 2)
                    modes.append((f, m, nn, p))
        modes.sort()
        rows = []
        for f, m, nn, p in modes[:self.N_MODES]:
            rows.append((f"f{_mnp_subscript(m, nn, p)}", f))
        if hasattr(self, "_modes_table"):
            self._modes_table.set_modes(rows)
        return {}


class VoltageDividerCard(CalcCard):
    """Resistive divider, with optional load.

      Loaded output:   V_out = V_in · (R₂‖R_L) / (R₁ + R₂‖R_L)
      Unloaded:        V_out = V_in · R₂ / (R₁ + R₂)

    The card is bidirectional — type into V_out and the card solves for
    R₁ given (V_in, R₂[, R_L]); type into V_in / R₁ / R₂ and V_out
    follows.  Useful when sizing the top-side resistor against a fixed
    rail and bottom resistor."""

    OPT_MODES = [("Current", "current"),
                 ("Max impedance", "maxz"),
                 ("Min impedance", "minz")]

    def __init__(self):
        self._opt_combo = None          # built in make_extras during super()
        super().__init__("Resistive voltage divider (loaded or unloaded)", [
            Field("vin",  "V_in",         "V"),
            Field("r1",   "R₁ (top)",     "Ω"),
            Field("r2",   "R₂ (bottom)",  "Ω"),
            Field("rload","R_load",       "Ω"),
            Field("vout", "V_out",        "V"),    # bidirectional
            Field("ratio","Divide by",    ""),     # bidirectional
            Field("itot", "I_total",      "mA"),   # target in Current mode
            Field("ptot", "P_total",      "mW", is_output=True),
            Field("r1_eia",  "R₁ closest E96", "Ω", is_output=True),
            Field("r2_eia",  "R₂ closest E96", "Ω", is_output=True),
            Field("vout_eia","V_out with E96", "V", is_output=True),
        ])

    def make_diagram(self):
        return VoltageDividerDiagram()

    def make_extras(self):
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Optimize for:"))
        cb = QComboBox()
        for label, _key in self.OPT_MODES:
            cb.addItem(label)
        cb.setMaximumHeight(20); cb.setMinimumWidth(120)
        cb.currentIndexChanged.connect(lambda *_: self.recompute_from_inputs())
        self._opt_combo = cb
        h.addWidget(cb); h.addStretch(1)
        return w

    def _opt_mode(self):
        cb = self._opt_combo
        return self.OPT_MODES[cb.currentIndex()][1] if cb is not None else "maxz"

    @staticmethod
    def _r2eff(r2, rl):
        if r2 is None or r2 < 0:
            return None
        if rl is not None and rl > 0:
            return r2 * rl / (r2 + rl)
        return r2

    def _eia_block(self, vin, r1, r2, rl):
        """Snap R₁ and R₂ to the closest E96 stock values and report
        the V_out that pair would actually produce.  Helper so both the
        forward and inverse paths can pick this up."""
        if r1 is None or r2 is None or r1 <= 0 or r2 <= 0:
            return {}
        r1_eia = _closest_eia(r1, EIA_E96)
        r2_eia = _closest_eia(r2, EIA_E96)
        out = {}
        if r1_eia is not None:
            out["r1_eia"] = r1_eia
        if r2_eia is not None:
            out["r2_eia"] = r2_eia
        if (vin is not None and vin > 0
                and r1_eia is not None and r2_eia is not None):
            r2e_eia = self._r2eff(r2_eia, rl)
            denom = r1_eia + r2e_eia if r2e_eia is not None else None
            if denom and denom > 0:
                out["vout_eia"] = vin * r2e_eia / denom
        return out

    _SEARCH_DECADES = range(2, 6)   # 100 Ω … ~1 MΩ for the optimal-pair search

    def _search_optimal_e96(self, vin, vout, rl, mode="maxz", i_ma=None):
        """Best (R₁, R₂) E96 pair for V_out across decades 100 Ω–1 MΩ.
        Pairs are bucketed into 0.1 % accuracy bands, then ranked by the
        chosen objective: nearest to a target divider current, or the
        highest / lowest series impedance."""
        ratio_r = (vin - vout) / vout    # R₁ / R₂  ideal
        r_total_target = None
        if mode == "current" and i_ma:
            r_total_target = vin / (i_ma * 1e-3)
        best = None
        for d in self._SEARCH_DECADES:
            scale = 10 ** d
            for v2 in EIA_E96:
                R2 = v2 * scale
                # Size R1 against the *loaded* bottom leg (R2‖R_L) — using
                # bare R2 here made every candidate miss the target whenever
                # R_load was small enough to matter.
                r2e = self._r2eff(R2, rl)
                if r2e is None or r2e <= 0:
                    continue
                R1 = _closest_eia(r2e * ratio_r, EIA_E96)
                if R1 is None or R1 <= 0:
                    continue
                v_actual = vin * r2e / (R1 + r2e)
                err = abs(v_actual - vout) / vout
                if r_total_target is not None:
                    obj = abs((R1 + R2) - r_total_target)
                elif mode == "minz":
                    obj = R1 + R2
                else:                       # maxz — lowest current draw
                    obj = -(R1 + R2)
                key = (round(err * 1000), obj, err)
                if best is None or key < best[0]:
                    best = (key, R1, R2, v_actual)
        return best

    def compute(self, driver, v):
        out = self._compute(driver, v) or {}
        vin  = out.get("vin",  v.get("vin"))
        vout = out.get("vout", v.get("vout"))
        if vin is not None and vout:
            out["ratio"] = vin / vout
        return out

    def _compute(self, driver, v):
        vin = v.get("vin"); r1 = v.get("r1"); r2 = v.get("r2")
        rl  = v.get("rload"); vout = v.get("vout")
        ratio = v.get("ratio")

        # "Divide by N" drives V_out when the user didn't type one — or
        # outright when the ratio / current target is what they edited.
        if vin is not None and ratio and ratio > 0 and (
                vout is None or driver in ("ratio", "itot")):
            vout = vin / ratio
            r1 = r2 = None

        # ---- Optimal E96-pair search:  user supplied V_in + V_out
        # only, no R₁/R₂. Pick the best stock pair. ----
        if (driver in (None, "vin", "vout", "ratio", "itot")
                and vin is not None and vout is not None
                and r1 is None and r2 is None
                and vin > 0 and 0 < vout < vin):
            best = self._search_optimal_e96(vin, vout, rl, self._opt_mode(),
                                            v.get("itot"))
            if best is not None:
                _, R1, R2, v_actual = best
                r2e = self._r2eff(R2, rl) or R2
                itot_a = vin / (R1 + r2e)
                return {
                    "r1":       R1,
                    "r2":       R2,
                    "r1_eia":   R1,
                    "r2_eia":   R2,
                    "vout":     v_actual,
                    "vout_eia": v_actual,
                    "itot":     itot_a * 1e3,
                    "ptot":     vin * itot_a * 1e3,
                }

        # ---- Inverse mode: user typed V_out → solve for R₁ ----
        if driver == "vout":
            if (vin is not None and r2 is not None and vout is not None
                    and vin > 0 and r2 > 0 and 0 < vout < vin):
                r2e = self._r2eff(r2, rl)
                if r2e is None or r2e <= 0:
                    return {}
                r1_calc = r2e * (vin / vout - 1)
                if r1_calc < 0:
                    return {}
                denom = r1_calc + r2e
                if denom <= 0:
                    return {}
                itot_a = vin / denom
                out = {
                    "r1":   r1_calc,
                    "itot": itot_a * 1e3,
                    "ptot": vin * itot_a * 1e3,
                }
                out.update(self._eia_block(vin, r1_calc, r2, rl))
                return out
            return {}
        # ---- Forward mode: V_out from R₁, R₂ ----
        if None in (vin, r1, r2) or r1 < 0 or r2 < 0:
            return {}
        r2e = self._r2eff(r2, rl)
        if r2e is None:
            return {}
        denom = r1 + r2e
        if denom <= 0:
            return {}
        vout_calc = vin * r2e / denom
        itot_a = vin / denom
        out = {
            "vout": vout_calc,
            "itot": itot_a * 1e3,
            "ptot": vin * itot_a * 1e3,
        }
        out.update(self._eia_block(vin, r1, r2, rl))
        return out


# --------------------------------------------------------------------
# EIA standard-resistor series.  Each list is the per-decade base
# values; multiply by 10^k for any decade.  Values rounded to the EIA
# standard step ratios (E12: 10^(1/12), E24: 10^(1/24), …).
# --------------------------------------------------------------------
EIA_E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
EIA_E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
           3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
EIA_E48 = [1.00, 1.05, 1.10, 1.15, 1.21, 1.27, 1.33, 1.40, 1.47, 1.54,
           1.62, 1.69, 1.78, 1.87, 1.96, 2.05, 2.15, 2.26, 2.37, 2.49,
           2.61, 2.74, 2.87, 3.01, 3.16, 3.32, 3.48, 3.65, 3.83, 4.02,
           4.22, 4.42, 4.64, 4.87, 5.11, 5.36, 5.62, 5.90, 6.19, 6.49,
           6.81, 7.15, 7.50, 7.87, 8.25, 8.66, 9.09, 9.53]
EIA_E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24,
           1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
           1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00,
           2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
           2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24,
           3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
           4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
           5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
           6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
           8.66, 8.87, 9.09, 9.31, 9.53, 9.76]


# E192 generated from 10^(k/192) rounded to 3 sig figs — matches the
# IEC-60063 standard table to within 0.5% across the decade.  Generated
# once at module load so the 192 numbers stay out of the source.
def _gen_e192():
    out = []
    for k in range(192):
        v = 10 ** (k / 192.0)
        digits = 3 - int(floor(log10(v))) - 1
        out.append(round(v, digits))
    return out


EIA_E192 = _gen_e192()

EIA_SERIES = {"E12":  EIA_E12,  "E24": EIA_E24,
              "E48":  EIA_E48,  "E96": EIA_E96,
              "E192": EIA_E192}


def _closest_eia(value, series):
    """Closest EIA-series resistor value to `value`.  Searches every
    decade so a 7.5 kΩ target on E12 returns 6.8 kΩ instead of 8.2 Ω."""
    if value is None or value <= 0:
        return None
    decade = int(floor(log10(value)))
    candidates = []
    for k in (decade - 1, decade, decade + 1):
        scale = 10 ** k
        candidates.extend(b * scale for b in series)
    return min(candidates, key=lambda x: abs(log10(x / value)))


class OpAmpGainCard(CalcCard):
    """Op-amp gain stage.  Pick a topology, set the gain, and get an E96
    resistor pair; or enter the resistors and read the gain back."""

    _diagram_below = True

    TOPOS = [("Non-inverting", "noninv"),
             ("Inverting",     "inv")]
    OPT_MODES = [("Balanced (~10 kΩ)", "bal"),
                 ("Min impedance",     "minz"),
                 ("Max impedance",     "maxz")]

    def __init__(self):
        self._topo_combo = None
        self._opt_combo = None
        super().__init__("Op-amp gain (non-inverting / inverting)", [
            Field("gain",     "Gain",           "V/V"),
            Field("rf",       "Rf (feedback)",  "Ω"),
            Field("rg",       "Rg / Rin",       "Ω"),
            Field("gain_eia", "Gain (E96 pair)", "V/V", is_output=True),
        ])

    def make_diagram(self):
        return OpAmpDiagram(self)

    def make_extras(self):
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Topology:"))
        tc = QComboBox()
        for label, _k in self.TOPOS:
            tc.addItem(label)
        tc.setMaximumHeight(20); tc.setMinimumWidth(110)
        tc.currentIndexChanged.connect(
            lambda *_: self.recompute_from_inputs())
        self._topo_combo = tc
        h.addWidget(tc)
        h.addSpacing(8); h.addWidget(QLabel("Optimize for:"))
        oc = QComboBox()
        for label, _k in self.OPT_MODES:
            oc.addItem(label)
        oc.setMaximumHeight(20); oc.setMinimumWidth(120)
        oc.currentIndexChanged.connect(
            lambda *_: self.recompute_from_inputs())
        self._opt_combo = oc
        h.addWidget(oc); h.addStretch(1)
        return w

    def _topo(self):
        cb = self._topo_combo
        return self.TOPOS[cb.currentIndex()][1] if cb is not None else "noninv"

    def _opt(self):
        cb = self._opt_combo
        return self.OPT_MODES[cb.currentIndex()][1] if cb is not None else "bal"

    # Keep feedback resistors in the practical op-amp range: below ~1 kΩ
    # loads the output and wastes power; above ~1 MΩ bias current and noise
    # dominate.
    R_MIN, R_MAX = 1e3, 1e6

    @classmethod
    def _best_pair(cls, ratio, mode):
        """Best E96 (Rf, Rg) with Rf/Rg ≈ ratio, both within 1 kΩ–1 MΩ.
        Rank by gain error first, then the impedance objective.
        ratio 0 → Rf = 0 (unity buffer)."""
        if ratio is None or ratio < 0:
            return None
        lo, hi = cls.R_MIN, cls.R_MAX
        best = None
        for d in range(3, 7):                 # Rg base decades 1 kΩ … 1 MΩ
            scale = 10 ** d
            for base in EIA_E96:
                Rg = base * scale
                if not (lo <= Rg <= hi):
                    continue
                Rf = 0.0 if ratio == 0 else _closest_eia(Rg * ratio, EIA_E96)
                if Rf is None or (ratio > 0 and not (lo <= Rf <= hi)):
                    continue
                ract = Rf / Rg
                err = abs(ract - ratio) / max(ratio, 1e-9)
                if mode == "minz":
                    obj = Rf + Rg
                elif mode == "maxz":
                    obj = -(Rf + Rg)
                else:                          # balanced → Rg near 10 kΩ
                    obj = abs(Rg - 10e3)
                key = (round(err * 1e4), obj)
                if best is None or key < best[0]:
                    best = (key, Rf, Rg, ract)
        return None if best is None else (best[1], best[2], best[3])

    def compute(self, driver, v):
        topo = self._topo()
        gain = v.get("gain"); rf = v.get("rf"); rg = v.get("rg")

        # Forward: user typed the resistors → read the gain back.
        if driver in ("rf", "rg") and rf is not None and rg is not None and rg > 0:
            g = 1.0 + rf / rg if topo == "noninv" else -(rf / rg)
            return {"gain": g, "gain_eia": g}

        # Solve resistors from the requested gain.
        if gain is None:
            return {}
        if topo == "noninv":
            ratio = gain - 1.0
            if ratio < 0:                      # non-inverting gain < 1 impossible
                return {}
        else:
            ratio = abs(gain)
        pair = self._best_pair(ratio, self._opt())
        if pair is None:
            return {}
        Rf, Rg, ract = pair
        g_act = 1.0 + ract if topo == "noninv" else -ract
        out = {"rf": Rf, "rg": Rg, "gain_eia": g_act}
        return out


class EIANearestCard(CalcCard):
    """Round any resistor (or capacitor) value to the closest standard
    EIA-series stock value.  Returns the E12, E24, E48, and E96 hits
    plus the relative error of each so you can pick the tightest series
    you're willing to buy.

    Works with engineering suffixes — type 49.9, 4k99, 1.21M, etc."""

    def __init__(self):
        super().__init__("Closest EIA standard value", [
            Field("target",  "Target value",  "Ω"),
            Field("e12",     "E12 closest",   "Ω", is_output=True),
            Field("e12_err", "   error",      "%", is_output=True),
            Field("e24",     "E24 closest",   "Ω", is_output=True),
            Field("e24_err", "   error",      "%", is_output=True),
            Field("e48",     "E48 closest",   "Ω", is_output=True),
            Field("e48_err", "   error",      "%", is_output=True),
            Field("e96",     "E96 closest",   "Ω", is_output=True),
            Field("e96_err", "   error",      "%", is_output=True),
            Field("e192",    "E192 closest",  "Ω", is_output=True),
            Field("e192_err","   error",      "%", is_output=True),
        ])

    def compute(self, driver, v):
        t = v.get("target")
        if t is None or t <= 0:
            return {}
        out = {}
        for key, series in EIA_SERIES.items():
            pick = _closest_eia(t, series)
            out[key.lower()] = pick
            out[key.lower() + "_err"] = (pick / t - 1) * 100
        return out


class VoltageDropCard(CalcCard):
    """DC voltage drop along a length of round wire.

      d_AWG = 0.005·92^((36−AWG)/39)   inch  (NEC standard step ratio)
      A     = π·(d/2)²
      R     = ρ · L / A
      V     = I · R

    Default ρ is copper at 20 °C  (1.68×10⁻⁸ Ω·m)."""
    RHO_COPPER = 1.68e-8     # Ω·m
    def __init__(self):
        super().__init__("Wire voltage drop  V = I · ρL/A", [
            Field("awg",   "Wire gauge",       "AWG"),
            Field("len_m", "Length",           "m"),
            Field("i_a",   "Current",          "A"),
            Field("rho",   "Resistivity ρ",    "Ω·m"),
            Field("d_mm",  "Wire diameter",    "mm",  is_output=True),
            Field("r_ohm", "Total resistance", "Ω",   is_output=True),
            Field("vdrop", "Voltage drop",     "V",   is_output=True),
        ])
        # Match the Conductor combo, which starts on CONDUCTORS[0] (copper).
        self.fields["rho"].edit.setText(f"{CONDUCTORS[0][1]:g}")

    def make_diagram(self):
        return _VoltageDropDiagram()

    def make_extras(self):
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Conductor:"))
        cb = QComboBox()
        for name, _rho in CONDUCTORS:
            cb.addItem(name)
        cb.setMaximumHeight(20); cb.setMinimumWidth(110)
        cb.currentIndexChanged.connect(self._on_conductor_changed)
        self._cond_combo = cb
        h.addWidget(cb); h.addStretch(1)
        return w

    def _on_conductor_changed(self, idx):
        if not (0 <= idx < len(CONDUCTORS)):
            return
        f = self.fields["rho"]
        f.edit.blockSignals(True)
        f.edit.setText(f"{CONDUCTORS[idx][1]:g}")
        f.edit.blockSignals(False)
        self.recompute_from_inputs()

    def compute(self, driver, v):
        awg = v.get("awg"); L = v.get("len_m"); I = v.get("i_a")
        rho = v.get("rho")
        if rho is None or rho <= 0: rho = self.RHO_COPPER
        if awg is None: return {}
        # AWG → diameter (inch then mm)
        d_in = 0.005 * (92 ** ((36 - awg) / 39.0))
        d_m  = d_in * 0.0254
        out = {"d_mm": d_m * 1000}
        if L is not None and L > 0:
            A = pi * (d_m / 2.0) ** 2
            R = rho * L / A
            out["r_ohm"] = R
            if I is not None:
                out["vdrop"] = I * R
        return out


class ButterworthLP3Card(CalcCard):
    """3rd-order Butterworth low-pass ladder, series-input topology.

      Normalized prototype:  g₁ = 1.0,  g₂ = 2.0,  g₃ = 1.0
      Frequency- & impedance-scaled component values:
        L₁ = g₁·Z₀ / (2π·f_c)
        C₂ = g₂   / (2π·f_c·Z₀)
        L₃ = g₃·Z₀ / (2π·f_c)
    """
    def __init__(self):
        super().__init__("Butterworth low-pass, N=3 (series-input)", [
            Field("fc_mhz", "Cut-off f_c", "MHz"),
            Field("z0",     "Z₀",          "Ω"),
            Field("l1_nh",  "L₁",          "nH",  is_output=True),
            Field("c2_pf",  "C₂",          "pF",  is_output=True),
            Field("l3_nh",  "L₃",          "nH",  is_output=True),
        ])

    def make_diagram(self):
        return _ButterworthLadderDiagram("LP")

    def compute(self, driver, v):
        fc = v.get("fc_mhz"); z0 = v.get("z0")
        if None in (fc, z0) or fc <= 0 or z0 <= 0: return {}
        w = 2 * pi * fc * 1e6
        return {
            "l1_nh": (1.0 * z0 / w) * 1e9,
            "c2_pf": (2.0 / (w * z0)) * 1e12,
            "l3_nh": (1.0 * z0 / w) * 1e9,
        }


class ButterworthHP3Card(CalcCard):
    """3rd-order Butterworth high-pass ladder (LP→HP transformation:
    L → C and C → L scaled by 1/(ω_c²·g_k))."""
    def __init__(self):
        super().__init__("Butterworth high-pass, N=3 (series-input)", [
            Field("fc_mhz", "Cut-off f_c", "MHz"),
            Field("z0",     "Z₀",          "Ω"),
            Field("c1_pf",  "C₁",          "pF",  is_output=True),
            Field("l2_nh",  "L₂",          "nH",  is_output=True),
            Field("c3_pf",  "C₃",          "pF",  is_output=True),
        ])

    def make_diagram(self):
        return _ButterworthLadderDiagram("HP")

    def compute(self, driver, v):
        fc = v.get("fc_mhz"); z0 = v.get("z0")
        if None in (fc, z0) or fc <= 0 or z0 <= 0: return {}
        w = 2 * pi * fc * 1e6
        # LP → HP: L_lp → C_hp = 1/(ω_c²·L_lp)·... actually simpler form:
        # for normalized g_k:  C_hp_k = 1/(g_k·ω_c·Z₀),  L_hp_k = Z₀/(g_k·ω_c)
        return {
            "c1_pf": (1.0 / (1.0 * w * z0)) * 1e12,
            "l2_nh": (z0 / (2.0 * w)) * 1e9,
            "c3_pf": (1.0 / (1.0 * w * z0)) * 1e12,
        }


class SineVRMSCard(CompactCard):
    """Sine wave: V_rms = V_p/√2,  V_avg = 2V_p/π,  V_pp = 2V_p."""
    def __init__(self):
        super().__init__("Sine  V_p ↔ V_rms ↔ V_avg ↔ V_pp", [
            Field("vp",   "V_peak",  "V"),
            Field("vrms", "V_rms",   "V"),
            Field("vavg", "V_avg",   "V"),
            Field("vpp",  "V_pp",    "V"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None or x < 0: return {}
        if   driver == "vp":   vp = x
        elif driver == "vrms": vp = x * sqrt(2)
        elif driver == "vavg": vp = x * pi / 2.0
        elif driver == "vpp":  vp = x / 2.0
        else: return {}
        return {"vp": vp, "vrms": vp/sqrt(2), "vavg": 2*vp/pi, "vpp": 2*vp}


class SquareVRMSCard(CompactCard):
    """Square wave (50 % duty): V_rms = V_p,  V_avg = V_p (full-wave),
    V_pp = 2V_p."""
    def __init__(self):
        super().__init__("Square wave  V_p ↔ V_rms ↔ V_avg ↔ V_pp", [
            Field("vp",   "V_peak",  "V"),
            Field("vrms", "V_rms",   "V"),
            Field("vavg", "V_avg",   "V"),
            Field("vpp",  "V_pp",    "V"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None or x < 0: return {}
        if   driver == "vp" or driver == "vrms" or driver == "vavg": vp = x
        elif driver == "vpp": vp = x / 2.0
        else: return {}
        return {"vp": vp, "vrms": vp, "vavg": vp, "vpp": 2*vp}


class TriangleVRMSCard(CompactCard):
    """Triangle wave: V_rms = V_p/√3,  V_avg = V_p/2 (full-wave),
    V_pp = 2V_p."""
    def __init__(self):
        super().__init__("Triangle  V_p ↔ V_rms ↔ V_avg ↔ V_pp", [
            Field("vp",   "V_peak",  "V"),
            Field("vrms", "V_rms",   "V"),
            Field("vavg", "V_avg",   "V"),
            Field("vpp",  "V_pp",    "V"),
        ])

    def compute(self, driver, v):
        x = v.get(driver)
        if x is None or x < 0: return {}
        if   driver == "vp":   vp = x
        elif driver == "vrms": vp = x * sqrt(3)
        elif driver == "vavg": vp = x * 2.0
        elif driver == "vpp":  vp = x / 2.0
        else: return {}
        return {"vp": vp, "vrms": vp/sqrt(3), "vavg": vp/2, "vpp": 2*vp}


# --------------------------------------------------------------------
#  Standard rectangular waveguide table (EIA WR-series, public
#  dimensional standards).  Each row is:
#      (designation, inner_a_mm, inner_b_mm, recommended_lo_GHz, recommended_hi_GHz)
#  WR-N's "N" gives the broad inner wall in hundredths of an inch.
# --------------------------------------------------------------------
WAVEGUIDES = [
    ("WR-2300", 584.20, 292.10,  0.32,   0.49),
    ("WR-1800", 457.20, 228.60,  0.41,   0.62),
    ("WR-1500", 381.00, 190.50,  0.49,   0.75),
    ("WR-1150", 292.10, 146.05,  0.64,   0.96),
    ("WR-975",  247.65, 123.83,  0.75,   1.12),
    ("WR-770",  195.58,  97.79,  0.96,   1.45),
    ("WR-650",  165.10,  82.55,  1.12,   1.70),
    ("WR-510",  129.54,  64.77,  1.45,   2.20),
    ("WR-430",  109.22,  54.61,  1.70,   2.60),
    ("WR-340",   86.36,  43.18,  2.20,   3.30),
    ("WR-284",   72.136, 34.036, 2.60,   3.95),
    ("WR-229",   58.166, 29.083, 3.30,   4.90),
    ("WR-187",   47.549, 22.149, 3.95,   5.85),
    ("WR-159",   40.386, 20.193, 4.90,   7.05),
    ("WR-137",   34.849, 15.799, 5.85,   8.20),
    ("WR-112",   28.499, 12.624, 7.05,  10.00),
    ("WR-90",    22.860, 10.160, 8.20,  12.40),
    ("WR-75",    19.050,  9.525,10.00,  15.00),
    ("WR-62",    15.799,  7.899,12.40,  18.00),
    ("WR-51",    12.954,  6.477,15.00,  22.00),
    ("WR-42",    10.668,  4.318,18.00,  26.50),
    ("WR-34",     8.636,  4.318,22.00,  33.00),
    ("WR-28",     7.112,  3.556,26.50,  40.00),
    ("WR-22",     5.690,  2.845,33.00,  50.00),
    ("WR-19",     4.775,  2.388,40.00,  60.00),
    ("WR-15",     3.760,  1.880,50.00,  75.00),
    ("WR-12",     3.099,  1.549,60.00,  90.00),
    ("WR-10",     2.540,  1.270,75.00, 110.00),
    ("WR-8",      2.032,  1.016,90.00, 140.00),
    ("WR-6",      1.651,  0.826,110.0, 170.00),
    ("WR-5",      1.295,  0.648,140.0, 220.00),
    ("WR-4",      1.092,  0.546,170.0, 260.00),
    ("WR-3",      0.864,  0.432,220.0, 325.00),
]

# Air breakdown peak field at sea level (very approximate; real designs derate
# heavily — multipactor, pressurization, materials all matter).
E_BREAKDOWN_AIR = 3.0e6   # V/m peak


def waveguide_for_freq(f_ghz):
    """Return the row in WAVEGUIDES whose recommended band contains f_ghz,
    preferring the lowest-cutoff (largest) waveguide that still fits."""
    if f_ghz is None or f_ghz <= 0:
        return None
    for row in WAVEGUIDES:
        _, _, _, lo, hi = row
        if lo <= f_ghz <= hi:
            return row
    return None


class WaveguideCard(CalcCard):
    """Rectangular-waveguide TE₁₀ analyser — auto-pick a WR-series guide
    from your frequency, or override `a`/`b` for a custom cross-section.

    For a rectangular guide with inner dimensions a (broad), b (narrow),
    filled with a dielectric of relative permittivity ε_r (default 1 =
    air), every output below is reported for the current frequency f:

      Cutoff frequencies (general TE_mn / TM_mn):
        f_c(mn) = (c/√ε_r) / (2π) · √((mπ/a)² + (nπ/b)²)
        TE₁₀ is the dominant; the single-mode band runs f_c10 < f < f_c20.

      Free-space wavelength:     λ₀ = c / (f · √ε_r)
      Cutoff wavelength (TE₁₀):  λ_c = 2a
      Guide wavelength:          λ_g = λ₀ / √(1 − (f_c10/f)²)
      Wave impedance (TE₁₀):     Z = (η₀/√ε_r) / √(1 − (f_c10/f)²)
      Phase constant β = 2π/λ_g; phase velocity v_p = ω/β;
      group velocity v_g = c·√(1 − (f_c10/f)²);  delay t_d = 1/v_g.

      Conductor attenuation (Pozar 3.96, TE₁₀):
        R_s   = √(π·f·μ₀/σ)        — surface resistance
        α_c   = (R_s / (b·η·√(1−(f_c/f)²))) · (1 + (2b/a)·(f_c/f)²) Np/m
        α(dB/m) = α_c × 8.686

      Air breakdown V at sea level: V_bd ≈ E_bd · b
      CW power limit (peak, air):    P_max ≈ (a·b·E_bd²/(4·η)) · √(1 − (f_c/f)²)
    """

    # Conductivities at ~20 °C (annealed material, S/m).  Used by the
    # closed-form conductor-loss formula.
    CONDUCTORS = (
        ("Copper",   5.96e7),
        ("Silver",   6.30e7),
        ("Gold",     4.10e7),
        ("Aluminum", 3.50e7),
        ("Brass",    1.50e7),
    )

    def __init__(self):
        self._sigma = self.CONDUCTORS[0][1]
        self._cond_name = self.CONDUCTORS[0][0]
        self._cond_combo = None
        super().__init__("Rectangular waveguide  (TE₁₀ + every mode)", [
            Field("f_ghz",     "Frequency",                "GHz"),
            Field("a_mm",      "Inner a (override)",       "mm"),
            Field("b_mm",      "Inner b (override)",       "mm"),
            Field("eps_r",     "Fill ε_r",                 ""),
            Field("wr",        "WR designation",           "",       is_output=True),
            Field("range",     "Recommended band",         "GHz",    is_output=True),
            Field("fc10",      "f_c (TE₁₀ dominant)",      "GHz",    is_output=True),
            Field("fc20",      "f_c (TE₂₀ next)",          "GHz",    is_output=True),
            Field("fc01",      "f_c (TE₀₁)",               "GHz",    is_output=True),
            Field("single",    "Single-mode TE₁₀ band",    "GHz",    is_output=True),
            Field("lam0_mm",   "λ₀ (in-medium)",           "mm",     is_output=True),
            Field("lam_c_mm",  "λ_c (TE₁₀ = 2a)",          "mm",     is_output=True),
            Field("lam_g_mm",  "λ_g (guide)",              "mm",     is_output=True),
            Field("z_te10",    "Z_TE₁₀ wave impedance",    "Ω",      is_output=True),
            Field("beta",      "β phase constant",         "rad/m",  is_output=True),
            Field("vp_kms",    "v_p phase velocity",       "km/s",   is_output=True),
            Field("vg_kms",    "v_g group velocity",       "km/s",   is_output=True),
            Field("td_ns_m",   "t_d group delay = 1/v_g",  "ns/m",   is_output=True),
            Field("rs_mohm",   "R_s surface resistance",   "mΩ/sq",  is_output=True),
            Field("alpha_db_m","α_c conductor loss",       "dB/m",   is_output=True),
            Field("v_bd",      "V_breakdown (air, peak)",  "kV",     is_output=True),
            Field("p_max",     "P_max CW (air, peak)",     "kW",     is_output=True),
            Field("modes",     "Lowest 8 modes (GHz)",     "",       is_output=True),
        ])
        # Placeholder text for the optional override fields.
        self.fields["a_mm"].edit.setPlaceholderText("auto from WR")
        self.fields["b_mm"].edit.setPlaceholderText("auto from WR")
        self.fields["eps_r"].edit.setPlaceholderText("1 (air)")

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Conductor:"))
        cc = QComboBox()
        for name, _ in self.CONDUCTORS:
            cc.addItem(name)
        cc.setMaximumHeight(20); cc.setMinimumWidth(110)
        cc.currentTextChanged.connect(self._on_conductor_changed)
        self._cond_combo = cc
        h.addWidget(cc)
        h.addStretch(1)
        return w

    def _on_conductor_changed(self, name):
        for n, sigma in self.CONDUCTORS:
            if n == name:
                self._cond_name = n
                self._sigma = sigma
                self.recompute_from_inputs()
                return

    def make_diagram(self):
        return WaveguideDiagram()

    def compute(self, driver, v):
        f_ghz = v.get("f_ghz")
        a_mm  = v.get("a_mm")
        b_mm  = v.get("b_mm")
        eps_r = v.get("eps_r") or 1.0
        if eps_r <= 0:
            eps_r = 1.0

        # ---- pick or accept dimensions ------------------------------
        if a_mm and a_mm > 0 and b_mm and b_mm > 0:
            wr_name = "custom"
            band_text = "—"
        elif f_ghz is not None and f_ghz > 0:
            row = waveguide_for_freq(f_ghz)
            if row is None:
                return {"wr": "out of standard range",
                        "range": "0.32–325 GHz",
                        "a_mm": "", "b_mm": "",
                        "fc10": "", "fc20": "", "fc01": "",
                        "single": "", "lam0_mm": "", "lam_c_mm": "",
                        "lam_g_mm": "", "z_te10": "", "beta": "",
                        "vp_kms": "", "vg_kms": "", "td_ns_m": "",
                        "rs_mohm": "", "alpha_db_m": "",
                        "v_bd": "", "p_max": "", "modes": ""}
            wr_name, a_mm, b_mm, lo, hi = row
            band_text = f"{lo:g}–{hi:g}"
        else:
            return {}

        a = a_mm * 1e-3; b = b_mm * 1e-3
        # In-medium speed of light.
        c_eff = C_LIGHT / sqrt(eps_r)
        eta   = ETA0 / sqrt(eps_r)
        fc10 = c_eff / (2 * a)
        fc20 = c_eff / a
        fc01 = c_eff / (2 * b)
        lam_c = 2 * a            # cutoff wavelength for TE₁₀

        out = {
            "wr":     wr_name,
            "a_mm":   a_mm,
            "b_mm":   b_mm,
            "range":  band_text,
            "fc10":   fc10 / 1e9,
            "fc20":   fc20 / 1e9,
            "fc01":   fc01 / 1e9,
            "single": f"{fc10/1e9:.3f}–{fc20/1e9:.3f}",
            "lam_c_mm": lam_c * 1e3,
        }

        if f_ghz is None or f_ghz <= 0:
            return out
        f = f_ghz * 1e9
        omega = 2 * pi * f
        lam0 = c_eff / f
        out["lam0_mm"] = lam0 * 1e3

        if f > fc10:
            ratio = sqrt(1 - (fc10 / f) ** 2)
            lam_g = lam0 / ratio
            z_te10 = eta / ratio
            beta = 2 * pi / lam_g
            vp = omega / beta
            vg = c_eff * ratio
            td = 1.0 / vg if vg > 0 else 0
            # Conductor attenuation (Pozar 3.96, TE₁₀):
            R_s = sqrt(pi * f * MU0 / self._sigma)
            alpha = (R_s / (b * eta * ratio)) * (1 + (2 * b / a) * (fc10 / f) ** 2)
            alpha_db_m = alpha * 8.686
            out.update({
                "lam_g_mm":   lam_g * 1e3,
                "z_te10":     z_te10,
                "beta":       beta,
                "vp_kms":     vp / 1e3,
                "vg_kms":     vg / 1e3,
                "td_ns_m":    td * 1e9,
                "rs_mohm":    R_s * 1e3,        # Ω → mΩ/sq
                "alpha_db_m": alpha_db_m,
                "v_bd":       E_BREAKDOWN_AIR * b / 1e3,
                "p_max":      (a * b * E_BREAKDOWN_AIR ** 2)
                              / (4 * eta) * ratio / 1e3,
            })
        else:
            out["lam_g_mm"] = "below cutoff"
            for k in ("z_te10", "beta", "vp_kms", "vg_kms",
                      "td_ns_m", "rs_mohm", "alpha_db_m",
                      "v_bd", "p_max"):
                out[k] = ""

        # ---- every (m,n) mode up to (3,3), sorted by cutoff ---------
        modes = []
        for m in range(0, 4):
            for n in range(0, 4):
                if m == 0 and n == 0:
                    continue
                fc = (c_eff / (2 * pi)) * sqrt(
                    (m * pi / a) ** 2 + (n * pi / b) ** 2)
                # TE_mn: any (m,n) except (0,0) — already filtered
                modes.append((fc, f"TE_{m}{n}"))
                # TM_mn requires m ≥ 1 AND n ≥ 1
                if m >= 1 and n >= 1:
                    modes.append((fc, f"TM_{m}{n}"))
        modes.sort()
        out["modes"] = "  ".join(
            f"{lbl} {fc/1e9:.3f}" for fc, lbl in modes[:8])
        return out


# ====================================================================
#  CALCULATOR TAB
# ====================================================================
#
# General-purpose programmer / engineering calculator.  Lets the user
# evaluate math expressions, sees the result simultaneously in decimal,
# hex, binary, octal and engineering form, plus a 32-bit visual grid
# (green = bit set).  History is recallable with Up / Down arrows; a
# unit-conversion popup appears as soon as the user types "->".
#
# Examples:
#     2 + 3 * 4
#     0x1F + 0b1010
#     sin(pi/4)
#     2**10
#     10W -> dBm
#     2.4GHz -> Hz
# --------------------------------------------------------------------

# Unit table.  Each value is one of:
#   ("category", scale_to_base)    — linear conversion to the category's base unit
#   "dBm" / "dBW"                  — special log power
#   "K" / "degC" / "degF"          — special temperature
CALC_UNIT_TABLE = {
    # Frequency  (base = Hz)
    "Hz":   ("freq", 1.0),
    "kHz":  ("freq", 1e3),
    "MHz":  ("freq", 1e6),
    "GHz":  ("freq", 1e9),
    "THz":  ("freq", 1e12),
    # Time  (base = s)
    "s":    ("time", 1.0),
    "ms":   ("time", 1e-3),
    "us":   ("time", 1e-6),
    "µs":   ("time", 1e-6),
    "ns":   ("time", 1e-9),
    "ps":   ("time", 1e-12),
    "fs":   ("time", 1e-15),
    "min":  ("time", 60.0),
    "hr":   ("time", 3600.0),
    "h":    ("time", 3600.0),
    "day":  ("time", 86400.0),
    "wk":   ("time", 604800.0),
    "yr":   ("time", 31557600.0),          # Julian year (365.25 d)
    # Length  (base = m)
    "m":    ("len",  1.0),
    "cm":   ("len",  1e-2),
    "mm":   ("len",  1e-3),
    "um":   ("len",  1e-6),
    "µm":   ("len",  1e-6),
    "km":   ("len",  1e3),
    "in":   ("len",  0.0254),
    '"':    ("len",  0.0254),    # double-prime alias for inches  (5/32")
    "ft":   ("len",  0.3048),
    "'":    ("len",  0.3048),    # prime alias for feet           (6')
    "mil":  ("len",  2.54e-5),
    "mi":   ("len",  1609.344),
    # Power  (base = W)
    "W":    ("power", 1.0),
    "mW":   ("power", 1e-3),
    "kW":   ("power", 1e3),
    "MW":   ("power", 1e6),
    "uW":   ("power", 1e-6),
    "µW":   ("power", 1e-6),
    "nW":   ("power", 1e-9),
    "dBm":  "dBm",
    "dBW":  "dBW",
    # Return Loss — bare "dB" is treated as RL → VSWR + mismatch loss.
    # Kept out of CALC_CATEGORY_UNITS so '->' completion never offers it
    # as a target (you can't convert a power into a return loss).
    "dB":   ("rl", 1.0),
    # Voltage  (base = V)
    "V":    ("volt", 1.0),
    "mV":   ("volt", 1e-3),
    "kV":   ("volt", 1e3),
    "uV":   ("volt", 1e-6),
    "µV":   ("volt", 1e-6),
    # Current  (base = A)
    "A":    ("curr", 1.0),
    "mA":   ("curr", 1e-3),
    "uA":   ("curr", 1e-6),
    "µA":   ("curr", 1e-6),
    "kA":   ("curr", 1e3),
    # Resistance  (base = ohm) — use 'Ohm'/'kOhm' for ASCII
    "Ohm":  ("res", 1.0),
    "ohm":  ("res", 1.0),
    "kOhm": ("res", 1e3),
    "MOhm": ("res", 1e6),
    "mOhm": ("res", 1e-3),
    # Capacitance  (base = F)
    "F":    ("cap", 1.0),
    "mF":   ("cap", 1e-3),
    "uF":   ("cap", 1e-6),
    "µF":   ("cap", 1e-6),
    "nF":   ("cap", 1e-9),
    "pF":   ("cap", 1e-12),
    # Inductance  (base = H)
    "H":    ("ind", 1.0),
    "mH":   ("ind", 1e-3),
    "uH":   ("ind", 1e-6),
    "µH":   ("ind", 1e-6),
    "nH":   ("ind", 1e-9),
    "pH":   ("ind", 1e-12),
    # Angle  (base = rad)
    "rad":  ("angle", 1.0),
    "deg":  ("angle", pi / 180.0),
    "grad": ("angle", pi / 200.0),         # gradian / gon
    "turn": ("angle", 2 * pi),
    "rev":  ("angle", 2 * pi),
    "arcmin": ("angle", pi / 10800.0),     # minute of arc
    "arcsec": ("angle", pi / 648000.0),    # second of arc
    # Volume  (base = L / litre).  US customary by default; metric, cubic-
    # length and imperial forms included, plus lowercase aliases so
    # "5l", "5ml", "5gal", "2.5cups" (sans plural) all Just Work.
    "L":      ("vol", 1.0),
    "l":      ("vol", 1.0),
    "mL":     ("vol", 1e-3),
    "ml":     ("vol", 1e-3),
    "cL":     ("vol", 1e-2),
    "cl":     ("vol", 1e-2),
    "dL":     ("vol", 1e-1),
    "dl":     ("vol", 1e-1),
    "kL":     ("vol", 1e3),
    "kl":     ("vol", 1e3),
    "cc":     ("vol", 1e-3),               # cubic centimetre = mL
    "cm3":    ("vol", 1e-3),
    "mm3":    ("vol", 1e-6),
    "dm3":    ("vol", 1.0),
    "m3":     ("vol", 1e3),
    "in3":    ("vol", 0.016387064),        # cubic inch
    "cuin":   ("vol", 0.016387064),
    "ft3":    ("vol", 28.316846592),       # cubic foot
    "cuft":   ("vol", 28.316846592),
    "yd3":    ("vol", 764.554857984),      # cubic yard
    "cuyd":   ("vol", 764.554857984),
    "gal":    ("vol", 3.785411784),        # US gallon
    "qt":     ("vol", 0.946352946),        # US quart
    "pt":     ("vol", 0.473176473),        # US pint
    "cup":    ("vol", 0.2365882365),       # US cup
    "floz":   ("vol", 0.0295735295625),    # US fluid ounce
    "tbsp":   ("vol", 0.01478676478125),   # US tablespoon
    "tsp":    ("vol", 0.00492892159375),   # US teaspoon
    "bbl":    ("vol", 158.987294928),      # US oil barrel (42 gal)
    "impgal": ("vol", 4.54609),            # imperial gallon
    "galUK":  ("vol", 4.54609),
    "flozUK": ("vol", 0.0284130625),       # imperial fluid ounce
    # Mass / weight  (base = kg).  'oz'/'lb' are avoirdupois; fluid ounce is
    # 'floz' (volume) so there's no clash.  Bare 't' is intentionally NOT a
    # unit (too useful as a variable) — use 'tonne'/'Mg' for the metric ton.
    "kg":     ("mass", 1.0),
    "g":      ("mass", 1e-3),
    "mg":     ("mass", 1e-6),
    "ug":     ("mass", 1e-9),
    "µg":     ("mass", 1e-9),
    "ng":     ("mass", 1e-12),
    "tonne":  ("mass", 1e3),                # metric ton
    "Mg":     ("mass", 1e3),
    "lb":     ("mass", 0.45359237),
    "lbs":    ("mass", 0.45359237),
    "oz":     ("mass", 0.028349523125),     # avoirdupois ounce
    "ozt":    ("mass", 0.0311034768),       # troy ounce
    "st":     ("mass", 6.35029318),         # stone
    "ton":    ("mass", 907.18474),          # US short ton (2000 lb)
    "longton":("mass", 1016.0469088),       # UK long ton (2240 lb)
    "gr":     ("mass", 6.479891e-5),        # grain
    "dr":     ("mass", 0.0017718451953125), # dram
    "dwt":    ("mass", 0.00155517384),      # pennyweight
    "ct":     ("mass", 2e-4),               # metric carat
    "slug":   ("mass", 14.593902937),
    # Energy  (base = J)
    "J":      ("energy", 1.0),
    "mJ":     ("energy", 1e-3),
    "kJ":     ("energy", 1e3),
    "MJ":     ("energy", 1e6),
    "GJ":     ("energy", 1e9),
    "Wh":     ("energy", 3600.0),
    "mWh":    ("energy", 3.6),
    "kWh":    ("energy", 3.6e6),
    "MWh":    ("energy", 3.6e9),
    "cal":    ("energy", 4.184),
    "kcal":   ("energy", 4184.0),
    "BTU":    ("energy", 1055.05585262),
    "Btu":    ("energy", 1055.05585262),
    "ftlb":   ("energy", 1.3558179483),     # foot-pound
    "erg":    ("energy", 1e-7),
    "eV":     ("energy", 1.602176634e-19),
    "keV":    ("energy", 1.602176634e-16),
    "MeV":    ("energy", 1.602176634e-13),
    "GeV":    ("energy", 1.602176634e-10),
    # Pressure  (base = Pa)
    "Pa":     ("pressure", 1.0),
    "hPa":    ("pressure", 100.0),
    "kPa":    ("pressure", 1e3),
    "MPa":    ("pressure", 1e6),
    "GPa":    ("pressure", 1e9),
    "bar":    ("pressure", 1e5),
    "mbar":   ("pressure", 100.0),
    "psi":    ("pressure", 6894.757293168),
    "ksi":    ("pressure", 6894757.293168),
    "atm":    ("pressure", 101325.0),
    "torr":   ("pressure", 133.32236842105263),
    "mmHg":   ("pressure", 133.322387415),
    "inHg":   ("pressure", 3386.389),
    # Force  (base = N)
    "N":      ("force", 1.0),
    "mN":     ("force", 1e-3),
    "kN":     ("force", 1e3),
    "MN":     ("force", 1e6),
    "lbf":    ("force", 4.4482216152605),
    "kgf":    ("force", 9.80665),
    "dyn":    ("force", 1e-5),
    # Speed  (base = m/s).  Written without slashes so they tokenise cleanly.
    "mps":    ("speed", 1.0),
    "kph":    ("speed", 0.2777777777777778),
    "kmh":    ("speed", 0.2777777777777778),
    "mph":    ("speed", 0.44704),
    "fps":    ("speed", 0.3048),
    "kn":     ("speed", 0.5144444444444445),
    "knot":   ("speed", 0.5144444444444445),
    # Digital data  (base = byte).  Decimal (kB=1000) and binary (KiB=1024).
    "B":      ("data", 1.0),
    "byte":   ("data", 1.0),
    "kB":     ("data", 1e3),
    "MB":     ("data", 1e6),
    "GB":     ("data", 1e9),
    "TB":     ("data", 1e12),
    "PB":     ("data", 1e15),
    "KiB":    ("data", 1024.0),
    "MiB":    ("data", 1048576.0),
    "GiB":    ("data", 1073741824.0),
    "TiB":    ("data", 1099511627776.0),
    "bit":    ("data", 0.125),
    "kbit":   ("data", 125.0),
    "Mbit":   ("data", 125000.0),
    "Gbit":   ("data", 1.25e8),
    "Tbit":   ("data", 1.25e11),
    # Temperature
    "K":    "K",
    "degC": "degC",
    "degF": "degF",
    "degR": "degR",                         # Rankine (absolute °F)
}

CALC_CATEGORY_UNITS = {
    "freq":  ["Hz", "kHz", "MHz", "GHz", "THz"],
    "time":  ["s", "ms", "us", "ns", "ps", "fs", "min", "hr", "day", "wk", "yr"],
    "len":   ["m", "cm", "mm", "um", "km", "in", "ft", "mil", "mi"],
    "power": ["W", "mW", "kW", "MW", "uW", "nW", "dBm", "dBW"],
    "volt":  ["V", "mV", "kV", "uV"],
    "curr":  ["A", "mA", "uA", "kA"],
    "res":   ["Ohm", "kOhm", "MOhm", "mOhm"],
    "cap":   ["F", "mF", "uF", "nF", "pF"],
    "ind":   ["H", "mH", "uH", "nH", "pH"],
    "angle": ["rad", "deg", "grad", "turn", "arcmin", "arcsec"],
    "vol":   ["L", "mL", "gal", "qt", "pt", "cup", "floz", "tbsp", "tsp",
              "m3", "in3", "ft3"],
    "mass":  ["kg", "g", "mg", "ug", "tonne", "lb", "oz", "st", "ton",
              "gr", "ct", "slug"],
    "energy": ["J", "kJ", "MJ", "Wh", "kWh", "cal", "kcal", "BTU", "ftlb",
               "eV", "erg"],
    "pressure": ["Pa", "kPa", "MPa", "bar", "mbar", "psi", "atm", "torr",
                 "mmHg", "inHg"],
    "force": ["N", "kN", "mN", "lbf", "kgf", "dyn"],
    "speed": ["mps", "kph", "mph", "fps", "kn"],
    "data":  ["B", "kB", "MB", "GB", "TB", "KiB", "MiB", "GiB",
              "bit", "kbit", "Mbit", "Gbit"],
    "temp":  ["K", "degC", "degF", "degR"],
}


# Case-insensitive aliases for frequency & time unit tokens.  Users type
# "KHz", "khz", "0.01KHz", "MS", etc.  Within these two categories every
# prefix is unambiguous (the table has no millihertz or megasecond), so
# every case permutation maps cleanly to one canonical unit.  A permutation
# is skipped when it already names a different unit (protects "H" = Henry)
# and alias keys are kept out of the intellisense list below.
def _gen_freq_time_aliases():
    aliases = {}
    for cat in ("freq", "time"):
        for u in CALC_CATEGORY_UNITS.get(cat, []):
            info = CALC_UNIT_TABLE.get(u)
            if not isinstance(info, tuple) or not (u.isalpha() and u.isascii()):
                continue
            for combo in itertools.product(*((c.lower(), c.upper()) for c in u)):
                v = "".join(combo)
                if v not in CALC_UNIT_TABLE and v not in aliases:
                    aliases[v] = info
    return aliases


_CALC_UNIT_ALIAS_KEYS = set(_gen_freq_time_aliases())
CALC_UNIT_TABLE.update(_gen_freq_time_aliases())


def _calc_unit_category(unit):
    e = CALC_UNIT_TABLE.get(unit)
    if isinstance(e, tuple):
        return e[0]
    if e in ("dBm", "dBW"):
        return "power"
    if e in ("K", "degC", "degF", "degR"):
        return "temp"
    return None


# Restricted globals for the math evaluator.  No __builtins__, no I/O,
# just numeric / math primitives.
_CALC_SAFE_GLOBALS = {
    "__builtins__": None,
    # constants
    "pi":    pi,
    "e":     math.e,
    "tau":   2 * pi,
    "inf":   math.inf,
    "nan":   math.nan,
    # math
    "sin":   math.sin, "cos":   math.cos, "tan":   math.tan,
    "asin":  math.asin, "acos":  math.acos, "atan":  math.atan,
    "atan2": math.atan2,
    "sinh":  math.sinh, "cosh":  math.cosh, "tanh":  math.tanh,
    "log":   math.log,  "log10": math.log10, "log2": math.log2,
    "exp":   math.exp,  "sqrt":  math.sqrt,
    "floor": math.floor, "ceil":  math.ceil, "trunc": math.trunc,
    "fabs":  math.fabs,  "factorial": math.factorial,
    "gcd":   math.gcd,   "degrees": math.degrees, "radians": math.radians,
    # builtins we want
    "abs":   abs,
    "min":   min,
    "max":   max,
    "round": round,
    "int":   int,
    "float": float,
    "pow":   pow,
}


def _calc_eval_math(text):
    """Evaluate `text` as a Python math expression in a restricted namespace.
    Hex / binary / octal Python literals (0x / 0b / 0o) work."""
    return eval(text, _CALC_SAFE_GLOBALS, {})


# Intellisense candidate pools for the Calc tab.
#   * functions  → offered with a trailing '(' so the caret lands inside
#   * constants  → pi / e / tau / inf / nan, plus 'ans'
#   * units      → every unit token, shortest first (m before mm before mmHg)
_CALC_FUNC_ITEMS  = sorted(k + "(" for k, v in _CALC_SAFE_GLOBALS.items()
                           if callable(v))
_CALC_CONST_ITEMS = sorted(k for k, v in _CALC_SAFE_GLOBALS.items()
                           if v is not None and not callable(v)) + ["ans"]
_CALC_IDENT_ITEMS = _CALC_FUNC_ITEMS + _CALC_CONST_ITEMS
_CALC_UNIT_ITEMS  = sorted((k for k in CALC_UNIT_TABLE
                            if k not in _CALC_UNIT_ALIAS_KEYS),
                           key=lambda u: (len(u), u))


# Single '=' that isn't part of '==', '<=', '>=', '!=' triggers equation
# solver mode in the Calc tab.
_CALC_EQUATION_RE = re.compile(r'(?<![<>=!])=(?!=)')


def _calc_solve_equation(text):
    """If `text` reads as 'LHS = RHS' with one unknown variable, solve it.

    Returns ``(var_name, [roots])`` where ``roots`` is a list of numeric
    values (``float`` for purely real roots, ``complex`` otherwise).
    Returns ``None`` when no single '=' sign is present.  Raises
    ``ValueError`` on a malformed or unsolvable equation."""
    m = _CALC_EQUATION_RE.search(text)
    if m is None:
        return None
    lhs_raw = text[:m.start()].strip()
    rhs_raw = text[m.end():].strip()
    if not lhs_raw or not rhs_raw:
        raise ValueError("equation missing a side")
    # Canonicalise cosmetic glyphs the same way the math evaluator does
    # (× → *, ² → ^2, sin²(x) → sin(x)**2) so the solver sees what the
    # user actually typed.  `convert_xor` below maps any remaining '^'
    # into '**', so a textbook-style `x^2 = 4` works too.
    lhs = _calc_normalize_superscripts(lhs_raw)
    rhs = _calc_normalize_superscripts(rhs_raw)
    # Identify the unknown variable: any identifier in either side
    # that's not already a constant, function, or unit token.
    idents = set(re.findall(r'[A-Za-z_]\w*', lhs + ' ' + rhs))
    known = set(_CALC_SAFE_GLOBALS) | set(CALC_UNIT_TABLE)
    unknowns = sorted(c for c in idents if c not in known)
    if not unknowns:
        raise ValueError("no unknown variable")
    if len(unknowns) > 1:
        raise ValueError("multiple unknowns: " + ", ".join(unknowns))
    var_name = unknowns[0]
    try:
        import sympy as _sp
        from sympy.parsing.sympy_parser import (
            parse_expr as _parse_expr,
            standard_transformations as _std_tx,
            implicit_multiplication_application as _imul_tx,
            convert_xor as _xor_tx,
        )
    except ImportError as exc:
        raise ValueError(f"sympy not available: {exc}")
    transformations = _std_tx + (_imul_tx, _xor_tx)
    sym = _sp.Symbol(var_name)
    local_dict = {var_name: sym}
    try:
        lhs_e = _parse_expr(lhs, local_dict=local_dict,
                             transformations=transformations)
        rhs_e = _parse_expr(rhs, local_dict=local_dict,
                             transformations=transformations)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ValueError(f"can't parse equation: {exc}")
    roots = _sp.solve(_sp.Eq(lhs_e, rhs_e), sym)
    if not roots:
        raise ValueError("no solution for " + var_name)
    out = []
    for r in roots:
        try:
            c = complex(r)
        except (TypeError, ValueError):
            out.append(r)
            continue
        if abs(c.imag) < 1e-12:
            out.append(float(c.real))
        else:
            out.append(c)
    return (var_name, out)


def _calc_split_unit(text):
    """Find a trailing unit token in `text` and return (head_expr, unit) or
    (text, None).  Won't strip a unit suffix off a hex/bin/oct literal.
    Recursively peels matched outer parens so '((10-5)dBm)' resolves to
    head='(10-5)', unit='dBm'."""
    text = text.strip()
    if not text:
        return ("", None)
    if re.fullmatch(r'0[xob][0-9a-fA-F_]+', text):
        return (text, None)
    # Sort longest first so "MHz" matches before "Hz", "dBm" before "B" etc.
    units_sorted = sorted(CALC_UNIT_TABLE.keys(), key=lambda u: -len(u))
    for unit in units_sorted:
        if not text.endswith(unit) or len(text) <= len(unit):
            continue
        head = text[:-len(unit)]
        ch = head[-1]
        if ch.isdigit() or ch in '.) ':
            return (head.strip(), unit)
    # No trailing unit — but the expression might be wrapped in matched
    # outer parens, e.g. '((10-5)dBm)'.  Peel them off and re-try once.
    if text.startswith('(') and text.endswith(')'):
        depth = 0
        for i, ch in enumerate(text):
            if ch == '(': depth += 1
            elif ch == ')': depth -= 1
            if depth == 0 and i < len(text) - 1:
                # First '(' closes before end → not a single matched pair.
                return (text, None)
        if depth == 0:
            inner_head, inner_unit = _calc_split_unit(text[1:-1])
            if inner_unit is not None:
                return (inner_head, inner_unit)
    return (text, None)


# Mixed-token preprocessing: "10dBm-5dB" → ("10-5", "dBm").  Lets the user
# write decibel arithmetic naturally inside a parenthesised expression
# (e.g. '(10dBm-5dB) -> W' for "10 dBm reduced by 5 dB of attenuation, then
# converted to watts").  An absolute power token (dBm/dBW) wins as the
# carrier unit; otherwise the first dB seen is used.
#
# Linear-power tokens (W, mW, µW, uW, kW) are also accepted — they get
# implicitly converted to dBm so the user can write expressions like
# "(50W - 5dB) -> W" and have it Just Work.  The carrier becomes 'dBm'
# whenever a linear-power token is mixed in, since that's the form
# we're normalising to internally.
#
# Listed longest→shortest so the regex's leftmost-first alternation
# never matches "W" inside "dBW" or "kW".
_CALC_NUMBER_TOKEN = r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'

_CALC_DB_TOKEN_RE = re.compile(
    r'(' + _CALC_NUMBER_TOKEN + r')\s*'
    r'(dBm|dBW|kW|mW|µW|uW|W|dB)(?![A-Za-z])'
)


# --------------------------------------------------------------------
# Superscript notation:  `sin^2(x)` ↔ `sin²(x)`
#
# In the input box we render `^<digit>` as Unicode superscript glyphs
# so the expression *looks* mathy.  On evaluate we translate it back:
# `func^N(args)` / `func²(args)` becomes `func(args)**N` (the math-
# textbook idiom — square the function output, not the argument).
# Bare `^` between operands is left alone, so it keeps its Python /
# bitwise-XOR meaning for hex / binary work in this same calculator.
# --------------------------------------------------------------------

_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"

_TO_SUPERSCRIPT = str.maketrans({
    str(i): _SUPERSCRIPT_DIGITS[i] for i in range(10)
})
_FROM_SUPERSCRIPT = str.maketrans({
    _SUPERSCRIPT_DIGITS[i]: str(i) for i in range(10)
})

_CARET_DIGIT_RE = re.compile(r'\^(\d+)')
_SUPERSCRIPT_RUN_RE = re.compile(f'[{_SUPERSCRIPT_DIGITS}]+')

# Recognise the math-function-postfix-power form for any of these
# well-known names.  Listed long-first so `asin` matches before `sin`.
_POWER_FUNCS = (
    "asin", "acos", "atan", "atan2",
    "sinh", "cosh", "tanh",
    "log10", "log2",
    "sin", "cos", "tan",
    "log", "ln", "exp", "sqrt", "abs",
)


def _calc_render_superscripts(text):
    """Replace each `^<digits>` run with the Unicode-superscript form
    (`^2` → `²`, `^12` → `¹²`).  Pure cosmetic — used in the input box
    so the expression reads mathematically."""
    return _CARET_DIGIT_RE.sub(
        lambda m: m.group(1).translate(_TO_SUPERSCRIPT),
        text,
    )


_MULT_SINGLE_STAR_RE = re.compile(r"(?<!\*)\*(?!\*)")


def _calc_render_multiplication(text):
    """Display-only rewrite of bare `*` to `×` (U+00D7).  `**` is left
    alone so the power operator still reads correctly, and `×` already
    in the text is canonicalised back to `*` first so an existing `×`
    flips back the moment the user appends a second `*` (turning the
    multiplication into a power).  1-to-1 substitution — caller does
    not need to adjust cursor positions."""
    canonical = text.replace("×", "*")
    return _MULT_SINGLE_STAR_RE.sub("×", canonical)


def _calc_normalize_superscripts(expr):
    """Reverse the cosmetic rewrites and apply the math-idiom transform.

    0. '×' (cosmetic multiplication) → '*' so the parser sees normal
       Python multiplication.
    1. Unicode superscript runs become `^<digits>` so we have a single
       canonical form.
    2. `<func>^<N>(args)` for the known function names becomes
       `<func>(args)**<N>` — that's how `sin²(x)` is read in textbooks
       (square the result, not the argument).
    Returns the rewritten string.  Any remaining bare `^` is rewritten
    to `**` (math-exponent convention — matches the equation-solver mode
    and how every desktop calculator reads `2^11`).  Pure bitwise-XOR
    between hex/binary/octal literals (e.g. `0xFF^0x0F`) is preserved
    because turning `**` between huge ints would just OOM."""
    # Step 0 — cosmetic '×' → '*'
    expr = expr.replace("×", "*")
    # Step 1 — superscript glyphs → "^<digits>"
    expr = _SUPERSCRIPT_RUN_RE.sub(
        lambda m: "^" + m.group(0).translate(_FROM_SUPERSCRIPT),
        expr,
    )
    # Step 2 — math-function postfix-power rewrite.  We loop until a
    # pass produces no change so nested expressions like `sin^2(cos^3(x))`
    # collapse correctly.
    func_alt = "|".join(_POWER_FUNCS)
    func_re = re.compile(
        rf'\b({func_alt})\^(\d+)\(([^()]*)\)'
    )
    while True:
        new_expr = func_re.sub(r'\1(\3)**\2', expr)
        if new_expr == expr:
            break
        expr = new_expr
    # Step 2b — `<func>(args)^<N>` → `<func>(args)**<N>`.  Covers the
    # parametric path where `log[x]²` becomes `log(0.5)²` and then
    # `log(0.5)^2` after Step 1 — without this the caret stays as XOR
    # and the eval fails on a non-integer.  Restricted to the known
    # function-name list so accidental XOR-on-parens (e.g. `(a)^3`) is
    # not silently re-typed.
    func_after_re = re.compile(
        rf'\b({func_alt})\(([^()]*)\)\^(\d+)'
    )
    while True:
        new_expr = func_after_re.sub(r'\1(\2)**\3', expr)
        if new_expr == expr:
            break
        expr = new_expr
    # Step 3 — any remaining bare `^` between two numeric operands is the
    # math-textbook exponent operator.  Preserve XOR semantics ONLY when
    # both adjacent operands are explicit base-N integer literals
    # (0x.., 0b.., 0o..) since that's the bit-twiddling idiom; everything
    # else (`2^11`, `2.5^3`, `(a+b)^2`) gets rewritten to `**`.
    _CARET_RE = re.compile(
        r'(?P<lhs>0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+'
        r'|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\))'
        r'\s*\^\s*'
        r'(?P<rhs>[+-]?(?:0[xX][0-9A-Fa-f]+|0[bB][01]+|0[oO][0-7]+'
        r'|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\())'
    )

    def _caret_repl(m):
        lhs, rhs = m.group("lhs"), m.group("rhs")
        # Strip any leading unary sign on rhs before checking the bit-XOR
        # exception — `0xFF^-0x0F` should still parse as XOR with the
        # raw operands, not as `0xFF**(-0x0F)`.
        rhs_core = rhs.lstrip("+-").strip()
        bit_prefix = ("0x", "0X", "0b", "0B", "0o", "0O")
        if lhs.startswith(bit_prefix) and rhs_core.startswith(bit_prefix):
            return m.group(0)            # keep XOR
        return f"{lhs}**{rhs}"

    # Sub repeatedly so `a^b^c` collapses left-to-right (Python's ** is
    # right-associative, matching textbook exponent associativity).
    while True:
        new_expr = _CARET_RE.sub(_caret_repl, expr)
        if new_expr == expr:
            break
        expr = new_expr
    return expr


def _calc_preprocess_db(expr):
    """Rewrite mixed dB / linear-power expressions into a single-carrier
    arithmetic problem.

    Returns (new_expr, carrier) where carrier is 'dBm', 'dBW', or 'dB'
    depending on which units appeared.  When no dB-style token is
    present the function is a no-op — the unit-split path handles
    pure-linear expressions."""
    matches = list(_CALC_DB_TOKEN_RE.finditer(expr))
    if not matches:
        return (expr, None)

    has_db    = any(m.group(2) == "dB"   for m in matches)
    has_dbm   = any(m.group(2) == "dBm"  for m in matches)
    has_dbw   = any(m.group(2) == "dBW"  for m in matches)
    has_lin   = any(m.group(2) in ("W", "mW", "uW", "µW", "kW")
                    for m in matches)

    _LIN_SCALE = {"W": 1.0, "mW": 1e-3, "uW": 1e-6, "µW": 1e-6, "kW": 1e3}

    # Pure linear-power expression (no dB family): collapse every W
    # variant to its numeric value in watts so "5W + 3W" → "5 + 3" and
    # "50W - 0.5W -> dBm" works via the standard unit-conversion path.
    # Carrier is "W" so a trailing -> dBm/dBW still does the right log
    # conversion.
    if not (has_db or has_dbm or has_dbw):
        if has_lin:
            def repl_lin(m):
                val = m.group(1); unit = m.group(2)
                try:
                    w = float(val) * _LIN_SCALE.get(unit, 1.0)
                except ValueError:
                    return val
                return f"{w:.10g}"
            return (_CALC_DB_TOKEN_RE.sub(repl_lin, expr), "W")
        return (expr, None)

    # Pick the carrier:
    #   • Mix of linear & dBW (no dBm)   → dBW
    #   • Otherwise any dBm / linear / dB → dBm
    #   • Pure dB only                    → dB
    if has_dbw and not has_dbm and not has_lin:
        carrier = "dBW"
    elif has_dbw and not has_dbm and has_lin:
        carrier = "dBW"        # let dBW dominate when paired with W
    elif has_dbm or has_lin:
        carrier = "dBm"
    elif has_dbw:
        carrier = "dBW"
    else:
        carrier = "dB"

    def repl(m):
        val = m.group(1); unit = m.group(2)
        if unit == "dB":
            return val
        if unit == "dBm":
            return f"({val} - 30)" if carrier == "dBW" else val
        if unit == "dBW":
            return f"({val} + 30)" if carrier == "dBm" else val
        # Linear-power token → carrier
        try:
            w = float(val) * _LIN_SCALE[unit]
        except (KeyError, ValueError):
            return val
        if w <= 0:
            return val
        dbm = 10.0 * log10(w * 1000.0)
        if carrier == "dBW":
            return f"{dbm - 30:.10g}"
        return f"{dbm:.10g}"

    return (_CALC_DB_TOKEN_RE.sub(repl, expr), carrier)


# --------------------------------------------------------------------
# Generic-unit arithmetic preprocessor — lets expressions like
#   "385mm / 2"          (single unit, embedded math) → 192.5 mm
#   "1in + 5mm"          (mixed compatible units)    → 1.197 in
#   "10MHz * 2"          (frequency × scalar)        → 20 MHz
# parse correctly.  The existing _calc_split_unit only finds a trailing
# unit; this preprocessor catches unit tokens anywhere inside the math
# expression.  dB-family power units stay with _calc_preprocess_db
# (their arithmetic semantics are non-multiplicative).
# --------------------------------------------------------------------
def _build_calc_unit_token_re():
    units = []
    for u, info in CALC_UNIT_TABLE.items():
        if not isinstance(info, tuple):
            continue           # skip "dBm" / "K" / "degC" / "degF"
        cat, _scale = info
        if cat in ("freq", "time", "len", "vol", "mass", "energy",
                   "pressure", "force", "speed", "data", "volt", "curr",
                   "res", "cap", "ind", "angle", "power"):
            # Linear-power tokens (W, mW, …) belong to _calc_preprocess_db
            if cat == "power":
                continue
            units.append(u)
    # Longest first so "MHz" / "kOhm" / "mm" all win over their prefixes.
    units.sort(key=len, reverse=True)
    return re.compile(
        r'(' + _CALC_NUMBER_TOKEN + r')\s*'
        r'(' + '|'.join(re.escape(u) for u in units) + r')(?![A-Za-z])'
    )


_CALC_UNIT_TOKEN_RE = _build_calc_unit_token_re()


def _calc_preprocess_units(expr):
    """Find <number><unit> tokens for ordinary (non-dB) units and rewrite
    every match to its numeric value expressed in a single canonical
    display unit.  Returns (rewritten_expr, display_unit) or (expr, None)
    when no token is present / units span incompatible categories."""
    matches = list(_CALC_UNIT_TOKEN_RE.finditer(expr))
    if not matches:
        return (expr, None)
    cats = set()
    units_seen = []
    for m in matches:
        u = m.group(2)
        info = CALC_UNIT_TABLE.get(u)
        if not isinstance(info, tuple):
            return (expr, None)
        cats.add(info[0])
        units_seen.append(u)
    if len(cats) != 1:
        # Mixing length with time etc. — bail out, the regular pipeline
        # will produce a clearer error than a silent wrong answer.
        return (expr, None)
    display_unit = units_seen[0]
    display_scale = CALC_UNIT_TABLE[display_unit][1]
    def repl(m):
        val_s = m.group(1); u = m.group(2)
        scale = CALC_UNIT_TABLE[u][1]
        # Convert val [u]  →  display_unit
        v_display = float(val_s) * (scale / display_scale)
        return f"({v_display:.12g})"
    return (_CALC_UNIT_TOKEN_RE.sub(repl, expr), display_unit)


def _calc_to_base(value, unit):
    """Return ('category', base_value) for `value` in `unit`."""
    e = CALC_UNIT_TABLE.get(unit)
    if e == "dBm":
        return ("power", 10 ** ((value - 30) / 10))     # → W
    if e == "dBW":
        return ("power", 10 ** (value / 10))            # → W
    if e == "K":
        return ("temp", value)
    if e == "degC":
        return ("temp", value + 273.15)
    if e == "degF":
        return ("temp", (value - 32.0) * 5.0 / 9.0 + 273.15)
    if e == "degR":
        return ("temp", value * 5.0 / 9.0)              # Rankine → K
    if isinstance(e, tuple):
        cat, scale = e
        return (cat, value * scale)
    return None


def _calc_from_base(value, unit):
    """Convert `value` (in the category's base unit) to `unit`."""
    e = CALC_UNIT_TABLE.get(unit)
    if e == "dBm":
        if value <= 0:
            raise ValueError("dBm needs strictly positive watts")
        return 10.0 * log10(value * 1000.0)
    if e == "dBW":
        if value <= 0:
            raise ValueError("dBW needs strictly positive watts")
        return 10.0 * log10(value)
    if e == "K":
        return value
    if e == "degC":
        return value - 273.15
    if e == "degF":
        return (value - 273.15) * 9.0 / 5.0 + 32.0
    if e == "degR":
        return value * 9.0 / 5.0                        # K → Rankine
    if isinstance(e, tuple):
        cat, scale = e
        return value / scale
    raise ValueError(f"Unknown target unit '{unit}'")


# --------------------------------------------------------------------
class CalcBitGrid(QWidget):
    """Compact single-row 32-bit display.  All 32 cells fit on one line,
    thin black gridlines between them, green fill when the bit is set.

    Left-clicking a cell toggles that bit and emits `valueChanged(int)`
    with the new unsigned 32-bit value — the Calc tab uses this to push
    the edited number straight back into its input."""

    BITS = 32

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tight, single-row strip.
        self.setMinimumHeight(22)
        self.setMaximumHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            self.setCursor(Qt.PointingHandCursor)
        except Exception:
            pass
        self.setToolTip("Click any bit to flip it — the calculator's "
                        "value updates immediately.")
        self._value = 0

    def set_value(self, v):
        try:
            iv = int(v)
        except (TypeError, ValueError, OverflowError):
            iv = 0
        if iv < 0:
            iv = (iv + (1 << self.BITS)) & ((1 << self.BITS) - 1)
        self._value = iv & ((1 << self.BITS) - 1)
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton or self.width() <= 0:
            return super().mousePressEvent(ev)
        # Map x → column → bit index (column 0 holds the MSB, B31).
        col = int(ev.x() * self.BITS / self.width())
        col = max(0, min(self.BITS - 1, col))
        bit_idx = (self.BITS - 1) - col
        self._value ^= (1 << bit_idx)
        self._value &= (1 << self.BITS) - 1
        self.update()
        self.valueChanged.emit(self._value)

    def paintEvent(self, ev):
        p = QPainter(self)
        # Pixel-aligned gridlines look cleaner without antialiasing.
        p.setRenderHint(QPainter.Antialiasing, False)
        if THEME == "dark":
            on_color  = QColor(80,  200, 100)
            off_color = QColor(40,  40,  40)
            border    = QColor(0,   0,   0)        # black gridlines either way
        else:
            on_color  = QColor(110, 220, 130)
            off_color = QColor(245, 245, 245)
            border    = QColor(0,   0,   0)
        # Bit numbers always render in black for readability against either
        # the green "1" fill or the off-white "0" fill.
        text_on  = QColor(0, 0, 0)
        text_off = QColor(0, 0, 0)
        w = self.width()
        h = self.height()
        # Use exact integer cell widths so the right edge always lines up.
        # First lay down the fills, then paint a single-pixel black grid on top.
        from PyQt5.QtCore import QRect
        f = QFont(); f.setPointSize(9); p.setFont(f)
        for col in range(self.BITS):
            # Column 0 (left) holds B31 (MSB).
            i = (self.BITS - 1) - col
            x0 = (col * w) // self.BITS
            x1 = ((col + 1) * w) // self.BITS
            cell_w = x1 - x0
            bit = (self._value >> i) & 1
            p.fillRect(x0, 0, cell_w, h, on_color if bit else off_color)
            p.setPen(text_on if bit else text_off)
            p.drawText(QRect(x0, 0, cell_w, h), Qt.AlignCenter, str(i))
        # 1-pixel black grid (vertical lines + outer border).
        p.setPen(QPen(border, 1))
        for col in range(1, self.BITS):
            x = (col * w) // self.BITS
            p.drawLine(x, 0, x, h - 1)
        p.drawRect(0, 0, w - 1, h - 1)


class CalcCompleter(QCompleter):
    """Completer for the Calc tab's intellisense.  The CalcTab recomputes the
    model + prefix on every keystroke; these overrides keep QCompleter's own
    idea of the 'current token' and the accepted-text in sync with whatever
    the tab is completing — a '->' unit target, a unit suffix after a number,
    or a function / constant name."""

    def __init__(self, tab, parent=None):
        super().__init__([], parent or tab)
        self._tab = tab

    def splitPath(self, path):
        return [self._tab._completion_prefix or ""]

    def pathFromIndex(self, index):
        # Build the full replacement text the same way the activated-signal
        # handler does, so whichever path applies, the result is identical.
        return self._tab._completion_full_text(super().pathFromIndex(index))


# --------------------------------------------------------------------
# Parametric expression syntax for the Calc tab.
#
# A bracketed token in the input acts as a "knob":
#
#   [N]                    – a literal value, editable in the popup
#   [name, lo, hi, step]   – a sweep variable; the popup generates one row
#                            per value lo .. hi (inclusive) step
#
# Example:  ([10]dBm - [x,1,10,0.1]dB) -> W
#
# Hitting Enter on an expression with any [...] knob pops up a
# ParametricDialog with editable knobs, a datagrid of (sweep value, result)
# rows, and an embedded plot.  Double-clicking a column header switches
# the plot's Y axis to that column.
# --------------------------------------------------------------------

_PARAM_RE = re.compile(r"\[([^\[\]]+)\]")


# Default sweep range used when the user writes a bare [name] with no
# explicit lo / hi / step.  Picks 0..10 in 0.1 steps — 101 rows, fine
# resolution for the common case of sweeping a dB loss or a small
# integer parameter.  The user can always tweak the spinboxes in the
# popup after the dialog opens.
_DEFAULT_SWEEP_LO   = 0.0
_DEFAULT_SWEEP_HI   = 10.0
_DEFAULT_SWEEP_STEP = 0.1


def _parse_param_token(inner):
    """Parse a single bracket payload.  Returns
        ("literal", value)                          for [N]
        ("sweep", name, lo, hi, step)               for [name, lo, hi, step]
                                                    or [name]
                                                    or [name, hi]
                                                    or [name, lo, hi]
    or None on a malformed token.

    A bare identifier like [x] is treated as a sweep with default
    range (0..10 step 0.1).  [name, hi] uses lo=0, default step.
    [name, lo, hi] uses default step."""
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) == 1:
        # Numeric → literal.
        try:
            return ("literal", float(parts[0]))
        except ValueError:
            pass
        # Identifier → sweep with all defaults.
        name = parts[0]
        if name and name.isidentifier():
            return ("sweep", name,
                    _DEFAULT_SWEEP_LO, _DEFAULT_SWEEP_HI, _DEFAULT_SWEEP_STEP)
        return None
    if len(parts) in (2, 3, 4):
        name = parts[0]
        if not name or not name.isidentifier():
            return None
        try:
            nums = [float(p) for p in parts[1:]]
        except ValueError:
            return None
        if len(nums) == 1:
            # [name, hi] → 0 .. hi with default step
            lo, hi, step = _DEFAULT_SWEEP_LO, nums[0], _DEFAULT_SWEEP_STEP
        elif len(nums) == 2:
            # [name, lo, hi] → fixed bounds, default step
            lo, hi, step = nums[0], nums[1], _DEFAULT_SWEEP_STEP
        else:
            lo, hi, step = nums
        if step == 0 or (hi - lo) * step < 0:
            return None
        return ("sweep", name, lo, hi, step)
    return None


def _extract_params(text):
    """Walk the input string and return (knobs, template).
        knobs    – list of parsed tokens in encounter order
        template – the original string with each bracket replaced by '{N}'
                   so we can `.format(*values)` it back later.
    Brackets that don't parse cleanly are recorded as ('verbatim', '[…]')
    knobs and re-emitted unchanged via the template.

    Brackets that directly follow an alphabetic identifier (a function
    name like `tan`) or a `)` are substituted as `({N})` so the value
    parses as a function argument — that lets the user write
    `tan[x]` and get `tan(0.5)` instead of `tan0.5`."""
    knobs = []
    parts = []
    last = 0
    for m in _PARAM_RE.finditer(text):
        parts.append(text[last:m.start()])
        parsed = _parse_param_token(m.group(1))
        if parsed is None:
            knobs.append(("verbatim", m.group(0)))
        else:
            knobs.append(parsed)
        # Auto-parenthesise when the bracket immediately follows an
        # identifier letter or a closing paren — preserves the existing
        # behaviour of `[N]dBm` / `(50W − [x]dB)` (preceded by space,
        # operator, or start-of-string) while making `tan[x]` parse.
        # Also look past a trailing `^<digits>` or Unicode superscript
        # run so `sin^2[x]` / `sin²[x]` wrap as `sin^2(<val>)` — that's
        # what the postfix-power normalizer needs to rewrite to
        # `sin(<val>)**2`.
        prefix = text[:m.start()]
        pow_tail = re.search(
            rf'(?:\^\d+|[{_SUPERSCRIPT_DIGITS}]+)$', prefix
        )
        core = prefix[:pow_tail.start()] if pow_tail else prefix
        # An identifier word (`log10`, `sin`) or a closing paren marks
        # a function-call site — auto-paren so the bracket value lands
        # inside the call.  Bare digit/operator/space contexts (e.g.
        # `[10]dBm`, `5^2[x]`) keep the literal-substitution behaviour.
        if re.search(r'[A-Za-z]\w*$', core) or core.endswith(")"):
            parts.append(f"({{{len(knobs) - 1}}})")
        else:
            parts.append(f"{{{len(knobs) - 1}}}")
        last = m.end()
    parts.append(text[last:])
    return knobs, "".join(parts)


def _frange(lo, hi, step):
    """Inclusive arithmetic progression that handles either direction and
    avoids float drift on the upper bound."""
    if step == 0:
        return [lo]
    n = int(round((hi - lo) / step))
    if n < 0:
        return [lo]
    out = [lo + i * step for i in range(n + 1)]
    if out and ((step > 0 and out[-1] > hi + 1e-9 * (abs(hi) + 1))
             or (step < 0 and out[-1] < hi - 1e-9 * (abs(hi) + 1))):
        out.pop()
    return out


class ParametricDialog(QDialog):
    """Live datagrid + plot for an expression with [knob] parameters.
    Double-click a table column header to make that column the plot Y axis."""

    def __init__(self, evaluator, knobs, template, raw_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Parametric — {raw_text}")
        self.resize(900, 540)
        self._evaluate = evaluator      # CalcTab._evaluate (same path used on Enter)
        self._knobs = knobs
        self._template = template
        self._raw = raw_text
        self._sweep_widgets = {}        # idx -> (lo_sb, hi_sb, step_sb)
        self._lit_widgets   = {}        # idx -> spinbox
        self._rows = []
        self._plot_y_col = None
        self._last_sweep_axes = []
        self._build_ui()
        self._recompute()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        expr_lbl = QLabel(f"<b>Expression:</b>  <code>{self._raw}</code>")
        expr_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(expr_lbl)

        # ---- table + plot side-by-side, full vertical real-estate --
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(self)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        self.table.setAlternatingRowColors(False)
        # Black grid lines per CLAUDE.md / user request.
        self.table.setStyleSheet(
            "QTableWidget { gridline-color: black; }"
            "QHeaderView::section { background-color: #f0f0f0; }"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(16)
        self.table.verticalHeader().setMinimumSectionSize(16)
        self.table.horizontalHeader().sectionDoubleClicked.connect(
            self._on_col_double_clicked)
        self.table.cellDoubleClicked.connect(
            lambda r, c: self._on_col_double_clicked(c))
        split.addWidget(self.table)

        if HAS_SMITH:
            self._fig = Figure(figsize=(4, 3), tight_layout=True)
            self._ax = self._fig.add_subplot(111)
            self._canvas = FigureCanvas(self._fig)
            split.addWidget(self._canvas)
        else:
            self._canvas = None
            self._ax = None
            placeholder = QLabel(
                "(matplotlib not installed – plot disabled)")
            placeholder.setAlignment(Qt.AlignCenter)
            split.addWidget(placeholder)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)

        # ---- bottom strip: knobs + Close button on one line --------
        # Compact horizontal layout: each sweep/literal knob fits in a
        # short labelled cluster, and the Close button anchors the
        # right side.  Saves the vertical real-estate the old GroupBox
        # was eating.
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)
        for i, k in enumerate(self._knobs):
            if k[0] == "sweep":
                _, name, lo, hi, step = k
                bottom.addWidget(QLabel(f"<b>{name}</b>"))
                lo_sb   = self._spin(lo,   "lo")
                hi_sb   = self._spin(hi,   "hi")
                step_sb = self._spin(step, "step")
                bottom.addWidget(QLabel("from"))
                bottom.addWidget(lo_sb)
                bottom.addWidget(QLabel("to"))
                bottom.addWidget(hi_sb)
                bottom.addWidget(QLabel("step"))
                bottom.addWidget(step_sb)
                self._sweep_widgets[i] = (lo_sb, hi_sb, step_sb)
                for sb in (lo_sb, hi_sb, step_sb):
                    sb.valueChanged.connect(self._recompute)
            elif k[0] == "literal":
                _, val = k
                bottom.addWidget(QLabel(f"k{i}"))
                sb = self._spin(val, "literal")
                self._lit_widgets[i] = sb
                bottom.addWidget(sb)
                sb.valueChanged.connect(self._recompute)
            else:
                bottom.addWidget(QLabel(f"<i>{k[1]}</i>"))
        bottom.addStretch(1)
        btns = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        btns.rejected.connect(self.reject)
        bottom.addWidget(btns)
        outer.addLayout(bottom)

    @staticmethod
    def _spin(value, kind):
        sb = QDoubleSpinBox()
        sb.setRange(-1e15, 1e15)
        sb.setDecimals(6)
        sb.setMaximumWidth(110)
        sb.setSingleStep(0.01 if kind == "step" else 0.1)
        sb.setValue(value)
        return sb

    def _recompute(self):
        knobs_now = []
        for i, k in enumerate(self._knobs):
            if k[0] == "sweep":
                lo, hi, step = (w.value() for w in self._sweep_widgets[i])
                knobs_now.append(("sweep", k[1], lo, hi, step))
            elif k[0] == "literal":
                knobs_now.append(("literal", self._lit_widgets[i].value()))
            else:
                knobs_now.append(k)

        sweep_axes = []
        for i, k in enumerate(knobs_now):
            if k[0] == "sweep":
                _, name, lo, hi, step = k
                sweep_axes.append((i, name, _frange(lo, hi, step)))

        rows = []
        if not sweep_axes:
            rows.append({})
        else:
            from itertools import product
            for combo in product(*[ax[2] for ax in sweep_axes]):
                row = {}
                for (_i, name, _vals), v in zip(sweep_axes, combo):
                    row[name] = v
                rows.append(row)

        result_unit = None
        for row in rows:
            values = []
            for i, k in enumerate(knobs_now):
                if k[0] == "sweep":
                    values.append(self._fmt_num(row[k[1]]))
                elif k[0] == "literal":
                    values.append(self._fmt_num(k[1]))
                else:
                    values.append(k[1])
            text = self._template.format(*values)
            try:
                value, unit = self._evaluate(text)
                row["_result"] = value
                row["_unit"]   = unit
                if unit is not None:
                    result_unit = unit
            except Exception as exc:
                row["_result"] = None
                row["_unit"]   = None
                row["_error"]  = str(exc)

        # When the result carries a convertible unit, add one column per
        # other unit in that category (mil → mm, cm, in, ft, …).
        cat = _calc_unit_category(result_unit) if result_unit else None
        conv_units = ([u for u in CALC_CATEGORY_UNITS.get(cat, [])
                       if u != result_unit] if cat else [])
        self._conv_units = conv_units

        self._rows = rows
        self._render_table(sweep_axes, result_unit, conv_units)
        self._render_plot(sweep_axes)

    @staticmethod
    def _fmt_num(v):
        return f"{v:.10g}"

    @staticmethod
    def _convert(value, from_unit, to_unit):
        """`value` [from_unit] → to_unit via the category base, or None."""
        if value is None or from_unit is None or isinstance(value, complex):
            return None
        try:
            tup = _calc_to_base(value, from_unit)
            if tup is None:
                return None
            return _calc_from_base(tup[1], to_unit)
        except Exception:
            return None

    @staticmethod
    def _fmt_cell(v):
        if v is None:
            return ""
        if isinstance(v, complex):
            return f"{v.real:.4g}+{v.imag:.4g}j"
        return f"{v:.5g}"

    def _render_table(self, sweep_axes, result_unit, conv_units):
        cols = [name for _, name, _ in sweep_axes]
        cols.append(f"result ({result_unit})" if result_unit else "result")
        rcol = len(sweep_axes)                 # result column index
        cols += list(conv_units)               # one column per conversion
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setRowCount(len(self._rows))
        self.table.setHorizontalHeaderLabels(cols)
        for r, row in enumerate(self._rows):
            for c, (_, name, _vals) in enumerate(sweep_axes):
                v = row.get(name)
                it = QTableWidgetItem("" if v is None else f"{v:.4g}")
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, it)
            res = row.get("_result"); ru = row.get("_unit")
            it = QTableWidgetItem(row.get("_error", "—") if res is None
                                  else self._fmt_cell(res))
            it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, rcol, it)
            for j, u in enumerate(conv_units):
                it = QTableWidgetItem(self._fmt_cell(self._convert(res, ru, u)))
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, rcol + 1 + j, it)
        hdr = self.table.horizontalHeader()
        mode = QHeaderView.Stretch if len(cols) <= 5 else QHeaderView.ResizeToContents
        for c in range(len(cols)):
            hdr.setSectionResizeMode(c, mode)

    def _on_col_double_clicked(self, col):
        self._plot_y_col = col
        self._render_plot(self._last_sweep_axes)

    def _render_plot(self, sweep_axes):
        self._last_sweep_axes = sweep_axes
        if self._canvas is None or self._ax is None:
            return
        self._ax.clear()
        if not sweep_axes:
            self._canvas.draw_idle()
            return
        _, x_name, _ = sweep_axes[0]
        n_sweeps = len(sweep_axes)
        result_col = n_sweeps
        y_col = self._plot_y_col if self._plot_y_col is not None else result_col

        x_vals, y_vals = [], []
        for row in self._rows:
            xv = row.get(x_name)
            if xv is None:
                continue
            conv = getattr(self, "_conv_units", [])
            if y_col == result_col:
                yv = row.get("_result")
            elif result_col < y_col <= result_col + len(conv):
                yv = self._convert(row.get("_result"), row.get("_unit"),
                                   conv[y_col - result_col - 1])
            elif y_col < n_sweeps:
                _, yname, _ = sweep_axes[y_col]
                yv = row.get(yname)
            else:
                yv = None
            if yv is None or isinstance(yv, complex):
                continue
            x_vals.append(xv)
            y_vals.append(float(yv))
        self._ax.plot(x_vals, y_vals, marker="o", markersize=3, linewidth=1)
        self._ax.set_xlabel(x_name)
        conv = getattr(self, "_conv_units", [])
        if y_col == result_col:
            sample_unit = next((row.get("_unit") for row in self._rows
                                if row.get("_unit")), None)
            self._ax.set_ylabel(
                f"result ({sample_unit})" if sample_unit else "result")
        elif result_col < y_col <= result_col + len(conv):
            self._ax.set_ylabel(conv[y_col - result_col - 1])
        else:
            _, yname, _ = sweep_axes[y_col]
            self._ax.set_ylabel(yname)
        self._ax.grid(True, linestyle=":", linewidth=0.5)
        self._canvas.draw_idle()


# =====================================================================
#  PCB-design helpers (Saturn-PCB-toolkit-flavoured cards)
# =====================================================================

class ResistorSeriesParallelCard(CalcCard):
    """Up to six resistor values combined in series and in parallel.
    Blank rows are skipped, so the user can do a 2-resistor or 6-resistor
    combination through the same card."""

    def __init__(self):
        super().__init__("Resistors  series / parallel  (up to 6)", [
            Field("r1", "R₁", "Ω"),
            Field("r2", "R₂", "Ω"),
            Field("r3", "R₃", "Ω"),
            Field("r4", "R₄", "Ω"),
            Field("r5", "R₅", "Ω"),
            Field("r6", "R₆", "Ω"),
            Field("r_series",   "Series total",   "Ω", is_output=True),
            Field("r_parallel", "Parallel total", "Ω", is_output=True),
        ])

    def make_diagram(self):
        return _SeriesParallelDiagram("R")

    def compute(self, driver, v):
        rs = [v.get(f"r{i}") for i in range(1, 7)]
        rs = [r for r in rs if r is not None and r > 0]
        if not rs:
            return {}
        s = sum(rs)
        try:
            p = 1.0 / sum(1.0 / r for r in rs)
        except ZeroDivisionError:
            p = None
        out = {"r_series": s}
        if p is not None:
            out["r_parallel"] = p
        return out


class CapacitorSeriesParallelCard(CalcCard):
    """Up to six capacitor values combined in series and in parallel."""

    def __init__(self):
        super().__init__("Capacitors  series / parallel  (up to 6)", [
            Field("c1", "C₁", "F"),
            Field("c2", "C₂", "F"),
            Field("c3", "C₃", "F"),
            Field("c4", "C₄", "F"),
            Field("c5", "C₅", "F"),
            Field("c6", "C₆", "F"),
            Field("c_parallel", "Parallel total", "F", is_output=True),
            Field("c_series",   "Series total",   "F", is_output=True),
        ])

    def make_diagram(self):
        return _SeriesParallelDiagram("C")

    def compute(self, driver, v):
        cs = [v.get(f"c{i}") for i in range(1, 7)]
        cs = [c for c in cs if c is not None and c > 0]
        if not cs:
            return {}
        p = sum(cs)
        try:
            s = 1.0 / sum(1.0 / c for c in cs)
        except ZeroDivisionError:
            s = None
        out = {"c_parallel": p}
        if s is not None:
            out["c_series"] = s
        return out


class RiseFallTimeCard(CalcCard):
    """RC step-response timing.  All four output rows update from a
    single (R, C) pair:

        τ        = R · C
        t_rise   = 2.2 · τ          (10 % → 90 % crossing)
        t_settle = 5   · τ          (~99 % settled)
        BW       = 0.35 / t_rise    (Gaussian-channel single-pole approx)

    Useful for sizing pull-ups, debounce / EMI filters, and digital
    edge-rate budgets."""

    def __init__(self):
        super().__init__("RC rise / fall time", [
            Field("r",        "R",                 "Ω"),
            Field("c",        "C",                 "F"),
            Field("tau",      "τ = R·C",           "s",  is_output=True),
            Field("t_rise",   "t_rise (10–90 %)",  "s",  is_output=True),
            Field("t_settle", "t_settle (≈ 5τ)",   "s",  is_output=True),
            Field("bw",       "BW = 0.35 / t_rise","Hz", is_output=True),
        ])

    def make_diagram(self):
        return _RiseFallDiagram()

    def compute(self, driver, v):
        R = v.get("r"); C = v.get("c")
        if R is None or C is None or R <= 0 or C <= 0:
            return {}
        tau = R * C
        t_rise = 2.2 * tau
        t_settle = 5.0 * tau
        bw = 0.35 / t_rise if t_rise > 0 else None
        out = {"tau": tau, "t_rise": t_rise, "t_settle": t_settle}
        if bw is not None:
            out["bw"] = bw
        return out


class ThermalJunctionCard(CalcCard):
    """Steady-state junction temperature from dissipation, ambient,
    and thermal resistance:

        T_j = T_a + P · θ_JA

    Either supply θ_JA directly (datasheet number for free-air JEDEC
    test boards), or supply θ_JC + θ_CA and the card sums them.  When
    θ_JC is known, case temperature is also reported.  Standard silicon
    Tj_max = 125 °C is used to compute the headroom; many automotive
    parts allow 150 °C, RF GaN ≥ 175 °C — adjust mentally."""

    def __init__(self):
        super().__init__("Junction temperature (steady-state)", [
            Field("p_w",     "Power dissipation",        "W"),
            Field("t_amb",   "Ambient temperature",      "°C"),
            Field("rth_ja",  "θ_JA (junction-to-amb)",   "°C/W"),
            Field("rth_jc",  "θ_JC (junction-to-case)",  "°C/W"),
            Field("rth_ca",  "θ_CA (case-to-amb)",       "°C/W"),
            Field("tj",      "T_J  junction temp",       "°C", is_output=True),
            Field("tc",      "T_C  case temp",           "°C", is_output=True),
            Field("margin",  "Headroom to 125 °C",       "°C", is_output=True),
        ])
        # Sensible defaults
        self.fields["t_amb"].edit.setText("25")

    def compute(self, driver, v):
        p   = v.get("p_w")
        ta  = v.get("t_amb")
        rja = v.get("rth_ja")
        rjc = v.get("rth_jc")
        rca = v.get("rth_ca")
        if p is None or p < 0 or ta is None:
            return {}
        # Prefer θ_JA when given; otherwise sum θ_JC + θ_CA.
        if rja is not None and rja > 0:
            theta_ja = rja
        elif rjc is not None and rjc > 0 and rca is not None and rca >= 0:
            theta_ja = rjc + rca
        else:
            return {}
        tj = ta + p * theta_ja
        out = {"tj": tj, "margin": 125.0 - tj}
        if rjc is not None and rjc > 0:
            out["tc"] = tj - p * rjc
        return out


class EmbeddedResistorCard(CalcCard):
    """IPC-2316 embedded planar PTF / Cu-Ni resistor.

    Resistance for a rectangular planar resistor:
        R = ρ_s · (L / W)
    where ρ_s is the sheet resistivity (Ω/sq) of the resistive layer.

    Typical Ω/sq values:
        • Polymer thick-film (PTF) inks (DuPont, Asahi):
            10, 100, 1k, 10k Ω/sq
        • Subtractive Cu-Ni foil (Ohmega-Ply):
            25, 50, 100, 250 Ω/sq

    The L/W ratio is the resistor "squares" count — the only dimension
    that affects R for a given material.  Wider parts hit higher power
    ratings; longer parts hit higher resistance."""

    def __init__(self):
        super().__init__("Embedded planar resistor (IPC-2316)", [
            Field("rho_s", "Sheet ρ_s", "Ω/sq"),
            Field("L_mil", "Length L",  "mil"),
            Field("W_mil", "Width W",   "mil"),
            Field("squares", "L/W (squares)", "",  is_output=True),
            Field("R_ohm",   "Resistance R",  "Ω", is_output=True),
        ])
        self.fields["rho_s"].edit.setToolTip(
            "Sheet resistivity of the resistive layer.  PTF inks: "
            "10/100/1k/10k Ω/sq.  Cu-Ni foil: 25/50/100/250 Ω/sq.")

    def make_diagram(self):
        return EmbeddedResistorDiagram()

    def compute(self, driver, v):
        rho_s = v.get("rho_s"); L = v.get("L_mil"); W = v.get("W_mil")
        if rho_s is None or L is None or W is None:
            return {}
        if rho_s <= 0 or L <= 0 or W <= 0:
            return {}
        squares = L / W
        R = rho_s * squares
        return {"squares": squares, "R_ohm": R}


# AWG ampacity table.  Source: PowerStream / NEC handbook 75 °C
# insulation (single conductor in free air for "chassis", bundled for
# "power transmission").  Negative AWG entries cover the multi-zero
# gauges: -3 = 4/0, -2 = 3/0, -1 = 2/0, 0 = 1/0.
_AWG_AMPACITY = {
    -3: (380.0, 302.0), -2: (328.0, 239.0), -1: (283.0, 190.0),
     0: (245.0, 150.0),  1: (211.0, 119.0),  2: (181.0,  95.0),
     4: (135.0,  60.0),  6: (101.0,  37.0),  8: ( 73.0,  24.0),
    10: ( 55.0,  15.0), 12: ( 41.0,   9.3), 14: ( 32.0,   5.9),
    16: ( 22.0,   3.7), 18: ( 16.0,   2.3), 20: ( 11.0,   1.46),
    22: (  7.0,   0.92),24: (  3.5,   0.577), 26: (2.2,    0.36),
    28: (  1.4,   0.226), 30: (0.86,   0.142),
}


def _parse_awg(text):
    """Accept 4/0, 0000, 0, 12, etc. and return the canonical integer
    AWG value used by the diameter formula.  4/0 → -3, 0000 → -3,
    000 → -2, 00 → -1, 0 → 0, plain integer → itself.  Returns None
    on garbage."""
    s = (text or "").strip()
    if not s:
        return None
    if "/" in s:
        try:
            n_str, _ = s.split("/", 1)
            return -int(n_str) + 1   # 4/0 → -3, 3/0 → -2, …
        except ValueError:
            return None
    if all(ch == "0" for ch in s):
        return -(len(s) - 1)         # 0 → 0, 00 → -1, 000 → -2, 0000 → -3
    try:
        return int(float(s))
    except ValueError:
        return None


class WireGaugeCard(CalcCard):
    """AWG ↔ diameter, resistance, ampacity, voltage drop.

        d_in  = 0.005 · 92^((36 − AWG) / 39)
        R/L   = ρ_Cu / A      ρ_Cu @ 20 °C = 1.724·10⁻⁸ Ω·m

    AWG accepts integer values, multi-zero shorthand (0000 / 4/0),
    and the slash form (4/0 / 3/0 / 2/0 / 1/0)."""

    RHO_CU = 1.724e-8       # Ω·m

    def __init__(self):
        super().__init__("Wire gauge (AWG)", [
            Field("awg",            "AWG",                 ""),
            Field("d_in",           "Diameter",            "in", is_output=True),
            Field("d_mm",           "Diameter",            "mm", is_output=True),
            Field("ohms_per_kft",   "Ω / 1000 ft",         "Ω",  is_output=True),
            Field("length_ft",      "Length",              "ft"),
            Field("load_a",         "Load current",        "A"),
            Field("v_drop",         "Voltage drop",        "V",  is_output=True),
            Field("max_a_chassis",  "Max amps (chassis)",  "A",  is_output=True),
            Field("max_a_power",    "Max amps (power tx)", "A",  is_output=True),
        ])
        self.fields["awg"].edit.setToolTip(
            "Enter an AWG integer.  Multi-zero shorthand also works: "
            "4/0 (= 0000), 3/0, 2/0, 1/0.")
        self.fields["awg"].edit.setPlaceholderText("e.g. 12, 4/0, 0000")

    def compute(self, driver, v):
        awg = _parse_awg(self.fields["awg"].edit.text())
        if awg is None:
            return {}
        d_in = 0.005 * 92 ** ((36 - awg) / 39)
        d_mm = d_in * 25.4
        # Resistance per 1000 ft.  A in m² (d in metres).
        d_m = d_in * 0.0254
        area_m2 = pi * (d_m / 2) ** 2
        ohms_per_m = self.RHO_CU / area_m2
        ohms_per_kft = ohms_per_m * 304.8       # 1000 ft → m
        out = {"d_in": d_in, "d_mm": d_mm, "ohms_per_kft": ohms_per_kft}
        # Voltage drop = 2 · L · I · R/m  (round-trip, so factor 2)
        L_ft = v.get("length_ft"); I = v.get("load_a")
        if L_ft is not None and I is not None and L_ft > 0 and I > 0:
            out["v_drop"] = 2.0 * L_ft * 0.3048 * I * ohms_per_m
        # Ampacity from the lookup table — interpolate to the nearest
        # listed AWG so non-table values still get a rough number.
        if awg in _AWG_AMPACITY:
            chassis, power = _AWG_AMPACITY[awg]
        else:
            keys = sorted(_AWG_AMPACITY.keys())
            # Clamp to table edges
            k = min(keys, key=lambda x: abs(x - awg))
            chassis, power = _AWG_AMPACITY[k]
        out["max_a_chassis"] = chassis
        out["max_a_power"]   = power
        return out


class ViaCharacteristicsCard(CalcCard):
    """Plated-through-hole via electrical characteristics.

    Geometry (all dimensions in mils):
        D_via       drill hole diameter
        D_pad       internal pad diameter (copper landing)
        D_anti      reference-plane opening (antipad clearance)
        H           via height (board thickness through the hole)
        T_plate     plating thickness on the barrel wall

    Closed-form approximations used (Howard Johnson / IPC-style):
        L  (nH)  = 5.08·H_in·(ln(4·H/D_via) + 1)
        C  (pF)  = 1.41·εr·H_in·D_pad / (D_anti − D_pad)
        Z  (Ω)   = √(L / C)
        f_res    = 1 / (2π·√(L·C))
        t_step   = 1.1·√(L·C)            (10–90 % rise on a Z₀=Z line)
        A_cu     = π·T_plate·(D_via + T_plate)   sq.mils
        R_dc     = ρ_Cu · H / A_cu
        I_max    = 0.048·ΔT^0.44 · A_cu^0.725    (IPC-2221, external)
        P_diss   = I_max² · R_dc"""

    RHO_CU = 1.724e-8     # Ω·m

    def __init__(self):
        super().__init__("Via characteristics (plated through-hole)", [
            Field("d_via",  "Via hole diameter D_via",     "mil"),
            Field("d_pad",  "Internal pad diameter D_pad", "mil"),
            Field("d_anti", "Ref plane opening D_anti",    "mil"),
            Field("h",      "Via height H",                "mil"),
            Field("t_plate","Plating thickness T",         "mil"),
            Field("er",     "Substrate ε_r",               ""),
            Field("dt",     "ΔT for I_max",                "°C"),
            Field("a_sqmil","Conductor cross-section",     "sq.mil", is_output=True),
            Field("l_nh",   "Inductance L",                "nH",     is_output=True),
            Field("c_pf",   "Capacitance C",               "pF",     is_output=True),
            Field("z_ohm",  "Via impedance Z",             "Ω",      is_output=True),
            Field("fres_mhz","Resonant frequency",         "MHz",    is_output=True),
            Field("tstep_ps","Step-response t_rise",       "ps",     is_output=True),
            Field("r_ohm",  "DC resistance",               "Ω",      is_output=True),
            Field("i_max",  "Max current I",               "A",      is_output=True),
            Field("p_w",    "Power dissipation P=I²R",     "W",      is_output=True),
        ])
        # Reasonable defaults match the Saturn-toolkit screenshot so the
        # card produces non-empty results out of the box.
        self.fields["er"].edit.setPlaceholderText("4.4 (FR-4)")
        self.fields["dt"].edit.setPlaceholderText("10")

    def make_diagram(self):
        return ViaDiagram()

    def compute(self, driver, v):
        d_via = v.get("d_via")
        d_pad = v.get("d_pad")
        d_anti = v.get("d_anti")
        H = v.get("h")
        T = v.get("t_plate")
        er = v.get("er") or 4.4
        dT = v.get("dt") or 10.0
        if None in (d_via, d_pad, d_anti, H, T):
            return {}
        if d_via <= 0 or d_pad <= 0 or d_anti <= 0 or H <= 0 or T <= 0:
            return {}
        if d_anti <= d_pad:
            return {}
        # Conductor cross-section: plating wall as a thin annulus.
        # Saturn's convention: A = π·T·(D_via + T)  [plating outside drill]
        a_sqmil = pi * T * (d_via + T)
        # Inductance (Howard Johnson): H, D in inches.
        H_in = H / 1000.0
        d_in = d_via / 1000.0
        l_nh = 5.08 * H_in * (log(4.0 * H_in / d_in) + 1.0)
        # Capacitance (parallel-plate via model, H in inches).
        c_pf = 1.41 * er * H_in * d_pad / (d_anti - d_pad)
        # Derived AC parameters
        out = {
            "a_sqmil": a_sqmil,
            "l_nh":    l_nh,
            "c_pf":    c_pf,
        }
        if l_nh > 0 and c_pf > 0:
            L = l_nh * 1e-9
            C = c_pf * 1e-12
            z = sqrt(L / C)
            fres = 1.0 / (2.0 * pi * sqrt(L * C))
            tstep = 1.1 * sqrt(L * C)        # seconds
            out["z_ohm"]    = z
            out["fres_mhz"] = fres / 1e6
            out["tstep_ps"] = tstep * 1e12
        # DC resistance: convert H (mils → m), A (sq.mils → m²).
        h_m = H * 2.54e-5
        a_m2 = a_sqmil * (2.54e-5) ** 2
        if a_m2 > 0:
            r_dc = self.RHO_CU * h_m / a_m2
            out["r_ohm"] = r_dc
            # IPC-2221 external-trace ampacity formula.
            i_max = 0.048 * (dT ** 0.44) * (a_sqmil ** 0.725)
            out["i_max"] = i_max
            out["p_w"]   = i_max * i_max * r_dc
        return out


# IPC-2221B Table 6-1.  Each tuple is the spacing in millimetres for
# a voltage cell, indexed in this order: (B1, B2, B3, B4, A5, A6, A7).
# Above 500 V the spacing scales linearly per volt — the second list is
# the (mm-per-V) coefficient added to the 500 V row entry.
_IPC2221_BANDS = [
    # (max_voltage, [B1, B2, B3, B4, A5, A6, A7])
    (15,  [0.05, 0.10, 0.05, 0.05, 0.10, 0.13, 0.13]),
    (30,  [0.05, 0.10, 0.05, 0.05, 0.10, 0.13, 0.13]),
    (50,  [0.10, 0.60, 0.40, 0.13, 0.13, 0.40, 0.13]),
    (100, [0.10, 0.60, 0.50, 0.13, 0.13, 0.50, 0.13]),
    (150, [0.20, 0.60, 0.60, 0.40, 0.40, 0.80, 0.40]),
    (170, [0.20, 1.25, 1.25, 0.40, 0.40, 0.80, 0.40]),
    (250, [0.20, 1.25, 1.25, 0.40, 0.40, 0.80, 0.40]),
    (300, [0.20, 1.25, 1.25, 0.40, 0.40, 0.80, 0.80]),
    (500, [0.25, 2.50, 2.50, 0.80, 0.80, 1.50, 0.80]),
]
_IPC2221_PER_V = [0.0025, 0.0050, 0.0050, 0.00305, 0.00305, 0.00305, 0.00305]


def _ipc2221_spacing_mm(voltage_v, type_idx):
    """IPC-2221B minimum-conductor spacing, in millimetres.
    `type_idx` is 0..6 mapping to B1, B2, B3, B4, A5, A6, A7."""
    if voltage_v is None or voltage_v < 0:
        return None
    if voltage_v <= 500:
        for cap_v, row in _IPC2221_BANDS:
            if voltage_v <= cap_v:
                return row[type_idx]
        return _IPC2221_BANDS[-1][1][type_idx]
    # Above 500 V — linear extrapolation per IPC-2221B.
    base = _IPC2221_BANDS[-1][1][type_idx]
    return base + (voltage_v - 500) * _IPC2221_PER_V[type_idx]


class MinSpacingCard(CalcCard):
    """IPC-2221B minimum conductor spacing.

    The output is the spacing required between two conductors carrying
    the entered DC bias for the chosen device class:

        B1  Internal conductors
        B2  External, uncoated, ≤ 3050 m altitude
        B3  External, uncoated, > 3050 m altitude
        B4  External with permanent polymer coating (any altitude)
        A5  External with conformal coating over assembly
        A6  Component lead / termination, uncoated
        A7  Component lead / termination, with conformal coating

    Above 500 V the standard scales linearly with voltage."""

    TYPES = ("B1", "B2", "B3", "B4", "A5", "A6", "A7")
    TYPE_DESCRIPTIONS = (
        "B1  Internal conductors",
        "B2  External, uncoated, ≤ 3050 m",
        "B3  External, uncoated, > 3050 m",
        "B4  External, polymer-coated",
        "A5  Conformal coating over assembly",
        "A6  Component lead, uncoated",
        "A7  Component lead, conformal coated",
    )

    def __init__(self):
        super().__init__("Minimum conductor spacing (IPC-2221B)", [
            Field("voltage_v",     "DC bias",       "V"),
            Field("spacing_mm",    "Spacing",       "mm",  is_output=True),
            Field("spacing_mil",   "Spacing",       "mil", is_output=True),
        ])
        self._type_idx = 0   # default = B1

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Type:"))
        self._type_combo = QComboBox()
        for desc in self.TYPE_DESCRIPTIONS:
            self._type_combo.addItem(desc)
        self._type_combo.setMinimumWidth(220)
        self._type_combo.setMaximumHeight(20)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        h.addWidget(self._type_combo)
        h.addStretch(1)
        return w

    def _on_type_changed(self, idx):
        self._type_idx = max(0, idx)
        self.recompute_from_inputs()

    def compute(self, driver, v):
        V = v.get("voltage_v")
        mm = _ipc2221_spacing_mm(V, self._type_idx)
        if mm is None:
            return {}
        return {"spacing_mm": mm, "spacing_mil": mm / 0.0254}


# Standard wire-gauge / letter / fractional drill sizes.  Subset of
# the full chart — the most-used gauges + fractional drills up to 1/2".
_DRILL_CHART = [
    # (label, dia_inch)
    ("80",     0.0135), ("79",     0.0145), ("78",     0.0160),
    ("77",     0.0180), ("76",     0.0200), ("75",     0.0210),
    ("74",     0.0225), ("73",     0.0240), ("72",     0.0250),
    ("71",     0.0260), ("70",     0.0280), ("69",     0.0292),
    ("68",     0.0310), ("67",     0.0320), ("66",     0.0330),
    ("65",     0.0350), ("64",     0.0360), ("63",     0.0370),
    ("62",     0.0380), ("61",     0.0390), ("60",     0.0400),
    ("59",     0.0410), ("58",     0.0420), ("57",     0.0430),
    ("56",     0.0465), ("1/16\"", 0.0625), ("55",     0.0520),
    ("54",     0.0550), ("53",     0.0595), ("52",     0.0635),
    ("51",     0.0670), ("50",     0.0700), ("49",     0.0730),
    ("48",     0.0760), ("5/64\"", 0.0781), ("47",     0.0785),
    ("46",     0.0810), ("45",     0.0820), ("44",     0.0860),
    ("43",     0.0890), ("42",     0.0935), ("3/32\"", 0.0938),
    ("41",     0.0960), ("40",     0.0980), ("39",     0.0995),
    ("38",     0.1015), ("37",     0.1040), ("36",     0.1065),
    ("7/64\"", 0.1094), ("35",     0.1100), ("34",     0.1110),
    ("33",     0.1130), ("32",     0.1160), ("31",     0.1200),
    ("1/8\"",  0.1250), ("30",     0.1285), ("29",     0.1360),
    ("28",     0.1405), ("9/64\"", 0.1406), ("27",     0.1440),
    ("26",     0.1470), ("25",     0.1495), ("24",     0.1520),
    ("23",     0.1540), ("5/32\"", 0.1563), ("22",     0.1570),
    ("21",     0.1590), ("20",     0.1610), ("19",     0.1660),
    ("18",     0.1695), ("11/64\"",0.1719), ("17",     0.1730),
    ("16",     0.1770), ("15",     0.1800), ("14",     0.1820),
    ("13",     0.1850), ("3/16\"", 0.1875), ("12",     0.1890),
    ("11",     0.1910), ("10",     0.1935), ("9",      0.1960),
    ("8",      0.1990), ("7",      0.2010), ("13/64\"",0.2031),
    ("6",      0.2040), ("5",      0.2055), ("4",      0.2090),
    ("3",      0.2130), ("7/32\"", 0.2188), ("2",      0.2210),
    ("1",      0.2280), ("A",      0.2340), ("15/64\"",0.2344),
    ("B",      0.2380), ("C",      0.2420), ("D",      0.2460),
    ("E",      0.2500), ("1/4\"",  0.2500), ("F",      0.2570),
    ("G",      0.2610), ("17/64\"",0.2656), ("H",      0.2660),
    ("I",      0.2720), ("J",      0.2770), ("K",      0.2810),
    ("9/32\"", 0.2813), ("L",      0.2900), ("M",      0.2950),
    ("19/64\"",0.2969), ("N",      0.3020), ("5/16\"", 0.3125),
    ("O",      0.3160), ("P",      0.3230), ("21/64\"",0.3281),
    ("Q",      0.3320), ("R",      0.3390), ("11/32\"",0.3438),
    ("S",      0.3480), ("T",      0.3580), ("23/64\"",0.3594),
    ("U",      0.3680), ("3/8\"",  0.3750), ("V",      0.3770),
    ("W",      0.3860), ("25/64\"",0.3906), ("X",      0.3970),
    ("Y",      0.4040), ("13/32\"",0.4063), ("Z",      0.4130),
    ("27/64\"",0.4219), ("7/16\"", 0.4375), ("29/64\"",0.4531),
    ("15/32\"",0.4688), ("31/64\"",0.4844), ("1/2\"",  0.5000),
]


class DrillChartTable(QWidget):
    """Read-only reference table — drill designation, inches, mm.
    Used as the diagram on the DrillChartCard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        cap = QLabel("Drill chart")
        cap.setStyleSheet("color:#555; font-weight:bold;")
        outer.addWidget(cap)
        self.table = QTableWidget(len(_DRILL_CHART), 3, self)
        self.table.setHorizontalHeaderLabels(["Drill", "in", "mm"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(16)
        self.table.verticalHeader().setMinimumSectionSize(16)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        for r, (label, d_in) in enumerate(_DRILL_CHART):
            it = QTableWidgetItem(label);  it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 0, it)
            it = QTableWidgetItem(f"{d_in:.4f}");  it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 1, it)
            it = QTableWidgetItem(f"{d_in*25.4:.3f}"); it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, 2, it)
        hdr = self.table.horizontalHeader()
        for c in range(3):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.setMaximumHeight(280)
        outer.addWidget(self.table)


class DrillChartCard(CalcCard):
    """Quick lookup tool: enter a target diameter (in or mm) and the
    card highlights the closest drill size in the side table."""

    def __init__(self):
        super().__init__("Drill-chart lookup", [
            Field("target_in", "Target Ø (in)",  "in"),
            Field("target_mm", "Target Ø (mm)",  "mm"),
            Field("drill",     "Closest drill", "",  is_output=True),
            Field("actual_in", "Actual Ø (in)", "in", is_output=True),
            Field("actual_mm", "Actual Ø (mm)", "mm", is_output=True),
        ])

    def make_diagram(self):
        self._chart = DrillChartTable()
        return self._chart

    def compute(self, driver, v):
        # Whichever input the user typed into wins; the other follows.
        if driver == "target_in":
            target_in = v.get("target_in")
            if target_in is None: return {}
            target_mm = target_in * 25.4
        elif driver == "target_mm":
            target_mm = v.get("target_mm")
            if target_mm is None: return {}
            target_in = target_mm / 25.4
        else:
            target_in = v.get("target_in")
            target_mm = v.get("target_mm")
            if target_in is None and target_mm is None:
                return {}
            if target_in is None:
                target_in = target_mm / 25.4
            elif target_mm is None:
                target_mm = target_in * 25.4
        # Closest table row by diameter (inches).
        best_idx, best_diff = 0, float("inf")
        for i, (_, d_in) in enumerate(_DRILL_CHART):
            diff = abs(d_in - target_in)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        label, d_in = _DRILL_CHART[best_idx]
        # Highlight the matched row in the side table.
        if hasattr(self, "_chart"):
            self._chart.table.selectRow(best_idx)
            self._chart.table.scrollToItem(
                self._chart.table.item(best_idx, 0),
                QAbstractItemView.PositionAtCenter,
            )
        return {
            "target_mm": target_mm,
            "target_in": target_in,
            "drill":     label,
            "actual_in": d_in,
            "actual_mm": d_in * 25.4,
        }


# ====================================================================
#  Batch 2 cards — analog/op-amp, power supply, mechanical beam, DSP
# ====================================================================

class OpAmpNoiseCard(CalcCard):
    """Output-referred RMS noise for an op-amp + source-impedance pair.

    Inputs (all RTI — referred to op-amp input):
      • e_n   – voltage-noise density                (nV/√Hz)
      • i_n   – current-noise density                (pA/√Hz)
      • R_s   – Thevenin source resistance           (Ω)
      • G     – closed-loop noise gain  (NG = 1 + Rf/Rg for non-inv)
      • BW    – signal bandwidth                     (Hz, single-pole −3 dB)

    Outputs:
      • Johnson-noise density of R_s             (nV/√Hz, white)
      • Total input-referred noise density       (nV/√Hz, RSS)
      • Output RMS noise                         (μV)

    The output RMS uses the standard single-pole noise-equivalent
    bandwidth NEB = π/2 · BW, which is the right factor for any
    single-real-pole roll-off (≈1.57 × the −3 dB BW)."""

    _K_BOLTZ = 1.380649e-23
    _T_REF   = 290.0   # noise temperature

    def __init__(self):
        super().__init__("Op-amp input-referred noise → output RMS", [
            Field("e_n",       "e_n  input voltage noise",   "nV/√Hz"),
            Field("i_n",       "i_n  input current noise",   "pA/√Hz"),
            Field("rs",        "R_s  source resistance",     "Ω"),
            Field("gain",      "Noise gain  NG = 1 + Rf/Rg", "V/V"),
            Field("bw_hz",     "Signal bandwidth (−3 dB)",   "Hz"),
            Field("vn_rs",     "Johnson noise of R_s",       "nV/√Hz",
                  is_output=True),
            Field("vn_rti",    "Total RTI noise density",    "nV/√Hz",
                  is_output=True),
            Field("vn_out_uv", "Output RMS noise",           "μV",
                  is_output=True),
        ])
        self.fields["e_n"].edit.setText("4.5")        # OPA192-class
        self.fields["i_n"].edit.setText("0.05")
        self.fields["rs"].edit.setText("1000")
        self.fields["gain"].edit.setText("10")
        self.fields["bw_hz"].edit.setText("100000")
        self.recompute_from_inputs()

    def compute(self, driver, v):
        en  = v.get("e_n")     # nV/√Hz
        inn = v.get("i_n")     # pA/√Hz
        rs  = v.get("rs")
        ng  = v.get("gain")
        bw  = v.get("bw_hz")
        out = {}
        if rs is not None and rs >= 0:
            # 4kTR is in V²/Hz; sqrt → V/√Hz; ×1e9 → nV/√Hz
            v_johnson_nv = (4.0 * self._K_BOLTZ * self._T_REF * rs) ** 0.5 * 1e9
            out["vn_rs"] = v_johnson_nv
        else:
            v_johnson_nv = 0.0
        if en is None: return out
        e_v   = en  * 1e-9          # V/√Hz
        i_a   = (inn or 0.0) * 1e-12  # A/√Hz
        vir_v = e_v
        vir_v = (vir_v * vir_v
                 + (i_a * (rs or 0.0)) ** 2
                 + (v_johnson_nv * 1e-9) ** 2) ** 0.5
        out["vn_rti"] = vir_v * 1e9
        if bw is not None and bw > 0 and ng is not None and ng > 0:
            neb = 1.5707963 * bw  # π/2 · BW for single real pole
            vout_rms = vir_v * (neb ** 0.5) * ng
            out["vn_out_uv"] = vout_rms * 1e6
        return out


class OpAmpGBWCard(CalcCard):
    """Op-amp small-signal BW, slew limit, and settling time.

    Inputs:
      • GBW              – gain-bandwidth product   (MHz)
      • SR               – slew rate                (V/μs)
      • G                – closed-loop gain         (V/V)
      • V_step           – output step amplitude    (V)
      • Settle tolerance – e.g. 0.1 for 0.1 %       (%)

    Outputs:
      • Closed-loop −3 dB bandwidth        BW = GBW / G  (MHz)
      • Full-power bandwidth at V_step     FPBW = SR / (π · V_step)
      • Slew time for the step             t_slew = V_step / SR  (μs)
      • Small-signal settling to tol       τ · ln(100/tol)        (μs)
      • Total settling (slew + linear)     (μs)"""

    def __init__(self):
        super().__init__(
            "Op-amp GBW / slew / settling time", [
                Field("gbw_mhz",   "GBW product",              "MHz"),
                Field("sr_vus",    "Slew rate",                "V/μs"),
                Field("gain",      "Closed-loop gain",         "V/V"),
                Field("vstep",     "Output step amplitude",    "V"),
                Field("tol_pct",   "Settling tolerance",       "%"),
                Field("bw_mhz",    "Closed-loop −3 dB BW",     "MHz",
                      is_output=True),
                Field("fpbw_mhz",  "Full-power BW @ V_step",   "MHz",
                      is_output=True),
                Field("t_slew_us", "Slew time for step",       "μs",
                      is_output=True),
                Field("t_lin_us",  "Linear settling to tol",   "μs",
                      is_output=True),
                Field("t_tot_us",  "Total settling",           "μs",
                      is_output=True),
            ])
        self.fields["gbw_mhz"].edit.setText("10")
        self.fields["sr_vus"].edit.setText("20")
        self.fields["gain"].edit.setText("10")
        self.fields["vstep"].edit.setText("1")
        self.fields["tol_pct"].edit.setText("0.1")
        self.recompute_from_inputs()

    def compute(self, driver, v):
        gbw  = v.get("gbw_mhz")
        sr   = v.get("sr_vus")
        gain = v.get("gain")
        vs   = v.get("vstep")
        tol  = v.get("tol_pct")
        out = {}
        bw_mhz = None
        if gbw is not None and gain is not None and gbw > 0 and gain > 0:
            bw_mhz = gbw / gain
            out["bw_mhz"] = bw_mhz
        if sr is not None and sr > 0 and vs is not None and vs > 0:
            # FPBW (V·s scaling so we land back in MHz with V/μs and V):
            #   SR [V/μs] / (π · V_pp [V])  →  MHz
            out["fpbw_mhz"] = sr / (3.14159265 * vs)
            out["t_slew_us"] = vs / sr
        if bw_mhz is not None and bw_mhz > 0 and tol is not None and tol > 0:
            tau_us = 1.0 / (2.0 * 3.14159265 * bw_mhz)  # μs (since BW in MHz)
            # Linear settling to fraction (tol/100):
            #   t = τ · ln(100/tol)
            import math as _m
            t_lin = tau_us * _m.log(100.0 / tol)
            out["t_lin_us"] = t_lin
            if "t_slew_us" in out:
                out["t_tot_us"] = out["t_slew_us"] + t_lin
            else:
                out["t_tot_us"] = t_lin
        return out


class BeamDeflectionCard(CalcCard):
    """Beam deflection / max stress for common load cases.

    Pick a configuration (combobox above the inputs):
      • Cantilever — tip point load P
      • Cantilever — uniform load w
      • Simply-supported — center point load P
      • Simply-supported — uniform load w

    Internally uses SI base units (m, N, Pa).  Material E is entered in
    GPa, section I in mm⁴, length in mm, loads in N (point) or N/m
    (uniform). Section modulus S (mm³) is optional — if supplied, max
    bending stress is reported as well.

    Formulas:
      • Cantilever, P at tip      δ = PL³/(3EI)        M_max = PL
      • Cantilever, UDL w         δ = wL⁴/(8EI)        M_max = wL²/2
      • SS, P at center           δ = PL³/(48EI)       M_max = PL/4
      • SS, UDL w                 δ = 5wL⁴/(384EI)     M_max = wL²/8
    """

    CONFIGS = [
        ("Cantilever — tip point load P",       "cant_pt"),
        ("Cantilever — uniform load w",          "cant_udl"),
        ("Simply-supported — center point P",    "ss_pt"),
        ("Simply-supported — uniform load w",    "ss_udl"),
    ]

    def __init__(self):
        super().__init__("Beam deflection / max moment / max stress", [
            Field("L_mm",     "L  length",            "mm"),
            Field("E_gpa",    "E  Young's modulus",   "GPa"),
            Field("I_mm4",    "I  area moment",       "mm⁴"),
            Field("S_mm3",    "S  section modulus",   "mm³"),
            Field("load",     "Load  (P in N or w in N/m)", ""),
            Field("delta_mm", "δ  max deflection",    "mm",
                  is_output=True),
            Field("M_nm",     "M  max moment",        "N·m",
                  is_output=True),
            Field("sigma_mpa","σ  max bending stress","MPa",
                  is_output=True),
        ])
        self._config_key = "cant_pt"
        self._config_combo = None
        self.fields["L_mm"].edit.setText("100")
        self.fields["E_gpa"].edit.setText("200")   # mild steel
        self.fields["I_mm4"].edit.setText("417")   # 10x10 mm bar = bh³/12
        self.fields["S_mm3"].edit.setText("167")   # 10x10 = bh²/6
        self.fields["load"].edit.setText("100")
        self.recompute_from_inputs()

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Configuration:"))
        c = QComboBox()
        for label, key in self.CONFIGS:
            c.addItem(label, key)
        c.setMaximumHeight(20)
        c.currentIndexChanged.connect(self._on_config_changed)
        self._config_combo = c
        h.addWidget(c, 1)
        return w

    def _on_config_changed(self, idx):
        if 0 <= idx < len(self.CONFIGS):
            self._config_key = self.CONFIGS[idx][1]
            self.recompute_from_inputs()

    def get_card_state(self):
        st = super().get_card_state()
        st["beam_config"] = self._config_key
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if isinstance(state, dict) and self._config_combo is not None:
            key = state.get("beam_config")
            for i, (_, k) in enumerate(self.CONFIGS):
                if k == key:
                    self._config_combo.setCurrentIndex(i)
                    self._config_key = k
                    break

    def compute(self, driver, v):
        L_mm = v.get("L_mm")
        E_gpa = v.get("E_gpa")
        I_mm4 = v.get("I_mm4")
        S_mm3 = v.get("S_mm3")
        load  = v.get("load")
        if (L_mm is None or E_gpa is None or I_mm4 is None or load is None
                or L_mm <= 0 or E_gpa <= 0 or I_mm4 <= 0):
            return {}
        L = L_mm * 1e-3       # m
        E = E_gpa * 1e9        # Pa
        I = I_mm4 * 1e-12      # m⁴
        EI = E * I             # N·m²
        k = self._config_key
        if k == "cant_pt":
            P = load
            delta = P * L**3 / (3.0 * EI)
            Mmax  = P * L
        elif k == "cant_udl":
            w = load
            delta = w * L**4 / (8.0 * EI)
            Mmax  = w * L * L / 2.0
        elif k == "ss_pt":
            P = load
            delta = P * L**3 / (48.0 * EI)
            Mmax  = P * L / 4.0
        elif k == "ss_udl":
            w = load
            delta = 5.0 * w * L**4 / (384.0 * EI)
            Mmax  = w * L * L / 8.0
        else:
            return {}
        out = {"delta_mm": delta * 1e3, "M_nm": Mmax}
        if S_mm3 is not None and S_mm3 > 0:
            # σ = M / S; M in N·m → N·mm = M·1e3; σ [N/mm² = MPa] = M_nmm / S_mm3
            out["sigma_mpa"] = (Mmax * 1e3) / S_mm3
        return out


class LEDCurrentLimiterCard(CalcCard):
    """Series-resistor LED driver.  Picks the nearest E24/E96 part and
    reports power dissipation so you don't burn the resistor.

        R = (V_supply − N · V_f) / I_f
        P_R = I_f² · R
        P_LED_each = V_f · I_f

    A warning is implied (headroom output goes negative) when the supply
    can't drive the requested current at the chosen V_f and N."""

    def __init__(self):
        super().__init__("LED current limiter (series resistor)", [
            Field("vs",         "V_supply",                   "V"),
            Field("vf",         "V_f per LED",                "V"),
            Field("n",          "N  LEDs in series",          ""),
            Field("if_ma",      "I_f  forward current",       "mA"),
            Field("r_ohm",      "R  series resistor (calc)",  "Ω",
                  is_output=True),
            Field("r_e24",      "Nearest E24 value",          "Ω",
                  is_output=True),
            Field("r_e96",      "Nearest E96 value",          "Ω",
                  is_output=True),
            Field("p_r_mw",     "P_R  resistor dissipation",  "mW",
                  is_output=True),
            Field("p_led_mw",   "P_LED  per LED",             "mW",
                  is_output=True),
            Field("headroom_v", "Headroom  V_s − N·V_f",      "V",
                  is_output=True),
        ])
        self.fields["vs"].edit.setText("5")
        self.fields["vf"].edit.setText("2.1")
        self.fields["n"].edit.setText("1")
        self.fields["if_ma"].edit.setText("20")
        self.recompute_from_inputs()

    @staticmethod
    def _nearest_eia(target, series):
        if target <= 0: return None
        import math as _m
        # Pick decade
        decade = _m.floor(_m.log10(target))
        candidates = [v * 10.0**decade for v in series]
        candidates += [v * 10.0**(decade+1) for v in series]
        candidates += [v * 10.0**(decade-1) for v in series]
        return min(candidates, key=lambda x: abs(_m.log10(x) - _m.log10(target)))

    _E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
            3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]

    @property
    def _E96(self):
        # Built once and cached on the class
        if not hasattr(type(self), "_E96_CACHE"):
            import math as _m
            type(self)._E96_CACHE = [
                round(10 ** (i / 96.0), 2) for i in range(96)
            ]
        return type(self)._E96_CACHE

    def compute(self, driver, v):
        vs = v.get("vs")
        vf = v.get("vf")
        n  = v.get("n")
        if_ma = v.get("if_ma")
        out = {}
        if (vs is None or vf is None or n is None or if_ma is None
                or n <= 0 or if_ma <= 0):
            return out
        n_int = max(1, int(round(n)))
        headroom = vs - n_int * vf
        out["headroom_v"] = headroom
        if headroom <= 0:
            # Can't drive — emit zeros so the user sees the headroom warning
            out["r_ohm"] = 0.0
            return out
        i_a = if_ma * 1e-3
        r_ohm = headroom / i_a
        out["r_ohm"] = r_ohm
        e24_val = self._nearest_eia(r_ohm, self._E24)
        e96_val = self._nearest_eia(r_ohm, self._E96)
        if e24_val is not None: out["r_e24"] = e24_val
        if e96_val is not None: out["r_e96"] = e96_val
        out["p_r_mw"]  = i_a * i_a * r_ohm * 1e3
        out["p_led_mw"] = vf * i_a * 1e3
        return out


class BatteryRuntimeCard(CalcCard):
    """Battery runtime / energy / charge time.

    Inputs:
      • Capacity  – cell or pack capacity            (mAh)
      • Voltage   – nominal terminal voltage         (V)
      • I_load    – steady draw, OR P_load (W)       (mA)
      • DoD       – usable depth-of-discharge        (%, default 80)
      • I_charge  – constant charge current          (mA)

    Outputs:
      • Energy    – capacity · voltage               (Wh)
      • Runtime   – Capacity·DoD / I_load            (hours)
      • Charge t  – Capacity / I_charge              (hours)

    Power-driven runtime is computed when P_load is supplied (Wh / W)."""

    def __init__(self):
        super().__init__("Battery runtime / energy / charge time", [
            Field("cap_mah",  "Capacity",                "mAh"),
            Field("v_nom",    "Nominal voltage",         "V"),
            Field("dod_pct",  "Usable DoD",              "%"),
            Field("i_load",   "Load current",            "mA"),
            Field("p_load",   "Load power (optional)",   "W"),
            Field("i_chg",    "Charge current",          "mA"),
            Field("energy_wh","Energy",                  "Wh",
                  is_output=True),
            Field("run_hr",   "Runtime",                 "h",
                  is_output=True),
            Field("run_days", "Runtime",                 "d",
                  is_output=True),
            Field("chg_hr",   "Charge time",             "h",
                  is_output=True),
        ])
        self.fields["cap_mah"].edit.setText("2000")
        self.fields["v_nom"].edit.setText("3.7")
        self.fields["dod_pct"].edit.setText("80")
        self.fields["i_load"].edit.setText("100")
        self.fields["i_chg"].edit.setText("500")
        self.recompute_from_inputs()

    def compute(self, driver, v):
        cap = v.get("cap_mah")
        vn  = v.get("v_nom")
        dod = v.get("dod_pct")
        il  = v.get("i_load")
        pl  = v.get("p_load")
        ic  = v.get("i_chg")
        out = {}
        if cap is None or cap <= 0 or vn is None or vn <= 0:
            return out
        cap_ah = cap * 1e-3
        wh = cap_ah * vn
        out["energy_wh"] = wh
        frac = ((dod or 100.0) / 100.0)
        usable_wh = wh * frac
        usable_ah = cap_ah * frac
        # Runtime — prefer current; fall back to power if no current given
        runtime_h = None
        if il is not None and il > 0:
            runtime_h = usable_ah / (il * 1e-3)
        elif pl is not None and pl > 0:
            runtime_h = usable_wh / pl
        if runtime_h is not None:
            out["run_hr"] = runtime_h
            out["run_days"] = runtime_h / 24.0
        if ic is not None and ic > 0:
            # Charge to 100 % of nameplate (ignore DoD); pessimistic estimate
            # without trickle-charge constant — divide by 0.9 for CV tail.
            out["chg_hr"] = cap_ah / (ic * 1e-3) / 0.9
        return out


class FilterDesignCard(CalcCard):
    """Analog filter order from a passband/stopband specification.

    Pick a topology (combobox).  Inputs are in Hz; the card calls
    scipy.signal's *ord helpers to compute the minimum order N and the
    natural frequency Wn that exactly meets the spec.  The pole count
    is N for LP/HP and 2·N for BP/BS — that pair is reported as
    "Components (LC)" because every pole costs one L + one C in a
    passive ladder."""

    TOPOLOGIES = [
        ("Butterworth — LPF",  "butter_lp"),
        ("Butterworth — HPF",  "butter_hp"),
        ("Chebyshev I — LPF",  "cheby1_lp"),
        ("Chebyshev I — HPF",  "cheby1_hp"),
        ("Bessel — LPF (3 dB)","bessel_lp"),
    ]

    def __init__(self):
        super().__init__("Filter design (order from spec, scipy.signal)", [
            Field("fp_hz",   "f_pass  passband edge",   "Hz"),
            Field("fs_hz",   "f_stop  stopband edge",   "Hz"),
            Field("rp_db",   "Passband ripple",         "dB"),
            Field("rs_db",   "Stopband attenuation",    "dB"),
            Field("order",   "Required order N",        "",
                  is_output=True),
            Field("wn_hz",   "Natural frequency W_n",   "Hz",
                  is_output=True),
            Field("poles",   "Pole count",              "",
                  is_output=True),
            Field("lc_count","Passive LC components",   "",
                  is_output=True),
        ])
        self._topology = "butter_lp"
        self._topology_combo = None
        self.fields["fp_hz"].edit.setText("1000")
        self.fields["fs_hz"].edit.setText("4000")
        self.fields["rp_db"].edit.setText("1")
        self.fields["rs_db"].edit.setText("40")
        self.recompute_from_inputs()

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(QLabel("Topology:"))
        c = QComboBox()
        for label, key in self.TOPOLOGIES:
            c.addItem(label, key)
        c.setMaximumHeight(20)
        c.currentIndexChanged.connect(self._on_topology_changed)
        self._topology_combo = c
        h.addWidget(c, 1)
        return w

    def _on_topology_changed(self, idx):
        if 0 <= idx < len(self.TOPOLOGIES):
            self._topology = self.TOPOLOGIES[idx][1]
            self.recompute_from_inputs()

    def get_card_state(self):
        st = super().get_card_state()
        st["filter_topology"] = self._topology
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if isinstance(state, dict) and self._topology_combo is not None:
            key = state.get("filter_topology")
            for i, (_, k) in enumerate(self.TOPOLOGIES):
                if k == key:
                    self._topology_combo.setCurrentIndex(i)
                    self._topology = k
                    break

    def compute(self, driver, v):
        fp = v.get("fp_hz")
        fs = v.get("fs_hz")
        rp = v.get("rp_db")
        rs = v.get("rs_db")
        if fp is None or fs is None or rp is None or rs is None:
            return {}
        if fp <= 0 or fs <= 0 or rp <= 0 or rs <= 0:
            return {}
        try:
            from scipy import signal as _sig
        except ImportError:
            return {}
        wp = 2.0 * 3.14159265 * fp
        ws = 2.0 * 3.14159265 * fs
        out = {}
        try:
            if self._topology == "butter_lp":
                N, Wn = _sig.buttord(wp, ws, rp, rs, analog=True)
            elif self._topology == "butter_hp":
                N, Wn = _sig.buttord(wp, ws, rp, rs, analog=True)
                # buttord doesn't care which side is which; the caller
                # supplies pass<stop for LP, pass>stop for HP. Convention:
                # for HP entries we keep fp/fs as written so the user
                # enters fp > fs and Wn comes back at fp roughly.
            elif self._topology == "cheby1_lp":
                N, Wn = _sig.cheb1ord(wp, ws, rp, rs, analog=True)
            elif self._topology == "cheby1_hp":
                N, Wn = _sig.cheb1ord(wp, ws, rp, rs, analog=True)
            elif self._topology == "bessel_lp":
                # No 'besselord' in scipy. Use the Butterworth lower bound
                # — Bessel needs more poles for the same attenuation than
                # Butterworth, so this is a lower bound rather than exact.
                N, Wn = _sig.buttord(wp, ws, rp, rs, analog=True)
            else:
                return {}
        except Exception:
            return {}
        # Wn returns in rad/s; convert back to Hz.
        wn_hz = Wn / (2.0 * 3.14159265)
        out["order"]  = float(N)
        out["wn_hz"]  = float(wn_hz)
        out["poles"]  = float(N)   # Lowpass / highpass: N poles
        out["lc_count"] = float(N)
        return out


class CalcTab(QWidget):
    """Multi-base calculator with history and unit-conversion popup."""
    HISTORY_MAX = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        # ---- input ----
        self.input = QLineEdit()
        self.input.setMinimumHeight(28)
        self.input.setFont(self._mono_font(13))
        self.input.installEventFilter(self)
        self.input.textEdited.connect(self._on_text_edited)
        self.input.returnPressed.connect(self._on_evaluate)
        outer.addWidget(self.input)

        # ---- "ans" pill: blue chip that appears inside the input when the
        # user types an operator immediately after a successful evaluate, so
        # `[Enter] / 2` reads as "ans / 2".  The chip is a child of the
        # QLineEdit, overlaid at the left edge; setTextMargins pushes the
        # caret past it.  When active, the evaluator prepends literal `ans`
        # to the typed text so the existing `_substitute_ans` path resolves
        # the previous result.
        self._ans_pill = QLabel("ans", self.input)
        self._ans_pill.setObjectName("ansPill")
        self._ans_pill.setCursor(Qt.PointingHandCursor)
        self._ans_pill.hide()
        self._ans_pill_active = False
        self._just_evaluated  = False
        self._apply_ans_pill_style()
        # Characters that, when typed first after Enter, summon the pill.
        # Includes the cosmetic '×' / '÷' glyphs the live renderer produces.
        self._ANS_TRIGGER_OPS = set("+-*/^%×÷")

        # ---- Intellisense (autocomplete) ----
        # Context of the completion currently on screen, so the activated
        # signal / CalcCompleter can rebuild the replacement text.
        self._completion_ctx    = None      # (prefix, candidates, kind)
        self._completion_prefix = ""
        self._intellisense_enabled = bool(globals().get("CALC_INTELLISENSE", True))
        self._completer = CalcCompleter(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setWidget(self.input)
        self._completer.activated.connect(self._on_completion_activated)

        # ---- result panel — one row per format, all left-justified, no
        # gap between rows so the formats stack tightly. ----
        rb = QGridLayout()
        rb.setHorizontalSpacing(8); rb.setVerticalSpacing(0)
        rb.setContentsMargins(0, 0, 0, 0)
        self.dec_label  = self._mono_label()
        self.hex_label  = self._mono_label()
        self.bin_label  = self._mono_label()
        self.oct_label  = self._mono_label()
        self.eng_label  = self._mono_label()
        self.auto_label = self._mono_label()
        self.auto_label.setWordWrap(True)
        # Left side: tag + value for DEC/HEX/BIN/OCT/ENG, stacked rows.
        for r, (k, w) in enumerate([("DEC",  self.dec_label),
                                    ("HEX",  self.hex_label),
                                    ("BIN",  self.bin_label),
                                    ("OCT",  self.oct_label),
                                    ("ENG",  self.eng_label)]):
            tag = QLabel(k)
            tag.setStyleSheet("color:#888; font-weight:bold;")
            tag.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            tag.setMinimumWidth(40)
            rb.addWidget(tag, r, 0)
            w.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            rb.addWidget(w, r, 1)
        # Right side: cross-conversion list sits in its own column to the
        # right of the base/format values, spanning every row so it can
        # grow downward past ENG when the category has many target units.
        self.auto_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        rb.addWidget(self.auto_label, 0, 3, 5, 1)
        rb.setColumnMinimumWidth(2, 20)
        rb.setColumnStretch(1, 0)
        rb.setColumnStretch(3, 1)
        result_box = QWidget(); result_box.setLayout(rb)

        # ---- bit grid (no caption) ----
        self.bit_grid = CalcBitGrid()
        # Clicking a cell flips that bit; the new integer flows back
        # through the input field so every result row re-derives.
        self.bit_grid.valueChanged.connect(self._on_bit_clicked)

        # ---- history list (no caption) ----
        self.history_list = QListWidget()
        self.history_list.setFont(self._mono_font(10))
        # Multi-select so the user can shift/ctrl-click a range of past
        # results and Ctrl+C the whole thing into the clipboard.
        self.history_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.history_list.itemDoubleClicked.connect(self._on_history_dblclick)

        # Stack the result panel, the 31..0 bit grid, and the history
        # list directly in the outer layout — no draggable divider.
        # The history list takes whatever vertical space is left after
        # the (fixed-height) result panel and bit grid.
        outer.addWidget(result_box)
        outer.addWidget(self.bit_grid)
        outer.addWidget(self.history_list, 1)

        # state
        self._history = []         # list of (expr_text, summary_text)
        self._hist_idx = None      # current Up/Down position; None = at "live" input
        # `ans` substitution: bare `ans` → last numeric value,
        # `[ans]` → previous formula text wrapped in parens.
        self._last_ans_value = None
        self._last_ans_text  = None

        # NB: no Ctrl+Backspace QShortcut here — that chord is reserved
        # for QLineEdit's native word-delete inside the input box.
        # Tab-wide reset is bound at the menu level to Ctrl+Shift+Backspace.

        # Ctrl+C — single tab-scoped handler that dispatches by focus:
        # QLineEdit → native text-copy; history list → copy selected rows;
        # anywhere else → fall back to "formula = result".  We do this here
        # (instead of leaving Ctrl+C unbound) because the user wants Ctrl+C
        # to "do something useful" no matter which Calc-tab widget is
        # focused, including the bottom history pane.
        copy_c = QShortcut(QKeySequence("Ctrl+C"), self)
        copy_c.setContext(Qt.WidgetWithChildrenShortcut)
        copy_c.activated.connect(self._on_ctrl_c)

        # Ctrl+Shift+C — tab-scoped duplicate of the global "copy current
        # tab" shortcut.  Tab-scoped contexts win over WindowShortcut, so
        # this guarantees the chord fires reliably even if the focused
        # widget would otherwise swallow / disambiguate the global.
        copy_short = QShortcut(QKeySequence("Ctrl+Shift+C"), self)
        copy_short.setContext(Qt.WidgetWithChildrenShortcut)
        copy_short.activated.connect(self._on_ctrl_shift_c)

        # Ctrl+Alt+Shift+C copies formula + every result format. Tab-scoped
        # so it doesn't fire while a different tab is foregrounded.
        copy_full = QShortcut(QKeySequence("Ctrl+Alt+Shift+C"), self)
        copy_full.setContext(Qt.WidgetWithChildrenShortcut)
        copy_full.activated.connect(self._copy_all_formats)

        # Ctrl+Backspace wipes the history list.  Tab-scoped — overrides
        # QLineEdit's native delete-previous-word inside the input, which
        # is the trade-off the user asked for.
        clear_hist_sc = QShortcut(QKeySequence("Ctrl+Backspace"), self)
        clear_hist_sc.setContext(Qt.WidgetWithChildrenShortcut)
        clear_hist_sc.activated.connect(self._clear_history)

        self._reset_result_display()
        self.input.setFocus()
        # Pull in any persisted history-list styling from the global config.
        self._apply_history_style_from_globals()

    # -----------------------------------------------------------------
    def _mono_font(self, pt=11):
        for fam in ("Consolas", "Cascadia Code", "Source Code Pro",
                    "DejaVu Sans Mono", "Courier New"):
            if fam in QFontDatabase().families():
                f = QFont(fam, pt)
                f.setStyleHint(QFont.Monospace)
                return f
        f = QFont(); f.setStyleHint(QFont.Monospace); f.setPointSize(pt)
        return f

    def _mono_label(self):
        l = QLabel("—")
        l.setFont(self._mono_font(11))
        l.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        l.setStyleSheet("padding:0px 4px;")
        l.setContentsMargins(0, 0, 0, 0)
        return l

    def _reset_result_display(self):
        for w in (self.dec_label, self.hex_label, self.bin_label,
                  self.oct_label, self.eng_label, self.auto_label):
            w.setText("—")
        self.bit_grid.set_value(0)

    # ---- ans pill: style, activation, geometry -----------------------
    def _apply_ans_pill_style(self):
        """Blue chip styling — works in both themes; the input field's
        own background bleeds through to the rounded corners since the
        QLabel is a child widget."""
        if THEME == "dark":
            bg, fg = "#3b82f6", "#ffffff"
        else:
            bg, fg = "#2563eb", "#ffffff"
        self._ans_pill.setStyleSheet(
            f"QLabel#ansPill {{"
            f"  background-color: {bg};"
            f"  color: {fg};"
            f"  border-radius: 8px;"
            f"  padding: 0px 6px;"
            f"  font-weight: bold;"
            f"  font-size: 9pt;"
            f"}}"
        )

    def _activate_ans_pill(self):
        if self._ans_pill_active:
            return
        self._ans_pill_active = True
        if self._last_ans_value is not None:
            self._ans_pill.setToolTip(f"ans = {self._last_ans_value!r}")
        else:
            self._ans_pill.setToolTip("ans")
        self._ans_pill.adjustSize()
        self._position_ans_pill()
        self._ans_pill.show()

    def _dismiss_ans_pill(self):
        if not self._ans_pill_active:
            return
        self._ans_pill_active = False
        self._ans_pill.hide()
        self.input.setTextMargins(0, 0, 0, 0)

    def _position_ans_pill(self):
        """Center the pill vertically inside the input, anchored to the
        left margin.  Push the QLineEdit text past it via setTextMargins."""
        if not self._ans_pill_active:
            return
        self._ans_pill.adjustSize()
        pw = self._ans_pill.width()
        ph = self._ans_pill.height()
        ih = self.input.height()
        # Left padding inside the QLineEdit, then the pill, then a 4px gap
        # before the caret starts.
        x = 4
        y = max(0, (ih - ph) // 2)
        self._ans_pill.move(x, y)
        self.input.setTextMargins(x + pw + 4, 0, 0, 0)

    def _effective_input_text(self, text):
        """The text the evaluator should see: `text` with `ans` prepended
        whenever the pill is active.  Centralised so live preview and the
        Enter path share the same rule."""
        if self._ans_pill_active and text:
            return "ans" + text
        return text

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # The input's height tracks the layout — reposition the pill so it
        # stays vertically centred when the row resizes.
        self._position_ans_pill()

    # ---- history list styling (driven by global config) --------------
    def _apply_history_style_from_globals(self):
        cfg = globals().get("CALC_HISTORY_STYLE", {}) or {}
        self.apply_history_style(
            cfg.get("font_family"),
            cfg.get("font_size"),
            cfg.get("fg"),
            cfg.get("bg"),
        )

    def apply_history_style(self, font_family, font_size, fg, bg):
        if font_family or font_size:
            f = QFont(font_family or "Consolas",
                      int(font_size) if font_size else 10)
            f.setStyleHint(QFont.Monospace)
            self.history_list.setFont(f)
        css = []
        if fg: css.append(f"color: {fg};")
        if bg: css.append(f"background: {bg};")
        self.history_list.setStyleSheet("QListWidget {" + " ".join(css) + "}"
                                        if css else "")

    # ---------------- key handling: history nav -----------------------
    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            popup = self._completer.popup()
            popup_visible = popup is not None and popup.isVisible()
            if event.key() == Qt.Key_Up and not popup_visible:
                self._history_back();    return True
            if event.key() == Qt.Key_Down and not popup_visible:
                self._history_forward(); return True
            if event.key() == Qt.Key_Escape and popup_visible:
                popup.hide();            return True
            # Numpad +/- are left to type into the Calc input here; the
            # window's global +/- shortcuts (which the focused input vetoes)
            # only cycle tabs on the other, non-Calc pages.
        return super().eventFilter(obj, event)

    # ---------------- "->" intellisense -------------------------------
    def _on_text_edited(self, text):
        # ans-pill: if the user just hit Enter and is now starting the
        # next expression with a binary operator, pop the blue chip in
        # front so the field reads "ans <op> ...".  Dismiss as soon as
        # the leading character is no longer an operator (e.g. backspace
        # to empty, or a digit got typed in front).
        if self._just_evaluated and not self._ans_pill_active \
                and text and text[0] in self._ANS_TRIGGER_OPS \
                and self._last_ans_value is not None:
            self._activate_ans_pill()
        # `_just_evaluated` is a one-shot — only the keystroke immediately
        # after Enter can summon the pill.
        self._just_evaluated = False
        if self._ans_pill_active and (
                not text or text[0] not in self._ANS_TRIGGER_OPS):
            self._dismiss_ans_pill()

        # Cosmetic: render '^<digit>' as a Unicode superscript so the
        # expression reads mathematically as the user types.  The
        # eval-side normaliser undoes this before parsing.
        new_text = _calc_render_superscripts(text)
        if new_text != text:
            cursor_pos = self.input.cursorPosition()
            # Each pair (^ + digit) collapses to a single glyph, so the
            # cursor needs to back off by the number of pairs that lay
            # before its position in the *original* text.
            pairs_before = len(_CARET_DIGIT_RE.findall(text[:cursor_pos]))
            self.input.blockSignals(True)
            self.input.setText(new_text)
            self.input.setCursorPosition(
                max(0, min(len(new_text), cursor_pos - pairs_before)))
            self.input.blockSignals(False)
            text = new_text
        # Cosmetic: bare '*' → '×'.  1-to-1 substitution so the cursor
        # stays put.  The normaliser flips '×' back to '*' at eval time.
        new_text = _calc_render_multiplication(text)
        if new_text != text:
            cursor_pos = self.input.cursorPosition()
            self.input.blockSignals(True)
            self.input.setText(new_text)
            self.input.setCursorPosition(min(len(new_text), cursor_pos))
            self.input.blockSignals(False)
            text = new_text
        # Live compute as the user types — silent on partial / invalid input.
        self._evaluate_live(text)
        # Then refresh the intellisense popup for the token at the cursor.
        if self._intellisense_enabled:
            self._refresh_completions()
        else:
            self._hide_completer()

    # ------------------------------------------------------------------
    #  Intellisense — pure context logic + thin Qt glue
    # ------------------------------------------------------------------
    _CALC_TOKEN_RE = re.compile(r"([A-Za-zµ]+)$")

    def _completion_context(self, before):
        """Pure: given the text left of the cursor, decide what to complete.
        Returns (prefix, candidates, kind) or None, where kind is:
          'arrow' — unit target after '->'  (category-aware, + P↔V bridge)
          'unit'  — a unit suffix typed right after a number / ')'
          'ident' — a function or constant name
        The number-before test is what lets '5 min' offer the minute unit
        while 'min(' still offers the min() function."""
        idx = before.rfind("->")
        if idx >= 0:
            partial = before[idx + 2:].lstrip()
            if re.fullmatch(r"[A-Za-z0-9µ]*", partial):
                cat = self._infer_category(before[:idx].strip())
                if cat is not None:
                    cands = list(CALC_CATEGORY_UNITS.get(cat, []))
                    if cat == "power":
                        cands += CALC_CATEGORY_UNITS.get("volt", [])
                    elif cat == "volt":
                        cands += CALC_CATEGORY_UNITS.get("power", [])
                    return (partial, cands, "arrow")
            return None
        m = self._CALC_TOKEN_RE.search(before)
        if not m:
            return None
        word = m.group(1)
        j = m.start(1) - 1
        while j >= 0 and before[j] == " ":
            j -= 1
        prev = before[j] if j >= 0 else ""
        if prev.isdigit() or prev in (")", "."):
            return (word, _CALC_UNIT_ITEMS, "unit")
        return (word, _CALC_IDENT_ITEMS, "ident")

    @staticmethod
    def _filter_candidates(prefix, cands):
        """Case-insensitive: prefer startswith, fall back to substring."""
        if not prefix:
            return list(cands)
        low = prefix.lower()
        starts = [c for c in cands if c.lower().startswith(low)]
        return starts if starts else [c for c in cands if low in c.lower()]

    @staticmethod
    def _build_completion(full, cursor, prefix, kind, chosen):
        """Pure: splice `chosen` in over the `prefix` token ending at
        `cursor`.  Returns (new_text, new_cursor)."""
        start = max(0, cursor - len(prefix))
        insert = chosen
        if kind == "arrow" and start > 0 and full[start - 1] not in " ":
            insert = " " + chosen          # keep '-> unit' readable
        return full[:start] + insert + full[cursor:], start + len(insert)

    def _refresh_completions(self):
        cursor = self.input.cursorPosition()
        ctx = self._completion_context(self.input.text()[:cursor])
        if ctx is None:
            self._completion_ctx = None
            self._hide_completer()
            return
        prefix, cands, _kind = ctx
        keep = self._filter_candidates(prefix, cands)
        # Nothing to add, or the token is already the sole full match.
        if not keep or (len(keep) == 1 and keep[0].lower() == prefix.lower()):
            self._completion_ctx = None
            self._hide_completer()
            return
        self._completion_ctx    = ctx
        self._completion_prefix = prefix
        self._completer.setModel(QStringListModel(keep, self._completer))
        self._completer.setCompletionPrefix(prefix)
        cr = self.input.cursorRect()
        popup = self._completer.popup()
        if popup is not None:
            cr.setWidth(popup.sizeHintForColumn(0)
                        + popup.verticalScrollBar().sizeHint().width() + 24)
        self._completer.complete(cr)

    def _hide_completer(self):
        popup = self._completer.popup()
        if popup is not None and popup.isVisible():
            popup.hide()

    def _completion_full_text(self, chosen):
        """Replacement text for the current completion (used by
        CalcCompleter.pathFromIndex)."""
        if self._completion_ctx is None:
            return self.input.text()
        prefix, _c, kind = self._completion_ctx
        new, _pos = self._build_completion(
            self.input.text(), self.input.cursorPosition(), prefix, kind, chosen)
        return new

    def set_intellisense_enabled(self, on):
        self._intellisense_enabled = bool(on)
        if not on:
            self._completion_ctx = None
            self._hide_completer()

    def _evaluate_live(self, text):
        """Evaluate the current input and refresh the result panel without
        touching history.  Errors are swallowed so the previous valid
        result keeps showing while the user is mid-typing."""
        text = text.strip()
        if not text:
            self._reset_result_display()
            return
        # When the ans-pill is active, the field text starts with an
        # operator like "/2"; prepend literal `ans` so the substitution
        # path resolves it the same way an Enter would.
        text = self._effective_input_text(text)
        # Resolve any `ans` / `[ans]` references before previewing so the
        # result panel updates as soon as the user finishes typing them.
        text = self._substitute_ans(text)
        # Skip a "-> " that's still missing its target unit
        if "->" in text and not text.split("->", 1)[1].strip():
            return
        try:
            value, unit = self._evaluate(text)
        except Exception:
            return
        self._display(value, unit)
        self._show_db_loss_info(text)

    def _infer_category(self, source_text):
        if not source_text:
            return None
        _head, unit = _calc_split_unit(source_text)
        if unit is None:
            return None
        return _calc_unit_category(unit)

    def _on_completion_activated(self, chosen):
        if self._completion_ctx is None:
            return
        prefix, _c, kind = self._completion_ctx
        new, pos = self._build_completion(
            self.input.text(), self.input.cursorPosition(), prefix, kind, chosen)
        self._completion_ctx = None
        self.input.setText(new)
        self.input.setCursorPosition(pos)
        self.input.setFocus()

    # ---------------- evaluation --------------------------------------
    # ---- `ans` substitution ----------------------------------------
    # Bare `ans` is replaced with the previous evaluation's numeric value
    # wrapped in parens.  `[ans]` is replaced with the previous formula
    # text wrapped in parens — so `[ans]*10` literally re-inserts the
    # previous expression and re-evaluates it as a sub-expression of the
    # new one (preserves units / operator precedence).
    _ANS_BRACKET_RE = re.compile(r"\[\s*ans\s*\]", re.IGNORECASE)
    _ANS_BARE_RE    = re.compile(r"\bans\b",        re.IGNORECASE)

    def _substitute_ans(self, text):
        if not text:
            return text
        # Bracket form first so the inserted formula isn't itself touched
        # by the bare-`ans` pass (the inserted text is already the
        # value-resolved form from the previous evaluation).
        if self._last_ans_text is not None and self._ANS_BRACKET_RE.search(text):
            text = self._ANS_BRACKET_RE.sub(
                "(" + self._last_ans_text + ")", text)
        if self._last_ans_value is not None and self._ANS_BARE_RE.search(text):
            v = self._last_ans_value
            if isinstance(v, complex):
                lit = f"({v.real:.15g}+{v.imag:.15g}j)"
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                lit = f"({v:.15g})" if isinstance(v, float) else f"({int(v)})"
            else:
                lit = f"({v})"
            text = self._ANS_BARE_RE.sub(lit, text)
        return text

    def _on_evaluate(self):
        raw_text = self.input.text().strip()
        if not raw_text:
            return
        # Pill active → the visible text starts with an operator, but the
        # evaluator and the history entry should see "ans<op>...".
        if self._ans_pill_active:
            raw_text = "ans" + raw_text
        text = self._substitute_ans(raw_text)
        # Parametric mode: any [...] knob in the input pops a sweep dialog
        # instead of running a single-shot evaluation.
        if "[" in text and "]" in text:
            knobs, template = _extract_params(text)
            if any(k[0] in ("sweep", "literal") for k in knobs):
                ParametricDialog(
                    self._evaluate, knobs, template, text, self
                ).exec_()
                return
        try:
            value, unit = self._evaluate(text)
        except Exception as exc:
            self._reset_result_display()
            self.dec_label.setText(f"Error: {exc}")
            return
        self._display(value, unit)
        self._show_db_loss_info(text)
        summary = self._format_summary(raw_text, value, unit)
        self._history.append((raw_text, summary))
        if len(self._history) > self.HISTORY_MAX:
            self._history.pop(0)
        self._hist_idx = None
        it = QListWidgetItem(summary)
        self.history_list.addItem(it)
        self.history_list.scrollToBottom()
        # Remember this result so the NEXT evaluation can resolve `ans`
        # (value) and `[ans]` (post-substitution formula text).
        if value is not None:
            self._last_ans_value = value
            self._last_ans_text  = text
        # Arm the ans-pill: the very next keystroke, if it's an operator,
        # will summon the chip.  Dismiss any currently-shown pill — the
        # user must type a fresh operator to re-summon it.
        self._dismiss_ans_pill()
        self._just_evaluated = (value is not None)
        self.input.selectAll()

    def _evaluate(self, text):
        """Return (value, unit). `unit` is None for unit-less results."""
        # Equation mode: a single '=' with one unknown identifier (e.g.
        # `8.3-(2.3+x)=12`) routes to the sympy-backed solver.  The
        # annotation is reset on every call so a later non-equation
        # expression doesn't keep the previous '<var> = ' prefix.
        self._last_equation = None
        sol = _calc_solve_equation(text)
        if sol is not None:
            var_name, roots = sol
            self._last_equation = (var_name, roots)
            # First purely-real root drives the DEC/HEX/BIN/OCT/ENG
            # views; `_display` lists the rest in `auto_label`.
            for r in roots:
                if isinstance(r, (int, float)) and not isinstance(r, bool):
                    return (r, None)
            return (roots[0], None)
        if "->" in text:
            left, _, right = text.partition("->")
            left  = left.strip()
            target = right.strip().split()[0] if right.strip() else ""
            if not target:
                raise ValueError("missing target unit after '->'")
            value, src_unit = self._eval_part(left)
            if src_unit is None:
                raise ValueError("source has no unit")
            tup = _calc_to_base(value, src_unit)
            if tup is None:
                raise ValueError(f"unknown source unit '{src_unit}'")
            src_cat, base_v = tup
            tgt_cat = _calc_unit_category(target)
            if tgt_cat is None:
                raise ValueError(f"unknown target unit '{target}'")
            if src_cat != tgt_cat:
                bridged = self._bridge_power_voltage(src_cat, tgt_cat, base_v)
                if bridged is None:
                    raise ValueError(f"can't convert {src_cat} → {tgt_cat}")
                return (_calc_from_base(bridged, target), target)
            return (_calc_from_base(base_v, target), target)
        return self._eval_part(text)

    # Assumed system impedance for power <-> voltage conversions in the
    # '->' operator (e.g. "150mW -> V").  RF convention: Vrms.
    _BRIDGE_Z0 = 50.0

    @staticmethod
    def _bridge_power_voltage(src_cat, tgt_cat, base_v):
        """Cross-category bridge for '->': convert between power (base watts)
        and voltage (base Vrms) assuming a 50 Ω system, P = Vrms²/Z₀.
        Returns the value in the *target* base unit, or None if the pair
        isn't a power<->voltage conversion."""
        z0 = CalcTab._BRIDGE_Z0
        if src_cat == "power" and tgt_cat == "volt":
            return sqrt(base_v * z0) if base_v >= 0 else None   # W → Vrms
        if src_cat == "volt" and tgt_cat == "power":
            return (base_v * base_v) / z0                       # Vrms → W
        return None

    def _eval_part(self, text):
        # Reverse the cosmetic superscript rewrite and convert the
        # textbook idiom `func²(x)` / `sin^2(x)` into Python's
        # `func(x)**2` so the rest of the pipeline doesn't have to know.
        text = _calc_normalize_superscripts(text)
        # Mixed dBm/dBW + dB arithmetic: substitute every '<num>(dBm|dBW|dB)'
        # token with its bare number and propagate the carrier unit out.
        # Lets '(10dBm-5dB)' parse as 5 dBm (10 dBm reduced by 5 dB of loss).
        pp_expr, pp_unit = _calc_preprocess_db(text)
        if pp_unit is not None:
            try:
                value = _calc_eval_math(pp_expr)
            except Exception:
                v = parse(pp_expr)
                if v is None:
                    raise ValueError(f"can't evaluate '{pp_expr}'")
                value = v
            return (value, pp_unit)
        # Generic-unit arithmetic — "385mm/2", "1in + 5mm", etc.
        pp_expr2, pp_unit2 = _calc_preprocess_units(text)
        if pp_unit2 is not None:
            try:
                value = _calc_eval_math(pp_expr2)
            except Exception:
                v = parse(pp_expr2)
                if v is None:
                    raise ValueError(f"can't evaluate '{pp_expr2}'")
                value = v
            return (value, pp_unit2)
        head, unit = _calc_split_unit(text)
        if not head:
            head = text
        try:
            value = _calc_eval_math(head)
        except Exception:
            v = parse(head)
            if v is None:
                raise ValueError(f"can't evaluate '{head}'")
            value = v
        return (value, unit)

    # ---------------- result rendering --------------------------------
    def _display(self, value, unit):
        if value is None:
            self._reset_result_display()
            return
        # Decimal
        if isinstance(value, complex):
            self.dec_label.setText(f"{value.real:.10g} + {value.imag:.10g}j")
        elif isinstance(value, float):
            if value.is_integer() and abs(value) < 1e15:
                self.dec_label.setText(self._with_unit(int(value), unit))
            else:
                self.dec_label.setText(self._with_unit(f"{value:.12g}", unit))
        else:
            self.dec_label.setText(self._with_unit(value, unit))
        # Integer-only views
        try:
            iv = int(value)
            if iv == value:
                if iv >= 0:
                    self.hex_label.setText(f"0x{iv:X}")
                    self.bin_label.setText(f"0b{iv:b}")
                    self.oct_label.setText(f"0o{iv:o}")
                else:
                    bits32 = iv & 0xFFFFFFFF
                    self.hex_label.setText(
                        f"-0x{-iv:X}      (32-bit two's-comp 0x{bits32:X})")
                    self.bin_label.setText(f"-0b{-iv:b}")
                    self.oct_label.setText(f"-0o{-iv:o}")
                self.bit_grid.set_value(iv)
            else:
                self.hex_label.setText("—")
                self.bin_label.setText("—")
                self.oct_label.setText("—")
                self.bit_grid.set_value(0)
        except (TypeError, ValueError, OverflowError):
            self.hex_label.setText("—")
            self.bin_label.setText("—")
            self.oct_label.setText("—")
            self.bit_grid.set_value(0)
        # Engineering
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value != 0:
            absv = abs(value)
            for suff, scale in (("T", 1e12), ("G", 1e9), ("M", 1e6),
                                ("k", 1e3), ("",  1.0), ("m", 1e-3),
                                ("u", 1e-6), ("n", 1e-9), ("p", 1e-12),
                                ("f", 1e-15)):
                if absv >= scale:
                    eng = f"{value/scale:.6g}{suff}"
                    break
            else:
                eng = f"{value:.6g}"
            self.eng_label.setText(self._with_unit(eng, unit))
        else:
            self.eng_label.setText(self._with_unit(value, unit))
        # Auto cross-conversion (power ↔ all power units; dB → VSWR + loss).
        self.auto_label.setText(self._auto_conv(value, unit) or "—")
        # Equation mode: prefix the textual rows with "<var> = " and, if
        # there's more than one root, list them all in the auto-conv slot
        # (which the unitless equation case leaves blank otherwise).
        eq = getattr(self, "_last_equation", None)
        if eq is not None:
            var_name, roots = eq
            self.dec_label.setText(f"{var_name} = {self.dec_label.text()}")
            self.eng_label.setText(f"{var_name} = {self.eng_label.text()}")
            if len(roots) > 1:
                self.auto_label.setText(
                    f"{var_name} ∈ {{"
                    + ", ".join(self._fmt_root(r) for r in roots)
                    + "}"
                )
            else:
                self.auto_label.setText("—")

    @staticmethod
    def _format_auto_table(pairs):
        """Render (value, unit) pairs as a vertical column with both
        value and unit right-aligned so the block right-justifies cleanly
        and each column lines up underneath itself."""
        if not pairs:
            return ""
        max_val_w = max(len(v) for v, _ in pairs)
        max_unit_w = max(len(u) for _, u in pairs)
        lines = [f"{v.rjust(max_val_w)}  {u.rjust(max_unit_w)}"
                 for v, u in pairs]
        return "\n".join(lines)

    @staticmethod
    def _auto_conv(value, unit):
        """Vertical, unit-aligned cross-conversion table.

        - Any power unit (W/mW/kW/MW/uW/nW/dBm/dBW) → every other power form
        - 'dB'  → interpreted as Return Loss → VSWR, ρ, mismatch loss,
                  reflected power assuming a 1 W reference input
        - Generic categories: every other listed unit in the same category
        """
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ""
        if unit is None:
            return ""
        cat = _calc_unit_category(unit)
        if cat == "power":
            tup = _calc_to_base(value, unit)
            if tup is None:
                return ""
            _, watts = tup
            if watts <= 0:
                return ""
            pairs = []
            if unit != "dBm":
                pairs.append((f"{10.0 * log10(watts * 1000.0):.5g}", "dBm"))
            if unit != "W":
                pairs.append((f"{watts:.5g}", "W"))
            if unit != "mW":
                pairs.append((f"{watts * 1000.0:.5g}", "mW"))
            if unit != "dBW":
                pairs.append((f"{10.0 * log10(watts):.5g}", "dBW"))
            # Equivalent sine-wave V/I into the assumed 50 Ω system:
            # Vrms = √(P·Z₀), Irms = √(P/Z₀), peak = √2 · rms.
            z0 = CalcTab._BRIDGE_Z0
            vrms = sqrt(watts * z0)
            irms = sqrt(watts / z0)
            root2 = sqrt(2.0)
            pairs.append((f"{vrms:.5g}", "Vrms"))
            pairs.append((f"{vrms * root2:.5g}", "Vpk"))
            pairs.append((f"{irms:.5g}", "Irms"))
            pairs.append((f"{irms * root2:.5g}", "Ipk"))
            return CalcTab._format_auto_table(pairs)
        # Generic length / frequency / time / volt / curr / res / cap /
        # ind / angle: show every other listed unit in the same category.
        if cat in ("len", "freq", "time", "vol", "mass", "energy",
                   "pressure", "force", "speed", "data", "volt", "curr",
                   "res", "cap", "ind", "angle"):
            tup = _calc_to_base(value, unit)
            if tup is None:
                return ""
            _, base_v = tup
            units = CALC_CATEGORY_UNITS.get(cat, [])
            pairs = []
            for u in units:
                if u == unit:
                    continue
                try:
                    converted = _calc_from_base(base_v, u)
                except (ValueError, ZeroDivisionError):
                    continue
                pairs.append((f"{converted:.5g}", u))
            # Frequency ↔ period: base_v is the category base (s for time,
            # Hz for freq), so 1/base_v is directly the opposite category's
            # base value.  A time input also lists its reciprocal frequency,
            # a frequency its reciprocal period.
            recip_cat = {"time": "freq", "freq": "time"}.get(cat)
            if recip_cat is not None and base_v != 0:
                recip_base = 1.0 / base_v
                for u in CALC_CATEGORY_UNITS.get(recip_cat, []):
                    try:
                        converted = _calc_from_base(recip_base, u)
                    except (ValueError, ZeroDivisionError):
                        continue
                    pairs.append((f"{converted:.5g}", u))
            return CalcTab._format_auto_table(pairs)
        if cat == "rl":
            rl = abs(float(value))
            rho = 10.0 ** (-rl / 20.0)
            if rho >= 1.0:
                return "RL ≤ 0 dB → fully reflective (VSWR=∞)"
            vswr     = (1.0 + rho) / (1.0 - rho)
            ml_db    = -10.0 * log10(1.0 - rho * rho)
            refl_w   = rho * rho                          # at 1 W input
            refl_dbm = 10.0 * log10(refl_w * 1000.0) if refl_w > 0 else float("-inf")
            return (f"VSWR={vswr:.4g}  ρ={rho:.4g}  "
                    f"Mismatch loss={ml_db:.4g} dB  "
                    f"Reflected={refl_w * 100.0:.3g}% "
                    f"({refl_w * 1000.0:.4g} mW @1W, "
                    f"{refl_dbm:.4g} dBm)")
        return ""

    def _db_loss_info(self, text):
        """For an expression carrying a dB gain/loss (e.g. '50W - 0.07473dB'),
        summarise the effect, else ''.

        When the carrier is an absolute power (dBm/dBW) and the net effect is
        a loss, return a small table giving delivered and lost power in both
        W and dBm plus the percent lost.  For a pure-dB carrier or a net
        gain, fall back to the one-line percent summary.

        The net dB delta is found by re-evaluating the expression with all
        pure-dB magnitudes zeroed and subtracting — so it works regardless
        of how many dB terms appear or what the carrier power unit is."""
        if not text:
            return ""
        db_tokens = [m for m in _CALC_DB_TOKEN_RE.finditer(text)
                     if m.group(2) == "dB"]
        if not db_tokens:
            return ""
        baseline = _CALC_DB_TOKEN_RE.sub(
            lambda m: ("0dB" if m.group(2) == "dB" else m.group(0)), text)
        try:
            full_v, full_u = self._evaluate(text)
            base_v, base_u = self._evaluate(baseline)
        except Exception:
            return ""
        if (not isinstance(full_v, (int, float)) or isinstance(full_v, bool)
                or not isinstance(base_v, (int, float)) or isinstance(base_v, bool)):
            return ""
        if full_u not in ("dB", "dBm", "dBW") or base_u != full_u:
            return ""
        net_db = float(full_v) - float(base_v)
        if abs(net_db) < 1e-12:
            return ""
        ratio = 10.0 ** (net_db / 10.0)          # output / input power

        # Absolute-power carrier (dBm/dBW) and a net loss → spell out the
        # delivered and lost power in both W and dBm.  This is what a query
        # like '50W - 0.07473dB' is really after: how much got through and
        # how much was dissipated.
        if full_u in ("dBm", "dBW") and net_db < 0:
            in_tup  = _calc_to_base(base_v, base_u)
            out_tup = _calc_to_base(full_v, full_u)
            if (in_tup and out_tup and in_tup[1] > 0
                    and out_tup[1] > 0 and in_tup[1] > out_tup[1]):
                out_w  = out_tup[1]
                lost_w = in_tup[1] - out_tup[1]
                pct_lost = (1.0 - ratio) * 100.0
                rows = [("delivered", f"{out_w:.5g} W",
                         f"{10.0 * log10(out_w * 1000.0):.5g} dBm"),
                        ("lost", f"{lost_w:.5g} W",
                         f"{10.0 * log10(lost_w * 1000.0):.5g} dBm")]
                w0 = max(len(r[0]) for r in rows)
                w1 = max(len(r[1]) for r in rows)
                w2 = max(len(r[2]) for r in rows)
                block = "\n".join(
                    f"{lbl.rjust(w0)}  {a.rjust(w1)}  {b.rjust(w2)}"
                    for lbl, a, b in rows)
                return f"{block}\n{pct_lost:.4g}% lost  ({net_db:+.4g} dB)"

        delivered = ratio * 100.0
        if net_db < 0:
            lost = (1.0 - ratio) * 100.0
            return (f"{net_db:+.4g} dB:  {delivered:.4g}% delivered,  "
                    f"{lost:.4g}% lost  (×{ratio:.4g})")
        # Net gain — "lost" is negative, so report the gain factor instead.
        return (f"{net_db:+.4g} dB:  {delivered:.4g}% of input  "
                f"(gain ×{ratio:.4g})")

    def _show_db_loss_info(self, text):
        """Append the dB delivered/lost summary to the cross-conversion
        panel when the expression involved a dB gain/loss."""
        info = self._db_loss_info(text)
        if not info:
            return
        cur = self.auto_label.text()
        if cur and cur != "—":
            self.auto_label.setText(cur + "\n" + info)
        else:
            self.auto_label.setText(info)

    @staticmethod
    def _with_unit(text, unit):
        return f"{text} {unit}" if unit else f"{text}"

    @staticmethod
    def _pretty_expr(expr):
        """Display-only beautification: ASCII '*' → ' × ' (U+00D7), but
        keep '**' intact so power expressions still read correctly."""
        return re.sub(r'(?<!\*)\*(?!\*)', ' × ', expr)

    @staticmethod
    def _fmt_root(r):
        """One-line numeric formatter shared by `_display` and
        `_format_summary` so equation roots render identically in the
        result panel and the history list."""
        if isinstance(r, complex):
            return f"{r.real:.10g}+{r.imag:.10g}j"
        if isinstance(r, float):
            if r.is_integer() and abs(r) < 1e15:
                return f"{int(r)}"
            return f"{r:.12g}"
        return str(r)

    def _format_summary(self, expr, value, unit):
        eq = getattr(self, "_last_equation", None)
        if eq is not None:
            var_name, roots = eq
            if len(roots) == 1:
                rhs = f"{var_name} = {self._fmt_root(roots[0])}"
            else:
                rhs = (f"{var_name} ∈ {{"
                       + ", ".join(self._fmt_root(r) for r in roots)
                       + "}")
            return f"{self._pretty_expr(expr)}   →   {rhs}"
        if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
            v = f"{int(value)}"
        elif isinstance(value, float):
            v = f"{value:.10g}"
        else:
            v = f"{value}"
        return f"{self._pretty_expr(expr)}  =  {v}{(' ' + unit) if unit else ''}"

    # ---------------- history navigation ------------------------------
    def _history_back(self):
        if not self._history:
            return
        if self._hist_idx is None:
            self._hist_idx = len(self._history) - 1
        else:
            self._hist_idx = max(0, self._hist_idx - 1)
        self.input.setText(self._history[self._hist_idx][0])
        self.input.setCursorPosition(len(self.input.text()))
        self._sync_history_selection()

    def _history_forward(self):
        if self._hist_idx is None:
            return
        self._hist_idx += 1
        if self._hist_idx >= len(self._history):
            self._hist_idx = None
            self.input.clear()
        else:
            self.input.setText(self._history[self._hist_idx][0])
            self.input.setCursorPosition(len(self.input.text()))
        self._sync_history_selection()

    def _sync_history_selection(self):
        """Mirror `_hist_idx` into the history QListWidget so the user
        sees which row their current Up/Down position corresponds to.
        Signals are blocked so we don't recursively trigger our own
        double-click handler."""
        self.history_list.blockSignals(True)
        if self._hist_idx is None:
            self.history_list.clearSelection()
            self.history_list.setCurrentRow(-1)
        elif 0 <= self._hist_idx < self.history_list.count():
            self.history_list.setCurrentRow(self._hist_idx)
            it = self.history_list.item(self._hist_idx)
            if it is not None:
                self.history_list.scrollToItem(it)
        self.history_list.blockSignals(False)

    def _on_history_dblclick(self, item):
        idx = self.history_list.row(item)
        if 0 <= idx < len(self._history):
            self.input.setText(self._history[idx][0])
            self.input.setFocus()

    # ---------------- bit-grid click → push value back to input -------
    def _on_bit_clicked(self, new_int):
        """Bit cell was toggled.  Push the new unsigned-32 integer back
        into the input as a decimal literal and re-run the live
        evaluator so every result row reflects it."""
        text = str(int(new_int))
        self.input.setText(text)
        self._evaluate_live(text)

    # ---------------- finder / persistence / clipboard ----------------
    def title(self):
        return "Calc"

    def search_entries(self, tab_name):
        # One entry per tab: typing the tab name in the finder lands on
        # the main calculator input.  The Calc tab has no "fields" of
        # its own that the rest of the app indexes, so without this the
        # tab itself wasn't reachable from Ctrl+Space.
        return [(tab_name, self.input, self)]

    def get_state(self):
        return {"history": [h[0] for h in self._history[-50:]]}

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        for expr in (st.get("history") or []):
            if not isinstance(expr, str):
                continue
            try:
                value, unit = self._evaluate(expr)
                summary = self._format_summary(expr, value, unit)
            except Exception:
                summary = f"{expr}  =  ?"
            self._history.append((expr, summary))
            self.history_list.addItem(summary)

    # Ctrl+Shift+C path — bare "formula  =  result" line, no header so the
    # user can paste it straight into a comment or message.
    def to_clipboard_text(self):
        expr = self.input.text().strip()
        if not expr:
            return ""
        pretty = self._pretty_expr(expr)
        dec = self.dec_label.text().strip()
        if not dec or dec == "—":
            return pretty
        return f"{pretty}  =  {dec}"

    # Ctrl+Alt+Shift+C path — formula plus every populated result format.
    def to_clipboard_text_full(self):
        expr = self.input.text().strip()
        if not expr:
            return ""
        rows = [("DEC",  self.dec_label.text()),
                ("HEX",  self.hex_label.text()),
                ("BIN",  self.bin_label.text()),
                ("OCT",  self.oct_label.text()),
                ("ENG",  self.eng_label.text()),
                ("AUTO", self.auto_label.text())]
        lines = [f"Formula:  {self._pretty_expr(expr)}"]
        for tag, val in rows:
            v = (val or "").strip()
            if not v or v == "—":
                continue
            lines.append(f"{tag:<5s} {v}")
        return "\n".join(lines)

    # ---------------- shortcut handlers --------------------------------
    def _clear_history(self):
        self._history.clear()
        self.history_list.clear()
        self._hist_idx = None

    def clear_all(self):
        """Reset the whole Calc tab to a blank slate: clear the input,
        the history list, and the result panel (DEC/HEX/BIN/OCT/ENG/AUTO
        and the 32-bit grid)."""
        self.input.clear()
        self._clear_history()
        self._reset_result_display()
        self.input.setFocus()

    def _copy_history_selection(self):
        items = self.history_list.selectedItems()
        if not items:
            return False
        # Preserve the on-screen order of the selection.
        rows = sorted(self.history_list.row(it) for it in items)
        text = "\n".join(self.history_list.item(r).text() for r in rows)
        QApplication.clipboard().setText(text)
        return True

    def _on_ctrl_c(self):
        """Ctrl+C dispatch: defers to QLineEdit's native text-copy when an
        input has focus; copies the selected history rows when the bottom
        list has focus; otherwise copies the current 'formula = result'."""
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.copy()
            return
        # Result rows (DEC/HEX/BIN/OCT/ENG and the unit-conversion list)
        # are mouse-selectable QLabels.  The tab-scoped Ctrl+C shortcut
        # shadows QLabel's built-in copy, so honour an active selection
        # here.  QLabel encodes line breaks as U+2029; normalise to '\n'.
        if isinstance(fw, QLabel):
            sel = fw.selectedText()
            if sel:
                QApplication.clipboard().setText(sel.replace(" ", "\n"))
                return
        if fw is self.history_list:
            if self._copy_history_selection():
                return
            # No selection: fall through to formula+result copy.
        text = self.to_clipboard_text()
        if not text:
            return
        QApplication.clipboard().setText(text)

    def _on_ctrl_shift_c(self):
        text = self.to_clipboard_text()
        if not text:
            return
        QApplication.clipboard().setText(text)

    def _copy_all_formats(self):
        text = self.to_clipboard_text_full()
        if not text:
            return
        QApplication.clipboard().setText(text)


# ====================================================================
#  ANTENNA DESIGNER TAB
# ====================================================================
#
# A single dedicated tab with a dropdown of common antenna types.  The
# right side shows a sketch of the selected geometry; the left side has
# inputs (frequency + a small number of type-specific parameters) and
# the calculated outputs (lengths, gain, beamwidth, etc.).
#
# All formulas are standard textbook results (Balanis, Stutzman, Kraus).

class AntennaDesignerTab(QWidget):
    """Antenna designer: pick a type, type a frequency (and any extra
    parameters such as dish diameter or number of Yagi elements), get
    physical dimensions, gain, beamwidth, etc."""

    KINDS = [
        ("dipole",    "Half-wave dipole"),
        ("monopole",  "Quarter-wave monopole (over ground)"),
        ("patch",     "Rectangular microstrip patch"),
        ("horn",      "Pyramidal horn"),
        ("dish",      "Parabolic dish"),
        ("yagi",      "Yagi-Uda"),
        ("helix",     "Axial-mode helix"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 8)
        outer.setSpacing(8)

        title = QLabel("Antenna designer")
        title.setStyleSheet("font-weight: bold;")
        outer.addWidget(title)

        # Top row: type selector
        type_row = QHBoxLayout(); type_row.setSpacing(8)
        type_row.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        for _, nice in self.KINDS:
            self.type_combo.addItem(nice)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_row.addWidget(self.type_combo, 0)
        type_row.addWidget(QLabel("   Frequency:"))
        self.freq_edit = QLineEdit("1000")
        self.freq_edit.setMaximumWidth(110); self.freq_edit.setMaximumHeight(18)
        self.freq_edit.textEdited.connect(lambda *_: self._recompute())
        type_row.addWidget(self.freq_edit)
        type_row.addWidget(QLabel("MHz"))
        type_row.addStretch(1)
        outer.addLayout(type_row)

        # Body: parameters/results on left, sketch on right
        body = QHBoxLayout(); body.setSpacing(16)
        # Left: parameters + outputs
        left = QWidget()
        self._left_v = QVBoxLayout(left)
        self._left_v.setContentsMargins(0, 0, 0, 0); self._left_v.setSpacing(4)
        body.addWidget(left, 0)
        # Right: sketch
        self.sketch = AntennaSketch()
        body.addWidget(self.sketch, 0, Qt.AlignTop)
        body.addStretch(1)
        outer.addLayout(body)
        outer.addStretch(1)

        # Per-type parameter widgets are rebuilt on type change.
        self._param_edits = {}     # name -> QLineEdit
        self._result_labels = {}   # name -> QLabel
        self._current_kind = self.KINDS[0][0]
        self._build_for_type(self._current_kind)
        self._recompute()

    # ---- type-driven schema -------------------------------------------------
    SCHEMA = {
        # kind: ([(param_name, label, unit, default_text)], [(out_name, label, unit)])
        "dipole":   ([("k_short", "Length factor", "", "0.95")],
                     [("L_mm", "Length L", "mm"),
                      ("Lf_mm","Half-length", "mm"),
                      ("gain", "Gain (free-space)", "dBi"),
                      ("hpbw", "HPBW (E-plane)", "°")]),
        "monopole": ([("k_short", "Length factor", "", "0.95")],
                     [("L_mm", "Length", "mm"),
                      ("gain", "Gain (over PEC)", "dBi")]),
        "patch":    ([("er", "Substrate ε_r", "", "4.4"),
                      ("h_mm", "Substrate height h", "mm", "1.6")],
                     [("W_mm", "Patch width W", "mm"),
                      ("L_mm", "Patch length L", "mm"),
                      ("eps_eff", "ε_eff", ""),
                      ("dL_mm", "ΔL (fringing)", "mm")]),
        "horn":     ([("Aap_mm", "Aperture A (E-plane)", "mm", "60"),
                      ("Bap_mm", "Aperture B (H-plane)", "mm", "80"),
                      ("eta", "Aperture efficiency", "", "0.51")],
                     [("gain", "Gain", "dBi"),
                      ("hpbw_e", "HPBW (E-plane)", "°"),
                      ("hpbw_h", "HPBW (H-plane)", "°")]),
        "dish":     ([("D_m",  "Dish diameter D", "m",  "1.0"),
                      ("eta",  "Aperture efficiency", "", "0.55")],
                     [("gain", "Gain", "dBi"),
                      ("hpbw", "HPBW (~70λ/D)", "°")]),
        "yagi":     ([("N",      "# elements",    "", "10")],
                     [("L_boom_lam", "Boom length", "λ"),
                      ("L_boom_m",   "Boom length", "m"),
                      ("gain",       "Gain (estimate)", "dBi"),
                      ("hpbw",       "HPBW (rough)", "°")]),
        "helix":    ([("N",     "# turns",        "", "10"),
                      ("D_lam", "Mean diameter D", "λ", "0.318"),
                      ("S_lam", "Pitch S",        "λ", "0.25")],
                     [("L_m",  "Axial length",  "m"),
                      ("gain", "Gain",          "dBi"),
                      ("hpbw", "HPBW",          "°")]),
    }

    def _clear_layout(self, layout):
        while layout.count():
            it = layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = it.layout()
                if sub is not None:
                    self._clear_layout(sub)

    def _build_for_type(self, kind):
        self._clear_layout(self._left_v)
        self._param_edits.clear(); self._result_labels.clear()
        params, results = self.SCHEMA[kind]
        # Parameters block
        if params:
            head = QLabel("Parameters"); head.setStyleSheet("font-weight: bold;")
            self._left_v.addWidget(head)
            grid = QGridLayout(); grid.setHorizontalSpacing(6); grid.setVerticalSpacing(2)
            for r, p in enumerate(params):
                name, label, unit = p[0], p[1], p[2]
                default = p[3] if len(p) > 3 else ""
                la = QLabel(label + ":"); la.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                ed = QLineEdit(default); ed.setMaximumWidth(120); ed.setMaximumHeight(18)
                ed.textEdited.connect(lambda *_: self._recompute())
                ul = QLabel(unit); ul.setStyleSheet("color: #555;")
                grid.addWidget(la, r, 0); grid.addWidget(ed, r, 1); grid.addWidget(ul, r, 2)
                self._param_edits[name] = ed
            host = QWidget(); host.setLayout(grid); self._left_v.addWidget(host)
        # Results block
        head2 = QLabel("Results"); head2.setStyleSheet("font-weight: bold;")
        self._left_v.addWidget(head2)
        grid2 = QGridLayout(); grid2.setHorizontalSpacing(6); grid2.setVerticalSpacing(2)
        for r, (name, label, unit) in enumerate(results):
            la = QLabel(label + ":"); la.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val = QLabel("—")
            val.setStyleSheet("padding-left:4px;")
            ul = QLabel(unit); ul.setStyleSheet("color: #555;")
            grid2.addWidget(la, r, 0); grid2.addWidget(val, r, 1); grid2.addWidget(ul, r, 2)
            self._result_labels[name] = val
        host2 = QWidget(); host2.setLayout(grid2); self._left_v.addWidget(host2)
        self._left_v.addStretch(1)

    def _on_type_changed(self, idx):
        kind = self.KINDS[idx][0]
        self._current_kind = kind
        self.sketch.set_kind(kind)
        self._build_for_type(kind)
        self._recompute()

    # ---- math --------------------------------------------------------------
    def _recompute(self):
        f_mhz = parse(self.freq_edit.text())
        if f_mhz is None or f_mhz <= 0:
            for v in self._result_labels.values(): v.setText("—")
            return
        lam = C_LIGHT / (f_mhz * 1e6)                # m
        kind = self._current_kind
        out = {}
        try:
            if kind == "dipole":
                k = parse(self._param_edits["k_short"].text()) or 0.95
                L = lam / 2 * k
                out["L_mm"]  = f"{L*1e3:.3g}"
                out["Lf_mm"] = f"{L*1e3/2:.3g}"
                out["gain"]  = "2.15"
                out["hpbw"]  = "78"
            elif kind == "monopole":
                k = parse(self._param_edits["k_short"].text()) or 0.95
                L = lam / 4 * k
                out["L_mm"] = f"{L*1e3:.3g}"
                out["gain"] = "5.15"
            elif kind == "patch":
                er = parse(self._param_edits["er"].text())   or 4.4
                h  = parse(self._param_edits["h_mm"].text()) or 1.6
                h_m = h * 1e-3
                W = (C_LIGHT / (2 * f_mhz * 1e6)) * sqrt(2.0 / (er + 1))
                eeff = (er + 1) / 2.0 + (er - 1) / 2.0 * (1 + 12 * h_m / W) ** -0.5
                dL = h_m * 0.412 * ((eeff + 0.3) * (W / h_m + 0.264)) / \
                                  ((eeff - 0.258) * (W / h_m + 0.8))
                L = (C_LIGHT / (2 * f_mhz * 1e6 * sqrt(eeff))) - 2 * dL
                out["W_mm"]    = f"{W*1e3:.3g}"
                out["L_mm"]    = f"{L*1e3:.3g}"
                out["eps_eff"] = f"{eeff:.3g}"
                out["dL_mm"]   = f"{dL*1e3:.3g}"
            elif kind == "horn":
                A = (parse(self._param_edits["Aap_mm"].text()) or 60) * 1e-3
                B = (parse(self._param_edits["Bap_mm"].text()) or 80) * 1e-3
                eta = parse(self._param_edits["eta"].text()) or 0.51
                Aap = A * B
                G_lin = eta * 4 * pi * Aap / (lam ** 2)
                if G_lin > 0:
                    out["gain"] = f"{10*log10(G_lin):.2f}"
                # Approximate beamwidths for pyramidal horn (Balanis)
                out["hpbw_e"] = f"{56.0 * lam / B:.2f}"
                out["hpbw_h"] = f"{78.0 * lam / A:.2f}"
            elif kind == "dish":
                D   = parse(self._param_edits["D_m"].text())  or 1.0
                eta = parse(self._param_edits["eta"].text()) or 0.55
                G_lin = eta * (pi * D / lam) ** 2
                if G_lin > 0:
                    out["gain"] = f"{10*log10(G_lin):.2f}"
                out["hpbw"] = f"{70 * lam / D:.2f}"
            elif kind == "yagi":
                N   = parse(self._param_edits["N"].text()) or 10
                if N < 2: N = 2
                # Empirical: boom length per element ≈ 0.20·λ for N≥3
                L_boom_lam = (N - 1) * 0.2
                L_boom_m   = L_boom_lam * lam
                # Stutzman/Thiele-style estimate vs boom length
                G_lin = 8.0 + 11.5 * L_boom_lam     # dBi-ish, rough
                out["L_boom_lam"] = f"{L_boom_lam:.2f}"
                out["L_boom_m"]   = f"{L_boom_m:.3g}"
                out["gain"]       = f"{G_lin:.1f}"
                out["hpbw"]       = f"{55 / sqrt(L_boom_lam + 0.5):.1f}"
            elif kind == "helix":
                N    = parse(self._param_edits["N"].text())     or 10
                D    = parse(self._param_edits["D_lam"].text()) or 0.318
                S    = parse(self._param_edits["S_lam"].text()) or 0.25
                axial_len_m = N * S * lam
                # Kraus' axial-mode formula:
                #   G ≈ 6.2 · C² · N · S    (linear, with C in λ, S in λ)
                C_lam = pi * D
                G_lin = 6.2 * C_lam * C_lam * N * S
                out["L_m"]  = f"{axial_len_m:.3g}"
                if G_lin > 0:
                    out["gain"] = f"{10*log10(G_lin):.2f}"
                out["hpbw"] = f"{52 / (C_lam * sqrt(N * S)):.2f}"
        except (ValueError, ZeroDivisionError, OverflowError):
            pass
        for name, lbl in self._result_labels.items():
            lbl.setText(out.get(name, "—"))

    # ---- persistence ----------
    def title(self):
        return "Antenna designer"

    def get_state(self):
        st = {"kind": self._current_kind, "freq": self.freq_edit.text()}
        # Save parameter inputs for the current kind
        st["params"] = {n: w.text() for n, w in self._param_edits.items()}
        return st

    def set_state(self, st):
        if not isinstance(st, dict): return
        kind = st.get("kind")
        if kind:
            for i, (k, _) in enumerate(self.KINDS):
                if k == kind:
                    self.type_combo.setCurrentIndex(i)
                    break
        if isinstance(st.get("freq"), str):
            self.freq_edit.setText(st["freq"])
        params = st.get("params") or {}
        for n, val in params.items():
            if n in self._param_edits and isinstance(val, str):
                self._param_edits[n].setText(val)
        self._recompute()

    def search_entries(self, tab_name):
        return [(f"{tab_name}  →  Frequency", self.freq_edit, self),
                (f"{tab_name}  →  Type",      self.type_combo, self)]

    def to_clipboard_text(self):
        lines = [self.type_combo.currentText(),
                 "-" * len(self.type_combo.currentText()),
                 f"  {'Frequency':<28s} {self.freq_edit.text()} MHz"]
        params, results = self.SCHEMA[self._current_kind]
        if params:
            lines.append("")
            lines.append("Parameters")
            for p in params:
                name, label, unit = p[0], p[1], p[2]
                w = self._param_edits.get(name)
                if w is None: continue
                u = f" {unit}" if unit else ""
                lines.append(f"  {label:<28s} {w.text()}{u}")
        lines.append("")
        lines.append("Results")
        for name, label, unit in results:
            lbl = self._result_labels.get(name)
            if lbl is None: continue
            txt = lbl.text()
            if txt == "—": continue
            u = f" {unit}" if unit else ""
            lines.append(f"  {label:<28s} {txt}{u}")
        return "\n".join(lines)


# ====================================================================
#  CAPACITOR ANALYZER TAB
# ====================================================================
#
# Browses an on-disk library of capacitor S-parameter files, organised by
# family / sub-family folders.  Lets the user:
#   * pick a target self-resonance frequency and find the two parts whose
#     measured SRF is closest;
#   * type a capacitance value and plot just that one part;
#   * toggle between S11 and S21 magnitude views.
#
# All data is loaded from disk at runtime (the user supplies their own
# manufacturer s-parameter files) — none of the measurement data lives in
# the source.
# --------------------------------------------------------------------

CAP_LIBRARY_ROOT = os.path.join(APP_DIR, "resource", "capacitors")


def _parse_cap_value_from_name(name):
    """Best-effort: extract the capacitance (farads) encoded in an s2p
    filename.  Tries family-aware patterns (Murata, AVX, generic 'pF'
    annotation) in order of specificity.  Returns the value in farads, or
    None if it can't be confidently decoded.

    Conventions covered:
      * Trailing annotation:  ..._<num>pF / nF / uF / fF
      * Murata GCQ / GJM / GRM:  ...<digit>R<digit>...  (R = decimal point,
            e.g. 'GJM1555C1H1R0BB01' → 1.0 pF; '0R6' → 0.6 pF)
      * AVX Accu-P sub-pF:  ...<int>r<int>$   ('C1005SE0r1' → 0.1 pF)
      * 3-digit EIA after SE/CE/CG/JA/UJ:  '...100' → 10 × 10⁰ pF
      * Generic '<a>p<b>' shorthand:  '4p7' → 4.7 pF (industry standard
            'p' as a decimal-point substitute)
    """
    base = os.path.basename(name)
    stem = os.path.splitext(base)[0]
    # 1) Explicit "<num>{p,n,u,µ,f}F" anywhere in the filename — most
    #    authoritative because data-sheets ship the value spelled out.
    m = re.search(r'(\d+(?:\.\d+)?)\s*(pF|nF|uF|µF|fF)', stem, re.IGNORECASE)
    if m:
        try:
            num = float(m.group(1))
            scale = {"pF": 1e-12, "nF": 1e-9,
                     "uF": 1e-6, "µF": 1e-6, "fF": 1e-15}[m.group(2)]
            return num * scale
        except (ValueError, KeyError):
            pass
    # 2) Murata-style "<digit>R<digit>" inside the body of the P/N.
    #    Anchor against the typical GCQ/GJM/GRM voltage code (C1H, C1E,
    #    C1V…) so we don't mis-identify the size code '1555' as a value.
    m = re.search(r'C\d[A-Z](\d)R(\d)[A-Z]', stem)
    if m:
        try:
            return (int(m.group(1)) + int(m.group(2)) / 10) * 1e-12
        except ValueError:
            pass
    # 3) AVX Accu-P sub-pF "Xr Y" form anchored at end of stem.
    m = re.search(r'(\d+)r(\d+)$', stem)
    if m:
        whole = int(m.group(1))
        frac  = m.group(2)
        try:
            return (whole + int(frac) / (10 ** len(frac))) * 1e-12
        except ValueError:
            pass
    # 3b) AVX Accu-P sub-pF series-code form 'SE[Ar]NN' anchored at end,
    #     e.g. 'C0201SEA05' (file P/N 02015JA05PBSTR) → 0.05 pF.
    #          'C0201SEr05' (file P/N 02011JR05ZBSTR) → 0.05 pF.
    #     The two letters distinguish AVX value-code class A vs R but encode
    #     the same numeric value 0.NN pF.
    m = re.search(r'SE[Ar](\d{2})$', stem)
    if m:
        try:
            return int(m.group(1)) / 100 * 1e-12
        except ValueError:
            pass
    # 4) 3-digit EIA code preceded by a series prefix (AVX / generic).
    m = re.search(r'(?:SE|CE|CG|JA|UJ)(\d)(\d)(\d)(?![A-Za-z\d])', stem)
    if m:
        d1, d2, mexp = m.group(1), m.group(2), m.group(3)
        try:
            return int(d1 + d2) * (10 ** int(mexp)) * 1e-12
        except ValueError:
            pass
    # 5) Generic "<a>p<b>" shorthand (common on Vishay / Yageo /
    #    KEMET — '4p7' = 4.7 pF, '1p0' = 1.0 pF) anchored at end of stem.
    m = re.search(r'(?<![A-Za-z])(\d+)p(\d+)$', stem)
    if m:
        try:
            return (int(m.group(1)) +
                    int(m.group(2)) / (10 ** len(m.group(2)))) * 1e-12
        except ValueError:
            pass
    return None


def _clean_cap_part_name(stem):
    """Strip the trailing '_DC<bias>_<value>pF' annotation that Murata
    bundles onto its s-parameter filenames so the displayed P/N is the
    actual orderable part number, e.g.

        'GCQ1555C1H100JB01_DC0V_10.0pF' → 'GCQ1555C1H100JB01'

    Other naming styles (AVX, TDK, generic) are returned unchanged."""
    return re.sub(r'_DC[\w.]*?(?:_[\d.]+\s*[a-zA-Z]F)?\s*$', '', stem)


def _fmt_cap(value_f):
    """Pretty-print a capacitance value.  pF is the default for anything
    sub-nF — sub-pF parts read as e.g. '0.6 pF' rather than '600 fF',
    matching the way the design kits / data-sheets label their parts."""
    if value_f is None:
        return "?"
    if value_f < 1e-9:
        return f"{value_f * 1e12:.3g} pF"
    if value_f < 1e-6:
        return f"{value_f * 1e9:.3g} nF"
    return f"{value_f * 1e6:.3g} µF"


class CapPlotCanvas(FigureCanvas if HAS_SMITH else QWidget):
    """matplotlib canvas for capacitor S-parameter traces.  Theme-aware
    (re-coloured when the global THEME global is flipped)."""

    PALETTE = ["#cc2222", "#2266cc", "#229933", "#cc8822",
               "#9933cc", "#118899", "#666666", "#bb1188"]

    def __init__(self, parent=None):
        if not HAS_SMITH:
            QWidget.__init__(self, parent)
            return
        self.fig = Figure(figsize=(7, 4), dpi=100, tight_layout=True)
        FigureCanvas.__init__(self, self.fig)
        self.ax = self.fig.add_subplot(111)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(360, 220)
        self._traces = []                # list of dicts (see add_trace)
        self._param  = "S11"             # "S11" or "S21"
        self._color_idx = 0
        self._family = ""                # set by tab via set_metadata()
        self._sub    = ""
        self._apply_theme()

    # ---- public API ----
    def set_param(self, name):
        if name not in ("S11", "S21"):
            return
        self._param = name
        self._redraw()

    def set_metadata(self, family, sub):
        """Family / sub-family captions baked into the plot title."""
        self._family = (family or "").strip()
        self._sub    = (sub    or "").strip()
        self._redraw()

    def add_trace(self, label, freqs, s11, s21, srf_hz=None,
                  part=None, cap_str=None):
        if not HAS_SMITH:
            return
        color = self.PALETTE[self._color_idx % len(self.PALETTE)]
        self._color_idx += 1
        # Pre-compute the equivalent attenuation at the SRF for both
        # ports — these go into the title so PowerPoint can pick up
        # everything without extra annotation overlap on the curve.
        s11_db_srf = self._db_at_freq(s11, freqs, srf_hz)
        s21_db_srf = self._db_at_freq(s21, freqs, srf_hz)
        self._traces.append({
            "label": label, "f": freqs, "s11": s11, "s21": s21,
            "srf":   srf_hz, "color": color,
            "part":  part or label, "cap_str": cap_str or "",
            "s11_db_srf": s11_db_srf, "s21_db_srf": s21_db_srf,
        })
        self._redraw()

    @staticmethod
    def _db_at_freq(s, f_array, target_f):
        """|s| in dB at target_f, linearly interpolated. None if no SRF."""
        if target_f is None or len(f_array) == 0:
            return None
        f_array = np.asarray(f_array)
        idx = int(np.searchsorted(f_array, target_f))
        if idx <= 0:
            return 20.0 * math.log10(max(abs(s[0]), 1e-12))
        if idx >= len(f_array):
            return 20.0 * math.log10(max(abs(s[-1]), 1e-12))
        f0, f1 = float(f_array[idx - 1]), float(f_array[idx])
        m0 = 20.0 * math.log10(max(abs(s[idx - 1]), 1e-12))
        m1 = 20.0 * math.log10(max(abs(s[idx]),     1e-12))
        if f1 == f0:
            return m0
        frac = (target_f - f0) / (f1 - f0)
        return m0 + (m1 - m0) * frac

    def _build_title(self):
        head = f"|{self._param}| vs frequency"
        ctx = self._family
        if self._sub and self._sub != "(this folder)":
            ctx = f"{self._family} / {self._sub}" if self._family else self._sub
        if ctx:
            head += f"   —   {ctx}"
        if not self._traces:
            return head
        # Build per-trace cells in fixed column order: SRF first (so the
        # eye lands on the resonant frequency immediately), then part
        # number, capacitance, |S11|@SRF, |S21|@SRF.  Each column gets
        # padded to the widest entry so the table aligns when rendered
        # in a monospace title font (set in _redraw).
        rows = []
        for t in self._traces:
            srf = t.get("srf")
            srf_txt = (f"SRF {srf/1e9:.3g} GHz"
                       if srf is not None else "SRF —")
            part_txt = t.get("part") or t.get("label") or ""
            cap_txt  = t.get("cap_str") or ""
            s11_db = t.get("s11_db_srf")
            s21_db = t.get("s21_db_srf")
            s11_txt = (f"|S11|@SRF {s11_db:+5.1f} dB"
                       if s11_db is not None else "")
            s21_txt = (f"|S21|@SRF {s21_db:+5.1f} dB"
                       if s21_db is not None else "")
            rows.append([srf_txt, part_txt, cap_txt, s11_txt, s21_txt])
        n_cols = len(rows[0])
        col_w = [max(len(r[c]) for r in rows) for c in range(n_cols)]
        lines = [head]
        for r in rows:
            lines.append("   ".join(f"{r[c]:<{col_w[c]}s}"
                                    for c in range(n_cols)))
        return "\n".join(lines)

    def remove_trace(self, label):
        self._traces = [t for t in self._traces if t["label"] != label]
        self._redraw()

    def clear(self):
        self._traces = []
        self._color_idx = 0
        self._redraw()

    def trace_labels(self):
        return [t["label"] for t in self._traces]

    # ---- theme ----
    def _apply_theme(self):
        if THEME == "dark":
            self._bg     = "#181818"
            self._grid   = "#3a3a40"
            self._axis   = "#7a7a80"
            self._text   = "#dddddd"
            self._marker = "#ffe48a"
        else:
            self._bg     = "#ffffff"
            self._grid   = "#bbbbbb"
            self._axis   = "#666666"
            self._text   = "#222222"
            self._marker = "#aa6600"
        if hasattr(self, "fig"):
            self.fig.patch.set_facecolor(self._bg)
            self.ax.set_facecolor(self._bg)
            self._redraw()

    # ---- drawing ----
    def _redraw(self):
        if not HAS_SMITH:
            return
        ax = self.ax
        ax.clear()
        ax.set_facecolor(self._bg)
        ax.grid(True, linestyle="--", alpha=0.7, color=self._grid)
        for spine in ax.spines.values():
            spine.set_color(self._axis)
        # Plot fonts ≈ 30% smaller than matplotlib defaults so the figure
        # fits cleanly when pasted into PowerPoint.
        ax.tick_params(colors=self._text, labelsize=7)
        ax.xaxis.label.set_color(self._text)
        ax.yaxis.label.set_color(self._text)
        ax.title.set_color(self._text)

        if not self._traces:
            ax.set_xlabel("Frequency (GHz)", fontsize=7)
            ax.set_ylabel(f"|{self._param}| (dB)", fontsize=7)
            ax.set_title(self._build_title() or
                         f"|{self._param}| — no trace plotted",
                         fontsize=8, color=self._text)
            self.fig.canvas.draw_idle()
            return

        # First pass: plot every curve and SRF marker, collecting label
        # positions for collision-aware placement afterwards.
        markers = []   # list of (srf_ghz, y_db, color, text)
        for t in self._traces:
            f_ghz = np.asarray(t["f"]) / 1e9
            s = t["s11"] if self._param == "S11" else t["s21"]
            mag_db = 20.0 * np.log10(np.maximum(np.abs(s), 1e-12))
            ax.plot(f_ghz, mag_db, color=t["color"], lw=1.2, label=t["label"])
            srf = t["srf"]
            if srf is None:
                continue
            f_arr = np.asarray(t["f"])
            idx = int(np.searchsorted(f_arr, srf))
            idx = min(max(idx, 1), len(f_arr) - 1)
            f0, f1 = f_arr[idx - 1], f_arr[idx]
            m0 = 20.0 * np.log10(max(abs(s[idx - 1]), 1e-12))
            m1 = 20.0 * np.log10(max(abs(s[idx]),     1e-12))
            frac = 0.0 if f1 == f0 else (srf - f0) / (f1 - f0)
            y = m0 + (m1 - m0) * frac
            ax.plot([srf / 1e9], [y], marker="o",
                    markersize=6, markerfacecolor=t["color"],
                    markeredgecolor=self._marker, markeredgewidth=1.2,
                    zorder=10)
            markers.append((srf / 1e9, y, t["color"],
                            f"{srf / 1e9:.3g} GHz"))

        # Second pass: place "<SRF> GHz" labels with vertical staggering
        # when two markers are close enough to overlap.  Stack index 0
        # sits above-right of the marker; 1 sits below-right; further
        # collisions fan out by ±10 pt per slot so labels never paint
        # on top of each other.
        if markers:
            xs = [m[0] for m in markers]
            ys = [m[1] for m in markers]
            x_range = max(max(xs) - min(xs), 1e-9)
            y_range = max(max(ys) - min(ys), 1e-9)
            x_thresh = max(x_range * 0.06, 0.05)
            y_thresh = max(y_range * 0.15, 3.0)
            stack = [0] * len(markers)
            for j in range(1, len(markers)):
                for k in range(j):
                    if (abs(markers[j][0] - markers[k][0]) < x_thresh
                            and abs(markers[j][1] - markers[k][1]) < y_thresh):
                        stack[j] = max(stack[j], stack[k] + 1)
            for (mx, my, mc, mt), s_idx in zip(markers, stack):
                if s_idx == 0:
                    x_off, y_off, va = 6, 5, "bottom"
                elif s_idx == 1:
                    x_off, y_off, va = 6, -5, "top"
                else:
                    side = 1 if s_idx % 2 == 0 else -1
                    x_off, y_off = 6, side * (5 + 10 * (s_idx // 2))
                    va = "bottom" if side > 0 else "top"
                ax.annotate(
                    mt,
                    xy=(mx, my),
                    xytext=(x_off, y_off), textcoords="offset points",
                    color=mc, fontsize=6,
                    va=va, ha="left", zorder=11,
                )

        ax.set_xlabel("Frequency (GHz)", fontsize=7)
        ax.set_ylabel(f"|{self._param}| (dB)", fontsize=7)
        leg = ax.legend(loc="best", fontsize=6, frameon=True)
        if leg is not None:
            leg.get_frame().set_facecolor(self._bg)
            leg.get_frame().set_edgecolor(self._grid)
            for txt in leg.get_texts():
                txt.set_color(self._text)
        # Centred above the plot, monospace so the per-column padding in
        # _build_title actually aligns visually.
        ax.set_title(self._build_title(), fontsize=8, color=self._text,
                     loc="center", fontfamily="monospace")
        self.fig.canvas.draw_idle()


class CapacitorAnalyzerTab(QWidget):
    """Browse on-disk capacitor S-parameter library; find parts by SRF;
    plot S11 / S21."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        if not HAS_SMITH:
            outer.addWidget(QLabel(
                "Capacitor analyzer needs matplotlib + scikit-rf:\n"
                f"  {_smith_err}"))
            return

        # ---- top row: family / sub-family / view toggle ----
        row = QHBoxLayout(); row.setSpacing(6)
        row.addWidget(QLabel("Family:"))
        self.family_cb = QComboBox()
        self.family_cb.setMinimumWidth(180)
        self.family_cb.currentIndexChanged.connect(self._on_family_changed)
        row.addWidget(self.family_cb)
        row.addSpacing(8)
        row.addWidget(QLabel("Sub-family:"))
        self.sub_cb = QComboBox()
        self.sub_cb.setMinimumWidth(140)
        self.sub_cb.currentIndexChanged.connect(self._on_sub_changed)
        row.addWidget(self.sub_cb)
        row.addSpacing(12)
        row.addWidget(QLabel("View:"))
        self.param_cb = QComboBox()
        self.param_cb.addItems(["S11", "S21"])
        self.param_cb.currentTextChanged.connect(self._on_param_changed)
        row.addWidget(self.param_cb)
        row.addStretch(1)
        outer.addLayout(row)

        # ---- second row: find by SRF + plot by value ----
        # The two QLineEdits self-document via placeholder text — no
        # 'Target SRF:' / 'Plot value:' labels eating horizontal space.
        row2 = QHBoxLayout(); row2.setSpacing(6)
        self.srf_edit = QLineEdit()
        self.srf_edit.setMaximumWidth(160); self.srf_edit.setMaximumHeight(20)
        self.srf_edit.setPlaceholderText("Target SRF (GHz) e.g. 2.4")
        self.srf_edit.setToolTip(
            "Self-resonance frequency to search for, in GHz "
            "(suffix-aware: 100M, 2.4G also accepted)")
        self.srf_edit.returnPressed.connect(self._on_find_srf)
        row2.addWidget(self.srf_edit)
        find_btn = QPushButton("Find 2 closest")
        find_btn.clicked.connect(self._on_find_srf)
        row2.addWidget(find_btn)
        row2.addSpacing(16)
        self.cap_edit = QLineEdit()
        self.cap_edit.setMaximumWidth(120); self.cap_edit.setMaximumHeight(20)
        self.cap_edit.setPlaceholderText("Plot value e.g. 10pF")
        self.cap_edit.setToolTip(
            "Capacitance value to plot — accepts engineering "
            "suffixes (10pF, 1n, 0.5p)")
        self.cap_edit.returnPressed.connect(self._on_plot_value)
        row2.addWidget(self.cap_edit)
        plot_btn = QPushButton("Plot")
        plot_btn.clicked.connect(self._on_plot_value)
        row2.addWidget(plot_btn)
        row2.addSpacing(16)
        clear_btn = QPushButton("Clear all")
        clear_btn.clicked.connect(self._on_clear_traces)
        row2.addWidget(clear_btn)
        copy_plot_btn = QPushButton("Copy plot")
        copy_plot_btn.setToolTip(
            "Copy the figure to the clipboard as a PNG image "
            "(also bound to Ctrl+C while this tab is active)")
        copy_plot_btn.clicked.connect(self._copy_figure)
        row2.addWidget(copy_plot_btn)
        row2.addStretch(1)
        outer.addLayout(row2)

        # ---- plot canvas ----
        self.canvas = CapPlotCanvas()
        self.canvas.set_param("S11")
        outer.addWidget(self.canvas, 1)

        # Hidden trace bookkeeping list — kept as a non-visible widget so
        # the rest of the tab (add/remove/clear paths) can still reference
        # `self.trace_list` without changes.  The previous "Traces:" panel
        # at the bottom of the tab is gone per user request — it took up
        # too much vertical space; removal is via "Clear all".
        self.trace_list = QListWidget()
        self.trace_list.setVisible(False)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#777; padding:0 4px;")
        outer.addWidget(self.status_label)

        # ---- internal state ----
        self._files     = []     # list of dicts: {part, cap_f, path, srf}
        self._cache     = {}     # path -> rf.Network (cached)
        # Debounced persist: writes family / sub-family back to the JSON
        # config a short while after a change.  Belt-and-braces with the
        # main window's closeEvent so the selection survives even if the
        # app exits without a clean shutdown.
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(400)
        self._persist_timer.timeout.connect(self._persist_state)

        # Ctrl+C → copy the figure (PNG image) to the clipboard so the user
        # can paste straight into PowerPoint / docs.  Falls through to the
        # focused QLineEdit's text-copy behaviour when an input has focus.
        copy_sc = QShortcut(QKeySequence("Ctrl+C"), self)
        copy_sc.setContext(Qt.WidgetWithChildrenShortcut)
        copy_sc.activated.connect(self._copy_figure_or_text)

        self._scan_top()

    # =====================================================================
    #  Library scanning
    # =====================================================================
    def _scan_top(self):
        self.family_cb.blockSignals(True)
        self.family_cb.clear()
        if not os.path.isdir(CAP_LIBRARY_ROOT):
            self.family_cb.addItem("(no library found)")
            self.family_cb.blockSignals(False)
            return
        names = sorted([n for n in os.listdir(CAP_LIBRARY_ROOT)
                        if os.path.isdir(os.path.join(CAP_LIBRARY_ROOT, n))])
        if not names:
            self.family_cb.addItem("(library empty)")
        else:
            for n in names:
                self.family_cb.addItem(n)
        self.family_cb.blockSignals(False)
        self._on_family_changed(0)

    def _scan_subfamilies(self, family):
        path = os.path.join(CAP_LIBRARY_ROOT, family)
        if not os.path.isdir(path):
            return []
        subs = sorted([n for n in os.listdir(path)
                       if os.path.isdir(os.path.join(path, n))])
        return subs

    def _scan_files(self, family, subfamily):
        """Build self._files: list of {part, cap_f, path}."""
        path = os.path.join(CAP_LIBRARY_ROOT, family)
        if subfamily:
            path = os.path.join(path, subfamily)
        if not os.path.isdir(path):
            self._files = []
            return
        out = []
        for n in os.listdir(path):
            if not n.lower().endswith((".s1p", ".s2p", ".s3p", ".s4p")):
                continue
            full = os.path.join(path, n)
            cap = _parse_cap_value_from_name(n)
            part = _clean_cap_part_name(os.path.splitext(n)[0])
            out.append({"part": part, "cap_f": cap, "path": full, "srf_hz": None})
        # Sort by capacitance, then by name
        out.sort(key=lambda r: (r["cap_f"] if r["cap_f"] is not None else 1e99,
                                r["part"]))
        self._files = out

    # =====================================================================
    #  s-parameter / SRF helpers
    # =====================================================================
    def _load_network(self, path):
        if path in self._cache:
            return self._cache[path]
        try:
            n = rf.Network(path)
        except Exception as e:
            self.status_label.setText(f"Failed to load {os.path.basename(path)}: {e}")
            return None
        self._cache[path] = n
        return n

    @staticmethod
    def _srf_from_network(n):
        """Self-resonance frequency: lowest frequency where Im(Z11) crosses
        zero from negative (capacitive) to positive (inductive)."""
        s11 = n.s[:, 0, 0]
        denom = 1.0 - s11
        # avoid /0; replace with tiny value
        denom = np.where(np.abs(denom) < 1e-12, 1e-12 + 0j, denom)
        z11 = 50.0 * (1.0 + s11) / denom
        im = z11.imag
        f = n.f
        # find sign change neg -> pos
        for i in range(len(im) - 1):
            if im[i] < 0.0 and im[i + 1] >= 0.0:
                if im[i + 1] == im[i]:
                    return float(f[i])
                # linear interpolation in frequency
                return float(f[i] + (f[i + 1] - f[i]) * (-im[i]) / (im[i + 1] - im[i]))
        # Fallback: frequency of min |S11| (works for series-mode caps too)
        try:
            mag = np.abs(s11)
            return float(f[int(np.argmin(mag))])
        except Exception:
            return None

    def _ensure_srf(self, file_rec):
        """Cache and return the SRF for a file record (None on failure)."""
        if file_rec["srf_hz"] is not None:
            return file_rec["srf_hz"]
        n = self._load_network(file_rec["path"])
        if n is None:
            return None
        srf = self._srf_from_network(n)
        file_rec["srf_hz"] = srf
        return srf

    # =====================================================================
    #  UI handlers
    # =====================================================================
    def _on_family_changed(self, _idx):
        family = self.family_cb.currentText()
        self.sub_cb.blockSignals(True)
        self.sub_cb.clear()
        subs = self._scan_subfamilies(family)
        if subs:
            for s in subs:
                self.sub_cb.addItem(s)
        else:
            self.sub_cb.addItem("(this folder)")
        self.sub_cb.blockSignals(False)
        self._on_sub_changed(0)
        self._update_canvas_metadata()
        self._persist_timer.start()

    def _on_sub_changed(self, _idx):
        family = self.family_cb.currentText()
        sub = self.sub_cb.currentText()
        if sub == "(this folder)":
            sub = ""
        self._scan_files(family, sub)
        self.status_label.setText(f"{len(self._files)} parts loaded from "
                                  f"{family}{('/' + sub) if sub else ''}")
        self._update_canvas_metadata()
        self._persist_timer.start()

    def _update_canvas_metadata(self):
        if hasattr(self, "canvas") and hasattr(self.canvas, "set_metadata"):
            sub = self.sub_cb.currentText()
            if sub == "(this folder)":
                sub = ""
            self.canvas.set_metadata(self.family_cb.currentText(), sub)

    def _persist_state(self):
        """Merge this tab's get_state() into the on-disk config so the
        family / sub-family selection survives even without a clean
        closeEvent.  Tolerates partial config files."""
        try:
            cfg = load_config() or {}
            if not isinstance(cfg.get("special_tabs"), dict):
                cfg["special_tabs"] = {}
            cfg["special_tabs"]["SRF"] = self.get_state()
            # Drop the old key from when this tab was named "Capacitors"
            # so we don't keep two stale copies hanging around.
            cfg["special_tabs"].pop("Capacitors", None)
            save_config(cfg)
        except Exception:
            pass

    # ---------------- clipboard formatters --------------------------
    def to_clipboard_mime(self):
        """Bundle the plot image + the summary text into a single
        QMimeData so 'Copy current tab' (Ctrl+Shift+C) puts BOTH on the
        clipboard.  PowerPoint / Word paste pulls the image; a plain
        text editor pulls the trace summary.  Returns None if matplotlib
        isn't loaded or there's no figure to copy."""
        if not HAS_SMITH or not hasattr(self, "canvas") \
                or not hasattr(self.canvas, "fig"):
            return None
        from io import BytesIO
        from PyQt5.QtGui import QImage
        from PyQt5.QtCore import QMimeData, QByteArray
        try:
            buf = BytesIO()
            fig = self.canvas.fig
            fig.savefig(buf, format="png", dpi=180,
                        facecolor=fig.get_facecolor())
            png_bytes = buf.getvalue()
            img = QImage()
            if not img.loadFromData(png_bytes, "PNG"):
                return None
        except Exception:
            return None
        mime = QMimeData()
        mime.setImageData(img)
        mime.setData("image/png", QByteArray(png_bytes))
        text = self.to_clipboard_text()
        if text:
            mime.setText(text)
        return mime

    def _copy_figure(self):
        """Render the matplotlib figure to a PNG and place it on the
        clipboard.  On Windows we go straight through win32clipboard so
        the data is owned by Windows (not Qt), and CF_DIB is set without
        the OLE-private-data chunk that confuses PowerPoint."""
        if not HAS_SMITH or not hasattr(self, "canvas") \
                or not hasattr(self.canvas, "fig"):
            self.status_label.setText("No figure to copy.")
            return
        try:
            from io import BytesIO
            from PyQt5.QtGui import QImage
            buf = BytesIO()
            fig = self.canvas.fig
            fig.savefig(buf, format="png", dpi=180,
                        facecolor=fig.get_facecolor())
            png_bytes = buf.getvalue()
            img = QImage()
            if not img.loadFromData(png_bytes, "PNG"):
                self.status_label.setText("Copy failed: PNG decode error.")
                return
            if sys.platform == "win32":
                _set_clipboard_image_native(img, png_bytes=png_bytes)
            else:
                from PyQt5.QtCore import QMimeData, QByteArray
                mime = QMimeData()
                mime.setImageData(img)
                mime.setData("image/png", QByteArray(png_bytes))
                QApplication.clipboard().setMimeData(mime)
            self.status_label.setText(
                f"Plot copied to clipboard ({img.width()}×{img.height()} px).")
        except Exception as exc:
            self.status_label.setText(f"Copy failed: {exc}")

    def _copy_figure_or_text(self):
        """Ctrl+C handler: defer to QLineEdit's native text-copy when an
        input has focus, otherwise copy the figure."""
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.copy()
            return
        self._copy_figure()

    def _on_param_changed(self, name):
        self.canvas.set_param(name)

    def _on_find_srf(self):
        # Field is labelled GHz: a bare number means GHz; an SI prefix
        # (k/M/G) is taken as absolute Hz and renormalised back to GHz.
        target_ghz = parse_field(self.srf_edit.text(), "GHz")
        if target_ghz is None or target_ghz <= 0:
            self.status_label.setText("Enter a target self-resonance frequency.")
            return
        target = target_ghz * 1e9   # internal storage is Hz
        if not self._files:
            self.status_label.setText("No parts loaded.")
            return
        # Compute SRF for each file (lazy-load each network on demand)
        results = []
        for rec in self._files:
            srf = self._ensure_srf(rec)
            if srf is not None:
                results.append((abs(srf - target), rec, srf))
        if not results:
            self.status_label.setText("Could not measure SRF in any part.")
            return
        results.sort(key=lambda x: x[0])
        # Plot the two closest (or one if only one)
        for _delta, rec, srf in results[:2]:
            self._add_or_replace_trace(rec, srf)
        ranks = "  ".join(f"{rec['part']}={srf/1e9:.3g}GHz"
                          for _, rec, srf in results[:2])
        self.status_label.setText(f"Target {target/1e9:.3g} GHz → {ranks}")

    def _on_plot_value(self):
        raw = (self.cap_edit.text() or "").strip()
        # Normalise "<num>pF / nF / uF / µF / fF / F" → engineering suffix
        # parse() understands.
        norm = raw
        for unit, suff in (("pF", "p"), ("nF", "n"), ("uF", "u"),
                           ("µF", "u"), ("fF", "f"), ("mF", "m")):
            if norm.lower().endswith(unit.lower()):
                norm = norm[: -len(unit)] + suff
                break
        else:
            # bare "F" with no prefix → drop it (1e0 farads, very rare)
            if norm.endswith("F") and not norm.endswith(("pF", "nF", "uF", "fF", "mF")):
                norm = norm[:-1]
        v = parse(norm)
        if v is None or v <= 0:
            self.status_label.setText("Enter a capacitance value (e.g. 10pF, 1n).")
            return
        # If the user typed bare number (no SI prefix), default to pF —
        # almost every cap in the library is sized in pF.
        last_char = norm[-1:] if norm else ""
        if last_char not in "TGMkKmunpfµ":
            v *= 1e-12
        if not self._files:
            self.status_label.setText("No parts loaded.")
            return
        with_caps = [r for r in self._files if r["cap_f"] is not None]
        if not with_caps:
            self.status_label.setText(
                "No capacitance values could be parsed from filenames.")
            return
        best = min(with_caps, key=lambda r: abs(r["cap_f"] - v))
        srf = self._ensure_srf(best)
        self._add_or_replace_trace(best, srf)
        self.status_label.setText(
            f"Closest to {_fmt_cap(v)}: {best['part']} ({_fmt_cap(best['cap_f'])})"
        )

    def _add_or_replace_trace(self, rec, srf_hz):
        # Avoid duplicate plots of the same part (compare on the bare P/N
        # since the canvas label also bakes in the capacitance string).
        if rec["part"] in [t.get("part") for t in self.canvas._traces]:
            return
        n = self._load_network(rec["path"])
        if n is None:
            return
        s11 = n.s[:, 0, 0]
        try:
            s21 = n.s[:, 1, 0]
        except Exception:
            s21 = s11           # 1-port file: degrade gracefully
        cap_str = _fmt_cap(rec["cap_f"])
        label = f"{rec['part']}  ({cap_str})"
        self.canvas.add_trace(label, n.f, s11, s21, srf_hz=srf_hz,
                              part=rec["part"], cap_str=cap_str)
        # Update list widget
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, rec["part"])
        self.trace_list.addItem(item)

    def _on_clear_traces(self):
        self.trace_list.clear()
        self.canvas.clear()

    # =====================================================================
    #  Persistence + finder integration
    # =====================================================================
    def title(self):
        return "Capacitor analyzer"

    def get_state(self):
        return {
            "family": self.family_cb.currentText(),
            "sub":    self.sub_cb.currentText(),
            "param":  self.param_cb.currentText(),
            "srf":    self.srf_edit.text(),
            "cap":    self.cap_edit.text(),
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        fam = st.get("family")
        if isinstance(fam, str):
            ix = self.family_cb.findText(fam)
            if ix >= 0:
                self.family_cb.setCurrentIndex(ix)
        sub = st.get("sub")
        if isinstance(sub, str):
            ix = self.sub_cb.findText(sub)
            if ix >= 0:
                self.sub_cb.setCurrentIndex(ix)
        if isinstance(st.get("param"), str):
            ix = self.param_cb.findText(st["param"])
            if ix >= 0:
                self.param_cb.setCurrentIndex(ix)
        if isinstance(st.get("srf"), str): self.srf_edit.setText(st["srf"])
        if isinstance(st.get("cap"), str): self.cap_edit.setText(st["cap"])

    def search_entries(self, tab_name):
        return [
            (f"{tab_name}  →  Family",       self.family_cb, self),
            (f"{tab_name}  →  Sub-family",   self.sub_cb,    self),
            (f"{tab_name}  →  Target SRF",   self.srf_edit,  self),
            (f"{tab_name}  →  Plot value",   self.cap_edit,  self),
        ]

    def to_clipboard_text(self):
        lines = [f"Family:     {self.family_cb.currentText()}",
                 f"Sub-family: {self.sub_cb.currentText()}",
                 f"View:       {self.param_cb.currentText()}",
                 ""]
        if self._files:
            lines.append(f"Parts in selection: {len(self._files)}")
        if self.canvas.trace_labels():
            lines.append("")
            lines.append("Plotted:")
            for lbl in self.canvas.trace_labels():
                lines.append(f"  {lbl}")
        return "\n".join(lines)


# ====================================================================
#  DUAL-STAGE FREQUENCY CONVERTER  +  SPUR-SOURCE FINDER
# ====================================================================
#
# Two cascaded mixers:    IF  →  M1 (LO1)  →  IF2  →  M2 (LO2)  →  RF
# Each mixer produces an output at  f_out = f_in ± f_LO, with the user
# selecting low-side (sum) or high-side (difference) injection.  The
# top half of the tab plans the chain by computing IF2 / RF ranges from
# the IF and LO ranges; the bottom half is a spur-source finder that
# enumerates (m1, n1, m2, n2) harmonic-product combinations whose
# resulting output frequency is close to a given spur observation.
# --------------------------------------------------------------------

def _fmt_mhz(v):
    if v is None:
        return "—"
    if abs(v) >= 1e3:
        return f"{v/1e3:.4f} GHz"
    if abs(v) < 1.0:
        return f"{v*1e3:.4f} kHz"
    return f"{v:.4f} MHz"


def _fmt_ghz(v):
    """Format a frequency value (already interpreted as GHz) for display.
    Used by the Converter tab where every numeric input/readout is in GHz."""
    if v is None:
        return "—"
    return f"{v:g} GHz"


# --------------------------------------------------------------------
# Spur-source description helpers — pure functions that take an
# (m1, n1, m2, n2) tuple and the converter sideband settings and return:
#   math   – algebraic expression like "2 × (LO1 - IF)"
#   title  – plain English: "Second harmonic of IF2"
#   where  – which mixer first generated the spur: "Mixer 1"
# --------------------------------------------------------------------

_ORDINAL = ("Zero", "Fundamental", "Second", "Third", "Fourth", "Fifth",
            "Sixth", "Seventh", "Eighth", "Ninth", "Tenth")


def _ordinal_word(n):
    n = abs(int(n))
    if n < len(_ORDINAL):
        return _ORDINAL[n]
    return f"{n}th"


def _spur_stage1_expr(sb1):
    """The algebraic form of IF2 in terms of LO1, IF for sideband sb1."""
    return "LO1 - IF" if sb1 == "low" else "LO1 + IF"


def _spur_stage2_expr(sb2):
    """The algebraic form of RF in terms of LO2, IF2 for sideband sb2."""
    return "LO2 - IF2" if sb2 == "low" else "LO2 + IF2"


def _coeff_term(coeff, name):
    """Format a single signed coefficient × symbol term for inclusion in
    a spur math expression.  Returns '' for zero coeffs so the caller can
    skip them; otherwise things like 'LO1', '-IF', '2·LO1'."""
    if coeff == 0:
        return ""
    if coeff == 1:
        return name
    if coeff == -1:
        return f"-{name}"
    return f"{coeff}·{name}"


def _signed_combine(*pairs):
    """Join (coeff, symbol) terms with proper '+' / '-' separators.
    Unlike _coeff_term the SECOND-and-later positive terms get a leading
    ' + '; negative terms become ' - <abs(coeff)>·<name>'.  Zero coeffs
    are omitted; an all-zero list returns '0'."""
    out = ""
    for coeff, name in pairs:
        if coeff == 0:
            continue
        if not out:
            out = _coeff_term(coeff, name)
        else:
            if coeff > 0:
                out += " + " + (name if coeff == 1 else f"{coeff}·{name}")
            else:
                ac = -coeff
                out += " - " + (name if ac == 1 else f"{ac}·{name}")
    return out or "0"


def _harmonic_label(k, base):
    """k=±1 → just `base` (or `-base`); k=±2 → '2 × base' / '-2 × base'.
    Wraps `base` in parens only when the surrounding context could
    mis-parse it (i.e. when |k| > 1 or k == -1 and base has operators)."""
    needs_parens = any(c in base for c in "+-")
    if k == 1:
        return base
    if k == -1:
        return f"-({base})" if needs_parens else f"-{base}"
    inner = f"({base})" if needs_parens else base
    return f"{k} × {inner}"


def _describe_spur(m1, n1, m2, n2, sb1, use_stage2):
    """Return (math, title, where) for an (m1,n1,m2,n2) spur tuple.

    Recognises common factorings:
      • k·LO1 + (±k)·IF    →  k × IF2  (when the sign matches sb1)
      • m1·LO1, n1·IF only →  harmonic of LO1 / IF
      • m2·LO2 alone       →  harmonic of LO2

    sb1 picks LO1 - IF (low) vs LO1 + IF (high).  use_stage2=False means
    the chain is single-stage — pretend the second mixer is a wire.
    """
    if1_sign = -1 if sb1 == "low" else 1   # sign of IF inside IF2

    # ---- stage-1 product f1 = m1·LO1 + n1·IF  -----------------------
    if m1 == 0 and n1 == 0:
        f1_math, f1_title = "0", ""
    elif m1 == 0:
        f1_math = _harmonic_label(n1, "IF")
        f1_title = (f"{_ordinal_word(n1)} harmonic of IF"
                    if abs(n1) > 1 else "IF")
    elif n1 == 0:
        f1_math = _harmonic_label(m1, "LO1")
        f1_title = (f"{_ordinal_word(m1)} harmonic of LO1"
                    if abs(m1) > 1 else "LO1")
    elif n1 == if1_sign * m1:
        # m1·LO1 + (if1_sign·m1)·IF = m1·(LO1 ± IF) = m1·IF2
        # Show both the expanded form (user-preferred) and the IF2 form
        # in the title.
        f1_math = _harmonic_label(m1, _spur_stage1_expr(sb1))
        f1_title = (f"{_ordinal_word(m1)} harmonic of IF2"
                    if abs(m1) > 1 else "IF2")
    else:
        f1_math = _signed_combine((m1, "LO1"), (n1, "IF"))
        f1_title = f1_math      # generic – just echo the math

    # ---- stage-2 product f_out = m2·LO2 + n2·f1  --------------------
    if not use_stage2:
        return f1_math, f1_title, "Mixer 1"

    if m2 == 0 and n2 == 0:
        return "0", "", "—"

    if n2 == 0 and m2 != 0:
        # Pure LO2 harmonic — the IF2 input plays no role.
        out_math = _harmonic_label(m2, "LO2")
        out_title = (f"{_ordinal_word(m2)} harmonic of LO2"
                     if abs(m2) > 1 else "LO2")
        return out_math, out_title, "Mixer 2 (LO2 alone)"

    if m2 == 0:
        # f_out = n2·f1.  Title is "<ordinal> harmonic of <stage-1 title>".
        out_math = _harmonic_label(n2, f1_math)
        if abs(n2) == 1:
            out_title = f1_title
        else:
            # If the stage-1 product already had its own ordinal (e.g.
            # "2nd harmonic of IF2"), saying "Nth harmonic of 2nd
            # harmonic of IF2" reads badly.  Prefer the expanded math.
            out_title = (f"{_ordinal_word(n2)} harmonic of "
                         + (f1_title or "stage-1 product"))
        # The spur was born in mixer 1 — mixer 2 just multiplied it
        # against the LO=0 component (i.e. passed it through).
        return out_math, out_title, "Mixer 1"

    # General case: both stages contribute.
    f1_part = f"({f1_math})" if any(c in f1_math for c in "+-·") else f1_math
    out_math = _signed_combine((m2, "LO2"), (n2, f1_part))
    if abs(n2) == 1:
        # "LO2 ± (stage-1)" — describe naturally
        sign = "+" if (n2 == 1) else "-"
        out_title = (f"{_ordinal_word(m2)} harmonic of LO2"
                     if abs(m2) > 1 else "LO2") + f" {sign} ({f1_title})"
    else:
        out_title = f"{_signed_combine((m2, 'LO2'), (n2, 'IF2'))}"
    return out_math, out_title, "Both mixers"


class _ExprNumericItem(QTableWidgetItem):
    """QTableWidgetItem that compares by an attached numeric value so the
    Frequency / Order columns sort numerically instead of lexicographically."""

    def __init__(self, text, value):
        super().__init__(text)
        self._num = value

    def __lt__(self, other):
        if isinstance(other, _ExprNumericItem):
            return self._num < other._num
        return super().__lt__(other)


class _ExprStageItem(QTableWidgetItem):
    """Stage-column item.  Default sort follows the chain order (IF, LO1,
    Mixer 1, IF2, LO2, Mixer 2, RF) rather than alphabetical."""

    def __init__(self, text, idx):
        super().__init__(text)
        self._idx = idx

    def __lt__(self, other):
        if isinstance(other, _ExprStageItem):
            return self._idx < other._idx
        return super().__lt__(other)


def _fmt_aligned_term(k, name):
    """One-term  'k × name'  with a 2-wide signed coefficient so positive
    and negative coefficients line up under a monospace font."""
    return f"{k:>2d} × {name}"


def _fmt_aligned_mix(m, n, name1, name2):
    """Two-term 'm × name1  ±  n × name2' with both coefficients padded
    to 2 chars so the operator and the second term align column-wise."""
    a = f"{m:>2d} × {name1}"
    if n == 0:
        return a
    sgn = "+" if n > 0 else "-"
    return f"{a} {sgn} {abs(n):>1d} × {name2}"


class ChainBoardWidget(QWidget):
    """Dual-stage mixer chain board — the IF / LO1 / LO2 input groups,
    sideband radios, and IF2 / RF readouts live inside the diagram, and
    the signal-line arrows and mixer circles are painted around them.

    The host (``DualStageConverterTab``) reads the children directly
    (``self.if_lo`` etc.) for compute / persistence.  Signal-flow arrows
    auto-track widget geometries — no manual coordinates."""

    @staticmethod
    def _mhz(default, maxw=52):
        e = QLineEdit(default)
        e.setMaximumHeight(20)
        e.setMinimumWidth(38)
        e.setMaximumWidth(maxw)
        return e

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(530)
        self.setMinimumWidth(460)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # ----- IF inputs (values in GHz) -----
        self.if_lo  = self._mhz("0.1")
        self.if_hi  = self._mhz("0.2")
        self.if_pwr = self._mhz("-10", 44); self.if_pwr.setToolTip("dBm")
        # ----- LO1 inputs (GHz) -----
        self.lo1_lo  = self._mhz("0.9")
        self.lo1_hi  = self._mhz("1.0")
        self.lo1_pwr = self._mhz("13", 44)
        # ----- LO2 inputs (GHz) -----
        self.lo2_lo  = self._mhz("1.2")
        self.lo2_hi  = self._mhz("1.4")
        self.lo2_pwr = self._mhz("13", 44)

        # ----- Sideband radios -----
        self.sb1_low  = QRadioButton("low")
        self.sb1_high = QRadioButton("high")
        self.sb1_low.setChecked(True)
        bg1 = QButtonGroup(self); bg1.addButton(self.sb1_low); bg1.addButton(self.sb1_high)
        self.sb2_low  = QRadioButton("low")
        self.sb2_high = QRadioButton("high")
        self.sb2_low.setChecked(True)
        bg2 = QButtonGroup(self); bg2.addButton(self.sb2_low); bg2.addButton(self.sb2_high)

        # ----- Stage-2 toggle (top-right header) -----
        self.use_stage2 = QCheckBox("Use stage 2")
        self.use_stage2.setChecked(True)

        # ----- Readouts -----
        self.if2_formula = QLabel("= LO1 − IF")
        self.if2_formula.setStyleSheet("color:#666;")
        self.if2_formula.setAlignment(Qt.AlignCenter)
        self.if2_out = QLabel("—")
        self.if2_out.setStyleSheet("color:#557; font-weight:bold;")
        self.if2_out.setAlignment(Qt.AlignCenter)
        self.if2_out.setWordWrap(True)
        self.rf_formula = QLabel("= LO2 − IF2")
        self.rf_formula.setStyleSheet("color:#666;")
        self.rf_formula.setAlignment(Qt.AlignCenter)
        self.rf_out = QLabel("—")
        self.rf_out.setStyleSheet("color:#175; font-weight:bold;")
        self.rf_out.setAlignment(Qt.AlignCenter)
        self.rf_out.setWordWrap(True)

        # ----- Block widgets (visible cells in the grid) -----
        self._if_box  = self._build_io_block("IF",  self.if_lo,  self.if_hi,  self.if_pwr)
        self._lo1_box = self._build_io_block("LO1", self.lo1_lo, self.lo1_hi, self.lo1_pwr)
        self._lo2_box = self._build_io_block("LO2", self.lo2_lo, self.lo2_hi, self.lo2_pwr)
        self._if2_box = self._build_readout_block("IF2", self.if2_formula, self.if2_out)
        self._rf_box  = self._build_readout_block("RF",  self.rf_formula,  self.rf_out)
        self._sb1_box = self._build_sb_box(self.sb1_low, self.sb1_high)
        self._sb2_box = self._build_sb_box(self.sb2_low, self.sb2_high)
        # Spacers reserve room for the painted mixer circles.
        self._m1_spacer = QWidget(); self._m1_spacer.setMinimumSize(48, 48)
        self._m2_spacer = QWidget(); self._m2_spacer.setMinimumSize(48, 48)

        # ----- Layout -----
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 2, 6, 2); outer.setSpacing(2)
        top = QHBoxLayout(); top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.use_stage2); top.addStretch(1)
        outer.addLayout(top)

        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8); g.setVerticalSpacing(2)
        outer.addLayout(g)

        # Row 0 (signal level)
        g.addWidget(self._if_box,    0, 0, alignment=Qt.AlignCenter)
        g.addWidget(self._m1_spacer, 0, 1, alignment=Qt.AlignCenter)
        g.addWidget(self._if2_box,   0, 2, alignment=Qt.AlignCenter)
        g.addWidget(self._m2_spacer, 0, 3, alignment=Qt.AlignCenter)
        g.addWidget(self._rf_box,    0, 4, alignment=Qt.AlignCenter)
        # Row 1 (sideband radios)
        g.addWidget(self._sb1_box,   1, 1, alignment=Qt.AlignCenter)
        g.addWidget(self._sb2_box,   1, 3, alignment=Qt.AlignCenter)
        # Row 2 (LO inputs)
        g.addWidget(self._lo1_box,   2, 1, alignment=Qt.AlignCenter)
        g.addWidget(self._lo2_box,   2, 3, alignment=Qt.AlignCenter)
        for c in range(5):
            g.setColumnStretch(c, 1)

        # ----- Internal wiring -----
        self.use_stage2.toggled.connect(self._apply_stage2_state)
        for rb in (self.sb1_low, self.sb1_high,
                   self.sb2_low, self.sb2_high):
            rb.toggled.connect(self._refresh_formulas)
        self._refresh_formulas()
        self._apply_stage2_state(True)

    @staticmethod
    def _styled_frame():
        """Bordered, opaque-fill frame so painted arrows clearly stop at
        the box edges.  Uses the standard window color so the block
        looks like part of the form, not like a data-entry control."""
        f = QFrame()
        f.setFrameShape(QFrame.Box)
        f.setLineWidth(1)
        f.setAutoFillBackground(True)
        pal = f.palette()
        pal.setColor(QPalette.Window,
                     pal.color(QPalette.Active, QPalette.Window))
        f.setPalette(pal)
        return f

    @staticmethod
    def _title_label(name):
        l = QLabel(name)
        l.setAlignment(Qt.AlignCenter)
        l.setStyleSheet("font-weight: bold; padding: 0px;")
        return l

    def _build_io_block(self, name, lo, hi, pwr):
        box = self._styled_frame()
        v = QVBoxLayout(box); v.setContentsMargins(4, 2, 4, 2); v.setSpacing(1)
        v.addWidget(self._title_label(name))
        r = QHBoxLayout(); r.setContentsMargins(0, 0, 0, 0); r.setSpacing(1)
        r.addWidget(lo); r.addWidget(QLabel("–"))
        r.addWidget(hi); r.addWidget(QLabel("GHz"))
        v.addLayout(r)
        pw = QHBoxLayout(); pw.setContentsMargins(0, 0, 0, 0); pw.setSpacing(1)
        pw.addStretch(1); pw.addWidget(pwr); pw.addWidget(QLabel("dBm")); pw.addStretch(1)
        v.addLayout(pw)
        return box

    def _build_readout_block(self, name, formula_lbl, value_lbl):
        box = self._styled_frame()
        v = QVBoxLayout(box); v.setContentsMargins(4, 2, 4, 2); v.setSpacing(1)
        v.addWidget(self._title_label(name))
        v.addWidget(formula_lbl)
        v.addWidget(value_lbl)
        return box

    def _build_sb_box(self, low_rb, high_rb):
        # Lay the radios horizontally with a stretch in the middle so the
        # vertical LO arrow drops cleanly through the gap between them
        # instead of overlapping the radio bullets.
        f = QFrame()
        h = QHBoxLayout(f); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        h.addWidget(low_rb)
        h.addStretch(1)
        h.addWidget(high_rb)
        return f

    def _apply_stage2_state(self, on):
        for w in (self.lo2_lo, self.lo2_hi, self.lo2_pwr,
                  self.sb2_low, self.sb2_high):
            w.setEnabled(on)
        self._sb2_box.setVisible(on)
        self._lo2_box.setVisible(on)
        self._rf_box.setVisible(on)
        self._m2_spacer.setVisible(on)
        self._refresh_formulas()
        self.update()

    def _refresh_formulas(self):
        op1 = "−" if self.sb1_low.isChecked() else "+"
        op2 = "−" if self.sb2_low.isChecked() else "+"
        if self.use_stage2.isChecked():
            self.if2_formula.setText(f"= LO1 {op1} IF")
            self.rf_formula.setText(f"= LO2 {op2} IF2")
        else:
            self.if2_formula.setText(f"= LO1 {op1} IF   (final)")
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        line_color = QColor("#666")
        accent     = QColor("#222")
        mixer_fill = QColor("#fafafa")
        mixer_r = 18

        if_geo  = self._if_box.geometry()
        if2_geo = self._if2_box.geometry()
        rf_geo  = self._rf_box.geometry()
        m1_geo  = self._m1_spacer.geometry()
        m2_geo  = self._m2_spacer.geometry()
        lo1_geo = self._lo1_box.geometry()
        lo2_geo = self._lo2_box.geometry()

        signal_y = if_geo.y() + if_geo.height() // 2
        m1_x = m1_geo.x() + m1_geo.width() // 2
        m2_x = m2_geo.x() + m2_geo.width() // 2

        def arrow_h(x1, x2, y):
            if x2 - x1 < 12:
                return
            p.setPen(QPen(line_color, 2))
            p.drawLine(x1, y, x2 - 6, y)
            head = QPolygon([QPoint(x2, y),
                             QPoint(x2 - 9, y - 5),
                             QPoint(x2 - 9, y + 5)])
            p.setBrush(line_color); p.setPen(QPen(line_color, 1))
            p.drawPolygon(head)

        def arrow_v_up(x, y_bottom, y_top):
            if y_bottom - y_top < 12:
                return
            p.setPen(QPen(line_color, 2))
            p.drawLine(x, y_bottom, x, y_top + 6)
            head = QPolygon([QPoint(x, y_top),
                             QPoint(x - 5, y_top + 9),
                             QPoint(x + 5, y_top + 9)])
            p.setBrush(line_color); p.setPen(QPen(line_color, 1))
            p.drawPolygon(head)

        def mixer(x, y, label):
            p.setPen(QPen(accent, 2))
            p.setBrush(mixer_fill)
            p.drawEllipse(x - mixer_r, y - mixer_r,
                          2 * mixer_r, 2 * mixer_r)
            d = mixer_r - 7
            p.drawLine(x - d, y - d, x + d, y + d)
            p.drawLine(x - d, y + d, x + d, y - d)
            p.setFont(QFont("Tahoma", 9, QFont.Bold))
            p.setPen(QPen(accent))
            fm = QFontMetrics(p.font())
            p.drawText(x - fm.horizontalAdvance(label) // 2,
                       y - mixer_r - 4, label)

        # Stage-1 chain
        arrow_h(if_geo.right() + 2,  m1_x - mixer_r - 2, signal_y)
        arrow_h(m1_x + mixer_r + 2,  if2_geo.left() - 2, signal_y)
        mixer(m1_x, signal_y, "M1")
        arrow_v_up(m1_x, lo1_geo.y() - 4, signal_y + mixer_r)
        # Stage-2 chain
        if self.use_stage2.isChecked():
            arrow_h(if2_geo.right() + 2, m2_x - mixer_r - 2, signal_y)
            arrow_h(m2_x + mixer_r + 2,  rf_geo.left() - 2,  signal_y)
            mixer(m2_x, signal_y, "M2")
            arrow_v_up(m2_x, lo2_geo.y() - 4, signal_y + mixer_r)
        p.end()


class DualStageConverterTab(QWidget):
    """Frequency-plan helper for a two-mixer up- or down-converter, with
    an attached harmonic-spur source finder."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _root = QVBoxLayout(self)
        _root.setContentsMargins(10, 8, 10, 8)
        _root.setSpacing(6)

        self._subtabs = QTabWidget()
        _root.addWidget(self._subtabs, 1)

        plan_page = QWidget()
        outer = QVBoxLayout(plan_page)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(6)
        self._subtabs.addTab(plan_page, "Plan / Spurs")

        # ---------------- chain board (figure + inputs combined) -----
        self._board = ChainBoardWidget()
        # Promote the board's editable widgets to self.* so the existing
        # _recompute_plan / get_state / set_state methods keep working
        # unchanged.
        for name in ("if_lo", "if_hi", "if_pwr",
                     "lo1_lo", "lo1_hi", "lo1_pwr",
                     "lo2_lo", "lo2_hi", "lo2_pwr",
                     "sb1_low", "sb1_high", "sb2_low", "sb2_high",
                     "use_stage2", "if2_out", "rf_out"):
            setattr(self, name, getattr(self._board, name))
        # Left-anchor the board so it stays visible at a 600 px window
        # width — centering wastes horizontal space and pushes the right
        # half of the diagram off the visible tab area on narrow windows.
        board_row = QHBoxLayout(); board_row.setContentsMargins(0, 0, 0, 0)
        board_row.addWidget(self._board); board_row.addStretch(1)
        outer.addLayout(board_row)

        # ---------------- Desired RF target row ----------------------
        target_row = QHBoxLayout(); target_row.setContentsMargins(0, 0, 0, 0); target_row.setSpacing(4)
        target_row.addStretch(1)
        target_row.addWidget(QLabel("Desired RF:"))
        self.rf_lo = self._mhz_edit("2.2")
        self.rf_hi = self._mhz_edit("2.4")
        target_row.addWidget(self.rf_lo)
        target_row.addWidget(QLabel("–"))
        target_row.addWidget(self.rf_hi)
        target_row.addWidget(QLabel("GHz"))
        self.rf_match = QLabel("")
        self.rf_match.setStyleSheet("color:#666; padding:0 6px;")
        target_row.addWidget(self.rf_match)
        target_row.addStretch(1)
        outer.addLayout(target_row)

        # ---------------- Wire change-handlers -----------------------
        edits = (self.if_lo, self.if_hi, self.if_pwr,
                 self.lo1_lo, self.lo1_hi, self.lo1_pwr,
                 self.lo2_lo, self.lo2_hi, self.lo2_pwr,
                 self.rf_lo, self.rf_hi)
        for e in edits:
            e.textEdited.connect(lambda *_: self._recompute_plan())
        for rb in (self.sb1_low, self.sb1_high, self.sb2_low, self.sb2_high):
            rb.toggled.connect(lambda *_: self._recompute_plan())
            rb.toggled.connect(lambda *_: self._refresh_spur_inputs()
                               if hasattr(self, "spur_if2") else None)
        self.use_stage2.toggled.connect(self._on_stage2_toggled)

        # ---------------- spur finder ----------------
        # IF2 and RF are derived from IF + M1 (+ M2 if stage 2 is on) using
        # the sideband selectors above — so the user only types IF, M1, M2.
        spur = QGroupBox("Spur source finder")
        sl = QGridLayout(spur)
        sl.setHorizontalSpacing(6); sl.setVerticalSpacing(3)
        outer.addWidget(spur, 1)

        sl.addWidget(QLabel("IF:"),       0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_if  = self._mhz_edit("0.15")
        sl.addWidget(self.spur_if, 0, 1)
        sl.addWidget(QLabel("GHz"), 0, 2)
        sl.addWidget(QLabel("M1 (LO1):"), 0, 3, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_m1  = self._mhz_edit("0.95")
        sl.addWidget(self.spur_m1, 0, 4)
        sl.addWidget(QLabel("GHz"), 0, 5)
        sl.addWidget(QLabel("→ IF2:"), 0, 6, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_if2 = QLabel("—")
        self.spur_if2.setStyleSheet("color:#557; padding:0 4px; font-weight:bold;")
        sl.addWidget(self.spur_if2, 0, 7, 1, 2)

        sl.addWidget(QLabel("M2 (LO2):"), 1, 3, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_m2  = self._mhz_edit("1.3")
        sl.addWidget(self.spur_m2, 1, 4)
        sl.addWidget(QLabel("GHz"), 1, 5)
        sl.addWidget(QLabel("→ RF:"), 1, 6, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_rf = QLabel("—")
        self.spur_rf.setStyleSheet("color:#175; padding:0 4px; font-weight:bold;")
        sl.addWidget(self.spur_rf, 1, 7, 1, 2)

        # IF2 / RF echoes follow IF / M1 / M2 / sb1 / sb2 / use_stage2
        for e in (self.spur_if, self.spur_m1, self.spur_m2):
            e.textEdited.connect(lambda *_: self._refresh_spur_inputs())

        # Plan-range guard: M1 / M2 must stay inside the plan's LO1 / LO2
        # ranges.  Live colour-flag while typing; hard clamp on focus-out.
        for e in (self.spur_m1, self.spur_m2):
            e.textEdited.connect(lambda *_: self._validate_spur_m())
        self.spur_m1.editingFinished.connect(
            lambda: self._clamp_spur_to_plan(self.spur_m1, "M1"))
        self.spur_m2.editingFinished.connect(
            lambda: self._clamp_spur_to_plan(self.spur_m2, "M2"))
        # When the plan's LO ranges (or stage-2 toggle) change, re-flag
        # any now-out-of-range M values.
        for e in (self.lo1_lo, self.lo1_hi, self.lo2_lo, self.lo2_hi):
            e.textEdited.connect(lambda *_: self._validate_spur_m())
        self.use_stage2.toggled.connect(lambda *_: self._validate_spur_m())

        sl.addWidget(QLabel("Spur freqs:"), 2, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_freq = self._mhz_edit("2.4")
        # Wider than the other plan edits — this field accepts a
        # comma / space / semicolon-separated list of target frequencies.
        self.spur_freq.setMaximumWidth(140)
        self.spur_freq.setMinimumWidth(90)
        self.spur_freq.setPlaceholderText("GHz, GHz, … (comma-separated)")
        self.spur_freq.setToolTip(
            "One or more target spur frequencies in GHz, separated by "
            "commas, spaces, or semicolons.  Each is searched against "
            "the same tolerance.")
        sl.addWidget(self.spur_freq, 2, 1)
        sl.addWidget(QLabel("tol:"), 2, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_tol = self._mhz_edit("0.005")
        self.spur_tol.setToolTip("Match window in GHz")
        sl.addWidget(self.spur_tol, 2, 3)
        sl.addWidget(QLabel("max |m|,|n|:"), 2, 4, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.spur_order = self._mhz_edit("5")
        sl.addWidget(self.spur_order, 2, 5)
        find_btn = QPushButton("Find sources")
        find_btn.clicked.connect(self._on_find_spurs)
        sl.addWidget(find_btn, 2, 6, 1, 3)

        # results table — rebuilt with natural-language columns.
        # Description:  "2 × (LO1 - IF)"      (math expression)
        # Title:        "Second harmonic of IF2"  (plain English)
        # Where:        "Mixer 1"             (origin stage)
        self.spur_table = QTableWidget(0, 7)
        self.spur_table.setHorizontalHeaderLabels(
            ["Target (GHz)", "Description", "Title", "Where",
             "f out (GHz)", "|Δ| (GHz)", "Order"])
        self.spur_table.setAlternatingRowColors(False)
        self.spur_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.spur_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.spur_table.verticalHeader().setVisible(False)
        self.spur_table.verticalHeader().setDefaultSectionSize(16)
        hdr = self.spur_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        sl.addWidget(self.spur_table, 3, 0, 1, 9)

        self.spur_status = QLabel("")
        self.spur_status.setStyleSheet("color:#666; padding:2px 4px;")
        sl.addWidget(self.spur_status, 4, 0, 1, 9)

        # ---------------- expressions sub-tab ----------------
        self._subtabs.addTab(self._build_expressions_page(), "Expressions")

        # initial update
        self._recompute_plan()
        self._refresh_expressions()

    # -----------------------------------------------------------------
    def _mhz_edit(self, default=""):
        e = QLineEdit(default)
        e.setMaximumHeight(20)
        e.setMinimumWidth(50)
        e.setMaximumWidth(80)
        return e

    @staticmethod
    def _ranges(lo_str, hi_str):
        lo = parse(lo_str); hi = parse(hi_str)
        if lo is None or hi is None:
            return None
        if lo > hi: lo, hi = hi, lo
        return (lo, hi)

    @staticmethod
    def _mix_range(in_lo, in_hi, lo_lo, lo_hi, sideband):
        """Return (out_lo, out_hi) for a mixer.  Sense of 'low' / 'high'
        follows standard RF mixer convention:
            sideband == 'high' → out = in + LO   (high-side / sum)
            sideband == 'low'  → out = LO - in   (low-side / difference)
        across the two input ranges."""
        if sideband == "high":
            return (in_lo + lo_lo, in_hi + lo_hi)
        # low-side: out = LO - in
        return (lo_lo - in_hi, lo_hi - in_lo)

    def _on_stage2_toggled(self, _on):
        # The ChainBoardWidget already handles enable/disable/show-hide on
        # the LO2 inputs and the M2/RF/sb2 cells via its own connection;
        # here we just propagate the change to the compute pipeline.
        self._recompute_plan()
        self._refresh_spur_inputs()

    @staticmethod
    def _fmt_range_short(lo, hi):
        """Compact GHz range for the board readouts.  Inputs are already
        in GHz (the whole Converter tab uses GHz as its native unit)."""
        return f"{lo:g} – {hi:g} GHz"

    def _recompute_plan(self):
        if_r = self._ranges(self.if_lo.text(), self.if_hi.text())
        lo1  = self._ranges(self.lo1_lo.text(), self.lo1_hi.text())
        lo2  = self._ranges(self.lo2_lo.text(), self.lo2_hi.text())
        sb1  = "low" if self.sb1_low.isChecked() else "high"
        sb2  = "low" if self.sb2_low.isChecked() else "high"
        use2 = self.use_stage2.isChecked()
        if if_r and lo1:
            if2_lo, if2_hi = self._mix_range(if_r[0], if_r[1], lo1[0], lo1[1], sb1)
            self.if2_out.setText(self._fmt_range_short(if2_lo, if2_hi))
            if lo2 and use2:
                rf_lo, rf_hi = self._mix_range(if2_lo, if2_hi, lo2[0], lo2[1], sb2)
                self.rf_out.setText(self._fmt_range_short(rf_lo, rf_hi))
                rf_target = self._ranges(self.rf_lo.text(), self.rf_hi.text())
                if rf_target:
                    tlo, thi = rf_target
                    inside = rf_lo <= tlo and rf_hi >= thi
                    self.rf_match.setText(
                        ("✓ covers desired RF" if inside else
                         "⚠ mismatch with desired"))
                else:
                    self.rf_match.setText("")
            elif use2:
                self.rf_out.setText("—")
                self.rf_match.setText("")
            else:
                # Single-stage mode: the IF2 block doubles as the RF output.
                self.rf_out.setText(self.if2_out.text())
                self.rf_match.setText("")
        else:
            self.if2_out.setText("—"); self.rf_out.setText("—")
            self.rf_match.setText("")
        # Spur-finder IF2 / RF echoes follow the same plan inputs.
        if hasattr(self, "spur_if2"):
            self._refresh_spur_inputs()

    # -----------------------------------------------------------------
    def _refresh_spur_inputs(self):
        """Sync the spur-finder's IF2 / RF readouts with IF, M1, M2 and the
        plan's sideband selection.  Called whenever any of those change."""
        IF = parse(self.spur_if.text())
        M1 = parse(self.spur_m1.text())
        M2 = parse(self.spur_m2.text())
        sb1 = "low" if self.sb1_low.isChecked() else "high"
        sb2 = "low" if self.sb2_low.isChecked() else "high"
        if IF is None or M1 is None:
            self.spur_if2.setText("—")
            self.spur_rf.setText("—")
            return
        if2 = (M1 - IF) if sb1 == "low" else (M1 + IF)
        self.spur_if2.setText(_fmt_ghz(if2))
        if not self.use_stage2.isChecked():
            self.spur_rf.setText("(stage 2 disabled)")
            return
        if M2 is None:
            self.spur_rf.setText("—")
            return
        rf = (M2 - if2) if sb2 == "low" else (M2 + if2)
        self.spur_rf.setText(_fmt_ghz(rf))

    # -----------------------------------------------------------------
    def _plan_lo_range_for(self, edit):
        """Return the (lo, hi) plan range that constrains the given spur
        M-edit, or None if the matching plan range is empty / invalid /
        not applicable (stage 2 disabled for M2)."""
        if edit is self.spur_m1:
            return self._ranges(self.lo1_lo.text(), self.lo1_hi.text())
        if edit is self.spur_m2:
            if not self.use_stage2.isChecked():
                return None
            return self._ranges(self.lo2_lo.text(), self.lo2_hi.text())
        return None

    def _validate_spur_m(self):
        """Light-red background on spur_m1 / spur_m2 when the typed value
        sits outside the plan's LO1 / LO2 range.  Pure visual feedback;
        the actual clamp happens on editingFinished and at find-time."""
        for edit in (self.spur_m1, self.spur_m2):
            rng = self._plan_lo_range_for(edit)
            v = parse(edit.text())
            if v is None or rng is None or rng[0] <= v <= rng[1]:
                edit.setStyleSheet("")
            else:
                edit.setStyleSheet("background:#ffd8d8;")

    @staticmethod
    def _fmt_plan_num(v):
        return f"{int(v)}" if abs(v - int(v)) < 1e-9 else f"{v:g}"

    def _clamp_spur_to_plan(self, edit, name):
        """Snap `edit`'s value into the plan's LO range; emit a status
        note when a clamp actually happens."""
        rng = self._plan_lo_range_for(edit)
        if rng is None:
            return
        v = parse(edit.text())
        if v is None:
            return
        if rng[0] <= v <= rng[1]:
            return
        clamped = max(rng[0], min(rng[1], v))
        edit.setText(self._fmt_plan_num(clamped))
        self.spur_status.setText(
            f"{name} clamped to plan range "
            f"[{self._fmt_plan_num(rng[0])}, "
            f"{self._fmt_plan_num(rng[1])}] GHz")
        self._validate_spur_m()
        self._refresh_spur_inputs()

    @staticmethod
    def _parse_spur_list(raw):
        """Parse a comma / space / semicolon / newline-separated list of
        positive spur frequencies (GHz).  Returns a sorted, de-duplicated
        list of floats.  Tokens that fail to parse or are non-positive
        are silently skipped."""
        out = []
        for tok in re.split(r"[,;\s]+", (raw or "").strip()):
            if not tok:
                continue
            v = parse(tok)
            if v is not None and v > 0:
                out.append(float(v))
        return sorted(set(out))

    def _find_spurs_for_target(self, spur, IF, M1, M2, tol, N, sb1, use_stage2):
        """Enumerate (m1, n1, m2, n2) within order N that produce a
        spur within ±tol of `spur` GHz; return the deduplicated list of
        (math, title, where, f_out, delta, order) rows ready for the
        results table."""
        rows = []
        m2_range = range(0, N + 1) if use_stage2 else range(0, 1)
        n2_range = range(-N, N + 1) if use_stage2 else range(1, 2)
        for m1 in range(0, N + 1):
            for n1 in range(-N, N + 1):
                f1 = m1 * M1 + n1 * IF
                if f1 == 0:
                    continue
                for m2 in m2_range:
                    for n2 in n2_range:
                        if m1 == 0 and n1 == 0 and m2 == 0 and n2 == 0:
                            continue
                        if use_stage2:
                            f_out = m2 * M2 + n2 * f1
                        else:
                            f_out = f1
                        f_out_abs = abs(f_out)
                        delta = abs(f_out_abs - spur)
                        if delta <= tol:
                            order = abs(m1) + abs(n1) + abs(m2) + abs(n2)
                            rows.append((order, delta, m1, n1, m2, n2,
                                         f_out_abs))
        seen = set()
        unique = []
        for r in rows:
            key = r[2:6]
            if key in seen:
                continue
            seen.add(key)
            unique.append(r)
        unique.sort(key=lambda r: (r[0], r[1], abs(r[2]) + abs(r[4])))
        seen_titles = set()
        out = []
        for order, delta, m1, n1, m2, n2, f_out in unique:
            math, title, where = _describe_spur(m1, n1, m2, n2, sb1, use_stage2)
            if title in seen_titles:
                continue
            seen_titles.add(title)
            if math.startswith("-(") and math.endswith(")"):
                math = math[2:-1]
            elif math.startswith("-"):
                math = math[1:]
            out.append((math, title, where, f_out, delta, order))
        return out

    def _on_find_spurs(self):
        # Snap M1 / M2 into the plan's LO ranges first — clicking the
        # button doesn't always emit editingFinished, so do it here too.
        self._clamp_spur_to_plan(self.spur_m1, "M1")
        self._clamp_spur_to_plan(self.spur_m2, "M2")
        IF = parse(self.spur_if.text())
        M1 = parse(self.spur_m1.text())
        M2 = parse(self.spur_m2.text())
        targets = self._parse_spur_list(self.spur_freq.text())
        tol = parse(self.spur_tol.text())
        N = parse(self.spur_order.text())
        sb1 = "low" if self.sb1_low.isChecked() else "high"
        use_stage2 = self.use_stage2.isChecked()
        required = [IF, M1, tol] + ([M2] if use_stage2 else [])
        if any(v is None for v in required) or not targets:
            self.spur_status.setText(
                "Fill in IF, M1, at least one spur frequency, and the tolerance"
                + (" (and M2 with stage 2 enabled)." if use_stage2 else "."))
            self.spur_table.setRowCount(0)
            return
        if tol <= 0:
            self.spur_status.setText("Tolerance must be > 0.")
            return
        N = int(N) if N is not None else 5
        N = max(1, min(N, 9))

        table_rows = []      # (target, math, title, where, f_out, delta, order)
        per_target_count = []
        for spur in targets:
            hits = self._find_spurs_for_target(
                spur, IF, M1, M2, tol, N, sb1, use_stage2)
            per_target_count.append((spur, len(hits)))
            for math, title, where, f_out, delta, order in hits:
                table_rows.append(
                    (spur, math, title, where, f_out, delta, order))

        self.spur_table.setRowCount(len(table_rows))
        for i, (spur, math, title, where, f_out, delta, order) in enumerate(table_rows):
            cells = (f"{spur:g}", math, title, where,
                     f"{f_out:g}", f"{delta:g}", str(order))
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if c == 0 or c >= 4:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                else:
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.spur_table.setItem(i, c, it)

        targets_str = ", ".join(f"{s:g}" for s in targets)
        if not table_rows:
            self.spur_status.setText(
                f"No (m,n) combinations within ±{tol} GHz of "
                f"{targets_str} GHz up to order {N}+{N}.")
        else:
            parts = [f"{cnt}@{s:g}" for s, cnt in per_target_count if cnt]
            self.spur_status.setText(
                f"{len(table_rows)} source(s) within ±{tol} GHz "
                f"({', '.join(parts)}; order |m|,|n| ≤ {N}).")

    # -----------------------------------------------------------------
    #  Expressions sub-tab — single-value IF / LO1 / LO2 + enumerated
    #  list of m·LO ± n·IF spur expressions at each stage.
    # -----------------------------------------------------------------
    def _build_expressions_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)

        # ---- inputs ----
        inp = QGroupBox("Inputs   (single-frequency values)")
        g = QGridLayout(inp)
        g.setHorizontalSpacing(6); g.setVerticalSpacing(3)
        lay.addWidget(inp)

        g.addWidget(QLabel("IF:"), 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_if = self._mhz_edit("0.15")
        g.addWidget(self.expr_if, 0, 1)
        g.addWidget(QLabel("GHz"), 0, 2)

        g.addWidget(QLabel("LO1:"), 0, 3, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_lo1 = self._mhz_edit("0.95")
        g.addWidget(self.expr_lo1, 0, 4)
        g.addWidget(QLabel("GHz"), 0, 5)

        g.addWidget(QLabel("LO2:"), 0, 6, alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_lo2 = self._mhz_edit("1.3")
        g.addWidget(self.expr_lo2, 0, 7)
        g.addWidget(QLabel("GHz"), 0, 8)

        g.addWidget(QLabel("M1 sideband:"), 1, 0,
                    alignment=Qt.AlignRight | Qt.AlignVCenter)
        sb1r = QHBoxLayout(); sb1r.setContentsMargins(0, 0, 0, 0); sb1r.setSpacing(4)
        self.expr_sb1_low  = QRadioButton("low")
        self.expr_sb1_high = QRadioButton("high")
        self.expr_sb1_low.setChecked(True)
        bg1 = QButtonGroup(self)
        bg1.addButton(self.expr_sb1_low); bg1.addButton(self.expr_sb1_high)
        sb1r.addWidget(self.expr_sb1_low); sb1r.addWidget(self.expr_sb1_high); sb1r.addStretch(1)
        sb1w = QWidget(); sb1w.setLayout(sb1r)
        g.addWidget(sb1w, 1, 1, 1, 3)

        g.addWidget(QLabel("M2 sideband:"), 1, 4,
                    alignment=Qt.AlignRight | Qt.AlignVCenter)
        sb2r = QHBoxLayout(); sb2r.setContentsMargins(0, 0, 0, 0); sb2r.setSpacing(4)
        self.expr_sb2_low  = QRadioButton("low")
        self.expr_sb2_high = QRadioButton("high")
        self.expr_sb2_low.setChecked(True)
        bg2 = QButtonGroup(self)
        bg2.addButton(self.expr_sb2_low); bg2.addButton(self.expr_sb2_high)
        sb2r.addWidget(self.expr_sb2_low); sb2r.addWidget(self.expr_sb2_high); sb2r.addStretch(1)
        sb2w = QWidget(); sb2w.setLayout(sb2r)
        g.addWidget(sb2w, 1, 5, 1, 4)

        g.addWidget(QLabel("Max order:"), 2, 0,
                    alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_order = self._mhz_edit("5")
        self.expr_order.setToolTip(
            "Max |m| + |n| for mixer products; also max harmonic number "
            "shown for each tone")
        g.addWidget(self.expr_order, 2, 1)

        self.expr_use_stage2 = QCheckBox("Use stage 2")
        self.expr_use_stage2.setChecked(True)
        g.addWidget(self.expr_use_stage2, 2, 2, 1, 2)

        g.addWidget(QLabel("Text:"), 2, 4,
                    alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_filter = QLineEdit()
        self.expr_filter.setPlaceholderText("e.g. 2 × LO2 - 3 × IF2")
        self.expr_filter.setMaximumWidth(180)
        self.expr_filter.setToolTip(
            "Substring filter against the Stage or Expression column. "
            "Spaces, dots and ×/· are ignored, so '2LO2-3IF2' matches "
            "'2 × LO2 - 3 × IF2'.")
        g.addWidget(self.expr_filter, 2, 5, 1, 4)

        # Row 3 — frequency-range filter (GHz).
        g.addWidget(QLabel("Freq (GHz):"), 3, 0,
                    alignment=Qt.AlignRight | Qt.AlignVCenter)
        self.expr_freq_filter = QLineEdit()
        self.expr_freq_filter.setPlaceholderText("e.g. 10-12, 14, 15")
        self.expr_freq_filter.setToolTip(
            "Comma-separated GHz ranges or bare values.  '10-12, 14, 15' "
            "keeps rows whose frequency lies in 10-12 GHz, or within "
            "±0.01 GHz of 14 GHz, or within ±0.01 GHz of 15 GHz.  "
            "Combined with the Text filter (both must match).")
        g.addWidget(self.expr_freq_filter, 3, 1, 1, 8)

        # ---- chain summary ----
        self.expr_summary = QLabel("")
        self.expr_summary.setStyleSheet(
            "color:#234; padding:4px 2px; font-family:Consolas,monospace;")
        self.expr_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.expr_summary.setWordWrap(True)
        lay.addWidget(self.expr_summary)

        # ---- expression table ----
        self.expr_table = QTableWidget(0, 4)
        self.expr_table.setHorizontalHeaderLabels(
            ["Stage", "Expression", "Frequency (GHz)", "Order"])
        self.expr_table.setAlternatingRowColors(False)
        self.expr_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.expr_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.expr_table.verticalHeader().setVisible(False)
        self.expr_table.verticalHeader().setDefaultSectionSize(16)
        hdr = self.expr_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setStretchLastSection(True)
        # Click any header to sort asc / desc; Expression column gets a
        # monospace font so the padded coefficients line up column-wise.
        self.expr_table.setSortingEnabled(True)
        hdr.setSortIndicatorShown(True)
        hdr.setSectionsClickable(True)
        self._expr_mono_font = QFont("Consolas", 9)
        self._expr_mono_font.setStyleHint(QFont.Monospace)
        lay.addWidget(self.expr_table, 1)

        self.expr_status = QLabel("")
        self.expr_status.setStyleSheet("color:#666; padding:2px 4px;")
        lay.addWidget(self.expr_status)

        # ---- wire change handlers ----
        for e in (self.expr_if, self.expr_lo1, self.expr_lo2, self.expr_order):
            e.textEdited.connect(lambda *_: self._refresh_expressions())
        for rb in (self.expr_sb1_low, self.expr_sb1_high,
                   self.expr_sb2_low, self.expr_sb2_high):
            rb.toggled.connect(lambda *_: self._refresh_expressions())
        self.expr_use_stage2.toggled.connect(
            lambda *_: self._refresh_expressions())
        self.expr_filter.textChanged.connect(
            lambda *_: self._refresh_expressions())
        self.expr_freq_filter.textChanged.connect(
            lambda *_: self._refresh_expressions())

        return page

    @staticmethod
    def _parse_freq_filter(text):
        """Parse a 'GHz' filter like '10-12, 14, 15' into a list of
        (lo_ghz, hi_ghz) intervals.  Bare values get a ±0.01 GHz
        tolerance so they actually match the calculated floats.  Empty
        input returns ``None`` meaning 'no frequency constraint'."""
        if not text or not text.strip():
            return None
        intervals = []
        for tok in re.split(r"[,;]+", text):
            tok = tok.strip()
            if not tok:
                continue
            m = re.match(
                r"^\s*([+-]?\d+(?:\.\d+)?)\s*(?:-|\.\.|to)\s*"
                r"([+-]?\d+(?:\.\d+)?)\s*$",
                tok, re.IGNORECASE)
            if m:
                lo = float(m.group(1))
                hi = float(m.group(2))
                if lo > hi:
                    lo, hi = hi, lo
                intervals.append((lo, hi))
                continue
            v = parse(tok)
            if v is not None:
                v_ghz = float(v)
                intervals.append((v_ghz - 0.01, v_ghz + 0.01))
        return intervals or None

    @staticmethod
    def _expr_norm(s):
        """Loose normaliser for the filter match — drops whitespace,
        middle dots, ×, ·, and unifies minus-sign variants."""
        return (re.sub(r"[\s·×.]+", "", (s or "").lower())
                .replace("−", "-"))

    def _refresh_expressions(self):
        if not hasattr(self, "expr_table"):
            return
        IF  = parse(self.expr_if.text())
        LO1 = parse(self.expr_lo1.text())
        LO2 = parse(self.expr_lo2.text())
        N_raw = parse(self.expr_order.text())
        N = int(N_raw) if N_raw is not None else 5
        N = max(1, min(N, 9))
        sb1 = "low" if self.expr_sb1_low.isChecked() else "high"
        sb2 = "low" if self.expr_sb2_low.isChecked() else "high"
        use_stage2 = self.expr_use_stage2.isChecked()
        # disable LO2 inputs when stage 2 is off
        self.expr_lo2.setEnabled(use_stage2)
        self.expr_sb2_low.setEnabled(use_stage2)
        self.expr_sb2_high.setEnabled(use_stage2)

        if IF is None or LO1 is None:
            self.expr_summary.setText(
                "Enter IF and LO1 (and LO2 with stage 2 enabled).")
            self.expr_table.setRowCount(0)
            self.expr_status.setText("")
            return

        sgn1 = -1 if sb1 == "low" else 1
        IF2 = LO1 + sgn1 * IF
        sb1_expr = _spur_stage1_expr(sb1)

        if use_stage2:
            if LO2 is None:
                self.expr_summary.setText(
                    f"IF = {_fmt_ghz(IF)}   LO1 = {_fmt_ghz(LO1)}   LO2 = ?\n"
                    f"IF2 = {sb1_expr} = {_fmt_ghz(IF2)}   "
                    f"RF = (enter LO2)")
                self.expr_table.setRowCount(0)
                self.expr_status.setText("Enter LO2 to populate stage 2.")
                return
            sgn2 = -1 if sb2 == "low" else 1
            RF = LO2 + sgn2 * IF2
            sb2_expr = _spur_stage2_expr(sb2)
            self.expr_summary.setText(
                f"IF  = {_fmt_ghz(IF)}     LO1 = {_fmt_ghz(LO1)}     "
                f"LO2 = {_fmt_ghz(LO2)}\n"
                f"IF2 = {sb1_expr} = {_fmt_ghz(IF2)}     "
                f"RF  = {sb2_expr} = {_fmt_ghz(RF)}")
        else:
            RF = IF2
            self.expr_summary.setText(
                f"IF  = {_fmt_ghz(IF)}     LO1 = {_fmt_ghz(LO1)}\n"
                f"IF2 = {sb1_expr} = {_fmt_ghz(IF2)}     "
                f"(stage 2 disabled — final output is IF2)")

        # Row = (stage_idx, sub_idx, stage, expression, freq, order)
        rows = []

        # IF fundamental + harmonics
        for k in range(1, N + 1):
            rows.append((1, k, "IF",
                         _fmt_aligned_term(k, "IF"), k * IF, k))

        # LO1 fundamental + harmonics
        for k in range(1, N + 1):
            rows.append((2, k, "LO1",
                         _fmt_aligned_term(k, "LO1"), k * LO1, k))

        # Mixer 1 mix products m·LO1 + n·IF (both coeffs non-zero, unique
        # by canonical-positive-frequency representative)
        for m in range(-N, N + 1):
            for n in range(-N, N + 1):
                if m == 0 or n == 0:
                    continue
                order = abs(m) + abs(n)
                if order < 2 or order > N:
                    continue
                f = m * LO1 + n * IF
                if f <= 0:
                    continue   # the (-m, -n) partner carries the positive rep
                rows.append((3, (order, -m, -n), "Mixer 1",
                             _fmt_aligned_mix(m, n, "LO1", "IF"), f, order))

        # IF2 fundamental + harmonics — same numbers as (k, sgn1·k) mixer-1
        # row but the IF2-named form is what engineers think in, so keep
        # both for clarity.
        for k in range(1, N + 1):
            rows.append((4, k, "IF2",
                         _fmt_aligned_term(k, "IF2"), k * IF2, k))

        if use_stage2:
            # LO2 fundamental + harmonics
            for k in range(1, N + 1):
                rows.append((5, k, "LO2",
                             _fmt_aligned_term(k, "LO2"), k * LO2, k))

            # Mixer 2 mix products m·LO2 + n·IF2
            for m in range(-N, N + 1):
                for n in range(-N, N + 1):
                    if m == 0 or n == 0:
                        continue
                    order = abs(m) + abs(n)
                    if order < 2 or order > N:
                        continue
                    f = m * LO2 + n * IF2
                    if f <= 0:
                        continue
                    rows.append((6, (order, -m, -n), "Mixer 2",
                                 _fmt_aligned_mix(m, n, "LO2", "IF2"),
                                 f, order))

            # RF fundamental + harmonics
            if RF > 0:
                for k in range(1, N + 1):
                    rows.append((7, k, "RF",
                                 _fmt_aligned_term(k, "RF"), k * RF, k))

        rows.sort(key=lambda r: (r[0], r[1]))

        # text filter
        flt_norm = self._expr_norm(self.expr_filter.text())
        if flt_norm:
            rows = [r for r in rows
                    if flt_norm in self._expr_norm(r[3])
                    or flt_norm in self._expr_norm(r[2])]

        # frequency filter (GHz ranges / bare values)
        freq_intervals = self._parse_freq_filter(self.expr_freq_filter.text())
        freq_filter_used = freq_intervals is not None
        if freq_filter_used:
            rows = [r for r in rows
                    if any(lo <= r[4] <= hi for lo, hi in freq_intervals)]

        # Disable sorting while populating, otherwise row indices shift
        # under us.  Re-enable afterwards so the user can click headers.
        self.expr_table.setSortingEnabled(False)
        self.expr_table.setRowCount(len(rows))
        for i, (stage_idx, _sub, stage, expr, freq, order) in enumerate(rows):
            stage_it = _ExprStageItem(stage, stage_idx)
            stage_it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.expr_table.setItem(i, 0, stage_it)

            expr_it = QTableWidgetItem(expr)
            expr_it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            expr_it.setFont(self._expr_mono_font)
            self.expr_table.setItem(i, 1, expr_it)

            freq_it = _ExprNumericItem(f"{freq:g}", float(freq))
            freq_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.expr_table.setItem(i, 2, freq_it)

            order_it = _ExprNumericItem(str(order), int(order))
            order_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.expr_table.setItem(i, 3, order_it)
        self.expr_table.setSortingEnabled(True)

        bits = [f"max order = {N}"]
        if self.expr_filter.text().strip():
            bits.append(f"text = '{self.expr_filter.text().strip()}'")
        if freq_filter_used:
            bits.append(f"freq = '{self.expr_freq_filter.text().strip()}' GHz")
        self.expr_status.setText(
            f"{len(rows)} expression(s) shown   ({', '.join(bits)})")

    # ---- finder/persistence/clipboard hooks -------------------------
    def title(self):
        return "Dual-stage converter"

    def get_state(self):
        return {
            "if_lo": self.if_lo.text(),  "if_hi": self.if_hi.text(),
            "if_pwr": self.if_pwr.text(),
            "lo1_lo": self.lo1_lo.text(), "lo1_hi": self.lo1_hi.text(),
            "lo1_pwr": self.lo1_pwr.text(),
            "sb1": "low" if self.sb1_low.isChecked() else "high",
            "lo2_lo": self.lo2_lo.text(), "lo2_hi": self.lo2_hi.text(),
            "lo2_pwr": self.lo2_pwr.text(),
            "sb2": "low" if self.sb2_low.isChecked() else "high",
            "use_stage2": bool(self.use_stage2.isChecked()),
            "rf_lo": self.rf_lo.text(),   "rf_hi": self.rf_hi.text(),
            "spur_if": self.spur_if.text(),     "spur_m1": self.spur_m1.text(),
            "spur_m2": self.spur_m2.text(),
            "spur_freq": self.spur_freq.text(), "spur_tol": self.spur_tol.text(),
            "spur_order": self.spur_order.text(),
            "expr_if": self.expr_if.text(),
            "expr_lo1": self.expr_lo1.text(),
            "expr_lo2": self.expr_lo2.text(),
            "expr_order": self.expr_order.text(),
            "expr_sb1": "low" if self.expr_sb1_low.isChecked() else "high",
            "expr_sb2": "low" if self.expr_sb2_low.isChecked() else "high",
            "expr_use_stage2": bool(self.expr_use_stage2.isChecked()),
            "expr_filter": self.expr_filter.text(),
            "expr_freq_filter": self.expr_freq_filter.text(),
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        for k, w in (("if_lo", self.if_lo), ("if_hi", self.if_hi),
                     ("if_pwr", self.if_pwr),
                     ("lo1_lo", self.lo1_lo), ("lo1_hi", self.lo1_hi),
                     ("lo1_pwr", self.lo1_pwr),
                     ("lo2_lo", self.lo2_lo), ("lo2_hi", self.lo2_hi),
                     ("lo2_pwr", self.lo2_pwr),
                     ("rf_lo", self.rf_lo), ("rf_hi", self.rf_hi),
                     ("spur_if", self.spur_if), ("spur_m1", self.spur_m1),
                     ("spur_m2", self.spur_m2),
                     ("spur_freq", self.spur_freq), ("spur_tol", self.spur_tol),
                     ("spur_order", self.spur_order),
                     ("expr_if", self.expr_if),
                     ("expr_lo1", self.expr_lo1),
                     ("expr_lo2", self.expr_lo2),
                     ("expr_order", self.expr_order),
                     ("expr_filter", self.expr_filter),
                     ("expr_freq_filter", self.expr_freq_filter)):
            v = st.get(k)
            if isinstance(v, str):
                w.setText(v)
        if st.get("sb1") == "high": self.sb1_high.setChecked(True)
        else:                         self.sb1_low.setChecked(True)
        if st.get("sb2") == "high": self.sb2_high.setChecked(True)
        else:                         self.sb2_low.setChecked(True)
        if "use_stage2" in st:
            self.use_stage2.setChecked(bool(st.get("use_stage2", True)))
        if st.get("expr_sb1") == "high": self.expr_sb1_high.setChecked(True)
        else:                              self.expr_sb1_low.setChecked(True)
        if st.get("expr_sb2") == "high": self.expr_sb2_high.setChecked(True)
        else:                              self.expr_sb2_low.setChecked(True)
        if "expr_use_stage2" in st:
            self.expr_use_stage2.setChecked(bool(st.get("expr_use_stage2", True)))
        self._recompute_plan()
        self._refresh_expressions()

    def search_entries(self, tab_name):
        return [
            (f"{tab_name}  →  IF low",    self.if_lo,    self),
            (f"{tab_name}  →  IF high",   self.if_hi,    self),
            (f"{tab_name}  →  LO1 low",   self.lo1_lo,   self),
            (f"{tab_name}  →  LO1 high",  self.lo1_hi,   self),
            (f"{tab_name}  →  LO2 low",   self.lo2_lo,   self),
            (f"{tab_name}  →  LO2 high",  self.lo2_hi,   self),
            (f"{tab_name}  →  Spur freq", self.spur_freq, self),
            (f"{tab_name}  →  Expr IF",   self.expr_if,  self),
            (f"{tab_name}  →  Expr LO1",  self.expr_lo1, self),
            (f"{tab_name}  →  Expr LO2",  self.expr_lo2, self),
        ]

    def to_clipboard_text(self):
        sb1 = "low" if self.sb1_low.isChecked() else "high"
        sb2 = "low" if self.sb2_low.isChecked() else "high"
        stage2 = "on" if self.use_stage2.isChecked() else "off"
        lines = [
            "Dual-stage converter",
            "--------------------",
            f"  IF   : {self.if_lo.text()} – {self.if_hi.text()} GHz   "
            f"P = {self.if_pwr.text()} dBm",
            f"  LO1  : {self.lo1_lo.text()} – {self.lo1_hi.text()} GHz   "
            f"P = {self.lo1_pwr.text()} dBm   {sb1}-side",
            f"  → IF2: {self.if2_out.text()}",
            f"  LO2  : {self.lo2_lo.text()} – {self.lo2_hi.text()} GHz   "
            f"P = {self.lo2_pwr.text()} dBm   {sb2}-side   (stage 2 {stage2})",
            f"  → RF : {self.rf_out.text()}",
            f"  Desired RF: {self.rf_lo.text()} – {self.rf_hi.text()} GHz",
        ]
        if self.spur_table.rowCount():
            lines.append("")
            lines.append("Spur sources:")
            for r in range(self.spur_table.rowCount()):
                cells = [self.spur_table.item(r, c).text()
                         for c in range(self.spur_table.columnCount())]
                lines.append("  " + "    ".join(cells))
        if hasattr(self, "expr_table") and self.expr_table.rowCount():
            lines.append("")
            lines.append("Expressions (single-value chain):")
            lines.append(f"  IF = {self.expr_if.text()} GHz   "
                         f"LO1 = {self.expr_lo1.text()} GHz   "
                         f"LO2 = {self.expr_lo2.text()} GHz")
            lines.append("  " + self.expr_summary.text().replace("\n", "\n  "))
            for r in range(self.expr_table.rowCount()):
                cells = [self.expr_table.item(r, c).text()
                         for c in range(self.expr_table.columnCount())]
                lines.append("  " + "    ".join(cells))
        return "\n".join(lines)


# ====================================================================
#  SMITH CHART TAB  (uses scikit-rf + matplotlib if available)
# ====================================================================

class SmithCanvas(FigureCanvas if HAS_SMITH else QWidget):
    """Embedded Smith-chart matplotlib canvas.  Can plot loaded
    impedance points and Touchstone S-parameter traces."""
    COLORS = ["#cc2222", "#2266cc", "#229933", "#cc8822",
              "#9933cc", "#118899", "#666666", "#bb1188"]

    pointClicked = pyqtSignal(float, float)   # (R, X) when user clicks the chart

    def __init__(self, parent=None):
        if not HAS_SMITH:
            QWidget.__init__(self, parent)
            return
        self.fig = Figure(figsize=(5.5, 5.5), dpi=100, tight_layout=True)
        FigureCanvas.__init__(self, self.fig)
        self.ax = self.fig.add_subplot(111)
        self.points = []
        self.traces = []
        self._color_idx = 0
        self.show_admittance = False
        self._click_z0 = 50.0
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mpl_connect("button_press_event", self._on_canvas_click)
        self._apply_theme()
        self._redraw()

    def _on_canvas_click(self, event):
        """Left-click inside the unit circle → emit pointClicked(R, X)."""
        if event.inaxes is not self.ax or event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        gx, gy = event.xdata, event.ydata
        if gx * gx + gy * gy > 1.0 - 1e-6:
            return                                  # outside or on unit circle
        gamma = complex(gx, gy)
        if abs(1 - gamma) < 1e-9:
            return
        z_norm = (1 + gamma) / (1 - gamma)
        R = z_norm.real * self._click_z0
        X = z_norm.imag * self._click_z0
        self.pointClicked.emit(R, X)

    def _next_color(self):
        c = self.COLORS[self._color_idx % len(self.COLORS)]
        self._color_idx += 1
        return c

    def _apply_theme(self):
        """Pick fg/bg colors based on the global THEME."""
        if THEME == "dark":
            self._bg         = "#181818"
            self._unit_col   = "#cccccc"
            self._grid_col   = "#4c4c52"
            self._axis_col   = "#7a7a80"
            self._text_col   = "#dddddd"
            self._label_col  = "#9a9a9e"
        else:
            self._bg         = "#ffffff"
            self._unit_col   = "#666666"
            self._grid_col   = "#bbbbbb"
            self._axis_col   = "#aaaaaa"
            self._text_col   = "#444444"
            self._label_col  = "#888888"
        self.fig.patch.set_facecolor(self._bg)
        self.ax.set_facecolor(self._bg)

    def _draw_grid(self):
        ax = self.ax
        # Outer unit circle
        theta = np.linspace(0, 2 * np.pi, 360)
        ax.plot(np.cos(theta), np.sin(theta), color=self._unit_col, lw=1.2)
        # Constant-resistance circles
        for r in (0.2, 0.5, 1.0, 2.0, 5.0):
            cx = r / (1 + r); rr = 1 / (1 + r)
            ax.plot(cx + rr * np.cos(theta), rr * np.sin(theta),
                    color=self._grid_col, lw=0.5)
            ax.text(cx - rr + 0.015, 0.012, f"{r:g}",
                    fontsize=7, color=self._label_col, ha="left", va="bottom")
        # Constant-reactance arcs (clip to inside the unit circle)
        for x in (0.2, 0.5, 1.0, 2.0, 5.0):
            for sign in (1, -1):
                cx, cy = 1.0, sign / x
                rr = 1 / x
                xs = cx + rr * np.cos(theta)
                ys = cy + rr * np.sin(theta)
                inside = xs * xs + ys * ys <= 1.0001
                xx = np.where(inside, xs, np.nan)
                yy = np.where(inside, ys, np.nan)
                ax.plot(xx, yy, color=self._grid_col, lw=0.5)
        # Real axis
        ax.plot([-1, 1], [0, 0], color=self._axis_col, lw=0.5)
        # Centre marker
        ax.plot(0, 0, "+", color=self._label_col, markersize=10)
        # Axis labels
        ax.text(-1.0, -0.04, "0",   fontsize=7, color=self._label_col, ha="center", va="top")
        ax.text( 1.0, -0.04, "∞",   fontsize=7, color=self._label_col, ha="center", va="top")
        ax.text( 0.0, -0.04, "Z₀",  fontsize=7, color=self._label_col, ha="center", va="top")

        # ---- admittance (Y) grid: constant-G circles + constant-B arcs,
        # mirrored about the imaginary axis from the Z chart ----
        if self.show_admittance:
            y_col = "#5588cc" if THEME == "dark" else "#3366aa"
            for g in (0.2, 0.5, 1.0, 2.0, 5.0):
                cx = -g / (1 + g); rr = 1 / (1 + g)
                ax.plot(cx + rr * np.cos(theta), rr * np.sin(theta),
                        color=y_col, lw=0.5, ls=(0, (3, 2)))
            for b in (0.2, 0.5, 1.0, 2.0, 5.0):
                for sign in (1, -1):
                    cx, cy = -1.0, sign / b
                    rr = 1 / b
                    xs = cx + rr * np.cos(theta)
                    ys = cy + rr * np.sin(theta)
                    inside = xs * xs + ys * ys <= 1.0001
                    ax.plot(np.where(inside, xs, np.nan),
                            np.where(inside, ys, np.nan),
                            color=y_col, lw=0.5, ls=(0, (3, 2)))

    def _redraw(self):
        self.ax.clear()
        self.fig.patch.set_facecolor(self._bg)
        self.ax.set_facecolor(self._bg)
        self._draw_grid()
        # Points: filled disc with the row number drawn inside, in white.
        # Marker is sized big enough to comfortably hold a 2-digit label.
        for i, (R, X, Z0, label, color) in enumerate(self.points):
            z = complex(R, X) / Z0
            g = (z - 1) / (z + 1)
            self.ax.plot(g.real, g.imag, "o", color=color, markersize=18,
                         markeredgecolor="white", markeredgewidth=1.2,
                         zorder=4)
            self.ax.text(g.real, g.imag, str(i + 1),
                         ha="center", va="center",
                         fontsize=8, fontweight="bold",
                         color="white", zorder=5)
        # Traces: number drawn inside the start marker; no chart legend.
        n_pts = len(self.points)
        for j, (name, freqs, gammas, color) in enumerate(self.traces):
            self.ax.plot(gammas.real, gammas.imag, "-",
                         color=color, lw=1.4, zorder=3)
            self.ax.plot(gammas[0].real, gammas[0].imag, "o",
                         color=color, markersize=14,
                         markeredgecolor="white", markeredgewidth=1.0,
                         zorder=4)
            self.ax.plot(gammas[-1].real, gammas[-1].imag, "s",
                         color=color, markersize=6, zorder=4)
            self.ax.text(gammas[0].real, gammas[0].imag,
                         str(n_pts + j + 1),
                         ha="center", va="center",
                         fontsize=7, fontweight="bold",
                         color="white", zorder=5)
        self.ax.set_xlim(-1.12, 1.12)
        self.ax.set_ylim(-1.12, 1.12)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        self.fig.canvas.draw_idle()

    # Public --------------------------------------------------------
    def add_point(self, R, X, Z0, label=None):
        if label is None or not label:
            label = f"{R:g} + j{X:g}"
        self.points.append((R, X, Z0, label, self._next_color()))
        self._redraw()

    def add_trace(self, name, freqs, gammas):
        self.traces.append((name, freqs, gammas, self._next_color()))
        self._redraw()

    def remove_point(self, idx):
        if 0 <= idx < len(self.points):
            self.points.pop(idx)
            self._redraw()

    def remove_trace(self, idx):
        if 0 <= idx < len(self.traces):
            self.traces.pop(idx)
            self._redraw()

    def set_show_admittance(self, on):
        self.show_admittance = bool(on)
        self._redraw()

    def clear(self):
        self.points = []
        self.traces = []
        self._color_idx = 0
        self._redraw()


class SmithChartTab(QWidget):
    """Smith-chart tab: enter impedances, drag/drop or load Touchstone files."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        # Splitter so the user can drag the boundary between the controls
        # and the chart canvas.
        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        outer.addWidget(self._splitter)

        # --- left: controls ---
        left = QWidget()
        left.setMinimumWidth(180)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)

        if not HAS_SMITH:
            lv.addWidget(QLabel(
                "Smith chart needs matplotlib + scikit-rf:\n"
                f"  {_smith_err}"))
            self._splitter.addWidget(left)
            return

        # ---- Z0 + single-line impedance entry ----
        z0_row = QHBoxLayout(); z0_row.setSpacing(4)
        z0_row.addWidget(QLabel("Z₀:"))
        self.z0_edit = QLineEdit("50"); self.z0_edit.setMaximumHeight(18)
        self.z0_edit.setMaximumWidth(60)
        z0_row.addWidget(self.z0_edit)
        z0_row.addWidget(QLabel("Ω"))
        z0_row.addStretch(1)
        # Which port to plot from a multiport file
        z0_row.addWidget(QLabel("Plot:"))
        self.port_combo = QComboBox()
        for v in ("S11", "S22", "S12", "S21"):
            self.port_combo.addItem(v)
        z0_row.addWidget(self.port_combo)
        lv.addLayout(z0_row)

        # Single-line impedance: [R] + j[X]  [+]
        z_row = QHBoxLayout(); z_row.setSpacing(3)
        self.r_edit = QLineEdit(); self.r_edit.setMaximumHeight(18)
        self.r_edit.setPlaceholderText("R")
        self.x_edit = QLineEdit(); self.x_edit.setMaximumHeight(18)
        self.x_edit.setText("0"); self.x_edit.setPlaceholderText("X")
        z_row.addWidget(self.r_edit, 1)
        plus = QLabel("+ j"); plus.setStyleSheet("color:#555;")
        z_row.addWidget(plus)
        z_row.addWidget(self.x_edit, 1)
        z_row.addWidget(QLabel("Ω"))
        add_btn = QPushButton("+")
        add_btn.setMaximumWidth(24)
        add_btn.setToolTip("Add this impedance as a point")
        add_btn.clicked.connect(self._on_add_point)
        z_row.addWidget(add_btn)
        lv.addLayout(z_row)
        # Enter in either field also adds
        for w in (self.r_edit, self.x_edit, self.z0_edit):
            w.returnPressed.connect(self._on_add_point)

        hint = QLabel("Drag .s2p / .s1p onto this tab to plot")
        hint.setStyleSheet("color: #888;")
        lv.addWidget(hint)

        lv.addSpacing(8)

        # ---- Plotted items table ----
        h3 = QHBoxLayout(); h3.setSpacing(6)
        t3 = QLabel("Plotted items"); t3.setStyleSheet("font-weight: bold;")
        h3.addWidget(t3, 0)
        l3 = QFrame(); l3.setFrameShape(QFrame.HLine); l3.setFrameShadow(QFrame.Sunken)
        h3.addWidget(l3, 1)
        lv.addLayout(h3)

        self.items = QTableWidget(0, 6, self)
        # Headers stripped of (Ω) / (dB) so all six columns fit in the
        # left splitter pane at a 620 px window width.
        self.items.setHorizontalHeaderLabels(["#", "Label", "R", "X", "VSWR", "RL"])
        self.items.verticalHeader().setVisible(False)
        self.items.verticalHeader().setDefaultSectionSize(16)
        self.items.setAlternatingRowColors(False)
        self.items.setShowGrid(True)
        self.items.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.items.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.items.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.items.setContextMenuPolicy(Qt.ActionsContextMenu)
        del_act = QAction("Delete selected", self.items)
        del_act.setShortcut(QKeySequence(Qt.Key_Delete))
        del_act.triggered.connect(self._on_delete_selected)
        self.items.addAction(del_act)
        hdr = self.items.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        for c in (2, 3, 4, 5):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        lv.addWidget(self.items, 1)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._on_delete_selected)
        btn_row.addWidget(del_btn)
        clear_btn = QPushButton("Clear all")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(clear_btn)
        lv.addLayout(btn_row)

        lv.addSpacing(8)

        # ---- Display options ----
        h4 = QHBoxLayout(); h4.setSpacing(6)
        t4 = QLabel("Display"); t4.setStyleSheet("font-weight: bold;")
        h4.addWidget(t4, 0)
        l4 = QFrame(); l4.setFrameShape(QFrame.HLine); l4.setFrameShadow(QFrame.Sunken)
        h4.addWidget(l4, 1)
        lv.addLayout(h4)
        self.show_y_box = QCheckBox("Show admittance (Y) grid")
        self.show_y_box.toggled.connect(self._on_admittance_toggled)
        lv.addWidget(self.show_y_box)
        lv.addWidget(QLabel("Click on the chart to add a point at that Γ"))

        # --- right: canvas ---
        self.canvas = SmithCanvas()
        self.canvas.pointClicked.connect(self._on_canvas_point)
        self._splitter.addWidget(left)
        self._splitter.addWidget(self.canvas)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([260, 600])

    # ---- actions ----
    def _on_add_point(self):
        if not HAS_SMITH:
            return
        R  = parse(self.r_edit.text())
        X  = parse(self.x_edit.text()) or 0.0
        Z0 = parse(self.z0_edit.text()) or 50.0
        if R is None:
            return
        self.canvas.add_point(R, X, Z0, None)
        self._refresh_list()

    @staticmethod
    def _vswr_rl(R, X, Z0):
        """Return (vswr, return_loss_dB) for a single impedance.
        Returns (inf, 0.0) at the unit circle (short/open) and
        (1.0, inf) at perfect match."""
        z = complex(R, X) / Z0
        g = (z - 1) / (z + 1)
        rho = abs(g)
        if rho >= 1.0 - 1e-12:
            return float("inf"), 0.0
        if rho < 1e-12:
            return 1.0, float("inf")
        return (1 + rho) / (1 - rho), -20.0 * log10(rho)

    def _load_touchstone(self, path):
        if not HAS_SMITH:
            return
        try:
            ntwk = rf.Network(path)
        except Exception as e:
            QMessageBox.warning(self, "Parse error",
                                f"Failed to load Touchstone file:\n\n{path}\n\n{e}")
            return
        port_str = self.port_combo.currentText()
        i = int(port_str[1]) - 1
        j = int(port_str[2]) - 1
        try:
            sij = ntwk.s[:, i, j]
        except Exception as e:
            QMessageBox.warning(self, "Port error",
                                f"This file doesn't have port {port_str}: {e}")
            return
        name = f"{os.path.basename(path)}  {port_str}"
        self.canvas.add_trace(name, ntwk.f, sij)
        self._refresh_list()

    def _on_clear(self):
        if HAS_SMITH:
            self.canvas.clear()
        self._refresh_list()

    def _on_delete_selected(self):
        if not HAS_SMITH:
            return
        rows = sorted({i.row() for i in self.items.selectedIndexes()}, reverse=True)
        if not rows:
            return
        n_pts = len(self.canvas.points)
        for row in rows:
            if row < n_pts:
                self.canvas.remove_point(row)
                n_pts -= 1
            else:
                self.canvas.remove_trace(row - n_pts)
        self._refresh_list()

    def _on_admittance_toggled(self, on):
        if HAS_SMITH:
            self.canvas.set_show_admittance(on)

    def _on_canvas_point(self, R, X):
        if not HAS_SMITH:
            return
        # Use the current Z0 from the input field for the click
        Z0 = parse(self.z0_edit.text()) or 50.0
        self.canvas._click_z0 = Z0
        self.canvas.add_point(R, X, Z0, None)
        self._refresh_list()

    def _refresh_list(self):
        self.items.setRowCount(0)
        if not HAS_SMITH:
            return
        n_pts = len(self.canvas.points)
        n_total = n_pts + len(self.canvas.traces)
        self.items.setRowCount(n_total)
        for i, (R, X, Z0, label, color) in enumerate(self.canvas.points):
            vswr, rl = self._vswr_rl(R, X, Z0)
            self._set_row(i, color, str(i + 1),
                          label or f"{R:g}{X:+g}j Ω",
                          f"{R:g}",
                          f"{X:+g}",
                          "∞" if vswr == float("inf") else f"{vswr:.2f}",
                          "0" if rl == 0.0 else ("∞" if rl == float("inf") else f"{rl:.1f}"))
        for j, (name, freqs, gammas, color) in enumerate(self.canvas.traces):
            row = n_pts + j
            f0 = freqs[0] / 1e6; f1 = freqs[-1] / 1e6
            mags = np.abs(gammas)
            mag_min = float(mags.min())
            if mag_min < 1e-12:
                vswr_best, rl_best = 1.0, float("inf")
            elif mag_min >= 1.0 - 1e-12:
                vswr_best, rl_best = float("inf"), 0.0
            else:
                vswr_best = (1 + mag_min) / (1 - mag_min)
                rl_best   = -20.0 * log10(mag_min)
            info = f"{name}  ({f0:g}–{f1:g} MHz, {len(freqs)} pts)"
            self._set_row(row, color, str(row + 1), info,
                          "—", "—",
                          f"{vswr_best:.2f} min" if vswr_best != float("inf") else "—",
                          f"{rl_best:.1f} max" if rl_best != float("inf") else "—")

    def _set_row(self, row, color, *cells):
        idx_item = QTableWidgetItem(cells[0])
        idx_item.setForeground(QColor(color))
        idx_item.setTextAlignment(Qt.AlignCenter)
        f = idx_item.font(); f.setBold(True); idx_item.setFont(f)
        self.items.setItem(row, 0, idx_item)
        for c, text in enumerate(cells[1:], start=1):
            it = QTableWidgetItem(text)
            if c >= 2:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.items.setItem(row, c, it)

    # ---- drag/drop ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                p = url.toLocalFile().lower()
                if p.endswith((".s1p", ".s2p", ".s3p", ".s4p")):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".s1p", ".s2p", ".s3p", ".s4p")):
                self._load_touchstone(path)

    # ---- persistence (called from MainWindow.closeEvent) ----
    def get_state(self):
        if not HAS_SMITH:
            return None
        points = []
        for R, X, Z0, label, color in self.canvas.points:
            points.append({
                "R": float(R), "X": float(X), "Z0": float(Z0),
                "label": label, "color": color,
            })
        return {
            "z0":     self.z0_edit.text(),
            "r":      self.r_edit.text(),
            "x":      self.x_edit.text(),
            "port":   self.port_combo.currentText(),
            "show_y": bool(self.show_y_box.isChecked()),
            "split":  list(self._splitter.sizes()),
            "points": points,
            # Traces are file-based and not round-trippable from JSON alone,
            # so we deliberately don't persist them.
        }

    def set_state(self, st):
        if not isinstance(st, dict) or not HAS_SMITH:
            return
        if isinstance(st.get("z0"), str): self.z0_edit.setText(st["z0"])
        if isinstance(st.get("r"),  str): self.r_edit.setText(st["r"])
        if isinstance(st.get("x"),  str): self.x_edit.setText(st["x"])
        port = st.get("port")
        if isinstance(port, str):
            ix = self.port_combo.findText(port)
            if ix >= 0: self.port_combo.setCurrentIndex(ix)
        if isinstance(st.get("show_y"), bool):
            self.show_y_box.setChecked(st["show_y"])
            self.canvas.set_show_admittance(st["show_y"])
        sizes = st.get("split")
        if isinstance(sizes, list) and len(sizes) >= 2:
            try: self._splitter.setSizes([int(s) for s in sizes])
            except (TypeError, ValueError): pass
        pts = st.get("points") or []
        for p in pts:
            try:
                R = float(p["R"]); X = float(p["X"]); Z0 = float(p["Z0"])
            except (KeyError, TypeError, ValueError):
                continue
            label = p.get("label") or f"{R:g} + j{X:g}"
            color = p.get("color") or self.canvas._next_color()
            self.canvas.points.append((R, X, Z0, label, color))
        # Advance the auto-color cycle so freshly-added points pick a new hue.
        self.canvas._color_idx = max(self.canvas._color_idx, len(pts))
        self.canvas._redraw()
        self._refresh_list()


# ====================================================================
#  RESISTOR COLOR-CODE TAB
# ====================================================================

# (name, RGB,             digit, mult-exp, tolerance %, tempco ppm/°C)
RC_COLOR_TABLE = [
    ("black",  (35,  35,  35),    0,   0,    None,   None),
    ("brown",  (110, 75,  38),    1,   1,    1.0,    100),
    ("red",    (210, 30,  25),    2,   2,    2.0,    50),
    ("orange", (240, 130, 30),    3,   3,    None,   15),
    ("yellow", (240, 215, 50),    4,   4,    None,   25),
    ("green",  (40,  160, 60),    5,   5,    0.5,    20),
    ("blue",   (40,  90,  210),   6,   6,    0.25,   10),
    ("violet", (170, 75,  215),   7,   7,    0.1,    5),
    ("gray",   (130, 130, 130),   8,   8,    0.05,   1),
    ("white",  (245, 245, 245),   9,   9,    None,   None),
    ("gold",   (212, 175, 55),    None, -1,  5.0,    None),
    ("silver", (192, 192, 192),   None, -2,  10.0,   None),
]
RC_BY_NAME = {row[0]: row for row in RC_COLOR_TABLE}
RC_DIGIT_COLORS  = [r[0] for r in RC_COLOR_TABLE if r[2] is not None]   # 10
RC_MULT_COLORS   = [r[0] for r in RC_COLOR_TABLE if r[3] is not None]   # 12
RC_TOL_COLORS    = [r[0] for r in RC_COLOR_TABLE if r[4] is not None]   # 8
RC_TEMPCO_COLORS = [r[0] for r in RC_COLOR_TABLE if r[5] is not None]   # 8

# E-series (standard preferred values, normalized to first decade)
E12  = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
E24  = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39,
        43, 47, 51, 56, 62, 68, 75, 82, 91]
E96  = [100, 102, 105, 107, 110, 113, 115, 118, 121, 124, 127, 130, 133,
        137, 140, 143, 147, 150, 154, 158, 162, 165, 169, 174, 178, 182,
        187, 191, 196, 200, 205, 210, 215, 221, 226, 232, 237, 243, 249,
        255, 261, 267, 274, 280, 287, 294, 301, 309, 316, 324, 332, 340,
        348, 357, 365, 374, 383, 392, 402, 412, 422, 432, 442, 453, 464,
        475, 487, 499, 511, 523, 536, 549, 562, 576, 590, 604, 619, 634,
        649, 665, 681, 698, 715, 732, 750, 768, 787, 806, 825, 845, 866,
        887, 909, 931, 953, 976]


def closest_e_value(R, series):
    """Closest E-series value to R (Ω)."""
    if R is None or R <= 0:
        return None
    decade = math.floor(math.log10(R))
    norm = series[0]   # first value: 10 (E12/E24) or 100 (E96)
    base_decade = 1 if norm == 10 else 2
    target = R / 10 ** (decade - base_decade)   # bring R into [norm, 10*norm)
    closest = min(series, key=lambda v: abs(math.log10(v) - math.log10(target)))
    return closest * 10 ** (decade - base_decade)


def value_to_color_bands(R, num_digit_bands):
    """Convert R (Ω) into the digit + multiplier color list (no tolerance/tempco).
    num_digit_bands = 2 (4-band) or 3 (5/6-band)."""
    if R is None or R <= 0:
        return None
    decade = math.floor(math.log10(R))
    if num_digit_bands == 2:
        mantissa = round(R / 10 ** (decade - 1))
        if mantissa >= 100:
            mantissa //= 10; decade += 1
        if mantissa < 10:
            mantissa = int(mantissa * 10); decade -= 1
        digits = [mantissa // 10, mantissa % 10]
        mult_exp = decade - 1
    else:
        mantissa = round(R / 10 ** (decade - 2))
        if mantissa >= 1000:
            mantissa //= 10; decade += 1
        if mantissa < 100:
            mantissa = int(mantissa * 10); decade -= 1
        digits = [mantissa // 100, (mantissa // 10) % 10, mantissa % 10]
        mult_exp = decade - 2
    if not all(0 <= d <= 9 for d in digits):
        return None
    if not (-2 <= mult_exp <= 9):
        return None
    digit_colors = [RC_DIGIT_COLORS[d] for d in digits]
    mult_color = next((r[0] for r in RC_COLOR_TABLE if r[3] == mult_exp), None)
    if mult_color is None:
        return None
    return digit_colors + [mult_color]


def color_bands_to_value(digit_color_names, mult_color_name):
    """Forward: bands → resistance (Ω).  Returns None on bad input."""
    digits = []
    for n in digit_color_names:
        d = RC_BY_NAME[n][2]
        if d is None: return None
        digits.append(d)
    mantissa = 0
    for d in digits:
        mantissa = mantissa * 10 + d
    mult_exp = RC_BY_NAME[mult_color_name][3]
    if mult_exp is None:
        return None
    return mantissa * 10 ** mult_exp


def fmt_ohms(R):
    """Pretty-print a resistance value with engineering suffix."""
    if R is None: return ""
    a = abs(R)
    if a >= 1e9:  s = f"{R/1e9:.4g} GΩ"
    elif a >= 1e6: s = f"{R/1e6:.4g} MΩ"
    elif a >= 1e3: s = f"{R/1e3:.4g} kΩ"
    elif a >= 1:   s = f"{R:.4g} Ω"
    elif a >= 1e-3: s = f"{R*1e3:.4g} mΩ"
    else: s = f"{R:.4g} Ω"
    return s


class ResistorImage(QWidget):
    """Visual resistor with N colored bands.  Click a band to cycle its
    color (left=next, right=previous)."""
    bandClicked = pyqtSignal(int, int)   # (band_index, +1 or -1)

    BAND_POSITIONS = {
        4: [0.16, 0.30, 0.44, 0.84],
        5: [0.13, 0.26, 0.39, 0.52, 0.84],
        6: [0.13, 0.24, 0.35, 0.46, 0.62, 0.84],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bands = []      # list of color names
        self.setMinimumHeight(110)
        self.setMinimumWidth(340)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_bands(self, bands):
        self.bands = list(bands)
        self.update()

    LEAD_LEN = 28   # short pin stubs on each side

    def _body_rect(self):
        w, h = self.width(), self.height()
        body_w = max(80, w - 2 * self.LEAD_LEN)
        body_h = int(h * 0.55)
        body_x = (w - body_w) // 2
        body_y = (h - body_h) // 2
        return body_x, body_y, body_w, body_h

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bx, by, bw, bh = self._body_rect()
        cy = by + bh // 2
        # leads
        if THEME == "dark":
            lead_col = QColor(190, 190, 190)
            body_col = QColor(220, 188, 145)
            border_col = QColor(120, 90, 50)
        else:
            lead_col = QColor(165, 165, 165)
            body_col = QColor(232, 200, 155)
            border_col = QColor(150, 110, 70)
        p.setPen(QPen(lead_col, 3))
        p.drawLine(0, cy, bx, cy)
        p.drawLine(bx + bw, cy, self.width(), cy)
        # body (rounded)
        p.setBrush(body_col)
        p.setPen(QPen(border_col, 1.4))
        p.drawRoundedRect(bx, by, bw, bh, 12, 12)
        # subtle highlight on top
        hl = QColor(255, 255, 255, 60)
        p.setBrush(hl); p.setPen(Qt.NoPen)
        p.drawRoundedRect(bx + 4, by + 3, bw - 8, bh // 3, 10, 10)
        # bands
        n = len(self.bands)
        if n == 0:
            return
        positions = self.BAND_POSITIONS.get(n, [(i + 1) / (n + 1) for i in range(n)])
        band_w = max(11, bw // (n + 5))
        for i, name in enumerate(self.bands):
            row = RC_BY_NAME.get(name)
            if row is None:
                continue
            cx = bx + int(positions[i] * bw)
            x = cx - band_w // 2
            p.setBrush(QColor(*row[1]))
            p.setPen(QPen(QColor(0, 0, 0, 100), 0.5))
            p.drawRect(x, by, band_w, bh)

    def mousePressEvent(self, ev):
        if not self.bands:
            return
        bx, by, bw, bh = self._body_rect()
        if not (bx <= ev.x() <= bx + bw and by <= ev.y() <= by + bh):
            return
        rel = (ev.x() - bx) / bw
        n = len(self.bands)
        positions = self.BAND_POSITIONS.get(n, [(i + 1) / (n + 1) for i in range(n)])
        idx = min(range(n), key=lambda i: abs(positions[i] - rel))
        if ev.button() == Qt.LeftButton:
            self.bandClicked.emit(idx, +1)
        elif ev.button() == Qt.RightButton:
            self.bandClicked.emit(idx, -1)


def _color_icon(color_name, size=(32, 14)):
    """Build a tiny solid-color QIcon for combo box items."""
    row = RC_BY_NAME.get(color_name)
    rgb = row[1] if row else (0, 0, 0)
    pm = QPixmap(*size)
    pm.fill(QColor(*rgb))
    painter = QPainter(pm)
    painter.setPen(QPen(QColor(0, 0, 0, 80), 0.5))
    painter.drawRect(0, 0, size[0] - 1, size[1] - 1)
    painter.end()
    return QIcon(pm)


class ResistorTab(QWidget):
    """Industry-best resistor color-code calculator.

    - 4 / 5 / 6 band toggle
    - Visual resistor; click any band to cycle its color
    - Per-band combos with colored swatches
    - Live resistance + tolerance + nominal range + E-series check
    - Reverse lookup: type a value (with engineering suffix) → bands
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 8)
        outer.setSpacing(8)

        # ---- header: 4 / 5 / 6 band selector ----
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)
        t = QLabel("Resistor color-code calculator")
        t.setStyleSheet("font-weight: bold;")
        hdr_row.addWidget(t, 0)
        ln = QFrame(); ln.setFrameShape(QFrame.HLine); ln.setFrameShadow(QFrame.Sunken)
        hdr_row.addWidget(ln, 1)
        outer.addLayout(hdr_row)

        n_row = QHBoxLayout(); n_row.setSpacing(12)
        n_row.addWidget(QLabel("Bands:"))
        self._band_grp = QButtonGroup(self)
        self._band_radios = []
        for n in (4, 5, 6):
            rb = QRadioButton(f"{n}-band")
            n_row.addWidget(rb)
            self._band_grp.addButton(rb, n)
            self._band_radios.append(rb)
        self._band_radios[0].setChecked(True)
        self._band_grp.buttonClicked.connect(lambda *_: self._rebuild_bands())
        n_row.addStretch(1)
        outer.addLayout(n_row)

        # ---- resistor visual ----
        self.image = ResistorImage()
        self.image.bandClicked.connect(self._on_band_clicked)
        outer.addWidget(self.image)

        # ---- band combos ----
        self._combo_row = QHBoxLayout()
        self._combo_row.setSpacing(10)
        outer.addLayout(self._combo_row)
        self._combos = []   # list of (combo, kind)

        # ---- result panel ----
        result_box = QFrame()
        result_box.setFrameShape(QFrame.NoFrame)
        rb = QVBoxLayout(result_box)
        rb.setContentsMargins(10, 8, 10, 8)
        rb.setSpacing(2)
        self.result_main = QLabel("—")
        f = QFont(); f.setPointSize(20); f.setBold(True)
        self.result_main.setFont(f)
        self.result_main.setAlignment(Qt.AlignCenter)
        rb.addWidget(self.result_main)
        self.result_sub = QLabel("")
        self.result_sub.setAlignment(Qt.AlignCenter)
        self.result_sub.setStyleSheet("color: #777;")
        rb.addWidget(self.result_sub)
        outer.addWidget(result_box)

        # ---- divider ----
        ln2 = QFrame(); ln2.setFrameShape(QFrame.HLine); ln2.setFrameShadow(QFrame.Sunken)
        outer.addWidget(ln2)

        # ---- reverse lookup ----
        rev_t = QLabel("Reverse lookup")
        rev_t.setStyleSheet("font-weight: bold;")
        outer.addWidget(rev_t)

        rev_row = QHBoxLayout()
        rev_row.setSpacing(6)
        rev_row.addWidget(QLabel("Value:"))
        self.rev_value = QLineEdit()
        self.rev_value.setPlaceholderText("4.7k, 220, 1M, 0.1, 2.2k …")
        self.rev_value.setMaximumWidth(180)
        rev_row.addWidget(self.rev_value)
        rev_row.addWidget(QLabel("Ω"))
        rev_row.addSpacing(12)
        rev_row.addWidget(QLabel("Tolerance:"))
        self.rev_tol = QComboBox()
        for label in ("any", "5%", "1%", "2%", "0.5%", "0.25%", "0.1%", "10%"):
            self.rev_tol.addItem(label)
        rev_row.addWidget(self.rev_tol)
        rev_row.addStretch(1)
        outer.addLayout(rev_row)

        self.rev_value.returnPressed.connect(self._on_reverse)
        self.rev_value.textEdited.connect(lambda _: self._on_reverse())
        self.rev_tol.currentIndexChanged.connect(lambda _: self._on_reverse())

        self.rev_result = QLabel("")
        self.rev_result.setStyleSheet("padding-left:14px;")
        outer.addWidget(self.rev_result)

        # ---- common-value buttons ----
        common_row = QHBoxLayout()
        common_row.addWidget(QLabel("Common:"))
        for v, t in (("10",  "10 Ω"), ("100", "100 Ω"), ("1k",   "1 kΩ"),
                     ("4.7k","4.7 kΩ"),("10k", "10 kΩ"), ("100k","100 kΩ"),
                     ("1M",  "1 MΩ")):
            b = QPushButton(t)
            b.setMaximumWidth(72)
            b.clicked.connect(lambda _, vv=v: (self.rev_value.setText(vv), self._on_reverse()))
            common_row.addWidget(b)
        common_row.addStretch(1)
        outer.addLayout(common_row)

        outer.addStretch(1)

        self._rebuild_bands()
        self._on_reverse()

    # ---------- band combo construction ----------
    def _band_kinds(self, n):
        if n == 4: return ("digit", "digit", "mult", "tol")
        if n == 5: return ("digit", "digit", "digit", "mult", "tol")
        if n == 6: return ("digit", "digit", "digit", "mult", "tol", "tempco")
        return ()

    def _kind_options(self, kind):
        if kind == "digit":  return RC_DIGIT_COLORS
        if kind == "mult":   return RC_MULT_COLORS
        if kind == "tol":    return RC_TOL_COLORS
        if kind == "tempco": return RC_TEMPCO_COLORS
        return []

    def _kind_label(self, kind):
        return {"digit": "digit", "mult": "multiplier",
                "tol": "tolerance", "tempco": "tempco"}[kind]

    def _kind_default(self, kind, idx):
        # Sensible defaults: 1, 0, ×100, 5% gold  ⇒ "1.0 kΩ ± 5%"
        if kind == "digit":
            return ["brown", "black", "black"][idx] if idx < 3 else "black"
        if kind == "mult":   return "red"
        if kind == "tol":    return "gold"
        if kind == "tempco": return "brown"
        return None

    def _rebuild_bands(self):
        # current count
        n = self._band_grp.checkedId()
        if n < 4: n = 4
        # snapshot existing colors so they survive a 4↔5↔6 toggle
        existing = [(c.currentText(), k) for c, k in self._combos]
        # tear down
        while self._combo_row.count():
            it = self._combo_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            else:
                lo = it.layout()
                if lo is not None:
                    while lo.count():
                        sub = lo.takeAt(0)
                        sw = sub.widget()
                        if sw: sw.deleteLater()
        self._combos = []

        kinds = self._band_kinds(n)
        for i, kind in enumerate(kinds):
            v = QVBoxLayout()
            v.setSpacing(2)
            la = QLabel(f"{i+1}. {self._kind_label(kind)}")
            la.setStyleSheet("color:#777;")
            v.addWidget(la)
            combo = QComboBox()
            combo.setMinimumWidth(96)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            for nm in self._kind_options(kind):
                combo.addItem(_color_icon(nm), nm)
            # carry over previous selection if compatible
            picked = None
            if i < len(existing):
                ename, ekind = existing[i]
                if ekind == kind and ename in self._kind_options(kind):
                    picked = ename
            if picked is None:
                picked = self._kind_default(kind, i)
            ix = combo.findText(picked)
            if ix < 0: ix = 0
            combo.setCurrentIndex(ix)
            combo.currentIndexChanged.connect(self._update_from_combos)
            v.addWidget(combo)
            self._combos.append((combo, kind))
            self._combo_row.addLayout(v, 1)
        self._update_from_combos()

    # ---------- forward: combos -> resistance ----------
    def _update_from_combos(self):
        # Update visual
        bands = [c.currentText() for c, _ in self._combos]
        self.image.set_bands(bands)
        # Compute resistance
        kinds = [k for _, k in self._combos]
        digits = [bands[i] for i, k in enumerate(kinds) if k == "digit"]
        mult_idx = next((i for i, k in enumerate(kinds) if k == "mult"), None)
        tol_idx  = next((i for i, k in enumerate(kinds) if k == "tol"),  None)
        tco_idx  = next((i for i, k in enumerate(kinds) if k == "tempco"), None)
        if mult_idx is None:
            self.result_main.setText("—")
            self.result_sub.setText("")
            return
        R = color_bands_to_value(digits, bands[mult_idx])
        if R is None or R <= 0:
            self.result_main.setText("—")
            self.result_sub.setText("invalid color combo")
            return
        tol_pct = RC_BY_NAME[bands[tol_idx]][4] if tol_idx is not None else None
        tempco  = RC_BY_NAME[bands[tco_idx]][5] if tco_idx is not None else None
        # Main label: e.g. "4.7 kΩ ± 5%"
        tol_str = f"  ± {tol_pct:g}%" if tol_pct is not None else ""
        self.result_main.setText(fmt_ohms(R) + tol_str)
        # Subtitle: range + E-series + tempco
        parts = []
        if tol_pct is not None:
            lo = R * (1 - tol_pct / 100)
            hi = R * (1 + tol_pct / 100)
            parts.append(f"range  {fmt_ohms(lo)} – {fmt_ohms(hi)}")
        # E-series check
        for name, series in (("E12", E12), ("E24", E24), ("E96", E96)):
            ev = closest_e_value(R, series)
            if ev and abs(ev - R) / R < 0.005:
                parts.append(f"✓ {name} preferred value")
                break
        else:
            ev24 = closest_e_value(R, E24)
            ev96 = closest_e_value(R, E96)
            if ev24: parts.append(f"closest E24: {fmt_ohms(ev24)}")
            if ev96: parts.append(f"closest E96: {fmt_ohms(ev96)}")
        if tempco is not None:
            parts.append(f"{tempco} ppm/°C")
        self.result_sub.setText("    ·    ".join(parts))

    # ---------- click on band cycles its color ----------
    def _on_band_clicked(self, idx, direction):
        if idx < 0 or idx >= len(self._combos):
            return
        combo, kind = self._combos[idx]
        cur = combo.currentIndex()
        nxt = (cur + direction) % combo.count()
        combo.setCurrentIndex(nxt)

    # ---------- reverse ----------
    def _on_reverse(self):
        text = self.rev_value.text().strip()
        R = parse(text)
        if R is None or R <= 0:
            self.rev_result.setText("")
            return
        # Use 5-band for precision values, 4-band for E12/E24
        ev24 = closest_e_value(R, E24)
        if ev24 and abs(ev24 - R) / R < 0.005:
            n_dig = 2
        else:
            n_dig = 3
        bands = value_to_color_bands(R, n_dig)
        if bands is None:
            self.rev_result.setText(f"  {fmt_ohms(R)}: out of range")
            return
        # tolerance from combo
        tol_text = self.rev_tol.currentText()
        if tol_text == "any":
            tol_color = "gold"
        else:
            t_pct = float(tol_text.rstrip("%"))
            tol_color = next((r[0] for r in RC_COLOR_TABLE if r[4] == t_pct), "gold")
        full = bands + [tol_color]
        # mirror the reverse-lookup colors onto the band-count radio,
        # the per-band combos, and (via cascade) the resistor preview
        self._apply_bands_to_visual(full)
        # build a swatch + text line
        line_parts = []
        for nm in full:
            line_parts.append(f"<span style='color:#fff;background:rgb({RC_BY_NAME[nm][1][0]},{RC_BY_NAME[nm][1][1]},{RC_BY_NAME[nm][1][2]});padding:1px 6px;border:1px solid #888;'>{nm}</span>")
        chain = "  ".join(line_parts)
        suffix = f"&nbsp;&nbsp;&nbsp;<b>{fmt_ohms(R)}</b>"
        if tol_text != "any":
            suffix += f" ± {tol_text}"
        self.rev_result.setText(chain + suffix)
        self.rev_result.setTextFormat(Qt.RichText)

    def _apply_bands_to_visual(self, full):
        """Push a reverse-lookup band sequence into the band-count radio,
        the per-band combos, and (via _update_from_combos) the resistor image."""
        target_n = len(full)
        if self._band_grp.checkedId() != target_n:
            for rb in self._band_radios:
                if self._band_grp.id(rb) == target_n:
                    rb.setChecked(True)
                    break
            self._rebuild_bands()
        changed = False
        for (combo, _kind), nm in zip(self._combos, full):
            ix = combo.findText(nm)
            if ix >= 0 and combo.currentIndex() != ix:
                combo.blockSignals(True)
                combo.setCurrentIndex(ix)
                combo.blockSignals(False)
                changed = True
        if changed:
            self._update_from_combos()

    # ---------- persistence ----------
    def title(self):
        return "Resistor color-code calculator"

    # ---- fuzzy finder integration ----
    def search_entries(self, tab_name):
        out = []
        # The reverse-lookup input
        out.append((f"{tab_name}  →  Reverse value", self.rev_value, self))
        # Each band combo
        for i, (combo, kind) in enumerate(self._combos):
            label = f"{tab_name}  →  Band {i+1} ({self._kind_label(kind)})"
            # combos aren't QLineEdits; supply the combo's lineEdit-like widget.
            # The finder calls .setFocus() and .selectAll() — both work on QComboBox.
            out.append((label, combo, self))
        # The 4/5/6 selector
        for n, rb in zip((4, 5, 6), self._band_radios):
            out.append((f"{tab_name}  →  {n}-band selector", rb, self))
        return out

    def get_state(self):
        return {
            "n":      self._band_grp.checkedId() or 4,
            "bands":  [c.currentText() for c, _ in self._combos],
            "rev":    self.rev_value.text(),
            "revtol": self.rev_tol.currentText(),
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        n = st.get("n", 4)
        for rb in self._band_radios:
            if self._band_grp.id(rb) == n:
                rb.setChecked(True)
        self._rebuild_bands()
        bands = st.get("bands") or []
        for (combo, kind), nm in zip(self._combos, bands):
            ix = combo.findText(nm)
            if ix >= 0:
                combo.setCurrentIndex(ix)
        rv = st.get("rev")
        if isinstance(rv, str):
            self.rev_value.setText(rv)
        rt = st.get("revtol")
        if isinstance(rt, str):
            ix = self.rev_tol.findText(rt)
            if ix >= 0:
                self.rev_tol.setCurrentIndex(ix)
        self._on_reverse()


# ====================================================================
#  LaTeX tab — paste LaTeX math, render with mathtext, export EMF/PNG/PDF
# ====================================================================

class LatexHighlighter(QSyntaxHighlighter):
    """Lightweight LaTeX syntax highlighter for the source editor."""

    def __init__(self, doc):
        super().__init__(doc)
        self._fmt_cmd = QTextCharFormat()
        self._fmt_cmd.setForeground(QColor("#0057b7"))
        self._fmt_cmd.setFontWeight(QFont.Bold)
        self._fmt_brace = QTextCharFormat()
        self._fmt_brace.setForeground(QColor("#666666"))
        self._fmt_brace.setFontWeight(QFont.Bold)
        self._fmt_dollar = QTextCharFormat()
        self._fmt_dollar.setForeground(QColor("#b40000"))
        self._fmt_dollar.setFontWeight(QFont.Bold)
        self._fmt_super = QTextCharFormat()
        self._fmt_super.setForeground(QColor("#9a3a00"))
        self._fmt_num = QTextCharFormat()
        self._fmt_num.setForeground(QColor("#005a8a"))
        self._fmt_cmt = QTextCharFormat()
        self._fmt_cmt.setForeground(QColor("#888888"))
        self._fmt_cmt.setFontItalic(True)
        self._rx = [
            (re.compile(r"\\[A-Za-z]+\*?"),     self._fmt_cmd),
            (re.compile(r"\\[^A-Za-z]"),        self._fmt_cmd),
            (re.compile(r"[{}\[\]]"),           self._fmt_brace),
            (re.compile(r"\$\$|\$"),            self._fmt_dollar),
            (re.compile(r"[_^]"),               self._fmt_super),
            (re.compile(r"\b\d+(?:\.\d+)?\b"),  self._fmt_num),
        ]
        self._rx_comment = re.compile(r"(?<!\\)%[^\n]*")

    def highlightBlock(self, text):
        for rx, fmt in self._rx:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        for m in self._rx_comment.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt_cmt)


if HAS_SMITH:
    class LatexCanvas(FigureCanvas):
        """Matplotlib figure that renders a math-mode LaTeX snippet via
        mathtext.  Two-pass: measure with renderer, then resize tightly."""

        def __init__(self, parent=None):
            self.fig = Figure(figsize=(4, 1.5), facecolor="white")
            super().__init__(self.fig)
            self.setParent(parent)
            self._last_size_inches = (4.0, 1.5)

        def render(self, math_src, font_size=28, pad=0.10):
            src = (math_src or "").strip()
            # Strip outer $ / $$ if user pasted them — we always wrap.
            if src.startswith("$$") and src.endswith("$$") and len(src) >= 4:
                src = src[2:-2].strip()
            elif src.startswith("$") and src.endswith("$") and len(src) >= 2:
                src = src[1:-1].strip()
            if not src:
                src = r"\;"
            wrapped = f"${src}$"
            # Validate via mathtext parser so we can report errors before
            # matplotlib silently substitutes a fallback glyph.
            try:
                from matplotlib import mathtext
                mathtext.MathTextParser("path").parse(wrapped, dpi=100)
            except Exception as exc:
                return False, str(exc).splitlines()[-1][:200]
            # Pass 1: oversize canvas, draw, measure text bbox.
            self.fig.clear()
            self.fig.set_size_inches(40.0, 20.0)
            ax = self.fig.add_axes([0, 0, 1, 1])
            ax.set_axis_off()
            ax.set_facecolor("white")
            txt = ax.text(0.5, 0.5, wrapped,
                          ha="center", va="center",
                          fontsize=font_size,
                          transform=ax.transAxes)
            try:
                self.fig.canvas.draw()
                renderer = self.fig.canvas.get_renderer()
                bb = txt.get_window_extent(renderer)
            except Exception as exc:
                return False, str(exc).splitlines()[-1][:200]
            dpi = float(self.fig.dpi or 100.0)
            w_in = max(0.4, bb.width  / dpi) + 2 * pad
            h_in = max(0.3, bb.height / dpi) + 2 * pad
            w_in = min(w_in, 60.0)
            h_in = min(h_in, 30.0)
            # Pass 2: resize tightly and redraw with text re-anchored.
            self.fig.clear()
            self.fig.set_size_inches(w_in, h_in)
            self.fig.patch.set_facecolor("white")
            ax = self.fig.add_axes([0, 0, 1, 1])
            ax.set_axis_off()
            ax.set_facecolor("white")
            ax.text(0.5, 0.5, wrapped,
                    ha="center", va="center",
                    fontsize=font_size,
                    transform=ax.transAxes)
            self._last_size_inches = (w_in, h_in)
            self.draw()
            return True, "OK"

        def to_png_bytes(self, dpi=300):
            from io import BytesIO
            buf = BytesIO()
            self.fig.savefig(buf, format="png", dpi=dpi,
                             facecolor=self.fig.get_facecolor(),
                             bbox_inches=None, pad_inches=0)
            return buf.getvalue()
else:
    class LatexCanvas(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.fig = None
            self._last_size_inches = (4.0, 1.5)
        def render(self, *a, **kw):
            return False, "matplotlib not installed"
        def to_png_bytes(self, dpi=300):
            return b""


def _qimage_to_hbitmap(qimage, ref_hdc):
    """Convert a QImage to a Windows HBITMAP via CreateDIBSection."""
    import ctypes
    from ctypes import wintypes
    img = qimage
    from PyQt5.QtGui import QImage as _QImage
    if img.format() != _QImage.Format_RGB32:
        img = img.convertToFormat(_QImage.Format_RGB32)
    w, h = img.width(), img.height()

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize",          wintypes.DWORD),
            ("biWidth",         wintypes.LONG),
            ("biHeight",        wintypes.LONG),
            ("biPlanes",        wintypes.WORD),
            ("biBitCount",      wintypes.WORD),
            ("biCompression",   wintypes.DWORD),
            ("biSizeImage",     wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed",       wintypes.DWORD),
            ("biClrImportant",  wintypes.DWORD),
        ]

    bih = BITMAPINFOHEADER()
    bih.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
    bih.biWidth       = w
    bih.biHeight      = -h   # negative = top-down DIB
    bih.biPlanes      = 1
    bih.biBitCount    = 32
    bih.biCompression = 0    # BI_RGB
    bih.biSizeImage   = 0

    gdi32 = ctypes.windll.gdi32
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP

    bits_ptr = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(
        ref_hdc, ctypes.byref(bih), 0, ctypes.byref(bits_ptr), None, 0
    )
    if not hbmp or not bits_ptr.value:
        raise RuntimeError("CreateDIBSection failed")
    src = img.bits()
    src.setsize(img.byteCount())
    src_bytes = bytes(src)
    ctypes.memmove(bits_ptr.value, src_bytes, len(src_bytes))
    return hbmp


_SRCCOPY = 0x00CC0020


def _delete_enh_metafile(hemf):
    import ctypes
    from ctypes import wintypes
    gdi32 = ctypes.windll.gdi32
    gdi32.DeleteEnhMetaFile.argtypes = [wintypes.HANDLE]
    gdi32.DeleteEnhMetaFile.restype  = wintypes.BOOL
    return bool(gdi32.DeleteEnhMetaFile(hemf))


def _qimage_to_dib_bytes(qimg):
    """Pack a QImage into a Windows DIB blob suitable for CF_DIB:
    BITMAPINFOHEADER (40 bytes) followed by bottom-up, 24bpp BGR rows
    padded to a 4-byte boundary.

    Standalone CF_DIB beats Qt's setMimeData()-routed clipboard for
    Office-app interop — Qt's clipboard registers an 'Ole Private Data'
    chunk that some PowerPoint versions read as an embed source, so the
    paste either silently fails or pulls in a broken OLE link instead
    of the bitmap.  Putting plain CF_DIB on the clipboard via the Win32
    API avoids that path entirely."""
    import struct, numpy as np
    from PyQt5.QtGui import QImage
    img = qimg.convertToFormat(QImage.Format_RGB888)
    w = img.width(); h = img.height()
    bpl = img.bytesPerLine()
    ptr = img.bits(); ptr.setsize(img.byteCount())
    src = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl)[:, :w * 3]
    src = src.reshape(h, w, 3)         # RGB rows, top-down
    bgr = src[..., ::-1]               # → BGR
    bgr = bgr[::-1]                    # bottom-up
    row_size = ((w * 3 + 3) // 4) * 4  # DWORD-aligned row stride
    if row_size == w * 3:
        pixel_bytes = bgr.tobytes()
    else:
        padded = np.zeros((h, row_size), dtype=np.uint8)
        padded[:, :w * 3] = bgr.reshape(h, w * 3)
        pixel_bytes = padded.tobytes()
    header = struct.pack(
        "<IiiHHIIiiII",
        40,              # biSize
        w,               # biWidth
        h,               # biHeight (positive = bottom-up)
        1,               # biPlanes
        24,              # biBitCount
        0,               # biCompression = BI_RGB
        len(pixel_bytes),
        0, 0, 0, 0,
    )
    return header + pixel_bytes


def _set_clipboard_image_native(qimg, png_bytes=None, text=None):
    """Put an image on the Windows clipboard via the Win32 API directly,
    bypassing Qt.  Registers CF_DIB (so PowerPoint/Word paste as image),
    optional 'PNG' registered format, and optional CF_UNICODETEXT.

    Once this returns, the data is owned by Windows — paste survives
    even if rcalc closes."""
    import win32clipboard, win32con
    dib = _qimage_to_dib_bytes(qimg)
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
        if png_bytes:
            try:
                fmt = win32clipboard.RegisterClipboardFormat("PNG")
                win32clipboard.SetClipboardData(fmt, png_bytes)
            except Exception:
                pass
        if text:
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


class _RECTL(__import__("ctypes").Structure):
    import ctypes as _ct
    from ctypes import wintypes as _wt
    _fields_ = [("left",   _wt.LONG),
                ("top",    _wt.LONG),
                ("right",  _wt.LONG),
                ("bottom", _wt.LONG)]


def _build_emf(png_bytes, width_px, height_px, dpi, out_path=None):
    """Build a Windows Enhanced Metafile wrapping the PNG bitmap.
    Returns HENHMETAFILE (int).  If out_path is given, the EMF is also
    written to disk.  Caller takes ownership of the handle (must either
    hand to clipboard or DeleteEnhMetaFile).

    pywin32 doesn't expose CreateEnhMetaFile, so we go through gdi32
    directly via ctypes."""
    import ctypes
    from ctypes import wintypes
    from PyQt5.QtGui import QImage
    img = QImage()
    if not img.loadFromData(png_bytes, "PNG"):
        raise RuntimeError("PNG decode failed")
    img = img.convertToFormat(QImage.Format_RGB32)

    gdi32  = ctypes.windll.gdi32
    user32 = ctypes.windll.user32

    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype  = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype  = ctypes.c_int

    gdi32.CreateEnhMetaFileW.argtypes = [
        wintypes.HDC, wintypes.LPCWSTR,
        ctypes.POINTER(_RECTL), wintypes.LPCWSTR,
    ]
    gdi32.CreateEnhMetaFileW.restype = wintypes.HDC
    gdi32.CloseEnhMetaFile.argtypes = [wintypes.HDC]
    gdi32.CloseEnhMetaFile.restype  = wintypes.HANDLE
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype  = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype  = wintypes.BOOL
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype  = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype  = wintypes.BOOL
    gdi32.StretchBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.StretchBlt.restype = wintypes.BOOL
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype  = ctypes.c_int

    screen_hdc = user32.GetDC(None)
    if not screen_hdc:
        raise RuntimeError("GetDC failed")
    try:
        # Natural physical size of the picture (from PNG pixels and the
        # target export DPI) — this is what we want PowerPoint to use as
        # the equation's natural paste size.
        width_in  = width_px  / float(dpi)
        height_in = height_px / float(dpi)

        # The metafile's *logical* drawing coordinates inherit the
        # reference DC's mapping (MM_TEXT = device pixels at the screen's
        # DPI).  rclBounds gets recorded in those units.  For consistency
        # with rclFrame (HIMETRIC), the drawing extent has to describe
        # the same physical size — i.e. width_in * screen_dpi, NOT the
        # PNG's pixel count.  Using width_px directly here is what made
        # PowerPoint clip earlier: it saw the drawing occupying ~10.85"
        # of logical space inside a frame declared to be ~3.47".
        #
        # GetDeviceCaps(LOGPIXELS*) returns the *logical* UI DPI (usually
        # 96), which on HiDPI screens disagrees with the physical DPI
        # recorded in the EMF header via szlDevice / szlMillimeters.  To
        # keep rclBounds and rclFrame in exact agreement we derive the
        # physical DPI from the same HORZRES/HORZSIZE pair that GDI puts
        # into the header.
        HORZSIZE, VERTSIZE, HORZRES, VERTRES = 4, 6, 8, 10
        h_res  = gdi32.GetDeviceCaps(screen_hdc, HORZRES)  or 1920
        v_res  = gdi32.GetDeviceCaps(screen_hdc, VERTRES)  or 1080
        h_size = gdi32.GetDeviceCaps(screen_hdc, HORZSIZE) or 508
        v_size = gdi32.GetDeviceCaps(screen_hdc, VERTSIZE) or 285
        phys_dpi_x = h_res / (h_size / 25.4)
        phys_dpi_y = v_res / (v_size / 25.4)
        logical_w = max(1, int(round(width_in  * phys_dpi_x)))
        logical_h = max(1, int(round(height_in * phys_dpi_y)))

        # rclFrame in HIMETRIC (.01 mm).
        rect = _RECTL(0, 0,
                      max(1, int(round(width_in  * 2540))),
                      max(1, int(round(height_in * 2540))))
        desc = "rcalc\0LaTeX Equation\0\0"
        emf_dc = gdi32.CreateEnhMetaFileW(
            screen_hdc, out_path, ctypes.byref(rect), desc
        )
        if not emf_dc:
            raise RuntimeError("CreateEnhMetaFileW failed")
        mem_dc = gdi32.CreateCompatibleDC(screen_hdc)
        if not mem_dc:
            gdi32.CloseEnhMetaFile(emf_dc)
            raise RuntimeError("CreateCompatibleDC failed")
        try:
            hbmp = _qimage_to_hbitmap(img, screen_hdc)
            old = gdi32.SelectObject(mem_dc, hbmp)
            try:
                ok = gdi32.StretchBlt(
                    emf_dc, 0, 0, logical_w, logical_h,
                    mem_dc, 0, 0, img.width(), img.height(),
                    _SRCCOPY,
                )
                if not ok:
                    raise RuntimeError("StretchBlt failed")
            finally:
                gdi32.SelectObject(mem_dc, old)
                gdi32.DeleteObject(hbmp)
        finally:
            gdi32.DeleteDC(mem_dc)
        hemf = gdi32.CloseEnhMetaFile(emf_dc)
        if not hemf:
            raise RuntimeError("CloseEnhMetaFile failed")
        return hemf
    finally:
        user32.ReleaseDC(None, screen_hdc)


class LatexTab(QWidget):
    """LaTeX math snippet editor + matplotlib preview + clipboard/file
    export (EMF / PNG / PDF).  Math-mode only — input is auto-wrapped
    in $...$."""

    DEFAULT_SRC = (
        r"\frac{1}{2\pi}\oint_{\partial \Omega}\!\mathbf{E}\cdot d\boldsymbol{\ell}"
        r" = -\frac{d\Phi_B}{dt}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        title = QLabel("LaTeX")
        title.setStyleSheet("font-weight: bold;")
        outer.addWidget(title)

        self._splitter = QSplitter(Qt.Vertical)
        outer.addWidget(self._splitter, 1)

        # ---- source editor ----
        self.src_edit = QPlainTextEdit()
        self.src_edit.setPlainText(self.DEFAULT_SRC)
        fams = set(QFontDatabase().families())
        mono_family = "Consolas" if "Consolas" in fams else "Courier New"
        self.src_edit.setFont(QFont(mono_family, 11))
        self.src_edit.setPlaceholderText(
            "Type or paste LaTeX math here, e.g.  \\frac{a}{b} + \\sum_{i=1}^n x_i"
        )
        self._hl = LatexHighlighter(self.src_edit.document())
        self._splitter.addWidget(self.src_edit)

        # ---- preview area ----
        prev_holder = QWidget()
        prev_lay = QVBoxLayout(prev_holder)
        prev_lay.setContentsMargins(0, 0, 0, 0)
        prev_lay.setSpacing(2)
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color:#555;")
        prev_lay.addWidget(self.status_label)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setFrameShape(QFrame.StyledPanel)
        self._canvas_scroll.setStyleSheet("background:white;")
        self._canvas_scroll.setAlignment(Qt.AlignCenter)
        if HAS_SMITH:
            self.canvas = LatexCanvas(self._canvas_scroll)
            self._canvas_scroll.setWidget(self.canvas)
        else:
            placeholder = QLabel(
                "matplotlib not installed — install matplotlib to enable "
                "LaTeX rendering."
            )
            placeholder.setStyleSheet("color:#a44; padding:20px;")
            self._canvas_scroll.setWidget(placeholder)
            self.canvas = None
        prev_lay.addWidget(self._canvas_scroll, 1)
        self._splitter.addWidget(prev_holder)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)

        # ---- controls row ----
        ctl = QHBoxLayout()
        ctl.setContentsMargins(0, 0, 0, 0)
        ctl.setSpacing(8)
        ctl.addWidget(QLabel("Font:"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 200)
        self.font_spin.setValue(28)
        self.font_spin.setSuffix(" pt")
        ctl.addWidget(self.font_spin)
        ctl.addSpacing(8)
        ctl.addWidget(QLabel("Export DPI:"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 1200)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        ctl.addWidget(self.dpi_spin)
        ctl.addSpacing(8)
        ctl.addWidget(QLabel("Pad:"))
        self.pad_spin = QDoubleSpinBox()
        self.pad_spin.setRange(0.0, 1.0)
        self.pad_spin.setSingleStep(0.02)
        self.pad_spin.setDecimals(2)
        self.pad_spin.setValue(0.10)
        self.pad_spin.setSuffix(" in")
        ctl.addWidget(self.pad_spin)
        ctl.addStretch(1)
        outer.addLayout(ctl)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self.btn_copy_emf = QPushButton("Copy as EMF")
        self.btn_copy_png = QPushButton("Copy as PNG")
        self.btn_save_emf = QPushButton("Save EMF…")
        self.btn_save_png = QPushButton("Save PNG…")
        self.btn_save_pdf = QPushButton("Save PDF…")
        for b in (self.btn_copy_emf, self.btn_copy_png,
                  self.btn_save_emf, self.btn_save_png, self.btn_save_pdf):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        # ---- wiring ----
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(150)
        self._render_timer.timeout.connect(self._render_now)
        self.src_edit.textChanged.connect(self._render_timer.start)
        self.font_spin.valueChanged.connect(lambda *_: self._render_timer.start())
        self.pad_spin.valueChanged.connect(lambda *_: self._render_timer.start())

        self.btn_copy_emf.clicked.connect(self._copy_emf)
        self.btn_copy_png.clicked.connect(self._copy_png)
        self.btn_save_emf.clicked.connect(self._save_emf)
        self.btn_save_png.clicked.connect(self._save_png)
        self.btn_save_pdf.clicked.connect(self._save_pdf)

        # Disable Windows-only actions on other platforms.
        if sys.platform != "win32":
            self.btn_copy_emf.setEnabled(False)
            self.btn_copy_emf.setToolTip("EMF clipboard is Windows-only.")
            self.btn_save_emf.setEnabled(False)
            self.btn_save_emf.setToolTip("EMF save is Windows-only.")

        QTimer.singleShot(0, self._render_now)

    # ---- rendering ---------------------------------------------------
    def _render_now(self):
        if self.canvas is None or not HAS_SMITH:
            return
        ok, msg = self.canvas.render(
            self.src_edit.toPlainText(),
            font_size=self.font_spin.value(),
            pad=self.pad_spin.value(),
        )
        if ok:
            w_in, h_in = self.canvas._last_size_inches
            screen_dpi = self.logicalDpiX() or 96
            self.canvas.setFixedSize(
                max(60, int(w_in * screen_dpi)),
                max(40, int(h_in * screen_dpi)),
            )
            self.status_label.setText("✓ Rendered")
            self.status_label.setStyleSheet("color:#175a25;")
        else:
            self.status_label.setText(f"✗ {msg}")
            self.status_label.setStyleSheet("color:#b40000;")

    # ---- export helpers ---------------------------------------------
    def _figure_png(self, dpi=None):
        if self.canvas is None:
            return b""
        if dpi is None:
            dpi = self.dpi_spin.value()
        try:
            return self.canvas.to_png_bytes(dpi=dpi)
        except Exception:
            return b""

    def _copy_png(self):
        png = self._figure_png()
        if not png:
            self.status_label.setText("✗ No figure to copy.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        from PyQt5.QtGui import QImage
        img = QImage()
        if not img.loadFromData(png, "PNG"):
            self.status_label.setText("✗ PNG decode failed.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        if sys.platform == "win32":
            _set_clipboard_image_native(img, png_bytes=png)
        else:
            from PyQt5.QtCore import QMimeData, QByteArray
            mime = QMimeData()
            mime.setImageData(img)
            mime.setData("image/png", QByteArray(png))
            QApplication.clipboard().setMimeData(mime)
        self.status_label.setText(
            f"✓ PNG copied ({img.width()}×{img.height()} px @ "
            f"{self.dpi_spin.value()} dpi)."
        )
        self.status_label.setStyleSheet("color:#175a25;")

    def _copy_emf(self):
        if sys.platform != "win32":
            self.status_label.setText("✗ EMF copy is Windows-only.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        png = self._figure_png()
        if not png:
            self.status_label.setText("✗ No figure to copy.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        try:
            import win32clipboard, win32con
            from PyQt5.QtGui import QImage
            img = QImage()
            if not img.loadFromData(png, "PNG"):
                self.status_label.setText("✗ PNG decode failed.")
                self.status_label.setStyleSheet("color:#b40000;")
                return
            dpi = self.dpi_spin.value()
            hemf = _build_emf(png, img.width(), img.height(), dpi)
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_ENHMETAFILE, hemf)
            finally:
                win32clipboard.CloseClipboard()
            # Clipboard owns hemf now; do NOT DeleteEnhMetaFile.
            self.status_label.setText(
                f"✓ EMF copied ({img.width()}×{img.height()} px @ {dpi} dpi)."
            )
            self.status_label.setStyleSheet("color:#175a25;")
        except Exception as exc:
            self.status_label.setText(f"✗ EMF copy failed: {exc}")
            self.status_label.setStyleSheet("color:#b40000;")

    def _last_dir(self):
        return APP_DIR

    def _save_emf(self):
        if sys.platform != "win32":
            return
        png = self._figure_png()
        if not png:
            self.status_label.setText("✗ No figure to save.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save EMF",
            os.path.join(self._last_dir(), "equation.emf"),
            "Enhanced Metafile (*.emf)",
        )
        if not path:
            return
        try:
            from PyQt5.QtGui import QImage
            img = QImage()
            img.loadFromData(png, "PNG")
            dpi = self.dpi_spin.value()
            hemf = _build_emf(png, img.width(), img.height(), dpi, path)
            _delete_enh_metafile(hemf)
            self.status_label.setText(f"✓ Saved {path}")
            self.status_label.setStyleSheet("color:#175a25;")
        except Exception as exc:
            self.status_label.setText(f"✗ Save EMF failed: {exc}")
            self.status_label.setStyleSheet("color:#b40000;")

    def _save_png(self):
        png = self._figure_png()
        if not png:
            self.status_label.setText("✗ No figure to save.")
            self.status_label.setStyleSheet("color:#b40000;")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PNG",
            os.path.join(self._last_dir(), "equation.png"),
            "PNG Image (*.png)",
        )
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(png)
            self.status_label.setText(f"✓ Saved {path}")
            self.status_label.setStyleSheet("color:#175a25;")
        except Exception as exc:
            self.status_label.setText(f"✗ Save PNG failed: {exc}")
            self.status_label.setStyleSheet("color:#b40000;")

    def _save_pdf(self):
        if self.canvas is None or not HAS_SMITH:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF",
            os.path.join(self._last_dir(), "equation.pdf"),
            "PDF Document (*.pdf)",
        )
        if not path:
            return
        try:
            self.canvas.fig.savefig(
                path,
                facecolor=self.canvas.fig.get_facecolor(),
                bbox_inches=None, pad_inches=0,
            )
            self.status_label.setText(f"✓ Saved {path}")
            self.status_label.setStyleSheet("color:#175a25;")
        except Exception as exc:
            self.status_label.setText(f"✗ Save PDF failed: {exc}")
            self.status_label.setStyleSheet("color:#b40000;")

    # ---- persistence -------------------------------------------------
    def get_state(self):
        return {
            "src":   self.src_edit.toPlainText(),
            "font":  int(self.font_spin.value()),
            "dpi":   int(self.dpi_spin.value()),
            "pad":   float(self.pad_spin.value()),
            "split": list(self._splitter.sizes()),
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        if isinstance(st.get("src"), str):
            self.src_edit.setPlainText(st["src"])
        if isinstance(st.get("font"), int):
            self.font_spin.setValue(st["font"])
        if isinstance(st.get("dpi"), int):
            self.dpi_spin.setValue(st["dpi"])
        if isinstance(st.get("pad"), (int, float)):
            self.pad_spin.setValue(float(st["pad"]))
        sp = st.get("split")
        if isinstance(sp, list) and len(sp) == 2:
            try: self._splitter.setSizes([int(x) for x in sp])
            except Exception: pass

    # ---- fuzzy-finder hook ------------------------------------------
    def title(self):
        return "LaTeX"

    def search_entries(self, tab_name):
        return [(f"{tab_name}  →  LaTeX source", self.src_edit, self)]

    # ---- Ctrl+Shift+C bundle ----------------------------------------
    def to_clipboard_mime(self):
        if self.canvas is None or not HAS_SMITH:
            return None
        png = self._figure_png()
        if not png:
            return None
        from PyQt5.QtGui import QImage
        from PyQt5.QtCore import QMimeData, QByteArray
        img = QImage()
        if not img.loadFromData(png, "PNG"):
            return None
        mime = QMimeData()
        mime.setImageData(img)
        mime.setData("image/png", QByteArray(png))
        mime.setText(self.src_edit.toPlainText())
        return mime

    def to_clipboard_text(self):
        return self.src_edit.toPlainText()


# ====================================================================
#  Periodic table tab — interactive 9 × 18 grid with details panel
# ====================================================================

class _PeriodicCell(QPushButton):
    doubleClicked = pyqtSignal(int)

    def __init__(self, z, parent=None):
        super().__init__(parent)
        self._z = z

    def mouseDoubleClickEvent(self, ev):
        super().mouseDoubleClickEvent(ev)
        if ev.button() == Qt.LeftButton:
            self.doubleClicked.emit(self._z)


class PeriodicTableTab(QWidget):
    """Interactive periodic table.  Single-click populates the details
    panel; double-click swaps the tab into a full drill-down view for
    that element (Esc returns to the table)."""

    SERIES_COLORS = {
        "Alkali metals":         "#ff9999",
        "Alkaline earth metals": "#ffcc99",
        "Transition metals":     "#ffe680",
        "Poor metals":           "#cce6cc",
        "Metalloids":            "#b3d9b3",
        "Nonmetals":             "#99ccff",
        "Halogens":              "#99e6e6",
        "Noble gases":           "#d9b3ff",
        "Lanthanides":           "#ffb3d9",
        "Actinides":             "#ff99cc",
        "Unknown":               "#dddddd",
    }
    CELL_SIZE = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._stack = QStackedWidget(self)
        root.addWidget(self._stack)

        table_page = QWidget()
        outer = QVBoxLayout(table_page)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        # ---- title + filter row ----
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Periodic table")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)
        head.addSpacing(18)
        head.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "symbol, name, or Z  (e.g.  Fe  /  iron  /  26)"
        )
        self.filter_edit.setMaximumWidth(320)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        head.addWidget(self.filter_edit)
        head.addStretch(1)
        outer.addLayout(head)

        # ---- legend row ----
        legend = QHBoxLayout()
        legend.setSpacing(4)
        legend.setContentsMargins(0, 0, 0, 0)
        for series, color in self.SERIES_COLORS.items():
            chip = QLabel(f"  {series}  ")
            chip.setStyleSheet(
                f"background:{color}; border:1px solid #888; "
                "color:#222; font-size:7pt; padding:1px 4px;"
            )
            legend.addWidget(chip)
        legend.addStretch(1)
        outer.addLayout(legend)

        # ---- grid ----
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self._buttons = {}             # Z -> QPushButton
        for e in PERIODIC_ELEMENTS:
            r, c = e.get("row"), e.get("col")
            if r is None or c is None:
                continue
            btn = self._make_cell(e)
            grid.addWidget(btn, r - 1, c - 1)
            self._buttons[e["Z"]] = btn

        # Placeholder markers for the 57-71 / 89-103 series anchors on
        # the main table — small labels in the same row+col where La/Ac
        # would otherwise live.
        for r0, span_z, color in (
            (5, "57-71",  self.SERIES_COLORS["Lanthanides"]),
            (6, "89-103", self.SERIES_COLORS["Actinides"]),
        ):
            chip = QLabel(span_z)
            chip.setAlignment(Qt.AlignCenter)
            chip.setFixedSize(self.CELL_SIZE, self.CELL_SIZE)
            chip.setStyleSheet(
                f"background:{color}; border:1px solid #888; "
                "color:#222; font-size:7pt;"
            )
            grid.addWidget(chip, r0, 2)

        # Vertical gap row between the main 7-period table and the
        # lanthanide/actinide blocks.
        grid.setRowMinimumHeight(7, 8)

        outer.addWidget(grid_holder, 0, Qt.AlignHCenter)

        # ---- details panel ----
        self.details = QLabel("Click an element for details.")
        self.details.setTextFormat(Qt.RichText)
        self.details.setStyleSheet(
            "background:#fafafa; border:1px solid #aaa; padding:8px;"
        )
        self.details.setWordWrap(True)
        self.details.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.details.setMinimumHeight(160)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.details, 1)

        self._stack.addWidget(table_page)
        self._drill_page = self._build_drill_page()
        self._stack.addWidget(self._drill_page)

        self._selected_z = None
        # Hydrogen as the default selection so the panel isn't empty.
        if 1 in self._buttons:
            self._select(1)

    # ---- cell construction --------------------------------------------
    def _make_cell(self, e):
        z = e["Z"]
        btn = _PeriodicCell(z)
        btn.setCheckable(True)
        btn.setFixedSize(self.CELL_SIZE, self.CELL_SIZE)
        btn.setCursor(Qt.PointingHandCursor)
        mass = e.get("mass")
        mass_str = (f"{mass:.4g}" if mass and mass >= 1 else
                    (f"{mass:.3g}" if mass else ""))
        btn.setText(f"{e['Z']}\n{e['symbol']}\n{mass_str}")
        btn.setStyleSheet(self._cell_css(e["series"], dim=False))
        btn.setToolTip(f"{e['name']} (Z={e['Z']}, {e['series']}) — "
                       f"double-click for full details")
        btn.clicked.connect(lambda _checked=False, z=z: self._select(z))
        btn.doubleClicked.connect(self._drill_down)
        return btn

    def _cell_css(self, series, dim=False):
        color = self.SERIES_COLORS.get(series, "#dddddd")
        if dim:
            color = "#eeeeee"
            fg = "#999"
        else:
            fg = "#111"
        return (
            "QPushButton {"
            f" background:{color};"
            " border:1px solid #555;"
            f" color:{fg};"
            " font-family:Tahoma;"
            " font-size:8pt;"
            " text-align:center;"
            " padding:0;"
            "}"
            "QPushButton:hover { border:2px solid #000; }"
            "QPushButton:checked { border:2px solid #d00000; font-weight:bold; }"
        )

    # ---- selection / details ------------------------------------------
    def _select(self, z):
        for zz, b in self._buttons.items():
            b.setChecked(zz == z)
        self._selected_z = z
        # Find and render
        e = next((x for x in PERIODIC_ELEMENTS if x["Z"] == z), None)
        if e is None:
            return
        self.details.setText(self._format_details(e))

    @staticmethod
    def _fmt_val(v, unit="", spec=".4g"):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:{spec}}{(' ' + unit) if unit else ''}"
        return f"{v}{(' ' + unit) if unit else ''}"

    def _format_details(self, e):
        F = self._fmt_val
        color = self.SERIES_COLORS.get(e["series"], "#dddddd")
        group_txt = (str(e["group"]) if e.get("group") is not None else "—")
        return (
            f"<table border='0' cellspacing='0' cellpadding='2' width='100%'>"
            f"<tr><td valign='top' style='width:90px;'>"
            f"  <div style='background:{color}; border:1px solid #555; "
            f"             padding:6px; text-align:center; min-width:64px;'>"
            f"    <div style='font-size:10pt;'>{e['Z']}</div>"
            f"    <div style='font-size:18pt; font-weight:bold;'>{e['symbol']}</div>"
            f"    <div style='font-size:9pt;'>{F(e.get('mass'))}</div>"
            f"  </div></td>"
            f"<td valign='top'>"
            f"  <div style='font-size:13pt;'><b>{e['name']}</b></div>"
            f"  <div style='color:#444;'><i>{e['series']}</i>"
            f"  &nbsp;·&nbsp; block <b>{e.get('block','—')}</b>"
            f"  &nbsp;·&nbsp; period <b>{e.get('period','—')}</b>"
            f"  &nbsp;·&nbsp; group <b>{group_txt}</b></div>"
            f"  <table cellspacing='1' cellpadding='2' style='font-size:9pt;'>"
            f"    <tr><td><b>Electron config</b></td>"
            f"        <td><code>{e.get('config','—') or '—'}</code></td>"
            f"        <td style='padding-left:18px;'><b>Electronegativity</b></td>"
            f"        <td>{F(e.get('en'), '(Pauling)')}</td></tr>"
            f"    <tr><td><b>Melting point</b></td>"
            f"        <td>{F(e.get('melt_k'), 'K')}</td>"
            f"        <td style='padding-left:18px;'><b>Boiling point</b></td>"
            f"        <td>{F(e.get('boil_k'), 'K')}</td></tr>"
            f"    <tr><td><b>Density</b></td>"
            f"        <td>{F(e.get('density'), 'g/cm³')}</td>"
            f"        <td style='padding-left:18px;'><b>1st ionization</b></td>"
            f"        <td>{F(e.get('ev_first'), 'eV')}</td></tr>"
            f"    <tr><td><b>Covalent radius</b></td>"
            f"        <td>{F(e.get('ar_cov'), 'pm')}</td>"
            f"        <td style='padding-left:18px;'><b>VdW radius</b></td>"
            f"        <td>{F(e.get('ar_van'), 'pm')}</td></tr>"
            f"    <tr><td><b>Discovered</b></td>"
            f"        <td colspan='3'>{e.get('year') or '?'} "
            f"           &nbsp;—&nbsp; {e.get('discoverer') or '?'}</td></tr>"
            f"  </table>"
            f"</td></tr></table>"
        )

    # ---- drill-down view ----------------------------------------------
    def _build_drill_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        back = QPushButton("← Back to periodic table")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._back_to_table)
        head.addWidget(back)
        head.addStretch(1)
        head.addWidget(QLabel("<i style='color:#666;'>Esc returns to table</i>"))
        lay.addLayout(head)

        self._drill_label = QLabel()
        self._drill_label.setTextFormat(Qt.RichText)
        self._drill_label.setWordWrap(True)
        self._drill_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._drill_label.setStyleSheet(
            "background:#fafafa; border:1px solid #aaa; padding:14px;"
        )
        self._drill_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._drill_label)
        scroll.setFrameShape(QScrollArea.NoFrame)
        lay.addWidget(scroll, 1)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), page)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._back_to_table)
        return page

    def _drill_down(self, z):
        e = next((x for x in PERIODIC_ELEMENTS if x["Z"] == z), None)
        if e is None:
            return
        self._select(z)
        self._drill_label.setText(self._format_drill_html(e))
        self._stack.setCurrentWidget(self._drill_page)
        self._drill_page.setFocus()

    def _back_to_table(self):
        self._stack.setCurrentIndex(0)
        if self._selected_z in self._buttons:
            self._buttons[self._selected_z].setFocus()

    def _format_drill_html(self, e):
        F = self._fmt_val
        color = self.SERIES_COLORS.get(e["series"], "#dddddd")
        group_txt = (str(e["group"]) if e.get("group") is not None else "—")
        mass = e.get("mass")
        mass_str = (f"{mass:.4g}" if isinstance(mass, (int, float)) else "—")
        rows = [
            ("Atomic number (Z)",      f"{e['Z']}"),
            ("Atomic mass",            mass_str),
            ("Series",                 e.get("series") or "—"),
            ("Block",                  e.get("block") or "—"),
            ("Period",                 str(e.get("period") or "—")),
            ("Group",                  group_txt),
            ("Electron configuration", f"<code>{e.get('config') or '—'}</code>"),
            ("Electronegativity",      F(e.get("en"), "(Pauling)")),
            ("1st ionization energy",  F(e.get("ev_first"), "eV")),
            ("Melting point",          F(e.get("melt_k"), "K")),
            ("Boiling point",          F(e.get("boil_k"), "K")),
            ("Density",                F(e.get("density"), "g/cm³")),
            ("Covalent radius",        F(e.get("ar_cov"), "pm")),
            ("Van der Waals radius",   F(e.get("ar_van"), "pm")),
            ("Discovered",             f"{e.get('year') or '?'} &nbsp;—&nbsp; "
                                       f"{e.get('discoverer') or '?'}"),
        ]
        body = "".join(
            f"<tr><td style='padding:4px 14px 4px 0; color:#444;'>{k}</td>"
            f"<td style='padding:4px 0;'><b>{v}</b></td></tr>"
            for k, v in rows
        )
        return (
            f"<table border='0' cellspacing='0' cellpadding='0' width='100%'>"
            f"<tr><td valign='top' style='width:170px;'>"
            f"  <div style='background:{color}; border:2px solid #333; "
            f"             padding:14px; text-align:center; min-width:150px;'>"
            f"    <div style='font-size:12pt; color:#222;'>{e['Z']}</div>"
            f"    <div style='font-size:44pt; font-weight:bold; "
            f"               line-height:1.0;'>{e['symbol']}</div>"
            f"    <div style='font-size:11pt; color:#222;'>{mass_str}</div>"
            f"  </div></td>"
            f"<td valign='top' style='padding-left:22px;'>"
            f"  <div style='font-size:22pt;'><b>{e['name']}</b></div>"
            f"  <div style='color:#444; font-size:10pt;'><i>{e['series']}</i>"
            f"  &nbsp;·&nbsp; block <b>{e.get('block','—')}</b>"
            f"  &nbsp;·&nbsp; period <b>{e.get('period','—')}</b>"
            f"  &nbsp;·&nbsp; group <b>{group_txt}</b></div>"
            f"  <br/>"
            f"  <table cellspacing='0' cellpadding='0' "
            f"         style='font-size:10pt;'>{body}</table>"
            f"</td></tr></table>"
        )

    # ---- filter --------------------------------------------------------
    def _on_filter_changed(self, text):
        q = text.strip().lower()
        for z, btn in self._buttons.items():
            e = next(x for x in PERIODIC_ELEMENTS if x["Z"] == z)
            if not q:
                show = True
            else:
                show = (
                    q in e["symbol"].lower()
                    or q in e["name"].lower()
                    or q in e["series"].lower()
                    or q in (e.get("block") or "").lower()
                    or q == str(e["Z"])
                )
            btn.setStyleSheet(self._cell_css(e["series"], dim=not show))

    # ---- finder / persistence -----------------------------------------
    def title(self):
        return "Periodic"

    def search_entries(self, tab_name):
        return [(tab_name, self.filter_edit, self)]

    def get_state(self):
        return {
            "selected": self._selected_z,
            "filter":   self.filter_edit.text(),
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        if isinstance(st.get("filter"), str):
            self.filter_edit.setText(st["filter"])
        z = st.get("selected")
        if isinstance(z, int) and z in self._buttons:
            self._select(z)

    def to_clipboard_text(self):
        if self._selected_z is None:
            return ""
        e = next((x for x in PERIODIC_ELEMENTS
                  if x["Z"] == self._selected_z), None)
        if e is None:
            return ""
        F = self._fmt_val
        lines = [
            f"{e['symbol']}  {e['name']}  (Z = {e['Z']})",
            f"  Mass: {F(e.get('mass'))}",
            f"  Series: {e['series']}  ·  block {e.get('block','')}  "
            f"·  period {e.get('period','')}  "
            f"·  group {e.get('group') if e.get('group') is not None else '—'}",
            f"  Electron config: {e.get('config','')}",
            f"  Electronegativity (Pauling): {F(e.get('en'))}",
            f"  Melting / boiling: {F(e.get('melt_k'),'K')} / "
            f"{F(e.get('boil_k'),'K')}",
            f"  Density: {F(e.get('density'),'g/cm^3')}",
            f"  1st ionization: {F(e.get('ev_first'),'eV')}",
            f"  Covalent / VdW radius: {F(e.get('ar_cov'),'pm')} / "
            f"{F(e.get('ar_van'),'pm')}",
            f"  Discovered: {e.get('year') or '?'} — {e.get('discoverer') or '?'}",
        ]
        return "\n".join(lines)


# ====================================================================
#  Mechanical reference tab — threads, drills, sheet gauges, bolt calc
# ====================================================================
#
# me-toolbox 0.0.18 ships with a buggy `Bolt.preload2torque` (sec(α)
# is called with α in *degrees* but the underlying mpmath.sec treats
# its argument as radians, so the formula returns nonsense numbers).
# Shigley's torque-tension equation (eq. 8-27) is short and
# unambiguous, so we implement it inline rather than route through
# the broken method.


def _bolt_torque_from_preload(preload_N, d_mm, p_mm,
                              mu_t=0.15, mu_c=0.15,
                              half_angle_deg=30.0):
    """Tightening torque (N·m) from preload (N) — Shigley eq. 8-27.

    d_mm, p_mm    – nominal diameter and pitch in millimetres.
    mu_t, mu_c    – thread and collar friction coefficients.
    half_angle_deg – thread half angle (30° for UN/ISO).

    The 0.625·μ_c·d collar term is Shigley's empirical effective-radius
    approximation for a typical hex / SHCS head with washer.
    """
    d  = d_mm / 1000.0
    p  = p_mm / 1000.0
    dp = d - 0.649519 * p
    dm = 0.5 * (dp + d)
    alpha = math.radians(half_angle_deg)
    sec_a = 1.0 / math.cos(alpha)
    lam = math.atan(p / (math.pi * dm))
    K_t = (math.tan(lam) + mu_t * sec_a) / (1.0 - mu_t * math.tan(lam) * sec_a)
    return preload_N * (0.5 * dm * K_t + 0.625 * mu_c * d)


def _stress_area_iso(d_mm, p_mm):
    """ISO 898-1 tensile stress area in mm²:  As = π/4 · (d - 0.9382·p)²"""
    dt = d_mm - 0.9382 * p_mm
    return math.pi / 4.0 * dt * dt


def _stress_area_un(d_in, tpi):
    """UN/UNF tensile stress area in in²:  As = π/4 · (d - 0.9743/n)²"""
    dt = d_in - 0.9743 / tpi
    return math.pi / 4.0 * dt * dt


# ====================================================================
#  TI linear-regulator (LDO) Vout calculator
# ====================================================================
#
# Vref / Vout-equation constants extracted from the TI datasheets in
# 01_Datasheets\02B_ICs_Analog_Power\02 Regulator Linear\.  Five
# distinct feedback topologies are supported:
#
#   • "ldo_pos"  – standard non-inverting divider, Vout = Vref·(1+R1/R2)
#                  Used by: TPS7A39 (positive ch), TPS7A4701 adj mode,
#                  LMZ14202H (switching module, same divider math)
#   • "ldo_neg"  – same divider with a negative Vref; -|Vref|·(1+R1/R2)
#                  Used by: TPS72301
#   • "ldo_inv"  – inverting amp referenced to BUF pin: -Vbuf·(R1/R2)
#                  Used by: TPS7A39 (negative ch)
#   • "3term"    – 3-terminal adj with Iadj correction:
#                    Vout = Vref·(1+R2/R1) + Iadj·R2
#                  Used by: LM337 (negative), TL1963A-Q1 (positive)
#   • "iref"     – precision current source × single R:
#                    Vout = I_ref · R
#                  Used by: TPS7A94
#   • "anyout"   – binary-weighted pin-strap (no resistors):
#                    Vout = V_floor + Σ(grounded pin weights)
#                  Used by: TPS7A4700, TPS7A4701 ANY-OUT mode
#
# LM340/LM7805 (fixed-output) and TPS727 (factory-EEPROM) are not
# user-adjustable and are intentionally omitted.

TI_LDO_PARTS = [
    ("TPS7A4701 (resistor divider mode)", {
        "topology": "ldo_pos",
        "vref": 1.4,
        "vout_min": 1.4, "vout_max": 34.0,
        "polarity": "+",
        "equation": "Vout = Vref · (1 + R1/R2)",
        "constants": "Vref = 1.4 V",
        "image": "TPS7A4701.png",
    }),
    ("TPS7A4700 / 4701 (ANY-OUT pin-strap)", {
        "topology": "anyout",
        "v_floor": 1.4,
        "anyout_weights": [0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 6.4],
        "anyout_labels": ["0.1V", "0.2V", "0.4V", "0.8V",
                          "1.6V", "3.2V", "6.4V(a)", "6.4V(b)"],
        "vout_min": 1.4, "vout_max": 20.5,
        "polarity": "+",
        "equation": "Vout = 1.4 V + Σ(grounded pin weights)",
        "constants": "V_floor = 1.4 V,  step = 100 mV",
        "image": "TPS7A4700.png",
    }),
    ("TPS7A39 (positive channel)", {
        "topology": "ldo_pos",
        "vref": 1.19,
        "vout_min": 1.2, "vout_max": 30.0,
        "polarity": "+",
        "equation": "Vout(p) = V_NR/SS · (1 + R1P/R2P)",
        "constants": "V_NR/SS = 1.19 V",
        "image": "TPS7A39_pos.png",
    }),
    ("TPS7A39 (negative channel)", {
        "topology": "ldo_inv",
        "vbuf": 1.19,
        "vout_min": -30.0, "vout_max": 0.0,
        "polarity": "-",
        "equation": "Vout(n) = −V_BUF · (R1N / R2N)",
        "constants": "V_BUF ≈ V_NR/SS = 1.19 V",
        "image": "TPS7A39_neg.png",
    }),
    ("LM337 (negative 3-terminal)", {
        "topology": "3term",
        "vref": 1.25,
        "iadj": 65e-6,
        "vout_min": -37.0, "vout_max": -1.25,
        "polarity": "-",
        "equation": "|Vout| = Vref · (1 + R2/R1) + I_adj · R2",
        "constants": "Vref = 1.25 V,  I_adj ≈ 65 µA",
        "image": "LM337.png",
    }),
    ("TL1963A-Q1 (positive 3-terminal)", {
        "topology": "3term",
        "vref": 1.21,
        "iadj": 3e-6,
        "vout_min": 1.21, "vout_max": 20.0,
        "polarity": "+",
        "equation": "Vout = Vref · (1 + R2/R1) + I_adj · R2",
        "constants": "Vref = 1.21 V,  I_adj ≈ 3 µA",
        "image": "TL1963A.png",
    }),
    ("TPS72301 (negative LDO)", {
        "topology": "ldo_neg",
        "vref": 1.186,
        "vout_min": -10.0, "vout_max": -1.2,
        "polarity": "-",
        "equation": "Vout = −1.186 V · (1 + R1/R2)",
        "constants": "|Vref| = 1.186 V",
        "image": "TPS72301.png",
    }),
    ("TPS7A94 (single-resistor adjustable)", {
        "topology": "iref",
        "i_ref": 150e-6,
        "vout_min": 0.4, "vout_max": 5.5,
        "polarity": "+",
        "equation": "Vout = I_NR/SS(nom) · R_NR/SS",
        "constants": "I_NR/SS(nom) = 150 µA,  Vin 1.7–5.7 V,  Iout ≤ 1 A",
        "image": "TPS7A94.png",
    }),
    ("LMZ14202H (2 A SIMPLE SWITCHER module)", {
        "topology": "ldo_pos",
        "vref": 0.8,
        "vout_min": 5.0, "vout_max": 24.0,
        "polarity": "+",
        "equation": "Vo = 0.8 V · (1 + R_FBT / R_FBB)",
        "constants": "Vref = 0.8 V,  Vin 6–42 V,  Iout ≤ 2 A",
        "image": "LMZ14202H.png",
    }),
    ("TPSM63602 (2 A buck power module)", {
        "topology": "ldo_pos",
        "vref": 1.0,
        "vout_min": 1.0, "vout_max": 16.0,
        "polarity": "+",
        "equation": "Vout = 1 V · (1 + R_FBT / R_FBB)",
        "constants": "Vref = 1.0 V,  Vin 3–36 V,  Iout ≤ 2 A",
        "image": "TPSM63602.png",
    }),
]


# Directory holding the reference-schematic images for each TI
# datasheet.  PNG is the default produced by the extraction script,
# but the resolver below accepts any common raster format so a user
# can drop in their own JPG / GIF / BMP / WebP override.
TI_LDO_IMG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "resource", "ICs")

# Extensions tried in order when resolving a part's image.  Most
# specific to least: PNG (lossless schematic), JPG/JPEG (camera-quality
# overrides), then a handful of other formats Qt loads natively.
TI_LDO_IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


def _resolve_ic_image(image_field):
    """Return the absolute path to the first existing image for
    `image_field` in `TI_LDO_IMG_DIR`, or None if nothing was found.

    Accepts either a bare stem ("TPS7A4701") or a filename with an
    extension ("TPS7A4701.png").  The stem path strips any extension
    and tries every TI_LDO_IMG_EXTS form so the user can drop in a
    .jpg replacement without editing TI_LDO_PARTS.  When the spec
    already names a specific file that exists, that exact file wins."""
    if not image_field:
        return None
    direct = os.path.join(TI_LDO_IMG_DIR, image_field)
    if os.path.isfile(direct):
        return direct
    stem = os.path.splitext(image_field)[0]
    for ext in TI_LDO_IMG_EXTS:
        candidate = os.path.join(TI_LDO_IMG_DIR, stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


# ====================================================================
#  Galvanic-corrosion compatibility table (anodic index, MIL-STD-889)
# ====================================================================
#
# Anodic index = each metal's open-circuit potential vs. a gold (Au)
# reference, in volts.  When two metals are joined in the presence of
# an electrolyte, the metal with the more-negative anodic index becomes
# the anode and corrodes preferentially.  The galvanic driving force is
# the magnitude of |ΔV| between the two.
#
# Field-tested compatibility thresholds (per MIL-STD-889 and Mil-Hdbk-454):
#   |ΔV| ≤ 0.15 V   →  compatible in any environment
#   |ΔV| ≤ 0.25 V   →  OK in normal indoor / sheltered outdoor (rule
#                       of thumb: ≤ 0.5 V for harsh / marine, ≤ 0.25 V
#                       for normal, ≤ 0.15 V for controlled humidity)
#   |ΔV| ≤ 0.50 V   →  OK only in dry / controlled environments
#   |ΔV| >  0.50 V   →  incompatible — anode will corrode whenever any
#                       moisture bridges the joint
#
# Values are nominal — they shift with alloy temper, passivation, and
# the specific electrolyte (seawater vs. sweat vs. industrial steam).
# Use this table as a first-pass screen, not a final corrosion model.

GALVANIC_METALS = [
    # (display name,                    anodic index V vs. gold)
    ("Gold, solid + plated",             -0.00),
    ("Rhodium plated on Ag-plate Cu",    -0.05),
    ("Silver, solid + plated",           -0.15),
    ("Nickel, solid + plated",           -0.15),
    ("Stainless 316, passive",           -0.05),
    ("Stainless 304, passive",           -0.05),
    ("Stainless 410, passive",           -0.15),
    ("Titanium",                         -0.15),
    ("Monel (Cu-Ni)",                    -0.20),
    ("Copper, brass, bronze",            -0.35),
    ("Tin-lead solder",                  -0.55),
    ("Tin plate, tin-bronze",            -0.65),
    ("Lead, solid + plated",             -0.70),
    ("Stainless 316, active",            -0.85),
    ("Carbon steel, low-alloy steel",    -0.85),
    ("Cast iron",                        -0.85),
    ("Aluminum 2024 (alclad)",           -0.75),
    ("Aluminum 6061, 5052, 1100",        -0.90),
    ("Cadmium plated",                   -0.80),
    ("Zinc plated, hot-dip galv steel",  -1.25),
    ("Magnesium",                        -1.75),
]


class GalvanicTab(QWidget):
    """Galvanic-corrosion compatibility table.

    Shows an N×N matrix of metals coloured by the absolute anodic-index
    difference between each pair (the galvanic driving force).  Drop-
    down selectors above the matrix isolate one specific pair and print
    the ΔV + compatibility verdict, so the chart serves both as a
    quick-reference and a per-joint check."""

    THRESHOLDS = [
        (0.15, QColor(196, 232, 196), "Compatible — any environment"),
        (0.25, QColor(232, 232, 196), "OK indoor / sheltered outdoor"),
        (0.50, QColor(252, 220, 176), "Dry / controlled only"),
        (10.0, QColor(252, 196, 196), "Incompatible — corrosion likely"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        title = QLabel("Galvanic-corrosion compatibility "
                       "(MIL-STD-889 anodic index)")
        title.setStyleSheet("font-weight:bold;")
        outer.addWidget(title)

        # --- per-pair quick check ---
        pair_row = QHBoxLayout()
        pair_row.setSpacing(8)
        pair_row.addWidget(QLabel("Metal A:"))
        self.cb_a = QComboBox()
        for name, _ in GALVANIC_METALS:
            self.cb_a.addItem(name)
        self.cb_a.setMaximumHeight(22)
        self.cb_a.setMinimumWidth(180)
        self.cb_a.currentIndexChanged.connect(self._on_pair_changed)
        pair_row.addWidget(self.cb_a)
        pair_row.addSpacing(10)
        pair_row.addWidget(QLabel("Metal B:"))
        self.cb_b = QComboBox()
        for name, _ in GALVANIC_METALS:
            self.cb_b.addItem(name)
        self.cb_b.setMaximumHeight(22)
        self.cb_b.setMinimumWidth(180)
        self.cb_b.setCurrentIndex(min(9, len(GALVANIC_METALS) - 1))
        self.cb_b.currentIndexChanged.connect(self._on_pair_changed)
        pair_row.addWidget(self.cb_b)
        pair_row.addStretch(1)
        outer.addLayout(pair_row)

        self.pair_label = QLabel("")
        self.pair_label.setTextFormat(Qt.RichText)
        self.pair_label.setStyleSheet(
            "background:#fafafa; border:1px solid #aaa; "
            "padding:6px; font-family:Tahoma;")
        self.pair_label.setMinimumHeight(34)
        outer.addWidget(self.pair_label)

        # --- legend ---
        legend = QHBoxLayout()
        legend.setSpacing(10)
        legend.addWidget(QLabel("Legend:"))
        for max_dv, color, descr in self.THRESHOLDS:
            sw = QLabel(" ")
            sw.setFixedSize(14, 14)
            sw.setStyleSheet(
                f"background:{color.name()}; border:1px solid #999;")
            legend.addWidget(sw)
            tag = QLabel(f"|ΔV| ≤ {max_dv:g} V" if max_dv < 10
                         else "|ΔV| > 0.5 V")
            tag.setStyleSheet("color:#444;")
            legend.addWidget(tag)
            legend.addSpacing(4)
        legend.addStretch(1)
        outer.addLayout(legend)

        # --- N×N compatibility matrix ---
        self.tbl = QTableWidget(len(GALVANIC_METALS) + 1,
                                len(GALVANIC_METALS) + 1)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.horizontalHeader().setVisible(False)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QAbstractItemView.NoSelection)
        self.tbl.setShowGrid(True)
        self.tbl.verticalHeader().setDefaultSectionSize(20)
        # Header row + column = the anodic-index value of each metal
        for c, (name, idx) in enumerate(GALVANIC_METALS):
            item = QTableWidgetItem(f"{idx:+.2f}")
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QColor(232, 232, 232))
            f = item.font(); f.setBold(True); item.setFont(f)
            item.setToolTip(name)
            self.tbl.setItem(0, c + 1, item)
            row_item = QTableWidgetItem(name)
            row_item.setBackground(QColor(232, 232, 232))
            f = row_item.font(); f.setBold(True); row_item.setFont(f)
            row_item.setToolTip(f"{name}   ({idx:+.2f} V vs. Au)")
            self.tbl.setItem(c + 1, 0, row_item)
        # Cells: |ΔV| between the row metal and column metal
        for r, (name_r, idx_r) in enumerate(GALVANIC_METALS):
            for c, (name_c, idx_c) in enumerate(GALVANIC_METALS):
                dv = abs(idx_r - idx_c)
                color, descr = self._verdict(dv)
                item = QTableWidgetItem(f"{dv:.2f}")
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(color)
                item.setToolTip(
                    f"{name_r}  ↔  {name_c}\n"
                    f"|ΔV| = {dv:.2f} V — {descr}")
                self.tbl.setItem(r + 1, c + 1, item)
        # Column / row widths
        self.tbl.setColumnWidth(0, 200)
        for c in range(1, self.tbl.columnCount()):
            self.tbl.setColumnWidth(c, 44)
        outer.addWidget(self.tbl, 1)

        self._on_pair_changed()

    def _verdict(self, dv):
        for limit, color, descr in self.THRESHOLDS:
            if dv <= limit:
                return color, descr
        # Shouldn't reach — fall back to "incompatible"
        return self.THRESHOLDS[-1][1], self.THRESHOLDS[-1][2]

    def _on_pair_changed(self, *_):
        a_name, a_idx = GALVANIC_METALS[self.cb_a.currentIndex()]
        b_name, b_idx = GALVANIC_METALS[self.cb_b.currentIndex()]
        dv = abs(a_idx - b_idx)
        color, descr = self._verdict(dv)
        # Anode = more-negative index
        if a_idx < b_idx:
            anode, cathode = a_name, b_name
        elif b_idx < a_idx:
            anode, cathode = b_name, a_name
        else:
            anode = cathode = "(same potential — no driving force)"
        html = (
            f"<b>{a_name}</b> ({a_idx:+.2f} V) "
            f"<span style='color:#888;'>↔</span> "
            f"<b>{b_name}</b> ({b_idx:+.2f} V)<br/>"
            f"<span style='font-size:11pt;'>|ΔV| = "
            f"<b>{dv:.2f} V</b></span> &nbsp; "
            f"<span style='background:{color.name()};"
            f"padding:1px 6px;border:1px solid #888;'>"
            f"{descr}</span><br/>"
            f"<span style='color:#666;'>Anode (corrodes): "
            f"{anode}</span>"
        )
        self.pair_label.setText(html)

    # ----- finder hook ------------------------------------------------
    def title(self):
        return "Galvanic"

    def search_entries(self, tab_name):
        return [(tab_name, self.cb_a, self)]


class TIRegSchematic(QWidget):
    """Simplified divider / 3-terminal / current-source schematic.

    The rendered topology is driven by `set_topology()` so a single
    widget handles every part — the IC block is fixed, the feedback
    network underneath changes."""

    DIEL   = QColor(218, 234, 252)
    METAL  = QColor( 90,  90, 130)
    LBL    = QColor( 30,  30,  30)
    SIG    = QColor( 40,  80, 160)
    GND    = QColor(110, 110, 110)
    RES    = QColor(250, 230, 170)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._topology = "ldo_pos"
        self._fb_pin_name = "FB"
        self._part_label = ""
        self._pixmap = None        # set when an extracted PDF image is available
        self.setFixedSize(380, 320)
        # Transparent background — let the card behind show through.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def set_topology(self, topology, fb_pin_name="FB", part_label="",
                     image_path=None):
        self._topology = topology
        self._fb_pin_name = fb_pin_name
        self._part_label = part_label
        # Load the reference-design image from disk when given; clear it
        # otherwise so a previously-selected part's image doesn't leak.
        if image_path and os.path.isfile(image_path):
            self._pixmap = QPixmap(image_path)
            if self._pixmap.isNull():
                self._pixmap = None
        else:
            self._pixmap = None
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setFont(QFont("Tahoma", 8))
        # Prefer the extracted reference-design PDF image when one is
        # available — drawn scaled to fit the widget while preserving
        # aspect ratio.  Falls back to the hand-drawn topology figure
        # for any part that doesn't have a PNG yet.
        if self._pixmap is not None:
            target = self.rect()
            scaled = self._pixmap.scaled(
                target.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            x = (target.width() - scaled.width()) // 2
            y = (target.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
            p.end()
            return
        if self._topology in ("ldo_pos", "ldo_neg", "3term"):
            self._draw_divider(p, is_3term=(self._topology == "3term"),
                               negative=(self._topology == "ldo_neg"))
        elif self._topology == "ldo_inv":
            self._draw_inverting(p)
        elif self._topology == "iref":
            self._draw_iref(p)
        elif self._topology == "anyout":
            self._draw_anyout(p)
        else:
            p.drawText(self.rect(), Qt.AlignCenter, "(no schematic)")
        p.end()

    # -- helpers -------------------------------------------------------
    # Pin-attach y-coordinates inside the IC block.  Wires connect at
    # PIN_TOP_DY for IN/OUT; the bottom edge (y + h) is the attach
    # point for GND / FB drops to the network below.  Labels sit
    # cleanly below the top wires and above the bottom edge — no
    # overlap with each other or with the centered part name.
    PIN_TOP_DY    = 10
    LBL_TOP_DY    = 24
    LBL_BOT_UP    = 8     # baseline = y + h - LBL_BOT_UP
    BLOCK_MIN_H   = 64

    def _ic_block(self, p, x, y, w=70, h=None, pin_out="OUT", pin_fb="FB"):
        if h is None or h < self.BLOCK_MIN_H:
            h = self.BLOCK_MIN_H
        p.setPen(QPen(self.LBL, 1))
        p.setBrush(QColor(240, 240, 245))
        p.drawRect(x, y, w, h)
        fm = QFontMetrics(p.font())
        out_w = fm.horizontalAdvance(pin_out)
        fb_w  = fm.horizontalAdvance(pin_fb)
        # Pin labels — top row at y + LBL_TOP_DY baseline (sits cleanly
        # below the y + PIN_TOP_DY wire), bottom row at y + h - LBL_BOT_UP.
        p.drawText(x + 6,             y + self.LBL_TOP_DY, "IN")
        p.drawText(x + w - out_w - 6, y + self.LBL_TOP_DY, pin_out)
        p.drawText(x + 6,             y + h - self.LBL_BOT_UP, "GND")
        p.drawText(x + w - fb_w - 6,  y + h - self.LBL_BOT_UP, pin_fb)
        # Input arrow + output stub at PIN_TOP_DY
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x - 28, y + self.PIN_TOP_DY, x, y + self.PIN_TOP_DY)
        p.drawLine(x + w, y + self.PIN_TOP_DY,
                   x + w + 24, y + self.PIN_TOP_DY)
        # Part-name centered between the top-label band (ends at
        # LBL_TOP_DY) and the bottom-label band (begins at h - LBL_BOT_UP
        # - ascent).  Bold, but small enough to never collide.
        if self._part_label:
            f = p.font(); f.setBold(True); p.setFont(f)
            fm2 = QFontMetrics(p.font())
            label_w = fm2.horizontalAdvance(self._part_label)
            text_x = x + max(4, (w - label_w) // 2)
            top_text_bot = y + self.LBL_TOP_DY
            bot_text_top = y + h - self.LBL_BOT_UP - fm2.height()
            mid = (top_text_bot + bot_text_top) // 2
            text_y = mid + fm2.ascent() // 2 + 2
            p.setPen(QPen(self.LBL, 1))
            p.drawText(text_x, text_y, self._part_label)
            f.setBold(False); p.setFont(f)

    def _draw_resistor(self, p, x, y_top, y_bot, label):
        p.setPen(QPen(self.LBL, 1))
        p.setBrush(self.RES)
        p.drawRect(x - 7, y_top, 14, y_bot - y_top)
        p.setPen(self.LBL)
        p.drawText(x + 12, (y_top + y_bot) // 2 + 4, label)

    def _draw_gnd(self, p, x, y):
        p.setPen(QPen(self.GND, 2))
        p.drawLine(x - 10, y, x + 10, y)
        p.drawLine(x - 7, y + 4, x + 7, y + 4)
        p.drawLine(x - 4, y + 8, x + 4, y + 8)

    # -- topologies ----------------------------------------------------
    def _draw_divider(self, p, is_3term, negative):
        # IC at top-left, FB pin drops down to the divider mid-point.
        ic_x, ic_y, ic_w, ic_h = 20, 24, 80, self.BLOCK_MIN_H
        fb_pin = "ADJ" if is_3term else self._fb_pin_name
        self._ic_block(p, ic_x, ic_y, ic_w, ic_h,
                       pin_out="OUT", pin_fb=fb_pin)
        # Output line from OUT pin going right then down to the top of R1
        x_out = ic_x + ic_w + 24
        y_out = ic_y + 10
        x_div = x_out + 70
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(ic_x + ic_w, y_out, x_div, y_out)
        # R1 (Rtop)
        y_r1_top = y_out + 4
        y_r1_bot = y_r1_top + 36
        self._draw_resistor(p, x_div, y_r1_top, y_r1_bot, "R1")
        # Junction at R1 bottom; tap goes left to FB pin
        y_mid = y_r1_bot + 6
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x_div, y_r1_bot, x_div, y_mid + 6)
        # FB tap horizontal
        x_fb_pin = ic_x + ic_w - 12
        y_fb_pin = ic_y + ic_h
        # Drop from FB pin straight down then over to junction
        p.drawLine(x_fb_pin, y_fb_pin, x_fb_pin, y_mid + 6)
        p.drawLine(x_fb_pin, y_mid + 6, x_div, y_mid + 6)
        # R2 (Rbot)
        y_r2_top = y_mid + 6
        y_r2_bot = y_r2_top + 36
        self._draw_resistor(p, x_div, y_r2_top, y_r2_bot, "R2")
        # GND
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x_div, y_r2_bot, x_div, y_r2_bot + 8)
        self._draw_gnd(p, x_div, y_r2_bot + 8)
        # Vout label
        p.setPen(self.LBL)
        f = p.font(); f.setBold(True); p.setFont(f)
        sign = "−" if negative else ""
        p.drawText(x_out, y_out - 4, f"{sign}Vout")
        f.setBold(False); p.setFont(f)

    def _draw_inverting(self, p):
        # IC with inverting-amp icon: BUF pin reference and FBN
        ic_x, ic_y, ic_w, ic_h = 20, 24, 80, self.BLOCK_MIN_H
        self._ic_block(p, ic_x, ic_y, ic_w, ic_h,
                       pin_out="OUTN", pin_fb="FBN")
        # BUF pin drawn as an external stub on the right side at
        # vertical mid-height so it never overlaps with the OUTN / FBN
        # pin labels printed inside the block.
        y_buf = ic_y + ic_h // 2 + 4
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(ic_x + ic_w, y_buf, ic_x + ic_w + 14, y_buf)
        p.setPen(self.LBL)
        p.drawText(ic_x + ic_w + 16, y_buf + 4, "BUF")
        # output line
        x_out = ic_x + ic_w + 24
        y_out = ic_y + 10
        x_div = x_out + 70
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(ic_x + ic_w, y_out, x_div, y_out)
        # R1N (top, OUT to FB)
        y_r1_top = y_out + 4
        y_r1_bot = y_r1_top + 36
        self._draw_resistor(p, x_div, y_r1_top, y_r1_bot, "R1N")
        # FB tap → R2N → BUF
        y_mid = y_r1_bot + 6
        p.setPen(QPen(self.SIG, 2))
        x_fb_pin = ic_x + ic_w - 12
        y_fb_pin = ic_y + ic_h
        p.drawLine(x_fb_pin, y_fb_pin, x_fb_pin, y_mid + 6)
        p.drawLine(x_fb_pin, y_mid + 6, x_div, y_mid + 6)
        # R2N to BUF
        y_r2_top = y_mid + 6
        y_r2_bot = y_r2_top + 36
        self._draw_resistor(p, x_div, y_r2_top, y_r2_bot, "R2N")
        # to BUF: line from R2N bottom back to BUF pin
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x_div, y_r2_bot, x_div, y_r2_bot + 14)
        x_buf = ic_x + ic_w
        y_buf = ic_y + ic_h // 2 + 4
        p.drawLine(x_div, y_r2_bot + 14, x_buf - 6, y_r2_bot + 14)
        p.drawLine(x_buf - 6, y_r2_bot + 14, x_buf - 6, y_buf)
        p.drawLine(x_buf - 6, y_buf, x_buf, y_buf)
        # −Vout label
        p.setPen(self.LBL)
        f = p.font(); f.setBold(True); p.setFont(f)
        p.drawText(x_out, y_out - 4, "−Vout")
        f.setBold(False); p.setFont(f)

    def _draw_iref(self, p):
        # IC with current source pulling from NR/SS pin into single R
        ic_x, ic_y, ic_w, ic_h = 20, 24, 90, self.BLOCK_MIN_H
        self._ic_block(p, ic_x, ic_y, ic_w, ic_h,
                       pin_out="OUT", pin_fb="NR/SS")
        # Current-source symbol next to NR/SS pin
        p.setPen(QPen(self.LBL, 1))
        x_pin = ic_x + ic_w - 12
        y_pin = ic_y + ic_h
        x_src = x_pin
        y_src = y_pin + 30
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(x_src - 10, y_src - 10, 20, 20)
        # arrow inside circle (downward current)
        p.drawLine(x_src, y_src - 6, x_src, y_src + 6)
        p.drawLine(x_src - 4, y_src + 2, x_src, y_src + 6)
        p.drawLine(x_src + 4, y_src + 2, x_src, y_src + 6)
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x_pin, y_pin, x_pin, y_src - 10)
        # R from current-source tail to GND
        y_r_top = y_src + 10
        y_r_bot = y_r_top + 40
        self._draw_resistor(p, x_src, y_r_top, y_r_bot, "R")
        p.setPen(QPen(self.SIG, 2))
        p.drawLine(x_src, y_src + 10, x_src, y_r_top)
        p.drawLine(x_src, y_r_bot, x_src, y_r_bot + 8)
        self._draw_gnd(p, x_src, y_r_bot + 8)
        # Output label
        x_out = ic_x + ic_w + 24
        y_out = ic_y + 10
        p.setPen(self.LBL)
        f = p.font(); f.setBold(True); p.setFont(f)
        p.drawText(x_out, y_out - 4, "Vout")
        f.setBold(False); p.setFont(f)
        # I_REF label
        p.setPen(self.LBL)
        p.drawText(x_src + 14, y_src + 4, "150 µA")

    def _draw_anyout(self, p):
        # IC block + 8 pin-strap legs.  "ANY-OUT[7:0]" is too long to fit
        # in the bottom-right of the block alongside "GND" — leave that
        # corner empty; the 8 labelled stubs already document the bus.
        ic_x, ic_y, ic_w, ic_h = 10, 24, 90, 110
        self._ic_block(p, ic_x, ic_y, ic_w, ic_h,
                       pin_out="OUT", pin_fb="")
        # 8 short legs out the right side, each labelled
        labels = ["6.4", "6.4", "3.2", "1.6", "0.8", "0.4", "0.2", "0.1"]
        x_pin = ic_x + ic_w
        for i, lab in enumerate(labels):
            y_p = ic_y + 14 + i * 10
            p.setPen(QPen(self.SIG, 1))
            p.drawLine(x_pin, y_p, x_pin + 14, y_p)
            p.setPen(self.LBL)
            p.drawText(x_pin + 16, y_p + 3, f"{lab} V")
        # GND bus at bottom
        p.setPen(QPen(self.GND, 2))
        p.drawLine(ic_x + 16, ic_y + ic_h + 18, ic_x + ic_w + 70,
                   ic_y + ic_h + 18)
        # OUT label
        p.setPen(self.LBL)
        f = p.font(); f.setBold(True); p.setFont(f)
        p.drawText(ic_x + ic_w + 24, ic_y + 8, "Vout")
        f.setBold(False); p.setFont(f)


class TIRegTab(QWidget):
    """Texas Instruments linear-regulator (LDO) output-voltage calculator.

    Pick a TI part from the dropdown.  Depending on the part's feedback
    topology the right-hand panel shows either:
        • Resistor divider — enter any two of (R1, R2, Vout) and the
          third solves out;
        • ANY-OUT pin strap — tick the pins you'll ground, Vout sums;
        • Single-resistor current-source (TPS7A94) — enter R or Vout.
    """

    # Pre-canned standard rail voltages (positive).  Negative-polarity
    # parts auto-negate these; the dropdown is filtered to each part's
    # vout_min/vout_max, so a 5.5 V LDO and a 24 V module both show only
    # the rails they can actually reach.
    COMMON_RAILS = [0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 1.8, 2.5, 2.8, 3.0,
                    3.3, 3.6, 5.0, 5.5, 6.0, 9.0, 12.0, 15.0, 18.0, 24.0,
                    28.0, 33.0]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = None
        # Per-part value cache so switching parts and coming back
        # preserves what the engineer typed.  Keyed by the displayed
        # part name (TI_LDO_PARTS[i][0]).
        self._part_states = {}
        self._prev_part_name = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        # ---- top header: dropdown with fuzzy finder + part info ------
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(QLabel("IC:"))
        self.cb_part = QComboBox()
        for label, _ in TI_LDO_PARTS:
            self.cb_part.addItem(label)
        # Editable combobox + case-insensitive contains-match completer:
        # the user can type any substring ("LM33", "negative", "anyout")
        # and the popup narrows live.  setInsertPolicy(NoInsert) prevents
        # the entered text from being added as a new item by mistake.
        self.cb_part.setEditable(True)
        self.cb_part.setInsertPolicy(QComboBox.NoInsert)
        completer = self.cb_part.completer()
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        self.cb_part.setMinimumWidth(320)
        self.cb_part.setMaximumHeight(22)
        self.cb_part.currentIndexChanged.connect(self._on_part_changed)
        head.addWidget(self.cb_part)
        head.addStretch(1)
        outer.addLayout(head)

        # ---- equation/constants panel --------------------------------
        self.eq_label = QLabel("")
        self.eq_label.setTextFormat(Qt.RichText)
        self.eq_label.setStyleSheet(
            "background:#fafafa; border:1px solid #aaa; "
            "padding:6px; font-family:Tahoma;"
        )
        self.eq_label.setWordWrap(True)
        self.eq_label.setMinimumHeight(46)
        outer.addWidget(self.eq_label)

        # ---- middle: schematic | fields ------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(10)
        self.schematic = TIRegSchematic(self)
        middle.addWidget(self.schematic, 0, Qt.AlignTop)

        # Right panel: stacked widget — divider-mode page, anyout page,
        # iref-mode page.  Switching by topology.
        self.right_stack = QStackedWidget(self)
        middle.addWidget(self.right_stack, 1)

        # Page 0 — divider/3-term mode (R1, R2, Vout)
        self.page_divider = QWidget()
        gl = QGridLayout(self.page_divider)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setVerticalSpacing(4); gl.setHorizontalSpacing(6)
        self.ed_r1 = QLineEdit()
        self.ed_r2 = QLineEdit()
        self.ed_vout = QLineEdit()
        for ed in (self.ed_r1, self.ed_r2, self.ed_vout):
            ed.setMaximumHeight(20)
            ed.setMaximumWidth(120)
            ed.textEdited.connect(self._on_div_input_edited)
        gl.addWidget(QLabel("R1 (top):"),     0, 0, Qt.AlignRight)
        gl.addWidget(self.ed_r1,              0, 1)
        gl.addWidget(QLabel("Ω"),             0, 2)
        gl.addWidget(QLabel("R2 (bottom):"),  1, 0, Qt.AlignRight)
        gl.addWidget(self.ed_r2,              1, 1)
        gl.addWidget(QLabel("Ω"),             1, 2)
        # Common-rail quick pick — fills Vout with a standard rail
        # (sign-adjusted for negative parts) and solves the divider.
        gl.addWidget(QLabel("Common rail:"),  2, 0, Qt.AlignRight)
        self.cb_rail = QComboBox()
        self.cb_rail.addItem("(custom)")
        self.cb_rail.setMaximumHeight(20)
        self.cb_rail.currentIndexChanged.connect(self._on_rail_selected)
        gl.addWidget(self.cb_rail,            2, 1)
        gl.addWidget(QLabel(""),              2, 2)
        gl.addWidget(QLabel("Vout:"),         3, 0, Qt.AlignRight)
        gl.addWidget(self.ed_vout,            3, 1)
        gl.addWidget(QLabel("V"),             3, 2)
        # Solve-for hint
        self.div_status = QLabel("")
        self.div_status.setStyleSheet("color:#456;")
        gl.addWidget(self.div_status,         4, 0, 1, 3)
        # Standard-value recommendations — populated after every solve.
        # Two rows: E24 (a typical engineer's stock) + E96 (1% precision).
        sep_lbl = QLabel("Recommended standard values:")
        sep_lbl.setStyleSheet("color:#666; font-style:italic; padding-top:6px;")
        gl.addWidget(sep_lbl, 5, 0, 1, 3)
        self.eia_label = QLabel("")
        self.eia_label.setTextFormat(Qt.RichText)
        self.eia_label.setWordWrap(True)
        self.eia_label.setStyleSheet(
            "background:#f4f8f4; border:1px solid #bbb; "
            "padding:4px; font-family:Consolas, 'Courier New', monospace;")
        self.eia_label.setMinimumHeight(64)
        gl.addWidget(self.eia_label, 6, 0, 1, 3)
        gl.setRowStretch(7, 1)
        self.right_stack.addWidget(self.page_divider)

        # Page 1 — ANY-OUT pin-strap (8 checkboxes + Vout readout)
        self.page_anyout = QWidget()
        agl = QGridLayout(self.page_anyout)
        agl.setContentsMargins(0, 0, 0, 0)
        agl.setVerticalSpacing(2); agl.setHorizontalSpacing(6)
        # Common-rail picker — auto-grounds the binary-decomposition of
        # (rail - V_floor) into the 8 pin-weight bits.
        agl.addWidget(QLabel("Common rail:"), 0, 0, Qt.AlignRight)
        self.cb_rail_ao = QComboBox()
        self.cb_rail_ao.addItem("(custom)")
        self.cb_rail_ao.setMaximumHeight(20)
        self.cb_rail_ao.currentIndexChanged.connect(self._on_rail_ao_selected)
        agl.addWidget(self.cb_rail_ao, 0, 1, 1, 2)
        agl.addWidget(QLabel("Ground these ANY-OUT pins:"),
                      1, 0, 1, 3)
        self.anyout_boxes = []
        self.anyout_weights = []
        # populated when an anyout part is selected
        self.anyout_grid = agl
        self.ao_vout_lbl = QLabel("")
        self.ao_vout_lbl.setStyleSheet("font-weight:bold; color:#208040;")
        agl.addWidget(self.ao_vout_lbl, 99, 0, 1, 3)
        agl.setRowStretch(100, 1)
        self.right_stack.addWidget(self.page_anyout)

        # Page 2 — current-source single R (TPS7A94)
        self.page_iref = QWidget()
        il = QGridLayout(self.page_iref)
        il.setContentsMargins(0, 0, 0, 0)
        il.setVerticalSpacing(4); il.setHorizontalSpacing(6)
        self.ed_iref_r = QLineEdit()
        self.ed_iref_vout = QLineEdit()
        for ed in (self.ed_iref_r, self.ed_iref_vout):
            ed.setMaximumHeight(20); ed.setMaximumWidth(120)
            ed.textEdited.connect(self._on_iref_input_edited)
        il.addWidget(QLabel("R_NR/SS:"), 0, 0, Qt.AlignRight)
        il.addWidget(self.ed_iref_r,     0, 1)
        il.addWidget(QLabel("Ω"),        0, 2)
        il.addWidget(QLabel("Vout:"),    1, 0, Qt.AlignRight)
        il.addWidget(self.ed_iref_vout,  1, 1)
        il.addWidget(QLabel("V"),        1, 2)
        # Standard-rail quick pick — fills Vout and solves R_NR/SS.
        il.addWidget(QLabel("Common rail:"), 2, 0, Qt.AlignRight)
        self.cb_rail_ir = QComboBox()
        self.cb_rail_ir.addItem("(custom)")
        self.cb_rail_ir.setMaximumHeight(20)
        self.cb_rail_ir.currentIndexChanged.connect(self._on_rail_ir_selected)
        il.addWidget(self.cb_rail_ir,        2, 1)
        self.iref_status = QLabel("")
        self.iref_status.setStyleSheet("color:#456;")
        il.addWidget(self.iref_status,   3, 0, 1, 3)
        il.setRowStretch(4, 1)
        self.right_stack.addWidget(self.page_iref)

        outer.addLayout(middle, 1)

        self._on_part_changed(0)

    # ----- title / search hooks --------------------------------------
    def title(self):
        return "TI REG"

    def search_entries(self, tab_name):
        # One entry per part so Ctrl+Space finds "LMZ14202H", "TPS7A39", …
        # directly instead of only the tab.  activate_search_entry() below
        # switches the combo to whichever one the user picked.
        return [(f"{tab_name}  →  {name}", self.cb_part, self)
                for name, _spec in TI_LDO_PARTS]

    def activate_search_entry(self, label):
        """Finder picked one of our per-part rows — select that part."""
        i = self.cb_part.findText(label.split("  →  ")[-1])
        if i >= 0:
            self.cb_part.setCurrentIndex(i)

    # ----- session persistence ---------------------------------------
    def get_state(self):
        # Make sure the current part's pending values land in the cache
        # before we serialize.
        if self._prev_part_name is not None:
            self._snapshot_state(self._prev_part_name)
        return {
            "part":        self.cb_part.currentText(),
            "part_states": self._part_states,
        }

    def set_state(self, st):
        if not isinstance(st, dict):
            return
        cached = st.get("part_states")
        if isinstance(cached, dict):
            self._part_states = cached
        part_name = st.get("part")
        if isinstance(part_name, str):
            idx = self.cb_part.findText(part_name)
            if idx >= 0:
                self.cb_part.setCurrentIndex(idx)

    # ----- per-part state cache --------------------------------------
    def _snapshot_state(self, part_name):
        """Capture R1/R2/Vout (divider), R/Vout (iref), or checked
        pin-mask (anyout) for `part_name` into self._part_states."""
        if not part_name:
            return
        st = {
            "r1":     self.ed_r1.text(),
            "r2":     self.ed_r2.text(),
            "vout":   self.ed_vout.text(),
            "iref_r": self.ed_iref_r.text(),
            "iref_v": self.ed_iref_vout.text(),
            "driver": getattr(self, "_div_driver", None),
            "ao":     [cb.isChecked() for cb in self.anyout_boxes],
        }
        self._part_states[part_name] = st

    def _restore_state(self, part_name):
        """Restore inputs for `part_name` if a snapshot exists.  Returns
        True iff anything was restored — caller uses that to decide
        whether to run a fresh compute."""
        st = self._part_states.get(part_name)
        if not st:
            return False
        for ed, key in ((self.ed_r1, "r1"), (self.ed_r2, "r2"),
                        (self.ed_vout, "vout"),
                        (self.ed_iref_r, "iref_r"),
                        (self.ed_iref_vout, "iref_v")):
            ed.blockSignals(True)
            ed.setText(st.get(key, "") or "")
            ed.blockSignals(False)
        self._div_driver = st.get("driver")
        ao = st.get("ao", [])
        for cb, val in zip(self.anyout_boxes, ao):
            cb.blockSignals(True)
            cb.setChecked(bool(val))
            cb.blockSignals(False)
        return True

    # ----- part switch -----------------------------------------------
    def _on_part_changed(self, idx):
        if idx < 0 or idx >= len(TI_LDO_PARTS):
            return
        # Save outgoing part's state before we wipe the inputs.
        if self._prev_part_name is not None:
            self._snapshot_state(self._prev_part_name)
        name, spec = TI_LDO_PARTS[idx]
        self._current = spec
        self._prev_part_name = name
        # Clear every input before either restoring saved state or
        # leaving them blank for a never-seen part.
        for ed in (self.ed_r1, self.ed_r2, self.ed_vout,
                   self.ed_iref_r, self.ed_iref_vout):
            ed.blockSignals(True)
            ed.clear()
            ed.blockSignals(False)
        self.div_status.setText("")
        self.iref_status.setText("")
        self.eia_label.setText("")
        self._div_driver = None
        topology = spec["topology"]
        eq = spec.get("equation", "")
        const = spec.get("constants", "")
        polarity = spec.get("polarity", "")
        vmin = spec.get("vout_min")
        vmax = spec.get("vout_max")
        range_txt = ""
        if vmin is not None and vmax is not None:
            range_txt = f"  ·  Vout range: {vmin:g} V to {vmax:g} V"
        html = (f"<b>{name}</b>  <span style='color:#888;'>"
                f"({topology}, {polarity}){range_txt}</span><br/>"
                f"<span style='font-size:11pt;color:#900;'>{eq}</span>")
        if const:
            html += f"<br/><span style='color:#444;'>{const}</span>"
        self.eq_label.setText(html)
        # Sync schematic
        fb_pin = "FB"
        if topology == "3term": fb_pin = "ADJ"
        elif topology == "iref": fb_pin = "NR/SS"
        elif topology == "anyout": fb_pin = "ANY-OUT"
        short = name.split(" ")[0]
        img_path = _resolve_ic_image(spec.get("image"))
        self.schematic.set_topology(topology, fb_pin_name=fb_pin,
                                    part_label=short,
                                    image_path=img_path)
        # Populate the common-rail dropdowns with values appropriate
        # to this part's polarity / range (negate for negative parts,
        # drop any out-of-range rails).
        self._rebuild_rail_dropdowns(spec)
        # Switch right panel
        if topology == "anyout":
            self._rebuild_anyout(spec)
            self.right_stack.setCurrentWidget(self.page_anyout)
            # Restore prior pin selections if any, then recompute Vout.
            self._restore_state(name)
            self._compute_anyout()
        elif topology == "iref":
            self.right_stack.setCurrentWidget(self.page_iref)
            self._restore_state(name)
            self._compute_iref()
        else:
            self.right_stack.setCurrentWidget(self.page_divider)
            self._restore_state(name)
            self._compute_divider()

    # ----- common-rail dropdowns -------------------------------------
    def _rebuild_rail_dropdowns(self, spec):
        """Refresh the divider-page and ANY-OUT-page rail pickers with
        the rails this specific part can actually deliver."""
        polarity = spec.get("polarity", "+")
        vmin, vmax = spec.get("vout_min"), spec.get("vout_max")
        rails = []
        for v in self.COMMON_RAILS:
            actual = -v if polarity == "-" else v
            if vmin is not None and vmax is not None:
                if not (min(vmin, vmax) - 1e-6 <= actual <= max(vmin, vmax) + 1e-6):
                    continue
            rails.append(actual)
        for cb in (self.cb_rail, self.cb_rail_ao, self.cb_rail_ir):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("(custom)")
            for v in rails:
                cb.addItem(f"{v:g} V", v)
            cb.blockSignals(False)

    def _on_rail_ir_selected(self, idx):
        """Standard rail picked on the single-resistor page → set Vout and
        solve R_NR/SS for it."""
        if idx <= 0:
            return
        v = self.cb_rail_ir.itemData(idx)
        if v is None:
            return
        self.ed_iref_vout.blockSignals(True)
        self.ed_iref_vout.setText(f"{v:g}")
        self.ed_iref_vout.blockSignals(False)
        self.ed_iref_r.clear()          # let _compute_iref solve R from Vout
        self._compute_iref()

    def _on_rail_selected(self, idx):
        """User picked a common rail in the divider page → drop value
        into Vout and re-solve (treat Vout as the driver)."""
        if idx <= 0:
            return
        v = self.cb_rail.itemData(idx)
        if v is None:
            return
        self.ed_vout.blockSignals(True)
        self.ed_vout.setText(f"{v:g}")
        self.ed_vout.blockSignals(False)
        # If R2 is empty, default to 10 kΩ so we have something to
        # solve R1 against.  Common rule-of-thumb sizing.
        if not self.ed_r2.text().strip():
            self.ed_r2.blockSignals(True)
            self.ed_r2.setText("10k")
            self.ed_r2.blockSignals(False)
        self._div_driver = "vout"
        self._compute_divider()

    def _on_rail_ao_selected(self, idx):
        """User picked a common rail in the ANY-OUT page → set the
        binary decomposition of (rail - V_floor) into the pin
        checkboxes."""
        if idx <= 0 or not self.anyout_boxes:
            return
        target = self.cb_rail_ao.itemData(idx)
        if target is None:
            return
        floor = getattr(self, "_floor_v", 0.0)
        remaining = target - floor
        if remaining < 0:
            return
        # Greedy bit-pack from largest pin to smallest.  Pins are
        # already in spec order [0.1, 0.2, …, 6.4, 6.4]; sort
        # descending for the decomposition.
        order = sorted(range(len(self.anyout_weights)),
                       key=lambda i: -self.anyout_weights[i])
        chosen = set()
        for i in order:
            w = self.anyout_weights[i]
            if remaining + 1e-9 >= w and i not in chosen:
                chosen.add(i)
                remaining -= w
        for i, cb in enumerate(self.anyout_boxes):
            cb.blockSignals(True)
            cb.setChecked(i in chosen)
            cb.blockSignals(False)
        self._compute_anyout()

    # ----- divider / 3-term / inverting solver -----------------------
    def _on_div_input_edited(self, _text):
        # Identify which field the user just edited so the solver can
        # treat *that* one as the authoritative input and recompute one
        # of the remaining two (rather than falling through to the
        # all-three-filled "Check" branch when a stale Vout is sitting
        # in the field from a prior part).
        sender = self.sender()
        if sender is self.ed_r1:
            self._div_driver = "r1"
        elif sender is self.ed_r2:
            self._div_driver = "r2"
        elif sender is self.ed_vout:
            self._div_driver = "vout"
        self._compute_divider()

    def _parse_float(self, edit):
        t = edit.text().strip()
        if not t:
            return None
        try:
            return parse_field(t, "")
        except Exception:
            try:
                return float(t)
            except ValueError:
                return None

    @staticmethod
    def _fmt_r_edit(v):
        """Solved resistor, written into an input box: snapped to the
        nearest E96 (1%) stock value and shown with a k/M suffix rather
        than scientific notation.  _parse_float reads the suffix back."""
        if v is None or v <= 0:
            return ""
        r = _closest_eia(v, EIA_E96) or v
        if r >= 1e6:
            return f"{r / 1e6:.6g}M"
        if r >= 1e3:
            return f"{r / 1e3:.6g}k"
        return f"{r:.6g}"

    @staticmethod
    def _fmt_res(v):
        """Pretty-print a resistance value with k/M SI suffix."""
        if v is None or v <= 0:
            return "—"
        if v >= 1e6:
            return f"{v/1e6:.4g} MΩ"
        if v >= 1e3:
            return f"{v/1e3:.4g} kΩ"
        return f"{v:.4g} Ω"

    def _vout_from_pair(self, r1, r2):
        """Compute Vout for the current topology given a specific
        (R1, R2) resistor pair.  Returns None if topology doesn't use
        the standard divider form."""
        spec = self._current
        if spec is None or r1 is None or r2 is None or r2 <= 0:
            return None
        topo = spec["topology"]
        if topo in ("ldo_pos", "ldo_neg"):
            sign = -1.0 if topo == "ldo_neg" else 1.0
            return sign * spec["vref"] * (1.0 + r1 / r2)
        if topo == "ldo_inv":
            return -spec["vbuf"] * (r1 / r2)
        if topo == "3term":
            sign = -1.0 if spec.get("polarity") == "-" else 1.0
            if r1 <= 0:
                return None
            return sign * (spec["vref"] * (1.0 + r2 / r1)
                           + spec["iadj"] * r2)
        return None

    def _update_eia_table(self, r1, r2, vout_target):
        """Render the E12/E24/E96 recommendation table for the current
        (R1, R2) solve.  vout_target is the target / entered Vout used
        to compute the % error of each rounded pair."""
        if r1 is None or r2 is None or r1 <= 0 or r2 <= 0:
            self.eia_label.setText("")
            return
        rows = []
        for series_name, series in (("E12",  EIA_E12),
                                    ("E24",  EIA_E24),
                                    ("E96",  EIA_E96)):
            r1_s = _closest_eia(r1, series)
            r2_s = _closest_eia(r2, series)
            vout_s = self._vout_from_pair(r1_s, r2_s)
            if vout_s is None or vout_target in (None, 0):
                err_txt = "—"
            else:
                err = (vout_s - vout_target) / abs(vout_target) * 100
                color = "#080" if abs(err) < 1 else ("#840" if abs(err) < 3
                                                     else "#a00")
                err_txt = (f"<span style='color:{color};'>{err:+.2f}%</span>")
            vout_txt = ("—" if vout_s is None else f"{vout_s:.4g} V")
            rows.append(
                f"<tr><td><b>{series_name}</b></td>"
                f"<td>{self._fmt_res(r1_s)}</td>"
                f"<td>{self._fmt_res(r2_s)}</td>"
                f"<td>{vout_txt}</td>"
                f"<td>{err_txt}</td></tr>"
            )
        html = (
            "<table cellspacing='3' cellpadding='1' style='font-family:Consolas,monospace;'>"
            "<tr style='color:#666;'>"
            "<td><b>Series</b></td>"
            "<td><b>R1</b></td>"
            "<td><b>R2</b></td>"
            "<td><b>Vout (actual)</b></td>"
            "<td><b>Δ</b></td></tr>"
            + "".join(rows) +
            "</table>"
        )
        self.eia_label.setText(html)

    def _compute_divider(self):
        spec = self._current
        if not spec:
            return
        topology = spec["topology"]
        r1 = self._parse_float(self.ed_r1)
        r2 = self._parse_float(self.ed_r2)
        vout = self._parse_float(self.ed_vout)
        filled = sum(x is not None for x in (r1, r2, vout))
        if filled < 2:
            self.div_status.setText(
                "Enter any two of (R1, R2, Vout) to solve the third.")
            self.eia_label.setText("")
            return

        # When all three are filled, treat the most recently-edited
        # field as the driver and discard one of the other two so the
        # standard solve path picks the right target.  Priorities:
        #   driver=R1 or R2  → recompute Vout
        #   driver=Vout      → recompute R1 (the most common ask)
        driver = getattr(self, "_div_driver", None)
        if filled == 3 and driver in ("r1", "r2", "vout"):
            if driver in ("r1", "r2"):
                vout = None
            else:   # driver == "vout"
                r1 = None

        def set_locked(target_field, value):
            # Block signals so the edit doesn't recurse into this slot.
            target_field.blockSignals(True)
            if target_field in (self.ed_r1, self.ed_r2):
                target_field.setText(self._fmt_r_edit(value))
            else:
                target_field.setText(f"{value:.6g}")
            target_field.blockSignals(False)

        # Cache the target Vout (whatever the user entered) so the EIA
        # recommendation table can compute % error against it after the
        # solve writes a slightly-different rounded Vout back to the
        # field.
        vout_target_for_eia = vout

        # ---- LDO positive divider:  Vout = Vref·(1 + R1/R2) ----------
        if topology in ("ldo_pos", "ldo_neg"):
            vref = spec["vref"]
            sign = -1.0 if topology == "ldo_neg" else 1.0
            # Three solve directions
            try:
                if vout is None:
                    if r2 == 0:
                        raise ValueError("R2 must be > 0")
                    v = sign * vref * (1.0 + r1 / r2)
                    set_locked(self.ed_vout, v)
                    self.div_status.setText(
                        f"Vout solved: {v:.4g} V")
                elif r1 is None:
                    target = sign * vout / vref - 1.0
                    if target <= 0:
                        raise ValueError(
                            "Vout below Vref — divider can't reach it")
                    v = r2 * target
                    set_locked(self.ed_r1, v)
                    self.div_status.setText(
                        f"R1 solved: {v:.4g} Ω")
                elif r2 is None:
                    target = sign * vout / vref - 1.0
                    if target <= 0:
                        raise ValueError(
                            "Vout below Vref — divider can't reach it")
                    v = r1 / target
                    set_locked(self.ed_r2, v)
                    self.div_status.setText(
                        f"R2 solved: {v:.4g} Ω")
                else:
                    # All three given — show check
                    if r2 != 0:
                        calc = sign * vref * (1.0 + r1 / r2)
                        err_pct = abs(calc - vout) / max(abs(vout), 1e-9) * 100
                        self.div_status.setText(
                            f"Check: Vref·(1+R1/R2) = {calc:.4g} V "
                            f"({err_pct:.2f}% from entered Vout)")
            except Exception as exc:
                self.div_status.setText(f"⚠ {exc}")

        # ---- Inverting (TPS7A39 neg ch): Vout = -Vbuf·(R1/R2) --------
        elif topology == "ldo_inv":
            vbuf = spec["vbuf"]
            try:
                if vout is None:
                    if r2 == 0: raise ValueError("R2 must be > 0")
                    v = -vbuf * (r1 / r2)
                    set_locked(self.ed_vout, v)
                    self.div_status.setText(f"Vout solved: {v:.4g} V")
                elif r1 is None:
                    if vout >= 0:
                        raise ValueError("Vout must be negative")
                    v = (-vout / vbuf) * r2
                    set_locked(self.ed_r1, v)
                    self.div_status.setText(f"R1 solved: {v:.4g} Ω")
                elif r2 is None:
                    if vout >= 0:
                        raise ValueError("Vout must be negative")
                    v = r1 / (-vout / vbuf)
                    set_locked(self.ed_r2, v)
                    self.div_status.setText(f"R2 solved: {v:.4g} Ω")
                else:
                    if r2 != 0:
                        calc = -vbuf * (r1 / r2)
                        err = abs(calc - vout) / max(abs(vout), 1e-9) * 100
                        self.div_status.setText(
                            f"Check: −Vbuf·(R1/R2) = {calc:.4g} V "
                            f"({err:.2f}% from entered Vout)")
            except Exception as exc:
                self.div_status.setText(f"⚠ {exc}")

        # ---- 3-terminal: Vout = Vref·(1 + R2/R1) + Iadj·R2 ------------
        elif topology == "3term":
            vref = spec["vref"]
            iadj = spec["iadj"]
            sign = -1.0 if spec.get("polarity") == "-" else 1.0
            # For solving, Vout taken as magnitude when sign=-1
            target_v = abs(vout) if vout is not None else None
            try:
                if vout is None:
                    if r1 == 0: raise ValueError("R1 must be > 0")
                    mag = vref * (1.0 + r2 / r1) + iadj * r2
                    v = sign * mag
                    set_locked(self.ed_vout, v)
                    self.div_status.setText(f"Vout solved: {v:.4g} V")
                elif r2 is None:
                    # target_v = Vref(1 + R2/R1) + Iadj·R2
                    # target_v - Vref = R2·(Vref/R1 + Iadj)
                    # R2 = (target_v - Vref) / (Vref/R1 + Iadj)
                    if r1 == 0: raise ValueError("R1 must be > 0")
                    denom = vref / r1 + iadj
                    if denom <= 0: raise ValueError("Bad R1/Iadj")
                    v = (target_v - vref) / denom
                    if v <= 0:
                        raise ValueError("Vout below Vref")
                    set_locked(self.ed_r2, v)
                    self.div_status.setText(f"R2 solved: {v:.4g} Ω")
                elif r1 is None:
                    # target_v = Vref(1+R2/R1) + Iadj·R2
                    # target_v - Iadj·R2 - Vref = Vref·R2/R1
                    # R1 = Vref·R2 / (target_v - Iadj·R2 - Vref)
                    denom = target_v - iadj * r2 - vref
                    if denom <= 0: raise ValueError("Vout too low for this R2")
                    v = vref * r2 / denom
                    set_locked(self.ed_r1, v)
                    self.div_status.setText(f"R1 solved: {v:.4g} Ω")
                else:
                    if r1 != 0:
                        calc_mag = vref * (1.0 + r2 / r1) + iadj * r2
                        calc = sign * calc_mag
                        err = abs(calc - vout) / max(abs(vout), 1e-9) * 100
                        self.div_status.setText(
                            f"Check: Vref·(1+R2/R1)+Iadj·R2 = "
                            f"{calc:.4g} V ({err:.2f}% from entered Vout)")
            except Exception as exc:
                self.div_status.setText(f"⚠ {exc}")

        # ---- Common tail: refresh the EIA recommendation table with
        # the values currently in the input fields (which include any
        # value the solver just wrote back).  Use the user's original
        # vout entry as the error reference when available.
        r1_now   = self._parse_float(self.ed_r1)
        r2_now   = self._parse_float(self.ed_r2)
        vout_now = self._parse_float(self.ed_vout)
        self._update_eia_table(
            r1_now, r2_now,
            vout_target_for_eia if vout_target_for_eia is not None else vout_now)

    # ----- current-source solver (TPS7A94) ---------------------------
    def _on_iref_input_edited(self, _text):
        self._compute_iref()

    def _compute_iref(self):
        spec = self._current
        if not spec:
            return
        i_ref = spec["i_ref"]
        r = self._parse_float(self.ed_iref_r)
        vout = self._parse_float(self.ed_iref_vout)
        if r is not None and vout is None:
            v = i_ref * r
            self.ed_iref_vout.blockSignals(True)
            self.ed_iref_vout.setText(f"{v:.4g}")
            self.ed_iref_vout.blockSignals(False)
            self.iref_status.setText(f"Vout solved: {v:.4g} V")
        elif r is None and vout is not None:
            if vout <= 0:
                self.iref_status.setText("⚠ Vout must be > 0")
                return
            v = vout / i_ref
            self.ed_iref_r.blockSignals(True)
            self.ed_iref_r.setText(self._fmt_r_edit(v))
            self.ed_iref_r.blockSignals(False)
            r_e96 = _closest_eia(v, EIA_E96) or v
            self.iref_status.setText(
                f"R = {self._fmt_res(r_e96)} (E96) → Vout {i_ref * r_e96:.4g} V")
        elif r is not None and vout is not None:
            calc = i_ref * r
            err = abs(calc - vout) / max(abs(vout), 1e-9) * 100
            self.iref_status.setText(
                f"Check: I·R = {calc:.4g} V "
                f"({err:.2f}% from entered Vout)")
        else:
            self.iref_status.setText("Enter R or Vout.")

    # ----- ANY-OUT pin-strap -----------------------------------------
    def _rebuild_anyout(self, spec):
        # Tear down existing checkboxes
        for cb in self.anyout_boxes:
            cb.setParent(None)
            cb.deleteLater()
        self.anyout_boxes = []
        self.anyout_weights = []
        weights = spec.get("anyout_weights", [])
        labels = spec.get("anyout_labels", [])
        floor = spec.get("v_floor", 0.0)
        for i, (w, lab) in enumerate(zip(weights, labels)):
            cb = QCheckBox(f"{lab}  (+{w:g} V)")
            cb.stateChanged.connect(self._compute_anyout)
            # +2 = skip the rail-picker row (0) and the section heading (1)
            row = i + 2
            self.anyout_grid.addWidget(cb, row, 0, 1, 3)
            self.anyout_boxes.append(cb)
            self.anyout_weights.append(w)
        self._floor_v = floor
        self._compute_anyout()

    def _compute_anyout(self, *_):
        total = self._floor_v
        for cb, w in zip(self.anyout_boxes, self.anyout_weights):
            if cb.isChecked():
                total += w
        self.ao_vout_lbl.setText(
            f"Vout = {self._floor_v:g} V + Σ = {total:.3g} V")


class CountersinkCard(CalcCard):
    """Countersink axial depth for a metric screw:
        D = (OD − ID) / (2·tan(θ/2))"""

    _diagram_below = True

    def __init__(self):
        super().__init__("Countersink depth", [
            Field("od",    "Countersink OD",   "mm"),
            Field("id",    "Hole ID",          "mm"),
            Field("theta", "Included angle θ", "°"),
            Field("depth", "Depth D",          "mm", is_output=True),
        ])
        for name, val in (("od", "3.00"), ("id", "2.55"), ("theta", "90")):
            self.fields[name].edit.setText(val)
        self.recompute_from_inputs()

    def make_diagram(self):
        return CountersinkDiagram(self)

    @staticmethod
    def _format_for_field(val, field=None):
        if field is not None and field.name == "depth" \
                and isinstance(val, (int, float)):
            return f"{val:.3f}"                    # ≥ 3 decimal places
        return CalcCard._format_for_field(val, field)

    def compute(self, driver, v):
        od = v.get("od"); idv = v.get("id"); th = v.get("theta")
        if None in (od, idv, th) or th <= 0 or th >= 180:
            return {}
        return {"depth": (od - idv) / (2.0 * math.tan(math.radians(th / 2.0)))}


class MechanicalTab(QWidget):
    """McMaster-style reference: imperial / metric threads, drills,
    sheet-metal gauges, plus a bolt torque / preload calculator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("Mechanical reference")
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title)
        head.addSpacing(18)
        head.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setMaximumWidth(280)
        self.filter_edit.setPlaceholderText(
            "size / drill # / fraction / mm  (e.g.  M6, 1/4, #43, 0.125, 22)"
        )
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        head.addWidget(self.filter_edit)
        head.addStretch(1)
        outer.addLayout(head)

        if MECH_DATA is None:
            outer.addWidget(QLabel(
                "Reference data not found — expected at "
                "resource/mechanical_data.py."
            ))
            return

        self._subtabs = QTabWidget()
        self._subtabs.setDocumentMode(True)
        outer.addWidget(self._subtabs, 1)

        # --- imperial threads ---
        self._imp_tbl = self._make_table(
            ["Size", "Series", "TPI", "Major (in)", "Pitch ∅ (in)",
             "Minor ∅ (in)", "Tap drill", "Clearance", "Hex key"],
            [(r[0], r[1], str(r[2]), f"{r[3]:.4f}", f"{r[4]:.4f}",
              f"{r[5]:.4f}", r[6], r[7], r[8])
             for r in MECH_DATA.IMPERIAL_THREADS]
        )
        self._subtabs.addTab(self._imp_tbl, "Imperial threads")

        # --- metric threads (all values mm; "(mm)" stripped from headers
        # so the 8 columns fit at 620 px window width) ---
        self._met_tbl = self._make_table(
            ["Size", "Pitch", "Major", "Pitch ∅",
             "Minor ∅", "Tap", "Clear", "Hex"],
            [(r[0], f"{r[1]:.2f}", f"{r[2]:.2f}", f"{r[3]:.3f}",
              f"{r[4]:.3f}", f"{r[5]:.2f}", f"{r[6]:.1f}",
              ("—" if r[7] is None else f"{r[7]:g}"))
             for r in MECH_DATA.METRIC_THREADS]
        )
        met_holder = QWidget()
        met_lay = QVBoxLayout(met_holder)
        met_lay.setContentsMargins(0, 0, 0, 0)
        met_lay.setSpacing(2)
        met_caption = QLabel("All values in mm")
        met_caption.setStyleSheet("color:#666; font-style:italic;")
        met_lay.addWidget(met_caption)
        met_lay.addWidget(self._met_tbl, 1)
        self._subtabs.addTab(met_holder, "Metric threads")

        # --- drill sizes (all three families in one sortable table) ---
        drill_rows = []
        for n, inches in MECH_DATA.NUMBER_DRILLS:
            drill_rows.append(("Number", f"#{n}", inches))
        for letter, inches in MECH_DATA.LETTER_DRILLS:
            drill_rows.append(("Letter", letter, inches))
        for label, inches in MECH_DATA.FRACTIONAL_DRILLS:
            drill_rows.append(("Fraction", f'{label}"', inches))
        drill_rows.sort(key=lambda r: -r[2])  # largest first
        self._drill_tbl = self._make_table(
            ["Type", "Size", "Inches", "mm"],
            [(t, s, f"{i:.4f}", f"{i*25.4:.3f}") for t, s, i in drill_rows]
        )
        self._subtabs.addTab(self._drill_tbl, "Drill sizes")

        # --- sheet-metal gauges (Carbon steel + Aluminum side-by-side;
        # each table is narrow — Gauge / Inches / mm — so both fit
        # comfortably at a 620 px window width with the explicit column
        # widths set in _make_table). ---
        self._sheet_steel = self._make_table(
            ["Gauge", "Inches", "mm"],
            [(str(g), f"{t:.4f}", f"{t*25.4:.3f}")
             for g, t in MECH_DATA.SHEET_GAUGES_STEEL],
        )
        self._sheet_alu = self._make_table(
            ["Gauge", "Inches", "mm"],
            [(str(g), f"{t:.4f}", f"{t*25.4:.3f}")
             for g, t in MECH_DATA.SHEET_GAUGES_AL],
        )
        sheet_holder = QWidget()
        sheet_lay = QHBoxLayout(sheet_holder)
        sheet_lay.setContentsMargins(0, 0, 0, 0)
        sheet_lay.setSpacing(8)
        for tbl, caption in (
            (self._sheet_steel, "Carbon steel  (Mfr's Std)"),
            (self._sheet_alu,   "Aluminum  (Aluminum Assoc.)"),
        ):
            col = QWidget()
            col_lay = QVBoxLayout(col)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(2)
            lab = QLabel(caption)
            lab.setStyleSheet("color:#444; font-weight:bold;")
            col_lay.addWidget(lab)
            col_lay.addWidget(tbl, 1)
            sheet_lay.addWidget(col, 1)
        self._subtabs.addTab(sheet_holder, "Sheet metal")

        # --- screw-drive dimensions (Torx across-points, hex/square
        # across-flats) ---
        drives = getattr(MECH_DATA, "SCREW_DRIVES", None)
        if drives:
            self._drive_tbl = self._make_table(
                ["Drive", "Size", "mm", "in"],
                [(fam, size, f"{mm:.2f}", f"{mm / 25.4:.4f}")
                 for fam, size, mm in drives]
            )
            self._subtabs.addTab(self._drive_tbl, "Screw drives")

        # --- bolt calculator ---
        self._calc_widget = self._build_bolt_calc()
        self._subtabs.addTab(self._calc_widget, "Bolt calc")

        # --- beam deflection calculator ---
        self._beam_card = BeamDeflectionCard()
        beam_holder = QWidget()
        beam_lay = QVBoxLayout(beam_holder)
        beam_lay.setContentsMargins(8, 8, 8, 8)
        beam_lay.setSpacing(6)
        beam_lay.addWidget(self._beam_card, 0, Qt.AlignTop)
        beam_lay.addStretch(1)
        self._subtabs.addTab(beam_holder, "Beam calc")

        # --- countersink depth calculator ---
        self._csink_card = CountersinkCard()
        csink_holder = QWidget()
        csink_lay = QVBoxLayout(csink_holder)
        csink_lay.setContentsMargins(8, 8, 8, 8)
        csink_lay.setSpacing(6)
        csink_lay.addWidget(self._csink_card, 0, Qt.AlignTop)
        csink_lay.addStretch(1)
        self._subtabs.addTab(csink_holder, "Countersink")

        # all the tables for filter iteration
        self._tables = [
            self._imp_tbl, self._met_tbl, self._drill_tbl,
            self._sheet_steel, self._sheet_alu,
        ]
        if getattr(self, "_drive_tbl", None) is not None:
            self._tables.append(self._drive_tbl)

    # ---- helpers ------------------------------------------------------
    def _make_table(self, headers, rows):
        tbl = QTableWidget(len(rows), len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setAlternatingRowColors(False)
        tbl.setShowGrid(True)
        tbl.verticalHeader().setDefaultSectionSize(16)
        tbl.verticalHeader().setMinimumSectionSize(16)
        tbl.setSortingEnabled(False)
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                it = QTableWidgetItem(str(cell))
                if c >= 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tbl.setItem(r, c, it)

        # Qt's QHeaderView.ResizeToContents only inspects rows that are
        # currently visible, so columns lock to a width that elides values
        # which scroll into view later (Fraction -> "Fracti..", 25.400 ->
        # "25...."). Measure every row + header with QFontMetrics and set
        # explicit widths so nothing gets truncated. No stretch-last-section
        # — stretching the right column either balloons an empty cell or
        # squeezes the last column smaller than its content needs.
        fm_h = QFontMetrics(tbl.horizontalHeader().font())
        fm_c = QFontMetrics(tbl.font())
        hdr = tbl.horizontalHeader()
        hdr.setStretchLastSection(False)
        widths = []
        for c in range(len(headers)):
            # Header padding: +10 px on each side covers the sort-arrow
            # indicator + a comfortable margin without ballooning the
            # 9-column Imperial-threads table past the 620 px viewport.
            w = fm_h.horizontalAdvance(str(headers[c])) + 12
            for r in range(len(rows)):
                item = tbl.item(r, c)
                if item is not None:
                    # Cells are pad-only (no sort indicator); +10 px.
                    w = max(w, fm_c.horizontalAdvance(item.text()) + 10)
            widths.append(w)
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
            tbl.setColumnWidth(c, w)
        tbl._qc_natural_width = sum(widths)
        return tbl

    def _build_bolt_calc(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # Build the thread selector list combining both systems.
        thread_items = []
        for r in MECH_DATA.IMPERIAL_THREADS:
            # (label, system, d_mm, p_mm) — convert inch threads to mm for the
            # single torque formula below.
            d_mm = r[3] * 25.4
            p_mm = 25.4 / r[2]
            thread_items.append((r[0], "imperial", d_mm, p_mm))
        for r in MECH_DATA.METRIC_THREADS:
            thread_items.append((r[0], "metric", r[2], r[1]))
        self._thread_items = thread_items

        form = QGridLayout()
        form.setVerticalSpacing(4)
        form.setHorizontalSpacing(10)

        form.addWidget(QLabel("Thread:"),       0, 0)
        self.calc_thread = QComboBox()
        for t in thread_items:
            self.calc_thread.addItem(t[0])
        # M6 makes a reasonable default
        idx = self.calc_thread.findText("M6")
        if idx >= 0:
            self.calc_thread.setCurrentIndex(idx)
        form.addWidget(self.calc_thread, 0, 1)

        form.addWidget(QLabel("Grade:"),        1, 0)
        self.calc_grade = QComboBox()
        for g in MECH_DATA.BOLT_GRADES:
            self.calc_grade.addItem(g[0])
        idx = self.calc_grade.findText("ISO Class 8.8")
        if idx >= 0:
            self.calc_grade.setCurrentIndex(idx)
        form.addWidget(self.calc_grade, 1, 1)

        form.addWidget(QLabel("Thread friction µₜ:"), 2, 0)
        self.calc_mu_t = QDoubleSpinBox()
        self.calc_mu_t.setRange(0.05, 0.50)
        self.calc_mu_t.setSingleStep(0.01)
        self.calc_mu_t.setDecimals(3)
        self.calc_mu_t.setValue(0.15)
        form.addWidget(self.calc_mu_t, 2, 1)

        form.addWidget(QLabel("Collar friction µ𝒸:"), 3, 0)
        self.calc_mu_c = QDoubleSpinBox()
        self.calc_mu_c.setRange(0.05, 0.50)
        self.calc_mu_c.setSingleStep(0.01)
        self.calc_mu_c.setDecimals(3)
        self.calc_mu_c.setValue(0.15)
        form.addWidget(self.calc_mu_c, 3, 1)

        form.addWidget(QLabel("Joint:"),        4, 0)
        self.calc_reused = QComboBox()
        self.calc_reused.addItems(["Permanent (0.90 × proof)",
                                   "Reused (0.75 × proof)"])
        form.addWidget(self.calc_reused, 4, 1)

        # Outputs panel
        self.calc_out = QLabel("")
        self.calc_out.setTextFormat(Qt.RichText)
        self.calc_out.setStyleSheet(
            "background:#fafafa; border:1px solid #aaa; "
            "padding:8px; font-family:Tahoma;"
        )
        self.calc_out.setMinimumHeight(180)
        self.calc_out.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.calc_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.calc_out.setWordWrap(True)

        # Stack form above the details panel so the page fits at a 620 px
        # window width.  Horizontal layout truncates the details on the
        # right at narrow widths.
        form_holder = QWidget()
        form_holder.setLayout(form)
        lay.addWidget(form_holder, 0, Qt.AlignTop)
        lay.addWidget(self.calc_out, 1)

        for w in (self.calc_thread, self.calc_grade,
                  self.calc_reused):
            w.currentIndexChanged.connect(self._recompute_calc)
        for w in (self.calc_mu_t, self.calc_mu_c):
            w.valueChanged.connect(self._recompute_calc)

        self._recompute_calc()
        return page

    def _recompute_calc(self, *_):
        idx = self.calc_thread.currentIndex()
        if idx < 0:
            return
        label, system, d_mm, p_mm = self._thread_items[idx]
        grade = MECH_DATA.BOLT_GRADES[self.calc_grade.currentIndex()]
        gname, gsys, proof_MPa, tens_MPa, yield_MPa = grade

        # Cross-system note (imperial bolt + ISO grade etc.) — just a UX hint;
        # the math is consistent either way.
        if system != gsys:
            sys_note = (f"<i style='color:#a44;'>Note: {system} thread "
                        f"with a {gsys} grade — values still correct.</i><br/>")
        else:
            sys_note = ""

        # Stress area — keep the formula in mixed units only for display;
        # internal calc uses mm consistently.
        As_mm2 = _stress_area_iso(d_mm, p_mm)
        if system == "imperial":
            # Choose the original imperial values from the table for the
            # As_in² display so the standard As-in² is shown.
            tpi = 25.4 / p_mm
            d_in = d_mm / 25.4
            As_in2 = _stress_area_un(d_in, tpi)
        else:
            As_in2 = As_mm2 / 25.4**2

        proof_load_N = proof_MPa * 1e6 * As_mm2 * 1e-6  # MPa·mm² = N
        proof_load_kN = proof_load_N / 1000.0
        proof_load_lbf = proof_load_N * 0.224809

        # Recommended preload
        preload_frac = 0.75 if "Reused" in self.calc_reused.currentText() else 0.90
        Fi_N = preload_frac * proof_load_N

        mu_t = self.calc_mu_t.value()
        mu_c = self.calc_mu_c.value()
        torque_Nm = _bolt_torque_from_preload(Fi_N, d_mm, p_mm, mu_t, mu_c)
        torque_lbft = torque_Nm * 0.737562
        torque_lbin = torque_Nm * 8.85075

        # Lightweight K-factor (T = K * F * d) as a sanity check.
        K_factor = torque_Nm / (Fi_N * (d_mm / 1000.0))

        html = (
            f"{sys_note}"
            f"<b>{label}</b> &nbsp; "
            f"<span style='color:#666;'>d = {d_mm:.3f} mm "
            f"({d_mm/25.4:.4f}\")  ·  p = {p_mm:.3f} mm "
            f"({1/(p_mm/25.4):.2f} TPI)</span><br/><br/>"
            f"<table cellspacing='1' cellpadding='2' style='font-size:9pt;'>"
            f"<tr><td><b>Grade</b></td><td>{gname}</td>"
            f"    <td style='padding-left:24px;'><b>Proof strength</b></td>"
            f"    <td>{proof_MPa} MPa "
            f"({proof_MPa/6.895:.1f} ksi)</td></tr>"
            f"<tr><td><b>Stress area</b></td>"
            f"    <td>{As_mm2:.3f} mm² ({As_in2:.4f} in²)</td>"
            f"    <td style='padding-left:24px;'><b>Proof load</b></td>"
            f"    <td>{proof_load_kN:.2f} kN "
            f"({proof_load_lbf:.0f} lbf)</td></tr>"
            f"<tr><td><b>Preload target</b></td>"
            f"    <td>{Fi_N/1000:.2f} kN "
            f"({Fi_N*0.224809:.0f} lbf)</td>"
            f"    <td style='padding-left:24px;'><b>Fraction of proof</b></td>"
            f"    <td>{preload_frac*100:.0f} %</td></tr>"
            f"<tr><td><b>Tightening torque</b></td>"
            f"    <td><span style='font-size:11pt;color:#900;'>"
            f"<b>{torque_Nm:.2f} N·m</b></span>"
            f"    &nbsp;({torque_lbft:.2f} ft·lbf, {torque_lbin:.1f} in·lbf)</td>"
            f"    <td style='padding-left:24px;'><b>K-factor</b></td>"
            f"    <td>{K_factor:.3f}</td></tr>"
            f"</table>"
            f"<br/><i style='color:#666;font-size:8pt;'>"
            f"Shigley eq. 8-27 with the 0.625·µc·d empirical collar term "
            f"(typical SHCS/hex head + washer).  Adjust µ for plated, "
            f"lubed, or anti-seize-coated threads.</i>"
        )
        self.calc_out.setText(html)

    # ---- filter -------------------------------------------------------
    def _on_filter_changed(self, text):
        q = text.strip().lower()
        for tbl in self._tables:
            for r in range(tbl.rowCount()):
                if not q:
                    tbl.setRowHidden(r, False)
                    continue
                row_text = " ".join(
                    (tbl.item(r, c).text().lower() if tbl.item(r, c) else "")
                    for c in range(tbl.columnCount())
                )
                tbl.setRowHidden(r, q not in row_text)

    # ---- finder / persistence ----------------------------------------
    def title(self):
        return "Mechanical"

    def search_entries(self, tab_name):
        return [(tab_name, self.filter_edit, self)]

    def get_state(self):
        return {
            "subtab":   self._subtabs.currentIndex() if hasattr(self, "_subtabs") else 0,
            "filter":   self.filter_edit.text(),
            "thread":   self.calc_thread.currentText() if hasattr(self, "calc_thread") else "",
            "grade":    self.calc_grade.currentText() if hasattr(self, "calc_grade") else "",
            "mu_t":     float(self.calc_mu_t.value()) if hasattr(self, "calc_mu_t") else 0.15,
            "mu_c":     float(self.calc_mu_c.value()) if hasattr(self, "calc_mu_c") else 0.15,
            "joint":    self.calc_reused.currentText() if hasattr(self, "calc_reused") else "",
        }

    def set_state(self, st):
        if not isinstance(st, dict) or not hasattr(self, "_subtabs"):
            return
        si = st.get("subtab")
        if isinstance(si, int) and 0 <= si < self._subtabs.count():
            self._subtabs.setCurrentIndex(si)
        if isinstance(st.get("filter"), str):
            self.filter_edit.setText(st["filter"])
        for key, widget in (("thread", self.calc_thread),
                            ("grade",  self.calc_grade),
                            ("joint",  self.calc_reused)):
            v = st.get(key)
            if isinstance(v, str):
                ix = widget.findText(v)
                if ix >= 0:
                    widget.setCurrentIndex(ix)
        if isinstance(st.get("mu_t"), (int, float)):
            self.calc_mu_t.setValue(float(st["mu_t"]))
        if isinstance(st.get("mu_c"), (int, float)):
            self.calc_mu_c.setValue(float(st["mu_c"]))


# ====================================================================
#  PCBToolkit  —  Saturn PCB Toolkit tools, rcalc-native, from standards
# ====================================================================

# Copper foil weight (oz) -> base conductor thickness (mil).  1 oz = 1.37 mil
# (34.8 µm) per IPC.  Plating is added on top of the base foil.
_CU_WEIGHT_MIL = {
    "0.25 oz": 0.3425, "0.5 oz": 0.685, "1 oz": 1.37, "1.5 oz": 2.055,
    "2 oz": 2.74, "3 oz": 4.11, "4 oz": 5.48, "5 oz": 6.85,
}
_CU_PLATE_MIL = {
    "None": 0.0, "0.5 oz": 0.685, "1 oz": 1.37, "1.5 oz": 2.055, "2 oz": 2.74,
}
ALPHA_CU = 0.00393        # /°C, temperature coefficient of Cu resistivity
RHO_CU = 1.724e-8         # Ω·m at 20 °C (IACS 100 %)
MIL_TO_M = 2.54e-5        # one mil in metres
MIL_TO_MM = 0.0254

# Etch factor -> top-width reduction.  Trapezoidal conductor cross-section:
#   A = t·(W + W_top)/2 ,  W_top = W − factor·t
# 1:1 removes 2·t total (W_top = W − 2t); 2:1 removes t; None = rectangular.
_ETCH_FACTOR = {"1:1": 2.0, "2:1": 1.0, "None": 0.0}


def _trapezoid_area(W, t, etch="1:1"):
    """Conductor cross-section (sq.mil) for width W and thickness t (mil)
    with the given etch factor.  Matches Saturn's A = t·(W + W_top)/2."""
    if W is None or t is None or W <= 0 or t <= 0:
        return None
    w_top = W - _ETCH_FACTOR.get(etch, 2.0) * t
    if w_top < 0:
        w_top = 0.0
    return t * (W + w_top) / 2.0


class _CuStackMixin:
    """Shared copper-weight + plating selector row.  Subclasses read
    `self._cu_mil()` for total conductor thickness in mils."""

    _CU_DEFAULT = "1 oz"
    _PLATE_DEFAULT = "1 oz"

    def _cu_extras(self, with_plating=True):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Cu weight:"))
        self._cu_combo = QComboBox()
        for k in _CU_WEIGHT_MIL:
            self._cu_combo.addItem(k)
        self._cu_combo.setCurrentText(self._CU_DEFAULT)
        self._cu_combo.setMaximumHeight(20)
        self._cu_combo.currentIndexChanged.connect(lambda _i: self.recompute_from_inputs())
        h.addWidget(self._cu_combo)
        if with_plating:
            h.addWidget(QLabel("Plating:"))
            self._plate_combo = QComboBox()
            for k in _CU_PLATE_MIL:
                self._plate_combo.addItem(k)
            self._plate_combo.setCurrentText(self._PLATE_DEFAULT)
            self._plate_combo.setMaximumHeight(20)
            self._plate_combo.currentIndexChanged.connect(lambda _i: self.recompute_from_inputs())
            h.addWidget(self._plate_combo)
        h.addStretch(1)
        return w

    def _cu_mil(self):
        base = _CU_WEIGHT_MIL.get(self._cu_combo.currentText(), 0.0)
        plate = _CU_PLATE_MIL.get(self._plate_combo.currentText(), 0.0) \
            if hasattr(self, "_plate_combo") else 0.0
        return base + plate


class _PcbStateMixin:
    """Persist a PCBToolkit card's combo selections (Cu weight, plating,
    layer, etch, geometry, class, shape, type) across save/restore, on top
    of the base collapse state.  set_card_state runs before field restore, so
    the combos are correct when the card recomputes.  Also opts every
    PCBToolkit card into the two-column field grid."""

    _two_col_fields = True
    _COMBO_ATTRS = ("_cu_combo", "_plate_combo", "_layer_combo", "_etch_combo",
                    "_geo", "_cls_combo", "_shape_combo", "_type")

    def get_card_state(self):
        st = super().get_card_state()
        for attr in self._COMBO_ATTRS:
            cb = getattr(self, attr, None)
            if cb is not None:
                st[attr] = cb.currentText()
        return st

    def set_card_state(self, state):
        super().set_card_state(state)
        if not isinstance(state, dict):
            return
        for attr in self._COMBO_ATTRS:
            cb = getattr(self, attr, None)
            v = state.get(attr)
            if cb is not None and isinstance(v, str):
                i = cb.findText(v)
                if i >= 0:
                    cb.setCurrentIndex(i)


class ConductorPropertiesCard(_PcbStateMixin, _CuStackMixin, CalcCard):
    """IPC-2221 conductor current vs temperature rise, plus DC resistance,
    skin depth, voltage drop and power dissipation.

        I = k·ΔT^0.44·A^0.725   (k = 0.024 internal, 0.048 external; A in sq.mil)
        ρ(T) = ρ20·(1 + α·(T−20))
        R = ρ(T)·L/A   V = I·R   P = I_load²·R   δ = √(ρ/(π·f·µ0))"""

    def __init__(self):
        super().__init__("Conductor properties (IPC-2221)", [
            Field("w",       "Conductor width W",   "mil"),
            Field("length",  "Conductor length",    "mil"),
            Field("dt",      "Temp rise ΔT",        "°C"),
            Field("ta",      "Ambient temp",        "°C"),
            Field("freq",    "Frequency",           "MHz"),
            Field("i_load",  "Load current",        "A"),
            Field("t_total", "Total Cu thickness",  "mil",     is_output=True),
            Field("area",    "Cross-section",       "sq.mil",  is_output=True),
            Field("i_cond",  "Conductor current",   "A",       is_output=True),
            Field("w_req",   "Width for load I",    "mil",     is_output=True),
            Field("r_dc",    "DC resistance",       "Ω",       is_output=True),
            Field("delta",   "Skin depth δ",        "mil",     is_output=True),
            Field("skin_pct","Skin-depth %",        "%",       is_output=True),
            Field("v_drop",  "Voltage drop",        "V",       is_output=True),
            Field("v_loaded","Loaded voltage drop", "V",       is_output=True),
            Field("p_w",     "Power dissipation",   "W",       is_output=True),
            Field("p_dbm",   "Power dissipation",   "dBm",     is_output=True),
            Field("j",       "Current density",     "A/mm²",   is_output=True),
        ])
        self._layer_ext = True
        self._etch = "1:1"
        self.fields["dt"].edit.setPlaceholderText("20")
        self.fields["ta"].edit.setPlaceholderText("25")

    def make_extras(self):
        row = QWidget()
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(self._cu_extras())
        h.addWidget(QLabel("Layer:"))
        self._layer_combo = QComboBox()
        self._layer_combo.addItems(["External", "Internal"])
        self._layer_combo.setMaximumHeight(20)
        self._layer_combo.currentIndexChanged.connect(self._on_layer)
        h.addWidget(self._layer_combo)
        h.addWidget(QLabel("Etch:"))
        self._etch_combo = QComboBox()
        self._etch_combo.addItems(list(_ETCH_FACTOR))
        self._etch_combo.setMaximumHeight(20)
        self._etch_combo.currentIndexChanged.connect(self._on_etch)
        h.addWidget(self._etch_combo)
        h.addStretch(1)
        return row

    def _on_layer(self, idx):
        self._layer_ext = (idx == 0)
        self.recompute_from_inputs()

    def _on_etch(self, idx):
        self._etch = self._etch_combo.currentText()
        self.recompute_from_inputs()

    def compute(self, driver, v):
        W = v.get("w"); L = v.get("length"); dT = v.get("dt")
        ta = v.get("ta"); freq = v.get("freq"); i_load = v.get("i_load")
        t_total = self._cu_mil()
        if t_total <= 0:
            return {}
        out = {"t_total": t_total}
        k = 0.048 if self._layer_ext else 0.024
        area = _trapezoid_area(W, t_total, self._etch)
        if area is not None:
            out["area"] = area
        if area is not None and dT is not None and dT > 0:
            i_cond = k * (dT ** 0.44) * (area ** 0.725)
            out["i_cond"] = i_cond
        else:
            i_cond = None
        if dT is not None and dT > 0 and i_load is not None and i_load > 0:
            area_req = (i_load / (k * dT ** 0.44)) ** (1.0 / 0.725)
            out["w_req"] = area_req / t_total + _ETCH_FACTOR.get(self._etch, 2.0) * t_total / 2.0
        t_cond = (ta if ta is not None else 25.0) + (dT if dT is not None else 0.0)
        rho_t = RHO_CU * (1.0 + ALPHA_CU * (t_cond - 20.0))
        # Skin depth needs only frequency + temperature.
        if freq is not None and freq > 0:
            delta_m = sqrt(rho_t / (pi * freq * 1e6 * MU0))
            out["delta"] = delta_m / MIL_TO_M
            out["skin_pct"] = min(delta_m / (t_total * MIL_TO_M), 1.0) * 100.0
        # Current density needs only cross-section + conductor current.
        if area is not None and i_cond is not None:
            out["j"] = i_cond / (area * MIL_TO_MM ** 2)
        # DC resistance and the voltage / power terms need the length.
        if area is not None and L is not None and L > 0:
            a_m2 = area * MIL_TO_M ** 2
            r_dc = rho_t * (L * MIL_TO_M) / a_m2
            out["r_dc"] = r_dc
            if i_cond is not None:
                out["v_drop"] = i_cond * r_dc
            if i_load is not None:
                out["v_loaded"] = i_load * r_dc
                out["p_w"] = i_load * i_load * r_dc
                if out["p_w"] > 0:
                    out["p_dbm"] = 10.0 * log10(out["p_w"] / 1e-3)
        return out


class FusingCurrentCard(_PcbStateMixin, _CuStackMixin, CalcCard):
    """Onderdonk fusing current for a copper trace.

        I = A_cmil·√( log10((Tm−Ta)/(234+Ta)+1) / (33·t) )
        A_cmil = A_sqmil·4/π   (circular mils)"""

    def __init__(self):
        super().__init__("Fusing current (Onderdonk)", [
            Field("w",       "Conductor width W",  "mil"),
            Field("time",    "Fuse time",          "s"),
            Field("ta",      "Ambient temp",       "°C"),
            Field("tmelt",   "Melt temp",          "°C"),
            Field("i_target","Target current",     "A"),
            Field("area",    "Cross-section",      "sq.mil", is_output=True),
            Field("i_fuse",  "Fusing current",     "A",      is_output=True),
            Field("w_fuse",  "Width fusing at target I", "mil", is_output=True),
        ])
        self._etch = "1:1"
        self.fields["time"].edit.setPlaceholderText("1")
        self.fields["ta"].edit.setPlaceholderText("22")
        self.fields["tmelt"].edit.setPlaceholderText("1084.62")

    def make_extras(self):
        row = QWidget()
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(self._cu_extras())
        h.addWidget(QLabel("Etch:"))
        self._etch_combo = QComboBox()
        self._etch_combo.addItems(list(_ETCH_FACTOR))
        self._etch_combo.setMaximumHeight(20)
        self._etch_combo.currentIndexChanged.connect(self._on_etch)
        h.addWidget(self._etch_combo); h.addStretch(1)
        return row

    def _on_etch(self, idx):
        self._etch = self._etch_combo.currentText()
        self.recompute_from_inputs()

    def compute(self, driver, v):
        W = v.get("w"); t = v.get("time")
        ta = v.get("ta"); ta = 22.0 if ta is None else ta
        tm = v.get("tmelt"); tm = 1084.62 if tm is None else tm
        i_target = v.get("i_target")
        t_total = self._cu_mil()
        if t_total <= 0 or t is None or t <= 0 or tm <= ta:
            return {}
        ratio = (tm - ta) / (234.0 + ta)
        root = sqrt(log10(ratio + 1.0) / (33.0 * t))
        out = {}
        area = _trapezoid_area(W, t_total, self._etch)
        if area is not None:
            a_cmil = area * 4.0 / pi
            out["area"] = area
            out["i_fuse"] = a_cmil * root
        if i_target is not None and i_target > 0 and root > 0:
            a_cmil_req = i_target / root
            w_top_frac = _ETCH_FACTOR.get(self._etch, 2.0)
            # Invert the trapezoid: A = t·(W + W − f·t)/2 = t·(W − f·t/2).
            out["w_fuse"] = (a_cmil_req * pi / 4.0) / t_total + w_top_frac * t_total / 2.0
        return out


class DifferentialPairCard(_PcbStateMixin, CalcCard):
    """Edge-coupled differential impedance (Wadell/IPC approximations).

        Microstrip: Zdiff = 2·Z0·(1 − 0.48·exp(−0.96·S/H))
        Stripline:  Zdiff = 2·Z0·(1 − 0.347·exp(−2.9·S/H))
    Single-ended Z0 uses the same Hammerstad / IPC-2141 models as the
    TLines tab.  Zodd = Zdiff/2, Zeven = Z0²/Zodd."""

    def __init__(self):
        super().__init__("Differential pair (edge-coupled)", [
            Field("w",   "Trace width W",      "mil"),
            Field("h",   "Dielectric h (or b)","mil"),
            Field("s",   "Edge spacing S",     "mil"),
            Field("t",   "Trace thickness t",  "mil"),
            Field("er",  "Dielectric εr",      ""),
            Field("z0",  "Single-ended Z₀",    "Ω", is_output=True),
            Field("zdiff","Differential Zdiff","Ω", is_output=True),
            Field("zodd", "Z_odd",             "Ω", is_output=True),
            Field("zeven","Z_even",            "Ω", is_output=True),
            Field("coupl","Coupling",          "%", is_output=True),
        ])
        self._stripline = False

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Geometry:"))
        self._geo = QComboBox()
        self._geo.addItems(["Edge-coupled microstrip", "Edge-coupled stripline"])
        self._geo.setMaximumHeight(20)
        self._geo.currentIndexChanged.connect(self._on_geo)
        h.addWidget(self._geo); h.addStretch(1)
        return w

    def _on_geo(self, idx):
        self._stripline = (idx == 1)
        self.recompute_from_inputs()

    def compute(self, driver, v):
        W = v.get("w"); H = v.get("h"); S = v.get("s")
        T = v.get("t"); er = v.get("er")
        if None in (W, H, S, er) or W <= 0 or H <= 0 or S <= 0 or er <= 0:
            return {}
        w_mm = W * MIL_TO_MM; h_mm = H * MIL_TO_MM
        t_mm = (T or 0.0) * MIL_TO_MM
        if self._stripline:
            z0 = StriplineCard._z0(w_mm, h_mm, t_mm, er)
            if z0 is None or z0 <= 0:
                return {}
            zdiff = 2.0 * z0 * (1.0 - 0.347 * exp(-2.9 * S / H))
        else:
            r = MicrostripCard._z0_eeff(w_mm, h_mm, er, t_mm)
            if r is None:
                return {}
            z0 = r[0]
            zdiff = 2.0 * z0 * (1.0 - 0.48 * exp(-0.96 * S / H))
        zodd = zdiff / 2.0
        zeven = z0 * z0 / zodd if zodd > 0 else 0.0
        coupl = (zeven - zodd) / (zeven + zodd) * 100.0 if (zeven + zodd) > 0 else 0.0
        return {"z0": z0, "zdiff": zdiff, "zodd": zodd, "zeven": zeven, "coupl": coupl}


class MaxConductorLengthCard(_PcbStateMixin, CalcCard):
    """IPC-2251 max conductor length before a trace is a transmission line.

        BW(knee) = 0.35/tr      v = c/√εr      Sr = v·tr
        Lmax(IPC) = factor·Sr   (factor rule-of-thumb, default 0.25)
        λ_air = c/f             Lmax(freq) = λ_air / N  (default N=7)"""

    def __init__(self):
        super().__init__("Bandwidth & max conductor length (IPC-2251)", [
            Field("tr",      "Signal risetime",    "ns"),
            Field("freq",    "Frequency",          "MHz"),
            Field("er",      "Dielectric εr",      ""),
            Field("factor",  "Sr divide factor",   ""),
            Field("ndiv",    "λ divide factor N",  ""),
            Field("bw",      "Bandwidth (knee)",   "MHz", is_output=True),
            Field("v",       "Propagation speed",  "m/s", is_output=True),
            Field("lam_in",  "Full λ (air)",       "in",  is_output=True),
            Field("lipc_in", "Max length (IPC)",   "in",  is_output=True),
            Field("lipc_mm", "Max length (IPC)",   "mm",  is_output=True),
            Field("lfrq_in", "Max length (freq)",  "in",  is_output=True),
            Field("lfrq_mm", "Max length (freq)",  "mm",  is_output=True),
        ])
        self.fields["tr"].edit.setPlaceholderText("1")
        self.fields["er"].edit.setPlaceholderText("4.6")
        self.fields["factor"].edit.setPlaceholderText("0.25")
        self.fields["ndiv"].edit.setPlaceholderText("7")

    def compute(self, driver, v):
        tr = v.get("tr"); freq = v.get("freq"); er = v.get("er")
        factor = v.get("factor"); factor = 0.25 if factor is None else factor
        ndiv = v.get("ndiv"); ndiv = 7.0 if ndiv is None else ndiv
        out = {}
        f_use = None
        if tr is not None and tr > 0:
            bw = 0.35 / (tr * 1e-9) / 1e6
            out["bw"] = bw
            f_use = bw
        if er is not None and er > 0:
            vprop = C_LIGHT / sqrt(er)
            out["v"] = vprop
            if tr is not None and tr > 0:
                sr = vprop * tr * 1e-9
                out["lipc_in"] = factor * sr / 0.0254    # metres -> inches
                out["lipc_mm"] = factor * sr * 1000.0
        if freq is not None and freq > 0:
            f_use = freq
        if f_use is not None and f_use > 0 and ndiv > 0:
            lam_air = C_LIGHT / (f_use * 1e6)
            out["lam_in"] = lam_air / 0.0254
            out["lfrq_in"] = (lam_air / ndiv) / 0.0254
            out["lfrq_mm"] = (lam_air / ndiv) * 1000.0
        return out


class PadstackCard(_PcbStateMixin, CalcCard):
    """Plated through-hole annular ring and minimum pad (IPC-2221 class).

        AR_nom = (pad − drill)/2     AR_min = AR_nom − tol − reg
        min pad = drill + 2·(tol + reg) + 2·AR_class"""

    _CLASS_AR_MIL = {"Class 1": 0.0, "Class 2": 1.97, "Class 3": 2.95}

    def __init__(self):
        super().__init__("Padstack / annular ring (IPC-2221)", [
            Field("pad",   "Pad diameter",        "mil"),
            Field("drill", "Drilled hole Ø",      "mil"),
            Field("tol",   "Fab tolerance",       "mil"),
            Field("reg",   "Registration",        "mil"),
            Field("ar_nom","Annular ring (nom)",  "mil", is_output=True),
            Field("ar_min","Annular ring (min)",  "mil", is_output=True),
            Field("min_pad","Recommended min pad","mil", is_output=True),
            Field("status","Status",              "",    is_output=True),
        ])
        self._cls = "Class 2"
        self.fields["tol"].edit.setPlaceholderText("2")
        self.fields["reg"].edit.setPlaceholderText("3")

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("IPC class:"))
        self._cls_combo = QComboBox()
        self._cls_combo.addItems(list(self._CLASS_AR_MIL))
        self._cls_combo.setCurrentText("Class 2")
        self._cls_combo.setMaximumHeight(20)
        self._cls_combo.currentIndexChanged.connect(self._on_cls)
        h.addWidget(self._cls_combo); h.addStretch(1)
        return w

    def _on_cls(self, idx):
        self._cls = self._cls_combo.currentText()
        self.recompute_from_inputs()

    def compute(self, driver, v):
        pad = v.get("pad"); drill = v.get("drill")
        tol = v.get("tol"); tol = 2.0 if tol is None else tol
        reg = v.get("reg"); reg = 3.0 if reg is None else reg
        if None in (pad, drill) or pad <= 0 or drill <= 0:
            return {}
        ar_nom = (pad - drill) / 2.0
        ar_min = ar_nom - tol - reg
        ar_cls = self._CLASS_AR_MIL[self._cls]
        min_pad = drill + 2.0 * (tol + reg) + 2.0 * ar_cls
        return {
            "ar_nom": ar_nom, "ar_min": ar_min, "min_pad": min_pad,
            "status": "pass" if ar_min >= ar_cls else "fail",
        }


class PDNCard(_PcbStateMixin, CalcCard):
    """Power distribution network target impedance and decoupling count.

        Z_target = Vdd·ripple% / ΔI_transient
        SRF = 1/(2π·√(C·ESL))     N_caps = ceil(ESR / Z_target)"""

    def __init__(self):
        super().__init__("PDN target impedance", [
            Field("vdd",    "Supply Vdd",       "V"),
            Field("ripple", "Ripple",           "%"),
            Field("di",     "Transient ΔI",     "A"),
            Field("c_uf",   "Decap value",      "µF"),
            Field("esr",    "Decap ESR",        "Ω"),
            Field("esl",    "Decap ESL",        "nH"),
            Field("z_tgt",  "Target impedance", "Ω",   is_output=True),
            Field("srf",    "Decap SRF",        "MHz", is_output=True),
            Field("n_caps", "Decap count",      "",    is_output=True),
        ])
        self.fields["ripple"].edit.setPlaceholderText("5")

    def compute(self, driver, v):
        vdd = v.get("vdd"); ripple = v.get("ripple"); di = v.get("di")
        c_uf = v.get("c_uf"); esr = v.get("esr"); esl = v.get("esl")
        out = {}
        if None not in (vdd, ripple, di) and di > 0 and vdd > 0 and ripple > 0:
            z_tgt = vdd * (ripple / 100.0) / di
            out["z_tgt"] = z_tgt
            if esr is not None and esr > 0 and z_tgt > 0:
                out["n_caps"] = float(max(1, math.ceil(round(esr / z_tgt, 9))))
        if c_uf is not None and c_uf > 0 and esl is not None and esl > 0:
            out["srf"] = 1.0 / (2.0 * pi * sqrt(c_uf * 1e-6 * esl * 1e-9)) / 1e6
        return out


class PlanarInductorCard(_PcbStateMixin, CalcCard):
    """Planar spiral inductor, modified-Wheeler expression (Mohan et al. 1999).

        L = K1·µ0·N²·d_avg / (1 + K2·ρ)
        d_in = d_out − 2·(N·w + (N−1)·s)
        ρ (fill) = (d_out − d_in)/(d_out + d_in)   d_avg = (d_out + d_in)/2
    (Circle reuses the octagon coefficients as an approximation.)"""

    _COEFF = {          # (K1, K2)
        "Square":   (2.34, 2.75),
        "Hexagon":  (2.33, 3.82),
        "Octagon":  (2.25, 3.55),
        "Circle":   (2.25, 3.55),
    }

    def __init__(self):
        super().__init__("Planar spiral inductor", [
            Field("n",     "Turns N",         ""),
            Field("w",     "Conductor width w","mil"),
            Field("s",     "Conductor spacing s","mil"),
            Field("dout",  "Outer Ø",         "mil"),
            Field("din",   "Inner Ø",         "mil", is_output=True),
            Field("fill",  "Fill factor ρ",   "",    is_output=True),
            Field("l_nh",  "Inductance L",    "nH",  is_output=True),
        ])
        self._shape = "Square"
        self.fields["n"].edit.setPlaceholderText("5")

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Shape:"))
        self._shape_combo = QComboBox()
        self._shape_combo.addItems(list(self._COEFF))
        self._shape_combo.setMaximumHeight(20)
        self._shape_combo.currentIndexChanged.connect(self._on_shape)
        h.addWidget(self._shape_combo); h.addStretch(1)
        return w

    def _on_shape(self, idx):
        self._shape = self._shape_combo.currentText()
        self.recompute_from_inputs()

    def compute(self, driver, v):
        n = v.get("n"); w = v.get("w"); s = v.get("s"); dout = v.get("dout")
        if None in (n, w, s, dout) or n <= 0 or w <= 0 or s < 0 or dout <= 0:
            return {}
        din = dout - 2.0 * (n * w + (n - 1) * s)
        if din <= 0:
            return {"din": din, "fill": None, "l_nh": None}
        rho = (dout - din) / (dout + din)
        davg = (dout + din) / 2.0 * MIL_TO_M
        k1, k2 = self._COEFF[self._shape]
        L = k1 * MU0 * n * n * davg / (1.0 + k2 * rho)
        return {"din": din, "fill": rho, "l_nh": L * 1e9}


class CrystalPPMCard(_PcbStateMixin, CalcCard):
    """Crystal frequency tolerance (ppm ↔ Hz) and load-capacitance network.

        ppm = (Fmax − Fc)/Fc·1e6     Δf(Hz) = ppm·Fc(MHz)
        CL (from C1,C2) = C1·C2/(C1+C2) + C_stray
        Rule-of-thumb C = 2·(C_load − C_stray)"""

    def __init__(self):
        super().__init__("Crystal PPM / load capacitance", [
            Field("f_mhz",  "Center frequency", "MHz"),
            Field("ppm",    "Tolerance",        "ppm"),
            Field("df_hz",  "Δf",               "Hz"),
            Field("fmax_hz","Max frequency",    "Hz", is_output=True),
            Field("fmin_hz","Min frequency",    "Hz", is_output=True),
            Field("c1",     "C1",               "pF"),
            Field("c2",     "C2",               "pF"),
            Field("cstray", "Stray C",          "pF"),
            Field("cl_net", "Load C (C1∥C2+stray)","pF", is_output=True),
            Field("cload",  "Datasheet load C", "pF"),
            Field("c_rule", "Rule-of-thumb C",  "pF", is_output=True),
        ])

    def compute(self, driver, v):
        f_mhz = v.get("f_mhz"); ppm = v.get("ppm"); df = v.get("df_hz")
        out = {}
        if f_mhz is not None and f_mhz > 0:
            f_hz = f_mhz * 1e6
            d = None
            if (driver == "df_hz" or ppm is None) and df is not None:
                out["ppm"] = df / f_mhz
                d = df
            elif ppm is not None:
                d = f_mhz * ppm
                out["df_hz"] = d
            if d is not None:
                # Hz resolution exceeds fmt's .6g; format wide so e.g.
                # 50 MHz ± 25 ppm shows 50001250, not 5.00013e7.
                out["fmax_hz"] = f"{f_hz + d:.12g}"
                out["fmin_hz"] = f"{f_hz - d:.12g}"
        c1 = v.get("c1"); c2 = v.get("c2"); cstray = v.get("cstray")
        if None not in (c1, c2) and (c1 + c2) > 0:
            out["cl_net"] = c1 * c2 / (c1 + c2) + (cstray or 0.0)
        cload = v.get("cload")
        if cload is not None and cstray is not None:
            out["c_rule"] = 2.0 * (cload - cstray)
        return out


class ThermalManagementCard(_PcbStateMixin, CalcCard):
    """Junction temperature from a θ network plus a conduction spreader.

        Tj = Ta + P·(θjc + θcs + θsa)
        θ_spreader = t / (k·A)"""

    def __init__(self):
        super().__init__("Thermal management", [
            Field("p_w",    "Power P",          "W"),
            Field("tjc",    "θ_jc",             "°C/W"),
            Field("tcs",    "θ_cs",             "°C/W"),
            Field("tsa",    "θ_sa",             "°C/W"),
            Field("ta",     "Ambient temp",     "°C"),
            Field("k",      "Spreader k",       "W/m·K"),
            Field("area",   "Spreader area",    "mm²"),
            Field("thick",  "Spreader thickness","mm"),
            Field("tj",     "Junction temp Tj", "°C",   is_output=True),
            Field("ttot",   "θ total",          "°C/W", is_output=True),
            Field("tspr",   "θ spreader",       "°C/W", is_output=True),
        ])
        self.fields["ta"].edit.setPlaceholderText("25")
        self.fields["k"].edit.setPlaceholderText("385")

    def compute(self, driver, v):
        p = v.get("p_w"); tjc = v.get("tjc") or 0.0; tcs = v.get("tcs") or 0.0
        tsa = v.get("tsa") or 0.0; ta = v.get("ta"); ta = 25.0 if ta is None else ta
        out = {}
        ttot = tjc + tcs + tsa
        if ttot > 0:
            out["ttot"] = ttot
            if p is not None:
                out["tj"] = ta + p * ttot
        k = v.get("k"); area = v.get("area"); thick = v.get("thick")
        if None not in (k, area, thick) and k > 0 and area > 0 and thick > 0:
            out["tspr"] = (thick * 1e-3) / (k * area * 1e-6)
        return out


class ConductorImpedanceCard(_PcbStateMixin, _CuStackMixin, CalcCard):
    """Single-ended controlled impedance with copper-weight / plating, and
    the per-length line parameters Saturn reports.

        Tpd = √εeff / c    Lo = Z0·Tpd    Co = Tpd / Z0"""

    def __init__(self):
        super().__init__("Conductor impedance (controlled Z₀)", [
            Field("w",      "Conductor width W", "mil"),
            Field("h",      "Height h / plate b","mil"),
            Field("er",     "Dielectric εr",     ""),
            Field("z0",     "Z₀",                "Ω",     is_output=True),
            Field("eeff",   "εr effective",      "",      is_output=True),
            Field("lo",     "Lo",                "nH/in", is_output=True),
            Field("co",     "Co",                "pF/in", is_output=True),
            Field("tpd",    "Tpd",               "ps/in", is_output=True),
            Field("t_total","Total Cu thickness","mil",   is_output=True),
        ])
        self._stripline = False

    def make_extras(self):
        row = QWidget()
        h = QHBoxLayout(row); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(self._cu_extras())
        h.addWidget(QLabel("Type:"))
        self._type = QComboBox()
        self._type.addItems(["Microstrip", "Stripline"])
        self._type.setMaximumHeight(20)
        self._type.currentIndexChanged.connect(self._on_type)
        h.addWidget(self._type); h.addStretch(1)
        return row

    def _on_type(self, idx):
        self._stripline = (idx == 1)
        self.recompute_from_inputs()

    def compute(self, driver, v):
        W = v.get("w"); H = v.get("h"); er = v.get("er")
        t_total = self._cu_mil()
        if None in (W, H, er) or W <= 0 or H <= 0 or er <= 0:
            return {"t_total": t_total}
        w_mm = W * MIL_TO_MM; h_mm = H * MIL_TO_MM; t_mm = t_total * MIL_TO_MM
        if self._stripline:
            z0 = StriplineCard._z0(w_mm, h_mm, t_mm, er)
            if z0 is None or z0 <= 0:
                return {"t_total": t_total}
            eeff = er
        else:
            r = MicrostripCard._z0_eeff(w_mm, h_mm, er, t_mm)
            if r is None:
                return {"t_total": t_total}
            z0, eeff = r
        tpd_s_m = sqrt(eeff) / C_LIGHT               # s/m
        tpd_s_in = tpd_s_m * MIL_TO_MM               # s per inch (0.0254 m)
        return {
            "z0": z0, "eeff": eeff, "t_total": t_total,
            "tpd": tpd_s_in * 1e12,
            "lo": z0 * tpd_s_in * 1e9,
            "co": tpd_s_in / z0 * 1e12,
        }


class ErEffectiveCard(_PcbStateMixin, CalcCard):
    """Effective permittivity.

        Microstrip: εeff = (εr+1)/2 + (εr−1)/2·(1+12h/W)^−0.5  (Hammerstad)
        Stripline:  εeff = εr"""

    def __init__(self):
        super().__init__("εr effective", [
            Field("w",    "Conductor width W", "mil"),
            Field("h",    "Dielectric height", "mil"),
            Field("t",    "Trace thickness t", "mil"),
            Field("er",   "Dielectric εr",     ""),
            Field("eeff", "εr effective",      "", is_output=True),
        ])
        self._stripline = False

    def make_extras(self):
        w = QWidget()
        h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        h.addWidget(QLabel("Type:"))
        self._type = QComboBox()
        self._type.addItems(["Microstrip", "Stripline"])
        self._type.setMaximumHeight(20)
        self._type.currentIndexChanged.connect(self._on_type)
        h.addWidget(self._type); h.addStretch(1)
        return w

    def _on_type(self, idx):
        self._stripline = (idx == 1)
        self.recompute_from_inputs()

    def compute(self, driver, v):
        W = v.get("w"); H = v.get("h"); T = v.get("t"); er = v.get("er")
        if None in (W, H, er) or W <= 0 or H <= 0 or er <= 0:
            return {}
        if self._stripline:
            return {"eeff": er}
        r = MicrostripCard._z0_eeff(W * MIL_TO_MM, H * MIL_TO_MM, er, (T or 0.0) * MIL_TO_MM)
        if r is None:
            return {}
        return {"eeff": r[1]}


class GainChainCard(_PcbStateMixin, CalcCard):
    """Bench dB chain: dBm in + gain − attenuator → dBm out, Vout (50 Ω)."""

    def __init__(self):
        super().__init__("Gain chain (dBm → V)", [
            Field("dbm_in", "dBm in",       "dBm"),
            Field("gain",   "Gain",         "dB"),
            Field("atten",  "Attenuator",   "dB"),
            Field("dbm_out","dBm out",      "dBm", is_output=True),
            Field("v_out",  "V out (50 Ω)", "V",   is_output=True),
        ])

    def compute(self, driver, v):
        din = v.get("dbm_in"); g = v.get("gain") or 0.0; a = v.get("atten") or 0.0
        if din is None:
            return {}
        dout = din + g - a
        p_w = 10.0 ** ((dout - 30.0) / 10.0)
        return {"dbm_out": dout, "v_out": sqrt(p_w * 50.0)}


# ====================================================================
#  TAB BUILDER + MAIN WINDOW
# ====================================================================

TAB_LAYOUT = [
    # ----- Top-level: general-purpose calculator -----
    ("Calc", CalcTab),

    # ----- Top-level: LaTeX equation renderer -----
    ("LaTeX", LatexTab),

    # ----- RF group: signal levels + frequency-domain tools -----
    ("RF", [
        # Force 2-column layout despite the diagrams on SourceLoadCard /
        # PowerFactorCard (auto-pick would otherwise drop to 1 column).
        ("Power", [
            PowerWattsCard, DBRatioCard, VoltageCard, PowerSumCard,
            SourceLoadCard,
            SineVRMSCard, SquareVRMSCard, TriangleVRMSCard,
            PowerFactorCard,
        ], 2),
        ("Noise", [
            NFCard, ThermalNoiseCard, CascadeNFCard, SNRCard,
            PhaseNoiseJitterCard, JitterSNRCard,
        ], 2),
        ("VSWR / Match", [
            VSWRCard, ZGammaCard, ComplexZCard,
        ], 2),
        ("Smith Chart",  SmithChartTab),
        ("Frequency / λ", [
            FreqWaveCard, FreqMediumCard, PropagationTimeCard,
            ViaFenceIsolationCard,
        ], 2),
        # FreqBandCard owns a wide chart, kept on its own page.
        ("Bands", [FreqBandCard]),
        ("Mixers", [
            IP3Card, SFDRCard, MixerImageCard,
            ShannonCard, SymbolBitCard, BERCard, FMDeviationCard,
        ], 2),
        # DSP-side dynamic-range and modulation tools — kept in its own
        # sub-tab so it doesn't crowd Mixers.  More cards land here as
        # the Batch-2 plotters get built.
        ("DSP", [
            ADCDynamicRangeCard, FilterDesignCard,
        ]),
        ("Converter", DualStageConverterTab),
        # TLinesHeader pushes Material / Solve / Conductor / Length to
        # every TLineCard on the page.
        ("TLines", [
            CoaxZ0Card, MicrostripCard, StriplineCard,
            CPWCard, GCPWCard, TwinLeadCard, ElectricalLengthCard,
            CableLossCard, SkinDepthCard,
        ], None, TLinesHeader),
        ("Cavity / Waveguide", [
            RectangularCavityCard, PCBShieldModesCard, WaveguideCard,
        ]),
    ]),

    # ----- Antenna group: aperture, link, radar -----
    ("Antenna", [
        # AntennaDesignerTab rides at the top of the Antenna sub-tab
        # as a header; the per-formula cards stack below.
        ("Antenna", [
            DBiDBdCard, GainApertureCard, EIRPCard, BeamwidthCard,
            DipoleLengthCard, NearFarFieldCard,
        ], None, AntennaDesignerTab),
        ("Path Loss / Link", [
            FSPLCard, LinkBudgetCard, FresnelCard, HorizonCard,
        ]),
        ("Radar", [
            RadarRangeCard, RadarBlindSpeedCard,
        ]),
    ]),

    # ----- Components group: networks, SRF analyzer, resistor codes ---
    ("Components", [
        ("Networks", [
            CapacitorReactanceCard, InductorReactanceCard, RLCComboCard,
            AttenuatorPadCard, VoltageDividerCard,
            EIANearestCard, VoltageDropCard,
            ResistorSeriesParallelCard, CapacitorSeriesParallelCard,
            RiseFallTimeCard,
            DeltaWyeCard, DirectionalCouplerCard,
            ButterworthLP3Card, ButterworthHP3Card,
        ]),
        ("SRF",      CapacitorAnalyzerTab),
        ("Resistor", ResistorTab),
    ]),

    # ----- Top-level: op-amp / analog signal-chain helpers -----
    ("Analog", [
        OpAmpGainCard, OpAmpNoiseCard, OpAmpGBWCard,
    ]),

    # ----- Top-level: power-supply / driver helpers -----
    ("Power", [
        LEDCurrentLimiterCard, BatteryRuntimeCard, PulsePowerCard,
    ]),

    # ----- Top-level: PCB design helpers -----
    ("PCB", [
        EmbeddedResistorCard, ViaCharacteristicsCard,
        WireGaugeCard, MinSpacingCard, DrillChartCard,
        ThermalJunctionCard,
    ]),

    # ----- Top-level: Saturn PCB Toolkit tools (standards-based) -----
    ("PCBToolkit", [
        # cols=1: each card already lays its fields in two columns
        # (inputs | outputs), so one card per row fits a 630px-wide window.
        ("Conductor", [
            ConductorPropertiesCard, FusingCurrentCard,
            ConductorImpedanceCard, ErEffectiveCard,
        ], 1),
        ("Signal integrity", [
            DifferentialPairCard, MaxConductorLengthCard, CrystalPPMCard,
        ], 1),
        ("Layout", [
            PadstackCard, PlanarInductorCard,
        ], 1),
        ("Power / thermal", [
            PDNCard, ThermalManagementCard,
        ], 1),
        ("Conversions", [
            GainChainCard,
        ], 1),
    ]),

    # ----- Top-level: physics + unit conversions -----
    ("Physics", [
        OhmsLawCard, RCTimeCard, LCResonanceCard,
        PhotonEnergyCard, WaveSpeedCard, MassEnergyCard, KineticEnergyCard,
        IdealGasCard, LensEqnCard, SnellsLawCard, DopplerCard,
        PendulumCard, QuadraticCard, CoulombCard,
        FieldStrengthCard, LengthCard, TemperatureCard,
    ]),

    # ----- Top-level: IC calculators (Linear Reg today, more to come) -----
    ("ICs", [
        ("Linear Reg (TI)", TIRegTab),
    ]),

    # ----- Reference group: lookup tables only -----
    ("Reference", [
        ("Periodic",   PeriodicTableTab),
        ("Mechanical", MechanicalTab),
        ("Galvanic",   GalvanicTab),
    ]),
]


def build_tab(card_classes, cols=None, header_factory=None):
    """Build a tab page with optional header widget above the card grid.

    `header_factory`, when given, is a zero-arg callable that returns a
    QWidget instance (typically a QWidget subclass).  The widget is
    placed *above* the per-column card grid so a custom panel (e.g.
    AntennaDesignerTab) can sit at the top of an otherwise standard
    cards tab.  Returns (page, scroll, cards, header_widget) — header
    is None when no factory was supplied."""
    page = QWidget()
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    inner = QWidget()

    # Wrap header + card grid in a vertical layout so the header (when
    # present) sits above everything else and spans the full width.
    inner_v = QVBoxLayout(inner)
    inner_v.setContentsMargins(0, 0, 0, 0)
    inner_v.setSpacing(8)

    header_widget = None
    if header_factory is not None:
        header_widget = header_factory()
        inner_v.addWidget(header_widget)

    grid_container = QWidget()
    inner_v.addWidget(grid_container, 1)

    # Build the cards first so we can decide column count by inspecting
    # whether any of them has a diagram (those are wider and want 1 col).
    cards = [cls() for cls in card_classes]
    if cols is None:
        any_diagram = any(getattr(c, "_has_diagram", False) for c in cards)
        cols = 1 if any_diagram else 2

    # Per-column QVBoxLayouts inside a top-level QHBoxLayout.  Each column
    # packs its cards top-to-bottom independently — collapsing a card in one
    # column actually shrinks that column (a QGridLayout would have set every
    # row's height to max(left, right), so a collapse on one side just
    # exposed empty space on the other).  This also means cards in a row no
    # longer share a baseline: the right column 'flows' upward as the left
    # column collapses, so there is no extra padding between them.
    if cols <= 1:
        col_layout = QVBoxLayout(grid_container)
        col_layout.setContentsMargins(8, 6, 8, 6)
        col_layout.setSpacing(8)
        for c in cards:
            col_layout.addWidget(c)
        col_layout.addStretch(1)
        col_layouts = [col_layout]
    else:
        row = QHBoxLayout(grid_container)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(16)
        col_layouts = []
        for _ in range(cols):
            col_w = QWidget()
            col_w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
            col_l = QVBoxLayout(col_w)
            col_l.setContentsMargins(0, 0, 0, 0)
            col_l.setSpacing(8)
            # No stretch on column widgets — each takes its natural width and
            # the trailing addStretch absorbs all extra horizontal space, so
            # columns pack tightly at the left even on a maximised window.
            row.addWidget(col_w, 0)
            col_layouts.append(col_l)
        row.addStretch(1)
        for i, c in enumerate(cards):
            col_layouts[i % cols].addWidget(c)
        for cl in col_layouts:
            cl.addStretch(1)

    # Align field labels across card boundaries within each column.  Find
    # the widest label per column, force every label in that column to that
    # width.  Same per-column grouping as before; the change is purely in
    # how cards stack vertically.
    labels_by_col = {col: [] for col in range(cols)}
    for i, c in enumerate(cards):
        col = i % cols
        for f in c.fields.values():
            if f.label_widget is not None:
                labels_by_col[col].append(f.label_widget)
    for labs in labels_by_col.values():
        if not labs:
            continue
        max_w = max(lab.sizeHint().width() for lab in labs)
        for lab in labs:
            lab.setMinimumWidth(max_w)

    # Align diagrams horizontally inside each column: pin every card's
    # field-column widget to the column's max field-block width so the
    # diagram (drawn to the right of the fields) always starts at the
    # same x.  Skipped for cards that put the diagram above/below the
    # fields — those don't have a horizontal field/diagram split.
    fields_by_col = {col: [] for col in range(cols)}
    for i, c in enumerate(cards):
        col = i % cols
        fw = getattr(c, "_fields_widget", None)
        if fw is None:
            continue
        if getattr(c, "_diagram_above", False):
            continue
        if getattr(c, "_diagram_below", False):
            continue
        if not getattr(c, "_has_diagram", False):
            continue
        fields_by_col[col].append(fw)
    for fws in fields_by_col.values():
        if len(fws) < 2:
            continue
        max_w = max(fw.sizeHint().width() for fw in fws)
        for fw in fws:
            fw.setMinimumWidth(max_w)

    # Headers that need to interact with the cards below (e.g. the
    # TLines tab's "apply to all" bar) get a callback hook now that
    # the cards exist.
    if header_widget is not None and hasattr(header_widget, "connect_cards"):
        try:
            header_widget.connect_cards(cards)
        except Exception:
            pass

    scroll.setWidget(inner)
    outer.addWidget(scroll)
    return page, scroll, cards, header_widget


class OptionsDialog(QDialog):
    """Centralised user-preferences dialog.  All settings persist in the
    main config file via parent_main._cfg."""
    def __init__(self, parent_main):
        super().__init__(parent_main)
        self.parent_main = parent_main
        self.setWindowTitle("Options")
        self.setModal(True)
        self.setMinimumWidth(420)
        cfg = parent_main._cfg

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 10)
        outer.setSpacing(10)

        def section(title):
            v = QVBoxLayout(); v.setSpacing(2)
            h = QHBoxLayout(); h.setSpacing(8)
            t = QLabel(title); t.setStyleSheet("font-weight: bold;")
            h.addWidget(t, 0)
            ln = QFrame(); ln.setFrameShape(QFrame.HLine); ln.setFrameShadow(QFrame.Sunken)
            h.addWidget(ln, 1)
            v.addLayout(h)
            return v

        def field(parent_layout, label, widget):
            r = QHBoxLayout(); r.setContentsMargins(12, 0, 0, 0); r.setSpacing(8)
            la = QLabel(label); la.setMinimumWidth(170)
            r.addWidget(la, 0)
            r.addWidget(widget, 0)
            r.addStretch(1)
            parent_layout.addLayout(r)

        # ---- appearance ----
        app_sec = section("Appearance")
        outer.addLayout(app_sec)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Light  (Windows Classic)", "Dark"])
        self.theme_combo.setCurrentIndex(1 if cfg.get("theme") == "dark" else 0)
        field(app_sec, "Theme:", self.theme_combo)

        outer.addSpacing(4)

        # ---- finder ----
        fnd_sec = section("Fuzzy finder")
        outer.addLayout(fnd_sec)
        self.finder_combo = QComboBox()
        self.finder_combo.addItems(["All fields", "Groups only (cards)"])
        self.finder_combo.setCurrentIndex(1 if cfg.get("finder_mode") == "groups" else 0)
        field(fnd_sec, "Show:", self.finder_combo)

        outer.addSpacing(4)

        # ---- units ----
        u_sec = section("Default units")
        outer.addLayout(u_sec)
        self.length_combo = QComboBox()
        self.length_combo.addItems(list(VALID_LENGTH_UNITS))
        self.length_combo.setCurrentText(cfg.get("default_length_unit", "mm"))
        field(u_sec, "Length (all length fields):", self.length_combo)

        self.freq_combo = QComboBox()
        self.freq_combo.addItems(["Hz", "kHz", "MHz", "GHz"])
        self.freq_combo.setCurrentText(cfg.get("default_freq_unit", "MHz"))
        field(u_sec, "Frequency:", self.freq_combo)

        outer.addSpacing(4)

        # ---- Calc tab ----
        h_sec = section("Calc tab")
        outer.addLayout(h_sec)

        self.intellisense_cb = QCheckBox("Intellisense (autocomplete popup)")
        self.intellisense_cb.setChecked(bool(cfg.get("calc_intellisense", True)))
        field(h_sec, "Autocomplete:", self.intellisense_cb)

        self._hist_font = QFont(cfg.get("calc_history_font", "Consolas"),
                                int(cfg.get("calc_history_size", 10)))
        self._hist_font.setStyleHint(QFont.Monospace)
        self._hist_fg   = cfg.get("calc_history_fg", "")
        self._hist_bg   = cfg.get("calc_history_bg", "")

        self.hist_font_btn = QPushButton(self._format_font(self._hist_font))
        self.hist_font_btn.clicked.connect(self._pick_history_font)
        field(h_sec, "Font:", self.hist_font_btn)

        self.hist_fg_btn = QPushButton(self._hist_fg or "(theme default)")
        self.hist_fg_btn.clicked.connect(lambda: self._pick_history_color("fg"))
        self._tint_button(self.hist_fg_btn, self._hist_fg)
        field(h_sec, "Foreground:", self.hist_fg_btn)

        self.hist_bg_btn = QPushButton(self._hist_bg or "(theme default)")
        self.hist_bg_btn.clicked.connect(lambda: self._pick_history_color("bg"))
        self._tint_button(self.hist_bg_btn, self._hist_bg)
        field(h_sec, "Background:", self.hist_bg_btn)

        # Reset button — clears all three back to theme defaults.
        reset_btn = QPushButton("Reset to theme defaults")
        reset_btn.clicked.connect(self._reset_history_style)
        h_sec.addWidget(reset_btn)

        outer.addStretch(1)

        # ---- buttons ----
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton("OK"); ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

    # ---- helpers for the history-style row -------------------------------
    @staticmethod
    def _format_font(font):
        return f"{font.family()}, {font.pointSize()} pt"

    @staticmethod
    def _tint_button(btn, color_str):
        if color_str:
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color_str}; "
                f"padding: 3px 10px; }}")
        else:
            btn.setStyleSheet("")

    def _pick_history_font(self):
        font, ok = QFontDialog.getFont(self._hist_font, self, "Pick history font")
        if ok:
            self._hist_font = font
            self.hist_font_btn.setText(self._format_font(font))

    def _pick_history_color(self, which):
        current = self._hist_fg if which == "fg" else self._hist_bg
        col = QColorDialog.getColor(QColor(current) if current else QColor("white"),
                                    self, "Pick history " +
                                    ("foreground" if which == "fg" else "background"))
        if not col.isValid():
            return
        chosen = col.name()
        if which == "fg":
            self._hist_fg = chosen
            self.hist_fg_btn.setText(chosen)
            self._tint_button(self.hist_fg_btn, chosen)
        else:
            self._hist_bg = chosen
            self.hist_bg_btn.setText(chosen)
            self._tint_button(self.hist_bg_btn, chosen)

    def _reset_history_style(self):
        self._hist_font = QFont("Consolas", 10); self._hist_font.setStyleHint(QFont.Monospace)
        self._hist_fg = ""; self._hist_bg = ""
        self.hist_font_btn.setText(self._format_font(self._hist_font))
        self.hist_fg_btn.setText("(theme default)"); self._tint_button(self.hist_fg_btn, "")
        self.hist_bg_btn.setText("(theme default)"); self._tint_button(self.hist_bg_btn, "")

    def _accept(self):
        cfg = self.parent_main._cfg
        cfg["theme"]               = "dark" if self.theme_combo.currentIndex() == 1 else "light"
        cfg["finder_mode"]         = "groups" if self.finder_combo.currentIndex() == 1 else "fields"
        cfg["default_length_unit"] = self.length_combo.currentText()
        cfg["default_freq_unit"]   = self.freq_combo.currentText()
        cfg["calc_history_font"]   = self._hist_font.family()
        cfg["calc_history_size"]   = self._hist_font.pointSize()
        cfg["calc_history_fg"]     = self._hist_fg
        cfg["calc_history_bg"]     = self._hist_bg
        cfg["calc_intellisense"]   = self.intellisense_cb.isChecked()
        self.parent_main._apply_options()
        save_config(cfg)
        self.accept()


# ====================================================================
#  Compressed (frameless) title bar — menu, title and min/max/close in
#  one caption row.  Ported from the rdoc app (app/ui/titlebar.py):
#  Windows does the move / snap / resize / double-click-maximize through
#  WM_NCHITTEST; the 3D border is drawn in the contents margin.
# ====================================================================
WM_NCHITTEST, WM_NCCALCSIZE, WM_NCACTIVATE = 0x0084, 0x0083, 0x0086
GWL_STYLE, WS_THICKFRAME, WS_CAPTION = -16, 0x00040000, 0x00C00000
WM_SYSCOMMAND, SC_MAXIMIZE, SC_RESTORE = 0x0112, 0xF030, 0xF120
SWP_FRAMECHANGED = 0x0020 | 0x0001 | 0x0002 | 0x0004 | 0x0010
HTCAPTION, HTLEFT, HTRIGHT, HTTOP = 2, 10, 11, 12
HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 13, 14, 15, 16, 17
WIN_BORDER = 4
DFC_CAPTION, DFCS_PUSHED = 1, 0x200
DFCS_CAPTIONCLOSE, DFCS_CAPTIONMIN, DFCS_CAPTIONMAX, DFCS_CAPTIONRESTORE = 0, 1, 2, 3
SM_CXSIZE, SM_CYSIZE = 30, 31


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD), ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


def _frame_control(kind, pushed, w, h):
    """The caption button exactly as Windows draws it (DrawFrameControl),
    w x h device pixels, returned as a QImage."""
    from PyQt5.QtGui import QImage
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    hdr = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    dc = gdi32.CreateCompatibleDC(None)
    bmp = gdi32.CreateDIBSection(ctypes.c_void_p(dc), ctypes.byref(hdr), 0, ctypes.byref(bits), None, 0)
    if not dc or not bmp:
        raise OSError("DrawFrameControl: GDI allocation failed")
    try:
        old = gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(bmp))
        rect = ctypes.wintypes.RECT(0, 0, w, h)
        user32.DrawFrameControl(ctypes.c_void_p(dc), ctypes.byref(rect),
                                DFC_CAPTION, kind | (DFCS_PUSHED if pushed else 0))
        gdi32.GdiFlush()
        img = QImage(ctypes.string_at(bits, w * h * 4), w, h, w * 4,
                     QImage.Format_RGB32).convertToFormat(QImage.Format_ARGB32)
        gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(old))
    finally:
        gdi32.DeleteObject(ctypes.c_void_p(bmp))
        gdi32.DeleteDC(ctypes.c_void_p(dc))
    return img


class CaptionButton(QAbstractButton):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.setFocusPolicy(Qt.NoFocus)
        dpi = round(96 * self.devicePixelRatioF())
        user32 = ctypes.windll.user32
        w = user32.GetSystemMetricsForDpi(SM_CXSIZE, dpi) - 2
        h = user32.GetSystemMetricsForDpi(SM_CYSIZE, dpi) - 4
        self.setFixedSize(QSize(round(w / self.devicePixelRatioF()),
                                round(h / self.devicePixelRatioF())))

    def paintEvent(self, e):
        dpr = self.devicePixelRatioF()
        img = _frame_control(self.kind, self.isDown(),
                             round(self.width() * dpr), round(self.height() * dpr))
        img.setDevicePixelRatio(dpr)
        p = QPainter(self)
        p.drawImage(0, 0, img)
        p.end()


class TitleBar(QWidget):
    """Icon, menu bar, centred title and caption buttons in the caption row."""
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.icon = QLabel()
        self.icon.setPixmap(QApplication.windowIcon().pixmap(16, 16))
        self.menubar = QMenuBar()
        self.menubar.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        font = self.title.font(); font.setBold(True); self.title.setFont(font)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(2, 1, 2, 1); self.row.setSpacing(4)
        self.row.addWidget(self.icon, 0, Qt.AlignVCenter)
        self.row.addWidget(self.menubar, 0, Qt.AlignVCenter)
        self.row.addSpacing(4)
        self.row.addWidget(self.title, 0, Qt.AlignVCenter)
        self.row.addStretch(1)       # drag area; pushes caption buttons right
        self.buttons = {}
        caption = QHBoxLayout(); caption.setSpacing(0)
        for key, kind, fn in (("min", DFCS_CAPTIONMIN, win.showMinimized),
                              ("max", DFCS_CAPTIONMAX, self.toggle_max),
                              ("close", DFCS_CAPTIONCLOSE, win.close)):
            b = CaptionButton(kind); b.clicked.connect(fn)
            if key == "close":
                caption.addSpacing(2)
            caption.addWidget(b)
            self.buttons[key] = b
        self.row.addLayout(caption)
        for w in (self.icon, self.title):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        win.windowTitleChanged.connect(self.title.setText)
        self.title.setText(win.windowTitle())

    def toggle_max(self):
        self.win.zoom(not self.win.isMaximized())

    def sync_state(self):
        self.buttons["max"].kind = DFCS_CAPTIONRESTORE if self.win.isMaximized() else DFCS_CAPTIONMAX
        self.buttons["max"].update()


class FramelessMixin:
    """Frameless main window whose caption row is a TitleBar.  MainWindow
    overrides resizeEvent, so it calls self._sync_frame() there itself."""

    def init_frameless(self, bar):
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint
                            | Qt.WindowSystemMenuHint | Qt.WindowMinMaxButtonsHint)
        self.titlebar = bar
        self.setMenuWidget(bar)
        self._apply_native_frame()
        self._sync_frame()

    def _apply_native_frame(self):
        # Qt's frameless window is a bare WS_POPUP; Windows only sizes windows
        # carrying WS_THICKFRAME.  Add it back (plus WS_CAPTION so window
        # managers treat this as captioned) and report a zero frame in
        # WM_NCCALCSIZE so nothing extra is drawn.
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        hwnd = ctypes.c_void_p(int(self.winId()))
        user32.SetWindowLongPtrW(
            hwnd, GWL_STYLE,
            ctypes.c_ssize_t(user32.GetWindowLongPtrW(hwnd, GWL_STYLE) | WS_THICKFRAME | WS_CAPTION))
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FRAMECHANGED)

    def zoom(self, on):
        # Let Windows maximize / restore so it keeps a restore size and caption
        # double-click agrees with the max button.
        ctypes.windll.user32.SendMessageW(
            ctypes.c_void_p(int(self.winId())), WM_SYSCOMMAND,
            SC_MAXIMIZE if on else SC_RESTORE, 0)

    def _sync_frame(self):
        if self.isFullScreen():
            self.setContentsMargins(0, 0, 0, 0)
        elif self.isMaximized():
            g, a = self.geometry(), self.screen().availableGeometry()
            self.setContentsMargins(max(0, a.left() - g.left()), max(0, a.top() - g.top()),
                                    max(0, g.right() - a.right()), max(0, g.bottom() - a.bottom()))
        else:
            self.setContentsMargins(WIN_BORDER, WIN_BORDER, WIN_BORDER, WIN_BORDER)
        if getattr(self, "titlebar", None) is not None:
            self.titlebar.sync_state()
        self.update()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self._sync_frame()
        super().changeEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.contentsMargins().left() and not self.isMaximized():
            p = QPainter(self)
            qDrawWinPanel(p, self.rect(), self.palette(), False, self.palette().window())
            p.end()

    def hit_test(self, pos):
        if self.contentsMargins().left() and not self.isMaximized():
            w, h = self.width(), self.height()
            left, right = pos.x() < WIN_BORDER, pos.x() >= w - WIN_BORDER
            top, bottom = pos.y() < WIN_BORDER, pos.y() >= h - WIN_BORDER
            code = {
                (True, False, True, False): HTTOPLEFT,
                (False, True, True, False): HTTOPRIGHT,
                (True, False, False, True): HTBOTTOMLEFT,
                (False, True, False, True): HTBOTTOMRIGHT,
                (True, False, False, False): HTLEFT,
                (False, True, False, False): HTRIGHT,
                (False, False, True, False): HTTOP,
                (False, False, False, True): HTBOTTOM,
            }.get((left, right, top, bottom))
            if code is not None:
                return code
        bar = getattr(self, "titlebar", None)
        if bar is None:
            return None
        local = bar.mapFrom(self, pos)
        if bar.rect().contains(local) and bar.childAt(local) is None:
            return HTCAPTION
        return None

    def nativeEvent(self, event_type, message):
        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == WM_NCCALCSIZE and msg.wParam:
            return True, 0
        if msg.message == WM_NCACTIVATE:
            user32 = ctypes.windll.user32
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                              ctypes.c_size_t, ctypes.c_ssize_t]
            return True, user32.DefWindowProcW(msg.hWnd, msg.message, msg.wParam, -1)
        if msg.message == WM_NCHITTEST:
            code = self.hit_test(self.mapFromGlobal(QCursor.pos()))
            if code is not None:
                return True, code
        return False, 0


class MainWindow(FramelessMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("rcalc")

        self._cfg = load_config()
        # One-time rename: the SRF tab used to be called "Capacitors", so
        # bring any saved family / sub-family selection forward instead of
        # silently dropping it.
        if isinstance(self._cfg, dict):
            sp = self._cfg.get("special_tabs")
            if isinstance(sp, dict) and "Capacitors" in sp and "SRF" not in sp:
                sp["SRF"] = sp.pop("Capacitors")
        # Default window size — 640 x 760 lays out cleanly without
        # horizontal scrolling on any tab.  Existing JSON configs keep
        # their previously-saved size.
        DEFAULT_W, DEFAULT_H = 640, 760
        geo = self._cfg.get("window") if isinstance(self._cfg, dict) else None
        if isinstance(geo, dict):
            try:
                x = int(geo["x"]); y = int(geo["y"])
                w = max(1, int(geo["width"]))
                h = max(1, int(geo["height"]))
                self.setGeometry(x, y, w, h)
            except (KeyError, TypeError, ValueError):
                self.resize(DEFAULT_W, DEFAULT_H)
        else:
            self.resize(DEFAULT_W, DEFAULT_H)
        # Allow the user to shrink the window to any size.  Each tab is
        # scroll-wrapped, so its child widgets' min-size hints don't impose
        # a floor on the main window.
        self.setMinimumSize(0, 0)

        # ---- Apply persisted options BEFORE building cards ----
        # (TLineCard reads DEFAULT_LENGTH_UNIT in __init__; theme affects
        #  diagram colors painted at draw time.)
        global DEFAULT_LENGTH_UNIT, DEFAULT_FREQ_UNIT, CALC_HISTORY_STYLE
        global CALC_INTELLISENSE
        DEFAULT_LENGTH_UNIT = self._cfg.get("default_length_unit", "mm")
        if DEFAULT_LENGTH_UNIT not in VALID_LENGTH_UNITS:
            DEFAULT_LENGTH_UNIT = "mm"
        DEFAULT_FREQ_UNIT   = self._cfg.get("default_freq_unit",   "MHz")
        if DEFAULT_FREQ_UNIT not in ("Hz", "kHz", "MHz", "GHz"):
            DEFAULT_FREQ_UNIT = "MHz"
        CALC_INTELLISENSE = bool(self._cfg.get("calc_intellisense", True))
        # Calc-tab history list style — read once before any CalcTab is
        # constructed so it picks up the user's choices on first show.
        CALC_HISTORY_STYLE = {
            "font_family": self._cfg.get("calc_history_font") or None,
            "font_size":   self._cfg.get("calc_history_size") or None,
            "fg":          self._cfg.get("calc_history_fg")   or None,
            "bg":          self._cfg.get("calc_history_bg")   or None,
        }
        apply_theme(QApplication.instance(), self._cfg.get("theme", "light"))

        self.tabs = QTabWidget()
        self.tabs.setMovable(False)
        self.tabs.setDocumentMode(True)

        self.all_cards = []  # list of (tab_name, card, scroll)
        self.search_index = []

        # special tabs (custom QWidget classes) — keep refs so we can
        # save/restore their state on close
        self._special_tabs = {}      # tab_name -> widget instance

        # One-time migration: the standalone "Antenna Designer" tab is
        # now embedded as the header on the "Antenna" tab.  Move any
        # saved state across so users who launched the old build keep
        # their Type / Frequency / parameter inputs.
        sp = self._cfg.get("special_tabs")
        if isinstance(sp, dict) and "Antenna Designer" in sp \
                and "Antenna" not in sp:
            sp["Antenna"] = sp.pop("Antenna Designer")
        elif isinstance(sp, dict):
            sp.pop("Antenna Designer", None)

        # Build the tab tree.  Each top-level entry is either a flat tab
        # (special-widget class or list of cards) or a group whose body
        # is a list of (name, body, ...) tuples — in which case we put a
        # nested QTabWidget on the top-level tab and recurse.
        self._sub_tabwidgets = []   # all nested QTabWidgets, for state
        for entry in TAB_LAYOUT:
            self._add_tab_entry(self.tabs, entry)

        # central widget = the tabs themselves (no QStackedWidget anymore;
        # the finder is a separate floating window that snaps to the top edge)
        self.setCentralWidget(self.tabs)

        # finder window is created lazily on first open
        self._finder_window = None

        # ---- compressed title bar: menu + title + min/max/close in one row
        self.init_frameless(TitleBar(self))

        self._build_menu()

        # restore form state and last tab
        self._restore_form_state(self._cfg.get("fields") if isinstance(self._cfg, dict) else None)
        last_idx = self._cfg.get("tab_index", 0) if isinstance(self._cfg, dict) else 0
        if isinstance(last_idx, int) and 0 <= last_idx < self.tabs.count():
            self.tabs.setCurrentIndex(last_idx)

        # extra shortcuts that don't appear in any menu (avoid ambiguity
        # with menu QAction shortcuts: each chord must be bound exactly once)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.open_finder)
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_finder)
        # Numpad +/− cycle through top-level tabs (next / previous)
        QShortcut(QKeySequence(Qt.Key_Plus),  self, activated=self._next_tab)
        QShortcut(QKeySequence(Qt.Key_Minus), self, activated=self._prev_tab)
        # Ctrl+Shift+C → copy current tab's calculation as plain text
        QShortcut(QKeySequence("Ctrl+Shift+C"), self,
                  activated=self.copy_current_to_clipboard)
        # Ctrl+Shift+Enter / Return → toggle expand/collapse on every
        # CalcCard in the active tab (no-op for special tabs).
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self,
                  activated=self.toggle_all_collapsed_in_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Enter"), self,
                  activated=self.toggle_all_collapsed_in_tab)

        # Restore "Always on top" from the last session.  Done at the end of
        # __init__ so the menu QAction (built in _build_menu) is already
        # alive — set_always_on_top reaches into it to sync the check mark.
        if bool(self._cfg.get("always_on_top", False)):
            self.set_always_on_top(True)

    # ------------------------------------------------------------------
    # finder (separate floating window, magnetically attached above)
    # ------------------------------------------------------------------
    def _ensure_finder(self):
        if self._finder_window is None:
            self._finder_window = FinderWindow(self)
        # Sync the user-selected mode from config every time we open
        self._finder_window.mode = self._cfg.get("finder_mode", "fields")
        return self._finder_window

    def _on_finder_mode_toggled(self, checked):
        mode = "groups" if checked else "fields"
        self._cfg["finder_mode"] = mode
        if self._finder_window is not None:
            self._finder_window.mode = mode

    def open_finder(self):
        fw = self._ensure_finder()
        if fw.isVisible():
            fw.input.selectAll(); fw.input.setFocus()
            return
        fw.show_above(self.search_index)

    def toggle_finder(self):
        fw = self._ensure_finder()
        if fw.isVisible():
            fw._cancel()
        else:
            fw.show_above(self.search_index)

    def close_finder_if_open(self):
        if self._finder_window and self._finder_window.isVisible():
            self._finder_window._cancel()

    # ------------------------------------------------------------------
    #  Nested-tab navigation helpers (after the group/sub-tab refactor,
    #  finder + clear + copy paths can't just look at the top-level
    #  QTabWidget — they have to drill into the active group, and
    #  activate both group + sub when jumping to a leaf by name).
    # ------------------------------------------------------------------
    def _current_leaf(self):
        """Return `(leaf_name, leaf_widget)` for whichever tab the user
        is actually looking at — recursing past any QTabWidget group
        into the currently-selected sub-tab.  Returns (None, None) when
        there is no active tab."""
        idx = self.tabs.currentIndex()
        if idx < 0:
            return None, None
        name = self.tabs.tabText(idx)
        widget = self.tabs.widget(idx)
        while isinstance(widget, QTabWidget):
            sub_idx = widget.currentIndex()
            if sub_idx < 0:
                break
            name = widget.tabText(sub_idx)
            widget = widget.widget(sub_idx)
        return name, widget

    def _activate_leaf_tab(self, leaf_name):
        """Walk the (top, sub) tab tree and switch to the tab whose
        text equals `leaf_name`.  Top-level matches win over sub-tab
        matches of the same name (e.g. top-level "Power" beats
        RF → "Power").  Activates the parent group when the leaf is
        nested.  Returns True on success."""
        if not leaf_name:
            return False
        for ti in range(self.tabs.count()):
            if self.tabs.tabText(ti) == leaf_name:
                self.tabs.setCurrentIndex(ti)
                return True
        for ti in range(self.tabs.count()):
            sub = self.tabs.widget(ti)
            if isinstance(sub, QTabWidget):
                for sj in range(sub.count()):
                    if sub.tabText(sj) == leaf_name:
                        self.tabs.setCurrentIndex(ti)
                        sub.setCurrentIndex(sj)
                        return True
        return False

    def _jump_to_card_only(self, card):
        """Switch to the tab containing `card` and scroll it into view.
        Used by the finder for live-preview navigation; does NOT change focus."""
        if card is None:
            return
        for i, (name, c, scroll) in enumerate(self.all_cards):
            if c is card:
                self._activate_leaf_tab(name)
                QTimer.singleShot(0,
                    lambda s=scroll, c=card: s.ensureWidgetVisible(c, 30, 30))
                return
        # Special-widget page (Calc, Resistor, Smith Chart, Antenna
        # designer header …) — the "card" handed to us by the finder
        # is the page widget itself.  Look it up by name in
        # self._special_tabs and activate that leaf tab.
        for tab_name, page in self._special_tabs.items():
            if page is card:
                self._activate_leaf_tab(tab_name)
                return
        idx = self.tabs.indexOf(card)
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)

    def moveEvent(self, ev):
        super().moveEvent(ev)
        if self._finder_window is not None and self._finder_window.isVisible():
            self._finder_window._reposition()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.isMaximized():
            self._sync_frame()   # maximized geometry arrives after the state change
        if self._finder_window is not None and self._finder_window.isVisible():
            self._finder_window._reposition()

    # ------------------------------------------------------------------
    # menus, view options
    # ------------------------------------------------------------------
    def _build_menu(self):
        bar = self.titlebar.menubar

        m = bar.addMenu("&File")
        a = QAction("Save preset…", self); a.setShortcut("Ctrl+S")
        a.triggered.connect(self.save_preset); m.addAction(a)
        a = QAction("Load preset…", self); a.setShortcut("Ctrl+O")
        a.triggered.connect(self.load_preset); m.addAction(a)
        a = QAction("Delete preset…", self)
        a.triggered.connect(self.delete_preset); m.addAction(a)
        m.addSeparator()
        # Ctrl+Shift+Backspace, not Ctrl+Backspace, so QLineEdit's
        # native word-delete (e.g. inside the Calc tab's input) keeps
        # working without an "Ambiguous shortcut" conflict.
        a = QAction("Reset current tab", self); a.setShortcut("Ctrl+Shift+Backspace")
        a.triggered.connect(self.clear_current_tab); m.addAction(a)
        a = QAction("Reset all tabs", self)
        a.triggered.connect(self.reset_all); m.addAction(a)
        m.addSeparator()
        a = QAction("E&xit", self); a.setShortcut("Ctrl+Q")
        a.triggered.connect(self.close); m.addAction(a)

        m = bar.addMenu("&View")
        a = QAction("Find field…", self)
        a.setShortcut("Ctrl+Space")
        a.setShortcutContext(Qt.ApplicationShortcut)
        a.triggered.connect(self.toggle_finder); m.addAction(a)
        m.addSeparator()
        a = QAction("Always on top", self, checkable=True)
        a.setShortcut("Ctrl+T")
        a.setChecked(bool(self._cfg.get("always_on_top", False)))
        a.triggered.connect(lambda checked: self.set_always_on_top(checked))
        m.addAction(a)
        self._always_on_top_action = a

        m = bar.addMenu("&Options")
        a = QAction("Options…", self)
        a.triggered.connect(self.open_options)
        m.addAction(a)

        m = bar.addMenu("&Help")
        a = QAction("Keyboard shortcuts", self); a.setShortcut("F1")
        a.triggered.connect(self.show_help); m.addAction(a)
        a = QAction("About", self)
        a.triggered.connect(self.show_about); m.addAction(a)

    def set_always_on_top(self, on):
        on = bool(on)
        flags = self.windowFlags()
        if on:
            new_flags = flags | Qt.WindowStaysOnTopHint
        else:
            new_flags = flags & ~Qt.WindowStaysOnTopHint
        if new_flags != flags:
            # Changing window flags re-creates the native window, so the
            # widget hides itself; re-show to keep it visible.  The new HWND
            # loses the WS_THICKFRAME tweak, so re-apply the frameless frame.
            self.setWindowFlags(new_flags)
            self.show()
            self._apply_native_frame()
            self._sync_frame()
        if hasattr(self, "_always_on_top_action"):
            self._always_on_top_action.setChecked(on)
        self._cfg["always_on_top"] = on

    def toggle_always_on_top(self):
        self.set_always_on_top(
            not bool(self.windowFlags() & Qt.WindowStaysOnTopHint))

    # ------------------------------------------------------------------
    #  Tab tree construction (handles flat tabs + nested groups)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_group_body(body):
        """A TAB_LAYOUT 'body' is a group when it's a list whose first
        element is a tuple — i.e. `[(subtab_name, sub_body, ...), …]`.
        Card lists hold class objects, not tuples, so this disambiguates
        without an explicit type marker."""
        return (isinstance(body, list) and len(body) > 0
                and isinstance(body[0], tuple))

    def _add_tab_entry(self, parent_tabwidget, entry):
        """Append one TAB_LAYOUT entry to `parent_tabwidget`.  Recurses
        for group entries so arbitrary nesting works in principle (we
        only use two levels)."""
        name, body = entry[0], entry[1]

        if self._is_group_body(body):
            inner = QTabWidget()
            inner.setDocumentMode(True)
            inner.setMovable(False)
            for sub in body:
                self._add_tab_entry(inner, sub)
            parent_tabwidget.addTab(inner, name)
            self._sub_tabwidgets.append(inner)
            return

        if isinstance(body, type) and issubclass(body, QWidget):
            page = body()
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setFrameShape(QFrame.NoFrame)
            # Match CalcCard-based pages: never show the outer page's
            # horizontal scrollbar.  Inner widgets (e.g. wide tables)
            # have their own scrollbars when they need to clip.
            wrapper.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            wrapper.setWidget(page)
            parent_tabwidget.addTab(wrapper, name)
            self._special_tabs[name] = page
            tab_cfg = (self._cfg.get("special_tabs") or {}).get(name)
            if tab_cfg is not None and hasattr(page, "set_state"):
                try: page.set_state(tab_cfg)
                except Exception: pass
            if hasattr(page, "search_entries"):
                try:
                    for sentry in page.search_entries(name):
                        self.search_index.append(sentry)
                except Exception:
                    pass
            return

        cols = entry[2] if len(entry) > 2 else None
        header_factory = entry[3] if len(entry) > 3 else None
        page, scroll, cards, header = build_tab(
            body, cols=cols, header_factory=header_factory)
        parent_tabwidget.addTab(page, name)
        for c in cards:
            self.all_cards.append((name, c, scroll))
            for sentry in c.search_entries(name):
                self.search_index.append(sentry)
        if header is not None:
            self._special_tabs[name] = header
            tab_cfg = (self._cfg.get("special_tabs") or {}).get(name)
            if tab_cfg is not None and hasattr(header, "set_state"):
                try: header.set_state(tab_cfg)
                except Exception: pass
            if hasattr(header, "search_entries"):
                try:
                    for sentry in header.search_entries(name):
                        self.search_index.append(sentry)
                except Exception:
                    pass

    def _set_tab(self, idx):
        if self._finder_window and self._finder_window.isVisible():
            self._finder_window._cancel()
        self.tabs.setCurrentIndex(idx)

    def _next_tab(self):
        if self._finder_window and self._finder_window.isVisible():
            return                                           # don't intercept finder
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % n)

    def _prev_tab(self):
        if self._finder_window and self._finder_window.isVisible():
            return
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % n)

    # ------------------------------------------------------------------
    # Ctrl+Shift+Enter → expand / collapse every CalcCard on the
    # active tab.  If any card is currently expanded, collapse them all;
    # otherwise expand them all.  No-op for special-widget tabs.
    # ------------------------------------------------------------------
    def toggle_all_collapsed_in_tab(self):
        tab_name, _ = self._current_leaf()
        if not tab_name:
            return
        cards = [c for n, c, _ in self.all_cards if n == tab_name]
        if not cards:
            return
        # If at least one is expanded, collapse all; else expand all.
        any_expanded = any(not c._collapsed for c in cards)
        target = True if any_expanded else False
        for c in cards:
            c.set_collapsed(target)

    # ------------------------------------------------------------------
    # Ctrl+Shift+C → plain-text dump of the active tab
    # ------------------------------------------------------------------
    def copy_current_to_clipboard(self):
        tab_name, widget = self._current_leaf()
        if tab_name is None:
            return
        # Special tabs are scroll-wrapped; unwrap one level.
        if isinstance(widget, QScrollArea):
            widget = widget.widget()
        # CalcTab opts out of the "=== Tab ===" wrapper so Ctrl+Shift+C
        # produces a bare "formula  =  result" line ready to paste.
        if isinstance(widget, CalcTab):
            text = ""
            try: text = widget.to_clipboard_text() or ""
            except Exception: pass
            if not text:
                return
            QApplication.clipboard().setText(text)
            return
        # 0) Rich-mime path — a special tab can bundle text + image (and
        #    optionally other formats) by exposing `to_clipboard_mime`.
        #    The SRF tab uses this so a single Ctrl+Shift+C drops the
        #    plot PNG into PowerPoint and the trace summary into plain
        #    text editors at the same time.
        if hasattr(widget, "to_clipboard_mime"):
            try:
                mime = widget.to_clipboard_mime()
            except Exception:
                mime = None
            if mime is not None:
                QApplication.clipboard().setMimeData(mime)
                return

        lines = [f"=== {tab_name} ===", ""]
        # 1) Special tab provides its own formatter?
        if hasattr(widget, "to_clipboard_text"):
            try:
                text = widget.to_clipboard_text()
                if text:
                    lines.append(text)
            except Exception:
                pass
        else:
            # 2) CalcCard tab: gather every card whose tab name matches.
            for name, card, _scroll in self.all_cards:
                if name != tab_name:
                    continue
                lines.append(card.title())
                lines.append("-" * len(card.title()))
                for f in card.fields.values():
                    val = f.edit.text().strip()
                    if val == "":
                        continue
                    unit = f" {f.unit}" if f.unit else ""
                    lines.append(f"  {f.label:<28s} {val}{unit}")
                lines.append("")
        text = "\n".join(lines).rstrip() + "\n"
        QApplication.clipboard().setText(text)

    def open_options(self):
        OptionsDialog(self).exec_()

    def _apply_options(self):
        """Push every option from self._cfg out to the live UI.  Called
        on startup AND from OptionsDialog after the user clicks OK."""
        global DEFAULT_LENGTH_UNIT
        cfg = self._cfg
        # 1) Theme
        apply_theme(QApplication.instance(), cfg.get("theme", "light"))
        for _, c, _ in self.all_cards:
            c.update()      # repaint with new diagram colors
        # Smith chart redraw if it exists (special tabs are scroll-wrapped,
        # so unwrap one level before the type check).
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, QScrollArea):
                w = w.widget()
            if isinstance(w, SmithChartTab) and HAS_SMITH:
                w.canvas._apply_theme()
                w.canvas._redraw()
        # 2) Finder mode
        if self._finder_window is not None:
            self._finder_window.mode = cfg.get("finder_mode", "fields")
        # 3) Default length unit — applies to every length field across
        #    every card.  We hot-reload it onto the running cards by calling
        #    apply_global_length_unit() on each one that supports it.
        new_unit = cfg.get("default_length_unit", "mm")
        if new_unit in VALID_LENGTH_UNITS:
            DEFAULT_LENGTH_UNIT = new_unit
        for _, card, _ in self.all_cards:
            if hasattr(card, "apply_global_length_unit"):
                try:
                    card.apply_global_length_unit()
                except Exception:
                    pass
        # 4) Default frequency unit (read by cards that opt into it on build)
        global DEFAULT_FREQ_UNIT
        new_freq = cfg.get("default_freq_unit", "MHz")
        if new_freq in ("Hz", "kHz", "MHz", "GHz"):
            DEFAULT_FREQ_UNIT = new_freq
        # 5) Calc-tab history list styling — mirror into the global so a
        # newly-built CalcTab can pick it up, and push to the live one if
        # the user has it open.
        global CALC_HISTORY_STYLE
        CALC_HISTORY_STYLE = {
            "font_family": cfg.get("calc_history_font") or None,
            "font_size":   cfg.get("calc_history_size") or None,
            "fg":          cfg.get("calc_history_fg")   or None,
            "bg":          cfg.get("calc_history_bg")   or None,
        }
        # 6) Calc-tab intellisense on/off
        global CALC_INTELLISENSE
        CALC_INTELLISENSE = bool(cfg.get("calc_intellisense", True))
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, QScrollArea):
                w = w.widget()
            if isinstance(w, CalcTab):
                w.apply_history_style(
                    CALC_HISTORY_STYLE["font_family"],
                    CALC_HISTORY_STYLE["font_size"],
                    CALC_HISTORY_STYLE["fg"],
                    CALC_HISTORY_STYLE["bg"],
                )
                w.set_intellisense_enabled(CALC_INTELLISENSE)

    def show_help(self):
        QMessageBox.information(self, "Keyboard shortcuts",
            "<style>td{padding:2px 12px 2px 0;}</style>"
            "<table>"
            "<tr><td><b>Ctrl+Space</b></td><td>Inline fuzzy find — jump to any field</td></tr>"
            "<tr><td><b>Esc</b></td><td>Close finder</td></tr>"
            "<tr><td><b>+ / −</b></td><td>Next / previous top-level tab</td></tr>"
            "<tr><td><b>Ctrl+S</b></td><td>Save current state as named preset</td></tr>"
            "<tr><td><b>Ctrl+O</b></td><td>Load a preset</td></tr>"
            "<tr><td><b>Ctrl+Shift+Backspace</b></td><td>Reset current tab "
            "(Ctrl+Backspace stays free for word-delete inside text fields)</td></tr>"
            "<tr><td><b>Ctrl+T</b></td><td>Toggle always-on-top</td></tr>"
            "<tr><td><b>F1</b></td><td>This help</td></tr>"
            "</table>"
            "<br><b>Number entry suffixes:</b> 2k = 2000, 5M = 5e6, 3.3G, 100m = 0.1, 50u, 10n, 2p"
            "<br><br>Window size, position, tab, every field value, and every selector "
            "(materials, units, solve-for, cable type) persist between sessions.")

    def show_about(self):
        QMessageBox.about(self, "rcalc",
            "<b>rcalc</b><br>"
            "Comprehensive RF calculation toolkit.<br><br>"
            "Type a value in any input field — every linked output recomputes live."
            "<br>Press <b>Ctrl+Space</b> to fuzzy-find any field by name.")

    # ------------------------------------------------------------------
    # presets (named workspace snapshots)
    # ------------------------------------------------------------------
    def save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        presets = self._cfg.setdefault("presets", {})
        presets[name] = self._gather_form_state()
        save_config(self._cfg)

    def load_preset(self):
        presets = self._cfg.get("presets", {}) if isinstance(self._cfg, dict) else {}
        if not presets:
            QMessageBox.information(self, "No presets", "No saved presets yet.")
            return
        names = sorted(presets.keys())
        name, ok = QInputDialog.getItem(self, "Load preset", "Choose a preset:",
                                        names, 0, False)
        if not ok:
            return
        self._restore_form_state(presets[name])

    def delete_preset(self):
        presets = self._cfg.get("presets", {}) if isinstance(self._cfg, dict) else {}
        if not presets:
            QMessageBox.information(self, "No presets", "No saved presets yet.")
            return
        names = sorted(presets.keys())
        name, ok = QInputDialog.getItem(self, "Delete preset", "Delete which preset?",
                                        names, 0, False)
        if not ok:
            return
        presets.pop(name, None)
        save_config(self._cfg)

    def reset_all(self):
        if QMessageBox.question(self, "Reset all",
                "Clear every field across every tab?") != QMessageBox.Yes:
            return
        for _, card, _ in self.all_cards:
            for f in card.fields.values():
                if f.edit is None: continue
                f.edit.blockSignals(True)
                f.edit.clear()
                f.edit.blockSignals(False)
            if isinstance(card, ThermalNoiseCard):
                card.fields["t_k"].edit.setText("290")
                card.fields["nf_db"].edit.setText("0")
            if isinstance(card, SkinDepthCard):
                card.fields["rho"].edit.setText("1.68e-8")
            card._refresh_figure()

    def _gather_form_state(self):
        """Snapshot every QLineEdit text plus card-level selectors,
        keyed by tab → card class → field. Selectors live under the
        reserved key '__card__'."""
        state = {}
        for tab_name, card, _ in self.all_cards:
            cls = type(card).__name__
            tab = state.setdefault(tab_name, {})
            card_state = {}
            for fname, f in card.fields.items():
                if f.edit is not None:
                    card_state[fname] = f.edit.text()
            meta = card.get_card_state()
            if meta:
                card_state["__card__"] = meta
            tab[cls] = card_state
        return state

    def _restore_form_state(self, state):
        """Reverse of _gather_form_state. Sets each field's text without
        triggering the per-edit signal handler, then runs each card once
        so derived outputs are regenerated. Card-level selectors are
        restored before fields so unit toggles don't double-convert."""
        if not isinstance(state, dict):
            return
        for tab_name, card, _ in self.all_cards:
            cls = type(card).__name__
            card_state = state.get(tab_name, {}).get(cls)
            if not isinstance(card_state, dict):
                continue
            meta = card_state.get("__card__")
            if meta:
                try: card.set_card_state(meta)
                except Exception: pass
            for fname, text in card_state.items():
                if fname == "__card__":
                    continue
                f = card.fields.get(fname)
                if f is None or f.edit is None or not isinstance(text, str):
                    continue
                f.edit.blockSignals(True)
                f.edit.setText(text)
                f.edit.blockSignals(False)
            try:
                card.recompute_from_inputs()
            except Exception:
                pass

    def closeEvent(self, ev):
        g = self.geometry()
        if not isinstance(self._cfg, dict):
            self._cfg = {}
        self._cfg["window"] = {
            "x": int(g.x()), "y": int(g.y()),
            "width": int(g.width()), "height": int(g.height()),
        }
        self._cfg["tab_index"] = int(self.tabs.currentIndex())
        self._cfg["fields"] = self._gather_form_state()
        # Special-tab state (Resistor, etc.)
        special = {}
        for tname, tw in self._special_tabs.items():
            if hasattr(tw, "get_state"):
                try:
                    st = tw.get_state()
                    if st is not None:
                        special[tname] = st
                except Exception:
                    pass
        if special:
            self._cfg["special_tabs"] = special
        save_config(self._cfg)
        super().closeEvent(ev)

    def clear_current_tab(self):
        tab_name, _ = self._current_leaf()
        if tab_name is None:
            return
        # Special-widget tab provides its own clear?
        sp = self._special_tabs.get(tab_name)
        if sp is not None and hasattr(sp, "clear_all"):
            try: sp.clear_all()
            except Exception: pass
            return
        for name, card, _ in self.all_cards:
            if name == tab_name:
                for f in card.fields.values():
                    f.edit.blockSignals(True)
                    f.edit.clear()
                    f.edit.blockSignals(False)
                # restore defaults that some cards seed
                if isinstance(card, ThermalNoiseCard):
                    card.fields["t_k"].edit.setText("290")
                    card.fields["nf_db"].edit.setText("0")
                if isinstance(card, SkinDepthCard):
                    card.fields["rho"].edit.setText("1.68e-8")
                card._refresh_figure()

    def _jump_to_field(self, edit, card):
        # Find which tab contains this card and activate it — including
        # the parent group when the leaf is nested.
        for i, (name, c, scroll) in enumerate(self.all_cards):
            if c is card:
                self._activate_leaf_tab(name)
                if self._finder_window and self._finder_window.isVisible():
                    self._finder_window.hide()
                QTimer.singleShot(0,  lambda s=scroll, c=card: s.ensureWidgetVisible(c, 20, 20))
                QTimer.singleShot(
                    10,
                    lambda e=edit: (
                        e.setFocus(),
                        e.selectAll() if hasattr(e, "selectAll") else None,
                    ),
                )
                return
        # Card wasn't in the all_cards index — could be a special-tab
        # field (e.g., LaTeX source edit, Periodic filter).  Activate by
        # the special-tab name and focus the supplied edit.
        for tab_name, page in self._special_tabs.items():
            if page is card:
                self._activate_leaf_tab(tab_name)
                if self._finder_window and self._finder_window.isVisible():
                    self._finder_window.hide()
                QTimer.singleShot(
                    10,
                    lambda e=edit: (
                        e.setFocus(),
                        e.selectAll() if hasattr(e, "selectAll") else None,
                    ),
                )
                return


def main():
    # Give the process its own AppUserModelID so the Windows taskbar groups
    # it under the app's icon instead of pythonw.exe's generic Python icon.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rcalc.Rcalc")
        except Exception:
            pass
    app = QApplication(sys.argv)
    # <ICON_INJECT_START>
    # Force Qt to be fully ready before any other operations
    app.processEvents()
    
    # Icon setup after processing events
    try:
        import os
        from PyQt5.QtGui import QIcon
        here = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(here, "Rcalc.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(here, "rcalc.png")
        if os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            app.setWindowIcon(app_icon)
    except Exception as e:
        print(f"Icon setup failed: {e}")
    # <ICON_INJECT_END>
    if "Windows" in QStyleFactory.keys():
        app.setStyle("Windows")
    app.setFont(QFont("Tahoma", 8))
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
