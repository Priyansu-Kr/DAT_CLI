import sys
from dat.cli.args import parse_args
from dat.cli.formatter import print_banner
from dat.commands.generate_doc import GenerateDocCommand
from dat.commands.screenshot import ScreenshotCommand
from dat.commands.doctor import DoctorCommand
from dat.commands.config_cmd import ConfigCommand
from dat.commands.gui_cmd import GuiCommand
from dat.utils.exit_codes import ExitCode


def main():
    args = parse_args()

    if not args.command:
        print_banner()
        sys.exit(ExitCode.SUCCESS)

    cmd_map = {
        "generate-doc": GenerateDocCommand(),
        "screenshot": ScreenshotCommand(),
        "doctor": DoctorCommand(),
        "config": ConfigCommand(),
        "gui": GuiCommand(),
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
