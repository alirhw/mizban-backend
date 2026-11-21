"""Payment gateway adapter interface, sandbox mock, and provider registry.

Task T-020 (PH-05 / WS-BILLING-WALLET / ARCH-005):
- Narrow adapter interface isolating provider request/response mapping from domain services.
- Standard Iranian IPG authority flow: initiate -> authority + redirect URL -> verify by authority.
- SandboxGatewayAdapter: zero-network mock configurable for success, failure, and timeout.
- Provider choice is OPEN: provider specifics remain strictly inside adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import uuid

from django.conf import settings

from core.exceptions import PaymentGatewayError, PaymentGatewayTimeoutError


@dataclass(frozen=True)
class PaymentInitiateRequest:
    """Standardized payment initiation request."""

    amount_toman: int
    callback_url: str
    description: str
    order_id: str
    customer_phone: str = ""
    customer_email: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentInitiateResult:
    """Standardized payment initiation result."""

    success: bool
    authority: str
    redirect_url: str
    raw_status: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class PaymentVerifyRequest:
    """Standardized payment verification request."""

    authority: str
    amount_toman: int
    callback_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentVerifyResult:
    """Standardized payment verification result."""

    success: bool
    status: str  # "SUCCESS", "FAILED", "ALREADY_VERIFIED"
    tracking_code: str = ""
    card_pan_masked: str = ""
    amount_toman: int = 0
    raw_status: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class PaymentStatusResult:
    """Standardized transaction inquiry result."""

    status: str
    amount_toman: int = 0
    tracking_code: str = ""
    card_pan_masked: str = ""
    raw_data: dict[str, Any] = field(default_factory=dict)


class PaymentGatewayAdapter(ABC):
    """Narrow interface isolating payment gateway mechanics from domain logic (ARCH-005)."""

    @abstractmethod
    def initiate(self, request: PaymentInitiateRequest) -> PaymentInitiateResult:
        """Request payment initiation and obtain gateway authority and redirect URL."""
        ...

    @abstractmethod
    def verify(self, request: PaymentVerifyRequest) -> PaymentVerifyResult:
        """Verify transaction server-to-server with the payment gateway."""
        ...

    @abstractmethod
    def get_status(self, authority: str) -> PaymentStatusResult:
        """Query transaction status by gateway authority."""
        ...

    @abstractmethod
    def extract_reference(self, callback_params: dict[str, Any]) -> str:
        """Extract unguessable provider reference from incoming callback parameters."""
        ...


class SandboxGatewayAdapter(PaymentGatewayAdapter):
    """Zero-network deterministic sandbox mock IPG adapter for development and testing.

    Configurable modes:
    - "success": normal successful initiation and verification
    - "failure": simulates gateway rejection
    - "timeout": simulates gateway network timeout (raising PaymentGatewayTimeoutError)
    """

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self._records: dict[str, dict[str, Any]] = {}

    def set_mode(self, mode: str) -> None:
        """Configure simulation mode ('success', 'failure', 'timeout')."""
        valid_modes = {"success", "failure", "timeout"}
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {valid_modes}")
        self.mode = mode

    def reset(self) -> None:
        """Reset mode to 'success' and clear stored records."""
        self.mode = "success"
        self._records.clear()

    def initiate(self, request: PaymentInitiateRequest) -> PaymentInitiateResult:
        """Simulate payment initiation."""
        if self.mode == "timeout":
            raise PaymentGatewayTimeoutError("Sandbox gateway initiate timed out (simulated 8.0s timeout).")

        if self.mode == "failure":
            return PaymentInitiateResult(
                success=False,
                authority="",
                redirect_url="",
                raw_status="-1",
                error_message="Sandbox gateway simulated initiation failure.",
            )

        authority = f"SBX-{uuid.uuid4().hex[:16].upper()}"
        redirect_url = f"https://sandbox.mizban.local/pg/startpay/{authority}"
        self._records[authority] = {
            "amount_toman": request.amount_toman,
            "order_id": request.order_id,
            "tracking_code": f"TRK-{uuid.uuid4().hex[:10].upper()}",
            "card_pan_masked": "603799******1234",
            "verified": False,
        }
        return PaymentInitiateResult(
            success=True,
            authority=authority,
            redirect_url=redirect_url,
            raw_status="100",
            error_message="",
        )

    def verify(self, request: PaymentVerifyRequest) -> PaymentVerifyResult:
        """Simulate server-to-server payment verification."""
        if self.mode == "timeout":
            raise PaymentGatewayTimeoutError("Sandbox gateway verify timed out (simulated 8.0s timeout).")

        if self.mode == "failure":
            return PaymentVerifyResult(
                success=False,
                status="FAILED",
                raw_status="-2",
                error_message="Sandbox gateway simulated verification failure.",
            )

        record = self._records.get(request.authority)
        if record:
            if record["amount_toman"] != request.amount_toman:
                return PaymentVerifyResult(
                    success=False,
                    status="FAILED",
                    amount_toman=record["amount_toman"],
                    raw_status="-3",
                    error_message=f"Amount mismatch: requested {request.amount_toman}, expected {record['amount_toman']}",
                )

            if record["verified"]:
                return PaymentVerifyResult(
                    success=True,
                    status="ALREADY_VERIFIED",
                    tracking_code=record["tracking_code"],
                    card_pan_masked=record["card_pan_masked"],
                    amount_toman=record["amount_toman"],
                    raw_status="101",
                )

            record["verified"] = True
            return PaymentVerifyResult(
                success=True,
                status="SUCCESS",
                tracking_code=record["tracking_code"],
                card_pan_masked=record["card_pan_masked"],
                amount_toman=record["amount_toman"],
                raw_status="100",
            )

        # Authority not in in-memory state (e.g. test fixture created authority directly)
        tracking_code = f"TRK-{uuid.uuid4().hex[:10].upper()}"
        card_pan_masked = "603799******1234"
        return PaymentVerifyResult(
            success=True,
            status="SUCCESS",
            tracking_code=tracking_code,
            card_pan_masked=card_pan_masked,
            amount_toman=request.amount_toman,
            raw_status="100",
        )

    def get_status(self, authority: str) -> PaymentStatusResult:
        """Query status of transaction."""
        record = self._records.get(authority)
        if not record:
            return PaymentStatusResult(status="NOT_FOUND")

        return PaymentStatusResult(
            status="SUCCESS" if record["verified"] else "PENDING",
            amount_toman=record["amount_toman"],
            tracking_code=record["tracking_code"],
            card_pan_masked=record["card_pan_masked"],
            raw_data=record,
        )

    def extract_reference(self, callback_params: dict[str, Any]) -> str:
        """Extract provider reference from sandbox callback parameters.

        Accepts standard provider-agnostic keys: 'provider_reference', 'reference', 'authority'.
        """
        for key in ("provider_reference", "reference", "authority"):
            val = callback_params.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""


_GATEWAY_REGISTRY: dict[str, type[PaymentGatewayAdapter]] = {
    "sandbox": SandboxGatewayAdapter,
}

_GATEWAY_INSTANCES: dict[str, PaymentGatewayAdapter] = {}


def register_gateway(name: str, adapter_cls: type[PaymentGatewayAdapter]) -> None:
    """Register a new payment gateway adapter class by provider name."""
    _GATEWAY_REGISTRY[name.lower()] = adapter_cls


def get_gateway(provider_name: str | None = None) -> PaymentGatewayAdapter:
    """Factory function returning the singleton adapter instance for the specified provider."""
    name = (provider_name or getattr(settings, "PAYMENT_GATEWAY_PROVIDER", "sandbox")).lower()
    if name not in _GATEWAY_INSTANCES:
        adapter_cls = _GATEWAY_REGISTRY.get(name)
        if not adapter_cls:
            raise ValueError(
                f"Unknown payment gateway provider '{name}'. Registered providers: {list(_GATEWAY_REGISTRY.keys())}"
            )
        _GATEWAY_INSTANCES[name] = adapter_cls()
    return _GATEWAY_INSTANCES[name]


def reset_sandbox_gateway() -> SandboxGatewayAdapter:
    """Reset sandbox adapter singleton to default mode and clear in-memory state."""
    adapter = get_gateway("sandbox")
    if isinstance(adapter, SandboxGatewayAdapter):
        adapter.reset()
    return adapter  # type: ignore[return-value]
