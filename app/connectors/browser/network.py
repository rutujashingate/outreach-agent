"""An outbound proxy pins browser connections to validated public addresses.

Checking only a page's URL is insufficient: redirects and page subrequests
also use this proxy. DNS is resolved once per connection, and the selected IP
is used for the socket so a second DNS lookup cannot switch to a private host.
"""
import asyncio
from contextlib import asynccontextmanager
import ipaddress
import socket
from urllib.parse import urlsplit

from app.connectors.search import ToolError


def parse_public_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
            raise ValueError()
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        if port not in {80, 443} or len(url) > 2048 or any(c.isspace() for c in url): raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')): raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and (not address.is_global or address.is_multicast or address.is_reserved): raise ValueError()
        return host, port
    except (ValueError, UnicodeError): raise ToolError('Only public HTTP/HTTPS pages on standard ports are allowed.') from None


async def public_address(host, port):
    try:
        async with asyncio.timeout(5):
            answers = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [entry[4][0] for entry in answers]
        if not addresses or any(not ipaddress.ip_address(a).is_global or ipaddress.ip_address(a).is_multicast or ipaddress.ip_address(a).is_reserved for a in addresses): raise ValueError()
        return addresses[0]
    except (OSError, ValueError, TimeoutError): raise ToolError('The page address is unavailable or not public.') from None


class PublicProxy:
    def __init__(self):
        self.tasks = set()
        self.connections = asyncio.Semaphore(12)
        self.requests = 0

    async def handle(self, reader, writer):
        task = asyncio.current_task(); self.tasks.add(task)
        remote = None
        try:
            async with self.connections, asyncio.timeout(25):
                self.requests += 1
                if self.requests > 100: raise ToolError('Page resource limit exceeded.')
                raw = await reader.readuntil(b'\r\n\r\n')
                if len(raw) > 16384: raise ToolError('Request headers too large.')
                line = raw.split(b'\r\n', 1)[0].decode('ascii')
                method, target, protocol = line.split(' ')
                if method == 'CONNECT':
                    host, port = parse_public_url('https://' + target)
                elif method in {'GET', 'HEAD'}:
                    host, port = parse_public_url(target)
                else: raise ToolError('Browser requests must be read-only.')
                address = await public_address(host, port)
                incoming, remote = await asyncio.open_connection(address, port)
                if method == 'CONNECT':
                    writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n'); await writer.drain()
                else:
                    parts = urlsplit(target)
                    path = (parts.path or '/') + ('?' + parts.query if parts.query else '')
                    headers = [h for h in raw.split(b'\r\n')[1:] if h and h.split(b':',1)[0].lower() not in {b'proxy-connection', b'connection', b'host'}]
                    remote.write((f'{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n').encode() + b'\r\n'.join(headers) + b'\r\n\r\n')
                    await remote.drain()

                async def copy(source, destination, maximum):
                    size = 0
                    while data := await source.read(65536):
                        size += len(data)
                        if size > maximum: raise ToolError('Page transfer limit exceeded.')
                        destination.write(data); await destination.drain()
                tasks = [asyncio.create_task(copy(reader, remote, 1024 * 1024)),
                         asyncio.create_task(copy(incoming, writer, 5 * 1024 * 1024))]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for item in done: item.result()
                finally:
                    for item in tasks: item.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (Exception, asyncio.CancelledError):
            pass  # Never expose URLs or network exception text in service logs.
        finally:
            for stream in (remote, writer):
                if stream is not None: stream.close()
            self.tasks.discard(task)

    @asynccontextmanager
    async def open(self):
        server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=16384)
        try: yield f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        finally:
            server.close(); await server.wait_closed()
            tasks = list(self.tasks)
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
