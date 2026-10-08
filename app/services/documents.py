"""Save uploads, queue extraction, and expose owner-readable source evidence."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.documents import MAX_FILE_BYTES, SUPPORTED_EXTENSIONS, ExtractedDocument
from app.storage.documents import DocumentRow, document_record
from app.storage.control import ControlStore, JobRow, now
from app.connectors.search import ToolError
from app.services.runs import RunConflict, RunNotFound


class DocumentService:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        self.store = ControlStore(engine)
        self.directory = settings.data_dir / 'uploads'

    def status(self):
        return {'available': True, 'ocr_available': shutil.which('tesseract') is not None,
                'ocr_languages': self.settings.ocr_languages,
                'extensions': sorted(SUPPORTED_EXTENSIONS), 'max_bytes': MAX_FILE_BYTES,
                'max_files_per_run': 5, 'max_pages': 20}

    def get(self, document_id):
        record = document_record(self.engine, document_id)
        if record is None: raise RunNotFound('Unknown document.')
        return record

    def list(self, page=1):
        with Session(self.engine) as session:
            ids = session.scalars(select(DocumentRow.id).order_by(DocumentRow.created_at.desc(), DocumentRow.id)
                                  .offset((page-1)*20).limit(20))
            records = [document_record(self.engine, item) for item in ids]
        return {'page': page, 'items': [{k:v for k,v in r.items() if k != 'content'} for r in records]}

    def save(self, filename, data):
        filename = Path(filename.replace('\\', '/')).name
        filename = ''.join(c for c in filename if c.isprintable()).strip()
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ToolError('Unsupported format. Use PDF, PNG/JPEG/WebP/TIFF/BMP, DOCX/ODT, or a text document.')
        if not data or len(data) > MAX_FILE_BYTES:
            raise ToolError('Each file must contain 1 byte to 10 MiB.')
        checksum = hashlib.sha256(data).hexdigest()
        document_id = hashlib.sha256(suffix.encode() + b'\0' + data).hexdigest()[:32]
        existing = document_record(self.engine, document_id)
        if existing is None:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = self.directory / document_id
            temporary = self.directory / (uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as file:
                    os.chmod(temporary, 0o600)
                    file.write(data)
                temporary.replace(target)
                with Session(self.engine) as session, session.begin():
                    session.add(DocumentRow(id=document_id, filename=filename[:180], suffix=suffix,
                                            sha256=checksum, size=len(data)))
            finally:
                temporary.unlink(missing_ok=True)
        # Content-based identity makes repeated Telegram updates/uploads reuse
        # extraction. This also repairs a crash between saving and enqueueing.
        job = self.store.enqueue('document', None, {'document_id': document_id}, 'document:' + document_id)
        return {'document': self.get(document_id), 'job': job}

    def retry(self, document_id, key):
        existing = self.store.find_job(key)
        if existing: return {'document': self.get(document_id), 'job': existing}
        record = self.get(document_id)
        if record['status'] != 'failed': raise RunConflict('Only failed or interrupted documents can be retried.')
        job = self.store.enqueue('document', None, {'document_id': document_id}, key)
        with Session(self.engine) as session, session.begin():
            session.execute(update(DocumentRow).where(DocumentRow.id == document_id).values(status='queued', error=None))
        return {'document': self.get(document_id), 'job': job}

    def recover(self):
        with Session(self.engine) as session, session.begin():
            active = {payload['document_id'] for payload in session.scalars(select(JobRow.payload).where(
                JobRow.kind == 'document', JobRow.status.in_(['queued', 'running'])))}
            for row in session.scalars(select(DocumentRow).where(DocumentRow.status == 'queued')):
                if row.id not in active:
                    row.status, row.error = 'failed', 'Extraction was interrupted. Retry this document.'
            session.execute(update(DocumentRow).where(DocumentRow.status == 'processing').values(
                status='failed', error='Extraction was interrupted. Retry this document.'))

    async def extract(self, document_id):
        record = self.get(document_id)
        if record['status'] == 'ready': return record
        with Session(self.engine) as session, session.begin():
            session.execute(update(DocumentRow).where(DocumentRow.id == document_id).values(status='processing', error=None))
        process = None
        try:
            # Do not give parser/OCR processes the application's provider keys.
            env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT', 'TMPDIR', 'TESSDATA_PREFIX') if key in os.environ}
            process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.connectors.documents.worker',
                str((self.directory / document_id).resolve()), record['suffix'], self.settings.ocr_languages,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                env=env, start_new_session=True)
            async with asyncio.timeout(90):
                output = bytearray()
                while chunk := await process.stdout.read(65536):
                    output.extend(chunk)
                    if len(output) > 512 * 1024: raise ToolError('Extracted document exceeded the reading limit.')
                await process.wait()
            if process.returncode: raise ToolError('Document reader stopped. The file may be damaged or exceed reading limits.')
            result = json.loads(output)
            if result.get('error'): raise ToolError(result['error'])
            content = ExtractedDocument.model_validate(result['content'])
            with Session(self.engine) as session, session.begin():
                session.execute(update(DocumentRow).where(DocumentRow.id == document_id).values(
                    status='ready', content=content.model_dump(), extracted_at=now(), error=None))
            return self.get(document_id)
        except (Exception, asyncio.CancelledError) as error:
            if process is not None and process.returncode is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                await process.wait()
            message = str(error) if isinstance(error, ToolError) else 'Document reading was interrupted or exceeded its 90-second limit. Retry a smaller file.'
            with Session(self.engine) as session, session.begin():
                session.execute(update(DocumentRow).where(DocumentRow.id == document_id).values(status='failed', error=message))
            if isinstance(error, asyncio.CancelledError): raise
            raise ToolError(message) from None
