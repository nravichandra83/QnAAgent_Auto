"""Render the compiled agent graph to docs/agent_graph.mmd (Mermaid) and docs/agent_graph.png.

    python scripts/draw_graph.py

The PNG is rendered by the mermaid.ink web service (only the diagram text is sent).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from langchain_core.runnables.graph import MermaidDrawMethod  # noqa: E402
from langchain_core.runnables.graph_mermaid import draw_mermaid_png  # noqa: E402

from agent.graph import build_graph  # noqa: E402

LLM_NODES = ("classify_intent", "generate_sql", "compose_answer")
MASK_NODES = ("execute_sql",)          # fetches and masks rows in one step


def main() -> None:
    mermaid = build_graph().get_graph().draw_mermaid()
    mermaid = mermaid.rstrip() + (
        "\n\tclassDef llm fill:#dbeafe,stroke:#2563eb,stroke-width:2px"
        "\n\tclassDef mask fill:#fef3c7,stroke:#d97706"
        f"\n\tclass {','.join(LLM_NODES)} llm"
        f"\n\tclass {','.join(MASK_NODES)} mask\n"
    )
    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "agent_graph.mmd").write_text(mermaid, encoding="utf-8")
    print(f"Wrote {out_dir / 'agent_graph.mmd'}")
    try:
        draw_mermaid_png(mermaid, output_file_path=str(out_dir / "agent_graph.png"),
                         draw_method=MermaidDrawMethod.API, background_color="white")
        print(f"Wrote {out_dir / 'agent_graph.png'}")
    except Exception as err:  # network or service failure: Mermaid file is still usable
        print(f"PNG not rendered ({err}); paste agent_graph.mmd into https://mermaid.live instead.")


if __name__ == "__main__":
    main()
