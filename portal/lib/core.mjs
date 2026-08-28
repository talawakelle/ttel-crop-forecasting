import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';

export function openDatabase(dbPath) {
  fs.mkdirSync(path.dirname(dbPath), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY,
      username TEXT NOT NULL UNIQUE COLLATE NOCASE,
      role TEXT NOT NULL CHECK(role IN ('admin','manager')),
      estate TEXT,
      display_name TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS one_manager_per_estate
      ON users(estate) WHERE role = 'manager' AND active = 1;
    CREATE TABLE IF NOT EXISTS sessions (
      token_hash TEXT PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      csrf_token TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS access_links (
      id INTEGER PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT NOT NULL UNIQUE,
      label TEXT NOT NULL,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      last_used_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_access_link_per_user
      ON access_links(user_id) WHERE active = 1;
    CREATE TABLE IF NOT EXISTS practice_entries (
      id INTEGER PRIMARY KEY,
      estate TEXT NOT NULL,
      entry_date TEXT NOT NULL,
      division TEXT,
      field_name TEXT NOT NULL,
      activity_type TEXT NOT NULL,
      product TEXT,
      quantity REAL,
      unit TEXT,
      labour_count REAL,
      cost_lkr REAL,
      notes TEXT,
      created_by INTEGER NOT NULL REFERENCES users(id),
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS practice_estate_date ON practice_entries(estate, entry_date);
    CREATE TABLE IF NOT EXISTS field_master (
      id INTEGER PRIMARY KEY,
      estate TEXT NOT NULL,
      division TEXT,
      field_name TEXT NOT NULL,
      area_ha REAL,
      elevation_m REAL,
      cultivar TEXT,
      bush_age_years REAL,
      last_pruning_date TEXT,
      soil_type TEXT,
      active INTEGER NOT NULL DEFAULT 1,
      updated_by INTEGER NOT NULL REFERENCES users(id),
      updated_at TEXT NOT NULL,
      UNIQUE(estate, division, field_name)
    );
    CREATE TABLE IF NOT EXISTS daily_actuals (
      id INTEGER PRIMARY KEY,
      estate TEXT NOT NULL,
      actual_date TEXT NOT NULL,
      crop_kg REAL NOT NULL CHECK(crop_kg >= 0),
      source TEXT NOT NULL DEFAULT 'manager entry',
      updated_by INTEGER NOT NULL REFERENCES users(id),
      updated_at TEXT NOT NULL,
      UNIQUE(estate, actual_date)
    );
    CREATE INDEX IF NOT EXISTS daily_actual_estate_date ON daily_actuals(estate, actual_date);
  `);
  db.exec("DELETE FROM sessions WHERE expires_at < datetime('now')");
  return db;
}

export function createSession(db, userId, hours = 8) {
  const token = crypto.randomBytes(32).toString('base64url');
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  const csrf = crypto.randomBytes(24).toString('base64url');
  const created = new Date();
  const expires = new Date(created.getTime() + hours * 3600_000);
  db.prepare('INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)')
    .run(tokenHash, userId, csrf, created.toISOString(), expires.toISOString());
  return { token, csrf, expires };
}

export function sessionFromRequest(db, request) {
  const cookies = parseCookies(request.headers.cookie || '');
  const token = cookies.tte_session;
  if (!token) return null;
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  const row = db.prepare(`
    SELECT s.token_hash,s.csrf_token,s.expires_at,u.*
    FROM sessions s JOIN users u ON u.id=s.user_id
    WHERE s.token_hash=? AND s.expires_at>? AND u.active=1
  `).get(tokenHash, new Date().toISOString());
  return row || null;
}

export function destroySession(db, request) {
  const token = parseCookies(request.headers.cookie || '').tte_session;
  if (!token) return;
  db.prepare('DELETE FROM sessions WHERE token_hash=?')
    .run(crypto.createHash('sha256').update(token).digest('hex'));
}

export function parseCookies(text) {
  const result = {};
  for (const part of text.split(';')) {
    const index = part.indexOf('=');
    if (index > 0) result[part.slice(0, index).trim()] = decodeURIComponent(part.slice(index + 1).trim());
  }
  return result;
}

export function safeEqual(a, b) {
  const left = Buffer.from(String(a || ''));
  const right = Buffer.from(String(b || ''));
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[character]);
}

export async function readForm(request, limit = 1_000_000) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('Request is too large.'), { statusCode: 413 });
    chunks.push(chunk);
  }
  return Object.fromEntries(new URLSearchParams(Buffer.concat(chunks).toString('utf8')));
}

export function parseCsv(text) {
  const rows = [];
  let row = [], value = '', quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { value += '"'; i += 1; }
      else if (c === '"') quoted = false;
      else value += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(value); value = ''; }
    else if (c === '\n') { row.push(value.replace(/\r$/, '')); rows.push(row); row = []; value = ''; }
    else value += c;
  }
  if (value.length || row.length) { row.push(value.replace(/\r$/, '')); rows.push(row); }
  if (!rows.length) return [];
  const header = rows.shift();
  return rows.filter(r => r.some(Boolean)).map(r => Object.fromEntries(header.map((h, i) => [h, r[i] ?? ''])));
}

export function readCsvFile(filePath) {
  return parseCsv(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''));
}

export function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function slugify(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, '');
}
