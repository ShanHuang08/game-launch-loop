# OpenSearch Log Search Plan

## 目的

在目前 Game Launch Loop web UI 新增一個 OpenSearch log 搜尋入口。這個功能是輔助工具，不是 game launch payload 的一部分。

入口位置固定放在 topbar 的 `Clear all report` 旁邊，做成一個 `OpenSearch Search` 按鈕。點擊按鈕時，在按鈕下方切換顯示搜尋 popover，讓使用者輸入 keyword、選擇 `QA` / `STG`，再按搜尋。

API 內部用 subprocess 執行另一個專案：

```text
/Users/stephenhuang/open-search
```

目前 Game Launch Loop 會先找 `ROOT.parent / "open-search"`，再 fallback 到 `ROOT.parent / "cli"`；Windows 文件裡的 `C:\Users\Shan\Workspace2\OpenSearch_Scrape` 是 OpenSearch_Scrape 原始專案路徑範例，不是目前 macOS 實作使用的固定路徑。

## 100% 必須遵守的限制

- 必須做檢查與 dry run。
- 實作前要先檢查目前 `web/index.html`、`web/app.js`、`web/styles.css`、`src/web_input_server.py` 的既有結構。
- 實作後要檢查沒有改壞既有 Game Launch 功能。
- 不可以改到原本 game launch 的排版。
- 不可以改到原本 game launch 的功能。
- 除了 topbar 新增 `OpenSearch Search` 按鈕與其 popover 外，其他 game launch UI 應與原本一模一樣。
- 不可以因為新增 OpenSearch 搜尋而移動、改名、刪除、重排任何既有 Game Launch 欄位、按鈕、結果表格、log 區塊、report link 行為。
- 不可以偷偷重構 unrelated code。
- CSS 只能新增 OpenSearch popover 需要的 class，或最小幅度調整 topbar 容器以容納新按鈕；不得影響既有 `.form-layout`、`.request-grid`、`.environment-section`、`.results`、`.launch-actions` 的既有呈現。
- JS 只能新增 OpenSearch 搜尋相關函式與事件綁定；既有 `runLaunch()`、`clearReports()`、`renderReport()`、`renderLaunchUrls()` 等行為不得被改變，除非只是被 OpenSearch 搜尋呼叫既有共用函式顯示結果。
- 後端只能新增 OpenSearch 搜尋／Clear log API 與 helper；既有 `/api/config`、`/api/run`、`/api/clear-reports` 行為不得改變。

## OpenSearch_Scrape 執行方式

已重新閱讀：

```text
C:\Users\Shan\Workspace2\OpenSearch_Scrape\README.md#執行
```

OpenSearch_Scrape 支援以下 CLI：

```powershell
open-search --env QA --keyword groove
open-search --env staging --keyword groove --keyword cs20260716071044
open-search --env QA --keyword groove or cs20260716071044
open-search --env QA --keyword groove and cs20260716071044
```

如果 CLI 指令尚未加入 PATH，也可以使用 module 方式：

```powershell
python -m cli --env QA --keyword groove --max-records 50
```

建議 web API 使用 module 方式。正式搜尋不要加 `--no-open-output`，讓 OpenSearch_Scrape 依照自己的預設行為，在產生 Markdown 後自動用系統預設瀏覽器開啟：

```powershell
python -m cli --env QA --keyword groove or cs20260716071044 --max-records 50
```

環境對應：

- UI `QA` -> CLI `--env QA`
- UI `STG` -> CLI `--env staging`

## macOS Markdown 自動開啟問題與預防方案

### 問題現象

OpenSearch 查詢與 Markdown 產生成功，但 CLI 顯示：

```text
Markdown：/Users/<user>/open-search/output/<report>.md
警告：開啟 Markdown 瀏覽器失敗（Error）。
```

或 Markdown 被 IDE 開啟，而不是預設瀏覽器。

### 根因

- `webbrowser.open(file://...md)` 在 macOS 上可能透過 AppleScript 開啟失敗，回傳 `Error`。
- 直接執行 `open file://...md` 會依 `.md` 副檔名的 LaunchServices 關聯開啟檔案；如果 `.md` 預設關聯到 VS Code、Cursor 或其他 IDE，就不會開啟瀏覽器。
- 因此，不能只依賴 `.md` 副檔名關聯，也不能只把本機檔案交給一般的 `open` 指令。

### 建議實作

macOS 應從 LaunchServices 讀取 `http`／`https` 的預設 handler Bundle ID，再明確指定瀏覽器開啟本機 Markdown：

```python
from pathlib import Path
import plistlib
import subprocess
import webbrowser


def macos_default_browser_bundle_id() -> str | None:
    result = subprocess.run(
        [
            "defaults",
            "export",
            "com.apple.LaunchServices/com.apple.launchservices.secure",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    preferences = plistlib.loads(result.stdout)
    for scheme in ("https", "http"):
        for handler in preferences.get("LSHandlers", []):
            if handler.get("LSHandlerURLScheme") == scheme:
                return handler.get("LSHandlerRoleAll")
    return None


def open_markdown_in_default_browser(path: Path) -> bool:
    url = path.resolve().as_uri()
    bundle_id = macos_default_browser_bundle_id()
    if bundle_id:
        return subprocess.run(
            ["open", "-b", bundle_id, url],
            check=False,
        ).returncode == 0
    return webbrowser.open(url)
```

實作注意事項：

- 只在 `sys.platform == "darwin"` 時使用上述 macOS 分支。
- `subprocess.run` 必須使用 argument list，不要使用 `shell=True`。
- `defaults export`、plist 解析或 `open -b` 失敗時要捕捉例外，輸出清楚警告，不能讓 Markdown 已成功產生的結果遺失。
- 非 macOS 平台維持 `webbrowser.open()` fallback。
- 讀取 handler 時優先檢查 `https`，再檢查 `http`；不要使用 `public.plain-text` 或 `.md` 的 handler。
- `--no-open-output` 必須仍可停用自動開啟行為。

### 驗證清單

在 macOS 測試以下情境：

1. 預設瀏覽器為 Chrome，`.md` 預設應用程式為 IDE：必須開啟 Chrome。
2. 預設瀏覽器改為 Safari，`.md` 預設應用程式仍為 IDE：必須開啟 Safari。
3. 瀏覽器 Bundle ID 無法讀取或瀏覽器未安裝：保留 Markdown，輸出警告，不應讓查詢失敗。
4. 使用 `--no-open-output`：不得呼叫任何開啟瀏覽器的函式。
5. 查詢成功時確認輸出檔存在，再確認瀏覽器開啟該檔案的 `open -b` 回傳碼為 0。

### 手動診斷指令

確認 macOS 目前的 URL handler：

```bash
defaults export com.apple.LaunchServices/com.apple.launchservices.secure - \
  | plutil -convert xml1 -o - -- \
  | grep -A4 -B2 'LSHandlerURLScheme'
```

確認程式實際產生的 Markdown 路徑可由指定瀏覽器開啟：

```bash
open -b com.google.chrome "/absolute/path/to/report.md"
```

若上述指令可開啟，問題通常在 CLI 使用了檔案副檔名關聯或 `webbrowser` controller；應修正 CLI 的開啟 helper，而不是改變輸出檔副檔名或刪除 Markdown。

## Keyword 規則

前端對使用者保持簡單：input field 直接輸入完整查詢字串。

支援範例：

```text
groove
groove or cs20260716071044
groove and cs20260716071044
```

判斷重點：

- `or` 必須前後都有空白，才視為 OR operator：`A or B`
- `and` 必須前後都有空白，才視為 AND operator：`A and B`
- 沒有空白的 `or` / `and` 不應被當作 operator，例如 `operatorData` 或 `grand` 只是一般 keyword。
- 如果同一個 input 同時出現 ` or ` 和 ` and `，後端應拒絕，避免查詢語意不清。
- 第一版只支援一層語法：`A or B`、`A and B`，不做括號或複雜 KQL 編輯器。

OpenSearch_Scrape 目前已在 `src/query.py` 提供 `parse_keyword_expression()`，會解析同一個 `--keyword` 後的 `or` / `and` 表達式。因此 Game Launch Loop API 可以把整個 input 原樣作為單一 `--keyword` 值傳入。

## Topbar Popover UI 計畫

修改 `web/index.html` 時，只在 `.topbar-actions` 裡新增一個 OpenSearch 搜尋入口，位置放在 `Clear all report` 旁邊。

建議順序：

```text
Clear all report
OpenSearch Search
Check all report
Reload Config
```

範例 HTML：

```html
<div class="opensearch-menu" id="opensearchMenu">
  <button id="opensearchToggle" type="button" class="secondary-button">
    OpenSearch Search
  </button>
  <section id="opensearchPopover" class="opensearch-popover hidden">
    <h2>OpenSearch Log Search</h2>
    <label>
      Search Text
      <input
        id="opensearchKeyword"
        autocomplete="off"
        placeholder="groove or cs20260716071044"
      >
    </label>
    <label>
      Environment
      <select id="opensearchEnv">
        <option value="QA">QA</option>
        <option value="STG">STG</option>
      </select>
    </label>
    <div class="opensearch-action-row">
      <button id="opensearchCheckLogsButton" type="button" class="secondary-button">
        Check Logs
      </button>
      <button id="opensearchClearLogButton" type="button" class="opensearch-clear-log-button">
        Clear log
      </button>
      <button id="opensearchSearchButton" type="button" class="opensearch-search-button">
        Search Logs
      </button>
    </div>
    <p class="field-hint">Use spaces around operators: groove or cs20260716071044</p>
  </section>
</div>
```

Popover 行為：

- Click `OpenSearch Search` button -> toggle popover。
- 第一次打開 popover 時，自動 focus 到 `Search Text` input，cursor 直接在 keyword input，使用者不用再點一次。
- Popover 開啟後保持顯示，讓使用者可以安心輸入、複製貼上、切換 `QA` / `STG`、點搜尋多次。
- `Search Text` input 支援 Enter 搜尋。
- `Check Logs` 按鈕固定放在 `Clear log` 按鈕左邊。
- `Clear log` 按鈕固定放在 `Search Logs` 按鈕左邊，使用紅底白字，三個按鈕放在同一列並靠右對齊。
- 點擊 `Check Logs` 時，前端呼叫 `POST /api/opensearch-check-logs`，由本機 server 用 Chrome 開新分頁指向 `file:///Users/stephenhuang/open-search/output/`。
- `Check Logs` 執行期間 disabled；成功時 Run Status 顯示 `OpenSearch logs opened`，失敗時顯示 API error。
- `Clear log` 只能由滑鼠／觸控點擊按鈕觸發，不綁定 Enter 或任何 keyboard shortcut。
- 在 keyword input 按 Enter 時只能執行搜尋，絕對不可執行 Clear log API。
- 按下 `Clear log` 後呼叫專用 API；執行期間按鈕 disabled，但文字保持不變。
- API 執行完成後，按鈕顯示 `Clear n files`，其中 `n` 是 API 回傳的 `removedCount`。
- `Search Logs` button enable 時使用藍底白字。
- 搜尋送出後，`Search Logs` button 要 disabled，文字改成 `Searching...`，並維持既有 disabled style，讓使用者知道搜尋已送出。
- 搜尋完成後，`Search Logs` button 再 enable，文字恢復 `Search Logs`。
- 一模一樣的搜尋如果正在執行中，第二次按 Search 或 Enter 不可以再送出 API。
- 建議採前端擋重複搜尋：用目前 keyword + environment 建立 signature，搭配 in-flight state 判斷。這比後端判斷簡單，也能立刻給使用者 UI feedback。
- Click outside -> 關閉 popover，但如果 `pointerdown` 從 popover 內開始，代表使用者可能正在拖曳選取 keyword；即使滑鼠放開或 click 落在 popover 外，也不可關閉 popover。
- Press `Escape` -> 關閉 popover。
- Click `OpenSearch Search` button again -> 關閉 popover。
- 按下搜尋後，popover 保持開啟，避免使用者想調整 keyword 時要重新打開。
- 不使用 hover 開啟。
- 不使用 mouseleave 關閉。
- 不使用 300-500ms close timer。
- popover 要稍微大一點，建議寬度約 `420px`。
- popover 位置建議用 `position: absolute`，對齊 `OpenSearch Search` 按鈕下方。
- 必須避免 popover 影響 topbar、launch form、results panel 的原本排版。

### Check Logs 設計限制

- 禁止使用 `window.open('file://...')`、`location.href = 'file://...'` 或 `<a href="file://...">` 從 Web UI 直接開啟本機目錄。
- 原因：頁面由 `http://127.0.0.1` / `http://localhost` 提供時，Chrome 會基於安全限制攔截 HTTP origin 導向本機 `file://` resource；click handler 即使有執行，也可能沒有新分頁且沒有明顯 JS error。
- 必須透過本機 backend API 執行 macOS `open -a "Google Chrome" <file-url>`，不得只用前端靜態檢查判定功能完成。
- output URL 必須由 `Path.resolve().as_uri()` 產生，避免自行拼接路徑與 URL encoding 問題。
- backend API response 的 `ok` 必須依 `open` command return code 決定；前端不得在 API failed 時顯示成功狀態。
- 修改或新增 backend route 後，必須重啟 `src/web_input_server.py`；只重新整理頁面不會載入新的 Python route。

記憶輸入：

- 使用 `localStorage` 記住上次輸入的 keyword。
- 使用 `localStorage` 記住上次選擇的 environment。
- 頁面載入時自動還原。
- 搜尋成功或 input change 時都可以更新 localStorage。

## 前端驗證

- input field trim 後為空時，不可送出。
- 空白時使用 `setCustomValidity()` 顯示提示文字：

```text
Please enter OpenSearch search text.
```

- 空白時不得呼叫 `/api/opensearch-log-search`。
- 每次 input 事件時清掉 validation message。
- 前端不需要拆 keyword，只要把完整字串送給 API。
- 可在提示文字提醒：`or` / `and` 前後要有空白。

## 前端 JS 計畫

修改 `web/app.js`，只新增 OpenSearch 相關函式和事件。

新增 payload：

```javascript
function buildOpenSearchPayload() {
  return {
    keyword: $('#opensearchKeyword').value.trim(),
    environment: $('#opensearchEnv').value,
  };
}
```

新增搜尋 action：

```javascript
let isOpenSearchSearching = false;
let activeOpenSearchSignature = '';

function openSearchSignature() {
  return JSON.stringify(buildOpenSearchPayload());
}

async function searchOpenSearchLogs() {
  const keywordInput = $('#opensearchKeyword');
  const keyword = keywordInput.value.trim();
  const signature = openSearchSignature();

  if (!keyword) {
    keywordInput.setCustomValidity('Please enter OpenSearch search text.');
    keywordInput.reportValidity();
    keywordInput.focus();
    return;
  }

  if (isOpenSearchSearching && signature === activeOpenSearchSignature) {
    setStatus('OpenSearch search is already running...', 'running');
    return;
  }

  keywordInput.setCustomValidity('');
  saveOpenSearchInputs();
  isOpenSearchSearching = true;
  activeOpenSearchSignature = signature;
  const searchButton = $('#opensearchSearchButton');
  searchButton.disabled = true;
  searchButton.textContent = 'Searching...';
  setStatus('Searching OpenSearch logs...', 'running');
  $('#logOutput').textContent = '';

  try {
    const result = await fetchJson('/api/opensearch-log-search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(buildOpenSearchPayload()),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    setStatus(result.ok ? 'OpenSearch search completed' : 'OpenSearch search failed', result.ok ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    isOpenSearchSearching = false;
    activeOpenSearchSignature = '';
    searchButton.disabled = false;
    searchButton.textContent = 'Search Logs';
  }
}
```

新增 Clear log action：

```javascript
let isOpenSearchClearing = false;

async function clearOpenSearchLogs() {
  if (isOpenSearchClearing) return;

  const clearButton = $('#opensearchClearLogButton');
  isOpenSearchClearing = true;
  clearButton.disabled = true;

  try {
    const result = await fetchJson('/api/opensearch-clear-log', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    clearButton.textContent = result.ok ? `Clear ${result.removedCount} files` : 'Clear log';
    setStatus(result.ok ? `Clear ${result.removedCount} files` : 'Clear log failed', result.ok ? 'ok' : 'error');
  } catch (error) {
    clearButton.textContent = 'Clear log';
    setStatus(error.message, 'error');
  } finally {
    isOpenSearchClearing = false;
    clearButton.disabled = false;
  }
}
```

新增 popover control：

```javascript
function openOpenSearchPopover() {
  $('#opensearchPopover').classList.remove('hidden');
  requestAnimationFrame(() => $('#opensearchKeyword').focus());
}

function closeOpenSearchPopover() {
  $('#opensearchPopover').classList.add('hidden');
}

function toggleOpenSearchPopover() {
  if (isOpenSearchPopoverOpen()) {
    closeOpenSearchPopover();
  } else {
    openOpenSearchPopover();
  }
}

function isOpenSearchPopoverOpen() {
  return !$('#opensearchPopover').classList.contains('hidden');
}
```

新增 localStorage：

```javascript
function loadOpenSearchInputs() {
  $('#opensearchKeyword').value = localStorage.getItem('opensearchKeyword') || '';
  $('#opensearchEnv').value = localStorage.getItem('opensearchEnv') || 'QA';
}

function saveOpenSearchInputs() {
  localStorage.setItem('opensearchKeyword', $('#opensearchKeyword').value.trim());
  localStorage.setItem('opensearchEnv', $('#opensearchEnv').value);
}
```

新增 Check Logs action。瀏覽器會阻擋 `http://localhost` 直接開啟 `file://`，因此改由本機後端呼叫 Chrome：

```javascript
async function checkOpenSearchLogs() {
  const checkButton = $('#opensearchCheckLogsButton');
  checkButton.disabled = true;

  try {
    const result = await fetchJson('/api/opensearch-check-logs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    setStatus(result.ok ? 'OpenSearch logs opened' : 'Unable to open OpenSearch logs', result.ok ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    checkButton.disabled = false;
  }
}
```

在 `DOMContentLoaded` 綁定：

```javascript
let openSearchPointerStartedInside = false;

loadOpenSearchInputs();

$('#opensearchToggle').addEventListener('click', (event) => {
  event.stopPropagation();
  toggleOpenSearchPopover();
});
$('#opensearchPopover').addEventListener('click', (event) => {
  event.stopPropagation();
});
$('#opensearchKeyword').addEventListener('input', () => {
  $('#opensearchKeyword').setCustomValidity('');
  saveOpenSearchInputs();
});
$('#opensearchKeyword').addEventListener('keydown', (event) => {
  if (event.key !== 'Enter') return;
  event.preventDefault();
  // Enter 只支援搜尋，不得呼叫 clearOpenSearchLogs()。
  searchOpenSearchLogs();
});
$('#opensearchEnv').addEventListener('change', saveOpenSearchInputs);
$('#opensearchCheckLogsButton').addEventListener('click', checkOpenSearchLogs);
$('#opensearchClearLogButton').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
  }
});
$('#opensearchClearLogButton').addEventListener('click', clearOpenSearchLogs);
$('#opensearchSearchButton').addEventListener('click', searchOpenSearchLogs);
document.addEventListener('pointerdown', (event) => {
  openSearchPointerStartedInside = Boolean(event.target.closest('#opensearchPopover'));
});
document.addEventListener('click', (event) => {
  if (event.target.closest('#opensearchMenu')) return;
  if (openSearchPointerStartedInside) {
    openSearchPointerStartedInside = false;
    return;
  }
  if (isOpenSearchPopoverOpen()) closeOpenSearchPopover();
  if (event.target.closest('.currency-select')) return;
  document.querySelectorAll('.currency-popover').forEach((item) => item.classList.add('hidden'));
  document.querySelectorAll('.currency-trigger').forEach((item) => item.setAttribute('aria-expanded', 'false'));
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeOpenSearchPopover();
});
```

## API 計畫

新增搜尋 API：

```http
POST /api/opensearch-log-search
Content-Type: application/json
```

Request body：

```json
{
  "keyword": "groove or cs20260716071044",
  "environment": "QA"
}
```

測試用 request body 可額外帶 `dryRun: true`，後端會把 `--dry-run` 加到 OpenSearch_Scrape command；前端正式搜尋不送這個欄位。

Response body：

```json
{
  "ok": true,
  "returnCode": 0,
  "command": [
    "...python...",
    "-m",
    "cli",
    "--env",
    "QA",
    "--keyword",
    "groove or cs20260716071044",
    "--max-records",
    "50"
  ],
  "stdout": "...",
  "stderr": "..."
}
```

錯誤 response：

```json
{
  "ok": false,
  "error": "keyword is required"
}
```

新增 Clear log API：

```http
POST /api/opensearch-clear-log
Content-Type: application/json
```

Request body 不需要參數，可傳空物件：

```json
{}
```

API 必須執行以下 OpenSearch_Scrape CLI 行為：

```text
open-search --clear_log
```

為了沿用指定 virtual environment，後端實際 command 可使用等價的 module 形式：

```text
<python> -m cli --clear_log
```

成功 response：

```json
{
  "ok": true,
  "returnCode": 0,
  "command": ["...python...", "-m", "cli", "--clear_log"],
  "removedCount": 6,
  "stdout": "Output 已清空：...",
  "stderr": ""
}
```

Clear log API 不接受 keyword 或 environment，也不可以轉送搜尋。

新增 Check Logs API，由本機 server 呼叫 Chrome 開啟 OpenSearch_Scrape output folder：

```http
POST /api/opensearch-check-logs
Content-Type: application/json
```

```json
{
  "ok": true,
  "returnCode": 0,
  "url": "file:///Users/stephenhuang/open-search/output/",
  "stderr": ""
}
```

實作約束：

- API 不接受 client 傳入的任意 path 或 URL，固定開啟 `opensearch_project_dir() / "output"`，避免成為可開啟任意本機位置的 endpoint。
- 使用 argument list 呼叫 `subprocess.run()`，不可使用 `shell=True`。
- command 為 `open -a "Google Chrome" <output-url>`，並回傳 `returnCode` 與 `stderr` 供前端顯示錯誤。

## 後端實作計畫

修改 `src/web_input_server.py`。

新增常數：

```python
OPENSEARCH_PROJECT_CANDIDATES = (
    ROOT.parent / "open-search",
    ROOT.parent / "cli",
)
OPENSEARCH_DEFAULT_MAX_RECORDS = 50
```

新增 OpenSearch project 目錄選擇：

```python
def opensearch_project_dir():
    for candidate in OPENSEARCH_PROJECT_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return OPENSEARCH_PROJECT_CANDIDATES[0]
```

新增 Python executable 選擇：

```python
def opensearch_python_path():
    project_dir = opensearch_project_dir()
    candidates = [
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)
```

新增 keyword validation：

```python
def validate_opensearch_keyword(keyword):
    if not keyword:
        raise ValueError("keyword is required")
    has_or = re.search(r"\s+or\s+", keyword, re.I)
    has_and = re.search(r"\s+and\s+", keyword, re.I)
    if has_or and has_and:
        raise ValueError("keyword cannot mix or and and operators")
```

注意：這裡刻意用 `\s+or\s+` / `\s+and\s+`，代表 `or` / `and` 前後必須有空白才算 operator。

新增 command builder：

```python
def build_opensearch_command(payload):
    keyword = str(payload.get("keyword", "")).strip()
    environment = str(payload.get("environment", "")).strip().upper()
    project_dir = opensearch_project_dir()

    if not project_dir.is_dir():
        raise ValueError(f"OpenSearch project not found: {project_dir}")
    validate_opensearch_keyword(keyword)
    if environment not in {"QA", "STG"}:
        raise ValueError("environment must be QA or STG")

    cli_environment = "staging" if environment == "STG" else "QA"
    command = [
        str(opensearch_python_path()),
        "-m",
        "cli",
        "--env",
        cli_environment,
        "--keyword",
        keyword,
        "--max-records",
        str(OPENSEARCH_DEFAULT_MAX_RECORDS),
    ]
    if payload.get("dryRun"):
        command.append("--dry-run")
    return command
```

新增 Clear log command builder：

```python
def build_opensearch_clear_log_command():
    project_dir = opensearch_project_dir()
    if not project_dir.is_dir():
        raise ValueError(f"OpenSearch project not found: {project_dir}")
    return [
        str(opensearch_python_path()),
        "-m",
        "cli",
        "--clear_log",
    ]
```

新增 Clear log 移除數量解析：

```python
def parse_clear_log_removed_count(stdout):
    match = re.search(r"移除\s+(\d+)\s+個項目", stdout)
    return int(match.group(1)) if match else 0
```

新增 `do_POST` 分支：

```python
if self.path == "/api/opensearch-check-logs":
    try:
        output_url = (opensearch_project_dir() / "output").resolve().as_uri()
        completed = open_in_chrome(output_url)
        write_json(self, 200, {
            "ok": completed.returncode == 0,
            "returnCode": completed.returncode,
            "url": output_url,
            "stderr": completed.stderr,
        })
    except Exception as error:
        write_json(self, 400, {"ok": False, "error": str(error)})
    return

if self.path == "/api/opensearch-log-search":
    try:
        payload = read_json_body(self)
        command = build_opensearch_command(payload)
        completed = subprocess.run(
            command,
            cwd=opensearch_project_dir(),
            text=True,
            capture_output=True,
            check=False,
        )
        write_json(self, 200, {
            "ok": completed.returncode == 0,
            "returnCode": completed.returncode,
            "command": command,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
    except Exception as error:
        write_json(self, 400, {"ok": False, "error": str(error)})
    return
```

新增 Clear log `do_POST` 分支：

```python
if self.path == "/api/opensearch-clear-log":
    try:
        command = build_opensearch_clear_log_command()
        completed = subprocess.run(
            command,
            cwd=opensearch_project_dir(),
            text=True,
            capture_output=True,
            check=False,
        )
        write_json(self, 200, {
            "ok": completed.returncode == 0,
            "returnCode": completed.returncode,
            "command": command,
            "removedCount": parse_clear_log_removed_count(completed.stdout),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
    except Exception as error:
        write_json(self, 400, {"ok": False, "error": str(error)})
    return
```

## Report 連結策略

這一段不用額外處理。

正式搜尋時不要傳 `--no-open-output`。OpenSearch_Scrape 在執行完成後會依照自己的預設行為，自動用系統預設瀏覽器開啟產生的 Markdown。

因此 Game Launch Loop 不需要：

- parse OpenSearch_Scrape stdout 裡的 Markdown path
- copy OpenSearch_Scrape 的 Markdown 到本專案 `reports/`
- 新增 `/opensearch-output/...` 靜態路由
- 回傳 `reportPath` / `reportUrl`
- 改動既有 `renderReport()` 行為

搜尋 API 回傳 `ok`、`returnCode`、`command`、`stdout`、`stderr`；Clear log API 另外回傳 `removedCount`，讓前端顯示 `Clear n files`。執行輸出仍顯示在既有 Log 區塊。

## CSS 計畫

修改 `web/styles.css` 時只新增 OpenSearch popover 相關 class。

```css
.opensearch-menu {
  position: relative;
}

.opensearch-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 20;
  width: 420px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  box-shadow: 0 12px 32px rgba(29, 36, 48, 0.18);
  padding: 14px;
}

.opensearch-popover label {
  margin-top: 10px;
}

.opensearch-popover button {
  margin-top: 12px;
}

.opensearch-action-row {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
}

.opensearch-search-button {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.opensearch-search-button:hover:not(:disabled) {
  background: var(--primary-dark);
  border-color: var(--primary-dark);
}

.opensearch-clear-log-button {
  background: #c62828;
  border-color: #c62828;
  color: #fff;
}

.opensearch-clear-log-button:hover:not(:disabled) {
  background: #a91f1f;
  border-color: #a91f1f;
}

.field-hint {
  margin-top: 8px;
  color: var(--muted);
  font-size: 13px;
}

@media (max-width: 960px) {
  .opensearch-popover {
    right: auto;
    left: 0;
    width: min(420px, calc(100vw - 48px));
  }
}
```

## 必須做的檢查與 dry run

實作前：

1. 檢查目前 topbar 結構，確認只在 `Clear all report` 旁新增 wrapper/button/popover。
2. 檢查目前 Game Launch form 和 results panel 的 class，列出不可改動區塊。

實作後：

1. 執行 Python 編譯檢查：

```powershell
python -m py_compile src\web_input_server.py
```

2. 執行後端 dry run 測試，不登入 OpenSearch、不抓資料，只確認 command 組裝與 keyword operator：

```powershell
python -m cli --env QA --keyword groove or cs20260716071044 --dry-run
python -m cli --env QA --keyword groove and cs20260716071044 --dry-run
```

3. 若從 Game Launch Loop API 測試，應先用 payload 加上 dry-run 支援，或暫時讓後端 command builder 支援 internal dry-run 測試；不得直接用真搜尋當第一個驗證。
4. 啟動 web UI 後手動檢查：
   - 原本 Game Launch 欄位位置不變。
   - 原本 QA/STG launch 選項不變。
   - 原本 Clear all report 可用。
   - 原本 Check all report 可用。
   - 原本 Reload Config 可用。
   - 原本 Launch Game 可用。
   - 原本 report link / launch urls / log output 行為不變。
   - OpenSearch input 空白時前端擋下，並顯示提示文字。
   - Click `OpenSearch Search` 會 toggle popover。
   - 第一次打開 popover 時 keyword input 自動 focus，cursor 在 input 裡。
   - Popover 開啟後可以正常輸入、貼上、切換 QA/STG、連續搜尋。
   - 在 keyword input 按 Enter 會觸發搜尋。
   - `Check Logs` 位於 `Clear log` 左邊。
   - 點擊 `Check Logs` 會送出一次 `POST /api/opensearch-check-logs`，執行期間按鈕 disabled。
   - 必須在實際 Chrome 點擊測試，確認真的新增分頁，且新分頁 URL 精確為 `file:///Users/stephenhuang/open-search/output/`；只有 API 200、button click 成功或無 console error 都不足以判定通過。
   - 成功後 Run Status 顯示 `OpenSearch logs opened`，API 失敗時顯示 error 且按鈕恢復 enabled。
   - Chrome 測試前後應比較 open tabs，確認不是既有同 URL 分頁造成誤判。
   - `Clear log` 位於 `Search Logs` 左邊，呈現紅底白字。
   - 點擊 `Clear log` 會呼叫 `/api/opensearch-clear-log`，並執行 `open-search --clear_log` 的等價 module command。
   - `Clear log` 執行期間 disabled，但按鈕文字不顯示 loading 文案。
   - Clear log API 完成後，按鈕顯示 `Clear n files`，`n` 與 response 的 `removedCount` 相同。
   - Enter 只觸發搜尋，不會觸發 Clear log。
   - 搜尋中 button disabled，文字顯示 `Searching...`。
   - 同一組 keyword/env 搜尋正在執行時，再按 Search 或 Enter 不會再送第二次 API。
   - 搜尋完成後 button enable，文字恢復 `Search Logs`。
   - Click outside 會關閉 popover。
   - 如果 `pointerdown` 從 popover 內開始，例如在 keyword input 拖曳選字，即使放開時游標在 popover 外，也不會關閉 popover。
   - Press Escape 會關閉 popover。
   - 再按一次 `OpenSearch Search` 會關閉 popover。
   - 重新整理後 keyword/env 可從 localStorage 還原。

## 實作順序

1. 在 `src/web_input_server.py` 新增 helper、`POST /api/opensearch-check-logs`、`POST /api/opensearch-log-search` 與 `POST /api/opensearch-clear-log`。
2. 先用 dry run 驗證搜尋 command builder，並用臨時 output 目錄驗證 Clear log command builder；Check Logs 先 mock `subprocess.run()` 驗證 Chrome command arguments。
3. 在 `web/index.html` 的 `.topbar-actions` 裡新增 `OpenSearch Search` button/popover。
4. 在 `web/app.js` 新增 popover 控制、localStorage、空白驗證、Check Logs 開啟 output folder、API 呼叫。
5. 在 `web/styles.css` 新增 popover CSS。
6. 重啟 Web server，並在實際 Chrome 完成「必須做的檢查與 dry run」章節列出的所有檢查。

## 注意事項

- subprocess 必須使用 `cwd=opensearch_project_dir()`，讓 OpenSearch_Scrape 正確讀取自己的 `.env`。
- 優先使用 OpenSearch_Scrape 的 `.venv/bin/python`，Windows 則使用 `.venv\Scripts\python.exe`，因為 Playwright 等依賴通常安裝在該 venv。
- input 只做簡單語法，完整 KQL 組裝交給 OpenSearch_Scrape。
- 這個 API 會執行本機命令，只建議維持 localhost 使用。
