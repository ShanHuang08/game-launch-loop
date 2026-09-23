#!/usr/bin/env python3
import argparse
import csv
import hashlib
import hmac
import html
import json
import re
import ssl
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CONFIG = "config.json"
COMMON_GAME_CODE_COLUMNS = ("gameCode", "game_code", "GAME_CODE", "code")
REPORT_TIMEZONE = timezone(timedelta(hours=8))
RESULT_ERROR_WRAP_LENGTH = 100
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENSEARCH_PROJECT_CANDIDATES = (
    PROJECT_ROOT.parent / "open-search",
    PROJECT_ROOT.parent / "cli",
)
OPENSEARCH_INDEX_PATTERNS = {
    "qa": "53ceb180-8f5d-11ef-b9c6-73a60e0d81fe",
    "stg": "48481400-8c6a-11ef-b9c6-73a60e0d81fe",
}
CLOUDFLARE_VPN_HINT = (
    "Cloudflare blocked one or more launch game requests. "
    "Please connect to FlyVPN and rerun."
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Loop call GA vendor /game/url and export results to Markdown."
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to config JSON.")
    parser.add_argument(
        "--env",
        help="Environment name. Use comma-separated values for multiple envs, e.g. qa,stg.",
    )
    parser.add_argument(
        "--clear_report",
        action="store_true",
        help="Delete all files under the reports folder, then exit.",
    )
    parser.add_argument(
        "--range",
        dest="game_range",
        help="Game code range, e.g. GALA_8000-GALA_8100.",
    )
    parser.add_argument(
        "--game-code",
        nargs="+",
        help="One or more game codes. Supports comma-separated values.",
    )
    parser.add_argument("--input", help="Input file: csv, tsv, or txt.")
    parser.add_argument(
        "--json",
        dest="json_input",
        help="JSON launch plan with env, shared request fields, and vendor_N agent_id/gameCode/currency entries.",
    )
    parser.add_argument(
        "--agent-id",
        action="append",
        default=[],
        help="Select a credential by agentId, e.g. 1087. Use env=agentId for multi-env runs, e.g. qa=1087.",
    )
    parser.add_argument(
        "--game-code-column",
        help="Column name for CSV/TSV input. Defaults to common names or first column.",
    )
    parser.add_argument(
        "--output",
        help="Markdown output path. Defaults to reports/game-launch-<timestamp>.md.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build requests and report them without calling the API.",
    )
    parser.add_argument(
        "--insecure-skip-tls-verify",
        action="store_true",
        help="Skip TLS certificate verification for test environments with incomplete cert chains.",
    )
    parser.add_argument(
        "--include-agent-id-in-body",
        action="store_true",
        help="Include agentId in the JSON request body. By default agent_id only selects credentials.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open the generated Markdown report in Google Chrome.",
    )
    return parser.parse_args()


def load_config(path):
    config_path = Path(path)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_json_launch_plan(path):
    json_path = Path(path)
    if not json_path.exists():
        raise SystemExit(f"JSON launch plan not found: {json_path}")
    with json_path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise SystemExit("JSON launch plan must be an object.")
    return payload


def parse_game_range(value):
    match = re.fullmatch(r"([A-Za-z0-9]+_)(\d+)-([A-Za-z0-9]+_)?(\d+)", value.strip())
    if not match:
        raise SystemExit(
            "Invalid range format. Expected something like GALA_8000-GALA_8100."
        )

    start_prefix, start_number, end_prefix, end_number = match.groups()
    end_prefix = end_prefix or start_prefix
    if start_prefix != end_prefix:
        raise SystemExit("Range prefix must match, e.g. GALA_8000-GALA_8100.")

    width = len(start_number)
    start = int(start_number)
    end = int(end_number)
    step = 1 if end >= start else -1
    return [f"{start_prefix}{number:0{width}d}" for number in range(start, end + step, step)]


def read_game_codes_from_file(path, column_name=None):
    input_path = Path(path)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    suffix = input_path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        delimiter = "\t" if suffix == ".tsv" else ","
        with input_path.open("r", encoding="utf-8-sig", newline="") as file:
            sample = file.read(4096)
            file.seek(0)
            has_header = csv.Sniffer().has_header(sample)
            if has_header:
                reader = csv.DictReader(file, delimiter=delimiter)
                selected_column = pick_column(reader.fieldnames or [], column_name)
                return clean_codes(row.get(selected_column, "") for row in reader)

            reader = csv.reader(file, delimiter=delimiter)
            return clean_codes(row[0] for row in reader if row)

    with input_path.open("r", encoding="utf-8-sig") as file:
        return clean_codes(line for line in file)


def pick_column(fieldnames, requested):
    if requested:
        if requested not in fieldnames:
            raise SystemExit(
                f"Column '{requested}' not found. Available columns: {', '.join(fieldnames)}"
            )
        return requested

    for candidate in COMMON_GAME_CODE_COLUMNS:
        if candidate in fieldnames:
            return candidate

    if not fieldnames:
        raise SystemExit("CSV/TSV input has no columns.")
    return fieldnames[0]


def clean_codes(values):
    codes = []
    seen = set()
    for value in values:
        code = str(value).strip()
        if not code or code in seen:
            continue
        codes.append(code)
        seen.add(code)
    return codes


def parse_game_code_args(values):
    raw_values = []
    for value in values:
        for part in str(value).split(","):
            item = part.strip()
            if not item:
                continue
            if is_game_range(item):
                raw_values.extend(parse_game_range(item))
            else:
                raw_values.append(item)
    return clean_codes(raw_values)


def is_game_range(value):
    return bool(re.fullmatch(r"[A-Za-z0-9]+_\d+-([A-Za-z0-9]+_)?\d+", value.strip()))


def parse_agent_id_map(values):
    agent_ids = {}
    for value in values:
        if "=" not in value:
            agent_id = str(value).strip()
            if not agent_id:
                raise SystemExit("Invalid --agent-id format. Expected agent_id or env=agent_id.")
            agent_ids["*"] = int(agent_id) if agent_id.isdigit() else agent_id
            continue
        env_name, agent_id = value.split("=", 1)
        env_name = env_name.strip()
        agent_id = agent_id.strip()
        if not env_name or not agent_id:
            raise SystemExit("Invalid --agent-id format. Expected agent_id or env=agent_id.")
        agent_ids[env_name] = int(agent_id) if agent_id.isdigit() else agent_id
    return agent_ids


def resolve_env_name(requested_env, environments):
    if not requested_env:
        raise SystemExit("JSON launch plan must include env.")
    for env_name in environments:
        if str(env_name).lower() == str(requested_env).lower():
            return env_name
    raise SystemExit(f"Missing env config: {requested_env}")


def select_env_config(env_name, env_config, agent_id_map):
    if isinstance(env_config, dict) and "agents" in env_config:
        agents = env_config.get("agents", [])
        selected_agent = select_env_config(env_name, agents, agent_id_map)
        env_defaults = {
            key: value
            for key, value in env_config.items()
            if key != "agents"
        }
        return {**env_defaults, **selected_agent}

    requested_agent_id = agent_id_map.get(env_name, agent_id_map.get("*"))
    if isinstance(env_config, list):
        if requested_agent_id is None:
            return env_config[0]
        for candidate in env_config:
            if str(candidate.get("agent_id")) == str(requested_agent_id):
                return candidate
        raise SystemExit(f"Env '{env_name}' has no credential for agent_id={requested_agent_id}.")

    if requested_agent_id is not None and str(env_config.get("agent_id")) != str(requested_agent_id):
        raise SystemExit(
            f"Env '{env_name}' config agent_id={env_config.get('agent_id')} does not match requested {requested_agent_id}."
        )
    return env_config


def json_plan_request_overrides(plan):
    request_keys = ("username", "language", "platform", "lobbyUrl", "ipAddress")
    return {
        key: plan[key]
        for key in request_keys
        if key in plan and plan[key] is not None
    }


def json_plan_vendor_items(plan):
    items = []
    vendors = plan.get("vendors")
    if isinstance(vendors, list):
        for index, vendor in enumerate(vendors, start=1):
            items.append(normalize_json_vendor_item(f"vendor_{index}", vendor))
    elif isinstance(vendors, dict):
        for vendor_name in sorted(vendors):
            items.append(normalize_json_vendor_item(vendor_name, vendors[vendor_name]))

    for vendor_key, vendor in plan.items():
        if is_top_level_json_vendor(vendor_key, vendor):
            items.append(normalize_json_vendor_item(vendor_key, vendor))

    if not items:
        raise SystemExit("JSON launch plan has no vendor entries.")
    return items


def is_top_level_json_vendor(key, value):
    if key == "vendors" or not isinstance(value, dict):
        return False
    vendor_fields = ("agent_id", "gameCode", "game_code", "currency")
    return any(field in value for field in vendor_fields)


def normalize_json_vendor_item(vendor_name, value):
    if not isinstance(value, dict):
        raise SystemExit(f"{vendor_name} must be an object.")
    game_code = value.get("gameCode") or value.get("game_code")
    currency = value.get("currency")
    agent_id = value.get("agent_id")
    if not game_code:
        raise SystemExit(f"{vendor_name} is missing gameCode.")
    if not currency:
        raise SystemExit(f"{vendor_name} is missing currency.")
    if agent_id is None or agent_id == "":
        raise SystemExit(f"{vendor_name} is missing agent_id.")
    return {
        "vendor": vendor_name,
        "agent_id": agent_id,
        "game_code": str(game_code).strip(),
        "currency": str(currency).strip(),
    }


def first_currency(value, default):
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item or "").strip()]
        return values[0] if values else default
    if value is None or value == "":
        return default
    return value


def build_body(config, env_config, game_code, trace_id, include_agent_id=False):
    request_defaults = config.get("request", {})
    default_currency = first_currency(request_defaults.get("currency"), "BRL")
    currency = first_currency(env_config.get("currency"), default_currency)
    body = {
        "traceId": trace_id,
        "username": request_defaults.get("username", "ga251110"),
        "gameCode": game_code,
        "language": env_config.get("language", request_defaults.get("language", "en")),
        "platform": env_config.get("platform", request_defaults.get("platform", "WEB")),
        "currency": currency,
        "lobbyUrl": env_config.get("lobbyUrl", request_defaults.get("lobbyUrl", "https://www.google.com/")),
        "ipAddress": env_config.get("ipAddress", request_defaults.get("ipAddress", "192.228.180.86")),
    }
    if include_agent_id:
        body["agentId"] = env_config.get("agent_id")
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def generate_signature(raw_body, api_secret):
    digest = hmac.new(
        api_secret.encode("utf-8"),
        raw_body.encode("utf-8"),
        hashlib.sha256,
    )
    return digest.hexdigest()


def post_json_endpoint(
    env_config,
    path,
    raw_body,
    signature,
    timeout,
    insecure_skip_tls_verify=True,
):
    base_url = env_config["ga_vendor_api"].rstrip("/")
    request = Request(
        f"{base_url}{path}",
        data=raw_body.encode("utf-8"),
        headers={
            "x-api-key": env_config["x_api_key"],
            "x-signature": signature,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": env_config.get("user_agent", "PostmanRuntime/7.43.0"),
        },
        method="POST",
    )

    try:
        config_skip_tls = env_config.get("insecure_skip_tls_verify", True)
        context = ssl._create_unverified_context() if insecure_skip_tls_verify or config_skip_tls else None
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 300,
                "http_status": response.status,
                "response_body": body,
                "error": "",
            }
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "http_status": error.code,
            "response_body": body,
            "error": f"HTTPError: {error.reason}",
        }
    except URLError as error:
        message = f"URLError: {error.reason}"
        if "CERTIFICATE_VERIFY_FAILED" in str(error.reason):
            message += " (TLS certificate chain failed)"
        return {
            "ok": False,
            "http_status": "",
            "response_body": "",
            "error": message,
        }
    except TimeoutError:
        return {
            "ok": False,
            "http_status": "",
            "response_body": "",
            "error": "TimeoutError",
        }


def post_game_url(env_config, raw_body, signature, timeout, insecure_skip_tls_verify=True):
    return post_json_endpoint(
        env_config,
        "/game/url",
        raw_body,
        signature,
        timeout,
        insecure_skip_tls_verify,
    )


def post_game_session(env_config, token, timeout, insecure_skip_tls_verify=True):
    raw_body = json.dumps({"token": token}, separators=(",", ":"), ensure_ascii=False)
    signature = generate_signature(raw_body, env_config["x_api_secret"])
    result = post_json_endpoint(
        env_config,
        "/agentPlayer/gameSession",
        raw_body,
        signature,
        timeout,
        insecure_skip_tls_verify,
    )
    result["request_body"] = raw_body
    return result


def parse_response_summary(response_body):
    if not response_body:
        return "", ""

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return trim(response_body, 300), ""

    launch_url = find_first_key(parsed, ("url", "gameUrl", "launchUrl", "gameLaunchUrl"))
    summary_keys = ("code", "message", "msg", "status", "errorCode", "errorMessage")
    summary = {key: parsed.get(key) for key in summary_keys if isinstance(parsed, dict) and key in parsed}
    if summary:
        return json.dumps(summary, ensure_ascii=False), launch_url or ""
    return trim(json.dumps(parsed, ensure_ascii=False), 300), launch_url or ""


def parse_response_error(response_body):
    """Return the most useful API error text for failed launch responses."""
    if not response_body:
        return ""
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""

    for key in ("error", "errorMessage", "exception", "message"):
        value = parsed.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def opensearch_project_dir():
    for candidate in OPENSEARCH_PROJECT_CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def opensearch_python_path(project_dir):
    candidates = [
        project_dir / ".venv" / "bin" / "python",
        project_dir / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def opensearch_error_from_report(report_text):
    """Extract non-empty detail errors from an OpenSearch Markdown report."""
    errors = []
    for match in re.finditer(
        r"^<a id=\"log-\d+\"></a>\n.*?(?=^<a id=\"log-\d+\"></a>|\Z)",
        report_text,
        re.MULTILINE | re.DOTALL,
    ):
        error_match = re.search(r"^- Error: (.+)$", match.group(0), re.MULTILINE)
        if error_match:
            error = error_match.group(1).strip().strip("`")
            if error and error not in errors:
                errors.append(error)
    return "\n".join(errors)


def extract_fenced_section(block, heading):
    match = re.search(
        rf"(?mi)^### {re.escape(heading)}[ \t]*\n(?:[ \t]*\n)*[ \t]*(`{{3,}})(?:[A-Za-z0-9_-]+)?[ \t]*\n(.*?)\n\1[ \t]*$",
        block,
        re.DOTALL,
    )
    return match.group(2).strip() if match else ""


def response_body_launch_url(response_body):
    if not response_body:
        return ""
    raw_response = html.unescape(str(response_body)).strip()
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        parsed = raw_response

    if isinstance(parsed, str):
        candidate = html.unescape(parsed).strip()
        parsed_url = urlparse(candidate)
        if (
            parsed_url.scheme.lower() in {"http", "https"}
            and parsed_url.netloc
            and not any(character.isspace() for character in candidate)
        ):
            return candidate
        return ""

    return find_first_key(parsed, ("launchUrl", "gameUrl", "gameLaunchUrl", "url"))


def opensearch_response_body_from_report(report_text, game_code):
    """Extract the vendor Response Body that contains a playable launch URL."""
    for match in re.finditer(
        r"^<a id=\"log-\d+\"></a>\n.*?(?=^<a id=\"log-\d+\"></a>|\Z)",
        report_text,
        re.MULTILINE | re.DOTALL,
    ):
        block = match.group(0)
        game_code_match = re.search(r"^- Game Code: `([^`]+)`", block, re.MULTILINE)
        report_game_code = game_code_match.group(1) if game_code_match else ""
        if report_game_code not in ("", "N/A", game_code):
            continue
        response_body = extract_fenced_section(block, "Response Body")
        if response_body_launch_url(response_body):
            return response_body
    return ""


def opensearch_report_path_from_stdout(stdout, project_dir):
    report_match = re.search(r"^Markdown[：:]\s*(.+)$", stdout, re.MULTILINE)
    if not report_match:
        return None
    report_path = Path(report_match.group(1).strip())
    if not report_path.is_absolute():
        report_path = project_dir / report_path
    return report_path


def fetch_opensearch_launch_log(env_name, username, game_code, timeout=60):
    """Look up launch log fields without making log lookup fatal."""
    empty = {"error": "", "response_body": ""}
    project_dir = opensearch_project_dir()
    if not project_dir or not username or not game_code:
        return empty

    def quote_keyword(value):
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    cli_environment = "staging" if str(env_name).lower() in {"stg", "staging"} else "QA"
    command = [
        str(opensearch_python_path(project_dir)),
        "-m",
        "cli",
        "--env",
        cli_environment,
        "--keyword",
        f'"{quote_keyword(username)}" and "{quote_keyword(game_code)}"',
        "--max-records",
        "100",
        "--no-open-output",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return empty
    if completed.returncode != 0:
        return empty

    report_path = opensearch_report_path_from_stdout(completed.stdout, project_dir)
    if not report_path:
        return empty
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return empty
    return {
        "error": opensearch_error_from_report(report_text),
        "response_body": opensearch_response_body_from_report(report_text, game_code),
    }


def enrich_opensearch_errors(results, config):
    """Keep launch output fast; OpenSearch lookups are only run by explicit UI actions."""
    return


def parse_response_status(response_body):
    if not response_body:
        return ""
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    status = parsed.get("status")
    return str(status).strip() if status is not None else ""


def parse_response_token(response_body):
    if not response_body:
        return ""
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return ""
    return find_first_key(parsed, ("token",))


def is_cloudflare_block(result):
    if result.get("ok"):
        return False
    if str(result.get("http_status")) == "403":
        return True

    haystack = " ".join(
        str(result.get(key, ""))
        for key in ("http_status", "response_body", "error")
    ).lower()
    cloudflare_markers = (
        "cloudflare",
        "cf-error",
        "cf-ray",
        "error code: 1020",
        "attention required",
        "access denied",
    )
    return any(marker in haystack for marker in cloudflare_markers)


def find_first_key(value, keys):
    if isinstance(value, dict):
        for key in keys:
            if key in value and isinstance(value[key], str):
                return value[key]
        for nested in value.values():
            found = find_first_key(nested, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_first_key(item, keys)
            if found:
                return found
    return ""


def trim(value, max_length):
    text = str(value).replace("\n", " ")
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def markdown_escape(value):
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def markdown_result_error(value):
    """Escape and wrap long errors so the Results table stays readable."""
    text = str(value or "")
    return "<br>".join(
        markdown_escape(text[index : index + RESULT_ERROR_WRAP_LENGTH])
        for index in range(0, len(text), RESULT_ERROR_WRAP_LENGTH)
    )


def markdown_line(value):
    return f"{value}  "


def markdown_launch_link(value):
    if not value:
        return ""
    escaped_url = html.escape(str(value), quote=True)
    return f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">Open Game</a>'


def markdown_opensearch_link(env_name, query_value):
    index_pattern = OPENSEARCH_INDEX_PATTERNS.get(str(env_name).lower())
    if not index_pattern or not query_value:
        return ""
    encoded_query = quote(f'"{query_value}"', safe="")
    url = (
        "https://opensearch-dashboard-dev.newnextgen.site/app/data-explorer/discover"
        "#?_a=(discover:(columns:!(requestBody,responseBody,url,operatorData,operatorResponse,operatorUrl,error,timeTaken),"
        f"isDirty:!f,sort:!()),metadata:(indexPattern:'{index_pattern}',view:discover))"
        "&_g=(filters:!(),refreshInterval:(pause:!t,value:0),time:(from:now-1w,to:now))"
        f"&_q=(filters:!(),query:(language:kuery,query:{encoded_query}))"
    )
    escaped_url = html.escape(url, quote=True)
    return f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">OpenSearch Log</a>'


def detail_anchor(result):
    game_code = str(result["game_code"]).strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", game_code)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{result['index']}-{slug}"


def markdown_game_code_link(result):
    label = markdown_escape(result["game_code"])
    return f"[{label}](#{detail_anchor(result)})"


def agent_name(env_config):
    return env_config.get("agent_name") or env_config.get("name") or ""


def agent_label(agent_id, name):
    if name:
        return f"{agent_id} - {name}"
    return str(agent_id)


def is_launch_success(result, launch_url, token):
    return bool(result["ok"] and launch_url and token)


def has_cloudflare_block(results):
    return any(result.get("cloudflare_blocked") for result in results)


def build_cloudflare_skipped_result(
    env_name,
    env_config,
    index,
    game_code,
    currency=None,
    vendor=None,
):
    result = {
        "env": env_name,
        "agent_id": env_config.get("agent_id", ""),
        "agent_name": agent_name(env_config),
        "index": index,
        "game_code": game_code,
        "username": "",
        "currency": currency if currency is not None else env_config.get("currency", ""),
        "trace_id": "",
        "http_status": "SKIPPED",
        "success": "SKIPPED",
        "summary": "",
        "launch_url": "",
        "error": CLOUDFLARE_VPN_HINT,
        "cloudflare_blocked": False,
        "request_body": "",
        "response_body": "",
        "backup_response_body": "",
        "game_session_http_status": "SKIPPED",
        "game_session_success": "SKIPPED",
        "game_session_error": CLOUDFLARE_VPN_HINT,
        "game_session_request_body": "",
        "game_session_response_body": "",
    }
    if vendor is not None:
        result["vendor"] = vendor
    return result


def append_skipped_game_codes(results, env_name, env_config, game_codes, start_index=1):
    total = start_index + len(game_codes) - 1
    for index, game_code in enumerate(game_codes, start=start_index):
        results.append(
            build_cloudflare_skipped_result(env_name, env_config, index, game_code)
        )
        print(
            f"[{env_name}] {index}/{total} {game_code} "
            "status=SKIPPED success=SKIPPED"
        )


def delay_seconds(config):
    return config.get("delay_ms", 5000) / 1000


def sleep_after_launch(config, should_sleep=True):
    seconds = delay_seconds(config)
    if should_sleep and seconds:
        time.sleep(seconds)


def run(
    env_name,
    env_config,
    config,
    game_codes,
    dry_run,
    insecure_skip_tls_verify=True,
    include_agent_id_in_body=False,
):
    results = []
    timeout = config.get("timeout_seconds", 30)

    for index, game_code in enumerate(game_codes, start=1):
        trace_id = str(uuid.uuid4())
        raw_body = build_body(
            config,
            env_config,
            game_code,
            trace_id,
            include_agent_id_in_body,
        )
        signature = generate_signature(raw_body, env_config["x_api_secret"])

        if dry_run:
            result = {
                "ok": True,
                "http_status": "DRY_RUN",
                "response_body": "",
                "error": "",
            }
        else:
            skip_tls_verify = (
                insecure_skip_tls_verify
                or config.get("insecure_skip_tls_verify", True)
                or env_config.get("insecure_skip_tls_verify", True)
            )
            result = post_game_url(
                env_config,
                raw_body,
                signature,
                timeout,
                skip_tls_verify,
            )

        summary, launch_url = parse_response_summary(result["response_body"])
        response_error = parse_response_error(result["response_body"])
        response_status = parse_response_status(result["response_body"])
        token = parse_response_token(result["response_body"])
        launch_success = is_launch_success(result, launch_url, token)
        cloudflare_blocked = is_cloudflare_block(result)
        if dry_run:
            game_session_result = {
                "http_status": "DRY_RUN",
                "success": "YES",
                "request_body": "",
                "response_body": "",
                "error": "",
            }
        elif launch_success:
            game_session_result = post_game_session(
                env_config,
                token,
                timeout,
                skip_tls_verify,
            )
            game_session_result["success"] = "YES" if game_session_result["ok"] else "NO"
        else:
            missing = []
            if not launch_url:
                missing.append("gameUrl")
            if not token:
                missing.append("token")
            game_session_result = {
                "http_status": "",
                "success": "NO",
                "request_body": "",
                "response_body": "",
                "error": f"Missing {' and '.join(missing)} from /game/url response",
            }

        results.append(
            {
                "env": env_name,
                "agent_id": env_config.get("agent_id", ""),
                "agent_name": agent_name(env_config),
                "index": index,
                "game_code": game_code,
                "username": json.loads(raw_body).get("username", ""),
                "currency": json.loads(raw_body).get("currency", ""),
                "trace_id": trace_id,
                "http_status": result["http_status"],
                "success": "YES" if dry_run or launch_success else "NO",
                "summary": summary,
                "launch_url": launch_url,
                "error": result["error"] or (response_error if not launch_success else ""),
                "cloudflare_blocked": cloudflare_blocked,
                "request_body": raw_body,
                "response_body": result["response_body"],
                "backup_response_body": "",
                "game_session_http_status": game_session_result["http_status"],
                "game_session_success": game_session_result["success"],
                "game_session_error": game_session_result["error"],
                "game_session_request_body": game_session_result["request_body"],
                "game_session_response_body": game_session_result["response_body"],
            }
        )

        response_log = f" response={response_status}" if response_status else ""
        print(
            f"[{env_name}] {index}/{len(game_codes)} {game_code} "
            f"status={result['http_status']} success={results[-1]['success']}"
            f"{response_log}"
        )

        if cloudflare_blocked:
            print(CLOUDFLARE_VPN_HINT)
            for skipped_index, skipped_game_code in enumerate(
                game_codes[index:],
                start=index + 1,
            ):
                results.append(
                    build_cloudflare_skipped_result(
                        env_name,
                        env_config,
                        skipped_index,
                        skipped_game_code,
                    )
                )
                print(
                    f"[{env_name}] {skipped_index}/{len(game_codes)} {skipped_game_code} "
                    "status=SKIPPED success=SKIPPED"
                )
            break

        sleep_after_launch(config, index < len(game_codes))

    return results


def run_json_launch_items(
    env_name,
    raw_env_config,
    config,
    items,
    dry_run,
    insecure_skip_tls_verify=True,
    include_agent_id_in_body=False,
):
    results = []
    timeout = config.get("timeout_seconds", 30)

    for index, item in enumerate(items, start=1):
        game_code = item["game_code"]
        selected_env_config = select_env_config(
            env_name,
            raw_env_config,
            {env_name: item["agent_id"]},
        )
        item_env_config = {**selected_env_config, "currency": item["currency"]}
        trace_id = str(uuid.uuid4())
        raw_body = build_body(
            config,
            item_env_config,
            game_code,
            trace_id,
            include_agent_id_in_body,
        )
        signature = generate_signature(raw_body, item_env_config["x_api_secret"])

        if dry_run:
            result = {
                "ok": True,
                "http_status": "DRY_RUN",
                "response_body": "",
                "error": "",
            }
            skip_tls_verify = True
        else:
            skip_tls_verify = (
                insecure_skip_tls_verify
                or config.get("insecure_skip_tls_verify", True)
                or item_env_config.get("insecure_skip_tls_verify", True)
            )
            result = post_game_url(
                item_env_config,
                raw_body,
                signature,
                timeout,
                skip_tls_verify,
            )

        summary, launch_url = parse_response_summary(result["response_body"])
        response_error = parse_response_error(result["response_body"])
        response_status = parse_response_status(result["response_body"])
        token = parse_response_token(result["response_body"])
        launch_success = is_launch_success(result, launch_url, token)
        cloudflare_blocked = is_cloudflare_block(result)
        if dry_run:
            game_session_result = {
                "http_status": "DRY_RUN",
                "success": "YES",
                "request_body": "",
                "response_body": "",
                "error": "",
            }
        elif launch_success:
            game_session_result = post_game_session(
                item_env_config,
                token,
                timeout,
                skip_tls_verify,
            )
            game_session_result["success"] = "YES" if game_session_result["ok"] else "NO"
        else:
            missing = []
            if not launch_url:
                missing.append("gameUrl")
            if not token:
                missing.append("token")
            game_session_result = {
                "http_status": "",
                "success": "NO",
                "request_body": "",
                "response_body": "",
                "error": f"Missing {' and '.join(missing)} from /game/url response",
            }

        results.append(
            {
                "env": env_name,
                "agent_id": item_env_config.get("agent_id", ""),
                "agent_name": agent_name(item_env_config),
                "index": index,
                "vendor": item["vendor"],
                "game_code": game_code,
                "username": json.loads(raw_body).get("username", ""),
                "currency": item["currency"],
                "trace_id": trace_id,
                "http_status": result["http_status"],
                "success": "YES" if dry_run or launch_success else "NO",
                "summary": summary,
                "launch_url": launch_url,
                "error": result["error"] or (response_error if not launch_success else ""),
                "cloudflare_blocked": cloudflare_blocked,
                "request_body": raw_body,
                "response_body": result["response_body"],
                "backup_response_body": "",
                "game_session_http_status": game_session_result["http_status"],
                "game_session_success": game_session_result["success"],
                "game_session_error": game_session_result["error"],
                "game_session_request_body": game_session_result["request_body"],
                "game_session_response_body": game_session_result["response_body"],
            }
        )

        response_log = f" response={response_status}" if response_status else ""
        print(
            f"[{env_name}] {index}/{len(items)} {item['vendor']} {game_code} "
            f"currency={item['currency']} status={result['http_status']} "
            f"success={results[-1]['success']}"
            f"{response_log}"
        )

        if cloudflare_blocked:
            print(CLOUDFLARE_VPN_HINT)
            for skipped_index, skipped_item in enumerate(
                items[index:],
                start=index + 1,
            ):
                skipped_env_config = select_env_config(
                    env_name,
                    raw_env_config,
                    {env_name: skipped_item["agent_id"]},
                )
                results.append(
                    build_cloudflare_skipped_result(
                        env_name,
                        skipped_env_config,
                        skipped_index,
                        skipped_item["game_code"],
                        currency=skipped_item["currency"],
                        vendor=skipped_item["vendor"],
                    )
                )
                print(
                    f"[{env_name}] {skipped_index}/{len(items)} "
                    f"{skipped_item['vendor']} {skipped_item['game_code']} "
                    f"currency={skipped_item['currency']} "
                    "status=SKIPPED success=SKIPPED"
                )
            break

        sleep_after_launch(config, index < len(items))

    return results


def write_markdown(path, config_path, env_names, game_codes, results, dry_run):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S UTC+8")
    success_count = sum(1 for result in results if result["success"] == "YES")
    skipped_count = sum(1 for result in results if result["success"] == "SKIPPED")
    request_count = len(results) - skipped_count
    failed_count = request_count - success_count
    has_vendor = any(result.get("vendor") for result in results)
    cloudflare_blocked = has_cloudflare_block(results)

    lines = [
        "# Game Launch Loop Report",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Config: `{config_path}`",
        f"- Environments: `{', '.join(env_names)}`",
        f"- Game codes: `{len(game_codes)}`",
        f"- Requests: `{request_count}`",
        f"- Success: `{success_count}`",
        f"- Failed: `{failed_count}`",
        f"- Skipped: `{skipped_count}`",
        f"- Dry run: `{'YES' if dry_run else 'NO'}`",
        "",
    ]
    if cloudflare_blocked:
        lines.extend([f"> {CLOUDFLARE_VPN_HINT}", ""])
    lines.extend(["## Results", ""])
    if has_vendor:
        lines.extend(
            [
                "| # | Env | Agent | Vendor | Game Code | Currency | HTTP | Success | Launch URL | Summary | Error |",
                "|---:|---|---:|---|---|---|---:|---|---|---|---|",
            ]
        )
    else:
        lines.extend(
            [
                "| # | Env | Agent | Game Code | Currency | HTTP | Success | Launch URL | Summary | Error |",
                "|---:|---|---:|---|---|---:|---|---|---|---|",
            ]
        )

    for result in results:
        if has_vendor:
            lines.append(
                "| {index} | {env} | {agent_id} | {vendor} | {game_code} | {currency} | {http_status} | {success} | {launch_url} | {summary} | {error} |".format(
                    index=result["index"],
                    env=markdown_escape(result["env"]),
                    agent_id=markdown_escape(agent_label(result["agent_id"], result["agent_name"])),
                    vendor=markdown_escape(result.get("vendor", "")),
                    game_code=markdown_game_code_link(result),
                    currency=markdown_escape(result.get("currency", "")),
                    http_status=markdown_escape(result["http_status"]),
                    success=markdown_escape(result["success"]),
                    launch_url=markdown_launch_link(result["launch_url"]),
                    summary=markdown_escape(result["summary"]),
                    error=markdown_result_error(result["error"]),
                )
            )
        else:
            lines.append(
                "| {index} | {env} | {agent_id} | {game_code} | {currency} | {http_status} | {success} | {launch_url} | {summary} | {error} |".format(
                    index=result["index"],
                    env=markdown_escape(result["env"]),
                    agent_id=markdown_escape(agent_label(result["agent_id"], result["agent_name"])),
                    game_code=markdown_game_code_link(result),
                    currency=markdown_escape(result.get("currency", "")),
                    http_status=markdown_escape(result["http_status"]),
                    success=markdown_escape(result["success"]),
                    launch_url=markdown_launch_link(result["launch_url"]),
                    summary=markdown_escape(result["summary"]),
                    error=markdown_result_error(result["error"]),
                )
            )

    lines.extend(["", "## Details", ""])

    for result in results:
        lines.extend(
            [
                f'<a id="{detail_anchor(result)}"></a>',
                f"### {result['index']}. {result['game_code']}",
                "",
                markdown_line(f"Vendor = {result.get('vendor', '-')}") if has_vendor else "",
                markdown_line(f"GameCode = {result['game_code']}"),
                markdown_line(f"Currency = {result.get('currency', '-')}"),
                markdown_line(f"{result['env']} agentId = {result['agent_id']}"),
                markdown_line(f"{result['env']} agentName = {result['agent_name'] or '-'}"),
                markdown_line(f"HTTP: {result['http_status']}"),
                markdown_line(f"Success: {result['success']}"),
            ]
        )
        if result["summary"]:
            lines.append(markdown_line(f"Summary: {result['summary']}"))
        if result["error"]:
            lines.append(markdown_line(f"Error: {result['error']}"))
        log_link = markdown_opensearch_link(result["env"], result["username"])
        if log_link:
            lines.append(markdown_line(log_link))
        lines.extend(
            [
                "",
                "Request Body",
                "",
                "```json",
                pretty_json(result["request_body"]),
                "```",
                "",
                "operator Response",
                "",
                "```json",
                pretty_json(result["response_body"]),
                "```",
                "",
                "responseBody",
                "",
                "```json",
                pretty_json(result.get("backup_response_body", "")),
                "```",
                "",
                "/agentPlayer/gameSession Request Body",
                "",
                "```json",
                pretty_json(result["game_session_request_body"]),
                "```",
                "",
                "/agentPlayer/gameSession Response",
                "",
                f"HTTP: {result['game_session_http_status']}",
                f"Success: {result['game_session_success']}",
            ]
        )
        if result["game_session_error"]:
            lines.append(f"Error: {result['game_session_error']}")
        lines.extend(
            [
                "",
                "```json",
                pretty_json(result["game_session_response_body"]),
                "```",
                "",
            ]
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def pretty_json(value):
    if not value:
        return ""
    try:
        return json.dumps(json.loads(value), indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return value


def default_output_path():
    return timestamped_output_path("reports/game-launch.md")


def timestamped_output_path(path):
    timestamp = datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d_%H-%M-%S")
    output_path = Path(path)
    suffix = output_path.suffix or ".md"
    stem = output_path.stem if output_path.suffix else output_path.name
    return output_path.with_name(f"{stem}-{timestamp}{suffix}")


def open_markdown_in_chrome(path):
    try:
        subprocess.run(
            ["open", "-a", "Google Chrome", str(Path(path).resolve())],
            check=False,
        )
    except OSError as error:
        print(f"Could not open Markdown in Google Chrome: {error}", file=sys.stderr)


def clear_reports(report_dir="reports"):
    root = Path(report_dir)
    if not root.exists():
        print(f"Reports folder not found: {root}")
        return 0
    if not root.is_dir():
        raise SystemExit(f"Reports path is not a folder: {root}")

    removed = 0
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed += 1
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    print(f"Cleared {removed} file(s) from {root}")
    return removed


def main():
    args = parse_args()
    if args.clear_report:
        clear_reports()
        return

    config = load_config(args.config)

    input_modes = [
        bool(args.game_range),
        bool(args.game_code),
        bool(args.input),
        bool(args.json_input),
    ]
    if sum(input_modes) != 1:
        raise SystemExit("Provide exactly one of --range, --game-code, --input, or --json.")

    environments = config.get("environments", {})

    if args.json_input:
        plan = load_json_launch_plan(args.json_input)
        env_name = resolve_env_name(plan.get("env"), environments)
        request_config = {
            **config.get("request", {}),
            **json_plan_request_overrides(plan),
        }
        json_config = {**config, "request": request_config}
        items = json_plan_vendor_items(plan)
        all_results = run_json_launch_items(
            env_name,
            environments[env_name],
            json_config,
            items,
            args.dry_run,
            args.insecure_skip_tls_verify,
            args.include_agent_id_in_body,
        )
        enrich_opensearch_errors(all_results, json_config)
        output_path = write_markdown(
            timestamped_output_path(args.output) if args.output else default_output_path(),
            args.json_input,
            [env_name],
            [item["game_code"] for item in items],
            all_results,
            args.dry_run,
        )
        print(f"Markdown report written: {output_path}")
        if not args.no_open:
            open_markdown_in_chrome(output_path)
        return

    if not args.env:
        raise SystemExit("Provide --env, or use --json or --clear_report.")

    env_names = [env.strip() for env in args.env.split(",") if env.strip()]
    agent_id_map = parse_agent_id_map(args.agent_id)
    missing_envs = [env for env in env_names if env not in environments]
    if missing_envs:
        raise SystemExit(f"Missing env config: {', '.join(missing_envs)}")

    if args.game_range:
        game_codes = parse_game_range(args.game_range)
    elif args.game_code:
        game_codes = parse_game_code_args(args.game_code)
    else:
        game_codes = read_game_codes_from_file(args.input, args.game_code_column)
    if not game_codes:
        raise SystemExit("No game codes found.")

    all_results = []
    for env_name in env_names:
        env_config = select_env_config(env_name, environments[env_name], agent_id_map)
        if has_cloudflare_block(all_results):
            append_skipped_game_codes(
                all_results,
                env_name,
                env_config,
                game_codes,
            )
            continue

        sleep_after_launch(config, bool(all_results))
        env_results = run(
            env_name,
            env_config,
            config,
            game_codes,
            args.dry_run,
            args.insecure_skip_tls_verify,
            args.include_agent_id_in_body,
        )
        all_results.extend(env_results)

    enrich_opensearch_errors(all_results, config)
    output_path = write_markdown(
        timestamped_output_path(args.output) if args.output else default_output_path(),
        args.config,
        env_names,
        game_codes,
        all_results,
        args.dry_run,
    )
    print(f"Markdown report written: {output_path}")
    if not args.no_open:
        open_markdown_in_chrome(output_path)


if __name__ == "__main__":
    main()
