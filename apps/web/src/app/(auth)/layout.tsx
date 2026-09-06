import type { ReactNode } from 'react';

import { t } from '@/messages/t';

export default function AuthLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-6 py-16">
      <header className="mb-8 space-y-1 text-start">
        <p className="text-sm font-semibold">{t('app.organizationName')}</p>
        <p className="text-muted-foreground text-sm">{t('app.productName')}</p>
      </header>
      {children}
    </main>
  );
}
