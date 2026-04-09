import React from 'react';
import { Card, CardContent } from './ui/card';
import { cn } from '../lib/utils';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface StatusCardProps {
  title: string;
  value: string;
  trend?: string;
  trendIsUp?: boolean;
  icon?: React.ReactNode;
  className?: string;
}

export const StatusCard: React.FC<StatusCardProps> = ({ 
  title, 
  value, 
  trend, 
  trendIsUp, 
  icon,
  className 
}) => {
  return (
    <Card className={cn("overflow-hidden border-l-2", trendIsUp ? "border-l-up-green" : trendIsUp === false ? "border-l-down-red" : "border-l-neon-cyan", className)}>
      <CardContent className="p-4 pt-4">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-widest text-info-gray/60">{title}</span>
          {icon && <div className="text-info-gray/40">{icon}</div>}
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-orbitron text-xl font-bold text-white">{value}</span>
          {trend && (
            <div className={cn(
              "flex items-center text-[10px] font-bold",
              trendIsUp ? "text-up-green" : "text-down-red"
            )}>
              {trendIsUp ? <TrendingUp className="mr-0.5 h-3 w-3" /> : <TrendingDown className="mr-0.5 h-3 w-3" />}
              {trend}
            </div>
          )}
        </div>
        <div className="mt-3 h-[1px] w-full bg-gradient-to-r from-border to-transparent" />
      </CardContent>
    </Card>
  );
};

export default StatusCard;
