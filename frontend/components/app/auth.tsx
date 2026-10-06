'use client';

import type { User } from '@supabase/supabase-js';
import { useRouter } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { LogoMark } from '@/components/brand';
import { Spinner } from '@/components/icons';
import { api } from '@/lib/api';
import { AUTH_CONFIGURED } from '@/lib/config';
import { describeError } from '@/lib/format';
import { getSupabase } from '@/lib/supabase';

type AuthState =
  | { status: 'loading' }
  | { status: 'unconfigured' }
  | { status: 'signed-out' }
  | { status: 'error'; message: string }
  | { status: 'ready'; user: User };

type AuthContextValue = { user: User; signOut: () => Promise<void> };

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthGate>');
  return value;
}

const BOOTSTRAP_KEY = 'bekenai-bootstrapped';

/** Creates the profile/workspace once per browser session; the endpoint is idempotent. */
export async function ensureBootstrapped(userId: string): Promise<void> {
  try {
    if (sessionStorage.getItem(BOOTSTRAP_KEY) === userId) return;
  } catch {
    // Storage may be unavailable; bootstrapping again is harmless.
  }
  await api.bootstrap();
  try {
    sessionStorage.setItem(BOOTSTRAP_KEY, userId);
  } catch {
    // Ignored for the same reason as above.
  }
}

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<AuthState>(() =>
    AUTH_CONFIGURED ? { status: 'loading' } : { status: 'unconfigured' },
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(async ({ data }) => {
      const session = data.session;
      if (!active) return;
      if (!session) {
        setState({ status: 'signed-out' });
        router.replace('/giris');
        return;
      }
      try {
        await ensureBootstrapped(session.user.id);
        if (active) setState({ status: 'ready', user: session.user });
      } catch (error) {
        if (active) setState({ status: 'error', message: describeError(error) });
      }
    });
    // Only react to sign-out here: calling Supabase from inside this callback can deadlock.
    const { data: subscription } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT' && active) {
        setState({ status: 'signed-out' });
        router.replace('/giris');
      }
    });
    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, [router, attempt]);

  const signOut = useCallback(async () => {
    try {
      sessionStorage.removeItem(BOOTSTRAP_KEY);
    } catch {
      // Nothing to clean up.
    }
    await getSupabase()?.auth.signOut();
  }, []);

  if (state.status === 'ready') {
    return <AuthContext.Provider value={{ user: state.user, signOut }}>{children}</AuthContext.Provider>;
  }
  if (state.status === 'unconfigured') {
    return (
      <FullScreenMessage title="Giriş yapılandırılmadı">
        Uygulamayı kullanmak için <code className="font-mono text-[13px]">SUPABASE_URL</code> ve{' '}
        <code className="font-mono text-[13px]">SUPABASE_PUBLISHABLE_KEY</code> değerlerini kökteki{' '}
        <code className="font-mono text-[13px]">.env</code> dosyasına ekleyip geliştirme sunucusunu yeniden başlatın.
      </FullScreenMessage>
    );
  }
  if (state.status === 'error') {
    return (
      <FullScreenMessage title="Çalışma alanı hazırlanamadı">
        {state.message}
        <button
          type="button"
          onClick={() => {
            setState({ status: 'loading' });
            setAttempt((value) => value + 1);
          }}
          className="mt-5 flex h-9 items-center rounded-[9px] bg-inv px-4 text-[13.5px] font-medium text-inv-fg"
        >
          Tekrar dene
        </button>
      </FullScreenMessage>
    );
  }
  return (
    <div className="flex h-dvh items-center justify-center gap-3 text-sm text-fg3" role="status">
      <Spinner />
      Oturum kontrol ediliyor…
    </div>
  );
}

export function FullScreenMessage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh items-center justify-center px-6">
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <LogoMark size={48} />
        <h1 className="m-0 text-xl font-semibold tracking-[-0.01em]">{title}</h1>
        <div className="flex flex-col items-center text-sm leading-relaxed text-fg2">{children}</div>
      </div>
    </div>
  );
}
