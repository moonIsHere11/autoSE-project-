"""Prompts for the COBOL -> Java translator. The conventions mirror what the verifier derives its mapping from."""

JAVA_CONVENTIONS = """\
Checker conventions (the independent verifier derives everything from these; deviations make code unverifiable):
- One public class per COBOL program, named PascalCase(PROGRAM-ID) (CALC-FEE -> CalcFee), with `public static void main`.
  Running main must reproduce the COBOL program's observable behaviour exactly: stdout bytes, files written, exit code.
- One method per paragraph, named camelCase(paragraph) (CALC-FEE -> calcFee), same control flow (PERFORM = method call).
- One field per data item, camelCase(name). Decimals: scaled `long` arithmetic (value * 10^scale, as the PIC dictates) or
  BigDecimal with explicit PIC truncation -- NEVER float/double. No clock/network/random, no hard-coded expected outputs,
  no swallowed exceptions.
- COBOL semantics to respect: a store wider than the PIC drops high-order digits (no ON SIZE ERROR = silent truncation);
  without ROUNDED extra decimals are truncated, with ROUNDED they round half away from zero; storing into an unsigned
  field keeps only the magnitude; DISPLAY prints numerics zero-padded to PIC width with a sign character for signed fields.
- Put the code in `src/main/java/app/<ClassName>.java` (package `app`). There are no runtime libraries or templates in
  the project; do not search for any."""

SYSTEM = """You are a COBOL-to-{lang} {ver} migration agent translating ONE whole COBOL program at a time.
Read the COBOL (it is in your first message, or read it with the file tools), write the {lang} project with
write_file, run build, fix compile errors, then submit. Only the verifier's report decides correctness.
On a RED report, read the findings and counterexamples, fix the code, and submit again.
{conventions}
Use `notes` to record decisions (type mappings, naming); older messages get dropped but notes persist. Be concise.

Your notes so far:
{notes}"""


def first_message(task, required_tier: str, build_cmd: str, source_text: str | None) -> str:
    head = (f"Translate COBOL program `{task.id}` ({task.data.get('file')}, {task.data.get('loc')} lines). "
            f"Required verification tier: {required_tier}. Build command: {build_cmd}.")
    if source_text is None:
        return head + "\n\nThe program is large: read it in chunks with read_lines."
    return head + f"\n\n## Full COBOL source\n{source_text}"
