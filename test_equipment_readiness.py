import copy
import json
import unittest
from equipment_readiness import preparation_status, ROOT


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'equipment-preparation.json').read_text())

    def test_reports_prepared_templates_without_physical_readiness(self):
        status = preparation_status(self.manifest)
        self.assertEqual(status['equipment_template_count'], 24)
        self.assertEqual(len(status['file_routes']), 3)
        self.assertFalse(status['physical_hardware_connected'])
        self.assertEqual(status['live_driver_count'], 0)

    def test_duplicate_profile_rejected(self):
        self.manifest['equipment_profiles'].append(copy.deepcopy(self.manifest['equipment_profiles'][0]))
        with self.assertRaises(ValueError):
            preparation_status(self.manifest)

    def test_missing_channel_template_rejected(self):
        self.manifest['equipment_profiles'][0]['metadata_template']['channels'] = []
        with self.assertRaises(ValueError):
            preparation_status(self.manifest)

    def test_template_cannot_claim_driver_connection_or_validity(self):
        for key in ('driver_installed', 'hardware_connected', 'physical_readiness', 'scientific_validity_established'):
            altered = copy.deepcopy(self.manifest)
            altered['equipment_profiles'][0][key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                preparation_status(altered)

    def test_unimplemented_file_route_rejected(self):
        self.manifest['available_import_routes'][0]['adapter_id'] = 'unimplemented-driver'
        with self.assertRaises(ValueError):
            preparation_status(self.manifest)

    def test_missing_connection_template_rejected(self):
        del self.manifest['equipment_profiles'][0]['connection']
        with self.assertRaises(ValueError):
            preparation_status(self.manifest)
