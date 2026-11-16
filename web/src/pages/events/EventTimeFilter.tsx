import { DayPicker } from '@daypicker/react';
import { zhCN } from '@daypicker/react/locale';
import * as Popover from '@radix-ui/react-popover';
import { CalendarDays, ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { messageDay } from './eventTimeRange';
import '@daypicker/react/style.css';

export const timeRanges = [
  { value: '', label: '全部时间', days: 0 },
  { value: 'today', label: '最新一天', days: 1 },
  { value: '3d', label: '近 3 天', days: 3 },
  { value: '7d', label: '近 7 天', days: 7 },
  { value: 'custom', label: '自定义', days: 0 },
];
/** 日历只表示日期，不进行业务消息的时区转换。 */
function parseDay(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const date = new Date(`${value}T12:00:00`);
  return Number.isFinite(date.getTime()) && dateKey(date) === value
    ? date
    : undefined;
}
function dateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function presetDates(mode: string, anchor: string) {
  const days = timeRanges.find((item) => item.value === mode)?.days;
  const last = parseDay(anchor);
  if (!days || !last) return ['', ''];
  last.setDate(last.getDate() - days + 1);
  return [dateKey(last), anchor];
}
/** 草稿和已应用筛选分开；关闭弹层不会改变列表。 */
export function EventTimeFilter({
  mode,
  start,
  end,
  anchor,
  onApply,
}: {
  mode: string;
  start: string;
  end: string;
  anchor: string;
  onApply: (values: Record<string, string>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftMode, setDraftMode] = useState(mode);
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);
  const [month, setMonth] = useState<Date>();
  const anchorDate = messageDay(anchor);
  const applied =
    mode === 'custom' ? [start, end] : presetDates(mode, anchorDate);
  const label = !mode
    ? '全部时间'
    : applied[0] || applied[1]
      ? `${applied[0] || '不限'} 至 ${applied[1] || '不限'}`
      : '选择日期范围';
  const invalid = Boolean(
    (from && !parseDay(from)) ||
      (to && !parseDay(to)) ||
      (from && to && from > to),
  );
  const incomplete = draftMode === 'custom' && (!from || !to);
  function resetDraft(nextMode: string) {
    const dates =
      nextMode === 'custom' ? [start, end] : presetDates(nextMode, anchorDate);
    setDraftMode(nextMode);
    setFrom(dates[0]);
    setTo(dates[1]);
    setMonth(parseDay(dates[0] || anchorDate) || new Date());
  }
  return (
    <Popover.Root
      open={open}
      onOpenChange={(value) => {
        if (value) resetDraft(mode);
        setOpen(value);
      }}
    >
      <Popover.Trigger asChild>
        <button
          className="time-filter-trigger"
          type="button"
          aria-label={`时间范围：${label}`}
        >
          <CalendarDays size={15} />
          <span>{label}</span>
          <ChevronDown size={14} />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="time-filter-popover"
          align="start"
          sideOffset={8}
          collisionPadding={12}
          aria-label="选择时间范围"
        >
          <header>
            <strong>选择时间范围</strong>
            <p>按事件最后关联消息时间 · 上海时区</p>
          </header>
          <div className="time-filter-presets">
            {timeRanges
              .filter((item) => item.value !== 'custom')
              .map((item) => (
                <button
                  type="button"
                  key={item.value}
                  aria-pressed={draftMode === item.value}
                  disabled={Boolean(item.days && !anchorDate)}
                  onClick={() => resetDraft(item.value)}
                >
                  {item.label}
                </button>
              ))}
          </div>
          <p className="time-filter-note">
            快捷范围截至数据最新日
            {anchorDate ? ` ${anchorDate}` : '（暂无数据）'}。
          </p>
          <div className="time-filter-inputs">
            <label>
              开始日期
              <input
                type="date"
                aria-label="开始日期"
                value={from}
                onChange={(e) => {
                  setDraftMode('custom');
                  setFrom(e.target.value);
                  if (parseDay(e.target.value))
                    setMonth(parseDay(e.target.value));
                }}
              />
            </label>
            <span aria-hidden="true">—</span>
            <label>
              结束日期
              <input
                type="date"
                aria-label="结束日期"
                value={to}
                onChange={(e) => {
                  setDraftMode('custom');
                  setTo(e.target.value);
                }}
              />
            </label>
          </div>
          <DayPicker
            mode="range"
            locale={zhCN}
            weekStartsOn={1}
            month={month}
            onMonthChange={setMonth}
            selected={
              parseDay(from)
                ? { from: parseDay(from), to: parseDay(to) }
                : undefined
            }
            onSelect={(value) => {
              setDraftMode('custom');
              setFrom(value?.from ? dateKey(value.from) : '');
              setTo(value?.to ? dateKey(value.to) : '');
            }}
            labels={{
              labelPrevious: () => '上个月',
              labelNext: () => '下个月',
            }}
          />
          <p className="time-filter-note" role={invalid ? 'alert' : undefined}>
            {invalid
              ? '日期范围无效，开始日期不能晚于结束日期。'
              : incomplete
                ? '请选择开始和结束日期，可选择同一天。'
                : '包含开始和结束当天的全部消息时间。'}
          </p>
          <footer>
            <Button
              variant="ghost"
              onClick={() => {
                onApply({ range: '', startDate: '', endDate: '', event: '' });
                setOpen(false);
              }}
            >
              清除筛选
            </Button>
            <div>
              <Button variant="ghost" onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button
                variant="primary"
                disabled={invalid || incomplete}
                onClick={() => {
                  onApply({
                    range: draftMode,
                    startDate: draftMode === 'custom' ? from : '',
                    endDate: draftMode === 'custom' ? to : '',
                    event: '',
                  });
                  setOpen(false);
                }}
              >
                应用
              </Button>
            </div>
          </footer>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
