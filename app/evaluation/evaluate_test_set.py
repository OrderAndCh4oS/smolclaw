import asyncio
import inspect

from app.definitions import EVALUATION_DATA_SET
from app.openai_llm import OpenAiLlm
from app.smol_rag import SmolRag
from app.utilities import get_json
from app.logger import logger, set_logger  # <-- Import logger and set_logger

rag = SmolRag()
llm = OpenAiLlm()


async def evaluate_accuracy(query, response, source):
    prompt = inspect.cleandoc(f"""
        Does the <response> accurately answer the <query> in relation to the <source>?
        
        Response parameters:
        You must answer with either "yes" or "no"
        There must be no other content in your response
        
        <query>
        {query}
        </query>
        
        <response>
        {response}
        </response>
        
        <source>
        {source}
        </source>
    """)

    tasks = [
        rag.rate_limited_get_completion(prompt, use_cache=False)
        for _ in range(3)
    ]
    logger.info(f"Evaluating accuracy for query: {query!r}")  # <-- Logging evaluation step
    results = await asyncio.gather(*tasks)

    responses = [
        1 if result == "yes" else 0
        for result in results
        if result in ("yes", "no")
    ]

    for result in results:
        if result not in ("yes", "no"):
            logger.warning(f"Unexpected response (not yes/no): {result!r}")  # <-- Logging unexpected responses

    accuracy = 1 if sum(responses) / len(responses) > 0.5 else 0
    logger.info(
        f"Evaluation result for query {query!r}: {sum(responses)}/{len(responses)} votes yes --> {accuracy}")

    return accuracy


if __name__ == '__main__':
    set_logger("evaluate_test_set.log")  # <-- Set log file

    async def main():
        logger.info("Starting evaluation of test set.")  # <-- Log start

        data_set = get_json(EVALUATION_DATA_SET)
        logger.info(f"Loaded dataset from {EVALUATION_DATA_SET} with {len(data_set)} items.")

        query_tasks = [rag.mix_query(row["query"]) for row in data_set]
        responses = await asyncio.gather(*query_tasks)
        logger.info("Completed generating responses for all queries.")

        accuracy_tasks = [
            evaluate_accuracy(row["query"], response, row["pull_quote"])
            for row, response in zip(data_set, responses)
        ]
        results = await asyncio.gather(*accuracy_tasks)

        score = sum(results) / len(results)
        logger.info(f"Evaluation completed. Final accuracy score: {score:.3f}")
        print(score)

    asyncio.run(main())