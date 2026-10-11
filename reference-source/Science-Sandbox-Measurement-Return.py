"""Science-Sandbox Measurement Return, Raw Evidence Preservation, Classification, Result Record."""
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple
import hashlib

VALID_MEASUREMENT_STATES = {
    "VALID MEASUREMENT", "ZERO", "MISSING", "BELOW DETECTION",
    "INVALID", "AMBIGUOUS", "NULL FINDING", "FAILED EXECUTION",
    "INCOMPLETE EXECUTION"
}

@dataclass(frozen=True)
class MeasurementReturn:
    run_id: str
    experiment_id: str
    component_id: str
    source_fingerprint: str
    actual_conditions: Tuple[str, ...]
    deviations: Tuple[str, ...]
    execution_status: str
    raw_payload: Optional[bytes]
    measurement_metadata: Dict[str, Any]
    claimed_measurement_state: str

@dataclass(frozen=True)
class RawEvidence:
    evidence_id: str
    run_id: str
    sha256: Optional[str]
    payload: Optional[bytes]
    preserved: bool

@dataclass(frozen=True)
class ResultRecord:
    result_id: str
    run_id: str
    experiment_id: str
    registration_id: str
    portal2_record_reference: str
    source_fingerprint: str
    component_id: str
    planned_conditions: Tuple[str, ...]
    actual_conditions: Tuple[str, ...]
    deviations: Tuple[str, ...]
    execution_status: str
    measurement_state: str
    raw_evidence_id: Optional[str]
    raw_evidence_sha256: Optional[str]
    measurement_metadata: Dict[str, Any]
    interpretation: Optional[str] = None
    conclusion: Optional[str] = None
    def to_dict(self): return asdict(self)

class EvidenceReturnGate:
    def __init__(self):
        self._next_evidence=1
        self._next_result=1
        self._evidence={}
        self._results={}

    def accept(self, run: Any, handoff: Any, returned: MeasurementReturn):
        # lineage first
        if returned.run_id != run.run_id or returned.run_id != handoff.run_id:
            raise ValueError("Measurement return does not belong to this run.")
        if returned.experiment_id != run.experiment_id or returned.experiment_id != handoff.experiment_id:
            raise ValueError("Measurement return experiment lineage mismatch.")
        if returned.component_id != run.component_id or returned.component_id != handoff.component_id:
            raise ValueError("Measurement return component lineage mismatch.")
        if returned.source_fingerprint != run.source_fingerprint or returned.source_fingerprint != handoff.source_fingerprint:
            raise ValueError("Measurement return source provenance mismatch.")
        if returned.claimed_measurement_state not in VALID_MEASUREMENT_STATES:
            raise ValueError("Unknown measurement-state classification.")
        if not returned.actual_conditions:
            raise ValueError("Actual conditions must be recorded separately from planned conditions.")

        state=returned.claimed_measurement_state
        payload=returned.raw_payload

        # Do not allow contradictory evidence-state claims.
        if state in {"VALID MEASUREMENT","ZERO","BELOW DETECTION","NULL FINDING"} and payload is None:
            raise ValueError(f"{state} requires preserved returned measurement evidence.")
        if state == "MISSING" and payload is not None:
            raise ValueError("MISSING cannot carry a measurement payload; classify the returned evidence instead.")

        evidence=None
        if payload is not None:
            if not isinstance(payload,(bytes,bytearray)):
                raise ValueError("Raw payload must be bytes.")
            eid=f"SS-EVID-{self._next_evidence:04d}"; self._next_evidence+=1
            frozen=bytes(payload)
            evidence=RawEvidence(eid,run.run_id,hashlib.sha256(frozen).hexdigest(),frozen,True)
            self._evidence[eid]=evidence

        rid=f"SS-RES-{self._next_result:04d}"; self._next_result+=1
        result=ResultRecord(
            rid,run.run_id,run.experiment_id,run.registration_id,run.portal2_record_reference,
            run.source_fingerprint,run.component_id,tuple(run.planned_conditions),
            tuple(returned.actual_conditions),tuple(returned.deviations),returned.execution_status,
            state,evidence.evidence_id if evidence else None,evidence.sha256 if evidence else None,
            dict(returned.measurement_metadata),None,None
        )
        self._results[rid]=result
        return evidence,result

    def get_evidence(self,evidence_id): return self._evidence[evidence_id]
    def get_result(self,result_id): return self._results[result_id]
