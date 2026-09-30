"""Shopware is a stub in Phase 0 (spec 9.4)."""

from app.platforms.base import Coverage


class ShopwarePlatform:
    async def audit_shipping(self) -> Coverage:
        raise NotImplementedError("Shopware is not supported in Phase 0")

    async def audit_returns(self) -> Coverage:
        raise NotImplementedError("Shopware is not supported in Phase 0")

    async def audit_sizing(self) -> Coverage:
        raise NotImplementedError("Shopware is not supported in Phase 0")
