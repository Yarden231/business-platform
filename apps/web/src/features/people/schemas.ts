import { z } from 'zod';

import { isValidIsraeliId } from '@/lib/identifiers';
import { t } from '@/messages/t';

const optionalText = z
  .string()
  .transform((value) => value.trim())
  .transform((value) => (value === '' ? '' : value));

export const personFormSchema = z
  .object({
    first_name: z.string().trim().min(1, t('people.validation.firstNameRequired')),
    last_name: z.string().trim().min(1, t('people.validation.lastNameRequired')),
    id_type: z.enum(['', 'ISRAELI_ID', 'PASSPORT', 'FOREIGN_ID']),
    id_number: optionalText,
    email: optionalText,
    phone: optionalText,
    address: optionalText,
    workplace: optionalText,
    organization_name: optionalText,
    license_number: optionalText,
    notes: optionalText,
  })
  .superRefine((value, context) => {
    const hasType = value.id_type !== '';
    const hasNumber = value.id_number !== '';
    if (hasType !== hasNumber) {
      context.addIssue({
        code: 'custom',
        path: hasType ? ['id_number'] : ['id_type'],
        message: t('people.validation.identifierPair'),
      });
    }
    if (value.id_type === 'ISRAELI_ID' && hasNumber && !isValidIsraeliId(value.id_number)) {
      context.addIssue({
        code: 'custom',
        path: ['id_number'],
        message: t('people.validation.israeliIdInvalid'),
      });
    }
    if (value.email !== '' && !value.email.includes('@')) {
      context.addIssue({
        code: 'custom',
        path: ['email'],
        message: t('people.validation.emailInvalid'),
      });
    }
  });

export type PersonFormValues = z.infer<typeof personFormSchema>;

export const emptyPersonForm: PersonFormValues = {
  first_name: '',
  last_name: '',
  id_type: '',
  id_number: '',
  email: '',
  phone: '',
  address: '',
  workplace: '',
  organization_name: '',
  license_number: '',
  notes: '',
};

export function blankToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}
