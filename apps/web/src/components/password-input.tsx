'use client';

import { useState, type ComponentProps } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { t } from '@/messages/t';

type PasswordInputProps = Omit<ComponentProps<typeof Input>, 'type'> & {
  toggleId?: string;
};

export function PasswordInput({
  toggleId,
  className,
  ...props
}: PasswordInputProps): React.JSX.Element {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <Input
        type={visible ? 'text' : 'password'}
        className={`pe-16 ${className ?? ''}`}
        {...props}
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        id={toggleId}
        className="absolute end-1 top-1/2 h-7 -translate-y-1/2 px-2 text-xs"
        onClick={() => {
          setVisible((current) => !current);
        }}
      >
        {visible ? t('common.hide') : t('common.show')}
      </Button>
    </div>
  );
}
