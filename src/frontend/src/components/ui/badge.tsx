import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../../lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-none border px-2 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-1 focus:ring-neon-cyan uppercase tracking-tighter",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-neon-cyan/20 text-neon-cyan",
        secondary:
          "border-transparent bg-neon-magenta/20 text-neon-magenta",
        destructive:
          "border-transparent bg-down-red/20 text-down-red",
        outline: "text-white border-border",
        success: "border-transparent bg-up-green/20 text-up-green",
        warning: "border-transparent bg-warn-gold/20 text-warn-gold",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
