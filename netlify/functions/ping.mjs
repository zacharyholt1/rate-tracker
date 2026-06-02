// Canary function — the simplest possible Netlify function.
//
// No imports, no file I/O, no env, no network. Its only job is to answer the
// question: "can this site run ANY function at all?"
//
//   GET /.netlify/functions/ping  ->  200 {"pong":true,...}
//
// If even THIS returns 502, the problem is the Netlify Functions deployment
// itself (functions dir not detected, runtime misconfigured) — not our code.
// If this works but leaderboard 502s, the problem is specific to leaderboard
// (its imports or data files).

export async function handler() {
  return {
    statusCode: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pong: true, node: process.version, ts: Date.now() }),
  };
}
