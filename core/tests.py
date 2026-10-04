from datetime import date, timedelta

from django.contrib.auth.models import User
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Attendance, FitnessProgress
from .views import compute_attendance_streaks


class ProgressBackendTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('m1', password='pw12345!')
        self.other = User.objects.create_user('m2', password='pw12345!')
        self.client.login(username='m1', password='pw12345!')

    def _add(self, user, days_ago, weight, fat=None, muscle=None):
        e = FitnessProgress.objects.create(
            user=user, weight=weight, body_fat_percentage=fat, muscle_mass=muscle)
        # date is auto_now_add, so backdate with update().
        FitnessProgress.objects.filter(pk=e.pk).update(
            date=timezone.now().date() - timedelta(days=days_ago))

    def test_update_progress_saves_all_metrics(self):
        self.client.post(reverse('update_progress'), {
            'weight': '75.5', 'body_fat_percentage': '18.2', 'muscle_mass': '34', 'notes': ' hi '})
        e = FitnessProgress.objects.get(user=self.user)
        self.assertEqual(str(e.weight), '75.50')
        self.assertEqual(str(e.body_fat_percentage), '18.20')
        self.assertEqual(str(e.muscle_mass), '34.00')
        self.assertEqual(e.notes, 'hi')

    def test_optional_metrics_may_be_blank(self):
        self.client.post(reverse('update_progress'), {'weight': '70'})
        e = FitnessProgress.objects.get(user=self.user)
        self.assertIsNone(e.body_fat_percentage)
        self.assertIsNone(e.muscle_mass)

    def test_invalid_values_rejected(self):
        for bad in ({'weight': ''}, {'weight': 'abc'}, {'weight': '-5'},
                    {'weight': 'nan'}, {'weight': '70', 'body_fat_percentage': '150'},
                    {'weight': '70', 'muscle_mass': 'x'}):
            self.client.post(reverse('update_progress'), bad)
        self.assertEqual(FitnessProgress.objects.count(), 0)

    def test_progress_data_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('progress_data'))
        self.assertEqual(resp.status_code, 302)

    def test_progress_data_series_and_summary(self):
        self._add(self.user, 20, 80, fat=20)
        self._add(self.user, 10, 78, muscle=35)
        self._add(self.user, 1, 76, fat=18)
        self._add(self.other, 5, 99)  # must not leak
        d = self.client.get(reverse('progress_data')).json()
        self.assertEqual(d['count'], 3)
        self.assertEqual(d['weight'], [80.0, 78.0, 76.0])
        self.assertEqual(d['body_fat'], [20.0, None, 18.0])
        self.assertEqual(d['muscle_mass'], [None, 35.0, None])
        self.assertEqual(d['summary']['weight']['change'], -4.0)
        self.assertEqual(d['summary']['body_fat']['change'], -2.0)
        self.assertEqual(d['summary']['muscle_mass']['change'], 0.0)

    def test_range_filter_and_empty(self):
        self._add(self.user, 100, 80)
        self._add(self.user, 5, 75)
        self.assertEqual(self.client.get(reverse('progress_data'), {'range': '30'}).json()['weight'], [75.0])
        self.assertEqual(self.client.get(reverse('progress_data'), {'range': 'bogus'}).json()['count'], 2)
        FitnessProgress.objects.all().delete()
        d = self.client.get(reverse('progress_data')).json()
        self.assertEqual((d['count'], d['summary']['weight']), (0, None))


class AttendanceStreakTests(TestCase):
    TODAY = date(2026, 10, 7)  # a Wednesday

    def test_no_visits(self):
        self.assertEqual(compute_attendance_streaks([], self.TODAY), (0, 0))

    def test_consecutive_weeks_including_this_one(self):
        ds = [date(2026, 10, 6), date(2026, 9, 30), date(2026, 9, 22)]
        self.assertEqual(compute_attendance_streaks(ds, self.TODAY), (3, 3))

    def test_streak_alive_if_only_last_week_visited(self):
        self.assertEqual(compute_attendance_streaks([date(2026, 9, 30)], self.TODAY), (1, 1))

    def test_streak_broken_after_missed_week(self):
        ds = [date(2026, 9, 22), date(2026, 9, 14), date(2026, 9, 8)]  # latest is 2 weeks ago
        self.assertEqual(compute_attendance_streaks(ds, self.TODAY), (0, 3))

    def test_longest_differs_from_current(self):
        ds = [date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17), date(2026, 10, 5)]
        self.assertEqual(compute_attendance_streaks(ds, self.TODAY), (1, 3))

    def test_multiple_visits_same_week_count_once(self):
        ds = [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]
        self.assertEqual(compute_attendance_streaks(ds, self.TODAY), (1, 1))


class AttendanceDataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('a1', password='pw12345!')
        self.other = User.objects.create_user('a2', password='pw12345!')
        self.client.login(username='a1', password='pw12345!')

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('attendance_data')).status_code, 302)

    def test_month_data_only_own_present_visits(self):
        Attendance.objects.create(user=self.user, date=date(2026, 3, 2))
        Attendance.objects.create(user=self.user, date=date(2026, 3, 9))
        Attendance.objects.create(user=self.user, date=date(2026, 3, 10), is_present=False)
        Attendance.objects.create(user=self.user, date=date(2026, 2, 27))
        Attendance.objects.create(user=self.other, date=date(2026, 3, 5))
        d = self.client.get(reverse('attendance_data'), {'month': '2026-03'}).json()
        self.assertEqual((d['year'], d['month']), (2026, 3))
        self.assertEqual(d['days'], [2, 9])
        self.assertEqual(d['month_count'], 2)
        self.assertEqual(d['total'], 3)
        self.assertEqual(d['recent'][0], '2026-03-09')

    def test_bad_month_falls_back_to_current(self):
        today = timezone.localdate()
        for bad in ('', 'x', '2026-13', '99999-01', '2026'):
            d = self.client.get(reverse('attendance_data'), {'month': bad}).json()
            self.assertEqual((d['year'], d['month']), (today.year, today.month), bad)

    def test_this_month_count_ignores_viewed_month(self):
        today = timezone.localdate()
        Attendance.objects.create(user=self.user, date=today)
        d = self.client.get(reverse('attendance_data'), {'month': '2020-01'}).json()
        self.assertEqual(d['this_month_count'], 1)
        self.assertEqual(d['month_count'], 0)


class AccountSettingsTests(TestCase):
    def setUp(self):
        # Django 4.2's test client crashes copying template contexts on Python 3.14,
        # so skip its context capture and assert on rendered content instead.
        patcher = mock.patch('django.test.client.store_rendered_templates')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user('s1', 's1@x.com', 'OldPass!2345')
        self.other = User.objects.create_user('s2', 's2@x.com', 'OldPass!2345')
        self.url = reverse('account_settings')
        self.client.login(username='s1', password='OldPass!2345')

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_page_renders_for_each_role(self):
        for role in ('member', 'trainer', 'admin'):
            self.user.profile.role = role
            self.user.profile.save()
            resp = self.client.get(self.url)
            self.assertEqual(resp.status_code, 200, role)
            self.assertEqual(b'Specialty' in resp.content, role == 'trainer')
            self.assertEqual(b'Deactivate account' in resp.content, role != 'admin')

    def test_profile_update(self):
        self.client.post(self.url, {
            'action': 'profile', 'first_name': 'Sam', 'last_name': 'Lee', 'email': 'new@x.com',
            'phone': '+8801712345678', 'address': 'Dhaka', 'bio': 'hi'})
        self.user.refresh_from_db()
        self.assertEqual((self.user.first_name, self.user.email), ('Sam', 'new@x.com'))
        self.assertEqual(self.user.profile.phone, '+8801712345678')

    def test_profile_rejects_duplicate_email_and_bad_phone(self):
        resp = self.client.post(self.url, {'action': 'profile', 'email': 'S2@x.com', 'phone': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already used by another account')
        self.assertContains(resp, 'Enter a valid phone number')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 's1@x.com')

    def test_own_email_resubmit_is_fine(self):
        resp = self.client.post(self.url, {'action': 'profile', 'email': 's1@x.com'})
        self.assertEqual(resp.status_code, 302)

    def test_password_change_keeps_session(self):
        resp = self.client.post(self.url, {
            'action': 'password', 'old_password': 'OldPass!2345',
            'new_password1': 'BrandNew!9876', 'new_password2': 'BrandNew!9876'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.get(self.url).status_code, 200)  # still logged in
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNew!9876'))

    def test_password_change_wrong_old_password(self):
        resp = self.client.post(self.url, {
            'action': 'password', 'old_password': 'nope',
            'new_password1': 'BrandNew!9876', 'new_password2': 'BrandNew!9876'})
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('OldPass!2345'))

    def test_deactivate_requires_password(self):
        self.client.post(self.url, {'action': 'deactivate', 'confirm_password': 'wrong'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_deactivate_logs_out_and_keeps_data(self):
        self.client.post(self.url, {'action': 'deactivate', 'confirm_password': 'OldPass!2345'})
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.client.get(self.url).status_code, 302)  # logged out

    def test_admin_cannot_deactivate(self):
        self.user.profile.role = 'admin'
        self.user.profile.save()
        self.client.post(self.url, {'action': 'deactivate', 'confirm_password': 'OldPass!2345'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)


import io
import os
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image


def _png(name='p.png', size=(4, 4)):
    buf = io.BytesIO()
    Image.new('RGB', size, 'red').save(buf, 'PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class SettingsPhotoTests(TestCase):
    def setUp(self):
        patcher = mock.patch('django.test.client.store_rendered_templates')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(MEDIA_ROOT=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user('ph', 'ph@x.com', 'OldPass!2345')
        self.client.login(username='ph', password='OldPass!2345')
        self.url = reverse('account_settings')

    def _profile(self, **extra):
        return self.client.post(self.url, {'action': 'profile', 'email': 'ph@x.com', **extra})

    def test_upload_replace_and_remove(self):
        self._profile(profile_pic=_png('a.png'))
        self.user.profile.refresh_from_db()
        first = self.user.profile.profile_pic.path
        self.assertTrue(os.path.exists(first))

        self._profile(profile_pic=_png('b.png'))  # replacing deletes the old file
        self.user.profile.refresh_from_db()
        self.assertFalse(os.path.exists(first))
        second = self.user.profile.profile_pic.path
        self.assertTrue(os.path.exists(second))

        self._profile(remove_photo='on')
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.profile_pic)
        self.assertFalse(os.path.exists(second))

    def test_saving_without_file_keeps_photo(self):
        self._profile(profile_pic=_png())
        self._profile(phone='123456')
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.profile_pic)

    def test_non_image_rejected(self):
        bad = SimpleUploadedFile('x.png', b'not an image', content_type='image/png')
        resp = self._profile(profile_pic=bad)
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertFalse(self.user.profile.profile_pic)
