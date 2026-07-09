from pathlib import Path
import json


def save_manifest(
    session_dir,
    session_id,
    video_url,
    original_language,
    original_text,
    translations,
    subtitles,
    avatars,
    avatar_debug,
    rendered_videos=None,
):
    import json

    manifest = {
        "session_id": session_id,
        "video_url": video_url,
        "original_language": original_language,
        "original_text": original_text,
        "translations": translations,
        "subtitles": subtitles,
        "avatars": avatars,
        "avatar_debug": avatar_debug,
        "rendered_videos": rendered_videos or {},
        "default": {
            "rendered_video": next(iter(rendered_videos), None) if rendered_videos else None
        },
    }

    path = session_dir / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest, path