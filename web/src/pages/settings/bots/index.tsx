import { Bot, Pencil, RefreshCw, Search } from 'lucide-react';
import { useState } from 'react';
import { ErrorNotice, LoadingRows, SuccessToast } from '@/components/Feedback';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeading } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useResource } from '@/lib/useResource';
import { errorMessage, formatTime } from '@/lib/utils';
import { api } from '@/services/api';
import './style.css';

const identities = { bot: '机器人', human: '人工账号', unknown: '待确认' };
type Editing = { rule: API.SenderRule; ruleId?: string; groupName?: string };

/** 身份配置与处理记录分开，保存规则只影响后续窗口。 */
export default function BotSettingsPage() {
  const [tab, setTab] = useState<'rules' | 'search'>('rules');
  const [input, setInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Editing>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const rules = useResource('sender-rules', api.senderRules);
  const candidates = useResource(
    tab === 'search' ? `sender-candidates:${keyword}:${offset}` : null,
    (signal) => api.senderCandidates(keyword, offset, signal),
  );
  const items = rules.data?.items || [];
  const enabledCount = items.filter((item) => item.enabled).length;

  function search(value: string) {
    setInput(value);
    setKeyword(value.trim());
    setOffset(0);
    setTab('search');
    candidates.refresh();
  }

  async function save(rule: API.SenderRule, ruleId?: string) {
    if (!rules.data || busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api.saveSenderRule({
        expected_version: rules.data.version,
        rule_id: ruleId,
        rule,
      });
      setEditing(undefined);
      setNotice('已保存，从后续处理窗口生效。历史事件保留原记录。');
      rules.refresh();
      candidates.refresh();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  function edit(item: API.SenderRuleResponse) {
    const { rule_id, ...rule } = item;
    setError('');
    setEditing({ rule, ruleId: rule_id });
  }

  function select(item: API.SenderCandidate) {
    const existing = items.find((rule) => rule.rule_id === item.rule_id);
    if (existing) return edit(existing);
    setError('');
    setEditing({
      groupName: item.conversation_name,
      rule: {
        uid: item.uid,
        source: item.source,
        sender_id: item.sender_id,
        conversation_id: item.conversation_id || undefined,
        kind: 'bot',
        label: item.sender_name,
        basis: '在配置页面人工确认账号身份',
        enabled: true,
      },
    });
  }

  return (
    <main className="page bot-rules-page">
      <header className="page-header">
        <div>
          <h1>机器人筛选</h1>
          <p className="bot-rule-count">
            {rules.data && (
              <>
                {enabledCount} 条规则已启用 · {items.length - enabledCount}{' '}
                条已停用
              </>
            )}
          </p>
        </div>
        <Button
          variant="ghost"
          onClick={() => {
            rules.refresh();
            candidates.refresh();
          }}
        >
          <RefreshCw size={16} />
          刷新
        </Button>
      </header>
      <SuccessToast message={notice} onDismiss={() => setNotice('')} />
      {rules.error && (
        <ErrorNotice message={rules.error} retry={rules.refresh} />
      )}
      {error && !editing && (
        <ErrorNotice message={error} retry={rules.refresh} />
      )}
      <Tabs
        value={tab}
        onValueChange={(value) =>
          setTab(value === 'search' ? 'search' : 'rules')
        }
      >
        <TabsList aria-label="机器人配置视图">
          <TabsTrigger value="rules" className="flex items-center gap-2">
            已配置账号 <span className="heading-count">{items.length}</span>
          </TabsTrigger>
          <TabsTrigger value="search" className="flex items-center gap-2">
            <Search size={15} />
            查找账号
          </TabsTrigger>
        </TabsList>
        <TabsContent value="rules">
          <section aria-label="已配置账号" className="bot-table-panel">
            <table className="bot-rule-table">
              <thead>
                <tr>
                  <th>账号</th>
                  <th>适用范围</th>
                  <th>身份</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody aria-busy={rules.loading}>
                {items.map((item) => (
                  <tr key={item.rule_id}>
                    <td>
                      <strong>{item.label || item.sender_id}</strong>
                      <small>{item.sender_id}</small>
                    </td>
                    <td>
                      客户 {item.uid}
                      <small>
                        {item.conversation_id
                          ? `指定群：${item.conversation_id}`
                          : '该客户的全部群'}
                      </small>
                    </td>
                    <td>{identities[item.kind || 'bot']}</td>
                    <td>
                      <span
                        className={`bot-status ${item.enabled ? 'enabled' : ''}`}
                      >
                        {item.enabled ? '已启用' : '已停用'}
                      </span>
                    </td>
                    <td className="bot-row-actions">
                      <Button
                        size="small"
                        variant="ghost"
                        disabled={busy || rules.loading}
                        onClick={() => edit(item)}
                      >
                        <Pencil size={14} />
                        编辑
                      </Button>
                      <Button
                        size="small"
                        disabled={busy || rules.loading}
                        onClick={() => {
                          const { rule_id, ...rule } = item;
                          void save(
                            { ...rule, enabled: !item.enabled },
                            rule_id,
                          );
                        }}
                      >
                        {item.enabled ? '停用' : '启用'}
                      </Button>
                    </td>
                  </tr>
                ))}
                {rules.loading && !rules.data ? (
                  <tr>
                    <td colSpan={5}>
                      <LoadingRows count={2} />
                    </td>
                  </tr>
                ) : (
                  !rules.error &&
                  !items.length && (
                    <tr>
                      <td colSpan={5} className="bot-empty">
                        暂无配置，先从已同步的消息中查找账号。
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          </section>
        </TabsContent>
        <TabsContent value="search">
          <section aria-label="查找发送账号">
            <form
              className="bot-search-form"
              onSubmit={(event) => {
                event.preventDefault();
                search(input);
              }}
            >
              <Input
                aria-label="账号名称或账号"
                placeholder="搜索发送人名称或账号"
                maxLength={128}
                value={input}
                onChange={(event) => setInput(event.target.value)}
              />
              <Button type="submit">
                <Search size={15} />
                搜索
              </Button>
              <Button variant="ghost" onClick={() => search('maas')}>
                查找 MAAS 账号
              </Button>
            </form>
            <p className="bot-search-help">
              名称仅用于查找。同名账号可能不同，请核对客户、群聊和账号后再配置。
            </p>
            {candidates.error && (
              <ErrorNotice
                message={candidates.error}
                retry={candidates.refresh}
              />
            )}
            <div className="bot-table-panel">
              <table className="bot-rule-table">
                <thead>
                  <tr>
                    <th>发送账号</th>
                    <th>客户与群</th>
                    <th>已接收消息</th>
                    <th>当前身份</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody aria-busy={candidates.loading}>
                  {candidates.data?.items.map((item) => (
                    <tr key={item.rule_id}>
                      <td>
                        <strong>{item.sender_name}</strong>
                        <small>{item.sender_id}</small>
                      </td>
                      <td>
                        客户 {item.uid}
                        <small>{item.conversation_name}</small>
                      </td>
                      <td>
                        {item.message_count} 条
                        <small>{formatTime(item.last_seen_at)}</small>
                      </td>
                      <td>{identities[item.sender_kind]}</td>
                      <td>
                        <Button
                          size="small"
                          disabled={busy || !rules.data || rules.loading}
                          onClick={() => select(item)}
                        >
                          {item.configured ? '编辑配置' : '配置账号'}
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {candidates.loading && !candidates.data ? (
                    <tr>
                      <td colSpan={5}>
                        <LoadingRows count={2} />
                      </td>
                    </tr>
                  ) : (
                    !candidates.error &&
                    !candidates.data?.items.length && (
                      <tr>
                        <td colSpan={5} className="bot-empty">
                          未找到匹配账号，可在相关消息同步后再查找。
                        </td>
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </div>
            <div className="bot-paging">
              <span>
                {candidates.data
                  ? `共 ${candidates.data.total} 条账号与群记录`
                  : ''}
              </span>
              <Button
                size="small"
                disabled={offset === 0 || candidates.loading}
                onClick={() => setOffset(Math.max(0, offset - 25))}
              >
                上一页
              </Button>
              <Button
                size="small"
                disabled={
                  candidates.loading ||
                  offset + 25 >= (candidates.data?.total || 0)
                }
                onClick={() => setOffset(offset + 25)}
              >
                下一页
              </Button>
            </div>
          </section>
        </TabsContent>
      </Tabs>
      <aside className="bot-policy-note" aria-label="筛选说明">
        <Bot size={17} aria-hidden="true" />
        <div>
          <strong>机器人通知保留原文，不单独生成事件。</strong>
          <p>
            有人参与讨论时，通知仍可作为证据。按账号和适用范围识别，改名不影响已有规则。
          </p>
        </div>
      </aside>
      {editing && (
        <RuleEditor
          editing={editing}
          busy={busy}
          error={error}
          onClose={() => {
            if (!busy) setEditing(undefined);
          }}
          onSave={save}
          onRefresh={rules.refresh}
        />
      )}
    </main>
  );
}

function RuleEditor({
  editing,
  busy,
  error,
  onClose,
  onSave,
  onRefresh,
}: {
  editing: Editing;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSave: (rule: API.SenderRule, ruleId?: string) => Promise<void>;
  onRefresh: () => void;
}) {
  const [value, setValue] = useState(editing.rule);
  const group = editing.rule.conversation_id;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="dialog-centered bot-rule-dialog">
        <DialogHeading
          title="配置账号身份"
          description="保存后影响后续处理窗口；已生成的历史事件不会自动重算。"
        />
        <form
          className="bot-rule-form"
          onSubmit={(event) => {
            event.preventDefault();
            void onSave(value, editing.ruleId);
          }}
        >
          <div className="bot-account-summary">
            客户 {value.uid}
            <small>账号 {value.sender_id}</small>
          </div>
          <label htmlFor="bot-rule-label">
            显示名称
            <Input
              id="bot-rule-label"
              value={value.label || ''}
              maxLength={256}
              onChange={(event) =>
                setValue({ ...value, label: event.target.value })
              }
            />
          </label>
          <label>
            账号身份
            <select
              value={value.kind || 'bot'}
              onChange={(event) =>
                setValue({
                  ...value,
                  kind: event.target.value as API.SenderRule['kind'],
                })
              }
            >
              <option value="bot">机器人</option>
              <option value="human">人工账号</option>
              <option value="unknown">待确认</option>
            </select>
          </label>
          <label>
            适用范围
            <select
              value={value.conversation_id ? 'group' : 'customer'}
              onChange={(event) =>
                setValue({
                  ...value,
                  conversation_id:
                    event.target.value === 'group' ? group : null,
                })
              }
            >
              {group && (
                <option value="group">
                  仅当前群{editing.groupName ? `：${editing.groupName}` : ''}
                </option>
              )}
              <option value="customer">该客户的全部群</option>
            </select>
          </label>
          <label htmlFor="bot-rule-basis">
            确认依据
            <Input
              id="bot-rule-basis"
              required
              maxLength={500}
              value={value.basis}
              onChange={(event) =>
                setValue({ ...value, basis: event.target.value })
              }
            />
          </label>
          <label className="bot-enable-field">
            <input
              type="checkbox"
              checked={value.enabled ?? true}
              onChange={(event) =>
                setValue({ ...value, enabled: event.target.checked })
              }
            />
            启用这条规则
          </label>
          <p className="bot-search-help">
            具体群的规则优先。停用后仍可能命中该客户全部群的配置。
          </p>
          {error && <ErrorNotice message={error} retry={onRefresh} />}
          <div className="bot-dialog-actions">
            <Button disabled={busy} onClick={onClose}>
              取消
            </Button>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? '保存中…' : '保存规则'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
