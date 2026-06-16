"""Video clip model and abstract video source."""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod


@dataclasses.dataclass
class VideoClip:
    url: str
    label: str = ""


class VideoSource(ABC):
    @abstractmethod
    def get_videos(self) -> list[VideoClip]: ...
