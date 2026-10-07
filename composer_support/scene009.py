"""Restored Scene Engine 009 control module. Downstream only."""
from __future__ import annotations
import math
ENGINE_ID="AI_COMP_3D_SPATIALIZATION_SCENE_ENGINE_009_RESTORED"
COORDINATE_SYSTEM="AI3D_C1"
MODES={"OBJECT","FIELD","HYBRID"}
INTERPOLATIONS={"HOLD","LINEAR","SMOOTH"}
class Scene009Error(ValueError): pass
def _unit(v,name):
    v=float(v)
    if not 0.0 <= v <= 1.0: raise Scene009Error(f"INVALID_0_1:{name}")
    return v
def _position(p):
    if not isinstance(p,dict): raise Scene009Error("INCOMPLETE_POSITION")
    if all(k in p for k in ("x","y","z")):
        return {"x":float(p["x"]),"y":float(p["y"]),"z":float(p["z"])}
    if all(k in p for k in ("azimuth_deg","elevation_deg","distance_m")):
        az=math.radians(float(p["azimuth_deg"])); el=math.radians(float(p["elevation_deg"])); d=float(p["distance_m"])
        if d < 0: raise Scene009Error("INVALID_DISTANCE")
        return {"x":d*math.cos(el)*math.sin(az),"y":d*math.cos(el)*math.cos(az),"z":d*math.sin(el)}
    raise Scene009Error("INCOMPLETE_POSITION")
def _extent(e):
    e=e or {}; out={k:float(e.get(k,0.0)) for k in ("width_m","height_m","depth_m")}
    if any(v<0 for v in out.values()): raise Scene009Error("NEGATIVE_EXTENT")
    out["diffuseness"]=_unit(e.get("diffuseness",0.0),"diffuseness"); return out
def _environment(e):
    e=e or {}
    return {"room_id":e.get("room_id"),"direct_gain":_unit(e.get("direct_gain",1.0),"direct_gain"),
            "early_reflection_send":_unit(e.get("early_reflection_send",0.0),"early_reflection_send"),
            "reverb_send":_unit(e.get("reverb_send",0.0),"reverb_send")}
def _movement(m):
    if not m: return None
    interp=str(m.get("interpolation","HOLD")).upper()
    if interp not in INTERPOLATIONS: raise Scene009Error("UNKNOWN_MOVEMENT_INTERPOLATION")
    keys=m.get("keyframes") or []; last=-float("inf"); out=[]
    for k in keys:
        t=float(k["time_seconds"])
        if t <= last: raise Scene009Error("NON_MONOTONIC_MOVEMENT")
        last=t; out.append({"time_seconds":t,"position":_position(k["position"])})
    return {"interpolation":interp,"keyframes":out}
def compile_scene(sources,listener,scene_id="AI_COMP_SCENE_009",legacy_profile_reference=None,derivatives=("stereo","binaural","multichannel")):
    if not sources: raise Scene009Error("EMPTY_SCENE")
    if not listener: raise Scene009Error("MISSING_LISTENER")
    lp=_position(listener.get("position") or {}); orient=listener.get("orientation") or {}
    listener_out={"position":lp,"orientation":{"yaw_deg":float(orient.get("yaw_deg",0)),"pitch_deg":float(orient.get("pitch_deg",0)),"roll_deg":float(orient.get("roll_deg",0))}}
    ids=set(); compiled=[]
    for s in sources:
        sid=s.get("source_id")
        if not sid: raise Scene009Error("MISSING_SOURCE_ID")
        if sid in ids: raise Scene009Error("DUPLICATE_SOURCE_ID")
        ids.add(sid); audio=s.get("audio_ref")
        if not audio: raise Scene009Error("NO_SOURCE_AUDIO")
        mode=str(s.get("mode","OBJECT")).upper()
        if mode not in MODES: raise Scene009Error("UNKNOWN_SOURCE_MODE")
        ext=_extent(s.get("extent")); physical_extent=ext["width_m"]+ext["height_m"]+ext["depth_m"]
        if mode=="FIELD" and physical_extent<=0: raise Scene009Error("ZERO_EXTENT_FIELD")
        if mode=="HYBRID" and ext["diffuseness"]<=0: raise Scene009Error("NON_DIFFUSE_HYBRID")
        compiled.append({"source_id":sid,"audio_ref":audio,"instrument_id":s.get("instrument_id"),"role":s.get("role"),
                         "mode":mode,"position":_position(s.get("position") or {}),"extent":ext,
                         "environment":_environment(s.get("environment")),"prominence":s.get("prominence"),
                         "provenance":s.get("provenance"),"movement":_movement(s.get("movement"))})
    return {"status":"PASS_SCENE_009","engine_id":ENGINE_ID,"coordinate_system":COORDINATE_SYSTEM,
            "scene_id":scene_id,"listener":listener_out,"sources":compiled,"source_stems_preserved":True,
            "legacy_profile_reference":legacy_profile_reference,
            "downstream_master_contract":"OBJECT_BASED_3D_MASTER_006_OR_COMPATIBLE_SUCCESSOR",
            "derivatives":[{"type":d,"authoritative_master":False} for d in derivatives],
            "authoritative_state":"3D_SCENE_AND_DOWNSTREAM_OBJECT_MASTER",
            "renderer_boundary":"NO_HRTF_AMBISONIC_PROPRIETARY_ENCODING_OR_SPEAKER_DSP_IN_ENGINE_009"}