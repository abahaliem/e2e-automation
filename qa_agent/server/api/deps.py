"""Akses objek bersama (store, secrets, hub, manager) dari request."""
from __future__ import annotations

from fastapi import HTTPException, Request

from qa_agent.server.events import EventHub
from qa_agent.server.runs import RunManager
from qa_agent.server.secrets import SecretStore
from qa_agent.server.settings import ServerSettings
from qa_agent.server.store import RunRow, Store


def store(request: Request) -> Store:
    return request.app.state.store


def secrets(request: Request) -> SecretStore:
    return request.app.state.secrets


def hub(request: Request) -> EventHub:
    return request.app.state.hub


def manager(request: Request) -> RunManager:
    return request.app.state.manager


def settings(request: Request) -> ServerSettings:
    return request.app.state.settings


def not_found(what: str = "Data") -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} tidak ditemukan")


def get_run_or_404(request: Request, run_id: int) -> RunRow:
    row = store(request).get_run(run_id)
    if row is None:
        raise not_found("Run")
    return row
