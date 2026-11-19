# Getting started

Run every program in this repo on your own laptop against **dmnax-server**, a demo DM-NAX that
needs no hardware. Follow the steps in order. Each command has a **Windows** (PowerShell) version
and a **macOS / Linux** version: use the one for your computer.

Every command is **one line**: copy it, paste it into your terminal, press Enter.

## Open a terminal in the class folder

Run every command from the `Crestron-Master-Class` folder (the one with `requirements.txt`). Keep
it on a short path (not deep inside OneDrive or Desktop).

| OS | How |
| --- | --- |
| Windows | Open the folder in File Explorer, type `powershell` in the address bar, press Enter. |
| macOS | In Finder, right-click the folder and choose **New Terminal at Folder**. |
| Linux | In the file manager, right-click the folder and choose **Open in Terminal**. |
| Any | Open a terminal and `cd` to the folder. |

You use up to three terminals; open each one in the class folder.

| Terminal | Runs | Used in |
| --- | --- | --- |
| 1 | dmnax-server | steps 2-7 |
| 2 | the HTTP MCP server | step 6 |
| 3 | the clients | steps 3, 5, 6, 7 |

To see how the pieces work, open [how-it-works.html](how-it-works.html) in a browser.

## 1. Install

**Need Python 3.10?** Skip this if you already have it (Windows: `py -0` lists `-V:3.10`;
macOS / Linux: `python3.10 --version` prints `Python 3.10.x`).

Windows:

```powershell
winget install --id Python.Python.3.10 --scope user
```

macOS ([Homebrew](https://brew.sh)):

```bash
brew install python@3.10
```

Linux (Debian / Ubuntu; on other distros use your package manager or pyenv):

```bash
sudo apt install python3.10 python3.10-venv
```

**Install the class libraries (once):**

Windows:

```powershell
py -3.10 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt
```

macOS / Linux:

```bash
python3.10 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
```

**Check it:**

Windows:

```powershell
.venv\Scripts\python.exe -c "import sys, aiohttp, websockets, cryptography, mcp; print('Python', sys.version.split()[0], '- all libraries OK')"
```

macOS / Linux:

```bash
.venv/bin/python -c "import sys, aiohttp, websockets, cryptography, mcp; print('Python', sys.version.split()[0], '- all libraries OK')"
```

Expect `Python 3.10.x - all libraries OK`.

| If you see | Fix |
| --- | --- |
| `No suitable Python runtime found` (Windows) | Install Python 3.10 (the `winget` line above), then run the install line again. |
| `python3.10: command not found` (macOS / Linux) | Install Python 3.10 (the `brew` or `apt` line above), then run the install line again. |
| `No such file or directory` or a Long Path hint during `pip install` | Move the folder to a short path, delete `.venv`, install again. |

## 2. Start the server

**Terminal 1:**

Windows:

```powershell
.venv\Scripts\python.exe dmnax-server\server.py
```

macOS / Linux:

```bash
.venv/bin/python dmnax-server/server.py
```

**Windows only: or start it in its own window** (your terminal stays free; close that window to
stop it):

```powershell
Start-Process "$PWD\.venv\Scripts\python.exe" -ArgumentList 'dmnax-server\server.py' -WorkingDirectory $PWD
```

**Output, not a command:** don't paste the next block. The server prints it in terminal 1, or in the
new window if you used `Start-Process` (macOS / Linux show `/` instead of `\`):

```text
dmnax-server: DM-NAX-4ZSA demo, 5 players, 5 zones
  status page   https://127.0.0.1:8443/   (self-signed certificate)
  client config dmnax-server\client-config.json
```

Leave it running. Every client below reads `dmnax-server/client-config.json` with `--config`, so
there is nothing to fill in.

**Check it:** open <https://127.0.0.1:8443/> and accept the certificate warning. Keep this
**status page** open for all steps: it shows Player01-Player05, the five zones (all at 25%), the
fault switches and the request log.

To start over, stop the server and start it again: that resets all players, zones and faults.

## 3. Direct demo (demo_python)

A fixed script on Player01 and its zone, Kitchen. **Terminal 3:**

Windows:

```powershell
.venv\Scripts\python.exe demo_python\main.py --config dmnax-server\client-config.json --check
```

```powershell
.venv\Scripts\python.exe demo_python\main.py --config dmnax-server\client-config.json --execute
```

macOS / Linux:

```bash
.venv/bin/python demo_python/main.py --config dmnax-server/client-config.json --check
```

```bash
.venv/bin/python demo_python/main.py --config dmnax-server/client-config.json --execute
```

| Option | What it does | Last lines |
| --- | --- | --- |
| `--check` | Reads only and prints the plan | `Read-only check complete; playback and volume were unchanged.` |
| `--execute` | Play 5 s, pause, Kitchen to 10%, play 3 s, pause | `Finished: player paused, zone volume 10%`, `Connections closed` |

Status page after `--execute`: Player01 `paused` on Harbor FM, Kitchen at 10%.

## 4. MCP: what each folder does

MCP (Model Context Protocol) lets a program or an AI assistant call **tools**. All three folders
offer the same 15 tools with the same rules; only the wiring differs.

| Folder | What it is | You run |
| --- | --- | --- |
| `demo_mcp/` | MCP server written by hand | `client.py` (it starts the server) |
| `demo_mcp_sdk/` | The same server built on the official MCP Python SDK; the one to give an AI host such as Claude Code | `client.py` (it starts the server) |
| `demo_mcp_http/` | The same tools over HTTP; several clients can share one server | `server.py`, then `client.py` |

## 5. MCP over stdio (demo_mcp, demo_mcp_sdk)

You need terminal 1 (dmnax-server) and terminal 3. Do the run below with the hand-written menu,
then repeat it with the SDK menu: same keys, same results.

**Hand-written menu** (terminal 3):

Windows:

```powershell
.venv\Scripts\python.exe demo_mcp\client.py --config dmnax-server\client-config.json
```

macOS / Linux:

```bash
.venv/bin/python demo_mcp/client.py --config dmnax-server/client-config.json
```

**SDK menu** (terminal 3):

Windows:

```powershell
.venv\Scripts\python.exe demo_mcp_sdk\client.py --config dmnax-server\client-config.json
```

macOS / Linux:

```bash
.venv/bin/python demo_mcp_sdk/client.py --config dmnax-server/client-config.json
```

### What to try

Everything uses **Player01**, which plays in the **Kitchen**. Type the keys shown, pressing Enter
after each one. Keep the status page (<https://127.0.0.1:8443/>) open next to the menu: every
change shows up there too.

**1. Play a song**

| Type | You see |
| --- | --- |
| `1` | Main House |
| `2` | DemoStream |
| `1` | Playlists |
| `4` | Big Mix (20 songs) |
| `1` | Silver Harbor |
| `1` | Player01. The menu shows `Preview: play 'Silver Harbor' on Player01` and asks `Do it? [y/N]:` |
| `y` | `Done and verified by the device.` Player01 is playing. |

**2. Control the player**

| Type | What it does | You see |
| --- | --- | --- |
| `1` | Status | `Player01 playing: Silver Harbor` |
| `4`, `1`, `y` | Next song | `Done and verified by the device.` |
| `2`, `1` | Pause (no question asked) | `Verified: Player01 paused` |
| `3`, `1`, `y` | Play again | `Done and verified by the device.` |

**3. Control the Kitchen**

| Type | What it does | You see |
| --- | --- | --- |
| `v`, `1`, `30`, `y` | Kitchen volume to 30% | `Preview: Kitchen: volume …% -> 30%`, then `Done` |
| `m`, `1`, `y` | Mute the Kitchen | `Kitchen: unmuted -> muted` |
| `m`, `1`, `y` | Unmute it | `Kitchen: muted -> unmuted` |

**4. Play a radio station**

| Type | What it does | You see |
| --- | --- | --- |
| `b`, `f` | Open Favorites | Harbor FM, Smoky Room Jazz, … |
| `1`, `1`, `y` | Play Harbor FM on Player01 | `Done and verified by the device.` |

**5. See the safety checks**

| Type | What it does | You see |
| --- | --- | --- |
| `v`, `1`, `50`, `n` | Say no to a change | `Cancelled; nothing changed.` |
| `4`, `1` | Next on live radio | Refused: `next is not available now; the player offers: Pause, Stop.` |

**6. Quit:** type `q`. You see `Cleanup: Player01 paused` and `Connections closed`.

**What to point out:** nothing changes until you type `y`. The menu always shows a `Preview` first,
and after each change it checks the device and says `verified`.

**Bonus: the SDK server in GitHub Copilot or Claude Code.** For Copilot, open the repository root
(the folder containing `Crestron-Master-Class`) in VS Code. The workspace MCP entry is in
`.vscode/mcp.json`; start the demo device from step 2 first so
`Crestron-Master-Class/dmnax-server/client-config.json` exists, then use **Start** for
`crestron-demo` in the MCP configuration or reload VS Code. Its tools will be available to Copilot
agents.

For Claude Code, register it once from the class folder (the command fills in the full paths for
you):

Windows:

```powershell
claude mcp add crestron-demo -- "$PWD\.venv\Scripts\python.exe" "$PWD\demo_mcp_sdk\server.py" --config "$PWD\dmnax-server\client-config.json"
```

macOS / Linux:

```bash
claude mcp add crestron-demo -- "$(pwd)/.venv/bin/python" "$(pwd)/demo_mcp_sdk/server.py" --config "$(pwd)/dmnax-server/client-config.json"
```

Then ask Claude, for example, "Play Harbor FM on Player01". Claude shows the preview and asks
before every change; the status page shows the change.

## 6. MCP over HTTP (demo_mcp_http)

Same menu and same keys as step 5; the only difference is that you start the server yourself.

**Terminal 2** (start the server first; leave it running):

Windows:

```powershell
.venv\Scripts\python.exe demo_mcp_http\server.py --config dmnax-server\client-config.json
```

macOS / Linux:

```bash
.venv/bin/python demo_mcp_http/server.py --config dmnax-server/client-config.json
```

You see `Running on http://127.0.0.1:8000`.

**Terminal 3:**

Windows:

```powershell
.venv\Scripts\python.exe demo_mcp_http\client.py
```

macOS / Linux:

```bash
.venv/bin/python demo_mcp_http/client.py
```

Now follow the same steps as [What to try](#what-to-try) in step 5.

## 7. Error simulation

Switch a fault on in the status page under **Fault injection**, run a client, and read its
message. Untick it (or restart dmnax-server) to switch it off.

| Fault on the status page | Try | Client shows |
| --- | --- | --- |
| **refuse LoadSource** | `--execute`, or play a song in the menu | `Player refused the command: Set Station Failed: This track is not currently available.` |
| **silent player** | `--execute`, or play a song in the menu | `Player did not verify 'playing' after the command; it may or may not have applied.` (after about 15 s) |
| **reply delay** `15` | `--check` | `MP2 timed out waiting for RegisterClient. Check device mode and subscriptions.` |
| **reject MP2 login** | `--check` | `MP2 login/handshake refused: check client_id, client_secret, and MP2 mode.` |
| **reject REST login** | `--check` | `REST login refused: check admin_user and admin_password.` |

**Errors without a fault switch:**

| Do | Client shows |
| --- | --- |
| Stop dmnax-server, run `--check` | `MP2 device unreachable: check the address, network, and MP2 mode.` (after about 15 s) |
| Mute Kitchen in the menu (`m`), then run `--check` | `Zone is muted; this demo will not unmute it implicitly.` |
| Menu: `v`, `1`, `150` | `percent must be a whole number from 0 to 100.` |

## Next: a real DM-NAX

Windows:

```powershell
Copy-Item config\config.example.json config\config.json
```

macOS / Linux:

```bash
cp config/config.example.json config/config.json
```

Fill in your device's address and logins ([settings](../config/README.md)), then leave out
`--config`: every program reads `config/config.json` by default. The device must be in Media
Player 2.0 mode. On a real device `--execute` plays audio in a real room: check the zone first.
