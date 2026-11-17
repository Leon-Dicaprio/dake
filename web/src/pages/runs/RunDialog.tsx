import { ArrowRight, LoaderCircle } from 'lucide-react';
import { type FormEvent, useState } from 'react';
import { ErrorNotice } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeading } from '@/components/ui/dialog';
import { durationLabel, errorMessage } from '@/lib/utils';
import { api } from '@/services/api';

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
  const [start, setStart] = useState(config.start.slice(0, 10));
  const [end, setEnd] = useState(config.end.slice(0, 10));
  const [interval, setInterval] = useState(config.interval);
  const [offline, setOffline] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (start > end) {
      setError('结束日期不能早于开始日期。');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const run = await api.createRun({
        uid: uid.trim(),
        start,
        end,
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
              <span>开始日期</span>
              <input
                type="date"
                name="start"
                required
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label className="form-field">
              <span>
                结束日期<span className="field-hint">含当天</span>
              </span>
              <input
                type="date"
                name="end"
                required
                value={end}
                min={start}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
          </div>
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
