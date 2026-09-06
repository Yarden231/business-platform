import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn(), push: vi.fn() }),
}));

import { AppShell } from '@/components/shell/app-shell';
import { t } from '@/messages/t';

import { renderWithProviders, testUser } from './helpers';

describe('AppShell', () => {
  it('renders the skip link, navigation and user menu', () => {
    renderWithProviders(
      <AppShell user={{ ...testUser, full_name: 'Dana Admin' }}>
        <p>content</p>
      </AppShell>,
    );

    expect(screen.getByText(t('app.skipToContent'))).toBeInTheDocument();
    expect(
      screen.getByRole('navigation', { name: t('shell.navigationLabel') }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('shell.navigation.home') })).toHaveAttribute(
      'href',
      '/',
    );
    expect(screen.getByRole('main', { name: t('shell.mainLabel') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('shell.userMenuLabel') })).toBeInTheDocument();
  });
});
