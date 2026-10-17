"""نماذج البيانات: المشروع والمستندات وتعديلات الصور."""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

SIDES = ("front", "back")
SIDE_NAMES = {"front": "الوجه", "back": "الظهر"}


@dataclass
class Edit:
    rot90: int = 0                      # 0/90/180/270 باتجاه عقارب الساعة
    angle: float = 0.0                  # تصحيح الميلان بالدرجات
    crop: list = field(default_factory=lambda: [0.0, 0.0, 1.0, 1.0])  # l,t,r,b
    brightness: int = 0                 # -100..100
    contrast: int = 0                   # -100..100
    bw: bool = False
    enhance: bool = False
    quad: Optional[list] = None         # 4 زوايا للهوية (نسب) — تصحيح المنظور

    def key(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    def copy(self) -> "Edit":
        return Edit.from_dict(asdict(self))

    @classmethod
    def from_dict(cls, d) -> "Edit":
        e = cls()
        for k, v in (d or {}).items():
            if hasattr(e, k):
                setattr(e, k, v)
        e.crop = list(e.crop)
        if e.quad: e.quad = [list(p) for p in e.quad]
        return e


@dataclass
class Side:
    path: Optional[str] = None
    edit: Edit = field(default_factory=Edit)
    pos: Optional[list] = None          # [page, x_mm, y_mm] عند النقل اليدوي

    def to_dict(self):
        return {"path": self.path, "edit": asdict(self.edit), "pos": self.pos}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("path"), Edit.from_dict(d.get("edit")), d.get("pos"))


@dataclass
class Doc:
    kind: str = "مستمسك"
    w_cm: float = 8.6
    h_cm: float = 5.6
    front: Side = field(default_factory=Side)
    back: Side = field(default_factory=Side)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def side(self, name: str) -> Side:
        return getattr(self, name)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "w_cm": self.w_cm, "h_cm": self.h_cm,
                "front": self.front.to_dict(), "back": self.back.to_dict()}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("kind", "مستمسك"), float(d.get("w_cm", 8.6)), float(d.get("h_cm", 5.6)),
                   Side.from_dict(d.get("front", {})), Side.from_dict(d.get("back", {})),
                   d.get("id") or uuid.uuid4().hex[:10])


@dataclass
class Project:
    docs: list = field(default_factory=list)
    orientation: str = "P"              # P عمودي / L أفقي
    margin_mm: float = 10.0
    gap_mm: float = 4.0

    def find(self, doc_id: str) -> Optional[Doc]:
        return next((d for d in self.docs if d.id == doc_id), None)

    def to_dict(self):
        return {"version": 1, "orientation": self.orientation, "margin_mm": self.margin_mm,
                "gap_mm": self.gap_mm, "docs": [d.to_dict() for d in self.docs]}

    @classmethod
    def from_dict(cls, d):
        return cls([Doc.from_dict(x) for x in d.get("docs", [])], d.get("orientation", "P"),
                   float(d.get("margin_mm", 10)), float(d.get("gap_mm", 4)))
