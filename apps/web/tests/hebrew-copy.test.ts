import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = join(import.meta.dirname, '../src');
const CATALOG = 'messages/he.ts';
const HEBREW = /[\u0590-\u05FF]/;

function walk(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      return walk(path);
    }
    if (path.endsWith('.ts') || path.endsWith('.tsx')) {
      return [path];
    }
    return [];
  });
}

describe('Hebrew copy', () => {
  it('lives only in the message catalog', () => {
    const offenders = walk(SRC_ROOT)
      .filter((path) => relative(SRC_ROOT, path) !== CATALOG)
      .filter((path) => HEBREW.test(readFileSync(path, 'utf8')))
      .map((path) => relative(SRC_ROOT, path));

    expect(offenders).toEqual([]);
  });
});
