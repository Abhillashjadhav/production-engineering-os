"""Deployment adapters. V1: local process with real HTTP verification."""

from pmpe.deployment.local import DeploymentAdapter, LocalProcessDeployer

__all__ = ["DeploymentAdapter", "LocalProcessDeployer"]
