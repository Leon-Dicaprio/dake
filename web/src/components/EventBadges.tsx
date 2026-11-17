import { Crown, Lock } from 'lucide-react';

const PRIORITY_RANKS: Record<string, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  待评估: 4,
};

const PRIORITY_CLASSES: Record<string, string> = {
  P0: 'p0',
  P1: 'p1',
  P2: 'p2',
  P3: 'p3',
  待评估: 'pending',
};

const STATUS_CLASSES: Record<string, string> = {
  跟进中: 'active',
  等待中: 'waiting',
  已解决: 'resolved',
  已取消: 'cancelled',
  状态未明: 'unknown',
};

function customerLevelNumber(customer?: API.CustomerResponse): number {
  if (
    customer?.level_state === 'fresh' &&
    customer.level &&
    /^L(?:10|[0-9])$/.test(customer.level)
  ) {
    return Number.parseInt(customer.level.slice(1), 10);
  }
  return -1;
}

/** 与后端一致的五层列表排序比较器：未结束优先 -> P0~P3 -> 超级大客 -> 等级数字 -> 最新消息时间。 */
export function compareEventsByPriority(
  left: API.EventResponse,
  right: API.EventResponse,
  customerMap?: Map<string, API.CustomerResponse>,
): number {
  const leftEnded =
    left.lifecycle_status === '已解决' || left.lifecycle_status === '已取消'
      ? 1
      : 0;
  const rightEnded =
    right.lifecycle_status === '已解决' || right.lifecycle_status === '已取消'
      ? 1
      : 0;
  if (leftEnded !== rightEnded) return leftEnded - rightEnded;

  const leftRank = PRIORITY_RANKS[left.priority || '待评估'] ?? 4;
  const rightRank = PRIORITY_RANKS[right.priority || '待评估'] ?? 4;
  if (leftRank !== rightRank) return leftRank - rightRank;

  const leftCustomer = customerMap?.get(left.uid);
  const rightCustomer = customerMap?.get(right.uid);
  const leftSuper = leftCustomer?.is_super_large ? 0 : 1;
  const rightSuper = rightCustomer?.is_super_large ? 0 : 1;
  if (leftSuper !== rightSuper) return leftSuper - rightSuper;

  const leftLevel = customerLevelNumber(leftCustomer);
  const rightLevel = customerLevelNumber(rightCustomer);
  if (leftLevel !== rightLevel) return rightLevel - leftLevel;

  return right.end_time.localeCompare(left.end_time);
}

/** 展示业务优先级徽标及超级大客提档、人工锁定标记。 */
export function PriorityBadge({
  priority,
  basePriority,
  detail,
  locked = false,
  compact = false,
}: {
  priority?: string;
  basePriority?: string;
  detail?: Record<string, unknown> | null;
  locked?: boolean;
  compact?: boolean;
}) {
  const value = priority || '待评估';
  const tone = PRIORITY_CLASSES[value] || 'pending';
  const vipBoosted = Boolean(detail?.vip_boosted);
  const levelNote =
    typeof detail?.level_note === 'string' ? detail.level_note : '';
  return (
    <span
      className={`priority-pill ${tone} ${compact ? 'compact' : ''}`}
      title={levelNote || undefined}
    >
      {vipBoosted && <Crown size={11} />}
      <span>{value}</span>
      {!compact && vipBoosted && basePriority && basePriority !== value && (
        <small className="priority-pill-sub">基 {basePriority}</small>
      )}
      {locked && <Lock size={10} aria-label="已人工锁定" />}
    </span>
  );
}

/** 展示生命周期五主态及等待方或结束结果子原因。 */
export function StatusBadge({
  status,
  waitingReason,
  resolution,
  locked = false,
  compact = false,
}: {
  status?: string;
  waitingReason?: string | null;
  resolution?: string | null;
  locked?: boolean;
  compact?: boolean;
}) {
  const main = status || '状态未明';
  const tone = STATUS_CLASSES[main] || 'unknown';
  const sub =
    main === '等待中'
      ? waitingReason
      : main === '已解决' || main === '已取消'
        ? resolution
        : null;
  return (
    <span className={`lifecycle-pill ${tone} ${compact ? 'compact' : ''}`}>
      <i aria-hidden="true" />
      <span>{main}</span>
      {!compact && sub ? <small>· {sub}</small> : null}
      {locked && <Lock size={10} aria-label="已人工锁定" />}
    </span>
  );
}
