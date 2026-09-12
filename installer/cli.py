"""Headless preview/apply interface for the same reviewed desktop transactions."""
import argparse
import json
import sys

from . import core
from .discovery import DetectionError, steam_games, running_valheim
from .package import Package, PackageError


def parser():
    result = argparse.ArgumentParser(description='Valheim Impact experimental probe installer. No finished overhaul or measured hardware compatibility claim.')
    commands = result.add_subparsers(dest='command')
    commands.add_parser('gui', help='Open the desktop installer')
    smoke = commands.add_parser('gui-smoke', help='Developer GUI startup check, closes automatically without game writes')
    smoke.add_argument('--output')
    commands.add_parser('detect', help='List local Steam game folders and running Valheim processes')
    package = commands.add_parser('verify-package', help='Verify package integrity without touching a game')
    package.add_argument('package')
    verify = commands.add_parser('verify', help='Check owned installed files without changes')
    verify.add_argument('--game', required=True)
    for name in ('preview', 'apply'):
        command = commands.add_parser(name, help='Preview exact changes' if name == 'preview' else 'Apply a previously reviewed preview token')
        command.add_argument('--game', required=True)
        command.add_argument('--package')
        command.add_argument('--operation', choices=['install', 'update', 'uninstall', 'rollback', 'recover'], default='install')
        command.add_argument('--profile', choices=core.PROFILES, default='Balanced')
        command.add_argument('--enable-game-replacement', action='store_true', help='Explicitly enable experimental material bindings for this install/update')
        if name == 'apply':
            command.add_argument('--review-token', required=True, help='Token from the exact preview you reviewed')
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command in (None, 'gui'):
            from .ui import main as gui
            return gui()
        if args.command == 'gui-smoke':
            from .smoke import main as smoke
            return smoke(args.output)
        if args.command == 'detect':
            result = dict(games=steam_games(), running=running_valheim())
        elif args.command == 'verify-package':
            package = Package.read(args.package)
            result = dict(ok=True, sha256=package.digest, manifest=package.manifest,
                          note='Integrity verified. This unsigned package is an experimental diagnostic/probe build. Obtain it from a trusted source.')
        elif args.command == 'verify':
            result = core.verify(args.game)
        else:
            plan = core.preview(args.game, args.package, operation=args.operation, profile=args.profile, enable_replacement=args.enable_game_replacement)
            if args.command == 'preview':
                result = dict(plan.summary(), reviewToken=plan.token)
            else:
                result = core.apply(plan, reviewed_token=args.review_token, progress=lambda message: print(message, file=sys.stderr))
        print(json.dumps(result, indent=2))
        return 0 if result.get('ok', True) else 1
    except (core.InstallError, PackageError, DetectionError, OSError, RuntimeError) as error:
        print(json.dumps(dict(ok=False, error=str(error)), indent=2), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
