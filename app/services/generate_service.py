import asyncio
import json

from openai import AsyncOpenAI

from app.config import get_settings

_client: AsyncOpenAI | None = None
_semaphore: asyncio.Semaphore | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().openai_max_concurrency)
    return _semaphore


MODEL = get_settings().openai_model

# ── Prompts ───────────────────────────────────────────────────────────────────

_PROMPTS = {
    "mnemonic": {
        "system": (
            "You are a NEET expert who creates powerful, memorable mnemonics for Biology, "
            "Chemistry, and Physics. Your mnemonics are precise, exam-focused, and easy to recall "
            "under pressure. You create acronyms, phrase mnemonics, and keyword associations."
        ),
        "user": (
            "Create strong mnemonics for NEET students studying '{section}' from the chapter '{chapter}'.\n\n"
            "Topic content:\n{content}\n\n"
            "Generate:\n"
            "1. **Acronym mnemonics** — for lists, classifications, or sequences in this topic\n"
            "2. **Phrase mnemonics** — catchy sentences where first letters represent key terms\n"
            "3. **Keyword associations** — link difficult terms to something familiar\n\n"
            "For each mnemonic, clearly show WHAT it helps remember and HOW to use it. "
            "Focus only on what a NEET student must memorize from this specific topic."
        ),
    },

    "story": {
        "system": (
            "You are a master science storyteller who explains complex NEET concepts through vivid, "
            "engaging narratives and analogies. Your stories make abstract biology, chemistry, and physics "
            "processes feel real and unforgettable. Every key concept must appear in the story."
        ),
        "user": (
            "Explain '{section}' from the chapter '{chapter}' as an engaging story or analogy for a NEET student.\n\n"
            "Topic content:\n{content}\n\n"
            "Write a narrative where:\n"
            "- Characters or objects represent the biological/chemical/physical entities\n"
            "- Events in the story map to the actual process or concept\n"
            "- Every key fact from the topic is covered naturally in the story\n"
            "- End with a **'Story → Science' key mapping** (e.g., 'The General = DNA Polymerase')\n\n"
            "Make it vivid and memorable. NEET-relevant facts must not be skipped."
        ),
    },

    "chunking": {
        "system": (
            "You are a NEET preparation expert who breaks complex topics into small, digestible micro-concepts. "
            "Each chunk is self-contained and can be learned in under 2 minutes. "
            "You reduce overwhelm and build understanding step by step."
        ),
        "user": (
            "Break down '{section}' from '{chapter}' into clear micro-concept chunks for a NEET student.\n\n"
            "Topic content:\n{content}\n\n"
            "Structure your response as:\n"
            "**Chunk 1: [Name]** — 2-3 sentences explaining just this micro-concept\n"
            "**Chunk 2: [Name]** — ...\n"
            "... and so on.\n\n"
            "Rules:\n"
            "- Each chunk must be independent and self-contained\n"
            "- Use simple language, no jargon without explanation\n"
            "- End each chunk with one **'Remember:'** line — the single most important takeaway\n"
            "- Cover the entire topic completely across all chunks"
        ),
    },

    "feynman": {
        "system": (
            "You are a NEET tutor using the Feynman Technique — you explain concepts as if teaching "
            "a 15-year-old student who is encountering this topic for the first time. "
            "You use zero unexplained jargon, real-world analogies, and build understanding from the ground up."
        ),
        "user": (
            "Use the Feynman Technique to explain '{section}' from '{chapter}' to a NEET student.\n\n"
            "Topic content:\n{content}\n\n"
            "Follow this structure:\n"
            "1. **Simple Explanation** — Explain it like the student has never heard of it\n"
            "2. **Identify the Hard Part** — What concept is tricky? Simplify it with an analogy\n"
            "3. **Real-world connection** — How does this concept appear in real life?\n"
            "4. **Exam angle** — What does NEET actually ask about this? (key facts, common traps)\n\n"
            "No complex sentences. If a technical term must be used, immediately define it simply."
        ),
    },

    "active_recall": {
        "system": (
            "You are a NEET exam coach who builds active recall sessions. "
            "Your questions are high-yield, exam-pattern aligned, and force deep retrieval. "
            "You follow the 'pause and answer' model — question first, answer revealed after."
        ),
        "user": (
            "Create an active recall session for '{section}' from '{chapter}' for a NEET student.\n\n"
            "Topic content:\n{content}\n\n"
            "Generate 6-8 active recall questions following this format:\n\n"
            "**Q1:** [Question — make the student think, not just recall]\n"
            "▶ **Answer:** [Precise NEET-level answer]\n\n"
            "Question types to mix:\n"
            "- Fill in the blank (for key terms/numbers)\n"
            "- Process questions (What happens next?)\n"
            "- Why/How questions (for understanding)\n"
            "- NEET trap questions (common misconceptions)\n\n"
            "Cover all high-yield facts from the topic. Difficulty should progress from basic to advanced."
        ),
    },

    "mind_map": {
        "system": (
            "You are a NEET preparation expert who creates structured, hierarchical mind maps "
            "for visual learners. Your mind maps capture all key relationships, sub-concepts, "
            "and connections in a topic for quick revision and big-picture understanding."
        ),
        "user": (
            "Create a detailed text mind map for '{section}' from '{chapter}' for NEET revision.\n\n"
            "Topic content:\n{content}\n\n"
            "Format strictly as:\n"
            "🧠 **[CENTRAL TOPIC]**\n"
            "├── **Branch 1: [Main concept]**\n"
            "│   ├── Sub-point 1\n"
            "│   ├── Sub-point 2\n"
            "│   └── Sub-point 3\n"
            "├── **Branch 2: [Main concept]**\n"
            "│   └── ...\n"
            "└── **Branch N: [Main concept]**\n\n"
            "Rules:\n"
            "- Every important concept from the topic must appear\n"
            "- Include key numbers, names, and NEET-important facts as sub-points\n"
            "- Group related concepts logically under the same branch\n"
            "- End with a **Key Connections** section showing how branches relate"
        ),
    },

    "flowchart": {
        "system": (
            "You are a NEET expert who explains biological processes, chemical reactions, and "
            "physical mechanisms through clear, exam-focused flowcharts. "
            "Your flowcharts are step-by-step, show decision points, and highlight NEET-important steps."
        ),
        "user": (
            "Create a detailed flowchart for '{section}' from '{chapter}' for a NEET student.\n\n"
            "Topic content:\n{content}\n\n"
            "Use this format:\n"
            "[ Step 1: Description ]\n"
            "        ↓\n"
            "[ Step 2: Description ]\n"
            "        ↓\n"
            "◆ Decision point? → YES → [ Step A ] / NO → [ Step B ]\n"
            "        ↓\n"
            "[ Final outcome ]\n\n"
            "Rules:\n"
            "- Capture the complete process from start to end\n"
            "- Mark NEET-important steps with ⭐\n"
            "- Add brief notes in (parentheses) for key facts at each step\n"
            "- If there are multiple processes, create separate flowcharts for each"
        ),
    },

    "infographic": {
        "system": (
            "You are a NEET preparation expert who creates dense, high-yield infographic-style "
            "summaries for fast last-minute revision. Your summaries are scannable, fact-packed, "
            "and organized by importance — most critical facts first."
        ),
        "user": (
            "Create an infographic-style summary of '{section}' from '{chapter}' for NEET revision.\n\n"
            "Topic content:\n{content}\n\n"
            "Structure it as:\n\n"
            "## ⚡ Quick Facts\n"
            "- [Most important fact for NEET]\n"
            "- [Key number/value/formula]\n"
            "- ...\n\n"
            "## 📌 Must Remember\n"
            "| Term | Meaning/Value |\n"
            "|------|---------------|\n"
            "| ... | ... |\n\n"
            "## 🔁 Key Processes\n"
            "1. [Process name]: [one-line description]\n\n"
            "## ⚠️ Common NEET Traps\n"
            "- [Misconception → Correct fact]\n\n"
            "## 🎯 Previous Year Focus\n"
            "- [What NEET has asked from this topic]\n\n"
            "Be dense, use bold for key terms, and prioritize high-yield content."
        ),
    },
}

# ── Mind Map JSON ─────────────────────────────────────────────────────────────

_MIND_MAP_JSON_SYSTEM = (
    "You are a NEET exam expert. Create structured mind map data for visual learning. "
    "Return ONLY valid JSON, no extra text, no markdown code fences."
)

_MIND_MAP_JSON_USER = """Create a visual mind map for NEET topic '{section}' from chapter '{chapter}'.

Topic content:
{content}

Return a JSON object with exactly this structure:
{{
  "center": "{section}",
  "branches": [
    {{
      "label": "Main concept name (2-4 words)",
      "children": [
        "Specific fact or process — concise, NEET-relevant",
        "Another key point with exact values or names"
      ]
    }}
  ]
}}

Rules:
- Create 4-6 main branches covering ALL key concepts in the topic
- Each branch: 2-5 children with specific NEET facts (numbers, names, processes)
- Each child: max 65 characters, factual and directly exam-relevant
- Branch labels: concise, 2-4 words max
- Cover everything important — classifications, processes, exceptions, values
- Return ONLY the JSON object, nothing else
"""


_INFOGRAPHIC_JSON_SYSTEM = (
    "You are a NEET exam expert. Create structured infographic data for visual learning. "
    "Return ONLY valid JSON, no extra text, no markdown code fences."
)

_INFOGRAPHIC_JSON_USER = """Create a visual infographic for NEET topic '{section}' from chapter '{chapter}'.

Topic content:
{content}

Return a JSON object with exactly this structure:
{{
  "title": "{section}",
  "sections": [
    {{
      "heading": "Quick Facts",
      "icon": "⚡",
      "color": "yellow",
      "type": "bullets",
      "items": ["fact 1", "fact 2", "fact 3"]
    }},
    {{
      "heading": "Must Remember",
      "icon": "📌",
      "color": "blue",
      "type": "pairs",
      "items": [["Term or Concept", "Value or Meaning"], ["Another term", "Its value"]]
    }},
    {{
      "heading": "Key Processes",
      "icon": "🔁",
      "color": "green",
      "type": "steps",
      "items": ["Step 1 description", "Step 2 description", "Step 3 description"]
    }},
    {{
      "heading": "NEET Traps",
      "icon": "⚠️",
      "color": "red",
      "type": "bullets",
      "items": ["Common misconception → correct fact"]
    }},
    {{
      "heading": "PYQ Focus",
      "icon": "🎯",
      "color": "purple",
      "type": "bullets",
      "items": ["What NEET has asked from this topic"]
    }}
  ]
}}

Rules:
- Quick Facts: 4-6 most important facts, each under 80 characters
- Must Remember: 4-8 key term/value pairs (classifications, values, exceptions)
- Key Processes: only include if topic has a process/sequence, else keep 1-2 items
- NEET Traps: 2-4 real misconceptions students make
- PYQ Focus: 2-4 specific things NEET has tested (e.g. "Which phylum has radial symmetry?")
- Return ONLY the JSON object, nothing else
"""


_FLOWCHART_JSON_SYSTEM = (
    "You are a NEET exam expert. Create structured flowchart data for visual learning. "
    "Return ONLY valid JSON, no extra text, no markdown code fences."
)

_FLOWCHART_JSON_USER = """Create a visual flowchart for NEET topic '{section}' from chapter '{chapter}'.

Topic content:
{content}

Return a JSON object with exactly this structure:
{{
  "title": "{section}",
  "steps": [
    {{"type": "start", "text": "Starting point name"}},
    {{"type": "process", "text": "Process description", "note": "Optional NEET fact", "star": false}},
    {{"type": "decision", "text": "Decision question?", "branches": [
      {{"badge": "YES", "text": "Outcome if yes", "note": ""}},
      {{"badge": "NO", "text": "Outcome if no", "note": ""}}
    ]}},
    {{"type": "end", "text": "Final outcome"}}
  ]
}}

Rules:
- start: exactly one step at the beginning
- process: main steps; set "star": true for NEET-critical steps; "note": short fact or value (empty string if none)
- decision: use for branching points; branches array must have exactly 2 items with badge ("YES"/"NO" or named labels) and text
- end: one or more final outcomes
- Include 6-12 total steps covering the complete process end-to-end
- Each text field: max 60 characters, concise and factual
- Return ONLY the JSON object, nothing else
"""


async def generate_flowchart_json(chapter: str, section: str, content: str) -> dict:
    client = _get_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _FLOWCHART_JSON_SYSTEM},
            {"role": "user", "content": _FLOWCHART_JSON_USER.format(
                section=section, chapter=chapter, content=content[:5000]
            )},
        ],
        temperature=0.3,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        raise ValueError("Failed to parse flowchart JSON from AI response")


async def generate_infographic_json(chapter: str, section: str, content: str) -> dict:
    client = _get_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _INFOGRAPHIC_JSON_SYSTEM},
            {"role": "user", "content": _INFOGRAPHIC_JSON_USER.format(
                section=section, chapter=chapter, content=content[:5000]
            )},
        ],
        temperature=0.4,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        raise ValueError("Failed to parse infographic JSON from AI response")


async def generate_mind_map_json(chapter: str, section: str, content: str) -> dict:
    client = _get_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _MIND_MAP_JSON_SYSTEM},
            {"role": "user", "content": _MIND_MAP_JSON_USER.format(
                section=section, chapter=chapter, content=content[:5000]
            )},
        ],
        temperature=0.4,
        max_tokens=1000,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        raise ValueError("Failed to parse mind map JSON from AI response")


MECHANIC_LABELS = {
    "mnemonic": "Mnemonics",
    "story": "Story-Based",
    "chunking": "Chunking",
    "feynman": "Feynman",
    "active_recall": "Active Recall",
    "mind_map": "Mind Map",
    "flowchart": "Flowchart",
    "infographic": "Infographic",
}

# ── Generator ─────────────────────────────────────────────────────────────────

async def generate_mechanic(
    chapter: str,
    section: str,
    content: str,
    mechanic: str,
) -> dict:
    if mechanic not in _PROMPTS:
        raise ValueError(f"Unknown mechanic: {mechanic}. Choose from: {list(_PROMPTS.keys())}")

    prompt = _PROMPTS[mechanic]
    user_message = prompt["user"].format(
        chapter=chapter,
        section=section,
        content=content[:6000],   # cap to stay within token limits
    )

    client = _get_client()
    async with _get_semaphore():
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1200,
        )

    return {
        "mechanic":      mechanic,
        "mechanic_label": MECHANIC_LABELS[mechanic],
        "chapter":       chapter,
        "section":       section,
        "result":        (response.choices[0].message.content or "").strip(),
    }
