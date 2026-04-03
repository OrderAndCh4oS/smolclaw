from typing import Final, Iterable, Literal

Capability = Literal["filesystem", "web", "memory", "orchestration", "subagents", "shell"]
Transport = Literal["direct", "mcp"]

CAPABILITY_FILESYSTEM: Final[str] = "filesystem"
CAPABILITY_WEB: Final[str] = "web"
CAPABILITY_MEMORY: Final[str] = "memory"
CAPABILITY_ORCHESTRATION: Final[str] = "orchestration"
CAPABILITY_SUBAGENTS: Final[str] = "subagents"
CAPABILITY_SHELL: Final[str] = "shell"

KNOWN_CAPABILITIES: Final[frozenset[str]] = frozenset({
    CAPABILITY_FILESYSTEM,
    CAPABILITY_WEB,
    CAPABILITY_MEMORY,
    CAPABILITY_ORCHESTRATION,
    CAPABILITY_SUBAGENTS,
    CAPABILITY_SHELL,
})

DEFAULT_CAPABILITIES: Final[tuple[str, ...]] = (
    CAPABILITY_FILESYSTEM,
    CAPABILITY_WEB,
)


def validate_capabilities(capabilities: Iterable[str]) -> None:
    unknown = sorted(set(capabilities) - KNOWN_CAPABILITIES)
    if unknown:
        supported = ", ".join(sorted(KNOWN_CAPABILITIES))
        raise ValueError(
            f"Unknown capabilities: {', '.join(unknown)}. Supported capabilities: {supported}."
        )


def unsupported_capabilities_for_transport(
    capabilities: Iterable[str],
    transport: Transport,
) -> list[str]:
    unsupported = []
    for capability in capabilities:
        if capability == CAPABILITY_SHELL and transport == "direct":
            unsupported.append(capability)
    return unsupported
