#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import subprocess
import sys
import uuid
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
WEB_DIR = ROOT / "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 20731


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_config(config):
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize_env_config(env_config):
    if isinstance(env_config, dict) and "agents" in env_config:
        if isinstance(env_config.get("currency"), list):
            env_config = {
                **env_config,
                "currency": normalize_currency_list(env_config.get("currency"))[0]
                if normalize_currency_list(env_config.get("currency"))
                else "",
            }
        return env_config

    agents = env_config if isinstance(env_config, list) else [env_config]
    env_defaults = {}
    shared_keys = (
        "ga_vendor_api",
        "currency",
        "language",
        "platform",
        "lobbyUrl",
        "ipAddress",
        "insecure_skip_tls_verify",
        "user_agent",
    )
    for key in shared_keys:
        values = [agent.get(key) for agent in agents if isinstance(agent, dict) and key in agent]
        if values and all(value == values[0] for value in values):
            env_defaults[key] = values[0]
    env_defaults["agents"] = [
        {key: value for key, value in agent.items() if key not in shared_keys}
        for agent in agents
        if isinstance(agent, dict)
    ]
    return env_defaults


def safe_config_payload(config):
    environments = {}
    for env_name, raw_env in config.get("environments", {}).items():
        env = normalize_env_config(raw_env)
        environments[env_name] = {
            "currency": env.get("currency", ""),
            "agents": [
                {
                    "id": agent.get("agent_id"),
                    "name": agent.get("agent_name") or agent.get("name") or "",
                }
                for agent in env.get("agents", [])
            ],
            "agentIds": [agent.get("agent_id") for agent in env.get("agents", [])],
        }
    return {
        "request": config.get("request", {}),
        "environments": environments,
    }


def read_json_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def write_json(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def validate_run_payload(payload, config):
    errors = []
    request = payload.get("request", {})
    env_names = payload.get("envs", [])
    agent_ids = payload.get("agentIds", {})
    currencies = payload.get("currencies", {})
    game_input = str(payload.get("gameInput", "")).strip()

    if not request.get("username"):
        errors.append("username is required")
    if not game_input:
        errors.append("gameCode or range is required")
    if not env_names:
        errors.append("at least one env is required")

    environments = config.get("environments", {})
    for env_name in env_names:
        if env_name not in environments:
            errors.append(f"unknown env: {env_name}")
            continue
        env = normalize_env_config(environments[env_name])
        available_agent_ids = {str(agent.get("agent_id")) for agent in env.get("agents", [])}
        if str(agent_ids.get(env_name, "")) not in available_agent_ids:
            errors.append(f"invalid agent_id for {env_name}")
        if not normalize_currency_list(currencies.get(env_name)):
            errors.append(f"currency is required for {env_name}")

    if errors:
        raise ValueError("; ".join(errors))


def normalize_currency_list(value):
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = [value]
    return [str(item).strip() for item in raw_values if str(item or "").strip()]


def update_config_from_payload(config, payload):
    request_payload = payload.get("request", {})
    request_config = config.setdefault("request", {})
    request_config["username"] = request_payload.get("username", "").strip()
    request_config["language"] = request_payload.get("language", "en").strip() or "en"
    request_config["platform"] = request_payload.get("platform", "WEB").strip() or "WEB"
    request_config["lobbyUrl"] = request_payload.get("lobbyUrl", "https://www.google.com/").strip() or "https://www.google.com/"
    request_config["ipAddress"] = request_payload.get("ipAddress", "192.228.180.86").strip() or "192.228.180.86"

    envs = config.setdefault("environments", {})
    for env_name in payload.get("envs", []):
        envs[env_name] = normalize_env_config(envs[env_name])
        selected_currencies = normalize_currency_list(payload.get("currencies", {}).get(env_name))
        if selected_currencies:
            envs[env_name]["currency"] = selected_currencies[0]


def is_range_input(value):
    return bool(re.fullmatch(r"[A-Za-z0-9]+_\d+-([A-Za-z0-9]+_)?\d+", value.strip()))


def parse_game_range(value):
    start_part, end_part = value.strip().split("-", 1)
    start_match = re.fullmatch(r"(.+_)(\d+)", start_part)
    end_match = re.fullmatch(r"(?:(.+_))?(\d+)", end_part)
    if not start_match or not end_match:
        raise ValueError(f"Invalid range: {value}")

    start_prefix, start_number = start_match.groups()
    end_prefix, end_number = end_match.groups()
    if end_prefix and end_prefix != start_prefix:
        raise ValueError("Range prefix must match, e.g. GALA_8000-GALA_8100.")

    width = len(start_number)
    start = int(start_number)
    end = int(end_number)
    step = 1 if end >= start else -1
    return [f"{start_prefix}{number:0{width}d}" for number in range(start, end + step, step)]


def parse_game_input(value):
    raw_codes = []
    for part in str(value).split(","):
        item = part.strip()
        if not item:
            continue
        if is_range_input(item):
            raw_codes.extend(parse_game_range(item))
        else:
            raw_codes.append(item)

    codes = []
    seen = set()
    for code in raw_codes:
        if code in seen:
            continue
        codes.append(code)
        seen.add(code)
    return codes


def has_multiple_currencies(payload):
    return any(
        len(normalize_currency_list(value)) > 1
        for value in payload.get("currencies", {}).values()
    )


def build_json_plan(payload):
    env_names = payload.get("envs", [])
    if len(env_names) != 1:
        raise ValueError("multi-currency launch currently supports one environment at a time")

    env_name = env_names[0]
    currencies = normalize_currency_list(payload.get("currencies", {}).get(env_name))
    game_codes = parse_game_input(payload.get("gameInput", ""))
    if not game_codes:
        raise ValueError("gameCode or range is required")

    plan = {
        "env": env_name,
        **payload.get("request", {}),
        "vendors": [],
    }
    agent_id = payload.get("agentIds", {}).get(env_name)
    for game_code in game_codes:
        for currency in currencies:
            plan["vendors"].append(
                {
                    "agent_id": agent_id,
                    "gameCode": game_code,
                    "currency": currency,
                }
            )
    return plan


def write_json_plan(payload):
    plan_dir = ROOT / "reports"
    plan_dir.mkdir(exist_ok=True)
    plan_path = plan_dir / f"web-launch-plan-{uuid.uuid4().hex}.json"
    plan_path.write_text(json.dumps(build_json_plan(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan_path


def build_command(payload):
    temp_paths = []
    if has_multiple_currencies(payload):
        plan_path = write_json_plan(payload)
        command = [
            sys.executable,
            "src/game_launch_loop.py",
            "--json",
            str(plan_path),
            "--no-open",
        ]
        if payload.get("dryRun"):
            command.append("--dry-run")
        if payload.get("outputPrefix"):
            command.extend(["--output", f"reports/{payload['outputPrefix']}.md"])
        return command, temp_paths

    env_names = payload.get("envs", [])
    game_input = str(payload.get("gameInput", "")).strip()
    command = [
        sys.executable,
        "src/game_launch_loop.py",
        "--env",
        ",".join(env_names),
        "--no-open",
    ]

    for env_name in env_names:
        agent_id = payload.get("agentIds", {}).get(env_name)
        command.extend(["--agent-id", f"{env_name}={agent_id}"])

    if is_range_input(game_input):
        command.extend(["--range", game_input])
    else:
        command.extend(["--game-code", game_input])

    if payload.get("dryRun"):
        command.append("--dry-run")
    if payload.get("outputPrefix"):
        command.extend(["--output", f"reports/{payload['outputPrefix']}.md"])
    return command, temp_paths


def build_clear_reports_command():
    return [
        sys.executable,
        "src/game_launch_loop.py",
        "--clear_report",
    ]


def extract_report_path(stdout):
    match = re.search(r"Markdown report written:\s*(.+)", stdout)
    if not match:
        return ""
    path = Path(match.group(1).strip())
    return str(path if path.is_absolute() else ROOT / path)


def split_markdown_row(row):
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def extract_markdown_label(value):
    match = re.search(r"\[([^\]]+)\]", value)
    return match.group(1) if match else value


def extract_open_game_url(value):
    match = re.search(r'<a href="([^"]+)"[^>]*>Open Game</a>', value)
    return html.unescape(match.group(1)) if match else ""


def extract_opensearch_url(report_path):
    if not report_path:
        return ""
    path = Path(report_path)
    if not path.exists():
        return ""
    match = re.search(
        r'<a href="([^"]+)"[^>]*>OpenSearch Log</a>',
        path.read_text(encoding="utf-8"),
    )
    return html.unescape(match.group(1)) if match else ""


def markdown_cell(row, name, default=""):
    return row.get(name, default)


def parse_launch_urls(report_path):
    if not report_path:
        return []
    path = Path(report_path)
    if not path.exists():
        return []

    launch_urls = []
    headers = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = split_markdown_row(line)
        if cells and cells[0] == "#":
            headers = cells
            continue
        if not headers or not cells or cells[0].startswith("---") or "Open Game" not in line:
            continue
        row = dict(zip(headers, cells))
        agent = markdown_cell(row, "Agent")
        game_code = markdown_cell(row, "Game Code")
        launch_url = markdown_cell(row, "Launch URL")
        if not agent or not game_code:
            continue
        launch_urls.append(
            {
                "env": markdown_cell(row, "Env"),
                "agent": agent,
                "agentId": agent.split(" - ", 1)[0],
                "agentName": agent.split(" - ", 1)[1] if " - " in agent else "",
                "gameCode": extract_markdown_label(game_code),
                "currency": markdown_cell(row, "Currency"),
                "httpStatus": markdown_cell(row, "HTTP"),
                "success": markdown_cell(row, "Success"),
                "url": extract_open_game_url(launch_url),
                "summary": markdown_cell(row, "Summary"),
                "error": markdown_cell(row, "Error"),
            }
        )
    return launch_urls


def report_has_failures(report_path):
    if not report_path:
        return None
    path = Path(report_path)
    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    failed_match = re.search(r"^- Failed:\s*`?(\d+)`?", content, re.MULTILINE)
    success_match = re.search(r"^- Success:\s*`?(\d+)`?", content, re.MULTILINE)
    requests_match = re.search(r"^- Requests:\s*`?(\d+)`?", content, re.MULTILINE)

    if failed_match:
        return int(failed_match.group(1)) > 0
    if success_match and requests_match:
        return int(success_match.group(1)) < int(requests_match.group(1))
    return None


def report_web_url(report_path):
    if not report_path:
        return ""
    try:
        relative = Path(report_path).resolve().relative_to(ROOT.resolve())
    except ValueError:
        return ""
    return "/" + str(relative).replace("\\", "/")


def open_in_chrome(url):
    commands = []
    if sys.platform == "darwin":
        commands.append(["open", "-a", "Google Chrome", url])
    elif sys.platform.startswith("win"):
        for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_name)
            if not base:
                continue
            chrome_path = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if chrome_path.exists():
                commands.append([str(chrome_path), url])
        commands.extend((["chrome", url], ["chrome.exe", url]))
    else:
        commands.extend(
            (
                ["google-chrome", url],
                ["google-chrome-stable", url],
                ["chromium", url],
                ["chromium-browser", url],
                ["xdg-open", url],
            )
        )

    last_error = None
    for command in commands:
        try:
            completed = subprocess.run(command, check=False)
            if completed.returncode == 0:
                return
        except OSError as error:
            last_error = error

    if webbrowser.open(url):
        return
    if last_error:
        print(f"Could not open browser automatically: {last_error}", file=sys.stderr)


class WebInputHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        parsed = urlparse(path)
        clean_path = unquote(parsed.path)
        if clean_path == "/":
            return str(WEB_DIR / "index.html")
        if clean_path.startswith("/web/"):
            return str(ROOT / clean_path.lstrip("/"))
        if clean_path.startswith("/reports/"):
            return str(ROOT / clean_path.lstrip("/"))
        candidate = WEB_DIR / clean_path.lstrip("/")
        return str(candidate)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/config":
            try:
                write_json(self, 200, safe_config_payload(load_config()))
            except Exception as error:
                write_json(self, 500, {"ok": False, "error": str(error)})
            return
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/clear-reports":
            try:
                command = build_clear_reports_command()
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                write_json(
                    self,
                    200,
                    {
                        "ok": completed.returncode == 0,
                        "returnCode": completed.returncode,
                        "command": command,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    },
                )
            except Exception as error:
                write_json(self, 400, {"ok": False, "error": str(error)})
            return

        if self.path != "/api/run":
            write_json(self, 404, {"ok": False, "error": "Not found"})
            return

        try:
            payload = read_json_body(self)
            config = load_config()
            validate_run_payload(payload, config)
            update_config_from_payload(config, payload)
            save_config(config)

            command, temp_paths = build_command(payload)
            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            for temp_path in temp_paths:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            report_path = extract_report_path(completed.stdout)
            has_failures = report_has_failures(report_path)
            launch_ok = completed.returncode == 0 and has_failures is not True
            write_json(
                self,
                200,
                {
                    "ok": launch_ok,
                    "processOk": completed.returncode == 0,
                    "launchOk": launch_ok,
                    "hasFailures": has_failures,
                    "returnCode": completed.returncode,
                    "command": command,
                    "reportPath": report_path,
                    "reportUrl": report_web_url(report_path),
                    "openSearchUrl": extract_opensearch_url(report_path),
                    "launchUrls": parse_launch_urls(report_path),
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
            )
        except Exception as error:
            write_json(self, 400, {"ok": False, "error": str(error)})


def parse_args():
    parser = argparse.ArgumentParser(description="Start the Game Launch Loop web input UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="Do not open Chrome automatically.")
    return parser.parse_args()


def main():
    args = parse_args()
    url = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), WebInputHandler)
    print(f"Game Launch Loop web UI: {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        open_in_chrome(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
