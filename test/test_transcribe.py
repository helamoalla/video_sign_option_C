from pathlib import Path
from app.transcribe import transcribe_video

file_path = Path("audio_sign/SGN-010.mp3")  # change to your file

result = transcribe_video(str(file_path))

print("LANGUAGE:", result["language"])
print("TEXT:", result["text"])
print("SEGMENTS:")
for seg in result["segments"]:
    print(seg["start"], "→", seg["end"], ":", seg["text"])