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
