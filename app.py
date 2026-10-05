import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "public"
MAX_REQUEST_BYTES = 32_768
PRIORITIES = {"Highest", "High", "Medium", "Low", "Lowest"}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
FIELD_LIMITS = {
    "applicationName": 120,
    "summary": 255,
    "businessImpact": 5_000,
    "description": 10_000,
}
PRIORITY_NAMES = {
    "Highest": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Lowest": 4,
}
REQUEST_TIMEOUT_SECONDS = 15
DEMO_STORAGE_PATH = ROOT / "data" / "demo_work_packages.json"
DEMO_STORAGE_LOCK = threading.Lock()


def _load_local_environment():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return

    for line_number, line in enumerate(env_file.read_text(encoding="utf-8").splitlines(), 1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if "=" not in entry:
            raise ValueError(f"Invalid .env entry on line {line_number}; expected KEY=VALUE.")
        name, value = entry.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name or not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid environment variable name on line {line_number}.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


class OpenProjectConfigurationError(Exception):
    pass


class OpenProjectApiError(Exception):
    pass


class DemoStorageError(Exception):
    pass


def _demo_mode_enabled():
    configured = all(
        os.environ.get(name, "").strip()
        for name in (
            "OPENPROJECT_URL",
            "OPENPROJECT_API_KEY",
            "OPENPROJECT_PROJECT_ID",
            "OPENPROJECT_TYPE_ID",
        )
    )
    mode = os.environ.get("OPENPROJECT_DEMO_MODE")
    if mode is None or not mode.strip():
        return not configured
    return mode.strip().casefold() == "true"


def create_demo_work_package(issue):
    with DEMO_STORAGE_LOCK:
        if os.environ.get("VERCEL") == "1":
            return {
                "id": f"DEMO-{secrets.token_hex(4).upper()}",
                "subject": issue["summary"],
                "priority": issue["priority"],
                "applicationName": issue["applicationName"],
                "businessImpact": issue["businessImpact"],
                "description": issue["description"],
                "demo": True,
                "persistent": False,
            }

        try:
            if DEMO_STORAGE_PATH.exists():
                stored = json.loads(DEMO_STORAGE_PATH.read_text(encoding="utf-8"))
                if not isinstance(stored, list):
                    raise DemoStorageError("The local demo issue file has an invalid format.")
            else:
                stored = []

            work_package = {
                "id": f"DEMO-{len(stored) + 1:03d}",
                "subject": issue["summary"],
                "priority": issue["priority"],
                "applicationName": issue["applicationName"],
                "businessImpact": issue["businessImpact"],
                "description": issue["description"],
                "demo": True,
                "persistent": True,
            }
            stored.append(work_package)
            DEMO_STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = DEMO_STORAGE_PATH.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(stored, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(DEMO_STORAGE_PATH)
            return work_package
        except DemoStorageError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DemoStorageError(
                "Could not save the local demo issue. Check the app folder's write permissions."
            ) from error


def _openproject_settings():
    base_url = os.environ.get("OPENPROJECT_URL", "").strip().rstrip("/")
    api_key = os.environ.get("OPENPROJECT_API_KEY", "").strip()
    project_id = os.environ.get("OPENPROJECT_PROJECT_ID", "").strip()
    type_id = os.environ.get("OPENPROJECT_TYPE_ID", "").strip()

    if not all((base_url, api_key, project_id, type_id)):
        raise OpenProjectConfigurationError(
            "OpenProject is not configured. Set OPENPROJECT_URL, "
            "OPENPROJECT_API_KEY, OPENPROJECT_PROJECT_ID, and OPENPROJECT_TYPE_ID."
        )

    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise OpenProjectConfigurationError(
            "OPENPROJECT_URL must be an absolute http:// or https:// URL."
        )
    if parsed_url.username or parsed_url.password:
        raise OpenProjectConfigurationError(
            "Do not put credentials in OPENPROJECT_URL; use OPENPROJECT_API_KEY."
        )
    if not project_id.isdigit() or not type_id.isdigit():
        raise OpenProjectConfigurationError(
            "OPENPROJECT_PROJECT_ID and OPENPROJECT_TYPE_ID must be numeric IDs."
        )

    return base_url, api_key, project_id, type_id


def _api_request(base_url, api_key, path, method="GET", payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url}/api/v3/{path}",
        data=body,
        method=method,
        headers={
            "Accept": "application/hal+json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/hal+json",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_body = response.read()
            if not response_body:
                return {}
            result = json.loads(response_body)
            if not isinstance(result, dict):
                raise OpenProjectApiError("OpenProject returned an invalid API response.")
            return result
    except HTTPError as error:
        if error.code in {401, 403}:
            raise OpenProjectApiError(
                "OpenProject rejected the API key or it lacks permission to create work packages."
            ) from error
        if error.code == 422:
            try:
                details = json.loads(error.read()).get("message")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                details = None
            message = f"OpenProject rejected the work package: {details}" if details else (
                "OpenProject rejected the work package. Check the project, type, "
                "priority, and required fields."
            )
            raise OpenProjectApiError(message) from error
        raise OpenProjectApiError(
            f"OpenProject returned HTTP {error.code} while processing the request."
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise OpenProjectApiError(
            "Could not connect to OpenProject. Check OPENPROJECT_URL and network access."
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OpenProjectApiError("OpenProject returned an invalid API response.") from error


def _resolve_priority_id(priorities, selected_priority):
    elements = priorities.get("_embedded", {}).get("elements", [])
    if not isinstance(elements, list):
        raise OpenProjectApiError("OpenProject returned an invalid priorities collection.")

    active_priorities = [
        priority for priority in elements
        if isinstance(priority, dict)
        and isinstance(priority.get("id"), int)
        and isinstance(priority.get("position"), int)
        and priority.get("isActive", True)
    ]
    active_priorities.sort(key=lambda priority: priority["position"])
    if not active_priorities:
        raise OpenProjectApiError("OpenProject has no active priorities available.")

    rank = PRIORITY_NAMES[selected_priority]
    last_index = len(active_priorities) - 1
    index = (rank * last_index + 2) // 4
    return active_priorities[index]["id"]


def create_work_package(issue):
    base_url, api_key, project_id, type_id = _openproject_settings()
    priorities = _api_request(base_url, api_key, "priorities")
    priority_id = _resolve_priority_id(priorities, issue["priority"])

    description = (
        f"Application: {issue['applicationName']}\n\n"
        f"Business impact:\n{issue['businessImpact']}\n\n"
        f"Description:\n{issue['description']}"
    )
    payload = {
        "subject": issue["summary"],
        "description": {"format": "markdown", "raw": description},
        "_links": {
            "project": {"href": f"/api/v3/projects/{quote(project_id, safe='')}"},
            "type": {"href": f"/api/v3/types/{quote(type_id, safe='')}"},
            "priority": {"href": f"/api/v3/priorities/{priority_id}"},
        },
    }
    created = _api_request(
        base_url, api_key, "work_packages", method="POST", payload=payload
    )
    return {
        "id": created.get("id"),
        "subject": created.get("subject", issue["summary"]),
        "url": created.get("_links", {}).get("self", {}).get("href"),
    }


class JiraAutomationHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            if _demo_mode_enabled():
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "demoMode": True,
                        "openProjectConfigured": False,
                    },
                )
                return
            try:
                _openproject_settings()
                configured = True
            except OpenProjectConfigurationError:
                configured = False
            self._send_json(
                200,
                {
                    "status": "ok",
                    "demoMode": False,
                    "openProjectConfigured": configured,
                },
            )
            return

        static_file = STATIC_FILES.get(path)
        if static_file is None:
            self._send_json(404, {"error": "Not found"})
            return

        filename, content_type = static_file
        try:
            content = (STATIC_ROOT / filename).read_bytes()
        except OSError:
            self._send_json(500, {"error": "Unable to load the application"})
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if urlparse(self.path).path != "/api/issues":
            self._send_json(404, {"error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_json(400, {"error": "A valid Content-Length header is required"})
            return

        if content_length < 1:
            self._send_json(400, {"error": "Request body is required"})
            return
        if content_length > MAX_REQUEST_BYTES:
            self._send_json(413, {"error": "Request body is too large"})
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON"})
            return

        errors = self._validate_issue(payload)
        if errors:
            self._send_json(400, {"error": "Please correct the highlighted fields", "fields": errors})
            return

        if _demo_mode_enabled():
            try:
                work_package = create_demo_work_package(payload)
            except DemoStorageError as error:
                self._send_json(500, {"error": str(error)})
                return
        else:
            try:
                work_package = create_work_package(payload)
            except OpenProjectConfigurationError as error:
                self._send_json(503, {"error": str(error)})
                return
            except OpenProjectApiError as error:
                self._send_json(502, {"error": str(error)})
                return

        self._send_json(201, work_package)

    def _validate_issue(self, payload):
        if not isinstance(payload, dict):
            return {"form": "Request body must be a JSON object"}

        errors = {}
        for field, limit in FIELD_LIMITS.items():
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                errors[field] = "This field is required"
            elif len(value.strip()) > limit:
                errors[field] = f"Must be {limit} characters or fewer"

        priority = payload.get("priority")
        if not isinstance(priority, str) or priority not in PRIORITIES:
            errors["priority"] = "Choose a valid priority"

        return errors

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        print(f"{self.client_address[0]} - {format_string % args}")


if __name__ == "__main__":
    _load_local_environment()
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), JiraAutomationHandler)
    print(f"OpenProject issue intake listening at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.server_close()
