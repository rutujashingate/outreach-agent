"""Run one local extraction outside the web server; stdout carries only JSON."""
import json
from pathlib import Path
import sys
from app.connectors.documents.extractor import extract, ExtractionError


def main():
    # Linux gets an additional memory/CPU ceiling. The parent enforces a wall
    # clock timeout and kills the entire process group, including active OCR.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    path, suffix, languages = sys.argv[1:]
    try:
        result = extract(Path(path).read_bytes(), suffix, languages)
        print(json.dumps({'content': result.model_dump()}, ensure_ascii=False))
    except ExtractionError as error:
        print(json.dumps({'error': str(error)}))


if __name__ == '__main__': main()
