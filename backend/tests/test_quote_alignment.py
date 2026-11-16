"""只使用虚构正文核对空白还原，不接受改字、错编号或多义位置。"""
import json
from dake.analysis.quote_alignment import align_quotes
from test_attribution import message, model_output
from dake.analysis.attribution import parse_attribution_output


def test_whitespace_restores_original_for_formal_changes():
    msg = message('align', 1, '虚构接口HTTP429，仍未恢复。')
    payload = json.loads(model_output(msg))
    payload['candidates'][0]['changes'][0]['evidence'][0]['quote'] = '虚构接口 HTTP 429，仍未恢复。'
    result = parse_attribution_output(json.dumps(payload), [msg], [], [])
    assert result[0].changes[0]['evidence'][0]['quote'] == msg.content


def test_wrong_id_changed_text_and_ambiguous_quote_remain_rejected():
    msg = message('align', 1, '虚构未恢复。虚构未恢复。')
    for key, quote in [(msg.key, '虚构 未恢复。'), ('official_chat:other', '虚构 未恢复。'),
                       (msg.key, '虚构已恢复。')]:
        raw = {'message_id': key, 'quote': quote}
        assert json.loads(align_quotes(json.dumps(raw), [msg])) == raw


def test_normalization_never_changes_message_id_or_fact_text():
    msg = message('align', 1, '虚构报告\n仍然失败。')
    raw = {'message_id': msg.key, 'quote': '虚构报告 仍然失败。', 'text': '原有事实文字'}
    normalized = json.loads(align_quotes(json.dumps(raw), [msg]))
    assert normalized == {**raw, 'quote': msg.content}
