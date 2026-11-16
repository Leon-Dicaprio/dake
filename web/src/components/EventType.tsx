import {
  BriefcaseBusiness,
  CircleAlert,
  CloudCog,
  Lightbulb,
  TrendingUp,
  Wrench,
} from 'lucide-react';

const types = {
  商机: { icon: TrendingUp, className: 'opportunity' },
  流失: { icon: CircleAlert, className: 'risk' },
  排障: { icon: Wrench, className: 'incident' },
  资源需求: { icon: CloudCog, className: 'resource' },
  功能需求: { icon: Lightbulb, className: 'feature' },
  商务需求: { icon: BriefcaseBusiness, className: 'business' },
};

export function eventTypeClass(type: string) {
  return types[type as keyof typeof types]?.className ?? '';
}

/** 六类主事件保持同一名称，用低饱和色和图标辅助快速识别。 */
export function EventType({
  type,
  compact = false,
}: {
  type: string;
  compact?: boolean;
}) {
  const display = types[type as keyof typeof types] || types.商务需求;
  const Icon = display.icon;
  return (
    <span
      className={`event-type ${display.className} ${compact ? 'compact' : ''}`}
    >
      <span className="event-type-icon">
        <Icon size={14} strokeWidth={1.7} />
      </span>
      {!compact && type}
    </span>
  );
}
