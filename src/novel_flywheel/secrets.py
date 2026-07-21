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

    def set(self, provider_id: str, value: str) -> None:
        keyring.set_password(self.SERVICE, provider_id, value)

    def get(self, provider_id: str) -> str | None:
        return keyring.get_password(self.SERVICE, provider_id)

    def delete(self, provider_id: str) -> None:
        try:
            keyring.delete_password(self.SERVICE, provider_id)
        except PasswordDeleteError:
            pass
