from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import FitnessProgress


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
