"""Science-Sandbox Analysis Release, Derived Analysis, Interpretation, Conclusion, Controlled Output."""
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, Optional, Tuple
import hashlib, json

@dataclass(frozen=True)
class AnalysisRelease:
    result_id: str
    status: str
    reasons: Tuple[str, ...]
    released: bool

@dataclass(frozen=True)
class DerivedAnalysis:
    analysis_id: str
    result_id: str
    raw_evidence_id: Optional[str]
    raw_evidence_sha256: Optional[str]
    method_name: str
    method_version: str
    derived_payload: bytes
    derived_sha256: str
    analytical_output: Dict[str, Any]

@dataclass(frozen=True)
class Interpretation:
    interpretation_id: str
    analysis_id: str
    text: str
    limitations: Tuple[str, ...]
    uncertainty: Tuple[str, ...]

@dataclass(frozen=True)
class Conclusion:
    conclusion_id: str
    interpretation_id: str
    category: str
    text: str

@dataclass(frozen=True)
class ControlledScientificOutput:
    output_id: str
    portal2_record_reference: str
    registration_id: str
    question_id: str
    experiment_id: str
    run_id: str
    result_id: str
    raw_evidence_id: Optional[str]
    raw_evidence_sha256: Optional[str]
    analysis_id: str
    interpretation_id: str
    conclusion_id: str
    measurement_state: str
    method_name: str
    method_version: str
    derived_sha256: str
    interpretation: str
    conclusion_category: str
    conclusion: str
    limitations: Tuple[str, ...]
    uncertainty: Tuple[str, ...]
    unresolved_questions: Tuple[str, ...]
    def to_dict(self): return asdict(self)

class AnalysisPipeline:
    ALLOWED_CONCLUSIONS = {
        "SUPPORTED UNDER TESTED CONDITIONS",
        "NOT SUPPORTED UNDER TESTED CONDITIONS",
        "PARTIALLY SUPPORTED",
        "INCONCLUSIVE",
        "EXPERIMENT INVALID",
        "INSUFFICIENT EVIDENCE",
        "ADDITIONAL TESTING REQUIRED",
    }

    def __init__(self):
        self._a=1; self._i=1; self._c=1; self._o=1

    def release(self, result: Any) -> AnalysisRelease:
        reasons=[]
        required = {
            "result_id": getattr(result,"result_id",None),
            "run_id": getattr(result,"run_id",None),
            "experiment_id": getattr(result,"experiment_id",None),
            "registration_id": getattr(result,"registration_id",None),
            "portal2_record_reference": getattr(result,"portal2_record_reference",None),
            "source_fingerprint": getattr(result,"source_fingerprint",None),
            "measurement_state": getattr(result,"measurement_state",None),
        }
        for k,v in required.items():
            if v is None or str(v).strip()=="":
                reasons.append(f"missing traceability field: {k}")
        state=getattr(result,"measurement_state",None)
        raw_id=getattr(result,"raw_evidence_id",None)
        raw_hash=getattr(result,"raw_evidence_sha256",None)
        if state in {"VALID MEASUREMENT","ZERO","BELOW DETECTION","NULL FINDING"}:
            if not raw_id or not raw_hash:
                reasons.append("measurement state requires preserved raw evidence")
        if state in {"INVALID","FAILED EXECUTION","INCOMPLETE EXECUTION"}:
            reasons.append(f"result state not releasable for substantive analysis: {state}")
        status="PASS" if not reasons else "HOLD"
        return AnalysisRelease(result.result_id,status,tuple(reasons),not reasons)

    def analyze(self, release: AnalysisRelease, result: Any, raw_evidence: Any,
                method_name: str, method_version: str,
                analyzer: Callable[[bytes], Tuple[bytes,Dict[str,Any]]]) -> DerivedAnalysis:
        if not release.released or release.result_id != result.result_id:
            raise ValueError("Result has not passed the Analysis Release Gate.")
        if not method_name.strip() or not method_version.strip():
            raise ValueError("Analysis method name and version are required.")
        if not getattr(raw_evidence,"preserved",False):
            raise ValueError("Preserved raw evidence is required.")
        if raw_evidence.evidence_id != result.raw_evidence_id or raw_evidence.sha256 != result.raw_evidence_sha256:
            raise ValueError("Raw evidence lineage mismatch.")
        # Verify raw evidence itself before deriving anything.
        if hashlib.sha256(raw_evidence.payload).hexdigest() != raw_evidence.sha256:
            raise ValueError("Raw evidence integrity failure.")
        derived, output=analyzer(bytes(raw_evidence.payload))
        if not isinstance(derived,(bytes,bytearray)) or not isinstance(output,dict):
            raise ValueError("Analyzer must return (bytes, dict).")
        aid=f"SS-AN-{self._a:04d}"; self._a+=1
        frozen=bytes(derived)
        return DerivedAnalysis(aid,result.result_id,raw_evidence.evidence_id,raw_evidence.sha256,
            method_name.strip(),method_version.strip(),frozen,hashlib.sha256(frozen).hexdigest(),dict(output))

    def interpret(self, analysis: DerivedAnalysis, text: str, limitations, uncertainty) -> Interpretation:
        if not text.strip(): raise ValueError("Interpretation text is required.")
        lim=tuple(str(x).strip() for x in limitations if str(x).strip())
        unc=tuple(str(x).strip() for x in uncertainty if str(x).strip())
        iid=f"SS-INT-{self._i:04d}"; self._i+=1
        return Interpretation(iid,analysis.analysis_id,text.strip(),lim,unc)

    def conclude(self, interpretation: Interpretation, category: str, text: str) -> Conclusion:
        if category not in self.ALLOWED_CONCLUSIONS:
            raise ValueError("Conclusion category is not controlled.")
        if not text.strip(): raise ValueError("Conclusion text is required.")
        cid=f"SS-CON-{self._c:04d}"; self._c+=1
        return Conclusion(cid,interpretation.interpretation_id,category,text.strip())

    def output(self, *, question: Any, experiment: Any, result: Any,
               analysis: DerivedAnalysis, interpretation: Interpretation,
               conclusion: Conclusion, unresolved_questions=()) -> ControlledScientificOutput:
        if analysis.result_id != result.result_id: raise ValueError("Analysis/result lineage mismatch.")
        if interpretation.analysis_id != analysis.analysis_id: raise ValueError("Interpretation/analysis lineage mismatch.")
        if conclusion.interpretation_id != interpretation.interpretation_id: raise ValueError("Conclusion/interpretation lineage mismatch.")
        if experiment.question_id != question.question_id or experiment.experiment_id != result.experiment_id:
            raise ValueError("Question/experiment/result lineage mismatch.")
        oid=f"SS-OUT-{self._o:04d}"; self._o+=1
        return ControlledScientificOutput(
            oid,result.portal2_record_reference,result.registration_id,question.question_id,
            experiment.experiment_id,result.run_id,result.result_id,result.raw_evidence_id,
            result.raw_evidence_sha256,analysis.analysis_id,interpretation.interpretation_id,
            conclusion.conclusion_id,result.measurement_state,analysis.method_name,analysis.method_version,
            analysis.derived_sha256,interpretation.text,conclusion.category,conclusion.text,
            interpretation.limitations,interpretation.uncertainty,
            tuple(str(x).strip() for x in unresolved_questions if str(x).strip()))
