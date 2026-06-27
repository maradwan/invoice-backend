import unittest
from unittest.mock import patch
import os
import sys

# Ensure the path to the directory containing pdf_converter.py is added to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from langchain_openai import OpenAI  # Updated import
from langchain_core.runnables import RunnableLambda
from langchain.prompts import PromptTemplate

class TestLangChain(unittest.TestCase):
    def setUp(self):
        self.llm = OpenAI(model="gpt-4", temperature=0.7)
        self.prompt = PromptTemplate(
            input_variables=["topic"],
            template="Write a short paragraph about {topic}."
        )
        self.chain = RunnableLambda(lambda x: self.llm.invoke(x["topic"]))  # Updated

    @patch('langchain_openai.OpenAI.invoke')  # Correctly mock `invoke`
    def test_chain_output(self, mock_llm_invoke):
        # Mock the LLM response
        mock_llm_invoke.return_value = "This is a test response about AI."

        # Test the chain
        result = self.chain.invoke({"topic": "AI"})  # Updated usage
        self.assertIsInstance(result, str)
        self.assertEqual(result, "This is a test response about AI.")

if __name__ == '__main__':
    unittest.main()
