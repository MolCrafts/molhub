import type { JSX, ReactNode } from "react";

export type EmptyStateDensity = "default" | "compact" | "inline";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  density?: EmptyStateDensity;
  className?: string;
}

const CONTAINER: Record<EmptyStateDensity, string> = {
  default: "flex flex-col items-center gap-3 py-8 text-center",
  compact: "flex flex-col items-center gap-2 px-3 py-6 text-center",
  inline: "px-2 py-1 text-left",
};

const TITLE: Record<EmptyStateDensity, string> = {
  default: "text-body font-medium text-foreground",
  compact: "text-label font-medium text-foreground",
  inline: "text-label font-medium text-foreground",
};

const DESCRIPTION: Record<EmptyStateDensity, string> = {
  default: "max-w-sm text-body leading-relaxed text-muted-foreground",
  compact: "max-w-sm text-label leading-relaxed text-muted-foreground",
  inline: "text-label leading-relaxed text-muted-foreground",
};

/** Empty placeholder with density variants tuned for the viewer inspector. */
export const EmptyState = ({
  title,
  description,
  action,
  icon,
  density = "default",
  className,
}: EmptyStateProps): JSX.Element => {
  return (
    <div
      className={[CONTAINER[density], className].filter(Boolean).join(" ")}
      role="status"
      aria-live="polite"
    >
      {icon && density !== "inline" && (
        <div className="flex size-10 items-center justify-center text-muted-foreground/50">
          {icon}
        </div>
      )}
      {icon && density === "inline" && <div className="mb-1 text-muted-foreground/40">{icon}</div>}
      <p className={TITLE[density]}>{title}</p>
      {description && <p className={DESCRIPTION[density]}>{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
};
