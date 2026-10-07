from __future__ import annotations
from pathlib import Path
import hashlib,json,math,wave
import numpy as np
from scene009 import compile_scene
from master006 import build_object_master,sha256_file
from global_3d_output_gate import validate_final_audio_output

ROCK_PAN={"BASS":0.0,"KICK":0.0,"SNARE":0.02,"HARMONY":-0.28,"LEAD":0.24,"HAT":0.34,"CRASH":0.34,"TOMS":0.10}

def _pcm_to_float(raw,width,channels):
    if width==1:
        a=(np.frombuffer(raw,dtype=np.uint8).astype(np.float32)-128.0)/128.0
    elif width==2:
        a=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768.0
    elif width==3:
        b=np.frombuffer(raw,dtype=np.uint8)
        if len(b)%3: raise ValueError("PCM24_FRAME_ALIGNMENT")
        b=b.reshape(-1,3).astype(np.int32); a=b[:,0]|(b[:,1]<<8)|(b[:,2]<<16)
        a=((a^0x800000)-0x800000).astype(np.float32)/8388608.0
    elif width==4:
        a=np.frombuffer(raw,dtype="<i4").astype(np.float32)/2147483648.0
    else: raise ValueError("UNSUPPORTED_PCM_WIDTH:"+str(width))
    if channels<1 or len(a)%channels: raise ValueError("INVALID_CHANNEL_LAYOUT")
    return a.reshape(-1,channels).mean(axis=1)

def _read_mono(path):
    with wave.open(str(path),"rb") as w:
        channels=w.getnchannels(); width=w.getsampwidth(); rate=w.getframerate(); frames=w.getnframes(); raw=w.readframes(frames)
    return rate,_pcm_to_float(raw,width,channels)

def _write_stereo(path,stereo,sr):
    path.parent.mkdir(parents=True,exist_ok=True)
    if stereo.ndim!=2 or stereo.shape[1]!=2: raise ValueError("STEREO_REQUIRED")
    if not np.isfinite(stereo).all(): raise ValueError("NONFINITE_AUDIO")
    peak=float(np.max(np.abs(stereo))) if stereo.size else 0.0
    if peak<=0 or peak>=1.0: raise ValueError("INVALID_OR_CLIPPING_AUDIO")
    pcm=np.clip(stereo*32767.0,-32768,32767).astype("<i2")
    with wave.open(str(path),"wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())

def finalize_spatial_master(engine_result,output_root):
    render=engine_result.get("audio_render") or {}; stems=render.get("stems") or []
    if render.get("status")!="AUDIO_STEMS_READY_MASTER_REQUIRED" or not stems: raise ValueError("SOURCE_STEMS_REQUIRED")
    output_root=Path(output_root).resolve(); output_root.mkdir(parents=True,exist_ok=True)
    package=(engine_result.get("output_handoff") or {}).get("source_package_id") or "COMPOSITION"
    directory=output_root/package/"final_master"; directory.mkdir(parents=True,exist_ok=True)
    profiles={p["track_id"]:p for p in engine_result["modules"]["instrument"].get("profiles",[]) if p.get("track_id")}
    sources=[]; source_audio=[]; sample_rate=None; max_frames=0
    for stem in stems:
        track=str(stem["track_id"]); path=Path(stem["wav_path"]).resolve()
        if not path.is_file(): raise ValueError("SOURCE_STEM_MISSING:"+track)
        rate,mono=_read_mono(path)
        if sample_rate is None: sample_rate=rate
        elif rate!=sample_rate: raise ValueError("SOURCE_SAMPLE_RATE_MISMATCH")
        max_frames=max(max_frames,len(mono)); source_audio.append((track,path,mono))
        profile=profiles.get(track,{}); pan=ROCK_PAN.get(track,0.0) if str(engine_result.get("genre","")).upper()=="ROCK" else 0.0
        az=pan*math.pi/2
        sources.append({"source_id":track,"audio_ref":str(path),"instrument_id":stem.get("instrument_id"),"role":profile.get("role"),
                        "mode":"OBJECT","position":{"x":math.sin(az),"y":math.cos(az),"z":0.0},
                        "extent":{"width_m":0,"height_m":0,"depth_m":0,"diffuseness":0},
                        "environment":{"direct_gain":1,"early_reflection_send":0,"reverb_send":0},
                        "provenance":{"audio_sha256":sha256_file(path),"renderer":"SFIZZ_RENDER",
                                      "resource_id":stem.get("resource_id"),"sfz_path":stem.get("sfz_path"),
                                      "fallback_policy":"NO_SYNTHETIC_SUBSTITUTION"}})
    if not sample_rate or max_frames<=0: raise ValueError("NO_SOURCE_AUDIO")
    scene=compile_scene(sources,{"position":{"x":0.0,"y":0.0,"z":0.0}},scene_id=package,derivatives=("stereo",))
    master=build_object_master(scene,represented_note_events=len(engine_result["modules"]["performance"].get("events",[])),production_resource_ready=True)
    master["master_id"]="AI_COMP_3D_OBJECT_MASTER_006__"+package
    master_path=directory/"object_master.json"; scene_path=directory/"scene.json"
    master_path.write_text(json.dumps(master,indent=2),encoding="utf-8"); scene_path.write_text(json.dumps(scene,indent=2),encoding="utf-8")
    stereo=np.zeros((max_frames,2),dtype=np.float32); source_map={o["source_id"]:o for o in master["audio_objects"]}; objects=[]
    for track,path,mono in source_audio:
        obj=source_map[track]
        if sha256_file(path)!=obj["audio_sha256"]: raise ValueError("SOURCE_AUDIO_CHANGED_AFTER_MASTER")
        p=obj["position"]; az=math.atan2(p["x"],p["y"]); pan=max(-1.0,min(1.0,az/(math.pi/2))); angle=(pan+1.0)*math.pi/4.0
        n=len(mono); stereo[:n,0]+=mono*math.cos(angle); stereo[:n,1]+=mono*math.sin(angle)
        objects.append({"source_identity":track,"azimuth":math.degrees(az),
                        "elevation":math.degrees(math.atan2(p["z"],math.hypot(p["x"],p["y"]))),
                        "distance":math.sqrt(sum(v*v for v in p.values()))})
    stereo-=np.mean(stereo,axis=0,keepdims=True); peak=float(np.max(np.abs(stereo)))
    if peak<=0 or not math.isfinite(peak): raise ValueError("SILENT_OR_INVALID_DERIVATIVE")
    stereo*=float(10**(-1/20))/peak
    derivative=directory/"stereo_derivative.wav"; _write_stereo(derivative,stereo,sample_rate)
    manifest={"output_kind":"audible_final","has_3d_master":True,"master_type":"object_scene","spatial_objects":objects,
              "derivative_type":"stereo","parent_3d_master_id":master["master_id"],"authoritative_master":False,
              "master_path":str(master_path),"scene_path":str(scene_path),"resource_quality":"REAL_OPEN_SAMPLE_LIBRARIES",
              "decoder":"SEPT27_EQUAL_POWER_STEREO","events":master["represented_note_events"],"source_count":len(stems),
              "channels":2,"sample_rate":sample_rate,"duration_seconds":max_frames/sample_rate}
    manifest["global_3d_gate"]=validate_final_audio_output(manifest)
    if not manifest["global_3d_gate"]["compliant"]: raise ValueError("GLOBAL_3D_GATE_FAILED")
    manifest["derivative_sha256"]=hashlib.sha256(derivative.read_bytes()).hexdigest()
    manifest_path=directory/"output_manifest.json"; manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return {"status":"AUDIO_RENDER_PASS","audio_rendered":True,"wav_path":str(derivative),
            "parent_3d_master_id":master["master_id"],"master_path":str(master_path),"scene_path":str(scene_path),
            "manifest_path":str(manifest_path),"source_stems":stems,"production_resource_ready":True}