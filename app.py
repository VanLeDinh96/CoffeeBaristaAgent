import logging
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from barista.agent import AgentConfigurationError, Chat, create_runner
from barista.menu import Menu, MenuConfigurationError

ROOT = Path(__file__).resolve().parent
logger = logging.getLogger(__name__)


def main() -> None:
    st.set_page_config(page_title="Coffee Barista", page_icon="☕")
    st.title("Coffee Barista")
    load_dotenv(ROOT / ".env")

    try:
        if "chat" not in st.session_state:
            menu = Menu(ROOT / "menu.json")
            st.session_state.chat = Chat(create_runner(menu))
            st.session_state.messages = []
    except (MenuConfigurationError, AgentConfigurationError):
        logger.exception("Barista configuration is invalid")
        st.error("Ứng dụng chưa được cấu hình đúng. Vui lòng liên hệ quản trị viên.")
        st.stop()

    chat = st.session_state.chat
    if st.button("Cuộc trò chuyện mới"):
        chat.reset()
        st.session_state.messages = []

    messages = st.session_state.messages
    for role, message in messages:
        st.chat_message(role).markdown(message)

    if prompt := st.chat_input("Hỏi về món hoặc giá trong menu"):
        messages.append(("user", prompt))
        st.chat_message("user").markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Đang tra cứu menu…"):
                answer = chat.answer(prompt)
            st.markdown(answer)
        messages.append(("assistant", answer))


if __name__ == "__main__":
    main()
