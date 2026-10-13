# RC Cars Launcher (prototype 0.1.3)

A Windows-oriented Python/Qt launcher and modding utility for **RC Cars (2003)**. This is the first functional project scaffold: source code is included; build the Windows EXE locally using the batch file.

## Features in this prototype

- Multiple game instances with custom names and optional icons; Steam detection uses app ID `289460` and `appmanifest_289460.acf`.
- Detects `RCCars.pack`, loose game directories, the WidescreenFix `.asi`/INI, `dinput8.dll`, and the PE Large Address Aware flag.
- Uses `rccars_pack_tool.py` to extract all archive contents **directly into the game root**. Before overwritten loose files are replaced, they are backed up. After successful extraction, the archive is renamed in-place to `_RCCars.pack` (or a timestamped `_RCCars-*.pack` if that name already exists), so the game uses loose files while the original remains recoverable next to the game.
- A single compatibility button installs the latest compiled WidescreenFix release and the official Win32 `dinput8.dll` package from Ultimate ASI Loader.
- Writes WidescreenFix INI values (`Width`, `Height`, `Aspect`, `FixFOV`, `CustomFOV`, `FixHUD`, `LegacyFixHUD`, `FPS/Limit`, `DEBUG/NoMinimize`) while preserving encoding, original CRLF/LF line endings, unrelated settings and comments. Newly created Windows-facing INIs use CRLF.
- Patches two X-resolution and two Y-resolution entries in `RCCars.crs` only if that file exists and the expected record pattern is found. It refuses to write if the expected two records per axis aren't found. An original copy is backed up first.
- Edits `Config.gm` flags for fog, gamma, and intro playback; writes the game's `Language` registry value on Windows. Russian is written as the exact game-specific token `Русский`, while the UI continues to display `Russian`.
- Applies the PE `IMAGE_FILE_LARGE_ADDRESS_AWARE` flag to standalone 32-bit `RCCars.exe` copies, making a backup first. Steam-managed copies and any executable with SteamStub's `.bind` section are protected from EXE modification because wrapper integrity checks may reject a modified executable; if a prior launcher backup exists, the same control can restore it.
- ZIP and optional 7z mod archives under `<game root>\Mods`; ordered overlays are copied into `<game root>\update`. Later mods override earlier files. Original pre-existing files under `update` are backed up and restored when a managed path is no longer supplied. The Mod Manager navigation and page remain disabled until the selected instance is detected as unpacked.
- Runs custom `.exe`, `.py`, `.bat`, `.cmd`, and `.ps1` tools from a `Tools` folder beside the launcher. The Mod Manager UI is disabled until the selected instance is detected as unpacked. Pack detection treats a missing RCCars.pack as unpacked, and also recognizes _RCCars.pack or at least three known loose game folders; the Instances table shows the detected Pack state.
- English/Russian launcher UI applies the selected language immediately; editable `social_links.json`; configurable GitHub-based launcher self-update scaffold.
- Import ZIP/7z mod archives by dragging them onto the Mod Manager page or archive table.
- Detects SteamStub-wrapped executables via the `.bind` PE section and blocks LAA patching even if the Steam EXE was copied outside a Steam library.

## Build a Windows EXE

Build on Windows (preferably Windows 10/11 x64) with Python 3.11 or 3.12 installed. Open the project folder and run:

```bat
build_exe.bat
```

The script creates a **single-file** `dist\RCCarsLauncher.exe`. If `launcher_icon.ico` is present beside `build_exe.bat`, that file is embedded as the EXE icon and bundled for the UI header. Without it, a neutral system icon is shown in the header. Distribute it together with `launcher_config.json`, `social_links.json`, and the `Tools` folder from `dist`. The Qt/Python runtime is bundled into the EXE, which also makes the self-updater able to replace a single executable. Mutable settings, backups, mod profiles and staged updates are stored in a `data` folder next to the launcher EXE. Previous profile data in `%APPDATA%\Aeralise\RCCarsLauncher` is copied to this folder once when no portable `data\launcher.json` exists.

For running from source:

```bat
py -3 -m pip install -r requirements.txt
py -3 launcher.py
```

`py7zr` is optional in concept but included in `requirements.txt`; if omitted, ZIP mods still work and selecting a 7z archive will show an instruction to install py7zr.

## GitHub updates

For the full step-by-step repository/release setup, see [`docs/GITHUB_UPDATES.md`](docs/GITHUB_UPDATES.md).

The combined compatibility installer checks `https://api.github.com/repos/Aeralise/RCCars_WidescreenFix/releases/latest` and chooses compiled `.asi`/`.ini` files from the release assets, then installs Ultimate ASI Loader's `Win32-latest/dinput8-Win32.zip` because RC Cars is a 32-bit game.

The launcher's own self-updater needs a GitHub repository with Releases for the launcher itself. Set `launcher_update_repo` in `launcher_config.json` to `owner/repository`, publish a Release and attach the built `RCCarsLauncher.exe` as an asset. Until then the self-update check will report that the repository is not configured. Update releases should use a matching release tag/version convention.

## Notes / safety

- This app directly writes files to game directories; close the game before applying fixes or mods.
- Keep backups. The app's backup tree is under `data\backups\<instance-id>` beside the launcher.
- The WidescreenFix source currently reads `CustomFOV` with `GetPrivateProfileIntA`, so the UI writes an integer. A decimal value would be ignored/truncated by that config reader until the ASI code itself is changed to read a floating-point value.
- For custom resolutions not listed by the local display modes, the Game Settings page adds the INI's current mode as a selectable combo-box entry. It does not automatically tick **Custom resolution**; that checkbox remains under the user's control.
- For `RCCars.crs`, the code expects two X and two Y records with a marker `01 00 04 00` and a 16-bit little-endian resolution immediately following that marker. If a game build has a different layout, it refuses to modify the file instead of guessing.
- The mod archive's internal paths must be relative to the game root, such as `Textures1\example.dds` or `Settings\Camera.ini`. Do not put the whole mod in an extra wrapper folder unless that wrapper folder is intended to be part of the game path.
- Large Address Aware expands address-space availability only on supported 64-bit Windows hosts; it does not increase physical RAM or guarantee the game can safely allocate more memory. Steam-managed executables are not patched because modifying them can cause Steam launch/integrity errors. If a pristine EXE backup exists and a Steam EXE already has LAA enabled, the LAA control offers to restore that backup.

## Project layout

```text
RCCarsLauncher/
  launcher.py
  rccars_pack_tool.py
  launcher_config.json
  launcher_icon.ico       # optional custom icon; add your own .ico file
  docs/GITHUB_UPDATES.md
  social_links.json
  requirements.txt
  build_exe.bat
  rccars_launcher/
    services.py
    modmanager.py
    ui.py
  Tools/
```

## Launcher self-update release asset

Name the release asset `RCCarsLauncher.exe`. The updater downloads the release EXE to a staging folder and uses a small Windows command script to replace the running executable after it exits. This assumes a single-file PyInstaller build (the provided build script uses `--onefile`).

## Run regression tests

From the project directory, run `py -3 -m pytest -q`. The current test suite covers INI line endings, Pack extraction/renaming, CRS and Config.gm patching, language mapping, LAA behavior, and mod overlays. Qt drag-and-drop and immediate UI language switching should also be smoke-tested on Windows after installing requirements.
