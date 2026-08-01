from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone


def build_tag_index(
    rows: list[tuple[str, str, list[str]]],
    *,
    threshold: float,
    model: str = "fancyfeast/joytag",
) -> bytes:
    counts = Counter(tag for _, _, tags in rows for tag in set(tags))
    catalog = sorted(counts, key=lambda tag: (-counts[tag], tag))
    tag_ids = {tag: index for index, tag in enumerate(catalog)}
    items = [
        [key, extension, [tag_ids[tag] for tag in tags if tag in tag_ids]]
        for key, extension, tags in rows
    ]
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "threshold": threshold,
        "tagged_count": len(items),
        "catalog": [[tag, counts[tag]] for tag in catalog],
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

