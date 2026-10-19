"""التعرف الذكي السريع والدقيق على أطراف الهوية أو ورقة A4 (مائلة، بمنظور، خلفية مشوشة، ظلال).

المراحل:
 1) مرشّحون من أشكال الحواف وفرق اللون عن الخلفية (سريع).
 2) إذا لم تكفِ الثقة: مرشّحون من الخطوط المستقيمة الطويلة (Hough) — ينجح مع الخلفيات المشوشة.
 3) احتياطي: GrabCut على نسخة صغيرة.
 كل مرشّح يُقيَّم بـ: المساحة، تطابق النسبة مع الإطار، قوة الحافة الفعلية على الأضلاع الأربعة،
 وتباين اللون بين داخل الشكل وما حوله. ثم تُدقَّق الزوايا الأربع على الصورة الكاملة بمطابقة خط على كل ضلع.
"""
import math
import numpy as np
from . import imaging
from .models import Edit

WORK = 560      # أكبر بُعد للبحث (للسرعة)


# ---------------- هندسة ----------------
def _order(pts):
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    pts = pts[np.argsort(np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0]))]
    return np.roll(pts, -int(np.argmin(pts.sum(axis=1))), axis=0)


def _edges(q):
    return ((np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2,
            (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2)


def _orient(q, landscape=True):
    top, side = _edges(q)
    if side > top:
        q = np.roll(q, -1, axis=0)
    return q if landscape else np.roll(q, -1, axis=0)


def _ratio(q):
    a, b = _edges(q)
    return max(a, b) / max(1e-6, min(a, b))


def _aspect_score(est, hint):
    if hint:
        hl = max(hint, 1 / hint)
        return math.exp(-(math.log(est / hl) / 0.22) ** 2)
    return 1.0 if 1.2 <= est <= 2.2 else 0.5


# ---------------- التقييم ----------------
def _edge_support(lab, q, off):
    h, w = lab.shape[:2]
    c = q.mean(axis=0)
    n = good = 0
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        e = b - a
        L = float(np.linalg.norm(e))
        if L < 15:
            continue
        t = e / L
        nrm = np.array([-t[1], t[0]])
        if np.dot(nrm, c - a) < 0:
            nrm = -nrm
        s = np.linspace(0.08, 0.92, 36)[:, None]
        p = a + e * s
        pi_, po = np.rint(p + nrm * off).astype(int), np.rint(p - nrm * off).astype(int)
        ok = (pi_[:, 0] >= 0) & (pi_[:, 0] < w) & (pi_[:, 1] >= 0) & (pi_[:, 1] < h) & \
             (po[:, 0] >= 0) & (po[:, 0] < w) & (po[:, 1] >= 0) & (po[:, 1] < h)
        pi_, po = pi_[ok], po[ok]
        if len(pi_) == 0:
            continue
        d = np.linalg.norm(lab[pi_[:, 1], pi_[:, 0]].astype(np.float32) - lab[po[:, 1], po[:, 0]].astype(np.float32), axis=1)
        n += len(d)
        good += int((d > 8).sum())
    return good / n if n > 24 else 0.0


def _contrast(ctx, q):
    """تباين اللون (Lab) بين شريط ضيّق داخل الحافة وشريط ضيّق خارجها (على الحافة نفسها فقط).
    يرفض شبكات الأقمشة ونقوش الخلفية لأن جانبي «الحافة» فيها متشابهان."""
    cv2 = ctx["cv2"]
    h, w = ctx["h"], ctx["w"]
    m_in = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(m_in, np.rint(q).astype(np.int32), 1)
    g, bw = 2, max(3, int(0.012 * ctx["diag"]))

    def k(n):
        return np.ones((n, n), np.uint8)
    inner = cv2.erode(m_in, k(2 * g + 1)) - cv2.erode(m_in, k(2 * (g + bw) + 1))
    outer = cv2.dilate(m_in, k(2 * (g + bw) + 1)) - cv2.dilate(m_in, k(2 * g + 1))
    if inner.sum() < 20 or outer.sum() < 20:
        return 0.5
    mi, mo = np.array(cv2.mean(ctx["lab"], inner)[:3]), np.array(cv2.mean(ctx["lab"], outer)[:3])
    return min(1.0, float(np.linalg.norm(mi - mo)) / 20.0) ** 0.5


def _score(ctx, q, rect=1.0):
    cv2, w, h = ctx["cv2"], ctx["w"], ctx["h"]
    q = np.asarray(q, np.float32)
    qa = cv2.contourArea(q)
    frac = qa / (w * h)
    if qa <= 0 or frac < 0.035 or frac > 0.97:
        return 0.0, None
    if q[:, 0].min() < -0.02 * w or q[:, 0].max() > 1.02 * w or q[:, 1].min() < -0.02 * h or q[:, 1].max() > 1.02 * h:
        return 0.0, None
    if not cv2.isContourConvex(q.reshape(-1, 1, 2)):
        return 0.0, None
    o = _orient(_order(q), landscape=(ctx["ratio"] is None or ctx["ratio"] >= 1))
    ar = _aspect_score(_ratio(o), ctx["ratio"])
    if ar < 0.15:
        return 0.0, None
    sup = _edge_support(ctx["lab"], o, max(3, int(0.012 * ctx["diag"])))
    if sup < 0.3:
        return 0.0, None
    return (frac ** 0.5) * rect * ar * (0.35 + 0.65 * sup) * _contrast(ctx, o), o


# ---------------- المرشّحون ----------------
def _quad_from_contour(cv2, cnt):
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.015, 0.025, 0.04):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return ap.reshape(4, 2).astype(np.float32)
    return cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)


def _contour_quads(ctx):
    cv2, gray, bgr = ctx["cv2"], ctx["gray"], ctx["bgr"]
    h, w = gray.shape
    k5 = np.ones((5, 5), np.uint8)
    masks = []
    for lo, hi in ((25, 80), (60, 160)):
        e = cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8), iterations=2)
        masks.append(cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
    lab = ctx["lab"].astype(np.float32)
    k = max(3, min(h, w) // 40)
    border = np.concatenate([lab[:k].reshape(-1, 3), lab[-k:].reshape(-1, 3),
                             lab[:, :k].reshape(-1, 3), lab[:, -k:].reshape(-1, 3)])
    diff = cv2.GaussianBlur(np.linalg.norm(lab - np.median(border, axis=0), axis=2), (5, 5), 0)
    d8 = np.clip(diff * 3, 0, 255).astype(np.uint8)
    for thr in (cv2.threshold(d8, 0, 255, cv2.THRESH_OTSU)[0], 40):
        m = ((d8 > max(24, thr)) * 255).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        masks.append(cv2.morphologyEx(m, cv2.MORPH_OPEN, k5))
    t = cv2.threshold(gray, 0, 255, cv2.THRESH_OTSU)[0]
    for inv in (False, True):
        m = ((gray <= t) if inv else (gray > t)).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        masks.append(cv2.morphologyEx(m, cv2.MORPH_OPEN, k5))
    for mask in masks:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:3]:
            if cv2.contourArea(c) > 0.035 * w * h:
                q = _quad_from_contour(cv2, c)
                qa = cv2.contourArea(q)
                yield q, min(1.0, cv2.contourArea(c) / max(qa, 1))


def _intersect(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    A = np.array([d1, -d2]).T
    if abs(np.linalg.det(A)) < 1e-4:
        return None
    s = np.linalg.solve(A, p2 - p1)
    return p1 + s[0] * d1


def _line_quads(ctx):
    """مرشّحون من الخطوط الطويلة: يختار زوجين شبه متوازيين متعامدين تقريبًا ويقاطعهما."""
    cv2, gray = ctx["cv2"], ctx["gray"]
    h, w = gray.shape
    diag = ctx["diag"]
    edges = cv2.Canny(gray, 35, 110)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=45, minLineLength=int(0.2 * min(h, w)),
                           maxLineGap=int(0.03 * diag))
    if segs is None:
        return
    L = []
    for x1, y1, x2, y2 in segs.reshape(-1, 4):
        ln = math.hypot(x2 - x1, y2 - y1)
        d = np.array([x2 - x1, y2 - y1], float) / ln
        L.append((ln, np.array([x1, y1], float), d))
    L.sort(key=lambda t: -t[0])
    kept = []
    for ln, p, d in L:                                     # دمج الخطوط المتكررة
        dup = False
        for _, p2, d2 in kept:
            if abs(d @ d2) > math.cos(math.radians(4)) and abs((p - p2) @ np.array([-d2[1], d2[0]])) < 0.02 * diag:
                dup = True; break
        if not dup:
            kept.append((ln, p, d))
        if len(kept) >= 16:
            break
    pairs = []
    for i in range(len(kept)):
        for j in range(i + 1, len(kept)):
            _, p1, d1 = kept[i]; _, p2, d2 = kept[j]
            if abs(d1 @ d2) > math.cos(math.radians(18)):
                sep = abs((p2 - p1) @ np.array([-d1[1], d1[0]]))
                if sep > 0.12 * diag:
                    pairs.append(((p1, d1), (p2, d2), kept[i][0] + kept[j][0]))
    pairs.sort(key=lambda t: -t[2])
    pairs = pairs[:18]
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            (A1, A2, _), (B1, B2, _) = pairs[a], pairs[b]
            if abs(A1[1] @ B1[1]) > math.cos(math.radians(50)):
                continue
            pts = [_intersect(A1, B1), _intersect(A1, B2), _intersect(A2, B2), _intersect(A2, B1)]
            if any(p is None for p in pts):
                continue
            yield np.array(pts, np.float32), 1.0


def _grabcut_quads(ctx):
    cv2, bgr = ctx["cv2"], ctx["bgr"]
    h, w = bgr.shape[:2]
    s = 320 / max(h, w)
    small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    m = int(0.05 * min(sh, sw))
    mask = np.zeros((sh, sw), np.uint8)
    cv2.grabCut(small, mask, (m, m, sw - 2 * m, sh - 2 * m), np.zeros((1, 65)), np.zeros((1, 65)), 3,
                cv2.GC_INIT_WITH_RECT)
    fg = (((mask == 1) | (mask == 3)) * 255).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:2]:
        q = _quad_from_contour(cv2, c) / s
        yield q.astype(np.float32), min(1.0, cv2.contourArea(c) / s / s / max(cv2.contourArea(q.astype(np.float32)), 1))


# ---------------- التدقيق على الصورة الكاملة ----------------
def _refine_pass(cv2, lab, q, B, K=3, inner=1.0):
    """لكل ضلع: يبحث عن موضع الحافة الفعلي (أكبر قفزة لون) على امتداد العمود عند عدة نقاط، ثم يطابق خطًا."""
    h, w = lab.shape[:2]
    diag = math.hypot(w, h)
    c = q.mean(axis=0)
    offs = np.arange(-B - K, B + K + 1)
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        e = b - a
        L = float(np.linalg.norm(e))
        t = e / L
        nrm = np.array([-t[1], t[0]], np.float32)
        if np.dot(nrm, a - c) < 0:
            nrm = -nrm                                      # نحو الخارج
        base = a + e * np.linspace(0.12, 0.88, 48)[:, None]
        pos = base[:, None, :] + nrm[None, None, :] * offs[None, :, None]
        xi = np.clip(np.rint(pos[..., 0]).astype(int), 0, w - 1)
        yi = np.clip(np.rint(pos[..., 1]).astype(int), 0, h - 1)
        prof = lab[yi, xi]                                   # (48, n, 3)
        cs = np.concatenate([np.zeros((48, 1, 3), np.float32), np.cumsum(prof, axis=1)], axis=1)
        n = len(offs)
        j = np.arange(K, n - K)
        inside = (cs[:, j] - cs[:, j - K]) / K
        outside = (cs[:, j + K] - cs[:, j]) / K
        r = np.linalg.norm(outside - inside, axis=2)         # (48, len(j))
        r = r * (1 - 0.3 * np.abs(offs[j])[None, :] / max(B, 1))
        r[:, offs[j] < -inner * B] = 0                       # لا نبحث بعيدًا للداخل (إطارات داخلية في الهوية)
        jb = r.argmax(axis=1)
        strength = r[np.arange(48), jb]
        ok = strength > 7
        if ok.sum() < 18:
            return None
        pts = (base + nrm[None, :] * offs[j][jb][:, None])[ok].astype(np.float32)
        vx, vy, x0, y0 = cv2.fitLine(pts, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    out = []
    for i in range(4):
        p = _intersect(lines[i - 1], lines[i])
        if p is None:
            return None
        out.append(p)
    out = np.array(out, np.float32)
    if not cv2.isContourConvex(out.reshape(-1, 1, 2)):
        return None
    return out


def _refine_edges(cv2, bgr, q):
    h, w = bgr.shape[:2]
    diag = math.hypot(w, h)
    lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    cur = q
    big = max(5, int(0.02 * diag))
    for B, inner in ((big, 0.45), (big, 0.45), (big, 0.45), (max(3, int(0.006 * diag)), 1.0)):
        nxt = _refine_pass(cv2, lab, cur, B, inner=inner)
        if nxt is None or np.linalg.norm(nxt - q, axis=1).max() > 0.1 * diag:
            break
        cur = nxt
    return cur


# ---------------- الواجهة ----------------
def find_quad(bgr, ratio=None):
    """يعيد (زوايا الهدف كنسب من الصورة، الثقة) أو None.
    ratio = عرض/ارتفاع الإطار المطلوب (يحدد وضع الورقة عمودي/أفقي)."""
    import cv2
    H0, W0 = bgr.shape[:2]
    s = min(1.0, WORK / max(H0, W0))
    small = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr
    h, w = small.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    ctx = dict(cv2=cv2, bgr=small, gray=gray, lab=cv2.cvtColor(small, cv2.COLOR_BGR2LAB), w=w, h=h,
               diag=math.hypot(w, h), ratio=ratio)
    best, score = None, 0.0
    for stage, gen, stop in ((0, _contour_quads, 0.80), (1, _line_quads, 0.70), (2, _grabcut_quads, 0.0)):
        if stage == 2 and score >= 0.35:
            break
        try:
            for q, rect in gen(ctx):
                sc, o = _score(ctx, q, rect)
                if stage == 1:
                    sc *= 0.8                  # الخطوط أقل موثوقية من أشكال الحواف
                if sc > score:
                    best, score = o, sc
        except Exception:
            pass
        if score >= stop:
            break
    if best is None or score < 0.28:
        return None
    full = (best / s).astype(np.float32)
    ref = _refine_edges(cv2, bgr, full)
    sc_ref, _ = _score(ctx, ref * s, 1.0)
    sc_old, _ = _score(ctx, full * s, 1.0)
    if sc_ref >= 0.9 * sc_old:
        full = ref
    c = full.mean(axis=0)
    full = c + (full - c) * 0.994                          # إزاحة طفيفة للداخل لتفادي حافة الخلفية
    return [[float(x / W0), float(y / H0)] for x, y in full], float(score)


def detect_quad(path, rot90=0, ratio=None):
    """يحلّل الصورة (بعد تدويرها rot90) ويعيد الزوايا الأربع كنسب، أو None إن لم يتعرف."""
    img = imaging.rotated_image(path, Edit(rot90=rot90), 1000)
    bgr = np.array(img)[:, :, ::-1].copy()
    r = find_quad(bgr, ratio)
    return r[0] if r else None
