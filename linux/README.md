> **Native Linux build:** A native port of the Windows tool. It behaves like upstream — writes go straight to the game with no extra gates or prompts. Physical tuning remains unverified after the earlier incident; test one section at a time.

# Neptune on Linux / CachyOS

Native Python/PySide6 UI; a statically linked C++ helper runs inside FH6's Proton prefix. No .NET, WebView, or Windows UI. Current upstream feature modules are shared; Linux code lives in `neptune_linux/`.

## Run

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r linux/requirements.lock
python3 linux/build_helper.py
./linux/run
```

Build requires `mingw-w64-gcc`; run requires Steam, FH6 and `protontricks`. Run as your normal desktop user. Default app ID is 2483190; override with `NEPTUNE_STEAM_APPID`. The launcher starts disconnected; click the plug/attach control after FH6 is running. Settings live under `$XDG_DATA_HOME/neptune-native` (normally `~/.local/share/neptune-native`). Helper logs live under `$XDG_STATE_HOME/neptune-native`.

## Update upstream without recreating the port

`origin` remains DVS-code/Neptune. `linux/upstream.json` records the integration baseline. The feature implementations and vehicle offsets are not duplicated. Small platform import switches select the adapters, and screenshot styling is isolated in `neptune_linux/shell.py`.

1. Save local work in your port branch before merging. Keep screenshots as user references.
2. Run `.venv/bin/python linux/check_upstream.py --fetch`. It reports all upstream changes and highlights platform-sensitive files; it never merges or overwrites work.
3. Review the incoming diff, especially offsets, the Process API, input bindings, runtime ownership, and new feature imports. Merge the chosen upstream revision into the port branch and resolve the small platform switches.
4. Rebuild the helper if changed. Update dependency locks deliberately. Run `.venv/bin/python -m unittest discover -s linux/tests` and `QT_QPA_PLATFORM=xcb .venv/bin/python linux/smoke_ui.py` and `QT_QPA_PLATFORM=xcb .venv/bin/python linux/test_overlay.py` from the desktop session.
5. Inspect all captures and run `.venv/bin/python linux/validate_live.py` with FH6 running. This diagnostic does not write game memory. Test restoration and car switching interactively before release.
6. Advance the revision in `linux/upstream.json` only after integration validation. Keep failures documented rather than marking an untested revision compatible.

The Windows executable updater is not a Linux-port update mechanism. Use the source integration workflow; do not replace this port with an upstream EXE.

## Current verification and limitations

- Native imports, typed memory adapter unit tests, C++ compilation, and main-page desktop renders pass.
- Controller buttons/triggers and keyboard bindings use the helper. Bind while attached; unattached input returns released.
- Live validation could not find FH6 in the selected prefix during this session. Engine writes, turbo, suspension, restoration, and car switching remain unverified on Linux.
- Racing-wheel buttons and hats use readable `/dev/input/js*` devices, matched by vendor/product. Physical wheel testing is pending; no broad device permission changes are made.
- Boost/Dragy overlays use X11 window tracking and X Shape click-through. The launcher selects Qt xcb when DISPLAY is available, including KDE Wayland via XWayland. Geometry and click-through passed disposable-window tests; stacking over the actual fullscreen game remains unverified. Native Wayland-only window tracking is not supported.
- Protected writes and thread suspension explicitly fail; ordinary engine/curve data access does not use these APIs in the current upstream revision.
- Car image extraction may need `NEPTUNE_GAME_EXE` set to the actual Linux path of the game executable.
- Upstream now differs from the six supplied screenshots (notably navigation and absence of World). The Linux style retains their compact purple sidebar treatment while sharing current upstream pages and controls.
- Engine torque and turbo multipliers are kept across a car change: the port re-applies the relative multiplier to the new car's own stock curve instead of resetting it (upstream resets).

## Licensing

Neptune remains GPL-3.0 under the root LICENSE. The helper/transport originate from the MIT-licensed Luna native work; its license is retained in `neptune_linux/bridge/LICENSE-Luna`. Distribute sources and license notices with releases.

## Manual changes and display performance

Neutral values such as torque 1.00 and ride-height offset 0 represent the baseline, not a command to force those values. A car change resets the tune to the new car's own stock values.

Writes go straight to the game through the helper, exactly like the Windows build. `Restore everything` and disconnect dispatch the upstream `restore` lifecycle, which writes each module's captured stock values back.

Display reads are cached off the GUI thread, grouped by memory page, and requested only while visible. Feature runtime reads stay live. The UI no longer waits on IPC for every telemetry label.
