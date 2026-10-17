from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel, QPushButton, QDoubleSpinBox, QHBoxLayout)


class DocCard(QFrame):
    def __init__(self, doc, index, win):
        super().__init__()
        self.setObjectName("card")
        self.doc, self.win = doc, win
        g = QGridLayout(self)
        t = QLabel(f"<b>البطاقة {index + 1}</b> ({doc.kind})")
        g.addWidget(t, 0, 0, 1, 3)
        self.sw = self._spin(doc.w_cm, "w_cm"); self.sh = self._spin(doc.h_cm, "h_cm")
        g.addWidget(QLabel("العرض (cm)"), 1, 0); g.addWidget(self.sw, 1, 1)
        g.addWidget(QLabel("الارتفاع (cm)"), 2, 0); g.addWidget(self.sh, 2, 1)
        g.addWidget(self._img_btn("front"), 1, 2); g.addWidget(self._img_btn("back"), 2, 2)
        row = QHBoxLayout()
        for name, label in (("front", "تحرير الوجه"), ("back", "تحرير الظهر")):
            b = QPushButton(label); b.setEnabled(bool(doc.side(name).path))
            b.clicked.connect(lambda _=False, n=name: win.edit_side(doc, n)); row.addWidget(b)
        g.addLayout(row, 3, 0, 1, 3)
        row2 = QHBoxLayout()
        up, dn = QPushButton("▲"), QPushButton("▼")
        up.clicked.connect(lambda: win.move_doc(doc, -1)); dn.clicked.connect(lambda: win.move_doc(doc, 1))
        d = QPushButton("حذف البطاقة"); d.setObjectName("danger"); d.clicked.connect(lambda: win.delete_doc(doc))
        row2.addWidget(up); row2.addWidget(dn); row2.addWidget(d, 1)
        g.addLayout(row2, 4, 0, 1, 3)

    def _spin(self, val, attr):
        s = QDoubleSpinBox(); s.setRange(0.5, 40); s.setDecimals(1); s.setSingleStep(0.1); s.setValue(val)
        s.valueChanged.connect(lambda v: (setattr(self.doc, attr, v), self.win.refresh_preview()))
        s.editingFinished.connect(self.win.commit)
        return s

    def _img_btn(self, name):
        has = bool(self.doc.side(name).path)
        word = "الوجه" if name == "front" else "الظهر"
        b = QPushButton(("✓ تغيير " if has else "رفع ") + word)
        b.clicked.connect(lambda: self.win.set_side_image(self.doc, name))
        return b
