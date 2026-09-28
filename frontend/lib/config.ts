export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');
export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
export const SUPABASE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || '';

/** Sign-in needs both public Supabase values; the landing page works without them. */
export const AUTH_CONFIGURED = Boolean(SUPABASE_URL && SUPABASE_PUBLISHABLE_KEY);

export const CHAT_MESSAGE_MAX = 4000;
export const CASE_FILE_MAX_BYTES = 50 * 1024 * 1024;
export const GITHUB_URL = process.env.NEXT_PUBLIC_GITHUB_URL || 'https://github.com/alierenkonak';
export const LINKEDIN_URL = process.env.NEXT_PUBLIC_LINKEDIN_URL || 'https://www.linkedin.com/in/alierenkonak/';
