import os
import re
import json
import uuid
import asyncio
from pathlib import Path

import edge_tts
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from magic_hour import Client
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

load_dotenv()

OUT_DIR = Path("outputs/director")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def get_llm():
    return ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.4,
    )


def extract_json(text: str):
    text = text.replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("LLM did not return JSON")
    return json.loads(match.group(0))


def create_plan(user_prompt: str, language: str = "french"):
    prompt = f"""
You are a film director for short social media ads.

Create a 9-second realistic video plan.

Return ONLY JSON:
{{
  "title": "...",
  "voiceover": "...",
  "scenes": [
    {{"prompt": "realistic cinematic video prompt, camera movement, lighting", "duration": 3}},
    {{"prompt": "realistic cinematic video prompt, camera movement, lighting", "duration": 3}},
    {{"prompt": "realistic cinematic video prompt, camera movement, lighting", "duration": 3}}
  ]
}}

Language of voiceover: {language}

User request:
{user_prompt}
"""
    response = get_llm().invoke(prompt)
    return extract_json(response.content)


def magic_hour_client():
    api_key = os.getenv("MAGIC_HOUR_API_KEY")
    if not api_key:
        raise ValueError("MAGIC_HOUR_API_KEY missing in .env")
    return Client(token=api_key)


def generate_magic_hour_scene(prompt: str, output_dir: Path, duration: int = 3):
    client = magic_hour_client()

    result = client.v1.text_to_video.generate(
        end_seconds=float(duration),
        orientation="landscape",
        style={"prompt": prompt},
        name="CYRKIL Director Scene",
        resolution="480p",
        model="ltx-2.3",
        audio=False,
        wait_for_completion=True,
        download_outputs=True,
        download_directory=str(output_dir),
    )

    downloaded = list(output_dir.glob("*.mp4"))
    if not downloaded:
        raise RuntimeError(f"Magic Hour finished but no MP4 found. Result: {result}")

    return downloaded[-1]


async def make_voice(text: str, output_path: Path, language: str):
    voice = "fr-FR-DeniseNeural"
    if language == "english":
        voice = "en-US-AriaNeural"
    elif language == "arabic":
        voice = "ar-EG-SalmaNeural"
    elif language == "german":
        voice = "de-DE-KatjaNeural"

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_path))
    return output_path


def assemble_video(scene_paths, audio_path: Path, output_path: Path):
    clips = [VideoFileClip(str(p)) for p in scene_paths]
    final = concatenate_videoclips(clips, method="compose")

    audio = AudioFileClip(str(audio_path))
    audio = audio.subclipped(0, min(audio.duration, final.duration))
    final = final.with_audio(audio)

    final.write_videofile(
        str(output_path),
        codec="libx264",
        audio_codec="aac",
        fps=24,
    )

    for clip in clips:
        clip.close()
    audio.close()
    final.close()

    return output_path


def generate_director_video(user_prompt: str, language: str = "french"):
    job_id = str(uuid.uuid4())
    job_dir = OUT_DIR / job_id
    scenes_dir = job_dir / "scenes"

    job_dir.mkdir(parents=True, exist_ok=True)
    scenes_dir.mkdir(parents=True, exist_ok=True)

    plan = create_plan(user_prompt, language)

    (job_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    scene_paths = []

    for i, scene in enumerate(plan["scenes"], start=1):
        scene_dir = scenes_dir / f"scene_{i}"
        scene_dir.mkdir(parents=True, exist_ok=True)

        scene_video = generate_magic_hour_scene(
            prompt=scene["prompt"],
            output_dir=scene_dir,
            duration=int(scene.get("duration", 3)),
        )

        final_scene_path = scenes_dir / f"scene_{i}.mp4"
        scene_video.replace(final_scene_path)
        scene_paths.append(final_scene_path)

    audio_path = job_dir / "voice.mp3"
    asyncio.run(make_voice(plan["voiceover"], audio_path, language))

    output_path = job_dir / "director_video.mp4"
    assemble_video(scene_paths, audio_path, output_path)

    return {
        "job_id": job_id,
        "plan": plan,
        "video_path": str(output_path),
        "video_url": f"/outputs/director/{job_id}/director_video.mp4",
    }