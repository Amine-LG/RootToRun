# Teaching standard

How lessons in this course teach, and the rules an author or reviewer applies to every step. Rules marked
**(research)** follow from published learning research (worked examples, retrieval practice, spacing, feedback);
the rest are design decisions, and their numbers are starting points to revise once real learners have used the lessons.
`scripts/teach_lint.py` checks the rules that a program can check.

## The teacher we are imitating

Picture a patient, competent engineer sitting next to a colleague who is new to the subject. They:

1. start from something the colleague already understands, or from a small problem worth solving;
2. explain **one** idea, in plain words, then show it working on a real machine;
3. point at the part of the output that matters, and say what it means;
4. hand over the keyboard for a small, safe task, and help with the specific mistake if it goes wrong;
5. ask a short question that only someone who understood would get right, and explain the answer either way;
6. move on once it has landed, saying how the next idea connects to this one;
7. at the end, say what the colleague can now do, and what that will be useful for.

They never show off an edge case before the main case is solid, never use a word they have not explained, and never
make the colleague read three screens before doing anything.

## Lesson anatomy

A lesson is a **flow** of small typed steps (`flow:` in the lesson YAML; the schema is in
`backend/academy/curriculum.py`):

| Step | Use it to | Notes |
|---|---|---|
| `teach` | explain one idea | a `title` starts a new part (listed in the lesson outline) |
| `show` | demonstrate: a **recorded** command and its real output (`run`), or a file or manifest (`code`) | `highlight` emphasises output lines; `notice` says what to look at |
| `try` | let the learner type a command | compared with `accept` after normalising spaces; nothing runs; `hints` answer the real mistakes; `run` shows the recorded output afterwards |
| `ask` | a question with a reason to exist | 2 to 4 choices, each with a `why`; `guess: true` makes it an unscored prediction answered by the next steps |
| `order` | put the steps of a procedure in order | for procedures and request paths, not for lists without a real order |
| `reflect` | say it in your own words, then compare with a model answer | never scored |

A typical lesson moves through this rhythm a few times:

```
situation or question → teach (one idea) → show (real output) → notice → try or ask → feedback → next idea
```

It opens with a situation the learner can picture, not a definition. It closes with a `teach` step titled
"What you can do now" that names the new abilities and the next lesson, and says honestly how this connects to
the course's destination.

Depth that most learners do not need (edge cases, version history, every flag) goes into `sections` with
`depth: true`, shown under "Go deeper", or into a later lesson. It does not go into the main flow.

## Rules

### Size and pace
1. **One new idea per step**, and about three new terms at most in a step; a fourth means the step should be split
   **(research: small steps, cognitive load)**.
2. A `teach` step is short: about 180 words at most. If it needs more, it is two ideas.
3. No more than four steps in a row without something for the learner to do (`try`, `ask`, `order`)
   **(research: frequent checks, active practice)**.
4. Lessons are as long as the idea needs. Ten to twenty minutes is typical, and a subject that needs more becomes
   several connected lessons, not one long one.

### Vocabulary and prerequisites
5. **Every term is explained in the step where it first appears**, in one sentence, unless an earlier lesson on
   the learner's path taught it. A glossary link is not a substitute.
6. A lesson may only rely on tools and terms from lessons before it on its track, or on its declared
   prerequisites. Mentioning something taught later is allowed only as a one-line, clearly labelled pointer ("you
   will meet this again in…"), never as part of an explanation or a question.
7. Each track teaches its own subject first. Linux lessons use Linux tools. Container lessons use Podman (with
   Docker differences where they matter). Kubernetes lessons use `kubectl`. OpenShift lessons use `oc` after the
   bridge lesson has explained how `oc` relates to `kubectl`.

### Commands and output
8. **A command, its real output and its explanation appear together** **(research: contiguity, signalling)**. No
   block of "the recorded commands" at the end of a lesson.
9. Output is never invented. A `show` with `run` shows what was recorded; a `code` step shows a file or manifest,
   not a fake terminal session.
10. Recording environment and taught command must match. A `kubectl` lesson shows output recorded with `kubectl`.
    If only an `oc` recording exists, the lesson says so ("recorded with `oc`, OpenShift's client; `kubectl get pods`
    prints the same table") and never relabels the command.
11. Point at the part of the output that matters (`highlight`, `notice`). Do not explain every column at once; say
    which ones can be ignored for now.

### Practice
12. Practice follows demonstration: the learner sees a command work before being asked to type it, and later tasks
    remove that support (a similar task, then a new one) **(research: worked examples, fading)**.
13. `try` hints are written for the mistakes people really make (a leading `/`, the wrong case, the wrong order,
    a missing argument), and each hint explains the model, not just the fix.
14. "Show me" is always available after one attempt. Struggling briefly helps; being stuck does not.

### Questions
15. Every question has a job: predict an outcome, read output, choose an action, find a cause, or transfer an idea
    to a new situation. A question that repeats a sentence from the lesson is deleted.
16. Stems are short: one idea, about 25 words at most, positively phrased. The difficulty must come from the
    technical idea, not from the English **(research: item-writing guidelines)**.
17. Three options by default; a fourth only for a distinct, real misconception **(research)**.
18. Options are parallel in length, form and precision. **The right answer must not be the longest or most hedged**
    **(research)**. No "all of the above".
19. Every wrong option is a real misconception, and its `why` names that misconception and corrects the model in
    one to three sentences. The right option's `why` says why it is right in one sentence, without restating the
    question or starting with "Yes" or "Right" (the interface already says so).
20. Prefer evidence in the question (`evidence:` holds output or a manifest) over describing output in words.
21. A prediction (`guess: true`) is asked only where a learner can reasonably guess, and the following steps reveal
    the answer. Do not ask beginners to predict something they have no basis for.

### Voice
22. Write the way a good teacher talks: second person, complete sentences, concrete examples, one idea per
    paragraph. Precise technical words, defined once.
23. No teasers, slogans or announcements ("The fix is one word, but only if you can see it"). Show the thing.
24. No "just", "simply", "obviously", "easy", "of course" or "as you know". No exclamation marks, no artificial
    excitement, no motivational clichés.
25. Analogies are welcome when they carry the idea, and each one says where it stops being true
    **(research: analogies)**.
26. Parentheses are for short glosses ("`pwd` (print working directory)"), not for a second idea.

### Closing and connection
27. Each lesson ends by naming what the learner can now do, and how the next lesson builds on it.
28. When a later lesson depends on an earlier one, it says so where the dependency appears, with a link, and
    briefly reminds the learner of the idea **(research: prior knowledge, retrieval)**.
29. Review cards ask for what matters most (a command, a mechanism, a distinction). They are what spaced review
    will bring back **(research: retrieval practice, spacing)**.

## Learners who already know some of it

- Every lesson offers "Know this already? Answer the checks". All right means the reading can be skipped; any miss
  links to the exact step that teaches it.
- Each territory has a diagnostic that marks lessons as study, review or known.
- An experienced learner gets the same accurate lessons. They move faster through them; they do not get a
  different, terser version **(research: expertise reversal, handled by skipping rather than by rewriting)**.

## Before and after, one example

Before (`lx.shell-basics`, minute 2 of the second lesson):

> The shell finds the command in one of two places. **Builtins** such as `cd`, `echo` and `export` are part of the
> shell itself. Everything else is a **file**, searched in the directories listed in `$PATH`, in order. `type`
> tells you which: `cd is a shell builtin`, `ls is /usr/bin/ls`. This matters because `cd` can only be a builtin:
> a separate program could change only its own directory, never the shell's.

Five new ideas in five sentences (builtins, files, `$PATH`, search order, `type`), one of them a subtle argument,
with no output shown and nothing to do.

After: one step asks where `ls` actually lives, shows `type ls` with its real output, and points at `/usr/bin/ls`.
The next step asks the learner to guess what `type cd` says, then shows that `cd` is part of the shell itself. Why
it must be is a depth note. `$PATH` gets its own lesson later, when it is needed.

## Reviewing a lesson

Read it as the learner will, from the start of the track, and ask:
- Does it start where this learner is, with something they can picture?
- Is every term explained before or where it is used?
- Is each step one idea? Is there something to do at least every few steps?
- Is every example real, and does it help?
- Are the questions short, with a reason to exist, and options that do not give the answer away?
- Does each `why` teach something?
- Does the learner know what they can now do, and why it matters for what comes next?
- Are Linux, Podman, `kubectl` and `oc` each used where they belong, and is any recording difference stated?

Then run `scripts/teach_lint.py <lesson-id>` and resolve or justify what it reports.
