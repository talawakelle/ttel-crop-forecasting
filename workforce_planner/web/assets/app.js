const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const fmt = new Intl.NumberFormat("en-LK", { maximumFractionDigits: 1 });

let profile = null;
let model = null;
let allocationResponse = null;
let allocationRequest = null;
let frontierResponse = null;
let practicalResponse = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 3200);
}

function setStep(number) {
  $$(".step").forEach((node, index) => node.classList.toggle("active", index < number));
}

function populateControls() {
  const dates = [...profile.dates].reverse();
  $("#template-date").innerHTML = dates.map((item) => {
    const selected = item.date === profile.default_template_date ? "selected" : "";
    const partial = item.incomplete ? " · partial day" : "";
    return `<option value="${esc(item.date)}" ${selected}>${esc(item.date)} · ${fmt.format(item.total_kg)} kg${partial}</option>`;
  }).join("");
  $("#division").innerHTML = `<option value="">All divisions</option>${profile.divisions.map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("")}`;
  const afterHistory = new Date(`${profile.date_max}T00:00:00`);
  afterHistory.setDate(afterHistory.getDate() + 1);
  const localToday = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  const iso = (value) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
  const earliest = iso(afterHistory);
  $("#planning-date").min = earliest;
  $("#planning-date").value = iso(localToday) < earliest ? earliest : iso(localToday);
  $("#about-employees").textContent = fmt.format(profile.employee_count);
  $("#about-fields").textContent = fmt.format(profile.field_count);
  $("#about-days").textContent = fmt.format(profile.dates.length);
}

function populateModelStatus() {
  const status = $("#model-status");
  const forecast = model.productivity_forecast || {};
  status.classList.toggle("ready", Boolean(forecast.ready));
  if (forecast.ready && model.trained && model.hybrid_ready) {
    status.querySelector("b").textContent = "Forecast + approved RL + optimizer ready";
  } else if (forecast.ready && model.hybrid_ready) {
    status.querySelector("b").textContent = "Forecast + optimizer ready · RL training required";
  } else if (forecast.ready) {
    status.querySelector("b").textContent = "Forecast + standard planner ready";
  } else {
    status.querySelector("b").textContent = model.hybrid_ready
      ? "Optimizer ready · forecast fallback active"
      : "Safe standard planner ready";
  }
  const forecastText = forecast.ready
    ? `${forecast.method}. Untouched test MAE: ${fmt.format(forecast.test_mae_kg)} kg versus ${fmt.format(forecast.baseline_test_mae_kg)} kg for the historical baseline. Forecast horizon: ${fmt.format(forecast.maximum_forecast_horizon_days)} days.`
    : "The approved employee-productivity forecast is unavailable, so historical medians are being used.";
  const crop = model.crop_forecast || {};
  const cropText = crop.ready
    ? (crop.stale_as_of_today
      ? `Merged crop forecast is loaded but expired on ${crop.forecast_end}. Import a refreshed forecast before selecting forecast demand.`
      : `Merged crop forecast: ${crop.forecast_start} to ${crop.forecast_end}. It predicts estate-week crop and scales the selected field schedule template.`)
    : "No merged estate crop forecast is loaded.";
  const rlText = model.trained
    ? "The RL policy passed its paired baseline and hard-constraint gates."
    : "No compatible approved schema-3 RL policy is active; hybrid planning safely uses the optimizer and forecast-aware baseline.";
  const optimizerText = model.hybrid_ready
    ? "The CP-SAT optimizer is available."
    : "The CP-SAT optimizer is unavailable on this installation.";
  const dynamicText = model.dynamic_rl?.compatible
    ? "The older full dynamic RL comparison model is approved."
    : "The older full dynamic RL model is inactive.";
  const selectiveText = model.selective_hybrid_rl?.compatible
    ? "Selective hybrid RL is approved for simulation: dynamic greedy remains primary, RL only reviews uncertain moves, and a conservative fallback is active."
    : "Selective hybrid RL requires GPU training and untouched-test approval. Until then, the planner safely uses CP-SAT and dynamic greedy without RL.";
  $("#model-summary").textContent = `${forecastText} ${cropText} ${rlText} ${optimizerText} ${dynamicText} ${selectiveText}`;
}

function plainPlanMessage(plan) {
  if (plan.policy === "cp-sat-optimal") {
    return "The mathematical optimizer proved that this is the maximum predicted crop coverage possible under the selected attendance, capacity and division rules.";
  }
  if (plan.policy === "cp-sat-feasible") {
    return "The mathematical optimizer found the strongest feasible plan within its time limit, and it outperformed the other checked methods.";
  }
  if (plan.policy === "baseline-safety-gate") {
    return "The standard allocation method produced the stronger feasible result for these conditions, so it was selected automatically. The RL option was still checked in the background.";
  }
  if (plan.policy === "forecast-aware-maskable-ppo" || plan.policy === "maskable-ppo") {
    return "The forecast-aware reinforcement-learning plan passed all rules and outperformed the checked alternatives for these conditions.";
  }
  return "The standard productivity-based allocation was selected for this plan.";
}

function renderFields(fields) {
  $("#field-count").textContent = `${fields.length} active fields`;
  $("#field-body").innerHTML = fields.length ? fields.map((field) => `
    <tr>
      <td><strong>${esc(field.field_id)}</strong></td>
      <td>${fmt.format(field.assigned_workers)} <small>of ${fmt.format(field.worker_capacity)} capacity</small></td>
      <td>${fmt.format(field.predicted_kg)} kg</td>
      <td>${fmt.format(field.target_kg)} kg</td>
      <td class="coverage-cell"><span class="mini-bar"><i style="width:${Math.min(100, field.coverage_pct)}%"></i></span><b>${fmt.format(field.coverage_pct)}%</b></td>
    </tr>
  `).join("") : `<tr><td colspan="5" class="empty-row">No active fields found.</td></tr>`;
}

function renderAssignments() {
  if (!allocationResponse) return;
  const query = $("#assignment-search").value.trim().toLowerCase();
  const assignments = allocationResponse.selected.assignments.filter((row) => {
    const text = `${row.employee_id} ${row.home_division} ${row.field_id}`.toLowerCase();
    return !query || text.includes(query);
  });
  $("#assignment-body").innerHTML = assignments.length ? assignments.map((row) => `
    <tr>
      <td><strong>${esc(row.employee_id)}</strong></td>
      <td>${esc(row.home_division)}</td>
      <td>${esc(row.field_id)}</td>
      <td>${fmt.format(row.predicted_kg)} kg <small>±${fmt.format(row.forecast_uncertainty_kg)} kg</small></td>
      <td>${fmt.format((row.forecast_confidence || 0) * 100)}% · ${esc(row.confidence)}</td>
    </tr>
  `).join("") : `<tr><td colspan="5" class="empty-row">No matching employees.</td></tr>`;
}

function renderComparison(payload) {
  const comparison = payload.comparison;
  if (!comparison) {
    $("#comparison-text").textContent = "Only the selected feasible plan was calculated.";
    return;
  }
  const methods = comparison.methods || {};
  const labels = { optimizer: "Mathematical optimizer", rl: "RL", standard: "Standard method" };
  const parts = ["optimizer", "rl", "standard"].flatMap((name) => {
    const method = methods[name];
    return method ? [`${labels[name]} ${fmt.format(method.coverage_pct)}%`] : [];
  });
  const selectedLabel = labels[comparison.selected_method] || comparison.selected_method;
  let proof = "";
  const optimization = methods.optimizer?.optimization;
  if (optimization) {
    proof = optimization.optimality_proven
      ? ` Maximum coverage was mathematically proven in ${fmt.format(optimization.solve_seconds)} seconds.`
      : ` The solver found a feasible result within ${fmt.format(optimization.time_limit_seconds)} seconds; its remaining theoretical gap is at most ${fmt.format(optimization.optimality_gap_pct_points)} points.`;
  }
  const errors = Object.entries(comparison.errors || {})
    .filter(([, value]) => value)
    .map(([name, value]) => `${labels[name] || name}: ${value}`);
  const errorText = errors.length ? ` Not available: ${errors.join("; ")}.` : "";
  const forecast = payload.forecast || payload.selected?.forecast || {};
  const forecastText = forecast.eligible_for_planning_date
    ? ` Productivity values came from the ${forecast.method} (${fmt.format(forecast.test_mae_kg)} kg untouched-test MAE; ${fmt.format(forecast.forecast_horizon_days)}-day horizon).`
    : " Productivity values used the historical median fallback because the forecast was unavailable or outside its safety horizon.";
  $("#comparison-text").textContent = `${parts.join(" · ")}. Selected: ${selectedLabel}. All displayed plans passed the hard-rule check.${proof}${forecastText}${errorText}`;
}

function renderCoverageGoal(goal) {
  const panel = $("#goal-panel");
  panel.className = `goal-panel ${esc(goal?.status || "analysis_unavailable")}`;
  if (!goal) {
    $("#goal-title").textContent = "Coverage-goal check unavailable";
    $("#goal-message").textContent = "The allocation is still valid, but no goal analysis was returned.";
    return;
  }
  const labels = {
    goal_met: "GOAL MET",
    more_attendance_needed: "STAFFING NEEDED",
    cross_division_needed: "TRANSFER NEEDED",
    capacity_gap: "NOT FEASIBLE",
    analysis_unavailable: "CHECK UNAVAILABLE",
  };
  $("#goal-title").textContent = goal.headline || "Coverage-goal result";
  $("#goal-badge").textContent = labels[goal.status] || "CHECKED";
  $("#goal-message").textContent = goal.current_shortfall_kg > 0
    ? `The current plan is ${fmt.format(goal.current_shortfall_kg)} kg short of the ${fmt.format(goal.goal_coverage_pct)}% goal.`
    : "The current plan reaches the requested coverage goal.";
  $("#goal-current").textContent = goal.current_coverage_pct == null ? "—" : `${fmt.format(goal.current_coverage_pct)}%`;
  $("#goal-target").textContent = goal.goal_coverage_pct == null ? "—" : `${fmt.format(goal.goal_coverage_pct)}%`;
  $("#goal-workers").textContent = goal.minimum_additional_workers == null
    ? goal.estimated_external_workers ? `~${fmt.format(goal.estimated_external_workers)} external` : "Not enough"
    : goal.minimum_additional_workers === 0
      ? "None"
      : `+${fmt.format(goal.minimum_additional_workers)}${goal.minimum_additional_workers_proven ? " exact" : " verified"}`;
  $("#goal-attendance").textContent = goal.required_attendance_pct == null
    ? "—" : `${fmt.format(goal.required_attendance_pct)}%`;
  $("#goal-actions").innerHTML = (goal.next_actions || []).map((item) => `<li>${esc(item)}</li>`).join("");
  const gaps = goal.field_shortfalls || [];
  const fields = $("#goal-fields");
  fields.hidden = !gaps.length;
  fields.innerHTML = gaps.length
    ? `<b>Largest current field gaps:</b> ${gaps.map((item) => `${esc(item.field_id)} (${fmt.format(item.gap_kg)} kg)`).join(" · ")}`
    : "";
  const exportButton = $("#goal-export-btn");
  exportButton.hidden = !(goal.goal_plan?.assignments?.length);
  exportButton.textContent = goal.status === "goal_met"
    ? "Download goal plan CSV"
    : "Download goal staffing CSV";
}

function buildRequestPayload() {
  return {
    template_date: $("#template-date").value,
    planning_date: $("#planning-date").value,
    division: $("#division").value || null,
    policy: "hybrid",
    attendance_rate: Number($("#attendance").value) / 100,
    demand_multiplier: Number($("#demand").value) / 100,
    demand_source: $("#demand-source").value,
    forecast_risk: $("#forecast-risk").value,
    same_division_only: $("#same-division").checked,
    coverage_goal_pct: Number($("#coverage-goal").value),
    seed: 42,
  };
}

function renderFrontier(payload) {
  frontierResponse = payload;
  const frontier = payload?.frontier;
  if (!frontier?.ready) {
    throw new Error(frontier?.error || "Coverage frontier is unavailable");
  }
  const labels = {
    current: "Current rules",
    flexible_divisions: "Flexible divisions",
    full_attendance: "Full attendance",
    full_attendance_flexible: "Full attendance + flexible divisions",
  };
  $("#frontier-options").innerHTML = frontier.options.map((option) => {
    const isBest = option.name === frontier.best_option;
    const proof = option.optimality_proven ? "Maximum proven" : "Best found in time limit";
    const gain = option.improvement_pct_points > 0
      ? `+${fmt.format(option.improvement_pct_points)} points`
      : "Current baseline";
    const staffing = option.additional_assigned_workers > 0
      ? `+${fmt.format(option.additional_assigned_workers)} additional assigned`
      : "No additional assigned workers";
    return `<article class="frontier-option ${isBest ? "best" : ""}">
      <div><span>${esc(isBest ? "STRONGEST CHECKED" : proof)}</span><strong>${esc(labels[option.name] || option.label)}</strong></div>
      <b>${fmt.format(option.coverage_pct)}%</b>
      <small>${esc(gain)} · ${esc(staffing)} · ${fmt.format(option.cross_division_assignments)} transfers</small>
      <ul>${option.conditions.map((condition) => `<li>${esc(condition)}</li>`).join("")}</ul>
      <em>${option.constraint_violations === 0 ? "0 rule violations" : `${fmt.format(option.constraint_violations)} violation(s)`} · ${esc(proof)}</em>
    </article>`;
  }).join("");
  const best = frontier.options.find((option) => option.name === frontier.best_option);
  const benchmark = frontier.reference_benchmark || {};
  const targetText = best?.goal_reached
    ? "This checked scenario reaches the 85% goal."
    : `It remains ${fmt.format(best?.gap_to_85_pct_points)} points below 85%, showing a real staffing/productivity limit.`;
  $("#frontier-best").innerHTML = `<strong>Best checked option: ${esc(best?.label || labels[frontier.best_option])}</strong>
    <span>${fmt.format(frontier.best_coverage_pct)}% coverage · +${fmt.format(frontier.best_improvement_pct_points)} points over this plan. ${esc(targetText)}</span>
    <small>Controlled 40-scenario reference: strict ${fmt.format(benchmark.strict_mean_coverage_pct)}%, flexible divisions ${fmt.format(benchmark.open_divisions_mean_coverage_pct)}%, full attendance ${fmt.format(benchmark.full_attendance_mean_coverage_pct)}%, combined ${fmt.format(benchmark.full_attendance_open_divisions_mean_coverage_pct)}%.</small>`;
  $("#frontier-results").hidden = false;
  $("#frontier-export-btn").hidden = !(frontier.best_is_conditional && frontier.best_plan?.assignments?.length);
  if (best) {
    $("#practical-suggestion").textContent = `The strongest what-if used ${fmt.format(best.additional_assigned_workers)} additional assigned workers and ${fmt.format(best.cross_division_assignments)} transfers. Enter only what is actually available this morning.`;
  }
}

async function loadFrontier() {
  if (!allocationRequest) return;
  const button = $("#frontier-btn");
  button.disabled = true;
  button.textContent = "Comparing…";
  $("#frontier-loading").hidden = false;
  try {
    renderFrontier(await api("/api/frontier", {
      method: "POST",
      body: JSON.stringify(allocationRequest),
    }));
  } catch (error) {
    toast(error.message);
  } finally {
    $("#frontier-loading").hidden = true;
    button.disabled = false;
    button.textContent = "Compare again";
  }
}

function updatePracticalExportState() {
  const practical = practicalResponse?.practical;
  const button = $("#practical-export-btn");
  if (!practical?.ready || !practical.plan?.assignments?.length) {
    button.disabled = true;
    button.textContent = "No practical plan to download";
    return;
  }
  const workersConfirmed = !practical.worker_confirmation_required || $("#confirm-workers").checked;
  const transfersConfirmed = !practical.transfer_approval_required || $("#confirm-transfers").checked;
  button.disabled = !(workersConfirmed && transfersConfirmed);
  button.textContent = button.disabled
    ? "Confirm above to download practical CSV"
    : "Download confirmed practical CSV";
}

function renderPractical(payload) {
  practicalResponse = payload;
  const practical = payload?.practical;
  if (!practical?.ready) {
    throw new Error(practical?.error || "Practical plan is unavailable");
  }
  const gain = practical.improvement_pct_points;
  const gainText = `${gain > 0 ? "+" : ""}${fmt.format(gain)} points`;
  const proofText = practical.optimality_proven
    ? "The maximum under these limits was mathematically proven."
    : `This is a valid plan found within the time limit; the remaining gap to the solver bound is at most ${fmt.format(practical.optimality_gap_pct_points)} points.`;
  const targetText = practical.goal_reached
    ? `It reaches the ${fmt.format(practical.goal_coverage_pct)}% goal.`
    : `It is ${fmt.format(practical.gap_to_goal_pct_points)} points below the ${fmt.format(practical.goal_coverage_pct)}% goal.`;
  $("#practical-status").textContent = practical.goal_reached ? "GOAL REACHED" : "VALID BELOW GOAL";
  $("#practical-title").textContent = practical.goal_reached
    ? "Practical target plan ready for confirmation"
    : "Best practical plan within today’s limits";
  const poolText = practical.effective_additional_worker_limit < practical.requested_additional_worker_limit
    ? ` Only ${fmt.format(practical.effective_additional_worker_limit)} additional template-day candidates were eligible.`
    : "";
  $("#practical-message").textContent = `${targetText} ${proofText}${poolText}`;
  $("#practical-coverage").textContent = `${fmt.format(practical.coverage_pct)}%`;
  $("#practical-worker-use").textContent = `${fmt.format(practical.additional_workers_used)} / ${fmt.format(practical.effective_additional_worker_limit)}`;
  $("#practical-transfer-use").textContent = `${fmt.format(practical.transfers_used)} / ${fmt.format(practical.requested_transfer_limit)}`;
  $("#practical-gain").textContent = gainText;
  $("#practical-rules").textContent = practical.constraint_violations === 0 ? "0 · passed" : fmt.format(practical.constraint_violations);

  $("#practical-workers-body").innerHTML = practical.additional_workers.length
    ? practical.additional_workers.map((item) => `<tr><td><strong>${esc(item.employee_id)}</strong></td><td>${esc(item.home_division)}</td><td>${esc(item.field_id)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty-row">No additional workers used.</td></tr>`;
  $("#practical-transfers-body").innerHTML = practical.transfer_assignments.length
    ? practical.transfer_assignments.map((item) => `<tr><td><strong>${esc(item.employee_id)}</strong></td><td>${esc(item.home_division)} → ${esc(item.assigned_division)}</td><td>${esc(item.field_id)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty-row">No division transfers used.</td></tr>`;

  const workerCheck = $("#confirm-workers");
  const transferCheck = $("#confirm-transfers");
  workerCheck.disabled = !practical.worker_confirmation_required;
  workerCheck.checked = !practical.worker_confirmation_required;
  transferCheck.disabled = !practical.transfer_approval_required;
  transferCheck.checked = !practical.transfer_approval_required;
  workerCheck.closest("label").classList.toggle("disabled", workerCheck.disabled);
  transferCheck.closest("label").classList.toggle("disabled", transferCheck.disabled);
  $("#practical-results").hidden = false;
  updatePracticalExportState();
}

async function buildPracticalPlan() {
  if (!allocationRequest) return;
  const additional = Number($("#practical-extra").value);
  const transfers = Number($("#practical-transfers").value);
  if (!Number.isInteger(additional) || additional < 0 || !Number.isInteger(transfers) || transfers < 0) {
    toast("Enter whole numbers of zero or more for workers and transfers.");
    return;
  }
  const button = $("#practical-btn");
  button.disabled = true;
  button.querySelector("span").textContent = "Building within limits…";
  $("#practical-loading").hidden = false;
  try {
    renderPractical(await api("/api/practical", {
      method: "POST",
      body: JSON.stringify({
        ...allocationRequest,
        additional_workers_available: additional,
        max_cross_division_transfers: transfers,
      }),
    }));
  } catch (error) {
    practicalResponse = null;
    $("#practical-results").hidden = true;
    toast(error.message);
  } finally {
    $("#practical-loading").hidden = true;
    button.disabled = false;
    button.querySelector("span").textContent = "Build practical plan";
  }
}

function renderPlan(payload) {
  allocationResponse = payload;
  const plan = payload.selected;
  const metrics = plan.metrics;

  $("#empty-state").hidden = true;
  $("#result-content").hidden = false;
  $("#plan-title").textContent = plan.policy.startsWith("cp-sat")
    ? "Mathematical plan selected"
    : plan.policy === "maskable-ppo"
      ? "RL plan selected"
      : "Safe standard plan selected";
  $("#plan-message").textContent = plainPlanMessage(plan);
  $("#kpi-coverage").textContent = `${fmt.format(metrics.coverage_pct)}%`;
  $("#kpi-assigned").textContent = fmt.format(metrics.assigned_workers);
  $("#kpi-workers").textContent = `${fmt.format(metrics.available_workers)} available · ${fmt.format(metrics.unassigned_workers)} not assigned`;
  $("#kpi-fulfilled").textContent = `${fmt.format(metrics.predicted_fulfilled_kg)} kg`;
  $("#kpi-target").textContent = `${fmt.format(metrics.target_kg)} kg target`;
  $("#kpi-constraints").textContent = metrics.constraint_violations === 0 ? "Passed" : `${fmt.format(metrics.constraint_violations)} issue(s)`;
  $("#kpi-constraints").style.color = metrics.constraint_violations === 0 ? "var(--green-700)" : "var(--danger)";

  renderFields(plan.fields);
  renderAssignments();
  renderComparison(payload);
  renderCoverageGoal(payload.coverage_goal);
  $("#export-btn").disabled = !plan.assignments.length;
  $("#frontier-btn").disabled = false;
  $("#frontier-results").hidden = true;
  frontierResponse = null;
  $("#practical-btn").disabled = false;
  $("#practical-results").hidden = true;
  practicalResponse = null;
  $("#confirm-workers").checked = false;
  $("#confirm-transfers").checked = false;
  setStep(3);
  $("#result-section").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function generatePlan() {
  const button = $("#generate-btn");
  button.disabled = true;
  button.querySelector("span").textContent = "Comparing safe plans…";
  setStep(2);
  try {
    allocationRequest = buildRequestPayload();
    renderPlan(await api("/api/allocate", {
      method: "POST",
      body: JSON.stringify(allocationRequest),
    }));
  } catch (error) {
    setStep(1);
    toast(error.message);
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Create employee plan";
  }
}

function resetForm() {
  $("#template-date").value = profile.default_template_date;
  $("#division").value = "";
  $("#attendance").value = "90";
  $("#demand").value = "100";
  $("#demand-source").value = "historical_template";
  $("#forecast-risk").value = "central";
  $("#same-division").checked = true;
  $("#coverage-goal").value = "85";
  $("#empty-state").hidden = false;
  $("#result-content").hidden = true;
  allocationResponse = null;
  allocationRequest = null;
  frontierResponse = null;
  practicalResponse = null;
  $("#frontier-btn").disabled = true;
  $("#frontier-results").hidden = true;
  $("#practical-extra").value = "0";
  $("#practical-transfers").value = "0";
  $("#practical-btn").disabled = true;
  $("#practical-results").hidden = true;
  $("#practical-suggestion").textContent = "Start with zero, then enter only confirmed morning resources.";
  setStep(1);
}

function exportCsv() {
  if (!allocationResponse) return;
  const headers = ["employee_id", "home_division", "field_id", "division", "field_code", "predicted_kg", "forecast_confidence", "forecast_uncertainty_kg", "confidence", "cross_division"];
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = allocationResponse.selected.assignments.map((row) => headers.map((key) => quote(row[key])).join(","));
  const content = [headers.join(","), ...rows].join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  link.download = `tte_employee_plan_${allocationResponse.selected.scenario.planning_date}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportGoalCsv() {
  const plan = allocationResponse?.coverage_goal?.goal_plan;
  if (!plan?.assignments?.length) return;
  const headers = ["employee_id", "home_division", "field_id", "division", "field_code", "predicted_kg", "forecast_confidence", "forecast_uncertainty_kg", "confidence", "cross_division"];
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = plan.assignments.map((row) => headers.map((key) => quote(row[key])).join(","));
  const content = [headers.join(","), ...rows].join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  link.download = `tte_coverage_goal_plan_${plan.scenario.planning_date}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportFrontierCsv() {
  const plan = frontierResponse?.frontier?.best_plan;
  if (!plan?.assignments?.length) return;
  const headers = ["employee_id", "home_division", "field_id", "division", "field_code", "predicted_kg", "forecast_confidence", "forecast_uncertainty_kg", "confidence", "cross_division"];
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = plan.assignments.map((row) => headers.map((key) => quote(row[key])).join(","));
  const content = [headers.join(","), ...rows].join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  link.download = `tte_frontier_${frontierResponse.frontier.best_option}_${plan.scenario.planning_date}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function exportPracticalCsv() {
  const practical = practicalResponse?.practical;
  const plan = practical?.plan;
  if (!practical?.ready || !plan?.assignments?.length || $("#practical-export-btn").disabled) return;
  const additionalIds = new Set(practical.additional_workers.map((item) => item.employee_id));
  const headers = ["employee_id", "home_division", "field_id", "division", "field_code", "predicted_kg", "forecast_confidence", "forecast_uncertainty_kg", "confidence", "cross_division", "attendance_status", "transfer_approval"];
  const quote = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = plan.assignments.map((row) => {
    const enriched = {
      ...row,
      attendance_status: additionalIds.has(row.employee_id) ? "supervisor_confirmed_call_up" : "expected_attendee",
      transfer_approval: row.cross_division ? "supervisor_approved" : "not_required",
    };
    return headers.map((key) => quote(enriched[key])).join(",");
  });
  const content = [headers.join(","), ...rows].join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([content], { type: "text/csv;charset=utf-8" }));
  link.download = `tte_practical_confirmed_plan_${plan.scenario.planning_date}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function bindEvents() {
  $("#generate-btn").addEventListener("click", generatePlan);
  $("#reset-btn").addEventListener("click", resetForm);
  $("#assignment-search").addEventListener("input", renderAssignments);
  $("#export-btn").addEventListener("click", exportCsv);
  $("#goal-export-btn").addEventListener("click", exportGoalCsv);
  $("#frontier-btn").addEventListener("click", loadFrontier);
  $("#frontier-export-btn").addEventListener("click", exportFrontierCsv);
  $("#practical-btn").addEventListener("click", buildPracticalPlan);
  $("#confirm-workers").addEventListener("change", updatePracticalExportState);
  $("#confirm-transfers").addEventListener("change", updatePracticalExportState);
  $("#practical-export-btn").addEventListener("click", exportPracticalCsv);
}

async function init() {
  bindEvents();
  try {
    [profile, model] = await Promise.all([api("/api/profile"), api("/api/model")]);
    populateControls();
    populateModelStatus();
  } catch (error) {
    $("#model-status").querySelector("b").textContent = "Connection problem";
    toast(error.message);
  }
}

init();
