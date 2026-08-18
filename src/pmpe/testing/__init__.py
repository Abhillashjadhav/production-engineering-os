"""Tests-before-code compilation, evidence, persistence, and legacy generation."""

from pmpe.testing.architect import TestArchitect
from pmpe.testing.compiler import TEST_PLAN_COMPILER_VERSION, TestPlanCompiler
from pmpe.testing.evidence import (
    MeaningfulRedAdmission,
    MeaningfulRedGate,
    MeaningfulRedRun,
    RedTestExecution,
    ToolExecutionReceipt,
)
from pmpe.testing.models import (
    TEST_PLAN_SCHEMA_VERSION,
    CoverageEntry,
    RepositoryTestCapability,
    TestClass,
    TestClassDecision,
    TestPlan,
    TestPlanCompilationResult,
    TestPlanDiagnostic,
    TestPlanDisposition,
    TestPlanNode,
)
from pmpe.testing.store import (
    ImplementationAuthorization,
    TestPlanConflict,
    TestPlanNotAdmitted,
    TestPlanReceipt,
    TestPlanStore,
)

__all__ = [
    "TEST_PLAN_COMPILER_VERSION",
    "TEST_PLAN_SCHEMA_VERSION",
    "CoverageEntry",
    "ImplementationAuthorization",
    "MeaningfulRedAdmission",
    "MeaningfulRedGate",
    "MeaningfulRedRun",
    "RedTestExecution",
    "RepositoryTestCapability",
    "TestArchitect",
    "TestClass",
    "TestClassDecision",
    "TestPlan",
    "TestPlanCompilationResult",
    "TestPlanCompiler",
    "TestPlanConflict",
    "TestPlanDiagnostic",
    "TestPlanDisposition",
    "TestPlanNode",
    "TestPlanNotAdmitted",
    "TestPlanReceipt",
    "TestPlanStore",
    "ToolExecutionReceipt",
]
