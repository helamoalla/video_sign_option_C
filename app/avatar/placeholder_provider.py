import shutil
from pathlib import Path
from app.avatar.base import AvatarProvider


class PlaceholderAvatarProvider(AvatarProvider):
    def generate(
    self,
    text: str,
    language: str,
    output_path: str,
    glosses: list[str] | None = None,
) -> str:
        placeholder = Path("static/avatar_placeholder.mp4")

        if not placeholder.exists():
            raise FileNotFoundError(
                "Add your test avatar video here: static/avatar_placeholder.mp4"
            )

        shutil.copy(placeholder, output_path)
        return output_path