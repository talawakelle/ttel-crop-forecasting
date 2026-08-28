import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';
import {
  csvEscape, openDatabase, readCsvFile, slugify,
} from './lib/core.mjs';

const portalRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(portalRoot, '..');
const dbPath = process.env.PORTAL_DB || path.join(portalRoot, 'data', 'portal.db');
const credentialsPath = process.env.PORTAL_ACCESS_LINKS || path.join(portalRoot, 'private', 'estate_access_links.csv');
const portfolioPath = path.join(projectRoot, 'outputs', 'portfolio_summary.csv');
const rotateLinks = process.argv.includes('--rotate-links');
const baseUrl = (process.env.PORTAL_BASE_URL || 'http://127.0.0.1:8080').replace(/\/$/, '');

if (!fs.existsSync(portfolioPath)) throw new Error(`Portfolio summary not found: ${portfolioPath}`);
const estates = readCsvFile(portfolioPath).map(row => row.estate).filter(Boolean).sort();
if (estates.length !== 33) throw new Error(`Expected 33 estates, found ${estates.length}.`);

const db = openDatabase(dbPath);
const now = new Date().toISOString();
const accessLinks = [];
const users = [
  { username: 'portfolio.admin', role: 'admin', estate: null, displayName: 'Portfolio Administrator' },
  ...estates.map(estate => ({
    username: `manager.${slugify(estate)}`,
    role: 'manager',
    estate,
    displayName: `${estate} Estate Manager`,
  })),
];

const find = db.prepare('SELECT id FROM users WHERE username=?');
const insert = db.prepare(`
  INSERT INTO users(username,role,estate,display_name,active,created_at,updated_at)
  VALUES(?,?,?,?,1,?,?)
`);
const update = db.prepare(`UPDATE users SET role=?,estate=?,display_name=?,active=1,updated_at=? WHERE username=?`);

for (const account of users) {
  const existing = find.get(account.username);
  if (existing) update.run(account.role, account.estate, account.displayName, now, account.username);
  else insert.run(account.username, account.role, account.estate, account.displayName, now, now);
}

if (rotateLinks) db.exec('UPDATE access_links SET active=0 WHERE active=1');
const accounts = db.prepare('SELECT id,username,role,estate FROM users WHERE active=1 ORDER BY role,estate').all();
for (const account of accounts) {
  const active = db.prepare('SELECT id FROM access_links WHERE user_id=? AND active=1').get(account.id);
  if (active) continue;
  const token = crypto.randomBytes(32).toString('base64url');
  const tokenHash = crypto.createHash('sha256').update(token).digest('hex');
  db.prepare('INSERT INTO access_links(user_id,token_hash,label,active,created_at) VALUES(?,?,?,1,?)')
    .run(account.id, tokenHash, account.role === 'admin' ? 'Portfolio administrator' : `${account.estate} estate`, now);
  accessLinks.push({
    role: account.role,
    estate: account.estate || 'ALL ESTATES',
    password_required: 'NO',
    secure_access_link: `${baseUrl}/access/${token}`,
  });
}

if (accessLinks.length) {
  fs.mkdirSync(path.dirname(credentialsPath), { recursive: true });
  const columns = Object.keys(accessLinks[0]);
  const output = [columns.join(','), ...accessLinks.map(row => columns.map(c => csvEscape(row[c])).join(','))].join('\n') + '\n';
  fs.writeFileSync(credentialsPath, output, { mode: 0o600 });
}

const managerCount = db.prepare("SELECT COUNT(*) AS count FROM users WHERE role='manager' AND active=1").get().count;
const adminCount = db.prepare("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND active=1").get().count;
console.log(JSON.stringify({
  database: dbPath,
  active_manager_accounts: managerCount,
  active_admin_accounts: adminCount,
  password_entry_required: false,
  access_links_written: accessLinks.length,
  access_links_file: accessLinks.length ? credentialsPath : 'unchanged; use --rotate-links only when intentionally replacing every access link',
}, null, 2));
