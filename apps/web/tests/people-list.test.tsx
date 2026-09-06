import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PeopleList } from '@/features/people/components/people-list';
import { t } from '@/messages/t';

import { jsonResponse, renderWithProviders } from './helpers';

const replace = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, refresh: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  replace.mockReset();
});

const summaryPerson = {
  representation: 'SUMMARY' as const,
  id: '22222222-2222-4222-8222-222222222222',
  first_name: 'דנה',
  last_name: 'לוי',
  organization_name: 'משרד לוי',
  id_number_masked: '******782',
  archived_at: null,
};

describe('PeopleList', () => {
  it('renders Hebrew labels and a person row without a full identifier', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() =>
        Promise.resolve(
          jsonResponse({
            items: [summaryPerson],
            total: 1,
            page: 1,
            page_size: 25,
          }),
        ),
      ),
    );

    renderWithProviders(<PeopleList />);

    expect(await screen.findByRole('heading', { name: t('people.title') })).toBeInTheDocument();
    expect(screen.getByLabelText(t('people.searchLabel'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('people.create') })).toHaveAttribute(
      'href',
      '/people/new',
    );
    expect(await screen.findByRole('link', { name: 'דנה לוי' })).toHaveAttribute(
      'href',
      `/people/${summaryPerson.id}`,
    );
    expect(screen.getByText('******782')).toBeInTheDocument();
    expect(screen.queryByText('123456782')).not.toBeInTheDocument();
  });

  it('submits a search through the query string', async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() =>
        Promise.resolve(jsonResponse({ items: [], total: 0, page: 1, page_size: 25 })),
      ),
    );

    renderWithProviders(<PeopleList />);
    await user.type(screen.getByLabelText(t('people.searchLabel')), 'לוי');
    await user.click(screen.getByRole('button', { name: t('people.searchSubmit') }));

    expect(replace).toHaveBeenCalledWith('/people?query=%D7%9C%D7%95%D7%99');
  });
});
