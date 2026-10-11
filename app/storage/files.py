"""Original-file storage. The server owns every object path and credential.

Uploads use a content-derived path. An uncertain upload is inspected before
retrying, so a lost HTTP response does not create a second copy.
"""
import asyncio
from hashlib import sha256
from pathlib import Path
import os
import re
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx

from app.connectors.search import ToolError
from app.domain.documents import MAX_FILE_BYTES

BUCKET = 'outreach-documents'


def checked_key(key):
    if not re.fullmatch(r'(?:originals/|validation/)?[a-f0-9]{32}', key):
        raise ToolError('Invalid stored file identifier.')
    return key


class LocalFiles:
    backend = 'local'

    def __init__(self, directory):
        self.directory = Path(directory)

    async def put(self, key, data):
        checked_key(key)
        def write():
            target = self.directory / key
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = target.with_name(uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as file:
                    os.chmod(temporary, 0o600)
                    file.write(data)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        await asyncio.to_thread(write)

    async def get(self, key):
        checked_key(key)
        def read():
            with (self.directory / key).open('rb') as file:
                data = file.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES: raise ToolError('The stored original exceeds the file-size limit.')
            return data
        try:
            return await asyncio.to_thread(read)
        except OSError:
            raise ToolError('The stored original is unavailable. Restore it or upload the file again.') from None

    async def delete(self, key):
        checked_key(key)
        await asyncio.to_thread((self.directory / key).unlink, missing_ok=True)


class SupabaseFiles:
    backend = 'supabase'

    def __init__(self, settings, http=None):
        self.url = settings.supabase_url.rstrip('/') + '/storage/v1'
        self.secret = settings.supabase_secret_key
        self.http = http

    @asynccontextmanager
    async def client(self):
        if self.http is not None:
            yield self.http
        else:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
                yield http

    async def request(self, method, path, **kwargs):
        # New Supabase secret keys belong in apikey, not a JWT bearer header.
        headers = {'apikey': self.secret, **kwargs.pop('headers', {})}
        try:
            if self.http is not None:
                return await self.http.request(method, self.url + path, headers=headers,
                                               follow_redirects=False, timeout=30, **kwargs)
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
                return await http.request(method, self.url + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ToolError('Supabase file storage could not be reached. Check the connection and retry.') from None

    async def ensure_bucket(self):
        response = await self.request('GET', '/bucket/' + BUCKET)
        missing = response.status_code == 404
        if response.status_code == 400:
            try: missing = response.json().get('message', '').casefold() == 'bucket not found'
            except ValueError: pass
        if missing:
            response = await self.request('POST', '/bucket', json={
                'id': BUCKET, 'name': BUCKET, 'public': False, 'file_size_limit': MAX_FILE_BYTES})
            if response.is_success:
                response = await self.request('GET', '/bucket/' + BUCKET)
        if not response.is_success:
            raise ToolError('Cannot inspect or create the private bucket. Check the Supabase server key.')
        bucket = response.json()
        if bucket.get('public') is not False:
            raise ToolError('The document bucket must be private. Change its visibility before using it.')
        if int(bucket.get('file_size_limit') or 0) != MAX_FILE_BYTES:
            changed = await self.request('PUT', '/bucket/' + BUCKET, json={'public': False, 'file_size_limit': MAX_FILE_BYTES})
            if not changed.is_success:
                raise ToolError('Cannot set the document bucket file-size limit.')

    async def get(self, key):
        checked_key(key)
        # Stream and bound downloads even when an object was changed externally.
        try:
            async with self.client() as http:
                async with http.stream('GET', self.url + '/object/authenticated/' + BUCKET + '/' + key,
                                       headers={'apikey': self.secret}, follow_redirects=False, timeout=30) as response:
                    if not response.is_success:
                        raise ToolError('The stored original is unavailable. Check Supabase storage.')
                    data = bytearray()
                    async for part in response.aiter_bytes():
                        data.extend(part)
                        if len(data) > MAX_FILE_BYTES:
                            raise ToolError('The stored original exceeds the file-size limit.')
                    return bytes(data)
        except httpx.HTTPError:
            raise ToolError('Supabase file storage could not be reached.') from None

    async def put(self, key, data):
        checked_key(key)
        if not 0 < len(data) <= MAX_FILE_BYTES:
            raise ToolError('Files must contain 1 byte to 10 MiB.')
        try:
            response = await self.request('POST', '/object/' + BUCKET + '/' + key,
                content=data, headers={'Content-Type': 'application/octet-stream', 'x-upsert': 'false'})
            if response.is_success:
                return
        except ToolError:
            pass
        # Includes duplicate-object responses and upload timeouts. Reading the
        # exact object also repairs a crash between the upload and SQL commit.
        stored = await self.get(key)
        if sha256(stored).digest() != sha256(data).digest():
            raise ToolError('The stored original does not match this upload. Inspection is required.')

    async def delete(self, key):
        checked_key(key)
        response = await self.request('DELETE', '/object/' + BUCKET, json={'prefixes': [key]})
        if not response.is_success:
            raise ToolError('Supabase could not remove the temporary validation file.')

    async def anonymous_denied(self, key):
        async with self.client() as http:
            response = await http.get(self.url + '/object/public/' + BUCKET + '/' + checked_key(key),
                                      follow_redirects=False, timeout=15)
        return response.status_code in {400, 401, 403, 404}


class FakeFiles:
    """A cloud-like object store shared across service restarts in tests."""
    backend = 'supabase'

    def __init__(self):
        self.objects = {}
        self.writes = 0

    async def put(self, key, data):
        checked_key(key)
        if key in self.objects and self.objects[key] != data:
            raise ToolError('Stored original checksum mismatch.')
        if key not in self.objects:
            self.writes += 1
        self.objects[key] = data

    async def get(self, key):
        if checked_key(key) not in self.objects:
            raise ToolError('Stored original unavailable.')
        return self.objects[key]

    async def delete(self, key):
        self.objects.pop(checked_key(key), None)

    async def anonymous_denied(self, key):
        return True
