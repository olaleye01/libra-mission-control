"""Shared HTTP errors. No application module starts a listener."""


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message
        super().__init__(message)
