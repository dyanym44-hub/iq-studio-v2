"""حفظ المشروع وفتحه: ملف .iqproj (zip) يحوي JSON + نسخ الصور، فلا تضيع الصور أبدًا."""
import hashlib, json, os, shutil, tempfile, zipfile
from pathlib import Path
from .models import Project

EXT = ".iqproj"


def cache_root():
    p = Path.home() / ".iq_studio" / "opened"
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_project(project, path):
    data = project.to_dict()
    tmp = path + ".tmp"           # الكتابة إلى ملف مؤقت أولاً حتى لا يتلف الملف القديم
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        names = {}
        for d in data["docs"]:
            for s in ("front", "back"):
                src = d[s]["path"]
                if not src:
                    continue
                if src not in names:
                    if not os.path.isfile(src):
                        raise FileNotFoundError(src)
                    with open(src, "rb") as f:
                        h = hashlib.md5(f.read()).hexdigest()[:10]
                    names[src] = f"images/{h}_{os.path.basename(src)}"
                    z.write(src, names[src])
                d[s]["path"] = names[src]
        z.writestr("project.json", json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def load_project(path):
    if not zipfile.is_zipfile(path):
        raise ValueError("الملف ليس مشروعًا صالحًا")
    dest = tempfile.mkdtemp(dir=cache_root())
    with zipfile.ZipFile(path) as z:
        z.extractall(dest)
    with open(os.path.join(dest, "project.json"), encoding="utf-8") as f:
        data = json.load(f)
    for d in data["docs"]:
        for s in ("front", "back"):
            if d[s]["path"]:
                d[s]["path"] = os.path.join(dest, d[s]["path"])
    return Project.from_dict(data)


def clean_cache(keep=5):
    dirs = sorted(cache_root().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in dirs[keep:]:
        shutil.rmtree(p, ignore_errors=True)
