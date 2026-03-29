from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - Windows only
    winreg = None


logger = logging.getLogger("voicemeeter-remote.vmr")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("config.json")
DEFAULT_PRESETS_PATH = Path(__file__).resolve().with_name("presets.json")
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^}]+?)\s*}}")
SCRIPT_COMMENT_PATTERN = re.compile(r"^\s*(#|//|;)")

DLL_NAME_32 = "VoicemeeterRemote.dll"
DLL_NAME_64 = "VoicemeeterRemote64.dll"
VM_TYPE_NAMES = {1: "Voicemeeter", 2: "Voicemeeter Banana", 3: "Voicemeeter Potato"}


class VoicemeeterError(Exception):
    pass


class ConfigError(VoicemeeterError):
    pass


class DllNotFoundError(VoicemeeterError):
    pass


class LoginError(VoicemeeterError):
    pass


class ParameterError(VoicemeeterError):
    pass


class PresetError(VoicemeeterError):
    pass


class PresetNotFoundError(PresetError):
    pass


class VoicemeeterNotRunningError(VoicemeeterError):
    pass


class VoicemeeterTypeError(VoicemeeterError):
    pass


class VoicemeeterRemote:
    def __init__(
        self,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        presets_path: str | Path = DEFAULT_PRESETS_PATH,
    ) -> None:
        self.config_path = Path(config_path)
        self.presets_path = Path(presets_path)
        self._lock = threading.RLock()
        self._dll = None
        self._dll_path: Path | None = None
        self._string_setter = None
        self._login_code: int | None = None
        self._config: dict[str, Any] = {}
        self._presets: dict[str, Any] = {}

    def reload_files(self) -> None:
        self._config = self._load_json(self.config_path, "config.json")
        self._presets = self._load_json(self.presets_path, "presets.json")

    def login(self) -> int:
        with self._lock:
            self.reload_files()
            self._ensure_dll_loaded()

            if self._login_code is not None and self._login_code >= 0:
                return self._login_code

            code = int(self._dll.VBVMR_Login())
            self._login_code = code
            if code < 0:
                raise LoginError(self._login_message(code))

            logger.info("Voicemeeter login returned %s", code)
            return code

    def logout(self) -> None:
        with self._lock:
            if self._dll is None or self._login_code is None or self._login_code < 0:
                return

            try:
                result = int(self._dll.VBVMR_Logout())
                logger.info("Voicemeeter logout returned %s", result)
            except Exception:
                logger.exception("Voicemeeter logout failed")
            finally:
                self._login_code = None

    def set_float_parameter(self, name: str, value: float) -> None:
        with self._lock:
            self.login()
            self._ensure_expected_type()
            resolved_name = str(self._resolve_value(name))

            try:
                resolved_value = float(self._resolve_value(value))
            except (TypeError, ValueError) as error:
                raise ParameterError(
                    f"Float parameter '{resolved_name}' needs a numeric value."
                ) from error

            logger.info("Setting float parameter %s=%s", resolved_name, resolved_value)
            result = int(
                self._dll.VBVMR_SetParameterFloat(
                    self._encode_param_name(resolved_name),
                    ctypes.c_float(resolved_value),
                )
            )
            self._raise_parameter_error(result, resolved_name, "set_float_parameter")

    def set_string_parameter(self, name: str, value: str) -> None:
        with self._lock:
            self.login()
            self._ensure_expected_type()
            resolved_name = str(self._resolve_value(name))
            resolved_value = str(self._resolve_value(value))

            logger.info("Setting string parameter %s=%s", resolved_name, resolved_value)

            if getattr(self, "_use_wide_strings", False):
                result = int(self._string_setter(self._encode_param_name(resolved_name), resolved_value))
            else:
                result = int(
                    self._string_setter(
                        self._encode_param_name(resolved_name),
                        self._encode_ansi(resolved_value),
                    )
                )

            self._raise_parameter_error(result, resolved_name, "set_string_parameter")

    def get_float_parameter(self, name: str) -> float:
        with self._lock:
            self.login()
            self._ensure_expected_type()
            resolved_name = str(self._resolve_value(name))
            output = ctypes.c_float()
            result = int(
                self._dll.VBVMR_GetParameterFloat(
                    self._encode_param_name(resolved_name),
                    ctypes.byref(output),
                )
            )
            self._raise_parameter_error(result, resolved_name, "get_float_parameter")
            return float(output.value)

    def apply_preset(self, preset_name: str) -> dict[str, Any]:
        with self._lock:
            self.reload_files()
            self.login()
            self._ensure_expected_type()

            library_presets = self._list_library_presets()
            if preset_name in library_presets:
                metadata = self._presets.get(preset_name, {}) if isinstance(self._presets.get(preset_name), dict) else {}
                label = str(metadata.get("label") or library_presets[preset_name].stem)
                return self._apply_command_load_preset(preset_name, label, library_presets[preset_name])

            preset = self._presets.get(preset_name)
            if preset is None:
                raise PresetNotFoundError(
                    f"Preset '{preset_name}' was not found in presets.json."
                )

            label = str(preset.get("label") or preset_name.replace("_", " ").title())
            script_file = preset.get("script_file")
            if script_file:
                return self._apply_script_file_preset(preset_name, label, script_file)

            actions = preset.get("actions")
            if not isinstance(actions, list) or not actions:
                raise PresetError(
                    f"Preset '{preset_name}' needs either 'actions' or 'script_file'."
                )

            executed = 0
            skipped = 0

            for index, action in enumerate(actions, start=1):
                try:
                    applied = self._apply_action(preset_name, index, action)
                    if applied:
                        executed += 1
                    else:
                        skipped += 1
                except VoicemeeterError as error:
                    raise PresetError(
                        f"Preset '{label}' failed on action {index}/{len(actions)}: {error}. "
                        "Earlier actions may already have been applied."
                    ) from error

            return {
                "preset": preset_name,
                "label": label,
                "message": (
                    f"Preset '{label}' applied successfully."
                    if skipped == 0
                    else f"Preset '{label}' applied successfully ({skipped} optional action(s) skipped)."
                ),
                "action_count": executed,
                "skipped_actions": skipped,
            }

    def get_presets_summary(self) -> list[dict[str, Any]]:
        self.reload_files()
        library_presets = self._list_library_presets()
        if library_presets:
            summaries: list[dict[str, Any]] = []
            for name, path in library_presets.items():
                metadata = self._presets.get(name, {}) if isinstance(self._presets.get(name), dict) else {}
                label = str(metadata.get("label") or path.stem)
                description = str(metadata.get("description") or "")
                color = str(metadata.get("color") or "").strip()
                try:
                    order = int(metadata.get("order", 9999))
                except (TypeError, ValueError):
                    order = 9999
                size = str(metadata.get("size") or "normal").strip().lower()
                if size not in {"normal", "wide"}:
                    size = "normal"

                summaries.append(
                    {
                        "name": name,
                        "label": label,
                        "description": description,
                        "filename": path.name,
                        "color": color,
                        "mode": "command_load",
                        "order": order,
                        "size": size,
                    }
                )

            summaries.sort(key=lambda item: (int(item["order"]), str(item["label"]).lower()))
            return summaries

        summaries = []
        for name, preset in self._presets.items():
            if str(name).startswith("_"):
                continue
            if not isinstance(preset, dict):
                continue

            try:
                order = int(preset.get("order", 9999))
            except (TypeError, ValueError):
                order = 9999
            size = str(preset.get("size") or "normal").strip().lower()
            if size not in {"normal", "wide"}:
                size = "normal"

            script_file = preset.get("script_file")
            filename = ""
            if isinstance(script_file, str) and script_file.strip():
                filename = self._resolve_script_path(script_file).name

            summaries.append(
                {
                    "name": name,
                    "label": str(preset.get("label") or name.replace("_", " ").title()),
                    "description": str(preset.get("description") or ""),
                    "filename": filename,
                    "color": str(preset.get("color") or "").strip(),
                    "mode": "script_file" if preset.get("script_file") else "actions",
                    "order": order,
                    "size": size,
                }
            )

        summaries.sort(key=lambda item: (int(item["order"]), str(item["label"]).lower()))
        return summaries

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            self.reload_files()
            status = {
                "ok": False,
                "server_running": True,
                "dll_found": False,
                "dll_path": None,
                "login_ok": False,
                "login_code": None,
                "voicemeeter_running": False,
                "voicemeeter_type": None,
                "expected_type": self._type_name(self._expected_type_code()),
                "message": "",
            }

            try:
                self._ensure_dll_loaded()
                status["dll_found"] = True
                status["dll_path"] = str(self._dll_path)
                status["login_code"] = self.login()
                status["login_ok"] = True

                detected = self._get_voicemeeter_type()
                status["voicemeeter_running"] = True
                status["voicemeeter_type"] = self._type_name(detected)

                expected = self._expected_type_code()
                if expected is not None and detected != expected:
                    status["message"] = (
                        f"Connected to {self._type_name(detected)}, but config.json expects "
                        f"{self._type_name(expected)}."
                    )
                    return status

                status["ok"] = True
                status["message"] = f"{self._type_name(detected)} is reachable and ready."
                return status
            except VoicemeeterError as error:
                status["message"] = str(error)
                return status

    def _load_json(self, path: Path, label: str) -> dict[str, Any]:
        if not path.exists():
            raise ConfigError(f"{label} is missing: {path}")

        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as error:
            raise ConfigError(f"{label} contains invalid JSON: {error}") from error

        if not isinstance(payload, dict):
            raise ConfigError(f"{label} must contain a JSON object at the top level.")
        return payload

    def _ensure_dll_loaded(self) -> None:
        if self._dll is not None:
            return

        dll_path = self._discover_dll_path()
        try:
            dll = ctypes.WinDLL(str(dll_path))
        except OSError as error:
            raise DllNotFoundError(
                f"Found a Voicemeeter DLL at '{dll_path}', but Windows could not load it: {error}"
            ) from error

        dll.VBVMR_Login.argtypes = []
        dll.VBVMR_Login.restype = ctypes.c_long
        dll.VBVMR_Logout.argtypes = []
        dll.VBVMR_Logout.restype = ctypes.c_long
        dll.VBVMR_GetVoicemeeterType.argtypes = [ctypes.POINTER(ctypes.c_long)]
        dll.VBVMR_GetVoicemeeterType.restype = ctypes.c_long
        dll.VBVMR_IsParametersDirty.argtypes = []
        dll.VBVMR_IsParametersDirty.restype = ctypes.c_long
        dll.VBVMR_GetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_float)]
        dll.VBVMR_GetParameterFloat.restype = ctypes.c_long
        dll.VBVMR_SetParameterFloat.argtypes = [ctypes.c_char_p, ctypes.c_float]
        dll.VBVMR_SetParameterFloat.restype = ctypes.c_long
        dll.VBVMR_SetParametersW.argtypes = [ctypes.c_wchar_p]
        dll.VBVMR_SetParametersW.restype = ctypes.c_long

        if hasattr(dll, "VBVMR_SetParameterStringW"):
            dll.VBVMR_SetParameterStringW.argtypes = [ctypes.c_char_p, ctypes.c_wchar_p]
            dll.VBVMR_SetParameterStringW.restype = ctypes.c_long
            self._string_setter = dll.VBVMR_SetParameterStringW
            self._use_wide_strings = True
        else:
            dll.VBVMR_SetParameterStringA.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            dll.VBVMR_SetParameterStringA.restype = ctypes.c_long
            self._string_setter = dll.VBVMR_SetParameterStringA
            self._use_wide_strings = False

        self._dll = dll
        self._dll_path = dll_path
        logger.info("Loaded Voicemeeter DLL from %s", dll_path)

    def _discover_dll_path(self) -> Path:
        configured = str(self._config.get("dll_path", "")).strip()
        if configured:
            candidate = Path(os.path.expandvars(configured)).expanduser()
            if candidate.is_file():
                return candidate
            raise DllNotFoundError(f"Configured dll_path does not exist: '{candidate}'.")

        env_path = os.environ.get("VOICEMEETER_REMOTE_DLL", "").strip()
        if env_path and Path(env_path).is_file():
            return Path(env_path)

        candidates: list[Path] = []
        for directory in self._registry_install_dirs() + self._common_install_dirs():
            for dll_name in self._preferred_dll_names():
                candidates.append(directory / dll_name)

        seen: set[str] = set()
        unique_candidates: list[Path] = []
        for candidate in candidates:
            normalized = str(candidate).lower()
            if normalized not in seen:
                seen.add(normalized)
                unique_candidates.append(candidate)

        for candidate in unique_candidates:
            if candidate.is_file():
                return candidate

        tried = "\n".join(f"- {path}" for path in unique_candidates[:12])
        raise DllNotFoundError(
            "Could not find VoicemeeterRemote64.dll automatically. "
            "Set 'dll_path' in config.json to the full DLL path.\n"
            f"Tried these locations:\n{tried}"
        )

    def _registry_install_dirs(self) -> list[Path]:
        if winreg is None:
            return []

        directories: list[Path] = []
        search_roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VB-Audio\Voicemeeter"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\VB-Audio\Voicemeeter"),
        ]

        for root, key_path in search_roots:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    subkey_count = winreg.QueryInfoKey(key)[0]
                    if subkey_count:
                        for index in range(subkey_count):
                            try:
                                subkey_name = winreg.EnumKey(key, index)
                                with winreg.OpenKey(key, subkey_name) as app_key:
                                    display_name = self._read_reg_value(app_key, "DisplayName")
                                    if display_name and "voicemeeter" not in display_name.lower():
                                        continue
                                    directories.extend(self._collect_dirs_from_key(app_key))
                            except OSError:
                                continue
                    else:
                        directories.extend(self._collect_dirs_from_key(key))
            except OSError:
                continue

        unique: list[Path] = []
        seen: set[str] = set()
        for directory in directories:
            normalized = str(directory).lower()
            if normalized not in seen:
                seen.add(normalized)
                unique.append(directory)
        return unique

    def _collect_dirs_from_key(self, key: Any) -> list[Path]:
        directories: list[Path] = []
        for value_name in ("InstallLocation", "InstallDir", "Path", "DisplayIcon", "UninstallString"):
            value = self._read_reg_value(key, value_name)
            if not value:
                continue
            extracted = self._extract_install_dir(value)
            if extracted is not None:
                directories.append(extracted)
        return directories

    def _common_install_dirs(self) -> list[Path]:
        directories: list[Path] = []
        for variable_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(variable_name)
            if not base:
                continue
            directories.append(Path(base) / "VB" / "Voicemeeter")
            directories.append(Path(base) / "Voicemeeter")
        return directories

    def _expected_type_code(self) -> int | None:
        expected = self._config.get("expected_voicemeeter_type", 3)
        try:
            return int(expected)
        except (TypeError, ValueError):
            return None

    def _ensure_expected_type(self) -> None:
        expected = self._expected_type_code()
        if expected is None:
            return

        detected = self._get_voicemeeter_type()
        if detected != expected:
            raise VoicemeeterTypeError(
                f"Connected to {self._type_name(detected)}, but config.json expects {self._type_name(expected)}."
            )

    def _get_voicemeeter_type(self) -> int:
        detected = ctypes.c_long()
        result = int(self._dll.VBVMR_GetVoicemeeterType(ctypes.byref(detected)))
        if result >= 0 and detected.value > 0:
            return int(detected.value)

        dirty = int(self._dll.VBVMR_IsParametersDirty())
        if dirty >= 0 and detected.value > 0:
            return int(detected.value)

        raise VoicemeeterNotRunningError(
            "Voicemeeter is not running. Start Voicemeeter Potato, then refresh the page."
        )

    def _apply_action(self, preset_name: str, index: int, action: Any) -> bool:
        if not isinstance(action, dict):
            raise PresetError(f"Preset '{preset_name}' action {index} must be a JSON object.")

        action_type = action.get("type")
        name = action.get("name")
        if action_type not in {"set_float_parameter", "set_string_parameter"}:
            raise PresetError(
                f"Preset '{preset_name}' action {index} uses unsupported type '{action_type}'."
            )
        if not isinstance(name, str) or not name.strip():
            raise PresetError(
                f"Preset '{preset_name}' action {index} is missing a valid parameter name."
            )

        resolved_name = str(self._resolve_value(name))
        resolved_value = self._resolve_value(action.get("value"))

        if action_type == "set_float_parameter":
            try:
                resolved_value = float(resolved_value)
            except (TypeError, ValueError) as error:
                raise PresetError(
                    f"Preset '{preset_name}' action {index} requires a numeric value for '{resolved_name}'."
                ) from error

            logger.info(
                "Preset '%s' action %s: %s=%s",
                preset_name,
                index,
                resolved_name,
                resolved_value,
            )
            result = int(
                self._dll.VBVMR_SetParameterFloat(
                    self._encode_param_name(resolved_name),
                    ctypes.c_float(resolved_value),
                )
            )
            self._raise_parameter_error(result, resolved_name, "set_float_parameter")
            return True

        resolved_value = str(resolved_value)
        if action.get("optional") and not resolved_value.strip():
            logger.info(
                "Skipping optional empty string action for preset '%s': %s",
                preset_name,
                resolved_name,
            )
            return False

        logger.info(
            "Preset '%s' action %s: %s=%s",
            preset_name,
            index,
            resolved_name,
            resolved_value,
        )

        if self._use_wide_strings:
            result = int(self._string_setter(self._encode_param_name(resolved_name), resolved_value))
        else:
            result = int(
                self._string_setter(
                    self._encode_param_name(resolved_name),
                    self._encode_ansi(resolved_value),
                )
            )
        self._raise_parameter_error(result, resolved_name, "set_string_parameter")
        return True

    def _apply_script_file_preset(
        self,
        preset_name: str,
        label: str,
        script_file: Any,
    ) -> dict[str, Any]:
        if not isinstance(script_file, str) or not script_file.strip():
            raise PresetError(
                f"Preset '{preset_name}' has an invalid 'script_file' value."
            )

        script_path = self._resolve_script_path(script_file)
        if not script_path.is_file():
            raise PresetError(
                f"Preset file for '{preset_name}' was not found: {script_path}"
            )

        try:
            raw_script = script_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_script = script_path.read_text(encoding="mbcs")
        except OSError as error:
            raise PresetError(
                f"Preset file for '{preset_name}' could not be read: {error}"
            ) from error

        resolved_script = self._resolve_value(raw_script)
        if not isinstance(resolved_script, str):
            resolved_script = str(resolved_script)

        script_text = self._normalize_script_text(resolved_script)
        if not script_text:
            raise PresetError(
                f"Preset file for '{preset_name}' does not contain any usable commands."
            )

        command_count = self._count_script_commands(script_text)
        logger.info(
            "Applying script preset '%s' from %s with %s command(s)",
            preset_name,
            script_path,
            command_count,
        )

        result = int(self._dll.VBVMR_SetParametersW(script_text))
        if result == 0:
            return {
                "preset": preset_name,
                "label": label,
                "message": f"Preset '{label}' loaded from file successfully.",
                "action_count": command_count,
                "skipped_actions": 0,
                "script_file": str(script_path),
            }

        if result == -2:
            raise VoicemeeterNotRunningError(
                "Voicemeeter is not running. Start Voicemeeter Potato, then try again."
            )

        if result > 0:
            raise PresetError(
                f"Preset '{label}' failed in script line {result}. "
                f"Check the file '{script_path.name}' for an invalid command."
            )

        raise PresetError(
            f"Preset '{label}' could not be loaded from file. "
            f"Voicemeeter returned script error code {result}."
        )

    def _apply_command_load_preset(
        self,
        preset_name: str,
        label: str,
        preset_path: Path,
    ) -> dict[str, Any]:
        logger.info("Loading Voicemeeter XML preset '%s' from %s", preset_name, preset_path)

        if self._use_wide_strings:
            result = int(self._string_setter(self._encode_param_name("Command.Load"), str(preset_path)))
        else:
            result = int(
                self._string_setter(
                    self._encode_param_name("Command.Load"),
                    self._encode_ansi(str(preset_path)),
                )
            )

        self._raise_parameter_error(result, "Command.Load", "load_preset_file")
        return {
            "preset": preset_name,
            "label": label,
            "message": f"Preset '{label}' loaded from XML file successfully.",
            "action_count": 1,
            "skipped_actions": 0,
            "script_file": str(preset_path),
        }

    def _resolve_value(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        matches = list(PLACEHOLDER_PATTERN.finditer(value))
        if not matches:
            return value

        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            return self._lookup_config(matches[0].group(1))

        return PLACEHOLDER_PATTERN.sub(
            lambda match: str(self._lookup_config(match.group(1))),
            value,
        )

    def _resolve_script_path(self, relative_or_absolute_path: str) -> Path:
        candidate = Path(os.path.expandvars(relative_or_absolute_path)).expanduser()
        if candidate.is_absolute():
            return candidate
        return self.presets_path.parent / candidate

    def _list_library_presets(self) -> dict[str, Path]:
        configured_dir = str(self._config.get("preset_library_dir", "")).strip()
        if not configured_dir:
            return {}

        candidate = Path(os.path.expandvars(configured_dir)).expanduser()
        if not candidate.is_absolute():
            candidate = self.config_path.parent / candidate

        if not candidate.exists():
            raise ConfigError(f"Configured preset_library_dir does not exist: {candidate}")
        if not candidate.is_dir():
            raise ConfigError(f"Configured preset_library_dir is not a folder: {candidate}")

        configured_extensions = self._config.get("preset_file_extensions", [".xml"])
        if not isinstance(configured_extensions, list) or not configured_extensions:
            configured_extensions = [".xml"]

        extensions = {
            str(extension).lower() if str(extension).startswith(".") else f".{str(extension).lower()}"
            for extension in configured_extensions
        }

        presets: dict[str, Path] = {}
        for file_path in sorted(candidate.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in extensions:
                continue
            presets[file_path.stem] = file_path
        return presets

    def _normalize_script_text(self, raw_script: str) -> str:
        lines: list[str] = []
        for line in raw_script.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if SCRIPT_COMMENT_PATTERN.match(stripped):
                continue
            lines.append(stripped)
        return "\n".join(lines)

    def _count_script_commands(self, script_text: str) -> int:
        return len([line for line in script_text.splitlines() if line.strip()])

    def _lookup_config(self, key_path: str) -> Any:
        current: Any = self._config
        for key in key_path.split("."):
            if not isinstance(current, dict) or key not in current:
                raise ConfigError(
                    f"Missing config value for placeholder '{{{{{key_path}}}}}'."
                )
            current = current[key]
        return current

    def _raise_parameter_error(self, result: int, parameter_name: str, action_type: str) -> None:
        if result == 0:
            return
        if result == -2:
            raise VoicemeeterNotRunningError(
                "Voicemeeter is not running. Start Voicemeeter Potato, then try again."
            )

        explanation = {
            -1: "unexpected API error",
            -3: "unknown parameter name",
            -5: "Voicemeeter structure mismatch",
        }.get(result, f"error {result}")
        raise ParameterError(f"{action_type} failed for '{parameter_name}': {explanation}.")

    def _preferred_dll_names(self) -> list[str]:
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            return [DLL_NAME_64, DLL_NAME_32]
        return [DLL_NAME_32, DLL_NAME_64]

    def _encode_param_name(self, name: str) -> bytes:
        try:
            return name.encode("ascii")
        except UnicodeEncodeError as error:
            raise ParameterError(
                f"Parameter names must be ASCII for the Voicemeeter API: {name!r}"
            ) from error

    @staticmethod
    def _encode_ansi(value: str) -> bytes:
        return value.encode("mbcs", errors="replace")

    def _extract_install_dir(self, raw_value: str) -> Path | None:
        candidate = Path(raw_value.strip().strip('"'))
        if candidate.is_dir():
            return candidate
        if candidate.is_file():
            return candidate.parent

        match = re.search(
            r"([A-Za-z]:\\[^\\/:*?\"<>|\r\n]+(?:\\[^\\/:*?\"<>|\r\n]+)*)",
            raw_value,
        )
        if not match:
            return None

        parsed = Path(match.group(1))
        if parsed.suffix:
            return parsed.parent
        return parsed

    def _read_reg_value(self, key: Any, value_name: str) -> str | None:
        try:
            value, _ = winreg.QueryValueEx(key, value_name)
        except OSError:
            return None
        if value is None:
            return None
        return str(value).strip()

    def _type_name(self, type_code: int | None) -> str:
        if type_code is None:
            return "Unknown"
        return VM_TYPE_NAMES.get(type_code, f"Unknown ({type_code})")

    def _login_message(self, code: int) -> str:
        if code == -1:
            return "Voicemeeter login failed because the Remote API is not available."
        if code == -2:
            return "Voicemeeter is not running. Start Voicemeeter Potato and try again."
        return f"Voicemeeter login failed with error code {code}."


_default_client: VoicemeeterRemote | None = None


def configure(
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    presets_path: str | Path = DEFAULT_PRESETS_PATH,
) -> VoicemeeterRemote:
    global _default_client
    _default_client = VoicemeeterRemote(config_path=config_path, presets_path=presets_path)
    return _default_client


def _require_default_client() -> VoicemeeterRemote:
    if _default_client is None:
        raise VoicemeeterError("vmr.configure(...) must be called before using module-level helpers.")
    return _default_client


def login() -> int:
    return _require_default_client().login()


def logout() -> None:
    _require_default_client().logout()


def set_float_parameter(name: str, value: float) -> None:
    _require_default_client().set_float_parameter(name, value)


def set_string_parameter(name: str, value: str) -> None:
    _require_default_client().set_string_parameter(name, value)


def get_float_parameter(name: str) -> float:
    return _require_default_client().get_float_parameter(name)


def apply_preset(preset_name: str) -> dict[str, Any]:
    return _require_default_client().apply_preset(preset_name)


def get_health() -> dict[str, Any]:
    return _require_default_client().health_check()
