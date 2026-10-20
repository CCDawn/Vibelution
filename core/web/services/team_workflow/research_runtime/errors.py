"""Shared runtime error contract, independent of execution services."""


class ResearchWorkflowError(Exception):
    def __init__(self, message: str, *, code: str = "workflow_error"):
        super().__init__(message)
        self.code = code
