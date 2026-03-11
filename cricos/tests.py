import csv
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from cricos.management.commands import import_cricos
from cricos.models import Course, CourseLocation, Dataset, Institution, Location


class ImportCricosCommandTests(TestCase):
    def _write_csv(self, path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    def test_import_normalizes_city_case_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            institutions_path = temp_path / "institutions.csv"
            courses_path = temp_path / "courses.csv"
            locations_path = temp_path / "locations.csv"
            course_locations_path = temp_path / "course_locations.csv"

            self._write_csv(
                institutions_path,
                ["CRICOS Provider Code", "Institution Name", "Institution Capacity"],
                [
                    {
                        "CRICOS Provider Code": "00001K",
                        "Institution Name": "Test Institute",
                        "Institution Capacity": "2,610",
                    }
                ],
            )
            self._write_csv(
                courses_path,
                [
                    "CRICOS Provider Code",
                    "CRICOS Course Code",
                    "Course Name",
                    "Institution Name",
                    "Field of Education 1 Broad Field",
                    "Work Component Hours/Week",
                    "Work Component Weeks",
                    "Work Component Total Hours",
                    "Duration (Weeks)",
                    "Tuition Fee",
                    "Non Tuition Fee",
                    "Estimated Total Course Cost",
                    "Expired",
                ],
                [
                    {
                        "CRICOS Provider Code": "00001K",
                        "CRICOS Course Code": "123456A",
                        "Course Name": "Test Course",
                        "Institution Name": "Test Institute",
                        "Field of Education 1 Broad Field": "Business and Management",
                        "Work Component Hours/Week": "10.00",
                        "Work Component Weeks": "12",
                        "Work Component Total Hours": "120",
                        "Duration (Weeks)": "44",
                        "Tuition Fee": "$13,300.00",
                        "Non Tuition Fee": "$150.00",
                        "Estimated Total Course Cost": "$13,450.00",
                        "Expired": "Yes",
                    }
                ],
            )
            self._write_csv(
                locations_path,
                ["CRICOS Provider Code", "Institution Name", "Location Name", "City", "State", "Postcode"],
                [
                    {
                        "CRICOS Provider Code": "00001K",
                        "Institution Name": "Test Institute",
                        "Location Name": "Campus Upper",
                        "City": "ABBOTSFORD",
                        "State": "VIC",
                        "Postcode": "3067",
                    },
                    {
                        "CRICOS Provider Code": "00001K",
                        "Institution Name": "Test Institute",
                        "Location Name": "Campus Title",
                        "City": "Abbotsford",
                        "State": "VIC",
                        "Postcode": "3067",
                    },
                ],
            )
            self._write_csv(
                course_locations_path,
                [
                    "CRICOS Provider Code",
                    "CRICOS Course Code",
                    "Institution Name",
                    "Location Name",
                    "Location City",
                    "Location State",
                ],
                [
                    {
                        "CRICOS Provider Code": "00001K",
                        "CRICOS Course Code": "123456A",
                        "Institution Name": "Test Institute",
                        "Location Name": "Campus Upper",
                        "Location City": "ABBOTSFORD",
                        "Location State": "VIC",
                    },
                    {
                        "CRICOS Provider Code": "00001K",
                        "CRICOS Course Code": "123456A",
                        "Institution Name": "Test Institute",
                        "Location Name": "Campus Title",
                        "Location City": "Abbotsford",
                        "Location State": "VIC",
                    },
                ],
            )

            csv_bundle = {
                "files": {
                    "CRICOS Institutions.csv": institutions_path,
                    "CRICOS Courses.csv": courses_path,
                    "CRICOS Locations.csv": locations_path,
                    "CRICOS Course Locations.csv": course_locations_path,
                },
                "dataset_datetime": timezone.now(),
                "source_file_name": "test-csv-bundle",
                "source_file_sha256": "test-csv-bundle-sha256",
            }

            with patch.object(
                import_cricos.Command,
                "_download_remote_csv_bundle_if_needed",
                return_value=csv_bundle,
            ):
                call_command("import_cricos", download_dir=temp_dir)

        self.assertEqual(set(Location.objects.values_list("city", flat=True)), {"Abbotsford"})
        self.assertEqual(set(CourseLocation.objects.values_list("location_city", flat=True)), {"Abbotsford"})
        course = Course.objects.get()
        self.assertTrue(course.expired)
        self.assertIn("test course", course.search_text)
        self.assertEqual(course.popular_study_area, "Business")
        self.assertEqual(course.work_component_hours_per_week, Decimal("10.00"))
        self.assertEqual(course.work_component_weeks, 12)
        self.assertEqual(course.work_component_total_hours, 120)
        self.assertEqual(course.duration_weeks, Decimal("44"))
        self.assertEqual(course.tuition_fee, Decimal("13300.00"))
        self.assertEqual(course.non_tuition_fee, Decimal("150.00"))
        self.assertEqual(course.estimated_total_course_cost, Decimal("13450.00"))
        self.assertEqual(course.campuses_count, 2)
        institution = Institution.objects.get()
        self.assertEqual(institution.institution_capacity, 2610)
        self.assertEqual(institution.active_courses_count, 0)
        self.assertEqual(institution.total_courses_count, 1)
        self.assertEqual(institution.campuses_count, 2)
        self.assertEqual(institution.cities_count, 1)
        self.assertEqual(institution.states_count, 1)

        dataset = Dataset.objects.get()
        self.assertEqual(dataset.locations_count, 2)
        self.assertEqual(dataset.course_locations_count, 2)
