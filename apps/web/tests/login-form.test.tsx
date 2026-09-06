import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { LoginForm } from '@/features/auth/components/login-form';
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

describe('LoginForm', () => {
  it('renders the Hebrew labels from the catalog', () => {
    renderWithProviders(<LoginForm />);

    expect(screen.getByLabelText(t('auth.login.emailLabel'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('auth.login.passwordLabel'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('auth.login.submit') })).toBeInTheDocument();
    expect(screen.getByText(t('auth.login.noSelfServiceReset'))).toBeInTheDocument();
  });

  it('shows a required-field error without calling the API', async () => {
    const user = userEvent.setup();
    const fetchMock = stubFetch(() => Promise.resolve(emptyResponse()));

    renderWithProviders(<LoginForm />);
    await user.click(screen.getByRole('button', { name: t('auth.login.submit') }));

    expect(await screen.findByText(t('auth.validation.emailRequired'))).toBeInTheDocument();
    expect(screen.getByText(t('auth.validation.passwordRequired'))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('submits credentials through the same-origin client and lands on the shell', async () => {
    const user = userEvent.setup();
    stubFetch((input) => {
      const url = String(input);
      if (url.endsWith('/auth/login')) {
        return Promise.resolve(emptyResponse());
      }
      return Promise.resolve(jsonResponse(testUser));
    });

    renderWithProviders(<LoginForm />);
    await user.type(screen.getByLabelText(t('auth.login.emailLabel')), 'admin@example.test');
    await user.type(
      screen.getByLabelText(t('auth.login.passwordLabel')),
      'admin-development-passphrase',
    );
    await user.click(screen.getByRole('button', { name: t('auth.login.submit') }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/');
    });
  });

  it('routes to the password-change page when the account must rotate', async () => {
    const user = userEvent.setup();
    stubFetch((input) => {
      const url = String(input);
      if (url.endsWith('/auth/login')) {
        return Promise.resolve(emptyResponse());
      }
      return Promise.resolve(jsonResponse({ ...testUser, must_change_password: true }));
    });

    renderWithProviders(<LoginForm />);
    await user.type(screen.getByLabelText(t('auth.login.emailLabel')), 'admin@example.test');
    await user.type(screen.getByLabelText(t('auth.login.passwordLabel')), 'temporary-password');
    await user.click(screen.getByRole('button', { name: t('auth.login.submit') }));

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith('/change-password');
    });
  });

  it('shows the Hebrew login failure without saying which field was wrong', async () => {
    const user = userEvent.setup();
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(
          {
            error: {
              code: 'AUTH_INVALID_CREDENTIALS',
              message: 'Those credentials are not valid.',
              details: [],
              request_id: 'req-login',
            },
          },
          {
            status: 401,
            headers: { 'content-type': 'application/json', 'X-Request-ID': 'req-login' },
          },
        ),
      ),
    );

    renderWithProviders(<LoginForm />);
    await user.type(screen.getByLabelText(t('auth.login.emailLabel')), 'admin@example.test');
    await user.type(screen.getByLabelText(t('auth.login.passwordLabel')), 'wrong-password');
    await user.click(screen.getByRole('button', { name: t('auth.login.submit') }));

    expect(await screen.findByText(t('auth.login.errorTitle'))).toBeInTheDocument();
    expect(screen.getByText(t('errors.codes.AUTH_INVALID_CREDENTIALS'))).toBeInTheDocument();
    expect(screen.getByText(t('errors.requestId', { requestId: 'req-login' }))).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
