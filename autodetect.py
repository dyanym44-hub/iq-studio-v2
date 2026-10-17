"""التعرف الذكي على أطراف الهوية في الصورة (حتى لو مائلة أو مصوّرة بزاوية)."""
import numpy as np
from . import imaging
from .models import Edit


def _order(pts):
    """ترتيب الزوايا: أعلى-يسار، أعلى-يمين، أسفل-يمين، أسفل-يسار."""
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]                      # باتجاه عقارب الساعة (محور y للأسفل)
    start = int(np.argmin(pts.sum(axis=1)))
    return np.roll(pts, -start, axis=0)


def _long_side_on_top(q):
    top = np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])
    side = np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])
    return np.roll(q, -1, axis=0) if side > top else q


def _quad_from_contour(cv2, cnt):
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.015, 0.025, 0.04):
        ap = cv2.approxPolyDP(hull, eps * peri, True)
        if len(ap) == 4:
            return ap.reshape(4, 2)
    return cv2.boxPoints(cv2.minAreaRect(hull))


def _candidates(cv2, bgr):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    masks = []
    for lo, hi in ((25, 80), (50, 150)):                       # الحواف
        e = cv2.Canny(blur, lo, hi)
        e = cv2.dilate(e, np.ones((3, 3), np.uint8), iterations=2)
        masks.append(cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)))
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)   # الفرق عن لون الخلفية
    k = max(4, min(h, w) // 40)
    border = np.concatenate([lab[:k].reshape(-1, 3), lab[-k:].reshape(-1, 3),
                             lab[:, :k].reshape(-1, 3), lab[:, -k:].reshape(-1, 3)])
    diff = cv2.GaussianBlur(np.linalg.norm(lab - np.median(border, axis=0), axis=2), (7, 7), 0)
    d8 = np.clip(diff, 0, 255).astype(np.uint8)
    thr = max(14, cv2.threshold(d8, 0, 255, cv2.THRESH_OTSU)[0])
    m = ((d8 > thr) * 255).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    masks.append(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)))
    for mask in masks:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:4]:
            if cv2.contourArea(c) > 0.08 * w * h:
                yield c


def find_quad(bgr):
    """يعيد (زوايا الهوية كنسب من الصورة، الثقة) أو None."""
    import cv2
    h, w = bgr.shape[:2]
    best, best_score = None, 0.0
    for c in _candidates(cv2, bgr):
        q = _quad_from_contour(cv2, c)
        qa = cv2.contourArea(q.astype(np.float32))
        frac = qa / (w * h)
        if frac < 0.12 or frac > 0.96 or qa <= 0:
            continue
        rect = min(1.0, cv2.contourArea(c) / qa)
        o = _long_side_on_top(_order(q))
        ratio = np.linalg.norm(o[1] - o[0]) / max(1e-6, np.linalg.norm(o[3] - o[0]))
        ar = 1.0 if 1.2 <= ratio <= 2.2 else 0.6
        score = (frac ** 0.5) * rect * ar
        if score > best_score:
            best, best_score = o, score
    if best is None or best_score < 0.3:
        return None
    return [[float(x / w), float(y / h)] for x, y in best], best_score


def detect_quad(path, rot90=0):
    """يحلّل الصورة (بعد تدويرها rot90) ويعيد الزوايا الأربع كنسب، أو None إن لم يتعرف."""
    img = imaging.rotated_image(path, Edit(rot90=rot90), 1000)
    bgr = np.array(img)[:, :, ::-1].copy()
    r = find_quad(bgr)
    return r[0] if r else None
