"""
Standalone script: generate query rewrite pairs for SFT training.

Usage:
    python generate_rewrite_dataset.py \
        --input eval_test_set.json \
        --output rewrite_sft_dataset.json \
        --concurrency 5

Requires:
    pip install httpx
    Environment variable: DEEPSEEK_API_KEY
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0

REWRITE_TYPES = ["expansion", "keyword_bridging", "disambiguation"]

SYSTEM_PROMPT = """\
You are a query rewriting assistant for an academic paper retrieval system.
Given an original search query, produce rewritten versions that would improve \
retrieval of relevant passages from a knowledge base of ML/AI research papers.

You will be told which rewrite type to produce. Follow the type definition exactly.

Rewrite type definitions:

- expansion: Add implicit context, expand abbreviations, and spell out the \
  full intent behind a terse or ambiguous query. Turn keyword-style queries \
  into complete questions. Example: "PPO clipping" → "How does the clipping \
  mechanism in Proximal Policy Optimization constrain policy updates to \
  ensure training stability?"

- keyword_bridging: Supplement the query with synonyms, related technical \
  terms, or canonical phrases that are likely to appear in academic papers \
  but are absent from the original query. Preserve the original intent. \
  Example: "how to reduce reward hacking" → "techniques to mitigate reward \
  hacking and reward overoptimization such as KL penalty and constrained \
  policy optimization"

- disambiguation: If the query contains terms with multiple meanings in ML \
  context, produce a version that resolves the ambiguity toward the most \
  likely research interpretation. If the query is already unambiguous, \
  rephrase it to be more precise without changing meaning. Example: \
  "what is the policy in RLHF" → "what role does the language model policy \
  play in reinforcement learning from human feedback"

Rules:
- Output ONLY the rewritten query text, nothing else.
- Keep the rewritten query in the SAME LANGUAGE as the original.
- Do NOT add information that contradicts or goes beyond the original intent.
- Aim for 15-40 words. Do not produce excessively long rewrites.
- If the original query is already well-formed for the given rewrite type \
  and you cannot meaningfully improve it, return the original query unchanged.\
"""


# ── API call ───────────────────────────────────────────────

async def call_deepseek(
    client: httpx.AsyncClient,
    api_key: str,
    original_query: str,
    rewrite_type: str,
    semaphore: asyncio.Semaphore,
) -> str | None:
    """Call DeepSeek API to generate one rewrite. Returns rewritten text or None on failure."""
    user_message = (
        f"Rewrite type: {rewrite_type}\n"
        f"Original query: {original_query}"
    )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        async with semaphore:
            try:
                resp = await client.post(
                    f"{DEEPSEEK_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if resp.status_code == 429:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)", wait, attempt, MAX_RETRIES)
                    await asyncio.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # Sanity: reject empty or suspiciously short rewrites
                if len(content) < 5:
                    logger.warning("Rewrite too short, discarding: %r", content)
                    return None
                return content

            except httpx.HTTPStatusError as e:
                logger.error("HTTP %d for query %r (attempt %d): %s", e.response.status_code, original_query[:50], attempt, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.error("Connection error for query %r (attempt %d): %s", original_query[:50], attempt, e)
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)

    logger.error("All retries exhausted for query: %r", original_query[:60])
    return None


# ── Per-query processing ──────────────────────────────────

async def process_query(
    client: httpx.AsyncClient,
    api_key: str,
    record: dict,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """Generate all rewrite variants for a single eval query record."""
    original_query = record["query"]
    results = []

    tasks = [
        call_deepseek(client, api_key, original_query, rtype, semaphore)
        for rtype in REWRITE_TYPES
    ]
    rewrites = await asyncio.gather(*tasks)

    for rtype, rewritten in zip(REWRITE_TYPES, rewrites):
        if rewritten is None:
            continue
        # Skip if rewrite is identical to original (no improvement possible)
        if rewritten.strip().lower() == original_query.strip().lower():
            logger.debug("Rewrite identical to original, skipping: %r [%s]", original_query[:50], rtype)
            continue

        results.append({
            "original_query": original_query,
            "rewritten_query": rewritten,
            "rewrite_type": rtype,
            # Carry over for RL reward computation
            "ground_truth_chunk_ids": record.get("ground_truth_chunk_ids", []),
            "source_document_id": record.get("source_document_id", ""),
            "original_metadata": record.get("metadata", {}),
        })

    return results


# ── Main ──────────────────────────────────────────────────

async def main(input_path: Path, output_path: Path, concurrency: int) -> None:
    # api_key = os.environ.get("DEEPSEEK_API_KEY")
    api_key = "sk-4242b2ca280142b28aa1c0adbde3b542"
    if not api_key:
        logger.error("DEEPSEEK_API_KEY environment variable not set")
        sys.exit(1)

    # Load eval set
    with open(input_path, "r", encoding="utf-8") as f:
        eval_records = json.load(f)
    logger.info("Loaded %d queries from %s", len(eval_records), input_path)

    semaphore = asyncio.Semaphore(concurrency)
    all_results: list[dict] = []
    failed_count = 0

    async with httpx.AsyncClient() as client:
        # Process in batches to show progress
        batch_size = 20
        for batch_start in range(0, len(eval_records), batch_size):
            batch = eval_records[batch_start : batch_start + batch_size]
            batch_tasks = [
                process_query(client, api_key, record, semaphore)
                for record in batch
            ]
            batch_results = await asyncio.gather(*batch_tasks)

            for query_results in batch_results:
                if not query_results:
                    failed_count += 1
                all_results.extend(query_results)

            logger.info(
                "Progress: %d/%d queries processed, %d pairs generated",
                min(batch_start + batch_size, len(eval_records)),
                len(eval_records),
                len(all_results),
            )

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    logger.info("Done. %d rewrite pairs written to %s", len(all_results), output_path)
    logger.info(
        "Stats: %d input queries → %d pairs (%.1f per query avg), %d queries with partial/full failure",
        len(eval_records),
        len(all_results),
        len(all_results) / max(len(eval_records), 1),
        failed_count,
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="Generate query rewrite SFT dataset via DeepSeek API")
    parser.add_argument("--input", "-i", type=Path, required=True, help="Path to eval test set JSON")
    parser.add_argument("--output", "-o", type=Path, default=Path("rewrite_sft_dataset.json"), help="Output path")
    parser.add_argument("--concurrency", "-c", type=int, default=5, help="Max concurrent API calls (default: 5)")
    args = parser.parse_args()

    if not args.input.exists():
        logger.error("Input file not found: %s", args.input)
        sys.exit(1)

    asyncio.run(main(args.input, args.output, args.concurrency))


if __name__ == "__main__":
    cli()