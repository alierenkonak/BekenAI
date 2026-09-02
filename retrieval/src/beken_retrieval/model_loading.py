import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager


class _SafeDownloadLog(logging.Filter):
    """Keep transport diagnostics, never raw requests or exception representations."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        status = re.match(r"HTTP Error ([1-5][0-9]{2}) thrown while requesting ", message)
        retry = re.fullmatch(r"Retrying in [0-9.]+s \[Retry [0-9]+/[0-9]+\]\.", message)
        if status:
            record.msg = f"Model download HTTP error {status.group(1)} (request details omitted)"
        elif retry:
            record.msg = message
        else:
            record.msg = "Model download transport event (sensitive request details omitted)"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


_SAFE_DOWNLOAD_LOG = _SafeDownloadLog()


@contextmanager
def safe_model_loading() -> Iterator[None]:
    """Do not expose provider headers/URLs in normal loader error tracebacks."""
    # The Hub logs raw HTTP errors and signed CDN URLs before it raises them.
    # Protect the emitting logger (not just root handlers); retain level and events.
    logging.getLogger("huggingface_hub.utils._http").addFilter(_SAFE_DOWNLOAD_LOG)
    try:
        yield
    except Exception:
        # Raw provider exceptions may contain Authorization headers or signed URLs.
        # Keep failures visible, without copying or chaining their sensitive details.
        raise RuntimeError("Pinned public model could not be loaded") from None
