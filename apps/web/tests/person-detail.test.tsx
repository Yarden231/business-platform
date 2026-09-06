import { screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PersonDetailView } from '@/features/people/components/person-detail';
import { t } from '@/messages/t';

import { jsonResponse, renderWithProviders, testUser } from './helpers';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn(), push: vi.fn() }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

const personId = '22222222-2222-4222-8222-222222222222';

const summary = {
  representation: 'SUMMARY' as const,
  id: personId,
  first_name: 'דנה',
  last_name: 'לוי',
  organization_name: 'משרד לוי',
  id_number_masked: '******782',
  archived_at: null,
};

const detail = {
  representation: 'DETAIL' as const,
  id: personId,
  first_name: 'דנה',
  last_name: 'לוי',
  id_type: 'ISRAELI_ID' as const,
  id_number: '123456782',
  email: 'dana@example.com',
  phone: '050-0000000',
  address: null,
  workplace: null,
  organization_name: 'משרד לוי',
  license_number: null,
  notes: 'הערה פנימית',
  created_by: testUser.id,
  created_at: '2026-09-06T10:00:00Z',
  updated_at: '2026-09-06T10:00:00Z',
  archived_at: null,
};

function stubPerson(body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>((input) => {
      const url = String(input);
      if (url.includes('/cases')) {
        return Promise.resolve(jsonResponse({ items: [], total: 0, page: 1, page_size: 25 }));
      }
      return Promise.resolve(jsonResponse(body));
    }),
  );
}

describe('PersonDetailView', () => {
  it('hides contact fields and edit for a summary', async () => {
    stubPerson(summary);

    renderWithProviders(
      <PersonDetailView personId={personId} user={{ ...testUser, role: 'EMPLOYEE' }} />,
    );

    expect(
      await screen.findByRole('heading', {
        name: t('people.detail.title', { first: 'דנה', last: 'לוי' }),
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(t('people.summaryNotice'))).toBeInTheDocument();
    expect(screen.queryByText('dana@example.com')).not.toBeInTheDocument();
    expect(screen.queryByText('123456782')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: t('people.detail.edit') })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: t('people.detail.archive') }),
    ).not.toBeInTheDocument();
  });

  it('shows full detail and admin actions', async () => {
    stubPerson(detail);

    renderWithProviders(<PersonDetailView personId={personId} user={testUser} />);

    expect(await screen.findByText('dana@example.com')).toBeInTheDocument();
    expect(screen.getByText('123456782')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: t('people.detail.edit') })).toHaveAttribute(
      'href',
      `/people/${personId}/edit`,
    );
    expect(screen.getByRole('button', { name: t('people.detail.archive') })).toBeInTheDocument();
  });
});
