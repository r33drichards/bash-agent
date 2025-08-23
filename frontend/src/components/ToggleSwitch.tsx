import React from 'react';

interface ToggleSwitchProps {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}

export const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onChange,
  disabled = false,
}) => {
  return (
    <button
      onClick={onChange}
      disabled={disabled}
      className={`
        relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background
        ${
          checked
            ? 'bg-secondary'
            : 'bg-border'
        }
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
      `}
    >
      <div
        className={`
          absolute top-0.5 left-0.5 w-5 h-5 bg-text-bright rounded-full transition-transform duration-200
          ${
            checked ? 'translate-x-5' : 'translate-x-0'
          }
        `}
      />
    </button>
  );
};
