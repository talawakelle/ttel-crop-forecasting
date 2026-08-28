import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import {
  createSession, destroySession, escapeHtml as e, openDatabase,
  readCsvFile, readForm, safeEqual, sessionFromRequest,
} from './lib/core.mjs';

const portalRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(portalRoot, '..');
const dbPath = process.env.PORTAL_DB || path.join(portalRoot, 'data', 'portal.db');
const db = openDatabase(dbPath);
const host = process.env.PORTAL_HOST || '127.0.0.1';
const port = Number(process.env.PORTAL_PORT || 8080);
const secureCookie = String(process.env.COOKIE_SECURE || '').toLowerCase() === 'true';
const css = fs.readFileSync(path.join(portalRoot, 'public', 'app.css'), 'utf8');

function headers(contentType = 'text/html; charset=utf-8') {
  return {
    'Content-Type': contentType,
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'none'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  };
}

function send(response, status, body, extraHeaders = {}) {
  response.writeHead(status, { ...headers(), ...extraHeaders });
  response.end(body);
}

function redirect(response, location, extraHeaders = {}) {
  response.writeHead(303, { ...headers(), Location: location, ...extraHeaders });
  response.end();
}

function cookieHeader(token, expires) {
  return `tte_session=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${Math.max(0, Math.floor((expires.getTime() - Date.now()) / 1000))}${secureCookie ? '; Secure' : ''}`;
}

function clearCookie() {
  return `tte_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0${secureCookie ? '; Secure' : ''}`;
}

function flash(message, type = 'notice') {
  return message ? `<div class="flash ${e(type)}">${e(message)}</div>` : '';
}

function nav(session) {
  const admin = session.role === 'admin';
  return `<aside class="sidebar">
    <div class="brand"><span>TTE</span><b>Integrated Planning</b><small>Crop · GAP · Workforce</small></div>
    <nav>
      <a href="/dashboard">Overview</a>
      <a href="/workforce">Workforce Planning</a>
      <a href="/practice">Practice Diary</a>
      <a href="/fields">Field Master</a>
      ${admin ? '<a href="/admin">Portfolio Administration</a>' : ''}
    </nav>
    <form method="post" action="/logout"><input type="hidden" name="csrf" value="${e(session.csrf_token)}"><button class="link-button">Sign out</button></form>
  </aside>`;
}

function page(title, content, session = null) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${e(title)} · TTE Integrated Planning</title><link rel="stylesheet" href="/assets/app.css"></head><body>
    ${session ? `<div class="app-shell">${nav(session)}<main class="main"><header class="topbar"><div><small>${e(session.role === 'admin' ? 'PORTFOLIO ACCESS' : 'ESTATE-RESTRICTED ACCESS')}</small><h1>${e(title)}</h1></div><div class="identity"><b>${e(session.display_name)}</b><span>${e(session.estate || 'All 33 estates')}</span></div></header>${content}</main></div>` : content}
  </body></html>`;
}

function loginPage(message = '') {
  return page('Access portal', `<main class="login-shell"><section class="login-visual"><div><span class="badge">TALAWAKELLE TEA ESTATES PLC</span><h1>Integrated Crop<br>& Workforce Planning</h1><p>Estate-level crop forecasting, actual crop, GAP evidence and conservative workforce decision support.</p></div></section><section class="login-panel"><div class="auth-card"><div class="logo-mark">TTE</div><h2>Passwordless manager portal</h2>${flash(message, 'error')}<p>Open the secure access link issued for your estate. No username or password is required.</p><div class="warning"><b>Estate restriction:</b> each link opens only its assigned estate. Do not forward your estate link to another person.</div><small>Contact the portfolio administrator if your link must be replaced.</small></div></section></main>`);
}

function portfolioData() {
  return {
    summary: readCsvFile(path.join(projectRoot, 'outputs', 'portfolio_summary.csv')),
    forecasts: readCsvFile(path.join(projectRoot, 'outputs', 'portfolio_forecasts.csv')),
  };
}

function workforceData() {
  const file = path.join(projectRoot, 'outputs', 'workforce_estate_data_audit.csv');
  return fs.existsSync(file) ? readCsvFile(file) : [];
}

function allowedEstate(session, requested) {
  if (session.role === 'manager') {
    if (requested && requested !== session.estate) throw Object.assign(new Error('Access to another estate is not permitted.'), { statusCode: 403 });
    return session.estate;
  }
  return requested || null;
}

function number(value, digits = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString('en-LK', { maximumFractionDigits: digits, minimumFractionDigits: digits }) : '—';
}

function todayColombo() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en', {
    timeZone: 'Asia/Colombo', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date()).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

let projectionCache = { mtime: 0, rows: [] };
function projectionRows() {
  const file = path.join(projectRoot, 'outputs', 'five_year_daily_projection.csv');
  if (!fs.existsSync(file)) return [];
  const mtime = fs.statSync(file).mtimeMs;
  if (projectionCache.mtime !== mtime) projectionCache = { mtime, rows: readCsvFile(file) };
  return projectionCache.rows;
}

let automatedActualCache = { mtime: 0, rows: [] };
function automatedActualRows() {
  const file = path.join(projectRoot, 'outputs', 'prompt_daily_actuals.csv');
  if (!fs.existsSync(file)) return [];
  const mtime = fs.statSync(file).mtimeMs;
  if (automatedActualCache.mtime !== mtime) automatedActualCache = { mtime, rows: readCsvFile(file) };
  return automatedActualCache.rows;
}

function addDays(dateText, days) {
  const date = new Date(`${dateText}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function periodKey(dateText, grain) {
  const date = new Date(`${dateText}T00:00:00Z`);
  if (grain === 'daily') return dateText;
  if (grain === 'weekly') {
    const daysToSunday = (7 - date.getUTCDay()) % 7;
    date.setUTCDate(date.getUTCDate() + daysToSunday);
    return date.toISOString().slice(0, 10);
  }
  if (grain === 'monthly') return `${dateText.slice(0, 7)}-01`;
  return `${dateText.slice(0, 4)}-01-01`;
}

function aggregateSeries(rows, dateColumn, valueColumn, grain) {
  const grouped = new Map();
  for (const row of rows) {
    const rawValue = row[valueColumn];
    if (rawValue == null || String(rawValue).trim() === '') continue;
    const value = Number(rawValue);
    if (!row[dateColumn] || !Number.isFinite(value)) continue;
    const key = periodKey(row[dateColumn], grain);
    grouped.set(key, (grouped.get(key) || 0) + value);
  }
  return [...grouped].sort((a, b) => a[0].localeCompare(b[0])).map(([date, value]) => ({ date, value }));
}

function estateHistory(estate) {
  const candidate = path.join(projectRoot, 'outputs', `${estate}_provisional`, 'weekly_history.csv');
  const file = fs.existsSync(candidate) ? candidate : path.join(projectRoot, 'outputs', 'weekly_history.csv');
  return readCsvFile(file).map(row => ({ date: row.week_ending, value: Number(row.crop_net_kg) })).filter(row => Number.isFinite(row.value));
}

function chartSvg(series, minDate, maxDate) {
  const width = 1160, height = 390, padding = { left: 72, right: 24, top: 30, bottom: 48 };
  const minX = new Date(`${minDate}T00:00:00Z`).getTime();
  const maxX = new Date(`${maxDate}T00:00:00Z`).getTime();
  const values = series.flatMap(item => item.points.map(point => point.value));
  const maxY = Math.max(1, ...values) * 1.12;
  const x = date => padding.left + ((new Date(`${date}T00:00:00Z`).getTime() - minX) / Math.max(1, maxX - minX)) * (width - padding.left - padding.right);
  const y = value => padding.top + (1 - value / maxY) * (height - padding.top - padding.bottom);
  const grid = Array.from({ length: 5 }, (_, index) => {
    const yy = padding.top + index * (height - padding.top - padding.bottom) / 4;
    const label = Math.round(maxY * (1 - index / 4));
    return `<line x1="${padding.left}" y1="${yy}" x2="${width - padding.right}" y2="${yy}" class="chart-grid"/><text x="${padding.left - 10}" y="${yy + 4}" text-anchor="end" class="axis-label">${e(number(label))}</text>`;
  }).join('');
  const lines = series.map(item => {
    const points = item.points.filter(point => point.date >= minDate && point.date <= maxDate);
    if (!points.length) return '';
    const stride = Math.max(1, Math.ceil(points.length / 700));
    const sampled = points.filter((_, index) => index % stride === 0 || index === points.length - 1);
    return `<polyline class="chart-line ${e(item.className)}" points="${sampled.map(point => `${x(point.date).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ')}"/>`;
  }).join('');
  return `<svg class="forecast-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Actual, current-practice and best-practice crop lines">${grid}<line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" class="axis"/>${lines}<text x="${padding.left}" y="${height - 15}" class="axis-label">${e(minDate)}</text><text x="${width - padding.right}" y="${height - 15}" text-anchor="end" class="axis-label">${e(maxDate)}</text></svg>`;
}

function forecastGraph(estate, url, origin) {
  const allowedGrains = new Set(['daily', 'weekly', 'monthly', 'yearly']);
  const allowedHorizons = new Set(['week', 'month', 'year', '3year', '5year']);
  const grain = allowedGrains.has(url.searchParams.get('view')) ? url.searchParams.get('view') : 'weekly';
  const horizon = allowedHorizons.has(url.searchParams.get('range')) ? url.searchParams.get('range') : 'month';
  const days = { week: 7, month: 31, year: 365, '3year': 1096, '5year': 1826 }[horizon];
  const lookback = { daily: 31, weekly: 182, monthly: 365, yearly: 1096 }[grain];
  const storedDaily = db.prepare('SELECT actual_date,crop_kg FROM daily_actuals WHERE estate=? ORDER BY actual_date').all(estate)
    .map(row => ({ date: row.actual_date, value: Number(row.crop_kg) }));
  const automaticDaily = automatedActualRows().filter(row => row.estate === estate)
    .map(row => ({ date: row.date, value: Number(row.actual_kg) }));
  const exactByDate = new Map(automaticDaily.map(row => [row.date, row.value]));
  for (const row of storedDaily) exactByDate.set(row.date, row.value);
  const exactDaily = [...exactByDate].sort((a, b) => a[0].localeCompare(b[0])).map(([date, value]) => ({ date, value }));
  const latestActual = exactDaily.at(-1)?.date;
  const chartAnchor = latestActual && latestActual > origin ? latestActual : origin;
  const end = addDays(chartAnchor, days);
  const start = addDays(chartAnchor, -lookback);
  const projection = projectionRows().filter(row => row.estate === estate && row.date <= end);
  const current = aggregateSeries(projection, 'date', 'current_practice_kg', grain);
  const best = aggregateSeries(projection, 'date', 'best_practice_kg', grain);
  const historicalWeekly = estateHistory(estate);
  const firstStoredDate = exactDaily[0]?.date;
  const actualBase = grain === 'daily'
    ? exactDaily.map(row => ({ date: row.date, actual: row.value }))
    : [
        ...historicalWeekly.filter(row => !firstStoredDate || row.date < firstStoredDate).map(row => ({ date: row.date, actual: row.value })),
        ...exactDaily.map(row => ({ date: row.date, actual: row.value })),
      ];
  const actual = aggregateSeries(actualBase, 'date', 'actual', grain);
  const chart = chartSvg([
    { className: 'actual', points: actual },
    { className: 'current-practice', points: current },
    { className: 'best-practice', points: best },
  ], start, end);
  const controls = `<form class="chart-controls" method="get" action="/dashboard"><label>View<select name="view">${['daily','weekly','monthly','yearly'].map(value => `<option value="${value}" ${grain === value ? 'selected' : ''}>${value[0].toUpperCase() + value.slice(1)}</option>`).join('')}</select></label><label>Range<select name="range">${[['week','This week'],['month','One month'],['year','One year'],['3year','Three years'],['5year','Maximum five years']].map(([value,label]) => `<option value="${value}" ${horizon === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label><button>Apply</button></form>`;
  const automaticCutoff = automaticDaily.at(-1)?.date;
  const manualCutoff = storedDaily.at(-1)?.date;
  const manualNote = manualCutoff && (!automaticCutoff || manualCutoff > automaticCutoff)
    ? `; manual fallback through ${e(manualCutoff)}`
    : '';
  return `<section class="panel chart-panel"><div class="section-title"><div><small>ACTUAL VS SCENARIOS</small><h2>${grain[0].toUpperCase() + grain.slice(1)} crop outlook</h2></div>${controls}</div><div class="chart-legend"><span class="actual-dot">Actual value${automaticCutoff ? ` — automated through ${e(automaticCutoff)}${manualNote}` : manualCutoff ? ` — manual through ${e(manualCutoff)}` : ''}</span><span class="current-dot">Current-practice forecast</span><span class="best-dot">Best-practice forecast ${best.length ? '' : '— awaiting GAP data'}</span></div>${chart}<p class="muted">PROMPT actuals are privacy-safe estate/day totals and refresh when the importer runs. Daily values beyond the validated four-week horizon are planning allocations from weekly/seasonal projections. Years 4–5 are strategic scenarios, not precise weather forecasts.</p></section>`;
}

function actualEntryPanel(session, estate) {
  return `<section class="panel compact-panel"><div><small>ACTUAL CROP LINE</small><h2>Record daily actual crop</h2><p class="muted">Entries update only ${e(estate)} and are used for the graph and later forecast refresh.</p></div><form class="inline-form" method="post" action="/actuals"><input type="hidden" name="csrf" value="${e(session.csrf_token)}"><input type="hidden" name="estate" value="${e(estate)}"><label>Date<input type="date" name="actual_date" required></label><label>Actual green leaf (kg)<input type="number" name="crop_kg" min="0" step="0.01" required></label><button class="primary">Save actual</button></form></section>`;
}

function workforcePage(session, url) {
  const data = portfolioData();
  const workforce = workforceData();
  let estate = allowedEstate(session, url.searchParams.get('estate'));
  if (!estate && session.role === 'admin') estate = data.summary[0]?.estate;
  const summary = data.summary.find(row => row.estate === estate);
  const audit = workforce.find(row => row.estate === estate);
  if (!summary) throw Object.assign(new Error('Estate forecast was not found.'), { statusCode: 404 });
  const selector = session.role === 'admin' ? `<form class="selector" method="get" action="/workforce"><label>View estate<select name="estate">${data.summary.map(row => `<option ${row.estate === estate ? 'selected' : ''}>${e(row.estate)}</option>`).join('')}</select></label><button>Open</button></form>` : '';
  if (!audit) return page('Workforce Planning', `${selector}<div class="warning"><b>Workforce audit unavailable:</b> run the multi-estate audit before planning.</div>`, session);

  const forecasts = data.forecasts.filter(row => row.estate === estate);
  const fourWeekKg = forecasts.reduce((total, row) => total + Number(row.forecast_kg || 0), 0);
  const today = todayColombo();
  const cropCurrent = summary.forecast_end >= today && !String(summary.operational_status).toUpperCase().startsWith('OUTDATED');
  const modelReady = audit.readiness === 'READY_FOR_MODEL_COMPARISON';
  const shortHistory = audit.readiness === 'CONDITIONAL_SHORT_HISTORY';
  const recoveredSource = audit.identity_status === 'RECOVERED_REQUIRES_SOURCE_REPLACEMENT';
  const plannerStatus = estate === 'Clarendon'
    ? 'PILOT ENGINE PRESERVED — SHADOW ONLY'
    : modelReady ? 'READY FOR ESTATE MODEL COMPARISON' : shortHistory ? 'PROVISIONAL POOLED COMPARISON ONLY' : 'DATA GATE NOT PASSED';
  const demandStatus = cropCurrent ? 'CURRENT DEMAND AVAILABLE' : 'BLOCKED — RETRAIN CROP FORECAST';
  const warning = !cropCurrent
    ? `<div class="warning"><b>Operational planning blocked:</b> the crop forecast ends ${e(summary.forecast_end)} and is marked ${e(summary.operational_status)}. Synchronize actuals, weather and retrain before making a daily labour plan.</div>`
    : '';
  const sourceWarning = recoveredSource ? '<div class="warning"><b>Source replacement required:</b> this checkpoint used recovered workbook content. Supply a valid replacement archive before production training.</div>' : '';
  const gates = [
    ['01', 'Identity & data audit', audit.identity_mismatch === 'False' || audit.identity_mismatch === 'false' ? 'PASS' : 'BLOCKED', `${number(audit.valid_plucking_rows)} valid plucking rows`],
    ['02', 'Estate model comparison', plannerStatus, `${number(audit.training_days)} / ${number(audit.validation_days)} / ${number(audit.test_days)} training-validation-test days`],
    ['03', 'Crop demand gate', demandStatus, `Forecast ${e(summary.forecast_origin)} to ${e(summary.forecast_end)}`],
    ['04', 'Manager decision', 'NO AUTOMATIC MOVES', 'Supervisor approval and shadow review required'],
  ].map(([step, label, state, note]) => `<article><span>${e(step)}</span><h3>${e(label)}</h3><b>${e(state)}</b><p>${note}</p></article>`).join('');

  return page(`${estate} Workforce Planning`, `${selector}${warning}${sourceWarning}
    <section class="kpi-grid workforce-kpis"><article><span>Observed employees</span><b>${number(audit.employees)}</b><small>historical identifiers, not today’s attendance</small></article><article><span>Divisions / fields</span><b>${number(audit.divisions)} / ${number(audit.fields)}</b><small>historical operating coverage</small></article><article><span>Four-week crop demand</span><b>${number(fourWeekKg)} kg</b><small>${e(demandStatus)}</small></article><article><span>Workforce readiness</span><b class="status-text">${e(audit.readiness)}</b><small>${e(audit.date_min)} to ${e(audit.date_max)}</small></article></section>
    <section class="panel"><div class="section-title"><div><small>CONSERVATIVE DECISION PIPELINE</small><h2>Estate-specific workforce gates</h2></div><span class="pill">RL DISABLED</span></div><div class="gate-grid">${gates}</div></section>
    <section class="panel"><div class="section-title"><div><small>APPROVED SAFETY ENVELOPE</small><h2>Planner limits inherited from Clarendon v1.5</h2></div></div><div class="safety-grid"><article><span>Default method</span><b>Budgeted dynamic greedy</b></article><article><span>Maximum movement rate</span><b>15%</b></article><article><span>Total moves</span><b>≤ 15</b></article><article><span>Moves per round</span><b>≤ 10</b></article><article><span>Per employee</span><b>≤ 1 voluntary move</b></article><article><span>RL role</span><b>High-confidence accept/veto only</b></article></div><p class="muted">CP-SAT may create the morning plan. Intraday changes default to the deterministic planner. RL cannot issue a move by itself and falls back to deterministic decisions.</p></section>
    <section class="panel"><div class="section-title"><div><small>REQUIRED DAILY INPUTS</small><h2>What the estate manager must confirm</h2></div></div><div class="requirements-grid"><article><b>Attendance & leave</b><span>Who is actually available today</span></article><article><b>Skills & restrictions</b><span>Task eligibility, legal hours and medical limits</span></article><article><b>Field work demand</b><span>Plucking, fertilizer, foliar and sundry tasks</span></article><article><b>Supervisor approval</b><span>Review every proposed reassignment in shadow mode</span></article></div><div class="danger-note"><b>Not authorized:</b> GPU/RL training, live automatic reallocations, or copying Clarendon’s productivity model into another estate without its own untouched test.</div></section>`, session);
}

function dashboardPage(session, url) {
  const data = portfolioData();
  let estate = allowedEstate(session, url.searchParams.get('estate'));
  if (!estate && session.role === 'admin') estate = data.summary[0]?.estate;
  const summary = data.summary.find(row => row.estate === estate);
  if (!summary) throw Object.assign(new Error('Estate forecast was not found.'), { statusCode: 404 });
  const workforceAudit = workforceData().find(row => row.estate === estate);
  const forecasts = data.forecasts.filter(row => row.estate === estate).sort((a, b) => Number(a.horizon_weeks) - Number(b.horizon_weeks));
  const diaryCount = db.prepare('SELECT COUNT(*) AS count FROM practice_entries WHERE estate=?').get(estate).count;
  const fieldCount = db.prepare('SELECT COUNT(*) AS count FROM field_master WHERE estate=? AND active=1').get(estate).count;
  const provisional = summary.training_status === 'PROVISIONAL POOLED';
  const selector = session.role === 'admin' ? `<form class="selector" method="get" action="/dashboard"><label>View estate<select name="estate">${data.summary.map(row => `<option ${row.estate === estate ? 'selected' : ''}>${e(row.estate)}</option>`).join('')}</select></label><button>Open</button></form>` : '';
  const cards = forecasts.map(row => `<article class="forecast-card"><span>WEEK ${e(row.horizon_weeks)}</span><b>${number(row.forecast_kg)} kg</b><p>${e(row.forecast_week_starting)} to ${e(row.forecast_week_ending)}</p><small>80% range ${number(row.lower_80_kg)}–${number(row.upper_80_kg)} kg</small><em>${e(row.selected_method)}</em></article>`).join('');
  const content = `${selector}${provisional ? '<div class="warning"><b>Provisional pooled model:</b> short estate history. Use for interim planning and replace after sufficient history is collected.</div>' : ''}<div class="warning"><b>Data timing:</b> forecast origin ${e(summary.forecast_origin)}. Upload records after ${e(summary.crop_date_max)} before operational use.</div>
    <section class="kpi-grid"><article><span>Training status</span><b>${e(summary.training_status)}</b></article><article><span>Average validation WAPE</span><b>${number(summary.average_selected_wape_pct, 1)}%</b></article><article><span>Practice diary entries</span><b>${number(diaryCount)}</b></article><article><span>Registered fields</span><b>${number(fieldCount)}</b></article></section>
    ${forecastGraph(estate, url, summary.forecast_origin)}
    ${actualEntryPanel(session, estate)}
    <section class="panel compact-panel workforce-callout"><div><small>INTEGRATED WORKFORCE GATE</small><h2>${e(workforceAudit?.readiness || 'AUDIT REQUIRED')}</h2><p class="muted">${workforceAudit ? `${number(workforceAudit.employees)} observed employees across ${number(workforceAudit.divisions)} divisions and ${number(workforceAudit.fields)} fields.` : 'The workforce audit is not available.'} Crop demand must be current before planner simulation.</p></div><a class="primary action-link" href="/workforce${session.role === 'admin' ? `?estate=${encodeURIComponent(estate)}` : ''}">Open workforce planning</a></section>
    <section><div class="section-title"><div><small>CURRENT PRACTICE</small><h2>Four-week crop forecast</h2></div><span class="pill">${e(summary.weather_value_status)}</span></div><div class="forecast-grid">${cards}</div></section>
    <section class="panel"><div class="section-title"><div><small>DECISION MODEL</small><h2>Current vs best-practice architecture</h2></div></div><div class="scenario-grid"><article class="scenario current"><span>01</span><h3>Current Practice</h3><p>Estate-specific crop and validated weather forecast.</p><b>AVAILABLE</b></article><article class="scenario potential"><span>02</span><h3>Best-Practice Potential</h3><p>Calculated from comparable all-estate field-week evidence.</p><b>${fieldCount && diaryCount ? 'DATA COLLECTION IN PROGRESS' : 'AWAITING FIELD & DIARY DATA'}</b></article><article class="scenario implementation"><span>03</span><h3>Implementation Forecast</h3><p>Current forecast plus feasible, delayed practice uplift and cost.</p><b>ACTIVATES AFTER VALIDATION</b></article></div></section>
    <section class="panel"><div class="section-title"><div><small>FIVE-YEAR ROADMAP</small><h2>Daily planning projection</h2></div></div><div class="timeline"><div><b>Days 1–28</b><span>Operational daily</span></div><div><b>Months 2–12</b><span>Weekly-to-daily</span></div><div><b>Years 2–3</b><span>Seasonal planning</span></div><div><b>Years 4–5</b><span>Strategic scenarios</span></div></div><p class="muted">The current-practice five-year planning projection is available now. The best-practice and implementation scenarios remain inactive until enough field and diary evidence is collected and validated; the portal will not invent an uplift.</p></section>`;
  return page(`${estate} Estate`, content, session);
}

function practicePage(session, url) {
  const data = portfolioData();
  const requested = url.searchParams.get('estate');
  const estate = allowedEstate(session, requested) || data.summary[0].estate;
  const entries = db.prepare('SELECT * FROM practice_entries WHERE estate=? ORDER BY entry_date DESC,id DESC LIMIT 100').all(estate);
  const selector = session.role === 'admin' ? `<form class="selector" method="get"><label>Estate<select name="estate">${data.summary.map(row => `<option ${row.estate === estate ? 'selected' : ''}>${e(row.estate)}</option>`).join('')}</select></label><button>Open</button></form>` : '';
  const rows = entries.map(row => `<tr><td>${e(row.entry_date)}</td><td>${e(row.division)}</td><td>${e(row.field_name)}</td><td>${e(row.activity_type)}</td><td>${e(row.product)}</td><td>${number(row.quantity, 2)} ${e(row.unit)}</td><td>${number(row.labour_count, 1)}</td><td>${number(row.cost_lkr, 2)}</td></tr>`).join('') || '<tr><td colspan="8">No practice entries recorded yet.</td></tr>';
  return page('Practice Diary', `${selector}${flash(url.searchParams.get('message'))}<section class="panel"><h2>Add agricultural practice</h2><form class="data-form" method="post" action="/practice"><input type="hidden" name="csrf" value="${e(session.csrf_token)}"><input type="hidden" name="estate" value="${e(estate)}"><label>Date<input type="date" name="entry_date" required></label><label>Division<input name="division" maxlength="100"></label><label>Field<input name="field_name" required maxlength="100"></label><label>Activity<select name="activity_type" required><option>Fertilizer</option><option>Foliar</option><option>Pruning</option><option>Plucking</option><option>Weeding</option><option>Pest Control</option><option>Drainage</option><option>Shade Management</option><option>Other</option></select></label><label>Product / work<input name="product" maxlength="150"></label><label>Quantity<input type="number" step="0.01" min="0" name="quantity"></label><label>Unit<input name="unit" maxlength="40" placeholder="kg, L, hours"></label><label>Labour count<input type="number" step="0.1" min="0" name="labour_count"></label><label>Cost (LKR)<input type="number" step="0.01" min="0" name="cost_lkr"></label><label class="wide">Notes<textarea name="notes" maxlength="1000"></textarea></label><button class="primary" type="submit">Save estate diary entry</button></form></section><section class="panel table-wrap"><h2>Recent entries — ${e(estate)}</h2><table><thead><tr><th>Date</th><th>Division</th><th>Field</th><th>Activity</th><th>Product</th><th>Quantity</th><th>Labour</th><th>Cost</th></tr></thead><tbody>${rows}</tbody></table></section>`, session);
}

function fieldsPage(session, url) {
  const data = portfolioData();
  const estate = allowedEstate(session, url.searchParams.get('estate')) || data.summary[0].estate;
  const fields = db.prepare('SELECT * FROM field_master WHERE estate=? AND active=1 ORDER BY division,field_name').all(estate);
  const selector = session.role === 'admin' ? `<form class="selector" method="get"><label>Estate<select name="estate">${data.summary.map(row => `<option ${row.estate === estate ? 'selected' : ''}>${e(row.estate)}</option>`).join('')}</select></label><button>Open</button></form>` : '';
  const rows = fields.map(row => `<tr><td>${e(row.division)}</td><td>${e(row.field_name)}</td><td>${number(row.area_ha, 2)}</td><td>${number(row.elevation_m)}</td><td>${e(row.cultivar)}</td><td>${number(row.bush_age_years, 1)}</td><td>${e(row.last_pruning_date)}</td><td>${e(row.soil_type)}</td></tr>`).join('') || '<tr><td colspan="8">No fields registered yet.</td></tr>';
  return page('Field Master', `${selector}${flash(url.searchParams.get('message'))}<section class="panel"><h2>Add or update field</h2><form class="data-form" method="post" action="/fields"><input type="hidden" name="csrf" value="${e(session.csrf_token)}"><input type="hidden" name="estate" value="${e(estate)}"><label>Division<input name="division" maxlength="100"></label><label>Field name<input name="field_name" required maxlength="100"></label><label>Area (ha)<input type="number" step="0.01" min="0" name="area_ha"></label><label>Elevation (m)<input type="number" step="0.1" name="elevation_m"></label><label>Cultivar<input name="cultivar" maxlength="100"></label><label>Bush age (years)<input type="number" step="0.1" min="0" name="bush_age_years"></label><label>Last pruning date<input type="date" name="last_pruning_date"></label><label>Soil type<input name="soil_type" maxlength="100"></label><button class="primary" type="submit">Save field</button></form></section><section class="panel table-wrap"><h2>Fields — ${e(estate)}</h2><table><thead><tr><th>Division</th><th>Field</th><th>Area ha</th><th>Elevation</th><th>Cultivar</th><th>Bush age</th><th>Last pruning</th><th>Soil</th></tr></thead><tbody>${rows}</tbody></table></section>`, session);
}

function adminPage(session, url) {
  if (session.role !== 'admin') throw Object.assign(new Error('Administrator access is required.'), { statusCode: 403 });
  const data = portfolioData();
  const workforce = Object.fromEntries(workforceData().map(row => [row.estate, row]));
  const counts = Object.fromEntries(db.prepare('SELECT estate,COUNT(*) AS count FROM practice_entries GROUP BY estate').all().map(r => [r.estate, r.count]));
  const users = Object.fromEntries(db.prepare("SELECT u.estate,u.username,CASE WHEN a.id IS NULL THEN 0 ELSE 1 END AS access_active,a.last_used_at FROM users u LEFT JOIN access_links a ON a.user_id=u.id AND a.active=1 WHERE u.role='manager'").all().map(r => [r.estate, r]));
  const rows = data.summary.map(row => `<tr><td><a href="/dashboard?estate=${encodeURIComponent(row.estate)}">${e(row.estate)}</a></td><td>${e(row.training_status)}</td><td><a href="/workforce?estate=${encodeURIComponent(row.estate)}">${e(workforce[row.estate]?.readiness || 'AUDIT REQUIRED')}</a></td><td>${e(users[row.estate]?.username)}</td><td>${users[row.estate]?.access_active ? 'Passwordless link active' : 'Link required'}</td><td>${number(counts[row.estate] || 0)}</td><td>${e(row.crop_date_max)}</td><td>${number(row.average_selected_wape_pct, 1)}%</td></tr>`).join('');
  const workforceReady = Object.values(workforce).filter(row => row.readiness === 'READY_FOR_MODEL_COMPARISON').length;
  return page('Portfolio Administration', `${flash(url.searchParams.get('message'))}<section class="kpi-grid"><article><span>Estate manager accounts</span><b>${number(Object.keys(users).length)}</b></article><article><span>Workforce model-comparison ready</span><b>${number(workforceReady)}</b></article><article><span>Pooled provisional crop</span><b>${number(data.summary.filter(r => r.training_status === 'PROVISIONAL POOLED').length)}</b></article><article><span>Total diary entries</span><b>${number(Object.values(counts).reduce((a, b) => a + b, 0))}</b></article></section><section class="panel table-wrap"><div class="section-title"><div><small>ACCESS & READINESS</small><h2>All 33 estates</h2></div></div><table><thead><tr><th>Estate</th><th>Crop model</th><th>Workforce gate</th><th>Manager account</th><th>Access status</th><th>Diary entries</th><th>Crop cutoff</th><th>Avg WAPE</th></tr></thead><tbody>${rows}</tbody></table></section>`, session);
}

function sameOrigin(request) {
  const origin = request.headers.origin;
  if (!origin) return true;
  try { return new URL(origin).host === request.headers.host; } catch { return false; }
}

function numeric(value) {
  if (value === '' || value == null) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) throw Object.assign(new Error('A numeric value is invalid.'), { statusCode: 400 });
  return parsed;
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host || 'localhost'}`);
    if (url.pathname === '/assets/app.css' && request.method === 'GET') return send(response, 200, css, { 'Content-Type': 'text/css; charset=utf-8', 'Cache-Control': 'public,max-age=3600' });
    if (url.pathname === '/health' && request.method === 'GET') return send(response, 200, JSON.stringify({ status: 'ok' }), { 'Content-Type': 'application/json; charset=utf-8' });
    const session = sessionFromRequest(db, request);

    if (url.pathname === '/login' && request.method === 'GET') {
      if (session) return redirect(response, '/dashboard');
      return send(response, 200, loginPage());
    }
    if (url.pathname.startsWith('/access/') && request.method === 'GET') {
      const token = decodeURIComponent(url.pathname.slice('/access/'.length));
      if (!/^[A-Za-z0-9_-]{40,100}$/.test(token)) return send(response, 404, loginPage('This access link is invalid.'));
      const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
      const link = db.prepare(`SELECT a.id AS access_link_id,u.* FROM access_links a JOIN users u ON u.id=a.user_id WHERE a.token_hash=? AND a.active=1 AND u.active=1`).get(tokenHash);
      if (!link) return send(response, 404, loginPage('This access link is invalid or has been replaced.'));
      db.prepare('UPDATE access_links SET last_used_at=? WHERE id=?').run(new Date().toISOString(), link.access_link_id);
      const created = createSession(db, link.id);
      return redirect(response, '/dashboard', { 'Set-Cookie': cookieHeader(created.token, created.expires) });
    }
    if (!session) return redirect(response, '/login');

    if (request.method === 'POST') {
      if (!sameOrigin(request)) throw Object.assign(new Error('Invalid request origin.'), { statusCode: 403 });
    }
    if (url.pathname === '/logout' && request.method === 'POST') {
      const form = await readForm(request);
      if (!safeEqual(form.csrf, session.csrf_token)) throw Object.assign(new Error('Invalid security token.'), { statusCode: 403 });
      destroySession(db, request);
      return redirect(response, '/login', { 'Set-Cookie': clearCookie() });
    }
    if ((url.pathname === '/' || url.pathname === '/dashboard') && request.method === 'GET') return send(response, 200, dashboardPage(session, url));
    if (url.pathname === '/workforce' && request.method === 'GET') return send(response, 200, workforcePage(session, url));
    if (url.pathname === '/practice' && request.method === 'GET') return send(response, 200, practicePage(session, url));
    if (url.pathname === '/practice' && request.method === 'POST') {
      const form = await readForm(request);
      if (!safeEqual(form.csrf, session.csrf_token)) throw Object.assign(new Error('Invalid security token.'), { statusCode: 403 });
      const estate = allowedEstate(session, form.estate);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(form.entry_date || '') || !form.field_name || !form.activity_type) throw Object.assign(new Error('Date, field and activity are required.'), { statusCode: 400 });
      db.prepare(`INSERT INTO practice_entries(estate,entry_date,division,field_name,activity_type,product,quantity,unit,labour_count,cost_lkr,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`)
        .run(estate, form.entry_date, form.division || null, form.field_name.trim(), form.activity_type, form.product || null, numeric(form.quantity), form.unit || null, numeric(form.labour_count), numeric(form.cost_lkr), form.notes || null, session.id, new Date().toISOString());
      return redirect(response, `/practice?estate=${encodeURIComponent(estate)}&message=${encodeURIComponent('Practice entry saved.')}`);
    }
    if (url.pathname === '/fields' && request.method === 'GET') return send(response, 200, fieldsPage(session, url));
    if (url.pathname === '/fields' && request.method === 'POST') {
      const form = await readForm(request);
      if (!safeEqual(form.csrf, session.csrf_token)) throw Object.assign(new Error('Invalid security token.'), { statusCode: 403 });
      const estate = allowedEstate(session, form.estate);
      if (!form.field_name) throw Object.assign(new Error('Field name is required.'), { statusCode: 400 });
      db.prepare(`INSERT INTO field_master(estate,division,field_name,area_ha,elevation_m,cultivar,bush_age_years,last_pruning_date,soil_type,active,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,1,?,?) ON CONFLICT(estate,division,field_name) DO UPDATE SET area_ha=excluded.area_ha,elevation_m=excluded.elevation_m,cultivar=excluded.cultivar,bush_age_years=excluded.bush_age_years,last_pruning_date=excluded.last_pruning_date,soil_type=excluded.soil_type,active=1,updated_by=excluded.updated_by,updated_at=excluded.updated_at`)
        .run(estate, form.division || '', form.field_name.trim(), numeric(form.area_ha), form.elevation_m === '' ? null : Number(form.elevation_m), form.cultivar || null, numeric(form.bush_age_years), form.last_pruning_date || null, form.soil_type || null, session.id, new Date().toISOString());
      return redirect(response, `/fields?estate=${encodeURIComponent(estate)}&message=${encodeURIComponent('Field master saved.')}`);
    }
    if (url.pathname === '/actuals' && request.method === 'POST') {
      const form = await readForm(request);
      if (!safeEqual(form.csrf, session.csrf_token)) throw Object.assign(new Error('Invalid security token.'), { statusCode: 403 });
      const estate = allowedEstate(session, form.estate);
      if (!/^\d{4}-\d{2}-\d{2}$/.test(form.actual_date || '')) throw Object.assign(new Error('A valid actual date is required.'), { statusCode: 400 });
      const cropKg = numeric(form.crop_kg);
      if (cropKg == null) throw Object.assign(new Error('Actual crop kilograms are required.'), { statusCode: 400 });
      db.prepare(`INSERT INTO daily_actuals(estate,actual_date,crop_kg,source,updated_by,updated_at) VALUES(?,?,?,'manager entry',?,?) ON CONFLICT(estate,actual_date) DO UPDATE SET crop_kg=excluded.crop_kg,source=excluded.source,updated_by=excluded.updated_by,updated_at=excluded.updated_at`)
        .run(estate, form.actual_date, cropKg, session.id, new Date().toISOString());
      return redirect(response, `/dashboard?estate=${encodeURIComponent(estate)}&view=daily&range=month`);
    }
    if (url.pathname === '/admin' && request.method === 'GET') return send(response, 200, adminPage(session, url));
    return send(response, 404, page('Not found', '<main class="error-page"><h1>404</h1><p>The requested page was not found.</p></main>'));
  } catch (error) {
    const status = error.statusCode || 500;
    if (status >= 500) console.error(error);
    return send(response, status, page('Request error', `<main class="error-page"><h1>${status}</h1><p>${e(status >= 500 ? 'An unexpected server error occurred.' : error.message)}</p><a href="/dashboard">Return to dashboard</a></main>`));
  }
});

server.listen(port, host, () => console.log(`TTE Crop Intelligence portal running at http://${host}:${port}`));

export { server };
