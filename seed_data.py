import os
import django
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fitnexis.settings')
django.setup()

from django.contrib.auth.models import User
from core.models import Profile, MembershipPlan, GymClass, Offer

def setup_data():
    # 1. Create Superuser
    if not User.objects.filter(username='admin').exists():
        admin = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        admin.profile.role = 'admin'
        admin.profile.save()
        print("Superuser 'admin' created (pass: admin123)")

    # 2. Create Trainer
    if not User.objects.filter(username='trainer1').exists():
        trainer = User.objects.create_user('trainer1', 'trainer@example.com', 'trainer123')
        trainer.profile.role = 'trainer'
        trainer.profile.save()
        print("Trainer 'trainer1' created (pass: trainer123)")

    # 3. Create Member
    if not User.objects.filter(username='member1').exists():
        member = User.objects.create_user('member1', 'member@example.com', 'member123')
        member.profile.role = 'member'
        member.profile.save()
        print("Member 'member1' created (pass: member123)")

    # 4. Create Membership Plans
    if not MembershipPlan.objects.exists():
        MembershipPlan.objects.create(title='Basic', description='Access to gym floor', price=29.99)
        MembershipPlan.objects.create(title='Pro', description='Gym + Classes', price=59.99)
        MembershipPlan.objects.create(title='Elite', description='Full access + Trainer', price=99.99)
        print("Membership plans created")

    # 5. Create Gym Classes
    if not GymClass.objects.exists():
        trainer = User.objects.get(username='trainer1')
        GymClass.objects.create(title='Weight Training', trainer=trainer, schedule_time=timezone.now() + timedelta(days=1), capacity=20)
        GymClass.objects.create(title='Yoga', trainer=trainer, schedule_time=timezone.now() + timedelta(days=2), capacity=15)
        print("Gym classes created")

if __name__ == "__main__":
    setup_data()
