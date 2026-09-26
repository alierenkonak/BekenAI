import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import type { NextConfig } from 'next';

// The repo keeps one .env at its root for every service. Only these public values
// are read from it; secrets in the same file never reach the Next.js build.
const PUBLIC_ROOT_KEYS = ['SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY', 'NEXT_PUBLIC_API_URL'] as const;

// `next dev` may run from frontend/ (make frontend-dev) or from the repo root (`next dev frontend`).
const projectDir = existsSync(path.join(process.cwd(), 'next.config.ts'))
  ? process.cwd()
  : path.join(process.cwd(), 'frontend');

function readRootEnv(): Partial<Record<(typeof PUBLIC_ROOT_KEYS)[number], string>> {
  let text: string;
  try {
    text = readFileSync(path.join(projectDir, '..', '.env'), 'utf8');
  } catch {
    return {};
  }
  const values: Partial<Record<(typeof PUBLIC_ROOT_KEYS)[number], string>> = {};
  for (const line of text.split(/\r?\n/)) {
    const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (!match) continue;
    const key = match[1] as (typeof PUBLIC_ROOT_KEYS)[number];
    if (!PUBLIC_ROOT_KEYS.includes(key)) continue;
    values[key] = match[2].replace(/^(['"])(.*)\1$/, '$2');
  }
  return values;
}

const root = readRootEnv();

const nextConfig: NextConfig = {
  turbopack: {
    root: projectDir,
  },
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL || root.SUPABASE_URL || '',
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:
      process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || root.SUPABASE_PUBLISHABLE_KEY || '',
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || root.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
    NEXT_PUBLIC_GITHUB_URL: process.env.NEXT_PUBLIC_GITHUB_URL || '',
    NEXT_PUBLIC_LINKEDIN_URL: process.env.NEXT_PUBLIC_LINKEDIN_URL || '',
  },
};

export default nextConfig;
