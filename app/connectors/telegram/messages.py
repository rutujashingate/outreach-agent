"""Save Telegram replies in bounded parts, with controls on the last part."""
import secrets
import time


def queue_message(store, owner, key, text, entries=None):
    """Queue text/buttons without contacting Telegram; repeated keys are safe."""
    markup = None
    if entries:
        buttons = []
        for title, value in entries:
            token = secrets.token_urlsafe(16)
            store.put('button:' + token, {**value, 'owner': owner, 'expires': time.time() + 86400})
            buttons.append({'text': title, 'callback_data': token})
        markup = {'inline_keyboard': [buttons[i:i + 2] for i in range(0, len(buttons), 2)]}
    chunks, part = [], ''
    for char in text:
        # Telegram counts UTF-16 units, so emoji can occupy two units.
        if len((part + char).encode('utf-16-le')) // 2 > 3500:
            chunks.append(part)
            part = ''
        part += char
    chunks.append(part)
    for index, chunk in enumerate(chunks):
        payload = {'chat_id': owner, 'text':
                   (f'[{index + 1}/{len(chunks)}] ' if len(chunks) > 1 else '') + chunk,
                   '_group': key}
        if index == len(chunks) - 1 and markup:
            payload['reply_markup'] = markup
        store.notify(f'{key}:{index:04}', payload)
