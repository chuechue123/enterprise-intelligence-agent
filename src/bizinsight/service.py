"""Uvicorn import target for the AgentScope service."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from bizinsight.app import create_agent_service

app = create_agent_service(Path(__file__).resolve().parents[2])
