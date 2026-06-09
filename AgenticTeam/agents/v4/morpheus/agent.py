from AgenticTeam.scripts.v4_interfaces import V4Agent, V4AgentContext
from AgenticTeam.scripts.v4_contracts import EventV4, TaskPackV4

class MorpheusAgent(V4Agent):
    """
    The Morpheus agent (Worker) that performs the actual task execution.
    """
    def __init__(self, name: str = "Morpheus"):
        self.name = name

    def get_agent_name(self) -> str:
        return self.name

    async def handle_event(self, event: EventV4, context: V4AgentContext) -> None:
        if event.event_type == "ASSIGN_WORK":
            await self._handle_assign_work(event, context)
        elif event.event_type == "WORK_RESULT_SUBMITTED":
            # In a real scenario, Morpheus might do something with results, 
            # but here it's primarily the producer.
            pass

    async def _handle_assign_work(self, event: EventV4, context: V4AgentContext) -> None:
        task_pack = event.payload
        if not isinstance(task_pack, TaskPackV4):
            return

        print(f"[{self.name}] Received work for task: {task_pack.task_id}")
        
        # Simulate work execution
        import asyncio
        await asyncio.sleep(0.1)
        
        # Prepare the result
        from AgenticTeam.scripts.v4_contracts import WorkResultV4
        result = WorkResultV4(
            task_id=task_pack.task_id,
            status="completed",
            output=f"Work completed for {task_pack.task_id}",
            evidence={"timestamp": "2023-10-27T10:00:00Z"} # Mock evidence
        )
        
        # Emit the result back to the system
        await context.emit("WORK_RESULT_SUBMITTED", result)
