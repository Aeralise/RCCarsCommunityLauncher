# RC Cars Launcher (prototype 0.1.6)

A Windows-oriented Python/Qt launcher and modding utility for **RC Cars (2003)**. This is the first functional project scaffold: source code is included; build the Windows EXE locally using the batch file.

## Features in this prototype

- Multiple game instances with custom names and optional icons; Steam detection uses app ID `289460` and `appmanifest_289460.acf`.
- Detects `RCCars.pack`, loose game directories, the WidescreenFix `.asi`/INI, `dinput8.dll`, and the PE Large Address Aware flag.
- Uses `rccars_pack_tool.py` to extract all archive contents **directly into the game root**. Before overwritten loose files are replaced, they are backed up. After successful extraction, the archive is renamed in-place to `_RCCars.pack` (or a timestamped `_RCCars-*.pack` if that name already exists), so the game uses loose files while the original remains recoverable next to the game.
- A single compatibility button checks the latest WidescreenFix release and the official Ultimate ASI Loader `Win32-latest` asset. It installs missing components and downloads/replaces only components whose recorded release token or local SHA-256 has changed; user INI settings are preserved.
- Writes WidescreenFix INI values (`Width`, `Height`, `Aspect`, `FixFOV`, `CustomFOV`, `FixHUD`, `LegacyFixHUD`, `FPS/Limit`, `DEBUG/NoMinimize`) while preserving encoding, original CRLF/LF line endings, unrelated settings and comments. Newly created Windows-facing INIs use CRLF.
- Patches `RCCars.crs` by discovering its length-prefixed `CSRC` records by setting name, regardless of record order. Each X/Y record has two 32-bit little-endian resolution slots; both slots in both records per axis are updated (four X values and four Y values total), so menu and race do not retain different resolutions. The file is checked before writing and backed up first. The selected resolution is also reapplied immediately before launching the game, since the file may be rewritten between sessions.
- Edits `Config.gm` flags for fog, gamma, and intro playback; writes the game's `Language` registry value on Windows. Russian is written as the exact game-specific token `Русский`, while the UI continues to display `Russian`.
- Applies the PE `IMAGE_FILE_LARGE_ADDRESS_AWARE` flag to standalone 32-bit `RCCars.exe` copies, making a backup first. Steam-managed copies and any executable with SteamStub's `.bind` section are protected from EXE modification because wrapper integrity checks may reject a modified executable; if a prior launcher backup exists, the same control can restore it.
- ZIP and optional 7z mod archives under `<game root>\Mods`; ordered overlays are copied into `<game root>\update`. Later mods override earlier files. Original pre-existing files under `update` are backed up and restored when a managed path is no longer supplied. Changing a mod checkbox reconciles `update/` automatically after a short debounce; removing an archive also removes obsolete managed files. After changing mod order, use **Apply enabled mods**.
- Runs custom `.exe`, `.py`, `.bat`, `.cmd`, and `.ps1` tools from a `Tools` folder beside the launcher. The Mod Manager UI is disabled until the selected instance is detected as unpacked. Pack detection treats a missing RCCars.pack as unpacked, and also recognizes _RCCars.pack or at least three known loose game folders; the Instances table shows the detected Pack state.
- English/Russian launcher UI applies the selected language immediately; editable `social_links.json`; configurable GitHub-based launcher self-update scaffold.
- Import ZIP/7z mod archives by dragging them onto the Mod Manager page or archive table. Extracted mod archives are cached under the launcher data directory by archive signature; repeat apply operations reuse cached files and skip copying files already applied from the same mod revision.
- Detects SteamStub-wrapped executables via the `.bind` PE section and blocks LAA patching even if the Steam EXE was copied outside a Steam library.

## Build a Windows EXE

Build on Windows (preferably Windows 10/11 x64) with Python 3.11 or 3.12 installed. Open the project folder and run:

```bat
build_exe.bat
```

The script creates a **one-directory** build under `dist\RCCarsLauncher\`, with `RCCarsLauncher.exe` and the bundled Qt/Python runtime in `_runtime`. It also creates `dist\RCCarsLauncher_Portable.zip`, whose root contains the EXE and `_runtime`; attach this ZIP to GitHub Releases for safe in-app updates. If `launcher_icon.ico` is present beside `build_exe.bat`, it is embedded as the EXE icon and copied beside the app for the UI header. Distribute the complete `RCCarsLauncher` folder, not just the EXE. This build starts faster than PyInstaller's one-file mode because it does not extract the whole runtime into a temporary folder on each launch. Mutable settings, backups, mod profiles and staged updates remain in a `data` folder beside the EXE. Previous profile data in `%APPDATA%\Aeralise\RCCarsLauncher` is copied to this folder once when no portable `data\launcher.json` exists.

For running from source:

```bat
py -3 -m pip install -r requirements.txt
py -3 launcher.py
```

`py7zr` is optional in concept but included in `requirements.txt`; if omitted, ZIP mods still work and selecting a 7z archive will show an instruction to install py7zr.

## GitHub updates

For the full step-by-step repository/release setup, see [`docs/GITHUB_UPDATES.md`](docs/GITHUB_UPDATES.md).

The combined compatibility installer checks the latest WidescreenFix GitHub Release and Ultimate ASI Loader's moving `Win32-latest` x86 asset. It records the upstream release token and installed file SHA-256 per instance: the next click checks for updates, downloads only changed components, and leaves the existing WidescreenFix INI intact. The loader is taken from `Win32-latest/dinput8-Win32.zip` because RC Cars is a 32-bit game.

The launcher's self-updater needs a GitHub repository with Releases. Set `launcher_update_repo` in `launcher_config.json` to `owner/repository` and attach `RCCarsLauncher_Portable.zip` to every release (the updater prefers it over a direct EXE because this is a one-directory build). The ZIP must contain `RCCarsLauncher.exe` and `_runtime/` at its root. Update releases should use tags matching `APP_VERSION`, e.g. `v0.1.6`.

## Notes / safety

- This app directly writes files to game directories; close the game before applying fixes or mods.
- Keep backups. The app's backup tree is under `data\backups\<instance-id>` beside the launcher.
- The WidescreenFix source currently reads `CustomFOV` with `GetPrivateProfileIntA`, so the UI writes an integer. A decimal value would be ignored/truncated by that config reader until the ASI code itself is changed to read a floating-point value.
- For custom resolutions not listed by the local display modes, the Game Settings page adds the INI's current mode as a selectable combo-box entry. It does not automatically tick **Custom resolution**; that checkbox remains under the user's control.
- For `RCCars.crs`, the code validates two actual `CSRC` records for each axis: `CSRC`, a little-endian key-name length, the NUL-terminated `XResolution`/`YResolution` name, the type/size marker `01 00 04 00`, and two following 32-bit little-endian slots. If a game build has a different layout, missing records, or truncated data, it refuses to modify the file instead of guessing.
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

Attach `RCCarsLauncher_Portable.zip` to the release. The archive should contain `RCCarsLauncher.exe` and the `_runtime/` directory directly at its root; the provided build script creates this ZIP automatically. The updater downloads and validates the package, stages the new runtime, waits for the launcher process to exit, swaps `_runtime` and the EXE, then restarts the launcher. It preserves the mutable `data`, `Tools`, `launcher_config.json`, and `social_links.json` belonging to the current installation. A direct `RCCarsLauncher.exe` asset remains a legacy fallback for old one-file releases, but should not be used for new onedir releases.

## Run regression tests

From the project directory, run `py -3 -m pytest -q`. The current test suite covers INI line endings, Pack extraction/renaming, CRS and Config.gm patching, language mapping, LAA behavior, mod overlay cleanup/conflicts, persistent extraction caching, and skipping copies for unchanged files. Qt drag-and-drop and immediate UI language switching should also be smoke-tested on Windows after installing requirements.
