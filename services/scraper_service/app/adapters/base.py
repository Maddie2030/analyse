from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any



@dataclass
class AdapterResult:
    title: str | None
    summary: str | None
    result: dict[str, Any]


class SourceAdapter(ABC):
    name = "base"

    @abstractmethod
    def matches(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def extract(
        self,
        url: str,
        html: str,
        mode: str,
    ) -> AdapterResult:
        raise NotImplementedError
