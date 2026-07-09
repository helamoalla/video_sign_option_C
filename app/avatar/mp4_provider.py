from pathlib import Path
from app.video_editor import build_avatar_video


class MP4AvatarProvider:
    def generate(self, text: str, language: str, output_path: str):
        glosses = [g.strip().lower() for g in text.split() if g.strip()]

        videos_dir = Path("app/avatar/videos") / language

        final_path, missing = build_avatar_video(
            words=glosses,
            videos_dir=videos_dir,
            output_path=output_path,
        )

        return final_path