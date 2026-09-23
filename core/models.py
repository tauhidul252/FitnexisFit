from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Profile(models.Model):
    ROLE_CHOICES = (
        ('member', 'Member'),
        ('trainer', 'Trainer'),
        ('admin', 'Admin'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    phone = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    bio = models.TextField(blank=True)
    specialty = models.CharField(max_length=100, blank=True, default='', help_text="Trainer specialty, e.g. Cardio Trainer, Bodybuilding Trainer")
    profile_pic = models.ImageField(upload_to='profiles/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.role}"

class MembershipPlan(models.Model):
    UNIT_CHOICES = (
        ('days', 'Days'),
        ('months', 'Months'),
        ('years', 'Years'),
    )
    title = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_months = models.IntegerField(default=1)
    duration_unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='months')
    has_trainer_access = models.BooleanField(default=False, help_text="If true, member can select any trainer and class")

    def __str__(self):
        return f"{self.title} ({self.duration_months} {self.duration_unit})"

class Subscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE)
    start_date = models.DateField(auto_now_add=True)
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan.title}"

    @property
    def is_valid(self):
        from django.utils import timezone
        return self.is_active and self.end_date >= timezone.now().date()

class Payment(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('approved', 'Approved'), # For offline payments
    )
    METHOD_CHOICES = (
        ('online', 'Online'),
        ('offline', 'Offline'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='online')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Offline payment fields
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    deposit_slip = models.ImageField(upload_to='slips/', blank=True, null=True)

    # Class booking linked to payment
    booked_class = models.ForeignKey('GymClass', on_delete=models.SET_NULL, null=True, blank=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount} ({self.status})"

class GymClass(models.Model):
    title = models.CharField(max_length=100)
    trainer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='classes_taught')
    schedule_time = models.DateTimeField()
    capacity = models.IntegerField(default=20)
    duration_minutes = models.IntegerField(default=60, help_text="Duration of the class in minutes")
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='classes/', blank=True, null=True)

    def __str__(self):
        return f"{self.title} by {self.trainer.username}"

class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    gym_class = models.ForeignKey(GymClass, on_delete=models.CASCADE)
    booking_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'gym_class')

    def __str__(self):
        return f"{self.user.username} booked {self.gym_class.title}"

class Attendance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.now)
    is_present = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user.username} - {self.date}"

class FitnessProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField(auto_now_add=True)
    weight = models.DecimalField(max_digits=5, decimal_places=2)
    body_fat_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    muscle_mass = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} progress on {self.date}"

class Offer(models.Model):
    title = models.CharField(max_length=100)
    discount_percentage = models.IntegerField()
    expiry_date = models.DateField()
    promo_code = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.title
