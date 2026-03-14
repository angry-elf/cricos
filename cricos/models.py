import json
import uuid

import redis
from django.conf import settings
from django.db import models
from django.db.models import Count, Prefetch, Q
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import slugify


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    author = models.ForeignKey(User, on_delete=models.RESTRICT)
    content = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=True)
    publish_date = models.DateField(default=timezone.now, db_index=True)

    seo_description = models.CharField(max_length=180, null=True)
    seo_title = models.CharField(max_length=100, null=True)
    seo_keyphrase = models.CharField(max_length=100, null=True)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog", args=[self.slug])

    def editorjs_to_html(self):
        html_content = ""
        blocks = json.loads(self.content).get('blocks', [])

        for block in blocks:
            if block["type"] == "paragraph":
                html_content += f'<p>{block["data"]["text"]}</p>\n'

            elif block["type"] == "header":
                level = block["data"]["level"]
                html_content += f'<h{level} class="mt-3 mb-3">{block["data"]["text"]}</h{level}>\n'

            elif block["type"] == "image":
                caption = block["data"].get("caption", "")
                html_content += f'<p><img src="{block["data"]["file"]["url"]}" alt="{escape(caption or '')}" class="img-fluid rounded"></p>\n'

            elif block["type"] == "list":
                style = "ul" if block["data"]["style"] == "unordered" else "ol"
                items = "".join([f'<li>{item.get("content", "")}</li>' for item in block["data"]["items"]])
                html_content += f'<{style} class="mb-3">\n{items}\n</{style}>\n'

            elif block["type"] == "quote":
                text = block["data"]["text"]
                caption = block["data"].get("caption", "")
                html_content += f'''
                    <blockquote class="blockquote bg-light p-3 rounded mb-3">
                        <p class="mb-2">{text}</p>
                        {f'<footer class="blockquote-footer mt-2">{caption}</footer>' if caption else ''}
                    </blockquote>\n'''

            elif block["type"] == "delimiter":
                html_content += '<hr class="my-4">\n'

            elif block["type"] == "table":
                rows_html = []
                for row in block["data"]["content"]:
                    cells_html = [f'<td>{cell}</td>' for cell in row]
                    rows_html.append('<tr>' + ''.join(cells_html) + '</tr>')
                html_content += '<table class="table table-bordered mb-3">' + ''.join(rows_html) + '</table>\n'

            elif block["type"] == "code":
                html_content += f'''
                    <pre class="bg-light p-3 rounded mb-3">
                        <code>{escape(block["data"]["code"])}</code>
                    </pre>\n'''

        return html_content

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        rds = redis.Redis(**settings.REDIS)
        rds.rpush(settings.REDIS_INDEXNOW, json.dumps({
            "url": self.get_absolute_url(),
        }))


class ImageFile(models.Model):
    name = models.CharField(max_length=255, default="")
    date_uploaded = models.DateTimeField(auto_now_add=True)
    content_type = models.CharField(max_length=100)
    content = models.BinaryField()


class Log(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    module = models.CharField(max_length=40, db_index=True)
    submodule = models.CharField(max_length=100, db_index=True)
    message = models.CharField(max_length=1000)
    data = models.TextField(blank=True, default=None, null=True)
    object_id = models.CharField(max_length=30, blank=True, default=None, null=True, db_index=True)
    user = models.ForeignKey(User, blank=True, default=None, null=True, on_delete=models.RESTRICT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Log({self.id} @ {self.date})"

    @staticmethod
    def journal(user, module, submodule, object_id=None, message=None, data=None):
        log = Log(
            module=module,
            submodule=submodule,
            message=message,
            user=user,
            object_id=object_id,
            data=data,
        )
        log.save()

        return log

    def get_absolute_url(self):
        return reverse('journal_record', kwargs={'log_id': self.id})

    @staticmethod
    def object_logs(request, module, submodule, object_id, limit=100):
        if object_id:
            return Log.objects.select_related("user").filter(module=module, submodule=submodule, object_id=object_id)[:limit]
        else:
            return Log.objects.select_related("user").filter(module=module, submodule=submodule)[:limit]


class Dataset(models.Model):
    source_file_name = models.CharField(max_length=512)
    source_file_sha256 = models.CharField(max_length=64, db_index=True)
    dataset_datetime = models.DateTimeField(blank=True, null=True, db_index=True)
    imported_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_current = models.BooleanField(default=False)
    institutions_count = models.PositiveIntegerField(default=0)
    courses_count = models.PositiveIntegerField(default=0)
    locations_count = models.PositiveIntegerField(default=0)
    course_locations_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.source_file_name or f"Dataset {self.id}"


class Institution(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    provider_code = models.CharField(max_length=32, db_index=True)
    institution_name = models.CharField(max_length=255, db_index=True, blank=True)
    active_courses_count = models.PositiveIntegerField(default=0)
    total_courses_count = models.PositiveIntegerField(default=0)
    campuses_count = models.PositiveIntegerField(default=0)
    cities_count = models.PositiveIntegerField(default=0)
    states_count = models.PositiveIntegerField(default=0)
    trading_name = models.CharField(max_length=255, blank=True)
    institution_type = models.CharField(max_length=255, blank=True)
    institution_capacity = models.PositiveIntegerField(blank=True, null=True)
    website = models.CharField(max_length=500, blank=True)
    postal_address_line_1 = models.CharField(max_length=255, blank=True)
    postal_address_line_2 = models.CharField(max_length=255, blank=True)
    postal_address_line_3 = models.CharField(max_length=255, blank=True)
    postal_address_line_4 = models.CharField(max_length=255, blank=True)
    postal_city = models.CharField(max_length=255, blank=True)
    postal_state = models.CharField(max_length=255, blank=True)
    postal_postcode = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.institution_name or self.provider_code

    def get_absolute_url(self):
        return reverse("provider", args=[self.provider_code])


class Course(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, blank=True, null=True)
    provider_code = models.CharField(max_length=32, db_index=True)
    course_code = models.CharField(max_length=64, db_index=True)
    institution_name = models.CharField(max_length=255, blank=True)
    course_name = models.CharField(max_length=500, db_index=True, blank=True)
    search_text = models.TextField(blank=True)
    popular_study_area = models.CharField(max_length=64, blank=True, db_index=True)
    campuses_count = models.PositiveIntegerField(default=0)
    vet_national_code = models.CharField(max_length=128, blank=True)
    dual_qualification = models.CharField(max_length=255, blank=True)
    course_level = models.CharField(max_length=255, blank=True)
    foundation_studies = models.CharField(max_length=255, blank=True)
    work_component = models.CharField(max_length=255, blank=True)
    work_component_hours_per_week = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    work_component_weeks = models.IntegerField(blank=True, null=True)
    work_component_total_hours = models.IntegerField(blank=True, null=True)
    course_language = models.CharField(max_length=255, blank=True)
    duration_weeks = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    tuition_fee = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    non_tuition_fee = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    estimated_total_course_cost = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    field_1_broad = models.CharField(max_length=255, blank=True)
    field_1_narrow = models.CharField(max_length=255, blank=True)
    field_1_detailed = models.CharField(max_length=255, blank=True)
    field_2_broad = models.CharField(max_length=255, blank=True)
    field_2_narrow = models.CharField(max_length=255, blank=True)
    field_2_detailed = models.CharField(max_length=255, blank=True)
    expired = models.BooleanField(default=False)

    def __str__(self):
        return self.course_name or self.course_code

    def get_absolute_url(self):
        return reverse("course_detail", args=[self.provider_code, self.course_code])

    @classmethod
    def search_courses(cls, dataset_id, city="", course_query=""):
        qs = cls.objects.select_related("institution").prefetch_related(
            Prefetch("courselocation_set", to_attr="course_locations"),
        ).filter(dataset_id=dataset_id, expired=False)

        state_code = ""
        popular_study_area = ""
        if course_query:
            query = course_query.lower()
            for state in settings.POPULAR_STATES:
                if query == state["name"].lower() or query == state["code"].lower():
                    state_code = state["code"]
                    break
            for area in settings.POPULAR_STUDY_AREAS:
                if query == area["name"].lower():
                    popular_study_area = area["name"]
                    break
                for keyword in area["keywords"]:
                    if query == keyword.lower():
                        popular_study_area = area["name"]
                        break
                if popular_study_area:
                    break

        if course_query:
            if state_code:
                qs = qs.filter(
                    id__in=CourseLocation.objects.filter(
                        dataset_id=dataset_id,
                        location_state=state_code,
                    ).values("course_id")
                )
            elif popular_study_area:
                qs = qs.filter(popular_study_area=popular_study_area)
            else:
                qs = qs.filter(search_text__icontains=course_query)
        if city:
            qs = qs.filter(
                id__in=CourseLocation.objects.filter(
                    dataset_id=dataset_id,
                    location_city__icontains=city,
                ).values("course_id")
            )
        return qs.order_by("course_name")

    @classmethod
    def study_area_stats(cls, study_areas, dataset_id):
        stats_rows = cls.objects.filter(
            dataset_id=dataset_id,
            expired=False,
            popular_study_area__in=[area["name"] for area in study_areas],
        ).values("popular_study_area").annotate(
            providers_count=Count("provider_code", distinct=True),
            courses_count=Count("id"),
        )

        stats_by_name = {}
        for row in stats_rows:
            stats_by_name[row["popular_study_area"]] = row

        items = []
        for area in study_areas:
            stats = stats_by_name.get(area["name"], {})
            items.append(
                {
                    "name": area["name"],
                    "providers_count": stats.get("providers_count", 0) or 0,
                    "courses_count": stats.get("courses_count", 0) or 0,
                    "url": reverse("search", kwargs={"course_slug": slugify(area["name"])}),
                }
            )

        return items


class Location(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    institution = models.ForeignKey("Institution", on_delete=models.CASCADE, blank=True, null=True)
    provider_code = models.CharField(max_length=32, db_index=True)
    institution_name = models.CharField(max_length=255, blank=True)
    location_name = models.CharField(max_length=255, db_index=True, blank=True)
    location_type = models.CharField(max_length=255, blank=True)
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    address_line_3 = models.CharField(max_length=255, blank=True)
    address_line_4 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=255, db_index=True, blank=True)
    state = models.CharField(max_length=255, db_index=True, blank=True)
    postcode = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return self.location_name or self.city or self.provider_code


class CourseLocation(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE)
    course = models.ForeignKey("Course", on_delete=models.CASCADE, blank=True, null=True)
    location = models.ForeignKey("Location", on_delete=models.SET_NULL, blank=True, null=True)
    provider_code = models.CharField(max_length=32, db_index=True)
    course_code = models.CharField(max_length=64, db_index=True)
    institution_name = models.CharField(max_length=255, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    location_city = models.CharField(max_length=255, db_index=True, blank=True)
    location_state = models.CharField(max_length=255, db_index=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["dataset", "location_city", "course"], name="cricos_cl_ds_city_course"),
            models.Index(fields=["dataset", "location_state", "course"], name="cricos_cl_ds_state_course"),
        ]

    def __str__(self):
        return self.location_name or self.course_code

    @classmethod
    def popular_cities(cls, city_names, dataset_id):
        city_stats = cls.objects.filter(
            dataset_id=dataset_id,
            location_city__in=city_names,
        ).values("location_city").annotate(
            providers_count=Count("provider_code", distinct=True),
            courses_count=Count("course_code", distinct=True),
        )

        stats_by_city = {}
        for row in city_stats:
            stats_by_city[row["location_city"].lower()] = row

        items = []
        for city_name in city_names:
            stats = stats_by_city.get(city_name.lower(), {})
            items.append(
                {
                    "name": city_name,
                    "providers_count": stats.get("providers_count", 0) or 0,
                    "courses_count": stats.get("courses_count", 0) or 0,
                    "url": reverse("search", kwargs={"city_slug": slugify(city_name)}),
                }
            )

        return items
