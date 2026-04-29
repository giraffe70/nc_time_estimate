const state = {
  profile: null,
  latestBlocks: [],
  latestCharts: null,
  segmentRows: [],
  estimateAbortController: null,
};

const CHART_MARGINS = { top: 28, right: 26, bottom: 48, left: 64 };
const TICK_COUNT = 5;
const ALWAYS_VISIBLE_PROFILE_KEYS = new Set([
  "machine_name",
  "controller_name",
  "kinematic_type",
  "units",
  "time_model.mode",
]);
const CONSTANT_VELOCITY_FIELDS = [
  "feed_unit",
  "max_cut_feed_mm_min",
  "default_cut_feed_mm_min",
  "axes.X.rapid_velocity_mm_min",
  "axes.Y.rapid_velocity_mm_min",
  "axes.Z.rapid_velocity_mm_min",
  "arc_tolerance_mm",
  "controller.dwell_p_unit",
  "controller.dwell_x_unit",
  "event_time.tool_change_sec",
  "event_time.spindle_start_sec",
  "event_time.spindle_stop_sec",
  "event_time.coolant_on_sec",
  "event_time.coolant_off_sec",
  "event_time.optional_stop_sec",
  "cycle.peck_clearance_mm",
  "reference_return.mode",
  "reference_return.fixed_time_sec",
  "reference_return.position.X",
  "reference_return.position.Y",
  "reference_return.position.Z",
];
const TRAPEZOID_FIELDS = [
  ...CONSTANT_VELOCITY_FIELDS,
  "default_cut_acc_mm_s2",
];
const PHASE2_FIELDS = [
  ...TRAPEZOID_FIELDS,
  "rapid_feed_mm_min",
  "default_cut_jerk_mm_s3",
  "arc_chord_tolerance_mm",
  "axes.X.max_velocity_mm_min",
  "axes.X.max_acc_mm_s2",
  "axes.X.max_jerk_mm_s3",
  "axes.Y.max_velocity_mm_min",
  "axes.Y.max_acc_mm_s2",
  "axes.Y.max_jerk_mm_s3",
  "axes.Z.max_velocity_mm_min",
  "axes.Z.max_acc_mm_s2",
  "axes.Z.max_jerk_mm_s3",
  "controller.interpolation_period_ms",
  "controller.lookahead_blocks",
  "controller.junction_tolerance_mm",
  "controller.same_direction_angle_threshold_deg",
  "controller.reverse_angle_threshold_deg",
  "controller.lookahead_max_iterations",
  "controller.velocity_tolerance_mm_s",
  "controller.phase2_max_samples_per_block",
];
const TIME_MODEL_FIELDS = {
  constant_velocity: CONSTANT_VELOCITY_FIELDS,
  trapezoid: TRAPEZOID_FIELDS,
  phase2: PHASE2_FIELDS,
};
const TIME_MODEL_DESCRIPTIONS = {
  constant_velocity: {
    title: "快速估算（固定速度）",
    summary: "切削段以路徑長度除以有效進給估算，Rapid 仍使用各軸 rapid velocity 取最慢軸時間。",
  },
  trapezoid: {
    title: "標準估算（含切削加減速）",
    summary: "在固定速度估算外，切削段會使用「切削加速度」估算起步加速與結尾減速，短線段會自動反映速度拉不上去的時間。",
  },
  phase2: {
    title: "精準動態估算（含加減速與轉角降速）",
    summary: "用更接近真實機台的方式估算：會考慮各軸速度能力、加減速平順度、轉角降速、連續短線段與圓弧路徑，因此適合正式比較與瓶頸分析。",
  },
};

const statusEl = document.querySelector("#status");
const estimateForm = document.querySelector("#estimate-form");
const compareForm = document.querySelector("#compare-form");
const profileInputs = Array.from(document.querySelectorAll("[data-profile-key]"));
const estimateTimeModelSelect = document.querySelector("#estimate-time-model");
const profileTimeModelSelect = document.querySelector('[data-profile-key="time_model.mode"]');

document.addEventListener("DOMContentLoaded", async () => {
  wireTabs();
  wireForms();
  await loadProfile();
});

function wireTabs() {
  for (const button of document.querySelectorAll(".tab")) {
    button.addEventListener("click", () => {
      activate(button, ".tab", ".tab-panel", "tab");
      if (button.dataset.tab === "blocks") {
        renderBlocks(state.latestBlocks);
      }
      if (button.dataset.tab === "charts") {
        renderCharts(state.latestCharts);
      }
    });
  }
}

function activate(button, buttonSelector, panelSelector, dataKey) {
  for (const item of document.querySelectorAll(buttonSelector)) {
    item.classList.toggle("active", item === button);
  }
  for (const panel of document.querySelectorAll(panelSelector)) {
    const id = panel.id ? panel.id.replace("tab-", "") : panel.dataset.toolPanel;
    panel.classList.toggle("active", id === button.dataset[dataKey]);
  }
}

function wireForms() {
  document.querySelector("#load-profile-button").addEventListener("click", async () => {
    const fileInput = document.querySelector("#estimate-profile-file");
    await loadProfile(fileInput.files[0]);
  });
  document.querySelector("#estimate-profile-file").addEventListener("change", async (event) => {
    if (event.target.files[0]) {
      await loadProfile(event.target.files[0]);
    }
  });
  estimateTimeModelSelect.addEventListener("change", () => {
    syncTimeModelControls(estimateTimeModelSelect.value);
    applyTimeModelVisibility();
  });
  profileTimeModelSelect.addEventListener("change", () => {
    syncTimeModelControls(profileTimeModelSelect.value);
    applyTimeModelVisibility();
  });
  estimateForm.addEventListener("submit", submitEstimate);
  compareForm.addEventListener("submit", submitCompare);
  document.querySelector("#estimate-stop-button").addEventListener("click", stopEstimate);
  for (const checkbox of ["#filter-slower", "#filter-low-speed", "#filter-unit"].map((id) => document.querySelector(id))) {
    checkbox.addEventListener("change", () => renderSegments(state.segmentRows));
  }
}

async function loadProfile(file) {
  setStatus("Loading profile");
  const payload = new FormData();
  if (file) {
    payload.append("profile", file);
  }
  try {
    const data = await postJson("/api/profile/parse", payload);
    state.profile = data.profile;
    populateProfile(data.profile);
    setStatus("Ready");
  } catch (error) {
    console.error(error);
    setStatus("Error");
  }
}

async function submitEstimate(event) {
  event.preventDefault();
  stopEstimate({ silent: true });
  setStatus("Estimating");
  const button = document.querySelector("#estimate-button");
  const stopButton = document.querySelector("#estimate-stop-button");
  const controller = new AbortController();
  state.estimateAbortController = controller;
  button.disabled = true;
  stopButton.disabled = false;
  try {
    const payload = new FormData(estimateForm);
    payload.append("profile_data", JSON.stringify(collectProfile()));
    const data = await postJson("/api/estimate", payload, { signal: controller.signal });
    if (controller.signal.aborted) return;
    renderEstimate(data);
    setStatus("Done");
  } catch (error) {
    if (error.name === "AbortError") {
      setStatus("Stopped");
      return;
    }
    console.error(error);
    setStatus("Error");
  } finally {
    if (state.estimateAbortController === controller) {
      state.estimateAbortController = null;
      button.disabled = false;
      stopButton.disabled = true;
    }
  }
}

function stopEstimate(options = {}) {
  if (!state.estimateAbortController) return;
  state.estimateAbortController.abort();
  state.estimateAbortController = null;
  document.querySelector("#estimate-button").disabled = false;
  document.querySelector("#estimate-stop-button").disabled = true;
  if (!options.silent) {
    setStatus("Stopped");
  }
}

async function submitCompare(event) {
  event.preventDefault();
  setStatus("Comparing");
  const button = document.querySelector("#compare-button");
  button.disabled = true;
  try {
    const payload = new FormData(compareForm);
    payload.append("profile_data", JSON.stringify(collectProfile()));
    const data = await postJson("/api/compare", payload);
    renderCompare(data);
    setStatus("Done");
  } catch (error) {
    console.error(error);
    setStatus("Error");
  } finally {
    button.disabled = false;
  }
}

function renderEstimate(data) {
  const summary = data.summary || {};
  const summaryLines = [
    `Total time: ${summary.total_time_text || "-"} (${fmt(summary.total_time_sec)} s)`,
    `Rapid time: ${fmt(summary.rapid_time_sec)} s`,
    `Cutting time: ${fmt(summary.cutting_time_sec)} s`,
    `Arc time: ${fmt(summary.arc_time_sec)} s`,
    `Auxiliary time: ${fmt(summary.auxiliary_time_sec)} s`,
    `Total length: ${fmt(summary.total_length_mm)} mm`,
    `Warnings: ${summary.warning_count || 0}`,
    `Feed unit: ${summary.feed_unit_effective || "-"}`,
    `Feed sanity critical: ${summary.feed_sanity_critical_count || 0}`,
  ];
  const sanityWarning = document.querySelector("#estimate-sanity-warning").checked;
  const warnings = [...(data.warnings || [])];
  if (sanityWarning && summary.feed_sanity_critical_count) {
    warnings.push("Feed sanity found critical issues. Check feed unit and feed mode settings.");
  }
  document.querySelector("#estimate-summary").textContent = summaryLines.join("\n");
  document.querySelector("#estimate-warnings").textContent = warnings.join("\n") || "None";
  renderDownloads("#estimate-downloads", data.download_urls || {});
  state.latestBlocks = data.blocks || [];
  state.latestCharts = data.charts || null;
  renderBlocks(state.latestBlocks);
  renderCharts(state.latestCharts);
}

function renderCompare(data) {
  const summary = data.summary || {};
  const delta = Number(summary.total_time_delta_sec || 0);
  const ratio = Number(summary.regression_ratio || 0);
  const metrics = [
    ["Original total time", `${summary.original_total_time_text || "-"} (${fmt(summary.original_total_time_sec)} s)`],
    ["Optimized total time", `${summary.optimized_total_time_text || "-"} (${fmt(summary.optimized_total_time_sec)} s)`],
    ["Time delta", `${delta >= 0 ? "+" : ""}${fmt(delta)} s`, delta > 0 ? "bad" : "good"],
    ["Regression Ratio", `${(ratio * 100).toFixed(3)}%`, summary.is_regression ? "bad" : "good"],
    ["Geometry Match", yesNo(summary.geometry_match), summary.geometry_match ? "good" : "bad"],
    ["Feed Sanity", `${summary.feed_sanity_critical_count || 0} critical / ${summary.feed_sanity_issue_count || 0} issues`, summary.feed_sanity_critical_count ? "bad" : ""],
  ];
  document.querySelector("#compare-metrics").replaceChildren(...metrics.map(([label, value, stateName]) => metricNode(label, value, stateName)));
  renderDownloads("#compare-downloads", data.download_urls || {});
  state.segmentRows = (data.comparison && data.comparison.segment_differences) || [];
  renderSegments(state.segmentRows);
  state.latestBlocks = data.optimized_blocks || [];
  state.latestCharts = data.charts || null;
  renderBlocks(state.latestBlocks);
  renderCharts(state.latestCharts);
}

function renderSegments(rows) {
  const filterSlower = document.querySelector("#filter-slower").checked;
  const filterLow = document.querySelector("#filter-low-speed").checked;
  const filterUnit = document.querySelector("#filter-unit").checked;
  const visible = rows.filter((row) => {
    const delta = Number(row.delta_time_sec || 0);
    if (filterSlower && delta <= 0) return false;
    if (filterLow && !row.is_low_speed_anomaly) return false;
    if (filterUnit && !row.is_unit_suspect) return false;
    return true;
  });
  const nodes = visible.map((row) => {
    const tr = document.createElement("tr");
    const delta = Number(row.delta_time_sec || 0);
    if (delta > 0) tr.classList.add("slower");
    if (row.is_low_speed_anomaly || row.is_unit_suspect) tr.classList.add("alert");
    const values = [
      row.line_no,
      row.original_feedrate,
      row.optimized_feedrate,
      row.original_effective_feed_mm_min,
      row.optimized_effective_feed_mm_min,
      fmt(row.original_time_sec),
      fmt(row.optimized_time_sec),
      `${delta >= 0 ? "+" : ""}${fmt(delta)}`,
      yesNo(row.is_low_speed_anomaly),
      yesNo(row.is_unit_suspect),
      row.match_status,
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value ?? "";
      if (value === "Yes") td.className = "bool-yes";
      tr.appendChild(td);
    }
    return tr;
  });
  document.querySelector("#segments-body").replaceChildren(...(nodes.length ? nodes : [emptyRow(11)]));
}

function renderBlocks(rows) {
  const table = document.querySelector("#blocks-table");
  if (!rows || !rows.length) {
    table.replaceChildren(emptyRow(1));
    return;
  }
  const headers = Object.keys(rows[0]);
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.textContent = header;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const header of headers) {
      const td = document.createElement("td");
      td.textContent = formatCell(row[header]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.replaceChildren(thead, tbody);
}

function renderCharts(charts) {
  drawToolpath(document.querySelector("#toolpath-chart"), charts && charts.xy_toolpath);
  drawBlockTimes(document.querySelector("#blocktime-chart"), charts && charts.block_times);
  drawVelocity(document.querySelector("#velocity-chart"), charts && charts.phase2_dynamic_samples);
}

function drawToolpath(canvas, segments) {
  const ctx = clearCanvas(canvas, "No toolpath");
  if (!segments || !segments.length) return;
  const points = [];
  for (const segment of segments) {
    if (Array.isArray(segment.start) && Array.isArray(segment.end)) {
      points.push(toPoint3d(segment.start), toPoint3d(segment.end));
    }
  }
  if (!points.length) return;

  const bounds3d = boundsOf3d(points);
  const projected = points.map((point) => project3d(point, bounds3d));
  const projectionBounds = boundsOf(
    projected.map((point) => point.x),
    projected.map((point) => point.y),
  );
  const area = chartArea(canvas);
  const scaleProjected = (point) => scalePoint(point.x, point.y, projectionBounds, area);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  draw3dAxes(ctx, bounds3d, projectionBounds, area);
  ctx.strokeStyle = "#0f766e";
  ctx.lineWidth = 1.7;
  ctx.beginPath();
  for (const segment of segments) {
    if (!Array.isArray(segment.start) || !Array.isArray(segment.end)) continue;
    const start = scaleProjected(project3d(toPoint3d(segment.start), bounds3d));
    const end = scaleProjected(project3d(toPoint3d(segment.end), bounds3d));
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
  }
  ctx.stroke();
}

function drawBlockTimes(canvas, rows) {
  const ctx = clearCanvas(canvas, "No block data");
  if (!rows || !rows.length) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const values = rows.map((row) => Number(row.estimated_time_sec || 0));
  const xs = rows.map((row, index) => Number(row.block_index ?? index));
  const bounds = boundsOf(xs, values);
  bounds.minY = 0;
  const area = chartArea(canvas);
  drawAxes(ctx, area, bounds, "Block index", "Time (s)");
  const gap = 1;
  const barWidth = Math.max(1, area.width / values.length - gap);
  ctx.fillStyle = "#334155";
  values.forEach((value, index) => {
    const point = scalePoint(xs[index], value, bounds, area);
    const zero = scalePoint(xs[index], 0, bounds, area);
    ctx.fillRect(area.left + index * (barWidth + gap), point.y, barWidth, zero.y - point.y);
  });
}

function drawVelocity(canvas, rows) {
  const ctx = clearCanvas(canvas, "No Phase 2 velocity");
  if (!rows || !rows.length) return;
  const sampled = downsample(rows, 2000);
  const xs = sampled.map((row) => Number(row.time_sec || 0));
  const ys = sampled.map((row) => Number(row.velocity_mm_s || 0));
  const bounds = boundsOf(xs, ys);
  bounds.minY = Math.min(0, bounds.minY);
  const area = chartArea(canvas);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawAxes(ctx, area, bounds, "Time (s)", "Velocity (mm/s)");
  ctx.strokeStyle = "#a15c07";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  sampled.forEach((row, index) => {
    const point = scalePoint(Number(row.time_sec || 0), Number(row.velocity_mm_s || 0), bounds, area);
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.stroke();
}

function drawAxes(ctx, area, bounds, xLabel, yLabel) {
  ctx.save();
  ctx.strokeStyle = "#cad3cd";
  ctx.fillStyle = "#5f6f67";
  ctx.lineWidth = 1;
  ctx.font = "12px Arial";
  ctx.beginPath();
  ctx.moveTo(area.left, area.top);
  ctx.lineTo(area.left, area.bottom);
  ctx.lineTo(area.right, area.bottom);
  ctx.stroke();

  for (const tick of ticks(bounds.minX, bounds.maxX, TICK_COUNT)) {
    const point = scalePoint(tick, bounds.minY, bounds, area);
    ctx.beginPath();
    ctx.moveTo(point.x, area.bottom);
    ctx.lineTo(point.x, area.bottom + 5);
    ctx.stroke();
    ctx.fillText(formatTick(tick), point.x - 12, area.bottom + 20);
  }
  for (const tick of ticks(bounds.minY, bounds.maxY, TICK_COUNT)) {
    const point = scalePoint(bounds.minX, tick, bounds, area);
    ctx.beginPath();
    ctx.moveTo(area.left - 5, point.y);
    ctx.lineTo(area.left, point.y);
    ctx.stroke();
    ctx.fillText(formatTick(tick), 8, point.y + 4);
  }
  ctx.fillText(xLabel, area.left + area.width / 2 - 28, ctx.canvas.height - 12);
  ctx.save();
  ctx.translate(16, area.top + area.height / 2 + 32);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(yLabel, 0, 0);
  ctx.restore();
  ctx.restore();
}

function draw3dAxes(ctx, bounds3d, projectionBounds, area) {
  const origin = { x: bounds3d.minX, y: bounds3d.minY, z: bounds3d.minZ };
  const axes = [
    ["X", { ...origin, x: bounds3d.maxX }, "#b42318"],
    ["Y", { ...origin, y: bounds3d.maxY }, "#0f766e"],
    ["Z", { ...origin, z: bounds3d.maxZ }, "#334155"],
  ];
  const originPoint = scalePoint(...projectPointTuple(origin, bounds3d), projectionBounds, area);
  ctx.save();
  ctx.lineWidth = 1.2;
  ctx.font = "12px Arial";
  for (const [label, endPoint, color] of axes) {
    const projectedEnd = scalePoint(...projectPointTuple(endPoint, bounds3d), projectionBounds, area);
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(originPoint.x, originPoint.y);
    ctx.lineTo(projectedEnd.x, projectedEnd.y);
    ctx.stroke();
    ctx.fillText(label, projectedEnd.x + 6, projectedEnd.y + 4);
  }
  ctx.fillStyle = "#5f6f67";
  ctx.fillText("X / Y / Z axes", area.left, area.top - 8);
  ctx.restore();
}

function populateProfile(profile) {
  for (const input of profileInputs) {
    const value = getPath(profile, input.dataset.profileKey);
    input.value = value ?? "";
  }
  syncTimeModelControls(getPath(profile, "time_model.mode") || estimateTimeModelSelect.value);
  applyTimeModelVisibility();
}

function collectProfile() {
  const profile = {};
  for (const input of profileInputs) {
    const key = input.dataset.profileKey;
    let value = input.value;
    if (input.type === "number") {
      value = Number(value);
    }
    setPath(profile, key, value);
  }
  return profile;
}

function syncTimeModelControls(mode) {
  if (!TIME_MODEL_FIELDS[mode]) return;
  estimateTimeModelSelect.value = mode;
  profileTimeModelSelect.value = mode;
}

function applyTimeModelVisibility() {
  const mode = estimateTimeModelSelect.value;
  const fields = new Set(TIME_MODEL_FIELDS[mode] || TIME_MODEL_FIELDS.constant_velocity);
  for (const input of profileInputs) {
    const key = input.dataset.profileKey;
    const row = input.closest("label");
    if (!row) continue;
    row.hidden = !ALWAYS_VISIBLE_PROFILE_KEYS.has(key) && !fields.has(key);
  }
  renderTimeModelHelp(mode, fields);
}

function renderTimeModelHelp(mode, fields) {
  const description = TIME_MODEL_DESCRIPTIONS[mode] || TIME_MODEL_DESCRIPTIONS.constant_velocity;
  document.querySelector("#time-model-help-title").textContent = description.title;
  document.querySelector("#time-model-help-summary").textContent = description.summary;
  // document.querySelector("#time-model-help-fields").textContent = `需設定參數：${Array.from(fields).map(readableProfileKey).join(", ")}`;
}

function readableProfileKey(key) {
  const labels = {
    default_cut_acc_mm_s2: "切削加速度",
    default_cut_jerk_mm_s3: "切削加減速平順度",
    max_cut_feed_mm_min: "切削進給上限",
    default_cut_feed_mm_min: "預設切削進給",
    rapid_feed_mm_min: "快速移動整體上限",
    arc_tolerance_mm: "圓弧幾何容許誤差",
    arc_chord_tolerance_mm: "圓弧切分精度",
    feed_unit: "進給單位",
    "cycle.peck_clearance_mm": "鑽孔循環退刀距離",
  };
  if (labels[key]) return labels[key];
  if (key.startsWith("axes.") && key.endsWith(".rapid_velocity_mm_min")) return `${key.slice(5, 6)} 軸快速速度`;
  if (key.startsWith("axes.") && key.endsWith(".max_velocity_mm_min")) return `${key.slice(5, 6)} 軸最高速度`;
  if (key.startsWith("axes.") && key.endsWith(".max_acc_mm_s2")) return `${key.slice(5, 6)} 軸最大加速度`;
  if (key.startsWith("axes.") && key.endsWith(".max_jerk_mm_s3")) return `${key.slice(5, 6)} 軸加減速平順度`;
  if (key.startsWith("controller.")) return key.replace("controller.", "控制器 ");
  if (key.startsWith("event_time.")) return key.replace("event_time.", "輔助事件 ");
  if (key.startsWith("reference_return.")) return key.replace("reference_return.", "原點復歸 ");
  return key;
}

function getPath(object, key) {
  return key.split(".").reduce((current, part) => current && current[part], object);
}

function setPath(object, key, value) {
  const parts = key.split(".");
  let current = object;
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      current[part] = value;
      return;
    }
    current[part] = current[part] || {};
    current = current[part];
  });
}

async function postJson(url, payload, options = {}) {
  const response = await fetch(url, { method: "POST", body: payload, signal: options.signal });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

function renderDownloads(selector, urls) {
  const labels = [["xlsx", "Excel"], ["html", "HTML"]];
  const links = [];
  for (const [fmtName, label] of labels) {
    if (!urls[fmtName]) continue;
    const link = document.createElement("a");
    link.href = urls[fmtName];
    link.textContent = label;
    links.push(link);
  }
  const container = document.querySelector(selector);
  if (links.length > 0) {
    const title = document.createElement("span");
    title.className = "downloads-title";
    title.textContent = "匯出報表";
    container.replaceChildren(title, ...links);
  } else {
    container.replaceChildren();
  }
  container.hidden = links.length === 0;
}

function metricNode(label, value, stateName) {
  const node = document.createElement("div");
  node.className = `metric ${stateName || ""}`.trim();
  const labelNode = document.createElement("div");
  labelNode.className = "label";
  labelNode.textContent = label;
  const valueNode = document.createElement("div");
  valueNode.className = "value";
  valueNode.textContent = value;
  node.append(labelNode, valueNode);
  return node;
}

function emptyRow(colSpan) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colSpan;
  td.textContent = "No rows";
  tr.appendChild(td);
  return tr;
}

function clearCanvas(canvas, message) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#6b7280";
  ctx.font = "14px Arial";
  ctx.fillText(message, 20, 28);
  return ctx;
}

function chartArea(canvas) {
  return {
    left: CHART_MARGINS.left,
    top: CHART_MARGINS.top,
    right: canvas.width - CHART_MARGINS.right,
    bottom: canvas.height - CHART_MARGINS.bottom,
    width: canvas.width - CHART_MARGINS.left - CHART_MARGINS.right,
    height: canvas.height - CHART_MARGINS.top - CHART_MARGINS.bottom,
  };
}

function boundsOf(xs, ys) {
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    minX,
    maxX: maxX === minX ? minX + 1 : maxX,
    minY,
    maxY: maxY === minY ? minY + 1 : maxY,
  };
}

function boundsOf3d(points) {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const zs = points.map((point) => point.z);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const minZ = Math.min(...zs);
  const maxZ = Math.max(...zs);
  return {
    minX,
    maxX: maxX === minX ? minX + 1 : maxX,
    minY,
    maxY: maxY === minY ? minY + 1 : maxY,
    minZ,
    maxZ: maxZ === minZ ? minZ + 1 : maxZ,
  };
}

function scalePoint(x, y, bounds, area) {
  return {
    x: area.left + (x - bounds.minX) / (bounds.maxX - bounds.minX) * area.width,
    y: area.bottom - (y - bounds.minY) / (bounds.maxY - bounds.minY) * area.height,
  };
}

function toPoint3d(point) {
  return {
    x: Number(point[0] || 0),
    y: Number(point[1] || 0),
    z: Number(point[2] || 0),
  };
}

function project3d(point, bounds) {
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;
  const centerZ = (bounds.minZ + bounds.maxZ) / 2;
  const x = point.x - centerX;
  const y = point.y - centerY;
  const z = point.z - centerZ;
  return {
    x: (x - y) * 0.866,
    y: (x + y) * 0.5 - z,
  };
}

function projectPointTuple(point, bounds) {
  const projected = project3d(point, bounds);
  return [projected.x, projected.y];
}

function ticks(min, max, count) {
  if (count <= 1) return [min];
  const step = (max - min) / (count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

function formatTick(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (Math.abs(number) >= 1000) return number.toFixed(0);
  if (Math.abs(number) >= 10) return number.toFixed(1);
  return number.toFixed(2);
}

function downsample(rows, limit) {
  if (rows.length <= limit) return rows;
  const step = (rows.length - 1) / (limit - 1);
  return Array.from({ length: limit }, (_, index) => rows[Math.round(index * step)]);
}

function formatCell(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return value ?? "";
}

function fmt(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(3);
}

function yesNo(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "-";
}

function setStatus(text) {
  statusEl.textContent = text;
}
