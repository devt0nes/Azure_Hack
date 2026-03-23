import json
import os
import time
import uuid
import threading
from datetime import datetime
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

try:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    from azure.servicebus.management import ServiceBusAdministrationClient
    from azure.servicebus.management import SqlRuleFilter
    from azure.core.exceptions import ResourceNotFoundError
    _SERVICEBUS_AVAILABLE = True
except Exception:
    ServiceBusClient = None
    ServiceBusMessage = None
    ServiceBusAdministrationClient = None
    SqlRuleFilter = None
    ResourceNotFoundError = None
    _SERVICEBUS_AVAILABLE = False


class ServiceBusCoordinator:
    """Azure Service Bus helper for directed agent-to-agent questions and responses."""

    def __init__(self, connection_str: str, topic_name: str):
        self.connection_str = connection_str
        self.topic_name = topic_name
        self.enabled = bool(connection_str and topic_name and _SERVICEBUS_AVAILABLE)
        self._admin_lock = threading.Lock()
        self._log_lock = threading.Lock()
        default_log_path = os.path.join(os.path.dirname(__file__), "service_bus_messages.log")
        self.log_path = os.getenv("SERVICE_BUS_LOG_PATH", default_log_path).strip() or default_log_path
        self.human_log_path = os.getenv(
            "SERVICE_BUS_HUMAN_LOG_PATH",
            os.path.join(os.path.dirname(self.log_path), "service_bus_messages_readable.log")
        ).strip() or os.path.join(os.path.dirname(self.log_path), "service_bus_messages_readable.log")
        self._ensure_log_file_permissions()

    def _ensure_log_file_permissions(self):
        """Ensure the log file exists and is user-only readable/writable."""
        try:
            log_dir = os.path.dirname(self.log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

            if not os.path.exists(self.log_path):
                with open(self.log_path, "a", encoding="utf-8"):
                    pass
            if not os.path.exists(self.human_log_path):
                with open(self.human_log_path, "a", encoding="utf-8"):
                    pass

            # User-only read/write permissions on Linux/macOS.
            os.chmod(self.log_path, 0o600)
            os.chmod(self.human_log_path, 0o600)
        except Exception:
            # Logging setup failure should never break orchestration.
            pass

    def _log_event(self, event_type: str, payload: Dict):
        """Append a structured JSON event to local Service Bus log."""
        try:
            event = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "event": event_type,
                "topic": self.topic_name,
                "payload": payload,
            }
            line = json.dumps(event, ensure_ascii=False)
            with self._log_lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")

                # Also write a concise human-readable mirror.
                p = payload or {}
                readable = (
                    f"[{event['ts']}] {event_type} "
                    f"from={p.get('from_agent', '-') } to={p.get('to_agent', p.get('agent_role', '-'))} "
                    f"id={p.get('id', '-')} in_reply_to={p.get('in_reply_to', '-')}"
                )
                content = p.get("content")
                if isinstance(content, str) and content:
                    readable += f" | {content}"
                with open(self.human_log_path, "a", encoding="utf-8") as f:
                    f.write(readable + "\n")

                # Re-assert restrictive permissions in case external tools changed them.
                try:
                    os.chmod(self.log_path, 0o600)
                    os.chmod(self.human_log_path, 0o600)
                except Exception:
                    pass
        except Exception:
            pass

    @classmethod
    def from_env(cls):
        conn = os.getenv("SERVICE_BUS_STR", "").strip()
        topic = os.getenv("AGENT_COORDINATION_TOPIC", "").strip()
        return cls(conn, topic)

    def is_enabled(self) -> bool:
        return self.enabled

    def _ensure_subscription(self, agent_role: str):
        if not self.enabled:
            return

        sub_name = agent_role
        admin = ServiceBusAdministrationClient.from_connection_string(self.connection_str)

        # Parallel agents may race here on first receive; serialize admin mutations.
        with self._admin_lock:
            if not self._subscription_exists(admin, self.topic_name, sub_name):
                try:
                    admin.create_subscription(self.topic_name, sub_name)
                    self._log_event("subscription_created", {
                        "agent_role": agent_role,
                        "subscription": sub_name
                    })
                except Exception:
                    # Another thread/process may have created it in the meantime.
                    if not self._subscription_exists(admin, self.topic_name, sub_name):
                        self._log_event("subscription_create_failed", {
                            "agent_role": agent_role,
                            "subscription": sub_name
                        })
                        raise

            # Ensure a deterministic rule that only keeps targeted messages for this role.
            rules = list(admin.list_rules(self.topic_name, sub_name))
            has_target_rule = any(getattr(r, "name", "") == "target-role" for r in rules)

            if not has_target_rule:
                # Remove default catch-all rule if present.
                for r in rules:
                    if getattr(r, "name", "") == "$Default":
                        try:
                            admin.delete_rule(self.topic_name, sub_name, "$Default")
                        except Exception:
                            pass

                self._create_rule_compat(admin, self.topic_name, sub_name, "target-role", SqlRuleFilter(f"to_agent = '{agent_role}'"))
                self._log_event("subscription_rule_created", {
                    "agent_role": agent_role,
                    "subscription": sub_name,
                    "rule": "target-role"
                })

    def _create_rule_compat(self, admin, topic_name: str, subscription_name: str, rule_name: str, rule_filter):
        """Compatibility wrapper for create_rule signatures across azure-servicebus versions."""
        # Newer SDK style: filter must be keyword-only.
        try:
            return admin.create_rule(
                topic_name,
                subscription_name,
                rule_name,
                filter=rule_filter
            )
        except TypeError:
            pass

        # Older SDK style: filter as positional argument.
        try:
            return admin.create_rule(
                topic_name,
                subscription_name,
                rule_name,
                rule_filter
            )
        except TypeError:
            pass

        # Fallback by explicit named filter_name if available in some variants.
        return admin.create_rule(
            topic_name,
            subscription_name,
            rule_name,
            filter=rule_filter,
            filter_name=rule_name
        )

    def ensure_subscriptions(self, agent_roles: List[str]):
        """Pre-create role subscriptions before a layer starts to avoid missing early messages."""
        if not self.enabled:
            self._log_event("ensure_subscriptions_skipped", {
                "reason": "service_bus_disabled",
                "agent_roles": agent_roles,
            })
            return

        for role in agent_roles:
            try:
                self._ensure_subscription(role)
            except Exception as e:
                self._log_event("ensure_subscription_error", {
                    "agent_role": role,
                    "error": str(e),
                })

    def _subscription_exists(self, admin, topic_name: str, subscription_name: str) -> bool:
        """Compatibility wrapper across azure-servicebus management API versions."""
        if hasattr(admin, "subscription_exists"):
            try:
                return bool(admin.subscription_exists(topic_name, subscription_name))
            except Exception:
                pass

        if hasattr(admin, "get_subscription"):
            try:
                admin.get_subscription(topic_name, subscription_name)
                return True
            except Exception as exc:
                if ResourceNotFoundError is not None and isinstance(exc, ResourceNotFoundError):
                    return False

        if hasattr(admin, "list_subscriptions"):
            try:
                for sub in admin.list_subscriptions(topic_name):
                    if getattr(sub, "subscription_name", None) == subscription_name:
                        return True
            except Exception:
                pass

        return False

    def send_question(self, from_agent: str, to_agent: str, question: str) -> str:
        if not self.enabled:
            self._log_event("send_question_skipped", {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "reason": "service_bus_disabled"
            })
            return "ERROR: Service Bus is not configured or azure-servicebus package is unavailable"

        envelope = {
            "id": str(uuid.uuid4()),
            "type": "question",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "content": question,
            "timestamp": time.time()
        }

        with ServiceBusClient.from_connection_string(self.connection_str) as client:
            sender = client.get_topic_sender(topic_name=self.topic_name)
            with sender:
                msg = ServiceBusMessage(
                    json.dumps(envelope),
                    application_properties={
                        "to_agent": to_agent,
                        "from_agent": from_agent,
                        "msg_type": "question",
                        "message_id": envelope["id"]
                    }
                )
                sender.send_messages(msg)

            self._log_event("send_question", {
                "id": envelope["id"],
                "from_agent": from_agent,
                "to_agent": to_agent,
                "type": "question",
                "content": question
            })

        return envelope["id"]

    def send_response(self, from_agent: str, to_agent: str, in_reply_to: str, response: str) -> str:
        if not self.enabled:
            self._log_event("send_response_skipped", {
                "from_agent": from_agent,
                "to_agent": to_agent,
                "in_reply_to": in_reply_to,
                "reason": "service_bus_disabled"
            })
            return "ERROR: Service Bus is not configured or azure-servicebus package is unavailable"

        envelope = {
            "id": str(uuid.uuid4()),
            "type": "response",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "in_reply_to": in_reply_to,
            "content": response,
            "timestamp": time.time()
        }

        with ServiceBusClient.from_connection_string(self.connection_str) as client:
            sender = client.get_topic_sender(topic_name=self.topic_name)
            with sender:
                msg = ServiceBusMessage(
                    json.dumps(envelope),
                    application_properties={
                        "to_agent": to_agent,
                        "from_agent": from_agent,
                        "msg_type": "response",
                        "in_reply_to": in_reply_to,
                        "message_id": envelope["id"]
                    }
                )
                sender.send_messages(msg)

            self._log_event("send_response", {
                "id": envelope["id"],
                "from_agent": from_agent,
                "to_agent": to_agent,
                "type": "response",
                "in_reply_to": in_reply_to,
                "content": response
            })

        return envelope["id"]

    def receive_for_agent(self, agent_role: str, max_messages: int = 20, wait_seconds: float = 1.0) -> List[Dict]:
        if not self.enabled:
            self._log_event("receive_skipped", {
                "agent_role": agent_role,
                "reason": "service_bus_disabled"
            })
            return []

        self._ensure_subscription(agent_role)
        received: List[Dict] = []

        with ServiceBusClient.from_connection_string(self.connection_str) as client:
            receiver = client.get_subscription_receiver(
                topic_name=self.topic_name,
                subscription_name=agent_role,
                max_wait_time=wait_seconds
            )
            with receiver:
                msgs = receiver.receive_messages(max_message_count=max_messages, max_wait_time=wait_seconds)
                for msg in msgs:
                    try:
                        body = b"".join([b for b in msg.body]).decode("utf-8")
                        envelope = json.loads(body)
                        received.append(envelope)
                        self._log_event("receive_message", {
                            "agent_role": agent_role,
                            "id": envelope.get("id"),
                            "from_agent": envelope.get("from_agent"),
                            "to_agent": envelope.get("to_agent"),
                            "type": envelope.get("type"),
                            "in_reply_to": envelope.get("in_reply_to"),
                            "content": envelope.get("content", "")
                        })
                    except Exception:
                        self._log_event("receive_message_parse_error", {
                            "agent_role": agent_role
                        })
                        pass
                    receiver.complete_message(msg)

        if len(received) > 0:
            self._log_event("receive_batch_complete", {
                "agent_role": agent_role,
                "count": len(received)
            })

        return received
