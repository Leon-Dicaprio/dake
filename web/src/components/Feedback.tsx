import * as Toast from '@radix-ui/react-toast';
import {
  ArrowRight,
  Check,
  Inbox,
  RefreshCw,
  TriangleAlert,
  X,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from './ui/button';

/** 请求失败保留明确重试入口，不用空列表掩盖连接问题。 */
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-notice" role="alert">
      <TriangleAlert size={16} />
      <span>{message}</span>
      {retry && (
        <Button size="small" variant="ghost" onClick={retry}>
          <RefreshCw size={14} />
          重试
        </Button>
      )}
    </div>
  );
}

/** 空状态只说明当前事实，操作由页面提供。 */
export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        {icon || <Inbox size={26} strokeWidth={1.4} />}
      </div>
      <h2>{title}</h2>
      {description ? <p>{description}</p> : null}
      {action && (
        <div className="empty-action">
          {action}
          <ArrowRight size={14} />
        </div>
      )}
    </div>
  );
}

/** 首屏骨架与实际表格保持相同密度，避免加载时大幅跳动。 */
export function LoadingRows({ count = 5 }: { count?: number }) {
  return (
    <div className="loading-rows" role="status" aria-label="正在读取">
      <span className="sr-only">正在读取</span>
      {['first', 'second', 'third', 'fourth', 'fifth']
        .slice(0, count)
        .map((row) => (
          <div className="loading-row" key={row}>
            <i />
            <i />
            <i />
          </div>
        ))}
    </div>
  );
}

/** 短操作回执在固定浮层展示，支持键盘关闭与悬停暂停。 */
export function SuccessToast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <Toast.Provider label="操作提示">
      {message && (
        <Toast.Root
          key={message}
          open
          onOpenChange={(open) => {
            if (!open) onDismiss();
          }}
          className="success-toast"
        >
          <Check size={16} aria-hidden="true" />
          <Toast.Description>{message}</Toast.Description>
          <Toast.Close aria-label="关闭提示">
            <X size={16} />
          </Toast.Close>
        </Toast.Root>
      )}
      <Toast.Viewport
        className="success-toast-viewport"
        label="操作提示（{hotkey}）"
      />
    </Toast.Provider>
  );
}
