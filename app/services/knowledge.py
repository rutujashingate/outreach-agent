"""Build a searchable owner library from real file and website evidence.

Index jobs publish an entire source version in one transaction. Failed rebuilds
keep the previous searchable version; a retry does not duplicate passages.
"""
import asyncio
from hashlib import sha256
import json
import math
import re
from uuid import uuid4

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.connectors.search import ToolError
from app.llm.embeddings import VERSION, LocalEmbeddings, checked_vectors
from app.storage.control import ControlStore, now
from app.storage.knowledge import KnowledgeSource, KnowledgeChunk
from app.storage.repository import stable_id
from app.services.runs import RunNotFound


def fallback_chunks(value):
    words = list(re.finditer(r'\S+', value))
    return [value[words[i].start():words[min(i+120, len(words))-1].end()][:4000]
            for i in range(0, len(words), 100)]


def capture_source(engine, *, kind, ref, label, pages, retrieved_at, purpose='background'):
    """Save bounded extracted evidence and enqueue indexing, without model calls."""
    store = ControlStore(engine)
    if not store.get('knowledge:enabled', {}).get('enabled'):
        return None
    remaining, bounded = 40000, []
    for page in pages[:20]:
        value = page['text'][:remaining]
        if value.strip(): bounded.append({'number': page['number'], 'text': value})
        remaining -= len(value)
        if remaining <= 0: break
    if not bounded: return None
    source_id = stable_id(kind, ref)
    digest = sha256(json.dumps(bounded, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    keyword_revision = digest + ':keyword'
    with Session(engine) as session, session.begin():
        source = session.get(KnowledgeSource, source_id)
        if source is None:
            source = KnowledgeSource(id=source_id, kind=kind, ref=ref, label=label[:300],
                purpose=purpose, retrieved_at=retrieved_at, content_hash=digest, pages=bounded)
            session.add(source)
            session.flush()
        elif source.content_hash != digest:
            source.pages, source.content_hash = bounded, digest
            source.retrieved_at, source.label, source.purpose = retrieved_at, label[:300], purpose
            source.status, source.error, source.updated_at = 'queued', None, now()
        if source.active_version is None:
            ordinal = 0
            for page in bounded:
                page_ref = f'{ref}#page={page["number"]}' if kind == 'document' else ref
                for passage in fallback_chunks(page['text']):
                    session.add(KnowledgeChunk(id=stable_id(source_id, keyword_revision, str(ordinal)),
                        source_id=source_id, ordinal=ordinal, page=page['number'], ref=page_ref,
                        content=passage, embedding_version='keyword', revision=keyword_revision,
                        evidence={'label': label[:300], 'purpose': purpose, 'retrieved_at': retrieved_at,
                                  'kind': kind, 'content_hash': digest}, embedding=None))
                    ordinal += 1
            source.active_version = keyword_revision
    store.enqueue('knowledge', None, {'source_id': source_id}, 'index:' + source_id + ':' + digest[:16] + ':' + VERSION)
    return source_id


def capture_page(engine, page):
    if page.error or not page.text.strip(): return None
    return capture_source(engine, kind='website', ref=page.url, label=page.title or page.url,
        pages=[{'number': 1, 'text': page.text}], retrieved_at=page.retrieved_at.isoformat(), purpose='research')


class KnowledgeService:
    def __init__(self, engine, settings, embedder=None):
        self.engine, self.settings = engine, settings
        self.store = ControlStore(engine)
        self.embedder = embedder or LocalEmbeddings(settings.data_dir / 'models')
        self.store.put('knowledge:enabled', {'enabled': settings.semantic_search_enabled})

    def status(self):
        with Session(self.engine) as session:
            counts = dict(session.execute(select(KnowledgeSource.status, func.count()).group_by(KnowledgeSource.status)).all())
            chunks = session.scalar(select(func.count()).select_from(KnowledgeChunk))
        return {'enabled': self.settings.semantic_search_enabled, 'backend': 'pgvector' if self.engine.dialect.name == 'postgresql' else 'local-test',
                'sources': counts, 'passages': chunks, 'embedding': self.embedder.status()}

    def sources(self, page=1):
        with Session(self.engine) as session:
            rows = session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.updated_at.desc(), KnowledgeSource.id)
                                   .offset((page-1)*20).limit(20))
            return {'page': page, 'items': [{key: getattr(row, key) for key in
                ('id', 'kind', 'ref', 'label', 'purpose', 'retrieved_at', 'status', 'active_version', 'error')} for row in rows]}

    def capture_document(self, record):
        return capture_source(self.engine, kind='document', ref='document:' + record['id'], label=record['filename'],
            pages=record['content'].get('pages', []), retrieved_at=record['extracted_at'], purpose='background')

    def reindex(self, source_id, key):
        if not self.settings.semantic_search_enabled: raise ToolError('Enable semantic search before reindexing.')
        previous = self.store.find_job(key)
        if previous: return previous
        with Session(self.engine) as session, session.begin():
            source = session.get(KnowledgeSource, source_id)
            if source is None: raise RunNotFound('Unknown knowledge source.')
            source.status, source.error = 'queued', None
        return self.store.enqueue('knowledge', None, {'source_id': source_id}, key)

    async def index(self, source_id):
        if not self.settings.semantic_search_enabled: raise ToolError('Semantic search is disabled.')
        with Session(self.engine) as session:
            source = session.get(KnowledgeSource, source_id)
            if source is None: raise RunNotFound('Unknown knowledge source.')
            snapshot = {key: getattr(source, key) for key in ('content_hash', 'pages', 'kind', 'ref', 'label', 'purpose', 'retrieved_at')}
            revision = source.content_hash + ':' + self.embedder.version
            if source.active_version == revision and source.status == 'ready': return
        with Session(self.engine) as session, session.begin():
            session.execute(update(KnowledgeSource).where(KnowledgeSource.id == source_id).values(status='indexing', error=None))
        try:
            passages = []
            for page in snapshot['pages']:
                for value in await self.embedder.chunks(page['text']):
                    passages.append((page['number'], value))
            if not passages: raise ToolError('The source has no extractable text.')
            vectors = checked_vectors(await self.embedder.passages([value for _, value in passages]), len(passages))
            def publish():
                with Session(self.engine) as session, session.begin():
                    source = session.get(KnowledgeSource, source_id)
                    if source.content_hash != snapshot['content_hash']:
                        return  # A newer capture has its own queued rebuild.
                    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id))
                    for ordinal, ((page, value), vector) in enumerate(zip(passages, vectors)):
                        ref = f'{snapshot["ref"]}#page={page}' if snapshot['kind'] == 'document' else snapshot['ref']
                        session.add(KnowledgeChunk(id=stable_id(source_id, revision, str(ordinal)), source_id=source_id,
                            ordinal=ordinal, page=page, ref=ref, content=value, embedding=vector,
                            embedding_version=self.embedder.version, revision=revision,
                            evidence={key: snapshot[key] for key in ('label', 'purpose', 'retrieved_at', 'kind', 'content_hash')}))
                    source.active_version, source.status, source.error, source.updated_at = revision, 'ready', None, now()
            await asyncio.to_thread(publish)
        except BaseException:
            with Session(self.engine) as session, session.begin():
                session.execute(update(KnowledgeSource).where(KnowledgeSource.id == source_id,
                    KnowledgeSource.content_hash == snapshot['content_hash']).values(status='failed',
                    error='Indexing was interrupted or the embedding model is unavailable. Existing passages remain searchable; retry indexing.'))
            raise

    def recover(self):
        with Session(self.engine) as session, session.begin():
            session.execute(update(KnowledgeSource).where(KnowledgeSource.status == 'indexing').values(
                status='failed', error='Indexing was interrupted. Reindex this source.'))

    def _rank(self, query, vector):
        with Session(self.engine) as session:
            if self.engine.dialect.name == 'postgresql':
                base = ' FROM knowledge_chunks c JOIN knowledge_sources s ON s.id=c.source_id AND s.active_version=c.revision '
                keywords = list(session.execute(text('SELECT c.id' + base +
                    " WHERE to_tsvector('english', c.content) @@ websearch_to_tsquery('english', :q) "
                    " ORDER BY ts_rank_cd(to_tsvector('english', c.content), websearch_to_tsquery('english', :q)) DESC, c.id LIMIT 20"), {'q': query}).scalars())
                semantic = list(session.execute(text('SELECT c.id' + base +
                    ' WHERE c.embedding IS NOT NULL AND c.embedding_version=:version '
                    ' ORDER BY c.embedding OPERATOR(extensions.<=>) CAST(:v AS extensions.vector) ASC, c.id LIMIT 20'),
                    {'version': self.embedder.version, 'v': json.dumps(vector)}).scalars()) if vector else []
            else:
                rows = list(session.scalars(select(KnowledgeChunk).join(KnowledgeSource,
                    (KnowledgeSource.id == KnowledgeChunk.source_id) & (KnowledgeSource.active_version == KnowledgeChunk.revision))))
                words = set(re.findall(r'\w+', query.casefold()))
                lexical = [(row.id, len(words.intersection(re.findall(r'\w+', row.content.casefold())))) for row in rows]
                keywords = [key for key, score in sorted(lexical, key=lambda item: (-item[1], item[0])) if score][:20]
                def cosine(first, second):
                    den = math.sqrt(sum(x*x for x in first) * sum(x*x for x in second))
                    return sum(a*b for a,b in zip(first, second))/den if den else 0
                scored = [(row.id, cosine(vector, row.embedding)) for row in rows
                          if vector and row.embedding and row.embedding_version == self.embedder.version]
                semantic = [key for key,_ in sorted(scored, key=lambda item: (-item[1], item[0]))[:20]]
            scores = {}
            for ranked in (keywords, semantic):
                for rank, key in enumerate(ranked, 1): scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            ids = sorted(scores, key=lambda key: (-scores[key], key))[:5]
            rows = {row.id: row for row in session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids)))}
            result, remaining = [], 8000
            for key in ids:
                row = rows[key]
                value = row.content[:remaining]
                if not value: break
                remaining -= len(value)
                result.append({'passage_id': key, 'source_id': row.source_id, 'ref': row.ref,
                               'page': row.page, 'text': value, **row.evidence, 'rank_score': scores[key]})
            return result

    async def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ToolError('Search questions must contain 1–1,000 characters.')
        if not self.settings.semantic_search_enabled: raise ToolError('Semantic search is disabled.')
        warning, vector = None, None
        try:
            vector = checked_vectors([await self.embedder.query(query.strip())], 1)[0]
        except ToolError:
            warning = 'The local embedding model is unavailable. These are keyword-only matches.'
        matches = await asyncio.to_thread(self._rank, query.strip(), vector)
        return {'mode': 'hybrid' if vector else 'keyword', 'matches': matches, 'warning': warning,
                'notice': 'Saved passages are historical evidence. Check source dates and verify relevance; matches do not establish facts.'}
