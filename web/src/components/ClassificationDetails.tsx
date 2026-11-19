import { formatMetricNumber, productDisplayName } from '@/lib/productLabels';

type FactRecord = {
  value?: unknown;
  quote?: unknown;
  evidence_ids?: unknown;
  evidence_refs?: unknown;
};

type StructuredEvidenceRecord = {
  field_id?: unknown;
  scope_type?: unknown;
  scope_key?: unknown;
  label?: unknown;
  unit?: unknown;
  normalized_value?: unknown;
  raw_value?: unknown;
  quote?: unknown;
  evidence_ids?: unknown;
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

/** 展示可配置产品归属、强类型结构化属性指标、分类标签原文依据及更正记录。 */
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
  const removedTypes = event.removed_types || {};
  const otherReason = event.other_reason;
  const products = event.products || [];
  const structuredEvidence = (event.structured_evidence ||
    []) as StructuredEvidenceRecord[];

  const hasTypeEvidence = Object.keys(typeEvidence).length > 0;
  const hasRemoved = Object.keys(removedTypes).length > 0;
  const hasOtherReason = Boolean(
    otherReason && typeof otherReason.quote === 'string',
  );
  const hasProducts = products.length > 0;
  const hasStructured = structuredEvidence.length > 0;

  if (
    !hasTypeEvidence &&
    !hasRemoved &&
    !hasOtherReason &&
    !hasProducts &&
    !hasStructured
  ) {
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
    <section className="classification-section" aria-label="产品与结构化属性">
      <h3>产品与结构化属性</h3>

      {hasProducts || hasStructured ? (
        <div className="typed-attr-card mb-3">
          {hasProducts ? (
            <div className="typed-attr-header flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-neutral-500">
                涉及产品：
              </span>
              {products.map((pkey) => (
                <span
                  key={pkey}
                  className="inline-flex items-center rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-amber-200/80 ring-inset"
                >
                  {productDisplayName(pkey)}
                </span>
              ))}
            </div>
          ) : null}
          {hasStructured ? (
            <dl className="typed-attr-list">
              {structuredEvidence.map((item, idx) => {
                const label = String(
                  item.label || item.field_id || `字段${idx}`,
                );
                const unit = typeof item.unit === 'string' ? item.unit : '';
                const formatted = formatMetricNumber(
                  item.normalized_value,
                  unit,
                );
                const quote = typeof item.quote === 'string' ? item.quote : '';
                const mids = messageRefIds({
                  evidence_ids: item.evidence_ids,
                });
                return (
                  <div key={String(item.field_id || idx)}>
                    <dt>{label}</dt>
                    <dd>
                      <span className="font-medium">{formatted}</span>
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
          ) : null}
        </div>
      ) : null}

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
                <strong>{label}</strong>
                {(facts || []).map((rawFact: Record<string, unknown>) => {
                  const fact = (rawFact || {}) as FactRecord;
                  const quote =
                    typeof fact.quote === 'string' ? fact.quote : '';
                  const mids = messageRefIds(fact);
                  return (
                    <blockquote key={`${label}-${mids.join(',')}-${quote}`}>
                      <p>{quote || '未记录更正引文'}</p>
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
    </section>
  );
}
