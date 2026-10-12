"""Entry point for PyInstaller (avoids the indirect console_scripts import)."""

import sys


def self_check(report: str) -> int:
    """`DrDeconstruct.exe --self-check report.txt`: checks the bundle, used by the release build."""
    from drdeconstruct import __version__
    from drdeconstruct.doctor import bundle_self_check

    results = bundle_self_check()
    lines = [f"DrDeconstruct {__version__}"]
    lines += [f"{'OK  ' if ok else 'FAIL'} {name}: {detail}" for name, ok, detail in results]
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        raise SystemExit(self_check(sys.argv[2]))
    from drdeconstruct.gui.app import main

    raise SystemExit(main())
