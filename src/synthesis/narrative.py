import os
from typing import Optional
import litellm


class NarrativeSynthesizer:
    """Synthesize narrative from lineage chain and localized comments using LLM."""

    def __init__(self, model: str = None):
        if model is None:
            model = os.environ.get("ARC_MODEL", "gemini/gemini-2.0-flash")
        self.model = model

        model_lower = model.lower()

        if "openai" in model_lower:
            self.api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get(
                "CLAUDE_API_KEY"
            )
        elif "claude" in model_lower or "anthropic" in model_lower:
            self.api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get(
                "ANTHROPIC_API_KEY"
            )
        elif "gemini" in model_lower:
            self.api_key = (
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("CLAUDE_API_KEY")
            )
        else:
            self.api_key = (
                os.environ.get("GEMINI_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("CLAUDE_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY")
            )

    def synthesize(
        self,
        lineage_data: list[dict],
        localized_comments: list[dict],
        current_code: str,
        function_name: str,
    ) -> str:
        """Generate a 5-sentence brief explaining what shaped this code."""

        if not self.api_key:
            return "Error: No API key set. Set GEMINI_API_KEY, OPENAI_API_KEY, or CLAUDE_API_KEY."

        context = self._build_context(
            lineage_data, localized_comments, current_code, function_name
        )

        prompt = f"""You are a senior software engineer investigating why a function exists in its current form.
Your task is to write a brief (5 sentences max) explaining the decision history of this function.

The output should answer:
1. What decisions shaped this code?
2. What was tried and abandoned?
3. What are the highest-risk assumptions baked into the current implementation?

Context:
{context}

Generate a concise 5-sentence brief:"""

        try:
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                api_key=self.api_key,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error generating narrative: {str(e)}"

    def _build_context(
        self,
        lineage_data: list[dict],
        localized_comments: list[dict],
        current_code: str,
        function_name: str,
    ) -> str:
        """Build context string from lineage and comments."""

        lines = []
        lines.append(f"## Function: {function_name}\n")
        lines.append(f"### Current Implementation:\n{current_code}\n")

        if lineage_data:
            lines.append("### Historical Versions:")
            for i, entry in enumerate(lineage_data[:5]):
                lines.append(f"\n--- Version {i + 1} ---")
                lines.append(f"Commit: {entry.get('commit_hash', 'unknown')[:8]}")
                lines.append(f"Change type: {entry.get('change_type', 'unknown')}")
                lines.append(f"Code:\n{entry.get('content', '')}")

        if localized_comments:
            lines.append("\n### Relevant Review Comments:")
            for comment in localized_comments[:10]:
                lines.append(
                    f"- [{comment.get('author', 'unknown')}]: {comment.get('body', '')}"
                )

        return "\n".join(lines)

    def synthesize_simple(
        self, lineage_data: list[dict], localized_comments: list[dict]
    ) -> str:
        """Simple synthesis without LLM - just summarize the data."""

        summary_parts = []

        if lineage_data:
            summary_parts.append(
                f"Found {len(lineage_data)} historical versions of this code."
            )

            change_types = {}
            for entry in lineage_data:
                ct = entry.get("change_type", "unknown")
                change_types[ct] = change_types.get(ct, 0) + 1

            if change_types:
                types_str = ", ".join(f"{k}: {v}" for k, v in change_types.items())
                summary_parts.append(f"Change types: {types_str}")

        if localized_comments:
            summary_parts.append(
                f"Found {len(localized_comments)} relevant review comments."
            )

        if not summary_parts:
            return "No historical data found for this function."

        return " | ".join(summary_parts)
