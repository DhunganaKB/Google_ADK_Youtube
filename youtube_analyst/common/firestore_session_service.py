# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import copy
import logging
from typing import Any, Optional

from google.cloud import firestore
from google.adk.platform import time as platform_time
from google.adk.platform import uuid as platform_uuid
from typing_extensions import override

from google.adk.sessions import _session_util
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.events.event import Event
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.base_session_service import GetSessionConfig
from google.adk.sessions.base_session_service import ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State

logger = logging.getLogger("youtube_analyst." + __name__)


class FirestoreSessionService(BaseSessionService):
    """A session service that uses Google Cloud Firestore for storage."""

    def __init__(self, database: str = "(default)", project: Optional[str] = None):
        import os
        import google.auth

        # Resolve the target project (env var or explicit arg wins over ADC)
        resolved_project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")

        # Get ADC credentials and override the quota project so all gRPC calls
        # are billed/authorized against the correct project, not the ADC default.
        creds, adc_project = google.auth.default()
        if not resolved_project:
            resolved_project = str(adc_project)
        if hasattr(creds, "with_quota_project"):
            creds = creds.with_quota_project(resolved_project)

        self.db = firestore.AsyncClient(
            project=resolved_project, credentials=creds, database=database
        )

    def _get_app_doc(self, app_name: str):
        return self.db.collection("apps").document(app_name)

    def _get_user_doc(self, app_name: str, user_id: str):
        return self._get_app_doc(app_name).collection("users").document(user_id)

    def _get_session_doc(self, app_name: str, user_id: str, session_id: str):
        return self._get_user_doc(app_name, user_id).collection("sessions").document(session_id)

    def _get_events_col(self, app_name: str, user_id: str, session_id: str):
        return self._get_session_doc(app_name, user_id, session_id).collection("events")

    @override
    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: Optional[dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> Session:
        if session_id:
            session_id = session_id.strip()
        if not session_id:
            session_id = platform_uuid.new_uuid()
        now = platform_time.get_time()

        session_doc = self._get_session_doc(app_name, user_id, session_id)
        app_doc = self._get_app_doc(app_name)
        user_doc = self._get_user_doc(app_name, user_id)

        @firestore.async_transactional
        async def _run(transaction):
            # --- ALL READS FIRST (Firestore requires reads before writes) ---
            session_snap = await session_doc.get(transaction=transaction)
            if session_snap.exists:
                raise AlreadyExistsError(f"Session with id {session_id} already exists.")

            app_snap = await app_doc.get(transaction=transaction)
            user_snap = await user_doc.get(transaction=transaction)

            # --- COMPUTE ---
            state_deltas = _session_util.extract_state_delta(state or {})
            app_state_delta = state_deltas["app"]
            user_state_delta = state_deltas["user"]
            session_state = state_deltas["session"]

            app_data = app_snap.to_dict() or {}
            user_data = user_snap.to_dict() or {}
            new_app_state = {**app_data.get("state", {}), **app_state_delta}
            new_user_state = {**user_data.get("state", {}), **user_state_delta}

            # --- ALL WRITES AFTER ALL READS ---
            if app_state_delta:
                if app_snap.exists:
                    transaction.update(app_doc, {"state": new_app_state, "update_time": now})
                else:
                    transaction.set(app_doc, {"state": new_app_state, "update_time": now})

            if user_state_delta:
                if user_snap.exists:
                    transaction.update(user_doc, {"state": new_user_state, "update_time": now})
                else:
                    transaction.set(user_doc, {"state": new_user_state, "update_time": now})

            transaction.set(session_doc, {
                "id": session_id,
                "state": session_state,
                "create_time": now,
                "update_time": now,
            })

            return Session(
                app_name=app_name,
                user_id=user_id,
                id=session_id,
                state=_merge_state(new_app_state, new_user_state, session_state),
                events=[],
                last_update_time=now,
            )

        return await _run(self.db.transaction())

    @override
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        session_doc = self._get_session_doc(app_name, user_id, session_id)
        session_snap = await session_doc.get()
        if not session_snap.exists:
            return None

        session_data = session_snap.to_dict()
        session_state = session_data.get("state", {})
        last_update_time = session_data.get("update_time", 0.0)

        events_ref = self._get_events_col(app_name, user_id, session_id)
        query = events_ref.order_by("timestamp", direction=firestore.Query.DESCENDING)

        if config and config.after_timestamp:
            query = query.where("timestamp", ">=", config.after_timestamp)
        if config and config.num_recent_events:
            query = query.limit(config.num_recent_events)

        events_snaps = await query.get()
        events = [
            Event.model_validate_json(snap.to_dict()["event_data"])
            for snap in reversed(events_snaps)
        ]

        app_snap = await self._get_app_doc(app_name).get()
        user_snap = await self._get_user_doc(app_name, user_id).get()

        app_state = (app_snap.to_dict() or {}).get("state", {})
        user_state = (user_snap.to_dict() or {}).get("state", {})

        return Session(
            app_name=app_name,
            user_id=user_id,
            id=session_id,
            state=_merge_state(app_state, user_state, session_state),
            events=events,
            last_update_time=last_update_time,
        )

    @override
    async def list_sessions(
        self, *, app_name: str, user_id: Optional[str] = None
    ) -> ListSessionsResponse:
        sessions_list = []

        app_snap = await self._get_app_doc(app_name).get()
        app_state = (app_snap.to_dict() or {}).get("state", {})

        if user_id:
            user_snap = await self._get_user_doc(app_name, user_id).get()
            user_state = (user_snap.to_dict() or {}).get("state", {})

            sessions_snaps = await self._get_user_doc(app_name, user_id).collection("sessions").get()
            for snap in sessions_snaps:
                data = snap.to_dict()
                if not data:
                    continue
                sessions_list.append(Session(
                    app_name=app_name,
                    user_id=user_id,
                    id=snap.id,
                    state=_merge_state(app_state, user_state, data.get("state", {})),
                    events=[],
                    last_update_time=data.get("update_time", 0.0),
                ))
        else:
            users_snaps = await self._get_app_doc(app_name).collection("users").get()
            for user_snap in users_snaps:
                u_id = user_snap.id
                u_state = (user_snap.to_dict() or {}).get("state", {})

                sessions_snaps = await user_snap.reference.collection("sessions").get()
                for s_snap in sessions_snaps:
                    data = s_snap.to_dict()
                    if not data:
                        continue
                    sessions_list.append(Session(
                        app_name=app_name,
                        user_id=u_id,
                        id=s_snap.id,
                        state=_merge_state(app_state, u_state, data.get("state", {})),
                        events=[],
                        last_update_time=data.get("update_time", 0.0),
                    ))

        return ListSessionsResponse(sessions=sessions_list)

    @override
    async def delete_session(
        self, *, app_name: str, user_id: str, session_id: str
    ) -> None:
        await self._get_session_doc(app_name, user_id, session_id).delete()

    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        if event.partial:
            return event

        self._apply_temp_state(session, event)
        event = self._trim_temp_delta_state(event)
        event_timestamp = event.timestamp

        session_doc = self._get_session_doc(session.app_name, session.user_id, session.id)

        @firestore.async_transactional
        async def _run(transaction):
            # --- ALL READS FIRST ---
            session_snap = await session_doc.get(transaction=transaction)
            if not session_snap.exists:
                raise ValueError(f"Session {session.id} not found.")

            data = session_snap.to_dict()
            if data.get("update_time", 0.0) > session.last_update_time:
                raise ValueError(
                    "The last_update_time provided in the session object is"
                    " earlier than the update_time in storage."
                    " Please check if it is a stale session."
                )

            # Determine state deltas before any reads/writes
            app_state_delta: dict = {}
            user_state_delta: dict = {}
            session_state_delta: dict = {}
            if event.actions and event.actions.state_delta:
                state_deltas = _session_util.extract_state_delta(event.actions.state_delta)
                app_state_delta = state_deltas["app"]
                user_state_delta = state_deltas["user"]
                session_state_delta = state_deltas["session"]

            # Read app/user docs if we need to update them (still before writes)
            app_snap = None
            user_snap = None
            if app_state_delta:
                app_snap = await self._get_app_doc(session.app_name).get(transaction=transaction)
            if user_state_delta:
                user_snap = await self._get_user_doc(session.app_name, session.user_id).get(transaction=transaction)

            # --- ALL WRITES AFTER ALL READS ---
            if app_state_delta and app_snap is not None:
                new_app_state = {**(app_snap.to_dict() or {}).get("state", {}), **app_state_delta}
                if app_snap.exists:
                    transaction.update(self._get_app_doc(session.app_name), {"state": new_app_state, "update_time": event_timestamp})
                else:
                    transaction.set(self._get_app_doc(session.app_name), {"state": new_app_state, "update_time": event_timestamp})

            if user_state_delta and user_snap is not None:
                new_user_state = {**(user_snap.to_dict() or {}).get("state", {}), **user_state_delta}
                if user_snap.exists:
                    transaction.update(self._get_user_doc(session.app_name, session.user_id), {"state": new_user_state, "update_time": event_timestamp})
                else:
                    transaction.set(self._get_user_doc(session.app_name, session.user_id), {"state": new_user_state, "update_time": event_timestamp})

            has_session_state_delta = False
            if session_state_delta:
                new_session_state = {**data.get("state", {}), **session_state_delta}
                transaction.update(session_doc, {"state": new_session_state, "update_time": event_timestamp})
                has_session_state_delta = True

            events_ref = self._get_events_col(session.app_name, session.user_id, session.id)
            transaction.set(events_ref.document(event.id), {
                "invocation_id": event.invocation_id,
                "timestamp": event.timestamp,
                "event_data": event.model_dump_json(exclude_none=True),
            })

            if not has_session_state_delta:
                transaction.update(session_doc, {"update_time": event_timestamp})

            return event_timestamp

        new_update_time = await _run(self.db.transaction())
        session.last_update_time = new_update_time

        await super().append_event(session=session, event=event)
        return event


def _merge_state(app_state: dict, user_state: dict, session_state: dict) -> dict:
    merged = copy.deepcopy(session_state)
    for k, v in app_state.items():
        merged[State.APP_PREFIX + k] = v
    for k, v in user_state.items():
        merged[State.USER_PREFIX + k] = v
    return merged
