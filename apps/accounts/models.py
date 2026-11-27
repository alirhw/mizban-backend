"""Custom user model for Miz Ban (TD-006, task T-005).

Identity is the mobile phone number - there is no password-based signup
for customers/venue owners; login is OTP via SMS (logic lands in
services.py in a later task). This model must exist BEFORE the first
migration of any dependent app, because every domain model points at it.
"""
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from core.utils import normalize_phone


class UserRole(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Customer"
    VENUE_OWNER = "VENUE_OWNER", "Venue owner"
    ADMIN = "ADMIN", "Admin"


class UserManager(BaseUserManager["User"]):
    """Creates users keyed by canonical phone number (single normalisation
    boundary - see core.utils.normalize_phone)."""

    def create_user(self, phone: str, password: str | None = None, **extra_fields):
        if not phone:
            raise ValueError("A phone number is required.")
        user = self.model(phone=normalize_phone(phone), **extra_fields)
        if password:
            user.set_password(password)
        else:
            # OTP-only accounts have no usable password.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self.create_user(phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(
        max_length=11,
        unique=True,
        db_index=True,
        help_text="Canonical Iranian mobile number, e.g. 09123456789.",
    )
    role = models.CharField(
        max_length=16,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.phone
