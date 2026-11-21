import asyncio
import logging
import os
from contextlib import aclosing
from uuid import uuid4

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from barista.menu import Menu

APP_NAME = "coffee_barista"
RETRY_MESSAGE = "Hiện chưa thể tra cứu menu. Bạn có thể thử gửi lại câu hỏi."
logger = logging.getLogger(__name__)

INSTRUCTION = """
You are a coffee shop menu assistant. Reply in the language of the customer's
latest message, or Vietnamese when their language is unclear.
For all menu questions, including prices, descriptions, ingredients and follow-ups,
call a menu tool before answering. Use only the tool results as menu facts.
Use get_menu_item for a named item, and search_menu for lists, categories or budgets.
Known category IDs are coffee and tea. Translate category requests to these IDs.
For taste and serving preferences, use search_menu with a tag. For "mát mát"
or "thanh mát", use refreshing. For "uống lạnh" or "có đá", use cold.
If a customer asks for both, recommend only items with both tags in the results.
Combine the tag with any category and price constraints. Explain each suggestion
with its menu description and price.
For allergy questions, ask what ingredient the customer is allergic to if it is
unspecified. For a specific allergen, report any matching ingredients explicitly
listed for a drink. The ingredients field lists selected recipe ingredients only.
Missing ingredients or missing cross-contact data never establish that an item is
allergen-free. Never label a drink safe for an allergy or recommend it as safe.
Ask the customer to confirm ingredients and shared equipment with the shop.
Use integer VND and include_max_price=false for "under", "less than", or "dưới".
Use include_max_price=true for "up to", "at most", or "tối đa".
For a follow-up referring to a single previously discussed item, look up that item
again. If several items could match the reference, ask the customer to choose.
For ambiguous lookups, show the options and ask the customer to choose.
For a missing item or empty search, say no matching item was found in the menu.
If the menu lacks a requested detail, say the menu does not provide enough
information to confirm it. Do not infer ingredients or dietary information.
If asked to place an order, explain that the app supports menu lookup.
"""


class AgentConfigurationError(ValueError):
    pass


def create_runner(menu: Menu) -> Runner:
    keys = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "BARISTA_MODEL")
    project, location, model = (os.getenv(key, "").strip() for key in keys)
    missing = [key for key in keys if not os.getenv(key, "").strip()]
    if missing:
        raise AgentConfigurationError(f"Missing configuration: {', '.join(missing)}")

    agent = Agent(
        name="barista",
        model=Gemini(
            model=model,
            client_kwargs={"vertexai": True, "project": project, "location": location},
        ),
        instruction=INSTRUCTION,
        tools=[menu.get_menu_item, menu.search_menu],
    )
    return Runner(app_name=APP_NAME, agent=agent, session_service=InMemorySessionService())


class Chat:
    def __init__(self, runner: Runner):
        self._runner = runner
        self._loop = asyncio.Runner()
        self._user_id = uuid4().hex
        self.session_id = None
        self.reset()

    def reset(self) -> None:
        self._loop.run(self._reset())

    async def _reset(self) -> None:
        service = self._runner.session_service
        session = await service.create_session(app_name=APP_NAME, user_id=self._user_id)
        previous = self.session_id
        self.session_id = session.id
        if previous is not None:
            await service.delete_session(
                app_name=APP_NAME, user_id=self._user_id, session_id=previous
            )

    def answer(self, prompt: str) -> str:
        try:
            return self._loop.run(self._answer(prompt))
        except Exception:
            logger.exception("Barista request failed")
            return RETRY_MESSAGE

    async def _answer(self, prompt: str) -> str:
        response = []
        events = self._runner.run_async(
            user_id=self._user_id,
            session_id=self.session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        )
        async with aclosing(events):
            async for event in events:
                if event.error_code or event.error_message:
                    raise RuntimeError(f"ADK error: {event.error_code} {event.error_message}")
                for result in event.get_function_responses():
                    if error := (result.response or {}).get("error"):
                        raise RuntimeError(f"ADK tool {result.name} failed: {error}")
                if event.is_final_response() and event.content:
                    response.extend(
                        part.text for part in event.content.parts or []
                        if part.text and not part.thought
                    )
        answer = "\n".join(response).strip()
        if not answer:
            raise RuntimeError("ADK returned no final text")
        return answer

    def close(self) -> None:
        self._loop.close()
