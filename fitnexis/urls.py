"""
URL configuration for fitnexis project.
"""
from django.urls import path
from django.shortcuts import render
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from core.views import (
    home, login_view, signup_view, logout_view, forgot_password_view,
    dashboard, member_dashboard, trainer_dashboard, admin_dashboard,
    error_404, book_class, update_progress, cancel_booking, mark_attendance, add_class,
    add_plan, edit_plan, delete_plan,
    manage_members, add_member, edit_member, delete_member,
    manage_trainers, add_trainer, edit_trainer, delete_trainer,
    assign_class_to_trainer, remove_class_from_trainer,
    manage_payments, delete_payment,
    manage_plans,
    manage_offers, add_offer, edit_offer, delete_offer,
    manage_reports,
    manage_classes, edit_class, delete_class, class_detail,
    membership_plans_view, initiate_payment, offline_payment, online_payment,
    payment_success, payment_fail, approve_payment, select_class, select_trainer,
)

urlpatterns = [
    path('admin/logout/', RedirectView.as_view(url='/logout/', permanent=True)),
    path('', home, name='home'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('signup/', signup_view, name='signup'),
    path('forgot-password/', forgot_password_view, name='forgot_password'),
    path('dashboard/', dashboard, name='dashboard'),
    path('dashboard/member/', member_dashboard, name='member_dashboard'),
    path('dashboard/trainer/', trainer_dashboard, name='trainer_dashboard'),
    path('dashboard/admin/', admin_dashboard, name='admin_dashboard'),
    path('book-class/<int:class_id>/', book_class, name='book_class'),
    path('cancel-booking/<int:booking_id>/', cancel_booking, name='cancel_booking'),
    path('update-progress/', update_progress, name='update_progress'),
    path('mark-attendance/<int:booking_id>/', mark_attendance, name='mark_attendance'),
    path('add-class/', add_class, name='add_class'),
    # Plans (legacy)
    path('add-plan/', add_plan, name='add_plan'),
    path('edit-plan/<int:plan_id>/', edit_plan, name='edit_plan'),
    path('delete-plan/<int:plan_id>/', delete_plan, name='delete_plan'),
    # Members
    path('manage/members/', manage_members, name='manage_members'),
    path('manage/members/add/', add_member, name='add_member'),
    path('manage/members/edit/<int:member_id>/', edit_member, name='edit_member'),
    path('manage/members/delete/<int:member_id>/', delete_member, name='delete_member'),
    # Trainers
    path('manage/trainers/', manage_trainers, name='manage_trainers'),
    path('manage/trainers/add/', add_trainer, name='add_trainer'),
    path('manage/trainers/edit/<int:trainer_id>/', edit_trainer, name='edit_trainer'),
    path('manage/trainers/delete/<int:trainer_id>/', delete_trainer, name='delete_trainer'),
    path('manage/trainers/<int:trainer_id>/assign-class/', assign_class_to_trainer, name='assign_class_to_trainer'),
    path('manage/trainers/remove-class/<int:class_id>/', remove_class_from_trainer, name='remove_class_from_trainer'),
    # Classes
    path('manage/classes/', manage_classes, name='manage_classes'),
    path('manage/classes/edit/<int:class_id>/', edit_class, name='edit_class'),
    path('manage/classes/delete/<int:class_id>/', delete_class, name='delete_class'),
    path('class/<int:class_id>/', class_detail, name='class_detail'),
    # Payments
    path('manage/payments/', manage_payments, name='manage_payments'),
    path('manage/payments/delete/<int:payment_id>/', delete_payment, name='delete_payment'),
    # Membership Plans
    path('manage/plans/', manage_plans, name='manage_plans'),
    # Offers & Discounts
    path('manage/offers/', manage_offers, name='manage_offers'),
    path('manage/offers/add/', add_offer, name='add_offer'),
    path('manage/offers/edit/<int:offer_id>/', edit_offer, name='edit_offer'),
    path('manage/offers/delete/<int:offer_id>/', delete_offer, name='delete_offer'),
    # Reports
    path('manage/reports/', manage_reports, name='manage_reports'),
    path('404/', lambda r: render(r, '404.html'), name='test_404'),
    # Payments
    path('membership/', membership_plans_view, name='membership_plans'),
    path('membership/select-trainer/<int:plan_id>/', select_trainer, name='select_trainer'),
    path('membership/select-class/<int:plan_id>/', select_class, name='select_class'),
    # Catch bare /payment/ URL - redirect to plans
    path('payment/', lambda r: RedirectView.as_view(pattern_name='membership_plans', permanent=False)(r), name='payment_redirect'),
    path('payment/initiate/<int:plan_id>/', initiate_payment, name='initiate_payment'),
    path('payment/offline/<int:plan_id>/', offline_payment, name='offline_payment'),
    path('payment/online/<int:plan_id>/', online_payment, name='online_payment'),
    path('payment/success/', payment_success, name='payment_success'),
    path('payment/fail/', payment_fail, name='payment_fail'),
    path('payment/cancel/', payment_fail, name='payment_cancel'),
    path('manage/payments/approve/<int:payment_id>/', approve_payment, name='approve_payment'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = 'core.views.error_404'
