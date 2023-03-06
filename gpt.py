import asyncio
import logging
from typing import cast
import openai
from models import AssistantMessage, Conversation, Message, Role, SystemMessage, UserMessage
from store import Store

class GPTClient:
  __background_tasks: set[asyncio.Task]

  def __init__(self, api_key: str, store: Store, max_message_count: int|None):
    self.__max_message_count = max_message_count
    self.__store = store
    self.__background_tasks = set()

    openai.api_key = api_key

  async def complete(self, current_conversation_id: int|None, chat_id: int, received_msg_id: int, sent_msg_id: int, text: str) -> tuple[AssistantMessage, Conversation]:
    logging.info(f"Completing message for chat {chat_id}, text: '{text}'")

    user_message = UserMessage(received_msg_id, text)
    conversation = None
    if current_conversation_id is not None:
      conversation = self.__store.get_conversation(chat_id, current_conversation_id)
    if not conversation:
      conversation = self.__new_conversation(chat_id, user_message)

    logging.debug(f"Current conversation for chat {chat_id}: {conversation}")

    text = await self.__request(conversation.messages)
    assistant_message = AssistantMessage(sent_msg_id, text, user_message.id)

    logging.info(f"Completed message for chat {chat_id}, message: '{assistant_message}'")

    self.__store.add_message(assistant_message, conversation)

    return (assistant_message, conversation)

  async def retry_last_message(self, conversation: Conversation, sent_msg_id: int) -> tuple[AssistantMessage, Conversation]|None:
    if conversation.last_message and conversation.last_message.role == Role.ASSISTANT:
      self.__store.pop_message(conversation)

    if not conversation.last_message or not conversation.last_message.role == Role.USER:
      return None

    text = await self.__request(conversation.messages)
    assistant_message = AssistantMessage(sent_msg_id, text, cast(UserMessage, conversation.last_message).id)

    logging.info(f"Retried message for conversation {conversation.id}, message: '{assistant_message}'")

    self.__store.add_message(assistant_message, conversation)

    return (assistant_message, conversation)

  def get_all_conversations(self, chat_id: int) -> list[Conversation]:
    return self.__store.get_all_conversations(chat_id)

  def get_conversation(self, chat_id: int, conversation_id: int) -> Conversation|None:
    return self.__store.get_conversation(chat_id, conversation_id)

  def __new_conversation(self, chat_id: int, message: UserMessage) -> Conversation:
    conversation = self.__store.new_conversation(chat_id, message, None)

    task = asyncio.create_task(self.__set_title(conversation, message))
    self.__background_tasks.add(task)
    task.add_done_callback(self.__background_tasks.discard)

    if self.__max_message_count and len(conversation.messages) > self.__max_message_count:
      self.__store.truncate_conversation(conversation, self.__max_message_count)

    return conversation

  async def __set_title(self, conversation: Conversation, message: UserMessage):
    prompt = 'You are a title generator. You will receive a message that initiates a conversation. You will reply with only the title of the conversation without any punctuation mark either at the begining or the end.'
    messages = [
      SystemMessage(prompt),
      message,
    ]

    title = await self.__request(messages)
    self.__store.set_title(conversation, title)

    logging.info(f"Set title for conversation {conversation}: '{title}'")

  async def __request(self, messages: list[Message]) -> str:
    response = openai.ChatCompletion.create(
      model='gpt-3.5-turbo',
      messages=[{'role': message.role, 'content': message.content} for message in messages],
    )
    return response['choices'][0]['message']['content']
