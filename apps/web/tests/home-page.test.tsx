import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { HomePage } from '@/components/home-page';
import { t } from '@/messages/t';

import { jsonResponse, renderWithProviders, testUser } from './helpers';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('HomePage', () => {
  it('greets the authenticated user in Hebrew', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse({ status: 'ok' }))),
    );

    renderWithProviders(<HomePage user={{ ...testUser, full_name: 'Dana Admin' }} />);

    expect(
      screen.getByRole('heading', { level: 1, name: t('home.title', { name: 'Dana Admin' }) }),
    ).toBeInTheDocument();
    expect(screen.getByText(t('home.accountSectionTitle'))).toBeInTheDocument();
    expect(screen.getByText(t('shell.roles.ADMIN'))).toBeInTheDocument();
    expect(screen.getByText(t('home.scopeNotice'))).toBeInTheDocument();
  });
});
