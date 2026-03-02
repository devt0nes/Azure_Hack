# service_bus_listener.py
from azure.servicebus.aio import ServiceBusClient
from config import SB_CONN, SB_QUEUE
import cosmos_client as db
import scheduler
import json
import asyncio

async def listen_for_commands():
    """
    Runs as a background task from app startup.
    Polls the Service Bus queue every 5 seconds for EXECUTE_AEG commands.
    On receiving one, fetches the AEG from Cosmos and kicks off the scheduler.
    """
    async with ServiceBusClient.from_connection_string(SB_CONN) as client:
        receiver = client.get_queue_receiver(
            queue_name=SB_QUEUE,
            max_wait_time=5
        )
        async with receiver:
            while True:
                try:
                    msgs = await receiver.receive_messages(
                        max_message_count=10,
                        max_wait_time=5
                    )
                    for msg in msgs:
                        try:
                            payload = json.loads(str(msg))
                            command = payload.get("command")
                            project_id = payload.get("project_id")

                            if not command or not project_id:
                                print(f"[Listener] Malformed message, skipping: {payload}")
                                await receiver.dead_letter_message(msg, reason="Missing command or project_id")
                                continue

                            if command == "EXECUTE_AEG":
                                print(f"[Listener] Received EXECUTE_AEG for project {project_id}")
                                aeg = db.get_aeg(project_id)
                                asyncio.create_task(scheduler.start(aeg))
                                print(f"[Listener] Scheduler started for project {project_id}")
                            else:
                                print(f"[Listener] Unknown command '{command}', skipping")

                            await receiver.complete_message(msg)

                        except json.JSONDecodeError as e:
                            print(f"[Listener] JSON parse error: {e}")
                            await receiver.dead_letter_message(msg, reason="Invalid JSON")

                        except Exception as e:
                            print(f"[Listener] Error processing message: {e}")
                            await receiver.abandon_message(msg)  # Requeues for retry

                except Exception as e:
                    # Outer catch — reconnection issues, network blips, etc.
                    print(f"[Listener] Receiver error, retrying in 10s: {e}")
                    await asyncio.sleep(10)