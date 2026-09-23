# Web Input UI Plan

## Goal

Build a simple local web page so users do not need to remember CLI arguments. The UI collects launch parameters, updates `config.json` for request defaults/env overrides when needed, then runs the existing `src/game_launch_loop.py` flow and opens the generated Markdown report.

## Main User Flow

1. User opens local web page.
2. Page loads current `config.json`.
3. Form pre-fills stable values:
   - `username`
   - `language`
   - `platform`
   - `lobbyUrl`
   - `ipAddress`
4. User selects:
   - env mode: `qa`, `stg`, or `qa,stg`
   - currency per selected env
   - agent_id per selected env
5. User enters gameCode input:
   - single gameCode
   - comma-separated non-contiguous gameCodes
   - range such as `GALA_8000-GALA_8100`
6. Backend validates the input.
7. Backend updates `config.json` request/env values.
8. Backend runs `src/game_launch_loop.py`.
9. If Cloudflare blocks a launch request, the runner immediately stops sending requests and records all remaining game codes, vendor items, and environments as `SKIPPED`.
10. UI shows run status and links to the generated Markdown report.

## Form Fields

### Text Inputs

- `username`
  - Default from `config.request.username`.
  - Example: `gro260629`.
- `gameCode`
  - Accepts:
    - `PPGROOVE2_247000057`
    - `PPGROOVE2_247000057, PPGROOVE2_247000159`
    - `GALA_8000-GALA_8100`
- `language`
  - Default from `config.request.language`.
  - Usually `en`.
- `platform`
  - Default from `config.request.platform`.
  - Usually `WEB`.
- `lobbyUrl`
  - Default from `config.request.lobbyUrl`.
- `ipAddress`
  - Default from `config.request.ipAddress`.

### Select Controls

- `env mode`
  - `QA only`
  - `STG only`
  - `QA + STG`
- `currency`
  - Per selected env.
  - Defaults from `config.environments.<env>.currency`.
  - if select one env, display one currency input field.
  - if select `QA + STG` env, appear QA and STG currency input fields seperately.
- `agent_id`
  - Per selected env.
  - Options from `config.environments.<env>.agents[*].agent_id`.
  - if select `QA`, default value is `1087`
  - if select `STG`, default value is `12`

## Config Strategy

Keep the optimized config shape:

```json
{
  "environments": {
    "qa": {
      "ga_vendor_api": "https://qa.example.com",
      "currency": "BRL",
      "agents": [
        {
          "agent_id": 1087,
          "x_api_key": "QA_API_KEY",
          "x_api_secret": "QA_API_SECRET"
        }
      ]
    },
    "stg": {
      "ga_vendor_api": "https://stg.example.com",
      "currency": "EUR",
      "agents": [
        {
          "agent_id": 12,
          "x_api_key": "STG_API_KEY",
          "x_api_secret": "STG_API_SECRET"
        }
      ]
    }
  },
  "request": {
    "username": "gro260629",
    "language": "en",
    "platform": "WEB",
    "lobbyUrl": "https://www.google.com/",
    "ipAddress": "192.228.180.86"
  },
  "timeout_seconds": 30,
  "delay_ms": 5000,
  "insecure_skip_tls_verify": true
}
```

Backend update rules:

- Update `config.request.username`.
- Update `config.request.language`.
- Update `config.request.platform`.
- Update `config.request.lobbyUrl`.
- Update `config.request.ipAddress`.
- Update `config.environments.qa.currency` only when QA is selected.
- Update `config.environments.stg.currency` only when STG is selected.
- Keep `delay_ms` as the single shared launch interval in `config.json`; the web form does not maintain separate delay values.
- Do not modify `ga_vendor_api`, `x_api_key`, or `x_api_secret` from the basic form.
- Do not store gameCode in `config.json`; gameCode is a run-time input.

`src/game_launch_loop.py` should read `delay_ms` through one helper and reuse that same value for normal game-code loops, JSON vendor-item loops, and waits between multiple selected environments.

## Backend Command Mapping

### QA Only

```bash
python3 src/game_launch_loop.py \
  --env qa \
  --agent-id qa=1087 \
  --game-code PPGROOVE2_247000057, PPGROOVE2_247000159
```

### STG Only

```bash
python3 src/game_launch_loop.py \
  --env stg \
  --agent-id stg=12 \
  --game-code PPGROOVE2_247000057, PPGROOVE2_247000159
```

### QA + STG

```bash
python3 src/game_launch_loop.py \
  --env qa,stg \
  --agent-id qa=1087 \
  --agent-id stg=12 \
  --game-code PPGROOVE2_247000057, PPGROOVE2_247000159
```

### Range Input

If the gameCode field matches range format, use `--range` instead of `--game-code`:

```bash
python3 src/game_launch_loop.py \
  --env stg \
  --agent-id stg=12 \
  --range GALA_8000-GALA_8100
```

## Suggested Implementation

Use Python standard library only:

- `http.server` for local web server.
- `json` for config read/write.
- `subprocess` to run `src/game_launch_loop.py`.
- No extra dependencies.

### Start Command

Use this as the Python launcher:

```bash
python3 src/web_input_server.py
```

Expected behavior:

- Start a local HTTP server on `127.0.0.1:20731`.
- Automatically open `http://127.0.0.1:20731` in Google Chrome.
- Serve the web UI from `web/index.html`.
- Expose `GET /api/config` for form defaults/options.
- Expose `POST /api/run` to update `config.json` and run `src/game_launch_loop.py`.
- Print the local URL and basic server status in the terminal.

### Auto Start/Stop

Goal:

- Start the web UI every day at `09:00`.
- Stop the web UI every day at `18:00`.
- Avoid leaving the local server running overnight.

Recommended macOS approach:

- Use `launchd` to start the server at 09:00.
- Add a small stop script that kills only this project's `web_input_server.py`.
- Use a second `launchd` job to run the stop script at 18:00.

Add a no-browser mode to the server:

```bash
python3 src/web_input_server.py --no-browser
```

Reason:

- Manual start should open Chrome.
- Scheduled start should not unexpectedly steal focus every morning unless we decide that is desired.

Suggested files:

```text
scripts/start_web_input.sh
scripts/stop_web_input.sh
launchd/com.game-launch-loop.web.start.plist
launchd/com.game-launch-loop.web.stop.plist
```

`scripts/start_web_input.sh`:

```bash
#!/usr/bin/env bash
cd /Users/stephenhuang/game-launch-loop
python3 src/web_input_server.py --no-browser
```

`scripts/stop_web_input.sh`:

```bash
#!/usr/bin/env bash
pkill -f "/Users/stephenhuang/game-launch-loop/src/web_input_server.py"
```

Start plist idea:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.game-launch-loop.web.start</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/stephenhuang/game-launch-loop/scripts/start_web_input.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>9</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/stephenhuang/game-launch-loop/logs/web_input_start.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/stephenhuang/game-launch-loop/logs/web_input_start.err</string>
</dict>
</plist>
```

Stop plist idea:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.game-launch-loop.web.stop</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/stephenhuang/game-launch-loop/scripts/stop_web_input.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>18</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/stephenhuang/game-launch-loop/logs/web_input_stop.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/stephenhuang/game-launch-loop/logs/web_input_stop.err</string>
</dict>
</plist>
```

Install commands:

```bash
mkdir -p logs
chmod +x scripts/start_web_input.sh scripts/stop_web_input.sh
cp launchd/com.game-launch-loop.web.start.plist ~/Library/LaunchAgents/
cp launchd/com.game-launch-loop.web.stop.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.game-launch-loop.web.start.plist
launchctl load ~/Library/LaunchAgents/com.game-launch-loop.web.stop.plist
```

Uninstall commands:

```bash
launchctl unload ~/Library/LaunchAgents/com.game-launch-loop.web.start.plist
launchctl unload ~/Library/LaunchAgents/com.game-launch-loop.web.stop.plist
rm ~/Library/LaunchAgents/com.game-launch-loop.web.start.plist
rm ~/Library/LaunchAgents/com.game-launch-loop.web.stop.plist
```

Notes:

- `web_input_server.py` should handle "port already in use" gracefully.
- `stop_web_input.sh` should match the full project path so it does not kill unrelated Python servers.
- If we want Chrome to open at 09:00, remove `--no-browser` from `start_web_input.sh`.

Suggested files:

```text
src/web_input_server.py
web/index.html
web/app.js
web/styles.css
```

Routes:

- `GET /`
  - Serve UI.
- `GET /api/config`
  - Return safe config data:
    - env names
    - env currencies
    - agent_id options
    - request defaults
  - Do not return `x_api_key` or `x_api_secret`.
- `POST /api/run`
  - Validate payload.
  - Update `config.json`.
  - Run `src/game_launch_loop.py`.
  - Return:
    - command status
    - generated report path
    - report open URL/path
    - launch URL list grouped by env/gameCode

Example `POST /api/run` response shape:

```json
{
  "ok": true,
  "reportPath": "reports/game-launch-2026-06-30_10-30-00.md",
  "launchUrls": [
    {
      "env": "stg",
      "agentId": 12,
      "gameCode": "PPGROOVE2_247000057",
      "url": "https://routerstg.groovegaming.com/game/..."
    }
  ],
  "stdout": "...",
  "stderr": ""
}
```

## Launch URL Actions

After a run completes, the UI should show launch URL actions:

- A result table with one row per launched game.
- Each row has:
  - checkbox
  - env
  - agent_id
  - gameCode
  - status
  - `Open Game` button
- Top-level buttons:
  - `Open selected games`
  - `Open all games`

Button behavior:

- `Open Game` opens only that row's launch URL in a new tab.
- If there is only one launch URL, `Open selected games` or `Open all games` should directly open that one URL.
- If there are multiple launch URLs, `Open selected games` opens each checked launch URL in a new tab.
- If there are multiple launch URLs, `Open all games` opens every successful launch URL in a new tab.
- Disable open buttons when there is no launch URL.
- For failed launches, show the status/message and leave the checkbox disabled.

Frontend implementation note:

```js
function openLaunchUrls(urls) {
  const validUrls = urls.filter(Boolean);
  if (validUrls.length === 0) {
    return;
  }

  if (validUrls.length === 1) {
    window.open(validUrls[0], "_blank", "noopener,noreferrer");
    return;
  }

  const blockedUrls = [];
  for (const url of validUrls) {
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    if (!opened) {
      blockedUrls.push(url);
    }
  }

  if (blockedUrls.length > 0) {
    showPopupBlockedWarning(blockedUrls);
  }
}
```

Browser popup note:

- Browsers are more likely to allow multiple tabs when `window.open` is called directly from a user click.
- Do not open launch URLs automatically right after the API response.
- Always require a user click on `Open Game`, `Open selected games`, or `Open all games`.
- Single-link opens are unlikely to be blocked when triggered by a user click.
- Multi-link opens may be blocked by Chrome.
- If Chrome blocks multiple tabs, show a short warning and keep individual `Open Game` buttons available as the fallback.

## Validation Rules

- `username` required.
- `gameCode` or range required.
- `env mode` required.
- selected env must exist in `config.json`.
- selected `agent_id` must exist under that env.
- currency required for every selected env.
- language defaults to `en` if empty.
- platform defaults to `WEB` if empty.
- lobbyUrl defaults to `https://www.google.com/` if empty.
- ipAddress defaults to `192.228.180.86` if empty.


## UI Notes

- Keep the first screen as the tool itself, not a landing page.
- Use compact layout:
  - left: request inputs
  - right: environment selectors
  - bottom: run button and status
- Use select dropdowns for env/currency/agent_id.
- Use text fields for username/gameCode/language/platform/lobbyUrl/ipAddress.
- Show generated report link after run.
- Show launch URL rows with `Open Game`, `Open selected games`, and `Open all games` actions after run.
- Show command output in a small log panel.

## Future Enhancements

- Add CSV upload for DBeaver export.
- Add recent run history.
- Add a "do not update config.json, run once only" checkbox.
- Add per-run output filename prefix.
- Add cancellation support for long bulk runs.
- Stop bulk launch early after the first `/game/url` HTTP 502 error. Mark remaining games as `SKIPPED` in the Markdown report, so users can see which inputs were not executed and retry after the upstream error is resolved.
