from django import forms
from django.utils.translation import gettext_lazy as _
from cricos.models import BlogPost
from django.utils.text import slugify
from django.utils import timezone


class DateFilterForm(forms.Form):
    date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control', 'style': 'width: auto'}),
        label='',
    )


class BlogPostForm(forms.Form):
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    content = forms.CharField(
        widget=forms.HiddenInput(attrs={'id': 'content-data'}),
        required=False
    )

    slug = forms.SlugField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )

    seo_title = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    seo_description = forms.CharField(
        max_length=180,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    seo_keyphrase = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    publish_date = forms.IntegerField(
        required=False,
        label=_('Deferred publication'),
        help_text=_('Postpone publication for N days. O - publish now. 1 - publish tomorrow, 2 - the day after tomorrow, an empty field - do not change the publication date')
    )

    is_published = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )


    def clean_slug(self):
        slug = self.cleaned_data.get('slug')
        title = self.cleaned_data.get('title')

        if not slug and title:
            slug = slugify(f"{title}-{timezone.now().strftime('%Y%m%d%H%M%S')}")

        if slug == self.initial.get("slug"):
            return slug

        if BlogPost.objects.filter(slug=slug).exists():
            raise forms.ValidationError('This slug is already in use. Please choose another one.')

        return slug
