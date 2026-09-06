from enum import Enum


class EvidenceLabel(str, Enum):
    OBSERVED = "OBSERVED"
    DOCUMENTED = "DOCUMENTED"
    ASSUMED = "ASSUMED"


class Classification(str, Enum):
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    ADVERTISED_ONLY = "ADVERTISED_ONLY"
    INCONCLUSIVE = "INCONCLUSIVE"


class GateOutcome(str, Enum):
    CLIENT_GATED = "CLIENT-GATED"
    SERVER_GATED = "SERVER-GATED"
    UNGATED = "UNGATED"
    NOT_OBSERVED = "NOT_OBSERVED"
