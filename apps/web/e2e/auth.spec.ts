import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

import { t } from '../src/messages/t';

const adminEmail = requiredEnv('E2E_ADMIN_EMAIL');
const adminPassword = requiredEnv('E2E_ADMIN_PASSWORD');

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Create an admin with ./scripts/create-admin and export the credentials, or run ./scripts/e2e.`,
    );
  }
  return value;
}

async function loginThroughUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel(t('auth.login.emailLabel')).fill(email);
  await page.getByLabel(t('auth.login.passwordLabel')).fill(password);
  await page.getByRole('button', { name: t('auth.login.submit') }).click();
}

async function readCsrfToken(page: Page): Promise<string> {
  const token = await page.evaluate(() => {
    const match = document.cookie.split('; ').find((entry) => entry.startsWith('csrf_token='));
    return match === undefined ? null : decodeURIComponent(match.slice('csrf_token='.length));
  });
  if (token === null) {
    throw new Error('csrf_token cookie was not issued after login.');
  }
  return token;
}

async function createTemporaryUser(
  request: APIRequestContext,
  csrfToken: string,
): Promise<{ email: string; password: string }> {
  const email = `e2e.employee.${Date.now()}@example.com`;
  const response = await request.post('/api/v1/users', {
    headers: { 'X-CSRF-Token': csrfToken, 'Content-Type': 'application/json' },
    data: { email, full_name: 'E2E Employee', role: 'EMPLOYEE' },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as { temporary_password: string };
  return { email, password: body.temporary_password };
}

test.describe('authentication', () => {
  test('an admin can log in, land on the shell, and log out', async ({ page }) => {
    await loginThroughUi(page, adminEmail, adminPassword);

    await expect(page).toHaveURL('/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByText(t('home.accountSectionTitle'))).toBeVisible();
    await expect(page.getByRole('navigation', { name: t('shell.navigationLabel') })).toBeVisible();
    await expect(page.getByRole('button', { name: t('shell.userMenuLabel') })).toBeVisible();

    await page.getByRole('button', { name: t('shell.userMenuLabel') }).click();
    await page.getByText(t('auth.logout.action')).click();

    await expect(page).toHaveURL('/login');
    await expect(page.getByRole('button', { name: t('auth.login.submit') })).toBeVisible();
  });

  test('a temporary password is forced through the password-change screen', async ({ page }) => {
    await loginThroughUi(page, adminEmail, adminPassword);
    await expect(page).toHaveURL('/');

    const csrfToken = await readCsrfToken(page);
    const temporary = await createTemporaryUser(page.request, csrfToken);

    await page.getByRole('button', { name: t('shell.userMenuLabel') }).click();
    await page.getByText(t('auth.logout.action')).click();
    await expect(page).toHaveURL('/login');

    await loginThroughUi(page, temporary.email, temporary.password);

    await expect(page).toHaveURL('/change-password');
    await expect(page.getByText(t('auth.passwordChange.forcedTitle'))).toBeVisible();

    const newPassword = `rotated-${Date.now()}-pass`;
    await page.getByLabel(t('auth.passwordChange.currentPasswordLabel')).fill(temporary.password);
    await page.getByLabel(t('auth.passwordChange.newPasswordLabel')).fill(newPassword);
    await page.getByLabel(t('auth.passwordChange.confirmPasswordLabel')).fill(newPassword);
    await page.getByRole('button', { name: t('auth.passwordChange.submit') }).click();

    await expect(page).toHaveURL('/');
    await expect(page.getByRole('navigation', { name: t('shell.navigationLabel') })).toBeVisible();
  });

  test('an unauthenticated visit to the shell is sent to login', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL('/login');
  });
});
