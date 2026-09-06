import type { Metadata } from 'next';
import type { ReactNode } from 'react';

import { he } from '@/messages/he';

import './globals.css';

export const metadata: Metadata = {
  title: he.app.documentTitle,
  description: he.app.documentDescription,
};

export default function RootLayout({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <html lang="he" dir="rtl">
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
