import { cn } from '@/lib/utils';

type FormFieldErrorProps = {
  id: string;
  message?: string | undefined;
  className?: string;
};

/** Accessible field-level error. Hidden when there is nothing to say. */
export function FormFieldError({
  id,
  message,
  className,
}: FormFieldErrorProps): React.JSX.Element | null {
  if (!message) {
    return null;
  }
  return (
    <p id={id} role="alert" className={cn('text-sm text-destructive', className)}>
      {message}
    </p>
  );
}
