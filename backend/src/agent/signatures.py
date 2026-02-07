import dspy
from src.agent.prompts import INITIAL_QUERY_PROMPT, FOLLOWUP_QUERY_PROMPT


class InitialQuerySignature(dspy.Signature):
    __doc__ = INITIAL_QUERY_PROMPT

    question: str = dspy.InputField(desc="The user's question")
    answer: str = dspy.OutputField(desc="Your helpful response with data and citations")


class FollowUpQuerySignature(dspy.Signature):
    __doc__ = FOLLOWUP_QUERY_PROMPT

    conversation_history: str = dspy.InputField(desc="Previous messages in the conversation")
    question: str = dspy.InputField(desc="The user's current question")
    answer: str = dspy.OutputField(desc="Your helpful response with data and citations")
