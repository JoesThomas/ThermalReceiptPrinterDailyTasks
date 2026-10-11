from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class FinanceRunState:
    blocked_resources: set[tuple[str, str]] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)

    def should_try(self, provider: str, resource: str) -> bool:
        return (provider.upper(), resource) not in self.blocked_resources

    def record_403(self, provider: str, resource: str, error_code: str) -> None:
        provider = provider.upper()
        if error_code in {"sca_exceeded", "access_denied"}:
            self.blocked_resources.add((provider, resource))
        message = f"{provider} {resource}: {error_code}"
        if message not in self.messages:
            self.messages.append(message)
