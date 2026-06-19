"""Universal link verification files and HTML fallback for shared event URLs."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.core.config import get_settings

router = APIRouter(tags=["links"])

_EVENT_ID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")


def _is_valid_event_id(event_id: str) -> bool:
    return bool(_EVENT_ID_PATTERN.fullmatch(event_id))


def build_apple_app_site_association(settings: Any) -> dict[str, Any]:
    app_id = f"{settings.ios_app_team_id}.{settings.ios_bundle_id}"
    return {
        "applinks": {
            "apps": [],
            "details": [
                {
                    "appID": app_id,
                    "paths": ["/events/*"],
                }
            ],
        }
    }


def build_assetlinks(settings: Any) -> list[dict[str, Any]]:
    fingerprints = [
        fingerprint.strip()
        for fingerprint in settings.android_sha256_cert_fingerprints.split(",")
        if fingerprint.strip()
    ]
    if not fingerprints:
        return []

    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": settings.android_package_name,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]


def build_event_fallback_html(
    *,
    event_id: str,
    share_base_url: str,
    deep_link_url: str,
    ios_app_store_url: str,
    android_play_store_url: str,
) -> str:
    safe_event_id = html.escape(event_id, quote=True)
    safe_deep_link = html.escape(deep_link_url, quote=True)
    safe_https_link = html.escape(f"{share_base_url.rstrip('/')}/events/{event_id}", quote=True)
    safe_ios_store = html.escape(ios_app_store_url, quote=True)
    safe_android_store = html.escape(android_play_store_url, quote=True)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Salvaí event</title>
  <meta name="description" content="Open this event in Salvaí." />
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #edf1fd;
      color: #1a1a1a;
      padding: 24px;
    }}
    main {{
      max-width: 420px;
      width: 100%;
      background: #fff;
      border-radius: 20px;
      padding: 32px 24px;
      box-shadow: 0 12px 40px rgba(26, 26, 26, 0.08);
      text-align: center;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 1.5rem;
    }}
    p {{
      margin: 0 0 20px;
      color: #5c6670;
      line-height: 1.5;
    }}
    a {{
      display: block;
      margin: 10px 0;
      padding: 14px 18px;
      border-radius: 999px;
      text-decoration: none;
      font-weight: 600;
    }}
    .primary {{
      background: #a1d0fd;
      color: #0f172a;
    }}
    .secondary {{
      background: #f3f4f6;
      color: #111827;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Open in Salvaí</h1>
    <p>This link opens an event inside the Salvaí app.</p>
    <a class="primary" id="open-app" href="{safe_deep_link}">Open app</a>
    <a class="secondary" id="open-ios" href="{safe_ios_store}">Download on the App Store</a>
    <a class="secondary" id="open-android" href="{safe_android_store}">Get it on Google Play</a>
  </main>
  <script>
    (function () {{
      var deepLink = "{safe_deep_link}";
      var httpsLink = "{safe_https_link}";
      var iosStore = "{safe_ios_store}";
      var androidStore = "{safe_android_store}";
      var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
      var isAndroid = /Android/.test(navigator.userAgent);

      function redirect(url) {{
        window.location.href = url;
      }}

      redirect(deepLink);

      window.setTimeout(function () {{
        if (document.hidden) return;
        if (isIOS) {{
          redirect(iosStore);
          return;
        }}
        if (isAndroid) {{
          redirect(androidStore);
          return;
        }}
        redirect(httpsLink);
      }}, 1500);
    }})();
  </script>
</body>
</html>"""


@router.get("/.well-known/apple-app-site-association")
def apple_app_site_association() -> JSONResponse:
    settings = get_settings()
    payload = build_apple_app_site_association(settings)
    return JSONResponse(content=payload, media_type="application/json")


@router.get("/.well-known/assetlinks.json")
def android_assetlinks() -> JSONResponse:
    settings = get_settings()
    payload = build_assetlinks(settings)
    return JSONResponse(content=payload, media_type="application/json")


@router.get("/events/{event_id}", response_class=HTMLResponse)
def event_share_fallback(event_id: str) -> Response:
    if not _is_valid_event_id(event_id):
        return Response(status_code=404, content="Not found")

    settings = get_settings()
    deep_link_url = f"salvai://events/{event_id}"
    html_body = build_event_fallback_html(
        event_id=event_id,
        share_base_url=settings.share_base_url,
        deep_link_url=deep_link_url,
        ios_app_store_url=settings.ios_app_store_url,
        android_play_store_url=settings.android_play_store_url,
    )
    return HTMLResponse(content=html_body)
