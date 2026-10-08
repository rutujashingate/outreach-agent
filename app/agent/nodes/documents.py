"""Bring immutable extracted sources into a run before interpreting its goal."""
import json
from app.domain.documents import DocumentEvidence
from app.storage.documents import document_record
from app.connectors.search import ToolError
from app.storage.events import trace


def evidence_records(documents):
    return [{'filename': doc.filename, 'purpose': doc.purpose,
             'source': doc.source(page.number), 'text': page.text}
            for doc in documents for page in doc.pages if page.text]


def bounded_evidence(records, max_chars, max_text_chars=80000):
    """Return complete JSON with a fair share of text from every cited page.

    JSON escaping also consumes space, so measure the serialized result rather
    than cutting it in the middle. Full filenames/text remain in saved evidence.
    """
    if not records:
        return '', False
    headers = [{**item, 'filename': item['filename'][:80]} for item in records]
    low, high = 0, min(max(len(item['text']) for item in records), max_text_chars // len(records))

    def encode(allowance):
        return json.dumps({'uploaded_documents': [{**item, 'text': item['text'][:allowance]}
                                                   for item in headers]}, ensure_ascii=False)

    while low < high:
        middle = (low + high + 1) // 2
        if len(encode(middle)) <= max_chars: low = middle
        else: high = middle - 1
    return encode(low), any(len(item['text']) > low for item in records)


async def prepare_documents(state, runtime):
    if not state.attachments: return {}
    documents = []
    for attachment in state.attachments:
        record = document_record(runtime.context.repository.engine, attachment.document_id)
        if record is None or record['status'] != 'ready':
            raise ToolError('An attached file is not ready. Check its extraction status, retry it if needed, then retry this run.')
        documents.append(DocumentEvidence(document_id=record['id'], filename=record['filename'],
            purpose=attachment.purpose, sha256=record['sha256'], extracted_at=record['extracted_at'], **record['content']))
    # Store file sources separately. Later nodes can cite a filename/page,
    # and the dashboard can show exactly what the reader extracted.
    notices = []
    background = '\n\n'.join(f"[{item['filename']}; {item['source']}]\n{item['text']}"
        for item in evidence_records(documents) if item['purpose'] == 'background')
    context = state.sender.context
    if background:
        combined = context + '\n\nOwner-supplied background documents:\n' + background
        if len(combined) > 10000: notices.append('Background was shortened to the 10,000-character sender-context limit.')
        context = combined[:10000]
    trace(runtime.context.repository, state.run_id, 'documents_loaded',
          document_ids=[d.document_id for d in documents], pages=sum(len(d.pages) for d in documents))
    return {'documents': documents, 'document_warnings': notices,
            'sender': state.sender.model_copy(update={'context': context})}
