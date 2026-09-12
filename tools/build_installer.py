"""Build a self-contained local installer with the active Python and PyInstaller."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tk-prefix', type=Path, help='Optional locally built Tcl/Tk prefix with desktop font support')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'build/installer')
    parser.add_argument('--name', default='ValheimImpactInstaller-linux-x86_64' if sys.platform.startswith('linux') else 'ValheimImpactInstaller-windows-x86_64')
    args = parser.parse_args()
    import tkinter
    import PyInstaller
    print(f'Building with Python {sys.version.split()[0]}, Tk {tkinter.TkVersion}, PyInstaller {PyInstaller.__version__}', flush=True)
    extra = []
    library_dir = Path(sys.base_prefix) / 'lib'
    for pattern in ('libtcl*.so*', 'libtk*.so*'):
        for library in library_dir.glob(pattern):
            if args.tk_prefix and 'tk' in library.name:
                continue
            extra.extend(['--add-binary', str(library) + ':.'])
    build_environment = dict(os.environ)
    if args.tk_prefix:
        tk_library = args.tk_prefix.resolve() / 'lib/libtcl9tk9.0.so'
        if not tk_library.is_file():
            parser.error('Local Tk prefix lacks ' + str(tk_library))
        extra.extend(['--add-binary', str(tk_library) + ':.'])
        # Keep the active Python's Tcl ABI; only replace its font-limited Tk build.
        build_environment['LD_PRELOAD'] = str(tk_library)
        build_environment['TK_LIBRARY'] = str(tk_library.parent / 'tk9.0')
    if sys.platform.startswith('linux'):
        build_environment['LD_LIBRARY_PATH'] = str(library_dir) + (os.pathsep + build_environment['LD_LIBRARY_PATH'] if build_environment.get('LD_LIBRARY_PATH') else '')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
                    '--name', args.name, '--distpath', str(args.output_dir),
                    '--workpath', str(ROOT/'build/installer-work'), '--specpath', str(ROOT/'build/installer-spec'),
                    '--paths', str(ROOT), *extra, str(ROOT/'installer/__main__.py')], cwd=ROOT, check=True, env=build_environment)
    artifact = args.output_dir / (args.name + ('.exe' if sys.platform == 'win32' else ''))
    subprocess.run([str(artifact), '--help'], check=True)
    print('Built and checked CLI startup: ' + str(artifact))


if __name__ == '__main__':
    main()
