from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QComboBox, QCheckBox,
                               QPushButton, QHBoxLayout, QVBoxLayout, QFileDialog, QLabel)


class SettingsDialog(QDialog):
    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.setWindowTitle("الإعدادات")
        self.s = s
        f = QFormLayout()
        self.title = QLineEdit(s["app_title"]); f.addRow("اسم البرنامج", self.title)
        self.lib = QLineEdit(s["library_name"]); f.addRow("اسم المكتبة", self.lib)
        self.logo = QLineEdit(s["logo"])
        b = QPushButton("اختيار..."); b.clicked.connect(self._pick_logo)
        r = QHBoxLayout(); r.addWidget(self.logo); r.addWidget(b); f.addRow("الشعار", r)
        self.soc = []
        for item in s["socials"]:
            lab, url = QLineEdit(item["label"]), QLineEdit(item["url"])
            url.setPlaceholderText("الرابط (مثال: https://t.me/name)")
            r = QHBoxLayout(); r.addWidget(lab, 1); r.addWidget(url, 3)
            f.addRow("تواصل", r); self.soc.append((lab, url))
        self.cw = self._spin(1, 40, s["card_w_cm"]); f.addRow("عرض البطاقة الافتراضي (سم)", self.cw)
        self.ch = self._spin(1, 40, s["card_h_cm"]); f.addRow("ارتفاع البطاقة الافتراضي (سم)", self.ch)
        self.mg = self._spin(0, 40, s["margin_mm"]); f.addRow("هوامش الطباعة (مم)", self.mg)
        self.gp = self._spin(0, 40, s["gap_mm"]); f.addRow("التباعد بين الهويات (مم)", self.gp)
        self.dpi = QComboBox(); self.dpi.addItems(["150", "300", "600"]); self.dpi.setCurrentText(str(s["export_dpi"]))
        f.addRow("دقة التصدير (DPI)", self.dpi)
        self.folder = QLineEdit(s["export_folder"])
        b2 = QPushButton("اختيار..."); b2.clicked.connect(self._pick_folder)
        r = QHBoxLayout(); r.addWidget(self.folder); r.addWidget(b2); f.addRow("مجلد الحفظ الافتراضي", r)
        self.auto = QCheckBox("حفظ تلقائي كل دقيقة"); self.auto.setChecked(s["autosave"]); f.addRow("", self.auto)
        self.det = QCheckBox("تعرّف ذكي تلقائي على حواف الهوية عند إضافة الصورة"); self.det.setChecked(s.get("auto_detect", True)); f.addRow("", self.det)
        self.opened = QCheckBox("فتح نافذة التحرير تلقائيًا بعد رفع صورة (للتأكيد على القص)"); self.opened.setChecked(s.get("auto_open_editor", True)); f.addRow("", self.opened)
        f.addRow("لغة الواجهة", QLabel("العربية (دعم لغات أخرى مستقبلًا)"))
        v = QVBoxLayout(self); v.addLayout(f)
        ok = QPushButton("حفظ"); ok.setObjectName("primary"); ok.clicked.connect(self.accept)
        v.addWidget(ok)
        self.setMinimumWidth(480)

    def _spin(self, a, b, val):
        d = QDoubleSpinBox(); d.setRange(a, b); d.setDecimals(1); d.setSingleStep(0.1); d.setValue(val); return d

    def _pick_logo(self):
        p, _ = QFileDialog.getOpenFileName(self, "الشعار", "", "صور (*.png *.jpg *.jpeg *.bmp)")
        if p: self.logo.setText(p)

    def _pick_folder(self):
        p = QFileDialog.getExistingDirectory(self, "مجلد الحفظ")
        if p: self.folder.setText(p)

    def result_settings(self):
        s = dict(self.s)
        s.update(app_title=self.title.text().strip() or s["app_title"], library_name=self.lib.text().strip(),
                 logo=self.logo.text().strip(), card_w_cm=self.cw.value(), card_h_cm=self.ch.value(),
                 margin_mm=self.mg.value(), gap_mm=self.gp.value(), export_dpi=int(self.dpi.currentText()),
                 export_folder=self.folder.text().strip(), autosave=self.auto.isChecked(), auto_detect=self.det.isChecked(), auto_open_editor=self.opened.isChecked(),
                 socials=[{"label": l.text().strip(), "url": u.text().strip()} for l, u in self.soc])
        return s
