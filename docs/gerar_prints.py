"""Gera os prints do README em docs/ a partir do próprio widget.pyw.

Rodar depois de qualquer mudança visual no widget (na pasta do projeto):

    run-python.cmd python-qt docs\\gerar_prints.py

Cartão, painel e ícones saem com dados de exemplo (sempre iguais, sem caminhos nem custo
reais). O taskbar.png é uma captura real da tela: precisa do widget aberto e com o cartão
na barra; sem isso, o print antigo fica como está.
"""
import importlib.util
import os
import sys
import time
from importlib.machinery import SourceFileLoader

from PyQt5.QtGui import QRegion

DOCS = os.path.dirname(os.path.abspath(__file__))
loader = SourceFileLoader("widget", os.path.join(os.path.dirname(DOCS), "widget.pyw"))
spec = importlib.util.spec_from_loader("widget", loader)
w = importlib.util.module_from_spec(spec)
loader.exec_module(w)

TASKBAR_BG = "#1c1c1c"  # fundo da barra de tarefas no tema escuro do Windows 11
ZOOM = 3  # cartão e ícones ampliados, para ficarem nítidos no README


def save(pm, name):
    path = os.path.join(DOCS, name)
    pm.save(path)
    print(f"  {name}  ({pm.width()}x{pm.height()})")


def example_usage(five, seven, ctx, now):
    return {"model": "Opus 5.5 (1M context)", "five_hour_pct": five, "seven_day_pct": seven,
            "five_hour_resets_at": now + 3 * 3600 + 3 * 60, "seven_day_resets_at": now + 6 * 86400 + 9 * 3600,
            "context_pct": ctx, "cwd": "C:/projetos/meu-projeto", "cost_usd": 1.38, "updated_at": now}


def fake_history(final, now):
    """Uso de 5h subindo aos poucos ao longo das últimas 5 horas, terminando em `final`."""
    start = now - w.Spark.WINDOW
    steps = 60
    return [(start + i * w.Spark.WINDOW / steps, final * (i / steps) ** 1.6) for i in range(steps + 1)]


def print_panel(five, seven, ctx, name, now):
    panel = w.Panel()
    w.load_history = lambda since, f=five: fake_history(f, now)  # o painel lê o histórico por aqui
    panel.refresh(example_usage(five, seven, ctx, now), now)
    panel.adjustSize()
    save(panel.grab(), name)


class CardPrint(w.MiniCard):
    """O mini-cartão de verdade, mas fora da barra de tarefas (sem place())."""

    def __init__(self, five, seven, h, scale):
        w.QWidget.__init__(self)
        self.setAttribute(w.Qt.WA_TranslucentBackground)
        self.values = (five, seven)
        self.stale = False
        self.hover = False
        self.layout, self.scale, width = self.compute_layout(h, scale)
        self.resize(width, h)


def print_card(five, seven, name):
    card = CardPrint(five, seven, 48 * ZOOM, ZOOM)
    pm = w.QPixmap(card.size())
    pm.fill(w.QColor(TASKBAR_BG))
    card.render(pm, w.QPoint(), QRegion(), w.QWidget.DrawChildren)
    save(pm, name)


def print_icons(name):
    cases = [(5, False), (67, False), (92, False), (None, True)]
    cell = 64 + 16
    pm = w.QPixmap(len(cases) * cell, 64 + 8 + 32)
    pm.fill(w.QColor(TASKBAR_BG))
    p = w.QPainter(pm)
    for i, (pct, stale) in enumerate(cases):
        icon = w.make_gauge_icon(pct, stale)
        x = i * cell + 8
        p.drawPixmap(x, 0, icon.pixmap(64, 64))
        # tamanhos reais da bandeja: 16 px (100%) e 32 px (200%)
        p.drawPixmap(x + 4, 72 + 8, icon.pixmap(16, 16))
        p.drawPixmap(x + 28, 72, icon.pixmap(32, 32))
    p.end()
    save(pm, name)


def print_taskbar(name):
    geo = w.taskbar_geometry()
    if not geo:
        print(f"  {name}: barra de tarefas não encontrada; mantido o print antigo")
        return
    _, bar, notify, scale = geo
    _, _, card_w = w.MiniCard.compute_layout(bar.height(), scale)
    x0 = max(bar.left(), notify.left() - card_w - int(60 * scale))
    screen = w.QApplication.screenAt(bar.center()) or w.QApplication.primaryScreen()
    pm = screen.grabWindow(0, x0, bar.top(), bar.right() - x0 + 1, bar.height())
    # dobra os pixels sem suavizar, para o print não ficar borrado no README
    save(pm.scaled(pm.width() * 2, pm.height() * 2, w.Qt.KeepAspectRatio, w.Qt.FastTransformation), name)
    print("    (captura real: confira se o cartão do widget aparece nela)")


def main():
    app = w.QApplication(sys.argv)  # noqa: F841 (precisa existir antes dos widgets)
    now = time.time()
    print(f"Gerando os prints em {DOCS}")
    print_card(100, 67, "card.png")
    print_panel(37, 12, 8, "panel.png", now)
    print_panel(67, 91, 8, "panel_hi.png", now)
    print_icons("icons.png")
    print_taskbar("taskbar.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
