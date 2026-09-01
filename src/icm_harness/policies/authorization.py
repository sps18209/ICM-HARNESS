from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorizationPolicy:
    allow_shell: bool = True
    allow_network: bool = True
    allow_production_write: bool = False
    allow_secret_access: bool = False
    require_human_approval_for_merge: bool = True
