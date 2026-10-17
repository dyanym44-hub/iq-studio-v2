"""معالجة الصور: تدوير، قص، سطوع/تباين، أبيض وأسود، تحسين. لا تُضاف أي بيانات للصورة."""
import os
from functools import lru_cache
from PIL import Image, ImageOps, ImageEnhance, ImageFilter


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


@lru_cache(maxsize=8)
def _load(path, mtime, max_side):
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def check_image(path):
    """يتأكد أن الملف موجود وأنه صورة صالحة (يرفع استثناء إن لم يكن)."""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(path or "")
    with Image.open(path) as im:
        im.verify()


def rotated_image(path, edit, max_side=None):
    """الصورة بعد التدوير وتصحيح الميلان فقط (قبل القص) — هي الأساس الذي يُقاس عليه القص."""
    img = _load(path, _mtime(path), max_side)
    if edit.rot90 % 360:
        img = img.rotate(-(edit.rot90 % 360), expand=True)
    if abs(edit.angle) > 0.01:
        img = img.rotate(-edit.angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
    return img


def adjust(img, edit):
    if edit.enhance:
        img = ImageOps.autocontrast(img, cutoff=1)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=3))
    if edit.brightness:
        img = ImageEnhance.Brightness(img).enhance(1 + edit.brightness / 100)
    if edit.contrast:
        img = ImageEnhance.Contrast(img).enhance(1 + edit.contrast / 100)
    if edit.bw:
        img = img.convert("L").convert("RGB")
    return img


def cover_crop(img, ratio):
    """قص مركزي إلى نسبة الإطار دون تشويه."""
    w, h = img.size
    if w / h > ratio:
        nw = round(h * ratio)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = round(w / ratio)
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def _persp_coeffs(src, w, h):
    """معاملات تحويل المنظور: تربط زوايا المستطيل الناتج بزوايا الهوية في الصورة."""
    import numpy as np
    A, B = [], []
    for (x, y), (X, Y) in zip(((0, 0), (w, 0), (w, h), (0, h)), src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); B.append(X)
        A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y]); B.append(Y)
    return tuple(np.linalg.solve(np.array(A, float), np.array(B, float)))


def render_side(side, w_px, h_px, max_side=None):
    """يعيد الصورة النهائية بالحجم المطلوب بالبكسل تمامًا."""
    img = rotated_image(side.path, side.edit, max_side)
    if side.edit.quad:      # هوية محددة بأربع زوايا: قص + تعديل الميلان والمنظور
        W, H = img.size
        pts = [(x * W, y * H) for x, y in side.edit.quad]
        qw = max(((pts[1][0] - pts[0][0]) ** 2 + (pts[1][1] - pts[0][1]) ** 2) ** .5,
                 ((pts[2][0] - pts[3][0]) ** 2 + (pts[2][1] - pts[3][1]) ** 2) ** .5)
        s = 2 if qw > 2 * w_px else 1
        out = img.transform((w_px * s, h_px * s), Image.PERSPECTIVE,
                            _persp_coeffs(pts, w_px * s, h_px * s), Image.BICUBIC, fillcolor=(255, 255, 255))
        if s != 1:
            out = out.resize((w_px, h_px), Image.LANCZOS)
        return adjust(out, side.edit)
    l, t, r, b = side.edit.crop
    W, H = img.size
    box = (round(l * W), round(t * H), max(round(r * W), round(l * W) + 1), max(round(b * H), round(t * H) + 1))
    if box != (0, 0, W, H):
        img = img.crop(box)
    img = cover_crop(img, w_px / h_px)
    img = img.resize((w_px, h_px), Image.LANCZOS)
    return adjust(img, side.edit)
