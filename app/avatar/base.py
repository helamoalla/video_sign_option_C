from abc import ABC, abstractmethod


class AvatarProvider(ABC):
    @abstractmethod
    def generate(
        self,
        text: str,
        language: str,
        output_path: str,
        glosses: list[str] | None = None,
    ) -> str:
        pass