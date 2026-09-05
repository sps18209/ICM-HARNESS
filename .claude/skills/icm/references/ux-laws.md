# UX laws — actionable directives

Consult this when building or reviewing **any user interface, screen, flow, or
frontend**. These are heuristics, not gates: apply the ones that fit the change,
and don't force all twenty onto a small tweak. Each law is stated as the concrete
thing to *do*.

## Choice & cognitive load — keep the screen light

- **Hick's law** — *Reduce choices per screen.* More options means slower
  decisions; show fewer, or stage them.
- **Miller's law** — *Break content into chunks* (roughly 5–9 items); group and
  paginate rather than dumping long lists.
- **Law of Prägnanz** — *Simplify complex interfaces.* People read the simplest
  form they can; prefer the plainest clear layout.
- **Tesler's law (conservation of complexity)** — Some complexity is irreducible.
  *Use sensible defaults* and absorb that complexity for the user instead of
  exposing it; *reveal complexity gradually* (progressive disclosure).
- **Occam's razor** — Remove the non-essential; the simplest solution that works
  wins.

## Targets & the primary action — make the right thing easy to hit

- **Fitts's law** — *Make targets large.* Time-to-hit grows as targets shrink or
  recede.
- **Minimize target distance** — *Place key actions nearby*, close to where the
  eye or cursor already is.
- **Von Restorff (isolation) effect** — *Highlight the primary action* so the one
  thing you want them to do visibly stands out.

## Memory & the shape of a flow — first, last, and the peak

- **Serial position effect** — *Put essentials first* (and last); the middle is
  what gets forgotten.
- **Peak-end rule** — *End flows memorably.* People judge an experience by its
  most intense moment and its ending — design both.
- **Zeigarnik effect** — *Show visible progress.* Unfinished tasks stay on the
  mind; progress bars, steppers, and checklists use this.
- **Goal-gradient effect** — *Make completion feel closer* as they near the end
  (e.g. a progress meter that starts partly filled).

## Grouping & perception (Gestalt) — show what belongs together

- **Law of proximity** — *Group related information* by placing it close together.
- **Law of similarity** — *Maintain pattern consistency*; elements that look alike
  are read as related, so make related things look alike (and unrelated things
  differ).
- **Uniform connectedness** — *Connect related elements visually* with a shared
  container, background, or connecting line — the strongest grouping signal.

## Familiarity & consistency — don't make them relearn

- **Jakob's law** — *Follow familiar patterns.* Users spend most of their time on
  other products and expect yours to work the same way.

## Speed & responsiveness — stay under the attention threshold

- **Doherty threshold** — *Keep interactions within ~400 ms.* Feedback faster than
  that keeps attention and productivity high; when work takes longer, show
  immediate progress feedback.

## Robustness & errors — be forgiving

- **Postel's law (robustness)** — Be liberal in what you accept and conservative
  in what you do: *prevent errors proactively* (constrain inputs, good defaults,
  confirmation on destructive actions) and *make errors recoverable* (undo, clear
  messages, no dead ends).

## Scope & effort — protect the flow

- **Parkinson's law** — Work expands to fill the time allowed; *reduce task
  completion time* by setting tight, explicit limits (fewer fields, defaults,
  deadlines) so a task can't sprawl.
- **Pareto principle (80/20)** — ~80% of the value comes from ~20% of the surface;
  prioritize the vital few interactions and polish those first.

---

### Quick review checklist

When reviewing a screen or flow, ask:

1. Are there fewer choices than a person can weigh at a glance? (Hick, Miller)
2. Is the primary action large, close, and visually obvious? (Fitts, Von Restorff)
3. Does related content sit together and look alike? (proximity, similarity,
   uniform connectedness)
4. Does it behave like the tools users already know? (Jakob)
5. Does every interaction give feedback within ~400 ms? (Doherty)
6. Is progress visible, and does the finish feel close and memorable? (Zeigarnik,
   goal-gradient, peak-end)
7. Are errors hard to make and easy to undo? (Postel)
8. Is anything here removable without losing value? (Occam, Pareto, Prägnanz)
