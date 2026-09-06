import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { UserMenu } from '@/components/shell/user-menu';
import { t } from '@/messages/t';

import { emptyResponse, renderWithProviders, testUser } from './helpers';

const replace = vi.fn();
const refresh = vi.fn();
const push = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, refresh, push }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  refresh.mockReset();
  push.mockReset();
});

describe('UserMenu', () => {
  it('exposes change-password and logout in Hebrew', async () => {
    const user = userEvent.setup();
    renderWithProviders(<UserMenu user={{ ...testUser, full_name: 'Dana Admin' }} />);

    await user.click(screen.getByRole('button', { name: t('shell.userMenuLabel') }));

    expect(await screen.findByText(t('shell.changePassword'))).toBeInTheDocument();
    expect(screen.getByText(t('auth.logout.action'))).toBeInTheDocument();
    expect(screen.getByText(t('shell.roles.ADMIN'))).toBeInTheDocument();
  });

  it('logs out through the API and returns to login', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() => Promise.resolve(emptyResponse())),
    );

    renderWithProviders(<UserMenu user={{ ...testUser, full_name: 'Dana Admin' }} />);
    await user.click(screen.getByRole('button', { name: t('shell.userMenuLabel') }));
    await user.click(await screen.findByText(t('auth.logout.action')));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/login');
    });
  });
});
