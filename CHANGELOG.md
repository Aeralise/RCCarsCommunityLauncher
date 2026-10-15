# Changelog

## 0.1.4
- Wrap every content page in a vertical scroll area to prevent controls/text from being compressed on smaller windows; reduce minimum window size.
- Make WidescreenFix + ASI Loader action install missing components and check/update only changed official releases using recorded release tokens and local SHA-256 checks. Existing WidescreenFix INI settings remain untouched.
- Defer initial filesystem/status refresh until after the window is shown and refresh only essential Home data on startup.
- Switch from PyInstaller one-file to one-directory build with runtime modules in `_runtime` to avoid unpacking Qt/Python runtime on every startup.
- Generate `RCCarsLauncher_Portable.zip` for GitHub Releases and update the self-updater to stage/swap the EXE plus `_runtime`, preserving user data/config/tools.

## 0.1.3
- Detect Pack as unpacked for new instances when RCCars.pack is absent and retained archive or known loose game folders are present.
- Show Pack status in the Instances table.
- Move Pack extraction and LAA controls to the Home page beside the combined WidescreenFix + ASI Loader installer.
- Replace the separate Game Setup / Graphics pages with one Game Settings page containing graphics options, Config.gm checkboxes, and in-game language selection.
- Embed and show optional `launcher_icon.ico`; remove the orange RC placeholder. Place the final icon file in the project root before building.
- Add detailed GitHub repository, Releases, and auto-update setup guide.

## 0.1.2
- Added drag-and-drop import for ZIP/7z mod archives over the Mod Manager page and table.
- Launcher language now changes immediately when the selection changes; removed the Apply language button and obsolete restart notice.
- Detects SteamStub-protected PE executables by their `.bind` section and blocks LAA changes even if the Steam EXE is outside the Steam library path.
- Updated the LAA test coverage for SteamStub detection.

## 0.1.1

- Retain `RCCars.pack` in the game directory by renaming it to `_RCCars.pack` after a successful extraction; use a timestamped name if the target already exists.
- Preserve existing INI encoding and line-ending style when updating WidescreenFix settings; create new Windows-facing INIs with CRLF.
- Do not auto-check Custom resolution for an INI resolution missing from the display-mode list; add that resolution to the dropdown instead. Preserve an explicit Custom checkbox choice for the current instance during refreshes.
- Write `Русский` into the game language registry setting for Russian, and normalize it back to the `Russian` UI choice when loading.
- Refuse to set the LAA flag on Steam-managed game copies. If the Steam EXE is already patched and a baseline backup is available, offer restoration.
- Replace separate WidescreenFix/ASI Loader install buttons with one combined installer action.
- Store settings, backups, mod profiles, and update staging files in a `data` directory beside the launcher; migrate the old AppData profile once when needed.
- Disable the Mod Manager page until the selected instance is detected as unpacked.
- Add regression tests for the fixes above.
