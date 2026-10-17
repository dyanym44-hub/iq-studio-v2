"""معاينة ورقة A4 بوحدة الملّيمتر (1 وحدة مشهد = 1 مم)، مع سحب وإفلات ومنع التداخل."""
import os
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPen, QColor, QBrush, QPixmap, QImage, QPainter
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsPixmapItem)
from core import imaging, layout

PREVIEW_DPI = 150
_cache = {}


def pil_to_pixmap(img):
    img = img.convert("RGB")
    qi = QImage(img.tobytes("raw", "RGB"), img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qi.copy())


def side_pixmap(side, w_mm, h_mm):
    wpx, hpx = max(8, round(w_mm / 25.4 * PREVIEW_DPI)), max(8, round(h_mm / 25.4 * PREVIEW_DPI))
    try:
        mt = os.path.getmtime(side.path)
    except OSError:
        mt = 0
    key = (side.path, mt, side.edit.key(), wpx, hpx)
    if key not in _cache:
        if len(_cache) > 200:
            _cache.clear()
        try:
            _cache[key] = pil_to_pixmap(imaging.render_side(side, wpx, hpx, max_side=max(wpx, hpx) * 2))
        except Exception:
            pm = QPixmap(wpx, hpx); pm.fill(QColor("#eee"))
            p = QPainter(pm); p.drawText(pm.rect(), Qt.AlignCenter, "الملف مفقود / تالف"); p.end()
            _cache[key] = pm
    return _cache[key]


class CardItem(QGraphicsPixmapItem):
    def __init__(self, pm, p, view):
        super().__init__(pm)
        self.p, self.view = p, view
        self.setScale(25.4 / PREVIEW_DPI)
        self.setPos(p.x, p.y)
        self.setFlag(QGraphicsPixmapItem.ItemIsMovable, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setTransformationMode(Qt.SmoothTransformation)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.view.item_dropped(self)


class PreviewView(QGraphicsView):
    def __init__(self, on_move):
        super().__init__()
        self.on_move = on_move
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#8d96a8")))
        self.setDragMode(QGraphicsView.NoDrag)
        self.project, self.placements, self.page = None, [], 0
        self.auto_fit = True

    def show_page(self, project, placements, page):
        self.project, self.placements, self.page = project, placements, page
        self.scene_.clear()
        pw, ph = layout.page_dims(project.orientation)
        pen = QPen(QColor("black"), 1); pen.setCosmetic(True)
        self.scene_.addRect(0, 0, pw, ph, pen, QBrush(Qt.white)).setZValue(-2)
        m = project.margin_mm
        mp = QPen(QColor("#4a90e2"), 1, Qt.DashLine); mp.setCosmetic(True)
        self.scene_.addRect(m, m, pw - 2 * m, ph - 2 * m, mp).setZValue(-1)
        for p in placements:
            if p.page != page:
                continue
            side = project.find(p.doc_id).side(p.side)
            self.scene_.addItem(CardItem(side_pixmap(side, p.w, p.h), p, self))
        self.setSceneRect(QRectF(-6, -6, pw + 12, ph + 12))
        if self.auto_fit:
            self.fit()

    def fit(self):
        self.auto_fit = True
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def zoom(self, f):
        self.auto_fit = False
        self.scale(f, f)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.auto_fit and self.project:
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    def item_dropped(self, item):
        p = item.p
        x, y = round(item.x() * 2) / 2, round(item.y() * 2) / 2   # خطوة 0.5 مم
        if abs(x - p.x) < 1e-6 and abs(y - p.y) < 1e-6:
            return
        pw, ph = layout.page_dims(self.project.orientation)
        others = [(q.x, q.y, q.w, q.h) for q in self.placements
                  if q.page == p.page and not (q.doc_id == p.doc_id and q.side == p.side)]
        ok = x >= 0 and y >= 0 and x + p.w <= pw and y + p.h <= ph and layout.is_free(others, x, y, p.w, p.h)
        if ok:
            self.on_move(p.doc_id, p.side, p.page, x, y)
        else:   # تداخل أو خروج عن الورقة: إرجاع البطاقة لمكانها
            item.setPos(p.x, p.y)
            self.on_move(None, None, None, None, None)
