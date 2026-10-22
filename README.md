# Game Launch Loop

Loop call GA vendor `/game/url` for many `gameCode` values, then export the launch results to Markdown.

## Requirements

- Python 3.9+
- No third-party packages required

## Setup

Copy the example config and fill in QA/STG endpoint plus credentials:

```bash
cp config.example.json config.json
```

`config.json`:

```json
{
  "environments": {
    "qa": {
      "ga_vendor_api": "https://qa.example.com",
      "currency": "BRL",
      "agents": [
        {
          "agent_id": 1087,
          "agent_name": "QA Agent",
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
          "agent_name": "STG Agent",
          "x_api_key": "STG_API_KEY",
          "x_api_secret": "STG_API_SECRET"
        }
      ]
    }
  },
  "request": {
    "username": "ga251110",
    "language": "en",
    "platform": "WEB",
    "lobbyUrl": "https://www.google.com/",
    "ipAddress": "191.168.1.1"
  },
  "timeout_seconds": 30,
  "delay_ms": 5000,
  "insecure_skip_tls_verify": true
}
```

`timeout_seconds` is the wait time for a failed/no-response request. `delay_ms` is the interval between every `/game/url` request; keep it at `5000` to avoid overwhelming the game server.

`insecure_skip_tls_verify` is set to `true`, so all requests skip TLS certificate verification for QA/STG test environments.

Put shared env settings such as `ga_vendor_api`, `currency`, `language`, `platform`, `lobbyUrl`, or `ipAddress` at the environment level. Put only per-agent credentials in `agents`. The legacy single-object/list formats still work, but this structure avoids repeating `ga_vendor_api` and env-specific request values for every `agent_id`.

## Usage

Start the local web input UI:

```bash
python3 src/web_input_server.py
```

It opens `http://127.0.0.1:20731` in Google Chrome. Use `--no-browser` if you only want to start the server:

```bash
python3 src/web_input_server.py --no-browser
```

### Web UI

The web UI is a local helper for building the same launch request without typing long CLI commands.

- Fill in request fields such as `username`, `language`, `platform`, `gameCode`, `lobbyUrl`, and `ipAddress`.
- Choose one env (`QA` or `STG`) or run both (`QA + STG`).
- Choose each env's `currency` and `agent_id`; agent names are shown when `agent_name` is configured.
- `Game Code / Range` is required. If it is empty, the browser shows a validation message and does not call the run API.
- `Launch Game` runs the CLI through the local Python server and shows the current run status.
- Successful launches show an `Open Game` area with one-click buttons for opening launch URLs in new tabs.
- Failed launches show `Game launch failed` in Run Status and keep the Markdown report link available for debugging.
- `Reload Config` rereads `config.json` and updates the form defaults without restarting the web server.
- `Clear all report` runs `python3 src/game_launch_loop.py --clear_report` and clears generated files from `reports`.
- Hover over `Reload Config` or `Clear all report` to see a short Chinese tooltip.

The web UI intentionally does not put request values into the browser URL. If old query parameters are present, the page removes them on load.

Run by game code range:

```bash
python3 src/game_launch_loop.py --env qa --range GALA_8000-GALA_8100
```

Run a single game code:

```bash
python3 src/game_launch_loop.py --env stg --game-code PPGROOVE_158000584
```

Run a few non-contiguous game codes:

```bash
python3 src/game_launch_loop.py --env stg --game-code PPGROOVE_158000584, PPGROOVE_158000223, PPGROOVE_158000123
```

Run multiple comma-separated ranges:

```bash
python3 src/game_launch_loop.py --env stg --game-code PPGROOVE_81500001-81500003, PPGROOVE_81500011-81500013
```

When an env has multiple credentials, the first one in `config.json` is used by default.
Select a different credential by `agent_id`:

```bash
python3 src/game_launch_loop.py --env stg --agent-id 12 --game-code PPGROOVE_158000584
```

For multi-env runs that need different credentials per env, use `env=agent_id`, e.g. `--agent-id qa=1087 --agent-id stg=12`.

Run a JSON launch plan with multiple vendor entries, per-vendor `agent_id`, and per-vendor currency:

```bash
python3 src/game_launch_loop.py --json Launch_STG_games.json
```

Example JSON format:

```json
{
  "env": "STG",
  "username": "test_user260701",
  "language": "en",
  "platform": "web",
  "lobbyUrl": "https://www.google.com",
  "ipAddress": "192.228.180.86",
  "vendor_1": {
    "agent_id": 12,
    "gameCode": "test_game1",
    "currency": "USD"
  },
  "vendor_2": {
    "agent_id": 12,
    "gameCode": "test_game2",
    "currency": "BRL"
  }
}
```

`--json` reads shared request fields from the top level, selects credentials from `config.json` by each vendor's `agent_id`, then launches each `vendor_N` entry with its own `gameCode` and `currency`. Use this when one JSON file needs to launch games across different vendors, agents, or currencies. This mode is CLI-only; the web UI does not read JSON launch plans.

Run from a file exported by DBeaver:

```bash
python3 src/game_launch_loop.py --env stg --input game_codes.csv
```

If the file has multiple columns, set the game code column name:

```bash
python3 src/game_launch_loop.py --env stg --input dbeaver_export.csv --game-code-column game_code
```

Run both QA and STG:

```bash
python3 src/game_launch_loop.py --env qa,stg --range GALA_8000-GALA_8100
```

Write output to a specific Markdown file:

```bash
python3 src/game_launch_loop.py --env qa --range GALA_8000-GALA_8100 --output reports/gala_launch.md
```

The script always appends a timestamp before `.md`, for example:

```text
reports/gala_launch-2026-06-29_11-20-30.md
```

Dry run without calling the API:

```bash
python3 src/game_launch_loop.py --env qa --range GALA_8000-GALA_8002 --dry-run
```

Clear generated reports:

```bash
python3 src/game_launch_loop.py --clear_report
```

After the script finishes, the generated Markdown report opens in Google Chrome by default. Disable that behavior with:

```bash
python3 src/game_launch_loop.py --env qa --game-code PPGROOVE_158000584 --no-open
```

If a test environment has an incomplete TLS certificate chain, use:

```bash
python3 src/game_launch_loop.py --env qa --game-code PPGROOVE_158000584 --insecure-skip-tls-verify
```

## Input File Formats

Supported:

- `.csv`
- `.tsv`
- plain `.txt`, one gameCode per line

CSV/TSV behavior:

- If `--game-code-column` is provided, that column is used.
- Otherwise, the script tries common names: `gameCode`, `game_code`, `GAME_CODE`, `code`.
- If no known header exists, it uses the first column.

## Signature Logic

For each request:

1. Generate `traceId` with UUID v4.
2. Build the JSON request body.
3. Generate `x-signature` with HMAC-SHA256 over the exact JSON body string using `x_api_secret`.
4. POST to `{ga_vendor_api}/game/url`.
5. Extract `token` from the `/game/url` response and POST `{"token":"..."}` to `{ga_vendor_api}/agentPlayer/gameSession`.
6. Mark `/game/url` as `Success: YES` only when the response is HTTP success and both `gameUrl` and `token` are present. A `200` response without both fields, such as `SC_GAME_DISABLED`, is reported as `Success: NO`.
7. Save a results table with clickable gameCode detail links and clickable launch URLs, plus per-game OpenSearch log links, `/game/url` request/response, and `/agentPlayer/gameSession` request/response details, into Markdown.
