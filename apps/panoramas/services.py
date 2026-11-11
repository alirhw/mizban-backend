"""Service layer for the panoramas app.

Upload handling only enqueues processing - heavy image work never runs
in the request/response cycle (ARCH-003); see tasks.py.
"""
