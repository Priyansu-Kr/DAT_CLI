from typing import Any, Dict
from dat.commands.base import BaseCommand
from dat.utils.exit_codes import ExitCode


class MCPCommand(BaseCommand):
    """Starts the DAT MCP stdio server. Blocks until stdin closes (EOF) or
    the process receives an interrupt - this is meant to be launched by an
    MCP client (Claude Desktop, Claude Code, etc.), not run interactively.
    """

    def execute(self, args: Dict[str, Any]) -> ExitCode:
        from dat.mcp.server import DATMCPServer, configure_logging

        configure_logging(args.get("log_level") or "WARNING")
        server = DATMCPServer(container=self.container)
        server.run_stdio_loop()
        return ExitCode.SUCCESS
