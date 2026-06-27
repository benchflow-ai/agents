"""In-memory store + async event hub.

Events are applied to the store and fanned out to SSE subscribers on the event
loop thread. The agent runs in a worker thread and publishes via ``publish``,
which hops to the loop thread with ``call_soon_threadsafe`` so no locks are
needed and HTTP handlers always read a consistent store.
"""

import asyncio


class Hub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}  # sessionID -> [Message]
        self.parts: dict[str, list[dict]] = {}  # messageID -> [Part]
        self.cancels: dict[str, object] = {}  # sessionID -> threading.Event

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    # --- subscriptions (SSE) ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    # --- publishing ---
    def publish(self, event: dict) -> None:
        """Thread-safe: callable from the agent worker thread or the loop."""
        if self.loop is None:
            self._publish_local(event)
            return
        self.loop.call_soon_threadsafe(self._publish_local, event)

    def _publish_local(self, event: dict) -> None:
        self._apply(event)
        for q in list(self.subscribers):
            q.put_nowait(event)

    def _apply(self, event: dict) -> None:
        t = event["type"]
        p = event["properties"]
        if t == "message.updated":
            self._upsert(self.messages.setdefault(p["info"]["sessionID"], []), p["info"])
        elif t == "message.part.updated":
            self._upsert(self.parts.setdefault(p["part"]["messageID"], []), p["part"])
        elif t == "session.updated":
            self.sessions[p["info"]["id"]] = p["info"]

    @staticmethod
    def _upsert(items: list[dict], obj: dict) -> None:
        for i, existing in enumerate(items):
            if existing["id"] == obj["id"]:
                items[i] = obj
                return
        items.append(obj)
        items.sort(key=lambda x: x["id"])

    # --- store reads/writes for HTTP handlers (loop thread) ---
    def put_session(self, s: dict) -> None:
        self.sessions[s["id"]] = s

    def list_sessions(self) -> list[dict]:
        return sorted(self.sessions.values(), key=lambda s: s["id"])

    def get_session(self, sid: str) -> dict | None:
        return self.sessions.get(sid)

    def get_messages(self, sid: str) -> list[dict]:
        return [{"info": m, "parts": self.parts.get(m["id"], [])} for m in self.messages.get(sid, [])]
