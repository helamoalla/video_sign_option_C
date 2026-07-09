from pathlib import Path
from app.transcribe import transcribe_video
from app.subtitles import generate_subtitles

file_path = Path("audio_sign/SGN-010.mp3")

result = transcribe_video(str(file_path))

subtitle_result = generate_subtitles(
    result=result,
    output_dir=Path("outputs/test_subtitles"),
    file_id="test"
)

print(subtitle_result["data"])
print("JSON:", subtitle_result["json_path"])
print("SRT:", subtitle_result["srt_path"])
print("VTT:", subtitle_result["vtt_path"])