import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PasswordChangeForm } from '@/features/auth/components/password-change-form';
import { t } from '@/messages/t';

import { emptyResponse, jsonResponse, renderWithProviders, testUser } from './helpers';

const replace = vi.fn();
const refresh = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, refresh, push: vi.fn() }),
}));

function stubFetch(implementation: typeof fetch): ReturnType<typeof vi.fn<typeof fetch>> {
  const fetchMock = vi.fn<typeof fetch>(implementation);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
  refresh.mockReset();
});

describe('PasswordChangeForm', () => {
  it('renders the Hebrew field labels', () => {
    renderWithProviders(<PasswordChangeForm />);

    expect(
      screen.getByLabelText(t('auth.passwordChange.currentPasswordLabel')),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(t('auth.passwordChange.newPasswordLabel'))).toBeInTheDocument();
    expect(
      screen.getByLabelText(t('auth.passwordChange.confirmPasswordLabel')),
    ).toBeInTheDocument();
  });

  it('rejects a confirmation mismatch before calling the API', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(() => Promise.resolve(emptyResponse()));

    renderWithProviders(<PasswordChangeForm />);
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.currentPasswordLabel')),
      'current-password-12',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.newPasswordLabel')),
      'brand-new-password',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.confirmPasswordLabel')),
      'does-not-match-12',
    );
    await user.click(screen.getByRole('button', { name: t('auth.passwordChange.submit') }));

    expect(await screen.findByText(t('auth.validation.confirmMismatch'))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('submits the change and returns to the shell', async () => {
    const user = userEvent.setup();
    stubFetch((input) => {
      const url = String(input);
      if (url.endsWith('/auth/password')) {
        return Promise.resolve(emptyResponse());
      }
      return Promise.resolve(jsonResponse({ ...testUser, must_change_password: false }));
    });

    renderWithProviders(<PasswordChangeForm forced />);
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.currentPasswordLabel')),
      'temporary-password',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.newPasswordLabel')),
      'brand-new-password',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.confirmPasswordLabel')),
      'brand-new-password',
    );
    await user.click(screen.getByRole('button', { name: t('auth.passwordChange.submit') }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/');
    });
  });

  it('shows the current-password error on the current field', async () => {
    const user = userEvent.setup();
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(
          {
            error: {
              code: 'CURRENT_PASSWORD_INVALID',
              message: 'The current password is not correct.',
              details: [],
              request_id: 'req-pw',
            },
          },
          { status: 422, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );

    renderWithProviders(<PasswordChangeForm />);
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.currentPasswordLabel')),
      'wrong-current-12',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.newPasswordLabel')),
      'brand-new-password',
    );
    await user.type(
      screen.getByLabelText(t('auth.passwordChange.confirmPasswordLabel')),
      'brand-new-password',
    );
    await user.click(screen.getByRole('button', { name: t('auth.passwordChange.submit') }));

    expect(await screen.findByText(t('errors.codes.CURRENT_PASSWORD_INVALID'))).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
