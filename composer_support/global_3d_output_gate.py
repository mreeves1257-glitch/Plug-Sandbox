REQUIRED_SPATIAL_KEYS={"azimuth","elevation","distance","source_identity"}
ACCEPTED_MASTER_TYPES={"object_scene","ambisonic","immersive_equivalent"}
def validate_final_audio_output(manifest):
    errors=[]
    if manifest.get("output_kind")!="audible_final": return {"status":"NOT_FINAL_AUDIO_GATE","compliant":True,"errors":[]}
    if not manifest.get("has_3d_master",False): errors.append("missing authoritative 3D master")
    if manifest.get("master_type") not in ACCEPTED_MASTER_TYPES: errors.append("master type is not an accepted 3D representation")
    objects=manifest.get("spatial_objects",[])
    if not objects: errors.append("no spatial objects supplied")
    else:
        for i,obj in enumerate(objects):
            missing=REQUIRED_SPATIAL_KEYS-set(obj)
            if missing: errors.append(f"spatial object {i} missing: {', '.join(sorted(missing))}")
    derivative=manifest.get("derivative_type")
    if derivative in {"stereo","binaural","multichannel"} and not manifest.get("parent_3d_master_id"):
        errors.append("playback derivative is not traceable to a parent 3D master")
    if derivative=="mono": errors.append("mono is not permitted as final audible output")
    return {"status":"PASS" if not errors else "FAIL","compliant":not errors,"errors":errors}