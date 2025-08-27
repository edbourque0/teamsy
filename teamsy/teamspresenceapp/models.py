from django.db import models
from django.utils import timezone

# Create your models here.

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantUser(TimeStampedModel):
    """
    Directory user resolved from Entra ID (Azure AD).
    We store Graph's user id (GUID) as a string to avoid UUID parsing pitfalls.
    """
    aad_user_id = models.CharField(max_length=64, unique=True, db_index=True)
    display_name = models.CharField(max_length=255, db_index=True)
    email = models.EmailField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.display_name} ({self.email or self.aad_user_id})"


class PresenceCurrent(TimeStampedModel):
    """
    One row per user representing the latest known presence.
    """
    AVAILABILITY_CHOICES = [
        ("Available", "Available"),
        ("AvailableIdle", "AvailableIdle"),
        ("Away", "Away"),
        ("BeRightBack", "BeRightBack"),
        ("Busy", "Busy"),
        ("BusyIdle", "BusyIdle"),
        ("DoNotDisturb", "DoNotDisturb"),
        ("Offline", "Offline"),
        ("PresenceUnknown", "PresenceUnknown"),
    ]

    ACTIVITY_CHOICES = [
        ("Available", "Available"),
        ("Away", "Away"),
        ("BeRightBack", "BeRightBack"),
        ("Busy", "Busy"),
        ("DoNotDisturb", "DoNotDisturb"),
        ("InACall", "In a call"),
        ("InAConferenceCall", "In a conference call"),
        ("InAMeeting", "In a meeting"),
        ("OffWork", "Off work"),
        ("Offline", "Offline"),
        ("OutOfOffice", "Out of office"),
        ("Presenting", "Presenting"),
        ("UrgentInterruptionsOnly", "Urgent interruptions only"),
        ("OnThePhone", "On the phone"),
        ("PresenceUnknown", "Presence unknown"),
    ]

    user = models.OneToOneField(
        TenantUser,
        on_delete=models.CASCADE,
        related_name="current_presence",
    )
    availability = models.CharField(max_length=32, choices=AVAILABILITY_CHOICES, db_index=True)
    activity = models.CharField(max_length=32, choices=ACTIVITY_CHOICES, db_index=True)
    # When we fetched this state from Graph (not just when we saved it)
    fetched_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["availability"]),
            models.Index(fields=["activity"]),
            models.Index(fields=["fetched_at"]),
        ]

    def __str__(self):
        return f"{self.user.display_name}: {self.availability}/{self.activity}"


class PresenceSnapshot(models.Model):
    """
    Append-only time series for analytics and history.
    """
    AVAILABILITY_CHOICES = PresenceCurrent.AVAILABILITY_CHOICES
    ACTIVITY_CHOICES = PresenceCurrent.ACTIVITY_CHOICES

    user = models.ForeignKey(
        TenantUser,
        on_delete=models.CASCADE,
        related_name="presence_snapshots",
    )
    availability = models.CharField(max_length=32, choices=AVAILABILITY_CHOICES)
    activity = models.CharField(max_length=32, choices=ACTIVITY_CHOICES)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["user", "fetched_at"]),
            models.Index(fields=["fetched_at"]),
            models.Index(fields=["availability"]),
            models.Index(fields=["activity"]),
        ]
        get_latest_by = "fetched_at"
        ordering = ["-fetched_at", "user_id"]

    def __str__(self):
        return f"{self.user.display_name} @ {self.fetched_at:%Y-%m-%d %H:%M} → {self.availability}/{self.activity}"