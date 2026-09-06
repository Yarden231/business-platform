'use client';

import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { he } from '@/messages/he';

/**
 * Same-origin path. The browser must never address the API host directly, so
 * this is relative on purpose — the Next.js rewrite forwards it to the API
 * (ADR-0005).
 */
export const API_HEALTH_PATH = '/api/v1/healthz';

type HealthState = 'checking' | 'online' | 'offline';

const STATE_LABEL: Record<HealthState, string> = {
  checking: he.apiHealth.checking,
  online: he.apiHealth.online,
  offline: he.apiHealth.offline,
};

const STATE_VARIANT: Record<HealthState, 'secondary' | 'success' | 'destructive'> = {
  checking: 'secondary',
  online: 'success',
  offline: 'destructive',
};

function isHealthyPayload(payload: unknown): boolean {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'status' in payload &&
    payload.status === 'ok'
  );
}

export function ApiHealthStatus(): React.JSX.Element {
  const [state, setState] = useState<HealthState>('checking');

  useEffect(() => {
    const controller = new AbortController();

    async function check(): Promise<void> {
      try {
        const response = await fetch(API_HEALTH_PATH, {
          signal: controller.signal,
          cache: 'no-store',
        });
        const payload: unknown = response.ok ? await response.json() : null;
        setState(response.ok && isHealthyPayload(payload) ? 'online' : 'offline');
      } catch {
        if (!controller.signal.aborted) {
          setState('offline');
        }
      }
    }

    void check();

    return () => {
      controller.abort();
    };
  }, []);

  return (
    <section
      aria-live="polite"
      className="flex items-center justify-between gap-4 rounded-lg border p-4"
    >
      <div className="space-y-1 text-start">
        <h2 className="text-sm font-medium">{he.apiHealth.title}</h2>
        {/* A URL is technical LTR text inside an RTL document. */}
        <p dir="ltr" className="text-muted-foreground font-mono text-xs">
          GET {API_HEALTH_PATH}
        </p>
      </div>
      <Badge variant={STATE_VARIANT[state]}>{STATE_LABEL[state]}</Badge>
    </section>
  );
}
