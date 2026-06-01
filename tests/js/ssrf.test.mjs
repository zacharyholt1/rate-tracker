// Tests for the Node SSRF guards. No network — exercises the pure policy logic
// that runs before any request is made.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  hostIsAllowed,
  isPublicIp,
  assertUrlAllowed,
  FetchError,
  ALLOWED_DOMAINS,
} from '../../netlify/functions/_lib/ssrf.mjs';

test('allowlist shared with Python config', () => {
  assert.ok(ALLOWED_DOMAINS.includes('rba.gov.au'));
  assert.ok(ALLOWED_DOMAINS.includes('federalreserve.gov'));
});

test('hostIsAllowed accepts known domains and subdomains', () => {
  assert.ok(hostIsAllowed('rba.gov.au'));
  assert.ok(hostIsAllowed('www.rba.gov.au'));
  assert.ok(hostIsAllowed('fred.stlouisfed.org'));
});

test('hostIsAllowed rejects unknown + suffix-confusion', () => {
  assert.ok(!hostIsAllowed('evil.example'));
  assert.ok(!hostIsAllowed('rba.gov.au.evil.example'));
  assert.ok(!hostIsAllowed('notrba.gov.au'));
});

test('isPublicIp blocks private / loopback / metadata / reserved IPv4', () => {
  for (const ip of [
    '127.0.0.1',        // loopback
    '169.254.169.254',  // cloud metadata
    '10.0.0.5',         // RFC1918
    '172.16.5.4',       // RFC1918
    '192.168.1.1',      // RFC1918
    '100.64.0.1',       // CGNAT
    '0.0.0.0',          // unspecified
    '224.0.0.1',        // multicast
  ]) {
    assert.ok(!isPublicIp(ip), `${ip} should be blocked`);
  }
});

test('isPublicIp allows normal public IPv4', () => {
  assert.ok(isPublicIp('23.45.67.89'));
  assert.ok(isPublicIp('8.8.8.8'));
});

test('isPublicIp blocks private IPv6 + mapped v4', () => {
  assert.ok(!isPublicIp('::1'));
  assert.ok(!isPublicIp('fe80::1'));
  assert.ok(!isPublicIp('fd00::1'));
  assert.ok(!isPublicIp('::ffff:127.0.0.1'));
  assert.ok(isPublicIp('2606:4700:4700::1111'));
});

test('assertUrlAllowed rejects non-https', () => {
  assert.throws(() => assertUrlAllowed('http://www.rba.gov.au/x'), FetchError);
});

test('assertUrlAllowed rejects off-allowlist host', () => {
  assert.throws(() => assertUrlAllowed('https://evil.example/x'), FetchError);
});

test('assertUrlAllowed accepts a valid allowlisted https URL', () => {
  const u = assertUrlAllowed('https://www.rba.gov.au/media-releases/2025/');
  assert.equal(u.hostname, 'www.rba.gov.au');
});
