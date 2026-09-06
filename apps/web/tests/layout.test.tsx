import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/font/google', () => ({
  Heebo: () => ({ variable: '--font-heebo', className: 'font-heebo' }),
}));

import RootLayout from '@/app/layout';

describe('RootLayout', () => {
  it('declares the document as Hebrew and right-to-left', () => {
    // The layout renders <html>, which React Testing Library cannot mount
    // inside a container, so the element is inspected directly.
    const element: ReactElement<{ lang?: string; dir?: string }> = RootLayout({ children: null });

    expect(element.props.lang).toBe('he');
    expect(element.props.dir).toBe('rtl');
  });
});
