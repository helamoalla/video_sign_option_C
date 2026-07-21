import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from moviepy import VideoFileClip
from playwright.async_api import async_playwright


logger = logging.getLogger(__name__)


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )


def trim_video(
    input_path: str,
    output_path: str,
    trim_start_seconds: float = 3.0,
) -> str:
    """Convert the isolated Playwright WebM recording to MP4."""

    input_file = Path(input_path).resolve()
    output_file = Path(output_path).resolve()

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
        clip = VideoFileClip(str(input_file))

        if clip.duration <= 0:
            raise RuntimeError(
                "Recorded Playwright video has no duration."
            )

        safe_trim_start = min(
            max(0.0, float(trim_start_seconds)),
            max(0.0, clip.duration - 0.1),
        )

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
    trim_start_seconds: float = 3.0,
    completion_timeout_seconds: float = 120.0,
) -> str:
    """
    Record one CWASA page in an isolated directory.

    The browser remains headed as required. Recording ends when the
    JavaScript gloss sequence finishes. The timeout is only a guard
    against a permanently stuck browser.
    """

    final_output_path = Path(output_path).resolve()
    final_output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory(
        prefix=f".{final_output_path.stem}_recording_",
        dir=str(final_output_path.parent),
    ) as temporary_directory:
        recording_directory = Path(temporary_directory)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=False,
            )

            context = None

            try:
                context = await browser.new_context(
                    viewport={
                        "width": 720,
                        "height": 720,
                    },
                    record_video_dir=str(recording_directory),
                    record_video_size={
                        "width": 720,
                        "height": 720,
                    },
                )

                page = await context.new_page()
                page_video = page.video

                if page_video is None:
                    raise RuntimeError(
                        "Playwright video recording was not enabled "
                        "for the CWASA page."
                    )

                page_errors: list[str] = []
                failed_requests: list[str] = []
                critical_asset_errors: list[str] = []

                critical_asset_names = (
                    "qskin.vert",
                    "qskin.frag",
                    "anna.jar",
                    "COMMON.jar",
                    "h2s.xsl",
                )

                def handle_page_error(error) -> None:
                    message = str(error)
                    page_errors.append(message)
                    logger.error(
                        "CWASA browser error: %s",
                        message,
                    )

                def handle_failed_request(request) -> None:
                    message = (
                        f"{request.method} {request.url}: "
                        f"{request.failure}"
                    )
                    failed_requests.append(message)

                    if any(
                        name in request.url
                        for name in critical_asset_names
                    ):
                        critical_asset_errors.append(message)

                    logger.error(
                        "CWASA request failed: %s",
                        message,
                    )

                def handle_response(response) -> None:
                    if response.status < 400:
                        return

                    message = (
                        f"HTTP {response.status} {response.url}"
                    )

                    if any(
                        name in response.url
                        for name in critical_asset_names
                    ):
                        critical_asset_errors.append(message)

                    logger.error(
                        "CWASA HTTP error: %s %s",
                        response.status,
                        response.url,
                    )

                def handle_console(message) -> None:
                    logger.info(
                        "CWASA console [%s]: %s",
                        message.type,
                        message.text,
                    )

                page.on("pageerror", handle_page_error)
                page.on("requestfailed", handle_failed_request)
                page.on("response", handle_response)
                page.on("console", handle_console)

                internal_worker_token = os.getenv(
                    "INTERNAL_WORKER_TOKEN",
                    "",
                ).strip()

                if len(internal_worker_token) < 32:
                    raise RuntimeError(
                        "INTERNAL_WORKER_TOKEN must contain at least "
                        "32 characters."
                    )

                internal_host = urlparse(page_url).netloc

                async def authorize_internal_requests(
                    route,
                    request,
                ) -> None:
                    request_host = urlparse(request.url).netloc
                    headers = dict(request.headers)

                    if request_host == internal_host:
                        headers[
                            "X-Internal-Worker-Token"
                        ] = internal_worker_token

                    await route.continue_(headers=headers)

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
                        "CWASA page returned no HTTP response."
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
                        && typeof playGlossesSequentially
                            === "function"
                        && window.CYRKIL_SIGN_PLAN_READY === true
                    )
                    """,
                    timeout=30_000,
                )

                await page.wait_for_function(
                    """
                    () => Array.from(
                        document.querySelectorAll("canvas")
                    ).some(canvas => {
                        const rectangle =
                            canvas.getBoundingClientRect();

                        return (
                            canvas.width > 0
                            && canvas.height > 0
                            && rectangle.width > 0
                            && rectangle.height > 0
                        );
                    })
                    """,
                    timeout=30_000,
                )

                # Allow CWASA and the selected avatar to initialize.
                await page.wait_for_timeout(2_000)

                if critical_asset_errors:
                    raise RuntimeError(
                        "CWASA cannot render the avatar because "
                        "required runtime assets failed to load: "
                        + "; ".join(critical_asset_errors)
                    )

                expected_glosses = await page.evaluate(
                    """
                    () => {
                        const glosses =
                            window.CYRKIL_FOUND_GLOSSES;

                        return Array.isArray(glosses)
                            ? glosses.length
                            : 0;
                    }
                    """
                )

                if expected_glosses < 1:
                    raise RuntimeError(
                        "CWASA received no glosses to play."
                    )

                # Instrument the existing CWASA sequence without
                # changing the simulator template. Recursive calls to
                # playGlossesSequentially pass through this wrapper,
                # which marks the sequence complete after its last item.
                await page.evaluate(
                    """
                    () => {
                        if (
                            window.CYRKIL_SEQUENCE_INSTRUMENTED
                            === true
                        ) {
                            window.CYRKIL_PLAYBACK_DONE = false;
                            return;
                        }

                        const originalSequence =
                            window.playGlossesSequentially;

                        if (
                            typeof originalSequence
                            !== "function"
                        ) {
                            throw new Error(
                                "playGlossesSequentially is missing"
                            );
                        }

                        window.playGlossesSequentially = function (
                            glosses,
                            index
                        ) {
                            if (
                                index >= glosses.length
                                || window.stopRequested === true
                            ) {
                                window.CYRKIL_PLAYBACK_DONE = true;
                                return;
                            }

                            return originalSequence.call(
                                window,
                                glosses,
                                index
                            );
                        };

                        window.CYRKIL_SEQUENCE_INSTRUMENTED = true;
                        window.CYRKIL_PLAYBACK_DONE = false;
                    }
                    """
                )

                logger.info(
                    "Starting CWASA playback for %s glosses.",
                    expected_glosses,
                )

                await page.evaluate(
                    """
                    () => {
                        window.CYRKIL_PLAYBACK_DONE = false;
                        playGloss();
                    }
                    """
                )

                # Capture a diagnostic frame while short signs are
                # still in progress.
                await page.wait_for_timeout(250)

                debug_screenshot_path = (
                    final_output_path.parent
                    / f"{final_output_path.stem}-cwasa-debug.png"
                )

                await page.screenshot(
                    path=str(debug_screenshot_path),
                    full_page=True,
                )

                try:
                    await page.wait_for_function(
                        """
                        () => (
                            window.CYRKIL_PLAYBACK_DONE === true
                        )
                        """,
                        timeout=int(
                            completion_timeout_seconds * 1000
                        ),
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "CWASA gloss sequence did not complete "
                        "before the safety timeout."
                    ) from exc

                # Keep a short tail after the final scheduled sign.
                await page.wait_for_timeout(750)

                if critical_asset_errors:
                    raise RuntimeError(
                        "CWASA runtime assets failed while recording: "
                        + "; ".join(critical_asset_errors)
                    )

                if page_errors:
                    logger.warning(
                        "CWASA page reported JavaScript errors: %s",
                        page_errors,
                    )

                if failed_requests:
                    logger.warning(
                        "CWASA page reported failed requests: %s",
                        failed_requests,
                    )

                await context.close()
                context = None

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

                logger.info(
                    "Trimming %.2f seconds from CWASA recording.",
                    trim_start_seconds,
                )

                trim_video(
                    input_path=str(playwright_video_path),
                    output_path=str(final_output_path),
                    trim_start_seconds=trim_start_seconds,
                )

            finally:
                if context is not None:
                    await context.close()

                await browser.close()

    return str(final_output_path)


def record_cwasa_page(
    page_url: str,
    output_path: str,
    trim_start_seconds: float = 3.0,
    completion_timeout_seconds: float = 120.0,
) -> str:
    return asyncio.run(
        record_cwasa_page_async(
            page_url=page_url,
            output_path=output_path,
            trim_start_seconds=trim_start_seconds,
            completion_timeout_seconds=(
                completion_timeout_seconds
            ),
        )
    )