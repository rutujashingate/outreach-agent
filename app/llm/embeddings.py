"""Local embeddings turn passages into vectors; they do not call Grok.

The setup command permits the first model download. Normal operation requires
the cached model, so a restart cannot silently download a different provider.
"""
import asyncio
from hashlib import sha256
import math
import re
import threading

from app.connectors.search import ToolError

MODEL = 'BAAI/bge-small-en-v1.5'
DIMENSION = 384
VERSION = MODEL + ':passage300-overlap50:v1'


def checked_vectors(vectors, count):
    result = [[float(number) for number in vector] for vector in vectors]
    if (len(result) != count or any(len(vector) != DIMENSION or
            not all(math.isfinite(number) for number in vector) or
            not any(vector) for vector in result)):
        raise ToolError('The embedding model returned invalid vectors.')
    return result


class LocalEmbeddings:
    version = VERSION

    def __init__(self, directory):
        self.directory = directory
        self.model = None
        self.lock = threading.Lock()
        self.error = None

    def _load(self, download=False):
        if self.model is None:
            from fastembed import TextEmbedding
            self.model = TextEmbedding(model_name=MODEL, cache_dir=str(self.directory),
                                       local_files_only=not download, threads=2)
        return self.model

    async def prepare(self, download=False):
        def load():
            with self.lock:
                return self._load(download)
        try:
            await asyncio.to_thread(load)
            self.error = None
        except Exception:
            self.error = 'Local embedding model unavailable. Run python -m app.setup_storage --download-model.'
            raise ToolError(self.error) from None

    async def passages(self, texts):
        def embed():
            with self.lock:
                return checked_vectors(list(self._load().passage_embed(texts, batch_size=16)), len(texts))
        try:
            return await asyncio.to_thread(embed)
        except Exception:
            self.error = 'Local embedding model unavailable. Run the model setup or use keyword search.'
            raise ToolError(self.error) from None

    async def query(self, text):
        def embed():
            with self.lock:
                return checked_vectors(list(self._load().query_embed([text])), 1)[0]
        try:
            return await asyncio.to_thread(embed)
        except Exception:
            self.error = 'Local embedding model unavailable. Using keyword search.'
            raise ToolError(self.error) from None

    async def chunks(self, text):
        """Use actual model-token offsets; never cross a supplied page boundary."""
        def split():
            with self.lock:
                model = self._load()
                tokenizer = model.model.tokenizer
                # Tokenizer truncation would otherwise hide all text after 512
                # tokens. Restore its settings before producing embeddings.
                previous = tokenizer.truncation
                tokenizer.no_truncation()
                try:
                    offsets = tokenizer.encode(text, add_special_tokens=False).offsets
                finally:
                    if previous:
                        tokenizer.enable_truncation(**previous)
                return [text[offsets[i][0]:offsets[min(i+300, len(offsets))-1][1]]
                        for i in range(0, len(offsets), 250) if offsets[i][0] < offsets[min(i+300, len(offsets))-1][1]]
        try:
            return await asyncio.to_thread(split)
        except Exception:
            raise ToolError('The embedding tokenizer is unavailable. Run model setup and reindex.') from None

    def status(self):
        return {'model': MODEL, 'dimension': DIMENSION, 'local': True,
                'loaded': self.model is not None, 'error': self.error}


class FakeEmbeddings:
    """Deterministic test vectors. These test plumbing, not retrieval quality."""
    version = VERSION

    async def passages(self, texts):
        result = []
        for text in texts:
            vector = [0.0] * DIMENSION
            for word in re.findall(r'\w+', text.casefold()):
                vector[int(sha256(word.encode()).hexdigest()[:8], 16) % DIMENSION] += 1
            if not any(vector): vector[0] = 1
            result.append(vector)
        return result

    async def query(self, text):
        return (await self.passages([text]))[0]

    async def chunks(self, text):
        words = list(re.finditer(r'\S+', text))
        return [text[words[i].start():words[min(i+300, len(words))-1].end()]
                for i in range(0, len(words), 250)]

    async def prepare(self, download=False): pass

    def status(self):
        return {'model': 'fake', 'dimension': DIMENSION, 'local': True, 'loaded': True, 'error': None}
