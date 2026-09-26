'use client';

import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { AUTH_CONFIGURED, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from './config';

let client: SupabaseClient | null = null;

/** Browser-only Supabase client. PKCE keeps the OAuth code exchange off the URL fragment. */
export function getSupabase(): SupabaseClient | null {
  if (!AUTH_CONFIGURED || typeof window === 'undefined') return null;
  client ??= createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    auth: {
      flowType: 'pkce',
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return client;
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
