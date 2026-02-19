# Todo: Extract snippets, generate query and responses. Write to json.
import asyncio
import inspect
import re

import nltk
from aiolimiter import AsyncLimiter
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from nltk.translate.meteor_score import meteor_score

from app.definitions import INPUT_DOCS_DIR, EVALUATION_DATA_SET
from app.logger import logger, set_logger
from app.openai_llm import OpenAiLlm
from app.utilities import get_docs, read_file, create_file_if_not_exists, write_json

# Note: Make sure to download the NLTK packages, if you haven't already
# nltk.download('punkt')
# nltk.download('punkt_tab')
# nltk.download('wordnet')

llm = OpenAiLlm()
llm_limiter = AsyncLimiter(max_rate=100, time_period=1)


async def rate_limited_get_completion(*args, **kwargs):
    async with llm_limiter:
        return await llm.get_completion(*args, **kwargs)


def calculate_bleu(reference_text: str, candidate_text: str) -> float:
    smoothing = SmoothingFunction().method1
    reference_tokens = nltk.word_tokenize(reference_text.lower())
    candidate_tokens = nltk.word_tokenize(candidate_text.lower())
    return sentence_bleu([reference_tokens], candidate_tokens, smoothing_function=smoothing)


def calculate_meteor(reference_text: str, candidate_text: str) -> float:
    reference_tokens = nltk.word_tokenize(reference_text.lower())
    candidate_tokens = nltk.word_tokenize(candidate_text.lower())
    return meteor_score([reference_tokens], candidate_tokens)


async def process_doc(doc, additional_context=None):
    logger.info(f"Processing document: {doc}")
    content = read_file(doc)
    raw_pull_quotes = await rate_limited_get_completion(inspect.cleandoc(f"""
                Extract up to ten pull quote facts from this document, you must pull the exact copy used in the document.

                Remove all markdown formatting
                Use no markdown formatting in your response
                Each pull quote should be on a single line

                <content>
                {content}
                </content>
            """))

    []

    pull_quotes = [pull_quote.strip() for pull_quote in re.sub(r'\n+', '\n', raw_pull_quotes).strip().split('\n')]
    logger.info(f"Extracted {len(pull_quotes)} pull quotes from {doc}")
    pull_quote_tasks = [process_pull_quote(pull_quote, content, additional_context) for pull_quote in pull_quotes]
    results = await asyncio.gather(*pull_quote_tasks)
    return results

async def process_pull_quote(pull_quote, content, additional_context=None):
    logger.info(f"Processing pull quote: {pull_quote}")
    prompt = inspect.cleandoc(f"""
        Ask a question that relates to the pull quote and an expected response that you might expect from a rag that contains this information

        The question and response must directly target this pull quote.

        Use no markdown formatting in your response
        The question and response should each be on a single line: 
         - the question must be on the first line
         - the response must be on the second line
        respond with only the question and response

        <content>
        {content}
        </content>

        <pull-quote>
        {pull_quote}
        </pull-quote>
    """)

    if additional_context is not None:
        prompt += f"\n\n<additional-context>\n{additional_context}\n</additional-context>"

    raw_query_response = await rate_limited_get_completion(prompt)

    clean_result = [line.strip() for line in re.sub(r'\n+', '\n', raw_query_response).strip().split('\n')]
    if len(clean_result) != 2:
        logger.info(f"Pull quote skipped due to unexpected answer format: {pull_quote}")
        return None
    (query, response) = clean_result
    bleu = calculate_bleu(pull_quote, response)
    meteor = calculate_meteor(pull_quote, response)
    if bleu >= 0.85:
        logger.info(f"Pull quote skipped due to high BLEU score (likely identical): {pull_quote}")
        return None
    # Note: chuck out results that match too closely they're likely identical to the initial query
    logger.info(f"Generated query/response pair for pull quote (BLEU={bleu:.2f}, METEOR={meteor:.2f})")
    return {
        "pull_quote": pull_quote,
        "query": query,
        "response": response,
        "bleu": bleu,
        "meteor": meteor
    }


if __name__ == '__main__':
    set_logger("generate_test_set.log")

    async def main():

        logger.info("Starting test set generation process.")
        logger.info(f"INPUT_DOCS_DIR: {INPUT_DOCS_DIR}")
        logger.info(f"EVALUATION_DATA_SET: {EVALUATION_DATA_SET}")

        create_file_if_not_exists(EVALUATION_DATA_SET, "")
        docs = get_docs(INPUT_DOCS_DIR)
        logger.info(f"Found {len(docs)} documents to process.")

        process_doc_tasks = [process_doc(doc, additional_context="SmolRag is a lightweight Retrieval-Augmented Generation system") for doc in docs]
        results = await asyncio.gather(*process_doc_tasks)
        clean_results = [result for sublist in results for result in sublist if result is not None]
        logger.info(f"Writing {len(clean_results)} query/response pairs to {EVALUATION_DATA_SET}")
        write_json(EVALUATION_DATA_SET, clean_results)
        logger.info("Test set generation completed successfully.")

    asyncio.run(main())