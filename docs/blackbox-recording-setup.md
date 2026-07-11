# Setting up blackbox recording (CLI commands)

Every variable name and value below was pulled directly from
`betaflight/betaflight`'s own firmware source
(`src/main/cli/settings.c`, `src/main/blackbox/blackbox.h`) rather than
guessed -- CLI variable names have changed across Betaflight versions
before (e.g. the old `blackbox_rate_num`/`blackbox_rate_denom` pair was
replaced by the single `blackbox_sample_rate`), so if a `set` below is
rejected on your firmware, run `get blackbox` in the CLI to see what
your installed version actually exposes, rather than assume the command
is wrong.

Paste into Betaflight Configurator's **CLI** tab, then `save` (which
reboots the FC).

## Quick start: onboard flash (most common -- no extra hardware needed)

```
set blackbox_device = SPIFLASH
set blackbox_mode = NORMAL
set blackbox_sample_rate = 1/1
set blackbox_disable_gyrounfilt = OFF
set blackbox_high_resolution = ON
save
```

- `blackbox_mode = NORMAL` -- records automatically whenever you're armed, stops on disarm. (Other options: `MOTOR_TEST` records during the motor test screen too; `ALWAYS` records continuously even disarmed -- burns through flash fast, mainly useful for catching something *before* an arm, e.g. self-test/drift issues.)
- `blackbox_sample_rate = 1/1` -- full rate (every loop iteration logged). This is what you want for filter/noise tuning work -- this tool's noise-heatmap and step-response analysis both want as much resolution as your flash budget allows. Drop to `1/2` if you're filling the flash chip too fast on long flights (halves both file size and time-resolution).
- `blackbox_disable_gyrounfilt = OFF` -- keeps the **pre-filter gyro** logged as its own field (`gyroUnfilt[]`), not just the post-filter `gyroADC[]`. Needed for this tool's "filter noise reduction" finding to have real data to compare against, not just a heuristic guess.
- `blackbox_high_resolution = ON` -- higher-precision field encoding, recommended if your firmware supports it (most modern targets do).

Onboard flash is typically 4-32MB depending on board -- expect a few minutes to ~10 minutes of full-rate logging before you need to erase it (Configurator's Blackbox tab has an **Erase Flash** button; there's no CLI text command for this, it's a binary flash operation done through Configurator or MSC mode).

## Alternative: SD card (if your FC has a slot)

```
set blackbox_device = SDCARD
set blackbox_mode = NORMAL
set blackbox_sample_rate = 1/1
set blackbox_disable_gyrounfilt = OFF
set blackbox_high_resolution = ON
save
```

Same settings, just a different `blackbox_device`. Card must be
**FAT32-formatted**. Effectively unlimited storage (limited by card
size, not flash chip size) -- SD logging also starts a **new file per
arm cycle** rather than appending to one growing file, which is why SD
logs usually come out as `.BFL` with one flight per file (see the
"what are .bbl/.bfl" answer earlier in this conversation for the full
BBL-vs-BFL distinction).

## Alternative: external serial logger (OpenLog, no onboard flash/SD)

```
set blackbox_device = SERIAL
```

then assign the **Blackbox** function to whichever UART your logger is
wired to. The exact `serial <port> <mask>` CLI syntax is port-numbering-
specific to your board, so this one specific step is safer to do in
**Configurator's Ports tab** (toggle "Blackbox" on the right UART) than
to copy a raw `serial` command here that might target the wrong port on
your board.

## Optional: trim fields you don't need

Each of these is independently toggleable (all default OFF, i.e.
captured) -- only disable ones for sensors you don't have or data you
don't care about, to save space/extend recording time:

```
set blackbox_disable_gps = ON        # no GPS module
set blackbox_disable_mag = ON        # no compass
set blackbox_disable_alt = ON        # don't care about altitude/baro
set blackbox_disable_rssi = ON       # don't care about RSSI
```

Do **not** disable `gyro`, `setpoint`, `rc`, `pids`, or `motors` --
those are exactly what this tool's step-response, noise, and propwash
analysis need.

## Manual arm-independent switch (optional)

If you'd rather control logging with a dedicated switch instead of
"always on when armed", assign it in Configurator's **Modes** tab
(add a range on the "Blackbox" mode) rather than via a raw `aux` CLI
command -- the AUX mode-ID number for Blackbox isn't worth guessing at
here when the Modes tab does the same thing safely.

## Extracting the log afterward

Configurator's **Blackbox** tab, while connected via USB: either
**Activate Mass Storage Device Mode** (FC mounts as a USB drive, copy
the `.bbl`/`.bfl` files off directly) or the tab's built-in save/download
button, depending on what your board/firmware supports. There's no CLI
text command for this part -- it's binary data, not something the CLI
console handles.

## Then analyze it

```bash
debrief serve
```
and drop the file in, or:
```bash
debrief analyze mylog.bbl -o report.html
```

## Source

Every setting name/value above is quoted from `betaflight/betaflight`
master at the time of writing:
- [`src/main/cli/settings.c`](https://github.com/betaflight/betaflight/blob/master/src/main/cli/settings.c) -- the CLI variable table and lookup value strings
- [`src/main/blackbox/blackbox.h`](https://github.com/betaflight/betaflight/blob/master/src/main/blackbox/blackbox.h) -- the underlying enums
