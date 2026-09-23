# Easy Command Plan

## 目的

現在啟動 web UI 太麻煩，需要輸入完整路徑，例如 Windows：

```powershell
python C:\Users\Shan\Workspace2\game-launch-loop\src\web_input_server.py
```

或 macOS：

```bash
python3 /Users/${user}/game-launch-loop/src/web_input_server.py
```

目標是簡化成唯一全域指令：

```bash
gameurl
```

之後不管目前 shell 在哪個資料夾，都可以直接啟動 Game Launch Loop web UI，並自動開啟瀏覽器。

## 必須遵守的限制

- 這次目標只是新增一個全域啟動指令 `gameurl`。
- 不要更動其他功能。
- 不要修改 Game Launch 的 request flow。
- 不要修改 web UI 排版。
- 不要修改既有 API 行為。
- 不要修改 `src/web_input_server.py` 的啟動邏輯，除非只是為了確認既有參數可被 wrapper 傳入。
- 不要修改 `src/game_launch_loop.py`。
- 不要修改 `web/index.html`、`web/app.js`、`web/styles.css`。
- 不要重構 unrelated code。
- 允許新增的專案檔案只限於：
  - `scripts/gameurl.cmd`
  - `scripts/gameurl`
- 允許更新文件：
  - `easy_command_plan.md`
  - 實作完成後更新 `README.md` 的啟動說明。
- PATH 設定是使用者環境設定，不應寫進專案程式邏輯。

## 指令名稱

只使用這個 command：

```bash
gameurl
```

不規劃其他備用名稱。

## 專案內腳本

把 helper command 放在專案裡的 `scripts` 目錄。

Windows：

```text
C:\Users\Shan\Workspace2\game-launch-loop\scripts\gameurl.cmd
```

macOS：

```text
~/Workspace2/game-launch-loop/scripts/gameurl
```

之後把 `scripts` 資料夾加到 PATH。兩個平台都使用同一個指令名稱：

```bash
gameurl
```

## Windows CMD Wrapper

檔案：

```text
C:\Users\Shan\Workspace2\game-launch-loop\scripts\gameurl.cmd
```

內容：

```bat
@echo off
"C:\Users\Shan\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\Shan\Workspace2\game-launch-loop\src\web_input_server.py" %*
```

`%*` 會把參數原樣傳給 `web_input_server.py`，保留未來擴充彈性，例如：

```powershell
gameurl --port 20732
```

主要日常使用只需要：

```powershell
gameurl
```

## macOS Shell Wrapper

檔案：

```text
~/open-search/src/web_input_server.py
```

內容：

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python not found. Please install Python 3.9+." >&2
  exit 1
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/src/web_input_server.py" "$@"
```

macOS 需要讓檔案可執行：

```bash
chmod +x ~/game-launch-loop/scripts/gameurl
```

這個 macOS wrapper 用 `scripts/gameurl` 自己的位置反推專案根目錄，所以把專案搬到其他位置時，只要 PATH 指到新的 `scripts` 目錄，script 內容通常不用改。

## 為什麼 Windows 用固定 Python 路徑

目前已確認這個 Python 存在：

```text
C:\Users\Shan\AppData\Local\Programs\Python\Python313\python.exe
```

之前也遇過目前 shell 裡 `python` 不一定在 PATH 的狀況，所以 Windows wrapper 直接指定 Python 3.13 的完整路徑會比較穩。

macOS 則建議用 `python3`，因為 macOS 的 Python 安裝路徑較常依安裝方式不同而變動，例如 Homebrew、pyenv、python.org installer。

## Windows PATH 設定

實作完成後，把專案的 scripts 資料夾加到 User PATH：

```text
C:\Users\Shan\Workspace2\game-launch-loop\scripts
```

PowerShell 可用：

```powershell
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$scriptsPath = 'C:\Users\Shan\Workspace2\game-launch-loop\scripts'
if (($userPath -split ';') -notcontains $scriptsPath) {
  [Environment]::SetEnvironmentVariable('Path', "$userPath;$scriptsPath", 'User')
}
```

設定後需要重開 PowerShell，新的 PATH 才會生效。

## macOS PATH 設定

假設專案放在：

```text
~/Workspace2/game-launch-loop
```

把 scripts 加到 shell PATH。若使用 zsh：

```bash
echo 'export PATH="$HOME/game-launch-loop/scripts:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

若使用 bash：

```bash
echo 'export PATH="$HOME/game-launch-loop/scripts:$PATH"' >> ~/.bash_profile
source ~/.bash_profile
```

若專案路徑不同，只要把 PATH 裡的專案路徑改成實際位置。

## Windows 實作步驟

1. 在專案裡建立 `scripts` 資料夾：

```powershell
New-Item -ItemType Directory -Force -Path 'C:\Users\Shan\Workspace2\game-launch-loop\scripts'
```

2. 建立：

```text
C:\Users\Shan\Workspace2\game-launch-loop\scripts\gameurl.cmd
```

3. 寫入：

```bat
@echo off
"C:\Users\Shan\AppData\Local\Programs\Python\Python313\python.exe" "C:\Users\Shan\Workspace2\game-launch-loop\src\web_input_server.py" %*
```

4. 先不用 PATH，直接測試：

```powershell
C:\Users\Shan\Workspace2\game-launch-loop\scripts\gameurl.cmd
```

5. 確認 terminal 顯示：

```text
Game Launch Loop web UI: http://127.0.0.1:20731
Press Ctrl+C to stop.
```

6. 確認瀏覽器自動開啟 web UI。
7. 停掉 server 後，再把 scripts 資料夾加到 User PATH。
8. 重開 PowerShell。
9. 測試全域指令：

```powershell
gameurl
```

## macOS 實作步驟

1. 在專案裡建立 `scripts` 資料夾：

```bash
mkdir -p ~/game-launch-loop/scripts
```

2. 建立：

```text
~/game-launch-loop/scripts/gameurl
```

3. 寫入 macOS shell wrapper。
4. 設成可執行：

```bash
chmod +x ~/game-launch-loop/scripts/gameurl
```

5. 先不用 PATH，直接測試：

```bash
~/game-launch-loop/scripts/gameurl
```

6. 確認 terminal 顯示：

```text
Game Launch Loop web UI: http://127.0.0.1:20731
Press Ctrl+C to stop.
```

7. 確認瀏覽器自動開啟 web UI。
8. 停掉 server 後，把 scripts 加到 PATH。
9. 重開 terminal 或 source shell profile。
10. 測試全域指令：

```bash
gameurl
```

## 驗證清單

Windows：

- 直接執行 `scripts\gameurl.cmd` 可以啟動 server 並自動開 browser。
- 加 PATH 後，`gameurl` 可以從任何資料夾啟動 server 並自動開 browser。
- `gameurl --port 20732` 可以使用不同 port。
- Ctrl+C 可以正常停止 server。
- 不影響原本指令：

```powershell
python src\web_input_server.py
```

macOS：

- 直接執行 `scripts/gameurl` 可以啟動 server 並自動開 browser。
- 加 PATH 後，`gameurl` 可以從任何資料夾啟動 server 並自動開 browser。
- `gameurl --port 20732` 可以使用不同 port。
- Ctrl+C 可以正常停止 server。
- 不影響原本指令：

```bash
python3 src/web_input_server.py
```

## README 更新

實作完成後，建議在 `README.md` 的 `Usage` 補一段：

```markdown
### Easy Web Command

After adding `scripts` to your PATH, start the web UI from anywhere:

```bash
gameurl
```
```

## 注意事項

- `scripts\gameurl.cmd` 和 `scripts/gameurl` 都是專案檔案，可以一起版本控管。
- PATH 是使用者環境設定，不是專案檔案內容。
- Windows 若未來 Python 安裝路徑改變，需要同步更新 `scripts\gameurl.cmd`。
- Windows 若未來專案路徑改變，需要同步更新 `scripts\gameurl.cmd` 和 User PATH。
- macOS 若未來專案路徑改變，通常只需要更新 PATH 指到新的 `scripts` 目錄。
- macOS wrapper 依賴 `python3` 或 `python` 可以在 shell 裡找到。
