import asyncio
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

from moviepy import VideoFileClip
from playwright.async_api import (
    async_playwright,
)
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


def trim_video(
    input_path: str,
    output_path: str,
    trim_start_seconds: float = 0.0,
) -> str:
    """
    Convert the Playwright WebM recording to MP4 and remove
    the initial CWASA loading period.
    """

    input_file = Path(
        input_path
    ).resolve()

    output_file = Path(
        output_path
    ).resolve()

    if not input_file.is_file():
        raise FileNotFoundError(
            "Recorded Playwright video was not found: "
            f"{input_file}"
        )

    if input_file.stat().st_size == 0:
        raise RuntimeError(
            "Recorded Playwright video is empty: "
            f"{input_file}"
        )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    clip = None
    trimmed_clip = None

    try:
        clip = VideoFileClip(
            str(input_file)
        )

        safe_trim_start = max(
            0.0,
            float(trim_start_seconds),
        )

        # Never attempt to start beyond the end of the clip.
        if (
            clip.duration <= 0
            or safe_trim_start
            >= clip.duration
        ):
            safe_trim_start = 0.0

        if safe_trim_start > 0:
            trimmed_clip = clip.subclipped(
                safe_trim_start,
                clip.duration,
            )

            output_clip = trimmed_clip

        else:
            output_clip = clip

        output_clip.write_videofile(
            str(output_file),
            codec="libx264",
            audio=False,
            fps=25,
            logger=None,
        )

    finally:
        if trimmed_clip is not None:
            trimmed_clip.close()

        if clip is not None:
            clip.close()

    if not output_file.is_file():
        raise RuntimeError(
            "Trimmed avatar video was not created: "
            f"{output_file}"
        )

    if output_file.stat().st_size == 0:
        raise RuntimeError(
            "Trimmed avatar video is empty: "
            f"{output_file}"
        )

    return str(output_file)


async def record_cwasa_page_async(
    page_url: str,
    output_path: str,
    duration_ms: int = 12_000,
    trim_start_seconds: float = 3.0,
) -> str:
    """
    Record one CWASA page in an isolated directory.

    The function:

    - Uses one temporary directory per recording.
    - Tracks Playwright's exact video path.
    - Authenticates as the internal worker.
    - Enables software WebGL in headless Chromium.
    - Waits for a visible CWASA canvas.
    - Captures a diagnostic screenshot.
    - Dynamically removes the complete page-loading period.
    """

    final_output_path = Path(
        output_path
    ).resolve()

    final_output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory(
        prefix=(
            f".{final_output_path.stem}"
            "_recording_"
        ),
        dir=str(
            final_output_path.parent
        ),
    ) as temporary_directory:
        recording_directory = Path(
            temporary_directory
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
            headless=False,
            args=[
                "--enable-webgl",
                "--ignore-gpu-blocklist",
                "--use-angle=swiftshader",
                "--disable-dev-shm-usage",
            ],
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

                # Playwright begins recording when the page is
                # created, not when playGloss() is called.
                recording_started_at = (
                    time.monotonic()
                )

                page_video = page.video

                if page_video is None:
                    raise RuntimeError(
                        "Playwright video recording was "
                        "not enabled for the CWASA page."
                    )

                page_errors: list[str] = []
                failed_requests: list[str] = []


                def handle_page_error(
                    error,
                ) -> None:
                    message = str(error)

                    page_errors.append(
                        message
                    )

                    logger.error(
                        "CWASA browser error: %s",
                        message,
                    )


                def handle_failed_request(
                    request,
                ) -> None:
                    message = (
                        f"{request.method} "
                        f"{request.url}: "
                        f"{request.failure}"
                    )

                    failed_requests.append(
                        message
                    )

                    logger.error(
                        "CWASA request failed: %s",
                        message,
                    )


                page.on(
                    "pageerror",
                    handle_page_error,
                )

                page.on(
                    "requestfailed",
                    handle_failed_request,
                )

                page.on(
                    "console",
                    lambda message: logger.info(
                        "CWASA console [%s]: %s",
                        message.type,
                        message.text,
                    ),
                )

                internal_worker_token = os.getenv(
                    "INTERNAL_WORKER_TOKEN",
                    "",
                ).strip()

                if (
                    len(internal_worker_token)
                    < 32
                ):
                    raise RuntimeError(
                        "INTERNAL_WORKER_TOKEN must "
                        "contain at least 32 characters."
                    )
                internal_host = urlparse(page_url).netloc


                async def authorize_internal_requests(
                    route,
                    request,
                ):
                    request_host = urlparse(
                        request.url
                    ).netloc

                    headers = dict(request.headers)

                    # Only authenticate requests sent to our API.
                    # Never send the internal token to external servers.
                    if request_host == internal_host:
                        headers[
                            "X-Internal-Worker-Token"
                        ] = internal_worker_token

                    await route.continue_(
                        headers=headers
                    )


                await page.route(
                    "**/*",
                    authorize_internal_requests,
                )

                response = await page.goto(
                    page_url,
                    wait_until="networkidle",
                    timeout=60_000,
                )

                if response is None:
                    raise RuntimeError(
                        "CWASA page returned no "
                        "HTTP response."
                    )

                if response.status != 200:
                    raise RuntimeError(
                        "CWASA page could not be loaded. "
                        f"HTTP status: {response.status}"
                    )

                await page.wait_for_function(
                    """
                    () => (
                        typeof playGloss === "function"
                        && window.CYRKIL_SIGN_PLAN_READY === true
                    )
                    """,
                    timeout=30_000,
                )
                # The function existing is insufficient. Confirm
                # that CWASA created a visible rendering canvas.
                await page.wait_for_function(
                    """
                    () => {
                        const canvases = Array.from(
                            document.querySelectorAll(
                                "canvas"
                            )
                        );

                        return canvases.some(
                            canvas => {
                                const rectangle =
                                    canvas
                                    .getBoundingClientRect();

                                return (
                                    canvas.width > 0
                                    && canvas.height > 0
                                    && rectangle.width > 0
                                    && rectangle.height > 0
                                );
                            }
                        );
                    }
                    """,
                    timeout=30_000,
                )

                # Give the avatar/model a short initialization
                # period before starting the animation.
                await page.wait_for_timeout(
                    2_000
                )

                # Calculate how much blank loading footage
                # Playwright has recorded so far.
                animation_start_offset = (
                    time.monotonic()
                    - recording_started_at
                )

                logger.info(
                    "CWASA animation begins %.2f seconds "
                    "after recording start.",
                    animation_start_offset,
                )

                await page.evaluate(
                    "() => playGloss()"
                )

                # Allow the first rendered animation frame to
                # become visible.
                await page.wait_for_timeout(
                    1_000
                )

                debug_screenshot_path = (
                    final_output_path.parent
                    / (
                        final_output_path.stem
                        + "-cwasa-debug.png"
                    )
                )

                await page.screenshot(
                    path=str(
                        debug_screenshot_path
                    ),
                    full_page=True,
                )

                canvas_information = (
                    await page.evaluate(
                        """
                        () => Array.from(
                            document.querySelectorAll(
                                "canvas"
                            )
                        ).map(
                            canvas => {
                                const rectangle =
                                    canvas
                                    .getBoundingClientRect();

                                return {
                                    id: canvas.id,
                                    width: canvas.width,
                                    height: canvas.height,
                                    displayedWidth:
                                        rectangle.width,
                                    displayedHeight:
                                        rectangle.height
                                };
                            }
                        )
                        """
                    )
                )

                logger.info(
                    "CWASA canvas information: %s",
                    canvas_information,
                )

                if page_errors:
                    logger.warning(
                        "CWASA page reported JavaScript "
                        "errors: %s",
                        page_errors,
                    )

                if failed_requests:
                    logger.warning(
                        "CWASA page reported failed "
                        "requests: %s",
                        failed_requests,
                    )

                await page.wait_for_timeout(
                    duration_ms
                )

                # Closing the context finalizes the WebM file.
                await context.close()
                context = None

                playwright_video_path = Path(
                    await page_video.path()
                ).resolve()

                if (
                    not playwright_video_path
                    .is_file()
                ):
                    raise FileNotFoundError(
                        "Playwright did not create "
                        "the expected recording: "
                        f"{playwright_video_path}"
                    )

                if (
                    playwright_video_path
                    .stat()
                    .st_size
                    == 0
                ):
                    raise RuntimeError(
                        "Playwright created an empty "
                        "recording: "
                        f"{playwright_video_path}"
                    )

                # Keep half a second before playGloss() so the
                # first sign frame is not cut.
                dynamic_trim_start = max(
                    0.0,
                    animation_start_offset
                    - 0.5,
                )

                effective_trim_start = dynamic_trim_start
                
                logger.info(
                    "Trimming %.2f seconds from CWASA "
                    "recording.",
                    effective_trim_start,
                )

                trim_video(
                    input_path=str(
                        playwright_video_path
                    ),
                    output_path=str(
                        final_output_path
                    ),
                    trim_start_seconds=(
                        effective_trim_start
                    ),
                )

            finally:
                if context is not None:
                    await context.close()

                await browser.close()

    return str(
        final_output_path
    )


def record_cwasa_page(
    page_url: str,
    output_path: str,
    duration_ms: int = 12_000,
    trim_start_seconds: float = 3.0,
) -> str:
    return asyncio.run(
        record_cwasa_page_async(
            page_url=page_url,
            output_path=output_path,
            duration_ms=duration_ms,
            trim_start_seconds=(
                trim_start_seconds
            ),
        )
    )