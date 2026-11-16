(() => {
  "use strict";

  const TAU = Math.PI * 2;
  const BASE_SIZE = 720;
  const MIN_PRIZES = 2;
  const MAX_PRIZES = 24;
  const MAX_NAME_LENGTH = 24;
  const MAX_TITLE_LENGTH = 30;
  const MAX_WEIGHT = 1_000_000;
  const HISTORY_SHOWN = 8;

  const PALETTE = [
    "#f6c453",
    "#ef6f6c",
    "#7b61ff",
    "#2ec4b6",
    "#ff9f1c",
    "#4d96ff",
    "#f06595",
    "#5c6b8a",
    "#b7e778",
    "#8d6e63",
    "#00b4d8",
    "#e0aaff",
  ];

  const FALLBACK_TITLE = "幸运大转盘";
  const FALLBACK_ROWS = [
    ["特等奖", 1],
    ["一等奖", 4],
    ["二等奖", 8],
    ["三等奖", 12],
    ["四等奖", 15],
    ["五等奖", 20],
    ["幸运奖", 20],
    ["谢谢参与", 20],
  ];
  const FALLBACK_PRIZES = FALLBACK_ROWS.map(([name, weight], index) => ({
    id: `fallback-${index + 1}`,
    name,
    weight,
    color: PALETTE[index % PALETTE.length],
  }));

  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)");
  const PERCENT_FORMAT = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
  const WEIGHT_FORMAT = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 });
  const TIME_FORMAT = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const DATETIME_FORMAT = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const state = {
    draft: cloneFallbackDraft(),
    savedConfig: fallbackConfig(),
    savedSnapshot: "",
    rotation: 0,
    ready: false,
    spinning: false,
    saving: false,
    modalOpen: false,
    returnFocus: null,
    toastTimer: null,
    resizeObserver: null,
  };
  state.savedSnapshot = snapshotDraft();

  const el = {};

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    cacheElements();
    bindEvents();
    el.titleInput.value = state.draft.title;
    renderPrizeList();
    updateDraftView();
    resizeWheel();
    observeWheel();
    setStatus("loading");
    loadInitialData();
  }

  function cacheElements() {
    const byId = (id) => document.getElementById(id);
    el.page = byId("page");
    el.wheel = byId("wheel");
    el.wheelShell = byId("wheel-shell");
    el.spinButton = byId("spin-button");
    el.spinLabel = el.spinButton.querySelector(".spin-label");
    el.spinSub = el.spinButton.querySelector(".spin-sub");
    el.brandTitle = byId("app-title");
    el.statusPill = byId("server-status");
    el.statusText = byId("status-text");
    el.hint = byId("hint");
    el.historyList = byId("history-list");
    el.historyCount = byId("history-count");
    el.panel = byId("settings-panel");
    el.titleInput = byId("title-input");
    el.totalChip = byId("total-chip");
    el.prizeList = byId("prize-list");
    el.addButton = byId("add-prize");
    el.revertButton = byId("revert-button");
    el.saveButton = byId("save-button");
    el.toast = byId("toast");
    el.modal = byId("result-modal");
    el.resultPrize = byId("result-prize");
    el.resultProb = byId("result-prob");
    el.closeResult = byId("close-result");
  }

  function bindEvents() {
    el.spinButton.addEventListener("click", spin);
    el.saveButton.addEventListener("click", saveConfig);
    el.revertButton.addEventListener("click", revertChanges);
    el.addButton.addEventListener("click", addPrize);

    el.titleInput.addEventListener("input", () => {
      if (!editable()) return;
      state.draft.title = el.titleInput.value;
      updateDraftView();
    });

    el.modal.addEventListener("click", (event) => {
      if (
        event.target instanceof HTMLElement &&
        event.target.hasAttribute("data-close-modal")
      ) {
        closeResult();
      }
    });
    el.closeResult.addEventListener("click", closeResult);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.modalOpen) {
        closeResult();
      }
    });

    window.addEventListener("beforeunload", (event) => {
      if (state.ready && isDirty()) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }

  async function loadInitialData() {
    try {
      const [config, historyPayload] = await Promise.all([
        api("/api/config"),
        api("/api/history"),
      ]);
      applyConfig(config);
      renderHistory(Array.isArray(historyPayload.history) ? historyPayload.history : []);
      state.ready = true;
      setStatus("online");
      refreshControls();
      el.hint.textContent = "点击转盘中间的按钮，结果由服务端按权重抽取。";
      if (typeof config.warning === "string" && config.warning) {
        showToast(config.warning, "warning", 7000);
      }
    } catch (error) {
      state.ready = false;
      setStatus("offline");
      refreshControls();
      el.hint.textContent = "无法连接服务端，请确认 python app.py 仍在运行。";
      showToast(`无法加载配置：${error.message}`, "error", 8000);
    }
  }

  // ---------------------------------------------------------------- config

  function applyConfig(config) {
    const prizes = Array.isArray(config.prizes) ? config.prizes : [];
    state.savedConfig = {
      title: String(config.title || FALLBACK_TITLE),
      prizes: prizes.map((prize) => ({
        id: String(prize.id),
        name: String(prize.name),
        weight: Number(prize.weight),
        color: String(prize.color),
      })),
    };
    resetDraftToSaved();
    el.titleInput.value = state.draft.title;
    renderPrizeList();
    updateDraftView();
  }

  function resetDraftToSaved() {
    state.draft = {
      title: state.savedConfig.title,
      prizes: state.savedConfig.prizes.map((prize) => ({
        id: prize.id,
        name: prize.name,
        weight: formatWeightInput(prize.weight),
        color: prize.color,
      })),
    };
    state.savedSnapshot = snapshotDraft();
  }

  function revertChanges() {
    if (!editable() || !isDirty()) return;
    resetDraftToSaved();
    el.titleInput.value = state.draft.title;
    renderPrizeList();
    updateDraftView();
    showToast("已撤销未保存的修改。", "info");
  }

  async function saveConfig() {
    if (!editable() || !isDirty()) return;
    const problem = validateDraft();
    if (problem) {
      showToast(problem, "error", 5000);
      return;
    }
    state.saving = true;
    refreshControls();
    try {
      const payload = {
        title: state.draft.title.trim(),
        prizes: state.draft.prizes.map((prize) => ({
          id: prize.id,
          name: prize.name.trim(),
          weight: Number(prize.weight),
          color: prize.color,
        })),
      };
      const config = await api("/api/config", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      applyConfig(config);
      showToast("设置已保存，下一次抽奖立即生效。", "success");
    } catch (error) {
      showToast(`保存失败：${error.message}`, "error", 6000);
    } finally {
      state.saving = false;
      refreshControls();
    }
  }

  function validateDraft() {
    if (Array.from(state.draft.title.trim()).length > MAX_TITLE_LENGTH) {
      return `活动标题不能超过 ${MAX_TITLE_LENGTH} 个字符。`;
    }
    if (state.draft.prizes.length < MIN_PRIZES) {
      return `至少需要 ${MIN_PRIZES} 个奖品。`;
    }
    if (state.draft.prizes.length > MAX_PRIZES) {
      return `最多只能有 ${MAX_PRIZES} 个奖品。`;
    }
    for (let index = 0; index < state.draft.prizes.length; index += 1) {
      const prize = state.draft.prizes[index];
      const name = prize.name.trim();
      if (!name) {
        return `第 ${index + 1} 个奖品的名称不能为空。`;
      }
      if (Array.from(name).length > MAX_NAME_LENGTH) {
        return `第 ${index + 1} 个奖品的名称不能超过 ${MAX_NAME_LENGTH} 个字符。`;
      }
      const weight = Number(prize.weight);
      if (!Number.isFinite(weight) || weight <= 0) {
        return `第 ${index + 1} 个奖品的权重必须是大于 0 的数字。`;
      }
      if (weight > MAX_WEIGHT) {
        return `第 ${index + 1} 个奖品的权重不能超过 ${MAX_WEIGHT}。`;
      }
      if (!isValidHex(prize.color)) {
        return `第 ${index + 1} 个奖品的颜色格式不正确。`;
      }
    }
    return null;
  }

  function isDirty() {
    return snapshotDraft() !== state.savedSnapshot;
  }

  function snapshotDraft() {
    return JSON.stringify({
      title: state.draft.title.trim(),
      prizes: state.draft.prizes.map((prize) => ({
        id: prize.id,
        name: prize.name.trim(),
        weight: normalizedWeight(prize.weight),
        color: String(prize.color).toLowerCase(),
      })),
    });
  }

  function normalizedWeight(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : String(value);
  }

  // ------------------------------------------------------- prize list UI

  function renderPrizeList() {
    const fragment = document.createDocumentFragment();
    state.draft.prizes.forEach((prize, index) => {
      fragment.appendChild(createPrizeRow(prize, index));
    });
    el.prizeList.replaceChildren(fragment);
    updateRowProbabilities();
  }

  function createPrizeRow(prize, index) {
    const row = document.createElement("div");
    row.className = "prize-row";
    row.dataset.prizeId = prize.id;

    const color = document.createElement("input");
    color.type = "color";
    color.className = "color-input";
    color.value = isValidHex(prize.color)
      ? prize.color
      : PALETTE[index % PALETTE.length];
    color.setAttribute("aria-label", `第 ${index + 1} 个奖品的颜色`);
    color.addEventListener("input", () => {
      if (!editable()) return;
      prize.color = color.value;
      updateDraftView();
    });

    const name = document.createElement("input");
    name.type = "text";
    name.className = "name-input";
    name.maxLength = MAX_NAME_LENGTH;
    name.autocomplete = "off";
    name.spellcheck = false;
    name.value = prize.name;
    name.placeholder = "奖品名称";
    name.setAttribute("aria-label", `第 ${index + 1} 个奖品的名称`);
    name.addEventListener("input", () => {
      if (!editable()) return;
      prize.name = name.value;
      updateDraftView();
    });

    const weight = document.createElement("input");
    weight.type = "number";
    weight.className = "weight-input";
    weight.min = "0.000001";
    weight.step = "0.01";
    weight.inputMode = "decimal";
    weight.value = prize.weight;
    weight.setAttribute("aria-label", `第 ${index + 1} 个奖品的权重`);
    weight.addEventListener("input", () => {
      if (!editable()) return;
      prize.weight = weight.value;
      updateDraftView();
    });

    const percent = document.createElement("span");
    percent.className = "prob-value";
    percent.textContent = "—";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-button";
    remove.textContent = "×";
    remove.title = "删除这个奖品";
    remove.setAttribute("aria-label", `删除第 ${index + 1} 个奖品`);
    remove.disabled = state.draft.prizes.length <= MIN_PRIZES;
    remove.addEventListener("click", () => {
      if (!editable() || state.draft.prizes.length <= MIN_PRIZES) return;
      state.draft.prizes = state.draft.prizes.filter(
        (item) => item.id !== prize.id
      );
      renderPrizeList();
      updateDraftView();
      el.addButton.focus();
    });

    row.append(color, name, weight, percent, remove);
    return row;
  }

  function addPrize() {
    if (!editable() || state.draft.prizes.length >= MAX_PRIZES) return;
    const index = state.draft.prizes.length;
    state.draft.prizes.push({
      id: `new-${Date.now().toString(36)}-${index}`,
      name: `新奖品 ${index + 1}`,
      weight: "1",
      color: PALETTE[index % PALETTE.length],
    });
    renderPrizeList();
    updateDraftView();
    const rows = el.prizeList.querySelectorAll(".prize-row");
    const lastRow = rows[rows.length - 1];
    const nameInput = lastRow ? lastRow.querySelector(".name-input") : null;
    if (nameInput) {
      nameInput.focus();
      nameInput.select();
    }
  }

  function updateRowProbabilities() {
    const rows = el.prizeList.querySelectorAll(".prize-row");
    const total = totalPositiveWeight();
    state.draft.prizes.forEach((prize, index) => {
      const row = rows[index];
      if (!row) return;
      const weight = numericWeight(prize);
      const percent = row.querySelector(".prob-value");
      if (percent) {
        percent.textContent =
          total > 0 && weight > 0
            ? formatPercent((weight / total) * 100)
            : "—";
      }
      const invalid = !prize.name.trim() || weight <= 0;
      row.classList.toggle("is-invalid", invalid);
      row.title = invalid ? "请填写奖品名称和大于 0 的权重" : "";
    });
  }

  function totalPositiveWeight() {
    return state.draft.prizes.reduce(
      (sum, prize) => sum + numericWeight(prize),
      0
    );
  }

  function numericWeight(prize) {
    const value = Number(prize.weight);
    return Number.isFinite(value) && value > 0 ? value : 0;
  }

  function updateDraftView() {
    updateBranding();
    updateRowProbabilities();
    updateTotalChip();
    drawWheel();
    refreshControls();
  }

  function updateBranding() {
    const title = state.draft.title.trim() || FALLBACK_TITLE;
    el.brandTitle.textContent = title;
    document.title =
      title === FALLBACK_TITLE ? title : `${title} · ${FALLBACK_TITLE}`;
  }

  function updateTotalChip() {
    const count = state.draft.prizes.length;
    const total = totalPositiveWeight();
    el.totalChip.textContent = `${count} 个奖品 · 总权重 ${WEIGHT_FORMAT.format(total)}`;
  }

  // ------------------------------------------------------------- controls

  function editable() {
    return state.ready && !state.spinning && !state.saving;
  }

  function refreshControls() {
    const locked = !state.ready || state.spinning || state.saving;
    const dirty = isDirty();

    el.spinButton.disabled = locked;
    el.spinButton.classList.toggle("is-spinning", state.spinning);
    el.spinLabel.textContent = state.spinning ? "抽奖中" : "抽奖";
    el.spinSub.textContent = state.spinning ? "WAIT" : "SPIN";

    el.panel.toggleAttribute("inert", locked);
    el.panel.classList.toggle("is-locked", locked);
    el.saveButton.textContent = state.saving ? "保存中…" : "保存设置";
    el.saveButton.disabled = locked || !dirty;
    el.revertButton.disabled = locked || !dirty;
    el.addButton.disabled =
      locked || state.draft.prizes.length >= MAX_PRIZES;
    el.titleInput.disabled = locked;

    const disableRemove = state.draft.prizes.length <= MIN_PRIZES;
    el.prizeList.querySelectorAll(".remove-button").forEach((button) => {
      button.disabled = locked || disableRemove;
    });

    el.wheelShell.classList.toggle("is-spinning", state.spinning);
  }

  // --------------------------------------------------------------- drawing

  function observeWheel() {
    if (typeof ResizeObserver === "function") {
      state.resizeObserver = new ResizeObserver(() => resizeWheel());
      state.resizeObserver.observe(el.wheelShell);
    } else {
      window.addEventListener("resize", resizeWheel);
    }
  }

  function resizeWheel() {
    const cssWidth = el.wheelShell.clientWidth;
    if (!cssWidth) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const size = Math.max(240, Math.round(cssWidth * dpr));
    if (el.wheel.width !== size) {
      el.wheel.width = size;
      el.wheel.height = size;
    }
    drawWheel();
  }

  function wheelPrizes() {
    const entries = state.draft.prizes.map((prize, index) => ({
      name: (prize.name || "").trim() || `奖品 ${index + 1}`,
      weight: numericWeight(prize),
      color: isValidHex(prize.color)
        ? prize.color.toLowerCase()
        : PALETTE[index % PALETTE.length],
    }));
    if (!entries.length) return [];

    let total = entries.reduce((sum, entry) => sum + entry.weight, 0);
    if (total <= 0) {
      entries.forEach((entry) => {
        entry.weight = 1;
      });
      total = entries.length;
    }
    return entries.map((entry) => ({
      ...entry,
      fraction: entry.weight / total,
    }));
  }

  function drawWheel() {
    const canvas = el.wheel;
    if (!canvas) return;
    const size = canvas.width;
    if (!size) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const scale = size / BASE_SIZE;
    ctx.setTransform(scale, 0, 0, scale, size / 2, size / 2);
    ctx.clearRect(-BASE_SIZE / 2, -BASE_SIZE / 2, BASE_SIZE, BASE_SIZE);

    const prizes = wheelPrizes();
    if (!prizes.length) return;

    const radius = 326;

    const rim = ctx.createLinearGradient(-radius, -radius, radius, radius);
    rim.addColorStop(0, "#fff0b8");
    rim.addColorStop(0.28, "#c7932f");
    rim.addColorStop(0.52, "#f9dc91");
    rim.addColorStop(1, "#8e611a");
    ctx.beginPath();
    ctx.arc(0, 0, radius + 12, 0, TAU);
    ctx.fillStyle = rim;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(0, 0, radius + 2, 0, TAU);
    ctx.fillStyle = "#111424";
    ctx.fill();

    for (let index = 0; index < 32; index += 1) {
      const angle = (index / 32) * TAU;
      const x = Math.cos(angle) * (radius + 7);
      const y = Math.sin(angle) * (radius + 7);
      ctx.beginPath();
      ctx.arc(x, y, 3.1, 0, TAU);
      ctx.fillStyle = index % 2 === 0 ? "#fff6d2" : "#dba62f";
      ctx.fill();
    }

    let cursor = 0;
    prizes.forEach((prize) => {
      if (prize.fraction <= 0) return;
      const start = -Math.PI / 2 + state.rotation + cursor * TAU;
      const end = start + prize.fraction * TAU;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, radius, start, end);
      ctx.closePath();
      ctx.fillStyle = prize.color;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(9, 11, 20, 0.32)";
      ctx.stroke();
      cursor += prize.fraction;
    });

    const shade = ctx.createRadialGradient(
      -radius * 0.15,
      -radius * 0.2,
      radius * 0.05,
      0,
      0,
      radius * 1.02
    );
    shade.addColorStop(0, "rgba(255, 255, 255, 0.13)");
    shade.addColorStop(0.55, "rgba(255, 255, 255, 0)");
    shade.addColorStop(1, "rgba(0, 0, 0, 0.25)");
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, TAU);
    ctx.fillStyle = shade;
    ctx.fill();

    let labelCursor = 0;
    prizes.forEach((prize) => {
      if (prize.fraction <= 0) return;
      const mid =
        -Math.PI / 2 +
        state.rotation +
        (labelCursor + prize.fraction / 2) * TAU;
      labelCursor += prize.fraction;
      const midNorm = ((mid % TAU) + TAU) % TAU;

      const wedgeWidth = prize.fraction * TAU * radius * 0.62;
      const fontSize = Math.max(11.5, Math.min(23, wedgeWidth * 0.6));
      const maxChars = Math.max(2, Math.floor((radius * 0.52) / fontSize));
      const chars = Array.from(prize.name);
      const label =
        chars.length > maxChars
          ? `${chars.slice(0, Math.max(1, maxChars - 1)).join("")}…`
          : prize.name;

      ctx.save();
      ctx.rotate(mid);
      ctx.font = `700 ${fontSize}px "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif`;
      ctx.fillStyle = readableInk(prize.color);
      ctx.textBaseline = "middle";
      ctx.shadowColor = "rgba(0, 0, 0, 0.28)";
      ctx.shadowBlur = 3;
      const outer = radius - 30;
      if (midNorm > Math.PI / 2 && midNorm < (3 * Math.PI) / 2) {
        ctx.rotate(Math.PI);
        ctx.textAlign = "left";
        ctx.fillText(label, -outer, 0);
      } else {
        ctx.textAlign = "right";
        ctx.fillText(label, outer, 0);
      }
      ctx.restore();
    });

    const hubRadius = 94;
    const hub = ctx.createRadialGradient(-26, -34, 6, 0, 0, hubRadius);
    hub.addColorStop(0, "#2c3150");
    hub.addColorStop(0.62, "#161a2e");
    hub.addColorStop(1, "#0c0f1c");
    ctx.beginPath();
    ctx.arc(0, 0, hubRadius, 0, TAU);
    ctx.fillStyle = hub;
    ctx.fill();
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(246, 196, 83, 0.8)";
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(0, 0, hubRadius - 11, 0, TAU);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.09)";
    ctx.stroke();
  }

  function readableInk(hex) {
    const rgb = hexToRgb(hex);
    if (!rgb) return "#171421";
    const luminance =
      0.2126 * srgbToLinear(rgb.r) +
      0.7152 * srgbToLinear(rgb.g) +
      0.0722 * srgbToLinear(rgb.b);
    const darkLuminance = 0.008;
    const darkContrast =
      (Math.max(luminance, darkLuminance) + 0.05) /
      (Math.min(luminance, darkLuminance) + 0.05);
    const lightContrast = 1.05 / (luminance + 0.05);
    return darkContrast >= lightContrast ? "#171421" : "#fffdf5";
  }

  function srgbToLinear(channel) {
    const value = channel / 255;
    return value <= 0.03928
      ? value / 12.92
      : ((value + 0.055) / 1.055) ** 2.4;
  }

  function hexToRgb(hex) {
    const match = /^#([0-9a-f]{6})$/i.exec(String(hex).trim());
    if (!match) return null;
    const value = Number.parseInt(match[1], 16);
    return {
      r: (value >> 16) & 255,
      g: (value >> 8) & 255,
      b: value & 255,
    };
  }

  function isValidHex(value) {
    return /^#[0-9a-f]{6}$/i.test(String(value).trim());
  }

  // ---------------------------------------------------------------- spin

  async function spin() {
    if (!state.ready || state.spinning || state.saving) return;
    if (isDirty()) {
      showToast("有未保存的修改，请先保存设置再抽奖。", "warning");
      el.saveButton.focus();
      return;
    }

    state.spinning = true;
    refreshControls();
    el.hint.textContent = "转盘转动中，结果由服务端决定…";

    try {
      const payload = await api("/api/spin", { method: "POST" });
      const result = payload.result;
      let targetIndex = state.draft.prizes.findIndex(
        (prize) => prize.id === result.id
      );
      if (targetIndex < 0 && Number.isInteger(result.index)) {
        targetIndex = result.index;
      }
      await animateTo(targetIndex);
      renderHistory(Array.isArray(payload.history) ? payload.history : []);
      el.hint.textContent = "点击转盘中间的按钮，结果由服务端按权重抽取。";
      showResult(result);
    } catch (error) {
      el.hint.textContent = "抽奖失败，请重试。";
      showToast(`抽奖失败：${error.message}`, "error", 6000);
    } finally {
      state.spinning = false;
      refreshControls();
    }
  }

  function animateTo(index) {
    return new Promise((resolve) => {
      const prizes = wheelPrizes();
      if (!prizes.length) {
        resolve();
        return;
      }
      const safeIndex = Math.min(Math.max(0, index), prizes.length - 1);
      const target = prizes[safeIndex];
      let before = 0;
      for (let cursor = 0; cursor < safeIndex; cursor += 1) {
        before += prizes[cursor].fraction;
      }
      const fraction =
        target.fraction > 0 ? target.fraction : 1 / prizes.length;
      const local =
        (before + fraction * (0.16 + Math.random() * 0.68)) * TAU;
      const normalized = ((state.rotation % TAU) + TAU) % TAU;
      const desired = (TAU - (local % TAU)) % TAU;
      let delta = desired - normalized;
      if (delta < 0) delta += TAU;

      const turns = REDUCED_MOTION.matches
        ? 1
        : 5 + Math.floor(Math.random() * 2);
      const from = state.rotation;
      const to = from + turns * TAU + delta;
      const duration = REDUCED_MOTION.matches ? 650 : 4200;
      const started = performance.now();

      function frame(now) {
        const progress = Math.min(1, (now - started) / duration);
        const eased = 1 - (1 - progress) ** 5;
        state.rotation = from + (to - from) * eased;
        drawWheel();
        if (progress < 1) {
          requestAnimationFrame(frame);
        } else {
          state.rotation = to;
          drawWheel();
          resolve();
        }
      }
      requestAnimationFrame(frame);
    });
  }

  function showResult(result) {
    el.resultPrize.textContent = result.name;
    el.resultProb.textContent = `中奖概率 ${formatPercent(result.probability)}`;
    state.returnFocus = document.activeElement;
    state.modalOpen = true;
    el.modal.hidden = false;
    el.page.setAttribute("inert", "");
    document.body.classList.add("modal-open");
    el.closeResult.focus({ preventScroll: true });
  }

  function closeResult() {
    if (!state.modalOpen) return;
    state.modalOpen = false;
    el.modal.hidden = true;
    el.page.removeAttribute("inert");
    document.body.classList.remove("modal-open");
    const target = state.returnFocus;
    state.returnFocus = null;
    if (target && typeof target.focus === "function" && document.contains(target)) {
      target.focus({ preventScroll: true });
    }
  }

  // -------------------------------------------------------------- history

  function renderHistory(history) {
    const items = Array.isArray(history) ? history.slice(0, HISTORY_SHOWN) : [];
    el.historyList.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("li");
      empty.className = "history-empty";
      empty.textContent = "还没有抽奖记录，试试手气吧。";
      el.historyList.appendChild(empty);
      el.historyCount.textContent = "暂无记录";
      return;
    }

    items.forEach((entry) => {
      const item = document.createElement("li");
      item.className = "history-item";
      const dot = document.createElement("span");
      dot.className = "history-dot";
      if (isValidHex(entry.color)) {
        dot.style.setProperty("--dot-color", entry.color);
      }
      const name = document.createElement("span");
      name.className = "history-name";
      name.textContent = String(entry.name || "");
      const time = document.createElement("time");
      time.className = "history-time";
      time.dateTime = String(entry.at || "");
      time.textContent = formatClock(entry.at);
      item.title = `${formatFullTime(entry.at)} · 概率 ${formatPercent(entry.probability)}`;
      item.append(dot, name, time);
      el.historyList.appendChild(item);
    });
    el.historyCount.textContent = `最近 ${items.length} 次`;
  }

  function formatClock(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : TIME_FORMAT.format(date);
  }

  function formatFullTime(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime())
      ? "时间未知"
      : DATETIME_FORMAT.format(date);
  }

  // --------------------------------------------------------------- helpers

  async function api(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      ...options,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message =
        payload && typeof payload.error === "string"
          ? payload.error
          : `请求失败（HTTP ${response.status}）`;
      throw new Error(message);
    }
    if (payload === null) {
      throw new Error("服务器返回了无法解析的响应");
    }
    return payload;
  }

  function setStatus(mode) {
    el.statusPill.dataset.state = mode;
    el.statusText.textContent =
      mode === "online"
        ? "服务已连接"
        : mode === "offline"
          ? "服务未连接"
          : "连接中…";
  }

  function showToast(message, kind = "info", timeout = 3600) {
    if (!el.toast) return;
    window.clearTimeout(state.toastTimer);
    el.toast.textContent = message;
    el.toast.dataset.kind = kind;
    el.toast.classList.add("is-visible");
    state.toastTimer = window.setTimeout(() => {
      el.toast.classList.remove("is-visible");
    }, timeout);
  }

  function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return "—";
    if (number > 0 && number < 0.01) return "<0.01%";
    return `${PERCENT_FORMAT.format(number)}%`;
  }

  function formatWeightInput(value) {
    const number = Number(value);
    return Number.isFinite(number) ? String(number) : "1";
  }

  function cloneFallbackDraft() {
    return {
      title: FALLBACK_TITLE,
      prizes: FALLBACK_PRIZES.map((prize) => ({
        id: prize.id,
        name: prize.name,
        weight: String(prize.weight),
        color: prize.color,
      })),
    };
  }

  function fallbackConfig() {
    return {
      title: FALLBACK_TITLE,
      prizes: FALLBACK_PRIZES.map((prize) => ({ ...prize })),
    };
  }
})();
