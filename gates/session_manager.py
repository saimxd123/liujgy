

import asyncio
import time
from typing import Dict, Optional, List, Any, Tuple

from logger import get_logger


logger = get_logger(__name__)






MAX_SESSIONS_PER_USER = 3
MAX_TOTAL_SESSIONS = 20


SESSION_TIMEOUT = 30 * 60



CLEANUP_INTERVAL = 5 * 60






class SessionManager:
    """
    Generic async session manager.

    Responsibilities:
    - Track active sessions
    - Enforce global/user limits
    - Track inactivity
    - Stop sessions
    - Cancel associated asyncio tasks
    - Clean stale sessions
    - Provide session information for admin dashboards
    """

    def __init__(self):
        self._sessions: Dict[str, dict] = {}
        self._user_sessions: Dict[int, List[str]] = {}

        self._lock = asyncio.Lock()

        self._cleanup_task: Optional[asyncio.Task] = None





    def get_session(
        self,
        session_id: str
    ) -> Optional[dict]:
        """Return a session by ID."""

        session = self._sessions.get(session_id)

        if session is None:
            return None

        return session

    def get_user_sessions(
        self,
        user_id: int
    ) -> List[str]:
        """Return active session IDs belonging to a user."""

        sessions = self._user_sessions.get(
            user_id,
            []
        )

        return [
            session_id
            for session_id in sessions
            if (
                session_id in self._sessions
                and self._sessions[session_id].get(
                    "active",
                    False
                )
            )
        ]

    def get_active_sessions_count(self) -> int:
        """Return number of active sessions."""

        return sum(
            1
            for session in self._sessions.values()
            if session.get("active", False)
        )

    def get_all_active_sessions(self) -> List[dict]:
        """
        Return a snapshot of all active sessions.

        This intentionally stays synchronous so existing
        /session code can call it without `await`.
        """

        return [
            {
                **data,
                "session_id": session_id
            }
            for session_id, data in self._sessions.items()
            if data.get("active", False)
        ]





    def can_start_session(
        self,
        user_id: int
    ) -> Tuple[bool, str]:
        """
        Check whether a user can start another session.

        Returns:
            (True, "OK")
            or
            (False, reason)
        """

        active_total = self.get_active_sessions_count()

        if active_total >= MAX_TOTAL_SESSIONS:
            return (
                False,
                (
                    f"Maximum of "
                    f"{MAX_TOTAL_SESSIONS} "
                    f"concurrent sessions reached. "
                    f"Please wait for a session to finish."
                )
            )

        active_user_sessions = len(
            self.get_user_sessions(user_id)
        )

        if active_user_sessions >= MAX_SESSIONS_PER_USER:
            return (
                False,
                (
                    f"You already have "
                    f"{MAX_SESSIONS_PER_USER} "
                    f"active sessions."
                )
            )

        return True, "OK"





    async def register_session(
        self,
        session_id: str,
        user_id: int,
        data: Optional[dict] = None
    ) -> bool:
        """
        Register a new session.

        Returns:
            True if registered.
            False if the limits were reached.
        """

        if data is None:
            data = {}

        async with self._lock:




            active_total = sum(
                1
                for session in self._sessions.values()
                if session.get("active", False)
            )

            if active_total >= MAX_TOTAL_SESSIONS:
                logger.warning(
                    "Session %s rejected: global limit reached.",
                    session_id
                )
                return False

            user_session_ids = self._user_sessions.get(
                user_id,
                []
            )

            active_user_count = sum(
                1
                for sid in user_session_ids
                if (
                    sid in self._sessions
                    and self._sessions[sid].get(
                        "active",
                        False
                    )
                )
            )

            if active_user_count >= MAX_SESSIONS_PER_USER:
                logger.warning(
                    "Session %s rejected: user %s limit reached.",
                    session_id,
                    user_id
                )
                return False

            now = time.time()

            session_data = dict(data)

            session_data["active"] = True
            session_data["stopped"] = False
            session_data["stop_reason"] = None

            session_data["user_id"] = user_id

            session_data["created_at"] = now
            session_data["last_activity"] = now

            self._sessions[
                session_id
            ] = session_data

            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = []

            if session_id not in self._user_sessions[user_id]:
                self._user_sessions[user_id].append(
                    session_id
                )

            logger.info(
                "Session %s registered for user %s "
                "(%d/%d active).",
                session_id,
                user_id,
                active_total + 1,
                MAX_TOTAL_SESSIONS
            )

            return True





    def touch_session(
        self,
        session_id: str
    ) -> bool:
        """
        Refresh the inactivity timer.

        Your long-running session should call this whenever
        meaningful work/activity occurs.
        """

        session = self._sessions.get(session_id)

        if not session:
            return False

        if not session.get("active", False):
            return False

        session["last_activity"] = time.time()

        return True





    async def unregister_session(
        self,
        session_id: str
    ) -> bool:
        """
        Mark a session as finished and release its slot.
        """

        async with self._lock:

            session = self._sessions.get(
                session_id
            )

            if not session:
                return False

            user_id = session.get("user_id")

            session["active"] = False

            self._sessions[
                session_id
            ] = session

            if user_id in self._user_sessions:

                if session_id in self._user_sessions[user_id]:
                    self._user_sessions[user_id].remove(
                        session_id
                    )

                if not self._user_sessions[user_id]:
                    del self._user_sessions[user_id]

            logger.info(
                "Session %s unregistered.",
                session_id
            )

            return True





    async def stop_session(
        self,
        session_id: str,
        reason: Optional[str] = None
    ) -> Optional[dict]:
        """
        Stop a session.

        This can be used by an owner/admin.

        It:
        - Marks the session inactive
        - Sets stop_event if present
        - Cancels the main task if present
        - Cancels worker tasks if present
        - Releases the user's session slot

        Returns the stopped session data.
        """

        async with self._lock:

            session = self._sessions.get(
                session_id
            )

            if not session:
                return None

            if not session.get("active", False):
                return None

            stop_reason = (
                reason
                or "Stopped by administrator"
            )





            session["active"] = False
            session["stopped"] = True
            session["stop_reason"] = stop_reason

            session["last_activity"] = time.time()

            self._sessions[
                session_id
            ] = session

            user_id = session.get(
                "user_id"
            )

            if user_id in self._user_sessions:

                if session_id in self._user_sessions[user_id]:
                    self._user_sessions[user_id].remove(
                        session_id
                    )

                if not self._user_sessions[user_id]:
                    del self._user_sessions[user_id]





            stop_event = session.get(
                "stop_event"
            )

            if stop_event is not None:

                try:
                    stop_event.set()
                except Exception:
                    logger.exception(
                        "Failed to set stop_event "
                        "for %s",
                        session_id
                    )





            main_task = session.get(
                "task"
            )

            if (
                isinstance(main_task, asyncio.Task)
                and not main_task.done()
            ):
                main_task.cancel()





            workers = session.get(
                "workers",
                []
            )

            if workers:

                for worker in list(workers):

                    if (
                        isinstance(worker, asyncio.Task)
                        and not worker.done()
                    ):
                        worker.cancel()

            logger.info(
                "Session %s stopped. "
                "User=%s Reason=%s",
                session_id,
                user_id,
                stop_reason
            )

            return {
                **session,
                "session_id": session_id
            }





    async def stop_user_session(
        self,
        session_id: str,
        user_id: int,
        reason: Optional[str] = None
    ) -> Optional[dict]:
        """
        Stop a session only if it belongs to the user.
        """

        async with self._lock:

            session = self._sessions.get(
                session_id
            )

            if not session:
                return None

            if not session.get("active", False):
                return None

            if session.get("user_id") != user_id:
                return None

        return await self.stop_session(
            session_id,
            reason or "Stopped by user"
        )





    async def cleanup_stale_sessions(self):
        """
        Remove sessions inactive for 30 minutes.

        Only one lightweight cleanup worker is used.
        """

        logger.info(
            "Session cleanup worker started."
        )

        try:

            while True:

                await asyncio.sleep(
                    CLEANUP_INTERVAL
                )

                now = time.time()

                stale_sessions = []

                async with self._lock:

                    for (
                        session_id,
                        session
                    ) in list(
                        self._sessions.items()
                    ):

                        if not session.get(
                            "active",
                            False
                        ):
                            continue

                        last_activity = session.get(
                            "last_activity",
                            session.get(
                                "created_at",
                                now
                            )
                        )

                        inactive_for = (
                            now - last_activity
                        )

                        if inactive_for >= SESSION_TIMEOUT:

                            session["active"] = False
                            session["stopped"] = True
                            session["stop_reason"] = (
                                "Inactive for 30 minutes"
                            )

                            stale_sessions.append(
                                (
                                    session_id,
                                    session
                                )
                            )

                            user_id = session.get(
                                "user_id"
                            )

                            if (
                                user_id
                                in self._user_sessions
                            ):

                                if (
                                    session_id
                                    in self._user_sessions[
                                        user_id
                                    ]
                                ):
                                    self._user_sessions[
                                        user_id
                                    ].remove(
                                        session_id
                                    )

                                if not self._user_sessions[
                                    user_id
                                ]:
                                    del self._user_sessions[
                                        user_id
                                    ]





                    for (
                        session_id,
                        session
                    ) in stale_sessions:

                        stop_event = session.get(
                            "stop_event"
                        )

                        if stop_event is not None:
                            try:
                                stop_event.set()
                            except Exception:
                                pass

                        task = session.get(
                            "task"
                        )

                        if (
                            isinstance(
                                task,
                                asyncio.Task
                            )
                            and not task.done()
                        ):
                            task.cancel()

                        workers = session.get(
                            "workers",
                            []
                        )

                        for worker in list(
                            workers
                        ):

                            if (
                                isinstance(
                                    worker,
                                    asyncio.Task
                                )
                                and not worker.done()
                            ):
                                worker.cancel()

                        logger.info(
                            "Session %s removed "
                            "after 30 minutes "
                            "of inactivity.",
                            session_id
                        )

                if stale_sessions:

                    logger.info(
                        "Cleaned %d stale session(s).",
                        len(stale_sessions)
                    )

        except asyncio.CancelledError:

            logger.info(
                "Session cleanup worker stopped."
            )

            raise

        except Exception:

            logger.exception(
                "Session cleanup worker crashed."
            )





    def start_cleanup(self):
        """
        Start the single cleanup worker.
        Safe to call multiple times.
        """

        if (
            self._cleanup_task is None
            or self._cleanup_task.done()
        ):

            self._cleanup_task = (
                asyncio.create_task(
                    self.cleanup_stale_sessions()
                )
            )

            logger.info(
                "Session cleanup scheduled."
            )





    async def shutdown(self):
        """
        Stop the cleanup worker cleanly.
        """

        if (
            self._cleanup_task
            and not self._cleanup_task.done()
        ):

            self._cleanup_task.cancel()

            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

            self._cleanup_task = None

            logger.info(
                "Session manager shutdown complete."
            )






session_manager = SessionManager()