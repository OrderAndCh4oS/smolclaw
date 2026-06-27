from app.runtime_capabilities import CAPABILITY_COMMAND, CAPABILITY_SHELL
from app.tool_providers import ToolProviderContext, register_capability_tools
from app.tools.registry import ToolRegistry
from app.workspace import WorkspaceContext


class ShellCapableRunner:
    supports_shell_sessions = True

    def requires_image_management_approval(self):
        return False


def test_register_capability_tools_uses_explicit_providers(temp_dir):
    registry = ToolRegistry()
    context = ToolProviderContext(
        smol_rag=None,
        workspace=WorkspaceContext.from_root(temp_dir).ensure_dirs(),
        command_runner=ShellCapableRunner(),
    )

    register_capability_tools(
        registry,
        capability_names=[CAPABILITY_COMMAND, CAPABILITY_SHELL],
        context=context,
    )

    assert "run_command" in registry.tool_names()
    assert "shell_session" in registry.tool_names()
