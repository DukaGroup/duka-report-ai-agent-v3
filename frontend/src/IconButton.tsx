import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  danger?: boolean;
};

export function IconButton({ label, danger, className = "", ...props }: Props) {
  return (
    <button
      {...props}
      type={props.type || "button"}
      className={`icon-button action-button${danger ? " danger-text" : ""} ${className}`}
      aria-label={label}
      data-tooltip={label}
    />
  );
}
