from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ImageRecord:
    ordinal: int
    path: Path
    content_index: int | str = ""
    mineru_type: str = ""
    mineru_sub_type: str = ""
    caption: str = ""
    content: str = ""
