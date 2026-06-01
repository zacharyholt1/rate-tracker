// SSRF-guarded fetch for the on-demand scrape_url endpoint.
//
// This is the Node counterpart to scrapers/fetch.py and enforces the SAME
// policy, reading the SAME allowlist (config/allowed_domains.json). Defences:
//   * https only
//   * host must be on the shared allowlist
//   * DNS resolved up front; any private/loopback/link-local/reserved IP is
//     rejected (blocks 169.254.169.254 metadata, RFC1918, localhost)
//   * redirects not followed
//   * response size capped, request timed out
//
// Pure helpers are exported so they can be unit-tested without the network.

import dns from 'node:dns/promises';
import net from 'node:net';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load the shared allowlist (single source of truth with the Python side).
const CONFIG_PATH = join(__dirname, '..', '..', '..', 'config', 'allowed_domains.json');
export const ALLOWED_DOMAINS = JSON.parse(readFileSync(CONFIG_PATH, 'utf8')).allowed_domains;

export const USER_AGENT = 'rate-tracker/0.1 (+https://github.com/zacharyholt1/rate-tracker)';
export const MAX_BYTES = 5 * 1024 * 1024; // 5 MB
export const TIMEOUT_MS = 15000;

export class FetchError extends Error {}

export function hostIsAllowed(host) {
  host = String(host).toLowerCase().replace(/\.+$/, '');
  return ALLOWED_DOMAINS.some(
    (d) => host === d || host.endsWith('.' + d)
  );
}

// Reject any IP that isn't a normal public address.
export function isPublicIp(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split('.').map(Number);
    if (a === 0) return false;                         // unspecified / "this"
    if (a === 10) return false;                        // RFC1918
    if (a === 127) return false;                       // loopback
    if (a === 169 && b === 254) return false;          // link-local (metadata!)
    if (a === 172 && b >= 16 && b <= 31) return false; // RFC1918
    if (a === 192 && b === 168) return false;          // RFC1918
    if (a === 100 && b >= 64 && b <= 127) return false;// CGNAT RFC6598
    if (a >= 224) return false;                        // multicast / reserved
    return true;
  }
  if (net.isIPv6(ip)) {
    const x = ip.toLowerCase();
    if (x === '::1' || x === '::') return false;       // loopback / unspecified
    if (x.startsWith('fe80')) return false;            // link-local
    if (x.startsWith('fc') || x.startsWith('fd')) return false; // unique-local
    // IPv4-mapped ::ffff:a.b.c.d — validate the embedded v4.
    const m = x.match(/::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    if (m) return isPublicIp(m[1]);
    return true;
  }
  return false;
}

// Validate a URL against scheme + allowlist (no DNS). Throws FetchError.
export function assertUrlAllowed(rawUrl) {
  let u;
  try {
    u = new URL(rawUrl);
  } catch {
    throw new FetchError('Malformed URL');
  }
  if (u.protocol !== 'https:') throw new FetchError('Only https is allowed');
  if (!u.hostname) throw new FetchError('URL has no host');
  if (!hostIsAllowed(u.hostname)) {
    throw new FetchError(`Host ${u.hostname} is not on the allowlist`);
  }
  return u;
}

// Full validation including DNS resolution. Throws FetchError on any violation.
export async function assertFetchable(rawUrl) {
  const u = assertUrlAllowed(rawUrl);
  let addrs;
  try {
    addrs = await dns.lookup(u.hostname, { all: true });
  } catch (e) {
    throw new FetchError(`DNS resolution failed: ${e.message}`);
  }
  if (!addrs.length) throw new FetchError('No DNS records');
  for (const { address } of addrs) {
    if (!isPublicIp(address)) {
      throw new FetchError(`Refusing to fetch: resolves to non-public address ${address}`);
    }
  }
  return u;
}

// Fetch after passing every check. Returns { status, body, contentType }.
export async function safeFetch(rawUrl) {
  await assertFetchable(rawUrl);

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let resp;
  try {
    resp = await fetch(rawUrl, {
      method: 'GET',
      redirect: 'manual', // a redirect can't smuggle us off-allowlist
      signal: controller.signal,
      headers: { 'User-Agent': USER_AGENT, Accept: 'text/html,text/csv,*/*' },
    });
  } catch (e) {
    clearTimeout(timer);
    throw new FetchError(`Request failed: ${e.message}`);
  }
  clearTimeout(timer);

  if (resp.status >= 300 && resp.status < 400) {
    throw new FetchError(`Redirect not followed (${resp.status})`);
  }
  if (resp.status !== 200) throw new FetchError(`HTTP ${resp.status}`);

  // Read with a hard byte ceiling.
  const reader = resp.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.length;
    if (total > MAX_BYTES) {
      controller.abort();
      throw new FetchError(`Response exceeded ${MAX_BYTES} bytes`);
    }
    chunks.push(value);
  }
  const body = Buffer.concat(chunks).toString('utf8');
  return { status: resp.status, body, contentType: resp.headers.get('content-type') || '' };
}
