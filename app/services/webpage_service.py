import json

import httpx
from bs4 import BeautifulSoup
from trafilatura import extract

from app.core.exceptions import UpstreamError
from app.schemas.instagram import PostMetadataResponse

_MAX_BODY_CHARS = 2000
_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def enrich_webpage(url: str) -> PostMetadataResponse:
    try:
        response = httpx.get(
            url,
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Salvai/1.0 EnrichmentBot"},
        )
        response.raise_for_status()
        html = response.text[: _MAX_BYTES]
    except httpx.TimeoutException:
        raise UpstreamError("Page fetch timed out")
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"Page fetch returned {exc.response.status_code}")
    except httpx.RequestError as exc:
        raise UpstreamError(f"Page fetch request failed: {exc}")

    soup = BeautifulSoup(html, "lxml")

    title = _extract_title(soup)
    description = _extract_meta_description(soup)
    thumbnail = _extract_og_image(soup)
    site_name = _extract_site_name(soup)
    json_ld_text = _extract_json_ld(soup)

    body_text = extract(html, include_comments=False, include_tables=False)
    if body_text:
        body_text = body_text[: _MAX_BODY_CHARS].strip()

    parts: list[str] = []
    if title:
        parts.append(title)
    if description:
        parts.append(description)
    if json_ld_text:
        parts.append(json_ld_text)
    if body_text:
        parts.append(body_text)

    composed = "\n\n".join(parts) if parts else None

    return PostMetadataResponse(
        platform="unknown",
        kind="post",
        description=composed,
        thumbnailUrl=thumbnail,
        authorHandle=site_name,
        publishedAt=None,
    )


def _extract_title(soup: BeautifulSoup) -> str | None:
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()

    twitter_title = soup.find("meta", attrs={"name": "twitter:title"})
    if twitter_title and twitter_title.get("content"):
        return twitter_title["content"].strip()

    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    return None


def _extract_meta_description(soup: BeautifulSoup) -> str | None:
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        return og_desc["content"].strip()

    twitter_desc = soup.find("meta", attrs={"name": "twitter:description"})
    if twitter_desc and twitter_desc.get("content"):
        return twitter_desc["content"].strip()

    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return meta_desc["content"].strip()

    return None


def _extract_og_image(soup: BeautifulSoup) -> str | None:
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image["content"].strip()

    twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
    if twitter_image and twitter_image.get("content"):
        return twitter_image["content"].strip()

    return None


def _extract_site_name(soup: BeautifulSoup) -> str | None:
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        return og_site["content"].strip()

    return None


def _extract_json_ld(soup: BeautifulSoup) -> str | None:
    """Extract human-readable fields from JSON-LD structured data."""
    scripts = soup.find_all("script", type="application/ld+json")
    lines: list[str] = []

    for script in scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")

            if "Event" in item_type:
                event_parts = []
                for field in ("name", "description", "startDate", "endDate", "location"):
                    val = item.get(field)
                    if isinstance(val, dict):
                        val = val.get("name", str(val))
                    if val and isinstance(val, str):
                        event_parts.append(f"{field}: {val}")
                if event_parts:
                    lines.append("\n".join(event_parts))
            elif "Article" in item_type or "WebPage" in item_type:
                for field in ("headline", "description", "articleBody"):
                    val = item.get(field)
                    if isinstance(val, str):
                        val = val[:500]
                        lines.append(val)

    return "\n".join(lines) if lines else None
