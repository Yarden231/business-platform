'use client';

import { useQuery } from '@tanstack/react-query';

import { Badge } from '@/components/ui/badge';
import { getHealth } from '@/lib/api/client';
import { API_PREFIX } from '@/lib/constants';
import { queryKeys } from '@/lib/api/query-keys';
import { t } from '@/messages/t';

export const API_HEALTH_PATH = `${API_PREFIX}/healthz`;

type HealthState = 'checking' | 'online' | 'offline';

const STATE_VARIANT: Record<HealthState, 'secondary' | 'success' | 'destructive'> = {
  checking: 'secondary',
  online: 'success',
  offline: 'destructive',
};

export function ApiHealthStatus(): React.JSX.Element {
  const health = useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => getHealth(signal),
    retry: false,
  });

  const state: HealthState = health.isPending
    ? 'checking'
    : health.isSuccess
      ? 'online'
      : 'offline';

  return (
    <section
      aria-live="polite"
      className="flex items-center justify-between gap-4 rounded-lg border p-4"
    >
      <div className="space-y-1 text-start">
        <h2 className="text-sm font-medium">{t('apiHealth.title')}</h2>
        <p dir="ltr" className="text-muted-foreground font-mono text-xs">
          GET {API_HEALTH_PATH}
        </p>
      </div>
      <Badge variant={STATE_VARIANT[state]}>{t(`apiHealth.${state}`)}</Badge>
    </section>
  );
}
