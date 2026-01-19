import argparse
import os


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="embedded-memory")
    sub = parser.add_subparsers(dest="command", required=True)

    observe = sub.add_parser("observe", help="Append an observation (JSONL)")
    observe.add_argument(
        "--store-root",
        default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."),
        help="Project root containing spec/ data/ runs/ (or EMBEDDED_MEMORY_ROOT)",
    )
    observe.add_argument("--run-id", default=None)
    observe.add_argument("--model-id", required=True)
    observe.add_argument("--fw-version", required=True)
    observe.add_argument("--source", required=True, choices=["chat", "analysis", "report", "system"])
    observe.add_argument("--content", required=True)
    observe.add_argument("--instance-id", default=None)

    compile_p = sub.add_parser("compile", help="Prepare/apply consolidation")
    compile_sub = compile_p.add_subparsers(dest="compile_cmd", required=True)
    prepare = compile_sub.add_parser("prepare", help="Build compile_request.json for host LLM")
    prepare.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    prepare.add_argument("--run-id", default=None)
    prepare.add_argument("--out", default="compile_request.json")
    prepare.add_argument("--limit", type=int, default=200, help="Max observations to include")

    apply_p = compile_sub.add_parser("apply", help="Validate + apply compile_response.json")
    apply_p.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    apply_p.add_argument("--in", dest="input_path", required=True)
    apply_p.add_argument("--request", dest="request_path", default=None, help="Optional compile_request.json to enforce policy/request_id")

    search = sub.add_parser("search", help="Search rules for a model+fw")
    search.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    search.add_argument("--model-id", required=True)
    search.add_argument("--fw-version", required=True)

    show = sub.add_parser("show", help="Show a specific rule file")
    show.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    show.add_argument("--model-id", required=True)
    show.add_argument("--rule-id", required=True)

    resolve = sub.add_parser("resolve", help="Resolve effective profile (JSON)")
    resolve.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    resolve.add_argument("--model-id", required=True)
    resolve.add_argument("--fw-version", required=True)
    resolve.add_argument("--instance-id", default=None)

    timeline = sub.add_parser("timeline", help="Show observations + apply history")
    timeline.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    timeline.add_argument("--model-id", default=None)
    timeline.add_argument("--run-id", default=None)
    timeline.add_argument("--limit", type=int, default=200)

    diff = sub.add_parser("diff", help="Diff two saved revisions for a rule")
    diff.add_argument("--store-root", default=os.environ.get("EMBEDDED_MEMORY_ROOT", "."))
    diff.add_argument("--model-id", required=True)
    diff.add_argument("--rule-id", required=True)
    diff.add_argument("--from", dest="rev_from", required=True)
    diff.add_argument("--to", dest="rev_to", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "observe":
        from .store import MemoryStore

        store = MemoryStore.from_root(args.store_root)
        store.observe(
            run_id=args.run_id,
            model_id=args.model_id,
            fw_version=args.fw_version,
            instance_id=args.instance_id,
            source=args.source,
            content=args.content,
        )
        return 0

    if args.command == "compile" and args.compile_cmd == "prepare":
        from .store import MemoryStore

        store = MemoryStore.from_root(args.store_root)
        store.compile_prepare(run_id=args.run_id, out_path=args.out, limit=args.limit)
        return 0

    if args.command == "compile" and args.compile_cmd == "apply":
        from .store import MemoryStore

        store = MemoryStore.from_root(args.store_root)
        store.compile_apply(input_path=args.input_path, request_path=args.request_path)
        return 0

    from .store import MemoryStore

    store = MemoryStore.from_root(args.store_root)
    if args.command == "search":
        store.search(model_id=args.model_id, fw_version=args.fw_version)
        return 0
    if args.command == "show":
        store.show(model_id=args.model_id, rule_id=args.rule_id)
        return 0
    if args.command == "resolve":
        store.resolve(model_id=args.model_id, fw_version=args.fw_version, instance_id=args.instance_id)
        return 0
    if args.command == "timeline":
        store.timeline(model_id=args.model_id, run_id=args.run_id, limit=args.limit)
        return 0
    if args.command == "diff":
        store.diff(model_id=args.model_id, rule_id=args.rule_id, rev_from=args.rev_from, rev_to=args.rev_to)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2
