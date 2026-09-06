import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { API_HEALTH_PATH, ApiHealthStatus } from '@/components/api-health-status';
import { t } from '@/messages/t';

import { jsonResponse, renderWithProviders } from './helpers';

function stubFetch(implementation: typeof fetch): ReturnType<typeof vi.fn<typeof fetch>> {
  const fetchMock = vi.fn<typeof fetch>(implementation);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ApiHealthStatus', () => {
  it('reports the API as reachable when it answers with a healthy payload', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(jsonResponse({ status: 'ok' })));

    renderWithProviders(<ApiHealthStatus />);

    expect(await screen.findByText(t('apiHealth.online'))).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(API_HEALTH_PATH, expect.anything());
  });

  it('requests the API through the same-origin proxy path, never the API host', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(jsonResponse({ status: 'ok' })));

    renderWithProviders(<ApiHealthStatus />);
    await screen.findByText(t('apiHealth.online'));

    const [requestedUrl] = fetchMock.mock.calls[0] ?? [];
    expect(requestedUrl).toBe('/api/v1/healthz');
  });

  it('reports no connection when the request fails', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')));

    renderWithProviders(<ApiHealthStatus />);

    expect(await screen.findByText(t('apiHealth.offline'))).toBeInTheDocument();
  });

  it('reports no connection when the API answers with an error status', async () => {
    stubFetch(() => Promise.resolve(jsonResponse({ status: 'ok' }, { status: 503 })));

    renderWithProviders(<ApiHealthStatus />);

    expect(await screen.findByText(t('apiHealth.offline'))).toBeInTheDocument();
  });
});
