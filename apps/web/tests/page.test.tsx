import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { HomePage } from '@/components/home-page';
import { t } from '@/messages/t';

import { jsonResponse, renderWithProviders, testUser } from './helpers';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('authenticated home', () => {
  it('renders the organisation name in the shell context via the home greeting', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() => Promise.resolve(jsonResponse({ status: 'ok' }))),
    );

    renderWithProviders(<HomePage user={testUser} />);

    expect(
      screen.getByRole('heading', {
        level: 1,
        name: t('home.title', { name: testUser.full_name }),
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { level: 2, name: t('home.systemSectionTitle') }),
    ).toBeInTheDocument();
  });
});
