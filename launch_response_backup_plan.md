# Launch Response Backup URL Plan

## Goal

Improve the Game Launch report and web UI so users can distinguish between the operator `/game/url` response and the vendor `responseBody` launch URL.

Reason:

- The current `Open Game` URL comes from the operator response field (`operatorResponse.data.gameUrl`).
- Some vendors may only open correctly through the vendor response body field (`responseBody.data.launchUrl` or `responseBody.url`).
- The existing `Open Game` behavior must stay unchanged.
- A new `Backup` button should open the playable URL from `responseBody`.
- Backup lookup should run in the background after a successful single-game launch, without blocking the first display of `Open Game`.

## Scope

Only change these surfaces:

- Markdown Details output in `src/game_launch_loop.py`.
- Launch result parsing in `src/web_input_server.py`.
- Launch result table rendering in `web/app.js`.
- Minimal CSS for the two per-row buttons in `web/styles.css`.
- `web/index.html` cache-busting query string for `app.js`.

Do not change:

- `/game/url` request payload.
- Existing `Open Game` button behavior.
- Existing launch success/failure rules.
- Existing report table columns unless required by this feature.
- OpenSearch search UI behavior.
- Normal launch completion speed; do not block showing `Open Game` while fetching backup data.

## Markdown Report Change

In `src/game_launch_loop.py`, inside `write_markdown()`, rename the current `Response` heading to:

```text
operator Response
```

Keep the JSON content exactly as the current `result["response_body"]`, because this is the operator API response from `/game/url`.

Add a new block immediately below it:

````text
responseBody

```json
{
  "error": false,
  "message": "",
  "data": {
    "launchUrl": "..."
  },
  "errorCode": null,
  "tenantErrorCode": null
}
```
````

The `responseBody` content must come from the real OpenSearch launch log `### Response Body` block. Do not synthesize this block from the operator `gameUrl`; some vendors return a different playable URL, such as `{"url":"https://api-stage.casinogate.dev/..."}`.

If OpenSearch does not return a matching response body, output an empty JSON code block rather than inventing a value.

Recommended result field:

```python
"backup_response_body": ""
```

The first Markdown write after launch may leave this block empty. The web UI background backup lookup can fill it later through `/api/backup-launch-url`.

Speed note:

- Do not enrich `backup_response_body` during every successful launch.
- OpenSearch lookup is slow because it drives the OpenSearch scraper and writes a report.
- Keep successful launch output fast; render `Open Game` first, then start backup lookup in the background.
- It is acceptable for the initial Markdown `responseBody` block to be empty until the background lookup finishes.
- Do not run backup lookup when launch failed.
- Do not run backup lookup for `Test STG launch`, because that path launches JSON vendor batches.
- Do not run backup lookup when the result contains more than one game row.

## Previous Wrong Approach

Do not build `responseBody` from `result["launch_url"]`.

This was the first attempted implementation and it was wrong:

```python
def response_body_from_launch_url(launch_url):
    if not launch_url:
        return ""
    return json.dumps(
        {
            "error": False,
            "message": "",
            "data": {"launchUrl": launch_url},
            "errorCode": None,
            "tenantErrorCode": None,
        },
        ensure_ascii=False,
    )
```

Why it is wrong:

- `result["launch_url"]` is parsed from the operator `/game/url` response.
- That value belongs to `operatorResponse.data.gameUrl`, not the vendor `responseBody`.
- Some vendors return a different playable URL in the real OpenSearch `Response Body`.
- CasinoGate is an example where the real vendor body is shaped like:

```json
{
  "url": "https://api-stage.casinogate.dev/api/tracker/v1/redirects?s_hash=5216d73fe2598b42&s_id=d807fc91913e2fb1"
}
```

If the code synthesizes `responseBody` from the operator URL, the Markdown will incorrectly show:

```json
{
  "error": false,
  "message": "",
  "data": {
    "launchUrl": "https://qa-launcher.atomrun.space/play/PPCG?token=..."
  },
  "errorCode": null,
  "tenantErrorCode": null
}
```

That makes the web UI `Backup` button open the same incorrect operator URL instead of the real vendor redirect URL.

Correct rule:

- `operator Response` must use `result["response_body"]`.
- `responseBody` must use `result["backup_response_body"]`.
- `backup_response_body` must be enriched after initial render from the OpenSearch report's real `### Response Body` section.
- Do not require the OpenSearch log `URL` field to contain `/game/url`; vendors such as CasinoGate may log the launch call as `/game-launch`.
- Choose the matching log by `Game Code`, then parse `### Response Body`. Accept either a playable URL key such as `launchUrl`, `gameUrl`, `gameLaunchUrl`, or `url`, or a response body whose complete value is a plain HTTP/HTTPS URL.
- If OpenSearch cannot provide the real `Response Body`, keep the Markdown `responseBody` block empty.

Markdown fence parsing rule:

- Do not use `\s*` between a heading and a fenced code block. In Python regex, `\s*` can consume newlines and skip past the intended empty code block.
- Use `[ \t]*` for same-line whitespace and `(?:[ \t]*\n)*` only when explicitly allowing blank lines before a fence.
- The bug to prevent: an empty `responseBody` block can be skipped, causing the replacement to consume the next `/agentPlayer/gameSession Request Body` fenced block.
- Add a regression fixture where `responseBody` is empty and immediately followed by `/agentPlayer/gameSession Request Body`; replacement must only fill `responseBody` and leave the gameSession request block unchanged.

## Web Backend Parsing Change

The web API returns launch rows from `parse_launch_urls()` in `src/web_input_server.py`.

Keep the existing `url` field as-is:

```python
"url": extract_open_game_url(launch_url)
```

Add a separate field:

```python
"backupUrl": backup_urls_by_index.get(markdown_cell(row, "#"), "")
```

Implementation approach:

1. Read the full markdown report text once.
2. Parse the `## Details` entries by result index.
3. In each Game Launch report details block, find the `responseBody` fenced JSON block.
4. Parse that block as JSON when possible; otherwise treat the complete value as a possible plain URL.
5. Recursively find the first available URL-like field in this order:
   - `launchUrl`
   - `gameUrl`
   - `gameLaunchUrl`
   - `url`
   If the parsed value itself is a string, accept it when it is a valid complete HTTP/HTTPS URL.
6. Store it by result index.
7. Merge that value into the corresponding Results table row as `backupUrl`.

Recommended helpers:

```python
def find_first_key(value, keys):
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key]:
                return str(value[key])
        for item in value.values():
            found = find_first_key(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first_key(item, keys)
            if found:
                return found
    return ""


def extract_response_body_backup_url(block):
    match = re.search(
        r"(?mi)^responseBody[ \t]*\n(?:[ \t]*\n)*[ \t]*```(?:json)?[ \t]*\n(.*?)\n```[ \t]*$",
        block,
        re.DOTALL,
    )
    if not match:
        return ""
    return response_body_launch_url(match.group(1))
```

Use the same fenced-block rule for `Request Body` username extraction and for report rewriting. The replacement regex must close on the same fenced block it opened:

```python
def write_report_response_body(report_path, index, response_body):
    text = report_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(^<a id=\"[^\"]+\"></a>\n###\s+{re.escape(str(index))}\..*?^responseBody[ \t]*\n(?:[ \t]*\n)*[ \t]*(```)(?:json)?[ \t]*\n)(.*?)(\n\2[ \t]*$)",
        re.MULTILINE | re.DOTALL,
    )
    if not pattern.search(text):
        return False
    updated = pattern.sub(
        lambda match: f"{match.group(1)}{response_body.strip()}{match.group(4)}",
        text,
        count=1,
    )
    report_path.write_text(updated, encoding="utf-8")
    return True
```

## Web UI Change

In `web/app.js`, update `renderLaunchUrls(items)` so each result row has two per-row buttons:

- `Open Game`: opens `item.url`.
- `Backup`: opens `item.backupUrl`.

Expected behavior:

- `Open Game` remains unchanged.
- `Backup` is placed to the right of `Open Game`.
- `Open Game` should appear immediately after launch completes.
- `Backup` starts disabled when `item.backupUrl` is empty.
- For a successful normal launch with exactly one result row, start backup lookup in the background after rendering the row.
- While background lookup is running, show `Loading` on the Backup button and keep it disabled.
- When lookup succeeds, cache the URL into `item.backupUrl` and enable `Backup`.
- When lookup fails, leave `Backup` disabled and do not overwrite the launch status unless the user explicitly clicked Backup.
- Bulk actions (`Open Selected Games`, `Open All Games`) continue to use only the existing `item.url` values.

Example row action cell:

```javascript
const hasUrl = Boolean(item.url);
const hasBackupUrl = Boolean(item.backupUrl);

row.innerHTML = `
  ...
  <td>
    <div class="launch-button-row">
      <button type="button" class="open-one" ${hasUrl ? '' : 'disabled'}>Open Game</button>
      <button type="button" class="open-backup" ${hasBackupUrl ? '' : 'disabled'}>Backup</button>
    </div>
  </td>
`;

row.querySelector('.open-one').addEventListener('click', () => openLaunchUrls([item.url]));
row.querySelector('.open-backup').addEventListener('click', () => openLaunchUrls([item.backupUrl]));
```

After `renderLaunchUrls()`, only normal `runLaunch()` should start the background lookup:

```javascript
const launchOk = result.launchOk ?? (!/\bsuccess=NO\b/.test(result.stdout || '') && result.ok);
setStatus(launchOk ? 'Completed' : 'Game launch failed', launchOk ? 'ok' : 'error');
if (launchOk && launchItems.length === 1) {
  lookupBackupLaunchUrlInBackground(launchItems[0]);
}
```

Do not call `lookupBackupLaunchUrlInBackground()` from `runTestStgLaunch()`.

## Background Backup API

Add a local web API endpoint:

```text
POST /api/backup-launch-url
```

Request payload:

```json
{
  "env": "qa",
  "username": "eso260904002",
  "gameCode": "PPCG_pragmatic-play.3-dancing-monkeys",
  "reportPath": "/Users/stephenhuang/game-launch-loop/reports/game-launch-2026-09-04_16-52-21.md",
  "index": "1"
}
```

Behavior:

- Run OpenSearch lookup only after the web UI has already rendered `Open Game`.
- Extract the real OpenSearch `### Response Body`.
- Parse the playable URL from `launchUrl`, `gameUrl`, `gameLaunchUrl`, or `url`.
- Return the URL to the web UI.
- If `reportPath` and `index` are provided, update that report's `responseBody` block with the fetched body.
- Reject `reportPath` values outside the local `reports` folder.

## CSS Change

Add a small row layout class in `web/styles.css`:

```css
.launch-button-row {
  display: flex;
  gap: 8px;
  align-items: center;
  white-space: nowrap;
}
```

This keeps `Open Game` and `Backup` aligned without changing the table structure.

## Cache Busting

After changing `web/app.js`, update the script version in `web/index.html`:

```html
<script src="/app.js?v=YYYYMMDD-backup-launch-url"></script>
```

This prevents the browser from using an old cached `app.js`.

## Verification

Run syntax checks:

```bash
python3 -m py_compile src/game_launch_loop.py src/web_input_server.py
/Users/stephenhuang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node --check web/app.js
```

Test markdown parsing with a fixture:

````python
from pathlib import Path
from tempfile import TemporaryDirectory
from src.web_input_server import parse_launch_urls

with TemporaryDirectory() as directory:
    report = Path(directory) / "report.md"
    report.write_text(
        """# Game Launch Loop Report

## Results

| # | Env | Agent | Game Code | Currency | HTTP | Success | Launch URL | Summary | Error |
|---:|---|---:|---|---|---:|---|---|---|---|
| 1 | qa | 1087 - QA Agent | [GAME_1](#1-game_1) | USD | 200 | YES | <a href="https://operator.example/game" target="_blank" rel="noopener noreferrer">Open Game</a> |  |  |

## Details

<a id="1-game_1"></a>
### 1. GAME_1

responseBody

```json
{
  "error": false,
  "message": "",
  "data": {
    "launchUrl": "https://vendor.example/game"
  },
  "errorCode": null,
  "tenantErrorCode": null
}
```
""",
        encoding="utf-8",
    )
    items = parse_launch_urls(str(report))
    assert items[0]["url"] == "https://operator.example/game"
    assert items[0]["backupUrl"] == "https://vendor.example/game"
````

Test responseBody rewriting with an empty code block followed by gameSession request:

````python
from pathlib import Path
from tempfile import TemporaryDirectory
from src.web_input_server import write_report_response_body

with TemporaryDirectory() as directory:
    report = Path(directory) / "report.md"
    report.write_text(
        """<a id="1-game"></a>
### 1. GAME

responseBody

```json

```

/agentPlayer/gameSession Request Body

```json
{
  "token": "token-1"
}
```
""",
        encoding="utf-8",
    )
    ok = write_report_response_body(report, "1", '{"url":"https://vendor.example/game"}')
    text = report.read_text(encoding="utf-8")
    assert ok is True
    assert '```json\n{"url":"https://vendor.example/game"}\n```\n\n/agentPlayer/gameSession Request Body' in text
    assert '```json\n{\n  "token": "token-1"\n}\n```' in text
````

Manual browser verification:

1. Restart the local web server if `src/web_input_server.py` changed.
2. Run one launch from the web UI.
3. Confirm the result row shows `Open Game` and `Backup`.
4. Confirm `Open Game` opens the original operator URL.
5. Confirm `Backup` opens the URL from `responseBody.data.launchUrl`.
6. Confirm `Backup` also supports vendor responses that use `responseBody.url`.
7. Confirm `Backup` supports a `responseBody` whose complete content is a plain HTTP/HTTPS URL.
8. Confirm rows without a supported URL show disabled `Backup`.

## Server Restart Note

Frontend-only changes need a hard reload after cache version update.

Backend parser changes require restarting the Game Launch web server:

```bash
python3 src/web_input_server.py --host 127.0.0.1 --port 20731 --no-browser
```
