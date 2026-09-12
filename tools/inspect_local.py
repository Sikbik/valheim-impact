"""Capture read-only local tool, game, process and hardware evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def capture(game):
    files = [game / 'valheim_Data/Managed/assembly_valheim.dll',
             game / 'valheim_Data/Managed/UnityEngine.CoreModule.dll',
             game / 'BepInEx/plugins/ValheimImpact/ValheimImpact.Unity.dll']
    files += sorted((game / 'BepInEx').rglob('*.cfg'))
    files += sorted((game / 'BepInEx/plugins').rglob('*.dll'))
    fingerprints = {str(p.relative_to(game)): digest(p) for p in dict.fromkeys(files)
                    if p.is_file() and not p.is_symlink()}
    processes = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            if (proc / 'comm').read_text().strip().lower().startswith('valheim'):
                processes.append({'pid': int(proc.name), 'command': (proc / 'comm').read_text().strip()})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
    devices = []
    for card in Path('/sys/class/drm').glob('card[0-9]*'):
        if '-' in card.name:
            continue
        record = {'card': card.name}
        for name in ['vendor', 'device', 'mem_info_vram_total', 'mem_info_vram_used']:
            file = card / 'device' / name
            if file.exists():
                record[name] = file.read_text().strip()
        if 'vendor' in record:
            devices.append(record)
    dotnet = shutil.which('dotnet')
    return dict(captured_at=datetime.now(timezone.utc).isoformat(), game_root=str(game),
        os=platform.platform(), machine=platform.machine(), processes=processes,
        gpu_sysfs=devices, memory=Path('/proc/meminfo').read_text().splitlines()[:3],
        tools={name: shutil.which(name) for name in ['dotnet', 'python', 'git', 'magick', 'glslangValidator', 'Unity']},
        dotnet_info=subprocess.run([dotnet, '--info'], capture_output=True, text=True).stdout if dotnet else None,
        installation_sha256=fingerprints,
        current_game_frame_times=None, new_overhaul_vram=None,
        note='Idle hardware observation and install fingerprints, not a game performance baseline.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--output', default=ROOT / 'local/evidence/baseline.json', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    result = capture(args.game.resolve())
    if args.compare:
        before = json.loads(args.compare.read_text())['installation_sha256']
        after = result['installation_sha256']
        result['installation_changed'] = [k for k in before.keys() | after.keys() if before.get(k) != after.get(k)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'output': str(args.output), 'processes': result['processes'],
        'fingerprints': len(result['installation_sha256']), 'changed': result.get('installation_changed')}))
