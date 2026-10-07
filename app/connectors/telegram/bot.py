"""A persisted guided conversation; the shared service owns all outreach work."""
import asyncio
import secrets
import time

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.connectors.telegram.client import RateLimited
from app.domain.workflow import ApprovalDecision, WorkflowRequest, Recipient
from app.services.runs import ConfigurationError, RunConflict, RunNotFound
from app.connectors.search import ToolError
from app.storage.control import OutboxRow, now


class TelegramBot:
    def __init__(self, service, client):
        self.service, self.client = service, client
        self.store = service.store
        self.owner = service.manager.settings.telegram_owner_id
        self.stop = asyncio.Event()
        self.sequence, self.message_key = 0, ''

    def buttons(self, entries):
        row = []
        for title, value in entries:
            token = secrets.token_urlsafe(16)
            self.store.put('button:' + token, {**value, 'owner': self.owner, 'expires': time.time() + 86400})
            row.append({'text': title, 'callback_data': token})
        return {'inline_keyboard': [row[i:i+2] for i in range(0, len(row), 2)]}

    def say(self, text, entries=None):
        markup = self.buttons(entries) if entries else None
        # Leave headroom for part numbering and Unicode surrogate pairs.
        chunks, part = [], ''
        for char in text:
            if len((part + char).encode('utf-16-le')) // 2 > 3500:
                chunks.append(part); part = ''
            part += char
        chunks.append(part)
        self.sequence += 1
        group = f'{self.message_key}:{self.sequence}'
        for index, chunk in enumerate(chunks):
            payload = {'chat_id': self.owner, 'text': (f'[{index+1}/{len(chunks)}] ' if len(chunks)>1 else '') + chunk,
                       '_group': group}
            if index == len(chunks)-1 and markup: payload['reply_markup'] = markup
            self.store.notify(f'{group}:{index:04}', payload)

    def _action_prompt(self, conversation):
        conversation['stage'] = 'action'
        entries = [('Save in app', {'wizard': 'none', 'conversation': conversation['id']}), ('Gmail draft', {'wizard': 'draft', 'conversation': conversation['id']})]
        if self.service.manager.settings.sending_enabled: entries.append(('Send after approval', {'wizard': 'send', 'conversation': conversation['id']}))
        self.say('What should happen after you approve the message?', entries)

    def _review(self, run_id):
        response = self.service.state(run_id)
        state = response.state
        if response.awaiting_recipients:
            self.say(f'Run {run_id} needs recipient choices. Use /recipients {run_id} to choose addresses, or use the dashboard.')
            return
        if not response.awaiting_approval:
            self.say(f'Run {run_id}: {state.current_step}. No draft is waiting for approval.')
            return
        for item in state.approval_requests:
            choice = {'run_id': run_id, 'prospect_id': item.prospect.id, 'version': item.version, 'fingerprint': item.fingerprint}
            text = (f'Run {run_id}\n{item.prospect.company_name}\nFrom: {state.sender.name} <{state.sender.email or "not configured"}>\n'
                    f'To: {item.recipient.email}\nAddress source: {item.recipient.source}\n{item.recipient.evidence_quote}\n'
                    f'Action after approval: {state.gmail_action}\nVersion: {item.version}\n\n'
                    f'Subject: {item.draft.subject}\n\n{item.draft.body}\n\nEvidence:\n' + '\n'.join(item.research_summary))
            self.say(text, [(f'Approve {state.gmail_action}', {**choice, 'decision': 'approve'}),
                            ('Reject', {**choice, 'decision': 'reject'}), ('Edit', {**choice, 'decision': 'edit'})])
        self.say('Choose one decision for each draft, then submit the batch. Nothing is sent while choices are being collected.',
                 [('Submit decisions', {'submit': run_id}), ('Later', {'later': run_id})])

    def _next_recipient(self, conversation):
        state = self.service.state(conversation['run_id']).state
        remaining = [pid for pid in state.recipient_requests if pid not in conversation['selections']]
        if not remaining:
            job = self.service.select_recipients(state.run_id, conversation['selections'], f'tg:{self.message_key}:recipients')
            self.say(f'Recipient choices saved. Job {job["id"]} will continue the run.')
            conversation.clear(); return
        pid = remaining[0]
        conversation.update(stage='recipient', prospect_id=pid)
        prospect = next(p for p in state.qualified_prospects if p.id == pid)
        candidates = state.recipient_candidates.get(pid, [])
        self.say(f'Choose an address for {prospect.company_name}, type an email address, or skip this prospect.\n' +
                 '\n'.join(f'{r.email} — {r.source}' for r in candidates),
                 [(r.email, {'recipient': r.model_dump(), 'run_id': state.run_id, 'prospect_id': pid}) for r in candidates[:10]] +
                 [('Skip prospect', {'recipient': None, 'run_id': state.run_id, 'prospect_id': pid})])

    async def process_one(self):
        item = self.store.next_update()
        if item is None: return False
        self.sequence, self.message_key = 0, str(item['update_id'])
        conversation = dict(self.store.get('telegram_conversation', {}))
        try:
            callback = item.get('callback_query')
            if callback:
                try: await self.client.call('answerCallbackQuery', callback_query_id=callback['id'])
                except ToolError: pass
                value = self.store.get('button:' + callback.get('data', ''))
                if not value or value['owner'] != self.owner or value['expires'] < time.time():
                    raise RunConflict('This button expired. Request a new review.')
                if 'decision' in value:
                    decision = {k: value[k] for k in ('prospect_id', 'version', 'fingerprint')}
                    if value['decision'] == 'edit':
                        # Check freshness now and again when the edit is submitted.
                        state = self.service.state(value['run_id']).state
                        if not any(r.fingerprint == value['fingerprint'] and r.version == value['version'] for r in state.approval_requests):
                            raise RunConflict('This draft is no longer current.')
                        conversation = {'stage': 'edit_subject', 'run_id': value['run_id'], 'decision': decision}
                        self.say('Type the replacement subject.')
                    else:
                        self.service.stage_decision(value['run_id'], ApprovalDecision(**decision, action=value['decision']))
                        self.say('Choice saved. Submit decisions when every draft has a choice.')
                elif 'submit' in value:
                    job = self.service.submit_choices(value['submit'], f'tg:{item["update_id"]}:submit')
                    self.say(f'Decisions submitted. Job {job["id"]}.')
                elif 'later' in value: self.say('The run remains paused. Use /review when ready.')
                elif 'recipient' in value:
                    if conversation.get('stage') != 'recipient' or any(conversation.get(k) != value[k] for k in ('run_id','prospect_id')):
                        raise RunConflict('Request current recipient choices again.')
                    conversation['selections'][value['prospect_id']] = value['recipient']
                    self._next_recipient(conversation)
                elif 'wizard' in value:
                    if value.get('conversation') != conversation.get('id'):
                        raise RunConflict('This conversation has changed. Use its latest buttons.')
                    self._wizard(conversation, value['wizard'])
            else:
                text = item.get('message', {}).get('text', '').strip()
                if not text:
                    self.say('Please send text or use the buttons.')
                elif text.startswith('/'):
                    self._command(text, conversation)
                else:
                    self._text(text, conversation)
        except (ValueError, RunConflict, RunNotFound, ConfigurationError, ToolError) as error:
            # Only local validation/tool messages reach the owner, never raw
            # provider HTTP exceptions, credentials, or full validation inputs.
            message = str(error) if isinstance(error, (RunConflict, RunNotFound, ConfigurationError, ToolError)) else 'Invalid input. Check the requested format and try again.'
            self.say(message[:1000])
        except Exception:
            self.say('That request could not be processed. Check the dashboard and try again.')
        self.store.finish_update(item['update_id'], conversation)
        return True

    def _command(self, text, conversation):
        command, _, arg = text.partition(' ')
        command = command.split('@')[0].lower()
        if command in {'/start', '/help'}:
            self.say('Outreach agent\n/new — start a guided goal\n/runs — recent runs\n/review RUN_ID — review drafts\n/recipients RUN_ID — choose addresses\n/status RUN_ID — progress\n/retry RUN_ID — retry a failed run\n/cancel RUN_ID — stop a run\n/replies — check tracked replies\n/account — Gmail status\nUse the dashboard for logs and connector setup.')
        elif command == '/new':
            conversation.clear(); conversation.update(stage='goal', id=secrets.token_hex(8), request={})
            self.say('What is your outreach goal?')
        elif command == '/runs':
            self.say('\n\n'.join(f'{r["run_id"]}\n{r["goal"]}\n{r["status"]} · {r["current_step"]}' for r in self.service.list_runs(limit=10)['items']) or 'No runs yet. Use /new.')
        elif command == '/review': self._review(arg.strip())
        elif command == '/status':
            details = self.service.details(arg.strip()); self.say(f'{arg.strip()}: {details["current_step"]}')
        elif command == '/recipients':
            response = self.service.state(arg.strip())
            if not response.awaiting_recipients: raise RunConflict('This run is not waiting for addresses.')
            conversation.clear(); conversation.update(run_id=arg.strip(), selections={})
            self._next_recipient(conversation)
        elif command == '/retry':
            job = self.service.retry(arg.strip(), f'tg:{self.message_key}:retry'); self.say(f'Retry queued: {job["id"]}')
        elif command == '/cancel':
            if not arg: conversation.clear(); self.say('Conversation cancelled. Existing runs are unchanged; use /cancel RUN_ID to stop one.')
            else: self.service.cancel(arg.strip()); self.say('Cancellation requested. An action already in progress will record its result.')
        elif command == '/replies':
            job = self.service.queue_replies(f'tg:{self.message_key}:replies'); self.say(f'Reply check queued: {job["id"]}')
        elif command == '/account':
            gmail = self.service.manager.gmail
            status = gmail.status() if gmail and hasattr(gmail, 'status') else {}
            self.say(f'Gmail: {status.get("email") or "not connected"}\nStatus: {status.get("health", "not connected")}\nConnect or reconnect in the dashboard.')
        else: self.say('Unknown command. Use /help.')

    def _text(self, text, conversation):
        stage = conversation.get('stage')
        if not stage:
            conversation.update(stage='goal', id=secrets.token_hex(8), request={}); stage='goal'
        if stage == 'goal':
            if not 1 <= len(text) <= 2000: raise ValueError('Goal length')
            conversation['request']['goal'] = text; conversation['stage'] = 'background'
            self.say('Describe your background or offering. Send - to reuse your saved profile.')
        elif stage == 'background':
            profile = self.store.get('sender_profile', {'name': 'User', 'context': ''})
            if text != '-': profile['context'] = text; self.store.put('sender_profile', profile)
            gmail = self.service.manager.gmail
            status = gmail.status() if gmail and hasattr(gmail, 'status') else {}
            conversation['request']['sender'] = {**profile, 'email': status.get('email') or profile.get('email')}
            conversation['stage'] = 'source'
            self.say('Where should the research evidence come from?', self._wizard_buttons(conversation,
                [('Search + browser', 'search'), ('Public URLs', 'urls'), ('My notes', 'notes')]))
        elif stage == 'notes':
            conversation['request']['research_material'] = text; self._addresses_prompt(conversation)
        elif stage == 'urls':
            from app.connectors.browser.network import parse_public_url
            urls = text.split()
            if not 1 <= len(urls) <= 5: raise ValueError('URL limit')
            for url in urls: parse_public_url(url)
            conversation['request'].update(seed_urls=urls, use_browser=True); self._addresses_prompt(conversation)
        elif stage == 'addresses':
            recipients = {}
            if text != '-':
                for line in text.splitlines():
                    target, separator, address = line.partition('|')
                    if not separator or not target.strip(): raise ValueError('Address format')
                    recipients[target.strip()] = Recipient(email=address.strip()).model_dump()
            conversation['request'].update(recipients=recipients, discover_emails=True)
            self._action_prompt(conversation)
        elif stage == 'edit_subject':
            if '\n' in text or '\r' in text: raise ValueError('Subject')
            conversation['subject'], conversation['stage'] = text, 'edit_body'; self.say('Type the replacement body.')
        elif stage == 'edit_body':
            decision = ApprovalDecision(**conversation['decision'], action='edit', edited_draft={
                'prospect_id': conversation['decision']['prospect_id'], 'subject': conversation['subject'], 'body': text})
            self.service.stage_decision(conversation['run_id'], decision)
            self.say('Edit saved as your choice. Submit all decisions to review the new version.', [('Submit decisions', {'submit': conversation['run_id']})])
            conversation.clear()
        elif stage == 'recipient':
            conversation['selections'][conversation['prospect_id']] = Recipient(email=text).model_dump()
            self._next_recipient(conversation)
        else: self.say('Use the current buttons, or /new to begin again.')

    def _wizard_buttons(self, conversation, options):
        return [(title, {'wizard': value, 'conversation': conversation['id']}) for title, value in options]

    def _addresses_prompt(self, conversation):
        conversation['stage'] = 'addresses'
        self.say('If you know recipient addresses, enter one per line as Organization or person | email@example.com. Send - to use public addresses found during research or choose them later.')

    def _wizard(self, conversation, value):
        stage = conversation.get('stage')
        if stage == 'source' and value in {'search','urls','notes'}:
            if value == 'search':
                conversation['request'].update(use_search=True, use_browser=True); self._addresses_prompt(conversation)
            else: conversation['stage'] = value; self.say('Send up to five public URLs separated by spaces.' if value=='urls' else 'Paste your research notes with their source URLs.')
        elif stage == 'action' and value in {'none','draft','send'}:
            conversation['request']['gmail_action'] = value
            # Validate before asking the user to confirm, keeping errors editable.
            request = WorkflowRequest.model_validate(conversation['request'])
            self.service.manager.validate_request(request)
            conversation['stage'] = 'confirm'
            self.say(f'Goal: {request.goal}\nFrom: {request.sender.name} <{request.sender.email or "not configured"}>\nSearch: {request.use_search}\nBrowser: {request.use_browser}\nAfter approval: {request.gmail_action}\nStart this run?', self._wizard_buttons(conversation, [('Start run', 'confirm')]))
        elif stage == 'confirm' and value == 'confirm':
            job = self.service.start(WorkflowRequest.model_validate(conversation['request']), f'tg:{self.message_key}:start', 'telegram')
            self.say(f'Run queued: {job["run_id"]}. I will notify you when it needs a decision.'); conversation.clear()
        else: raise RunConflict('This conversation has advanced. Use the latest buttons.')

    async def deliver_one(self):
        with Session(self.store.engine) as session, session.begin():
            row = session.scalar(select(OutboxRow).where(OutboxRow.status == 'pending').order_by(OutboxRow.created_at, OutboxRow.key).limit(1))
            if row is None or row.retry_at > time.time(): return False
            key, payload = row.key, dict(row.payload)
            group = payload.pop('_group', None)
            if group:
                siblings = session.scalars(select(OutboxRow).where(OutboxRow.key != key))
                if any(s.payload.get('_group') == group and s.status in {'uncertain', 'blocked'} for s in siblings):
                    row.status = 'blocked'; return True
            row.status = 'sending'
        status, delay = 'done', 0
        try: await self.client.call('sendMessage', **payload)
        except RateLimited as error: status, delay = 'pending', error.delay
        except ToolError: status = 'uncertain'
        with Session(self.store.engine) as session, session.begin():
            session.execute(update(OutboxRow).where(OutboxRow.key == key).values(status=status, retry_at=time.time()+delay))
        if status == 'uncertain': self.store.put('telegram_status', {'health': 'delivery_uncertain', 'checked_at': now()})
        return True

    async def poll(self):
        try:
            webhook = await self.client.call('getWebhookInfo')
            if webhook.get('url'): raise ToolError('Remove the existing Telegram webhook before using long polling.')
            identity = await self.client.call('getMe')
            self.store.put('telegram_status', {'health': 'connected', 'username': identity.get('username'), 'checked_at': now()})
        except ToolError:
            self.store.put('telegram_status', {'health': 'configuration_error', 'checked_at': now()}); return
        while not self.stop.is_set():
            try:
                updates = await self.client.call('getUpdates', offset=self.store.get('telegram_offset', {}).get('next', 0),
                    timeout=25, allowed_updates=['message','callback_query'])
                self.store.accept_updates(updates, self.owner)
                self.store.put('telegram_status', {'health': 'connected', 'username': identity.get('username'), 'checked_at': now()})
            except ToolError as error:
                self.store.put('telegram_status', {'health': 'connection_error', 'checked_at': now()})
                try: await asyncio.wait_for(self.stop.wait(), timeout=error.delay if isinstance(error, RateLimited) else 5)
                except TimeoutError: pass

    async def handle(self):
        while not self.stop.is_set():
            processed = await self.process_one()
            delivered = await self.deliver_one()
            if not processed and not delivered:
                try: await asyncio.wait_for(self.stop.wait(), timeout=0.3)
                except TimeoutError: pass
