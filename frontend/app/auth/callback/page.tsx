'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { ensureBootstrapped, FullScreenMessage } from '@/components/app/auth';
import { Spinner } from '@/components/icons';
import { AUTH_CONFIGURED } from '@/lib/config';
import { describeError } from '@/lib/format';
import { getSupabase } from '@/lib/supabase';

/** Supabase exchanges the PKCE `?code=` on client init; we only wait for the session. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(() =>
    AUTH_CONFIGURED ? null : 'Giriş yapılandırılmadı: SUPABASE_URL ve SUPABASE_PUBLISHABLE_KEY değerleri eksik.',
  );

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(async ({ data, error: sessionError }) => {
      if (!active) return;
      const params = new URLSearchParams(window.location.search);
      if (sessionError || !data.session) {
        setError(params.get('error_description') || 'Giriş tamamlanamadı. Lütfen tekrar deneyin.');
        return;
      }
      try {
        await ensureBootstrapped(data.session.user.id);
        router.replace('/sohbet');
      } catch (bootstrapError) {
        if (active) setError(describeError(bootstrapError));
      }
    });
    return () => {
      active = false;
    };
  }, [router]);

  if (error) {
    return (
      <FullScreenMessage title="Giriş tamamlanamadı">
        {error}
        <Link href="/giris" className="mt-5 flex h-9 items-center rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg no-underline">
          Giriş sayfasına dön
        </Link>
      </FullScreenMessage>
    );
  }
  return (
    <div className="flex h-dvh items-center justify-center gap-3 text-sm text-fg3" role="status">
      <Spinner />
      Giriş tamamlanıyor…
    </div>
  );
}
