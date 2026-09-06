import type { Metadata } from 'next';
import { Heebo } from 'next/font/google';
import type { ReactNode } from 'react';

import { Providers } from '@/components/providers';
import { t } from '@/messages/t';

import './globals.css';

const heebo = Heebo({
  subsets: ['hebrew', 'latin'],
  variable: '--font-heebo',
  display: 'swap',
});

export const metadata: Metadata = {
  title: t('app.documentTitle'),
  description: t('app.documentDescription'),
};

export default function RootLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <html lang="he" dir="rtl" className={heebo.variable}>
      <body className="min-h-dvh antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
