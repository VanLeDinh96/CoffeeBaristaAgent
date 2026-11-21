import unittest
from pathlib import Path
from unittest.mock import patch

from google.adk.agents import Agent
from google.adk.models import BaseLlm, LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from streamlit.testing.v1 import AppTest

from barista.agent import APP_NAME, INSTRUCTION, RETRY_MESSAGE, Chat
from barista.menu import Menu

ROOT = Path(__file__).resolve().parents[1]


class FakeGemini(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        contents = llm_request.contents
        part = contents[-1].parts[0]
        if part.function_response:
            result = part.function_response
            if result.name == "search_menu":
                answer = ", ".join(item["name"] for item in result.response["result"])
            else:
                item = result.response["item"]
                answer = (
                    item["description"] if "vị gì" in contents[-3].parts[0].text
                    else f'{item["name"]} {item["price_vnd"]:,} VND'
                )
            reply = types.Part(text=answer)
        elif part.text == "fail":
            raise RuntimeError("Fake Vertex AI failure")
        elif "50.000" in part.text:
            reply = types.Part.from_function_call(
                name="search_menu",
                args={
                    "category_id": "coffee",
                    "max_price_vnd": 50000,
                    "include_max_price": "tối đa" in part.text,
                },
            )
        elif "Latte" in part.text or any(
            p.text and "Latte" in p.text for message in contents[:-1] for p in message.parts or []
        ):
            reply = types.Part.from_function_call(name="get_menu_item", args={"name": "Latte"})
        else:
            reply = types.Part(text="Bạn muốn hỏi món nào?")
        yield LlmResponse(content=types.Content(role="model", parts=[reply]))


def make_runner(menu=None):
    menu = menu or Menu(ROOT / "menu.json")
    return Runner(
        app_name=APP_NAME,
        agent=Agent(
            name="barista",
            model=FakeGemini(model="fake-gemini"),
            instruction=INSTRUCTION,
            tools=[menu.get_menu_item, menu.search_menu],
        ),
        session_service=InMemorySessionService(),
    )


class ChatFlowTests(unittest.TestCase):
    def test_adk_budget_tool(self):
        chat = Chat(make_runner())
        self.addCleanup(chat.close)
        self.assertEqual(chat.answer("Cà phê dưới 50.000 đồng?"), "Cà phê đen, Latte")
        self.assertEqual(
            chat.answer("Cà phê tối đa 50.000 đồng?"), "Cà phê đen, Latte, Cappuccino"
        )

    def test_streamlit_followup_and_reset(self):
        with patch("barista.agent.create_runner", side_effect=make_runner):
            app = AppTest.from_file(str(ROOT / "app.py")).run()
            self.assertFalse(app.exception)
            chat = app.session_state["chat"]
            self.addCleanup(chat.close)
            previous = chat.session_id
            app.chat_input[0].set_value("Latte giá bao nhiêu?").run()
            self.assertIn("45,000", app.chat_message[-1].markdown[0].value)
            app.chat_input[0].set_value("Món đó có vị gì?").run()
            self.assertIn("vị nhẹ", app.chat_message[-1].markdown[0].value)
            app.button[0].click().run()
            self.assertNotEqual(previous, chat.session_id)
            self.assertEqual(len(app.chat_message), 0)
            app.chat_input[0].set_value("Món đó có vị gì?").run()
            self.assertEqual(app.chat_message[-1].markdown[0].value, "Bạn muốn hỏi món nào?")

    def test_model_error_is_logged_and_customer_can_retry(self):
        chat = Chat(make_runner())
        self.addCleanup(chat.close)
        with self.assertLogs("barista.agent", level="ERROR") as logs:
            self.assertEqual(chat.answer("fail"), RETRY_MESSAGE)
        self.assertIn("Fake Vertex AI failure", logs.output[0])
        self.assertIn("45,000", chat.answer("Latte giá bao nhiêu?"))
