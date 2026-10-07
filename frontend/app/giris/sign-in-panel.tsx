'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Spinner } from '@/components/icons';
import { AUTH_CONFIGURED } from '@/lib/config';
import { useI18n } from '@/lib/i18n/client';
import { rich } from '@/lib/i18n/rich';
import { getSupabase } from '@/lib/supabase';

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  );
}

export function SignInPanel() {
  const router = useRouter();
  const { m } = useI18n();
  const t = m.signIn;
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (active && data.session) router.replace('/sohbet');
    });
    return () => {
      active = false;
    };
  }, [router]);

  const signIn = async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    setPending(true);
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
    if (signInError) {
      setPending(false);
      setError(t.googleFailed);
    }
  };

  return (
    <>
      <div className="flex flex-col gap-2">
        <h2 className="m-0 text-[26px] font-semibold tracking-[-0.02em]">{t.heading}</h2>
        <p className="m-0 text-[14.5px] leading-normal text-fg2">
          {t.lead}
        </p>
      </div>
      {AUTH_CONFIGURED ? (
        <button
          type="button"
          onClick={() => void signIn()}
          disabled={pending}
          className="flex h-[46px] items-center justify-center gap-2.5 rounded-[10px] border border-line-strong bg-surface text-[14.5px] font-medium text-fg shadow-soft transition-colors hover:bg-hover disabled:opacity-60"
        >
          {pending ? <Spinner size={18} /> : <GoogleMark />}
          {t.google}
        </button>
      ) : (
        <p role="alert" className="m-0 rounded-[10px] border border-doc-line bg-doc-bg px-4 py-3 text-[13.5px] leading-normal text-doc">
          {rich(t.notConfigured, {
            env: <code className="font-mono">.env</code>,
            url: <code className="font-mono">SUPABASE_URL</code>,
            key: <code className="font-mono">SUPABASE_PUBLISHABLE_KEY</code>,
          })}
        </p>
      )}
      {error && (
        <p role="alert" className="m-0 text-[13px] text-err">
          {error}
        </p>
      )}
      <p className="m-0 text-[12.5px] leading-relaxed text-fg3">
        {t.consent}{' '}
        <Link href="/" className="text-fg2 underline">
          {t.backHome}
        </Link>
      </p>
    </>
  );
}
