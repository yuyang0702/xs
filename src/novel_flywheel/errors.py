def describe_error(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or f"{type(exc).__name__} (provider returned no error detail)"
