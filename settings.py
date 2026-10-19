import json
from pathlib import Path

DIR = Path.home() / ".iq_studio"
FILE = DIR / "settings.json"
DEFAULTS = {
    "app_title": "منظومة الهويات والمستمسكات IQ",
    "library_name": "",
    "logo": "",
    "socials": [{"label": "تيليغرام", "url": ""}, {"label": "إنستغرام", "url": ""},
                {"label": "تيك توك", "url": ""}, {"label": "واتساب", "url": ""}],
    "card_w_cm": 8.6, "card_h_cm": 5.6,
    "margin_mm": 10.0, "gap_mm": 4.0,
    "export_dpi": 300, "export_folder": "", "export_format": "JPG",
    "autosave": False,
    "auto_detect": True,
    "auto_open_editor": True,
}


def load():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        s.update(json.loads(FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def save(s):
    DIR.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
