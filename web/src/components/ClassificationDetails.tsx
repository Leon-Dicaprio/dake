import { EventType } from './EventType';

type FactRecord = {
  value?: unknown;
  quote?: unknown;
  evidence_ids?: unknown;
  evidence_refs?: unknown;
};

function messageRefIds(fact: FactRecord): string[] {
  const refs = Array.isArray(fact.evidence_refs) ? fact.evidence_refs : [];
  const fromRefs = refs
    .map((item) =>
      item && typeof item === 'object'
        ? String(
            (item as Record<string, unknown>).message_id ??
              (item as Record<string, unknown>).id ??
              '',
          )
        : '',
    )
    .filter(Boolean);
  if (fromRefs.length) return [...new Set(fromRefs)];
  const raw = Array.isArray(fact.evidence_ids) ? fact.evidence_ids : [];
  return [
    ...new Set(
      raw.map((id) => String(id || '').replace(/^[^:]+:/, '')).filter(Boolean),
    ),
  ];
}

/** 展示多标签逐项原文依据、按类型归属的专属属性、「其他」排除理由及已撤销标签审计。 */
export function ClassificationDetails({
  event,
  evidence = [],
  onLocate,
}: {
  event: API.EventResponse;
  evidence?: API.EvidenceResponse[];
  onLocate?: (evidenceKeyValue: string) => void;
}) {
  const typeEvidence = event.type_evidence || {};
  const typedAttributes = event.typed_attributes || {};
  const removedTypes = event.removed_types || {};
  const otherReason = event.other_reason;

  const hasTypeEvidence = Object.keys(typeEvidence).length > 0;
  const hasTypedAttrs = Object.values(typedAttributes).some(
    (attrs) => attrs && Object.keys(attrs).length > 0,
  );
  const hasRemoved = Object.keys(removedTypes).length > 0;
  const hasOtherReason = Boolean(
    otherReason && typeof otherReason.quote === 'string',
  );

  if (!hasTypeEvidence && !hasTypedAttrs && !hasRemoved && !hasOtherReason) {
    return null;
  }

  function locateByMessageId(mid: string) {
    if (!onLocate) return;
    const matched = evidence.find((item) => item.message_id === mid);
    if (!matched) return;
    const key = `${matched.source}:${matched.message_id}:${matched.digest || ''}`;
    onLocate(key);
  }

  return (
    <section className="classification-section" aria-label="分类依据与专属属性">
      <h3>分类与专属属性</h3>

      {hasOtherReason && otherReason ? (
        <div className="classification-note">
          <strong>归为「其他」的排除依据：</strong>
          <span>{String(otherReason.value || otherReason.quote || '')}</span>
          {typeof otherReason.quote === 'string' &&
            otherReason.quote !== otherReason.value && (
              <blockquote>{otherReason.quote}</blockquote>
            )}
        </div>
      ) : null}

      {hasTypedAttrs ? (
        <div className="typed-attr-groups">
          {Object.entries(typedAttributes).map(([label, attrs]) => {
            const entries = Object.entries(attrs || {});
            if (!entries.length) return null;
            return (
              <div key={label} className="typed-attr-card">
                <div className="typed-attr-header">
                  <EventType type={label} />
                </div>
                <dl className="typed-attr-list">
                  {entries.map(([name, rawFact]) => {
                    const fact = (rawFact || {}) as FactRecord;
                    const quote =
                      typeof fact.quote === 'string' ? fact.quote : '';
                    const mids = messageRefIds(fact);
                    return (
                      <div key={name}>
                        <dt>{name}</dt>
                        <dd>
                          <span>{String(fact.value ?? '—')}</span>
                          {quote || mids.length ? (
                            <small className="typed-attr-proof">
                              {quote ? `「${quote}」` : ''}
                              {mids.map((mid) =>
                                onLocate &&
                                evidence.some((e) => e.message_id === mid) ? (
                                  <button
                                    key={mid}
                                    type="button"
                                    className="evidence-locate"
                                    onClick={() => locateByMessageId(mid)}
                                  >
                                    消息 {mid}
                                  </button>
                                ) : (
                                  <span key={mid}> 消息 {mid}</span>
                                ),
                              )}
                            </small>
                          ) : null}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </div>
            );
          })}
        </div>
      ) : null}

      {hasTypeEvidence ? (
        <details className="aside-update-facts">
          <summary>查看各标签原文依据</summary>
          <div className="type-evidence-list">
            {Object.entries(typeEvidence).map(([label, facts]) => (
              <div key={label} className="type-evidence-group">
                <strong>{label}</strong>
                {(facts || []).map((rawFact: Record<string, unknown>) => {
                  const fact = (rawFact || {}) as FactRecord;
                  const quote =
                    typeof fact.quote === 'string' ? fact.quote : '';
                  const mids = messageRefIds(fact);
                  return (
                    <blockquote key={`${label}-${mids.join(',')}-${quote}`}>
                      <p>{quote || '未记录引文'}</p>
                      {mids.length ? (
                        <small>消息 {mids.join('、')}</small>
                      ) : null}
                    </blockquote>
                  );
                })}
              </div>
            ))}
          </div>
        </details>
      ) : null}

      {hasRemoved ? (
        <details className="aside-update-facts">
          <summary>
            已更正移除的标签（{Object.keys(removedTypes).join('、')}）
          </summary>
          <div className="type-evidence-list">
            {Object.entries(removedTypes).map(([label, facts]) => (
              <div key={label} className="type-evidence-group">
                <strong>已撤销：{label}</strong>
                {(facts || []).map((rawFact: Record<string, unknown>) => {
                  const fact = (rawFact || {}) as FactRecord;
                  const quote =
                    typeof fact.quote === 'string' ? fact.quote : '';
                  const mids = messageRefIds(fact);
                  return (
                    <blockquote
                      key={`${label}-removed-${mids.join(',')}-${quote}`}
                    >
                      <p>{quote || '已按更正依据撤销'}</p>
                    </blockquote>
                  );
                })}
              </div>
            ))}
          </div>
        </details>
      ) : null}
    </section>
  );
}
