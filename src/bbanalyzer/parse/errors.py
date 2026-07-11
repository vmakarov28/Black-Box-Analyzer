class LogParseError(Exception):
    """Raised when a file is not a readable Betaflight blackbox log at all
    (no header found, decoder binary missing, etc). Per-flight corruption
    inside an otherwise valid multi-flight file is NOT an error -- it is
    reported as a skipped/warned flight on LogFile instead, so one bad
    segment never prevents reading the rest of the file.
    """
