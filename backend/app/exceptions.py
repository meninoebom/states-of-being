"""Domain exceptions for the processing pipeline.

Kept in a dedicated module so both the endpoint (app.api.process) and the
upstream service wrappers (app.services.*) can import them without a circular
dependency through process.py.
"""

from __future__ import annotations


class UpstreamServiceError(Exception):
    """A paid upstream dependency (Replicate) timed out or errored.

    Distinct from UploadValidationError (the client's fault, a 4xx) and from an
    unexpected pipeline bug (our fault, a 500). The endpoint maps this to a 502:
    we accepted the request but the downstream audio service is unavailable.
    """
