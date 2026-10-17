"""التعرف الذكي على أطراف الهوية أو ورقة A4 في الصورة (مائلة، بمنظور، خلفية مشوشة).

الفكرة: عدة طرق لاستخراج الشكل (حواف، فرق عن الخلفية، سطوع، GrabCut)، ثم تقدير أربع زوايا لكل مرشّح،
وتدقيقها بمطابقة أربعة خطوط على الحافة الفعلية، ثم اختيار الأفضل بحسب: المساحة، شبه المستطيل،
تطابق النسبة مع إطار البطاقة/الورقة، وقوة الحافة الفعلية على الصورة.
"""
import math
import numpy as np
from . import imaging
from .models import Edit


def _order(pts):
    """ترتيب الزوايا: أعلى-يسار، أعلى-يمين، أسفل-يمين، أسفل-يسار."""
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]
    return np.roll(pts, -int(np.argmin(pts.sum(axis=1))), axis=0)


def _edges(q):
    top = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    side = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return top, side


def _orient(q, landscape=True):
    """الضلع الطويل أفقي (landscape) أو عمودي حسب شكل الإطار المطلوب."""
    top, side = _edges(q)
    if side > top:
        q = np.roll(q, -1, axis=0)
    if not landscape:
        q = np.roll(q, -1, axis=0)
    return q


def _ratio(q):
    a, b = _edges(q)
    return max(a, b) / max(1e-6, min(a, b))


def _aspect_score(est, hint):
    if hint:
        hl = max(hint, 1 / hint)
        return math.exp(-(math.log(est / hl) / 0.22) ** 2)
    return 1.0 if 1.2 <= est <= 2.2 else 0.5


def _quad_from_contour(cv2, cnt):
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.015, 0.025, 0.04):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return ap.reshape(4, 2).astype(np.float32)
    return cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)


def _refine(cv2, q, cnt, diag):
    """يدقّق الزوايا: يطابق خطًا على كل ضلع من نقاط الحافة الفعلية ويأخذ تقاطعها
    (يعالج الزوايا المستديرة للبطاقات وتشوّه المنظور)."""
    pts = cnt.reshape(-1, 2).astype(np.float32)
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        e = b - a
        L = float(np.linalg.norm(e))
        if L < 1:
            return q
        t = e / L
        rel = pts - a
        along = rel @ t
        dist = np.abs(rel @ np.array([-t[1], t[0]], np.float32))
        m = (dist < 0.03 * diag) & (along > 0.12 * L) & (along < 0.88 * L)
        if m.sum() < 8:
            return q
        vx, vy, x0, y0 = cv2.fitLine(pts[m], cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    out = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-3:
            return q
        s = np.linalg.solve(A, p2 - p1)
        out.append(p1 + s[0] * d1)
    out = np.array(out, np.float32)
    if np.linalg.norm(out - q, axis=1).max() > 0.06 * diag:
        return q
    if not cv2.isContourConvex(out.reshape(-1, 1, 2)):
        return q
    return out


def _edge_support(gray, q):
    """نسبة نقاط الحافة التي فيها فرق حقيقي بين الداخل والخارج (تميّز الحافة الحقيقية)."""
    h, w = gray.shape
    c = q.mean(axis=0)
    n = good = 0
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        e = b - a
        L = float(np.linalg.norm(e))
        if L < 20:
            continue
        t = e / L
        nrm = np.array([-t[1], t[0]])
        if np.dot(nrm, c - a) < 0:
            nrm = -nrm
        for s in np.linspace(0.1, 0.9, 40):
            p = a + e * s
            xi, yi = (int(round(v)) for v in p + nrm * 6)
            xo, yo = (int(round(v)) for v in p - nrm * 6)
            if not (0 <= xi < w and 0 <= yi < h and 0 <= xo < w and 0 <= yo < h):
                continue
            n += 1
            good += abs(int(gray[yi, xi]) - int(gray[yo, xo])) > 10
    return good / n if n > 20 else 0.0


def _masks(cv2, bgr, gray_s):
    h, w = gray_s.shape
    k5 = np.ones((5, 5), np.uint8)
    for lo, hi in ((20, 70), (40, 120), (70, 190)):                   # الحواف
        e = cv2.Canny(gray_s, lo, hi)
        e = cv2.dilate(e, np.ones((3, 3), np.uint8), iterations=2)
        yield cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)     # الفرق عن لون الخلفية
    k = max(4, min(h, w) // 40)
    border = np.concatenate([lab[:k].reshape(-1, 3), lab[-k:].reshape(-1, 3),
                             lab[:, :k].reshape(-1, 3), lab[:, -k:].reshape(-1, 3)])
    diff = cv2.GaussianBlur(np.linalg.norm(lab - np.median(border, axis=0), axis=2), (7, 7), 0)
    d8 = np.clip(diff * 3, 0, 255).astype(np.uint8)
    for thr in (cv2.threshold(d8, 0, 255, cv2.THRESH_OTSU)[0], 30, 60):
        m = ((d8 > max(24, thr)) * 255).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8))
        yield cv2.morphologyEx(m, cv2.MORPH_OPEN, k5)
    t = cv2.threshold(gray_s, 0, 255, cv2.THRESH_OTSU)[0]            # السطوع (ورقة فاتحة أو بطاقة داكنة)
    for inv in (False, True):
        m = ((gray_s <= t) if inv else (gray_s > t)).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((13, 13), np.uint8))
        yield cv2.morphologyEx(m, cv2.MORPH_OPEN, k5)


def _grabcut_contours(cv2, bgr):
    """احتياطي للحالات الصعبة: GrabCut على نسخة مصغّرة."""
    h, w = bgr.shape[:2]
    s = 480 / max(h, w)
    small = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))))
    sh, sw = small.shape[:2]
    m = int(0.05 * min(sh, sw))
    mask = np.zeros((sh, sw), np.uint8)
    cv2.grabCut(small, mask, (m, m, sw - 2 * m, sh - 2 * m), np.zeros((1, 65)), np.zeros((1, 65)), 4,
                cv2.GC_INIT_WITH_RECT)
    fg = (((mask == 1) | (mask == 3)) * 255).astype(np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:2]:
        yield (c.astype(np.float32) / s).astype(np.int32)


def _best(cv2, gray_s, contours, w, h, ratio, best, best_score):
    diag = math.hypot(w, h)
    for c in contours:
        q = _quad_from_contour(cv2, c)
        q = _refine(cv2, _order(q), c, diag)
        qa = cv2.contourArea(q.astype(np.float32))
        frac = qa / (w * h)
        if qa <= 0 or frac < 0.10 or frac > 0.97:
            continue
        o = _orient(_order(q), landscape=(ratio is None or ratio >= 1))
        rect = min(1.0, cv2.contourArea(c) / qa)
        sup = _edge_support(gray_s, o)
        score = (frac ** 0.5) * rect * _aspect_score(_ratio(o), ratio) * (0.5 + 0.5 * sup)
        if score > best_score:
            best, best_score = o, score
    return best, best_score


def find_quad(bgr, ratio=None):
    """يعيد (زوايا الهدف كنسب من الصورة، الثقة) أو None.
    ratio = عرض/ارتفاع الإطار المطلوب (يحدد شكل الورقة ووضعها عمودي/أفقي)."""
    import cv2
    h, w = bgr.shape[:2]
    gray_s = cv2.GaussianBlur(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    best, score = None, 0.0
    for mask in _masks(cv2, bgr, gray_s):
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        big = [c for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:4] if cv2.contourArea(c) > 0.08 * w * h]
        best, score = _best(cv2, gray_s, big, w, h, ratio, best, score)
    if score < 0.45:
        try:
            best, score = _best(cv2, gray_s, list(_grabcut_contours(cv2, bgr)), w, h, ratio, best, score)
        except Exception:
            pass
    if best is None or score < 0.3:
        return None
    return [[float(x / w), float(y / h)] for x, y in best], float(score)


def detect_quad(path, rot90=0, ratio=None):
    """يحلّل الصورة (بعد تدويرها rot90) ويعيد الزوايا الأربع كنسب، أو None إن لم يتعرف."""
    img = imaging.rotated_image(path, Edit(rot90=rot90), 1000)
    bgr = np.array(img)[:, :, ::-1].copy()
    r = find_quad(bgr, ratio)
    return r[0] if r else None
