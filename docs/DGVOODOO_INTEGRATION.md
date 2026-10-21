# dgVoodoo integration

The launcher checks the official `dege-diosg/dgVoodoo2` GitHub Releases endpoint and selects the full distribution ZIP matching the latest tag. It does not use a third-party mirror.

The game is 32-bit, so installation extracts only these files to the selected game root:

- `dgVoodooCpl.exe`, kept under its official filename;
- `dgVoodoo.conf`;
- `MS/x86/D3D8.dll`, installed as `d3d8.dll`.

The installer forces `[General] EnumerateRefreshRates = true` and `[DirectX] dgVoodooWatermark = false`. Other configuration values are preserved. New configurations use `Filtering = bilinear` and `Antialiasing = appdriven` by default. The Game Settings page controls:

- `[DirectX] Resolution = h:<width>, v:<height>, refrate:<Hz>`;
- `[DirectX] DisableAndPassThru = true|false`;
- `[DirectX] Filtering = appdriven|pointsampled|bilinear|pointmip|linearmip|trilinear|2|4|8|16`;
- `[DirectX] Antialiasing = appdriven|off|2x|4x|8x`;
- `[DirectXExt] DepthBuffersBitDepth = appdriven|forcemin24bit|force32bit`.

If dgVoodoo has not been installed yet, these values are saved per instance under the launcher's `data/backups/<instance-id>/dgvoodoo_settings.json` and applied when installation occurs. Existing configuration is backed up before edits. The installer records the official release tag and installed file hashes, enabling later update checks while leaving user settings intact.

## Clean EXE references

The project stores SHA-256 fingerprints of the supplied clean standalone and Steam EXE samples rather than redistributing either game executable. If a newly added instance does not match the appropriate reference, the launcher warns and stores the found executable under `data/backups/<instance-id>/RCCars.exe`. A SHA mismatch is a diagnostic warning, not proof of malware: it can also mean an existing legitimate patch or a different game build.
