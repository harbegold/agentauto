#!/usr/bin/env python3
"""CLI entrypoint: run browser navigation challenge agent."""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from agent.runner import run_challenge, write_results, create_submission_zip

OUT_DIR = Path("out")
SUBMISSION_ZIP = Path("submission.zip")
MAX_ITERATIONS = 30
TARGET_STEPS = 30
TARGET_SECONDS = 300  # 5 minutes


def main() -> int:
    parser = argparse.ArgumentParser(description="Browser Navigation Challenge Agent")
    parser.add_argument("url", nargs="?", default="https://serene-frangipane-7fd25b.netlify.app/", help="Challenge URL")
    parser.add_argument("--headful", action="store_true", help="Run browser visible (live view)")
    parser.add_argument("--slowmo", type=int, default=0, metavar="MS", help="Slow down operations by MS milliseconds")
    parser.add_argument("--video", action="store_true", default=True, help="Record video to out/videos (default: True)")
    parser.add_argument("--no-video", action="store_false", dest="video", help="Disable video recording")
    parser.add_argument("--trace", action="store_true", default=False, help="Enable Playwright tracing (saved to out/traces/run_trace.zip)")
    parser.add_argument("--timeout-minutes", type=int, default=5, help="Timeout per run in minutes (default: 5 for challenge)")
    parser.add_argument("--no-block-resources", action="store_true", help="Do not block images/fonts/media")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR, help="Output directory")
    parser.add_argument("--max-iterations", type=int, default=MAX_ITERATIONS, help="Max iterations until 30 steps in <5 min (default: 30)")
    parser.add_argument("--continue-on-error", action="store_true", help="On step failure, continue to next step (partial scoring)")
    parser.add_argument("--diagnostic-screenshots", action="store_true", help="Take a screenshot every second for 60s (out/diagnostic/, timestamped) for analysis")
    parser.add_argument("--run-until-30", action="store_true", default=True, help="Keep running until 30 steps in under 5 min (default: on)")
    parser.add_argument("--no-run-until-30", action="store_false", dest="run_until_30", help="Single run only, no loop until 30")
    # LLM fallback (opt-in; requires OPENAI_API_KEY)
    parser.add_argument("--use-llm", action="store_true", help="Use LLM fallback when deterministic extraction fails")
    parser.add_argument("--llm-provider", type=str, default="openai", choices=["openai", "anthropic"], help="LLM provider: openai (OPENAI_API_KEY) or anthropic (ANTHROPIC_API_KEY) (default: openai)")
    parser.add_argument("--max-llm-calls", type=int, default=10, metavar="N", help="Max LLM calls per run (default: 10)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", metavar="MODEL", help="Model name for chosen provider (e.g. gpt-4o-mini, claude-3-5-haiku-20241022)")
    args = parser.parse_args()

    url = args.url.strip()
    if not url:
        url = "https://serene-frangipane-7fd25b.netlify.app/"

    # Resolve API key for chosen LLM provider
    from agent.llm_providers import get_api_key_for_provider
    llm_api_key = get_api_key_for_provider(args.llm_provider) if args.use_llm else ""
    if args.use_llm and not llm_api_key:
        print(f"Warning: --use-llm set but {args.llm_provider.upper()}_API_KEY not set; LLM fallback disabled.", file=sys.stderr)
        args.use_llm = False

    # Per-run folder: each invocation writes to out/run_<timestamp>/ so iterations don't overwrite previous runs
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    run_dir = args.out_dir / f"run_{run_ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "videos").mkdir(parents=True, exist_ok=True)
    (run_dir / "traces").mkdir(parents=True, exist_ok=True)
    if args.diagnostic_screenshots:
        (run_dir / "diagnostic").mkdir(parents=True, exist_ok=True)
    print(f"Run output: {run_dir}", file=sys.stderr)

    live_status_path = (run_dir / "live_status.md").resolve()
    best_solved = 0
    best_stats = None

    def write_live_status(iteration: int, step_reached: int, extra: str = "") -> None:
        """Write live_status.md so user can watch progress."""
        try:
            live_status_path.parent.mkdir(parents=True, exist_ok=True)
            from datetime import datetime, timezone
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            with open(live_status_path, "w", encoding="utf-8") as f:
                f.write("# Live Run Status\n\n")
                f.write(f"**Iteration {iteration}:** got to step **{step_reached}**\n\n")
                if extra:
                    f.write(f"{extra}\n\n")
                f.write(f"*Updated: {ts}*\n")
        except Exception as e:
            print(f"Warning: could not write live_status.md: {e}", file=sys.stderr)

    for iteration in range(1, args.max_iterations + 1):
        print(f"\n--- Iteration {iteration}/{args.max_iterations} ---", file=sys.stderr)
        write_live_status(iteration, 0, "Starting...")
        try:
            stats = asyncio.run(
                asyncio.wait_for(
                    run_challenge(
                        url=url,
                        out_dir=run_dir,
                        headless=not args.headful,
                        slow_mo=args.slowmo if args.slowmo > 0 else None,
                        video=args.video,
                        trace=args.trace,
                        timeout_minutes=args.timeout_minutes,
                        resource_blocking=not args.no_block_resources,
                        max_retries_per_step=3,
                        continue_on_error=args.continue_on_error,
                        diagnostic_screenshots=args.diagnostic_screenshots,
                        use_llm=args.use_llm,
                        max_llm_calls=args.max_llm_calls,
                        llm_model=args.model,
                        llm_provider=args.llm_provider,
                        openai_api_key=llm_api_key if args.use_llm else None,
                        live_status_path=live_status_path,
                        iteration=iteration,
                        shared_learned_dir=args.out_dir,
                    ),
                    timeout=args.timeout_minutes * 60,
                )
            )
            write_results(run_dir, stats, iteration=iteration)
            if stats.solved_count > best_solved:
                best_solved = stats.solved_count
                best_stats = stats
            total_sec = stats.total_seconds
            print(f"Solved {stats.solved_count}/{stats.attempted_count} steps in {total_sec:.1f}s", file=sys.stderr)
            if stats.token_usage:
                print(f"Token usage: {stats.token_usage}", file=sys.stderr)
            if stats.token_cost_usd is not None:
                print(f"Token cost: ${stats.token_cost_usd:.4f}", file=sys.stderr)
            # Success: 30 steps in under 5 minutes
            if stats.solved_count >= TARGET_STEPS and total_sec <= TARGET_SECONDS:
                print("All 30 steps completed in under 5 minutes.", file=sys.stderr)
                break
            if stats.solved_count >= TARGET_STEPS:
                print(f"Completed 30 steps but took {total_sec:.1f}s (target <{TARGET_SECONDS}s). Continuing.", file=sys.stderr)
            if not args.run_until_30:
                break
        except asyncio.TimeoutError:
            print(f"Iteration {iteration} timed out after {args.timeout_minutes} min.", file=sys.stderr)
        except KeyboardInterrupt:
            print("\nInterrupted by user.", file=sys.stderr)
            break
        except Exception as e:
            print(f"Iteration {iteration} error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)

    # Generate submission zip from this run's folder
    run_dir.mkdir(parents=True, exist_ok=True)
    if best_stats:
        write_results(run_dir, best_stats)
    create_submission_zip(run_dir, SUBMISSION_ZIP)
    print(f"Submission zip: {SUBMISSION_ZIP}", file=sys.stderr)
    success = best_solved >= TARGET_STEPS and (best_stats and best_stats.total_seconds <= TARGET_SECONDS)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
