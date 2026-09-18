# Neptune on Linux

Based on upstream **v1.1.5** (`e1117f2`).

Neptune is a Windows tool. This is it running natively on Linux: same UI, same feature modules,
same offsets. A small C++ helper runs inside the game's Proton prefix and does the Windows-only
work over a loopback socket. No Wine, no .NET, no WebView.

---

## Using it

### What you need

- 64-bit Linux, either X11 or Wayland with XWayland
- Steam, with Forza Horizon 6 installed and running through Proton
- `protontricks` (on Arch and CachyOS: `sudo pacman -S protontricks`)
- Python 3 with venv, and `mingw-w64-gcc` if you build the helper yourself

A packaged build already contains the helper, so most people can skip the compiler.

### Installing from source

```sh
git clone <repo> && cd Neptune
python3 -m venv .venv
.venv/bin/python -m pip install -r linux/requirements.lock
python3 linux/build_helper.py
./linux/run
```

If your copy of the game isn't under the default Steam app ID, pass yours:

```sh
NEPTUNE_STEAM_APPID=1234560 ./linux/run
```

Settings go in `$XDG_DATA_HOME/neptune-native`, and the helper log is at
`$XDG_STATE_HOME/neptune-native/proton.log`.

### Attaching

Start Forza Horizon 6 first, then start Neptune. Neptune warms the helper while you're looking at
the window, so the first attach is mostly waiting on Proton's container to come up. Click the
attach button in the top bar, watch the status line, and the pages fill in once it says the car
is ready. Later attaches in the same session are quick.

If it fails, read the helper log. It usually says why.

### Pages

Engine, Turbo, Transmission, Suspension, Car, Dyno, Logs, Tunes, Presets and Settings.

### Section toggles

Engine, Turbo, Transmission, Suspension and Dyno each have a master toggle at the top. Nothing
in a section reaches the game until you turn it on, and turning it off writes that section's
stock values back straight away. You don't have to reset values first. Presets remember the
toggle state.

### Grip

The Suspension page has a Grip card:

- **Cornering** scales lateral grip
- **Straight-line** scales longitudinal grip
- **Both** moves the two together
- **Reset to stock grip** puts them back

Range is 1.00x to 3.00x, with 1.00x being stock.

Start lower than you think. Cornering grip in particular can transform a car at values that look
small, and how much it changes varies a lot between cars. Try 1.05 to 1.10 and go up in steps of
0.05. It won't fix inside-wheel lift either. That's weight transfer, and adding grip makes it
worse.

Under the same card there's a live per-wheel friction readout. It's display only.

### Multipliers across cars

Engine torque and Turbo multipliers stay where you set them when you change cars. The port
re-applies the relative multiplier to the new car's own stock curve. Everything else
car-specific, like the rev limit and the custom curve, resets the way upstream intends.

### Restoring and quitting

**Restore everything** writes every section's stock values back without switching the sections
off. Quitting does the same when *restore on exit* is on, then releases the helper and closes the
window.

---

## For the maintainer

### How it attaches

The feature layer isn't duplicated. Upstream's `Process` is the seam.

`neptune_linux/bridge/main.cpp` is a statically linked C++17 helper, no CLR and no WebView. It
gets launched inside the game's Proton prefix through `protontricks` and speaks an authenticated
loopback protocol: HMAC token, framed messages, 20 MB cap. `neptune_linux/process.py` implements
upstream's `Process` on top of it.

`runtime.py` and `shell.py` subclass upstream's `Runtime` and `Shell`; only attach and teardown
differ. `control.py` holds the `wrap_module` machinery and the display cache bypass.

The shared tree gained about fourteen small `sys.platform` import switches, and the adapter is
imported at the bottom of `core/input.py`, `core/wheels.py`, `memory/process.py` and
`ui/gamewindow.py`.

### Layout

```
neptune_linux/    adapter: transport, process, runtime, shell, control, dispatch, prewarm,
                  input, wheels, gamewindow, bridge/main.cpp
linux/            build_helper.py, run, requirements.lock, tests/, smoke_ui.py,
                  test_overlay.py, validate_live.py, check_upstream.py, upstream.json
.github/workflows/linux-port.yml   build helper, run tests, render pages, overlay test
```

### Building and checking

```
python3 linux/build_helper.py                              # mingw-w64
.venv/bin/python -m unittest discover -s linux/tests       # 52 tests
QT_QPA_PLATFORM=offscreen .venv/bin/python linux/smoke_ui.py /tmp/captures
xvfb-run -a .venv/bin/python linux/test_overlay.py
.venv/bin/python linux/validate_live.py                    # read-only; needs the game
```

### Things that cost me time

These all came out of running it, and they explain why parts of the port look the way they do.

Every helper call used to take 41 ms. The helper was sending each response as two small TCP
segments, so Nagle held the second one waiting for a delayed ACK. A section disable is about
fifteen writes, so that was roughly 600 ms per toggle, and restores or closing were worse.
Sending the header and payload as one segment and setting `TCP_NODELAY` on both ends brought it
down to 0.1 ms.

Overlays have to be built on the GUI thread. `on_attach` runs on the runtime thread and
constructs overlay `QWidget`s, and doing that off the GUI thread leaves Qt's font engines bound
to the wrong thread. The process dies later with SIGSEGV, far away from the cause.
`wrap_module` posts any `_ensure_*overlay`, `_build_*overlay` or `_create_*overlay` method to the
GUI thread.

Restore and teardown must not run on the GUI thread either. They're a long series of synchronous
helper calls, and running them inline froze the window badly enough that the desktop marked it
unresponsive. `reset_controls` and the overlay lifecycle still run on the GUI thread because they
touch widgets; the memory writes go to a worker.

The display cache must never hand the UI a `None`. Writes cleared the whole cache and a miss
returned `None`, so the torque graph blanked for a frame every time a tune re-applied. Writes now
patch the overlapping cache entries, and a cold key is read synchronously.

Overlay windows are matched by `_NET_WM_PID`, with the title only as a fallback. Titles get
translated and change between builds.

The helper protocol carries a version in its greeting. A newer helper is refused at connect with
a message telling you to rebuild, instead of failing somewhere in the middle of a tune.

Data writes no longer force `PAGE_EXECUTE_READWRITE`. A plain write is tried first and protection
is only escalated for pages that genuinely aren't writable, then put back.

### Updating from upstream

`linux/upstream.json` records the revision the port was last reviewed against.

```
python3 linux/check_upstream.py --fetch
```

It lists changed files and flags the ones this port touches. It never merges. Review the diff,
merge on a working branch, run the tests and the smoke renderer, then advance the pin.

The contract tests in `linux/tests/test_platform.py` are what stop an upstream change from
slipping through quietly. They check that the import-time seams still point at the Linux
implementations, that the `Process` surface features depend on still exists, and that every
method which constructs an overlay is covered by the GUI-thread guard. They fail in CI when an
upstream interface moves.

### License

GPL-3.0, matching upstream. The helper and transport come from MIT-licensed native work, and that
notice stays in `neptune_linux/bridge/LICENSE-Luna`.
