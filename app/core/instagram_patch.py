"""
Monkey-patch instaloader's ``doc_id_graphql_query`` for Instagram API changes.

Instagram started returning 403 Forbidden for POST requests to
/graphql/query.  This patch switches the request method to GET.

It also applies the doc_id fix from instaloader PR #2696 for Profile
metadata queries (stale doc_id + missing relay variables).

Import this module before any instaloader usage.  Once instaloader ships
an official fix, this entire module can be deleted.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from instaloader.instaloadercontext import InstaloaderContext, copy_session

# Profile doc_id fix from https://github.com/instaloader/instaloader/pull/2696
_STALE_PROFILE_DOC_ID = "25980296051578533"
_FIXED_PROFILE_DOC_ID = "27937681195819736"
_PROFILE_EXTRA_VARS = {
    "__relay_internal__pv__PolarisWebSchoolsEnabledrelayprovider": False,
    "enable_integrity_filters": True,
}

_original = InstaloaderContext.doc_id_graphql_query


def _patched_doc_id_graphql_query(
    self: InstaloaderContext,
    doc_id: str,
    variables: dict[str, Any],
    referer: str | None = None,
) -> dict[str, Any]:
    # Apply Profile metadata fix when the stale doc_id is detected.
    if doc_id == _STALE_PROFILE_DOC_ID:
        doc_id = _FIXED_PROFILE_DOC_ID
        variables = {**variables, **_PROFILE_EXTRA_VARS}

    # Instagram returns 403 for POST to /graphql/query – switch to GET.
    with copy_session(self._session, self.request_timeout) as tmpsession:
        tmpsession.headers.update(self._default_http_header(empty_session_only=True))
        del tmpsession.headers["Connection"]
        del tmpsession.headers["Content-Length"]
        tmpsession.headers["authority"] = "www.instagram.com"
        tmpsession.headers["scheme"] = "https"
        tmpsession.headers["accept"] = "*/*"
        if referer is not None:
            tmpsession.headers["referer"] = urllib.parse.quote(referer)

        variables_json = json.dumps(variables, separators=(",", ":"))

        resp_json = self.get_json(
            "graphql/query",
            params={
                "variables": variables_json,
                "doc_id": doc_id,
                "server_timestamps": "true",
            },
            session=tmpsession,
            use_post=False,  # ← was True; GET avoids 403
        )
    if "status" not in resp_json:
        self.error('GraphQL response did not contain a "status" field.')
    return resp_json


InstaloaderContext.doc_id_graphql_query = _patched_doc_id_graphql_query  # type: ignore[method-assign]
