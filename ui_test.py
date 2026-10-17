import os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.style import QSS
from ui.editor_dialog import ImageEditor
from core.models import Edit

app = QApplication([]); app.setLayoutDirection(Qt.RightToLeft); app.setStyleSheet(QSS)
tmp = tempfile.mkdtemp()
def mk(n, c):
    p = os.path.join(tmp, n); im = Image.new("RGB", (1600, 1000), c); ImageDraw.Draw(im).rectangle((30,30,1570,970), outline="black", width=12); im.save(p); return p
w = MainWindow(); w.show()
w.add_doc(); w.add_doc(); w.add_doc()
for i, d in enumerate(w.project.docs):
    d.front.path = mk(f"f{i}.png", (220, 120+i*40, 90)); d.back.path = mk(f"b{i}.png", (90, 150, 230-i*30))
w.after_structure_change()
# سحب يدوي + تراجع
pl, _ = __import__("core.layout", fromlist=["x"]).compute_layout(w.project)
w.on_drag(pl[0].doc_id, pl[0].side, 0, 20.0, 200.0)
assert w.project.docs[0].front.pos == [0, 20.0, 200.0]
w.undo(); assert w.project.docs[0].front.pos is None
w.redo(); w.auto_arrange(); assert w.project.docs[0].front.pos is None
w.toggle_orient(); w.toggle_orient()
dlg = ImageEditor(w.project.docs[0].front.path, Edit(), 8.6/5.6, w); dlg._rot(); dlg._fit_frame(); dlg.s_bri.setValue(20); dlg.c_bw.setChecked(True)
w.project.docs[0].front.edit = dlg.edit; w.refresh_preview()
p = os.path.join(tmp, "p.iqproj"); w._save_to(p); w._load_into(__import__("core.project_io", fromlist=["x"]).load_project(p), p)
assert len(w.project.docs) == 3 and w.project.docs[0].front.edit.rot90 == 90
app.processEvents(); w.grab().save("/home/claude/ui_shot.png"); print("UI OK")
# --- تعرّف ذكي ---
import shutil
w2 = MainWindow(); w2.add_doc(); d = w2.project.docs[0]
shutil.copy("/tmp/tilt.jpg", os.path.join(tmp, "tilt.jpg")); d.front.path = os.path.join(tmp, "tilt.jpg")
w2.smart_all.__func__  # موجود
assert w2._auto_detect(d.front) and d.front.edit.quad
dlg = ImageEditor(d.front.path, d.front.edit, 8.6/5.6, w2); dlg._flip(); dlg._smart(); dlg.grab().save("/home/claude/editor_shot.png")
print("SMART OK")
