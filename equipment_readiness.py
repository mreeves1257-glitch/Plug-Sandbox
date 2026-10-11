"""Inspect software preparation without claiming physical equipment readiness."""
import json
from pathlib import Path

from science_plug import FileImportAdapter
from recording_adapters import WavFileAdapter, CsvFileAdapter

ROOT = Path(__file__).resolve().parent


def preparation_status(manifest=None):
    if manifest is None:
        manifest = json.loads((ROOT / 'equipment-preparation.json').read_text())
    profiles = manifest.get('equipment_profiles')
    if not isinstance(profiles, list) or not profiles:
        raise ValueError('Equipment profiles are required')
    seen = set()
    equipment = []
    for profile in profiles:
        identifier = profile.get('profile_id')
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError('Equipment profile IDs must be nonempty and unique')
        seen.add(identifier)
        metadata = profile.get('metadata_template')
        if not isinstance(metadata, dict) or not isinstance(metadata.get('channels'), list) or not metadata['channels']:
            raise ValueError('A channel metadata template is required')
        if any(profile.get(key) is not False for key in ('driver_installed', 'hardware_connected', 'physical_readiness', 'scientific_validity_established')):
            raise ValueError('This preparation manifest cannot activate or certify physical equipment')
        connection = profile.get('connection')
        if not isinstance(connection, dict) or 'adapter_id' not in connection:
            raise ValueError('A model-specific connection template is required')
        equipment.append(dict(profile_id=identifier, label=profile.get('label'),
            state='TEMPLATE PREPARED / PHYSICAL INTEGRATION PENDING',
            driver_installed=False, hardware_connected=False, physical_readiness=False))
    adapters = [FileImportAdapter, WavFileAdapter, CsvFileAdapter]
    declared = manifest.get('available_import_routes', [])
    if {item.get('adapter_id') for item in declared} != {adapter.adapter_id for adapter in adapters}:
        raise ValueError('Declared file routes do not match the implemented adapters')
    return dict(project='Sound, Vibration, Pattern & Consciousness', parent='Science-Sandbox',
        state='SOFTWARE PREPARED / EXTERNAL EQUIPMENT PENDING',
        file_routes=[dict(adapter_id=adapter.adapter_id, version=adapter.version,
            state='IMPLEMENTED FILE IMPORT') for adapter in adapters],
        equipment_template_count=len(equipment), equipment=equipment,
        physical_hardware_connected=False, live_driver_count=0,
        scientific_validity_established=False,
        remaining_physical_checks=manifest.get('activation_checks', []))


if __name__ == '__main__':
    print(json.dumps(preparation_status(), indent=2))
