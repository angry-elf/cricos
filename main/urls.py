"""
URL configuration for main project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.views.static import serve
from debug_toolbar.toolbar import debug_toolbar_urls
from cricos import views
from metasite.tools import views as metasite

urlpatterns = [
    path("admin/", admin.site.urls),

    path('3bbfb19b0bff407ebd17ba1ef3aa314b.txt', serve, {'document_root': settings.MEDIA_ROOT, 'path': '3bbfb19b0bff407ebd17ba1ef3aa314b.txt'}),
    path('sitemap_index.xml', metasite.sitemap_serve, name="sitemap"),
    path('sitemap_<int:index>.xml', metasite.sitemap_serve, name="sitemap"),

    path('privacy-policy/', metasite.privacy_policy, name='privacy_policy'),
    path('terms-conditions/', metasite.terms_conditions, name='terms_conditions'),

    path('faq/', views.faq, name='faq'),
    path("study-areas/", views.study_areas, name="study_areas"),
    path("data-source/", views.data_source, name="data_source"),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('methodology/', views.methodology, name='methodology'),
    path('disclaimer/', views.disclaimer, name='disclaimer'),

    path("", views.home, name="home"),
    path("courses/city/<slug:city_slug>/<slug:course_slug>/", views.search, name="search"),
    path("courses/city/<slug:city_slug>/", views.search, name="search"),
    path("courses/<slug:course_slug>/", views.search, name="search"),
    path("courses/", views.search, name="search"),
    path("courses/<str:provider_code>/<str:course_code>/", views.course_detail, name="course_detail"),

    path("cities/all/", views.all_cities, name="all_cities"),
    path("cities/", views.cities, name="cities"),

    path("providers/", views.providers, name="providers"),
    path("providers/<str:provider_code>/", views.provider, name="provider"),

    path('blogs/', views.blog_list, name='blogs'),
    path('blogs/<slug:slug>/edit/', views.blog_edit, name='blog_edit'),
    path('blogs/edit/', views.blog_edit, name='blog_edit'),
    path('blogs/<slug:slug>/', views.blog_detail, name='blog'),

    path('images/upload_file/', views.image_upload, name='image_upload'),
    path('images/<int:file_id>/', views.image_fetch, name='image_fetch'),

    path('journal/', views.journal_list, name='journal'),
    path('journal/<uuid:log_id>/', views.journal_record, name='journal_record'),

    path('ping', views.ping),

    path('media/<path:path>', serve, {'document_root': settings.MEDIA_ROOT}),
] + debug_toolbar_urls()
