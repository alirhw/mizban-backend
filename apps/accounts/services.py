"""Account services: OTP generation/validation in Redis lands here
(TD-006: 5-digit codes, 120-second expiry, strict rate limiting).
Never store OTP codes in the database and never log them.
"""
