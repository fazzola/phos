import asyncio

from robot.ai.agent import RobotAgent
from robot.ai.provider import LLMMessage, LLMProvider, LLMResponse


class FakeProvider(LLMProvider):
    async def generate(self, messages, *, tools=(), temperature=None):
        return LLMResponse(text="ciao", model="fake")


def test_agent_depends_on_llm_provider_contract():
    response = asyncio.run(
        RobotAgent(FakeProvider()).respond([LLMMessage(role="user", content="ciao")])
    )
    assert response.text == "ciao"
    assert response.model == "fake"
