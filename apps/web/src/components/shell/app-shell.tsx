import Link from 'next/link';
import type { ReactNode } from 'react';

import { UserMenu } from '@/components/shell/user-menu';
import { Separator } from '@/components/ui/separator';
import type { CurrentUser } from '@/lib/api/types';
import { t } from '@/messages/t';

type AppShellProps = {
  user: CurrentUser;
  children: ReactNode;
};

export function AppShell({ user, children }: AppShellProps): React.JSX.Element {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main-content"
        className="bg-primary text-primary-foreground sr-only focus:not-sr-only focus:absolute focus:start-4 focus:top-4 focus:z-50 focus:rounded-md focus:px-3 focus:py-2"
      >
        {t('app.skipToContent')}
      </a>
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-3">
          <div className="flex min-w-0 flex-col">
            <p className="truncate text-sm font-semibold">{t('app.organizationName')}</p>
            <p className="text-muted-foreground truncate text-xs">{t('app.productName')}</p>
          </div>
          <UserMenu user={user} />
        </div>
        <Separator />
        <nav aria-label={t('shell.navigationLabel')} className="mx-auto w-full max-w-5xl px-4 py-2">
          <Link href="/" className="text-sm font-medium underline-offset-4 hover:underline">
            {t('shell.navigation.home')}
          </Link>
        </nav>
      </header>
      <main
        id="main-content"
        aria-label={t('shell.mainLabel')}
        className="mx-auto w-full max-w-5xl flex-1 px-4 py-8"
      >
        {children}
      </main>
    </div>
  );
}
