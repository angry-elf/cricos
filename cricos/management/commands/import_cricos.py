import csv
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from cricos.models import Course, CourseLocation, Dataset, Institution, Location
from .worker_basic import BasicCommand


DATA_GOV_PACKAGE_SHOW_URL = "https://data.gov.au/data/api/3/action/package_show"
DATA_GOV_DATASET_IDS = ("e5ae2a58-700f-4748-b6bd-f86eaf33f4e2", "cricos")

CSV_RESOURCE_NAMES = {
    "CRICOS Course Locations.csv",
    "CRICOS Courses.csv",
    "CRICOS Institutions.csv",
    "CRICOS Locations.csv",
}

AUSTRALIAN_STATE_CODES = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def as_bool(value):
    return clean(value).casefold() in {"1", "true", "y", "yes"}


def as_decimal(value):
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def as_int(value):
    number = as_decimal(value)
    return None if number is None else int(number)


def normalize(value):
    return " ".join(clean(value).split())


def titlecase_city(value):
    tokens = []
    for token in normalize(value).split(" "):
        tokens.append(token.upper() if token.isalpha() and token.upper() in AUSTRALIAN_STATE_CODES else token.title())
    return " ".join(tokens)


def course_search_text(row):
    parts = [
        normalize(row.get("Course Name")),
        normalize(row.get("Institution Name")),
        normalize(row.get("CRICOS Course Code")).upper(),
        normalize(row.get("CRICOS Provider Code")).upper(),
        normalize(row.get("Course Level")),
        normalize(row.get("Field of Education 1 Broad Field")),
        normalize(row.get("Field of Education 1 Narrow Field")),
        normalize(row.get("Field of Education 1 Detailed Field")),
        normalize(row.get("Field of Education 2 Broad Field")),
        normalize(row.get("Field of Education 2 Narrow Field")),
        normalize(row.get("Field of Education 2 Detailed Field")),
    ]
    return " ".join(part.casefold() for part in parts if part)


def popular_study_area(search_text):
    for area in settings.POPULAR_STUDY_AREAS:
        for keyword in area["keywords"]:
            if keyword.casefold() in search_text:
                return area["name"]
    return ""


def resource_datetime(resource):
    for field in ("last_modified", "created"):
        value = clean(resource.get(field))
        if not value:
            continue
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except ValueError:
            continue
    return timezone.make_aware(datetime(1970, 1, 1), timezone.get_current_timezone())


def read_csv(path, required_headers):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header_set = {str(x).strip() for x in (reader.fieldnames or [])}
        missing = [h for h in required_headers if h not in header_set]
        if missing:
            raise ValueError(f"CSV '{path.name}' missing headers: {', '.join(missing)}")
        return [
            {str(k).strip(): clean(v) for k, v in row.items() if k is not None}
            for row in reader
            if any(row.values())
        ]


class Command(BasicCommand):
    help = "Import CRICOS data into database and optionally set imported dataset as current."

    def add_arguments(self, parser):
        parser.add_argument("--no-make-current", action="store_true")
        parser.add_argument("--download-dir", default=".")
        parser.add_argument("--force-download", action="store_true")

    def handle(self, *args, **options):
        super().handle(*args, **options)

        force_download = bool(options["force_download"])
        make_current = not bool(options["no_make_current"])
        download_dir = Path(options["download_dir"]).expanduser().resolve()

        self.log("Checking latest CRICOS CSV bundle")
        payload = None
        for dataset_id in DATA_GOV_DATASET_IDS:
            try:
                response = requests.get(
                    DATA_GOV_PACKAGE_SHOW_URL,
                    params={"id": dataset_id},
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; CRICOS-Importer/1.0)"},
                    timeout=60,
                )
                data = response.json()
            except Exception:
                continue

            if data.get("success"):
                payload = data
                break

        if payload is None:
            raise CommandError("Failed to load CRICOS dataset metadata from data.gov.au")

        resources = {}
        for resource in payload.get("result", {}).get("resources", []):
            name = clean(resource.get("name"))
            if name not in CSV_RESOURCE_NAMES:
                continue
            url = clean(resource.get("url"))
            if not url:
                continue
            updated_at = resource_datetime(resource)
            if name not in resources or updated_at > resources[name]["updated_at"]:
                resources[name] = {"url": url, "id": clean(resource.get("id")), "hash": clean(resource.get("hash")), "updated_at": updated_at}

        missing = [name for name in CSV_RESOURCE_NAMES if name not in resources]
        if missing:
            raise CommandError(f"Missing CSV resources in data.gov.au package: {', '.join(missing)}")

        fingerprint_parts = [
            "|".join([name, resources[name]["id"], resources[name]["url"], resources[name]["hash"], str(resources[name]["updated_at"])])
            for name in sorted(resources)
        ]
        bundle_hash = hashlib.sha256("\n".join(fingerprint_parts).encode()).hexdigest()
        latest_datetime = max(item["updated_at"] for item in resources.values())

        existing_dataset = Dataset.objects.filter(source_file_sha256=bundle_hash).first()
        if existing_dataset:
            self.log(f"Dataset already exists (id={existing_dataset.id}).")
            if make_current and not existing_dataset.is_current:
                with transaction.atomic():
                    Dataset.objects.filter(is_current=True).exclude(pk=existing_dataset.pk).update(is_current=False)
                    existing_dataset.is_current = True
                    existing_dataset.save()
                self.log("Existing dataset marked as current.")
            return

        if not force_download:
            current_dataset = Dataset.objects.order_by("-dataset_datetime", "-imported_at").first()
            if current_dataset and current_dataset.dataset_datetime and latest_datetime <= current_dataset.dataset_datetime:
                self.log("Local CRICOS dataset is already up to date.")
                return

        download_dir.mkdir(parents=True, exist_ok=True)
        files = {}
        for name, resource in resources.items():
            download_path = download_dir / name.replace(" ", "-")
            temp_path = download_path.with_suffix(download_path.suffix + ".part")
            with requests.get(resource["url"], stream=True, timeout=60) as response:
                response.raise_for_status()
                with temp_path.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            fh.write(chunk)
            temp_path.replace(download_path)
            files[name] = download_path

        self.log("Downloaded CRICOS CSV bundle to: %s", download_dir)

        self.log("Reading CSV files")
        institutions = read_csv(files["CRICOS Institutions.csv"], ("CRICOS Provider Code", "Institution Name"))
        courses = read_csv(files["CRICOS Courses.csv"], ("CRICOS Provider Code", "CRICOS Course Code", "Course Name"))
        locations = read_csv(files["CRICOS Locations.csv"], ("CRICOS Provider Code", "Location Name", "City"))
        course_locations = read_csv(files["CRICOS Course Locations.csv"], ("CRICOS Provider Code", "CRICOS Course Code", "Location City"))

        self.log("Preparing import data")
        total_courses_by_provider = {}
        active_courses_by_provider = {}
        campuses_by_provider = {}
        cities_by_provider = {}
        states_by_provider = {}
        campuses_by_course = {}

        for row in courses:
            provider_code = clean(row.get("CRICOS Provider Code")).upper()
            course_code = clean(row.get("CRICOS Course Code")).upper()
            if not provider_code or not course_code:
                continue
            total_courses_by_provider[provider_code] = total_courses_by_provider.get(provider_code, 0) + 1
            if not as_bool(row.get("Expired")):
                active_courses_by_provider[provider_code] = active_courses_by_provider.get(provider_code, 0) + 1

        for row in locations:
            provider_code = clean(row.get("CRICOS Provider Code")).upper()
            if not provider_code:
                continue
            campuses_by_provider[provider_code] = campuses_by_provider.get(provider_code, 0) + 1
            city = titlecase_city(row.get("City", ""))
            state = clean(row.get("State")).upper()
            if city:
                cities_by_provider.setdefault(provider_code, set()).add(city)
            if state:
                states_by_provider.setdefault(provider_code, set()).add(state)

        for row in course_locations:
            provider_code = clean(row.get("CRICOS Provider Code")).upper()
            course_code = clean(row.get("CRICOS Course Code")).upper()
            if not provider_code or not course_code:
                continue
            key = (provider_code, course_code)
            campuses_by_course[key] = campuses_by_course.get(key, 0) + 1

        self.log("Writing dataset to database")
        with transaction.atomic():
            dataset = Dataset.objects.create(
                source_file_name=f"cricos-csv-bundle-{latest_datetime.strftime('%Y-%m-%d')}",
                source_file_sha256=bundle_hash,
                dataset_datetime=latest_datetime,
                is_current=False,
            )

            institution_objs = []
            for row in institutions:
                provider_code = clean(row.get("CRICOS Provider Code")).upper()
                if not provider_code:
                    continue
                institution_objs.append(Institution(
                    dataset=dataset,
                    provider_code=provider_code,
                    institution_name=clean(row.get("Institution Name")),
                    active_courses_count=active_courses_by_provider.get(provider_code, 0),
                    total_courses_count=total_courses_by_provider.get(provider_code, 0),
                    campuses_count=campuses_by_provider.get(provider_code, 0),
                    cities_count=len(cities_by_provider.get(provider_code, set())),
                    states_count=len(states_by_provider.get(provider_code, set())),
                    trading_name=clean(row.get("Trading Name")),
                    institution_type=clean(row.get("Institution Type")),
                    institution_capacity=as_int(row.get("Institution Capacity")),
                    website=clean(row.get("Website")),
                    postal_address_line_1=clean(row.get("Postal Address Line 1")),
                    postal_address_line_2=clean(row.get("Postal Address Line 2")),
                    postal_address_line_3=clean(row.get("Postal Address Line 3")),
                    postal_address_line_4=clean(row.get("Postal Address Line 4")),
                    postal_city=clean(row.get("Postal Address City")),
                    postal_state=clean(row.get("Postal Address State")),
                    postal_postcode=clean(row.get("Postal Address Postcode")),
                ))
            Institution.objects.bulk_create(institution_objs)
            institution_map = {clean(item.provider_code).upper(): item for item in Institution.objects.filter(dataset=dataset)}

            course_objs = []
            for row in courses:
                provider_code = clean(row.get("CRICOS Provider Code")).upper()
                course_code = clean(row.get("CRICOS Course Code")).upper()
                if not provider_code or not course_code:
                    continue
                search_text = course_search_text(row)
                course_objs.append(Course(
                    dataset=dataset,
                    institution=institution_map.get(provider_code),
                    provider_code=provider_code,
                    course_code=course_code,
                    institution_name=clean(row.get("Institution Name")),
                    course_name=clean(row.get("Course Name")),
                    search_text=search_text,
                    popular_study_area=popular_study_area(search_text),
                    campuses_count=campuses_by_course.get((provider_code, course_code), 0),
                    vet_national_code=clean(row.get("VET National Code")),
                    dual_qualification=clean(row.get("Dual Qualification")),
                    course_level=clean(row.get("Course Level")),
                    foundation_studies=clean(row.get("Foundation Studies")),
                    work_component=clean(row.get("Work Component")),
                    work_component_hours_per_week=as_decimal(row.get("Work Component Hours/Week")),
                    work_component_weeks=as_int(row.get("Work Component Weeks")),
                    work_component_total_hours=as_int(row.get("Work Component Total Hours")),
                    course_language=clean(row.get("Course Language")),
                    duration_weeks=as_decimal(row.get("Duration (Weeks)")),
                    tuition_fee=as_decimal(row.get("Tuition Fee")),
                    non_tuition_fee=as_decimal(row.get("Non Tuition Fee")),
                    estimated_total_course_cost=as_decimal(row.get("Estimated Total Course Cost")),
                    field_1_broad=clean(row.get("Field of Education 1 Broad Field")),
                    field_1_narrow=clean(row.get("Field of Education 1 Narrow Field")),
                    field_1_detailed=clean(row.get("Field of Education 1 Detailed Field")),
                    field_2_broad=clean(row.get("Field of Education 2 Broad Field")),
                    field_2_narrow=clean(row.get("Field of Education 2 Narrow Field")),
                    field_2_detailed=clean(row.get("Field of Education 2 Detailed Field")),
                    expired=as_bool(row.get("Expired")),
                ))
            Course.objects.bulk_create(course_objs)
            course_map = {
                (clean(item.provider_code).upper(), clean(item.course_code).upper()): item
                for item in Course.objects.filter(dataset=dataset)
            }

            location_objs = []
            for row in locations:
                provider_code = clean(row.get("CRICOS Provider Code")).upper()
                if not provider_code:
                    continue
                location_objs.append(Location(
                    dataset=dataset,
                    institution=institution_map.get(provider_code),
                    provider_code=provider_code,
                    institution_name=clean(row.get("Institution Name")),
                    location_name=clean(row.get("Location Name")),
                    location_type=clean(row.get("Location Type")),
                    address_line_1=clean(row.get("Address Line 1")),
                    address_line_2=clean(row.get("Address Line 2")),
                    address_line_3=clean(row.get("Address Line 3")),
                    address_line_4=clean(row.get("Address Line 4")),
                    city=titlecase_city(row.get("City", "")),
                    state=clean(row.get("State")),
                    postcode=clean(row.get("Postcode")),
                ))
            Location.objects.bulk_create(location_objs)
            location_map = {
                (clean(item.provider_code).upper(), clean(item.location_name).lower()): item
                for item in Location.objects.filter(dataset=dataset)
            }

            course_location_objs = []
            for row in course_locations:
                provider_code = clean(row.get("CRICOS Provider Code")).upper()
                course_code = clean(row.get("CRICOS Course Code")).upper()
                if not provider_code or not course_code:
                    continue
                location_name = clean(row.get("Location Name"))
                course_location_objs.append(CourseLocation(
                    dataset=dataset,
                    course=course_map.get((provider_code, course_code)),
                    location=location_map.get((provider_code, location_name.lower())) if location_name else None,
                    provider_code=provider_code,
                    course_code=course_code,
                    institution_name=clean(row.get("Institution Name")),
                    location_name=location_name,
                    location_city=titlecase_city(row.get("Location City", "")),
                    location_state=clean(row.get("Location State")),
                ))
            CourseLocation.objects.bulk_create(course_location_objs)

            dataset.institutions_count = len(institution_objs)
            dataset.courses_count = len(course_objs)
            dataset.locations_count = len(location_objs)
            dataset.course_locations_count = len(course_location_objs)
            if make_current:
                Dataset.objects.filter(is_current=True).exclude(pk=dataset.pk).update(is_current=False)
                dataset.is_current = True
            dataset.save()

        self.log(
            "Dataset id=%s, current=%s, institutions=%s, courses=%s, locations=%s, course_locations=%s",
            dataset.id, dataset.is_current, dataset.institutions_count, dataset.courses_count,
            dataset.locations_count, dataset.course_locations_count,
        )
        self.log("CRICOS import completed")
