import { ArrowRight, LoaderCircle } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { ErrorNotice } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeading } from '@/components/ui/dialog';
import { durationLabel, errorMessage } from '@/lib/utils';
import { api } from '@/services/api';

function localInput(value: string) {
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return `${value}T00:00`;
  return new Date(Date.parse(value) + 8 * 3600000).toISOString().slice(0, 16);
}

/** 提交一次明确范围的客户聊天处理任务。 */
export function RunDialog({
  config,
  onClose,
  onCreated,
}: {
  config: API.ConfigResponse;
  onClose: () => void;
  onCreated: (run: API.RunResponse) => void;
}) {
  const [uid, setUid] = useState(config.uid);
  const [start, setStart] = useState(localInput(config.start));
  const [end, setEnd] = useState(
    config.end.includes('T')
      ? localInput(config.end)
      : `${new Date(Date.parse(`${config.end}T00:00:00Z`) + 86400000).toISOString().slice(0, 10)}T00:00`,
  );
  const [interval, setInterval] = useState(config.interval);
  const [offline, setOffline] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (start >= end) {
      setError('结束时间须晚于开始时间。');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const run = await api.createRun({
        uid: uid.trim(),
        start: `${start}:00+08:00`,
        end: `${end}:00+08:00`,
        interval,
        offline,
      });
      onCreated(run);
    } catch (cause) {
      setError(errorMessage(cause));
      setSubmitting(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !submitting) onClose();
      }}
    >
      <DialogContent
        className="run-dialog"
        onEscapeKeyDown={(event) => {
          if (submitting) event.preventDefault();
        }}
      >
        <DialogHeading
          title="开始一次处理"
          description="按选定的时间范围整理聊天，并持续更新已有事件。"
        />
        <form onSubmit={submit}>
          <label className="form-field">
            <span>客户 UID</span>
            <input
              name="uid"
              value={uid}
              onChange={(event) => setUid(event.target.value)}
              required
              pattern="[0-9]+"
              inputMode="numeric"
              autoComplete="off"
            />
          </label>
          <div className="form-grid">
            <label className="form-field">
              <span>开始时间</span>
              <input
                type="datetime-local"
                name="start"
                required
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>
                结束时间<span className="field-hint">不含此刻</span>
              </span>
              <input
                type="datetime-local"
                name="end"
                required
                value={end}
                min={start}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
          </div>
          <p className="field-hint">
            使用北京时间；可先处理一个窗口，再处理紧接的窗口，检查新消息如何更新同一事件。
          </p>
          <label className="form-field">
            <span>每轮处理范围</span>
            <select
              name="interval"
              value={interval}
              onChange={(event) => setInterval(event.target.value)}
            >
              {!['15m', '1h', '1d'].includes(interval) && (
                <option value={interval}>{durationLabel(interval)}</option>
              )}
              <option value="15m">15 分钟</option>
              <option value="1h">1 小时</option>
              <option value="1d">1 天</option>
            </select>
            <small>按这个间隔依次处理选定日期，不会自动定时运行。</small>
          </label>
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={offline}
              onChange={(event) => setOffline(event.target.checked)}
            />
            <span>
              仅使用已保存的聊天<small>取消后会从官方接口读取消息。</small>
            </span>
          </label>
          <div className="notice compact-notice">
            {config.provider === 'xhub'
              ? '将识别客户聊天中的事项，并持续更新已有事件。处理结果可在事件页查看。'
              : '智能识别尚未启用。本次整理与保存聊天，暂不生成分析事件。'}
          </div>
          {error && <ErrorNotice message={error} />}
          <div className="dialog-actions">
            <Button onClick={onClose} disabled={submitting}>
              取消
            </Button>
            <Button variant="primary" type="submit" disabled={submitting}>
              {submitting ? (
                <LoaderCircle className="spinning" size={15} />
              ) : (
                <ArrowRight size={15} />
              )}
              {submitting ? '正在提交' : '开始处理'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
