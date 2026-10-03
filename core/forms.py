import re

from django import forms
from django.contrib.auth.models import User
from .models import Profile, Payment

class SignupForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=Profile.ROLE_CHOICES)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
            profile = user.profile
            profile.role = self.cleaned_data['role']
            profile.save()
        return user

class OfflinePaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['bank_name', 'account_number', 'deposit_slip']
        widgets = {
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Bank Name'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter Account Number'}),
            'deposit_slip': forms.FileInput(attrs={'class': 'form-control'}),
        }


MAX_PHOTO_BYTES = 5 * 1024 * 1024


class UserSettingsForm(forms.ModelForm):
    """Name and email fields stored on the auth User."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This email is already used by another account.")
        return email


class ProfileSettingsForm(forms.ModelForm):
    """Contact details and photo stored on the Profile."""
    remove_photo = forms.BooleanField(required=False)

    class Meta:
        model = Profile
        fields = ['phone', 'address', 'bio', 'specialty', 'profile_pic']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'bio': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Specialty only makes sense for trainers.
        if self.instance.role != 'trainer':
            del self.fields['specialty']

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        if phone and not re.fullmatch(r'\+?[0-9][0-9 ()\-]{5,14}', phone):
            raise forms.ValidationError("Enter a valid phone number (6-15 digits, may start with +).")
        return phone

    def clean_profile_pic(self):
        pic = self.cleaned_data.get('profile_pic')
        if pic and hasattr(pic, 'size') and pic.size > MAX_PHOTO_BYTES:
            raise forms.ValidationError("Photo must be 5 MB or smaller.")
        return pic
