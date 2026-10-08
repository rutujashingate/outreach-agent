"""Checked references and extracted evidence for owner-uploaded files."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MAX_TEXT_CHARS = 40000
MAX_ATTACHMENTS = 5
TEXT_EXTENSIONS = {'.txt', '.md', '.csv', '.json', '.log', '.rst', '.xml', '.yaml', '.yml', '.tex'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS | {'.pdf', '.docx', '.odt', '.html', '.htm'}


class Attachment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    purpose: Literal['research', 'background'] = 'research'


class DocumentPage(BaseModel):
    number: int = Field(ge=1, le=MAX_PAGES)
    text: str = Field(max_length=MAX_TEXT_CHARS)
    method: Literal['text', 'ocr'] = 'text'


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pages: list[DocumentPage] = Field(max_length=MAX_PAGES)
    warnings: list[str] = Field(default_factory=list)


class DocumentEvidence(ExtractedDocument):
    document_id: str
    filename: str
    purpose: Literal['research', 'background']
    sha256: str
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def source(self, page_number: int) -> str:
        return f'document:{self.document_id}#page={page_number}'
