# RCCars.crs resolution layout analysis

The supplied `RCCars.crs` is 5,409 bytes. The resolution records are not at fixed offsets across runs, so the launcher locates entries by validated `CSRC` headers and length-prefixed names.

In the attached sample, the decoded 32-bit little-endian values are:

| Key record offset | Setting | Values before patch |
|---:|---|---|
| `0x0C50` | `XResolution` inside `VideoRace` | `1280`, `1920` |
| `0x0C74` | `YResolution` inside `VideoRace` | `720`, `1080` |
| `0x13DB` | second `XResolution` record | `1280`, `1280` |
| `0x13FF` | second `YResolution` record | `720`, `720` |

Each record has a type/size marker `01 00 04 00` followed by two 4-byte integer slots. The previous implementation wrote only a 16-bit value into the first slot of each record. Consequently, the alternate/race value could remain `1920x1080` when the menu setting was changed to `1280x720`.

The updated patcher validates the `CSRC` marker, the key-name length, the NUL terminator, and the type/size marker; it then updates both 32-bit slots in both records for each axis. On this sample, in-memory validation confirmed that all four X slots and all four Y slots are changed to each tested target resolution (1280x720, 1920x1080, and 2560x1440). The uploaded original file was not modified.

The patch is run when saving graphics settings, when applying game settings, and immediately before launching the selected game instance. If records are missing, malformed, or truncated, the patcher raises an error before modifying any bytes.
