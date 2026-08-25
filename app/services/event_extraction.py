import json
import logging
import re
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = """You are a precise event information extractor for social media posts.
Your task is to extract the event title, location, and all concrete event dates mentioned in the post caption provided.

Respond with a single JSON object only. Do not use markdown fences, TypeScript types, or extra text.

Rules for title:
- Extract a concise, human-readable event name (e.g. "Rock in Rio", "Festival de Inverno", "Festa de Lançamento").
- Do NOT use the post author's username or handle as the title.
- If no clear event name is present, return null for title.

Rules for location:
- Extract a concrete venue name or city only when it is explicitly stated (e.g. "Allianz Parque", "São Paulo", "Madison Square Garden").
- Do NOT infer or guess the location from context clues.
- If the location is ambiguous or not mentioned, return null for location.

Rules for dates:
- Return each date in DD/MM/YYYY format only (zero-padded, e.g. 03/07/2025).
- Only include dates that refer to concrete event dates (e.g. a show, party, festival, launch).
- Do NOT include publication/post dates or relative terms like "tomorrow" that you cannot resolve.
- If the event spans a range, return the start date first and the end date last.
- Include intermediate dates in the array only when they are explicitly mentioned as separate event days; otherwise omit them.
- If no reliable date is found, return an empty array for dates.

Rules for times:
- Return startTime and endTime in HH:mm 24-hour format only (e.g. 20:00, 09:30).
- Only include times explicitly stated for the event start or end.
- Do NOT guess times or convert vague phrases like "at night" into a time.
- If no reliable start time is found, return null for startTime.
- If no reliable end time is found, return null for endTime.
- Always include a brief reasoning string."""

_USER_PROMPT = """Extract event information from the following post. Return only valid JSON.

Example when fields are present:
{"title": "Rock in Rio", "location": "Rio de Janeiro", "dates": ["13/09/2025", "14/09/2025"], "startTime": "20:00", "endTime": null, "reasoning": "Caption states the festival name, city, dates, and start time."}

Example when nothing reliable is found:
{"title": null, "location": null, "dates": [], "startTime": null, "endTime": null, "reasoning": "No event date, time, or venue was stated."}

{post_block}"""

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DISPLAY_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_MAX_CAPTION_CHARS = 4000
_GROQ_MAX_TOKENS = 1536
_FAILED_GENERATION_LOG_CHARS = 500


class EventExtractionRequest(BaseModel):
    description: str = Field(..., min_length=1)
    title: str | None = None


class EventExtractionResponse(BaseModel):
    title: str | None
    dates: list[str]
    startTime: str | None
    endTime: str | None
    location: str | None
    reasoning: str | None


def empty_extraction() -> EventExtractionResponse:
    return EventExtractionResponse(
        title=None,
        dates=[],
        startTime=None,
        endTime=None,
        location=None,
        reasoning=None,
    )


def _is_valid_display_date(value: str) -> bool:
    match = _DISPLAY_DATE_RE.fullmatch(value)
    if not match:
        return False
    day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def iso_to_display_date(value: str) -> str | None:
    if _is_valid_display_date(value):
        return value
    match = _ISO_DATE_RE.match(value)
    if not match:
        return None
    year, month, day = match.group(1), match.group(2), match.group(3)
    candidate = f"{day}/{month}/{year}"
    return candidate if _is_valid_display_date(candidate) else None


def _normalize_time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed if _TIME_RE.fullmatch(trimmed) else None


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _truncate_caption(text: str) -> str:
    if len(text) <= _MAX_CAPTION_CHARS:
        return text
    return text[:_MAX_CAPTION_CHARS].rstrip()


def _post_block(description: str, title: str | None) -> str:
    caption = description.strip()
    extra_title = (title or "").strip()
    lines = ["Caption:", caption]
    if extra_title and extra_title.casefold() not in caption.casefold():
        lines.extend(["", "Title:", extra_title])
    return "\n".join(lines)


def _user_prompt(description: str, title: str | None) -> str:
    return _USER_PROMPT.replace("{post_block}", _post_block(description, title))


def _parse_message_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Groq content is not a JSON object")
    return parsed


def _error_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    error = body.get("error")
    return error if isinstance(error, dict) else {}


def _log_groq_http_error(response: httpx.Response) -> None:
    error = _error_payload(response)
    failed = error.get("failed_generation")
    if isinstance(failed, str) and len(failed) > _FAILED_GENERATION_LOG_CHARS:
        failed = failed[:_FAILED_GENERATION_LOG_CHARS] + "..."
    logger.warning(
        "Groq event extraction HTTP %s code=%s failed_generation=%s",
        response.status_code,
        error.get("code"),
        failed,
    )


def _groq_request_body(
    *,
    model: str,
    user_content: str,
    json_object: bool,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": _GROQ_MAX_TOKENS,
        "reasoning_format": "hidden",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }
    if json_object:
        body["response_format"] = {"type": "json_object"}
    return body


def _response_to_extraction(parsed: dict[str, Any]) -> EventExtractionResponse:
    raw_dates: list[Any] = []
    if isinstance(parsed.get("dates"), list):
        raw_dates = parsed["dates"]
    elif isinstance(parsed.get("date"), str) and parsed["date"]:
        raw_dates = [parsed["date"]]

    valid_dates = [
        display
        for item in raw_dates
        if isinstance(item, str) and item
        for display in [iso_to_display_date(item)]
        if display is not None
    ]
    dates = (
        valid_dates if len(valid_dates) <= 2 else [valid_dates[0], valid_dates[-1]]
    )

    return EventExtractionResponse(
        title=_normalize_optional_text(parsed.get("title")),
        dates=dates,
        startTime=_normalize_time(parsed.get("startTime")),
        endTime=_normalize_time(parsed.get("endTime")),
        location=_normalize_optional_text(parsed.get("location")),
        reasoning=_normalize_optional_text(parsed.get("reasoning")),
    )


def extract_event_from_description(
    description: str,
    title: str | None = None,
) -> EventExtractionResponse:
    """Call Groq to extract event fields. Never raises; returns empty on failure."""
    text = description.strip()
    if not text:
        return empty_extraction()

    settings = get_settings()
    if not settings.groq_api_key.strip():
        logger.warning("Groq event extraction skipped: GROQ_API_KEY is empty")
        return empty_extraction()

    text = _truncate_caption(text)
    user_content = _user_prompt(text, title)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.groq_api_key}",
    }

    try:
        response = httpx.post(
            _GROQ_URL,
            headers=headers,
            json=_groq_request_body(
                model=settings.groq_model,
                user_content=user_content,
                json_object=True,
            ),
            timeout=20.0,
        )
        if response.status_code == 400:
            _log_groq_http_error(response)
            if _error_payload(response).get("code") == "json_validate_failed":
                response = httpx.post(
                    _GROQ_URL,
                    headers=headers,
                    json=_groq_request_body(
                        model=settings.groq_model,
                        user_content=user_content,
                        json_object=False,
                    ),
                    timeout=20.0,
                )
        response.raise_for_status()
        payload = response.json()
        raw = payload["choices"][0]["message"]["content"]
        if not isinstance(raw, str):
            raise ValueError("Groq message content is missing")
        parsed = _parse_message_json(raw)
    except Exception:
        logger.warning("Groq event extraction failed", exc_info=True)
        return empty_extraction()

    return _response_to_extraction(parsed)
