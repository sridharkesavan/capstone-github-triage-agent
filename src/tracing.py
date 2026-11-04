"""Optional Langfuse tracing. If Langfuse is missing or failing, everything here is a no-op."""
try:
    from langfuse import get_client, observe
except Exception:  # not installed or broken: tracing off, agent unaffected
    get_client = None

    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


def update_generation(**kwargs):
    """Attach model, input, output and token usage to the current generation."""
    if get_client is None:
        return
    try:
        get_client().update_current_span(**kwargs)
    except Exception as e:
        print(f"[TRACE] update skipped: {e}")


def flush():
    """Send buffered traces. Call before a short-lived process exits."""
    if get_client is None:
        return
    try:
        get_client().flush()
    except Exception as e:
        print(f"[TRACE] flush skipped: {e}")
