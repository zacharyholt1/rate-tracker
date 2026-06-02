// Staging store for user-submitted sources.
//
// scrape_url never writes to live data. It stages a submission in Supabase with
// status 'pending', for review and promotion through the normal validated
// Python pipeline. This keeps a stranger's URL from ever poisoning live scores.
//
// Uses the Supabase REST endpoint with the service-role key (server-only). No
// SDK dependency — just fetch.

import crypto from 'crypto';

export function contentHash(raw) {
  return 'sha256:' + crypto.createHash('sha256').update(raw).digest('hex');
}

// Insert a pending submission. Returns the created row.
export async function stageSubmission({ url, host, body, contentType, userId }) {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!base || !key) throw new Error('Supabase not configured');

  const row = {
    url,
    host,
    content_hash: contentHash(body),
    // Cap stored raw content; the reviewer can re-fetch for the full document.
    raw_excerpt: body.slice(0, 20000),
    content_type: contentType,
    submitted_by: userId,
    status: 'pending',
  };

  const resp = await fetch(`${base}/rest/v1/submissions`, {
    method: 'POST',
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      Prefer: 'return=representation',
    },
    body: JSON.stringify(row),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Staging failed (${resp.status}): ${text.slice(0, 200)}`);
  }
  const [created] = await resp.json();
  return created;
}
