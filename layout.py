"""الترتيب التلقائي على ورقة A4 دون تداخل، مع دعم المواضع اليدوية."""
from dataclasses import dataclass
from collections import defaultdict

EPS = 1e-6


def page_dims(orientation):
    return (297.0, 210.0) if orientation == "L" else (210.0, 297.0)


@dataclass
class Placement:
    doc_id: str
    side: str
    page: int
    x: float
    y: float
    w: float
    h: float


def is_free(rects, x, y, w, h, gap=0.0):
    for rx, ry, rw, rh in rects:
        if not (x + w + gap <= rx + EPS or rx + rw + gap <= x + EPS or
                y + h + gap <= ry + EPS or ry + rh + gap <= y + EPS):
            return False
    return True


def _find_spot(rects, w, h, margin, gap, pw, ph):
    xs = {margin, pw - margin - w}
    ys = {margin}
    for rx, ry, rw, rh in rects:
        xs.update((rx - gap - w, rx + rw + gap))
        ys.update((ry + rh + gap, ry))
    cands = [(y, -x) for y in ys for x in xs
             if x >= margin - EPS and y >= margin - EPS and
             x + w <= pw - margin + EPS and y + h <= ph - margin + EPS]
    for y, nx in sorted(cands):
        if is_free(rects, -nx, y, w, h, gap):
            return -nx, y
    return None


def compute_layout(project):
    """يعيد (قائمة المواضع، عدد الصفحات). الوجه يوضع يمين الظهر (ترتيب RTL)."""
    pw, ph = page_dims(project.orientation)
    m, gap = project.margin_mm, project.gap_mm
    pages = defaultdict(list)
    out, flow = [], []
    for doc in project.docs:
        for name in ("front", "back"):
            side = doc.side(name)
            if not side.path:
                continue
            w, h = doc.w_cm * 10, doc.h_cm * 10
            if side.pos:
                pg, x, y = int(side.pos[0]), float(side.pos[1]), float(side.pos[2])
                if x >= -EPS and y >= -EPS and x + w <= pw + EPS and y + h <= ph + EPS \
                        and is_free(pages[pg], x, y, w, h):
                    pages[pg].append((x, y, w, h))
                    out.append(Placement(doc.id, name, pg, x, y, w, h))
                    continue
            flow.append((doc.id, name, w, h))
    for doc_id, name, w, h in flow:
        pg = 0
        while True:
            spot = _find_spot(pages[pg], w, h, m, gap, pw, ph)
            if spot is None and not pages[pg]:
                # أكبر من المساحة داخل الهوامش (مثل ورقة A4 كاملة): يوضع في وسط الصفحة إن كان يتسع للورقة
                if w <= pw + EPS and h <= ph + EPS:
                    spot = (max(0.0, (pw - w) / 2), max(0.0, (ph - h) / 2))
                else:
                    spot = (m, m)
            if spot:
                pages[pg].append((spot[0], spot[1], w, h))
                out.append(Placement(doc_id, name, pg, spot[0], spot[1], w, h))
                break
            pg += 1
    n = max([p.page for p in out], default=0) + 1
    return out, n
