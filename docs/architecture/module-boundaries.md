# Module Boundaries

Core modules may depend on `kernel`.
`integrations` may implement public core contracts.
Core modules must never import integrations.

This keeps Portkey, Hatchet, Serena, River, Promptfoo, OpenLIT, E2B, MCP, and future replacements
from becoming cognitive-architecture dependencies.
