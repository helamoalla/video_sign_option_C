import asyncio
import sys
import tempfile
from pathlib import Path

from moviepy import VideoFileClip
from playwright.async_api import async_playwright


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


def trim_video(
    input_path: str,
    output_path: str,
    trim_start_seconds: float = 3.0,
) -> str:
    input_file = Path(input_path).resolve()
    output_file = Path(output_path).resolve()

    if not input_file.is_file():
        raise FileNotFoundError(
            f"Recorded Playwright video was not found: "
            f"{input_file}"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    clip = None
    trimmed_clip = None

    try:
        clip = VideoFileClip(str(input_file))

        if clip.duration <= trim_start_seconds:
            clip.write_videofile(
                str(output_file),
                codec="libx264",
                audio=False,
                fps=25,
            )

        else:
            trimmed_clip = clip.subclipped(
                trim_start_seconds,
                clip.duration,
            )

            trimmed_clip.write_videofile(
                str(output_file),
                codec="libx264",
                audio=False,
                fps=25,
            )

    finally:
        if trimmed_clip is not None:
            trimmed_clip.close()

        if clip is not None:
            clip.close()

    if not output_file.is_file():
        raise RuntimeError(
            f"Trimmed avatar video was not created: "
            f"{output_file}"
        )

    if output_file.stat().st_size == 0:
        raise RuntimeError(
            f"Trimmed avatar video is empty: "
            f"{output_file}"
        )

    return str(output_file)


async def record_cwasa_page_async(
    page_url: str,
    output_path: str,
    duration_ms: int = 12000,
    trim_start_seconds: float = 3.0,
) -> str:
    """
    Record one CWASA page in an isolated directory.

    Playwright's exact page.video.path() is used instead of
    searching for the newest .webm file.
    """

    final_output_path = Path(output_path).resolve()

    final_output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Every recording receives a unique temporary directory.
    # Two jobs can therefore never inspect or select each
    # other's Playwright recording.
    with tempfile.TemporaryDirectory(
        prefix=f".{final_output_path.stem}_recording_",
        dir=str(final_output_path.parent),
    ) as temporary_directory:
        recording_directory = Path(
            temporary_directory
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True
            )

            context = None

            try:
                context = await browser.new_context(
                    viewport={
                        "width": 720,
                        "height": 720,
                    },
                    record_video_dir=str(
                        recording_directory
                    ),
                    record_video_size={
                        "width": 720,
                        "height": 720,
                    },
                )

                page = await context.new_page()

                # Keep the exact Playwright video object associated
                # with this page and this recording.
                page_video = page.video

                if page_video is None:
                    raise RuntimeError(
                        "Playwright video recording was not "
                        "enabled for the CWASA page."
                    )

                await page.goto(
                    page_url,
                    wait_until="networkidle",
                    timeout=60_000,
                )

                await page.wait_for_function(
                    "() => typeof playGloss === 'function'",
                    timeout=30_000,
                )

                await page.wait_for_timeout(2_000)

                await page.evaluate("playGloss()")

                await page.wait_for_timeout(duration_ms)

                # Closing the context finalizes the WebM recording.
                await context.close()
                context = None

                # This is the exact file belonging to page_video.
                playwright_video_path = Path(
                    await page_video.path()
                ).resolve()

                if not playwright_video_path.is_file():
                    raise FileNotFoundError(
                        "Playwright did not create the expected "
                        f"recording: {playwright_video_path}"
                    )

                if playwright_video_path.stat().st_size == 0:
                    raise RuntimeError(
                        "Playwright created an empty recording: "
                        f"{playwright_video_path}"
                    )

                trim_video(
                    input_path=str(
                        playwright_video_path
                    ),
                    output_path=str(
                        final_output_path
                    ),
                    trim_start_seconds=(
                        trim_start_seconds
                    ),
                )

            finally:
                if context is not None:
                    await context.close()

                await browser.close()

    return str(final_output_path)


def record_cwasa_page(
    page_url: str,
    output_path: str,
    duration_ms: int = 12000,
    trim_start_seconds: float = 3.0,
) -> str:
    return asyncio.run(
        record_cwasa_page_async(
            page_url=page_url,
            output_path=output_path,
            duration_ms=duration_ms,
            trim_start_seconds=trim_start_seconds,
        )
    )