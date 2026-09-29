import datetime
import json

from velum.security.redact import redact


def event(level, message, **fields):
    return redact(json.dumps({'time': datetime.datetime.now(datetime.UTC).isoformat(),
                              'level': level, 'message': message, **fields}, ensure_ascii=True))
