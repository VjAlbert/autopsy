# Windows packaging

Two artifacts are produced for every release:

| File | What it is |
|---|---|
| `DrDeconstruct-Setup-<version>.exe` | Inno Setup installer (per-user, no admin rights, Start menu + optional desktop shortcut, uninstaller). **Recommended.** |
| `DrDeconstruct-portable.exe` | The PyInstaller one-file build. No installation, run it from anywhere. |
| `SHA256SUMS.txt` | Checksums of both files. |

## Automatic build

Push a tag like `v0.2.0` and `.github/workflows/release.yml` builds everything on a Windows
runner, smoke-tests the exe (it must stay open for 12 seconds), builds the installer and attaches
all files to the GitHub Release. **Actions → Release → Run workflow** does the same as a dry run
and leaves the files as a downloadable run artifact without publishing anything.

## Build locally (Windows 10/11)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e ".[full]" pyinstaller
pyinstaller packaging\drdeconstruct.spec            # -> dist\DrDeconstruct.exe
# optional: the installer (needs Inno Setup 6 from https://jrsoftware.org/isinfo.php)
iscc /DAppVersion=0.1.0 packaging\installer.iss     # -> dist\DrDeconstruct-Setup-0.1.0.exe
```

The icon (`drdeconstruct.ico`) is drawn in code; regenerate it with
`python scripts/make_icon.py` if you change the logo in `src/drdeconstruct/gui/icons.py`.

## Notes

- The exe bundles the GUI and the acquisition modules (serial, USB, Bluetooth).
  `flashrom`, Ghidra and Java stay external: the app's **Start** page checks for them and
  links to the downloads.
- The **Claude** engine needs Claude Code on the PC for the login. The app can open the
  official installer and the login window for the user (buttons on the Start page).
- **Code signing:** the files are not signed, so Windows SmartScreen warns on first launch.
  Signing needs a certificate that cannot be created from the CI environment. Options: a
  commercial OV/EV certificate, [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/),
  or [SignPath Foundation](https://signpath.org/) (free for open-source projects). Once a
  certificate exists, add a `signtool` step before the checksum step of the workflow.
