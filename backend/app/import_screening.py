"""Freeze conservative input selection, retaining every original message."""
from collections import Counter
from time import perf_counter

from . import prefilter, deletions as D
from .db import rows


def prepare(entries):
    started = perf_counter()
    decisions = prefilter.classify(entries)
    for entry, reason in zip(entries, decisions, strict=True):
        entry['prefilter_reason'] = reason
        entry['prefilter_reason_label'] = prefilter.REASONS.get(reason, '')
    counts = Counter(reason for reason in decisions if reason)
    return dict(version=prefilter.VERSION, total=len(entries), retained=len(entries)-sum(counts.values()),
                filtered=sum(counts.values()), restored=0,
                reasons=[dict(code=code, label=prefilter.REASONS[code], count=count) for code,count in sorted(counts.items())],
                elapsed_ms=round((perf_counter()-started)*1000, 3))


def annotate_batches(db, batches):
    """One grouped query for all visible batches; counts describe prefiltering only."""
    confirmed = [str(b['id']) for b in batches if b.get('prefilter_report') and b.get('confirmed_at')]
    counts = {}
    if confirmed:
        for item in rows(db, '''SELECT m.batch_id,d.prefilter_reason,
            count(*) FILTER (WHERE d.state='ignored' AND d.prefilter_restored_at IS NULL) AS filtered,
            count(*) FILTER (WHERE d.prefilter_restored_at IS NOT NULL OR d.state<>'ignored') AS restored
            FROM messages m JOIN message_dispositions d ON d.message_id=m.id
            WHERE m.batch_id=ANY(%s::uuid[]) AND d.prefilter_reason IS NOT NULL
            GROUP BY m.batch_id,d.prefilter_reason''', (confirmed,)):
            counts.setdefault(str(item['batch_id']), []).append(item)
    for batch in batches:
        original = batch.get('prefilter_report')
        summary = dict(original) if original else None
        if summary and batch.get('confirmed_at'):
            current = counts.get(str(batch['id']), [])
            labels = {r['code']:r['label'] for r in original['reasons']}
            summary.update(filtered=sum(r['filtered'] for r in current), restored=sum(r['restored'] for r in current),
                           reasons=[dict(code=r['prefilter_reason'], label=labels.get(r['prefilter_reason'], r['prefilter_reason']),
                                         count=r['filtered']) for r in sorted(current,key=lambda r:r['prefilter_reason']) if r['filtered']])
            summary['retained'] = summary['total']-summary['filtered']
        batch['screening_summary'] = summary
    return batches


def preview_summary(batch, records):
    """Use the same disposition snapshot for counts and paged preview records."""
    original = batch.get('prefilter_report')
    if not original:
        return None
    if not batch.get('confirmed_at'):
        return dict(original)
    counts = Counter(r['prefilter_reason'] for r in records if r['prefilter_filtered'])
    labels = {r['code']:r['label'] for r in original['reasons']}
    filtered = sum(counts.values())
    return dict(original, filtered=filtered, retained=original['total']-filtered,
                restored=sum(r['prefilter_restored'] for r in records),
                reasons=[dict(code=code,label=labels.get(code,code),count=count) for code,count in sorted(counts.items())])


def preview_records(db, batch, entries):
    current = {}
    if batch.get('confirmed_at'):
        current = {m['source_index']:m for m in rows(db, '''SELECT m.id AS message_id,m.source_index,
            d.state AS disposition,d.version AS disposition_version,d.prefilter_reason,d.prefilter_restored_at,
            '''+D.deleted('message','m')+''' AS is_deleted
            FROM messages m JOIN message_dispositions d ON d.message_id=m.id WHERE m.batch_id=%s''', (batch['id'],))}
    result = []
    for index, original in enumerate(entries):
        item = dict(original, source_index=index)
        reason = original.get('prefilter_reason')
        item.update(prefilter_reason=reason, prefilter_reason_label=original.get('prefilter_reason_label',''),
                    prefilter_filtered=bool(reason), prefilter_restored=False, is_deleted=False)
        if index in current:
            state = current[index]
            restored = bool(state['prefilter_restored_at'] or reason and state['disposition']!='ignored')
            item.update(message_id=state['message_id'], disposition=state['disposition'],
                        disposition_version=state['disposition_version'], is_deleted=state['is_deleted'],
                        prefilter_filtered=bool(reason and not restored), prefilter_restored=restored)
        result.append(item)
    return result
