import { z } from 'zod';

import { MAX_EMAIL_LENGTH, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from '@/lib/constants';
import { t } from '@/messages/t';

export const loginSchema = z.object({
  email: z
    .string()
    .trim()
    .min(1, t('auth.validation.emailRequired'))
    .max(MAX_EMAIL_LENGTH, t('auth.validation.emailTooLong')),
  password: z.string().min(1, t('auth.validation.passwordRequired')),
});

export type LoginValues = z.infer<typeof loginSchema>;

export const passwordChangeSchema = z
  .object({
    currentPassword: z.string().min(1, t('auth.validation.passwordRequired')),
    newPassword: z
      .string()
      .min(
        MIN_PASSWORD_LENGTH,
        t('auth.validation.newPasswordTooShort', { min: MIN_PASSWORD_LENGTH }),
      )
      .max(
        MAX_PASSWORD_LENGTH,
        t('auth.validation.newPasswordTooLong', { max: MAX_PASSWORD_LENGTH }),
      ),
    confirmPassword: z.string().min(1, t('auth.validation.passwordRequired')),
  })
  .superRefine((value, context) => {
    if (value.newPassword !== value.confirmPassword) {
      context.addIssue({
        code: 'custom',
        path: ['confirmPassword'],
        message: t('auth.validation.confirmMismatch'),
      });
    }
    if (value.newPassword === value.currentPassword && value.newPassword.length > 0) {
      context.addIssue({
        code: 'custom',
        path: ['newPassword'],
        message: t('auth.validation.newPasswordSameAsCurrent'),
      });
    }
  });

export type PasswordChangeValues = z.infer<typeof passwordChangeSchema>;
