import base64
import json
from pathlib import Path

SESSION_ID = "9354ae04-1198-48b3-9579-566c2a839666" #put your session id here before executing the script
SESSION_DIR = Path("outputs") / SESSION_ID
MANIFEST_PATH = SESSION_DIR / "manifest.json"
OUTPUT_HTML = SESSION_DIR / "offline_player.html"


def to_base64_video(path: Path):
    data = path.read_bytes()
    return "data:video/mp4;base64," + base64.b64encode(data).decode("utf-8")


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rendered = manifest.get("rendered_videos", {})

    videos = {}

    for key, url in rendered.items():
        local_path = SESSION_DIR / url.replace(f"/outputs/{SESSION_ID}/", "")
        if local_path.exists():
            videos[key] = to_base64_video(local_path)

    buttons = "\n".join([
        f'<button onclick="loadVideo(\'{key}\')">{key.replace("_", " / ").upper()}</button>'
        for key in videos
    ])

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CYRKIL Offline Player</title>
<style>
body {{
  background:#111;
  color:white;
  font-family:Arial;
  text-align:center;
}}
button {{
  padding:12px 18px;
  margin:8px;
  border-radius:8px;
  border:0;
  cursor:pointer;
}}
video {{
  width:900px;
  max-width:95vw;
  border-radius:14px;
  background:#000;
}}
</style>
</head>
<body>

<h2>CYRKIL Offline Sign Player</h2>

<div>
{buttons}
</div>

<video id="player" controls></video>

<script>
const videos = {json.dumps(videos)};

function loadVideo(key) {{
  const player = document.getElementById("player");
  player.src = videos[key];
  player.load();
  player.play();
}}

const first = Object.keys(videos)[0];
if (first) loadVideo(first);
</script>

</body>
</html>
"""

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print("Saved:", OUTPUT_HTML)


if __name__ == "__main__":
    main()