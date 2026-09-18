# Neptune on Linux

This is the Windows tool running natively on Linux. I didn't rewrite the tuning layer: the
Python/PySide6 UI, the feature modules and the offsets are all upstream. What's new is a small
C++ helper that runs inside FH6's Proton prefix and does the Windows-only work (process memory,
XInput, keyboard), plus an adapter around it. No .NET, no WebView.

Everything new lives in `neptune_linux/`. The shared tree picked up a few `sys.platform`
switches and nothing else.

Fair warning before you start: physical writes go straight to the game, same as on Windows,
with no confirmation step. Test one section at a time.

## Running from source

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r linux/requirements.lock
python3 linux/build_helper.py
./linux/run
```

Building the helper needs `mingw-w64-gcc`. Running needs Steam, Forza Horizon 6 and
`protontricks`, as your normal desktop user (not root).

Start the game first. Neptune opens disconnected; click the attach button once FH6 is up. If
your copy isn't under Steam app ID 2483190, set `NEPTUNE_STEAM_APPID` to your own.

Settings live in `$XDG_DATA_HOME/neptune-native` (usually `~/.local/share/neptune-native`).
If attach misbehaves, the helper log in `$XDG_STATE_HOME/neptune-native` is the first place to
look.

## AppImage

`./linux/package.sh` produces `dist/Neptune.AppImage`, about 100 MB. Build the helper first and
have PyInstaller in `.venv`. The script fetches appimagetool 1.9.1 (checksum pinned), freezes
the app via `linux/neptune.spec`, assembles the AppDir and packs it.

Normally it mounts through FUSE. Where FUSE isn't available:

```sh
./dist/Neptune.AppImage --appimage-extract-and-run
```

AppRun sets `QT_QPA_PLATFORM=xcb` when a display is present, and strips its own directory out of
`LD_LIBRARY_PATH` so that `protontricks-launch` picks up system libraries rather than the ones
frozen into the bundle.

The AppImage doesn't ship Steam, the game, `protontricks` or a display. Auto-attach follows your
saved setting, so if you switched it off you'll need to click Attach. And a running game only
proves Proton is set up; it says nothing about whether `protontricks` is installed. Install it.

Build it on your own machine and you get an artifact that only runs on machines at least as new
as yours. For a release that anyone can use, build it in the container instead:

```sh
./linux/packaging/run.sh
```

That runs `linux/packaging/Containerfile` (Debian 12, glibc 2.36) and writes the AppImage and its
checksum into `dist/`. Docker needs to be running. The first build pulls an image and downloads
PySide6, so give it a few minutes; after that, source edits rebuild in seconds.

The result needs **glibc 2.36 or newer**. I verified that by running it, not by assuming: it
starts and stays up on Debian 12 and Ubuntu 24.04, and on Ubuntu 22.04 it exits with
`GLIBC_2.36 not found`. So the floor is Debian 12, Ubuntu 23.04/24.04, Fedora 37, or current
Arch. Ubuntu 22.04 and RHEL 9 are older than that and would need a wider build.

It doesn't self-update. New version, new download.

## Updating from upstream

In a fork checkout `origin` is your fork and `upstream` is `DVS-code/Neptune`; a direct clone
just uses `origin`. `linux/upstream.json` records the upstream revision the port was last
reviewed against.

1. Commit or stash local work first.
2. `.venv/bin/python linux/check_upstream.py --fetch` lists what changed upstream and flags the
   files this port touches. It never merges anything.
3. Read the diff, paying attention to offsets, the `Process` API, input bindings, runtime
   ownership and any new feature modules.
4. Merge into your port branch and fix up the platform switches. Rebuild the helper if the
   protocol or the C++ changed.
5. Run the tests, the smoke renderer and the overlay test, then `linux/validate_live.py` with
   the game running. That one only reads.
6. Advance the revision in `linux/upstream.json` once you've actually validated it, not before.

The Windows updater doesn't apply here. Update by merging source, not by dropping in an
upstream EXE.

## What's verified, and what isn't

The test suite is 52 tests, covering the adapter and lifecycle, the display cache, input dropout,
async teardown, the helper greeting and the port/upstream contract checks. The smoke renderer
draws every page headless; the overlay test checks X Shape click-through and anchor geometry.

Keyboard and controller input go through the helper. You bind while attached; with nothing
attached, everything reads as released.

Engine, turbo, suspension and transmission writes have been exercised in game, along with
restore and car switching. A helper round trip is about 0.1 ms now, so section toggles and
restores are instant.

Racing wheel buttons and hats come from `/dev/input/js*`, matched by vendor and product. I
haven't tested a physical wheel. No device permissions are changed.

Overlays (boost, dyno, logs) track the game window over X11 and use X Shape for click-through.
They match on `_NET_WM_PID` first and fall back to the title. Geometry and click-through pass on
throwaway windows; I haven't verified stacking over the real fullscreen game. Native Wayland
without XWayland isn't supported. The launcher opts into xcb when `DISPLAY` is set, which covers
KDE Wayland through XWayland.

Protected writes and thread suspension fail on purpose. Nothing in the current upstream revision
needs them.

Car image extraction may need `NEPTUNE_GAME_EXE` pointed at the Linux path of the game binary.

Engine and turbo multipliers survive a car swap. The port re-applies the relative multiplier to
the new car's own stock curve; upstream resets it to 1.0. That's the one behavioural difference
you'd notice on Windows too.

## Restores and display

Neutral values (torque 1.00, ride-height offset 0) mean "baseline", not "force this value".
Changing cars resets the tune to the new car's stock.

Writes go straight to the game through the helper, the same as on Windows. `Restore everything`
and detaching both run upstream's `restore` lifecycle, which writes each module's captured stock
values back.

Display reads are cached off the GUI thread, grouped by memory page, and only requested while a
page is visible. Runtime reads in feature code stay live, so the UI isn't paying an IPC round
trip per label.

## License

GPL-3.0, same as upstream (root `LICENSE`). The helper and transport come from MIT-licensed Luna
native work; that notice is kept in `neptune_linux/bridge/LICENSE-Luna`. Ship both with any
release.
