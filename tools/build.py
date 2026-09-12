#!/usr/bin/env python3
"""Compile local runtime artifacts with Roslyn, without an SDK or game writes."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def discover_runtime(dotnet):
    candidates = []
    for line in subprocess.check_output([dotnet, '--list-runtimes'], text=True).splitlines():
        match = re.fullmatch(r'Microsoft.NETCore.App (\d+\.\d+\.\d+) \[(.+)\]', line)
        if match:
            version, base = match.groups()
            candidates.append((tuple(map(int, version.split('.'))), version, Path(base) / version))
    if not candidates:
        raise ValueError('No stable Microsoft.NETCore.App runtime found')
    _, version, path = max(candidates)
    return version, path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, help='Local JSON configuration (keep outside tracked source)')
    parser.add_argument('--test', action='store_true', help='Run engine-independent regression tests')
    parser.add_argument('--game', type=Path, help='Read-only installed Valheim directory')
    parser.add_argument('--roslyn', type=Path, help='Path to local csc.dll')
    args = parser.parse_args()
    config = json.loads(args.config.read_text()) if args.config else {}
    dotnet = config.get('dotnet') or shutil.which('dotnet')
    csc = args.roslyn or os.environ.get('VALHEIM_ROSLYN_CSC') or config.get('roslyn_csc')
    if not dotnet or not csc or not Path(csc).is_file():
        parser.error('Configure dotnet and a valid Roslyn csc.dll using --roslyn, VALHEIM_ROSLYN_CSC, or --config')
    version, runtime = discover_runtime(dotnet)
    out = ROOT / 'build/runtime'
    out.mkdir(parents=True, exist_ok=True)
    core = sorted((ROOT / 'src/ValheimImpact.Core').rglob('*.cs'))

    def compile_cs(output, sources, refs, target):
        for ref in refs:
            if not ref.is_file():
                raise ValueError('Missing read-only compile reference: ' + str(ref))
        subprocess.run([dotnet, '--roll-forward', 'Major', str(csc), '-nologo', '-noconfig',
                        '-nostdlib+', '-langversion:latest', '-optimize+', '-deterministic+',
                        '-target:' + target, '-out:' + str(output)] +
                       ['-reference:' + str(p) for p in refs] + [str(p) for p in sources], check=True)

    if args.test:
        target = out / 'CoreTests.dll'
        compile_cs(target, core + sorted((ROOT / 'tests/runtime').glob('*.cs')), sorted(runtime.glob('*.dll')), 'exe')
        target.with_suffix('.runtimeconfig.json').write_text(json.dumps({'runtimeOptions': {
            'tfm': 'net' + '.'.join(version.split('.')[:2]),
            'framework': {'name': 'Microsoft.NETCore.App', 'version': version}}}))
        subprocess.run([dotnet, str(target)], check=True)
    else:
        game_value = args.game or os.environ.get('VALHEIM_DIR') or config.get('game_dir')
        if not game_value:
            parser.error('Supply --game, VALHEIM_DIR, or game_dir in configuration')
        game = Path(game_value)
        managed = game / 'valheim_Data/Managed'
        refs = [managed / name for name in ['mscorlib.dll', 'System.dll', 'System.Core.dll', 'System.Runtime.Serialization.dll', 'System.Xml.dll', 'netstandard.dll']]
        core_dll = out / 'ValheimImpact.Core.dll'
        compile_cs(core_dll, core, refs, 'library')
        refs += [core_dll, game / 'BepInEx/core/BepInEx.dll']
        refs += [managed / name for name in ['UnityEngine.dll', 'UnityEngine.CoreModule.dll', 'UnityEngine.AssetBundleModule.dll']]
        compile_cs(out / 'ValheimImpact.Unity.dll', sorted((ROOT / 'src/ValheimImpact.Unity').glob('*.cs')), refs, 'library')
        print('Compiled staging artifacts in ' + str(out) + '; no game deployment performed.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
