from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.config import get_settings


def get_chat_model(callbacks: list[BaseCallbackHandler] | None = None) -> BaseChatModel:
    """OpenAI chat model; OPENAI_API_KEY is read from the environment (.env)."""
    return ChatOpenAI(model=get_settings().openai_model, temperature=0, callbacks=callbacks)
