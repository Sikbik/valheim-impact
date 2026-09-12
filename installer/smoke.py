"""Developer GUI smoke probe; creates no game files and exits automatically."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import font

from .ui import InstallerWindow


def main(output=None):
    root = tk.Tk()
    window = InstallerWindow(root)
    root.update()
    report = dict(tk=tk.TkVersion, title=root.title(), dimensions=[root.winfo_width(), root.winfo_height()],
                  availableFonts=len(font.families()), defaultProfile=window.profile.get(), replacementEnabled=window.replacement.get(),
                  applyDisabled=str(window.apply_button['state']) == 'disabled', realGameMutated=False)
    if report['replacementEnabled'] or not report['applyDisabled'] or report['defaultProfile'] != 'Balanced':
        raise RuntimeError('Unexpected initial installer state')
    if output:
        Path(output).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    root.after(600, root.destroy)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
