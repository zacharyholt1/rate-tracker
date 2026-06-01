// Netlify build step.
//
//  1. Copy ONLY the public data files into site/data (the timeline's data).
//     rollups.json is deliberately excluded — it's the leaderboard data and is
//     served only through the auth-gated function, never as a static file.
//  2. Write site/config.js with the PUBLIC Supabase config (URL + anon key).
//     These are public by design; the secret keys never touch the frontend.

import { mkdirSync, copyFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

// --- 1. public data subset ---
const PUBLIC_DATA = [
  'decisions.json',
  'indicators.json',
  'forecasts.json',
  'forecasters.json',
  'scores.json',
];
mkdirSync(join(root, 'site', 'data'), { recursive: true });
for (const f of PUBLIC_DATA) {
  copyFileSync(join(root, 'data', f), join(root, 'site', 'data', f));
}

// --- 2. public config ---
const config = {
  SUPABASE_URL: process.env.SUPABASE_URL || '',
  SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY || '',
};
writeFileSync(
  join(root, 'site', 'config.js'),
  `window.RT_CONFIG = ${JSON.stringify(config)};\n`
);

console.log('build: copied', PUBLIC_DATA.length, 'public data files; wrote config.js');
if (!config.SUPABASE_URL) console.warn('build: SUPABASE_URL not set — auth will be disabled');
