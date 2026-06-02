// scrape_url — on-demand source ingestion for signed-in users.
//
// Flow (every step is a gate):
//   1. POST only
//   2. caller must present a valid Supabase JWT (signed-in user)
//   3. URL must pass the SSRF-guarded allowlist + private-IP checks
//   4. fetch with size/timeout caps, no redirects
//   5. STAGE the result (status 'pending') — never write to live data
//
// Promotion from staging into live data happens out-of-band through the normal
// validated Python pipeline, with human review. So a hostile URL, at worst,
// lands a pending row a reviewer can reject.

import { requireUser, AuthError } from './_lib/auth.mjs';
import { safeFetch, assertUrlAllowed, FetchError } from './_lib/ssrf.mjs';
import { stageSubmission } from './_lib/submissions.mjs';

const json = (statusCode, obj) => ({
  statusCode,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(obj),
});

export async function handler(event) {
  // Top-level guard so an unexpected throw can never surface as a 502.
  try {
    return await handle(event);
  } catch (e) {
    console.error('Unhandled scrape_url error:', e && e.stack ? e.stack : e);
    return json(500, { error: 'Internal error' });
  }
}

async function handle(event) {
  if (event.httpMethod !== 'POST') {
    return json(405, { error: 'Method not allowed' });
  }

  // 1. Require a signed-in user.
  let user;
  try {
    user = await requireUser(event.headers || {});
  } catch (e) {
    if (e instanceof AuthError) return json(401, { error: e.message });
    console.error('Auth verification error:', e && e.stack ? e.stack : e);
    return json(500, { error: 'Auth verification failed' });
  }

  // 2. Parse + validate input.
  let url;
  try {
    ({ url } = JSON.parse(event.body || '{}'));
  } catch {
    return json(400, { error: 'Invalid JSON body' });
  }
  if (!url || typeof url !== 'string') {
    return json(400, { error: 'A "url" string is required' });
  }

  // 3. Cheap allowlist/scheme check before any network work, for a clean error.
  let parsed;
  try {
    parsed = assertUrlAllowed(url);
  } catch (e) {
    if (e instanceof FetchError) {
      return json(422, { error: e.message, allowlisted: false });
    }
    throw e;
  }

  // 4. SSRF-guarded fetch.
  let result;
  try {
    result = await safeFetch(url);
  } catch (e) {
    if (e instanceof FetchError) return json(422, { error: e.message });
    throw e;
  }

  // 5. Stage for review — never live.
  try {
    const submission = await stageSubmission({
      url,
      host: parsed.hostname,
      body: result.body,
      contentType: result.contentType,
      userId: user.sub,
    });
    return json(202, {
      status: 'staged',
      message: 'Thanks — your source was captured and is pending review.',
      submission_id: submission?.id ?? null,
    });
  } catch (e) {
    // Don't leak internal config details to the client.
    console.error('Staging error:', e.message);
    return json(500, { error: 'Could not stage submission' });
  }
}
