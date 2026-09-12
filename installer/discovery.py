"""Conservative local Steam discovery and process checks. Never stops processes."""
import csv
import io
import os
from pathlib import Path
import re
import subprocess
import sys


class DetectionError(RuntimeError):
    pass


def running_valheim():
    names = {'valheim', 'valheim.exe', 'valheim.x86_64', 'valheim_server.x86_64', 'valheim_server.exe', 'valheim_server'}
    found = []
    if sys.platform == 'win32':
        try:
            result = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=15, check=True,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for row in csv.reader(io.StringIO(result.stdout)):
                if row and row[0].lower() in names:
                    found.append(row[0] + ' (PID ' + row[1] + ')')
        except (OSError, subprocess.SubprocessError) as error:
            raise DetectionError('Cannot inspect running processes: ' + str(error)) from error
    elif sys.platform.startswith('linux'):
        proc = Path('/proc')
        if not proc.is_dir():
            raise DetectionError('Cannot inspect /proc; refusing changes')
        for process in proc.iterdir():
            if not process.name.isdigit():
                continue
            try:
                comm = (process / 'comm').read_text().strip().lower()
                arguments = (process / 'cmdline').read_bytes().decode(errors='replace').split('\0')
                executable = Path(arguments[0]).name.lower() if arguments else ''
                # Wine may place the Windows executable after the loader.
                wine_game = any(Path(a.replace('\\', '/')).name.lower() in names for a in arguments[:3]) if 'wine' in comm else False
                if comm in names or executable in names or wine_game:
                    found.append((executable or comm) + ' (PID ' + process.name + ')')
            except (FileNotFoundError, ProcessLookupError):
                continue  # Process exited during enumeration.
            except PermissionError as error:
                # Reading another user's command line may be forbidden; its comm is still available.
                try:
                    comm = (process / 'comm').read_text().strip().lower()
                    if comm in names:
                        found.append(comm + ' (PID ' + process.name + ')')
                except (FileNotFoundError, ProcessLookupError):
                    continue  # Process exited during the fallback check.
                except OSError:
                    raise DetectionError('Cannot inspect all running processes; refusing changes') from error
    else:
        raise DetectionError('Process detection is supported on Linux and Windows only')
    return found


def steam_games(home=None, roots=None):
    home = Path(home or Path.home())
    candidates = list(roots or [])
    if roots is None:
        candidates.extend([home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root', home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'])
        for variable in ('PROGRAMFILES(X86)', 'PROGRAMFILES'):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / 'Steam')
        if sys.platform == 'win32':
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                    candidates.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
            except OSError:
                pass
    libraries = set()
    for root in candidates:
        root = Path(root).expanduser()
        libraries.add(root)
        manifest = root / 'steamapps/libraryfolders.vdf'
        try:
            text = manifest.read_text(encoding='utf-8')
            for value in re.findall(r'"path"\s*"([^"\n]+)"', text):
                libraries.add(Path(value.replace('\\\\', '\\')))
            for value in re.findall(r'"\d+"\s*"([^"\n]+)"', text):
                if '/' in value or '\\' in value:
                    libraries.add(Path(value.replace('\\\\', '\\')))
        except OSError:
            continue
    games = set()
    for library in libraries:
        game = library / 'steamapps/common/Valheim'
        if game.is_dir():
            # Resolve Steam's normal discovery links, then validate this canonical folder at install time.
            games.add(str(game.resolve()))
    return sorted(games)
