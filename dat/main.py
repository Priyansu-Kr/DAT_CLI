import sys
from dat.cli.args import parse_args
from dat.cli.console import harden_stdio
from dat.cli.formatter import print_banner
from dat.commands.generate_doc import GenerateDocCommand
from dat.commands.doctor import DoctorCommand
from dat.commands.config_cmd import ConfigCommand
from dat.commands.gui_cmd import GuiCommand
from dat.commands.mcp_cmd import MCPCommand
from dat.commands.save_api_key import SaveApiKeyCommand
from dat.utils.exit_codes import ExitCode


def main():
    # Before anything prints: DAT gets run from launchd agents, Xcode build
    # phases, cron and CI containers, where the streams claim an ASCII
    # encoding and any non-ASCII output (a branch name, a path, a status
    # glyph) would otherwise abort the command with UnicodeEncodeError.
    harden_stdio()

    args = parse_args()

    if not args.command:
        print_banner()
        sys.exit(ExitCode.SUCCESS)

    cmd_map = {
        "generate-doc": GenerateDocCommand(),
        "doctor": DoctorCommand(),
        "config": ConfigCommand(),
        "gui": GuiCommand(),
        "mcp": MCPCommand(),
        "save-api-key": SaveApiKeyCommand(),
    }

    command_handler = cmd_map.get(args.command)
    if not command_handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(ExitCode.VALIDATION_ERROR)

    args_dict = vars(args)
    code = command_handler.execute(args_dict)
    sys.exit(code)

if __name__ == "__main__":
    main()
