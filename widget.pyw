"""Widget de uso do Claude Code na área de notificação da barra de tarefas.

Lê o usage.json gravado pelo statusline.py e mostra:
- na bandeja: dois ícones de medidor de 240° (sessão 5h e semana 7d), coloridos por faixa;
- na barra de tarefas: um mini-cartão com os dois medidores, encostado na bandeja;
- no tooltip: 5h, 7d e contexto com os horários de reset;
- no painel (clique esquerdo): medidores, contagem regressiva, contexto, custo e gráfico.

Rodar com: run-python.cmd pythonw widget.pyw  (ou pelo iniciar-widget.vbs)
"""
import ctypes
import json
import math
import os
import sys
import time
import winreg
from ctypes import wintypes
from datetime import datetime

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import (QAction, QApplication, QHBoxLayout, QLabel, QMenu,
                             QSystemTrayIcon, QVBoxLayout, QWidget)

BASE = os.path.dirname(os.path.abspath(__file__))
USAGE = os.path.join(BASE, "usage.json")
HISTORY = os.path.join(BASE, "history.jsonl")
LAUNCHER = os.path.join(BASE, "iniciar-widget.vbs")
CONFIG = os.path.join(BASE, "widget.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "ClaudeUsageWidget"
INSTANCE = "claude-usage-widget"
POLL_MS = 5000
STALE_S = 15 * 60  # sem atualização há mais que isso: dados "antigos"

GREEN, AMBER, RED, GRAY = "#3fb950", "#d29922", "#f85149", "#6e7681"
BG, FG, MUTED, TRACK = "#1f2328", "#e6edf3", "#8d96a0", "#30363d"
DIAS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def level_color(pct):
    if pct is None:
        return GRAY
    return GREEN if pct < 50 else AMBER if pct < 80 else RED


def load_usage():
    try:
        with open(USAGE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load_history(since):
    points = []
    try:
        with open(HISTORY, encoding="utf-8") as f:
            for line in f:
                try:
                    s = json.loads(line)
                except ValueError:
                    continue
                if s.get("updated_at", 0) >= since and s.get("five_hour_pct") is not None:
                    points.append((s["updated_at"], s["five_hour_pct"]))
    except OSError:
        pass
    return points


def effective_pct(pct, resets_at, now):
    """Depois do reset a janela zerou, mesmo sem nova leitura."""
    if pct is not None and resets_at and now >= resets_at:
        return 0
    return pct


def fmt_countdown(resets_at, now, sep=" "):
    if not resets_at:
        return ""
    left = int(resets_at - now)
    if left <= 0:
        return "resetado"
    h, m = divmod(left // 60, 60)
    d, h = divmod(h, 24)
    when = datetime.fromtimestamp(resets_at)
    if d:
        return f"reseta {DIAS[when.weekday()]} {when:%H:%M}{sep}(em {d}d {h}h)"
    left_txt = f"{h}h {m:02d}min" if h else f"{m}min"
    return f"reseta {when:%H:%M}{sep}(em {left_txt})"


def fmt_age(ts, now):
    age = int(now - ts)
    if age < 60:
        return "agora"
    if age < 3600:
        return f"há {age // 60} min"
    return f"há {age // 3600} h {age % 3600 // 60:02d} min"


def paint_gauge240(p, x, y, r, thick, pct, number_px, label=None, label_px=0, stale=False,
                   percent_sign=True, track=TRACK, label_color=MUTED, number_lift=0.15,
                   max_number=None):
    """Medidor de 240° (aberto embaixo), com o número no centro e o rótulo na abertura.

    Usado pelo mini-cartão da barra de tarefas, pelo painel e pelos ícones da bandeja. Ocupa 2r + thick de largura; na altura,
    r + thick/2 acima do centro e r/2 + thick/2 abaixo (o rótulo pode passar um pouco disso).
    """
    p.setRenderHint(QPainter.Antialiasing)
    cx, cy = x + r + thick / 2, y + r + thick / 2
    arc = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    pen = QPen(QColor(track), thick, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawArc(arc, 210 * 16, -240 * 16)
    if pct:
        pen.setColor(QColor(GRAY if stale else level_color(pct)))
        p.setPen(pen)
        p.drawArc(arc, 210 * 16, -int(240 * 16 * min(pct, 100) / 100))

    font = QFont("Segoe UI")
    font.setBold(True)
    if pct is None:
        text = "—"
    else:
        n = round(pct) if max_number is None else min(round(pct), max_number)
        text = f"{n}%" if percent_sign else str(n)
    # encolhe o número até caber no vão interno do arco (ex.: "100%")
    inner = (2 * r - thick) * 0.8
    while number_px > 6:
        font.setPixelSize(int(number_px))
        if QFontMetrics(font).horizontalAdvance(text) <= inner:
            break
        number_px -= 0.5
    p.setFont(font)
    p.setPen(QColor(FG))
    p.drawText(QRectF(cx - r, cy - number_lift * r - number_px * 0.7, 2 * r, number_px * 1.4),
               Qt.AlignCenter, text)
    if not label:
        return
    font.setBold(False)
    font.setPixelSize(int(label_px))
    p.setFont(font)
    p.setPen(QColor(label_color))
    p.drawText(QRectF(cx - r, cy + 0.5 * r - label_px * 0.7, 2 * r, label_px * 1.4),
               Qt.AlignCenter, label)


def make_gauge_icon(pct, stale):
    """Ícone da bandeja: mini medidor de 240° com o número (sem %, para caber em 16 px)."""
    size, thick = 64, 10
    r = (size - thick) / 2
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    # sem rótulo: o número desce um pouco, para dentro da abertura de baixo; centraliza na altura
    top = (size - (1.5 * r + thick)) / 2
    paint_gauge240(p, 0, top, r, thick, pct, 34, stale=stale, percent_sign=False, track="#5a636e",
                   number_lift=-0.1, max_number=99)
    p.end()
    return QIcon(pm)


class Bar(QWidget):
    """Barra de progresso fina, desenhada à mão para ficar igual em qualquer tema."""

    def __init__(self):
        super().__init__()
        self.pct = None
        self.setFixedHeight(8)

    def set_pct(self, pct):
        self.pct = pct
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(r, 4, 4)
        if self.pct:
            w = max(8, int(r.width() * min(self.pct, 100) / 100))
            p.setBrush(QColor(level_color(self.pct)))
            p.drawRoundedRect(QRect(r.x(), r.y(), w, r.height()), 4, 4)


class Gauge(QWidget):
    """Medidor de 240°: trilho cinza, arco colorido proporcional ao %, número no centro."""

    THICK = 12
    R = 56  # largura = 2R + THICK

    def __init__(self, label):
        super().__init__()
        self.label = label
        self.pct = None
        self.setFixedSize(2 * self.R + self.THICK, 100)

    def set_pct(self, pct):
        self.pct = pct
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        paint_gauge240(p, 0, 0, self.R, self.THICK, self.pct, 24, self.label, 12)


class Spark(QWidget):
    """Gráfico do % de 5h nas últimas 5 horas."""

    WINDOW = 5 * 3600

    def __init__(self):
        super().__init__()
        self.points = []
        self.setFixedHeight(54)

    def set_points(self, points):
        self.points = points
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 4, -1, -1)
        p.setPen(QPen(QColor(TRACK), 1))
        p.drawLine(r.bottomLeft(), r.bottomRight())
        if len(self.points) < 2 or self.points[-1][0] - self.points[0][0] < 15 * 60:
            p.setPen(QColor(MUTED))
            p.drawText(r, Qt.AlignCenter, "histórico ainda curto")
            return
        end = time.time()
        start = end - self.WINDOW
        top = max(100, max(v for _, v in self.points))

        def xy(t, v):
            x = r.left() + (t - start) / self.WINDOW * r.width()
            y = r.bottom() - v / top * r.height()
            return x, y

        path = QPainterPath()
        for i, (t, v) in enumerate(self.points):
            x, y = xy(t, v)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.setPen(QPen(QColor(level_color(self.points[-1][1])), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class Panel(QWidget):
    def __init__(self):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(300)
        self.setStyleSheet(f"QLabel {{ color: {FG}; font-family: 'Segoe UI'; font-size: 10pt; }}"
                           f"QLabel[muted='true'] {{ color: {MUTED}; font-size: 9pt; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)

        self.title = QLabel()
        self.title.setStyleSheet("font-size: 11pt; font-weight: 600;")
        lay.addWidget(self.title)
        lay.addSpacing(8)

        self.gauges = {}
        gauges_row = QHBoxLayout()
        gauges_row.setSpacing(8)
        for key, label in (("five", "Sessão · 5h"), ("seven", "Semana · 7d")):
            col = QVBoxLayout()
            col.setSpacing(2)
            gauge = Gauge(label)
            sub = self._muted()
            sub.setAlignment(Qt.AlignHCenter)
            col.addWidget(gauge, 0, Qt.AlignHCenter)
            col.addWidget(sub)
            gauges_row.addLayout(col)
            self.gauges[key] = (gauge, sub)
        lay.addLayout(gauges_row)
        lay.addSpacing(10)

        self.ctx_head = QLabel()
        self.ctx_bar = Bar()
        self.ctx_sub = self._muted()
        lay.addWidget(self.ctx_head)
        lay.addWidget(self.ctx_bar)
        lay.addWidget(self.ctx_sub)
        lay.addSpacing(8)

        lay.addWidget(self._muted("Uso de 5h nas últimas 5 horas"))
        self.spark = Spark()
        lay.addWidget(self.spark)
        lay.addSpacing(4)
        self.footer = self._muted()
        lay.addWidget(self.footer)

    @staticmethod
    def _muted(text=""):
        lbl = QLabel(text)
        lbl.setProperty("muted", True)
        return lbl

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(TRACK), 1))
        p.setBrush(QColor(BG))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

    def refresh(self, u, now):
        self.title.setText(f"Claude · {u.get('model') or '—'}" if u else "Claude · sem dados")
        u = u or {}
        for key, prefix in (("five", "five_hour"), ("seven", "seven_day")):
            gauge, sub = self.gauges[key]
            resets_at = u.get(f"{prefix}_resets_at")
            gauge.set_pct(effective_pct(u.get(f"{prefix}_pct"), resets_at, now))
            sub.setText(fmt_countdown(resets_at, now, sep="\n"))
        ctx = u.get("context_pct")
        self.ctx_head.setText(f"Contexto da conversa  <b>{'—' if ctx is None else f'{round(ctx)}%'}</b>")
        self.ctx_bar.set_pct(ctx)
        self.ctx_sub.setText(os.path.basename(u.get("cwd") or ""))
        self.spark.set_points(load_history(now - Spark.WINDOW))
        parts = []
        if u.get("cost_usd") is not None:
            parts.append(f"sessão US$ {u['cost_usd']:.2f}")
        if u.get("updated_at"):
            parts.append(f"atualizado {fmt_age(u['updated_at'], now)}")
        self.footer.setText(" · ".join(parts))

    def show_near(self, anchor):
        self.adjustSize()
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(anchor.x() - self.width() // 2, area.left() + 8), area.right() - self.width() - 8)
        # barra embaixo (padrão): abre acima; barra no topo: abre abaixo
        y = area.bottom() - self.height() - 8 if anchor.y() > area.center().y() else area.top() + 8
        self.move(x, y)
        self.show()
        self.activateWindow()


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_startup(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'wscript.exe "{LAUNCHER}"')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# --- Win32: localizar a barra de tarefas e a bandeja -------------------------
user32 = ctypes.windll.user32
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
GWLP_HWNDPARENT = -8


def win_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)


def taskbar_geometry():
    """(hwnd da barra, retângulo da barra, retângulo da bandeja, escala de DPI) ou None."""
    bar = user32.FindWindowW("Shell_TrayWnd", None)
    if not bar:
        return None
    notify = user32.FindWindowExW(bar, None, "TrayNotifyWnd", None)
    if not notify:
        return None
    scale = (user32.GetDpiForWindow(bar) or 96) / 96
    return bar, win_rect(bar), win_rect(notify), scale


def fullscreen_app_active():
    """Algum app (vídeo, apresentação, jogo) ocupa a tela inteira?"""
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(fg, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False
    r = win_rect(fg)
    screen = QApplication.screenAt(r.center())
    return bool(screen) and r.contains(screen.geometry())


class MiniCard(QWidget):
    """Dois mini medidores de 240° (5h e 7d) desenhados sobre a barra de tarefas.

    A janela é "dona" (owner) da barra de tarefas: assim o Windows a mantém sempre
    acima dela, sem disputar o topo. Fica encostada à esquerda da bandeja de ícones;
    não empurra os ícones dos apps, então pode cobri-los se a barra encher.
    """

    GAP, MARGIN, LOGO_W = 6, 4, 26  # em px a 100% de escala
    LABEL_PX = 11  # rótulo "AI" do logo
    LOGO_COLOR = "#d97757"  # terracota do Claude
    # (folga vertical, espessura do arco, número, rótulo, escala do logo) em px a 100%.
    # O compacto é para a barra com "botões menores" (~32 px em vez de 48).
    NORMAL = (5, 5, 12, 11, 1.0)
    COMPACT = (4, 3, 9, 9, 0.7)

    def __init__(self, on_click, menu):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.on_click = on_click
        self.menu = menu
        self.values = (None, None)
        self.stale = False
        self.hover = False
        self.scale = 1.0  # escala do logo, margens e espaçamentos
        self.layout = None
        self.owner = None
        self.timer = QTimer(self, interval=1000, timeout=self.place)
        self.timer.start()
        self.place()

    def set_values(self, five, seven, stale, tooltip):
        self.values = (five, seven)
        self.stale = stale
        self.setToolTip(tooltip)
        self.update()

    def place(self):
        geo = taskbar_geometry()
        if not geo or fullscreen_app_active():
            self.hide()
            return
        bar, bar_rect, notify, scale = geo
        screen = QApplication.screenAt(bar_rect.center())
        # barra oculta automaticamente (fora da tela) ou vertical: não mostra
        if (not screen or not screen.geometry().contains(bar_rect.center())
                or bar_rect.height() > bar_rect.width()):
            self.hide()
            return
        h = bar_rect.height()
        # o tamanho dos medidores sai da altura da barra; recalculado a cada segundo,
        # acompanha a troca de tamanho da barra sem reiniciar
        compact = h < 40 * scale
        pad, thick, number_px, label_px, logo = self.COMPACT if compact else self.NORMAL
        pad, thick, number_px, label_px = (v * scale for v in (pad, thick, number_px, label_px))
        below = max(thick / 2, label_px * 0.4)  # abaixo do centro: ponta do arco ou rótulo
        r = (h - 2 * pad - thick / 2 - below) / 1.5  # 240°: r acima do centro, r/2 abaixo
        layout = (compact, pad, thick, number_px, label_px, r)
        if layout != self.layout:
            self.layout = layout
            self.scale = logo * scale
            self.update()
        s = self.scale
        w = int((self.LOGO_W + self.GAP + 2 * self.MARGIN) * s + 2 * (2 * r + thick))
        x = notify.left() - w - int(self.MARGIN * s)
        target = QRect(x, bar_rect.top(), w, h)
        if self.geometry() != target:
            self.setGeometry(target)
        if not self.isVisible():
            self.show()
        hwnd = int(self.winId())
        if self.owner != bar or user32.GetWindowLongPtrW(hwnd, GWLP_HWNDPARENT) != bar:
            user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, bar)
            self.owner = bar

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.scale
        # fundo quase invisível: sem ele, pixels 100% transparentes não recebem clique
        bg = QColor(255, 255, 255, 22 if self.hover else 1)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(self.rect().adjusted(0, int(4 * s), 0, -int(4 * s)), 4 * s, 4 * s)

        if not self.layout:
            return
        compact, top, thick, number_px, label_px, r = self.layout
        gw = 2 * r + thick
        self.paint_logo(p, self.MARGIN * s, top, self.height() - top - self.LABEL_PX * 1.25 * s)
        # no compacto: rótulo quase branco, número sem "%" e um pouco mais alto (longe do
        # rótulo), para ler melhor em tamanho menor
        label_color, sign, lift = ("#d0d7de", False, 0.22) if compact else (MUTED, True, 0.15)
        for i, (pct, label) in enumerate(zip(self.values, ("5h", "7d"))):
            x = (self.MARGIN + self.LOGO_W) * s + i * (gw + self.GAP * s)
            paint_gauge240(p, x, top, r, thick, pct, number_px, label, label_px, stale=self.stale,
                           percent_sign=sign, track="#5a636e", label_color=label_color,
                           number_lift=lift)

    def paint_logo(self, p, x, top, base):
        """Asterisco radiante em terracota (referência ao Claude) com "AI" embaixo,
        alinhado aos semicírculos: o desenho ocupa a altura do arco, o rótulo a do "5h"."""
        s = self.scale
        w = self.LOGO_W * s
        cx, cy = x + w / 2, (top + base) / 2 + 1 * s
        outer = (base - top) / 2 + 1 * s
        pen = QPen(QColor(self.LOGO_COLOR), 2.2 * s, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        # 12 raios com comprimentos levemente irregulares, como um traço feito à mão
        lengths = (1.0, 0.72, 0.9, 0.78, 1.0, 0.7, 0.92, 0.76, 0.98, 0.72, 0.88, 0.8)
        for i, k in enumerate(lengths):
            a = math.radians(i * 30 + 8)
            r0, r1 = outer * 0.18, outer * k
            p.drawLine(QPointF(cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                       QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
        font = QFont("Segoe UI")
        font.setBold(True)
        font.setPixelSize(int(self.LABEL_PX * s))
        p.setFont(font)
        p.setPen(QColor(self.LOGO_COLOR))
        p.drawText(QRectF(x, base, w, self.LABEL_PX * 1.6 * s), Qt.AlignHCenter | Qt.AlignTop, "AI")

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.on_click(self.geometry().center())
        elif e.button() == Qt.RightButton:
            self.menu.popup(e.globalPos())


class Widget:
    def __init__(self, app):
        self.app = app
        self.usage = None
        self.cfg = load_config()
        self.panel = Panel()

        menu = QMenu()
        menu.addAction("Mostrar painel", lambda: self.toggle_panel(self.tray_anchor()))
        self.card_action = QAction("Mostrar na barra de tarefas", menu, checkable=True)
        self.card_action.setChecked(self.cfg.get("taskbar_card", True))
        self.card_action.toggled.connect(self.set_card)
        menu.addAction(self.card_action)
        self.startup = QAction("Iniciar com o Windows", menu, checkable=True)
        self.startup.setChecked(startup_enabled())
        self.startup.toggled.connect(set_startup)
        menu.addAction(self.startup)
        menu.addSeparator()
        menu.addAction("Sair", app.quit)
        self.menu = menu

        # dois ícones na bandeja: semana (7d) e sessão (5h); ambos abrem o painel
        self.trays = {}
        for key in ("seven", "five"):
            tray = QSystemTrayIcon(make_gauge_icon(None, True))
            tray.setContextMenu(menu)
            tray.activated.connect(lambda reason, t=tray: self.on_activated(reason, t))
            self.trays[key] = tray

        self.card = None
        self.set_card(self.card_action.isChecked())

        self.timer = QTimer(interval=POLL_MS, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        for tray in self.trays.values():
            tray.show()

    def set_card(self, on):
        self.cfg["taskbar_card"] = on
        save_config(self.cfg)
        if on and not self.card:
            self.card = MiniCard(self.toggle_panel, self.menu)
            self.refresh()
        elif not on and self.card:
            self.card.timer.stop()
            self.card.deleteLater()
            self.card = None

    def tray_anchor(self):
        for tray in self.trays.values():
            geo = tray.geometry()
            if geo.isValid():
                return geo.center()
        area = QApplication.primaryScreen().geometry()
        return QPoint(area.right() - 150, area.bottom())

    def toggle_panel(self, anchor):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.refresh(self.usage, time.time())
            self.panel.show_near(anchor)

    def on_activated(self, reason, tray):
        if reason == QSystemTrayIcon.Trigger:
            geo = tray.geometry()
            self.toggle_panel(geo.center() if geo.isValid() else self.tray_anchor())

    def refresh(self):
        if not hasattr(self, "trays"):
            return
        now = time.time()
        u = load_usage()
        self.usage = u
        if not u:
            for tray in self.trays.values():
                tray.setIcon(make_gauge_icon(None, True))
                tray.setToolTip("Claude: sem dados ainda (usage.json não encontrado)")
            if self.card:
                self.card.set_values(None, None, True, "Claude: sem dados ainda")
            return
        five = effective_pct(u.get("five_hour_pct"), u.get("five_hour_resets_at"), now)
        seven = effective_pct(u.get("seven_day_pct"), u.get("seven_day_resets_at"), now)
        stale = now - (u.get("limits_at") or u.get("updated_at") or 0) > STALE_S

        def pct(v):
            return "—" if v is None else f"{round(v)}%"

        lines = [f"Sessão 5h: {pct(five)} · {fmt_countdown(u.get('five_hour_resets_at'), now)}",
                 f"Semana 7d: {pct(seven)} · {fmt_countdown(u.get('seven_day_resets_at'), now)}",
                 f"Contexto: {pct(u.get('context_pct'))}"]
        if u.get("updated_at"):
            lines.append(f"atualizado {fmt_age(u['updated_at'], now)}")
        tooltip = "\n".join(lines)
        self.trays["five"].setIcon(make_gauge_icon(five, stale and five != 0))
        self.trays["seven"].setIcon(make_gauge_icon(seven, stale and seven != 0))
        for tray in self.trays.values():
            tray.setToolTip(tooltip[:127])  # limite do Windows
        if self.card:
            self.card.set_values(five, seven, stale, tooltip)
        if self.panel.isVisible():
            self.panel.refresh(u, now)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # uma instância só: se já houver outra rodando, sai
    probe = QLocalSocket()
    probe.connectToServer(INSTANCE)
    if probe.waitForConnected(300):
        return 0
    QLocalServer.removeServer(INSTANCE)
    server = QLocalServer()
    server.listen(INSTANCE)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        return 1
    widget = Widget(app)  # noqa: F841 (mantém referências vivas)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
