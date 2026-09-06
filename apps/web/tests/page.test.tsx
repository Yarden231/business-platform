import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import HomePage from '@/app/page';
import { he } from '@/messages/he';

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(() =>
      Promise.resolve(
        new Response(JSON.stringify({ status: 'ok' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    ),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('HomePage', () => {
  it('renders the Hebrew organisation and product names', () => {
    render(<HomePage />);

    expect(
      screen.getByRole('heading', { level: 1, name: he.app.organizationName }),
    ).toBeInTheDocument();
    expect(screen.getByText(he.app.productName)).toBeInTheDocument();
  });

  it('shows the API connectivity panel', () => {
    render(<HomePage />);

    expect(screen.getByRole('heading', { level: 2, name: he.apiHealth.title })).toBeInTheDocument();
  });
});
