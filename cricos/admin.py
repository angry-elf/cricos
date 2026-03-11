from django.contrib import admin

from .models import (
    BlogPost,
    Course,
    CourseLocation,
    Dataset,
    Institution,
    Location,
)


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "created_at", "is_published")
    list_filter = ("is_published", "created_at", "author")
    search_fields = ("title", "content")
    readonly_fields = ("updated_at", "created_at")


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "source_file_name",
        "dataset_datetime",
        "is_current",
        "institutions_count",
        "courses_count",
        "locations_count",
        "course_locations_count",
        "imported_at",
    )
    list_filter = ("is_current",)
    search_fields = ("source_file_name", "source_file_sha256")
    ordering = ("-is_current", "-dataset_datetime", "-imported_at", "-id")


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ("provider_code", "institution_name", "institution_type", "postal_city", "postal_state")
    list_filter = ("institution_type", "postal_state", "dataset")
    search_fields = ("provider_code", "institution_name", "trading_name", "website")
    autocomplete_fields = ("dataset",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("provider_code", "course_code", "course_name", "course_level", "duration_weeks", "tuition_fee", "expired")
    list_filter = ("expired", "course_level", "dataset")
    search_fields = ("provider_code", "course_code", "course_name", "institution_name")
    autocomplete_fields = ("dataset",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("provider_code", "location_name", "city", "state", "postcode")
    list_filter = ("state", "city", "dataset")
    search_fields = ("provider_code", "location_name", "city", "state", "postcode")
    autocomplete_fields = ("dataset",)


@admin.register(CourseLocation)
class CourseLocationAdmin(admin.ModelAdmin):
    list_display = ("provider_code", "course_code", "location_name", "location_city", "location_state")
    list_filter = ("location_state", "location_city", "dataset")
    search_fields = ("provider_code", "course_code", "location_name", "location_city", "location_state")
    autocomplete_fields = ("dataset",)
