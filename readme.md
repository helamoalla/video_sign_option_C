# VideoSign

VideoSign is an AI-powered accessibility platform that automatically generates multilingual accessible videos by combining speech recognition, subtitle generation, translation, sign language avatars, and an interactive multilingual player.

> **Note:** This project is a technical prototype developed as part of a technical assessment. Some components still require additional datasets, SiGML files, and production-grade services before being production-ready.

---

# Features

- 🎥 Video upload and processing
- 📝 Automatic speech transcription
- 🌍 Subtitle translation
- 🤟 Sign language avatar generation (CWASA)
- 🎬 Automatic multilingual video rendering
- 🎞️ AI Video Director (Magic Hour demo)
- 🖥️ Interactive multilingual player
- 📦 Offline HTML player generation

---

# Project Structure

```
video_sign/
│
├── app/
│   ├── avatar/
│   ├── director/
│   ├── tools/
│   ├── main.py
│   ├── player_builder.py
│   ├── session_manifest.py
│   ├── subtitles.py
│   ├── transcribe.py
│   ├── translate.py
│   ├── video_editor.py
│   └── ...
│
├── outputs/
├── uploads/
├── static/
├── docs/
├── data/
├── audio_sign/
│
├── requirements.txt
├── streamlit_app.py
└── avatar_scene.blend
```

---

# Installation

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
GROQ_API_KEY=...
MAGIC_HOUR_API_KEY=...
```

---

# Run

```bash
python -m uvicorn app.main:app --reload
```

Swagger:

```
http://127.0.0.1:8000/docs
```

---

# Main Endpoints

## Process a video

```
POST /process-video-assets
```

This endpoint automatically generates:

- transcription
- subtitles
- translated subtitles
- sign language avatars
- rendered videos
- multilingual player

---

## AI Director

```
POST /director/hf-video
```

This endpoint generates a promotional video from a natural language prompt.

For the prototype, the project uses **Magic Hour** for video generation.

Later, this can easily be replaced with more powerful video generation APIs (Runway, Veo, PixVerse, Kling, etc.).

The generated video can then be processed by:

```
POST /process-video-assets
```

to automatically generate subtitles, translations and sign language versions.

---

# Offline Player

After processing a video, each execution generates a unique **session id** inside the `outputs/` folder.

To create an offline version of the multilingual player:

```bash
python -m app.tools.build_offline_player
```

This generates:

```
outputs/<session_id>/offline_player.html
```

The session id must correspond to an already generated video.

The offline player allows switching between all available languages without requiring the backend to be running.

---

# Generated Outputs

After each execution, the generated assets can be found inside:

```
outputs/<session_id>/
```

including:

- rendered videos
- subtitles
- avatar videos
- multilingual player
- offline player

---

# Technologies

- Python
- FastAPI
- Groq LLM
- Whisper
- MoviePy
- Edge-TTS
- CWASA
- Magic Hour
- FFmpeg

---

# Current Limitations

This prototype still requires:

- more SiGML files
- additional sign language datasets
- more HamNoSys dictionaries
- more supported glosses
- production-grade video generation APIs

---

# Future Work

- Integration of a realistic human avatar
- Integration of Baseera platform
- Improved 3D avatar animation
- Larger multilingual sign language datasets
- Production video generation APIs

# Useful github Updated

https://github.com/helamoalla/hamnosys_to_sigml     

https://github.com/helamoalla/sl_generation_blender

# Useful github original

https://github.com/carolNeves/HamNoSys2SiGML


https://github.com/lanthaon/sl-animation-blender/tree/main