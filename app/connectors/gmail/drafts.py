"""Read and replace draft content while keeping its MIME attachments/headers."""
import base64
import hashlib
import html
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

from app.connectors.search import ToolError
from app.domain.workflow import Recipient
from app.agent.components.writer import validate_email_content


class DraftChanged(ToolError):
    """The owner edited, sent, or deleted a draft after its preview was made."""


def snapshot(payload):
    """Turn Gmail's raw response into a checked snapshot, without credentials."""
    try:
        raw = payload['message']['raw']
        if len(raw) > 3_000_000:
            raise ValueError
        content = base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4))
        message = BytesParser(policy=policy.default).parsebytes(content)
        part = message.get_body(preferencelist=('plain',))
        if part is None:
            raise ToolError('This draft has no plain-text body. Edit this HTML-only draft in Gmail.')
        addresses = {name: [Recipient(email=address).email for _, address in getaddresses(message.get_all(name, []))]
                     for name in ('to', 'cc', 'bcc')}
        if not addresses['to']:
            raise ValueError
        sender = [Recipient(email=address).email for _, address in getaddresses(message.get_all('from', []))]
        if len(sender) != 1:
            raise ValueError
        return {'draft_id': payload['id'], 'thread_id': payload['message'].get('threadId'),
            'raw': raw, 'baseline_hash': hashlib.sha256(content).hexdigest(),
            'sender': sender[0], **addresses, 'subject': str(message.get('subject', '')),
            'body': part.get_content(), 'attachment_count': sum(1 for _ in message.iter_attachments())}
    except ToolError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ToolError('That draft could not be safely read. Check its addresses and content in Gmail.') from None


def updated_raw(original, draft):
    """Change only subject/body; preserve recipients, reply headers, attachments."""
    validate_email_content(draft)
    if '\r' in draft.subject or '\n' in draft.subject:
        raise ValueError('Email subjects cannot contain line breaks.')
    message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(original['raw'] + '=' * (-len(original['raw']) % 4)))
    if message.get('subject') is None:
        message['Subject'] = draft.subject
    else:
        message.replace_header('Subject', draft.subject)
    part = message.get_body(preferencelist=('plain',))
    if part is None:
        raise ToolError('This draft has no editable plain-text body.')
    part.set_content(draft.body)
    alternative = message.get_body(preferencelist=('html',))
    if alternative is not None:
        # Prevent Gmail from showing an unchanged HTML alternative after the
        # plain-text body has been edited. Attachment parts stay untouched.
        alternative.set_content('<html><body><pre>' + html.escape(draft.body) + '</pre></body></html>', subtype='html')
    return base64.urlsafe_b64encode(message.as_bytes()).decode('ascii')
