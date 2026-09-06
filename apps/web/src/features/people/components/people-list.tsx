'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { usePeopleListQuery } from '@/features/people/queries';
import type { PersonRead } from '@/lib/api/types';
import { formatNumber } from '@/lib/format';
import { t, tDynamic } from '@/messages/t';

function fullName(person: PersonRead): string {
  return `${person.first_name} ${person.last_name}`;
}

function identifierLabel(person: PersonRead): string {
  if (person.representation === 'DETAIL') {
    if (person.id_type === null || person.id_number === null) {
      return t('people.noIdentifier');
    }
    return `${tDynamic(`people.identifierTypes.${person.id_type}`, person.id_type)} ${person.id_number}`;
  }
  if (person.id_number_masked === null) {
    return t('people.noIdentifier');
  }
  return person.id_number_masked;
}

export function PeopleList(): React.JSX.Element {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryFromUrl = searchParams.get('query') ?? '';
  const page = Math.max(1, Number(searchParams.get('page') ?? '1') || 1);
  const archived = searchParams.get('archived') === 'true';
  const [draft, setDraft] = useState(queryFromUrl);

  const list = usePeopleListQuery({ query: queryFromUrl, page, archived });
  const data = list.data;
  const pageCount = data === undefined ? 1 : Math.max(1, Math.ceil(data.total / data.page_size));

  function replaceParams(next: { query?: string; page?: number; archived?: boolean }): void {
    const params = new URLSearchParams();
    const query = next.query ?? queryFromUrl;
    const nextPage = next.page ?? page;
    const nextArchived = next.archived ?? archived;
    if (query) {
      params.set('query', query);
    }
    if (nextPage > 1) {
      params.set('page', String(nextPage));
    }
    if (nextArchived) {
      params.set('archived', 'true');
    }
    const encoded = params.toString();
    router.replace(encoded === '' ? '/people' : `/people?${encoded}`);
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight">{t('people.title')}</h1>
          <p className="text-muted-foreground">{t('people.subtitle')}</p>
        </div>
        <Button asChild>
          <Link href="/people/new">{t('people.create')}</Link>
        </Button>
      </header>

      <form
        className="flex flex-col gap-3 sm:flex-row sm:items-end"
        onSubmit={(event) => {
          event.preventDefault();
          replaceParams({ query: draft, page: 1 });
        }}
      >
        <div className="min-w-0 flex-1 space-y-2">
          <Label htmlFor="people-search">{t('people.searchLabel')}</Label>
          <Input
            id="people-search"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={t('people.searchPlaceholder')}
          />
        </div>
        <Button type="submit">{t('people.searchSubmit')}</Button>
      </form>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={archived}
          onChange={(event) => replaceParams({ archived: event.target.checked, page: 1 })}
        />
        {t('people.showArchived')}
      </label>

      {list.isError ? <p className="text-destructive">{t('errors.unexpected')}</p> : null}

      {data !== undefined && data.items.length === 0 ? (
        <p className="text-muted-foreground">
          {queryFromUrl || archived ? t('people.empty') : t('people.emptyDefault')}
        </p>
      ) : null}

      {data !== undefined && data.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-start text-sm">
            <caption className="sr-only">{t('people.title')}</caption>
            <thead>
              <tr className="border-b">
                <th className="px-2 py-2 font-medium">{t('people.columns.name')}</th>
                <th className="px-2 py-2 font-medium">{t('people.columns.organization')}</th>
                <th className="px-2 py-2 font-medium">{t('people.columns.identifier')}</th>
                <th className="px-2 py-2 font-medium">{t('people.columns.status')}</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((person) => (
                <tr key={person.id} className="border-b">
                  <td className="px-2 py-3">
                    <Link
                      href={`/people/${person.id}`}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {fullName(person)}
                    </Link>
                  </td>
                  <td className="text-muted-foreground px-2 py-3">
                    {person.organization_name ?? t('people.noOrganization')}
                  </td>
                  <td className="px-2 py-3" dir="ltr">
                    {identifierLabel(person)}
                  </td>
                  <td className="px-2 py-3">
                    {person.archived_at ? (
                      <Badge variant="secondary">{t('people.archivedBadge')}</Badge>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {data !== undefined ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted-foreground text-sm">
            {t('people.pagination.summary', { total: formatNumber(data.total) })}
            {data.total > 0
              ? ` · ${t('people.pagination.page', { page: formatNumber(data.page), pages: formatNumber(pageCount) })}`
              : ''}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={page <= 1}
              onClick={() => replaceParams({ page: page - 1 })}
            >
              {t('people.pagination.previous')}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={page >= pageCount}
              onClick={() => replaceParams({ page: page + 1 })}
            >
              {t('people.pagination.next')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
