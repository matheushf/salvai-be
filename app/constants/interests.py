ALLOWED_INTERESTS: frozenset[str] = frozenset(
    {
        "music",
        "sports",
        "food",
        "travel",
        "art",
        "tech",
        "fitness",
        "nightlife",
        "outdoors",
        "movies",
    }
)

MAX_INTERESTS = 5


def normalize_interests(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []

    for raw in values:
        slug = raw.strip()
        if not slug:
            continue
        if slug not in ALLOWED_INTERESTS:
            raise ValueError(f"Unknown interest: {slug}")
        if slug in seen:
            continue
        seen.add(slug)
        normalized.append(slug)
        if len(normalized) > MAX_INTERESTS:
            raise ValueError(f"At most {MAX_INTERESTS} interests allowed")

    return normalized
