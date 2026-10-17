"""رسم الصفحات بالدقة المطلوبة وتصدير PDF / PNG / JPG بأبعاد حقيقية."""
import os
from PIL import Image
from . import imaging, layout


def mm_px(mm, dpi):
    return round(mm / 25.4 * dpi)


def missing_files(project):
    return [s.path for d in project.docs for s in (d.front, d.back)
            if s.path and not os.path.isfile(s.path)]


def render_page(project, placements, page, dpi):
    pw, ph = layout.page_dims(project.orientation)
    canvas = Image.new("RGB", (mm_px(pw, dpi), mm_px(ph, dpi)), "white")
    for p in placements:
        if p.page != page:
            continue
        side = project.find(p.doc_id).side(p.side)
        x0, y0 = mm_px(p.x, dpi), mm_px(p.y, dpi)
        x1, y1 = mm_px(p.x + p.w, dpi), mm_px(p.y + p.h, dpi)
        canvas.paste(imaging.render_side(side, max(1, x1 - x0), max(1, y1 - y0)), (x0, y0))
    return canvas


def render_pages(project, dpi, only_page=None):
    placements, n = layout.compute_layout(project)
    idx = [only_page] if only_page is not None else range(n)
    for i in idx:
        yield render_page(project, placements, i, dpi)


def export_pdf(project, path, dpi, only_page=None):
    pages = list(render_pages(project, dpi, only_page))
    pages[0].save(path, "PDF", resolution=float(dpi), save_all=True,
                  append_images=pages[1:], quality=95)
    return len(pages)


def export_images(project, path, dpi, fmt, only_page=None):
    """يحفظ صفحة واحدة باسم الملف المختار، وعند تعدد الصفحات يضيف _2 _3 ..."""
    fmt = fmt.upper()
    base, ext = os.path.splitext(path)
    ext = ext or ("." + fmt.lower())
    saved = []
    for i, page in enumerate(render_pages(project, dpi, only_page)):
        target = path if i == 0 else f"{base}_{i + 1}{ext}"
        if fmt in ("JPG", "JPEG"):
            page.save(target, "JPEG", quality=95, dpi=(dpi, dpi), subsampling=0)
        else:
            page.save(target, "PNG", dpi=(dpi, dpi))
        saved.append(target)
    return saved
