"""Queue normal messages, remember recent turns, and run read-only chat tools.

The conversational model can propose outreach, but only the shared outreach
service can start it. A proposal button never approves an email.
"""
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.conversation import ConversationContext, build_conversation_graph
from app.agent.context import ManagedModelClient, ManagedSearchTool
from app.connectors.browser.managed import ManagedBrowser
from app.connectors.browser.network import parse_public_url
from app.connectors.search import ToolError
from app.connectors.telegram.messages import queue_message
from app.domain.documents import Attachment
from app.domain.workflow import Sender, WorkflowRequest, WorkflowState
from app.llm.client import ModelProviderError
from app.services.cancellation import RunCancelled, check_cancelled
from app.services.limits import LimitExceeded
from app.services.runs import ConfigurationError, RunConflict, RunNotFound
from app.storage.control import JobRow, ValueRow
from app.storage.events import trace


class ConversationService:
    def __init__(self, service):
        self.service, self.manager, self.store = service, service.manager, service.store
        self.graph = build_conversation_graph()

    def queue(self, message, session_id, attachments, key):
        """Save a turn immediately; model calls belong to the background worker."""
        existing = self.store.find_job(key)
        if existing:
            return existing
        if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
            raise RunConflict('Please keep each message between 1 and 4,000 characters.')
        references = [Attachment.model_validate(item) for item in attachments]
        if len(references) > 5:
            raise RunConflict('Attach at most five files to this conversation.')
        for item in references:
            self.service.documents.get(item.document_id)
        state = WorkflowState(run_id=uuid4().hex, goal=message.strip()[:2000], attachments=references)
        job = self.store.enqueue('chat', state.run_id, {'message': message.strip(), 'session_id': session_id},
                                 key, state=state, origin='telegram', run_kind='chat')
        return job

    def retry_payload(self, run_id):
        with Session(self.store.engine) as session:
            row = session.scalar(select(JobRow).where(JobRow.run_id == run_id, JobRow.kind == 'chat')
                                 .order_by(JobRow.created_at).limit(1))
            if row is None:
                raise RunNotFound('Unknown conversation turn.')
            return row.payload

    async def execute(self, job):
        run_id, payload = job['run_id'], job['payload']
        state = self.service.state(run_id).state
        cached = self.store.get('chat:result:' + run_id)
        try:
            check_cancelled(self.manager.repository, run_id)
            if cached is None:
                self.manager.repository.save_run(state, 'running')
                trace(self.manager.repository, run_id, 'node_start', node='conversation')
                history = self.store.get('chat:history:' + payload['session_id'], {}).get('turns', [])
                files = [self.service.documents.get(item.document_id) for item in state.attachments]
                gmail = self.manager.gmail
                account = gmail.status() if gmail and hasattr(gmail, 'status') else {}
                inputs = {
                    'message': payload['message'],
                    'history': [{'user': turn['user'][:1500], 'assistant': turn['reply'][:2500]}
                                for turn in history[-6:]],
                    'previous_evidence': [item for turn in history[-2:] for item in turn.get('evidence', [])][-4:],
                    'attached_files': [{'document_id': f['id'], 'filename': f['filename'], 'status': f['status'],
                                        'purpose': reference.purpose} for f, reference in zip(files, state.attachments)],
                    'sender_profile': self.store.get('sender_profile', {'name': 'User', 'context': ''}),
                    'capabilities': {'search': self.manager.search is not None, 'browser': self.manager.browser is not None,
                                     'gmail_connected': bool(account.get('connected')),
                                     'sending_enabled': False,
                                     'max_drafts_per_run': self.manager.settings.limits.max_qualified},
                }
                limits = self.manager.settings.limits
                limits = limits.model_copy(update={'max_model_calls': min(limits.max_model_calls, limits.max_chat_model_calls),
                                                  'max_chat_model_calls': min(limits.max_model_calls, limits.max_chat_model_calls)})
                async with self.manager.client_factory() as client:
                    context = ConversationContext(self, run_id,
                        ManagedModelClient(client, self.manager.repository, run_id, limits),
                        ManagedSearchTool(self.manager.search, self.manager.repository, run_id, limits) if self.manager.search else None,
                        ManagedBrowser(self.manager.browser, self.manager.repository, run_id, limits) if self.manager.browser else None,
                        inputs, limits)
                    output = await self.graph.ainvoke({'observations': [], 'steps': 0, 'action': {}, 'result': {}},
                        context=context, config={'recursion_limit': 2 * limits.max_chat_model_calls + 4})
                cached = {**output['result'], 'session_id': payload['session_id']}
                # Save the answer before outbox delivery. An explicit retry after
                # a crash here reuses it, without a second model or Gmail call.
                self.store.put('chat:result:' + run_id, cached)
                trace(self.manager.repository, run_id, 'node_end', node='conversation')
            check_cancelled(self.manager.repository, run_id)
            self._remember(run_id, payload, cached)
            entries = []
            if cached.get('proposal'):
                entries.append(('Start outreach', {'chat_proposal': run_id, 'conversation': payload['session_id']}))
            if cached.get('review_run_id'):
                entries.append(('Review current drafts', {'review_run': cached['review_run_id']}))
            queue_message(self.store, self.manager.settings.telegram_owner_id, 'chat:' + run_id, cached['text'], entries)
            state.current_step = 'completed'
            self.manager.repository.save_run(state, 'completed')
        except RunCancelled:
            state.current_step = 'cancelled'
            self.manager.repository.save_run(state, 'cancelled')
            return 'cancelled'
        except BaseException as error:
            # Cancellation and crashes keep budgets and inputs for explicit retry.
            state.current_step = 'failed'
            message = (error.public_message if isinstance(error, ModelProviderError)
                       else 'Conversation interrupted or unavailable. Retry this turn.')
            self.manager.repository.save_run(state, 'failed', message)
            raise
        return 'completed'

    def _remember(self, run_id, payload, result):
        key = 'chat:history:' + payload['session_id']
        with Session(self.store.engine) as session, session.begin():
            row = session.get(ValueRow, key)
            turns = list(row.value.get('turns', [])) if row else []
            if not any(turn['run_id'] == run_id for turn in turns):
                turns.append({'run_id': run_id, 'user': payload['message'], 'reply': result['text'],
                              'evidence': result.get('evidence', [])[-2:]})
            session.merge(ValueRow(key=key, value={'turns': turns[-6:]}))

    def _page_depth(self, url, context, observations):
        """Allow supplied/search URLs and one level of same-site links."""
        messages = [context.inputs['message'], *(turn['user'] for turn in context.inputs['history'])]
        seeds = {value.rstrip('.,;:!?)\'\"]') for text in messages for value in re.findall(r'https?://[^\s<>]+', text)}
        evidence = [*context.inputs['previous_evidence'], *observations]
        seeds.update(source['ref'] for item in evidence if item['tool'] == 'search' for source in item['sources'])
        if url in seeds:
            return 0
        for item in evidence:
            if item['tool'] != 'read_page' or item.get('error'):
                continue
            if url in {source['ref'] for source in item['sources']}:
                return item.get('depth', 0)
            if item.get('depth', 0) == 0 and url in item.get('links', []):
                parent = item['sources'][0]['ref']
                if urlsplit(url).hostname == urlsplit(parent).hostname:
                    return 1
        raise ToolError('Supply a public URL, use a search result, or follow one level of same-site links.')

    async def read_tool(self, action, context, observations):
        """Dispatch a checked read operation; external content cannot add tools."""
        observation = {'tool': action.action, 'content': '', 'sources': []}
        try:
            if action.action == 'search':
                if context.search is None:
                    raise ToolError('Web search is not configured. Ask for a public URL or an uploaded file.')
                if not action.query.strip():
                    raise ToolError('A search query is required.')
                results = await context.search.search(action.query)
                observation['content'] = '\n\n'.join(f'{r.title}\n{r.url}\n{r.description[:1200]}' for r in results)[:12000]
                observation['sources'] = [{'ref': r.url, 'label': r.title} for r in results]
            elif action.action == 'read_page':
                if context.browser is None:
                    raise ToolError('The public browser is unavailable. Ask for a file or pasted text.')
                parse_public_url(action.url)
                depth = self._page_depth(action.url, context, observations)
                page = await context.browser.read(action.url)
                if page.error:
                    raise ToolError('That page could not be read. It may be blocked or unavailable.')
                observation['content'] = page.text[:12000]
                if len(page.text) > 12000:
                    observation['warnings'] = ['Only the first 12,000 extracted characters of this page are included.']
                observation['sources'] = [{'ref': page.url, 'label': page.title or page.url}]
                observation['retrieved_at'] = page.retrieved_at.isoformat()
                observation['depth'] = depth
                observation['links'] = page.links[:10]
            elif action.action == 'read_file':
                if action.document_id not in {item['document_id'] for item in context.inputs['attached_files']}:
                    raise ToolError('Choose a file attached to this conversation.')
                record = self.service.documents.get(action.document_id)
                if record['status'] != 'ready':
                    raise ToolError(f"File reading is {record['status']}. Use /files or retry a failed file before asking again.")
                sections, remaining = [], 12000
                observation['document_id'] = action.document_id
                observation['purpose'] = next(item['purpose'] for item in context.inputs['attached_files']
                                              if item['document_id'] == action.document_id)
                for page in record['content']['pages']:
                    if remaining <= 0:
                        break
                    ref = f"document:{record['id']}#page={page['number']}"
                    excerpt = page['text'][:remaining]
                    sections.append(f"{record['filename']} — page {page['number']}\n{ref}\n{excerpt}")
                    observation['sources'].append({'ref': ref, 'label': f"{record['filename']}, page {page['number']}"})
                    remaining -= len(excerpt)
                observation['content'] = '\n\n'.join(sections)
                observation['warnings'] = record['content'].get('warnings', [])
                if sum(len(p['text']) for p in record['content']['pages']) > 12000:
                    observation['warnings'] = [*observation['warnings'], 'Only the first 12,000 extracted characters are included.']
            elif action.action == 'run_status':
                run_id = action.run_id
                if not run_id:
                    recent = self.service.list_runs(limit=1)['items']
                    if not recent:
                        raise ToolError('There are no outreach runs yet.')
                    run_id = recent[0]['run_id']
                if (self.store.metadata(run_id) or {}).get('kind') != 'outreach':
                    raise ToolError('Choose an existing outreach run.')
                details = self.service.details(run_id)
                state = details['state']
                observation['content'] = json.dumps({'run_id': run_id, 'status': details['status'],
                    'current_step': details['current_step'], 'goal': state['goal'], 'drafts': state['drafts'],
                    'outcomes': state['outcomes'], 'awaiting_recipients': details['awaiting_recipients']}, ensure_ascii=False)[:12000]
                if details['awaiting_approval']:
                    observation['review_run_id'] = run_id
                if details['awaiting_recipients']:
                    observation['content'] += f'\nChoose missing addresses with /recipients {run_id}.'
            else:
                raise ToolError('That operation is not available in conversation.')
        except (ToolError, ValueError, RunNotFound, LimitExceeded):
            # These errors contain only locally chosen validation messages.
            # Provider bodies and arbitrary exception strings never reach chat.
            if action.action == 'search' and context.search is None:
                observation['error'] = 'Web search is not configured. Ask the owner for a public URL or file.'
            elif action.action == 'read_file':
                observation['error'] = 'The file is not attached or is not ready. Check /files and retry if needed.'
            else:
                observation['error'] = 'The read operation was unavailable, invalid, blocked, or reached its limit.'
        trace(self.manager.repository, context.run_id, 'conversation_tool', tool=action.action,
              succeeded='error' not in observation)
        return observation

    def response(self, action, observations, context):
        """Build an answer and, when requested, a concrete outreach proposal."""
        evidence = [*context.inputs['previous_evidence'], *observations]
        known_sources = {source['ref']: source['label'] for item in evidence for source in item.get('sources', [])}
        sources = [ref for ref in action.sources if ref in known_sources]
        if not sources:
            sources = list(dict.fromkeys(s['ref'] for item in observations for s in item.get('sources', [])))[:8]
        text = action.text.strip() or 'What would you like to explore? You can send a question, website URL, or file.'
        result = {'text': text, 'evidence': [{**item, 'content': item.get('content', '')[:4000]} for item in observations[-2:]]}
        if action.action == 'outreach':
            try:
                if action.request is None:
                    raise ValueError('Missing outreach request.')
                request = action.request
                profile = Sender.model_validate(context.inputs['sender_profile'])
                # Identity comes from the saved profile/connected account. The
                # model can carry user-supplied background into this request.
                sender = profile.model_copy(update={'context': request.sender.context or profile.context})
                attachments = self.service.state(context.run_id).state.attachments
                request = request.model_copy(update={'sender': sender, 'attachments': attachments, 'discover_emails': True})
                account = self.manager.gmail.status() if self.manager.gmail and hasattr(self.manager.gmail, 'status') else {}
                if account.get('connected'):
                    request = request.model_copy(update={'sender': sender.model_copy(update={'email': account['email']})})
                for url in request.seed_urls:
                    parse_public_url(url)
                if request.gmail_action != 'none' and not account.get('connected'):
                    raise RunConflict('Connect Gmail in the dashboard first, or ask to save the message in the app.')
                self.manager.validate_request(request)
                # Supply actual tool evidence, not model-written research claims.
                purposes = {item['document_id']: item['purpose'] for item in context.inputs['attached_files']}
                material = '\n\n'.join(json.dumps(item, ensure_ascii=False) for item in evidence if item.get('sources')
                    and not (item.get('tool') == 'read_file' and
                             purposes.get(item.get('document_id'), item.get('purpose')) == 'background'))
                request = request.model_copy(update={'research_material': material[:100000]})
                result['proposal'] = request.model_dump(mode='json')
                result['text'] = ('Ready to start this outreach request:\n' + request.goal +
                    '\n\nYour background: ' + (request.sender.context or 'Not supplied') +
                    '\nWeb search: ' + ('on' if request.use_search else 'off') +
                    '\nPublic browser: ' + ('on' if request.use_browser else 'off') +
                    '\nStarting URLs: ' + (', '.join(request.seed_urls) or 'none') +
                    '\nAttached files: ' + str(len(request.attachments)) +
                    '\nKnown recipients: ' + (', '.join(f'{name}: {item.email}' for name, item in request.recipients.items()) or 'resolve during research') +
                    '\nDraft destination: ' + {'none': 'save in app', 'draft': 'Gmail Drafts; you review and send manually'}[request.gmail_action] +
                    f'\nBatch limit: up to {self.manager.settings.limits.max_qualified} qualified prospects; fewer drafts if evidence, contact checks, or budget prevent completion.' +
                    '\n\nPress Start outreach to request these drafts, or tell me what to change. No email will be sent by the agent.')
            except (ValueError, RunConflict, ConfigurationError) as error:
                result['text'] = str(error) if isinstance(error, (RunConflict, ConfigurationError)) else 'Please clarify the outreach goal and which sources I should use.'
        else:
            for item in observations:
                if item.get('review_run_id'):
                    result['review_run_id'] = item['review_run_id']
            if sources:
                result['text'] += '\n\nSources:\n' + '\n'.join(f'{known_sources[ref]} — {ref}' for ref in sources)
            warnings = list(dict.fromkeys(warning for item in observations for warning in item.get('warnings', [])))
            if warnings:
                result['text'] += '\n\nReading limits: ' + ' '.join(warnings)
        return result

    def start_proposal(self, turn_id, session_id):
        result = self.store.get('chat:result:' + turn_id, {})
        if result.get('session_id') != session_id or not result.get('proposal'):
            raise RunConflict('This outreach proposal is no longer available. Ask for a new one.')
        if self.store.get('chat:latest:' + session_id, {}).get('run_id') != turn_id:
            raise RunConflict('This proposal predates your latest message. Ask me to prepare the updated request.')
        # A proposal may start once, even if Telegram delivers the click twice.
        return self.service.start(WorkflowRequest.model_validate(result['proposal']), 'chat:proposal:' + turn_id, 'telegram')
