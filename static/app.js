const appTitle = document.getElementById("appTitle");
const healthDot = document.getElementById("healthDot");
const healthState = document.getElementById("healthState");
const healthMessage = document.getElementById("healthMessage");
const autostartChip = document.getElementById("autostartChip");
const autostartState = document.getElementById("autostartState");
const modeLabel = document.getElementById("modeLabel");
const surfaceHint = document.getElementById("surfaceHint");
const refreshButton = document.getElementById("refreshButton");
const presetGrid = document.getElementById("presetGrid");
const editorTitle = document.getElementById("editorTitle");
const editorEmpty = document.getElementById("editorEmpty");
const editorFormWrap = document.getElementById("editorFormWrap");
const labelInput = document.getElementById("labelInput");
const colorInput = document.getElementById("colorInput");
const descriptionInput = document.getElementById("descriptionInput");
const filenameDisplay = document.getElementById("filenameDisplay");
const moveEarlierButton = document.getElementById("moveEarlierButton");
const moveLaterButton = document.getElementById("moveLaterButton");
const savePresetButton = document.getElementById("savePresetButton");
const statusBox = document.getElementById("statusBox");
const lockToggle = document.getElementById("lockToggle");
const lockStateLabel = document.getElementById("lockStateLabel");
const serverAddress = document.getElementById("serverAddress");
const layoutButtons = Array.from(document.querySelectorAll(".layout-chip"));
const sizeButtons = Array.from(document.querySelectorAll(".size-chip"));

const FALLBACK_COLORS = [
  "#58b8ff",
  "#70dbff",
  "#68d39b",
  "#7be495",
  "#ffb457",
  "#ffc96b",
  "#ff7d66",
  "#ff8ea1",
];

const state = {
  presets: [],
  ui: {
    layout_mode: "mosaic",
  },
  busyPreset: null,
  locked: true,
  selectedPresetName: null,
  savingCustomization: false,
};

document.addEventListener("DOMContentLoaded", () => {
  refreshButton.addEventListener("click", () => {
    initialize(true);
  });

  lockToggle.addEventListener("click", toggleLock);
  moveEarlierButton.addEventListener("click", () => moveSelectedPreset(-1));
  moveLaterButton.addEventListener("click", () => moveSelectedPreset(1));
  savePresetButton.addEventListener("click", () => saveCurrentPreset("Preset look saved."));

  layoutButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setLayoutMode(button.dataset.layout || "mosaic");
    });
  });

  sizeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      setSelectedPresetSize(button.dataset.size || "normal");
    });
  });

  labelInput.addEventListener("input", () => {
    updateSelectedPreset({ label: labelInput.value });
    renderPresets();
  });

  descriptionInput.addEventListener("input", () => {
    updateSelectedPreset({ description: descriptionInput.value });
    renderPresets();
  });

  colorInput.addEventListener("input", () => {
    updateSelectedPreset({ color: colorInput.value });
    renderPresets();
  });

  colorInput.addEventListener("change", () => {
    saveCurrentPreset("Accent color updated.");
  });

  [labelInput, descriptionInput].forEach((input) => {
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveCurrentPreset("Preset text saved.");
      }
    });

    input.addEventListener("blur", () => {
      if (!state.locked && getSelectedPreset()) {
        saveCurrentPreset("Preset text saved.");
      }
    });
  });

  initialize(false);
});

async function initialize(isManualRefresh) {
  setStatus(
    "info",
    isManualRefresh
      ? "Refreshing your local scene surface..."
      : "Connecting to your local scene surface..."
  );

  try {
    await loadConfig();
    await loadAutostart();
    await loadHealth();
    await loadPresets();
  } catch (error) {
    setStatus("error", error.message);
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();
  let payload = {};

  if (text) {
    try {
      payload = JSON.parse(text);
    } catch (error) {
      throw new Error(`Invalid JSON response from ${url}.`);
    }
  }

  if (!response.ok || payload.success === false) {
    throw new Error(payload.message || `Request failed with status ${response.status}.`);
  }

  return payload;
}

async function loadConfig() {
  const data = await fetchJson("/api/config");
  const config = data.config || {};
  const title = config.app_title || "Voicemeeter Potato Remote";

  document.title = title;
  appTitle.textContent = title;
  serverAddress.textContent = `${location.hostname}:${config.port || 8787} on private LAN`;
}

async function loadHealth() {
  const data = await fetchJson("/api/health");
  renderHealth(data);

  if (data.dll_found && data.login_ok && data.voicemeeter_running) {
    setStatus("success", data.message || "Voicemeeter is reachable.");
    return;
  }

  setStatus("info", data.message || "Server is up, but Voicemeeter is not ready.");
}

async function loadAutostart() {
  const data = await fetchJson("/api/autostart");
  renderAutostart(data.autostart || {});
}

async function loadPresets() {
  const data = await fetchJson("/api/presets");
  state.presets = normalizePresets(data.presets);
  state.ui = normalizeUi(data.ui);

  if (state.selectedPresetName && !state.presets.some((preset) => preset.name === state.selectedPresetName)) {
    state.selectedPresetName = null;
  }

  renderAll();
}

function normalizePresets(rawPresets) {
  if (!Array.isArray(rawPresets)) {
    return [];
  }

  return rawPresets
    .map((preset, index) => ({
      name: String(preset.name || "").trim(),
      label: String(preset.label || preset.name || "Preset").trim(),
      description: String(preset.description || "").trim(),
      filename: String(preset.filename || preset.name || "").trim(),
      color: normalizeColor(preset.color, index),
      order: normalizeOrder(preset.order, index),
      size: normalizeSize(preset.size),
    }))
    .filter((preset) => preset.name)
    .sort((left, right) => left.order - right.order || left.label.localeCompare(right.label));
}

function normalizeUi(rawUi) {
  const layoutMode = rawUi && typeof rawUi.layout_mode === "string"
    ? rawUi.layout_mode.trim().toLowerCase()
    : "mosaic";

  if (!["stack", "duo", "mosaic"].includes(layoutMode)) {
    return { layout_mode: "mosaic" };
  }

  return { layout_mode: layoutMode };
}

function normalizeOrder(value, index) {
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric;
  }
  return (index + 1) * 10;
}

function normalizeSize(value) {
  return value === "wide" ? "wide" : "normal";
}

function renderAll() {
  renderSurfaceCopy();
  renderPresets();
  renderEditor();
  renderDock();
}

function renderSurfaceCopy() {
  if (state.locked) {
    modeLabel.textContent = "Locked mode";
    surfaceHint.textContent = "Tap any preset to load it.";
    return;
  }

  modeLabel.textContent = "Edit mode";
  surfaceHint.textContent = "Tap a tile to rename it, recolor it or move it.";
}

function renderHealth(data) {
  const compactType = compactVoicemeeterName(data.voicemeeter_type);

  if (data.dll_found && data.login_ok && data.voicemeeter_running) {
    healthDot.dataset.state = "ready";
    healthState.textContent = compactType || "Potato";
    healthMessage.textContent = "Ready";
    return;
  }

  if (data.dll_found) {
    healthDot.dataset.state = "warn";
    healthState.textContent = compactType || "Voicemeeter";
    healthMessage.textContent = "Check";
    return;
  }

  healthDot.dataset.state = "error";
  healthState.textContent = "DLL";
  healthMessage.textContent = "Missing";
}

function renderAutostart(autostart) {
  const enabled = Boolean(autostart.enabled);
  const supported = autostart.supported !== false;
  const hasError = typeof autostart.error === "string" && autostart.error.trim();

  if (!supported) {
    autostartChip.dataset.state = "unknown";
    autostartState.textContent = "N/A";
    autostartChip.title = autostart.message || "Autostart status is unavailable on this platform.";
    return;
  }

  if (hasError) {
    autostartChip.dataset.state = "error";
    autostartState.textContent = "Issue";
    autostartChip.title = autostart.message || autostart.error;
    return;
  }

  autostartChip.dataset.state = enabled ? "on" : "off";
  autostartState.textContent = enabled ? "On" : "Off";
  autostartChip.title = autostart.message || `Autostart is ${enabled ? "on" : "off"}.`;
}

function renderPresets() {
  presetGrid.dataset.layout = state.ui.layout_mode;

  if (!state.presets.length) {
    presetGrid.innerHTML = '<p class="empty-state">No presets found.</p>';
    return;
  }

  presetGrid.innerHTML = "";

  state.presets.forEach((preset, index) => {
    const tile = document.createElement("article");
    tile.className = "preset-tile";
    tile.dataset.size = normalizeSize(preset.size);
    tile.style.setProperty("--preset-color", normalizeColor(preset.color, index));
    tile.style.animationDelay = `${60 + index * 45}ms`;

    if (preset.name === state.selectedPresetName && !state.locked) {
      tile.classList.add("is-selected");
    }

    if (preset.name === state.busyPreset) {
      tile.classList.add("is-busy");
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-tap";
    button.disabled = state.busyPreset !== null || state.savingCustomization;
    button.addEventListener("click", () => handlePresetTap(preset.name));

    const topRow = document.createElement("span");
    topRow.className = "preset-top";

    const title = document.createElement("span");
    title.className = "preset-title";
    title.textContent = preset.label || preset.name;

    topRow.appendChild(title);

    if (!state.locked && preset.name === state.selectedPresetName) {
      const chip = document.createElement("span");
      chip.className = "selected-chip";
      chip.textContent = "Editing";
      topRow.appendChild(chip);
    }

    const filename = document.createElement("span");
    filename.className = "preset-file";
    filename.textContent = preset.filename || preset.name;

    button.append(topRow, filename);

    if (!state.locked && preset.description) {
      const note = document.createElement("span");
      note.className = "preset-note";
      note.textContent = preset.description;
      button.appendChild(note);
    }

    tile.appendChild(button);
    presetGrid.appendChild(tile);
  });
}

function renderEditor() {
  const selectedPreset = getSelectedPreset();

  layoutButtons.forEach((button) => {
    const isActive = button.dataset.layout === state.ui.layout_mode;
    button.classList.toggle("is-active", isActive);
    button.disabled = state.locked || state.savingCustomization;
  });

  if (state.locked) {
    editorTitle.textContent = "Layout locked";
    editorEmpty.hidden = false;
    editorEmpty.textContent = "Unlock below to rename buttons, recolor them, reorder them and switch the grid.";
    editorFormWrap.hidden = true;
    return;
  }

  if (!selectedPreset) {
    editorTitle.textContent = "Edit unlocked";
    editorEmpty.hidden = false;
    editorEmpty.textContent = "Tap any preset tile to start editing it.";
    editorFormWrap.hidden = true;
    return;
  }

  editorTitle.textContent = selectedPreset.label || selectedPreset.name;
  editorEmpty.hidden = true;
  editorFormWrap.hidden = false;

  labelInput.value = selectedPreset.label || "";
  descriptionInput.value = selectedPreset.description || "";
  colorInput.value = normalizeColor(selectedPreset.color, 0);
  filenameDisplay.textContent = selectedPreset.filename || selectedPreset.name;

  const selectedIndex = state.presets.findIndex((preset) => preset.name === selectedPreset.name);
  moveEarlierButton.disabled = state.savingCustomization || selectedIndex <= 0;
  moveLaterButton.disabled = state.savingCustomization || selectedIndex === -1 || selectedIndex >= state.presets.length - 1;
  savePresetButton.disabled = state.savingCustomization;
  savePresetButton.textContent = state.savingCustomization ? "Saving..." : "Save look";

  sizeButtons.forEach((button) => {
    const isActive = button.dataset.size === normalizeSize(selectedPreset.size);
    button.classList.toggle("is-active", isActive);
    button.disabled = state.savingCustomization;
  });
}

function renderDock() {
  lockStateLabel.textContent = state.locked ? "Locked" : "Unlocked";
  lockToggle.textContent = state.locked ? "Unlock edit" : "Lock layout";
  lockToggle.disabled = state.busyPreset !== null || state.savingCustomization;
}

function getSelectedPreset() {
  return state.presets.find((preset) => preset.name === state.selectedPresetName) || null;
}

function handlePresetTap(name) {
  if (state.locked) {
    const preset = state.presets.find((item) => item.name === name);
    applyPreset(name, preset ? preset.label : name);
    return;
  }

  state.selectedPresetName = name;
  renderPresets();
  renderEditor();

  const preset = getSelectedPreset();
  if (preset) {
    setStatus("info", `Editing "${preset.label}".`);
  }
}

function toggleLock() {
  if (state.busyPreset !== null || state.savingCustomization) {
    return;
  }

  state.locked = !state.locked;

  if (!state.locked && !state.selectedPresetName && state.presets.length) {
    state.selectedPresetName = state.presets[0].name;
  }

  if (state.locked) {
    setStatus("info", "Layout locked. Tap a preset to load it.");
  } else {
    setStatus("info", "Edit unlocked. Tap a preset tile to customize it.");
  }

  renderAll();
}

function updateSelectedPreset(patch) {
  const selectedPreset = getSelectedPreset();
  if (!selectedPreset) {
    return;
  }

  Object.assign(selectedPreset, patch);
}

async function setLayoutMode(layoutMode) {
  if (state.locked || state.savingCustomization) {
    return;
  }

  if (!["stack", "duo", "mosaic"].includes(layoutMode)) {
    return;
  }

  state.ui.layout_mode = layoutMode;
  renderPresets();
  renderEditor();
  await saveCustomization("Grid layout updated.");
}

async function setSelectedPresetSize(size) {
  if (state.locked || state.savingCustomization) {
    return;
  }

  const selectedPreset = getSelectedPreset();
  if (!selectedPreset) {
    return;
  }

  selectedPreset.size = normalizeSize(size);
  renderPresets();
  renderEditor();
  await saveCustomization("Tile size updated.");
}

async function moveSelectedPreset(direction) {
  if (state.locked || state.savingCustomization) {
    return;
  }

  const currentIndex = state.presets.findIndex((preset) => preset.name === state.selectedPresetName);
  const targetIndex = currentIndex + direction;

  if (currentIndex < 0 || targetIndex < 0 || targetIndex >= state.presets.length) {
    return;
  }

  const [movedPreset] = state.presets.splice(currentIndex, 1);
  state.presets.splice(targetIndex, 0, movedPreset);
  resequencePresets();
  renderPresets();
  renderEditor();
  await saveCustomization("Preset order updated.");
}

function resequencePresets() {
  state.presets.forEach((preset, index) => {
    preset.order = (index + 1) * 10;
  });
}

async function saveCurrentPreset(successMessage) {
  if (state.locked || !getSelectedPreset()) {
    return;
  }

  resequencePresets();
  await saveCustomization(successMessage);
}

async function saveCustomization(successMessage) {
  if (state.savingCustomization) {
    return;
  }

  state.savingCustomization = true;
  renderEditor();
  renderDock();
  setStatus("info", "Saving layout changes...");

  try {
    const payload = {
      ui: {
        layout_mode: state.ui.layout_mode,
      },
      presets: state.presets.map((preset, index) => ({
        name: preset.name,
        label: String(preset.label || "").trim(),
        description: String(preset.description || "").trim(),
        color: normalizeColor(preset.color, index),
        order: (index + 1) * 10,
        size: normalizeSize(preset.size),
      })),
    };

    const data = await fetchJson("/api/presets/customize", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    state.presets = normalizePresets(data.presets);
    state.ui = normalizeUi(data.ui);

    if (state.selectedPresetName && !state.presets.some((preset) => preset.name === state.selectedPresetName)) {
      state.selectedPresetName = state.presets[0]?.name || null;
    }

    setStatus("success", data.message || successMessage || "Layout updated.");
  } catch (error) {
    setStatus("error", error.message);
  } finally {
    state.savingCustomization = false;
    renderAll();
  }
}

async function applyPreset(name, label) {
  state.busyPreset = name;
  renderPresets();
  renderDock();
  setStatus("info", `Loading "${label}"...`);

  try {
    const data = await fetchJson(`/api/preset/${encodeURIComponent(name)}`, {
      method: "POST",
    });

    const applied = typeof data.action_count === "number"
      ? data.action_count
      : typeof data.actions_applied === "number"
        ? data.actions_applied
        : null;
    const skipped = typeof data.skipped_actions === "number"
      ? data.skipped_actions
      : typeof data.actions_skipped === "number"
        ? data.actions_skipped
        : 0;
    const detail = applied === null
      ? ""
      : ` ${applied} command(s) applied${skipped ? `, ${skipped} skipped` : ""}.`;

    setStatus("success", `${data.message || `"${label}" applied successfully.`}${detail}`);
    await loadHealthCardOnly();
  } catch (error) {
    setStatus("error", error.message);
    await loadHealthCardOnly();
  } finally {
    state.busyPreset = null;
    renderPresets();
    renderDock();
  }
}

async function loadHealthCardOnly() {
  try {
    const data = await fetchJson("/api/health");
    renderHealth(data);
  } catch (error) {
    healthDot.dataset.state = "error";
    healthState.textContent = "Unavailable";
    healthMessage.textContent = error.message;
  }
}

function setStatus(kind, message) {
  statusBox.className = `status-box status-${kind}`;
  statusBox.textContent = message;
}

function normalizeColor(color, index) {
  if (typeof color === "string" && /^#(?:[0-9a-fA-F]{6})$/.test(color.trim())) {
    return color.trim();
  }

  return FALLBACK_COLORS[index % FALLBACK_COLORS.length];
}

function compactVoicemeeterName(typeName) {
  if (typeof typeName !== "string") {
    return "";
  }

  return typeName.replace(/^Voicemeeter\s+/i, "").trim();
}
