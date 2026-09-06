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

async function createRotatedEmployee(
  page: Page,
  request: APIRequestContext,
): Promise<{ email: string; password: string }> {
  const csrfToken = await readCsrfToken(page);
  const email = `e2e.people.${Date.now()}@example.com`;
  const created = await request.post('/api/v1/users', {
    headers: { 'X-CSRF-Token': csrfToken, 'Content-Type': 'application/json' },
    data: { email, full_name: 'E2E People Employee', role: 'EMPLOYEE' },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const temporary = (await created.json()) as { temporary_password: string };

  await page.getByRole('button', { name: t('shell.userMenuLabel') }).click();
  await page.getByText(t('auth.logout.action')).click();
  await expect(page).toHaveURL('/login');

  await loginThroughUi(page, email, temporary.temporary_password);
  await expect(page).toHaveURL('/change-password');
  const password = `rotated-${Date.now()}-pass`;
  await page
    .getByLabel(t('auth.passwordChange.currentPasswordLabel'))
    .fill(temporary.temporary_password);
  await page.getByLabel(t('auth.passwordChange.newPasswordLabel')).fill(password);
  await page.getByLabel(t('auth.passwordChange.confirmPasswordLabel')).fill(password);
  await page.getByRole('button', { name: t('auth.passwordChange.submit') }).click();
  await expect(page).toHaveURL('/');
  return { email, password };
}

test.describe('people directory', () => {
  test('an admin can create, find, view and archive a person', async ({ page }) => {
    const stamp = Date.now();
    const firstName = 'אייל';
    const lastName = `בדיקה${stamp}`;

    await loginThroughUi(page, adminEmail, adminPassword);
    await expect(page).toHaveURL('/');

    await page.getByRole('link', { name: t('shell.navigation.people') }).click();
    await expect(page).toHaveURL('/people');
    await expect(page.getByRole('heading', { name: t('people.title') })).toBeVisible();

    await page.getByRole('link', { name: t('people.create') }).click();
    await expect(page).toHaveURL('/people/new');

    await page.getByLabel(t('people.form.firstName')).fill(firstName);
    await page.getByLabel(t('people.form.lastName')).fill(lastName);
    await page.getByLabel(t('people.form.organization')).fill('משרד בדיקה');
    await page.getByRole('button', { name: t('people.form.submitCreate') }).click();

    await expect(page.getByRole('heading', { level: 1 })).toContainText(lastName);
    await expect(page.getByRole('link', { name: t('people.detail.edit') })).toBeVisible();
    await expect(page.getByRole('button', { name: t('people.detail.archive') })).toBeVisible();

    await page.getByRole('link', { name: t('people.detail.backToList') }).click();
    await page.getByLabel(t('people.searchLabel')).fill(lastName);
    await page.getByRole('button', { name: t('people.searchSubmit') }).click();
    await expect(page.getByRole('link', { name: `${firstName} ${lastName}` })).toBeVisible();
  });

  test('an employee sees a masked summary and cannot edit or archive', async ({ page }) => {
    const stamp = Date.now();
    const lastName = `סיכום${stamp}`;
    const idNumber = `P${stamp}`;
    const email = `secret.${stamp}@example.com`;

    await loginThroughUi(page, adminEmail, adminPassword);
    await expect(page).toHaveURL('/');
    const csrfToken = await readCsrfToken(page);

    const created = await page.request.post('/api/v1/people', {
      headers: { 'X-CSRF-Token': csrfToken, 'Content-Type': 'application/json' },
      data: {
        first_name: 'רות',
        last_name: lastName,
        id_type: 'PASSPORT',
        id_number: idNumber,
        email,
      },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const person = (await created.json()) as { id: string };

    await createRotatedEmployee(page, page.request);

    await page.goto(`/people/${person.id}`);
    await expect(page.getByText(t('people.summaryNotice'))).toBeVisible();
    await expect(page.getByText(idNumber)).toHaveCount(0);
    await expect(page.getByText(email)).toHaveCount(0);
    await expect(page.getByRole('link', { name: t('people.detail.edit') })).toHaveCount(0);
    await expect(page.getByRole('button', { name: t('people.detail.archive') })).toHaveCount(0);
  });
});
