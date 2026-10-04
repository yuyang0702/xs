from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import keyring
from keyring.errors import PasswordDeleteError


class SecretStore(Protocol):
    def set(self, provider_id: str, value: str) -> None: ...

    def get(self, provider_id: str) -> str | None: ...

    def delete(self, provider_id: str) -> None: ...


class MemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, provider_id: str, value: str) -> None:
        self._values[provider_id] = value

    def get(self, provider_id: str) -> str | None:
        return self._values.get(provider_id)

    def delete(self, provider_id: str) -> None:
        self._values.pop(provider_id, None)

    def __repr__(self) -> str:
        return "MemorySecretStore(<redacted>)"


class KeyringSecretStore:
    SERVICE = "novel-flywheel-console"

    @classmethod
    def _read_password(cls, provider_id: str) -> str | None:
        """Read one secret in a keyring-compatible worker context.

        Windows Vault can return an empty result when the lookup is made from
        the async event-loop thread, while the same user session is readable
        from a normal worker thread.  Retry only the local read in a bounded
        executor; this never changes the provider route or sends a request.
        """

        return keyring.get_password(cls.SERVICE, provider_id)

    def set(self, provider_id: str, value: str) -> None:
        keyring.set_password(self.SERVICE, provider_id, value)

    def get(self, provider_id: str) -> str | None:
        value = self._read_password(provider_id)
        if value is not None:
            return value
        # A missing value is ambiguous for the Windows backend: it can mean
        # either an absent credential or a lookup made on the event-loop
        # thread.  A single worker retry preserves fail-closed behavior while
        # allowing the user-level Vault session to be observed by async runs.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="keyring-read") as pool:
            return pool.submit(self._read_password, provider_id).result()

    def delete(self, provider_id: str) -> None:
        try:
            keyring.delete_password(self.SERVICE, provider_id)
        except PasswordDeleteError:
            pass
