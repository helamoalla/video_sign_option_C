import asyncio
import json

from app.request_limits import (
    RequestBodyLimitMiddleware,
)


def run_request(
    body_chunks: list[bytes],
    content_length: int | None,
    max_bytes: int,
):
    app_called = False
    sent_messages = []

    async def application(
        scope,
        receive,
        send,
    ):
        nonlocal app_called
        app_called = True

        while True:
            message = await receive()

            if not message.get(
                "more_body",
                False,
            ):
                break

        response_body = b'{"status":"ok"}'

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response_body,
            }
        )

    headers = []

    if content_length is not None:
        headers.append(
            (
                b"content-length",
                str(content_length).encode(
                    "ascii"
                ),
            )
        )

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/process-video-assets",
        "headers": headers,
    }

    pending_messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": (
                index < len(body_chunks) - 1
            ),
        }
        for index, chunk in enumerate(
            body_chunks
        )
    ]

    async def receive():
        return pending_messages.pop(0)

    async def send(message):
        sent_messages.append(message)

    middleware = RequestBodyLimitMiddleware(
        application,
        max_bytes=max_bytes,
    )

    asyncio.run(
        middleware(
            scope,
            receive,
            send,
        )
    )

    return app_called, sent_messages


def response_status(messages) -> int:
    return next(
        message["status"]
        for message in messages
        if message["type"]
        == "http.response.start"
    )


def response_json(messages) -> dict:
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"]
        == "http.response.body"
    )

    return json.loads(body)


def test_accepts_request_within_limit():
    app_called, messages = run_request(
        body_chunks=[b"12345"],
        content_length=5,
        max_bytes=10,
    )

    assert app_called is True
    assert response_status(messages) == 200


def test_rejects_large_content_length():
    app_called, messages = run_request(
        body_chunks=[b""],
        content_length=11,
        max_bytes=10,
    )

    assert app_called is False
    assert response_status(messages) == 413
    assert (
        response_json(messages)["detail"]["code"]
        == "REQUEST_TOO_LARGE"
    )


def test_rejects_chunked_body_over_limit():
    app_called, messages = run_request(
        body_chunks=[b"123456", b"78901"],
        content_length=None,
        max_bytes=10,
    )

    assert app_called is True
    assert response_status(messages) == 413
    assert (
        response_json(messages)["detail"]["code"]
        == "REQUEST_TOO_LARGE"
    )