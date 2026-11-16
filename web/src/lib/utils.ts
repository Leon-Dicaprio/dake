import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** 合并条件样式，后写的工具类覆盖同一属性。 */
export function cn(...values: ClassValue[]) {
  return twMerge(clsx(values));
}

/** 业务时间固定为上海时间，避免浏览器所在时区改变消息日期。 */
export function formatTime(value: string | null | undefined, dateOnly = false) {
  if (!value) return '—';
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit', hour12: false }),
  });
}

/** 页面错误只展示请求层给出的业务提示。 */
export function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '暂时无法读取，请稍后重试。';
}

/** 处理周期按配置原值转换，不把未知周期误显示为预设值。 */
export function durationLabel(value: string) {
  const match = /^(\d+)([smhd])$/.exec(value);
  const units: Record<string, string> = {
    s: '秒',
    m: '分钟',
    h: '小时',
    d: '天',
  };
  return match ? `${match[1]} ${units[match[2]]}` : value;
}

/** 午夜右开终点显示为前一日；非整日范围保留准确的开始和截至时间。 */
export function formatRange(start: string, end: string) {
  const finish = new Date(end);
  const clock = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(finish);
  const wholeDay = clock === '00:00:00' && finish.getMilliseconds() === 0;
  const displayEnd = wholeDay
    ? new Date(finish.getTime() - 1).toISOString()
    : end;
  return `${formatTime(start, wholeDay)} — ${formatTime(displayEnd, wholeDay)}`;
}
