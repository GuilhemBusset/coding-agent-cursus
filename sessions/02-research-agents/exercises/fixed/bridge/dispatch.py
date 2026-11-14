"""One bounded UTF-8 JSON request per process; launched by bridge.ts without a shell."""

import json
import sys
from pathlib import Path

from exercises.fixed.tools.corpus import ToolError, require
from exercises.fixed.tools.research import ResearchTools

MAX_REQUEST_BYTES = 16384
MAX_RESPONSE_BYTES = 131072


def dispatch(root: Path, request: dict) -> dict:
    require(isinstance(request, dict) and set(request) == {'tool', 'arguments', 'run_id', 'tool_call_id'}, 'invalid request envelope')
    return ResearchTools(root).invoke(request['tool'], request['arguments'], request['run_id'], request['tool_call_id'])


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        require(len(raw) <= MAX_REQUEST_BYTES, 'request exceeds size limit')
        response = dispatch(Path(sys.argv[1]), json.loads(raw.decode('utf-8')))
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode('utf-8')
        require(len(encoded) <= MAX_RESPONSE_BYTES, 'response exceeds size limit')
    except (ValueError, TypeError, KeyError, OSError, IndexError) as error:
        response = dict(bridge_error=dict(code=error.code if isinstance(error, ToolError) else 'invalid_input',
                                         retryable=False))
        encoded = json.dumps(response).encode('utf-8')
    sys.stdout.buffer.write(encoded + b'\n')


if __name__ == '__main__':
    main()
