"""Read RSS and GPU-wide VRAM for an existing process; never starts/stops games."""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--duration', type=float, default=120)
    parser.add_argument('--interval', type=float, default=.5)
    parser.add_argument('--gpu', type=Path, required=True,
                        help='sysfs mem_info_vram_used path for the selected GPU')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.pid <= 0 or args.duration <= 0 or args.interval < .1:
        parser.error('Positive pid/duration and interval >= 0.1 are required')
    comm = Path('/proc') / str(args.pid) / 'comm'
    if not comm.read_text().strip().lower().startswith('valheim'):
        parser.error('PID is not a Valheim process')
    stat = comm.with_name('stat')
    identity = stat.read_text().rsplit(')', 1)[1].split()[19]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        writer = csv.writer(stream)
        writer.writerow(['utc', 'elapsed_seconds', 'pid', 'rss_kib', 'gpu_wide_vram_bytes'])
        start = time.monotonic()
        while time.monotonic() - start < args.duration:
            try:
                if stat.read_text().rsplit(')', 1)[1].split()[19] != identity:
                    break
                status = comm.with_name('status').read_text().splitlines()
                rss = next(line.split()[1] for line in status if line.startswith('VmRSS:'))
                writer.writerow([datetime.now(timezone.utc).isoformat(), time.monotonic() - start,
                                 args.pid, rss, int(args.gpu.read_text())])
            except (FileNotFoundError, ProcessLookupError):
                break
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
