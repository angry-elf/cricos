from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from cricos.models import BlogPost, Course, CourseLocation, Dataset, Institution


class PageSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        for route_name in (
            "home",
            "search",
            "cities",
            "all_cities",
            "study_areas",
            "popular_providers",
            "providers",
            "data_source",
        ):
            yield {"loc": reverse(route_name), "lastmod": dataset.imported_at.isoformat()}

        for route_name in (
            "about",
            "contact",
            "methodology",
            "disclaimer",
            "privacy_policy",
            "terms_conditions",
            "faq",
        ):
            yield {"loc": reverse(route_name)}


class BlogSitemap(object):
    def items(self, site):
        for row in BlogPost.objects.filter(is_published=True, publish_date__lte=timezone.now()):
            yield {
                "loc": row.get_absolute_url(),
                "lastmod": row.updated_at.isoformat(),
            }


class ProviderSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        for row in Institution.objects.filter(dataset=dataset):
            yield {"loc": row.get_absolute_url(), "lastmod": dataset.imported_at.isoformat()}


class CourseSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        for row in Course.objects.filter(dataset=dataset, expired=False):
            yield {"loc": row.get_absolute_url(), "lastmod": dataset.imported_at.isoformat()}


class CitySearchSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        city_names = {row.location_city for row in CourseLocation.objects.filter(dataset=dataset).exclude(location_city="")}
        for city_name in city_names:
            yield {"loc": reverse("search", kwargs={"city_slug": slugify(city_name)}), "lastmod": dataset.imported_at.isoformat()}


class StudyAreaSearchSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        study_areas = {row.popular_study_area for row in Course.objects.filter(dataset=dataset, expired=False).exclude(popular_study_area="")}
        for area_name in study_areas:
            yield {"loc": reverse("search", kwargs={"course_slug": slugify(area_name)}), "lastmod": dataset.imported_at.isoformat()}


class StateSearchSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        for state in settings.POPULAR_STATES:
            yield {"loc": reverse("search", kwargs={"course_slug": slugify(state["name"])}), "lastmod": dataset.imported_at.isoformat()}


class PopularCombinationSitemap(object):
    def items(self, site):
        dataset = Dataset.objects.get(is_current=True)

        for item in settings.POPULAR_COMBINATIONS:
            yield {
                "loc": reverse(
                    "search",
                    kwargs={
                        "city_slug": slugify(item["city"]),
                        "course_slug": slugify(item["q"]),
                    },
                ),
                "lastmod": dataset.imported_at.isoformat(),
            }
