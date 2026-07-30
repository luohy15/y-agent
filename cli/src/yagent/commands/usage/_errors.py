class CredentialsMissingError(Exception):
    """The vendor CLI's own credential file doesn't exist (or holds no
    refresh_token) for this provider -- log in with that provider's own CLI
    (`codex login` / `grok login`)."""

    def __init__(self, provider: str):
        super().__init__(f"no vendor credentials found for provider {provider!r}; log in with that provider's own CLI")
        self.provider = provider


class ReauthRequiredError(Exception):
    """The vendor file's stored refresh token was rejected (invalid_grant)
    -- the user must log in again with that provider's own CLI.

    Raised instead of a transport/HTTP error so callers can distinguish a
    dead grant (needs re-login) from a transient network failure.
    """

    def __init__(self, provider: str):
        super().__init__(f"provider {provider!r} needs re-authentication; log in again with that provider's own CLI")
        self.provider = provider
