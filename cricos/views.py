import hashlib
import json
from datetime import timedelta
from io import BytesIO
from PIL import Image
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.forms import model_to_dict
from django.http import FileResponse, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt

from .forms import BlogPostForm, DateFilterForm
from .models import BlogPost, Course, CourseLocation, Dataset, ImageFile, Institution, Log


def home(request):
    dataset = Dataset.objects.get(is_current=True)
    featured_providers = Institution.objects.filter(
        dataset_id=dataset.id,
    ).order_by("-active_courses_count").prefetch_related(
        Prefetch("location_set", to_attr="locations"),
    )[:settings.MAX_PAGE_SIZE]

    latest_guides = BlogPost.objects.filter(is_published=True)[:settings.MAX_PAGE_SIZE]

    return render(
        request,
        "home.html",
        {
            "popular_cities": CourseLocation.popular_cities(settings.POPULAR_CITY_NAMES, dataset.id),
            "popular_study_areas": Course.study_area_stats(settings.POPULAR_STUDY_AREAS, dataset.id),
            "featured_providers": featured_providers,
            "latest_guides": latest_guides,
            "dataset": dataset,
        },
    )


def all_cities(request):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    city_stats = CourseLocation.objects.filter(
        dataset_id=dataset_id
    ).exclude(location_city="").values("location_city").annotate(
        providers_count=Count("provider_code", filter=~Q(provider_code=""), distinct=True),
        courses_count=Count("course_code", distinct=True),
    ).order_by("location_city")
    paginator = Paginator(city_stats, settings.MAX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "cities_all.html", {"page_obj": page_obj})


def search(request, city_slug="", course_slug=""):
    city = request.GET.get("city", "").strip()
    course = request.GET.get("q", "").strip()

    if city and course:
        return redirect(reverse("search", kwargs={"city_slug": slugify(city), "course_slug": slugify(course)}))
    elif city:
        return redirect(reverse("search", kwargs={"city_slug": slugify(city)}))
    elif course:
        return redirect(reverse("search", kwargs={"course_slug": slugify(course)}))

    city = city_slug.replace("-", " ").title()
    course = course_slug.replace("-", " ")

    page_obj = None
    if city or course:
        dataset_id = Dataset.objects.only("id").get(is_current=True).id
        courses = Course.search_courses(dataset_id=dataset_id, city=city, course_query=course)
        paginator = Paginator(courses, settings.MAX_PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "search.html",
        {
            "city": city,
            "course": course,
            "page_obj": page_obj,
        },
    )


def course_detail(request, provider_code, course_code):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    course = get_object_or_404(
        Course.objects.select_related("institution").prefetch_related(
            Prefetch("courselocation_set", to_attr="course_locations"),
            Prefetch("institution__location_set", to_attr="campus_locations"),
        ),
        dataset_id=dataset_id,
        provider_code__iexact=provider_code,
        course_code__iexact=course_code,
    )

    return render(
        request,
        "course_detail.html",
        {
            "course": course,
        },
    )


def provider(request, provider_code):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    institution = get_object_or_404(
        Institution.objects.prefetch_related(
            Prefetch("location_set", to_attr="locations"),
        ),
        dataset_id=dataset_id,
        provider_code__iexact=provider_code,
    )
    courses = institution.course_set.filter(expired=False).order_by("course_name").prefetch_related(
        Prefetch("courselocation_set", to_attr="course_locations"),
    )
    provider_locations = institution.locations
    provider_course_locations = CourseLocation.objects.filter(course__institution=institution)
    provider_cities = []
    provider_states = []
    for location in provider_locations:
        if location.city and location.city not in provider_cities:
            provider_cities.append(location.city)
        if location.state and location.state not in provider_states:
            provider_states.append(location.state)

    paginator = Paginator(courses, settings.MAX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "provider.html",
        {
            "institution": institution,
            "page_obj": page_obj,
            "provider_cities": provider_cities,
            "provider_states": provider_states,
            "provider_locations": provider_locations,
            "provider_course_locations": provider_course_locations,
        },
    )


def popular_providers(request):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    featured_providers = Institution.objects.filter(
        dataset_id=dataset_id,
    ).order_by("-active_courses_count").prefetch_related(
        Prefetch("location_set", to_attr="locations"),
    )[:12]

    return render(request, "providers_popular.html", {"featured_providers": featured_providers})


def providers(request):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    institutions = Institution.objects.filter(
        dataset_id=dataset_id,
    ).order_by("-active_courses_count").prefetch_related(
        Prefetch("location_set", to_attr="locations"),
    )
    paginator = Paginator(institutions, settings.MAX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "providers.html", {"page_obj": page_obj})


def cities(request):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    return render(request, "cities.html", {"popular_cities": CourseLocation.popular_cities(settings.POPULAR_CITY_NAMES, dataset_id)})


def study_areas(request):
    dataset_id = Dataset.objects.only("id").get(is_current=True).id
    return render(request, "study_areas.html", {"popular_study_areas": Course.study_area_stats(settings.POPULAR_STUDY_AREAS, dataset_id)})


def data_source(request):
    return render(request, "data_source.html", {"dataset": Dataset.objects.get(is_current=True)})


def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True).order_by("-publish_date")
    if not request.user.is_staff:
        posts = posts.filter(publish_date__lte=timezone.now())

    paginator = Paginator(posts, settings.MAX_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "blog_list.html", {"page_obj": page_obj, "now": timezone.now().date()})


def blog_detail(request, slug):
    posts = BlogPost.objects.select_related("author").filter(slug=slug, is_published=True)
    if not request.user.is_staff:
        posts = posts.filter(publish_date__lte=timezone.now())

    post = get_object_or_404(posts)
    return render(request, "blog.html", {"post": post, "now": timezone.now().date()})


@staff_member_required
def blog_edit(request, slug=None):
    if slug:
        post = get_object_or_404(BlogPost, slug=slug)
    else:
        post = BlogPost(author=request.user)

    initial = model_to_dict(post)
    if request.method == "POST":
        form = BlogPostForm(request.POST, initial=initial)
        if form.is_valid():
            post.title = form.cleaned_data["title"]
            post.content = form.cleaned_data["content"]
            post.is_published = form.cleaned_data["is_published"]
            post.slug = form.cleaned_data["slug"]
            post.seo_title = form.cleaned_data["seo_title"]
            post.seo_description = form.cleaned_data["seo_description"]
            post.seo_keyphrase = form.cleaned_data["seo_keyphrase"]
            post.publish_date = timezone.now() + timedelta(days=form.cleaned_data["publish_date"] or 0)
            post.save()
            Log.journal(None, "cricos", "blog", str(post.id), "Blog created", request.POST)
            if form.cleaned_data["is_published"]:
                return redirect(post.get_absolute_url())
            return render(request, "blog_edit.html", {"form": form, "post": post})
    else:
        form = BlogPostForm(initial=initial)

    return render(request, "blog_edit.html", {"form": form, "post": post})


@csrf_exempt
@staff_member_required
def image_upload(request):
    try:
        file = request.FILES.get("image")
        if not file:
            return JsonResponse({"success": 0, "message": "No image provided"})

        buffer = BytesIO()
        image = Image.open(file)
        image.save(buffer, format="WEBP", quality=100)
        buffer.seek(0)
        image_data = buffer.getvalue()

        image_obj = ImageFile.objects.create(content_type="image/webp", content=image_data, name=file.name)

        return JsonResponse(
            {
                "success": 1,
                "file": {
                    "url": reverse("image_fetch", kwargs={"file_id": image_obj.id}),
                    "name": image_obj.name,
                    "size": len(image_data),
                    "title": image_obj.name,
                    "date_uploaded": image_obj.date_uploaded,
                    "file_id": image_obj.id,
                    "content_type": image_obj.content_type,
                },
            }
        )
    except Exception as exc:
        return JsonResponse({"success": 0, "message": str(exc)})


def image_fetch(request, file_id):
    try:
        file = ImageFile.objects.get(id=file_id)
        etag = f"md5-{hashlib.md5(file.content).hexdigest()}"

        if request.META.get("HTTP_IF_NONE_MATCH", "") == etag:
            return HttpResponseNotModified()

        response = FileResponse(BytesIO(file.content), content_type=file.content_type)
        response["ETag"] = etag
        response["Content-Length"] = len(file.content)
        response["Content-Disposition"] = f'attachment; filename="{file.name}"'
        return response
    except ImageFile.DoesNotExist:
        return JsonResponse({"error": "Файл не найден"}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


def ping(request):
    if "sentry" in request.GET:
        _ = 1 / 0

    if "headers" in request.GET:
        keys = ("REMOTE_ADDR", "GATEWAY_INTERFACE", "HOME", "SCRIPT", "HTTP_", "SERVER_", "DJANGO_", "WSGI", "UWSGI")
        meta = [f"{k}: {v}" for k, v in sorted(request.META.items()) if k.upper().startswith(keys)]
        meta.append(f"host: {request.get_host()}")
        meta.append(f"scheme: {request.scheme}")
        return HttpResponse(json.dumps(meta, indent=4), content_type="application/json")

    return HttpResponse("ok")


@staff_member_required
def journal_record(request, log_id):
    log = Log.objects.select_related("user").get(id=log_id)
    if log.object_id:
        try:
            if log.module == "main":
                url = reverse(log.submodule, args=(log.object_id,))
            else:
                url = reverse(f"{log.module}:{log.submodule}", args=(log.object_id,))
        except Exception as exc:
            messages.error(request, _("Address conversion error: %s") % exc)
            url = None
    else:
        url = None

    return render(request, "log.html", {"log": log, "url": url})


@staff_member_required
def journal_list(request):
    current_date = timezone.now().date()
    initial = {"date": current_date}

    form = DateFilterForm()
    if "date" in request.GET:
        form = DateFilterForm(request.GET)
        if form.is_valid():
            initial.update(form.cleaned_data)

    return render(
        request,
        "journal.html",
        {
            "logs": Log.objects.select_related("user").filter(date__date=initial["date"]),
            "form": form,
            "initial": initial,
            "is_today": initial["date"] == current_date,
        },
    )


def faq(request):
    return render(request, "about.html")


def about(request):
    return render(request, "about.html")


def methodology(request):
    dataset = Dataset.objects.get(is_current=True)
    data_last_updated = dataset.dataset_datetime or dataset.imported_at

    return render(
        request,
        "methodology.html",
        {
            "dataset": dataset,
            "data_last_updated": data_last_updated,
            "seo_title": "CRICOS Finder Methodology",
            "seo_description": "How CRICOS Finder imports, structures and presents publicly available CRICOS data.",
            "canonical_url": request.build_absolute_uri(request.path),
        },
    )


def disclaimer(request):
    dataset = Dataset.objects.get(is_current=True)
    data_last_updated = dataset.dataset_datetime or dataset.imported_at

    return render(
        request,
        "disclaimer.html",
        {
            "dataset": dataset,
            "data_last_updated": data_last_updated,
            "seo_title": "CRICOS Finder Disclaimer",
            "seo_description": "Important legal and data-accuracy disclaimer for using CRICOS Finder content.",
            "canonical_url": request.build_absolute_uri(request.path),
        },
    )


def contact(request):
    return render(
        request,
        "contact.html",
        {
            "seo_title": "Contact CRICOS Finder",
            "seo_description": "Contact page for CRICOS Finder questions, corrections and feedback.",
            "canonical_url": request.build_absolute_uri(request.path),
        },
    )
