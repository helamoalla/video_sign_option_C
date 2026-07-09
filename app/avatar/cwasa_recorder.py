import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from moviepy import VideoFileClip

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def trim_video(input_path: str, output_path: str, trim_start_seconds: float = 3.0):
    clip = VideoFileClip(input_path)

    if clip.duration <= trim_start_seconds:
        clip.write_videofile(output_path, codec="libx264", audio=False, fps=25)
        clip.close()
        return output_path

    trimmed = clip.subclipped(trim_start_seconds, clip.duration)

    trimmed.write_videofile(
        output_path,
        codec="libx264",
        audio=False,
        fps=25
    )

    clip.close()
    trimmed.close()

    return output_path


async def record_cwasa_page_async(
    page_url: str,
    output_path: str,
    duration_ms: int = 12000,
    trim_start_seconds: float = 3.0
):
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    raw_output_path = output_path.with_name(output_path.stem + "_raw.webm")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        context = await browser.new_context(
            viewport={"width": 720, "height": 720},
            record_video_dir=str(output_path.parent),
            record_video_size={"width": 720, "height": 720}
        )

        page = await context.new_page()
        await page.goto(page_url, wait_until="networkidle")
        await page.wait_for_function("() => typeof playGloss === 'function'")
        await page.wait_for_timeout(2000)

        await page.evaluate("playGloss()")
        await page.wait_for_timeout(duration_ms)

        await context.close()
        await browser.close()

    videos = list(output_path.parent.glob("*.webm"))
    latest_video = max(videos, key=lambda p: p.stat().st_mtime)

    if raw_output_path.exists():
        raw_output_path.unlink()

    latest_video.rename(raw_output_path)

    trim_video(
        input_path=str(raw_output_path),
        output_path=str(output_path),
        trim_start_seconds=trim_start_seconds
    )

    return str(output_path)


def record_cwasa_page(
    page_url: str,
    output_path: str,
    duration_ms: int = 12000,
    trim_start_seconds: float = 3.0
):
    return asyncio.run(
        record_cwasa_page_async(
            page_url=page_url,
            output_path=output_path,
            duration_ms=duration_ms,
            trim_start_seconds=trim_start_seconds
        )
    )