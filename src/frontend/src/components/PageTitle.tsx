import { type ReactNode } from "react";
import { cn } from "../lib/utils";

interface PageTitleProps {
  title: string;
  subtitle: string;
  actions?: ReactNode;
  className?: string;
}

export function PageTitle({ title, subtitle, actions, className }: PageTitleProps) {
  return (
    <section className={cn("flex flex-col gap-1 mb-6", className)}>
      <div className="flex justify-between items-end">
        <div>
          <h1 className="font-orbitron text-2xl font-extrabold tracking-[0.15em] text-white">
            {title}
            <span className="inline-block w-1.5 h-6 bg-neon-cyan ml-2 animate-pulse align-middle" />
          </h1>
          <p className="text-info-gray/60 text-xs font-mono mt-1 uppercase tracking-widest">
            {subtitle}
          </p>
        </div>
        {actions && <div className="flex items-center gap-3">{actions}</div>}
      </div>
      <div className="h-[1px] w-full bg-gradient-to-r from-neon-cyan/50 via-border/20 to-transparent mt-3" />
    </section>
  );
}
