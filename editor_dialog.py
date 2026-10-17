"""نافذة تحرير الصورة: تعرّف ذكي على الهوية، 4 زوايا قابلة للسحب، قص، تدوير، سطوع/تباين، تحسين."""
import math
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QSlider,
                               QLabel, QCheckBox, QGridLayout, QMessageBox)
from core import imaging
from core.models import Edit, Side
from ui.preview import pil_to_pixmap

HANDLE = 8


class CropWidget(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(520, 380)
        self.pm = None
        self.crop = [0.0, 0.0, 1.0, 1.0]
        self.quad = None                      # 4 نقاط [x,y] كنسب من الصورة
        self.p0 = self.p1 = None
        self.drag_i = None
        self.setCursor(Qt.CrossCursor)

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def img_rect(self):
        if not self.pm:
            return QRectF()
        s = min(self.width() / self.pm.width(), self.height() / self.pm.height())
        w, h = self.pm.width() * s, self.pm.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _clamp(self, pt):
        r = self.img_rect()
        return QPointF(min(max(pt.x(), r.left()), r.right()), min(max(pt.y(), r.top()), r.bottom()))

    def _quad_pts(self):
        r = self.img_rect()
        return [QPointF(r.left() + x * r.width(), r.top() + y * r.height()) for x, y in self.quad]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#2b3040"))
        if not self.pm:
            return
        r = self.img_rect()
        p.drawPixmap(r.toRect(), self.pm)
        if self.quad:
            pts = self._quad_pts()
            p.setPen(QPen(QColor("#3ddc84"), 2))
            p.setBrush(QColor(61, 220, 132, 40))
            p.drawPolygon(QPolygonF(pts))
            p.setBrush(QColor("#ffffff"))
            for pt in pts:
                p.drawEllipse(pt, HANDLE, HANDLE)
            return
        sel = QRectF(self.p0, self.p1).normalized() if (self.p0 and self.p1) else QRectF(
            r.left() + self.crop[0] * r.width(), r.top() + self.crop[1] * r.height(),
            (self.crop[2] - self.crop[0]) * r.width(), (self.crop[3] - self.crop[1]) * r.height())
        shade = QColor(0, 0, 0, 120)
        for part in (QRectF(r.left(), r.top(), r.width(), sel.top() - r.top()),
                     QRectF(r.left(), sel.bottom(), r.width(), r.bottom() - sel.bottom()),
                     QRectF(r.left(), sel.top(), sel.left() - r.left(), sel.height()),
                     QRectF(sel.right(), sel.top(), r.right() - sel.right(), sel.height())):
            p.fillRect(part, shade)
        p.setPen(QPen(QColor("#3ddc84"), 2))
        p.drawRect(sel)

    def mousePressEvent(self, e):
        pos = e.position()
        if self.quad:
            d = [math.hypot(pt.x() - pos.x(), pt.y() - pos.y()) for pt in self._quad_pts()]
            i = d.index(min(d))
            self.drag_i = i if d[i] < 24 else None
            return
        self.p0 = self._clamp(pos); self.p1 = self.p0

    def mouseMoveEvent(self, e):
        if self.quad and self.drag_i is not None:
            r = self.img_rect(); pt = self._clamp(e.position())
            self.quad[self.drag_i] = [(pt.x() - r.left()) / r.width(), (pt.y() - r.top()) / r.height()]
            self.update(); return
        if self.p0:
            self.p1 = self._clamp(e.position()); self.update()

    def mouseReleaseEvent(self, e):
        if self.quad:
            if self.drag_i is not None:
                self.drag_i = None; self.changed.emit()
            return
        if not self.p0:
            return
        sel = QRectF(self.p0, self._clamp(e.position())).normalized()
        self.p0 = self.p1 = None
        r = self.img_rect()
        if sel.width() > 10 and sel.height() > 10:
            self.crop = [(sel.left() - r.left()) / r.width(), (sel.top() - r.top()) / r.height(),
                         (sel.right() - r.left()) / r.width(), (sel.bottom() - r.top()) / r.height()]
            self.changed.emit()
        self.update()


class ImageEditor(QDialog):
    def __init__(self, path, edit, ratio, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تحرير الصورة — تعرّف ذكي وقص وتحسين")
        self.path, self.edit, self.ratio = path, edit.copy(), ratio
        self._img_size = (1, 1)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.crop_w = CropWidget(); self.crop_w.changed.connect(self._crop_changed)
        top.addWidget(self.crop_w, 3)
        rv = QVBoxLayout()
        rv.addWidget(QLabel("النتيجة النهائية:"))
        self.result = QLabel(); self.result.setMinimumSize(300, 200); self.result.setAlignment(Qt.AlignCenter)
        self.result.setStyleSheet("background:#fff;border:1px solid #bbb;")
        rv.addWidget(self.result); rv.addStretch()
        top.addLayout(rv, 1)
        v.addLayout(top, 1)
        v.addWidget(QLabel("«تعرّف ذكي» يحدد حواف الهوية ويعدّل ميلانها تلقائيًا. اسحب النقاط البيضاء لضبط الزوايا. "
                           "أو اسحب على الصورة لقص مستطيل."))

        g = QGridLayout()
        self.s_angle = self._slider(-150, 150, int(self.edit.angle * 10))
        self.s_bri = self._slider(-100, 100, self.edit.brightness)
        self.s_con = self._slider(-100, 100, self.edit.contrast)
        self.l_angle = QLabel()
        for i, (txt, s) in enumerate((("تصحيح الميلان", self.s_angle), ("السطوع", self.s_bri), ("التباين", self.s_con))):
            g.addWidget(QLabel(txt), i, 0); g.addWidget(s, i, 1)
        g.addWidget(self.l_angle, 0, 2)
        v.addLayout(g)
        row = QHBoxLayout()
        self.c_bw = QCheckBox("أبيض وأسود"); self.c_bw.setChecked(self.edit.bw)
        self.c_en = QCheckBox("تحسين الوضوح"); self.c_en.setChecked(self.edit.enhance)
        row.addWidget(self.c_bw); row.addWidget(self.c_en); row.addStretch()
        v.addLayout(row)

        btns = QHBoxLayout()
        b = QPushButton("🔍 تعرّف ذكي على الهوية"); b.setObjectName("primary"); b.clicked.connect(self._smart)
        btns.addWidget(b, 2)
        for txt, fn in (("ضبط الحواف يدويًا", self._manual_quad), ("تدوير 90°", self._rot),
                        ("قلب 180°", self._flip), ("ملاءمة الإطار", self._fit_frame),
                        ("إلغاء التحديد", self._clear), ("استعادة الأصل", self._reset)):
            x = QPushButton(txt); x.clicked.connect(fn); btns.addWidget(x)
        v.addLayout(btns)
        ok = QHBoxLayout()
        b_ok = QPushButton("اعتماد"); b_ok.setObjectName("primary"); b_ok.clicked.connect(self.accept)
        b_no = QPushButton("إلغاء"); b_no.clicked.connect(self.reject)
        ok.addWidget(b_ok, 2); ok.addWidget(b_no, 1)
        v.addLayout(ok)

        for s in (self.s_angle, self.s_bri, self.s_con):
            s.valueChanged.connect(self._params_changed)
        self.c_bw.toggled.connect(self._params_changed)
        self.c_en.toggled.connect(self._params_changed)
        self.resize(1050, 720)
        self.refresh()

    def _slider(self, a, b, val):
        s = QSlider(Qt.Horizontal); s.setRange(a, b); s.setValue(val); return s

    def _clear_geometry(self):
        self.edit.crop = [0.0, 0.0, 1.0, 1.0]
        self.edit.quad = None

    def _params_changed(self):
        e = self.edit
        new_angle = self.s_angle.value() / 10
        if abs(new_angle - e.angle) > 1e-9:
            self._clear_geometry()              # تغيّر الأساس الهندسي فيُلغى التحديد
        e.angle = new_angle
        e.brightness, e.contrast = self.s_bri.value(), self.s_con.value()
        e.bw, e.enhance = self.c_bw.isChecked(), self.c_en.isChecked()
        self.refresh()

    def _crop_changed(self):
        if self.crop_w.quad:
            self.edit.quad = [list(p) for p in self.crop_w.quad]
        else:
            self.edit.crop = list(self.crop_w.crop)
        self.refresh(redraw_base=False)

    def _smart(self):
        from core import autodetect
        try:
            q = autodetect.detect_quad(self.path, self.edit.rot90) if abs(self.edit.angle) < 0.01 else None
        except Exception as ex:
            QMessageBox.warning(self, "التعرف الذكي", f"تعذّر التشغيل:\n{ex}"); return
        if q is None:
            if abs(self.edit.angle) >= 0.01:
                self.s_angle.setValue(0)
                return self._smart()
            self._manual_quad()
            QMessageBox.information(self, "التعرف الذكي",
                                    "لم أستطع تحديد الحواف بثقة (الخلفية قريبة من لون الهوية؟).\n"
                                    "حرّكت لك أربع نقاط — اسحبها على زوايا الهوية.")
            return
        self.edit.crop = [0.0, 0.0, 1.0, 1.0]; self.edit.quad = q
        self.refresh()

    def _manual_quad(self):
        self.edit.crop = [0.0, 0.0, 1.0, 1.0]
        self.edit.quad = [[0.08, 0.08], [0.92, 0.08], [0.92, 0.92], [0.08, 0.92]]
        self.refresh()

    def _rot(self):
        self.edit.rot90 = (self.edit.rot90 + 90) % 360
        self._clear_geometry(); self.refresh()

    def _flip(self):
        if self.edit.quad:      # قلب الناتج 180° بتدوير ترتيب الزوايا
            q = self.edit.quad; self.edit.quad = q[2:] + q[:2]
        else:
            self.edit.rot90 = (self.edit.rot90 + 180) % 360; self._clear_geometry()
        self.refresh()

    def _clear(self):
        self._clear_geometry(); self.refresh()

    def _fit_frame(self):
        w, h = self._img_size
        a = w / h
        self.edit.quad = None
        if a > self.ratio:
            f = self.ratio / a; self.edit.crop = [(1 - f) / 2, 0.0, (1 + f) / 2, 1.0]
        else:
            f = a / self.ratio; self.edit.crop = [0.0, (1 - f) / 2, 1.0, (1 + f) / 2]
        self.refresh()

    def _reset(self):
        self.edit = Edit()
        for s in (self.s_angle, self.s_bri, self.s_con):
            s.blockSignals(True); s.setValue(0); s.blockSignals(False)
        for c in (self.c_bw, self.c_en):
            c.blockSignals(True); c.setChecked(False); c.blockSignals(False)
        self.refresh()

    def refresh(self, redraw_base=True):
        try:
            base = imaging.rotated_image(self.path, self.edit, 1400)
        except Exception as ex:
            QMessageBox.critical(self, "خطأ", f"تعذّر فتح الصورة:\n{ex}")
            self.reject(); return
        self._img_size = base.size
        self.l_angle.setText(f"{self.edit.angle:+.1f}°")
        self.crop_w.crop = list(self.edit.crop)
        self.crop_w.quad = [list(p) for p in self.edit.quad] if self.edit.quad else None
        if redraw_base:
            self.crop_w.set_pixmap(pil_to_pixmap(imaging.adjust(base, self.edit)))
        self.crop_w.update()
        w = 300; h = max(40, round(w / self.ratio))
        try:
            img = imaging.render_side(Side(path=self.path, edit=self.edit), w * 2, h * 2, max_side=1400)
            self.result.setPixmap(pil_to_pixmap(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.result.setText("—")
