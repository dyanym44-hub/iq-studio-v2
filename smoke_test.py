"""اختبار آلي: الترتيب، الأبعاد الحقيقية في PDF/PNG/JPG، حفظ وفتح المشروع."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image, ImageDraw
from core.models import Project, Doc
from core import layout, exporter, project_io

tmp = tempfile.mkdtemp()
def mk(name, color, size=(1600, 1000)):
    p = os.path.join(tmp, name); im = Image.new("RGB", size, color)
    ImageDraw.Draw(im).rectangle((20, 20, size[0]-20, size[1]-20), outline="black", width=10); im.save(p); return p

proj = Project()
for i in range(7):
    d = Doc(kind=f"d{i}"); d.front.path = mk(f"f{i}.jpg", (200, 100+i*20, 100)); d.back.path = mk(f"b{i}.png", (100, 200, 100+i*20))
    proj.docs.append(d)
pl, n = layout.compute_layout(proj)
print("placements", len(pl), "pages", n)
for a in pl:
    assert a.x >= proj.margin_mm - 1e-6 and a.x + a.w <= 210 - proj.margin_mm + 1e-6, a
    assert a.y >= proj.margin_mm - 1e-6 and a.y + a.h <= 297 - proj.margin_mm + 1e-6, a
    for b in pl:
        if a is not b and a.page == b.page:
            assert layout.is_free([(b.x, b.y, b.w, b.h)], a.x, a.y, a.w, a.h), (a, b)
for dpi in (300, 600):
    pdf = os.path.join(tmp, f"o{dpi}.pdf"); exporter.export_pdf(proj, pdf, dpi)
    import fitz
    doc = fitz.open(pdf); r = doc[0].rect
    print(dpi, "PDF pages", len(doc), "size mm", round(r.width/72*25.4, 2), round(r.height/72*25.4, 2))
    assert abs(r.width/72*25.4-210) < 0.5 and abs(r.height/72*25.4-297) < 0.5
png = exporter.export_images(proj, os.path.join(tmp, "x.png"), 300, "PNG")
im = Image.open(png[0]); print("PNG", im.size, im.info.get("dpi")); assert im.size == (2480, 3508)
jp = exporter.export_images(proj, os.path.join(tmp, "x.jpg"), 600, "JPG", only_page=0)
print("JPG", Image.open(jp[0]).size); assert Image.open(jp[0]).size == (4961, 7016)
p0 = pl[0]; assert abs(exporter.mm_px(p0.w, 300) - 1016) <= 1
pp = os.path.join(tmp, "t.iqproj"); project_io.save_project(proj, pp)
p2 = project_io.load_project(pp)
assert len(p2.docs) == 7 and all(os.path.isfile(d.front.path) for d in p2.docs) and p2.docs[0].w_cm == 8.6
print("ALL OK")
