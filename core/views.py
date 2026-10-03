from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import models
from .models import Subscription, MembershipPlan, GymClass, Booking, Attendance, FitnessProgress, Payment, Offer
import uuid
from decimal import Decimal, InvalidOperation
import json
import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

# Public landing page: keep the first few records lightweight so the home page
# can show a useful preview without loading every class and trainer.
def home(request):
    classes = GymClass.objects.all()[:3]
    trainers = User.objects.filter(profile__role='trainer')[:3]
    schedule = GymClass.objects.all().order_by('schedule_time')[:5]
    
    context = {
        'classes': classes,
        'trainers': trainers,
        'schedule': schedule,
    }
    return render(request, 'home.html', context)

from django.contrib.auth import login, authenticate, logout
from .forms import SignupForm
from django.contrib import messages

def login_view(request):
    """Authenticate a user and send them to the role-aware dashboard."""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('home')

def signup_view(request):
    """Create a member account through the shared signup form."""
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = SignupForm()
    return render(request, 'signup.html', {'form': form})

def forgot_password_view(request):
    return render(request, 'forgot_password.html')

@login_required
def dashboard(request):
    """Route authenticated users to the dashboard for their profile role."""
    role = request.user.profile.role
    if role == 'admin':
        return redirect('admin_dashboard')
    elif role == 'trainer':
        return redirect('trainer_dashboard')
    else:
        return redirect('member_dashboard')

from django.utils import timezone
from datetime import timedelta

@login_required
def member_dashboard(request):
    """Build the member dashboard from progress, bookings, attendance, and plan data."""
    user = request.user
    progress = FitnessProgress.objects.filter(user=user).order_by('-date')[:5]

    # Keep one ordered queryset so the upcoming/past lists use the same source
    # and the template can display a consistent booking history.
    bookings = Booking.objects.filter(user=user).order_by('gym_class__schedule_time').select_related('gym_class', 'gym_class__trainer')

    # Split in Python because the two lists are also used to find the next class.
    now = timezone.now()
    upcoming_bookings = [b for b in bookings if b.gym_class.schedule_time >= now]
    past_bookings = [b for b in bookings if b.gym_class.schedule_time < now]

    # The dashboard treats 20 attended sessions in 30 days as the 100% target.
    last_30_days = timezone.now().date() - timedelta(days=30)
    attendance_count = Attendance.objects.filter(user=user, date__gte=last_30_days, is_present=True).count()
    attendance_pct = min(int((attendance_count / 20) * 100), 100)

    # A plan is usable only when it is marked active and its end date has passed.
    active_sub = Subscription.objects.filter(
        user=user,
        is_active=True,
        end_date__gte=timezone.now().date()
    ).first()

    # Fall back to the latest past booking when no future class exists, allowing
    # the dashboard to still show the member's most recent session.
    next_booking = upcoming_bookings[0] if upcoming_bookings else (past_bookings[-1] if past_bookings else None)

    # Exclude already-booked classes to prevent duplicate choices in the UI.
    booked_class_ids = bookings.values_list('gym_class__id', flat=True)
    available_classes = GymClass.objects.exclude(id__in=booked_class_ids).order_by('schedule_time')[:6]

    context = {
        'progress': progress,
        'bookings': bookings,
        'upcoming_bookings': upcoming_bookings,
        'past_bookings': past_bookings,
        'attendance_pct': attendance_pct,
        'active_sub': active_sub,
        'next_booking': next_booking,
        'available_classes': available_classes,
        'now': now,
    }
    return render(request, 'dashboard_member.html', context)

@login_required
def book_class(request, class_id):
    """Book a class only for members with an active plan and open capacity."""
    # Subscription validity is checked before reading or changing the booking.
    from django.utils import timezone
    active_sub = Subscription.objects.filter(
        user=request.user, 
        is_active=True, 
        end_date__gte=timezone.now().date()
    ).first()
    
    if not active_sub:
        messages.error(request, "Your membership has expired or you don't have an active plan. Please renew to book classes.")
        return redirect('membership_plans')

    gym_class = GymClass.objects.get(id=class_id)
    # Count current bookings before creating one so a full class cannot be extended.
    current_bookings = Booking.objects.filter(gym_class=gym_class).count()
    if current_bookings < gym_class.capacity:
        Booking.objects.get_or_create(user=request.user, gym_class=gym_class)
        messages.success(request, f"Successfully booked {gym_class.title}!")
    else:
        messages.error(request, "This class is full.")
    return redirect('member_dashboard')

def _parse_metric(raw, field, low, high, required=False):
    """Parse an optional decimal form value; return (value, error_message)."""
    raw = (raw or '').strip()
    if not raw:
        return (None, f"{field} is required.") if required else (None, None)
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, f"{field} must be a number."
    if not value.is_finite() or not (low < value <= high):
        return None, f"{field} must be between {low} and {high}."
    return value.quantize(Decimal('0.01')), None


@login_required
def update_progress(request):
    """Record a progress entry (weight required; body fat % and muscle mass optional)."""
    if request.method == 'POST':
        weight, err_w = _parse_metric(request.POST.get('weight'), "Weight", 0, 500, required=True)
        body_fat, err_f = _parse_metric(request.POST.get('body_fat_percentage'), "Body fat %", 0, 100)
        muscle, err_m = _parse_metric(request.POST.get('muscle_mass'), "Muscle mass", 0, 500)
        errors = [e for e in (err_w, err_f, err_m) if e]
        if errors:
            for e in errors:
                messages.error(request, e)
        else:
            FitnessProgress.objects.create(
                user=request.user, weight=weight, body_fat_percentage=body_fat,
                muscle_mass=muscle, notes=(request.POST.get('notes') or '').strip(),
            )
            messages.success(request, "Progress updated!")
    return redirect(reverse('member_dashboard') + '#progress')


PROGRESS_RANGES = {'30': 30, '90': 90, '180': 180, '365': 365}


@login_required
def progress_data(request):
    """JSON feed for the progress charts. ?range=30|90|180|365|all (default all)."""
    entries = FitnessProgress.objects.filter(user=request.user)
    range_key = request.GET.get('range', 'all')
    if range_key in PROGRESS_RANGES:
        since = timezone.now().date() - timedelta(days=PROGRESS_RANGES[range_key])
        entries = entries.filter(date__gte=since)
    else:
        range_key = 'all'
    entries = list(entries.order_by('date', 'id'))

    def num(v):
        return float(v) if v is not None else None

    def summarize(values):
        # Only entries that actually recorded this metric count toward it.
        vals = [v for v in values if v is not None]
        if not vals:
            return None
        return {
            'first': vals[0], 'latest': vals[-1],
            'change': round(vals[-1] - vals[0], 2),
            'min': min(vals), 'max': max(vals),
        }

    weight = [num(e.weight) for e in entries]
    body_fat = [num(e.body_fat_percentage) for e in entries]
    muscle = [num(e.muscle_mass) for e in entries]
    return JsonResponse({
        'range': range_key,
        'count': len(entries),
        'labels': [e.date.isoformat() for e in entries],
        # None becomes null so Chart.js leaves a gap instead of plotting 0.
        'weight': weight,
        'body_fat': body_fat,
        'muscle_mass': muscle,
        'notes': [e.notes for e in entries],
        'summary': {
            'weight': summarize(weight),
            'body_fat': summarize(body_fat),
            'muscle_mass': summarize(muscle),
        },
    })

@login_required
def cancel_booking(request, booking_id):
    if request.method == 'POST':
        try:
            booking = Booking.objects.get(id=booking_id, user=request.user)
            title = booking.gym_class.title
            booking.delete()
            messages.success(request, f"Successfully cancelled your booking for {title}.")
        except Booking.DoesNotExist:
            messages.error(request, "Booking not found.")
    return redirect('member_dashboard')

@login_required
def trainer_dashboard(request):
    """Prepare the trainer's profile, classes, assigned members, and daily schedule."""
    user = request.user
    if request.user.profile.role != 'trainer':
        return redirect('dashboard')
        
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.save()
        
        profile = user.profile
        profile.phone = request.POST.get('phone', profile.phone)
        profile.bio = request.POST.get('bio', profile.bio)
        profile.save()
        messages.success(request, "Your profile has been successfully updated!")
        return redirect('trainer_dashboard')

    classes = GymClass.objects.filter(trainer=user).order_by('schedule_time')
    
    # distinct() prevents a member who booked several classes appearing repeatedly.
    assigned_member_ids = Booking.objects.filter(gym_class__trainer=user).values_list('user_id', flat=True).distinct()
    assigned_members = User.objects.filter(id__in=assigned_member_ids).select_related('profile')
    assigned_members_count = assigned_members.count()
    
    # Limit the feed so the trainer dashboard stays focused on recent updates.
    member_progress = FitnessProgress.objects.filter(user__in=assigned_member_ids).order_by('-date')[:15]
    
    # The ordered class queryset makes the first future record the next session.
    next_session = classes.filter(schedule_time__gte=timezone.now()).first()
    
    # These records power the trainer's attendance workflow for the current day.
    today = timezone.now().date()
    todays_classes = classes.filter(schedule_time__date=today)
    todays_bookings = Booking.objects.filter(gym_class__in=todays_classes)
    
    context = {
        'classes': classes,
        'assigned_members_count': assigned_members_count,
        'assigned_members': assigned_members,
        'member_progress': member_progress,
        'next_session': next_session,
        'todays_bookings': todays_bookings,
    }
    return render(request, 'dashboard_trainer.html', context)

@login_required
def mark_attendance(request, booking_id):
    """Record today's attendance once for the member linked to a booking."""
    if request.user.profile.role != 'trainer':
        messages.error(request, "Only trainers can mark attendance.")
        return redirect('dashboard')
        
    booking = Booking.objects.get(id=booking_id)
    Attendance.objects.get_or_create(
        user=booking.user,
        date=timezone.now().date(),
        is_present=True
    )
    messages.success(request, f"Attendance marked for {booking.user.username}")
    return redirect('trainer_dashboard')

@login_required
def add_class(request):
    from .models import GymClass
    if request.user.profile.role != 'trainer':
        messages.error(request, "Only trainers can add classes.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        schedule_time = request.POST.get('schedule_time')
        capacity = request.POST.get('capacity', 20)
        duration_minutes = request.POST.get('duration_minutes', 60)
        image = request.FILES.get('image')
        
        GymClass.objects.create(
            title=title,
            description=description,
            schedule_time=schedule_time,
            capacity=capacity,
            duration_minutes=duration_minutes,
            trainer=request.user,
            image=image
        )
        messages.success(request, f"Class '{title}' created successfully!")
    return redirect('trainer_dashboard')


# ─── Admin: assign a new class to a specific trainer ───────────────────────────
@login_required
def assign_class_to_trainer(request, trainer_id):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    trainer = User.objects.get(id=trainer_id)

    if request.method == 'POST':
        title         = request.POST.get('title', '').strip()
        description   = request.POST.get('description', '')
        schedule_time = request.POST.get('schedule_time')
        capacity      = request.POST.get('capacity', 20)
        image         = request.FILES.get('image')

        if not title or not schedule_time:
            messages.error(request, "Title and schedule time are required.")
            return redirect('manage_trainers')

        GymClass.objects.create(
            title=title,
            description=description,
            schedule_time=schedule_time,
            capacity=capacity,
            trainer=trainer,
            image=image
        )
        messages.success(request, f"Class '{title}' assigned to {trainer.username}!")

    return redirect('manage_trainers')


# ─── Admin: remove (delete) a class from a trainer ─────────────────────────────
@login_required
def remove_class_from_trainer(request, class_id):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    gym_class = GymClass.objects.get(id=class_id)
    title = gym_class.title
    gym_class.delete()
    messages.success(request, f"Class '{title}' removed.")
    return redirect('manage_trainers')



@login_required
def admin_dashboard(request):
    """Collect the summary metrics displayed on the administrator dashboard."""
    from django.db.models import Sum
    plans = MembershipPlan.objects.all()
    payments = Payment.objects.all().order_by('-timestamp')[:10]
    offers = Offer.objects.all()
    
    # Aggregate returns None when there are no payments, so use zero for the UI.
    total_revenue = Payment.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    
    # Count users rather than subscriptions because one user may have multiple records.
    active_members_count = Subscription.objects.filter(is_active=True).values('user').distinct().count()
    
    # This metric intentionally covers the current calendar day in server time.
    recent_payments_count = Payment.objects.filter(timestamp__date=timezone.now().date()).count()
    
    context = {
        'plans': plans,
        'payments': payments,
        'offers': offers,
        'total_revenue': total_revenue,
        'active_members_count': active_members_count,
        'recent_payments_count': recent_payments_count,
    }
    return render(request, 'dashboard_admin.html', context)

@login_required
def add_plan(request):
    from .models import MembershipPlan
    if request.user.profile.role != 'admin':
        messages.error(request, "Only admins can add plans.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        price = request.POST.get('price')
        duration_months = request.POST.get('duration_months', 1)
        duration_unit = request.POST.get('duration_unit', 'months')
        has_trainer_access = request.POST.get('has_trainer_access') == 'on'

        MembershipPlan.objects.create(
            title=title,
            description=description,
            price=price,
            duration_months=duration_months,
            duration_unit=duration_unit,
            has_trainer_access=has_trainer_access
        )
        messages.success(request, f"Plan '{title}' created successfully!")
    return redirect('manage_plans')

@login_required
def edit_plan(request, plan_id):
    from .models import MembershipPlan
    if request.user.profile.role != 'admin':
        messages.error(request, "Only admins can edit plans.")
        return redirect('dashboard')
        
    plan = MembershipPlan.objects.get(id=plan_id)
    if request.method == 'POST':
        plan.title = request.POST.get('title')
        plan.description = request.POST.get('description')
        plan.price = request.POST.get('price')
        plan.duration_months = request.POST.get('duration_months')
        plan.duration_unit = request.POST.get('duration_unit', 'months')
        plan.has_trainer_access = request.POST.get('has_trainer_access') == 'on'
        plan.save()
        messages.success(request, f"Plan '{plan.title}' updated successfully!")
    return redirect('manage_plans')

@login_required
def delete_plan(request, plan_id):
    from .models import MembershipPlan
    if request.user.profile.role != 'admin':
        messages.error(request, "Only admins can delete plans.")
        return redirect('dashboard')
        
    plan = MembershipPlan.objects.get(id=plan_id)
    title = plan.title
    plan.delete()
    messages.success(request, f"Plan '{title}' deleted successfully!")
    return redirect('manage_plans')


# ─────────────────────────────────────────────
#  PAYMENTS PAGE
# ─────────────────────────────────────────────

@login_required
def manage_payments(request):
    """List payment records with optional username search and summary statistics."""
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from django.db.models import Sum, Count

    payments = Payment.objects.select_related('user').order_by('-timestamp')

    # Apply the search to the queryset before rendering so filtering stays in SQL.
    search = request.GET.get('q', '').strip()
    if search:
        payments = payments.filter(user__username__icontains=search)

    # Stats
    total_revenue   = Payment.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    today_revenue   = Payment.objects.filter(timestamp__date=timezone.now().date()).aggregate(Sum('amount'))['amount__sum'] or 0
    total_txns      = Payment.objects.count()
    today_txns      = Payment.objects.filter(timestamp__date=timezone.now().date()).count()

    context = {
        'payments'      : payments,
        'total_revenue' : total_revenue,
        'today_revenue' : today_revenue,
        'total_txns'    : total_txns,
        'today_txns'    : today_txns,
        'search'        : search,
    }
    return render(request, 'manage_payments.html', context)


@login_required
def delete_payment(request, payment_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    pay = Payment.objects.get(id=payment_id)
    pay.delete()
    messages.success(request, "Payment record deleted.")
    return redirect('manage_payments')


# ─────────────────────────────────────────────
#  MEMBERSHIP PLANS PAGE
# ─────────────────────────────────────────────

@login_required
def manage_plans(request):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from django.db.models import Count
    plans = MembershipPlan.objects.annotate(
        subscriber_count=Count('subscription', distinct=True)
    )

    trainers = User.objects.filter(profile__role='trainer')

    context = {
        'plans'      : plans,
        'total_plans': plans.count(),
        'total_subs' : Subscription.objects.filter(is_active=True).count(),
        'trainers'   : trainers,
    }
    return render(request, 'manage_plans.html', context)


# ─────────────────────────────────────────────
#  OFFERS & DISCOUNTS PAGE
# ─────────────────────────────────────────────

@login_required
def manage_offers(request):
    """Prepare offers with an explicit expired flag for the admin template."""
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    offers = Offer.objects.all().order_by('expiry_date')
    today  = timezone.now().date()

    # Keep the expiry decision in one place instead of duplicating date logic in
    # the template for every offer row.
    offer_data = []
    for o in offers:
        offer_data.append({
            'offer'  : o,
            'expired': o.expiry_date < today,
        })

    context = {
        'offer_data'   : offer_data,
        'total_offers' : offers.count(),
        'active_offers': sum(1 for od in offer_data if not od['expired']),
        'today'        : today,
    }
    return render(request, 'manage_offers.html', context)


@login_required
def add_offer(request):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    if request.method == 'POST':
        title      = request.POST.get('title')
        discount   = request.POST.get('discount_percentage')
        expiry     = request.POST.get('expiry_date')
        promo_code = request.POST.get('promo_code', '').upper().strip()

        if Offer.objects.filter(promo_code=promo_code).exists():
            messages.error(request, f"Promo code '{promo_code}' already exists.")
        else:
            Offer.objects.create(
                title=title,
                discount_percentage=discount,
                expiry_date=expiry,
                promo_code=promo_code,
            )
            messages.success(request, f"Offer '{title}' created!")
    return redirect('manage_offers')


@login_required
def edit_offer(request, offer_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    offer = Offer.objects.get(id=offer_id)
    if request.method == 'POST':
        offer.title               = request.POST.get('title', offer.title)
        offer.discount_percentage = request.POST.get('discount_percentage', offer.discount_percentage)
        offer.expiry_date         = request.POST.get('expiry_date', offer.expiry_date)
        offer.promo_code          = request.POST.get('promo_code', offer.promo_code).upper().strip()
        offer.save()
        messages.success(request, f"Offer '{offer.title}' updated!")
    return redirect('manage_offers')


@login_required
def delete_offer(request, offer_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    offer = Offer.objects.get(id=offer_id)
    title = offer.title
    offer.delete()
    messages.success(request, f"Offer '{title}' deleted.")
    return redirect('manage_offers')


# ─────────────────────────────────────────────
#  REPORTS PAGE
# ─────────────────────────────────────────────

@login_required
def manage_reports(request):
    """Build the reporting data used by the admin charts and summary cards."""
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from django.db.models import Sum, Count
    from datetime import timedelta

    today     = timezone.now().date()
    last_30   = today - timedelta(days=30)
    last_7    = today - timedelta(days=7)

    # Revenue stats use the payment timestamp, while membership and class stats
    # use their respective model dates below.
    total_revenue   = Payment.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    revenue_30d     = Payment.objects.filter(timestamp__date__gte=last_30).aggregate(Sum('amount'))['amount__sum'] or 0
    revenue_7d      = Payment.objects.filter(timestamp__date__gte=last_7).aggregate(Sum('amount'))['amount__sum'] or 0

    # Member stats
    total_members   = User.objects.filter(profile__role='member').count()
    active_subs     = Subscription.objects.filter(is_active=True).count()
    new_members_30d = User.objects.filter(profile__role='member', date_joined__date__gte=last_30).count()

    # Class stats
    total_classes   = GymClass.objects.count()
    total_bookings  = Booking.objects.count()
    bookings_7d     = Booking.objects.filter(booking_date__date__gte=last_7).count()

    # Database annotation lets the database rank classes without loading every
    # booking into Python.
    top_classes = GymClass.objects.annotate(bc=Count('booking')).order_by('-bc')[:5]

    # Plan distribution
    plan_dist = MembershipPlan.objects.annotate(
        sub_count=Count('subscription', filter=__import__('django.db.models', fromlist=['Q']).Q(subscription__is_active=True))
    )

    # Produce chart-ready labels and totals for the six displayed calendar months.
    monthly_labels  = []
    monthly_revenue = []
    for i in range(5, -1, -1):
        from datetime import date
        import calendar
        target = today.replace(day=1) - timedelta(days=i * 28)
        month_start = target.replace(day=1)
        last_day    = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end   = month_start.replace(day=last_day)
        rev = Payment.objects.filter(
            timestamp__date__gte=month_start,
            timestamp__date__lte=month_end,
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        monthly_labels.append(month_start.strftime('%b %Y'))
        monthly_revenue.append(float(rev))

    # Include zero-attendance days so the chart always has seven points.
    att_labels  = []
    att_counts  = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        count = Attendance.objects.filter(date=d, is_present=True).count()
        att_labels.append(d.strftime('%a'))
        att_counts.append(count)

    context = {
        'total_revenue'  : total_revenue,
        'revenue_30d'    : revenue_30d,
        'revenue_7d'     : revenue_7d,
        'total_members'  : total_members,
        'active_subs'    : active_subs,
        'new_members_30d': new_members_30d,
        'total_classes'  : total_classes,
        'total_bookings' : total_bookings,
        'bookings_7d'    : bookings_7d,
        'top_classes'    : top_classes,
        'plan_dist'      : plan_dist,
        'monthly_labels' : monthly_labels,
        'monthly_revenue': monthly_revenue,
        'att_labels'     : att_labels,
        'att_counts'     : att_counts,
    }
    return render(request, 'manage_reports.html', context)


# ─────────────────────────────────────────────
#  CLASS SCHEDULE / MANAGE CLASSES
# ─────────────────────────────────────────────

@login_required
def manage_classes(request):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    classes = GymClass.objects.select_related('trainer').order_by('schedule_time')

    # Filter by search
    search = request.GET.get('q', '').strip()
    if search:
        classes = classes.filter(
            models.Q(title__icontains=search) | 
            models.Q(trainer__username__icontains=search)
        )

    # Trainers for the "Add Class" modal
    trainers = User.objects.filter(profile__role='trainer')
    
    context = {
        'classes': classes,
        'total_classes': classes.count(),
        'trainers': trainers,
        'search': search,
    }
    return render(request, 'manage_classes.html', context)


@login_required
def edit_class(request, class_id):
    # Admins may edit any class; trainers are restricted to classes they own.
    gym_class = GymClass.objects.get(id=class_id)
    is_admin = request.user.profile.role == 'admin'
    is_owner_trainer = request.user.profile.role == 'trainer' and gym_class.trainer == request.user
    if not (is_admin or is_owner_trainer):
        return redirect('dashboard')

    if request.method == 'POST':
        gym_class.title = request.POST.get('title', gym_class.title)
        gym_class.description = request.POST.get('description', gym_class.description)
        gym_class.duration_minutes = request.POST.get('duration_minutes', gym_class.duration_minutes)
        # Preserve the existing image when the edit form has no new upload.
        image = request.FILES.get('image')
        if image:
            gym_class.image = image
        # Trainer reassignment is an admin-only operation.
        trainer_id = request.POST.get('trainer')
        if trainer_id and is_admin:
            gym_class.trainer = User.objects.get(id=trainer_id)
        gym_class.schedule_time = request.POST.get('schedule_time', gym_class.schedule_time)
        gym_class.capacity = request.POST.get('capacity', gym_class.capacity)
        gym_class.save()
        messages.success(request, f"Class '{gym_class.title}' updated successfully!")

    # Redirect trainers back to their dashboard, admins to manage page
    return redirect('trainer_dashboard' if is_owner_trainer and not is_admin else 'manage_classes')


@login_required
def delete_class(request, class_id):
    # Allow admins to delete any class, and trainers to delete their own classes
    gym_class = GymClass.objects.get(id=class_id)
    is_admin = request.user.profile.role == 'admin'
    is_owner_trainer = request.user.profile.role == 'trainer' and gym_class.trainer == request.user
    if not (is_admin or is_owner_trainer):
        return redirect('dashboard')

    title = gym_class.title
    gym_class.delete()
    messages.success(request, f"Class '{title}' has been removed from schedule.")
    return redirect('trainer_dashboard' if is_owner_trainer and not is_admin else 'manage_classes')


def class_detail(request, class_id):
    gym_class = GymClass.objects.get(id=class_id)
    booking_count = gym_class.booking_set.count()
    context = {
        'gym_class': gym_class,
        'booking_count': booking_count,
        'spots_left': gym_class.capacity - booking_count,
    }
    return render(request, 'class_detail.html', context)


def error_404(request, exception):
    return render(request, '404.html', status=404)



# ─────────────────────────────────────────────
#  MANAGE MEMBERS
# ─────────────────────────────────────────────

@login_required
def manage_members(request):
    """Prepare member records and simple engagement signals for administrators."""
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    from django.db.models import Count
    members = User.objects.filter(profile__role='member').select_related('profile').prefetch_related(
        'subscription_set__plan', 'attendance_set', 'booking_set'
    )

    # Build one view-model per member so the template receives both raw records
    # and the engagement signal used to highlight members needing attention.
    member_data = []
    for m in members:
        att_count = m.attendance_set.filter(is_present=True).count()
        bookings   = m.booking_set.count()
        active_sub = m.subscription_set.filter(is_active=True).first()

        # These transparent rules are intentionally deterministic and explainable;
        # they are guidance for staff, not a replacement for a clinical assessment.
        if att_count == 0:
            insight = "⚠️ No attendance recorded. Consider a re-engagement email."
            risk    = "high"
        elif att_count < 5:
            insight = "📉 Low attendance. Recommend a personal trainer check-in."
            risk    = "medium"
        elif bookings == 0:
            insight = "📅 Active but not booking classes. Suggest group sessions."
            risk    = "low"
        else:
            insight = "✅ Engaged member. Great retention candidate."
            risk    = "good"

        member_data.append({
            'user'       : m,
            'att_count'  : att_count,
            'bookings'   : bookings,
            'active_sub' : active_sub,
            'insight'    : insight,
            'risk'       : risk,
        })

    plans = MembershipPlan.objects.all()
    context = {
        'member_data': member_data,
        'plans'      : plans,
        'total_members': len(member_data),
        'at_risk'    : sum(1 for m in member_data if m['risk'] == 'high'),
    }
    return render(request, 'manage_members.html', context)


@login_required
def add_member(request):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    if request.method == 'POST':
        username  = request.POST.get('username')
        email     = request.POST.get('email')
        password  = request.POST.get('password')
        phone     = request.POST.get('phone', '')
        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            user.profile.role  = 'member'
            user.profile.phone = phone
            user.profile.save()
            messages.success(request, f"Member '{username}' added successfully!")
    return redirect('manage_members')


@login_required
def edit_member(request, member_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    member = User.objects.get(id=member_id)
    if request.method == 'POST':
        member.email            = request.POST.get('email', member.email)
        member.first_name       = request.POST.get('first_name', member.first_name)
        member.last_name        = request.POST.get('last_name', member.last_name)
        member.profile.phone    = request.POST.get('phone', member.profile.phone)
        member.profile.address  = request.POST.get('address', member.profile.address)
        member.save()
        member.profile.save()
        messages.success(request, f"Member '{member.username}' updated.")
    return redirect('manage_members')


@login_required
def delete_member(request, member_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    user = User.objects.get(id=member_id)
    uname = user.username
    user.delete()
    messages.success(request, f"Member '{uname}' deleted.")
    return redirect('manage_members')


# ─────────────────────────────────────────────
#  MANAGE TRAINERS
# ─────────────────────────────────────────────

@login_required
def manage_trainers(request):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')

    trainers = User.objects.filter(profile__role='trainer').select_related('profile')

    trainer_data = []
    for t in trainers:
        classes      = GymClass.objects.filter(trainer=t)
        classes_count = classes.count()
        members_count = Booking.objects.filter(gym_class__trainer=t).values('user').distinct().count()
        total_bookings = Booking.objects.filter(gym_class__trainer=t).count()

        # Use transparent booking-based rules to give admins a quick trainer
        # performance signal without hiding how the recommendation was formed.
        if classes_count == 0:
            insight     = "⚠️ No classes assigned. Assign classes to activate trainer."
            performance = "inactive"
        elif members_count == 0:
            insight     = "📭 Classes created but no bookings yet. Promote to members."
            performance = "low"
        elif total_bookings < 5:
            insight     = "📈 Growing presence. Encourage marketing of their sessions."
            performance = "medium"
        elif members_count >= 10:
            insight     = "🌟 Top performer! High member engagement and retention."
            performance = "top"
        else:
            insight     = "✅ Consistent performance. Good class attendance rates."
            performance = "good"

        trainer_data.append({
            'user'         : t,
            'classes_count': classes_count,
            'members_count': members_count,
            'total_bookings': total_bookings,
            'insight'      : insight,
            'performance'  : performance,
            'classes'      : classes,
        })

    context = {
        'trainer_data' : trainer_data,
        'total_trainers': len(trainer_data),
        'top_performers': sum(1 for t in trainer_data if t['performance'] == 'top'),
    }
    return render(request, 'manage_trainers.html', context)


@login_required
def add_trainer(request):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    if request.method == 'POST':
        username = request.POST.get('username')
        email    = request.POST.get('email')
        password = request.POST.get('password')
        bio      = request.POST.get('bio', '')
        specialty = request.POST.get('specialty', '')
        profile_pic = request.FILES.get('profile_pic')
        # Prevent duplicate usernames before creating the linked trainer profile.
        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            user.profile.role = 'trainer'
            user.profile.bio  = bio
            user.profile.specialty = specialty
            if profile_pic:
                user.profile.profile_pic = profile_pic
            user.profile.save()
            messages.success(request, f"Trainer '{username}' added successfully!")
    # Redirect back to the referring page (home or manage_trainers)
    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('manage_trainers')


@login_required
def edit_trainer(request, trainer_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    trainer = User.objects.get(id=trainer_id)
    if request.method == 'POST':
        trainer.email          = request.POST.get('email', trainer.email)
        trainer.first_name     = request.POST.get('first_name', trainer.first_name)
        trainer.last_name      = request.POST.get('last_name', trainer.last_name)
        trainer.profile.bio    = request.POST.get('bio', trainer.profile.bio)
        trainer.profile.phone  = request.POST.get('phone', trainer.profile.phone)
        trainer.profile.specialty = request.POST.get('specialty', trainer.profile.specialty)
        profile_pic = request.FILES.get('profile_pic')
        if profile_pic:
            trainer.profile.profile_pic = profile_pic
        trainer.save()
        trainer.profile.save()
        messages.success(request, f"Trainer '{trainer.username}' updated.")
    next_url = request.POST.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('manage_trainers')


@login_required
def delete_trainer(request, trainer_id):
    if request.user.profile.role != 'admin':
        return redirect('dashboard')
    user = User.objects.get(id=trainer_id)
    uname = user.username
    user.delete()
    messages.success(request, f"Trainer '{uname}' deleted.")
    next_url = request.GET.get('next', '')
    if next_url:
        return redirect(next_url)
    return redirect('manage_trainers')


    # ── rule-based NLU ──
    reply = ""

    if any(w in query for w in ['member', 'members', 'সদস্য']):
        if any(w in query for w in ['how many', 'total', 'count', 'কতজন', 'কত']):
            reply = f"📊 There are currently **{total_members} members** registered in the system. Of these, **{active_subs} have active subscriptions**."
        elif any(w in query for w in ['risk', 'inactive', 'churn', 'ঝুঁকি']):
            reply = f"⚠️ **{at_risk} members** have no attendance records and may be at risk of churning. I recommend sending them a re-engagement email or offering a discount."
        elif any(w in query for w in ['active', 'subscription', 'plan']):
            reply = f"✅ **{active_subs} members** currently have active subscriptions. That's {round((active_subs/total_members*100) if total_members else 0)}% of your total member base."
        else:
            reply = f"👥 Member summary: **{total_members} total**, **{active_subs} active subscriptions**, **{at_risk} at-risk** (no attendance)."

    elif any(w in query for w in ['trainer', 'trainers', 'প্রশিক্ষক']):
        if any(w in query for w in ['how many', 'total', 'count', 'কতজন']):
            reply = f"🏋️ You have **{total_trainers} trainers** on staff managing **{total_classes} classes** with a combined **{total_bookings} bookings**."
        elif any(w in query for w in ['best', 'top', 'perform', 'সেরা']):
            top_trainer = User.objects.filter(profile__role='trainer').annotate(
                bc=__import__('django.db.models', fromlist=['Count']).Count('classes_taught__booking')
            ).order_by('-bc').first()
            if top_trainer:
                bc = Booking.objects.filter(gym_class__trainer=top_trainer).count()
                reply = f"🌟 Your top-performing trainer is **{top_trainer.get_full_name() or top_trainer.username}** with **{bc} total bookings** across their classes."
            else:
                reply = "No trainer data available yet."
        else:
            reply = f"🏋️ Trainer overview: **{total_trainers} trainers**, managing **{total_classes} classes**, with **{total_bookings} total bookings**."

    elif any(w in query for w in ['revenue', 'money', 'income', 'আয়', 'রাজস্ব']):
        reply = f"💰 Total lifetime revenue is **${total_revenue:,.2f}**. You have **{active_subs} active subscriptions** currently generating recurring income."

    elif any(w in query for w in ['class', 'classes', 'ক্লাস']):
        most_booked = GymClass.objects.annotate(
            bc=__import__('django.db.models', fromlist=['Count']).Count('booking')
        ).order_by('-bc').first()
        if most_booked:
            reply = f"📅 You have **{total_classes} classes** in total. The most popular is **'{most_booked.title}'** with **{most_booked.bc} bookings**."
        else:
            reply = f"📅 There are **{total_classes} classes** currently scheduled."

    elif any(w in query for w in ['attendance', 'উপস্থিতি']):
        total_att = Attendance.objects.filter(is_present=True).count()
        reply = f"📋 There are **{total_att} total attendance records** across all members. Members with zero attendance: **{at_risk}**."

    elif any(w in query for w in ['summary', 'overview', 'report', 'সারসংক্ষেপ', 'সারাংশ']):
        reply = (
            f"📈 **Fitnexis AI Summary**\n\n"
            f"• 👥 Members: **{total_members}** ({active_subs} active subscriptions)\n"
            f"• 🏋️ Trainers: **{total_trainers}**\n"
            f"• 📅 Classes: **{total_classes}** ({total_bookings} total bookings)\n"
            f"• 💰 Revenue: **${total_revenue:,.2f}**\n"
            f"• ⚠️ At-risk members: **{at_risk}**\n\n"
            f"Overall gym health looks {'🟢 good' if at_risk < total_members * 0.3 else '🔴 needs attention'}."
        )

    elif any(w in query for w in ['help', 'what can you', 'সাহায্য', 'কি করতে পারো']):
        reply = (
            "🤖 I'm the **Fitnexis AI Assistant**. You can ask me:\n\n"
            "• *How many members do we have?*\n"
            "• *Who is the top trainer?*\n"
            "• *What is our total revenue?*\n"
            "• *Which class is most booked?*\n"
            "• *How many at-risk members are there?*\n"
            "• *Give me a full summary*"
        )

    else:
        reply = (
            "🤔 I'm not sure about that. Try asking:\n"
            "• 'How many members do we have?'\n"
            "• 'Who is the top trainer?'\n"
            "• 'Give me a summary'\n"
            "• 'What is our revenue?'"
        )

    return JsonResponse({'reply': reply})

@login_required
def membership_plans_view(request):
    plans = MembershipPlan.objects.all()
    active_sub = Subscription.objects.filter(user=request.user, is_active=True).first()
    return render(request, 'membership_plans.html', {'plans': plans, 'active_sub': active_sub})

@login_required
def select_trainer(request, plan_id):
    """Step 1: Show all trainers with their class counts for plans with trainer access."""
    plan = MembershipPlan.objects.get(id=plan_id)

    if not plan.has_trainer_access:
        return redirect('initiate_payment', plan_id=plan.id)

    # Trainer-enabled plans use a two-step selection: trainer first, class next.
    trainers = User.objects.filter(profile__role='trainer').select_related('profile')
    trainer_data = []
    for t in trainers:
        classes = GymClass.objects.filter(trainer=t)
        upcoming = classes.filter(schedule_time__gte=timezone.now()).count()
        trainer_data.append({
            'trainer': t,
            'total_classes': classes.count(),
            'upcoming_classes': upcoming,
        })

    context = {
        'plan': plan,
        'trainer_data': trainer_data,
    }
    return render(request, 'select_trainer.html', context)

@login_required
def select_class(request, plan_id):
    """Step 2: Show classes for the selected trainer."""
    plan = MembershipPlan.objects.get(id=plan_id)
    trainer_id = request.GET.get('trainer_id')
    classes_with_seats = []
    selected_trainer = None

    if not plan.has_trainer_access:
        return redirect('initiate_payment', plan_id=plan.id)

    if trainer_id:
        selected_trainer = User.objects.filter(id=trainer_id, profile__role='trainer').first()
        if selected_trainer:
            classes = GymClass.objects.filter(trainer=selected_trainer).order_by('schedule_time')
            # Calculate seats here so full classes can be disabled before payment.
            for c in classes:
                booked = Booking.objects.filter(gym_class=c).count()
                available = c.capacity - booked
                classes_with_seats.append({
                    'class': c,
                    'available_seats': available,
                    'is_full': available <= 0,
                })

    context = {
        'plan': plan,
        'selected_trainer': selected_trainer,
        'classes_with_seats': classes_with_seats,
        'trainer_id': trainer_id,
    }
    return render(request, 'select_class.html', context)

@login_required
def initiate_payment(request, plan_id):
    plan = MembershipPlan.objects.get(id=plan_id)
    promo_code = request.GET.get('promo_code')
    class_id = request.GET.get('class_id')
    discount = 0
    final_price = plan.price
    applied_offer = None
    selected_class = None

    if class_id:
        selected_class = GymClass.objects.filter(id=class_id).first()

    # Apply only non-expired promo codes and pass the result to the payment form.
    if promo_code:
        offer = Offer.objects.filter(promo_code__iexact=promo_code, expiry_date__gte=timezone.now().date()).first()
        if offer:
            discount = (plan.price * offer.discount_percentage) / 100
            final_price = plan.price - discount
            applied_offer = offer
            messages.success(request, f"Promo code applied! You saved BDT {discount:,.2f} ({offer.discount_percentage}% off)")
        else:
            messages.error(request, "Invalid or expired promo code.")

    context = {
        'plan': plan,
        'final_price': final_price,
        'discount': discount,
        'promo_code': promo_code,
        'applied_offer': applied_offer,
        'selected_class': selected_class,
        'class_id': class_id,
    }
    return render(request, 'initiate_payment.html', context)

from .forms import OfflinePaymentForm

@login_required
def offline_payment(request, plan_id):
    plan = MembershipPlan.objects.get(id=plan_id)
    promo_code = request.GET.get('promo_code')
    class_id = request.GET.get('class_id')
    final_price = plan.price
    booked_class = GymClass.objects.filter(id=class_id).first() if class_id else None

    if promo_code:
        offer = Offer.objects.filter(promo_code__iexact=promo_code, expiry_date__gte=timezone.now().date()).first()
        if offer:
            discount = (plan.price * offer.discount_percentage) / 100
            final_price = plan.price - discount

    # Offline payments remain pending until an administrator verifies the proof.
    if request.method == 'POST':
        form = OfflinePaymentForm(request.POST, request.FILES)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.user = request.user
            payment.plan = plan
            payment.amount = final_price
            payment.payment_method = 'offline'
            payment.status = 'pending'
            payment.booked_class = booked_class
            payment.save()
            messages.success(request, f"Offline payment of BDT {final_price} submitted. Admin will verify and approve your enrollment shortly.")
            return redirect('member_dashboard')
    else:
        form = OfflinePaymentForm()
    return render(request, 'offline_payment.html', {'form': form, 'plan': plan, 'final_price': final_price, 'booked_class': booked_class})

@login_required
def online_payment(request, plan_id):
    plan = MembershipPlan.objects.get(id=plan_id)
    promo_code = request.GET.get('promo_code')
    class_id = request.GET.get('class_id')
    final_price = plan.price
    booked_class = GymClass.objects.filter(id=class_id).first() if class_id else None

    if promo_code:
        offer = Offer.objects.filter(promo_code__iexact=promo_code, expiry_date__gte=timezone.now().date()).first()
        if offer:
            discount = (plan.price * offer.discount_percentage) / 100
            final_price = plan.price - discount

    # Store the transaction as pending before redirecting so gateway callbacks
    # can always match the result to an internal payment record.
    # SSLCommerz Sandbox Test Credentials (Official: testbox / qwerty)
    store_id = 'testbox'
    store_pass = 'qwerty'
    
    tran_id = str(uuid.uuid4())[:10]
    
    Payment.objects.create(
        user=request.user,
        plan=plan,
        amount=final_price,
        booked_class=booked_class,
        transaction_id=tran_id,
        payment_method='online',
        status='pending'
    )
    
    post_url = "https://sandbox.sslcommerz.com/gwprocess/v4/api.php"
    
    # The gateway needs publicly resolvable absolute callback URLs.
    domain = request.build_absolute_uri('/')[:-1]
    
    payload = {
        'store_id': store_id,
        'store_passwd': store_pass,
        'total_amount': float(final_price),
        'currency': 'BDT',
        'tran_id': tran_id,
        'success_url': f"{domain}/payment/success/",
        'fail_url': f"{domain}/payment/fail/",
        'cancel_url': f"{domain}/payment/cancel/",
        'emi_option': '0',
        'cus_name': request.user.username,
        'cus_email': request.user.email or 'customer@example.com',
        'cus_add1': request.user.profile.address or 'Dhaka',
        'cus_add2': 'Dhaka',
        'cus_city': 'Dhaka',
        'cus_state': 'Dhaka',
        'cus_postcode': '1000',
        'cus_country': 'Bangladesh',
        'cus_phone': request.user.profile.phone or '01700000000',
        'shipping_method': 'NO',
        'num_of_item': 1,
        'product_name': plan.title,
        'product_category': 'Membership',
        'product_profile': 'general',
    }
    
    try:
        response = requests.post(post_url, data=payload)
        result = response.json()
        if result['status'] == 'SUCCESS':
            return redirect(result['GatewayPageURL'])
        else:
            messages.error(request, f"Failed to initiate online payment: {result.get('failedreason', 'Unknown error')}")
    except Exception as e:
        messages.error(request, f"Payment Gateway Error: {str(e)}")
        
    return redirect('initiate_payment', plan_id=plan.id)

@csrf_exempt
def payment_success(request):
    if request.method == 'POST':
        tran_id = request.POST.get('tran_id')
        try:
            payment = Payment.objects.get(transaction_id=tran_id)
            # Mark payment success before activating access and optional booking.
            payment.status = 'success'
            payment.save()

            # Activate subscription
            activate_subscription(payment.user, payment.plan)

            # Auto-book the selected class only when capacity is still available.
            if payment.booked_class:
                gym_class = payment.booked_class
                current_bookings = Booking.objects.filter(gym_class=gym_class).count()
                if current_bookings < gym_class.capacity:
                    Booking.objects.get_or_create(user=payment.user, gym_class=gym_class)
                    messages.success(request, f"Payment successful! You are enrolled in {payment.plan.title} and booked into '{gym_class.title}' on {gym_class.schedule_time.strftime('%b %d @ %I:%M %p')}.")
                else:
                    messages.warning(request, f"Payment successful! However, '{gym_class.title}' is now full. Please book another class from your dashboard.")
            else:
                messages.success(request, f"Payment successful! You are now enrolled in {payment.plan.title}.")
        except Payment.DoesNotExist:
            messages.error(request, "Transaction not found.")

    return redirect('member_dashboard')

@csrf_exempt
def payment_fail(request):
    messages.error(request, "Payment failed. Please try again.")
    return redirect('member_dashboard')

@login_required
def approve_payment(request, payment_id):
    if request.user.profile.role != 'admin':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    payment = Payment.objects.get(id=payment_id)
    payment.status = 'approved'
    payment.save()
    
    # Admin approval is the activation point for offline payments.
    activate_subscription(payment.user, payment.plan)
    
    messages.success(request, f"Payment for {payment.user.username} approved. Enrollment active.")
    return redirect('manage_payments')

def activate_subscription(user, plan):
    from datetime import timedelta
    from django.utils import timezone
    
    # Replace the user's current subscription so approval always leaves one
    # authoritative active plan and a date range derived from that plan.
    start_date = timezone.now().date()
    if plan.duration_unit == 'days':
        end_date = start_date + timedelta(days=plan.duration_months)
    elif plan.duration_unit == 'years':
        end_date = start_date + timedelta(days=plan.duration_months * 365)
    else: # months
        end_date = start_date + timedelta(days=plan.duration_months * 30)
        
    Subscription.objects.update_or_create(
        user=user,
        defaults={
            'plan': plan,
            'end_date': end_date,
            'is_active': True
        }
    )
