import { ChevronDown, ListFilter } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

type FilterKey = 'type' | 'status' | 'priority' | 'group';
type FilterOption = { value: string; label: string };

/** 四个条件即时生效，收起后在入口标出已用条件数。 */
export function EventListFilters({
  values,
  types,
  statuses,
  priorities,
  groups,
  update,
}: {
  values: Record<FilterKey, string>;
  types: string[];
  statuses: string[];
  priorities: string[];
  groups: { id: string; name: string }[];
  update: (values: Record<string, string>) => void;
}) {
  const options = (items: string[]) =>
    items.map((value) => ({ value, label: value }));
  const fields: {
    key: FilterKey;
    label: string;
    all: string;
    options: FilterOption[];
  }[] = [
    {
      key: 'type',
      label: '事件类型',
      all: '全部类型',
      options: options(types),
    },
    {
      key: 'status',
      label: '事件状态',
      all: '全部状态',
      options: options(statuses),
    },
    {
      key: 'priority',
      label: '优先级',
      all: '全部优先级',
      options: options(priorities),
    },
    {
      key: 'group',
      label: '群聊',
      all: '全部群聊',
      options: groups.map(({ id, name }) => ({ value: id, label: name })),
    },
  ];
  const selected = fields.filter(({ key }) => values[key]);
  const summary = selected
    .map(
      ({ key, options }) =>
        options.find((item) => item.value === values[key])?.label ||
        values[key],
    )
    .join('、');
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          className="event-filter-trigger"
          variant="ghost"
          size="small"
          title={summary || '按类型、状态、优先级或群聊筛选'}
        >
          <ListFilter size={15} aria-hidden="true" />
          筛选{selected.length > 0 && <span>{selected.length}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        collisionPadding={12}
        sideOffset={6}
        className="event-filter-popover"
        aria-label="筛选事件"
      >
        <header>
          <h3>筛选事件</h3>
          <Button
            variant="ghost"
            size="small"
            disabled={!selected.length}
            onClick={() =>
              update({
                type: '',
                status: '',
                priority: '',
                group: '',
                event: '',
              })
            }
          >
            清除条件
          </Button>
        </header>
        <div className="event-filter-fields">
          {fields.map(({ key, label, all, options }) => (
            <label key={key}>
              {label}
              <span className="filter-select">
                <select
                  aria-label={label}
                  value={values[key]}
                  onChange={(event) =>
                    update({ [key]: event.target.value, event: '' })
                  }
                >
                  <option value="">{all}</option>
                  {values[key] &&
                    !options.some(({ value }) => value === values[key]) && (
                      <option value={values[key]}>{values[key]}</option>
                    )}
                  {options.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} aria-hidden="true" />
              </span>
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
