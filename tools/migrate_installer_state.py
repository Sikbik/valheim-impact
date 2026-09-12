#!/usr/bin/env python3
"""Preview/apply a closed-game migration of legacy installer backup filenames."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import core, state_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('preview', 'apply'))
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--review-token')
    args = parser.parse_args()
    try:
        plan = state_migration.preview(args.game)
        result = plan if args.operation == 'preview' else state_migration.apply(plan, reviewed_token=args.review_token)
        print(json.dumps(result, indent=2))
    except (core.InstallError, OSError, ValueError) as error:
        parser.exit(2, 'State migration stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
