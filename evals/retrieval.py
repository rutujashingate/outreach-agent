"""Measure real local retrieval against keyword-only search; never call an LLM.

Use --cache-dir .data/models after model setup. Output distinguishes actual
embedding quality from the fake-vector tests used for application behavior.
"""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile

from app.llm.embeddings import LocalEmbeddings
from app.services.knowledge import KnowledgeService, capture_source
from app.settings import Settings
from app.storage.database import create_database
from app.storage.control import now


async def evaluate(cache_dir):
    cases = json.loads(Path(__file__).with_name('retrieval_cases.json').read_text())
    with tempfile.TemporaryDirectory(prefix='outreach-retrieval-eval-') as folder:
        engine = create_database('sqlite:///' + folder + '/eval.sqlite3')
        try:
            embedder = LocalEmbeddings(cache_dir)
            await embedder.prepare()
            service = KnowledgeService(engine, Settings(semantic_search_enabled=True), embedder)
            sources = {}
            for item in cases['sources']:
                sources[item['id']] = capture_source(engine, kind='document', ref='eval:' + item['id'],
                    label=item['id'], pages=[{'number': 1, 'text': item['text']}], retrieved_at=now())
                await service.index(sources[item['id']])
            results = []
            for item in cases['queries']:
                found = await service.search(item['query'])
                baseline = await asyncio.to_thread(service._rank, item['query'], None)
                expected = sources[item['expected']]
                def rank(matches):
                    return next((i for i, match in enumerate(matches,1) if match['source_id']==expected), None)
                results.append({'query':item['query'], 'expected':item['expected'],
                                'hybrid_rank':rank(found['matches']), 'keyword_rank':rank(baseline)})
            metrics = {}
            for mode in ('hybrid','keyword'):
                ranks = [row[mode+'_rank'] for row in results]
                metrics[mode] = {'recall_at_5':sum(rank is not None for rank in ranks)/len(ranks),
                                 'mean_reciprocal_rank':sum(1/rank if rank else 0 for rank in ranks)/len(ranks)}
            return {'model':embedder.status()['model'], 'corpus_sources':len(sources), 'queries':results,
                    'metrics':metrics, 'passed':metrics['hybrid']['recall_at_5']>=0.85,
                    'limitations':'Small English retrieval fixture. Does not measure generated answer quality or production relevance.'}
        finally: engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',type=Path,default=Path('.data/models'))
    parser.add_argument('--output',type=Path,default=None)
    args=parser.parse_args()
    report=asyncio.run(evaluate(args.cache_dir))
    if args.output: args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__': main()
