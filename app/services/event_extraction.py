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
Your task is to extract the event title, location, and all concrete event dates mentioned in the post description provided.

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
- Always include a brief reasoning."""

_USER_PROMPT = """Extract event information from the following post. Return ONLY valid JSON in this exact format:
{
  "title": string | null,
  "location": string | null,
  "dates": ["DD/MM/YYYY"] | [],
  "startTime": string | null,
  "endTime": string | null,
  "reasoning": string
}

Post:
{description}"""

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DISPLAY_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


class EventExtractionRequest(BaseModel):
    description: str = Field(..., min_length=1)


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


def extract_event_from_description(description: str) -> EventExtractionResponse:
    """Call Groq to extract event fields. Never raises; returns empty on failure."""
    text = description.strip()
    if not text:
        return empty_extraction()

    settings = get_settings()
    if not settings.groq_api_key.strip():
        return empty_extraction()

    try:
        response = httpx.post(
            _GROQ_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.groq_api_key}",
            },
            json={
                "model": settings.groq_model,
                "temperature": 0.1,
                "max_tokens": 256,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _USER_PROMPT.replace("{description}", text)},
                ],
            },
            timeout=20.0,
        )
        response.raise_for_status()
        payload = response.json()
        raw = payload["choices"][0]["message"]["content"]
        parsed: dict[str, Any] = json.loads(raw)
    except Exception:
        logger.warning("Groq event extraction failed", exc_info=True)
        return empty_extraction()

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
        valid_dates
        if len(valid_dates) <= 2
        else [valid_dates[0], valid_dates[-1]]
    )

    return EventExtractionResponse(
        title=_normalize_optional_text(parsed.get("title")),
        dates=dates,
        startTime=_normalize_time(parsed.get("startTime")),
        endTime=_normalize_time(parsed.get("endTime")),
        location=_normalize_optional_text(parsed.get("location")),
        reasoning=_normalize_optional_text(parsed.get("reasoning")),
    )
