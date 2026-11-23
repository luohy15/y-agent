from dataclasses import dataclass


@dataclass
class RelayCredential:
    credential_id: str
    user_id: int
    relay_origin: str
    relay_key_id: str
    key_name: str
    billing_mode: str
    api_key: str

    def public_dict(self) -> dict:
        return {
            "configured": True,
            "credential_id": self.credential_id,
            "relay_origin": self.relay_origin,
            "relay_key_id": self.relay_key_id,
            "key_name": self.key_name,
            "billing_mode": self.billing_mode,
        }
