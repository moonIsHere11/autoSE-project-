# extras: what the COBOL -> Java translator uses on top of the harness

`cobol_java/` is a `harness.types.Profile`:
- `profile.py`: tasks = one per COBOL program (any source file with a PROCEDURE DIVISION; copybooks are skipped),
  prompts, and the tool packs. No static analysis, planning or knowledge base: the agent reads the COBOL itself.
- `prompts.py`: system prompt and the Java conventions the verifier's mapping relies on (class/method/field naming,
  scaled-long or BigDecimal decimals, COBOL truncation/rounding/sign rules, DISPLAY format).
- `tools.py`: `FilesPack` (list_files, read_file, read_lines, search, write_file; COBOL source is read-only) and
  `BuildPack` (build, runs `target.build_cmd` in staging).

To target another language or domain, write a new profile package and point `harness.profile.adapter` at it.
