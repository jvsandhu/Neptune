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
bundled, so those have to be present already. Settings live in `~/.local/share/neptune-native`,
and the helper log is at `~/.local/state/neptune-native` if attach has trouble.

To update, download the new AppImage. It does not self-update.

## Changes

### 1.0.1

- **Rev limit works now.** The slider only wrote `MAX_CLAMP`, which is the upper bound the torque
  curve gets sampled to, so the engine kept cutting at its stock rpm wherever you put it. It now
  writes `THRESH` and `NEG_CLAMP` as well, which are where the engine actually limits. On the
  test car, raising all three to 12000 with the curve extended reached 12083 rpm.

  Worth knowing: this raises *where the engine cuts*, it does not add power. In neutral the
  engine will reach the new limit because there is no load; in gear it still has to pull there,
  and past the stock curve the extension declines on purpose. If you want it to pull to the new
  limit, raise the Torque multiplier or shape the torque graph by hand.

- **Releases are built in a pinned container** (Debian 12, glibc 2.36) instead of on whatever
  machine happened to build them. The artifact runs on Debian 12, Ubuntu 23.04/24.04 and newer.
  Ubuntu 22.04 and RHEL 9 are older than that and will refuse to start it.

### 1.0.0

First Linux build.

- Neptune runs natively on Linux. Same UI, features and offsets as the Windows build; a small
  helper runs inside the game's Proton prefix and does the Windows-only work. No Wine, no .NET,
  no WebView.
- Engine, Turbo, Transmission, Suspension, Car, Dyno and Logs pages, with the section toggles
  upstream added in 1.1.5.
- Grip controls on the Suspension page: Cornering, Straight-line and Both sliders from 1.00x to
  3.00x, plus a reset, and a live per-wheel friction readout.
- The loaded car's name above the status line.
- Engine and Turbo multipliers survive a car change instead of resetting.

## Requirements

- 64-bit Linux, X11 or Wayland **with XWayland**
- Steam with Forza Horizon 6 installed and running through Proton
- `protontricks`

Not supported: native Wayland without XWayland, and protected writes or thread suspension (no
current feature needs those).

## Licence

GPL-3.0, same as upstream. The helper and transport come from MIT-licensed work; that notice is
kept in `neptune_linux/bridge/LICENSE-Luna`.
