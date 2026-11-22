"""Payment provider abstraction. No provider is hardcoded into billing.

- `test`   : sandbox only (env dev/test). 'test_ok' succeeds, 'test_fail' declines. Never enabled in production.
- `manual` : staff records an out-of-band payment (bank transfer, cheque). Needs a reference.
- real gateways (Stripe, ...) are NOT implemented; selecting one raises NotImplementedError -> HTTP 501.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from ueos.platform.config import get_settings
from ueos.platform.errors import Invalid


@dataclass(frozen=True)
class ChargeResult:
    ok: bool
    ref: str
    reason: str | None = None


class Provider(Protocol):
    name: str

    def charge(self, amount: Decimal, currency: str, method: str) -> ChargeResult: ...


class TestProvider:
    name = "test"

    def charge(self, amount: Decimal, currency: str, method: str) -> ChargeResult:
        if method == "test_ok":
            return ChargeResult(True, f"test_{amount}_{currency}")
        if method == "test_fail":
            return ChargeResult(False, "test_declined", "card_declined")
        raise Invalid("payment_method must be test_ok or test_fail with the test provider")


class ManualProvider:
    name = "manual"

    def charge(self, amount: Decimal, currency: str, method: str) -> ChargeResult:
        if not method.strip():
            raise Invalid("a payment reference is required for manual payments")
        return ChargeResult(True, f"manual:{method.strip()[:80]}")


def get_provider(name: str | None = None) -> Provider:
    s = get_settings()
    n = name or s.payment_provider
    if n == "manual":
        return ManualProvider()
    if n == "test":
        if s.env not in ("dev", "test"):
            raise NotImplementedError("the test payment provider is disabled outside dev/test")
        return TestProvider()
    raise NotImplementedError(f"payment provider '{n}' is not implemented")
