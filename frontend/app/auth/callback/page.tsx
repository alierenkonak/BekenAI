'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ensureBootstrapped, FullScreenMessage } from '@/components/app/auth';
import { Spinner } from '@/components/icons';
import { AUTH_CONFIGURED } from '@/lib/config';
import { describeError } from '@/lib/format';
import { useI18n } from '@/lib/i18n/client';
import { getSupabase } from '@/lib/supabase';

/** Supabase exchanges the PKCE `?code=` on client init; we only wait for the session. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const { m } = useI18n();
  // Kept as data, not text, so a language switch on this screen still shows the right words.
  const [error, setError] = useState<{ text: string } | { code: unknown } | 'unconfigured' | 'failed' | null>(() =>
    AUTH_CONFIGURED ? null : 'unconfigured',
  );

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(async ({ data, error: sessionError }) => {
      if (!active) return;
      const params = new URLSearchParams(window.location.search);
      if (sessionError || !data.session) {
        const description = params.get('error_description');
        setError(description ? { text: description } : 'failed');
        return;
      }
      try {
        await ensureBootstrapped(data.session.user.id);
        router.replace('/sohbet');
      } catch (bootstrapError) {
        if (active) setError({ code: bootstrapError });
      }
    });
    return () => {
      active = false;
    };
  }, [router]);

  if (error) {
    return (
      <FullScreenMessage title={m.auth.callbackTitle}>
        {error === 'unconfigured'
          ? m.auth.callbackUnconfigured
          : error === 'failed'
            ? m.auth.callbackFailed
            : 'text' in error
              ? error.text
              : describeError(error.code, m)}
        <Link href="/giris" className="mt-5 flex h-9 items-center rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg no-underline">
          {m.auth.backToSignIn}
        </Link>
      </FullScreenMessage>
    );
  }
  return (
    <div className="flex h-dvh items-center justify-center gap-3 text-sm text-fg3" role="status">
      <Spinner />
      {m.auth.completing}
    </div>
  );
}
