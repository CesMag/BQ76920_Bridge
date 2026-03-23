## Description
<!-- What does this PR change and why? -->


## Type of Change
- [ ] Bug fix
- [ ] New feature / peripheral driver
- [ ] CubeMX regeneration (peripheral config change)
- [ ] Refactor / cleanup
- [ ] CI / tooling change
- [ ] Documentation

## Checklist

### Build
- [ ] Firmware builds clean (Debug and Release) — no new warnings
- [ ] No new `cppcheck` warnings in `Core/Src/` (static-analysis job passes)

### Size
- [ ] Flash / RAM usage reviewed in the **size-report** workflow summary
- [ ] Usage increase (if any) is justified in the description above

### Code
- [ ] Register map or I2C protocol changes are documented in a comment or updated in `README.md`
- [ ] CubeMX-managed files (`Drivers/`, `USB_DEVICE/`, `Core/Src/main.c` generated regions) were **not** hand-edited outside `USER CODE` blocks
- [ ] New application code lives in `bq76920.c` / `usb_hid_bridge.c` (or new standalone files), not inlined into CubeMX-generated files

### Hardware
- [ ] Tested on Adafruit Feather STM32F405 with BQ76920 attached
- [ ] N/A — hardware not yet available (pre-arrival stage)

## References
<!-- Link to datasheet section, TI app note, issue, or course lab being addressed -->
