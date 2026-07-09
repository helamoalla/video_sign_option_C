from pathlib import Path
import json

def format_srt_time(seconds):
    milliseconds = int((seconds % 1) * 1000)
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def format_vtt_time(seconds):
    return format_srt_time(seconds).replace(",", ".")


def generate_subtitles(result, output_dir: Path, file_id: str):
    output_dir.mkdir(parents=True, exist_ok=True)

    segments = [
        {
            "id": i,
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "text": seg["text"].strip()
        }
        for i, seg in enumerate(result["segments"], start=1)
    ]

    data = {
        "language": result["language"],
        "text": result["text"],
        "video_path": f"videos/{file_id}.mp4",
        "segments": segments
    }

    json_path = output_dir / "subtitles.json"
    srt_path = output_dir / "subtitles.srt"
    vtt_path = output_dir / "subtitles.vtt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    with open(srt_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"{seg['id']}\n")
            f.write(f"{format_srt_time(seg['start'])} --> {format_srt_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")

    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{format_vtt_time(seg['start'])} --> {format_vtt_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")

    return {
        "data": data,
        "json_path": str(json_path),
        "srt_path": str(srt_path),
        "vtt_path": str(vtt_path)
    }