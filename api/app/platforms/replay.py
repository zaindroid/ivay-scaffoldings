"""A GraphQLClient that replays stored responses instead of calling Shopify.

Used by the tests and by `audit_merchant_data.py --dry`. A fixture maps an operation name to a
list of responses, one per page, returned in order.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.platforms.shopify import ShopifyError

SAMPLE_DIR = Path(__file__).parent / "sample_data"


class ReplayClient:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        # keys starting with an underscore are comments in the fixture file
        self._responses = {k: list(v) for k, v in responses.items() if not k.startswith("_")}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @classmethod
    def from_file(cls, path: Path) -> "ReplayClient":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        m = re.search(r"\b(?:query|mutation)\s+(\w+)", query)
        if m is None or m.group(1) not in self._responses:
            raise ShopifyError(f"no recorded response for operation {m.group(1) if m else '?'}")
        self.calls.append((m.group(1), dict(variables or {})))
        pages = self._responses[m.group(1)]
        if not pages:
            raise ShopifyError(f"recorded responses for {m.group(1)} are exhausted")
        return pages.pop(0)
