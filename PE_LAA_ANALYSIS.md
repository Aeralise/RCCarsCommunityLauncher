# RC Cars executable comparison: Large Address Aware (LAA)

Files examined:

- `RCCars.exe` — standalone copy supplied for analysis
- `RCCars_steam.exe` — Steam copy supplied for analysis

## Findings

| Property | Standalone `RCCars.exe` | Steam `RCCars_steam.exe` |
|---|---:|---:|
| File size | 1,586,408 bytes (`0x1834E8`) | 2,008,592 bytes (`0x1EA610`) |
| Architecture / optional-header format | x86 / PE32 | x86 / PE32 |
| COFF Characteristics | `0x010F` | `0x010F` |
| LAA (`IMAGE_FILE_LARGE_ADDRESS_AWARE`, `0x0020`) | Off | Off |
| Section count | 5 | 6 |
| `.bind` section | No | Yes |
| Entry-point RVA | `0x0014A21A` | `0x012642F0` |
| `SizeOfImage` | `0x01264000` | `0x012CD000` |
| Security directory | file offset `0x182000`, size `0x14E8` | empty |

The COFF Characteristics field is at file offset `0x12E` in both files. Its two bytes are `0F 01` (little-endian value `0x010F`). Setting the LAA bit alone would turn these bytes into `2F 01` (`0x012F`); this sets only mask `0x0020` and does not move sections or change the entry point.

## Why the Steam executable is different

The Steam copy has an extra `.bind` section mapped at RVA `0x01264000`, stored at file offset `0x182000`, with raw size `0x68610`. Its entry point is inside that section at RVA `0x012642F0`. This is the characteristic layout of a SteamStub-protected executable: the bootstrap code runs first and then transfers control to the game. The standalone copy has no `.bind` section and its entry point is in the original code section.

The Steam file therefore is not merely the standalone EXE with a different filename. Its `.text` section also differs between the two supplied files, while `.rdata`, `.data`, `.data1`, and `.rsrc` have identical raw-section hashes. The Steam copy is 422,184 bytes larger. The `.bind` data begins at the same file offset where the standalone file has its security/certificate table.

References on this PE layout:

- Microsoft PE/COFF specification: `IMAGE_FILE_LARGE_ADDRESS_AWARE` is `0x0020` and means the application can handle addresses above 2 GB: https://learn.microsoft.com/en-us/windows/win32/debug/pe-format
- Steam DRM overview: SteamStub-wrapped executables use a `.bind` section as the DRM bootstrap and change the entry point to execute it first: https://www.pcgamingwiki.com/wiki/User:Cyanic/Steam_DRM
- Steamless code handles the `.bind` section as the SteamStub DRM section: https://github.com/atom0s/Steamless

## Conclusion for the launcher

Both supplied pristine executables have LAA disabled. The standalone copy is eligible for the launcher's normal LAA patch. The Steam executable should not be patched automatically: its `.bind` section identifies it as SteamStub-wrapped, and modifying the executable's PE header can conflict with a protected launch path. The launcher now detects `.bind` even if the file has been copied outside a Steam library.

The two pristine files alone cannot conclusively prove which internal integrity check produced a previous `Application load error 3:0000065432`; that would require comparing the exact failing, LAA-patched Steam EXE against this pristine file. The `.bind` structure makes avoiding this patch the conservative and appropriate behavior.
