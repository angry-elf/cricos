import csv
import hashlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from cricos.models import (
    Course,
    CourseLocation,
    Dataset,
    Institution,
    Location,
)
from .worker_basic import BasicCommand


DATA_GOV_PACKAGE_SHOW_URL = "https://data.gov.au/data/api/3/action/package_show"
DATA_GOV_DATASET_IDS = ("e5ae2a58-700f-4748-b6bd-f86eaf33f4e2", "cricos")

CSV_RESOURCE_NAMES = {
    "course_locations": "CRICOS Course Locations.csv",
    "courses": "CRICOS Courses.csv",
    "institutions": "CRICOS Institutions.csv",
    "locations": "CRICOS Locations.csv",
}

AUSTRALIAN_STATE_CODES = frozenset({"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"})


def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _as_bool(value):
    return _clean(value).casefold() in {"1", "true", "y", "yes"}


def _as_decimal(value):
    text = _clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _as_int(value):
    number = _as_decimal(value)
    if number is None:
        return None
    return int(number)


def _as_positive_int(value):
    number = _as_int(value)
    if number is None or number < 0:
        return None
    return number


def _normalize_whitespace(value):
    return " ".join(_clean(value).split())


def _titlecase_city(value):
    tokens = []
    for token in _normalize_whitespace(value).split(" "):
        if token.isalpha() and token.upper() in AUSTRALIAN_STATE_CODES:
            tokens.append(token.upper())
        else:
            tokens.append(token.title())
    return " ".join(tokens)


def _choose_canonical_city(variants):
    ordered_variants = sorted(variants, key=lambda item: (len(item), item.casefold(), item))
    for candidate in ordered_variants:
        if candidate == _titlecase_city(candidate):
            return candidate
    return _titlecase_city(ordered_variants[0])


def _build_city_name_map(locations, course_locations):
    grouped = {}

    for rows, field_name in ((locations, "City"), (course_locations, "Location City")):
        for row in rows:
            city = _normalize_whitespace(row.get(field_name))
            if not city:
                continue
            grouped.setdefault(city.casefold(), set()).add(city)

    return {city_key: _choose_canonical_city(variants) for city_key, variants in grouped.items()}


def _canonical_city(value, city_name_map):
    city = _normalize_whitespace(value)
    if not city:
        return ""
    return city_name_map.get(city.casefold(), _titlecase_city(city))


def _course_search_text(row):
    parts = [
        _normalize_whitespace(row.get("Course Name")),
        _normalize_whitespace(row.get("Institution Name")),
        _normalize_whitespace(row.get("CRICOS Course Code")).upper(),
        _normalize_whitespace(row.get("CRICOS Provider Code")).upper(),
        _normalize_whitespace(row.get("Course Level")),
        _normalize_whitespace(row.get("Field of Education 1 Broad Field")),
        _normalize_whitespace(row.get("Field of Education 1 Narrow Field")),
        _normalize_whitespace(row.get("Field of Education 1 Detailed Field")),
        _normalize_whitespace(row.get("Field of Education 2 Broad Field")),
        _normalize_whitespace(row.get("Field of Education 2 Narrow Field")),
        _normalize_whitespace(row.get("Field of Education 2 Detailed Field")),
    ]
    return " ".join(part.casefold() for part in parts if part)


def _popular_study_area(search_text):
    for area in settings.POPULAR_STUDY_AREAS:
        for keyword in area["keywords"]:
            if keyword.casefold() in search_text:
                return area["name"]
    return ""


def _parse_dataset_datetime(file_name):
    text = _clean(file_name).lower()
    if "as-at-" in text:
        text = text.split("as-at-", 1)[1]

    parts = []
    for token in text.replace("_", "-").replace("t", "-").replace(":", "-").split("-"):
        token = token.strip().removesuffix("z")
        if token.isdigit():
            parts.append(int(token))
        elif parts:
            break

    if len(parts) < 3:
        return None

    try:
        dt = datetime(
            parts[0],
            parts[1],
            parts[2],
            parts[3] if len(parts) > 3 else 0,
            parts[4] if len(parts) > 4 else 0,
            parts[5] if len(parts) > 5 else 0,
        )
    except ValueError:
        return None

    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _safe_file_name(value, default_extension):
    file_name = []
    for char in _clean(value):
        if char.isalnum() or char in "._-":
            file_name.append(char)
        else:
            file_name.append("-")
    file_name = "".join(file_name).strip("-")
    if not file_name:
        file_name = f"cricos{default_extension}"
    if not file_name.lower().endswith(default_extension):
        file_name = f"{file_name}{default_extension}"
    return file_name


def _resource_file_name(url, name, default_extension):
    parsed = urlparse(url)
    from_url = Path(unquote(parsed.path or "")).name
    if from_url:
        return _safe_file_name(from_url, default_extension=default_extension)
    return _safe_file_name(name or f"cricos{default_extension}", default_extension=default_extension)


def _resource_sort_datetime(resource, file_name):
    return (
        _parse_dataset_datetime(file_name)
        or _parse_dataset_datetime(_clean(resource.get("name")))
        or _parse_dataset_datetime(resource.get("description"))
        or _parse_dataset_datetime(resource.get("last_modified"))
        or _parse_dataset_datetime(resource.get("created"))
    )


def _read_csv_table(path, required_headers):
    with path.open("r", encoding="utf-8-sig", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")

        normalized_headers = [str(x).strip() for x in reader.fieldnames if str(x).strip()]
        header_set = set(normalized_headers)
        missing_required = [h for h in required_headers if h not in header_set]
        if missing_required:
            raise ValueError(f"CSV '{path.name}' missing required headers: {', '.join(missing_required)}")

        rows = []
        for row in reader:
            if not row:
                continue
            normalized_row = {str(k).strip(): _clean(v) for k, v in row.items() if k is not None}
            if not any(normalized_row.values()):
                continue
            rows.append(normalized_row)
        return rows


def _bulk_create_in_chunks(model_cls, objects, batch_size):
    for idx in range(0, len(objects), batch_size):
        model_cls.objects.bulk_create(objects[idx : idx + batch_size], batch_size=batch_size)


class Command(BasicCommand):
    help = "Import CRICOS data into database and optionally set imported dataset as current."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Bulk insert batch size (default: 2000)",
        )
        parser.add_argument(
            "--no-make-current",
            action="store_true",
            help="Import data but do not switch current dataset",
        )
        parser.add_argument(
            "--download-dir",
            default=".",
            help="Directory for downloaded CSV files (default: current directory)",
        )
        parser.add_argument(
            "--force-download",
            action="store_true",
            help="Download latest CSV files even if local dataset date appears up to date",
        )
        parser.add_argument(
            "--request-timeout",
            type=int,
            default=90,
            help="HTTP timeout in seconds for data.gov.au requests (default: 90)",
        )

    def _latest_local_dataset(self):
        return Dataset.objects.order_by("-dataset_datetime", "-imported_at").first()

    def _fetch_remote_csv_resources(self, timeout_seconds):
        payload = None
        last_error = None

        for dataset_id in DATA_GOV_DATASET_IDS:
            try:
                response = requests.get(
                    DATA_GOV_PACKAGE_SHOW_URL,
                    params={"id": dataset_id},
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0 (compatible; CRICOS-Importer/1.0)",
                    },
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = f"{dataset_id}: {exc}"
                continue

            try:
                data = response.json()
            except ValueError:
                last_error = f"{dataset_id}: non-JSON response"
                continue

            if data.get("success"):
                payload = data
                break

            last_error = f"{dataset_id}: success=false"

        if payload is None:
            raise CommandError(f"Failed to load CRICOS dataset metadata from data.gov.au ({last_error})")

        resources = payload.get("result", {}).get("resources", [])
        selected = {}

        for resource in resources:
            resource_name = _clean(resource.get("name"))
            if resource_name not in CSV_RESOURCE_NAMES.values():
                continue

            url = _clean(resource.get("url"))
            if not url:
                continue

            file_name = _resource_file_name(url, resource_name, default_extension=".csv")
            updated_at = (
                _resource_sort_datetime(resource, file_name)
                or timezone.make_aware(datetime(1970, 1, 1), timezone.get_current_timezone())
            )

            current = selected.get(resource_name)
            if not current or updated_at > current["updated_at"]:
                selected[resource_name] = {
                    "name": resource_name,
                    "url": url,
                    "id": _clean(resource.get("id")),
                    "file_name": file_name,
                    "updated_at": updated_at,
                    "hash": _clean(resource.get("hash")),
                }

        missing = [name for name in CSV_RESOURCE_NAMES.values() if name not in selected]
        if missing:
            raise CommandError(f"Missing CSV resources in data.gov.au package: {', '.join(missing)}")

        return selected

    def _remote_csv_bundle_fingerprint(self, resources):
        parts = []
        for name in sorted(resources):
            item = resources[name]
            parts.append(
                "|".join(
                    [
                        _clean(name),
                        _clean(item.get("id")),
                        _clean(item.get("url")),
                        _clean(item.get("hash")),
                        _clean(item.get("updated_at")),
                    ]
                )
            )
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def _download_remote_csv_bundle_if_needed(self, download_dir, timeout_seconds, force_download):
        resources = self._fetch_remote_csv_resources(timeout_seconds=timeout_seconds)
        latest_datetime = max(item["updated_at"] for item in resources.values())
        bundle_hash = self._remote_csv_bundle_fingerprint(resources)
        current_dataset = self._latest_local_dataset()

        if not force_download and current_dataset:
            if current_dataset.source_file_sha256 == bundle_hash:
                self.log("Latest CRICOS CSV bundle already imported (same metadata fingerprint).")
                return None
            if current_dataset.dataset_datetime and latest_datetime <= current_dataset.dataset_datetime:
                self.log("Local CRICOS dataset is already up to date by date.")
                return None

        download_dir.mkdir(parents=True, exist_ok=True)
        downloaded_files = {}

        for name in sorted(resources):
            resource = resources[name]
            download_path = download_dir / resource["file_name"]
            temp_path = download_path.with_suffix(download_path.suffix + ".part")
            try:
                with requests.get(resource["url"], stream=True, timeout=timeout_seconds) as response:
                    response.raise_for_status()
                    with temp_path.open("wb") as file_handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                file_handle.write(chunk)
            except requests.RequestException as exc:
                raise CommandError(f"Failed to download CSV '{name}' from data.gov.au: {exc}") from exc

            temp_path.replace(download_path)
            downloaded_files[name] = download_path

        self.log("Downloaded CRICOS CSV bundle to: %s", download_dir)
        return {
            "files": downloaded_files,
            "dataset_datetime": latest_datetime,
            "source_file_name": f"cricos-csv-bundle-{latest_datetime.strftime('%Y-%m-%d')}",
            "source_file_sha256": bundle_hash,
        }

    def handle(self, *args, **options):
        super().handle(*args, **options)

        request_timeout = max(int(options["request_timeout"]), 10)
        force_download = bool(options["force_download"])

        download_dir = Path(options["download_dir"]).expanduser().resolve()
        self.log("Checking latest CRICOS CSV bundle")
        csv_bundle = self._download_remote_csv_bundle_if_needed(
            download_dir=download_dir,
            timeout_seconds=request_timeout,
            force_download=force_download,
        )
        if csv_bundle is None:
            return

        files = csv_bundle["files"]
        self.log("Reading CSV files from data.gov.au")
        institutions = _read_csv_table(
            files["CRICOS Institutions.csv"],
            required_headers=("CRICOS Provider Code", "Institution Name"),
        )
        courses = _read_csv_table(
            files["CRICOS Courses.csv"],
            required_headers=("CRICOS Provider Code", "CRICOS Course Code", "Course Name"),
        )
        locations = _read_csv_table(
            files["CRICOS Locations.csv"],
            required_headers=("CRICOS Provider Code", "Location Name", "City"),
        )
        course_locations = _read_csv_table(
            files["CRICOS Course Locations.csv"],
            required_headers=("CRICOS Provider Code", "CRICOS Course Code", "Location City"),
        )

        source_file_name = csv_bundle["source_file_name"]
        source_file_sha256 = csv_bundle["source_file_sha256"]
        dataset_datetime = csv_bundle["dataset_datetime"]

        batch_size = max(int(options["batch_size"]), 100)
        make_current = not bool(options["no_make_current"])
        existing_dataset = Dataset.objects.filter(source_file_sha256=source_file_sha256).first()

        if existing_dataset:
            self.log(
                f"Dataset with same file hash already exists (id={existing_dataset.id}, file={existing_dataset.source_file_name})."
            )
            if make_current and not existing_dataset.is_current:
                with transaction.atomic():
                    Dataset.objects.filter(is_current=True).exclude(pk=existing_dataset.pk).update(is_current=False)
                    existing_dataset.is_current = True
                    existing_dataset.save(update_fields=["is_current"])
                self.log("Existing dataset marked as current.")
            return

        self.log("Preparing import data")
        city_name_map = _build_city_name_map(locations=locations, course_locations=course_locations)
        total_courses_by_provider = {}
        active_courses_by_provider = {}
        campuses_by_provider = {}
        cities_by_provider = {}
        states_by_provider = {}
        campuses_by_course = {}

        for row in courses:
            provider_code = _clean(row.get("CRICOS Provider Code")).upper()
            course_code = _clean(row.get("CRICOS Course Code")).upper()
            if not provider_code or not course_code:
                continue
            total_courses_by_provider[provider_code] = total_courses_by_provider.get(provider_code, 0) + 1
            if not _as_bool(row.get("Expired")):
                active_courses_by_provider[provider_code] = active_courses_by_provider.get(provider_code, 0) + 1

        for row in locations:
            provider_code = _clean(row.get("CRICOS Provider Code")).upper()
            if not provider_code:
                continue
            campuses_by_provider[provider_code] = campuses_by_provider.get(provider_code, 0) + 1

            city = _canonical_city(row.get("City"), city_name_map)
            state = _clean(row.get("State")).upper()
            if city:
                cities_by_provider.setdefault(provider_code, set()).add(city)
            if state:
                states_by_provider.setdefault(provider_code, set()).add(state)

        for row in course_locations:
            provider_code = _clean(row.get("CRICOS Provider Code")).upper()
            course_code = _clean(row.get("CRICOS Course Code")).upper()
            if not provider_code or not course_code:
                continue
            key = (provider_code, course_code)
            campuses_by_course[key] = campuses_by_course.get(key, 0) + 1

        self.log("Writing dataset to database")
        with transaction.atomic():
            dataset = Dataset.objects.create(
                source_file_name=source_file_name,
                source_file_sha256=source_file_sha256,
                dataset_datetime=dataset_datetime,
                is_current=False,
            )

            institution_objs = []
            for row in institutions:
                provider_code = _clean(row.get("CRICOS Provider Code")).upper()
                if not provider_code:
                    continue
                institution_objs.append(
                    Institution(
                        dataset=dataset,
                        provider_code=provider_code,
                        institution_name=_clean(row.get("Institution Name")),
                        active_courses_count=active_courses_by_provider.get(provider_code, 0),
                        total_courses_count=total_courses_by_provider.get(provider_code, 0),
                        campuses_count=campuses_by_provider.get(provider_code, 0),
                        cities_count=len(cities_by_provider.get(provider_code, set())),
                        states_count=len(states_by_provider.get(provider_code, set())),
                        trading_name=_clean(row.get("Trading Name")),
                        institution_type=_clean(row.get("Institution Type")),
                        institution_capacity=_as_positive_int(row.get("Institution Capacity")),
                        website=_clean(row.get("Website")),
                        postal_address_line_1=_clean(row.get("Postal Address Line 1")),
                        postal_address_line_2=_clean(row.get("Postal Address Line 2")),
                        postal_address_line_3=_clean(row.get("Postal Address Line 3")),
                        postal_address_line_4=_clean(row.get("Postal Address Line 4")),
                        postal_city=_clean(row.get("Postal Address City")),
                        postal_state=_clean(row.get("Postal Address State")),
                        postal_postcode=_clean(row.get("Postal Address Postcode")),
                    )
                )
            _bulk_create_in_chunks(Institution, institution_objs, batch_size)
            institution_map = {}
            for item in Institution.objects.filter(dataset=dataset):
                code = _clean(item.provider_code).upper()
                if code and code not in institution_map:
                    institution_map[code] = item

            course_objs = []
            for row in courses:
                provider_code = _clean(row.get("CRICOS Provider Code")).upper()
                course_code = _clean(row.get("CRICOS Course Code")).upper()
                if not provider_code or not course_code:
                    continue
                search_text = _course_search_text(row)
                course_objs.append(
                    Course(
                        dataset=dataset,
                        institution=institution_map.get(provider_code),
                        provider_code=provider_code,
                        course_code=course_code,
                        institution_name=_clean(row.get("Institution Name")),
                        course_name=_clean(row.get("Course Name")),
                        search_text=search_text,
                        popular_study_area=_popular_study_area(search_text),
                        campuses_count=campuses_by_course.get((provider_code, course_code), 0),
                        vet_national_code=_clean(row.get("VET National Code")),
                        dual_qualification=_clean(row.get("Dual Qualification")),
                        course_level=_clean(row.get("Course Level")),
                        foundation_studies=_clean(row.get("Foundation Studies")),
                        work_component=_clean(row.get("Work Component")),
                        work_component_hours_per_week=_as_decimal(row.get("Work Component Hours/Week")),
                        work_component_weeks=_as_int(row.get("Work Component Weeks")),
                        work_component_total_hours=_as_int(row.get("Work Component Total Hours")),
                        course_language=_clean(row.get("Course Language")),
                        duration_weeks=_as_decimal(row.get("Duration (Weeks)")),
                        tuition_fee=_as_decimal(row.get("Tuition Fee")),
                        non_tuition_fee=_as_decimal(row.get("Non Tuition Fee")),
                        estimated_total_course_cost=_as_decimal(row.get("Estimated Total Course Cost")),
                        field_1_broad=_clean(row.get("Field of Education 1 Broad Field")),
                        field_1_narrow=_clean(row.get("Field of Education 1 Narrow Field")),
                        field_1_detailed=_clean(row.get("Field of Education 1 Detailed Field")),
                        field_2_broad=_clean(row.get("Field of Education 2 Broad Field")),
                        field_2_narrow=_clean(row.get("Field of Education 2 Narrow Field")),
                        field_2_detailed=_clean(row.get("Field of Education 2 Detailed Field")),
                        expired=_as_bool(row.get("Expired")),
                    )
                )
            _bulk_create_in_chunks(Course, course_objs, batch_size)
            course_map = {}
            for item in Course.objects.filter(dataset=dataset):
                key = (_clean(item.provider_code).upper(), _clean(item.course_code).upper())
                if key[0] and key[1] and key not in course_map:
                    course_map[key] = item

            location_objs = []
            for row in locations:
                provider_code = _clean(row.get("CRICOS Provider Code")).upper()
                if not provider_code:
                    continue
                location_objs.append(
                    Location(
                        dataset=dataset,
                        institution=institution_map.get(provider_code),
                        provider_code=provider_code,
                        institution_name=_clean(row.get("Institution Name")),
                        location_name=_clean(row.get("Location Name")),
                        location_type=_clean(row.get("Location Type")),
                        address_line_1=_clean(row.get("Address Line 1")),
                        address_line_2=_clean(row.get("Address Line 2")),
                        address_line_3=_clean(row.get("Address Line 3")),
                        address_line_4=_clean(row.get("Address Line 4")),
                        city=_canonical_city(row.get("City"), city_name_map),
                        state=_clean(row.get("State")),
                        postcode=_clean(row.get("Postcode")),
                    )
                )
            _bulk_create_in_chunks(Location, location_objs, batch_size)
            location_map = {}
            for item in Location.objects.filter(dataset=dataset):
                location_name = _clean(item.location_name).lower()
                key = (_clean(item.provider_code).upper(), location_name)
                if key[0] and key[1] and key not in location_map:
                    location_map[key] = item

            course_location_objs = []
            for row in course_locations:
                provider_code = _clean(row.get("CRICOS Provider Code")).upper()
                course_code = _clean(row.get("CRICOS Course Code")).upper()
                if not provider_code or not course_code:
                    continue
                location_name = _clean(row.get("Location Name"))
                course_location_objs.append(
                    CourseLocation(
                        dataset=dataset,
                        course=course_map.get((provider_code, course_code)),
                        location=location_map.get((provider_code, location_name.lower())) if location_name else None,
                        provider_code=provider_code,
                        course_code=course_code,
                        institution_name=_clean(row.get("Institution Name")),
                        location_name=location_name,
                        location_city=_canonical_city(row.get("Location City"), city_name_map),
                        location_state=_clean(row.get("Location State")),
                    )
                )
            _bulk_create_in_chunks(CourseLocation, course_location_objs, batch_size)

            dataset.institutions_count = len(institution_objs)
            dataset.courses_count = len(course_objs)
            dataset.locations_count = len(location_objs)
            dataset.course_locations_count = len(course_location_objs)

            if make_current:
                Dataset.objects.filter(is_current=True).exclude(pk=dataset.pk).update(is_current=False)
                dataset.is_current = True

            dataset.save(
                update_fields=[
                    "institutions_count",
                    "courses_count",
                    "locations_count",
                    "course_locations_count",
                    "is_current",
                ]
            )

        self.log(
            "Dataset id=%s, current=%s, institutions=%s, courses=%s, locations=%s, course_locations=%s",
            dataset.id,
            dataset.is_current,
            dataset.institutions_count,
            dataset.courses_count,
            dataset.locations_count,
            dataset.course_locations_count,
        )
        self.log("CRICOS import completed")
