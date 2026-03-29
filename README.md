# Voicemeeter Potato Remote

Small local-only Flask control panel for Voicemeeter Potato on Windows. It serves a single page with large phone-friendly preset buttons and applies named presets through the Voicemeeter Remote API DLL.

This is a LAN-only utility app.
Do not expose it to the public internet.

## What V1 Includes

- Flask server on `0.0.0.0:8787`
- Single dark mobile-friendly page
- Large touch-friendly preset buttons
- JSON API endpoints
- `ctypes` wrapper around the Voicemeeter Remote API DLL
- Declarative presets in `presets.json`
- Configurable device names and parameter targets in `config.json`

## Project Layout

```text
voicemeeter-remote/
  app.py
  vmr.py
  config.json
  presets.json
  .gitignore
  requirements.txt
  README.md
  scripts/
    start_voicemeeter_remote.ps1
    install_startup_task.ps1
    remove_startup_task.ps1
  preset_scripts/
    Scene_Potato/
      *.xml
  static/
    index.html
    app.js
    style.css
```

## 1. Prerequisites

- Windows 11
- Python 3.11 or newer, preferably 64-bit
- Voicemeeter Potato already installed and working locally
- Phone and PC on the same private Wi-Fi / LAN

If `python` opens the Microsoft Store alias or `pip` is missing, install Python first and make sure the installer enables:

- `Add python.exe to PATH`
- `Install launcher for all users`
- `pip`

## 2. Where To Create The Project Folder

Example location:

```powershell
mkdir C:\dev\voicemeeter-remote
cd C:\dev\voicemeeter-remote
```

If you already have this folder, just `cd` into it.

## 3. Create A Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\activate
```

If PowerShell blocks activation in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## 4. Install Requirements

```powershell
python -m pip install -r requirements.txt
```

## 5. Configure `config.json`

Edit [config.json](C:/dev/voicemeeter-remote/config.json) before first real use.

Current config fields:

- `host`: leave `0.0.0.0` so devices on your LAN can connect
- `port`: default `8787`
- `dll_path`: leave blank to auto-detect, or set the full DLL path manually
- `app_title`: title used by the web UI
- `log_level`: console log level, default `INFO`
- `expected_voicemeeter_type`: use `3` for Potato
- `preset_library_dir`: optional folder whose preset files should be shown directly as buttons
- `preset_file_extensions`: file extensions loaded from that folder, default `.xml`
- `a1_device_parameter`: output device parameter for A1
- `a2_device_parameter`: output device parameter for A2
- `a1_device_name`: optional A1 device name
- `a2_device_name`: optional A2 device name
- `main_route_strip_index`: strip index the output-routing presets should control
- `eq_bus_index`: bus index used by the EQ presets
- `movie_mode_bus_gain_db`: gain applied by `movie_mode`
- `night_mode_bus_gain_db`: gain applied by `night_mode`

Starter assumptions in the shipped defaults:

- `main_route_strip_index = 5`
- `a1_device_parameter = Bus[0].device.wdm`
- `a2_device_parameter = Bus[1].device.wdm`
- `eq_bus_index = 0`

Those are only example defaults. They may not match your own Potato layout.

If `a1_device_name` or `a2_device_name` is blank, that optional device-binding action is skipped and the preset only changes routing / EQ state.

Example:

```json
{
  "host": "0.0.0.0",
  "port": 8787,
  "dll_path": "",
  "app_title": "Voicemeeter Potato Remote",
  "log_level": "INFO",
  "expected_voicemeeter_type": 3,
  "a1_device_parameter": "Bus[0].device.wdm",
  "a2_device_parameter": "Bus[1].device.wdm",
  "a1_device_name": "",
  "a2_device_name": "",
  "main_route_strip_index": 5,
  "eq_bus_index": 0,
  "movie_mode_bus_gain_db": 0.0,
  "night_mode_bus_gain_db": -6.0
}
```

If auto-detection does not find the DLL, set `dll_path` explicitly. Common examples are:

```text
C:\Program Files (x86)\VB\Voicemeeter\VoicemeeterRemote64.dll
C:\Program Files\VB\Voicemeeter\VoicemeeterRemote64.dll
```

## 6. Use Your Own Preset Files

If `preset_library_dir` is set in [config.json](C:/dev/voicemeeter-remote/config.json), the app will first list the files from that folder as buttons.

Current starter setting:

```json
"preset_library_dir": "preset_scripts/Scene_Potato",
"preset_file_extensions": [".xml"]
```

That is useful when you already have Voicemeeter scene files and just want them on the phone page.

The XML files are loaded through `Command.Load` with their full path.

New XML presets are detected automatically.
If you copy a new matching file into `preset_library_dir`, it will appear after:

- tapping `Refresh` in the web UI, or
- reloading the page

If there is no matching entry yet in [presets.json](C:/dev/voicemeeter-remote/presets.json), the app falls back to:

- the file stem as the button label
- automatic ordering
- a default accent color
- normal tile size

Add an entry in [presets.json](C:/dev/voicemeeter-remote/presets.json) only if you want custom label, color, order, description, or tile size.

## 7. Edit `presets.json`

[presets.json](C:/dev/voicemeeter-remote/presets.json) is declarative. Each preset contains:

- `label`
- `description`
- `color`
- `order`
- `size`
- either `script_file` or `actions`

When you use the web page's unlock/edit mode, the app writes the current button order, label, color, size, and the global grid mode back into `presets.json`.
The shared layout setting is stored under `_ui.layout_mode`.

The simplest workflow now is `script_file`.

Example:

```json
{
  "gaming": {
    "label": "Gaming",
    "script_file": "preset_scripts/gaming.txt"
  },
  "movie": {
    "label": "Movie",
    "script_file": "preset_scripts/movie.txt"
  }
}
```

Then create the referenced files in [preset_scripts/README.txt](C:/dev/voicemeeter-remote/preset_scripts/README.txt)'s folder, for example:

```text
Strip[{{main_route_strip_index}}].A1=1
Strip[{{main_route_strip_index}}].A2=0
Bus[{{eq_bus_index}}].EQ.on=1
```

The script files support placeholders using `{{name}}` syntax.

Examples:

- `{{main_route_strip_index}}`
- `{{eq_bus_index}}`
- `{{movie_mode_bus_gain_db}}`

Empty lines and comment lines starting with `#`, `//`, or `;` are ignored.

The older action-based format is still supported if you want it later.

If you are using `preset_library_dir` with XML scene files, `presets.json` acts as the visual metadata layer for those files:

- short button names
- accent colors
- display order
- wide vs normal tiles

Supported action types:

- `set_float_parameter`
- `set_string_parameter`

Example action:

```json
{
  "type": "set_float_parameter",
  "name": "Strip[{{main_route_strip_index}}].A1",
  "value": 1.0
}
```

Shipped example presets:

- `headphones_only`
- `tv_only`
- `both_outputs`
- `movie_mode`
- `night_mode`
- `reset`

These now load local files from the [preset_scripts](C:/dev/voicemeeter-remote/preset_scripts) folder.

## 8. Run The App

Start Voicemeeter Potato first, then run:

```powershell
python app.py
```

Open this on the Windows PC first:

```text
http://127.0.0.1:8787
```

The health panel should tell you:

- whether the web server is up
- whether the Voicemeeter DLL was found
- whether login succeeded
- whether Voicemeeter Potato is reachable

Optional helper script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_voicemeeter_remote.ps1 -Foreground
```

That launches the same app through the project's `.venv`.

## 9. Start Automatically With Windows

Best practical option for this project: use a current-user startup entry in the Windows `Run` registry key.
That does not need admin rights on most systems and is simpler than Task Scheduler for this local-only tool.

Install the startup entry:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_startup_task.ps1
```

What it does:

- creates or updates `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\VoicemeeterPotatoRemote`
- waits about 20 seconds after logon
- starts [scripts/start_voicemeeter_remote.ps1](C:/dev/voicemeeter-remote/scripts/start_voicemeeter_remote.ps1)
- uses your project's `.venv\Scripts\python.exe`
- writes logs into the local `logs` folder

Remove the startup entry later:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\remove_startup_task.ps1
```

Notes:

- this starts when you log into Windows, not before user logon
- if the app is already listening on the configured port, the startup script exits without starting a second copy
- if you change the app port in [config.json](C:/dev/voicemeeter-remote/config.json), the startup script follows that automatically
- the same install command can be run again safely to update the startup entry
- the web UI shows a small `Autostart On/Off` indicator in the top status area

## 10. Find The PC's Local IP

Run:

```powershell
ipconfig
```

Look for the IPv4 address of your active Wi-Fi or Ethernet adapter.

PowerShell alternative:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.254*' -and $_.IPAddress -ne '127.0.0.1'}
```

## 11. Open The UI From Your Phone

Make sure the phone is on the same home Wi-Fi, then open:

```text
http://YOUR_PC_IP:8787
```

Example:

```text
http://192.168.1.42:8787
```

By default the page is locked for safe preset launching.
Use the bottom `Unlock edit` button if you want to rename buttons, change colors, switch the grid, or reorder tiles directly from the browser.

## 12. Windows Firewall Notes

Allow TCP port `8787` only on private networks.

PowerShell example:

```powershell
New-NetFirewallRule -DisplayName "Voicemeeter Remote 8787" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -Profile Private
```

To remove the rule later:

```powershell
Remove-NetFirewallRule -DisplayName "Voicemeeter Remote 8787"
```

Do not expose this app to the public internet.

- Do not port-forward it
- Do not put it behind a public reverse proxy
- Do not allow it on public network profiles

## 13. GitHub Upload Notes

This project is now set up to upload cleanly to GitHub.

- [`.gitignore`](C:/dev/voicemeeter-remote/.gitignore) excludes `.venv`, `__pycache__`, and common editor folders
- the app is intentionally local-only and should stay documented that way
- before a public push, review [config.json](C:/dev/voicemeeter-remote/config.json) and [presets.json](C:/dev/voicemeeter-remote/presets.json) for any personal device names, folder names, or scene labels you do not want to publish
- if you want a more reusable public repo, keep generic placeholders in `config.json` and store your personal live values locally

## API Endpoints

- `GET /api/health`
- `GET /api/autostart`
- `GET /api/config`
- `GET /api/presets`
- `POST /api/preset/<preset_name>`

Examples:

```powershell
Invoke-RestMethod -Method Get http://127.0.0.1:8787/api/health
Invoke-RestMethod -Method Post http://127.0.0.1:8787/api/preset/headphones_only
```

## Troubleshooting

- DLL missing:
  Set `dll_path` in [config.json](C:/dev/voicemeeter-remote/config.json) to the full path of `VoicemeeterRemote64.dll`.

- Voicemeeter not running:
  Start Voicemeeter Potato first, then refresh the page and retry the preset.

- Wrong Voicemeeter edition:
  This project expects Potato by default. If another edition is running, `/api/health` will show the mismatch.

- Preset touches the wrong strip or bus:
  Check `main_route_strip_index`, `eq_bus_index`, and the parameter names in [config.json](C:/dev/voicemeeter-remote/config.json).

- Device binding fails:
  Confirm the device name and the driver type are correct.
  Example: `Bus[0].device.wdm` vs `Bus[0].device.ks` vs `Bus[0].device.asio`.

- Phone cannot connect:
  Confirm the PC and phone are on the same LAN, the app is running, and Windows Firewall allows private inbound TCP 8787.

- `python` command is not found:
  Install Python from python.org and enable PATH, or use the `py` launcher if it is available on your machine.

- `pip` command is not found:
  Use `python -m pip ...` instead of bare `pip ...`, and verify Python was installed with `pip` included.

- A preset fails halfway through:
  Earlier actions may already have been applied.
  Fix the bad parameter, device name, or script line and run the preset again or use `reset`.

## Notes

- This is intentionally a small V1, not a full mixer clone
- No auth is included in V1, so keep it on a trusted private network only
- Live faders, realtime meters, and drag controls are intentionally out of scope
#   v o i c e m e e t e r - p o t a t o - r e m o t e  
 