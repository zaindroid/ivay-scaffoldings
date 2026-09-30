"""Merchant platform protocol (spec 9.4): what a shop's own data can answer.

Each audit returns counts of covered and total items. The numbers feed the content coverage
index in the shop config and the grounded-answer coverage gate (spec 2, number 3).
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Coverage:
    covered: int
    total: int
    # Facts the audit could not establish (for example a truncated page). Never hidden.
    warnings: tuple[str, ...] = field(default=(), compare=False)

    @property
    def share(self) -> float | None:
        return None if self.total == 0 else self.covered / self.total


@dataclass(frozen=True)
class ShippingCoverage(Coverage):
    complete: tuple[str, ...] = field(default=(), compare=False)
    incomplete: tuple[str, ...] = field(default=(), compare=False)


class MerchantPlatform(Protocol):
    async def audit_shipping(self) -> Coverage:
        """Shipping countries with complete rates, out of all shipping countries."""
        ...

    async def audit_returns(self) -> Coverage:
        """Whether a return policy exists: covered 1 of 1, or 0 of 1."""
        ...

    async def audit_sizing(self) -> Coverage:
        """Products with a size chart, out of all products."""
        ...
