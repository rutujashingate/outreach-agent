"""Extract visible text locally. This module never executes document instructions.

The service runs this parser in a separate, time-limited process. Tesseract
recognizes printed text in images; it does not interpret diagrams or photos.
"""
from html.parser import HTMLParser
from contextlib import closing
from io import BytesIO
from pathlib import Path
import math
import shutil
import subprocess
import tempfile
import warnings
import zipfile
from xml.etree import ElementTree

from PIL import Image, ImageOps
from app.domain.documents import (
    ExtractedDocument, DocumentPage, IMAGE_EXTENSIONS, TEXT_EXTENSIONS,
    MAX_FILE_BYTES, MAX_PAGES, MAX_TEXT_CHARS,
)

MAX_PIXELS = 16_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ExtractionError(ValueError):
    """A safe, owner-readable explanation; never include raw parser errors."""


def recognize_image(image, languages='eng'):
    if shutil.which('tesseract') is None:
        raise ExtractionError('OCR is unavailable. Install Tesseract to read images and scanned PDFs.')
    if image.width * image.height > MAX_PIXELS:
        raise ExtractionError('Image exceeds the 16-megapixel reading limit.')
    # Normalize orientation and transparency before OCR. No personal files or
    # remote URLs are passed to Tesseract; only this temporary image is read.
    oriented = ImageOps.exif_transpose(image).convert('RGBA')
    canvas = Image.new('RGBA', oriented.size, 'white')
    canvas.alpha_composite(oriented)
    with tempfile.TemporaryDirectory(prefix='outreach-ocr-') as directory:
        path = Path(directory) / 'page.png'
        canvas.convert('RGB').save(path)
        try:
            result = subprocess.run(['tesseract', str(path), 'stdout', '-l', languages, '--psm', '3'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
            return result.stdout.decode('utf-8').strip()
        except (subprocess.SubprocessError, OSError, UnicodeError):
            raise ExtractionError('OCR could not read this page. Check installed language data and image quality.') from None


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'head', 'template'}: self.hidden += 1
        if tag in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3'} and not self.hidden: self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'head', 'template'}: self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def decode_text(data):
    try:
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        text = data.decode(encoding)
    except UnicodeError:
        raise ExtractionError('Save text documents as UTF-8 or UTF-16 before uploading.') from None
    if '\x00' in text or sum(ord(c) < 32 and c not in '\n\r\t' for c in text) > len(text) * .01:
        raise ExtractionError('This file contains binary data rather than readable text.')
    return text


def office_text(data, suffix):
    """Read only the document's XML text; ignore macros, media and external links."""
    member = 'word/document.xml' if suffix == '.docx' else 'content.xml'
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(e.file_size for e in entries) > 40 * 1024 * 1024:
                raise ExtractionError('The expanded document exceeds the reading limit.')
            info = archive.getinfo(member)
            if info.file_size > MAX_FILE_BYTES or info.file_size > max(info.compress_size, 1) * 200:
                raise ExtractionError('The compressed document exceeds the reading limit.')
            xml = decode_text(archive.read(member))
            if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
                raise ExtractionError('Documents with XML entity declarations are unsupported.')
            root = ElementTree.fromstring(xml)
            if suffix == '.docx':
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                return '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p'))
            ns = '{urn:oasis:names:tc:opendocument:xmlns:text:1.0}'
            return '\n'.join(''.join(p.itertext()) for p in root.iter() if p.tag in {ns+'p', ns+'h'})
    except ExtractionError: raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, ValueError):
        raise ExtractionError('This Word/OpenDocument file is damaged or unsupported.') from None


def extract(data, suffix, languages='eng'):
    if not data or len(data) > MAX_FILE_BYTES:
        raise ExtractionError('Files must contain 1 byte to 10 MiB.')
    pages, notices, remaining = [], [], MAX_TEXT_CHARS

    def add(number, text, method='text'):
        nonlocal remaining
        text = text.replace('\r\n', '\n').strip()
        if len(text) > remaining and 'Text was shortened at 40,000 characters.' not in notices:
            notices.append('Text was shortened at 40,000 characters.')
        pages.append(DocumentPage(number=number, text=text[:remaining], method=method))
        remaining = max(0, remaining - len(text))

    try:
        if suffix == '.pdf':
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(data) as pdf:
                if len(pdf) > MAX_PAGES: raise ExtractionError('PDFs may contain at most 20 pages. Split the file first.')
                for index in range(len(pdf)):
                    with closing(pdf[index]) as page:
                        with closing(page.get_textpage()) as textpage:
                            text = textpage.get_text_bounded()
                        method = 'text'
                        if not text.strip():
                            width, height = page.get_size()
                            if width <= 0 or height <= 0: raise ExtractionError('Invalid PDF page dimensions.')
                            scale = min(2.5, math.sqrt(MAX_PIXELS / (width * height)))
                            bitmap = page.render(scale=scale)
                            try: text = recognize_image(bitmap.to_pil(), languages)
                            finally: bitmap.close()
                            method = 'ocr'
                        add(index+1, text, method)
                        if not remaining:
                            if index + 1 < len(pdf): notices.append('Later PDF pages were omitted after the text limit.')
                            break
        elif suffix in IMAGE_EXTENSIONS:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(data)) as image:
                    if image.format not in {'JPEG','PNG','WEBP','TIFF','BMP'}:
                        raise ExtractionError('Unsupported image encoding.')
                    frames = getattr(image, 'n_frames', 1)
                    if frames > MAX_PAGES: raise ExtractionError('Images may contain at most 20 frames/pages.')
                    for index in range(frames):
                        image.seek(index)
                        add(index+1, recognize_image(image, languages), 'ocr')
                        if not remaining:
                            if index + 1 < frames: notices.append('Later image frames were omitted after the text limit.')
                            break
        elif suffix in {'.docx', '.odt'}:
            add(1, office_text(data, suffix))
        elif suffix in TEXT_EXTENSIONS | {'.html', '.htm'}:
            text = decode_text(data)
            if suffix in {'.html', '.htm'}:
                parser = VisibleHTML(); parser.feed(text); text = ''.join(parser.parts)
            add(1, text)
        else:
            raise ExtractionError('Unsupported format. Use PDF, images, DOCX, ODT or a supported text document.')
    except ExtractionError: raise
    except Exception:
        raise ExtractionError('This file is encrypted, damaged, or cannot be read safely.') from None
    if not any(page.text.strip() for page in pages):
        raise ExtractionError('No readable text was found. Try a clearer scan or a text-based document.')
    return ExtractedDocument(pages=pages, warnings=notices)
