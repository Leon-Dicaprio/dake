import { useLayoutEffect, useRef, useState } from 'react';

export function ExpandableText({
  text,
  lines,
  as: Tag = 'p',
  className,
  empty = '暂无摘要',
}: {
  text: string;
  lines: number;
  as?: 'p' | 'h2';
  className?: string;
  empty?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const value = text.trim();

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || !value) {
      setOverflows(false);
      return;
    }
    if (open) return;
    setOverflows(node.scrollHeight > node.clientHeight + 1);
  }, [open, value]);

  if (!value) {
    return (
      <Tag className={`expandable-empty ${className ?? ''}`.trim()}>
        {empty}
      </Tag>
    );
  }

  return (
    <div className="expandable-text">
      <Tag
        ref={ref as never}
        className={`${className ?? ''} ${open ? 'is-expanded' : 'is-clamped'}`.trim()}
        data-lines={lines}
      >
        {value}
      </Tag>
      {overflows ? (
        <button
          type="button"
          className="expandable-toggle"
          onClick={() => setOpen((current) => !current)}
        >
          {open ? '收起' : '展开'}
        </button>
      ) : null}
    </div>
  );
}
