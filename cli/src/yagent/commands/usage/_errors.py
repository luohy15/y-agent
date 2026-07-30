class CredentialsMissingError(Exception):
    """No stored grant for this provider yet -- `y usage login <provider>` first."""

    def __init__(self, provider: str):
        super().__init__(f"no stored credentials for provider {provider!r}; run `y usage login {provider}`")
        self.provider = provider


class ReauthRequiredError(Exception):
    """The stored refresh token was rejected (invalid_grant) -- re-login needed.

    Raised instead of a transport/HTTP error so callers can distinguish a
    dead grant (needs `y usage login`) from a transient network failure.
    """

    def __init__(self, provider: str):
        super().__init__(f"provider {provider!r} needs re-authentication; run `y usage login {provider}`")
        self.provider = provider
