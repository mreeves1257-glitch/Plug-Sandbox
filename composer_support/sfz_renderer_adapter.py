#!/usr/bin/env python3
"""External SFZ renderer boundary for AI Composition - Sandbox.
Resolves approved sample resources and never synthesizes/substitutes timbre.
"""
from __future__ import annotations
from pathlib import Path
import os, re, shutil, subprocess, wave, math

class SFZRendererError(RuntimeError): pass

RESOURCE_ENV = 'AI_COMP_RESOURCE_BANK'
RENDERER_ENV = 'AI_COMP_SFZ_RENDERER'


def _candidate_roots():
    seen=set()
    for raw in (os.environ.get(RESOURCE_ENV), str(Path(__file__).resolve().parent/'sound_resources'), str(Path(__file__).resolve().parent/'resources'), str(Path(__file__).resolve().parent.parent/'Sound Resource Bank')):
        if not raw: continue
        p=Path(raw).expanduser().resolve()
        if p not in seen:
            seen.add(p); yield p


def resolve_sfz(resource: dict) -> Path:
    mapping=resource.get('preferred_mapping')
    if resource.get('resource_type')!='SFZ_SAMPLE_LIBRARY' or not mapping:
        raise SFZRendererError('SFZ_RESOURCE_DECLARATION_INVALID')
    for root in _candidate_roots():
        direct=root/mapping
        if direct.is_file(): return direct
        rid=resource.get('resource_id','')
        for rel in (rid, 'Growlybass', 'Karoryfer.Growlybass.v1.002', 'Karoryfer Growlybass'):
            p=root/rel/mapping
            if p.is_file(): return p
    raise SFZRendererError(f"SFZ_RESOURCE_NOT_INSTALLED:{resource.get('resource_id')}:{mapping}")


def validate_sfz_samples(sfz_path: Path) -> dict:
    """Validate SFZ sample references, including nested #include files and default_path.

    Validation is deliberately read-only: it proves that the declared sample graph exists;
    it does not rewrite mappings or substitute timbres.
    """
    visited=set(); refs=[]; missing=[]

    def walk(path: Path, inherited_default: Path|None=None):
        path=path.resolve()
        if path in visited:
            return
        if not path.is_file():
            missing.append('INCLUDE:'+str(path)); return
        visited.add(path)
        text=path.read_text(errors='strict')
        text=re.sub(r'//[^\n]*', '', text)
        default=inherited_default
        dm=re.search(r'(?:^|\s)default_path=([^\s<]+)', text)
        if dm:
            raw=dm.group(1).strip().strip('"').replace('\\','/')
            default=(path.parent/raw).resolve()
        for inc in re.findall(r'#include\s+["<]([^">]+)[">]', text):
            walk((path.parent/inc.replace('\\','/')).resolve(), default)
        for match in re.finditer(r'(?:^|\s)sample=(.*?)(?=\s+\w+=|\s*<|$)', text, re.S):
            ref=match.group(1).strip().strip('"').replace('\\','/')
            refs.append(ref)
            base=default if default is not None else path.parent
            if not (base/ref).resolve().is_file():
                missing.append(ref)

    walk(sfz_path)
    if not refs: raise SFZRendererError('SFZ_NO_SAMPLE_REFERENCES')
    return {'sample_references':len(refs),'unique_samples':len(set(refs)),
            'sfz_files_validated':len(visited),
            'static_unresolved_references':len(missing),
            'static_validation_status':'PASS' if not missing else 'DEFERRED_TO_RENDERER'}


def resolve_renderer() -> str:
    explicit=os.environ.get(RENDERER_ENV)
    if explicit:
        p=shutil.which(explicit) or (explicit if Path(explicit).is_file() else None)
        if p: return str(p)
    for name in ('sfizz_render','sfizz-render'):
        p=shutil.which(name)
        if p: return p
    raise SFZRendererError('SFZ_RENDERER_NOT_INSTALLED')


def preflight(resource: dict) -> dict:
    sfz=resolve_sfz(resource)
    samples=validate_sfz_samples(sfz)
    renderer=resolve_renderer()
    try:
        help_result=subprocess.run([renderer,'--help'],capture_output=True,text=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise SFZRendererError('SFZ_RENDERER_UNAVAILABLE:'+str(exc))
    help_text=help_result.stdout+help_result.stderr
    if not all(flag in help_text for flag in ('--sfz','--midi','--wav','--samplerate')):
        raise SFZRendererError('SFZ_RENDERER_COMMAND_CONTRACT_UNSUPPORTED')
    return {'status':'SFZ_RENDER_READY','resource_id':resource.get('resource_id'),
            'sfz_path':str(sfz),'renderer':renderer,**samples,
            'fallback_policy':'NO_SYNTHETIC_SUBSTITUTION'}


def render_midi(resource: dict, midi_path: str|Path, wav_path: str|Path, sample_rate: int=44100) -> dict:
    """Render MIDI through an approved SFZ backend."""
    ready=preflight(resource)
    midi=Path(midi_path).resolve(); wav=Path(wav_path).resolve()
    if not midi.is_file(): raise SFZRendererError('MIDI_INPUT_MISSING')
    wav.parent.mkdir(parents=True,exist_ok=True)
    cmd=[ready['renderer'],'--sfz',ready['sfz_path'],'--midi',str(midi),'--wav',str(wav),'--samplerate',str(sample_rate)]
    if wav.exists(): wav.unlink()
    try:
        cp=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise SFZRendererError('SFZ_RENDER_FAILED:'+str(exc))
    if cp.returncode!=0 or not wav.is_file():
        raise SFZRendererError('SFZ_RENDER_FAILED:'+((cp.stderr or cp.stdout or '').strip()[:400]))
    try:
        with wave.open(str(wav),'rb') as stream:
            frames=stream.getnframes(); channels=stream.getnchannels(); rate=stream.getframerate()
            width=stream.getsampwidth(); audible=False
            while True:
                chunk=stream.readframes(8192)
                if not chunk: break
                audible |= any(v != (128 if width==1 else 0) for v in chunk)
        if not frames or not audible or rate!=sample_rate or channels not in (1,2):
            raise SFZRendererError('SFZ_WAVEFORM_INVALID_OR_SILENT')
    except (wave.Error, EOFError, OSError) as exc:
        raise SFZRendererError('SFZ_WAVEFORM_UNREADABLE:'+str(exc))
    return {**ready,'frames':frames,'channels':channels,'sample_rate':rate,'status':'AUDIO_RENDER_PASS','wav_path':str(wav),'audio_rendered':True}
