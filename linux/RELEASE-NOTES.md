# Neptune on Linux 1.0.1

Based on upstream Neptune **v1.1.5**. The Linux build carries its own version so fixes can ship
without waiting for an upstream release.

## Install

1. Install `protontricks` (Arch/CachyOS: `sudo pacman -S protontricks`, Debian/Ubuntu:
   `sudo apt install protontricks`).
2. Download `Neptune-1.1.5-linux.1.0.1-x86_64.AppImage` from the release assets.
3. Make it executable. Right-click and choose "Allow executing file as program", or run
   `chmod +x` on it.
4. Start Forza Horizon 6 first, then double-click the AppImage.
5. Click the attach button in the top bar. The status line shows progress, then says the car is
   ready.

There is no Python, pip or compiler to install. Steam, the game and `protontricks` are not
bundled. Settings live in `~/.local/share/neptune-native`, and the helper log is at
`~/.local/state/neptune-native` if attach has trouble.

To update, download the new AppImage. It does not self-update.

## Changes

### 1.0.1

- Rev limit slider now works. It was only writing `MAX_CLAMP`; it also writes `THRESH` and
  `NEG_CLAMP`, which are where the engine limits.
- Releases are built in a pinned Debian 12 container (glibc 2.36), so the AppImage runs on
  Debian 12, Ubuntu 23.04/24.04 and newer. Not Ubuntu 22.04 or RHEL 9.

### 1.0.0

- First Linux build. Same features and offsets as upstream, with a small helper running inside
  the game's Proton prefix.
- Grip sliders on Suspension: Cornering, Straight-line and Both from 1.00x to 3.00x, plus a
  reset, and a live per-wheel friction readout.
- Loaded car's name above the status line.
- Engine and Turbo multipliers survive a car change.

## Requirements

- 64-bit Linux, X11 or Wayland **with XWayland**
- Steam with Forza Horizon 6 installed and running through Proton
- `protontricks`

Not supported: native Wayland without XWayland, and protected writes or thread suspension.

## Licence

GPL-3.0, same as upstream. The helper and transport come from MIT-licensed work; that notice is
kept in `neptune_linux/bridge/LICENSE-Luna`.
