import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PersonForm } from '@/features/people/components/person-form';
import { t } from '@/messages/t';

import { emptyResponse, renderWithProviders } from './helpers';

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

describe('PersonForm', () => {
  it('renders Hebrew field labels', () => {
    renderWithProviders(<PersonForm mode="create" />);

    expect(screen.getByLabelText(t('people.form.firstName'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('people.form.lastName'))).toBeInTheDocument();
    expect(screen.getByLabelText(t('people.form.idType'))).toBeInTheDocument();
    expect(screen.getByRole('button', { name: t('people.form.submitCreate') })).toBeInTheDocument();
  });

  it('shows required-field errors without calling the API', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(emptyResponse()));
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<PersonForm mode="create" />);
    await user.click(screen.getByRole('button', { name: t('people.form.submitCreate') }));

    expect(await screen.findByText(t('people.validation.firstNameRequired'))).toBeInTheDocument();
    expect(screen.getByText(t('people.validation.lastNameRequired'))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an Israeli ID without its checksum', async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(() => Promise.resolve(emptyResponse()));
    vi.stubGlobal('fetch', fetchMock);

    renderWithProviders(<PersonForm mode="create" />);
    await user.type(screen.getByLabelText(t('people.form.firstName')), 'דנה');
    await user.type(screen.getByLabelText(t('people.form.lastName')), 'לוי');
    await user.selectOptions(screen.getByLabelText(t('people.form.idType')), 'ISRAELI_ID');
    await user.type(screen.getByLabelText(t('people.form.idNumber')), '123456780');
    await user.click(screen.getByRole('button', { name: t('people.form.submitCreate') }));

    expect(await screen.findByText(t('people.validation.israeliIdInvalid'))).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
