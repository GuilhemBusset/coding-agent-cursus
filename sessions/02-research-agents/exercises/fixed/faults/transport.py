"""Public synthetic Responses SSE, consumed by the real Pi adapter (no sockets)."""

import json
from typing import Any


def response(calls: list[dict[str, Any]] | None = None, text: str = 'continue',
             input_tokens: int = 10, output_tokens: int = 3, unknown: bool = False) -> dict[str, Any]:
    events: list[dict[str, Any]] = [dict(type='response.created', response=dict(id='resp_synthetic'))]
    items = []
    for index, args in enumerate(calls or []):
        item = dict(type='function_call', id=f'fc_{index}', call_id=f'call_{index}', name='read', arguments=json.dumps(args))
        items.append(item)
        events += [dict(type='response.output_item.added', output_index=index, item=dict(item, arguments='')),
                   dict(type='response.function_call_arguments.delta', output_index=index, delta=item['arguments']),
                   dict(type='response.function_call_arguments.done', output_index=index, arguments=item['arguments']),
                   dict(type='response.output_item.done', output_index=index, item=item)]
    if calls is None:
        item = dict(type='message', id='msg_synthetic', role='assistant', content=[dict(type='output_text', text=text, annotations=[])])
        items.append(item)
        events += [dict(type='response.output_item.added', output_index=0, item=dict(item, content=[])),
                   dict(type='response.output_text.delta', output_index=0, content_index=0, delta=text),
                   dict(type='response.output_item.done', output_index=0, item=item)]
    usage = None if unknown else dict(input_tokens=input_tokens, output_tokens=output_tokens,
        input_tokens_details=dict(cached_tokens=0, cache_write_tokens=0), output_tokens_details=dict(reasoning_tokens=0))
    events.append(dict(type='response.completed', response=dict(id='resp_synthetic', status='completed', output=items, usage=usage, error=None)))
    return dict(body=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))
