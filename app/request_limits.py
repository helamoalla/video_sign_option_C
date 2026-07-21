import os
from starlette.types import (
    ASGIApp,
    Message,
    Receive,
    Scope,
    Send,
)


MAX_REQUEST_BYTES = int(
    os.getenv(
        "MAX_REQUEST_BYTES",
        str(105 * 1024 * 1024),
    )
)


class RequestBodyTooLargeError(Exception):
    pass


class RequestBodyLimitMiddleware:
    """
    Reject oversized HTTP request bodies before FastAPI parses
    multipart uploads.

    Content-Length is checked first. The actual received bytes
    are also counted because Content-Length can be absent or false.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int = MAX_REQUEST_BYTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError(
                "max_bytes must be greater than zero."
            )

        self.app = app
        self.max_bytes = max_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(
                scope,
                receive,
                send,
            )
            return

        headers = dict(scope.get("headers", []))

        content_length_value = headers.get(
            b"content-length"
        )

        if content_length_value is not None:
            try:
                content_length = int(
                    content_length_value
                )
            except ValueError:
                await self._send_error(send)
                return

            if content_length > self.max_bytes:
                await self._send_error(send)
                return

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes

            message = await receive()

            if message["type"] == "http.request":
                received_bytes += len(
                    message.get("body", b"")
                )

                if received_bytes > self.max_bytes:
                    raise RequestBodyTooLargeError

            return message

        async def tracked_send(
            message: Message,
        ) -> None:
            nonlocal response_started

            if message["type"] == "http.response.start":
                response_started = True

            await send(message)

        try:
            await self.app(
                scope,
                limited_receive,
                tracked_send,
            )

        except RequestBodyTooLargeError:
            if not response_started:
                await self._send_error(send)

    async def _send_error(
        self,
        send: Send,
    ) -> None:
        body = (
            b'{"detail":{"code":"REQUEST_TOO_LARGE",'
            b'"message":"The request body exceeds the '
            b'maximum allowed size."}}'
        )

        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (
                        b"content-type",
                        b"application/json",
                    ),
                    (
                        b"content-length",
                        str(len(body)).encode(
                            "ascii"
                        ),
                    ),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )