"""PHOS application-service boundary used by every remote adapter."""

from .application import ApplicationError, PhosApplicationService

__all__ = ("ApplicationError", "PhosApplicationService")
