from __future__ import annotations

import atexit
import json
import logging
import re
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

import vmr

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only
    winreg = None


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
PRESETS_PATH = BASE_DIR / "presets.json"
STATIC_DIR = BASE_DIR / "static"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8787
DEFAULT_LAYOUT_MODE = "duo"
ALLOWED_LAYOUT_MODES = {"stack", "duo", "mosaic"}
ALLOWED_SIZE_MODES = {"normal", "wide"}
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{6})$")
STARTUP_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_ENTRY_NAME = "VoicemeeterPotatoRemote"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger("voicemeeter-remote")


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_app_config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "app_title": "Voicemeeter Potato Remote",
        "expected_voicemeeter_type": 3,
    }

    try:
        loaded = load_json_file(CONFIG_PATH)
    except Exception as error:
        LOGGER.warning("Could not load config.json: %s", error)
        return config

    if not isinstance(loaded, dict):
        LOGGER.warning("config.json must contain a JSON object. Using defaults.")
        return config

    config.update(loaded)
    try:
        config["port"] = int(config.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        config["port"] = DEFAULT_PORT
    config["host"] = str(config.get("host", DEFAULT_HOST)).strip() or DEFAULT_HOST
    config["app_title"] = str(config.get("app_title", "Voicemeeter Potato Remote"))
    return config


def json_error(message: str, status_code: int, **extra: object):
    payload = {"ok": False, "success": False, "message": message}
    payload.update(extra)
    return jsonify(payload), status_code


def load_presets_document() -> dict[str, Any]:
    document = load_json_file(PRESETS_PATH)
    if not isinstance(document, dict):
        raise ValueError("presets.json must contain a JSON object.")
    return document


def write_presets_document(document: dict[str, Any]) -> None:
    temp_path = PRESETS_PATH.with_suffix(f"{PRESETS_PATH.suffix}.tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temp_path.replace(PRESETS_PATH)


def get_ui_settings(document: dict[str, Any]) -> dict[str, Any]:
    ui = document.get("_ui", {})
    if not isinstance(ui, dict):
        ui = {}

    layout_mode = str(ui.get("layout_mode", DEFAULT_LAYOUT_MODE)).strip().lower()
    if layout_mode not in ALLOWED_LAYOUT_MODES:
        layout_mode = DEFAULT_LAYOUT_MODE

    return {"layout_mode": layout_mode}


def sanitize_preset_update(raw_item: Any) -> dict[str, Any]:
    if not isinstance(raw_item, dict):
        raise ValueError("Each preset update must be an object.")

    name = str(raw_item.get("name", "")).strip()
    if not name or name.startswith("_"):
        raise ValueError("Each preset update needs a valid preset name.")

    label = str(raw_item.get("label", "")).strip()
    description = str(raw_item.get("description", "")).strip()
    color = str(raw_item.get("color", "")).strip()
    if color and not HEX_COLOR_PATTERN.fullmatch(color):
        raise ValueError(f"Invalid color value for preset '{name}'.")

    try:
        order = int(raw_item.get("order", 9999))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid order value for preset '{name}'.") from error

    size = str(raw_item.get("size", "normal")).strip().lower()
    if size not in ALLOWED_SIZE_MODES:
        size = "normal"

    return {
        "name": name,
        "label": label,
        "description": description,
        "color": color,
        "order": order,
        "size": size,
    }


def get_autostart_status() -> dict[str, Any]:
    if winreg is None:
        return {
            "supported": False,
            "enabled": False,
            "name": STARTUP_ENTRY_NAME,
            "method": "windows_run_key",
            "message": "Windows startup status is only available on Windows.",
        }

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_ENTRY_NAME)
    except FileNotFoundError:
        return {
            "supported": True,
            "enabled": False,
            "name": STARTUP_ENTRY_NAME,
            "method": "windows_run_key",
            "message": "Autostart is off.",
            "command": None,
        }
    except OSError as error:
        return {
            "supported": True,
            "enabled": False,
            "name": STARTUP_ENTRY_NAME,
            "method": "windows_run_key",
            "message": f"Autostart status could not be read: {error}",
            "command": None,
            "error": str(error),
        }

    return {
        "supported": True,
        "enabled": True,
        "name": STARTUP_ENTRY_NAME,
        "method": "windows_run_key",
        "message": "Autostart is on.",
        "command": str(value).strip(),
    }


app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
remote = vmr.VoicemeeterRemote(config_path=CONFIG_PATH, presets_path=PRESETS_PATH)
atexit.register(remote.logout)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def api_health():
    runtime_config = load_app_config()
    try:
        health = remote.health_check()
    except vmr.VoicemeeterError as error:
        return json_error(
            str(error),
            500,
            server={
                "host": runtime_config.get("host", DEFAULT_HOST),
                "port": int(runtime_config.get("port", DEFAULT_PORT)),
                "running": True,
            },
            voicemeeter={
                "dll_found": False,
                "dll_path": None,
                "login_ok": False,
                "running": False,
                "type_name": None,
                "message": str(error),
            },
        )
    payload = {
        "ok": bool(
            health.get("ok")
            or (
                health.get("dll_found")
                and health.get("login_ok")
                and health.get("voicemeeter_running")
            )
        ),
        "success": True,
        "server_running": True,
        "dll_found": health.get("dll_found", False),
        "dll_path": health.get("dll_path"),
        "login_ok": health.get("login_ok", False),
        "voicemeeter_running": health.get("voicemeeter_running", False),
        "voicemeeter_type": health.get("voicemeeter_type"),
        "message": health.get("message", ""),
        "server": {
            "host": runtime_config.get("host", DEFAULT_HOST),
            "port": int(runtime_config.get("port", DEFAULT_PORT)),
            "running": True,
        },
        "voicemeeter": {
            "dll_found": health.get("dll_found", False),
            "dll_path": health.get("dll_path"),
            "login_ok": health.get("login_ok", False),
            "running": health.get("voicemeeter_running", False),
            "type_name": health.get("voicemeeter_type"),
            "message": health.get("message", ""),
        },
    }
    return jsonify(payload)


@app.get("/api/config")
def api_config():
    return jsonify({"ok": True, "success": True, "config": load_app_config()})


@app.get("/api/autostart")
def api_autostart():
    return jsonify({"ok": True, "success": True, "autostart": get_autostart_status()})


@app.get("/api/presets")
def api_presets():
    try:
        document = load_presets_document()
        presets = remote.get_presets_summary()
    except vmr.VoicemeeterError as error:
        return json_error(str(error), 500)
    except Exception as error:
        return json_error(str(error), 500)
    return jsonify(
        {
            "ok": True,
            "success": True,
            "presets": presets,
            "ui": get_ui_settings(document),
        }
    )


@app.post("/api/presets/customize")
def api_customize_presets():
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception as error:
        return json_error(f"Invalid JSON payload: {error}", 400)

    if not isinstance(payload, dict):
        return json_error("Request body must be a JSON object.", 400)

    try:
        document = load_presets_document()
        presets_payload = payload.get("presets", [])
        if not isinstance(presets_payload, list):
            raise ValueError("'presets' must be a list.")

        for raw_item in presets_payload:
            item = sanitize_preset_update(raw_item)
            existing = document.get(item["name"], {})
            if not isinstance(existing, dict):
                existing = {}

            existing["label"] = item["label"]
            existing["description"] = item["description"]
            existing["color"] = item["color"]
            existing["order"] = item["order"]
            existing["size"] = item["size"]
            document[item["name"]] = existing

        if "ui" in payload:
            ui_payload = payload.get("ui")
            if not isinstance(ui_payload, dict):
                raise ValueError("'ui' must be an object.")
            layout_mode = str(ui_payload.get("layout_mode", DEFAULT_LAYOUT_MODE)).strip().lower()
            if layout_mode not in ALLOWED_LAYOUT_MODES:
                raise ValueError("Invalid layout_mode value.")
            document["_ui"] = {"layout_mode": layout_mode}

        write_presets_document(document)
    except ValueError as error:
        return json_error(str(error), 400)
    except Exception as error:
        LOGGER.exception("Failed to save preset customization.")
        return json_error(f"Could not save preset customization: {error}", 500)

    try:
        presets = remote.get_presets_summary()
    except vmr.VoicemeeterError as error:
        return json_error(str(error), 500)

    return jsonify(
        {
            "ok": True,
            "success": True,
            "message": "Preset layout updated.",
            "presets": presets,
            "ui": get_ui_settings(document),
        }
    )


@app.post("/api/preset/<preset_name>")
def api_apply_preset(preset_name: str):
    try:
        result = remote.apply_preset(preset_name)
        return jsonify(
            {
                "ok": True,
                "success": True,
                "message": result.get("message", ""),
                "preset": result,
                **result,
            }
        )
    except vmr.PresetNotFoundError as error:
        return json_error(str(error), 404, preset=preset_name)
    except vmr.ConfigError as error:
        return json_error(str(error), 500, preset=preset_name)
    except vmr.DllNotFoundError as error:
        return json_error(str(error), 503, preset=preset_name)
    except vmr.LoginError as error:
        return json_error(str(error), 503, preset=preset_name)
    except vmr.VoicemeeterNotRunningError as error:
        return json_error(str(error), 503, preset=preset_name)
    except vmr.PresetError as error:
        LOGGER.exception("Preset '%s' failed.", preset_name)
        return json_error(str(error), 500, preset=preset_name)
    except vmr.VoicemeeterError as error:
        LOGGER.exception("Failed to apply preset '%s'.", preset_name)
        return json_error(str(error), 500, preset=preset_name)


if __name__ == "__main__":
    runtime_config = load_app_config()
    host = runtime_config.get("host", DEFAULT_HOST)
    port = int(runtime_config.get("port", DEFAULT_PORT))

    LOGGER.info("Starting local server on http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)
