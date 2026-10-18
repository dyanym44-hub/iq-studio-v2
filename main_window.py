import json, os, traceback
from functools import wraps
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QPainter, QImage, QPixmap, QIcon, QPageLayout, QPageSize
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QScrollArea,
                               QComboBox, QSlider, QFileDialog, QMessageBox, QApplication, QFrame)
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog
from core import settings as cfg, layout, exporter, imaging, project_io
from core.models import Project, Doc, Edit, SIDE_NAMES
from ui.preview import PreviewView
from ui.doc_card import DocCard
from ui.editor_dialog import ImageEditor
from ui.settings_dialog import SettingsDialog
try:
    from core import autodetect
except Exception:
    autodetect = None

KINDS = ["ورقة A4 (مستند كامل)", "البطاقة الوطنية", "هوية الأحوال المدنية", "شهادة الجنسية", "بطاقة السكن",
         "بطاقة الناخب", "بطاقة موظف", "بطاقة طالب", "مستمسك آخر"]
# أبعاد افتراضية خاصة ببعض أنواع المستمسكات (عرض، ارتفاع) بالسنتيمتر
KIND_SIZES = {"بطاقة السكن": (9.5, 6.5)}
IMG_FILTER = "صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
AUTOSAVE = cfg.DIR / "autosave.iqproj"


def safe(fn):
    """يمنع انهيار البرنامج: أي خطأ يظهر كرسالة واضحة والعمل يبقى محفوظًا."""
    @wraps(fn)
    def w(self, *a, **k):
        try:
            return fn(self, *a)
        except Exception as ex:
            traceback.print_exc()
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "حدث خطأ", f"{ex}\n\nلم يُفقد عملك. حاول مرة أخرى.")
    return w


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.s = cfg.load()
        self.project = Project(margin_mm=self.s["margin_mm"], gap_mm=self.s["gap_mm"])
        self.path = None
        self.page = 0
        self.history, self.hpos, self.saved_state = [], -1, None
        self._build()
        self.commit(); self.saved_state = self.history[-1]
        self.timer = QTimer(self); self.timer.timeout.connect(self.autosave); self.apply_settings()
        QTimer.singleShot(300, self.offer_restore)

    # ---------- بناء الواجهة ----------
    def _build(self):
        self.resize(1180, 820)
        c = QWidget(); self.setCentralWidget(c)
        root = QVBoxLayout(c)
        self.title = QLabel(); self.title.setObjectName("title"); self.title.setAlignment(Qt.AlignCenter)
        root.addWidget(self.title)
        self.soc_row = QHBoxLayout(); root.addLayout(self.soc_row)

        body = QHBoxLayout(); root.addLayout(body, 1)
        # المعاينة (يمين في RTL)
        pv = QVBoxLayout(); body.addLayout(pv, 3)
        nav = QHBoxLayout()
        self.b_prev, self.b_next = QPushButton("السابق"), QPushButton("التالي")
        self.b_prev.clicked.connect(lambda: self.goto(self.page - 1)); self.b_next.clicked.connect(lambda: self.goto(self.page + 1))
        self.l_page = QLabel(); self.l_page.setAlignment(Qt.AlignCenter)
        self.b_orient = QPushButton(); self.b_orient.clicked.connect(self.toggle_orient)
        zi, zo, zf = QPushButton("＋"), QPushButton("－"), QPushButton("ملاءمة")
        zi.clicked.connect(lambda: self.view.zoom(1.2)); zo.clicked.connect(lambda: self.view.zoom(1 / 1.2)); zf.clicked.connect(lambda: self.view.fit())
        for w in (self.b_prev, self.l_page, self.b_next, self.b_orient, zi, zo, zf):
            nav.addWidget(w, 1 if w is self.l_page else 0)
        pv.addLayout(nav)
        self.view = PreviewView(self.on_drag)
        pv.addWidget(self.view, 1)
        self.l_status = QLabel(); self.l_status.setObjectName("status"); pv.addWidget(self.l_status)

        # اللوحة الجانبية
        side = QVBoxLayout(); body.addLayout(side, 1)
        add = QHBoxLayout()
        self.kind = QComboBox(); self.kind.addItems(KINDS)
        b_add = QPushButton("＋ إضافة مستمسك"); b_add.setObjectName("primary"); b_add.clicked.connect(lambda: self.add_doc())
        add.addWidget(self.kind, 1); add.addWidget(b_add, 1); side.addLayout(add)
        b_multi = QPushButton("إضافة عدة صور دفعة واحدة"); b_multi.clicked.connect(self.add_many); side.addWidget(b_multi)
        fr = QFrame(); fr.setObjectName("card"); fv = QVBoxLayout(fr)
        self.sl_gap, self.l_gap = self._mm_slider(fv, "التباعد بين الهويات", 0, 20, lambda v: self._set_proj("gap_mm", v))
        self.sl_mar, self.l_mar = self._mm_slider(fv, "هوامش الطباعة", 0, 30, lambda v: self._set_proj("margin_mm", v))
        b_smart = QPushButton("🔍 تعرّف ذكي على حواف كل الهويات"); b_smart.clicked.connect(self.smart_all); fv.addWidget(b_smart)
        b_auto = QPushButton("ترتيب تلقائي لاستغلال الورقة"); b_auto.clicked.connect(self.auto_arrange); fv.addWidget(b_auto)
        side.addWidget(fr)
        self.cards = QVBoxLayout(); self.cards.setAlignment(Qt.AlignTop)
        host = QWidget(); host.setLayout(self.cards)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setWidget(host); sc.setMinimumWidth(340)
        side.addWidget(sc, 1)

        # الأسفل
        bot = QHBoxLayout(); root.addLayout(bot)
        self.b_print = QPushButton("طباعة مباشرة"); self.b_pdf = QPushButton("تصدير PDF"); self.b_img = QPushButton("تصدير صورة")
        for b, fn in ((self.b_print, self.print_now), (self.b_pdf, self.export_pdf), (self.b_img, self.export_img)):
            b.setObjectName("primary"); b.clicked.connect(fn); bot.addWidget(b, 3)
        self.fmt = QComboBox(); self.fmt.addItems(["JPG", "PNG"]); self.fmt.setCurrentText(self.s["export_format"])
        self.dpi = QComboBox(); self.dpi.addItems(["150", "300", "600"])
        self.rng = QComboBox(); self.rng.addItems(["كل الصفحات", "الصفحة الحالية"])
        for w in (self.fmt, self.dpi, self.rng):
            bot.addWidget(w, 1)

        mb = self.menuBar(); m = mb.addMenu("ملف")
        for txt, fn, key in (("مشروع جديد", self.new_project, QKeySequence.New), ("فتح مشروع...", self.open_project, QKeySequence.Open),
                             ("حفظ", self.save, QKeySequence.Save), ("حفظ باسم جديد...", self.save_as, QKeySequence("Ctrl+Shift+S")),
                             ("إعادة تعيين المشروع", self.reset_project, None), ("الإعدادات...", self.open_settings, None),
                             ("خروج", self.close, None)):
            a = QAction(txt, self); a.triggered.connect(fn)
            if key: a.setShortcut(key)
            m.addAction(a)
        e = mb.addMenu("تحرير")
        for txt, fn, key in (("تراجع", self.undo, QKeySequence.Undo), ("إعادة", self.redo, QKeySequence.Redo)):
            a = QAction(txt, self); a.triggered.connect(fn); a.setShortcut(key); e.addAction(a)
        self.statusBar().showMessage("جاهز")

    def _mm_slider(self, lay, text, a, b, cb):
        row = QHBoxLayout(); lab = QLabel(text); val = QLabel(); s = QSlider(Qt.Horizontal); s.setRange(a * 2, b * 2)
        s.valueChanged.connect(lambda v: (val.setText(f"{v/2:.1f} mm"), cb(v / 2)))
        s.sliderReleased.connect(self.commit)
        row.addWidget(lab); row.addWidget(s, 1); row.addWidget(val); lay.addLayout(row)
        return s, val

    # ---------- الحالة والتراجع ----------
    def _state(self):
        return json.dumps(self.project.to_dict(), ensure_ascii=False)

    def commit(self):
        st = self._state()
        if self.hpos >= 0 and self.history[self.hpos] == st:
            return
        self.history = self.history[:self.hpos + 1] + [st]
        self.hpos = len(self.history) - 1
        self.setWindowTitle(self._window_title())

    def _restore(self, st):
        self.project = Project.from_dict(json.loads(st))
        self.sync_controls(); self.rebuild_cards(); self.refresh_preview()
        self.setWindowTitle(self._window_title())

    def undo(self):
        if self.hpos > 0:
            self.hpos -= 1; self._restore(self.history[self.hpos])

    def redo(self):
        if self.hpos < len(self.history) - 1:
            self.hpos += 1; self._restore(self.history[self.hpos])

    def dirty(self):
        return self._state() != self.saved_state

    def _window_title(self):
        name = os.path.basename(self.path) if self.path else "مشروع جديد"
        return f"{self.s['app_title']} — {name}{' *' if self.hpos >= 0 and self.history[self.hpos] != self.saved_state else ''}"

    def sync_controls(self):
        for sl, v in ((self.sl_gap, self.project.gap_mm), (self.sl_mar, self.project.margin_mm)):
            sl.blockSignals(True); sl.setValue(round(v * 2)); sl.blockSignals(False)
        self.l_gap.setText(f"{self.project.gap_mm:.1f} mm"); self.l_mar.setText(f"{self.project.margin_mm:.1f} mm")
        self.b_orient.setText("الاتجاه: عمودي" if self.project.orientation == "P" else "الاتجاه: أفقي")

    def _set_proj(self, attr, v):
        setattr(self.project, attr, v); self.refresh_preview()

    # ---------- العرض ----------
    def apply_settings(self):
        self.title.setText(self.s["app_title"] + (f" — {self.s['library_name']}" if self.s["library_name"] else ""))
        if self.s["logo"] and os.path.isfile(self.s["logo"]):
            self.setWindowIcon(QIcon(self.s["logo"]))
        while self.soc_row.count():
            w = self.soc_row.takeAt(0).widget()
            if w: w.deleteLater()
        for it in self.s["socials"]:
            if not it["label"]:
                continue
            b = QPushButton(it["label"]); b.clicked.connect(lambda _=False, u=it["url"]: self.open_url(u)); self.soc_row.addWidget(b)
        self.dpi.setCurrentText(str(self.s["export_dpi"]))
        self.timer.stop()
        if self.s["autosave"]: self.timer.start(60000)
        self.sync_controls(); self.setWindowTitle(self._window_title())

    def open_url(self, url):
        if not url:
            QMessageBox.information(self, "رابط غير مضبوط", "أضف الرابط من: ملف ← الإعدادات")
        else:
            QDesktopServices.openUrl(QUrl(url if "://" in url else "https://" + url))

    def rebuild_cards(self):
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w: w.deleteLater()
        for i, d in enumerate(self.project.docs):
            self.cards.addWidget(DocCard(d, i, self))

    def refresh_preview(self):
        pl, n = layout.compute_layout(self.project)
        self.page = max(0, min(self.page, n - 1))
        self.view.show_page(self.project, pl, self.page)
        pw, ph = layout.page_dims(self.project.orientation)
        self.l_page.setText(f"الصفحة {self.page + 1} / {n}")
        self.b_prev.setEnabled(self.page > 0); self.b_next.setEnabled(self.page < n - 1)
        self.l_status.setText(f"معاينة • A4 • {pw:.0f} × {ph:.0f} mm • جودة التصدير {self.dpi.currentText()} dpi")
        over = [p for p in pl if p.x + p.w > pw - self.project.margin_mm + 1e-6 or p.y + p.h > ph - self.project.margin_mm + 1e-6]
        if over:
            self.statusBar().showMessage("تنبيه: بعض البطاقات أكبر من المساحة المتاحة داخل الهوامش")

    def goto(self, p):
        self.page = p; self.refresh_preview()

    def toggle_orient(self):
        self.project.orientation = "L" if self.project.orientation == "P" else "P"
        for d in self.project.docs:
            for n in ("front", "back"): d.side(n).pos = None
        self.sync_controls(); self.commit(); self.refresh_preview()

    # ---------- المستندات ----------
    @safe
    def add_doc(self, files=None):
        self.project.docs.append(self._new_doc())
        self.after_structure_change()

    def after_structure_change(self):
        self.commit(); self.rebuild_cards(); self.refresh_preview()

    def _new_doc(self):
        kind = self.kind.currentText()
        if "A4" in kind:
            return Doc(kind=kind, w_cm=21.0, h_cm=29.7)
        w, h = KIND_SIZES.get(kind, (self.s["card_w_cm"], self.s["card_h_cm"]))
        return Doc(kind=kind, w_cm=w, h_cm=h)

    def _auto_detect(self, side, doc):
        """يحدد حواف الهوية تلقائيًا إن كان الخيار مفعّلًا؛ يفشل بصمت ويترك الصورة كما هي."""
        if not (self.s.get("auto_detect", True) and autodetect and side.path):
            return False
        try:
            q = autodetect.detect_quad(side.path, side.edit.rot90, doc.w_cm / doc.h_cm)
        except Exception:
            return False
        if q:
            side.edit.crop, side.edit.quad = [0.0, 0.0, 1.0, 1.0], q
        return bool(q)

    def smart_all(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok = total = 0
        try:
            for d in self.project.docs:
                for n in ("front", "back"):
                    sd = d.side(n)
                    if sd.path and os.path.isfile(sd.path):
                        total += 1; sd.edit.quad = None
                        ok += self._auto_detect(sd, d)
        finally:
            QApplication.restoreOverrideCursor()
        self.commit(); self.refresh_preview()
        QMessageBox.information(self, "التعرف الذكي", f"تم التعرف على {ok} من {total} صورة.\nالباقي عدّله من «تحرير الوجه/الظهر».")

    @safe
    def add_many(self):
        files, _ = QFileDialog.getOpenFileNames(self, "اختر صور المستمسكات", self.s["export_folder"], IMG_FILTER)
        bad = []
        for f in files:
            try:
                imaging.check_image(f)
            except Exception:
                bad.append(os.path.basename(f)); continue
            d = self._new_doc()
            d.front.path = f; self._auto_detect(d.front, d); self.project.docs.append(d)
        if files: self.after_structure_change()
        if bad: QMessageBox.warning(self, "ملفات غير صالحة", "تعذّر فتح:\n" + "\n".join(bad))

    @safe
    def set_side_image(self, doc, side):
        f, _ = QFileDialog.getOpenFileName(self, f"اختر صورة {SIDE_NAMES[side]}", self.s["export_folder"], IMG_FILTER)
        if not f: return
        try:
            imaging.check_image(f)
        except Exception:
            QMessageBox.warning(self, "ملف غير صالح", "الملف المختار ليس صورة صالحة أو لا يمكن فتحه."); return
        s = doc.side(side); s.path, s.edit = f, Edit()
        self._auto_detect(s, doc)
        self.after_structure_change()

    @safe
    def edit_side(self, doc, side):
        s = doc.side(side)
        if not s.path or not os.path.isfile(s.path):
            QMessageBox.warning(self, "الصورة مفقودة", "ملف الصورة غير موجود. اختر صورة جديدة."); return
        dlg = ImageEditor(s.path, s.edit, doc.w_cm / doc.h_cm, self)
        if dlg.exec():
            s.edit = dlg.edit; self.commit(); self.refresh_preview()

    def delete_doc(self, doc):
        if QMessageBox.question(self, "حذف", "حذف هذه البطاقة؟") == QMessageBox.Yes:
            self.project.docs.remove(doc); self.after_structure_change()

    def move_doc(self, doc, d):
        L = self.project.docs; i = L.index(doc); j = i + d
        if 0 <= j < len(L):
            L[i], L[j] = L[j], L[i]
            for x in L:
                for n in ("front", "back"): x.side(n).pos = None   # إعادة الترتيب تلغي المواضع اليدوية
            self.after_structure_change()

    def auto_arrange(self):
        for d in self.project.docs:
            for n in ("front", "back"): d.side(n).pos = None
        self.commit(); self.refresh_preview()

    def on_drag(self, doc_id, side, page, x, y):
        if doc_id is None:
            self.statusBar().showMessage("لا يمكن وضع البطاقة هنا (تداخل أو خارج الورقة)"); return
        pl, _ = layout.compute_layout(self.project)
        for p in pl:    # تثبيت الوضع الحالي كي لا تتحرك بقية البطاقات
            self.project.find(p.doc_id).side(p.side).pos = [p.page, p.x, p.y]
        self.project.find(doc_id).side(side).pos = [page, x, y]
        self.commit(); self.refresh_preview()

    # ---------- المشاريع ----------
    def _confirm_discard(self):
        if not self.dirty(): return True
        r = QMessageBox.question(self, "تغييرات غير محفوظة", "هل تريد حفظ المشروع قبل المتابعة؟",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save: return self.save()
        return r == QMessageBox.Discard

    def _load_into(self, project, path):
        self.project, self.path, self.page = project, path, 0
        self.history, self.hpos = [], -1
        self.sync_controls(); self.rebuild_cards(); self.refresh_preview(); self.commit(); self.saved_state = self.history[-1]
        self.setWindowTitle(self._window_title())

    def new_project(self):
        if self._confirm_discard():
            self._load_into(Project(margin_mm=self.s["margin_mm"], gap_mm=self.s["gap_mm"]), None)

    def reset_project(self):
        if QMessageBox.question(self, "إعادة تعيين", "مسح كل المستندات والبدء من جديد؟") == QMessageBox.Yes:
            self.project = Project(margin_mm=self.s["margin_mm"], gap_mm=self.s["gap_mm"])
            self.sync_controls(); self.after_structure_change()

    @safe
    def open_project(self):
        if not self._confirm_discard(): return
        f, _ = QFileDialog.getOpenFileName(self, "فتح مشروع", self.s["export_folder"], "مشروع IQ (*.iqproj)")
        if f:
            self._load_into(project_io.load_project(f), f); project_io.clean_cache()

    @safe
    def save(self):
        if not self.path: return self.save_as()
        return self._save_to(self.path)

    @safe
    def save_as(self):
        f, _ = QFileDialog.getSaveFileName(self, "حفظ المشروع", os.path.join(self.s["export_folder"], "مشروع.iqproj"), "مشروع IQ (*.iqproj)")
        if not f: return False
        if not f.endswith(project_io.EXT): f += project_io.EXT
        return self._save_to(f)

    def _save_to(self, f):
        project_io.save_project(self.project, f)
        self.path, self.saved_state = f, self._state()
        self.setWindowTitle(self._window_title()); self.statusBar().showMessage(f"تم الحفظ: {f}")
        return True

    def autosave(self):
        try:
            cfg.DIR.mkdir(parents=True, exist_ok=True)
            if self.project.docs: project_io.save_project(self.project, str(AUTOSAVE)); self.statusBar().showMessage("حفظ تلقائي")
        except Exception:
            pass

    def offer_restore(self):
        if AUTOSAVE.exists() and self.s["autosave"] and not self.project.docs:
            if QMessageBox.question(self, "استرجاع", "وُجدت نسخة محفوظة تلقائيًا. هل تريد استرجاعها؟") == QMessageBox.Yes:
                try: self._load_into(project_io.load_project(str(AUTOSAVE)), None)
                except Exception as ex: QMessageBox.warning(self, "تعذّر الاسترجاع", str(ex))

    def open_settings(self):
        d = SettingsDialog(self.s, self)
        if d.exec():
            self.s = d.result_settings(); cfg.save(self.s); self.apply_settings(); self.refresh_preview()

    # ---------- التصدير والطباعة ----------
    def _ready(self):
        if not any(s.path for d in self.project.docs for s in (d.front, d.back)):
            QMessageBox.information(self, "لا توجد صور", "أضف صور المستمسكات أولًا."); return False
        miss = exporter.missing_files(self.project)
        if miss:
            QMessageBox.warning(self, "ملفات مفقودة", "هذه الصور لم تعد موجودة:\n" + "\n".join(miss[:8])); return False
        return True

    def _only(self):
        return self.page if self.rng.currentIndex() == 1 else None

    def _default_name(self, ext):
        return os.path.join(self.s["export_folder"], "مستمسكات." + ext)

    @safe
    def export_pdf(self):
        if not self._ready(): return
        f, _ = QFileDialog.getSaveFileName(self, "تصدير PDF", self._default_name("pdf"), "PDF (*.pdf)")
        if not f: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try: n = exporter.export_pdf(self.project, f, int(self.dpi.currentText()), self._only())
        finally: QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "تم التصدير", f"تم إنشاء PDF ({n} صفحة) بحجم A4 حقيقي:\n{f}")

    @safe
    def export_img(self):
        if not self._ready(): return
        fmt = self.fmt.currentText()
        f, _ = QFileDialog.getSaveFileName(self, "تصدير صورة", self._default_name(fmt.lower()), f"{fmt} (*.{fmt.lower()})")
        if not f: return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try: files = exporter.export_images(self.project, f, int(self.dpi.currentText()), fmt, self._only())
        finally: QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "تم التصدير", "تم الحفظ:\n" + "\n".join(files))

    @safe
    def print_now(self):
        if not self._ready(): return
        pr = QPrinter(QPrinter.HighResolution); self._setup_printer(pr)
        dlg = QPrintPreviewDialog(pr, self); dlg.setWindowTitle("معاينة الطباعة (100%)")
        dlg.paintRequested.connect(self._paint_print); dlg.resize(900, 700); dlg.exec()

    def _setup_printer(self, pr):
        pr.setPageSize(QPageSize(QPageSize.A4))
        pr.setPageOrientation(QPageLayout.Landscape if self.project.orientation == "L" else QPageLayout.Portrait)
        pr.setFullPage(True)

    def _paint_print(self, pr):
        """الطباعة بالحجم الفعلي: صفحة A4 كاملة تُرسم على الورقة بنسبة 100% دون تصغير."""
        self._setup_printer(pr)
        painter = QPainter(pr)
        rect = pr.paperRect(QPrinter.DevicePixel)
        for i, img in enumerate(exporter.render_pages(self.project, 300)):
            if i: pr.newPage()
            qi = QImage(img.tobytes("raw", "RGB"), img.width, img.height, img.width * 3, QImage.Format_RGB888)
            painter.drawImage(rect, qi)
        painter.end()

    def closeEvent(self, e):
        if self._confirm_discard():
            self.s["export_format"] = self.fmt.currentText(); cfg.save(self.s); e.accept()
        else:
            e.ignore()
