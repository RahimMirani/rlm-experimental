from dataclasses import dataclass


@dataclass
class PaymentResult:
    status: str
    gateway_reference: str


class PaymentsGateway:
    """
    The external gateway deduplicates capture requests by exact merchant_reference.
    If the first request returns an uncertain status and the caller retries with a
    different merchant_reference, the gateway may create a second charge.
    """

    def capture(
        self,
        *,
        amount_cents: int,
        currency: str,
        card_token: str,
        merchant_reference: str,
    ) -> PaymentResult:
        if merchant_reference.endswith(":timeout"):
            return PaymentResult(status="processing", gateway_reference="gw-pending-001")
        return PaymentResult(status="captured", gateway_reference=f"gw-{merchant_reference}")


class StorageSigner:
    def sign_download(self, storage_key: str, expires_in_seconds: int) -> str:
        return f"https://downloads.example.invalid/{storage_key}?ttl={expires_in_seconds}"
