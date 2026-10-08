"""Streaming client for the RodiumAI chat completions API (OpenAI-compatible)."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import anyio
import httpx

from config import MAX_TOKENS, RODIUMAI_API_KEY, RODIUMAI_BASE_URL

# A shared client keeps the connection to the API open between requests.
# Long read timeout: a chunk can take a while to come when the model "thinks".
client = httpx.AsyncClient(
    base_url=RODIUMAI_BASE_URL,
    timeout=httpx.Timeout(connect=10, read=90, write=10, pool=10),
)


class LLMError(Exception):
    """The API call failed (before or during the stream)."""


@dataclass
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMStream:
    """An open streamed answer. Iterate over it to get the text pieces; `usage` is filled at the end."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.usage: Usage | None = None
        self.finish_reason: str | None = None

    async def __aiter__(self) -> AsyncIterator[str]:
        # The API sends Server-Sent Events: "data: {json}" lines, blank lines in between,
        # and a final "data: [DONE]".
        done = False
        try:
            async for line in self._response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    done = True
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise LLMError("Invalid chunk received from the API.") from exc
                if chunk.get("error"):
                    # Some providers report a failure inside the stream, after a 200 status.
                    raise LLMError(str(chunk["error"]))
                if chunk.get("usage"):
                    usage = chunk["usage"]
                    self.usage = Usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason"):
                        self.finish_reason = choice["finish_reason"]
                    content = (choice.get("delta") or {}).get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:
            raise LLMError("The connection to the API was lost.") from exc
        if not done and self.finish_reason is None:
            # The connection ended without [DONE] nor finish_reason: the answer is incomplete.
            raise LLMError("The stream ended before the answer was complete.")

    async def aclose(self) -> None:
        # Shielded so the connection is released even when the request is being cancelled (Stop button).
        with anyio.CancelScope(shield=True):
            await self._response.aclose()


async def open_stream(model: str, messages: list[dict]) -> LLMStream:
    """Send the request and wait for the status line. Raises LLMError if the API refuses it."""
    request = client.build_request(
        "POST",
        "/chat/completions",
        headers={"Authorization": f"Bearer {RODIUMAI_API_KEY}"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "stream": True,
            # Ask for a last chunk carrying the token counts.
            "stream_options": {"include_usage": True},
        },
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        raise LLMError("The LLM API could not be reached.") from exc
    if response.status_code != 200:
        body = await response.aread()
        await response.aclose()
        raise LLMError(f"The LLM API answered {response.status_code}: {body[:300]!r}")
    return LLMStream(response)
