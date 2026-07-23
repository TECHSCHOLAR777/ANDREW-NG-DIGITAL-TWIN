import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * A calm, explanatory empty state.
 *
 * The design system requires empty states to say what CREATES content rather
 * than apologising for its absence — e.g. an empty Context Graph explains that
 * connections appear as conversations continue, not that nothing is
 * remembered. Kept presentational; callers supply copy and any real action.
 */
export interface EmptyStateProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: React.ReactNode
  title: React.ReactNode
  description?: React.ReactNode
  action?: React.ReactNode
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-6 py-10 text-center",
        className
      )}
      {...props}
    >
      {icon != null && (
        <div className="grid size-11 place-items-center rounded-full bg-[var(--surface-alt)] text-[var(--text-muted)] [&>svg]:size-5">
          {icon}
        </div>
      )}
      <div className="space-y-1.5">
        <p className="text-[15px] font-medium text-[var(--text)]">{title}</p>
        {description != null && (
          <p className="mx-auto max-w-[42ch] text-[13px] leading-relaxed text-[var(--text-muted)]">
            {description}
          </p>
        )}
      </div>
      {action != null && <div className="mt-1">{action}</div>}
    </div>
  )
}
